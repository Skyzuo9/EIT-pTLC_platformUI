"""Fourteen business routes and host-side orchestration plans."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Mapping

import yaml

from .robot_plan import ResolvedRobotPlan, RobotPlanCatalog, RobotPlanError


class RobotRouteError(ValueError):
    """Business route configuration or parameters are invalid."""


@dataclass(frozen=True)
class BusinessParamSpec:
    name: str
    kind: str
    minimum: int | None = None
    maximum: int | None = None
    values: tuple[str, ...] = ()

    def validate(self, value: object) -> object:
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise RobotRouteError(f"{self.name} must be an integer")
            if self.minimum is not None and value < self.minimum:
                raise RobotRouteError(f"{self.name} is below {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise RobotRouteError(f"{self.name} is above {self.maximum}")
            return value
        if self.kind == "enum":
            text = str(value)
            if text not in self.values:
                raise RobotRouteError(
                    f"{self.name} must be one of {self.values}, got {text!r}"
                )
            return text
        raise RobotRouteError(f"unsupported parameter type: {self.kind}")


@dataclass(frozen=True)
class ResourceRef:
    resource_type: str
    resource_id: object | None


@dataclass(frozen=True)
class RobotRouteStep:
    step_id: str
    plan: ResolvedRobotPlan


@dataclass(frozen=True)
class PlcActionStep:
    step_id: str
    action: str


@dataclass(frozen=True)
class PlcWaitStep:
    step_id: str
    condition: str
    timeout_s: float
    poll_interval_s: float


@dataclass(frozen=True)
class CameraActionStep:
    step_id: str
    action: str


@dataclass(frozen=True)
class RailMoveStep:
    """把地轨 (地轨轴11Y) 移到某工位的前置伺服原子动作。

    由 RoutePlanner 在每个机器人步骤进入新工位前自动注入, 不在 route YAML 手写。
    position_code 对应 PLC 侧 Rail 原子动作码 (legacy HMI_地轨轴11Y.position[1..6])。
    """

    step_id: str
    route_group: str
    position_code: int


HostRouteStep = (
    RobotRouteStep | PlcActionStep | PlcWaitStep | CameraActionStep | RailMoveStep
)


@dataclass(frozen=True)
class RouteDefinition:
    route_id: str
    description: str
    params: tuple[BusinessParamSpec, ...]
    resources: tuple[dict[str, object], ...]
    robot_lock_scope: str
    steps: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class ResolvedRoutePlan:
    route_id: str
    description: str
    business_params: tuple[tuple[str, object], ...]
    resources: tuple[ResourceRef, ...]
    robot_lock_scope: str
    steps: tuple[HostRouteStep, ...]
    config_version: str
    config_sha256: str


class RoutePlanner:
    def __init__(
        self,
        catalog: RobotPlanCatalog,
        routes: Mapping[str, RouteDefinition],
        *,
        config_version: str,
        config_sha256: str,
    ) -> None:
        self.catalog = catalog
        self._routes = dict(routes)
        self.config_version = config_version
        self.config_sha256 = config_sha256

    @classmethod
    def load(
        cls,
        path: str | Path,
        catalog: RobotPlanCatalog,
    ) -> "RoutePlanner":
        source = Path(path).resolve()
        raw_bytes = source.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        if checksum != catalog.config_sha256:
            raise RobotRouteError("route and robot-plan checksums differ")
        data = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            raise RobotRouteError("route source version must be 2")
        routes_raw = data.get("routes")
        if not isinstance(routes_raw, dict):
            raise RobotRouteError("route source requires routes")
        routes: dict[str, RouteDefinition] = {}
        for route_id, values in routes_raw.items():
            if not isinstance(values, dict):
                raise RobotRouteError(f"route {route_id} must be an object")
            params_raw = values.get("params", {})
            if not isinstance(params_raw, dict):
                raise RobotRouteError(f"route {route_id} params must be an object")
            params = tuple(
                cls._parse_param(str(name), spec)
                for name, spec in params_raw.items()
            )
            resources_raw = values.get("resources", [])
            steps_raw = values.get("steps")
            if not isinstance(resources_raw, list):
                raise RobotRouteError(f"route {route_id} resources must be an array")
            if not isinstance(steps_raw, list) or not steps_raw:
                raise RobotRouteError(f"route {route_id} steps must be a non-empty array")
            lock_scope = str(values.get("robot_lock_scope", "flow"))
            if lock_scope not in {"flow", "transaction"}:
                raise RobotRouteError(f"route {route_id} invalid robot_lock_scope")
            routes[str(route_id)] = RouteDefinition(
                route_id=str(route_id),
                description=str(values.get("description", "")),
                params=params,
                resources=tuple(resources_raw),
                robot_lock_scope=lock_scope,
                steps=tuple(steps_raw),
            )
        return cls(
            catalog,
            routes,
            config_version=str(data.get("config_version", "")),
            config_sha256=checksum,
        )

    @property
    def route_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._routes))

    def legal_parameter_sets(
        self,
        route_id: str,
    ) -> tuple[dict[str, object], ...]:
        try:
            definition = self._routes[route_id]
        except KeyError as exc:
            raise RobotRouteError(f"unknown business route: {route_id}") from exc
        names: list[str] = []
        domains: list[tuple[object, ...]] = []
        for spec in definition.params:
            names.append(spec.name)
            if spec.kind == "int":
                assert spec.minimum is not None and spec.maximum is not None
                domains.append(tuple(range(spec.minimum, spec.maximum + 1)))
            else:
                domains.append(tuple(spec.values))
        if not names:
            return ({},)
        return tuple(
            dict(zip(names, values))
            for values in product(*domains)
        )

    def resolve_all_legal(self) -> tuple[ResolvedRoutePlan, ...]:
        return tuple(
            self.resolve(route_id, params)
            for route_id in self.route_ids
            for params in self.legal_parameter_sets(route_id)
        )

    def resolve(
        self,
        route_id: str,
        business_params: Mapping[str, object],
    ) -> ResolvedRoutePlan:
        try:
            definition = self._routes[route_id]
        except KeyError as exc:
            raise RobotRouteError(f"unknown business route: {route_id}") from exc
        expected = {spec.name for spec in definition.params}
        actual = set(business_params)
        if actual != expected:
            raise RobotRouteError(
                f"route {route_id} requires {sorted(expected)}, got {sorted(actual)}"
            )
        validated = {
            spec.name: spec.validate(business_params[spec.name])
            for spec in definition.params
        }
        resources = tuple(
            self._resolve_resource(item, validated)
            for item in definition.resources
        )
        resolved_steps = [
            self._resolve_step(item, validated)
            for item in definition.steps
        ]
        steps = self._inject_rail_moves(route_id, resolved_steps)
        return ResolvedRoutePlan(
            route_id=route_id,
            description=definition.description,
            business_params=tuple(sorted(validated.items())),
            resources=resources,
            robot_lock_scope=definition.robot_lock_scope,
            steps=steps,
            config_version=self.config_version,
            config_sha256=self.config_sha256,
        )

    def _inject_rail_moves(
        self,
        route_id: str,
        steps: list[HostRouteStep],
    ) -> tuple[HostRouteStep, ...]:
        """在每个进入新工位的机器人步骤前注入"地轨到站"原子动作。

        功能:
            机器人坐在地轨上, 各工位点是在地轨停在该工位时示教的。本方法按
            route_group -> 位置码 (catalog.rail_stations) 推导每个机器人步骤所需的
            地轨位置, 与"当前地轨位置"不同时插入一个 RailMoveStep; 同工位连续
            (含 enter/exit 对) 自然不重复。

        参数:
            route_id: 业务路线 id, 仅用于错误信息
            steps: 已解析的 route 步骤序列 (未注入地轨)

        返回:
            tuple[HostRouteStep, ...], 注入地轨步骤后的完整序列

        安全:
            仅当机械臂收回 (上一机器人步骤 exit_role == home) 时才允许移动地轨;
            否则 (地轨需移动但臂未回 home) 判定为非法 route, 直接报错。
        """
        result: list[HostRouteStep] = []
        current_code: int | None = None
        prev_robot_exit_role: str | None = None
        for step in steps:
            if isinstance(step, RobotRouteStep):
                route_group = step.plan.route_group
                try:
                    target_code = self.catalog.rail_stations[route_group]
                except KeyError as exc:
                    raise RobotRouteError(
                        f"route {route_id} step {step.step_id}: "
                        f"route group {route_group} has no rail position"
                    ) from exc
                if target_code != current_code:
                    # 地轨需移动: 必须保证机械臂已收回 (上一机器人步骤回 home)
                    if (
                        prev_robot_exit_role is not None
                        and prev_robot_exit_role != "home"
                    ):
                        raise RobotRouteError(
                            f"route {route_id} step {step.step_id}: rail must move "
                            f"but previous robot flow did not return home "
                            f"(exit_role={prev_robot_exit_role})"
                        )
                    result.append(
                        RailMoveStep(
                            step_id=f"rail--{step.step_id}",
                            route_group=route_group,
                            position_code=target_code,
                        )
                    )
                    current_code = target_code
                result.append(step)
                prev_robot_exit_role = step.plan.exit_role
            else:
                result.append(step)
        return tuple(result)

    @staticmethod
    def _parse_param(name: str, raw: object) -> BusinessParamSpec:
        if not isinstance(raw, dict):
            raise RobotRouteError(f"parameter {name} must be an object")
        kind = str(raw.get("type", ""))
        if kind == "int":
            return BusinessParamSpec(
                name=name,
                kind=kind,
                minimum=int(raw["min"]),
                maximum=int(raw["max"]),
            )
        if kind == "enum":
            values = tuple(str(v) for v in raw.get("values", ()))
            if not values:
                raise RobotRouteError(f"enum parameter {name} has no values")
            return BusinessParamSpec(name=name, kind=kind, values=values)
        raise RobotRouteError(f"parameter {name} has invalid type {kind}")

    @staticmethod
    def _binding(raw: object, params: Mapping[str, object]) -> object:
        if not isinstance(raw, dict):
            raise RobotRouteError("step binding must be an object")
        if set(raw) == {"value"}:
            return raw["value"]
        if set(raw) == {"param"}:
            try:
                return params[str(raw["param"])]
            except KeyError as exc:
                raise RobotRouteError(f"unknown parameter binding: {raw}") from exc
        raise RobotRouteError(f"binding must contain exactly value or param: {raw}")

    @classmethod
    def _resolve_resource(
        cls,
        raw: object,
        params: Mapping[str, object],
    ) -> ResourceRef:
        if not isinstance(raw, dict) or "type" not in raw:
            raise RobotRouteError("resource must contain type")
        resource_id = None
        if "id" in raw:
            resource_id = cls._binding(raw["id"], params)
        return ResourceRef(str(raw["type"]), resource_id)

    def _resolve_step(
        self,
        raw: object,
        params: Mapping[str, object],
    ) -> HostRouteStep:
        if not isinstance(raw, dict):
            raise RobotRouteError("route step must be an object")
        step_id = str(raw.get("id", "")).strip()
        step_type = str(raw.get("type", "")).strip()
        if not step_id:
            raise RobotRouteError("route step id cannot be empty")
        if step_type == "robot_flow":
            bindings = raw.get("params", {})
            if not isinstance(bindings, dict):
                raise RobotRouteError(f"{step_id} robot params must be an object")
            robot_params = {
                str(name): self._binding(binding, params)
                for name, binding in bindings.items()
            }
            return RobotRouteStep(
                step_id,
                self.catalog.resolve(str(raw["template"]), robot_params),
            )
        if step_type == "plc_action":
            return PlcActionStep(step_id, str(raw["action"]))
        if step_type == "plc_wait":
            timeout_s = float(raw.get("timeout_s", 0))
            poll_interval_s = float(raw.get("poll_interval_s", 0))
            if timeout_s <= 0 or poll_interval_s <= 0:
                raise RobotRouteError(f"{step_id} requires positive timeout and poll interval")
            return PlcWaitStep(
                step_id,
                str(raw["condition"]),
                timeout_s,
                poll_interval_s,
            )
        if step_type == "camera_action":
            return CameraActionStep(step_id, str(raw["action"]))
        if step_type == "wait":
            raise RobotRouteError(
                f"{step_id}: fixed wait is forbidden in host orchestration"
            )
        raise RobotRouteError(f"{step_id}: unknown route step type {step_type}")
