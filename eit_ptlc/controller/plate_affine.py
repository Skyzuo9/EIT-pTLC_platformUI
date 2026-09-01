"""孔板点位仿射 — 由「耗材类型 + 3 个标定点」算出每孔物理目标 (X, Y)。

职责：
  上位机对每种耗材只维护「类型(行列数/孔序) + 3 个标定点」。操作员人工 jog 到
  3 个已知孔、读伺服实际位置 (fActPos) 得到 3 对「逻辑(行,列) ↔ 物理(mm)」，
  本模块解 2D 仿射 6 参数 `物理 = A·逻辑 + t`，再把任意孔 (行,列) 映射到物理
  (X, Y)。执行时按孔把目标值推送给 PLC (见 docs/伺服地轨控制_架构与实施计划)。

设计要点：
  - 逻辑坐标取 (col, row) 网格 (1-based)，物理取 (X_4X, Y_3Y) mm。仿射的 2×2 部分
    A 同时吸收行列间距、缩放、旋转与错切，故「类型」不必登记物理 mm 间距 —— 3 个
    标定点就完全确定物理嵌入。标称间距仅作可选的标定自检 (此处不强制)。
  - 轴对齐 (孔板与机床轴平行) 时 A 近似对角 (a12≈a21≈0)；含旋转/错切亦正确求解，
    故对孔板未对正、换规格 (24→96 孔) 均鲁棒。
  - ≥3 个标定点：恰 3 点为精确解，>3 点取最小二乘 (numpy.linalg.lstsq)。逻辑上
    共线 (退化) 立即抛 ValueError。
  - 物理坐标统一 round(…, 3) (0.001mm)，与 cnc_path 一致。

数据流：
  标定 UI: jog → 读 *_ActPos → CalibrationPoint × 3
    → solve_affine(plate, points) → AffineTransform
    → compute_targets(plate, T) → [WellTarget(well, x_mm, y_mm), …]
    → 执行层按孔写 Sampling_4X_Target / Sampling_3Y_Target 并触发。
"""

from __future__ import annotations

import logging
import math
import string
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

_RANK_MIN = 3  # 仿射 6 参数需逻辑设计矩阵满秩 (3 列)


@dataclass(frozen=True)
class Well:
    """孔的逻辑地址 (1-based)。row 沿 Y(打样3Y)，col 沿 X(上样4X)。"""

    row: int
    col: int


@dataclass(frozen=True)
class PlateType:
    """孔板逻辑类型 (规格 + 推荐标定孔)。

    物理嵌入由标定点确定，故此处不含 mm 间距 (标称值仅供自检，可缺省)。
    参数:
        name: 规格标识，如 "24-well" / "96-well"。
        rows/cols: 行数(Y)/列数(X)，1-based 取值 [1, rows]/[1, cols]。
        calib_wells: 推荐操作员 jog 对点的 3 个孔 (须逻辑不共线)；仅为指引，
            solve_affine 接受任意给定的 ≥3 个不共线孔。
        row_major: 孔序 True=行优先(A1,A2,…) / False=列优先。
        nominal_pitch_x_mm/nominal_pitch_y_mm: 标称行列间距，仅供标定结果自检。
    """

    name: str
    rows: int
    cols: int
    calib_wells: tuple[Well, Well, Well]
    row_major: bool = True
    nominal_pitch_x_mm: float | None = None
    nominal_pitch_y_mm: float | None = None


@dataclass(frozen=True)
class CalibrationPoint:
    """一个标定点：某逻辑孔 + 其实测物理位置 (mm，取自伺服 fActPos)。"""

    well: Well
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class AffineTransform:
    """2D 仿射：`X = a11·col + a12·row + tx`，`Y = a21·col + a22·row + ty`。"""

    a11: float
    a12: float
    a21: float
    a22: float
    tx: float
    ty: float

    def apply(self, col: float, row: float) -> tuple[float, float]:
        """逻辑 (col, row) → 物理 (X, Y) mm，round 到 0.001mm。"""
        x = self.a11 * col + self.a12 * row + self.tx
        y = self.a21 * col + self.a22 * row + self.ty
        return round(x, 3), round(y, 3)

    @property
    def det(self) -> float:
        """A 的行列式 (≈ 单孔逻辑面积对应的物理面积)；接近 0 表示退化。"""
        return self.a11 * self.a22 - self.a12 * self.a21


