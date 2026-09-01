#!/usr/bin/env python3
"""Offline tests for schema-v2 robot plan resolution."""

from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

import yaml

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.operation.robot_routes.robot_flow import SetMountedToolStep, ToolStep  # noqa: E402
from eit_ptlc.operation.robot_routes.robot_plan import RobotPlanCatalog, RobotPlanError  # noqa: E402
from eit_ptlc.driver.robot_transport import ToolAction  # noqa: E402


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
        meta = UI_ROOT / "config" / "points" / "robot" / "robot_points_meta.json"
        self.registry = PointRegistry.load(
            point_source,
            source_version="v0.11",
            meta_path=meta,
        )
        self.catalog = RobotPlanCatalog.load(
            UI_ROOT / "config" / "backup" / "robot_flows_v2.yaml",
            self.registry,
        )

    def _load_changed(self, old: str, new: str) -> RobotPlanCatalog:
        text = (
            UI_ROOT / "config" / "backup" / "robot_flows_v2.yaml"
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

    def test_slot_one_put_uses_controlled_extension_only(self) -> None:
        first = self.catalog.resolve("tool.put", {"tool_id": 1})
        second = self.catalog.resolve("tool.put", {"tool_id": 2})
        first_ids = [step.step_id for step in first.flow.steps]
        second_ids = [step.step_id for step in second.flow.steps]
        self.assertIn("slot-1-aux-prepare", first_ids)
        self.assertNotIn("slot-1-aux-prepare", second_ids)
        self.assertEqual(len(first_ids), len(second_ids) + 1)

    def test_tool_pick_declares_selected_slot(self) -> None:
        # tool.pick 每个分支声明本分支 tool_id; tool.put 声明 0 (裸腕)
        for tid in (1, 2, 3):
            steps = self.catalog.resolve("tool.pick", {"tool_id": tid}).flow.steps
            decls = [s for s in steps if isinstance(s, SetMountedToolStep)]
            self.assertEqual([s.tool_id for s in decls], [tid])
            put_steps = self.catalog.resolve("tool.put", {"tool_id": tid}).flow.steps
            put_decls = [s for s in put_steps if isinstance(s, SetMountedToolStep)]
            self.assertEqual([s.tool_id for s in put_decls], [0])

    def test_flip_is_tank_and_spotting_only(self) -> None:
        # tank 进缸下翻; spotting 取/放上翻 (放另有退出下翻); scrape/waste 不翻
        def rotaries(plan):
            return [s.action for s in plan.flow.steps
                    if isinstance(s, ToolStep) and s.action in (ToolAction.ROTARY_UP, ToolAction.ROTARY_DOWN)]

        self.assertEqual(rotaries(self.catalog.resolve("tank.pick", {"tank_id": 1})), [ToolAction.ROTARY_DOWN])
        self.assertEqual(rotaries(self.catalog.resolve("tank.put", {"tank_id": 1})), [ToolAction.ROTARY_DOWN])
        self.assertEqual(rotaries(self.catalog.resolve("suction.pick", {"station_id": "spotting"})),
                         [ToolAction.ROTARY_UP])
        self.assertEqual(rotaries(self.catalog.resolve("suction.put", {"station_id": "spotting"})),
                         [ToolAction.ROTARY_UP, ToolAction.ROTARY_DOWN])
        self.assertEqual(rotaries(self.catalog.resolve("suction.pick", {"station_id": "scrape"})), [])
        self.assertEqual(rotaries(self.catalog.resolve("suction.put", {"station_id": "scrape"})), [])
        self.assertEqual(rotaries(self.catalog.resolve("suction.put", {"station_id": "waste"})), [])

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
            UI_ROOT / "config" / "backup" / "robot_flows_v2.yaml"
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
            UI_ROOT / "config" / "backup" / "robot_flows_v2.yaml"
        ).read_text(encoding="utf-8"))
        for section in ("templates", "test_templates"):
            for template in data[section].values():
                step_types = {step["type"] for step in template["steps"]}
                self.assertNotIn("plc_wait", step_types)
                self.assertNotIn("plc_action", step_types)
                self.assertNotIn("camera_action", step_types)


if __name__ == "__main__":
    unittest.main(verbosity=2)
