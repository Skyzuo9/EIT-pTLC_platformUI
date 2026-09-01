#!/usr/bin/env python3
"""三维泵相位表 ↔ translator plan 漂移门禁
==========================================
背景 (仿真模块阶段①·泵链路归真):
    three_d/pipeline/pump_syringe_spec.PUMP_SYRINGE_ACTIONS 是三维演示的泵相位
    脚本 (三方消费: clip_compiler / PumpSyringeModel.js / flowSim.js), 历史上是
    照着 translator 手抄的 —— 真实指令改了、表没改, 演示照旧"看起来对", 配置
    错误在三维里永远不可见 (2026-08-08 用户在上样-充液润洗上抓到的正是这一类)。

    本门禁把两边钉在一起: 对每个泵动作, 用同一组具体参数
      (a) 按相位表求值 → 柱塞绝对轨迹 (op, 端口, 绝对mL, 速度档名) 序列;
      (b) 跑 tools/pump 的 plan_* (PLC 实收 DT 串的同一产地) → 同形序列;
    逐段断言一致。改 translator 不改表、或改表不改 translator, 这里即红。

具名豁免 (唯一允许的偏差, 每条给理由):
    * develop.fill / rinse_fill / clean_line 的**多溶剂**场景: 真实指令按配比逐
      通道(口2-5)分段吸到各累计位, 相位表的静态 schema 表达不了"按配比动态分段",
      只能写单段吸到总量。故多溶剂只对账**终点不变量**(峰值=总量, 终态=0);
      单溶剂场景仍逐段严判 (此时两边应当完全一致)。
    * *.init: 真实指令是 Z 初始化 (非运动计划, plan_* 无对应物), 不对账。
    * rampS: 演示侧渐近时长, 不参与对账 (真实时长由 V/M 换算, 另有换算测试)。

附带性质测试: 每个 plan 的语义段必须与 dt_codec.motion_segments 从其指令串
机械抽取的运动段逐位对齐 —— 语义注解永远不许与字符串本体脱钩。

运行:
    python -m pytest eit_ptlc/tests/test_pump_manifest_drift_offline.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))
sys.path.insert(0, str(_PKG / "three_d" / "pipeline"))

from pump_syringe_spec import PUMP_SYRINGE_ACTIONS  # noqa: E402

from eit_ptlc.tools.pump import collect_translator as ct  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import dt_codec  # noqa: E402
from eit_ptlc.tools.pump import sample_translator_v2 as s2  # noqa: E402

# mL 容差: 一步 = 1/240 mL, 逐段取整最多差几步; 0.02mL ≈ 5 步, 足够严。
_TOL_ML = 0.02

# 不对账的动作与理由 (完备性测试逼着每个新表条目要么被门禁、要么在此具名)。
_EXEMPT_ACTIONS = {
    "develop.init": "Z 初始化, 非运动计划",
    "collect.init": "Z 初始化, 非运动计划",
    "sampling.init": "Z 初始化, 非运动计划",
}


def _phase_rows(spec: dict, args: dict, *, output_port: int | None = None,
                loop_rounds: int = 1) -> list[tuple]:
    """按相位表求值 → [(op, port, 绝对mL, 速度档名)] (柱塞从 0 起算)。"""
    phases = list(spec.get("phases") or [])
    loop = spec.get("loop") or {}
    phases += list(loop.get("phases") or []) * loop_rounds
    rows: list[tuple] = []
    pos = 0.0
    for phase in phases:
        names = ((phase.get("toFrom") or {}).get("add")
                 or (phase.get("byFrom") or {}).get("add") or [])
        if phase.get("skipIfMissing") and any(n not in args for n in names):
            continue
        if "to" in phase:
            pos = float(phase["to"])
        elif "toFrom" in phase:
            pos = sum(float(args[n]) for n in phase["toFrom"]["add"])
        elif "by" in phase:
            pos += float(phase["by"]) * (1.0 if phase["op"] == "aspirate" else -1.0)
        elif "byFrom" in phase:
            delta = sum(float(args[n]) for n in phase["byFrom"]["add"])
            pos += delta * (1.0 if phase["op"] == "aspirate" else -1.0)
        else:
            raise AssertionError(f"相位缺目标声明: {phase}")
        port = phase.get("port")
        if port == "output":
            port = output_port
        rows.append((phase["op"], port, pos, phase.get("speed")))
    return rows


def _plan_rows(plan, *, entry_order: tuple[int, ...] | None = None) -> list[tuple]:
    """把 PumpPlan 的语义段折成 [(op, port, 绝对mL, 速度档名)] (柱塞从 0 起算)。

    entry_order: PLC 消费序与数组下标序不同时显式给 (如 sampling.aspirate 的
    [2]→[1]); 缺省按 entries 原序。
    """
    entries = list(plan.entries)
    if entry_order is not None:
        entries = [entries[i] for i in entry_order]
    rows: list[tuple] = []
    pos = 0.0
    for entry in entries:
        for seg in entry.segments:
            if seg.kind == "abs":
                pos = seg.ml
            else:
                pos += seg.ml * (1.0 if seg.op == "aspirate" else -1.0)
            rows.append((seg.op, seg.port, pos, seg.speed_key))
    return rows


class PumpManifestDriftTests(unittest.TestCase):
    """相位表 ↔ plan 逐段对账。"""

    #: 已被本门禁覆盖的动作 (完备性测试用)
    gated: set = set()

    def _assert_rows_match(self, action: str, table_rows: list, plan_rows: list) -> None:
        self.gated.add(action)
        self.assertEqual(
            len(table_rows), len(plan_rows),
            f"{action}: 相位段数 {len(table_rows)} != plan 段数 {len(plan_rows)}\n"
            f"  表侧: {table_rows}\n  plan: {plan_rows}")
        for i, (t_row, p_row) in enumerate(zip(table_rows, plan_rows)):
            with self.subTest(action=action, segment=i):
                t_op, t_port, t_ml, t_speed = t_row
                p_op, p_port, p_ml, p_speed = p_row
                self.assertEqual(t_op, p_op, f"{action}[{i}] 吸/排方向漂移")
                if t_port is not None:
                    self.assertEqual(t_port, p_port, f"{action}[{i}] 阀口漂移")
                self.assertAlmostEqual(
                    t_ml, p_ml, delta=_TOL_ML,
                    msg=f"{action}[{i}] 柱塞绝对位漂移: 表 {t_ml}mL vs 指令 {p_ml}mL")
                self.assertEqual(t_speed, p_speed, f"{action}[{i}] 速度档名漂移")

    # ---- 上样 ----
    def test_sampling_clean(self) -> None:
        args = {"wash_volume_ml": 10.0}
        self._assert_rows_match(
            "sampling.clean",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.clean"], args),
            _plan_rows(s2.plan_clean_array(10.0)))

    def test_sampling_flush(self) -> None:
        for volumes in ((17.0, 5.0, 3.0), (16.0, 4.0, 2.5)):
            flush, outer, spot = volumes
            args = {"flush_volume_ml": flush, "outer_wash_volume_ml": outer,
                    "spot_head_volume_ml": spot}
            with self.subTest(volumes=volumes):
                self._assert_rows_match(
                    "sampling.flush",
                    _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.flush"], args),
                    _plan_rows(s2.plan_flush_array(flush, outer, spot)))

    def test_sampling_prep(self) -> None:
        args = {"air_buffer_ml": 0.2}
        self._assert_rows_match(
            "sampling.prep",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.prep"], args),
            _plan_rows(s2.plan_prep_array(0.2)))

    def test_sampling_aspirate_with_gap(self) -> None:
        args = {"sample_volume_ml": 5.0, "air_gap_ml": 0.2}
        self._assert_rows_match(
            "sampling.aspirate",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.aspirate"], args),
            # PLC 消费序 [2] 气隔断 → [1] 样品 (build_sample_array 文档约定)
            _plan_rows(s2.plan_sample_array(5.0, 0.2), entry_order=(1, 0)))

    def test_sampling_aspirate_without_gap(self) -> None:
        args = {"sample_volume_ml": 5.0}     # air_gap 缺席 → skipIfMissing 生效
        self._assert_rows_match(
            "sampling.aspirate",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.aspirate"], args),
            _plan_rows(s2.plan_sample_array(5.0, None), entry_order=(1, 0)))

    def test_sampling_rinse_mix(self) -> None:
        args = {"rinse_volume_ml": 3.0, "mix_volume_ml": 1.5, "air_gap_ml": 0.2}
        self._assert_rows_match(
            "sampling.rinse_mix",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.rinse_mix"], args, loop_rounds=1),
            _plan_rows(s2.plan_rinse_mix_array(3.0, 1.5, 0.2)))

    def test_sampling_spot(self) -> None:
        args = {"sample_volume_ml": 5.0}
        self._assert_rows_match(
            "sampling.spot",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.spot"], args),
            # profiles._build_sampling_spot 恒传解析后的 dispense_disp_speed
            _plan_rows(s2.plan_dispense_array(5.0, dispense_disp_speed=50)))

    def test_sampling_spot_band_layer(self) -> None:
        args = {"spot_end_position_ml": 1.0}
        self._assert_rows_match(
            "sampling.spot_band_layer",
            _phase_rows(PUMP_SYRINGE_ACTIONS["sampling.spot_band_layer"], args),
            _plan_rows(s2.plan_spot_band_run(end_position_ml=1.0)))

    # ---- 收集 ----
    def test_collect_collect(self) -> None:
        args = {"solvent_volume_ml": 10.0}
        self._assert_rows_match(
            "collect.collect",
            _phase_rows(PUMP_SYRINGE_ACTIONS["collect.collect"], args),
            _plan_rows(ct.plan_collect(10.0)))

    # ---- 展开 (单溶剂严判) ----
    def test_develop_single_solvent_strict(self) -> None:
        for action in ("develop.fill", "develop.rinse_fill", "develop.clean_line"):
            for target_tank, addr in ((1, "1"), (5, "2")):
                args = {"solvent_volume_ml": 20.0, "target_tank": target_tank}
                output_port = dt.PUMP_OUTPUT_PORT_MAP[addr]
                with self.subTest(action=action, tank=target_tank):
                    self._assert_rows_match(
                        action,
                        _phase_rows(PUMP_SYRINGE_ACTIONS[action], args,
                                    output_port=output_port),
                        _plan_rows(dt.plan_forward_instructions(
                            [1, 0, 0, 0], 20.0, pump_addr=addr)))

    def test_develop_multi_solvent_endpoint_exemption(self) -> None:
        """具名豁免: 多溶剂分段吸液无法进相位表, 只对账终点不变量。

        真实指令 (plan): 逐通道吸到各累计位, 峰值 = 总量, 终态 = 0;
        相位表: 单段吸到总量再打空 —— 峰值与终态与真实一致, 中途分段被简化。
        """
        plan = dt.plan_forward_instructions([3, 2, 1, 0], 15.0, pump_addr="1")
        rows = _plan_rows(plan)
        peak = max(ml for _op, _port, ml, _speed in rows)
        self.assertAlmostEqual(peak, 15.0, delta=_TOL_ML, msg="多溶剂峰值 != 总量")
        self.assertAlmostEqual(rows[-1][2], 0.0, delta=_TOL_ML, msg="多溶剂终态 != 0")
        self.assertEqual(rows[-1][0], "dispense")
        # 表侧同一组参数的峰值/终态
        table_rows = _phase_rows(
            PUMP_SYRINGE_ACTIONS["develop.fill"], {"solvent_volume_ml": 15.0,
                                                   "target_tank": 1},
            output_port=dt.PUMP_OUTPUT_PORT_MAP["1"])
        self.assertAlmostEqual(max(r[2] for r in table_rows), peak, delta=_TOL_ML)
        self.assertAlmostEqual(table_rows[-1][2], 0.0, delta=_TOL_ML)

    # ---- 完备性: 每个表条目要么被门禁, 要么具名豁免 ----
    def test_zz_every_table_action_is_gated_or_exempt(self) -> None:
        """(zz 前缀保证本用例最后跑, gated 集合已收齐)"""
        uncovered = set(PUMP_SYRINGE_ACTIONS) - self.gated - set(_EXEMPT_ACTIONS)
        self.assertFalse(
            uncovered,
            f"泵相位表新增/遗漏条目未被漂移门禁覆盖: {sorted(uncovered)} —— "
            f"要么在本文件补对账用例, 要么进 _EXEMPT_ACTIONS 并写明理由")


class PlanSegmentConsistencyTests(unittest.TestCase):
    """plan 语义段 ↔ 指令串机械运动段 逐位对齐 (语义注解不许与串脱钩)。"""

    def _assert_plan_selfconsistent(self, plan) -> None:
        for entry in plan.entries:
            mech = dt_codec.motion_segments(entry.program)
            self.assertEqual(
                len(entry.segments), len(mech),
                f"语义段数与串内 A/P 数不符: {entry.command()!r}")
            for seg, m in zip(entry.segments, mech):
                self.assertEqual(seg.steps, m.steps)
                self.assertEqual(seg.kind, m.kind)
                self.assertEqual(seg.port, m.port)
                self.assertEqual(seg.speed, m.speed)
                self.assertEqual(seg.delay_ms, m.delay_ms)

    def test_all_production_plans(self) -> None:
        plans = {
            "clean": s2.plan_clean_array(10.0),
            "flush": s2.plan_flush_array(),
            "prep": s2.plan_prep_array(0.2),
            "sample": s2.plan_sample_array(5.0, 0.2),
            "rinse_mix": s2.plan_rinse_mix_array(3.0, 1.5),
            "dispense": s2.plan_dispense_array(5.0, dispense_disp_speed=50),
            "band_run": s2.plan_spot_band_run(end_position_ml=1.0),
            "collect": ct.plan_collect(10.0),
            "forward": dt.plan_forward_instructions([3, 2, 1, 0], 15.0),
        }
        for name, plan in plans.items():
            with self.subTest(plan=name):
                self._assert_plan_selfconsistent(plan)


if __name__ == "__main__":
    unittest.main()
