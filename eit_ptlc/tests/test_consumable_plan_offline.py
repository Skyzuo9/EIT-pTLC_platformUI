"""耗材换板决策离线测试
========================
功能:
    验证 MaterialStore.plan_staging 的四条路径 (NONE 复用 / PUT_NEW 取新板 / SWAP 先还再取 /
    EXHAUSTED 无料), 以及"连跑一整块板不会重复发同一个孔、板耗尽自动转 SWAP"这条核心不变量。
    该判定是 ptlc_full_v2 备耗材环节的唯一裁决方 (经 material.plan_staging 动作供 ensure_*
    脚本做 if 分支), 判错就是撞机或抓空, 故逐条钉住。

    只测纯查询部分; 中转在位传感器防呆在 runtime/bootstrap.py 的闭包里 (要 PLC IO),
    不在本文件覆盖范围。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m unittest eit_ptlc.tests.test_consumable_plan_offline -v
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

import yaml

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.state import VmStatus
from eit_ptlc.operation.vm.thread import VmThread
from eit_ptlc.runtime.material_store import (
    HOLES_PER_PLATE,
    OP_EXHAUSTED,
    OP_NONE,
    OP_PUT_NEW,
    OP_SWAP,
    PLATES_PER_KIND,
    STATE_FRESH,
    STATE_USED,
    MaterialStore,
    load_topology,
)

# 直读现役拓扑, 避免造假表掩盖配置错误 (与 test_material_store_offline 同取向)
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_TOPOLOGY_FILE = _CONFIG_DIR / "material_topology.yaml"
_OPERATION_DIR = _CONFIG_DIR / "operation"


def _store() -> MaterialStore:
    """建一个内存账本; 不挂绑定表 (本文件只测查询, 不走事件记账)."""
    return MaterialStore(":memory:", topology=load_topology(_TOPOLOGY_FILE))


def _load_plate(store: MaterialStore, kind: str, plate: int) -> None:
    """把某块板整板标为可用 (等价实验员在物料页盘点录入满板)."""
    store.mark_plate(kind, plate, STATE_FRESH, detail="测试装板")


class PlanStagingPathTest(unittest.TestCase):
    """四条决策路径."""

    def setUp(self) -> None:
        self.store = _store()
        self.addCleanup(self.store.close)

    def test_中转有余量则原地复用不动整板(self) -> None:
        _load_plate(self.store, "collector", 3)
        self.store.set_staging("staging-a", 3)
        # 3 号板已在中转A 且 6 孔全新
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_NONE)
        self.assertEqual(plan["rack_slot"], 0)
        self.assertEqual(plan["old_rack_slot"], 0)
        self.assertEqual(plan["hole"], 1)
        self.assertEqual(plan["staged_plate"], 3)

    def test_复用时取该板最小可用孔而非恒定1号(self) -> None:
        _load_plate(self.store, "collector", 2)
        self.store.mark("collector", 2, 1, STATE_USED)
        self.store.mark("collector", 2, 2, STATE_USED)
        self.store.set_staging("staging-a", 2)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_NONE)
        self.assertEqual(plan["hole"], 3)

    def test_中转空则从货架取首块有料的板(self) -> None:
        _load_plate(self.store, "collector", 3)
        _load_plate(self.store, "collector", 5)
        # 中转A 为空 (播种默认即 NULL)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_PUT_NEW)
        self.assertEqual(plan["rack_slot"], 3)      # 按板号升序取首块
        self.assertEqual(plan["old_rack_slot"], 0)
        self.assertEqual(plan["hole"], 1)
        self.assertEqual(plan["staged_plate"], 0)

    def test_中转板耗尽则先还原库位再取新板(self) -> None:
        _load_plate(self.store, "collector", 4)
        self.store.mark_plate("collector", 2, STATE_USED)   # 2 号板已用尽
        self.store.set_staging("staging-a", 2)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_SWAP)
        self.assertEqual(plan["rack_slot"], 4)              # 取有料的 4 号
        self.assertEqual(plan["old_rack_slot"], 2)          # 2 号还回它自己的库位
        self.assertEqual(plan["hole"], 1)
        self.assertEqual(plan["staged_plate"], 2)

    def test_账本全空则判定耗尽(self) -> None:
        # 播种初值即全 USED (账本无权威, 不谎称有货)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_EXHAUSTED)
        self.assertEqual(plan["rack_slot"], 0)
        self.assertEqual(plan["hole"], 0)

    def test_中转有板但架上再无余料时仍判耗尽(self) -> None:
        self.store.mark_plate("collector", 1, STATE_USED)
        self.store.set_staging("staging-a", 1)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_EXHAUSTED)
        self.assertEqual(plan["staged_plate"], 1)

    def test_两类耗材各走各的中转区互不串台(self) -> None:
        _load_plate(self.store, "collector", 1)
        _load_plate(self.store, "bottle", 6)
        self.store.set_staging("staging-a", 1)
        self.assertEqual(self.store.plan_staging("collector")["op"], OP_NONE)
        # 中转B 仍空, 瓶该走 PUT_NEW 且取的是瓶那一套板号
        bottle = self.store.plan_staging("bottle")
        self.assertEqual(bottle["op"], OP_PUT_NEW)
        self.assertEqual(bottle["rack_slot"], 6)

    def test_种类非法即抛错(self) -> None:
        with self.assertRaises(ValueError):
            self.store.plan_staging("powder")


class PlanStagingSequenceTest(unittest.TestCase):
    """连续消耗下的序列不变量 —— 这是硬编码 slot_id=1 时代最容易复发的一类 bug."""

    def setUp(self) -> None:
        self.store = _store()
        self.addCleanup(self.store.close)

    def test_连跑一整块板孔号递增不重复且耗尽后转SWAP(self) -> None:
        _load_plate(self.store, "collector", 1)
        _load_plate(self.store, "collector", 2)

        # 第 1 轮: 中转空 -> 取 1 号板
        first = self.store.plan_staging("collector")
        self.assertEqual(first["op"], OP_PUT_NEW)
        self.assertEqual(first["rack_slot"], 1)
        self.store.set_staging("staging-a", 1)      # 模拟 transfer 完成后的 staging_load

        seen: list[int] = []
        for _ in range(HOLES_PER_PLATE):
            plan = self.store.plan_staging("collector")
            self.assertEqual(plan["op"], OP_NONE, "板上还有余量时不该动整板")
            seen.append(plan["hole"])
            # 模拟 consume: 该孔被取走
            self.store.mark("collector", 1, plan["hole"], STATE_USED)

        self.assertEqual(seen, list(range(1, HOLES_PER_PLATE + 1)),
                         "孔号应 1..6 递增且不重复")

        # 第 7 次: 1 号板耗尽 -> 还 1 取 2
        after = self.store.plan_staging("collector")
        self.assertEqual(after["op"], OP_SWAP)
        self.assertEqual(after["old_rack_slot"], 1)
        self.assertEqual(after["rack_slot"], 2)
        self.assertEqual(after["hole"], 1)

    def test_成品瓶占着的孔不会被当成可用再发一次(self) -> None:
        """fill 把孔置 USED 并打样品号; 决策必须跳过它, 否则会往装了样的瓶上再灌一次."""
        _load_plate(self.store, "bottle", 1)
        self.store.set_staging("staging-b", 1)
        self.store.mark("bottle", 1, 1, STATE_USED, sample_id="S-001")
        plan = self.store.plan_staging("bottle")
        self.assertEqual(plan["op"], OP_NONE)
        self.assertNotEqual(plan["hole"], 1)
        self.assertEqual(plan["hole"], 2)

    def test_决策是只读的不改任何账(self) -> None:
        _load_plate(self.store, "collector", 1)
        before = self.store.grid()
        for _ in range(3):
            self.store.plan_staging("collector")
        after = self.store.grid()
        self.assertEqual(before["cells"], after["cells"], "plan_staging 不得改孔位账")
        self.assertEqual(before["staging"], after["staging"], "plan_staging 不得改中转占用")

    def test_板号候选覆盖全部六块板(self) -> None:
        """只有末块板有料时也要能找到 —— 防止候选扫描被首板短路."""
        _load_plate(self.store, "collector", PLATES_PER_KIND)
        plan = self.store.plan_staging("collector")
        self.assertEqual(plan["op"], OP_PUT_NEW)
        self.assertEqual(plan["rack_slot"], PLATES_PER_KIND)


class _StubExecutor:
    """记录型桩执行器: 除 material.plan_staging 与 robot.query 外一律回 DONE 空结果.

    只为验证 ensure_* 脚本的分支走向, 不涉任何真实设备语义。
    """

    def __init__(self, plan: dict) -> None:
        self._plan = plan
        self.events: list[tuple[str, str]] = []
        self.calls: list[tuple[str, dict]] = []      # (动作名, 求值后的入参)

    async def execute(self, action: str, args: dict, current_mode=None) -> ActionResult:
        self.events.append(("call", action))
        self.calls.append((action, dict(args or {})))
        if action == "material.plan_staging":
            result = dict(self._plan)
        elif action == "robot.query":
            # 令 robot_tool_ensure 判定 current == needed(2) 而跳过换刀, 避免牵进地轨与工具站
            result = {"tool_state": {"mounted_tool": 2, "suction_on": False}}
        else:
            result = {}
        return ActionResult(action=action, request_id="t", status=ActionStatus.DONE,
                            accepted=True, result=result)


def _scripts() -> dict:
    """全量读 config/operation 供 VM 解析子脚本 (直读真源, 不造假脚本)."""
    docs = {}
    for path in sorted(_OPERATION_DIR.glob("**/*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        docs[doc["name"]] = doc
    return docs


class EnsureScriptBranchTest(unittest.TestCase):
    """ensure_* 脚本的分支走向 —— 决策对了但分支接错一样会撞机, 故按动作码逐条钉住."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.docs = _scripts()

    def _run(self, script: str, plan: dict) -> tuple[VmStatus, _StubExecutor, list]:
        """在桩执行器上跑一个 ensure 脚本, 返回 (终态, 执行器, 事件序列)."""
        stub = _StubExecutor(plan)
        events: list = []

        def _emit(event: dict) -> None:
            if event.get("type") == "vm_node_enter" and event.get("op") == "run_script":
                events.append(("run_script", event.get("action", "")))

        thread = VmThread(self.docs[script], executor=stub, res_gate=ResourceGate(),
                          resolve_script=lambda n: self.docs[n],
                          emit=_emit, mode_provider=lambda: "RUN")
        status = asyncio.run(thread.run({}))
        return status, stub, events

    def test_NONE_不动整板只声明终态夹紧(self) -> None:
        plan = {"op": OP_NONE, "rack_slot": 0, "old_rack_slot": 0, "hole": 4, "staged_plate": 3}
        status, stub, events = self._run("ensure_collector_staged", plan)
        self.assertEqual(status, VmStatus.DONE)
        moved = [name for kind, name in events if name.startswith("transfer_")]
        self.assertEqual(moved, [], "中转还有余量时不得动整板")
        self.assertNotIn("robot_tool_ensure", [n for _k, n in events], "不动板就不该换刀")
        self.assertEqual(stub.events[-1], ("call", "staging_a.locator_a"),
                         "终态必须显式夹紧中转A")

    def test_PUT_NEW_只取新板不还板(self) -> None:
        plan = {"op": OP_PUT_NEW, "rack_slot": 3, "old_rack_slot": 0, "hole": 1, "staged_plate": 0}
        status, _stub, events = self._run("ensure_collector_staged", plan)
        self.assertEqual(status, VmStatus.DONE)
        moved = [name for _k, name in events if name.startswith("transfer_")]
        self.assertEqual(moved, ["transfer_collector_rack_to_staging_a"])
        self.assertIn("robot_tool_ensure", [n for _k, n in events], "动整板前须切大夹爪")

    def test_SWAP_先还满板再取新板顺序不能颠倒(self) -> None:
        plan = {"op": OP_SWAP, "rack_slot": 4, "old_rack_slot": 2, "hole": 1, "staged_plate": 2}
        status, _stub, events = self._run("ensure_collector_staged", plan)
        self.assertEqual(status, VmStatus.DONE)
        moved = [name for _k, name in events if name.startswith("transfer_")]
        self.assertEqual(moved, ["transfer_collector_staging_a_to_rack",
                                 "transfer_collector_rack_to_staging_a"],
                         "必须先腾空中转再放新板, 顺序颠倒会往有板的中转位放整板")

    def test_瓶版走中转B与瓶转运脚本(self) -> None:
        plan = {"op": OP_SWAP, "rack_slot": 5, "old_rack_slot": 1, "hole": 1, "staged_plate": 1}
        status, stub, events = self._run("ensure_bottle_staged", plan)
        self.assertEqual(status, VmStatus.DONE)
        moved = [name for _k, name in events if name.startswith("transfer_")]
        self.assertEqual(moved, ["transfer_bottle_staging_b_to_rack",
                                 "transfer_bottle_rack_to_staging_b"])
        self.assertEqual(stub.events[-1], ("call", "staging_a.locator_b"),
                         "瓶版终态必须夹紧中转B")

    def test_决策的孔号原样透到调用方(self) -> None:
        """hole 是 out 变量, 调用方要拿它同时驱动取件与归还; 透传错就会取空孔或覆盖成品."""
        for op, hole in ((OP_NONE, 5), (OP_PUT_NEW, 1), (OP_SWAP, 1)):
            with self.subTest(op=op):
                plan = {"op": op, "rack_slot": 3, "old_rack_slot": 2 if op == OP_SWAP else 0,
                        "hole": hole, "staged_plate": 2 if op != OP_PUT_NEW else 0}
                stub = _StubExecutor(plan)

                # 顶层包一层脚本: 接出 ensure_* 的 out 变量 (与 ptlc_full_v2 的接法同形),
                # 再把它当参数发给一个探针动作 —— 只经可观测行为读回, 不碰 VM 内部结构
                caller = {
                    "schema": "ptlc.script/v1", "kind": "operation", "name": "_probe",
                    "vars": [{"name": "got", "scope": "local", "type": "INT",
                              "io": "var", "default": 0}],
                    "body": [
                        {"op": "run_script", "script": "ensure_collector_staged",
                         "inputs": {}, "outputs": {"hole": {"var": "got"}}},
                        {"op": "call", "action": "_probe.echo", "mode": "RUN",
                         "args": {"slot_id": {"var": "got"}}},
                    ],
                }
                thread = VmThread(caller, executor=stub, res_gate=ResourceGate(),
                                  resolve_script=lambda n: self.docs[n],
                                  emit=lambda e: None, mode_provider=lambda: "RUN")
                status = asyncio.run(thread.run({}))
                self.assertEqual(status, VmStatus.DONE)
                echoed = [args for name, args in stub.calls if name == "_probe.echo"]
                self.assertEqual(echoed, [{"slot_id": hole}],
                                 f"op={op} 时孔号应原样透出为 {hole}")


if __name__ == "__main__":
    unittest.main()
