"""配置数据模型
================
功能:
    定义 eit_ptlc 全部静态配置的 dataclass 结构与合法取值常量.
    本模块只声明结构, 不做 YAML 解析 (解析在 loader.py).
    迁移自 UI-Upper/core/config.py, 适配统一上位机控制架构:
    - 以 FastAPI ``api`` 取代旧 NiceGUI ``ui``
    - 以 ``control_mode`` 取代旧批处理 ``mode`` (pltc/collect/stress)
    - PLC 节点表外置到 plc_nodes.yaml, 经 ``PLCCfg.nodes_file`` 引用
    - 机器人默认 transport 改为 dobot_tcp (直连)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ----------------------------------------------------------------------
# 合法取值常量
# ----------------------------------------------------------------------

# 控制模式两态: DEBUG 可执行所有动作; RUN 不能执行调试功能 (设备手动操作)
ALLOWED_CONTROL_MODES = ("RUN", "DEBUG")
ALLOWED_PLATE_ORIENTATIONS = ("rot0", "rot90cw", "rot180", "rot270cw")
ALLOWED_ORIGIN_CORNERS = ("lower-left", "top-right", "top-left", "bottom-right")
ALLOWED_PATH_STRATEGIES = ("zigzag", "boustrophedon", "contour")
ALLOWED_ROBOT_TRANSPORTS = ("dobot_tcp",)  # 仅生产直连; 历史 modbus 传输已移除
# 双气工具动作 (gripper/rotary) 按动作到位确认模式: di=等DI / dwell=固定停顿 / di_or_dwell=先DI超时回退dwell
ALLOWED_TOOL_CONFIRM_MODES = ("di", "dwell", "di_or_dwell")

# CNC 点位数组长度 (与 controller/cnc_path SCRAPE_POINT_COUNT 同步, 列数需能整除)
PLC_CNC_ARRAY_LEN = 400

# OPC UA 合法变量类型名 (字符串形式, 解耦 driver 的 asyncua.VariantType)
# driver/opcua_driver.py 负责把这些名字映射为 ua.VariantType.
VALID_NODE_TYPES = frozenset({
    "Boolean", "SByte", "Byte",
    "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64",
    "Float", "Double", "String",
})


# ----------------------------------------------------------------------
# PLC 节点表 (来自 plc_nodes.yaml)
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class NodeSpec:
    """单个 OPC UA 节点声明.

    功能:
        描述 Host_Computer 下一个全局变量的类型与维度.
    参数:
        name: 变量名 (OPC UA BrowseName)
        var_type: 类型名, 取自 VALID_NODE_TYPES
        array_len: 0 表示标量, >0 表示 ARRAY[1..array_len]
        comment: 说明 (协议版本 / 用途)
        optional: 已知 PLC 端暂无该变量 (待建 / 仅 Mock 用). 连接后 browse 不到时只记 INFO,
                  不进"节点表声明但 PLC 端未发现"的 WARNING —— 让那行告警只在真漂移时响。
    """
    name: str
    var_type: str
    array_len: int = 0
    comment: str = ""
    optional: bool = False


@dataclass(frozen=True)
class PlcNodeMap:
    """PLC 节点表整体结构.

    功能:
        承载 OPC UA 全局变量容器路径与全部节点声明.
    参数:
        gvl_path: 从 Objects 起逐级 BrowseName 文本匹配到全局变量容器的路径
        heartbeat_node: 心跳读取节点名
        estop_node: 急停节点名
        nodes: 变量名到 NodeSpec 的映射
    """
    gvl_path: tuple[str, ...]
    heartbeat_node: str
    estop_node: str
    nodes: dict[str, NodeSpec]


# ----------------------------------------------------------------------
# 单点控制点表 (来自 manual_points.yaml)
# ----------------------------------------------------------------------

# 单点面板可挂载的工位键 = runtime/bootstrap._ALL_L2_STATIONS 各项 .lower(),
# 也就是设备节点 id 去掉 `plc.` 前缀 (见 node_registry.build_node_registry 的
# f"plc.{station.lower()}")。注意 StagingA -> "staginga", 没有下划线 ——
# 面板靠这个键从路由参数直接取点表, 拼错了面板就静默不显示。
MANUAL_STATIONS = frozenset({
    "sampling", "collect", "develop", "photoscrape",
    "feedlift", "pump", "rail", "staginga",
})


@dataclass(frozen=True)
class ManualRef:
    """单点控制对一个 PLC 变量的引用.

    参数:
        container: containers.names 里的容器键 (cylinder/servo/gvl/io/hmi/pcmanual)
        name: 变量 BrowseName (含中文, 逐字来自 PLC 声明)
        var_type: 类型名, 取自 VALID_NODE_TYPES
    """
    container: str
    name: str
    var_type: str = "Boolean"


@dataclass(frozen=True)
class ManualCylinder:
    """一个气缸 / 电磁阀的单点控制契约.

    全部执行器均为 FB_cylinder 单控模式 (cylinder_type=0), 故 manual/auto 是
    电平二态: TRUE=阀通电. fb_on/fb_off 缺失表示 PLC 该口悬空, 无到位传感器.
    """
    id: str
    label: str
    station: str
    manual: ManualRef
    auto_ro: Optional[ManualRef] = None
    fb_on: Optional[ManualRef] = None
    fb_off: Optional[ManualRef] = None
    alarm_bit: int = -1          # cyinderAlarm 的位号; -1 = PLC 未接 bAlarm
    note: str = ""


@dataclass(frozen=True)
class ManualAxis:
    """一根伺服轴的单点控制契约 (servoaxisdate.<struct> 结构体).

    jog_vel_fixed 是 PLC `伺服调用` 里硬编码进 FB_SERVOAXIS 的点动速度 ——
    <轴>DATE.fJogVel 并未接线, 上位机写它无效, 故此值只作只读显示。
    vel_max 限幅的是 fVelocity (已接线, 供绝对/相对定位)。
    """
    id: str
    label: str
    station: str
    struct: str
    jog_vel_fixed: float = 0.0
    vel_max: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class ManualPointMap:
    """单点控制点表整体结构.

    参数:
        root: 从 Objects 起到 Application 的 BrowseName 路径
        search: 容器所在层的候选前缀, 驱动按序探测 (GVL 挂 GlobalVars 下, PROGRAM 实例可能直挂 Application)
        containers: 容器键 -> 容器 BrowseName
        host: 握手变量名 (container/enable/keepalive/active/reject)
        globals_: 全局状态引用 (manual_auto/mode_state/cylinder_alarm/one_key_home)
        cylinders: id -> ManualCylinder (跨工位扁平, 保持 YAML 顺序)
        axes: id -> ManualAxis
        stations: YAML 中出现过的工位, 保持顺序
    """
    root: tuple[str, ...]
    search: tuple[tuple[str, ...], ...]
    containers: dict[str, str]
    host: dict[str, str]
    globals_: dict[str, ManualRef]
    cylinders: dict[str, ManualCylinder]
    axes: dict[str, ManualAxis]
    stations: tuple[str, ...]

    def station_cylinders(self, station: str) -> list[ManualCylinder]:
        return [c for c in self.cylinders.values() if c.station == station]

    def station_axes(self, station: str) -> list[ManualAxis]:
        return [a for a in self.axes.values() if a.station == station]


# ----------------------------------------------------------------------
# 设备 / 业务子配置
# ----------------------------------------------------------------------

@dataclass
class PLCCfg:
    """PLC OPC UA 连接与节点表引用."""
    url: str = "opc.tcp://localhost:4840"
    # 等待终态 = 订阅事件驱动 + 看门狗: action_timeout 为绝对上限(兜底病态挂死),
    # action_stall_timeout 为停滞判停(无任何 L2 状态推进多久判"结果不明确"). 二者均为统一阈值,
    # 与动作类型/参数无关 (慢动作只要 PLC 持续推进 Step/State 就不会误判).
    action_timeout: float = 600.0          # 单 L2 动作绝对上限 (秒)
    action_stall_timeout: float = 60.0     # 单 L2 动作停滞判停 (秒)
    # 软复核间隔(秒): 等待终态时镜像静默超过此值即直读一次对账, 兜底 OPC UA 订阅"漏推 delta 不自愈"
    # (report-on-change 水位线丢一次终态通知就永不重发, 详见 plc_controller._execute_one)。把漏推恢复
    # 从 action_stall_timeout(几十秒) 压到亚秒级; 0 = 关闭(退回旧的仅 stall 边界直读)。
    action_soft_recheck: float = 1.0       # 单 L2 动作镜像静默软复核间隔 (秒)
    # 订阅每监控项队列深度 + 采样间隔(ms, 0=最快): 降低漏推概率(溢出丢弃/快跳变漏采), 与软复核互补。
    subscription_queue_size: int = 10      # OPC UA 订阅每监控项队列深度
    subscription_sampling_ms: float = 0.0  # OPC UA 订阅采样间隔 (ms, 0=服务器最快)
    reconnect_wait_timeout: float = 60.0   # 心跳失联后等待重连恢复的最大秒数
    # ── asyncua 客户端参数 (必须显式给, 别吃库默认值) ──
    # asyncua 2.x 的 Client 默认 timeout=4 / watchdog_intervall=1.0, 且 connect() 会无条件起
    # 一个连接监管任务, 每 watchdog_intervall 秒探一次 server_state, 探测超时 =
    # min(session_timeout/2000, watchdog_intervall) —— session_timeout 默认 1 小时, 所以探测
    # 超时实际就等于 watchdog_intervall。默认值下只要 PLC 有一次应答慢过 1 秒, 整条会话即被
    # 判死 (auto_reconnect=False 时监管直接退出并把状态标成 DISCONNECTED, 此后每个请求抛
    # "client is disconnected", 尽管 TCP 还是好的), 驱动随之整条重建。嵌入式 OPC UA 服务端
    # 排队抖到秒级是常态, 故这两个值必须放宽。
    request_timeout: float = 10.0          # 单请求应答超时 (秒) -> Client(timeout=)
    watchdog_interval: float = 5.0         # 链路健康探测周期 = 探测超时 (秒) -> Client(watchdog_intervall=)
    # 单会话在途请求上限: 遥测(8 工位并发) + 实时回馈 20Hz + 动作 FSM 轮询全压一条会话,
    # 不限流会把服务端排队推过探测超时, 反噬成上面那条误判。心跳不走限流, 不会被业务读饿死。
    max_inflight_requests: int = 6         # <=0 表示不限流
    nodes_file: Path = Path("config/plc_nodes.yaml")
    # 运行期地轨随点自动到位 (地轨作为机器人点第7维 Win B; 见 docs 地轨点位合并管理_第7维_设计):
    # move_to_point 走臂前据目标点 rail 槽把地轨先移到位。默认关 = 保持真机现行为 (地轨仍由编排层
    # rail_move_safe 字面量驱动); 逐工位上真机 dry-run 验证后再逐步开, 全切完才删编排层字面量。
    auto_rail: bool = False


@dataclass(frozen=True)
class ToolActionConfirmCfg:
    """单个双气工具动作 (gripper-open/close, rotary-up/down) 作动后的到位确认策略.

    mode:
        di          -- 作动后等 DI 到位 (旧行为); 张开限位 DI2 可靠可达.
        dwell       -- 不等 DI, 改固定停顿 settle(dwell_ms); 闭合夹物件 DI1 不稳 / rotary DI 未现场校验.
        di_or_dwell -- 先等 DI, 超时回退 dwell.
    dwell_ms: dwell / di_or_dwell 回退时的固定到位停顿 (毫秒).
    """
    mode: str = "dwell"
    dwell_ms: int = 400


@dataclass
class ToolConfirmCfg:
    """四个双气工具动作的按动作到位确认 (替代单一全局 tool_di_feedback_enabled).

    现场依据: gripper 张开限位 (DI2) 可靠 → di; gripper 闭合限位 (DI1) 夹持物件时不可靠 → dwell;
    rotary DI 尚未现场校验 → 暂 dwell, 校验后只改本配置 mode: di 即可切回 (无需改代码).
    RobotCfg.tool_confirm 为 None (app.yaml 缺 tool_confirm 段) 时驱动回退旧全局开关行为.
    """
    gripper_open: ToolActionConfirmCfg = field(
        default_factory=lambda: ToolActionConfirmCfg(mode="di", dwell_ms=400))
    gripper_close: ToolActionConfirmCfg = field(
        default_factory=lambda: ToolActionConfirmCfg(mode="dwell", dwell_ms=400))
    rotary_up: ToolActionConfirmCfg = field(
        default_factory=lambda: ToolActionConfirmCfg(mode="dwell", dwell_ms=600))
    rotary_down: ToolActionConfirmCfg = field(
        default_factory=lambda: ToolActionConfirmCfg(mode="dwell", dwell_ms=600))


@dataclass
class RobotCfg:
    """机器人连接与安全策略; 生产路径为 Dobot TCP-IP-V4 直连."""
    transport: str = "dobot_tcp"           # 仅 dobot_tcp (生产直连)
    host: str = "192.168.0.15"
    # Dobot TCP-IP-V4 端口
    command_port: int = 29999              # dashboard 命令口
    feedback_port: int = 30004             # 实时反馈口
    move_port: int = 30003                 # 运动指令口
    error_http_port: int = 22000           # 官方 GetError HTTP 接口
    # 超时与轮询
    connect_timeout: float = 3.0
    command_timeout: float = 5.0
    action_timeout: float = 300.0
    ack_timeout: float = 10.0
    poll_interval: float = 0.05
    # 点表
    points_file: Path = Path("config/points/robot/robot_points.json")
    points_meta_file: Path = Path("config/points/robot/robot_points_meta.json")
    point_source_version: str = "v0.11"
    home_point: str = "robot-main.home"
    # 末端工具(夹爪)权威状态文件: 四态(0=无/1=吸盘/2=大夹爪/3=小夹爪)持久化真源,
    # 启动直接读盘恢复当前挂载 (不再人工重新声明); set_mounted_tool 写盘。
    tool_state_file: Path = Path("config/robot_tool_state.json")
    # 安全门控 (默认双重禁用, 避免自动掩盖现场状态)
    allow_enable_command: bool = False
    allow_clear_error_command: bool = False
    tool_di_feedback_enabled: bool = False
    tool_di_timeout: float = 10.0          # 工具动作 DI 到位确认等待上限(秒); 启用 tool_di_feedback 时生效
    # 按动作到位确认 (替代单一全局 tool_di_feedback_enabled): 每个双气工具动作各自 di/dwell/di_or_dwell.
    # None = app.yaml 未配置 tool_confirm 段 → 驱动回退全局 tool_di_feedback_enabled 旧行为 (向后兼容).
    tool_confirm: Optional[ToolConfirmCfg] = None
    # 全局速度比 SpeedFactor (1-100): connect 后下发, 影响点动与所有运动 (实际速度 = speed_factor% × 各命令 v%)
    speed_factor: int = 20
    # jog/step 默认运动参数
    jog_speed_percent: int = 20            # 点动速度百分比 1-100
    step_distance_mm: float = 1.0          # 步进默认线性增量 mm
    step_angle_deg: float = 1.0            # 步进默认关节/姿态增量 deg


@dataclass
class VisionCfg:
    """视觉分析与条带检测配置."""
    mock: bool = True
    output_dir: Path = Path("vision_output")
    image_plate_orientation: str = "rot0"  # 板物理朝向归一化
    auto_rectify_tilt: bool = False        # 板倾斜自动矫正
    rectify_min_angle_deg: float = 0.5
    min_row_score: float = 5.0
    image_plate_rotation_deg: float | None = None  # 固定 deskew 角(度); None=回落 auto_rectify_tilt 每帧现估


# DahengCameraService 默认参数 (与 app.yaml camera.daheng 段同步)
DAHENG_DEFAULTS: dict = {
    "ip": "192.168.0.169",
    "exposure_time": 500_000.0,
    "gain": 1.0,
    "pixel_format": "RGB8",
    "trigger_mode": "Off",
    "trigger_source": "Software",
    "timeout_ms": 5000,
    "width": 0,
    "height": 0,
    "offset_x": 0,
    "offset_y": 0,
    "auto_light_control": True,
    "light_line": "Line1",
    "uv_on_time_ms": 1000,
}


@dataclass
class PallasVisionCfg:
    """PALLASVision TCP 纠偏配置。"""
    enabled: bool = False
    mock: bool = True
    bridge_enabled: bool = False
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 18888
    bridge_timeout: float = 15.0
    host: str = "192.168.0.168"
    port: int = 8887
    trigger: str = "1"
    encoding: str = "utf-8"
    terminator: str = "none"          # none | cr | lf | crlf | nul
    result_mode: str = "callback"     # callback | reply
    listen_host: str = "0.0.0.0"
    listen_port: int = 18887
    connect_timeout: float = 3.0
    result_timeout: float = 10.0
    read_bytes: int = 4096
    err_fail_code: int = 111
    max_abs_xy_mm: float = 10.0
    max_abs_rz_deg: float = 5.0
    light_control_enabled: bool = True
    light_do_channel: int = 7
    light_settle_ms: int = 1000       # 开补光后、触发拍照前的稳定等待 (ms): 让机械臂到位残振衰减 + 补光到稳态再拍
    local_vision_enabled: bool = False  # 本地视觉临时替代 PALLAS TCP 的总开关; True 时 Bridge /capture 走 .163 相机+OpenCV (标定见 config/local_plate_vision.yaml)


@dataclass
class CameraCfg:
    """相机采集配置 (大恒 gxipy 或 Mock)."""
    mock: bool = True
    test_image: Path = Path("data/samples/case1/after.jpg")
    test_before_image: Optional[Path] = None
    daheng: dict = field(default_factory=lambda: dict(DAHENG_DEFAULTS))
    # 命名拍照 profile: {profile名: {部分 daheng 参数覆盖}}; camera 动作按 profile 预填,
    # 流程内 args 可逐项覆写, 解析见 CameraController.resolve_params。供 UI 预填/覆写/保存更新。
    profiles: dict = field(default_factory=dict)


@dataclass
class VisionDebugCfg:
    """独立视觉调试台配置: 只承载采集/工作区参数。

    识别参数 (image_plate_orientation/auto_rectify_tilt/rectify_min_angle_deg/min_row_score)
    统一由 config.vision 单一真源提供 —— 调试台默认由 config.vision 播种, 不再在此重复
    (见 memory: vision-tab-single-track)。
    """
    workspace_dir: Path = Path("eit_ptlc/var/vision_debug")
    default_exposure_time_us: int = 1_000_000
    default_gain: float = 1.0
    default_uv_on_time_ms: int = 1000


@dataclass
class ToolCfg:
    """刀具与收集瓶物理参数."""
    cutter_diameter_mm: float = 2.0
    # 刀径半径补偿(纯度优先): 刮扫中心路径内缩 R=刀半径+安全边, 刀刃外缘不越谱带轮廓,
    # 大刀径不刮进相邻杂带。默认关=零回归; 真机 app.yaml 显式开。收集路径不受影响。
    cutter_compensation: bool = False
    compensation_margin_mm: float = 0.0  # 额外纯度安全边(mm/单侧), 补视觉分割边界误差, [0,10]
    bottle_diameter_mm: float = 5.0
    bottle_x_offset_mm: float = 85.0
    bottle_y_offset_mm: float = 0.0   # 铣刀↔收集器 Y 向装配偏移补偿(只作用收集路径, 默认0=零行为变化)


@dataclass
class ScrapeCfg:
    """多层刮取工艺参数."""
    total_depth_mm: float = 1.0
    num_passes: int = 1
    overlap_ratio: float = 0.4
    feed_rate: int = 800
    # 松散系数: 刮下来的硅胶粉相对板上压实涂层的堆积膨胀倍数。
    # **只作用于物料账本与三维显示的体积估算**, 不进任何路径 / 切深 / PLC 计算 ——
    # 改它绝不会改变刮取动作。默认 1.0 = 按压实层体积记(零回归, 与 cutter_compensation /
    # collector_x_positive / machine_y_min_mm 同一条"新参数默认不改行为"的约定);
    # 真机在 app.yaml 显式给实测值。
    bulk_factor: float = 1.0


@dataclass
class CollectionCfg:
    """尾端粉末收集参数."""
    return_sweep: bool = True  # True=拖尾正向补收 + 残粉 −X 回走(全面); False=仅拖尾(旧行为)


def default_water_level_payload_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "driver" / "water_level_payload"


@dataclass
class GCodeCfg:
    """G-code / CNC 路径生成参数 (真机标定 + 工艺参数). Z 正方向 = 向下."""
    origin_corner: str = "lower-left"
    plate_origin_x: float = 0.0
    plate_origin_y: float = 0.0
    plate_surface_z_mm: float = 7.0
    align_clearance_mm: float = 2.5     # 对位检查高度余量(mm): 检查Z = plate_surface_z_mm − 此值; 不立第二刀长源
    path_strategy: str = "boustrophedon"
    boustrophedon_columns: int = 20
    scrape_keep_ratio: float = 1.0
    collect_margin_mm: float = 4.0
    collect_expand_ratio: float = 1.0   # 收集 Y 乘性包络(治硅胶崩飞): y_half=ratio×带半高+(margin−桶口半径); 1.0=仅绝对余量
    machine_y_min_mm: float | None = None  # 机床 Y 软下限(mm): 非 None 时刮取/收集 Y 钳到此值+告警, 防撞机(点样线底边 <5mm 余量); None=关(零回归)
    # 收集器(粉桶)相对铣刀的机床 X 侧: true=收集器在 +X 侧(本机硬件)。收集拖尾/回走几何是在
    # flip_x=True 的规范帧调参的; 当 origin_corner 的 flip_x 与收集器侧不符(如 rot0/lower-left+收集器+X)
    # 时, generate_scrape_arrays 把整条路径 X 镜像回规范帧(保刮取机床位置不变), 使收集朝 band 反侧正确落。
    # 默认 false = legacy(不镜像, 保持 lower-left 既有行为零回归); 真机按硬件在 app.yaml 显式设 true。
    collector_x_positive: bool = False
    tool: ToolCfg = field(default_factory=ToolCfg)
    scrape: ScrapeCfg = field(default_factory=ScrapeCfg)
    collection: CollectionCfg = field(default_factory=CollectionCfg)


@dataclass
class WaterLevelCfg:
    """液位检测模块 MQTT + MJPEG + 香橙派 SSH 远程管理配置."""
    enabled: bool = False
    broker_ip: str = "192.168.0.168"
    broker_port: int = 1883
    stream_port: int = 7070            # 香橙派 MJPEG HTTP 服务端口
    orangepi_ip: str = "192.168.0.60"  # 用于构造 MJPEG URL
    ssh_user: str = "orangepi"
    ssh_ip: str = ""                   # 空则取 orangepi_ip
    work_dir: str = "Desktop/work"
    script_name: str = "run.sh"
    payload_dir: Path = field(default_factory=default_water_level_payload_dir)
    auto_start: bool = False
    start_timeout: float = 30.0
    # 香橙派抓帧脚本启动参数 (start_remote 注入到 run.sh; run.sh 为纯透传 `python3 ... "$@"`).
    # cameras / tl_bl_cm 是脚本 argparse 必填项 — 缺失则脚本启动即退出, 故必须由此真源下发.
    cameras: str = (
        "/dev/camera1,/dev/camera2,/dev/camera3,/dev/camera4,"
        "/dev/camera5,/dev/camera6,/dev/camera7,/dev/camera8"
    )
    tl_bl_cm: float = 15.0             # QR TL-BL 实距(cm); argparse 必填, --no-detect 下不参与检测
    cap_width: int = 1920              # 采集分辨率 (归一化 ROI 后检测与此解耦; 见 waterlevel_detector.roi_frac)
    cap_height: int = 1080
    cap_fps: int = 30                  # 采集帧率; 液位慢过程可降 (10/5) 省 USB 等时预留带宽
    # 手动曝光/白平衡定值 (香橙派侧 v4l2 锁死, 见 payload ChannelDetector._lock_camera_controls).
    # 上位机差分检测的判湿阈值只有 5%, 自动曝光一动整块 ROI 就同时翻成"已浸润" —— 2026-07-26
    # 真机实测 CH1 出现 6 秒内 0%→100%→0% 整体翻转并骗过 wait_level 触发自动排液, 故一律锁死.
    exposure_time: int = 312           # v4l2 exposure_time_absolute (1~10000, 单位100us); 实测均亮约165
    awb_temp: int = 4600               # v4l2 white_balance_temperature (2800~6500); 设备出厂值
    no_detect: bool = True             # 检测已搬上位机: 香橙派只抓帧 (省算力)
    # 上位机拉帧检测 (检测从香橙派搬到上位机后启用)
    detect_interval: float = 2.0       # 拉帧检测周期 (s); 溶剂前沿非时间敏感任务
    # 并发采集相机数上限 (0=不限). 8 路 UVC 同开会顶爆香橙派 USB2 带宽/供电致整段丢流 (现场 wl.log
    # 实证 CH5/6/7 同时挂且永不自愈). >0 时上位机只激活 pinned(录制/查看中)+低号补齐至此数, 其余停用;
    # 网格总览超上限的通道显示"无信号". 硬件确能稳开 8 路(分散 USB 控制器/带供电 hub)则保持 0.
    max_active_channels: int = 0
    calib_path: Optional[Path] = None  # 标定真源 JSON; None → config 目录下 water_level_calib.json
    # 单通道原始录制 (Phase 0; 为回放 + 离线整定而生): 录制根目录, None → <repo_root>/data/water_level_recordings
    recordings_dir: Optional[Path] = None


@dataclass
class CodesysCfg:
    """CODESYS(InoProShop SP11) 工程编辑/编译/部署自动化配置.

    功能:
        后端经文件 IPC 驱动一个带 UI 的 InoProShop 常驻 worker(复用 tools/codesys-mcp/worker_body.py),
        实现 web 端 POU 读写 / 编译 / 部署到真机 PLC. 仅 real 模式按 enabled 装配, sim 不装配.
    字段:
        enabled: 是否装配该服务(real 默认关, 现场需 web 编辑/部署时显式开)
        allow_deploy: 是否允许下发部署到真机(Phase 0 spike 验证通过前保持关, 部署端点返回 503)
        exe: InoProShop.exe 绝对路径
        profile: CODESYS profile 名(决定内核版本)
        project: .project 工程文件路径(相对 config 目录解析为绝对路径)
        ipc_dir: 文件 IPC 目录(相对 config 目录解析为绝对路径), 用于与 MCP server 共享 worker
        compile_category: 编译消息类别 GUID(从该类别取 error/warning)
        idle_timeout: worker 空闲超时秒数(注入 worker); >0 时无请求超时即关闭 InoProShop 释放工程锁,
                      多客户端(MCP+后端)共享同一实例; 0=常驻永不自关(人机共用同一窗口, 接管/释放
                      换手; 现场 app.yaml 用 0)。接管(manual_control)期间 worker 冻结空闲计时不自关。
        session_idle_release: 会话属主(session.owner)空闲接管阈值秒数; 属主最近一次写类 op 距今
                      超过该值即视为空闲, 可被其它自动方抢占。须 > agent 两次 op 的正常间隔(含模型
                      思考+编译等待), 否则还在干活的 agent 会被误抢。与 server.mjs 同名阈值同值。
        session_wait_timeout: 想抢占的一方轮询阻塞的最长秒数, 超时抛忙(与编译超时同量级)。
        session_max_hold: 单个属主持有的硬上限秒数(逃生阀), 防显式持有方崩溃后残留把实例钉死。
    """
    enabled: bool = False
    allow_deploy: bool = False
    exe: str = "D:/InoProShop/CODESYS/Common/InoProShop.exe"
    profile: str = "InoProShop(V1.9.1.6)"
    project: Path = Path("../plc/20260702.project")
    ipc_dir: Path = Path("../var/codesys-ipc")
    compile_category: str = "97f48d64-a2a3-4856-b640-75c046e37ea9"
    idle_timeout: float = 120.0
    # 会话属主租约阈值(秒); 与 codesys_ipc._SESSION_* / server.mjs 同名常量同值(跨语言镜像)
    session_idle_release: float = 60.0
    session_wait_timeout: float = 300.0
    session_max_hold: float = 900.0


@dataclass
class ApiCfg:
    """FastAPI + WebSocket 后端服务配置 (取代旧 NiceGUI ui)."""
    enabled: bool = True
    host: str = "0.0.0.0"              # 0.0.0.0 允许局域网访问
    port: int = 18080
    cors_origins: list = field(default_factory=lambda: ["http://localhost:15173"])  # Vue3 dev


@dataclass
class ExperimentCfg:
    """并行实验系统配置 (批量样品调度 + 实验数据库).

    字段:
        db_path:   experiments.db 路径; None 则由 bootstrap 落到 var/experiments.db
                   (独立库文件, 绝不并入会 LRU 淘汰的 runs.db)
        wip_limit: 同时在制样品数默认上限 (批次提交可覆盖); 限的是"已开跑未走完"的样品数,
                   防止前段无节制进料把停放位/耗材占满
        tank_pool: 调度器可分配的展开缸号全集 (批次提交可再取子集); 缸号 1-8
        recipe:    默认并行配方名 (config/recipes/<name>.yaml)
    """
    db_path: Optional[Path] = None
    wip_limit: int = 3
    tank_pool: tuple = (1, 2, 3, 4, 5, 6, 7, 8)
    recipe: str = "parallel_v1"


@dataclass
class ThreeDCfg:
    """
    功能:
        配置三维工程工作区, 供上位机读取模型资产并执行受管 authoring 操作.

    参数:
        workspace_root: 上位机仓库内的三维模块根目录.
        hardware_root: 仓库外的 TLC 自动化设备原始文件目录.

    返回:
        ThreeDCfg 配置对象.
    """
    workspace_root: Path = Path("../three_d")
    hardware_root: Path = Path("E:/eit_lab/eit_lab_hardware/eit_ptlc_station")


@dataclass
class AppConfig:
    """顶层应用配置."""
    control_mode: str = "DEBUG"        # RUN | DEBUG
    plc: PLCCfg = field(default_factory=PLCCfg)
    robot: RobotCfg = field(default_factory=RobotCfg)
    vision: VisionCfg = field(default_factory=VisionCfg)
    pallas_vision: PallasVisionCfg = field(default_factory=PallasVisionCfg)
    camera: CameraCfg = field(default_factory=CameraCfg)
    vision_debug: VisionDebugCfg = field(default_factory=VisionDebugCfg)
    gcode: GCodeCfg = field(default_factory=GCodeCfg)
    water_level: WaterLevelCfg = field(default_factory=WaterLevelCfg)
    codesys: CodesysCfg = field(default_factory=CodesysCfg)
    api: ApiCfg = field(default_factory=ApiCfg)
    experiment: ExperimentCfg = field(default_factory=ExperimentCfg)
    three_d: ThreeDCfg = field(default_factory=ThreeDCfg)
    default_recipe: Optional[str] = None
    recipes_dir: Path = Path("config/recipes")
