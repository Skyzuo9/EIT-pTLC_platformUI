"""CODESYS 文件-IPC 客户端
========================
功能:
    后端(FastAPI)侧驱动 InoProShop(CODESYS SP11) 常驻 worker 的 Python 客户端, 是
    tools/codesys-mcp/server.mjs 的 Python 等价. 懒启动一个带 UI 的 InoProShop 实例
    (其内跑 tools/codesys-mcp/worker_body.py), 经"请求/响应文件"与 worker 通信, 实现
    POU 读/写/编译/保存(及 Phase 2 的部署)等操作. worker_body.py 为唯一真源, 本客户端
    只注入 4 个常量后生成 worker_active.py, 不复制其逻辑.

协议(与 worker_body.py 约定一致):
    请求: <ipc_dir>/requests/<id>.req.json   ({"op":..., "args":{...}})
    响应: <ipc_dir>/responses/<id>.resp.json ({"ok":bool, "result"|"error":...})
    状态: <ipc_dir>/worker.status            (worker 心跳, state ∈ opening/ready/error/stopped)
    停止: <ipc_dir>/worker.stop              (存在即 worker 优雅退出并关闭 IDE)

关键约束:
    - SP11 必须带 UI (--noUI 下 projects.open 会 NPE), 故 spawn 不加 --noUI, 会弹 GUI 窗口
    - 同一 .project 同一时刻只能被一个 InoProShop 打开; 被占用时 worker 写 state=error,
      ensure_worker 如实抛出, 由路由层转 503 (写在内存, save 才落盘, 争用不损坏工程)
    - 阻塞型 spawn / 文件轮询全部经 asyncio.to_thread 执行, 不阻塞事件循环
    - 本客户端比 Node MCP 长命, 调用方(lifespan)必须在退出时 await shutdown(), 否则
      残留 InoProShop 进程占用工程
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import logging
import os
import secrets
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class CodesysDeployNotStartedError(RuntimeError):
    """Authorization/fingerprint failure proven to occur before worker login."""


# 独占 op(改内存/落盘/编译/部署)需抢 write.lock; 共享 op(读/列举/状态/在线探测)不抢锁 -> 写期间读仍可并发
_EXCLUSIVE_OPS = frozenset({"write", "create", "save", "compile", "generate_code", "deploy"})
_SESSION_STATUS_OPS = frozenset({"status"})
_DEPLOY_GUARD_BLOCKED_OPS = frozenset({
    "write", "create", "save", "compile", "generate_code", "deploy", "stop",
    "takeover", "release_takeover", "restore",
})
_DEPLOY_GUARD_PURPOSE_OPS = {
    "deploy": frozenset({"compile", "save", "deploy", "start_worker"}),
    "restore": frozenset({"stop"}),
}
_WORKER_PROTOCOL_VERSION = 3
_DEPLOY_AUTH_TTL_SEC = 60.0

# spawn 失败冷却: worker 报 error(典型=工程被人工 InoProShop 占用)后, 该时长内不再重复拉起 EXE。
# 无冷却时每次上层重试都弹一个 GUI 窗口再失败(弹窗风暴, 2026-07 真实事故); 与 server.mjs 同值。
_SPAWN_ERROR_COOLDOWN_SEC = 60.0

# 接管标志 TTL 逃生阀(F8): manual_control=true 且 updated_at 距今超过该时长 → 视为过期(未接管)+告警。
# 缺 updated_at 的旧格式 = 永不过期(接管是人类属主, 禁按 pid 存活自动失效 — 945dc6f 语义)。
# 与 worker_body.py MANUAL_CONTROL_TTL_SEC / server.mjs MANUAL_CONTROL_TTL_SEC 同值(秒)。
MANUAL_CONTROL_TTL_SEC = 86400

# 会话属主租约(session.owner)默认阈值; 与 server.mjs 的同名常量必须同值(跨语言镜像)。
# IDLE_RELEASE: 属主最近一次写类 op 距今超过该秒数即空闲, 可被其它自动方抢占;
#   须 > agent 两次 op 的正常间隔(含模型思考+编译等待), 否则还在干活的 agent 会被误抢。
# WAIT_TIMEOUT: 想抢的一方轮询阻塞的最长秒数, 超时抛忙(与编译超时同量级)。
# MAX_HOLD: 单个属主持有的硬上限(逃生阀), 防显式持有方崩溃后刷新器残留把实例钉死。
_SESSION_IDLE_RELEASE_SEC = 60.0
_SESSION_WAIT_TIMEOUT_SEC = 300.0
_SESSION_MAX_HOLD_SEC = 900.0
_SESSION_POLL_SEC = 0.15


def _as_float(value) -> float:
    """把可能缺失/非数的时间戳安全转 float; 失败返回 0.0(视为极旧, 利于判空闲/超时)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _valid_guard_token(value) -> bool:
    if not isinstance(value, str) or len(value) != 48:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _pid_alive(pid) -> bool:
    """判定 pid 进程是否存活(Windows: OpenProcess + GetExitCodeProcess==STILL_ACTIVE).

    功能:
        跨进程判活原语. 多客户端据 worker.status 里的 pid 判断共享 worker 是否在跑,
        免疫编译/部署等长阻塞操作(心跳期间无法刷新, 而 pid 始终可探)。
    参数:
        pid: 进程号(int; None/非数/<=0 视为不存活)
    返回:
        bool, True 表示进程仍在运行
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER is the documented "PID does not exist" case.
        # Access denied (for example an elevated InoProShop) and every unknown
        # query failure are treated as alive/unknown so no safety lock is stolen.
        error_code = int(kernel32.GetLastError())
        return error_code != 87
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class CodesysIpcClient:
    """驱动 InoProShop 常驻 worker 的文件-IPC 客户端."""

    def __init__(self, *, exe: str, profile: str, project, ipc_dir,
                 compile_category: str, plc_ip: str = "", poll_sec: float = 0.12,
                 ready_timeout: float = 180.0, idle_timeout: float = 120.0,
                 session_label: str = "fastapi",
                 session_idle_release: float = _SESSION_IDLE_RELEASE_SEC,
                 session_wait_timeout: float = _SESSION_WAIT_TIMEOUT_SEC,
                 session_max_hold: float = _SESSION_MAX_HOLD_SEC) -> None:
        """参数:
        exe: InoProShop.exe 绝对路径; profile: CODESYS profile 名;
        project: .project 工程绝对路径; ipc_dir: 文件 IPC 目录(与 MCP server.mjs 共享同一目录,
                 多客户端经 spawn.lock/write.lock + status.pid 协调共用同一个 InoProShop 实例);
        compile_category: 编译消息类别 GUID;
        plc_ip: 真机 PLC IP(取自 config.plc.url host); 注入 worker 供 op_deploy 按 IP 单播
                设活动路径(绕开 InoProShop 广播扫描)。空则 op_deploy 不设路径(依赖 GUI 已设)。
        poll_sec: worker 轮询间隔(注入 worker);
        ready_timeout: 首次冷启动等待 worker 就绪的最大秒数(InoProShop 启动+开工程较慢);
        idle_timeout: 注入 worker 的空闲超时秒数, worker 无请求超过该时长即关闭 InoProShop 释放工程锁;
                      0=常驻永不自关(人机共用一个窗口, 接管/释放换手; 关停走 stop_worker/codesys_shutdown)。
        session_label: 本客户端在 session.owner 里的展示标签(如 fastapi);
        session_idle_release/session_wait_timeout/session_max_hold: 会话属主租约阈值(秒),
                含义见模块常量 _SESSION_*; 与 server.mjs 同名阈值必须同值(跨语言镜像)。
        """
        self._exe = str(exe)
        self._profile = str(profile)
        self._project = str(Path(project))            # 绝对路径字符串, 供 projects.open
        self._ipc_dir = str(Path(ipc_dir))
        self._compile_category = str(compile_category)
        self._plc_ip = str(plc_ip)
        self._poll_sec = poll_sec
        self._ready_timeout = ready_timeout
        self._idle_timeout = idle_timeout
        self._req_dir = os.path.join(self._ipc_dir, "requests")
        self._resp_dir = os.path.join(self._ipc_dir, "responses")
        self._status_path = os.path.join(self._ipc_dir, "worker.status")
        self._stop_path = os.path.join(self._ipc_dir, "worker.stop")
        self._keeper_status_path = os.path.join(self._ipc_dir, "keeper.status")
        self._session_control_path = os.path.join(self._ipc_dir, "session_control.json")
        self._lease_path = os.path.join(self._ipc_dir, "lease.status")
        self._deploy_guard_path = os.path.join(self._ipc_dir, "deploy.guard.json")
        self._deploy_auth_dir = os.path.join(self._ipc_dir, "deploy-auth")
        self._physical_deploy_lock_path = os.path.join(
            self._ipc_dir, "deploy.physical.lock")
        self._worker_script = os.path.join(self._ipc_dir, "worker_active.py")
        self._spawn_lock_path = os.path.join(self._ipc_dir, "spawn.lock")   # 跨进程冷启动互斥
        self._write_lock_path = os.path.join(self._ipc_dir, "write.lock")   # 单写者租约
        self._session_owner_path = os.path.join(self._ipc_dir, "session.owner")  # 可抢占会话属主租约
        # worker_body.py 唯一真源: driver/ 的上级即包根, tools/codesys-mcp/ 在其下
        self._worker_body_path = (
            Path(__file__).resolve().parent.parent / "tools" / "codesys-mcp" / "worker_body.py"
        )
        self._worker_body_sha256 = hashlib.sha256(
            self._worker_body_path.read_bytes()
        ).hexdigest()
        self._child: Optional[subprocess.Popen] = None
        self._start_lock = asyncio.Lock()             # 串行化 spawn, 防并发重复启动(进程内)
        self._spawn_lock_token: Optional[str] = None
        # 会话属主租约状态: owner_id 每进程稳定唯一(跨主机不冲突); label 展示用; 阈值见构造参数。
        self._session_label = str(session_label)
        self._session_idle_release = float(session_idle_release)
        self._session_wait_timeout = float(session_wait_timeout)
        self._session_max_hold = float(session_max_hold)
        self._owner_id = "%s:%d:%s" % (self._safe_hostname(), os.getpid(), secrets.token_hex(4))
        self._session_token: Optional[str] = None     # 本客户端当前租约的最新 owner_token(供 release/refresh)
        self._session_acquired_at: Optional[float] = None
        self._session_stamp_lock = threading.Lock()   # 串行化本进程内对 session.owner 的写(前台 op 与后台刷新器)
        self._session_hold_depth = 0                  # own_session 可重入计数(>0 = 显式持有)
        self._session_refresher: Optional[asyncio.Task] = None  # 显式持有期间的后台 last_activity 刷新任务

    @staticmethod
    def _safe_hostname() -> str:
        try:
            return socket.gethostname() or "host"
        except OSError:
            return "host"

    # ------------------------------------------------------------------
    # 公共异步接口
    # ------------------------------------------------------------------

    async def ensure_worker(self, *, guard_token: str | None = None) -> None:
        """确保 worker 在线就绪; 不在线则懒启动(冷启动 ~14s + 弹 GUI 窗口)."""
        if self._worker_alive():
            return
        self._assert_deploy_guard_allows("start_worker", guard_token)
        async with self._start_lock:
            if self._worker_alive():               # 双检: 等锁期间可能已被其它协程启动
                return
            self._assert_deploy_guard_allows("start_worker", guard_token)
            await asyncio.to_thread(self._spawn_and_wait_ready)

    async def call(
        self,
        op: str,
        args: Optional[dict] = None,
        timeout: float = 60.0,
        *,
        guard_token: str | None = None,
    ):
        """发起一次 IPC 调用并返回 worker 的 result.

        参数:
            op: 操作名(对应 worker_body.OPS 的 key, 如 list/read/write/compile/save);
            args: 操作参数; timeout: 等待响应的最大秒数(编译/部署需给大值)。
        返回:
            worker 返回的 result 对象。
        失败:
            worker 报错(resp.ok=False) → RuntimeError(含 error+trace);
            超时 → TimeoutError; worker 启动失败 → 由 ensure_worker 抛出;
            写锁被其它客户端占用且等待超时 → RuntimeError。
        """
        await asyncio.to_thread(self._assert_not_manual_control, op)
        await asyncio.to_thread(self._assert_deploy_guard_allows, op, guard_token)
        if op in _EXCLUSIVE_OPS:
            # 会话属主门: 写类 op 抢占/盖章 session.owner(裸调用即自动持有); 被存活外部属主
            # 独占时按前提3阻塞轮询至 WAIT_TIMEOUT 超时抛忙。显式持有(own_session)时命中"属我"
            # 分支只刷新 last_activity。读/list/status 不入此门, 保持与 write.lock 同作用域。
            await asyncio.to_thread(self._claim_or_wait, op, self._session_wait_timeout)
        await self.ensure_worker(guard_token=guard_token)
        if op in _EXCLUSIVE_OPS:
            return await asyncio.to_thread(
                self._call_with_lease, op, args, timeout, True, guard_token)
        if op in _SESSION_STATUS_OPS:
            return await asyncio.to_thread(
                self._call_blocking, op, args, timeout, guard_token)
        return await asyncio.to_thread(
            self._call_with_lease, op, args, timeout, False, guard_token)

    def deploy_guard_snapshot(self) -> dict:
        """Read the persistent cross-process project/deploy guard without starting the IDE."""
        guard = self._read_json(self._deploy_guard_path)
        if guard:
            return guard
        if os.path.exists(self._deploy_guard_path):
            return {"state": "corrupt", "purpose": "unreadable", "fail_closed": True}
        return {}

    def physical_deploy_lock_snapshot(self) -> dict:
        """Read the persistent physical-login barrier without mutating it."""
        lock = self._read_json(self._physical_deploy_lock_path)
        if lock:
            return lock
        if os.path.exists(self._physical_deploy_lock_path):
            return {"state": "corrupt", "purpose": "unreadable", "fail_closed": True}
        return {}

    @property
    def target_plc_ip(self) -> str:
        return self._plc_ip

    @property
    def worker_body_sha256(self) -> str:
        return self._worker_body_sha256

    def begin_deploy_guard(self, *, purpose: str = "deploy", timeout: float = 5.0) -> str:
        """Atomically reserve the whole project transaction across Python/Node clients.

        The guard is deliberately persistent: process death never makes a physical
        deployment safe to retry.  Only a proven pre-download rollback, successful
        READY completion, or explicit operator reconciliation may clear it.
        """
        self._assert_not_manual_control(purpose)
        self._assert_worker_body_unchanged()
        os.makedirs(self._ipc_dir, exist_ok=True)
        lock_token = self._acquire_write_lock(timeout)
        try:
            if os.path.exists(self._physical_deploy_lock_path):
                raise RuntimeError(
                    "a previous physical deploy is still in-flight or outcome-unknown")
            existing = self._read_json(self._deploy_guard_path)
            if existing:
                raise RuntimeError(
                    "PLC project transaction is guarded by %s since %s; reconcile it before %s"
                    % (existing.get("purpose", "unknown"), existing.get("created_at"), purpose)
                )
            token = secrets.token_hex(24)
            payload = {
                "state": "active",
                "purpose": purpose,
                "token": token,
                "owner": "fastapi",
                "owner_pid": os.getpid(),
                "created_at": time.time(),
                "updated_at": time.time(),
                "project": self._canonical_project(),
                "plc_ip": self._plc_ip,
                "protocol_version": _WORKER_PROTOCOL_VERSION,
                "worker_body_sha256": self._worker_body_sha256,
            }
            os.makedirs(self._ipc_dir, exist_ok=True)
            try:
                fd = os.open(
                    self._deploy_guard_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError as exc:
                raise RuntimeError("PLC project transaction guard already exists") from exc
            try:
                os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            finally:
                os.close(fd)
            return token
        finally:
            self._release_write_lock(lock_token)

    def end_deploy_guard(self, token: str) -> None:
        """Release a guard only when the caller proves ownership of the same token."""
        lock_token = self._acquire_write_lock(5.0)
        barrier_token = None
        try:
            barrier_token = self._acquire_guard_change_barrier(force=False)
            guard = self._read_json(self._deploy_guard_path) or {}
            if not guard:
                if os.path.exists(self._deploy_guard_path):
                    raise RuntimeError("PLC project transaction guard is unreadable; fail-closed")
                return
            if (not token or guard.get("token") != token
                    or guard.get("state") != "active"):
                raise RuntimeError("PLC project transaction guard token mismatch")
            # Two-phase release: final worker authorization accepts only
            # state=active.  Persist releasing first, strictly remove our
            # physical barrier second, and delete the guard last.  A crash at
            # every boundary leaves a fail-closed, reconcilable marker.
            releasing = dict(guard)
            releasing.update({
                "state": "releasing",
                "release_started_at": time.time(),
                "release_owner_pid": os.getpid(),
            })
            self._write_json_atomic(self._deploy_guard_path, releasing)
            removed = self._remove_lock_if_owned(
                self._physical_deploy_lock_path, barrier_token)
            if not removed or os.path.exists(self._physical_deploy_lock_path):
                raise RuntimeError(
                    "deploy guard is releasing but its physical barrier could not be removed")
            barrier_token = None
            os.remove(self._deploy_guard_path)
            if os.path.exists(self._deploy_guard_path):
                raise RuntimeError("PLC project transaction guard deletion was not confirmed")
        finally:
            if barrier_token:
                removed = self._remove_lock_if_owned(
                    self._physical_deploy_lock_path, barrier_token)
                if os.path.exists(self._physical_deploy_lock_path):
                    self._release_write_lock(lock_token)
                    raise RuntimeError(
                        "guard release failed and its physical deploy barrier remains; reconciliation required")
            self._release_write_lock(lock_token)

    def force_clear_deploy_guard(
        self,
        *,
        reason: str,
        expected_token: str,
        expected_purpose: str,
        expected_state: str,
        expected_project: str,
        expected_plc_ip: str,
        expected_protocol_version: int,
        expected_worker_body_sha256: str | None,
    ) -> dict:
        """Clear a persistent guard after the service has completed explicit reconciliation."""
        if not str(reason or "").strip():
            raise ValueError("clearing the PLC deploy guard requires an audit reason")
        if not _valid_guard_token(expected_token):
            raise ValueError("clearing the PLC deploy guard requires its exact valid token")
        if expected_purpose not in _DEPLOY_GUARD_PURPOSE_OPS:
            raise ValueError("clearing the PLC deploy guard requires its exact purpose")
        if expected_state not in {"active", "releasing"}:
            raise ValueError("reconciled guard state is not recoverable")
        if expected_project != self._canonical_project() or expected_plc_ip != self._plc_ip:
            raise ValueError("reconciled guard is not bound to this project and PLC")
        try:
            expected_protocol_version = int(expected_protocol_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("reconciled guard protocol fingerprint is invalid") from exc
        if expected_protocol_version <= 0:
            raise ValueError("reconciled guard protocol fingerprint is invalid")
        if expected_worker_body_sha256 is not None:
            body_sha = str(expected_worker_body_sha256).lower()
            if len(body_sha) != 64:
                raise ValueError("reconciled guard worker-build fingerprint is invalid")
            try:
                int(body_sha, 16)
            except ValueError as exc:
                raise ValueError("reconciled guard worker-build fingerprint is invalid") from exc
            expected_worker_body_sha256 = body_sha
        lock_token = self._acquire_write_lock(5.0)
        barrier_token = None
        try:
            barrier_token = self._acquire_guard_change_barrier(force=True)
            guard = self._read_json(self._deploy_guard_path) or {}
            guard_exists = os.path.exists(self._deploy_guard_path)
            if not guard_exists:
                raise RuntimeError("PLC deploy guard changed before reconciliation; nothing was cleared")
            if not guard:
                raise RuntimeError("PLC deploy guard is unreadable; refusing unbound reconciliation")
            if (guard.get("token") != expected_token
                    or guard.get("purpose") != expected_purpose
                    or guard.get("state") != expected_state):
                raise RuntimeError(
                    "PLC deploy guard changed before reconciliation; refusing to clear a newer guard")
            fingerprint_ok = (
                guard.get("project") == expected_project
                and str(guard.get("plc_ip", "")) == expected_plc_ip
                and int(guard.get("protocol_version", 0) or 0) == expected_protocol_version
                and guard.get("worker_body_sha256") == expected_worker_body_sha256
            )
            if not fingerprint_ok:
                raise RuntimeError(
                    "PLC deploy guard fingerprint changed before reconciliation")
            audit = dict(guard)
            audit.update({
                "state": "cleared",
                "cleared_at": time.time(),
                "cleared_by_pid": os.getpid(),
                "clear_reason": str(reason),
            })
            if guard.get("state") == "active":
                releasing = dict(guard)
                releasing.update({
                    "state": "releasing",
                    "release_started_at": time.time(),
                    "release_owner_pid": os.getpid(),
                    "release_reason": str(reason),
                })
                self._write_json_atomic(self._deploy_guard_path, releasing)
            removed = self._remove_lock_if_owned(
                self._physical_deploy_lock_path, barrier_token)
            if not removed or os.path.exists(self._physical_deploy_lock_path):
                raise RuntimeError(
                    "deploy guard is releasing but reconciliation barrier could not be removed")
            barrier_token = None
            os.remove(self._deploy_guard_path)
            if os.path.exists(self._deploy_guard_path):
                raise RuntimeError("PLC deploy guard deletion was not confirmed")
            # Record completion only after both the physical barrier and the
            # persistent guard are confirmed absent.  A pre-clear audit would
            # falsely claim success if either delete failed.
            self._write_json_atomic(
                os.path.join(self._ipc_dir, "deploy.guard.last-cleared.json"), audit)
            return guard
        finally:
            if barrier_token:
                removed = self._remove_lock_if_owned(
                    self._physical_deploy_lock_path, barrier_token)
                if os.path.exists(self._physical_deploy_lock_path):
                    self._release_write_lock(lock_token)
                    raise RuntimeError(
                        "deploy guard release failed and its physical barrier remains; reconciliation required")
            self._release_write_lock(lock_token)

    def force_clear_orphan_physical_lock(
        self,
        *,
        reason: str,
        expected_owner_token: str,
    ) -> dict:
        """Archive a dead physical-lock orphan after explicit PLC/version reconciliation."""
        if not str(reason or "").strip():
            raise ValueError("clearing an orphan physical deploy lock requires an audit reason")
        if not isinstance(expected_owner_token, str) or len(expected_owner_token) != 32:
            raise ValueError("orphan physical deploy lock owner token is invalid")
        try:
            int(expected_owner_token, 16)
        except ValueError as exc:
            raise ValueError("orphan physical deploy lock owner token is invalid") from exc
        lock_token = self._acquire_write_lock(5.0)
        barrier_token = None
        previous = self.physical_deploy_lock_snapshot()
        try:
            if previous.get("owner_token") != expected_owner_token:
                raise RuntimeError(
                    "physical deploy lock changed before reconciliation")
            barrier_token = self._acquire_guard_change_barrier(
                force=True, expected_existing_token=expected_owner_token)
            audit = dict(previous)
            audit.update({
                "state": "reconciled",
                "reconciled_at": time.time(),
                "reconciled_by_pid": os.getpid(),
                "reconcile_reason": str(reason),
            })
            removed = self._remove_lock_if_owned(
                self._physical_deploy_lock_path, barrier_token)
            if not removed or os.path.exists(self._physical_deploy_lock_path):
                raise RuntimeError(
                    "orphan physical deploy reconciliation barrier could not be removed")
            barrier_token = None
            # Like guard reconciliation, write the completed audit only after
            # the replacement barrier is confirmed absent.
            self._write_json_atomic(
                os.path.join(self._ipc_dir, "deploy.physical.last-reconciled.json"), audit)
            return previous
        finally:
            if barrier_token:
                removed = self._remove_lock_if_owned(
                    self._physical_deploy_lock_path, barrier_token)
                if os.path.exists(self._physical_deploy_lock_path):
                    self._release_write_lock(lock_token)
                    raise RuntimeError(
                        "orphan physical deploy reconciliation barrier remains; reconciliation required")
            self._release_write_lock(lock_token)

    async def authorized_deploy(
        self,
        *,
        expected_sha256: str,
        commit_seq: int,
        expected_plc_ip: str,
        guard_token: str,
        timeout: float = 300.0,
    ) -> dict:
        """Issue a short-lived, one-time authorization bound to worker/project/PLC/commit."""
        try:
            self._assert_worker_body_unchanged()
        except Exception as exc:
            raise CodesysDeployNotStartedError(str(exc)) from exc
        sha = str(expected_sha256 or "").lower()
        if len(sha) != 64:
            raise CodesysDeployNotStartedError("expected_sha256 must be a 64-character SHA-256")
        try:
            int(sha, 16)
        except ValueError as exc:
            raise CodesysDeployNotStartedError("expected_sha256 is not hexadecimal") from exc
        seq = int(commit_seq)
        if seq <= 0:
            raise CodesysDeployNotStartedError("commit_seq must be positive")
        target_ip = str(expected_plc_ip or "").strip()
        if not target_ip or target_ip != self._plc_ip:
            raise CodesysDeployNotStartedError(
                "expected PLC IP does not match configured CODESYS target (%r != %r)"
                % (target_ip, self._plc_ip)
            )
        try:
            self._assert_deploy_guard_allows("deploy", guard_token)
        except Exception as exc:
            raise CodesysDeployNotStartedError(str(exc)) from exc
        guard = self._read_json(self._deploy_guard_path) or {}
        if not guard_token or guard.get("token") != guard_token:
            raise CodesysDeployNotStartedError(
                "authorized deploy requires ownership of the active deploy guard")

        try:
            await self.ensure_worker(guard_token=guard_token)
            status = self._read_live_status() or {}
        except Exception as exc:
            raise CodesysDeployNotStartedError(
                "CODESYS worker is not safely attachable; download not started: %s" % exc
            ) from exc
        instance_id = status.get("instance_id")
        if not instance_id:
            raise CodesysDeployNotStartedError(
                "worker has no instance_id; restart it before deployment")
        nonce = secrets.token_hex(24)
        now = time.time()
        authorization = {
            "nonce": nonce,
            "issued_at": now,
            "expires_at": now + _DEPLOY_AUTH_TTL_SEC,
            "worker_instance_id": instance_id,
            "guard_token": guard_token,
            "expected_sha256": sha,
            "expected_plc_ip": target_ip,
            "commit_seq": seq,
            "protocol_version": _WORKER_PROTOCOL_VERSION,
            "worker_body_sha256": self._worker_body_sha256,
        }
        os.makedirs(self._deploy_auth_dir, exist_ok=True)
        pending = os.path.join(self._deploy_auth_dir, nonce + ".pending.json")
        try:
            fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise CodesysDeployNotStartedError("deploy authorization nonce collision") from exc
        try:
            os.write(fd, json.dumps(authorization).encode("utf-8"))
        finally:
            os.close(fd)
        try:
            return await self.call(
                "deploy", {"authorization": authorization}, timeout,
                guard_token=guard_token,
            )
        except BaseException:
            self._revoke_deploy_authorization(nonce, reason="client_call_failed_or_cancelled")
            raise

    def session_snapshot(self) -> dict:
        """Return session/control state without starting InoProShop."""
        control = self._read_json(self._session_control_path) or {}
        worker = self._read_status() or {}
        keeper = self._read_json(self._keeper_status_path) or {}
        lease = self._read_json(self._lease_path) or {}
        deploy_guard = self.deploy_guard_snapshot()
        worker_alive = self._worker_alive()
        keeper_alive = _pid_alive(keeper.get("pid"))
        lease_active = (
            lease.get("state") == "active" and _pid_alive(lease.get("pid"))
        )
        owner = self._read_json(self._session_owner_path) or {}
        owner_alive = _pid_alive(owner.get("pid")) if owner else False
        owner_idle_sec = (
            round(time.time() - _as_float(owner.get("last_activity")), 3)
            if owner else None
        )
        owned = self._owner_is_held(owner)          # 存活且新近活跃 = 正被会话独占中
        return {
            "manual_control": bool(control.get("manual_control")),
            "control": control,
            "worker": worker,
            "worker_alive": worker_alive,
            "keeper": keeper,
            "keeper_alive": keeper_alive,
            "lease": lease,
            "lease_active": lease_active,
            "owner": owner,
            "owned": owned,
            "owner_alive": owner_alive,
            "owner_idle_sec": owner_idle_sec,
            "deploy_guard": deploy_guard,
            "deploy_guard_active": bool(deploy_guard),
            "ipc_dir": self._ipc_dir,
            "project": self._project,
            "idle_timeout": self._idle_timeout,
        }

    def takeover(self, *, by: str = "operator", reason: str = "") -> dict:
        self._assert_deploy_guard_allows("takeover")
        payload = {
            "manual_control": True,
            "owner": by or "operator",
            "reason": reason or "upper-ui takeover",
            "updated_at": time.time(),
            "updated_by": by or "operator",
        }
        self._write_json_atomic(self._session_control_path, payload)
        return self.session_snapshot()

    def release_takeover(self, *, by: str = "operator") -> dict:
        self._assert_deploy_guard_allows("release_takeover")
        payload = {
            "manual_control": False,
            "owner": "shared",
            "reason": "released",
            "updated_at": time.time(),
            "updated_by": by or "operator",
        }
        self._write_json_atomic(self._session_control_path, payload)
        return self.session_snapshot()

    # ------------------------------------------------------------------
    # 会话属主租约(session.owner): 可抢占的会话级独占
    # ------------------------------------------------------------------
    # 与人工接管(manual_control/takeover)正交: 那是"人类属主挡所有自动方"; 这里是"某个自动方
    # (agent/后端)临时独占共享实例, 挡其它自动方的写类 op"。两种持有姿势共用同一份 session.owner,
    # 差别只在谁刷新 last_activity:
    #   - 自动持有(默认): 每个写类 op 经 call() -> _claim_or_wait 原子盖章 + 刷新 last_activity,
    #     裸调用即持有; 最后一次 op 后 IDLE_RELEASE 秒空闲即可被抢占。VS Code agent 无需懂 session。
    #   - 显式持有(own_session/acquire_session): 抢占后启后台刷新器每 ~T/2 刷 last_activity, 免于
    #     空闲抢占, 直到显式 release / 进程死亡 / 超 MAX_HOLD。供后端已知事务与 agent 长事务。
    # 抢占判定与原子夺锁完全沿用 write.lock 的 _pid_alive + owner_token 陈旧回收范式(见 _claim_or_wait)。

    def _owner_is_held(self, owner: Optional[dict]) -> bool:
        """判定 session.owner 是否"被存活属主实际持有中"(= 不可被抢占)。

        持有 = 记录存在 且 属主 pid 存活 且 未空闲超阈(last_activity 在 IDLE_RELEASE 内)
             且 未超持有硬上限(acquired_at 在 MAX_HOLD 内)。任一不满足即视为可抢占。
        """
        if not owner:
            return False
        if not _pid_alive(owner.get("pid")):
            return False
        now = time.time()
        if now - _as_float(owner.get("last_activity")) > self._session_idle_release:
            return False
        if now - _as_float(owner.get("acquired_at")) > self._session_max_hold:
            return False
        return True

    def _new_owner_payload(self):
        """构造一份新的 session.owner 内容 + 其 owner_token(每次盖章换新 token, 使空闲抢占无 TOCTOU)。

        acquired_at 首次盖章设为当下并保持(供 MAX_HOLD 逃生阀); last_activity 每次刷新为当下。
        必须在持有 _session_stamp_lock 时调用(读写 self._session_acquired_at)。返回 (payload, token)。
        """
        now = time.time()
        if self._session_acquired_at is None:
            self._session_acquired_at = now
        token = secrets.token_hex(16)
        payload = {
            "owner_id": self._owner_id,
            "label": self._session_label,
            "pid": os.getpid(),
            "acquired_at": self._session_acquired_at,
            "last_activity": now,
            "owner_token": token,
        }
        return payload, token

    def _claim_or_wait(self, op: str, wait_timeout: float) -> None:
        """写类 op 的会话属主门(同步, 经 to_thread 调用): 抢占/盖章 session.owner, 忙则阻塞至超时。

        - 空闲(无文件/死属主/空闲超阈/超 MAX_HOLD): O_EXCL 原子夺得并写入本客户端租约;
        - 已属我: 仅刷新 last_activity(短路);
        - 被存活外部属主独占: 轮询等待其空闲/释放/死亡, 超过 wait_timeout 抛 RuntimeError(忙)。
        沿用 _acquire_write_lock 的 O_EXCL + owner_token 陈旧回收范式。
        失败:
            RuntimeError: 等待超时(实例正被他方独占), 或陈旧租约无有效 token 无法回收。
        """
        # 本门跑在 ensure_worker 之前(见 call), 首次调用时 ipc 目录可能尚未由 spawn 创建
        os.makedirs(self._ipc_dir, exist_ok=True)
        deadline = time.time() + wait_timeout
        while True:
            try:
                fd = os.open(self._session_owner_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                held = self._read_json(self._session_owner_path)
                if held and held.get("owner_id") == self._owner_id:
                    self._refresh_owner()          # 属我: 刷新 last_activity 即可
                    return
                if not self._owner_is_held(held):
                    # 可抢占: 按文件里记录的 owner_token 删旧租约再重试夺锁。死/空闲属主删不掉自己;
                    # 若属主刚 restamp 换了 token, token 不匹配 -> 删除失败 -> 重评(天然消解 TOCTOU)。
                    stale_token = (held or {}).get("owner_token")
                    if stale_token and self._remove_lock_if_owned(
                        self._session_owner_path, stale_token
                    ):
                        continue
                    if time.time() > deadline:
                        raise RuntimeError(
                            "无法抢占 PLC 会话属主(陈旧租约无有效 token 或刚被刷新); 等待 %ss 超时"
                            % wait_timeout)
                    time.sleep(_SESSION_POLL_SEC)
                    continue
                if time.time() > deadline:
                    raise RuntimeError(
                        "PLC 实例正被 %s 会话独占(op=%s); 等待 %ss 超时"
                        % ((held or {}).get("label", "?"), op, wait_timeout))
                time.sleep(_SESSION_POLL_SEC)
            else:
                # O_EXCL 夺得空闲: 写入本客户端租约(全新 acquired_at)
                with self._session_stamp_lock:
                    self._session_acquired_at = None
                    payload, token = self._new_owner_payload()
                    try:
                        os.write(fd, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                    finally:
                        os.close(fd)
                    self._session_token = token
                return

    def _refresh_owner(self) -> None:
        """刷新本客户端 session.owner 的 last_activity(同步)。仅当仍属我时刷新, 否则静默返回(已被抢占)。"""
        with self._session_stamp_lock:
            held = self._read_json(self._session_owner_path)
            if not held or held.get("owner_id") != self._owner_id:
                return
            payload, token = self._new_owner_payload()
            self._write_json_atomic(self._session_owner_path, payload)
            self._session_token = token

    def _release_owner(self) -> None:
        """释放本客户端持有的 session.owner(同步): 按最新 owner_token 比对删除, 不误删继任者。"""
        with self._session_stamp_lock:
            token = self._session_token
            self._session_token = None
            self._session_acquired_at = None
        if token:
            self._remove_lock_if_owned(self._session_owner_path, token)

    async def _session_refresh_loop(self) -> None:
        """显式持有期间的后台刷新循环: 每 IDLE_RELEASE/2 刷 last_activity, 使会话免于空闲抢占。

        间隔必须严格小于 IDLE_RELEASE(取其半), 否则两次刷新之间属主会"显得空闲"而被误抢。
        """
        interval = max(0.05, self._session_idle_release / 2.0)
        while True:
            await asyncio.sleep(interval)
            try:
                await asyncio.to_thread(self._refresh_owner)
            except Exception:
                # 瞬时错误不杀刷新器(否则会话会被误判空闲抢占); 下轮继续刷
                log.exception("[plc] 会话属主刷新失败(忽略, 下轮重试)")

    def _start_session_refresher(self) -> None:
        if self._session_refresher is not None and not self._session_refresher.done():
            return
        self._session_refresher = asyncio.create_task(self._session_refresh_loop())

    def _stop_session_refresher(self) -> None:
        task = self._session_refresher
        self._session_refresher = None
        if task is not None and not task.done():
            task.cancel()

    async def acquire_session(self, *, label: str | None = None,
                              wait_timeout: float | None = None) -> None:
        """显式抢占并独占共享实例一段会话(阻塞至取得或超时), 并启后台刷新器免于空闲抢占。

        参数:
            label: 覆盖本次持有的展示标签(如 'agent:xxx'); wait_timeout: 覆盖默认等待上限(秒)。
        失败:
            RuntimeError: 被他方独占且等待超时。
        """
        if label:
            self._session_label = str(label)
        wt = self._session_wait_timeout if wait_timeout is None else float(wait_timeout)
        await asyncio.to_thread(self._claim_or_wait, "acquire", wt)
        self._start_session_refresher()

    async def release_session(self) -> None:
        """释放显式持有的会话(停刷新器 + 清 session.owner)。"""
        self._stop_session_refresher()
        await asyncio.to_thread(self._release_owner)

    @asynccontextmanager
    async def own_session(self, label: str | None = None, *,
                          wait_timeout: float | None = None):
        """把一段多步工程改动括成会话级独占: 块内别的自动方写类 op 被挡, 块退出即释放。可重入。

        用法:
            async with client.own_session(label="fastapi:symbol_export"):
                await client.call("read", ...); await client.call("write", ..., save=True)
        """
        self._session_hold_depth += 1
        if self._session_hold_depth == 1:
            try:
                await self.acquire_session(label=label, wait_timeout=wait_timeout)
            except BaseException:
                self._session_hold_depth -= 1
                raise
        try:
            yield
        finally:
            self._session_hold_depth -= 1
            if self._session_hold_depth == 0:
                await self.release_session()

    async def shutdown(self) -> None:
        """释放本地子进程句柄; 不停共享 worker(其它客户端可能在用, 由空闲超时收尾)。

        worker 现为多客户端共享守护进程: 单个后端退出不应关闭它/释放工程锁(会打断正在使用的 agent)。
        残留实例由 worker 自身空闲超时(idle_timeout)关闭。Windows 下 Popen 子进程不随父退出被回收, 故安全留存。
        本客户端若持有会话属主(session.owner), 退出前显式释放, 免得别的自动方等到 idle 才接管。
        """
        self._stop_session_refresher()
        try:
            await asyncio.to_thread(self._release_owner)
        except Exception:
            log.exception("[plc] 退出时释放会话属主失败(忽略, 属主进程消亡后自动失效)")
        self._child = None

    async def stop_worker(
        self, timeout: float = 30.0, *, guard_token: str | None = None,
    ) -> bool:
        """显式停止共享 worker(写 stop 哨兵并等其进程退出), 释放 .project 文件锁。

        仅供确需释放文件锁的路径使用(如版本还原要覆盖 .project); 常规退出走 shutdown()
        不停共享实例。idle_timeout=0 常驻模式下这是唯一的程序化关停途径。

        stop 契约:
            - 接管中不可停: manual_control=true 时抛 RuntimeError(restore 路由映射 503),
              防止关掉操作员正在手改的 InoProShop 窗口;
            - 活体进程(pid 存活, 含 opening/error 态)可停: 写哨兵 + 轮询 pid 消亡;
              opening 态等待上限放宽为 ready_timeout + timeout(哨兵要等其进主循环才被消费);
            - status 缺失但 spawn.lock 持有者存活 = 启动窗口: 拒停(RuntimeError), 稍后重试;
            - status 缺失且无活的 spawn.lock: 本就不在线, 返回 False;
            - 超时 = 取消停止: 回收哨兵后抛 TimeoutError(worker 结束长操作后不再被残留哨兵毒杀);
            - 已知残留洞(不修): 接管门挡不住绕过本客户端直写 worker.stop 哨兵的第三方 —
              worker 主循环先消费哨兵后查接管冻结(见 worker_body.py 主循环)。

        返回:
            bool, True=worker 已停(或等待期间自行退出); False=本就不在线, 无需停。
        失败:
            RuntimeError: 接管中, 或 worker 正在启动窗口内;
            TimeoutError: worker 在线但超时未退出(可能在长编译/部署中, 或 IDE 弹了模态
              对话框); 哨兵已回收, 停止已取消。
        """
        return await asyncio.to_thread(
            self._stop_worker_blocking, timeout, guard_token)

    def _stop_worker_blocking(
        self, timeout: float, guard_token: str | None = None,
    ) -> bool:
        # 接管门: stop 是 call() 之外的第二个入口, 同样不可绕过接管(945dcf6 只把门装在 call 一条路;
        # 无门则版本还原会当面关掉操作员已接管的 InoProShop 窗口, 未保存手改丢失)
        self._assert_not_manual_control("stop")
        self._assert_deploy_guard_allows("stop", guard_token)
        status = self._read_live_status()
        if status is None:
            # 启动窗口: spawn 胜者拉起前先删 worker.status(本文件与 server.mjs 皆如此), 此刻
            # status 缺失但 InoProShop 正在启动。放行还原会覆盖一个即将被 IDE 锁定的 .project
            # (PermissionError, 或还原结果被 IDE 首次 save 静默冲掉) → 拒停, 让调用方稍后重试。
            held = self._read_json(self._spawn_lock_path)
            if held and _pid_alive(held.get("pid")):
                raise RuntimeError(
                    "worker 正在启动(spawn.lock 持有者 pid=%s 存活), 稍后重试" % held.get("pid"))
            return False
        pid = status.get("pid")
        if status.get("state") == "opening":
            # opening = InoProShop 正在开工程(冷启动 ~14s): 哨兵要等 worker 进主循环才被消费,
            # 等待上限放宽为 ready_timeout + timeout
            timeout = self._ready_timeout + timeout
        self._write_json_atomic(
            self._stop_path,
            {"requested_at": time.time(), "owner_pid": os.getpid(),
             "deploy_guard_token": guard_token},
        )
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                # 等进程真正退出(而非仅 status=stopped): .project 文件锁随进程消亡才释放
                if not _pid_alive(pid):
                    return True
                time.sleep(0.2)
        finally:
            # 超时=取消停止: 回收哨兵。不回收则 worker 结束当前长操作(如 300s 部署)后看到残留
            # 哨兵仍会退出 → 延迟毒杀操作员窗口(用户收到超时报错以为"什么都没发生")。
            # 成功路径 worker 已自行消费哨兵, 此处 _safe_unlink 为 no-op; 意外异常路径同样回收。
            self._safe_unlink(self._stop_path)
        raise TimeoutError("等待 worker 停止超时(%ss); InoProShop 可能在长操作或弹了对话框" % timeout)

    # ------------------------------------------------------------------
    # 内部同步实现 (全部经 to_thread 调用)
    # ------------------------------------------------------------------

    def _read_live_status(self) -> Optional[dict]:
        """读 worker.status 并核 pid 存活: 活体(不论 state)返回 status dict, 否则 None。

        全部「在线」谓词的单一收编点(session_snapshot / _worker_alive / _stop_worker_blocking /
        _wait_worker_ready 四处共用; 跨语言镜像: server.mjs 的 readLiveStatus)。
        「就绪可用」判定 = _read_live_status() 且 state=="ready"(见 _worker_alive);
        stop 用更宽的「活体(含 opening/error)」判定(见 _stop_worker_blocking)。
        """
        status = self._read_status()
        if status and _pid_alive(status.get("pid")):
            problems = []
            if status.get("project") != self._canonical_project():
                problems.append("project=%r" % status.get("project"))
            if str(status.get("plc_ip", "")) != self._plc_ip:
                problems.append("plc_ip=%r" % status.get("plc_ip"))
            if int(status.get("protocol_version", 0) or 0) != _WORKER_PROTOCOL_VERSION:
                problems.append("protocol_version=%r" % status.get("protocol_version"))
            if status.get("worker_body_sha256") != self._worker_body_sha256:
                problems.append("worker_body_sha256=%r" % status.get("worker_body_sha256"))
            if not status.get("instance_id"):
                problems.append("instance_id missing")
            if problems:
                raise RuntimeError(
                    "live CODESYS worker fingerprint mismatch; controlled restart required: "
                    + ", ".join(problems)
                )
            return status
        return None

    def _worker_alive(self) -> bool:
        """worker 在线可用 = 活体进程(_read_live_status)且 state==ready.

        进程无关: 共享 worker 可能由 MCP server.mjs 或其它后端进程拉起, 故不看本进程 _child,
        只看状态文件与其 pid 是否存活 -> 第二个客户端据此 attach 而非另拉一个 InoProShop。
        """
        status = self._read_live_status()
        return bool(status) and status.get("state") == "ready"

    def _raise_if_fresh_spawn_error(self) -> None:
        """新鲜的 worker error 状态(冷却期内)直接抛错, 不再拉起 EXE。

        典型场景: 工程正被人工打开的 InoProShop 占用 -> 每次 spawn 都弹一个 GUI 窗口、
        重试 ~5s 后失败。上层(agent/UI)的重试若每次都重新 spawn 即弹窗风暴。冷却期由
        error 状态文件的 ts 界定; 关闭占用方后等冷却到期(或下轮 spawn 成功清除)即恢复。
        """
        status = self._read_status()
        if status and status.get("state") == "error":
            age = time.time() - status.get("ts", 0)
            if 0 <= age < _SPAWN_ERROR_COOLDOWN_SEC:
                raise RuntimeError(
                    "InoProShop 启动冷却中(%.0fs 前打开工程失败, 剩余 %.0fs): %s\n"
                    "工程可能正被人工打开的 InoProShop 占用; 请在该窗口关闭工程(文件→关闭工程)后重试"
                    % (age, _SPAWN_ERROR_COOLDOWN_SEC - age, status.get("error", "")))

    def _spawn_and_wait_ready(self) -> None:
        """取 spawn 锁: 胜者 spawn InoProShop 并等就绪; 败者等共享 worker 就绪后 attach."""
        self._raise_if_fresh_spawn_error()   # 占用冷却: 冷却期内快速失败, 不弹新窗口
        os.makedirs(self._req_dir, exist_ok=True)
        os.makedirs(self._resp_dir, exist_ok=True)
        if self._acquire_spawn_lock():
            try:
                self._safe_unlink(self._status_path)
                self._safe_unlink(self._stop_path)
                self._build_worker_script()
                log.info("[CODESYS] 启动 InoProShop(带 UI) 常驻 worker: %s", self._exe)
                # 关键: 不能加 --noUI (SP11 下 projects.open 会 NPE); 参数列表直传避免引号问题
                self._child = subprocess.Popen(
                    [self._exe, "--profile=%s" % self._profile, "--runscript=%s" % self._worker_script],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self._wait_worker_ready(spawned=True)
            finally:
                self._release_spawn_lock()   # 仅释放自己持有的锁，不能误删下一任 owner
        else:
            self._wait_worker_ready(spawned=False)

    def _acquire_spawn_lock(self) -> bool:
        """O_EXCL 原子创建 spawn.lock. 返回 True=胜者(去 spawn), False=败者(去等就绪).

        持有者已死或锁过期(超 ready 上限)视为陈旧, 夺锁重试(原持有者 spawn 中途崩溃的回收)。
        """
        token = secrets.token_hex(16)
        # 活 PID 永不按年龄夺锁；owner token 防止旧 owner finally 误删下一任锁。
        payload = json.dumps({"pid": os.getpid(), "ts": time.time(), "owner_token": token})
        while True:
            try:
                fd = os.open(self._spawn_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                held = self._read_json(self._spawn_lock_path)
                stale = bool(held) and not _pid_alive(held.get("pid"))
                if stale:
                    stale_token = held.get("owner_token")
                    if not stale_token or not self._remove_lock_if_owned(
                        self._spawn_lock_path, stale_token
                    ):
                        return False
                    continue
                return False
            else:
                try:
                    os.write(fd, payload.encode("utf-8"))
                finally:
                    os.close(fd)
                self._spawn_lock_token = token
                return True

    def _release_spawn_lock(self) -> None:
        token = self._spawn_lock_token
        self._remove_lock_if_owned(self._spawn_lock_path, token or "")
        self._spawn_lock_token = None

    def _wait_worker_ready(self, spawned: bool) -> None:
        """轮询 worker.status 至 ready(pid 存活); error 仅在胜者自身或 spawn 锁已释放时才认定真失败."""
        deadline = time.time() + self._ready_timeout
        while time.time() < deadline:
            live = self._read_live_status()
            if live and live.get("state") == "ready":
                log.info("[CODESYS] worker 就绪")
                return
            status = live or self._read_status()   # error 态不要求 pid 存活(worker 报错后随即退出)
            if status and status.get("state") == "error":
                # 败者: 仅当 spawn 锁已被胜者删除(收尾完成)才认定真失败, 否则可能读到上一轮陈旧 error, 继续等
                if spawned or not os.path.exists(self._spawn_lock_path):
                    raise RuntimeError(
                        "worker 打开工程失败(可能工程正被其它 InoProShop 占用): "
                        + str(status.get("error", "")) + "\n" + str(status.get("trace", "")))
            if spawned and self._child is not None and self._child.poll() is not None:
                raise RuntimeError("InoProShop 进程提前退出, 未能就绪")
            time.sleep(0.5)
        raise TimeoutError("等待 worker 就绪超时(%ss)" % self._ready_timeout)

    def _build_worker_script(self) -> None:
        """读 worker_body.py, 注入运行目标常量, 生成 worker_active.py(worker_body 不被修改).

        与 MCP server.mjs 注入的常量集一致(IPC_DIR/PROJECT_PATH/POLL_SEC/COMPILE_CATEGORY/PLC_IP/
        IDLE_TIMEOUT_SEC), 确保两侧任一作为 spawn 胜者生成的 worker 行为一致(含 deploy 用 PLC_IP)。
        """
        body_bytes = self._worker_body_path.read_bytes()
        current_body_sha256 = hashlib.sha256(body_bytes).hexdigest()
        if current_body_sha256 != self._worker_body_sha256:
            raise RuntimeError(
                "worker_body.py changed after this backend started; restart the backend before spawning CODESYS"
            )
        body = body_bytes.decode("utf-8")
        header = (
            "# -*- coding: utf-8 -*-\n"
            'IPC_DIR = r"%s"\n' % self._ipc_dir
            + 'PROJECT_PATH = r"%s"\n' % self._project
            + "POLL_SEC = %s\n" % self._poll_sec
            + 'COMPILE_CATEGORY = "%s"\n' % self._compile_category
            + 'PLC_IP = r"%s"\n' % self._plc_ip
            + "IDLE_TIMEOUT_SEC = %s\n" % self._idle_timeout
            + "WORKER_PROTOCOL_VERSION = %d\n" % _WORKER_PROTOCOL_VERSION
            + "DEPLOY_AUTH_TTL_SEC = %s\n" % _DEPLOY_AUTH_TTL_SEC
            + 'WORKER_BODY_SHA256 = "%s"\n\n' % self._worker_body_sha256
        )
        with open(self._worker_script, "w", encoding="utf-8") as f:
            f.write(header + body)

    def _call_blocking(
        self, op: str, args: Optional[dict], timeout: float,
        guard_token: str | None = None,
    ):
        """原子写请求文件, 轮询响应文件直到拿到结果或超时."""
        rid = secrets.token_hex(8)
        req_path = os.path.join(self._req_dir, rid + ".req.json")
        tmp_path = req_path + ".tmp"
        request = {
            "op": op,
            "args": args or {},
            "client_pid": os.getpid(),
            "issued_at": time.time(),
        }
        if guard_token:
            request["deploy_guard_token"] = guard_token
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(request))
        os.replace(tmp_path, req_path)             # 原子落位, worker 读到的必是完整请求

        resp_path = os.path.join(self._resp_dir, rid + ".resp.json")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with open(resp_path, "r", encoding="utf-8") as f:
                    resp = json.loads(f.read())
            except FileNotFoundError:
                time.sleep(0.08)
                continue
            except ValueError:                     # 半写入(理论上 worker 已原子写, 防御性重试)
                time.sleep(0.08)
                continue
            self._safe_unlink(resp_path)
            self._safe_unlink(req_path)
            if not resp.get("ok"):
                trace = ("\n" + resp["trace"]) if resp.get("trace") else ""
                raise RuntimeError(str(resp.get("error", "")) + trace)
            return resp.get("result")
        # Best-effort cancellation: if the worker has not atomically claimed the
        # request, removing it prevents a later worker restart from executing it.
        self._safe_unlink(req_path)
        raise TimeoutError("操作 '%s' 超时(%ss); worker 可能在编译或无响应" % (op, timeout))

    def _call_exclusive(
        self, op: str, args: Optional[dict], timeout: float,
        guard_token: str | None = None,
    ):
        """独占 op: 先抢 write.lock(单写者), 再走普通 IPC 调用, finally 释放锁."""
        lock_token = self._acquire_write_lock(timeout)
        try:
            # Re-check under the same cross-process write lock; this closes the
            # race where a deploy guard is created after the caller's first check.
            self._assert_deploy_guard_allows(op, guard_token)
            return self._call_blocking(op, args, timeout, guard_token)
        finally:
            self._release_write_lock(lock_token)

    def _call_with_lease(
        self, op: str, args: Optional[dict], timeout: float, exclusive: bool,
        guard_token: str | None = None,
    ):
        self._begin_lease(op)
        try:
            if exclusive:
                return self._call_exclusive(op, args, timeout, guard_token)
            return self._call_blocking(op, args, timeout, guard_token)
        finally:
            self._end_lease(op)

    def _assert_not_manual_control(self, op: str) -> None:
        if op in _SESSION_STATUS_OPS:
            return
        control = self._read_json(self._session_control_path) or {}
        if not control.get("manual_control"):
            return
        updated_at = control.get("updated_at")
        if updated_at is not None:
            try:
                age = time.time() - float(updated_at)
            except (TypeError, ValueError):
                age = None
            if age is not None and age > MANUAL_CONTROL_TTL_SEC:
                # TTL 逃生阀(F8): 宿主/浏览器崩溃后 release 永不到来的标志, 24h 后自动失效
                log.warning(
                    "manual_control 标志已过期(%.1fh > TTL 24h), 视为未接管放行 op=%s",
                    age / 3600.0, op)
                return
        owner = control.get("owner") or "operator"
        reason = control.get("reason") or "manual control"
        raise RuntimeError(
            "PLC session is under manual control by %s; operation '%s' is blocked (%s)"
            % (owner, op, reason)
        )

    def _assert_deploy_guard_allows(
        self, op: str, guard_token: str | None = None,
    ) -> None:
        guard = self._read_json(self._deploy_guard_path) or {}
        if not guard:
            if os.path.exists(self._deploy_guard_path) and (
                op in _DEPLOY_GUARD_BLOCKED_OPS or op == "start_worker"
            ):
                raise RuntimeError(
                    "PLC project/deploy guard is unreadable; operation '%s' is blocked fail-closed"
                    % op
                )
            return
        structurally_valid = (
            guard.get("state") == "active"
            and _valid_guard_token(guard.get("token"))
            and guard.get("project") == self._canonical_project()
            and str(guard.get("plc_ip", "")) == self._plc_ip
            and int(guard.get("protocol_version", 0) or 0) == _WORKER_PROTOCOL_VERSION
            and guard.get("worker_body_sha256") == self._worker_body_sha256
        )
        if not structurally_valid and (
            op in _DEPLOY_GUARD_BLOCKED_OPS or op == "start_worker"
        ):
            raise RuntimeError(
                "PLC project/deploy guard fingerprint is invalid; operation '%s' is blocked fail-closed"
                % op
            )
        owns = bool(guard_token) and guard.get("token") == guard_token
        allowed_for_purpose = op in _DEPLOY_GUARD_PURPOSE_OPS.get(
            str(guard.get("purpose", "")), frozenset())
        if owns and allowed_for_purpose:
            return
        if op in _DEPLOY_GUARD_BLOCKED_OPS or op == "start_worker":
            raise RuntimeError(
                "PLC project/deploy transaction is active (%s); operation '%s' is blocked"
                % (guard.get("purpose", "unknown"), op)
            )

    def _canonical_project(self) -> str:
        return os.path.normcase(os.path.abspath(self._project))

    def project_sha256(self) -> str:
        """Hash the exact on-disk project currently bound to this IPC client."""
        h = hashlib.sha256()
        with open(self._project, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _assert_worker_body_unchanged(self) -> None:
        current = hashlib.sha256(self._worker_body_path.read_bytes()).hexdigest()
        if current != self._worker_body_sha256:
            raise RuntimeError(
                "worker_body.py changed after this backend started; restart backend and worker before deployment"
            )

    def _revoke_deploy_authorization(self, nonce: str, *, reason: str) -> bool:
        pending = os.path.join(self._deploy_auth_dir, nonce + ".pending.json")
        revoked = os.path.join(self._deploy_auth_dir, nonce + ".revoked.json")
        try:
            os.replace(pending, revoked)
        except OSError:
            return False  # already consumed/expired/missing: physical outcome may be unknown
        payload = self._read_json(revoked) or {"nonce": nonce}
        payload.update({"revoked_at": time.time(), "revoke_reason": reason})
        self._write_json_atomic(revoked, payload)
        return True

    def _begin_lease(self, op: str) -> None:
        payload = {
            "state": "active",
            "owner": "fastapi",
            "op": op,
            "pid": os.getpid(),
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        self._write_json_atomic(self._lease_path, payload)

    def _end_lease(self, op: str) -> None:
        previous = self._read_json(self._lease_path) or {}
        payload = {
            "state": "idle",
            "owner": previous.get("owner", "fastapi"),
            "last_op": op,
            "pid": os.getpid(),
            "started_at": previous.get("started_at"),
            "ended_at": time.time(),
            "updated_at": time.time(),
        }
        self._write_json_atomic(self._lease_path, payload)

    def _acquire_write_lock(self, timeout: float) -> str:
        """O_EXCL 原子创建 write.lock；活 owner 永不按时间夺锁，返回 owner token.

        失败:
            等待超过 timeout 仍未取得 → RuntimeError(另一个客户端正在写入)。
        """
        token = secrets.token_hex(16)
        payload = json.dumps({
            "owner_pid": os.getpid(), "ts": time.time(), "owner_token": token,
        })
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(self._write_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                held = self._read_json(self._write_lock_path)
                stale = bool(held) and not _pid_alive(held.get("owner_pid"))
                if stale:
                    stale_token = held.get("owner_token")
                    if stale_token and self._remove_lock_if_owned(
                        self._write_lock_path, stale_token
                    ):
                        continue
                    if time.time() > deadline:
                        raise RuntimeError("陈旧 write.lock 无有效 owner token，拒绝自动删除")
                    time.sleep(0.15)
                    continue
                if time.time() > deadline:
                    raise RuntimeError("另一个客户端正在写入(owner=%s); 写锁等待超时" % held.get("owner_pid"))
                time.sleep(0.15)
            else:
                try:
                    os.write(fd, payload.encode("utf-8"))
                finally:
                    os.close(fd)
                return token

    def _release_write_lock(self, token: str) -> None:
        self._remove_lock_if_owned(self._write_lock_path, token)

    def _acquire_guard_change_barrier(
        self,
        *,
        force: bool,
        expected_existing_token: str | None = None,
    ) -> str:
        """Own the same physical-login barrier used by the worker.

        Normal guard release never steals this lock.  Explicit reconciliation may
        archive a crash remnant, but only after its recorded process is no longer
        alive; an active worker may still be between its final check and login.
        """
        token = secrets.token_hex(16)
        payload = json.dumps({
            "owner": "fastapi",
            "purpose": "guard_change",
            "owner_pid": os.getpid(),
            "owner_token": token,
            "worker_body_sha256": self._worker_body_sha256,
            "created_at": time.time(),
        })
        while True:
            try:
                fd = os.open(
                    self._physical_deploy_lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError as exc:
                held = self._read_json(self._physical_deploy_lock_path)
                if not force:
                    raise RuntimeError(
                        "physical PLC deploy is in-flight or outcome-unknown; guard is retained"
                    ) from exc
                # O_EXCL creation precedes the owner's write by a few instructions.
                # An unreadable/partial file may therefore belong to a live worker;
                # never interpret it as stale and never steal it.
                if not held:
                    raise RuntimeError(
                        "physical PLC deploy lock is unreadable; retry reconciliation after it settles"
                    ) from exc
                physical_token = held.get("owner_token")
                if (expected_existing_token is not None
                        and physical_token != expected_existing_token):
                    raise RuntimeError(
                        "physical PLC deploy lock changed before reconciliation") from exc
                try:
                    int(str(physical_token), 16)
                    physical_token_valid = len(str(physical_token)) == 32
                    owner_pid = int(held.get("owner_pid"))
                except (TypeError, ValueError):
                    physical_token_valid = False
                    owner_pid = 0
                if not physical_token_valid or owner_pid <= 0:
                    raise RuntimeError(
                        "physical PLC deploy lock has no trustworthy owner identity; refusing to steal it"
                    ) from exc
                if _pid_alive(owner_pid):
                    raise RuntimeError(
                        "physical PLC deploy lock belongs to a live process; stop/wait for it before reconciliation"
                    ) from exc
                archive = os.path.join(
                    self._ipc_dir,
                    "deploy.physical.reconciled.%d.%s.json"
                    % (int(time.time() * 1000), secrets.token_hex(6)),
                )
                try:
                    os.replace(self._physical_deploy_lock_path, archive)
                except OSError as replace_exc:
                    raise RuntimeError(
                        "could not archive the stale physical deploy lock"
                    ) from replace_exc
                continue
            else:
                try:
                    os.write(fd, payload.encode("utf-8"))
                finally:
                    os.close(fd)
                return token

    def _remove_lock_if_owned(self, path: str, token: str) -> bool:
        """Best-effort compare-before-delete; never unlink a successor owner's lock."""
        if not token:
            return False
        held = self._read_json(path) or {}
        if held.get("owner_token") != token:
            return False
        try:
            os.remove(path)
        except OSError:
            return False
        return True

    # ------------------------------------------------------------------
    # 文件工具
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: str) -> Optional[dict]:
        """读 JSON 文件; 不存在/半写入(解析失败)均返回 None(供 status/spawn.lock/write.lock/session_control 共用).

        utf-8-sig 是 utf-8 的超集: 机器写入的无 BOM 文件零行为变化; 兼容 PowerShell/记事本
        手改 session_control.json 带 BOM 的场景(F9: 不剥则 worker 拒请求而本客户端接管门
        放行, split-brain)。与 worker_body.read_json_file / server.mjs readJson 同语义镜像。
        """
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.loads(f.read())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_json_atomic(path: str, obj: dict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=2))
        os.replace(tmp, path)

    def _read_status(self) -> Optional[dict]:
        return self._read_json(self._status_path)

    @staticmethod
    def _safe_unlink(path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass
