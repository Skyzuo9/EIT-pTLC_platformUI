"""仅供离线等价性测试读取冻结的 schema-v1 行为基线。"""

from __future__ import annotations

from pathlib import Path

import yaml

from core.robot_flow import MoveStep, RobotFlow, ToolStep, WaitStep
from core.robot_transport import MotionProfile, TOOL_ACTION_NAMES


def load_frozen_baseline(path: str | Path) -> dict[str, RobotFlow]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("frozen baseline version must be 1")
    profiles = {
        str(name): MotionProfile(
            acc=int(values["acc"]),
            vel=int(values["vel"]),
            cp=int(values.get("cp", 0)),
        )
        for name, values in data["motion_profiles"].items()
    }
    flows: dict[str, RobotFlow] = {}
    for flow_id, values in data["flows"].items():
        steps = []
        for raw in values["steps"]:
            kind = raw["type"]
            if kind == "move":
                steps.append(MoveStep(
                    step_id=str(raw["id"]),
                    point=str(raw["point"]),
                    motion=str(raw["motion"]),
                    profile=profiles[str(raw["profile"])],
                ))
            elif kind == "tool_action":
                steps.append(ToolStep(
                    step_id=str(raw["id"]),
                    action=TOOL_ACTION_NAMES[str(raw["action"])],
                    timeout_ms=int(raw.get("timeout_ms", 3000)),
                ))
            elif kind == "wait":
                steps.append(WaitStep(
                    step_id=str(raw["id"]),
                    duration_ms=int(raw["duration_ms"]),
                ))
            else:
                raise ValueError(f"unknown frozen baseline step type: {kind}")
        tolerance = values.get("anchor_tolerance") or {}
        flows[str(flow_id)] = RobotFlow(
            flow_id=str(flow_id),
            description=str(values.get("description", "")),
            entry_point=str(values["entry_point"]),
            exit_point=str(values["exit_point"]),
            steps=tuple(steps),
            anchor_joint_tolerance_deg=float(tolerance.get("joint_deg", 2.0)),
            anchor_position_tolerance_mm=float(tolerance.get("position_mm", 5.0)),
            anchor_rotation_tolerance_deg=float(tolerance.get("rotation_deg", 5.0)),
        )
    return flows