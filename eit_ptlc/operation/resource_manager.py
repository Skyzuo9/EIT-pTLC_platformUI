"""ResourceManager - 展缸资源管理器
====================================
协议 v1.3 多通道展开：管理样品→展缸的绑定关系。

职责：
- allocate(sample_id) → tank_id：从 Idle 池选取空闲展缸，绑定样品
- release(tank_id)：解绑样品，写 PLC Tank_State[tank_id]=0
- sync_states()：从 PLC 同步 Tank_State 数组（1次网络往返）
- 查询接口：get_tank_state / get_tank_for_sample / idle_tanks

Phase 1 简化：
- allocate 取首个 Idle 缸（默认 Tank 1）
- 不设独立轮询，按需 sync_states
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from eit_ptlc.controller.plc_controller import PlcController

log = logging.getLogger(__name__)

TANK_COUNT = 8


class TankStatus(Enum):
    """展缸状态枚举——与 PLC Tank_State 数组值对齐。"""
    IDLE = 0          # 可分配
    PREPPING = 10     # 准备中（润洗+上液+放板）
    DEVELOPING = 40   # 展开中
    DRAINING = 50     # 排液中
    BLOW_AIR = 55     # 吹气清扫（排液子步 Phase B）
    CYLINDER = 60     # 气缸退回（排液子步 Phase C）
    ROBOT_PICKUP = 65 # 机器人取板（排液子步 Phase D，电平握手串行）
    ERROR = 90        # PLC 侧故障
    NEEDS_DRAIN = 91  # PC 侧虚拟状态（不对应 PLC Tank_State，禁止数值比较）
    DONE = 99         # 排液完成，待释放


@dataclass
class TankInfo:
    """单缸跟踪信息。

    handoff_pending：DevelopStage Phase 3 收到 Drain_Done=TRUE 后，物理上硅胶板仍在缸中
    等待机器人取走送至拍照刮板工位。在 RecipeTask 拿到 ScrapeStage._scrape_lock 之前，
    本缸仍被占用，不可重新分配；sync_states() 的 DONE 自动释放也不能插手。
    该标记由 mark_handoff_pending() 置位，release() 清除。
    """
    tank_id: int
    state: TankStatus = TankStatus.IDLE
    sample_id: Optional[str] = None
    allocated_at: Optional[float] = None
    handoff_pending: bool = False


class ResourceManager:
    """展缸资源管理器——管理样品→展缸的绑定生命周期。

    使用方式：
        rm = ResourceManager(plc_client)
        tank_id = await rm.allocate("S001", preferred_tank=1)
        # ... develop stage runs ...
        await rm.release(tank_id)

    并发支持：
        allocate() 无可用缸时，通过 asyncio.Condition 等待 release() 通知，
        而非直接抛 RuntimeError。多个并发任务可同时等待，release 唤醒所有等待者。
    """

    def __init__(self, plc: "PlcController") -> None:
        self._plc = plc
        self._tanks: dict[int, TankInfo] = {
            i: TankInfo(tank_id=i) for i in range(1, TANK_COUNT + 1)
        }
        self._lock = asyncio.Lock()
        self._tank_available = asyncio.Condition(self._lock)
        # 可选: WaterLevelClient 引用, 用于按需启停摄像头
        self._wl_client = None
        self._wl_stream_channels: set[int] = set()

    def set_water_level_client(self, wl_client) -> None:
        """注入 WaterLevelClient 引用, 启用摄像头按需启停。

        若未设置, RM 正常工作但不自动管理液位摄像头。
        """
        self._wl_client = wl_client

    def set_stream_channels(self, channels: set[int]) -> None:
        """设置需要 MJPEG 流的通道 (来自 UI Debug Tab)。"""
        self._wl_stream_channels = set(channels)

    async def _sync_active_channels(self) -> None:
        """计算当前需要监控的通道集合并下发到香橙派。

        规则:
          - 非 IDLE/DONE 状态的缸 → 需要监控
          - ERROR 状态的缸也保留监控 (诊断用途)
          - stream_channels 额外获得 MJPEG 流
        """
        if self._wl_client is None:
            return
        active = []
        for tank_id, info in self._tanks.items():
            if info.state not in (TankStatus.IDLE, TankStatus.DONE):
                active.append(tank_id)
            elif info.state == TankStatus.ERROR:
                active.append(tank_id)
        active = list(set(active))
        stream = [t for t in self._wl_stream_channels if t in active]
        try:
            await self._wl_client.send_command("set_active_channels", {
                "channels": active,
                "stream_channels": stream,
            })
        except Exception as e:
            log.warning("[RM] sync_active_channels 失败: %s", e)

    # ------------------------------------------------------------------
    # 核心操作
    # ------------------------------------------------------------------

    async def allocate(self, sample_id: str, preferred_tank: Optional[int] = None) -> int:
        """为样品分配空闲展缸。

        策略（偏好+降级）：
          1. 若指定 preferred_tank 且该缸空闲，优先分配该缸
          2. 指定缸被占用 → 记 WARNING 并降级分配首个空闲缸
          3. 无 preferred_tank → 分配首个空闲缸
          4. 全部被占用 → 等待 release() 通知后重试（不抛异常）

        先同步一次 PLC 侧实际状态，再从本地 Idle 池选取。
        分配成功后 sample_id ↔ tank_id 绑定关系锁定。
        """
        async with self._tank_available:
            while True:
                # 持锁调内部 sync（避免 Condition 重入死锁）
                await self._sync_states_locked()
                result = self._try_allocate(sample_id, preferred_tank)
                if result is not None:
                    tank_id = result
                    break
                # 无可用缸 → 等待释放通知
                log.info("[RM] 无可用展缸，等待释放... (sample=%s)", sample_id)
                await self._tank_available.wait()
        # 锁外同步液位摄像头状态 (fire-and-forget)
        if self._wl_client:
            asyncio.create_task(self._sync_active_channels())
        return tank_id

    def _try_allocate(self, sample_id: str, preferred_tank: Optional[int] = None) -> Optional[int]:
        """尝试分配空闲展缸（内部方法，无锁保护，需在持有 _lock 时调用）。

        Returns:
            int: 分配的 tank_id；None 表示无可用缸。
        """
        # 1. 优先尝试偏好缸
        if preferred_tank is not None and 1 <= preferred_tank <= TANK_COUNT:
            info = self._tanks[preferred_tank]
            if info.state == TankStatus.IDLE and info.sample_id is None:
                info.sample_id = sample_id
                info.allocated_at = time.monotonic()
                log.info(
                    "[RM] 展缸分配(偏好命中): tank=%d → sample=%s",
                    info.tank_id, sample_id,
                )
                return info.tank_id
            else:
                log.warning(
                    "[RM] 偏好缸 %d 不可用(state=%s, sample=%s)，降级分配",
                    preferred_tank, info.state.name, info.sample_id,
                )
        # 2. 降级：分配首个空闲缸
        for info in self._tanks.values():
            if info.state == TankStatus.IDLE and info.sample_id is None:
                info.sample_id = sample_id
                info.allocated_at = time.monotonic()
                log.info(
                    "[RM] 展缸分配(降级): tank=%d → sample=%s (preferred=%s)",
                    info.tank_id, sample_id, preferred_tank,
                )
                return info.tank_id
        return None

    async def mark_handoff_pending(self, tank_id: int) -> None:
        """标记展缸进入 "handoff 等待" 状态。

        调用场景：DevelopStage Phase 4 收到 Drain_Done=TRUE 后。此时从 PLC 控件看
        缸状态是 DONE(99)，但上位机不能立刻释放资源——物理上硅胶板还在缸中等待
        机器人取走送至拍照刮板工位，RecipeTask 拿到 ScrapeStage._scrape_lock 那一刻
        才是物理转移完成点。

        效果：
        - sync_states() 的 DONE 自动释放跳过本缸
        - release() 调用后清除本标记
        """
        async with self._tank_available:
            self._tanks[tank_id].handoff_pending = True
            log.info(
                "[RM] 展缸标记 handoff_pending: tank=%d (sample=%s)——等待拍照刮板工位接管",
                tank_id, self._tanks[tank_id].sample_id,
            )

    async def release(self, tank_id: int, *, mark_needs_drain: bool = False) -> None:
        """释放展缸：解绑样品 + 写 PLC Tank_State[tank_id]=0 + 清排液信号。

        安全保证：仅在 PLC 不再推进该缸状态时调用
        （排液完成 Done=99 或故障 Error=90）。

        Args:
            mark_needs_drain: 当为 True 时（E-Stop 路径），不写 PLC 也不置
                IDLE，而是标记为 NEEDS_DRAIN 等待人工强制排液。
        """
        async with self._tank_available:
            info = self._tanks[tank_id]
            sample_id = info.sample_id
            info.sample_id = None
            info.allocated_at = None
            info.handoff_pending = False  # 释放后清除 handoff 标记

            if mark_needs_drain:
                # E-Stop 路径：不写 PLC（PLC 侧已由急停逻辑处理），
                # 标记为 NEEDS_DRAIN，等待 Recovery UI 强制排液后才能重用
                info.state = TankStatus.NEEDS_DRAIN
                log.warning(
                    "[RM] 展缸急停标记 NEEDS_DRAIN: tank=%d (was sample=%s)",
                    tank_id, sample_id,
                )
            else:
                info.state = TankStatus.IDLE
                # 写 PLC：缸回归 Idle + 清排液信号
                await self._plc.release_tank(tank_id)
                log.info(
                    "[RM] 展缸释放: tank=%d (was sample=%s)",
                    tank_id, sample_id,
                )
            # 唤醒所有等待 allocate 的协程（即使是 NEEDS_DRAIN 也通知，用于状态刷新）
            self._tank_available.notify_all()
        # 锁外同步液位摄像头状态 (fire-and-forget)
        if self._wl_client:
            asyncio.create_task(self._sync_active_channels())

    async def manual_release(self, tank_id: int) -> None:
        """手动释放 NEEDS_DRAIN 缸（Recovery UI 调用）。

        前提：PLC 侧 Tank_State[tank_id] 已回到 0（IDLE）或 99（DONE，排液完成）。
        将本地状态从 NEEDS_DRAIN → IDLE 并写 PLC 确认。

        Raises:
            RuntimeError: 缸状态不是 NEEDS_DRAIN，或 PLC 侧 Tank_State 不允许释放。
        """
        async with self._tank_available:
            info = self._tanks[tank_id]
            if info.state is not TankStatus.NEEDS_DRAIN:
                raise RuntimeError(
                    f"Tank {tank_id} 状态为 {info.state.name}，仅 NEEDS_DRAIN 缸允许 manual_release"
                )
            # 从 PLC 读取实际状态确认已排液
            try:
                plc_val = await self._plc.read_tank_state(tank_id)
            except Exception as e:
                raise RuntimeError(
                    f"读取 Tank_State[{tank_id}] 失败: {e}"
                ) from e
            # 接受 IDLE(0) 和 DONE(99)：
            #   - 99(DONE): 排液刚完成，PLC 尚未复位到 IDLE，release_tank() 会写回 0
            #   - 0(IDLE): PLC 侧已复位（边缘情况）
            # 拒绝其他状态（40=Developing, 50=Draining, 90=Error 等）
            if plc_val not in (0, TankStatus.DONE.value):
                raise RuntimeError(
                    f"Tank_State[{tank_id}]={plc_val}，排液未完成或状态异常，不允许手动释放"
                )
            info.state = TankStatus.IDLE
            info.sample_id = None
            info.allocated_at = None
            info.handoff_pending = False  # 兜底清理
            await self._plc.release_tank(tank_id)
            log.info("[RM] 展缸手动释放: tank=%d (NEEDS_DRAIN → IDLE)", tank_id)
            self._tank_available.notify_all()
        # 锁外同步液位摄像头状态 (fire-and-forget)
        if self._wl_client:
            asyncio.create_task(self._sync_active_channels())

    async def sync_states(self) -> None:
        """从 PLC 同步 Tank_State 数组（1次网络往返） + 孤儿缸自动释放。
    
        外部入口（如 ui/_periodic_refresh）调本方法。**整段必须持 _tank_available
        锁运行**，否则与 mark_handoff_pending / release / allocate 之间会出现
        TOCTOU——典型场景：read 期间 mark_handoff_pending 设标记，但 sync_states
        之前已决定释放孤儿缸，handoff_pending 跳过失效；以及 notify_all 在无锁
        状态调用触发 "cannot notify on un-acquired lock" 警告。
    
        本地已标记 NEEDS_DRAIN 的缸不从 PLC 覆盖——该状态是 PC 侧虚拟值，
        PLC 侧不可能产生 91，用 PLC 值覆盖会丢失 Recovery UI 的排液跟踪。
    
        同步完成后执行 **孤儿缸自动释放**：PLC 侧 Tank_State=99 且 PC 侧 sample_id=None
        的缸（上一会话残留）才会被 release_tank() 释放回 IDLE。含归属的 DONE 缸
        （sample_id 非空）不在此处处理，由 DevelopStage finally + RecipeTask handoff
        路径负责释放。
        """
        async with self._tank_available:
            await self._sync_states_locked()
    
    async def _sync_states_locked(self) -> None:
        """sync_states 实际实现——**调用方必须已持有 _tank_available 锁**。
    
        拆分动机：allocate() 已在 ``async with self._tank_available:`` 块内，
        如果重新调 sync_states() 会因 asyncio.Condition 不可重入而死锁。
        public sync_states() 自加锁；allocate() 直接调本方法。
        """
        try:
            states = await self._plc.read_all_tank_states()
            for i, val in enumerate(states, start=1):
                # 本地已标记 NEEDS_DRAIN，不从 PLC 覆盖
                if self._tanks[i].state == TankStatus.NEEDS_DRAIN:
                    continue
                try:
                    self._tanks[i].state = TankStatus(val)
                except ValueError:
                    log.warning("[RM] Tank_State[%d]=%d 未知状态值", i, val)
                    self._tanks[i].state = TankStatus.ERROR
        except Exception as e:
            log.warning("[RM] 同步 Tank_State 失败: %s", e)
            return  # 同步失败不执行清扫
    
        # ── DONE 缸收敛扫描（仅清孤儿缸）──
        # 设计原则：sync_states 是 "PLC→PC 镜像同步" 机制，不应篡改业务归属语义。
        #
        # 两类 DONE 缸区分处理：
        #   1. 孤儿缸（sample_id=None）：PLC 上一会话残留，本会话没人负责——自动释放。
        #   2. 含归属（sample_id 非空）：DevelopStage 正在走 handoff 路径，释放权在
        #      DevelopStage finally + RecipeTask scrape_lock 接管路径，sync_states 不介入。
        #      反向可验证：DevelopStage 在 trigger_drain 后立即 mark_handoff_pending，
        #      handoff_pending 覆盖整段 排液中→DONE→RecipeTask 接管；若这里还能扫到
        #      "sample_id 非空 + handoff_pending=False + DONE"，那就是 DevelopStage finally
        #      未走的真异常——该修 bug而不是静默抹平，所以仅 log.warning 允许出头。
        for i, info in self._tanks.items():
            if info.state != TankStatus.DONE:
                continue
            if info.handoff_pending:
                # handoff 中：等 RecipeTask 在 scrape_lock 内显式 release()
                continue
            if info.sample_id is not None:
                # 真异常：DevelopStage 路径未正常进入 handoff_pending 却到达 DONE。
                # 不在此处篡改 sample_id/state，留给 DevelopStage finally 释放路径。
                # 仅告警，避免静默掩盖真实 bug。
                log.warning(
                    "[RM] DONE 缸含归属但未 handoff_pending（异常路径，等 DevelopStage finally 释放）: "
                    "tank=%d sample=%s", i, info.sample_id,
                )
                continue
            # 孤儿缸：PLC 上一会话残留，自动释放
            try:
                await self._plc.release_tank(i)
                info.state = TankStatus.IDLE
                info.allocated_at = None
                log.info("[RM] 孤儿缸自动释放: tank=%d (DONE→IDLE)", i)
                # 持锁状态下 notify_all 合法，不会再触发
                # "cannot notify on un-acquired lock" 警告
                self._tank_available.notify_all()
            except Exception as e:
                log.warning("[RM] 孤儿缸释放失败 tank=%d: %s", i, e)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def idle_tanks(self) -> list[int]:
        """返回所有 Idle 态缸号列表。"""
        return [
            info.tank_id
            for info in self._tanks.values()
            if info.state == TankStatus.IDLE and info.sample_id is None
        ]

    def needs_drain_tanks(self) -> list[int]:
        """返回所有 NEEDS_DRAIN 态缸号列表（供 Recovery UI 拉取）。"""
        return [
            info.tank_id
            for info in self._tanks.values()
            if info.state == TankStatus.NEEDS_DRAIN
        ]

    def get_tank_state(self, tank_id: int) -> TankStatus:
        """获取指定缸当前状态。"""
        return self._tanks[tank_id].state

    def get_tank_for_sample(self, sample_id: str) -> Optional[int]:
        """查询样品绑定的缸号（未绑定返回 None）。"""
        for info in self._tanks.values():
            if info.sample_id == sample_id:
                return info.tank_id
        return None

    def get_tank_info(self, tank_id: int) -> TankInfo:
        """获取指定缸完整信息。"""
        return self._tanks[tank_id]

    def all_tank_info(self) -> dict[int, TankInfo]:
        """返回所有缸完整信息快照 {tank_id: TankInfo}（供 Dashboard 渲染）。"""
        return dict(self._tanks)

    def all_tank_states(self) -> dict[int, TankStatus]:
        """返回所有缸状态快照 {tank_id: TankStatus}。"""
        return {i: info.state for i, info in self._tanks.items()}

    def peek_handoff_pending(self) -> list[tuple[int, Optional[str], Optional[float]]]:
        """返回当前 handoff_pending=True 的缸快照 [(tank_id, sample_id, allocated_at)]。

        仅供 Recovery UI 诊断使用。无锁读取——调用者可接受短暂不一致（与
        Develop/RecipeTask 可能同时在锁内修改该标记），不参与控制路径。
        allocated_at 是 time.monotonic() 时间戳，调用者自行计算差值。
        """
        return [
            (info.tank_id, info.sample_id, info.allocated_at)
            for info in self._tanks.values()
            if info.handoff_pending
        ]
