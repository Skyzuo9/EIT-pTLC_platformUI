"""Pinned Dobot CR5 forward/inverse kinematics used by the PTLC asset compiler.

This module is build-time only.  Browser code consumes generated joint samples and the
manifest; it never receives a development-machine path or guesses an unreachable pose.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
import yaml
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation, Slerp


CALIBRATION_PATH = Path(__file__).with_name("calibration") / "cr5_ptlc_v1.yaml"


def load_calibration(path: str | Path = CALIBRATION_PATH) -> dict:
    """Load and minimally validate the versioned CR5 calibration."""
    with Path(path).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if data.get("schema") != "ptlc.robot-calibration/v1" or len(data.get("joints", ())) != 6:
        raise ValueError(f"invalid CR5 calibration: {path}")
    return data


def _transform(translation=(0.0, 0.0, 0.0), rotation: Rotation | None = None) -> np.ndarray:
    result = np.eye(4, dtype=float)
    result[:3, 3] = np.asarray(translation, dtype=float)
    if rotation is not None:
        result[:3, :3] = rotation.as_matrix()
    return result


def pose_matrix(pose: Iterable[float]) -> np.ndarray:
    """Convert Dobot [x,y,z,rx,ry,rz] (mm/deg, fixed XYZ) to a 4x4 matrix."""
    values = tuple(float(value) for value in pose)
    if len(values) != 6:
        raise ValueError("robot pose must contain six values")
    return _transform(
        np.asarray(values[:3]) / 1000.0,
        Rotation.from_euler("xyz", values[3:], degrees=True),
    )


def tool_matrix(calibration: dict, tool: int) -> np.ndarray:
    spec = (calibration.get("tool_transforms") or {}).get(str(int(tool)))
    if not spec:
        raise ValueError(f"tool {tool} has no flange transform")
    return _transform(
        spec.get("translation_m", (0.0, 0.0, 0.0)),
        Rotation.from_euler("xyz", spec.get("rpy_deg", (0.0, 0.0, 0.0)), degrees=True),
    )


def forward_kinematics(
    joint_deg: Iterable[float],
    calibration: dict,
    *,
    tool: int | None = None,
    apply_mapping: bool = True,
) -> np.ndarray:
    """Return base->flange (or TCP) using the official xacro's local-Z chain."""
    values = np.asarray(tuple(joint_deg), dtype=float)
    if values.shape != (6,):
        raise ValueError("joint vector must contain six values")

    result = _transform(
        calibration.get("base_transform", {}).get("translation_m", (0.0, 0.0, 0.0)),
        Rotation.from_euler(
            "xyz",
            calibration.get("base_transform", {}).get("rpy_deg", (0.0, 0.0, 0.0)),
            degrees=True,
        ),
    )
    for index, spec in enumerate(calibration["joints"]):
        angle = values[index]
        if apply_mapping:
            angle = angle * float(spec.get("sign", 1.0)) + float(spec.get("zero_offset_deg", 0.0))
        result = result @ _transform(
            spec["origin_xyz_m"],
            Rotation.from_euler("xyz", spec["origin_rpy_rad"]),
        )
        axis = np.asarray(spec.get("axis", (0.0, 0.0, 1.0)), dtype=float)
        axis /= np.linalg.norm(axis)
        result = result @ _transform(rotation=Rotation.from_rotvec(axis * math.radians(angle)))
    if tool is not None:
        result = result @ tool_matrix(calibration, tool)
    return result


def unwrap_degrees(values: Iterable[float], reference: Iterable[float]) -> np.ndarray:
    """Choose the equivalent angle nearest the previous frame on every axis."""
    values = np.asarray(tuple(values), dtype=float)
    reference = np.asarray(tuple(reference), dtype=float)
    return reference + (values - reference + 180.0) % 360.0 - 180.0


def interpolate_pose(start: np.ndarray, end: np.ndarray, fraction: float) -> np.ndarray:
    fraction = float(np.clip(fraction, 0.0, 1.0))
    result = np.eye(4)
    result[:3, 3] = start[:3, 3] + (end[:3, 3] - start[:3, 3]) * fraction
    key = Rotation.from_matrix(np.stack([start[:3, :3], end[:3, :3]]))
    result[:3, :3] = Slerp([0.0, 1.0], key)([fraction]).as_matrix()[0]
    return result


