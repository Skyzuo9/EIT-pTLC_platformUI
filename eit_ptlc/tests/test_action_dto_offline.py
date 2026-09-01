#!/usr/bin/env python3
"""动作 DTO default_hint (泵档默认提示) 离线测试
================================================
守护"未覆写时实际执行值"在 DTO 的透出 (派发单 A2 显示侧):
    无 YAML default 的泵速度/延时参数, action_def_to_dto 须把 translator 泵档常量作为
    default_hint 透给前端 (前端据此占位显示真实数字, 而非误导的 0). 断言值直接引用 translator
    常量 (s2/ct/dt.*) -> 常量改了断言跟着变, 证明 default_hint 与执行默认单一真源、不漂移.
    config.pump provider 注入时 hint 跟随持久值 (三层链见 test_pump_defaults_config_offline).
    有默认参数 / 必填参数 default_hint 须为 None.

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
      eit_ptlc/tests/test_action_dto_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.api.dto import action_def_to_dto  # noqa: E402
from eit_ptlc.tools.pump import collect_translator as ct  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import sample_translator_v2 as s2  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"


class ActionDtoHintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)

    def _hints(self, action_name: str) -> dict:
        """取某动作 DTO 各参数的 default_hint (参数名 -> 值)."""
        dto = action_def_to_dto(self.registry.get(action_name))
        return {p.name: p.default_hint for p in dto.params}

    def test_sampling_hints_equal_translator_constants(self) -> None:
        h = self._hints("sampling.clean")
        self.assertEqual(h["asp_speed"], s2.ASP_SPEED)
        self.assertEqual(h["disp_speed"], s2.DISP_SPEED)
        self.assertEqual(h["step_delay"], s2.STEP_DELAY)

    def test_sampling_spot_disp_speed_hint(self) -> None:
        h = self._hints("sampling.spot")
        self.assertEqual(h["asp_speed"], s2.ASP_SPEED)
        self.assertEqual(h["spot_disp_speed"], s2.DEFAULT_DISPENSE_DISP_SPEED)
        self.assertEqual(h["step_delay"], s2.STEP_DELAY)

    def test_collect_hints(self) -> None:
        h = self._hints("collect.collect")
        self.assertEqual(h["asp_speed"], ct.ASP_SPEED)
        self.assertEqual(h["disp_speed"], ct.DISP_SPEED)
        self.assertEqual(h["step_delay"], ct.STEP_DELAY)

    def test_develop_hints(self) -> None:
        h = self._hints("develop.fill")
        self.assertEqual(h["asp_speed"], dt.ASP_SPEED)
        self.assertEqual(h["disp_speed"], dt.DISP_SPEED)
        self.assertEqual(h["step_delay"], dt.STEP_DELAY)

    def test_defaulted_and_required_params_have_no_hint(self) -> None:
        # 有 YAML default 的参数 (wash_volume_ml) 不透 hint
        self.assertIsNone(self._hints("sampling.clean")["wash_volume_ml"])
        # 必填参数 (target_tank) 不透 hint
        self.assertIsNone(self._hints("develop.fill")["target_tank"])

    def test_point_ref_options_filled_from_target_keys(self) -> None:
        # point_ref 参数 (点样合并为组合点位的引用) 的 options 由 target_keys 注入, 供前端渲染点位下拉
        dto = action_def_to_dto(self.registry.get("sampling.spot"), ["photo_8y", "spot_pose"])
        refs = {p.name: p for p in dto.params if p.type == "point_ref"}
        self.assertEqual(set(refs), {"ref_spot"})
        # 取值域统一下发 [{value, label}] (与脚本变量 enum 同形, 前端一个 enumOf 通吃)
        self.assertEqual(refs["ref_spot"].options,
                         [{"value": "photo_8y", "label": "photo_8y"},
                          {"value": "spot_pose", "label": "spot_pose"}])
        # 不传 target_keys 时 options 为空 (前端回退文本输入)
        dto2 = action_def_to_dto(self.registry.get("sampling.spot"))
        self.assertEqual(next(p for p in dto2.params if p.type == "point_ref").options, [])

    def test_preload_targets_visible_in_dto(self) -> None:
        dto = action_def_to_dto(self.registry.get("feedlift.feed_raise"))
        self.assertEqual(dto.preload_targets, ["feedlift_1z_search_low", "feedlift_1z_search_high"])

    def test_hint_follows_pump_config_when_provider_injected(self) -> None:
        # config.pump 有值时 default_hint 透出持久值而非常量 (live-read 同源)
        from eit_ptlc.tools.pump import profiles
        profiles.set_pump_defaults_provider(lambda: {"collect": {"asp_speed": 333}})
        try:
            h = self._hints("collect.collect")
            self.assertEqual(h["asp_speed"], 333)
            self.assertEqual(h["disp_speed"], ct.DISP_SPEED)  # 缺键回退常量
        finally:
            profiles.set_pump_defaults_provider(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
