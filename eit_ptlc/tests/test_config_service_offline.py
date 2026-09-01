#!/usr/bin/env python3
"""设备参数配置服务离线测试
==========================
功能:
    校验 ConfigService 对 app.yaml camera/gcode/vision/pump 段的读取、嵌套合并保存、
    ruamel 注释保留、loader 校验拒绝 (越界不写盘)。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.config_service import ConfigService  # noqa: E402
from eit_ptlc.config.loader import _parse_vision  # noqa: E402

_APP_YAML = """# 顶部注释 (应保留)
control_mode: DEBUG
camera:
  mock: true
  daheng:
    exposure_time: 500000.0  # 曝光注释
    gain: 1.0
gcode:
  plate_surface_z_mm: 5.0
  boustrophedon_columns: 20  # 列数注释
  path_strategy: contour
vision:
  mock: true
  image_plate_orientation: rot0
pump:
  sampling:
    asp_speed: 250  # 泵档注释
    step_delay: 1500
  collect:
    disp_speed: 500
"""


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(_APP_YAML)
            self.tmp = Path(f.name)
        self.svc = ConfigService(self.tmp)

    def tearDown(self):
        if self.tmp.exists():
            self.tmp.unlink()

    def test_read_section(self):
        cam = self.svc.read_section("camera")
        self.assertEqual(cam["daheng"]["exposure_time"], 500000.0)

    def test_parse_vision_rotation_deg(self):
        # 固定 deskew 角: 显式浮点 → float; 缺省 / null → None (回落每帧自动估)
        self.assertEqual(_parse_vision({"image_plate_rotation_deg": -2.43}).image_plate_rotation_deg, -2.43)
        self.assertIsNone(_parse_vision({}).image_plate_rotation_deg)
        self.assertIsNone(_parse_vision({"image_plate_rotation_deg": None}).image_plate_rotation_deg)

    def test_save_gcode_valid_keeps_comments(self):
        self.svc.save_section("gcode", {"plate_surface_z_mm": 9.9})
        self.assertEqual(self.svc.read_section("gcode")["plate_surface_z_mm"], 9.9)
        text = self.tmp.read_text(encoding="utf-8")
        self.assertIn("列数注释", text)   # 注释保留
        self.assertIn("曝光注释", text)
        self.assertIn("顶部注释", text)

    def test_save_gcode_invalid_rejected_not_written(self):
        with self.assertRaises(ValueError):
            self.svc.save_section("gcode", {"boustrophedon_columns": 7})  # 不整除 400
        self.assertEqual(self.svc.read_section("gcode")["boustrophedon_columns"], 20)  # 未改

    def test_save_camera_nested_merge_preserves_siblings(self):
        self.svc.save_section("camera", {"daheng": {"exposure_time": 800000.0}})
        cam = self.svc.read_section("camera")
        self.assertEqual(cam["daheng"]["exposure_time"], 800000.0)
        self.assertEqual(cam["daheng"]["gain"], 1.0)  # 兄弟字段保留

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.read_section("robot")
        with self.assertRaises(ValueError):
            self.svc.save_section("robot", {"x": 1})

    def test_pump_read_and_save_roundtrip_keeps_comments(self):
        self.assertEqual(self.svc.read_section("pump")["sampling"]["asp_speed"], 250)
        self.svc.save_section("pump", {"sampling": {"asp_speed": 300}})
        pump = self.svc.read_section("pump")
        self.assertEqual(pump["sampling"]["asp_speed"], 300)
        self.assertEqual(pump["sampling"]["step_delay"], 1500)   # 兄弟字段保留
        self.assertIn("泵档注释", self.tmp.read_text(encoding="utf-8"))  # 注释保留

    def test_pump_save_invalid_rejected_not_written(self):
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"sampling": {"asp_speed": 501}})  # 越上限
        self.assertEqual(self.svc.read_section("pump")["sampling"]["asp_speed"], 250)  # 未改

    def test_pump_save_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"sampling": {"asp_sped": 300}})  # 拼写错误
        with self.assertRaises(ValueError):
            self.svc.save_section("pump", {"smapling": {"asp_speed": 300}})


if __name__ == "__main__":
    unittest.main()
