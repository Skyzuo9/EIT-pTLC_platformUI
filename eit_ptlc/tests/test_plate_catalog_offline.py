#!/usr/bin/env python3
"""孔板/标定目录离线测试
======================
功能:
    校验 plate_catalog: 内置+yaml 合并孔板类型, 解析/回写 calibration.yaml,
    未标定拒算、已标定 solve+算点、save/load 往返、set_calibration 失效缓存。
    并验证仓库内 config/plates.yaml 与 config/calibration.yaml 能正确解析。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.plate_affine import (  # noqa: E402
    CalibrationPoint,
    Well,
    parse_well,
    well_label,
)
from eit_ptlc.controller.plate_catalog import (  # noqa: E402
    PlateCatalog,
    PlateCatalogError,
    load_calibrations,
    load_plate_types,
    save_calibrations,
)

_CFG = _PKG / "config"

# 轴对齐 24孔标定 (A1/A6/D1, pitch 19.3, 原点 tx=120/ty=55)
_CALIB_24 = [
    CalibrationPoint(Well(1, 1), 139.3, 74.3),
    CalibrationPoint(Well(1, 6), 235.8, 74.3),
    CalibrationPoint(Well(4, 1), 139.3, 132.2),
]

_CALIBRATED_YAML = """\
version: 1
instances:
  - id: sampling_plate_1
    label: "上样板1"
    plate_type: "24-well"
    points:
      - {well: [1, 1], x_mm: 139.3, y_mm: 74.3}
      - {well: [1, 6], x_mm: 235.8, y_mm: 74.3}
      - {well: [4, 1], x_mm: 139.3, y_mm: 132.2}