@dataclass(frozen=True)
class WellTarget:
    """一个孔的计算结果：逻辑地址 + 标签 + 物理目标 (mm)。"""

    well: Well
    label: str
    x_mm: float
    y_mm: float


# ──────────────────────────────────────────────────────────────────────
# 求解 / 应用
# ──────────────────────────────────────────────────────────────────────

def solve_affine(plate: PlateType, points: list[CalibrationPoint]) -> AffineTransform:
    """由标定点解 2D 仿射变换。

    参数:
        plate: 孔板类型 (用于校验孔在界内)。
        points: ≥3 个标定点 (逻辑孔 ↔ 实测 mm)；恰 3 点精确解，>3 点最小二乘。
    返回:
        AffineTransform。
    Raises:
        ValueError: 标定点不足 3 个 / 孔越界 / 逻辑上共线(退化) 无法确定变换。
    """
    if len(points) < _RANK_MIN:
        raise ValueError(f"标定点需至少 3 个, 实际 {len(points)}")
    for p in points:
        _check_well(plate, p.well)

    design = np.array([[p.well.col, p.well.row, 1.0] for p in points], dtype=float)
    if np.linalg.matrix_rank(design) < _RANK_MIN:
        raise ValueError("标定点在逻辑网格上共线(退化), 无法确定仿射变换; 请取不共线的 3 孔")

    bx = np.array([p.x_mm for p in points], dtype=float)
    by = np.array([p.y_mm for p in points], dtype=float)
    cx, *_ = np.linalg.lstsq(design, bx, rcond=None)  # [a11, a12, tx]
    cy, *_ = np.linalg.lstsq(design, by, rcond=None)  # [a21, a22, ty]

    transform = AffineTransform(
        a11=float(cx[0]), a12=float(cx[1]), tx=float(cx[2]),
        a21=float(cy[0]), a22=float(cy[1]), ty=float(cy[2]),
    )
    _warn_if_off_nominal(plate, transform)
    log.info(
        "[plate_affine] %s 标定完成 n=%d det=%.3f |dx_col|≈%.3fmm |dy_row|≈%.3fmm",
        plate.name, len(points), transform.det,
        math.hypot(transform.a11, transform.a21), math.hypot(transform.a12, transform.a22),
    )
    return transform


def compute_targets(plate: PlateType, transform: AffineTransform) -> list[WellTarget]:
    """按孔序生成全部孔的物理目标 (供执行层逐孔推送)。"""
    return [
        WellTarget(w, well_label(plate, w), *transform.apply(w.col, w.row))
        for w in wells_in_order(plate)
    ]


# ──────────────────────────────────────────────────────────────────────
# 孔序 / 标签 / 校验
# ──────────────────────────────────────────────────────────────────────

def wells_in_order(plate: PlateType) -> list[Well]:
    """按 row_major/col_major 返回全部孔 (1-based)。"""
    if plate.row_major:
        return [Well(r, c) for r in range(1, plate.rows + 1) for c in range(1, plate.cols + 1)]
    return [Well(r, c) for c in range(1, plate.cols + 1) for r in range(1, plate.rows + 1)]


def well_number(plate: PlateType, well: Well) -> int:
    """孔 → 1-based 序号 (按 row_major/col_major)。"""
    _check_well(plate, well)
    if plate.row_major:
        return (well.row - 1) * plate.cols + well.col
    return (well.col - 1) * plate.rows + well.row


