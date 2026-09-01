#!/usr/bin/env python3
"""Collect station four-stage contract checks.

These checks are intentionally static. They guard the operation/action contract
for the collect station, but do not claim PLC or field closure.
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
_COLLECT_DIR = _OPERATION_DIR / "04_collect"
_TRANSFER_DIR = _OPERATION_DIR / "05_transfer"


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


def _bool_arg(event: tuple[str, str, dict], name: str) -> bool:
    return bool(event[2][name]["lit"])


class CollectFourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.docs = {path.stem: _load_doc(path) for path in sorted(_COLLECT_DIR.glob("*.yaml"))}
        cls.transfer_docs = {
            name: _load_doc(_TRANSFER_DIR / f"{name}.yaml")
            for name in (
                "transfer_bottle_staging_b_to_collect",
                "transfer_bottle_collect_to_staging_b",
            )
        }

    def test_collect_scripts_validate(self) -> None:
        valid_actions = {action.name for action in self.registry.list()}
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_collect_station_task_and_phase_ui_contract(self) -> None:
        task_names = [
            name
            for name, doc in self.docs.items()
            if doc.get("ui", {}).get("role") == "station_task"
            and doc.get("ui", {}).get("station") == "collect"
        ]
        self.assertEqual(task_names, ["collect_cycle"])

        task_ui = self.docs["collect_cycle"].get("ui", {})
        self.assertTrue(task_ui.get("primary"))
        self.assertEqual(task_ui.get("order"), 40)
        self.assertFalse(task_ui.get("hidden", False))

        expected_phases = [
            ("collect_prepare", "prepare", 41),
            ("collect_load", "load", 42),
            ("collect_execute", "execute", 43),
            ("collect_unload", "unload", 44),
        ]
        phase_names = []
        for name, phase, order in expected_phases:
            with self.subTest(script=name):
                ui = self.docs[name].get("ui", {})
                self.assertEqual(ui.get("role"), "station_phase")
                self.assertEqual(ui.get("station"), "collect")
                self.assertEqual(ui.get("phase"), phase)
                self.assertTrue(ui.get("primary"))
                self.assertEqual(ui.get("order"), order)
                self.assertFalse(ui.get("hidden", False))
                phase_names.append(name)

        visible_collect_phases = [
            name
            for name, doc in sorted(
                self.docs.items(), key=lambda item: item[1].get("ui", {}).get("order", 999)
            )
            if doc.get("ui", {}).get("role") == "station_phase"
            and doc.get("ui", {}).get("station") == "collect"
            and not doc.get("ui", {}).get("hidden", False)
        ]
        self.assertEqual(visible_collect_phases, phase_names)

    def test_collect_cycle_is_four_stage_wrapper(self) -> None:
        non_comment_nodes = [
            node for node in self.docs["collect_cycle"].get("body", []) if node.get("op") != "comment"
        ]
        self.assertEqual(
            [(node.get("op"), node.get("script")) for node in non_comment_nodes],
            [
                ("run_script", "collect_prepare"),
                ("run_script", "collect_load"),
                ("run_script", "collect_execute"),
                ("run_script", "collect_unload"),
            ],
        )

        events = _events(self.docs["collect_cycle"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in events],
            [
                ("run_script", "collect_prepare"),
                ("run_script", "collect_load"),
                ("run_script", "collect_execute"),
                ("run_script", "collect_unload"),
            ],
        )
        self.assertEqual(
            events[2][2],
            {
                "solvent_volume_ml": {"var": "solvent_volume_ml"},
                "liquid_repeat_count": {"var": "liquid_repeat_count"},
            },
        )

    def test_bottle_locator_action_contract(self) -> None:
        action = self.registry.get("staging_a.locator_b")
        self.assertEqual(action.kind, "plc_l2")
        self.assertEqual(action.station, "staging_a")
        self.assertEqual(action.action_code, 25)
        self.assertEqual(len(action.params), 1)
        param = action.params[0]
        self.assertEqual(param.name, "target")
        self.assertEqual(param.type, "bool")
        self.assertTrue(param.required)
        self.assertEqual(param.channel, "StagingA_LocatorB_Target")

        alias = self.registry.get("collect.bottle_locator")
        self.assertEqual((alias.kind, alias.station, alias.action_code), ("plc_l2", "staging_a", 25))
        self.assertEqual(alias.params[0].name, "target")
        self.assertEqual(alias.params[0].channel, "StagingA_LocatorB_Target")
        with self.assertRaises(KeyError):
            self.registry.get("staging_b.plate_locator")

    def test_collect_load_releases_press_then_loads_bottle(self) -> None:
        events = _events(self.docs["collect_load"])
        enter = _index(events, "run_script", "robot_scrape_holder_pick_enter")
        press_release = _index(events, "call", "photoscrape.press_cylinder")
        scrape_exit = _index(events, "run_script", "robot_scrape_holder_pick_exit")
        stop_rot = _index(events, "call", "photoscrape.retr_stoprot")

        def _rail_idx(target: int) -> int:
            return next(
                i
                for i, (kind, name, args) in enumerate(events)
                if kind == "run_script"
                and name == "rail_move_safe"
                and args.get("target", {}).get("lit") == target
            )

        rail_guard = _rail_idx(2)  # 段首自守卫: 取接粉收集器前地轨须在刮板位(位2)
        rail_to_collect = _rail_idx(3)  # 取件后移轨到收集位(位3)放入收集夹具
        collect_put = _index(events, "run_script", "robot_collect_holder_put_enter")
        clamp = _index(events, "call", "collect.clamp")
        extend = _index(events, "call", "collect.extend")
        bottle_put = _index(events, "run_script", "transfer_bottle_staging_b_to_collect")

        self.assertLess(rail_guard, enter)  # 地轨自守卫(位2)在取接粉收集器之前
        self.assertLess(enter, press_release)
        self.assertFalse(_bool_arg(events[press_release], "pressed"))
        self.assertLess(press_release, scrape_exit)
        self.assertLess(scrape_exit, stop_rot)
        self.assertLess(stop_rot, rail_to_collect)
        self.assertEqual(events[rail_to_collect][2], {"target": {"lit": 3}})
        self.assertLess(rail_to_collect, collect_put)
        self.assertLess(collect_put, clamp)
        self.assertLess(clamp, extend)
        self.assertLess(extend, bottle_put)

        call_names = [name for kind, name, _args in events if kind == "call"]
        self.assertNotIn("collect.lift_press", call_names)
        self.assertNotIn("collect.transport_extend", call_names)

    def test_collect_execute_wraps_elution_with_pose_actions(self) -> None:
        events = _events(self.docs["collect_execute"])
        lift_press = _index(events, "call", "collect.lift_press")
        collect = _index(events, "call", "collect.collect")
        transport_extend = _index(events, "call", "collect.transport_extend")

        self.assertLess(lift_press, collect)
        self.assertLess(collect, transport_extend)
        self.assertEqual(
            events[collect][2],
            {
                "solvent_volume_ml": {"var": "solvent_volume_ml"},
                "liquid_repeat_count": {"var": "liquid_repeat_count"},
            },
        )

    def test_collect_unload_takes_bottle_before_collector(self) -> None:
        events = _events(self.docs["collect_unload"])
        bottle_pick = _index(events, "run_script", "transfer_bottle_collect_to_staging_b")
        retract = _index(events, "call", "collect.retract")
        collector_enter = _index(events, "run_script", "robot_collect_holder_pick_enter")
        release_clamp = _index(events, "call", "collect.release_clamp")
        collector_exit = _index(events, "run_script", "robot_collect_holder_pick_exit")
        collector_return = _index(events, "run_script", "robot_collector_return_put")

        self.assertLess(bottle_pick, retract)
        self.assertLess(retract, collector_enter)
        self.assertLess(collector_enter, release_clamp)
        self.assertLess(release_clamp, collector_exit)
        self.assertLess(collector_exit, collector_return)
        call_names = [name for kind, name, _args in events if kind == "call"]
        self.assertNotIn("collect.transport_extend", call_names)

    def test_collect_station_steps_do_not_manage_staging_b_locator(self) -> None:
        self.assertEqual(self.registry.get("collect.lift_press").params, ())
        self.assertEqual(self.registry.get("collect.transport_extend").params, ())
        for script in ("collect_load", "collect_execute", "collect_unload"):
            with self.subTest(script=script):
                call_names = [
                    name
                    for kind, name, _args in _events(self.docs[script])
                    if kind == "call"
                ]
                self.assertNotIn("collect.bottle_locator", call_names)
                self.assertNotIn("staging_a.locator_a", call_names)
                self.assertNotIn("staging_a.locator_b", call_names)

    def test_collect_bottle_single_transfer_stays_at_collect_rail_position(self) -> None:
        # Win B (B2/B3): 单瓶转运 (中转B位3 ↔ 收集位3, 同轨) 已删 rail_move_safe; "全程停位3不移轨"
        # 的语义现由途经 robot 原子 (individual_pick / collect_bottle_pick / put, 均 rail=3) enter 的
        # rail.ensure(3) 保证 (点 rail 一致性见 test_rail_point_consistency)。本用例守: 编排层零
        # rail_move_safe + 取/放顺序不变。
        to_collect = _events(self.transfer_docs["transfer_bottle_staging_b_to_collect"])
        self.assertFalse(any(k == "run_script" and n == "rail_move_safe" for k, n, _ in to_collect),
                         "transfer_bottle_staging_b_to_collect 应已删 rail_move_safe (迁移到 rail.ensure)")
        staging_pick = _index(to_collect, "run_script", "robot_individual_pick")
        collect_put = _index(to_collect, "run_script", "robot_collect_bottle_put")
        self.assertLess(staging_pick, collect_put)

        to_staging = _events(self.transfer_docs["transfer_bottle_collect_to_staging_b"])
        self.assertFalse(any(k == "run_script" and n == "rail_move_safe" for k, n, _ in to_staging),
                         "transfer_bottle_collect_to_staging_b 应已删 rail_move_safe (迁移到 rail.ensure)")

    def test_collect_rail_resource_is_declared_for_direct_and_wrapped_runs(self) -> None:
        for script in ("collect_cycle", "collect_load", "collect_unload"):
            with self.subTest(script=script):
                self.assertIn("station:rail", self.docs[script].get("resources") or [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
