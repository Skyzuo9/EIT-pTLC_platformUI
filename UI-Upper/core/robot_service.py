"""机器人动作服务：把点位许可与底层 transport 隔离。"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from functools import wraps
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from .dobot_tcp_transport import DobotTcpRobotTransport
from .point_registry import PointRegistry, RobotPoint
from .robot_flow import RobotFlowService
from .robot_host_adapter import HostActionCatalog
from .robot_plan import RobotPlanCatalog
from .robot_route import RoutePlanner
from .robot_transport import (
    ModbusRobotTransport,
    MotionOptions,
    MotionProfile,
    RobotFeedback,
    RobotTransport,
    ToolAction,
)


def _serialized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._action_lock:
            return method(self, *args, **kwargs)

    return wrapper


@dataclass(frozen=True)
class RobotRuntime:
    transport: RobotTransport
    service: "RobotActionService"
    registry: PointRegistry
    flow_service: RobotFlowService
    plan_catalog: RobotPlanCatalog
    route_planner: RoutePlanner
    host_action_catalog: HostActionCatalog


class RobotActionService:
    """唯一对业务层开放的点位运动入口。"""

    def __init__(
        self,
        transport: RobotTransport,
        registry: PointRegistry,
        *,
        home_point: str,
    ) -> None:
        self.transport = transport
        self.registry = registry
        self.home_point = home_point
        # The transport lock covers one command; this reentrant lease lets a
        # flow own the robot across its entire audited route.
        self._action_lock = threading.RLock()

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self._action_lock:
            yield

    def query(self) -> RobotFeedback:
        with self._action_lock:
            return self.transport.query()

    @_serialized
    def home(self) -> RobotFeedback:
        point = self.registry.require_motion(self.home_point, "move_j")
        if point.role != "home":
            raise PermissionError(f"配置的 home 点角色不是 home: {point.point_id}")
        options = MotionOptions(
            user=point.user,
            tool=point.tool,
            acc=point.acc,
            vel=point.vel,
            cp=point.cp,
        )
        # TCP 无内建 P1，使用已标定的 home 点位姿+关节角走 move_j；
        # Modbus 通过 FID=26 使用机器人控制器内建 P1 变量。
        if isinstance(self.transport, DobotTcpRobotTransport):
            return self.transport.move_j(point.pose, options, joint=point.joint)
        return self.transport.home(options)

    @_serialized
    def move_j(self, point_id_or_robot_name: str) -> RobotFeedback:
        return self._move_point(
            self.registry.require_motion(point_id_or_robot_name, "move_j"),
            "move_j",
        )

    @_serialized
    def move_l(self, point_id_or_robot_name: str) -> RobotFeedback:
        return self._move_point(
            self.registry.require_motion(point_id_or_robot_name, "move_l"),
            "move_l",
        )

    @_serialized
    def move_to_point(
        self,
        point_id_or_robot_name: str,
        motion: str | None = None,
        *,
        profile: MotionProfile | None = None,
    ) -> RobotFeedback:
        point = self.registry.get(point_id_or_robot_name)
        if motion is None:
            if len(point.allowed_motion) != 1:
                raise PermissionError(
                    f"点 {point.point_id} 允许动作不是唯一值，必须显式指定 move_j/move_l"
                )
            motion = point.allowed_motion[0]
        if motion not in {"move_j", "move_l"}:
            raise ValueError(f"不支持的运动类型: {motion}")
        return self._move_point(
            self.registry.require_motion(point_id_or_robot_name, motion),
            motion,
            profile=profile,
        )

    @_serialized
    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        return self.transport.tool_action(action, timeout_ms)

    def _move_point(
        self, point: RobotPoint, motion: str, *, profile: MotionProfile | None = None
    ) -> RobotFeedback:
        options = MotionOptions(
            user=point.user,
            tool=point.tool,
            acc=point.acc if profile is None else profile.acc,
            vel=point.vel if profile is None else profile.vel,
            cp=point.cp if profile is None else profile.cp,
        )
        if motion == "move_j":
            return self.transport.move_j(point.pose, options, joint=point.joint)
        return self.transport.move_l(point.pose, options)


def build_robot_runtime(config: object, *, base_dir: str | Path = ".") -> RobotRuntime:
    """由 ``AppConfig.robot`` 构建 transport；默认仍为 Modbus。"""
    base = Path(base_dir).resolve()
    source_path = _resolve(base, getattr(config, "point_source"))
    flow_path = _resolve(base, getattr(config, "flow_source"))
    host_action_path = _resolve(base, getattr(config, "host_action_source"))

    meta_path = _resolve(base, getattr(config, "point_meta"))
    registry = PointRegistry.load(
        source_path,
        source_version=getattr(config, "point_source_version"),
        meta_path=meta_path,
    )
    plan_catalog = RobotPlanCatalog.load(flow_path, registry)
    registry = plan_catalog.registry
    route_planner = RoutePlanner.load(flow_path, plan_catalog)
    host_action_catalog = HostActionCatalog.load(host_action_path)
    host_action_catalog.validate_routes(route_planner)
    transport_name = getattr(config, "transport")
    if transport_name == "modbus":
        transport: RobotTransport = ModbusRobotTransport(
            getattr(config, "host"),
            port=getattr(config, "modbus_port"),
            unit_id=getattr(config, "modbus_unit_id"),
            timeout=getattr(config, "action_timeout"),
            socket_timeout=getattr(config, "command_timeout"),
            ack_timeout=getattr(config, "ack_timeout", 10.0),
            byte_order=getattr(config, "modbus_byte_order"),
        )
    elif transport_name == "dobot_tcp":
        transport = DobotTcpRobotTransport(
            getattr(config, "host"),
            command_port=getattr(config, "command_port"),
            feedback_port=getattr(config, "feedback_port"),
            error_http_port=getattr(config, "error_http_port"),
            connect_timeout=getattr(config, "connect_timeout"),
            command_timeout=getattr(config, "command_timeout"),
            action_timeout=getattr(config, "action_timeout"),
            poll_interval=getattr(config, "poll_interval"),
            allow_enable_command=getattr(config, "allow_enable_command"),
            allow_clear_error_command=getattr(config, "allow_clear_error_command"),
            tool_di_feedback_enabled=getattr(config, "tool_di_feedback_enabled"),
        )
    else:
        raise ValueError(f"未知 robot.transport: {transport_name}")
    service = RobotActionService(
        transport,
        registry,
        home_point=getattr(config, "home_point"),
    )
    flow_service = RobotFlowService(service, registry)
    return RobotRuntime(
        transport=transport,
        service=service,
        registry=registry,
        flow_service=flow_service,
        plan_catalog=plan_catalog,
        route_planner=route_planner,
        host_action_catalog=host_action_catalog,
    )


def _resolve(base: Path, value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()
