"""Vision Tab - 拍照刮板可视化交互界面。

功能：
  - 样品选择 / 分析触发
  - 分析结果展示（标注图 + band 列表）
  - Band 选择（自动/手动）
  - G-code 生成与预览

NiceGUI 注意：
  - ui.notify() 不可在后台 Task 中调用 -> 使用 state._notification_queue
  - @refreshable 内避免 ui.select（闪退）-> 用 ui.checkbox 列表
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from nicegui import ui

from dataclasses import replace as dc_replace

from core.cnc_path_generator import generate_scrape_arrays
from core.config import GCodeCfg
from core.gcode_generator import GCodeGenerator
from core.gcode_renderer import render_gcode_path, render_scrape_arrays_path
from core.sample_store import SampleStore
from core.vision_service import AnalysisResult, BandInfo, VisionService, build_vision_from_cfg
from ui.state import get_state

log = logging.getLogger(__name__)


def _format_arrays_summary(arrays, selected_bands: list[str]) -> str:
    """将 ScrapeArrays 格式化为可读文本摘要（替代 .gcode 文本预览）。"""
    lines = [
        "# CNC Path Summary (PLC actual execution data)",
        f"# Bands: {', '.join(selected_bands)}",
        f"# Pass count: {arrays.g_pass_count}",
        f"# Total depth: {arrays.g_total_depth} mm",
        f"# Safe Z: {arrays.g_safe_z} mm | Approach Z: {arrays.g_approach_z} mm",
        f"# Plate surface Z: {arrays.g_plate_surface_z} mm",
        f"# Scrape feed: {arrays.g_scrape_feed} mm/min | Plunge: {arrays.g_plunge_feed} mm/min",
        f"# Scrape points: {len(arrays.g_sx)} | Collect points: {len(arrays.g_cx)}",
    ]
    if arrays.g_sx:
        lines.append(f"# Scrape X range: [{min(arrays.g_sx):.2f}, {max(arrays.g_sx):.2f}] mm")
    if arrays.g_sy:
        lines.append(f"# Scrape Y range: [{min(arrays.g_sy):.2f}, {max(arrays.g_sy):.2f}] mm")
    if arrays.g_cx:
        lines.append(f"# Collect X range: [{min(arrays.g_cx):.2f}, {max(arrays.g_cx):.2f}] mm")
    if arrays.g_cy:
        lines.append(f"# Collect Y range: [{min(arrays.g_cy):.2f}, {max(arrays.g_cy):.2f}] mm")
    return "\n".join(lines)


def _resolve_vision_gcode_cfg(refs: dict) -> tuple[GCodeCfg, Optional[str], Optional[float]]:
    """解析 Vision Tab 的有效 GCodeCfg（base config.yaml + Vision Tab 手动覆盖）。

    Returns:
        (effective_cfg, strategy_override, keep_ratio_override)
        strategy/keep_ratio 为 None 时表示不覆盖，走 effective_cfg 内的值。
    """
    state = get_state()
    base_cfg = state.gcode_cfg if state.gcode_cfg is not None else GCodeCfg()
    cfg = base_cfg
    strategy_ov: Optional[str] = None
    keep_ratio_ov: Optional[float] = None

    # Vision Tab 手动覆盖（从 refs 读取 UI 控件值）
    passes_inp = refs.get("vision_cnc_passes")
    if passes_inp is not None and passes_inp.value and int(passes_inp.value) > 0:
        cfg = dc_replace(cfg, scrape=dc_replace(cfg.scrape, num_passes=int(passes_inp.value)))

    depth_inp = refs.get("vision_cnc_depth")
    if depth_inp is not None and depth_inp.value and float(depth_inp.value) > 0:
        cfg = dc_replace(cfg, scrape=dc_replace(cfg.scrape, total_depth_mm=float(depth_inp.value)))

    feed_inp = refs.get("vision_cnc_feed")
    if feed_inp is not None and feed_inp.value and int(feed_inp.value) > 0:
        cfg = dc_replace(cfg, scrape=dc_replace(cfg.scrape, feed_rate=int(feed_inp.value)))

    plunge_inp = refs.get("vision_cnc_plunge")
    if plunge_inp is not None and plunge_inp.value and int(plunge_inp.value) > 0:
        cfg = dc_replace(cfg, scrape=dc_replace(cfg.scrape, plunge_rate=int(plunge_inp.value)))

    strat_inp = refs.get("vision_cnc_strategy")
    if strat_inp is not None and strat_inp.value and strat_inp.value != "(default)":
        strategy_ov = str(strat_inp.value).strip().lower()

    kr_inp = refs.get("vision_cnc_keep_ratio")
    if kr_inp is not None and kr_inp.value and float(kr_inp.value) > 0:
        keep_ratio_ov = float(kr_inp.value)

    return cfg, strategy_ov, keep_ratio_ov


def render() -> dict:
    """构建 Vision Tab UI，返回 refreshable 引用。"""
    state = get_state()
    refs = {}

    # ── 分析结果展示区（含样品选择） ──
    analysis_card = ui.card().classes("w-full")
    refs["analysis_card"] = analysis_card
    with analysis_card:
        # 样品选择 + 操作按钮行
        with ui.row().classes("w-full items-center"):
            ui.label("Vision").classes("text-h6")
            ui.space()
            # 样品下拉框
            sample_select = ui.select(
                options=[],
                label="选择样品",
                with_input=True,
                on_change=lambda e: _on_sample_change(state, refs, e.value),
            ).classes("min-w-[200px]")
            refs["sample_select"] = sample_select

            # 分析按钮
            analyze_btn = ui.button(
                "开始分析",
                on_click=lambda: _on_analyze(state, refs),
            ).props("color=primary")
            refs["analyze_btn"] = analyze_btn

            # 分析状态指示
            analyzing_label = ui.label("").classes("text-caption")
            refs["analyzing_label"] = analyzing_label

        # 状态 banner：区分"实时分析等待下发" vs "历史数据浏览"
        with ui.row().classes("w-full items-center gap-2"):
            status_banner = ui.label("").classes("text-caption q-px-sm q-py-xs rounded")
            refs["status_banner"] = status_banner
            jump_btn = ui.button(
                "切换到实时样品",
                on_click=lambda: _jump_to_waiting_sample(state, refs),
            ).props("size=sm color=primary outline")
            jump_btn.visible = False
            refs["jump_btn"] = jump_btn

        # ScrapeStage 占用指示器
        scrape_indicator = ui.label("").classes("text-caption")
        refs["scrape_indicator"] = scrape_indicator

        ui.separator()

        # 轮廓图：显示所有 band 的标注图（矩形框 + 标签 + Rf 值）
        # object-contain 保比例 + 点击放大查看原图（避免横版图被压扁导致 band 标签挤压）
        contour_overview = ui.image().classes(
            "max-h-[480px] max-w-full object-contain cursor-pointer"
        ).tooltip("点击放大查看原图")
        contour_overview.on(
            "click",
            lambda _e=None, img=contour_overview: _open_image_dialog(
                img.source, "标注图"
            ),
        )
        refs["contour_overview"] = contour_overview

        # Before/After 双图并排对比区
        with ui.row().classes("w-full gap-2"):
            with ui.column().classes("flex-1"):
                ui.label("Before (点样后)").classes("text-caption")
                before_photo = ui.image().classes(
                    "max-h-[280px] w-full object-contain cursor-pointer"
                ).tooltip("点击放大查看原图")
                before_photo.on(
                    "click",
                    lambda _e=None, img=before_photo: _open_image_dialog(
                        img.source, "Before (点样后)"
                    ),
                )
                refs["before_photo"] = before_photo
            with ui.column().classes("flex-1"):
                ui.label("After (展开后)").classes("text-caption")
                after_photo = ui.image().classes(
                    "max-h-[280px] w-full object-contain cursor-pointer"
                ).tooltip("点击放大查看原图")
                after_photo.on(
                    "click",
                    lambda _e=None, img=after_photo: _open_image_dialog(
                        img.source, "After (展开后)"
                    ),
                )
                refs["after_photo"] = after_photo

        # band 信息摘要
        band_info_label = ui.label("").classes("text-caption")
        refs["band_info_label"] = band_info_label

    # ── Band 选择 + G-code 预览区 ──
    with ui.row().classes("w-full gap-4"):
        # Band 选择区
        with ui.card().classes("flex-1"):
            ui.label("Band 选择").classes("text-subtitle1")

            # 自动/手动切换
            with ui.row().classes("items-center"):
                selection_mode = ui.radio(
                    options={"auto": "自动选择（最大面积）", "manual": "手动选择（多选）"},
                    value="manual",
                    on_change=lambda e: _on_selection_mode_change(state, refs, e.value),
                ).props("dense")
                refs["selection_mode_radio"] = selection_mode

            # 调试：手动加载分析结果（summary.json）
            with ui.expansion("调试：手动加载分析结果（summary.json）", icon="science").classes("w-full") as debug_expansion:
                debug_expansion.props("dense")
                with ui.row().classes("w-full items-center gap-2"):
                    debug_summary_input = ui.input(
                        "summary.json 路径",
                        placeholder="如 D:/data/analysis/summary.json",
                    ).classes("flex-1").props("dense outlined")
                    refs["debug_summary_input"] = debug_summary_input
                    ui.button(
                        "加载 Band",
                        on_click=lambda: _on_load_debug_summary(state, refs),
                    ).props("size=sm color=secondary dense")

                with ui.row().classes("w-full items-center gap-2"):
                    debug_gcode_input = ui.input(
                        ".gcode 文件路径 (可选)",
                        placeholder="如 D:/data/output.gcode",
                    ).classes("flex-1").props("dense outlined")
                    refs["debug_gcode_input"] = debug_gcode_input
                    ui.button(
                        "加载文本(仅诊断)",
                        on_click=lambda: _on_load_debug_gcode(state, refs),
                    ).props("size=sm color=secondary dense")
                ui.label("注: .gcode 文本仅供诊断查看，路径预览和下发均基于点位数组").classes(
                    "text-caption text-grey"
                )

            # Band 复选框容器
            band_checkbox_container = ui.column().classes("w-full gap-1")
            refs["band_checkbox_container"] = band_checkbox_container

        # G-code 预览区
        with ui.card().classes("flex-1"):
            ui.label("G-code 预览").classes("text-subtitle1")

            with ui.tabs() as gcode_tabs:
                tab_text = ui.tab("文本")
                tab_path = ui.tab("路径图")

            with ui.tab_panels(gcode_tabs, value=tab_text).classes("w-full"):
                with ui.tab_panel(tab_text):
                    gcode_textarea = ui.textarea(
                        value="",
                    ).classes("w-full font-mono").props("rows=15 outlined dense readonly")
                    refs["gcode_textarea"] = gcode_textarea
                with ui.tab_panel(tab_path):
                    gcode_path_image = ui.image().classes(
                        "max-h-[480px] max-w-full object-contain cursor-pointer"
                    ).tooltip("点击放大查看原图")
                    gcode_path_image.on(
                        "click",
                        lambda _e=None, img=gcode_path_image: _open_image_dialog(
                            img.source, "G-code 路径图"
                        ),
                    )
                    refs["gcode_path_image"] = gcode_path_image

            with ui.row().classes("w-full items-center gap-2 mt-2"):
                ui.button(
                    "生成 G-code",
                    on_click=lambda: _on_generate_gcode(state, refs),
                ).props("color=primary")

                confirm_btn = ui.button(
                    "确认选择并下发刮取",
                    on_click=lambda: _on_confirm_gcode(state, refs),
                ).props("color=positive")
                confirm_btn.set_enabled(False)
                refs["confirm_btn"] = confirm_btn

                # Scrape 等待状态提示
                scrape_wait_label = ui.label("").classes("text-caption")
                refs["scrape_wait_label"] = scrape_wait_label

    # ── CNC 工艺参数覆盖面板 ──
    with ui.card().classes("w-full q-pa-md q-mt-sm"):
        with ui.expansion("CNC 工艺参数覆盖", icon="tune").classes("w-full"):
            ui.label("覆盖 config.yaml 全局默认值；0/空=不覆盖（走全局配置）。"
                     "配方级覆盖在 Recipe Tab 的 scrape 阶段参数中设置。").classes(
                "text-caption text-grey q-mb-sm"
            )
            with ui.row().classes("items-center gap-3 flex-wrap"):
                refs["vision_cnc_passes"] = ui.number(
                    label="passes (0=全局)", value=0, min=0, max=10,
                ).classes("w-32").props("dense outlined")
                refs["vision_cnc_depth"] = ui.number(
                    label="depth mm (0=全局)", value=0.0, min=0.0, max=10.0, step=0.1,
                ).classes("w-36").props("dense outlined")
                refs["vision_cnc_feed"] = ui.number(
                    label="feed mm/min (0=全局)", value=0, min=0, max=5000, step=10,
                ).classes("w-40").props("dense outlined")
                refs["vision_cnc_plunge"] = ui.number(
                    label="plunge mm/min (0=全局)", value=0, min=0, max=2000, step=10,
                ).classes("w-40").props("dense outlined")
            with ui.row().classes("items-center gap-3 flex-wrap q-mt-xs"):
                refs["vision_cnc_strategy"] = ui.select(
                    options=["(default)", "zigzag", "boustrophedon", "contour"],
                    value="(default)", label="path_strategy",
                ).classes("w-44").props("dense outlined")
                refs["vision_cnc_keep_ratio"] = ui.number(
                    label="keep_ratio (0=全局)", value=0.0,
                    min=0.0, max=1.0, step=0.05, format="%.2f",
                ).classes("w-40").props("dense outlined")

    # 初始化样品列表
    _refresh_sample_list(state, refs)

    return refs


# ──────────────────────────────────────────────────────────────────────
# 样品列表刷新
# ──────────────────────────────────────────────────────────────────────

# ───────────────────────────────────────────────────────────────────
# 图像放大查看 dialog（全局复用）
# ───────────────────────────────────────────────────────────────────

def _open_image_dialog(src: Optional[str], title: str = "原图") -> None:
    """弹出 maximized dialog 显示原图（不压缩）。

    每次不依赖状态全新构造 dialog（与 compare.py 同模式），
    避免多样品切换时 dialog 状态泄漏。src 为 None/空串时仅提示。
    """
    if not src:
        ui.notify("暂无图像可放大", type="info")
        return
    dlg = ui.dialog().props("maximized")
    with dlg:
        with ui.card().classes("w-full h-full bg-black q-pa-sm"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(title).classes("text-white text-subtitle1")
                ui.button("关闭", on_click=dlg.close).props("flat color=white icon=close")
            ui.image(src).classes(
                "max-w-full max-h-[88vh] object-contain w-full"
            )
    dlg.open()


def _refresh_sample_list(state, refs: dict) -> None:
    """刷新样品下拉框选项。"""
    sample_select = refs.get("sample_select")
    if sample_select is None:
        return

    store = state.sample_store
    if store is None:
        # 初始化 SampleStore
        data_dir = Path("data/samples")
        store = SampleStore(root_dir=data_dir)
        state.sample_store = store

    samples = store.list_samples()
    sample_select.options = samples
    if state.vision_current_sample_id in samples:
        sample_select.value = state.vision_current_sample_id
    elif samples:
        sample_select.value = samples[0]
        state.vision_current_sample_id = samples[0]
    sample_select.update()


def _is_owner_sample(state) -> bool:
    """当前选中样品是否为乒乓採业样品——可以下发 G-code。

    需同时满足：
      1. vision_waiting_sample_id == vision_current_sample_id
      2. vision_scrape_waiting=True（处于乒乓等待中）
    """
    return (
        state.vision_waiting_sample_id is not None
        and state.vision_waiting_sample_id == state.vision_current_sample_id
        and state.vision_scrape_waiting
    )


def _compute_view_state(state) -> dict:
    """计算当前视图相对于全局 live 的归属关系。

    区分两种 live：
      - is_live_for_view: 当前视图样品处于 live 状态（才应该高亮）
      - other_live: 全局有 live 但不是当前视图样品（应试默提示 + 跳转入口）
    """
    cur = state.vision_current_sample_id
    wait_id = state.vision_waiting_sample_id
    is_scrape = state.vision_scrape_waiting
    is_bphoto = state.vision_before_photo_waiting
    is_analyzing = state.vision_analyzing

    is_owner = (
        cur is not None and wait_id is not None and cur == wait_id
    )
    return {
        "is_analyzing": is_analyzing,
        "is_scrape": is_scrape,
        "is_bphoto": is_bphoto,
        "is_owner": is_owner,
        "owner_scrape": is_scrape and is_owner,
        "owner_bphoto": is_bphoto and is_owner,
        "is_live_for_view": (
            is_analyzing
            or (is_scrape and is_owner)
            or (is_bphoto and is_owner)
        ),
        "other_live": (is_scrape or is_bphoto) and not is_owner,
        "wait_id": wait_id,
    }


def _clear_vision_state(state, refs: dict) -> None:
    """清理 Vision Tab 内存 state 与 UI 控件，磁盘 SampleStore 保留。

    仅清“浏览态”字段；不动“乒乓採业态”字段（vision_waiting_sample_id /
    vision_scrape_waiting / vision_band_selection_future / vision_*_photo_path），
    避免干扰 ScrapeStage / BeforePhotoStage 的运行。
    """
    state.vision_analysis_result = None
    state.vision_selected_bands = []
    state.vision_gcode_text = None
    state.vision_gcode_path = None
    # 不将 mode 重置为 "auto"：会与 UI radio 默认 "manual" 不一致，
    # 导致 _update_band_checkboxes 误禁用复选框，
    # 并使 ScrapeStage._wait_for_band_selection 误用 15s 超时。
    # 保持与 state.py 默认 + UI radio 构建值三方一致："manual"。
    state.vision_band_selection_mode = "manual"
    # 清除 checkbox 指纹缓存：避免清空后陈旧指纹阻止下次重建
    state._ui_refresh_cache.pop("vision_band_checkboxes_fp", None)

    # 清空图片控件 + 缓存
    for key in ("contour_overview", "before_photo", "after_photo", "gcode_path_image"):
        ctrl = refs.get(key)
        if ctrl is None:
            continue
        try:
            ctrl.set_source("")
        except Exception:
            pass
        if hasattr(ctrl, "_src_cache"):
            ctrl._src_cache = None

    # 清空 G-code 文本
    gcode_textarea = refs.get("gcode_textarea")
    if gcode_textarea is not None:
        try:
            gcode_textarea.set_value("")
        except Exception:
            pass

    # 清空 Band 复选框容器
    container = refs.get("band_checkbox_container")
    if container is not None:
        try:
            container.clear()
        except Exception:
            pass

    # band 信息摘要
    band_info_label = refs.get("band_info_label")
    if band_info_label is not None:
        band_info_label.text = ""


async def _load_sample_from_store(state, refs: dict, sample_id: str) -> None:
    """从 SampleStore 加载给定样品的历史数据（before/after/标注图 + summary）。

    有分析结果 → 复用 _load_existing_analysis；无则仅靠 refresh_vision 从
    SampleStore 读取 before/after 路径渲染（无需额外动作）。
    """
    store = state.sample_store
    if store is None:
        return
    try:
        if store.has_analysis(sample_id):
            await _load_existing_analysis(state, refs, sample_id)
    except Exception as e:
        log.warning("[Vision Tab] 加载历史分析失败 (sample=%s): %s", sample_id, e)


def _on_sample_change(state, refs: dict, new_id) -> None:
    """下拉框 on_change 回调：切样品时清理内存 state + 从 SampleStore 重载。"""
    if not new_id:
        return
    if state.vision_current_sample_id == new_id and state.vision_analysis_result is not None:
        # 已加载过，避免重复刷新
        return
    state.vision_current_sample_id = new_id

    # 乒乓守卫：切换到正在等待的乒乓样品时，不清空 ScrapeStage 已预设的状态
    # （vision_selected_bands / vision_band_selection_mode 由 _push_to_vision_tab 驱动）
    if (
        state.vision_scrape_waiting
        and new_id == state.vision_waiting_sample_id
        and state.vision_analysis_result is not None
    ):
        # 已有 ScrapeStage 推送的分析结果，跳过 clear，直接显示
        return

    _clear_vision_state(state, refs)
    # 异步加载历史数据（on_change 为同步回调，使用 create_task 调用异步加载器）
    try:
        asyncio.create_task(_load_sample_from_store(state, refs, new_id))
    except RuntimeError:
        # 无运行中 loop（极端场景）——跳过异步加载，refresh_vision 仍会渲染基础图片
        pass


def _jump_to_waiting_sample(state, refs: dict) -> None:
    """banner 按钮回调：将下拉框切到当前乒乓所属样品。"""
    waiting_id = state.vision_waiting_sample_id
    if not waiting_id:
        return
    sample_select = refs.get("sample_select")
    if sample_select is None:
        return
    if waiting_id not in (sample_select.options or []):
        # 样品不在列表中，先刷新一下
        _refresh_sample_list(state, refs)
    sample_select.value = waiting_id
    sample_select.update()
    # 手动触发 on_change 逻辑（防 NiceGUI 同值不触发）
    _on_sample_change(state, refs, waiting_id)


# ──────────────────────────────────────────────────────────────────────
# 事件处理
# ──────────────────────────────────────────────────────────────────────

async def _on_analyze(state, refs: dict) -> None:
    """触发视觉分析。"""
    # ScrapeStage 占用守卫：ScrapeStage 正在分析时禁止手动触发
    if state.vision_scrape_waiting:
        state._notification_queue.append(("ScrapeStage 正在分析中，请等待完成", "warning"))
        return

    sample_id = _get_selected_sample_id(state, refs)
    if not sample_id:
        state._notification_queue.append(("请先选择样品", "warning"))
        return

    store = state.sample_store
    before_path = store.get_before_path(sample_id)
    after_path = store.get_after_path(sample_id)

    if not before_path or not after_path:
        state._notification_queue.append(
            (f"样品 {sample_id} 缺少 before/after 图像", "warning")
        )
        return

    # 如果已有分析结果：检查图像时间戳决定加载缓存或重新分析
    if store.has_analysis(sample_id):
        if not _images_newer_than_cache(store, sample_id, before_path, after_path):
            await _load_existing_analysis(state, refs, sample_id)
            return
        # 图像比缓存更新 → 自动重新分析（无需用户干预）
        log.info("[Vision Tab] 图像比缓存更新，自动重新分析 (sample=%s)", sample_id)

    # 执行分析
    state.vision_analyzing = True
    _update_analyzing_label(refs, True)

    try:
        analysis_dir = store.get_analysis_dir(sample_id)
        analysis_dir.mkdir(parents=True, exist_ok=True)

        vision = build_vision_from_cfg(state.vision_cfg, output_dir=analysis_dir)
        result = await vision.analyze_full(
            sample_id=sample_id,
            before_path=before_path,
            after_path=after_path,
        )
        state.vision_analysis_result = result

        if result.ok:
            # 默认手动模式，不预选 band（只有用户主动切 auto 才触发自动选择）
            state.vision_selected_bands = []
            _update_analysis_display(state, refs)
            _update_band_checkboxes(state, refs)
            # 同步 analyses + bands 到 DB 二级索引层
            try:
                summary_path = result.case_dir / "summary.json"
                if summary_path.exists():
                    summary_data = result.summary or {}
                    bands_data = summary_data.get("bands", []) if summary_data else []
                    store.trigger_db_analysis(sample_id, summary_data, summary_path, bands_data)
            except Exception as e:
                log.debug("[Vision Tab] DB 同步分析结果失败（已忽略）: %s", e)
            state._notification_queue.append(
                (f"分析完成: {len(result.bands)} 条 band", "positive")
            )
        else:
            state._notification_queue.append(("分析失败", "negative"))

    except Exception as e:
        log.error("[Vision Tab] 分析异常: %s", e, exc_info=True)
        state._notification_queue.append((f"分析异常: {e}", "negative"))
    finally:
        state.vision_analyzing = False
        _update_analyzing_label(refs, False)


async def _load_existing_analysis(state, refs: dict, sample_id: str) -> None:
    """加载已有的分析结果。

    case_dir 取 summary.json 所在目录（process_pair 输出可能在 analysis_dir/{sample_id}/ 子目录），
    确保 path_json 等相对路径能正确解析。
    """
    import json

    store = state.sample_store
    summary_path = store.get_summary_path(sample_id)
    if not summary_path:
        state._notification_queue.append(("summary.json 不存在", "warning"))
        return

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        state._notification_queue.append((f"读取 summary 失败: {e}", "negative"))
        return

    # case_dir 取 summary.json 所在目录，确保与 process_pair 输出目录一致
    case_dir = summary_path.parent

    # 从 summary 构建 AnalysisResult
    from core.vision_service import VisionService
    band_infos = VisionService._extract_band_infos(summary, case_dir)

    annotated_path = store.get_annotated_image_path(sample_id)
    before_path = store.get_before_path(sample_id)
    after_path = store.get_after_path(sample_id)

    # 标注图不存在但有 after 图像 → 动态生成（利用已有 summary 中的 contour/path 数据）
    if not annotated_path and after_path and after_path.is_file():
        try:
            svc = build_vision_from_cfg(state.vision_cfg, output_dir=case_dir)
            annotated_path = svc._generate_annotated_image(
                sample_id, case_dir, band_infos, after_path,
            )
            if annotated_path:
                log.info("[Vision Tab] 已动态生成标注图: %s", annotated_path)
        except Exception as e:
            log.warning("[Vision Tab] 动态生成标注图失败: %s", e)

    result = AnalysisResult(
        ok=True,
        case_name=sample_id,
        case_dir=case_dir,
        summary=summary,
        bands=band_infos,
        annotated_image_path=annotated_path,
        before_image_path=before_path,
        after_image_path=after_path,
    )
    state.vision_analysis_result = result
    # 默认手动模式，不预选 band（与 _on_analyze 保持一致）
    state.vision_selected_bands = []
    _update_analysis_display(state, refs)
    _update_band_checkboxes(state, refs)
    state._notification_queue.append(
        (f"已加载分析结果: {len(band_infos)} 条 band", "positive")
    )


def _images_newer_than_cache(store, sample_id: str, before_path, after_path) -> bool:
    """检查图像文件是否比缓存的 summary.json 更新。

    确定性算法 + 相同输入 = 相同输出，仅当图像更新时才需重新分析。
    """
    summary_path = store.get_summary_path(sample_id)
    if not summary_path or not summary_path.is_file():
        return True  # 无缓存，视为需要分析
    summary_mtime = summary_path.stat().st_mtime
    for img in (before_path, after_path):
        if img and Path(img).is_file() and Path(img).stat().st_mtime > summary_mtime:
            return True
    return False





# ──────────────────────────────────────────────────────────────────────
# 调试：手动加载固定 G-code
# ──────────────────────────────────────────────────────────────────────

def _on_load_debug_summary(state, refs: dict) -> None:
    """手动加载 summary.json，构造 AnalysisResult 供 band 选择和下发使用。

    绕过视觉分析，直接复用已有分析产物驱动 ScrapeStage 乒乓下发。
    case_dir 取 summary.json 所在目录，确保 ScrapeStage._build_plc_params_from_vision
    能通过 case_dir/summary.json 定位文件。
    """
    import json

    inp = refs.get("debug_summary_input")
    if inp is None:
        return
    raw = (inp.value or "").strip()
    if not raw:
        state._notification_queue.append(("请输入 summary.json 路径", "warning"))
        return

    path = Path(raw)
    if not path.is_file():
        state._notification_queue.append((f"文件不存在: {raw}", "negative"))
        return

    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        state._notification_queue.append((f"读取 summary.json 失败: {e}", "negative"))
        return

    case_dir = path.parent
    band_infos = VisionService._extract_band_infos(summary, case_dir)
    if not band_infos:
        state._notification_queue.append(("summary.json 中未提取到 band 信息", "warning"))
        return

    result = AnalysisResult(
        ok=True,
        case_name=path.stem,
        case_dir=case_dir,
        summary=summary,
        bands=band_infos,
    )
    state.vision_analysis_result = result
    state.vision_selected_bands = []
    # 清除 checkbox 指纹缓存，强制重建
    state._ui_refresh_cache.pop("vision_band_checkboxes_fp", None)
    _update_band_checkboxes(state, refs)

    non_origin = [b for b in band_infos if not b.is_origin]
    state._notification_queue.append(
        (f"已加载 {len(non_origin)} 条 band（共 {len(band_infos)} 条含 origin）", "positive")
    )
    log.info("[Vision Tab] 调试模式加载 summary: %s (%d bands)", path, len(band_infos))


def _on_load_debug_gcode(state, refs: dict) -> None:
    """手动加载 .gcode 文件内容到预览区（仅可视化，不影响下发逻辑）。

    .gcode 文件为可选——ScrapeStage 实际消费的是从 summary.json 生成的点位数组，
    而非 .gcode 文本。此函数仅供用户在 Vision Tab 预览已有 G-code 内容。
    """
    inp = refs.get("debug_gcode_input")
    if inp is None:
        return
    raw = (inp.value or "").strip()
    if not raw:
        state._notification_queue.append(("请输入 .gcode 文件路径", "warning"))
        return

    path = Path(raw)
    if not path.is_file():
        state._notification_queue.append((f"文件不存在: {raw}", "negative"))
        return

    try:
        gcode_text = path.read_text(encoding="utf-8")
    except Exception as e:
        state._notification_queue.append((f"读取 .gcode 失败: {e}", "negative"))
        return

    state.vision_gcode_text = gcode_text
    state.vision_gcode_path = path

    # 更新文本预览
    gcode_textarea = refs.get("gcode_textarea")
    if gcode_textarea:
        gcode_textarea.set_value(gcode_text)

    # 尝试渲染路径图
    try:
        preview_png = path.with_suffix("_debug_path.png")
        path_image_path = render_gcode_path(path, output_path=preview_png)
        gcode_path_image = refs.get("gcode_path_image")
        if gcode_path_image and path_image_path:
            gcode_path_image.set_source(str(path_image_path))
    except Exception as e:
        log.debug("[Vision Tab] 调试 G-code 路径图渲染失败（不影响文本预览）: %s", e)

    line_count = gcode_text.count("\n") + 1
    state._notification_queue.append(
        (f"已加载 G-code: {path.name} ({line_count} 行)", "positive")
    )
    log.info("[Vision Tab] 调试模式加载 G-code: %s (%d 行)", path, line_count)


def _on_selection_mode_change(state, refs: dict, mode: str) -> None:
    """切换自动/手动选择模式。"""
    state.vision_band_selection_mode = mode
    if mode == "auto":
        _apply_auto_selection(state, refs)
    else:
        # 手动模式：清空选择，让用户勾选
        state.vision_selected_bands = []
    _update_band_checkboxes(state, refs)
    # 模式切换后重新生成 G-code 预览，确保路径图与当前选中 band 一致
    _regenerate_gcode_preview(state, refs)


def _apply_auto_selection(state, refs: dict) -> None:
    """自动选择面积最大的 1 条非 origin band。"""
    result = state.vision_analysis_result
    if not result or not result.bands:
        state.vision_selected_bands = []
        return

    non_origin = [b for b in result.bands if not b.is_origin]
    if not non_origin:
        state.vision_selected_bands = []
        return

    # 显式按 area_cm2 降序排序，band_id 作为 tiebreaker；避免 max() 在面积相等时返回首个的隐式行为
    ranked = sorted(non_origin, key=lambda b: (-b.area_cm2, b.band_id))
    log.info(
        "[Vision Tab] auto candidates: %s",
        [(b.band_id, round(b.area_cm2, 2)) for b in ranked],
    )
    best = ranked[0]
    state.vision_selected_bands = [best.band_id]
    log.info("[Vision Tab] 自动选择: %s (面积=%.2f cm²)", best.band_id, best.area_cm2)


async def _on_generate_gcode(state, refs: dict) -> None:
    """生成 CNC 点位数组并渲染预览（统一使用 cnc_path_generator）。"""
    result = state.vision_analysis_result
    if not result or not result.ok:
        state._notification_queue.append(("请先完成分析", "warning"))
        return

    selected = state.vision_selected_bands
    if not selected:
        state._notification_queue.append(("请选择至少一条 band", "warning"))
        return

    store = state.sample_store
    sample_id = state.vision_current_sample_id

    summary_path = result.case_dir / "summary.json"
    if not summary_path.exists():
        state._notification_queue.append(("summary.json 不存在", "negative"))
        return

    try:
        gcode_dir = store.get_gcode_dir(sample_id) if store else result.case_dir
        gcode_dir.mkdir(parents=True, exist_ok=True)

        # 使用含 band ID 的唯一路径，避免浏览器缓存导致图像不刷新
        bands_suffix = "_".join(selected)
        preview_png = gcode_dir / f"{sample_id}_{bands_suffix}_path.png"

        # 解析 GCodeCfg（config.yaml 基础 + Vision Tab 手动覆盖）
        gcode_cfg, strategy_ov, keep_ratio_ov = _resolve_vision_gcode_cfg(refs)

        # CNC 点位数组生成与路径渲染均为 CPU/IO 密集操作，通过 executor 异步化避免阻塞 UI
        loop = asyncio.get_running_loop()
        arrays = await loop.run_in_executor(
            None,
            lambda: generate_scrape_arrays(
                summary_path, selected[0], gcode_cfg,
                strategy=strategy_ov, keep_ratio=keep_ratio_ov,
            ),
        )

        # 路径图渲染（直接从 ScrapeArrays，确保预览 = PLC 实际执行路径）
        path_image_path = await loop.run_in_executor(
            None,
            lambda: render_scrape_arrays_path(
                arrays, output_path=preview_png,
                title=f"{sample_id} ({strategy_ov or gcode_cfg.path_strategy})",
            ),
        )

        # 文本预览：ScrapeArrays 参数摘要
        gcode_text = _format_arrays_summary(arrays, selected)

        state.vision_gcode_text = gcode_text
        state.vision_gcode_path = path_image_path
        # v2 别名同步赋值
        state.vision_arrays_summary = gcode_text
        state.vision_preview_path = path_image_path

        # 更新 UI
        gcode_textarea = refs.get("gcode_textarea")
        if gcode_textarea:
            gcode_textarea.set_value(gcode_text)

        gcode_path_image = refs.get("gcode_path_image")
        if gcode_path_image:
            gcode_path_image.set_source(str(path_image_path))

        # 保存 metadata
        if store:
            store.save_metadata(sample_id, {
                "sample_id": sample_id,
                "selected_bands": selected,
            })
            store.trigger_db_selected_bands(sample_id, selected)
            # v2 主路径：将 ScrapeArrays 写入 DB scrape_arrays 表
            try:
                if hasattr(store, "trigger_db_scrape_arrays"):
                    store.trigger_db_scrape_arrays(
                        sample_id, selected[0], arrays,
                        png_path=path_image_path,
                        strategy=strategy_ov or gcode_cfg.path_strategy,
                    )
            except Exception as ex:
                log.debug("[Vision Tab] trigger_db_scrape_arrays 异常（已忽略）: %s", ex)

        state._notification_queue.append(
            (f"点位数组已生成: passes={arrays.g_pass_count} "
             f"strategy={strategy_ov or gcode_cfg.path_strategy}", "positive")
        )

    except Exception as e:
        log.error("[Vision Tab] 点位数组生成异常: %s", e, exc_info=True)
        # UI 一致性：生成失败后清空预览，避免用户看到上次预览误认为可用
        gcode_textarea = refs.get("gcode_textarea")
        if gcode_textarea:
            try:
                gcode_textarea.set_value("")
            except Exception:
                pass
        gcode_path_image = refs.get("gcode_path_image")
        if gcode_path_image:
            try:
                gcode_path_image.set_source("")
            except Exception:
                pass
            if hasattr(gcode_path_image, "_src_cache"):
                gcode_path_image._src_cache = None
        state.vision_gcode_text = None
        state.vision_gcode_path = None
        state.vision_arrays_summary = None
        state.vision_preview_path = None
        state._notification_queue.append((f"点位数组生成失败: {e}", "negative"))


def _on_confirm_gcode(state, refs: dict) -> None:
    """确认下发 G-code——解析 ScrapeStage 的乒乓等待 Future。"""
    # owner 守卫：当前查看的样品必须是乒乓中的样品，防止误下发
    if state.vision_current_sample_id != state.vision_waiting_sample_id:
        ui.notify(
            f"当前查看的不是实时样品（实时样品: {state.vision_waiting_sample_id}），无法下发",
            type="warning",
        )
        return
    future = state.vision_band_selection_future
    if future is not None and not future.done():
        # ScrapeStage 正在等待 band 选择：resolve Future，传入选中的 band 列表
        selected = list(state.vision_selected_bands)
        future.set_result(selected)
        log.info("[Vision Tab] 确认选择并下发: %s", selected)
        # 不在此处清除 vision_scrape_waiting，由 ScrapeStage.finally 统一清理
        # 禁用按钮防止重复点击
        confirm_btn = refs.get("confirm_btn")
        if confirm_btn:
            confirm_btn.set_enabled(False)
        scrape_wait_label = refs.get("scrape_wait_label")
        if scrape_wait_label:
            scrape_wait_label.text = ""
    else:
        ui.notify("当前无 ScrapeStage 等待", type="info")


# ──────────────────────────────────────────────────────────────────────
# UI 更新辅助
# ──────────────────────────────────────────────────────────────────────

def _get_selected_sample_id(state, refs: dict) -> Optional[str]:
    """获取当前选中的样品 ID。"""
    sample_select = refs.get("sample_select")
    if sample_select and sample_select.value:
        return sample_select.value
    return state.vision_current_sample_id


def _update_analyzing_label(refs: dict, analyzing: bool) -> None:
    """更新分析状态指示。"""
    label = refs.get("analyzing_label")
    if label:
        label.text = "分析中..." if analyzing else ""
        label.classes(replace="text-orange" if analyzing else "text-caption")


def _update_analysis_display(state, refs: dict) -> None:
    """更新分析结果展示区域。

    轮廓图展示标注后的 TLC 板图像（所有 band 矩形框 + 标签 + Rf 值），
    使用户能一目了然地看到所有检测到的 band 及其关键参数。
    """
    result = state.vision_analysis_result
    if not result:
        return

    # 轮廓图：使用标注图（显示所有 band 的 contour 轮廓、刮取路径、标签）
    contour_overview = refs.get("contour_overview")
    if contour_overview:
        src = None
        if result.annotated_image_path and result.annotated_image_path.is_file():
            src = str(result.annotated_image_path)
            # 使用绝对路径避免 NiceGUI 解析相对路径出错
            src = str(result.annotated_image_path.resolve())
            log.debug("[Vision Tab] 轮廓图路径: %s (exists=%s)",
                      src, result.annotated_image_path.is_file())
        elif result.after_image_path and result.after_image_path.is_file():
            src = str(result.after_image_path.resolve())
            log.debug("[Vision Tab] 回退到 after 图像: %s", src)
        if src:
            # 仅在路径变化时刷新图片；避免相同路径重复调用 set_source
            current_src = getattr(contour_overview, '_src_cache', None)
            if current_src != src:
                contour_overview.set_source(src)
                contour_overview._src_cache = src
                log.info("[Vision Tab] 轮廓图已更新: %s", src)
            contour_overview.visible = True
        else:
            contour_overview.visible = False
            log.warning("[Vision Tab] 无可显示的图像（annotated 和 after 均无效）")

    # Band 信息摘要
    band_info_label = refs.get("band_info_label")
    if band_info_label:
        non_origin = [b for b in result.bands if not b.is_origin]
        band_info_label.text = (
            f"检测到 {len(non_origin)} 条 band（共 {len(result.bands)} 条含 origin）"
        )

    # Band 复选框不在此处重建：避免 refresh_vision 周期销毁重建截断用户点击。
    # 仅在 _on_analyze / _load_existing_analysis / _on_selection_mode_change 里显式调用
    # _update_band_checkboxes。


def _update_band_checkboxes(state, refs: dict) -> None:
    """更新 Band 复选框列表。"""
    container = refs.get("band_checkbox_container")
    if container is None:
        return

    container.clear()
    result = state.vision_analysis_result
    if not result or not result.bands:
        with container:
            ui.label("暂无分析结果").classes("text-caption")
        return

    non_origin = [b for b in result.bands if not b.is_origin]
    is_manual = state.vision_band_selection_mode == "manual"
    selected = state.vision_selected_bands

    with container:
        for b in non_origin:
            is_checked = b.band_id in selected
            label_text = (
                f"{b.band_id}  Y={b.centroid_cm[1]:.2f}cm  "
                f"w={b.vertical_width_cm:.2f}cm  "
                f"A={b.area_cm2:.1f}cm²  "
                f"Rf={b.normalized_develop_height:.3f}"
            )
            cb = ui.checkbox(
                label_text,
                value=is_checked,
                on_change=lambda e, bid=b.band_id: _on_band_checkbox_change(
                    state, refs, bid, e.value
                ),
            )
            # 显式两端写，不依赖 NiceGUI 默认 enabled 行为
            cb.set_enabled(is_manual)
            if not is_manual and is_checked:
                cb.classes(replace="text-primary font-bold")

        if not non_origin:
            ui.label("未检测到非 origin band").classes("text-caption")


def _on_band_checkbox_change(state, refs: dict, band_id: str, checked: bool) -> None:
    """Band 复选框变化回调——更新选中列表并自动重新生成 G-code 预览。"""
    selected = list(state.vision_selected_bands)
    if checked and band_id not in selected:
        selected.append(band_id)
    elif not checked and band_id in selected:
        selected.remove(band_id)
    state.vision_selected_bands = selected
    # 自动触发 G-code 重新生成（刷新路径图和文本）
    _regenerate_gcode_preview(state, refs)


def _regenerate_gcode_preview(state, refs: dict) -> None:
    """根据当前选中的 band 重新生成点位数组预览（同步，统一使用 cnc_path_generator）。"""
    result = state.vision_analysis_result
    if not result or not result.ok:
        return

    # 无选中 band 时清空预览
    if not state.vision_selected_bands:
        gcode_textarea = refs.get("gcode_textarea")
        if gcode_textarea:
            gcode_textarea.set_value("")
        gcode_path_image = refs.get("gcode_path_image")
        if gcode_path_image:
            gcode_path_image.set_source("")
        return

    try:
        summary_path = result.case_dir / "summary.json"
        if not summary_path.exists():
            return

        selected = state.vision_selected_bands
        # 使用含 band ID 的唯一路径，避免浏览器缓存导致图像不刷新
        bands_suffix = "_".join(selected)
        preview_png = summary_path.parent / f"_preview_{bands_suffix}_path.png"

        # 解析 GCodeCfg（config.yaml 基础 + Vision Tab 手动覆盖）
        gcode_cfg, strategy_ov, keep_ratio_ov = _resolve_vision_gcode_cfg(refs)

        # 生成点位数组（与 PLC 实际执行路径一致）
        arrays = generate_scrape_arrays(
            summary_path, selected[0], gcode_cfg,
            strategy=strategy_ov, keep_ratio=keep_ratio_ov,
        )

        # 文本预览
        gcode_text = _format_arrays_summary(arrays, selected)
        state.vision_gcode_text = gcode_text
        state.vision_arrays_summary = gcode_text

        # 更新 UI 文本
        gcode_textarea = refs.get("gcode_textarea")
        if gcode_textarea:
            gcode_textarea.set_value(gcode_text)

        # 路径图渲染
        path_image_path = render_scrape_arrays_path(
            arrays, output_path=preview_png,
            title=f"{state.vision_current_sample_id} ({strategy_ov or gcode_cfg.path_strategy})",
        )
        state.vision_gcode_path = path_image_path
        state.vision_preview_path = path_image_path
        gcode_path_image = refs.get("gcode_path_image")
        if gcode_path_image:
            gcode_path_image.set_source(str(path_image_path))
    except Exception as e:
        log.warning("[Vision Tab] 点位数组重新生成失败: %s", e)


def refresh_vision(state, refs: dict) -> None:
    """Vision Tab 刷新入口，由 app.py timer 调用。"""
    # 刷新样品列表（仅当列表为空时）
    sample_select = refs.get("sample_select")
    if sample_select and not sample_select.options:
        _refresh_sample_list(state, refs)

    # 如果有分析结果变化，更新展示
    if state.vision_analysis_result and not state.vision_analyzing:
        _update_analysis_display(state, refs)

        # 一次性脏检查：分析结果 / mode / 选中列表变化时，重建一次 checkbox
        # 静态状态下不重建，避免 0.5s timer 打断用户点击
        cache = state._ui_refresh_cache
        ar = state.vision_analysis_result
        fp = (
            getattr(ar, "case_name", None),
            len(getattr(ar, "bands", []) or []),
            state.vision_band_selection_mode,
            tuple(state.vision_selected_bands),
        )
        if fp != cache.get("vision_band_checkboxes_fp"):
            cache["vision_band_checkboxes_fp"] = fp
            _update_band_checkboxes(state, refs)

    # ── 状态区分：当前视图 live vs 其他样品 live vs 历史 ──
    view = _compute_view_state(state)
    analysis_card = refs.get("analysis_card")
    status_banner = refs.get("status_banner")
    jump_btn = refs.get("jump_btn")

    if analysis_card:
        if view["is_live_for_view"]:
            # 实时模式（当前视图样品为归属样品）：橙色边框 + 浅橙背景
            analysis_card.style(
                replace="border: 2px solid #f59e0b; background: #fffbeb;"
            )
        else:
            # 历史浏览 / 其他样品 live：清空内联样式（必须用 replace=""
            # 才能真正清除，传位置参数 "" 等于 add="" 不会移除已有样式）
            analysis_card.style(replace="")

    if status_banner:
        if view["owner_scrape"]:
            status_banner.text = "● 实时分析 — 等待选择 Band 并下发 G-code"
            status_banner.classes(replace="text-caption q-px-sm q-py-xs rounded bg-orange-2 text-orange-9 text-bold")
            status_banner.visible = True
        elif view["owner_bphoto"]:
            status_banner.text = "● 实时拍照中 — BeforePhotoStage 正在执行"
            status_banner.classes(replace="text-caption q-px-sm q-py-xs rounded bg-orange-2 text-orange-9 text-bold")
            status_banner.visible = True
        elif view["is_analyzing"]:
            status_banner.text = "● 分析进行中..."
            status_banner.classes(replace="text-caption q-px-sm q-py-xs rounded bg-blue-1 text-blue-9 text-bold")
            status_banner.visible = True
        elif view["other_live"]:
            wait_id = view["wait_id"] or "?"
            status_banner.text = f"○ 另有样品 {wait_id} 正在实时分析"
            status_banner.classes(replace="text-caption q-px-sm q-py-xs rounded bg-grey-2 text-grey-7")
            status_banner.visible = True
        elif state.vision_analysis_result:
            status_banner.text = "○ 历史分析结果"
            status_banner.classes(replace="text-caption q-px-sm q-py-xs rounded bg-grey-2 text-grey-7")
            status_banner.visible = True
        else:
            status_banner.text = ""
            status_banner.visible = False

    # 跳转按钮：仅 other_live 时可见
    if jump_btn:
        jump_btn.visible = bool(view["other_live"] and view["wait_id"])

    # 按钮状态管理：仅当前视图样品是 live 时才锁定调作控件
    analyze_btn = refs.get("analyze_btn")
    scrape_indicator = refs.get("scrape_indicator")
    lock_controls = (
        view["is_analyzing"] or view["owner_scrape"] or view["owner_bphoto"]
    )

    if lock_controls:
        if sample_select:
            sample_select.set_enabled(False)
        if analyze_btn:
            analyze_btn.set_enabled(False)
    else:
        if sample_select:
            sample_select.set_enabled(True)
        if analyze_btn:
            analyze_btn.set_enabled(True)

    # selection_mode radio：仅当前视图为乒乓等待样品时开放 mode 切换；
    # 历史回看 / 其他样品 live / 纯浏览均禁用，避免误触发 _send_to_plc。
    selection_mode_radio = refs.get("selection_mode_radio")
    if selection_mode_radio is not None:
        selection_mode_radio.set_enabled(bool(view["owner_scrape"]))

    # scrape_indicator 文案：始终使用 wait_id（真正在 live 的样品）
    if scrape_indicator:
        if view["is_analyzing"]:
            scrape_indicator.text = "分析进行中..."
            scrape_indicator.classes(replace="text-orange text-caption")
        elif view["owner_scrape"]:
            scrape_indicator.text = f"ScrapeStage 实时分析中（样品: {view['wait_id']}）"
            scrape_indicator.classes(replace="text-orange text-caption")
        elif view["owner_bphoto"]:
            scrape_indicator.text = f"BeforePhotoStage 拍照中（样品: {view['wait_id']}）"
            scrape_indicator.classes(replace="text-orange text-caption")
        elif view["other_live"]:
            kind = "ScrapeStage" if view["is_scrape"] else "BeforePhotoStage"
            scrape_indicator.text = f"{kind} 实时任务运行中（样品: {view['wait_id']}）"
            scrape_indicator.classes(replace="text-grey text-caption")
        else:
            scrape_indicator.text = ""
            scrape_indicator.classes(replace="text-caption")

    # Before/After 双图并排刷新（防串图：非 owner 不使用 live 路径）
    before_photo = refs.get("before_photo")
    after_photo = refs.get("after_photo")
    result = state.vision_analysis_result
    use_live_paths = view["is_owner"] or view["is_analyzing"]

    if before_photo:
        bp = None
        if use_live_paths:
            bp = state.vision_before_photo_path
            if not bp or not bp.exists():
                if result and result.before_image_path and result.before_image_path.is_file():
                    bp = result.before_image_path
        else:
            if result and result.before_image_path and result.before_image_path.is_file():
                bp = result.before_image_path
        if bp and bp.exists():
            src = str(bp.resolve())
            if getattr(before_photo, '_src_cache', None) != src:
                before_photo.set_source(src)
                before_photo._src_cache = src
        else:
            if getattr(before_photo, '_src_cache', None) is not None:
                before_photo.set_source("")
                before_photo._src_cache = None

    if after_photo:
        ap = None
        if use_live_paths:
            ap = state.vision_scrape_after_path
            if not ap or not ap.exists():
                if result and result.after_image_path and result.after_image_path.is_file():
                    ap = result.after_image_path
        else:
            if result and result.after_image_path and result.after_image_path.is_file():
                ap = result.after_image_path
        if ap and ap.exists():
            src = str(ap.resolve())
            if getattr(after_photo, '_src_cache', None) != src:
                after_photo.set_source(src)
                after_photo._src_cache = src
        else:
            if getattr(after_photo, '_src_cache', None) is not None:
                after_photo.set_source("")
                after_photo._src_cache = None

    # ScrapeStage 乒乓等待状态：仅 owner 视图启用确认按钮
    confirm_btn = refs.get("confirm_btn")
    scrape_wait_label = refs.get("scrape_wait_label")
    if confirm_btn:
        if view["owner_scrape"]:
            confirm_btn.set_enabled(True)
            if scrape_wait_label:
                scrape_wait_label.text = "ScrapeStage 正在等待 band 选择..."
                scrape_wait_label.classes(replace="text-orange text-caption")
        elif view["other_live"] and view["is_scrape"]:
            confirm_btn.set_enabled(False)
            if scrape_wait_label:
                scrape_wait_label.text = f"样品 {view['wait_id']} 等待中—请先切换到该样品"
                scrape_wait_label.classes(replace="text-grey text-caption")
        else:
            confirm_btn.set_enabled(False)
            if scrape_wait_label:
                scrape_wait_label.text = ""

    # 通知队列由 app.py 统一消费，此处不再重复
