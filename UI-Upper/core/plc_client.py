"""PLCClient - OPC UA 通信封装
============================
与PLC（或 mock/plc_server.py）通信的唯一入口。

关键约束：
- 所有写操作通过内部 asyncio.Lock 串行执行
- 心跳监测：每 100ms 读一次节点，连续失败3次进入 RECONNECTING 态
- RECONNECTING 态：后台指数退避重连，send_* 方法阻塞等待直到恢复或超时
- 急停：心跳循环同时读 PLC_EStop，False→True 上升沿触发 on_estop 回调

Phase C：旧握手路径（send_action/wait_done/send_vision_result）已删除。
电平范式 API：start_stage / await_stage_done / await_stage_step / confirm_stage。
"""

import asyncio
import logging
from enum import Enum
from typing import Awaitable, Callable, Optional

from asyncua import Client, ua

log = logging.getLogger(__name__)

# OPC UA 服务器默认地址（与 mock/plc_server.py 一致）
DEFAULT_URL = "opc.tcp://localhost:4840"

# OPC UA 路径：Objects 起逐级按 BrowseName 文本匹配（跨命名空间）到全局变量容器
# 实机（Inovance / CODESYS 内核）树结构：
#   Objects/DeviceSet/Inovance-ARM-Linux/Resources/Application/GlobalVars/Host_Computer/<var>
# mock/plc_server.py 会构建同构的树。
# 不用 namespace index 定位：每层经 read_browse_name().Name 比对文本，
# 自动兼容 http://opcfoundation.org/UA/DI/ 与 http://PLCopen.org/OpcUa/IEC61131-3/ 等多命名空间分层。
GVL_PATH = [
    "DeviceSet",
    "Inovance-ARM-Linux",
    "Resources",
    "Application",
    "GlobalVars",
    "Host_Computer",
]

# 心跳参数
HEARTBEAT_INTERVAL = 0.1   # 100 ms
HEARTBEAT_MAX_FAIL = 3     # 连续失败次数阈值

# 重连退避序列（秒），末项为最大退避
RECONNECT_BACKOFF = [1.0, 2.0, 4.0, 8.0, 30.0]


def _warn_long_wait(label: str, elapsed: float, hint_seconds: float) -> None:
    """长等待提示：log.warning + UI 通知（非阻塞、零依赖）。

    用于 await_stage_done / await_stage_step / await_drain_done 三个轮询函数：
    `timeout` 参数语义已改为「提示间隔」而非「放弃阈值」——超过 hint_seconds
    仍未完成时调用本函数发一次提示，循环继续等待，直到 PLC 完成或外部取消
    （急停 / 任务取消按钮）。

    UI 通知通过 state._notification_queue 由 NiceGUI timer 消费（与 estop.py 同模式），
    避免后台任务直接调用 ui.notify() 触发 slot stack 错误。
    """
    msg = (f"⏳ {label} 已等待 {int(elapsed)}s（>={int(hint_seconds)}s 仍未完成），"
           f"PLC 可能未推进，请检查或手动急停")
    log.warning("[PLC] %s", msg)
    try:
        from ui.state import get_state  # 延迟导入：避免 core 反向依赖 ui
        state = get_state()
        state._notification_queue.append((msg, "warning"))
    except Exception:
        # UI 未就绪 / 测试脚本场景：仅日志即可
        pass

