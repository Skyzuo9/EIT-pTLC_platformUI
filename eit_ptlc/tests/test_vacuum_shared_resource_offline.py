"""离线: 大真空泵作为共享资源的引用计数语义 (ResourceGate + with_resources 区间).

覆盖:
    1. 并发两条运行各持真空区间 -> 开泵/关泵各恰好一次, 且先退出者不关泵 (本次改造的核心不变量)
    2. 区间内抛异常 -> 计数回落且仍关泵一次
    3. 嵌套 (父子脚本各声明同一资源) -> 不重复开关
    4. activate 失败 -> 计数回滚, 运行以失败收口
    5. 实盘 YAML: 主干流程不再出现 pump.vacuum_* 字面量, 真空区间落在预期动作上
    6. schema: 未登记资源名 / 区间声明独占资源 / 直调资源钩子动作 均被拒

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_vacuum_shared_resource_offline.py -v
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
from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.operation.resources import ResourceGate, load_resource_specs  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402

_CFG_DIR = _PKG / "config"
_OP_DIR = _CFG_DIR / "operation"
_RES_FILE = _CFG_DIR / "resources.yaml"
_VACUUM = "device:vacuum_pump"


def _load_op(name: str) -> dict:
    for path in _OP_DIR.glob(f"*/{name}.yaml"):
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    raise AssertionError(f"缺流程 {name}")


class _RecordingExecutor:
    """假执行器: 记录调用序列, 全 DONE; 指定动作名可强制失败."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self._fail_on = fail_on

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append(name)
        status = ActionStatus.REJECTED if name == self._fail_on else ActionStatus.DONE
        return ActionResult(action=name, request_id="x", status=status,
                            accepted=status is ActionStatus.DONE, message="ok", result={})


def _gate(executor: _RecordingExecutor) -> ResourceGate:
    """按实盘资源表构造资源门, 钩子动作转发给假执行器 (非 DONE 即抛)."""
    async def activator(action: str) -> None:
        result = await executor.execute(action)
        if result.status is not ActionStatus.DONE:
            raise RuntimeError(f"钩子动作 {action} 失败")
    return ResourceGate(load_resource_specs(_RES_FILE), activator=activator)


def _script(body: list) -> dict:
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": "t", "vars": [], "body": body}


