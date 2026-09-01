"""单元测试: core.consumable_manager（v3，数字板号 1-6 / 双轨账本）

板号约定：
  显示编号 plate_id（int，1-6）：UI/PLC 共用；粉末与玻璃各自独立 1-6
  内部索引 internal_num（1-12）：粉末 1-6，玻璃 7-12（PLC 偏移 +6）

覆盖范围：
  账本接口：
    - mark_plate_loaded（默认满 6 孔 / 自定义子集）
    - mark_plate_emptied
    - mark_slot_loaded / mark_slot_used
  DI 同步：
    - sync_plate_presence 长度校验
    - sync_plate_presence 不写孔账本（双轨独立）
    - detect_inconsistencies
  决策接口：
    - prepare_for_scrape：暂存空 + 板在位 + 账本可用 → 取板
    - prepare_for_scrape：暂存有余量 → 复用
    - prepare_for_scrape：账本全空 → ConsumableExhaustedError
    - prepare_for_scrape：账本可用但 DI 离位 → ConsumablePlateMissingError
    - prepare_for_collect：FILLED 阻塞
  生命周期：
    - StagedPlate take → fill（玻璃瓶）
    - StagedPlate fill 粉末 → InvalidSlotTransitionError
    - on_collect_done TAKEN → FILLED
    - on_scrape_done 清理决策
    - 并发 prepare：asyncio.Lock 保证不重复
  辅助：
    - slot_id_to_index / index_to_slot_id / plate_to_indices 边界
    - manual_reset_staging / manual_clear_filled_bottles
    - snapshot 结构
  持久化：
    - JSON 写盘 → 重建实例 → 账本完整恢复
    - JSON 损坏 → 退化为空账本，不抛异常

运行:
    cd UI-Upper
    python -m unittest tests.test_consumable_manager -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

# 让 'core' 包可被导入（本文件位于 UI-Upper/tests/）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.consumable_manager import (  # noqa: E402
    OP_NONE,
    OP_PUT_NEW,
    OP_SWAP,
    PLATE_SENSOR_COUNT,
    SLOTS_PER_PLATE,
    TOTAL_PLATES,
    TOTAL_RACK_SLOTS,
    ConsumableExhaustedError,
    ConsumableManager,
    ConsumablePlateMissingError,
    ConsumableSnapshot,
    ConsumableType,
    InvalidSlotTransitionError,
    PrepareDecision,
    SlotStatus,
    StagedPlate,
    StagedPlateBlockedError,
    StagingId,
    _display_to_internal,
    _internal_to_display,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _di_all_true() -> list[bool]:
    return [True] * PLATE_SENSOR_COUNT


def _di_all_false() -> list[bool]:
    return [False] * PLATE_SENSOR_COUNT


def _di_powder_only() -> list[bool]:
    """粉末板 1-6 在位，玻璃瓶板 7-12 离位。"""
    return [True] * 6 + [False] * 6


def _di_bottle_only() -> list[bool]:
    """粉末板 1-6 离位，玻璃瓶板 7-12 在位。"""
    return [False] * 6 + [True] * 6


# ---------------------------------------------------------------------------
# 测试类
# ---------------------------------------------------------------------------


class TestLedgerInputAPI(unittest.IsolatedAsyncioTestCase):
    """账本录入接口测试。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_mark_plate_loaded_default_full(self) -> None:
        """mark_plate_loaded(N) 默认 6 孔全装入。"""
        await self.cm.mark_plate_loaded(1)
        for i in range(6):
            self.assertTrue(self.cm._rack[i].has_consumable)
        # 其它板不受影响
        for i in range(6, TOTAL_RACK_SLOTS):
            self.assertFalse(self.cm._rack[i].has_consumable)

    async def test_mark_plate_loaded_custom_slots(self) -> None:
        """mark_plate_loaded(N, slots=[1,3,5]) 仅指定孔位为可用。"""
        await self.cm.mark_plate_loaded(2, slots=[1, 3, 5])
        # 板 2（索引 6-11）：1/3/5 可用，2/4/6 不可用
        self.assertTrue(self.cm._rack[6].has_consumable)   # slot 1
        self.assertFalse(self.cm._rack[7].has_consumable)  # slot 2
        self.assertTrue(self.cm._rack[8].has_consumable)   # slot 3
        self.assertFalse(self.cm._rack[9].has_consumable)  # slot 4
        self.assertTrue(self.cm._rack[10].has_consumable)  # slot 5
        self.assertFalse(self.cm._rack[11].has_consumable) # slot 6

    async def test_mark_plate_emptied(self) -> None:
        """mark_plate_emptied 整板清空。"""
        await self.cm.mark_plate_loaded(3)
        await self.cm.mark_plate_emptied(3)
        # 板 3（索引 12-17）全 False
        for i in range(12, 18):
            self.assertFalse(self.cm._rack[i].has_consumable)

    async def test_mark_slot_loaded_used(self) -> None:
        """mark_slot_loaded / mark_slot_used 单孔点改。"""
        await self.cm.mark_slot_loaded(1, 4)
        self.assertTrue(self.cm._rack[3].has_consumable)
        await self.cm.mark_slot_used(1, 4)
        self.assertFalse(self.cm._rack[3].has_consumable)

    async def test_mark_plate_loaded_invalid_plate(self) -> None:
        """plate_num 越界 → ValueError。"""
        with self.assertRaises(ValueError):
            await self.cm.mark_plate_loaded(0)
        with self.assertRaises(ValueError):
            await self.cm.mark_plate_loaded(13)

    async def test_mark_plate_loaded_invalid_slot(self) -> None:
        """slots 列表中元素越界 → ValueError。"""
        with self.assertRaises(ValueError):
            await self.cm.mark_plate_loaded(1, slots=[1, 7])


