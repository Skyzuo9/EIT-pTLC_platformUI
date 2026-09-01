"""物料账本离线测试
====================
功能:
    验证 MaterialStore 的播种幂等、绑定表闭集校验、VM 事件记账 (含 (run_id, script, aid)
    三元关联键防串台)、只认 DONE 的终态门、四种 effect 的余量迁移, 以及"满瓶不会被
    next_fresh 当空瓶再取"这条核心不变量.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m unittest eit_ptlc.tests.test_material_store_offline -v
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.thread import VmThread
from eit_ptlc.runtime.material_store import (
    HOLES_PER_PLATE,
    KINDS,
    PLATES_PER_KIND,
    STATE_FRESH,
    STATE_USED,
    MaterialStore,
    load_bindings,
    load_topology,
)

# 现役配置 (随 config 一起演进; 测试直读真源, 避免造假表掩盖配置错误)
_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_BINDINGS_FILE = _CONFIG_DIR / "material_bindings.yaml"
_TOPOLOGY_FILE = _CONFIG_DIR / "material_topology.yaml"


def _topology():
    """现役物料拓扑 (四类物料/位置/传感器单一真源)."""
    return load_topology(_TOPOLOGY_FILE)


def _store(**kwargs) -> MaterialStore:
    """建一个内存账本, 默认挂现役拓扑与绑定表."""
    topology = kwargs.pop("topology", None) or _topology()
    if "bindings" in kwargs:
        bindings = kwargs.pop("bindings")
    else:
        bindings = load_bindings(_BINDINGS_FILE, topology)
    return MaterialStore(":memory:", topology=topology, bindings=bindings, **kwargs)


def _enter(run_id: str, script: str, aid: str, callee: str, args: dict) -> dict:
    """造一条 run_script 的 vm_node_enter 事件 (script = 调用方脚本名)."""
    return {"type": "vm_node_enter", "run_id": run_id, "script": script, "aid": aid,
            "op": "run_script", "action": callee, "args": args, "ts": 1000.0}


def _done(run_id: str, script: str, aid: str, callee: str, status: str = "DONE") -> dict:
    """造一条 vm_node_done 事件."""
    return {"type": "vm_node_done", "run_id": run_id, "script": script, "aid": aid,
            "op": "run_script", "action": callee, "status": status, "ts": 1001.0}


def _run_script(store: MaterialStore, callee: str, args: dict, *, run_id: str = "r1",
                caller: str = "demo", aid: str = "b1", status: str = "DONE") -> None:
    """驱动一次子脚本调用的 enter+done 事件对."""
    store.on_event(_enter(run_id, caller, aid, callee, args))
    store.on_event(_done(run_id, caller, aid, callee, status))


def _cell(store: MaterialStore, kind: str, plate: int, hole: int) -> dict:
    """从 grid() 里取单格 (测试只经公开接口读, 不碰内部连接)."""
    for row in store.grid()["cells"]:
        if row["kind"] == kind and row["plate"] == plate and row["hole"] == hole:
            return row
    raise AssertionError(f"网格缺格 {kind} 板{plate} 孔{hole}")


class TestSeeding(unittest.TestCase):
    """播种与幂等."""

    def test_seeds_full_grid_as_empty(self):
        """播种 72 格, 初值 USED (空孔) —— 账本不谎称有货."""
        grid = _store().grid()
        self.assertEqual(len(grid["cells"]), len(KINDS) * PLATES_PER_KIND * HOLES_PER_PLATE)
        self.assertEqual(len(grid["cells"]), 72)
        self.assertTrue(all(row["state"] == STATE_USED for row in grid["cells"]))
        self.assertTrue(all(not row["sample_id"] for row in grid["cells"]))
        for kind in KINDS:
            self.assertEqual(grid["summary"][kind],
                             {"fresh": 0, "used": 36, "filled": 0, "absent_plates": 0})

    def test_seeds_two_empty_staging_areas(self):
        """两个中转区行存在且初始为空."""
        staging = _store().grid()["staging"]
        self.assertEqual(set(staging), {"staging-a", "staging-b"})
        self.assertIsNone(staging["staging-a"]["plate"])
        self.assertEqual(staging["staging-a"]["kind"], "collector")
        self.assertEqual(staging["staging-b"]["kind"], "bottle")

    def test_reseed_preserves_marks(self):
        """重开同一库文件时播种不覆盖已有盘点结果 (幂等)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.db"
            first = MaterialStore(path, topology=_topology(), bindings=None)
            first.mark_plate("collector", 2, STATE_FRESH)
            first.set_staging("staging-a", 2)
            first.close()

            second = MaterialStore(path, topology=_topology(), bindings=None)
            self.assertEqual(_cell(second, "collector", 2, 3)["state"], STATE_FRESH)
            self.assertEqual(second.grid()["staging"]["staging-a"]["plate"], 2)
            second.close()


class TestBindingsValidation(unittest.TestCase):
    """绑定表闭集校验: 拼错必须启动即失败, 不静默漏账."""

    def test_live_bindings_file_loads(self):
        """现役 config/material_bindings.yaml 可加载: 22 条脚本 + 5 条动作.

        22 = 10 条位置/计数迁移 (transfer_* 与 feedlift_*_cycle) + 6 条在途 (robot_* 叶子)
             + 6 条站侧交接 (robot_collect_bottle_* / robot_*_holder_*)。
        站侧那 6 条是 2026-08-05 补的: 它们物理上开合小爪却一条绑定都没有, 于是单件被放到
        工位夹具后在途行再没人清, 三维把瓶/桶焊在机械臂上飞完整个周期。
        5 = 3 条 liquid_draw (develop.fill / develop.rinse_fill / collect.collect)
            + 2 条刮取产粉量的两段式 (photoscrape.cnc_path 的 scrape_arm
            + photoscrape.scrape_finish 的 powder_fill), 2026-08 补。
        """
        bindings = load_bindings(_BINDINGS_FILE, _topology())
        # 2026-08-13 +13: 薄层板的板位与工艺阶段 (plate_seat ×2 + plate_stage ×11),
        # 见 material_bindings.yaml 的"薄层板的板位与工艺阶段"一节
        self.assertEqual(len(bindings.scripts), 35)
        self.assertEqual(len(bindings.actions), 5)
        self.assertEqual(
            bindings.scripts["transfer_collector_rack_to_staging_a"]["effect"], "staging_load")
        self.assertEqual(bindings.scripts["robot_collector_return_put"]["effect"], "fill")
        self.assertEqual(bindings.scripts["robot_group_rack_pick"], {
            "effect": "transit_pick", "carrier": "gripper_plate96", "payload": "tray",
            "kind_from": "rack_id", "from_loc": "rack",
            "plate_from": "slot_id", "hole_from": None, "seat": ""})
        # 站侧取件: 身份没有任何入参来源, 全部从座位行读回, 故三个 *_from 均为 None
        self.assertEqual(bindings.scripts["robot_collect_bottle_pick"], {
            "effect": "transit_pick", "carrier": "gripper_vial", "payload": "item",
            "kind_from": None, "from_loc": "station",
            "plate_from": None, "hole_from": None, "seat": "collect-bottle"})
        self.assertEqual(bindings.scripts["robot_scrape_holder_put_exit"], {
            "effect": "transit_place", "carrier": "gripper_vial", "to_loc": "station",
            "plate_from": None, "seat": "scrape-holder"})
        self.assertEqual(bindings.scripts["robot_group_staging_put"], {
            "effect": "transit_place", "carrier": "gripper_plate96",
            "to_loc": "staging", "plate_from": None, "seat": ""})
        self.assertEqual(bindings.scripts["feedlift_load_cycle"],
                         {"effect": "plate_take", "magazine": "feed"})
        self.assertEqual(bindings.scripts["feedlift_unload_cycle"],
                         {"effect": "plate_put", "magazine": "waste"})
        up = bindings.actions["develop.fill"]
        self.assertEqual(up["volume_from"], "solvent_volume_ml")
        self.assertEqual(up["count_from"], "up_liquid_repeat_count")
        self.assertEqual(len(up["ratio_from"]), 4)
        self.assertEqual(up["bottles"], ["solvent_1", "solvent_2", "solvent_3", "solvent_4"])
        # 展缸两条不写 to_seat/wet_seat ⇒ 解析出 None ⇒ 一格都不动 (零回归)
        self.assertIsNone(up["to_seat"])
        self.assertIsNone(up["wet_seat"])
        col = bindings.actions["collect.collect"]
        self.assertEqual(col["to_seat"], "collect-bottle")
        self.assertEqual(col["wet_seat"], "collect-holder")
        self.assertEqual(bindings.actions["photoscrape.cnc_path"], {
            "effect": "scrape_arm", "volume_from_result": "scrape_volume_mm3",
            "area_from_result": "scrape_area_mm2",
            "source_from_result": "scrape_area_source"})
        self.assertEqual(bindings.actions["photoscrape.scrape_finish"],
                         {"effect": "powder_fill", "seat": "scrape-holder"})

    def test_bindings_match_catalog(self):
        """绑定表引用的动作名与取参名必须真实存在于动作目录, 且脚本名存在于流程库.

        钉住"静默永不触发"这一类错: 绑到不存在的动作名 (曾把 develop.fill 写成
        develop.up_liquid) 或不存在的参数名, 记账会一声不响地永远不发生, 而所有
        造事件的单测仍全绿 —— 只有拿真配置交叉验证才抓得住.
        """
        from eit_ptlc.action.registry import ActionRegistry

        config_dir = Path(__file__).resolve().parent.parent / "config"
        registry = ActionRegistry.load(config_dir / "actions")
        catalog = {a.name: {p.name for p in a.params} for a in registry.list()}
        bindings = load_bindings(_BINDINGS_FILE, _topology())

        for action, spec in bindings.actions.items():
            self.assertIn(action, catalog, f"绑定表引用了不存在的动作 {action}")
            params = catalog[action]
            # 按 effect 分支: 只有 liquid_draw 是"从**入参**取量", 才能拿动作目录核对参名。
            # scrape_arm 取的是动作 **result** 的键 (动作目录不描述 result), 由下面那条
            # test_scrape_arm_keys_exist_in_action_result 顶上; powder_fill 不取任何量。
            if spec["effect"] != "liquid_draw":
                continue
            names = [spec["volume_from"], *spec["ratio_from"]]
            if spec["count_from"]:
                names.append(spec["count_from"])
            for arg in names:
                self.assertIn(arg, params,
                              f"动作 {action} 没有参数 {arg} (绑定表取参名写错则静默不扣减)")

        # 脚本侧: 绑定的脚本名必须在流程库里存在 (文件名 stem)
        op_dir = config_dir / "operation"
        known = {p.stem for p in op_dir.glob("*/*.yaml")} | {p.stem for p in op_dir.glob("*.yaml")}
        for script in bindings.scripts:
            self.assertIn(script, known, f"绑定表引用了不存在的流程脚本 {script}")

    def test_scrape_arm_keys_exist_in_action_result(self):
        """scrape_arm 的三个取键必须真实存在于 cnc_path 动作的 result 里.

        这是 test_bindings_match_catalog 那道门在 scrape_arm 上的**替代品**: 动作目录只描述
        入参不描述 result, 于是取键写错会静默永不记账而所有造事件的单测仍全绿。这里拿
        safe_placeholder_arrays 的真键集交叉验证 —— 它与 generate_scrape_arrays 走同一个
        ScrapeArrays.as_action_result()。
        """
        from eit_ptlc.config.models import GCodeCfg
        from eit_ptlc.controller.cnc_path import safe_placeholder_arrays

        keys = set(safe_placeholder_arrays(GCodeCfg()).as_action_result())
        bindings = load_bindings(_BINDINGS_FILE, _topology())
        armed = 0
        for action, spec in bindings.actions.items():
            if spec["effect"] != "scrape_arm":
                continue
            armed += 1
            for field in ("volume_from_result", "area_from_result", "source_from_result"):
                name = spec.get(field)
                if not name:
                    continue
                self.assertIn(name, keys,
                              f"动作 {action} 的 result 里没有 {name} "
                              f"(绑定表取键写错则静默永不记粉)")
        self.assertEqual(armed, 1, "现役应恰有一条 scrape_arm 绑定; 0 条说明这道门在空转")

    def _write(self, tmp: str, body: str) -> Path:
        path = Path(tmp) / "b.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_rejects_bad_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "schema: wrong/v9\nbindings: {}\n")
            with self.assertRaises(ValueError):
                load_bindings(path, _topology())

    def test_rejects_bad_action_bindings(self):
        """动作级绑定的闭集校验: effect/bottles/ratio_from 长度/未知键."""
        base = "schema: ptlc.material_bindings/v1\nbindings: {}\nactions:\n  a.b:\n"
        cases = [
            # 未知 effect
            "    {effect: teleport, volume_from: v, bottles: [solvent_1]}\n",
            # 缺 volume_from
            "    {effect: liquid_draw, bottles: [solvent_1]}\n",
            # bottles 空
            "    {effect: liquid_draw, volume_from: v, bottles: []}\n",
            # 未知瓶名
            "    {effect: liquid_draw, volume_from: v, bottles: [beaker]}\n",
            # ratio_from 与 bottles 长度不一致 (同序位对应, 错位即静默记错瓶)
            "    {effect: liquid_draw, volume_from: v, ratio_from: [r1, r2], bottles: [solvent_1]}\n",
            # 未知键
            "    {effect: liquid_draw, volume_from: v, bottles: [solvent_1], oops: 1}\n",
        ]
        for tail in cases:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, base + tail)
                with self.assertRaises(ValueError, msg=tail):
                    load_bindings(path, _topology())

    def test_rejects_bad_plate_bindings(self):
        """玻璃板计数绑定必须声明合法 magazine, 且不接受盘位类键."""
        base = "schema: ptlc.material_bindings/v1\nbindings:\n  s:\n"
        for tail in ("    {effect: plate_take, magazine: attic}\n",
                     "    {effect: plate_take}\n",
                     "    {effect: plate_put, magazine: feed, kind: collector}\n"):
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, base + tail)
                with self.assertRaises(ValueError, msg=tail):
                    load_bindings(path, _topology())

    def test_rejects_unknown_effect_kind_area(self):
        base = "schema: ptlc.material_bindings/v1\nbindings:\n  s:\n"
        cases = [
            "    {effect: teleport, kind: collector, area: staging-a, plate_from: slot_id}\n",
            "    {effect: consume, kind: widget, area: staging-a, hole_from: slot_id}\n",
            "    {effect: consume, kind: collector, area: staging-z, hole_from: slot_id}\n",
            # 中转区与耗材种类错配 (staging-b 只放 bottle)
            "    {effect: consume, kind: collector, area: staging-b, hole_from: slot_id}\n",
            # consume 缺 hole_from
            "    {effect: consume, kind: collector, area: staging-a}\n",
            # staging_load 缺 plate_from
            "    {effect: staging_load, kind: collector, area: staging-a}\n",
            # 未知键
            "    {effect: consume, kind: collector, area: staging-a, hole_from: slot_id, oops: 1}\n",
        ]
        for tail in cases:
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, base + tail)
                with self.assertRaises(ValueError, msg=tail):
                    load_bindings(path, _topology())


