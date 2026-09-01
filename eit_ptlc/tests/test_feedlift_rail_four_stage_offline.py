#!/usr/bin/env python3
"""Feed-lift and rail four-stage contract checks.

These checks guard the operation shape and action declarations only. They do
not prove PLC download, sensor behavior, or field timing.
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
_FEEDLIFT_DIR = _OPERATION_DIR / "07_feedlift"
_RAIL_DIR = _OPERATION_DIR / "08_rail"


def _load_doc(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _event(node: dict) -> tuple[str, str, dict]:
    if node.get("op") == "call":
        return ("call", node.get("action", ""), node.get("args") or {})
    if node.get("op") == "run_script":
        return ("run_script", node.get("script", ""), node.get("inputs") or {})
    return (node.get("op", ""), "", {})


def _events(doc: dict) -> list[tuple[str, str, dict]]:
    return [_event(node) for node in doc.get("body", []) if node.get("op") in {"call", "run_script"}]


def _index(events: list[tuple[str, str, dict]], kind: str, name: str) -> int:
    for i, (event_kind, event_name, _args) in enumerate(events):
        if event_kind == kind and event_name == name:
            return i
    raise AssertionError(f"missing event {kind}:{name}")


def _lit(event: tuple[str, str, dict], name: str):
    return event[2][name]["lit"]


class FeedLiftRailFourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.actions = {action.name: action for action in cls.registry.list()}
        cls.feed_docs = {path.stem: _load_doc(path) for path in sorted(_FEEDLIFT_DIR.glob("*.yaml"))}
        cls.rail_docs = {path.stem: _load_doc(path) for path in sorted(_RAIL_DIR.glob("*.yaml"))}

    def test_scripts_validate(self) -> None:
        valid_actions = set(self.actions)
        for group in (self.feed_docs, self.rail_docs):
            for name, doc in group.items():
                with self.subTest(script=name):
                    self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_ui_roles_keep_cycles_visible_and_rail_helper_hidden(self) -> None:
        for name in ("feedlift_load_cycle", "feedlift_unload_cycle"):
            ui = self.feed_docs[name].get("ui") or {}
            with self.subTest(script=name):
                self.assertEqual(ui.get("role"), "cycle")
                self.assertTrue(ui.get("primary"))
                self.assertFalse(ui.get("hidden", False))
        rail_ui = self.rail_docs["rail_move_safe"].get("ui") or {}
        self.assertEqual(rail_ui.get("role"), "helper")
        self.assertTrue(rail_ui.get("hidden"))

    def test_feedlift_actions_match_l2_contract(self) -> None:
        expected = {
            "feedlift.feed_raise": ("feedlift", 11, ("feedlift_1z_search_low", "feedlift_1z_search_high")),
            "feedlift.feed_lower": ("feedlift", 12, ()),
            "feedlift.unload_ready": ("feedlift", 21, ("feedlift_2z_search_low", "feedlift_2z_search_high")),
            "feedlift.unload_bury": ("feedlift", 22, ("feedlift_2z_search_low", "feedlift_2z_search_high")),
        }
        for name, (station, code, preload_targets) in expected.items():
            action = self.actions[name]
            with self.subTest(action=name):
                self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", station, code))
                self.assertEqual(action.params, ())
                self.assertEqual(action.preload_targets, preload_targets)

    def test_feedlift_debug_photoelectric_action_is_debug_only(self) -> None:
        action = self.actions["feedlift.debug_check_photoelectric_edge"]
        self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "feedlift", 91))
        self.assertEqual(action.preload_targets, (
            "feedlift_1z_search_low", "feedlift_1z_search_high",
            "feedlift_2z_search_low", "feedlift_2z_search_high",
        ))
        self.assertEqual(action.modes, ("DEBUG",))
        params = {p.name: p for p in action.params}
        self.assertEqual(set(params), {"axis", "expected_final"})
        self.assertEqual(params["axis"].channel, "FeedLift_DebugAxis")
        self.assertEqual(params["expected_final"].channel, "FeedLift_DebugExpectedFinal")

    def test_rail_move_action_contract_and_safe_wrapper(self) -> None:
        action = self.actions["rail.move"]
        self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "rail", 10))
        self.assertEqual(len(action.params), 1)
        param = action.params[0]
        self.assertEqual(param.name, "Rail_Target_Position")
        self.assertEqual(param.type, "int")
        self.assertTrue(param.required)
        self.assertEqual(param.minimum, 1)
        self.assertEqual(param.maximum, 6)

        events = _events(self.rail_docs["rail_move_safe"])
        anchor = _index(events, "call", "robot.home_ensure")   # 确保式安全门 (原 require_anchor)
        rail = _index(events, "call", "rail.move")
        self.assertLess(anchor, rail)
        self.assertEqual(events[rail][2]["Rail_Target_Position"], {"var": "target"})

    def test_feedlift_load_cycle_order(self) -> None:
        events = _events(self.feed_docs["feedlift_load_cycle"])
        tool = _index(events, "run_script", "robot_tool_ensure")
        rail = _index(events, "run_script", "rail_move_safe")
        raise_axis = _index(events, "call", "feedlift.feed_raise")
        robot_enter = _index(events, "run_script", "robot_feed_lift_pick_enter")
        lower_axis = _index(events, "call", "feedlift.feed_lower")
        robot_exit = _index(events, "run_script", "robot_feed_lift_pick_exit")

        self.assertEqual(_lit(events[tool], "needed"), 1)
        self.assertEqual(_lit(events[rail], "target"), 1)
        # 换刀必须先于移轨: robot_tool_ensure 需要换刀时会自己把地轨开到工具站(位4)且不还原,
        # 反过来排会把位1 那趟推翻成 168->500->168 白跑一趟, 还把 feed_raise 夹在往返中间。
        self.assertLess(tool, rail)
        self.assertLess(rail, raise_axis)
        self.assertLess(raise_axis, robot_enter)
        self.assertLess(robot_enter, lower_axis)
        self.assertLess(lower_axis, robot_exit)

    def test_feedlift_unload_cycle_order(self) -> None:
        """下料 cycle 现有两次 unload_bury, 语义不同, 不能只取第一次:

        开头那次是**测量前清零** (unload_ready 在光电2 已 TRUE 时幂等直通, 不清零就会读到
        陈旧位置); 末尾那次才是原本的**埋料**。故按出现序分别取用。
        """
        events = _events(self.feed_docs["feedlift_unload_cycle"])
        tool = _index(events, "run_script", "robot_tool_ensure")
        rail = _index(events, "run_script", "rail_move_safe")
        ready = _index(events, "call", "feedlift.unload_ready")
        robot_put = _index(events, "run_script", "robot_suction_put")
        buries = [i for i, e in enumerate(events)
                  if e[0] == "call" and e[1] == "feedlift.unload_bury"]

        self.assertEqual(_lit(events[tool], "needed"), 1)
        self.assertEqual(_lit(events[rail], "target"), 1)
        self.assertEqual(_lit(events[robot_put], "station_id"), "waste")
        self.assertEqual(len(buries), 2, "开头清零 + 末尾埋料, 各一次")
        clear_bury, final_bury = buries
        # 同 load cycle: 换刀会把地轨带到位4 且不还原, 必须排在移轨之前
        self.assertLess(tool, rail)
        self.assertLess(rail, clear_bury)
        self.assertLess(clear_bury, ready)      # 清零必须在逼近之前
        self.assertLess(ready, robot_put)
        self.assertLess(robot_put, final_bury)


if __name__ == "__main__":
    unittest.main(verbosity=2)
