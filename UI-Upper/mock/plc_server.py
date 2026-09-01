"""
Mock OPC UA PLC Server
======================
模拟汇川 PLC 的 OPC UA 服务器，用于本地联调。

功能：
- 暴露 plan.md 中定义的所有控制变量节点（全部可写，便于调试）
- 协议 v1.1：删除 Recipe_Param_A..F / I1..I4 / Gcode_Name / Mode_Flag 通用抽象，
  collect 工位参数改为 collect_forward_instructions / collect_count 业务直名。
- collect / develop / spotting / scrape 工位走 StageFSM，同时派生工位_Busy；PLC_Busy 由独立聚合协程单写。
- 交互式控制台：手动设置任意 PLC 变量，模拟异常场景
- 可配置自动完成延时、禁用自动完成（测试超时）

启动方式：
    python mock/plc_server.py                     # 默认 0.5s 自动完成
    python mock/plc_server.py --delay 2.0         # 2 秒自动完成
    python mock/plc_server.py --no-auto           # 禁用自动完成（手动控制）
    python mock/plc_server.py --port 4841         # 自定义端口
"""


import argparse
import asyncio
import logging
import os
import random
import sys
from typing import Optional

from asyncua import Server, ua

# 允许作为脚本直接运行（python mock/plc_server.py）时找到 core 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Phase C：旧握手通道变量已删除（Action_ID / PC_Trigger / PLC_Done / PLC_Error），
# 上位机不再使用旧握手路径。PLC_Busy 保留（BusyAggregator 单写，维持实机同构）。