# 节点类型映射（显式指定，避免 asyncua 自动推断错误类型）
# Phase A.1 / 协议 v1.1：删除 Recipe_Param_A..F / I1..I4 / Recipe_Gcode_Name / Recipe_Mode_Flag
# 通用抽象，各工位参数按业务名直接声明。
NODE_TYPES: dict[str, ua.VariantType] = {
    # ── 调试辅助（Batch 7）──
    "Test_BOOL":       ua.VariantType.Boolean,
    # ── 协议 v1.1：collect 工位六件套 + 业务参数 ──
    # 契约见 docs/PLC_Unified_Stage_Protocol.md
    "collect_Enable":               ua.VariantType.Boolean,
    "collect_Step":                 ua.VariantType.Int16,     # 实机 PLC 声明为 INT（Int16）
    "collect_Done":                 ua.VariantType.Boolean,
    "collect_Error":                ua.VariantType.Boolean,
    "collect_Reset":                ua.VariantType.Boolean,
    "collect_Busy":                 ua.VariantType.Boolean,   # v1.1: 工位独立 _Busy
    "collect_forward_instructions": ua.VariantType.String,     # v1.1: 注射泵转发指令
    "collect_count":                ua.VariantType.Int16,      # 实机 PLC 声明为 INT（Int16）
    # ── 协议 v1.2：develop（展开）工位六件套 + 业务参数 ──
    # PLC 变量前缀为 Expand（实机 Host_Computer 命名），上位机 stage name 为 develop
    # 契约见 docs/PLC_Unified_Stage_Protocol.md §7
    "Expand_Enable":                          ua.VariantType.Boolean,
    "Expand_Step":                            ua.VariantType.Int16,   # 实机 PLC 声明为 INT（Int16）
    "Expand_Done":                            ua.VariantType.Boolean,
    "Expand_Error":                           ua.VariantType.Boolean,
    "Expand_Reset":                           ua.VariantType.Boolean,
    "Expand_Busy":                            ua.VariantType.Boolean,   # v1.2: 工位独立 _Busy
    # Expand_Confirm 已废弃（v1.3）：排液由 Tank_Drain_Enable[i] 替代
    "Expand_Mode_Flag":                       ua.VariantType.Int16,     # 0=润洗缸 / 1=清洗管路
    "Expand_Group":                           ua.VariantType.Int16,     # 展开组号（PLC 从 Target_Tank 自动推导，上位机不再写入）
    "Expand_Number":                          ua.VariantType.Int16,     # 展缸号（PLC 从 Target_Tank 自动推导，上位机不再写入）
    "Expand_forward_instructions":            ua.VariantType.String,    # 注射泵转发指令
    # ── 协议 v1.3：多通道展开 - 展缸状态跟踪（真数组节点）──
    "Tank_State":            ua.VariantType.Int16,      # ARRAY[1..8] OF INT {0,10,40,50,99,90}
    "Tank_SampleID":         ua.VariantType.Int32,      # ARRAY[1..8] OF DINT（调试用）
    "Tank_Drain_Enable":     ua.VariantType.Boolean,    # ARRAY[1..8] OF BOOL
    "Tank_Drain_Done":        ua.VariantType.Boolean,    # ARRAY[1..8] OF BOOL
    # ── 协议 v1.3：目标缸号（标量）──
    "Expand_Target_Tank":    ua.VariantType.Int16,      # INT 1-8，PC 写入，PLC 自动推导 Group/Number
    "Expand_rinse_count":     ua.VariantType.Int16,      # 润洗注射泵重复执行次数（Step 10）
    "Expand_up_liquid_count": ua.VariantType.Int16,      # 上液注射泵重复执行次数（Step 20）
    # ── 协议 v1.4：spotting（上样点样）工位六件套 + 业务参数 ──
    # PLC 变量前缀 Sampling（实机 Host_Computer 命名），契约见 docs/PLC_Unified_Stage_Protocol.md §6
    "Sampling_Enable":                 ua.VariantType.Boolean,
    "Sampling_Step":                   ua.VariantType.Int16,     # 实机 PLC 声明为 INT（Int16）
    "Sampling_Done":                   ua.VariantType.Boolean,
    "Sampling_Error":                  ua.VariantType.Boolean,
    "Sampling_Reset":                  ua.VariantType.Boolean,
    "Sampling_Busy":                   ua.VariantType.Boolean,
    "Sampling_clean_instructions":      ua.VariantType.String,    # ARRAY[1..2] OF STRING(128) — 清洗 [内壁, 外壁]（Step 10）
    "Sampling_clean_count":             ua.VariantType.Int16,     # 清洗次数
    # 协议 v1.5 4 数组重构：bubble_instructions 拆分为 prep + sample + dispense 三个 1×2 数组
    "Sampling_prep_instructions":       ua.VariantType.String,    # ARRAY[1..2] OF STRING(128) — 上样准备 [吸取空气, 废液打出]（Step 20）
    "Sampling_X_coordinate":            ua.VariantType.Int16,     # 上样 X 坐标
    "Sampling_Y_coordinate":            ua.VariantType.Int16,     # 上样 Y 坐标
    "Sampling_sample_instructions":     ua.VariantType.String,    # ARRAY[1..2] OF STRING(128) — 上样 [回抽样品, 废液排废]（Step 40）
    "Sampling_dispense_instructions":   ua.VariantType.String,    # ARRAY[1..2] OF STRING(128) — 点样 [抽取空气, 打气点样]（Step 50）
    # Sampling L2 atomic-action channel; ControlMode keeps it exclusive with legacy.
    "Sampling_ControlMode":             ua.VariantType.Int16,     # 0=LEGACY, 1=L2
    "Sampling_L2_ActionCode":           ua.VariantType.Int16,
    "Sampling_L2_RequestSeq":           ua.VariantType.Int32,
    "Sampling_L2_Start":                ua.VariantType.Boolean,
    "Sampling_L2_Reset":                ua.VariantType.Boolean,
    "Sampling_L2_State":                ua.VariantType.Int16,
    "Sampling_L2_ActiveCode":           ua.VariantType.Int16,
    "Sampling_L2_AcceptedSeq":          ua.VariantType.Int32,
    "Sampling_L2_CompletedSeq":         ua.VariantType.Int32,
    "Sampling_L2_Step":                 ua.VariantType.Int16,
    "Sampling_L2_ErrorCode":            ua.VariantType.Int16,
    "Sampling_L2_SafeState":            ua.VariantType.Int16,
    "Sampling_L2_Retryable":            ua.VariantType.Boolean,
    # Rail (地轨轴11Y) L2 伺服原子动作通道 (类型须与 mock/实机节点一致, 避免 String 误写)
    "Rail_L2_ActionCode":               ua.VariantType.Int16,
    "Rail_L2_RequestSeq":               ua.VariantType.Int32,
    "Rail_L2_Start":                    ua.VariantType.Boolean,
    "Rail_L2_Reset":                    ua.VariantType.Boolean,
    "Rail_L2_State":                    ua.VariantType.Int16,
    "Rail_L2_ActiveCode":               ua.VariantType.Int16,
    "Rail_L2_AcceptedSeq":              ua.VariantType.Int32,
    "Rail_L2_CompletedSeq":             ua.VariantType.Int32,
    "Rail_L2_Step":                     ua.VariantType.Int16,
    "Rail_L2_ErrorCode":                ua.VariantType.Int16,
    "Rail_L2_SafeState":                ua.VariantType.Int16,
    "Rail_L2_Retryable":                ua.VariantType.Boolean,
    # ── 协议 v1.5：scrape（拍照刮板）工位六件套 + 业务参数 ──
    # PLC 变量前缀 scrape，契约见 docs/PLC_Unified_Stage_Protocol.md §8
    "scrape_Enable":                 ua.VariantType.Boolean,
    "scrape_Step":                   ua.VariantType.Int16,     # 実机 PLC 声明为 INT（Int16）
    "scrape_Done":                   ua.VariantType.Boolean,
    "scrape_Error":                  ua.VariantType.Boolean,
    "scrape_Reset":                  ua.VariantType.Boolean,
    "scrape_Busy":                   ua.VariantType.Boolean,
    "scrape_Confirm":                ua.VariantType.Boolean,   # v1.5: 乒乓确认信号
    "scrape_WaitConfirm":            ua.VariantType.Boolean,   # v1.7: PLC 侧显式就绪信号（进入 confirm 轮询时 TRUE，消费后 FALSE）
    "scrape_gcode_instructions":     ua.VariantType.String,    # v1.5: G-code 指令（CNC 主方案接入后保留兼容写空）
    "scrape_PhotoMode":              ua.VariantType.Int16,     # v1.6: 0=完整刮板, 1=仅before-photo, 2=重刮（V3：跳过A00+A10物理拍照）
    "scrape_IsLast":                 ua.VariantType.Boolean,   # v1.8 V3: TRUE=本次为该样品最后一次刮取（PLC 据此清板送废料）
    # 诊断用单向变量（PC→PLC，仅写不读、PLC 缺失即 WARN 降级）：
    # 写入本次 scrape 对应的展缸号（pending_release_tank）。用于 PLC 端 trace
    # 与上位机 handoff 校验侧的事后比对，不参与任何控制路由；0=未关联展缸
    # （重刮 / collect-only 路径）。最小耦合：仅一个 Int16，可选消费。
    "scrape_Source_Tank":            ua.VariantType.Int16,
    # ── CNC 主方案：Host_Computer/ScrapeCNC 点位数组 + 标量参数 ──
    # 契约见 docs/PLC_ScrapeCNC_Interface.md，模板见 CNCTest/scrape_template_v2.cnc
    "g_sx":                ua.VariantType.Float,     # ARRAY[1..400] OF REAL
    "g_sy":                ua.VariantType.Float,     # ARRAY[1..400] OF REAL
    "g_cx":                ua.VariantType.Float,     # ARRAY[1..400] OF REAL
    "g_cy":                ua.VariantType.Float,     # ARRAY[1..400] OF REAL
    "g_safe_z":            ua.VariantType.Float,     # REAL 安全高度 mm
    "g_approach_z":        ua.VariantType.Float,     # REAL 接近高度 mm
    "g_pass_z":            ua.VariantType.Float,     # REAL 当前 pass 深度 mm
    "g_pass_count":        ua.VariantType.Int16,     # INT pass 次数（0=占位/跳过）
    "g_total_depth":       ua.VariantType.Float,     # REAL 总深度 mm
    "g_plate_surface_z":   ua.VariantType.Float,     # REAL 板面 Z 基准 mm
    "g_scrape_feed":       ua.VariantType.Int16,     # INT 刮扫进给 mm/min
    "g_plunge_feed":       ua.VariantType.Int16,     # INT 下刀进给 mm/min
    # ── 协议 v2.5：耗材管理（PC→PLC 决策参数 + PLC→PC 传感器数组）──
    # 契约见 UI-Upper/plans/consumable_phase3_plc_interface_plan.md §3.1
    # v2.5 动作码：暂存区无传感器，PC 账本显式告知 PLC 动作语义
    # （0=NONE, 1=PUT_NEW, 2=SWAP）。PLC 哑执行不推理。
    "scrape_Plate_Op":          ua.VariantType.Int16,   # 0=NONE/1=PUT_NEW/2=SWAP
    "scrape_Fetch_Rack_Plate":  ua.VariantType.Int16,   # 0=不搬, 1-12=从架搬板到暂存A
    "scrape_Old_Plate_Slot":    ua.VariantType.Int16,   # 0 或 1-12（仅 op=SWAP 时非0）
    "scrape_Consume_Slot":      ua.VariantType.Int16,   # 1-6=从暂存A取该孔
    "collect_Plate_Op":         ua.VariantType.Int16,   # 同 scrape_Plate_Op
    "collect_Fetch_Rack_Plate": ua.VariantType.Int16,   # 0=不搬, 1-12=从架搬板到暂存B
    "collect_Old_Plate_Slot":   ua.VariantType.Int16,   # 0 或 1-12（仅 op=SWAP 时非0）
    "collect_Consume_Slot":     ua.VariantType.Int16,   # 1-6=从暂存B取该孔
    "collect_Powder_Return_Slot": ua.VariantType.Int16, # v2.4：粉末收集器归还暂存A 原始孔号（1-6）
    # 协议 v2.3 修订：耗材架板级在位 DI 改用 2 BYTE 打包（PLC 工程未按 ARRAY[1..12] OF BOOL 实现）
    # IX11.bit0..bit7 = 料库检测 1..8（粉末板 1-6 + 玻璃瓶板 1-2）
    # IX12.bit0..bit3 = 料库检测 9..12（玻璃瓶板 3-6），bit4..7 保留
    # 位解码由 PLCClient.read_consumable_sensor() 封装，对外仍呈现 list[bool, 12]。
    "IX11":                     ua.VariantType.Byte,
    "IX12":                     ua.VariantType.Byte,
    # 全局急停（上升沿触发上位机 on_estop 回调）
    "PLC_EStop":       ua.VariantType.Boolean,
    # ── 实机 PLC Host_Computer 额外变量（b 前缀）──
    "bOutput":         ua.VariantType.Boolean,
    "bEnable":         ua.VariantType.Boolean,
    "bErrorReset":     ua.VariantType.Boolean,
    "bStepEnable":     ua.VariantType.Boolean,
}

