#!/usr/bin/env python3
"""Offline resolution tests for all fourteen robot business routes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from core.robot_plan import RobotPlanCatalog  # noqa: E402
from core.robot_route import (  # noqa: E402
    CameraActionStep,
    PlcWaitStep,
    RailMoveStep,
    RobotRouteError,
    RobotRouteStep,
    RouteDefinition,
    RoutePlanner,
)


class RobotRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        candidates = list(UI_ROOT.parent.glob("*/**/roboprogram/point.json"))
        self.assertTrue(candidates)
        registry = PointRegistry.load(
            candidates[0],
            source_version="v0.11",
            meta_path=UI_ROOT / "config" / "robot_points_meta.json",
        )
        config = UI_ROOT / "config" / "robot_flows_v2.yaml"
        self.catalog = RobotPlanCatalog.load(config, registry)
        self.planner = RoutePlanner.load(config, self.catalog)

    def legal_cases(self) -> list[tuple[str, dict[str, object]]]:
        cases: list[tuple[str, dict[str, object]]] = [
            ("plate.feed-to-spotting", {}),
            ("plate.spotting-to-scrape", {}),
            ("plate.scrape-to-waste", {}),
            ("consumable.collector-scrape-to-collect", {}),
        ]
        for tank_id in range(1, 9):
            cases.append(("plate.scrape-to-tank", {"tank_id": tank_id}))
            cases.append(("plate.tank-to-scrape", {"tank_id": tank_id}))
        for slot_id in range(1, 7):
            cases.extend(
                [
                    (
                        "consumable.bottle-group-rack-to-staging-b",
                        {"rack_id": "bottle", "slot_id": slot_id},
                    ),
                    (
                        "consumable.collector-group-rack-to-staging-a",
                        {"rack_id": "collector", "slot_id": slot_id},
                    ),
                    (
                        "consumable.bottle-group-staging-b-to-rack",
                        {"rack_id": "bottle", "slot_id": slot_id},
                    ),
                    (
                        "consumable.collector-group-staging-a-to-rack",
                        {"rack_id": "collector", "slot_id": slot_id},
                    ),
                    (
                        "consumable.collector-staging-a-to-scrape",
                        {"rack_id": "collector", "slot_id": slot_id},
                    ),
                    (
                        "consumable.bottle-staging-b-to-collect",
                        {"rack_id": "bottle", "slot_id": slot_id},
                    ),
                    (
                        "consumable.collector-collect-to-staging-a",
                        {"slot_id": slot_id},
                    ),
                    (
                        "consumable.bottle-collect-to-staging-b",
                        {"rack_id": "bottle", "slot_id": slot_id},
                    ),
                ]
            )
        return cases

    def test_exactly_fourteen_business_routes(self) -> None:
        self.assertEqual(len(self.planner.route_ids), 14)
        self.assertFalse(any(route.startswith("test.") for route in self.planner.route_ids))

    def test_every_legal_combination_resolves_deterministically(self) -> None:
        cases = self.legal_cases()
        self.assertEqual(len(cases), 68)
        for route_id, params in cases:
            with self.subTest(route_id=route_id, params=params):
                first = self.planner.resolve(route_id, params)
                second = self.planner.resolve(route_id, params)
                self.assertEqual(first, second)
                self.assertTrue(first.steps)
                self.assertEqual(first.robot_lock_scope, "transaction")
                robot_steps = [
                    step for step in first.steps if isinstance(step, RobotRouteStep)
                ]
                self.assertTrue(robot_steps)
                for route_step in robot_steps:
                    self.assertTrue(route_step.plan.resolved_points)
                    for move in route_step.plan.flow.steps:
                        if hasattr(move, "point"):
                            point = self.catalog.registry.get(move.point)
                            self.assertEqual(point.status, "validated")
                            self.assertIn(move.motion, point.allowed_motion)

    def test_tank_groups_preserve_mechanical_split(self) -> None:
        for tank_id in range(1, 9):
            plan = self.catalog.resolve("tank.put", {"tank_id": tank_id})
            expected = "tank-a" if tank_id <= 4 else "tank-b"
            self.assertEqual(plan.route_group, expected)
            ids = [step.step_id for step in plan.flow.steps]
            if tank_id <= 4:
                self.assertIn("enter-tank-outer", ids)
                self.assertIn("enter-tank-inner", ids)
            else:
                self.assertNotIn("enter-tank-outer", ids)
                self.assertNotIn("enter-tank-inner", ids)

    def test_illegal_ids_and_wrong_rack_group_reject(self) -> None:
        for tank_id in (0, 9):
            with self.assertRaises(RobotRouteError):
                self.planner.resolve("plate.scrape-to-tank", {"tank_id": tank_id})
        for slot_id in (0, 7):
            with self.assertRaises(RobotRouteError):
                self.planner.resolve(
                    "consumable.bottle-staging-b-to-collect",
                    {"rack_id": "bottle", "slot_id": slot_id},
                )
        with self.assertRaises(RobotRouteError):
            self.planner.resolve(
                "consumable.bottle-staging-b-to-collect",
                {"rack_id": "collector", "slot_id": 1},
            )

    def test_plc_conditions_are_host_steps_not_fixed_waits(self) -> None:
        for route_id, params in self.legal_cases():
            plan = self.planner.resolve(route_id, params)
            for step in plan.steps:
                if isinstance(step, PlcWaitStep):
                    self.assertTrue(step.condition)
                    self.assertGreater(step.timeout_s, 0)
                    self.assertGreater(step.poll_interval_s, 0)
            for robot_step in (
                step for step in plan.steps if isinstance(step, RobotRouteStep)
            ):
                self.assertFalse(
                    any(
                        token in type(inner).__name__.lower()
                        for inner in robot_step.plan.flow.steps
                        for token in ("plc", "camera")
                    )
                )

    def test_every_robot_flow_runs_at_its_required_rail_position(self) -> None:
        """全链路不变式: 每个机器人步骤执行前, 地轨已停在该工位所需位置。"""
        for route_id, params in self.legal_cases():
            with self.subTest(route_id=route_id, params=params):
                plan = self.planner.resolve(route_id, params)
                current_code: int | None = None
                rail_count = 0
                for step in plan.steps:
                    if isinstance(step, RailMoveStep):
                        # 不允许冗余地轨移动 (同位置重复下发)
                        self.assertNotEqual(step.position_code, current_code)
                        current_code = step.position_code
                        rail_count += 1
                    elif isinstance(step, RobotRouteStep):
                        required = self.catalog.rail_stations[step.plan.route_group]
                        self.assertEqual(
                            current_code,
                            required,
                            f"{route_id}/{step.step_id} ran at rail {current_code}, "
                            f"needs {required}",
                        )
                self.assertGreaterEqual(rail_count, 1)

    def test_rail_safety_rejects_move_when_arm_not_home(self) -> None:
        """臂未回 home 时若地轨需移动, 必须 load 期 fail-stop。"""
        bad = RouteDefinition(
            route_id="x.bad-rail-safety",
            description="",
            params=(),
            resources=(),
            robot_lock_scope="transaction",
            steps=(
                # put-enter 停在 target (exit_role=target), 地轨=刮板(2)
                {
                    "id": "enter",
                    "type": "robot_flow",
                    "template": "scrape.holder.put-enter",
                    "params": {"station_id": {"value": "default"}},
                },
                # 直接跳到 tank (地轨=展开缸 5), 臂还在 target -> 非法
                {
                    "id": "to-tank",
                    "type": "robot_flow",
                    "template": "tank.put",
                    "params": {"tank_id": {"value": 1}},
                },
            ),
        )
        planner = RoutePlanner(
            self.catalog,
            {"x.bad-rail-safety": bad},
            config_version="x",
            config_sha256="x",
        )
        with self.assertRaises(RobotRouteError):
            planner.resolve("x.bad-rail-safety", {})

    def test_camera_actions_are_independent_host_steps(self) -> None:
        routes = (
            "plate.feed-to-spotting",
            "plate.spotting-to-scrape",
            "plate.tank-to-scrape",
        )
        params = ({}, {}, {"tank_id": 1})
        for route_id, values in zip(routes, params):
            plan = self.planner.resolve(route_id, values)
            self.assertTrue(any(isinstance(step, CameraActionStep) for step in plan.steps))


if __name__ == "__main__":
    unittest.main(verbosity=2)
