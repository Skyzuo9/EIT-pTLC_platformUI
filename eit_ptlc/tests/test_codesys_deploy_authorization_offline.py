"""Offline security contracts for full CODESYS downloads.

These tests deliberately execute only the definitions in ``worker_body.py``;
they never start InoProShop and never connect to a PLC.  Their purpose is to
make a delayed/stale file-IPC request incapable of becoming a later download.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import eit_ptlc.driver.codesys_ipc as codesys_ipc_module
from eit_ptlc.controller.plc_version_repo import PlcVersionRepo
from eit_ptlc.driver.codesys_ipc import CodesysIpcClient


_ROOT = Path(__file__).resolve().parent.parent
_WORKER_BODY = _ROOT / "tools" / "codesys-mcp" / "worker_body.py"
_MCP_SERVER = _ROOT / "tools" / "codesys-mcp" / "server.mjs"

_PLC_IP = "192.0.2.55"
_PROTOCOL_VERSION = 3
_AUTH_TTL_SEC = 60.0


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_WORKER_BODY_SHA256 = _sha(_WORKER_BODY.read_bytes())


class _FakeApplication:
    def __init__(self) -> None:
        self.build_calls = 0

    def build(self) -> None:
        self.build_calls += 1


class _FakeProject:
    def __init__(self, project_path: Path, *, save_bytes: bytes | None = None) -> None:
        self.active_application = _FakeApplication()
        self._project_path = project_path
        self._save_bytes = save_bytes
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1
        if self._save_bytes is not None:
            self._project_path.write_bytes(self._save_bytes)

    def find(self, *_args):
        return []


class _FakeOnlineApplication:
    def __init__(self) -> None:
        self.login_calls = 0
        self.start_calls = 0
        self.logout_calls = 0
        self.on_create = None

    def login(self, *_args) -> None:
        self.login_calls += 1

    def start(self) -> None:
        self.start_calls += 1

    def logout(self) -> None:
        self.logout_calls += 1


class _FakeOnline:
    def __init__(self, online_application: _FakeOnlineApplication) -> None:
        self._online_application = online_application

    def create_online_application(self, *_args):
        if self._online_application.on_create is not None:
            self._online_application.on_create()
        return self._online_application


class _FakeSystem:
    def clear_messages(self, _category) -> None:
        return None

    def get_message_objects(self, _category):
        return []

    def process_messageloop(self) -> None:
        return None


def _load_worker(tmp_path: Path, *, project_bytes: bytes = b"project-v1", save_bytes=None):
    """Load worker functions without entering its polling loop."""
    project_path = tmp_path / "active.project"
    project_path.write_bytes(project_bytes)
    ipc_dir = tmp_path / "ipc"
    ipc_dir.mkdir()

    online_application = _FakeOnlineApplication()
    fake_online = _FakeOnline(online_application)
    project = _FakeProject(project_path, save_bytes=save_bytes)

    source = _WORKER_BODY.read_text(encoding="utf-8")
    definitions = source.rsplit("\nmain()\n", 1)[0]
    namespace = {
        "__name__": "codesys_worker_deploy_authorization_test",
        "IPC_DIR": str(ipc_dir),
        "PROJECT_PATH": str(project_path),
        "POLL_SEC": 0.01,
        "COMPILE_CATEGORY": "test",
        "PLC_IP": _PLC_IP,
        "IDLE_TIMEOUT_SEC": 0,
        "WORKER_PROTOCOL_VERSION": _PROTOCOL_VERSION,
        "DEPLOY_AUTH_TTL_SEC": _AUTH_TTL_SEC,
        "WORKER_BODY_SHA256": _WORKER_BODY_SHA256,
        "unicode": str,
        "system": _FakeSystem(),
        "online": fake_online,
        "OnlineChangeOption": SimpleNamespace(Never="force-full"),
    }
    exec(compile(definitions, "worker_body_deploy_authorization_test", "exec"), namespace)
    # Keep a valid authorization test quick and independent of CODESYS message-loop timing.
    namespace["time"] = SimpleNamespace(time=time.time, sleep=lambda _seconds: None)
    comm_path = SimpleNamespace(
        selected_address="route-to-authorized-plc",
        current_address="route-to-authorized-plc",
        select_calls=0,
        readback_calls=0,
    )

    def select_target(_project):
        comm_path.select_calls += 1
        comm_path.current_address = comm_path.selected_address
        return {
            "description": f"target={_PLC_IP}",
            "plc_ip": _PLC_IP,
            "address": comm_path.selected_address,
        }

    def verify_target(_project, expected_address):
        comm_path.readback_calls += 1
        if comm_path.current_address != expected_address:
            return (
                "target path changed before login: "
                f"expected={expected_address}, current={comm_path.current_address}"
            )
        return None

    namespace["set_comm_path_by_ip"] = select_target
    namespace["verify_comm_path_readback"] = verify_target
    namespace["_test_comm_path"] = comm_path
    return namespace, project, online_application, project_path, ipc_dir


def _worker_instance_id(ns: dict) -> str:
    value = ns.get("WORKER_INSTANCE_ID") or ns.get("WORKER_SESSION_ID")
    assert isinstance(value, str) and value, "worker must expose a per-process instance id"
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _authorization(
    ns: dict,
    ipc_dir: Path,
    project_path: Path,
    *,
    nonce: str = "a" * 48,
    expected_sha256: str | None = None,
    expected_plc_ip: str = _PLC_IP,
    worker_instance_id: str | None = None,
    worker_body_sha256: str = _WORKER_BODY_SHA256,
    issued_at: float | None = None,
    expires_at: float | None = None,
    commit_seq: int = 17,
) -> tuple[dict, str]:
    now = time.time()
    token = "d" * 48
    auth = {
        "nonce": nonce,
        "issued_at": now - 1 if issued_at is None else issued_at,
        "expires_at": now + 30 if expires_at is None else expires_at,
        "worker_instance_id": worker_instance_id or _worker_instance_id(ns),
        "guard_token": token,
        "expected_sha256": expected_sha256 or _sha(project_path.read_bytes()),
        "expected_plc_ip": expected_plc_ip,
        "commit_seq": commit_seq,
        "protocol_version": _PROTOCOL_VERSION,
        "worker_body_sha256": worker_body_sha256,
    }
    _write_json(
        ipc_dir / "deploy.guard.json",
        {
            "state": "active",
            "purpose": "deploy",
            "token": token,
            "project": ns["os"].path.normcase(ns["os"].path.abspath(str(project_path))),
            "plc_ip": _PLC_IP,
            "protocol_version": _PROTOCOL_VERSION,
            "worker_body_sha256": worker_body_sha256,
        },
    )
    _write_json(ipc_dir / "deploy-auth" / f"{nonce}.pending.json", auth)
    return auth, token


def _dispatch_deploy(ns: dict, project: _FakeProject, auth: dict | None, token: str | None):
    request = {
        "op": "deploy",
        "args": {} if auth is None else {"authorization": auth},
    }
    if token is not None:
        request["deploy_guard_token"] = token
    response = ns["dispatch"](project, request)
    assert response["ok"] is True, response
    return response["result"]


def _assert_rejected_before_login(result: dict, project: _FakeProject,
                                  online_app: _FakeOnlineApplication) -> None:
    assert result["deployed"] is False
    assert result["authorization_valid"] is False
    assert result.get("reason")
    assert project.save_calls == 0
    assert project.active_application.build_calls == 0
    assert online_app.login_calls == 0


def test_worker_rejects_old_request_without_authorization_before_touching_project(tmp_path: Path) -> None:
    ns, project, online_app, _project_path, _ipc_dir = _load_worker(tmp_path)

    result = _dispatch_deploy(ns, project, auth=None, token=None)

    _assert_rejected_before_login(result, project, online_app)


@pytest.mark.parametrize(
    "failure",
    ["expired", "oversized_ttl", "old_worker", "wrong_target", "wrong_worker_body"],
)
def test_worker_binds_authorization_to_ttl_session_and_target(
    tmp_path: Path, failure: str,
) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    kwargs: dict = {
        "nonce": {
            "expired": "a" * 48,
            "oversized_ttl": "b" * 48,
            "old_worker": "c" * 48,
            "wrong_target": "e" * 48,
            "wrong_worker_body": "f" * 48,
        }[failure],
    }
    if failure == "expired":
        kwargs.update(issued_at=time.time() - 120, expires_at=time.time() - 60)
    elif failure == "oversized_ttl":
        # Still unexpired, but its 120-second authority window exceeds the
        # protocol's exact 60-second maximum and must fail closed.
        kwargs.update(issued_at=time.time(), expires_at=time.time() + 120)
    elif failure == "old_worker":
        kwargs["worker_instance_id"] = "previous-worker-instance"
    elif failure == "wrong_target":
        kwargs["expected_plc_ip"] = "192.0.2.99"
    else:
        kwargs["worker_body_sha256"] = "0" * 64
    auth, token = _authorization(ns, ipc_dir, project_path, **kwargs)

    result = _dispatch_deploy(ns, project, auth, token)

    _assert_rejected_before_login(result, project, online_app)
    assert not (ipc_dir / "deploy-auth" / f"{auth['nonce']}.pending.json").exists()
    assert (ipc_dir / "deploy-auth" / f"{auth['nonce']}.consumed.json").exists()


def test_worker_rechecks_disk_sha_without_resaving_before_login(tmp_path: Path) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(
        tmp_path, project_bytes=b"authorized-bytes",
    )
    auth, token = _authorization(
        ns, ipc_dir, project_path, expected_sha256=_sha(b"authorized-bytes"),
    )
    project_path.write_bytes(b"changed-after-authorization")

    result = _dispatch_deploy(ns, project, auth, token)

    assert result["deployed"] is False
    # The one-shot authorization itself was valid; the separately bound project
    # bytes were not.  This distinction is useful in deployment diagnostics.
    assert result["authorization_valid"] is True
    assert result["stage"] == "project_hash_mismatch"
    assert result["project_sha256"] == _sha(b"changed-after-authorization")
    assert project.save_calls == 0
    assert project.active_application.build_calls == 0
    assert online_app.login_calls == 0


def test_worker_authorization_claim_is_one_time_and_cannot_be_replayed(tmp_path: Path) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    auth, token = _authorization(ns, ipc_dir, project_path)

    first = _dispatch_deploy(ns, project, auth, token)
    second = _dispatch_deploy(ns, project, auth, token)

    assert first["deployed"] is True
    assert first["authorization_valid"] is True
    assert first["project_sha256"] == auth["expected_sha256"]
    assert first["commit_seq"] == auth["commit_seq"]
    assert second["deployed"] is False
    assert second["authorization_valid"] is False
    assert "consumed" in second["reason"] or "authorization" in second["reason"]
    assert online_app.login_calls == 1
    assert project.active_application.build_calls == 1
    assert not (ipc_dir / "deploy-auth" / f"{auth['nonce']}.pending.json").exists()


def test_worker_revalidates_changed_guard_inside_physical_lock_before_login(
    tmp_path: Path,
) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    auth, token = _authorization(ns, ipc_dir, project_path)

    def replace_guard_after_locked_target_selection() -> None:
        guard_path = ipc_dir / "deploy.guard.json"
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
        guard["token"] = "e" * 48
        _write_json(guard_path, guard)

    # The online handle is created after the lock-protected second target
    # selection, but before the final authorization check and oa.login().
    online_app.on_create = replace_guard_after_locked_target_selection
    result = _dispatch_deploy(ns, project, auth, token)

    assert result["deployed"] is False
    assert result["stage"] == "final_authorization_failed"
    assert result["authorization_valid"] is False
    assert result["login_attempted"] is False
    assert result["physical_lock_released"] is True
    assert online_app.login_calls == 0
    assert ns["_test_comm_path"].select_calls == 2
    assert ns["_test_comm_path"].readback_calls == 1
    assert not (ipc_dir / "deploy.physical.lock").exists()


def test_worker_rechecks_locked_target_readback_immediately_before_login(
    tmp_path: Path,
) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    auth, token = _authorization(ns, ipc_dir, project_path)

    def switch_target_after_online_handle_creation() -> None:
        ns["_test_comm_path"].current_address = "route-to-different-plc"

    online_app.on_create = switch_target_after_online_handle_creation
    result = _dispatch_deploy(ns, project, auth, token)

    assert result["deployed"] is False
    assert result["stage"] == "final_target_verification_failed"
    assert result.get("target_verified") is not True
    assert result["login_attempted"] is False
    assert result["physical_lock_released"] is True
    assert "target path changed" in result["reason"]
    assert online_app.login_calls == 0
    assert ns["_test_comm_path"].select_calls == 2
    assert ns["_test_comm_path"].readback_calls == 1


def test_worker_refuses_login_while_physical_deploy_lock_is_occupied(
    tmp_path: Path,
) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    auth, token = _authorization(ns, ipc_dir, project_path)
    lock_path = ipc_dir / "deploy.physical.lock"
    _write_json(
        lock_path,
        {
            "owner": "another-worker",
            "purpose": "physical_deploy",
            "owner_pid": os.getpid(),
            "owner_token": "1" * 32,
        },
    )

    result = _dispatch_deploy(ns, project, auth, token)

    assert result["deployed"] is False
    assert result["stage"] == "physical_deploy_locked"
    assert result["login_attempted"] is False
    assert result["retryable"] is False
    assert online_app.login_calls == 0
    assert json.loads(lock_path.read_text(encoding="utf-8"))["owner_token"] == "1" * 32


def test_worker_preserves_deployed_truth_when_physical_lock_release_fails_after_login(
    tmp_path: Path,
) -> None:
    ns, project, online_app, project_path, ipc_dir = _load_worker(tmp_path)
    auth, token = _authorization(ns, ipc_dir, project_path)
    ns["release_physical_deploy_lock"] = lambda _token: False

    result = _dispatch_deploy(ns, project, auth, token)

    # Once login was attempted successfully, a lock-cleanup failure must never
    # be rewritten as a safe pre-download rejection: operator reconciliation is
    # required and automatic retry remains forbidden.
    assert result["deployed"] is True
    assert result["login_attempted"] is True
    assert result["physical_lock_released"] is False
    assert result["ready"] is False
    assert result["retryable"] is False
    assert result["maintenance_recovery_required"] is True
    assert result["stage"] == "physical_lock_release_failed"
    assert online_app.login_calls == 1
    assert (ipc_dir / "deploy.physical.lock").exists()


def test_new_worker_rejects_abandoned_claim_instead_of_replaying_it(tmp_path: Path) -> None:
    ns, project, online_app, _project_path, ipc_dir = _load_worker(tmp_path)
    request_dir = ipc_dir / "requests"
    response_dir = ipc_dir / "responses"
    request_dir.mkdir()
    response_dir.mkdir()
    claim = request_dir / "stale.claimed.json"
    _write_json(claim, {"op": "deploy", "args": {"authorization": {"nonce": "a" * 48}}})

    ns["reject_abandoned_deploy_claims"]()

    response = json.loads((response_dir / "stale.resp.json").read_text(encoding="utf-8"))
    assert response["ok"] is False
    assert "replay is forbidden" in response["error"]
    assert not claim.exists()
    assert project.save_calls == 0
    assert online_app.login_calls == 0


def test_worker_guard_blocks_old_mutation_and_stop_requests(tmp_path: Path) -> None:
    ns, _project, _online_app, project_path, ipc_dir = _load_worker(tmp_path)
    token = "d" * 48
    _write_json(
        ipc_dir / "deploy.guard.json",
        {
            "state": "active",
            "purpose": "deploy",
            "token": token,
            "project": ns["os"].path.normcase(ns["os"].path.abspath(str(project_path))),
            "plc_ip": _PLC_IP,
            "protocol_version": _PROTOCOL_VERSION,
            "worker_body_sha256": _WORKER_BODY_SHA256,
        },
    )

    allowed, error = ns["deploy_guard_allows"]({"op": "write", "args": {}})
    assert allowed is False
    assert "blocks operation" in error
    allowed, error = ns["deploy_guard_allows"]({
        "op": "compile", "args": {}, "deploy_guard_token": token,
    })
    assert allowed is True
    assert error is None
    allowed, error = ns["deploy_guard_allows"]({
        "op": "write", "args": {}, "deploy_guard_token": token,
    })
    assert allowed is False
    assert "purpose" in error

    (ipc_dir / "worker.stop").write_text("1", encoding="utf-8")
    assert ns["stop_guard_allows"]() is False
    guard = json.loads((ipc_dir / "deploy.guard.json").read_text(encoding="utf-8"))
    guard["purpose"] = "restore"
    _write_json(ipc_dir / "deploy.guard.json", guard)
    _write_json(ipc_dir / "worker.stop", {"deploy_guard_token": token})
    assert ns["stop_guard_allows"]() is True


def test_worker_status_fingerprints_instance_project_protocol_and_plc(tmp_path: Path) -> None:
    ns, _project, _online_app, project_path, ipc_dir = _load_worker(tmp_path)

    ns["write_status"]("ready")

    status = json.loads((ipc_dir / "worker.status").read_text(encoding="utf-8"))
    assert status["instance_id"] == _worker_instance_id(ns)
    assert status["project"] == ns["os"].path.normcase(
        ns["os"].path.abspath(str(project_path)),
    )
    assert status["plc_ip"] == _PLC_IP
    assert status["protocol_version"] == _PROTOCOL_VERSION
    assert status["worker_body_sha256"] == _WORKER_BODY_SHA256


def _client(tmp_path: Path, *, ipc_dir: Path | None = None) -> CodesysIpcClient:
    project = tmp_path / "active.project"
    if not project.exists():
        project.write_bytes(b"project")
    return CodesysIpcClient(
        exe=str(tmp_path / "InoProShop.exe"),
        profile="test",
        project=project,
        ipc_dir=ipc_dir or (tmp_path / "ipc"),
        compile_category="test",
        plc_ip=_PLC_IP,
        poll_sec=0.001,
        ready_timeout=0.01,
        idle_timeout=0,
    )


def test_python_ipc_timeout_removes_unconsumed_request(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    Path(client._req_dir).mkdir(parents=True)  # noqa: SLF001 - protocol-level test
    Path(client._resp_dir).mkdir(parents=True)  # noqa: SLF001
    monkeypatch.setattr("eit_ptlc.driver.codesys_ipc.secrets.token_hex", lambda _n: "deadbeef")

    with pytest.raises(TimeoutError):
        client._call_blocking("compile", {}, timeout=0)  # noqa: SLF001

    assert not (Path(client._req_dir) / "deadbeef.req.json").exists()  # noqa: SLF001
    assert not (Path(client._req_dir) / "deadbeef.req.json.tmp").exists()  # noqa: SLF001


def test_deploy_guard_blocks_other_client_mutations_and_lazy_worker_start(tmp_path: Path) -> None:
    ipc_dir = tmp_path / "shared-ipc"
    owner = _client(tmp_path, ipc_dir=ipc_dir)
    other = _client(tmp_path, ipc_dir=ipc_dir)
    token = owner.begin_deploy_guard(purpose="offline-test")

    try:
        with pytest.raises(RuntimeError, match="guard|transaction|deploy"):
            asyncio.run(other.call("write", {"path": "Application/Foo"}, timeout=0.01))
        with pytest.raises(RuntimeError, match="guard|transaction|deploy"):
            asyncio.run(other.ensure_worker())
        with pytest.raises(RuntimeError, match="guard|transaction|deploy"):
            other.takeover(by="test")
        with pytest.raises(RuntimeError, match="guard|transaction|deploy"):
            asyncio.run(other.stop_worker(timeout=0.01))
        assert not Path(other._worker_script).exists()  # noqa: SLF001
    finally:
        owner.end_deploy_guard(token)

    assert not (ipc_dir / "deploy.guard.json").exists()


def test_client_rejects_live_worker_with_wrong_target_fingerprint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ipc_dir = Path(client._ipc_dir)  # noqa: SLF001
    ipc_dir.mkdir(parents=True)
    _write_json(
        Path(client._status_path),  # noqa: SLF001
        {
            "state": "ready",
            "pid": os.getpid(),
            "project": client._canonical_project(),  # noqa: SLF001
            "plc_ip": "192.0.2.99",
            "protocol_version": _PROTOCOL_VERSION,
            "worker_body_sha256": client.worker_body_sha256,
            "instance_id": "different-target-worker",
        },
    )

    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        client._read_live_status()  # noqa: SLF001


def test_live_write_lock_is_not_stolen_by_age_and_release_is_token_conditional(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ipc_dir = Path(client._ipc_dir)  # noqa: SLF001
    ipc_dir.mkdir(parents=True)
    lock_path = Path(client._write_lock_path)  # noqa: SLF001
    _write_json(
        lock_path,
        {"owner_pid": os.getpid(), "ts": time.time() - 10_000, "owner_token": "old-owner"},
    )

    with pytest.raises(RuntimeError, match="owner"):
        client._acquire_write_lock(timeout=0)  # noqa: SLF001
    assert json.loads(lock_path.read_text(encoding="utf-8"))["owner_token"] == "old-owner"

    client._release_write_lock("not-the-owner")  # noqa: SLF001
    assert lock_path.exists()


def test_force_reconcile_refuses_unreadable_physical_lock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    physical = Path(client._physical_deploy_lock_path)  # noqa: SLF001
    physical.write_bytes(b"")

    with pytest.raises(RuntimeError, match="unreadable"):
        client.force_clear_deploy_guard(
            reason="offline safety test",
            expected_token=token,
            expected_purpose="deploy",
            expected_state="active",
            expected_project=client._canonical_project(),  # noqa: SLF001
            expected_plc_ip=_PLC_IP,
            expected_protocol_version=_PROTOCOL_VERSION,
            expected_worker_body_sha256=client.worker_body_sha256,
        )

    assert Path(client._deploy_guard_path).exists()  # noqa: SLF001
    assert physical.exists()


def test_force_reconcile_refuses_live_physical_lock_owner(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    physical = Path(client._physical_deploy_lock_path)  # noqa: SLF001
    _write_json(physical, {
        "owner": "codesys-worker",
        "owner_pid": os.getpid(),
        "owner_token": "a" * 32,
    })

    with pytest.raises(RuntimeError, match="live process"):
        client.force_clear_deploy_guard(
            reason="offline safety test",
            expected_token=token,
            expected_purpose="deploy",
            expected_state="active",
            expected_project=client._canonical_project(),  # noqa: SLF001
            expected_plc_ip=_PLC_IP,
            expected_protocol_version=_PROTOCOL_VERSION,
            expected_worker_body_sha256=client.worker_body_sha256,
        )

    assert Path(client._deploy_guard_path).exists()  # noqa: SLF001
    assert physical.exists()


def test_force_reconcile_archives_only_well_formed_dead_owner_lock(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    physical = Path(client._physical_deploy_lock_path)  # noqa: SLF001
    _write_json(physical, {
        "owner": "codesys-worker",
        "owner_pid": 2_147_483_647,
        "owner_token": "b" * 32,
    })

    cleared = client.force_clear_deploy_guard(
        reason="operator verified PLC READY and online version",
        expected_token=token,
        expected_purpose="deploy",
        expected_state="active",
        expected_project=client._canonical_project(),  # noqa: SLF001
        expected_plc_ip=_PLC_IP,
        expected_protocol_version=_PROTOCOL_VERSION,
        expected_worker_body_sha256=client.worker_body_sha256,
    )

    assert cleared["token"] == token
    assert not Path(client._deploy_guard_path).exists()  # noqa: SLF001
    assert not physical.exists()
    assert len(list(Path(client._ipc_dir).glob("deploy.physical.reconciled.*.json"))) == 1  # noqa: SLF001


def test_force_reconcile_is_token_and_fingerprint_conditional(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")

    with pytest.raises(RuntimeError, match="changed"):
        client.force_clear_deploy_guard(
            reason="offline safety test",
            expected_token="f" * 48,
            expected_purpose="deploy",
            expected_state="active",
            expected_project=client._canonical_project(),  # noqa: SLF001
            expected_plc_ip=_PLC_IP,
            expected_protocol_version=_PROTOCOL_VERSION,
            expected_worker_body_sha256=client.worker_body_sha256,
        )
    assert Path(client._deploy_guard_path).exists()  # noqa: SLF001

    guard_path = Path(client._deploy_guard_path)  # noqa: SLF001
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    guard["project"] = str(tmp_path / "different.project")
    _write_json(guard_path, guard)
    with pytest.raises(RuntimeError, match="fingerprint"):
        client.force_clear_deploy_guard(
            reason="offline safety test",
            expected_token=token,
            expected_purpose="deploy",
            expected_state="active",
            expected_project=client._canonical_project(),  # noqa: SLF001
            expected_plc_ip=_PLC_IP,
            expected_protocol_version=_PROTOCOL_VERSION,
            expected_worker_body_sha256=client.worker_body_sha256,
        )
    assert guard_path.exists()


def test_end_guard_release_failure_leaves_reconcilable_marker(
    tmp_path: Path, monkeypatch,
) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    physical_path = client._physical_deploy_lock_path  # noqa: SLF001
    original_remove = client._remove_lock_if_owned  # noqa: SLF001

    def fail_only_physical(path: str, owner_token: str) -> bool:
        if path == physical_path:
            return False
        return original_remove(path, owner_token)

    monkeypatch.setattr(client, "_remove_lock_if_owned", fail_only_physical)
    with pytest.raises(RuntimeError, match="physical"):
        client.end_deploy_guard(token)

    guard = client.deploy_guard_snapshot()
    assert guard["state"] == "releasing"
    assert guard["token"] == token
    assert Path(physical_path).exists()


def test_force_reconcile_release_failure_keeps_guard_and_no_false_audit(
    tmp_path: Path, monkeypatch,
) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    physical_path = client._physical_deploy_lock_path  # noqa: SLF001
    original_remove = client._remove_lock_if_owned  # noqa: SLF001

    def fail_only_physical(path: str, owner_token: str) -> bool:
        if path == physical_path:
            return False
        return original_remove(path, owner_token)

    monkeypatch.setattr(client, "_remove_lock_if_owned", fail_only_physical)
    with pytest.raises(RuntimeError, match="physical"):
        client.force_clear_deploy_guard(
            reason="operator verified PLC READY and online version",
            expected_token=token,
            expected_purpose="deploy",
            expected_state="active",
            expected_project=client._canonical_project(),  # noqa: SLF001
            expected_plc_ip=_PLC_IP,
            expected_protocol_version=_PROTOCOL_VERSION,
            expected_worker_body_sha256=client.worker_body_sha256,
        )

    guard = client.deploy_guard_snapshot()
    assert guard["state"] == "releasing"
    assert guard["token"] == token
    assert Path(physical_path).exists()
    assert not (Path(client._ipc_dir) / "deploy.guard.last-cleared.json").exists()  # noqa: SLF001


def test_force_reconcile_accepts_exact_legacy_guard_fingerprint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    guard_path = Path(client._deploy_guard_path)  # noqa: SLF001
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    guard["protocol_version"] = 2
    guard.pop("worker_body_sha256")
    _write_json(guard_path, guard)

    cleared = client.force_clear_deploy_guard(
        reason="operator verified legacy online version and PLC READY",
        expected_token=token,
        expected_purpose="deploy",
        expected_state="active",
        expected_project=client._canonical_project(),  # noqa: SLF001
        expected_plc_ip=_PLC_IP,
        expected_protocol_version=2,
        expected_worker_body_sha256=None,
    )

    assert cleared["protocol_version"] == 2
    assert "worker_body_sha256" not in cleared
    assert not guard_path.exists()


def test_force_reconcile_clears_dead_physical_only_orphan(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ipc_dir = Path(client._ipc_dir)  # noqa: SLF001
    ipc_dir.mkdir(parents=True)
    physical = Path(client._physical_deploy_lock_path)  # noqa: SLF001
    owner_token = "c" * 32
    _write_json(physical, {
        "owner": "codesys-worker",
        "owner_pid": 2_147_483_647,
        "owner_token": owner_token,
    })

    cleared = client.force_clear_orphan_physical_lock(
        reason="operator verified online version and PLC READY",
        expected_owner_token=owner_token,
    )

    assert cleared["owner_token"] == owner_token
    assert not physical.exists()
    assert (ipc_dir / "deploy.physical.last-reconciled.json").exists()


def test_pid_liveness_treats_access_denied_as_alive_unknown(monkeypatch) -> None:
    class Kernel32:
        def OpenProcess(self, *_args):
            return 0

        def GetLastError(self):
            return 5  # ERROR_ACCESS_DENIED

    monkeypatch.setattr(
        codesys_ipc_module.ctypes, "windll",
        SimpleNamespace(kernel32=Kernel32()),
    )
    assert codesys_ipc_module._pid_alive(12345) is True


def test_pid_liveness_only_treats_invalid_parameter_as_dead(monkeypatch) -> None:
    class Kernel32:
        def OpenProcess(self, *_args):
            return 0

        def GetLastError(self):
            return 87  # ERROR_INVALID_PARAMETER / nonexistent PID

    monkeypatch.setattr(
        codesys_ipc_module.ctypes, "windll",
        SimpleNamespace(kernel32=Kernel32()),
    )
    assert codesys_ipc_module._pid_alive(12345) is False


def test_node_client_obeys_shared_guard_and_revokes_timed_out_request() -> None:
    """The second (MCP/Node) client must not bypass the Python deploy transaction."""
    source = _MCP_SERVER.read_text(encoding="utf-8")

    assert 'const DEPLOY_GUARD_PATH = path.join(CFG.ipcDir, "deploy.guard.json")' in source
    assert 'await assertDeployGuardAllows("start_worker")' in source
    assert 'await assertDeployGuardAllows("shutdown")' in source
    assert "await assertDeployGuardAllows(op)" in source
    assert "await safeUnlink(reqPath)" in source
    assert "workerChild.kill()" not in source
    assert "currentBodySha256 !== WORKER_BODY_SHA256" in source


def test_python_client_refuses_to_spawn_with_changed_worker_body(tmp_path: Path) -> None:
    client = _client(tmp_path)
    client._worker_body_sha256 = "0" * 64  # noqa: SLF001 - simulate hot source change

    with pytest.raises(RuntimeError, match="restart backend and worker"):
        client.begin_deploy_guard(purpose="deploy")
    with pytest.raises(RuntimeError, match="changed after this backend started"):
        client._build_worker_script()  # noqa: SLF001


def test_authorized_deploy_failure_revokes_pending_ticket(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    token = client.begin_deploy_guard(purpose="deploy")
    instance_id = "worker-instance-for-test"
    observed: dict = {}

    async def worker_already_ready(*, guard_token=None) -> None:
        assert guard_token == token
        return None

    async def fail_call(_op, _args=None, _timeout=60.0, *, guard_token=None):
        assert guard_token == token
        observed.update(op=_op, args=_args, timeout=_timeout)
        nonce = _args["authorization"]["nonce"]
        assert (Path(client._deploy_auth_dir) / f"{nonce}.pending.json").exists()  # noqa: SLF001
        raise TimeoutError("simulated response timeout")

    monkeypatch.setattr(client, "ensure_worker", worker_already_ready)
    monkeypatch.setattr(client, "_read_live_status", lambda: {"instance_id": instance_id})
    monkeypatch.setattr(client, "call", fail_call)

    try:
        with pytest.raises(TimeoutError):
            asyncio.run(client.authorized_deploy(
                expected_sha256=_sha(b"project"),
                commit_seq=9,
                expected_plc_ip=_PLC_IP,
                guard_token=token,
                timeout=0.01,
            ))
        auth_dir = Path(client._deploy_auth_dir)  # noqa: SLF001
        assert list(auth_dir.glob("*.pending.json")) == []
        auth = observed["args"]["authorization"]
        assert observed["op"] == "deploy"
        assert observed["timeout"] == 0.01
        assert auth["worker_instance_id"] == instance_id
        assert auth["guard_token"] == token
        assert auth["expected_sha256"] == _sha(b"project")
        assert auth["expected_plc_ip"] == _PLC_IP
        assert auth["commit_seq"] == 9
        assert auth["protocol_version"] == _PROTOCOL_VERSION
        assert auth["worker_body_sha256"] == client.worker_body_sha256
        assert auth["expires_at"] - auth["issued_at"] == pytest.approx(_AUTH_TTL_SEC)
    finally:
        client.end_deploy_guard(token)


def test_version_repo_marks_only_the_exact_expected_project_sha(tmp_path: Path) -> None:
    project = tmp_path / "active.project"
    project.write_bytes(b"version-a")
    repo = PlcVersionRepo(project, tmp_path / "history", time_fn=lambda: 1_700_000_000.0)
    sha_a = _sha(b"version-a")

    assert repo.current_sha256() == sha_a
    repo.snapshot_if_changed()
    project.write_bytes(b"version-b")

    with pytest.raises(RuntimeError, match="SHA|sha|hash|content"):
        repo.mark_deployed(expected_sha256=sha_a)

    assert len(repo.history()) == 1
    assert repo.history()[0]["sha256"] == sha_a
    assert repo.history()[0]["deployed_at"] is None

    sha_b = _sha(b"version-b")
    marked = repo.mark_deployed(expected_sha256=sha_b)
    assert marked["sha256"] == sha_b
    assert marked["deployed_at"] is not None