# 数组维度信息（供 PLCClient 辅助方法使用）
NODE_ARRAYS: dict[str, int] = {
    "Tank_State":                8,
    "Tank_SampleID":             8,
    "Tank_Drain_Enable":         8,
    "Tank_Drain_Done":           8,
    "Sampling_clean_instructions": 2,     # ARRAY[1..2] OF STRING(128) — 清洗 [内壁, 外壁]
    "Sampling_prep_instructions": 2,      # ARRAY[1..2] OF STRING(128) — 上样准备
    "Sampling_sample_instructions": 2,    # ARRAY[1..2] OF STRING(128) — 上样
    "Sampling_dispense_instructions": 2,  # ARRAY[1..2] OF STRING(128) — 点样
    # CNC 主方案：刮扫 + 收集点位数组（与 scrape_template_v2.cnc g_sx[1..400] 等对齐）
    "g_sx":  400,
    "g_sy":  400,
    "g_cx":  400,
    "g_cy":  400,
    # ── 协议 v2.3（再修订）：耗材架板级 DI 改用 IX11/IX12 两个 BYTE 标量 ──
    # 不再是数组节点（PLC 工程师未按 ARRAY[1..12] OF BOOL 暴露），
    # 由 PLCClient.read_consumable_sensor() 读 2 BYTE → 按位解码 list[bool, 12]。
}

# Phase A：Stage 心跳读取的节点名（任选一个包含全局与工位，验证心跳在两类节点上都工作）
HEARTBEAT_NODE = "collect_Step"
ESTOP_NODE = "PLC_EStop"

# CNC 主方案必需变量集合：连接缓存完成后做一次差集自检，
# 若 PLC 工程未升级到支持 ScrapeCNC，启动期 ERROR 即时暴露，
# 避免 ScrapeStage / Debug Tab / test_cnc_e2e 首次写入时才以 KeyError 形式爆炸。
REQUIRED_SCRAPE_CNC_VARS: tuple[str, ...] = (
    "g_sx", "g_sy", "g_cx", "g_cy",
    "g_safe_z", "g_approach_z", "g_pass_z",
    "g_pass_count", "g_total_depth",
    "g_plate_surface_z", "g_scrape_feed", "g_plunge_feed",
)

# 协议 v2.5 耗材管理必需变量集合：启动期自检，
# PLC 工程未升级时提前 ERROR，避免 Stage 首次写入时 KeyError。
# v2.5 新增 Plate_Op / Old_Plate_Slot 4 个变量（PC 显式动作码协议）。
REQUIRED_CONSUMABLE_VARS: tuple[str, ...] = (
    "scrape_Plate_Op", "scrape_Fetch_Rack_Plate",
    "scrape_Old_Plate_Slot", "scrape_Consume_Slot",
    "collect_Plate_Op", "collect_Fetch_Rack_Plate",
    "collect_Old_Plate_Slot", "collect_Consume_Slot",
    "collect_Powder_Return_Slot",  # v2.4 跨工位粉末收集器归还孔
    "IX11", "IX12",  # 耗材架板级 DI（2 BYTE 打包，位序见 read_consumable_sensor）
)


# ----------------------------------------------------------------------
# OPC UA 路径定位工具函数（跨命名空间，VariableMonitor 也复用）
# ----------------------------------------------------------------------

async def _find_child_by_name(parent, name: str):
    """在 parent 的直接子节点中按 BrowseName.Name 匹配，返回匹中节点。

    不依赖 namespace index，同一路径对实机（多 ns 分层）与 mock（单 ns）通用。
    未命中抛 KeyError。
    """
    children = await parent.get_children()
    for child in children:
        try:
            bn = await child.read_browse_name()
            if bn.Name == name:
                return child
        except Exception:
            continue
    raise KeyError(f"未找到子节点 '{name}'")


async def resolve_gvl_node(client_session):
    """沿 GVL_PATH 逐层按 BrowseName 文本定位到 Host_Computer 对象节点。

    供 PLCClient 内部与外部（如 VariableMonitor）共享，避免路径路线双维护。
    """
    node = client_session.nodes.objects
    for part in GVL_PATH:
        node = await _find_child_by_name(node, part)
    return node


class PLCState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTED    = "connected"
    RECONNECTING = "reconnecting"
    ERROR        = "error"


# 外部回调类型
StateChangeCallback = Callable[[PLCState], Awaitable[None]]
EstopCallback       = Callable[[], Awaitable[None]]