class TestSinkCorrelation(unittest.TestCase):
    """事件关联与终态门."""

    def test_aid_collision_across_script_frames_does_not_crosstalk(self):
        """两个不同脚本帧用同一 aid 时互不串台 —— 关联键含脚本名 (vm/thread.py:71-73)."""
        store = _store()
        store.mark_plate("collector", 1, STATE_FRESH)
        store.mark_plate("bottle", 1, STATE_FRESH)
        store.set_staging("staging-a", 1)
        store.set_staging("staging-b", 1)

        # 同 run_id、同 aid "b3", 但来自不同调用方脚本帧
        store.on_event(_enter("r1", "frame_a", "b3", "transfer_collector_staging_a_to_scrape",
                              {"slot_id": 2}))
        store.on_event(_enter("r1", "frame_b", "b3", "transfer_bottle_staging_b_to_collect",
                              {"slot_id": 5}))
        # 交叉结清: 各自命中自己的那笔
        store.on_event(_done("r1", "frame_b", "b3", "transfer_bottle_staging_b_to_collect"))
        store.on_event(_done("r1", "frame_a", "b3", "transfer_collector_staging_a_to_scrape"))

        self.assertEqual(_cell(store, "collector", 1, 2)["state"], STATE_USED)
        self.assertEqual(_cell(store, "bottle", 1, 5)["state"], STATE_USED)
        # 未涉及的孔保持 FRESH
        self.assertEqual(_cell(store, "collector", 1, 5)["state"], STATE_FRESH)
        self.assertEqual(_cell(store, "bottle", 1, 2)["state"], STATE_FRESH)

    def test_non_done_status_never_commits(self):
        """CANCELLED / ERROR / REJECTED 一律不记账 —— 物料没动."""
        for status in ("CANCELLED", "ERROR", "REJECTED", "FAILED"):
            store = _store()
            store.mark_plate("collector", 3, STATE_FRESH)
            store.set_staging("staging-a", 3)
            _run_script(store, "transfer_collector_staging_a_to_scrape", {"slot_id": 1},
                        status=status)
            self.assertEqual(_cell(store, "collector", 3, 1)["state"], STATE_FRESH,
                             f"status={status} 不应记账")

    def test_unbound_script_ignored(self):
        """未登记的脚本不产生任何账目.

        用 robot_tool_ensure 而不是取放类脚本: 换刀与物料无关, 永远不会被绑, 是稳定的
        反例。(此处原本用 robot_group_rack_pick, 2026-08-05 起它已绑 transit_pick。)
        """
        store = _store()
        _run_script(store, "robot_tool_ensure", {"needed": 2})
        self.assertIsNone(store.grid()["staging"]["staging-a"]["plate"])
        self.assertEqual(store.list_events(), [])

    def test_root_script_records_via_operation_start_inputs(self):
        """面板直跑 transfer_* (根脚本, 无 run_script 节点) 经 operation_start.inputs 记账."""
        store = _store()
        store.mark_plate("collector", 4, STATE_FRESH)
        store.on_event({"type": "operation_start", "run_id": "r9",
                        "operation": "transfer_collector_rack_to_staging_a",
                        "inputs": {"slot_id": 4}, "ts": 1.0})
        store.on_event({"type": "operation_done", "run_id": "r9",
                        "operation": "transfer_collector_rack_to_staging_a", "ts": 2.0})
        self.assertEqual(store.grid()["staging"]["staging-a"]["plate"], 4)

    def test_root_script_failed_run_does_not_record(self):
        """根脚本运行失败时不记账."""
        store = _store()
        store.on_event({"type": "operation_start", "run_id": "r9",
                        "operation": "transfer_collector_rack_to_staging_a",
                        "inputs": {"slot_id": 4}, "ts": 1.0})
        store.on_event({"type": "operation_failed", "run_id": "r9",
                        "operation": "transfer_collector_rack_to_staging_a", "ts": 2.0})
        self.assertIsNone(store.grid()["staging"]["staging-a"]["plate"])

    def test_events_without_run_id_ignored(self):
        """无 run_id 的事件 (如 telemetry) 直接忽略."""
        store = _store()
        store.on_event({"type": "telemetry", "nodes": []})
        self.assertEqual(store.list_events(), [])


class TestEffects(unittest.TestCase):
    """四种 effect 的余量迁移."""

    def setUp(self):
        self.store = _store()
        self.store.mark_plate("collector", 3, STATE_FRESH)
        self.store.mark_plate("bottle", 2, STATE_FRESH)

    def test_staging_load_then_consume_locates_plate(self):
        """整板载入把板号写进中转占用, 单件消耗据此定位到 (板, 孔)."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        self.assertEqual(self.store.grid()["staging"]["staging-a"]["plate"], 3)

        _run_script(self.store, "transfer_collector_staging_a_to_scrape", {"slot_id": 4},
                    aid="b2")
        self.assertEqual(_cell(self.store, "collector", 3, 4)["state"], STATE_USED)
        # 同孔号但别的板不受影响
        self.assertEqual(_cell(self.store, "collector", 1, 4)["state"], STATE_USED)  # 本来就空
        self.assertEqual(_cell(self.store, "collector", 3, 5)["state"], STATE_FRESH)

    def test_consume_without_staged_plate_does_not_guess(self):
        """中转占用为空时无法定位孔位: 不猜板号, 不改余量, 留一条流水."""
        _run_script(self.store, "transfer_collector_staging_a_to_scrape", {"slot_id": 4})
        self.assertEqual(_cell(self.store, "collector", 3, 4)["state"], STATE_FRESH)
        # 只看 consume 流水 (setUp 的整板盘点另有 6 条 manual)
        consume = [e for e in self.store.list_events() if e["effect"] == "consume"]
        self.assertEqual(len(consume), 1)
        self.assertIsNone(consume[0]["plate"])
        self.assertIn("无法定位孔位", consume[0]["detail"])

    def test_staging_unload_clears_and_flags_slot_mismatch(self):
        """整板卸出清空占用; 回到非载入库位时告警留痕且不迁移孔位账本."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "transfer_collector_staging_a_to_rack", {"slot_id": 5}, aid="b2")

        self.assertIsNone(self.store.grid()["staging"]["staging-a"]["plate"])
        # 孔位账本仍挂在原板 3 上, 未被迁到 5
        self.assertEqual(_cell(self.store, "collector", 3, 1)["state"], STATE_FRESH)
        self.assertEqual(_cell(self.store, "collector", 5, 1)["state"], STATE_USED)
        unload = [e for e in self.store.list_events() if e["effect"] == "staging_unload"]
        self.assertEqual(len(unload), 1)
        self.assertIn("库位不一致", unload[0]["detail"])

    def test_staging_unload_matching_slot_is_clean(self):
        """回到载入库位时不产生告警文案."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "transfer_collector_staging_a_to_rack", {"slot_id": 3}, aid="b2")
        unload = [e for e in self.store.list_events() if e["effect"] == "staging_unload"]
        self.assertEqual(unload[0]["detail"], "")

    def test_fill_stamps_sample_id_from_run_inputs(self):
        """归还件打上本次运行的 sample_id (来自 operation_start.inputs)."""
        self.store.on_event({"type": "operation_start", "run_id": "r1", "operation": "demo",
                             "inputs": {"sample_id": "S-2026-07-26-01"}, "ts": 1.0})
        _run_script(self.store, "transfer_bottle_rack_to_staging_b", {"slot_id": 2})
        _run_script(self.store, "transfer_bottle_staging_b_to_collect", {"slot_id": 1}, aid="b2")
        _run_script(self.store, "transfer_bottle_collect_to_staging_b", {"slot_id": 1}, aid="b3")

        cell = _cell(self.store, "bottle", 2, 1)
        self.assertEqual(cell["state"], STATE_USED)
        self.assertEqual(cell["sample_id"], "S-2026-07-26-01")
        self.assertEqual(self.store.grid()["summary"]["bottle"]["filled"], 1)

    def test_collector_return_put_is_bound(self):
        """收集器归还绑在 robot_collector_return_put (无 transfer 层包装)."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "transfer_collector_staging_a_to_scrape", {"slot_id": 6}, aid="b2")
        _run_script(self.store, "robot_collector_return_put",
                    {"slot_id": 6, "enter_anchor": "P70"}, aid="b3")
        fills = [e for e in self.store.list_events() if e["effect"] == "fill"]
        self.assertEqual(len(fills), 1)
        self.assertEqual((fills[0]["plate"], fills[0]["hole"]), (3, 6))


