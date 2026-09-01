"""机器人路线运行时装配
======================
功能:
    把点表 / 计划目录 / 路线规划 / 主机动作目录 / Dobot 直连传输 / 机器人控制器 / 流程服务
    装配为 RobotRuntime, 供 execute_route 执行短时机器人业务路线 (取放转运).
    迁移自 UI-Upper/core/robot_service.py 的 RobotRuntime + build_robot_runtime,
    适配: 仅 Dobot 直连 (Modbus 历史), service 用 RobotController.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eit_ptlc.config.models import RobotCfg
from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.driver.dobot_tcp_driver import DobotTcpRobotTransport
from eit_ptlc.driver.robot_transport import RobotTransport

from .robot_flow import RobotFlowService
from .robot_host_adapter import HostActionCatalog
from .robot_plan import RobotPlanCatalog
from .robot_route import RoutePlanner


@dataclass(frozen=True)
class RobotRuntime:
    """机器人路线运行时容器 (装配产物)."""
    transport: RobotTransport
    service: RobotController
    registry: PointRegistry
    flow_service: RobotFlowService
    plan_catalog: RobotPlanCatalog
    route_planner: RoutePlanner
    host_action_catalog: HostActionCatalog


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def build_robot_runtime(
    robot_cfg: RobotCfg,
    *,
    base_dir: str | Path = ".",
    flow_source: str | Path | None = None,
    host_action_source: str | Path | None = None,
) -> RobotRuntime:
    """由 RobotCfg 装配机器人路线运行时 (Dobot 直连).

    参数:
        robot_cfg: 机器人配置 (端口/点表/安全门控);
        base_dir: 解析相对路径基准;
        flow_source: 路线/模板/点集 yaml (默认 config/backup/robot_flows_v2.yaml; 已归档, 仅离线规划用);
        host_action_source: 主机动作绑定 json (默认 config/robot_host_actions.json)
    返回:
        RobotRuntime
    """
    if robot_cfg.transport != "dobot_tcp":
        raise ValueError(f"机器人路线仅支持 dobot_tcp 直连, 配置为: {robot_cfg.transport}")
    base = Path(base_dir).resolve()
    points = _resolve(base, robot_cfg.points_file)
    meta = _resolve(base, robot_cfg.points_meta_file)
    cfg_dir = base  # config 目录 (相对 points_file 的解析基准; 点表已迁入 points/robot/, 故不再用 points.parent)
    flow = _resolve(base, flow_source) if flow_source else cfg_dir / "backup" / "robot_flows_v2.yaml"
    hosts = _resolve(base, host_action_source) if host_action_source else cfg_dir / "robot_host_actions.json"

    registry = PointRegistry.load(points, source_version=robot_cfg.point_source_version, meta_path=meta)
    plan_catalog = RobotPlanCatalog.load(flow, registry)
    registry = plan_catalog.registry          # 计划目录可能补充派生点
    route_planner = RoutePlanner.load(flow, plan_catalog)
    host_action_catalog = HostActionCatalog.load(hosts)
    host_action_catalog.validate_routes(route_planner)

    transport = DobotTcpRobotTransport(
        robot_cfg.host,
        command_port=robot_cfg.command_port,
        feedback_port=robot_cfg.feedback_port,
        error_http_port=robot_cfg.error_http_port,
        connect_timeout=robot_cfg.connect_timeout,
        command_timeout=robot_cfg.command_timeout,
        action_timeout=robot_cfg.action_timeout,
        poll_interval=robot_cfg.poll_interval,
        allow_enable_command=robot_cfg.allow_enable_command,
        allow_clear_error_command=robot_cfg.allow_clear_error_command,
        tool_di_feedback_enabled=robot_cfg.tool_di_feedback_enabled,
        tool_di_timeout=robot_cfg.tool_di_timeout,
        tool_confirm=DobotTcpRobotTransport.tool_confirm_from_cfg(robot_cfg.tool_confirm),
    )
    service = RobotController(
        transport, registry, home_point=robot_cfg.home_point,
        jog_speed_percent=robot_cfg.jog_speed_percent,
        step_distance_mm=robot_cfg.step_distance_mm,
        step_angle_deg=robot_cfg.step_angle_deg,
    )
    flow_service = RobotFlowService(service, registry)
    return RobotRuntime(
        transport=transport, service=service, registry=registry, flow_service=flow_service,
        plan_catalog=plan_catalog, route_planner=route_planner, host_action_catalog=host_action_catalog,
    )
