"""PLC 完整下载安全握手与结果语义离线测试（不启动 IDE、不连接真机）。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.plc_program_routes import register_plc_program_routes
from eit_ptlc.controller.plc_controller import (
    PLCDeployRejected,
    PLCDeployState,
    PLCStartupFailed,
    PlcController,
)
from eit_ptlc.controller.plc_program_service import (
    PLCDeployMaintenanceRecoveryRequired,
    PLCDeployOutcomeUnknown,
    PLCDeployPreparationTimeout,
    PLCDeployPreconditionError,
    PlcProgramService,
)
from eit_ptlc.runtime.maintenance_gate import MaintenanceGate


class FakeIpc:
    def __init__(self, *, compile_result=None, deploy_result=None) -> None:
        self.calls: list[tuple[str, dict, float]] = []
        self.target_plc_ip = "192.0.2.55"
        self.worker_body_sha256 = "b" * 64
        self._project_sha = "a" * 64
        self._guard_token: str | None = None
        self._guard_purpose: str | None = None
        self._guard_state: str | None = None
        self._physical_lock: dict = {}
        self.compile_result = compile_result or {
            "error_count": 0, "warning_count": 0, "errors": [], "warnings": [],
        }
        self.deploy_result = deploy_result or {
            "deployed": True, "started": True, "error_count": 0,
        }

    async def call(self, op, args=None, timeout=60.0, *, guard_token=None):
        self.calls.append((op, args or {}, timeout))
        if op == "compile":
            result = self.compile_result
        elif op == "save":
            result = {"saved": True}
        else:
            result = self.deploy_result
        if isinstance(result, Exception):
            raise result
        return result

    def project_sha256(self) -> str:
        return self._project_sha

    def begin_deploy_guard(self, *, purpose="deploy", timeout=5.0) -> str:
        if self._guard_token is not None:
            raise RuntimeError("deploy guard already active")
        self._guard_token = f"fake-{purpose}-guard"
        self._guard_purpose = purpose
        self._guard_state = "active"
        return self._guard_token

    def end_deploy_guard(self, token: str) -> None:
        if token != self._guard_token:
            raise RuntimeError("deploy guard token mismatch")
        self._guard_token = None
        self._guard_purpose = None
        self._guard_state = None

    def deploy_guard_snapshot(self) -> dict:
        if self._guard_token is None:
            return {}
        return {"state": self._guard_state, "token": self._guard_token,
                "purpose": self._guard_purpose,
                "project": "fake-project", "plc_ip": self.target_plc_ip,
                "protocol_version": 3,
                "worker_body_sha256": self.worker_body_sha256}

    def physical_deploy_lock_snapshot(self) -> dict:
        return dict(self._physical_lock)

    def force_clear_deploy_guard(
        self, *, reason: str, expected_token: str, expected_purpose: str,
        expected_state: str,
        expected_project: str, expected_plc_ip: str,
        expected_protocol_version: int, expected_worker_body_sha256: str | None,
    ) -> dict:
        if (expected_token != self._guard_token
                or expected_purpose != self._guard_purpose
                or expected_state != self._guard_state
                or expected_state not in {"active", "releasing"}):
            raise RuntimeError("deploy guard changed before reconciliation")
        previous = ({"token": self._guard_token, "purpose": self._guard_purpose,
                     "reason": reason}
                    if self._guard_token is not None else {})
        self._guard_token = None
        self._guard_purpose = None
        self._guard_state = None
        self._physical_lock = {}
        return previous

    def force_clear_orphan_physical_lock(
        self, *, reason: str, expected_owner_token: str,
    ) -> dict:
        if self._physical_lock.get("owner_token") != expected_owner_token:
            raise RuntimeError("physical deploy lock changed before reconciliation")
        previous = dict(self._physical_lock)
        self._physical_lock = {}
        return previous

    async def authorized_deploy(
        self, *, expected_sha256, commit_seq, expected_plc_ip, guard_token,
        timeout=300.0,
    ):
        assert guard_token == self._guard_token
        args = {
            "expected_sha256": expected_sha256,
            "commit_seq": commit_seq,
            "expected_plc_ip": expected_plc_ip,
        }
        # Route through ``call`` so timing/error subclasses used below still
        # control the physical-deploy boundary exactly as the old fake did.
        result = await self.call(
            "deploy", args, timeout, guard_token=guard_token)
        result = dict(result)
        if result.get("deployed") is True:
            result.setdefault("authorization_valid", True)
            result.setdefault("project_sha256", expected_sha256)
            result.setdefault("target_ip", expected_plc_ip)
            result.setdefault("target_verified", True)
            result.setdefault("commit_seq", commit_seq)
            result.setdefault("worker_body_sha256", self.worker_body_sha256)
            result.setdefault("physical_lock_released", True)
        return result


class FakePlc:
    def __init__(self) -> None:
        self.reset_calls = 0
        self.prepare_calls = 0
        self.wait_calls = 0
        self.confirm_calls = 0
        self.commit_calls = 0
        self.reset_error: Exception | None = None
        self.prepare_error: Exception | None = None
        self.wait_error: Exception | None = None
        self.confirm_error: Exception | None = None
        self.commit_error: Exception | None = None
        self.startup_values = {"State": 60, "ErrorCode": 0, "Ready": True}
        self.deploy_values = {"State": 0, "AcceptedSeq": 0, "CommitSeq": 0, "ErrorCode": 0}

    async def reset_deploy(self, **_kwargs) -> None:
        self.reset_calls += 1
        if self.reset_error is not None:
            raise self.reset_error

    async def prepare_for_deploy(self, **_kwargs):
        self.prepare_calls += 1
        if self.prepare_error is not None:
            raise self.prepare_error
        return {"state": 20, "accepted_seq": 7, "error_code": 0, "request_seq": 7}

    async def commit_deploy(self, request_seq: int, **_kwargs):
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error
        return {"state": 25, "accepted_seq": request_seq, "commit_seq": request_seq,
                "error_code": 0, "request_seq": request_seq}

    async def confirm_deploy_committed(self, request_seq: int):
        self.confirm_calls += 1
        if self.confirm_error is not None:
            raise self.confirm_error
        return {"state": 25, "accepted_seq": request_seq, "commit_seq": request_seq,
                "error_code": 0, "request_seq": request_seq, "start": True}

    async def wait_startup_ready(self, **_kwargs):
        self.wait_calls += 1
        if self.wait_error is not None:
            raise self.wait_error
        callback = _kwargs.get("progress_callback")
        if callback is not None:
            callback("ready", {"State": 60, "ErrorCode": 0, "Ready": True})
        return {"State": 60, "ErrorCode": 0, "Ready": True}

    async def startup_snapshot(self):
        return dict(self.startup_values)

    async def deploy_snapshot(self):
        return dict(self.deploy_values)


class FakeDeployDriver:
    """直接测试 PlcController 系统节点协议的内存驱动。"""

    def __init__(self, *, reject=False) -> None:
        self.reject = reject
        self.values = {
            "PLC_Deploy_RequestSeq": 0,
            "PLC_Deploy_Start": False,
            "PLC_Deploy_Reset": False,
            "PLC_Deploy_State": 0,
            "PLC_Deploy_AcceptedSeq": 0,
            "PLC_Deploy_CommitSeq": 0,
            "PLC_Deploy_ErrorCode": 0,
            "PLC_Startup_State": 60,
            "PLC_Startup_ErrorCode": 0,
            "PLC_Ready": True,
        }
        self.writes: list[tuple[str, object]] = []

    async def read_many(self, names):
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name):
        return self.values[name]

    async def write_variable(self, name, value):
        self.writes.append((name, value))
        self.values[name] = value
        if name == "PLC_Deploy_Reset" and value:
            self.values["PLC_Deploy_State"] = 0
            self.values["PLC_Deploy_ErrorCode"] = 0
        if name == "PLC_Deploy_Start" and value:
            self.values["PLC_Deploy_AcceptedSeq"] = self.values["PLC_Deploy_RequestSeq"]
            self.values["PLC_Deploy_State"] = 30 if self.reject else 20
            self.values["PLC_Deploy_ErrorCode"] = 701 if self.reject else 0
        if (name == "PLC_Deploy_CommitSeq" and value
                and value == self.values["PLC_Deploy_AcceptedSeq"]
                and self.values["PLC_Deploy_State"] == 20):
            self.values["PLC_Deploy_State"] = 25


def test_plc_controller_prepare_reset_and_wait_ready() -> None:
    async def run():
        driver = FakeDeployDriver()
        plc = PlcController(driver, poll_interval=0.001)
        await plc.reset_deploy(pulse_s=0, timeout=0.1)
        prepared = await plc.prepare_for_deploy(timeout=0.1)
        committed = await plc.commit_deploy(prepared["request_seq"], timeout=0.1)
        confirmed = await plc.confirm_deploy_committed(prepared["request_seq"])
        startup = await plc.wait_startup_ready(timeout=0.1)
        return driver, prepared, committed, confirmed, startup

    driver, prepared, committed, confirmed, startup = asyncio.run(run())
    assert prepared == {"state": 20, "accepted_seq": 1, "error_code": 0, "request_seq": 1}
    assert startup["Ready"] is True
    assert driver.values["PLC_Deploy_Start"] is True
    assert committed["state"] == 25
    assert confirmed["start"] is True


def test_plc_controller_startup_progress_callback_maps_real_states() -> None:
    async def run(states):
        plc = PlcController(FakeDeployDriver(), poll_interval=0)
        snapshots = iter(states)

        async def startup_snapshot():
            return next(snapshots)

        plc.startup_snapshot = startup_snapshot  # type: ignore[method-assign]
        phases: list[str] = []
        result = await plc.wait_startup_ready(
            timeout=0.1,
            progress_callback=lambda phase, _snapshot: phases.append(phase),
        )
        return phases, result

    phases, result = asyncio.run(run([
        {"State": 10, "ErrorCode": 0, "Ready": False},
        {"State": 40, "ErrorCode": 0, "Ready": False},
        {"State": 41, "ErrorCode": 0, "Ready": False},
        {"State": 50, "ErrorCode": 0, "Ready": False},
        {"State": 51, "ErrorCode": 0, "Ready": False},
        {"State": 60, "ErrorCode": 0, "Ready": True},
        {"State": 60, "ErrorCode": 0, "Ready": True},
    ]))
    assert phases == ["reconnect", "home_5z", "home_4x", "ready"]
    assert result["Ready"] is True


def test_plc_controller_startup_progress_reports_state90_failure() -> None:
    async def run():
        plc = PlcController(FakeDeployDriver(), poll_interval=0)
        snapshots = iter([
            {"State": 40, "ErrorCode": 0, "Ready": False},
            {"State": 90, "ErrorCode": 941, "Ready": False},
        ])

        async def startup_snapshot():
            return next(snapshots)

        plc.startup_snapshot = startup_snapshot  # type: ignore[method-assign]
        phases: list[str] = []
        with pytest.raises(PLCStartupFailed):
            await plc.wait_startup_ready(
                timeout=0.1,
                progress_callback=lambda phase, _snapshot: phases.append(phase),
            )
        return phases

    assert asyncio.run(run()) == ["home_5z", "failed"]


def test_plc_controller_prepare_rejection_is_explicit() -> None:
    async def run():
        plc = PlcController(FakeDeployDriver(reject=True), poll_interval=0.001)
        await plc.prepare_for_deploy(timeout=0.1)

    with pytest.raises(PLCDeployRejected) as caught:
        asyncio.run(run())
    assert caught.value.state is PLCDeployState.REJECTED
    assert caught.value.error_code == 701
    assert caught.value.request_seq == 1


def test_plc_controller_confirmation_rejects_lost_commit_ownership() -> None:
    async def run():
        driver = FakeDeployDriver()
        plc = PlcController(driver, poll_interval=0.001)
        prepared = await plc.prepare_for_deploy(timeout=0.1)
        await plc.commit_deploy(prepared["request_seq"], timeout=0.1)
        driver.values["PLC_Deploy_CommitSeq"] = 0  # simulate illegal external mutation
        await plc.confirm_deploy_committed(prepared["request_seq"])

    with pytest.raises(RuntimeError, match="提交所有权已变化"):
        asyncio.run(run())


def test_plc_controller_confirmation_rejects_committed_invariant_error() -> None:
    async def run():
        driver = FakeDeployDriver()
        plc = PlcController(driver, poll_interval=0.001)
        prepared = await plc.prepare_for_deploy(timeout=0.1)
        await plc.commit_deploy(prepared["request_seq"], timeout=0.1)
        # PLC keeps State=25 and power disabled, but latches the lost safe-state
        # invariant so the worker must not begin login/download.
        driver.values["PLC_Deploy_ErrorCode"] = 41
        await plc.confirm_deploy_committed(prepared["request_seq"])

    with pytest.raises(RuntimeError, match="提交所有权已变化"):
        asyncio.run(run())


def test_compile_error_blocks_worker_deploy() -> None:
    ipc = FakeIpc(compile_result={"error_count": 2, "errors": [{"text": "bad"}]})
    plc = FakePlc()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc)

    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(svc.deploy())

    assert caught.value.stage == "compile_failed"
    assert [op for op, _, _ in ipc.calls] == ["compile"]
    assert plc.prepare_calls == 0
    progress = svc.deploy_status()
    assert progress["phase"] == "compile"
    assert progress["status"] == "error"
    assert progress["downloaded"] is False
    assert progress["retryable"] is True


def test_busy_guard_blocks_before_handshake_and_worker_deploy() -> None:
    async def busy_guard():
        raise PLCDeployPreconditionError("VM still active", stage="busy")

    ipc = FakeIpc()
    plc = FakePlc()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc, idle_guard=busy_guard)

    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(svc.deploy())

    assert caught.value.stage == "busy"
    assert [op for op, _, _ in ipc.calls] == ["compile", "save"]
    assert plc.prepare_calls == 0


def test_registered_activity_atomically_blocks_maintenance_acquisition() -> None:
    gate = MaintenanceGate()
    activity = gate.try_enter_activity("already accepted action")
    assert activity is not None
    ipc = FakeIpc()
    plc = FakePlc()
    svc = PlcProgramService(
        ipc, allow_deploy=True, plc=plc, maintenance_gate=gate,
    )

    try:
        with pytest.raises(PLCDeployPreconditionError) as caught:
            asyncio.run(svc.deploy())
        assert caught.value.stage == "busy"
        assert caught.value.details["activity_count"] == 1
        assert [op for op, _, _ in ipc.calls] == ["compile", "save"]
        assert plc.prepare_calls == 0
    finally:
        gate.leave_activity(activity)


def test_prepare_timeout_never_calls_worker_deploy_and_resets_handshake() -> None:
    ipc = FakeIpc()
    plc = FakePlc()
    plc.prepare_error = TimeoutError("prepare timeout")
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc)

    with pytest.raises(PLCDeployPreparationTimeout) as caught:
        asyncio.run(svc.deploy())

    assert [op for op, _, _ in ipc.calls] == ["compile", "save"]
    assert plc.reset_calls == 2  # 初始清场 + 失败恢复
    assert caught.value.payload()["downloaded"] is False
    assert caught.value.payload()["result_uncertain"] is False


def test_legacy_firmware_without_handshake_nodes_fails_closed() -> None:
    ipc = FakeIpc()
    plc = FakePlc()
    plc.reset_error = KeyError("PLC_Deploy_State")
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc)

    with pytest.raises(PLCDeployMaintenanceRecoveryRequired) as caught:
        asyncio.run(svc.deploy())

    assert caught.value.stage == "maintenance_recovery_required"
    assert caught.value.payload()["downloaded"] is False
    assert caught.value.payload()["retryable"] is False
    assert caught.value.payload()["maintenance_recovery_required"] is True
    assert svc.maintenance_snapshot()["active"] is True
    assert [op for op, _, _ in ipc.calls] == ["compile", "save"]


def test_success_waits_for_startup_ready_and_normalizes_result() -> None:
    ipc = FakeIpc()
    plc = FakePlc()
    gate = MaintenanceGate()
    guard_observations: list[bool] = []

    async def idle_guard():
        guard_observations.append(gate.active)

    svc = PlcProgramService(
        ipc, allow_deploy=True, plc=plc,
        idle_guard=idle_guard, maintenance_gate=gate,
    )

    result = asyncio.run(svc.deploy())

    assert [op for op, _, _ in ipc.calls] == ["compile", "save", "deploy"]
    assert result["downloaded"] is True
    assert result["ready"] is True
    assert result["retryable"] is False
    assert result["result_uncertain"] is False
    assert result["stage"] == "ready"
    assert result["startup_state"] == 60
    assert plc.wait_calls == 1
    assert plc.confirm_calls == 1
    assert plc.commit_calls == 1
    assert guard_observations == [True, True]
    assert svc.maintenance_snapshot()["active"] is False


def test_deploy_progress_is_live_memory_and_tracks_all_real_phases() -> None:
    async def run():
        class StagedIpc(FakeIpc):
            def __init__(self):
                super().__init__()
                self.compile_enter = asyncio.Event()
                self.compile_release = asyncio.Event()
                self.deploy_enter = asyncio.Event()
                self.deploy_release = asyncio.Event()

            async def call(self, op, args=None, timeout=60.0, *, guard_token=None):
                self.calls.append((op, args or {}, timeout))
                if op == "compile":
                    self.compile_enter.set()
                    await self.compile_release.wait()
                    return self.compile_result
                if op == "save":
                    return {"saved": True}
                if op == "deploy":
                    self.deploy_enter.set()
                    await self.deploy_release.wait()
                    return self.deploy_result
                raise AssertionError(f"unexpected worker op: {op}")

        class StagedPlc(FakePlc):
            def __init__(self):
                super().__init__()
                self.prepare_enter = asyncio.Event()
                self.prepare_release = asyncio.Event()
                self.startup_enter = asyncio.Event()
                self.go_5z = asyncio.Event()
                self.seen_5z = asyncio.Event()
                self.go_4x = asyncio.Event()
                self.seen_4x = asyncio.Event()
                self.go_ready = asyncio.Event()

            async def prepare_for_deploy(self, **_kwargs):
                self.prepare_calls += 1
                self.prepare_enter.set()
                await self.prepare_release.wait()
                return {"state": 20, "accepted_seq": 7, "error_code": 0,
                        "request_seq": 7}

            async def wait_startup_ready(self, **kwargs):
                self.wait_calls += 1
                callback = kwargs["progress_callback"]
                callback("reconnect", {"State": 10, "ErrorCode": 0, "Ready": False})
                self.startup_enter.set()
                await self.go_5z.wait()
                callback("home_5z", {"State": 41, "ErrorCode": 0, "Ready": False})
                self.seen_5z.set()
                await self.go_4x.wait()
                callback("home_4x", {"State": 51, "ErrorCode": 0, "Ready": False})
                self.seen_4x.set()
                await self.go_ready.wait()
                callback("ready", {"State": 60, "ErrorCode": 0, "Ready": True})
                return {"State": 60, "ErrorCode": 0, "Ready": True}

        ipc = StagedIpc()
        plc = StagedPlc()
        svc = PlcProgramService(ipc, allow_deploy=True, plc=plc)
        task = asyncio.create_task(svc.deploy())

        await ipc.compile_enter.wait()
        compile_status = svc.deploy_status()
        worker_calls = len(ipc.calls)
        assert svc.deploy_status()["revision"] == compile_status["revision"]
        assert len(ipc.calls) == worker_calls  # status reads are worker-free

        ipc.compile_release.set()
        await plc.prepare_enter.wait()
        prepare_status = svc.deploy_status()

        plc.prepare_release.set()
        await ipc.deploy_enter.wait()
        download_status = svc.deploy_status()

        ipc.deploy_release.set()
        await plc.startup_enter.wait()
        reconnect_status = svc.deploy_status()

        plc.go_5z.set()
        await plc.seen_5z.wait()
        home_5z_status = svc.deploy_status()

        plc.go_4x.set()
        await plc.seen_4x.wait()
        home_4x_status = svc.deploy_status()

        plc.go_ready.set()
        result = await task
        ready_status = svc.deploy_status()
        return (
            compile_status, prepare_status, download_status, reconnect_status,
            home_5z_status, home_4x_status, ready_status, result,
        )

    statuses = asyncio.run(run())
    assert [item["phase"] for item in statuses[:7]] == [
        "compile", "prepare", "download", "reconnect", "home_5z", "home_4x", "ready",
    ]
    assert statuses[0]["phase_states"] == [
        "running", "pending", "pending", "pending", "pending", "pending", "pending",
    ]
    assert statuses[2]["deploy_state"] == 25
    assert statuses[2]["commit_seq"] == 7
    assert statuses[2]["downloaded"] is None
    assert statuses[6]["phase_states"] == ["done"] * 7
    assert statuses[6]["status"] == "done"
    assert statuses[6]["active"] is False
    assert statuses[7]["ready"] is True


def test_project_mutations_cannot_interleave_with_deploy_handshake() -> None:
    """The compile/snapshot/handshake/download sequence owns one project-wide lock."""

    async def run() -> None:
        class BlockingPreparePlc(FakePlc):
            def __init__(self) -> None:
                super().__init__()
                self.entered = asyncio.Event()
                self.release = asyncio.Event()

            async def prepare_for_deploy(self, **_kwargs):
                self.prepare_calls += 1
                self.entered.set()
                await self.release.wait()
                return {"state": 20, "accepted_seq": 7, "error_code": 0,
                        "request_seq": 7}

        class RecordingRepo:
            def __init__(self) -> None:
                self.restore_calls: list[str] = []

            def snapshot_if_changed(self, **_kwargs):
                return None

            def current_sha256(self):
                return "a" * 64

            def mark_deployed(self, *, expected_sha256):
                assert expected_sha256 == "a" * 64
                return None

            def get_version(self, rev: str):
                self.restore_calls.append(f"get:{rev}")
                return {"rev": rev}

            def restore(self, rev: str):
                self.restore_calls.append(f"restore:{rev}")
                return {"rev": rev}

        ipc = FakeIpc()
        plc = BlockingPreparePlc()
        repo = RecordingRepo()
        svc = PlcProgramService(
            ipc, allow_deploy=True, plc=plc, version_repo=repo,
        )
        deploying = asyncio.create_task(svc.deploy())
        await plc.entered.wait()
        progress = svc.deploy_status()
        calls_before = list(ipc.calls)

        for mutation in (
            svc.save_pou("Application/Foo", None, "x:=1;", False),
            svc.set_symbol_export("Application/GVL", "Foo", True),
            svc.restore_version("0001"),
        ):
            with pytest.raises(PLCDeployPreconditionError) as caught:
                await mutation
            assert caught.value.stage == "busy"

        with pytest.raises(PLCDeployPreconditionError) as caught:
            await svc.deploy()
        assert caught.value.stage == "busy"
        assert svc.deploy_status()["revision"] == progress["revision"]
        assert svc.deploy_status()["attempt"] == progress["attempt"]
        assert ipc.calls == calls_before
        assert repo.restore_calls == []

        plc.release.set()
        result = await deploying
        assert result["ready"] is True

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    [PLCStartupFailed(state=90, error_code=902), TimeoutError("ready timeout")],
)
def test_downloaded_but_startup_failed_is_not_retryable(failure: Exception) -> None:
    ipc = FakeIpc()
    plc = FakePlc()
    plc.wait_error = failure
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc)

    result = asyncio.run(svc.deploy())

    assert result["downloaded"] is True
    assert result["ready"] is False
    assert result["retryable"] is False
    assert result["stage"] == "startup_failed"
    assert [op for op, _, _ in ipc.calls] == ["compile", "save", "deploy"]
    assert svc.maintenance_snapshot()["active"] is True
    progress = svc.deploy_status()
    assert progress["phase"] == "reconnect"
    assert progress["status"] == "error"
    assert progress["downloaded"] is True
    assert progress["retryable"] is False
    assert progress["result_uncertain"] is False


def test_worker_failure_after_deploy_call_is_outcome_unknown_and_not_retryable() -> None:
    ipc = FakeIpc(deploy_result=TimeoutError("worker timeout"))
    svc = PlcProgramService(ipc, allow_deploy=True, plc=FakePlc())

    with pytest.raises(PLCDeployOutcomeUnknown) as caught:
        asyncio.run(svc.deploy())

    assert caught.value.payload()["retryable"] is False
    assert caught.value.payload()["downloaded"] is None
    assert caught.value.payload()["result_uncertain"] is True
    assert [op for op, _, _ in ipc.calls] == ["compile", "save", "deploy"]
    assert svc.maintenance_snapshot()["active"] is True
    progress = svc.deploy_status()
    assert progress["phase"] == "download"
    assert progress["status"] == "error"
    assert progress["downloaded"] is None
    assert progress["retryable"] is False
    assert progress["result_uncertain"] is True


def test_prepare_revalidation_failure_blocks_worker_and_releases_gate() -> None:
    ipc = FakeIpc()
    plc = FakePlc()
    plc.confirm_error = RuntimeError("Start ownership lost")
    gate = MaintenanceGate()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=plc, maintenance_gate=gate)

    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(svc.deploy())

    assert caught.value.stage == "prepare_failed"
    assert [op for op, _, _ in ipc.calls] == ["compile", "save"]
    assert plc.confirm_calls == 1
    assert plc.reset_calls == 2
    assert gate.active is False


def test_prepare_failure_with_unconfirmed_reset_keeps_persistent_gate() -> None:
    class FailSecondResetPlc(FakePlc):
        async def reset_deploy(self, **_kwargs) -> None:
            self.reset_calls += 1
            if self.reset_calls >= 2:
                raise TimeoutError("reset acknowledgement lost")

    ipc = FakeIpc()
    plc = FailSecondResetPlc()
    plc.confirm_error = RuntimeError("commit invariant lost")
    gate = MaintenanceGate()
    svc = PlcProgramService(
        ipc, allow_deploy=True, plc=plc, maintenance_gate=gate,
    )

    with pytest.raises(PLCDeployMaintenanceRecoveryRequired) as caught:
        asyncio.run(svc.deploy())

    payload = caught.value.payload()
    assert payload["downloaded"] is False
    assert payload["retryable"] is False
    assert payload["maintenance_recovery_required"] is True
    assert [op for op, _, _ in ipc.calls] == ["compile", "save"]
    assert plc.reset_calls == 2
    assert gate.active is True


def test_worker_reports_not_downloaded_returns_409_semantics_and_releases_gate() -> None:
    ipc = FakeIpc(deploy_result={"deployed": False, "error_count": 1})
    plc = FakePlc()
    gate = MaintenanceGate()
    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(PlcProgramService(
            ipc, allow_deploy=True, plc=plc, maintenance_gate=gate,
        ).deploy())

    payload = caught.value.payload()
    assert payload["downloaded"] is False
    assert payload["retryable"] is True
    assert caught.value.stage == "download_blocked"
    assert plc.reset_calls == 2
    assert gate.active is False


def test_latched_unknown_outcome_blocks_a_second_download() -> None:
    gate = MaintenanceGate()
    svc = PlcProgramService(
        FakeIpc(deploy_result=TimeoutError("worker timeout")),
        allow_deploy=True, plc=FakePlc(), maintenance_gate=gate,
    )
    with pytest.raises(PLCDeployOutcomeUnknown):
        asyncio.run(svc.deploy())
    assert gate.active is True
    uncertain_progress = svc.deploy_status()

    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(svc.deploy())
    assert caught.value.stage == "maintenance_locked"
    after_rejected_retry = svc.deploy_status()
    assert after_rejected_retry["attempt"] == uncertain_progress["attempt"]
    assert after_rejected_retry["phase"] == "download"
    assert after_rejected_retry["result_uncertain"] is True


def test_read_only_reconcile_never_unlocks_state90_then_unlocks_proven_ready(tmp_path) -> None:
    latch = tmp_path / "deploy-latch.json"
    gate = MaintenanceGate(latch)
    assert gate.try_acquire("download uncertain") is not None
    plc = FakePlc()
    plc.startup_values = {"State": 90, "ErrorCode": 902, "Ready": False}
    svc = PlcProgramService(FakeIpc(), allow_deploy=True, plc=plc, maintenance_gate=gate)

    failed = asyncio.run(svc.reconcile_maintenance_latch())
    assert failed["released"] is False
    assert failed["safe_to_release"] is False
    assert gate.active is True
    assert latch.exists()

    plc.startup_values = {"State": 60, "ErrorCode": 0, "Ready": True}
    plc.deploy_values["State"] = 0
    awaiting_confirmation = asyncio.run(svc.reconcile_maintenance_latch())
    assert awaiting_confirmation["released"] is False
    assert awaiting_confirmation["operator_confirmation_required"] is True
    assert gate.active is True

    recovered = asyncio.run(svc.reconcile_maintenance_latch(
        operator_confirmed_online_version=True,
    ))
    assert recovered["released"] is True
    assert recovered["version_verified"] is False
    assert gate.active is False
    assert not latch.exists()


def test_read_only_reconcile_can_clear_orphan_deploy_guard_without_latch() -> None:
    ipc = FakeIpc()
    token = ipc.begin_deploy_guard(purpose="deploy")
    gate = MaintenanceGate()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=FakePlc(), maintenance_gate=gate)

    awaiting_confirmation = asyncio.run(svc.reconcile_maintenance_latch())
    assert awaiting_confirmation["released"] is False
    assert awaiting_confirmation["operator_confirmation_required"] is True
    assert ipc.deploy_guard_snapshot()["token"] == token

    recovered = asyncio.run(svc.reconcile_maintenance_latch(
        operator_confirmed_online_version=True,
    ))
    assert recovered["released"] is True
    assert recovered["deploy_guard_cleared"] is True
    assert ipc.deploy_guard_snapshot() == {}
    assert gate.active is False


def test_read_only_reconcile_can_finish_releasing_guard_after_crash() -> None:
    ipc = FakeIpc()
    token = ipc.begin_deploy_guard(purpose="deploy")
    ipc._guard_state = "releasing"
    ipc._physical_lock = {
        "owner_token": token,
        "pid": 999_999_999,
        "created_at": "2026-07-21T00:00:00Z",
    }
    gate = MaintenanceGate()
    assert gate.try_acquire("deploy release interrupted") is not None
    svc = PlcProgramService(ipc, allow_deploy=True, plc=FakePlc(), maintenance_gate=gate)

    awaiting_confirmation = asyncio.run(svc.reconcile_maintenance_latch())
    assert awaiting_confirmation["released"] is False
    assert awaiting_confirmation["operator_confirmation_required"] is True
    assert ipc.deploy_guard_snapshot()["state"] == "releasing"

    recovered = asyncio.run(svc.reconcile_maintenance_latch(
        operator_confirmed_online_version=True,
    ))
    assert recovered["released"] is True
    assert recovered["deploy_guard_cleared"] is True
    assert ipc.deploy_guard_snapshot() == {}
    assert ipc.physical_deploy_lock_snapshot() == {}
    assert gate.active is False


def test_read_only_reconcile_can_clear_dead_physical_only_orphan() -> None:
    ipc = FakeIpc()
    ipc._physical_lock = {
        "owner_token": "dead-physical-owner",
        "pid": 999_999_999,
        "created_at": "2026-07-21T00:00:00Z",
    }
    gate = MaintenanceGate()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=FakePlc(), maintenance_gate=gate)

    awaiting_confirmation = asyncio.run(svc.reconcile_maintenance_latch())
    assert awaiting_confirmation["released"] is False
    assert awaiting_confirmation["operator_confirmation_required"] is True
    assert ipc.physical_deploy_lock_snapshot()["owner_token"] == "dead-physical-owner"

    recovered = asyncio.run(svc.reconcile_maintenance_latch(
        operator_confirmed_online_version=True,
    ))
    assert recovered["released"] is True
    assert recovered["physical_deploy_lock_cleared"] is True
    assert ipc.physical_deploy_lock_snapshot() == {}
    assert gate.active is False


def test_read_only_reconcile_never_clears_restore_guard() -> None:
    ipc = FakeIpc()
    token = ipc.begin_deploy_guard(purpose="restore")
    gate = MaintenanceGate()
    svc = PlcProgramService(ipc, allow_deploy=True, plc=FakePlc(), maintenance_gate=gate)

    with pytest.raises(PLCDeployPreconditionError) as caught:
        asyncio.run(svc.reconcile_maintenance_latch(
            operator_confirmed_online_version=True,
        ))

    assert caught.value.stage == "guard_mismatch"
    assert ipc.deploy_guard_snapshot()["token"] == token


def test_deploy_route_maps_predownload_and_unknown_outcomes() -> None:
    app = FastAPI()
    app.state.plc = None
    app.state.control_mode = "DEBUG"
    register_plc_program_routes(app)

    async def busy_guard():
        raise PLCDeployPreconditionError("busy", stage="busy")

    with TestClient(app) as client:
        status_ipc = FakeIpc()
        app.state.plc_program = PlcProgramService(
            status_ipc, allow_deploy=True, plc=FakePlc())
        response = client.get("/api/plc/deploy/status")
        assert response.status_code == 200
        assert response.json()["status"] == "idle"
        assert response.json()["phase_states"] == ["pending"] * 7
        assert status_ipc.calls == []  # GET 只读内存，不唤醒/排队 worker

        app.state.plc_program = PlcProgramService(
            FakeIpc(), allow_deploy=True, plc=FakePlc(), idle_guard=busy_guard)
        response = client.post("/api/plc/deploy")
        assert response.status_code == 409
        assert response.json()["detail"]["stage"] == "busy"
        assert response.json()["detail"]["downloaded"] is False
        assert response.json()["detail"]["result_uncertain"] is False

        class BusyRestoreService:
            async def restore_version(self, _rev: str):
                raise PLCDeployPreconditionError(
                    "PLC 部署期间禁止还原工程版本", stage="busy")

        app.state.plc_program = BusyRestoreService()
        response = client.post("/api/plc/versions/0001/restore")
        assert response.status_code == 409
        assert response.json()["detail"]["stage"] == "busy"

        timeout_plc = FakePlc()
        timeout_plc.prepare_error = TimeoutError("prepare timeout")
        app.state.plc_program = PlcProgramService(
            FakeIpc(), allow_deploy=True, plc=timeout_plc)
        response = client.post("/api/plc/deploy")
        assert response.status_code == 504
        assert response.json()["detail"]["stage"] == "prepare_timeout"
        assert response.json()["detail"]["downloaded"] is False
        assert response.json()["detail"]["result_uncertain"] is False

        app.state.plc_program = PlcProgramService(
            FakeIpc(deploy_result=TimeoutError("worker timeout")),
            allow_deploy=True,
            plc=FakePlc(),
        )
        response = client.post("/api/plc/deploy")
        assert response.status_code == 502
        assert response.json()["detail"]["stage"] == "deploy_outcome_unknown"
        assert response.json()["detail"]["retryable"] is False

        reconcile_gate = MaintenanceGate()
        assert reconcile_gate.try_acquire("人工恢复测试") is not None
        app.state.plc_program = PlcProgramService(
            FakeIpc(), allow_deploy=True, plc=FakePlc(),
            maintenance_gate=reconcile_gate,
        )
        response = client.post("/api/plc/deploy/reconcile", json={
            "operator_confirmed_online_version": False,
        })
        assert response.status_code == 200
        assert response.json()["operator_confirmation_required"] is True
        assert reconcile_gate.active is True

        response = client.post("/api/plc/deploy/reconcile", json={
            "operator_confirmed_online_version": True,
        })
        assert response.status_code == 200
        assert response.json()["released"] is True
        assert reconcile_gate.active is False
