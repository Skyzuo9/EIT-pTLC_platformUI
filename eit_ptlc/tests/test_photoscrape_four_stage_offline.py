#!/usr/bin/env python3
"""Photo-scrape station four-stage contract checks.

These checks guard the station-level operation shape. They do not claim PLC
download or field closure, and they intentionally keep warehouse-to-staging
consumable replenishment outside the photo-scrape station load step.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"
_OPERATION_DIR = _PKG / "config" / "operation"
_PHOTO_DIR = _OPERATION_DIR / "03_photoscrape"
_COLLECT_DIR = _OPERATION_DIR / "04_collect"
_TRANSFER_DIR = _OPERATION_DIR / "05_transfer"
_FULL_DIR = _OPERATION_DIR / "09_full"


def _load_doc(path: Path) -> dict:
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


def _index(events: list[tuple[str, str, dict]], kind: str, name: str, *, start: int = 0) -> int:
    for i in range(start, len(events)):
        event_kind, event_name, _args = events[i]
        if event_kind == kind and event_name == name:
            return i
    raise AssertionError(f"missing event {kind}:{name}")


def _bool_arg(event: tuple[str, str, dict], name: str) -> bool:
    return bool(event[2][name]["lit"])


def _lit_arg(event: tuple[str, str, dict], name: str):
    return event[2][name]["lit"]


class PhotoScrapeFourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.actions = {action.name: action for action in cls.registry.list()}
        cls.photo_docs = {path.stem: _load_doc(path) for path in sorted(_PHOTO_DIR.glob("*.yaml"))}
        cls.collect_load = _load_doc(_COLLECT_DIR / "collect_load.yaml")
        cls.collect_full = _load_doc(_COLLECT_DIR / "collect_full.yaml")
        cls.collector_to_scrape = _load_doc(_TRANSFER_DIR / "transfer_collector_staging_a_to_scrape.yaml")
        cls.ptlc_full = _load_doc(_FULL_DIR / "ptlc_full.yaml")
        cls.ptlc_full_v2 = _load_doc(_FULL_DIR / "ptlc_full_v2.yaml")
        cls.robot_suction_pick = _load_doc(_OPERATION_DIR / "06_robot" / "robot_suction_pick.yaml")

    def test_photoscrape_scripts_validate(self) -> None:
        valid_actions = set(self.actions)
        for name, doc in self.photo_docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_photoscrape_run_script_references_exist(self) -> None:
        all_script_names = {path.stem for path in _OPERATION_DIR.glob("*/*.yaml")}
        for name, doc in self.photo_docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") == "run_script":
                    with self.subTest(script=name, child=node.get("script")):
                        self.assertIn(node.get("script"), all_script_names)

    def test_photoscrape_station_task_and_phase_ui_contract(self) -> None:
        task_names = [
            name
            for name, doc in self.photo_docs.items()
            if doc.get("ui", {}).get("role") == "station_task"
            and doc.get("ui", {}).get("station") == "photo_scrape"
        ]
        self.assertEqual(
            task_names,
            [
                "photoscrape_before_photo_cycle",
                "photoscrape_cycle",
                "photoscrape_scrape_calib",   # 刮痕标定 (刮已知图案测三链合量偏差, 修 plate_origin)
                "photoscrape_tool_align",     # jog 对刀 (刀尖静态对板角, 只测机床原点)
            ],
        )

        task_ui = self.photo_docs["photoscrape_cycle"].get("ui", {})
        self.assertTrue(task_ui.get("primary"))
        self.assertEqual(task_ui.get("order"), 30)
        self.assertFalse(task_ui.get("hidden", False))
        self.assertIn("station:rail", self.photo_docs["photoscrape_cycle"].get("resources") or [])
        before_task_ui = self.photo_docs["photoscrape_before_photo_cycle"].get("ui", {})
        self.assertFalse(before_task_ui.get("primary"))
        self.assertEqual(before_task_ui.get("order"), 29)
        self.assertFalse(before_task_ui.get("hidden", False))
        self.assertIn("station:rail", self.photo_docs["photoscrape_before_photo_cycle"].get("resources") or [])

        expected_phases = [
            ("photoscrape_prepare", "prepare", 31),
            ("photoscrape_load", "load", 32),
            ("photoscrape_process", "execute", 33),
            ("photoscrape_unload", "unload", 34),
        ]
        phase_names = []
        for name, phase, order in expected_phases:
            ui = self.photo_docs[name].get("ui") or {}
            with self.subTest(script=name):
                self.assertEqual(ui.get("role"), "station_phase")
                self.assertEqual(ui.get("station"), "photo_scrape")
                self.assertEqual(ui.get("phase"), phase)
                self.assertTrue(ui.get("primary"))
                self.assertEqual(ui.get("order"), order)
                self.assertFalse(ui.get("hidden", False))
                phase_names.append(name)

        visible_photo_phases = [
            name
            for name, doc in sorted(
                self.photo_docs.items(), key=lambda item: item[1].get("ui", {}).get("order", 999)
            )
            if doc.get("ui", {}).get("role") == "station_phase"
            and doc.get("ui", {}).get("station") == "photo_scrape"
            and doc.get("ui", {}).get("primary")
            and not doc.get("ui", {}).get("hidden", False)
        ]
        self.assertEqual(visible_photo_phases, phase_names)

        for name, phase in (
            ("photoscrape_plate_load", "load"),
            ("photoscrape_before_photo_capture", "execute"),
        ):
            ui = self.photo_docs[name].get("ui") or {}
            with self.subTest(script=name):
                self.assertEqual(ui.get("role"), "station_phase")
                self.assertEqual(ui.get("station"), "photo_scrape")
                self.assertEqual(ui.get("phase"), phase)
                self.assertFalse(ui.get("primary"))
                self.assertFalse(ui.get("hidden", False))

    def test_photoscrape_cycle_is_four_stage_wrapper(self) -> None:
        non_comment_nodes = [
            node for node in self.photo_docs["photoscrape_cycle"].get("body", []) if node.get("op") != "comment"
        ]
        self.assertEqual(
            [(node.get("op"), node.get("script")) for node in non_comment_nodes],
            [
                ("run_script", "photoscrape_prepare"),
                ("run_script", "photoscrape_load"),
                ("run_script", "photoscrape_process"),
                ("run_script", "photoscrape_unload"),
            ],
        )
        self.assertEqual(non_comment_nodes[1].get("inputs"), {"collector_slot": {"var": "collector_slot"}})

    def test_before_photo_cycle_is_explicit_four_step_path(self) -> None:
        non_comment_nodes = [
            node
            for node in self.photo_docs["photoscrape_before_photo_cycle"].get("body", [])
            if node.get("op") != "comment"
        ]
        self.assertEqual(
            [(node.get("op"), node.get("script")) for node in non_comment_nodes],
            [
                ("run_script", "photoscrape_prepare"),
                ("run_script", "photoscrape_plate_load"),
                ("run_script", "photoscrape_before_photo_capture"),
                ("run_script", "photoscrape_unload"),
            ],
        )
        capture_node = non_comment_nodes[2]
        self.assertEqual(
            capture_node.get("outputs"),
            {"before_path": {"var": "before_path"}},
        )

    def test_legacy_entrypoints_are_hidden(self) -> None:
        for name in ("photoscrape_place", "photoscrape_execute", "photoscrape_pick"):
            with self.subTest(script=name):
                self.assertEqual(self.photo_docs[name].get("ui", {}).get("role"), "helper")
                self.assertTrue(self.photo_docs[name].get("ui", {}).get("hidden"))
        self.assertIn("station:rail", self.photo_docs["photoscrape_place"].get("resources") or [])
        self.assertIn("station:rail", self.photo_docs["photoscrape_pick"].get("resources") or [])
        self.assertEqual(self.photo_docs["photoscrape_full"].get("ui", {}).get("role"), "legacy")
        self.assertTrue(self.photo_docs["photoscrape_full"].get("ui", {}).get("hidden"))
        self.assertEqual(self.collect_full.get("ui", {}).get("role"), "legacy")
        self.assertTrue(self.collect_full.get("ui", {}).get("hidden"))
        self.assertEqual(self.ptlc_full.get("ui", {}).get("role"), "legacy")
        self.assertTrue(self.ptlc_full.get("ui", {}).get("hidden"))

    def test_photoscrape_bool_action_contracts(self) -> None:
        expected = {
            "photoscrape.locate_cylinder": (32, "clamped", "PhotoScrape_CamLocate_Target"),
            "photoscrape.press_cylinder": (33, "pressed", "PhotoScrape_CamPress_Target"),
        }
        for name, (code, param_name, channel) in expected.items():
            action = self.actions[name]
            with self.subTest(action=name):
                self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "photoscrape", code))
                self.assertEqual(len(action.params), 1)
                param = action.params[0]
                self.assertEqual(param.name, param_name)
                self.assertEqual(param.type, "bool")
                self.assertTrue(param.required)
                self.assertEqual(param.channel, channel)

    def test_staging_a_bool_action_contracts(self) -> None:
        expected = {
            "staging_a.locator_a": (24, "target", "StagingA_LocatorA_Target"),
            "staging_a.locator_b": (25, "target", "StagingA_LocatorB_Target"),
        }
        for name, (code, param_name, channel) in expected.items():
            action = self.actions[name]
            with self.subTest(action=name):
                self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "staging_a", code))
                self.assertEqual(len(action.params), 1)
                param = action.params[0]
                self.assertEqual(param.name, param_name)
                self.assertEqual(param.type, "bool")
                self.assertTrue(param.required)
                self.assertEqual(param.channel, channel)

        self.assertNotIn("staging_a.powder_collector_locator", self.actions)
        self.assertNotIn("photoscrape.powder_collector_locator", self.actions)

    def test_prepare_positions_station_for_loading(self) -> None:
        events = _events(self.photo_docs["photoscrape_prepare"])
        init = _index(events, "call", "photoscrape.init")
        cam_x335 = _index(events, "call", "photoscrape.cam_x335")

        self.assertLess(init, cam_x335)

    def test_load_places_plate_and_scrape_collector_from_staging(self) -> None:
        events = _events(self.photo_docs["photoscrape_load"])
        rail_window = _index(events, "run_script", "rail_move_safe")
        put_plate = _index(events, "run_script", "robot_suction_put")
        locate = _index(events, "call", "photoscrape.locate_cylinder")
        ensure_gripper = _index(events, "run_script", "robot_tool_ensure")
        collector = _index(events, "run_script", "transfer_collector_staging_a_to_scrape")

        self.assertIn("station:rail", self.photo_docs["photoscrape_load"].get("resources") or [])
        self.assertEqual(_lit_arg(events[rail_window], "target"), 2)
        self.assertLess(rail_window, put_plate)
        self.assertLess(put_plate, locate)
        self.assertTrue(_bool_arg(events[locate], "clamped"))
        self.assertLess(locate, ensure_gripper)
        self.assertEqual(events[ensure_gripper][2], {"needed": {"lit": 3}})
        self.assertLess(ensure_gripper, collector)
        self.assertEqual(events[collector][2], {"slot_id": {"var": "collector_slot"}})

        run_scripts = [name for kind, name, _ in events if kind == "run_script"]
        self.assertNotIn("transfer_collector_rack_to_staging_a", run_scripts)

    def test_place_compatibility_entry_establishes_scrape_rail_window(self) -> None:
        events = _events(self.photo_docs["photoscrape_place"])
        cam_x335 = _index(events, "call", "photoscrape.cam_x335")
        rail_window = _index(events, "run_script", "rail_move_safe")
        put_plate = _index(events, "run_script", "robot_suction_put")

        self.assertEqual(_lit_arg(events[rail_window], "target"), 2)
        self.assertLess(cam_x335, rail_window)
        self.assertLess(rail_window, put_plate)

    def test_plate_load_is_plate_only(self) -> None:
        events = _events(self.photo_docs["photoscrape_plate_load"])
        rail_window = _index(events, "run_script", "rail_move_safe")
        put_plate = _index(events, "run_script", "robot_suction_put")
        locate = _index(events, "call", "photoscrape.locate_cylinder")

        self.assertIn("station:rail", self.photo_docs["photoscrape_plate_load"].get("resources") or [])
        self.assertEqual(_lit_arg(events[rail_window], "target"), 2)
        self.assertLess(rail_window, put_plate)
        self.assertLess(put_plate, locate)
        self.assertEqual(events[put_plate][2], {"station_id": {"lit": "scrape"}})
        self.assertTrue(_bool_arg(events[locate], "clamped"))
        self.assertNotIn("transfer_collector_staging_a_to_scrape", [name for kind, name, _ in events])
        self.assertNotIn("photoscrape.powder_collector_locator", [name for kind, name, _ in events])
        self.assertNotIn("staging_a.powder_collector_locator", [name for kind, name, _ in events])
        self.assertNotIn("staging_a.locator_a", [name for kind, name, _ in events])

    def test_before_photo_capture_outputs_real_before_path(self) -> None:
        doc = self.photo_docs["photoscrape_before_photo_capture"]
        events = _events(doc)
        photo_pos = _index(events, "call", "photoscrape.cam_photopos")
        capture = _index(events, "call", "photoscrape.capture")
        photo_home = _index(events, "call", "photoscrape.cam_photohome")

        self.assertLess(photo_pos, capture)
        self.assertLess(capture, photo_home)
        self.assertEqual(events[capture][2]["filename"], {"lit": "before.jpg"})
        assign_nodes = [node for node in _walk(doc.get("body")) if node.get("op") == "assign"]
        self.assertEqual(len(assign_nodes), 1)
        self.assertEqual(assign_nodes[0].get("target"), {"var": "before_path"})
        self.assertEqual(assign_nodes[0].get("value"), {"field": {"var": "shot"}, "name": "image_path"})

    def test_collector_staging_to_scrape_helper_confirms_staging_locator(self) -> None:
        events = _events(self.collector_to_scrape)
        rail_windows = [i for i, (kind, name, _) in enumerate(events)
                        if kind == "run_script" and name == "rail_move_safe"]
        self.assertEqual(len(rail_windows), 2)
        locate = _index(events, "call", "staging_a.locator_a")
        pick = _index(events, "run_script", "robot_individual_pick")
        enter = _index(events, "run_script", "robot_scrape_holder_put_enter")
        exit_holder = _index(events, "run_script", "robot_scrape_holder_put_exit")

        # 中转A≡刮板/拍照站(位2, 168.0): 从中转A取收集器与放入刮板夹具同处位2 —— 两次 rail_move_safe 均位2 (自守卫幂等)。
        self.assertEqual(events[rail_windows[0]][2], {"target": {"lit": 2}})
        self.assertEqual(events[rail_windows[1]][2], {"target": {"lit": 2}})
        self.assertLess(rail_windows[0], locate)
        self.assertTrue(_bool_arg(events[locate], "target"))
        self.assertLess(locate, pick)
        self.assertLess(pick, rail_windows[1])
        self.assertLess(rail_windows[1], enter)
        self.assertLess(enter, exit_holder)

        run_scripts = [name for kind, name, _ in events if kind == "run_script"]
        self.assertNotIn("robot_group_rack_pick", run_scripts)

    def test_execute_compatibility_wrapper_delegates_to_visible_process(self) -> None:
        events = _events(self.photo_docs["photoscrape_execute"])
        self.assertEqual([(kind, name) for kind, name, _ in events], [("run_script", "photoscrape_process")])

    def test_process_owns_press_down_and_scrape_only(self) -> None:
        events = _events(self.photo_docs["photoscrape_process"])
        press = _index(events, "call", "photoscrape.press_cylinder")
        photo_pos = _index(events, "call", "photoscrape.cam_photopos")
        capture = _index(events, "call", "photoscrape.capture")
        analyze = _index(events, "call", "photoscrape.analyze")
        write_path = _index(events, "call", "photoscrape.write_cnc_path")
        scrape = _index(events, "call", "photoscrape.scrape")
        finish = _index(events, "call", "photoscrape.scrape_finish")

        # 首个 press 是压下开拍 (唯一压下点); 其后所有 press 都是释放放板 (容错/取消恢复)。
        self.assertTrue(_bool_arg(events[press], "pressed"))
        self.assertLess(press, photo_pos)
        self.assertLess(photo_pos, capture)
        self.assertLess(capture, analyze)
        self.assertLess(analyze, write_path)
        self.assertLess(write_path, scrape)
        self.assertLess(scrape, finish)

    def test_process_is_fault_tolerant_with_placeholder_and_abort_release(self) -> None:
        """容错化契约: analyze/cnc_path 失败可人工处置; 跳过刮板走 placeholder;
        中止/取消恢复必须同时释放下压+定位气缸放板 (板不卡压头下)。"""
        doc = self.photo_docs["photoscrape_process"]
        events = _events(doc)
        call_names = [name for kind, name, _ in events if kind == "call"]

        # (1) 首 press 压下, 其余 press 全为释放 (pressed=false)
        press_events = [e for e in events if e[1] == "photoscrape.press_cylinder"]
        self.assertGreaterEqual(len(press_events), 2, "应有压下 + 至少一处释放放板")
        self.assertTrue(_bool_arg(press_events[0], "pressed"))
        for e in press_events[1:]:
            self.assertFalse(_bool_arg(e, "pressed"), "首个之外的 press 必须是释放放板")

        # (2) process 内所有 locate 都是释放 (clamped=false); 夹紧属 load, process 只在恢复时放板
        locate_events = [e for e in events if e[1] == "photoscrape.locate_cylinder"]
        self.assertGreaterEqual(len(locate_events), 1, "中止/取消恢复应释放定位气缸")
        for e in locate_events:
            self.assertFalse(_bool_arg(e, "clamped"), "process 内 locate 只做释放")

        # (3) 恢复/中止路径成对释放双气缸 (数量对等 → 每个中止点都同时松 press+locate)
        release_press = [e for e in press_events if not _bool_arg(e, "pressed")]
        self.assertEqual(
            len(release_press), len(locate_events),
            "每个中止/取消恢复点必须同时释放 press 与 locate",
        )

        # (4) 无谱带/跳过刮板经 cnc_path(placeholder=true) 生成 0-pass 安全占位数组
        cnc_events = [e for e in events if e[1] == "photoscrape.cnc_path"]
        self.assertGreaterEqual(len(cnc_events), 2, "常规路径 + placeholder 跳过路径")
        placeholder_calls = [e for e in cnc_events if e[2].get("placeholder", {}).get("lit") is True]
        self.assertEqual(len(placeholder_calls), 1, "应恰有一处 cnc_path(placeholder=true) 作跳过刮板")

        # (5) 统一下发门(choose): assign_choice=gate_choice, 选项含下发/手绘/跳过/中止; 另有手绘门(sketch)
        gate_humans = [
            node
            for node in _walk(doc.get("body"))
            if node.get("op") == "human" and node.get("kind") == "choose"
            and (node.get("assign_choice") or {}).get("var") == "gate_choice"
        ]
        self.assertEqual(len(gate_humans), 1, "应有一个统一下发门 (kind=choose, gate_choice)")
        opt_values = {o.get("value") for o in gate_humans[0].get("options", []) or []}
        self.assertEqual(
            opt_values, {"dispatch", "align", "reanalyze", "sketch", "skip", "abort"},
            "门应含下发/对位检查/重识别/手绘/跳过/中止六选项",
        )
        # 手绘兜底门 (kind=sketch), 带回 summary_path 供 VM 交 cnc_path
        sketch_humans = [
            node
            for node in _walk(doc.get("body"))
            if node.get("op") == "human" and node.get("kind") == "sketch"
        ]
        self.assertEqual(len(sketch_humans), 1, "应有一个手绘门 (kind=sketch)")
        sketch_fields = {f.get("var") for f in sketch_humans[0].get("fields", []) or []}
        self.assertIn("sketch_summary_path", sketch_fields)

        # (6) 中止抛 PHOTOSCRAPE_ABORTED (放板后干净中止)
        raises = [node for node in _walk(doc.get("body")) if node.get("op") == "raise"]
        self.assertTrue(any(r.get("error") == "PHOTOSCRAPE_ABORTED" for r in raises))
        self.assertIn("photoscrape.scrape_finish", call_names)

    def test_pick_compatibility_wrapper_delegates_to_unload(self) -> None:
        events = _events(self.photo_docs["photoscrape_pick"])
        self.assertEqual([(kind, name) for kind, name, _ in events], [("run_script", "photoscrape_unload")])

    def test_unload_step_owns_only_plate_release_and_pick(self) -> None:
        events = _events(self.photo_docs["photoscrape_unload"])
        ensure_suction = _index(events, "run_script", "robot_tool_ensure")
        rail_window = _index(events, "run_script", "rail_move_safe")
        press_release = _index(events, "call", "photoscrape.press_cylinder")
        locate_release = _index(events, "call", "photoscrape.locate_cylinder")
        pick_plate = _index(events, "run_script", "robot_suction_pick")
        call_names = [name for kind, name, _ in events if kind == "call"]
        run_scripts = [name for kind, name, _ in events if kind == "run_script"]

        self.assertIn("station:rail", self.photo_docs["photoscrape_unload"].get("resources") or [])
        self.assertEqual(events[ensure_suction][2], {"needed": {"lit": 1}})
        self.assertEqual(_lit_arg(events[rail_window], "target"), 2)
        self.assertLess(ensure_suction, rail_window)
        # 补放下压气缸 (press gap 修复): 独立/短流程无 collect 段会漏放, 板卡压头下。
        # 先松 press 再松 locate, 机器人方可安全取板; full 流程已由 collect_load 放过, 幂等无副作用。
        self.assertLess(rail_window, press_release)
        self.assertFalse(_bool_arg(events[press_release], "pressed"))
        self.assertLess(press_release, locate_release)
        self.assertFalse(_bool_arg(events[locate_release], "clamped"))
        self.assertLess(locate_release, pick_plate)
        self.assertNotIn("photoscrape.retr_stoprot", call_names)
        self.assertNotIn("photoscrape.powder_collector_locator", call_names)
        self.assertNotIn("staging_a.powder_collector_locator", call_names)
        self.assertNotIn("photoscrape_pick", run_scripts)

    def test_scrape_suction_pick_rotates_only_after_safe_retreat(self) -> None:
        # 入口 prologue (comment + home_ensure + tool_ensure) 后, 首个 selector if 不再是 body[0]; 按 op 定位
        selector = next(n for n in self.robot_suction_pick["body"] if n.get("op") == "if")
        scrape_branch = next(
            branch["body"]
            for branch in selector.get("elifs", [])
            if branch.get("cond", {}).get("right", {}).get("lit") == "scrape"
        )
        events = _events({"body": scrape_branch})

        def _move_indices(point_id: str) -> list[int]:
            return [
                i
                for i, event in enumerate(events)
                if event[0] == "call"
                and event[1] == "robot.move_to_point"
                and _lit_arg(event, "point_id_or_robot_name") == point_id
            ]

        def _tool_indices(action: str) -> list[int]:
            return [
                i
                for i, event in enumerate(events)
                if event[0] == "call"
                and event[1] == "robot.tool_action"
                and _lit_arg(event, "action") == action
            ]

        pickup = _move_indices("P65")[0]
        retreat_far = _move_indices("scrape.plate-pick.retreat_far")[0]
        safe_transition = _move_indices("P63")[-1]
        final_home = _move_indices("P1")[0]
        suction_on = _tool_indices("suction-on")[0]
        rotary_up_events = _tool_indices("rotary-up")

        self.assertEqual(_tool_indices("rotary-down"), [])
        self.assertEqual(len(rotary_up_events), 2)
        self.assertLess(pickup, suction_on)
        self.assertLess(suction_on, retreat_far)
        self.assertLess(retreat_far, safe_transition)
        self.assertLess(safe_transition, rotary_up_events[-1])
        self.assertLess(rotary_up_events[-1], final_home)

    def test_collector_release_is_in_collect_load(self) -> None:
        events = _events(self.collect_load)
        enter = _index(events, "run_script", "robot_scrape_holder_pick_enter")
        press_release = _index(events, "call", "photoscrape.press_cylinder")
        exit_holder = _index(events, "run_script", "robot_scrape_holder_pick_exit")
        stop_rot = _index(events, "call", "photoscrape.retr_stoprot")

        self.assertLess(enter, press_release)
        self.assertFalse(_bool_arg(events[press_release], "pressed"))
        self.assertLess(press_release, exit_holder)
        self.assertLess(exit_holder, stop_rot)

    def test_full_v2_uses_before_photo_cycle_and_passes_before_path_to_process(self) -> None:
        events = _events(self.ptlc_full_v2)
        before_cycle = _index(events, "run_script", "photoscrape_before_photo_cycle")
        develop = _index(events, "run_script", "develop_cycle")
        plate_load = _index(events, "run_script", "photoscrape_plate_load")
        locator_a_on = _index(events, "call", "staging_a.locator_a")
        locator_b_on = _index(events, "call", "staging_a.locator_b")
        process = _index(events, "run_script", "photoscrape_process")
        collect = _index(events, "run_script", "collect_cycle")
        locator_b_off = _index(events, "call", "staging_a.locator_b", start=collect + 1)
        locator_a_off = _index(events, "call", "staging_a.locator_a", start=collect + 1)
        final_unload = _index(events, "run_script", "photoscrape_unload")

        self.assertLess(before_cycle, develop)
        self.assertLess(develop, plate_load)
        self.assertLess(plate_load, locator_a_on)
        self.assertLess(locator_a_on, locator_b_on)
        self.assertLess(locator_b_on, process)
        self.assertLess(develop, process)
        self.assertLess(process, collect)
        self.assertLess(collect, locator_b_off)
        self.assertLess(locator_b_off, locator_a_off)
        self.assertLess(locator_a_off, final_unload)
        self.assertEqual(events[locator_a_on][2], {"target": {"lit": True}})
        self.assertEqual(events[locator_b_on][2], {"target": {"lit": True}})
        self.assertEqual(events[locator_b_off][2], {"target": {"lit": False}})
        self.assertEqual(events[locator_a_off][2], {"target": {"lit": False}})
        self.assertEqual(
            events[before_cycle][2],
            {"sample_id": {"var": "sample_id"}, "save_dir": {"var": "save_dir"}},
        )
        self.assertNotIn("photoscrape_pick", [name for kind, name, _ in events if kind == "run_script"])

        process_nodes = [
            node
            for node in _walk(self.ptlc_full_v2.get("body"))
            if node.get("op") == "run_script" and node.get("script") == "photoscrape_process"
        ]
        self.assertEqual(len(process_nodes), 1)
        self.assertEqual(process_nodes[0].get("inputs", {}).get("before_path"), {"var": "before_path"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
