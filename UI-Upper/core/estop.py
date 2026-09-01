"""EstopBroadcaster - 急停信号广播器
===================================

PLCClient 心跳循环已实现 PLC_EStop 上升沿检测（plc_client.py L940-952），
但 app.py 未注册 on_estop 回调 → 所有运行 Stage 将超时阻塞。

本模块提供：
- 全局 E-Stop 事件（asyncio.Event 单例）
- broadcast_estop(scheduler)：注册为 PLCClient.on_estop 回调
  设置全局事件 + 取消所有运行中任务 + 推送 UI 通知
- is_estop_active()：查询 E-Stop 是否激活（供 StageExecutor 状态映射使用）
- reset_estop(scheduler)：人工确认后清除 E-Stop 状态

设计原则（第一性原理）：
1. E-Stop 是设备事件，不是调度事件 → 状态映射为 ESTOP（非 CANCELLED）
2. 利用已有 CancelledError 清理路径 → task.cancel() 触发 → 零新代码路径
3. 展缸释放依赖 DevelopStage.finally 的 asyncio.shield(release()) → 无需新增逻辑
4. 人工逐工位 Reset → 工业安全原则，不自动批量复位
"""

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── 全局 E-Stop 事件（单例，懒初始化） ──
_estop_event: Optional[asyncio.Event] = None


def _get_estop_event() -> asyncio.Event:
    """获取或创建全局 E-Stop 事件。"""
    global _estop_event
    if _estop_event is None:
        _estop_event = asyncio.Event()
    return _estop_event


def is_estop_active() -> bool:
    """查询 E-Stop 是否处于激活状态。

    供 StageExecutor.execute() 在 CancelledError 时区分 E-Stop 与普通取消。
    """
    return _estop_event is not None and _estop_event.is_set()


async def broadcast_estop(scheduler) -> None:
    """E-Stop 回调：由 PLCClient.on_estop 触发。

    执行顺序：
    1. 设置全局 E-Stop 事件（is_estop_active() → True）
    2. 调用 scheduler.estop_activate() 取消所有运行中任务
    3. 推送 UI 通知（全屏警告）

    任务取消后 CancelledError 传播，各 Stage 的已有清理路径执行：
    - 锁释放（async with 自动）
    - 展缸释放（DevelopStage.finally asyncio.shield）
    - PLC Enable=False（ScrapeStage/BeforePhotoStage 条件化清理）
    """
    log.critical("[E-Stop] ═══ 急停信号触发，广播至所有运行中任务 ═══")
    _get_estop_event().set()

    # 激活 Scheduler 的 E-Stop 模式（取消所有运行中任务 + 暂停调度）
    if scheduler is not None:
        scheduler.estop_activate()

    # 推送 UI 通知（后台任务写 _notification_queue，UI timer 消费）
    try:
        from ui.state import get_state
        state = get_state()
        state.estop_active = True
        state._notification_queue.append(
            ("⚠ 急停信号触发！所有运行中任务已终止，请确认安全后逐工位 Reset", "negative"),
        )
    except Exception:
        pass  # UI 不可用时静默


def reset_estop(scheduler) -> None:
    """清除 E-Stop 状态（人工确认安全后调用）。

    仅清除上位机侧标志，不自动复位 PLC 变量。
    用户需在 Debug Tab 逐工位 Reset PLC 状态机。
    """
    if _estop_event is not None:
        _estop_event.clear()
    log.info("[E-Stop] 急停状态已重置（上位机侧），需人工逐工位 Reset PLC")

    # 恢复 Scheduler 调度
    if scheduler is not None:
        scheduler.estop_deactivate()

    # 清除 UI 标志
    try:
        from ui.state import get_state
        state = get_state()
        state.estop_active = False
    except Exception:
        pass