class TestPlatePresence(unittest.IsolatedAsyncioTestCase):
    """板级 DI 同步与一致性检测。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_sync_plate_presence_length_check(self) -> None:
        """sync_plate_presence 长度必须为 12。"""
        with self.assertRaises(ValueError):
            await self.cm.sync_plate_presence([True] * 11)
        with self.assertRaises(ValueError):
            await self.cm.sync_plate_presence([True] * 72)

    async def test_sync_plate_presence_does_not_write_ledger(self) -> None:
        """DI 同步只写 _plate_present，完全不动 _rack 账本（双轨独立）。"""
        await self.cm.mark_plate_loaded(1)
        # 模拟板被拔走 → DI 全 False
        await self.cm.sync_plate_presence(_di_all_false())
        # 账本仍然 6 孔可用，DI 显示离位
        for i in range(6):
            self.assertTrue(self.cm._rack[i].has_consumable)
        for present in self.cm._plate_present:
            self.assertFalse(present)

    async def test_detect_inconsistencies(self) -> None:
        """账本可用 + DI 离位 → 出现在 detect_inconsistencies 列表。"""
        await self.cm.mark_plate_loaded(1)   # 粉末板 display=1 (internal=1)
        await self.cm.mark_plate_loaded(7)   # 玻璃板 display=1 (internal=7)
        await self.cm.sync_plate_presence(_di_powder_only())  # 玻璃板不在位
        missing = self.cm.detect_inconsistencies()
        # detect_inconsistencies 返回 (display_num, ctype) 元组
        self.assertIn((1, ConsumableType.GLASS_BOTTLE), missing)
        self.assertNotIn((1, ConsumableType.POWDER_COLLECTOR), missing)


class TestPrepareDecision(unittest.IsolatedAsyncioTestCase):
    """prepare_for_scrape / prepare_for_collect 决策路径。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_prepare_scrape_fetches_new_plate(self) -> None:
        """暂存空 + 板 1 在位 + 账本可用 → op=PUT_NEW 搬板 1, slot=1。"""
        await self.cm.mark_plate_loaded(1)
        await self.cm.sync_plate_presence(_di_all_true())

        d = await self.cm.prepare_for_scrape("S001")
        self.assertIsInstance(d, PrepareDecision)
        self.assertEqual(d.op, OP_PUT_NEW)
        self.assertEqual(d.fetch_rack_plate, 1)
        self.assertEqual(d.old_plate_slot, 0)
        self.assertEqual(d.consume_slot, 1)
        staging_a = self.cm._staging[StagingId.A]
        self.assertIsNotNone(staging_a)
        assert staging_a is not None
        self.assertEqual(staging_a.plate_id, 1)
        self.assertEqual(staging_a.slots[0], SlotStatus.TAKEN)

    async def test_prepare_scrape_reuses_staging(self) -> None:
        """暂存有余量 → op=NONE 复用，fetch=0/old=0。"""
        self.cm._staging[StagingId.A] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
            slots=[
                SlotStatus.TAKEN, SlotStatus.TAKEN, SlotStatus.TAKEN,
                SlotStatus.AVAILABLE, SlotStatus.AVAILABLE, SlotStatus.AVAILABLE,
            ],
        )
        d = await self.cm.prepare_for_scrape("S002")
        self.assertEqual(d.op, OP_NONE)
        self.assertEqual(d.fetch_rack_plate, 0)
        self.assertEqual(d.old_plate_slot, 0)
        self.assertEqual(d.consume_slot, 4)

    async def test_prepare_scrape_swap_when_exhausted(self) -> None:
        """暂存耗尽（粉末板 1 全 TAKEN）+ 粉末板 2 可用 → op=SWAP, fetch=2, old=1。"""
        # 暂存 A 装着粉末板 1（6 孔全 TAKEN 但无 FILLED）→ is_exhausted=True
        self.cm._staging[StagingId.A] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
            slots=[SlotStatus.TAKEN] * SLOTS_PER_PLATE,
        )
        # 架上仅粉末板 2（internal=2）有账本 + DI 在位
        await self.cm.mark_plate_loaded(2)
        await self.cm.sync_plate_presence(_di_all_true())

        d = await self.cm.prepare_for_scrape("S_swap")
        self.assertEqual(d.op, OP_SWAP)
        self.assertEqual(d.fetch_rack_plate, 2)
        self.assertEqual(d.old_plate_slot, 1)   # 旧板 display=1
        self.assertEqual(d.consume_slot, 1)
        # 暂存已被新板 display=2 覆盖
        staging_a = self.cm._staging[StagingId.A]
        assert staging_a is not None
        self.assertEqual(staging_a.plate_id, 2)
        self.assertEqual(staging_a.slots[0], SlotStatus.TAKEN)

    async def test_prepare_scrape_exhausted(self) -> None:
        """账本全空（无可用粉末板）→ ConsumableExhaustedError。"""
        # 仅装入玻璃瓶板，粉末板账本全空
        await self.cm.mark_plate_loaded(7)
        await self.cm.sync_plate_presence(_di_all_true())
        with self.assertRaises(ConsumableExhaustedError):
            await self.cm.prepare_for_scrape("S003")

    async def test_prepare_scrape_plate_missing(self) -> None:
        """账本可用但所有候选板 DI 都离位 → ConsumablePlateMissingError。"""
        await self.cm.mark_plate_loaded(1)
        await self.cm.mark_plate_loaded(2)
        # 粉末板全部 DI 离位
        await self.cm.sync_plate_presence(_di_bottle_only())
        with self.assertRaises(ConsumablePlateMissingError):
            await self.cm.prepare_for_scrape("S004")

    async def test_prepare_scrape_skips_offline_plate(self) -> None:
        """板 1 离位 + 板 2 在位且账本可用 → 选板 2（op=PUT_NEW）。"""
        await self.cm.mark_plate_loaded(1)
        await self.cm.mark_plate_loaded(2)
        di = _di_all_false()
        di[1] = True  # 板 2 在位
        await self.cm.sync_plate_presence(di)
        d = await self.cm.prepare_for_scrape("S005")
        self.assertEqual(d.op, OP_PUT_NEW)
        self.assertEqual(d.fetch_rack_plate, 2)
        self.assertEqual(d.old_plate_slot, 0)
        self.assertEqual(d.consume_slot, 1)

    async def test_prepare_collect_filled_swap(self) -> None:
        """暂存 B 板满（全 FILLED）→ 自动 SWAP，机器人归还满板 + 取新板。"""
        # 暂存 B 装玻璃板 display=1（internal=7）全 FILLED（is_exhausted=True）
        self.cm._staging[StagingId.B] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.GLASS_BOTTLE,
            slots=[SlotStatus.FILLED] * SLOTS_PER_PLATE,
        )
        # 架上玻璃板 display=2（internal=8）有账本 + DI 在位
        await self.cm.mark_plate_loaded(8)
        await self.cm.sync_plate_presence(_di_all_true())

        d = await self.cm.prepare_for_collect("S006")
        self.assertEqual(d.op, OP_SWAP)
        self.assertEqual(d.fetch_rack_plate, 2)   # 新板 display=2
        self.assertEqual(d.old_plate_slot, 1)     # 旧板 display=1
        self.assertEqual(d.consume_slot, 1)
        # 暂存已被新板覆盖
        staging_b = self.cm._staging[StagingId.B]
        assert staging_b is not None
        self.assertEqual(staging_b.plate_id, 2)
        self.assertEqual(staging_b.slots[0], SlotStatus.TAKEN)

    async def test_prepare_collect_partial_filled_reuses(self) -> None:
        """暂存 B 含部分 FILLED 但仍有余量 → 复用 AVAILABLE 孔。"""
        self.cm._staging[StagingId.B] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.GLASS_BOTTLE,
            slots=[
                SlotStatus.TAKEN, SlotStatus.FILLED, SlotStatus.TAKEN,
                SlotStatus.TAKEN, SlotStatus.TAKEN, SlotStatus.AVAILABLE,
            ],
        )
        d = await self.cm.prepare_for_collect("S006b")
        self.assertEqual(d.op, OP_NONE)
        self.assertEqual(d.fetch_rack_plate, 0)
        self.assertEqual(d.old_plate_slot, 0)
        self.assertEqual(d.consume_slot, 6)  # 唯一的 AVAILABLE 孔

    async def test_concurrent_prepare_no_duplicate(self) -> None:
        """并发 prepare：asyncio.Lock 保证孔位不重复分配。"""
        self.cm._staging[StagingId.A] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
            slots=[
                SlotStatus.TAKEN, SlotStatus.TAKEN, SlotStatus.TAKEN,
                SlotStatus.AVAILABLE, SlotStatus.AVAILABLE, SlotStatus.AVAILABLE,
            ],
        )
        results = await asyncio.gather(
            self.cm.prepare_for_scrape("S_c1"),
            self.cm.prepare_for_scrape("S_c2"),
        )
        slots = [r.consume_slot for r in results]
        self.assertEqual(len(slots), len(set(slots)))


