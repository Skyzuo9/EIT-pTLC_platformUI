"""
Scheduler - 样品队列调度器
============================
asyncio.Queue + 并发任务池。

设计约束：
- 多样品可同时运行（并发任务池），由 DevelopStage._prep_lock / _group_locks 互斥
- ResourceManager.allocate 自然限流：无可用缸时等待释放
- 状态变更通过 LogStore 记录（不侵入 SampleTask 内部）
- PLCClient 只有一个实例，由 Scheduler 持有并传入各 SampleTask

Batch 5 新增：
- resume_confirm 回调：PLC 重连成功后询问是否继续队列
- 订阅 PLCClient.on_state_change：进入 RECONNECTING 暂停取新样品
- abort 机制：resume_confirm=False 或外部调用时立即结束 run_until_empty

Parallel 分支新增：
- run_until_empty() 改为并发任务池：create_task + asyncio.wait(FIRST_COMPLETED)
- active 样品跟踪：_active dict（sample_id → asyncio.Task）
- active_sample_ids 属性供 UI 查询
"""

import asyncio
import copy
import logging
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional, TYPE_CHECKING

from core.log_store import LogStore
from core.plc_client import PLCClient, PLCState
from core.recipe import RecipeTemplate
from core.resource_manager import ResourceManager
from core.task import RecipeTask, SampleTask
from core.vision_service import VisionService

if TYPE_CHECKING:
    from core.camera_service import CameraService

log = logging.getLogger(__name__)

# 人工确认回调类型（与 task.py 保持一致）
ConfirmCallback = Callable[[SampleTask], Awaitable[bool]]

# 重连恢复确认回调：询问用户是否继续执行剩余队列
ResumeConfirmCallback = Callable[[], Awaitable[bool]]


@dataclass
class SampleRequest:
    """入队请求，包含单个样品所需的全部参数。

    Batch 6 Phase C：新增 recipe 字段（可选）。
        - None      → 走旧 SampleTask 路径（Batch 2-4 向后兼容）
        - 非 None   → 走 RecipeTask 分派器，Scheduler.enqueue 会自动 deepcopy 快照
    """
    sample_id: str
    before_path: Path
    after_path: Path
    action_timeout: float = 30.0
    recipe: Optional[RecipeTemplate] = None


