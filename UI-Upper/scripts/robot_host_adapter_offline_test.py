#!/usr/bin/env python3
"""Offline checks for real PLC/camera semantic bindings."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.point_registry import PointRegistry  # noqa: E402
from core.robot_host_adapter import (  # noqa: E402
    HostActionCatalog,
    HostActionConfigError,
    ThreadsafePlcCameraHost,
)
from core.robot_plan import RobotPlanCatalog  # noqa: E402
from core.robot_route import RoutePlanner  # noqa: E402


class FakePLC:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}
        self.writes: list[tuple[str, object, object]] = []

    async def read_variable(self, name: str) -> object:
        return self.values.get(name, False)

    async def write_variable_dynamic(
        self,
        name: str,
        value: object,
        variant: object,
    ) -> None:
        self.values[name] = value
        self.writes.append((name, value, variant))


class FakeCamera:
    async def capture(
        self,
        sample_id: str,
        save_dir: Path,
        *,
        filename: str,
    ) -> Path:
        save_dir.mkdir(parents=True, exist_ok=True)
        result = save_dir / filename
        result.write_bytes(b"offline-camera")
        return result


class HostActionCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        sources = list(UI_ROOT.parent.glob("*/**/roboprogram/point.json"))
        registry = PointRegistry.load(
            sources[0],
            source_version="v0.11",
            meta_path=UI_ROOT / "config" / "robot_points_meta.json",
        )
        flow_source = UI_ROOT / "config" / "robot_flows_v2.yaml"
        catalog = RobotPlanCatalog.load(flow_source, registry)
        self.planner = RoutePlanner.load(flow_source, catalog)
        self.host_catalog = HostActionCatalog.load(
            UI_ROOT / "config" / "robot_host_actions.json"
        )

    def test_all_route_semantics_have_explicit_bindings(self) -> None:
        self.host_catalog.validate_routes(self.planner)
        self.assertTrue(self.host_catalog.source_sha256)

    def test_missing_binding_fails_startup_validation(self) -> None:
        incomplete = HostActionCatalog(
            plc_actions={},
            plc_conditions=self.host_catalog.plc_conditions,
            camera_actions=self.host_catalog.camera_actions,
            source_sha256="test",
        )
        with self.assertRaises(HostActionConfigError):
            incomplete.validate_routes(self.planner)


class ThreadsafeHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.plc = FakePLC()
        self.camera = FakeCamera()
        self.catalog = HostActionCatalog.load(
            UI_ROOT / "config" / "robot_host_actions.json"
        )
        self.host = ThreadsafePlcCameraHost(
            loop=asyncio.get_running_loop(),
            plc=self.plc,  # type: ignore[arg-type]
            camera=self.camera,  # type: ignore[arg-type]
            catalog=self.catalog,
            sample_id="sample-001",
            save_dir=self.temp.name,
        )

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_plc_action_writes_and_verifies_real_variable(self) -> None:
        result = await asyncio.to_thread(
            self.host.plc_action,
            "feed-lift.raise",
            {},
        )
        self.assertEqual(result["verified"], True)
        self.assertEqual(len(self.plc.writes), 1)
        self.assertEqual(
            self.plc.writes[0][0],
            self.catalog.plc_actions["feed-lift.raise"].variable,
        )

    async def test_parameterized_tank_selection_uses_int16_value(self) -> None:
        result = await asyncio.to_thread(
            self.host.plc_action,
            "tank.select",
            {"tank_id": 8},
        )
        self.assertEqual(result["value"], 8)
        self.assertEqual(self.plc.values["Expand_Target_Tank"], 8)

    async def test_stale_true_handshake_is_rejected_before_write(self) -> None:
        variable = self.catalog.plc_actions[
            "scrape.confirm-plate-loaded"
        ].variable
        self.plc.values[variable] = True
        with self.assertRaises(RuntimeError):
            await asyncio.to_thread(
                self.host.plc_action,
                "scrape.confirm-plate-loaded",
                {},
            )
        self.assertEqual(self.plc.writes, [])

    async def test_condition_reads_actual_plc_value(self) -> None:
        variable = self.catalog.plc_conditions["tank.receive-ready"].variable
        self.plc.values[variable] = False
        self.assertFalse(await asyncio.to_thread(
            self.host.plc_condition, "tank.receive-ready", {"tank_id": 1}
        ))
        self.plc.values[variable] = True
        self.assertTrue(await asyncio.to_thread(
            self.host.plc_condition, "tank.receive-ready", {"tank_id": 1}
        ))

    async def test_camera_action_returns_raw_file_metadata(self) -> None:
        result = await asyncio.to_thread(
            self.host.camera_action,
            "plate.capture-after-develop",
            {},
        )
        self.assertEqual(result["sample_id"], "sample-001")
        self.assertEqual(result["size"], len(b"offline-camera"))
        self.assertTrue(Path(result["path"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