class VacuumSharedResourceTest(unittest.TestCase):

    # ------------------------------------------------------------------
    # 1. 核心不变量: 先退出的流程不得关掉后者仍在用的真空
    # ------------------------------------------------------------------

    def test_concurrent_runs_share_pump_and_short_run_does_not_stop_it(self) -> None:
        ex = _RecordingExecutor()
        gate = _gate(ex)
        long_entered = asyncio.Event()
        long_may_exit = asyncio.Event()
        calls_seen_by_short_on_exit: list[str] = []

        async def long_run() -> None:
            async with gate.acquire([_VACUUM]):
                long_entered.set()
                await long_may_exit.wait()

        async def short_run() -> None:
            await long_entered.wait()
            async with gate.acquire([_VACUUM]):
                pass
            # 短流程已完全退出: 此刻绝不能出现 vacuum_off
            calls_seen_by_short_on_exit.extend(ex.calls)
            long_may_exit.set()

        async def main() -> None:
            await asyncio.gather(long_run(), short_run())

        asyncio.run(main())
        self.assertEqual(calls_seen_by_short_on_exit, ["pump.vacuum_on"],
                         "短流程退出时不得关泵 (长流程仍在使用真空)")
        self.assertEqual(ex.calls, ["pump.vacuum_on", "pump.vacuum_off"],
                         "两条流程全退出后才关泵, 且开关各一次")
        self.assertEqual(gate.holders(_VACUUM), 0)

    # ------------------------------------------------------------------
    # 2/3/4. 异常 / 嵌套 / 开启失败
    # ------------------------------------------------------------------

    def test_exception_inside_region_still_releases_pump(self) -> None:
        ex = _RecordingExecutor()
        gate = _gate(ex)

        async def main() -> None:
            with self.assertRaises(ValueError):
                async with gate.acquire([_VACUUM]):
                    raise ValueError("区间内失败")

        asyncio.run(main())
        self.assertEqual(ex.calls, ["pump.vacuum_on", "pump.vacuum_off"])
        self.assertEqual(gate.holders(_VACUUM), 0)

    def test_nested_regions_do_not_toggle_pump_twice(self) -> None:
        ex = _RecordingExecutor()
        gate = _gate(ex)

        async def main() -> None:
            async with gate.acquire([_VACUUM]):
                async with gate.acquire([_VACUUM]):
                    self.assertEqual(gate.holders(_VACUUM), 2)
                self.assertEqual(ex.calls, ["pump.vacuum_on"], "内层退出不得关泵")

        asyncio.run(main())
        self.assertEqual(ex.calls, ["pump.vacuum_on", "pump.vacuum_off"])

    def test_activate_failure_rolls_back_count(self) -> None:
        ex = _RecordingExecutor(fail_on="pump.vacuum_on")
        gate = _gate(ex)

        async def main() -> None:
            with self.assertRaises(RuntimeError):
                async with gate.acquire([_VACUUM]):
                    self.fail("开泵失败时不应进入区间")

        asyncio.run(main())
        self.assertEqual(gate.holders(_VACUUM), 0, "开启失败必须回滚计数")
        self.assertNotIn("pump.vacuum_off", ex.calls, "从未开启成功, 不应发关泵")

    # ------------------------------------------------------------------
    # 5. 实盘 YAML: 区间落位与字面量清除
    # ------------------------------------------------------------------

    def test_no_operation_calls_pump_actions_directly(self) -> None:
        offenders: list[str] = []
        for path in _OP_DIR.rglob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            if "pump.vacuum_on" in text or "pump.vacuum_off" in text:
                offenders.append(path.relative_to(_OP_DIR).as_posix())
        self.assertEqual(offenders, [], "真空泵开关必须由资源门驱动, 编排层不得出现字面量")

    def test_primary_flows_declare_vacuum_region_on_expected_actions(self) -> None:
        cases = {"sampling_prepare": "sampling.flush", "develop_prepare": "develop.rinse_suction"}
        for script, action in cases.items():
            with self.subTest(script=script):
                doc = _load_op(script)
                regions = [n for n in doc["body"] if n.get("op") == "with_resources"]
                self.assertEqual(len(regions), 1, f"{script} 应恰有一个真空区间")
                self.assertEqual(regions[0]["resources"], [_VACUUM])
                inner = [n.get("action") for n in regions[0]["body"] if n.get("op") == "call"]
                self.assertEqual(inner, [action], f"{script} 真空区间应精确包住 {action}")

    def test_vacuum_region_runs_pump_once_through_vm(self) -> None:
        """经 VmThread 跑实盘 sampling_prepare: 开关泵各一次, 且包住 sampling.flush."""
        ex = _RecordingExecutor()
        thread = VmThread(_load_op("sampling_prepare"), executor=ex, res_gate=_gate(ex))
        status = asyncio.run(thread.run())
        self.assertIs(status, VmStatus.DONE, "实盘 sampling_prepare 应跑到 DONE")
        self.assertEqual(ex.calls.count("pump.vacuum_on"), 1)
        self.assertEqual(ex.calls.count("pump.vacuum_off"), 1)
        on, flush, off = (ex.calls.index("pump.vacuum_on"), ex.calls.index("sampling.flush"),
                          ex.calls.index("pump.vacuum_off"))
        self.assertLess(on, flush)
        self.assertLess(flush, off)

    # ------------------------------------------------------------------
    # 6. schema 校验
    # ------------------------------------------------------------------

    def test_schema_rejects_bad_resource_declarations(self) -> None:
        specs = load_resource_specs(_RES_FILE)
        modes = {rid: spec.mode for rid, spec in specs.items()}
        hooks = {n for s in specs.values() for n in (s.activate, s.deactivate) if n}
        actions = {a.name for a in ActionRegistry.load(_CFG_DIR / "actions").list()}

        def errors(doc: dict) -> list[str]:
            return validate_script(doc, valid_actions=actions, resource_modes=modes,
                                   hook_actions=hooks)

        ok = _script([{"op": "with_resources", "resources": [_VACUUM],
                       "body": [{"op": "call", "action": "sampling.flush"}]}])
        self.assertEqual(errors(ok), [], "合法区间声明不应报错")

        unknown = _script([])
        unknown["resources"] = ["station:不存在"]
        self.assertTrue(any("未登记资源" in e for e in errors(unknown)))

        # 并行改造后语义: 独占区间在"根无独占"的脚本中合法 (W2 允许的展开等待段形态)
        exclusive_in_region = _script([{"op": "with_resources", "resources": ["station:sampling"],
                                        "body": []}])
        self.assertEqual(errors(exclusive_in_region), [],
                         "根无独占时, with_resources 声明独占应放行 (展开等待段短取排液形态)")

        # W2: 根已持独占 -> 体内独占区间被拒 (hold-and-wait)
        w2 = _script([{"op": "with_resources", "resources": ["station:sampling"], "body": []}])
        w2["resources"] = ["robot"]
        self.assertTrue(any("W2" in e for e in errors(w2)))

        # W1: 嵌套区间重取已持有的独占名 -> 自死锁被拒
        w1 = _script([{"op": "with_resources", "resources": ["station:sampling"],
                       "body": [{"op": "with_resources", "resources": ["station:sampling"],
                                 "body": []}]}])
        self.assertTrue(any("W1" in e for e in errors(w1)))

        # call 节点级仍只允许共享资源
        call_excl = _script([{"op": "call", "action": "sampling.flush",
                              "resources": ["station:sampling"]}])
        self.assertTrue(any("只能声明共享资源" in e for e in errors(call_excl)))

        direct_hook = _script([{"op": "call", "action": "pump.vacuum_off"}])
        self.assertTrue(any("不能直调资源钩子动作" in e for e in errors(direct_hook)))

        no_resources = _script([{"op": "with_resources", "body": []}])
        self.assertTrue(any("with_resources 缺少 resources" in e for e in errors(no_resources)))

    def test_resource_table_covers_every_declared_name(self) -> None:
        """全部实盘流程声明的资源名都必须在资源表中登记 (防写错名字静默变成新锁)."""
        specs = load_resource_specs(_RES_FILE)
        for path in _OP_DIR.rglob("*.yaml"):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                continue
            for name in (doc.get("resources") or []):
                self.assertIn(name, specs,
                              f"{path.relative_to(_OP_DIR).as_posix()} 引用未登记资源 {name}")


if __name__ == "__main__":
    unittest.main()
