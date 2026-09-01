"""L2 错误码释义的离线测试 (纯读 spec, 不起服务)
================================================
功能:
    钉住四条:
      ① **八工位覆盖率** —— 遍历全部 spec 的 errors 键, 每一个都翻得出话来。
         此前只有 feedlift 有释义, 其余七个工位在现场只显示裸数字。
      ② **单一真源** —— 门原文由 spec 现算出期望值再断言逐字出现; 哪天有人在上位机
         侧复活一份手抄门表, 这条立刻打架。
      ③ **分语境** —— 沙盒语境的 301 不含"标定"二字 (用户 2026-08-12 撞到的正是
         沙盒里被真机标定话术引偏)。
      ④ 认不出的码返回空串, 不编。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest \
        eit_ptlc/tests/test_plc_error_hints_offline.py -q
"""

from __future__ import annotations

import unittest

from eit_ptlc.action.plc_error_hints import CONTEXT_REAL, CONTEXT_SIM, describe
from eit_ptlc.mock.behavior.spec_loader import load_all_specs, load_station_spec


class TestCoverage(unittest.TestCase):
    """八个工位的每个已登记错误码都有释义."""

    def test_every_spec_error_code_has_text(self):
        specs = load_all_specs()
        self.assertGreaterEqual(len(specs), 8, "应有八个工位的编排说明书")
        missing = []
        for station, spec in specs.items():
            for code, action_spec in spec.actions.items():
                for error_code in (action_spec.errors or {}):
                    text = describe(station, code, error_code)
                    if not text:
                        missing.append(f"{station} 动作{code} 错误码{error_code}")
        self.assertEqual(missing, [],
                         f"这些错误码翻不出话来 (spec 里加了码却没被释义层认到): {missing}")

    def test_dispatcher_gate_errors_are_covered(self):
        """派发器级错误码 (未登记码等) 也要翻得出."""
        for station, spec in load_all_specs().items():
            for error_code in (spec.gate_errors or {}):
                self.assertTrue(describe(station, 0, error_code),
                                f"{station} 的派发器错误码 {error_code} 无释义")

    def test_unknown_code_error_is_named(self):
        """未登记动作码的那个码 (101/103) 说得出它是"派发器不认这个码"."""
        spec = load_station_spec("FeedLift")
        text = describe("feedlift", 0, spec.unknown_code_error)
        self.assertIn("未登记", text)


class TestSingleSourceOfTruth(unittest.TestCase):
    """门原文只能来自 spec."""

    def test_gate_text_is_computed_from_the_spec(self):
        spec = load_station_spec("FeedLift")
        action = spec.action(11)
        text = describe("feedlift", 11, 301)
        for key, value in action.gate.items():
            if key == "timeout_error":
                continue
            self.assertIn(str(value), text,
                          f"门项 {key}={value} 应逐字出现在释义里; 若不在, 说明释义走的"
                          f"不是 spec 而是别处抄的表")

    def test_error_text_is_the_spec_wording(self):
        spec = load_station_spec("FeedLift")
        for code, error_code in ((11, 304), (13, 307), (13, 303)):
            expected = spec.action(code).errors[error_code]
            self.assertIn(expected, describe("feedlift", code, error_code))


class TestSemantics(unittest.TestCase):
    """释义要指向正确的排查方向 (迁移自 test_feedlift_count_offline 的旧断言)."""

    def test_gate_timeout_points_at_preconditions_not_motion(self):
        """301/302 = 轴根本没启动; 不该出现到界字样."""
        text = describe("feedlift", 11, 301)
        self.assertIn("前置门", text)
        self.assertIn("上料进料传感器", text)
        self.assertNotIn("搜到", text)

        waste = describe("feedlift", 21, 302)
        self.assertIn("下料出料传感器", waste)
        self.assertNotIn("接近开关2", waste,
                         "A21 的门刻意不查接近开关2 —— 释义不该替它加一项")

    def test_boundary_codes_point_at_the_search_window(self):
        """304/307 = 真搜到了边界; 不该出现前置字样."""
        up = describe("feedlift", 11, 304)
        self.assertIn("SearchHighTarget", up)
        self.assertNotIn("前置门", up)

        down = describe("feedlift", 13, 307)
        self.assertIn("SearchLowTarget", down)
        self.assertNotIn("前置门", down)

    def test_step_from_another_action_is_flagged(self):
        """段号命中别的动作 -> 明确点出"疑为残留段号" (手抄表给不了的诊断)."""
        text = describe("feedlift", 11, 301, step=41)      # 41 属 A13
        self.assertIn("与本动作不符", text)

    def test_step_of_this_action_is_named(self):
        text = describe("feedlift", 13, 301, step=44)
        self.assertIn("段号 44", text)
        self.assertIn("fail", text)

    def test_unknown_inputs_return_empty(self):
        self.assertEqual(describe("feedlift", 11, 999), "")
        self.assertEqual(describe("nosuchstation", 11, 301), "")
        self.assertEqual(describe("feedlift", 11, 0), "")


class TestContexts(unittest.TestCase):
    """真机话术与沙盒指引分家."""

    def test_real_context_keeps_the_calibration_hint(self):
        text = describe("feedlift", 11, 301, context=CONTEXT_REAL)
        self.assertIn("标定不要采空仓那一组", text)
        self.assertIn("一键回原点", text)

    def test_sim_context_points_at_the_sandbox_state_face(self):
        """沙盒里没有"标定失准"这回事 —— 该说去哪儿设板仓张数."""
        text = describe("feedlift", 11, 301, context=CONTEXT_SIM)
        # 断言的是"误导性建议不在", 不是"标定二字不出现" —— 沙盒话术里那句
        # "标定文件是真机的, 沙盒不涉及标定失准"恰恰是要说的话
        self.assertNotIn("标定不要采空仓那一组", text)
        self.assertNotIn("一键回原点", text)
        self.assertIn("/api/sim/materials/magazine", text)
        # 门原文与错误码文本两种语境下都在 —— 分家的只有处置话术
        self.assertIn("前置门", text)
        self.assertIn("上料进料传感器", text)

    def test_non_feedlift_stations_get_no_disposal_hint(self):
        """其余工位没有整理过的处置话术, 就只给 spec 原文, 不编."""
        text = describe("collect", 23, 201, context=CONTEXT_SIM)
        self.assertTrue(text, "Collect 的缺瓶 201 应有释义")
        self.assertNotIn("/api/sim/materials/magazine", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
