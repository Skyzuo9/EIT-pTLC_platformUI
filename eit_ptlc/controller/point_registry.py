"""Read-only normalized registry for Dobot point.json files."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import yaml


VALID_STATUSES = {"unreviewed", "validated", "deprecated", "placeholder"}
VALID_MOTIONS = {"move_j", "move_l"}

# 派生点中文名自动生成: point_id 末段 (normalize: 小写, "-"→"_") -> 后缀。
# labels.yaml 的 suffixes 可逐项覆盖; 未命中再按 role 兜底 (_ROLE_LABEL_SUFFIXES)。
_TAIL_LABEL_SUFFIXES = {
    "far": "·远接近", "approach_far": "·远接近",
    "mid": "·中接近", "approach_mid": "·中接近",
    "near": "·近接近", "approach_near": "·近接近",
    "high": "·高位接近", "approach_high": "·高位接近",
    "retreat_near": "·近退离", "retreat_far": "·远退离",
    "retreat_0": "·退离1", "retreat_1": "·退离2", "retreat_2": "·退离3",
    "x_plus": "·+X靠拢", "x_minus": "·−X靠拢",
    "y_plus": "·+Y靠拢", "y_minus": "·−Y靠拢",
}
_ROLE_LABEL_SUFFIXES = {"approach": "·接近", "retreat": "·退离", "settle": "·靠拢", "ready": "·准备"}


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
    # 地轨槽码 (1-6): 到达本点时地轨应在的工位定位; None=未收编 (退化为编排层 rail_move_safe 字面量)。
    # 单真源: 收编后编排层不再各写地轨 (见 docs/地轨点位合并管理_第7维_设计)。派生/网格点继承 base。
    rail: int | None = None
    # 安全邻域锚点: True = 已验证的自由空间停靠点, 机器人处于其容差邻域内时允许自动 move_j 回 home。
    # 真源在 meta (overrides/supplement 的 safe_anchor 布尔), 仅 validated 点可标; 库位/网格点不读此字段。
    safe_anchor: bool = False
    # 中文显示名 (纯展示, 不参与寻址)。真源在 labels.yaml: 基点/库位按 robot_name 查 points,
    # 派生点按 point_id 查 derived, 未命中时由基点 label + 末段后缀自动生成; 全未命中为空串 (前端回退 alias)。
    label: str = ""


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
        labels_path: str | Path | None = None,
    ) -> "PointRegistry":
        source = Path(source_path).resolve()
        meta = Path(meta_path).resolve()
        # labels.yaml 缺省随 meta 同目录; meta 走临时文件的热替换调用方 (points_service
        # 原文编辑/单点提交) 必须显式传真源路径, 否则重建后中文名会整体丢失。
        labels_file = Path(labels_path).resolve() if labels_path is not None else meta.parent / "labels.yaml"
        point_labels, derived_labels, label_suffixes = cls._load_labels(labels_file)
        raw_bytes = source.read_bytes()
        records = json.loads(raw_bytes.decode("utf-8-sig"))
        if not isinstance(records, list):
            raise ValueError("robot point source must be a JSON array")
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        meta_overrides, supplement_records, grid_records, meta_source_version = cls._load_meta(meta)
        meta_checksum = hashlib.sha256(meta.read_bytes()).hexdigest()

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
                label=point_labels.get(robot_name, ""),
            )
            override = meta_overrides.get(robot_name, {})
            if override:
                point = replace(point, **override)
            cls._validate_normalized(point)
            points.append(point)

        if grid_records:
            # 仿射网格库位 (如货架): 先展开为基点级 slot 点 (P25-P36 …), 使后续 offset
            # 派生接近点仍可正常引用它们, operation 也照旧按 slot 名寻址。网格为库位真源:
            # 若 point.json 仍含同名示教点 (迁移过渡态 / 原始设备导出), 由网格取代之
            # (避免 robot_name/point_id 重复, 并让上位机的仿射几何成为唯一来源)。
            grid_points = cls._build_grids(
                grid_records,
                meta_source_version=meta_source_version,
                meta_path=meta,
                meta_checksum=meta_checksum,
                point_labels=point_labels,
            )
            grid_names = {p.robot_name for p in grid_points}
            points = [p for p in points if p.robot_name not in grid_names]
            points.extend(grid_points)
        if supplement_records:
            points.extend(
                cls._build_supplemental(
                    supplement_records,
                    points,
                    meta_source_version=meta_source_version,
                    meta_path=meta,
                    meta_checksum=meta_checksum,
                    derived_labels=derived_labels,
                    label_suffixes=label_suffixes,
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
            # 派生点可能已并入 meta.supplement (运行期单一来源); 若已存在则校验解析一致后
            # 幂等跳过, 使离线工具/测试的 RobotPlanCatalog.load(flows, ...) 不因重复 point_id 失败.
            if point_id in self._by_id:
                offset = tuple(float(v) for v in raw["offset"])
                expected = tuple(base.pose[i] + offset[i] for i in range(6))
                current = self._by_id[point_id].pose
                if not all(
                    math.isclose(current[i], expected[i], rel_tol=1e-9, abs_tol=1e-3)
                    for i in range(6)
                ):
                    raise ValueError(
                        f"derived point {point_id} conflicts with existing registry "
                        f"point: existing pose {current} != flows-derived {expected}"
                    )
                continue
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
                    # 派生点省略 status 即视为 validated + move_l (确定性几何派生: 已验证基点+纯平移offset、rx/ry/rz强制0, 无需逐点示教确认)。示教点不走此默认。
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

    def safe_anchor_points(self) -> tuple[RobotPoint, ...]:
        """全部安全邻域锚点 (meta safe_anchor=true 且 validated), 供 ensure_home 邻域判定."""
        return tuple(point for point in self._points if point.safe_anchor)

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
    def _load_meta(path: str | Path) -> tuple[dict[str, dict[str, object]], list[dict[str, object]], list[dict[str, object]], str]:
        """Load and validate the unified robot_points_meta.json (version 2).

        Returns (overrides, supplement, grids, meta_source_version).
        """
        source = Path(path).resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 2:
            raise ValueError("robot points meta version must be 2")
        overrides = data.get("overrides")
        supplement = data.get("supplement")
        grids = data.get("grids", [])
        if not isinstance(overrides, dict):
            raise ValueError("robot points meta overrides must be a JSON object")
        if not isinstance(supplement, list):
            raise ValueError("robot points meta supplement must be a JSON array")
        if not isinstance(grids, list):
            raise ValueError("robot points meta grids must be a JSON array")
        allowed = {
            "point_id", "workstation", "role", "allowed_motion", "status",
            "calibrated_at", "notes", "acc", "vel", "cp", "rail", "safe_anchor",
        }
        for name, values in overrides.items():
            unknown = set(values) - allowed
            if unknown:
                raise ValueError(f"unsupported overrides in meta for {name}: {sorted(unknown)}")
            if "allowed_motion" in values:
                values["allowed_motion"] = tuple(values["allowed_motion"])
            if values.get("rail") is not None:
                values["rail"] = int(values["rail"])  # 槽码存 int; 供 replace(point, **override) 并入
            if "safe_anchor" in values:
                values["safe_anchor"] = bool(values["safe_anchor"])  # 安全邻域布尔; 供 replace 并入
        meta_source_version = str(data.get("source_version", "v0.11"))
        return overrides, supplement, grids, meta_source_version

    @staticmethod
    def _load_labels(path: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        """Load labels.yaml -> (points: robot_name→中文, derived: point_id→中文, suffixes 覆盖表).

        文件缺失即全空 (显示回退 alias); 存在则强校验结构, 防静默丢名。
        """
        if not path.exists():
            return {}, {}, {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("robot labels.yaml version 必须为 1")
        result: list[dict[str, str]] = []
        for section in ("points", "derived", "suffixes"):
            raw = data.get(section) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"robot labels.yaml {section} 必须是 mapping")
            result.append({str(k): str(v) for k, v in raw.items()})
        return result[0], result[1], result[2]

    @staticmethod
    def _derive_label(
        base_label: str,
        point_id: str,
        role: str,
        label_suffixes: dict[str, str] | None = None,
    ) -> str:
        if not base_label:
            return ""
        tail = point_id.rsplit(".", 1)[-1].lower().replace("-", "_")
        table = {**_TAIL_LABEL_SUFFIXES, **(label_suffixes or {})}
        suffix = table.get(tail) or _ROLE_LABEL_SUFFIXES.get(role, "")
        if not suffix:
            return ""
        return f"{base_label}{suffix}"

    @staticmethod
    def _build_grids(
        grid_records: list[dict[str, object]],
        *,
        meta_source_version: str,
        meta_path: Path,
        meta_checksum: str,
        point_labels: dict[str, str] | None = None,
    ) -> list[RobotPoint]:
        """Expand affine grid records (如货架库位) into taught-equivalent slot points.

        每个 grid: 由 >=3 个角点 (anchors) 解 6 分量仿射平面 (见 point_grid), 再对每个
        slot 叠加静态 offset 得 6DOF 位姿; offset 播种为 示教值−网格值 → 精确复现原示教
        点 (零位移迁移)。产出点以 slot.name (如 P25) 命名, 作基点级注入, operation 与
        offset 派生接近点照旧引用。计算库位无 joint, 仅 move_l (与货架流程一致)。
        重标货架 = 只改 anchors 位姿 (整架随之走); 单库位微调 = 只改该 slot 的 offset。
        """
        from eit_ptlc.controller.point_grid import (
            GridAnchor,
            grid_pose,
            solve_grid_planes,
        )

        points: list[RobotPoint] = []
        for grid in grid_records:
            if not isinstance(grid, dict):
                raise ValueError("grid record must be a JSON object")
            gid = str(grid.get("id", "grid"))
            anchors_raw = grid.get("anchors")
            slots_raw = grid.get("slots")
            if not isinstance(anchors_raw, list) or len(anchors_raw) < 3:
                raise ValueError(f"grid {gid} requires >=3 anchors")
            if not isinstance(slots_raw, list) or not slots_raw:
                raise ValueError(f"grid {gid} requires a non-empty slots array")
            anchors: list[GridAnchor] = []
            for a in anchors_raw:
                pose = tuple(float(v) for v in a["pose"])
                if len(pose) != 6:
                    raise ValueError(f"grid {gid} anchor pose must contain six values")
                anchors.append(GridAnchor(int(a["row"]), int(a["col"]), pose))
            planes = solve_grid_planes(anchors)

            g_ws = str(grid.get("workstation", "unknown"))
            g_role = str(grid.get("role", "target"))
            g_user = int(grid.get("user", 0))
            g_tool = int(grid.get("tool", 1))
            g_rail = grid.get("rail")  # 网格级地轨槽 (整架同槽, 如货架=位6); 可被 slot 级覆盖
            for s in slots_raw:
                name = str(s["name"])
                row, col = int(s["row"]), int(s["col"])
                offset = tuple(float(v) for v in s.get("offset", (0.0,) * 6))
                if len(offset) != 6:
                    raise ValueError(f"grid {gid} slot {name} offset must contain six values")
                pose = grid_pose(planes, row, col, offset)
                alias = str(s.get("alias", name))
                slot_rail = s.get("rail", g_rail)  # slot 级优先, 否则继承网格级
                point = RobotPoint(
                    point_id=str(s.get("point_id", f"robot-main.{PointRegistry._slug(alias)}")),
                    source_id=str(s.get("id", f"grid:{gid}:{name}")),
                    robot_name=name,
                    alias=alias,
                    workstation=str(s.get("workstation", g_ws)),
                    role=str(s.get("role", g_role)),
                    pose=pose,
                    joint=None,
                    rail=None if slot_rail is None else int(slot_rail),
                    user=int(s.get("user", g_user)),
                    tool=int(s.get("tool", g_tool)),
                    acc=int(s.get("acc", 20)),
                    vel=int(s.get("vel", 20)),
                    cp=int(s.get("cp", 0)),
                    allowed_motion=tuple(str(v) for v in s.get("allowed_motion", ("move_l",))),
                    status=str(s.get("status", "validated")),
                    source_file=str(meta_path),
                    source_version=meta_source_version,
                    source_sha256=meta_checksum,
                    calibrated_at=s.get("calibrated_at"),
                    notes=str(s.get("notes", grid.get("notes", ""))),
                    derived_from=str(s.get("derived_from", gid)),
                    derivation=str(s.get("derivation", f"grid_affine({gid}: r{row}c{col})")),
                    label=(point_labels or {}).get(name, ""),
                )
                PointRegistry._validate_normalized(point)
                points.append(point)
        return points

    @staticmethod
    def _build_supplemental(
        records: list[dict[str, object]],
        source_points: list[RobotPoint],
        *,
        meta_source_version: str,
        meta_path: Path,
        meta_checksum: str,
        derived_labels: dict[str, str] | None = None,
        label_suffixes: dict[str, str] | None = None,
    ) -> list[RobotPoint]:
        """Build supplement RobotPoints with offset resolution against source points.

        接受两种写法: 完整记录 (全字段), 或精简派生点 (仅 point_id/base_point/offset/
        workstation/role); 缺省元数据按默认补全, user/tool 继承 base 示教点. 二者
        生成结果与历史 with_derived_points 路径等价.
        """
        source_by_name: dict[str, RobotPoint] = {p.robot_name: p for p in source_points}
        points: list[RobotPoint] = []

        for record in records:
            if not isinstance(record, dict) or "point_id" not in record:
                raise ValueError("invalid supplement point record in meta (missing point_id)")
            if "workstation" not in record or "role" not in record:
                raise ValueError(
                    f"supplement point {record['point_id']} requires workstation and role"
                )

            base: RobotPoint | None = None
            base_point_name = record.get("base_point")
            has_offset = (
                base_point_name is not None
                and isinstance(base_point_name, str)
                and base_point_name != ""
            )

            if has_offset:
                if "offset" not in record:
                    raise ValueError(
                        f"supplement point {record['point_id']} 声明了 base_point 但缺少 offset"
                    )
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

            # 地轨槽: 显式声明优先, 否则从 base 示教点继承 (offset 派生点随 base 走; 无 base 的显式 pose 点默认 None)
            if record.get("rail") is not None:
                rail = int(record["rail"])
            else:
                rail = base.rail if base is not None else None
            point_id = str(record["point_id"])
            role = str(record["role"])
            label = (derived_labels or {}).get(point_id) or PointRegistry._derive_label(
                base.label if base is not None else "", point_id, role, label_suffixes
            )
            point = RobotPoint(
                point_id=point_id,
                source_id=str(record.get("source_id", f"derived:{record['point_id']}")),
                robot_name=str(record.get("robot_name", f"DERIVED__{record['point_id']}")),
                alias=str(record.get("alias", record["point_id"])),
                workstation=str(record["workstation"]),
                role=role,
                label=label,
                pose=pose,
                joint=joint,
                rail=rail,
                safe_anchor=bool(record.get("safe_anchor", False)),
                user=int(record.get("user", base.user if base is not None else 0)),
                tool=int(record.get("tool", base.tool if base is not None else 1)),
                acc=int(record.get("acc", 20)),
                vel=int(record.get("vel", 20)),
                cp=int(record.get("cp", 0)),
                allowed_motion=tuple(str(v) for v in record.get("allowed_motion", ("move_l",))),
                # 派生点省略 status 即视为 validated + move_l (确定性几何派生: 已验证基点+纯平移offset、rx/ry/rz强制0, 无需逐点示教确认)。示教点不走此默认。
                status=str(record.get("status", "validated")),
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
        if point.rail is not None and point.rail not in (1, 2, 3, 4, 5, 6):
            raise ValueError(f"invalid rail slot for {point.robot_name}: {point.rail} (须 1-6 或 null)")
        if point.safe_anchor and point.status != "validated":
            raise ValueError(f"safe_anchor 点 {point.robot_name} 必须为 validated (当前 {point.status})")

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