class TestTransit(unittest.TestCase):
    """在途态: 载荷此刻在哪把夹爪上.

    这一段存在的意义是取放的**中间窗口** —— 旧账本在 pick 与 put 之间仍说板在原处,
    中途取消/断电即静默失同步且不留痕。下面的用例逐条钉住那个窗口的表达。
    """

    def setUp(self):
        self.store = _store()
        self.store.mark_plate("collector", 3, STATE_FRESH)

    def _rack_present(self, kind: str, plate: int) -> bool:
        for row in self.store.grid()["rack"]:
            if row["kind"] == kind and row["plate"] == plate:
                return bool(row["present"])
        raise AssertionError(f"缺库位行 {kind} 板{plate}")

    def test_leaf_pick_puts_tray_on_gripper_and_empties_source(self):
        """取整板: 在途行记 (大爪, collector 板3), 且货架库位同时标空 —— 不能两处都有板."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        transit = self.store.grid()["transit"]
        self.assertEqual(set(transit), {"gripper_plate96"})
        row = transit["gripper_plate96"]
        self.assertEqual((row["payload"], row["kind"], row["plate"]), ("tray", "collector", 3))
        self.assertIsNone(row["hole"])
        self.assertEqual(row["from_loc"], "rack")
        self.assertFalse(self._rack_present("collector", 3), "板在爪上时库位必须已标空")
        self.assertIsNone(self.store.grid()["staging"]["staging-a"]["plate"])

    def test_leaf_place_lands_tray_and_clears_transit(self):
        """放整板: 在途行清空, 中转位记上板号; 库位保持标空 (板并没有回架)."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        _run_script(self.store, "robot_group_staging_put", {"rack_id": "collector"}, aid="b2")
        grid = self.store.grid()
        self.assertEqual(grid["transit"], {})
        self.assertEqual(grid["staging"]["staging-a"]["plate"], 3)
        self.assertFalse(self._rack_present("collector", 3))

    def test_transfer_layer_is_idempotent_after_leaf_landed(self):
        """叶子层已落位时, transfer 层的 staging_load 退化为一致性收口, 不误报"覆盖"."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        _run_script(self.store, "robot_group_staging_put", {"rack_id": "collector"}, aid="b2")
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3},
                    aid="b3")
        loads = [e for e in self.store.list_events() if e["effect"] == "staging_load"]
        self.assertEqual(len(loads), 1)
        self.assertIn("与在途落位一致", loads[0]["detail"])
        self.assertNotIn("失同步", loads[0]["detail"])
        self.assertEqual(self.store.grid()["staging"]["staging-a"]["plate"], 3)

    def test_full_round_trip_back_to_rack_is_clean(self):
        """整趟回架 (叶子取+放 → transfer 收口) 全程不产生任何失同步告警文案."""
        for args, aid, callee in (
            ({"rack_id": "collector", "slot_id": 3}, "b1", "robot_group_rack_pick"),
            ({"rack_id": "collector"}, "b2", "robot_group_staging_put"),
            ({"slot_id": 3}, "b3", "transfer_collector_rack_to_staging_a"),
            ({"rack_id": "collector"}, "b4", "robot_group_staging_pick"),
            ({"rack_id": "collector", "slot_id": 3}, "b5", "robot_group_rack_put"),
            ({"slot_id": 3}, "b6", "transfer_collector_staging_a_to_rack"),
        ):
            _run_script(self.store, callee, args, aid=aid)
        grid = self.store.grid()
        self.assertEqual(grid["transit"], {})
        self.assertIsNone(grid["staging"]["staging-a"]["plate"])
        self.assertTrue(self._rack_present("collector", 3), "回架后库位应记为在架")
        for event in self.store.list_events():
            self.assertNotIn("失同步", event["detail"], f"不该有失同步告警: {event}")

    def test_transit_row_survives_a_failed_run(self):
        """流程中途失败, 在途行必须留着 —— 这正是它相对旧账本的全部价值."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        self.store.on_event({"type": "operation_failed", "run_id": "r1",
                             "operation": "demo", "ts": 1002.0})
        self.assertEqual(set(self.store.grid()["transit"]), {"gripper_plate96"})

    def test_carried_tray_is_not_counted_as_absent(self):
        """在爪上的板库位 present=0, 但那是"在途"不是"缺板", 不得剔除它的孔位统计."""
        before = self.store.grid()["summary"]["collector"]
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        after = self.store.grid()["summary"]["collector"]
        self.assertEqual(after["absent_plates"], before["absent_plates"])
        self.assertEqual(after["fresh"], before["fresh"], "在途板的孔应照常计入")

    def test_second_pick_without_place_warns_and_overwrites(self):
        """一把爪最多一件: 上一件未清就再取, 覆盖并留痕 (主键保证不会长出两行)."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 5}, aid="b2")
        transit = self.store.grid()["transit"]
        self.assertEqual(len(transit), 1)
        self.assertEqual(transit["gripper_plate96"]["plate"], 5)
        # list_events 是新在前, 覆盖的那条即最新一条
        picks = [e for e in self.store.list_events() if e["effect"] == "transit_pick"]
        self.assertIn("覆盖未清的在途", picks[0]["detail"])

    def test_place_without_pick_changes_nothing(self):
        """只跑 put 没跑 pick: 不猜载荷身份, 不改任何位置账, 只留一条告警流水."""
        _run_script(self.store, "robot_group_staging_put", {"rack_id": "collector"})
        grid = self.store.grid()
        self.assertIsNone(grid["staging"]["staging-a"]["plate"])
        self.assertEqual(grid["transit"], {})
        places = [e for e in self.store.list_events() if e["effect"] == "transit_place"]
        self.assertIn("无在途载荷", places[0]["detail"])

    def test_rack_put_slot_mismatch_warns_without_migrating(self):
        """回架库位与在途板号不一致: 告警留痕, 按在途板号记, 绝不按入参迁移."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        _run_script(self.store, "robot_group_rack_put",
                    {"rack_id": "collector", "slot_id": 5}, aid="b2")
        self.assertTrue(self._rack_present("collector", 3), "按在途板号 3 记回架")
        places = [e for e in self.store.list_events() if e["effect"] == "transit_place"]
        self.assertIn("不一致", places[0]["detail"])
        self.assertEqual(places[0]["plate"], 3)

    def test_item_pick_records_hole_and_fill_clears_it(self):
        """单件在途: pick 记 (板, 孔) 且**不**改余量; 归还落账时顺带收口在途行."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 6}, aid="b2")
        row = self.store.grid()["transit"]["gripper_vial"]
        self.assertEqual((row["payload"], row["plate"], row["hole"]), ("item", 3, 6))
        # 消耗与否由 transfer 层负责, 在途本身不动 cells
        self.assertEqual(_cell(self.store, "collector", 3, 6)["state"], STATE_FRESH)

        _run_script(self.store, "robot_collector_return_put",
                    {"slot_id": 6, "enter_anchor": "P70"}, aid="b3")
        self.assertEqual(self.store.grid()["transit"], {}, "件回孔即离爪")

    def test_consume_does_not_touch_transit(self):
        """consume 只改余量, 绝不清在途行 —— 件此刻在哪由取放事件说了算, 不由消耗推断.

        ⚠ 这条**不**等于"消耗时件一定在爪上": 真实运行里外层 transfer 的 consume 是最后
        才落的, 那时叶子 robot_scrape_holder_put_exit 早已把件放上刮板夹具 (见
        TestStationSeat)。本用例只驱外层脚本, 故爪上仍有件 —— 锁的是 _do_consume 的边界。
        """
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 6}, aid="b2")
        _run_script(self.store, "transfer_collector_staging_a_to_scrape", {"slot_id": 6},
                    aid="b3")
        self.assertEqual(_cell(self.store, "collector", 3, 6)["state"], STATE_USED)
        self.assertEqual(set(self.store.grid()["transit"]), {"gripper_vial"})

    def test_bad_kind_arg_records_nothing(self):
        """kind 取参非法时不猜种类, 不写在途行, 只留一条流水."""
        _run_script(self.store, "robot_group_rack_pick", {"rack_id": "", "slot_id": 3})
        self.assertEqual(self.store.grid()["transit"], {})
        picks = [e for e in self.store.list_events() if e["effect"] == "transit_pick"]
        self.assertIn("耗材种类取参非法", picks[0]["detail"])

    def test_staging_pick_reads_plate_from_ledger(self):
        """从中转取整板时板号读账本 (该脚本本就没有 slot_id 入参), 中转位随之清空."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "robot_group_staging_pick", {"rack_id": "collector"}, aid="b2")
        grid = self.store.grid()
        self.assertEqual(grid["transit"]["gripper_plate96"]["plate"], 3)
        self.assertIsNone(grid["staging"]["staging-a"]["plate"])
        self.assertFalse(self._rack_present("collector", 3),
                         "板去了爪上而不是回架, 库位必须继续标空")

    def test_manual_clear_transit(self):
        """人工清账: 崩溃后板滞留在爪上, 物料页一键归位."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        cleared = self.store.clear_transit("gripper_plate96", land_at="rack")
        self.assertEqual(cleared["plate"], 3)
        self.assertEqual(self.store.grid()["transit"], {})
        self.assertTrue(self._rack_present("collector", 3))
        self.assertEqual(self.store.clear_transit("gripper_plate96"), {}, "空手清账是空操作")
        with self.assertRaises(ValueError):
            self.store.clear_transit("gripper_nonexistent")

    def test_manual_clear_without_landing_leaves_position_untouched(self):
        """去向不明时只清行, 不替人猜板落在哪."""
        _run_script(self.store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 3})
        self.store.clear_transit("gripper_plate96")
        self.assertEqual(self.store.grid()["transit"], {})
        self.assertFalse(self._rack_present("collector", 3))
        self.assertIsNone(self.store.grid()["staging"]["staging-a"]["plate"])


class TestStationSeat(unittest.TestCase):
    """站侧落位: 单件停在工位夹具上.

    这一段是 2026-08-05 补的, 补的是一个**每次正常运行都会发生**的缺陷:
    robot_collect_bottle_put / robot_scrape_holder_put_exit / robot_collect_holder_put_exit
    物理上确实松爪放件, 但绑定表里一条绑定都没有, 于是在途行从放件那刻起再没人清
    (_do_consume 刻意不碰在途), 一路挂到几分钟后归还中转板才由 _do_fill 收口。
    三维照着账本画就是瓶/桶焊在机械臂上飞完整个拍照-展开-收集周期。
    """

    def setUp(self):
        self.store = _store()
        self.store.mark_plate("collector", 3, STATE_FRESH)
        self.store.mark_plate("bottle", 2, STATE_FRESH)

    def _seats(self) -> dict:
        return {row["seat"]: row for row in self.store.grid()["payload_seats"]}

    def _pick_collector(self, hole: int = 6) -> None:
        """把 collector 板3 装上中转A, 再用小爪拔出一件."""
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": hole}, aid="b2")

    def test_seed_leaves_all_seats_empty(self):
        """三个座初始都空 —— 空座就是没有行, 不播种占位行."""
        self.assertEqual(self.store.grid()["payload_seats"], [])

    def test_put_at_station_clears_transit_and_seats_it(self):
        """放件到刮板夹具: 在途行清空, 座位行记下身份 —— 这就是"焊在机械臂上"的根治点."""
        self._pick_collector(6)
        self.assertEqual(set(self.store.grid()["transit"]), {"gripper_vial"})

        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")
        grid = self.store.grid()
        self.assertEqual(grid["transit"], {}, "放到工位后件已离爪, 在途行必须清")
        seat = self._seats()["scrape-holder"]
        self.assertEqual((seat["payload"], seat["kind"], seat["plate"], seat["hole"]),
                         ("item", "collector", 3, 6))
        self.assertEqual(seat["accepts"], "collector")
        self.assertFalse(seat["stale"], "本进程刚记的座位行不该判陈旧")

    def test_pick_from_station_recovers_identity_from_seat(self):
        """站侧取件: 脚本只有 station_id 入参, 身份只能从座位行读回, 且座位随之清空."""
        self._pick_collector(6)
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")

        _run_script(self.store, "robot_scrape_holder_pick_enter", {"station_id": "scrape"},
                    aid="b4")
        grid = self.store.grid()
        row = grid["transit"]["gripper_vial"]
        self.assertEqual((row["payload"], row["kind"], row["plate"], row["hole"]),
                         ("item", "collector", 3, 6))
        self.assertEqual(row["from_loc"], "station")
        self.assertEqual(grid["payload_seats"], [], "件被取走后座位必须空")

    def test_pick_from_empty_seat_records_nothing(self):
        """座位空着时不猜身份: 凭空造一件载荷比不记账危害大得多 (三维会挂个不存在的瓶子)."""
        _run_script(self.store, "robot_scrape_holder_pick_enter", {"station_id": "scrape"})
        self.assertEqual(self.store.grid()["transit"], {})
        picks = [e for e in self.store.list_events() if e["effect"] == "transit_pick"]
        self.assertIn("上无载荷却执行取件", picks[0]["detail"])

    def test_wrong_kind_is_rejected_and_transit_kept(self):
        """瓶不能落进收集器座: 只告警不迁移, 且**在途行保留** —— 件还在爪上是唯一能确认的事实."""
        _run_script(self.store, "transfer_bottle_rack_to_staging_b", {"slot_id": 2})
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "bottle", "slot_id": 1}, aid="b2")
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")
        grid = self.store.grid()
        self.assertEqual(grid["payload_seats"], [], "种类不符不得落座")
        self.assertEqual(set(grid["transit"]), {"gripper_vial"}, "在途行必须保留")
        places = [e for e in self.store.list_events() if e["effect"] == "transit_place"]
        self.assertIn("只收 collector", places[0]["detail"])   # list_events 按 id 倒序

    def test_bottle_round_trip_through_collect_station_is_clean(self):
        """瓶 中转B → 收集工位 → 中转B 整趟: 全程无失同步告警, 末态回到孔里.

        这是用户报的那条链的端到端形态。任何一条"无在途载荷"/"上无载荷"的流水都说明
        绑定表少了一环 —— 那正是修复前的症状。
        """
        _run_script(self.store, "transfer_bottle_rack_to_staging_b", {"slot_id": 2})
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "bottle", "slot_id": 4}, aid="b2")
        _run_script(self.store, "robot_collect_bottle_put", {"station_id": "default"}, aid="b3")
        self.assertEqual(self.store.grid()["transit"], {})
        self.assertEqual(self._seats()["collect-bottle"]["hole"], 4)

        _run_script(self.store, "robot_collect_bottle_pick", {"station_id": "default"}, aid="b4")
        _run_script(self.store, "robot_individual_put",
                    {"rack_id": "bottle", "slot_id": 4}, aid="b5")
        grid = self.store.grid()
        self.assertEqual(grid["transit"], {})
        self.assertEqual(grid["payload_seats"], [])
        noise = [e for e in self.store.list_events()
                 if "无在途载荷" in e["detail"] or "上无载荷" in e["detail"]]
        self.assertEqual(noise, [], f"正常一趟不该有失同步告警: {noise}")

    def test_second_put_on_occupied_seat_warns(self):
        """座上还有上一件时再放: 覆盖并留痕 (主键保证一个座最多一件)."""
        self._pick_collector(6)
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 5}, aid="b4")
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b5")
        self.assertEqual(self._seats()["scrape-holder"]["hole"], 5)
        places = [e for e in self.store.list_events() if e["effect"] == "transit_place"]
        self.assertIn("原停放", places[0]["detail"])           # list_events 按 id 倒序

    def test_manual_clear_payload_seat(self):
        """人工清座: 件被人从夹具上拿走时一键清账, 但**不猜它去了哪** (与 clear_transit 同纪律)."""
        self._pick_collector(6)
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")
        cleared = self.store.clear_payload_seat("scrape-holder")
        self.assertEqual((cleared["plate"], cleared["hole"]), (3, 6))
        self.assertEqual(self.store.grid()["payload_seats"], [])
        self.assertEqual(self.store.clear_payload_seat("scrape-holder"), {}, "空座清账是空操作")
        with self.assertRaises(ValueError):
            self.store.clear_payload_seat("nonexistent-holder")

    def test_clear_transit_rejects_station_as_landing(self):
        """station 不是 clear_transit 的合法落位 —— 工位座另有清账入口, 混用会写错表."""
        self._pick_collector(6)
        with self.assertRaises(ValueError):
            self.store.clear_transit("gripper_vial", land_at="station")
        self.assertEqual(set(self.store.grid()["transit"]), {"gripper_vial"}, "拒绝后不得改账")

    def test_two_holders_are_independent(self):
        """刮板夹具与收集工位夹具各占一行 —— 同种耗材两个座, 故绑定表必须显式写 seat."""
        self._pick_collector(6)
        _run_script(self.store, "robot_scrape_holder_put_exit", {}, aid="b3")
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 5}, aid="b4")
        _run_script(self.store, "robot_collect_holder_put_exit", {}, aid="b5")
        seats = self._seats()
        self.assertEqual(seats["scrape-holder"]["hole"], 6)
        self.assertEqual(seats["collect-holder"]["hole"], 5)

    def test_manual_seat_payload(self):
        """人工放件: 盘点发现座上有件而账本没有时的反向入口 (clear 的对称面)."""
        self.store.seat_payload_manually("scrape-holder", "collector", 3, 6)
        seat = self._seats()["scrape-holder"]
        self.assertEqual((seat["payload"], seat["kind"], seat["plate"], seat["hole"]),
                         ("item", "collector", 3, 6))
        self.assertFalse(seat["stale"], "人工放件是此刻亲眼所见, 不该判陈旧")
        # 刻意不动孔账: 座位账与孔位账分开更正 (与清账后的纪律对称)
        cell = next(c for c in self.store.grid()["cells"]
                    if c["kind"] == "collector" and c["plate"] == 3 and c["hole"] == 6)
        self.assertEqual(cell["state"], STATE_FRESH)
        manual = [e for e in self.store.list_events() if e["effect"] == "manual"]
        self.assertIn("放 collector 板3 孔6", manual[0]["detail"])

    def test_manual_seat_payload_rejections(self):
        """放件的四道拒绝: 非法座 / kind 准入不符 / 座已占 / 件在爪上."""
        with self.assertRaises(ValueError):
            self.store.seat_payload_manually("nonexistent", "collector", 1, 1)
        with self.assertRaises(ValueError):
            # 刮板夹具只收 collector, 硬拒防手滑
            self.store.seat_payload_manually("scrape-holder", "bottle", 1, 1)
        self.store.seat_payload_manually("scrape-holder", "collector", 3, 6)
        with self.assertRaises(ValueError):
            self.store.seat_payload_manually("scrape-holder", "collector", 3, 5)
        # 件记为在爪上时拒绝落座 (否则同一件东西账上出现两处)
        self._pick_collector(4)
        with self.assertRaises(ValueError):
            self.store.seat_payload_manually("collect-holder", "collector", 3, 4)


class TestRestartEpoch(unittest.TestCase):
    """重启持久化: 账本活过进程重启, 且能指出哪些行是上一个进程留下的.

    账本本身一直是持久的 (全部走 SQLite, 每个写路径显式 commit) —— 缺的是"这行是谁记的"
    这一位信息。没有它, 后端在搬运半途重启后 (_pending 内存态丢失, 放料的 vm_node_done
    配不上对) 那条在途行会永久残留, 而三维无从分辨"真的挂着"与"上次没走完"。
    """

    def setUp(self):
        """建一个真库文件 (不能用 :memory: —— 本类测的正是"跨进程活下来").

        清理靠 addCleanup 的 LIFO 顺序: 目录先注册故最后删, 每个 store 后注册故先关。
        不用 `with TemporaryDirectory()` 是因为 addCleanup 在测试方法**返回之后**才跑,
        那时 with 块已退出、目录已删, Windows 上未关的 sqlite 句柄会抛 PermissionError
        并盖住真正的断言失败 (踩过一次)。
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "materials.db"

    def _reopen(self) -> MaterialStore:
        """开 (或重开) 那个真库文件上的账本; 关连接交给 addCleanup 兜底."""
        topology = _topology()
        store = MaterialStore(self.path, topology=topology,
                              bindings=load_bindings(_BINDINGS_FILE, topology))
        self.addCleanup(store.close)
        return store

    def test_transit_row_survives_restart_and_is_marked_stale(self):
        """在途行逐字段活过重启, 但被标 stale —— 内容可信, "还在爪上"这件事不可信."""
        first = self._reopen()
        first.mark_plate("collector", 3, STATE_FRESH)
        _run_script(first, "robot_group_rack_pick", {"rack_id": "collector", "slot_id": 3})
        before = first.grid()
        first.close()                          # 模拟"停后端"

        second = self._reopen()                # 模拟"再起后端"
        after = second.grid()
        keep = ("carrier", "payload", "kind", "plate", "hole", "from_loc", "to_loc",
                "since_at", "run_id", "script")
        row_before = before["transit"]["gripper_plate96"]
        row_after = after["transit"]["gripper_plate96"]
        for key in keep:
            self.assertEqual(row_after[key], row_before[key], f"{key} 没活过重启")
        self.assertFalse(row_before["stale"], "本进程记的行不该判陈旧")
        self.assertTrue(row_after["stale"], "上个进程记的行必须判陈旧")
        self.assertEqual(before["transit_stale"], 0)
        self.assertEqual(after["transit_stale"], 1)

    def test_seat_row_survives_restart_and_is_marked_but_still_trusted(self):
        """座位行同样活过重启且标 stale, 但语义相反: 瓶子停在工位上, 重启不会让它跑掉.

        这条不对称正是 payload_seat 值得存在的理由 —— 把易失的"在爪上"换成耐久的"在座上"。
        前端据此分别处置: 陈旧在途行不挂载, 陈旧座位行照常生效。
        """
        first = self._reopen()
        first.mark_plate("collector", 3, STATE_FRESH)
        _run_script(first, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(first, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 6}, aid="b2")
        _run_script(first, "robot_scrape_holder_put_exit", {}, aid="b3")
        first.close()                          # 模拟"停后端"

        second = self._reopen()                # 模拟"再起后端"
        seats = {row["seat"]: row for row in second.grid()["payload_seats"]}
        self.assertEqual(seats["scrape-holder"]["plate"], 3)
        self.assertEqual(seats["scrape-holder"]["hole"], 6)
        self.assertTrue(seats["scrape-holder"]["stale"])
        # 座位陈旧不进 transit_stale 计数: 它不是"可疑", 只是"上次记的"
        self.assertEqual(second.grid()["transit_stale"], 0)

    def test_pending_is_empty_after_restart(self):
        """_pending / _run_inputs 是纯内存态, 重启必丢 —— 把它钉成显式契约.

        这正是 epoch 存在的理由: 半途重启后放料的 vm_node_done 找不到配对的 enter,
        在途行于是永久残留。不能指望它持久, 只能让它可辨认。
        """
        first = self._reopen()
        first.on_event(_enter("r1", "demo", "b1", "robot_group_rack_pick",
                              {"rack_id": "collector", "slot_id": 3}))
        self.assertTrue(first._pending, "enter 之后应有未结清节点")
        first.close()                          # 模拟"搬运半途停后端"

        second = self._reopen()
        self.assertEqual(second._pending, {})
        self.assertEqual(second._run_inputs, {})
        self.assertEqual(second.grid()["transit"], {}, "只 enter 未 done 不该记账")

    def test_legacy_db_without_epoch_column_migrates_in_place(self):
        """旧库 (payload_transit 无 epoch 列) 原地补列, 数据不丢, 旧行自动判陈旧.

        var/materials.db 是真账本 (盘点结果都在里面), 只能 ALTER TABLE 不能重建。
        旧行拿到 DEFAULT '' 而 '' 永远不等于本进程的 epoch —— 语义恰好正确。
        """
        import sqlite3
        conn = sqlite3.connect(self.path)
        conn.executescript(
            """
            CREATE TABLE payload_transit (
                carrier  TEXT PRIMARY KEY,
                payload  TEXT    NOT NULL,
                kind     TEXT    NOT NULL,
                plate    INTEGER NOT NULL,
                hole     INTEGER,
                from_loc TEXT    NOT NULL,
                to_loc   TEXT    NOT NULL DEFAULT '',
                since_at REAL    NOT NULL,
                run_id   TEXT    NOT NULL DEFAULT '',
                script   TEXT    NOT NULL DEFAULT ''
            );
            INSERT INTO payload_transit VALUES
                ('gripper_plate96', 'tray', 'collector', 4, NULL, 'rack', '', 1.0, 'r0', 's0');
            """
        )
        conn.commit()
        conn.close()

        store = self._reopen()
        row = store.grid()["transit"]["gripper_plate96"]
        self.assertEqual((row["kind"], row["plate"], row["run_id"]), ("collector", 4, "r0"))
        self.assertTrue(row["stale"], "旧库的行没有 epoch, 必须判陈旧")
        self.assertEqual(store.grid()["transit_stale"], 1)

    def test_summary_absent_plates_unchanged_across_restart(self):
        """"在爪上不算缺板"这条统计口径重启后仍成立 (它依赖在途行, 而在途行是持久的)."""
        first = self._reopen()
        first.mark_plate("collector", 3, STATE_FRESH)
        _run_script(first, "robot_group_rack_pick", {"rack_id": "collector", "slot_id": 3})
        before = first.grid()["summary"]["collector"]
        first.close()                          # 模拟"停后端"

        second = self._reopen()
        self.assertEqual(second.grid()["summary"]["collector"], before)
        self.assertEqual(before["absent_plates"], 0, "板在爪上, 不该算缺板")