class Scheduler:
    """样品队列调度器。

    使用方式：
        scheduler = Scheduler(plc, vision, confirm_callback, log_store)
        await scheduler.enqueue(SampleRequest("S001", before, after))
        await scheduler.enqueue(SampleRequest("S002", before, after))
        await scheduler.run_until_empty()   # 阻塞直至所有任务完成

    参数：
        plc              : 已连接的 PLCClient 实例
        vision           : VisionService 实例
        confirm_callback : 视觉失败时的人工确认回调
        log_store        : LogStore 实例，记录状态变更与关键事件
        resume_confirm   : PLC 重连成功后是否继续队列的回调；None 表示默认继续
    """

    def __init__(
        self,
        plc: PLCClient,
        vision: VisionService,
        confirm_callback: Optional[ConfirmCallback],
        log_store: LogStore,
        resume_confirm: Optional[ResumeConfirmCallback] = None,
        resource_manager: Optional[ResourceManager] = None,
        camera: Optional["CameraService"] = None,
        sample_store=None,
        consumable_manager=None,
        robot_runtime=None,
    ) -> None:
        self._plc = plc
        self._vision = vision
        self._camera = camera
        self._confirm_callback = confirm_callback
        self._log = log_store
        self._resume_confirm = resume_confirm
        self._resource_manager = resource_manager or ResourceManager(plc)
        self._sample_store = sample_store
        self._consumable_manager = consumable_manager
        self._robot_runtime = robot_runtime
        if robot_runtime is not None:
            from core.plc_action_client import PLCActionClient
            from core.robot_business_resources import RobotBusinessResourceLedger
            self._plc_action_client = PLCActionClient(plc)
            self._robot_resources = RobotBusinessResourceLedger()
        else:
            self._plc_action_client = None
            self._robot_resources = None
        self._queue: asyncio.Queue[SampleRequest] = asyncio.Queue()

        # 暂停/恢复事件：set=可继续取下一个样品，clear=暂停等待
        self._pause_evt = asyncio.Event()
        self._pause_evt.set()
        self._aborted = False

        # 并发任务池：{sample_id: asyncio.Task}
        self._active: dict[str, asyncio.Task] = {}

        # 入队唤醒事件：enqueue() 时 set，唤醒 asyncio.wait 以便立即 drain 新样品
        self._enqueue_evt = asyncio.Event()

        # 已取消的样品 ID 集合（P1：取消 PENDING 样品功能）
        self._cancelled_ids: set[str] = set()

        # E-Stop 急停标志（可恢复暂停，区别于 _aborted 的永久终止）
        self._estop_active: bool = False

        # 订阅 PLC 状态迁移（多订阅，UI 可追加自己的监听）
        plc.add_state_listener(self._on_plc_state_change)

    # ------------------------------------------------------------------
    # 入队
    # ------------------------------------------------------------------

    async def enqueue(self, request: SampleRequest) -> None:
        """将样品请求放入队列。

        奥卡姆修订 4：request.recipe 非空时 deepcopy 一份快照，UI 后续对
        RecipeTemplate 的编辑不会回及已入队样品。
        """
        if request.recipe is not None:
            # deepcopy 整个 request（包含 recipe 子树）；非 recipe 字段代价很小
            request = copy.deepcopy(request)
        await self._queue.put(request)
        self._enqueue_evt.set()  # 唤醒 run_until_empty 中的 asyncio.wait
        self._log.append(request.sample_id, "ENQUEUED", f"队列长度={self._queue.qsize()}")
        log.info("[Scheduler] 入队: %s（当前队列长度=%d）", request.sample_id, self._queue.qsize())

    def qsize(self) -> int:
        """当前队列残余样品数（公开给压测/UI 使用）。"""
        return self._queue.qsize()

    def running_sample_ids(self) -> set[str]:
        """返回当前活跃任务的 sample_id 集合（调用者取读冻结快照）。

        供 Recovery UI 诊断“孤儿 handoff”使用——某缸 handoff_pending=True 但
        其 sample_id 不在本集合 ⇒ 该样品任务已下台，需人工介入。
        """
        return set(self._active.keys())

    def cancel_sample(self, sample_id: str) -> bool:
        """取消已入队但未开始执行的 PENDING 样品。

        Returns True: 成功标记为取消; False: 样品已在执行中或不存在。
        """
        if sample_id in self._active:
            log.warning("[Scheduler] 样品 %s 正在执行中，无法取消", sample_id)
            return False
        self._cancelled_ids.add(sample_id)
        log.info("[Scheduler] 样品 %s 已标记为取消", sample_id)
        return True

    def cancel_running_sample(self, sample_id: str) -> bool:
        """取消正在执行中的 RUNNING 样品（通过 task.cancel() 触发 CancelledError）。

        适用于并发模型下样品在等锁期间被用户主动取消的场景。
        Returns True: 成功触发取消; False: 样品不在活跃列表中。
        """
        task = self._active.get(sample_id)
        if task is None:
            log.warning("[Scheduler] 样品 %s 不在活跃任务中，无法取消", sample_id)
            return False
        task.cancel()
        log.info("[Scheduler] 样品 %s 的任务已 cancel()", sample_id)
        return True

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def active_sample_ids(self) -> list[str]:
        """当前正在执行的样品ID列表（供UI查询）。"""
        return list(self._active.keys())

    async def run_until_empty(self) -> None:
        """并发任务池：同时启动所有队列样品，由锁/RM 自然限流。

        循环逻辑：
        1. 从队列取新样品 → create_task 启动
        2. asyncio.wait 同时监听「任务完成」+「新样品入队」
        3. 新入队 → 立即 drain 并 create_task；任务完成 → 清理
        """
        log.info("[Scheduler] 开始执行，共 %d 个样品", self._queue.qsize())

        while (not self._queue.empty() or self._active) and not self._aborted:
            # 若 PLC 进入 RECONNECTING，等待恢复
            if not self._pause_evt.is_set():
                log.warning("[Scheduler] 队列已暂停，等待 PLC 恢复...")
                await self._pause_evt.wait()
                if self._aborted:
                    break

            # E-Stop 激活时，等待解除（不退出循环，保留队列）
            if self._estop_active and not self._active:
                log.info("[Scheduler] E-Stop 激活中，等待解除...")
                await asyncio.sleep(0.5)
                continue

            # 从队列取新样品启动（不限数量，由 RM.allocate + 锁自然限流）
            self._enqueue_evt.clear()
            while not self._queue.empty() and not self._aborted and not self._estop_active:
                request = await self._queue.get()
                # P1：检查样品是否已被取消
                if request.sample_id in self._cancelled_ids:
                    self._cancelled_ids.discard(request.sample_id)
                    self._log.append(request.sample_id, "CANCELLED", "队列中取消，未启动")
                    self._queue.task_done()
                    log.info("[Scheduler] 样品 %s 已取消，跳过启动", request.sample_id)
                    continue
                t = asyncio.create_task(
                    self._run_one(request), name=f"recipe-{request.sample_id}"
                )
                self._active[request.sample_id] = t
                self._log.append(request.sample_id, "LAUNCHED", "并发任务已启动")
                log.info("[Scheduler] 并发启动: %s", request.sample_id)

            if not self._active:
                break

            # 同时等待：任一任务完成 OR 新样品入队
            async def _wait_enqueue() -> None:
                await self._enqueue_evt.wait()

            enqueue_watcher = asyncio.create_task(_wait_enqueue())
            try:
                done, _ = await asyncio.wait(
                    set(self._active.values()) | {enqueue_watcher},
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                # 确保 watcher 被清理
                if not enqueue_watcher.done():
                    enqueue_watcher.cancel()
                    try:
                        await enqueue_watcher
                    except (asyncio.CancelledError, Exception):
                        pass

            # 处理已完成的 recipe 任务（跳过 watcher）
            for t in done:
                if t is enqueue_watcher:
                    # 新样品入队信号，回到循环顶部 drain
                    log.info("[Scheduler] 收到入队唤醒，回顶部 drain 新样品")
                    continue
                sid = next(
                    (s for s, task in self._active.items() if task is t),
                    None,
                )
                if sid is None:
                    log.warning("[Scheduler] done 任务不在 _active 中: %s", t.get_name())
                    continue
                del self._active[sid]
                self._queue.task_done()
                # 异常已在 _run_one 内捕获记录，此处仅清理
                log.info("[Scheduler] 样品 %s 执行完毕（并发池剩余 %d）", sid, len(self._active))

        if self._aborted:
            # 取消所有活跃任务
            cancelled_count = len(self._active)
            for sid, t in list(self._active.items()):
                t.cancel()
            # 等待被取消任务的 finally 块执行完毕（含展缸释放）
            if self._active:
                await asyncio.gather(*self._active.values(), return_exceptions=True)
            self._active.clear()
            remaining = self._queue.qsize()
            log.warning(
                "[Scheduler] 队列被中止，已取消 %d + 未执行 %d",
                cancelled_count, remaining,
            )
            self._log.append(
                "SYSTEM", "QUEUE_STOPPED",
                f"已取消 {cancelled_count}，未执行 {remaining}",
            )
        else:
            log.info("[Scheduler] 全部样品执行完毕")

    def abort(self) -> None:
        """外部调用：中止后续样品执行（当前正在跑的样品不被打断）。"""
        self._aborted = True
        self._pause_evt.set()  # 唤醒等待

    # ------------------------------------------------------------------
    # E-Stop 急停控制（供 core/estop.py 调用）
    # ------------------------------------------------------------------

    def estop_activate(self) -> None:
        """激活 E-Stop：取消所有运行中任务 + 暂停调度。

        由 EstopBroadcaster.broadcast_estop() 调用。
        与 abort() 不同，E-Stop 是可恢复的暂停——解除后可继续调度队列中样品。
        """
        self._estop_active = True
        cancelled_count = 0
        for sid, task in list(self._active.items()):
            if not task.done():
                task.cancel()
                cancelled_count += 1
                log.warning("[Scheduler] E-Stop 取消运行中任务: %s", sid)
        self._log.append(
            "SYSTEM", "ESTOP_ACTIVATE",
            f"急停触发，已取消 {cancelled_count} 个运行中任务",
        )
        log.critical("[Scheduler] E-Stop 已激活，取消 %d 个任务，暂停调度", cancelled_count)

    def estop_deactivate(self) -> None:
        """解除 E-Stop：恢复调度能力。

        由 EstopBroadcaster.reset_estop() 调用（人工确认安全后）。
        仅清除暂停标志，不自动启动新任务——下一轮循环自然恢复。
        """
        self._estop_active = False
        self._log.append("SYSTEM", "ESTOP_DEACTIVATE", "急停解除，调度恢复")
        log.info("[Scheduler] E-Stop 已解除，调度恢复")

    # ------------------------------------------------------------------
    # PLC 状态订阅
    # ------------------------------------------------------------------

    async def _on_plc_state_change(self, state: PLCState) -> None:
        """响应 PLC 状态变更。"""
        if state == PLCState.RECONNECTING:
            log.warning("[Scheduler] PLC 进入 RECONNECTING，暂停取新样品")
            self._pause_evt.clear()
            self._log.append("SYSTEM", "PLC_RECONNECTING", "PLC 心跳失联，队列暂停")
        elif state == PLCState.CONNECTED:
            # 首次 CONNECTED（启动时）也会进到这里，此时 pause_evt 本就是 set，跳过
            if self._pause_evt.is_set():
                return
            self._log.append("SYSTEM", "PLC_RECONNECTED", "PLC 重连成功")
            should_continue = True
            if self._resume_confirm is not None:
                try:
                    should_continue = await self._resume_confirm()
                except Exception as e:
                    log.warning("[Scheduler] resume_confirm 回调异常: %s", e)
                    should_continue = True
            if should_continue:
                log.info("[Scheduler] 恢复取样")
                self._log.append("SYSTEM", "QUEUE_RESUMED", "用户选择继续")
                self._pause_evt.set()
            else:
                log.warning("[Scheduler] 用户选择停止队列")
                self._aborted = True
                self._pause_evt.set()
        elif state == PLCState.ERROR:
            log.error("[Scheduler] PLC 进入 ERROR 态，中止队列")
            self._aborted = True
            self._pause_evt.set()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _run_one(self, request: SampleRequest) -> None:
        """执行单个样品，捕获异常并记录日志，不向上传播。

        Batch 6 Phase C：根据 request.recipe 是否存在分派：
          - recipe is None  → 旧 SampleTask 四步状态机（Batch 2 路径）
          - recipe 非空     → RecipeTask 多阶段分派器（Batch 6 路径）
        """
        if request.recipe is not None:
            await self._run_recipe_task(request)
        else:
            await self._run_sample_task(request)

    async def _run_sample_task(self, request: SampleRequest) -> None:
        """旧路径：Batch 2 的 SampleTask 四步状态机。"""
        task = SampleTask(
            sample_id=request.sample_id,
            before_path=request.before_path,
            after_path=request.after_path,
            plc=self._plc,
            vision=self._vision,
            camera=self._camera,
            confirm_callback=self._wrapped_confirm(request.sample_id),
            action_timeout=request.action_timeout,
            resource_manager=self._resource_manager,
        )

        try:
            await task.run()
            # 视觉结果记录
            vr = task.vision_result
            if vr and vr.ok:
                self._log.append(
                    request.sample_id, "VISION_OK",
                    f"X={vr.x:.3f} Y={vr.y:.3f} conf={vr.confidence:.3f}",
                )
            elif vr:
                self._log.append(request.sample_id, "VISION_FAIL", "视觉分析失败")
            self._log.append(
                request.sample_id, "DONE",
                self._format_vision(task),
            )
        except Exception as e:
            self._log.append(request.sample_id, "ERROR", str(e))
            log.error("[Scheduler] 样品 %s 执行失败: %s", request.sample_id, e)

    async def _run_recipe_task(self, request: SampleRequest) -> None:
        """新路径：Batch 6 Phase C 基于 RecipeTemplate 的多阶段分派器。"""
        task = RecipeTask(
            sample_id=request.sample_id,
            recipe=request.recipe,
            plc=self._plc,
            log_store=self._log,
            vision=self._vision,
            camera=self._camera,
            before_path=request.before_path,
            after_path=request.after_path,
            confirm_callback=self._wrapped_confirm_by_id(request.sample_id),
            action_timeout=request.action_timeout,
            resource_manager=self._resource_manager,
            sample_store=self._sample_store,
            consumable_manager=self._consumable_manager,
            robot_runtime=self._robot_runtime,
            robot_resources=self._robot_resources,
            plc_action_client=self._plc_action_client,
        )

        try:
            await task.run()
            vr = task.vision_result
            if vr and vr.ok:
                self._log.append(
                    request.sample_id, "VISION_OK",
                    f"X={vr.x:.3f} Y={vr.y:.3f} conf={vr.confidence:.3f}",
                )
            elif vr:
                self._log.append(request.sample_id, "VISION_FAIL", "视觉分析失败")
            self._log.append(request.sample_id, "DONE",
                self._format_vision_vr(vr) + f" recipe={request.recipe.name}",
            )
        except Exception as e:
            self._log.append(request.sample_id, "ERROR", str(e))
            log.error("[Scheduler] 样品 %s 执行失败: %s", request.sample_id, e)

    def _wrapped_confirm(self, sample_id: str) -> Optional[ConfirmCallback]:
        """包装原始 confirm_callback（旧路径 SampleTask：接受 task）。"""
        if self._confirm_callback is None:
            return None

        async def _cb(task: SampleTask) -> bool:
            result = await self._confirm_callback(task)
            event = "CONFIRM_CONT" if result else "CONFIRM_STOP"
            self._log.append(sample_id, event, "人工确认结果")
            return result

        return _cb

    def _wrapped_confirm_by_id(self, sample_id: str):
        """包装原始 confirm_callback（新路径 RecipeTask/ScrapeStage：接受 sample_id）。

        用 SimpleNamespace 构造伪 task，保证 UI/终端侧的 terminal_confirm(task)/
        ui_confirm(task) 对 task.sample_id 的读取还能用，不用改 main.py / ui/app.py。
        """
        if self._confirm_callback is None:
            return None

        async def _cb(sid: str) -> bool:
            proxy = types.SimpleNamespace(sample_id=sid)
            result = await self._confirm_callback(proxy)
            event = "CONFIRM_CONT" if result else "CONFIRM_STOP"
            self._log.append(sid, event, "人工确认结果")
            return result

        return _cb

    @staticmethod
    def _format_vision(task: SampleTask) -> str:
        vr = task.vision_result
        if vr and vr.ok:
            return f"X={vr.x:.3f} Y={vr.y:.3f} conf={vr.confidence:.3f}"
        return "视觉结果不可用"

    @staticmethod
    def _format_vision_vr(vr) -> str:
        if vr and vr.ok:
            return f"X={vr.x:.3f} Y={vr.y:.3f} conf={vr.confidence:.3f}"
        return "视觉结果不可用"