def solve_ik(
    target: np.ndarray,
    seed_deg: Iterable[float],
    calibration: dict,
    *,
    tool: int,
    max_position_error_mm: float = 1.0,
    max_orientation_error_deg: float = 0.5,
) -> np.ndarray:
    """Solve one pose continuously from seed; fail closed on limits or FK error."""
    seed = np.asarray(tuple(seed_deg), dtype=float)
    limits = np.asarray([joint["limit_deg"] for joint in calibration["joints"]], dtype=float)

    # Limits span almost two turns on most CR5 axes. Shift each interval by full turns so
    # the optimizer remains around the seed and does not introduce a +/-180 visual jump.
    lower = limits[:, 0].copy()
    upper = limits[:, 1].copy()
    for index in range(6):
        while seed[index] < lower[index]:
            lower[index] -= 360.0
            upper[index] -= 360.0
        while seed[index] > upper[index]:
            lower[index] += 360.0
            upper[index] += 360.0

    def residual(joints: np.ndarray) -> np.ndarray:
        actual = forward_kinematics(joints, calibration, tool=tool)
        position_mm = (actual[:3, 3] - target[:3, 3]) * 1000.0
        orientation_deg = (
            Rotation.from_matrix(target[:3, :3]).inv()
            * Rotation.from_matrix(actual[:3, :3])
        ).as_rotvec() * (180.0 / math.pi)
        return np.concatenate([position_mm, orientation_deg * 5.0])

    solved = least_squares(
        residual,
        np.clip(seed, lower + 1e-7, upper - 1e-7),
        bounds=(lower, upper),
        max_nfev=250,
        xtol=1e-11,
        ftol=1e-11,
        gtol=1e-11,
    )
    joints = unwrap_degrees(solved.x, seed)
    actual = forward_kinematics(joints, calibration, tool=tool)
    position_error = float(np.linalg.norm(actual[:3, 3] - target[:3, 3]) * 1000.0)
    orientation_error = float(
        (
            Rotation.from_matrix(target[:3, :3]).inv()
            * Rotation.from_matrix(actual[:3, :3])
        ).magnitude() * 180.0 / math.pi
    )
    if (
        not solved.success
        or position_error > max_position_error_mm
        or orientation_error > max_orientation_error_deg
        or np.any(joints < lower - 1e-6)
        or np.any(joints > upper + 1e-6)
    ):
        raise ValueError(
            "IK rejected: "
            f"success={solved.success}, pos={position_error:.3f}mm, "
            f"rot={orientation_error:.3f}deg, message={solved.message}"
        )
    return joints


def sample_move_l(
    start_joint_deg: Iterable[float],
    target_pose: Iterable[float],
    calibration: dict,
    *,
    tool: int,
    max_step_mm: float = 5.0,
    max_step_deg: float = 2.0,
    target_joint_deg: Iterable[float] | None = None,
) -> list[list[float]]:
    """Sample TCP line + orientation SLERP, solving every frame from the prior frame.

    为什么中间帧非解 IK 不可: move_l 要求 TCP 走**笛卡尔直线**, 而这条线上的中间位姿
    在点表里没有任何示教数据 —— 点表只有端点。不解就只能走关节空间圆弧, 那是另一种
    物理运动(插入/退刀这类要求直线的路径上会穿模)。

    ``target_joint_deg`` 给了的话, **末帧直接用它**而不是 IK 解: 端点的关节角是实测的,
    比任何数值反解都准。这样既保住了中间段的直线性, 又不会让端点被 IK 的残差带偏
    (曾因此把 `robot_feed_lift_pick_exit` 卡在 1.5mm 残差上编不出来)。
    """
    current = np.asarray(tuple(start_joint_deg), dtype=float)
    start = forward_kinematics(current, calibration, tool=tool)
    target = pose_matrix(target_pose)
    distance_mm = np.linalg.norm(target[:3, 3] - start[:3, 3]) * 1000.0
    rotation_deg = (
        Rotation.from_matrix(start[:3, :3]).inv()
        * Rotation.from_matrix(target[:3, :3])
    ).magnitude() * 180.0 / math.pi
    segments = max(1, int(math.ceil(max(distance_mm / max_step_mm, rotation_deg / max_step_deg))))
    known_target = None
    if target_joint_deg is not None:
        candidate = [float(v) for v in target_joint_deg]
        # 全零是点表里"占位未示教"的哨兵, 不能当实测值用
        if len(candidate) == 6 and max(abs(v) for v in candidate) > 1e-9:
            known_target = candidate

    frames = [current.tolist()]
    for index in range(1, segments + 1):
        # 末帧若有实测关节角就直接落地: 它是真值, 不必也不该再用 IK 去逼近
        if index == segments and known_target is not None:
            frames.append([round(v, 8) for v in known_target])
            break
        desired = interpolate_pose(start, target, index / segments)
        current = solve_ik(desired, current, calibration, tool=tool)
        frames.append([round(float(value), 8) for value in current])
    return frames