class TestGridContract(unittest.TestCase):
    """grid() 的键集契约 —— 双段绊线的第一段.

    要拦的是这一类事故: 后端给 grid() 加了字段, 而前端
    three-d/twin/bindings/MaterialStateStore.normalizeSnapshot 那张**显式键白名单**没跟上,
    于是新字段被静默丢掉。2026-08-05 已发生过两次 (transit 漏了导致"托盘纹丝不动";
    seats 从来就没进过白名单), 靠人记住已经失败两次了。

    金样是 JSON 而不是 .py —— 让 Python 与 Node 读**同一份字节**, 不可能各自漂。
    重新生成: 见 web/tests/three-d/materialState.test.js 头注释里的命令。
    """

    CONTRACT = (Path(__file__).resolve().parent.parent / "web" / "tests" / "three-d"
                / "materialGrid.contract.json")

    def _full_grid(self) -> dict:
        """造一帧**全部可选段都非空**的快照: 空段会让键集缺项, 金样就锁不住那些字段."""
        store = _store()
        store.mark_plate("collector", 3, STATE_FRESH)
        _run_script(store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        _run_script(store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": 6}, aid="b2")
        _run_script(store, "robot_scrape_holder_put_exit", {}, aid="b3")
        _run_script(store, "robot_group_rack_pick",
                    {"rack_id": "collector", "slot_id": 4}, aid="b4")
        return store.grid()

    def test_grid_keys_match_contract(self):
        """键集与金样逐字相同; 不同就更新金样并去 MaterialStateStore 表态."""
        golden = json.loads(self.CONTRACT.read_text(encoding="utf-8"))
        grid = self._full_grid()
        hint = ("grid() 的键集变了。若是有意新增: 重跑金样生成脚本, 再去 "
                "web/src/three-d/twin/bindings/MaterialStateStore.js 的 "
                "EVENT_KEY_TO_SNAPSHOT_KEY 显式表态 —— 否则新字段会被静默丢掉。")
        self.assertEqual(sorted(grid), golden["top"], hint)
        self.assertEqual(sorted(next(iter(grid["transit"].values()))),
                         golden["transitRow"], hint)
        self.assertEqual(sorted(grid["payload_seats"][0]), golden["payloadSeatRow"], hint)
        self.assertEqual(sorted(grid["cells"][0]), golden["cellRow"], hint)
        self.assertEqual(sorted(grid["seats"][0]), golden["seatRow"], hint)

    def test_full_grid_fixture_really_covers_every_section(self):
        """金样赖以成立的前提: 那一帧里每个可选段都真的非空 (否则锁了个寂寞)."""
        grid = self._full_grid()
        for key in ("transit", "payload_seats", "cells", "seats", "magazines", "bottles",
                    "staging", "rack"):
            self.assertTrue(grid[key], f"{key} 段是空的, 金样锁不住它的行键")


class TestPanelSingleFireAccounting(unittest.TestCase):
    """维护面板单发动作 (POST /api/actions/{name}/run) 的 step_done 扣账."""

    @staticmethod
    def _step_done(action: str, params: dict, *, status: str = "DONE") -> dict:
        """造一条合成路径的 step_done (形状照 api/app.py::_execute_with_live_events)."""
        return {"type": "step_done", "run_id": "p1", "step": "a1", "action": action,
                "index": 0, "params": params, "status": status, "ts": 2000.0}

    def _volume(self, store: MaterialStore, bottle: str) -> float:
        for row in store.grid()["bottles"]:
            if row["bottle"] == bottle:
                return float(row["volume_ml"])
        raise AssertionError(f"缺瓶 {bottle}")

    def test_panel_single_fire_draws_and_is_traceable(self):
        """单发上液真扣账, 且流水标 [面板单发] 供人辨认与撤销."""
        store = _store()
        store.set_bottle("eluent", 500.0)
        store.on_event(self._step_done("collect.collect", {"solvent_volume_ml": 12.0}))
        self.assertAlmostEqual(self._volume(store, "eluent"), 488.0, places=3)
        draws = [e for e in store.list_events() if e["effect"] == "liquid_draw"]
        self.assertEqual(len(draws), 1)
        self.assertTrue(draws[0]["detail"].startswith("[面板单发]"))

    def test_vm_path_does_not_double_count(self):
        """VM 只发 vm_node_*, 合成路径只发 step_*, 两条互斥 —— 走 VM 时绝不重复扣."""
        store = _store()
        store.set_bottle("eluent", 500.0)
        store.on_event({"type": "vm_node_enter", "run_id": "r1", "script": "demo", "aid": "a1",
                        "op": "call", "action": "collect.collect",
                        "args": {"solvent_volume_ml": 12.0}, "ts": 1000.0})
        store.on_event({"type": "vm_node_done", "run_id": "r1", "script": "demo", "aid": "a1",
                        "op": "call", "action": "collect.collect", "status": "DONE",
                        "ts": 1001.0})
        self.assertAlmostEqual(self._volume(store, "eluent"), 488.0, places=3)
        self.assertEqual(
            len([e for e in store.list_events() if e["effect"] == "liquid_draw"]), 1)

    def test_failed_step_does_not_draw(self):
        """单发失败不扣账 (与 vm_node_done 的终态门同一条纪律)."""
        store = _store()
        store.set_bottle("eluent", 500.0)
        store.on_event(self._step_done("collect.collect", {"solvent_volume_ml": 12.0},
                                       status="ERROR"))
        self.assertAlmostEqual(self._volume(store, "eluent"), 500.0, places=3)

    def test_missing_volume_param_warns_instead_of_drawing_zero(self):
        """表单没填液量时留痕告警, **不**默默按 0 扣 —— 否则"试发过没记上"与"确实没抽"同形."""
        store = _store()
        store.set_bottle("eluent", 500.0)
        store.on_event(self._step_done("collect.collect", {}))
        self.assertAlmostEqual(self._volume(store, "eluent"), 500.0, places=3)
        draws = [e for e in store.list_events() if e["effect"] == "liquid_draw"]
        self.assertEqual(len(draws), 1)
        self.assertIn("[面板单发]", draws[0]["detail"])
        self.assertIn("液量取参非法", draws[0]["detail"])

    def test_manual_panel_steps_are_not_material_actions(self):
        """manual_service 的气缸/点动也发 step_*, 但动作名不在绑定表里, 天然不误伤."""
        store = _store()
        store.set_bottle("eluent", 500.0)
        store.on_event(self._step_done("manual.cylinder.staging_a_locator", {"on": True}))
        self.assertAlmostEqual(self._volume(store, "eluent"), 500.0, places=3)
        # 只该有 set_bottle 那条 manual 盘点流水, 不该多出任何记账
        self.assertEqual([e["effect"] for e in store.list_events()], ["manual"])


class TestNextFresh(unittest.TestCase):
    """预填建议查询 —— 核心不变量在此."""

    def test_returns_none_on_empty_ledger(self):
        """空账本无建议 (前端据此退回流程 default)."""
        store = _store()
        self.assertIsNone(store.next_fresh("collector"))
        self.assertIsNone(store.next_fresh("bottle"))

    def test_rejects_unknown_kind(self):
        self.assertIsNone(_store().next_fresh("widget"))

    def test_picks_lowest_plate_then_hole(self):
        """中转空时在全部板上找, 按 (板, 孔) 升序取首个."""
        store = _store()
        store.mark("collector", 5, 4, STATE_FRESH)
        store.mark("collector", 2, 6, STATE_FRESH)
        store.mark("collector", 2, 3, STATE_FRESH)
        hit = store.next_fresh("collector")
        self.assertEqual((hit["rack_slot"], hit["hole"]), (2, 3))
        self.assertFalse(hit["from_staging"])
        self.assertIsNone(hit["staging_plate"])

    def test_restricts_to_staged_plate(self):
        """中转已装板时只在该板上找孔 —— 单件取放的孔号必须落在当前中转板上."""
        store = _store()
        store.mark("collector", 2, 1, STATE_FRESH)   # 别的板有货, 但不在中转区
        store.mark("collector", 4, 5, STATE_FRESH)
        store.set_staging("staging-a", 4)
        hit = store.next_fresh("collector")
        self.assertEqual((hit["rack_slot"], hit["hole"]), (4, 5))
        self.assertTrue(hit["from_staging"])
        self.assertEqual(hit["staging_plate"], 4)

    def test_staged_plate_exhausted_returns_none(self):
        """中转板已耗尽时不越板建议 (需先换板)."""
        store = _store()
        store.mark("collector", 2, 1, STATE_FRESH)
        store.set_staging("staging-a", 4)            # 4 号板全空
        self.assertIsNone(store.next_fresh("collector"))

    def test_returned_full_bottle_is_never_offered_again(self):
        """核心不变量: 满瓶归还原孔后不会被当空瓶再取."""
        store = _store()
        store.mark_plate("bottle", 2, STATE_FRESH)
        store.on_event({"type": "operation_start", "run_id": "r1", "operation": "demo",
                        "inputs": {"sample_id": "S-1"}, "ts": 1.0})
        _run_script(store, "transfer_bottle_rack_to_staging_b", {"slot_id": 2})
        _run_script(store, "transfer_bottle_staging_b_to_collect", {"slot_id": 1}, aid="b2")
        _run_script(store, "transfer_bottle_collect_to_staging_b", {"slot_id": 1}, aid="b3")

        # 1 号孔现装着满瓶, 建议必须跳到 2 号孔
        hit = store.next_fresh("bottle")
        self.assertEqual(hit["hole"], 2)
        # 把余下 5 孔都消耗掉后, 满瓶那一孔仍然不会被建议
        for hole in range(2, HOLES_PER_PLATE + 1):
            _run_script(store, "transfer_bottle_staging_b_to_collect", {"slot_id": hole},
                        aid=f"c{hole}")
        self.assertIsNone(store.next_fresh("bottle"))


class TestPlateMagazines(unittest.TestCase):
    """玻璃板仓计数 (纯软件; 升降光电是边界搜索开关, 测不出数量)."""

    def test_seeds_two_empty_magazines(self):
        mags = {m["magazine"]: m for m in _store().grid()["magazines"]}
        self.assertEqual(set(mags), {"feed", "waste"})
        self.assertEqual(mags["feed"]["count"], 0)
        self.assertEqual(mags["feed"]["label"], "上料仓 (1Z)")

    def test_load_cycle_decrements_feed(self):
        """feedlift_load_cycle 一次 = 上料仓 −1."""
        store = _store()
        store.set_magazine("feed", 10)
        _run_script(store, "feedlift_load_cycle", {})
        mags = {m["magazine"]: m["count"] for m in store.grid()["magazines"]}
        self.assertEqual(mags["feed"], 9)
        self.assertEqual(mags["waste"], 0)

    def test_unload_cycle_increments_waste(self):
        """feedlift_unload_cycle 一次 = 下料仓 +1."""
        store = _store()
        _run_script(store, "feedlift_unload_cycle", {})
        mags = {m["magazine"]: m["count"] for m in store.grid()["magazines"]}
        self.assertEqual(mags["waste"], 1)
        self.assertEqual(mags["feed"], 0)

    def test_take_from_empty_clamps_at_zero_and_flags(self):
        """账本记为 0 还继续取: 计数停在 0 并留告警痕, 不变负数."""
        store = _store()
        _run_script(store, "feedlift_load_cycle", {})
        mags = {m["magazine"]: m["count"] for m in store.grid()["magazines"]}
        self.assertEqual(mags["feed"], 0)
        events = [e for e in store.list_events() if e["effect"] == "plate_take"]
        self.assertIn("账实已失同步", events[0]["detail"])

    def test_non_done_does_not_count(self):
        store = _store()
        store.set_magazine("feed", 5)
        _run_script(store, "feedlift_load_cycle", {}, status="ERROR")
        mags = {m["magazine"]: m["count"] for m in store.grid()["magazines"]}
        self.assertEqual(mags["feed"], 5)

    def test_manual_set_validates(self):
        store = _store()
        with self.assertRaises(ValueError):
            store.set_magazine("attic", 1)
        with self.assertRaises(ValueError):
            store.set_magazine("feed", -1)


class TestLiquidBottles(unittest.TestCase):
    """溶剂瓶余量扣减 (量全部来自动作参数, 无标定常数)."""

    def setUp(self):
        self.store = _store()
        for bottle in ("solvent_1", "solvent_2", "solvent_3", "solvent_4", "eluent"):
            self.store.set_bottle(bottle, 500.0)

    def _call(self, action: str, args: dict, *, status: str = "DONE"):
        """驱动一次 op:call 动作的 enter+done 事件对."""
        self.store.on_event({"type": "vm_node_enter", "run_id": "r1", "script": "demo",
                             "aid": "b1", "op": "call", "action": action, "args": args,
                             "ts": 1000.0})
        self.store.on_event({"type": "vm_node_done", "run_id": "r1", "script": "demo",
                             "aid": "b1", "op": "call", "action": action,
                             "status": status, "ts": 1001.0})

    def _vol(self, bottle: str) -> float:
        for row in self.store.grid()["bottles"]:
            if row["bottle"] == bottle:
                return float(row["volume_ml"])
        raise AssertionError(f"缺瓶 {bottle}")

    def test_up_liquid_splits_by_ratio(self):
        """展缸上液: 总量 = volume x count, 按 4 路权重分摊."""
        self._call("develop.fill", {
            "target_tank": 1, "solvent_volume_ml": 10.0, "up_liquid_repeat_count": 2,
            "solvent_ratio_1": 3.0, "solvent_ratio_2": 1.0,
            "solvent_ratio_3": 0.0, "solvent_ratio_4": 0.0,
        })
        # 总量 20mL, 权重 3:1 -> 溶剂1 扣 15, 溶剂2 扣 5, 3/4 不动
        self.assertAlmostEqual(self._vol("solvent_1"), 485.0, places=3)
        self.assertAlmostEqual(self._vol("solvent_2"), 495.0, places=3)
        self.assertAlmostEqual(self._vol("solvent_3"), 500.0, places=3)
        self.assertAlmostEqual(self._vol("solvent_4"), 500.0, places=3)

    def test_count_defaults_to_one(self):
        """count_from 缺省时按单趟记."""
        self._call("develop.fill", {
            "solvent_volume_ml": 4.0,
            "solvent_ratio_1": 1.0, "solvent_ratio_2": 0.0,
            "solvent_ratio_3": 0.0, "solvent_ratio_4": 0.0,
        })
        self.assertAlmostEqual(self._vol("solvent_1"), 496.0, places=3)

    def test_all_zero_ratio_draws_nothing(self):
        """配比权重全零 = 没走那路溶剂, 不扣并留痕."""
        self._call("develop.fill", {
            "solvent_volume_ml": 10.0, "solvent_ratio_1": 0.0, "solvent_ratio_2": 0.0,
            "solvent_ratio_3": 0.0, "solvent_ratio_4": 0.0,
        })
        self.assertAlmostEqual(self._vol("solvent_1"), 500.0, places=3)
        events = [e for e in self.store.list_events() if e["effect"] == "liquid_draw"]
        self.assertIn("权重全为零", events[0]["detail"])

    def test_eluent_single_bottle_without_ratio(self):
        """收集洗脱: 无 ratio_from, 全额记到 bottles[0]."""
        self._call("collect.collect", {"solvent_volume_ml": 2.5, "liquid_repeat_count": 4})
        self.assertAlmostEqual(self._vol("eluent"), 490.0, places=3)

    def test_rinse_fill_single_solvent(self):
        self._call("develop.rinse_fill", {"solvent_volume_ml": 3.0, "solvent_ratio_1": 1.0})
        self.assertAlmostEqual(self._vol("solvent_1"), 497.0, places=3)

    def test_insufficient_clamps_to_zero_and_flags(self):
        """余量不足: 扣到 0 并告警留痕 (账本只反映已抽这件事, 不裁决)."""
        self.store.set_bottle("eluent", 5.0)
        self._call("collect.collect", {"solvent_volume_ml": 10.0, "liquid_repeat_count": 1})
        self.assertAlmostEqual(self._vol("eluent"), 0.0, places=3)
        events = [e for e in self.store.list_events() if e["effect"] == "liquid_draw"]
        self.assertIn("余量不足", events[0]["detail"])

    def test_bad_volume_arg_draws_nothing(self):
        self._call("collect.collect", {"liquid_repeat_count": 1})
        self.assertAlmostEqual(self._vol("eluent"), 500.0, places=3)

    def test_non_done_does_not_draw(self):
        self._call("collect.collect", {"solvent_volume_ml": 10.0}, status="ERROR")
        self.assertAlmostEqual(self._vol("eluent"), 500.0, places=3)

    def test_unbound_action_ignored(self):
        """未登记的动作不产生扣减 (setUp 的 5 条 manual 盘点流水不算)."""
        self._call("develop.drain", {"target_tank": 1})
        draws = [e for e in self.store.list_events() if e["effect"] == "liquid_draw"]
        self.assertEqual(draws, [])

    def test_manual_set_validates(self):
        with self.assertRaises(ValueError):
            self.store.set_bottle("beaker", 1.0)
        with self.assertRaises(ValueError):
            self.store.set_bottle("eluent", -1.0)


class TestTopology(unittest.TestCase):
    """物料拓扑加载与闭集校验 (五类物料/位置/传感器的单一真源)."""

    def test_live_topology_loads_six_categories(self):
        """现役 config/material_topology.yaml: 六类, 盘位 3 处位置, 上料 2 处.

        类目顺序即左 Dock 顺序, 故这里连顺序一起钉。板位 (seat) 与件位 (holder) 都是
        无位置无传感器的类目, 但两者不可合并: seat 记薄层板停在点样座/刮板台 (纯人工账),
        holder 记单件耗材停在工位夹具上 (由流程事件自动记账, 且决定三维把哪个孔画空)。
        """
        topo = _topology()
        self.assertEqual([c.key for c in topo.categories],
                         ["tray", "holder", "feed", "glass", "solvent", "seat"])
        by_key = {c.key: c for c in topo.categories}
        self.assertEqual([loc.id for loc in by_key["tray"].locations],
                         ["rack", "staging-a", "staging-b"])
        self.assertEqual([loc.id for loc in by_key["feed"].locations], ["feed-1", "feed-2"])
        self.assertEqual(topo.magazines, {"feed": ("上料仓 (1Z)", 30),
                                          "waste": ("下料仓 (2Z)", 30)})
        self.assertEqual(set(topo.bottles),
                         {"solvent_1", "solvent_2", "solvent_3", "solvent_4", "eluent"})
        self.assertEqual(by_key["seat"].locations, ())
        self.assertEqual(set(topo.seats),
                         {"spot_seat", "scrape_table"} | {f"tank_{i}" for i in range(1, 9)})
        # 收集瓶位是件位类唯一有传感器的位置 (IX8.1); 极性同族推定, 实证前不判定
        holder_locs = by_key["holder"].locations
        self.assertEqual([loc.id for loc in holder_locs], ["collect-bottle"])
        self.assertEqual((holder_locs[0].sensor.byte, holder_locs[0].sensor.bit), ("IX8", 1))
        self.assertFalse(holder_locs[0].sensor.verified)
        # kind 是放件时的准入约束, 不是描述 —— 连它一起钉住
        self.assertEqual(topo.payload_seats, {
            "scrape-holder": ("刮板夹具 (接粉收集器位)", "collector"),
            "collect-holder": ("收集工位夹具 (接粉收集器位)", "collector"),
            "collect-bottle": ("收集工位 (样品瓶位)", "bottle"),
        })

    def test_rack_has_twelve_bits_others_single(self):
        """货架展开 12 位; 中转/上料各单点."""
        locs = {loc.id: loc for loc in _topology().locations}
        self.assertEqual(len(locs["rack"].rack_bits), 12)
        self.assertIsNone(locs["rack"].sensor)
        for lid in ("staging-a", "staging-b", "feed-1", "feed-2"):
            self.assertEqual(locs[lid].rack_bits, ())
            self.assertIsNotNone(locs[lid].sensor)

    def test_byte_names_cover_all_sensors(self):
        """对账需读的字节集 = 拓扑用到的全部字节, 去重."""
        self.assertEqual(set(_topology().byte_names()),
                         {"IX8", "IX9", "IX10", "IX11", "IX12"})

    def test_bytes_declared_in_plc_nodes(self):
        """拓扑引用的每个输入字节必须在 plc_nodes.yaml 里声明 —— 否则真机读不到而静默失真."""
        import yaml
        nodes = yaml.safe_load((_CONFIG_DIR / "plc_nodes.yaml").read_text(encoding="utf-8"))
        declared = set(nodes.get("nodes") or nodes.get("host_computer") or {})
        if not declared:      # 结构不同则退回全文匹配, 保证这条钉子不因 schema 变动而空转
            text = (_CONFIG_DIR / "plc_nodes.yaml").read_text(encoding="utf-8")
            declared = {name for name in _topology().byte_names() if f"{name}:" in text}
        for name in _topology().byte_names():
            self.assertIn(name, declared, f"拓扑用了 {name} 但 plc_nodes.yaml 未声明")

    def _write(self, tmp: str, body: str) -> Path:
        path = Path(tmp) / "t.yaml"
        path.write_text(body, encoding="utf-8")
        return path

    def test_rejects_bad_topology(self):
        """闭集校验: schema/极性/位号/字节名/id 重复 全部启动即失败."""
        head = "schema: ptlc.material_topology/v1\ncategories:\n- key: k\n  label: K\n  locations:\n  - id: a\n    label: A\n"
        cases = [
            # schema 错
            "schema: wrong/v9\ncategories: []\n",
            # categories 空
            "schema: ptlc.material_topology/v1\ncategories: []\n",
            # 缺 polarity (刻意无默认: 猜错极性会让整页在位全反)
            head + "    sensor: {name: S, byte: IX8, bit: 2}\n",
            # polarity 非法
            head + "    sensor: {name: S, byte: IX8, bit: 2, polarity: maybe}\n",
            # polarity 裸 no (yaml 1.1 布尔陷阱, 必须写 "no"; 已实际踩过)
            head + "    sensor: {name: S, byte: IX8, bit: 2, polarity: no}\n",
            # 位号越界
            head + "    sensor: {name: S, byte: IX8, bit: 8, polarity: nc}\n",
            # 字节名格式错
            head + "    sensor: {name: S, byte: QB8, bit: 2, polarity: nc}\n",
            # 货架位数不是 12
            head.replace("  - id: a\n    label: A\n",
                         "  - id: a\n    label: A\n    rack_slots: true\n")
            + "    sensor: {name: S, polarity: nc, rack_bits: [{byte: IX11, bit: 0}]}\n",
        ]
        for body in cases:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError, msg=body[:70]):
                    load_topology(self._write(tmp, body))

    def test_rejects_duplicate_ids(self):
        body = ("schema: ptlc.material_topology/v1\ncategories:\n"
                "- key: k\n  label: K\n  locations:\n"
                "  - {id: a, label: A, sensor: {name: S, byte: IX8, bit: 0, polarity: nc}}\n"
                "  - {id: a, label: B, sensor: {name: T, byte: IX8, bit: 1, polarity: nc}}\n")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_topology(self._write(tmp, body))


class TestPresenceReconcile(unittest.TestCase):
    """位置级在位对账 (按拓扑遍历, 各位置按自己的极性折算)."""

    # 全 12 位料库为"有板" (货架 NC -> 原始位取 0), 四个单点为"空" (NO -> 原始位取 0)
    def _bytes(self, **over) -> dict:
        base = {"IX8": 0x00, "IX9": 0x00, "IX10": 0x00, "IX11": 0x00, "IX12": 0x00}
        base.update(over)
        return base

    def test_nc_polarity_inverts_raw_bit(self):
        """常闭 NC: 原始位 0 = 有料; 常开 NO 则相反 —— 同一原始位折算出相反结果."""
        from eit_ptlc.runtime.material_store import SensorBit
        nc = SensorBit(name="s", byte="IX8", bit=2, polarity="nc")
        no = SensorBit(name="s", byte="IX8", bit=2, polarity="no")
        raw_set = 0b00000100        # bit2 = 1
        self.assertFalse(nc.present(raw_set))
        self.assertTrue(no.present(raw_set))
        self.assertTrue(nc.present(0b00000000))
        self.assertFalse(no.present(0b00000000))

    def test_rack_all_present_matches_empty_staging(self):
        """货架 12 路极性未实证 (verified:false) ⇒ 只显读数不判定 (ok=None), 不再判红绿."""
        store = _store()
        rows = store.reconcile_presence(self._bytes())["rows"]
        rack = [r for r in rows if r["location_id"].startswith("rack.")]
        self.assertEqual(len(rack), 12)
        for r in rack:
            self.assertIsNone(r["ok"], r)
            self.assertEqual(r["note"], "极性未核实, 不判定")
            self.assertTrue(r["expected"])           # 期望值照算照显 (人工账初值=在架)

    def test_staged_plate_expected_absent(self):
        """板已搬去中转 ⇒ 该库位期望为空; 但货架未实证 ⇒ 只给期望不判定."""
        store = _store()
        store.set_staging("staging-a", 3)
        rows = store.reconcile_presence(self._bytes())["rows"]
        staged_row = next(r for r in rows if r["location_id"] == "rack.collector.3")
        self.assertFalse(staged_row["expected"])
        self.assertIsNone(staged_row["ok"])
        others = [r for r in rows if r["location_id"].startswith("rack.")
                  and r["location_id"] != "rack.collector.3"]
        self.assertTrue(all(r["expected"] for r in others))
        # 货架行不判定 (中转A 自己的可判定不一致与本用例无关, 不在此断)
        self.assertEqual([r for r in rows if r["ok"] is False
                          and r["location_id"].startswith("rack.")], [])

    def test_missing_plate_flagged(self):
        """传感器报无板 (bottle 板2 = 料库检测8 = IX11 bit7): 未实证 ⇒ 读数照显但不判红."""
        store = _store()
        rows = store.reconcile_presence(self._bytes(IX11=0b10000000))["rows"]
        row = next(r for r in rows if r["location_id"] == "rack.bottle.2")
        self.assertFalse(row["present"])
        self.assertTrue(row["expected"])
        self.assertIsNone(row["ok"])
        self.assertIn("极性未核实", row["note"])
        self.assertEqual([r for r in rows if r["ok"] is False], [])

    def test_staging_sensor_vs_ledger(self):
        """中转: 账本记板号即期望有料; 传感器报空则不一致 —— 用户要的那套对账."""
        store = _store()
        # IX10 bit2 = 0 -> NO -> 中转A 无料; 而账本记着板 3 -> 不一致
        store.set_staging("staging-a", 3)
        rows = store.reconcile_presence(self._bytes(IX10=0x00))["rows"]
        row = next(r for r in rows if r["location_id"] == "staging-a")
        self.assertFalse(row["present"])
        self.assertTrue(row["expected"])
        self.assertFalse(row["ok"])
        self.assertIn("账本记着板 3", row["note"])

        # 传感器报有料 (NO -> bit2 = 1) -> 一致
        rows = store.reconcile_presence(self._bytes(IX10=0b00000100))["rows"]
        row = next(r for r in rows if r["location_id"] == "staging-a")
        self.assertTrue(row["present"])
        self.assertTrue(row["ok"])

    def test_staging_empty_ledger_with_sensor_material(self):
        """账本记中转为空但传感器报有料 -> 也算不一致."""
        store = _store()
        rows = store.reconcile_presence(self._bytes(IX8=0b00000100))["rows"]
        row = next(r for r in rows if r["location_id"] == "staging-b")
        self.assertTrue(row["present"])
        self.assertFalse(row["expected"])
        self.assertFalse(row["ok"])
        self.assertIn("账本记", row["note"])

    def test_feed_locations_never_mismatch(self):
        """上料两处无软件账 ⇒ expected/ok 为 None, 不计入不一致."""
        store = _store()
        result = store.reconcile_presence(self._bytes(IX9=0b00000011))
        feed = [r for r in result["rows"] if r["category"] == "feed"]
        self.assertEqual(len(feed), 2)
        for row in feed:
            self.assertIsNone(row["expected"])
            self.assertIsNone(row["ok"])
            self.assertTrue(row["present"])          # IX9 bit0/1 = 1 -> NO -> 有料
        # 上料不贡献 mismatches
        self.assertEqual(result["mismatches"],
                         sum(1 for r in result["rows"] if r["ok"] is False))

    def test_verified_flag_passed_through(self):
        """极性是否已实证随行透出 —— 页面据此标注"极性未核实"."""
        rows = _store().reconcile_presence(self._bytes())["rows"]
        feed = next(r for r in rows if r["location_id"] == "feed-1")
        self.assertTrue(feed["verified"])            # 上样料架检测1 托盘对照实测过 (NO)
        rack = next(r for r in rows if r["location_id"].startswith("rack."))
        self.assertFalse(rack["verified"])           # 货架未供电, 极性未实证

    def test_snapshot_lands_in_grid(self):
        """对账快照进 grid; 货架未实证不判定, 可判定的中转不符仍计入 mismatches."""
        store = _store()
        store.set_staging("staging-a", 3)
        # 中转A 账本记着板 3 而传感器报空 (IX10 bit2 = 0, NO) -> 唯一可判定的不一致
        store.reconcile_presence(self._bytes(IX10=0x00, IX11=0b10000000))
        grid = store.grid()
        self.assertEqual(len(grid["presence"]), 17)   # 12 货架 + 2 中转 + 2 上料 + 1 收集瓶位
        self.assertEqual(grid["presence_mismatches"], 1)
        rack_rows = [r for r in grid["presence"] if r["location_id"].startswith("rack.")]
        self.assertEqual(len(rack_rows), 12)
        self.assertTrue(all(r["ok"] is None for r in rack_rows))
        self.assertEqual([c["key"] for c in grid["topology"]["categories"]],
                         ["tray", "holder", "feed", "glass", "solvent", "seat"])

    def test_reconcile_does_not_touch_cells_or_staging(self):
        """只报不改: 传感器只知有/无, 不得覆盖孔级余量或中转占用."""
        store = _store()
        store.mark_plate("collector", 1, STATE_FRESH)
        store.set_staging("staging-a", 1)
        before = store.grid()
        store.reconcile_presence(self._bytes(IX11=0xFF, IX8=0xFF, IX9=0xFF, IX10=0xFF))
        after = store.grid()
        self.assertEqual(before["cells"], after["cells"])
        self.assertEqual(before["staging"], after["staging"])
        self.assertEqual(before["rack"], after["rack"])

    def test_rejects_missing_byte(self):
        """缺任何一个拓扑用到的字节即抛错, 不拿缺省 0 凑一张假快照."""
        with self.assertRaises(ValueError):
            _store().reconcile_presence({"IX11": 0, "IX12": 0})

    def test_verified_gate_is_generic(self):
        """判定门挂在 verified 上而非 hard-code 货架: 合成 verified:true 的货架拓扑恢复判定,
        且对比对象是人工在架账."""
        body = (
            "schema: ptlc.material_topology/v1\n"
            "categories:\n"
            "- key: tray\n"
            "  label: 盘位\n"
            "  locations:\n"
            "  - id: rack\n"
            "    label: 货架\n"
            "    rack_slots: true\n"
            "    sensor:\n"
            "      name: 料库检测1..12\n"
            "      polarity: nc\n"
            "      verified: true\n"
            "      rack_bits:\n"
            + "".join(f"      - {{byte: IX11, bit: {b}}}\n" for b in range(8))
            + "".join(f"      - {{byte: IX12, bit: {b}}}\n" for b in range(4))
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.yaml"
            path.write_text(body, encoding="utf-8")
            from eit_ptlc.runtime.material_store import load_topology as _load
            store = MaterialStore(":memory:", topology=_load(path), bindings=None)
        bytes_all_zero = {"IX11": 0x00, "IX12": 0x00}     # NC + 0 = 全部报有板
        rows = store.reconcile_presence(bytes_all_zero)["rows"]
        self.assertTrue(all(r["ok"] is True for r in rows), rows)
        store.set_rack_presence("collector", 1, False)
        rows = store.reconcile_presence(bytes_all_zero)["rows"]
        row = next(r for r in rows if r["location_id"] == "rack.collector.1")
        self.assertFalse(row["expected"])
        self.assertIs(row["ok"], False)
        self.assertIn("无板", row["note"])


class TestRackOccupancy(unittest.TestCase):
    """货架库位板级在架人工账 (rack_occupancy): 播种/翻转/不变量/决策过滤."""

    def _present(self, store: MaterialStore, kind: str, plate: int) -> int:
        row = next(r for r in store.grid()["rack"]
                   if r["kind"] == kind and r["plate"] == plate)
        return int(row["present"])

    def test_seeds_twelve_present_rows(self):
        """播种 12 行, 初值全在架 (与旧推导语义"不是中转板就在架上"一致)."""
        grid = _store().grid()
        self.assertEqual(len(grid["rack"]), 12)
        self.assertTrue(all(r["present"] for r in grid["rack"]))
        for kind in KINDS:
            self.assertEqual(grid["summary"][kind]["absent_plates"], 0)

    def test_set_rack_presence_toggles_and_logs(self):
        """有板/无板翻转落库并记 manual 流水."""
        store = _store()
        store.set_rack_presence("collector", 2, False)
        self.assertEqual(self._present(store, "collector", 2), 0)
        self.assertEqual(store.grid()["summary"]["collector"]["absent_plates"], 1)
        events = store.list_events(limit=5)
        self.assertTrue(any(e["effect"] == "manual" and "无板" in e["detail"]
                            for e in events), events)
        store.set_rack_presence("collector", 2, True)
        self.assertEqual(self._present(store, "collector", 2), 1)
        self.assertEqual(store.grid()["summary"]["collector"]["absent_plates"], 0)

    def test_set_rack_presence_validates(self):
        """非法 kind/板号即抛错."""
        store = _store()
        with self.assertRaises(ValueError):
            store.set_rack_presence("widget", 1, False)
        with self.assertRaises(ValueError):
            store.set_rack_presence("collector", 7, False)

    def test_staged_plate_rejects_manual_presence(self):
        """板在中转位时拒改 (两个方向都拒): 在架态由中转占用维护."""
        store = _store()
        store.set_staging("staging-a", 3)
        with self.assertRaises(ValueError):
            store.set_rack_presence("collector", 3, False)
        with self.assertRaises(ValueError):
            store.set_rack_presence("collector", 3, True)

    def test_manual_staging_maintains_invariant(self):
        """人工中转标记维护不变量: 落位→0, 换板→旧板回 1, 置空→回 1; 中转板不算缺板."""
        store = _store()
        store.set_staging("staging-a", 3)
        self.assertEqual(self._present(store, "collector", 3), 0)
        self.assertEqual(store.grid()["summary"]["collector"]["absent_plates"], 0)
        store.set_staging("staging-a", 5)
        self.assertEqual(self._present(store, "collector", 3), 1)
        self.assertEqual(self._present(store, "collector", 5), 0)
        store.set_staging("staging-a", None)
        self.assertEqual(self._present(store, "collector", 5), 1)

    def test_vm_staging_effects_maintain_invariant(self):
        """VM staging_load/unload 与人工路径经同一 helper 维护在架账."""
        store = _store()
        store.mark_plate("collector", 3, STATE_FRESH)
        _run_script(store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        self.assertEqual(self._present(store, "collector", 3), 0)
        _run_script(store, "transfer_collector_staging_a_to_rack", {"slot_id": 3}, aid="b2")
        self.assertEqual(self._present(store, "collector", 3), 1)

    def test_migration_seeds_from_existing_staging(self):
        """旧库升级 (无 rack_occupancy 表): 建行时正在中转的板置 0, 其余置 1."""
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.db"
            first = MaterialStore(path, topology=_topology(), bindings=None)
            first.set_staging("staging-a", 2)
            first.close()
            conn = sqlite3.connect(str(path))
            conn.execute("DROP TABLE rack_occupancy")     # 模拟升级前的旧库
            conn.commit()
            conn.close()

            second = MaterialStore(path, topology=_topology(), bindings=None)
            rack = {(r["kind"], r["plate"]): int(r["present"])
                    for r in second.grid()["rack"]}
            self.assertEqual(rack[("collector", 2)], 0)
            self.assertEqual(sum(rack.values()), 11)
            second.close()

    def test_next_fresh_skips_absent(self):
        """中转空时取孔建议跳过无板库位; 标回有板即恢复."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.mark_plate("collector", 5, STATE_FRESH)
        store.set_rack_presence("collector", 2, False)
        self.assertEqual(store.next_fresh("collector")["rack_slot"], 5)
        store.set_rack_presence("collector", 2, True)
        self.assertEqual(store.next_fresh("collector")["rack_slot"], 2)

    def test_plan_staging_skips_absent(self):
        """换板决策不选无板库位."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.mark_plate("collector", 5, STATE_FRESH)
        store.set_rack_presence("collector", 2, False)
        plan = store.plan_staging("collector")
        self.assertEqual(plan["op"], "PUT_NEW")
        self.assertEqual(plan["rack_slot"], 5)

    def test_plan_staging_exhausted_when_only_absent_has_fresh(self):
        """唯一有料的板不在架 ⇒ EXHAUSTED (提示盘点), 不是可等待的 BLOCKED."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.set_rack_presence("collector", 2, False)
        self.assertEqual(store.plan_staging("collector")["op"], "EXHAUSTED")

    def test_plan_staging_none_reuse_unaffected_by_invariant(self):
        """中转板 present=0 是"在中转"不是缺板: NONE 原地复用必须仍能命中."""
        store = _store()
        store.mark_plate("collector", 3, STATE_FRESH)
        store.set_staging("staging-a", 3)
        plan = store.plan_staging("collector")
        self.assertEqual(plan["op"], "NONE")
        self.assertEqual(plan["staged_plate"], 3)

    def test_absent_reserved_holes_report_exhausted_not_blocked(self):
        """无板库位上滞留的他人预留不撑 BLOCKED (板都不在, 等释放也等不来)."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        other = store.plan_staging("collector", reserve_for="s-other")
        self.assertEqual(other["op"], "PUT_NEW")      # s-other 的孔级预留落在板 2
        store.set_rack_presence("collector", 2, False)
        plan = store.plan_staging("collector", reserve_for="s-me")
        self.assertEqual(plan["op"], "EXHAUSTED")

    def test_reserve_count_ignores_absent_but_counts_staged(self):
        """批次准入: 无板库位的 FRESH 不算可用; 正在中转的板照算."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.set_rack_presence("collector", 2, False)
        self.assertFalse(store.reserve_count("s1", "collector"))
        store.set_rack_presence("collector", 2, True)
        self.assertTrue(store.reserve_count("s1", "collector"))
        store.release_reservations("s1")

        store.mark_plate("bottle", 3, STATE_FRESH)
        store.set_staging("staging-b", 3)             # 板 3 present=0 但在中转, 余量可用
        self.assertTrue(store.reserve_count("s2", "bottle"))

    def test_summary_excludes_absent_plates(self):
        """无板库位的孔不计入任何统计; absent_plates 供页面显示「缺板 N」."""
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.mark_plate("collector", 5, STATE_FRESH)
        store.set_rack_presence("collector", 2, False)
        summary = store.grid()["summary"]["collector"]
        self.assertEqual(summary["fresh"], 6)         # 只剩板 5 的 6 孔
        self.assertEqual(summary["used"], 24)         # 其余 4 板 x 6 孔
        self.assertEqual(summary["absent_plates"], 1)

    def test_grid_expected_follows_manual_account(self):
        """标无板后 grid 重算的 presence.expected 变 False; 货架未实证 ok 恒 None."""
        store = _store()
        store.reconcile_presence(
            {"IX8": 0, "IX9": 0, "IX10": 0, "IX11": 0, "IX12": 0})
        store.set_rack_presence("collector", 4, False)
        grid = store.grid()
        row = next(r for r in grid["presence"]
                   if r["location_id"] == "rack.collector.4")
        self.assertFalse(row["expected"])
        self.assertIsNone(row["ok"])
        self.assertEqual(grid["presence_mismatches"], 0)


class TestSeatOccupancy(unittest.TestCase):
    """单板停放位有板/无板人工账 (seat_occupancy): 点样座 / 刮板拍照台.

    这两处无任何在位传感器, 故只有人工账。需求刻意把它限定为"只供展示与人工同步",
    所以本类除了常规的播种/翻转/校验/落盘, 还有一条看门狗
    (test_seat_untouched_by_decisions) 钉住它不得渗进任何流程决策。
    """

    def _seat(self, store: MaterialStore, seat: str) -> dict:
        return next(r for r in store.grid()["seats"] if r["seat"] == seat)

    def test_seeded_absent(self):
        """播种全部座, 初值无板且阶段空白 (同"账本不谎称有货"准则), 带拓扑显示名."""
        grid = _store().grid()
        seats = {r["seat"]: r for r in grid["seats"]}
        self.assertEqual(set(seats),
                         {"spot_seat", "scrape_table"} | {f"tank_{i}" for i in range(1, 9)},
                         "2026-08-13 补了 8 个展缸位: 此前'板在哪个缸'只存在于调度器缸池")
        self.assertTrue(all(r["present"] is False for r in grid["seats"]))
        self.assertTrue(all(r["stage"] == "blank" for r in grid["seats"]),
                        "空座的阶段一律 blank —— 阶段是板的属性, 座上没板就无从谈起")
        self.assertIn("点样座", seats["spot_seat"]["label"])
        self.assertIn("刮板", seats["scrape_table"]["label"])
        self.assertIn("3 号展缸", seats["tank_3"]["label"])

    def test_topology_exposes_seats_without_sensors(self):
        """拓扑透出 seats 且不带传感器: 对账读字节的清单不因新增这类而变."""
        store = _store()
        cat = next(c for c in store.topology_dto()["categories"] if c["key"] == "seat")
        self.assertEqual([s["id"] for s in cat["seats"]],
                         ["spot_seat", "scrape_table"] + [f"tank_{i}" for i in range(1, 9)])
        self.assertEqual(cat["locations"], [])
        self.assertNotIn("spot_seat", str(store.topology.byte_names()))

    def test_set_seat_presence_toggles_and_logs(self):
        """有板/无板翻转落库并记 manual 流水 (detail 写清座名与新状态)."""
        store = _store()
        store.set_seat_presence("spot_seat", True)
        self.assertTrue(self._seat(store, "spot_seat")["present"])
        self.assertFalse(self._seat(store, "scrape_table")["present"])
        self.assertGreater(self._seat(store, "spot_seat")["updated_at"], 0)

        events = store.list_events(kind="seat", limit=5)
        self.assertTrue(any(e["effect"] == "manual" and "有板" in e["detail"]
                            for e in events), events)
        self.assertEqual(events[0]["to_state"], "PRESENT")
        self.assertEqual(events[0]["from_state"], "ABSENT")

        store.set_seat_presence("spot_seat", False)
        self.assertFalse(self._seat(store, "spot_seat")["present"])
        self.assertEqual(store.list_events(kind="seat", limit=1)[0]["to_state"], "ABSENT")

    def test_set_seat_presence_validates(self):
        """未知座名即抛错 (座号闭集由拓扑约束, 不写死在代码里)."""
        store = _store()
        with self.assertRaises(ValueError):
            store.set_seat_presence("nope", True)
        with self.assertRaises(ValueError):
            store.set_seat_presence("", True)

    def test_seat_untouched_by_decisions(self):
        """看门狗: 板位账不得渗进任何流程决策与统计口径.

        需求明写"暂时不嵌入流程的判断"。把两个座都置有板后, 取孔建议 / 换板决策 /
        批次准入 / 统计必须与置有板之前逐字相同 —— 哪天有人顺手把 seat 接进
        plan_staging 的 SQL, 这条会立刻红。
        """
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.mark_plate("bottle", 4, STATE_FRESH)
        before = (store.next_fresh("collector"), store.next_fresh("bottle"),
                  store.plan_staging("collector"), store.plan_staging("bottle"),
                  store.grid()["summary"])

        store.set_seat_presence("spot_seat", True)
        store.set_seat_presence("scrape_table", True)

        after = (store.next_fresh("collector"), store.next_fresh("bottle"),
                 store.plan_staging("collector"), store.plan_staging("bottle"),
                 store.grid()["summary"])
        self.assertEqual(before, after)
        # 统计口径也不新增 seat 字段 (summary 是耗材孔账的口径, 薄层板不是孔位耗材)
        for kind in KINDS:
            self.assertEqual(set(store.grid()["summary"][kind]),
                             {"fresh", "used", "filled", "absent_plates"})

    def test_presence_reconcile_ignores_seats(self):
        """在位对账不含这两处 (硬件无板检测输入), 差异数不受人工账影响."""
        store = _store()
        store.set_seat_presence("spot_seat", True)
        result = store.reconcile_presence(
            {"IX8": 0, "IX9": 0, "IX10": 0, "IX11": 0, "IX12": 0})
        self.assertFalse(any("seat" in r["location_id"] or "scrape_table" in r["location_id"]
                             for r in result["rows"]), result["rows"])

    def test_survives_restart(self):
        """跨重启保留 (需求核心): 重开同一库文件时播种不覆盖人工盘点结果."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.db"
            first = MaterialStore(path, topology=_topology(), bindings=None)
            first.set_seat_presence("scrape_table", True)
            first.close()

            second = MaterialStore(path, topology=_topology(), bindings=None)
            self.assertTrue(self._seat(second, "scrape_table")["present"])
            self.assertFalse(self._seat(second, "spot_seat")["present"])
            second.close()


class TestSuggestInputs(unittest.TestCase):
    """输入框预填建议解析 (前端不做推断, 全在此)."""

    def setUp(self):
        self.store = _store()
        self.store.mark_plate("collector", 3, STATE_FRESH)
        self.store.mark_plate("bottle", 4, STATE_FRESH)

    def test_bare_slot_id_resolved_by_binding_plate(self):
        """裸 slot_id + staging_load 绑定 -> 货架库位号."""
        out = self.store.suggest_inputs("transfer_collector_rack_to_staging_a", ["slot_id"])
        self.assertEqual(out["inputs"], {"slot_id": 3})
        self.assertIn("货架库位", out["source"]["slot_id"])

    def test_bare_slot_id_resolved_by_binding_hole(self):
        """裸 slot_id + consume 绑定 -> 板上孔号."""
        self.store.set_staging("staging-a", 3)
        self.store.mark("collector", 3, 1, STATE_USED)      # 1 号孔已用, 应建议 2 号
        out = self.store.suggest_inputs("transfer_collector_staging_a_to_scrape", ["slot_id"])
        self.assertEqual(out["inputs"], {"slot_id": 2})
        self.assertIn("孔号", out["source"]["slot_id"])

    def test_named_vars_resolved_by_name(self):
        """demo 式显式变量名自带耗材种类与 rack/hole 语义, 不依赖绑定表."""
        out = self.store.suggest_inputs("single_sample_demo",
                                        ["collector_rack_slot", "bottle_rack_slot",
                                         "collector_slot", "bottle_slot"])
        self.assertEqual(out["inputs"]["collector_rack_slot"], 3)
        self.assertEqual(out["inputs"]["bottle_rack_slot"], 4)
        self.assertEqual(out["inputs"]["collector_slot"], 1)
        self.assertEqual(out["inputs"]["bottle_slot"], 1)

    def test_unrelated_vars_get_no_suggestion(self):
        """非库位类变量不给建议 (前端退回脚本 default)."""
        out = self.store.suggest_inputs("transfer_collector_rack_to_staging_a",
                                        ["sample_id", "save_dir", "enter_anchor"])
        self.assertEqual(out["inputs"], {})

    def test_unbound_script_with_bare_slot_id_gets_nothing(self):
        """未登记脚本的裸 slot_id 无从判断 kind, 不猜."""
        out = self.store.suggest_inputs("robot_group_rack_pick", ["rack_id", "slot_id"])
        self.assertEqual(out["inputs"], {})

    def test_no_stock_yields_no_suggestion(self):
        """账本无余量时不给建议 (端点返回空 inputs, 前端用 default)."""
        empty = _store()
        out = empty.suggest_inputs("transfer_collector_rack_to_staging_a", ["slot_id"])
        self.assertEqual(out["inputs"], {})


class TestManualInventory(unittest.TestCase):
    """人工盘点."""

    def test_mark_plate_sets_six_holes(self):
        store = _store()
        store.mark_plate("bottle", 6, STATE_FRESH)
        for hole in range(1, HOLES_PER_PLATE + 1):
            self.assertEqual(_cell(store, "bottle", 6, hole)["state"], STATE_FRESH)
        self.assertEqual(store.grid()["summary"]["bottle"]["fresh"], 6)

    def test_mark_clears_sample_id(self):
        """重新盘为空瓶时清掉旧样品号 (成品已被取走)."""
        store = _store()
        store.mark("bottle", 1, 1, STATE_USED, sample_id="S-old")
        self.assertEqual(_cell(store, "bottle", 1, 1)["sample_id"], "S-old")
        store.mark("bottle", 1, 1, STATE_FRESH)
        self.assertEqual(_cell(store, "bottle", 1, 1)["sample_id"], "")

    def test_rejects_bad_addressing(self):
        store = _store()
        for args in (("widget", 1, 1, STATE_FRESH), ("bottle", 0, 1, STATE_FRESH),
                     ("bottle", 7, 1, STATE_FRESH), ("bottle", 1, 0, STATE_FRESH),
                     ("bottle", 1, 7, STATE_FRESH)):
            with self.assertRaises(ValueError, msg=str(args)):
                store.mark(*args)
        with self.assertRaises(ValueError):
            store.mark("bottle", 1, 1, "MAYBE")

    def test_set_staging_roundtrip_and_validation(self):
        store = _store()
        store.set_staging("staging-b", 5)
        self.assertEqual(store.grid()["staging"]["staging-b"]["plate"], 5)
        store.set_staging("staging-b", None)
        self.assertIsNone(store.grid()["staging"]["staging-b"]["plate"])
        with self.assertRaises(ValueError):
            store.set_staging("staging-z", 1)
        with self.assertRaises(ValueError):
            store.set_staging("staging-a", 9)

    def test_manual_actions_leave_audit_trail(self):
        """人工盘点也留追溯流水."""
        store = _store()
        store.mark("collector", 1, 1, STATE_FRESH)
        events = store.list_events(kind="collector", plate=1, hole=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["effect"], "manual")
        self.assertEqual(events[0]["to_state"], STATE_FRESH)


class _FakeExecutor:
    """假执行器: 一律返回 DONE (本测试只关心 VM 发出的事件, 不关心动作实现)."""

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result={})


def _script(name: str, variables: list, body: list) -> dict:
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": name, "label": name,
            "vars": variables, "body": body}


class TestVmIntegration(unittest.TestCase):
    """与真 VmThread 联跑: 钉住 operation_start 必须携带根入参 (决断 4).

    这是本方案唯一的 VM 改动。若 operation_start 丢掉 inputs, 面板直跑 transfer_* 时
    slot_id 在事件流里无处可寻, 账本静默记不到而所有纯 store 测试仍会全绿 ——
    故必须由真 VmThread 驱动一次来钉。
    """

    def _drive(self, doc: dict, inputs: dict, store: MaterialStore):
        """用真 VmThread 跑一遍, 事件同时喂给 store 与本地列表."""
        events: list[dict] = []

        def emit(event: dict) -> None:
            events.append(event)
            store.on_event(event)

        thread = VmThread(doc, executor=_FakeExecutor(), res_gate=ResourceGate(), emit=emit)
        asyncio.run(thread.run(inputs))
        return events

    def test_operation_start_carries_root_inputs(self):
        """operation_start 事件必须带 inputs (参数快照)."""
        doc = _script("transfer_collector_rack_to_staging_a",
                      [{"name": "slot_id", "scope": "local", "type": "INT",
                        "io": "in", "default": 1}],
                      [{"op": "call", "action": "noop"}])
        store = _store()
        events = self._drive(doc, {"slot_id": 4}, store)

        starts = [e for e in events if e["type"] == "operation_start"]
        self.assertEqual(len(starts), 1)
        self.assertIn("inputs", starts[0], "operation_start 丢了 inputs, 根脚本记账会静默失效")
        self.assertEqual(starts[0]["inputs"], {"slot_id": 4})

    def test_root_bound_script_records_through_real_vm(self):
        """面板直跑 transfer_* (根脚本) 经真 VM 落账到中转占用."""
        doc = _script("transfer_collector_rack_to_staging_a",
                      [{"name": "slot_id", "scope": "local", "type": "INT",
                        "io": "in", "default": 1}],
                      [{"op": "call", "action": "noop"}])
        store = _store()
        store.mark_plate("collector", 4, STATE_FRESH)
        self._drive(doc, {"slot_id": 4}, store)
        self.assertEqual(store.grid()["staging"]["staging-a"]["plate"], 4)

    def test_nested_bound_script_records_through_real_vm(self):
        """经 run_script 调用的绑定脚本落账 (demo/full 流程的形态)."""
        child = _script("transfer_collector_staging_a_to_scrape",
                        [{"name": "slot_id", "scope": "local", "type": "INT",
                          "io": "in", "default": 1}],
                        [{"op": "call", "action": "noop"}])
        parent = _script("wrapper", [],
                         [{"op": "run_script",
                           "script": "transfer_collector_staging_a_to_scrape",
                           "inputs": {"slot_id": {"lit": 5}}, "outputs": {}}])
        store = _store()
        store.mark_plate("collector", 2, STATE_FRESH)
        store.set_staging("staging-a", 2)

        events: list[dict] = []

        def emit(event: dict) -> None:
            events.append(event)
            store.on_event(event)

        thread = VmThread(parent, executor=_FakeExecutor(), res_gate=ResourceGate(),
                          resolve_script=lambda n: child, emit=emit)
        asyncio.run(thread.run({}))

        # 子脚本的 enter 事件须带被调脚本名与求值后的入参 (记账所依赖的两个字段)
        enters = [e for e in events
                  if e["type"] == "vm_node_enter" and e.get("op") == "run_script"]
        self.assertEqual(len(enters), 1)
        self.assertEqual(enters[0]["action"], "transfer_collector_staging_a_to_scrape")
        self.assertEqual(enters[0]["args"], {"slot_id": 5})
        self.assertEqual(_cell(store, "collector", 2, 5)["state"], STATE_USED)


class TestPowderAndLiquidFill(unittest.TestCase):
    """刮取产粉量的两段式落账, 与洗脱液注进样品瓶 / 粉桶标已淋洗."""

    #: 一次刮取的动作 result (形状照 cnc_path.ScrapeArrays.as_action_result 的三个粉量键)
    ARM = {"scrape_volume_mm3": 768.4, "scrape_area_mm2": 480.0, "scrape_area_source": "contour"}

    def setUp(self):
        self.store = _store()
        self.store.set_bottle("eluent", 500.0)

    def _call(self, action: str, args: dict, *, result: Optional[dict] = None,
              run_id: str = "r1", aid: str = "c1", status: str = "DONE") -> None:
        """驱动一次 op:call 动作的 enter+done 事件对 (done 带 result)."""
        self.store.on_event({"type": "vm_node_enter", "run_id": run_id, "script": "demo",
                             "aid": aid, "op": "call", "action": action, "args": args,
                             "ts": 1000.0})
        self.store.on_event({"type": "vm_node_done", "run_id": run_id, "script": "demo",
                             "aid": aid, "op": "call", "action": action, "status": status,
                             "result": result or {}, "ts": 1001.0})

    def _seat_collector(self, hole: int = 6, *, seat_script: str = "robot_scrape_holder_put_exit",
                        aid: str = "s1") -> None:
        """把 3 号板经中转 A 上的 hole 号孔的粉桶取出并放到某工位夹具上.

        必须先走 transfer_*_rack_to_staging_* —— robot_individual_pick 是从**中转区**取件,
        中转为空时它只会告警不记在途, 于是座位行永远建不起来 (与 _full_grid 同款铺垫)。
        """
        self.store.mark_plate("collector", 3, STATE_FRESH)
        _run_script(self.store, "transfer_collector_rack_to_staging_a",
                    {"slot_id": 3}, aid=f"{aid}l")
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "collector", "slot_id": hole}, aid=f"{aid}p")
        _run_script(self.store, seat_script, {}, aid=f"{aid}q")

    def _seat_bottle(self, hole: int = 2) -> None:
        """把 1 号板经中转 B 上的 hole 号孔的样品瓶放到收集工位瓶位上."""
        self.store.mark_plate("bottle", 1, STATE_FRESH)
        _run_script(self.store, "transfer_bottle_rack_to_staging_b", {"slot_id": 1}, aid="t1l")
        _run_script(self.store, "robot_individual_pick",
                    {"rack_id": "bottle", "slot_id": hole}, aid="t1p")
        _run_script(self.store, "robot_collect_bottle_put", {}, aid="t1q")

    def test_two_stage_powder_fill(self):
        """cnc_path 算量 -> scrape_finish 落账到刮板夹具上那只桶所属的托盘格."""
        self._seat_collector(hole=6)
        self._call("photoscrape.cnc_path", {}, result=self.ARM, aid="c1")
        # arm 阶段一格都不许动 —— 这一刻一粒粉都还没刮
        self.assertEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 0)

        self._call("photoscrape.scrape_finish", {}, aid="c2")
        self.assertAlmostEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 768.4)
        fills = [e for e in self.store.list_events() if e["effect"] == "powder_fill"]
        self.assertEqual(len(fills), 1)
        self.assertIn("480.0mm²(contour)", fills[0]["detail"])

    def test_last_arm_wins_not_accumulated(self):
        """cnc_path 一次运行里跑好几遍 (候选/重画/占位), 只有最后一次的量落账."""
        self._seat_collector(hole=6)
        for i, volume in enumerate((100.0, 200.0, 768.4)):
            self._call("photoscrape.cnc_path", {},
                       result={**self.ARM, "scrape_volume_mm3": volume}, aid=f"c{i}")
        self._call("photoscrape.scrape_finish", {}, aid="cf")
        self.assertAlmostEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 768.4)

    def test_scrape_finish_without_arm_records_nothing(self):
        """没 arm 过就 scrape_finish (面板单发 / 中途重启后端): 不加粉, 只留一条流水."""
        self._seat_collector(hole=6)
        self._call("photoscrape.scrape_finish", {}, aid="cf")
        self.assertEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 0)
        fills = [e for e in self.store.list_events() if e["effect"] == "powder_fill"]
        self.assertEqual(len(fills), 1)
        self.assertIn("没有 armed 的刮取量", fills[0]["detail"])

    def test_empty_seat_records_nothing_but_leaves_trace(self):
        """刮板夹具上没件时不编数, 只留痕 —— 身份只有座位行知道, 猜不得."""
        self._call("photoscrape.cnc_path", {}, result=self.ARM, aid="c1")
        self._call("photoscrape.scrape_finish", {}, aid="c2")
        fills = [e for e in self.store.list_events() if e["effect"] == "powder_fill"]
        self.assertEqual(len(fills), 1)
        self.assertIn("上没有件", fills[0]["detail"])

    def test_placeholder_zero_volume_records_nothing(self):
        """安全占位 (体积 0) 不加粉 —— 跳过刮板的路径不该长出粉柱."""
        self._seat_collector(hole=6)
        self._call("photoscrape.cnc_path", {},
                   result={"scrape_volume_mm3": 0.0, "scrape_area_mm2": 0.0,
                           "scrape_area_source": ""}, aid="c1")
        self._call("photoscrape.scrape_finish", {}, aid="c2")
        self.assertEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 0)

    def test_arm_does_not_survive_run_end(self):
        """一次运行结束即丢暂存: 下一次运行的 scrape_finish 不该捡到上一轮的量."""
        self._seat_collector(hole=6)
        self._call("photoscrape.cnc_path", {}, result=self.ARM, aid="c1")
        self.store.on_event({"type": "operation_done", "run_id": "r1",
                             "operation": "demo", "ts": 1002.0})
        self._call("photoscrape.scrape_finish", {}, run_id="r1", aid="c2")
        self.assertEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 0)

    def test_panel_single_fire_cannot_bridge_two_runs(self):
        """面板单发: 每次 /actions/{name}/run 是独立 run_id, 且其后紧跟 operation_done
        会清掉暂存 —— 于是单发 cnc_path 再单发 scrape_finish 绝不会记出一笔粉,
        只留一条"没有 armed 的量"的流水。凭空编数比不记更糟。
        """
        self._seat_collector(hole=6)
        # 单发 cnc_path (合成路径: step_done 带 result, 随后 operation_done)
        self.store.on_event({"type": "step_done", "run_id": "p1", "step": "a1",
                             "action": "photoscrape.cnc_path", "index": 0, "params": {},
                             "status": "DONE", "result": self.ARM, "ts": 2000.0})
        self.store.on_event({"type": "operation_done", "run_id": "p1",
                             "operation": "photoscrape.cnc_path", "ts": 2001.0})
        # 另一次单发 scrape_finish (新 run_id)
        self.store.on_event({"type": "step_done", "run_id": "p2", "step": "a1",
                             "action": "photoscrape.scrape_finish", "index": 0, "params": {},
                             "status": "DONE", "result": {}, "ts": 2002.0})
        self.assertEqual(_cell(self.store, "collector", 3, 6)["powder_mm3"], 0)
        fills = [e for e in self.store.list_events() if e["effect"] == "powder_fill"]
        self.assertEqual(len(fills), 1)
        self.assertIn("没有 armed 的刮取量", fills[0]["detail"])

    def test_collect_fills_bottle_and_marks_collector_eluted(self):
        """洗脱: eluent 扣量、瓶格记液量、桶格标已淋洗 —— 三件事同一次动作."""
        self._seat_collector(hole=5, seat_script="robot_collect_holder_put_exit", aid="h1")
        self._seat_bottle(hole=2)
        self._call("collect.collect",
                   {"solvent_volume_ml": 10.0, "liquid_repeat_count": 2}, aid="c1")

        self.assertAlmostEqual(
            next(b["volume_ml"] for b in self.store.grid()["bottles"]
                 if b["bottle"] == "eluent"), 480.0, places=3)
        self.assertAlmostEqual(_cell(self.store, "bottle", 1, 2)["liquid_ml"], 20.0)
        self.assertEqual(_cell(self.store, "collector", 3, 5)["eluted"], 1)

    def test_eluted_logged_once_across_rounds(self):
        """洗脱循环跑多次只留一条 powder_eluted 流水 (已是 1 时不再留痕)."""
        self._seat_collector(hole=5, seat_script="robot_collect_holder_put_exit", aid="h1")
        self._seat_bottle(hole=2)
        for i in range(3):
            self._call("collect.collect", {"solvent_volume_ml": 2.0}, aid=f"c{i}")
        marks = [e for e in self.store.list_events() if e["effect"] == "powder_eluted"]
        self.assertEqual(len(marks), 1)
        # 但液量是逐轮累加的
        self.assertAlmostEqual(_cell(self.store, "bottle", 1, 2)["liquid_ml"], 6.0)

    def test_develop_fill_touches_no_cell(self):
        """零回归: develop.fill 没有 to_seat/wet_seat, 一格内容物都不许动."""
        self._seat_collector(hole=5, seat_script="robot_collect_holder_put_exit", aid="h1")
        self._seat_bottle(hole=2)
        self.store.set_bottle("solvent_1", 500.0)
        self._call("develop.fill", {
            "solvent_volume_ml": 10.0, "up_liquid_repeat_count": 2,
            "solvent_ratio_1": 1.0, "solvent_ratio_2": 0.0,
            "solvent_ratio_3": 0.0, "solvent_ratio_4": 0.0,
        }, aid="c1")
        self.assertAlmostEqual(
            next(b["volume_ml"] for b in self.store.grid()["bottles"]
                 if b["bottle"] == "solvent_1"), 480.0, places=3)
        self.assertEqual(_cell(self.store, "bottle", 1, 2)["liquid_ml"], 0)
        self.assertEqual(_cell(self.store, "collector", 3, 5)["eluted"], 0)

    def test_consume_zeroes_contents(self):
        """FRESH->USED 即件离开托盘孔上工位: 内容物一并归零 (跨周期不累积的唯一保障)."""
        self.store.mark_plate("collector", 3, STATE_FRESH)
        _run_script(self.store, "transfer_collector_rack_to_staging_a", {"slot_id": 3})
        self.store.set_cell_amount("collector", 3, 4, powder_mm3=500.0, eluted=True)
        _run_script(self.store, "transfer_collector_staging_a_to_scrape",
                    {"slot_id": 4}, aid="b9")

        cell = _cell(self.store, "collector", 3, 4)
        self.assertEqual(cell["state"], STATE_USED)
        self.assertEqual(cell["powder_mm3"], 0)
        self.assertEqual(cell["eluted"], 0)
        consumes = [e for e in self.store.list_events() if e["effect"] == "consume"]
        self.assertIn("清掉上一轮残留内容物", consumes[-1]["detail"])

    def test_mark_fresh_zeroes_but_mark_used_keeps(self):
        """标 FRESH = 换上新件 -> 清零; 标 USED+样品号 = 登记成品待取 -> 不清."""
        self.store.set_cell_amount("collector", 2, 2, powder_mm3=500.0, eluted=True)
        self.store.mark("collector", 2, 2, STATE_USED, sample_id="S-1")
        self.assertAlmostEqual(_cell(self.store, "collector", 2, 2)["powder_mm3"], 500.0,
                               msg="成品待取不该被抹掉内容物")
        self.store.mark("collector", 2, 2, STATE_FRESH)
        self.assertEqual(_cell(self.store, "collector", 2, 2)["powder_mm3"], 0)
        self.assertEqual(_cell(self.store, "collector", 2, 2)["eluted"], 0)


