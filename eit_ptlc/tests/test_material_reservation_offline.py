"""离线: 物料并行预留语义 (material_reservations 表 + plan_staging(reserve_for)).

背景:
    多样品并行后, plan 与 consume 之间出现并发者, 单运行时代"刻意不做预留"的三个前提
    全部失效: (a) check_availability 对多个样品重复放行同一件余量; (b) B 的孔在 consume
    落账前仍 FRESH, C 会计划到同一孔; (c) C 的换板会把还载着 B 在保留件的中转板送回货架。

覆盖:
    1. 计数级预留扣减可用 (reserve_count 超发拒绝, 幂等恒一行)
    2. 孔级预留排他 (他人 plan 不到我的在保留孔; 自己可复用)
    3. 换板不吞在保留孔 (BLOCKED 而非 SWAP)
    4. 全部余量被他人预留 -> BLOCKED (区分 EXHAUSTED)
    5. consume 落账清预留; release_reservations 释放
    6. 空 reserve_for 与旧行为逐字段一致 (无预留时)

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_material_reservation_offline.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.runtime.material_store import (  # noqa: E402
    OP_BLOCKED,
    OP_EXHAUSTED,
    OP_NONE,
    OP_PUT_NEW,
    OP_SWAP,
    MaterialStore,
    load_bindings,
    load_topology,
)

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
_BINDINGS_FILE = _CONFIG_DIR / "material_bindings.yaml"
_TOPOLOGY_FILE = _CONFIG_DIR / "material_topology.yaml"


def _store() -> MaterialStore:
    topology = load_topology(_TOPOLOGY_FILE)
    bindings = load_bindings(_BINDINGS_FILE, topology)
    return MaterialStore(":memory:", topology=topology, bindings=bindings)


def _mark_fresh(store: MaterialStore, kind: str, plate: int, holes: list[int]) -> None:
    for hole in holes:
        store.mark(kind, plate, hole, "FRESH")


class ReservationCountTest(unittest.TestCase):
    """计数级预留 (批次准入门)."""

    def test_reserve_count_caps_at_fresh_total(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1, 2])   # 仅 2 件可用
        self.assertTrue(store.reserve_count("S-01", "collector"))
        self.assertTrue(store.reserve_count("S-02", "collector"))
        self.assertFalse(store.reserve_count("S-03", "collector"), "第 3 件应超发拒绝")

    def test_reserve_count_idempotent(self) -> None:
        store = _store()
        _mark_fresh(store, "bottle", 1, [1])
        self.assertTrue(store.reserve_count("S-01", "bottle"))
        self.assertTrue(store.reserve_count("S-01", "bottle"), "同样品重复预留应幂等成功")
        summary = store.reserved_summary()
        self.assertEqual(summary["bottle"]["count_level"], ["S-01"], "恒一行")

    def test_release_reservations(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1])
        self.assertTrue(store.reserve_count("S-01", "collector"))
        self.assertFalse(store.reserve_count("S-02", "collector"))
        self.assertEqual(store.release_reservations("S-01"), 1)
        self.assertTrue(store.reserve_count("S-02", "collector"), "释放后名额应回来")


class ReservationHoleTest(unittest.TestCase):
    """孔级预留 (plan_staging(reserve_for) 升级) 与排他."""

    def test_plan_reserves_hole_and_excludes_others(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1, 2])
        store.set_staging("staging-a", 1)              # 板 1 已在中转A
        p1 = store.plan_staging("collector", reserve_for="S-01")
        self.assertEqual((p1["op"], p1["hole"]), (OP_NONE, 1))
        # 他人再计划: 孔 1 已被 S-01 预留, 应给孔 2
        p2 = store.plan_staging("collector", reserve_for="S-02")
        self.assertEqual((p2["op"], p2["hole"]), (OP_NONE, 2))
        # S-01 自己重算: 自己的预留可复用, 仍是孔 1
        p1b = store.plan_staging("collector", reserve_for="S-01")
        self.assertEqual(p1b["hole"], 1)

    def test_anonymous_plan_cannot_take_reserved_hole(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1])
        store.set_staging("staging-a", 1)
        store.plan_staging("collector", reserve_for="S-01")
        anon = store.plan_staging("collector")
        self.assertEqual(anon["op"], OP_BLOCKED, "匿名调用不得抢在保留孔, 且应报 BLOCKED 而非缺料")

    def test_swap_blocked_when_others_hole_on_staged_plate(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1])
        _mark_fresh(store, "collector", 2, [1])
        store.set_staging("staging-a", 1)
        store.plan_staging("collector", reserve_for="S-01")   # S-01 预留板1孔1
        # S-02: 中转板 1 对它无可用孔, 但板上压着 S-01 的在保留件 -> 不许 SWAP
        p2 = store.plan_staging("collector", reserve_for="S-02")
        self.assertEqual(p2["op"], OP_BLOCKED, "换板会吞掉 S-01 的在保留孔, 必须 BLOCKED")

    def test_blocked_vs_exhausted(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 2, [1])
        store.plan_staging("collector", reserve_for="S-01")   # 唯一一件被 S-01 预留 (板2孔1)
        p2 = store.plan_staging("collector", reserve_for="S-02")
        self.assertEqual(p2["op"], OP_BLOCKED, "有料但全被他人预留 = BLOCKED")
        store.release_reservations("S-01")
        store.mark("collector", 2, 1, "USED")
        p3 = store.plan_staging("collector", reserve_for="S-02")
        self.assertEqual(p3["op"], OP_EXHAUSTED, "真没料 = EXHAUSTED")

    def test_consume_clears_reservation(self) -> None:
        store = _store()
        _mark_fresh(store, "collector", 1, [1, 2])
        store.set_staging("staging-a", 1)
        store.plan_staging("collector", reserve_for="S-01")   # 预留板1孔1
        # 经绑定表事件驱动消耗孔 1 (transfer_collector_staging_a_to_scrape 绑 consume)
        store.on_event({"type": "vm_node_enter", "run_id": "r1", "script": "demo", "aid": "b1",
                        "op": "run_script", "action": "transfer_collector_staging_a_to_scrape",
                        "args": {"slot_id": 1}, "ts": 1.0})
        store.on_event({"type": "vm_node_done", "run_id": "r1", "script": "demo", "aid": "b1",
                        "op": "run_script", "action": "transfer_collector_staging_a_to_scrape",
                        "status": "DONE", "ts": 2.0})
        summary = store.reserved_summary()
        self.assertEqual(summary.get("collector", {}).get("holes", []), [],
                         "consume 落账后孔级预留应被清掉")

    def test_empty_reserve_for_keeps_legacy_behavior(self) -> None:
        """无任何预留时, 带不带 reserve_for 的匿名判定与旧实现逐字段一致."""
        store = _store()
        # 场景 1: 中转有板且有余量 -> NONE
        _mark_fresh(store, "collector", 1, [3])
        store.set_staging("staging-a", 1)
        self.assertEqual(store.plan_staging("collector"),
                         {"op": OP_NONE, "rack_slot": 0, "old_rack_slot": 0,
                          "hole": 3, "staged_plate": 1})
        # 场景 2: 中转板耗尽, 货架有料 -> SWAP
        store.mark("collector", 1, 3, "USED")
        _mark_fresh(store, "collector", 4, [2])
        self.assertEqual(store.plan_staging("collector"),
                         {"op": OP_SWAP, "rack_slot": 4, "old_rack_slot": 1,
                          "hole": 2, "staged_plate": 1})
        # 场景 3: 中转空 -> PUT_NEW
        store.set_staging("staging-a", None)
        self.assertEqual(store.plan_staging("collector"),
                         {"op": OP_PUT_NEW, "rack_slot": 4, "old_rack_slot": 0,
                          "hole": 2, "staged_plate": 0})
        # 场景 4: 全空 -> EXHAUSTED
        store.mark("collector", 4, 2, "USED")
        self.assertEqual(store.plan_staging("collector")["op"], OP_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()
