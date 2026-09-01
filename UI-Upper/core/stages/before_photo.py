"""BeforePhoto Stage - 点样后拍照（电平范式 v1.6）

协议 v1.6：BeforePhotoStage 复用 scrape FSM（通过 scrape_PhotoMode=1 区分路径）。
PLC 子步：0(idle) → 10(init) → 15(before-photo 乒乓) → 0 + Done=TRUE
PC 侧介入点：Step 15 到达后（PLC 将硅胶板送至拍照位），PC 侧触发拍照（保存为 before.jpg），
              写 scrape_Confirm=TRUE → PLC 归位 → Done。

资源互斥：BeforePhotoStage 与 ScrapeStage 共享 _scrape_lock（类级 asyncio.Lock），
确保 before_photo 和 scrape 对拍照刮板工位硬件的访问串行化。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from core import flow_events as fe
from core.camera_service import CameraService
from core.stages.base import StageExecutor

log = logging.getLogger(__name__)

# before_photo 子步映射（与 scrape FSM 的 Step 号对齐）
BEFORE_PHOTO_SUB_STEPS: dict[int, tuple[str, str]] = {
    0:  ("idle",          "空闲"),
    10: ("init",          "初始化"),
    15: ("before_photo",  "点样后拍照(乒乓)"),
    90: ("error",         "故障"),
}


class BeforePhotoStage(StageExecutor):
    """点样后拍照执行器（电平范式 v1.6）。

    复用 scrape FSM，通过 scrape_PhotoMode=1 路由到 Step 15（before-photo 乒乓等待）。
    流程：写 PhotoMode=1 → start_stage → await Step 15 → PC 拍照 → Confirm → await Done。

    _scrape_lock 与 ScrapeStage 共享同一实例，确保硬件互斥。
    """

    NAME = "before_photo"
    PLC_NAME = "scrape"       # 复用 scrape FSM
    STAGE_TIMEOUT = 120.0     # before-photo 仅拍照，无需 600s

    def __init__(
        self,
        *args,
        camera: Optional[CameraService] = None,
        sample_store: Optional[object] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._camera = camera
        self._sample_store = sample_store
        self._before_path: Optional[Path] = None

    async def run(self) -> None:
        """执行点样后拍照全流程。

        流程：
          1. 写 scrape_PhotoMode=1（路由到 Step 15）
          2. start_stage("scrape") → PLC 进入 Step 10(init) → Step 15(before-photo)
          3. await_stage_step("scrape", 15) → PLC 停在 Step 15（板已到位）
          4. PC 侧拍照（保存为 before.jpg）
          5. confirm_stage("scrape") → PLC 归位 → Done
          6. await_stage_done("scrape") → 完成
        """
        # Warning #5: 防御性检查 _scrape_lock 是否已绑定
        if self._scrape_lock is None:
            raise RuntimeError(
                "BeforePhotoStage._scrape_lock 未绑定——"
                "应在 stages/__init__.py 中赋值为 ScrapeStage._scrape_lock"
            )

        # 设置 BeforePhotoStage 占用标志（让 Vision Tab 感知）
        self._set_vision_state(waiting=True)
        _fsm_started = False  # 追踪 PLC FSM 是否已启动，用于异常清理

        try:
            async with self._scrape_lock:
                self._emit_stage_start()  # 方案A：持锁后标记开始
                t0 = time.monotonic()
                last_code: list[int | None] = [None]
                last_start_ts: list[float | None] = [None]

                async def _on_step_change(code: int) -> None:
                    prev = last_code[0]
                    if prev is not None and prev in BEFORE_PHOTO_SUB_STEPS and prev not in (0, 90):
                        dur = int((time.monotonic() - (last_start_ts[0] or t0)) * 1000)
                        self._log.append(
                            self._sample_id, fe.STEP_DONE,
                            fe.fmt_detail(stage=self.NAME, action_id=prev, duration_ms=dur),
                        )
                    if code in BEFORE_PHOTO_SUB_STEPS and code not in (0,):
                        _, label = BEFORE_PHOTO_SUB_STEPS[code]
                        self._log.append(
                            self._sample_id, fe.STEP_START,
                            fe.fmt_detail(stage=self.NAME, action_id=code, label=label),
                        )
                        last_start_ts[0] = time.monotonic()
                        log.info("[BeforePhoto %s] 子步 → %d (%s)", self._sample_id, code, label)
                    last_code[0] = code

                # Phase 1: 写 PhotoMode=1 + 启动 scrape FSM
                log.info("[BeforePhoto %s] 写 scrape_PhotoMode=1, start_stage", self._sample_id)
                await self._plc.send_recipe_params({"scrape_PhotoMode": 1})
                await self._plc.start_stage("scrape")
                _fsm_started = True

                # Phase 2: 等待 Step 15（before-photo 乒乓等待点）
                await self._plc.await_stage_step(
                    "scrape", 15,
                    on_step_change=_on_step_change,
                    timeout=self.STAGE_TIMEOUT,
                )

                # Phase 3: PC 侧拍照（保存为 before.jpg）
                await self._capture_before_photo()

                # Phase 4: Confirm → PLC 归位 + Done
                await self._plc.confirm_stage("scrape")

                # Phase 5: 等待完成（正常完成时 await_stage_done 内部写 Enable=False）
                await self._plc.await_stage_done(
                    "scrape",
                    on_step_change=_on_step_change,
                    timeout=self.STAGE_TIMEOUT,
                )

                log.info("[BeforePhoto %s] 完成 (%.1fs)", self._sample_id, time.monotonic() - t0)
        except BaseException:
            # Critical #3: 异常/取消清理——仅在 FSM 仍处于 before_photo 遗留步时写 Enable=False
            # 避免在并发场景中干扰其他样品正在使用的 scrape FSM
            if _fsm_started:
                try:
                    current_step = int(await self._plc.read_variable("scrape_Step"))
                    if current_step in (0, 10, 15):
                        log.warning(
                            "[BeforePhoto %s] 异常退出，FSM Step=%d，写 scrape_Enable=False 清理",
                            self._sample_id, current_step,
                        )
                        await self._plc.write_variable("scrape_Enable", False)
                    else:
                        log.info(
                            "[BeforePhoto %s] 异常退出，FSM Step=%d 非before_photo步，跳过 Enable=False",
                            self._sample_id, current_step,
                        )
                except BaseException:
                    pass  # 清理中断（含 CancelledError）不影响异常传播
            raise
        finally:
            # 确保无论正常完成、异常还是取消，都清除 Vision Tab 占用标志
            self._set_vision_state(waiting=False)

    async def _capture_before_photo(self) -> None:
        """Step 15 到达后触发拍照，保存为 before.jpg。

        拍照完成后将 before_path 存入 sample_store，供后续 ScrapeStage 读取。
        同时推送到 Vision Tab 的 AppState，让 UI 可显示 before 照片。
        """
        if self._camera is None:
            log.info("[BeforePhoto %s] 未配 CameraService，跳过拍照", self._sample_id)
            return

        try:
            # 确定 save_dir
            if self._sample_store is not None:
                save_dir = self._sample_store.get_sample_dir(self._sample_id)
            else:
                save_dir = Path("data/samples") / self._sample_id

            image_path = await self._camera.capture(
                self._sample_id, save_dir, filename="before.jpg"
            )
            self._before_path = image_path
            log.info("[BeforePhoto %s] 拍照完成: %s", self._sample_id, image_path)

            # 存入 sample_store，供 ScrapeStage 读取
            if self._sample_store is not None and hasattr(self._sample_store, "set_before_path"):
                self._sample_store.set_before_path(self._sample_id, image_path)
                log.info("[BeforePhoto %s] before_path 已存入 SampleStore", self._sample_id)

            # 推送到 Vision Tab
            self._push_before_photo_to_vision(image_path)

        except Exception as e:
            log.error("[BeforePhoto %s] 拍照失败: %s", self._sample_id, e)
            # Critical #2: 相机失败后必须 re-raise，让 run() 的 except BaseException 执行 PLC 清理
            # 不再静默继续——拍照失败意味着 before.jpg 不可用，后续视觉分析必失败
            raise


    def _push_before_photo_to_vision(self, image_path: Path) -> None:
        """将 before 照片路径推送到 AppState，让 Vision Tab 显示。"""
        try:
            from ui.state import get_state
            state = get_state()
            state.vision_before_photo_path = image_path
            # 不再覆盖用户选中的 vision_current_sample_id（仅由下拉框 on_change 主导）；
            # 改写权威字段 vision_waiting_sample_id，标识该样品为当前乒乓所属样品。
            state.vision_waiting_sample_id = self._sample_id
            log.info("[BeforePhoto %s] 已推送 before 照片到 Vision Tab: %s",
                     self._sample_id, image_path)
        except ImportError:
            pass

    def _set_vision_state(self, *, waiting: bool) -> None:
        """设置/清除 BeforePhotoStage 占用标志。"""
        try:
            from ui.state import get_state
            state = get_state()
            state.vision_before_photo_waiting = waiting
            if not waiting:
                state.vision_before_photo_path = None
                # 同步清理权威字段（仅在属于本 stage 时清，避免误清 ScrapeStage 写入的值）
                if state.vision_waiting_sample_id == self._sample_id and not state.vision_scrape_waiting:
                    state.vision_waiting_sample_id = None
        except ImportError:
            pass


# 锁共享：BeforePhotoStage 与 ScrapeStage 使用同一个 _scrape_lock 实例
# 确保两个阶段对拍照刮板工位硬件的访问串行化
# 必须在 ScrapeStage 类定义后赋值（避免循环 import）
BeforePhotoStage._scrape_lock = None  # 占位，在 stages/__init__.py 中替换为 ScrapeStage._scrape_lock
