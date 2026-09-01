"""OPC UA 驱动
=============
功能:
    PLC OPC UA 通信的纯传输层. 提供连接 / 节点缓存 / 读写 / 数组读写 / 心跳 /
    指数退避重连 / 急停边沿检测. 不含工位握手或 L2 动作语义 (那些在 controller 层).
    迁移自 UI-Upper/core/plc_client.py 的传输部分, 节点表由 config.PlcNodeMap 注入,
    替代旧硬编码 NODE_TYPES.

关键约束:
    - 所有写操作经内部 asyncio.Lock 串行执行
    - 心跳每 100ms 读一次节点, 连续失败 3 次进入 RECONNECTING 态
    - RECONNECTING 态: 后台指数退避重连, 读写方法阻塞等待恢复或超时
    - 调用侧先于心跳发现连接已死 (asyncua 断开即时 vs 心跳 3x100ms 判定, 存在竞态窗口) 时,
      立即触发同款重连迁移并在恢复后重试一次, 不向调用方泄漏原始断连异常 (_guarded)
    - 急停: 心跳循环同时读 estop_node, False->True 上升沿触发 on_estop 回调
    - 连接失败日志必须经 _exc_text: asyncua 的超时抛 str() 为空的 TimeoutError, 直接 %s
      会渲染成空白; 并附 _link_hint() 的裸 TCP 探测结论区分"网络不通"与"OPC UA 不应答"

跨命名空间:
    沿 gvl_path 逐级按 BrowseName 文本匹配定位全局变量容器,
    不依赖 namespace index, 实机 (多 ns) 与 mock (单 ns) 通用.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Awaitable, Callable, Optional
from urllib.parse import urlparse

from asyncua import Client, Node, ua

from eit_ptlc.config.models import PlcNodeMap

log = logging.getLogger(__name__)

# 心跳参数
HEARTBEAT_INTERVAL = 0.1   # 100 ms
HEARTBEAT_MAX_FAIL = 3     # 连续失败阈值
# 重连退避序列 (秒), 末项为最大退避
RECONNECT_BACKOFF = [1.0, 2.0, 4.0, 8.0, 30.0]
# 裸 TCP 连通性探测超时 (秒): 仅用于给连接失败归类, 不参与重试判定
LINK_PROBE_TIMEOUT = 1.0
# OPC UA 缺省端口 (url 未显式带端口时用)
_DEFAULT_OPCUA_PORT = 4840

# 配置类型名 -> asyncua VariantType (config 层与 asyncua 解耦的映射点)
_VARIANT_BY_NAME: dict[str, ua.VariantType] = {
    "Boolean": ua.VariantType.Boolean,
    "SByte": ua.VariantType.SByte,
    "Byte": ua.VariantType.Byte,
    "Int16": ua.VariantType.Int16,
    "UInt16": ua.VariantType.UInt16,
    "Int32": ua.VariantType.Int32,
    "UInt32": ua.VariantType.UInt32,
    "Int64": ua.VariantType.Int64,
    "UInt64": ua.VariantType.UInt64,
    "Float": ua.VariantType.Float,
    "Double": ua.VariantType.Double,
    "String": ua.VariantType.String,
}
_INT_VARIANTS = (
    ua.VariantType.SByte, ua.VariantType.Byte,
    ua.VariantType.Int16, ua.VariantType.UInt16,
    ua.VariantType.Int32, ua.VariantType.UInt32,
    ua.VariantType.Int64, ua.VariantType.UInt64,
)
_FLOAT_VARIANTS = (ua.VariantType.Float, ua.VariantType.Double)

# write_block_confirmed 默认浮点回读容差 (REAL float32 往返 + PLC 精度; 单位随节点量纲, mm 级安全)
_DEFAULT_CONFIRM_ATOL = 1e-3


class PLCWriteConfirmError(RuntimeError):
    """写-回读确认失败: 某字段写入后回读值与期望不符 (经多次重写仍不符)."""

    def __init__(self, node: str, detail: str) -> None:
        self.node = node
        self.detail = detail
        super().__init__(f"PLC 写回读确认失败 node={node}: {detail}")


async def _probe_tcp(host: str, port: int, timeout: float) -> Optional[BaseException]:
    """裸 TCP 建连探测.

    参数:
        host/port: 目标; timeout: 建连超时 (秒)
    返回:
        None = 建连成功 (已立即关闭); 否则返回失败异常
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except Exception as exc:
        return exc
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return None


def _exc_text(exc: BaseException) -> str:
    """异常摘要, 保证日志始终带类型名.

    功能:
        直接 %s 打异常时, str() 为空的异常 (asyncio.TimeoutError 等) 会渲染成空白,
        日志只剩 "重连失败 (#48): " 这种无信息量的行。统一经本函数格式化。
    参数:
        exc: 任意异常
    返回:
        "类型名: 消息" 或消息为空时的 "类型名"
    """
    msg = str(exc)
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


class _ReadTiming:
    """批量读耗时台账: 按节点数分档累积样本, 出分位数。

    存在的理由: 判断实时反馈跑不满配置频率, 需要能把"服务端读得慢"与"客户端调度
    写错了"分开。没有本类时两者在 WebSocket 到达间隔上表现完全相同。

    分档而非全局聚合, 是因为一次请求的成本主要是固定往返开销 (实测约 12 ms) 而非
    节点数 (每节点约 0.10 ms) —— 混档统计会把 22 点与 154 点的批次搅在一起, 掩盖
    掉"固定开销才是大头"这个决定优化方向的事实。
    """

    __slots__ = ("_buckets", "_cap")
    # 与实际调用点对齐: 22 = 11 轴 ×2, 154 = 轴 + 51 机构相关点, 250+ = 单点面板全量
    _EDGES = (32, 64, 128, 192, 256, 512)

    def __init__(self, cap: int = 512) -> None:
        self._cap = int(cap)
        self._buckets: dict[str, list[float]] = {}

    @classmethod
    def _label(cls, count: int) -> str:
        low = 0
        for edge in cls._EDGES:
            if count <= edge:
                return f"{low + 1}-{edge}"
            low = edge
        return f"{low + 1}+"

    def record(self, count: int, elapsed_s: float) -> None:
        if count <= 0:
            return
        samples = self._buckets.setdefault(self._label(count), [])
        samples.append(elapsed_s * 1000.0)
        if len(samples) > self._cap:
            # 环形丢最旧: 只关心近况, 且必须是 O(1) 摊还, 不能让计时本身成为负载
            del samples[: len(samples) - self._cap]

    def snapshot(self) -> dict:
        out: dict[str, dict] = {}
        for label, samples in self._buckets.items():
            if not samples:
                continue
            ordered = sorted(samples)
            n = len(ordered)

            def pct(p: float) -> float:
                # 最近邻分位: 样本量小时不做插值, 免得报出从未出现过的耗时
                idx = min(n - 1, max(0, int(round((n - 1) * p))))
                return round(ordered[idx], 3)

            out[label] = {
                "n": n,
                "p50_ms": pct(0.50),
                "p95_ms": pct(0.95),
                "p99_ms": pct(0.99),
                "max_ms": round(ordered[-1], 3),
            }
        return out


class PLCState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


StateChangeCallback = Callable[[PLCState], Awaitable[None]]
EstopCallback = Callable[[], Awaitable[None]]


# ----------------------------------------------------------------------
# 跨命名空间路径定位
# ----------------------------------------------------------------------

