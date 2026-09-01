#!/usr/bin/env python3
"""Software-loop tests for route execution and fail-stop semantics."""

from __future__ import annotations

import sys
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Mapping

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from core.robot_plan import RobotPlanCatalog  # noqa: E402
from core.robot_route import RoutePlanner  # noqa: E402
from core.robot_route_executor import (  # noqa: E402
    RouteExecutionError,
    RouteExecutor,
)


class FakeActionService:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.lease_depth = 0

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        with self.lock:
            self.lease_depth += 1
            try:
                yield
            finally:
                self.lease_depth -= 1


class FakeResourceLedger:
    def __init__(self) -> None:
        self.held = False
        self.history: list[str] = []
        self.lock = threading.RLock()

    @contextmanager
    def lease(self, resources: object, params: object) -> Iterator[None]:
        with self.lock:
            self.history.append("acquire")
            self.held = True
            try:
                yield
            finally:
                self.held = False
                self.history.append("release")


class FakeFlowService:
    def __init__(
        self,
        action: FakeActionService,
        resources: FakeResourceLedger,
    ) -> None:
        self.action = action
        self.resources = resources
        self.records: list[str] = []
        self.block_first = False
        self._blocked = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def run_resolved(
        self,
        flow: object,
        on_step: object = None,
    ) -> dict[str, object]:
        self.assert_leases()
        if callable(on_step):
            on_step("fake-step", "RUNNING")
        self.records.append(flow.flow_id)
        if self.block_first and not self._blocked:
            self._blocked = True
            self.entered.set()
            if not self.release.wait(2):
                raise RuntimeError("test did not release robot flow")
        if callable(on_step):
            on_step("fake-step", "DONE")
        return {"flow_id": flow.flow_id, "steps": len(flow.steps)}

    def assert_leases(self) -> None:
        if self.action.lease_depth <= 0:
            raise AssertionError("robot transaction lease not held")
        if not self.resources.held:
            raise AssertionError("business resources not held")


class FakeHost:
    def __init__(
        self,
        action: FakeActionService,
        resources: FakeResourceLedger,
    ) -> None:
        self.action = action
        self.resources = resources
        self.records: list[tuple[str, str]] = []
        self.robot_lease_depths: list[tuple[str, int]] = []
        self.condition_values: dict[str, list[bool]] = {}
        self.fail_action: str | None = None
        # (position_code, lease_depth) 单独记录, 不污染 records 上的 plc/camera 断言
        self.rail_records: list[tuple[int, int]] = []

    def _assert_resources(self) -> None:
        if not self.resources.held:
            raise AssertionError("host action ran without business resources")

    def plc_action(self, action: str, params: Mapping[str, object]) -> object:
        self._assert_resources()
        self.robot_lease_depths.append((action, self.action.lease_depth))
        self.records.append(("plc_action", action))
        if action == self.fail_action:
            raise RuntimeError("injected PLC failure")
        return {"action": action, "accepted": True}

    def plc_condition(self, condition: str, params: Mapping[str, object]) -> bool:
        self._assert_resources()
        self.robot_lease_depths.append((condition, self.action.lease_depth))
        self.records.append(("plc_condition", condition))
        values = self.condition_values.get(condition)
        if values:
            return values.pop(0)
        return True

    def camera_action(self, action: str, params: Mapping[str, object]) -> object:
        self._assert_resources()
        self.robot_lease_depths.append((action, self.action.lease_depth))
        self.records.append(("camera_action", action))
        return {"ok": True, "raw": {"frame_id": "offline-1", "score": 0.87}}

    def rail_move(self, position_code: int) -> object:
        self._assert_resources()
        self.rail_records.append((position_code, self.action.lease_depth))
        return {"station": "Rail", "position_code": position_code, "done": True}


class RouteExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        point_sources = list(UI_ROOT.parent.glob("*/**/roboprogram/point.json"))
        registry = PointRegistry.load(
            point_sources[0],
            source_version="v0.11",
            meta_path=UI_ROOT / "config" / "robot_points_meta.json",
        )
        config = UI_ROOT / "config" / "robot_flows_v2.yaml"
        catalog = RobotPlanCatalog.load(config, registry)
        self.planner = RoutePlanner.load(config, catalog)
        self.action = FakeActionService()
        self.resources = FakeResourceLedger()
        self.flows = FakeFlowService(self.action, self.resources)
        self.host = FakeHost(self.action, self.resources)
        self.events: list[dict[str, object]] = []
        self.clock = 0.0
        self.executor = RouteExecutor(
            action_service=self.action,  # type: ignore[arg-type]
            flow_service=self.flows,  # type: ignore[arg-type]
            host=self.host,
            resources=self.resources,
            event_sink=self.events.append,
            monotonic=lambda: self.clock,
            sleep=self._sleep,
        )

    def _sleep(self, duration: float) -> None:
        self.clock += duration

    def test_resources_and_robot_lease_cover_the_whole_transaction(self) -> None:
        plan = self.planner.resolve(
            "consumable.collector-staging-a-to-scrape",
            {"rack_id": "collector", "slot_id": 2},
        )
        result = self.executor.execute(plan)
        self.assertEqual(self.resources.history, ["acquire", "release"])
        self.assertFalse(self.resources.held)
        self.assertEqual(len(result.steps), len(plan.steps))
        self.assertEqual(
            [kind for kind, _ in self.host.records],
            [
                "plc_condition",
                "plc_action",
                "plc_condition",
                "plc_action",
            ],
        )

    def test_rail_moves_to_each_station_before_robot_flow_under_lock(self) -> None:
        # collector-staging-a-to-scrape: 取料(group=6) -> 刮板交接(scrape=2)
        plan = self.planner.resolve(
            "consumable.collector-staging-a-to-scrape",
            {"rack_id": "collector", "slot_id": 2},
        )
        self.executor.execute(plan)
        codes = [code for code, _ in self.host.rail_records]
        self.assertEqual(codes, [6, 2])
        # 地轨移动必须在机器人独占锁内 (lease_depth > 0)
        self.assertTrue(all(depth > 0 for _, depth in self.host.rail_records))

    def test_robot_lock_starts_at_first_flow_and_ends_at_last_flow(self) -> None:
        plan = self.planner.resolve("plate.feed-to-spotting", {})
        self.executor.execute(plan)
        depths = dict(self.host.robot_lease_depths)
        self.assertEqual(depths["feed-lift.pick-ready"], 0)
        self.assertGreater(depths["feed-lift.raise"], 0)
        self.assertGreater(depths["plate.calibrate"], 0)
        self.assertEqual(depths["spotting.clamp-plate"], 0)
    def test_plc_wait_polls_real_condition_until_true(self) -> None:
        condition = "scrape.holder-clamped"
        self.host.condition_values[condition] = [False, False, True]
        plan = self.planner.resolve(
            "consumable.collector-staging-a-to-scrape",
            {"rack_id": "collector", "slot_id": 1},
        )
        self.executor.execute(plan)
        checks = [item for item in self.host.records if item == ("plc_condition", condition)]
        self.assertEqual(len(checks), 3)
        self.assertAlmostEqual(self.clock, 0.2)

    def test_failure_stops_route_without_retry_or_recovery(self) -> None:
        self.host.fail_action = "scrape.clamp-holder"
        plan = self.planner.resolve(
            "consumable.collector-staging-a-to-scrape",
            {"rack_id": "collector", "slot_id": 1},
        )
        with self.assertRaises(RouteExecutionError) as caught:
            self.executor.execute(plan)
        self.assertEqual(caught.exception.failed_step, "clamp-holder")
        self.assertEqual(
            self.host.records.count(("plc_action", "scrape.clamp-holder")),
            1,
        )
        self.assertNotIn("scrape.holder.put-exit", self.flows.records)
        self.assertFalse(self.resources.held)
        event_names = [event["event"] for event in self.events]
        self.assertIn("step_failed", event_names)
        self.assertIn("route_failed", event_names)

    def test_requested_stop_blocks_every_subsequent_step(self) -> None:
        stopped = False

        def sink(event: dict[str, object]) -> None:
            nonlocal stopped
            self.events.append(event)
            if event["event"] == "step_done":
                stopped = True

        executor = RouteExecutor(
            action_service=self.action,  # type: ignore[arg-type]
            flow_service=self.flows,  # type: ignore[arg-type]
            host=self.host,
            resources=self.resources,
            event_sink=sink,
            monotonic=lambda: self.clock,
            sleep=self._sleep,
            stop_requested=lambda: stopped,
        )
        plan = self.planner.resolve("plate.scrape-to-waste", {})
        with self.assertRaises(RouteExecutionError) as caught:
            executor.execute(plan)
        # 第一个机器人步骤前已注入"地轨到站", 故 stop 首先命中该地轨步骤
        self.assertEqual(caught.exception.failed_step, "rail--scrape-pick")
        self.assertEqual(self.flows.records, [])
        self.assertFalse(self.resources.held)

    def test_robot_step_status_is_in_execution_log(self) -> None:
        plan = self.planner.resolve("plate.scrape-to-waste", {})
        self.executor.execute(plan)
        robot_events = [
            event for event in self.events
            if event["event"] == "robot_step_status"
        ]
        self.assertTrue(robot_events)
        self.assertEqual({event["status"] for event in robot_events}, {"RUNNING", "DONE"})

    def test_camera_raw_result_is_logged_but_does_not_change_robot_plan(self) -> None:
        plan = self.planner.resolve("plate.feed-to-spotting", {})
        robot_before = [
            step.plan for step in plan.steps if hasattr(step, "plan")
        ]
        self.executor.execute(plan)
        robot_after = [
            step.plan for step in plan.steps if hasattr(step, "plan")
        ]
        self.assertEqual(robot_before, robot_after)
        camera_events = [
            event
            for event in self.events
            if event.get("step_id") == "camera-calibrate"
            and event["event"] == "step_done"
        ]
        self.assertEqual(len(camera_events), 1)
        self.assertEqual(
            camera_events[0]["raw_result"]["raw"]["frame_id"],
            "offline-1",
        )

    def test_transaction_lock_prevents_route_interleaving(self) -> None:
        self.flows.block_first = True
        plan = self.planner.resolve("plate.scrape-to-waste", {})
        errors: list[BaseException] = []

        def run() -> None:
            try:
                self.executor.execute(plan)
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        self.assertTrue(self.flows.entered.wait(1))
        second.start()
        threading.Event().wait(0.05)
        self.assertEqual(len(self.flows.records), 1)
        self.flows.release.set()
        first.join(2)
        second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
