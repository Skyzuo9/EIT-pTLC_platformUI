"""Fail-closed verification for generated PTLC robot clips and calibration assets."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

from robot_kinematics import forward_kinematics, load_calibration


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _segment_deviation_mm(points: np.ndarray) -> float:
    start, end = points[0], points[-1]
    delta = end - start
    length_sq = float(delta @ delta)
    if length_sq < 1e-16:
        return float(np.max(np.linalg.norm(points - start, axis=1)) * 1000.0)
    ratio = np.clip(((points - start) @ delta) / length_sq, 0.0, 1.0)
    nearest = start + ratio[:, None] * delta
    return float(np.max(np.linalg.norm(points - nearest, axis=1)) * 1000.0)


def verify(workspace_root: Path) -> dict:
    calibration = load_calibration()
    calibration_version = str(calibration["version"])
    catalog = json.loads((workspace_root / "generated" / "robot-points.json").read_text(encoding="utf-8"))
    expected_hash = calibration["reference_points"]["sha256"]
    expected_commit = calibration["kinematics_source"]["commit"]
    if catalog.get("referencePointHash") != expected_hash:
        raise ValueError("robot-points.json 点表 SHA 与校准文件不一致")
    if catalog.get("kinematicsCommit") != expected_commit:
        raise ValueError("robot-points.json 官方模型提交与校准文件不一致")

    manifest_path = workspace_root / "models" / "device-manifest.official-cr5.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    robot_manifest = manifest.get("robot") or {}
    if robot_manifest.get("calibrationVersion") != calibration_version:
        raise ValueError("浏览器 manifest 校准版本与校准文件不一致")
    if robot_manifest.get("referencePointHash") != expected_hash:
        raise ValueError("浏览器 manifest 点表 SHA 与校准文件不一致")
    if (robot_manifest.get("kinematicsSource") or {}).get("commit") != expected_commit:
        raise ValueError("浏览器 manifest 官方模型提交与校准文件不一致")

    expected_registration = calibration["scene_registration"]
    manifest_registration = robot_manifest.get("baseTransform") or {}
    if not np.isclose(
        float(manifest_registration.get("base_contact_height_m", float("nan"))),
        float(expected_registration["base_contact_height_m"]),
        atol=1e-9,
    ):
        raise ValueError("浏览器 manifest 仍在使用过期的 CR5 基座接触高度")
    expected_base = np.asarray(
        expected_registration["base_transform_at_reference_rail"]["matrix"], dtype=float
    )
    manifest_base = np.asarray(
        (manifest_registration.get("base_transform_at_reference_rail") or {}).get("matrix", []),
        dtype=float,
    )
    if manifest_base.shape != (4, 4) or not np.allclose(manifest_base, expected_base, atol=1e-9):
        raise ValueError("浏览器 manifest 的 CR5 基座矩阵与校准文件不一致")

    expected_mount = calibration["physical_tool_mount"]
    manifest_mount = robot_manifest.get("toolMountTransform") or {}
    for field in ("translation_m", "rpy_deg"):
        actual_values = np.asarray(manifest_mount.get(field, []), dtype=float)
        expected_values = np.asarray(expected_mount[field], dtype=float)
        if actual_values.shape != expected_values.shape or not np.allclose(
            actual_values, expected_values, atol=1e-8
        ):
            raise ValueError(f"浏览器 manifest 的工具安装变换 {field} 与校准文件不一致")

    clean_report = json.loads((ROOT / "work" / "03_clean_model.report.json").read_text(encoding="utf-8"))
    clean_robot = clean_report.get("robot_joints") or {}
    if clean_robot.get("calibration_version") != calibration_version:
        raise ValueError("导出模型报告的校准版本与校准文件不一致，必须重建 GLB")
    clean_base = np.asarray(
        ((clean_robot.get("base_transform") or {}).get("base_transform_at_reference_rail") or {}).get(
            "matrix", []
        ),
        dtype=float,
    )
    if clean_base.shape != (4, 4) or not np.allclose(clean_base, expected_base, atol=1e-9):
        raise ValueError("导出模型报告的 CR5 基座矩阵与校准文件不一致，必须重建 GLB")

    source_model = workspace_root / "models" / "machine.official-cr5.glb"
    source_model_hash = _sha256(source_model)

    report = {"clips": {}, "asset_contract": {
        "calibration_version": calibration_version,
        "base_contact_height_m": float(expected_registration["base_contact_height_m"]),
        "model_sha256": source_model_hash,
    }, "thresholds": {
        "move_j_endpoint_deg": 0.01,
        "move_l_line_mm": 5.0,
        "move_l_endpoint_mm": 1.0,
        "joint_frame_jump_deg": 180.0,
    }}
    for path in sorted((workspace_root / "clips").glob("robot.tool_*.yaml")):
        clip = yaml.safe_load(path.read_text(encoding="utf-8"))
        if clip.get("schema") != "ptlc.clip/v2":
            raise ValueError(f"{path.name} 不是 ptlc.clip/v2")
        source = clip.get("source") or {}
        if source.get("referencePointHash") != expected_hash or source.get("kinematicsCommit") != expected_commit:
            raise ValueError(f"{path.name} 使用了过期点表或运动学")

        trajectories = (clip.get("compiled") or {}).get("moveLTrajectories") or {}
        clip_result = {"move_j": [], "move_l": []}
        for index, step in enumerate(clip.get("steps") or []):
            point_ref = ((step.get("do") or {}).get("robot_point") or {})
            if not point_ref:
                continue
            point_id = str(point_ref["id"])
            point = catalog["points"].get(point_id)
            if point is None:
                raise ValueError(f"{path.name}: 缺少点位 {point_id}")
            motion = point_ref.get("motion")
            if motion == "move_j":
                joint = point.get("joint")
                if not joint or len(joint) != 6:
                    raise ValueError(f"{path.name}: move_j {point_id} 缺少六轴实测角")
                clip_result["move_j"].append({"point": point_id, "endpoint_error_deg": 0.0})
                continue
            if motion != "move_l":
                raise ValueError(f"{path.name}: 不支持运动 {motion}")

            frames = trajectories.get(str(index))
            if not frames or len(frames) < 2:
                raise ValueError(f"{path.name}: move_l {point_id} 缺少连续 IK 轨迹")
            joints = np.asarray(frames, dtype=float)
            jumps = np.max(np.abs(np.diff(joints, axis=0)), axis=1)
            max_jump = float(np.max(jumps))
            if max_jump >= 180.0:
                raise ValueError(f"{path.name}: {point_id} 出现跨周跳变 {max_jump:.3f}°")

            tool = int(point.get("tool") or 0)
            tcp = np.asarray([
                forward_kinematics(frame, calibration, tool=tool)[:3, 3]
                for frame in joints
            ])
            target = np.asarray(point["pose"][:3], dtype=float) / 1000.0
            endpoint_mm = float(np.linalg.norm(tcp[-1] - target) * 1000.0)
            line_mm = _segment_deviation_mm(tcp)
            if endpoint_mm > 1.0:
                raise ValueError(f"{path.name}: {point_id} FK 终点误差 {endpoint_mm:.3f}mm")
            if line_mm > 5.0:
                raise ValueError(f"{path.name}: {point_id} TCP 直线偏差 {line_mm:.3f}mm")
            clip_result["move_l"].append({
                "point": point_id,
                "samples": len(frames),
                "endpoint_error_mm": round(endpoint_mm, 4),
                "line_deviation_mm": round(line_mm, 4),
                "max_joint_frame_jump_deg": round(max_jump, 4),
            })

        report["clips"][clip["name"]] = clip_result
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="验证三维模块机器人离线资产")
    parser.add_argument("--workspace", default=str(ROOT))
    parser.add_argument("--report", default=str(ROOT / "work" / "verify_robot_assets.json"))
    args = parser.parse_args()
    report = verify(Path(args.workspace).resolve())
    Path(args.report).resolve().write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    move_l = [item for clip in report["clips"].values() for item in clip["move_l"]]
    print(json.dumps({
        "clips": len(report["clips"]),
        "move_l_segments": len(move_l),
        "max_line_deviation_mm": round(max(item["line_deviation_mm"] for item in move_l), 4),
        "max_endpoint_error_mm": round(max(item["endpoint_error_mm"] for item in move_l), 4),
        "max_joint_frame_jump_deg": round(max(item["max_joint_frame_jump_deg"] for item in move_l), 4),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
