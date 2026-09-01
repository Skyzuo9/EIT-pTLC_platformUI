"""Scrape Stage - 拍照 + 视觉分析 + 刮板（电平范式 v1.6）

协议 v1.6：scrape 工位单 FSM + 乒乓握手 + PhotoMode 路由。
PLC 子步：0(idle) → 10(init) → 15(拍照+乒乓) → 20(CNC刮取) → 30(机器人取粉末) → 0 + Done=TRUE

Step 15 为唯一乒乓等待点（A10 FB 内部阻塞等 Confirm）：
  PC 侧在此窗口完成：拍照 → 视觉分析 → band 选择 → CNC 点位生成 → send_recipe_params
  → 写 scrape_Confirm=TRUE → A10 返回 → PLC 按 PhotoMode 分支
    PhotoMode=0（默认）：→ Step 20(CNC) → Step 30(机器人) → Done
    PhotoMode=1：→ Step 0 + Done（仅 before-photo，由 BeforePhotoStage 处理）

运行时分支决策（三选一，PhotoMode=0 路径）：
  VisionResult.ok == True            -> 等待 band 选择 → 生成 G-code → 下发 + Confirm
  VisionResult.ok == False           -> 人工确认 → 写安全占位 G-code + Confirm 或中止
  VisionResult 为 None（未配视觉）   -> 写安全占位 G-code + Confirm 跳过刮取

权威参考：PLCsoftware/OPCUAtest/ref_plc_scraping.txt
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from core import flow_events as fe
from core.camera_service import CameraService
from core.cnc_path_generator import generate_scrape_arrays, safe_placeholder_arrays
from core.config import GCodeCfg
from core.stages.base import StageExecutor
from core.vision_service import AnalysisResult, VisionResult, VisionService

log = logging.getLogger(__name__)

ConfirmCallback = Callable[[str], Awaitable[bool]]

# CNC 主方案接入后：G-code 文本不再下发到 PLC，改为点位数组下发。
# 保留本常量为调试诨别：这个占位 STRING 仅与 scrape_gcode_instructions 字段兼容写入（阶段一保留，
# 阶段二 PLC 工程师确认后可从 NODE_TYPES + mock 中删除该字段）。
LEGACY_GCODE_FIELD = "scrape_gcode_instructions"
LEGACY_GCODE_PLACEHOLDER = ""

# 自动选择模式超时（秒）：auto 模式下若用户未手动确认，超时后自动下发最大面积 band 的参数
# 区别于手动模式的 300s 长超时；auto 模式用户意图即为自动，仅留短窗口供检视
AUTO_CONFIRM_TIMEOUT = 15.0
# 手动选择模式超时（秒）：等待用户交互选择 band 并确认
MANUAL_CONFIRM_TIMEOUT = 300.0


def _resolve_gcode_cfg(state: Optional[object]) -> GCodeCfg:
    """从 state 取 GCodeCfg；state 为 None 或 gcode_cfg 未注入时返回默认值。

    所有路径（正常/重刮/占位/安全退路）都走这个入口，保证标定参数一致性。
    """
    if state is not None:
        gc = getattr(state, "gcode_cfg", None)
        if gc is not None:
            return gc
    return GCodeCfg()


def _build_plc_params(arrays_obj, *, include_legacy: bool = True) -> dict[str, Any]:
    """将 ScrapeArrays 转为 plc.send_recipe_params 可消费的 dict，可选附带兼容字段。"""
    plc_params = arrays_obj.as_plc_dict()
    if include_legacy:
        plc_params[LEGACY_GCODE_FIELD] = LEGACY_GCODE_PLACEHOLDER
    return plc_params

# scrape 子步映射（与 PLC ref_plc_scraping.txt 对齐）
SCRAPE_SUB_STEPS: dict[int, tuple[str, str]] = {
    0:  ("idle",          "空闲"),
    10: ("init",          "初始化"),
    15: ("photo",         "拍照+乒乓(A10阻塞等Confirm)"),
    20: ("scrape",        "CNC刮取(A20)"),
    30: ("collect",       "机器人取粉末(A30)"),
    90: ("error",         "故障"),
}

# 子步语义常量（唯一事实源）
STEP = {v[0]: k for k, v in SCRAPE_SUB_STEPS.items()}


class ScrapeStage(StageExecutor):
    """拍照刮板工位执行器（电平范式 v1.6）。

    与 collect/develop/spotting 同构：start_stage → await_stage_step(乒乓点) →
    PC 侧处理 → confirm_stage → await_stage_done。

    PhotoMode=0（默认）：Step 10 → Step 15(拍照+乒乓) → Step 20(CNC) → Step 30(机器人) → Done
    PhotoMode=1：Step 10 → Step 15(拍照+乒乓) → Done
    """

    NAME = "scrape"
    PLC_NAME = "scrape"
    STAGE_TIMEOUT = 600.0  # 含视觉分析+用户交互时间，需较长

    # 类级锁：scrape 单 FSM 硬件互斥，同一时刻只允许一个样品进入 scrape 流程
    _scrape_lock = asyncio.Lock()

    # v1.5：不再需要 ACTION_IDS / Step 数据类 / _run_step
    # G-code 由视觉分析动态生成，不再预置 gcode_name

    # CNC 工艺参数（覆盖 config.yaml gcode 段，0/"(default)"=不覆盖走全局默认）
    PARAMS_SCHEMA = {
        "num_passes": {
            "type": "int", "default": 0, "min": 0, "max": 10,
            "label": "刮取次数 (0=走全局配置)", "step_label": "CNC工艺",
        },
        "total_depth_mm": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 10.0,
            "label": "总深度mm (0=走全局)", "step_label": "CNC工艺",
        },
        "feed_rate": {
            "type": "int", "default": 0, "min": 0, "max": 5000,
            "label": "刮取进给mm/min (0=走全局)", "step_label": "CNC工艺",
        },
        "plunge_rate": {
            "type": "int", "default": 0, "min": 0, "max": 2000,
            "label": "下刀进给mm/min (0=走全局)", "step_label": "CNC工艺",
        },
        "path_strategy": {
            "type": "select", "default": "(default)",
            "options": ["(default)", "zigzag", "boustrophedon", "contour"],
            "label": "路径策略", "step_label": "CNC工艺",
        },
        "keep_ratio": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 1.0,
            "label": "contour保留比例 (0=走全局)", "step_label": "CNC工艺",
        },
        "overlap_ratio": {
            "type": "float", "default": 0.0, "min": 0.0, "max": 0.99,
            "label": "重叠率 (0=走全局)", "step_label": "CNC工艺",
        },
    }

    def __init__(
        self,
        *args,
        vision: Optional[VisionService] = None,
        camera: Optional[CameraService] = None,
        before_path: Optional[Path] = None,
        after_path: Optional[Path] = None,
        confirm_callback: Optional[ConfirmCallback] = None,
        sample_store: Optional[object] = None,
        rescrape_mode: bool = False,
        rescrape_band_id: Optional[str] = None,
        rescrape_analysis_result: Optional[AnalysisResult] = None,
        skip_lock: bool = False,
        consumable_manager: Optional[object] = None,
        source_tank: int = 0,
        is_last_band: Optional[bool] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._vision = vision
        self._camera = camera
        self._before_path = before_path
        self._after_path = after_path
        self._confirm_callback = confirm_callback
        self._sample_store = sample_store

        # 重刮模式参数
        self._rescrape_mode = rescrape_mode
        self._rescrape_band_id = rescrape_band_id
        self._rescrape_analysis_result = rescrape_analysis_result

        # V3 (v1.8): is_last_band 显式控制 scrape_IsLast 写入
        #   None  = 首次 scrape 自决（依 len(self.selected_bands) <= 1）
        #   True  = 本次为最后一次刮取 → PLC 清板送废料
        #   False = 多 band 中间，板留位不送
        # RecipeTask 在重刮模式下显式传值；is_last_band=True 同时表达
        # “本次刮后锁可释放”（参见 task.py 锁结构重构）
        self._is_last_band = is_last_band

        # skip_lock: True 时跳过 _scrape_lock 获取（由 RecipeTask 外层持有）
        self._skip_lock = skip_lock

        # 耗材管理器（Phase 4 v2.5）。None 时降级跳过耗材决策，兼容遗留调用路径。
        self._cm = consumable_manager

        # Batch 3：诊断用 source_tank——本次 scrape 源自哪个展缸（0=未关联）。
        # 仅作为 PC→PLC 诊断变量 scrape_Source_Tank 写入，不参与任何 PC 侧控制逐辑。
        self._source_tank = source_tank

        # 多 Band 暴露属性（RecipeTask 从实例属性读取，避免 TOCTOU）
        self.analysis_result: Optional[AnalysisResult] = None  # 首次分析结果
        self.selected_bands: list[str] = []                    # Vision Tab 返回的完整 band 选择列表
        self.vision_result: Optional[VisionResult] = None

        # FSM 启动追踪标志（供异常清理使用）
        self._fsm_started = False

    async def run(self) -> None:
        """执行拍照刮板全流程（电平范式 v1.6）。

        流程（PhotoMode=0 默认路径）：
          1. start_stage("scrape") → PLC 进入 Step 10(init) → Step 15(A10拍照+乒乓)
          2. await_stage_step("scrape", 15) → PLC 停在 Step 15（A10 FB 内部等 Confirm）
          3. PC 侧：拍照 → 视觉分析 → band 选择 → CNC 点位生成 → send_recipe_params
          4. confirm_stage("scrape") → A10 返回 → PLC Step 20(CNC) → Step 30(机器人) → Done
          5. await_stage_done("scrape") → 完成

        重刮模式（rescrape_mode=True）：
          Step 15 到达后跳过拍照+分析，直接从 rescrape_analysis_result 生成
          指定 band 的 CNC 点位 → send_params + confirm → PLC 继续 → Done。
          PLC FSM 路径完全相同（10→15→20→30→Done），不关心 PC 是否拍了照。

        锁策略：
          skip_lock=False（默认）：自行获取 _scrape_lock，独立运行
          skip_lock=True：跳过锁获取，由 RecipeTask 外层持有 _scrape_lock，
                         确保多 Band 刮取过程中 scrape 工位不被其他样品抢占
        """
        self._fsm_started = False
        try:
            if self._skip_lock:
                # 锁由 RecipeTask 外层持有，直接执行 FSM 逻辑
                await self._run_scrape_body()
            else:
                async with self._scrape_lock:
                    await self._run_scrape_body()
        except BaseException:
            # Critical #1: 异常/取消清理——仅在 FSM 仍处于 scrape 遗留步时写 Enable=False
            # 与 BeforePhotoStage 的 Critical #3 修复方案保持对称
            if self._fsm_started:
                try:
                    current_step = int(await self._plc.read_variable("scrape_Step"))
                    # scrape 遗留步: 0(idle), 10(init), 15(gate乒乓), 20(photo乒乓)
                    if current_step in (0, 10, 15, 20):
                        log.warning(
                            "[Scrape %s] 异常退出，FSM Step=%d，写 scrape_Enable=False 清理",
                            self._sample_id, current_step,
                        )
                        await self._plc.write_variable("scrape_Enable", False)
                        # 尝试等待 FSM 归零，防止下一个 scrape 任务错过上升沿
                        try:
                            await self._wait_fsm_idle()
                        except BaseException:
                            pass  # _wait_fsm_idle 抛异常也不影响主异常传播（含 CancelledError）
                    elif current_step in (30, 40):
                        # Step 30/40 期间 PLC 正在驱动硬件，等自然归零后再清 Enable
                        log.warning(
                            "[Scrape %s] 异常退出 Step=%d，等待自然归零后清 Enable",
                            self._sample_id, current_step,
                        )
                        try:
                            await asyncio.wait_for(
                                self._wait_fsm_idle(), timeout=10.0
                            )
                        except (asyncio.TimeoutError, RuntimeError):
                            pass  # 超时不强写 Enable=False（硬件可能仍在运动）
                        try:
                            step_now = int(await self._plc.read_variable("scrape_Step"))
                            if step_now == 0:
                                await self._plc.write_variable("scrape_Enable", False)
                        except BaseException:
                            pass
                    else:
                        log.info(
                            "[Scrape %s] 异常退出，FSM Step=%d 非scrape乒乓步，跳过 Enable=False",
                            self._sample_id, current_step,
                        )
                except BaseException:
                    pass  # 清理中断（含 CancelledError）不影响主异常传播
            raise

    def _resolve_is_last(self) -> bool:
        """决定 scrape_IsLast 写入值（V3）。

        - is_last_band 显式传值 → 直接返回
        - 否则 → 首次 scrape 自决：selected_bands 长度 <= 1 表示“唯一/最后一次”
          （0 个 band 也表示最后一次——视觉失败/未选/安全占位路径需清板）
        """
        if self._is_last_band is not None:
            return bool(self._is_last_band)
        return len(self.selected_bands) <= 1

    async def _send_params_with_is_last(self, plc_params: dict[str, Any]) -> None:
        """包装 send_recipe_params，自动注入 scrape_IsLast（V3）。

        所有 Step 15 乒乓后的点位/占位参数下发均走此入口，确保 PLC A20/A30
        在 Step 20/30 读到的 IsLast 与当前 ScrapeStage 实例判断一致。
        """
        plc_params = dict(plc_params)  # 冗余防御，不覆盖调用方 dict
        plc_params["scrape_IsLast"] = self._resolve_is_last()
        await self._plc.send_recipe_params(plc_params)

    async def _run_scrape_body(self) -> None:
        """Scrape FSM 执行逻辑（由 run() 调用，锁由 run() 或 RecipeTask 管理）。

        包含：FSM 启动 → Step 15 乒乓（拍照+视觉+CNC）→ confirm → await Done。
        """
        self._emit_stage_start()  # 方案A：持锁后标记开始
        t0 = time.monotonic()
        last_code: list[int | None] = [None]
        last_start_ts: list[float | None] = [None]

        async def _on_step_change(code: int) -> None:
            prev = last_code[0]
            if prev is not None and prev in SCRAPE_SUB_STEPS and prev not in (0, 90):
                dur = int((time.monotonic() - (last_start_ts[0] or t0)) * 1000)
                self._log.append(
                    self._sample_id, fe.STEP_DONE,
                    fe.fmt_detail(stage=self.NAME, action_id=prev, duration_ms=dur),
                )
            if code in SCRAPE_SUB_STEPS and code not in (0,):
                _, label = SCRAPE_SUB_STEPS[code]
                self._log.append(
                    self._sample_id, fe.STEP_START,
                    fe.fmt_detail(stage=self.NAME, action_id=code, label=label),
                )
                last_start_ts[0] = time.monotonic()
                log.info("[Scrape %s] 子步 → %d (%s)", self._sample_id, code, label)
            last_code[0] = code

        # Phase 1: 写 PhotoMode=0 + 耗材参数 + 启动 scrape FSM
        # 即使 PLC Step 10 有消费语义（读取后归零），PC 侧仍应显式写入
        # 防止 BeforePhotoStage 残留 PhotoMode=1 导致 A10 完成后错误路由

        # 耗材决策（v2.5 动作码）：在 start_stage 前写入 4 字段
        # 首次 scrape 与重刮走同样路径——粉末不能混合是物理硬约束，每个 band
        # 都需新孔位的全新粉末收集器。同一 sample_id 重复调用 prepare_for_scrape
        # 会覆盖 _decisions[sample_id]，这是期望行为（CollectStage 读到的总是最新孔）。
        consumable_params: dict = {}
        if self._cm is not None:
            d = await self._cm.prepare_for_scrape(self._sample_id)
            consumable_params = {
                "scrape_Plate_Op":         d.op,
                "scrape_Fetch_Rack_Plate": d.fetch_rack_plate,
                "scrape_Old_Plate_Slot":   d.old_plate_slot,
                "scrape_Consume_Slot":     d.consume_slot,
            }
            log.info(
                "[Scrape %s] 耗材决策: op=%d fetch=%d old=%d slot=%d",
                self._sample_id, d.op, d.fetch_rack_plate,
                d.old_plate_slot, d.consume_slot,
            )
        else:
            log.warning(
                "[Scrape %s] consumable_manager 未注入，跳过耗材决策（遗留调用路径）",
                self._sample_id,
            )

        # V3：首次 scrape 写 PhotoMode=0（完整初始化+拍照）；重刮写 PhotoMode=2（跳过初始化+跳过拍照）。
        # 重刮时 PLC A00 跳过复位（保留板物理状态），A10 跳到 step 40（仅保留 Confirm 乒乓）。
        photo_mode = 2 if self._rescrape_mode else 0
        # 首次写 scrape_IsLast：FSM 启动阶段仅作占位。真正生效在后续 send_recipe_params
        # （Confirm 前）覆盖写入，PLC A20/A30 在 Step 20/30 才读到。
        is_last_initial = self._resolve_is_last()
        log.info(
            "[Scrape %s] 写 scrape_PhotoMode=%d (rescrape=%s) IsLast=%s, start_stage",
            self._sample_id, photo_mode, self._rescrape_mode, is_last_initial,
        )
        # Batch 3：同时写入诊断变量 scrape_Source_Tank（单向 PC→PLC，仅供 PLC trace）。
        # PLC 未升级时该 key 会被 plc_client 跳过并 WARN，主流程不受影响。
        await self._plc.send_recipe_params({
            "scrape_PhotoMode": photo_mode,
            "scrape_IsLast": is_last_initial,
            "scrape_Source_Tank": int(self._source_tank or 0),
            **consumable_params,
        })
        await self._plc.start_stage("scrape")
        self._fsm_started = True

        # Phase 2: 等待 Step 15（A10 FB 内部阻塞等 Confirm，PC 在此窗口完成全部工作）
        await self._plc.await_stage_step(
            "scrape", STEP["photo"],
            on_step_change=_on_step_change,
            timeout=self.STAGE_TIMEOUT,
        )

        if self._rescrape_mode:
            # ── 重刮模式：跳过拍照+分析，直接从已有 AnalysisResult 生成指定 band 的点位数组 ──
            log.info(
                "[Scrape %s] 重刮模式: band_id=%s（跳过拍照+分析）",
                self._sample_id, self._rescrape_band_id,
            )
            # F10: 重刮模式带 band_id 标识的 STAGE_START 事件
            self._log.append(
                self._sample_id, fe.STEP_START,
                fe.fmt_detail(stage=self.NAME, action_id=15, label=f"photo(rescrape:{self._rescrape_band_id})"),
            )
            plc_params = self._build_plc_params_for_band(
                self._rescrape_analysis_result, self._rescrape_band_id
            )
            if plc_params is None:
                # 重刮点位生成失败 → 安全占位（g_pass_count=0）
                log.warning(
                    "[Scrape %s] 重刮点位生成失败，下发安全占位数组",
                    self._sample_id,
                )
                gcode_cfg = _resolve_gcode_cfg(self._get_state())
                plc_params = _build_plc_params(safe_placeholder_arrays(gcode_cfg))
            await self._send_params_with_is_last(plc_params)
            await self._plc.confirm_stage("scrape")
        else:
            # ── 正常模式：拍照 + 视觉分析 + band 选择 + 点位数组生成 ──
            # Phase 2.5: PC 侧触发拍照（Step 15 到达 = A10 FB 内部等 Confirm，板已到位）
            await self._capture_photo()

            # Phase 2.6: 自动推导图像路径 + 优雅降级
            self._resolve_image_paths()

            # Phase 3: PC 侧视觉分析 + 分支决策
            ar = await self._analyze_vision_full()

            if ar is None:
                # 未配视觉 → 下发安全占位数组 + Confirm
                log.info("[Scrape %s] 跳过视觉分支（未配 VisionService）", self._sample_id)
                gcode_cfg = _resolve_gcode_cfg(self._get_state())
                await self._send_params_with_is_last(
                    _build_plc_params(safe_placeholder_arrays(gcode_cfg))
                )
                await self._plc.confirm_stage("scrape")
            elif ar.ok:
                # 视觉成功 → 推送到 Vision Tab → 等待 band 选择 → 生成点位 → 下发 + Confirm
                self.analysis_result = ar  # 暴露给 RecipeTask
                self._push_to_vision_tab(ar)
                plc_params = await self._wait_for_band_selection_and_build_params()
                # ★ 视觉成功路径也需要从 state 同步 AnalysisResult：
                #   用户可能通过 Vision Tab 调试模式加载了不同的 summary.json，
                #   首次 scrape 的 _build_plc_params_from_vision 已使用 state 中的数据，
                #   但 self.analysis_result 仍为原始视觉分析结果。
                #   RecipeTask Phase 4 重刮需要与首次 scrape 实际使用的数据源一致。
                state = self._get_state()
                if state is not None:
                    ar_from_state = getattr(state, "vision_analysis_result", None)
                    if (
                        ar_from_state is not None
                        and ar_from_state is not ar
                        and getattr(ar_from_state, "ok", False)
                    ):
                        self.analysis_result = ar_from_state
                        log.info(
                            "[Scrape %s] 从 state.vision_analysis_result 同步 AnalysisResult 供重刮使用 (case=%s)",
                            self._sample_id,
                            getattr(ar_from_state, "case_name", "?"),
                        )
                if plc_params is None:
                    log.warning("[Scrape %s] 点位生成失败，下发安全占位数组", self._sample_id)
                    gcode_cfg = _resolve_gcode_cfg(self._get_state())
                    plc_params = _build_plc_params(safe_placeholder_arrays(gcode_cfg))
                await self._send_params_with_is_last(plc_params)
                await self._plc.confirm_stage("scrape")
            else:
                # 视觉失败 → 人工确认
                should_continue = await self._confirm_or_abort()
                if should_continue:
                    # 推送失败样品图像到 Vision Tab，激活手动 band 选择路径
                    # 用户可加载历史分析或切换样品获取 band 数据；超时兜底 → 安全占位
                    log.warning("[Scrape %s] 视觉失败，用户选择继续——推送 Vision Tab 等待手动 band 选择",
                                self._sample_id)
                    analysis_dir = Path()
                    if self._sample_store is not None:
                        try:
                            analysis_dir = self._sample_store.get_analysis_dir(self._sample_id)
                        except Exception:
                            pass
                    enriched_ar = AnalysisResult(
                        ok=False,
                        case_name=self._sample_id,
                        case_dir=analysis_dir,
                        summary={},
                        bands=[],
                        after_image_path=self._after_path,
                        before_image_path=self._before_path,
                    )
                    self._push_to_vision_tab(enriched_ar)
                    plc_params = await self._wait_for_band_selection_and_build_params()
                    # ★ 视觉失败 + 用户加载历史路径：从 state 捕获真实 AnalysisResult，
                    #   供 RecipeTask Phase 4 多 band 重刮使用（_build_plc_params_for_band
                    #   必需有效 case_dir + summary.json）。
                    #   排除 enriched_ar 本身（ok=False/bands=[]，重刮路径不可用）
                    if self.analysis_result is None:
                        state = self._get_state()
                        if state is not None:
                            ar_from_state = getattr(state, "vision_analysis_result", None)
                            if (
                                ar_from_state is not None
                                and ar_from_state is not enriched_ar
                                and getattr(ar_from_state, "ok", False)
                            ):
                                self.analysis_result = ar_from_state
                                log.info(
                                    "[Scrape %s] 视觉失败路径捕获 state.vision_analysis_result 供重刮模式使用 (case=%s)",
                                    self._sample_id,
                                    getattr(ar_from_state, "case_name", "?"),
                                )
                    if plc_params is None:
                        log.warning("[Scrape %s] 视觉失败后手动路径未生成，下发安全占位数组",
                                    self._sample_id)
                        gcode_cfg = _resolve_gcode_cfg(self._get_state())
                        plc_params = _build_plc_params(safe_placeholder_arrays(gcode_cfg))
                    await self._send_params_with_is_last(plc_params)
                    await self._plc.confirm_stage("scrape")
                else:
                    # 中止：写 Enable=FALSE + 等待 PLC FSM 归零
                    await self._plc.write_variable("scrape_Enable", False)
                    await self._wait_fsm_idle()
                    raise RuntimeError(
                        f"[Scrape {self._sample_id}] 视觉失败且人工选择终止"
                    )

        # Phase 4: 等待整个流程完成（PLC: Step 20 CNC → Step 30 机器人 → Done）
        await self._plc.await_stage_done(
            "scrape",
            on_step_change=_on_step_change,
            timeout=self.STAGE_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # 拍照触发（Phase 2.5）
    # ------------------------------------------------------------------

    async def _capture_photo(self) -> None:
        """Step 20 到达后触发拍照，保存图像并更新 after_path。

        如果拍照失败，self._after_path 被清空为 None，确保后续视觉分析
        不使用过期路径。拍照成功后推送到 Vision Tab 的“拍照结果”tab。
        """
        if self._camera is None:
            log.info("[Scrape %s] 未配 CameraService，跳过拍照", self._sample_id)
            return

        try:
            # 确定 save_dir：优先从 sample_store 获取，回退到默认 data/samples/<sample_id>/
            if self._sample_store is not None:
                save_dir = self._sample_store.get_sample_dir(self._sample_id)
            else:
                save_dir = Path("data/samples") / self._sample_id

            image_path = await self._camera.capture(self._sample_id, save_dir)
            self._after_path = image_path  # 动态更新 after_path 供视觉分析使用
            log.info("[Scrape %s] 拍照完成: %s", self._sample_id, image_path)

            # 推送 after 照片到 Vision Tab（即使视觉分析未开始，也先显示拍照结果）
            try:
                from ui.state import get_state
                state = get_state()
                state.vision_scrape_after_path = image_path
            except ImportError:
                pass
        except Exception as e:
            log.error("[Scrape %s] 拍照失败: %s", self._sample_id, e)
            self._after_path = None  # 确保失败后不使用旧路径

    # ------------------------------------------------------------------
    # 图像路径自动推导 + 降级（Phase 2.5 → Phase 3 之间）
    # ------------------------------------------------------------------

    def _resolve_image_paths(self) -> None:
        """在拍照后解析 before/after 图像路径，推导缺失路径，优雅降级。

        解析逻辑：
        1. after_path → 拍照后通常已有效；无效时尝试 SampleStore / 文件系统回退
        2. before_path →
           a. 已是有效文件 → 保持
           b. SampleStore 非 None → sample_store.get_before_path(sample_id)
           c. 文件系统回退 → Path("data/samples") / sample_id / "before.jpg"
           d. 仍无效 → _before_path = None，日志 WARN
        3. _before_path 为 None 时 → VisionService.analyze_full() 返回 ok=False（双帧是唯一模式），
           ScrapeStage 走视觉失败分支（人工确认 → 安全占位 G-code 或中止）
        """
        # --- after_path 推导 ---
        if self._after_path is not None and Path(self._after_path).is_file():
            pass  # 拍照后一定有效
        else:
            # 尝试回退推导
            fallback = self._try_fallback_path("after.jpg")
            if fallback is not None:
                log.info("[Scrape %s] after_path 回退推导: %s", self._sample_id, fallback)
                self._after_path = fallback
            else:
                log.warning("[Scrape %s] after_path 无效且无法推导，视觉分析将跳过",
                            self._sample_id)
                self._after_path = None

        # --- before_path 推导 ---
        if self._before_path is not None and Path(self._before_path).is_file():
            pass  # 已是有效文件
        else:
            resolved = None

            # 尝试 SampleStore
            if self._sample_store is not None and hasattr(self._sample_store, "get_before_path"):
                try:
                    resolved = self._sample_store.get_before_path(self._sample_id)
                    if resolved is not None and not Path(resolved).is_file():
                        resolved = None
                except Exception:
                    resolved = None

            # 文件系统回退
            if resolved is None:
                resolved = self._try_fallback_path("before.jpg")

            if resolved is not None:
                log.info("[Scrape %s] before_path 推导: %s", self._sample_id, resolved)
                self._before_path = resolved
            else:
                log.warning(
                    "[Scrape %s] before_path 无法推导，双帧视觉分析将失败 (sample_id=%s)",
                    self._sample_id, self._sample_id,
                )
                self._before_path = None

    def _try_fallback_path(self, filename: str) -> Optional[Path]:
        """尝试从文件系统回退查找图像文件。

        Suggestion #11: 文件系统回退时记录 WARNING 日志，
        提示可能是旧文件（非当前运行产生），留待异常路径验证设计时统一处理。
        """
        fallback = Path("data/samples") / self._sample_id / filename
        if fallback.is_file():
            log.warning(
                "[Scrape %s] 图像路径通过文件系统回退找到: %s（可能是旧文件，非当前运行产生）",
                self._sample_id, fallback,
            )
            return fallback
        return None

    # ------------------------------------------------------------------
    # 视觉分析
    # ------------------------------------------------------------------

    async def _analyze_vision_full(self) -> Optional[AnalysisResult]:
        """执行完整视觉分析（调用 VisionService.analyze_full()），获取 AnalysisResult。

        同时从 AnalysisResult 派生 VisionResult 存入 self.vision_result（保持向后兼容）。

        双帧模式（唯一模式）：
          before_path 为 None 时，VisionService.analyze_full() 返回 ok=False，
          不存在单帧回退路径。ScrapeStage 走视觉失败分支
          （人工确认 → 安全占位 G-code + Confirm 或中止）。

        输出目录策略：
          - 有 SampleStore → 使用 analysis_dir 作为 output_dir，与 Vision Tab 搜索路径一致
          - 无 SampleStore → 使用 VisionService 原始 output_dir（向后兼容）

        Warning #6 语义修正：
          - _vision is None → 返回 None（未配视觉，由调用方处理）
          - _after_path is None + _vision is not None → 返回 AnalysisResult(ok=False)（拍照失败）
        """
        if self._vision is None:
            return None
        if self._after_path is None:
            # Warning #6: after_path 缺失但视觉已配 → 返回 ok=False（非 None）
            # 调用方走视觉失败分支（人工确认 → 安全占位 G-code 或中止）
            log.warning("[Scrape %s] after_path 缺失但视觉已配，返回 AnalysisResult(ok=False)",
                        self._sample_id)
            return AnalysisResult(
                ok=False, case_name=self._sample_id, case_dir=Path(), summary={}
            )

        # 统一输出目录：优先使用 SampleStore 的 analysis 目录
        # 这样 Vision Tab 的 has_analysis()/get_annotated_image_path() 能找到结果
        vision = self._vision
        if self._sample_store is not None:
            analysis_dir = self._sample_store.get_analysis_dir(self._sample_id)
            analysis_dir.mkdir(parents=True, exist_ok=True)
            vision = self._vision.with_output_dir(analysis_dir)
            log.info(
                "[Scrape %s] 使用 SampleStore analysis 目录: %s",
                self._sample_id, analysis_dir,
            )

        result = await vision.analyze_full(
            sample_id=self._sample_id,
            before_path=self._before_path,  # None 时 VisionService 返回 ok=False
            after_path=self._after_path,
        )

        # 向后兼容：派生 VisionResult
        if result.ok and result.bands:
            non_origin = [b for b in result.bands if not b.is_origin]
            if non_origin:
                best = max(non_origin, key=lambda b: b.area_cm2)
                self.vision_result = VisionResult(
                    x=best.centroid_cm[0], y=best.centroid_cm[1],
                    confidence=best.normalized_develop_height, ok=True,
                )
        return result

    async def _analyze_vision(self) -> Optional[VisionResult]:
        """执行视觉分析（调用 VisionService.analyze()）。"""
        if self._vision is None:
            return None
        if self._after_path is None:
            log.warning("[Scrape %s] after_path 缺失，视觉分析跳过", self._sample_id)
            return None
        return await self._vision.analyze(
            sample_id=self._sample_id,
            before_path=self._before_path,  # None 时 VisionService 返回 ok=False
            after_path=self._after_path,
        )

    # ------------------------------------------------------------------
    # Vision Tab 状态推送
    # ------------------------------------------------------------------

    def _push_to_vision_tab(self, analysis_result: AnalysisResult) -> None:
        """将 AnalysisResult 推送到 AppState，让 Vision Tab 自动渲染。"""
        try:
            from ui.state import get_state
            state = get_state()
        except ImportError:
            return

        # 不再覆盖用户选中的 vision_current_sample_id（仅由下拉框 on_change 主导）；
        # 改写权威字段 vision_waiting_sample_id，标识该样品为当前乒乓所属样品。
        state.vision_waiting_sample_id = self._sample_id
        state.vision_analysis_result = analysis_result
        state.vision_scrape_after_path = self._after_path  # 新字段

        # 自动选择面积最大的非 origin band
        non_origin = [b for b in analysis_result.bands if not b.is_origin]
        if non_origin:
            best = max(non_origin, key=lambda b: b.area_cm2)
            state.vision_selected_bands = [best.band_id]
        else:
            state.vision_selected_bands = []

        # 乒乓等待标志 + Future 创建
        state.vision_scrape_waiting = True
        if state.vision_band_selection_future is None or state.vision_band_selection_future.done():
            loop = asyncio.get_running_loop()
            state.vision_band_selection_future = loop.create_future()

        log.info("[Scrape %s] 已推送分析结果到 Vision Tab (%d bands)",
                 self._sample_id, len(analysis_result.bands))

    # ------------------------------------------------------------------
    # Vision Tab 乒乓接口
    # ------------------------------------------------------------------

    @staticmethod
    def _get_state():
        """获取 AppState 实例；UI 未启动场景（如单元测试）返回 None。"""
        try:
            from ui.state import get_state
            return get_state()
        except Exception:
            return None

    async def _wait_for_band_selection_and_build_params(self) -> Optional[dict[str, Any]]:
        """等待 Vision Tab 用户选择 band，然后生成 PLC params dict（点位数组 + 标量）。

        交互流程：
        1. 设置 state.vision_scrape_waiting = True
        2. 创建 vision_band_selection_future（如果尚未创建）
        3. 等待 Future 完成（Vision Tab 用户点击"确认选择"按钮）
        4. 保存完整 selected_bands 列表到 self.selected_bands
        5. 仅用 selected_bands[0] 生成点位数组（多 band 时首条 band，单 band 时唯一 band）
        6. 清理状态

        多 band 支持：
          - 完整 selected_bands 列表保存到 self.selected_bands（供 RecipeTask 读取）
          - 点位仅用 selected_bands[0] 生成（物理约束：每条 band 必须单独刮取+收集）
          - RecipeTask 从实例属性读取 band 列表（非 state.vision_selected_bands，TOCTOU 防护）

        Returns:
            PLC params dict（含 12 个 g_xxx + 兼容字段）或 None（生成失败时，由调用方走安全占位）。
        """
        state = self._get_state()

        # 设置乒乓等待标志（仅当 _push_to_vision_tab 尚未设置时）
        if state is not None and not state.vision_scrape_waiting:
            state.vision_scrape_waiting = True
            # 如果 Vision Tab 尚未创建 future，由 ScrapeStage 创建
            if state.vision_band_selection_future is None or state.vision_band_selection_future.done():
                loop = asyncio.get_running_loop()
                state.vision_band_selection_future = loop.create_future()

        # 顶部统一初始化所有跨分支局部变量，避免 state is None / future 已完成等
        # 路径下读取未赋值的 timed_out_mode 触发 UnboundLocalError
        selected_bands: list[str] | None = None
        plc_params: Optional[dict[str, Any]] = None
        timed_out_mode: Optional[str] = None

        try:
            # 等待 Vision Tab 交互或走兼容路径
            if state is not None:
                future = state.vision_band_selection_future
                if future is not None and not future.done():
                    # 周期轮询 mode：mode 可在等待期间被 Vision Tab 切换，
                    # timeout 必须动态响应。原一次性 wait_for 会锁死初始 mode 的 timeout，
                    # 导致“hand-off-to-auto”场景 manual→auto 的 15s 超时不生效。
                    poll_interval = 0.5
                    start_ts = time.monotonic()
                    initial_mode = getattr(state, "vision_band_selection_mode", "auto")
                    log.info(
                        "[Scrape %s] 进入 band 选择等待（初始模式=%s, "
                        "auto=%.0fs / manual=%.0fs，每 %.1fs 轮询模式变化）",
                        self._sample_id, initial_mode,
                        AUTO_CONFIRM_TIMEOUT, MANUAL_CONFIRM_TIMEOUT, poll_interval,
                    )

                    while not future.done():
                        cur_mode = getattr(state, "vision_band_selection_mode", "auto")
                        cur_timeout = (
                            AUTO_CONFIRM_TIMEOUT if cur_mode == "auto"
                            else MANUAL_CONFIRM_TIMEOUT
                        )
                        elapsed = time.monotonic() - start_ts
                        remaining = cur_timeout - elapsed
                        if remaining <= 0:
                            # 当前模式下已超时（可能是初始 manual→后改 auto 后立即达阈）
                            timed_out_mode = cur_mode
                            if not future.done():
                                future.cancel()
                            break
                        try:
                            # shield 防止 wait_for 取消传播到 future 本体
                            await asyncio.wait_for(
                                asyncio.shield(future),
                                timeout=min(poll_interval, remaining),
                            )
                            # future 已完成，退出循环取结果
                        except asyncio.TimeoutError:
                            continue  # 重新读 mode 并检查是否超时

                    if future.done() and timed_out_mode is None:
                        try:
                            selected_bands = future.result()
                        except BaseException:
                            selected_bands = None
                    else:
                        selected_bands = None
                        if timed_out_mode == "auto":
                            log.info(
                                "[Scrape %s] 自动模式超时（%.0fs）——未确认，将下发安全占位 G-code",
                                self._sample_id, AUTO_CONFIRM_TIMEOUT,
                            )
                        else:
                            log.warning(
                                "[Scrape %s] 手动模式超时（%.0fs）——未确认，将下发安全占位 G-code",
                                self._sample_id, MANUAL_CONFIRM_TIMEOUT,
                            )
            else:
                # 无 state（Batch 2 无交互场景）
                pass

            # 保存完整 selected_bands 列表到实例属性（供 RecipeTask 读取）
            # 必须在 _build_plc_params_from_vision 之前保存，因为该函数可能修改列表
            if selected_bands:
                self.selected_bands = list(selected_bands)  # 冻结副本，TOCTOU 安全
                log.info(
                    "[Scrape %s] 用户选择 %d 条 band: %s",
                    self._sample_id, len(selected_bands), selected_bands,
                )
                # 多 band 时仅用 selected_bands[0] 生成点位
                # 物理约束：每条 band 必须单独刮取+收集，不能一次刮多条（粉末会混合）
                plc_params = self._build_plc_params_from_vision(state, selected_bands[:1])
            elif timed_out_mode is not None:
                # 超时未确认：区分 auto vs manual 不同语义
                if timed_out_mode == "auto":
                    # auto 模式超时 = 用户意图就是自动，正常自动选最大面积 band 并下发
                    log.info(
                        "[Scrape %s] auto 模式超时（%.0fs）——自动选择最大面积 band 下发",
                        self._sample_id, AUTO_CONFIRM_TIMEOUT,
                    )
                    if state is not None:
                        state._notification_queue.append((
                            "自动确认：已选择最大面积条带下发点位数组", "positive",
                        ))
                    plc_params = self._build_plc_params_from_vision(state, None)
                else:
                    # manual 模式超时 = 用户应该在场但未操作，安全占位
                    log.warning(
                        "[Scrape %s] manual 模式超时（%.0fs）——未确认，下发安全占位数组",
                        self._sample_id, MANUAL_CONFIRM_TIMEOUT,
                    )
                    if state is not None:
                        state._notification_queue.append((
                            "超时未确认（manual）：已下发安全占位数组，跳过本次刮取",
                            "warning",
                        ))
                    gcode_cfg = _resolve_gcode_cfg(state)
                    plc_params = _build_plc_params(safe_placeholder_arrays(gcode_cfg))
            else:
                # 兼容路径：无 state / 无 future（Batch 2 无交互场景）
                # → 走 _build_plc_params_from_vision 原有"无 selected_bands 时自动选最大面积"兑底
                plc_params = self._build_plc_params_from_vision(state, None)
        except BaseException:
            # P1-2: CancelledError/异常时 PLC 侧清理
            # 当 CancelledError 在 Step 20 乒乓等待期间发生，PLC FSM 卡在 Step 20 等 Confirm
            # 必须在最近点写 Enable=False，让 FSM 回到 Step 0
            # run() 的 except BaseException 也有类似清理，但此处更近点、成功率更高
            if self._fsm_started:
                try:
                    step = int(await self._plc.read_variable("scrape_Step"))
                    if step in (0, 10, 15, 20):
                        log.warning(
                            "[Scrape %s] _wait_for_band_selection 异常清理: "
                            "FSM Step=%d, 写 scrape_Enable=False",
                            self._sample_id, step,
                        )
                        await self._plc.write_variable("scrape_Enable", False)
                except BaseException:
                    pass  # 清理失败不影响主异常传播
            raise
        finally:
            # 清理乒乓状态
            if state is not None:
                state.vision_scrape_waiting = False
                state.vision_band_selection_future = None
                state.vision_waiting_sample_id = None

        return plc_params

    def _apply_recipe_cnc_overrides(
        self, gcode_cfg: GCodeCfg,
    ) -> tuple[GCodeCfg, Optional[str], Optional[float]]:
        """从 self._params 读取 CNC 覆盖参数，返回 (modified_cfg, strategy_override, keep_ratio_override)。

        0/空值 = 不覆盖，保留 gcode_cfg 原值。
        """
        from dataclasses import replace as dc_replace

        p = self._params or {}
        strategy_override: Optional[str] = None
        keep_ratio_override: Optional[float] = None

        # 策略覆盖
        ps = p.get("path_strategy", "(default)")
        if ps and ps != "(default)":
            strategy_override = str(ps).strip().lower()

        # keep_ratio 覆盖
        kr = float(p.get("keep_ratio", 0.0))
        if kr > 0:
            keep_ratio_override = kr

        # ScrapeCfg 子字段覆盖
        scrape_overrides: dict = {}
        np_ = int(p.get("num_passes", 0))
        if np_ > 0:
            scrape_overrides["num_passes"] = np_
        td = float(p.get("total_depth_mm", 0.0))
        if td > 0:
            scrape_overrides["total_depth_mm"] = td
        fr = int(p.get("feed_rate", 0))
        if fr > 0:
            scrape_overrides["feed_rate"] = fr
        pr = int(p.get("plunge_rate", 0))
        if pr > 0:
            scrape_overrides["plunge_rate"] = pr
        or_ = float(p.get("overlap_ratio", 0.0))
        if or_ > 0:
            scrape_overrides["overlap_ratio"] = or_

        if scrape_overrides:
            gcode_cfg = dc_replace(gcode_cfg, scrape=dc_replace(gcode_cfg.scrape, **scrape_overrides))
            log.info(
                "[Scrape %s] 配方 CNC 覆盖生效: %s",
                self._sample_id, scrape_overrides,
            )
        if strategy_override:
            log.info(
                "[Scrape %s] 配方路径策略覆盖: %s",
                self._sample_id, strategy_override,
            )
        if keep_ratio_override is not None:
            log.info(
                "[Scrape %s] 配方 keep_ratio 覆盖: %.2f",
                self._sample_id, keep_ratio_override,
            )

        return gcode_cfg, strategy_override, keep_ratio_override

    def _build_plc_params_from_vision(
        self,
        state: Optional[object],
        selected_bands: Optional[list[str]],
    ) -> Optional[dict[str, Any]]:
        """根据选中的 band 生成 PLC params dict（点位数组 + 标量参数）。

        副作用：仍然调用 GCodeGenerator.generate() 将 G-code 文本落盘作为本地可视化/历史记录，
        但不再将文本下发到 PLC。PLC 实际消费的是本函数返回的字典。

        失败语义（安全契约）：
          - 任何原因导致点位生成出错 → 返回 None
          - 调用方 _run_scrape_body 检测到 None 后会下发 safe_placeholder_arrays（g_pass_count=0）
          - 不再从 VisionResult 拼凑伪点位——那在未经标定的坐标系下下发是不安全的

        多 band 支持：
          - selected_bands 仅包含需要生成点位的 band（首次 scrape 时仅 selected_bands[0]）
          - 完整 band 列表已保存在 self.selected_bands，供 RecipeTask 循环使用
        """
        from core.gcode_generator import GCodeGenerator

        gcode_cfg = _resolve_gcode_cfg(state)

        if state is None:
            log.warning("[Scrape] state 为 None，无法定位 AnalysisResult，返回 None 以走安全占位")
            return None

        analysis_result = getattr(state, "vision_analysis_result", None)
        if analysis_result is None:
            log.warning("[Scrape] state.vision_analysis_result 不可用，返回 None")
            return None

        # 查找 summary.json 路径
        case_dir = getattr(analysis_result, "case_dir", None)
        if case_dir is None:
            log.warning("[Scrape] AnalysisResult.case_dir 为 None，返回 None")
            return None
        case_dir = Path(case_dir)
        summary_path = case_dir / "summary.json"
        if not summary_path.exists():
            case_name = getattr(analysis_result, "case_name", "")
            if case_name:
                summary_path = case_dir / f"{case_name}_summary.json"
        if not summary_path.exists():
            log.warning("[Scrape] summary.json 不存在: %s", summary_path)
            return None

        # 确定选中的 band
        if not selected_bands:
            bands = getattr(analysis_result, "bands", [])
            non_origin = [b for b in bands if not b.is_origin]
            if not non_origin:
                log.warning("[Scrape] AnalysisResult 中无可选 band（都是 origin）")
                return None
            best = max(non_origin, key=lambda b: b.area_cm2)
            selected_bands = [best.band_id]
            log.info("[Scrape] 自动选择 band: %s (面积=%.2f cm²)",
                     best.band_id, best.area_cm2)
            if not self.selected_bands:
                self.selected_bands = [best.band_id]

        # 副作用：G-code 文本落盘（仅作可视化/日志归档，不下发到 PLC）
        try:
            self._render_gcode_artifact(summary_path, selected_bands, gcode_cfg)
        except Exception as e:
            log.warning("[Scrape %s] G-code 可视化落盘失败（不影响 PLC 下发）: %s",
                        self._sample_id, e)

        # 主路径：生成 PLC 点位数组（应用配方 CNC 参数覆盖）
        gcode_cfg, strategy_ov, keep_ratio_ov = self._apply_recipe_cnc_overrides(gcode_cfg)
        try:
            arrays = generate_scrape_arrays(
                summary_path, selected_bands[0], gcode_cfg,
                strategy=strategy_ov, keep_ratio=keep_ratio_ov,
            )
        except (FileNotFoundError, KeyError, Exception) as e:
            log.warning(
                "[Scrape %s] cnc_path_generator 生成失败 (band=%s): %s",
                self._sample_id, selected_bands[0], e,
            )
            return None

        log.info(
            "[Scrape %s] 点位数组生成成功 (band=%s, pass_count=%d)",
            self._sample_id, selected_bands[0], arrays.g_pass_count,
        )
        # v2 主路径：渲染点位路径 PNG + 入 DB 索引（fire-and-forget）
        self._persist_scrape_arrays_artifact(
            arrays, selected_bands[0], strategy_ov or gcode_cfg.path_strategy,
        )
        return _build_plc_params(arrays)

    @staticmethod
    def _render_gcode_artifact(summary_path: Path, selected_bands: list[str], gc: GCodeCfg) -> None:
        """副作用：调用 GCodeGenerator.generate() 将 G-code 落盘为本地文件（可视化/归档）。

        返回值丢弃。失败不报错（由调用方 try/except 包裹）。
        """
        from core.gcode_generator import GCodeGenerator
        GCodeGenerator.generate(
            summary_path=summary_path,
            selected_band_ids=selected_bands,
            origin_corner=gc.origin_corner,
            plate_origin_x=gc.plate_origin_x,
            plate_origin_y=gc.plate_origin_y,
            plate_surface_z_mm=gc.plate_surface_z_mm,
            safe_z_mm=gc.safe_z_mm,
            approach_z_mm=gc.approach_z_mm,
            cutter_diameter_mm=gc.tool.cutter_diameter_mm,
            bottle_diameter_mm=gc.tool.bottle_diameter_mm,
            bottle_x_offset_mm=gc.tool.bottle_x_offset_mm,
            total_depth_mm=gc.scrape.total_depth_mm,
            num_passes=gc.scrape.num_passes,
            scrape_overlap_ratio=gc.scrape.overlap_ratio,
            scrape_feed_rate=gc.scrape.feed_rate,
            plunge_rate=gc.scrape.plunge_rate,
            collection_overlap_ratio=gc.collection.overlap_ratio,
            collection_feed_rate=gc.collection.feed_rate,
            collection_mode=gc.collection.mode,
        )

    def _build_plc_params_for_band(
        self,
        analysis_result: AnalysisResult,
        band_id: str,
    ) -> Optional[dict[str, Any]]:
        """重刮模式：根据指定 band_id 从已有 AnalysisResult 直接生成 PLC params dict。

        从 analysis_result.case_dir/summary.json 读取分析数据，
        用 cnc_path_generator 生成指定 band 的单 band 点位数组。

        副作用：同时将 G-code 文本落盘作为本地可视化（不下发到 PLC）。

        Returns:
            PLC params dict（含 12 个 g_xxx + 兼容字段），或 None（生成失败时）。
        """
        if not band_id:
            log.warning("[Scrape %s] 重刮模式: band_id 为空或 None", self._sample_id)
            return None

        if analysis_result is None:
            log.warning("[Scrape %s] 重刮模式: AnalysisResult 为 None", self._sample_id)
            return None

        case_dir = getattr(analysis_result, "case_dir", None)
        if case_dir is None:
            log.warning("[Scrape %s] 重刮模式: AnalysisResult.case_dir 为 None", self._sample_id)
            return None

        case_dir = Path(case_dir)  # 防御性转换
        summary_path = case_dir / "summary.json"

        # 尝试 process_pair 嵌套输出结构（case_dir/sample_id/summary.json）
        if not summary_path.exists():
            case_name = getattr(analysis_result, "case_name", "")
            if case_name:
                summary_path = case_dir / case_name / "summary.json"
        # 修正双重嵌套：case_dir = analysis_dir/sample_id/，回退到 analysis_dir/ 级
        if not summary_path.exists():
            summary_path = case_dir.parent / "summary.json"
        if not summary_path.exists():
            # 尝试从 SampleStore 回退查找
            if self._sample_store is not None and hasattr(self._sample_store, "get_summary_path"):
                try:
                    alt_path = self._sample_store.get_summary_path(self._sample_id)
                    if alt_path is not None and alt_path.is_file():
                        summary_path = alt_path
                except Exception:
                    pass

        if not summary_path.exists():
            log.warning(
                "[Scrape %s] 重刮模式: summary.json 不存在 (尝试路径: %s)",
                self._sample_id, summary_path,
            )
            return None

        gcode_cfg = _resolve_gcode_cfg(self._get_state())

        # 副作用：G-code 文本落盘作为可视化产物（不影响 PLC 下发）
        try:
            self._render_gcode_artifact(summary_path, [band_id], gcode_cfg)
        except Exception as e:
            log.warning("[Scrape %s] 重刮 G-code 可视化落盘失败: %s",
                        self._sample_id, e)

        # 主路径：生成 PLC 点位数组（应用配方 CNC 参数覆盖）
        gcode_cfg, strategy_ov, keep_ratio_ov = self._apply_recipe_cnc_overrides(gcode_cfg)
        try:
            arrays = generate_scrape_arrays(
                summary_path, band_id, gcode_cfg,
                strategy=strategy_ov, keep_ratio=keep_ratio_ov,
            )
        except (FileNotFoundError, KeyError, Exception) as e:
            log.warning(
                "[Scrape %s] 重刮 cnc_path_generator 生成失败 (band=%s): %s",
                self._sample_id, band_id, e,
            )
            return None

        log.info(
            "[Scrape %s] 重刮点位数组生成成功 (band=%s, pass_count=%d)",
            self._sample_id, band_id, arrays.g_pass_count,
        )
        # v2 主路径：重刮同样写 DB（band_id 主键会覆盖旧记录）
        self._persist_scrape_arrays_artifact(
            arrays, band_id, strategy_ov or gcode_cfg.path_strategy,
        )
        return _build_plc_params(arrays)

    # ------------------------------------------------------------------
    # ScrapeArrays 主路径产物落盘 + DB sideband（v2）
    # ------------------------------------------------------------------

    def _persist_scrape_arrays_artifact(
        self,
        arrays,
        band_id: str,
        strategy: str | None,
    ) -> None:
        """渲染 ScrapeArrays 路径 PNG 与调 sample_store DB sideband。

        主路径 v2：PLC 实际消费的是该 ScrapeArrays，DB 也应该以它为主索引。
        任何失败仅 log.warning，不影响 PLC 下发与主流程。
        """
        png_path: Optional[Path] = None
        try:
            from core.gcode_renderer import render_scrape_arrays_path
            if self._sample_store is not None and hasattr(self._sample_store, "get_gcode_dir"):
                gcode_dir = self._sample_store.get_gcode_dir(self._sample_id)
            else:
                gcode_dir = Path("data/samples") / self._sample_id / "gcode"
            gcode_dir.mkdir(parents=True, exist_ok=True)
            png_path = gcode_dir / f"{self._sample_id}_{band_id}_arrays_path.png"
            render_scrape_arrays_path(
                arrays, output_path=png_path,
                title=f"{self._sample_id} / {band_id} ({strategy or 'default'})",
            )
        except Exception as e:
            log.warning(
                "[Scrape %s] ScrapeArrays PNG 渲染失败（不影响主流程）: %s",
                self._sample_id, e,
            )
            png_path = None

        try:
            if (
                self._sample_store is not None
                and hasattr(self._sample_store, "trigger_db_scrape_arrays")
            ):
                self._sample_store.trigger_db_scrape_arrays(
                    self._sample_id, band_id, arrays,
                    png_path=png_path, strategy=strategy,
                )
        except Exception as e:
            log.debug(
                "[Scrape %s] trigger_db_scrape_arrays 异常（已忽略）: %s",
                self._sample_id, e,
            )

    # ------------------------------------------------------------------
    # 人工确认
    # ------------------------------------------------------------------

    async def _confirm_or_abort(self) -> bool:
        """视觉失败后的人工确认流程。返回 True=继续 / False=终止。"""
        should_continue = True
        if self._confirm_callback is not None:
            should_continue = await self._confirm_callback(self._sample_id)
            self._log.append(
                self._sample_id,
                "CONFIRM_CONT" if should_continue else "CONFIRM_STOP",
                fe.fmt_detail(stage=self.NAME, reason="vision_failed"),
            )
        return should_continue

    # ------------------------------------------------------------------
    # PLC FSM 归零等待
    # ------------------------------------------------------------------

    async def _wait_fsm_idle(self, timeout: float = 5.0) -> None:
        """等待 PLC scrape FSM 回到 Step 0（idle）。

        在写 Enable=FALSE 后调用，确保 PLC 侧状态机归零后再抛出异常，
        避免下一个 scrape 任务启动时因 PLC 尚未归零而错过上升沿。

        Warning #8: 超时 + Reset 尝试后若 Step 仍非 0，抛出 RuntimeError
        防止静默返回导致后续任务因 FSM 未归零而出错。
        """
        elapsed = 0.0
        interval = 0.1
        while elapsed < timeout:
            try:
                step_val = int(await self._plc.read_variable("scrape_Step"))
                if step_val == 0:
                    log.info("[Scrape %s] PLC FSM 已归零", self._sample_id)
                    return
            except Exception:
                pass
            await asyncio.sleep(interval)
            elapsed += interval
        log.warning("[Scrape %s] PLC FSM 归零超时 (%.1fs), 尝试强制 Reset",
                    self._sample_id, timeout)
        final_step = "unknown"
        try:
            await self._plc.write_variable("scrape_Reset", True)
            await asyncio.sleep(0.1)
            await self._plc.write_variable("scrape_Reset", False)
            # Reset 后再等一小段时间确认
            await asyncio.sleep(0.2)
            final_step = int(await self._plc.read_variable("scrape_Step"))
            if final_step == 0:
                log.info("[Scrape %s] PLC FSM 经 Reset 后已归零", self._sample_id)
                return
        except Exception:
            pass
        # Warning #8: Reset 后 FSM 仍未归零 → 抛出 RuntimeError
        raise RuntimeError(
            f"[Scrape {self._sample_id}] PLC FSM 归零失败（超时 {timeout:.1f}s + Reset 无效），"
            f"当前 Step={final_step}"
        )
