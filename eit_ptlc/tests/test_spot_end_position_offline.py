#!/usr/bin/env python3
"""点样活塞终点位置(死体积补偿)离线测试
=============================================
守护 spec 2026-07-14-spot-end-position:
    - 换算助手 spot_band_end_steps: mL->步 (25mL=6000步), 0..5mL 闭区间越界 ValueError;
    - build_dispense_all_cmd 新增 keyword-only end_steps, 缺省 0 时指令串与旧版逐字相等;
    - build_spot_band_run_cmd 新增 end_position_ml, 指令 A{N} 与 spot_band_end_steps 同源;
    - profiles builder 消费 spot_end_position_ml, 节点 Sampling_band_end_position 与指令同源。

运行:
    & E:/Anaconda/envs/platformupper/python.exe -m pytest \
      eit_ptlc/tests/test_spot_end_position_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eit_ptlc.config.loader import _parse_pump
from eit_ptlc.tools.pump import profiles
from eit_ptlc.tools.pump import sample_translator as s1
from eit_ptlc.tools.pump import sample_translator_v2 as s2
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES


class TranslatorEndPositionTests(unittest.TestCase):
    def test_end_steps_conversion(self):
        self.assertEqual(s2.spot_band_end_steps(0.0), 0)
        self.assertEqual(s2.spot_band_end_steps(1.0), 240)   # 1mL × 6000/25
        self.assertEqual(s2.spot_band_end_steps(5.0), 1200)

    def test_end_steps_out_of_range(self):
        for bad in (-0.1, 5.01):
            with self.assertRaises(ValueError):
                s2.spot_band_end_steps(bad)

    def test_dispense_all_default_verbatim_unchanged(self):
        old = f"/4V50I{s1.OUTPUT_PORT}A0M{s1.STEP_DELAY}R\r"
        self.assertEqual(s1.build_dispense_all_cmd("4", 50), old)
        self.assertEqual(s1.build_dispense_all_cmd("4", 50, end_steps=0), old)

    def test_dispense_all_end_steps(self):
        cmd = s1.build_dispense_all_cmd("4", 50, end_steps=240)
        self.assertIn("A240M", cmd)
        self.assertNotIn("A0M", cmd)

    def test_spot_band_run_cmd_default_verbatim_unchanged(self):
        self.assertEqual(s2.build_spot_band_run_cmd(),
                         s2.build_spot_band_run_cmd(end_position_ml=0.0))
        self.assertIn("A0M", s2.build_spot_band_run_cmd())

    def test_spot_band_run_cmd_end_position(self):
        cmd = s2.build_spot_band_run_cmd(end_position_ml=1.0)
        self.assertIn(f"A{s2.spot_band_end_steps(1.0)}M", cmd)

    def test_spot_band_run_cmd_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            s2.build_spot_band_run_cmd(end_position_ml=5.5)


class BandLayerBuilderTests(unittest.TestCase):
    """点样分层的通道构建 (断言的是**未注入 config.pump provider** 时的回退语义).

    ⚠ set_pump_defaults_provider 是**进程级全局**: 任何起过 app 的测试 (bootstrap
    的 lifespan 会注入它) 都会把 config.pump 的持久档带进来, 其中 sampling 的
    spot_end_position_ml=1.125 会顶掉这里期望的回退值 0。本类因此必须自己钉住该
    全局 —— 否则测试结果取决于 pytest 的文件执行顺序 (曾真的因新增测试文件
    改变顺序而由绿转红)。
    """

    _BASE = {"ref_spot": "spot_pose", "spot_disp_speed": None, "step_delay": None,
             "spot_speed_mm_s": 5.0, "dry_speed_mm_s": 20.0, "dry_cycles": 1}

    def setUp(self):
        self._saved_provider = profiles._pump_defaults_provider
        profiles.set_pump_defaults_provider(None)

    def tearDown(self):
        profiles.set_pump_defaults_provider(self._saved_provider)

    def _build(self, **extra):
        values = dict(self._BASE)
        values.update(extra)
        return PUMP_PROFILES["sampling.spot_band_layer"].build(values)

    def test_default_end_position_zero(self):
        ch = self._build(spot_end_position_ml=None)
        self.assertEqual(ch["Sampling_band_end_position"], 0)
        self.assertIn("A0M", ch["Sampling_band_run_instruction"])

    def test_end_position_same_source(self):
        ch = self._build(spot_end_position_ml=1.0)
        self.assertEqual(ch["Sampling_band_end_position"], 240)
        self.assertIn("A240M", ch["Sampling_band_run_instruction"])


class SpotEndConfigTierTests(unittest.TestCase):
    """config.pump 层 (三层链中间层): validator float 键 + builder 回退 + hint 同源。"""

    _BASE = {"ref_spot": "spot_pose", "spot_disp_speed": None, "step_delay": None,
             "spot_speed_mm_s": 5.0, "dry_speed_mm_s": 20.0, "dry_cycles": 1}

    def tearDown(self):
        profiles.set_pump_defaults_provider(None)

    def _build(self, **extra):
        values = dict(self._BASE)
        values.update(extra)
        return PUMP_PROFILES["sampling.spot_band_layer"].build(values)

    def test_parse_pump_accepts_float_spot_end(self):
        out = _parse_pump({"sampling": {"spot_end_position_ml": 1.5}})
        self.assertEqual(out["sampling"]["spot_end_position_ml"], 1.5)
        # 整数/0 也合法, 统一存 float
        out0 = _parse_pump({"sampling": {"spot_end_position_ml": 0}})
        self.assertEqual(out0["sampling"]["spot_end_position_ml"], 0.0)
        self.assertIsInstance(out0["sampling"]["spot_end_position_ml"], float)

    def test_parse_pump_rejects_bad_spot_end(self):
        for bad in (5.01, -0.1, True, "abc"):
            with self.assertRaises(ValueError):
                _parse_pump({"sampling": {"spot_end_position_ml": bad}})

    def test_parse_pump_speed_keys_still_integer_only(self):
        # 回归: float 分支不得放松速度键的整数约束
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": {"asp_speed": 250.5}})

    def test_builder_falls_back_to_config(self):
        profiles.set_pump_defaults_provider(
            lambda: {"sampling": {"spot_end_position_ml": 1.0}})
        ch = self._build(spot_end_position_ml=None)
        self.assertEqual(ch["Sampling_band_end_position"], 240)
        self.assertIn("A240M", ch["Sampling_band_run_instruction"])

    def test_knob_overrides_config(self):
        profiles.set_pump_defaults_provider(
            lambda: {"sampling": {"spot_end_position_ml": 1.0}})
        ch = self._build(spot_end_position_ml=0.5)
        self.assertEqual(ch["Sampling_band_end_position"], 120)

    def test_no_provider_falls_back_to_zero(self):
        ch = self._build(spot_end_position_ml=None)
        self.assertEqual(ch["Sampling_band_end_position"], 0)

    def test_hint_follows_config(self):
        self.assertEqual(profiles.pump_default_hint("sampling", "spot_end_position_ml"), 0.0)
        profiles.set_pump_defaults_provider(
            lambda: {"sampling": {"spot_end_position_ml": 2.0}})
        self.assertEqual(profiles.pump_default_hint("sampling", "spot_end_position_ml"), 2.0)

    def test_app_yaml_seed_parses(self):
        import yaml
        root = Path(__file__).resolve().parents[1]
        raw = yaml.safe_load((root / "config" / "app.yaml").read_text(encoding="utf-8"))
        cleaned = _parse_pump(raw.get("pump"))
        # 对照文件原始值而非钉死常量: 该值为真机标定定值, 会随重标定变化
        seed = float(raw["pump"]["sampling"]["spot_end_position_ml"])
        self.assertEqual(cleaned["sampling"]["spot_end_position_ml"], seed)
        self.assertTrue(0.0 <= seed <= 5.0)


if __name__ == "__main__":
    unittest.main()