"""


class PlateTypeLoadTests(unittest.TestCase):
    def test_builtins_only_when_no_file(self) -> None:
        types = load_plate_types(None)
        self.assertIn("24-well", types)
        self.assertIn("96-well", types)

    def test_repo_plates_yaml_parses(self) -> None:
        types = load_plate_types(_CFG / "plates.yaml")
        self.assertEqual(types["4×6"].rows, 4)
        self.assertEqual(types["4×6"].cols, 6)
        self.assertEqual(types["6×8"].rows, 6)
        self.assertEqual(types["6×8"].cols, 8)

    def test_bad_calib_wells_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "plates.yaml"
            p.write_text("plates:\n  - {name: bad, rows: 2, cols: 3, calib_wells: [[1,1],[1,3]]}\n",
                         encoding="utf-8")
            with self.assertRaises(PlateCatalogError):
                load_plate_types(p)


class CalibrationLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.types = load_plate_types(_CFG / "plates.yaml")

    def test_repo_calibration_yaml_parses(self) -> None:
        calibs = load_calibrations(_CFG / "calibration.yaml", self.types)
        self.assertEqual(set(calibs), {"plate_4x6_1", "plate_4x6_2", "plate_6x8_1", "plate_6x8_2"})
        self.assertTrue(calibs["plate_4x6_1"].is_calibrated)   # 4×6 沿用既有 3 点
        self.assertFalse(calibs["plate_6x8_1"].is_calibrated)  # 6×8 出厂未标定 (points: [])
        self.assertEqual(calibs["plate_4x6_1"].slot, 1)
        self.assertEqual(calibs["plate_6x8_2"].slot, 2)

    def test_instance_for_resolves_spec_slot(self) -> None:
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        self.assertEqual(cat.instance_for("4×6", 1).id, "plate_4x6_1")
        self.assertEqual(cat.instance_for("6×8", 2).id, "plate_6x8_2")
        with self.assertRaises(PlateCatalogError):
            cat.instance_for("4×6", 9)    # 无此盘位号
        with self.assertRaises(PlateCatalogError):
            cat.instance_for("nope", 1)   # 无此规格

    def test_unknown_plate_type_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.yaml"
            p.write_text("instances:\n  - {id: x, plate_type: nope, points: []}\n", encoding="utf-8")
            with self.assertRaises(PlateCatalogError):
                load_calibrations(p, self.types)

    def test_calibration_point_out_of_bounds_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "calibration.yaml"
            p.write_text(
                "instances:\n  - id: x\n    plate_type: 24-well\n    points:\n"
                "      - {well: [9, 1], x_mm: 0, y_mm: 0}\n",
                encoding="utf-8")
            with self.assertRaises(PlateCatalogError):
                load_calibrations(p, self.types)


class PlateCatalogComputeTests(unittest.TestCase):
    def _calibrated_catalog(self, tmp: Path) -> PlateCatalog:
        (tmp / "calibration.yaml").write_text(_CALIBRATED_YAML, encoding="utf-8")
        return PlateCatalog.load(_CFG / "plates.yaml", tmp / "calibration.yaml")

    def test_uncalibrated_instance_rejects(self) -> None:
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        self.assertFalse(cat.is_calibrated("plate_6x8_1"))
        with self.assertRaises(PlateCatalogError):
            cat.transform("plate_6x8_1")
        with self.assertRaises(PlateCatalogError):
            cat.well_target("plate_6x8_1", Well(1, 1))

    def test_unknown_instance_raises(self) -> None:
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        with self.assertRaises(PlateCatalogError):
            cat.instance("nope")

    def test_calibrated_well_target(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cat = self._calibrated_catalog(Path(d))
            self.assertTrue(cat.is_calibrated("sampling_plate_1"))
            # B2 = (col2,row2): X=19.3*2+120=158.6, Y=19.3*2+55=93.6
            x, y = cat.well_target("sampling_plate_1", Well(2, 2))
            self.assertAlmostEqual(x, 158.6, places=3)
            self.assertAlmostEqual(y, 93.6, places=3)

    def test_targets_full_plate(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cat = self._calibrated_catalog(Path(d))
            targets = cat.targets("sampling_plate_1")
            self.assertEqual(len(targets), 24)
            self.assertEqual(targets[0].label, "A1")
            self.assertAlmostEqual(targets[0].x_mm, 139.3, places=3)
            self.assertAlmostEqual(targets[0].y_mm, 74.3, places=3)

    def test_well_target_out_of_bounds_raises(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cat = self._calibrated_catalog(Path(d))
            with self.assertRaises(PlateCatalogError):
                cat.well_target("sampling_plate_1", Well(9, 1))


class CalibrationSaveSetTests(unittest.TestCase):
    def test_set_calibration_invalidates_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cal_path = Path(d) / "calibration.yaml"
            # 起始未标定 (仓库 calibration.yaml 的 6×8 实例 points: [])
            cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
            with self.assertRaises(PlateCatalogError):
                cat.transform("plate_6x8_1")
            cat.set_calibration("plate_6x8_1", _CALIB_24)
            self.assertTrue(cat.is_calibrated("plate_6x8_1"))
            x, y = cat.well_target("plate_6x8_1", Well(1, 1))
            self.assertAlmostEqual(x, 139.3, places=3)
            self.assertAlmostEqual(y, 74.3, places=3)
            # 持久化后重载, 点保留 (含 slot)
            save_calibrations(cal_path, {c.id: c for c in cat.instances()})
            types = load_plate_types(_CFG / "plates.yaml")
            reloaded = load_calibrations(cal_path, types)
            self.assertTrue(reloaded["plate_6x8_1"].is_calibrated)
            self.assertEqual(len(reloaded["plate_6x8_1"].points), 3)
            self.assertEqual(reloaded["plate_6x8_1"].slot, 1)

    def test_set_calibration_out_of_bounds_raises(self) -> None:
        cat = PlateCatalog.load(_CFG / "plates.yaml", _CFG / "calibration.yaml")
        with self.assertRaises(PlateCatalogError):
            cat.set_calibration("plate_6x8_1", [CalibrationPoint(Well(99, 1), 0.0, 0.0)])


class ParseWellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plate = load_plate_types(_CFG / "plates.yaml")["4×6"]

    def test_parse_basic(self) -> None:
        self.assertEqual(parse_well(self.plate, "A1"), Well(1, 1))
        self.assertEqual(parse_well(self.plate, "d6"), Well(4, 6))   # 大小写不敏感
        self.assertEqual(parse_well(self.plate, " C3 "), Well(3, 3))  # 容前后空格

    def test_parse_roundtrip_with_label(self) -> None:
        for r in range(1, self.plate.rows + 1):
            for c in range(1, self.plate.cols + 1):
                lbl = well_label(self.plate, Well(r, c))
                self.assertEqual(parse_well(self.plate, lbl), Well(r, c))

    def test_parse_bad_format_raises(self) -> None:
        for bad in ["", "A", "1", "1A", "AB"]:
            with self.assertRaises(ValueError):
                parse_well(self.plate, bad)

    def test_parse_out_of_bounds_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_well(self.plate, "E1")   # 4×6 仅 A-D
        with self.assertRaises(ValueError):
            parse_well(self.plate, "A7")   # 4×6 仅 1-6
        with self.assertRaises(ValueError):
            parse_well(self.plate, "A0")   # 列 0 越界


if __name__ == "__main__":
    unittest.main()
