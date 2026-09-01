"""Robot templates, immutable PointSets and offline plan resolution.

This module resolves restricted business parameters into concrete plans.
It does not access Modbus registers or execute PLC/camera actions.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

import yaml

from .point_registry import PointRegistry
from .robot_flow import MoveStep, RobotFlow, ToolStep, WaitStep
from .robot_transport import MotionProfile, TOOL_ACTION_NAMES, ToolAction


class RobotPlanError(ValueError):
    """Robot plan configuration or business parameters are invalid."""


@dataclass(frozen=True)
class TemplateMoveStep:
    step_id: str
    role: str
    motion: str
    profile: MotionProfile


@dataclass(frozen=True)
class TemplateToolStep:
    step_id: str
    action: ToolAction
    timeout_ms: int


@dataclass(frozen=True)
class TemplateWaitStep:
    step_id: str
    duration_ms: int


@dataclass(frozen=True)
class TemplateExtensionStep:
    step_id: str
    extension: str


TemplateStep = (
    TemplateMoveStep | TemplateToolStep | TemplateWaitStep | TemplateExtensionStep
)


@dataclass(frozen=True)
class PointSet:
    point_set_id: str
    route_group: str
    points: Mapping[str, str]
    extensions: Mapping[str, tuple[TemplateStep, ...]]

    def point_for(self, role: str) -> str:
        try:
            return self.points[role]
        except KeyError as exc:
            raise RobotPlanError(
                f"PointSet {self.point_set_id} is missing role {role}"
            ) from exc


@dataclass(frozen=True)
class RobotFlowTemplate:
    template_id: str
    description: str
    selector: str
    selector_param: str
    secondary_param: str | None
    allowed_route_groups: tuple[str, ...]
    entry_role: str
    exit_role: str
    steps: tuple[TemplateStep, ...]
    anchor_joint_tolerance_deg: float
    anchor_position_tolerance_mm: float
    anchor_rotation_tolerance_deg: float
    is_test: bool = False


@dataclass(frozen=True)
class ResolvedRobotPlan:
    template_id: str
    point_set_id: str
    route_group: str
    business_params: tuple[tuple[str, object], ...]
    resolved_points: tuple[tuple[str, str], ...]
    config_version: str
    config_sha256: str
    flow: RobotFlow
    exit_role: str = "home"


class StationRegistry:
    """Immutable, explicit business-id to PointSet mapping."""

    def __init__(
        self,
        point_sets: Mapping[str, PointSet],
        selectors: Mapping[str, object],
    ) -> None:
        self._point_sets = MappingProxyType(dict(point_sets))
        self._selectors = MappingProxyType(dict(selectors))

    @property
    def point_set_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._point_sets))

    def get(self, point_set_id: str) -> PointSet:
        try:
            return self._point_sets[point_set_id]
        except KeyError as exc:
            raise RobotPlanError(f"unknown PointSet: {point_set_id}") from exc

    def resolve(
        self,
        selector: str,
        value: object,
        secondary: object | None = None,
    ) -> PointSet:
        try:
            mapping = self._selectors[selector]
        except KeyError as exc:
            raise RobotPlanError(f"unknown station selector: {selector}") from exc
        if not isinstance(mapping, dict):
            raise RobotPlanError(f"station selector {selector} is not a mapping")
        first = mapping.get(str(value))
        if secondary is not None:
            if not isinstance(first, dict):
                raise RobotPlanError(
                    f"{selector} does not accept {value!r}/{secondary!r}"
                )
            point_set_id = first.get(str(secondary))
        else:
            point_set_id = first
        if not isinstance(point_set_id, str):
            suffix = f", secondary={secondary!r}" if secondary is not None else ""
            raise RobotPlanError(
                f"invalid business id: {selector}={value!r}{suffix}"
            )
        return self.get(point_set_id)


class RobotPlanCatalog:
    """Schema-v2 robot plan catalog."""

    def __init__(
        self,
        *,
        registry: PointRegistry,
        stations: StationRegistry,
        templates: Mapping[str, RobotFlowTemplate],
        test_templates: Mapping[str, RobotFlowTemplate],
        config_version: str,
        config_sha256: str,
        rail_stations: Mapping[str, int],
    ) -> None:
        self.registry = registry
        self.stations = stations
        self._templates = dict(templates)
        self._test_templates = dict(test_templates)
        self.config_version = config_version
        self.config_sha256 = config_sha256
        # route_group -> 地轨绝对位置码; 供 RoutePlanner 注入"地轨到站"前置步骤
        self.rail_stations = dict(rail_stations)

    @classmethod
    def load(
        cls,
        path: str | Path,
        registry: PointRegistry,
    ) -> "RobotPlanCatalog":
        source = Path(path).resolve()
        raw_bytes = source.read_bytes()
        data = yaml.safe_load(raw_bytes.decode("utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            raise RobotPlanError("robot flow source version must be 2")
        config_version = str(data.get("config_version", "")).strip()
        if not config_version:
            raise RobotPlanError("robot flow source requires config_version")
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        derived = data.get("derived_points", [])
        if not isinstance(derived, list):
            raise RobotPlanError("derived_points must be an array")
        if derived:
            registry = registry.with_derived_points(
                derived,
                source_path=source,
                source_version=config_version,
            )

        profiles = cls._load_profiles(data.get("motion_profiles"))
        point_sets = cls._load_point_sets(data.get("point_sets"), profiles)
        selectors = data.get("selectors")
        if not isinstance(selectors, dict):
            raise RobotPlanError("selectors must be an object")
        stations = StationRegistry(point_sets, selectors)
        templates = cls._load_templates(
            data.get("templates"), profiles, is_test=False
        )
        test_templates = cls._load_templates(
            data.get("test_templates", {}), profiles, is_test=True
        )
        rail_stations = cls._load_rail_stations(data.get("rail_stations"))
        catalog = cls(
            registry=registry,
            stations=stations,
            templates=templates,
            test_templates=test_templates,
            config_version=config_version,
            config_sha256=checksum,
            rail_stations=rail_stations,
        )
        catalog.preflight()
        return catalog

    @property
    def template_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._templates))

    @property
    def test_template_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._test_templates))

    def resolve(
        self,
        template_id: str,
        business_params: Mapping[str, object],
        *,
        allow_test: bool = False,
    ) -> ResolvedRobotPlan:
        template = self._get_template(template_id, allow_test=allow_test)
        expected = {template.selector_param}
        if template.secondary_param is not None:
            expected.add(template.secondary_param)
        actual = set(business_params)
        if actual != expected:
            raise RobotPlanError(
                f"template {template_id} requires {sorted(expected)}, got {sorted(actual)}"
            )
        primary = business_params[template.selector_param]
        secondary = (
            business_params[template.secondary_param]
            if template.secondary_param is not None
            else None
        )
        point_set = self.stations.resolve(template.selector, primary, secondary)
        if point_set.route_group not in template.allowed_route_groups:
            raise RobotPlanError(
                f"template {template_id} rejects route group {point_set.route_group}"
            )

        concrete = self._resolve_steps(template, point_set)
        entry_point = point_set.point_for(template.entry_role)
        exit_point = point_set.point_for(template.exit_role)
        for anchor_name in (entry_point, exit_point):
            anchor = self.registry.get(anchor_name)
            if anchor.status != "validated":
                raise PermissionError(
                    f"flow anchor {anchor.point_id} is not validated"
                )
        flow = RobotFlow(
            flow_id=template.template_id,
            description=template.description,
            entry_point=entry_point,
            exit_point=exit_point,
            steps=concrete,
            anchor_joint_tolerance_deg=template.anchor_joint_tolerance_deg,
            anchor_position_tolerance_mm=template.anchor_position_tolerance_mm,
            anchor_rotation_tolerance_deg=template.anchor_rotation_tolerance_deg,
        )
        return ResolvedRobotPlan(
            template_id=template.template_id,
            point_set_id=point_set.point_set_id,
            route_group=point_set.route_group,
            business_params=tuple(sorted(business_params.items())),
            resolved_points=tuple(sorted(point_set.points.items())),
            config_version=self.config_version,
            config_sha256=self.config_sha256,
            flow=flow,
            exit_role=template.exit_role,
        )

    def preflight(self) -> None:
        for template in (*self._templates.values(), *self._test_templates.values()):
            mapping = self.stations._selectors.get(template.selector)
            if not isinstance(mapping, dict):
                raise RobotPlanError(f"template {template.template_id} has no selector")
            for primary, target in mapping.items():
                if isinstance(target, dict):
                    for secondary in target:
                        params: dict[str, object] = {
                            template.selector_param: primary,
                        }
                        if template.secondary_param is None:
                            raise RobotPlanError(
                                f"template {template.template_id} lacks secondary_param"
                            )
                        params[template.secondary_param] = secondary
                        self.resolve(
                            template.template_id,
                            params,
                            allow_test=template.is_test,
                        )
                else:
                    self.resolve(
                        template.template_id,
                        {template.selector_param: primary},
                        allow_test=template.is_test,
                    )

    def _get_template(
        self, template_id: str, *, allow_test: bool
    ) -> RobotFlowTemplate:
        template = self._templates.get(template_id)
        if template is not None:
            return template
        if allow_test:
            test_template = self._test_templates.get(template_id)
            if test_template is not None:
                return test_template
        raise RobotPlanError(f"unknown production template: {template_id}")

    def _resolve_steps(
        self,
        template: RobotFlowTemplate,
        point_set: PointSet,
    ) -> tuple[MoveStep | ToolStep | WaitStep, ...]:
        result: list[MoveStep | ToolStep | WaitStep] = []
        seen: set[str] = set()

        def append_steps(steps: Iterable[TemplateStep]) -> None:
            for step in steps:
                if isinstance(step, TemplateExtensionStep):
                    append_steps(point_set.extensions.get(step.extension, ()))
                    continue
                if step.step_id in seen:
                    raise RobotPlanError(
                        f"duplicate resolved step id: {template.template_id}/{step.step_id}"
                    )
                seen.add(step.step_id)
                if isinstance(step, TemplateMoveStep):
                    point_id = point_set.point_for(step.role)
                    self.registry.require_motion(point_id, step.motion)
                    result.append(
                        MoveStep(step.step_id, point_id, step.motion, step.profile)
                    )
                elif isinstance(step, TemplateToolStep):
                    result.append(
                        ToolStep(step.step_id, step.action, step.timeout_ms)
                    )
                else:
                    result.append(WaitStep(step.step_id, step.duration_ms))

        append_steps(template.steps)
        if not result:
            raise RobotPlanError(f"template {template.template_id} resolved empty")
        return tuple(result)

    @staticmethod
    def _load_rail_stations(raw: object) -> dict[str, int]:
        """解析 route_group -> 地轨绝对位置码映射。

        参数:
            raw: YAML rail_stations 节点, 可缺省 (None)

        返回:
            dict[str, int], route_group 名到位置码; 缺省时为空表
        """
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise RobotPlanError("rail_stations must be an object")
        result: dict[str, int] = {}
        for name, code in raw.items():
            # 布尔是 int 子类, 显式排除避免 True/False 被当作位置码
            if isinstance(code, bool) or not isinstance(code, int):
                raise RobotPlanError(f"rail_stations[{name}] must be an integer")
            result[str(name)] = code
        return result

    @staticmethod
    def _load_profiles(raw: object) -> dict[str, MotionProfile]:
        if not isinstance(raw, dict):
            raise RobotPlanError("motion_profiles must be an object")
        result: dict[str, MotionProfile] = {}
        for name, values in raw.items():
            if not isinstance(values, dict):
                raise RobotPlanError(f"motion profile {name} must be an object")
            result[str(name)] = MotionProfile(
                acc=int(values["acc"]),
                vel=int(values["vel"]),
                cp=int(values.get("cp", 0)),
            )
        return result

    @classmethod
    def _load_point_sets(
        cls,
        raw: object,
        profiles: Mapping[str, MotionProfile],
    ) -> dict[str, PointSet]:
        if not isinstance(raw, dict):
            raise RobotPlanError("point_sets must be an object")
        result: dict[str, PointSet] = {}
        for point_set_id, values in raw.items():
            if not isinstance(values, dict):
                raise RobotPlanError(f"PointSet {point_set_id} must be an object")
            points = values.get("points")
            if not isinstance(points, dict) or not points:
                raise RobotPlanError(f"PointSet {point_set_id} requires points")
            extensions_raw = values.get("extensions", {})
            if not isinstance(extensions_raw, dict):
                raise RobotPlanError(f"PointSet {point_set_id} extensions invalid")
            extensions = {
                str(name): cls._load_steps(
                    steps, profiles, owner=f"PointSet {point_set_id}/{name}"
                )
                for name, steps in extensions_raw.items()
            }
            result[str(point_set_id)] = PointSet(
                point_set_id=str(point_set_id),
                route_group=str(values["route_group"]),
                points=MappingProxyType(
                    {str(role): str(point) for role, point in points.items()}
                ),
                extensions=MappingProxyType(extensions),
            )
        return result

    @classmethod
    def _load_templates(
        cls,
        raw: object,
        profiles: Mapping[str, MotionProfile],
        *,
        is_test: bool,
    ) -> dict[str, RobotFlowTemplate]:
        if not isinstance(raw, dict):
            raise RobotPlanError("templates must be an object")
        result: dict[str, RobotFlowTemplate] = {}
        for template_id, values in raw.items():
            if not isinstance(values, dict):
                raise RobotPlanError(f"template {template_id} must be an object")
            tolerance = values.get("anchor_tolerance", {})
            if not isinstance(tolerance, dict):
                raise RobotPlanError(f"template {template_id} anchor_tolerance invalid")
            route_groups = tuple(str(v) for v in values.get("route_groups", ()))
            if not route_groups:
                raise RobotPlanError(f"template {template_id} requires route_groups")
            result[str(template_id)] = RobotFlowTemplate(
                template_id=str(template_id),
                description=str(values.get("description", "")),
                selector=str(values["selector"]),
                selector_param=str(values["selector_param"]),
                secondary_param=(
                    str(values["secondary_param"])
                    if values.get("secondary_param") is not None
                    else None
                ),
                allowed_route_groups=route_groups,
                entry_role=str(values.get("entry_role", "home")),
                exit_role=str(values.get("exit_role", "home")),
                steps=cls._load_steps(
                    values.get("steps"), profiles, owner=f"template {template_id}"
                ),
                anchor_joint_tolerance_deg=float(tolerance.get("joint_deg", 2.0)),
                anchor_position_tolerance_mm=float(tolerance.get("position_mm", 5.0)),
                anchor_rotation_tolerance_deg=float(tolerance.get("rotation_deg", 5.0)),
                is_test=is_test,
            )
        return result

    @staticmethod
    def _load_steps(
        raw: object,
        profiles: Mapping[str, MotionProfile],
        *,
        owner: str,
    ) -> tuple[TemplateStep, ...]:
        if not isinstance(raw, list):
            raise RobotPlanError(f"{owner} steps must be an array")
        result: list[TemplateStep] = []
        for item in raw:
            if not isinstance(item, dict):
                raise RobotPlanError(f"{owner} contains invalid step")
            step_id = str(item.get("id", "")).strip()
            step_type = str(item.get("type", "")).strip()
            if not step_id:
                raise RobotPlanError(f"{owner} contains empty step id")
            if step_type == "move":
                motion = str(item.get("motion", ""))
                if motion not in {"move_j", "move_l"}:
                    raise RobotPlanError(f"{owner}/{step_id} invalid motion")
                try:
                    profile = profiles[str(item["profile"])]
                except KeyError as exc:
                    raise RobotPlanError(f"{owner}/{step_id} unknown profile") from exc
                result.append(
                    TemplateMoveStep(step_id, str(item["role"]), motion, profile)
                )
            elif step_type == "tool_action":
                try:
                    action = TOOL_ACTION_NAMES[str(item["action"])]
                except KeyError as exc:
                    raise RobotPlanError(f"{owner}/{step_id} unknown tool action") from exc
                timeout_ms = int(item.get("timeout_ms", 3000))
                if not 100 <= timeout_ms <= 60000:
                    raise RobotPlanError(f"{owner}/{step_id} timeout out of range")
                result.append(TemplateToolStep(step_id, action, timeout_ms))
            elif step_type == "wait":
                duration_ms = int(item.get("duration_ms", 0))
                if not 1 <= duration_ms <= 60000:
                    raise RobotPlanError(f"{owner}/{step_id} wait out of range")
                result.append(TemplateWaitStep(step_id, duration_ms))
            elif step_type == "extension":
                result.append(TemplateExtensionStep(step_id, str(item["extension"])))
            else:
                raise RobotPlanError(
                    f"{owner}/{step_id} invalid type {step_type}; "
                    "PLC and camera actions are forbidden inside robot templates"
                )
        return tuple(result)
