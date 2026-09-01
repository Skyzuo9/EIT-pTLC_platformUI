#!/usr/bin/env python3
"""泵档持久化配置 (config.pump) 离线测试
========================================
两道守护 (spec 2026-07-14-pump-defaults-config-design):
    ParsePumpTests           — _parse_pump 校验器: 未知键拒绝 / 范围守卫 / 缺键合法。
    PumpDefaultsProviderTests — profiles provider 三层回退链:
        knob 传值 > config.pump 持久值 > translator 常量; provider 抛异常回退不阻断。

运行:
    & E:/Anaconda/envs/platformupper/python.exe -m pytest \
      eit_ptlc/tests/test_pump_defaults_config_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import _parse_pump  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import profiles  # noqa: E402


class ParsePumpTests(unittest.TestCase):
    def test_valid_full_section(self):
        out = _parse_pump({
            "sampling": {"asp_speed": 250, "disp_speed": 100, "spot_disp_speed": 50,
                         "step_delay": 1500, "flush_disp_speed": 300,
                         "spot_head_disp_speed": 100},
            "collect": {"asp_speed": 500, "disp_speed": 500, "step_delay": 1000},
            "develop": {"asp_speed": 100, "disp_speed": 100, "step_delay": 500},
        })
        self.assertEqual(out["sampling"]["asp_speed"], 250)
        self.assertEqual(out["collect"]["step_delay"], 1000)
        self.assertEqual(out["develop"]["disp_speed"], 100)

    def test_empty_missing_and_none_ok(self):
        # 空段 / None / 缺工位 / 键值为 null 均合法 (回退常量)
        self.assertEqual(_parse_pump({}), {})
        self.assertEqual(_parse_pump(None), {})
        self.assertEqual(_parse_pump({"collect": {}}), {})
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": None}}), {})

    def test_unknown_station_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"smapling": {"asp_speed": 250}})   # 工位名拼写错误

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_sped": 500}})      # 参数名拼写错误
        with self.assertRaises(ValueError):
            # flush 键只属 sampling, 出现在 develop 是错误
            _parse_pump({"develop": {"flush_disp_speed": 300}})

    def test_speed_bounds(self):
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": {"asp_speed": 0}})      # 下限 1
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": {"disp_speed": 501}})   # PLC 守卫上限 500
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": 1}})["sampling"]["asp_speed"], 1)
        self.assertEqual(_parse_pump({"sampling": {"asp_speed": 500}})["sampling"]["asp_speed"], 500)

    def test_step_delay_bounds(self):
        self.assertEqual(_parse_pump({"develop": {"step_delay": 0}})["develop"]["step_delay"], 0)
        with self.assertRaises(ValueError):
            _parse_pump({"develop": {"step_delay": -1}})
        with self.assertRaises(ValueError):
            _parse_pump({"develop": {"step_delay": 60001}})

    def test_non_integer_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_speed": "fast"}})
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_speed": 250.5}})   # 非整浮点拒绝 (防静默截断)
        with self.assertRaises(ValueError):
            _parse_pump({"collect": {"asp_speed": True}})   # bool 是 int 子类, 须显式拒绝
        # 整值浮点可接受 (前端 number 输入可能送 250.0)
        self.assertEqual(_parse_pump({"collect": {"asp_speed": 250.0}})["collect"]["asp_speed"], 250)

    def test_non_mapping_rejected(self):
        with self.assertRaises(ValueError):
            _parse_pump({"sampling": [250]})
        with self.assertRaises(ValueError):
            _parse_pump("pump")


class PumpDefaultsProviderTests(unittest.TestCase):
    """三层回退链: knob 传值 > config.pump (provider) > translator 常量。

    provider 是 profiles 模块级状态 —— 每个用例 tearDown 必须复位, 防跨用例污染。
    """

    def tearDown(self):
        profiles.set_pump_defaults_provider(None)

    def test_knob_value_beats_config(self):
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"asp_speed": 111}})
        out = profiles._speed_kwargs({"asp_speed": 222}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {"asp_speed": 222})

    def test_config_beats_constant(self):
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"asp_speed": 111}})
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {"asp_speed": 111})

    def test_missing_key_falls_back_to_constant(self):
        # config 缺键 → 不传 kwarg → translator 函数签名常量兜底 (行为与历史一致)
        profiles.set_pump_defaults_provider(lambda: {"sampling": {}})
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {})

    def test_no_provider_falls_back_to_constant(self):
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "collect")
        self.assertEqual(out, {})

    def test_provider_error_falls_back_not_raises(self):
        def boom():
            raise RuntimeError("yaml 损坏")
        profiles.set_pump_defaults_provider(boom)
        out = profiles._speed_kwargs({"asp_speed": None}, {"asp_speed": "asp_speed"}, "sampling")
        self.assertEqual(out, {})   # 回退常量, 不抛出、不阻断派发

    def test_spot_handwritten_fallback_uses_config(self):
        # sampling.spot 的 spot_disp_speed 绕过 _speed_kwargs 的手写回退, 须同样接 config
        profiles.set_pump_defaults_provider(lambda: {"sampling": {"spot_disp_speed": 77}})
        channels = profiles.PUMP_PROFILES["sampling.spot"].build({"sample_volume_ml": 1.0})
        self.assertTrue(
            any("V77" in cmd for cmd in channels["Sampling_dispense_instructions"]),
            f"点样指令未用 config 打速 77: {channels['Sampling_dispense_instructions']}")

    def test_spot_band_layer_handwritten_fallback_uses_config(self):
        profiles.set_pump_defaults_provider(
            lambda: {"sampling": {"spot_disp_speed": 66, "step_delay": 123}})
        channels = profiles.PUMP_PROFILES["sampling.spot_band_layer"].build(
            {"spot_speed_mm_s": 1.0, "dry_speed_mm_s": 2.0, "dry_cycles": 1})
        cmd = channels["Sampling_band_run_instruction"]
        self.assertIn("V66", cmd)
        self.assertIn("M123", cmd)

    def test_hint_follows_config_live(self):
        profiles.set_pump_defaults_provider(lambda: {"develop": {"asp_speed": 123}})
        self.assertEqual(profiles.pump_default_hint("develop", "asp_speed"), 123)
        # config 缺键 → 常量兜底
        self.assertEqual(profiles.pump_default_hint("develop", "disp_speed"), dt.DISP_SPEED)
        # 撤销 provider → 全部回常量
        profiles.set_pump_defaults_provider(None)
        self.assertEqual(profiles.pump_default_hint("develop", "asp_speed"), dt.ASP_SPEED)
        # 非泵工位/非泵参数仍返回 None
        self.assertIsNone(profiles.pump_default_hint("robot", "asp_speed"))
        self.assertIsNone(profiles.pump_default_hint("collect", "wash_volume_ml"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
