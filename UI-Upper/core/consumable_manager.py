"""ConsumableManager - 耗材管理核心模块
======================================

职责划分（v2，板级 DI + 孔级账本双轨）：
- 12 个板级 DI（`sync_plate_presence`）仅作为“板是否在位”防呆，是硬件真值源。
- 72 孔耗材账本由实验员通过 UI 录入（mark_plate_loaded / mark_plate_emptied /
  mark_slot_loaded / mark_slot_used），由上位机 JSON 落盘 write-through 持久化，
  是余量账本的 PC 真值源。
- prepare_for_scrape / prepare_for_collect 决策输出 `PrepareDecision`
  （op + fetch_rack_plate + old_plate_slot + consume_slot，协议 v2.5 动作码）；
  取板需同时满足 “账本有可用孔” 与 “DI 该板在位”，二者任一缺失都会报错。
- on_scrape_done / on_collect_done 完成回调。
- manual_*（重置暂存、单孔点改、手动设架位）供手动修正。

设计原则：
- PC 决策，PLC 执行（与 Expand_Target_Tank 同构）。
- v2.5 账本是唯一裁决方：PC 显式下发动作码（NONE/PUT_NEW/SWAP），
  PLC 不推理暂存状态，机器人不“虚空抓一下”。暂存区无传感器依赖。
- take() 在 prepare_for_xxx 内原子完成，避免并发分配 Bug。
- 架上孔位保持二态（has_consumable: bool），三态语义仅在暂存板。
- DI 不写孔账本，账本不读 DI；实验员是孔状态唯一录入者。

不含：
- 溶剂管理（SolventChannel，正交问题，推迟到需要时添加）
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SLOTS_PER_PLATE = 6
TOTAL_PLATES = 12
TOTAL_RACK_SLOTS = SLOTS_PER_PLATE * TOTAL_PLATES   # 72：账本容量
PLATE_SENSOR_COUNT = TOTAL_PLATES                    # 12：DI 数组长度
TOTAL_SENSORS = TOTAL_RACK_SLOTS                     # 向后兼容别名（账本容量=72）

PERSISTENCE_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# 动作码（协议 v2.5）
# ---------------------------------------------------------------------------

# 暂存区无传感器 → PC 账本显式告知 PLC 动作语义。
# 与 plans/consumable_phase3_plc_interface_plan.md §3.1 中
# scrape_Plate_Op / collect_Plate_Op 取值一一对应；
# PLC 哑执行，不推理暂存状态。
OP_NONE = 0     # 暂存有余量复用，Fetch/Old 均为 0
OP_PUT_NEW = 1  # 暂存空，仅放新板（Fetch=1-12, Old=0）
OP_SWAP = 2     # 暂存耗尽，先取旧板回料架原孔再放新板（Fetch=1-12, Old=1-12）


# ---------------------------------------------------------------------------
# 编号约定
# ---------------------------------------------------------------------------
#
# 显示编号（plate_id, 用户与 PLC 共用）：
#   粉末收集器板 1-6 / 玻璃收集瓶板 1-6
#   PLC 对玻璃做 +6 偏移，PC 侧始终发 1-6。
#
# 内部索引（DI 数组 / 料架 72 孔定位）：
#   粉末 1-6 → index 0-5；玻璃 1-6 → index 6-11
#   _display_to_internal(n, ctype) 完成转换。

def _display_to_internal(display_num: int, ctype: "ConsumableType") -> int:
    """显示编号(1-6) → 内部索引(1-12)。玻璃 +6 偏移。"""
    if ctype == ConsumableType.GLASS_BOTTLE:
        return display_num + 6
    return display_num


def _internal_to_display(internal_num: int, ctype: "ConsumableType") -> int:
    """内部索引(1-12) → 显示编号(1-6)。"""
    if ctype == ConsumableType.GLASS_BOTTLE:
        return internal_num - 6
    return internal_num


def _op_name(op: int) -> str:
    """动作码 → 可读名称（仅供 log、不参与逻辑）。"""
    return {OP_NONE: "NONE", OP_PUT_NEW: "PUT_NEW", OP_SWAP: "SWAP"}.get(op, f"OP_{op}")

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class SlotStatus(IntEnum):
    """暂存板孔位三态枚举（仅暂存板使用，架上孔位用 bool）。"""
    AVAILABLE = 0   # 有可用空耗材（可被动作 B 取走）
    TAKEN = 1       # 耗材被取走，物理孔位空（粉末/玻璃瓶共用）
    FILLED = 2      # 装样玻璃瓶已放回（仅玻璃瓶类型）


class ConsumableType(str, Enum):
    """耗材类型。"""
    POWDER_COLLECTOR = "powder_collector"
    GLASS_BOTTLE = "glass_bottle"


class StagingId(str, Enum):
    """暂存工位 ID。"""
    A = "A"   # 暂存 A：粉末收集器
    B = "B"   # 暂存 B：玻璃收集瓶


# 板号 → 耗材类型映射（显示编号 1-6，粉末与玻璃瓶各自独立编号）
PLATES_BY_TYPE: dict[ConsumableType, set[int]] = {
    ConsumableType.POWDER_COLLECTOR: {1, 2, 3, 4, 5, 6},
    ConsumableType.GLASS_BOTTLE:     {1, 2, 3, 4, 5, 6},
}

# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class ConsumableError(Exception):
    """耗材管理异常基类。"""


class ConsumableExhaustedError(ConsumableError):
    """架上无可用耗材，无法继续。"""


class StagedPlateBlockedError(ConsumableError):
    """暂存板含 FILLED 装样瓶，必须人工先清理。"""


class InvalidSlotTransitionError(ConsumableError):
    """状态转移非法（如 FILLED→TAKEN）。"""


class ConsumablePlateMissingError(ConsumableError):
    """账本表示有可用板，但 DI 显示该板均不在位，物理防呆阻塞取板。"""


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class StagedPlate:
    """暂存板上的一块耗材板（PC 单方面维护，无传感器依赖）。

    plate_id 为显示编号 (1-6)，与下发给 PLC 的 Fetch_Rack_Plate 一致。
    """
    plate_id: int                                 # 1-6（显示编号）
    consumable_type: ConsumableType
    slots: list[SlotStatus] = field(
        default_factory=lambda: [SlotStatus.AVAILABLE] * SLOTS_PER_PLATE,
    )

    @property
    def remaining_available(self) -> int:
        """当前 AVAILABLE 孔位数。"""
        return sum(1 for s in self.slots if s == SlotStatus.AVAILABLE)

    @property
    def is_exhausted(self) -> bool:
        """是否无可用孔位（TAKEN + FILLED 都计为已耗尽）。"""
        return self.remaining_available == 0

    @property
    def has_filled_bottles(self) -> bool:
        """是否含 FILLED 装样瓶（该板不能被覆盖为新板）。"""
        return any(s == SlotStatus.FILLED for s in self.slots)

    def next_available_slot(self) -> Optional[int]:
        """返回 1-6 的孔位号（首个 AVAILABLE）；全部不可用时返回 None。"""
        for i, s in enumerate(self.slots):
            if s == SlotStatus.AVAILABLE:
                return i + 1
        return None

    def take(self, slot_number: int) -> None:
        """AVAILABLE → TAKEN（其他状态报错）。

        Args:
            slot_number: 1-6 孔位号

        Raises:
            InvalidSlotTransitionError: 孔位非 AVAILABLE
            ValueError: slot_number 越界
        """
        self._validate_slot(slot_number)
        idx = slot_number - 1
        if self.slots[idx] != SlotStatus.AVAILABLE:
            raise InvalidSlotTransitionError(
                f"Slot {slot_number} 状态为 {self.slots[idx].name}，仅 AVAILABLE 可 take"
            )
        self.slots[idx] = SlotStatus.TAKEN

    def fill(self, slot_number: int) -> None:
        """TAKEN → FILLED（仅玻璃瓶类型；粉末类型禁用）。

        Args:
            slot_number: 1-6 孔位号

        Raises:
            InvalidSlotTransitionError: 粉末类型 / 非 TAKEN 状态
            ValueError: slot_number 越界
        """
        self._validate_slot(slot_number)
        if self.consumable_type != ConsumableType.GLASS_BOTTLE:
            raise InvalidSlotTransitionError(
                f"粉末收集器不支持 fill 操作（plate={self.plate_id}）"
            )
        idx = slot_number - 1
        if self.slots[idx] != SlotStatus.TAKEN:
            raise InvalidSlotTransitionError(
                f"Slot {slot_number} 状态为 {self.slots[idx].name}，仅 TAKEN 可 fill"
            )
        self.slots[idx] = SlotStatus.FILLED

    def _validate_slot(self, slot_number: int) -> None:
        if not 1 <= slot_number <= SLOTS_PER_PLATE:
            raise ValueError(f"slot_number 必须在 1-{SLOTS_PER_PLATE}，收到 {slot_number}")


@dataclass
class RackSlot:
    """耗材架上单个孔位。

    二态（has_consumable: bool）仅反映上位机孔级账本（实验员录入 + 决策消耗），
    与板级 DI 传感器独立。DI 仅用于 prepare_for_* 决策时的“板在位”防呆。
    """
    slot_id: str              # "1-3"（内部索引-孔位）
    plate_id: str             # "1"-"6"（显示编号）
    position: int             # 1-6
    consumable_type: ConsumableType
    has_consumable: bool      # 账本状态（不是传感器）


@dataclass(frozen=True)
class PrepareDecision:
    """prepare_for_scrape / prepare_for_collect 返回值（协议 v2.5）。

    调用者需将 4 个字段全部写入 PLC：
        scrape_Plate_Op / scrape_Fetch_Rack_Plate /
        scrape_Old_Plate_Slot / scrape_Consume_Slot
    （collect 同构）。

    不变量：
    - op == OP_NONE      → fetch_rack_plate == 0 且 old_plate_slot == 0
    - op == OP_PUT_NEW   → fetch_rack_plate ∈ [1,12] 且 old_plate_slot == 0
    - op == OP_SWAP      → fetch_rack_plate ∈ [1,12] 且 old_plate_slot ∈ [1,12]
    - consume_slot 始终 ∈ [1,6]
    """
    op: int                # OP_NONE / OP_PUT_NEW / OP_SWAP
    fetch_rack_plate: int  # 0 或 1-12
    old_plate_slot: int    # 0 或 1-12（仅 op=OP_SWAP 时非 0）
    consume_slot: int      # 1-6


@dataclass(frozen=True)
class ConsumableSnapshot:
    """不可变快照，供 UI/Dashboard 渲染（无锁读，最终一致性）。"""
    staging: dict[str, Optional[StagedPlate]]   # StagingId.value → StagedPlate | None
    rack: tuple[RackSlot, ...]                   # 72 个 RackSlot（12 板 × 6 孔）
    plate_present: tuple[bool, ...]              # 12 个板级 DI 状态快照
    powder_available: int                        # 架上粉末收集器可用总数
    bottle_available: int                        # 架上玻璃瓶可用总数
    powder_staging_remaining: int                # 暂存 A 剩余可用
    bottle_staging_remaining: int                # 暂存 B 剩余可用


# ---------------------------------------------------------------------------
# ConsumableManager
# ---------------------------------------------------------------------------


class ConsumableManager:
    """耗材管理核心。

    线程安全：asyncio.Lock 保护所有状态修改操作。
    无 PLC/UI 依赖：可独立实例化和单元测试。

    决策模式（与 Expand_Target_Tank 同构）：
        PC 写决策值 → PLC 读取执行

    决策输出（协议 v2.5）：
        prepare_for_scrape  → PrepareDecision(op, fetch_rack_plate, old_plate_slot, consume_slot)
        prepare_for_collect → PrepareDecision(同上）
    """

    def __init__(self, persistence_path: Optional[Path] = None) -> None:
        self._lock = asyncio.Lock()
        # 暂存（PC 单方面维护，无传感器）
        self._staging: dict[StagingId, Optional[StagedPlate]] = {
            StagingId.A: None,
            StagingId.B: None,
        }
        # 架上 72 孔位账本（实验员录入 + 决策消耗，与 DI 独立）
        self._rack: list[RackSlot] = self._init_rack()
        # 12 个板级 DI（PLC 实时同步，仅作防呆）
        self._plate_present: list[bool] = [False] * PLATE_SENSOR_COUNT
        # 每样品最近一次决策记录 {sample_id: (fetch_rack_plate, consume_slot, staging_id)}
        self._decisions: dict[str, tuple[int, int, StagingId]] = {}
        # 账本持久化 JSON 文件（None = 纯内存，用于 mock/测试场景）
        self._persistence_path: Optional[Path] = persistence_path
        if persistence_path is not None:
            self._load_from_disk()

    # ------------------------------------------------------------------
    # 决策接口（核心）
    # ------------------------------------------------------------------

    async def prepare_for_scrape(
        self, sample_id: str,
    ) -> PrepareDecision:
        """为 Scrape 生成耗材搬运决策参数（协议 v2.5）。

        原子操作：在 lock 内完成暂存状态检查 + take()，
        确保并发样品不会分配到同一孔位。

        Returns:
            PrepareDecision(op, fetch_rack_plate, old_plate_slot, consume_slot)
            - op=OP_NONE     暂存有余量，复用（fetch=0, old=0）
            - op=OP_PUT_NEW  暂存空，仅放新板（fetch=1-12, old=0）
            - op=OP_SWAP     暂存耗尽，先取旧板回料架原孔再放新板（fetch=1-12, old=1-12）

        Raises:
            ConsumableExhaustedError: 架上账本无可用粉末收集器
            ConsumablePlateMissingError: 账本可用但所有候选板 DI 都不在位

        注意：has_filled_bottles 不再阻塞——板满（is_exhausted=True）时
        自动走 SWAP 路径，机器人将满板归还料架并取新板。
        """
        async with self._lock:
            staging = self._staging[StagingId.A]
            if staging is not None:
                assert isinstance(staging.plate_id, int), (
                    f"plate_id 类型异常: {type(staging.plate_id).__name__} "
                    f"(预期 int 显示编号 1-6)"
                )

            # 路径 1：暂存有余量（含 AVAILABLE 孔）→ 不搬运，复用暂存
            if staging is not None and not staging.is_exhausted:
                slot = staging.next_available_slot()
                assert slot is not None, "is_exhausted=False 但 next_available_slot=None"
                staging.take(slot)
                self._decisions[sample_id] = (0, slot, StagingId.A)
                log.info(
                    "[CM] prepare_for_scrape: 复用暂存 A, slot=%d (sample=%s)",
                    slot, sample_id,
                )
                self._save_to_disk()
                return PrepareDecision(
                    op=OP_NONE, fetch_rack_plate=0,
                    old_plate_slot=0, consume_slot=slot,
                )

            # 路径 2：暂存空/耗尽 → 找架上有耗材的粉末板
            old_plate_num = (
                staging.plate_id
                if (staging is not None and staging.is_exhausted)
                else 0
            )
            candidates = self._find_available_plate_candidates(
                ConsumableType.POWDER_COLLECTOR,
            )
            if not candidates:
                raise ConsumableExhaustedError(
                    "架上无可用粉末收集器（账本全空）"
                )
            new_plate = self._pick_plate_in_position(candidates, ConsumableType.POWDER_COLLECTOR)
            if new_plate is None:
                raise ConsumablePlateMissingError(
                    f"账本可用粉末板 {candidates} 全部 DI 不在位，"
                    "请补放料板或在 UI 清空账本对应项"
                )

            # 标记架上该板所有孔位为已搬走（预防重复分配）
            self._mark_plate_consumed(new_plate, ConsumableType.POWDER_COLLECTOR)

            # 创建新暂存板，立即 take 第 1 孔
            new_staging = StagedPlate(
                plate_id=new_plate,
                consumable_type=ConsumableType.POWDER_COLLECTOR,
            )
            new_staging.take(1)
            self._staging[StagingId.A] = new_staging
            self._decisions[sample_id] = (0, 1, StagingId.A)
            op = OP_SWAP if old_plate_num > 0 else OP_PUT_NEW
            log.info(
                "[CM] prepare_for_scrape: op=%s 新板=%d old=%d slot=1 (sample=%s)",
                _op_name(op), new_plate, old_plate_num, sample_id,
            )
            self._save_to_disk()
            return PrepareDecision(
                op=op, fetch_rack_plate=new_plate,
                old_plate_slot=old_plate_num, consume_slot=1,
            )

    async def prepare_for_collect(
        self, sample_id: str,
    ) -> PrepareDecision:
        """为 Collect 生成耗材搬运决策参数（玻璃收集瓶，暂存 B，协议 v2.5）。

        语义与 prepare_for_scrape 对称，作用于暂存 B。

        Returns:
            PrepareDecision(op, fetch_rack_plate, old_plate_slot, consume_slot)

        Raises:
            ConsumableExhaustedError: 架上账本无可用玻璃收集瓶
            ConsumablePlateMissingError: 账本可用但所有候选板 DI 都不在位

        注意：has_filled_bottles 不再阻塞——板满（is_exhausted=True）时
        自动走 SWAP 路径，机器人将满板归还料架并取新板。
        """
        async with self._lock:
            staging = self._staging[StagingId.B]
            if staging is not None:
                assert isinstance(staging.plate_id, int), (
                    f"plate_id 类型异常: {type(staging.plate_id).__name__} "
                    f"(预期 int 显示编号 1-6)"
                )

            # 路径 1：暂存有余量（含 AVAILABLE 孔）→ 复用
            if staging is not None and not staging.is_exhausted:
                slot = staging.next_available_slot()
                assert slot is not None
                staging.take(slot)
                self._decisions[sample_id] = (0, slot, StagingId.B)
                log.info(
                    "[CM] prepare_for_collect: 复用暂存 B, slot=%d (sample=%s)",
                    slot, sample_id,
                )
                self._save_to_disk()
                return PrepareDecision(
                    op=OP_NONE, fetch_rack_plate=0,
                    old_plate_slot=0, consume_slot=slot,
                )

            # 路径 2：暂存空/耗尽 → 找架上玻璃瓶板
            old_plate_num = (
                staging.plate_id
                if (staging is not None and staging.is_exhausted)
                else 0
            )
            candidates = self._find_available_plate_candidates(
                ConsumableType.GLASS_BOTTLE,
            )
            if not candidates:
                raise ConsumableExhaustedError(
                    "架上无可用玻璃收集瓶（账本全空）"
                )
            new_plate = self._pick_plate_in_position(candidates, ConsumableType.GLASS_BOTTLE)
            if new_plate is None:
                raise ConsumablePlateMissingError(
                    f"账本可用玻璃瓶板 {candidates} 全部 DI 不在位，"
                    "请补放料板或在 UI 清空账本对应项"
                )

            self._mark_plate_consumed(new_plate, ConsumableType.GLASS_BOTTLE)
            new_staging = StagedPlate(
                plate_id=new_plate,
                consumable_type=ConsumableType.GLASS_BOTTLE,
            )
            new_staging.take(1)
            self._staging[StagingId.B] = new_staging
            self._decisions[sample_id] = (0, 1, StagingId.B)
            op = OP_SWAP if old_plate_num > 0 else OP_PUT_NEW
            log.info(
                "[CM] prepare_for_collect: op=%s 新板=%d old=%d slot=1 (sample=%s)",
                _op_name(op), new_plate, old_plate_num, sample_id,
            )
            self._save_to_disk()
            return PrepareDecision(
                op=op, fetch_rack_plate=new_plate,
                old_plate_slot=old_plate_num, consume_slot=1,
            )

    # ------------------------------------------------------------------
    # 跨工位绑定查询（Phase 4 v2.5）
    # ------------------------------------------------------------------

    async def get_powder_return_slot(self, sample_id: str) -> int:
        """读取最近一次 prepare_for_scrape 写入的 consume_slot。

        用于 CollectStage 写入 `collect_Powder_Return_Slot`，让 PLC Step 50
        把粉末收集器归还到暂存 A 的原始孔位。

        **关键时序**：CollectStage 必须先调用本接口再调用 prepare_for_collect，
        因为后者会用 (_, _, StagingId.B) 覆盖 _decisions[sample_id]。

        Returns:
            slot ∈ [1,6]  : 命中粉末收集器决策记录
            0             : 无决策记录 / 决策为玻璃瓶（语义错位）
        """
        async with self._lock:
            decision = self._decisions.get(sample_id)
            if decision is None:
                log.error(
                    "[CM] get_powder_return_slot: 无决策记录 sample=%s",
                    sample_id,
                )
                return 0
            _, slot, staging_id = decision
            if staging_id != StagingId.A:
                log.error(
                    "[CM] get_powder_return_slot: 决策 staging=%s 非 A (sample=%s)",
                    staging_id, sample_id,
                )
                return 0
            return slot

    # ------------------------------------------------------------------
    # 入队前预检（RecipeTask 在 Phase 1 前调用）
    # ------------------------------------------------------------------

    def check_availability(
        self,
        *,
        need_powder: bool = False,
        need_bottle: bool = False,
    ) -> list[str]:
        """检查耗材可用性（不消耗资源，供入队前预检）。

        Args:
            need_powder: 是否需要粉末收集器（scrape 启用时为 True）
            need_bottle: 是否需要玻璃收集瓶（collect 启用时为 True）

        Returns:
            警告消息列表（空列表 = 全部可用）。不抛异常，调用方决定是否阻塞。
        """
        warnings: list[str] = []

        if need_powder:
            staging_a = self._staging[StagingId.A]
            if staging_a is not None and not staging_a.is_exhausted:
                pass  # 暂存 A 有余量
            else:
                ctype = ConsumableType.POWDER_COLLECTOR
                candidates = self._find_available_plate_candidates(ctype)
                if not candidates:
                    warnings.append(
                        "粉末收集器耗尽且架上无可用粉末板（账本全空）"
                    )
                else:
                    in_pos = self._pick_plate_in_position(candidates, ctype)
                    if in_pos is None:
                        warnings.append(
                            f"粉末收集器耗尽，账本可用板 {candidates} 全部 DI 不在位"
                        )

        if need_bottle:
            staging_b = self._staging[StagingId.B]
            if staging_b is not None and not staging_b.is_exhausted:
                pass  # 暂存 B 有余量
            else:
                ctype = ConsumableType.GLASS_BOTTLE
                candidates = self._find_available_plate_candidates(ctype)
                if not candidates:
                    warnings.append(
                        "玻璃收集瓶耗尽且架上无可用玻璃瓶板（账本全空）"
                    )
                else:
                    in_pos = self._pick_plate_in_position(candidates, ctype)
                    if in_pos is None:
                        warnings.append(
                            f"玻璃收集瓶耗尽，账本可用板 {candidates} 全部 DI 不在位"
                        )

        return warnings

    # ------------------------------------------------------------------
    # 完成回调（Stage 报 Done 后调用）
    # ------------------------------------------------------------------

    async def on_scrape_done(self, sample_id: str) -> None:
        """Scrape 完成回调。

        Phase 1 语义：prepare_for_scrape 已原子完成 take()，
        此方法清理决策记录。保留为扩展点（日志/DB/统计）。
        """
        async with self._lock:
            decision = self._decisions.pop(sample_id, None)
            if decision:
                log.debug("[CM] on_scrape_done: sample=%s decision=%s", sample_id, decision)

    async def rollback_for_sample(self, sample_id: str) -> None:
        """Rollback 该样品在 prepare_for_scrape/collect 中已分配但未通过 on_*_done 消费的 staging 占位。

        取消路径调用：将 TAKEN 孔位恢复为 AVAILABLE，不动 DI 缓存。
        幂等：无决策记录时安静跳过。
        并发安全：复用 self._lock，与 prepare_for_* 互斥。
        """
        async with self._lock:
            decision = self._decisions.pop(sample_id, None)
            if decision is None:
                log.debug("[CM] rollback_for_sample: sample=%s 无决策记录，跳过", sample_id)
                return

            _, consume_slot, staging_id = decision
            staging = self._staging.get(staging_id)
            if staging is None:
                log.warning(
                    "[CM] rollback_for_sample: sample=%s staging %s 为空，无法回滚",
                    sample_id, staging_id.value,
                )
                return

            # 将 TAKEN 回滚为 AVAILABLE（仅当当前仍为 TAKEN 时）
            idx = consume_slot - 1
            if 0 <= idx < len(staging.slots) and staging.slots[idx] == SlotStatus.TAKEN:
                staging.slots[idx] = SlotStatus.AVAILABLE
                log.info(
                    "[CM] rollback_for_sample: sample=%s staging=%s slot=%d TAKEN→AVAILABLE",
                    sample_id, staging_id.value, consume_slot,
                )
                self._save_to_disk()
            else:
                log.warning(
                    "[CM] rollback_for_sample: sample=%s staging=%s slot=%d 状态非 TAKEN(%s)，跳过",
                    sample_id, staging_id.value, consume_slot,
                    staging.slots[idx].name if 0 <= idx < len(staging.slots) else "OOB",
                )

    async def on_collect_done(self, sample_id: str) -> None:
        """Collect 完成回调：暂存 B 该孔 TAKEN → FILLED（动作 D 已放回装样瓶）。

        Raises:
            InvalidSlotTransitionError: 重复调用或状态异常
        """
        async with self._lock:
            decision = self._decisions.pop(sample_id, None)
            if decision is None:
                log.warning("[CM] on_collect_done: sample=%s 无决策记录", sample_id)
                return

            _, consume_slot, _ = decision
            staging = self._staging[StagingId.B]
            if staging is None:
                log.warning("[CM] on_collect_done: 暂存 B 为空，忽略")
                return

            staging.fill(consume_slot)
            log.info(
                "[CM] on_collect_done: 暂存 B slot %d → FILLED (sample=%s)",
                consume_slot, sample_id,
            )
            self._save_to_disk()

    # ------------------------------------------------------------------
    # PLC 传感器同步（仅板级 DI，不写孔账本）
    # ------------------------------------------------------------------

    async def sync_plate_presence(self, plate_states: list[bool]) -> None:
        """同步 12 个板级 DI 在位状态。

        数据源（协议 v2.3 再修订）：PLC 工程将 12 个位 DI 打包为
        `IX11` / `IX12` 两个 BYTE（不是 ARRAY[1..12] OF BOOL），
        上位机 `PLCClient.read_consumable_sensor()` 内部位解码后
        传入本方法，调用者拿到的仍是长度 12 的 list[bool]。

        语义：
        - 仅更新内部 `_plate_present` 缓存，供 prepare_for_* 决策防呆使用。
        - **不写 `_rack` 账本**：孔位 has_consumable 仅由实验员录入接口与决策消耗变更。

        Args:
            plate_states: 长度 12 的 bool 列表，索引 0 对应板 1
                          （1-6 = 粉末板，7-12 = 玻璃瓶板）。

        Raises:
            ValueError: plate_states 长度不为 12
        """
        if len(plate_states) != PLATE_SENSOR_COUNT:
            raise ValueError(
                f"plate_states 长度必须为 {PLATE_SENSOR_COUNT}，收到 {len(plate_states)}"
            )
        async with self._lock:
            self._plate_present = list(plate_states)

    def detect_inconsistencies(self) -> list[tuple[int, ConsumableType]]:
        """检测“账本可用但 DI 不在位”的板号列表。

        返回 (display_num, consumable_type) 元组列表，供 UI 告警条显示。
        无锁读（最终一致性）。
        """
        out: list[tuple[int, ConsumableType]] = []
        for ctype in (ConsumableType.POWDER_COLLECTOR, ConsumableType.GLASS_BOTTLE):
            for display_num in sorted(PLATES_BY_TYPE[ctype]):
                internal = _display_to_internal(display_num, ctype)
                start = (internal - 1) * SLOTS_PER_PLATE
                indices = range(start, start + SLOTS_PER_PLATE)
                ledger_has = any(self._rack[i].has_consumable for i in indices)
                di_present = self._plate_present[internal - 1]
                if ledger_has and not di_present:
                    out.append((display_num, ctype))
        return out

    # ------------------------------------------------------------------
    # 账本录入接口（实验员 UI 调用）
    # ------------------------------------------------------------------

    async def mark_plate_loaded(
        self, internal_num: int, slots: Optional[list[int]] = None,
    ) -> None:
        """装入新板：将该板指定孔位置为可用（默认 6 孔全装）。

        Args:
            internal_num: 内部索引 1-12（粉末 1-6 / 玻璃 7-12）
            slots: 1-6 孔位号列表；None = [1..6] 满孔装入。
        """
        self._validate_internal_num(internal_num)
        if slots is None:
            target_slots = list(range(1, SLOTS_PER_PLATE + 1))
        else:
            target_slots = []
            for s in slots:
                if not 1 <= s <= SLOTS_PER_PLATE:
                    raise ValueError(f"slot {s} 越界（1-{SLOTS_PER_PLATE}）")
                target_slots.append(s)
        target_set = set(target_slots)
        async with self._lock:
            for s in range(1, SLOTS_PER_PLATE + 1):
                idx = (internal_num - 1) * SLOTS_PER_PLATE + s
                self._rack[idx - 1].has_consumable = (s in target_set)
            log.info(
                "[CM] mark_plate_loaded: internal=%d, slots=%s",
                internal_num, sorted(target_set),
            )
            self._save_to_disk()

    async def mark_plate_emptied(self, internal_num: int) -> None:
        """整板清空：该板 6 孔全部置为不可用。"""
        self._validate_internal_num(internal_num)
        async with self._lock:
            for s in range(1, SLOTS_PER_PLATE + 1):
                idx = (internal_num - 1) * SLOTS_PER_PLATE + s
                self._rack[idx - 1].has_consumable = False
            log.info("[CM] mark_plate_emptied: internal=%d", internal_num)
            self._save_to_disk()

    async def mark_slot_loaded(self, internal_num: int, slot: int) -> None:
        """单孔补录为可用。"""
        self._validate_internal_num(internal_num)
        if not 1 <= slot <= SLOTS_PER_PLATE:
            raise ValueError(f"slot {slot} 越界（1-{SLOTS_PER_PLATE}）")
        async with self._lock:
            idx = (internal_num - 1) * SLOTS_PER_PLATE + slot
            self._rack[idx - 1].has_consumable = True
            log.info("[CM] mark_slot_loaded: internal=%d slot=%d", internal_num, slot)
            self._save_to_disk()

    async def mark_slot_used(self, internal_num: int, slot: int) -> None:
        """单孔点改为已用。"""
        self._validate_internal_num(internal_num)
        if not 1 <= slot <= SLOTS_PER_PLATE:
            raise ValueError(f"slot {slot} 越界（1-{SLOTS_PER_PLATE}）")
        async with self._lock:
            idx = (internal_num - 1) * SLOTS_PER_PLATE + slot
            self._rack[idx - 1].has_consumable = False
            log.info("[CM] mark_slot_used: internal=%d slot=%d", internal_num, slot)
            self._save_to_disk()

    @staticmethod
    def _validate_internal_num(internal_num: int) -> None:
        if not 1 <= internal_num <= TOTAL_PLATES:
            raise ValueError(
                f"internal_num 必须在 1-{TOTAL_PLATES}，收到 {internal_num}"
            )

    # ------------------------------------------------------------------
    # 手动修正接口（UI 调用）
    # ------------------------------------------------------------------

    async def manual_reset_staging(
        self, staging_id: StagingId, plate_id: int,
    ) -> None:
        """重置暂存板为全 AVAILABLE（人工换板 / 异常恢复）。

        Args:
            staging_id: 暂存工位（A 或 B）
            plate_id: 显示编号 1-6
        """
        expected_type = (
            ConsumableType.POWDER_COLLECTOR
            if staging_id == StagingId.A
            else ConsumableType.GLASS_BOTTLE
        )
        valid_plates = PLATES_BY_TYPE[expected_type]
        if plate_id not in valid_plates:
            raise ValueError(
                f"板号 {plate_id} 不属于暂存 {staging_id.value} 的有效板 "
                f"（有效: {sorted(valid_plates)}）"
            )
        async with self._lock:
            self._staging[staging_id] = StagedPlate(
                plate_id=plate_id,
                consumable_type=expected_type,
                slots=[SlotStatus.AVAILABLE] * SLOTS_PER_PLATE,
            )
            log.info(
                "[CM] manual_reset_staging: %s → 板 %d 全 AVAILABLE",
                staging_id.value, plate_id,
            )
            self._save_to_disk()

    async def manual_set_staging_slot(
        self,
        staging_id: StagingId,
        slot_number: int,
        status: SlotStatus,
    ) -> None:
        """修正暂存单孔状态（UI 点选修正）。

        Raises:
            ValueError: 暂存为空或 slot_number 越界
        """
        async with self._lock:
            staging = self._staging[staging_id]
            if staging is None:
                raise ValueError(f"暂存 {staging_id.value} 为空，无法修正")
            staging._validate_slot(slot_number)
            old = staging.slots[slot_number - 1]
            staging.slots[slot_number - 1] = status
            log.info(
                "[CM] manual_set_staging_slot: %s slot %d: %s → %s",
                staging_id.value, slot_number, old.name, status.name,
            )
            self._save_to_disk()

    async def manual_clear_filled_bottles(self, staging_id: StagingId) -> None:
        """人工取走 FILLED 玻璃瓶后将暂存板重置为 None。

        下次 prepare_for_xxx 会从架上搬新板。

        Raises:
            ValueError: 暂存为空或不含 FILLED
        """
        async with self._lock:
            staging = self._staging[staging_id]
            if staging is None:
                raise ValueError(f"暂存 {staging_id.value} 为空")
            if not staging.has_filled_bottles:
                raise ValueError(f"暂存 {staging_id.value} 无 FILLED 孔位")
            self._staging[staging_id] = None
            log.info("[CM] manual_clear_filled_bottles: %s 已清空", staging_id.value)
            self._save_to_disk()

    async def manual_remove_staging(self, staging_id: StagingId) -> None:
        """移除暂存板（设为 None），下次 prepare_for_xxx 会从架上搬新板。"""
        async with self._lock:
            self._staging[staging_id] = None
            log.info("[CM] manual_remove_staging: %s 已移除", staging_id.value)
            self._save_to_disk()

    async def manual_set_rack_slot(
        self, internal_num: int, slot: int, has_consumable: bool,
    ) -> None:
        """修正架上单个孔位（UI 点选修正）。

        Args:
            internal_num: 内部索引 1-12
            slot: 孔位 1-6
        """
        self._validate_internal_num(internal_num)
        if not 1 <= slot <= SLOTS_PER_PLATE:
            raise ValueError(f"slot {slot} 越界（1-{SLOTS_PER_PLATE}）")
        async with self._lock:
            idx = (internal_num - 1) * SLOTS_PER_PLATE + slot
            self._rack[idx - 1].has_consumable = has_consumable
            log.info(
                "[CM] manual_set_rack_slot: internal=%d slot=%d → has_consumable=%s",
                internal_num, slot, has_consumable,
            )
            self._save_to_disk()

    # ------------------------------------------------------------------
    # 快照（UI 渲染）
    # ------------------------------------------------------------------

    def snapshot(self) -> ConsumableSnapshot:
        """返回不可变快照供 UI/Dashboard 渲染（无锁读，最终一致性）。

        StagedPlate 和 RackSlot 是可变 dataclass，快照中为引用拷贝；
        UI 层应在渲染前读取字段值，不持有长期引用。
        """
        powder_rack = sum(
            1 for s in self._rack
            if s.consumable_type == ConsumableType.POWDER_COLLECTOR and s.has_consumable
        )
        bottle_rack = sum(
            1 for s in self._rack
            if s.consumable_type == ConsumableType.GLASS_BOTTLE and s.has_consumable
        )
        staging_a = self._staging[StagingId.A]
        staging_b = self._staging[StagingId.B]
        return ConsumableSnapshot(
            staging={
                StagingId.A.value: staging_a,
                StagingId.B.value: staging_b,
            },
            rack=tuple(self._rack),
            plate_present=tuple(self._plate_present),
            powder_available=powder_rack,
            bottle_available=bottle_rack,
            powder_staging_remaining=(
                staging_a.remaining_available if staging_a else 0
            ),
            bottle_staging_remaining=(
                staging_b.remaining_available if staging_b else 0
            ),
        )

    # ------------------------------------------------------------------
    # 账本持久化（write-through JSON）
    # ------------------------------------------------------------------

    def _save_to_disk(self) -> None:
        """write-through 持久化（持锁时调用）。失败仅 log，不抛。

        使用 .tmp 临时文件 + replace 原子替换，避免部分写入损坏。
        """
        if self._persistence_path is None:
            return
        try:
            path = self._persistence_path
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._serialize()
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as e:  # pragma: no cover - 防御性仅记录
            log.error("[CM] _save_to_disk 失败: %s", e)

    def _load_from_disk(self) -> None:
        """启动期加载（__init__ 调用，同步）。

        文件不存在/损坏 → log + 退化为空账本，不抛异常。
        """
        if self._persistence_path is None or not self._persistence_path.exists():
            return
        try:
            text = self._persistence_path.read_text(encoding="utf-8")
            data = json.loads(text)
            self._deserialize(data)
            log.info(
                "[CM] _load_from_disk: 账本恢复完成 (%s)",
                self._persistence_path,
            )
        except Exception as e:
            log.error(
                "[CM] _load_from_disk 失败，退化为空账本: %s", e,
            )
            # 不抛，保持 _init_rack 默认状态

    def _serialize(self) -> dict:
        return {
            "schema_version": PERSISTENCE_SCHEMA_VERSION,
            "rack": [s.has_consumable for s in self._rack],
            "staging": {
                sid.value: (
                    None if plate is None
                    else {
                        "plate_id": plate.plate_id,
                        "consumable_type": plate.consumable_type.value,
                        "slots": [int(s) for s in plate.slots],
                    }
                )
                for sid, plate in self._staging.items()
            },
        }

    def _deserialize(self, data: dict) -> None:
        rack_states = data.get("rack", [])
        if isinstance(rack_states, list) and len(rack_states) == TOTAL_RACK_SLOTS:
            for i, val in enumerate(rack_states):
                self._rack[i].has_consumable = bool(val)
        else:
            log.warning(
                "[CM] _deserialize: rack 字段长度异常 (%s)，保持默认空账本",
                len(rack_states) if isinstance(rack_states, list) else type(rack_states),
            )
        staging_data = data.get("staging") or {}
        for sid_str, plate_data in staging_data.items():
            try:
                sid = StagingId(sid_str)
            except ValueError:
                continue
            if plate_data is None:
                self._staging[sid] = None
                continue
            try:
                raw_plate_id = plate_data["plate_id"]
                # 向后兼容：旧格式 "A"→1, "G"→1(glass) 等
                if isinstance(raw_plate_id, str):
                    internal = ord(raw_plate_id.upper()) - ord('A') + 1
                    ctype = ConsumableType(plate_data["consumable_type"])
                    display = _internal_to_display(internal, ctype)
                else:
                    display = int(raw_plate_id)
                self._staging[sid] = StagedPlate(
                    plate_id=display,
                    consumable_type=ConsumableType(plate_data["consumable_type"]),
                    slots=[SlotStatus(int(s)) for s in plate_data["slots"]],
                )
            except (KeyError, ValueError, TypeError) as e:
                log.warning(
                    "[CM] 反序列化暂存 %s 失败: %s", sid_str, e,
                )
                self._staging[sid] = None

    # ------------------------------------------------------------------
    # 索引转换 helper（纯静态方法）
    # ------------------------------------------------------------------

    @staticmethod
    def slot_id_to_index(slot_id: str) -> int:
        """"1-3" → 3, "7-2" → 38, "12-6" → 72。

        兼容旧格式 "A3" → 3（向后兼容加载旧 JSON）。
        """
        # 新格式: "P-S"
        if '-' in slot_id:
            parts = slot_id.split('-')
            if len(parts) == 2:
                try:
                    internal = int(parts[0])
                    position = int(parts[1])
                    if 1 <= internal <= TOTAL_PLATES and 1 <= position <= SLOTS_PER_PLATE:
                        return (internal - 1) * SLOTS_PER_PLATE + position
                except ValueError:
                    pass
            raise ValueError(f"slot_id 格式非法: {slot_id!r}（期望如 '1-3'）")
        # 旧格式: "A3" → 向后兼容
        if len(slot_id) >= 2 and slot_id[0].isalpha() and slot_id[1:].isdigit():
            plate_letter = slot_id[0].upper()
            position = int(slot_id[1:])
            plate_num = ord(plate_letter) - ord('A') + 1
            if 1 <= plate_num <= TOTAL_PLATES and 1 <= position <= SLOTS_PER_PLATE:
                return (plate_num - 1) * SLOTS_PER_PLATE + position
        raise ValueError(f"slot_id 格式非法: {slot_id!r}")

    @staticmethod
    def index_to_slot_id(index: int) -> str:
        """3 → '1-3', 38 → '7-2', 72 → '12-6'。"""
        if not 1 <= index <= TOTAL_RACK_SLOTS:
            raise ValueError(f"index 必须在 1-{TOTAL_RACK_SLOTS}，收到 {index}")
        internal = (index - 1) // SLOTS_PER_PLATE + 1
        position = (index - 1) % SLOTS_PER_PLATE + 1
        return f"{internal}-{position}"

    @staticmethod
    def plate_to_indices(internal_num: int) -> list[int]:
        """内部索引 → 6 个料架索引（1-based）。

        粉末板 1 → [1,2,3,4,5,6]；玻璃板 7 → [37,38,39,40,41,42]
        """
        if not 1 <= internal_num <= TOTAL_PLATES:
            raise ValueError(f"internal_num 必须在 1-{TOTAL_PLATES}，收到 {internal_num}")
        start = (internal_num - 1) * SLOTS_PER_PLATE + 1
        return list(range(start, start + SLOTS_PER_PLATE))

    # ------------------------------------------------------------------
    # 内部 helper
    # ------------------------------------------------------------------

    @staticmethod
    def _init_rack() -> list[RackSlot]:
        """初始化 72 个架上孔位（默认 has_consumable=False，等待实验员在 UI 录入或从磁盘恢复）。"""
        rack: list[RackSlot] = []
        for internal in range(1, TOTAL_PLATES + 1):
            ctype = (
                ConsumableType.POWDER_COLLECTOR if internal <= 6
                else ConsumableType.GLASS_BOTTLE
            )
            display = _internal_to_display(internal, ctype)
            for pos in range(1, SLOTS_PER_PLATE + 1):
                rack.append(RackSlot(
                    slot_id=f"{internal}-{pos}",
                    plate_id=str(display),
                    position=pos,
                    consumable_type=ctype,
                    has_consumable=False,
                ))
        return rack

    def _find_available_plate_candidates(self, ctype: ConsumableType) -> list[int]:
        """返回账本中该类型下“有可用孔”的板显示编号列表（顺序扫描，需持锁）。"""
        candidates: list[int] = []
        for display_num in sorted(PLATES_BY_TYPE[ctype]):
            internal = _display_to_internal(display_num, ctype)
            start = (internal - 1) * SLOTS_PER_PLATE
            if any(self._rack[start + i].has_consumable for i in range(SLOTS_PER_PLATE)):
                candidates.append(display_num)
        return candidates

    def _pick_plate_in_position(self, candidates: list[int], ctype: ConsumableType) -> Optional[int]:
        """从候选板中返回首个 DI 在位的显示编号；全部不在位返回 None（需持锁）。"""
        for display_num in candidates:
            internal = _display_to_internal(display_num, ctype)
            if self._plate_present[internal - 1]:
                return display_num
        return None

    def _mark_plate_consumed(self, display_num: int, ctype: ConsumableType) -> None:
        """标记架上该板所有孔位为已搬走（需持有 _lock 时调用）。"""
        internal = _display_to_internal(display_num, ctype)
        start = (internal - 1) * SLOTS_PER_PLATE
        for i in range(SLOTS_PER_PLATE):
            self._rack[start + i].has_consumable = False
