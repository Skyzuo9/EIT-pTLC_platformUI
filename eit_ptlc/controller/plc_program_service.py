"""PLC 程序(POU)编辑服务
========================
功能:
    PLC 程序(CODESYS POU)编辑/编译的业务语义层, 经 CodesysIpcClient 驱动一个常驻
    InoProShop(SP11) 实例完成 list/read/write/compile. 挂 app.state.plc_program, 由
    api/plc_program_routes.py 暴露为 REST 端点, 供 web「PLC 编辑界面」使用.

    与运行时控制(controller/plc_controller.py 经 OPC UA 下发动作)解耦: 本服务只动 PLC
    的"程序源码与工程", 不与运行中的真机通信.

    部署(deploy): 预编译和空闲门控后，经 OPC UA 请求 PLC 安全撤销伺服使能，再由 worker
    强制全下载并自动启动；随后等待 PLC 完成 EtherCAT 恢复和 5Z→4X 自动回零。经
    allow_deploy 门控(默认关, 关时路由返回 403)。

    版本管理: 经 PlcVersionRepo 对整份 .project 做全量快照(内容哈希去重) — save=true 落盘后
    自快照, deploy 成功后打部署标记(下发台账), 支持列出/下载/还原.

保存语义(沿用 tools/codesys-mcp/README 约定):
    POU 无静态 schema, 真正的校验是 compile. 故流程为 write(save=false, 仅内存) → compile
    看错误 → 满意再 write(save=true)/save 落盘. 本服务不做"写前临时全量校验"(那是 YAML 动作的范式).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Awaitable, Callable

from eit_ptlc.driver.codesys_ipc import CodesysDeployNotStartedError, CodesysIpcClient
from eit_ptlc.controller.plc_controller import (
    PLCDeployRejected,
    PLCStartupFailed,
    PlcController,
)
from eit_ptlc.controller.plc_symbol_pragma import parse_symbols, set_symbol_pragma
from eit_ptlc.runtime.maintenance_gate import MaintenanceGate, MaintenanceLease

log = logging.getLogger(__name__)

_DEPLOY_PHASES = (
    "compile", "prepare", "download", "reconnect", "home_5z", "home_4x", "ready",
)


class PLCDeployPreconditionError(RuntimeError):
    """完整下载前置条件不满足；保证尚未调用 worker 的 deploy 操作。"""

    def __init__(self, reason: str, *, stage: str = "precheck", details=None) -> None:
        self.stage = str(stage)
        self.details = details
        super().__init__(reason)

    def payload(self) -> dict:
        result = {
            "stage": self.stage,
            "reason": str(self),
            "downloaded": False,
            "deployed": False,
            "ready": False,
            "retryable": True,
            "result_uncertain": False,
        }
        if self.details is not None:
            result["details"] = self.details
        return result


class PLCDeployOutcomeUnknown(RuntimeError):
    """worker 部署调用已开始但未返回确定结果；物理结果不明，禁止自动重试。"""

    def payload(self) -> dict:
        return {
            "stage": "deploy_outcome_unknown",
            "reason": str(self),
            "downloaded": None,
            "deployed": None,
            "ready": False,
            "retryable": False,
            "result_uncertain": True,
        }


class PLCDeployPreparationTimeout(TimeoutError):
    """下载前安全握手超时；保证尚未调用 worker deploy。"""

    def __init__(self, reason: str, *, stage: str = "prepare_timeout") -> None:
        self.stage = stage
        super().__init__(reason)

    def payload(self) -> dict:
        return {
            "stage": self.stage,
            "reason": str(self),
            "downloaded": False,
            "deployed": False,
            "ready": False,
            "retryable": True,
            "result_uncertain": False,
        }


class PLCDeployMaintenanceRecoveryRequired(PLCDeployPreconditionError):
    """下载尚未发生，但 PLC 下载准备态未能确认退出；必须保持维护锁。"""

    def __init__(self, reason: str, *, details=None) -> None:
        super().__init__(
            reason,
            stage="maintenance_recovery_required",
            details=details,
        )

    def payload(self) -> dict:
        payload = super().payload()
        payload.update({
            "retryable": False,
            # 下载是否发生是确定的（False）；不确定的是 PLC 是否已恢复正常控制。
            "result_uncertain": False,
            "maintenance_recovery_required": True,
        })
        return payload


class PlcProgramService:
    """POU 编辑/编译服务 (薄封装 CodesysIpcClient)."""

    # 各操作的 IPC 超时(秒): 首次 status 含冷启动, compile 最慢(InoProShop build ~14s),
    # deploy 含 build + login + 全下载 + 写引导, 最慢, 给足余量; 均留余量
    _T_STATUS = 160.0
    _T_LIST = 120.0
    _T_READ = 60.0
    _T_WRITE = 60.0
    _T_COMPILE = 240.0
    _T_GENERATE_CODE = 240.0
    _T_ONLINE = 120.0
    _T_DEPLOY = 300.0

    def __init__(
        self,
        ipc: CodesysIpcClient,
        *,
        allow_deploy: bool = False,
        version_repo=None,
        plc: PlcController | None = None,
        idle_guard: Callable[[], Awaitable[None]] | None = None,
        deploy_prepare_timeout: float = 30.0,
        startup_ready_timeout: float = 300.0,
        maintenance_gate: MaintenanceGate | None = None,
    ) -> None:
        """
        参数:
            ipc: 已构造的 CodesysIpcClient(懒启动, 首个调用才拉起 InoProShop)
            allow_deploy: 是否允许下发部署到真机(由 config.codesys.allow_deploy 注入; 关时路由 403)
            version_repo: PlcVersionRepo 实例; None 则版本管理优雅退化(快照/列表为空)
            plc: 真机 PlcController, 用于下载前安全卸载握手与下载后 READY 等待
            idle_guard: 可注入的异步全局空闲守卫; 不满足时应抛 PLCDeployPreconditionError
            maintenance_gate: 与动作/VM/机器人共享的进程级维护门；下载结果不明时保持锁定
        """
        self._ipc = ipc
        self.allow_deploy = allow_deploy
        self._version_repo = version_repo
        self._plc = plc
        self._idle_guard = idle_guard
        self._deploy_prepare_timeout = float(deploy_prepare_timeout)
        self._startup_ready_timeout = float(startup_ready_timeout)
        self._deploy_lock = asyncio.Lock()
        # Even standalone service instances retain an uncertain deployment latch;
        # production injects the same gate into ActionExecutor/VM/RobotController.
        self._maintenance_gate = maintenance_gate or MaintenanceGate()
        self._deploy_attempt = 0
        self._deploy_progress: dict[str, object] = {
            "attempt": 0, "revision": 0, "active": False, "status": "idle",
            "phase": "idle", "phase_index": -1, "downloaded": False,
            "ready": False, "retryable": True, "result_uncertain": False,
            "deploy_state": None, "commit_seq": None,
            "startup_state": None, "startup_error_code": None,
            "reason": None, "updated_at": time.time(),
        }

    def maintenance_snapshot(self) -> dict[str, object]:
        """Read-only diagnostic state; a latched failed download needs human recovery."""
        return self._maintenance_gate.snapshot()

    def deploy_status(self) -> dict[str, object]:
        """返回当前/最近一次下载的纯内存进度，不访问 worker、OPC UA 或真机。"""
        snapshot = copy.deepcopy(self._deploy_progress)
        states = ["pending"] * len(_DEPLOY_PHASES)
        index = int(snapshot.get("phase_index", -1))
        status = str(snapshot.get("status", "idle"))
        if index >= 0:
            for i in range(min(index, len(states))):
                states[i] = "done"
            if index < len(states):
                states[index] = {
                    "running": "running", "error": "error", "done": "done",
                }.get(status, "pending")
        snapshot["phases"] = list(_DEPLOY_PHASES)
        snapshot["phase_states"] = states
        return snapshot

    def _begin_deploy_progress(self) -> None:
        self._deploy_attempt += 1
        self._deploy_progress = {
            "attempt": self._deploy_attempt,
            "revision": int(self._deploy_progress.get("revision", 0)) + 1,
            "active": True, "status": "running", "phase": "compile", "phase_index": 0,
            "downloaded": False, "ready": False, "retryable": True,
            "result_uncertain": False, "deploy_state": None, "commit_seq": None,
            "startup_state": None, "startup_error_code": None,
            "reason": None, "updated_at": time.time(),
        }

    def _set_deploy_progress(self, phase: str | None = None, *, status: str = "running", **fields) -> None:
        current = dict(self._deploy_progress)
        if phase is not None:
            if phase not in _DEPLOY_PHASES:
                raise ValueError(f"未知 PLC 部署阶段: {phase}")
            target_index = _DEPLOY_PHASES.index(phase)
            current_index = int(current.get("phase_index", -1))
            # 全下载重连窗口可能短暂读到旧应用值；运行态只向前推进，不倒退 UI。
            if status == "running" and target_index < current_index:
                phase = str(current.get("phase", phase))
                target_index = current_index
            current["phase"] = phase
            current["phase_index"] = target_index
        current.update(fields)
        current["status"] = status
        current["active"] = status == "running"
        current["revision"] = int(current.get("revision", 0)) + 1
        current["updated_at"] = time.time()
        self._deploy_progress = current

    def _on_startup_progress(self, phase: str, snapshot) -> None:
        fields = {
            "startup_state": int(snapshot.get("State", 0)),
            "startup_error_code": int(snapshot.get("ErrorCode", 0)),
        }
        if phase == "failed":
            # State=90 不足以反推出根因步骤，保留最后到达的真实阶段并标红。
            self._set_deploy_progress(status="error", ready=False, **fields)
        else:
            self._set_deploy_progress(phase, ready=False, **fields)

    async def reconcile_maintenance_latch(
        self,
        *,
        operator_confirmed_online_version: bool = False,
    ) -> dict[str, object]:
        """Read PLC facts and clear a crash/failure latch only after proven READY.

        This method performs no PLC writes, reset, download or motion.  State 90 is
        deliberately insufficient: an operator must first complete manual recovery
        until Startup=60, PLC_Ready=TRUE and Deploy=IDLE.
        """
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError(
                "PLC 下载流程仍在运行，拒绝并发对账释放维护门", stage="busy")
        async with self._deploy_lock:
            before = self._maintenance_gate.snapshot()
            guard = self._ipc.deploy_guard_snapshot()
            physical_lock = self._ipc.physical_deploy_lock_snapshot()
            maintenance_active = bool(before.get("active"))
            guard_active = bool(guard)
            physical_lock_active = bool(physical_lock)
            if not maintenance_active and not guard_active and not physical_lock_active:
                return {"released": False, "reason": "maintenance_not_active",
                        "maintenance": before, "version_verified": False,
                        "deploy_guard": guard, "physical_deploy_lock": physical_lock}
            if guard_active:
                if (guard.get("state") not in {"active", "releasing"}
                        or guard.get("purpose") != "deploy"
                        or not guard.get("token")):
                    raise PLCDeployPreconditionError(
                        "PLC 项目守卫不可读或不属于下载事务，拒绝自动清除",
                        stage="guard_mismatch", details=guard,
                    )
                expected_guard_token = str(guard["token"])
            else:
                expected_guard_token = None
            if physical_lock_active and not physical_lock.get("owner_token"):
                raise PLCDeployPreconditionError(
                    "物理下载锁不可读或缺少 owner token，拒绝自动清除",
                    stage="physical_lock_mismatch", details=physical_lock,
                )
            if self._plc is None:
                raise PLCDeployPreconditionError(
                    "PLC 运行时控制器未装配，无法只读对账", stage="precheck")

            startup = await self._plc.startup_snapshot()
            deploy = await self._plc.deploy_snapshot()
            startup_state = int(startup["State"])
            ready = bool(startup["Ready"])
            deploy_state = int(deploy["State"])
            safe = startup_state == 60 and ready and deploy_state == 0
            expected_version = None
            if self._version_repo is not None:
                deployed = [item for item in self._version_repo.history()
                            if item.get("deployed_at")]
                if deployed:
                    latest = deployed[-1]
                    expected_version = {
                        "rev": latest.get("rev"), "sha256": latest.get("sha256"),
                        "deployed_at": latest.get("deployed_at"),
                    }

            result = {
                "released": False,
                "safe_to_release": safe,
                "startup": startup,
                "deploy": deploy,
                "deploy_guard": guard,
                "physical_deploy_lock": physical_lock,
                # online_status cannot read a controller application hash.
                "version_verified": False,
                "expected_version": expected_version,
            }
            if not safe:
                result["reason"] = (
                    "只读对账未满足 Startup=60、PLC_Ready=TRUE、Deploy=0，维护门/下载守卫保持锁定"
                )
                result["maintenance"] = before
                return result

            if not operator_confirmed_online_version:
                result["reason"] = (
                    "PLC 状态已满足 READY，但系统无法读取控制器应用哈希；请先在 "
                    "InoProShop 人工核对在线版本，再明确确认后释放维护门/下载守卫"
                )
                result["operator_confirmation_required"] = True
                result["maintenance"] = before
                return result

            cleared_guard = {}
            cleared_physical_lock = {}
            if expected_guard_token is not None:
                cleared_guard = self._ipc.force_clear_deploy_guard(
                    reason="operator confirmed online version and PLC READY reconciliation",
                    expected_token=expected_guard_token,
                    expected_purpose="deploy",
                    expected_state=str(guard.get("state")),
                    expected_project=str(guard.get("project") or ""),
                    expected_plc_ip=str(guard.get("plc_ip") or ""),
                    expected_protocol_version=guard.get("protocol_version"),
                    expected_worker_body_sha256=guard.get("worker_body_sha256"),
                )
            elif physical_lock_active:
                cleared_physical_lock = self._ipc.force_clear_orphan_physical_lock(
                    reason="operator confirmed online version and PLC READY reconciliation",
                    expected_owner_token=str(physical_lock["owner_token"]),
                )
            if maintenance_active:
                self._maintenance_gate.release_after_reconcile()
            result["released"] = True
            result["deploy_guard_cleared"] = bool(cleared_guard)
            result["physical_deploy_lock_cleared"] = bool(cleared_physical_lock)
            result["reason"] = "PLC 已人工恢复并通过只读 READY 对账"
            result["maintenance"] = self._maintenance_gate.snapshot()
            return result

    async def status(self) -> dict:
        """查询 worker/工程状态; worker 未起则在此懒启动(首次较慢, 会弹 InoProShop 窗口).

        附带 allow_deploy(供 web 门控「下载到设备」按钮; 真值仍由后端 deploy 路由 403 强校验)。
        """
        result = await self._ipc.call("status", {}, self._T_STATUS)
        result["allow_deploy"] = self.allow_deploy
        result["maintenance"] = self.maintenance_snapshot()
        return result

    def session(self) -> dict:
        """Return InoProShop session/keeper/control state without starting worker."""
        result = self._ipc.session_snapshot()
        result["allow_deploy"] = self.allow_deploy
        result["maintenance"] = self.maintenance_snapshot()
        return result

    def takeover(self, by: str = "operator", reason: str = "") -> dict:
        """Put the shared InoProShop session under manual operator control."""
        result = self._ipc.takeover(by=by, reason=reason)
        result["allow_deploy"] = self.allow_deploy
        return result

    def release_takeover(self, by: str = "operator") -> dict:
        """Release manual control so automated clients may use the session again."""
        result = self._ipc.release_takeover(by=by)
        result["allow_deploy"] = self.allow_deploy
        return result

    async def list_pous(self) -> dict:
        """列出 Application 下可编辑 POU 路径 (返回 {"pous":[...], "count":n})."""
        return await self._ipc.call("list", {"textual_only": True}, self._T_LIST)

    async def tree(self) -> dict:
        """列出工程完整设备树 (从工程根遍历, 含硬件节点).

        返回:
            dict, {"nodes":[{path,name,depth,has_impl,has_decl,has_children}], "count":n};
            预序展开列表, 兄弟顺序即 InoProShop 设备树原序, 供 web「设备」标签逐级渲染。
        """
        return await self._ipc.call("tree", {}, self._T_LIST)

    async def read_pou(self, path: str) -> dict:
        """读取某 POU 的声明(VAR)与实现(ST)文本."""
        return await self._ipc.call("read", {"path": path}, self._T_READ)

    async def save_pou(self, path: str, declaration, implementation, save: bool) -> dict:
        """整体替换某 POU 的声明/实现.

        参数:
            path: POU 路径; declaration/implementation: 新文本(None 表示该项不动);
            save: True 则立即落盘到 .project, False 仅改内存(供随后 compile 验证)。
        """
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError("PLC 工程写锁已占用，暂时禁止修改工程", stage="busy")
        async with self._deploy_lock:
            # own_session 会话级独占: 括住 write→版本快照, 保证快照对应的正是本次写入,
            # 其间别的自动方(agent MCP)写类 op 被跨进程挡住, 不会在两步之间插改工程。
            async with self._ipc.own_session(label="fastapi:save_pou"):
                result = await self._ipc.call("write", {
                    "path": path,
                    "declaration": declaration,
                    "implementation": implementation,
                    "save": save,
                }, self._T_WRITE)
                # 落盘成功后自快照整份工程(内容哈希去重); 快照失败不影响保存本身(版本是旁路台账)
                if save and self._version_repo is not None:
                    try:
                        self._version_repo.snapshot_if_changed()
                    except Exception:
                        log.exception("[plc] 保存成功但版本快照失败")
                return result

    async def compile(self) -> dict:
        """编译 Application, 返回 {"error_count","warning_count","errors":[...],"warnings":[...]}."""
        return await self._ipc.call("compile", {}, self._T_COMPILE)

    async def generate_code(self) -> dict:
        """离线生成活动 Application 的 Symbol Configuration XML。

        底层只调用 CODESYS ``app.generate_code()``；不创建 online application，
        不登录 PLC，也不触发下载。返回 XML 路径、mtime/size 与编译消息计数。
        """
        return await self._ipc.call("generate_code", {}, self._T_GENERATE_CODE)

    # ------------------------------------------------------------------
    # OPC 符号导出 (pragma 管理; 复用 read/write, 不脚本化符号配置对象)
    # ------------------------------------------------------------------

    async def list_symbols(self, path: str) -> dict:
        """列出某 POU(GVL)声明里的变量及其 OPC 符号导出态(是否已加 symbol pragma)。

        参数:
            path: POU 路径
        返回:
            dict, {"path":path, "symbols":[{"name","type","exported"}]}; 无声明则 symbols 为空
        """
        decl = (await self._ipc.call("read", {"path": path}, self._T_READ)).get("declaration") or ""
        return {"path": path, "symbols": parse_symbols(decl)}

    async def set_symbol_export(self, path: str, name: str, enabled: bool) -> dict:
        """增删某变量的 `{attribute 'symbol'}` 导出 pragma 并落盘 (供编译+下载后暴露到 OPC)。

        参数:
            path: POU 路径; name: 变量名; enabled: 目标导出态 (True 加 pragma, False 删)
        返回:
            dict, {"path","name","exported","changed"}; changed=False 表示本已是该态
        异常:
            ValueError: 声明中未找到该变量 (由路由映射为 400)
        """
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError("PLC 工程写锁已占用，暂时禁止修改符号导出", stage="busy")
        async with self._deploy_lock:
            # read→transform→write is one project mutation transaction. Holding
            # the deploy lock also prevents a restore/deploy from swapping the
            # project between the read and write.
            # own_session 再补上跨进程缺口: 括住 read→write, 别的自动方(agent MCP)不能
            # 在读到写之间插改同一 POU 声明(否则本次基于旧声明的 pragma 改写会覆盖它)。
            async with self._ipc.own_session(label="fastapi:symbol_export"):
                decl = (await self._ipc.call("read", {"path": path}, self._T_READ)).get("declaration") or ""
                new_decl = set_symbol_pragma(decl, name, enabled)        # name 不存在抛 ValueError
                changed = new_decl != decl
                if changed:
                    await self._ipc.call("write", {"path": path, "declaration": new_decl,
                                                   "implementation": None, "save": True}, self._T_WRITE)
                    # 落盘后自快照整份工程 (与 save_pou 同; 快照失败不影响保存本身)
                    if self._version_repo is not None:
                        try:
                            self._version_repo.snapshot_if_changed()
                        except Exception:
                            log.exception("[plc] 符号导出改动已保存但版本快照失败")
                return {"path": path, "name": name, "exported": enabled, "changed": changed}

    # ------------------------------------------------------------------
    # 部署 (全下载到真机; allow_deploy 门控由路由层校验)
    # ------------------------------------------------------------------

    async def online_status(self) -> dict:
        """探测真机在线可达性(创建 online application 句柄 + 读状态), 供 web 门控下发按钮.

        返回:
            dict, {"reachable":bool, "state":...}; 不可达时 web 提示去 GUI 设活动通信路径。
        """
        return await self._ipc.call("online_status", {}, self._T_ONLINE)

    async def deploy(self) -> dict:
        """执行完整下载，同时维护 GET /deploy/status 使用的旁路内存快照。"""
        # 并发请求不得覆盖正在执行的那次进度。
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError("PLC 工程正在部署或修改", stage="busy")

        if bool(self._maintenance_gate.snapshot().get("active")):
            raise PLCDeployPreconditionError(
                "系统已处于 PLC 下载维护态，须先完成只读对账，禁止再次下载",
                stage="maintenance_locked",
            )
        try:
            guard_token = self._ipc.begin_deploy_guard(purpose="deploy")
        except Exception as exc:
            raise PLCDeployPreconditionError(
                f"无法取得跨进程 PLC 工程部署守卫: {exc}", stage="busy") from exc

        progress_context = {"track": False}
        try:
            result = await self._deploy_impl(
                progress_context, guard_token=guard_token)
        except asyncio.CancelledError:
            track_progress = bool(progress_context["track"])
            if track_progress:
                self._set_deploy_progress(status="error", reason="PLC 部署请求被取消", ready=False)
            raise
        except Exception as exc:
            track_progress = bool(progress_context["track"])
            if track_progress:
                payload = exc.payload() if callable(getattr(exc, "payload", None)) else {}
                self._set_deploy_progress(
                    status="error",
                    reason=str(payload.get("reason", str(exc))),
                    downloaded=payload.get("downloaded", self._deploy_progress.get("downloaded")),
                    ready=False,
                    retryable=payload.get("retryable", self._deploy_progress.get("retryable", True)),
                    result_uncertain=payload.get(
                        "result_uncertain", self._deploy_progress.get("result_uncertain", False)),
                )
            raise
        finally:
            # Persistent guard follows the physical maintenance latch.  Unknown
            # download/startup outcomes keep both latched across process restarts;
            # proven pre-download rollback or READY completion releases both.
            if not bool(self._maintenance_gate.snapshot().get("active")):
                guard = self._ipc.deploy_guard_snapshot()
                if guard.get("token") == guard_token:
                    self._ipc.end_deploy_guard(guard_token)

        track_progress = bool(progress_context["track"])
        result = dict(result)
        result["deploy_attempt"] = self._deploy_attempt
        if bool(result.get("ready")):
            self._set_deploy_progress(
                "ready", status="done", downloaded=True, ready=True,
                retryable=False, result_uncertain=False,
                startup_state=result.get("startup_state"),
                startup_error_code=result.get("startup_error_code"), reason=None,
            )
        else:
            self._set_deploy_progress(
                status="error", downloaded=result.get("downloaded"), ready=False,
                retryable=bool(result.get("retryable", False)),
                result_uncertain=bool(result.get("result_uncertain", False)),
                startup_state=result.get("startup_state"),
                startup_error_code=result.get("startup_error_code"),
                reason=result.get("reason") or result.get("start_error") or "PLC 部署未完成",
            )
        return result

    async def _deploy_impl(
        self,
        progress_context: dict[str, bool] | None = None,
        *,
        guard_token: str,
    ) -> dict:
        """经安全门控执行全下载，并等待新程序启动/自动回零 READY。

        严格顺序：预编译 → 保存/快照 → host 空闲守卫 → PLC 安全卸载握手 → worker 全下载
        → OPC 重连/READY。任何下载前失败均不会调用 worker ``deploy``；下载已经发生后
        的启动失败以 ``downloaded=True, retryable=False`` 正常返回，禁止调用方自动重发。
        """
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError("PLC 工程正在部署或修改", stage="busy")

        async with self._deploy_lock:
            # Only the request that actually owns the project-wide lock may
            # allocate/overwrite deployment progress. A racing request rejected
            # above must leave the first request's status untouched.
            if progress_context is None:
                progress_context = {"track": False}
            latched = bool(self._maintenance_gate.snapshot().get("active"))
            track_progress = not latched or self._deploy_attempt == 0
            progress_context["track"] = track_progress
            if track_progress:
                self._begin_deploy_progress()

            if self._plc is None:
                raise PLCDeployPreconditionError(
                    "PLC 运行时控制器未装配，无法执行下载前安全握手", stage="precheck")
            if not str(self._ipc.target_plc_ip or "").strip():
                raise PLCDeployPreconditionError(
                    "CODESYS 目标 PLC IP 未配置，禁止沿用 GUI 历史活动路径下载",
                    stage="target_unbound",
                )

            try:
                compile_result = await self._ipc.call(
                    "compile", {}, self._T_COMPILE, guard_token=guard_token)
            except TimeoutError as exc:
                raise PLCDeployPreparationTimeout(
                    f"PLC 工程预编译超时，未执行下载: {exc}",
                    stage="compile_timeout",
                ) from exc
            except Exception as exc:
                raise PLCDeployPreconditionError(
                    f"CODESYS worker/工程指纹不可用，未执行下载: {exc}",
                    stage="worker_unavailable",
                ) from exc
            if not isinstance(compile_result, dict) or "error_count" not in compile_result:
                raise PLCDeployPreconditionError(
                    f"PLC 编译返回格式异常，未执行下载: {compile_result!r}",
                    stage="compile_invalid",
                )
            try:
                error_count = int(compile_result["error_count"])
            except (TypeError, ValueError) as exc:
                raise PLCDeployPreconditionError(
                    f"PLC 编译错误数格式异常，未执行下载: {compile_result!r}",
                    stage="compile_invalid",
                ) from exc
            if error_count:
                raise PLCDeployPreconditionError(
                    f"PLC 编译未通过 ({error_count} 个错误)，未执行下载",
                    stage="compile_failed",
                    details=(compile_result or {}).get("errors", []),
                )

            # 编译可能针对 InoProShop 内存中的 save=false 编辑态；先保存，确保磁盘快照与
            # 随后 worker 实际下载的是同一份工程。
            try:
                save_result = await self._ipc.call(
                    "save", {}, self._T_WRITE, guard_token=guard_token)
            except TimeoutError as exc:
                raise PLCDeployPreparationTimeout(
                    f"PLC 工程下载前保存超时，未执行下载: {exc}",
                    stage="save_timeout",
                ) from exc
            except Exception as exc:
                raise PLCDeployPreconditionError(
                    f"PLC 工程下载前保存失败，未执行下载: {exc}",
                    stage="save_failed",
                ) from exc
            if not isinstance(save_result, dict) or not bool(save_result.get("saved")):
                raise PLCDeployPreconditionError(
                    f"PLC 工程下载前保存失败，未执行下载: {save_result!r}",
                    stage="save_failed",
                )

            # 下载前快照是恢复点，不是旁路台账；失败即阻断部署。
            if self._version_repo is not None:
                try:
                    self._version_repo.snapshot_if_changed(message="PLC 完整下载前自动快照")
                    expected_project_sha = self._version_repo.current_sha256()
                except Exception as exc:
                    raise PLCDeployPreconditionError(
                        f"PLC 工程下载前快照失败: {exc}", stage="snapshot_failed") from exc
            else:
                try:
                    expected_project_sha = self._ipc.project_sha256()
                except Exception as exc:
                    raise PLCDeployPreconditionError(
                        f"PLC 工程下载前哈希失败: {exc}", stage="snapshot_failed") from exc

            self._set_deploy_progress("prepare")

            # 原子锁住全部新动作后才做第一次空闲检查。若已有动作恰好先于本租约进入，
            # idle_guard 会看见并拒绝；租约阻止检查之后再出现新的 VM/单动作/机器人运动。
            maintenance_lease = self._maintenance_gate.try_acquire(
                "PLC 完整下载：等待安全卸载、下载及自动回零"
            )
            if maintenance_lease is None:
                snap = self._maintenance_gate.snapshot()
                if bool(snap.get("active")):
                    reason = "系统已处于 PLC 下载维护态，禁止再次下载"
                    stage = "maintenance_locked"
                else:
                    reason = "仍有上位机操作处于活动状态，拒绝进入 PLC 下载维护态"
                    stage = "busy"
                raise PLCDeployPreconditionError(
                    reason, stage=stage, details=snap,
                )
            try:
                await self._run_idle_guard()
            except asyncio.CancelledError:
                self._release_guard_then_maintenance(
                    maintenance_lease, guard_token=guard_token)
                raise
            except Exception:
                self._release_guard_then_maintenance(
                    maintenance_lease, guard_token=guard_token)
                raise

            handshake_started = False
            try:
                # reset_deploy performs OPC writes; mark the handshake as started
                # before awaiting because a disconnect can occur after a partial write.
                handshake_started = True
                await self._plc.reset_deploy(timeout=5.0)
                prepared = await self._plc.prepare_for_deploy(
                    timeout=self._deploy_prepare_timeout)
                # 缩小“检查为空闲后又启动新动作”的竞态窗口；PLC READY 同时会锁住新轴动作。
                await self._run_idle_guard()
                committed = await self._plc.commit_deploy(
                    int(prepared["request_seq"]), timeout=5.0)
                confirmed = await self._plc.confirm_deploy_committed(
                    int(prepared["request_seq"]))
            except PLCDeployRejected as exc:
                if handshake_started:
                    await self._release_after_confirmed_reset(
                        maintenance_lease, cause=exc, guard_token=guard_token)
                else:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                raise PLCDeployPreconditionError(
                    str(exc), stage="prepare_rejected",
                    details={"state": int(exc.state), "error_code": exc.error_code,
                             "request_seq": exc.request_seq},
                ) from exc
            except PLCDeployPreconditionError as exc:
                if handshake_started:
                    await self._release_after_confirmed_reset(
                        maintenance_lease, cause=exc, guard_token=guard_token)
                else:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                raise
            except asyncio.CancelledError:
                if handshake_started:
                    try:
                        await self._release_after_confirmed_reset(
                            maintenance_lease,
                            cause=RuntimeError("下载安全握手期间请求被取消"),
                            guard_token=guard_token,
                        )
                    except PLCDeployMaintenanceRecoveryRequired as recovery_exc:
                        self._set_deploy_progress(
                            status="error", ready=False, retryable=False,
                            result_uncertain=False, reason=str(recovery_exc),
                        )
                        log.error("[plc] 请求取消且下载准备态未确认恢复，维护锁保持")
                else:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                raise
            except TimeoutError as exc:
                if handshake_started:
                    await self._release_after_confirmed_reset(
                        maintenance_lease, cause=exc, guard_token=guard_token)
                else:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                raise PLCDeployPreparationTimeout(str(exc)) from exc
            except Exception as exc:
                if handshake_started:
                    await self._release_after_confirmed_reset(
                        maintenance_lease, cause=exc, guard_token=guard_token)
                else:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                raise PLCDeployPreconditionError(
                    f"PLC 下载安全握手不可用，未执行下载: {exc}",
                    stage="prepare_failed",
                    details={"exception": type(exc).__name__},
                ) from exc

            # 这是唯一真正改写真机的调用。此行之后的失败不得触发自动重发。
            self._set_deploy_progress(
                "download",
                deploy_state=int(committed["state"]),
                commit_seq=int(committed["commit_seq"]),
            )
            try:
                worker = asyncio.create_task(
                    self._ipc.authorized_deploy(
                        expected_sha256=expected_project_sha,
                        commit_seq=int(committed["commit_seq"]),
                        expected_plc_ip=self._ipc.target_plc_ip,
                        guard_token=guard_token,
                        timeout=self._T_DEPLOY,
                    ),
                    name="plc-full-deploy",
                )
                self._set_deploy_progress(
                    downloaded=None, retryable=False, result_uncertain=True,
                )
            except Exception:
                # worker 尚未获得执行机会，仍属于明确的下载前失败。
                await self._release_after_confirmed_reset(
                    maintenance_lease,
                    cause=RuntimeError("CODESYS worker 部署任务未能创建"),
                    guard_token=guard_token,
                )
                raise
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                # 客户端断开/请求取消不能中止已经送进 worker 的非幂等全下载；等待它给出确定结果，
                # 再继续做台账与 READY 核对。若进程被强杀，下一次操作仍须人工核对在线版本。
                log.warning("[plc] HTTP 请求已取消，但全下载已开始；继续等待确定结果，禁止重发")
                try:
                    result = await asyncio.shield(worker)
                except Exception as exc:
                    raise PLCDeployOutcomeUnknown(
                        f"PLC 部署调用在请求取消后结果不明确，禁止自动重试: {exc}"
                    ) from exc
            except CodesysDeployNotStartedError as exc:
                result = {
                    "deployed": False,
                    "authorization_valid": False,
                    "reason": str(exc),
                    "stage": "authorization_failed",
                }
            except Exception as exc:
                raise PLCDeployOutcomeUnknown(
                    f"PLC 部署调用结果不明确，禁止自动重试；请人工核对在线版本: {exc}"
                ) from exc
            if not isinstance(result, dict) or not isinstance(result.get("deployed"), bool):
                raise PLCDeployOutcomeUnknown(
                    f"PLC 部署返回缺少确定的 deployed 布尔值，禁止自动重试: {result!r}"
                )
            result = dict(result)
            downloaded = result["deployed"]
            if downloaded:
                try:
                    result_commit_seq = int(result.get("commit_seq", 0) or 0)
                except (TypeError, ValueError):
                    result_commit_seq = 0
                binding_ok = (
                    result.get("authorization_valid") is True
                    and str(result.get("project_sha256", "")).lower() == expected_project_sha
                    and str(result.get("target_ip", "")) == self._ipc.target_plc_ip
                    and result.get("target_verified") is True
                    and result_commit_seq == int(committed["commit_seq"])
                    and result.get("worker_body_sha256") == self._ipc.worker_body_sha256
                )
                if not binding_ok:
                    raise PLCDeployOutcomeUnknown(
                        "worker reported downloaded=true without matching authorization/SHA/target/commit; "
                        "禁止自动重试，请人工核对在线版本"
                    )
            result["downloaded"] = downloaded
            result["result_uncertain"] = False
            self._set_deploy_progress(
                downloaded=downloaded,
                retryable=not downloaded,
                result_uncertain=False,
            )

            if not downloaded:
                # worker 在 login 前二次编译中止，旧 PLC 程序仍在；只有确认 PLC 已恢复
                # Deploy=0/Startup=60/Ready 后才能重新开放动作。
                recovered = await self._best_effort_reset_deploy()
                result.update({"ready": False, "retryable": recovered,
                               "stage": result.get("stage") or "download_blocked",
                               "prepare": prepared, "committed": committed,
                               "confirmed": confirmed})
                if recovered:
                    self._release_guard_then_maintenance(
                        maintenance_lease, guard_token=guard_token)
                    raise PLCDeployPreconditionError(
                        result.get("reason") or "CODESYS worker 在登录前阻止了完整下载",
                        stage=str(result.get("stage") or "download_blocked"),
                        details=result,
                    )
                result.update({
                    "stage": "maintenance_recovery_required",
                    "reason": "下载未发生，但 PLC 下载准备态未确认恢复；维护锁保持",
                    "maintenance_recovery_required": True,
                })
                raise PLCDeployMaintenanceRecoveryRequired(
                    result["reason"], details=result)

            # 真机已被改写：无论后续启动是否成功，都先留下部署台账。
            ledger_error = None
            if self._version_repo is not None:
                try:
                    self._version_repo.mark_deployed(
                        expected_sha256=expected_project_sha)
                except Exception as exc:
                    ledger_error = str(exc)
                    log.exception("[plc] 部署成功但按 SHA 写版本台账失败；维护锁保持")

            if result.get("physical_lock_released") is not True:
                result.update({
                    "ready": False,
                    "retryable": False,
                    "stage": "physical_lock_release_failed",
                    "reason": result.get("reason") or (
                        "PLC 已完成下载，但 worker 未能确认释放物理下载锁；"
                        "维护门和下载守卫保持，禁止重试"
                    ),
                    "maintenance_recovery_required": True,
                })
                return result

            result.update({"ready": False, "retryable": False,
                           "stage": "waiting_startup", "prepare": prepared,
                           "committed": committed, "confirmed": confirmed})
            self._set_deploy_progress(
                "reconnect", downloaded=True, retryable=False, result_uncertain=False,
            )
            # 即使 worker 的 oa.start() 未确认成功，也必须以 PLC_Ready 为最终事实源；
            # 汇川全下载可能已由 login 自动启动，worker 的 started=False 不能代替现场核对。
            startup_worker = asyncio.create_task(
                self._plc.wait_startup_ready(
                    timeout=self._startup_ready_timeout,
                    progress_callback=self._on_startup_progress,
                ),
                name="plc-wait-startup-ready",
            )
            try:
                try:
                    startup = await asyncio.shield(startup_worker)
                except asyncio.CancelledError:
                    log.warning("[plc] HTTP 请求已取消，但 PLC 已下载；继续等待启动 READY，禁止重发")
                    startup = await asyncio.shield(startup_worker)
            except (PLCStartupFailed, TimeoutError) as exc:
                reason = str(exc)
                if result.get("start_error"):
                    reason = f"worker 启动提示: {result['start_error']}; {reason}"
                result.update({
                    "stage": "startup_failed",
                    "reason": reason,
                    "startup_state": getattr(exc, "state", None),
                    "startup_error_code": getattr(exc, "error_code", None),
                })
                return result

            result.update({
                "ready": True,
                "stage": "ready",
                "startup_state": int(startup["State"]),
                "startup_error_code": int(startup["ErrorCode"]),
            })
            if ledger_error:
                result.update({
                    "ready": False,
                    "stage": "ledger_mismatch",
                    "reason": "PLC 已下载且启动 READY，但工程版本台账按 SHA 核验失败: "
                              + ledger_error,
                    "maintenance_recovery_required": True,
                    "retryable": False,
                })
                return result
            try:
                self._release_guard_then_maintenance(
                    maintenance_lease, guard_token=guard_token)
            except PLCDeployMaintenanceRecoveryRequired as exc:
                result.update({
                    "ready": False,
                    "stage": "maintenance_recovery_required",
                    "reason": str(exc),
                    "retryable": False,
                    "maintenance_recovery_required": True,
                })
                return result
            return result

    async def _run_idle_guard(self) -> None:
        """运行注入的全局空闲守卫；未注入仅依赖 PLC 自身安全握手。"""
        if self._idle_guard is not None:
            await self._idle_guard()

    async def _best_effort_reset_deploy(self) -> bool:
        """仅用于确定未下载路径；确认 PLC 完整恢复正常控制才返回 True。"""
        try:
            await self._plc.reset_deploy(timeout=5.0)
            startup = await self._plc.wait_startup_ready(timeout=15.0)
            deploy = await self._plc.deploy_snapshot()
            recovered = (
                int(deploy["State"]) == 0
                and int(deploy.get("CommitSeq", 0)) == 0
                and int(startup["State"]) == 60
                and bool(startup["Ready"])
            )
            if recovered:
                return True
            log.error(
                "[plc] 下载尚未发生，但恢复对账不满足安全条件: deploy=%r startup=%r",
                deploy, startup,
            )
        except Exception:
            log.exception("[plc] 下载尚未发生，但退出下载准备维护态失败，请人工复位")
        return False

    async def _release_after_confirmed_reset(
        self,
        maintenance_lease: MaintenanceLease,
        *,
        cause: BaseException,
        guard_token: str,
    ) -> None:
        """恢复被安全证据确认后释放；否则持久锁并替换为明确恢复错误。"""
        if await self._best_effort_reset_deploy():
            self._release_guard_then_maintenance(
                maintenance_lease, guard_token=guard_token)
            return
        raise PLCDeployMaintenanceRecoveryRequired(
            "下载尚未发生，但 PLC 下载准备态无法确认恢复；动作保持锁定，"
            "请人工复位后执行只读安全对账",
            details={"original_error": str(cause), "exception": type(cause).__name__},
        ) from cause

    def _release_guard_then_maintenance(
        self,
        maintenance_lease: MaintenanceLease,
        *,
        guard_token: str,
    ) -> None:
        """Clear the cross-process guard before reopening machine activity."""
        try:
            self._ipc.end_deploy_guard(guard_token)
        except Exception as exc:
            raise PLCDeployMaintenanceRecoveryRequired(
                "PLC 已满足释放条件，但跨进程下载守卫未能确认清除；维护门保持锁定",
                details={"guard_error": str(exc)},
            ) from exc
        self._maintenance_gate.release(maintenance_lease)

    # ------------------------------------------------------------------
    # 版本管理 (整份 .project 二进制快照; 仓库为 None 时优雅退化)
    # ------------------------------------------------------------------

    def versions(self) -> list[dict]:
        """列出 .project 全量快照历史 (rev/ts/sha256/size/deployed_at/message; 升序)."""
        if self._version_repo is None:
            return []
        return self._version_repo.history()

    def version_bytes(self, rev: str) -> bytes:
        """取某版快照二进制内容 (供下载); rev 不存在抛 KeyError."""
        if self._version_repo is None:
            raise RuntimeError("版本仓库未装配")
        return self._version_repo.version_bytes(rev)

    def snapshot(self, message: str = "") -> dict | None:
        """手动给当前活动工程打一版快照 (内容未变返回 None)."""
        if self._version_repo is None:
            raise RuntimeError("版本仓库未装配")
        return self._version_repo.snapshot_if_changed(message=message)

    async def restore_version(self, rev: str) -> dict:
        """还原某版到活动工程: 先停共享 worker 释放 .project 文件锁, 再覆盖(还原前先自快照, 可逆);
        下次 status 懒重启 worker 打开还原后工程。rev 不存在抛 KeyError。"""
        if self._deploy_lock.locked():
            raise PLCDeployPreconditionError("PLC 工程写锁已占用，暂时禁止还原版本", stage="busy")
        async with self._deploy_lock:
            if self._version_repo is None:
                raise RuntimeError("版本仓库未装配")
            self._version_repo.get_version(rev)  # 先校验存在(不存在抛 KeyError→404), 避免无谓停 worker
            try:
                guard_token = self._ipc.begin_deploy_guard(purpose="restore")
            except Exception as exc:
                raise PLCDeployPreconditionError(
                    f"无法取得跨进程 PLC 工程还原守卫: {exc}", stage="busy") from exc
            try:
                # 真停共享 worker(写 stop 哨兵等进程退出释放文件锁); shutdown() 只放本地句柄, 挡不住文件锁
                await self._ipc.stop_worker(guard_token=guard_token)
                return self._version_repo.restore(rev)
            except TimeoutError as exc:
                raise RuntimeError("停止 InoProShop worker 超时, 无法释放工程文件锁: %s" % exc)
            finally:
                self._ipc.end_deploy_guard(guard_token)
