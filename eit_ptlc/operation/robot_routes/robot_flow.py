"""Robot named-point flow catalog and serialized executor."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable


from eit_ptlc.controller.point_registry import PointRegistry, RobotPoint
from eit_ptlc.driver.robot_transport import (
    MotionProfile,
    RobotFeedback,
    RobotTransportError,
    TOOL_ACTION_NAMES,
    ToolAction,
)

if TYPE_CHECKING:
    from eit_ptlc.controller.robot_controller import RobotController as RobotActionService


@dataclass(frozen=True)
class MoveStep:
    step_id: str
    point: str
    motion: str
    profile: MotionProfile


@dataclass(frozen=True)
class ToolStep:
    step_id: str
    action: ToolAction
    timeout_ms: int = 3000


@dataclass(frozen=True)
class WaitStep:
    step_id: str
    duration_ms: int


@dataclass(frozen=True)
class SetMountedToolStep:
    """声明权威工具态 (0=无/裸腕, 1/2/3=slot); 换刀编排里挂/卸刀后通知驱动."""
    step_id: str
    tool_id: int


FlowStep = MoveStep | ToolStep | WaitStep | SetMountedToolStep


@dataclass(frozen=True)
class RobotFlow:
    flow_id: str
    description: str
    entry_point: str
    exit_point: str
    steps: tuple[FlowStep, ...]
    anchor_joint_tolerance_deg: float = 2.0
    anchor_position_tolerance_mm: float = 5.0
    anchor_rotation_tolerance_deg: float = 5.0


@dataclass(frozen=True)
class FlowStepResult:
    step_id: str
    kind: str
    elapsed_s: float
    feedback: RobotFeedback | None


@dataclass(frozen=True)
class RobotFlowResult:
    flow_id: str
    elapsed_s: float
    completed_steps: tuple[FlowStepResult, ...]
    final_feedback: RobotFeedback


class RobotFlowError(RobotTransportError):
    def __init__(
        self,
        flow_id: str,
        failed_step: str,
        completed_steps: tuple[FlowStepResult, ...],
        cause: BaseException,
    ) -> None:
        super().__init__(f"robot flow {flow_id} failed at {failed_step}: {cause}")
        self.flow_id = flow_id
        self.failed_step = failed_step
        self.completed_steps = completed_steps
        self.cause = cause


class RobotFlowService:
    """Execute an audited flow while holding the RobotActionService lease."""

    def __init__(
        self,
        action_service: "RobotActionService",
        registry: PointRegistry,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.action_service = action_service
        self.registry = registry
        self._sleep = sleep_fn

    def run_resolved(
        self,
        flow: RobotFlow,
        *,
        on_step: Callable[[str, str], None] | None = None,
    ) -> RobotFlowResult:
        """Execute a preflighted concrete plan from the schema-v2 resolver."""

        completed: list[FlowStepResult] = []
        flow_started = time.monotonic()
        last_feedback: RobotFeedback | None = None

        with self.action_service.exclusive():
            try:
                entry_feedback = self.action_service.query()
                self._require_anchor(flow, flow.entry_point, entry_feedback)
            except BaseException as exc:
                raise RobotFlowError(flow.flow_id, "<entry-check>", (), exc) from exc

            for step in flow.steps:
                step_started = time.monotonic()
                if on_step is not None:
                    on_step(step.step_id, "RUNNING")
                try:
                    if isinstance(step, MoveStep):
                        last_feedback = self.action_service.move_to_point(
                            step.point,
                            step.motion,
                            profile=step.profile,
                        )
                        kind = "move"
                    elif isinstance(step, ToolStep):
                        last_feedback = self.action_service.tool_action(
                            step.action,
                            step.timeout_ms,
                        )
                        kind = "tool_action"
                    elif isinstance(step, SetMountedToolStep):
                        self.action_service.set_mounted_tool(step.tool_id)
                        kind = "set_mounted_tool"
                    else:
                        self._sleep(step.duration_ms / 1000.0)
                        kind = "wait"
                    completed.append(
                        FlowStepResult(
                            step_id=step.step_id,
                            kind=kind,
                            elapsed_s=time.monotonic() - step_started,
                            feedback=last_feedback if kind in ("move", "tool_action") else None,
                        )
                    )
                    if on_step is not None:
                        on_step(step.step_id, "DONE")
                except BaseException as exc:
                    if on_step is not None:
                        on_step(step.step_id, "ERROR")
                    raise RobotFlowError(
                        flow.flow_id,
                        step.step_id,
                        tuple(completed),
                        exc,
                    ) from exc

            try:
                final_feedback = last_feedback or self.action_service.query()
                self._require_anchor(flow, flow.exit_point, final_feedback)
            except BaseException as exc:
                raise RobotFlowError(
                    flow.flow_id,
                    "<exit-check>",
                    tuple(completed),
                    exc,
                ) from exc

        return RobotFlowResult(
            flow_id=flow.flow_id,
            elapsed_s=time.monotonic() - flow_started,
            completed_steps=tuple(completed),
            final_feedback=final_feedback,
        )

    def _require_anchor(
        self,
        flow: RobotFlow,
        point_name: str,
        feedback: RobotFeedback,
    ) -> None:
        point = self.registry.get(point_name)
        if point.joint is not None and len(feedback.joint) == 6:
            delta = max(
                abs(_angle_delta_deg(actual, expected))
                for actual, expected in zip(feedback.joint, point.joint)
            )
            if delta > flow.anchor_joint_tolerance_deg:
                raise PermissionError(
                    f"robot is not at anchor {point.point_id}: joint delta={delta:.3f} deg"
                )
            return
        if len(feedback.pose) != 6:
            raise PermissionError(f"robot feedback cannot verify anchor {point.point_id}")
        position_delta = max(abs(feedback.pose[i] - point.pose[i]) for i in range(3))
        rotation_delta = max(
            abs(_angle_delta_deg(feedback.pose[i], point.pose[i])) for i in range(3, 6)
        )
        if (
            position_delta > flow.anchor_position_tolerance_mm
            or rotation_delta > flow.anchor_rotation_tolerance_deg
        ):
            raise PermissionError(
                f"robot is not at anchor {point.point_id}: "
                f"position delta={position_delta:.3f} mm, rotation delta={rotation_delta:.3f} deg"
            )


def _angle_delta_deg(actual: float, expected: float) -> float:
    return math.fmod(actual - expected + 540.0, 360.0) - 180.0

