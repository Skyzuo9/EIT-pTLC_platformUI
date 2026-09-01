#!/usr/bin/env python3
"""Develop station phase-2/four-stage guard tests.

These tests intentionally stay narrow: they document the current station-local
closure without claiming hardware validation. Drain is required to stay on the
PLC L2 + ActionExecutor path; raw PLC writes are not an acceptable substitute.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.action.models import ActionResult, ActionStatus  # noqa: E402
from eit_ptlc.action.executor import ActionExecutor  # noqa: E402
from eit_ptlc.operation.resources import ResourceGate  # noqa: E402
from eit_ptlc.operation.vm.knobs import collect_knobs, validate_overrides  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402
from eit_ptlc.operation.vm.state import VmStatus  # noqa: E402
from eit_ptlc.operation.vm.thread import VmThread  # noqa: E402
from eit_ptlc.tools.pump.profiles import PUMP_PROFILES  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"
_OPERATION_DIR = _PKG / "config" / "operation"
_DEVELOP_OP_DIR = _PKG / "config" / "operation" / "02_develop"

_DEVELOP_ACTIONS = {
    "develop.init",
    "develop.clean_line",
    "develop.rinse_fill",
    "develop.rinse_suction",
    "develop.fill",
    "develop.drain",
    "develop.release_tank",
    "develop.plate_retract",
    "develop.plate_extend",
}

_NON_PROFILE_CHANNEL_ACTIONS = {
    "develop.init",
    "develop.rinse_suction",
    "develop.drain",
    "develop.release_tank",
    "develop.plate_retract",
    "develop.plate_extend",
}


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _walk(nodes):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("then", "else", "body", "finally"):
            yield from _walk(node.get(key))
        for branch in node.get("branches") or []:
            yield from _walk(branch)
        for handler in node.get("catch") or []:
            yield from _walk(handler.get("body"))
        for elif_branch in node.get("elifs") or []:
            yield from _walk(elif_branch.get("body"))


def _event(node: dict) -> tuple[str, str, dict]:
    if node.get("op") == "call":
        return ("call", node.get("action", ""), node.get("args") or {})
    if node.get("op") == "run_script":
        return ("run_script", node.get("script", ""), node.get("inputs") or {})
    return (node.get("op", ""), "", {})


def _events(doc: dict) -> list[tuple[str, str, dict]]:
    return [_event(node) for node in _walk(doc.get("body")) if node.get("op") in {"call", "run_script"}]


def _index(events: list[tuple[str, str, dict]], kind: str, name: str) -> int:
    for i, (event_kind, event_name, _args) in enumerate(events):
        if event_kind == kind and event_name == name:
            return i
    raise AssertionError(f"missing event {kind}:{name}")


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append((name, dict(params or {})))
        return ActionResult(
            action=name,
            request_id=request_id or "test",
            status=ActionStatus.DONE,
            accepted=True,
            message="ok",
            result={},
        )


class DevelopFourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.actions = {action.name: action for action in cls.registry.list()}
        cls.docs = {
            path.stem: _load_yaml(path)
            for path in sorted(_DEVELOP_OP_DIR.glob("*.yaml"))
        }

    def test_develop_scripts_validate(self) -> None:
        valid_actions = set(self.actions)
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_develop_run_script_references_exist(self) -> None:
        all_script_names = {path.stem for path in _OPERATION_DIR.glob("*/*.yaml")}
        for name, doc in self.docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") == "run_script":
                    with self.subTest(script=name, child=node.get("script")):
                        self.assertIn(node.get("script"), all_script_names)

    def test_develop_actions_keep_target_tank_contract(self) -> None:
        self.assertLessEqual(_DEVELOP_ACTIONS, set(self.actions))
        for name in sorted(_DEVELOP_ACTIONS):
            action = self.actions[name]
            param = action.param("target_tank")
            self.assertIsNotNone(param, f"{name} missing target_tank")
            self.assertTrue(param.required, f"{name}.target_tank must be required")
            self.assertEqual(param.type, "int")
            self.assertEqual(param.minimum, 1)
            self.assertEqual(param.maximum, 8)
            if name in _NON_PROFILE_CHANNEL_ACTIONS:
                self.assertEqual(param.channel, "Expand_Target_Tank")
            else:
                self.assertIn(name, PUMP_PROFILES)

    def test_develop_pump_actions_expose_exactly_four_solvent_ratios(self) -> None:
        expected = {f"solvent_ratio_{i}" for i in range(1, 5)}
        executor = ActionExecutor(self.registry)
        for name in ("develop.clean_line", "develop.rinse_fill", "develop.fill"):
            with self.subTest(action=name):
                declared = {param.name for param in self.actions[name].params}
                self.assertEqual(
                    {item for item in declared if item.startswith("solvent_ratio_")},
                    expected,
                )
                self.assertNotIn("solvent_ratio_5", declared)
                ok, _coerced, message = executor._validate(
                    self.actions[name],
                    {"target_tank": 1, "solvent_ratio_5": 1.0},
                )
                self.assertFalse(ok)
                self.assertIn("solvent_ratio_5", message)

    def test_plate_cylinder_has_both_l2_directions(self) -> None:
        retract = self.actions["develop.plate_retract"]
        extend = self.actions["develop.plate_extend"]
        self.assertEqual((retract.kind, retract.station, retract.action_code), ("plc_l2", "develop", 31))
        self.assertEqual((extend.kind, extend.station, extend.action_code), ("plc_l2", "develop", 32))

    def test_plate_cylinder_calls_pin_run_mode(self) -> None:
        # 放板/入缸气缸 L2 动作必须显式 mode: RUN —— 缸动作与会话模式无关, mode:null 会落到
        # 会话模式, 非 RUN 会话下与强制 RUN 的兄弟动作失步 (develop_load 的 plate_retract 曾漏成 null)。
        for op_name, doc in self.docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") == "call" and node.get("action") in (
                    "develop.plate_retract", "develop.plate_extend",
                ):
                    with self.subTest(operation=op_name, action=node.get("action")):
                        self.assertEqual(
                            node.get("mode"), "RUN",
                            f"{op_name}:{node.get('action')} 应 mode: RUN, 得到 {node.get('mode')!r}",
                        )

    def test_drain_has_l2_closed_loop_actions(self) -> None:
        drain = self.actions["develop.drain"]
        release = self.actions["develop.release_tank"]
        self.assertEqual((drain.kind, drain.station, drain.action_code), ("plc_l2", "develop", 50))
        self.assertEqual((release.kind, release.station, release.action_code), ("plc_l2", "develop", 51))
        self.assertGreaterEqual(drain.stall_timeout or 0, 120.0)
        self.assertGreaterEqual(drain.action_timeout or 0, 600.0)

    def test_develop_pump_actions_pin_stall_and_ceiling_budgets(self) -> None:
        # 单趟吸+打为泵内原子执行, 全程 L2 字段静默 (真机曾以 20mL@V100≈97s 撞全局 60s 停滞判停);
        # 停滞预算须覆盖 液量上限 25mL @ 旋钮速度下限 V50 ≈ 240s, 绝对上限须严格大于停滞预算
        for name in ("develop.rinse_fill", "develop.fill"):
            action = self.actions[name]
            with self.subTest(action=name):
                self.assertEqual(action.stall_timeout, 300.0)
                self.assertEqual(action.action_timeout, 1800.0)
                self.assertGreater(action.action_timeout, action.stall_timeout)
        # rinse_suction: PLC 废液传感器自判窗口 (cap_s, 402) 已参数化, 停滞预算须严格大于其上限
        # 让 PLC 先裁决 (否则竞态把明确的 402 错报为结果不明确); 逐项不变式见下一用例
        suction = self.actions["develop.rinse_suction"]
        self.assertEqual(suction.stall_timeout, 180.0)
        self.assertIsNone(suction.action_timeout)

    def test_rinse_suction_durations_are_host_tunable_within_stall_budget(self) -> None:
        """A26 四个时长参数化后的契约与时长不变式。

        A26 全程不写 Develop_L2_Step (8 个 L2 字段静默), 停滞看门狗从动作开始一路计到结束,
        故 stall_timeout 必须覆盖整动作最坏时长, 而非单段:
            成功路径 = max(settle_s, empty_s) + blow_s   (step0 两定时器并行起算, 再进吹气段)
            失败路径 = cap_s                              (402 直接结束, 不进吹气段)
        放宽任一参数 max 或调小 stall_timeout 都会在此处失败。
        """
        suction = self.actions["develop.rinse_suction"]
        params = {p.name: p for p in suction.params}
        # PLC 侧 Host_Computer 同名变量初值须与这些 default 一致 (通道写不进来时的唯一兜底)
        expected = {"settle_s": ("Tank_Suction_Settle_S", 3.0),
                    "empty_s": ("Tank_Suction_Empty_S", 10.0),
                    "blow_s": ("Tank_Suction_Blow_S", 30.0),
                    "cap_s": ("Tank_Suction_Cap_S", 120.0)}
        for name, (channel, default) in expected.items():
            with self.subTest(param=name):
                param = params.get(name)
                self.assertIsNotNone(param, f"rinse_suction 缺时长参数 {name}")
                self.assertEqual(param.channel, channel)
                self.assertFalse(param.required)
                # 缺 default 会退化成"PLC 保持旧值", 对超时参数是隐性状态残留
                self.assertEqual(param.default, default)
                self.assertIsNotNone(param.minimum)
                self.assertIsNotNone(param.maximum)

        stall = float(suction.stall_timeout)
        worst_ok = max(float(params["settle_s"].maximum), float(params["empty_s"].maximum)) \
            + float(params["blow_s"].maximum)
        worst_fail = float(params["cap_s"].maximum)
        self.assertLess(worst_ok, stall, f"成功路径最坏 {worst_ok}s 须 < stall_timeout {stall}s")
        self.assertLess(worst_fail, stall, f"402 窗口上限 {worst_fail}s 须 < stall_timeout {stall}s")

    def test_rinse_suction_knob_ranges_are_subset_of_action_params(self) -> None:
        """两个抽吸旋钮的域必须 ⊆ 动作参数域 (动作层 min/max 是硬闸, 越界直接 REJECTED)。

        旋钮域若比动作域宽, 中间那段就是"面板允许但运行时必拒"的不可达区间, 且要等流程跑到
        rinse_suction 才炸 (此时润洗注液已耗掉溶剂), 故用本例钉死包含关系。
        """
        doc = self.docs["develop_prepare"]
        knobs = {v["name"]: v for v in doc["vars"]}
        params = {p.name: p for p in self.actions["develop.rinse_suction"].params}
        for knob_name, param_name in (("tank_suction_empty_s", "empty_s"),
                                      ("tank_suction_cap_s", "cap_s")):
            with self.subTest(knob=knob_name):
                knob = knobs[knob_name]
                param = params[param_name]
                lo, hi = float(knob["ui"]["min"]), float(knob["ui"]["max"])
                self.assertGreaterEqual(lo, float(param.minimum))
                self.assertLessEqual(hi, float(param.maximum))
                # 旋钮缺省值也必须能过动作层校验, 且与动作 default 同口径
                self.assertEqual(float(knob["default"]), float(param.default))

    def test_develop_operation_call_args_match_action_contracts(self) -> None:
        for op_name, doc in self.docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") != "call":
                    continue
                action_name = node.get("action")
                action = self.actions[action_name]
                args = set((node.get("args") or {}).keys())
                declared = {param.name for param in action.params}
                required = {
                    param.name
                    for param in action.params
                    if param.required and param.default is None
                }
                with self.subTest(operation=op_name, action=action_name):
                    self.assertLessEqual(args, declared)
                    self.assertLessEqual(required, args)

    def test_develop_station_task_and_phase_ui_contract(self) -> None:
        task_names = [
            name
            for name, doc in self.docs.items()
            if doc.get("ui", {}).get("role") == "station_task"
            and doc.get("ui", {}).get("station") == "develop"
        ]
        self.assertEqual(task_names, ["develop_cycle"])

        task_ui = self.docs["develop_cycle"].get("ui", {})
        self.assertTrue(task_ui.get("primary"))
        self.assertEqual(task_ui.get("order"), 20)
        self.assertFalse(task_ui.get("hidden", False))

        expected_phases = [
            ("develop_prepare", "prepare", 21),
            ("develop_load", "load", 22),
            ("develop_execute", "execute", 23),
            ("develop_unload", "unload", 24),
        ]
        phase_names = []
        for name, phase, order in expected_phases:
            with self.subTest(script=name):
                ui = self.docs[name].get("ui", {})
                self.assertEqual(ui.get("role"), "station_phase")
                self.assertEqual(ui.get("station"), "develop")
                self.assertEqual(ui.get("phase"), phase)
                self.assertTrue(ui.get("primary"))
                self.assertEqual(ui.get("order"), order)
                self.assertFalse(ui.get("hidden", False))
                phase_names.append(name)

        visible_develop_phases = [
            name
            for name, doc in sorted(
                self.docs.items(), key=lambda item: item[1].get("ui", {}).get("order", 999)
            )
            if doc.get("ui", {}).get("role") == "station_phase"
            and doc.get("ui", {}).get("station") == "develop"
            and not doc.get("ui", {}).get("hidden", False)
        ]
        self.assertEqual(visible_develop_phases, phase_names)

    def test_develop_cycle_is_four_stage_wrapper(self) -> None:
        non_comment_nodes = [
            node for node in self.docs["develop_cycle"].get("body", []) if node.get("op") != "comment"
        ]
        self.assertEqual(
            [(node.get("op"), node.get("script")) for node in non_comment_nodes],
            [
                ("run_script", "develop_prepare"),
                ("run_script", "develop_load"),
                ("run_script", "develop_execute"),
                ("run_script", "develop_unload"),
            ],
        )
        for node in non_comment_nodes:
            self.assertEqual(node.get("inputs"), {"tank": {"var": "tank"}})

    def test_develop_phase_actions_preserve_cycle_order(self) -> None:
        prepare_events = _events(self.docs["develop_prepare"])
        # 真空泵开关已由 with_resources(device:vacuum_pump) 区间接管, 编排层不再出现 pump.vacuum_*;
        # 区间落位由 test_vacuum_shared_resource_offline 守卫。
        self.assertEqual(
            [(kind, name) for kind, name, _ in prepare_events],
            [
                ("call", "develop.init"),
                ("call", "develop.plate_extend"),
                ("call", "develop.rinse_fill"),
                ("call", "develop.rinse_suction"),
                ("call", "develop.fill"),
            ],
        )

        prepare_names = [name for kind, name, _ in prepare_events if kind == "call"]
        self.assertNotIn("develop.plate_retract", prepare_names)
        # 清管由润洗第 1 轮承担 (A21 开阀后走同一条泵指令), prepare 不再单独调 clean_line
        self.assertNotIn("develop.clean_line", prepare_names)
        close_index = prepare_names.index("develop.plate_extend")
        for liquid_action in ("develop.rinse_fill", "develop.fill"):
            self.assertLess(close_index, prepare_names.index(liquid_action))

        load_events = _events(self.docs["develop_load"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in load_events],
            [
                # 放板前先缩缸让出空间 (幂等复位, 防上一循环残留展开态挡住机器人入缸),
                # 机器人放板到位后再关盖夹持; prepare 已关盖, 本动作是唯一 just-in-time 开盖。
                ("call", "develop.plate_retract"),
                ("run_script", "robot_tank_put"),
                ("call", "develop.plate_extend"),
            ],
        )

    def test_prepare_knobs_are_visible_from_prepare_cycle_and_top_recipe(self) -> None:
        expected = {
            "solvent_ratio_1", "solvent_ratio_2", "solvent_ratio_3", "solvent_ratio_4",
            "tank_rinse_volume_ml", "develop_volume_ml",
            "rinse_repeat_count", "up_liquid_repeat_count",
            "tank_asp_speed", "tank_disp_speed",
            "tank_suction_empty_s", "tank_suction_cap_s",
        }
        all_docs = {
            doc["name"]: doc
            for path in sorted(_OPERATION_DIR.glob("*/*.yaml"))
            if (doc := _load_yaml(path)).get("name")
        }
        for entry in ("develop_prepare", "develop_cycle", "ptlc_full_v2"):
            with self.subTest(entry=entry):
                knobs = collect_knobs(all_docs[entry], lambda name: all_docs[name])
                names = [knob["name"] for knob in knobs]
                self.assertLessEqual(expected, set(names))
                for name in expected:
                    self.assertEqual(names.count(name), 1)
                self.assertTrue(validate_overrides(knobs, {"tank_rinse_volume_ml": 0.09}))
                self.assertTrue(validate_overrides(knobs, {"develop_volume_ml": 25.1}))
                self.assertTrue(validate_overrides(knobs, {"rinse_repeat_count": 0}))
                self.assertTrue(validate_overrides(knobs, {"up_liquid_repeat_count": 21}))
                self.assertTrue(validate_overrides(knobs, {"solvent_ratio_4": -0.1}))
                self.assertTrue(validate_overrides(knobs, {"tank_asp_speed": 49}))
                self.assertTrue(validate_overrides(knobs, {"tank_disp_speed": 501}))
                self.assertTrue(validate_overrides(knobs, {"tank_suction_empty_s": 0.9}))
                self.assertTrue(validate_overrides(knobs, {"tank_suction_cap_s": 120.1}))

    def test_prepare_defaults_and_overrides_feed_shared_formula_and_independent_volumes(self) -> None:
        doc = self.docs["develop_prepare"]
        defaults = {var["name"]: var.get("default") for var in doc["vars"]}
        # 单趟液量受注射器 25 mL 量程限制, 工艺总量靠趟数凑:
        # 润洗 10 × 2 = 20 mL; 上液 20 × 3 = 60 mL
        self.assertEqual(defaults["tank_rinse_volume_ml"], 10.0)
        self.assertEqual(defaults["develop_volume_ml"], 20.0)
        # 润洗默认 2 轮: 第 1 轮顶掉管路上次残留, 第 2 轮起才真正润缸
        self.assertEqual(defaults["rinse_repeat_count"], 2)
        self.assertEqual(defaults["up_liquid_repeat_count"], 3)
        # 吸打液速度默认 V=300 (75 mL/min): 20mL 单趟吸+打 ≈32s, 远离停滞预算
        self.assertEqual(defaults["tank_asp_speed"], 300)
        self.assertEqual(defaults["tank_disp_speed"], 300)
        # 抽吸时长默认值 = PLC 侧 Tank_Suction_* 初值 (改这里须同步 PLC 初值)
        self.assertEqual(defaults["tank_suction_empty_s"], 10.0)
        self.assertEqual(defaults["tank_suction_cap_s"], 120.0)

        overrides = {
            "solvent_ratio_1": 4.0,
            "solvent_ratio_2": 3.0,
            "solvent_ratio_3": 2.0,
            "solvent_ratio_4": 1.0,
            "tank_rinse_volume_ml": 4.0,
            "develop_volume_ml": 5.0,
            "rinse_repeat_count": 4,
            "up_liquid_repeat_count": 5,
            "tank_asp_speed": 260,
            "tank_disp_speed": 320,
        }
        executor = _RecordingExecutor()
        thread = VmThread(
            doc,
            executor=executor,
            res_gate=ResourceGate(),
            overrides=overrides,
        )
        self.assertIs(asyncio.run(thread.run()), VmStatus.DONE)
        calls = {name: params for name, params in executor.calls}
        shared_ratios = {f"solvent_ratio_{i}": float(5 - i) for i in range(1, 5)}
        for action in ("develop.rinse_fill", "develop.fill"):
            self.assertEqual(
                {key: calls[action][key] for key in shared_ratios},
                shared_ratios,
            )
        self.assertNotIn("develop.clean_line", calls)
        self.assertEqual(calls["develop.rinse_fill"]["solvent_volume_ml"], 4.0)
        self.assertEqual(calls["develop.rinse_fill"]["rinse_repeat_count"], 4)
        self.assertEqual(calls["develop.fill"]["solvent_volume_ml"], 5.0)
        self.assertEqual(calls["develop.fill"]["up_liquid_repeat_count"], 5)
        # 速度旋钮为共用一对: 两个泵动作须同时收到同一份吸/打速度覆写
        for action in ("develop.rinse_fill", "develop.fill"):
            self.assertEqual(calls[action]["asp_speed"], 260)
            self.assertEqual(calls[action]["disp_speed"], 320)

    def test_legacy_tank_prep_delegates_to_canonical_prepare(self) -> None:
        events = _events(self.docs["tank_prep"])
        self.assertEqual(
            events,
            [("run_script", "develop_prepare", {"tank": {"var": "tank"}})],
        )

    def test_execute_and_unload_preserve_cycle_order(self) -> None:
        execute_events = _events(self.docs["develop_execute"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in execute_events],
            [
                ("call", "develop.capture_reference"),  # run 起点: 干板参考自动采集
                ("call", "develop.drain"),              # ref 失败: 退化人工门后排液
                ("call", "develop.wait_level"),         # auto: T1 等待
                ("call", "develop.wait_level"),         # auto: T2 等待 (地轨就位已拆出为 develop_standby 段)
                ("call", "develop.drain"),              # auto: 排液 (reached/hard_cap/人已确认)
                ("call", "develop.drain"),              # manual else: HITL 后排液
            ],
        )

        unload_events = _events(self.docs["develop_unload"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in unload_events],
            [
                ("run_script", "rail_move_safe"),    # 地轨就位须早于开盖, 见下方专项测试
                ("call", "develop.plate_retract"),
                ("run_script", "robot_tank_pick"),
                ("call", "develop.plate_extend"),   # 板出缸后关盖回空缸待机态, 须早于释放
                ("call", "develop.release_tank"),
            ],
        )

    def test_rail_standby_precedes_lid_open(self) -> None:
        """地轨就位必须早于开盖.

        排液终态 Tank_State=98 是盖关待取板, unload 开头 just-in-time 开盖。若移轨排在
        开盖之后 (即只靠 robot_tank_pick 入口的 rail.ensure 兜底), 板会在开盖状态下白等
        一个移轨时长, 多受一段蒸气/干燥环境暴露。
        """
        names = [name for _, name, _ in _events(self.docs["develop_unload"])]
        self.assertLess(names.index("rail_move_safe"), names.index("develop.plate_retract"))
        # 显式移轨的编排层脚本须声明 station:rail (与 photoscrape_unload 同模式)
        self.assertIn("station:rail", set(self.docs["develop_unload"].get("resources") or []))
        # 目标位 5 = 展开位 (plc_rail.yaml 位置码)
        rail_node = next(n for n in self.docs["develop_unload"]["body"]
                         if n.get("script") == "rail_move_safe")
        self.assertEqual(rail_node["inputs"]["target"], {"lit": 5})

    def test_drain_boundary_is_l2_action_not_raw_output(self) -> None:
        execute_events = _events(self.docs["develop_execute"])
        unload_events = _events(self.docs["develop_unload"])
        self.assertIn(("call", "develop.drain"), [(kind, name) for kind, name, _ in execute_events])

        pick = _index(unload_events, "run_script", "robot_tank_pick")
        release = _index(unload_events, "call", "develop.release_tank")
        self.assertLess(pick, release)

        prompts = [
            str((node.get("prompt") or {}).get("lit", ""))
            for node in _walk(self.docs["develop_execute"].get("body"))
            if node.get("op") == "human"
        ]
        self.assertTrue(any("开始 PLC L2 排液" in prompt for prompt in prompts))

        raw_drain_actions = []
        for action in self.actions.values():
            field_nodes = [field.node for field in action.fields]
            if action.kind == "plc_write" and (
                action.name.startswith("develop.") or any("Tank_Drain" in node for node in field_nodes)
            ):
                raw_drain_actions.append(action.name)
        self.assertEqual(raw_drain_actions, [])

    def test_wait_level_action_contract(self) -> None:
        adef = self.actions["develop.wait_level"]
        self.assertEqual(adef.kind, "host")
        self.assertEqual(adef.method, "wait_level")
        stage = adef.param("stage")
        self.assertEqual([o.value for o in stage.options], ["t1", "t2"])
        tank = adef.param("target_tank")
        self.assertTrue(tank.required)
        self.assertEqual((tank.minimum, tank.maximum), (1, 8))

    def test_auto_drain_knob_defaults_off(self) -> None:
        # 上机验证前 auto_drain 必须默认 false (spec Global Constraint); ui 块使其成为运行前旋钮
        doc = self.docs["develop_execute"]
        var = next(v for v in doc["vars"] if v["name"] == "auto_drain")
        self.assertEqual(var["type"], "BOOL")
        self.assertEqual(var["io"], "in")
        self.assertIs(var["default"], False)
        self.assertIsInstance(var.get("ui"), dict)

    def test_auto_branch_error_paths(self) -> None:
        # degraded → HITL 确认门在 auto 分支内
        doc = self.docs["develop_execute"]
        prompts = [
            str((node.get("prompt") or {}).get("lit", ""))
            for node in _walk(doc.get("body")) if node.get("op") == "human"
        ]
        self.assertTrue(any("液位检测异常" in p for p in prompts))
        self.assertTrue(any("展开完成" in p for p in prompts))   # manual 门原样保留
        cycle = set(self.docs["develop_cycle"].get("resources") or [])
        self.assertIn("station:rail", cycle)

    def test_execute_holds_only_develop_station(self) -> None:
        """execute 段不得独占机械臂/地轨.

        execute 含液位等待 (硬上限 3600s) 与人工门, 而独占资源在 VM 里是整条运行持有
        (thread.py 只在根脚本 acquire), 挂上 robot/station:rail 就等于整段虚占机械臂与
        地轨 —— 且 auto_drain 默认 false 时那段预就位根本不执行。地轨就位已并入 unload。
        """
        self.assertEqual(set(self.docs["develop_execute"].get("resources") or []),
                         {"station:develop"})
        self.assertNotIn("run_script",
                         {node.get("op") for node in _walk(self.docs["develop_execute"].get("body"))})


if __name__ == "__main__":
    unittest.main(verbosity=2)
