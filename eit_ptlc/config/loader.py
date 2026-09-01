"""配置加载与校验
================
功能:
    加载 app.yaml / plc_nodes.yaml / robot_points(.json + meta), 解析为 dataclass,
    并做跨文件一致性校验. 提供 ``--check`` CLI 供 P0 验证.
    迁移自 UI-Upper/core/config.py 的解析逻辑, 适配新分层架构.

使用方式:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.config.loader --check
    cfg = load_config(Path("eit_ptlc/config/app.yaml"))

校验失败:
    --check 打印全部错误并以退出码 1 结束; 不自动回退或绕过.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import yaml

from eit_ptlc.config.models import (
    ALLOWED_CONTROL_MODES,
    ALLOWED_ORIGIN_CORNERS,
    ALLOWED_PATH_STRATEGIES,
    ALLOWED_PLATE_ORIENTATIONS,
    ALLOWED_ROBOT_TRANSPORTS,
    ALLOWED_TOOL_CONFIRM_MODES,
    DAHENG_DEFAULTS,
    MANUAL_STATIONS,
    PLC_CNC_ARRAY_LEN,
    VALID_NODE_TYPES,
    ApiCfg,
    AppConfig,
    CameraCfg,
    CodesysCfg,
    CollectionCfg,
    ExperimentCfg,
    GCodeCfg,
    ManualAxis,
    ManualCylinder,
    ManualPointMap,
    ManualRef,
    NodeSpec,
    PallasVisionCfg,
    PLCCfg,
    PlcNodeMap,
    RobotCfg,
    ScrapeCfg,
    ToolActionConfirmCfg,
    ToolCfg,
    ToolConfirmCfg,
    ThreeDCfg,
    VisionCfg,
    VisionDebugCfg,
    WaterLevelCfg,
)

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# 通用工具
# ----------------------------------------------------------------------

def _parse_bool(value: object, default: bool) -> bool:
    """将 YAML 来源的值安全解析为 bool.

    功能:
        只接受显式布尔表示, 避免 Python bool() 把 "false"/"0" 当 True.
    参数:
        value: YAML 原始值; default: value 为 None 时的回落值
    返回:
        bool
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    raise ValueError(f"期望布尔值 (true/false, 1/0, yes/no, on/off), 实际: {value!r}")


def _resolve(base: Path, value: object, default: Path) -> Path:
    """把配置中引用其它配置文件的相对路径解析到 config 目录下.

    功能:
        nodes_file / points_file / recipes_dir 等配置引用路径, 相对 app.yaml 所在目录解析,
        绝对路径原样返回.
    参数:
        base: app.yaml 所在目录; value: YAML 值 (可缺失); default: 缺失时的默认相对名
    返回:
        Path (已解析)
    """
    raw = Path(str(value)) if value is not None else default
    if raw.is_absolute():
        return raw
    return (base / raw).resolve()


# ----------------------------------------------------------------------
# app.yaml 解析
# ----------------------------------------------------------------------