class TestCellAmounts(unittest.TestCase):
    """单件内容物余量三列 (粉 mm³ / 液 mL / 已淋洗): 迁移、人工覆盖、NaN 防线."""

    def test_migration_adds_columns_without_touching_rows(self):
        """旧库(没有这三列)打开时原地补列, 旧行拿到 0 且 state/sample_id 分毫不动.

        var/materials.db 是真账本(盘点结果都在里面), 只能 ALTER 不能重建 —— 这条就是
        那次迁移的看门狗。手写旧 schema 而不是"删列", 因为 SQLite 的 DROP COLUMN 有版本
        门槛, 手写才真的复现了升级前那个库长什么样。
        """
        import sqlite3

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "materials.db"
            # ── 升级前的 material_cells: 只有 7 列 ──────────────────────────
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE material_cells (
                    kind       TEXT    NOT NULL,
                    plate      INTEGER NOT NULL,
                    hole       INTEGER NOT NULL,
                    state      TEXT    NOT NULL,
                    sample_id  TEXT    NOT NULL DEFAULT '',
                    updated_at REAL    NOT NULL,
                    run_id     TEXT    NOT NULL DEFAULT '',
                    PRIMARY KEY (kind, plate, hole)
                );
                """
            )
            conn.execute(
                "INSERT INTO material_cells(kind, plate, hole, state, sample_id,"
                " updated_at, run_id) VALUES ('collector', 2, 4, 'FRESH', 'S-77', 123.0, 'r9')")
            conn.commit()
            conn.close()

            store = MaterialStore(path, topology=_topology(), bindings=None)
            try:
                cell = _cell(store, "collector", 2, 4)
                # 盘点结果一个字节都不许动
                self.assertEqual(cell["state"], STATE_FRESH)
                self.assertEqual(cell["sample_id"], "S-77")
                # 新列补齐且旧行取 0 —— "没记过"就是 0, 不编造
                self.assertEqual(cell["powder_mm3"], 0)
                self.assertEqual(cell["liquid_ml"], 0)
                self.assertEqual(cell["eluted"], 0)
            finally:
                store.close()

    def test_set_cell_amount_leaves_unnamed_fields_alone(self):
        """缺省的字段不动: 清粉量不会顺带抹掉已淋洗标志, 反之亦然."""
        store = _store()
        store.set_cell_amount("collector", 1, 1, powder_mm3=768.4, eluted=True)
        cell = _cell(store, "collector", 1, 1)
        self.assertAlmostEqual(cell["powder_mm3"], 768.4)
        self.assertEqual(cell["eluted"], 1)

        store.set_cell_amount("collector", 1, 1, powder_mm3=0.0)   # 只清粉量
        cell = _cell(store, "collector", 1, 1)
        self.assertEqual(cell["powder_mm3"], 0)
        self.assertEqual(cell["eluted"], 1, "只给 powder_mm3 时不该动 eluted")

        store.set_cell_amount("bottle", 2, 3, liquid_ml=20.5)
        self.assertAlmostEqual(_cell(store, "bottle", 2, 3)["liquid_ml"], 20.5)

    def test_set_cell_amount_rejects_bad_input(self):
        """负数/非有限数/三个全缺 一律抛错, 不静默返回成功."""
        store = _store()
        with self.assertRaises(ValueError):
            store.set_cell_amount("collector", 1, 1)                       # 三个全缺
        with self.assertRaises(ValueError):
            store.set_cell_amount("collector", 1, 1, powder_mm3=-1.0)
        with self.assertRaises(ValueError):
            store.set_cell_amount("collector", 1, 1, powder_mm3=float("nan"))
        with self.assertRaises(ValueError):
            store.set_cell_amount("bottle", 1, 1, liquid_ml=float("inf"))
        with self.assertRaises(ValueError):
            store.set_cell_amount("collector", 9, 1, powder_mm3=1.0)       # 孔位非法

    def test_grid_stays_json_serializable_without_nan(self):
        """grid() 必须恒能以 allow_nan=False 序列化.

        这不是洁癖: runtime/material_feedback 的指纹用 allow_nan=False, 一个 NaN 落进
        cells 会让那个 0.5s 推流循环**每一轮都抛异常**(catch 后只打日志), 于是
        material_state 永不再发、整条实时链静默停摆, 而前端只表现为"账本卡住了"。
        入库前的两道 math.isfinite 就是为这条服务的。
        """
        store = _store()
        store.set_cell_amount("collector", 1, 1, powder_mm3=768.4, eluted=True)
        store.set_cell_amount("bottle", 1, 1, liquid_ml=20.5)
        json.dumps(store.grid(), allow_nan=False)   # 抛 ValueError 即失败

    def test_grid_exposes_amounts(self):
        """grid().cells 必须带出三列 —— 三维与物料页都从这里取数."""
        store = _store()
        store.set_cell_amount("collector", 3, 6, powder_mm3=768.4, eluted=True)
        row = next(c for c in store.grid()["cells"]
                   if c["kind"] == "collector" and c["plate"] == 3 and c["hole"] == 6)
        self.assertAlmostEqual(row["powder_mm3"], 768.4)
        self.assertEqual(row["eluted"], 1)
        self.assertEqual(row["liquid_ml"], 0)


class TestMagazineObserver(unittest.TestCase):
    """板仓改写观察者: 仿真沙盒把账面回灌板堆物理模型的唯一出口.

    三条用例对应观察者契约的三个面 —— 谁触发、谁不触发、载荷是什么。
    第三条 (流程记账不触发) 是"刻意解耦"的看门狗, 不是凑数。
    """

    def _observed(self, store) -> list:
        """给 store 挂一个记录型观察者, 返回它的收件箱 (列表)."""
        inbox: list = []
        store.set_magazine_observer(lambda counts, detail: inbox.append((counts, detail)))
        return inbox

    def test_set_magazine_notifies_with_the_new_count(self):
        """人工盘点 / 光电盘点校正 -> 观察者收到 {该仓: 新张数}."""
        store = _store()
        inbox = self._observed(store)
        store.set_magazine("feed", 17)
        self.assertEqual(len(inbox), 1, "set_magazine 应恰好通知一次")
        counts, detail = inbox[0]
        self.assertEqual(counts, {"feed": 17})
        self.assertIn("人工盘点", detail)

    def test_import_rows_notifies_only_when_the_magazine_table_is_present(self):
        """整表采纳 -> 通知一次且给全部板仓的导入后张数; 部分快照不含板仓表则不通知."""
        source = _store()
        source.set_magazine("feed", 12)
        source.set_magazine("waste", 9)
        snapshot = source.export_rows()

        target = _store()
        inbox = self._observed(target)
        target.import_rows({"plate_magazines": snapshot["plate_magazines"]})
        self.assertEqual(len(inbox), 1, "带板仓表的导入应通知一次")
        counts, _ = inbox[0]
        self.assertEqual(counts, {"feed": 12, "waste": 9},
                         "载荷应是导入后的全部板仓张数, 不是单仓增量")

        inbox.clear()
        target.import_rows({"liquid_bottles": snapshot["liquid_bottles"]})
        self.assertEqual(inbox, [], "不含板仓表的部分快照不该通知 —— "
                                    "那会把回灌变成周期性覆写")

    def test_flow_bookkeeping_never_notifies(self):
        """流程记账的 ±1 **刻意不通知** —— 沙盒板堆模型自己按物理事件增减.

        这条是设计决策的看门狗: 若哪天有人把 _do_plate 也接上观察者, 沙盒会双重扣减,
        并重新引入 mock/behavior/feedlift.py 头注论证过的时序矛盾 (账本扣减发生在
        脚本 DONE, 晚于流程中段第二次 probe)。
        """
        store = _store()
        store.set_magazine("feed", 5)
        inbox = self._observed(store)
        _run_script(store, "feedlift_load_cycle", {})
        self.assertEqual(store.magazine_count("feed"), 4, "流程记账本身应照常扣减")
        self.assertEqual(inbox, [], "流程记账不该触发板仓观察者")

    def test_observer_failure_never_breaks_the_write(self):
        """观察者抛错只记 warning: 人工盘点不能因为沙盒的模型出问题而写失败."""
        store = _store()
        store.set_magazine_observer(
            lambda counts, detail: (_ for _ in ()).throw(RuntimeError("boom")))
        store.set_magazine("feed", 7)
        self.assertEqual(store.magazine_count("feed"), 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
