#!/usr/bin/env python3
"""孔板点位仿射离线测试
======================
功能:
    校验 plate_affine: 3 标定点解 2D 仿射 (轴对齐/旋转/最小二乘均能恢复),
    退化(共线)/点数不足/孔越界抛错, 孔序与标签往返正确。
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.plate_affine import (  # noqa: E402
    WELL_PLATE_24,
    WELL_PLATE_96,
    AffineTransform,
    CalibrationPoint,
    PlateType,
    Well,
    compute_targets,
    solve_affine,
    well_at,
    well_label,
    well_number,
    wells_in_order,
)


def _apply_exact(t: AffineTransform, col: float, row: float) -> tuple[float, float]:
    """不 round 的应用 (构造 ground-truth 标定点用)。"""
    return (t.a11 * col + t.a12 * row + t.tx, t.a21 * col + t.a22 * row + t.ty)


def _calib_from(truth: AffineTransform, wells) -> list[CalibrationPoint]:
    return [CalibrationPoint(w, *_apply_exact(truth, w.col, w.row)) for w in wells]


def _rotation(pitch_x: float, pitch_y: float, theta: float, ox: float, oy: float) -> AffineTransform:
    """构造旋转 theta、行列间距 (pitch_x, pitch_y)、平移 (ox, oy) 的真值仿射。"""
    c, s = math.cos(theta), math.sin(theta)
    return AffineTransform(
        a11=pitch_x * c, a12=-pitch_y * s, tx=ox,
        a21=pitch_x * s, a22=pitch_y * c, ty=oy,
    )


class SolveAffineTests(unittest.TestCase):
    def _assert_recovers(self, plate: PlateType, truth: AffineTransform, wells) -> None:
        solved = solve_affine(plate, _calib_from(truth, wells))
        for w in wells_in_order(plate):
            gx, gy = _apply_exact(truth, w.col, w.row)
            sx, sy = solved.apply(w.col, w.row)
            self.assertAlmostEqual(sx, gx, places=3, msg=f"X@{w}")
            self.assertAlmostEqual(sy, gy, places=3, msg=f"Y@{w}")

    def test_axis_aligned_recovery(self) -> None:
        # 轴对齐: a12=a21=0, 仅平移+行列间距
        truth = AffineTransform(a11=19.3, a12=0.0, tx=120.0,
                                a21=0.0, a22=19.3, ty=55.0)
        self._assert_recovers(WELL_PLATE_24, truth, WELL_PLATE_24.calib_wells)

    def test_rotated_recovery(self) -> None:
        # 含旋转 7°: 3 角点仍精确恢复, 验证非轴对齐鲁棒
        truth = _rotation(19.3, 19.3, math.radians(7.0), ox=120.0, oy=55.0)
        self._assert_recovers(WELL_PLATE_24, truth, WELL_PLATE_24.calib_wells)

    def test_anisotropic_skew_recovery(self) -> None:
        # 列行间距不等 + 错切: 仍是仿射, 应精确恢复
        truth = AffineTransform(a11=18.0, a12=1.2, tx=-30.0,
                                a21=0.5, a22=20.5, ty=200.0)
        self._assert_recovers(WELL_PLATE_24, truth, WELL_PLATE_24.calib_wells)

    def test_least_squares_with_extra_points(self) -> None:
        # 4 个点带微小噪声 → 最小二乘解贴近真值
        truth = AffineTransform(a11=19.3, a12=0.0, tx=120.0,
                                a21=0.0, a22=19.3, ty=55.0)
        wells = [Well(1, 1), Well(1, 6), Well(4, 1), Well(4, 6)]
        pts = _calib_from(truth, wells)
        noisy = [CalibrationPoint(p.well, p.x_mm + d, p.y_mm - d)
                 for p, d in zip(pts, (0.02, -0.02, 0.01, -0.01))]
        solved = solve_affine(WELL_PLATE_24, noisy)
        for w in (Well(2, 3), Well(3, 5)):
            gx, gy = _apply_exact(truth, w.col, w.row)
            sx, sy = solved.apply(w.col, w.row)
            self.assertAlmostEqual(sx, gx, places=1, msg=f"X@{w}")
            self.assertAlmostEqual(sy, gy, places=1, msg=f"Y@{w}")

    def test_96_well_recovery(self) -> None:
        truth = _rotation(9.0, 9.0, math.radians(-3.0), ox=10.0, oy=10.0)
        self._assert_recovers(WELL_PLATE_96, truth, WELL_PLATE_96.calib_wells)

    def test_collinear_calibration_raises(self) -> None:
        # 同一行的 3 孔逻辑共线 → 退化
        pts = [CalibrationPoint(Well(1, 1), 0.0, 0.0),
               CalibrationPoint(Well(1, 3), 38.6, 0.0),
               CalibrationPoint(Well(1, 5), 77.2, 0.0)]
        with self.assertRaises(ValueError):
            solve_affine(WELL_PLATE_24, pts)

    def test_too_few_points_raises(self) -> None:
        pts = [CalibrationPoint(Well(1, 1), 0.0, 0.0),
               CalibrationPoint(Well(4, 1), 0.0, 57.9)]
        with self.assertRaises(ValueError):
            solve_affine(WELL_PLATE_24, pts)

    def test_out_of_bounds_well_raises(self) -> None:
        pts = [CalibrationPoint(Well(1, 1), 0.0, 0.0),
               CalibrationPoint(Well(1, 6), 96.5, 0.0),
               CalibrationPoint(Well(9, 1), 0.0, 999.0)]  # 9 行越界 (24孔仅4行)
        with self.assertRaises(ValueError):
            solve_affine(WELL_PLATE_24, pts)


class WellOrderLabelTests(unittest.TestCase):
    def test_well_number_roundtrip_row_major(self) -> None:
        total = WELL_PLATE_24.rows * WELL_PLATE_24.cols
        for n in range(1, total + 1):
            self.assertEqual(well_number(WELL_PLATE_24, well_at(WELL_PLATE_24, n)), n)
        self.assertEqual(well_number(WELL_PLATE_24, Well(2, 3)), 9)  # (2-1)*6+3

    def test_well_number_roundtrip_col_major(self) -> None:
        plate = PlateType(name="cm", rows=4, cols=6,
                          calib_wells=(Well(1, 1), Well(1, 6), Well(4, 1)),
                          row_major=False)
        total = plate.rows * plate.cols
        for n in range(1, total + 1):
            self.assertEqual(well_number(plate, well_at(plate, n)), n)
        self.assertEqual(well_number(plate, Well(2, 1)), 2)  # 列优先: (1,1)=1,(2,1)=2

    def test_wells_in_order_row_major(self) -> None:
        wells = wells_in_order(WELL_PLATE_24)
        self.assertEqual(len(wells), 24)
        self.assertEqual(wells[0], Well(1, 1))
        self.assertEqual(wells[1], Well(1, 2))   # 行优先: 先扫列
        self.assertEqual(wells[6], Well(2, 1))

    def test_well_label(self) -> None:
        self.assertEqual(well_label(WELL_PLATE_24, Well(1, 1)), "A1")
        self.assertEqual(well_label(WELL_PLATE_24, Well(4, 6)), "D6")
        self.assertEqual(well_label(WELL_PLATE_96, Well(8, 12)), "H12")

    def test_well_label_out_of_bounds_raises(self) -> None:
        with self.assertRaises(ValueError):
            well_label(WELL_PLATE_24, Well(5, 1))


class ComputeTargetsTests(unittest.TestCase):
    def test_count_order_and_values(self) -> None:
        truth = AffineTransform(a11=19.3, a12=0.0, tx=120.0,
                                a21=0.0, a22=19.3, ty=55.0)
        transform = solve_affine(WELL_PLATE_24, _calib_from(truth, WELL_PLATE_24.calib_wells))
        targets = compute_targets(WELL_PLATE_24, transform)
        self.assertEqual(len(targets), 24)
        self.assertEqual(targets[0].label, "A1")
        self.assertEqual(targets[-1].label, "D6")
        # A1 物理目标 = (a11*1 + tx, a22*1 + ty)
        self.assertAlmostEqual(targets[0].x_mm, 19.3 + 120.0, places=3)
        self.assertAlmostEqual(targets[0].y_mm, 19.3 + 55.0, places=3)


if __name__ == "__main__":
    unittest.main()
