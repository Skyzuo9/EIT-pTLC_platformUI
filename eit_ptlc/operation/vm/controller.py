"""mini-VM 调试控制器
====================
功能:
    管理按 run_id 索引的活动 VmThread 与其驱动任务, 对外暴露调试动词:
    start / step / run(resume) / pause / stop / reset(含复位到节点) / human_reply / state / vars /
    set_breakpoints. 并提供 run_sample 适配现有 Scheduler 的 RunnerCallable 形态.

说明:
    单事件循环内驱动; step/reset 后会让出事件循环直至线程停驻或终止 (_settle), 以便返回稳定的 IP.
    自由运行 (run/resume) 不阻塞等待完成.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Callable, Optional

from eit_ptlc.operation.vm.state import VmStatus
from eit_ptlc.operation.vm.thread import VmThread
from eit_ptlc.runtime.maintenance_gate import MaintenanceActiveError

log = logging.getLogger(__name__)

# 停驻或终止态 (可作为 _settle 的返回条件)
_SETTLED = {VmStatus.STOPPED, VmStatus.PAUSED, VmStatus.WAITING_HUMAN,
            VmStatus.DONE, VmStatus.ERROR, VmStatus.KILLED}

# 最终态 (不可再恢复): 可安全淘汰其运行态; STOPPED/PAUSED/WAITING_HUMAN 仍可 resume 故不算
_FINAL = {VmStatus.DONE, VmStatus.ERROR, VmStatus.KILLED}

# 保留最近运行 (含已完成) 上限; 超出则淘汰最旧的最终态运行, 防常驻进程内存无界增长
_MAX_RETAINED_RUNS = 128


class VmController:
    """VM 运行/调试控制器 (持有活动线程与任务)."""

    def __init__(
        self,
        *,
        executor,
        res_gate,
        resolve_script: Optional[Callable[[str], dict]] = None,
        event_sink: Optional[Callable[[dict], None]] = None,
        mode_provider: Optional[Callable[[], Optional[str]]] = None,
        time_fn: Callable[[], float] = time.time,
        maintenance_gate=None,
    ) -> None:
        self._executor = executor
        self._res_gate = res_gate
        self._resolve = resolve_script
        self._emit = event_sink or (lambda e: None)
        self._mode_provider = mode_provider
        self._time = time_fn
        self._maintenance_gate = maintenance_gate
        self._threads: dict[str, VmThread] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._docs: dict[str, dict] = {}
        self._inputs: dict[str, dict] = {}
        # 运行前旋钮覆盖 (run_id -> {名: 值}); 与 _inputs 并列, 复位重跑参数不丢。
        self._overrides: dict[str, dict] = {}
        # reset 复用 run_id；代次跨 VmThread 单调递增，供前端拒绝旧执行快照。
        self._execution_generations: dict[str, int] = {}
        # 当前挂起类型 (run_id -> "frozen" 冻结在飞运动 / "at_boundary" 跑完当前动作停在边界);
        # 供前端据此决定"继续"按钮语义 (冻结续跑 vs 放行下一动作)。缺省即无挂起。
        self._hold: dict[str, str] = {}
        # 运行元信息 (run_id -> {origin/sample_id/batch_id...}): 调度器自报, 随
        # operation_start 外发; 与 _inputs 并列存留, 复位重跑 (reset->_new_thread) 不丢。
        self._metas: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def _new_thread(self, doc: dict, run_id: str, overrides: Optional[dict] = None,
                    preset_vars: Optional[dict] = None) -> VmThread:
        generation = self._execution_generations.get(run_id, 0) + 1
        self._execution_generations[run_id] = generation
        return VmThread(doc, executor=self._executor, res_gate=self._res_gate,
                        resolve_script=self._resolve, emit=self._emit, run_id=run_id,
                        mode_provider=self._mode_provider, time_fn=self._time,
                        overrides=overrides, execution_generation=generation,
                        meta=self._metas.get(run_id), preset_vars=preset_vars)

    async def start(self, doc: dict, inputs: Optional[dict] = None, *,
                    mode_run: str = "run", run_id: Optional[str] = None,
                    start_aid: Optional[str] = None, overrides: Optional[dict] = None,
                    meta: Optional[dict] = None, preset_vars: Optional[dict] = None) -> dict:
        """启动一次脚本运行.

        参数:
            doc: 脚本节点树; inputs: in 变量入参; mode_run: run (自由运行) | step (停在首叶子)
            start_aid: 从该 AID 起跑 (结构化快进, 跳过其前设备/人工叶子); None 则从头
            overrides: 运行前旋钮覆盖 (名 -> 值); 建帧时按名注入带 ui 的 in var, 深层子脚本亦可达
            meta: 运行元信息 (origin/sample_id/batch_id 等), 非空时随 operation_start 外发
            preset_vars: 断点续跑的根帧变量回注 (名 -> 值); 与 start_aid 配套, 补齐被快进
                跳过的 call/run_script 本应产出的中间变量
        返回:
            {run_id, status, current_aid}
        """
        activity_lease = self._enter_activity("流程运行")
        run_id = run_id or uuid.uuid4().hex[:12]
        try:
            self._overrides[run_id] = dict(overrides or {})
            if meta:
                self._metas[run_id] = dict(meta)
            thread = self._new_thread(doc, run_id, self._overrides[run_id],
                                      preset_vars=preset_vars)
            if mode_run == "step":
                thread._step_mode = True
            if start_aid:
                thread._skip_to = start_aid
            self._threads[run_id] = thread
            self._docs[run_id] = doc
            self._inputs[run_id] = dict(inputs or {})
            self._tasks[run_id] = asyncio.create_task(
                self._drive(run_id, thread, dict(inputs or {}), activity_lease)
            )
        except BaseException:
            self._leave_activity(activity_lease)
            raise
        self._purge()
        if mode_run == "step":
            await self._settle(thread)
        else:
            await asyncio.sleep(0)
        return self._state(thread)

    async def _drive(self, run_id: str, thread: VmThread, inputs: dict,
                     activity_lease=None) -> None:
        try:
            await thread.run(inputs)
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("[VM] 运行 %s 异常", run_id)
        finally:
            self._leave_activity(activity_lease)

    async def _settle(self, thread: VmThread) -> None:
        """让出事件循环直至线程停驻或终止 (轻量轮询, 避免在真实设备调用期间空转)."""
        for _ in range(600_000):
            if thread.status in _SETTLED:
                return
            await asyncio.sleep(0.002)

    # ------------------------------------------------------------------
    # 调试动词
    # ------------------------------------------------------------------

    async def step(self, run_id: str) -> dict:
        thread = self._get(run_id)
        if thread.status in (VmStatus.STOPPED, VmStatus.PAUSED):
            thread.step()
            await self._settle(thread)
        return self._state(thread)

    async def step_over(self, run_id: str) -> dict:
        """单步步过: run_script 子脚本一次跑完, 停在父流程下一叶子 (子脚本内部不逐叶停驻)."""
        thread = self._get(run_id)
        if thread.status in (VmStatus.STOPPED, VmStatus.PAUSED):
            thread.step_over()
            await self._settle(thread)
        return self._state(thread)

    async def run(self, run_id: str) -> dict:
        """自由运行 / 从停驻恢复 (不阻塞等待完成)."""
        thread = self._get(run_id)
        self._set_hold(run_id, None)
        if thread.status in (VmStatus.STOPPED, VmStatus.PAUSED):
            thread.cont()
            await asyncio.sleep(0)
        return self._state(thread)

    async def pause(self, run_id: str) -> dict:
        """暂停 (冻结): 立即冻结在飞机器人运动 (Pause), 配合 resume 从冻结点续跑.

        作用于运动中途, 不等当前动作做完; 机器人无运动时为安全空操作。
        """
        thread = self._get(run_id)
        await self._robot_preempt("robot_pause")
        self._set_hold(run_id, "frozen")
        return self._state(thread)

    async def stop_after(self, run_id: str) -> dict:
        """运行后停止 (边界): 跑完当前动作后停在动作边界, 可 resume 放行下一动作.

        即旧"暂停"语义 (下一个叶子 checkpoint 停驻); 当前在飞动作不被打断。
        """
        thread = self._get(run_id)
        thread.pause()
        self._set_hold(run_id, "at_boundary")
        return self._state(thread)

    async def resume(self, run_id: str) -> dict:
        """继续: 按当前挂起类型恢复 —— 冻结则续跑机器人, 边界/单步停驻则放行 VM."""
        if self._hold.get(run_id) == "frozen":
            thread = self._get(run_id)
            await self._robot_preempt("robot_resume")
            self._set_hold(run_id, None)
            return self._state(thread)
        return await self.run(run_id)

    async def terminate(self, run_id: str) -> dict:
        """终止运行: 软停机器人 (Stop, 臂保持使能、不报警) + 熄火在跑的刮取 CNC + 干净结束本次运行 (KILLED, 不可继续)."""
        thread = self._get(run_id)
        thread.mark_terminating()
        await self._robot_preempt("robot_stop")
        await self._robot_preempt("plc_abort_scrape")
        await self._hard_cancel(run_id)
        self._set_hold(run_id, None)
        return self._state(thread)

    async def estop(self, run_id: str, pressed: bool = True) -> dict:
        """急停: EmergencyStop (失能臂并报警) + 熄火在跑的刮取 CNC + 结束本次运行; 释放后需清警重新使能."""
        thread = self._get(run_id)
        thread.mark_terminating()
        await self._robot_preempt("robot_estop", pressed)
        await self._robot_preempt("plc_abort_scrape")
        await self._hard_cancel(run_id)
        self._set_hold(run_id, None)
        return self._state(thread)

    async def _robot_preempt(self, method_name: str, *args) -> None:
        """调用 executor 上的中止类薄封装; executor 未提供 (如离线 fake) 时安全跳过.

        名为 robot 是历史原因: 现也用于 plc_abort_scrape (刮取 CNC 熄火)。各封装自身负责
        best-effort 降级 —— 设备离线不得反噬调用方, 否则 terminate/estop 会被整体阻断。
        """
        fn = getattr(self._executor, method_name, None)
        if fn is None:
            return
        await fn(*args)

    async def stop(self, run_id: str) -> dict:
        """兼容旧端点: 等价于 terminate (软停机器人 + 干净结束)."""
        return await self.terminate(run_id)

    async def _hard_cancel(self, run_id: str) -> None:
        """取消驱动任务并等其退出 (脚本协程层收尾; 不直接操作机器人)."""
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _set_hold(self, run_id: str, kind: str | None) -> None:
        """更新挂起类型并外发 vm_hold 事件 (前端据此切换'继续'语义与按钮态)."""
        if kind:
            self._hold[run_id] = kind
        else:
            self._hold.pop(run_id, None)
        thread = self._threads.get(run_id)
        self._emit({"type": "vm_hold", "run_id": run_id, "hold": kind or "none",
                    "execution_generation": thread.execution_generation if thread else 0,
                    "ts": self._time()})

    async def reset(self, run_id: str, aid: Optional[str] = None) -> dict:
        """复位: 停掉当前线程, 用同脚本同入参重建并以单步模式停在首叶子; 给定 aid 则结构化快进至该节点."""
        await self.stop(run_id)
        activity_lease = self._enter_activity("流程复位重跑")
        try:
            thread = self._new_thread(self._docs[run_id], run_id, self._overrides.get(run_id))
            thread._step_mode = True
            if aid:
                thread._skip_to = aid
            self._threads[run_id] = thread
            self._tasks[run_id] = asyncio.create_task(
                self._drive(run_id, thread, self._inputs[run_id], activity_lease)
            )
        except BaseException:
            self._leave_activity(activity_lease)
            raise
        await self._settle(thread)
        return self._state(thread)

    async def human_reply(self, run_id: str, req_id: str, payload: dict) -> dict:
        thread = self._get(run_id)
        ok = thread.human_reply(req_id, payload)
        if ok and thread._step_mode:
            await self._settle(thread)
        else:
            await asyncio.sleep(0)
        return {"accepted": ok, **self._state(thread)}

    def set_breakpoints(self, run_id: str, aids) -> dict:
        thread = self._get(run_id)
        thread.set_breakpoints(aids)
        return {"run_id": run_id, "breakpoints": sorted(thread.breakpoints)}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def wait_final(self, run_id: str, *, timeout: float | None = None) -> dict:
        """等一次运行走到最终态 (DONE/ERROR/KILLED), 返回其状态。

        参数:
            run_id: start() 返回的运行标识
            timeout: 秒; None 为不限。超时**不取消运行** —— 物理动作正在跑, 掐掉它
                只会留下一个说不清的中间态。超时抛 TimeoutError, 运行继续, 调用方按
                run_id 去事件流/运行历史里跟。
        返回:
            _state(thread) 同形 dict

        用途: 让"点一次按钮跑完一条短流程"的同步调用方 (如板仓标定采样路由) 既走 VM
        拿到事件、历史与回放, 又能像直调执行器那样一次请求返回结果。需要中途单步或
        人工交互的运行不该用它 —— 那是调试端点 + WS 事件流的活。
        """
        task = self._tasks.get(run_id)
        thread = self._get(run_id)                     # 不存在即 KeyError, 与其余查询一致
        if task is not None and not task.done():
            # shield: wait_for 超时时取消的是外层壳而非 _drive 本身, 运行不受影响
            await asyncio.wait_for(asyncio.shield(task), timeout)
        return self._state(thread)

    def state(self, run_id: str) -> dict:
        return self._state(self._get(run_id))

    def vars(self, run_id: str) -> dict:
        thread = self._get(run_id)
        return {"run_id": run_id, "script": thread.current_script(), "vars": thread.snapshot_vars()}

    def active(self) -> dict:
        """非终态运行列表, 供前端刷新/断线重连后重建 HITL 弹窗与调试状态 (rehydrate).

        返回:
            {"runs": [_state + {"operation": 根脚本名}]}; operation 与 operation_start
            事件同源 (根 doc 的 name), 供前端 DebugDock 归属判定 (isRunActiveElsewhere)。
            终态 (DONE/ERROR/KILLED) 即使仍驻留 _threads (未被 _purge 淘汰) 也不出现。
        """
        runs = []
        for run_id, thread in self._threads.items():
            if thread.status in _FINAL:
                continue
            runs.append({**self._state(thread),
                         "operation": self._docs.get(run_id, {}).get("name", "")})
        return {"runs": runs}

    def _state(self, thread: VmThread) -> dict:
        return {"run_id": thread.run_id, "status": thread.status.value,
                "current_aid": thread.current_aid, "script": thread.current_script(),
                "stack_depth": len(thread.stack), "hold": self._hold.get(thread.run_id, "none"),
                "active_nodes": thread.active_nodes(),
                "active_revision": thread.active_revision,
                "execution_generation": thread.execution_generation,
                "pending_human": thread.pending_human_request}

    def _get(self, run_id: str) -> VmThread:
        thread = self._threads.get(run_id)
        if thread is None:
            raise KeyError(f"无此运行: {run_id}")
        return thread

    def _forget(self, run_id: str) -> None:
        """从所有按 run_id 索引的表移除一次运行 (释放 VmThread/Task/doc/inputs/overrides/hold)."""
        self._threads.pop(run_id, None)
        self._tasks.pop(run_id, None)
        self._docs.pop(run_id, None)
        self._inputs.pop(run_id, None)
        self._overrides.pop(run_id, None)
        self._execution_generations.pop(run_id, None)
        self._hold.pop(run_id, None)
        self._metas.pop(run_id, None)

    def _purge(self) -> None:
        """驻留运行数超上限时淘汰最旧的最终态运行 (dict 保序, 最旧在前); 未终结的绝不淘汰."""
        if len(self._threads) <= _MAX_RETAINED_RUNS:
            return
        for run_id in list(self._threads):
            if len(self._threads) <= _MAX_RETAINED_RUNS:
                break
            thread = self._threads.get(run_id)
            task = self._tasks.get(run_id)
            if thread is not None and thread.status in _FINAL and (task is None or task.done()):
                self._forget(run_id)

    # ------------------------------------------------------------------
    # Scheduler 适配 (样品级编排)
    # ------------------------------------------------------------------

    async def run_sample(self, request) -> None:
        """作为 Scheduler 的 RunnerCallable: 以 operation 脚本执行一个样品请求至完成.

        参数:
            request: 含 sample_id / params / recipe(脚本名) 的样品请求
        """
        activity_lease = self._enter_activity("样品流程运行")
        try:
            doc = self._resolve(getattr(request, "recipe", None) or "ptlc_full")
            run_id = f"sample-{getattr(request, 'sample_id', uuid.uuid4().hex[:8])}"
            thread = self._new_thread(doc, run_id)
            self._threads[run_id] = thread
            self._docs[run_id] = doc
            self._inputs[run_id] = dict(getattr(request, "params", {}) or {})
            self._purge()
            await thread.run(self._inputs[run_id])
        finally:
            self._leave_activity(activity_lease)

    def _enter_activity(self, operation: str):
        """Atomically register a VM lifetime before allocating or resuming execution."""
        gate = self._maintenance_gate
        if gate is None:
            return None
        lease = gate.try_enter_activity(operation)
        if lease is None:
            raise MaintenanceActiveError(
                f"PLC 下载维护态已锁定，拒绝{operation}: "
                f"{gate.reason or '等待 PLC 重新启动并就绪'}"
            )
        return lease

    def _leave_activity(self, lease) -> None:
        if self._maintenance_gate is not None and lease is not None:
            self._maintenance_gate.leave_activity(lease)
