"""运行时装配
============
功能:
    把 config -> drivers -> controllers -> action executor -> FastAPI 串起来.
    提供 sim 装配 (内存机器人仿真 + Mock PLC), 供离线开发 / 演示 / 端到端测试;
    real 装配 (Dobot 直连 + 真机 PLC) 供现场使用.

运行 (sim):
    & "C:/ProgramData/miniforge3/python.exe" -m uvicorn eit_ptlc.runtime.bootstrap:app --host 0.0.0.0 --port 18080

运行 (real):
    $env:EIT_MODE="real"
    & "C:/ProgramData/miniforge3/python.exe" -m uvicorn eit_ptlc.runtime.bootstrap:app --host 0.0.0.0 --port 18080

监听地址真源在 config/app.yaml api.host (main.py launcher 会读取自动传 --host);
裸跑 uvicorn 需自带 --host, 缺省 127.0.0.1 仅本机可访问.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.config.loader import load_config, load_manual_points, load_plc_nodes
from eit_ptlc.config.models import AppConfig
from eit_ptlc.controller.plc_controller import PlcController
from eit_ptlc.config.loader import _parse_gcode, _parse_pump, _parse_vision
from eit_ptlc.controller.camera_controller import CameraController
from eit_ptlc.controller.cnc_path import CncPathController
from eit_ptlc.controller.scrape_reconcile import ScrapeReconcileController
from eit_ptlc.controller.config_service import ConfigService
from eit_ptlc.tools.pump.profiles import set_pump_defaults_provider
from eit_ptlc.controller.vision_controller import VisionService
from eit_ptlc.controller.pallas_vision_client import PallasVisionClient
from eit_ptlc.controller.plate_align_service import PlateAlignService
from eit_ptlc.controller.vision_debug_service import VisionDebugService
from eit_ptlc.controller.waterlevel_observation import WaterLevelObservationCollector
from eit_ptlc.controller.actions_service import ActionsService
from eit_ptlc.controller.manual_service import ManualService
from eit_ptlc.controller.plc_program_service import (
    PLCDeployPreconditionError,
    PlcProgramService,
)
from eit_ptlc.controller.plc_version_repo import PlcVersionRepo
from eit_ptlc.controller.calibration_service import CalibrationService
from eit_ptlc.controller.plate_catalog import PlateCatalog
from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.points_service import PointsService
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.codesys_ipc import CodesysIpcClient
from eit_ptlc.driver.opcua_driver import OpcUaDriver
from eit_ptlc.driver.robot_sim import SimRobotTransport
from eit_ptlc.mock.manual_plc import build_manual_mock_tree, run_manual_fsm
from eit_ptlc.mock.plc_server import (
    build_mock_server,
    mock_read,
    mock_write,
    run_deploy_fsm,
    run_l2_fsm,
)
from eit_ptlc.action.models import ActionStatus
from eit_ptlc.operation.resources import ResourceError, ResourceGate, ResourceSpec, load_resource_specs
from eit_ptlc.operation.scheduler import FlowScheduler
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.operation.vm.repo import ScriptRepo
from eit_ptlc.operation.vm.schema import validate_script
from eit_ptlc.runtime.events import EventBus, make_event_sink
from eit_ptlc.runtime.maintenance_gate import MaintenanceGate
from eit_ptlc.runtime.node_registry import build_node_registry, telemetry_loop
from eit_ptlc.runtime.realtime_feedback import realtime_feedback_loop
from eit_ptlc.runtime.material_feedback import material_feedback_loop
from eit_ptlc.runtime.three_d_authoring import ThreeDAuthoringService
from eit_ptlc.runtime.material_store import (
    AREAS, OP_BLOCKED, OP_EXHAUSTED, OP_PUT_NEW, MaterialBindings, MaterialStore, MaterialTopology,
    load_bindings, load_topology)
from eit_ptlc.runtime.experiment_store import ExperimentStore
from eit_ptlc.runtime.recording.activity import load_station_map
from eit_ptlc.runtime.recording.recorder import StateRecorder
from eit_ptlc.runtime.recording.store import RecordingStore, default_root
from eit_ptlc.runtime.run_store import RunStore

log = logging.getLogger(__name__)

# asyncua 在 INFO 下逐条打 open/close_secure_channel 等内部动作, 断线重连时会把驱动自己的
# 诊断行淹掉。压到 WARNING 只保留真正需要注意的库内告警。
# 注意必须在这里设 (uvicorn 加载的后端进程), launcher main.py 里设无效: 那是另一个进程。
logging.getLogger("asyncua").setLevel(logging.WARNING)
# 唯独放开 asyncua.client.client 到 INFO: asyncua 2.x 的连接监管在判定链路失效时打
# "Supervisor detected connection issue: <exc>" (client.py _handle_connection_loss), 这是
# 现场唯一能区分断连成因的一行 —— exc 为 asyncio.TimeoutError 即上位机自身把 PLC 压到
# server_state 探测超时(负载问题), 为 ConnectionResetError/OSError 即真断网(查链路)。
# 缺了它只看得见症状 (驱动的"调用侧先于心跳发现连接断开" + 库内 request id 报错) 看不见病因。
# 该 logger 的 INFO 只在连接异常时出声, 稳态不刷屏。
logging.getLogger("asyncua.client.client").setLevel(logging.INFO)

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "app.yaml"
_DATA_DIR = Path(__file__).resolve().parent.parent / "var"  # 运行记录等运行期数据
_SIM_URL = "opc.tcp://127.0.0.1:48490/eit_ptlc/sim/"
# robot_pose 发布节流。30004 反馈口原生约 125 Hz 且后台 reader 线程无条件常转
# (dobot_tcp_driver._start_feedback_pump 在 connect() 即启动, 每帧都回调观察者),
# 所以这个常量是唯一的限速点 —— 帧本来就在收在解, 放宽它不增加任何 I/O, 只增加
# 事件总线与 WebSocket 的负载 (约 317 B/帧)。0.018 → 约 50 Hz。
_ROBOT_POSE_MIN_INTERVAL = 0.018
# 全部 L2 工位通道前缀 (Sim: FSM 覆盖; Real: 遥测注册)
_ALL_L2_STATIONS = ("Sampling", "Collect", "Develop", "PhotoScrape", "FeedLift", "Pump", "Rail", "StagingA")
# 视觉纠偏补光(机器人 DO7)在三维孪生里的灯 id。必须与 three_d/pipeline/rig_map.yaml
# 的 lights[].id 逐字一致 —— 前端按 id 查 manifest.lights, 对不上就是一盏永远不亮的灯。
PALLAS_LIGHT_TWIN_ID = "vision_fill"


def make_pallas_light_setter(config: AppConfig, robot, app):
    """造视觉纠偏补光(机器人 DO7)的开关函数, 并在写成功后向事件总线公告灯态。

    功能:
        `PallasVisionClient._run_with_light` 经 `light_setter` 调进来开/关补光。这里
        就是**全仓唯一**写 DO7 的地方 —— 机器人 DO 没有便宜的回读通道, 所以三维孪生
        实时页要知道"补光此刻亮着没有", 唯一诚实的取数点就是这一次调用本身:
        与写 DO 同一拍公告, 无需新开轮询, 也不会与真机脱节。
        (2026-08-05 之前实时页根本没有这条链, 现象是"上样-上料时闪光灯不闪"。)

    两条不能动的次序:
        * 事件排在 `set_output` **之后**: 写失败会抛出去(关灯失败还会被上游升级成
          PallasVisionError), 那种情况下画面不该跟着变 —— 只报已经写成功的 DO 状态。
        * `bus` 走运行期 late lookup 而不是闭包捕获: `app.state.bus` 的赋值晚于本函数
          被调用的时刻, 但**真正开灯**(跑流程)时它早已就绪。

    参数:
        config: 应用配置 (取 pallas_vision.light_do_channel)
        robot: 机器人控制器 (经 transport.set_output 写 DO)
        app: FastAPI 应用 (运行期取 state.bus)
    返回值:
        async (enabled: bool) -> None
    """
    channel = config.pallas_vision.light_do_channel

    async def pallas_light_setter(enabled: bool) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: robot.transport.set_output(channel, enabled))
        bus = getattr(app.state, "bus", None)
        if bus is not None:
            bus.publish({
                "type": "process_light",
                "id": PALLAS_LIGHT_TWIN_ID,
                "on": bool(enabled),
                "channel": channel,
                "ts": time.time(),
            })

    return pallas_light_setter


def _actions_dir(config: AppConfig) -> Path:
    """动作目录 = plc_nodes.yaml 同级的 actions/ (即 config/actions)."""
    return config.plc.nodes_file.parent / "actions"


def _feedlift_calib_path(config: AppConfig) -> Path:
    """升降板仓行程标定 = plc_nodes.yaml 同级的 feedlift_calib.json (即 config/)."""
    return config.plc.nodes_file.parent / "feedlift_calib.json"


def _operation_dir(config: AppConfig) -> Path:
    """流程仓库目录 = config/operation (UI 直读直写, 其顶层子文件夹即分组)."""
    return config.plc.nodes_file.parent / "operation"


def _resource_specs(config: AppConfig) -> dict[str, ResourceSpec]:
    """设备资源表 = plc_nodes.yaml 同级的 resources.yaml (即 config/resources.yaml)."""
    return load_resource_specs(config.plc.nodes_file.parent / "resources.yaml")


def _material_topology(config: AppConfig) -> MaterialTopology:
    """物料拓扑 = plc_nodes.yaml 同级的 material_topology.yaml (四类物料/位置/传感器单一真源)."""
    return load_topology(config.plc.nodes_file.parent / "material_topology.yaml")


def _material_bindings(config: AppConfig, topology: MaterialTopology) -> MaterialBindings:
    """物料记账绑定表 = plc_nodes.yaml 同级的 material_bindings.yaml; 名字按拓扑交叉校验."""
    return load_bindings(config.plc.nodes_file.parent / "material_bindings.yaml", topology)


def _script_validator(reg_box: dict, specs: dict[str, ResourceSpec]):
    """构造流程脚本校验器.

    动作名集经 reg_box 实时跟随 registry (重命名/增删动作不失真); 资源名与模式、以及禁止
    编排层直调的资源钩子动作 (如 pump.vacuum_on/off) 由资源表把关.

    参数:
        reg_box: 可变持有盒 {"reg": ActionRegistry}
        specs: 资源表 {资源名: ResourceSpec}
    返回:
        Callable[[dict], list[str]], 返回错误消息列表 (空=合法)
    """
    modes = {rid: spec.mode for rid, spec in specs.items()}
    hooks = {name for spec in specs.values() for name in (spec.activate, spec.deactivate) if name}
    return lambda d: validate_script(d, valid_actions={a.name for a in reg_box["reg"].list()},
                                     resource_modes=modes, hook_actions=hooks)


# ------------------------------------------------------------------
# 共享装配逻辑
# ------------------------------------------------------------------

async def _build_water_level(config: AppConfig):
    """按 config.water_level 构建并连接液位 MQTT 客户端 + 只读快照控制器。

    未启用 / paho-mqtt 缺失 / 构建失败 → 返回 (None, None), 不阻断起服 (节点显示离线)。
    connect() 仅发起连接, 在线状态由香橙派 LWT (water_level/status) 异步回报。
    """
    wl = config.water_level
    if not wl.enabled:
        return None, None
    try:
        from eit_ptlc.controller.waterlevel_controller import WaterLevelController
        from eit_ptlc.driver.orangepi_waterlevel import WaterLevelClient
    except ImportError as exc:  # paho-mqtt 未安装
        log.warning("[WL] 液位驱动不可用, 跳过 (paho-mqtt 未安装?): %s", exc)
        return None, None
    try:
        client = WaterLevelClient(wl.broker_ip, wl.broker_port)
        ctrl = WaterLevelController(client)  # 注册 on_data/on_state/on_alarm 回调
        if not await client.connect():
            log.warning("[WL] 液位 MQTT 连接发起失败, 节点显示离线 (broker=%s:%s)",
                        wl.broker_ip, wl.broker_port)
        return client, ctrl
    except Exception as exc:  # 构建/连接异常一律降级, 不阻断起服
        log.warning("[WL] 液位客户端构建失败, 跳过: %s", exc)
        return None, None


def _build_water_level_detect(config: AppConfig, wl_client, config_path):
    """按 config.water_level 构建上位机拉帧检测服务 (检测真源, percent)。

    未启用 / cv2/httpx 缺失 → None (snapshot 回退离线, 不阻断起服)。
    标定真源: water_level.calib_path, 缺省取 config 目录下 water_level_calib.json。
    """
    wl = config.water_level
    if not wl.enabled:
        return None
    try:
        from eit_ptlc.controller.waterlevel_service import WaterLevelDetectService
    except ImportError as exc:
        log.warning("[WL] 拉帧检测服务不可用 (cv2/httpx 缺失?): %s", exc)
        return None
    config_dir = Path(config_path).parent
    calib_path = Path(wl.calib_path) if wl.calib_path else (config_dir / "water_level_calib.json")
    # 迁移友好: 上位机真源不存在但香橙派原文件 water_level_config.json 在 → 一次性转换
    # (之后 calib.json 作真源, 香橙派原文件留备份不动; 重迁需先删 calib.json)
    if not calib_path.is_file():
        legacy = config_dir / "water_level_config.json"
        if legacy.is_file():
            try:
                from eit_ptlc.controller.waterlevel_store import (
                    load_channel_configs, save_channel_configs)
                save_channel_configs(calib_path, load_channel_configs(legacy))
                log.info("[WL] 已从香橙派 %s 迁移标定 → %s", legacy.name, calib_path.name)
            except Exception as exc:
                log.warning("[WL] 标定迁移失败: %s", exc)
    return WaterLevelDetectService(
        orangepi_ip=wl.orangepi_ip, stream_port=wl.stream_port,
        config_path=calib_path, interval=wl.detect_interval, wl_client=wl_client,
        max_active_channels=wl.max_active_channels)


def _build_water_level_recorder(config: AppConfig, wl_detect):
    """按 config.water_level 构建上位机单通道原始录制器 (Phase 0; 手动/自动录制共用)。

    未启用 / cv2/httpx 缺失 → None (录制命令回 503, 不阻断起服)。
    帧源与检测器同 (香橙派 /frame/chN); 起始时从拉帧检测服务读该通道标定快照写进 meta,
    检测服务不在 → 快照 null。
    """
    wl = config.water_level
    if not wl.enabled:
        return None
    try:
        from eit_ptlc.controller.waterlevel_recorder import WaterLevelRecorder
    except ImportError as exc:
        log.warning("[WL] 单通道录制器不可用 (cv2/httpx 缺失?): %s", exc)
        return None

    def _calib_snapshot(channel: int):
        """录制起始时读该通道当时标定 (只读; 检测服务缺/异常 → None)。"""
        if wl_detect is None:
            return None
        cfg = wl_detect.get_config(int(channel))
        if cfg is None:
            return None
        c = cfg.calib
        return {
            "rotation_angle_deg": c.rotation_angle_deg,
            "roi_bbox": list(c.roi_bbox) if c.roi_bbox is not None else None,
            "roi_frac": list(c.roi_frac) if c.roi_frac is not None else None,
            "dry_ref_frac": list(c.dry_ref_frac) if c.dry_ref_frac is not None else None,
            "flow_direction": c.flow_direction,
            "calibrated": bool(c.calibrated),
            "params": wl_detect.get_params(int(channel)),
        }

    return WaterLevelRecorder(
        wl.orangepi_ip, wl.stream_port,
        cap_fps=wl.cap_fps, cap_width=wl.cap_width, cap_height=wl.cap_height,
        recordings_dir=wl.recordings_dir, calibration_snapshot=_calib_snapshot)


def _build_orangepi(config: AppConfig):
    """按 config.water_level 构建香橙派 SSH 远程管理器 (仅持配置, 不建立连接)。

    未启用 → None (相关 REST 路由返回 503)。先决条件: 本机已配 SSH 免密登录香橙派。
    """
    wl = config.water_level
    if not wl.enabled:
        return None
    try:
        from eit_ptlc.driver.orangepi_ssh import OrangePiManager
    except ImportError as exc:
        log.warning("[OPI] 香橙派 SSH 管理器不可用, 跳过: %s", exc)
        return None
    return OrangePiManager(
        ssh_user=wl.ssh_user,
        ssh_ip=wl.ssh_ip or wl.orangepi_ip,  # ssh_ip 留空则复用 MJPEG 用的 orangepi_ip
        work_dir=wl.work_dir,
        script_name=wl.script_name,
        broker_ip=wl.broker_ip,
        broker_port=wl.broker_port,
        start_timeout=wl.start_timeout,
        payload_dir=wl.payload_dir,  # 供"推送载荷"按钮 scp 同步香橙派端脚本
        # 抓帧脚本启动参数 (注入 run.sh; cameras/tl_bl_cm 缺则脚本 argparse 退出)
        stream_port=wl.stream_port,
        cameras=wl.cameras,
        tl_bl_cm=wl.tl_bl_cm,
        cap_width=wl.cap_width,
        cap_height=wl.cap_height,
        cap_fps=wl.cap_fps,
        exposure_time=wl.exposure_time,
        awb_temp=wl.awb_temp,
        no_detect=wl.no_detect,
    )


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _build_recorder(*, sim_mode: bool, manual_points_file: Path) -> StateRecorder | None:
    """构建并启动状态录像机; 失败一律降级为"不录", 绝不拖垮上位机启动。

    可调环境变量:
        PTLC_RECORD_ENABLED    0 关闭录制 (默认开)
        PTLC_RECORD_ROOT       存储根 (默认 eit_ptlc/var/recordings)
        PTLC_RECORD_DAYS       保留天数 (默认 30)
        PTLC_RECORD_MAX_GB     总容量上限 GB (默认不限, 由天数兜底)
        PTLC_RECORD_CHUNK_S    分块时长秒 (默认 10)

    sim_mode 只改 sessions.kind, 不改是否录 —— 仿真录像本身有价值 (沙盒复现),
    但绝不能与真机录像混在一起, 事故追溯时分不清哪条是真的比没有录像更糟。

    manual_points_file 只用来读工位归属 (时间轴的利用率条按工位聚合): 单点控制点表
    已经把 62 个气缸与轴分好组, 不必新建第二份映射。读不到就退化成"全部实体认不出
    工位", status() 会把它们列出来 —— 比悄悄画一条恒为 0 的条诚实。
    """
    explicit = os.environ.get("PTLC_RECORD_ENABLED")
    if explicit is None and os.environ.get("PYTEST_CURRENT_TEST"):
        # 离线测试里每建一次 app 就会起一个录制会话, 往仓库的 var/ 里写真数据, 且多个
        # 用例并发开同一个索引库会撞 "database is locked"。测试要的是可重复与不留痕,
        # 录像对它没有任何价值 —— 默认关掉, 需要时用 PTLC_RECORD_ENABLED=1 显式打开。
        return None
    if not _env_flag("PTLC_RECORD_ENABLED", True):
        log.info("[dvr] 已按 PTLC_RECORD_ENABLED 关闭状态录制")
        return None
    try:
        max_gb = float(os.environ.get("PTLC_RECORD_MAX_GB", "0") or 0)
        store = RecordingStore(
            os.environ.get("PTLC_RECORD_ROOT") or default_root(),
            retention_days=float(os.environ.get("PTLC_RECORD_DAYS", "30") or 30),
            max_bytes=int(max_gb * 1e9) if max_gb > 0 else None,
        )
        try:
            station_map = load_station_map(manual_points_file)
        except (FileNotFoundError, ValueError):
            log.warning("[dvr] 读不到单点控制点表 %s, 利用率条无法按工位聚合",
                        manual_points_file)
            station_map = {}
        recorder = StateRecorder(
            store,
            kind="sim" if sim_mode else "real",
            chunk_seconds=float(os.environ.get("PTLC_RECORD_CHUNK_S", "10") or 10),
            station_map=station_map,
        )
        recorder.start(note="上位机启动")
        # 启动时做一次**便宜的**索引整理: 目录整个没了的会话 + 时间戳不合理的块行。
        # 这两类会让回放直接不可用(前者读到空气 500, 后者把时间轴下界拖到 1970),
        # 而代价只有每会话一次 stat。逐块核对留给 POST /api/recording/reconcile。
        try:
            fixed = recorder.store.reconcile(active_session_id=recorder.status()["session"]["id"])
            if any(v for k, v in fixed.items() if k != "coverage"):
                log.info("[dvr] 启动整理索引: %s",
                         {k: v for k, v in fixed.items() if k != "coverage" and v})
        except Exception:
            log.exception("[dvr] 启动整理索引失败(不影响录制)")
        return recorder
    except Exception:
        log.exception("[dvr] 状态录制启动失败, 本次运行不录像")
        return None


async def _shutdown_recorder(app) -> None:
    """收尾: 把最后一块落盘并结束会话, 否则末尾几秒的录像会丢在内存里。"""
    recorder = getattr(app.state, "recorder", None)
    if recorder is None:
        return
    try:
        recorder.stop()
    except Exception:
        log.exception("[dvr] 录制收尾失败")


async def _shutdown_manual(app) -> None:
    """进程退出前收口单点会话: 撤 PC_Manual_Enable 并清扫全部执行器命令位.

    不做这一步的话, 阀会一直通着直到 PLC 侧 3s 心跳看门狗兜底 —— 那条路能兜住,
    但让 OPC UA 链路在"阀还开着"的状态下断开不是好习惯。
    """
    manual = getattr(app.state, "manual", None)
    if manual is None:
        return
    try:
        await manual.exit(reason="上位机退出")
    except Exception as exc:
        log.warning("[Manual] 退出时收口失败 (PLC 看门狗兜底): %s", exc)


def _build_shared_state(app, config: AppConfig, registry: ActionRegistry, reg_box: dict,
                        plc: PlcController, robot: RobotController,
                        stations: tuple[str, ...], script_repo: ScriptRepo,
                        stop: asyncio.Event, config_path,
                        water_level_client=None, water_level_ctrl=None,
                        water_level_detect=None, water_level_recorder=None,
                        sim_mode: bool = False):
    """填充 app.state 的共享字段 (executor / bus / vm / telemetry / points / config / 液位)."""
    # AppConfig 快照: 仿真沙盒 (api/sim_routes -> runtime/sim_stack) 建栈时按它取
    # 点表/拓扑/相机等路径 —— 只读使用, 不经它改配置 (改配置走 config_svc)。
    app.state.app_config = config
    bus = EventBus()
    # 高频机器人姿态只旁听既有 30004 读帧：后台 reader 线程自 connect() 起无条件常转，
    # 每帧都回调观察者，因此发布速率完全由 _ROBOT_POSE_MIN_INTERVAL 决定（原生约 125 Hz）。
    # 连接断开时无帧可听，由原 1 Hz telemetry 兼容回退。观察者不发任何控制命令。
    transport = getattr(robot, "transport", None)
    if transport is not None and hasattr(transport, "set_feedback_observer"):
        loop = asyncio.get_running_loop()
        pose_state = {"last": 0.0, "seq": 0}

        def _publish_robot_pose(frame, captured_at: float) -> None:
            if captured_at - pose_state["last"] < _ROBOT_POSE_MIN_INTERVAL:
                return
            pose_state["last"] = captured_at
            pose_state["seq"] += 1
            bus.publish({
                "type": "robot_pose",
                "joint": list(frame.joint),
                "pose": list(frame.pose),
                "tool": int(robot.mounted_tool),
                "mode": int(frame.robot_mode),
                "ts": captured_at,
                "seq": pose_state["seq"],
            })

        def _observe_robot_pose(frame) -> None:
            captured_at = time.time()
            loop.call_soon_threadsafe(_publish_robot_pose, frame, captured_at)

        transport.set_feedback_observer(_observe_robot_pose)
    run_store = RunStore(_DATA_DIR / "runs.db")
    # 启动收敛: 此刻 VmController 尚未构造, 库里凡是 RUNNING 的行都是上个进程的残留
    # (单步停驻被遗弃 / 动作在飞时被杀), 一律判 INTERRUPTED —— 否则顶栏与三维物料门禁
    # 会被一条永远不会结束的假 RUNNING 点亮 (2026-08-14 实测库里积了 5 条, 最早 6 月底)
    orphan_ids = run_store.reconcile_orphans()
    if orphan_ids:
        log.info("启动收敛: %d 条残留 RUNNING 运行已判为中断: %s", len(orphan_ids), orphan_ids)
    # 物料账本: 独立库文件, 绝不与 runs.db 合并 —— 后者 max_runs LRU 淘汰最旧运行连带其事件,
    # 而 (板x孔) 余量账本不能被淘汰。绑定表拼错即在此启动失败, 避免静默漏账。
    material_topology = _material_topology(config)
    material_store = MaterialStore(_DATA_DIR / "materials.db",
                                   topology=material_topology,
                                   bindings=_material_bindings(config, material_topology))
    # 统一点位目录: 机器人点位聚合自运行期点表(含派生点); PLC 伺服/目标点位按工位散于 config/points/plc/
    # (先于 node_registry/executor 建: 供 Rail 节点映射所在站 + servo_target 原子 push_target 下发 *_Target)
    points = PointsService(
        config.plc.nodes_file.parent / "points", robot.registry,
        driver=plc._driver, robot=robot,
        robot_points_file=config.robot.points_file,
        robot_meta_file=config.robot.points_meta_file,
        point_source_version=config.robot.point_source_version)
    # 地轨站位坐标 (slot->mm, rail.yaml 真源): 供 Rail 节点据实际位置(Rail_ActPos)映射所在站名 (缺/异常 -> {})
    try:
        rail_stations = {p.slot: p.value for p in points._servo_points_in("rail") if p.value is not None}
    except Exception:
        rail_stations = {}
    node_registry = build_node_registry(robot=robot, plc=plc, stations=stations, rail_stations=rail_stations)
    # sim 模式始终用预置图，避免调试台或动作误触真机相机/UV。
    camera_cfg = replace(config.camera, mock=True) if sim_mode else config.camera
    camera = CameraController.from_config(camera_cfg)  # camera 拍照动作 (profile 预填+覆写)
    # cnc_path 计算动作 (vision kind): 运行期实时读 app.yaml gcode 段, config 页改动即时生效
    cnc_ctrl = CncPathController(
        lambda: _parse_gcode(app.state.config_svc.read_section("gcode")),
        image_root_provider=lambda: Path(config.vision.output_dir),
        # 三维孪生的刮痕条带: 只有这里知道本次视觉解出的谱带在板上的哪一块
        # (下发 PLC 的是机床 mm 数组, 反算不回板帧)。见 CncPathController._emit_scrape_armed
        event_sink=bus.publish,
    )
    # 刮后对账叠加 (vision kind): 刮后照片回放归一化帧 + 同一 preview payload 叠加, 全链 fail-safe (spec§5.2)
    scrape_reconcile = ScrapeReconcileController(
        image_root_provider=lambda: Path(config.vision.output_dir),
    )
    # 视觉分析动作 (vision kind): 前后图 → summary.json (测试用预置图; mock 由 config.vision.mock 控)
    vision_svc = VisionService(
        output_dir=config.vision.output_dir,
        mock_mode=config.vision.mock,
        image_plate_orientation=config.vision.image_plate_orientation,
        auto_rectify_tilt=config.vision.auto_rectify_tilt,
        rectify_min_angle_deg=config.vision.rectify_min_angle_deg,
        min_row_score=config.vision.min_row_score,
        image_plate_rotation_deg=config.vision.image_plate_rotation_deg,
    )
    pallas_light_setter = None
    if config.pallas_vision.light_control_enabled:
        pallas_light_setter = make_pallas_light_setter(config, robot, app)

    pallas_vision = PallasVisionClient(config.pallas_vision, light_setter=pallas_light_setter)
    app.state.pallas_vision = pallas_vision
    debug_cfg = config.vision_debug
    app.state.vision_debug = VisionDebugService(
        debug_cfg.workspace_dir,
        camera,
        vision_svc,
        camera_defaults={
            "exposure_time_us": debug_cfg.default_exposure_time_us,
            "gain": debug_cfg.default_gain,
            "uv_on_time_ms": debug_cfg.default_uv_on_time_ms,
        },
        # 识别参数默认由 config.vision 单一真源播种 (不再取 vision_debug; 见 memory vision-tab-single-track)
        recognition_defaults={
            "image_plate_orientation": config.vision.image_plate_orientation,
            "auto_rectify_tilt": config.vision.auto_rectify_tilt,
            "rectify_min_angle_deg": config.vision.rectify_min_angle_deg,
            "min_row_score": config.vision.min_row_score,
            "image_plate_rotation_deg": config.vision.image_plate_rotation_deg,
        },
    )
    def _live_vision_recognition() -> dict:
        """运行期实时读 config.vision 的 5 识别参数作 analyze 基线 (照抄 cnc_ctrl 的
        live-read; 现状 vision_svc 建时烘死一次, 改 config 需重启 —— 这里让每次 analyze 读
        活配置, 使调试台"应用到生产"即时生效)。config_svc 未就绪(纯离线测试)/读失败 → {}
        → 回落 vision_svc 烘定基线。"""
        cfg_svc = getattr(app.state, "config_svc", None)
        if cfg_svc is None:
            return {}
        try:
            vcfg = _parse_vision(cfg_svc.read_section("vision"))
        except Exception:
            logging.getLogger(__name__).warning(
                "[bootstrap] 实时读 config.vision 失败, analyze 回落烘定基线", exc_info=True
            )
            return {}
        return {
            "image_plate_orientation": vcfg.image_plate_orientation,
            "auto_rectify_tilt": vcfg.auto_rectify_tilt,
            "rectify_min_angle_deg": vcfg.rectify_min_angle_deg,
            "min_row_score": vcfg.min_row_score,
            "image_plate_rotation_deg": vcfg.image_plate_rotation_deg,
        }

    async def _analyze_live(sample_id, before_path, after_path, **overrides):
        """VM vision.analyze 入口: config.vision 活基线 + 每-run 覆盖 (门内重识别 / 中控)。
        overrides = vision.yaml 声明的 5 个可选识别参数 (VM 缺省即不在 kwargs)。"""
        merged = _live_vision_recognition()
        merged.update({key: value for key, value in overrides.items() if value is not None})
        return await vision_svc.analyze_action(sample_id, before_path, after_path, **merged)

    async def _wait_level(**kwargs):
        """VM develop.wait_level 入口: 液位阈值等待 (host 轮询; 服务未启用则拒绝)。
        经 app.state 惰性取服务 — 不依赖 bootstrap 内构造顺序。"""
        detect = getattr(app.state, "water_level_detect", None)
        if detect is None:
            raise ValueError("液位检测服务未启用 (water_level.enabled=false), develop.wait_level 不可用")
        from eit_ptlc.controller.waterlevel_trigger import wait_level
        return await wait_level(detect, **kwargs)

    async def _wl_capture_reference(**kwargs):
        """VM develop.capture_reference 入口: run 起点自动采集干板参考。

        服务未启用 (water_level.enabled=false) 时不 raise — 返回 ok=false 让流程走
        "参考不可用→退化人工门" 分支 (与 D1 语义同构), manual 模式不因液位服务停用而炸。
        """
        detect = getattr(app.state, "water_level_detect", None)
        if detect is None:
            log.warning("[WL] capture_reference: 液位检测服务未启用, 返回 ok=false (流程退化人工门)")
            return {"ok": False, "has_ref": False, "elapsed_s": 0.0}
        from eit_ptlc.controller.waterlevel_trigger import capture_reference
        return await capture_reference(detect, **kwargs)

    async def _align_readout(**kwargs):
        """VM photoscrape.align_readout 入口: 读三轴 ActPos + live-read gcode → 回显/Δ/建议。
        经 app.state 惰性取 config_svc (赋值晚于本闭包定义, getattr 惰性读无顺序问题);
        纯计算在 controller/align_check.build_align_readout, 本闭包只做 IO。"""
        from eit_ptlc.controller.align_check import build_align_readout
        cfg_svc = getattr(app.state, "config_svc", None)
        if cfg_svc is None:
            raise ValueError("配置服务未就绪, align_readout 不可用")
        g = _parse_gcode(cfg_svc.read_section("gcode"))
        axes = await plc.read_scrape_axes()
        return build_align_readout(axes, g)

    async def _photoscrape_wait_rot(target: str = "extend", timeout_s: float = 6.0) -> dict:
        """VM photoscrape.wait_rot 入口: 轮询 IX9 等接粉桶翻料缸到位。

        A41/A52 都是开环(同一扫描周期返回 DONE, 不等气缸反馈), 到位位却一直读得到 ——
        IX9.7=动点 / IX9.6=原点。轮询与判定在 controller/photoscrape_rot, 本闭包只做 IO。

        哨兵语义: 该函数永不抛, 超时/读不到只 ok=false + WARN。翻料没翻成不影响板子,
        但在收尾这一步抛错会把已完成的标定判成 ABORTED、生产侧让板卡在压头下。
        """
        from eit_ptlc.controller.photoscrape_rot import wait_rot

        async def _read_ix9():
            try:
                return await plc.read_host_var("IX9")
            except Exception as exc:      # 节点未下装/通讯抖动不该炸掉收尾链
                log.warning("[翻料缸] IX9 读取异常, 按读不到处理: %s", exc)
                return None

        return await wait_rot(_read_ix9, target=str(target), timeout_s=float(timeout_s))

    async def _feedlift_probe(magazine: str, z_prev=None, expect_taken=None,
                              reconcile: bool = False, z_clear=None) -> dict:
        """VM feedlift.probe_stack 入口: 读升降轴位置 → 换算板数 / 差分判定 / 对账。

        纯计算在 controller/feedlift_count.py::evaluate, 本闭包只做 IO 与落账:
        判定不通过时抛错交执行器转 ERROR (双张/空吸/读数不可信一律停机);
        reconcile 为真时以实测为准校正账本 —— 实测是真值, 账实不符只留痕不报错。

        给了 z_clear 时先做陈旧读数自校验: 逼近动作在光电已 TRUE 时是幂等直通, 此时
        读回的是上次停轴的位置, 换算出来的板数会是上一次的。这个守卫属于"这个读数可不
        可信"的判断, 和残差/量程判定同类, 故与它们放在一起。
        """
        from eit_ptlc.controller.feedlift_count import (
            MAGAZINE_AXIS, MIN_APPROACH_MM, evaluate, load_calib)

        axis = MAGAZINE_AXIS[magazine]
        # 仓容量取自物料拓扑 (单一真源), 不在标定文件里重复定义
        calib = load_calib(_feedlift_calib_path(config), magazine,
                           material_topology.magazines[magazine][1])
        z_mm = await plc.read_feedlift_pos(axis)
        if z_clear is not None:
            approach = round(z_mm - float(z_clear), 3)
            if approach <= MIN_APPROACH_MM:
                raise ValueError(
                    f"逼近动作返回 DONE 但轴几乎没动 (清零位 {float(z_clear):.3f}mm → 触发位 "
                    f"{z_mm:.3f}mm, 逼近仅 {approach:.3f}mm): 读数是陈旧值, 已拒绝采用。"
                    f"多半是清零动作没把光电退成 FALSE, 请查该动作与光电接线")
        result = evaluate(z_mm, calib, z_prev=z_prev, expect_taken=expect_taken)
        if not result["ok"]:
            raise ValueError(result["text"])
        if result["warn"] or result["pitch_drift"]:
            log.warning("[升降板仓] %s", result["text"])
        if reconcile:
            ledger = material_store.magazine_count(magazine)
            if ledger != result["count"]:
                # 账面与实测不符 = 手动试发动作漏账或人工加减料未录入; 实测是真值。
                # 差得多说明漏账已积累已久 (或机构异常), 提到 warning 让它可见。
                level = log.warning if abs(ledger - result["count"]) > 1 else log.info
                level("[升降板仓] %s 账面 %d 张, 光电行程实测 %d 张, 按实测校正",
                      material_topology.magazines[magazine][0], ledger, result["count"])
                material_store.set_magazine(magazine, result["count"],
                                            detail="光电行程盘点")
        return result

    async def _feedlift_preflight(magazine: str) -> dict:
        """VM feedlift.preflight 入口: 读 IX8 与 PLC_Ready, 做发动作前的可见前置自检。

        判定纯函数在 controller/feedlift_count.py::preflight_gate, 本闭包只做 IO。
        可见前置已经确定不满足时抛错止步 —— 与其让 PLC 白等 10 秒再回 301/302,
        不如在下发前就说清楚是哪一项。

        ⚠ 自检只能证伪不能证真: bHomed 与 Alarm 没有暴露成 OPC 节点, 通过了也不代表
        动作一定能跑; 返回体的 unobservable 如实列出这两项。
        """
        from eit_ptlc.controller.feedlift_count import preflight_gate

        ix8 = await plc.read_host_var("IX8")
        if ix8 is None:
            # 读到 None 不是"全 0", 是读不到 —— 当 0 用会得到一张骗人的快照并误报接近开关故障
            raise ValueError("输入字节 IX8 读回空值; 节点存在但无值, "
                             "通常是 PLC 未运行或输入映像未刷新")
        try:
            plc_ready = await plc.read_host_var("PLC_Ready")
        except Exception:                      # 该节点未下装时不该拖垮自检主线
            plc_ready = None
        result = preflight_gate(magazine, int(ix8),
                                None if plc_ready is None else bool(plc_ready))
        if not result["ok"]:
            raise ValueError(result["text"])
        log.info("[升降板仓] %s 前置自检: %s", magazine, result["text"])
        return result

    async def _feedlift_read_pos(magazine: str) -> dict:
        """VM feedlift.read_pos 入口: 读该板仓升降轴实际位置(mm)。

        编排里取位要经动作层才留得下痕迹 (谁在什么时候读到了多少); 直接在路由里读
        PLC 是看不见的。判定与换算不在这里, 见 feedlift.probe_stack。
        """
        from eit_ptlc.controller.feedlift_count import MAGAZINE_AXIS

        if magazine not in MAGAZINE_AXIS:
            raise ValueError(f"板仓应为 {tuple(MAGAZINE_AXIS)} 之一, 收到 {magazine!r}")
        axis = MAGAZINE_AXIS[magazine]
        return {"magazine": magazine, "axis": axis,
                "z_mm": round(await plc.read_feedlift_pos(axis), 3)}

    async def _feedlift_calib_record(magazine: str, plates: int,
                                     z_clear: float, z_trigger: float) -> dict:
        """VM feedlift.calib_record 入口: 自校验逼近位移 → 记样本 → 重新拟合 → 落盘。

        判定、拟合与落盘全在 controller/feedlift_count.py::record_sample (纯逻辑 + 文件),
        本闭包只注入路径与仓容量并留痕。
        """
        from eit_ptlc.controller.feedlift_count import record_sample

        label, capacity = material_topology.magazines[magazine]
        result = record_sample(_feedlift_calib_path(config), magazine, capacity,
                               plates, z_clear, z_trigger)
        log.info("[升降板仓] %s 采样: %d 张 -> %.3fmm (第 %d 组)",
                 label, result["plates"], result["z_mm"], result["n_samples"])
        fit = result["fit"]
        if result["reject_reason"]:
            # 定不出直线 (样本不足) 是正常过程态, 只有"定出来了但不合理"才值得告警
            if fit["ok"]:
                log.warning("[升降板仓] %s %s", label, result["reject_reason"])
        else:
            log.info("[升降板仓] %s 拟合: 节距 %.4fmm 空仓位 %.3fmm 残差 %s (%d 组)",
                     label, fit["pitch_mm"], fit["z_empty_mm"], fit["residual_rms_mm"],
                     fit["n"])
        return result

    # 耗材种类 -> 中转区 id (AREAS 是 {区: 种类}, 这里反向取)
    _kind_to_area = {kind: area for area, kind in AREAS.items()}

    def _staging_location(kind: str):
        """按耗材种类取其中转区的位置声明 (含在位传感器); 拓扑未声明则返回 None.

        参数:
            kind: 耗材种类 (collector | bottle)
        返回:
            LocationSpec 或 None
        """
        area = _kind_to_area.get(kind)
        if area is None:
            return None
        for loc in material_topology.locations:
            if loc.area == area and loc.sensor is not None:
                return loc
        return None

    async def _material_check_availability(need_collector: bool = False,
                                           need_bottle: bool = False,
                                           exclude_sample: str = "") -> dict:
        """VM material.check_availability 入口: 开工前逐类判定能否取到一件可用耗材。

        刻意放在流程最开头而不是备耗材那一步: 不足若等到搬板时才发现, 样品已经点样、
        展开、准备刮取, 中断就白费一个样品; 在这里拦下时样品还没动, 零损失。

        纯读账本, 不碰传感器; exclude_sample 供并行批次样品自检 (自己的预留不算占用,
        但**不落新预留** —— 预留由调度器准入与随后的 plan_staging 完成)。
        """
        plans: dict = {}
        short: list = []
        blocked: list = []
        for kind, needed in (("collector", bool(need_collector)), ("bottle", bool(need_bottle))):
            if needed is False:
                continue
            # 匿名调用 (V2/手动) 纯只读; 带 exclude_sample 时以该样品视角判定, 顺带把它的
            # 计数级预留升级为孔级 (plan_staging 幂等覆盖, 之后 ensure_* 再算会重选) ——
            # "预检即预定位", 对他人只是把占用算得更精确, 无额外占坑。
            plan = material_store.plan_staging(kind) if not exclude_sample else \
                material_store.plan_staging(kind, reserve_for=str(exclude_sample))
            plans[kind] = plan
            if plan["op"] == OP_EXHAUSTED:
                short.append(kind)
            elif plan["op"] == OP_BLOCKED:
                blocked.append(kind)
        if short:
            raise ValueError(
                f"耗材余量不足, 无法开工: {', '.join(short)} 在账本里已无未用孔; "
                f"请在物料页盘点补录后重试")
        if blocked:
            raise ValueError(
                f"耗材暂被并行批次占用: {', '.join(blocked)} 的可用孔已被其他样品预留"
                f" (或中转板上压着他人在保留件); 等其收集完成释放后重试, 无需补料")
        log.info("[物料] 开工前预检通过: %s", {k: v["op"] for k, v in plans.items()})
        return {"ok": True, "plans": plans}

    async def _material_plan_staging(kind: str, reserve_for: str = "") -> dict:
        """VM material.plan_staging 入口: 账本出决策 + 中转在位传感器防呆。

        决策查询在 material_store.plan_staging, 本闭包只做 IO 与核对。

        为什么必须核对: 账本一旦与现场失同步 (最常见来源是面板直跑 robot_group_* 叶子
        脚本不入账, 见 config/material_bindings.yaml 的已知边界), 按错账搬整板就是撞机。
        故对不上一律抛错停机等人盘点, 绝不硬放。
        货架侧那 12 路在位信号与物理世界零耦合 (现场实测恒 0), 无从核对, 只能信账本
        (板级在架另有人工账 rack_occupancy, plan_staging 已按它跳过无板库位)。

        reserve_for 非空 (并行批次样品): 决策同时落该样品的孔级预留, 挡住其他样品在
        plan 与 consume 的窗口内抢同一孔或把整板换走; 空串即旧行为, 手动直跑零变化。
        """
        plan = material_store.plan_staging(kind, reserve_for=str(reserve_for or ""))
        if plan["op"] == OP_EXHAUSTED:
            raise ValueError(
                f"{kind} 在账本里已无未用孔, 无法取件; 请在物料页盘点补录后重试")
        if plan["op"] == OP_BLOCKED:
            raise ValueError(
                f"{kind} 的可用孔已被其他样品预留 (或中转板上压着他人在保留件), "
                f"本次取件被拦; 等其收集完成释放后重试, 无需补料")
        loc = _staging_location(kind)
        if loc is None:
            # 拓扑没给该中转区传感器: 无从核对, 按账本直出 (不静默假装核对过)
            log.warning("[物料] %s 的中转区未声明在位传感器, 本次换板决策未做防呆", kind)
            return plan
        raw = await plc.read_host_var(loc.sensor.byte)
        if raw is None:
            # 读到 None 不是"全 0", 是读不到 —— 当 0 用会得到一张骗人的快照
            raise ValueError(
                f"中转区在位输入字节 {loc.sensor.byte} 读回空值; 节点存在但无值, "
                f"通常是 PLC 未运行或输入映像未刷新")
        present = loc.sensor.present(int(raw))
        # 只有 PUT_NEW 期望中转是空的; NONE 复用与 SWAP 送回都要求那块板还在
        expect_present = plan["op"] != OP_PUT_NEW
        if present != expect_present:
            if expect_present is False:
                raise ValueError(
                    f"{loc.label} 传感器报有板, 但账本记该区为空 (判定 {plan['op']} 要放新板): "
                    f"账实失同步, 硬放整板会撞。请在物料页核对中转占用后重试")
            raise ValueError(
                f"{loc.label} 传感器报无板, 但账本记着板 {plan['staged_plate']} "
                f"(判定 {plan['op']}): 账实失同步。请在物料页核对中转占用后重试")
        log.info("[物料] %s 换板决策 op=%s 取板=%s 还板=%s 孔=%s (中转板=%s)",
                 kind, plan["op"], plan["rack_slot"], plan["old_rack_slot"],
                 plan["hole"], plan["staged_plate"])
        return plan

    vision_methods = {
        "generate_cnc_path": cnc_ctrl.generate_cnc_path,
        "scraped_overlay": scrape_reconcile.scraped_overlay,
        "analyze": _analyze_live,
        "capture_plate_offset": pallas_vision.capture_plate_offset,
        "wait_level": _wait_level,
        "capture_reference": _wl_capture_reference,
        "align_readout": _align_readout,
        "photoscrape_wait_rot": _photoscrape_wait_rot,
        "feedlift_probe": _feedlift_probe,
        "feedlift_preflight": _feedlift_preflight,
        "feedlift_read_pos": _feedlift_read_pos,
        "feedlift_calib_record": _feedlift_calib_record,
        "material_check_availability": _material_check_availability,
        "material_plan_staging": _material_plan_staging,
    }
    # 孔板标定/下发服务: 内置+plates.yaml 类型, calibration.yaml 标定; 运行时 solve+算点写 *_Target。
    # 先于执行器构造并注入: 上样吸液按 (规格+盘位号+孔) 寻址时由执行器调 push_well。软限位由 points.yaml 注入。
    _cfg_dir = config.plc.nodes_file.parent

    def _axis_limits(key: str) -> tuple[float, float] | None:
        t = points.target_entry(key)
        return None if t is None else (t.min_limit, t.max_limit)

    calibration = CalibrationService(
        PlateCatalog.load(_cfg_dir / "plates.yaml", _cfg_dir / "calibration.yaml"),
        plc._driver, _cfg_dir / "calibration.yaml",
        x_limits=_axis_limits("sampling_4x"), y_limits=_axis_limits("sampling_3y"))
    # 单点控制 (PC Manual Mode): 复刻 HMI 手动屏的执行器电平二态 + 轴点动。
    # 点表缺失不算致命 —— 保持 app.state.manual=None, 路由回 503, 其余功能照常。
    manual = None
    _manual_points_file = _cfg_dir / "manual_points.yaml"
    try:
        manual = ManualService(
            driver=plc._driver, plc=plc,
            manual_map=load_manual_points(_manual_points_file),
            bus=bus, maintenance_gate=getattr(app.state, "maintenance_gate", None),
            # VM 稍后才建 (见下方 app.state.vm), 故用惰性 provider 而非直接持有
            vm_provider=lambda: getattr(app.state, "vm", None),
            stations=tuple(stations))
    except FileNotFoundError:
        log.warning("[Manual] 未找到单点控制点表 %s, 单点控制端点将回 503", _manual_points_file)
    except Exception as exc:
        log.error("[Manual] 单点控制点表加载失败 (%s): %s", _manual_points_file, exc)
    app.state.manual = manual

    executor = ActionExecutor(registry, robot=robot, plc=plc, points=points,
                              driver=plc._driver, calibration=calibration, camera=camera,
                              vision_methods=vision_methods,
                              auto_rail=config.plc.auto_rail,
                              maintenance_gate=getattr(app.state, "maintenance_gate", None),
                              manual_guard=(manual.exclusion_reason if manual is not None else None))
    app.state.executor = executor
    app.state.calibration = calibration
    app.state.plc = plc  # L2 工位运行时控制 (snapshot/reset) 直读控制器; 运行仍走 executor (动作目录)
    # 板位对位: 点样视觉零点一键示教 (executor 走运动 + pallas_vision 走取图/写零点热更)
    app.state.plate_align = PlateAlignService(executor=executor, vision_client=pallas_vision)

    # 动作 YAML 源文件服务 (整文件读写 + 热重载): 保存后同步刷新 registry 三处引用
    # (app.state.registry / executor 动作目录 / reg_box → VM 脚本校验器名集)
    def _on_actions_reload(new_reg: ActionRegistry) -> None:
        app.state.registry = new_reg
        reg_box["reg"] = new_reg
    app.state.actions = ActionsService(_actions_dir(config), executor=executor,
                                       on_reload=_on_actions_reload,
                                       operation_dir=_operation_dir(config))
    # 液位控制台 (快照 + 命令透传 + MJPEG 代理) 由 water_level_routes 经 app.state 读取
    app.state.water_level_client = water_level_client
    app.state.water_level_ctrl = water_level_ctrl
    app.state.water_level_detect = water_level_detect   # 上位机拉帧检测服务 (percent 真源)
    app.state.water_level_recorder = water_level_recorder  # 单通道原始录制器 (Phase 0; record_* 命令)
    app.state.water_level_cfg = config.water_level if water_level_client is not None else None
    water_level_observations = WaterLevelObservationCollector(
        water_level_detect, _DATA_DIR / "water-level-observations",
    )
    app.state.water_level_observations = water_level_observations
    # 香橙派 SSH 远程管理 (启动/停止 run.sh): 由 water_level_routes 经 app.state 读取
    app.state.orangepi = _build_orangepi(config)
    app.state.bus = bus
    app.state.run_store = run_store
    # 数字孪生状态录像机 (3D DVR)。此前高频连续量无人持久化: run_store.on_event 开头
    # 就以"无 run_id"为由把 axis_pose/robot_pose/mechanism_state 全部丢弃, 时间线因此
    # 只能回放到步骤粒度。
    #
    # 必须挂在 bus.add_tap 而不是 VmController 的 event_sink 上 —— 连续量由
    # realtime_feedback 与 30004 观察者**直接** bus.publish, 压根不经过 event_sink;
    # 挂错地方只会录到运行事件, 连续量一条也录不到, 而且不报任何错。
    # 存储根走 PTLC_RECORD_ROOT (本机是开发机, 部署机盘符不同, 不可写死)。
    app.state.recorder = _build_recorder(sim_mode=sim_mode,
                                         manual_points_file=_manual_points_file)
    if app.state.recorder is not None:
        bus.add_tap(app.state.recorder.on_event)
    app.state.material_store = material_store
    app.state.material_topology = material_topology  # 物料页/升降标定路由按它取仓号与容量
    app.state.feedlift_calib_path = _feedlift_calib_path(config)  # 板仓行程标定端点读写此文件
    app.state.node_registry = node_registry
    app.state.points = points
    # 设备参数 (app.yaml camera/gcode/vision 段, 含 CNC 几何/进给) 读写; CNC 已归此页, 点位页不再展示
    app.state.config_svc = ConfigService(config_path)
    # 泵档持久默认 live-read: knob 传值 > config.pump > translator 常量 (清洗在闭包, profiles 不依赖 loader)
    _cfg_svc = app.state.config_svc
    set_pump_defaults_provider(lambda: _parse_pump(_cfg_svc.read_section("pump")))

    async def _run_resource_hook(action: str) -> None:
        """资源门驱动共享设备物理开关: 执行动作, 非 DONE 即抛出使持有方运行以失败收口.

        参数:
            action: 资源表登记的 activate/deactivate 动作名 (如 pump.vacuum_on)
        """
        result = await executor.execute(action, {}, current_mode=app.state.control_mode)
        if result.status is not ActionStatus.DONE:
            raise ResourceError(f"资源钩子动作 {action} 未成功: {result.status.value} {result.message}")

    # 资源门: 独占资源 (工位/机器人/展缸) 互斥, 共享资源 (大真空泵) 引用计数合成唯一物理开关
    res_gate = ResourceGate(_resource_specs(config), activator=_run_resource_hook)
    app.state.res_gate = res_gate
    # 调度器 late-box: 调度器依赖 VM 只能后建, 而 sink 元组在 VmController 构造时冻结,
    # 经 box 解环 —— 调度器就位前该 sink 是空操作。
    sched_box: dict = {}

    def _sched_sink(event: dict) -> None:
        sched = sched_box.get("s")
        if sched is not None:
            sched.on_vm_event(event)

    app.state.vm = VmController(
        executor=executor, res_gate=res_gate,
        resolve_script=lambda n: script_repo.get("default", n),
        event_sink=make_event_sink(
            water_level_observations.on_event, bus.publish, run_store.on_event,
            material_store.on_event, _sched_sink,
        ),
        mode_provider=lambda: app.state.control_mode,
        maintenance_gate=getattr(app.state, "maintenance_gate", None))
    # 并行实验系统: 实验库 (独立 experiments.db, 不并入会 LRU 淘汰的 runs.db) + 段级调度器
    experiment_store = ExperimentStore(
        config.experiment.db_path or (_DATA_DIR / "experiments.db"))
    scheduler = FlowScheduler(
        vm=app.state.vm, res_gate=res_gate,
        resolve_script=lambda n: script_repo.get("default", n),
        material_store=material_store, experiment_store=experiment_store,
        registry=reg_box["reg"],
        resource_modes={rid: spec.mode for rid, spec in _resource_specs(config).items()},
        recipes_dir=config.recipes_dir, bus=bus,
        wip_limit=config.experiment.wip_limit, tank_pool=config.experiment.tank_pool,
        default_recipe=config.experiment.recipe,
        vision_output_dir=Path(config.vision.output_dir))
    scheduler.config_service = app.state.config_svc   # 提交时冻结 gcode/pump/vision 三段快照
    sched_box["s"] = scheduler
    app.state.experiment_store = experiment_store
    app.state.scheduler = scheduler
    scheduler.start()
    realtime_feedback = None
    if manual is not None:
        realtime_feedback = asyncio.create_task(
            realtime_feedback_loop(
                manual, bus, stop,
                # 末端执行器(夹爪/吸盘翻转)状态并入同一 mechanism_state 事件,
                # 三维孪生按 rob_* 机构 id 驱动几何; 见 RobotController.mechanism_snapshot.
                robot_states=robot.mechanism_snapshot if robot is not None else None,
            ),
            name="realtime-feedback-loop",
        )
    app.state.realtime_feedback_task = realtime_feedback
    material_feedback = asyncio.create_task(
        material_feedback_loop(material_store, bus, stop),
        name="material-feedback-loop",
    )
    app.state.material_feedback_task = material_feedback
    telemetry = asyncio.create_task(telemetry_loop(node_registry, bus, stop), name="telemetry-loop")
    return executor, bus, run_store, node_registry, telemetry, material_store, experiment_store, scheduler


# ------------------------------------------------------------------
# Sim 装配
# ------------------------------------------------------------------

def create_sim_app(config_path: str | Path = _DEFAULT_CONFIG, *, opcua_url: str = _SIM_URL):
    """构建 sim 模式 FastAPI 应用: 内存机器人 + Mock PLC, lifespan 内装配执行器与流程引擎.

    opcua_url: Mock OPC UA 监听地址; 测试可传不同端口以避免并发/连跑端口占用.
    """
    config = load_config(Path(config_path))
    three_d_authoring = ThreeDAuthoringService(
        config.three_d.workspace_root,
        hardware_root=config.three_d.hardware_root,
    )
    registry = ActionRegistry.load(_actions_dir(config))
    # 可变持有盒: 动作 raw 编辑保存后由 ActionsService 更新, 使脚本校验器名集实时跟随 (重命名/增删动作不失真)
    reg_box = {"reg": registry}
    # 流程仓库 = config/operation 本身 (子文件夹即组); 校验器引用动作目录与资源表; 版本历史落 var 避免污染配置目录
    script_repo = ScriptRepo(_operation_dir(config),
                             validator=_script_validator(reg_box, _resource_specs(config)),
                             history_root=_DATA_DIR / "operation_history")

    @asynccontextmanager
    async def lifespan(app):
        maintenance_gate = MaintenanceGate()
        app.state.maintenance_gate = maintenance_gate
        node_map = load_plc_nodes(config.plc.nodes_file)
        server = await build_mock_server(opcua_url, node_map)
        # 单点控制的兄弟容器 (cyinder_date / servoaxisdate / GVL / IO / PLC_PCManual):
        # 点表缺失时跳过, sim 其余部分照常起。
        manual_map = None
        try:
            manual_map = load_manual_points(config.plc.nodes_file.parent / "manual_points.yaml")
            await build_manual_mock_tree(server, manual_map)
        except FileNotFoundError:
            log.warning("[sim] 未找到单点控制点表, Mock 不建单点容器")
        except Exception as exc:
            log.error("[sim] 单点控制 Mock 容器构建失败: %s", exc)
            manual_map = None
        async with server:
            stop = asyncio.Event()
            fsms = [asyncio.create_task(run_l2_fsm(server, prefix, stop)) for prefix in _ALL_L2_STATIONS]
            fsms.append(asyncio.create_task(run_deploy_fsm(server, stop)))
            if manual_map is not None:
                # 复刻 PLC_PCManual 的判定/看门狗/清扫 + 气缸到位反馈 + 轴运动积分
                fsms.append(asyncio.create_task(run_manual_fsm(
                    server, stop, manual_map,
                    lambda name: mock_read(server, name),
                    lambda name, value: mock_write(server, name, value))))
            driver = OpcUaDriver(opcua_url, node_map, reconnect_wait_timeout=10.0,
                                 subscription_queue_size=config.plc.subscription_queue_size,
                                 subscription_sampling_ms=config.plc.subscription_sampling_ms,
                                 request_timeout=config.plc.request_timeout,
                                 watchdog_interval=config.plc.watchdog_interval,
                                 max_inflight_requests=config.plc.max_inflight_requests)
            await driver.connect()
            plc = PlcController(driver, poll_interval=0.05, action_timeout=config.plc.action_timeout,
                                stall_timeout=config.plc.action_stall_timeout,
                                soft_recheck=config.plc.action_soft_recheck)
            # 单一来源加载: robot_points.json + meta (派生点已全部并入 meta.supplement);
            # 运行期不再叠加 robot_flows_v2.yaml (该文件仅供离线生成工具 gen_robot_point_operations.py)
            point_registry = PointRegistry.load(config.robot.points_file, source_version=config.robot.point_source_version,
                                                meta_path=config.robot.points_meta_file)
            # 仿真机器人起始置于 home 点 (使点位 operation 进/出 require_anchor 通过; 真机由实际位姿决定)
            home_pt = point_registry.get(config.robot.home_point)
            robot_transport = SimRobotTransport(pose=home_pt.pose, joint=home_pt.joint)
            robot_transport.connect()
            robot = RobotController(robot_transport, point_registry, home_point=config.robot.home_point,
                                    jog_speed_percent=config.robot.jog_speed_percent,
                                    step_distance_mm=config.robot.step_distance_mm,
                                    step_angle_deg=config.robot.step_angle_deg,
                                    maintenance_gate=maintenance_gate)
            _telemetry = None
            material_store = None
            experiment_store = None
            scheduler = None
            try:
                (_, __, run_store, ___, _telemetry, material_store,
                 experiment_store, scheduler) = _build_shared_state(
                    app, config, registry, reg_box, plc, robot, _ALL_L2_STATIONS,
                    script_repo, stop, config_path, sim_mode=True)
                log.info("[sim] 执行器+VM编排+节点遥测就绪: 内存机器人仿真 + Mock PLC L2 %s", _ALL_L2_STATIONS)
                yield
            finally:
                # 仿真沙盒先收口 (独立栈, 与主栈无共享任务, 先停防止悬挂连接)
                _sim_stack = getattr(app.state, "sim", None)
                if _sim_stack is not None:
                    app.state.sim = None
                    await _sim_stack.stop()
                # 单点会话必须先收口: 撤 Enable 并清扫全部执行器命令位, 再断链
                await _shutdown_recorder(app)
                await _shutdown_manual(app)
                if scheduler is not None:
                    await scheduler.stop()
                stop.set()
                tasks = [*fsms]
                if _telemetry is not None:
                    tasks.append(_telemetry)
                realtime_feedback = getattr(app.state, "realtime_feedback_task", None)
                if realtime_feedback is not None:
                    tasks.append(realtime_feedback)
                material_feedback = getattr(app.state, "material_feedback_task", None)
                if material_feedback is not None:
                    tasks.append(material_feedback)
                await asyncio.gather(*tasks, return_exceptions=True)
                await driver.disconnect()
                robot_transport.close()
                run_store.close()
                if material_store is not None:
                    material_store.close()
                if experiment_store is not None:
                    experiment_store.close()
                await three_d_authoring.close()

    return create_app(registry, script_repo=script_repo, control_mode=config.control_mode,
                      cors_origins=config.api.cors_origins, lifespan=lifespan,
                      three_d_authoring=three_d_authoring)


# ------------------------------------------------------------------
# Real 装配
# ------------------------------------------------------------------

def create_real_app(config_path: str | Path = _DEFAULT_CONFIG):
    """构建 real 模式 FastAPI 应用: 真机 Dobot + 真机 PLC, lifespan 内装配执行器与流程引擎.

    与 sim 的区别:
        - 不创建 Mock OPC UA 服务器, 不启动 Mock L2 FSM
        - OpcUaDriver 直连 config 中的真实 PLC URL (如 opc.tcp://192.168.0.50:4840)
        - 机器人使用 DobotTcpRobotTransport 直连 (非内存仿真)
    """
    config = load_config(Path(config_path))
    three_d_authoring = ThreeDAuthoringService(
        config.three_d.workspace_root,
        hardware_root=config.three_d.hardware_root,
    )
    registry = ActionRegistry.load(_actions_dir(config))
    # 可变持有盒: 动作 raw 编辑保存后由 ActionsService 更新, 使脚本校验器名集实时跟随 (重命名/增删动作不失真)
    reg_box = {"reg": registry}
    script_repo = ScriptRepo(_operation_dir(config),
                             validator=_script_validator(reg_box, _resource_specs(config)),
                             history_root=_DATA_DIR / "operation_history")

    @asynccontextmanager
    async def lifespan(app):
        maintenance_gate = MaintenanceGate(_DATA_DIR / "plc-deploy-maintenance.json")
        app.state.maintenance_gate = maintenance_gate
        node_map = load_plc_nodes(config.plc.nodes_file)
        # ── 真机 PLC 连接 (无 Mock Server / FSM) ──
        driver = OpcUaDriver(str(config.plc.url), node_map,
                             reconnect_wait_timeout=config.plc.reconnect_wait_timeout,
                             subscription_queue_size=config.plc.subscription_queue_size,
                             subscription_sampling_ms=config.plc.subscription_sampling_ms,
                             request_timeout=config.plc.request_timeout,
                             watchdog_interval=config.plc.watchdog_interval,
                             max_inflight_requests=config.plc.max_inflight_requests)
        await driver.connect()
        plc = PlcController(driver, poll_interval=0.05, action_timeout=config.plc.action_timeout,
                            stall_timeout=config.plc.action_stall_timeout,
                            soft_recheck=config.plc.action_soft_recheck)

        # ── 真机机器人连接 ──
        from eit_ptlc.driver.dobot_tcp_driver import DobotTcpRobotTransport
        from eit_ptlc.driver.robot_transport import RobotTransportError
        # 单一来源加载 (派生点已并入 meta.supplement, 不再叠加 robot_flows_v2.yaml)
        point_registry = PointRegistry.load(config.robot.points_file, source_version=config.robot.point_source_version,
                                            meta_path=config.robot.points_meta_file)

        robot_transport = DobotTcpRobotTransport(
            host=config.robot.host,
            command_port=config.robot.command_port,
            feedback_port=config.robot.feedback_port,
            error_http_port=config.robot.error_http_port,
            connect_timeout=config.robot.connect_timeout,
            command_timeout=config.robot.command_timeout,
            action_timeout=config.robot.action_timeout,
            poll_interval=config.robot.poll_interval,
            allow_enable_command=config.robot.allow_enable_command,
            allow_clear_error_command=config.robot.allow_clear_error_command,
            tool_di_feedback_enabled=config.robot.tool_di_feedback_enabled,
            tool_di_timeout=config.robot.tool_di_timeout,
            tool_confirm=DobotTcpRobotTransport.tool_confirm_from_cfg(config.robot.tool_confirm),
            speed_factor=config.robot.speed_factor,
            # 工具态持久化 (权威四态真源): 启动读盘恢复当前挂载夹爪; 路径由 RobotCfg.tool_state_file 配置
            tool_state_path=config.robot.tool_state_file,
        )
        # 机器人连不上不阻断起服: 节点显示 offline, 维护页点"重连"即可恢复. (connect 现会如实抛
        # 链路级失败; 若反复报"机器人关闭 29999 连接", 多为上次未干净退出致 dashboard 单会话未释放,
        # 等约 1 分钟 keepalive 超时或重启机器人控制器后再重连.)
        try:
            robot_transport.connect()
        except (RobotTransportError, OSError) as exc:
            log.warning("[real] 机器人启动连接失败, 后端照常起服, 机器人节点 offline, 可在维护页点'重连': %s", exc)
        robot = RobotController(robot_transport, point_registry, home_point=config.robot.home_point,
                                jog_speed_percent=config.robot.jog_speed_percent,
                                step_distance_mm=config.robot.step_distance_mm,
                                step_angle_deg=config.robot.step_angle_deg,
                                maintenance_gate=maintenance_gate)

        # ── 液位外设 (香橙派) MQTT 连接 (可选; 未启用/连不上不阻断起服) ──
        wl_client, wl_ctrl = await _build_water_level(config)
        wl_detect = _build_water_level_detect(config, wl_client, config_path)
        wl_recorder = _build_water_level_recorder(config, wl_detect)

        # ── CODESYS 程序编辑服务 (可选; 懒启动, 首个 web 请求才拉起带 UI 的 InoProShop) ──
        # sim 不装配 (sim 机器可能没装 InoProShop, 也无真机可部署); enabled=false 则端点返回 503。
        codesys_ipc = None
        if config.codesys.enabled:
            # PLC IP 取自 OPC UA url 的 host(同一台真机), 注入 worker 供 op_deploy 按 IP 单播设活动路径
            plc_ip = str(config.plc.url).split("://")[-1].split("/")[0].split(":")[0]
            codesys_ipc = CodesysIpcClient(
                exe=config.codesys.exe, profile=config.codesys.profile,
                project=config.codesys.project, ipc_dir=config.codesys.ipc_dir,
                compile_category=config.codesys.compile_category, plc_ip=plc_ip,
                idle_timeout=config.codesys.idle_timeout,
                session_idle_release=config.codesys.session_idle_release,
                session_wait_timeout=config.codesys.session_wait_timeout,
                session_max_hold=config.codesys.session_max_hold)
            # 整份 .project 全量快照仓库(内容哈希去重 + 部署台账); 历史落 var/(已 gitignore)
            plc_version_repo = PlcVersionRepo(config.codesys.project, _DATA_DIR / "plc-history")

            async def _deploy_idle_guard() -> None:
                """部署前最小全局空闲守卫；只读检查，不会中止任何现有动作。"""
                reasons: list[str] = []
                vm = getattr(app.state, "vm", None)
                if vm is not None:
                    active_runs = vm.active().get("runs", [])
                    if active_runs:
                        reasons.append("流程仍在运行: " + ", ".join(
                            str(item.get("run_id", "?")) for item in active_runs[:5]))

                if plc.has_active_actions():
                    reasons.append("上位机仍有 PLC L2 动作占用工位")
                try:
                    station_snaps = await asyncio.gather(
                        *(plc.snapshot(station) for station in _ALL_L2_STATIONS))
                    running = [station for station, snap in zip(_ALL_L2_STATIONS, station_snaps)
                               if int(snap.get("State", 0)) == 10]
                    if running:
                        reasons.append("PLC 工位仍在 RUNNING: " + ", ".join(running))
                except Exception as exc:
                    reasons.append(f"无法确认全部 PLC 工位空闲: {exc}")

                try:
                    if await plc.sampling_free_move_active():
                        reasons.append("孔板手动标定仍处于轴去使能状态")
                except Exception as exc:
                    reasons.append(f"无法确认孔板手动标定已退出: {exc}")

                # 动作锁覆盖点到点/步进等阻塞动作；锁空闲后再读 RobotMode，补捉连续点动/暂停态。
                if robot.is_busy():
                    reasons.append("机器人动作仍在执行")
                else:
                    try:
                        feedback = await asyncio.to_thread(robot.query)
                        if not feedback.connected:
                            reasons.append("机器人离线，无法确认自动回零运动区域安全")
                        elif feedback.robot_mode in (7, 8, 10):  # RUNNING / SINGLE_MOVE / PAUSE
                            reasons.append(f"机器人未空闲: RobotMode={feedback.robot_mode}")
                    except Exception as exc:
                        reasons.append(f"无法确认机器人空闲: {exc}")

                if reasons:
                    raise PLCDeployPreconditionError("；".join(reasons), stage="busy")

            app.state.plc_program = PlcProgramService(
                codesys_ipc,
                allow_deploy=config.codesys.allow_deploy,
                version_repo=plc_version_repo,
                plc=plc,
                idle_guard=_deploy_idle_guard,
                maintenance_gate=maintenance_gate,
            )
            log.info("[real] CODESYS 程序编辑服务已装配(懒启动, 首次请求拉起 InoProShop; allow_deploy=%s): %s ipc=%s",
                     config.codesys.allow_deploy, config.codesys.project, config.codesys.ipc_dir)

        stop = asyncio.Event()
        _telemetry = None
        material_store = None
        experiment_store = None
        scheduler = None
        try:
            (_, __, run_store, ___, _telemetry, material_store,
             experiment_store, scheduler) = _build_shared_state(
                app, config, registry, reg_box, plc, robot, _ALL_L2_STATIONS, script_repo, stop, config_path,
                water_level_client=wl_client, water_level_ctrl=wl_ctrl,
                water_level_detect=wl_detect, water_level_recorder=wl_recorder)
            if wl_detect is not None:
                await wl_detect.start()
            log.info("[real] 执行器+VM编排+节点遥测就绪: 真机 PLC %s @ %s  机器人 %s  液位 %s",
                     _ALL_L2_STATIONS, config.plc.url, config.robot.host,
                     "已接入" if wl_client is not None else "未启用")
            yield
        finally:
            # 仿真沙盒先收口 (real 模式同样可建沙盒: 连着真机也能推演)
            _sim_stack = getattr(app.state, "sim", None)
            if _sim_stack is not None:
                app.state.sim = None
                await _sim_stack.stop()
            # 单点会话必须先收口: 撤 Enable 并清扫全部执行器命令位, 再断链
            await _shutdown_recorder(app)
            await _shutdown_manual(app)
            if scheduler is not None:
                await scheduler.stop()
            stop.set()
            realtime_tasks = [task for task in (
                _telemetry,
                getattr(app.state, "realtime_feedback_task", None),
                getattr(app.state, "material_feedback_task", None),
            ) if task is not None]
            if realtime_tasks:
                await asyncio.gather(*realtime_tasks, return_exceptions=True)
            if wl_recorder is not None:
                wl_recorder.stop_all()   # 关停全部活跃录制 (join 有界; 落 meta/收尾)
            if wl_detect is not None:
                await wl_detect.stop()
            if wl_client is not None:
                await wl_client.disconnect()
            if codesys_ipc is not None:
                await codesys_ipc.shutdown()  # 仅释放本地句柄; 共享 worker 不强杀(他客户端可能在用), 残留由空闲超时收尾
            await driver.disconnect()
            robot_transport.close()
            run_store.close()
            if material_store is not None:
                material_store.close()
            if experiment_store is not None:
                experiment_store.close()
            await three_d_authoring.close()

    return create_app(registry, script_repo=script_repo, control_mode=config.control_mode,
                      cors_origins=config.api.cors_origins, lifespan=lifespan,
                      three_d_authoring=three_d_authoring)


# ------------------------------------------------------------------
# 模块级 app (供 uvicorn 字符串引用)
# ------------------------------------------------------------------

def _resolve_mode() -> str:
    """从环境变量 EIT_MODE 取模式, 默认 sim; 非法值降级为 sim 并警告."""
    raw = os.environ.get("EIT_MODE", "sim").strip().lower()
    if raw not in ("sim", "real"):
        log.warning("EIT_MODE=%r 无效, 降级为 sim", raw)
        return "sim"
    return raw


def _build_mode_app(mode: str):
    """按模式创建 app (sim / real)."""
    if mode == "real":
        log.info("[bootstrap] 模式: REAL — 连接真机 PLC + 真机机器人")
        return create_real_app()
    log.info("[bootstrap] 模式: SIM — 内存机器人仿真 + Mock PLC")
    return create_sim_app()


# 供 `uvicorn eit_ptlc.runtime.bootstrap:app` 直接运行
app = _build_mode_app(_resolve_mode())