def load_config(path: Path) -> AppConfig:
    """从 app.yaml 加载顶层配置; 字段缺失使用默认值.

    功能:
        解析 YAML 为 AppConfig; 引用其它配置文件的路径相对 app.yaml 目录解析.
    参数:
        path: app.yaml 路径
    返回:
        AppConfig
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    base = path.parent

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件根节点必须是 mapping, 得到 {type(raw).__name__}")

    control_mode = str(raw.get("control_mode", "DEBUG")).strip().upper()
    if control_mode not in ALLOWED_CONTROL_MODES:
        raise ValueError(f"control_mode 必须是 {ALLOWED_CONTROL_MODES} 之一, 得到: {control_mode}")

    default_recipe = raw.get("default_recipe")
    default_recipe = str(default_recipe).strip() if default_recipe else None

    return AppConfig(
        control_mode=control_mode,
        plc=_parse_plc(raw.get("plc") or {}, base),
        robot=_parse_robot(raw.get("robot") or {}, base),
        vision=_parse_vision(raw.get("vision") or {}),
        pallas_vision=_parse_pallas_vision(raw.get("pallas_vision") or {}),
        camera=_parse_camera(raw.get("camera") or {}),
        vision_debug=_parse_vision_debug(raw.get("vision_debug") or {}),
        gcode=_parse_gcode(raw.get("gcode") or {}),
        water_level=_parse_water_level(raw.get("water_level") or {}, base),
        codesys=_parse_codesys(raw.get("codesys") or {}, base),
        api=_parse_api(raw.get("api") or {}),
        experiment=_parse_experiment(raw.get("experiment") or {}, base),
        three_d=_parse_three_d(raw.get("three_d") or {}, base),
        default_recipe=default_recipe,
        recipes_dir=_resolve(base, raw.get("recipes_dir"), Path("recipes")),
    )


def _parse_three_d(d: dict, base: Path) -> ThreeDCfg:
    """
    功能:
        解析三维工程工作区配置.

    参数:
        d: three_d 配置段.
        base: app.yaml 所在目录.

    返回:
        ThreeDCfg 配置对象.
    """
    return ThreeDCfg(
        workspace_root=_resolve(
            base,
            d.get("workspace_root"),
            ThreeDCfg.workspace_root,
        ),
        hardware_root=_resolve(
            base,
            d.get("hardware_root"),
            ThreeDCfg.hardware_root,
        ),
    )


def _parse_experiment(d: dict, base: Path) -> ExperimentCfg:
    """解析 experiment 段 (并行实验系统: 调度默认值 + 实验数据库路径)."""
    pool_raw = d.get("tank_pool", list(ExperimentCfg.tank_pool))
    if not isinstance(pool_raw, list):
        raise ValueError("experiment.tank_pool 必须是缸号列表")
    tank_pool = tuple(sorted({int(t) for t in pool_raw}))
    for t in tank_pool:
        if not 1 <= t <= 8:
            raise ValueError(f"experiment.tank_pool 缸号越界 (1-8): {t}")
    db_path = _resolve(base, d["db_path"], Path("experiments.db")) if d.get("db_path") else None
    wip = int(d.get("wip_limit", ExperimentCfg.wip_limit))
    if wip < 1:
        raise ValueError(f"experiment.wip_limit 必须 >= 1: {wip}")
    return ExperimentCfg(
        db_path=db_path,
        wip_limit=wip,
        tank_pool=tank_pool,
        recipe=str(d.get("recipe", ExperimentCfg.recipe)),
    )


def _parse_plc(d: dict, base: Path) -> PLCCfg:
    return PLCCfg(
        url=str(d.get("url", PLCCfg.url)),
        action_timeout=float(d.get("action_timeout", PLCCfg.action_timeout)),
        action_stall_timeout=float(d.get("action_stall_timeout", PLCCfg.action_stall_timeout)),
        action_soft_recheck=float(d.get("action_soft_recheck", PLCCfg.action_soft_recheck)),
        subscription_queue_size=int(d.get("subscription_queue_size", PLCCfg.subscription_queue_size)),
        subscription_sampling_ms=float(d.get("subscription_sampling_ms", PLCCfg.subscription_sampling_ms)),
        reconnect_wait_timeout=float(d.get("reconnect_wait_timeout", PLCCfg.reconnect_wait_timeout)),
        request_timeout=float(d.get("request_timeout", PLCCfg.request_timeout)),
        watchdog_interval=float(d.get("watchdog_interval", PLCCfg.watchdog_interval)),
        max_inflight_requests=int(d.get("max_inflight_requests", PLCCfg.max_inflight_requests)),
        nodes_file=_resolve(base, d.get("nodes_file"), Path("plc_nodes.yaml")),
        auto_rail=bool(d.get("auto_rail", PLCCfg.auto_rail)),
    )


def _parse_robot(d: dict, base: Path) -> RobotCfg:
    transport = str(d.get("transport", RobotCfg.transport)).strip().lower()
    if transport not in ALLOWED_ROBOT_TRANSPORTS:
        raise ValueError(f"robot.transport 必须是 {ALLOWED_ROBOT_TRANSPORTS} 之一, 得到: {transport}")
    cfg = RobotCfg(
        transport=transport,
        host=str(d.get("host", RobotCfg.host)),
        command_port=int(d.get("command_port", RobotCfg.command_port)),
        feedback_port=int(d.get("feedback_port", RobotCfg.feedback_port)),
        move_port=int(d.get("move_port", RobotCfg.move_port)),
        error_http_port=int(d.get("error_http_port", RobotCfg.error_http_port)),
        connect_timeout=float(d.get("connect_timeout", RobotCfg.connect_timeout)),
        command_timeout=float(d.get("command_timeout", RobotCfg.command_timeout)),
        action_timeout=float(d.get("action_timeout", RobotCfg.action_timeout)),
        ack_timeout=float(d.get("ack_timeout", RobotCfg.ack_timeout)),
        poll_interval=float(d.get("poll_interval", RobotCfg.poll_interval)),
        points_file=_resolve(base, d.get("points_file"), Path("points/robot/robot_points.json")),
        points_meta_file=_resolve(base, d.get("points_meta_file"), Path("points/robot/robot_points_meta.json")),
        tool_state_file=_resolve(base, d.get("tool_state_file"), Path("robot_tool_state.json")),
        point_source_version=str(d.get("point_source_version", RobotCfg.point_source_version)),
        home_point=str(d.get("home_point", RobotCfg.home_point)),
        allow_enable_command=_parse_bool(d.get("allow_enable_command"), False),
        allow_clear_error_command=_parse_bool(d.get("allow_clear_error_command"), False),
        tool_di_feedback_enabled=_parse_bool(d.get("tool_di_feedback_enabled"), False),
        tool_di_timeout=float(d.get("tool_di_timeout", RobotCfg.tool_di_timeout)),
        tool_confirm=_parse_tool_confirm(d.get("tool_confirm")),
        jog_speed_percent=int(d.get("jog_speed_percent", RobotCfg.jog_speed_percent)),
        step_distance_mm=float(d.get("step_distance_mm", RobotCfg.step_distance_mm)),
        step_angle_deg=float(d.get("step_angle_deg", RobotCfg.step_angle_deg)),
    )
    if min(cfg.connect_timeout, cfg.command_timeout, cfg.action_timeout, cfg.poll_interval,
           cfg.tool_di_timeout) <= 0:
        raise ValueError("robot 超时和轮询间隔必须为正数")
    if not (1 <= cfg.jog_speed_percent <= 100):
        raise ValueError("robot.jog_speed_percent 必须在 1-100")
    return cfg




def _parse_tool_confirm(d: object) -> Optional[ToolConfirmCfg]:
    """解析 robot.tool_confirm 段 (四个双气工具动作的按动作到位确认).

    段缺失 (None) → 返回 None → 驱动回退全局 tool_di_feedback_enabled 旧行为 (向后兼容).
    段存在但缺某动作 → 该动作用 ToolConfirmCfg 默认 (open=di, close/rotary=dwell).
    """
    if d is None:
        return None
    if not isinstance(d, dict):
        raise ValueError("robot.tool_confirm 必须是映射")
    defaults = ToolConfirmCfg()
    return ToolConfirmCfg(
        gripper_open=_parse_tool_action_confirm(d.get("gripper_open"), defaults.gripper_open, "gripper_open"),
        gripper_close=_parse_tool_action_confirm(d.get("gripper_close"), defaults.gripper_close, "gripper_close"),
        rotary_up=_parse_tool_action_confirm(d.get("rotary_up"), defaults.rotary_up, "rotary_up"),
        rotary_down=_parse_tool_action_confirm(d.get("rotary_down"), defaults.rotary_down, "rotary_down"),
    )


def _parse_tool_action_confirm(d: object, default: ToolActionConfirmCfg, label: str) -> ToolActionConfirmCfg:
    """解析单个双气工具动作的到位确认 (mode + dwell_ms); 缺失回落到该动作默认."""
    if d is None:
        return default
    if not isinstance(d, dict):
        raise ValueError(f"robot.tool_confirm.{label} 必须是映射")
    mode = str(d.get("mode", default.mode)).strip().lower()
    if mode not in ALLOWED_TOOL_CONFIRM_MODES:
        raise ValueError(
            f"robot.tool_confirm.{label}.mode 必须是 {ALLOWED_TOOL_CONFIRM_MODES} 之一, 得到: {mode!r}"
        )
    dwell_ms = int(d.get("dwell_ms", default.dwell_ms))
    if dwell_ms < 0:
        raise ValueError(f"robot.tool_confirm.{label}.dwell_ms 必须 >= 0")
    return ToolActionConfirmCfg(mode=mode, dwell_ms=dwell_ms)


def _parse_vision(d: dict) -> VisionCfg:
    orientation = str(d.get("image_plate_orientation", VisionCfg.image_plate_orientation)).strip().lower()
    if orientation not in ALLOWED_PLATE_ORIENTATIONS:
        raise ValueError(
            f"vision.image_plate_orientation 必须是 {ALLOWED_PLATE_ORIENTATIONS} 之一, 得到: {orientation!r}"
        )
    cfg = VisionCfg(
        mock=_parse_bool(d.get("mock"), True),
        output_dir=Path(d.get("output_dir", "vision_output")),
        image_plate_orientation=orientation,
        auto_rectify_tilt=_parse_bool(d.get("auto_rectify_tilt"), VisionCfg.auto_rectify_tilt),
        rectify_min_angle_deg=float(d.get("rectify_min_angle_deg", VisionCfg.rectify_min_angle_deg)),
        min_row_score=float(d.get("min_row_score", VisionCfg.min_row_score)),
        image_plate_rotation_deg=(float(d["image_plate_rotation_deg"]) if d.get("image_plate_rotation_deg") is not None else None),
    )
    if cfg.rectify_min_angle_deg < 0:
        raise ValueError("vision.rectify_min_angle_deg 必须 >= 0")
    if cfg.min_row_score < 0:
        raise ValueError("vision.min_row_score 必须 >= 0")
    return cfg


# ----------------------------------------------------------------------
# 泵档持久默认 (config.pump): 工位 -> {参数名: int}
# ----------------------------------------------------------------------
# 不进 AppConfig (live-read 段, 见 spec 2026-07-14-pump-defaults-config-design §4.2):
# 本校验器服务 ConfigService 写前校验 + bootstrap provider 闭包读后清洗。
# 速度类 1..500 (PLC 守卫上限, 与 translator 一致); step_delay 0..60000 ms。
PUMP_SPEED_MAX = 500
PUMP_STEP_DELAY_MAX = 60000
# 点样活塞终点上限 (mL; 与 translator SPOT_END_POSITION_MAX_ML / 动作 YAML max 同值 5.0)
PUMP_SPOT_END_MAX_ML = 5.0
# float mL 语义的键 (其余键一律整数); 值域 [0, PUMP_SPOT_END_MAX_ML], 统一存 float
PUMP_FLOAT_ML_KEYS = ("spot_end_position_ml",)
PUMP_STATION_KEYS: dict[str, tuple[str, ...]] = {
    "sampling": ("asp_speed", "disp_speed", "spot_disp_speed", "step_delay",
                 "flush_disp_speed", "spot_head_disp_speed", "spot_end_position_ml"),
    "collect": ("asp_speed", "disp_speed", "step_delay"),
    "develop": ("asp_speed", "disp_speed", "step_delay"),
}


def _parse_pump(d) -> dict:
    """校验并规范化 pump 段 -> {工位: {参数名: int|float}}.

    功能:
        缺键/缺工位/空段/null 值合法 (调用方回退 translator 常量); 未知工位/未知参数键
        一律拒绝 —— 缺键语义是"静默回退常量", 拼写错误若不拒绝会伪装成缺键。
        PUMP_FLOAT_ML_KEYS 内的键按 float mL 校验 (0..PUMP_SPOT_END_MAX_ML), 其余整数。
    参数:
        d: app.yaml pump 段原始值 (dict / None)
    返回:
        {station: {key: int|float}} 仅含显式给值的键
    """
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError("pump 必须是映射")
    unknown_stations = set(d) - set(PUMP_STATION_KEYS)
    if unknown_stations:
        raise ValueError(
            f"pump 未知工位: {sorted(unknown_stations)} (合法 {tuple(PUMP_STATION_KEYS)})")
    out: dict = {}
    for station, keys in PUMP_STATION_KEYS.items():
        sub = d.get(station)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise ValueError(f"pump.{station} 必须是映射")
        unknown = set(sub) - set(keys)
        if unknown:
            raise ValueError(f"pump.{station} 未知键: {sorted(unknown)} (合法 {keys})")
        cleaned: dict = {}
        for key, raw in sub.items():
            if raw is None:
                continue
            if key in PUMP_FLOAT_ML_KEYS:
                if isinstance(raw, bool):
                    raise ValueError(f"pump.{station}.{key} 必须是数值 (mL), 得到: {raw!r}")
                try:
                    fvalue = float(raw)
                except (TypeError, ValueError):
                    raise ValueError(f"pump.{station}.{key} 必须是数值 (mL), 得到: {raw!r}")
                if not 0.0 <= fvalue <= PUMP_SPOT_END_MAX_ML:
                    raise ValueError(
                        f"pump.{station}.{key} 须在 0..{PUMP_SPOT_END_MAX_ML} mL, 得到: {fvalue}")
                cleaned[key] = fvalue
                continue
            if isinstance(raw, bool):
                raise ValueError(f"pump.{station}.{key} 必须是整数, 得到: {raw!r}")
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError(f"pump.{station}.{key} 必须是整数, 得到: {raw!r}")
            try:
                value = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"pump.{station}.{key} 必须是整数, 得到: {raw!r}")
            if key == "step_delay":
                if not 0 <= value <= PUMP_STEP_DELAY_MAX:
                    raise ValueError(
                        f"pump.{station}.step_delay 须在 0..{PUMP_STEP_DELAY_MAX}, 得到: {value}")
            elif not 1 <= value <= PUMP_SPEED_MAX:
                raise ValueError(
                    f"pump.{station}.{key} 须在 1..{PUMP_SPEED_MAX}, 得到: {value}")
            cleaned[key] = value
        if cleaned:
            out[station] = cleaned
    return out


def _parse_pallas_vision(d: dict) -> PallasVisionCfg:
    if not isinstance(d, dict):
        raise ValueError("pallas_vision 必须是映射")
    cfg = PallasVisionCfg(
        enabled=_parse_bool(d.get("enabled"), PallasVisionCfg.enabled),
        mock=_parse_bool(d.get("mock"), PallasVisionCfg.mock),
        bridge_enabled=_parse_bool(d.get("bridge_enabled"), PallasVisionCfg.bridge_enabled),
        bridge_host=str(d.get("bridge_host", PallasVisionCfg.bridge_host)),
        bridge_port=int(d.get("bridge_port", PallasVisionCfg.bridge_port)),
        bridge_timeout=float(d.get("bridge_timeout", PallasVisionCfg.bridge_timeout)),
        host=str(d.get("host", PallasVisionCfg.host)),
        port=int(d.get("port", PallasVisionCfg.port)),
        trigger=str(d.get("trigger", PallasVisionCfg.trigger)),
        encoding=str(d.get("encoding", PallasVisionCfg.encoding)),
        terminator=str(d.get("terminator", PallasVisionCfg.terminator)).strip().lower(),
        result_mode=str(d.get("result_mode", PallasVisionCfg.result_mode)).strip().lower(),
        listen_host=str(d.get("listen_host", PallasVisionCfg.listen_host)),
        listen_port=int(d.get("listen_port", PallasVisionCfg.listen_port)),
        connect_timeout=float(d.get("connect_timeout", PallasVisionCfg.connect_timeout)),
        result_timeout=float(d.get("result_timeout", PallasVisionCfg.result_timeout)),
        read_bytes=int(d.get("read_bytes", PallasVisionCfg.read_bytes)),
        err_fail_code=int(d.get("err_fail_code", PallasVisionCfg.err_fail_code)),
        max_abs_xy_mm=float(d.get("max_abs_xy_mm", PallasVisionCfg.max_abs_xy_mm)),
        max_abs_rz_deg=float(d.get("max_abs_rz_deg", PallasVisionCfg.max_abs_rz_deg)),
        light_control_enabled=_parse_bool(
            d.get("light_control_enabled"), PallasVisionCfg.light_control_enabled
        ),
        light_do_channel=int(d.get("light_do_channel", PallasVisionCfg.light_do_channel)),
        light_settle_ms=int(d.get("light_settle_ms", PallasVisionCfg.light_settle_ms)),
        local_vision_enabled=_parse_bool(
            d.get("local_vision_enabled"), PallasVisionCfg.local_vision_enabled
        ),
    )
    if cfg.terminator not in {"none", "cr", "lf", "crlf", "nul"}:
        raise ValueError("pallas_vision.terminator 必须是 none/cr/lf/crlf/nul")
    if cfg.result_mode not in {"callback", "reply"}:
        raise ValueError("pallas_vision.result_mode 必须是 callback 或 reply")
    if min(cfg.port, cfg.listen_port, cfg.bridge_port, cfg.read_bytes) <= 0:
        raise ValueError("pallas_vision 端口和 read_bytes 必须为正数")
    if min(cfg.connect_timeout, cfg.result_timeout, cfg.bridge_timeout) <= 0:
        raise ValueError("pallas_vision 超时必须为正数")
    if min(cfg.max_abs_xy_mm, cfg.max_abs_rz_deg) <= 0:
        raise ValueError("pallas_vision 纠偏阈值必须为正数")
    if cfg.light_do_channel <= 0:
        raise ValueError("pallas_vision.light_do_channel 必须为正数")
    if cfg.light_settle_ms < 0:
        raise ValueError("pallas_vision.light_settle_ms 必须 >= 0")
    if cfg.light_do_channel in {1, 2, 3, 6}:
        raise ValueError(
            f"pallas_vision.light_do_channel={cfg.light_do_channel} 与工具 DO 白名单 {{1,2,3,6}} 冲突"
        )
    return cfg

def _parse_camera(d: dict) -> CameraCfg:
    before_img = d.get("test_before_image")
    daheng_raw = d.get("daheng") or {}
    daheng = {
        **DAHENG_DEFAULTS,
        **({k: v for k, v in daheng_raw.items() if k in DAHENG_DEFAULTS}
           if isinstance(daheng_raw, dict) else {}),
    }
    # profiles: {名称: {部分 daheng 参数}}; 仅保留合法 DAHENG 键, 丢弃未知键
    profiles_raw = d.get("profiles") or {}
    profiles: dict = {}
    if isinstance(profiles_raw, dict):
        for pname, pvals in profiles_raw.items():
            if isinstance(pvals, dict):
                profiles[str(pname)] = {k: v for k, v in pvals.items() if k in DAHENG_DEFAULTS}
    return CameraCfg(
        mock=_parse_bool(d.get("mock"), True),
        test_image=Path(d.get("test_image", str(CameraCfg.test_image))),
        test_before_image=Path(before_img) if before_img else None,
        daheng=daheng,
        profiles=profiles,
    )


def _parse_vision_debug(d: dict) -> VisionDebugCfg:
    if not isinstance(d, dict):
        raise ValueError("vision_debug 必须是映射")
    # 识别参数已并入 vision 段单一真源; 此处只解析采集/工作区项 (残留的识别键会被忽略)。
    cfg = VisionDebugCfg(
        workspace_dir=Path(d.get("workspace_dir", VisionDebugCfg.workspace_dir)),
        default_exposure_time_us=int(
            d.get("default_exposure_time_us", VisionDebugCfg.default_exposure_time_us)
        ),
        default_gain=float(d.get("default_gain", VisionDebugCfg.default_gain)),
        default_uv_on_time_ms=int(
            d.get("default_uv_on_time_ms", VisionDebugCfg.default_uv_on_time_ms)
        ),
    )
    if cfg.default_exposure_time_us <= 0:
        raise ValueError("vision_debug.default_exposure_time_us 必须 > 0")
    if cfg.default_uv_on_time_ms <= 0:
        raise ValueError("vision_debug.default_uv_on_time_ms 必须 > 0")
    if cfg.default_exposure_time_us / 1000 > cfg.default_uv_on_time_ms:
        raise ValueError("vision_debug 默认曝光时间不能大于 UV 总点亮时间")
    if cfg.default_uv_on_time_ms > 1800:
        raise ValueError("vision_debug.default_uv_on_time_ms 不能超过 1800 ms")
    if cfg.default_gain < 0:
        raise ValueError("vision_debug.default_gain 必须 >= 0")
    return cfg


def _parse_gcode(d: dict) -> GCodeCfg:
    origin_corner = str(d.get("origin_corner", GCodeCfg.origin_corner)).strip()
    if origin_corner not in ALLOWED_ORIGIN_CORNERS:
        raise ValueError(f"gcode.origin_corner 必须是 {ALLOWED_ORIGIN_CORNERS} 之一, 得到: {origin_corner!r}")
    path_strategy = str(d.get("path_strategy", GCodeCfg.path_strategy)).strip().lower()
    if path_strategy not in ALLOWED_PATH_STRATEGIES:
        raise ValueError(f"gcode.path_strategy 必须是 {ALLOWED_PATH_STRATEGIES} 之一, 得到: {path_strategy!r}")
    boustrophedon_columns = int(d.get("boustrophedon_columns", GCodeCfg.boustrophedon_columns))
    if boustrophedon_columns < 1 or PLC_CNC_ARRAY_LEN % boustrophedon_columns != 0:
        raise ValueError(f"gcode.boustrophedon_columns 必须能整除 {PLC_CNC_ARRAY_LEN}, 得到: {boustrophedon_columns}")
    scrape_keep_ratio = float(d.get("scrape_keep_ratio", GCodeCfg.scrape_keep_ratio))
    if not (0.0 < scrape_keep_ratio <= 1.0):
        raise ValueError(f"gcode.scrape_keep_ratio 必须在 (0, 1], 得到: {scrape_keep_ratio}")
    collect_margin_mm = float(d.get("collect_margin_mm", GCodeCfg.collect_margin_mm))
    if collect_margin_mm < 0.0:
        raise ValueError(f"gcode.collect_margin_mm 必须 ≥ 0, 得到: {collect_margin_mm}")
    collect_expand_ratio = float(d.get("collect_expand_ratio", GCodeCfg.collect_expand_ratio))
    if not (1.0 <= collect_expand_ratio <= 2.0):
        raise ValueError(f"gcode.collect_expand_ratio 必须在 [1.0, 2.0], 得到: {collect_expand_ratio}")
    _ymin_raw = d.get("machine_y_min_mm", None)
    machine_y_min_mm = None if _ymin_raw is None else float(_ymin_raw)
    collector_x_positive = bool(d.get("collector_x_positive", GCodeCfg.collector_x_positive))
    tool_raw = d.get("tool") or {}
    bottle_y_offset_mm = float(tool_raw.get("bottle_y_offset_mm", ToolCfg.bottle_y_offset_mm))
    if abs(bottle_y_offset_mm) > 20.0:
        raise ValueError(f"gcode.tool.bottle_y_offset_mm 必须在 [-20, 20]mm, 得到: {bottle_y_offset_mm}")
    compensation_margin_mm = float(tool_raw.get("compensation_margin_mm", ToolCfg.compensation_margin_mm))
    if not (0.0 <= compensation_margin_mm <= 10.0):
        raise ValueError(
            f"gcode.tool.compensation_margin_mm 必须在 [0, 10]mm, 得到: {compensation_margin_mm}"
        )
    tool = ToolCfg(
        cutter_diameter_mm=float(tool_raw.get("cutter_diameter_mm", ToolCfg.cutter_diameter_mm)),
        cutter_compensation=bool(tool_raw.get("cutter_compensation", ToolCfg.cutter_compensation)),
        compensation_margin_mm=compensation_margin_mm,
        bottle_diameter_mm=float(tool_raw.get("bottle_diameter_mm", ToolCfg.bottle_diameter_mm)),
        bottle_x_offset_mm=float(tool_raw.get("bottle_x_offset_mm", ToolCfg.bottle_x_offset_mm)),
        bottle_y_offset_mm=bottle_y_offset_mm,
    )
    scrape_raw = d.get("scrape") or {}
    bulk_factor = float(scrape_raw.get("bulk_factor", ScrapeCfg.bulk_factor))
    if not (0.5 <= bulk_factor <= 5.0):
        raise ValueError(f"gcode.scrape.bulk_factor 必须在 [0.5, 5.0], 得到: {bulk_factor}")
    scrape = ScrapeCfg(
        total_depth_mm=float(scrape_raw.get("total_depth_mm", ScrapeCfg.total_depth_mm)),
        num_passes=int(scrape_raw.get("num_passes", ScrapeCfg.num_passes)),
        overlap_ratio=float(scrape_raw.get("overlap_ratio", ScrapeCfg.overlap_ratio)),
        feed_rate=int(scrape_raw.get("feed_rate", ScrapeCfg.feed_rate)),
        bulk_factor=bulk_factor,
    )
    collection_raw = d.get("collection") or {}
    collection = CollectionCfg(
        return_sweep=bool(collection_raw.get("return_sweep", CollectionCfg.return_sweep)),
    )
    return GCodeCfg(
        origin_corner=origin_corner,
        plate_origin_x=float(d.get("plate_origin_x", GCodeCfg.plate_origin_x)),
        plate_origin_y=float(d.get("plate_origin_y", GCodeCfg.plate_origin_y)),
        plate_surface_z_mm=float(d.get("plate_surface_z_mm", GCodeCfg.plate_surface_z_mm)),
        align_clearance_mm=float(d.get("align_clearance_mm", GCodeCfg.align_clearance_mm)),
        path_strategy=path_strategy,
        boustrophedon_columns=boustrophedon_columns,
        scrape_keep_ratio=scrape_keep_ratio,
        collect_margin_mm=collect_margin_mm,
        collect_expand_ratio=collect_expand_ratio,
        machine_y_min_mm=machine_y_min_mm,
        collector_x_positive=collector_x_positive,
        tool=tool,
        scrape=scrape,
        collection=collection,
    )


def _parse_water_level(d: dict, base: Path) -> WaterLevelCfg:
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
        payload_dir=_resolve(base, d.get("payload_dir"), WaterLevelCfg().payload_dir),
        auto_start=_parse_bool(d.get("auto_start"), False),
        start_timeout=float(d.get("start_timeout", WaterLevelCfg.start_timeout)),
        cameras=str(d.get("cameras", WaterLevelCfg.cameras)),
        tl_bl_cm=float(d.get("tl_bl_cm", WaterLevelCfg.tl_bl_cm)),
        cap_width=int(d.get("cap_width", WaterLevelCfg.cap_width)),
        cap_height=int(d.get("cap_height", WaterLevelCfg.cap_height)),
        cap_fps=int(d.get("cap_fps", WaterLevelCfg.cap_fps)),
        exposure_time=int(d.get("exposure_time", WaterLevelCfg.exposure_time)),
        awb_temp=int(d.get("awb_temp", WaterLevelCfg.awb_temp)),
        no_detect=_parse_bool(d.get("no_detect"), WaterLevelCfg.no_detect),
        # 录制根目录: 给了就按 config 目录解析相对路径; 留空则 None → 录制器自派生 <repo_root>/data/...
        recordings_dir=(_resolve(base, d["recordings_dir"], Path(".")) if d.get("recordings_dir") else None),
    )


def _parse_codesys(d: dict, base: Path) -> CodesysCfg:
    return CodesysCfg(
        enabled=_parse_bool(d.get("enabled"), False),
        allow_deploy=_parse_bool(d.get("allow_deploy"), False),
        exe=str(d.get("exe", CodesysCfg.exe)),
        profile=str(d.get("profile", CodesysCfg.profile)),
        project=_resolve(base, d.get("project"), Path("../plc/20260702.project")),
        ipc_dir=_resolve(base, d.get("ipc_dir"), Path("../var/codesys-ipc")),
        compile_category=str(d.get("compile_category", CodesysCfg.compile_category)),
        idle_timeout=float(d.get("idle_timeout", CodesysCfg.idle_timeout)),
        session_idle_release=float(d.get("session_idle_release", CodesysCfg.session_idle_release)),
        session_wait_timeout=float(d.get("session_wait_timeout", CodesysCfg.session_wait_timeout)),
        session_max_hold=float(d.get("session_max_hold", CodesysCfg.session_max_hold)),
    )


def _parse_api(d: dict) -> ApiCfg:
    origins = d.get("cors_origins")
    if origins is None:
        origins = list(ApiCfg().cors_origins)
    elif not isinstance(origins, list):
        raise ValueError("api.cors_origins 必须是列表")
    return ApiCfg(
        enabled=_parse_bool(d.get("enabled"), True),
        host=str(d.get("host", ApiCfg.host)),
        port=int(d.get("port", ApiCfg.port)),
        cors_origins=[str(o) for o in origins],
    )


# ----------------------------------------------------------------------
# plc_nodes.yaml 解析
# ----------------------------------------------------------------------

def load_plc_nodes(path: Path) -> PlcNodeMap:
    """加载并校验 PLC 节点表.

    功能:
        解析 plc_nodes.yaml 为 PlcNodeMap; 校验类型名合法, 心跳/急停节点存在.
    参数:
        path: plc_nodes.yaml 路径
    返回:
        PlcNodeMap
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PLC 节点表不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    gvl_path = raw.get("gvl_path")
    if not isinstance(gvl_path, list) or not gvl_path:
        raise ValueError("plc_nodes.gvl_path 必须是非空列表")
    heartbeat_node = str(raw.get("heartbeat_node") or "")
    estop_node = str(raw.get("estop_node") or "")
    nodes_raw = raw.get("nodes") or {}
    if not isinstance(nodes_raw, dict) or not nodes_raw:
        raise ValueError("plc_nodes.nodes 必须是非空 mapping")

    nodes: dict[str, NodeSpec] = {}
    for name, spec in nodes_raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"plc_nodes.nodes.{name} 必须是 mapping")
        var_type = str(spec.get("type") or "")
        if var_type not in VALID_NODE_TYPES:
            raise ValueError(f"plc_nodes.nodes.{name}.type 非法: {var_type!r} (合法: {sorted(VALID_NODE_TYPES)})")
        array_len = int(spec.get("array_len", 0))
        if array_len < 0:
            raise ValueError(f"plc_nodes.nodes.{name}.array_len 不能为负")
        nodes[str(name)] = NodeSpec(
            name=str(name), var_type=var_type, array_len=array_len, comment=str(spec.get("comment", "")),
            optional=bool(spec.get("optional", False)),
        )

    if heartbeat_node not in nodes:
        raise ValueError(f"plc_nodes.heartbeat_node {heartbeat_node!r} 不在 nodes 中")
    if estop_node not in nodes:
        raise ValueError(f"plc_nodes.estop_node {estop_node!r} 不在 nodes 中")

    return PlcNodeMap(
        gvl_path=tuple(str(p) for p in gvl_path),
        heartbeat_node=heartbeat_node,
        estop_node=estop_node,
        nodes=nodes,
    )


