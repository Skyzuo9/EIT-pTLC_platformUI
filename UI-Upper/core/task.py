"""
SampleTask - 单样品流程状态机（Batch 2）
==============================
状态流：
    PENDING → SPOTTING → DEVELOPING → SCRAPING → DONE
                                                          ↘ ERROR

每步通过 StageExecutor 子类驱动 PLC 执行（电平范式）。
所有工位（spotting/develop/scrape）已完成迁移，不再使用旧 send_action 路径。

RecipeTask - Batch 6 Phase C 多阶段分派器
==========================================
基于 RecipeTemplate，按 STAGE_ORDER 顺序遍历 stages：
    - enabled=False → 记 STAGE_SKIPPED 事件，直接跳过
    - enabled=True  → 实例化对应 StageExecutor 子类并 execute()
ScrapeStage 额外注入 vision / before_path / after_path / confirm_callback。
与 SampleTask 共存，Batch 2 直接构造 SampleTask 的调用路径保持向后兼容。
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Optional, TYPE_CHECKING

from core.log_store import LogStore
from core.plc_client import PLCClient
from core.vision_service import VisionResult, VisionService

if TYPE_CHECKING:
    from core.camera_service import CameraService
    from core.recipe import RecipeTemplate
    from core.vision_service import AnalysisResult

log = logging.getLogger(__name__)

# 旧 ActionID 常量已全部删除（Phase C：所有工位迁移至电平范式）

# 人工确认回调类型：接受 SampleTask，返回 True=继续 / False=终止
ConfirmCallback = Callable[["SampleTask"], Awaitable[bool]]


class TaskState(Enum):
    PENDING    = "PENDING"
    SPOTTING   = "SPOTTING"
    DEVELOPING = "DEVELOPING"
    SCRAPING   = "SCRAPING"
    DONE       = "DONE"
    ERROR      = "ERROR"


class SampleTask:
    """单样品流程状态机。

    使用方式：
        task = SampleTask(
            sample_id="S001",
            before_path=Path("before.png"),
            after_path=Path("after.png"),
            plc=plc_client,
            vision=vision_service,
        )
        await task.run()

    参数：
        sample_id        : 样品唯一标识
        before_path      : 点样前图像路径（供视觉分析使用）
        after_path       : 展开后图像路径（供视觉分析使用）
        plc              : 已连接的 PLCClient 实例
        vision           : VisionService 实例
        camera           : CameraService 实例（Step 20 拍照触发）
        confirm_callback : 视觉失败时的人工确认回调；
                           None → 视觉失败直接标记 ERROR
        action_timeout   : 每个 PLC 动作超时（秒），默认 30
    """

    def __init__(
        self,
        sample_id: str,
        before_path: Path,
        after_path: Path,
        plc: PLCClient,
        vision: VisionService,
        camera: Optional["CameraService"] = None,
        confirm_callback: Optional[ConfirmCallback] = None,
        action_timeout: float = 30.0,
        log_store: Optional[LogStore] = None,
        resource_manager=None,
    ):
        self.sample_id = sample_id
        self.before_path = Path(before_path)
        self.after_path = Path(after_path)
        self._plc = plc
        self._vision = vision
        self._camera = camera
        self._confirm_callback = confirm_callback
        self._action_timeout = action_timeout
        self._log_store = log_store or LogStore()
        self._resource_manager = resource_manager

        self._state = TaskState.PENDING
        self._vision_result: Optional[VisionResult] = None

    # ------------------------------------------------------------------
    # 公共属性
    # ------------------------------------------------------------------

    @property
    def state(self) -> TaskState:
        return self._state

    @property
    def vision_result(self) -> Optional[VisionResult]:
        return self._vision_result

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """驱动完整样品流程。出错时设置状态为 ERROR，并重新抛出异常。"""
        log.info("=" * 55)
        log.info("[Task %s] ▶ 开始执行单样品全流程", self.sample_id)
        try:
            await self._step(TaskState.SPOTTING,   self._do_spotting)
            await self._step(TaskState.DEVELOPING, self._do_developing)
            await self._step(TaskState.SCRAPING,   self._do_scraping)
            # 视觉分析已内嵌到 ScrapeStage（电平范式 v1.5）

            self._set_state(TaskState.DONE)
            log.info("[Task %s] ✓ 全程完成", self.sample_id)

        except asyncio.CancelledError:
            self._set_state(TaskState.ERROR)
            log.warning("[Task %s] ✗ 任务被取消", self.sample_id)
            raise
        except Exception as e:
            self._set_state(TaskState.ERROR)
            log.error("[Task %s] ✗ 任务失败: %s", self.sample_id, e)
            raise

    # ------------------------------------------------------------------
    # 步骤实现
    # ------------------------------------------------------------------

    async def _do_spotting(self) -> None:
        """Step 1 - 上样点样（电平范式 v1.4：SpottingStage 替代旧 send_action 路径）。"""
        from core.stages.spotting import SpottingStage
        stage = SpottingStage(
            plc=self._plc,
            log_store=self._log_store,
            params={},  # 使用 PARAMS_SCHEMA 默认参数
            sample_id=self.sample_id,
            action_timeout=self._action_timeout,
        )
        await stage.execute()

    async def _do_developing(self) -> None:
        """Step 2 - 展开/运行（电平范式 v1.3：DevelopStage 替代旧 send_action 路径）。"""
        from core.stages.develop import DevelopStage
        stage = DevelopStage(
            plc=self._plc,
            log_store=self._log_store,
            params={},  # 使用 PARAMS_SCHEMA 默认参数
            sample_id=self.sample_id,
            action_timeout=self._action_timeout,
            resource_manager=self._resource_manager,
        )
        await stage.execute()

    async def _do_scraping(self) -> None:
        """Step 3 - 刮取（电平范式 v1.5：ScrapeStage 替代旧 send_action 路径）。"""
        from core.stages.scrape import ScrapeStage

        # 适配：ScrapeStage 回调签名为 (sample_id: str)，
        # 但 SampleTask._confirm_callback 期望 (task: SampleTask)
        _orig_cb = self._confirm_callback
        if _orig_cb is not None:
            async def _adapt(sample_id: str) -> bool:
                return await _orig_cb(self)
            scrape_cb = _adapt
        else:
            scrape_cb = None

        stage = ScrapeStage(
            plc=self._plc,
            log_store=self._log_store,
            params={},
            sample_id=self.sample_id,
            action_timeout=self._action_timeout,
            vision=self._vision,
            camera=self._camera,
            before_path=self.before_path,
            after_path=self.after_path,
            confirm_callback=scrape_cb,
        )
        await stage.execute()
        self._vision_result = stage.vision_result

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _step(self, state: TaskState, coro_func) -> None:
        """切换到指定状态并执行对应协程。"""
        self._set_state(state)
        await coro_func()

    def _set_state(self, state: TaskState) -> None:
        log.info(
            "[Task %s] 状态变更: %-12s → %s",
            self.sample_id,
            self._state.value,
            state.value,
        )
        self._state = state


# ======================================================================
# RecipeTask - Batch 6 Phase C：基于 RecipeTemplate 的多阶段分派器
# ======================================================================

# scrape 人工确认回调签名：收 sample_id，返回 True=继续 / False=终止
RecipeConfirmCallback = Callable[[str], Awaitable[bool]]


class RecipeTask:
    """基于 RecipeTemplate 的多阶段分派器。

    - 按 STAGE_ORDER 顺序遍历 recipe.stages
    - enabled=False 的 Stage 记 STAGE_SKIPPED 事件，不实例化
    - enabled=True 的 Stage 实例化对应 StageExecutor 子类（查 STAGE_REGISTRY）
    - ScrapeStage 额外注入 vision / camera / before_path / after_path / confirm_callback
    - vision_result 从 ScrapeStage 单向拽出，保持与原 SampleTask 简要兼容（VISION_OK/FAIL）
    """

    def __init__(
        self,
        sample_id: str,
        recipe: "RecipeTemplate",
        plc: PLCClient,
        log_store,
        vision: Optional[VisionService] = None,
        camera: Optional["CameraService"] = None,
        before_path: Optional[Path] = None,
        after_path: Optional[Path] = None,
        confirm_callback: Optional[RecipeConfirmCallback] = None,
        action_timeout: float = 30.0,
        resource_manager=None,
        sample_store=None,
        consumable_manager=None,
        robot_runtime=None,
        robot_resources=None,
        plc_action_client=None,
    ) -> None:
        self.sample_id = sample_id
        self.recipe = recipe
        self._plc = plc
        self._log = log_store
        self._vision = vision
        self._camera = camera
        self._before_path = Path(before_path) if before_path is not None else None
        self._after_path = Path(after_path) if after_path is not None else None
        self._confirm_callback = confirm_callback
        self._action_timeout = action_timeout
        self._vision_result: Optional[VisionResult] = None
        self._resource_manager = resource_manager
        self._sample_store = sample_store
        self._consumable_manager = consumable_manager
        self._robot_runtime = robot_runtime
        self._robot_resources = robot_resources
        self._plc_action_client = plc_action_client

    @property
    def vision_result(self) -> Optional[VisionResult]:
        return self._vision_result

    async def run(self) -> None:
        # 延迟 import 避免循环依赖（core.recipe -> core.stages -> …）
        from core import flow_events as fe
        from core.stages import STAGE_REGISTRY, ScrapeStage
        from core.stages.develop import DevelopStage
        from core.vision_service import AnalysisResult

        log.info("=" * 55)
        log.info(
            "[RecipeTask %s] ▶ 执行 recipe '%s'",
            self.sample_id, self.recipe.name,
        )
        # develop tank handoff：DevelopStage Phase 4 不再直接 release，由本 RecipeTask
        # 在拿到 ScrapeStage._scrape_lock 之后第一时间 release（物理上等价于机器人
        # 把硅胶板从展缸送到拍照刮板工位完成）。pending_release_tank 在以下场景必须
        # 被消费：
        #   * scrape 启用：进入 async with _scrape_lock 后 release，pending 置 None
        #   * scrape 未启用：Phase 1 完成后兜底 release（recipe 不应该出现这种配置，
        #     但 collect-only 等模式可能没有 scrape，安全 fallback）
        #   * 异常 / 取消：在外层 finally 兜底释放（或标记 NEEDS_DRAIN if E-Stop）
        pending_release_tank: Optional[int] = None
        try:
            # ── 耗材预检：在 Phase 1 开始前检查耗材可用性，防止走了一半才报错 ──
            if self._consumable_manager is not None:
                scrape_sp = self.recipe.get_stage("scrape")
                collect_sp = self.recipe.get_stage("collect")
                need_powder = bool(scrape_sp and scrape_sp.enabled)
                need_bottle = bool(collect_sp and collect_sp.enabled)
                if need_powder or need_bottle:
                    warnings = self._consumable_manager.check_availability(
                        need_powder=need_powder, need_bottle=need_bottle,
                    )
                    if warnings:
                        msg = "；".join(warnings)
                        raise RuntimeError(
                            f"耗材预检失败（sample={self.sample_id}）: {msg}"
                        )
                    log.info(
                        "[RecipeTask %s] 耗材预检通过 (powder=%s, bottle=%s)",
                        self.sample_id, need_powder, need_bottle,
                    )

            # ── Phase 1: 执行 spotting / before_photo / develop（各执行一次） ──
            # 物理事实：展开后的硅胶板不能重新点样/展开，这些阶段只执行一次
            # 并行优化：before_photo 与 develop prep 使用不同硬件（拍照工位 vs 展缸+泵），
            # 可并行启动以节省 ~13s。PLC 前置条件：机器人 Step 30 准入条件需放宽为
            # (Expand_Step=0 OR 展开工位允许放硅胶板1)，否则并行场景下机器人死锁。
            # PLC 写安全：PLCClient._lock 串行化所有 OPC UA 写操作，BeforePhoto (scrape FSM)
            # 与 Develop (Expand FSM) 写不同 PLC 变量，传输层无冲突。
            develop_task: Optional[asyncio.Task] = None
            dev_executor: Optional[DevelopStage] = None
            for stage_params in self.recipe.stages:
                if stage_params.name in ("scrape", "collect"):
                    continue  # scrape/collect 在 Phase 2-4 处理
                if not stage_params.enabled:
                    self._log.append(
                        self.sample_id, fe.STAGE_SKIPPED,
                        fe.fmt_detail(stage=stage_params.name, reason="disabled"),
                    )
                    log.info(
                        "[RecipeTask %s] ⊝ Stage '%s' 未启用，跳过",
                        self.sample_id, stage_params.name,
                    )
                    continue

                if stage_params.name == "before_photo":
                    # ── 提前构建并启动 develop（如果启用）──
                    develop_sp = self.recipe.get_stage("develop")
                    if develop_sp and develop_sp.enabled:
                        dev_executor = self._build_executor(
                            develop_sp, STAGE_REGISTRY, ScrapeStage,
                        )
                        develop_task = asyncio.create_task(dev_executor.execute())
                        log.info(
                            "[RecipeTask %s] ⊕ develop 已异步启动（与 before_photo 并行）",
                            self.sample_id,
                        )

                    # before_photo 正常执行
                    executor = self._build_executor(stage_params, STAGE_REGISTRY, ScrapeStage)
                    try:
                        await executor.execute()
                    except BaseException:
                        # before_photo 失败 → 取消 develop（如果还在运行）
                        if develop_task is not None and not develop_task.done():
                            develop_task.cancel()
                            try:
                                await develop_task
                            except BaseException:
                                pass  # 吞 cancel + develop 自身异常，handoff_tank 在下方收集
                        # develop 可能已完成 Phase 4（pending_handoff_tank_id 已设置），
                        # 必须在 re-raise 前收集 handoff tank，否则 finally 兜底无法释放展缸
                        if dev_executor is not None:
                            handoff_tank = getattr(
                                dev_executor, "pending_handoff_tank_id", None
                            )
                            if handoff_tank is not None:
                                pending_release_tank = handoff_tank
                        raise
                    continue

                elif stage_params.name == "develop":
                    if develop_task is not None:
                        # develop 已在 before_photo 路径中异步启动，此处等待完成
                        try:
                            await develop_task
                        except BaseException:
                            # 与 before_photo 路径对称：cancel develop_task 并收集 handoff tank
                            if not develop_task.done():
                                develop_task.cancel()
                                try:
                                    await develop_task
                                except BaseException:
                                    pass
                            if dev_executor is not None:
                                handoff_tank = getattr(
                                    dev_executor, "pending_handoff_tank_id", None
                                )
                                if handoff_tank is not None:
                                    pending_release_tank = handoff_tank
                            raise
                        # 收集 handoff tank
                        handoff_tank = dev_executor.pending_handoff_tank_id
                        if handoff_tank is not None:
                            pending_release_tank = handoff_tank
                            log.info(
                                "[RecipeTask %s] develop handoff 接收: "
                                "tank=%d 待 scrape_lock 内释放",
                                self.sample_id, handoff_tank,
                            )
                        continue
                    # fallback: before_photo 未启用时走串行路径
                    executor = self._build_executor(stage_params, STAGE_REGISTRY, ScrapeStage)
                    await executor.execute()
                    handoff_tank = executor.pending_handoff_tank_id
                    if handoff_tank is not None:
                        pending_release_tank = handoff_tank
                        log.info(
                            "[RecipeTask %s] develop handoff 接收: tank=%d 待 scrape_lock 内释放",
                            self.sample_id, handoff_tank,
                        )
                    continue

                # 通用路径（spotting 等其他 stage）
                executor = self._build_executor(stage_params, STAGE_REGISTRY, ScrapeStage)
                await executor.execute()

            # ── Phase 2-4: scrape→collect 序列 ──
            # RecipeTask 在外层持有 _scrape_lock，确保多 Band 刮取过程中
            # scrape 工位不会被其他样品抢占（BeforePhotoStage 也共享此锁，会自动排队等待）
            scrape_params = self.recipe.get_stage("scrape")
            collect_params = self.recipe.get_stage("collect")

            if scrape_params and scrape_params.enabled:
                # 捕获本样品 scrape 对应的源展缸号（诊断用，仅为 scrape_Source_Tank 写入）。
                # release 之后 pending_release_tank 会被置 None，必须提前快照。
                # 重刮路径不传递（0 表示未关联展缸）。
                source_tank_for_scrape = int(pending_release_tank or 0)
                async with ScrapeStage._scrape_lock:
                    # ── 拍照刮板工位就绪：第一时间释放 develop tank ──
                    # 物理依据：拿到 _scrape_lock 那一刻等价于机器人可以把硅胶板从
                    # 展缸搬到拍照刮板工位（前一样品已让出工位），此时展缸真正空出。
                    if (
                        pending_release_tank is not None
                        and self._resource_manager is not None
                    ):
                        # 两方校验：进入 _scrape_lock 之后、release 之前，
                        # 确认 "上位机锁住的样品" 与 "PLC 送到工位的板" 严格对应。
                        # 依据：
                        #   1) 样品-tank 绑定不可迁移（allocate 之后锁定）、
                        #   2) await_drain_done(N) 返回 ⇔ PLC 已完成 tank N 的 robot_pickup。
                        # 这两点叠加后，只要 pending_release_tank == bound_tank
                        # 且 tank 的 handoff_pending 仍为 True，就可以断言 "板-样品对应"。
                        bound_tank = self._resource_manager.get_tank_for_sample(self.sample_id)
                        info = self._resource_manager.get_tank_info(pending_release_tank)
                        if (
                            bound_tank != pending_release_tank
                            or info is None
                            or not info.handoff_pending
                        ):
                            raise RuntimeError(
                                f"[RecipeTask {self.sample_id}] handoff 校验失败: "
                                f"pending={pending_release_tank} bound={bound_tank} "
                                f"handoff_pending={(info.handoff_pending if info else 'N/A')}"
                            )
                        await self._resource_manager.release(pending_release_tank)
                        log.info(
                            "[RecipeTask %s] develop tank 在 scrape_lock 内释放: tank=%d",
                            self.sample_id, pending_release_tank,
                        )
                        pending_release_tank = None

                    # Phase 2: 首次 scrape（skip_lock=True，锁由 RecipeTask 持有）
                    # is_last_band 不传 → ScrapeStage 内部根据 selected_bands 长度自决
                    first_scrape = self._build_executor(
                        scrape_params, STAGE_REGISTRY, ScrapeStage,
                        skip_lock=True,
                        source_tank=source_tank_for_scrape,
                    )
                    await first_scrape.execute()

                    if isinstance(first_scrape, ScrapeStage):
                        self._vision_result = first_scrape.vision_result

                        # 从 ScrapeStage 实例属性读取 band 列表（非 state，TOCTOU 防护）
                        analysis_result: Optional[AnalysisResult] = first_scrape.analysis_result
                        selected_bands: list[str] = list(first_scrape.selected_bands)  # 冻结副本
                        n_bands = len(selected_bands)

                        log.info(
                            "[RecipeTask %s] 首次 scrape 完成，选中 %d 条 band: %s",
                            self.sample_id, n_bands, selected_bands,
                        )

                        # 降级路径日志（F7）
                        if not selected_bands:
                            log.info(
                                "[RecipeTask %s] 无 band 选中（视觉失败或未配），跳过多 Band 序列",
                                self.sample_id,
                            )
                        elif n_bands == 1:
                            log.info(
                                "[RecipeTask %s] 单 band 选中，向后兼容模式（无重刮循环）",
                                self.sample_id,
                            )
                    else:
                        analysis_result = None
                        selected_bands = []
                        n_bands = 0
                        log.warning(
                            "[RecipeTask %s] 首次 scrape 非ScrapeStage实例(type=%s)，跳过多Band序列",
                            self.sample_id, type(first_scrape).__name__,
                        )

                    # ── V3 锁结构：锁内 N 次 scrape + N-1 次 collect；锁外第 N 次 collect ──
                    # 中间循环 i=0..n_bands-2：每轮 “中间 collect + 下一条 band 重刮”
                    # n_bands <= 1 时循环为空，直接出锁走锁外 collect
                    if isinstance(first_scrape, ScrapeStage) and n_bands > 1:
                        for i in range(n_bands - 1):
                            # 中间 collect（锁内，板还在工位）
                            if collect_params and collect_params.enabled:
                                collect_exec = self._build_executor(
                                    collect_params, STAGE_REGISTRY, ScrapeStage,
                                )
                                await collect_exec.execute()
                            # 重刮下一条 band（锁内，skip_lock=True）
                            next_band = selected_bands[i + 1]
                            is_last = (i + 1 == n_bands - 1)  # 是否末次重刮
                            log.info(
                                "[RecipeTask %s] Phase 4: 重刮 band=%s (is_last=%s)",
                                self.sample_id, next_band, is_last,
                            )
                            re_scrape = self._build_executor(
                                scrape_params, STAGE_REGISTRY, ScrapeStage,
                                rescrape_mode=True,
                                rescrape_band_id=next_band,
                                rescrape_analysis_result=analysis_result,
                                skip_lock=True,
                                is_last_band=is_last,
                            )
                            await re_scrape.execute()
                # ── 锁释放（最后一次 scrape 已送板废料区，工位空）──
                # BeforePhoto 此时可抢锁；本样品的第 N 次 collect 在锁外执行
                if collect_params and collect_params.enabled:
                    collect_exec = self._build_executor(collect_params, STAGE_REGISTRY, ScrapeStage)
                    await collect_exec.execute()
            else:
                # scrape 未启用 → 单次 collect（仅 collect 模式）
                # 此路径下 develop 通常也未启用，pending_release_tank 应为 None；
                # 但若 recipe 配置异常出现 develop+collect 无 scrape，下方 fallback 兜底释放。
                if collect_params and collect_params.enabled:
                    collect_exec = self._build_executor(collect_params, STAGE_REGISTRY, ScrapeStage)
                    await collect_exec.execute()

            # ── Fallback: 无 scrape 路径下消费 develop handoff（罕见配置） ──
            if (
                pending_release_tank is not None
                and self._resource_manager is not None
            ):
                log.warning(
                    "[RecipeTask %s] scrape 未启用但 develop tank 已 handoff，直接释放: tank=%d",
                    self.sample_id, pending_release_tank,
                )
                await self._resource_manager.release(pending_release_tank)
                pending_release_tank = None

            # ── Phase 5A: 成功出口 → save_metadata 触发 DB upsert ──
            if self._sample_store is not None:
                try:
                    enabled_stages = [
                        sp.name for sp in self.recipe.stages if sp.enabled
                    ]
                    self._sample_store.save_metadata(self.sample_id, {
                        "sample_id": self.sample_id,
                        "recipe_name": self.recipe.name,
                        "completed_at": datetime.now().isoformat(),
                        "enabled_stages": enabled_stages,
                    })
                except Exception as e:
                    log.warning(
                        "[RecipeTask %s] save_metadata 失败（已忽略）: %s",
                        self.sample_id, e,
                    )

            log.info("[RecipeTask %s] ✓ recipe 执行完毕", self.sample_id)
        except asyncio.CancelledError:
            log.warning("[RecipeTask %s] ✗ 任务被取消", self.sample_id)
            # 取消路径耗材回滚（非 ESTOP）：将已分配但未消费的 staging 占位恢复。
            # shield 避免取消传播在 lock acquire / save_to_disk 期间打断回滚。
            from core.estop import is_estop_active
            if not is_estop_active() and self._consumable_manager is not None:
                try:
                    await asyncio.shield(
                        self._consumable_manager.rollback_for_sample(self.sample_id)
                    )
                except Exception as e:
                    log.warning(
                        "[RecipeTask %s] 耗材回滚异常（已忽略）: %s",
                        self.sample_id, e,
                    )
            raise
        except Exception as e:
            log.error("[RecipeTask %s] ✗ 任务失败: %s", self.sample_id, e)
            raise
        finally:
            # 异常 / 取消路径：develop handoff 残留必须兜底释放，否则展缸永久占用。
            # 急停场景下沿用 DevelopStage finally 同款语义：标记 NEEDS_DRAIN 等人工排液。
            if (
                pending_release_tank is not None
                and self._resource_manager is not None
            ):
                from core.estop import is_estop_active
                needs_drain = is_estop_active()
                log.warning(
                    "[RecipeTask %s] 异常路径兜底释放 develop tank: tank=%d (needs_drain=%s)",
                    self.sample_id, pending_release_tank, needs_drain,
                )
                try:
                    await asyncio.shield(
                        self._resource_manager.release(
                            pending_release_tank,
                            mark_needs_drain=needs_drain,
                        )
                    )
                except asyncio.CancelledError:
                    # shield 保证 release 后台继续执行，本协程被取消
                    pass
                except Exception:
                    log.error(
                        "[RecipeTask %s] develop tank 兜底释放失败: tank=%d",
                        self.sample_id, pending_release_tank, exc_info=True,
                    )

    def _build_executor(
        self,
        stage_params,
        registry,
        scrape_cls,
        *,
        rescrape_mode: bool = False,
        rescrape_band_id: Optional[str] = None,
        rescrape_analysis_result: Optional["AnalysisResult"] = None,
        skip_lock: bool = False,
        source_tank: int = 0,
        is_last_band: Optional[bool] = None,
    ):
        from core.stages.before_photo import BeforePhotoStage
        from core.stages.collect import CollectStage
        from core.stages.develop import DevelopStage
        from core.stages.spotting import SpottingStage

        cls = registry[stage_params.name]
        kwargs = dict(
            plc=self._plc,
            log_store=self._log,
            params=stage_params.params,
            sample_id=self.sample_id,
            action_timeout=self._action_timeout,
        )
        if isinstance(cls, type) and issubclass(cls, scrape_cls):
            kwargs.update(
                vision=self._vision,
                camera=self._camera,
                before_path=self._before_path,
                after_path=self._after_path,
                confirm_callback=self._confirm_callback,
                sample_store=self._sample_store,
                rescrape_mode=rescrape_mode,
                rescrape_band_id=rescrape_band_id,
                rescrape_analysis_result=rescrape_analysis_result,
                skip_lock=skip_lock,
                consumable_manager=self._consumable_manager,
                source_tank=source_tank,
                is_last_band=is_last_band,
            )
        if cls is CollectStage and self._consumable_manager is not None:
            kwargs["consumable_manager"] = self._consumable_manager
        if cls is DevelopStage and self._resource_manager is not None:
            kwargs["resource_manager"] = self._resource_manager
        if cls is BeforePhotoStage:
            kwargs.update(
                camera=self._camera,
                sample_store=self._sample_store,
            )
        if cls is SpottingStage and self._plc_action_client is not None:
            kwargs.update(
                plc_action_client=self._plc_action_client,
                robot_runtime=self._robot_runtime,
                robot_resources=self._robot_resources,
                camera=self._camera,
                sample_store=self._sample_store,
            )
        return cls(**kwargs)