class TestStagedPlateLifecycle(unittest.IsolatedAsyncioTestCase):
    """StagedPlate / on_*_done 生命周期。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_take_then_fill_glass(self) -> None:
        plate = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.GLASS_BOTTLE,
        )
        plate.take(1)
        plate.fill(1)
        self.assertEqual(plate.slots[0], SlotStatus.FILLED)

    async def test_fill_powder_raises(self) -> None:
        plate = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
        )
        plate.take(1)
        with self.assertRaises(InvalidSlotTransitionError):
            plate.fill(1)

    async def test_on_collect_done_taken_to_filled(self) -> None:
        """完整玻璃瓶生命周期：装板 → prepare → on_collect_done。"""
        await self.cm.mark_plate_loaded(7)   # 玻璃板 internal=7 → display=1
        await self.cm.sync_plate_presence(_di_all_true())
        d = await self.cm.prepare_for_collect("S012")
        self.assertEqual(d.op, OP_PUT_NEW)
        self.assertEqual(d.fetch_rack_plate, 1)   # display 编号
        self.assertEqual(d.consume_slot, 1)

        await self.cm.on_collect_done("S012")
        staging_b = self.cm._staging[StagingId.B]
        assert staging_b is not None
        self.assertEqual(staging_b.slots[0], SlotStatus.FILLED)

    async def test_on_scrape_done_clears_decision(self) -> None:
        await self.cm.mark_plate_loaded(1)
        await self.cm.sync_plate_presence(_di_all_true())
        await self.cm.prepare_for_scrape("S_done")
        self.assertIn("S_done", self.cm._decisions)
        await self.cm.on_scrape_done("S_done")
        self.assertNotIn("S_done", self.cm._decisions)
        # 重复调用不报错
        await self.cm.on_scrape_done("S_done")


class TestIndexHelpers(unittest.IsolatedAsyncioTestCase):
    """slot_id_to_index / index_to_slot_id / plate_to_indices 边界（v3 数字板号）。"""

    async def test_slot_id_to_index_new_format(self) -> None:
        """新格式 'P-S'（internal-position）。"""
        self.assertEqual(ConsumableManager.slot_id_to_index("1-1"), 1)
        self.assertEqual(ConsumableManager.slot_id_to_index("1-6"), 6)
        self.assertEqual(ConsumableManager.slot_id_to_index("2-1"), 7)
        self.assertEqual(ConsumableManager.slot_id_to_index("12-6"), 72)

    async def test_slot_id_to_index_legacy_format(self) -> None:
        """旧格式 'A3' 仍可解析（向后兼容旧 JSON 加载）。"""
        self.assertEqual(ConsumableManager.slot_id_to_index("A1"), 1)
        self.assertEqual(ConsumableManager.slot_id_to_index("A6"), 6)
        self.assertEqual(ConsumableManager.slot_id_to_index("B1"), 7)
        self.assertEqual(ConsumableManager.slot_id_to_index("L6"), 72)

    async def test_index_to_slot_id(self) -> None:
        """写出始终采用新格式。"""
        self.assertEqual(ConsumableManager.index_to_slot_id(1), "1-1")
        self.assertEqual(ConsumableManager.index_to_slot_id(7), "2-1")
        self.assertEqual(ConsumableManager.index_to_slot_id(72), "12-6")

    async def test_plate_to_indices(self) -> None:
        self.assertEqual(
            ConsumableManager.plate_to_indices(2),  # 粉末板 internal=2
            [7, 8, 9, 10, 11, 12],
        )
        self.assertEqual(
            ConsumableManager.plate_to_indices(12),  # 玻璃板 internal=12
            list(range(67, 73)),
        )

    async def test_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            ConsumableManager.slot_id_to_index("M1")
        with self.assertRaises(ValueError):
            ConsumableManager.slot_id_to_index("99-99")
        with self.assertRaises(ValueError):
            ConsumableManager.index_to_slot_id(0)
        with self.assertRaises(ValueError):
            ConsumableManager.index_to_slot_id(73)
        with self.assertRaises(ValueError):
            ConsumableManager.plate_to_indices(0)
        with self.assertRaises(ValueError):
            ConsumableManager.plate_to_indices(13)

    async def test_display_internal_roundtrip(self) -> None:
        """_display_to_internal / _internal_to_display 互逆。"""
        # 粉末：display 1-6 ↔ internal 1-6
        for n in range(1, 7):
            internal = _display_to_internal(n, ConsumableType.POWDER_COLLECTOR)
            self.assertEqual(internal, n)
            self.assertEqual(_internal_to_display(internal, ConsumableType.POWDER_COLLECTOR), n)
        # 玻璃：display 1-6 ↔ internal 7-12
        for n in range(1, 7):
            internal = _display_to_internal(n, ConsumableType.GLASS_BOTTLE)
            self.assertEqual(internal, n + 6)
            self.assertEqual(_internal_to_display(internal, ConsumableType.GLASS_BOTTLE), n)


class TestManualOps(unittest.IsolatedAsyncioTestCase):
    """manual_* 修正接口。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_manual_reset_staging(self) -> None:
        self.cm._staging[StagingId.A] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
            slots=[SlotStatus.TAKEN] * SLOTS_PER_PLATE,
        )
        await self.cm.manual_reset_staging(StagingId.A, 2)
        staging_a = self.cm._staging[StagingId.A]
        assert staging_a is not None
        self.assertEqual(staging_a.plate_id, 2)
        self.assertEqual(staging_a.remaining_available, 6)
        # 板号越界（>6） → ValueError
        with self.assertRaises(ValueError):
            await self.cm.manual_reset_staging(StagingId.A, 7)
        with self.assertRaises(ValueError):
            await self.cm.manual_reset_staging(StagingId.A, 0)

    async def test_manual_clear_filled_bottles(self) -> None:
        self.cm._staging[StagingId.B] = StagedPlate(
            plate_id=2,
            consumable_type=ConsumableType.GLASS_BOTTLE,
            slots=[
                SlotStatus.TAKEN, SlotStatus.FILLED, SlotStatus.TAKEN,
                SlotStatus.TAKEN, SlotStatus.FILLED, SlotStatus.TAKEN,
            ],
        )
        await self.cm.manual_clear_filled_bottles(StagingId.B)
        self.assertIsNone(self.cm._staging[StagingId.B])


