"""Thread-safe bridge from route semantics to real PLC and camera services."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from asyncua import ua

from .robot_route import CameraActionStep, PlcActionStep, PlcWaitStep, RoutePlanner

if TYPE_CHECKING:
    from eit_ptlc.driver.camera_driver import CameraService
    from eit_ptlc.controller.plc_controller import PlcController as PLCClient


class HostActionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PlcActionBinding:
    variable: str
    variant: str
    value: object | None
    value_param: str | None
    kind: str = "write"
    station: str | None = None
    action: str | None = None


@dataclass(frozen=True)
class PlcConditionBinding:
    variable: str
    equals: object


@dataclass(frozen=True)
class CameraActionBinding:
    filename: str


class HostActionCatalog:
    def __init__(
        self,
        *,
        plc_actions: Mapping[str, PlcActionBinding],
        plc_conditions: Mapping[str, PlcConditionBinding],
        camera_actions: Mapping[str, CameraActionBinding],
        source_sha256: str,
    ) -> None:
        self.plc_actions = dict(plc_actions)
        self.plc_conditions = dict(plc_conditions)
        self.camera_actions = dict(camera_actions)
        self.source_sha256 = source_sha256

    @classmethod
    def load(cls, path: str | Path) -> "HostActionCatalog":
        source = Path(path).resolve()
        raw = source.read_bytes()
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise HostActionConfigError("robot host action config version must be 1")
        actions_raw = data.get("plc_actions")
        conditions_raw = data.get("plc_conditions")
        cameras_raw = data.get("camera_actions")
        if not all(isinstance(item, dict) for item in (
            actions_raw, conditions_raw, cameras_raw
        )):
            raise HostActionConfigError("host action mappings must be objects")
        actions: dict[str, PlcActionBinding] = {}
        for name, values in actions_raw.items():
            if not isinstance(values, dict):
                raise HostActionConfigError(f"invalid PLC action binding: {name}")
            if values.get("type") == "l2_action":
                if not values.get("station") or not values.get("action"):
                    raise HostActionConfigError(
                        f"PLC L2 action {name} requires station and action"
                    )
                actions[str(name)] = PlcActionBinding(
                    variable="",
                    variant="",
                    value=None,
                    value_param=None,
                    kind="l2_action",
                    station=str(values["station"]),
                    action=str(values["action"]),
                )
                continue
            has_value = "value" in values
            has_param = "value_param" in values
            if has_value == has_param:
                raise HostActionConfigError(
                    f"PLC action {name} requires exactly value or value_param"
                )
            variant = str(values.get("variant", ""))
            if variant not in {"boolean", "int16"}:
                raise HostActionConfigError(
                    f"PLC action {name} has invalid variant {variant}"
                )
            actions[str(name)] = PlcActionBinding(
                variable=str(values["variable"]),
                variant=variant,
                value=values.get("value"),
                value_param=(
                    str(values["value_param"]) if has_param else None
                ),
            )
        conditions = {
            str(name): PlcConditionBinding(
                variable=str(values["variable"]),
                equals=values["equals"],
            )
            for name, values in conditions_raw.items()
            if isinstance(values, dict)
        }
        cameras = {
            str(name): CameraActionBinding(filename=str(values["filename"]))
            for name, values in cameras_raw.items()
            if isinstance(values, dict)
        }
        catalog = cls(
            plc_actions=actions,
            plc_conditions=conditions,
            camera_actions=cameras,
            source_sha256=hashlib.sha256(raw).hexdigest(),
        )
        return catalog

    def validate_routes(self, planner: RoutePlanner) -> None:
        required_actions: set[str] = set()
        required_conditions: set[str] = set()
        required_cameras: set[str] = set()
        for plan in planner.resolve_all_legal():
            for step in plan.steps:
                if isinstance(step, PlcActionStep):
                    required_actions.add(step.action)
                elif isinstance(step, PlcWaitStep):
                    required_conditions.add(step.condition)
                elif isinstance(step, CameraActionStep):
                    required_cameras.add(step.action)
        missing = {
            "plc_actions": sorted(required_actions - self.plc_actions.keys()),
            "plc_conditions": sorted(
                required_conditions - self.plc_conditions.keys()
            ),
            "camera_actions": sorted(required_cameras - self.camera_actions.keys()),
        }
        missing = {key: values for key, values in missing.items() if values}
        if missing:
            raise HostActionConfigError(f"missing host action mappings: {missing}")


class ThreadsafePlcCameraHost:
    """Synchronous RouteExecutor port backed by an asyncio application loop.

    Run RouteExecutor.execute in a worker thread. PLC/camera coroutines are
    submitted to the owning application loop, so the robot transaction stays
    on one thread and its reentrant lock remains valid across PLC waits.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        plc: "PLCClient",
        camera: "CameraService",
        catalog: HostActionCatalog,
        plc_action_client=None,
        sample_id: str,
        save_dir: str | Path,
        call_timeout_s: float = 30.0,
    ) -> None:
        if not sample_id.strip():
            raise ValueError("sample_id cannot be empty")
        self.loop = loop
        self.plc = plc
        self.camera = camera
        self.catalog = catalog
        self.plc_action_client = plc_action_client
        self.sample_id = sample_id
        self.save_dir = Path(save_dir).resolve()
        self.call_timeout_s = float(call_timeout_s)

    def plc_action(
        self,
        action: str,
        business_params: Mapping[str, object],
    ) -> object:
        try:
            binding = self.catalog.plc_actions[action]
        except KeyError as exc:
            raise HostActionConfigError(f"unmapped PLC action: {action}") from exc
        if binding.kind == "l2_action":
            if self.plc_action_client is None:
                raise RuntimeError(
                    f"PLC L2 client is required for host action {action}"
                )
            result = self._submit(
                self.plc_action_client.execute(
                    binding.station,
                    binding.action,
                    timeout=self.call_timeout_s,
                )
            )
            return {
                "action": action,
                "station": binding.station,
                "result": result,
            }

        value = (
            business_params[binding.value_param]
            if binding.value_param is not None
            else binding.value
        )
        variant = (
            ua.VariantType.Boolean
            if binding.variant == "boolean"
            else ua.VariantType.Int16
        )
        if binding.variant == "boolean" and bool(value):
            current = self._submit(self.plc.read_variable(binding.variable))
            if bool(current):
                raise RuntimeError(
                    f"stale PLC handshake is already TRUE: {binding.variable}"
                )
        self._submit(
            self.plc.write_variable_dynamic(
                binding.variable,
                value,
                variant,
            )
        )
        verified = self._submit(self.plc.read_variable(binding.variable))
        if verified != value:
            raise RuntimeError(
                f"PLC write verification failed: {binding.variable}, "
                f"expected={value!r}, actual={verified!r}"
            )
        return {
            "action": action,
            "variable": binding.variable,
            "value": value,
            "verified": verified,
            "host_config_sha256": self.catalog.source_sha256,
        }

    def plc_condition(
        self,
        condition: str,
        business_params: Mapping[str, object],
    ) -> bool:
        try:
            binding = self.catalog.plc_conditions[condition]
        except KeyError as exc:
            raise HostActionConfigError(
                f"unmapped PLC condition: {condition}"
            ) from exc
        actual = self._submit(self.plc.read_variable(binding.variable))
        return actual == binding.equals

    def camera_action(
        self,
        action: str,
        business_params: Mapping[str, object],
    ) -> object:
        try:
            binding = self.catalog.camera_actions[action]
        except KeyError as exc:
            raise HostActionConfigError(f"unmapped camera action: {action}") from exc
        path = Path(
            self._submit(
                self.camera.capture(
                    self.sample_id,
                    self.save_dir,
                    filename=binding.filename,
                )
            )
        ).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"camera result is not a file: {path}")
        return {
            "action": action,
            "sample_id": self.sample_id,
            "path": str(path),
            "size": path.stat().st_size,
            "host_config_sha256": self.catalog.source_sha256,
        }

    def _submit(self, coroutine: object) -> object:
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result(timeout=self.call_timeout_s)
