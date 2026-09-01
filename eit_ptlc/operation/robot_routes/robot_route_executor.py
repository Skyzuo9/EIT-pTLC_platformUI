"""Fail-stop host executor for resolved robot business routes."""

from __future__ import annotations

import time
from contextlib import ExitStack, nullcontext
from dataclasses import asdict, dataclass
from typing import Callable, ContextManager, Mapping, Protocol

from .robot_flow import RobotFlowResult, RobotFlowService
from .robot_route import (
    CameraActionStep,
    HostRouteStep,
    PlcActionStep,
    PlcWaitStep,
    ResolvedRoutePlan,
    ResourceRef,
    RobotRouteStep,
)
from eit_ptlc.controller.robot_controller import RobotController as RobotActionService


class HostActionPort(Protocol):
    """PLC and camera operations owned by the upper-computer layer."""

    def plc_action(
        self,
        action: str,
        business_params: Mapping[str, object],
    ) -> object:
        ...

    def plc_condition(
        self,
        condition: str,
        business_params: Mapping[str, object],
    ) -> bool:
        ...

    def camera_action(
        self,
        action: str,
        business_params: Mapping[str, object],
    ) -> object:
        ...


class ResourceLeasePort(Protocol):
    def lease(
        self,
        resources: tuple[ResourceRef, ...],
        business_params: Mapping[str, object],
    ) -> ContextManager[object]:
        ...


class NullResourceLease:
    """For offline acceptance only; production must inject a real ledger."""

    def lease(
        self,
        resources: tuple[ResourceRef, ...],
        business_params: Mapping[str, object],
    ) -> ContextManager[object]:
        return nullcontext()


@dataclass(frozen=True)
class RouteStepResult:
    step_id: str
    kind: str
    elapsed_s: float
    raw_result: object


@dataclass(frozen=True)
class RouteExecutionResult:
    route_id: str
    business_params: tuple[tuple[str, object], ...]
    resources: tuple[ResourceRef, ...]
    config_version: str
    config_sha256: str
    elapsed_s: float
    steps: tuple[RouteStepResult, ...]


class RouteExecutionError(RuntimeError):
    def __init__(
        self,
        route_id: str,
        failed_step: str,
        completed_steps: tuple[RouteStepResult, ...],
        cause: BaseException,
    ) -> None:
        super().__init__(
            f"route {route_id} failed at {failed_step}: {cause}"
        )
        self.route_id = route_id
        self.failed_step = failed_step
        self.completed_steps = completed_steps
        self.cause = cause