class TestSnapshot(unittest.IsolatedAsyncioTestCase):
    """ConsumableSnapshot 结构。"""

    async def test_snapshot_structure(self) -> None:
        cm = ConsumableManager()
        await cm.mark_plate_loaded(1)
        await cm.sync_plate_presence(_di_all_true())
        snap = cm.snapshot()
        self.assertIsInstance(snap, ConsumableSnapshot)
        self.assertEqual(len(snap.rack), TOTAL_RACK_SLOTS)
        self.assertEqual(len(snap.plate_present), PLATE_SENSOR_COUNT)
        self.assertEqual(snap.powder_available, 6)
        self.assertEqual(snap.bottle_available, 0)


# ---------------------------------------------------------------------------
# 持久化往返
# ---------------------------------------------------------------------------


class TestPersistence(unittest.IsolatedAsyncioTestCase):
    """JSON write-through 持久化往返。"""

    async def test_persistence_roundtrip(self) -> None:
        """mark_plate_loaded → 销毁实例 → 用同 path 重建 → 账本完整恢复。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consumable_state.json"

            cm1 = ConsumableManager(persistence_path=path)
            await cm1.mark_plate_loaded(1)
            await cm1.mark_plate_loaded(7, slots=[1, 2, 3])
            del cm1

            cm2 = ConsumableManager(persistence_path=path)
            # 板 1 应 6 孔可用
            for i in range(6):
                self.assertTrue(cm2._rack[i].has_consumable)
            # 板 7（索引 36-41）应只有 1/2/3 可用
            self.assertTrue(cm2._rack[36].has_consumable)
            self.assertTrue(cm2._rack[37].has_consumable)
            self.assertTrue(cm2._rack[38].has_consumable)
            self.assertFalse(cm2._rack[39].has_consumable)
            self.assertFalse(cm2._rack[40].has_consumable)
            self.assertFalse(cm2._rack[41].has_consumable)

    async def test_persistence_corrupt_file(self) -> None:
        """损坏的 JSON → 退化为空账本，不抛异常。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consumable_state.json"
            path.write_text("{ this is not valid json", encoding="utf-8")
            cm = ConsumableManager(persistence_path=path)
            # 退化为默认空账本
            for slot in cm._rack:
                self.assertFalse(slot.has_consumable)

    async def test_persistence_staging_roundtrip(self) -> None:
        """暂存板状态也持久化。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consumable_state.json"
            cm1 = ConsumableManager(persistence_path=path)
            await cm1.mark_plate_loaded(1)
            await cm1.sync_plate_presence(_di_all_true())
            await cm1.prepare_for_scrape("S_persist")  # 创建暂存 A
            del cm1

            cm2 = ConsumableManager(persistence_path=path)
            staging_a = cm2._staging[StagingId.A]
            assert staging_a is not None
            self.assertEqual(staging_a.plate_id, 1)
            self.assertEqual(staging_a.slots[0], SlotStatus.TAKEN)

    async def test_persistence_no_path_no_disk_io(self) -> None:
        """persistence_path=None → 不写盘（mock/测试场景）。"""
        cm = ConsumableManager(persistence_path=None)
        await cm.mark_plate_loaded(1)
        # 内存里有，磁盘没有任何文件需要清理（无副作用）
        self.assertTrue(cm._rack[0].has_consumable)


class TestPowderReturnSlot(unittest.IsolatedAsyncioTestCase):
    """get_powder_return_slot 跨工位绑定查询测试（Phase 4 v2.5）。"""

    async def test_returns_slot_after_scrape_decision(self) -> None:
        """prepare_for_scrape 后读到 consume_slot。"""
        cm = ConsumableManager(persistence_path=None)
        await cm.mark_plate_loaded(1)
        await cm.sync_plate_presence(_di_all_true())
        d = await cm.prepare_for_scrape("S001")
        self.assertEqual(d.consume_slot, 1)

        slot = await cm.get_powder_return_slot("S001")
        self.assertEqual(slot, 1)

    async def test_returns_zero_when_no_decision(self) -> None:
        """未调过 prepare_for_scrape → 返回 0。"""
        cm = ConsumableManager(persistence_path=None)
        slot = await cm.get_powder_return_slot("S404")
        self.assertEqual(slot, 0)

    async def test_returns_zero_after_collect_decision_overwrites(self) -> None:
        """prepare_for_collect 覆盖 _decisions 为 StagingId.B → 返回 0（语义错位）。

        这也是 CollectStage 为什么必须 **先** get_powder_return_slot **再** prepare_for_collect 的原因。
        """
        cm = ConsumableManager(persistence_path=None)
        await cm.mark_plate_loaded(1)   # 粉末板 A
        await cm.mark_plate_loaded(7)   # 玻璃瓶板 G
        await cm.sync_plate_presence(_di_all_true())
        await cm.prepare_for_scrape("S001")
        await cm.prepare_for_collect("S001")  # _decisions 被覆盖为 (StagingId.B)

        slot = await cm.get_powder_return_slot("S001")
        self.assertEqual(slot, 0)  # staging 非 A 报错返回 0


class TestCheckAvailability(unittest.IsolatedAsyncioTestCase):
    """check_availability 入队前预检测试。"""

    def setUp(self) -> None:
        self.cm = ConsumableManager()

    async def test_all_available(self) -> None:
        """粉末+玻璃瓶均可用 → 无警告。"""
        await self.cm.mark_plate_loaded(1)   # 粉末板 A
        await self.cm.mark_plate_loaded(7)   # 玻璃瓶板 G
        await self.cm.sync_plate_presence(_di_all_true())
        warnings = self.cm.check_availability(need_powder=True, need_bottle=True)
        self.assertEqual(warnings, [])

    async def test_powder_exhausted(self) -> None:
        """粉末板账本全空 → 警告。"""
        # 仅装入玻璃瓶板，粉末板账本全空
        await self.cm.mark_plate_loaded(7)
        await self.cm.sync_plate_presence(_di_all_true())
        warnings = self.cm.check_availability(need_powder=True, need_bottle=False)
        self.assertEqual(len(warnings), 1)
        self.assertIn("粉末收集器耗尽", warnings[0])

    async def test_bottle_di_missing(self) -> None:
        """玻璃瓶账本可用但 DI 离位 → 警告。"""
        await self.cm.mark_plate_loaded(7)   # 玻璃瓶板 G 账本可用
        await self.cm.sync_plate_presence(_di_powder_only())  # 玻璃瓶板 DI 离位
        warnings = self.cm.check_availability(need_powder=False, need_bottle=True)
        self.assertEqual(len(warnings), 1)
        self.assertIn("DI 不在位", warnings[0])

    async def test_staging_has_remaining(self) -> None:
        """暂存有余量 → 无警告（即使架上无板）。"""
        self.cm._staging[StagingId.A] = StagedPlate(
            plate_id=1,
            consumable_type=ConsumableType.POWDER_COLLECTOR,
            slots=[
                SlotStatus.TAKEN, SlotStatus.TAKEN, SlotStatus.TAKEN,
                SlotStatus.AVAILABLE, SlotStatus.AVAILABLE, SlotStatus.AVAILABLE,
            ],
        )
        # 架上无粉末板，但暂存 A 有余量
        warnings = self.cm.check_availability(need_powder=True, need_bottle=False)
        self.assertEqual(warnings, [])

    async def test_no_need_no_warning(self) -> None:
        """不需要任何耗材 → 无警告。"""
        warnings = self.cm.check_availability(need_powder=False, need_bottle=False)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
