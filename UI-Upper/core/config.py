"""
AppConfig - YAML 配置加载
==========================
Batch 5 集成入口的配置结构。

使用方式：
    cfg = load_config(Path("config.example.yaml"))
    print(cfg.mode, cfg.plc.url)

字段缺失时回落到默认值；仅对关键字段（mode / samples 非空时 id）做最小校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml


# ----------------------------------------------------------------------
# 子配置
# ----------------------------------------------------------------------


@dataclass
class PLCCfg:
    url: str = "opc.tcp://localhost:4840"
    action_timeout: float = 15.0
    reconnect_wait_timeout: float = 60.0


_ALLOWED_PLATE_ORIENTATIONS = ("rot0", "rot90cw", "rot180", "rot270cw")


@dataclass
class VisionCfg:
    mock: bool = True
    output_dir: Path = Path("vision_output")
    # 板坐标系姿态归一化（新工位适配）：图像中板的物理朝向
    image_plate_orientation: str = "rot0"  # rot0 | rot90cw | rot180 | rot270cw
    auto_rectify_tilt: bool = False         # 板倾斜自动矫正（minAreaRect + warpAffine）
    rectify_min_angle_deg: float = 0.5      # 小于此角度不做 warp（避免无谓插值损失）


# DahengCameraService 默认参数（与 config.example.yaml camera.daheng 段同步）
_DAHENG_DEFAULTS: dict = {
    "ip": "192.168.0.169",
    "exposure_time": 500_000.0,
    "gain": 1.0,
    "pixel_format": "RGB8",
    "trigger_mode": "Off",
    "timeout_ms": 5000,
    "width": 0,
    "height": 0,
    "offset_x": 0,
    "offset_y": 0,
    "auto_light_control": True,   # 拍照前开光源，拍照后关（保护光源寿命）
    "light_line": "Line1",        # 光源物理 I/O 线（Line1=Pin7/8 光耦输出）
}


@dataclass
class CameraCfg:
    mock: bool = True                        # True=MockCameraService, False=DahengCameraService
    test_image: Path = Path("data/samples/case1/after.jpg")  # Mock 模式预置图路径
    test_before_image: Optional[Path] = None  # Mock 模式 before 预置图路径（可选，双帧调试用）
    daheng: dict = field(default_factory=lambda: dict(_DAHENG_DEFAULTS))  # DahengCameraService 参数


@dataclass
class UICfg:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class SampleCfg:
    id: str
    before: Path = Path("before.png")
    after: Path = Path("after.png")
    action_timeout: Optional[float] = None  # None 表示使用 PLCCfg.action_timeout
    recipe: Optional[str] = None            # Batch 6 Phase C：Recipe 名称（recipes/<name>.yaml）


@dataclass
class StressCfg:
    duration_sec: int = 7200
    interval_sec: float = 1.0


@dataclass
class LoggingPersistenceCfg:
    """P2-1：日志持久化配置。"""
    enabled: bool = True
    flush_interval_sec: float = 0.5
    batch_size: int = 10
    archive_older_than_days: int = 30


@dataclass
class LoggingCfg:
    persistence: LoggingPersistenceCfg = field(default_factory=LoggingPersistenceCfg)


@dataclass
class WaterLevelCfg:
    """液位检测模块 MQTT + MJPEG + 香橙派 SSH 远程管理配置。"""
    enabled: bool = False
    broker_ip: str = "192.168.10.226"
    broker_port: int = 1883
    stream_port: int = 8080
    orangepi_ip: str = "192.168.10.200"
    # SSH 远程管理
    ssh_user: str = "orangepi"
    ssh_ip: str = ""              # 空则取 orangepi_ip
    work_dir: str = "Desktop/work"
    script_name: str = "run.sh"
    auto_start: bool = False      # True=主程序启动时自动 SSH 拉起远程脚本
    start_timeout: float = 30.0   # 等待香橙派 MQTT online 的超时秒数


@dataclass
class DatabaseCfg:
    """SQLite 二级索引层配置。"""
    enabled: bool = True
    path: str = "data/tlc_data.sqlite"


@dataclass
class RobotCfg:
    """机器人 transport 与安全策略；默认保持现有 Modbus Lua MVP。"""
    transport: str = "modbus"  # modbus | dobot_tcp
    host: str = "192.168.0.15"
    modbus_port: int = 502
    modbus_unit_id: int = 1
    modbus_byte_order: str = "word-swap"
    command_port: int = 29999
    feedback_port: int = 30004
    error_http_port: int = 22000
    connect_timeout: float = 3.0
    command_timeout: float = 5.0
    action_timeout: float = 300.0
    poll_interval: float = 0.05
    point_source: Path = Path("../机器人程序/机器人程序v0.11/roboprogram/point.json")
    point_meta: Path = Path("config/robot_points_meta.json")
    flow_source: Path = Path("config/robot_flows_v2.yaml")
    host_action_source: Path = Path("config/robot_host_actions.json")
    point_source_version: str = "v0.11"
    home_point: str = "robot-main.home"
    allow_enable_command: bool = False
    allow_clear_error_command: bool = False
    tool_di_feedback_enabled: bool = False


_ALLOWED_ORIGIN_CORNERS = ("lower-left", "top-right", "top-left", "bottom-right")
_ALLOWED_PATH_STRATEGIES = ("zigzag", "boustrophedon", "contour")
_PLC_CNC_ARRAY_LEN = 400  # 与 core.cnc_path_generator.SCRAPE_POINT_COUNT 同步；列数需能整除


@dataclass
class ToolCfg:
    """刀具与收集瓶物理参数。"""
    cutter_diameter_mm: float = 2.0
    bottle_diameter_mm: float = 5.0
    bottle_x_offset_mm: float = 85.0


@dataclass
class ScrapeCfg:
    """多层刮取工艺参数。"""
    total_depth_mm: float = 1.0
    num_passes: int = 1
    overlap_ratio: float = 0.4
    feed_rate: int = 800
    plunge_rate: int = 200


@dataclass
class CollectionCfg:
    """尾端粉末收集参数。"""
    overlap_ratio: float = 0.5
    feed_rate: int = 800
    mode: str = "per_pass"  # per_pass | final

    def __post_init__(self):
        if self.mode not in ("per_pass", "final"):
            raise ValueError(f"collection.mode 必须是 per_pass 或 final，得到 {self.mode!r}")


@dataclass
class GCodeCfg:
    """G-code 生成参数（真机标定 + 工艺参数）。"""
    origin_corner: str = "lower-left"
    plate_origin_x: float = 0.0
    plate_origin_y: float = 0.0
    # Z 轴（Z 正=向下，物理机床约定）
    plate_surface_z_mm: float = 7.0
    safe_z_mm: float = 5.0
    approach_z_mm: float = 6.5
    # CNC 主方案路径策略（与 core.cnc_path_generator._PATH_DISPATCH 同步）
    path_strategy: str = "boustrophedon"
    boustrophedon_columns: int = 20  # 作为列数上限提示；实际列数由 cutter_diameter × overlap_ratio 自动推导
    # contour 策略下：每列长度的保留比例（0,1]；以列重心为中心两侧各扩 列长×k/2
    scrape_keep_ratio: float = 1.0
    # 收集路径 Y 方向全局膨胀比（1.0=与刮取 bbox 一致，>1.0=扩大收集范围，通过 bbox 放大实现）
    collect_expand_ratio: float = 1.0
    # 子配置
    tool: ToolCfg = field(default_factory=ToolCfg)
    scrape: ScrapeCfg = field(default_factory=ScrapeCfg)
    collection: CollectionCfg = field(default_factory=CollectionCfg)


@dataclass
class AppConfig:
    mode: str = "pltc"  # pltc | collect | stress
    plc: PLCCfg = field(default_factory=PLCCfg)
    vision: VisionCfg = field(default_factory=VisionCfg)
    camera: CameraCfg = field(default_factory=CameraCfg)
    ui: UICfg = field(default_factory=UICfg)
    samples: List[SampleCfg] = field(default_factory=list)
    stress: StressCfg = field(default_factory=StressCfg)
    # collect 模式下的 case 数量（mode=collect 时生效）
    collect_count: int = 1
    # Batch 6 Phase C：样品未指定 recipe 时的全局默认（None=向后兼容走 Batch 2 SampleTask）
    default_recipe: Optional[str] = None
    # Batch 6 Phase C：Recipe 库根目录（相对于 main.py 所在目录）
    recipes_dir: Path = Path("recipes")
    # P2-1：日志持久化配置
    logging: LoggingCfg = field(default_factory=LoggingCfg)
    # SQLite 二级索引层配置
    database: DatabaseCfg = field(default_factory=DatabaseCfg)
    # G-code 生成参数（真机标定相关）
    gcode: GCodeCfg = field(default_factory=GCodeCfg)
    # 液位检测模块 MQTT + MJPEG 配置
    water_level: WaterLevelCfg = field(default_factory=WaterLevelCfg)
    # 机器人直连配置；主业务尚未自动启用，仅供动作服务和验收 CLI 使用
    robot: RobotCfg = field(default_factory=RobotCfg)


# ----------------------------------------------------------------------
# 加载
# ----------------------------------------------------------------------


_ALLOWED_MODES = {"pltc", "collect", "stress"}


def _parse_bool(value: object, default: bool) -> bool:
    """将 YAML 来源的值安全解析为 Python bool。

    Python 内置 ``bool()`` 将任意非空字符串（包括 ``"false"``, ``"0"``,
    ``"no"``, ``"off"``）视为 ``True``，这对配置解析是危险的。
    本函数只接受显式的布尔表示。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    raise ValueError(
        f"期望布尔值 (true/false, 1/0, yes/no, on/off)，实际: {value!r}"
    )


