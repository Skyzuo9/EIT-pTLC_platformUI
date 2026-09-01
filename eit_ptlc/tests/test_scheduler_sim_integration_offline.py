"""离线集成: 并行调度器全链 (create_sim_app + Mock PLC + 真 VM/资源门).

用 parallel_smoke 配方 (纯 PLC L2 + 人工门, 不依赖相机/视觉仿真) 验证官方文档阶段 6 判据:
    1. A 离开点样位后 B 才能进入 (B.sa.started >= A.sb.finished, station:sampling 互斥)
    2. 缸1/缸2 区间真实重叠: 两样品的段C (零资源人工门) 同时 WAITING_HUMAN, 且缸号不同
    3. 时间证据落 experiments.db (经 /api/experiments/{bid}/timeline 可查)
    4. HITL 经 /api/debug/{run_id}/human/{req_id} 逐门放行后批次 COMPLETED

隔离: monkeypatch bootstrap._DATA_DIR 到临时目录 —— runs/materials/experiments 三库
与 operation_history 全部不落真实 var/ (照 test_material_wired 的隔离原则)。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_scheduler_sim_integration_offline.py -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from fastapi.testclient import TestClient  # noqa: E402

from eit_ptlc.runtime import bootstrap  # noqa: E402
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider  # noqa: E402

_URL = "opc.tcp://127.0.0.1:48533/eit_ptlc/sim/"   # 独立端口, 避免与其他测试并跑冲突


def _wait(client: TestClient, pred, *, timeout=45.0, interval=0.2, desc=""):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = pred(client)
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"等待超时: {desc}; 最后观测 {last!r}")


class SchedulerSimIntegrationTest(unittest.TestCase):
    def test_two_samples_overlap_and_complete(self) -> None:
        prefix = f"IT{uuid.uuid4().hex[:6]}"
        with tempfile.TemporaryDirectory() as tmp:
            old_data_dir = bootstrap._DATA_DIR
            bootstrap._DATA_DIR = Path(tmp)
            try:
                app = bootstrap.create_sim_app(opcua_url=_URL)
                with TestClient(app) as client:
                    self._drive(client, prefix)
            finally:
                bootstrap._DATA_DIR = old_data_dir
                # 撤销装配注入的模块级泵参 provider, 防止污染同进程后续测试
                # (test_spot_end_position 等断言出厂默认; 实证于全量回归)
                set_pump_defaults_provider(None)

    def _drive(self, client: TestClient, prefix: str) -> None:
        # 配方可枚举且静态校验干净
        recipes = client.get("/api/recipes").json()["recipes"]
        self.assertIn("parallel_smoke", [r["name"] for r in recipes])
        ok = client.get("/api/recipes/parallel_smoke/validate").json()
        self.assertTrue(ok["ok"], f"冒烟配方校验失败: {ok['errors']}")

        # 提交 2 样品批 + 启动
        res = client.post("/api/experiments", json={
            "recipe": "parallel_smoke", "sample_count": 2, "id_prefix": prefix,
            "name": "sim 集成验收", "tank_subset": [1, 2]})
        self.assertEqual(res.status_code, 200, res.text)
        batch_id = res.json()["batch_id"]
        s1, s2 = res.json()["sample_ids"]
        self.assertEqual([s1, s2], [f"{prefix}-01", f"{prefix}-02"])
        self.assertEqual(client.post(f"/api/experiments/{batch_id}/start").status_code, 200)

        # 判据 2: 两样品的段C 同时 WAITING_HUMAN = 缸内等待真实重叠
        def _both_waiting(c):
            snap = c.get("/api/scheduler/snapshot").json()
            batch = next((b for b in snap["batches"] if b["batch_id"] == batch_id), None)
            if not batch:
                return None
            states = {s["sample_id"]: {j["flow_id"]: j["status"] for j in s["jobs"]}
                      for s in batch["samples"]}
            if (states.get(s1, {}).get("sc") == "WAITING_HUMAN"
                    and states.get(s2, {}).get("sc") == "WAITING_HUMAN"):
                return batch
            return None

        batch = _wait(client, _both_waiting, desc="两样品段C同时等待人工门 (重叠)")
        tanks = {s["sample_id"]: s["tank"] for s in batch["samples"]}
        self.assertEqual(sorted(tanks.values()), [1, 2], f"两样品应分占两缸: {tanks}")

        # 判据 1 + 3: 时间证据 —— B 的段A 起跑不早于 A 的段B (离开点样位) 完成
        timeline = client.get(f"/api/experiments/{batch_id}/timeline").json()["jobs"]
        by_key = {(j["sample_id"], j["flow_id"]): j for j in timeline}
        a_sb, b_sa = by_key[(s1, "sb")], by_key[(s2, "sa")]
        self.assertIsNotNone(a_sb["finished_at"])
        self.assertGreaterEqual(
            b_sa["started_at"], a_sb["finished_at"] - 0.05,
            "B 必须等 A 离开点样位 (A.sb 完成) 后才进入点样")
        # 重叠的区间证据: 两个 sc 都已开跑且都未结束
        for sid in (s1, s2):
            row = by_key[(sid, "sc")]
            self.assertIsNotNone(row["started_at"])
            self.assertIsNone(row["finished_at"])

        # 判据 4: 逐门放行 (经现有 HITL 通道), 批次收口 COMPLETED
        def _pending_gates(c):
            runs = c.get("/api/debug/active").json()["runs"]
            gates = [(r["run_id"], r["pending_human"]["req_id"]) for r in runs
                     if r.get("pending_human")]
            return gates or None

        for _ in range(2):
            gates = _wait(client, _pending_gates, desc="待回复的人工门")
            run_id, req_id = gates[0]
            reply = client.post(f"/api/debug/{run_id}/human/{req_id}",
                                json={"choice": "ok"})
            self.assertEqual(reply.status_code, 200, reply.text)
            time.sleep(0.2)

        def _completed(c):
            detail = c.get(f"/api/experiments/{batch_id}").json()
            return detail if detail["status"] == "COMPLETED" else None

        detail = _wait(client, _completed, desc="批次 COMPLETED")
        self.assertTrue(all(s["status"] == "DONE" for s in detail["samples"]))
        # 结果查询面可用 (冒烟配方无视觉段, 结果为空但端点可用)
        self.assertEqual(
            client.get(f"/api/experiments/{batch_id}/results").status_code, 200)
        events = client.get(f"/api/experiments/{batch_id}/events").json()["events"]
        self.assertTrue(any(e["type"] == "batch_completed" for e in events))


if __name__ == "__main__":
    unittest.main()
