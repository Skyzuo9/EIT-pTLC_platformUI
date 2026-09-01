#!/usr/bin/env python3
"""泵动作参数契约 + recipe 引用完整性 离线测试
================================================
两道守护 (派发单 A3 + C3):

A3 一致性 — PumpContractTests:
    泵动作的"参数声明真源 = 动作 YAML (registry)"; profiles 仅持 builder。本测试用
    访问追踪 dict 跑每个 builder, 断言 *YAML 声明的参数集 == builder 实际消费的参数集*:
      - 声明了却没被 builder 读 -> 死参数 (旧 sampling.prep.sample_volume_ml 即此类);
      - builder 读了却没声明 -> 缺旋钮/拼写漂移 (KeyError 或多出键)。
    新加的 V/M (asp_speed/disp_speed/spot_disp_speed/step_delay) 也被此测试钉住:
    只要 YAML 声明了就必须被 builder 转发, 否则失败。

C3 引用完整性 — RecipeIntegrityTests:
    全量 operation 经 validate_script 零错误 (动作名合法 / 变量可解析); 且所有 run_script
    目标都能解析到现存 operation (顶层 ptlc_full_v2 的调用图无悬空引用)。补离线套件原本
    只跑 ptlc_full(v1) 不解析 v2 的盲区。

运行:
    & E:/Anaconda/envs/platformupper/python.exe -m pytest \
      eit_ptlc/tests/test_pump_contract_offline.py -q
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.executor import PLATE_WELL_PARAMS  # noqa: E402
from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.controller.points_service import PointsService  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES  # noqa: E402
from eit_ptlc.tools.pump import develop_translator as dt  # noqa: E402
from eit_ptlc.tools.pump import sample_translator_v2 as s2  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"
_OPERATION_DIR = _PKG / "config" / "operation"


class _TrackingDict(dict):
    """记录被读取过的键 (__getitem__ / get 均记账), 供"声明==消费"断言。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.read: set = set()

    def __getitem__(self, key):
        self.read.add(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.read.add(key)
        return super().get(key, default)


def _valid_value(param):
    """造一个落在范围内的合法值, 让 builder 的体积/比例/次数算式不报错。"""
    if param.default is not None:
        return param.default
    if param.type == "int":
        return int(param.minimum) if param.minimum is not None else 1
    if param.type == "float":
        if param.minimum is not None and param.minimum > 0:
            return float(param.minimum)
        return 1.0
    if param.type == "enum":
        return param.options[0].value if param.options else ""
    return "x"


class PumpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        # 组合点位成员键: 执行器在触发 L2 前把同名动作参数弹出作 member_overrides 透传 push_composite
        # (点样几何 x_start/x_end/y_height 即此类), 与 point_ref/PLATE_WELL 同属"非泵 builder 消费", 不计契约。
        # 从 executor 用的同一点位目录派生 → 不会与真实组合成员漂移。
        catalog = PointsService.load_catalog(_PKG / "config" / "points")
        cls.composite_member_keys = {m.key for c in catalog.composites for m in c.members}

    def test_declared_params_equal_builder_consumed(self) -> None:
        for name, profile in PUMP_PROFILES.items():
            with self.subTest(action=name):
                adef = self.registry.get(name)
                # executor 触发前消费的参数 (point_ref 点位引用 / PLATE_WELL_PARAMS 孔位寻址 / 组合点位成员覆盖)
                # 非泵 builder, 不计契约
                declared = {p.name for p in adef.params
                            if p.type != "point_ref" and p.name not in PLATE_WELL_PARAMS
                            and p.name not in self.composite_member_keys}
                self.assertTrue(declared, f"{name}: 泵动作应声明参数")
                values = _TrackingDict({p.name: _valid_value(p) for p in adef.params})
                profile.build(values)  # builder 只能经 values 取参数
                self.assertEqual(
                    values.read, declared,
                    f"{name}: builder 消费集 {sorted(values.read)} != YAML 声明集 {sorted(declared)} "
                    f"(声明未消费=死参数; 消费未声明=漂移)",
                )


class PumpTranslationTests(unittest.TestCase):
    def test_develop_uses_only_four_solvent_inlets_and_pump_specific_output(self) -> None:
        ratios = [1.0, 1.0, 1.0, 1.0]
        pump1 = dt.translate_develop_cmd(ratios, 4.0, pump_addr="1")
        pump2 = dt.translate_develop_cmd(ratios, 4.0, pump_addr="2")

        self.assertEqual([part["channel"] for part in pump1], [2, 3, 4, 5, 6])
        self.assertEqual([part["channel"] for part in pump2], [2, 3, 4, 5, 1])
        self.assertEqual(
            dt.build_forward_instructions(ratios, 4.0, pump_addr="1"),
            "/1V100I2A240M500I3A480M500I4A720M500I5A960M500V100I6A0M500R\r",
        )
        self.assertEqual(
            dt.build_forward_instructions(ratios, 4.0, pump_addr="2"),
            "/2V100I2A240M500I3A480M500I4A720M500I5A960M500V100I1A0M500R\r",
        )

    def test_develop_rejects_fifth_solvent_and_invalid_four_channel_ratios(self) -> None:
        with self.assertRaisesRegex(ValueError, "必须包含 4 个值"):
            dt.translate_develop_cmd([1.0, 0.0, 0.0, 0.0, 1.0], 2.0)
        with self.assertRaisesRegex(ValueError, "至少一个溶剂通道"):
            dt.translate_develop_cmd([0.0, 0.0, 0.0, 0.0], 2.0)
        with self.assertRaisesRegex(ValueError, "不能为负数"):
            dt.translate_develop_cmd([1.0, -1.0, 0.0, 0.0], 2.0)

    def test_prep_retains_cleaning_liquid_without_a0(self) -> None:
        commands = s2.build_prep_array(0.2, asp_speed=9, step_delay=1500)
        self.assertEqual(commands, ["/4V9I3A48M1500R\r", ""])

    def test_aspirate_uses_relative_p_without_a0(self) -> None:
        """不传 air_gap_ml: [2] 留空串, PLC 跳过吸气段 (legacy 先调 prep 的编排逐字不变)。"""
        commands = s2.build_sample_array(5.0, asp_speed=100, step_delay=1500)
        self.assertEqual(commands, ["/4V100I3P1200M1500R\r", ""])

    def test_aspirate_array_carries_absolute_air_gap_in_slot_two(self) -> None:
        """传 air_gap_ml: [2] 为绝对 A{gap}; PLC 按 [2]->[1] 消费 (移孔位前吸气, 下探后吸样)。

        绝对语义是润洗轮幂等的来源: A55 终态活塞已在 A{gap}, 再绝对吸至同位为零位移。
        """
        commands = s2.build_sample_array(3.5, 0.2, asp_speed=50, step_delay=1500)
        self.assertEqual(commands, ["/4V50I3P840M1500R\r", "/4V50I3A48M1500R\r"])
        self.assertIn("P", commands[0])          # [1] 相对叠加样品
        self.assertNotIn("P", commands[1])       # [2] 绝对定位, 不可相对否则润洗轮会累积气隔断

    def test_relative_volume_rejects_single_move_over_capacity(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_sample_array(25.1)
        with self.assertRaises(ValueError):     # 气隔断越界同样在 host 侧拦下
            s2.build_sample_array(5.0, 25.1)
        with self.assertRaises(ValueError):
            s2.build_sample_array(5.0, 0.0)

    # ---- 轻清洗充液 build_flush_array (spec 2026-07-14-sampling-light-flush §3.2) ----
    def test_flush_array_defaults_matches_spec(self) -> None:
        commands = s2.build_flush_array(17.0, 5.0, 3.0)
        self.assertEqual(commands, [
            "/4V250I1A6000M1500V300I3A1920M1500V300I2A720M1500R\r",
            "/4V100I3A0M1500R\r",
        ])

    def test_flush_array_step_conservation_and_a0_invariant(self) -> None:
        # s1=2400 s2=480 s3=360 -> total=3240, p1=840, p2=360; entry2 恒打到 A0
        commands = s2.build_flush_array(
            10.0, 2.0, 1.5,
            asp_speed=200, flush_disp_speed=400, spot_head_disp_speed=80, step_delay=500,
        )
        self.assertEqual(commands, [
            "/4V200I1A3240M500V400I3A840M500V400I2A360M500R\r",
            "/4V80I3A0M500R\r",
        ])

    def test_flush_array_rejects_over_capacity(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(18.0, 5.0, 3.0)   # 26 mL > 25 mL

    def test_flush_array_rejects_nonpositive_stage(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(17.0, 0.0, 3.0)

    def test_flush_array_rejects_disp_speed_over_500(self) -> None:
        with self.assertRaises(ValueError):
            s2.build_flush_array(17.0, 5.0, 3.0, flush_disp_speed=501)
        with self.assertRaises(ValueError):
            s2.build_flush_array(17.0, 5.0, 3.0, spot_head_disp_speed=501)

    def test_clean_and_flush_write_mode_every_dispatch(self) -> None:
        """防陈旧契约: clean/flush 每次派发都显式写 Sampling_clean_mode (spec §3.1)。"""
        clean = PUMP_PROFILES["sampling.clean"].build(
            {"wash_volume_ml": 25.0, "cleaning_count": 3})
        self.assertEqual(clean["Sampling_clean_mode"], 0)
        flush = PUMP_PROFILES["sampling.flush"].build(
            {"flush_volume_ml": 17.0, "outer_wash_volume_ml": 5.0, "spot_head_volume_ml": 3.0})
        self.assertEqual(flush["Sampling_clean_mode"], 1)
        self.assertEqual(flush["Sampling_clean_count"], 1)
        self.assertEqual(flush["Sampling_clean_instructions"],
                         s2.build_flush_array(17.0, 5.0, 3.0))

    # ---- 点样后润洗吹打混匀 build_rinse_mix_array (A55) ----
    def test_rinse_mix_array_exact_commands_and_gap_invariant(self) -> None:
        commands = s2.build_rinse_mix_array(
            2.0, 1.5,
            asp_speed=200, disp_speed=150, step_delay=500,
        )
        self.assertEqual(commands, [
            "/4V150I3A0M500R\r",  # 当前余量经上样针回打原孔, 泵归 A0
            "/4V200I1A480M500V150I3A0M500R\r",  # 口1吸2mL, 口3打入原孔
            "/4V200I3A48M500R\r",  # 抬针后吸 0.2mL 气隔断至 A48
            "/4V200I3A408M500V150I3A48M500R\r",  # 口3吸1.5mL至A408再打回A48, 隔断保留
        ])
        # 不变量: 前两条以 A0 收尾, 后两条以 A{gap}=A48 收尾 (终态活塞停在气隔断位)
        self.assertTrue(all(cmd.endswith("A0M500R\r") for cmd in commands[:2]))
        self.assertTrue(all(cmd.endswith("A48M500R\r") for cmd in commands[2:]))

    def test_rinse_mix_array_rejects_invalid_volume_or_speed(self) -> None:
        for rinse_ml, mix_ml in ((0.0, 1.0), (25.1, 1.0), (1.0, 0.0), (1.0, 25.1)):
            with self.subTest(rinse_ml=rinse_ml, mix_ml=mix_ml):
                with self.assertRaises(ValueError):
                    s2.build_rinse_mix_array(rinse_ml, mix_ml)
        # 气隔断守卫: 非正值 / 与吹打体积之和超量程
        with self.assertRaises(ValueError):
            s2.build_rinse_mix_array(1.0, 1.0, 0.0)
        with self.assertRaises(ValueError):
            s2.build_rinse_mix_array(1.0, 24.9, 0.2)
        with self.assertRaises(ValueError):
            s2.build_rinse_mix_array(1.0, 1.0, asp_speed=501)
        with self.assertRaises(ValueError):
            s2.build_rinse_mix_array(1.0, 1.0, disp_speed=501)

    def test_rinse_mix_profile_channels_and_count_guard(self) -> None:
        values = {
            "rinse_volume_ml": 2.0,
            "mix_volume_ml": 1.5,
            "mix_count": 3,
        }
        channels = PUMP_PROFILES["sampling.rinse_mix"].build(values)
        self.assertEqual(
            set(channels),
            {"Sampling_rinse_mix_instructions", "Sampling_rinse_mix_count"},
        )
        self.assertEqual(channels["Sampling_rinse_mix_count"], 3)
        self.assertEqual(
            channels["Sampling_rinse_mix_instructions"],
            s2.build_rinse_mix_array(2.0, 1.5),
        )
        # air_gap_ml knob 透传: 显式 0.5 → 与直接构建 0.5 一致
        gap_channels = PUMP_PROFILES["sampling.rinse_mix"].build({**values, "air_gap_ml": 0.5})
        self.assertEqual(
            gap_channels["Sampling_rinse_mix_instructions"],
            s2.build_rinse_mix_array(2.0, 1.5, 0.5),
        )
        with self.assertRaises(ValueError):
            PUMP_PROFILES["sampling.rinse_mix"].build({**values, "mix_count": 0})
        with self.assertRaises(ValueError):
            PUMP_PROFILES["sampling.rinse_mix"].build({**values, "mix_count": 21})


def _walk(nodes):
    """递归遍历 operation 节点 (所有子块: then/else/body/finally/elifs/catch/branches)。"""
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("then", "else", "body", "finally"):
            yield from _walk(node.get(key))
        for br in node.get("elifs") or []:
            yield from _walk(br.get("body"))
        for handler in node.get("catch") or []:
            yield from _walk(handler.get("body"))
        for branch in node.get("branches") or []:
            yield from _walk(branch)


class RecipeIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.valid_actions = {a.name for a in registry.list()}
        cls.docs: dict[str, dict] = {}
        for path in sorted(_OPERATION_DIR.glob("**/*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cls.docs[doc["name"]] = doc

    def test_all_operations_validate(self) -> None:
        for name, doc in self.docs.items():
            with self.subTest(operation=name):
                errors = validate_script(doc, valid_actions=self.valid_actions)
                self.assertEqual(errors, [], f"{name}: {errors}")

    def test_run_script_refs_resolve(self) -> None:
        names = set(self.docs)
        for op_name, doc in self.docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") == "run_script":
                    target = node.get("script")
                    with self.subTest(operation=op_name, ref=target):
                        self.assertIn(target, names, f"{op_name} 悬空 run_script 引用: {target}")

    def test_top_recipe_present_and_closed(self) -> None:
        self.assertIn("ptlc_full_v2", self.docs, "顶层 recipe ptlc_full_v2 缺失")
        refs = {n.get("script") for n in _walk(self.docs["ptlc_full_v2"].get("body"))
                if n.get("op") == "run_script"}
        missing = refs - set(self.docs)
        self.assertFalse(missing, f"ptlc_full_v2 调用图悬空引用: {sorted(missing)}")


class SamplingExecuteVolumeChainTests(unittest.TestCase):
    """过阀排空点样体积链 (V=2 缺省场景) 的编排-指令闭环断言。

    模型: 首轮 aspirate 内置吸 G(0.2) -> P(V+E=3.5) -> spot 到 N=D+G/2=1.225;
    润洗轮 rinse_mix(终态A{G}, 润洗液 R 全量入孔) -> aspirate P(R+E=4.5) -> spot 到同一 N。

    派生与守卫的表达式住在 sampling_volume_model (单样品的 sampling_execute 与多样品的
    sampling_multi_execute 共用同一份), 旋钮缺省仍读 sampling_execute —— 与运行时同构:
    execute 把自己的旋钮值传进模型子流程。两者的接线由 test_volume_model_is_wired_* 钉住。
    """

    @classmethod
    def setUpClass(cls) -> None:
        path = _OPERATION_DIR / "01_sampling" / "sampling_execute.yaml"
        cls.doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        model_path = _OPERATION_DIR / "01_sampling" / "sampling_volume_model.yaml"
        cls.model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
        cls.defaults = {v["name"]: v.get("default") for v in cls.doc.get("vars", [])}
        cls.actions = {a.name: a for a in ActionRegistry.load(_ACTIONS_DIR).list()}

    def _eval_derived(self, overrides: dict | None = None) -> dict:
        """按脚本顺序对体积模型的 op:assign 求值, 返回全部变量终值 (真源=YAML 里的表达式)。

        overrides 用于替换旋钮缺省值, 以便对多组入参跑同一套派生表达式。
        """
        from eit_ptlc.operation.vm.expr import eval_expr
        env = dict(self.defaults)
        env.update(overrides or {})
        for node in self.model.get("body", []):
            if node.get("op") == "assign":
                env[node["target"]["var"]] = eval_expr(node["value"], env.__getitem__)
        return env

    def test_volume_model_is_wired_to_execute_with_matching_defaults(self) -> None:
        """体积模型外提后仍须真正接在 execute 上, 且两边缺省同值。

        脱钩的两种形态都在此拦: (a) execute 不再 run_script 模型 (派生量永远是 0, 点样
        活塞终点变 0 → 样品推不出去); (b) 模型自己的 in 缺省与面板旋钮缺省漂移 (面板显示
        一套、实际算另一套)。本例连同 _eval_derived 的取值来源一起构成"改一处即两处同步"。
        """
        calls = [n for n in self.doc.get("body", [])
                 if n.get("op") == "run_script" and n.get("script") == "sampling_volume_model"]
        self.assertEqual(len(calls), 1, "sampling_execute 必须且只须调用一次体积模型")
        inputs, outputs = calls[0].get("inputs") or {}, calls[0].get("outputs") or {}
        self.assertEqual(
            inputs,
            {name: {"var": name} for name in
             ("sample_volume_ml", "over_aspirate_ml", "air_gap_ml", "rinse_volume_ml")})
        self.assertEqual(
            outputs,
            {name: {"var": name} for name in
             ("spray_margin_ml", "aspirate_total_ml", "band_end_ml", "aspirate_round_ml")})

        model_defaults = {v["name"]: v.get("default") for v in self.model.get("vars", [])}
        for name in inputs:
            with self.subTest(var=name):
                self.assertAlmostEqual(float(model_defaults[name]), float(self.defaults[name]))

    def test_derived_volumes_default_2ml_scenario(self) -> None:
        env = self._eval_derived()
        self.assertAlmostEqual(env["aspirate_total_ml"], 3.5)   # V2 + E1.5
        self.assertAlmostEqual(env["spray_margin_ml"], 0.475)   # (E1.5-1.125) + G0.2/2, 窗口正中
        self.assertAlmostEqual(env["band_end_ml"], 1.225)       # = 1.125 + G0.2/2 (E 数学抵消)
        self.assertAlmostEqual(env["aspirate_round_ml"], 4.5)   # R3 (全量入孔) + E1.5

    def _ceiling_literals(self) -> dict:
        """取出守卫里对各派生量做 '>' 比较的字面量 (真源=YAML 表达式树)。"""
        found: dict[str, float] = {}

        def walk(node) -> None:
            if isinstance(node, dict):
                right = node.get("right")
                left = node.get("left")
                if (node.get("binop") == ">" and isinstance(left, dict) and "var" in left
                        and isinstance(right, dict) and "lit" in right):
                    found[left["var"]] = float(right["lit"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(self.model.get("body"))
        return found

    def test_aspirate_ceiling_guard_matches_action_hard_limit(self) -> None:
        """吸取总量上限: 编排守卫字面量必须与 sampling.aspirate 动作层硬闸同值。

        物理来源是针尖到泵腔的距离 = 针流路 1.125 + 泵至三通共管 15.7 = 16.825 mL,
        吸入量超过它样品段就被抽进注射器筒 —— "样品不进泵腔"原则破功, 而 PLC 的
        6000 步(=25mL)行程闸拦不住。两处若脱钩就会出现"编排放行、动作层拒"的缝隙,
        且要跑到该动作才炸(此时首轮点样已完成), 故在此钉死。
        """
        param = next(p for p in self.actions["sampling.aspirate"].params
                     if p.name == "sample_volume_ml")
        ceiling = float(param.maximum)
        self.assertLess(ceiling, 1.125 + 15.7, "动作上限必须留在针尖→泵腔的物理距离以内")
        guarded = self._ceiling_literals()
        for name in ("aspirate_total_ml", "aspirate_round_ml"):
            with self.subTest(var=name):
                self.assertIn(name, guarded, f"守卫缺少对 {name} 的上限检查")
                self.assertAlmostEqual(guarded[name], ceiling)

    def test_every_round_keeps_over_aspirate_above_dead_volume(self) -> None:
        """每轮的"抽干后多吸空气量"必须 > 针流路死体积, 否则液段没被整段拖过三通。

        多吸空气量 = 吸取总量 - 孔内实际液量。首轮孔内=V, 润洗轮孔内=R
        (A55 的[1]推出量 N=D+G/2 全是空气, 针流路在加润洗液前已被共管清洗液填满,
        故 R 全量入孔, 不存在"针流路空气置换"扣减)。二者都必须留出 E 的余量。
        """
        dead = 1.125
        for over, gap, sample, rinse in ((1.5, 0.2, 2.0, 3.0), (1.2, 0.1, 0.5, 1.5),
                                         (3.0, 1.0, 5.0, 8.0), (5.0, 0.5, 1.0, 25.0)):
            derived = self._eval_derived({
                "over_aspirate_ml": over, "air_gap_ml": gap,
                "sample_volume_ml": sample, "rinse_volume_ml": rinse,
            })
            with self.subTest(over=over, rinse=rinse):
                self.assertAlmostEqual(derived["aspirate_total_ml"] - sample, over)
                self.assertAlmostEqual(derived["aspirate_round_ml"] - rinse, over)
                self.assertGreater(over, dead, "排空余量必须大于针流路死体积")

    def test_spray_margin_is_derived_and_stays_in_physical_window(self) -> None:
        """S 无独立自由度: 不得是 in 旋钮; 且对全域 E/G 恒落在 (E-D, E-D+G) 开区间正中。"""
        spray = next(v for v in self.doc["vars"] if v["name"] == "spray_margin_ml")
        self.assertEqual(spray["io"], "var")
        self.assertNotIn("ui", spray)
        dead = 1.125
        for over, gap in ((1.2, 0.05), (1.5, 0.2), (3.0, 0.5), (5.0, 1.0)):
            with self.subTest(over=over, gap=gap):
                margin = (over - dead) + gap / 2.0
                self.assertGreater(margin, over - dead)          # 样品尾巴推得完
                self.assertLess(margin, over - dead + gap)       # 不推穿气隔断
                # N 与 E 无关, 恒等于 死体积 + 半个气隔断, 且在 translator 合法域内
                self.assertAlmostEqual(gap + over - margin, dead + gap / 2.0)
                self.assertLessEqual(gap + over - margin, s2.SPOT_END_POSITION_MAX_ML)

    def test_air_gap_knob_range_is_subset_of_every_consuming_action(self) -> None:
        """气隔断旋钮域必须是各消费动作参数域的子集。

        动作层 executor._validate 对 min/max 是硬闸 (越界直接 REJECTED)。旋钮域若比
        动作域宽, 中间那段就是"面板允许但运行时必拒"的不可达区间 —— 且要等流程跑到
        该动作才炸 (此时 prepare 的充液润洗已耗掉整支溶剂), 故用本例钉死包含关系。
        """
        knob = next(v for v in self.doc["vars"] if v["name"] == "air_gap_ml")["ui"]
        lo, hi = float(knob["min"]), float(knob["max"])
        consumers = (("sampling.aspirate", "air_gap_ml"), ("sampling.rinse_mix", "air_gap_ml"),
                     ("sampling.prep", "air_buffer_ml"))  # prep 仍供 legacy/单动作调试, 同域
        for action_name, param_name in consumers:
            with self.subTest(action=action_name, param=param_name):
                param = next(p for p in self.actions[action_name].params if p.name == param_name)
                self.assertIsNotNone(param.minimum, f"{action_name}.{param_name} 缺 min")
                self.assertIsNotNone(param.maximum, f"{action_name}.{param_name} 缺 max")
                self.assertGreaterEqual(lo, float(param.minimum))
                self.assertLessEqual(hi, float(param.maximum))
                # 旋钮缺省值也必须能过动作层校验
                self.assertGreaterEqual(float(self.defaults["air_gap_ml"]), float(param.minimum))
                self.assertLessEqual(float(self.defaults["air_gap_ml"]), float(param.maximum))

    def test_derived_volumes_translate_to_expected_dt_steps(self) -> None:
        env = self._eval_derived()
        # 首轮吸取: [1] P840 相对回抽 (3.5mL) + [2] A48 绝对气隔断 (0.2mL×240步/mL), 由 A50 一并消费
        first = PUMP_PROFILES["sampling.aspirate"].build({
            "sample_volume_ml": env["aspirate_total_ml"],
            "air_gap_ml": env["air_gap_ml"],
        })
        self.assertIn("P840", first["Sampling_sample_instructions"][0])
        self.assertIn("A48", first["Sampling_sample_instructions"][1])
        # 点样终点: A294 + 判终节点同源 (1.225mL = 死体积1.125 + 半个气隔断0.1)
        spot = PUMP_PROFILES["sampling.spot_band_layer"].build({
            "spot_end_position_ml": env["band_end_ml"],
            "spot_speed_mm_s": 5.0, "dry_speed_mm_s": 20.0, "dry_cycles": 1,
        })
        self.assertIn("A294", spot["Sampling_band_run_instruction"])
        self.assertEqual(spot["Sampling_band_end_position"], 294)
        # 润洗轮吸取: P1080 (4.5mL); [2] 仍是 A48 但因 A55 终态已在 A48 而为零位移
        rnd = PUMP_PROFILES["sampling.aspirate"].build({
            "sample_volume_ml": env["aspirate_round_ml"],
            "air_gap_ml": env["air_gap_ml"],
        })
        self.assertIn("P1080", rnd["Sampling_sample_instructions"][0])
        self.assertEqual(rnd["Sampling_sample_instructions"][1],
                         first["Sampling_sample_instructions"][1])

    def test_execute_wires_derived_vars_and_round_loop(self) -> None:
        calls = [n for n in _walk(self.doc.get("body")) if n.get("op") == "call"]
        aspirates = [n for n in calls if n.get("action") == "sampling.aspirate"]
        spots = [n for n in calls if n.get("action") == "sampling.spot_band_layer"]
        rinses = [n for n in calls if n.get("action") == "sampling.rinse_mix"]
        preps = [n for n in calls if n.get("action") == "sampling.prep"]
        self.assertEqual(len(aspirates), 2)
        self.assertEqual(len(spots), 2)
        self.assertEqual(len(rinses), 1)
        # 首轮吸 aspirate_total, 润洗轮吸 aspirate_round
        self.assertEqual(aspirates[0]["args"]["sample_volume_ml"], {"var": "aspirate_total_ml"})
        self.assertEqual(aspirates[1]["args"]["sample_volume_ml"], {"var": "aspirate_round_ml"})
        # 两处点样均显式传活塞终点 (覆盖 config.pump 旧标定值)
        for spot in spots:
            self.assertEqual(spot["args"]["spot_end_position_ml"], {"var": "band_end_ml"})
        # 气隔断由 A50 内置: 两处 aspirate 都传 (润洗轮为零位移的幂等兜底), rinse_mix 亦带
        for asp in aspirates:
            self.assertEqual(asp["args"]["air_gap_ml"], {"var": "air_gap_ml"})
        self.assertEqual(rinses[0]["args"]["air_gap_ml"], {"var": "air_gap_ml"})
        # prep 已被 A50 内置吸气段取代, execute 不再调用 (动作本身保留供 legacy/单动作调试)
        self.assertEqual(preps, [])
        # N 轮循环由 rinse_rounds 驱动
        loops = [n for n in _walk(self.doc.get("body")) if n.get("op") == "for"]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["stop"], {"var": "rinse_rounds"})


class ThreeDPumpActionTableTests(unittest.TestCase):
    """三维注射泵动作表 ↔ 动作 YAML 的参数名契约。

    三维侧 gen_twin_manifest.PUMP_SYRINGE_ACTIONS 按参数名从动作事件的 args 里取体积,
    取不到就静默走 fallback(或按 0 算)。于是 solvent_volume_ml 这类参数一旦改名, 现象
    是"柱塞照跑但幅度不对/根本不动", 没有任何报错 —— 三维那边也不可能有人天天盯。
    本测试是这条链路上唯一的防线: 动作表引用的每个参数名都必须在对应动作 YAML 里
    真的声明过。

    只查参数名存在性, 不查语义 —— 语义(哪个参数该乘几趟)属于观感, 由目检收尾。
    """

    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(_PKG / "three_d" / "pipeline"))
        from gen_twin_manifest import PUMP_SYRINGE_ACTIONS  # noqa: E402
        cls.table = PUMP_SYRINGE_ACTIONS
        cls.actions = {a.name: a for a in ActionRegistry.load(_ACTIONS_DIR).list()}

    @staticmethod
    def _referenced_params(spec: dict) -> set[str]:
        """收齐一条动作表条目引用到的全部入参名(含 repeatFrom / 内层 loop)。"""
        names: set[str] = set()
        if spec.get("repeatFrom"):
            names.add(spec["repeatFrom"])
        if spec.get("pump", {}).get("from") == "tankGroup":
            names.add(spec["pump"]["arg"])
        loop = spec.get("loop") or {}
        if loop.get("repeatFrom"):
            names.add(loop["repeatFrom"])
        for phase in list(spec.get("phases") or []) + list(loop.get("phases") or []):
            for key in ("toFrom", "byFrom"):
                names.update((phase.get(key) or {}).get("add") or [])
        return names

    def test_every_referenced_param_is_declared(self) -> None:
        """动作表引用的参数名必须都在动作 YAML 的 params 里。"""
        for action_name, spec in self.table.items():
            with self.subTest(action=action_name):
                action = self.actions.get(action_name)
                self.assertIsNotNone(
                    action, f"三维动作表引用了不存在的动作 {action_name}")
                declared = {p.name for p in (action.params or ())}
                for name in self._referenced_params(spec):
                    self.assertIn(
                        name, declared,
                        f"{action_name} 的三维动作表引用了 {name}, 但该动作没声明这个参数 "
                        f"—— 参数改名会让三维静默按 fallback 画, 两边必须一起改")

    def test_phases_are_scripts_not_single_targets(self) -> None:
        """每条都必须是相位脚本: 单目标模型下"吸满→打空"的往复运动会整个消失。"""
        for action_name, spec in self.table.items():
            with self.subTest(action=action_name):
                self.assertTrue(
                    spec.get("phases"),
                    f"{action_name} 缺 phases —— 起终都是 0 的动作会表现为柱塞纹丝不动")

    def test_ports_are_within_the_valve_channel_count(self) -> None:
        """动作表里的阀口号必须落在该泵阀头的通道数内, 且 "output" 必须真有出口可解析。

        三维靠这些口号转阀指针。写超范围(比如给 T-04 写第 6 口)会被前端悄悄丢弃 ——
        表现是"阀就是不转", 没有任何报错; 而写错到另一个合法口, 表现是"转到了错的口",
        更看不出来。口号的真源是 tools/pump/*.py 生成的 DT 指令串, 本测试守的是范围。
        """
        import re as _re
        rig = yaml.safe_load(
            (_PKG / "three_d" / "pipeline" / "rig_map.yaml").read_text(encoding="utf-8"))
        items = {i["id"]: i for i in (rig.get("pumps") or {}).get("items") or []}

        def channels(item: dict) -> int:
            """功能: 从阀型号尾数取通道数(T-04→4). 参数: item. 返回值: int"""
            match = _re.search(r"(\d+)\s*$", str(item.get("valve") or ""))
            return int(match.group(1)) if match else 0

        for action_name, spec in self.table.items():
            pump = spec.get("pump") or {}
            if pump.get("from") == "fixed":
                targets = [items[pump["id"]]] if pump.get("id") in items else []
            else:   # tankGroup 路由: 该动作会落到任何一台带缸组的泵上
                targets = [i for i in items.values() if i.get("tank_group")]
            loop = spec.get("loop") or {}
            phases = list(spec.get("phases") or []) + list(loop.get("phases") or [])
            for order, phase in enumerate(phases):
                port = phase.get("port")
                if port is None:
                    continue
                for item in targets:
                    with self.subTest(action=action_name, phase=order, pump=item["id"]):
                        total = channels(item)
                        self.assertGreater(total, 0, f'泵 {item["id"]} 的 valve 型号取不出通道数')
                        if port == "output":
                            self.assertIsNotNone(
                                item.get("output_port"),
                                f'{action_name} 用了 "output", 但泵 {item["id"]} 没声明 '
                                f"output_port —— 前端会解析成 null 而静默不转阀")
                            port = item["output_port"]
                        self.assertTrue(
                            1 <= int(port) <= total,
                            f'{action_name} 第 {order} 相位的口号 {port} 超出泵 '
                            f'{item["id"]} 的 {item.get("valve")} 阀({total} 通)范围')

    def test_every_phase_speed_key_is_declared_by_its_action(self) -> None:
        """每个相位声明的速度档必须是该动作 YAML 真的暴露过的参数名。

        三维按 `t = 步数/V + M/1000` 算相位时长(换算真源 tools/pump/mvp_staged_clean.py:106),
        V 从这个档名取。写错档名的现象是**静默退回动作表里那个写死的 rampS** —— 动画照跑,
        只是时序与实机对不上, 没有任何报错。

        尤其防的是上样站那几个专用档: sampling.spot 走 spot_disp_speed(9)、
        sampling.flush 末段走 spot_head_disp_speed(100), 拿 disp_speed(100/300) 顶替
        会让点样快十倍。
        """
        for action_name, spec in self.table.items():
            action = self.actions.get(action_name)
            declared = {p.name for p in (action.params or ())} if action else set()
            loop = spec.get("loop") or {}
            phases = list(spec.get("phases") or []) + list(loop.get("phases") or [])
            for order, phase in enumerate(phases):
                key = phase.get("speed")
                if key is None:
                    continue            # 无体积变化的相位(home)不需要速度档
                with self.subTest(action=action_name, phase=order):
                    self.assertIn(
                        key, declared,
                        f"{action_name} 第 {order} 相位声明用 {key} 算时长, 但该动作没暴露"
                        f"这个参数 —— 三维会静默退回写死的 rampS, 时序与实机对不上")

    def test_manifest_port_angles_match_the_channel_count(self) -> None:
        """出厂 manifest 里 valvePortAngles 必须与 valvePorts 等长、且落在 [0, 360)。

        实物阀头的接口全挤在下半圈, 不是 360° 均布(2026-08-05 按实物返工)。前端拿这张
        角度表把指针转到选中口; 表长度对不上就会**静默退回均布**, 现象是指针转到接针筒的
        平口那侧 —— 那里一个口都没有, 而画面上只是"指得有点怪", 不会报错。

        角度表由 03 的几何直接产出(建了几个接头就有几个角), 所以它同时也是"通道数改了但
        几何没跟着重建"的探针。
        """
        manifest = json.loads(
            (_PKG / "three_d" / "models" / "device-manifest.json").read_text(encoding="utf-8"))
        pumps = ((manifest.get("pumpSyringe") or {}).get("pumps")) or []
        self.assertTrue(pumps, "manifest 里没有 pumpSyringe.pumps —— 三维泵段整个没生成")
        for pump in pumps:
            with self.subTest(pump=pump.get("id")):
                angles = pump.get("valvePortAngles")
                if not angles:
                    # 没建几何的泵(collect 泵 CAD 里没有泵体)允许缺表, 前端退回均布
                    self.assertFalse(
                        pump.get("rigged"),
                        f'泵 {pump.get("id")} 标了 rigged 却没有 valvePortAngles —— '
                        f"多半是 manifest 陈旧(这一项 2026-08-05 才随阀头返工加上), "
                        f"重跑管线的 gen_twin_manifest 那一步即可; 若重跑后仍缺, "
                        f"才是 03 的 valve_port_angles 没产出")
                    continue
                self.assertEqual(
                    len(angles), int(pump.get("valvePorts") or 0),
                    f'泵 {pump.get("id")} 的角度表 {len(angles)} 项对不上 '
                    f'valvePorts={pump.get("valvePorts")} —— 前端会静默退回 360° 均布')
                for order, angle in enumerate(angles):
                    self.assertTrue(0.0 <= float(angle) < 360.0,
                                    f'泵 {pump.get("id")} 第 {order} 个口的角 {angle} 越界')

    def test_fixed_pump_ids_exist_in_rig_map(self) -> None:
        """fixed 路由的泵 id 必须在 rig_map.pumps 里声明过。"""
        rig_map = yaml.safe_load(
            (_PKG / "three_d" / "pipeline" / "rig_map.yaml").read_text(encoding="utf-8"))
        known = {item["id"] for item in (rig_map.get("pumps") or {}).get("items") or []}
        for action_name, spec in self.table.items():
            pump = spec.get("pump") or {}
            if pump.get("from") == "fixed":
                with self.subTest(action=action_name):
                    self.assertIn(pump["id"], known,
                                  f"{action_name} 指向 rig_map 里没有的泵 {pump['id']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