def load_config(path: Path) -> AppConfig:
    """从 YAML 文件加载配置；字段缺失使用默认值。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"配置文件根节点必须是 mapping，得到 {type(raw).__name__}")

    mode = str(raw.get("mode", "pltc")).strip().lower()
    if mode not in _ALLOWED_MODES:
        raise ValueError(f"mode 必须是 {_ALLOWED_MODES} 之一，得到: {mode}")

    plc = _parse_plc(raw.get("plc") or {})
    vision = _parse_vision(raw.get("vision") or {})
    camera = _parse_camera(raw.get("camera") or {})
    ui = _parse_ui(raw.get("ui") or {})
    samples = _parse_samples(raw.get("samples") or [])
    stress = _parse_stress(raw.get("stress") or {})
    collect_count = int(raw.get("collect_count", 1))
    default_recipe = raw.get("default_recipe")
    default_recipe = str(default_recipe).strip() if default_recipe else None
    recipes_dir = Path(raw.get("recipes_dir", "recipes"))
    logging_cfg = _parse_logging(raw.get("logging") or {})
    database_cfg = _parse_database(raw.get("database") or {})
    gcode_cfg = _parse_gcode(raw.get("gcode") or {})
    water_level_cfg = _parse_water_level(raw.get("water_level") or {})
    robot_cfg = _parse_robot(raw.get("robot") or {})

    return AppConfig(
        mode=mode,
        plc=plc,
        vision=vision,
        camera=camera,
        ui=ui,
        samples=samples,
        stress=stress,
        collect_count=collect_count,
        default_recipe=default_recipe,
        recipes_dir=recipes_dir,
        logging=logging_cfg,
        database=database_cfg,
        gcode=gcode_cfg,
        water_level=water_level_cfg,
        robot=robot_cfg,
    )


# ----------------------------------------------------------------------
# 子节点解析
# ----------------------------------------------------------------------


def _parse_plc(d: dict) -> PLCCfg:
    return PLCCfg(
        url=str(d.get("url", PLCCfg.url)),
        action_timeout=float(d.get("action_timeout", PLCCfg.action_timeout)),
        reconnect_wait_timeout=float(d.get("reconnect_wait_timeout", PLCCfg.reconnect_wait_timeout)),
    )


def _parse_vision(d: dict) -> VisionCfg:
    orientation = str(d.get("image_plate_orientation", VisionCfg.image_plate_orientation)).strip().lower()
    if orientation not in _ALLOWED_PLATE_ORIENTATIONS:
        raise ValueError(
            f"vision.image_plate_orientation 必须是 {_ALLOWED_PLATE_ORIENTATIONS} 之一，"
            f"得到: {orientation!r}"
        )
    return VisionCfg(
        mock=_parse_bool(d.get("mock"), True),
        output_dir=Path(d.get("output_dir", "vision_output")),
        image_plate_orientation=orientation,
        auto_rectify_tilt=_parse_bool(d.get("auto_rectify_tilt"), VisionCfg.auto_rectify_tilt),
        rectify_min_angle_deg=float(d.get("rectify_min_angle_deg", VisionCfg.rectify_min_angle_deg)),
    )


def _parse_camera(d: dict) -> CameraCfg:
    before_img = d.get("test_before_image")
    # 解析 daheng 子段：深合并到默认值之上，缺失字段保留默认值
    daheng_raw = d.get("daheng") or {}
    daheng = {
        **_DAHENG_DEFAULTS,
        **({k: v for k, v in daheng_raw.items() if k in _DAHENG_DEFAULTS}
           if isinstance(daheng_raw, dict) else {}),
    }
    return CameraCfg(
        mock=_parse_bool(d.get("mock"), True),
        test_image=Path(d.get("test_image", str(CameraCfg.test_image))),
        test_before_image=Path(before_img) if before_img else None,
        daheng=daheng,
    )


def _parse_ui(d: dict) -> UICfg:
    return UICfg(
        enabled=_parse_bool(d.get("enabled"), True),
        host=str(d.get("host", "0.0.0.0")),
        port=int(d.get("port", 8080)),
    )


def _parse_samples(items: list) -> List[SampleCfg]:
    result: List[SampleCfg] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            raise ValueError(f"samples[{i}] 必须是 mapping")
        sid = str(it.get("id") or "").strip()
        if not sid:
            raise ValueError(f"samples[{i}].id 不能为空")
        action_to = it.get("action_timeout")
        recipe_name = it.get("recipe")
        recipe_name = str(recipe_name).strip() if recipe_name else None
        result.append(SampleCfg(
            id=sid,
            before=Path(it.get("before", "before.png")),
            after=Path(it.get("after", "after.png")),
            action_timeout=float(action_to) if action_to is not None else None,
            recipe=recipe_name,
        ))
    return result


def _parse_stress(d: dict) -> StressCfg:
    return StressCfg(
        duration_sec=int(d.get("duration_sec", StressCfg.duration_sec)),
        interval_sec=float(d.get("interval_sec", StressCfg.interval_sec)),
    )


def _parse_logging(d: dict) -> LoggingCfg:
    persistence_raw = d.get("persistence") or {}
    persistence = LoggingPersistenceCfg(
        enabled=_parse_bool(persistence_raw.get("enabled"), LoggingPersistenceCfg.enabled),
        flush_interval_sec=float(persistence_raw.get(
            "flush_interval_sec", LoggingPersistenceCfg.flush_interval_sec
        )),
        batch_size=int(persistence_raw.get(
            "batch_size", LoggingPersistenceCfg.batch_size
        )),
        archive_older_than_days=int(persistence_raw.get(
            "archive_older_than_days", LoggingPersistenceCfg.archive_older_than_days
        )),
    )
    return LoggingCfg(persistence=persistence)


def _parse_water_level(d: dict) -> WaterLevelCfg:
    return WaterLevelCfg(
        enabled=_parse_bool(d.get("enabled"), False),
        broker_ip=str(d.get("broker_ip", WaterLevelCfg.broker_ip)),
        broker_port=int(d.get("broker_port", WaterLevelCfg.broker_port)),
        stream_port=int(d.get("stream_port", WaterLevelCfg.stream_port)),
        orangepi_ip=str(d.get("orangepi_ip", WaterLevelCfg.orangepi_ip)),
        ssh_user=str(d.get("ssh_user", WaterLevelCfg.ssh_user)),
        ssh_ip=str(d.get("ssh_ip", WaterLevelCfg.ssh_ip)),
        work_dir=str(d.get("work_dir", WaterLevelCfg.work_dir)),
        script_name=str(d.get("script_name", WaterLevelCfg.script_name)),
        auto_start=_parse_bool(d.get("auto_start"), False),
        start_timeout=float(d.get("start_timeout", WaterLevelCfg.start_timeout)),
    )


def _parse_database(d: dict) -> DatabaseCfg:
    return DatabaseCfg(
        enabled=_parse_bool(d.get("enabled"), DatabaseCfg.enabled),
        path=str(d.get("path", DatabaseCfg.path)),
    )


def _parse_robot(d: dict) -> RobotCfg:
    transport = str(d.get("transport", RobotCfg.transport)).strip().lower()
    if transport not in {"modbus", "dobot_tcp"}:
        raise ValueError("robot.transport 必须是 modbus 或 dobot_tcp")
    byte_order = str(d.get("modbus_byte_order", RobotCfg.modbus_byte_order)).strip()
    if byte_order not in {"be", "word-swap"}:
        raise ValueError("robot.modbus_byte_order 必须是 be 或 word-swap")
    cfg = RobotCfg(
        transport=transport,
        host=str(d.get("host", RobotCfg.host)),
        modbus_port=int(d.get("modbus_port", RobotCfg.modbus_port)),
        modbus_unit_id=int(d.get("modbus_unit_id", RobotCfg.modbus_unit_id)),
        modbus_byte_order=byte_order,
        command_port=int(d.get("command_port", RobotCfg.command_port)),
        feedback_port=int(d.get("feedback_port", RobotCfg.feedback_port)),
        error_http_port=int(d.get("error_http_port", RobotCfg.error_http_port)),
        connect_timeout=float(d.get("connect_timeout", RobotCfg.connect_timeout)),
        command_timeout=float(d.get("command_timeout", RobotCfg.command_timeout)),
        action_timeout=float(d.get("action_timeout", RobotCfg.action_timeout)),
        poll_interval=float(d.get("poll_interval", RobotCfg.poll_interval)),
        point_source=Path(d.get("point_source", RobotCfg.point_source)),
        point_meta=Path(d.get("point_meta", RobotCfg.point_meta)),
        flow_source=Path(d.get("flow_source", RobotCfg.flow_source)),
        host_action_source=Path(
            d.get("host_action_source", RobotCfg.host_action_source)
        ),
        point_source_version=str(d.get("point_source_version", RobotCfg.point_source_version)),
        home_point=str(d.get("home_point", RobotCfg.home_point)),
        allow_enable_command=_parse_bool(d.get("allow_enable_command"), False),
        allow_clear_error_command=_parse_bool(d.get("allow_clear_error_command"), False),
        tool_di_feedback_enabled=_parse_bool(d.get("tool_di_feedback_enabled"), False),
    )
    if min(cfg.connect_timeout, cfg.command_timeout, cfg.action_timeout, cfg.poll_interval) <= 0:
        raise ValueError("robot 超时和轮询间隔必须为正数")
    return cfg


def _parse_gcode(d: dict) -> GCodeCfg:
    origin_corner = str(d.get("origin_corner", GCodeCfg.origin_corner)).strip()
    if origin_corner not in _ALLOWED_ORIGIN_CORNERS:
        raise ValueError(
            f"gcode.origin_corner 必须是 {_ALLOWED_ORIGIN_CORNERS} 之一，得到: {origin_corner!r}"
        )
    path_strategy = str(d.get("path_strategy", GCodeCfg.path_strategy)).strip().lower()
    if path_strategy not in _ALLOWED_PATH_STRATEGIES:
        raise ValueError(
            f"gcode.path_strategy 必须是 {_ALLOWED_PATH_STRATEGIES} 之一，得到: {path_strategy!r}"
        )
    boustrophedon_columns = int(d.get("boustrophedon_columns", GCodeCfg.boustrophedon_columns))
    if boustrophedon_columns < 1 or _PLC_CNC_ARRAY_LEN % boustrophedon_columns != 0:
        raise ValueError(
            f"gcode.boustrophedon_columns 必须能整除 {_PLC_CNC_ARRAY_LEN}，得到: {boustrophedon_columns}"
        )
    scrape_keep_ratio = float(d.get("scrape_keep_ratio", GCodeCfg.scrape_keep_ratio))
    if not (0.0 < scrape_keep_ratio <= 1.0):
        raise ValueError(
            f"gcode.scrape_keep_ratio 必须在 (0, 1] 区间内，得到: {scrape_keep_ratio}"
        )
    collect_expand_ratio = float(d.get("collect_expand_ratio", GCodeCfg.collect_expand_ratio))
    if not (1.0 <= collect_expand_ratio <= 2.0):
        raise ValueError(
            f"gcode.collect_expand_ratio 必须在 [1.0, 2.0] 区间内，得到: {collect_expand_ratio}"
        )
    tool_raw = d.get("tool") or {}
    tool = ToolCfg(
        cutter_diameter_mm=float(tool_raw.get("cutter_diameter_mm", ToolCfg.cutter_diameter_mm)),
        bottle_diameter_mm=float(tool_raw.get("bottle_diameter_mm", ToolCfg.bottle_diameter_mm)),
        bottle_x_offset_mm=float(tool_raw.get("bottle_x_offset_mm", ToolCfg.bottle_x_offset_mm)),
    )
    scrape_raw = d.get("scrape") or {}
    scrape = ScrapeCfg(
        total_depth_mm=float(scrape_raw.get("total_depth_mm", ScrapeCfg.total_depth_mm)),
        num_passes=int(scrape_raw.get("num_passes", ScrapeCfg.num_passes)),
        overlap_ratio=float(scrape_raw.get("overlap_ratio", ScrapeCfg.overlap_ratio)),
        feed_rate=int(scrape_raw.get("feed_rate", ScrapeCfg.feed_rate)),
        plunge_rate=int(scrape_raw.get("plunge_rate", ScrapeCfg.plunge_rate)),
    )
    collection_raw = d.get("collection") or {}
    collection = CollectionCfg(
        overlap_ratio=float(collection_raw.get("overlap_ratio", CollectionCfg.overlap_ratio)),
        feed_rate=int(collection_raw.get("feed_rate", CollectionCfg.feed_rate)),
        mode=str(collection_raw.get("mode", CollectionCfg.mode)).strip(),
    )
    return GCodeCfg(
        origin_corner=origin_corner,
        plate_origin_x=float(d.get("plate_origin_x", GCodeCfg.plate_origin_x)),
        plate_origin_y=float(d.get("plate_origin_y", GCodeCfg.plate_origin_y)),
        plate_surface_z_mm=float(d.get("plate_surface_z_mm", GCodeCfg.plate_surface_z_mm)),
        safe_z_mm=float(d.get("safe_z_mm", GCodeCfg.safe_z_mm)),
        approach_z_mm=float(d.get("approach_z_mm", GCodeCfg.approach_z_mm)),
        path_strategy=path_strategy,
        boustrophedon_columns=boustrophedon_columns,
        scrape_keep_ratio=scrape_keep_ratio,
        collect_expand_ratio=collect_expand_ratio,
        tool=tool,
        scrape=scrape,
        collection=collection,
    )
