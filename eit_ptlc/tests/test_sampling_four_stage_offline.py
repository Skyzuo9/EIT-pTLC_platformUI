#!/usr/bin/env python3
"""Sampling station four-stage contract checks.

These checks are static by design. They guard the operation shape and upper-
machine action contract, but do not prove PLC Sampling_L2 action 33 exists or
has been field-validated.
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
_SAMPLING_DIR = _PKG / "config" / "operation" / "01_sampling"


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


def _index(events: list[tuple[str, str, dict]], kind: str, name: str) -> int:
    for i, (event_kind, event_name, _args) in enumerate(events):
        if event_kind == kind and event_name == name:
            return i
    raise AssertionError(f"missing event {kind}:{name}")


class SamplingFourStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.actions = {action.name: action for action in cls.registry.list()}
        cls.docs = {path.stem: _load_doc(path) for path in sorted(_SAMPLING_DIR.glob("*.yaml"))}

    def test_sampling_scripts_validate(self) -> None:
        valid_actions = set(self.actions)
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_sampling_run_script_references_exist(self) -> None:
        all_script_names = {path.stem for path in _OPERATION_DIR.glob("*/*.yaml")}
        for name, doc in self.docs.items():
            for node in _walk(doc.get("body")):
                if node.get("op") == "run_script":
                    with self.subTest(script=name, child=node.get("script")):
                        self.assertIn(node.get("script"), all_script_names)

    def test_sampling_station_task_and_phase_ui_contract(self) -> None:
        task_names = [
            name
            for name, doc in self.docs.items()
            if doc.get("ui", {}).get("role") == "station_task"
            and doc.get("ui", {}).get("station") == "sampling"
        ]
        # 多样品周期是第二个工位任务: 同一四段骨架, execute 段换成板内多条带 (primary 仍归单样品周期)
        self.assertEqual(task_names, ["sampling_cycle", "sampling_multi_cycle"])

        task_ui = self.docs["sampling_cycle"].get("ui", {})
        self.assertTrue(task_ui.get("primary"))
        self.assertEqual(task_ui.get("order"), 10)
        self.assertFalse(task_ui.get("hidden", False))

        multi_task_ui = self.docs["sampling_multi_cycle"].get("ui", {})
        self.assertFalse(multi_task_ui.get("primary", False))
        self.assertEqual(multi_task_ui.get("order"), 15)
        self.assertFalse(multi_task_ui.get("hidden", False))

        expected_phases = [
            ("sampling_prepare", "prepare", 11),
            ("sampling_load", "load", 12),
            ("sampling_execute", "execute", 13),
            ("sampling_unload", "unload", 14),
        ]
        phase_names = []
        for name, phase, order in expected_phases:
            with self.subTest(script=name):
                ui = self.docs[name].get("ui", {})
                self.assertEqual(ui.get("role"), "station_phase")
                self.assertEqual(ui.get("station"), "sampling")
                self.assertEqual(ui.get("phase"), phase)
                self.assertTrue(ui.get("primary"))
                self.assertEqual(ui.get("order"), order)
                self.assertFalse(ui.get("hidden", False))
                phase_names.append(name)

        visible_sampling_phases = [
            name
            for name, doc in sorted(
                self.docs.items(), key=lambda item: item[1].get("ui", {}).get("order", 999)
            )
            if doc.get("ui", {}).get("role") == "station_phase"
            and doc.get("ui", {}).get("station") == "sampling"
            and not doc.get("ui", {}).get("hidden", False)
        ]
        # 多样品执行段与 sampling_execute 平级 (同 phase=execute), 非 primary, 排在四段之后
        multi_exec_ui = self.docs["sampling_multi_execute"].get("ui", {})
        self.assertEqual(multi_exec_ui.get("role"), "station_phase")
        self.assertEqual(multi_exec_ui.get("station"), "sampling")
        self.assertEqual(multi_exec_ui.get("phase"), "execute")
        self.assertFalse(multi_exec_ui.get("primary", False))
        self.assertEqual(multi_exec_ui.get("order"), 15)
        self.assertEqual(visible_sampling_phases, phase_names + ["sampling_multi_execute"])

        for name in ("sampling_place_plate", "sampling_spot", "sampling_volume_model"):
            with self.subTest(script=name):
                self.assertEqual(self.docs[name].get("ui", {}).get("role"), "helper")
                self.assertTrue(self.docs[name].get("ui", {}).get("hidden"))
        self.assertEqual(self.docs["sampling_full"].get("ui", {}).get("role"), "legacy")
        self.assertTrue(self.docs["sampling_full"].get("ui", {}).get("hidden"))

    def test_sampling_cycle_is_four_stage_wrapper(self) -> None:
        non_comment_nodes = [
            node for node in self.docs["sampling_cycle"].get("body", []) if node.get("op") != "comment"
        ]
        self.assertEqual(
            [(node.get("op"), node.get("script")) for node in non_comment_nodes],
            [
                ("run_script", "sampling_prepare"),
                ("run_script", "sampling_load"),
                ("run_script", "sampling_execute"),
                ("run_script", "sampling_unload"),
            ],
        )
        execute_inputs = non_comment_nodes[2].get("inputs") or {}
        self.assertEqual(
            execute_inputs,
            {
                "plate_spec": {"var": "plate_spec"},
                "plate_no": {"var": "plate_no"},
                "well": {"var": "well"},
            },
        )

    def test_sampling_phase_actions_preserve_cycle_order(self) -> None:
        prepare_events = _events(self.docs["sampling_prepare"])
        # 真空泵开关已由 with_resources(device:vacuum_pump) 区间接管, 编排层不再出现 pump.vacuum_*;
        # 区间落位由 test_vacuum_shared_resource_offline 守卫。
        self.assertEqual(
            [(kind, name) for kind, name, _ in prepare_events],
            [
                ("call", "sampling.init"),
                ("call", "sampling.flush"),
                ("call", "sampling.place_axis"),
            ],
        )

        load_events = _events(self.docs["sampling_load"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in load_events],
            [
                # 自守卫点样座: 单独点跑时没有 prepare 顺带把 7Y 带到放板位, 本段必须自己做。
                # 必须先松夹再移轴, 且整体排在取板之前 —— 7Y 超时可在空手时干净中止。
                ("call", "sampling.place_release"),
                ("call", "sampling.place_axis"),
                ("run_script", "feedlift_load_cycle"),  # 升降上料取板并入上料首段
                ("run_script", "robot_suction_put"),
                ("call", "sampling.place_locate"),
            ],
        )
        self.assertEqual(load_events[_index(load_events, "run_script", "feedlift_load_cycle")][2], {})

        # execute 全程口3回抽/打出, 分配阀不切废液口, 故不括真空泵 (prepare 的 flush 外壁段才需要);
        # 气隔断已并入 A50 (移孔位前吸), execute 不再调 sampling.prep
        execute_events = _events(self.docs["sampling_execute"])
        aspirate = _index(execute_events, "call", "sampling.aspirate")
        spot = _index(execute_events, "call", "sampling.spot_band_layer")
        self.assertLess(aspirate, spot)
        self.assertNotIn("sampling.prep", [name for kind, name, _ in execute_events])
        self.assertNotIn("pump.vacuum_on", [name for kind, name, _ in execute_events])
        self.assertNotIn("pump.vacuum_off", [name for kind, name, _ in execute_events])

        unload_events = _events(self.docs["sampling_unload"])
        self.assertEqual(
            [(kind, name) for kind, name, _ in unload_events],
            [
                ("call", "sampling.place_axis"),   # 取放同点: 取板前先 7Y 带板回放板位 (P19); 必须先回位再松夹
                ("call", "sampling.place_release"),
                ("run_script", "rail_move_safe"),  # 自守卫地轨在上样位(位1)再取板
                ("run_script", "robot_suction_pick"),
            ],
        )
        self.assertEqual(unload_events[2][2], {"target": {"lit": 1}})

    def test_sampling_execute_uses_plate_well_contract(self) -> None:
        events = _events(self.docs["sampling_execute"])
        aspirate = events[_index(events, "call", "sampling.aspirate")]
        self.assertEqual(
            {"plate_spec", "plate_no", "well", "sample_volume_ml", "air_gap_ml",
             "asp_speed", "step_delay"},
            set(aspirate[2]),
        )
        self.assertNotIn("source_x", aspirate[2])
        self.assertNotIn("source_y", aspirate[2])

    def test_sampling_unload_documents_handoff_boundary(self) -> None:
        comments = [
            str(node.get("text", ""))
            for node in _walk(self.docs["sampling_unload"].get("body"))
            if node.get("op") == "comment"
        ]
        text = "\n".join(comments)
        self.assertIn("handoff", text)
        self.assertIn("机器人持板 home 不是可抢占空闲态", text)

    def test_sampling_l2_actions_are_declared_but_not_field_proven_here(self) -> None:
        action = self.actions["sampling.place_release"]
        self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "sampling", 33))
        action = self.actions["sampling.spot_band_layer"]
        self.assertEqual((action.kind, action.station, action.action_code), ("plc_l2", "sampling", 62))


if __name__ == "__main__":
    unittest.main(verbosity=2)
