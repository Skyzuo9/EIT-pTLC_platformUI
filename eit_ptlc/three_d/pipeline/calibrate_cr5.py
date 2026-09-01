"""Fit the virtual CR5 mapping from immutable PTLC taught points.

Usage (PowerShell):
    $env:PTLC_CONTROL_ROOT='E:\\eit_lab\\pTLC_platformUI\\eit_ptlc'
    python pipeline/calibrate_cr5.py --check
    python pipeline/calibrate_cr5.py --write

The script never writes the controller repository.  It imports its active PointRegistry so
overrides/derived-point semantics stay identical to production, then fits source points that
are validated for move_j.  Six-axis-zero placeholders and points without measured joints are
excluded by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from robot_kinematics import CALIBRATION_PATH, forward_kinematics, load_calibration


def control_root(value: str | None) -> Path:
    raw = value or os.environ.get("PTLC_CONTROL_ROOT")
    if not raw:
        raise SystemExit("PTLC_CONTROL_ROOT 未设置；拒绝使用写死的开发机路径")
    root = Path(raw).resolve()
    if not (root / "controller" / "point_registry.py").is_file():
        raise SystemExit(f"PTLC_CONTROL_ROOT 不是有效上位机目录: {root}")
    return root


def load_source_points(root: Path):
    sys.path.insert(0, str(root.parent))
    from eit_ptlc.controller.point_registry import PointRegistry  # pylint: disable=import-outside-toplevel

    point_dir = root / "config" / "points" / "robot"
    meta_path = point_dir / "robot_points_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    registry = PointRegistry.load(
        point_dir / "robot_points.json",
        source_version=str(meta.get("source_version", "unknown")),
        meta_path=meta_path,
        labels_path=point_dir / "labels.yaml",
    )
    points = [
        point
        for point in registry.points
        if point.derived_from is None
        and point.status == "validated"
        and "move_j" in point.allowed_motion
        and point.joint is not None
        and len(point.joint) == 6
        and max(abs(value) for value in point.joint) > 1e-9
    ]
    return registry, points


def percentile(values: list[float], q: float) -> float:
    return round(float(np.percentile(np.asarray(values), q)), 4)


def validate_custom_mount_sources(calibration_path: Path, calibration: dict) -> None:
    """Fail closed when the CAD/official meshes used by the geometry fit have changed."""
    alignment = calibration.get("custom_mount_alignment") or {}
    project_root = calibration_path.parents[2]
    for path_key, hash_key in (
        ("source_model", "source_model_sha256"),
        ("official_link6_mesh", "official_link6_mesh_sha256"),
    ):
        relative = alignment.get(path_key)
        expected = str(alignment.get(hash_key, "")).lower()
        if not relative or len(expected) != 64:
            raise SystemExit(f"custom_mount_alignment.{path_key}/{hash_key} 缺失")
        source = project_root / str(relative)
        if not source.is_file():
            raise SystemExit(f"自制末端几何标定源不存在: {source}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise SystemExit(f"自制末端几何标定源已变化: {source}；必须重新做法兰网格配准")


def fit_scene_registration(registry, calibration: dict) -> tuple[dict, dict, dict]:
    """Fit horizontal scene registration and the physical flange-to-coupling transform.

    The controller's Tool 1 pose is a TCP, not the physical quick-change interface. Its
    vertical offset must therefore never lift the robot base. The base height is anchored
    to the CAD rail contact plane; P8/P9/P10 fit only the two horizontal components. Their
    taught joints then fit a separate rigid Link6-flange -> tool-side coupling frame.
    """
    registration = json.loads(json.dumps(calibration.get("scene_registration") or {}))
    correspondences = registration.get("correspondences") or []
    if len(correspondences) != 3:
        raise SystemExit("scene_registration 必须包含 P8/P9/P10 三个工具对接点")
    axis_map = np.asarray(registration.get("axis_map_robot_to_gltf"), dtype=float)
    if axis_map.shape != (3, 3) or not np.allclose(axis_map.T @ axis_map, np.eye(3), atol=1e-9):
        raise SystemExit("scene_registration.axis_map_robot_to_gltf 不是正交 3x3 矩阵")
    dock_rotation = np.asarray(registration.get("dock_frame_rotation"), dtype=float)
    if dock_rotation.shape != (3, 3) or not np.allclose(dock_rotation.T @ dock_rotation, np.eye(3), atol=1e-9):
        raise SystemExit("scene_registration.dock_frame_rotation 不是正交 3x3 矩阵")
    contact_height = registration.get("base_contact_height_m")
    if contact_height is None:
        raise SystemExit("scene_registration.base_contact_height_m 缺失，拒绝猜测地轨接触高度")

    translations = []
    robot_points = []
    scene_points = []
    for item in correspondences:
        point = registry.get(str(item["point_id"]))
        robot_position = np.asarray(point.pose[:3], dtype=float) / 1000.0
        scene_position = np.asarray(item["scene_point_m"], dtype=float)
        robot_points.append(robot_position)
        scene_points.append(scene_position)
        translations.append(scene_position - axis_map @ robot_position)

    translation = np.mean(np.asarray(translations), axis=0)
    # glTF Y 是竖直方向；硬约束来自原始 CAD 的地轨/基座接触装配，不参与 TCP 拟合。
    translation[1] = float(contact_height)
    matrix = np.eye(4)
    matrix[:3, :3] = axis_map
    matrix[:3, 3] = translation
    support = registration.get("rail_support") or {}
    source_mount = np.asarray(support.get("source_mount_frame_m", ()), dtype=float)
    if source_mount.shape != (3,):
        raise SystemExit(
            "scene_registration.rail_support.source_mount_frame_m 缺失，"
            "拒绝用附近钢板或包围盒猜测地轨托盘中心"
        )
    # The fitted base translation is the slot-4 mounting target. Persist it beside
    # the named CAD source datum so Blender moves the complete physical trolley,
    # rather than moving only the robot and leaving the tray at its authoring pose.
    support["reference_mount_frame_m"] = [
        round(float(value), 9) for value in translation
    ]
    registration["rail_support"] = support
    registration.setdefault("base_transform_at_reference_rail", {})["matrix"] = [
        [round(float(value), 9) for value in row] for row in matrix
    ]
    relative_mounts = []
    for item in correspondences:
        point = registry.get(str(item["point_id"]))
        scene_flange = matrix @ forward_kinematics(point.joint, calibration)
        scene_dock = np.eye(4)
        scene_dock[:3, :3] = dock_rotation
        scene_dock[:3, 3] = np.asarray(item["scene_point_m"], dtype=float)
        relative_mounts.append(np.linalg.inv(scene_flange) @ scene_dock)

    mount_translation = np.mean([item[:3, 3] for item in relative_mounts], axis=0)
    mount_rotation = Rotation.from_matrix(
        np.stack([item[:3, :3] for item in relative_mounts])
    ).mean()
    physical_mount = {
        "status": "fitted-from-three-cad-docks",
        "translation_m": [round(float(value), 8) for value in mount_translation],
        "rpy_deg": [
            round(float(value), 8)
            for value in mount_rotation.as_euler("xyz", degrees=True)
        ],
    }
    mount_matrix = np.eye(4)
    mount_matrix[:3, :3] = mount_rotation.as_matrix()
    mount_matrix[:3, 3] = mount_translation
    errors_mm = []
    orientation_errors_deg = []
    for item in correspondences:
        point = registry.get(str(item["point_id"]))
        predicted = matrix @ forward_kinematics(point.joint, calibration) @ mount_matrix
        target_position = np.asarray(item["scene_point_m"], dtype=float)
        errors_mm.append(float(np.linalg.norm(predicted[:3, 3] - target_position) * 1000.0))
        orientation_errors_deg.append(float(
            (Rotation.from_matrix(predicted[:3, :3]).inv() * Rotation.from_matrix(dock_rotation)).magnitude()
            * 180.0 / math.pi
        ))

    validation = {
        "residual_mm": [round(value, 4) for value in errors_mm],
        "orientation_residual_deg": [round(value, 4) for value in orientation_errors_deg],
        "rms_mm": round(float(np.sqrt(np.mean(np.asarray(errors_mm) ** 2))), 4),
        "max_mm": round(float(np.max(errors_mm)), 4),
        "orientation_rms_deg": round(float(np.sqrt(np.mean(np.asarray(orientation_errors_deg) ** 2))), 4),
        "orientation_max_deg": round(float(np.max(orientation_errors_deg)), 4),
    }
    registration["validation"] = validation
    return registration, validation, physical_mount


def fit(root: Path, calibration: dict) -> tuple[dict, dict]:
    registry, points = load_source_points(root)
    indices = np.arange(len(points))
    train = indices[indices % 5 != 0]
    holdout = indices[indices % 5 == 0]

    def tcp_position(point, params: np.ndarray) -> np.ndarray:
        trial = {**calibration, "joints": [dict(spec) for spec in calibration["joints"]]}
        for index, value in enumerate(params[:6]):
            trial["joints"][index]["zero_offset_deg"] = float(value)
        flange = forward_kinematics(point.joint, trial, apply_mapping=True)
        return flange[:3, 3] + flange[:3, :3] @ params[6:9]

    def residual(params: np.ndarray, selected: np.ndarray) -> np.ndarray:
        chunks = []
        for index in selected:
            point = points[int(index)]
            target = np.asarray(point.pose[:3], dtype=float) / 1000.0
            chunks.append((tcp_position(point, params) - target) * 1000.0)
        return np.concatenate(chunks)

    initial = np.asarray(
        [spec.get("zero_offset_deg", 0.0) for spec in calibration["joints"]]
        + calibration["tool_transforms"]["1"]["translation_m"],
        dtype=float,
    )
    solved = least_squares(
        lambda value: residual(value, train),
        initial,
        bounds=(np.r_[np.full(6, -10.0), np.full(3, -0.3)], np.r_[np.full(6, 10.0), np.full(3, 0.3)]),
        loss="soft_l1",
        f_scale=5.0,
        max_nfev=1000,
    )
    if not solved.success:
        raise SystemExit(f"标定优化失败: {solved.message}")

    fitted = {**calibration, "joints": [dict(spec) for spec in calibration["joints"]]}
    for index in range(6):
        fitted["joints"][index]["zero_offset_deg"] = round(float(solved.x[index]), 8)
    fitted["tool_transforms"] = {
        key: dict(value) for key, value in calibration["tool_transforms"].items()
    }
    fitted["tool_transforms"]["1"]["translation_m"] = [
        round(float(value), 8) for value in solved.x[6:9]
    ]

    relative_rotations = []
    for point in points:
        flange = forward_kinematics(point.joint, fitted)
        measured = Rotation.from_euler("xyz", point.pose[3:], degrees=True)
        relative_rotations.append(
            Rotation.from_matrix(flange[:3, :3].T @ measured.as_matrix()).as_quat()
        )
    tool_rotation = Rotation.from_quat(relative_rotations).mean()
    fitted["tool_transforms"]["1"]["rpy_deg"] = [
        round(float(value), 8) for value in tool_rotation.as_euler("xyz", degrees=True)
    ]

    def errors(selected: np.ndarray) -> tuple[list[float], list[float]]:
        position, orientation = [], []
        for index in selected:
            point = points[int(index)]
            actual = forward_kinematics(point.joint, fitted, tool=point.tool)
            target = np.asarray(point.pose[:3], dtype=float) / 1000.0
            position.append(float(np.linalg.norm(actual[:3, 3] - target) * 1000.0))
            measured = Rotation.from_euler("xyz", point.pose[3:], degrees=True)
            orientation.append(float((Rotation.from_matrix(actual[:3, :3]).inv() * measured).magnitude() * 180.0 / math.pi))
        return position, orientation

    train_position, train_orientation = errors(train)
    holdout_position, holdout_orientation = errors(holdout)
    all_position, all_orientation = errors(indices)
    metrics = {
        "position_mm": {
            "train_median": percentile(train_position, 50),
            "train_p95": percentile(train_position, 95),
            "holdout_median": percentile(holdout_position, 50),
            "holdout_p95": percentile(holdout_position, 95),
            "all_max": round(max(all_position), 4),
        },
        "orientation_deg": {
            "train_median": percentile(train_orientation, 50),
            "train_p95": percentile(train_orientation, 95),
            "holdout_median": percentile(holdout_orientation, 50),
            "holdout_p95": percentile(holdout_orientation, 95),
            "all_max": round(max(all_orientation), 4),
        },
    }

    source_path = root / "config" / "points" / "robot" / "robot_points.json"
    fitted["reference_points"].update(
        {
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "source_records": len(json.loads(source_path.read_text(encoding="utf-8-sig"))),
            "fitted_records": len(points),
        }
    )
    scene_registration, scene_metrics, physical_mount = fit_scene_registration(registry, fitted)
    fitted["scene_registration"] = scene_registration
    fitted["physical_tool_mount"] = physical_mount
    metrics["scene_registration_mm"] = scene_metrics
    fitted["validation"] = metrics
    return fitted, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="标定并验证 PTLC CR5 虚拟运动链")
    parser.add_argument("--control-root", help="覆盖 PTLC_CONTROL_ROOT")
    parser.add_argument("--calibration", default=str(CALIBRATION_PATH))
    parser.add_argument("--write", action="store_true", help="验收通过后写回版本化标定文件")
    parser.add_argument("--check", action="store_true", help="同时校验当前点表哈希")
    args = parser.parse_args()

    root = control_root(args.control_root)
    path = Path(args.calibration).resolve()
    current = load_calibration(path)
    validate_custom_mount_sources(path, current)
    fitted, metrics = fit(root, current)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    if metrics["position_mm"]["holdout_p95"] > 15.0 or metrics["orientation_deg"]["holdout_p95"] > 5.0:
        raise SystemExit("留出集超过验收阈值，拒绝写入")
    if args.check and fitted["reference_points"]["sha256"] != current["reference_points"]["sha256"]:
        raise SystemExit("点表 SHA 已变化，请运行 --write 重新标定并重建资产")
    if metrics["scene_registration_mm"]["max_mm"] > 5.0:
        raise SystemExit("三个工具对接点的场景注册残差超过 5 mm，拒绝写入")
    if metrics["scene_registration_mm"]["orientation_max_deg"] > 1.0:
        raise SystemExit("三个工具对接点的实体快换姿态残差超过 1°，拒绝写入")
    if args.check:
        current_matrix = np.asarray(
            current["scene_registration"]["base_transform_at_reference_rail"]["matrix"],
            dtype=float,
        )
        fitted_matrix = np.asarray(
            fitted["scene_registration"]["base_transform_at_reference_rail"]["matrix"],
            dtype=float,
        )
        if not np.allclose(current_matrix, fitted_matrix, atol=1e-8):
            raise SystemExit("工具工位场景注册已变化，请运行 --write 并重建资产")
        current_mount = current.get("physical_tool_mount") or {}
        fitted_mount = fitted.get("physical_tool_mount") or {}
        if not np.allclose(
            np.asarray(current_mount.get("translation_m", ()), dtype=float),
            np.asarray(fitted_mount.get("translation_m", ()), dtype=float),
            atol=1e-8,
        ) or not np.allclose(
            np.asarray(current_mount.get("rpy_deg", ()), dtype=float),
            np.asarray(fitted_mount.get("rpy_deg", ()), dtype=float),
            atol=1e-8,
        ):
            raise SystemExit("实体法兰到快换接口标定已变化，请运行 --write 并重建资产")
    if args.write:
        path.write_text(yaml.safe_dump(fitted, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"已写入 {path}")


if __name__ == "__main__":
    main()