logging.basicConfig(
    level=logging.INFO,
    format="[MockPLC] %(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
# 压低 asyncua 子 logger 的级别，避免上位机高频轮询刷屏终端，
# 保持交互式控制台可输入 error/reset/status 等命令。
logging.getLogger("asyncua").setLevel(logging.WARNING)
log = logging.getLogger("mock_plc")

SERVER_URL = "opc.tcp://localhost:4840"
NAMESPACE = "urn:ptlc:plc"

# 变量名 → (默认值, VariantType) 用于 reset 命令
# 协议 v1.1：删除 Recipe_Param_A..F / I1..I4 / Recipe_Gcode_Name / Recipe_Mode_Flag
VAR_DEFAULTS_LIST = [
    # 旧握手通道（Phase C：Action_ID / PC_Trigger / PLC_Done / PLC_Error 已删除）
    # PLC_Busy 保留：BusyAggregator 单写，维持与实机同构行为
    ("PLC_Busy",        (False, ua.VariantType.Boolean)),   # BusyAggregator 单写
    # Vision_Done / Vision_Result_X/Y 已删除（v1.5：scrape 电平范式替代旧乒乓通道）
    # 调试辅助（Batch 7）
    ("Test_BOOL",       (False, ua.VariantType.Boolean)),
    ("UV_Lamp",         (False, ua.VariantType.Boolean)),
    ("Motor_Run",       (False, ua.VariantType.Boolean)),
    ("Solenoid_Valve",  (False, ua.VariantType.Boolean)),
    # ── 协议 v1.1：collect 工位六件套 + 业务参数 ──
    # 契约见 docs/PLC_Unified_Stage_Protocol.md
    ("collect_Enable",                (False, ua.VariantType.Boolean)),
    ("collect_Step",                  (0,     ua.VariantType.Int16)),      # 实机 PLC 声明为 INT（Int16）
    ("collect_Done",                  (False, ua.VariantType.Boolean)),
    ("collect_Error",                 (False, ua.VariantType.Boolean)),
    ("collect_Reset",                 (False, ua.VariantType.Boolean)),
    ("collect_Busy",                  (False, ua.VariantType.Boolean)),   # v1.1: 工位独立 _Busy
    ("collect_forward_instructions",  ("",    ua.VariantType.String)),    # v1.1: 注射泵转发指令
    ("collect_count",                 (0,     ua.VariantType.Int16)),      # 実机 PLC 声明为 INT（Int16）
    # ── 协议 v1.2→v1.3：develop（展开）工位六件套 + 业务参数 ──
    # PLC 变量前缀 Expand，契约见 docs/PLC_Unified_Stage_Protocol.md §7
    ("Expand_Enable",                          (False, ua.VariantType.Boolean)),
    ("Expand_Step",                            (0,     ua.VariantType.Int16)),      # 実机 PLC 声明为 INT（Int16）
    ("Expand_Done",                            (False, ua.VariantType.Boolean)),
    ("Expand_Error",                           (False, ua.VariantType.Boolean)),
    ("Expand_Reset",                           (False, ua.VariantType.Boolean)),
    ("Expand_Busy",                            (False, ua.VariantType.Boolean)),
    # Expand_Confirm 已废弃（v1.3）：排液由 Tank_Drain_Enable[i] 替代
    ("Expand_Mode_Flag",                       (0,     ua.VariantType.Int16)),
    ("Expand_Group",                           (0,     ua.VariantType.Int16)),      # PLC 自动推导
    ("Expand_Number",                          (0,     ua.VariantType.Int16)),      # PLC 自动推导
    ("Expand_forward_instructions",            ("",    ua.VariantType.String)),    # 注射泵转发指令
    # ── 协议 v1.3：多通道展开 - 展缸状态跟踪（真数组节点）──
    ("Tank_State",         ([0]*8,  ua.VariantType.Int16)),     # ARRAY[1..8] OF INT
    ("Tank_SampleID",      ([0]*8,  ua.VariantType.Int32)),     # ARRAY[1..8] OF DINT
    ("Tank_Drain_Enable",  ([False]*8, ua.VariantType.Boolean)), # ARRAY[1..8] OF BOOL
    ("Tank_Drain_Done",    ([False]*8, ua.VariantType.Boolean)), # ARRAY[1..8] OF BOOL
    # ── 协议 v1.3：目标缸号（标量）──
    ("Expand_Target_Tank", (0,     ua.VariantType.Int16)),      # INT 1-8
    ("Expand_rinse_count",  (1,     ua.VariantType.Int16)),      # 润洗注射泵重复次数
    ("Expand_up_liquid_count", (1,  ua.VariantType.Int16)),      # 上液注射泵重复次数
    # ── 协议 v1.4：spotting（上样点样）工位六件套 + 业务参数 ──
    # PLC 变量前缀 Sampling（实机 Host_Computer 命名），契约见 docs/PLC_Unified_Stage_Protocol.md §6
    ("Sampling_Enable",                 (False, ua.VariantType.Boolean)),
    ("Sampling_Step",                   (0,     ua.VariantType.Int16)),
    ("Sampling_Done",                   (False, ua.VariantType.Boolean)),
    ("Sampling_Error",                  (False, ua.VariantType.Boolean)),
    ("Sampling_Reset",                  (False, ua.VariantType.Boolean)),
    ("Sampling_Busy",                   (False, ua.VariantType.Boolean)),
    ("Sampling_clean_instructions",     ([""]*2, ua.VariantType.String)),   # ARRAY[1..2] 清洗 [内壁, 外壁]（Step 10）
    ("Sampling_clean_count",            (0,     ua.VariantType.Int16)),     # 清洗次数
    # 协议 v1.5 4 数组重构：bubble_instructions 拆分为 prep + sample + dispense 三个 1×2 数组
    ("Sampling_prep_instructions",      ([""]*2, ua.VariantType.String)),   # ARRAY[1..2] 上样准备 [吸取空气, 废液打出]（Step 20）
    ("Sampling_X_coordinate",           (0,     ua.VariantType.Int16)),     # 上样 X 坐标
    ("Sampling_Y_coordinate",           (0,     ua.VariantType.Int16)),     # 上样 Y 坐标
    ("Sampling_sample_instructions",    ([""]*2, ua.VariantType.String)),   # ARRAY[1..2] 上样 [回抽样品, 废液排废]（Step 40）
    ("Sampling_dispense_instructions",  ([""]*2, ua.VariantType.String)),   # ARRAY[1..2] 点样 [抽取空气, 打气点样]（Step 50）
    # Sampling L2 atomic-action channel. ControlMode defaults to LEGACY.
    ("Sampling_ControlMode",             (0,     ua.VariantType.Int16)),
    ("Sampling_L2_ActionCode",           (0,     ua.VariantType.Int16)),
    ("Sampling_L2_RequestSeq",           (0,     ua.VariantType.Int32)),
    ("Sampling_L2_Start",                (False, ua.VariantType.Boolean)),
    ("Sampling_L2_Reset",                (False, ua.VariantType.Boolean)),
    ("Sampling_L2_State",                (0,     ua.VariantType.Int16)),
    ("Sampling_L2_ActiveCode",           (0,     ua.VariantType.Int16)),
    ("Sampling_L2_AcceptedSeq",          (0,     ua.VariantType.Int32)),
    ("Sampling_L2_CompletedSeq",         (0,     ua.VariantType.Int32)),
    ("Sampling_L2_Step",                 (0,     ua.VariantType.Int16)),
    ("Sampling_L2_ErrorCode",            (0,     ua.VariantType.Int16)),
    ("Sampling_L2_SafeState",            (0,     ua.VariantType.Int16)),
    ("Sampling_L2_Retryable",            (False, ua.VariantType.Boolean)),
    # Rail (地轨轴11Y) L2 servo atomic-action channel. 地轨到站前置动作, 无 ControlMode/SafeState 前置。
    ("Rail_L2_ActionCode",               (0,     ua.VariantType.Int16)),
    ("Rail_L2_RequestSeq",               (0,     ua.VariantType.Int32)),
    ("Rail_L2_Start",                    (False, ua.VariantType.Boolean)),
    ("Rail_L2_Reset",                    (False, ua.VariantType.Boolean)),
    ("Rail_L2_State",                    (0,     ua.VariantType.Int16)),
    ("Rail_L2_ActiveCode",               (0,     ua.VariantType.Int16)),
    ("Rail_L2_AcceptedSeq",              (0,     ua.VariantType.Int32)),
    ("Rail_L2_CompletedSeq",             (0,     ua.VariantType.Int32)),
    ("Rail_L2_Step",                     (0,     ua.VariantType.Int16)),
    ("Rail_L2_ErrorCode",                (0,     ua.VariantType.Int16)),
    ("Rail_L2_SafeState",                (0,     ua.VariantType.Int16)),
    ("Rail_L2_Retryable",                (False, ua.VariantType.Boolean)),
    # ── 协议 v1.5：scrape（拍照刮板）工位六件套 + 业务参数 ──
    # 契约见 docs/PLC_Unified_Stage_Protocol.md §8
    ("scrape_Enable",               (False, ua.VariantType.Boolean)),
    ("scrape_Step",                 (0,     ua.VariantType.Int16)),     # 実机 PLC 声明为 INT（Int16）
    ("scrape_Done",                 (False, ua.VariantType.Boolean)),
    ("scrape_Error",                (False, ua.VariantType.Boolean)),
    ("scrape_Reset",                (False, ua.VariantType.Boolean)),
    ("scrape_Busy",                 (False, ua.VariantType.Boolean)),  # v1.5: 工位独立 _Busy
    ("scrape_Confirm",              (False, ua.VariantType.Boolean)),  # v1.5: 乒乓确认信号
    ("scrape_WaitConfirm",          (False, ua.VariantType.Boolean)),  # v1.7: PLC 侧显式就绪信号
    ("scrape_gcode_instructions",   ("",    ua.VariantType.String)),   # v1.5: G-code 指令（CNC 主方案接入后保留兼容写空）
    ("scrape_PhotoMode",            (0,     ua.VariantType.Int16)),     # v1.6: 0=完整刮板, 1=仅before-photo
    # 诊断用单向变量（PC→PLC）：scrape 对应的展缸号，0=未关联（重刮 / collect-only）
    ("scrape_Source_Tank",          (0,     ua.VariantType.Int16)),
    # ── CNC 主方案：Host_Computer/ScrapeCNC 点位数组 + 标量参数 ──
    # 契约见 docs/PLC_ScrapeCNC_Interface.md，模板见 CNCTest/scrape_template_v2.cnc
    ("g_sx",              ([0.0]*400, ua.VariantType.Float)),             # ARRAY[1..400] OF REAL
    ("g_sy",              ([0.0]*400, ua.VariantType.Float)),             # ARRAY[1..400] OF REAL
    ("g_cx",              ([0.0]*400, ua.VariantType.Float)),             # ARRAY[1..400] OF REAL
    ("g_cy",              ([0.0]*400, ua.VariantType.Float)),             # ARRAY[1..400] OF REAL
    ("g_safe_z",          (5.0,   ua.VariantType.Float)),                 # REAL 安全高度 mm
    ("g_approach_z",      (6.5,   ua.VariantType.Float)),                 # REAL 接近高度 mm
    ("g_pass_z",          (8.0,   ua.VariantType.Float)),                 # REAL 当前 pass 深度 mm
    ("g_pass_count",      (0,     ua.VariantType.Int16)),                 # INT pass 次数（0=占位）
    ("g_total_depth",     (1.0,   ua.VariantType.Float)),                 # REAL 总深度 mm
    ("g_plate_surface_z", (7.0,   ua.VariantType.Float)),                 # REAL 板面 Z 基准 mm
    ("g_scrape_feed",     (800,   ua.VariantType.Int16)),                 # INT 刮扫进给 mm/min
    ("g_plunge_feed",     (200,   ua.VariantType.Int16)),                 # INT 下刀进给 mm/min
    # ── 协议 v2.5（动作码协议升级）：耗材管理（PC→PLC 决策参数）──
    # v2.5 动作码：暂存区无传感器，PC 账本显式告知 PLC 动作（0=NONE / 1=PUT_NEW / 2=SWAP）
    ("scrape_Plate_Op",          (0,     ua.VariantType.Int16)),             # 0=NONE/1=PUT_NEW/2=SWAP
    ("scrape_Fetch_Rack_Plate",  (0,     ua.VariantType.Int16)),             # 0=不搬, 1-12=搬板到暂存A
    ("scrape_Old_Plate_Slot",    (0,     ua.VariantType.Int16)),             # 0 或 1-12（仅 op=SWAP）
    ("scrape_Consume_Slot",      (0,     ua.VariantType.Int16)),             # 1-6=从暂存A取该孔
    ("collect_Plate_Op",         (0,     ua.VariantType.Int16)),             # 同 scrape_Plate_Op
    ("collect_Fetch_Rack_Plate", (0,     ua.VariantType.Int16)),             # 0=不搬, 1-12=搬板到暂存B
    ("collect_Old_Plate_Slot",   (0,     ua.VariantType.Int16)),             # 0 或 1-12（仅 op=SWAP）
    ("collect_Consume_Slot",     (0,     ua.VariantType.Int16)),             # 1-6=从暂存B取该孔
    ("collect_Powder_Return_Slot", (0,   ua.VariantType.Int16)),             # v2.4：粉末收集器归还暂存A 原始孔号（1-6）
    # 协议 v2.3（再修订）：耗材架板级 DI 改为 2 BYTE打包，IX11.bit0..bit7=检测1..8、IX12.bit0..bit3=检测9..12
    # 默认：满架 → IX11=0xFF（8 位全 1） / IX12=0x0F（低 4 位全 1，高 4 位保留=0）
    # （旧 ARRAY[1..12] OF BOOL `Consumable_Sensor` 节点已废弃，mock 不再创建）
    ("IX11",                     (0xFF,  ua.VariantType.Byte)),               # %IX11 BYTE【6 粉末 + 2 玻璃瓶】
    ("IX12",                     (0x0F,  ua.VariantType.Byte)),               # %IX12 BYTE【4 玻璃瓶 + 4 位保留】
    # 全局急停（上升沿触发上位机 on_estop）
    ("PLC_EStop",       (False, ua.VariantType.Boolean)),
    # ── 实机 PLC Host_Computer 额外变量（b 前缀）──
    ("bOutput",         (False, ua.VariantType.Boolean)),
    ("bEnable",         (True,  ua.VariantType.Boolean)),
    ("bErrorReset",     (False, ua.VariantType.Boolean)),
    ("bStepEnable",     (True,  ua.VariantType.Boolean)),
]
_VAR_DEFAULTS = dict(VAR_DEFAULTS_LIST)


# Phase A StageFSM 默认轨迹：(子步号, 停留秒数)
# collect 契约：0 → 10(prepare) → 20(collecting) → 30(transfer) → 0 + _Done=TRUE
STAGE_FSM_TRACE_DEFAULT = [(10, 2.0), (20, 3.0), (30, 2.0)]

# Phase B1→v1.3：develop（展开）工位轨迹
# 子步 35 已废弃（乒乓握手删除），Step 40 = 交付至展开态（立即 Done）
DEVELOP_FSM_TRACE = [(10, 2.0), (20, 3.0), (30, 2.0), (40, 0)]

# Phase B2→v1.4：spotting（上样点样）工位轨迹
# 子步对齐 PLC 侧 上样点样流程 {0,10,20,30,40,50}
SPOTTING_FSM_TRACE = [(10, 2.0), (20, 3.0), (30, 2.0), (40, 2.0), (50, 2.0)]


# Phase B3→v1.6：scrape（拍照刮板）工位轨迹
# 对齐 PLC ref_plc_scraping.txt：子步 {0, 10, 15, 20, 30, 90}
# Step 15 为唯一乒乓等待点（A10 FB 内部阻塞等 Confirm）
# Step 20(CNC) / Step 30(机器人) 无乒乓，PLC 自动推进
# Step 10 后按 PhotoMode 路由：0→15→20→30(完整刮板), 1→15(仅before-photo→Done)
SCRAPE_FSM_TRACE_DEFAULT = [(10, 2.0), (12, 1.0), (13, 1.0), (15, 2.0), (20, 3.0), (30, 2.0)]
SCRAPE_FSM_TRACE_BEFORE_PHOTO = [(10, 2.0), (12, 1.0), (13, 1.0), (15, 2.0)]

# Collect FSM 轨迹（协议 v2.5：Step 12 动作码分支 / Step 13 取耗材）
COLLECT_FSM_TRACE = [(10, 2.0), (12, 1.0), (13, 1.0), (20, 3.0), (30, 2.0), (40, 2.0)]


def _parse_bool(s: str) -> bool:
    return s.lower() in ("true", "1", "yes")


def _parse_value(var_name: str, value_str: str):
    """根据变量名解析用户输入值，返回 (value, VariantType)。"""
    meta = _VAR_DEFAULTS.get(var_name)
    if meta is None:
        raise ValueError(f"未知变量: {var_name}")
    _, vtype = meta
    if vtype == ua.VariantType.Boolean:
        return _parse_bool(value_str), vtype
    elif vtype in (ua.VariantType.Int16, ua.VariantType.Int32):
        return int(value_str), vtype
    elif vtype == ua.VariantType.Float:
        return float(value_str), vtype
    elif vtype == ua.VariantType.String:
        return value_str, vtype
    else:
        return value_str, vtype


async def run_server(
    delay: float = 0.5,
    auto_complete: bool = True,
    port: int = 4840,
    error_rate: float = 0.0,
    error_actions: set = None,
):
    server = Server()
    await server.init()
    url = f"opc.tcp://localhost:{port}"
    server.set_endpoint(url)
    server.set_server_name("pTLC Mock PLC")

    ns = await server.register_namespace(NAMESPACE)
    # 按实机（Inovance / CODESYS 内核）OPC UA 树结构构建层级：
    #   Objects → DeviceSet → Inovance-ARM-Linux → Resources → Application → GlobalVars → Host_Computer → <变量>
    # 上位机 plc_client.py 通过 BrowseName 文本比对逐级查找，无须关心 namespace 索引。
    # mock 依然用自己的 urn:ptlc:plc 命名空间，但树形状与实机同构。
    device_set  = await server.nodes.objects.add_object(ns, "DeviceSet")
    device      = await device_set.add_object(ns, "Inovance-ARM-Linux")
    resources   = await device.add_object(ns, "Resources")
    application = await resources.add_object(ns, "Application")
    global_vars = await application.add_object(ns, "GlobalVars")
    gvl         = await global_vars.add_object(ns, "Host_Computer")

    # ── 创建所有变量节点（挂在 Host_Computer 下）──
    nodes: dict[str, object] = {}
    for var_name, (default, vtype) in _VAR_DEFAULTS.items():
        nodes[var_name] = await gvl.add_variable(ns, var_name, default, vtype)

    # 所有节点允许外部写入（调试模式）
    for node in nodes.values():
        await node.set_writable()

    # Phase C：旧握手通道变量已删除（同构更新：实机 PLC 端 Phase C 同步后不再存在）
    # 仅保留 BusyAggregator 所需的 plc_busy_node
    plc_busy_node    = nodes["PLC_Busy"]
    # 协议 v1.1：collect 工位业务参数
    # 协议 v1.3：多通道展开数组节点快捷引用
    tank_state_node   = nodes["Tank_State"]
    tank_drain_en_node = nodes["Tank_Drain_Enable"]
    tank_drain_dn_node = nodes["Tank_Drain_Done"]
    target_tank_node  = nodes["Expand_Target_Tank"]

    # ── Phase A StageFSM（collect 先行）──
    # collect_Enable 上升沿 → 按 COLLECT_FSM_TRACE 推进；控制台 `error collect` 可注入 _Step=90
    # 协议 v1.1：StageFSM 额外派生 <stage>_Busy；全局 PLC_Busy 由 BusyAggregator 单写
    # 协议 v2.5：Step 12 按 _Plate_Op 走 NONE/PUT_NEW/SWAP 分支 / Step 13 取耗材
    stage_fsms: dict[str, "StageFSM"] = {}

    async def _collect_step12_hook():
        """collect FSM Step 12 模拟（v2.5）：根据 collect_Plate_Op 决定动作。

        - 0 NONE   跳过（暂存 B 有余量）
        - 1 PUT_NEW 仅放新板（PUT_PLATE_TO_STAGING_B）
        - 2 SWAP   先 RETURN_PLATE_TO_RACK_B(Old_Slot) 再 PUT_PLATE_TO_STAGING_B(Fetch)
        """
        try:
            op = int(await nodes["collect_Plate_Op"].read_value())
            fetch = int(await nodes["collect_Fetch_Rack_Plate"].read_value())
            old = int(await nodes["collect_Old_Plate_Slot"].read_value())
            if op == 0:
                log.info("   [collect FSM] Step 12: op=NONE 跳过搬板")
            elif op == 1:
                log.info("   [collect FSM] Step 12: op=PUT_NEW PUT_PLATE_TO_STAGING_B(%d)", fetch)
            elif op == 2:
                log.info(
                    "   [collect FSM] Step 12: op=SWAP RETURN(%d)→RACK → PUT(%d)→STAGING_B",
                    old, fetch,
                )
            else:
                log.warning("   [collect FSM] Step 12: 非法 op=%d（期望 0/1/2）", op)
        except Exception as e:
            log.warning("   [collect FSM] Step 12 hook 异常: %s", e)

    async def _collect_step13_hook():
        """collect FSM Step 13 模拟：动作B 从暂存B取空玻璃瓶。"""
        try:
            slot = int(await nodes["collect_Consume_Slot"].read_value())
            log.info("   [collect FSM] Step 13: 动作B 从暂存B slot %d 取空玻璃瓶", slot)
        except Exception as e:
            log.warning("   [collect FSM] Step 13 hook 异常: %s", e)

    stage_fsms["collect"] = StageFSM(
        name="collect",
        enable_node=nodes["collect_Enable"],
        step_node=nodes["collect_Step"],
        done_node=nodes["collect_Done"],
        error_node=nodes["collect_Error"],
        reset_node=nodes["collect_Reset"],
        busy_node=nodes["collect_Busy"],
        trace=COLLECT_FSM_TRACE,
        step_hooks={12: _collect_step12_hook, 13: _collect_step13_hook},
    )
    # Phase B1→v1.3：develop（展开）工位——PLC 变量前缀 Expand
    # v1.3：删除 confirm_steps（Step 35 乒乓握手已废弃）；新增 step_hooks 更新 Tank_State
    async def _expand_step0_hook():
        """Expand FSM Step 0 钩子：读 Expand_Target_Tank，设 Tank_State[target]=10。"""
        try:
            target = int(await target_tank_node.read_value())
            if 1 <= target <= 8:
                arr = list(await tank_state_node.read_value())
                arr[target - 1] = 10
                await tank_state_node.write_value(
                    ua.DataValue(ua.Variant(arr, ua.VariantType.Int16))
                )
                # 自动推导 Group/Number
                group = (target - 1) // 4 + 1
                number = (target - 1) % 4 + 1
                await nodes["Expand_Group"].write_value(
                    ua.DataValue(ua.Variant(group, ua.VariantType.Int16))
                )
                await nodes["Expand_Number"].write_value(
                    ua.DataValue(ua.Variant(number, ua.VariantType.Int16))
                )
                log.info("   [Expand FSM] Step 0 hook: Tank_State[%d]=10, Group=%d, Number=%d",
                         target, group, number)
        except Exception as e:
            log.warning("   [Expand FSM] Step 0 hook 异常: %s", e)

    async def _expand_step40_hook():
        """Expand FSM Step 40 钩子：设 Tank_State[target]=40（交付至展开态）。"""
        try:
            target = int(await target_tank_node.read_value())
            if 1 <= target <= 8:
                arr = list(await tank_state_node.read_value())
                arr[target - 1] = 40
                await tank_state_node.write_value(
                    ua.DataValue(ua.Variant(arr, ua.VariantType.Int16))
                )
                log.info("   [Expand FSM] Step 40 hook: Tank_State[%d]=40（交付至展开态）", target)
        except Exception as e:
            log.warning("   [Expand FSM] Step 40 hook 异常: %s", e)

    stage_fsms["Expand"] = StageFSM(
        name="Expand",
        enable_node=nodes["Expand_Enable"],
        step_node=nodes["Expand_Step"],
        done_node=nodes["Expand_Done"],
        error_node=nodes["Expand_Error"],
        reset_node=nodes["Expand_Reset"],
        busy_node=nodes["Expand_Busy"],
        trace=DEVELOP_FSM_TRACE,
        step_hooks={0: _expand_step0_hook, 40: _expand_step40_hook},
    )
    # Phase B2→v1.4：spotting（上样点样）工位——PLC 变量前缀 Sampling
    stage_fsms["Sampling"] = StageFSM(
        name="Sampling",
        enable_node=nodes["Sampling_Enable"],
        step_node=nodes["Sampling_Step"],
        done_node=nodes["Sampling_Done"],
        error_node=nodes["Sampling_Error"],
        reset_node=nodes["Sampling_Reset"],
        busy_node=nodes["Sampling_Busy"],
        trace=SPOTTING_FSM_TRACE,
        control_mode_node=nodes["Sampling_ControlMode"],
        expected_control_mode=0,
    )
    # Phase B3→v1.6：scrape（拍照刮板）工位——PLC 变量前缀 scrape
    # Step 15 为唯一乒乓等待点（A10 FB 内部阻塞等 Confirm）
    # Step 20(CNC)/Step 30(机器人) 无乒乓，PLC 自动推进
    # Step 10 后按 PhotoMode 动态路由：0→15→20→30(完整刮板), 1→15(仅before-photo→Done)

    # PhotoMode 路由 hook：Step 10 完成后读取 PhotoMode，动态替换 trace
    async def _scrape_step10_hook():
        """scrape FSM Step 10 钩子：读 scrape_PhotoMode，动态切换后续轨迹。

        消费语义：Step 10 读取并路由后必须将 PhotoMode 归零，
        避免下一次 scrape 启动时残留值导致错误路由。
        参考 AGENTS.md: "scrape_PhotoMode 消费语义：Step 10 reads and resets it to 0 after routing"
        """
        try:
            photo_mode = int(await nodes["scrape_PhotoMode"].read_value())
            # 诊断读取：source_tank 仅用于 trace，不参与路由；节点缺失或读失败均不阻塞主逻辑。
            try:
                source_tank = int(await nodes["scrape_Source_Tank"].read_value())
            except Exception:
                source_tank = -1  # 诊断节点未创建或读失败
            log.info(
                "   [scrape FSM] Step 10 hook: PhotoMode=%d source_tank=%d",
                photo_mode, source_tank,
            )
            if photo_mode == 1:
                # before-photo 模式：替换 trace 为 Step 15 路径
                stage_fsms["scrape"]._trace = SCRAPE_FSM_TRACE_BEFORE_PHOTO
                log.info("   [scrape FSM] Step 10 hook: PhotoMode=1, 切换为 before-photo 路径")
            else:
                # 完整刮板模式（默认）
                stage_fsms["scrape"]._trace = SCRAPE_FSM_TRACE_DEFAULT
                log.info("   [scrape FSM] Step 10 hook: PhotoMode=0, 使用完整刮板路径")
            # 消费语义：路由完成后归零，防止下一次 scrape 启动时残留 PhotoMode=1 导致错误路由
            # 必须显式指定 VariantType.Int16，否则 asyncua 默认包装为 Int64 导致 BadTypeMismatch
            await nodes["scrape_PhotoMode"].write_value(
                ua.DataValue(ua.Variant(0, ua.VariantType.Int16))
            )
        except Exception as e:
            log.warning("   [scrape FSM] Step 10 hook 异常: %s", e)

    async def _scrape_step12_hook():
        """scrape FSM Step 12 模拟（v2.5）：根据 scrape_Plate_Op 决定动作。

        - 0 NONE   跳过（暂存 A 有余量）
        - 1 PUT_NEW 仅放新板（PUT_PLATE_TO_STAGING_A）
        - 2 SWAP   先 RETURN_PLATE_TO_RACK_A(Old_Slot) 再 PUT_PLATE_TO_STAGING_A(Fetch)
        """
        try:
            op = int(await nodes["scrape_Plate_Op"].read_value())
            fetch = int(await nodes["scrape_Fetch_Rack_Plate"].read_value())
            old = int(await nodes["scrape_Old_Plate_Slot"].read_value())
            if op == 0:
                log.info("   [scrape FSM] Step 12: op=NONE 跳过搬板")
            elif op == 1:
                log.info("   [scrape FSM] Step 12: op=PUT_NEW PUT_PLATE_TO_STAGING_A(%d)", fetch)
            elif op == 2:
                log.info(
                    "   [scrape FSM] Step 12: op=SWAP RETURN(%d)→RACK → PUT(%d)→STAGING_A",
                    old, fetch,
                )
            else:
                log.warning("   [scrape FSM] Step 12: 非法 op=%d（期望 0/1/2）", op)
        except Exception as e:
            log.warning("   [scrape FSM] Step 12 hook 异常: %s", e)

    async def _scrape_step13_hook():
        """scrape FSM Step 13 模拟：动作B 从暂存A取空粉末收集器。"""
        try:
            slot = int(await nodes["scrape_Consume_Slot"].read_value())
            log.info("   [scrape FSM] Step 13: 动作B 从暂存A slot %d 取空粉末收集器", slot)
        except Exception as e:
            log.warning("   [scrape FSM] Step 13 hook 异常: %s", e)

    stage_fsms["scrape"] = StageFSM(
        name="scrape",
        enable_node=nodes["scrape_Enable"],
        step_node=nodes["scrape_Step"],
        done_node=nodes["scrape_Done"],
        error_node=nodes["scrape_Error"],
        reset_node=nodes["scrape_Reset"],
        busy_node=nodes["scrape_Busy"],
        trace=SCRAPE_FSM_TRACE_DEFAULT,
        confirm_steps={15: nodes["scrape_Confirm"]},  # Step 15 唯一乒乓点（A10 FB 等 Confirm）
        step_hooks={10: _scrape_step10_hook, 12: _scrape_step12_hook, 13: _scrape_step13_hook},
        wait_confirm_node=nodes["scrape_WaitConfirm"],  # v1.7: 显式就绪信号
    )
    fsm_tasks = [asyncio.create_task(fsm.run_loop()) for fsm in stage_fsms.values()]
    sampling_l2 = SamplingL2FSM(
        nodes,
        delay=max(0.05, delay),
        auto_complete=auto_complete,
    )
    fsm_tasks.append(asyncio.create_task(sampling_l2.run_loop()))
    rail_l2 = RailL2FSM(
        nodes,
        delay=max(0.05, delay),
        auto_complete=auto_complete,
    )
    fsm_tasks.append(asyncio.create_task(rail_l2.run_loop()))

    # 协议 v1.1 BusyAggregator：PLC_Busy := OR(各工位 _Busy)。独立协程单写，避免与 StageFSM 冲突。
    # Phase C：上位机不再读取 PLC_Busy，但 mock 侧保留 BusyAggregator 以维持实机同构行为
    busy_agg_task = asyncio.create_task(_busy_aggregator_loop(plc_busy_node, stage_fsms))

    # 协议 v1.3：TankDrainFSM——独立协程模拟排液
    # 传入 scrape_Busy / collect_Busy 节点：robot_pickup 子步需要轮询两者均 FALSE
    # 才能完成 65→99（协议 A：Done=99 = 板已离缸送至拍照刮板工位、上一块板已让出工位）。
    # 2026-05-31 (D')：从读 _Enable 改为读 _Busy，避免上位机 write _Enable=TRUE 后
    # PLC FSM 尚未推进到忙状态的闪烁采样窗口。`<Stage>_Busy` 定义为
    # `(_Step ∈ [10,80]) AND NOT _Done`，是工位实际占用的权威信号。
    drain_fsm_task = asyncio.create_task(
        _tank_drain_fsm_loop(
            tank_state_node, tank_drain_en_node, tank_drain_dn_node,
            nodes["scrape_Busy"], nodes["collect_Busy"],
        )
    )

    # ── 自动完成控制 ──
    auto_config = {"enabled": auto_complete, "delay": delay}
    error_config = {"rate": error_rate, "actions": error_actions or set()}

    log.info("Mock PLC server started at %s", url)
    log.info("collect/develop/spotting/scrape 工位参数已注册")
    log.info("自动完成: %s (delay=%.1fs)", "ON" if auto_config["enabled"] else "OFF", auto_config["delay"])

    # ── 启动交互式控制台 ──
    console_task = asyncio.create_task(
        _interactive_console(nodes, auto_config, stage_fsms)
    )

    # Phase C：PC_Trigger 上升沿监听已移除（上位机已不再使用旧握手路径）
    # mock 主循环仅维持 server 运行
    async with server:
        while True:
            await asyncio.sleep(1.0)


async def _busy_aggregator_loop(plc_busy_node, stage_fsms: dict) -> None:
    """协议 v1.1 BusyAggregator：轮询各工位 _Busy，OR 后单写 PLC_Busy。

    仅本协程写 PLC_Busy，避免与 StageFSM 互相覆盖。
    """
    busy_nodes = [fsm._busy for fsm in stage_fsms.values() if fsm._busy is not None]
    if not busy_nodes:
        return
    prev: bool | None = None
    while True:
        await asyncio.sleep(0.05)
        try:
            agg = False
            for n in busy_nodes:
                if bool(await n.read_value()):
                    agg = True
                    break
            if agg != prev:
                await plc_busy_node.write_value(
                    ua.DataValue(ua.Variant(agg, ua.VariantType.Boolean))
                )
                prev = agg
        except Exception as e:
            log.debug("[BusyAggregator] 写入失败（忽略）: %s", e)


# ───────────────────────────────────────────────────────────────────
# Phase A：StageFSM——电平驱动自治状态机（Mock）
# ───────────────────────────────────────────────────────────────────


class RailL2FSM:
    """同构地轨 (地轨轴11Y) L2 伺服原子动作模拟器。

    协议与 Sampling L2 一致 (ActionCode/RequestSeq/Start → poll State 至 DONE),
    但作为纯伺服绝对移动: 无 ControlMode 门控, 无 SafeState 前置校验。
    动作码 1..6 对应 legacy HMI_地轨轴11Y.position[1..6]。
    """

    IDLE, RUNNING, DONE, REJECTED, ERROR, INTERRUPTED = 0, 10, 20, 30, 40, 50
    ACTIONS = {1, 2, 3, 4, 5, 6}

    def __init__(self, nodes: dict, *, delay: float, auto_complete: bool) -> None:
        self.nodes = nodes
        self.delay = delay
        self.auto_complete = auto_complete
        self._prev_start = False
        self._prev_reset = False
        self._run_task: Optional[asyncio.Task] = None

    async def _write(self, name: str, value, vtype) -> None:
        await self.nodes[name].write_value(ua.DataValue(ua.Variant(value, vtype)))

    async def _i16(self, name: str, value: int) -> None:
        await self._write(name, int(value), ua.VariantType.Int16)

    async def _i32(self, name: str, value: int) -> None:
        await self._write(name, int(value), ua.VariantType.Int32)

    async def _bool(self, name: str, value: bool) -> None:
        await self._write(name, bool(value), ua.VariantType.Boolean)

    async def _terminal(self, *, seq: int, state: int, error: int, retryable: bool) -> None:
        await self._i16("Rail_L2_ErrorCode", error)
        await self._bool("Rail_L2_Retryable", retryable)
        await self._i32("Rail_L2_CompletedSeq", seq)
        await self._i16("Rail_L2_State", state)

    async def _reject(self, seq: int, error: int, retryable: bool) -> None:
        await self._terminal(seq=seq, state=self.REJECTED, error=error, retryable=retryable)

    async def _run_action(self, code: int, seq: int) -> None:
        try:
            await self._i16("Rail_L2_Step", code)
            if not self.auto_complete:
                while True:
                    await asyncio.sleep(1.0)
            await asyncio.sleep(self.delay)
            if bool(await self.nodes["PLC_EStop"].read_value()):
                await self._terminal(seq=seq, state=self.INTERRUPTED, error=401, retryable=False)
                return
            await self._terminal(seq=seq, state=self.DONE, error=0, retryable=False)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[Rail L2] mock action failed")
            await self._terminal(seq=seq, state=self.ERROR, error=599, retryable=False)

    async def _accept_start(self) -> None:
        code = int(await self.nodes["Rail_L2_ActionCode"].read_value())
        seq = int(await self.nodes["Rail_L2_RequestSeq"].read_value())
        state = int(await self.nodes["Rail_L2_State"].read_value())
        accepted = int(await self.nodes["Rail_L2_AcceptedSeq"].read_value())
        completed = int(await self.nodes["Rail_L2_CompletedSeq"].read_value())
        if state != self.IDLE:
            await self._reject(seq, 101, True)
            return
        if seq <= max(accepted, completed):
            await self._reject(seq, 102, False)
            return
        if code not in self.ACTIONS:
            await self._reject(seq, 103, False)
            return
        await self._i16("Rail_L2_ActiveCode", code)
        await self._i32("Rail_L2_AcceptedSeq", seq)
        await self._i16("Rail_L2_ErrorCode", 0)
        await self._bool("Rail_L2_Retryable", False)
        await self._i16("Rail_L2_State", self.RUNNING)
        self._run_task = asyncio.create_task(self._run_action(code, seq))

    async def _reset(self) -> None:
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        seq = int(await self.nodes["Rail_L2_AcceptedSeq"].read_value())
        await self._terminal(seq=seq, state=self.INTERRUPTED, error=402, retryable=False)

    async def run_loop(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            start = bool(await self.nodes["Rail_L2_Start"].read_value())
            reset = bool(await self.nodes["Rail_L2_Reset"].read_value())
            state = int(await self.nodes["Rail_L2_State"].read_value())
            if reset and not self._prev_reset:
                await self._reset()
            self._prev_reset = reset
            if start and not self._prev_start:
                await self._accept_start()
            if (
                not start
                and self._prev_start
                and state in {self.DONE, self.REJECTED, self.ERROR, self.INTERRUPTED}
            ):
                await self._i16("Rail_L2_State", self.IDLE)
                await self._i16("Rail_L2_ActiveCode", 0)
                await self._i16("Rail_L2_Step", 0)
                await self._i16("Rail_L2_ErrorCode", 0)
                await self._bool("Rail_L2_Retryable", False)
            self._prev_start = start


class SamplingL2FSM:
    """Isomorphic Sampling L2 action-channel simulator."""

    IDLE, RUNNING, DONE, REJECTED, ERROR, INTERRUPTED = 0, 10, 20, 30, 40, 50
    READY, HELD, RELEASE_READY, RECOVERY = 10, 20, 30, 90
    ACTIONS = {10, 20, 30, 40, 50, 60, 70, 80, 90}

    def __init__(self, nodes: dict, *, delay: float, auto_complete: bool) -> None:
        self.nodes = nodes
        self.delay = delay
        self.auto_complete = auto_complete
        self._prev_start = False
        self._prev_reset = False
        self._run_task: Optional[asyncio.Task] = None
        self._receive_prepared = False

    async def _write(self, name: str, value, vtype) -> None:
        await self.nodes[name].write_value(
            ua.DataValue(ua.Variant(value, vtype))
        )

    async def _i16(self, name: str, value: int) -> None:
        await self._write(name, int(value), ua.VariantType.Int16)

    async def _i32(self, name: str, value: int) -> None:
        await self._write(name, int(value), ua.VariantType.Int32)

    async def _bool(self, name: str, value: bool) -> None:
        await self._write(name, bool(value), ua.VariantType.Boolean)

    async def _terminal(
        self,
        *,
        seq: int,
        state: int,
        error: int,
        retryable: bool,
        safe_state: int | None = None,
    ) -> None:
        if safe_state is not None:
            await self._i16("Sampling_L2_SafeState", safe_state)
        await self._i16("Sampling_L2_ErrorCode", error)
        await self._bool("Sampling_L2_Retryable", retryable)
        await self._i32("Sampling_L2_CompletedSeq", seq)
        await self._i16("Sampling_L2_State", state)

    async def _reject(self, seq: int, error: int, retryable: bool) -> None:
        await self._terminal(
            seq=seq,
            state=self.REJECTED,
            error=error,
            retryable=retryable,
        )

    async def _validate(self, code: int) -> int:
        safe_state = int(
            await self.nodes["Sampling_L2_SafeState"].read_value()
        )
        if code == 10:
            return 0
        if code in {20, 30, 40} and safe_state != self.READY:
            return 501
        if code == 50 and (
            safe_state != self.READY or not self._receive_prepared
        ):
            return 502
        if code in {60, 70, 80} and safe_state != self.HELD:
            return 503
        if code == 90 and safe_state != self.RELEASE_READY:
            return 504
        return 0

    async def _run_action(self, code: int, seq: int) -> None:
        try:
            await self._i16("Sampling_L2_Step", code)
            if not self.auto_complete:
                while True:
                    await asyncio.sleep(1.0)
            await asyncio.sleep(self.delay)
            if bool(await self.nodes["PLC_EStop"].read_value()):
                await self._terminal(
                    seq=seq,
                    state=self.INTERRUPTED,
                    error=401,
                    retryable=False,
                    safe_state=self.RECOVERY,
                )
                return

            if code == 10:
                safe_state = self.READY
                self._receive_prepared = False
            elif code == 40:
                safe_state = self.READY
                self._receive_prepared = True
            elif code == 50:
                safe_state = self.HELD
                self._receive_prepared = False
            elif code == 80:
                safe_state = self.RELEASE_READY
            elif code == 90:
                safe_state = self.READY
            else:
                safe_state = int(
                    await self.nodes["Sampling_L2_SafeState"].read_value()
                )
            await self._terminal(
                seq=seq,
                state=self.DONE,
                error=0,
                retryable=False,
                safe_state=safe_state,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[Sampling L2] mock action failed")
            await self._terminal(
                seq=seq,
                state=self.ERROR,
                error=599,
                retryable=False,
                safe_state=self.RECOVERY,
            )

    async def _accept_start(self) -> None:
        code = int(await self.nodes["Sampling_L2_ActionCode"].read_value())
        seq = int(await self.nodes["Sampling_L2_RequestSeq"].read_value())
        mode = int(await self.nodes["Sampling_ControlMode"].read_value())
        legacy_busy = bool(await self.nodes["Sampling_Busy"].read_value())
        state = int(await self.nodes["Sampling_L2_State"].read_value())
        accepted = int(
            await self.nodes["Sampling_L2_AcceptedSeq"].read_value()
        )
        completed = int(
            await self.nodes["Sampling_L2_CompletedSeq"].read_value()
        )
        if mode != 1:
            await self._reject(seq, 401, False)
            return
        if state != self.IDLE or legacy_busy:
            await self._reject(seq, 101, True)
            return
        if seq <= max(accepted, completed):
            await self._reject(seq, 102, False)
            return
        if code not in self.ACTIONS:
            await self._reject(seq, 103, False)
            return
        precondition_error = await self._validate(code)
        if precondition_error:
            await self._reject(seq, precondition_error, False)
            return

        await self._i16("Sampling_L2_ActiveCode", code)
        await self._i32("Sampling_L2_AcceptedSeq", seq)
        await self._i16("Sampling_L2_ErrorCode", 0)
        await self._bool("Sampling_L2_Retryable", False)
        await self._i16("Sampling_L2_State", self.RUNNING)
        self._run_task = asyncio.create_task(self._run_action(code, seq))

    async def _reset(self) -> None:
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        seq = int(await self.nodes["Sampling_L2_AcceptedSeq"].read_value())
        await self._terminal(
            seq=seq,
            state=self.INTERRUPTED,
            error=402,
            retryable=False,
            safe_state=self.RECOVERY,
        )

    async def run_loop(self) -> None:
        while True:
            await asyncio.sleep(0.05)
            start = bool(
                await self.nodes["Sampling_L2_Start"].read_value()
            )
            reset = bool(
                await self.nodes["Sampling_L2_Reset"].read_value()
            )
            state = int(
                await self.nodes["Sampling_L2_State"].read_value()
            )
            if reset and not self._prev_reset:
                await self._reset()
            self._prev_reset = reset
            if start and not self._prev_start:
                await self._accept_start()
            if (
                not start
                and self._prev_start
                and state
                in {
                    self.DONE,
                    self.REJECTED,
                    self.ERROR,
                    self.INTERRUPTED,
                }
            ):
                await self._i16("Sampling_L2_State", self.IDLE)
                await self._i16("Sampling_L2_ActiveCode", 0)
                await self._i16("Sampling_L2_Step", 0)
                await self._i16("Sampling_L2_ErrorCode", 0)
                await self._bool("Sampling_L2_Retryable", False)
            self._prev_start = start


class StageFSM:
    """单工位电平驱动状态机，契约见 docs/PLC_Unified_Stage_Protocol.md。

    - Enable 上升沿（且 Step==0）→ 按 trace 逐步推进；完成后 Step 回 0 + Done=TRUE
    - Enable 下降沿 → 清 Done
    - 外部注入 Step=90 → 锁存 Error=TRUE；Reset=TRUE → 清 Error + Step=0
    - 协议 v1.1：每个调度周期派生 <stage>_Busy = (Step ∈ [10,80]) AND NOT Done
    - v1.3：step_hooks 支持在指定步执行自定义异步回调（如更新 Tank_State 数组）
    """

    def __init__(
        self, name: str,
        enable_node, step_node, done_node, error_node, reset_node,
        busy_node,
        trace: list,
        confirm_steps: Optional[dict[int, object]] = None,
        step_hooks: Optional[dict[int, object]] = None,
        wait_confirm_node: Optional[object] = None,
        control_mode_node: Optional[object] = None,
        expected_control_mode: int = 0,
    ) -> None:
        self.name = name
        self._enable = enable_node
        self._step = step_node
        self._done = done_node
        self._error = error_node
        self._reset = reset_node
        self._busy = busy_node
        self._trace = trace
        # v1.2: 乒乓握手步——{子步号: confirm_node}，到达后轮询等待该节点为 TRUE
        self._confirm_steps = confirm_steps or {}
        # v1.3: 步钩子——{子步号: async callable}，在写 _Step 后调用
        self._step_hooks = step_hooks or {}
        # v1.7: 显式就绪信号节点——PLC 进入 confirm 轮询前置 TRUE，消费后清零
        self._wait_confirm_node = wait_confirm_node
        self._run_task: Optional[asyncio.Task] = None
        self._control_mode_node = control_mode_node
        self._expected_control_mode = expected_control_mode
        self._prev_enable = False
        self._prev_reset = False
        self._prev_busy: bool | None = None

    async def _write_bool(self, node, value: bool) -> None:
        await node.write_value(ua.DataValue(ua.Variant(bool(value), ua.VariantType.Boolean)))

    async def _write_int(self, node, value: int) -> None:
        # 读取节点实际类型，保证写入 VariantType 与节点声明一致（避免 Int32→Int16 拒绝写入）
        try:
            dt = await node.read_data_type_as_variant_type()
        except Exception:
            dt = ua.VariantType.Int32
        await node.write_value(ua.DataValue(ua.Variant(int(value), dt)))

    async def inject_error(self) -> None:
        """控制台注入故障：Step=90 + Error=TRUE，并取消当前 run_task。"""
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
            self._run_task = None
        await self._write_int(self._step, 90)
        await self._write_bool(self._error, True)
        log.info("<< [%s FSM] 故障注入: _Step=90 _Error=TRUE", self.name)

    async def _run_sequence(self) -> None:
        """按 trace 逐步写 _Step；完成后 _Step=0 + _Done=TRUE。

        v1.2 扩展：如果当前步在 _confirm_steps 中，则轮询等待对应 Confirm 节点
        为 TRUE 后清零该节点，再继续下一步。
        v1.3 扩展：如果当前步在 _step_hooks 中，则在写 _Step 后调用对应异步回调。
        v1.6 扩展：step_hooks 可动态修改 self._trace，本方法按索引迭代以支持动态切换。
        """
        try:
            idx = 0
            while idx < len(self._trace):
                step, delay = self._trace[idx]
                await self._write_int(self._step, step)
                log.info("   [%s FSM] _Step = %d", self.name, step)

                # v1.3: 步钩子——在写 _Step 后调用
                if step in self._step_hooks:
                    try:
                        await self._step_hooks[step]()
                    except Exception as e:
                        log.warning("   [%s FSM] step_hook(%d) 异常: %s", self.name, step, e)

                if step in self._confirm_steps:
                    # v1.2: 乒乓握手——轮询等待 Confirm 信号
                    confirm_node = self._confirm_steps[step]
                    # v1.7: 显式就绪信号——PLC 已准备好接收 Confirm
                    if self._wait_confirm_node:
                        await self._write_bool(self._wait_confirm_node, True)
                    log.info("   [%s FSM] 等待 Confirm 信号（Step=%d）...", self.name, step)
                    while True:
                        try:
                            if bool(await confirm_node.read_value()):
                                await self._write_bool(confirm_node, False)  # PLC 侧清零
                                # v1.7: 清除就绪信号
                                if self._wait_confirm_node:
                                    await self._write_bool(self._wait_confirm_node, False)
                                log.info("   [%s FSM] Confirm 收到，继续（Step=%d）", self.name, step)
                                break
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                else:
                    await asyncio.sleep(delay)
                idx += 1
            # 正常结束：Step 回 0，Done 锁存（待 Enable=FALSE 清零）
            await self._write_int(self._step, 0)
            await self._write_bool(self._done, True)
            log.info("<< [%s FSM] 完成: _Step=0 _Done=TRUE", self.name)
        except asyncio.CancelledError:
            log.info("[%s FSM] run_sequence 已取消", self.name)
            raise

    async def run_loop(self) -> None:
        """独立协程：监听 Enable / Reset 边沿，驱动状态机；同时派生 <stage>_Busy。"""
        while True:
            await asyncio.sleep(0.05)
            try:
                enable = bool(await self._enable.read_value())
                reset = bool(await self._reset.read_value())
                cur_step = int(await self._step.read_value())
                cur_done = bool(await self._done.read_value())
            except Exception as e:
                log.debug("[%s FSM] 读节点失败: %s", self.name, e)
                continue

            # 协议 v1.1：派生 <stage>_Busy = (Step ∈ [10,80]) AND NOT Done
            busy = (10 <= cur_step <= 80) and not cur_done
            if busy != self._prev_busy:
                try:
                    await self._write_bool(self._busy, busy)
                except Exception as e:
                    log.debug("[%s FSM] 写 _Busy 失败: %s", self.name, e)
                self._prev_busy = busy

            # Reset 上升沿：清 Error + Step=0 + WaitConfirm=FALSE
            if reset and not self._prev_reset:
                await self._write_bool(self._error, False)
                await self._write_int(self._step, 0)
                # v1.7: Reset 时清除 WaitConfirm（与 Confirm 同步清理）
                if self._wait_confirm_node:
                    try:
                        await self._write_bool(self._wait_confirm_node, False)
                    except Exception:
                        pass
                log.info("<< [%s FSM] Reset 上升沿: _Error=FALSE _Step=0", self.name)
            self._prev_reset = reset

            # Enable 上升沿：启动 run_sequence（需 Step==0，避免从故障态误启动）
            if enable and not self._prev_enable:
                pass
            if (
                enable
                and not self._prev_enable
                and self._control_mode_node is not None
            ):
                mode = int(await self._control_mode_node.read_value())
                if mode != self._expected_control_mode:
                    log.warning(
                        "[%s FSM] Enable rejected by ControlMode=%d",
                        self.name,
                        mode,
                    )
                    self._prev_enable = enable
                    continue
                if cur_step == 0 and (self._run_task is None or self._run_task.done()):
                    log.info(">> [%s FSM] Enable 上升沿，启动状态机 trace=%s",
                             self.name, self._trace)
                    self._run_task = asyncio.create_task(self._run_sequence())
                else:
                    log.warning("[%s FSM] Enable 上升沿被忽略（_Step=%d run_task_active=%s）",
                                self.name, cur_step,
                                self._run_task is not None and not self._run_task.done())

            if (
                enable
                and not self._prev_enable
                and self._control_mode_node is None
            ):
                if cur_step == 0 and (
                    self._run_task is None or self._run_task.done()
                ):
                    self._run_task = asyncio.create_task(self._run_sequence())

            # Enable 下降沿：清 Done + WaitConfirm；若 run_task 在跑，取消
            if (not enable) and self._prev_enable:
                if self._run_task and not self._run_task.done():
                    self._run_task.cancel()
                    try:
                        await self._run_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    self._run_task = None
                await self._write_bool(self._done, False)
                # v1.7: Enable 下降沿清除 WaitConfirm（防止下次启动残留）
                if self._wait_confirm_node:
                    try:
                        await self._write_bool(self._wait_confirm_node, False)
                    except Exception:
                        pass
                log.info("<< [%s FSM] Enable 下降沿: _Done=FALSE", self.name)

            self._prev_enable = enable


# ───────────────────────────────────────────────────────────────────
# 协议 v1.3：TankDrainFSM——排液模拟协程
# ───────────────────────────────────────────────────────────────────

# 排液 4 阶段子步时长（秒）——与协议 v1.3 §7 排液 FSM 子状态对齐
#   Phase A (50 Draining)         排液阀+真空泵抽液
#   Phase B (55 BlowAir)          吹气清扫
#   Phase C (60 CylinderRetract)  气缸退回
#   Phase D (65 RobotPickup)      机器人物理取板，把硅胶板送至拍照刮板工位（最慢，串行）
# 物理依据：robot_pickup 是串行资源（单台机器人）+ 物理移动耗时，必须显著长于其他子步，
# 才能在 mock 时序上正确呈现「展缸在硅胶板被取走前一直被占用」。
DRAIN_DELAY_DRAINING   = 1.5
DRAIN_DELAY_BLOW_AIR   = 1.0
DRAIN_DELAY_CYLINDER   = 0.5
DRAIN_DELAY_ROBOT_PICK = 3.0

# 机器人取板串行锁：协议要求多缸同时到达 65 时按缸号顺序串行（单台机器人）
_robot_pickup_lock: asyncio.Lock = asyncio.Lock()
# Tank 数组写入互斥：保护 Tank_State / Tank_Drain_Done 的 RMW 不被并发排液协程串改
_tank_array_write_lock: asyncio.Lock = asyncio.Lock()


async def _set_tank_state_one(tank_state_node, tank_idx: int, value: int) -> None:
    """单缸 Tank_State 元素 RMW 写入（持 _tank_array_write_lock）。"""
    async with _tank_array_write_lock:
        try:
            arr = list(await tank_state_node.read_value())
            arr[tank_idx] = value
            await tank_state_node.write_value(
                ua.DataValue(ua.Variant(arr, ua.VariantType.Int16))
            )
        except Exception as e:
            log.warning("[TankDrain] Tank %d 写 Tank_State=%d 失败: %s", tank_idx + 1, value, e)


async def _set_drain_done_one(tank_drain_dn_node, tank_idx: int, value: bool) -> None:
    """单缸 Tank_Drain_Done 元素 RMW 写入（持 _tank_array_write_lock）。"""
    async with _tank_array_write_lock:
        try:
            arr = list(await tank_drain_dn_node.read_value())
            arr[tank_idx] = value
            await tank_drain_dn_node.write_value(
                ua.DataValue(ua.Variant(arr, ua.VariantType.Boolean))
            )
        except Exception as e:
            log.warning("[TankDrain] Tank %d 写 Drain_Done=%s 失败: %s", tank_idx + 1, value, e)


async def _tank_drain_fsm_loop(
    tank_state_node,
    tank_drain_en_node,
    tank_drain_dn_node,
    scrape_busy_node,
    collect_busy_node,
) -> None:
    """独立协程：轮询 Tank_Drain_Enable 数组，模拟排液流程。

    逻辑：
    - Drain_Enable[i]=TRUE 且 Tank_State[i]=40 → 切 Tank_State[i]=50（Draining），
      派发 _drain_complete 协程跑完 4 阶段子步
    - Drain_Enable[i]=FALSE（PC 复位）→ 清 Drain_Done[i]=FALSE

    与 _drain_complete 共用 _tank_array_write_lock 保护 RMW 不被互相串改。
    scrape_busy_node / collect_busy_node 透传给 _drain_complete 用于 Phase D 工位等待。
    2026-05-31 (D')：参数从 _Enable 换为 _Busy，避免采样窗口 race。
    """
    # 跟踪每个缸的排液状态（避免重复触发）
    draining: set[int] = set()

    while True:
        await asyncio.sleep(0.1)
        async with _tank_array_write_lock:
            try:
                en_arr  = list(await tank_drain_en_node.read_value())
                dn_arr  = list(await tank_drain_dn_node.read_value())
                st_arr  = list(await tank_state_node.read_value())
            except Exception:
                continue

            st_changed = False
            dn_changed = False
            spawn_list: list[int] = []

            for i in range(8):  # 0-based index
                en = bool(en_arr[i])
                dn = bool(dn_arr[i])
                st = int(st_arr[i])

                if en and st == 40 and (i + 1) not in draining:
                    # 触发排液：Tank_State → 50
                    st_arr[i] = 50
                    st_changed = True
                    draining.add(i + 1)
                    spawn_list.append(i)
                    log.info("[TankDrain] Tank %d: Phase A 排液 (Tank_State=50)", i + 1)

                if not en and dn:
                    # PC 复位排液信号：清 Drain_Done
                    dn_arr[i] = False
                    dn_changed = True
                    draining.discard(i + 1)

            if st_changed:
                await tank_state_node.write_value(
                    ua.DataValue(ua.Variant(st_arr, ua.VariantType.Int16))
                )
            if dn_changed:
                await tank_drain_dn_node.write_value(
                    ua.DataValue(ua.Variant(dn_arr, ua.VariantType.Boolean))
                )

        # 派发 _drain_complete 必须在锁外，避免子任务首次写入立刻自死锁
        for i in spawn_list:
            asyncio.create_task(
                _drain_complete(
                    i, tank_state_node, tank_drain_dn_node,
                    scrape_busy_node, collect_busy_node,
                )
            )


# 拍照刮板工位轮询间隔（秒）——robot_pickup 等待上一块板让出工位时使用
WORKSTATION_POLL = 0.1


async def _wait_scrape_workstation_idle(
    scrape_busy_node,
    collect_busy_node,
) -> None:
    """轮询等待拍照刮板工位空闲：scrape FSM 与 collect FSM 都不在跑。

    协议 A 语义：Tank_State=99 (Done) = 硅胶板已离缸物理送至拍照刮板工位。
    拍照刮板工位是**单工位**，上一块板未让出前机器人不能完成下一次取板。

    2026-05-31 (D')：采样节点从 _Enable 换为 _Busy。`<Stage>_Busy` 定义为
    `(_Step ∈ [10,80]) AND NOT _Done`，是工位实际占用的权威信号。读 _Enable
    会在上位机 write _Enable=TRUE 之后、PLC FSM 推进到 _Step>=10 之前的闪烁
    窗口错误报如 idle，造成机器人 pickup 与 scrape 启动同时进行。

    上位机 RecipeTask 持有 ScrapeStage._scrape_lock 期间包含整段
    scrape→collect→多 band 重刮，在 mock 端对应 scrape_Busy 或 collect_Busy
    任一为 TRUE 的期间。本函数轮询 100ms 粒度：RecipeTask 在 scrape↔collect
    切换中间的 μs 级间隙不会被踩中；即使物理上被踩中，上位机主动的
    handoff_pending 机制 + sync_states 锁修复依然提供安全网。

    顺序：本函数在 _robot_pickup_lock 内部调用——机器人串行锁抢到后再等工位。
    这避免多缸都看到工位空闲后争抢机器人资源、乱序。
    """
    waited_ticks = 0
    while True:
        try:
            scr = bool(await scrape_busy_node.read_value())
            col = bool(await collect_busy_node.read_value())
        except Exception:
            await asyncio.sleep(WORKSTATION_POLL)
            continue
        if not scr and not col:
            return
        # 每 5s 记一次 INFO，避免长等期间日志寂静
        if waited_ticks % 50 == 0:
            log.info(
                "[TankDrain] 等待拍照刮板工位空闲 (scrape_Busy=%s collect_Busy=%s)",
                scr, col,
            )
        waited_ticks += 1
        await asyncio.sleep(WORKSTATION_POLL)


async def _drain_complete(
    tank_idx: int,  # 0-based
    tank_state_node,
    tank_drain_dn_node,
    scrape_busy_node,
    collect_busy_node,
) -> None:
    """模拟排液 4 阶段 FSM：50 → 55 → 60 → 65 → 99。

    与协议 v1.3 §7 排液并发语义对齐：
      * Tank_Drain_Done=TRUE 仅在 state=99（机器人取板完成）时置位
      * 此时硅胶板已被机器人取出展缸送至拍照刮板工位，缸内为空
      * 因此上位机 DevelopStage Phase 4 拿到 Drain_Done 后释放展缸是安全的

    机器人取板（Phase D, state=65）两重物理约束：
      1. **单台机器人串行**：_robot_pickup_lock 保证同时只有一个缸在取板动作中。
         这是实机侧 PLC 全局锁 `Robot_Busy`（§5.4.4）的 mock 等价。
      2. **单拍照刮板工位**：上一块板未让出工位前机器人不能完成取板
         ——轮询 scrape_Busy / collect_Busy 均 FALSE 才进入现场动作。
         这是协议 A（Done=99 = 板已送至工位）的 mock 端仿真保证，防止
         8 个缸同时以定时器并行“瞬移”到 99。
    这两重锁的存在保证：在 robot_pickup 实际完成前 Drain_Done 不会被错误置位，
    从而防止 mock 模式下展缸在硅胶板尚未离缸时就被释放给排队样品。
    """
    tank_id = tank_idx + 1
    try:
        # Phase A: Draining (state=50 已由 _tank_drain_fsm_loop 设置)
        await asyncio.sleep(DRAIN_DELAY_DRAINING)

        # Phase B: BlowAir
        await _set_tank_state_one(tank_state_node, tank_idx, 55)
        log.info("[TankDrain] Tank %d: Phase B 吹气清扫 (Tank_State=55)", tank_id)
        await asyncio.sleep(DRAIN_DELAY_BLOW_AIR)

        # Phase C: CylinderRetract
        await _set_tank_state_one(tank_state_node, tank_idx, 60)
        log.info("[TankDrain] Tank %d: Phase C 气缸退回 (Tank_State=60)", tank_id)
        await asyncio.sleep(DRAIN_DELAY_CYLINDER)

        # Phase D: RobotPickup（单台机器人串行 + 单拍照刮板工位排队）
        await _set_tank_state_one(tank_state_node, tank_idx, 65)
        log.info("[TankDrain] Tank %d: Phase D 等待机器人取板 (Tank_State=65)", tank_id)
        async with _robot_pickup_lock:
            # 抢到机器人后，还需等拍照刮板工位空闲才能完成取板动作。
            # 顺序故意：先抢机器人再等工位，等价于“该我的服务了，不过可能要等位”，
            # 避免多缸看到工位空后争抢机器人资源乱序。
            await _wait_scrape_workstation_idle(scrape_busy_node, collect_busy_node)
            log.info("[TankDrain] Tank %d: 拍照刮板工位空闲，机器人取板进行中…", tank_id)
            await asyncio.sleep(DRAIN_DELAY_ROBOT_PICK)
            # Done: state=99 + Drain_Done=TRUE（先 state 再 done，保证读到 Done=TRUE 时 state 一定是 99）
            await _set_tank_state_one(tank_state_node, tank_idx, 99)
            await _set_drain_done_one(tank_drain_dn_node, tank_idx, True)
        log.info(
            "[TankDrain] Tank %d: 排液完成 (Tank_State=99, Drain_Done=TRUE) — 硅胶板已送至拍照刮板工位",
            tank_id,
        )
    except Exception as e:
        log.warning("[TankDrain] Tank %d 排液 FSM 异常: %s", tank_id, e)


# ───────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────

_HELP_TEXT = """
Mock PLC 交互控制台
====================
命令:
  set <变量名> <值>   设置变量值（如: set PLC_Busy True / set Action_ID 1001）
  status              显示所有变量当前值
  tank                显示所有缸状态（Tank_State / Drain_Enable / Drain_Done）
  tank_state <n> <v>  设置第 n 号缸状态（如: tank_state 1 40）
  drain <n>           模拟第 n 号缸排液完成
  reset               重置所有变量为默认值
  done                快捷：置 PLC_Done=True, PLC_Busy=False
  busy                快捷：置 PLC_Busy=True
  error               快捷：置 PLC_Error=True
  error <stage>       Phase A：向指定工位 FSM 注入故障（_Step=90 _Error=TRUE）。如：error collect
  reset <stage>       Phase A：向指定工位 FSM 发 Reset 脉冲（清 Error + Step=0）。如：reset collect
  auto [on|off]       切换自动完成开关
  delay <秒>          设置自动完成延时
  estop / estop_on    模拟急停：PLC_EStop=True（上升沿触发上位机急停回调）
  estop_off           模拟急停解除：PLC_EStop=False
  mark_tank <N> needs_drain  [测试辅助] 模拟急停标记展缸：Tank_State[N]=91（实机PLC无此值）
  consumable fill           耗材架 12 板 DI 全 TRUE（IX11=0xFF, IX12=0x0F，模拟满架）
  consumable clear          耗材架 12 板 DI 全 FALSE（IX11=IX12=0，模拟空架）
  consumable plate <N> on|off  切单板 DI（N=1-12），演示“板被拔走”防呆告警
  consumable status         显示 IX11/IX12 两字节及解码后的 12 板状态
  （注意：孔级耗材账本走上位机 UI Consumable Tab，与本控制台无关）
  help                显示此帮助
  quit                退出

变量列表:
  PLC_Busy (bool, BusyAggregator 单写)
  collect_Enable/_Step/_Done/_Error/_Reset/_Busy (Phase A.1 工位六件套)
  collect_forward_instructions (string)  collect_count (int)
  Expand_Enable/_Step/_Done/_Error/_Reset/_Busy (v1.3 展开工位六件套)
  Expand_Target_Tank (int 1-8)  Expand_Mode_Flag / Expand_Group / Expand_Number 等
  Tank_State[1..8] / Tank_Drain_Enable[1..8] / Tank_Drain_Done[1..8] (v1.3 数组)
  Sampling_Enable/_Step/_Done/_Error/_Reset/_Busy (v1.4 上样点样工位六件套)
  Sampling_clean_instructions[1..2]/count  Sampling_prep_instructions[1..2] (v1.5 清洗+上样准备)
  Sampling_X/Y_coordinate  Sampling_sample/dispense_instructions[1..2] (v1.5 上样+点样)
  scrape_Enable/_Step/_Done/_Error/_Reset/_Busy (v1.5 拍照刮板工位六件套)
  scrape_Confirm (bool, 乒乓确认)  scrape_gcode_instructions (string, G-code指令)
  PLC_EStop (bool)
"""


async def _interactive_console(nodes: dict, auto_config: dict, stage_fsms: dict):
    """异步交互式控制台：手动控制 PLC 变量状态。"""
    loop = asyncio.get_event_loop()

    # 等待服务器就绪
    await asyncio.sleep(0.5)
    print(_HELP_TEXT)

    while True:
        try:
            line = await loop.run_in_executor(None, lambda: input("mock> "))
        except (EOFError, KeyboardInterrupt):
            log.info("[Console] 退出")
            break

        line = line.strip()
        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        try:
            if cmd == "help":
                print(_HELP_TEXT)

            elif cmd == "tank":
                # 显示所有缸状态
                st_arr = await nodes["Tank_State"].read_value()
                en_arr = await nodes["Tank_Drain_Enable"].read_value()
                dn_arr = await nodes["Tank_Drain_Done"].read_value()
                state_names = {0: "Idle", 10: "Prepping", 40: "Developing",
                               50: "Draining", 90: "Error", 91: "NEEDS_DRAIN", 99: "Done"}
                print("  ── 展缸状态 ──")
                for i in range(8):
                    st = int(st_arr[i])
                    name = state_names.get(st, f"Unknown({st})")
                    en = "EN" if en_arr[i] else "  "
                    dn = "DN" if dn_arr[i] else "  "
                    print(f"  Tank {i+1}: {name:12s} {en} {dn}")

            elif cmd == "tank_state":
                if len(parts) < 3:
                    print("  用法: tank_state <缸号1-8> <状态值>")
                    continue
                try:
                    tank_id = int(parts[1])
                    value = int(parts[2])
                    if not 1 <= tank_id <= 8:
                        print("  缸号必须在1-8范围")
                        continue
                except ValueError:
                    print("  参数必须是整数")
                    continue
                arr = list(await nodes["Tank_State"].read_value())
                arr[tank_id - 1] = value
                await nodes["Tank_State"].write_value(
                    ua.DataValue(ua.Variant(arr, ua.VariantType.Int16))
                )
                print(f"  Tank_State[{tank_id}] = {value}")
                log.info("[Console] Tank_State[%d] = %d", tank_id, value)

            elif cmd == "drain":
                if len(parts) < 2:
                    print("  用法: drain <缸号1-8>")
                    continue
                try:
                    tank_id = int(parts[1])
                    if not 1 <= tank_id <= 8:
                        print("  缸号必须在1-8范围")
                        continue
                except ValueError:
                    print("  参数必须是整数")
                    continue
                en_arr = list(await nodes["Tank_Drain_Enable"].read_value())
                en_arr[tank_id - 1] = True
                await nodes["Tank_Drain_Enable"].write_value(
                    ua.DataValue(ua.Variant(en_arr, ua.VariantType.Boolean))
                )
                print(f"  Tank_Drain_Enable[{tank_id}] = True")
                log.info("[Console] 模拟排液触发: Tank_Drain_Enable[%d]=True", tank_id)

            elif cmd == "set":
                if len(parts) < 3:
                    print("  用法: set <变量名> <值>")
                    continue
                var_name = parts[1]
                value_str = " ".join(parts[2:])
                if var_name not in nodes:
                    print(f"  未知变量: {var_name}")
                    print(f"  可用: {', '.join(sorted(_VAR_DEFAULTS.keys()))}")
                    continue
                try:
                    value, vtype = _parse_value(var_name, value_str)
                except (ValueError, TypeError) as e:
                    print(f"  解析失败: {e}")
                    continue
                await nodes[var_name].write_value(ua.DataValue(ua.Variant(value, vtype)))
                log.info("[Console] %s = %s", var_name, value)
                print(f"  {var_name} = {value}")

            elif cmd == "status":
                print("  ── PLC 变量状态 ──")
                for var_name in sorted(_VAR_DEFAULTS.keys()):
                    val = await nodes[var_name].read_value()
                    print(f"  {var_name:25s} = {val}")
                print(f"  auto_complete = {'ON' if auto_config['enabled'] else 'OFF'}  "
                      f"delay = {auto_config['delay']:.1f}s")

            elif cmd == "reset":
                # Phase A：`reset <stage>` 向工位 FSM 发 Reset 脉冲；无参数回落到旧语义（全量重置）
                if len(parts) >= 2:
                    stage_name = parts[1]
                    fsm = stage_fsms.get(stage_name)
                    if fsm is None:
                        print(f"  未知工位: {stage_name}（可用: {', '.join(stage_fsms) or '无'}）")
                    else:
                        reset_node = nodes.get(f"{stage_name}_Reset")
                        if reset_node is None:
                            print(f"  节点 {stage_name}_Reset 不存在")
                        else:
                            await reset_node.write_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                            await asyncio.sleep(0.15)
                            await reset_node.write_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                            print(f"  [{stage_name} FSM] Reset 脉冲已发送")
                    continue
                for var_name, (default, vtype) in _VAR_DEFAULTS.items():
                    await nodes[var_name].write_value(ua.DataValue(ua.Variant(default, vtype)))
                log.info("[Console] 所有变量已重置")
                print("  所有变量已重置为默认值")

            elif cmd == "done":
                # Phase C 后 PLC_Done 已废弃，仅保留 PLC_Busy 清零便于诊断 BusyAggregator
                await nodes["PLC_Busy"].write_value(ua.DataValue(ua.Variant(False, ua.VariantType.Boolean)))
                log.info("[Console] 手动清忙: PLC_Busy=False（旧 PLC_Done 已废弃）")
                print("  PLC_Busy=False（旧 PLC_Done 已废弃，工位完成请用 done <stage> 或自动完成）")

            elif cmd == "busy":
                await nodes["PLC_Busy"].write_value(ua.DataValue(ua.Variant(True, ua.VariantType.Boolean)))
                log.info("[Console] 手动置忙: PLC_Busy=True")
                print("  PLC_Busy=True")

            elif cmd == "error":
                # Phase A 后仅支持 `error <stage>`：向工位 FSM 注入故障（旧 PLC_Error 已删除）
                if len(parts) >= 2:
                    stage_name = parts[1]
                    fsm = stage_fsms.get(stage_name)
                    if fsm is None:
                        print(f"  未知工位: {stage_name}（可用: {', '.join(stage_fsms) or '无'}）")
                    else:
                        await fsm.inject_error()
                        print(f"  [{stage_name} FSM] 故障注入: _Step=90 _Error=TRUE")
                else:
                    print("  用法: error <stage>（旧全局 PLC_Error 已废弃，必须指定工位）")

            elif cmd == "auto":
                if len(parts) > 1 and parts[1].lower() in ("on", "off"):
                    auto_config["enabled"] = parts[1].lower() == "on"
                else:
                    auto_config["enabled"] = not auto_config["enabled"]
                state_str = "ON" if auto_config["enabled"] else "OFF"
                log.info("[Console] 自动完成: %s", state_str)
                print(f"  自动完成: {state_str}")

            elif cmd == "delay":
                if len(parts) < 2:
                    print(f"  当前延时: {auto_config['delay']:.1f}s")
                else:
                    try:
                        new_delay = float(parts[1])
                        if new_delay < 0:
                            raise ValueError
                        auto_config["delay"] = new_delay
                        log.info("[Console] 自动完成延时: %.1fs", new_delay)
                        print(f"  自动完成延时: {new_delay:.1f}s")
                    except ValueError:
                        print("  用法: delay <秒> (非负浮点数)")

            elif cmd in ("estop", "estop_on"):
                # 模拟急停：设置 PLC_EStop=TRUE（上升沿触发上位机 on_estop 回调）
                await nodes["PLC_EStop"].write_value(
                    ua.DataValue(ua.Variant(True, ua.VariantType.Boolean))
                )
                log.info("[Console] 急停触发: PLC_EStop=True")
                print("  PLC_EStop = True（急停已触发）")

            elif cmd == "estop_off":
                # 模拟急停解除：设置 PLC_EStop=FALSE
                await nodes["PLC_EStop"].write_value(
                    ua.DataValue(ua.Variant(False, ua.VariantType.Boolean))
                )
                log.info("[Console] 急停解除: PLC_EStop=False")
                print("  PLC_EStop = False（急停已解除）")

            elif cmd == "mark_tank":
                # [测试辅助] 模拟急停标记展缸：Tank_State[N]=91 (NEEDS_DRAIN)
                # ⚠ 注意：91=NEEDS_DRAIN 是 PC 侧虚拟状态，实机 PLC 永远不会产生此值。
                # 此命令仅用于模拟急停后 Recovery UI 的排液流程测试。
                if len(parts) < 3 or parts[2].lower() != "needs_drain":
                    print("  用法: mark_tank <缸号1-8> needs_drain")
                    continue
                try:
                    tank_id = int(parts[1])
                    if not 1 <= tank_id <= 8:
                        print("  缸号必须在1-8范围")
                        continue
                except ValueError:
                    print("  缸号必须是整数")
                    continue
                arr = list(await nodes["Tank_State"].read_value())
                arr[tank_id - 1] = 91
                await nodes["Tank_State"].write_value(
                    ua.DataValue(ua.Variant(arr, ua.VariantType.Int16))
                )
                log.info("[Console] Tank_State[%d] = 91 (NEEDS_DRAIN)", tank_id)
                print(f"  Tank_State[{tank_id}] = 91 (NEEDS_DRAIN)")

            elif cmd == "consumable":
                # 协议 v2.3（再修订）：耗材架板级 DI 走 IX11/IX12 两个 BYTE
                # 位序约定（CODESYS LSB）：
                #   IX11.bit0..bit7 = 检测1..8（粉末板1-6 + 玻璃瓶板1-2）
                #   IX12.bit0..bit3 = 检测9..12（玻璃瓶板3-6），bit4..7 保留
                if len(parts) < 2:
                    print("  用法: consumable <fill|clear|plate <N> on|off|status>")
                    continue
                sub = parts[1].lower()
                ix11_node = nodes["IX11"]
                ix12_node = nodes["IX12"]
                if sub == "fill":
                    await ix11_node.write_value(
                        ua.DataValue(ua.Variant(0xFF, ua.VariantType.Byte))
                    )
                    await ix12_node.write_value(
                        ua.DataValue(ua.Variant(0x0F, ua.VariantType.Byte))
                    )
                    log.info("[Console] IX11=0xFF, IX12=0x0F（12 板全 TRUE）")
                    print("  IX11=0xFF, IX12=0x0F（12 板全 TRUE，满架）")
                elif sub == "clear":
                    await ix11_node.write_value(
                        ua.DataValue(ua.Variant(0x00, ua.VariantType.Byte))
                    )
                    await ix12_node.write_value(
                        ua.DataValue(ua.Variant(0x00, ua.VariantType.Byte))
                    )
                    log.info("[Console] IX11=IX12=0（12 板全 FALSE）")
                    print("  IX11=IX12=0（12 板全 FALSE，空架）")
                elif sub == "plate":
                    # consumable plate <N> on|off 切单板 DI
                    if len(parts) < 4 or parts[3].lower() not in ("on", "off"):
                        print("  用法: consumable plate <N=1-12> on|off")
                        continue
                    try:
                        plate_n = int(parts[2])
                        if not 1 <= plate_n <= 12:
                            print("  板号必须在 1-12")
                            continue
                    except ValueError:
                        print("  板号必须是整数")
                        continue
                    target = parts[3].lower() == "on"
                    # 定位所在字节 + 位偏移（1-8 在 IX11 bit0..7；9-12 在 IX12 bit0..3）
                    if plate_n <= 8:
                        target_node = ix11_node
                        bit_idx = plate_n - 1
                        node_name = "IX11"
                    else:
                        target_node = ix12_node
                        bit_idx = plate_n - 9
                        node_name = "IX12"
                    cur = int(await target_node.read_value())
                    if target:
                        new_val = cur | (1 << bit_idx)
                    else:
                        new_val = cur & ~(1 << bit_idx) & 0xFF
                    await target_node.write_value(
                        ua.DataValue(ua.Variant(new_val, ua.VariantType.Byte))
                    )
                    log.info(
                        "[Console] %s.bit%d = %s → %s = 0x%02X【板 %d %s】",
                        node_name, bit_idx, target, node_name, new_val,
                        plate_n, "在位" if target else "离位",
                    )
                    print(
                        f"  {node_name}.bit{bit_idx} = {target} → {node_name} = 0x{new_val:02X}"
                        f"（板 {plate_n} {'在位' if target else '离位'}）"
                    )
                elif sub == "status":
                    ix11 = int(await ix11_node.read_value())
                    ix12 = int(await ix12_node.read_value())
                    # 解码为 12 个 bool
                    bits: list[bool] = [bool((ix11 >> i) & 1) for i in range(8)]
                    bits.extend(bool((ix12 >> i) & 1) for i in range(4))
                    print(f"  IX11 = 0x{ix11:02X} (bin {ix11:08b})")
                    print(f"  IX12 = 0x{ix12:02X} (bin {ix12:08b})  [bit4..7 保留位丢弃]")
                    print("  板级在位解码（●=在位, ○=离位）：")
                    for p_idx in range(12):
                        ctype = "粉末" if p_idx < 6 else "玻璃"
                        display_num = (p_idx + 1) if p_idx < 6 else (p_idx - 5)
                        sym = "●" if bits[p_idx] else "○"
                        src = "IX11" if p_idx < 8 else "IX12"
                        bit_idx = p_idx if p_idx < 8 else p_idx - 8
                        print(
                            f"  板 {display_num} ({ctype})：{sym}"
                            f"  ← %{src}.{bit_idx}"
                        )
                else:
                    print(
                        f"  未知子命令: {sub}（可用: fill, clear, plate <N> on|off, status）"
                    )

            elif cmd == "quit":
                log.info("[Console] 退出")
                break

            else:
                print(f"  未知命令: {cmd}，输入 help 查看帮助")

        except Exception as e:
            print(f"  命令执行失败: {e}")


# ──────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="pTLC Mock OPC UA PLC Server（调试用）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python mock/plc_server.py                     # 默认 0.5s 自动完成
  python mock/plc_server.py --delay 2.0         # 2 秒自动完成
  python mock/plc_server.py --no-auto           # 禁用自动完成（手动控制）
  python mock/plc_server.py --port 4841         # 自定义端口
""",
    )
    parser.add_argument(
        "--delay", type=float, default=0.5,
        help="自动完成延时（秒），默认 0.5",
    )
    parser.add_argument(
        "--no-auto", action="store_true",
        help="禁用自动完成（需手动 done 或 set PLC_Done True）",
    )
    parser.add_argument(
        "--port", type=int, default=4840,
        help="OPC UA 服务端口，默认 4840",
    )
    parser.add_argument(
        "--error-rate", type=float, default=0.0,
        help="动作报错概率（0.0~1.0），默认 0",
    )
    parser.add_argument(
        "--error-actions", type=str, default="",
        help="必定报错的 ActionID，逗号分隔（如: 2001,2002）",
    )
    args = parser.parse_args()

    error_actions = set()
    if args.error_actions:
        try:
            error_actions = {int(x.strip()) for x in args.error_actions.split(",")}
        except ValueError:
            log.warning("--error-actions 解析失败，忽略该参数")

    asyncio.run(run_server(
        delay=args.delay,
        auto_complete=not args.no_auto,
        port=args.port,
        error_rate=args.error_rate,
        error_actions=error_actions,
    ))


if __name__ == "__main__":
    main()
