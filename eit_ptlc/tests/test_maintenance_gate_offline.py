"""Shared PLC-deploy maintenance gate tests (no hardware or IDE)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.action.executor import ActionExecutor
from eit_ptlc.action.models import ActionStatus, RejectCode
from eit_ptlc.action.registry import ActionDef, ActionRegistry
from eit_ptlc.api.vm_routes import register_vm_routes
from eit_ptlc.controller.point_registry import PointRegistry
from eit_ptlc.controller.robot_controller import RobotController
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.controller import VmController
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError, MaintenanceGate
from eit_ptlc.tests.test_robot_controller_offline import _RecordingTransport


class _Robot:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def query(self):
        self.calls.append("query")

    def stop(self):
        self.calls.append("stop")

    def emergency_stop(self):
        self.calls.append("emergency_stop")

    def jog_stop(self):
        self.calls.append("jog_stop")

    def disable_robot(self):
        self.calls.append("disable_robot")


def _leased_gate() -> MaintenanceGate:
    gate = MaintenanceGate()
    assert gate.try_acquire("test deploy") is not None
    return gate


def test_persistent_latch_survives_process_reconstruction(tmp_path) -> None:
    path = tmp_path / "plc-deploy-maintenance.json"
    first = MaintenanceGate(path)
    assert first.try_acquire("deploy in progress") is not None
    assert path.exists()

    restarted = MaintenanceGate(path)
    assert restarted.active is True
    assert restarted.try_enter_activity("new action") is None
    restarted.release_after_reconcile()
    assert restarted.active is False
    assert not path.exists()


def test_action_executor_rejects_new_actions_but_allows_risk_reduction() -> None:
    actions = {
        name: ActionDef(name=name, kind="robot", method=method,
                        modes=("DEBUG",) if method in {"jog_stop", "disable_robot"} else ())
        for name, method in {
            "robot.query": "query",
            "robot.stop": "stop",
            "robot.estop": "emergency_stop",
            "robot.jog_stop": "jog_stop",
            "robot.disable": "disable_robot",
        }.items()
    }
    robot = _Robot()
    executor = ActionExecutor(
        ActionRegistry(actions), robot=robot, maintenance_gate=_leased_gate(),
    )

    rejected = asyncio.run(executor.execute("robot.query"))
    assert rejected.status is ActionStatus.REJECTED
    assert rejected.reject_code == RejectCode.RESOURCE_CONFLICT.value
    assert robot.calls == []

    for name in ("robot.stop", "robot.estop", "robot.jog_stop", "robot.disable"):
        result = asyncio.run(executor.execute(name, current_mode="RUN"))
        assert result.status is ActionStatus.DONE
    assert robot.calls == ["stop", "emergency_stop", "jog_stop", "disable_robot"]


def test_action_activity_and_maintenance_acquisition_are_atomic() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _BlockingRobot:
        def query(self):
            entered.set()
            assert release.wait(2.0)

    gate = MaintenanceGate()
    executor = ActionExecutor(
        ActionRegistry({
            "robot.query": ActionDef(name="robot.query", kind="robot", method="query"),
        }),
        robot=_BlockingRobot(), maintenance_gate=gate,
    )

    async def run():
        task = asyncio.create_task(executor.execute("robot.query"))
        assert await asyncio.to_thread(entered.wait, 1.0)
        snap = gate.snapshot()
        assert snap["activity_count"] == 1
        assert gate.try_acquire("deploy") is None
        release.set()
        result = await task
        assert result.status is ActionStatus.DONE
        lease = gate.try_acquire("deploy")
        assert lease is not None
        gate.release(lease)

    asyncio.run(run())


def test_vm_refuses_to_allocate_a_run_while_maintenance_is_active() -> None:
    gate = _leased_gate()
    vm = VmController(
        executor=object(), res_gate=ResourceGate(), maintenance_gate=gate,
    )
    doc = {"schema": "ptlc.script/v1", "kind": "operation", "name": "noop", "body": []}

    with pytest.raises(MaintenanceActiveError):
        asyncio.run(vm.start(doc))
    assert vm.active() == {"runs": []}


def test_vm_lifetime_blocks_maintenance_between_leaf_actions() -> None:
    gate = MaintenanceGate()
    entered = asyncio.Event()
    release = asyncio.Event()

    class _Thread:
        async def run(self, _inputs):
            entered.set()
            await release.wait()

    class _Request:
        recipe = "blocking"
        sample_id = "S1"
        params = {}

    vm = VmController(
        executor=object(), res_gate=ResourceGate(), maintenance_gate=gate,
        resolve_script=lambda _name: {"name": "blocking"},
    )
    vm._new_thread = lambda *_args, **_kwargs: _Thread()

    async def run():
        task = asyncio.create_task(vm.run_sample(_Request()))
        await asyncio.wait_for(entered.wait(), 1.0)
        assert gate.snapshot()["activity_count"] == 1
        assert gate.try_acquire("deploy") is None
        release.set()
        await task
        assert gate.snapshot()["activity_count"] == 0

    asyncio.run(run())


def test_vm_http_start_maps_maintenance_rejection_to_conflict() -> None:
    gate = _leased_gate()
    vm = VmController(executor=object(), res_gate=ResourceGate(), maintenance_gate=gate)
    doc = {"schema": "ptlc.script/v1", "kind": "operation", "name": "noop", "body": []}

    class _Repo:
        def get(self, _ws, _name):
            return doc

    app = FastAPI()
    app.state.vm = vm
    app.state.script_repo = _Repo()
    register_vm_routes(app)
    with TestClient(app) as client:
        response = client.post("/api/scripts/noop/debug/run", json={})
    assert response.status_code == 409
    assert "PLC 下载维护态" in response.json()["detail"]


# 原先这里有两个 test_manual_calibration_* —— 覆盖孔板标定「去使能手推」enter/exit 的
# ActivityLease 语义。那对端点已于 2026-07 删除 (PLC 侧是自毁循环, 见
# controller/calibration_service.py 模块 docstring), 标定改走 PC 单点会话,
# 同一组租约语义 (维护态拒绝进入 / 会话激活时维护门抢不到) 由
# tests/test_manual_control_offline.py 的「维护门与单点会话互斥」段落覆盖。


def test_robot_controller_blocks_direct_motion_bypass_and_keeps_stops_available() -> None:
    cfg = Path(__file__).resolve().parent.parent / "config" / "points" / "robot"
    registry = PointRegistry.load(
        cfg / "robot_points.json", source_version="v0.11",
        meta_path=cfg / "robot_points_meta.json",
    )
    transport = _RecordingTransport()
    gate = _leased_gate()
    robot = RobotController(
        transport, registry, home_point="robot-main.home", maintenance_gate=gate,
    )

    with pytest.raises(MaintenanceActiveError):
        robot.move_j("robot-main.home")
    with pytest.raises(MaintenanceActiveError):
        robot.jog_start("X+")
    with pytest.raises(MaintenanceActiveError):
        robot.enable_robot(confirm=True)
    assert transport.calls == []

    robot.stop()
    robot.jog_stop()
    robot.emergency_stop()
    robot.disable_robot(confirm=True)
    assert transport.calls == [
        ("stop",), ("jog_stop",), ("emergency_stop", True),
        ("disable_robot", True),
    ]


def test_robot_serialized_wait_holds_activity_before_action_lock() -> None:
    cfg = Path(__file__).resolve().parent.parent / "config" / "points" / "robot"
    registry = PointRegistry.load(
        cfg / "robot_points.json", source_version="v0.11",
        meta_path=cfg / "robot_points_meta.json",
    )
    gate = MaintenanceGate()
    transport = _RecordingTransport()
    robot = RobotController(
        transport, registry, home_point="robot-main.home", maintenance_gate=gate,
    )

    robot._action_lock.acquire()
    errors: list[BaseException] = []

    def move():
        try:
            robot.move_j("robot-main.home")
        except BaseException as exc:  # surfaced in the test thread
            errors.append(exc)

    thread = threading.Thread(target=move)
    thread.start()
    deadline = time.monotonic() + 1.0
    while gate.snapshot()["activity_count"] != 1 and time.monotonic() < deadline:
        time.sleep(0.001)
    try:
        assert gate.snapshot()["activity_count"] == 1
        # Old check-then-lock code allowed this acquisition and then moved afterward.
        assert gate.try_acquire("deploy") is None
    finally:
        robot._action_lock.release()
        thread.join(1.0)
    assert not errors
    assert not thread.is_alive()
    assert transport.calls[-1][0] == "move_j"


def test_continuous_jog_keeps_activity_until_successful_stop() -> None:
    cfg = Path(__file__).resolve().parent.parent / "config" / "points" / "robot"
    registry = PointRegistry.load(
        cfg / "robot_points.json", source_version="v0.11",
        meta_path=cfg / "robot_points_meta.json",
    )
    gate = MaintenanceGate()
    transport = _RecordingTransport()
    robot = RobotController(
        transport, registry, home_point="robot-main.home", maintenance_gate=gate,
    )

    robot.jog_start("X+")
    assert gate.snapshot()["activity_count"] == 1
    assert gate.try_acquire("deploy") is None
    robot.jog_stop()
    assert gate.snapshot()["activity_count"] == 0
