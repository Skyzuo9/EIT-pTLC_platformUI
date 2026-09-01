"""离线: FlowScheduler 纯逻辑测试 (FakeVm, 不起真 VM/PLC).

用真配置 (parallel_v1 配方 + 真脚本索引 + 真动作表 + 真资源表) 驱动调度器, VM 层用可控
Future 桩替代 —— 验证的是调度决策本身:

    1. 流水线次序与资源全取或全不取 (两样品 s1 抢 robot 只放行一个)
    2. s3 缸预备与 s2 点样真并行; 双样品 s6 展开等待真重叠 (8 缸并行)
    3. 缸池分配 (s3 派发注入 tank) 与出缸段 (s8) 释放
    4. 停放位容量: 刮板台被占时他样品的进台段等待 (no_slot)
    5. scrape-holder 占位账: s7 DONE 占用, s10 DONE 释放, 期间他样品 s7 等待
    6. WIP 上限; 失败隔离 (A 失败 HOLD, B 继续); 断点续跑 (start_aid + vars 回注)
    7. 重启恢复: 在飞段 INTERRUPTED + 批 PAUSED + 禁自动重派 + reconcile 后可恢复

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_scheduler_offline.py -v
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.operation.resources import load_resource_specs  # noqa: E402
from eit_ptlc.operation.scheduler import FlowScheduler, SubmitError  # noqa: E402
from eit_ptlc.runtime.experiment_store import ExperimentStore  # noqa: E402
from eit_ptlc.runtime.material_store import MaterialStore, load_bindings, load_topology  # noqa: E402

_CFG = _PKG / "config"
_OP_DIR = _CFG / "operation"


def _script_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in _OP_DIR.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("name"):
            index[doc["name"]] = doc
    return index


_INDEX = _script_index()
_REGISTRY = ActionRegistry.load(_CFG / "actions")
_MODES = {rid: s.mode for rid, s in load_resource_specs(_CFG / "resources.yaml").items()}


class FakeVm:
    """可控终态的 VM 桩: start 记账, wait_final 等测试 finish()."""

    def __init__(self) -> None:
        self.started: list[dict] = []
        self._futures: dict[str, asyncio.Future] = {}
        self._vars: dict[str, dict] = {}

    async def start(self, doc, inputs=None, *, mode_run="run", run_id=None,
                    start_aid=None, overrides=None, meta=None, preset_vars=None):
        self.started.append({"run_id": run_id, "script": doc.get("name"),
                             "inputs": dict(inputs or {}), "start_aid": start_aid,
                             "overrides": dict(overrides or {}),
                             "preset_vars": dict(preset_vars or {}),
                             "meta": dict(meta or {})})
        self._futures[run_id] = asyncio.get_event_loop().create_future()
        return {"run_id": run_id, "status": "RUNNING", "current_aid": None}

    async def wait_final(self, run_id, *, timeout=None):
        return await self._futures[run_id]

    def vars(self, run_id):
        return {"run_id": run_id, "vars": self._vars.get(run_id, {})}

    def finish(self, run_id, status="DONE", *, variables=None, aid="", script=""):
        self._vars[run_id] = variables or {}
        self._futures[run_id].set_result(
            {"run_id": run_id, "status": status, "current_aid": aid, "script": script})

    def running(self) -> list[str]:
        return [rid for rid, f in self._futures.items() if not f.done()]


class FakeGate:
    def locked(self, name):
        return False

    def snapshot(self):
        return {}


def _materials(fresh_collectors=4, fresh_bottles=4) -> MaterialStore:
    topology = load_topology(_CFG / "material_topology.yaml")
    bindings = load_bindings(_CFG / "material_bindings.yaml", topology)
    store = MaterialStore(":memory:", topology=topology, bindings=bindings)
    for i in range(fresh_collectors):
        store.mark("collector", 1 + i // 6, 1 + i % 6, "FRESH")
    for i in range(fresh_bottles):
        store.mark("bottle", 1 + i // 6, 1 + i % 6, "FRESH")
    return store


class _Harness:
    """一套完整的调度器测试台 (不起派发循环, 手动 _pass 保确定性)."""

    def __init__(self, *, wip=3, tanks=(1, 2, 3)) -> None:
        self.vm = FakeVm()
        self.exp = ExperimentStore(":memory:")
        self.materials = _materials()
        self.sched = FlowScheduler(
            vm=self.vm, res_gate=FakeGate(), resolve_script=lambda n: _INDEX[n],
            material_store=self.materials, experiment_store=self.exp,
            registry=_REGISTRY, resource_modes=_MODES,
            recipes_dir=_CFG / "recipes", wip_limit=wip, tank_pool=tanks)

    async def submit_and_start(self, count=2, prefix="T", **kw) -> dict:
        res = await self.sched.submit_batch({"sample_count": count, "id_prefix": prefix, **kw})
        await self.sched.batch_start(res["batch_id"])
        return res

    async def step(self, rounds=6) -> None:
        """跑若干轮派发 + 让 tracker 收口 (无在飞 future 变化即稳态)."""
        for _ in range(rounds):
            await self.sched._pass()
            for _ in range(4):
                await asyncio.sleep(0)

    async def run_until(self, run_id, *, max_rounds=30) -> bool:
        """反复派发直到某段进入运行 (对派发次序不敏感的推进方式)."""
        for _ in range(max_rounds):
            if run_id in self.vm.running():
                return True
            await self.step(1)
        return False

    async def advance(self, run_id, **finish_kw) -> None:
        """推进到某段开跑并立即完成它."""
        ok = await self.run_until(run_id)
        assert ok, f"{run_id} 始终未被派发; running={self.vm.running()} " \
                   f"waits={self.sched._wait_reasons}"
        self.finish(run_id, **finish_kw)
        await self.step(1)

    def finish(self, run_id, **kw) -> None:
        self.vm.finish(run_id, **kw)

    def job(self, job_id) -> dict:
        return self.sched._store.get_job(job_id) or {}

    def sample(self, sid) -> dict:
        return self.sched._store.get_sample(sid) or {}

    def started_ids(self) -> list[str]:
        return [s["run_id"] for s in self.vm.started]


def _run(coro):
    return asyncio.run(coro)


class PipelineTest(unittest.TestCase):
    def test_af0_first_then_resource_exclusive_s1(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.step()
            # 首轮只派批级起手段 (s1 依赖它)
            self.assertEqual(h.started_ids(), [f"{bid}-af0"])
            h.finish(f"{bid}-af0")
            await h.step()
            # 两个样品的 s1 都就绪, 但都要 robot: 全取或全不取 -> 只放行 T-01
            self.assertIn("T-01-s1", h.started_ids())
            self.assertNotIn("T-02-s1", h.started_ids())
            self.assertEqual(h.job("T-02-s1")["status"], "PENDING")
            reason = h.sched._wait_reasons.get("T-02-s1") or {}
            self.assertEqual(reason.get("reason"), "waiting_resource")
            return h

        _run(main())

    def test_s2_s3_parallel_and_develop_overlap(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.advance(f"{bid}-af0")
            h.finish("T-01-s1") if await h.run_until("T-01-s1") else None
            await h.step()
            # s1 完成 -> 点样(s2, 占上样工位) 与 缸预备(s3, 占展开工位) 同时在跑 = 真并行
            running = set(h.vm.running())
            self.assertIn("T-01-s2", running)
            self.assertIn("T-01-s3", running)
            # T-02 的 s1 需要上样工位 (被 T-01-s2 占) -> 仍等待
            self.assertNotIn("T-02-s1", h.started_ids())
            # 缸已在 s3 派发时分配
            self.assertEqual(h.sample("T-01")["tank"], 1)
            # 推进 T-01: s4 (取板段, 占上样+机器人) 期间 T-02 仍进不了场 —— 物理正确
            h.finish("T-01-s2")
            h.finish("T-01-s3")
            await h.step()
            self.assertIn("T-01-s4", h.vm.running())
            self.assertNotIn("T-02-s1", h.started_ids(),
                             "s4 仍占上样工位与机器人, T-02 不得进场")
            await h.advance("T-01-s4",
                            variables={"before_path": {"value": "b.jpg", "type": "STRING"}})
            await h.advance("T-01-s5")
            # s5 后: s6 (零资源) 与 s7 (机器人备耗材) 并发; 机器人段策略序偏向后段 (s7 先)
            self.assertTrue(await h.run_until("T-01-s6"), "展开等待应已派发 (零资源)")
            await h.advance("T-01-s7",
                            variables={"collector_hole": {"value": 1, "type": "INT"},
                                       "bottle_hole": {"value": 1, "type": "INT"}})
            # s7 释放机器人后 T-02 进场, 一路推进到自己的展开等待
            await h.advance("T-02-s1")
            await h.advance("T-02-s2")
            await h.advance("T-02-s3")
            await h.advance("T-02-s4",
                            variables={"before_path": {"value": "b2.jpg", "type": "STRING"}})
            await h.advance("T-02-s5")
            self.assertTrue(await h.run_until("T-02-s6"))
            running = set(h.vm.running())
            self.assertIn("T-01-s6", running)
            self.assertIn("T-02-s6", running, "两个样品的展开等待必须真重叠 (8缸并行)")
            self.assertEqual(h.sample("T-02")["tank"], 2, "第二样品应分到另一缸")
            self.assertEqual(h.sample("T-01")["context"].get("before_path"), "b.jpg")
            return h

        _run(main())

    def test_tank_release_and_slot_capacity(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.advance(f"{bid}-af0")
            # 快进 T-01 到 s8 完成 (出缸, 板回刮板台)
            await h.advance("T-01-s1")
            await h.advance("T-01-s2")
            await h.advance("T-01-s3")
            await h.advance("T-01-s4",
                            variables={"before_path": {"value": "b", "type": "STRING"}})
            await h.advance("T-01-s5")
            self.assertEqual(h.sample("T-01")["position"], "tank:1")
            # 先收 s6 再收 s7: s7 释放机器人的那一轮, s8 (af8) 按策略序压过 T-02-s1 (af1)
            await h.advance("T-01-s6")
            await h.advance("T-01-s7",
                            variables={"collector_hole": {"value": 1, "type": "INT"},
                                       "bottle_hole": {"value": 1, "type": "INT"}})
            await h.advance("T-01-s8")
            self.assertEqual(h.sample("T-01")["position"], "scrape_table")
            self.assertIsNone(h.sched._tanks[1], "出缸段 DONE 后缸应回池")
            # T-02 推进到 s4 就绪, 但刮板台被 T-01 板占着 -> no_slot
            await h.advance("T-02-s1")
            await h.advance("T-02-s2")
            await h.advance("T-02-s3")
            await h.step(3)
            self.assertNotIn("T-02-s4", h.vm.running())
            wait = h.sched._wait_reasons.get("T-02-s4") or {}
            self.assertEqual(wait.get("reason"), "no_slot", f"实际: {wait}")
            return h

        _run(main())

    def test_scrape_holder_occupancy(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            # 直接用账本层验证占位: 人工标记 T-01 s7 完成 -> 占用; T-02 的 s7 就绪时应等
            await h.sched.job_skip(bid, "T-01", "s7", mark_done=True,
                                   context={"collector_hole": 1, "bottle_hole": 1})
            self.assertEqual(h.sched._occupancy.get("scrape-holder"), "T-01")
            await h.sched.job_skip(bid, "T-02", "s5", position="tank:2")  # 让 T-02 s7 依赖满足
            h.sched._store.update_sample("T-02", status="ACTIVE")
            await h.step()
            wait = h.sched._wait_reasons.get("T-02-s7") or {}
            self.assertEqual(wait.get("reason"), "occupancy", f"实际: {wait}")
            # T-01 s10 标记完成 -> 释放 -> T-02 s7 可派
            await h.sched.job_skip(bid, "T-01", "s9", mark_done=True)
            await h.sched.job_skip(bid, "T-01", "s10", mark_done=True)
            self.assertIsNone(h.sched._occupancy.get("scrape-holder"))
            return h

        _run(main())


class LimitAndFailureTest(unittest.TestCase):
    def test_wip_limit(self) -> None:
        async def main():
            h = _Harness(wip=1)
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            await h.step()
            h.finish("T-01-s1")
            await h.step()
            # WIP=1: T-01 在制, T-02 的 s1 即便 robot 空闲也不放行
            self.assertNotIn("T-02-s1", h.started_ids())
            wait = h.sched._wait_reasons.get("T-02-s1") or {}
            self.assertEqual(wait.get("reason"), "wip_limit")
            return h

        _run(main())

    def test_failure_isolation_and_resume(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(2)
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            await h.step()
            h.finish("T-01-s1")
            await h.step()
            # T-01 点样段失败 (retry: resume 段), 带断点与变量快照
            h.finish("T-01-s2", status="ERROR", aid="b/0/body/3", script="sampling_execute",
                     variables={"well": {"value": "A3", "type": "STRING"}})
            await h.step()
            job = h.job("T-01-s2")
            self.assertEqual(job["status"], "ERROR")
            self.assertEqual(job["failed_aid"], "b/0/body/3")
            self.assertEqual(h.sample("T-01")["status"], "HOLD", "失败样品应 HOLD")
            # 失败隔离的物理边界: T-01 的板仍停在点样座 -> T-02 的 s1 因停放位被占而等待
            # (这是正确行为: 板没挪走前不能再放一块), 调度器其余部分继续运转
            await h.step(2)
            wait = h.sched._wait_reasons.get("T-02-s1") or {}
            self.assertEqual(wait.get("reason"), "no_slot", f"实际: {wait}")
            # 断点续跑: 顶层边界取整 b/0, 变量回注
            await h.sched.job_resume(bid, "T-01", "s2")
            await h.step()
            resumed = [s for s in h.vm.started if s["run_id"] == "T-01-s2-r2"]
            self.assertEqual(len(resumed), 1, "续跑应铸新 run_id (-r2)")
            self.assertEqual(resumed[0]["start_aid"], "b/0")
            self.assertEqual(resumed[0]["preset_vars"].get("well"), "A3")
            self.assertEqual(h.sample("T-01")["status"], "ACTIVE")
            # T-01 续跑完成并一路让出机器人 (s4 挪板 -> s5 进缸 -> s6 空手 -> s7 备耗材)
            # 后, T-02 进场 -> 失败不拖垮流水线
            h.finish("T-01-s2-r2")
            await h.step()
            h.finish("T-01-s3") if "T-01-s3" in h.vm.running() else None
            await h.advance("T-01-s4",
                            variables={"before_path": {"value": "b", "type": "STRING"}})
            await h.advance("T-01-s5")
            self.assertTrue(await h.run_until("T-01-s6"))
            await h.advance("T-01-s7",
                            variables={"collector_hole": {"value": 1, "type": "INT"},
                                       "bottle_hole": {"value": 1, "type": "INT"}})
            self.assertTrue(await h.run_until("T-02-s1"),
                            "机器人链让出后 T-02 应恢复进场")
            return h

        _run(main())

    def test_manual_retry_needs_confirm(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(1, prefix="M")
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            await h.step()
            h.finish("M-01-s1", status="ERROR", aid="b/1", script="sampling_load")
            await h.step()
            with self.assertRaises(ValueError):
                await h.sched.job_retry(bid, "M-01", "s1")   # retry:manual 无 confirm 应拒
            await h.sched.job_retry(bid, "M-01", "s1", confirm=True)
            await h.step()
            self.assertIn("M-01-s1-r2", h.started_ids())
            return h

        _run(main())

    def test_sample_hold_at_boundary(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(1, prefix="H")
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            await h.step()
            await h.sched.sample_hold(bid, "H-01") if h.sample("H-01")["status"] == "ACTIVE" else None
            # s1 在跑时 hold: 跑完当前段后不派 s2/s3
            self.assertEqual(h.sample("H-01")["status"], "HOLD")
            h.finish("H-01-s1")
            await h.step()
            self.assertNotIn("H-01-s2", h.started_ids())
            self.assertNotIn("H-01-s3", h.started_ids())
            await h.sched.sample_resume(bid, "H-01")
            await h.step()
            self.assertIn("H-01-s2", h.started_ids())
            return h

        _run(main())


class SubmitAndRestartTest(unittest.TestCase):
    def test_submit_validations(self) -> None:
        async def main():
            h = _Harness()
            with self.assertRaises(SubmitError):
                await h.sched.submit_batch({"sample_count": 0, "id_prefix": "X"})
            with self.assertRaises(SubmitError):
                await h.sched.submit_batch({"sample_count": 1, "id_prefix": "坏 前缀"})
            with self.assertRaises(SubmitError):
                await h.sched.submit_batch({"sample_count": 1, "id_prefix": "X",
                                            "params": {"no_such_knob": 1}})
            # 耗材不足: 只有 4 件, 5 个样品应拒收且回滚预留
            with self.assertRaises(SubmitError):
                await h.sched.submit_batch({"sample_count": 5, "id_prefix": "N"})
            self.assertEqual(h.materials.reserved_summary(), {}, "拒收后预留应全回滚")
            res = await h.sched.submit_batch({"sample_count": 2, "id_prefix": "OK"})
            self.assertEqual(res["sample_ids"], ["OK-01", "OK-02"])
            with self.assertRaises(SubmitError) as ctx:
                await h.sched.submit_batch({"sample_count": 2, "id_prefix": "OK"})
            self.assertTrue(ctx.exception.conflict, "重名应标记 409 冲突")
            return h

        _run(main())

    def test_restart_marks_interrupted_and_blocks_until_reconcile(self) -> None:
        async def main():
            h = _Harness()
            res = await h.submit_and_start(1, prefix="R")
            bid = res["batch_id"]
            await h.step()
            h.finish(f"{bid}-af0")
            await h.step()
            self.assertIn("R-01-s1", h.vm.running())
            # 模拟重启: 同一 experiments 库上新建调度器 (不 finish 在飞段)
            vm2 = FakeVm()
            sched2 = FlowScheduler(
                vm=vm2, res_gate=FakeGate(), resolve_script=lambda n: _INDEX[n],
                material_store=h.materials, experiment_store=h.exp,
                registry=_REGISTRY, resource_modes=_MODES,
                recipes_dir=_CFG / "recipes", wip_limit=3, tank_pool=(1, 2, 3))
            report = h.exp.mark_interrupted_on_boot()
            sched2._boot_report = report
            sched2._rebuild_ledgers()
            self.assertEqual(report["jobs"], 1)
            batch = h.exp.get_batch(bid)
            self.assertEqual(batch["status"], "PAUSED")
            self.assertTrue(batch["needs_reconcile"])
            self.assertEqual(h.exp.get_job("R-01-s1")["status"], "INTERRUPTED")
            # 禁自动重派: 跑派发轮不得启动任何运行
            await sched2._pass()
            self.assertEqual(vm2.started, [], "重启后未对账不得自动重派")
            with self.assertRaises(ValueError):
                await sched2.batch_start(bid)
            # 对账: 该段整段重试 (人工确认物理态) -> 恢复批次 -> 重派
            await sched2.reconcile(bid, [{"sample_id": "R-01", "flow": "s1",
                                          "action": "retry", "confirm": True}])
            await sched2.batch_start(bid)
            await sched2._pass()
            self.assertEqual([s["run_id"] for s in vm2.started], ["R-01-s1-r2"])
            return h

        _run(main())


if __name__ == "__main__":
    unittest.main()
