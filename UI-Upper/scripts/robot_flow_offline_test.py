#!/usr/bin/env python3
"""Robot flow catalog/executor offline tests."""

from __future__ import annotations

import math
import threading
import sys
import unittest
from pathlib import Path
from typing import Sequence

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from core.robot_flow import RobotFlowError, RobotFlowService  # noqa: E402
from robot_flow_baseline import load_frozen_baseline  # noqa: E402
from core.robot_service import RobotActionService  # noqa: E402
from core.robot_transport import (  # noqa: E402
    MotionOptions,
    RobotFeedback,
    RobotTransport,
    RobotTransportError,
    ToolAction,
    ToolState,
)


class FakeRobotTransport(RobotTransport):
    def __init__(self, registry: PointRegistry) -> None:
        self.registry = registry
        home = registry.get("robot-main.home")
        assert home.joint is not None
        self.pose = home.pose
        self.joint = home.joint
        self.records: list[tuple[str, object, MotionOptions | None]] = []
        self.fail_after: int | None = None
        self.block_first_move = False
        self._blocked_once = False
        self.move_entered = threading.Event()
        self.release_move = threading.Event()

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        self._record("query", None, options)
        return self._feedback(24)

    def home(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        point = self.registry.get("robot-main.home")
        return self.move_j(point.pose, options, joint=point.joint)

    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback:
        target = tuple(float(v) for v in pose)
        self._record("move_j", target, options)
        if self.block_first_move and not self._blocked_once:
            self._blocked_once = True
            self.move_entered.set()
            if not self.release_move.wait(2.0):
                raise RobotTransportError("test did not release blocked move")
        self._update_position(target, joint)
        return self._feedback(25)

    def move_l(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
    ) -> RobotFeedback:
        target = tuple(float(v) for v in pose)
        self._record("move_l", target, options)
        self._update_position(target, None)
        return self._feedback(27)

    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        self._record("tool_action", ToolAction(action), None)
        return self._feedback(28)

    def _record(self, kind: str, value: object, options: MotionOptions | None) -> None:
        if self.fail_after is not None and len(self.records) >= self.fail_after:
            raise RobotTransportError("injected flow failure")
        self.records.append((kind, value, options))

    def _update_position(
        self,
        pose: tuple[float, ...],
        joint: Sequence[float] | None,
    ) -> None:
        self.pose = pose
        if joint is not None:
            self.joint = tuple(float(v) for v in joint)
            return
        for point in self.registry.points:
            if point.pose == pose and point.joint is not None:
                self.joint = point.joint
                return

    def _feedback(self, last_action: int) -> RobotFeedback:
        return RobotFeedback(
            pose=self.pose,
            joint=self.joint,
            check_result=0,
            last_action=last_action,
            tool_state=ToolState(0, None, 0, False, False),
        )


class RobotFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        source = UI_ROOT.parent / "机器人程序" / "机器人程序v0.11" / "roboprogram" / "point.json"
        meta = UI_ROOT / "config" / "robot_points_meta.json"
        flow_source = UI_ROOT / "config" / "robot_flows_v1_baseline.yaml"
        self.registry = PointRegistry.load(
            source,
            source_version="v0.11",
            meta_path=meta,
        )
        self.baseline = load_frozen_baseline(flow_source)

    def _service(self) -> tuple[FakeRobotTransport, RobotFlowService, list[float]]:
        transport = FakeRobotTransport(self.registry)
        action_service = RobotActionService(
            transport,
            self.registry,
            home_point="robot-main.home",
        )
        sleeps: list[float] = []
        return (
            transport,
            RobotFlowService(
                action_service,
                self.registry,
                sleep_fn=sleeps.append,
            ),
            sleeps,
        )

    # ---- offset derivation tests ------------------------------------------------

    def test_offset_derived_point_has_correct_pose(self) -> None:
        """Offset-derived approach points equal base_point + offset."""
        high = self.registry.get("robot-main.tool-change.slot-1.approach-high")
        near = self.registry.get("robot-main.tool-change.slot-1.approach-near")
        p8 = self.registry.get("robot-main.tool-change.slot-1.target")
        for i in range(6):
            self.assertAlmostEqual(high.pose[i], p8.pose[i] + [0, 0, 200, 0, 0, 0][i], places=5)
            self.assertAlmostEqual(near.pose[i], p8.pose[i] + [0, 0, 20, 0, 0, 0][i], places=5)
        # Same for slot 2 (P9) and slot 3 (P10)
        high2 = self.registry.get("robot-main.tool-change.slot-2.approach-high")
        p9 = self.registry.get("robot-main.tool-change.slot-2.target")
        for i in range(6):
            self.assertAlmostEqual(high2.pose[i], p9.pose[i] + [0, 0, 200, 0, 0, 0][i], places=5)

    def test_offset_derived_point_has_no_joints(self) -> None:
        """Offset-derived points must have joint=None (move_l only)."""
        for slot in (1, 2, 3):
            for variant in ("approach-high", "approach-near"):
                pid = f"robot-main.tool-change.slot-{slot}.{variant}"
                point = self.registry.get(pid)
                self.assertIsNone(point.joint, f"{pid} joint must be None")
                self.assertEqual(point.allowed_motion, ("move_l",), f"{pid} must be move_l only")

    def test_offset_derived_point_has_derivation_metadata(self) -> None:
        """Offset-derived points carry derived_from and derivation provenance."""
        high = self.registry.get("robot-main.tool-change.slot-1.approach-high")
        self.assertEqual(high.derived_from, "P8")
        self.assertIn("offset", high.derivation)
        high2 = self.registry.get("robot-main.tool-change.slot-2.approach-high")
        self.assertEqual(high2.derived_from, "P9")

    def test_offset_cross_validation_rejects_mismatch(self) -> None:
        """A supplement point with both offset and conflicting pose raises ValueError."""
        records = [
            {
                "source_id": "bad-point",
                "robot_name": "BAD_POINT",
                "point_id": "robot-main.test.bad",
                "alias": "Bad",
                "workstation": "global",
                "role": "approach",
                "user": 0, "tool": 1,
                "allowed_motion": ["move_l"],
                "status": "validated",
                "base_point": "P8",
                "offset": [0, 0, 200, 0, 0, 0],
                "pose": [999.0, 999.0, 999.0, 999.0, 999.0, 999.0],  # deliberately wrong
            },
        ]
        p8 = self.registry.get("P8")
        src_points = [p8]
        with self.assertRaises(ValueError):
            PointRegistry._build_supplemental(
                records, src_points,
                meta_source_version="test",
                meta_path=UI_ROOT / "config" / "robot_points_meta.json",
                meta_checksum="fake",
            )

    def test_offset_missing_base_point_raises(self) -> None:
        """A supplement point referencing a nonexistent base point raises ValueError."""
        records = [
            {
                "source_id": "orphan",
                "robot_name": "ORPHAN",
                "point_id": "robot-main.test.orphan",
                "alias": "Orphan",
                "workstation": "global",
                "role": "approach",
                "user": 0, "tool": 1,
                "allowed_motion": ["move_l"],
                "status": "validated",
                "base_point": "P999",
                "offset": [0, 0, 200, 0, 0, 0],
            },
        ]
        src_points = [self.registry.get("P8")]
        with self.assertRaises(ValueError):
            PointRegistry._build_supplemental(
                records, src_points,
                meta_source_version="test",
                meta_path=UI_ROOT / "config" / "robot_points_meta.json",
                meta_checksum="fake",
            )

    # ---- flow tests (unchanged) -----------------------------------------------

    def test_catalog_contains_explicit_legacy_approach_points(self) -> None:
        self.assertEqual(len(self.baseline), 7)
        high = self.registry.get("robot-main.tool-change.slot-1.approach-high")
        near = self.registry.get("robot-main.tool-change.slot-1.approach-near")
        self.assertEqual(high.pose[2], 138.003296)
        self.assertEqual(near.pose[2], -41.996704)
        self.assertIsNone(high.joint)
        self.assertEqual(high.allowed_motion, ("move_l",))

    def test_pick_flow_matches_legacy_order_and_profiles(self) -> None:
        transport, service, sleeps = self._service()
        result = service.run_resolved(self.baseline["tool.pick.1"])
        kinds = [record[0] for record in transport.records]
        self.assertEqual(
            kinds,
            [
                "query",
                "move_j",
                "move_l",
                "move_l",
                "move_l",
                "tool_action",
                "tool_action",
                "move_l",
                "move_l",
                "move_j",
                "move_j",
            ],
        )
        tool_actions = [record[1] for record in transport.records if record[0] == "tool_action"]
        self.assertEqual(
            tool_actions,
            [ToolAction.QUICK_CHANGE_LOCK, ToolAction.TOOL_CHANGE_AUX_ON],
        )
        move_l_options = [record[2] for record in transport.records if record[0] == "move_l"]
        self.assertEqual(move_l_options[1].vel, 15)
        self.assertEqual(move_l_options[3].vel, 10)
        self.assertEqual(sleeps, [0.5])
        self.assertEqual(result.final_feedback.joint, self.registry.get("robot-main.home").joint)

    def test_put_slot_one_preserves_aux_prepare_and_lock_order(self) -> None:
        transport, service, sleeps = self._service()
        service.run_resolved(self.baseline["tool.put.1"])
        tool_actions = [record[1] for record in transport.records if record[0] == "tool_action"]
        self.assertEqual(
            tool_actions,
            [
                ToolAction.TOOL_CHANGE_AUX_ON,
                ToolAction.QUICK_CHANGE_RELEASE,
                ToolAction.TOOL_CHANGE_AUX_OFF,
            ],
        )
        self.assertEqual(sleeps, [])

    def test_modbus_lua_contains_legacy_quick_change_timing_and_aux_actions(self) -> None:
        lua_path = UI_ROOT.parent / "unilabos迁移" / "robotsoftware" / "robot_mvp_minimal.lua"
        text = lua_path.read_text(encoding="utf-8")
        self.assertIn(
            "if action == TOOL_QUICK_CHANGE_LOCK then",
            text,
        )
        self.assertIn(
            "DO(TOOL_DO_QUICK_CHANGE, 0)\n"
            "    Wait(1000)",
            text,
        )
        self.assertIn(
            "elseif action == TOOL_QUICK_CHANGE_RELEASE then",
            text,
        )
        self.assertIn(
            "DO(TOOL_DO_QUICK_CHANGE, 1)\n"
            "    Wait(1000)",
            text,
        )
        self.assertIn("elseif action == TOOL_CHANGE_AUX_ON then", text)
        self.assertIn("elseif action == TOOL_CHANGE_AUX_OFF then", text)

    def test_entry_anchor_mismatch_rejects_before_motion(self) -> None:
        transport, service, _ = self._service()
        transport.joint = tuple(value + 20 for value in transport.joint)
        with self.assertRaises(RobotFlowError) as caught:
            service.run_resolved(self.baseline["tool.pick.1"])
        self.assertEqual(caught.exception.failed_step, "<entry-check>")
        self.assertEqual([record[0] for record in transport.records], ["query"])

    def test_flow_lease_prevents_interleaving_between_steps(self) -> None:
        transport, service, _ = self._service()
        transport.block_first_move = True
        errors: list[BaseException] = []

        def run_flow() -> None:
            try:
                service.run_resolved(self.baseline["tool.put.2"])
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=run_flow)
        second = threading.Thread(target=run_flow)
        first.start()
        self.assertTrue(transport.move_entered.wait(1.0))
        second.start()
        threading.Event().wait(0.05)
        self.assertEqual([record[0] for record in transport.records], ["query", "move_j"])
        transport.release_move.set()
        first.join(2.0)
        second.join(2.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sum(record[0] == "query" for record in transport.records), 2)

    def test_failure_stops_remaining_steps(self) -> None:
        transport, service, _ = self._service()
        transport.fail_after = 4
        with self.assertRaises(RobotFlowError):
            service.run_resolved(self.baseline["tool.pick.1"])
        self.assertNotIn("tool_action", [record[0] for record in transport.records])


if __name__ == "__main__":
    unittest.main(verbosity=2)