def well_at(plate: PlateType, number: int) -> Well:
    """1-based 序号 → 孔 (well_number 的逆)。"""
    total = plate.rows * plate.cols
    if not 1 <= number <= total:
        raise ValueError(f"孔序号 {number} 越界 (1..{total})")
    idx = number - 1
    if plate.row_major:
        return Well(idx // plate.cols + 1, idx % plate.cols + 1)
    return Well(idx % plate.rows + 1, idx // plate.rows + 1)


def well_label(plate: PlateType, well: Well) -> str:
    """孔 → 显示标签，行用字母(A..)、列用数字，如 (1,1)->"A1"。"""
    _check_well(plate, well)
    return f"{_row_letter(well.row)}{well.col}"


def _row_letter(row: int) -> str:
    """行号(1-based) → 字母标签 (1->A … 26->Z, 27->AA …)。"""
    letters = ""
    n = row
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = string.ascii_uppercase[rem] + letters
    return letters


def parse_well(plate: PlateType, label: str) -> Well:
    """孔标签 → 逻辑孔 (well_label 的逆): 字母段=行(A=1), 数字段=列。

    功能:
        把操作员输入的孔编号 (如 "A1"/"d6"/"F8") 解析为 Well(row, col), 并校验在该孔板界内。
    参数:
        plate: 孔板类型 (用于界内校验)。
        label: 孔标签, 形如 字母+数字 (大小写不敏感, 容前后空格)。
    返回:
        Well。
    Raises:
        ValueError: 格式非法 (非 "字母+数字") 或 孔越界 (_check_well 抛出)。
    """
    text = str(label).strip().upper()
    cut = 0
    while cut < len(text) and text[cut].isalpha():
        cut += 1
    letters, digits = text[:cut], text[cut:]
    if not letters or not digits or not digits.isdigit():
        raise ValueError(f"孔编号格式非法: {label!r} (应为 字母+数字, 如 A1)")
    row = 0
    for ch in letters:
        row = row * 26 + (ord(ch) - ord("A") + 1)
    well = Well(row, int(digits))
    _check_well(plate, well)  # 越界即抛 ValueError
    return well


def _check_well(plate: PlateType, well: Well) -> None:
    if not (1 <= well.row <= plate.rows and 1 <= well.col <= plate.cols):
        raise ValueError(
            f"孔 (row={well.row}, col={well.col}) 越界 {plate.name} "
            f"(rows=1..{plate.rows}, cols=1..{plate.cols})"
        )


def _warn_if_off_nominal(plate: PlateType, t: AffineTransform) -> None:
    """若标称间距已知且实测列/行间距偏离 >10%，记 WARN (可能标定点选错孔)。"""
    checks = (
        ("列间距X", plate.nominal_pitch_x_mm, math.hypot(t.a11, t.a21)),
        ("行间距Y", plate.nominal_pitch_y_mm, math.hypot(t.a12, t.a22)),
    )
    for label, nominal, actual in checks:
        if nominal and nominal > 0 and abs(actual - nominal) / nominal > 0.10:
            log.warning(
                "[plate_affine] %s 标定实测%s %.3fmm 偏离标称 %.3fmm >10%%, 请核对标定孔",
                plate.name, label, actual, nominal,
            )


# ──────────────────────────────────────────────────────────────────────
# 内置孔板类型 (现场可经配置扩展; 标定孔取三角不共线)
# ──────────────────────────────────────────────────────────────────────

WELL_PLATE_24 = PlateType(
    name="24-well",
    rows=4,
    cols=6,
    calib_wells=(Well(1, 1), Well(1, 6), Well(4, 1)),
    nominal_pitch_x_mm=19.3,
    nominal_pitch_y_mm=19.3,
)

WELL_PLATE_96 = PlateType(
    name="96-well",
    rows=8,
    cols=12,
    calib_wells=(Well(1, 1), Well(1, 12), Well(8, 1)),
    nominal_pitch_x_mm=9.0,
    nominal_pitch_y_mm=9.0,
)

BUILTIN_PLATES: dict[str, PlateType] = {
    WELL_PLATE_24.name: WELL_PLATE_24,
    WELL_PLATE_96.name: WELL_PLATE_96,
}