class PLCClient:
    """OPC UA PLC 客户端。

    使用方式：
        client = PLCClient(on_state_change=cb, on_estop=cb2)
        await client.connect()
        await client.start_stage("collect", params)
        await client.disconnect()

    或使用 async context manager：
        async with PLCClient() as client:
            await client.start_stage("collect")

    参数：
        url                     : OPC UA 服务器地址
        on_state_change         : 状态迁移回调（异步，单参数 PLCState）
        on_estop                : 急停触发回调（异步，无参数）
        reconnect_wait_timeout  : send_* 等待重连恢复的最大秒数，超时抛 ConnectionError
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        on_state_change: Optional[StateChangeCallback] = None,
        on_estop: Optional[EstopCallback] = None,
        reconnect_wait_timeout: float = 60.0,
    ):
        self._url = url
        self._client: Optional[Client] = None
        self._lock = asyncio.Lock()
        self._state = PLCState.DISCONNECTED
        self._hb_fail_count = 0
        self._hb_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None

        # 节点缓存（连接后填充）
        self._nodes: dict[str, object] = {}
        # 动态节点缓存（运行时按需查找，不在 NODE_TYPES 中的变量）
        self._dynamic_nodes: dict[str, object] = {}
        self._dynamic_types: dict[str, ua.VariantType] = {}

        # 外部回调（支持多订阅：Scheduler + UI 同时监听）
        self._state_listeners: list[StateChangeCallback] = []
        if on_state_change is not None:
            self._state_listeners.append(on_state_change)
        self._on_estop = on_estop
        self._reconnect_wait_timeout = reconnect_wait_timeout

        # 连接可用事件（CONNECTED 时 set，其他态 clear）
        self._connected_evt = asyncio.Event()

        # 急停边沿检测
        self._prev_estop = False

        # 重连计数（供上层统计展示）
        self._reconnect_count = 0

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """连接到 OPC UA 服务器并启动心跳。"""
        self._client = Client(self._url)
        await self._client.connect()
        log.info("[PLC] 已连接: %s", self._url)
        await self._cache_nodes()
        await self._set_state(PLCState.CONNECTED)
        self._hb_fail_count = 0
        self._prev_estop = False
        self._connected_evt.set()
        self._hb_task = asyncio.create_task(self._heartbeat_loop())

    async def disconnect(self) -> None:
        """断开连接并停止心跳/重连任务。"""
        for task in (self._hb_task, self._reconnect_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._hb_task = None
        self._reconnect_task = None

        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                log.warning("[PLC] 断开时出现异常（忽略）: %s", e)
        self._connected_evt.clear()
        await self._set_state(PLCState.DISCONNECTED)
        log.info("[PLC] 已断开")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.disconnect()

    # ------------------------------------------------------------------
    # 核心公共方法
    # ------------------------------------------------------------------

    async def send_recipe_params(self, params: dict) -> None:
        """批量写入工位业务参数（协议 v1.1：业务直名）。
    
        params dict 的 key 直接是 PLC 变量名（如 collect_forward_instructions / collect_count），
        value 是对应值。类型按 NODE_TYPES 查找并带型写入；动态变量走 _dynamic_types。
    
        未在 NODE_TYPES 及 _dynamic_types 中出现的 key 记 WARNING 并忽略。
        Stage 内部在置位 _Enable 之前调用；本方法自身占锁，与 start_stage 串行。
        """
        if not params:
            return
        await self._await_connected()
        async with self._lock:
            for name, value in params.items():
                # 数组节点（NODE_ARRAYS 中声明）— 整体写入，value 必须是 list
                if name in NODE_ARRAYS and isinstance(value, (list, tuple)):
                    await self._write_array(name, list(value))
                    continue
                if name in NODE_TYPES:
                    vtype = NODE_TYPES[name]
                    coerced = self._coerce_value(value, vtype)
                    if name in self._nodes:
                        await self._write(name, coerced)
                    else:
                        # NODE_TYPES 声明但 _cache_nodes 未命中 → 动态解析回退
                        # （与 read_variable 三级回退对齐，修复"能读不能写"不对称）
                        if name not in self._dynamic_nodes:
                            try:
                                node = await self._resolve_node(name)
                                self._dynamic_nodes[name] = node
                                log.info("[PLC] 动态解析写入节点: %s（_cache_nodes 未命中，回退成功）", name)
                            except KeyError:
                                log.warning("[PLC] 写入跳过: %s（NODE_TYPES 声明但 PLC 端未发现，动态解析也失败）", name)
                                continue
                        node = self._dynamic_nodes[name]
                        await node.write_value(ua.DataValue(ua.Variant(coerced, vtype)))
                elif name in self._dynamic_nodes:
                    vtype = self._dynamic_types.get(name, ua.VariantType.String)
                    coerced = self._coerce_value(value, vtype)
                    node = self._dynamic_nodes[name]
                    await node.write_value(ua.DataValue(ua.Variant(coerced, vtype)))
                else:
                    log.warning("[PLC] 未知参数变量: %s（不在 NODE_TYPES 与动态缓存，已忽略）", name)
        # 日志中 list 值过长，仅记录长度防止刷屏
        log_view = {
            k: f"<list len={len(v)}>" if isinstance(v, (list, tuple)) and len(v) > 8 else v
            for k, v in params.items()
        }
        log.info("[PLC] 工位参数已写入: %s", log_view)
    
    @staticmethod
    def _coerce_value(value, vtype: ua.VariantType):
        """按 VariantType 强转 value，避免 asyncua 严格类型报错。"""
        if vtype == ua.VariantType.Float:
            return float(value)
        if vtype in (ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.UInt16):
            return int(value)
        if vtype == ua.VariantType.Boolean:
            return bool(value)
        if vtype == ua.VariantType.String:
            return str(value)
        return value

    async def _verify_params_barrier(self, params: Optional[dict]) -> bool:
        """写-查-Enable 屏障：选取最后一个标量参数做 read-back 验证。

        TCP 有序性保证：如果最后写入的参数读回正确，则所有先前的参数必已落地。
        构成 start_stage 中 Enable=TRUE 之前的完整内存屏障。

        策略：
          - 从 params 中选取最后一个非数组、已缓存节点的标量参数
          - 读回并比对（数值类型做粗略比较，容忍浮点精度差异）
          - 最多重试 3 次，每次间隔 20ms
          - 若无可验证参数或验证失败，返回 False（调用方回退到 50ms sleep）

        Returns:
            True = 屏障通过（参数已确认落地），False = 回退到 sleep
        """
        if not params:
            return False

        # 选取屏障变量：最后一个非数组、已缓存节点的标量参数
        barrier_name: Optional[str] = None
        barrier_expected = None
        for name, value in params.items():
            if isinstance(value, (list, tuple)):
                continue  # 跳过数组参数（读回开销大）
            if name in self._nodes or name in self._dynamic_nodes:
                barrier_name = name
                barrier_expected = value

        if barrier_name is None:
            return False

        # 读回验证（最多 3 次，总耗时上限 ~60ms）
        for attempt in range(3):
            try:
                actual = await self.read_variable(barrier_name)
                if self._barrier_match(barrier_expected, actual):
                    log.debug(
                        "[PLC] 屏障验证通过: %s = %s (attempt %d)",
                        barrier_name, actual, attempt + 1,
                    )
                    return True
                log.debug(
                    "[PLC] 屏障验证未匹配: %s expected=%s actual=%s (attempt %d)",
                    barrier_name, barrier_expected, actual, attempt + 1,
                )
            except Exception as e:
                log.debug("[PLC] 屏障验证读取异常: %s %s", barrier_name, e)
            await asyncio.sleep(0.02)  # 20ms 重试间隔

        log.warning(
            "[PLC] 屏障验证失败（回退 50ms sleep）: %s expected=%s",
            barrier_name, barrier_expected,
        )
        return False

    @staticmethod
    def _barrier_match(expected, actual) -> bool:
        """屏障比较：容忍浮点精度差异和类型差异。"""
        try:
            # 整数比较
            if isinstance(expected, int):
                return int(actual) == expected
            # 浮点比较（容忍 PLC REAL 4字节精度）
            if isinstance(expected, float):
                return abs(float(actual) - expected) < 0.01
            # 布尔比较
            if isinstance(expected, bool):
                return bool(actual) == expected
            # 字符串比较
            return str(actual) == str(expected)
        except (ValueError, TypeError):
            return False

    async def start_stage(self, stage: str, params: Optional[dict] = None) -> None:
        """Phase A：启动一个电平范式工位状态机（契约见 docs/PLC_Unified_Stage_Protocol.md）。

        时序（v1.10 下降沿确认 + 写-查-Enable 屏障）：
          1. 写 Recipe 参数（params非空时）
          2. 确保 <stage>_Enable=FALSE（幂等复位）、清 <stage>_Confirm
          3. 轮询确认 Done=FALSE（最多 2s）—— 等待 FSM 下降沿处理自行清除 Done，
             不主动写 Done=FALSE（否则会掩盖 FSM 未处理下降沿的事实）
          4. Read-back 验证关键参数已落地（构成完整内存屏障）
          5. 写 <stage>_Enable=TRUE（不阻塞）

        下降沿确认原理（v1.10 核心修正）：
          FSM 下降沿处理器（Enable TRUE→FALSE）会自行写 Done=FALSE + 取消 run_task。
          Done 从 TRUE→FALSE 的转变是 FSM 已处理下降沿的唯一可靠信号。
          旧版本 start_stage 直接写 Done=FALSE，导致轮询读到的是自己写的值
          而非 FSM 的确认，back-to-back 启动时 FSM 下降沿未处理就写 Enable=TRUE，
          上升沿丢失。v1.10 去掉直接写入，改为等待 FSM 自行清除。

        params dict 格式与 send_recipe_params 一致。
        """
        await self._await_connected()
        enable_name = f"{stage}_Enable"
        done_name = f"{stage}_Done"
        confirm_name = f"{stage}_Confirm"
        if enable_name not in NODE_TYPES:
            raise KeyError(f"未知工位：{stage}（{enable_name} 不在 NODE_TYPES）")
        if params:
            await self.send_recipe_params(params)
        async with self._lock:
            # 幂等复位：确保 Enable=FALSE，为后续上升沿做准备
            await self._write(enable_name, False)
            # v1.10: 不直接写 Done=FALSE —— Done 只能由 FSM 下降沿处理清除。
            # 这样后续轮询 Done=FALSE 才能作为「FSM 已处理下降沿」的可靠确认。
            # v1.7: 主动清零 Confirm（不依赖 PLC 侧清零，防止上次残留导致无上升沿）
            if confirm_name in NODE_TYPES and confirm_name in self._nodes:
                await self._write(confirm_name, False)

        # v1.10: 轮询等待 FSM 下降沿处理完成（Done=FALSE）
        # 对于首次启动：Done 初始即为 FALSE → 立即通过（无下降沿需要处理）
        # 对于 back-to-back 启动：前一样品 await_stage_done 写 Enable=FALSE →
        # FSM 下降沿处理清除 Done → 本样品轮询检测到 Done=FALSE → 确认下降沿已处理 →
        # 写 Enable=TRUE 时 FSM 一定能检测到上升沿（_prev_enable 已被 FSM 更新为 False）
        if done_name in self._nodes:
            for _ in range(20):  # 最多 20 × 100ms = 2s
                try:
                    if not bool(await self._read(done_name)):
                        break
                except Exception:
                    break
                await asyncio.sleep(0.1)
            else:
                log.warning(
                    "[PLC] start_stage: %s_Done 清零超时（2s），FSM 下降沿可能未处理"
                    "（PLC 工程是否已升级到 v1.10？）",
                    stage,
                )

        # v1.8: 写-查-Enable 屏障 —— 用 read-back 替代固定 50ms sleep
        # 选取最后一个标量参数做验证；TCP 有序性保证：末尾参数已落地 ⟹ 所有先前参数已落地
        barrier_ok = await self._verify_params_barrier(params)
        if not barrier_ok:
            # 回退：验证失败或无可验证参数时，保留原 50ms 兜底
            await asyncio.sleep(0.05)

        async with self._lock:
            await self._write(enable_name, True)
        log.info("[PLC] start_stage: %s_Enable=TRUE params=%s barrier=%s", stage, params or {}, barrier_ok)

    async def await_stage_done(
        self,
        stage: str,
        *,
        on_step_change: Optional[Callable[[int], Awaitable[None]]] = None,
        timeout: float = 300.0,
        poll_interval: float = 0.15,
    ) -> None:
        """Phase A：轮询 <stage>_Step/_Done/_Error 直到完成或故障。

        - on_step_change(step): 可选回调，每当 _Step 值变化时被调用（用于 UI 镜像子步事件）
        - _Done=TRUE → 写 <stage>_Enable=FALSE 让 PLC 清 Done，然后返回
        - _Error=TRUE 或 _Step==90 → 抛 RuntimeError（不自动 Reset，由上层决策）
        - timeout 语义已变为「提示间隔」：超过该间隔仍未完成时发一次 warning + UI
          通知后**继续轮询**，不再抛 TimeoutError、也不主动清 Enable。调试场景下
          PLC 推进较慢时不再放弃样品；如需中止请走急停 / 任务取消路径（CancelledError）。
        """
        await self._await_connected()
        step_name = f"{stage}_Step"
        done_name = f"{stage}_Done"
        error_name = f"{stage}_Error"
        enable_name = f"{stage}_Enable"
        for n in (step_name, done_name, error_name, enable_name):
            if n not in NODE_TYPES:
                raise KeyError(f"未知工位：{stage}（{n} 不在 NODE_TYPES）")

        elapsed = 0.0
        next_warn_at = timeout       # 下一次提示的时间点（秒）
        last_step: Optional[int] = None
        while True:
            try:
                step_val = int(await self._read(step_name))
                done_val = bool(await self._read(done_name))
                err_val = bool(await self._read(error_name))
            except Exception:
                await self._await_connected()
                continue

            if step_val != last_step:
                if on_step_change is not None:
                    try:
                        await on_step_change(step_val)
                    except Exception as e:
                        log.warning("[PLC] on_step_change 回调异常: %s", e)
                last_step = step_val

            if err_val or step_val == 90:
                log.error("[PLC] await_stage_done: %s 进入故障态 (Step=%d Error=%s)",
                          stage, step_val, err_val)
                # 故障清理：写 Enable=FALSE + Confirm=FALSE 让 PLC FSM 归零
                try:
                    async with self._lock:
                        await self._write(enable_name, False)
                        # v1.7: 故障路径也清零 Confirm（防止乒乓等待步故障后 Confirm 残留）
                        confirm_name = f"{stage}_Confirm"
                        if confirm_name in NODE_TYPES and confirm_name in self._nodes:
                            await self._write(confirm_name, False)
                except Exception:
                    pass  # 清理失败不影响异常传播
                raise RuntimeError(
                    f"{stage} stage error (Step={step_val} Error={err_val})"
                )
            if done_val:
                async with self._lock:
                    await self._write(enable_name, False)   # 让 PLC 清 _Done
                    # v1.7: 主动清零 Confirm（不依赖 PLC 侧清零）
                    # 防止 Confirm 残留导致下次 confirm_stage 无上升沿
                    confirm_name = f"{stage}_Confirm"
                    if confirm_name in NODE_TYPES and confirm_name in self._nodes:
                        await self._write(confirm_name, False)
                log.info("[PLC] await_stage_done: %s 完成 (耗时 %.2fs)", stage, elapsed)
                return
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            # 长等待提示：每 timeout 秒发一次，不放弃样品
            if timeout > 0 and elapsed >= next_warn_at:
                _warn_long_wait(f"{stage} 工位", elapsed, timeout)
                next_warn_at += timeout

    async def await_stage_step(
        self,
        stage: str,
        target_step: int,
        *,
        on_step_change: Optional[Callable[[int], Awaitable[None]]] = None,
        timeout: float = 300.0,
        poll_interval: float = 0.15,
    ) -> None:
        """Phase B：轮询 <stage>_Step 直到到达 target_step，然后返回（不清 Enable/Done）。

        用于工位内部乒乓握手场景：PLC 在某个子步等待上位机确认信号，
        上位机先等待 Step 到达握手点，再下发确认，再调 await_stage_done。

        - on_step_change(step): 可选回调，每当 _Step 值变化时被调用
        - _Step == target_step → 直接返回（不做任何写入）
        - _Error=TRUE 或 _Step==90 → 抛 RuntimeError
        - timeout 语义已变为「提示间隔」：超过该间隔仍未到达 target_step 时发一次
          warning + UI 通知后**继续轮询**，不再抛 TimeoutError。
        """
        await self._await_connected()
        step_name = f"{stage}_Step"
        error_name = f"{stage}_Error"
        for n in (step_name, error_name):
            if n not in NODE_TYPES:
                raise KeyError(f"未知工位：{stage}（{n} 不在 NODE_TYPES）")

        # v1.7: WaitConfirm 联合校验——若工位声明了 WaitConfirm 变量，
        # 则返回条件从 Step==target 升级为 Step==target AND WaitConfirm==TRUE，
        # 消除 PLC 写 _Step 与进入 confirm 轮询之间的扫描周期窗口。
        wait_confirm_name = f"{stage}_WaitConfirm"
        has_wait_confirm = wait_confirm_name in NODE_TYPES

        elapsed = 0.0
        next_warn_at = timeout
        last_step: Optional[int] = None
        while True:
            try:
                step_val = int(await self._read(step_name))
                err_val = bool(await self._read(error_name))
                if has_wait_confirm:
                    wc_val = bool(await self._read(wait_confirm_name))
                else:
                    wc_val = False
            except Exception:
                await self._await_connected()
                continue

            if step_val != last_step:
                if on_step_change is not None:
                    try:
                        await on_step_change(step_val)
                    except Exception as e:
                        log.warning("[PLC] on_step_change 回调异常: %s", e)
                last_step = step_val

            if err_val or step_val == 90:
                log.error("[PLC] await_stage_step: %s 进入故障态 (Step=%d Error=%s)",
                          stage, step_val, err_val)
                raise RuntimeError(
                    f"{stage} stage error (Step={step_val} Error={err_val})"
                )
            # v1.7: 有 WaitConfirm 变量时需同时校验；无则仅校验 Step
            step_reached = step_val == target_step
            if has_wait_confirm:
                if step_reached and wc_val:
                    log.info(
                        "[PLC] await_stage_step: %s 到达 Step=%d + WaitConfirm=TRUE (耗时 %.2fs)",
                        stage, target_step, elapsed,
                    )
                    return
            elif step_reached:
                log.info("[PLC] await_stage_step: %s 到达 Step=%d (耗时 %.2fs)",
                         stage, target_step, elapsed)
                return
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if timeout > 0 and elapsed >= next_warn_at:
                _warn_long_wait(
                    f"{stage} 工位等待 Step={target_step}", elapsed, timeout,
                )
                next_warn_at += timeout

    async def confirm_stage(self, stage: str) -> None:
        """Phase B3：写 <stage>_Confirm=TRUE，让 PLC 从乒乓等待步继续推进。

        协议 v1.5：scrape 工位在 Step 20（拍照完成）等待 PC 侧确认后继续。
        PC 侧在完成视觉分析 + 下发 G-code 参数后调用本方法。
        PLC 侧消费 Confirm 后自动清零。

        v1.7 防御性校验：写 Confirm 前先读 WaitConfirm；若不为 TRUE 则 log.warning
        但仍写入（不阻断），兼容尚未声明 WaitConfirm 的工位。
        """
        confirm_name = f"{stage}_Confirm"
        if confirm_name not in NODE_TYPES:
            raise KeyError(f"未知工位 Confirm 变量：{confirm_name}（不在 NODE_TYPES）")
        await self._await_connected()

        # v1.7: WaitConfirm 防御性校验
        wait_confirm_name = f"{stage}_WaitConfirm"
        if wait_confirm_name in NODE_TYPES:
            try:
                wc_val = bool(await self._read(wait_confirm_name))
                if not wc_val:
                    log.warning(
                        "[PLC] confirm_stage: %s_WaitConfirm=FALSE（PLC 可能尚未进入等待循环），"
                        "仍写入 Confirm",
                        stage,
                    )
            except Exception as e:
                log.debug("[PLC] confirm_stage: 读 WaitConfirm 异常: %s", e)

        # 上升沿保障：先确保 FALSE，再写 TRUE（与 start_stage 同模式）
        async with self._lock:
            await self._write(confirm_name, False)
        await asyncio.sleep(0.05)  # 50ms 余量
        async with self._lock:
            await self._write(confirm_name, True)
        log.info("[PLC] confirm_stage: %s_Confirm=TRUE", stage)

    async def write_variable(self, name: str, value) -> None:
        """公共写接口，保证与 start_stage 使用同一把锁。

        供 UI Debug Tab 等场景直接写入单个 PLC 变量。
        支持 NODE_TYPES 预缓存节点 + 动态解析回退（与 read_variable 对称）。
        """
        await self._await_connected()
        async with self._lock:
            if name in self._nodes:
                await self._write(name, value)
            elif name in self._dynamic_nodes:
                node = self._dynamic_nodes[name]
                vtype = self._dynamic_types.get(name, NODE_TYPES.get(name, ua.VariantType.String))
                coerced = self._coerce_value(value, vtype)
                await node.write_value(ua.DataValue(ua.Variant(coerced, vtype)))
            else:
                # 动态解析回退
                node = await self._resolve_node(name)
                self._dynamic_nodes[name] = node
                vtype = NODE_TYPES.get(name, ua.VariantType.String)
                coerced = self._coerce_value(value, vtype)
                await node.write_value(ua.DataValue(ua.Variant(coerced, vtype)))

    async def read_variable(self, name: str, vtype: Optional[ua.VariantType] = None):
        """动态读取任意 PLC 变量（支持 NODE_TYPES 内的 + 动态查找的节点）。

        供 UI Debug Tab 等场景读取不在 NODE_TYPES 中的变量。
        动态查找的节点会缓存到 _dynamic_nodes 中避免重复查找。

        Args:
            name: 变量名（必须与 PLC 端 OPC UA 节点名一致）
            vtype: 变量类型（仅用于缓存；若为 None 则按 NODE_TYPES 查找或默认 Boolean）

        Returns:
            变量当前值

        Raises:
            ConnectionError: PLC 未连接
            KeyError: 节点未找到
        """
        await self._await_connected()
        # 优先从预缓存中读取
        if name in self._nodes:
            return await self._read(name)
        # 从动态缓存中读取
        if name in self._dynamic_nodes:
            node = self._dynamic_nodes[name]
            return await node.read_value()
        # 动态查找节点
        node = await self._resolve_node(name)
        self._dynamic_nodes[name] = node
        return await node.read_value()

    async def write_variable_dynamic(
        self, name: str, value, vtype: Optional[ua.VariantType] = None
    ) -> None:
        """动态写入任意 PLC 变量（支持 NODE_TYPES 内的 + 动态查找的节点）。

        与 write_variable 不同，此方法支持不在 NODE_TYPES 中的变量，
        通过 vtype 参数显式指定类型；若未指定则按 NODE_TYPES 查找或默认 Boolean。

        Args:
            name: 变量名
            value: 写入值
            vtype: 显式指定 VariantType（避免类型推断错误）
        """
        await self._await_connected()
        async with self._lock:
            # 预缓存节点走标准写入路径
            if name in NODE_TYPES:
                await self._write(name, value)
                return
            # 动态节点：查找 → 写入
            if name not in self._dynamic_nodes:
                node = await self._resolve_node(name)
                self._dynamic_nodes[name] = node
                self._dynamic_types[name] = vtype or ua.VariantType.Boolean
            node = self._dynamic_nodes[name]
            actual_type = self._dynamic_types.get(name, vtype or ua.VariantType.Boolean)
            await node.write_value(ua.DataValue(ua.Variant(value, actual_type)))

    async def _resolve_node(self, name: str):
        """动态查找 Host_Computer 下的变量节点（运行时按需）。

        查找路径：Objects → GVL_PATH 每层按 BrowseName 文本匹配 → Host_Computer → {name}
        """
        if self._client is None:
            raise ConnectionError("PLC 未连接")
        gvl = await resolve_gvl_node(self._client)
        try:
            node = await _find_child_by_name(gvl, name)
            log.info("[PLC] 动态节点已解析: %s", name)
            return node
        except KeyError as e:
            raise KeyError(
                f"PLC 节点 '{name}' 未找到（Host_Computer 下无此变量，路径 {'/'.join(GVL_PATH)}）"
            ) from e

    async def browse_plc_nodes(self) -> dict[str, ua.VariantType]:
        """浏览 PLC 对象下所有变量节点，返回 {name: VariantType}。

        供 UI "扫描 PLC 变量" 功能调用：一次性发现 PLC 端所有可访问变量。
        只浏览 PLC 对象下一层子节点，不递归。

        副作用：不在 NODE_TYPES 中的变量会自动缓存到 _dynamic_nodes / _dynamic_types，
        使得 poll_snapshot() 和 write_variable_dynamic() 可以直接使用。
        """
        await self._await_connected()
        if self._client is None:
            raise ConnectionError("PLC 未连接")
        gvl = await resolve_gvl_node(self._client)
        children = await gvl.get_children()
        result: dict[str, ua.VariantType] = {}
        new_count = 0
        for child in children:
            try:
                browse_name = await child.read_browse_name()
                name = browse_name.Name
                data_type = await child.read_data_type_as_variant_type()
                result[name] = data_type
                # 自动缓存不在 NODE_TYPES 中的变量
                if name not in NODE_TYPES and name not in self._dynamic_nodes:
                    self._dynamic_nodes[name] = child
                    self._dynamic_types[name] = data_type
                    new_count += 1
            except Exception:
                pass
        log.info("[PLC] 浏览发现 %d 个变量节点（%d 个新缓存）", len(result), new_count)
        return result

    async def poll_snapshot(self) -> dict:
        """批量读取所有 NODE_TYPES 变量 + 动态发现变量的当前值。

        供 VariableMonitor 轮询回退使用——当 asyncua 订阅通知不可靠时，
        定期调用此方法可保证快照与 PLC 实际值同步。
        不占锁，直接读取缓存节点。
        """
        if self._state != PLCState.CONNECTED or not self._nodes:
            return {}
        result = {}
        for name in NODE_TYPES:
            try:
                result[name] = await self._read(name)
            except Exception:
                pass
        # 也读取动态发现的节点
        for name, node in self._dynamic_nodes.items():
            if name in result:
                continue
            try:
                result[name] = await node.read_value()
            except Exception:
                pass
        return result

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def state(self) -> PLCState:
        return self._state

    @property
    def is_ok(self) -> bool:
        return self._state == PLCState.CONNECTED

    @property
    def reconnect_count(self) -> int:
        """累计成功重连次数（供稳定性统计）。"""
        return self._reconnect_count

    @property
    def client_session(self):
        """底层 asyncua.Client 实例（供 VariableMonitor 订阅等外部使用）。"""
        return self._client

    def get_all_variable_types(self) -> dict[str, str]:
        """返回所有已知变量的类型名映射 {name: "Boolean"/"Int32"/...}。

        合并 NODE_TYPES（静态已知变量）和 _dynamic_types（运行时发现的变量），
        供 UI variable_table 统一查询类型显示名。
        """
        result: dict[str, str] = {}
        for name, vtype in NODE_TYPES.items():
            result[name] = vtype.name
        for name, vtype in self._dynamic_types.items():
            if name not in result:
                result[name] = vtype.name
        return result

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def add_state_listener(self, cb: StateChangeCallback) -> None:
        """注册状态变更监听（支持多订阅：Scheduler / UI 可同时监听）。"""
        self._state_listeners.append(cb)

    async def _set_state(self, state: PLCState) -> None:
        if state == self._state:
            return
        old = self._state
        self._state = state
        log.info("[PLC] 状态迁移: %s → %s", old.value, state.value)
        for cb in list(self._state_listeners):
            try:
                await cb(state)
            except Exception as e:
                log.warning("[PLC] 状态监听回调异常: %s", e)

    async def _await_connected(self) -> None:
        """阻塞等待进入 CONNECTED 态；超时或进入 ERROR 时抛 ConnectionError。"""
        if self._state == PLCState.CONNECTED:
            return
        if self._state == PLCState.ERROR:
            raise ConnectionError("PLC 处于 ERROR 态，无法继续")
        if self._state == PLCState.DISCONNECTED:
            raise ConnectionError("PLC 未连接")
        # RECONNECTING：等待事件
        log.warning("[PLC] 当前处于 RECONNECTING，阻塞等待恢复（最多 %.1fs）", self._reconnect_wait_timeout)
        try:
            await asyncio.wait_for(
                self._connected_evt.wait(),
                timeout=self._reconnect_wait_timeout,
            )
        except asyncio.TimeoutError as e:
            raise ConnectionError(
                f"等待 PLC 重连超时（{self._reconnect_wait_timeout}s）"
            ) from e

    async def _cache_nodes(self) -> None:
        """连接后 browse Host_Computer 下所有变量并缓存。

        策略（自适应，PLC 侧 Host_Computer 可自由增删，上位机零修改）：
          - 枚举 Host_Computer 下所有子节点，按 BrowseName.Name 建索引；
          - 命中 NODE_TYPES 的 → 存入 self._nodes（业务路径，写入用 NODE_TYPES 显式类型）；
          - PLC 有但 NODE_TYPES 未声明的 → 存入 self._dynamic_nodes / _dynamic_types（UI 扫描变量可见）；
          - NODE_TYPES 声明但 PLC 缺失的 → 仅 WARN，不再视为连接失败；
            相关业务（视觉、recipe、collect）若调用到这些变量，会在调用时明确报错。
        """
        gvl = await resolve_gvl_node(self._client)
        children = await gvl.get_children()
        plc_vars: dict[str, object] = {}
        plc_types: dict[str, ua.VariantType] = {}
        for child in children:
            try:
                bn = await child.read_browse_name()
                name = bn.Name
                plc_vars[name] = child
                try:
                    plc_types[name] = await child.read_data_type_as_variant_type()
                except Exception:
                    pass
            except Exception as e:
                log.debug("[PLC] 浏览 Host_Computer 子节点失败（跳过）: %s", e)

        # 分流：NODE_TYPES 命中 vs 动态变量
        missing: list[str] = []
        for name in NODE_TYPES:
            if name in plc_vars:
                self._nodes[name] = plc_vars[name]
            else:
                missing.append(name)
        for name, node in plc_vars.items():
            if name in NODE_TYPES:
                continue
            self._dynamic_nodes[name] = node
            if name in plc_types:
                self._dynamic_types[name] = plc_types[name]

        log.info(
            "[PLC] 节点缓存完成: Host_Computer 共 %d 变量（命中 NODE_TYPES %d 个；动态 %d 个）",
            len(plc_vars), len(self._nodes), len(self._dynamic_nodes),
        )
        if missing:
            log.warning(
                "[PLC] NODE_TYPES 声明但 PLC 端未发现的变量: %s（调用相关业务时会报错）",
                ", ".join(missing),
            )

        # CNC 主方案版本自检：缺一即视为 PLC 工程未升级，提前 ERROR 而非
        # 延迟到 _write_array 抛 KeyError
        missing_cnc = [v for v in REQUIRED_SCRAPE_CNC_VARS if v not in self._nodes]
        if missing_cnc:
            log.error(
                "[PLC] CNC 接口变量缺失 %d 个: %s。"
                "PLC 工程可能未升级至支持 ScrapeCNC 的版本，"
                "ScrapeStage / Debug Tab CNC 面板 / test_cnc_e2e.py 在写入时会报错。",
                len(missing_cnc), ", ".join(missing_cnc),
            )

        # 协议 v2.3 耗材管理版本自检
        missing_consumable = [v for v in REQUIRED_CONSUMABLE_VARS if v not in self._nodes]
        if missing_consumable:
            log.error(
                "[PLC] 耗材管理变量缺失 %d 个: %s。"
                "PLC 工程可能未升级至支持 v2.3 耗材协议，"
                "ConsumableManager 传感器同步与 Stage 参数写入时会报错。",
                len(missing_consumable), ", ".join(missing_consumable),
            )

    async def _read(self, name: str):
        node = self._nodes[name]
        return await node.read_value()

    async def _write_array(self, name: str, values: list) -> None:
        """整体写入数值数组节点（如 g_sx/g_sy/g_cx/g_cy）。

        与 write_string_array 同模式，但：
          - 用于数值类型（Double / Int16 / Int32），支持 g_sx/g_sy 等 LREAL 数组
          - 长度不足声明维度时末尾补 0；超出时截断
          - 必须显式带 VariantType 包装，避免 asyncua 推断为错误类型
        """
        array_len = NODE_ARRAYS.get(name)
        if array_len is None:
            raise KeyError(f"未知数组变量: {name}（不在 NODE_ARRAYS）")
        if name not in self._nodes:
            # 动态解析回退：与标量写入路径对齐，修复"_cache_nodes 未命中但 PLC 实际暴露"的场景
            if name not in self._dynamic_nodes:
                try:
                    node = await self._resolve_node(name)
                    self._dynamic_nodes[name] = node
                    log.info("[PLC] 动态解析数组节点: %s（_cache_nodes 未命中，回退成功）", name)
                except KeyError:
                    raise KeyError(
                        f"PLC 节点 '{name}' 未缓存且动态解析也失败（PLC 端 OPC UA 命名空间可能未暴露此变量，"
                        f"请检查 PLC 程序是否已编译下载、Host_Computer 变量是否勾选 OPC UA 可见）"
                    )
            node = self._dynamic_nodes[name]
        else:
            node = self._nodes[name]
        vtype = NODE_TYPES.get(name, ua.VariantType.Double)
        # 按声明维度补齐/截断；填充值按类型选择
        pad_value = 0 if vtype in (
            ua.VariantType.Int16, ua.VariantType.Int32, ua.VariantType.UInt16
        ) else (False if vtype == ua.VariantType.Boolean else 0.0)
        normalized = [self._coerce_value(v, vtype) for v in values[:array_len]]
        normalized += [pad_value] * max(0, array_len - len(normalized))
        try:
            await node.write_value(ua.DataValue(ua.Variant(normalized, vtype)))
        except ua.UaStatusCodeError as e:
            log.error(
                "[PLC] _write_array 失败 node=%s vtype=%s len=%d status=0x%08X (%s)",
                name, vtype.name, len(normalized),
                getattr(e, "code", 0) & 0xFFFFFFFF,
                e.__class__.__name__,
            )
            raise

    async def _write(self, name: str, value) -> None:
        node = self._nodes[name]
        vtype = NODE_TYPES[name]
        try:
            await node.write_value(ua.DataValue(ua.Variant(value, vtype)))
        except ua.UaStatusCodeError as e:
            # 调试增强：精确暴露 BadNotWritable / BadOutOfRange / BadTypeMismatch 等节点级错误
            # 关键信息：节点名 + VariantType + 值长度（String 场景）+ OPC UA 状态码
            value_len = len(value) if isinstance(value, (str, bytes, list, tuple)) else None
            log.error(
                "[PLC] _write 失败 node=%s vtype=%s value_len=%s status=0x%08X (%s)",
                name, vtype.name, value_len,
                getattr(e, "code", 0) & 0xFFFFFFFF,
                e.__class__.__name__,
            )
            raise

    # ------------------------------------------------------------------
    # 数组节点辅助方法（协议 v1.3 多通道展开）
    # ------------------------------------------------------------------

    async def read_tank_array(self, name: str, tank_id: int):
        """读取数组节点的第 tank_id 个元素（1-based 索引）。"""
        values = await self._read(name)
        return values[tank_id - 1]

    async def write_tank_element(self, name: str, tank_id: int, value) -> None:
        """写入数组节点的第 tank_id 个元素（1-based 索引，读-改-写策略）。

        竞争安全：仅修改目标索引，不改变其他元素。
        PC 写入仅发生在 release(Done→0) 场景，此时 PLC 不再推进该缸状态。
        """
        await self._await_connected()
        async with self._lock:
            arr = list(await self._read(name))
            vtype = NODE_TYPES[name]
            arr[tank_id - 1] = self._coerce_value(value, vtype)
            node = self._nodes[name]
            await node.write_value(ua.DataValue(ua.Variant(arr, vtype)))

    async def read_tank_state(self, tank_id: int) -> int:
        """读取 Tank_State[tank_id]（1-based）。"""
        return int(await self.read_tank_array("Tank_State", tank_id))

    async def write_tank_state(self, tank_id: int, value: int) -> None:
        """写入 Tank_State[tank_id]（1-based，读-改-写）。"""
        await self.write_tank_element("Tank_State", tank_id, value)

    async def read_all_tank_states(self) -> list[int]:
        """一次读取全部 Tank_State 数组（1次网络往返）。"""
        values = await self._read("Tank_State")
        return [int(v) for v in values]

    async def trigger_drain(self, tank_id: int) -> None:
        """触发排液：写 Tank_Drain_Enable[tank_id]=TRUE。"""
        await self.write_tank_element("Tank_Drain_Enable", tank_id, True)
        log.info("[PLC] 触发排液: Tank_Drain_Enable[%d]=TRUE", tank_id)

    async def await_drain_done(self, tank_id: int, timeout: float = 300.0,
                                poll_interval: float = 0.5) -> None:
        """轮询等待 Tank_Drain_Done[tank_id]=TRUE。

        timeout 语义已变为「提示间隔」：超过该间隔仍未完成时发一次 warning + UI
        通知后**继续轮询**，不再抛 TimeoutError、不放弃样品。调试场景下排液偏慢时
        样品不会被误判为 ERROR；如需中止请走急停 / 任务取消路径（CancelledError）。
        """
        await self._await_connected()
        elapsed = 0.0
        next_warn_at = timeout
        while True:
            try:
                done = bool(await self.read_tank_array("Tank_Drain_Done", tank_id))
            except Exception:
                await self._await_connected()
                continue
            if done:
                log.info("[PLC] 排液完成: Tank_Drain_Done[%d]=TRUE (%.1fs)", tank_id, elapsed)
                return
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if timeout > 0 and elapsed >= next_warn_at:
                _warn_long_wait(f"展缸 {tank_id} 号排液", elapsed, timeout)
                next_warn_at += timeout

    async def release_tank(self, tank_id: int) -> None:
        """释放展缸：清排液信号 + Tank_State[tank_id]=0。"""
        await self.write_tank_element("Tank_Drain_Enable", tank_id, False)
        await self.write_tank_state(tank_id, 0)
        log.info("[PLC] 释放展缸: Tank_State[%d]=0, Drain_Enable[%d]=FALSE", tank_id, tank_id)

    async def read_consumable_sensor(self) -> list[bool]:
        """读 IX11/IX12 两个 BYTE → 按位解码为 12 元素 list[bool]。

        协议 v2.3（再修订）适配层：PLC 工程未按 ARRAY[1..12] OF BOOL 暴露，
        而是打包为 2 个 BYTE（`%IX11` / `%IX12`）。本方法封装位解码，
        调用者（ui/app.py polling）拿到的仍是与原 `Consumable_Sensor` 同义的
        list[bool, 12]，ConsumableManager.sync_plate_presence() 接口不变。

        映射（CODESYS 标准 LSB 位序，详见 docs/PLC_Engineer_Handover_Core.md §3.4）：
            result[0]  = IX11 bit0  (%IX11.0)  料库检测1   粉末板1
            result[1]  = IX11 bit1  (%IX11.1)  料库检测2   粉末板2
            result[2]  = IX11 bit2  (%IX11.2)  料库检测3   粉末板3
            result[3]  = IX11 bit3  (%IX11.3)  料库检测4   粉末板4
            result[4]  = IX11 bit4  (%IX11.4)  料库检测5   粉末板5
            result[5]  = IX11 bit5  (%IX11.5)  料库检测6   粉末板6
            result[6]  = IX11 bit6  (%IX11.6)  料库检测7   玻璃瓶板1
            result[7]  = IX11 bit7  (%IX11.7)  料库检测8   玻璃瓶板2
            result[8]  = IX12 bit0  (%IX12.0)  料库检测9   玻璃瓶板3
            result[9]  = IX12 bit1  (%IX12.1)  料库检测10  玻璃瓶板4
            result[10] = IX12 bit2  (%IX12.2)  料库检测11  玻璃瓶板5
            result[11] = IX12 bit3  (%IX12.3)  料库检测12  玻璃瓶板6
        【IX12 bit4..bit7 保留位丢弃】

        Returns:
            list[bool] 长度 12，TRUE=在位 / FALSE=不在位
        """
        ix11 = int(await self.read_variable("IX11"))
        ix12 = int(await self.read_variable("IX12"))
        result: list[bool] = [bool((ix11 >> i) & 1) for i in range(8)]
        result.extend(bool((ix12 >> i) & 1) for i in range(4))
        return result

    async def write_string_array(self, name: str, values: list[str]) -> None:
        """整体写入 STRING 数组节点（1 次网络往返）。

        用途：启动工位前一次性写入变长指令序列（如 Sampling_prep_instructions）。
        数组长度不足 NODE_ARRAYS[name] 时，末尾补空字符串；超出时截断。
        """
        await self._await_connected()
        array_len = NODE_ARRAYS.get(name)
        if array_len is None:
            raise KeyError(f"未知数组变量: {name}（不在 NODE_ARRAYS）")
        vtype = NODE_TYPES.get(name, ua.VariantType.String)
        # 补齐或截断到声明长度
        padded = list(values[:array_len]) + [""] * max(0, array_len - len(values))
        async with self._lock:
            if name not in self._nodes:
                raise KeyError(
                    f"PLC 节点 '{name}' 未缓存（PLC 端 OPC UA 命名空间可能未暴露此变量，"
                    f"请检查 PLC 程序是否已编译下载、Host_Computer 变量是否勾选 OPC UA 可见）"
                )
            node = self._nodes[name]
            await node.write_value(ua.DataValue(ua.Variant(padded, vtype)))
        log.info("[PLC] write_string_array: %s (%d 条指令写入)", name, len(values))

    async def _heartbeat_loop(self) -> None:
        """每 100 ms 读一次心跳节点；同步检测 ESTOP_NODE=PLC_EStop 上升沿。

        心跳失败计数 ≥ HEARTBEAT_MAX_FAIL → 切 RECONNECTING 并启动重连。

        容错策略（v1.6.1）：
          - KeyError（节点未缓存 / PLC 工程未暴露）不触发重连，自动降级到任意可用节点；
          - 仅 OPC UA 网络异常（BadConnectionClosed / Timeout 等）才计入失败计数；
          - 降级时打一次 WARNING，后续不再重复刷屏。
        """
        _fallback_warned = False   # 降级提示只打一次
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                # ── 心跳活检：优先 HEARTBEAT_NODE，缺失则降级到任意已缓存节点 ──
                try:
                    _ = await self._read(HEARTBEAT_NODE)
                except KeyError:
                    # 节点不在 self._nodes（PLC 工程未暴露），尝试降级
                    fallback_node = next(iter(self._nodes), None)
                    if fallback_node is None:
                        # _nodes 为空，再尝试 _dynamic_nodes
                        fallback_node = next(iter(self._dynamic_nodes), None)
                    if fallback_node is None:
                        # Host_Computer 完全空，视为连接异常
                        raise RuntimeError("Host_Computer 下无任何可用节点")
                    if not _fallback_warned:
                        log.warning(
                            "[PLC] 心跳节点 '%s' 未缓存，降级读取 '%s'（PLC 工程可能未包含该变量）",
                            HEARTBEAT_NODE, fallback_node,
                        )
                        _fallback_warned = True
                    # 降级节点走直接 OPC UA read，绕过 _nodes 索引
                    node_obj = self._nodes.get(fallback_node) or self._dynamic_nodes.get(fallback_node)
                    if node_obj is not None:
                        await node_obj.read_value()
                    else:
                        raise RuntimeError(f"降级节点 '{fallback_node}' 对象丢失")

                self._hb_fail_count = 0
                # ── 急停边沿检测——PLC_EStop ──
                try:
                    estop = bool(await self._read(ESTOP_NODE))
                except (KeyError, Exception):
                    estop = False
                if estop and not self._prev_estop:
                    log.error("[PLC] 检测到急停信号 PLC_EStop=True（上升沿）")
                    if self._on_estop is not None:
                        try:
                            asyncio.create_task(self._on_estop())
                        except Exception as e:
                            log.warning("[PLC] on_estop 回调调度失败: %s", e)
                self._prev_estop = estop

            except KeyError as e:
                # 节点缺失（不应到达此处，上面已处理）——安全兜底，不触发重连
                if not _fallback_warned:
                    log.warning("[PLC] 心跳节点缺失（不触发重连）: %s", e)
                    _fallback_warned = True

            except Exception as e:
                # OPC UA 网络层异常 → 真正的连接故障
                self._hb_fail_count += 1
                log.warning(
                    "[PLC] 心跳失败 (%d/%d): %s",
                    self._hb_fail_count, HEARTBEAT_MAX_FAIL, e,
                )
                if self._hb_fail_count >= HEARTBEAT_MAX_FAIL:
                    log.error(
                        "[PLC] 心跳连续失败 %d 次，进入 RECONNECTING 态",
                        HEARTBEAT_MAX_FAIL,
                    )
                    self._connected_evt.clear()
                    await self._set_state(PLCState.RECONNECTING)
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())
                    return

    async def _reconnect_loop(self) -> None:
        """指数退避重连；成功后恢复 CONNECTED 并重启心跳。"""
        attempt = 0
        # 先尝试释放旧 client
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        while True:
            backoff = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log.info("[PLC] 重连尝试 #%d，退避 %.1fs", attempt, backoff)
            await asyncio.sleep(backoff)
            try:
                self._client = Client(self._url)
                await self._client.connect()
                await self._cache_nodes()
            except Exception as e:
                log.warning("[PLC] 重连失败（#%d）: %s", attempt, e)
                if self._client is not None:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                continue

            # 重连成功
            self._hb_fail_count = 0
            self._prev_estop = False
            self._reconnect_count += 1
            await self._set_state(PLCState.CONNECTED)
            self._connected_evt.set()
            log.info("[PLC] 重连成功（累计 %d 次）", self._reconnect_count)
            self._hb_task = asyncio.create_task(self._heartbeat_loop())
            self._reconnect_task = None
            return
