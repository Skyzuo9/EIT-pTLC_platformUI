#!/usr/bin/env python3
"""标定提交次序离线测试 (#3 先校验后提交)
======================================
功能:
    验证 CalibrationService.commit / PlateCatalog.validate_calibration 的
    "先纯函数式 solve 校验, 通过才改共享状态" 次序: 退化(共线)输入被拒,
    且**不污染**内存中原本可用的标定 (该实例后续 transform/well_target 仍正常)。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.calibration_service import CalibrationService  # noqa: E402
from eit_ptlc.controller.plate_affine import CalibrationPoint, Well  # noqa: E402
from eit_ptlc.controller.plate_catalog import PlateCatalog  # noqa: E402

_CFG = _PKG / "config"

# 轴对齐 24孔标定 (A1/A6/D1 不共线, pitch 19.3, 原点 tx=120/ty=55)
_GOOD = [
    CalibrationPoint(Well(1, 1), 139.3, 74.3),
    CalibrationPoint(Well(1, 6), 235.8, 74.3),
    CalibrationPoint(Well(4, 1), 139.3, 132.2),
]
# 逻辑网格共线 (同一行 → 退化, solve_affine 必抛 ValueError)
_COLLINEAR = [
    CalibrationPoint(Well(1, 1), 10.0, 10.0),
    CalibrationPoint(Well(1, 2), 20.0, 10.0),
    CalibrationPoint(Well(1, 3), 30.0, 10.0),
]


class CommitOrderTests(unittest.TestCase):
    def _service(self, d: Path) -> tuple[CalibrationService, PlateCatalog]:
        # 起始用仓库 calibration.yaml (plate_6x8_1 未标定, points: [])
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        svc = CalibrationService(cat, None, d / "calibration.yaml")
        return svc, cat

    def test_collinear_commit_rejected_and_keeps_old(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            svc, cat = self._service(Path(d))
            # 先提交一组合法标定 → 后续可算点
            svc.commit("plate_6x8_1", _GOOD)
            x0, y0 = cat.well_target("plate_6x8_1", Well(1, 1))
            self.assertAlmostEqual(x0, 139.3, places=3)

            # 提交退化(共线)输入 → 抛 ValueError
            with self.assertRaises(ValueError):
                svc.commit("plate_6x8_1", _COLLINEAR)

            # 关键: 原标定未被坏输入覆盖, 仍可用且结果不变
            x1, y1 = cat.well_target("plate_6x8_1", Well(1, 1))
            self.assertAlmostEqual(x1, x0, places=6)
            self.assertAlmostEqual(y1, y0, places=6)
            self.assertEqual(len(cat.instance("plate_6x8_1").points), 3)

    def test_validate_calibration_pure_no_mutation(self) -> None:
        # validate_calibration 退化输入抛错时, 不得触碰 _calibs/_transforms
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        cat.set_calibration("plate_6x8_1", _GOOD)
        cat.transform("plate_6x8_1")  # 暖缓存
        before = cat.instance("plate_6x8_1").points
        with self.assertRaises(ValueError):
            cat.validate_calibration("plate_6x8_1", _COLLINEAR)
        self.assertEqual(cat.instance("plate_6x8_1").points, before)
        # 缓存与算点仍正常
        cat.well_target("plate_6x8_1", Well(2, 2))

    def test_validate_calibration_too_few_points(self) -> None:
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        with self.assertRaises(ValueError):
            cat.validate_calibration("plate_6x8_1", _GOOD[:2])


if __name__ == "__main__":
    unittest.main()
