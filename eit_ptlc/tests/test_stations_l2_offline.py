"""四工位统一 L2 端到端离线测试 (HTTP)
=======================================
功能:
    验证 Sampling/Collect/Develop/PhotoScrape 四工位的 L2 动作目录与 operation 脚本均可经
    HTTP (VM 运行 API) 在 sim (Mock PLC 全工位 L2 FSM) 下跑通; 含带参动作 (develop.fill 目标缸)
    与必填缺失拒绝.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_stations_l2_offline
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app

_REPO = Path(__file__).resolve().parents[2]
# 预置底图 (与 app.yaml camera.test_before_image 同一张): 双帧视觉分析强制要有效 before 图
_BEFORE_IMG = _REPO / "data" / "samples" / "case1" / "before.jpg"


def _run_script(client, name, mode="RUN", tries=600):
    """经 VM 运行 API 跑一个脚本至终态; 返回 (终态 state, run_id)."""
    r = client.post(f"/api/scripts/{name}/debug/run",
                    json={"inputs": {}, "mode": mode, "mode_run": "run"}).json()
    run_id = r["run_id"]
    for _ in range(tries):
        st = client.get(f"/api/debug/{run_id}/state").json()
        if st["status"] in ("DONE", "ERROR", "KILLED"):
            return st, run_id
        time.sleep(0.05)
    return client.get(f"/api/debug/{run_id}/state").json(), run_id


def _run_photoscrape_full(client, tries=900):
    """拍照刮板完整 happy-path (mock, 不上实机): 供齐输入 + 自动喂掉两个人工步, 跑到终态。

    photoscrape_full 与无输入脚本不同 — 它需要 save_dir/before_path/sample_id, 且含
    选带(input)+参数确认(confirm)两个 op:human。本助手用临时目录 + 预置底图填输入,
    经 /debug/{run}/human/{req} 应答: 选带从 vis.band_ids 取真实条带(vision.mock=false,
    条带名非固定, 不能写死 band_01), confirm 给非 cancel 的 choice。
    """
    save_dir = tempfile.mkdtemp(prefix="ptlc_photoscrape_")
    r = client.post("/api/scripts/photoscrape_full/debug/run",
                    json={"inputs": {"sample_id": "TEST-PS-001", "save_dir": save_dir,
                                     "before_path": str(_BEFORE_IMG)},
                          "mode": "RUN", "mode_run": "run"}).json()
    run_id = r["run_id"]
    answered: set[str] = set()
    for _ in range(tries):
        st = client.get(f"/api/debug/{run_id}/state").json()
        if st["status"] in ("DONE", "ERROR", "KILLED"):
            return st, run_id
        if st["status"] == "WAITING_HUMAN":
            events = client.get(f"/api/runs/{run_id}").json().get("events", [])
            req = next((e for e in reversed(events)
                        if e.get("type") == "vm_human_request" and e.get("req_id") not in answered), None)
            if req is None:
                time.sleep(0.05)
                continue
            if req.get("kind") == "input":          # 选带: 取分析出的真实第一条带
                vs = client.get(f"/api/debug/{run_id}/vars").json().get("vars", {})
                bands = (vs.get("vis") or {}).get("band_ids") or ["band_01"]
                payload = {"values": {"band_id": bands[0]}}
            else:                                    # confirm: 任意非 cancel 即放行
                payload = {"choice": "ok"}
            client.post(f"/api/debug/{run_id}/human/{req['req_id']}", json=payload)
            answered.add(req["req_id"])
            continue
        time.sleep(0.05)
    return client.get(f"/api/debug/{run_id}/state").json(), run_id


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48493/eit_ptlc/sim/")
    with TestClient(app) as client:
        # 四工位动作目录齐全
        names = {a["name"] for a in client.get("/api/actions?kind=plc_l2").json()}
        need = {"sampling.init", "collect.collect", "develop.fill", "photoscrape.scrape", "feedlift.feed_raise"}
        check("catalog_all_stations", need <= names, str(sorted(need - names)))

        # 无输入工位 operation 脚本全程 DONE (含调用 action 子脚本的 develop_prep_tank1)
        for script in ("sampling_full", "collect_full", "develop_prep_tank1"):
            st, _ = _run_script(client, script)
            check(f"run_{script}", st["status"] == "DONE", str(st))

        # 拍照刮板完整流程 (交互式: 供齐输入 + 自动应答 选带/确认 两个人工步, 跑到 DONE)
        st, _ = _run_photoscrape_full(client)
        check("run_photoscrape_full", st["status"] == "DONE", str(st))

        # 带参动作: develop.fill 指定目标缸 (泵动作语义参数 target_tank, 执行器翻译为泵指令)
        r = client.post("/api/actions/develop.fill/run",
                        json={"params": {"target_tank": 3}, "mode": "RUN"}).json()
        check("develop_fill_param", r["status"] == "DONE", str(r))

        # 必填缺失 -> REJECTED
        r = client.post("/api/actions/develop.fill/run", json={"params": {}, "mode": "RUN"}).json()
        check("develop_fill_missing", r["status"] == "REJECTED" and r["reject_code"] == "INVALID_PARAM", str(r))

        # pTLC 全工位流程脚本 (跨四工位, 12 次设备调用: 含上样段 2 次真空泵开关)
        st, run_id = _run_script(client, "ptlc_full")
        run = client.get(f"/api/runs/{run_id}").json()
        call_done = sum(1 for e in run.get("events", [])
                        if e.get("type") == "vm_node_done" and e.get("op") == "call" and e.get("status") == "DONE")
        check("ptlc_full", st["status"] == "DONE" and call_done == 12, f"{st} call_done={call_done}")

    print(f"\n共 8 用例, 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
