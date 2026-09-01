"""离线集成: develop_execute auto 分支在 mini-VM 上端到端 (FakeExecutor, 实盘 YAML).

覆盖: reached→standby→reached→drain / T1 hard_cap 跳过 standby 直排 /
T2 硬上限预算扣减表达式 / manual 默认分支不含 wait_level (结构级).
human 门路径不在此跑 (需 HITL 应答机制), 由 test_develop_four_stage_offline 结构断言守卫.
运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_develop_auto_drain_flow_offline
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

from eit_ptlc.action.models import ActionResult, ActionStatus  # noqa: E402
from eit_ptlc.operation.resources import ResourceGate  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402

_OP_DIR = _PKG / "config" / "operation"


def _load(name: str) -> dict:
    for path in _OP_DIR.glob(f"*/{name}.yaml"):
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise AssertionError(f"缺流程 {name}")


class SeqExecutor:
    """假执行器: 全 DONE; develop.wait_level 依次弹出预置结果."""

    def __init__(self, wait_results) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._wait = list(wait_results)

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        params = dict(params or {})
        self.calls.append((name, params))
        if name == "develop.wait_level":
            result = self._wait.pop(0)
        elif name == "develop.capture_reference":
            result = {"ok": True, "has_ref": True, "elapsed_s": 31.0}
        else:
            result = {}
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result=result)


def _run_execute(wait_results) -> SeqExecutor:
    docs = {n: _load(n) for n in ("develop_execute",)}
    ex = SeqExecutor(wait_results)
    thread = VmThread(docs["develop_execute"], executor=ex, res_gate=ResourceGate(),
                      resolve_script=lambda n: docs[n], overrides={"auto_drain": True})
    status = asyncio.run(thread.run())
    if status is not VmStatus.DONE:
        raise AssertionError(f"运行未 DONE: {status}")
    return ex


def _names(ex: SeqExecutor) -> list[str]:
    return [c[0] for c in ex.calls]


class AutoDrainFlowTests(unittest.TestCase):
    def test_reached_then_reached_full_path(self) -> None:
        ex = _run_execute([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 100.0, "reason": ""},
            {"status": "reached", "front_percent": 81.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 40.0, "reason": ""},
        ])
        names = _names(ex)
        # capture → T1 → T2 → 排液; 无 human 挂起。
        # 地轨就位已拆为 develop_standby 独立段 (execute 不再持 robot/station:rail),
        # 故本段不再出现 robot.home_ensure / rail.move
        self.assertEqual(names, ["develop.capture_reference", "develop.wait_level",
                                 "develop.wait_level", "develop.drain"])
        # T2 硬上限 = 3600 - T1 已耗 100 (max 兜零)
        t2_args = dict(ex.calls[2][1])
        self.assertEqual(t2_args.get("stage"), "t2")
        self.assertEqual(t2_args.get("hard_cap_s"), 3500.0)

    def test_t1_hard_cap_skips_t2_and_drains(self) -> None:
        ex = _run_execute([
            {"status": "hard_cap", "front_percent": 50.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 3600.0, "reason": ""},
        ])
        self.assertEqual(_names(ex), ["develop.capture_reference",
                                      "develop.wait_level", "develop.drain"])

    def test_t2_budget_never_negative(self) -> None:
        ex = _run_execute([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 3601.5, "reason": ""},
            {"status": "hard_cap", "front_percent": 66.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 0.0, "reason": ""},
        ])
        t2_args = dict(ex.calls[2][1])
        self.assertEqual(t2_args.get("hard_cap_s"), 0.0)   # max(0, 3600-3601.5)
        self.assertEqual(_names(ex)[-1], "develop.drain")

    def test_rail_move_safe_emits_home_ensure_then_move(self) -> None:
        """地轨就位构件: P1 确保式安全门 + 地轨到展开位(5), 顺序不可颠倒.

        这段原先跑在 develop_execute 内 (develop_standby), 现由 develop_unload 在开盖前
        直接调用。地轨平移会拖着机械臂走, 故 home_ensure 必须先于 rail.move。
        """
        docs = {n: _load(n) for n in ("develop_standby", "rail_move_safe")}
        ex = SeqExecutor([])
        thread = VmThread(docs["develop_standby"], executor=ex, res_gate=ResourceGate(),
                          resolve_script=lambda n: docs[n])
        self.assertIs(asyncio.run(thread.run()), VmStatus.DONE)
        self.assertEqual(_names(ex), ["robot.home_ensure", "rail.move"])
        self.assertEqual(dict(ex.calls[1][1]).get("Rail_Target_Position"), 5)

    def test_dry_duration_knob_passthrough(self) -> None:
        """knob dry_duration_s 经 override 注入后必须透传到 develop.drain args."""
        docs = {n: _load(n) for n in ("develop_execute",)}
        ex = SeqExecutor([
            {"status": "reached", "front_percent": 66.0, "threshold": 65.0,
             "stage": "t1", "elapsed_s": 100.0, "reason": ""},
            {"status": "reached", "front_percent": 81.0, "threshold": 80.0,
             "stage": "t2", "elapsed_s": 40.0, "reason": ""},
        ])
        thread = VmThread(docs["develop_execute"], executor=ex, res_gate=ResourceGate(),
                          resolve_script=lambda n: docs[n],
                          overrides={"auto_drain": True, "dry_duration_s": 45.0})
        status = asyncio.run(thread.run())
        self.assertIs(status, VmStatus.DONE)
        name, args = ex.calls[-1]
        self.assertEqual(name, "develop.drain")
        self.assertEqual(dict(args).get("dry_duration_s"), 45.0)

    def test_drain_calls_and_unload_order_structural(self) -> None:
        """结构级: 两分支 drain 都带 dry_duration_s 变量引用; unload 序 = 开盖→取板→关盖→释放."""
        def walk(nodes):
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                if n.get("op") == "call" and n.get("action") == "develop.drain":
                    yield n
                for key in ("then", "else", "body"):
                    if isinstance(n.get(key), list):
                        yield from walk(n[key])
        execute = _load("develop_execute")
        drains = list(walk(execute["body"]))
        self.assertEqual(len(drains), 3, "develop_execute 应有 ref-fail/auto/manual 三处 drain")
        for node in drains:
            self.assertEqual(node["args"].get("dry_duration_s"), {"var": "dry_duration_s"})
        knobs = [v for v in execute["vars"] if v["name"] == "dry_duration_s"]
        self.assertEqual(len(knobs), 1)
        self.assertTrue(isinstance(knobs[0].get("ui"), dict), "dry_duration_s 必须是 knob (带 ui)")
        unload = _load("develop_unload")
        names = [n.get("action") or n.get("script")
                 for n in unload["body"] if n.get("op") in ("call", "run_script")]
        self.assertEqual(names, ["rail_move_safe", "develop.plate_retract", "robot_tank_pick",
                                 "develop.plate_extend", "develop.release_tank"])

    def test_ref_fail_branch_structural(self) -> None:
        """参考采集失败分支: 合并 HITL 门 (告知失败+确认排液) + drain, 在 auto/manual 大 if 之外."""
        execute = _load("develop_execute")
        body = execute["body"]
        capture = [n for n in body if isinstance(n, dict)
                   and n.get("op") == "call" and n.get("action") == "develop.capture_reference"]
        self.assertEqual(len(capture), 1)
        self.assertEqual(capture[0]["args"].get("target_tank"), {"var": "tank"})
        self.assertEqual(capture[0].get("assign"), {"var": "ref_result"})
        fail_if = next(n for n in body if isinstance(n, dict) and n.get("op") == "if"
                       and (n.get("cond") or {}).get("binop") == "==")
        prompts = [str((x.get("prompt") or {}).get("lit", ""))
                   for x in fail_if["then"] if isinstance(x, dict) and x.get("op") == "human"]
        self.assertTrue(any("参考图采集失败" in p for p in prompts))
        drains = [x for x in fail_if["then"] if isinstance(x, dict)
                  and x.get("op") == "call" and x.get("action") == "develop.drain"]
        self.assertEqual(len(drains), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
