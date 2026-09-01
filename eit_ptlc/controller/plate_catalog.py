"""孔板类型与标定目录 — 加载 config/plates.yaml + config/calibration.yaml。

职责：
  - 孔板类型：内置常量 (plate_affine.BUILTIN_PLATES) + config/plates.yaml 现场扩展/覆盖。
  - 标定：每个上样板实例 (工位上 2 个物理位置 → 2 条) 的「类型引用 + 3 个实测点」，
    持久化于 config/calibration.yaml；标定点由操作员 jog 对点读伺服 fActPos 得到。
  - 运行时算点：下发时按业务参数 (实例 + 孔行列) 实时 solve_affine + apply，得物理目标，
    再交执行层逐孔推送 (写 *_Target)。变换按实例缓存，标定变更即失效。

不含 PLC/硬件交互：纯配置 IO + plate_affine 计算，可离线测试。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from eit_ptlc.controller.plate_affine import (
    BUILTIN_PLATES,
    AffineTransform,
    CalibrationPoint,
    PlateType,
    Well,
    WellTarget,
    compute_targets,
    solve_affine,
)

log = logging.getLogger(__name__)


class PlateCatalogError(ValueError):
    """孔板/标定配置解析或使用错误。"""


@dataclass(frozen=True)
class PlateCalibration:
    """一个上样板实例的标定记录。

    slot: 盘位号 (物理位置 1/2); 与 plate_type(规格) 一起唯一确定一块托盘的标定 (见 instance_for)。
    """

    id: str
    label: str
    plate_type: str
    slot: int
    points: tuple[CalibrationPoint, ...]

    @property
    def is_calibrated(self) -> bool:
        return len(self.points) >= 3


# ──────────────────────────────────────────────────────────────────────
# 加载 (内置 + yaml)
# ──────────────────────────────────────────────────────────────────────

def load_plate_types(path: Path | None) -> dict[str, PlateType]:
    """内置规格 + config/plates.yaml (同名覆盖内置, 新名追加)。path 缺省/缺文件→仅内置。"""
    types = dict(BUILTIN_PLATES)
    if path is None or not path.is_file():
        return types
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for d in raw.get("plates", []):
        pt = _parse_plate_type(d)
        types[pt.name] = pt
    return types


def load_calibrations(path: Path | None, plate_types: dict[str, PlateType]) -> dict[str, PlateCalibration]:
    """加载 config/calibration.yaml。path 缺省/缺文件→空目录。引用未知类型即抛错。"""
    if path is None or not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, PlateCalibration] = {}
    for d in raw.get("instances", []):
        c = _parse_calibration(d, plate_types)
        if c.id in out:
            raise PlateCatalogError(f"标定实例 id 重复: {c.id}")
        out[c.id] = c
    return out


def save_calibrations(path: Path, calibrations: dict[str, PlateCalibration]) -> None:
    """回写 calibration.yaml (供 jog 标定采点持久化)。"""
    doc = {
        "version": 1,
        "instances": [
            {
                "id": c.id,
                "label": c.label,
                "plate_type": c.plate_type,
                "slot": c.slot,
                "points": [
                    {"well": [p.well.row, p.well.col], "x_mm": p.x_mm, "y_mm": p.y_mm}
                    for p in c.points
                ],
            }
            for c in calibrations.values()
        ],
    }
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)


def _parse_plate_type(d: dict) -> PlateType:
    try:
        calib_raw = d["calib_wells"]
        calib = tuple(Well(int(r), int(c)) for r, c in calib_raw)
        if len(calib) != 3:
            raise PlateCatalogError(f"孔板 {d.get('name')!r} 的 calib_wells 需恰 3 个, 实际 {len(calib)}")
        return PlateType(
            name=str(d["name"]),
            rows=int(d["rows"]),
            cols=int(d["cols"]),
            calib_wells=calib,  # type: ignore[arg-type]
            row_major=bool(d.get("row_major", True)),
            nominal_pitch_x_mm=_opt_float(d.get("nominal_pitch_x_mm")),
            nominal_pitch_y_mm=_opt_float(d.get("nominal_pitch_y_mm")),
        )
    except PlateCatalogError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise PlateCatalogError(f"孔板类型定义无效: {d!r} ({exc})") from exc


def _parse_calibration(d: dict, plate_types: dict[str, PlateType]) -> PlateCalibration:
    try:
        pid = str(d["id"])
        ptype = str(d["plate_type"])
        slot = int(d.get("slot", 0))   # 盘位号; 缺省 0 = 未指定 (instance_for 不会命中)
    except (KeyError, TypeError, ValueError) as exc:
        raise PlateCatalogError(f"标定记录缺 id/plate_type 或 slot 非整数: {d!r}") from exc
    if ptype not in plate_types:
        raise PlateCatalogError(f"标定 {pid} 引用未知孔板类型 {ptype!r} (已知: {sorted(plate_types)})")
    plate = plate_types[ptype]
    points = []
    for p in d.get("points") or []:
        try:
            row, col = p["well"]
            well = Well(int(row), int(col))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlateCatalogError(f"标定 {pid} 的点 well 无效: {p!r}") from exc
        if not (1 <= well.row <= plate.rows and 1 <= well.col <= plate.cols):
            raise PlateCatalogError(f"标定 {pid} 的孔 {well} 越界 {ptype}")
        points.append(CalibrationPoint(well, float(p["x_mm"]), float(p["y_mm"])))
    return PlateCalibration(pid, str(d.get("label", pid)), ptype, slot, tuple(points))


def _opt_float(v) -> float | None:
    return None if v is None else float(v)


# ──────────────────────────────────────────────────────────────────────
# 目录 (类型 + 标定 + 运行时算点)
# ──────────────────────────────────────────────────────────────────────

class PlateCatalog:
    """聚合孔板类型与标定，按实例缓存仿射变换，对外算每孔物理目标。"""

    def __init__(self, plate_types: dict[str, PlateType], calibrations: dict[str, PlateCalibration]):
        self._types = plate_types
        self._calibs = calibrations
        self._transforms: dict[str, AffineTransform] = {}

    @classmethod
    def load(cls, plates_path: Path | None, calibration_path: Path | None) -> "PlateCatalog":
        types = load_plate_types(plates_path)
        calibs = load_calibrations(calibration_path, types)
        return cls(types, calibs)

    # —— 查询 ——
    def plate_types(self) -> dict[str, PlateType]:
        return dict(self._types)

    def instances(self) -> list[PlateCalibration]:
        return list(self._calibs.values())

    def instance(self, instance_id: str) -> PlateCalibration:
        if instance_id not in self._calibs:
            raise PlateCatalogError(f"未知标定实例: {instance_id}")
        return self._calibs[instance_id]

    def instance_for(self, plate_type: str, slot: int) -> PlateCalibration:
        """按 (规格 plate_type × 盘位号 slot) 定位标定实例 (吸液动作据此取标定算 xy)。

        参数:
            plate_type: 孔板规格名 (如 "4×6"/"6×8"), 与动作参数 plate_spec 同值。
            slot: 盘位号 (1/2), 与动作参数 plate_no 同值。
        返回:
            匹配的 PlateCalibration。
        Raises:
            PlateCatalogError: 无 (规格, 盘位号) 对应实例 (calibration.yaml 未登记)。
        """
        for c in self._calibs.values():
            if c.plate_type == plate_type and c.slot == slot:
                return c
        raise PlateCatalogError(
            f"无标定实例匹配 规格={plate_type!r} 盘位号={slot} (请在 calibration.yaml 添加并标定)")

    def is_calibrated(self, instance_id: str) -> bool:
        return self.instance(instance_id).is_calibrated

    # —— 算点 ——
    def transform(self, instance_id: str) -> AffineTransform:
        if instance_id not in self._transforms:
            calib = self.instance(instance_id)
            if not calib.is_calibrated:
                raise PlateCatalogError(
                    f"实例 {instance_id} 未标定 (需 3 点, 现 {len(calib.points)})")
            self._transforms[instance_id] = solve_affine(
                self._types[calib.plate_type], list(calib.points))
        return self._transforms[instance_id]

    def well_target(self, instance_id: str, well: Well) -> tuple[float, float]:
        """业务参数 (实例 + 孔) → 物理目标 (X_4X, Y_3Y) mm。下发时实时调用。"""
        calib = self.instance(instance_id)
        plate = self._types[calib.plate_type]
        if not (1 <= well.row <= plate.rows and 1 <= well.col <= plate.cols):
            raise PlateCatalogError(f"孔 {well} 越界 {calib.plate_type}")
        return self.transform(instance_id).apply(well.col, well.row)

    def targets(self, instance_id: str) -> list[WellTarget]:
        """该实例全部孔的物理目标 (按孔序)。"""
        calib = self.instance(instance_id)
        return compute_targets(self._types[calib.plate_type], self.transform(instance_id))

    # —— 标定采点 (jog 对点后调用; 不在此读硬件) ——
    def validate_calibration(self, instance_id: str, points: list[CalibrationPoint]) -> AffineTransform:
        """纯函数式校验候选标定: 检查孔界 + 点数 + solve 一次。

        不触碰共享状态 (`_calibs`/`_transforms`); 退化/不足/越界即抛, 通过则返回算得的变换。
        供 commit "先校验后提交" 用, 避免退化输入污染内存中已可用的标定 (无回滚)。
        """
        old = self.instance(instance_id)
        plate = self._types[old.plate_type]
        for p in points:
            if not (1 <= p.well.row <= plate.rows and 1 <= p.well.col <= plate.cols):
                raise PlateCatalogError(f"标定孔 {p.well} 越界 {old.plate_type}")
        if len(points) < 3:
            raise PlateCatalogError(f"实例 {instance_id} 标定需 3 点, 现 {len(points)}")
        return solve_affine(plate, list(points))  # 共线/退化在此抛, 不写共享状态

    def set_calibration(self, instance_id: str, points: list[CalibrationPoint]) -> PlateCalibration:
        """更新某实例的标定点并使变换缓存失效 (调用方随后 save_calibrations 持久化)。"""
        old = self.instance(instance_id)
        plate = self._types[old.plate_type]
        for p in points:
            if not (1 <= p.well.row <= plate.rows and 1 <= p.well.col <= plate.cols):
                raise PlateCatalogError(f"标定孔 {p.well} 越界 {old.plate_type}")
        updated = PlateCalibration(old.id, old.label, old.plate_type, old.slot, tuple(points))
        self._calibs[instance_id] = updated
        self._transforms.pop(instance_id, None)
        return updated