def _recover_browse_name(name: str) -> str:
    """还原被按 UTF-8 解码的 GBK BrowseName.

    功能:
        汇川/CODESYS 的 OPC UA 服务器用 PLC 本地代码页 (GBK) 编码含中文的标识符,
        asyncua 按 UTF-8 + surrogateescape 解码, 中文就碎成一串孤立代理字符 ——
        2026-07-28 真机实测 `大真空泵手动` 取回来是
        '\\udcb4\\udcf3\\udcd5\\udce6\\udcbf\\u0571\\udcc3\\udcca\\u05b6\\udcaf'
        (\\udcb4\\udcf3 = 字节 B4 F3 = GBK 的"大"; \\u0571 是 D5 B1 恰好构成合法 UTF-8
        序列的产物)。这里把字节原样取回再按 GBK 解一次。
    参数:
        name: read_browse_name() 拿到的原始名
    返回:
        还原后的名字; 无代理字符 (纯 ASCII 或服务器本就发 UTF-8) 时原样返回
    说明:
        以"含代理字符"为触发条件, 既让 ASCII 名零开销, 也保证真·UTF-8 服务器的
        中文名不会被误当 GBK 重解。
    """
    if not any("\ud800" <= ch <= "\udfff" for ch in name):
        return name
    try:
        raw = name.encode("utf-8", "surrogateescape")
    except Exception:
        return name
    for encoding in ("gbk", "gb18030"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return name


async def browse_children(parent) -> list[tuple[str, Node]]:
    """一次 Browse 取回 parent 的全部直接子节点, 返回 [(原始 BrowseName, 节点)] (保序).

    功能:
        用 get_children_descriptions() 而非 get_children() —— 两者都只发一次 Browse,
        但前者的 ReferenceDescription 自带 BrowseName, 省掉对每个子节点再单发一次
        read_browse_name() 的 N 次往返。Host_Computer 下有 ~130 个变量, 逐个读名
        意味着单次容器解析就要 130+ 次串行往返, 是把 PLC 服务端压到应答超时的主因之一。
    参数:
        parent: 父节点
    返回:
        [(BrowseName.Name, Node)]
    """
    out: list[tuple[str, Node]] = []
    for ref in await parent.get_children_descriptions():
        raw = ref.BrowseName.Name
        if raw is None:
            continue
        out.append((raw, Node(parent.session, ref.NodeId)))
    return out


async def browse_children_map(parent) -> dict[str, Node]:
    """按名索引 parent 的直接子节点 (一次 Browse).

    参数:
        parent: 父节点
    返回:
        {BrowseName: Node}; 原始名与 GBK 还原名都作为 key 落表 (实机中文标识符走还原名,
        mock 的正规 UTF-8 名走原始名, 调用方同一套代码)。同名冲突时先到先得。
    """
    out: dict[str, Node] = {}
    for raw, node in await browse_children(parent):
        out.setdefault(raw, node)
        recovered = _recover_browse_name(raw)
        if recovered != raw:
            out.setdefault(recovered, node)
    return out


async def _find_child_by_name(parent, name: str):
    """在 parent 直接子节点中按 BrowseName.Name 匹配, 命中返回该节点, 未命中抛 KeyError.

    功能:
        不依赖 namespace index, 对实机 (多 ns 分层) 与 mock (单 ns) 通用.
        原始名与 GBK 还原名都接受 —— 实机的中文标识符走还原名, mock 的正规 UTF-8
        名走原始名, 两边同一套代码。
    参数:
        parent: 父节点; name: 目标 BrowseName
    返回:
        匹中的子节点
    """
    children = await browse_children_map(parent)
    try:
        return children[name]
    except KeyError:
        raise KeyError(f"未找到子节点 '{name}'") from None


async def resolve_gvl_node(client: Client, gvl_path: tuple[str, ...]):
    """沿 gvl_path 逐级 BrowseName 文本定位到全局变量容器对象节点.

    参数:
        client: 已连接的 asyncua.Client; gvl_path: 从 Objects 起的路径段
    返回:
        全局变量容器节点 (如 Host_Computer)
    """
    node = client.nodes.objects
    for part in gvl_path:
        node = await _find_child_by_name(node, part)
    return node


# ----------------------------------------------------------------------
# 驱动
# ----------------------------------------------------------------------

class OpcUaDriver:
    """OPC UA PLC 传输驱动.

    使用方式:
        driver = OpcUaDriver(url, node_map, on_state_change=cb, on_estop=cb2)
        await driver.connect()
        await driver.write_variable("collect_Enable", True)
        v = await driver.read_variable("collect_Step")
        await driver.disconnect()

    参数:
        url: OPC UA 服务器地址
        node_map: PLC 节点表 (gvl_path / heartbeat / estop / nodes)
        on_state_change: 状态迁移回调 (异步, 单参数 PLCState)
        on_estop: 急停上升沿回调 (异步, 无参数)
        reconnect_wait_timeout: 读写等待重连恢复的最大秒数, 超时抛 ConnectionError
        request_timeout: 单请求应答超时秒 -> asyncua Client(timeout=)
        watchdog_interval: 链路健康探测周期秒 -> asyncua Client(watchdog_intervall=);
            asyncua 的探测超时 = min(session_timeout/2000, 本值), 实际就等于本值
        max_inflight_requests: 单会话在途请求上限 (心跳不受限), <=0 关限流
    """

    def __init__(
        self,
        url: str,
        node_map: PlcNodeMap,
        on_state_change: Optional[StateChangeCallback] = None,
        on_estop: Optional[EstopCallback] = None,
        reconnect_wait_timeout: float = 60.0,
        subscription_period_ms: int = 100,
        subscription_queue_size: int = 10,
        subscription_sampling_ms: float = 0.0,
        request_timeout: float = 10.0,
        watchdog_interval: float = 5.0,
        max_inflight_requests: int = 6,
    ):
        self._url = url
        # 预解析出裸 host/port, 供 _link_hint 做 TCP 连通性探测 (给连接失败归类)
        _parsed = urlparse(url)
        self._host = _parsed.hostname or ""
        self._port = _parsed.port or _DEFAULT_OPCUA_PORT
        self._node_map = node_map
        self._gvl_path = node_map.gvl_path
        # 节点名 -> VariantType / array_len, 由 node_map 预构建
        self._variant: dict[str, ua.VariantType] = {
            name: _VARIANT_BY_NAME[spec.var_type] for name, spec in node_map.nodes.items()
        }
        self._array_len: dict[str, int] = {
            name: spec.array_len for name, spec in node_map.nodes.items() if spec.array_len > 0
        }

        self._client: Optional[Client] = None
        self._lock = asyncio.Lock()
        # asyncua Client 构造参数: 见类 docstring "关键约束" 与 config.PLCCfg 注释,
        # 绝不能吃库默认值 (timeout=4 / watchdog_intervall=1.0)。
        self._request_timeout = float(request_timeout)
        self._watchdog_interval = float(watchdog_interval)
        # 在途请求限流。取序不变量: 先 _io_sem 后 _lock —— sem 在 _guarded 里取, _lock 在
        # op() 内取, 单向, 不构成死锁 (持锁者必然已持有一个 sem 名额)。
        self._max_inflight = int(max_inflight_requests)
        self._io_sem: Optional[asyncio.Semaphore] = (
            asyncio.Semaphore(self._max_inflight) if self._max_inflight > 0 else None
        )
        self._state = PLCState.DISCONNECTED
        # 批量读耗时台账。此前对 OPC 读取**没有任何计时**, "一轮要多久"只能从
        # WebSocket 到达间隔反解, 于是"读得慢"与"调度写错了"两种病因无法区分。
        # 按节点数分档累积, 供 read_timing_stats() 出 p50/p95/p99。
        self._read_timing = _ReadTiming()
        self._hb_fail_count = 0
        self._hb_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        # 急停派发是 fire-and-forget 协程: 存引用防被 GC, 并挂完成回调冒泡异常 (否则静默丢失)。
        self._estop_tasks: set[asyncio.Task] = set()

        # 节点缓存 (连接后填充): 已知节点 + 动态发现节点
        self._nodes: dict[str, object] = {}
        self._dynamic_nodes: dict[str, object] = {}
        self._dynamic_types: dict[str, ua.VariantType] = {}
        # 扩展容器节点缓存 (单点控制读写 cyinder_date / servoaxisdate / GVL / IO 等
        # Host_Computer 之外的容器): key = 从 Objects 起的完整 BrowseName 路径。
        # 在 _cache_nodes 里清空 —— 该方法连接与重连都会走, 保证复连后重新解析。
        self._ext_nodes: dict[tuple[str, ...], object] = {}
        # 容器路径 -> {子节点名: 节点}: 同容器下解析第二个变量起免去重复 browse。
        # 不做这层缓存的话, 单点面板首次拉 250 个点会退化成 O(n²) 次 get_children,
        # 实测慢到能拖垮会话心跳。与 _ext_nodes 同批清空。
        self._ext_children: dict[tuple[str, ...], dict[str, object]] = {}
        # 负缓存: PLC 端确实没有的变量名 -> 首次判定原因。没有它的话, 每次读一个未下装的
        # 符号 (如节点表里标 optional 的 Sampling_5Z_ActPos) 都要重走一遍 _resolve_node ——
        # 逐级 browse 容器 + 在 Host_Computer 全部子节点里扫一遍且必然扫不到。遥测 1Hz 调它,
        # 就是每秒一轮几百次串行往返的自伤负载, 足以把服务端压到应答超时触发误判断连。
        # 与 _nodes 同批在 _cache_nodes 里清空并重建 -> PLC 一旦下装该符号, 任意一次重连即自愈。
        self._missing_nodes: dict[str, str] = {}

        # 回调 (支持多订阅)
        self._state_listeners: list[StateChangeCallback] = []
        if on_state_change is not None:
            self._state_listeners.append(on_state_change)
        self._on_estop = on_estop
        self._reconnect_wait_timeout = reconnect_wait_timeout

        self._connected_evt = asyncio.Event()
        self._prev_estop = False
        self._reconnect_count = 0
        # 每次进入 RECONNECTING 只播报一次"阻塞等待": 遥测 1Hz 并发读 8 个工位,
        # 否则每轮固定刷 8 行 WARNING 把真正的失败原因淹掉
        self._reconnect_notice_logged = False

        # ── 订阅 / 内存镜像 (事件驱动取代忙轮询) ──
        # _mirror: 已订阅节点名 -> 最新值 (由 datachange_notification 维护, 供 cached* 本地读)
        # _change_count + _change_waiters: 任意订阅变化的唤醒机制 (单调计数避免丢唤醒)
        self._sub_period_ms = int(subscription_period_ms)
        # 每监控项队列深度: 一个发布周期内变量若变化多次, 队列满(默认服务器=1, discard-oldest)会丢中间值。
        # 放深队列在"并行多工位/客户端排空慢/字段快跳变"时降低溢出丢弃概率 (report-on-change 丢一条 delta
        # 就不自愈, 见 plc_controller 软复核)。非确定性缓解, 与软复核直读对账互补, 不替代它。
        self._sub_queue_size = int(subscription_queue_size)
        # 采样间隔(ms): 0 = 请求服务器最快(跟随发布/PLC), 兜底捕获单扫描内塌缩的快跳变。
        self._sub_sampling_ms = float(subscription_sampling_ms)
        self._subscription = None
        self._sub_names: set[str] = set()
        self._sub_name_by_nodeid: dict[object, str] = {}
        self._mirror: dict[str, object] = {}
        self._change_count = 0
        self._change_waiters: list[asyncio.Future] = []

    def _spawn_estop(self) -> None:
        """派发急停回调为后台任务, 存引用防 GC, 完成后从集合移除并冒泡异常."""
        task = asyncio.create_task(self._on_estop())
        self._estop_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._estop_tasks.discard(t)
            if not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    log.error("[PLC] on_estop 回调异常: %s", exc, exc_info=exc)

        task.add_done_callback(_done)

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _new_client(self) -> Client:
        """构造 asyncua Client, 显式给全超时参数 (首连与重连共用, 参数必须一致).

        说明:
            auto_reconnect 显式给 False: 重连由本驱动的 _reconnect_loop 负责 (它还要重建
            节点缓存与订阅, asyncua 那套不认识这些), 两套重连并存会互踩。但要清楚 asyncua
            2.x 即使 auto_reconnect=False 也照样起连接监管任务, 只是探到失效后不重连、直接
            把状态标死并退出 —— 所以 watchdog_interval 决定的是"多慢算断", 必须给够。
        """
        return Client(
            self._url,
            timeout=self._request_timeout,
            watchdog_intervall=self._watchdog_interval,
            auto_reconnect=False,
        )

    async def connect(self) -> None:
        """连接 OPC UA 服务器, 缓存节点并启动心跳.

        首次连接失败时先做一次 TCP 探测再抛, 让"开机就连不上"直接给出排查方向,
        而不是抛一个 str() 为空的 TimeoutError。
        """
        self._client = self._new_client()
        try:
            await self._client.connect()
        except Exception as exc:
            log.error("[PLC] 首次连接失败 %s: %s — %s",
                      self._url, _exc_text(exc), await self._link_hint())
            self._client = None
            raise
        log.info("[PLC] 已连接: %s", self._url)
        await self._cache_nodes()
        await self._resubscribe_all()  # 复连/复用驱动时恢复订阅 (首次连接 _sub_names 空, no-op)
        await self._set_state(PLCState.CONNECTED)
        self._hb_fail_count = 0
        self._prev_estop = False
        self._connected_evt.set()
        self._hb_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """断开连接并停止心跳/重连任务."""
        for task in (self._hb_task, self._reconnect_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._hb_task = None
        self._reconnect_task = None
        for task in list(self._estop_tasks):
            if not task.done():
                task.cancel()
        self._estop_tasks.clear()
        if self._subscription is not None:
            try:
                await self._subscription.delete()
            except Exception:
                pass
            self._subscription = None
        # 与 _reconnect_loop 同一条纪律: 先摘缓存节点再 disconnect, 免得并发协程拿着
        # 绑定旧 session 的 Node 继续往正在拆的会话上发请求 (见 _reconnect_loop docstring)
        old, self._client = self._client, None
        self._nodes.clear()
        self._dynamic_nodes.clear()
        self._dynamic_types.clear()
        self._ext_nodes.clear()
        self._ext_children.clear()
        self._missing_nodes.clear()
        if old is not None:
            try:
                await old.disconnect()
            except Exception as exc:
                log.warning("[PLC] 断开时异常 (忽略): %s", _exc_text(exc))
        self._connected_evt.clear()
        await self._set_state(PLCState.DISCONNECTED)
        log.info("[PLC] 已断开")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.disconnect()

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    @property
    def state(self) -> PLCState:
        return self._state

    @property
    def is_ok(self) -> bool:
        return self._state == PLCState.CONNECTED

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def client_session(self) -> Optional[Client]:
        """底层 asyncua.Client (供订阅等外部使用)."""
        return self._client

    def add_state_listener(self, cb: StateChangeCallback) -> None:
        """注册状态变更监听 (支持多订阅)."""
        self._state_listeners.append(cb)

    async def _set_state(self, state: PLCState) -> None:
        if state == self._state:
            return
        old = self._state
        self._state = state
        # 换态即重置播报闸: 下一次断连仍会 WARNING 一次 (只压同一次断连内的重复)
        self._reconnect_notice_logged = False
        log.info("[PLC] 状态迁移: %s -> %s", old.value, state.value)
        for cb in list(self._state_listeners):
            try:
                await cb(state)
            except Exception as exc:
                log.warning("[PLC] 状态监听回调异常: %s", _exc_text(exc))

    async def _link_hint(self) -> str:
        """裸 TCP 探测, 把连接失败归类成可执行的排查方向 (给日志补一句人话).

        功能:
            asyncua 的 connect() 超时抛空消息 TimeoutError, 单看日志分不清是"网络不通"
            还是"通了但 OPC UA 不应答"。本探测只做结论分类, 不参与重试判定。
        约束:
            只报"裸 TCP 这一层是否走得通", 不臆断更多。本机若开着 TUN/代理 (如 Mihomo),
            关闭的端口会表现为超时而非拒绝 (实测连回环也如此), 故超时分支不能断言
            "主机不存在", 只能给排查方向。
        返回:
            人类可读的排查方向
        """
        target = f"TCP {self._host}:{self._port}"
        err = await _probe_tcp(self._host, self._port, LINK_PROBE_TIMEOUT)
        if err is None:
            return (f"{target} 可建连, 但 OPC UA 握手没走完 "
                    f"(查 PLC 是否 STOP / OPC UA 服务未启 / 连接数耗尽)")
        if isinstance(err, ConnectionRefusedError):
            return f"{target} 拒绝连接 (主机在线, 但该端口没在监听: 查 OPC UA 服务是否启动)"
        return (f"{target} 裸 TCP 也连不上 ({_exc_text(err)}) — 查网线/网口链路/PLC 电源/IP 配置 "
                f"(本机若开着 TUN/代理, 端口关闭也会表现为超时而非拒绝)")

    async def _await_connected(self) -> None:
        """阻塞等待 CONNECTED; ERROR/DISCONNECTED 立即抛, RECONNECTING 等事件或超时."""
        if self._state == PLCState.CONNECTED:
            return
        if self._state == PLCState.ERROR:
            raise ConnectionError("PLC 处于 ERROR 态, 无法继续")
        if self._state == PLCState.DISCONNECTED:
            raise ConnectionError("PLC 未连接")
        # 同一次断连内只 WARNING 一次: 遥测 1Hz gather 并发 8 工位, 否则每轮刷 8 行
        if self._reconnect_notice_logged:
            log.debug("[PLC] 当前 RECONNECTING, 阻塞等待恢复 (最多 %.1fs)", self._reconnect_wait_timeout)
        else:
            self._reconnect_notice_logged = True
            log.warning("[PLC] 当前 RECONNECTING, 阻塞等待恢复 (最多 %.1fs)", self._reconnect_wait_timeout)
        try:
            await asyncio.wait_for(self._connected_evt.wait(), timeout=self._reconnect_wait_timeout)
        except asyncio.TimeoutError as exc:
            raise ConnectionError(f"等待 PLC 重连超时 ({self._reconnect_wait_timeout}s)") from exc

    async def _note_link_lost(self, exc: Exception) -> None:
        """公开调用先于心跳发现连接已死时, 立即触发与心跳同款的重连迁移 (幂等).

        仅 CONNECTED 态动作; 已在 RECONNECTING/其它态则直接返回。必须先取消心跳任务再迁移:
        否则心跳随后也累计满 3 次失败并二次 create_task(_reconnect_loop), 产生两个重连循环
        互踩 (双 client)。状态检查到赋值之间无 await (_set_state 首个挂起点前已完成赋值),
        并发调用同踩窗口时只有一个能进入迁移分支。
        """
        if self._state != PLCState.CONNECTED:
            return
        log.warning("[PLC] 调用侧先于心跳发现连接断开: %s, 立即进入 RECONNECTING", _exc_text(exc))
        if self._hb_task is not None and not self._hb_task.done():
            self._hb_task.cancel()
        self._hb_task = None
        self._connected_evt.clear()
        await self._set_state(PLCState.RECONNECTING)
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _guarded(self, op):
        """连接守卫执行: 等待 CONNECTED -> 限流 -> 执行 op -> 断连异常则触发重连并重试一次.

        参数:
            op: 无参协程工厂 (含取锁的完整操作体); 锁随异常传播已释放, 重试自然重新取锁
        返回:
            op 的返回值
        说明:
            _await_connected 在 try 外, 其自身抛出的 ConnectionError (PLC 未连接 / 等待重连
            超时) 不参与重试; 只对 op 内泄漏的断连异常 (asyncua 在心跳判定窗口内的
            "client is disconnected" 等) 触发 _note_link_lost 并重试。重试的写操作均为
            绝对值写 (幂等), 读-改-写在重试时会重新读取, 均安全。

            限流取序不变量: **先 _io_sem 后 _lock**。sem 在这里取、_lock 在 op() 内取,
            方向单一 —— 任何持 _lock 的协程必然已经拿到 sem 名额, 所以名额耗尽时不会出现
            "都在等锁, 而锁的主人在等名额"。改动此处务必维持这个顺序。
            心跳走 _read()/直接 node.read_value(), 不经本方法 —— 故意不限流, 不让心跳被
            业务读饿死后误判 3 连失败。
        """
        for attempt in (1, 2):
            await self._await_connected()
            try:
                if self._io_sem is None:
                    return await op()
                async with self._io_sem:
                    return await op()
            except ConnectionError as exc:
                if attempt == 2:
                    raise
                await self._note_link_lost(exc)

    # ------------------------------------------------------------------
    # 节点缓存与类型
    # ------------------------------------------------------------------

    async def _cache_nodes(self) -> None:
        """连接后 browse 全局变量容器下所有变量并分流缓存.

        功能:
            命中节点表 -> self._nodes (带类型写入); 表外变量 -> 动态缓存 (调试可见);
            表中声明但 PLC 缺失 -> 仅记日志, 不视为连接失败.
            缺失再分两档: 标了 optional 的是已知待建/仅 Mock 用, 走 INFO; 其余是真漂移
            (多半有人在 PLC 侧改名/删变量), 走 WARNING —— 别让已知项把这行告警刷废.
            两档都会落进 _missing_nodes 负缓存, 使后续读取零往返直接抛 KeyError。
        """
        # 复连后 NodeId 可能已失效, **所有**节点缓存必须整体重建而不是覆盖式更新:
        # asyncua 的 Node 对象硬引用创建它的 session, 旧连接上的 Node 即使 self._client 已换
        # 也照样往那条死会话上发请求。只覆盖命中项的话, 重连后没被重新 browse 到的名字会永久
        # 留着一个绑死旧 session 的 Node, 之后每次读都必失败且不可自愈。
        self._nodes.clear()
        self._dynamic_nodes.clear()
        self._dynamic_types.clear()
        self._ext_nodes.clear()
        self._ext_children.clear()
        self._missing_nodes.clear()
        gvl = await resolve_gvl_node(self._client, self._gvl_path)
        plc_vars: dict[str, object] = {}
        plc_types: dict[str, ua.VariantType] = {}
        for name, child in await browse_children(gvl):
            plc_vars[name] = child
            try:
                plc_types[name] = await child.read_data_type_as_variant_type()
            except Exception as exc:
                log.debug("[PLC] 读子节点类型失败 (跳过): %s", _exc_text(exc))

        missing: list[str] = []       # 意外缺失: 节点表与真机漂移了
        absent_ok: list[str] = []     # 声明为 optional 的已知缺失
        for name, spec in self._node_map.nodes.items():
            if name in plc_vars:
                self._nodes[name] = plc_vars[name]
            elif spec.optional:
                absent_ok.append(name)
                self._missing_nodes[name] = (
                    f"PLC 节点 '{name}' 未下装 (节点表标 optional, 已知待建/仅 Mock 用)")
            else:
                missing.append(name)
                self._missing_nodes[name] = (
                    f"PLC 节点 '{name}' 未找到 (节点表与真机漂移: PLC 侧改名/删变量?)")
        for name, node in plc_vars.items():
            if name in self._node_map.nodes:
                continue
            self._dynamic_nodes[name] = node
            if name in plc_types:
                self._dynamic_types[name] = plc_types[name]

        log.info("[PLC] 节点缓存完成: 共 %d 变量 (命中 %d, 动态 %d)",
                 len(plc_vars), len(self._nodes), len(self._dynamic_nodes))
        if absent_ok:
            log.info("[PLC] 节点表中标 optional 且 PLC 端暂无的变量: %s (已知待建/仅 Mock, 不影响运行)",
                     ", ".join(absent_ok))
        if missing:
            log.warning("[PLC] 节点表声明但 PLC 端未发现的变量: %s (调用相关业务时会报错)", ", ".join(missing))

    def _coerce(self, value, vtype: ua.VariantType):
        """按 VariantType 强转 value, 避免 asyncua 严格类型报错."""
        if vtype in (ua.VariantType.Float, ua.VariantType.Double):
            return float(value)
        if vtype in _INT_VARIANTS:
            return int(value)
        if vtype == ua.VariantType.Boolean:
            return bool(value)
        if vtype == ua.VariantType.String:
            return str(value)
        return value

    def variant_of(self, name: str) -> ua.VariantType:
        """返回变量的 VariantType (节点表优先, 其次动态类型, 默认 String)."""
        if name in self._variant:
            return self._variant[name]
        return self._dynamic_types.get(name, ua.VariantType.String)

    # ------------------------------------------------------------------
    # 标量读写
    # ------------------------------------------------------------------

    async def _read(self, name: str):
        """读已缓存节点 (无连接等待, 供心跳/快照内部用)."""
        return await self._nodes[name].read_value()

    async def _write(self, name: str, value) -> None:
        """写已缓存节点 (带类型包装与错误日志, 调用方持锁)."""
        node = self._nodes[name]
        vtype = self._variant[name]
        try:
            await node.write_value(ua.DataValue(ua.Variant(self._coerce(value, vtype), vtype)))
        except ua.UaStatusCodeError as exc:
            value_len = len(value) if isinstance(value, (str, bytes, list, tuple)) else None
            log.error("[PLC] _write 失败 node=%s vtype=%s value_len=%s status=0x%08X (%s)",
                      name, vtype.name, value_len, getattr(exc, "code", 0) & 0xFFFFFFFF, exc.__class__.__name__)
            raise

    async def read_variable(self, name: str):
        """读取任意变量 (已缓存 / 动态缓存 / 动态解析回退).

        参数:
            name: 变量名 (须与 PLC OPC UA 节点名一致)
        返回:
            变量当前值
        """
        # 负缓存判定放在 _guarded 之外: 已知 PLC 端没有的符号不该去排队等重连,
        # 否则遥测轮询在 RECONNECTING 期间会为一个必然失败的读白等 reconnect_wait_timeout。
        self._check_missing(name)

        async def _op():
            if name in self._nodes:
                return await self._read(name)
            if name in self._dynamic_nodes:
                return await self._dynamic_nodes[name].read_value()
            node = await self._resolve_node(name)
            self._dynamic_nodes[name] = node
            return await node.read_value()

        return await self._guarded(_op)

    async def read_many(self, names: list[str]) -> list:
        """批量读 Host_Computer 变量, 一次 OPC UA 请求返回全部值.

        参数:
            names: 变量名列表 (可含负缓存命中的已知缺失名)
        返回:
            与 names 等长的值列表; 已知缺失 / 单点解析失败 / 单点读失败置 None, 不影响其余点
        说明:
            遥测每个工位要读 8 个 L2 字段 + 若干诊断镜像, 逐点 read_variable 就是每工位十余次
            串行往返 × 8 工位并发 —— 这些往返本身正是把服务端压到应答超时、进而触发误判断连的
            负载。合成一次 read_values 后单工位一轮只剩 1 次请求。
            断连语义与逐点读保持一致: ConnectionError 照常向上抛 (交 _guarded 触发重连并重试),
            不会被降级成一批 None —— 否则调用方会把"链路断了"误读成"PLC 字段全空"。
        """
        if not names:
            return []

        async def _op():
            if self._client is None:
                raise ConnectionError("PLC 未连接")
            nodes: list[object] = []
            index_of: list[int] = []
            out: list = [None] * len(names)
            for i, name in enumerate(names):
                if name in self._missing_nodes:
                    continue
                node = self._nodes.get(name) or self._dynamic_nodes.get(name)
                if node is None:
                    try:
                        node = await self._resolve_node(name)
                    except KeyError as exc:
                        log.debug("[PLC] read_many 跳过未解析节点 %s: %s", name, _exc_text(exc))
                        continue
                    self._dynamic_nodes[name] = node
                nodes.append(node)
                index_of.append(i)
            if not nodes:
                return out
            try:
                started = time.perf_counter()
                values = await self._client.read_values(nodes)
                self._read_timing.record(len(nodes), time.perf_counter() - started)
            except ua.UaStatusCodeError as exc:
                # 整批失败 (常见于某个 NodeId 已失效) 时降级逐点读, 保住其余点的回显
                log.warning("[PLC] read_many 批量读失败, 降级逐点: %s", _exc_text(exc))
                values = []
                for node in nodes:
                    try:
                        values.append(await node.read_value())
                    except ConnectionError:
                        raise
                    except Exception:
                        values.append(None)
            for slot, value in zip(index_of, values):
                out[slot] = value
            return out

        return await self._guarded(_op)

    async def read_named(self, names: list[str]) -> dict:
        """read_many 的具名版: 返回 {变量名: 值}, 缺失/失败为 None."""
        values = await self.read_many(names)
        return dict(zip(names, values))

    async def write_variable(self, name: str, value) -> None:
        """写入任意标量变量 (与读写共用一把锁, 支持动态解析回退).

        参数:
            name: 变量名; value: 写入值 (按节点表类型强转)
        """
        self._check_missing(name)   # 同 read_variable: 已知缺失不排队等重连

        async def _op():
            async with self._lock:
                if name in self._nodes:
                    await self._write(name, value)
                    return
                if name not in self._dynamic_nodes:
                    self._dynamic_nodes[name] = await self._resolve_node(name)
                node = self._dynamic_nodes[name]
                vtype = self.variant_of(name)
                await node.write_value(ua.DataValue(ua.Variant(self._coerce(value, vtype), vtype)))

        await self._guarded(_op)

    async def write_many(self, params: dict) -> None:
        """批量写入变量 (标量带类型强转, 数组整体写). 自身占锁与其它写串行.

        功能:
            key 为 PLC 变量名, value 为值; 数组节点 (array_len>0) 且 value 为 list 时整体写.
            未知变量记 WARNING 并跳过.
        参数:
            params: {变量名: 值}
        """
        if not params:
            return

        async def _op():
            async with self._lock:
                for name, value in params.items():
                    if name in self._array_len and isinstance(value, (list, tuple)):
                        await self._write_array_locked(name, list(value))
                        continue
                    if name in self._nodes:
                        await self._write(name, value)
                    elif name in self._dynamic_nodes:
                        node = self._dynamic_nodes[name]
                        vtype = self.variant_of(name)
                        await node.write_value(ua.DataValue(ua.Variant(self._coerce(value, vtype), vtype)))
                    else:
                        log.warning("[PLC] 未知参数变量: %s (不在节点表与动态缓存, 已忽略)", name)

        await self._guarded(_op)
        log_view = {
            k: f"<list len={len(v)}>" if isinstance(v, (list, tuple)) and len(v) > 8 else v
            for k, v in params.items()
        }
        log.info("[PLC] 批量参数已写入: %s", log_view)

    # ------------------------------------------------------------------
    # 数组读写
    # ------------------------------------------------------------------

    async def read_array(self, name: str) -> list:
        """整体读取数组节点, 返回 list (连接守卫由 read_variable 承担, 避免嵌套重试)."""
        return list(await self.read_variable(name))

    async def read_array_element(self, name: str, index: int):
        """读取数组节点第 index 个元素 (1-based, 与 PLC ARRAY[1..n] 一致)."""
        values = await self.read_array(name)
        return values[index - 1]

    async def write_array(self, name: str, values: list) -> None:
        """整体写入数组节点 (补齐/截断到声明维度). 自身占锁."""
        async def _op():
            async with self._lock:
                await self._write_array_locked(name, values)

        await self._guarded(_op)

    async def write_array_element(self, name: str, index: int, value) -> None:
        """写入数组节点第 index 个元素 (1-based, 读-改-写, 仅改目标索引; 重试时重新读取)."""
        async def _op():
            async with self._lock:
                arr = list(await self._read(name))
                vtype = self._variant[name]
                arr[index - 1] = self._coerce(value, vtype)
                await self._nodes[name].write_value(ua.DataValue(ua.Variant(arr, vtype)))

        await self._guarded(_op)

    async def _write_array_locked(self, name: str, values: list) -> None:
        """数组整体写入实现 (调用方已持锁); 长度不足补默认值, 超出截断."""
        array_len = self._array_len.get(name)
        if array_len is None:
            raise KeyError(f"未知数组变量: {name} (array_len 未声明)")
        if name in self._nodes:
            node = self._nodes[name]
        else:
            if name not in self._dynamic_nodes:
                self._dynamic_nodes[name] = await self._resolve_node(name)
            node = self._dynamic_nodes[name]
        vtype = self.variant_of(name)
        if vtype == ua.VariantType.String:
            pad = ""
        elif vtype == ua.VariantType.Boolean:
            pad = False
        elif vtype in _INT_VARIANTS:
            pad = 0
        else:
            pad = 0.0
        normalized = [self._coerce(v, vtype) for v in values[:array_len]]
        normalized += [pad] * max(0, array_len - len(normalized))
        try:
            await node.write_value(ua.DataValue(ua.Variant(normalized, vtype)))
        except ua.UaStatusCodeError as exc:
            log.error("[PLC] _write_array 失败 node=%s vtype=%s len=%d status=0x%08X (%s)",
                      name, vtype.name, len(normalized), getattr(exc, "code", 0) & 0xFFFFFFFF, exc.__class__.__name__)
            raise

    # ------------------------------------------------------------------
    # 写-回读确认 (plc_write 原语: 块/标量混合, 锁内写后逐字段回读比对)
    # ------------------------------------------------------------------

    async def _read_locked(self, name: str):
        """锁内读取节点当前值 (标量或数组). 调用方已持锁, 不再加锁/等待连接.

        与 read_variable 区别: 本方法不获取 self._lock (避免与持锁的写阻塞自死锁),
        供 write_block_confirmed 在同一锁事务内回读。
        """
        if name in self._nodes:
            return await self._nodes[name].read_value()
        if name not in self._dynamic_nodes:
            self._dynamic_nodes[name] = await self._resolve_node(name)
        return await self._dynamic_nodes[name].read_value()

    async def _write_field_locked(self, name: str, value) -> None:
        """锁内写单字段 (数组整体 / 标量, 含动态解析回退). 调用方已持锁."""
        if name in self._array_len and isinstance(value, (list, tuple)):
            await self._write_array_locked(name, list(value))
            return
        if name in self._nodes:
            await self._write(name, value)
            return
        if name not in self._dynamic_nodes:
            self._dynamic_nodes[name] = await self._resolve_node(name)
        node = self._dynamic_nodes[name]
        vtype = self.variant_of(name)
        await node.write_value(ua.DataValue(ua.Variant(self._coerce(value, vtype), vtype)))

    def _expected_value(self, name: str, value):
        """计算字段写入后应回读到的归一值 (数组按 array_len 补齐/截断 + 强转; 标量强转).

        回读必须与此归一值比对, 而非原始入参 —— 因 _write_array_locked 会按 array_len
        补齐/截断并逐元素强转, 写入值通常 != 原始入参。
        """
        vtype = self.variant_of(name)
        if name in self._array_len and isinstance(value, (list, tuple)):
            array_len = self._array_len[name]
            pad = self._pad_value(vtype)
            norm = [self._coerce(v, vtype) for v in list(value)[:array_len]]
            norm += [pad] * max(0, array_len - len(norm))
            return norm
        return self._coerce(value, vtype)

    @staticmethod
    def _pad_value(vtype: ua.VariantType):
        if vtype == ua.VariantType.String:
            return ""
        if vtype == ua.VariantType.Boolean:
            return False
        if vtype in _INT_VARIANTS:
            return 0
        return 0.0

    @staticmethod
    def _scalar_matches(vtype: ua.VariantType, expected, got, atol: float) -> bool:
        """单值比对: 浮点用 atol, 整型/布尔/字符串精确."""
        if vtype in _FLOAT_VARIANTS:
            return abs(float(got) - float(expected)) <= atol
        if vtype in _INT_VARIANTS:
            return int(got) == int(expected)
        if vtype == ua.VariantType.Boolean:
            return bool(got) == bool(expected)
        return str(got) == str(expected)

    def _compare_field(self, name: str, expected, got, atol: float) -> Optional[str]:
        """比对回读值与期望值; 一致返回 None, 否则返回首个不符的描述串."""
        vtype = self.variant_of(name)
        if isinstance(expected, list):
            got_list = list(got) if isinstance(got, (list, tuple)) else None
            if got_list is None:
                return f"期望数组, 回读非数组 ({type(got).__name__})"
            if len(got_list) != len(expected):
                return f"数组长度不符: 期望 {len(expected)}, 回读 {len(got_list)}"
            for i, (e, g) in enumerate(zip(expected, got_list)):
                if not self._scalar_matches(vtype, e, g, atol):
                    return f"elem[{i + 1}] 不符: 期望 {e}, 回读 {g}"
            return None
        if not self._scalar_matches(vtype, expected, got, atol):
            return f"标量不符: 期望 {expected}, 回读 {got}"
        return None

    async def write_block_confirmed(
        self,
        fields: dict,
        *,
        atol: float = _DEFAULT_CONFIRM_ATOL,
        attempts: int = 2,
    ) -> dict:
        """写一组字段 (数组+标量混合) 并逐字段回读确认; 整事务占同一把写锁.

        plc_write 原语后端: 单写者契约下, 写后立即回读保证 _Target 在被 L2 消费前已确认。
        对每字段最多重写 attempts 次 (同值幂等); 仍不符抛 PLCWriteConfirmError。

        参数:
            fields:   {PLC 变量名: 值}; 数组节点值为 list, 标量为标量
            atol:     浮点回读容差 (绝对); 整型/布尔/字符串精确比对, 不受 atol 影响
            attempts: 单字段最大写入次数 (含首次)
        返回:
            {变量名: {"ok": True, "attempts": n}} 报告
        异常:
            PLCWriteConfirmError: 某字段经 attempts 次仍回读不符
        """
        atol_v = float(atol)

        async def _op():
            report: dict = {}
            async with self._lock:
                for name, value in fields.items():
                    expected = self._expected_value(name, value)
                    last_detail = ""
                    for attempt in range(1, attempts + 1):
                        await self._write_field_locked(name, value)
                        got = await self._read_locked(name)
                        last_detail = self._compare_field(name, expected, got, atol_v) or ""
                        if not last_detail:
                            report[name] = {"ok": True, "attempts": attempt}
                            break
                        log.warning("[PLC] 回读不符 (第 %d/%d 次) node=%s: %s",
                                    attempt, attempts, name, last_detail)
                    else:
                        raise PLCWriteConfirmError(name, last_detail)
            return report

        report = await self._guarded(_op)
        log.info("[PLC] 块写回读确认通过: %s", list(fields))
        return report

    # ------------------------------------------------------------------
    # 结构体成员数组读写 (第二 GVL 容器, 如 HMI 伺服 T_HMI_Servo.position[1..10])
    # ------------------------------------------------------------------

    async def _resolve_struct_member(self, gvl_path, struct_name: str, member: str):
        """定位 第二容器/struct/member 节点 (按需 browse, 复用跨命名空间 BrowseName 匹配, 不缓存)。

        假设 PLC 把 struct (如 T_HMI_Servo) 暴露为 Object 节点, 其成员 (position/write/execute)
        为可独立读写的子变量数组。若实机将整个 struct 暴露为单个 ExtensionObject 变量, 需改为
        读整 struct 再取成员 (真机核对; 见 points.yaml 注释)。
        """
        if self._client is None:
            raise ConnectionError("PLC 未连接")
        container = await resolve_gvl_node(self._client, tuple(gvl_path))
        struct = await _find_child_by_name(container, struct_name)
        return await _find_child_by_name(struct, member)

    async def read_struct_array_member(self, gvl_path, struct_name: str, member: str, index: int):
        """读 struct.member 数组第 index 元素 (1-based, 与 PLC ARRAY[1..n] 一致)。"""
        async def _op():
            node = await self._resolve_struct_member(gvl_path, struct_name, member)
            arr = list(await node.read_value())
            if not 1 <= index <= len(arr):
                raise IndexError(f"{struct_name}.{member} 索引 {index} 越界 (1..{len(arr)})")
            return arr[index - 1]

        return await self._guarded(_op)

    async def write_struct_array_member(self, gvl_path, struct_name: str, member: str,
                                        index: int, value: float) -> None:
        """写 struct.member 数组第 index 元素 (1-based, 读-改-写整数组, LREAL/Double)。占写锁与其它写串行。"""
        async def _op():
            async with self._lock:
                node = await self._resolve_struct_member(gvl_path, struct_name, member)
                arr = list(await node.read_value())
                if not 1 <= index <= len(arr):
                    raise IndexError(f"{struct_name}.{member} 索引 {index} 越界 (1..{len(arr)})")
                arr[index - 1] = float(value)
                await node.write_value(ua.DataValue(ua.Variant(arr, ua.VariantType.Double)))

        await self._guarded(_op)

    # ------------------------------------------------------------------
    # 扩展容器任意路径读写 (Host_Computer 之外: cyinder_date / servoaxisdate / GVL / IO / 程序实例)
    #
    # 与上面的 read/write_variable 的分工: 那些走 plc_nodes.yaml 节点表, 只覆盖
    # Host_Computer 一个容器; 单点控制要碰的是同级兄弟容器与结构体成员, 路径由
    # manual_points.yaml 给出, 故这里按完整路径寻址并缓存节点。
    # ------------------------------------------------------------------

    async def resolve_ext_node(self, path: tuple[str, ...]):
        """按从 Objects 起的完整 BrowseName 路径定位节点, 结果缓存.

        参数:
            path: 如 (DeviceSet, ..., Application, GlobalVars, cyinder_date, 展缸1气缸1手动)
        返回:
            节点对象
        说明:
            未命中抛 KeyError (来自 _find_child_by_name), 调用方据此可探测容器候选前缀。
        """
        key = tuple(path)
        cached = self._ext_nodes.get(key)
        if cached is not None:
            return cached
        if self._client is None:
            raise ConnectionError("PLC 未连接")
        node = self._client.nodes.objects
        for depth, part in enumerate(key):
            parent_key = key[:depth]
            children = self._ext_children.get(parent_key)
            if children is None:
                children = {}
                for child in await node.get_children():
                    try:
                        raw = (await child.read_browse_name()).Name
                    except Exception:
                        continue
                    # 原始名与 GBK 还原名都登记: 实机中文标识符按还原名查, mock 的
                    # 正规 UTF-8 名按原始名查 (见 _recover_browse_name)
                    children[raw] = child
                    children[_recover_browse_name(raw)] = child
                self._ext_children[parent_key] = children
            node = children.get(part)
            if node is None:
                raise KeyError(f"未找到子节点 '{part}' (父路径 {'/'.join(parent_key) or 'Objects'})")
            self._ext_nodes[key[:depth + 1]] = node
        return node

    async def read_ext(self, path: tuple[str, ...]):
        """读扩展容器下任意节点 (不占写锁, 与 read_variable 同策略)."""
        async def _op():
            node = await self.resolve_ext_node(path)
            return await node.read_value()

        return await self._guarded(_op)

    async def write_ext(self, path: tuple[str, ...], value, var_type: str = "Boolean") -> None:
        """写扩展容器下任意节点 (占写锁, 与其它写串行).

        参数:
            path: 完整 BrowseName 路径
            value: 待写值
            var_type: VALID_NODE_TYPES 里的类型名, 决定 Variant 包装
        """
        vtype = _VARIANT_BY_NAME.get(var_type)
        if vtype is None:
            raise ValueError(f"write_ext 未知类型名: {var_type!r}")

        async def _op():
            async with self._lock:
                node = await self.resolve_ext_node(path)
                try:
                    await node.write_value(
                        ua.DataValue(ua.Variant(self._coerce(value, vtype), vtype)))
                except ua.UaStatusCodeError as exc:
                    log.error("[PLC] write_ext 失败 path=%s vtype=%s status=0x%08X (%s)",
                              "/".join(path), vtype.name,
                              getattr(exc, "code", 0) & 0xFFFFFFFF, exc.__class__.__name__)
                    raise

        await self._guarded(_op)

    async def read_ext_batch(self, paths: list[tuple[str, ...]]) -> list:
        """批量读扩展容器节点, 一次 OPC UA 请求返回全部值.

        参数:
            paths: 完整 BrowseName 路径列表
        返回:
            与 paths 等长的值列表; 单点解析或读取失败置 None, 不影响其余点
        说明:
            单点控制面板一次要拉几十上百个点 (51 缸 ×4 + 11 轴 ×9), 逐点 read 的
            往返次数不可接受; 解析结果有缓存, 稳态下只剩一次 read_values 请求。
        """
        if not paths:
            return []

        async def _op():
            nodes: list[object] = []
            index_of: list[int] = []
            out: list = [None] * len(paths)
            for i, path in enumerate(paths):
                try:
                    nodes.append(await self.resolve_ext_node(path))
                    index_of.append(i)
                except KeyError as exc:
                    log.debug("[PLC] read_ext_batch 路径未解析 %s: %s", "/".join(path), exc)
            if not nodes:
                return out
            try:
                started = time.perf_counter()
                values = await self._client.read_values(nodes)
                self._read_timing.record(len(nodes), time.perf_counter() - started)
            except ua.UaStatusCodeError as exc:
                # 整批失败 (常见于某个 NodeId 已失效) 时降级逐点读, 保住其余点的回显
                log.warning("[PLC] read_ext_batch 批量读失败, 降级逐点: %s", _exc_text(exc))
                values = []
                for node in nodes:
                    try:
                        values.append(await node.read_value())
                    except Exception:
                        values.append(None)
            for slot, value in zip(index_of, values):
                out[slot] = value
            return out

        return await self._guarded(_op)

    def read_timing_stats(self) -> dict:
        """批量读耗时分位数, 按节点数分档。同步只读, 不触网。

        返回:
            {"22-32": {"n":…, "p50_ms":…, "p95_ms":…, "p99_ms":…, "max_ms":…}, …}
        用途:
            判定实时反馈跑不满配置频率时, 病因是服务端读得慢还是客户端调度写错了。
            若 p50 明显小于 (实测周期 − 配置周期), 那就不是读的问题。
        """
        return self._read_timing.snapshot()

    # ------------------------------------------------------------------
    # 动态解析 / 浏览 / 快照
    # ------------------------------------------------------------------

    def missing_reason(self, name: str) -> Optional[str]:
        """该变量若已被判定为 PLC 端不存在, 返回判定原因; 否则 None.

        供上层在批读拿到 None 时区分"节点没下装"与"读回来就是空", 好把诊断话说准。
        """
        return self._missing_nodes.get(name)

    def _check_missing(self, name: str) -> None:
        """负缓存命中即抛 (零往返). 供各读写路径在走动态解析之前调用."""
        reason = self._missing_nodes.get(name)
        if reason is not None:
            raise KeyError(reason)

    async def _resolve_node(self, name: str):
        """运行时按需查找全局变量容器下的变量节点 (表外变量回退).

        未命中会记入 _missing_nodes 负缓存: 本次解析要逐级 browse 容器再在其全部子节点里
        扫一遍, 代价是几十上百次往返; 遥测每秒都读的未下装符号若不负缓存, 等于给 PLC 常年
        挂一个每秒一轮的 browse 风暴。负缓存随 _cache_nodes 清空, 重连即自愈。
        """
        self._check_missing(name)
        if self._client is None:
            raise ConnectionError("PLC 未连接")
        gvl = await resolve_gvl_node(self._client, self._gvl_path)
        try:
            node = await _find_child_by_name(gvl, name)
            log.info("[PLC] 动态节点已解析: %s", name)
            return node
        except KeyError as exc:
            reason = f"PLC 节点 '{name}' 未找到 (容器下无此变量, 路径 {'/'.join(self._gvl_path)})"
            self._missing_nodes[name] = reason
            log.info("[PLC] 节点 '%s' 解析失败, 已记入负缓存 (后续读写零往返直接抛, 重连后重试)", name)
            raise KeyError(reason) from exc

    async def browse_nodes(self) -> dict[str, str]:
        """浏览全局变量容器下所有变量, 返回 {name: 类型名}; 表外变量自动缓存.

        这是"手动重扫"入口: 扫到的名字会从负缓存里摘掉, 所以 PLC 现场刚下装了新符号时,
        不必等一次重连也能让它立刻生效。
        """
        async def _op():
            gvl = await resolve_gvl_node(self._client, self._gvl_path)
            result: dict[str, str] = {}
            for name, child in await browse_children(gvl):
                try:
                    vtype = await child.read_data_type_as_variant_type()
                except Exception:
                    continue
                result[name] = vtype.name
                self._missing_nodes.pop(name, None)   # 现场新下装的符号即刻解禁
                if name not in self._node_map.nodes and name not in self._dynamic_nodes:
                    self._dynamic_nodes[name] = child
                    self._dynamic_types[name] = vtype
            return result

        result = await self._guarded(_op)
        log.info("[PLC] 浏览发现 %d 个变量节点", len(result))
        return result

    async def poll_snapshot(self) -> dict:
        """批量读取节点表 + 动态变量当前值 (不占锁, 供监控轮询)."""
        if self._state != PLCState.CONNECTED or not self._nodes:
            return {}
        result: dict = {}
        for name in self._node_map.nodes:
            try:
                result[name] = await self._read(name)
            except Exception:
                pass
        for name, node in self._dynamic_nodes.items():
            if name in result:
                continue
            try:
                result[name] = await node.read_value()
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # 订阅 / 内存镜像 (事件驱动, 取代上层忙轮询)
    # ------------------------------------------------------------------

    async def add_subscription(self, names) -> None:
        """订阅一组节点的数据变化, 维护内存镜像 (幂等, 可增量追加).

        功能:
            首次调用建立 OPC UA subscription; 后续追加节点到同一 subscription.
            订阅时同步直读一次种子化镜像, 保证 cached* 立即可用. 记录节点名,
            供断线重连后自动重订阅 (见 _resubscribe_all).
        参数:
            names: 待订阅的节点名集合 (须为节点表或可动态解析的变量)
        """
        names = list(names)

        async def _op():
            # fresh 在 op 内重算且成功后才记录: 失败重试时不漏订阅; 若重连先行发生,
            # _resubscribe_all 只挂载已记录集合, 与重试互不重复
            fresh = [n for n in names if n not in self._sub_names]
            if fresh:
                await self._subscribe_nodes(fresh, seed=True)
                self._sub_names.update(fresh)

        await self._guarded(_op)

    def cached(self, name: str):
        """从镜像读取一个已订阅节点的最新值 (无网络; 未订阅返回 None)."""
        return self._mirror.get(name)

    def cached_many(self, names) -> dict:
        """从镜像批量读取 (无网络); 返回 {名: 值}, 未订阅项为 None."""
        return {n: self._mirror.get(n) for n in names}

    async def refresh_mirror(self, names) -> None:
        """直读一批节点当前值写入镜像 (一次性基线; 消除订阅最终一致带来的启动滞后).

        单节点读失败仅跳过该节点; 连接中断则短路其余节点 —— 守卫内每次读都会阻塞等待
        重连, 逐节点重复等待会把一次基线放大成 N 倍阻塞, 调用方按镜像现值决策即可。
        """
        for name in names:
            try:
                self._mirror[name] = await self.read_variable(name)
            except ConnectionError as exc:
                log.warning("[PLC] 镜像基线直读遇连接中断, 跳过其余节点: %s", _exc_text(exc))
                break
            except Exception:
                pass
        self._notify_change()

    def change_token(self) -> int:
        """当前订阅变化计数 (配合 wait_change 实现无丢失唤醒)."""
        return self._change_count

    async def wait_change(self, since_token: int) -> int:
        """阻塞直至订阅出现新数据变化 (相对 since_token); 立即返回若已变化.

        参数:
            since_token: 调用方读取镜像前取得的 change_token
        返回:
            最新 change_token
        """
        if since_token != self._change_count:
            return self._change_count
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._change_waiters.append(fut)
        try:
            await fut
        finally:
            try:
                self._change_waiters.remove(fut)
            except ValueError:
                pass
        return self._change_count

    def datachange_notification(self, node, val, data) -> None:
        """asyncua 订阅回调: 更新镜像并唤醒等待者 (同步, 在事件循环内被调用)."""
        name = self._sub_name_by_nodeid.get(node.nodeid)
        if name is None:
            return
        self._mirror[name] = val
        self._notify_change()

    def _notify_change(self) -> None:
        """递增变化计数并唤醒全部等待者 (取出后清空, 避免重复唤醒)."""
        self._change_count += 1
        waiters, self._change_waiters = self._change_waiters, []
        for fut in waiters:
            if not fut.done():
                fut.set_result(None)

    async def _subscribe_nodes(self, names, *, seed: bool) -> None:
        """解析节点对象, 种子化镜像并挂到 subscription (调用方保证已连接)."""
        nodes = []
        for name in names:
            node = self._nodes.get(name) or self._dynamic_nodes.get(name)
            if node is None:
                node = await self._resolve_node(name)
                self._dynamic_nodes[name] = node
            self._sub_name_by_nodeid[node.nodeid] = name
            if seed:
                try:
                    self._mirror[name] = await node.read_value()
                except Exception:
                    pass
            nodes.append(node)
        if self._subscription is None:
            self._subscription = await self._client.create_subscription(self._sub_period_ms, self)
        # queuesize 深队列 + sampling_interval 快采: 降低漏推概率 (溢出丢弃/快跳变漏采); 详见构造期注释。
        await self._subscription.subscribe_data_change(
            nodes, queuesize=self._sub_queue_size, sampling_interval=self._sub_sampling_ms)
        self._notify_change()  # 种子化后唤醒可能已在等待的调用方

    async def _resubscribe_all(self) -> None:
        """(重)建订阅并重新挂载全部已记录节点 (供 connect / 重连后调用)."""
        if not self._sub_names:
            return
        if self._subscription is not None:  # 旧 subscription 尽力删除 (重连时旧 client 已死, 失败忽略)
            try:
                await self._subscription.delete()
            except Exception:
                pass
        self._subscription = None
        self._sub_name_by_nodeid.clear()
        await self._subscribe_nodes(list(self._sub_names), seed=True)
        log.info("[PLC] 订阅已恢复: %d 个节点", len(self._sub_names))

    # ------------------------------------------------------------------
    # 心跳与重连
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """每 100ms 读心跳节点, 同步检测急停上升沿; 连续失败进入 RECONNECTING."""
        fallback_warned = False
        hb_node = self._node_map.heartbeat_node
        estop_node = self._node_map.estop_node
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                # 心跳活检: 优先心跳节点, 缺失则降级到任意可用节点
                try:
                    await self._read(hb_node)
                except KeyError:
                    fallback = next(iter(self._nodes), None) or next(iter(self._dynamic_nodes), None)
                    if fallback is None:
                        raise RuntimeError("全局变量容器下无任何可用节点")
                    if not fallback_warned:
                        log.warning("[PLC] 心跳节点 '%s' 未缓存, 降级读取 '%s'", hb_node, fallback)
                        fallback_warned = True
                    node_obj = self._nodes.get(fallback) or self._dynamic_nodes.get(fallback)
                    await node_obj.read_value()

                self._hb_fail_count = 0
                # 急停边沿检测
                try:
                    estop = bool(await self._read(estop_node))
                except Exception:
                    estop = False
                if estop and not self._prev_estop:
                    log.error("[PLC] 检测到急停 %s=True (上升沿)", estop_node)
                    if self._on_estop is not None:
                        try:
                            self._spawn_estop()
                        except Exception as exc:
                            log.warning("[PLC] on_estop 调度失败: %s", _exc_text(exc))
                self._prev_estop = estop

            except KeyError as exc:
                if not fallback_warned:
                    log.warning("[PLC] 心跳节点缺失 (不触发重连): %s", exc)
                    fallback_warned = True
            except Exception as exc:
                self._hb_fail_count += 1
                log.warning("[PLC] 心跳失败 (%d/%d): %s",
                            self._hb_fail_count, HEARTBEAT_MAX_FAIL, _exc_text(exc))
                if self._hb_fail_count >= HEARTBEAT_MAX_FAIL:
                    log.error("[PLC] 心跳连续失败 %d 次, 进入 RECONNECTING", HEARTBEAT_MAX_FAIL)
                    self._connected_evt.clear()
                    await self._set_state(PLCState.RECONNECTING)
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())
                    return

    async def _reconnect_loop(self) -> None:
        """指数退避重连; 成功后恢复 CONNECTED 并重启心跳.

        拆连顺序有讲究: **先摘干净所有缓存节点, 再 disconnect**。
        asyncua 的 Node 对象硬引用创建它的 session, 所以只把 self._client 置 None 拦不住
        并发协程继续用 self._nodes[x] 往旧会话发请求; 而 disconnect() 内部的
        close_secure_channel() 会在 socket 仍开着时清空待应答表, 那些后到的请求与响应就会
        撞出库内的 "No request found for request id ..." 并把 socket 直接拆掉。
        先摘缓存 -> 并发协程只会拿到干净的 ConnectionError 去排队等重连, 不再往垂死会话上打。
        仍保留优雅 disconnect (而不是硬拆 socket): 嵌入式 OPC UA 服务端会话槽有限,
        CloseSession 能立刻还回去, 别留给它自己超时回收。
        """
        attempt = 0
        old, self._client = self._client, None
        self._nodes.clear()
        self._dynamic_nodes.clear()
        self._dynamic_types.clear()
        self._ext_nodes.clear()
        self._ext_children.clear()
        self._missing_nodes.clear()
        if old is not None:
            try:
                await old.disconnect()
            except Exception:
                pass
        while True:
            backoff = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log.info("[PLC] 重连尝试 #%d, 退避 %.1fs", attempt, backoff)
            await asyncio.sleep(backoff)
            # 两段式: connect 与 节点/订阅 的失败清理语义不同, 不能共用一个 except。
            client = self._new_client()
            try:
                await client.connect()
            except Exception as exc:
                # 此处不再 disconnect(): asyncua connect() 失败时内部已拆 socket,
                # 再调一次只会打出 "close_secure_channel was called but connection is closed" 噪音
                log.warning("[PLC] 重连失败 (#%d, connect): %s — %s",
                            attempt, _exc_text(exc), await self._link_hint())
                continue
            self._client = client
            try:
                await self._cache_nodes()
                await self._resubscribe_all()  # 新连接上重建订阅 (节点对象已重新缓存)
            except Exception as exc:
                log.warning("[PLC] 重连失败 (#%d, 节点/订阅): %s", attempt, _exc_text(exc))
                try:
                    await client.disconnect()  # 这里连接是活的, 必须拆
                except Exception:
                    pass
                self._client = None
                continue
            self._hb_fail_count = 0
            self._prev_estop = False
            self._reconnect_count += 1
            await self._set_state(PLCState.CONNECTED)
            self._connected_evt.set()
            log.info("[PLC] 重连成功 (累计 %d 次)", self._reconnect_count)
            self._hb_task = asyncio.create_task(self._heartbeat_loop())
            self._reconnect_task = None
            return
