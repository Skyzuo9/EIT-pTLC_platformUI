"""Read-only normalized registry for Dobot point.json files."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


VALID_STATUSES = {"unreviewed", "validated", "deprecated", "placeholder"}
VALID_MOTIONS = {"move_j", "move_l"}


@dataclass(frozen=True)
class RobotPoint:
    point_id: str
    source_id: str
    robot_name: str
    alias: str
    workstation: str
    role: str
    pose: tuple[float, ...]
    joint: tuple[float, ...] | None
    user: int
    tool: int
    acc: int
    vel: int
    cp: int
    allowed_motion: tuple[str, ...]
    status: str
    source_file: str
    source_version: str
    source_sha256: str
    calibrated_at: str | None = None
    notes: str = ""
    derived_from: str | None = None
    derivation: str = ""


class PointRegistry:
    """Immutable point index with source checksum and startup validation."""

    def __init__(self, points: Iterable[RobotPoint]) -> None:
        self._points = tuple(points)
        self._by_id = self._unique_index("point_id")
        self._by_robot_name = self._unique_index("robot_name")

    @classmethod
    def load(
        cls,
        source_path: str | Path,
        *,
        source_version: str,
        meta_path: str | Path,
    ) -> "PointRegistry":
        source = Path(source_path).resolve()
        meta = Path(meta_path).resolve()
        raw_bytes = source.read_bytes()
        records = json.loads(raw_bytes.decode("utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("robot point source must be a JSON array")
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        meta_overrides, supplement_records, meta_source_version = cls._load_meta(meta)

        points: list[RobotPoint] = []
        for record in records:
            cls._validate_source_record(record)
            robot_name = str(record["name"])
            alias = str(record["alias"])
            point = RobotPoint(
                point_id=f"robot-main.{cls._slug(alias or robot_name)}",
                source_id=str(record["id"]),
                robot_name=robot_name,
                alias=alias,
                workstation=cls._infer_workstation(alias),
                role=cls._infer_role(alias),
                pose=tuple(float(v) for v in record["pose"]),
                joint=tuple(float(v) for v in record["joint"]),
                user=int(record["user"]),
                tool=int(record["tool"]),
                acc=20,
                vel=20,
                cp=0,
                allowed_motion=(),
                status="placeholder" if cls._looks_placeholder(record) else "unreviewed",
                source_file=str(source),
                source_version=source_version,
                source_sha256=checksum,
            )
            override = meta_overrides.get(robot_name, {})
            if override:
                point = replace(point, **override)
            cls._validate_normalized(point)
            points.append(point)

        if supplement_records:
            points.extend(
                cls._build_supplemental(
                    supplement_records,
                    points,
                    meta_source_version=meta_source_version,
                    meta_path=meta,
                    meta_checksum=hashlib.sha256(meta.read_bytes()).hexdigest(),
                )
            )
        return cls(points)
    @property
    def points(self) -> tuple[RobotPoint, ...]:
        return self._points

    @property
    def source_sha256(self) -> str:
        return self._points[0].source_sha256 if self._points else ""

    def with_derived_points(
        self,
        records: list[dict[str, object]],
        *,
        source_path: str | Path,
        source_version: str,
    ) -> "PointRegistry":
        """Return a new registry containing explicitly declared derived points.

        Derived points may reference taught source points only and may apply
        translation offsets only. Callers must declare every point id, base
        point and offset; this method never infers names from business ids.
        """
        source = Path(source_path).resolve()
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        normalized: list[dict[str, object]] = []
        for raw in records:
            required = {"point_id", "base_point", "offset", "workstation", "role"}
            if not isinstance(raw, dict) or not required.issubset(raw):
                raise ValueError(
                    "derived point requires point_id/base_point/offset/workstation/role"
                )
            base = self.get(str(raw["base_point"]))
            if base.status != "validated":
                raise PermissionError(
                    f"derived point base {base.point_id} is not validated"
                )
            point_id = str(raw["point_id"])
            normalized.append(
                {
                    "source_id": str(raw.get("source_id", f"derived:{point_id}")),
                    "robot_name": str(raw.get("robot_name", f"DERIVED__{point_id}")),
                    "point_id": point_id,
                    "alias": str(raw.get("alias", point_id)),
                    "workstation": str(raw["workstation"]),
                    "role": str(raw["role"]),
                    "user": int(raw.get("user", base.user)),
                    "tool": int(raw.get("tool", base.tool)),
                    "allowed_motion": list(raw.get("allowed_motion", ["move_l"])),
                    "status": str(raw.get("status", "validated")),
                    "base_point": base.robot_name,
                    "offset": raw["offset"],
                    "notes": str(raw.get("notes", "")),
                }
            )
        derived = self._build_supplemental(
            normalized,
            list(self._points),
            meta_source_version=source_version,
            meta_path=source,
            meta_checksum=checksum,
        )
        return PointRegistry((*self._points, *derived))

    def get(self, point_id_or_robot_name: str) -> RobotPoint:
        try:
            return self._by_id.get(point_id_or_robot_name) or self._by_robot_name[point_id_or_robot_name]
        except KeyError as exc:
            raise KeyError(f"unknown robot point: {point_id_or_robot_name}") from exc

    def require_motion(self, point_id_or_robot_name: str, motion: str) -> RobotPoint:
        point = self.get(point_id_or_robot_name)
        if point.status != "validated":
            raise PermissionError(f"point {point.point_id} is {point.status}, not validated")
        if motion not in point.allowed_motion:
            raise PermissionError(f"point {point.point_id} does not allow {motion}")
        return point

    def duplicate_pose_groups(self, precision: int = 6) -> list[tuple[str, ...]]:
        groups: dict[tuple[float, ...], list[str]] = {}
        for point in self._points:
            key = tuple(round(value, precision) for value in point.pose)
            groups.setdefault(key, []).append(point.robot_name)
        return [tuple(names) for names in groups.values() if len(names) > 1]

    def _unique_index(self, field: str) -> dict[str, RobotPoint]:
        result: dict[str, RobotPoint] = {}
        for point in self._points:
            key = str(getattr(point, field))
            if key in result:
                raise ValueError(f"duplicate {field}: {key}")
            result[key] = point
        return result

    @staticmethod
    def _load_meta(path: str | Path) -> tuple[dict[str, dict[str, object]], list[dict[str, object]], str]:
        """Load and validate the unified robot_points_meta.json (version 2).

        Returns (overrides, supplement, meta_source_version).
        """
        source = Path(path).resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            raise ValueError("robot points meta version must be 2")
        overrides = data.get("overrides")
        supplement = data.get("supplement")
        if not isinstance(overrides, dict):
            raise ValueError("robot points meta overrides must be a JSON object")
        if not isinstance(supplement, list):
            raise ValueError("robot points meta supplement must be a JSON array")
        allowed = {
            "point_id", "workstation", "role", "allowed_motion", "status",
            "calibrated_at", "notes", "acc", "vel", "cp",
        }
        for name, values in overrides.items():
            unknown = set(values) - allowed
            if unknown:
                raise ValueError(f"unsupported overrides in meta for {name}: {sorted(unknown)}")
            if "allowed_motion" in values:
                values["allowed_motion"] = tuple(values["allowed_motion"])
        meta_source_version = str(data.get("source_version", "v0.11"))
        return overrides, supplement, meta_source_version

    @staticmethod
    def _build_supplemental(
        records: list[dict[str, object]],
        source_points: list[RobotPoint],
        *,
        meta_source_version: str,
        meta_path: Path,
        meta_checksum: str,
    ) -> list[RobotPoint]:
        """Build supplement RobotPoints with offset resolution against source points."""
        required = {
            "source_id", "robot_name", "point_id", "alias", "workstation", "role",
            "user", "tool", "allowed_motion", "status",
        }
        source_by_name: dict[str, RobotPoint] = {p.robot_name: p for p in source_points}
        points: list[RobotPoint] = []

        for record in records:
            if not isinstance(record, dict) or not required.issubset(record):
                raise ValueError("invalid supplement point record in meta")

            base_point_name = record.get("base_point")
            has_offset = (
                base_point_name is not None
                and isinstance(base_point_name, str)
                and base_point_name != ""
            )

            if has_offset:
                offset_raw = record["offset"]
                offset = tuple(float(v) for v in offset_raw)
                if len(offset) != 6:
                    raise ValueError(
                        f"supplement point {record['point_id']} offset must contain six values"
                    )
                # 偏移量在基坐标系下逐元素加法计算，仅支持平移分量
                # (x, y, z)；旋转分量 (rx, ry, rz) 不通过简单加法组合。
                if any(abs(offset[i]) > 1e-9 for i in range(3, 6)):
                    raise ValueError(
                        f"supplement point {record['point_id']} offset[3:6] "
                        f"(rx, ry, rz) 必须全为零；不支持旋转偏移。"
                        f"实际值: {offset[3:]}"
                    )
                base_name = str(base_point_name)
                base = source_by_name.get(base_name)
                if base is None:
                    raise ValueError(
                        f"supplement point {record['point_id']} base_point '{base_name}' "
                        f"not found in point.json source points "
                        f"(supplement points can only reference taught source points)"
                    )
                computed_pose = tuple(base.pose[i] + offset[i] for i in range(6))
                if "pose" in record:
                    explicit_pose = tuple(float(v) for v in record["pose"])
                    if len(explicit_pose) != 6:
                        raise ValueError(
                            f"supplement point {record['point_id']} pose must contain six values"
                        )
                    if not all(
                        math.isclose(computed_pose[i], explicit_pose[i], rel_tol=1e-9, abs_tol=0.001)
                        for i in range(6)
                    ):
                        raise ValueError(
                            f"supplement point {record['point_id']} computed pose "
                            f"{computed_pose} does not match explicit pose {explicit_pose}"
                        )
                pose = computed_pose
                joint = None
            elif "pose" in record:
                pose = tuple(float(v) for v in record["pose"])
                if len(pose) != 6:
                    raise ValueError(
                        f"supplement point {record['point_id']} pose must contain six values"
                    )
                joint_raw = record.get("joint")
                joint = None if joint_raw is None else tuple(float(v) for v in joint_raw)
                if joint is not None and len(joint) != 6:
                    raise ValueError(
                        f"supplement point {record['point_id']} joint must contain six values"
                    )
            else:
                raise ValueError(
                    f"supplement point {record['point_id']} must have either "
                    f"base_point+offset or explicit pose"
                )

            point = RobotPoint(
                point_id=str(record["point_id"]),
                source_id=str(record["source_id"]),
                robot_name=str(record["robot_name"]),
                alias=str(record["alias"]),
                workstation=str(record["workstation"]),
                role=str(record["role"]),
                pose=pose,
                joint=joint,
                user=int(record["user"]),
                tool=int(record["tool"]),
                acc=int(record.get("acc", 20)),
                vel=int(record.get("vel", 20)),
                cp=int(record.get("cp", 0)),
                allowed_motion=tuple(str(v) for v in record["allowed_motion"]),
                status=str(record["status"]),
                source_file=str(meta_path),
                source_version=meta_source_version,
                source_sha256=meta_checksum,
                calibrated_at=record.get("calibrated_at"),
                notes=str(record.get("notes", "")),
                derived_from=record.get("derived_from") or (str(base_point_name) if has_offset else None),
                derivation=str(record.get("derivation", "")),
            )
            PointRegistry._validate_normalized(point)
            points.append(point)

        return points

    @staticmethod
    def _validate_source_record(record: object) -> None:
        required = {"id", "name", "alias", "pose", "joint", "user", "tool"}
        if not isinstance(record, dict) or not required.issubset(record):
            raise ValueError("invalid point.json record")
        if len(record["pose"]) != 6 or len(record["joint"]) != 6:
            raise ValueError(f"point {record['name']} must have six pose and joint values")

    @staticmethod
    def _validate_normalized(point: RobotPoint) -> None:
        if point.status not in VALID_STATUSES:
            raise ValueError(f"invalid status for {point.robot_name}: {point.status}")
        if not set(point.allowed_motion).issubset(VALID_MOTIONS):
            raise ValueError(f"invalid allowed_motion for {point.robot_name}")
        if point.status == "validated" and not point.allowed_motion:
            raise ValueError(f"validated point {point.robot_name} must allow at least one motion type")
        if point.status != "validated" and point.allowed_motion:
            raise ValueError(f"non-validated point {point.robot_name} cannot allow production motion")
        if "move_j" in point.allowed_motion and point.joint is None:
            raise ValueError(f"move_j point {point.robot_name} must contain joint values")
        if not 1 <= point.acc <= 100 or not 1 <= point.vel <= 100 or not 0 <= point.cp <= 100:
            raise ValueError(f"invalid acc/vel/cp for {point.robot_name}")

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "unnamed"

    @staticmethod
    def _infer_workstation(alias: str) -> str:
        match = re.search(r"area[_-]?(\d+)", alias, re.IGNORECASE)
        if match:
            return f"area-{match.group(1)}"
        if alias.lower() == "home":
            return "global"
        if "shijue" in alias.lower():
            return "vision"
        if "biaoding" in alias.lower():
            return "calibration"
        return "unknown"

    @staticmethod
    def _infer_role(alias: str) -> str:
        lower = alias.lower()
        if lower == "home":
            return "home"
        if "ready" in lower:
            return "ready"
        if "biaoding" in lower:
            return "calibration"
        return "target"

    @staticmethod
    def _looks_placeholder(record: dict[str, object]) -> bool:
        pose = tuple(float(v) for v in record["pose"])
        joint = tuple(float(v) for v in record["joint"])
        return int(record["tool"]) == 0 and all(abs(v) < 1e-9 for v in joint) and pose == (0.0, -246.0, 1047.0, -90.0, 0.0, 180.0)
