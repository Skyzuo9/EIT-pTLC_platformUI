#!/usr/bin/env python3
"""泵 DT 指令逐字节金测试
========================
背景 (仿真模块阶段①·泵链路归真):
    四个 translator 的 build_*/translate_* 是 PLC 实际收到的 DT 指令串的唯一产地。
    为了让三维演示/仿真与真实执行同源, 这批函数将拆出结构化 plan_* API 并把字符串
    构造改为 plan 的序列化 (dt_codec.serialize)。本测试在重构**之前**落地: 对每个
    公开构建函数取参数矩阵 (默认值 + 非默认覆写 + 边界), 把当时的输出串固化为
    GOLDEN 常量 —— 重构后任何一个字节的漂移都在此现形。

    GOLDEN 常量由脚本一次性生成 (repr 内联), 之后**手不许碰**: 若某天确需改变 DT
    输出 (硬件协议升级), 必须在 PR 里同时改此表并说明协议依据。

另含 dt_codec 往返性质测试: 对 GOLDEN 里每一条指令串断言
    serialize(parse(s)) == s
—— codec 的语法覆盖以真实产地为准, 不自造样例。

运行:
    python -m pytest eit_ptlc/tests/test_pump_dt_golden_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.tools.pump import collect_translator as ct  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import sample_translator as s1  # noqa: E402
from eit_ptlc.tools.pump import sample_translator_v2 as s2  # noqa: E402

# ---------------------------------------------------------------------------
# 参数矩阵: key -> 无参 thunk (与 GOLDEN 逐键对应)。
# 覆盖原则: 每个函数至少 默认值 1 条 + 覆写 1 条; 有边界语义的加边界条
# (满行程 25mL / retract=0 / air_gap=None / 零体积展开)。
# ---------------------------------------------------------------------------
CASES: dict[str, object] = {
    # -- sample_translator (v1) 低层构建 --
    "s1.segment.default": lambda: s1.build_segment_cmd(2.0, 1),
    "s1.segment.custom": lambda: s1.build_segment_cmd(
        12.5, 4, pump_addr="9", asp_speed=111, disp_speed=222, step_delay=333,
        output_port=2),
    "s1.segment.full_stroke": lambda: s1.build_segment_cmd(25.0, 1),
    "s1.aspirate.default": lambda: s1.build_aspirate_cmd(3.0, 3),
    "s1.aspirate.custom": lambda: s1.build_aspirate_cmd(
        0.2, 4, pump_addr="4", asp_speed=50, step_delay=100),
    "s1.rel_aspirate.default": lambda: s1.build_relative_aspirate_cmd(1.5, 3),
    "s1.rel_aspirate.custom": lambda: s1.build_relative_aspirate_cmd(
        25.0, 3, pump_addr="4", asp_speed=77, step_delay=250),
    "s1.dispense_all.default": lambda: s1.build_dispense_all_cmd(),
    "s1.dispense_all.end_steps": lambda: s1.build_dispense_all_cmd(
        pump_addr="4", disp_speed=50, step_delay=1500, output_port=3, end_steps=120),
    "s1.bubble.default": lambda: s1.translate_sample_bubble_cmd(2.0, 1.0, 2),
    "s1.bubble.custom": lambda: s1.translate_sample_bubble_cmd(
        3.0, 0.5, 1, pump_addr="4", tail_volume_ml=30.0, asp_speed=200,
        disp_speed=90, step_delay=800),
    "s1.init.default": lambda: s1.pump_init_cmd(),
    "s1.init.custom": lambda: s1.pump_init_cmd("4", init_speed=1, input_port=2, output_port=3),
    "s1.query.default": lambda: s1.pump_query_cmd(),
    # -- sample_translator_v2 --
    "s2.v2.default": lambda: s2.translate_sample_v2_cmd(5.0),
    "s2.v2.no_retract": lambda: s2.translate_sample_v2_cmd(5.0, retract_volume_ml=0.0),
    "s2.v2.spot_speed": lambda: s2.translate_sample_v2_cmd(
        4.0, air_buffer_ml=2.0, wash_volume_ml=20.0, retract_volume_ml=0.5,
        asp_speed=200, disp_speed=80, dispense_disp_speed=40, step_delay=900),
    "s2.clean.default": lambda: s2.build_clean_array(25.0),
    "s2.clean.custom": lambda: s2.build_clean_array(
        10.0, pump_addr="4", asp_speed=120, disp_speed=60, step_delay=700),
    "s2.flush.default": lambda: s2.build_flush_array(),
    "s2.flush.custom": lambda: s2.build_flush_array(
        16.0, 4.0, 2.5, pump_addr="4", asp_speed=250, flush_disp_speed=300,
        spot_head_disp_speed=100, step_delay=1500),
    "s2.prep.default": lambda: s2.build_prep_array(),
    "s2.prep.small": lambda: s2.build_prep_array(0.2, asp_speed=250, step_delay=1500),
    "s2.sample.no_gap": lambda: s2.build_sample_array(5.0),
    "s2.sample.with_gap": lambda: s2.build_sample_array(5.0, 0.2),
    "s2.sample.custom": lambda: s2.build_sample_array(
        2.5, 0.5, pump_addr="4", asp_speed=50, step_delay=1500),
    "s2.rinse_mix.default": lambda: s2.build_rinse_mix_array(3.0, 1.5),
    "s2.rinse_mix.custom": lambda: s2.build_rinse_mix_array(
        2.0, 1.0, 0.5, pump_addr="4", asp_speed=250, disp_speed=100, step_delay=1500),
    "s2.dispense.default": lambda: s2.build_dispense_array(5.0),
    "s2.dispense.no_retract": lambda: s2.build_dispense_array(5.0, 0.0),
    "s2.dispense.spot_speed": lambda: s2.build_dispense_array(3.0, 1.0, dispense_disp_speed=50),
    "s2.band_run.default": lambda: s2.build_spot_band_run_cmd(),
    "s2.band_run.end_pos": lambda: s2.build_spot_band_run_cmd(
        disp_speed=50, step_delay=1500, end_position_ml=1.0),
    "s2.band_end_steps.zero": lambda: s2.spot_band_end_steps(0.0),
    "s2.band_end_steps.max": lambda: s2.spot_band_end_steps(5.0),
    "s2.band_end_steps.mid": lambda: s2.spot_band_end_steps(2.5),
    "s2.stop.default": lambda: s2.build_pump_stop_cmd(),
    "s2.stop.addr": lambda: s2.build_pump_stop_cmd(pump_addr="9"),
    # -- collect_translator --
    "ct.collect.default": lambda: ct.translate_collect_cmd(10.0),
    "ct.collect.custom": lambda: ct.translate_collect_cmd(
        24.5, pump_addr="3", asp_speed=400, disp_speed=350, step_delay=600),
    "ct.collect.boundary": lambda: ct.translate_collect_cmd(25.0),
    "ct.init.default": lambda: ct.pump_init_cmd(),
    "ct.query.default": lambda: ct.pump_query_cmd(),
    # -- develop_translator --
    "dt.cmd_seq.three_solvent": lambda: dt.translate_develop_cmd([3, 2, 1, 0], 15.0),
    "dt.cmd_seq.single": lambda: dt.translate_develop_cmd([1, 0, 0, 0], 25.0, pump_addr="2"),
    "dt.forward.three_solvent": lambda: dt.build_forward_instructions([3, 2, 1, 0], 15.0),
    "dt.forward.single_pump2": lambda: dt.build_forward_instructions(
        [1, 0, 0, 0], 25.0, pump_addr="2"),
    "dt.forward.custom_speed": lambda: dt.build_forward_instructions(
        [1, 1, 0, 0], 20.0, pump_addr="1", asp_speed=150, disp_speed=90, step_delay=400),
    "dt.params.fill_tank5": lambda: dt.translate_develop_params(
        [1, 0, 0, 0], 20.0, target_tank=5, up_liquid_repeat_count=2),
    "dt.params.line_tank1": lambda: dt.translate_develop_params(
        [3, 2, 1, 0], 15.0, rinse_mode="line", target_tank=1, rinse_repeat_count=3,
        asp_speed=120, disp_speed=80, step_delay=300),
    "dt.params.zero_volume": lambda: dt.translate_develop_params(
        [1, 0, 0, 0], 0.0, target_tank=2),
    "dt.init.pump1": lambda: dt.pump_init_cmd("1"),
    "dt.init.pump2": lambda: dt.pump_init_cmd("2"),
    "dt.query.default": lambda: dt.pump_query_cmd(),
}

# ---------------------------------------------------------------------------
# 金常量: 2026-08-08 由重构前实现生成 (scratch dump_pump_golden.py), 逐字节冻结。
# ---------------------------------------------------------------------------
GOLDEN = {
    's1.segment.default': '/1V250I1A480M1500V100I3A0M1500R\r',
    's1.segment.custom': '/9V111I4A3000M333V222I2A0M333R\r',
    's1.segment.full_stroke': '/1V250I1A6000M1500V100I3A0M1500R\r',
    's1.aspirate.default': '/1V250I3A720M1500R\r',
    's1.aspirate.custom': '/4V50I4A48M100R\r',
    's1.rel_aspirate.default': '/1V250I3P360M1500R\r',
    's1.rel_aspirate.custom': '/4V77I3P6000M250R\r',
    's1.dispense_all.default': '/1V100I3A0M1500R\r',
    's1.dispense_all.end_steps': '/4V50I3A120M1500R\r',
    's1.bubble.default': ['/1V250I1A480M1500V100I3A0M1500R\r', '/1V250I4A240M1500V100I3A0M1500R\r', '/1V250I1A480M1500V100I3A0M1500R\r', '/1V250I4A240M1500V100I3A0M1500R\r', '/1V250I1A6000M1500V100I3A0M1500R\r', '/1V250I1A240M1500V100I3A0M1500R\r', '/1V250I3A6000M1500R\r', '/1V100I3A0M1500R\r'],
    's1.bubble.custom': ['/4V200I1A720M800V90I3A0M800R\r', '/4V200I4A120M800V90I3A0M800R\r', '/4V200I1A6000M800V90I3A0M800R\r', '/4V200I1A1200M800V90I3A0M800R\r', '/4V200I3A6000M800R\r', '/4V90I3A0M800R\r'],
    's1.init.default': '/1Z0,0,3R$R',
    's1.init.custom': '/4Z1,2,3R$R',
    's1.query.default': '/1Q$R',
    's2.v2.default': ['/4V250I1A6000M1500V100I3A0M1500R\r', '/4V250I3A720M1500R\r', '/4V250I3A1200M1500R\r', '/4V100I2A0M1500R\r', '/4V250I4A1200M1500R\r', '/4V100I3A0M1500R\r', '/4V250I3A240M1500R\r'],
    's2.v2.no_retract': ['/4V250I1A6000M1500V100I3A0M1500R\r', '/4V250I3A720M1500R\r', '/4V250I3A1200M1500R\r', '/4V100I2A0M1500R\r', '/4V250I4A1200M1500R\r', '/4V100I3A0M1500R\r'],
    's2.v2.spot_speed': ['/4V200I1A4800M900V80I3A0M900R\r', '/4V200I3A480M900R\r', '/4V200I3A960M900R\r', '/4V80I2A0M900R\r', '/4V200I4A960M900R\r', '/4V40I3A0M900R\r', '/4V200I3A120M900R\r'],
    's2.clean.default': ['/4V250I1A6000M1500V100I3A0M1500R\r', '/4V250I1A6000M1500V100I2A0M1500R\r'],
    's2.clean.custom': ['/4V120I1A2400M700V60I3A0M700R\r', '/4V120I1A2400M700V60I2A0M700R\r'],
    's2.flush.default': ['/4V250I1A6000M1500V300I3A1920M1500V300I2A720M1500R\r', '/4V100I3A0M1500R\r'],
    's2.flush.custom': ['/4V250I1A5400M1500V300I3A1560M1500V300I2A600M1500R\r', '/4V100I3A0M1500R\r'],
    's2.prep.default': ['/4V250I3A720M1500R\r', ''],
    's2.prep.small': ['/4V250I3A48M1500R\r', ''],
    's2.sample.no_gap': ['/4V250I3P1200M1500R\r', ''],
    's2.sample.with_gap': ['/4V250I3P1200M1500R\r', '/4V250I3A48M1500R\r'],
    's2.sample.custom': ['/4V50I3P600M1500R\r', '/4V50I3A120M1500R\r'],
    's2.rinse_mix.default': ['/4V100I3A0M1500R\r', '/4V250I1A720M1500V100I3A0M1500R\r', '/4V250I3A48M1500R\r', '/4V250I3A408M1500V100I3A48M1500R\r'],
    's2.rinse_mix.custom': ['/4V100I3A0M1500R\r', '/4V250I1A480M1500V100I3A0M1500R\r', '/4V250I3A120M1500R\r', '/4V250I3A360M1500V100I3A120M1500R\r'],
    's2.dispense.default': ['/4V250I4A1200M1500R\r', '/4V100I3A0M1500V250I3A240M1500R\r'],
    's2.dispense.no_retract': ['/4V250I4A1200M1500R\r', '/4V100I3A0M1500R\r'],
    's2.dispense.spot_speed': ['/4V250I4A720M1500R\r', '/4V50I3A0M1500V250I3A240M1500R\r'],
    's2.band_run.default': '/4V50I3A0M1500R\r',
    's2.band_run.end_pos': '/4V50I3A240M1500R\r',
    's2.band_end_steps.zero': 0,
    's2.band_end_steps.max': 1200,
    's2.band_end_steps.mid': 600,
    's2.stop.default': '/4T\r',
    's2.stop.addr': '/9T\r',
    'ct.collect.default': '/3V500I2A2400M1000V500I1A0M1000R\r',
    'ct.collect.custom': '/3V400I2A5880M600V350I1A0M600R\r',
    'ct.collect.boundary': '/3V500I2A6000M1000V500I1A0M1000R\r',
    'ct.init.default': '/3Z0,0,1R$R',
    'ct.query.default': '/3Q$R',
    'dt.cmd_seq.three_solvent': [{'channel': 2, 'volume_ml': 7.5, 'command': 'I2A1800M500'}, {'channel': 3, 'volume_ml': 5.0, 'command': 'I3A3000M500'}, {'channel': 4, 'volume_ml': 2.5, 'command': 'I4A3600M500'}, {'channel': 6, 'volume_ml': 0.0, 'command': 'I6A0M500'}],
    'dt.cmd_seq.single': [{'channel': 2, 'volume_ml': 25.0, 'command': 'I2A6000M500'}, {'channel': 1, 'volume_ml': 0.0, 'command': 'I1A0M500'}],
    'dt.forward.three_solvent': '/1V100I2A1800M500I3A3000M500I4A3600M500V100I6A0M500R\r',
    'dt.forward.single_pump2': '/2V100I2A6000M500V100I1A0M500R\r',
    'dt.forward.custom_speed': '/1V150I2A2400M400I3A4800M400V90I6A0M400R\r',
    'dt.params.fill_tank5': {'Expand_Mode_Flag': 0, 'Expand_Target_Tank': 5, 'Expand_forward_instructions': '/2V100I2A4800M500V100I1A0M500R\r', 'Expand_rinse_count': 1, 'Expand_up_liquid_count': 2},
    'dt.params.line_tank1': {'Expand_Mode_Flag': 1, 'Expand_Target_Tank': 1, 'Expand_forward_instructions': '/1V120I2A1800M300I3A3000M300I4A3600M300V80I6A0M300R\r', 'Expand_rinse_count': 3, 'Expand_up_liquid_count': 1},
    'dt.params.zero_volume': {'Expand_Mode_Flag': 0, 'Expand_Target_Tank': 2, 'Expand_forward_instructions': '', 'Expand_rinse_count': 1, 'Expand_up_liquid_count': 1},
    'dt.init.pump1': '/1Z0,0,6R$R',
    'dt.init.pump2': '/2Z0,0,1R$R',
    'dt.query.default': '/1Q$R',
}


def _iter_strings(value: object):
    """从 GOLDEN 值里抽出全部 DT 指令串 (str / list[str] / dict 内嵌串)。"""
    if isinstance(value, str):
        if value.startswith("/"):
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)


class PumpDtGoldenTests(unittest.TestCase):
    """重构前后 DT 输出逐字节一致。"""

    def test_case_keys_match_golden_keys(self) -> None:
        """参数矩阵与金常量逐键对应 (漏抓/多抓都在这里现形)。"""
        self.assertEqual(set(CASES), set(GOLDEN))

    def test_builders_emit_golden_bytes(self) -> None:
        for key, thunk in CASES.items():
            with self.subTest(case=key):
                self.assertEqual(thunk(), GOLDEN[key])


class DtCodecRoundTripTests(unittest.TestCase):
    """dt_codec 对真实产地全部指令串满足 serialize(parse(s)) == s。

    dt_codec 是阶段①新增模块; 本用例在其落地前 skip, 落地后自动生效。
    """

    def test_roundtrip_every_golden_string(self) -> None:
        try:
            from eit_ptlc.tools.pump import dt_codec
        except ImportError:
            self.skipTest("dt_codec 尚未落地")
        seen = 0
        for key, value in GOLDEN.items():
            for cmd in _iter_strings(value):
                with self.subTest(case=key, cmd=cmd):
                    self.assertEqual(dt_codec.serialize(dt_codec.parse(cmd)), cmd)
                seen += 1
        self.assertGreater(seen, 40, "金常量里应当抽出足量指令串, 抽不出说明遍历器坏了")

    def test_roundtrip_empty_placeholder(self) -> None:
        """数组里的空串占位 (prep/sample 的 entry[2]) 也必须可往返。"""
        try:
            from eit_ptlc.tools.pump import dt_codec
        except ImportError:
            self.skipTest("dt_codec 尚未落地")
        self.assertEqual(dt_codec.serialize(dt_codec.parse("")), "")


if __name__ == "__main__":
    unittest.main()
