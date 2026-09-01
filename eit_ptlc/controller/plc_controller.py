"""PLC 控制器 (统一 L2 动作通道)
================================
功能:
    PLC 设备语义层. 把 OPC UA 传输封装为统一 L2 原子动作通道, 对上层提供
    execute(station, action_code, params) -> PLCActionResult, 实现下降沿启动时序 /
    单调序号 / 终态轮询 / 断线不重发不确定物理动作.
    迁移自 UI-Upper/core/plc_action_client.py, 由 Sampling 专用泛化为任意工位,
    底座改为 driver.OpcUaDriver.

统一 L2 通道字段 (每工位 {prefix}_L2_*):
    PC->PLC: ActionCode, RequestSeq, Start, Reset, + 具名工艺参数
    PLC->PC: State, ActiveCode, AcceptedSeq, CompletedSeq, Step, ErrorCode, SafeState, Retryable

启动时序 (下降沿确认):
    Start=FALSE -> 等 State=IDLE -> 写参数/ActionCode/RequestSeq -> 写回校验 -> Start=TRUE
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Mapping

from eit_ptlc.driver.opcua_driver import OpcUaDriver

log = logging.getLogger(__name__)

# 工位名 -> L2 变量前缀 (便于上层用业务名调用; 未命中时按传入字符串作为精确前缀)
STATION_PREFIX = {
    "sampling": "Sampling",
    "spotting": "Sampling",
    "collect": "Collect",
    "develop": "Develop",
    "expand": "Develop",
    "photoscrape": "PhotoScrape",
    "scrape": "PhotoScrape",
    "feedlift": "FeedLift",
    "pump": "Pump",
    "rail": "Rail",
    "staging_a": "StagingA",
}


# 工位 L2 状态快照字段 (PLC->PC; 既用于直读 snapshot, 也是订阅看门狗监控的字段集)
_L2_FIELDS = ("State", "ActiveCode", "AcceptedSeq", "CompletedSeq",
              "Step", "ErrorCode", "SafeState", "Retryable")

# PLC 全下载维护握手/启动诊断使用系统级节点，不属于任何工位 L2 动作。
_DEPLOY_FIELDS = ("State", "AcceptedSeq", "CommitSeq", "ErrorCode")


class PLCActionState(IntEnum):
    IDLE = 0
    RUNNING = 10
    DONE = 20
    REJECTED = 30
    ERROR = 40
    INTERRUPTED = 50


class PLCActionSafeState(IntEnum):
    UNKNOWN = 0
    READY = 10
    PLATE_HELD_UNVERIFIED = 20
    RELEASE_READY_UNVERIFIED = 30
    RECOVERY_REQUIRED = 90


@dataclass(frozen=True)
class PLCActionResult:
    """L2 动作终态结果."""
    station: str
    action_code: int
    request_seq: int
    state: PLCActionState
    error_code: int
    safe_state: PLCActionSafeState
    retryable: bool
    step: int

    @property
    def ok(self) -> bool:
        return self.state is PLCActionState.DONE


class PLCActionError(RuntimeError):
    """L2 动作进入非 DONE 终态 (REJECTED/ERROR/INTERRUPTED)."""

    def __init__(self, result: PLCActionResult) -> None:
        self.result = result
        # step 必须带上: 同一个 ErrorCode 在一个动作里可能来自不同阶段 (前置等待 / 搜索 /
        # 确认), 各工位的 L2_Step 段号正是用来区分的。它本来就已经读回在 result 里,
        # 漏在消息外只会逼现场再去 InoProShop 看一眼。
        super().__init__(
            f"PLC L2 动作失败: station={result.station} action={result.action_code} "
            f"seq={result.request_seq} state={result.state.name} error={result.error_code} "
            f"step={result.step}"
        )


class PLCActionOutcomeUnknown(RuntimeError):
    """动作结果不明确, 调用方绝不能自动重发 (非幂等物理动作)."""


class PLCDeployState(IntEnum):
    """PLC 全下载前安全准备握手状态。"""

    IDLE = 0
    PREPARING = 10
    READY = 20
    COMMITTED = 25
    REJECTED = 30
    ERROR = 40


class PLCStartupState(IntEnum):
    """PLC 完整下载后的启动/回零状态。"""

    BOOT = 0
    WAIT_BUS = 10
    RESET_FAULT = 20
    ENABLE_AXES = 30
    RETREAT_5Z = 40
    HOME_5Z = 41
    RETREAT_4X = 50
    HOME_4X = 51
    READY = 60
    ERROR = 90


class PLCDeployRejected(RuntimeError):
    """PLC 明确拒绝或无法完成下载前安全准备；此时尚未执行下载。"""

    def __init__(self, *, state: PLCDeployState, error_code: int, request_seq: int) -> None:
        self.state = state
        self.error_code = int(error_code)
        self.request_seq = int(request_seq)
        super().__init__(
            f"PLC 下载准备失败: seq={request_seq} state={state.name} error={error_code}"
        )


class PLCStartupFailed(RuntimeError):
    """下载已发生，但 PLC 启动状态机明确进入 ERROR；禁止自动重新下载。"""

    def __init__(self, *, state: int, error_code: int) -> None:
        self.state = int(state)
        self.error_code = int(error_code)
        super().__init__(f"PLC 下载后启动失败: state={state} error={error_code}")


class PlcController:
    """统一 L2 动作通道控制器.

    使用方式:
        ctrl = PlcController(driver)
        result = await ctrl.execute("sampling", 10)   # Sampling_Init
    """

    _TERMINAL = {
        PLCActionState.DONE,
        PLCActionState.REJECTED,
        PLCActionState.ERROR,
        PLCActionState.INTERRUPTED,
    }

    def __init__(
        self,
        driver: OpcUaDriver,
        *,
        poll_interval: float = 0.05,
        action_timeout: float = 600.0,
        stall_timeout: float = 60.0,
        soft_recheck: float = 1.0,
        station_prefix: dict[str, str] | None = None,
    ) -> None:
        self._driver = driver
        self._poll_interval = float(poll_interval)
        # action_timeout: 绝对上限 (兜底病态挂死); stall_timeout: 停滞判停 (T_idle, 无进度多久算卡).
        # 等待终态改为订阅事件驱动 + 看门狗: 只要 PLC 还在推进 (任一 L2 字段变化) 就一直等,
        # 停滞超过 stall_timeout 或总时长超过 action_timeout 才判 "结果不明确".
        self._action_timeout = float(action_timeout)
        self._stall_timeout = float(stall_timeout)
        # soft_recheck: 镜像静默软复核间隔 (秒). 等待终态时只读订阅镜像, 而 OPC UA 订阅是
        # report-on-change: 服务器只在采样值 != "上次已发水位线" 时推 delta, 且对保持不变的电平
        # 不重发。故一旦 "State→终态" 那一条 delta 在发布/传输/队列环节丢失, 镜像会永久停在动作前
        # 的旧值 (对单扫描完成的动作如 StagingA 塌缩为一条 IDLE→DONE), 直到 stall_timeout 才靠边界
        # 直读救回 —— 现场即 "定位气缸等几十秒才动"。软复核在镜像静默超过此值时主动直读对账 (绕开
        # 水位线, 直接问 PLC 真值), 把漏推恢复从 stall_timeout 压到 ~soft_recheck。0/负 = 关闭。
        self._soft_recheck = float(soft_recheck)
        self._prefix_map = dict(STATION_PREFIX)
        if station_prefix:
            self._prefix_map.update({k.lower(): v for k, v in station_prefix.items()})
        self._locks: dict[str, asyncio.Lock] = {}
        self._next_seq: dict[str, int] = {}
        self._monitored: set[str] = set()   # 已订阅 L2 状态字段的工位前缀 (懒订阅)
        self._deploy_lock = asyncio.Lock()
        self._next_deploy_seq: int | None = None

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    async def execute(
        self,
        station: str,
        action_code: int,
        params: Mapping[str, object] | None = None,
        *,
        timeout: float | None = None,
        stall_timeout: float | None = None,
    ) -> PLCActionResult:
        """执行一个 L2 工位动作, 返回终态结果 (DONE), 非 DONE 抛 PLCActionError.

        参数:
            station: 工位名或 L2 前缀; action_code: 动作码; params: 具名工艺参数;
            timeout: 绝对上限覆盖 (None=用构造期 action_timeout);
            stall_timeout: 停滞判停覆盖 (None=用构造期 stall_timeout). 静默窗口长的动作
                (如 CNC 单 pass 刮取: PLC 内部 SoftMotion 全程无 L2 字段推进) 按需放大,
                不必牵动全局阈值 (否则其它动作的看门狗一起变迟钝)。
        返回:
            PLCActionResult (state=DONE)
        """
        prefix = self._prefix(station)
        async with self._locks.setdefault(prefix, asyncio.Lock()):
            seq = await self._allocate_seq(prefix)
            worker = asyncio.create_task(
                self._execute_one(prefix, int(action_code), seq, dict(params or {}),
                                   timeout, stall_timeout),
                name=f"plc-action-{prefix}-{seq}",
            )
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # 让已接受的物理动作执行完再传播取消, 避免半途状态不一致
                try:
                    await asyncio.shield(worker)
                except Exception:
                    log.exception("[%s L2] 取消后清理失败 seq=%d", prefix, seq)
                raise

    async def reset(self, station: str, *, pulse_s: float = 0.1) -> None:
        """脉冲 {prefix}_L2_Reset, 清工位故障 (不产生回零运动)."""
        prefix = self._prefix(station)
        await self._driver.write_variable(f"{prefix}_L2_Reset", True)
        await asyncio.sleep(pulse_s)
        await self._driver.write_variable(f"{prefix}_L2_Reset", False)

    async def snapshot(self, station: str) -> dict[str, object]:
        """读取工位 L2 状态快照 (直读, 供监控/诊断).

        一次批读拿全 8 个字段: 逐字段读的话遥测每秒要为 8 个工位发 64 次串行往返,
        那些往返正是把 PLC 服务端压到应答超时、触发 asyncua 误判断连的主要负载。
        """
        prefix = self._prefix(station)
        values = await self._driver.read_many([f"{prefix}_L2_{f}" for f in _L2_FIELDS])
        return dict(zip(_L2_FIELDS, values))

    async def snapshot_with_mirrors(self, station: str,
                                    mirrors: tuple[str, ...] = ()) -> dict[str, object]:
        """L2 状态快照 + 附加诊断镜像, 合并成一次批读 (遥测专用)。

        参数:
            station: 工位; mirrors: 额外的 Host_Computer 镜像变量名
        返回:
            {L2 字段名: 值} ∪ {镜像名: 值}; 未下装/读失败的键为 None
        说明:
            遥测 1Hz 要拉 8 个工位, 每工位 8 个 L2 字段加若干镜像。分开逐个读是十余次串行
            往返 × 8 工位, 合并后每工位一次请求。已被判定未下装的镜像 (如 Sampling_5Z_ActPos)
            在驱动侧走负缓存, 零往返直接填 None, 不会再触发按名浏览容器的风暴。
        """
        prefix = self._prefix(station)
        names = [f"{prefix}_L2_{f}" for f in _L2_FIELDS] + list(mirrors)
        values = await self._driver.read_many(names)
        out: dict[str, object] = dict(zip(_L2_FIELDS, values[:len(_L2_FIELDS)]))
        out.update(zip(mirrors, values[len(_L2_FIELDS):]))
        return out

    def host_var_missing_reason(self, name: str):
        """该 Host_Computer 变量若已判定未下装, 返回原因; 否则 None (供遥测告警取信)。"""
        return self._driver.missing_reason(name)

    def has_active_actions(self) -> bool:
        """是否有本控制器派发的 L2 动作仍占用工位锁（纯内存、无设备 IO）。"""
        return any(lock.locked() for lock in self._locks.values())

    async def deploy_snapshot(self) -> dict[str, object]:
        """直读全下载安全准备握手状态 (一次批读)。"""
        values = await self._driver.read_many([f"PLC_Deploy_{f}" for f in _DEPLOY_FIELDS])
        return dict(zip(_DEPLOY_FIELDS, values))

    async def startup_snapshot(self) -> dict[str, object]:
        """直读下载后启动/自动回零状态 (一次批读)。"""
        fields = ("State", "ErrorCode", "Ready")
        values = await self._driver.read_many(
            ["PLC_Startup_State", "PLC_Startup_ErrorCode", "PLC_Ready"])
        return dict(zip(fields, values))

    async def sampling_free_move_active(self) -> bool:
        """直读手动孔板标定去使能请求，供完整下载空闲守卫使用。"""
        return bool(await self._driver.read_variable("Sampling_Servo_FreeMove"))

    async def reset_deploy(self, *, pulse_s: float = 0.1, timeout: float = 5.0) -> None:
        """取消/复位下载准备握手，并确认 PLC 回到 IDLE。

        该方法只退出维护占位，不产生轴运动。部署服务在编译/守卫失败后不会调用它；
        握手已开始但下载尚未发生时失败，才用它恢复 PLC 正常接单。
        """
        # COMMITTED 状态只有先撤销提交序号才允许退出；顺序不可反转。
        await self._driver.write_variable("PLC_Deploy_CommitSeq", 0)
        await self._driver.write_variable("PLC_Deploy_Start", False)
        await self._driver.write_variable("PLC_Deploy_Reset", True)
        await asyncio.sleep(max(0.0, float(pulse_s)))
        await self._driver.write_variable("PLC_Deploy_Reset", False)

        deadline = asyncio.get_running_loop().time() + float(timeout)
        while True:
            state = PLCDeployState(int(await self._driver.read_variable("PLC_Deploy_State")))
            if state is PLCDeployState.IDLE:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"PLC 下载准备复位后未在 {timeout:.1f}s 内回到 IDLE")
            await asyncio.sleep(self._poll_interval)

    async def prepare_for_deploy(self, *, timeout: float = 30.0) -> dict[str, int]:
        """请求 PLC 停止接收动作、确认轴静止并撤销伺服使能。

        返回 READY 快照；PLC 明确 REJECTED/ERROR 时抛 ``PLCDeployRejected``，
        超时抛 ``TimeoutError``。本方法绝不触发 CODESYS 下载。
        """
        if self._deploy_lock.locked():
            raise PLCDeployRejected(
                state=PLCDeployState.REJECTED, error_code=1, request_seq=0,
            )
        async with self._deploy_lock:
            state = PLCDeployState(int(await self._driver.read_variable("PLC_Deploy_State")))
            if state is not PLCDeployState.IDLE:
                raise PLCDeployRejected(state=state, error_code=int(
                    await self._driver.read_variable("PLC_Deploy_ErrorCode")), request_seq=0)

            seq = await self._allocate_deploy_seq()
            await self._driver.write_variable("PLC_Deploy_Start", False)
            await self._driver.write_variable("PLC_Deploy_CommitSeq", 0)
            await self._driver.write_variable("PLC_Deploy_RequestSeq", seq)
            written = int(await self._driver.read_variable("PLC_Deploy_RequestSeq"))
            if written != seq:
                raise RuntimeError(f"PLC 下载准备序号写回校验失败: {written}/{seq}")
            await self._driver.write_variable("PLC_Deploy_Start", True)

            deadline = asyncio.get_running_loop().time() + float(timeout)
            ready_owned = False
            try:
                while True:
                    snap = await self.deploy_snapshot()
                    state = PLCDeployState(int(snap["State"]))
                    accepted = int(snap["AcceptedSeq"])
                    error_code = int(snap["ErrorCode"])
                    if accepted == seq and state is PLCDeployState.READY:
                        # 成功后故意保持 Start=TRUE：它是 Host 对 READY 状态的所有权租约。
                        # PLC 仅在 Start 下降后才接受 HMI Reset/取消；完整下载会自然重建变量。
                        ready_owned = True
                        return {"state": int(state), "accepted_seq": accepted,
                                "error_code": error_code, "request_seq": seq}
                    if accepted == seq and state in (PLCDeployState.REJECTED, PLCDeployState.ERROR):
                        raise PLCDeployRejected(
                            state=state, error_code=error_code, request_seq=seq)
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError(
                            f"PLC 下载安全准备超过 {timeout:.1f}s: seq={seq} "
                            f"state={state.name} accepted={accepted} error={error_code}"
                        )
                    await asyncio.sleep(self._poll_interval)
            finally:
                # 失败时撤销请求；READY 成功时保持 TRUE，直到 worker 开始完整下载或
                # 上位机在“尚未下载”的失败路径显式 reset_deploy()。
                if not ready_owned:
                    try:
                        await self._driver.write_variable("PLC_Deploy_Start", False)
                    except Exception:
                        log.warning("[PLC deploy] Start 下降沿未确认 seq=%d", seq, exc_info=True)

    async def commit_deploy(self, request_seq: int, *, timeout: float = 5.0) -> dict[str, int]:
        """Commit a prepared request so HMI cancellation can no longer re-enable axes."""
        seq = int(request_seq)
        snap = await self.deploy_snapshot()
        state = PLCDeployState(int(snap["State"]))
        accepted = int(snap["AcceptedSeq"])
        if state is not PLCDeployState.READY or accepted != seq:
            raise RuntimeError(
                "PLC 下载准备态已变化，禁止提交: "
                f"seq={seq} state={state.name} accepted={accepted}"
            )

        await self._driver.write_variable("PLC_Deploy_CommitSeq", seq)
        written = int(await self._driver.read_variable("PLC_Deploy_CommitSeq"))
        if written != seq:
            raise RuntimeError(f"PLC 下载提交序号写回校验失败: {written}/{seq}")

        deadline = asyncio.get_running_loop().time() + float(timeout)
        while True:
            snap = await self.deploy_snapshot()
            state = PLCDeployState(int(snap["State"]))
            accepted = int(snap["AcceptedSeq"])
            committed = int(snap["CommitSeq"])
            error_code = int(snap["ErrorCode"])
            if (state is PLCDeployState.COMMITTED and accepted == seq
                    and committed == seq and error_code == 0):
                return {
                    "state": int(state), "accepted_seq": accepted,
                    "commit_seq": committed, "error_code": error_code,
                    "request_seq": seq,
                }
            if state in (PLCDeployState.REJECTED, PLCDeployState.ERROR):
                raise PLCDeployRejected(
                    state=state, error_code=error_code, request_seq=seq,
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    f"PLC 下载提交超过 {timeout:.1f}s: seq={seq} state={state.name} "
                    f"accepted={accepted} committed={committed} error={error_code}"
                )
            await asyncio.sleep(self._poll_interval)

    async def confirm_deploy_committed(self, request_seq: int) -> dict[str, int | bool]:
        """Immediately before worker login, revalidate the immutable commit lease.

        State, AcceptedSeq and CommitSeq must still belong to the same request.
        Start is retained as an additional ownership diagnostic, while COMMITTED
        is the PLC-side barrier that ignores subsequent HMI cancellation.
        """
        snap = await self.deploy_snapshot()
        start = bool(await self._driver.read_variable("PLC_Deploy_Start"))
        state = PLCDeployState(int(snap["State"]))
        accepted = int(snap["AcceptedSeq"])
        committed = int(snap["CommitSeq"])
        error_code = int(snap["ErrorCode"])
        seq = int(request_seq)
        if (state is not PLCDeployState.COMMITTED or accepted != seq
                or committed != seq or not start or error_code != 0):
            raise RuntimeError(
                "PLC 下载提交所有权已变化，禁止开始完整下载: "
                f"seq={seq} state={state.name} accepted={accepted} "
                f"committed={committed} start={start} error={error_code}"
            )
        return {
            "state": int(state), "accepted_seq": accepted,
            "commit_seq": committed, "error_code": error_code,
            "request_seq": seq, "start": start,
        }

    async def wait_startup_ready(
        self,
        *,
        timeout: float = 300.0,
        progress_callback: Callable[[str, Mapping[str, object]], object] | None = None,
    ) -> dict[str, object]:
        """下载后等待 OPC UA 重连以及 PLC 启动/5Z→4X 自动回零完成。

        通信窗口内的读失败会持续复核直到总超时；状态机明确进入 ERROR 则立即抛
        ``PLCStartupFailed``。调用方必须把两种失败都视为“已下载、结果不可重试”。

        可选回调只做观测：0/10/20/30 映射 ``reconnect``，40/41 映射
        ``home_5z``，50/51 映射 ``home_4x``，两次确认的 60 映射 ``ready``，
        90 映射 ``failed``。回调异常不会中断下载后的安全等待。
        """
        deadline = asyncio.get_running_loop().time() + float(timeout)
        last: dict[str, object] | None = None
        last_error: Exception | None = None
        ready_samples = 0
        last_progress_phase: str | None = None

        async def notify(phase: str, snapshot: Mapping[str, object]) -> None:
            nonlocal last_progress_phase
            if progress_callback is None or phase == last_progress_phase:
                return
            last_progress_phase = phase
            try:
                callback_result = progress_callback(phase, snapshot)
                if inspect.isawaitable(callback_result):
                    await callback_result
            except Exception:
                log.exception("[PLC deploy] 启动进度回调失败，继续等待: phase=%s", phase)

        while True:
            try:
                last = await self.startup_snapshot()
                last_error = None
                state = int(last["State"])
                error_code = int(last["ErrorCode"])
                ready = bool(last["Ready"])
                if ready and state == int(PLCStartupState.READY):
                    # 两次连续直读均 READY，避免应用重建窗口的一次撕裂/旧值误判。
                    ready_samples += 1
                    if ready_samples >= 2:
                        await notify("ready", last)
                        return last
                else:
                    ready_samples = 0
                    if state in (int(PLCStartupState.RETREAT_5Z), int(PLCStartupState.HOME_5Z)):
                        await notify("home_5z", last)
                    elif state in (int(PLCStartupState.RETREAT_4X), int(PLCStartupState.HOME_4X)):
                        await notify("home_4x", last)
                    elif state == int(PLCStartupState.ERROR):
                        await notify("failed", last)
                    else:
                        await notify("reconnect", last)
                if state == int(PLCStartupState.ERROR):
                    raise PLCStartupFailed(state=state, error_code=error_code)
            except PLCStartupFailed:
                raise
            except Exception as exc:
                # 完整下载会短暂关闭 OPC UA；只在整体死线到达时判失败，不重发下载。
                # asyncua 在不同断链阶段可能抛 UaStatusCodeError/TimeoutError/OSError 等不同类型，
                # 这里统一视为启动窗口内的暂态读失败；CancelledError 不属于 Exception，不会被吞。
                last_error = exc
                ready_samples = 0

            if asyncio.get_running_loop().time() >= deadline:
                detail = f"last={last}" if last is not None else f"last_error={last_error}"
                raise TimeoutError(f"PLC 下载后 {timeout:.1f}s 内未进入 READY: {detail}")
            await asyncio.sleep(self._poll_interval)

    async def read_rail_pose(self) -> tuple[float, bool]:
        """读地轨11Y 实际位置(mm)与回零标志 (供后端映射所在站; 站位坐标取 rail.yaml 真源)。

        返回:
            (实际位置mm, 已回零)。节点未下载到真机时抛 KeyError, 由调用方兜底。
        """
        pos, homed = await self._driver.read_many(["Rail_ActPos", "Rail_Homed"])
        if pos is None or homed is None:
            # 批读把"没这个节点"降级成 None, 这里还原成调用方约定的 KeyError
            raise KeyError(self._driver.missing_reason("Rail_ActPos")
                           or self._driver.missing_reason("Rail_Homed")
                           or "Rail_ActPos/Rail_Homed 读取返回空 (PLC 未下装?)")
        return float(pos), bool(homed)

    async def read_host_var(self, name: str):
        """读单个 Host_Computer 诊断镜像变量 (设备页附加字段, 如废液传感器/真空泵命令态)。

        节点未下装到真机时 driver 抛错, 由调用方兜底 (置 None + 告警)。
        """
        return await self._driver.read_variable(name)

    async def read_host_array(self, name: str) -> list:
        """读单个 Host_Computer 数组镜像 (设备页展缸阵列, 如 Tank_State/Tank_Drain_Done)。

        参数:
            name: 数组节点名
        返回:
            list, 下标 0 对应 PLC ARRAY[1] (即 1 号缸)

        节点未下装到真机时 driver 抛错, 由调用方兜底 (置 None + 告警)。
        """
        return await self._driver.read_array(name)

    async def read_scrape_axes(self) -> tuple[float, float, float]:
        """读刮板 CNC 三轴实际位置 (mm, Z 正方向向下): 9X/8Y/10Z — 对位检查回显。

        节点由后续 B11 落地; 未下装到真机时 driver 抛 KeyError, 由调用方兜底
        (端点 503 / 动作 ERROR)。
        """
        x = float(await self._driver.read_variable("PhotoScrape_9X_ActPos"))
        y = float(await self._driver.read_variable("PhotoScrape_8Y_ActPos"))
        z = float(await self._driver.read_variable("PhotoScrape_10Z_ActPos"))
        return x, y, z

    async def read_feedlift_pos(self, axis: int) -> float:
        """读升降上下料轴实际位置 (mm): axis=1 → 1Z 上料仓, axis=2 → 2Z 下料仓。

        参数:
            axis: 1=上料仓 1Z, 2=下料仓 2Z
        返回:
            float, 轴实际位置(mm)

        节点由 PLC_MainPRG 每扫描无条件镜像 fActPos, 故任何时刻可读; 但只有在光电
        搜索动作 DONE 后 (停轴并稳定 300ms) 读到的值才对应板堆高度。
        节点未下装到真机时 driver 抛 KeyError, 由调用方兜底。
        """
        if axis not in (1, 2):
            raise ValueError(f"升降轴号应为 1(上料)或 2(下料), 实际为 {axis!r}")
        return float(await self._driver.read_variable(f"FeedLift_{axis}Z_ActPos"))

    async def start_monitoring(self, stations) -> None:
        """显式预订阅一批工位的 L2 状态字段 (可选; 不调用则首次 execute 时懒订阅)."""
        for station in stations:
            await self._ensure_monitored(self._prefix(station))

    async def _ensure_monitored(self, prefix: str) -> None:
        """确保该工位的 L2 状态字段已被订阅 (幂等懒订阅, 供看门狗等待循环本地读镜像)."""
        if prefix in self._monitored:
            return
        await self._driver.add_subscription([f"{prefix}_L2_{f}" for f in _L2_FIELDS])
        self._monitored.add(prefix)

    def _cached_l2(self, prefix: str) -> dict[str, object]:
        """从驱动镜像取该工位 L2 快照 (无网络); 字段名 -> 最新值."""
        vals = self._driver.cached_many([f"{prefix}_L2_{f}" for f in _L2_FIELDS])
        return {f: vals[f"{prefix}_L2_{f}"] for f in _L2_FIELDS}

    # ------------------------------------------------------------------
    # 展缸数组辅助 (多通道展开; 供 ResourceManager / Develop 编排)
    # ------------------------------------------------------------------

    async def read_all_tank_states(self) -> list[int]:
        """一次读取全部 Tank_State 数组 (1-based 对应 1..8 号缸)."""
        return [int(v) for v in await self._driver.read_array("Tank_State")]

    async def read_tank_state(self, tank_id: int) -> int:
        """读取 Tank_State[tank_id] (1-based)."""
        return int(await self._driver.read_array_element("Tank_State", tank_id))

    async def trigger_drain(self, tank_id: int) -> None:
        """触发排液: Tank_Drain_Enable[tank_id]=TRUE."""
        await self._driver.write_array_element("Tank_Drain_Enable", tank_id, True)
        log.info("[PLC] 触发排液: Tank_Drain_Enable[%d]=TRUE", tank_id)

    async def release_tank(self, tank_id: int) -> None:
        """释放展缸: 清排液信号 + Tank_State[tank_id]=0."""
        await self._driver.write_array_element("Tank_Drain_Enable", tank_id, False)
        await self._driver.write_array_element("Tank_State", tank_id, 0)
        log.info("[PLC] 释放展缸: Tank_State[%d]=0, Drain_Enable[%d]=FALSE", tank_id, tank_id)

    # ------------------------------------------------------------------
    # 单次执行实现
    # ------------------------------------------------------------------

    async def _execute_one(
        self, prefix: str, action_code: int, seq: int, params: dict[str, object],
        timeout: float | None, stall_timeout: float | None = None,
    ) -> PLCActionResult:
        await self._prepare_idle(prefix)
        # 订阅本工位 L2 状态字段 (幂等), 种子化镜像; 之后等待终态全程读镜像, 不再忙轮询 PLC
        await self._ensure_monitored(prefix)
        if params:
            await self._driver.write_many(params)
        await self._driver.write_variable(f"{prefix}_L2_ActionCode", action_code)
        await self._driver.write_variable(f"{prefix}_L2_RequestSeq", seq)
        # 写回校验: 确认参数/动作码/序号已落地 (TCP 有序性屏障)
        read_action = int(await self._driver.read_variable(f"{prefix}_L2_ActionCode"))
        read_seq = int(await self._driver.read_variable(f"{prefix}_L2_RequestSeq"))
        if (read_action, read_seq) != (action_code, seq):
            raise RuntimeError(
                f"{prefix} L2 写回校验失败: action={read_action}/{action_code}, seq={read_seq}/{seq}"
            )

        start_write_uncertain = False
        try:
            await self._driver.write_variable(f"{prefix}_L2_Start", True)
        except Exception:
            # Start 写入可能已到 PLC, 只查原序号, 不重发
            start_write_uncertain = True
            log.warning("[%s L2] Start 结果不明确, 查询原 seq=%d", prefix, seq)

        # 启动基线: 直读同步镜像, 避免上一动作滞后的终态被误判为 "终态属于旧 seq" (订阅最终一致)
        await self._driver.refresh_mirror([f"{prefix}_L2_{f}" for f in _L2_FIELDS])

        loop = asyncio.get_running_loop()
        start_ts = loop.time()
        ceiling = start_ts + (self._action_timeout if timeout is None else float(timeout))
        # 停滞判停阈值: per-action 覆盖优先, 否则用构造期全局值 (静默窗口长的动作单独放大)
        stall = self._stall_timeout if stall_timeout is None else float(stall_timeout)
        soft = self._soft_recheck       # 镜像静默软复核间隔 (<=0 关闭)
        last_progress = start_ts        # 上次观测到 PLC 推进 (任一 L2 字段变化) 的时刻
        last_soft = start_ts            # 上次软复核直读的时刻 (限流, 免每拍打网络)
        prev_snap: dict | None = None
        accepted = False
        try:
            while True:
                token = self._driver.change_token()
                snap = self._cached_l2(prefix)
                now = loop.time()
                # 镜像 seeding/refresh 吞过瞬时首读失败时, cached_many 可能返回 None;
                # 此时不做 int() (否则 TypeError 逃逸看门狗), 视为"尚未拿到镜像", 落到下方
                # 死线/停滞/等待分支, 由停滞看门狗兜底为 PLCActionOutcomeUnknown (非 TypeError)。
                have_snap = (
                    snap.get("State") is not None
                    and snap.get("AcceptedSeq") is not None
                    and snap.get("CompletedSeq") is not None
                )
                if have_snap:
                    accepted = accepted or int(snap["AcceptedSeq"]) == seq
                    if snap != prev_snap:           # 任一字段变化 = PLC 在推进, 看门狗复位
                        last_progress = now
                        prev_snap = snap
                    result = self._decide_terminal(prefix, action_code, seq, snap,
                                                   accepted=accepted,
                                                   start_write_uncertain=start_write_uncertain)
                    if result is not None:
                        return result
                hit_ceiling = now >= ceiling               # 绝对上限兜底 (病态挂死)
                hit_stall = now - last_progress >= stall    # 停滞看门狗
                if hit_ceiling or hit_stall:
                    # 超时前直读复核 (结构性修复): 等待循环只读订阅镜像, 若 "进 DONE" 这一次数据变化通知
                    # 被漏推 / 合并, 镜像会停在 RUNNING 造成 "停滞无进度" 假超时。PLC 按下降沿契约在 host
                    # 清 Start 前保持终态, 故此刻直读能看到真终态 —— 把已完成的动作从误判里救回。直读仍非
                    # 本 seq 终态才是真卡, 照常判超时。见 test_plc_l2_missed_done_offline。
                    await self._driver.refresh_mirror([f"{prefix}_L2_{f}" for f in _L2_FIELDS])
                    fresh = self._cached_l2(prefix)
                    if fresh.get("AcceptedSeq") is not None:
                        accepted = accepted or int(fresh["AcceptedSeq"]) == seq
                    result = self._decide_terminal(prefix, action_code, seq, fresh,
                                                   accepted=accepted,
                                                   start_write_uncertain=start_write_uncertain)
                    if result is not None:
                        return result
                    qualifier = "已接受" if accepted else "接受状态未知"
                    if hit_ceiling:
                        raise PLCActionOutcomeUnknown(
                            f"{prefix} L2 seq {seq} 超过绝对上限 {ceiling - start_ts:.0f}s ({qualifier}); 不重发"
                        )
                    raise PLCActionOutcomeUnknown(
                        f"{prefix} L2 seq {seq} 停滞 {stall:.0f}s 无进度 ({qualifier}); 不重发"
                    )

                # 软复核 (漏推 delta 兜底): 镜像已静默超过 soft 且距上次直读复核也超过 soft 时, 主动直读
                # 对账一次 —— 绕开订阅 report-on-change 水位线, 直接问 PLC 当前真值。廉价快判先只读
                # State+CompletedSeq, 疑似本 seq 终态才 full refresh 取准确结果字段, 再交 _decide_terminal
                # 判定 (返回 DONE 结果 / 抛非 DONE 终态)。非终态则本次不判超时 (那是 stall 硬看门狗的职责),
                # 仅刷新镜像让下一拍据真值决策。正常收到通知时 last_progress 持续复位, soft 永不触发 → 快
                # 路径零额外网络; 仅当镜像真静默 (漏推 / PLC 单 pass 长静默) 才 ~1Hz 直读 2 字段, 开销可忽略。
                if soft > 0 and (now - last_progress) >= soft and (now - last_soft) >= soft:
                    last_soft = now
                    try:
                        st = await self._driver.read_variable(f"{prefix}_L2_State")
                        cs = await self._driver.read_variable(f"{prefix}_L2_CompletedSeq")
                    except ConnectionError as exc:
                        # 软复核只是漏推 delta 的辅助对账, 连接中断时放弃本拍即可 (真机曾因
                        # 这里泄漏 "client is disconnected" 把在飞泵动作杀成 ERROR)。动作生死
                        # 交由镜像 (重连后重订阅+种子化会恢复推进) 与 stall/ceiling 预算裁决:
                        # 瞬断存活, 持续断连按停滞判 "结果不明确", 不误分类为普通执行异常。
                        log.warning("[%s L2] 软复核直读遇连接中断, 跳过本拍 seq=%d: %s",
                                    prefix, seq, exc)
                        continue
                    if (st is not None and cs is not None and int(cs) == seq
                            and PLCActionState(int(st)) in self._TERMINAL):
                        await self._driver.refresh_mirror([f"{prefix}_L2_{f}" for f in _L2_FIELDS])
                        fresh = self._cached_l2(prefix)
                        if fresh.get("AcceptedSeq") is not None:
                            accepted = accepted or int(fresh["AcceptedSeq"]) == seq
                        result = self._decide_terminal(prefix, action_code, seq, fresh,
                                                       accepted=accepted,
                                                       start_write_uncertain=start_write_uncertain)
                        if result is not None:
                            return result
                    continue

                # 事件驱动等待: 被下一次订阅变化唤醒, 或到最近死线 / soft 复核点 / poll_interval 复核止 (本地读镜像, 不打网络)
                budget = min(ceiling, last_progress + stall) - now
                if soft > 0:
                    budget = min(budget, last_soft + soft - now)
                if self._poll_interval > 0:
                    budget = min(budget, self._poll_interval)
                if budget > 0:
                    try:
                        await asyncio.wait_for(self._driver.wait_change(token), timeout=budget)
                    except asyncio.TimeoutError:
                        pass
        finally:
            # 终态后清 Start 下降沿 (仅当确认是本序号终态); 结果不明确时保留现场
            try:
                snap = await self.snapshot(prefix)
                terminal = PLCActionState(int(snap["State"])) in self._TERMINAL
                if int(snap["CompletedSeq"]) == seq and terminal:
                    await self._driver.write_variable(f"{prefix}_L2_Start", False)
                    await self._wait_idle(prefix, timeout=2.0)
            except Exception:
                log.warning("[%s L2] 终态下降沿清理未确认 seq=%d", prefix, seq, exc_info=True)

    def _decide_terminal(
        self, prefix: str, action_code: int, seq: int, snap: Mapping[str, object],
        *, accepted: bool, start_write_uncertain: bool,
    ) -> PLCActionResult | None:
        """据一份 L2 快照判定本 seq 是否已到终态 (等待循环与超时前直读复核共用同一判据)。

        返回:
            - 本 seq DONE: PLCActionResult;
            - 尚未终态 (含镜像缺字段): None。
        抛出:
            - 本 seq 非 DONE 终态 (ERROR/REJECTED/INTERRUPTED): PLCActionError;
            - 终态属于旧 seq / Start 写不确定且回到 IDLE: PLCActionOutcomeUnknown。
        """
        # 需全字段就位再判终态: 除决策用的 State/AcceptedSeq/CompletedSeq 外, _result 还读
        # ErrorCode/SafeState/Retryable/Step; 任一镜像项尚为 None 即视为快照未就绪, 返回 None 让
        # 循环/直读复核下一拍再判, 杜绝 int(None) TypeError 逃逸 (镜像逐字段 try/except 落库)。
        if any(snap.get(f) is None for f in _L2_FIELDS):
            return None
        state = PLCActionState(int(snap["State"]))
        completed_seq = int(snap["CompletedSeq"])
        if completed_seq == seq and state in self._TERMINAL:
            result = self._result(prefix, action_code, seq, state, snap)
            if result.ok:
                return result
            raise PLCActionError(result)
        if state in self._TERMINAL and completed_seq != seq:
            raise PLCActionOutcomeUnknown(
                f"{prefix} L2 终态属于旧 seq {completed_seq}, 期望 {seq}; 不重发"
            )
        if start_write_uncertain and not accepted and state is PLCActionState.IDLE:
            raise PLCActionOutcomeUnknown(f"{prefix} L2 无法证明 seq {seq} 已被接受; 不重发")
        return None

    async def _prepare_idle(self, prefix: str) -> None:
        """启动前确保 Start=FALSE 且 State=IDLE.

        超时几乎必是上一个动作卡死在 RUNNING: PLC FSM 的 RUNNING 态只认 {prefix}_L2_Reset、
        不认 Start 落沿 (终态才认落沿), 故 Start:=False 救不回来。此处把无法自愈的这一档直接在
        报错里引导操作员去设备页对该工位执行"复位(清L2故障)" (脉冲 L2_Reset), 见
        controller.reset / api /plc/stations/{station}/reset。"""
        await self._driver.write_variable(f"{prefix}_L2_Start", False)
        try:
            await self._wait_idle(prefix, timeout=2.0)
        except TimeoutError:
            raise TimeoutError(
                f"{prefix} L2 未回到 IDLE (工位可能卡在 RUNNING); "
                f"请切 DEBUG 模式, 在设备页对该工位执行『复位(清L2故障)』后重试"
            ) from None

    async def _wait_idle(self, prefix: str, *, timeout: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            state = PLCActionState(int(await self._driver.read_variable(f"{prefix}_L2_State")))
            if state is PLCActionState.IDLE:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"{prefix} L2 未回到 IDLE")
            await asyncio.sleep(self._poll_interval)

    async def _allocate_seq(self, prefix: str) -> int:
        """分配单调序号; 首次从 PLC 现值恢复, 避免与历史结果混淆."""
        if prefix not in self._next_seq:
            values = await asyncio.gather(
                self._driver.read_variable(f"{prefix}_L2_RequestSeq"),
                self._driver.read_variable(f"{prefix}_L2_AcceptedSeq"),
                self._driver.read_variable(f"{prefix}_L2_CompletedSeq"),
            )
            self._next_seq[prefix] = max(int(v) for v in values) + 1
        seq = self._next_seq[prefix]
        if seq > 2_147_483_647:
            raise OverflowError(f"{prefix} L2 请求序号耗尽")
        self._next_seq[prefix] = seq + 1
        return seq

    async def _allocate_deploy_seq(self) -> int:
        """分配系统级下载握手序号；首次从 PLC 请求/接受值恢复。"""
        if self._next_deploy_seq is None:
            request_seq, accepted_seq = await asyncio.gather(
                self._driver.read_variable("PLC_Deploy_RequestSeq"),
                self._driver.read_variable("PLC_Deploy_AcceptedSeq"),
            )
            self._next_deploy_seq = max(int(request_seq), int(accepted_seq)) + 1
        seq = self._next_deploy_seq
        if seq > 2_147_483_647:
            raise OverflowError("PLC 下载准备请求序号耗尽")
        self._next_deploy_seq = seq + 1
        return seq

    def _prefix(self, station: str) -> str:
        """工位名 -> L2 变量前缀 (未命中按精确前缀)."""
        return self._prefix_map.get(station.strip().lower(), station.strip())

    @staticmethod
    def _result(prefix, action_code, seq, state, snap: Mapping[str, object]) -> PLCActionResult:
        return PLCActionResult(
            station=prefix,
            action_code=action_code,
            request_seq=seq,
            state=state,
            error_code=int(snap["ErrorCode"]),
            safe_state=PLCActionSafeState(int(snap["SafeState"])),
            retryable=bool(snap["Retryable"]),
            step=int(snap["Step"]),
        )