# ----------------------------------------------------------------------
# manual_points.yaml 解析 (单点控制点表)
# ----------------------------------------------------------------------

def _manual_ref(raw: object, where: str, containers: dict[str, str]) -> ManualRef:
    """把 {container, name, type?} 解析为 ManualRef 并校验容器/类型."""
    if not isinstance(raw, dict):
        raise ValueError(f"manual_points.{where} 必须是 mapping")
    container = str(raw.get("container") or "")
    if container not in containers:
        raise ValueError(
            f"manual_points.{where}.container {container!r} 未在 containers.names 中声明"
        )
    name = str(raw.get("name") or "")
    if not name:
        raise ValueError(f"manual_points.{where}.name 不能为空")
    var_type = str(raw.get("type") or "Boolean")
    if var_type not in VALID_NODE_TYPES:
        raise ValueError(
            f"manual_points.{where}.type 非法: {var_type!r} (合法: {sorted(VALID_NODE_TYPES)})"
        )
    return ManualRef(container=container, name=name, var_type=var_type)


def load_manual_points(path: Path) -> ManualPointMap:
    """加载并校验单点控制点表.

    功能:
        解析 manual_points.yaml 为 ManualPointMap; 校验容器引用、类型名、
        工位名合法, id 全局唯一 (气缸与轴共用一个 id 命名空间, 面板按 id 派发)。
    参数:
        path: manual_points.yaml 路径
    返回:
        ManualPointMap
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"单点控制点表不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cont_raw = raw.get("containers")
    if not isinstance(cont_raw, dict):
        raise ValueError("manual_points.containers 必须是 mapping")
    root = cont_raw.get("root")
    if not isinstance(root, list) or not root:
        raise ValueError("manual_points.containers.root 必须是非空列表")
    search_raw = cont_raw.get("search") or [[]]
    if not isinstance(search_raw, list) or not search_raw:
        raise ValueError("manual_points.containers.search 必须是非空列表")
    search: list[tuple[str, ...]] = []
    for item in search_raw:
        if not isinstance(item, list):
            raise ValueError("manual_points.containers.search 的每项必须是列表 (可为空列表)")
        search.append(tuple(str(p) for p in item))
    names_raw = cont_raw.get("names")
    if not isinstance(names_raw, dict) or not names_raw:
        raise ValueError("manual_points.containers.names 必须是非空 mapping")
    containers = {str(k): str(v) for k, v in names_raw.items()}

    host_raw = raw.get("host")
    if not isinstance(host_raw, dict):
        raise ValueError("manual_points.host 必须是 mapping")
    host = {str(k): str(v) for k, v in host_raw.items()}
    if host.get("container") not in containers:
        raise ValueError(
            f"manual_points.host.container {host.get('container')!r} 未在 containers.names 中声明"
        )
    for key in ("enable", "keepalive", "active"):
        if not host.get(key):
            raise ValueError(f"manual_points.host.{key} 不能为空")

    globals_raw = raw.get("globals") or {}
    if not isinstance(globals_raw, dict):
        raise ValueError("manual_points.globals 必须是 mapping")
    globals_ = {
        str(k): _manual_ref(v, f"globals.{k}", containers)
        for k, v in globals_raw.items()
    }

    stations_raw = raw.get("stations") or {}
    if not isinstance(stations_raw, dict) or not stations_raw:
        raise ValueError("manual_points.stations 必须是非空 mapping")

    cylinders: dict[str, ManualCylinder] = {}
    axes: dict[str, ManualAxis] = {}
    stations: list[str] = []
    for station, body in stations_raw.items():
        station = str(station)
        if station not in MANUAL_STATIONS:
            raise ValueError(
                f"manual_points.stations.{station} 非法工位 (合法: {sorted(MANUAL_STATIONS)})"
            )
        if not isinstance(body, dict):
            raise ValueError(f"manual_points.stations.{station} 必须是 mapping")
        stations.append(station)

        for item in body.get("cylinders") or []:
            if not isinstance(item, dict):
                raise ValueError(f"manual_points.stations.{station}.cylinders 每项必须是 mapping")
            cid = str(item.get("id") or "")
            if not cid:
                raise ValueError(f"manual_points.stations.{station}.cylinders 存在缺 id 的条目")
            if cid in cylinders or cid in axes:
                raise ValueError(f"manual_points id 重复: {cid!r}")
            where = f"stations.{station}.cylinders.{cid}"
            if "manual" not in item:
                raise ValueError(f"manual_points.{where}.manual 缺失 (手动位是必需的写入口)")
            alarm_bit = int(item.get("alarm_bit", -1))
            if alarm_bit < -1 or alarm_bit > 15:
                raise ValueError(f"manual_points.{where}.alarm_bit 越界: {alarm_bit} (cyinderAlarm 是 INT)")
            cylinders[cid] = ManualCylinder(
                id=cid,
                label=str(item.get("label") or cid),
                station=station,
                manual=_manual_ref(item["manual"], f"{where}.manual", containers),
                auto_ro=_manual_ref(item["auto_ro"], f"{where}.auto_ro", containers)
                if "auto_ro" in item else None,
                fb_on=_manual_ref(item["fb_on"], f"{where}.fb_on", containers)
                if "fb_on" in item else None,
                fb_off=_manual_ref(item["fb_off"], f"{where}.fb_off", containers)
                if "fb_off" in item else None,
                alarm_bit=alarm_bit,
                note=str(item.get("note", "")),
            )

        for item in body.get("axes") or []:
            if not isinstance(item, dict):
                raise ValueError(f"manual_points.stations.{station}.axes 每项必须是 mapping")
            aid = str(item.get("id") or "")
            if not aid:
                raise ValueError(f"manual_points.stations.{station}.axes 存在缺 id 的条目")
            if aid in cylinders or aid in axes:
                raise ValueError(f"manual_points id 重复: {aid!r}")
            where = f"stations.{station}.axes.{aid}"
            struct = str(item.get("struct") or "")
            if not struct:
                raise ValueError(f"manual_points.{where}.struct 不能为空")
            vel_max = float(item.get("vel_max", 0.0))
            if vel_max <= 0:
                raise ValueError(f"manual_points.{where}.vel_max 必须为正 (定位速度限幅)")
            axes[aid] = ManualAxis(
                id=aid,
                label=str(item.get("label") or aid),
                station=station,
                struct=struct,
                jog_vel_fixed=float(item.get("jog_vel_fixed", 0.0)),
                vel_max=vel_max,
                note=str(item.get("note", "")),
            )

    if not cylinders and not axes:
        raise ValueError("manual_points 未声明任何气缸或轴")

    return ManualPointMap(
        root=tuple(str(p) for p in root),
        search=tuple(search),
        containers=containers,
        host=host,
        globals_=globals_,
        cylinders=cylinders,
        axes=axes,
        stations=tuple(stations),
    )


# ----------------------------------------------------------------------
# robot_points 解析 (P0 轻校验; 完整 PointRegistry 在 P2)
# ----------------------------------------------------------------------

def load_robot_points(points_file: Path, meta_file: Optional[Path] = None) -> tuple[list, dict]:
    """加载机器人点表与 meta 覆盖层 (P0 仅做结构校验).

    功能:
        读取 point.json 数组与 meta 覆盖文件; 校验每点含 id/alias/name/pose,
        校验 meta overrides 引用的机器人名存在.
    参数:
        points_file: 点表 JSON; meta_file: meta 覆盖 JSON (可选)
    返回:
        (points: list[dict], meta: dict)
    """
    points_file = Path(points_file)
    if not points_file.exists():
        raise FileNotFoundError(f"机器人点表不存在: {points_file}")
    with points_file.open("r", encoding="utf-8") as f:
        points = json.load(f)
    if not isinstance(points, list) or not points:
        raise ValueError("robot_points 必须是非空 JSON 数组")

    names = set()
    for i, p in enumerate(points):
        for key in ("id", "alias", "name", "pose"):
            if key not in p:
                raise ValueError(f"robot_points[{i}] 缺少字段 {key!r}")
        if not isinstance(p["pose"], list) or len(p["pose"]) != 6:
            raise ValueError(f"robot_points[{i}].pose 必须是 6 元数组")
        names.add(str(p["name"]))

    meta: dict = {}
    if meta_file is not None:
        meta_file = Path(meta_file)
        if meta_file.exists():
            with meta_file.open("r", encoding="utf-8") as f:
                meta = json.load(f) or {}
            overrides = meta.get("overrides") or {}
            for robot_name in overrides:
                if robot_name not in names:
                    raise ValueError(f"robot_points_meta.overrides 引用不存在的机器人名: {robot_name!r}")

    return points, meta


# ----------------------------------------------------------------------
# 跨文件一致性校验 (--check)
# ----------------------------------------------------------------------

def check_config(app_yaml: Path) -> list[str]:
    """加载并跨文件校验全部配置, 返回错误列表 (空=通过).

    功能:
        统一加载 app.yaml / plc_nodes.yaml / robot_points, 逐项捕获错误并汇总,
        不在首个错误处中断, 便于一次暴露全部问题.
    参数:
        app_yaml: app.yaml 路径
    返回:
        list[str], 错误消息; 空列表表示校验通过
    """
    errors: list[str] = []

    cfg: Optional[AppConfig] = None
    try:
        cfg = load_config(app_yaml)
        log.info("[check] app.yaml 加载成功: control_mode=%s plc.url=%s robot.transport=%s",
                 cfg.control_mode, cfg.plc.url, cfg.robot.transport)
    except Exception as exc:
        errors.append(f"app.yaml 加载失败: {exc}")
        return errors  # 顶层配置都加载不了, 后续无意义

    try:
        node_map = load_plc_nodes(cfg.plc.nodes_file)
        log.info("[check] plc_nodes.yaml 加载成功: %d 个节点, 心跳=%s 急停=%s",
                 len(node_map.nodes), node_map.heartbeat_node, node_map.estop_node)
    except Exception as exc:
        errors.append(f"plc_nodes.yaml 校验失败: {exc}")

    try:
        points, meta = load_robot_points(cfg.robot.points_file, cfg.robot.points_meta_file)
        override_count = len((meta.get("overrides") or {}))
        log.info("[check] robot_points 加载成功: %d 点, meta overrides=%d", len(points), override_count)
    except Exception as exc:
        errors.append(f"robot_points 校验失败: {exc}")

    return errors


def main(argv: Optional[list[str]] = None) -> int:
    """配置校验 CLI 入口."""
    # Windows 控制台默认 GBK, 重配为 UTF-8 保证中文日志可读
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="eit_ptlc 配置加载与校验")
    parser.add_argument("--check", action="store_true", help="加载并跨文件校验全部配置")
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "app.yaml",
                        help="app.yaml 路径 (默认 eit_ptlc/config/app.yaml)")
    args = parser.parse_args(argv)

    if not args.check:
        parser.print_help()
        return 0

    errors = check_config(args.config)
    if errors:
        log.error("配置校验未通过, 共 %d 个错误:", len(errors))
        for e in errors:
            log.error("  - %s", e)
        return 1
    log.info("配置校验通过 (0 错误)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
