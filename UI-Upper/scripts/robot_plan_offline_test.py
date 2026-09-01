#!/usr/bin/env python3
"""Offline tests for schema-v2 robot plan resolution."""

from __future__ import annotations

import tempfile
import sys
import unittest
from dataclasses import asdict
from pathlib import Path

import yaml

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from robot_flow_baseline import load_frozen_baseline  # noqa: E402
from core.robot_plan import RobotPlanCatalog, RobotPlanError  # noqa: E402


def flow_signature(flow: object) -> tuple[object, ...]:
    return (
        flow.entry_point,
        flow.exit_point,
        tuple(
            (type(step).__name__, tuple(sorted(asdict(step).items())))
            for step in flow.steps
        ),
        flow.anchor_joint_tolerance_deg,
        flow.anchor_position_tolerance_mm,
        flow.anchor_rotation_tolerance_deg,
    )


class RobotPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        point_source = (
            UI_ROOT.parent
            / "robot program"
            / "robot programv0.11"
            / "roboprogram"
            / "point.json"
        )
        # Use real non-ASCII paths without embedding them into this source.
        candidates = list(UI_ROOT.parent.glob("*/**/roboprogram/point.json"))
        self.assertTrue(candidates)
        point_source = candidates[0]
        meta = UI_ROOT / "config" / "robot_points_meta.json"
        self.registry = PointRegistry.load(
            point_source,
            source_version="v0.11",
            meta_path=meta,
        )
        self.legacy = load_frozen_baseline(
            UI_ROOT / "config" / "robot_flows_v1_baseline.yaml"
        )
        self.catalog = RobotPlanCatalog.load(
            UI_ROOT / "config" / "robot_flows_v2.yaml",
            self.registry,
        )

    def _load_changed(self, old: str, new: str) -> RobotPlanCatalog:
        text = (
            UI_ROOT / "config" / "robot_flows_v2.yaml"
        ).read_text(encoding="utf-8")
        changed = text.replace(old, new, 1)
        self.assertNotEqual(changed, text)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "changed.yaml"
            path.write_text(changed, encoding="utf-8")
            return RobotPlanCatalog.load(path, self.registry)

    def test_production_and_test_catalogs_are_separate(self) -> None:
        self.assertIn("tool.pick", self.catalog.template_ids)
        self.assertIn("tool.put", self.catalog.template_ids)
        self.assertEqual(self.catalog.test_template_ids, ("test.gripper",))
        with self.assertRaises(RobotPlanError):
            self.catalog.resolve("test.gripper", {"test_id": "p2"})

    def test_all_six_tool_flows_match_frozen_v1(self) -> None:
        for action in ("pick", "put"):
            for tool_id in (1, 2, 3):
                with self.subTest(action=action, tool_id=tool_id):
                    resolved = self.catalog.resolve(
                        f"tool.{action}",
                        {"tool_id": tool_id},
                    )
                    legacy = self.legacy[f"tool.{action}.{tool_id}"]
                    self.assertEqual(
                        flow_signature(resolved.flow),
                        flow_signature(legacy),
                    )

    def test_slot_one_put_uses_controlled_extension_only(self) -> None:
        first = self.catalog.resolve("tool.put", {"tool_id": 1})
        second = self.catalog.resolve("tool.put", {"tool_id": 2})
        first_ids = [step.step_id for step in first.flow.steps]
        second_ids = [step.step_id for step in second.flow.steps]
        self.assertIn("slot-1-aux-prepare", first_ids)
        self.assertNotIn("slot-1-aux-prepare", second_ids)
        self.assertEqual(len(first_ids), len(second_ids) + 1)

    def test_business_params_and_point_set_are_logged_in_plan(self) -> None:
        plan = self.catalog.resolve("tool.pick", {"tool_id": 3})
        self.assertEqual(plan.business_params, (("tool_id", 3),))
        self.assertEqual(plan.point_set_id, "tool-slot-3")
        self.assertTrue(plan.config_sha256)
        self.assertEqual(plan.config_version, "2.2.0-orchestration")
        self.assertIn(
            ("target", "robot-main.tool-change.slot-3.target"),
            plan.resolved_points,
        )

    def test_invalid_and_extra_business_params_are_rejected(self) -> None:
        with self.assertRaises(RobotPlanError):
            self.catalog.resolve("tool.pick", {"tool_id": 0})
        with self.assertRaises(RobotPlanError):
            self.catalog.resolve("tool.pick", {"tool_id": 4})
        with self.assertRaises(RobotPlanError):
            self.catalog.resolve(
                "tool.pick",
                {"tool_id": 1, "slot_id": 1},
            )

    def test_point_set_mapping_is_immutable(self) -> None:
        point_set = self.catalog.stations.get("tool-slot-1")
        with self.assertRaises(TypeError):
            point_set.points["target"] = "P1"  # type: ignore[index]

    def test_wrong_route_group_is_rejected_before_motion(self) -> None:
        text = (
            UI_ROOT / "config" / "robot_flows_v2.yaml"
        ).read_text(encoding="utf-8")
        changed = text.replace(
            "route_group: tool-change",
            "route_group: tank-group-a",
            1,
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad-route.yaml"
            path.write_text(changed, encoding="utf-8")
            with self.assertRaises(RobotPlanError):
                RobotPlanCatalog.load(path, self.registry)

    def test_missing_point_is_rejected_during_preflight(self) -> None:
        with self.assertRaises(KeyError):
            self._load_changed(
                "target: robot-main.tool-change.slot-1.target",
                "target: missing.point",
            )

    def test_unvalidated_point_is_rejected_during_preflight(self) -> None:
        with self.assertRaises(PermissionError):
            self._load_changed(
                "target: robot-main.tool-change.slot-1.target",
                "target: P6",
            )

    def test_wrong_motion_type_is_rejected_during_preflight(self) -> None:
        with self.assertRaises(PermissionError):
            self._load_changed(
                (
                    "role: approach_high, motion: move_l, "
                    "profile: tool-high-in"
                ),
                (
                    "role: approach_high, motion: move_j, "
                    "profile: tool-high-in"
                ),
            )

    def test_robot_templates_contain_no_host_wait_types(self) -> None:
        data = yaml.safe_load((
            UI_ROOT / "config" / "robot_flows_v2.yaml"
        ).read_text(encoding="utf-8"))
        for section in ("templates", "test_templates"):
            for template in data[section].values():
                step_types = {step["type"] for step in template["steps"]}
                self.assertNotIn("plc_wait", step_types)
                self.assertNotIn("plc_action", step_types)
                self.assertNotIn("camera_action", step_types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