class RouteExecutor:
    """Execute one resolved transaction without retry or recovery side effects."""

    def __init__(
        self,
        *,
        action_service: RobotActionService,
        flow_service: RobotFlowService,
        host: HostActionPort,
        resources: ResourceLeasePort,
        event_sink: Callable[[dict[str, object]], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self.action_service = action_service
        self.flow_service = flow_service
        self.host = host
        self.resources = resources
        self.event_sink = event_sink or (lambda event: None)
        self._monotonic = monotonic
        self._sleep = sleep
        self._stop_requested = stop_requested or (lambda: False)

    def execute(self, plan: ResolvedRoutePlan) -> RouteExecutionResult:
        params = dict(plan.business_params)
        completed: list[RouteStepResult] = []
        started = self._monotonic()
        self._emit(
            "route_start",
            plan,
            business_params=params,
            resources=[asdict(item) for item in plan.resources],
            orchestration_steps=[
                self._step_audit(step) for step in plan.steps
            ],
        )
        robot_indexes = [
            index for index, step in enumerate(plan.steps)
            if isinstance(step, RobotRouteStep)
        ]
        first_robot = robot_indexes[0] if robot_indexes else None
        last_robot = robot_indexes[-1] if robot_indexes else None
        try:
            with self.resources.lease(plan.resources, params):
                with ExitStack() as robot_stack:
                    for step_index, step in enumerate(plan.steps):
                        if (
                            plan.robot_lock_scope == "transaction"
                            and step_index == first_robot
                        ):
                            robot_stack.enter_context(
                                self.action_service.exclusive()
                            )
                        if self._stop_requested():
                            raise RouteExecutionError(
                                plan.route_id,
                                step.step_id,
                                tuple(completed),
                                RuntimeError("route cancellation requested"),
                            )
                        step_started = self._monotonic()
                        self._emit(
                            "step_start",
                            plan,
                            step_id=step.step_id,
                            step=self._step_audit(step),
                        )
                        try:
                            raw = self._execute_step(plan, step, params)
                        except BaseException as exc:
                            self._emit(
                                "step_failed",
                                plan,
                                step_id=step.step_id,
                                failure_reason=str(exc),
                                failure_type=type(exc).__name__,
                            )
                            raise RouteExecutionError(
                                plan.route_id,
                                step.step_id,
                                tuple(completed),
                                exc,
                            ) from exc
                        result = RouteStepResult(
                            step_id=step.step_id,
                            kind=type(step).__name__,
                            elapsed_s=self._monotonic() - step_started,
                            raw_result=raw,
                        )
                        completed.append(result)
                        self._emit(
                            "step_done",
                            plan,
                            step_id=step.step_id,
                            raw_result=self._safe_raw(raw),
                        )
                        if (
                            plan.robot_lock_scope == "transaction"
                            and step_index == last_robot
                        ):
                            robot_stack.close()
        except RouteExecutionError:
            self._emit(
                "route_failed",
                plan,
                completed_steps=[asdict(item) for item in completed],
            )
            raise

        result = RouteExecutionResult(
            route_id=plan.route_id,
            business_params=plan.business_params,
            resources=plan.resources,
            config_version=plan.config_version,
            config_sha256=plan.config_sha256,
            elapsed_s=self._monotonic() - started,
            steps=tuple(completed),
        )
        self._emit("route_done", plan, result=asdict(result))
        return result

    def _execute_step(
        self,
        route: ResolvedRoutePlan,
        step: HostRouteStep,
        params: Mapping[str, object],
    ) -> object:
        if isinstance(step, RobotRouteStep):
            return self.flow_service.run_resolved(
                step.plan.flow,
                on_step=lambda robot_step_id, status: self._emit(
                    "robot_step_status",
                    route,
                    route_step_id=step.step_id,
                    robot_step_id=robot_step_id,
                    status=status,
                ),
            )
        if isinstance(step, PlcActionStep):
            return self.host.plc_action(step.action, params)
        if isinstance(step, PlcWaitStep):
            deadline = self._monotonic() + step.timeout_s
            while True:
                if self._stop_requested():
                    raise RuntimeError("route cancellation requested")
                if self.host.plc_condition(step.condition, params):
                    return {"condition": step.condition, "value": True}
                if self._monotonic() >= deadline:
                    raise TimeoutError(
                        f"PLC condition did not become true: {step.condition}"
                    )
                self._sleep(step.poll_interval_s)
        if isinstance(step, CameraActionStep):
            return self.host.camera_action(step.action, params)
        raise TypeError(f"unsupported route step: {type(step).__name__}")

    @staticmethod
    def _step_audit(step: HostRouteStep) -> dict[str, object]:
        if isinstance(step, RobotRouteStep):
            return {
                "type": "robot_flow",
                "step_id": step.step_id,
                "template_id": step.plan.template_id,
                "business_params": dict(step.plan.business_params),
                "point_set_id": step.plan.point_set_id,
                "route_group": step.plan.route_group,
                "resolved_points": dict(step.plan.resolved_points),
                "robot_steps": [
                    asdict(robot_step) for robot_step in step.plan.flow.steps
                ],
            }
        return {"type": type(step).__name__, **asdict(step)}

    @staticmethod
    def _safe_raw(value: object) -> object:
        if isinstance(value, RobotFlowResult):
            return asdict(value)
        if value is None or isinstance(value, (bool, int, float, str, dict, list, tuple)):
            return value
        return repr(value)

    def _emit(
        self,
        event_type: str,
        plan: ResolvedRoutePlan,
        **payload: object,
    ) -> None:
        self.event_sink(
            {
                "event": event_type,
                "route_id": plan.route_id,
                "config_version": plan.config_version,
                "config_sha256": plan.config_sha256,
                **payload,
            }
        )
