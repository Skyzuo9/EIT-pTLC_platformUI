"""事件总线
==========
功能:
    进程内异步发布/订阅, 供 operation 引擎发出步骤/流程事件, WebSocket 订阅后推送前端.
    迁移目标也将承接 flow_events/log_store 的日志事件 (后续 P5+).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from contextlib import asynccontextmanager
from typing import Callable

log = logging.getLogger(__name__)


def make_event_sink(*sinks: Callable[[dict], None]) -> Callable[[dict], None]:
    """把多个事件接收器合并为一个 event_sink (扇出); 单个接收器抛错不影响其它.

    参数:
        sinks: 若干 (event) -> None 接收器 (如 bus.publish, run_store.on_event)
    返回:
        合并后的 event_sink, 依次投递给每个接收器
    """
    def emit(event: dict) -> None:
        for sink in sinks:
            try:
                sink(event)
            except Exception:  # 一个接收器失败不应阻断其它 (如持久化异常不应中断推流)
                log.exception("[events] 事件接收器异常")
    return emit


# 满载时允许被挤掉的事件类型: 皆为"最新快照即全部语义"的高频状态流, 丢旧无损。
# 运行生命周期事件 (operation_*/vm_state/vm_node_*/vm_human_*/step_* 等) 每条都承载
# 增量语义, 丢任何一条都会让前端事件溯源投影 (步骤树/报警/高亮) 永久失真, 一律不丢。
_DROPPABLE_TYPES = frozenset({
    "telemetry", "robot_pose", "axis_pose", "mechanism_state", "material_state", "vm_vars",
    "signal_light",
    # pump_state: 仿真沙盒专属 (虚拟泵柱塞/阀位快照, busy 期 ~10Hz); 真机泵无位置
    # 回读, 主通道不发 —— 见 three_d/docs/PTLC_REALTIME_PROTOCOL.md 泵反馈节。
    "pump_state",
    # tank_liquid: 同上, 仿真沙盒专属 (展缸液量, 变化超阈值才发)。最新一帧即全部语义,
    # 丢中间帧只是液面少走几格, 不丢语义。
    "tank_liquid",
})


class _SubQueue:
    """单订阅者事件队列: 满载只挤掉可丢类型 (遥测类), 运行事件保序不丢.

    功能:
        替代 asyncio.Queue 的丢最旧策略 —— 无差别丢最旧会把慢消费者 (被节流的
        浏览器标签页) 队列里的运行终态挤掉, 前端步骤树因此永远等不到收口事件。
        运行事件积压超硬上限 (4 x max) 说明消费者已僵死 (半死 TCP 卡在 send 背压),
        此时宁断不丢: 标死清缓冲护内存, get 抛错促使订阅连接关闭, 客户端经
        onclose 重连沿由 reseedLive 从权威存储整树补种, 语义仍无损。
        仅暴露消费端用到的 await get(); 生产与消费都在同一事件循环内, 无需加锁。
    """

    def __init__(self, max_items: int) -> None:
        self._buf: deque = deque()
        self._max = max_items
        self._ready = asyncio.Event()
        self._dead = False   # 积压超硬上限被标死: put 变 no-op, get 抛错

    def put(self, event: dict) -> None:
        """入队一条事件; 满载时从最旧向最新挤掉第一条可丢事件.

        参数:
            event: 事件 dict (须含 type 字段)
        """
        if self._dead:
            return
        if self._max > 0 and len(self._buf) >= self._max:
            # 全是运行事件时允许临时超限: 积压上界为单次运行的事件量, 远小于遥测流量
            for i, old in enumerate(self._buf):
                if old.get("type") in _DROPPABLE_TYPES:
                    del self._buf[i]
                    break
            else:
                # 没挤到可丢事件且积压已达硬上限: 消费者僵死, 断开优于无限积压。
                # 内存上界在 put 侧即时生效, 不依赖消费者再来调 get。
                if len(self._buf) >= self._max * 4:
                    self._dead = True
                    self._buf.clear()
                    self._ready.set()   # 唤醒挂起中的 get, 使其立刻抛错退出
                    return
        self._buf.append(event)
        self._ready.set()

    async def get(self) -> dict:
        """取最旧一条事件; 队列空则挂起等待; 被标死则抛错 (促使订阅方关闭连接)."""
        while True:
            if self._dead:
                raise RuntimeError("事件订阅积压超硬上限已断开, 待客户端重连补种")
            if self._buf:
                return self._buf.popleft()
            self._ready.clear()
            await self._ready.wait()


class EventBus:
    """简单异步事件总线 (每订阅者一个队列)."""

    def __init__(self, max_queue: int = 1000) -> None:
        self._subs: set[_SubQueue] = set()
        self._max = max_queue
        self._taps: list = []

    def add_tap(self, fn) -> None:
        """登记一个同步旁路观察者, 每条发布的事件都会先经过它。

        与 subscribe() 的关键差别: tap 在按订阅者队列丢帧**之前**被调用, 因此它看到
        的是完整事件流, 而不是某个消费者视角下幸存的那一份。状态录像机据此保证录到
        的比任何前端客户端看到的都全。

        另一个必须走 tap 而不是走 VmController 的 event_sink 的理由: 高频连续量
        (axis_pose / robot_pose / mechanism_state / signal_light) 由 realtime_feedback
        与 30004 观察者**直接** bus.publish, 根本不经过 event_sink —— 挂在 sink 上
        只能录到运行事件, 连续量一条也录不到, 且不会报任何错。

        fn 必须轻量且不抛异常语义 (异常在此被隔离): 它跑在发布者线程上。
        """
        if fn not in self._taps:
            self._taps.append(fn)

    def remove_tap(self, fn) -> None:
        if fn in self._taps:
            self._taps.remove(fn)

    def publish(self, event: dict) -> None:
        """向全部订阅者投递事件 (非阻塞; 满载只挤可丢类型, 运行事件不丢)."""
        for tap in self._taps:
            try:
                tap(event)
            except Exception:
                # 旁路观察者故障绝不能影响实时推送
                pass
        for q in list(self._subs):
            try:
                q.put(event)
            except Exception:
                pass

    @asynccontextmanager
    async def subscribe(self):
        """订阅事件; 退出时自动注销. 用法: async with bus.subscribe() as q: await q.get()."""
        q = _SubQueue(self._max)
        self._subs.add(q)
        try:
            yield q
        finally:
            self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
