"""PLC 工程版本仓库/部署服务路由离线测试
=========================================
功能:
    不启动 InoProShop, 用临时 .project 文件 + 假 IPC 客户端验证:
      - PlcVersionRepo: save 触发快照、相同内容去重、history 升序、mark_deployed 写
        deployed_at、restore 字节级还原且还原前先自快照(可逆)、version_bytes/get_version
      - PlcProgramService: save=true 后自快照、save=false 不快照、deploy 后打部署标记、
        online_status/deploy 的 op/超时映射、restore_version 先停 worker(stop_worker 释放文件锁)、
        接管态 restore 被 stop 门拒绝(RuntimeError→503, 不停 worker 不覆盖工程)
      - /api/plc/* 路由: allow_deploy=false→deploy 403; =true→200; versions 列表/下载/
        手动快照/还原; 版本不存在→404; 服务未就绪→503
    全程离线, 不连真机, 不弹 IDE。

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m eit_ptlc.tests.test_plc_version_offline
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from eit_ptlc.controller.plc_program_service import (
    PLCDeployPreconditionError,
    PlcProgramService,
)
from eit_ptlc.controller.plc_version_repo import PlcVersionRepo
from eit_ptlc.runtime.bootstrap import create_sim_app


class FakeIpc:
    """假 CodesysIpcClient: 记录每次 call, 按 op 返回/抛错; 记录 stop_worker 次数(供 restore 验证);
    manual_control=True 时 stop_worker 拒绝(模拟 codesys_ipc 的接管门, 供 F1 还原路径验证)。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.responses: dict = {}
        self.stop_worker_called = 0
        self.manual_control = False
        self.target_plc_ip = "192.0.2.55"
        self.worker_body_sha256 = "b" * 64
        self._guard_token: str | None = None
        self._guard_purpose: str | None = None
        self._physical_lock: dict = {}

    async def call(self, op, args=None, timeout=60.0, *, guard_token=None):
        self.calls.append((op, args, timeout))
        r = self.responses.get(op)
        if isinstance(r, Exception):
            raise r
        return r

    async def stop_worker(
        self, timeout: float = 30.0, *, guard_token=None,
    ) -> bool:
        if self.manual_control:
            raise RuntimeError(
                "PLC session is under manual control by operator; operation 'stop' is blocked (fake)")
        self.stop_worker_called += 1
        return True

    def project_sha256(self) -> str:
        # Services with a PlcVersionRepo use the repository hash.  This fallback
        # keeps the fake complete for service instances without one.
        return "a" * 64

    def begin_deploy_guard(self, *, purpose="deploy", timeout=5.0) -> str:
        if self._guard_token is not None:
            raise RuntimeError("deploy guard already active")
        self._guard_token = f"fake-{purpose}-guard"
        self._guard_purpose = purpose
        return self._guard_token

    def end_deploy_guard(self, token: str) -> None:
        if token != self._guard_token:
            raise RuntimeError("deploy guard token mismatch")
        self._guard_token = None
        self._guard_purpose = None

    def deploy_guard_snapshot(self) -> dict:
        if self._guard_token is None:
            return {}
        return {"state": "active", "token": self._guard_token,
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
        assert expected_token == self._guard_token
        assert expected_purpose == self._guard_purpose
        assert expected_state in {"active", "releasing"}
        previous = ({"token": self._guard_token, "purpose": self._guard_purpose,
                     "reason": reason}
                    if self._guard_token is not None else {})
        self._guard_token = None
        self._guard_purpose = None
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
        self.calls.append(("deploy", args, timeout))
        result = self.responses.get("deploy")
        if isinstance(result, Exception):
            raise result
        result = dict(result or {})
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
    """部署安全握手假控制器；版本测试只关心台账，不重复验证握手细节。"""

    async def reset_deploy(self, **_kwargs) -> None:
        return None

    async def prepare_for_deploy(self, **_kwargs) -> dict:
        return {"state": 20, "accepted_seq": 1, "error_code": 0, "request_seq": 1}

    async def commit_deploy(self, request_seq: int, **_kwargs) -> dict:
        return {"state": 25, "accepted_seq": request_seq, "commit_seq": request_seq,
                "error_code": 0, "request_seq": request_seq}

    async def confirm_deploy_committed(self, request_seq: int) -> dict:
        return {"state": 25, "accepted_seq": request_seq, "commit_seq": request_seq,
                "error_code": 0, "request_seq": request_seq, "start": True}

    async def wait_startup_ready(self, **_kwargs) -> dict:
        return {"State": 60, "ErrorCode": 0, "Ready": True}

    async def startup_snapshot(self) -> dict:
        return {"State": 60, "ErrorCode": 0, "Ready": True}

    async def deploy_snapshot(self) -> dict:
        return {"State": 0, "AcceptedSeq": 0, "CommitSeq": 0, "ErrorCode": 0}


def _clock():
    """单调递增取时函数(每调 +1s), 使各快照 ISO 戳互不相同, 便于断言。"""
    state = {"t": 1_700_000_000.0}

    def fn():
        state["t"] += 1.0
        return state["t"]

    return fn


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # ================= 1) 仓库层: 快照/去重/还原 =================
    d1 = Path(tempfile.mkdtemp(prefix="plcver_"))
    proj = d1 / "20260622.project"
    proj.write_bytes(b"AAAA")
    repo = PlcVersionRepo(proj, d1 / "history", time_fn=_clock())

    e1 = repo.snapshot_if_changed(message="init")
    check("repo_first_snapshot", e1 is not None and e1["rev"] == "0001", str(e1))
    check("repo_first_deployed_none", bool(e1) and e1["deployed_at"] is None, str(e1))

    check("repo_dedup_none", repo.snapshot_if_changed() is None, "内容未变应去重返回 None")
    check("repo_hist_len1_after_dup", len(repo.history()) == 1, str(repo.history()))

    proj.write_bytes(b"BBBB")
    e2 = repo.snapshot_if_changed()
    check("repo_second_snapshot_0002", e2 is not None and e2["rev"] == "0002", str(e2))
    check("repo_hist_order", [h["rev"] for h in repo.history()] == ["0001", "0002"], str(repo.history()))
    check("repo_bytes_v1", repo.version_bytes("0001") == b"AAAA", "")
    check("repo_bytes_v2", repo.version_bytes("0002") == b"BBBB", "")

    try:
        repo.get_version("9999")
        missing_ok = False
    except KeyError:
        missing_ok = True
    check("repo_get_missing_keyerror", missing_ok, "")

    # mark_deployed: 当前=BBBB 已是最新快照 → 不新增, 给 0002 写 deployed_at
    dep = repo.mark_deployed(expected_sha256=_sha(b"BBBB"))
    check("repo_mark_deployed_rev", dep["rev"] == "0002" and dep["deployed_at"] is not None, str(dep))
    check("repo_no_extra_snapshot", len(repo.history()) == 2, str(repo.history()))

    # restore 0001: 当前 BBBB 已入库(去重) → 覆盖 proj 为 AAAA
    restored = repo.restore("0001")
    check("repo_restore_rev", restored["rev"] == "0001", str(restored))
    check("repo_restore_bytes", proj.read_bytes() == b"AAAA", proj.read_bytes()[:8].hex())

    # restore 自快照可逆: proj 改为 CCCC(未快照) 再 restore 0001 → 应先把 CCCC 快照为 0003
    proj.write_bytes(b"CCCC")
    repo.restore("0001")
    hist2 = repo.history()
    check("repo_restore_autosnapshots_current",
          len(hist2) == 3 and hist2[-1]["sha256"] == _sha(b"CCCC"), str([h["rev"] for h in hist2]))
    check("repo_restore_final_bytes", proj.read_bytes() == b"AAAA", "")

    # ================= 2) 服务层: save 自快照 / deploy 打标记 / restore 停 worker =================
    async def svc_checks():
        d2 = Path(tempfile.mkdtemp(prefix="plcsvc_"))
        p2 = d2 / "20260622.project"
        p2.write_bytes(b"PROJ-V1")
        r2 = PlcVersionRepo(p2, d2 / "history", time_fn=_clock())
        fake = FakeIpc()
        fake.responses = {
            "write": {"path": "Application/Foo", "updated": ["implementation"], "saved": True},
            "compile": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
            "save": {"saved": True},
            "deploy": {"deployed": True, "boot_written": True, "started": False, "error_count": 0},
            "online_status": {"ready": True, "state": "stop", "reason": None},
        }
        svc = PlcProgramService(fake, allow_deploy=True, version_repo=r2, plc=FakePlc())

        await svc.save_pou("Application/Foo", None, "x:=1;", True)
        check("svc_save_true_snapshots", len(r2.history()) == 1, str(r2.history()))
        await svc.save_pou("Application/Foo", None, "x:=2;", False)
        check("svc_save_false_no_snapshot", len(r2.history()) == 1, "save=false 不应快照")
        await svc.save_pou("Application/Foo", None, "x:=3;", True)  # proj 文件未变 → 去重
        check("svc_save_true_dedup", len(r2.history()) == 1, "内容未变应去重")

        await svc.online_status()
        check("svc_online_op", ("online_status", {}, 120.0) in fake.calls, str(fake.calls))

        await svc.deploy()
        check("svc_deploy_op", any(c[0] == "deploy" and c[2] == 300.0 for c in fake.calls),
              str(fake.calls))
        check("svc_deploy_marks_deployed", r2.history()[-1]["deployed_at"] is not None, str(r2.history()))

        # 编译中止的下发(deployed=False, ok 仍 True) → 不打部署标记、不新增快照
        deployed_before = sum(1 for h in r2.history() if h["deployed_at"])
        fake.responses["deploy"] = {"deployed": False, "error_count": 2,
                                    "errors": [{"severity": "error", "text": "未定义变量 X"}],
                                    "reason": "编译未通过, 已中止下发"}
        try:
            await svc.deploy()
            res_abort = None
        except PLCDeployPreconditionError as exc:
            res_abort = exc.payload()
        check("svc_deploy_abort_no_mark",
              res_abort is not None and res_abort["downloaded"] is False
              and sum(1 for h in r2.history() if h["deployed_at"]) == deployed_before,
              str(r2.history()))

        # restore_version: 改 proj 为 V2 → 快照 0002; 还原 0001 应 await ipc.stop_worker() 并覆盖回 V1
        p2.write_bytes(b"PROJ-V2")
        await svc.save_pou("Application/Foo", None, "y:=1;", True)
        check("svc_v2_snapshot", len(r2.history()) == 2, str(r2.history()))
        await svc.restore_version("0001")
        check("svc_restore_stop_worker_called", fake.stop_worker_called == 1, str(fake.stop_worker_called))
        check("svc_restore_bytes", p2.read_bytes() == b"PROJ-V1", "")

        # restore 不存在的版本: 先校验 → KeyError, 不应停 worker(stop_worker 仍为 1)
        try:
            await svc.restore_version("9999")
            missing = False
        except KeyError:
            missing = True
        check("svc_restore_missing_keyerror", missing, "")
        check("svc_restore_missing_no_stop", fake.stop_worker_called == 1, str(fake.stop_worker_called))

        # F1: 接管态下 restore 被 stop 接管门拒绝(RuntimeError) → 不停 worker、不覆盖工程字节
        fake.manual_control = True
        bytes_before = p2.read_bytes()
        try:
            await svc.restore_version("0001")
            blocked = False
        except RuntimeError:
            blocked = True
        fake.manual_control = False
        check("svc_restore_manual_blocked", blocked, "接管态 restore 应抛 RuntimeError")
        check("svc_restore_manual_no_stop", fake.stop_worker_called == 1, str(fake.stop_worker_called))
        check("svc_restore_manual_bytes_intact", p2.read_bytes() == bytes_before, "")

    asyncio.run(svc_checks())

    # ================= 3) 路由层: 经 TestClient(sim) 验证门控/版本端点 =================
    d3 = Path(tempfile.mkdtemp(prefix="plcroute_"))
    p3 = d3 / "20260622.project"
    p3.write_bytes(b"ROUTE-V1")
    r3 = PlcVersionRepo(p3, d3 / "history", time_fn=_clock())
    r3.snapshot_if_changed(message="seed")  # 预置 0001

    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48499/eit_ptlc/sim/")
    with TestClient(app) as client:
        fake = FakeIpc()
        fake.responses = {
            "compile": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
            "save": {"saved": True},
            "deploy": {"deployed": True, "boot_written": True, "started": False, "error_count": 0},
            "online_status": {"ready": True, "state": "stop", "reason": None},
        }
        # allow_deploy=False → deploy 403
        app.state.plc_program = PlcProgramService(fake, allow_deploy=False, version_repo=r3)
        check("route_deploy_403_when_disabled", client.post("/api/plc/deploy").status_code == 403,
              str(client.post("/api/plc/deploy").status_code))

        # allow_deploy=True → deploy 200 + 打部署标记
        app.state.plc_program = PlcProgramService(
            fake, allow_deploy=True, version_repo=r3, plc=FakePlc())
        rr = client.post("/api/plc/deploy")
        check("route_deploy_200", rr.status_code == 200 and rr.json()["deployed"] is True, rr.text)
        check("route_deploy_recorded",
              any(c[0] == "deploy" and c[2] == 300.0 for c in fake.calls), str(fake.calls))

        rr = client.get("/api/plc/online_status")
        check("route_online_200", rr.status_code == 200 and rr.json()["ready"] is True, rr.text)

        rr = client.get("/api/plc/versions")
        vs = rr.json()
        check("route_versions_200", rr.status_code == 200 and len(vs) >= 1, rr.text)
        check("route_versions_deployed_mark", vs[-1]["deployed_at"] is not None, str(vs))

        rr = client.get("/api/plc/versions/0001/download")
        check("route_download_200", rr.status_code == 200 and rr.content == b"ROUTE-V1", str(rr.status_code))
        check("route_download_404", client.get("/api/plc/versions/9999/download").status_code == 404, "")

        rr = client.post("/api/plc/versions/snapshot", json={"message": "手动"})
        check("route_snapshot_dedup_200", rr.status_code == 200 and rr.json()["snapshotted"] is False, rr.text)

        rr = client.post("/api/plc/versions/0001/restore")
        check("route_restore_200", rr.status_code == 200 and rr.json()["rev"] == "0001", rr.text)
        check("route_restore_stop_worker", fake.stop_worker_called == 1, str(fake.stop_worker_called))
        check("route_restore_404", client.post("/api/plc/versions/9999/restore").status_code == 404, "")

        # F1: 接管态 restore → 503(RuntimeError 映射), 不停 worker、工程字节未覆盖
        fake.manual_control = True
        bytes_before = p3.read_bytes()
        rr = client.post("/api/plc/versions/0001/restore")
        check("route_restore_manual_503", rr.status_code == 503, f"{rr.status_code}: {rr.text}")
        check("route_restore_manual_no_stop", fake.stop_worker_called == 1, str(fake.stop_worker_called))
        check("route_restore_manual_bytes_intact", p3.read_bytes() == bytes_before, "")
        fake.manual_control = False

        # 服务未就绪(None) → 503
        app.state.plc_program = None
        check("route_versions_503_when_unset", client.get("/api/plc/versions").status_code == 503, "")

    print(f"\nPLC 工程版本/部署服务路由离线测试: 失败 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
