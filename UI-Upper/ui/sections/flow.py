"""Flow 流程可视化 Tab - 甘特色带 + 事件时间轴 + 系统总览

从 LogStore 读取 STAGE_START/DONE + STEP_START/DONE 事件，
用 CSS flex 色带渲染甘特条（每阶段一行，子步骤为行内色块）。

视图模式：
  - 甘特视图：阶段甘特条
  - 时间轴视图：列表展示所有事件
  - 工位卡片：单工位详细状态
  - 系统总览：4 大物理工位并发占用 + 8 缸网格
"""

import asyncio
import logging
from typing import Optional

from nicegui import ui

from core import flow_events as fe
from core.log_store import LogStore
from core.stage_state_registry import StageStateRegistry
from core.stages import STAGE_ORDER
from core.stages.before_photo import BEFORE_PHOTO_SUB_STEPS
from core.stages.collect import COLLECT_SUB_STEPS
from core.stages.develop import DEVELOP_SUB_STEPS
from core.stages.scrape import SCRAPE_SUB_STEPS
from core.stages.spotting import SPOTTING_SUB_STEPS
from core.resource_manager import TankStatus
from ui.state import get_state

log = logging.getLogger(__name__)

# 阶段颜色映射
_STAGE_COLORS = {
    "spotting":      "#3b82f6",  # blue
    "before_photo":  "#06b6d4",  # cyan
    "develop":       "#8b5cf6",  # purple
    "scrape":        "#f59e0b",  # amber
    "collect":       "#10b981",  # emerald
}

# 事件状态颜色
_EVENT_STATUS_COLOR = {
    "OK":       "green",
    "ERROR":    "red",
    "running":  "blue",
    "skipped":  "grey",
    "ESTOP":    "deep-orange",
    "CANCELLED":"orange",
}


def render() -> dict:
    """渲染 Flow 流程可视化 Tab。"""

    # 视图切换状态
    _view_mode = {"value": "gantt"}
    _selected_sample = {"value": None}

    # ── 样品选择下拉（不用 @ui.refreshable，避免 rebuild 摧毁 select） ──
    state = get_state()
    ids = state.log_store.all_sample_ids()
    if not ids:
        ids = list(state.sample_statuses.keys())
    if ids and _selected_sample["value"] is None:
        _selected_sample["value"] = ids[0]

    with ui.row().classes("items-center gap-3 q-mb-md"):
        sample_sel = ui.select(
            options=ids,
            value=_selected_sample["value"],
            label="选择样品",
            on_change=lambda e: _on_sample_change(e.value),
        ).classes("w-48")

        ui.toggle(
            options={"gantt": "甘特视图", "timeline": "时间轴", "stage": "工位卡片", "dashboard": "系统总览"},
            value=_view_mode["value"],
            on_change=lambda e: _on_view_change(e.value),
        )

    # 低频更新 select 的 options（脏检查：仅选项变化时才触及组件，
    # 避免 .update() 导致正在展开的下拉菜单被强制折叠）
    def _update_sample_options() -> None:
        st = get_state()
        new_ids = st.log_store.all_sample_ids()
        if not new_ids:
            new_ids = list(st.sample_statuses.keys())
        if list(sample_sel.options) == new_ids:
            return  # 选项未变化，不触及组件
        sample_sel.options = new_ids
        if _selected_sample["value"] not in new_ids and new_ids:
            _selected_sample["value"] = new_ids[0]
            sample_sel.value = new_ids[0]
        sample_sel.update()

    ui.timer(3.0, _update_sample_options)

    # 甘特/时间轴/工位卡片：
    # - 有运行中阶段时 1s 刷新让累计耗时走起来
    # - 无运行阶段时依赖 _periodic_refresh（app.py 0.5s 脏检查 log_store 条目数变化）
    _MONITORED_STAGES = ["collect", "develop", "spotting", "before_photo", "scrape"]
    
    # dashboard per-card refreshable：每张卡片独立刷新，避免无关工位变化导致 ui.expansion 折叠
    _dash_cards: dict = {}   # {"stats": refreshable, "header": refreshable, "spotting": ..., "develop": ..., "scrape": ..., "collect": ...}
    _dash_fps: dict = {}     # 每张卡片的指纹缓存

    # dashboard 顶部数据库统计卡片：总样品数 / 今日样品数 / 总 band 数 / 配方 Top1（30s 刷新）
    _stats_data: dict = {
        "total_samples": 0,
        "today_samples": 0,
        "total_bands": 0,
        "top_recipe": None,
        "loaded": False,     # 首次加载完成前显示「-」
        "db_disabled": False,  # 数据库未启用时单独提示
    }

    async def _refresh_stats() -> None:
        """异步加载 DB 统计；仅在 dashboard 视图且 stats 卡片存在时触发 UI 刷新。"""
        st = get_state()
        db = getattr(st, "database", None)
        if db is None or not getattr(db, "connected", False):
            _stats_data.update({
                "total_samples": 0,
                "today_samples": 0,
                "total_bands": 0,
                "top_recipe": None,
                "loaded": True,
                "db_disabled": True,
            })
        else:
            try:
                stats = await db.get_statistics()
            except Exception as e:
                log.debug("[Flow] get_statistics 异常: %s", e)
                return
            _stats_data.update(stats)
            _stats_data["loaded"] = True
            _stats_data["db_disabled"] = False
        ref = _dash_cards.get("stats")
        if ref is not None:
            try:
                ref.refresh()
            except Exception as e:
                log.debug("[Flow] stats 卡片刷新异常: %s", e)

    # 30s 节流刷新——dashboard 未激活时 _dash_cards.get("stats") 为 None，自然 no-op
    ui.timer(30.0, lambda: asyncio.create_task(_refresh_stats()))

    def _format_top_recipe(top_recipe) -> str:
        """配方 Top1 显示格式化：('PG-1', 5) → 'PG-1 ×5'；None → '—'。"""
        if not top_recipe:
            return "—"
        try:
            name, count = top_recipe
            return f"{name}  ×{int(count)}"
        except Exception:
            return "—"

    def _stats_content() -> None:
        """4 张统计卡片内容。loaded=False 时主数字以「-」占位；db_disabled=True 时顶部提示「数据库未启用」。

        在 render() 闭包内定义以访问 _stats_data；作为 ui.refreshable 的裸函数传入 _build_dashboard_cards。
        """
        loaded = _stats_data.get("loaded", False)
        db_disabled = _stats_data.get("db_disabled", False)
        placeholder = "—" if not loaded else None

        def _num(key: str) -> str:
            if placeholder is not None:
                return placeholder
            return str(_stats_data.get(key, 0))

        cards_def = [
            ("总样品数", _num("total_samples"), "inventory_2", "#3b82f6"),
            ("今日样品", _num("today_samples"), "today", "#10b981"),
            ("总 Band 数", _num("total_bands"), "view_module", "#8b5cf6"),
            (
                "配方使用 Top1",
                placeholder if placeholder is not None else _format_top_recipe(_stats_data.get("top_recipe")),
                "star",
                "#f59e0b",
            ),
        ]

        with ui.column().classes("w-full gap-1 q-mb-md"):
            if db_disabled:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("info", size="sm").classes("text-grey-6")
                    ui.label("数据库未启用，统计卡片仅展示零值").classes(
                        "text-caption text-grey-6"
                    )
            with ui.grid(columns=4).classes("w-full gap-3"):
                for title, value, icon, color in cards_def:
                    with ui.card().classes("q-pa-sm"):
                        with ui.row().classes("items-center no-wrap gap-2"):
                            ui.icon(icon, size="md").style(f"color: {color};")
                            with ui.column().classes("gap-0"):
                                ui.label(title).classes(
                                    "text-caption text-grey-7"
                                )
                                ui.label(value).classes(
                                    "text-h6 text-weight-bold"
                                )

    def _tick_dashboard_cards(st) -> None:
        """每张卡片独立指纹脏检查：一次性计算全部数据，按卡片粒度比较，仅刷新变化的卡片。"""
        snap = StageStateRegistry(st.log_store).snapshot(_MONITORED_STAGES)
        waiting = _derive_waiting_for_station(st)
        rm = getattr(st, "resource_manager", None)

        def _maybe(name: str, fp: tuple) -> None:
            if fp != _dash_fps.get(name):
                _dash_fps[name] = fp
                card = _dash_cards.get(name)
                if card:
                    card.refresh()

        # Header
        active = sum(1 for s in st.sample_statuses.values() if s == "RUNNING")
        pending = sum(1 for s in st.sample_statuses.values() if s == "PENDING")
        _maybe("header", (active, pending))

        # Spotting
        sp = snap["spotting"]
        _maybe("spotting", (sp.state, sp.sample_id, tuple(waiting.get("spotting", []))))

        # Develop — 含展缸状态
        dev = snap["develop"]
        tank_fp = ()
        if rm is not None:
            info = rm.all_tank_info()
            tank_fp = tuple(
                (i, info[i].state.value, info[i].sample_id) for i in range(1, 9)
            )
        _maybe("develop", (dev.state, dev.sample_id, tank_fp, tuple(waiting.get("develop", []))))

        # Scrape（合并 before_photo）
        bp, sc = snap["before_photo"], snap["scrape"]
        merged = bp if bp.state == "running" else sc
        _maybe("scrape", (merged.state, merged.sample_id, tuple(waiting.get("scrape", []))))

        # Collect
        co = snap["collect"]
        _maybe("collect", (co.state, co.sample_id, tuple(waiting.get("collect", []))))

        # Consumable
        cm = getattr(st, "consumable_manager", None)
        if cm is not None:
            cs = cm.snapshot()
            _maybe("consumable", (
                cs.powder_available, cs.bottle_available,
                cs.powder_staging_remaining, cs.bottle_staging_remaining,
            ))

    def _build_dashboard_cards() -> None:
        """构建 dashboard per-card refreshable 布局。

        每张工位卡片包装为独立 ui.refreshable，由 _tick_dashboard_cards()
        per-card 指纹脏检查驱动刷新——某张卡片数据变化不会重建其他卡片的 DOM。
        """
        _dash_cards.clear()
        _dash_fps.clear()

        # ── 顶部数据库统计卡片（4 张）──
        ref_stats = ui.refreshable(_stats_content)
        _dash_cards["stats"] = ref_stats
        ref_stats()

        # 首次进入 dashboard 时触发异步加载（30s 定时器后续维护刷新）
        asyncio.create_task(_refresh_stats())

        # ── Header 概览 ──
        def _header_content():
            st = get_state()
            active = sum(1 for s in st.sample_statuses.values() if s == "RUNNING")
            pending = sum(1 for s in st.sample_statuses.values() if s == "PENDING")
            with ui.card().classes("w-full q-pa-sm q-mb-md").style("background: #f8fafc;"):
                with ui.row().classes("items-center gap-4"):
                    ui.icon("dashboard", size="sm")
                    ui.label("pTLC 工作站总览").classes("text-subtitle1 text-weight-bold")
                    if active:
                        ui.badge(f"{active} 样品执行中", color="blue").classes("text-xs")
                    if pending:
                        ui.badge(f"{pending} 待执行", color="grey-6").classes("text-xs")

        ref_h = ui.refreshable(_header_content)
        _dash_cards["header"] = ref_h
        ref_h()

        # ── 2×2 工位卡片网格 ──
        with ui.grid(columns=2).classes("w-full gap-3"):
            # 左上：上样点样
            def _spotting_content():
                st = get_state()
                snap = StageStateRegistry(st.log_store).snapshot(["spotting"])
                waiting = _derive_waiting_for_station(st)
                _render_station_card(
                    "上样点样", "colorize", snap["spotting"], waiting.get("spotting", [])
                )

            ref_sp = ui.refreshable(_spotting_content)
            _dash_cards["spotting"] = ref_sp
            ref_sp()

            # 右上：展开（8 缸）
            def _develop_content():
                st = get_state()
                snap = StageStateRegistry(st.log_store).snapshot(["develop"])
                waiting = _derive_waiting_for_station(st)
                _render_develop_station(st, snap["develop"], waiting.get("develop", []))

            ref_dev = ui.refreshable(_develop_content)
            _dash_cards["develop"] = ref_dev
            ref_dev()

            # 左下：拍照刮板（合并 before_photo + scrape）
            def _scrape_content():
                st = get_state()
                snap = StageStateRegistry(st.log_store).snapshot(["before_photo", "scrape"])
                waiting = _derive_waiting_for_station(st)
                bp, sc = snap["before_photo"], snap["scrape"]
                merged = bp if bp.state == "running" else sc
                _render_station_card(
                    "拍照刮板", "photo_camera", merged, waiting.get("scrape", [])
                )

            ref_sc = ui.refreshable(_scrape_content)
            _dash_cards["scrape"] = ref_sc
            ref_sc()

            # 右下：收集
            def _collect_content():
                st = get_state()
                snap = StageStateRegistry(st.log_store).snapshot(["collect"])
                waiting = _derive_waiting_for_station(st)
                _render_station_card(
                    "收集", "filter_alt", snap["collect"], waiting.get("collect", [])
                )

            ref_co = ui.refreshable(_collect_content)
            _dash_cards["collect"] = ref_co
            ref_co()

        # ── 耗材状态卡片（全宽，位于工位网格下方）──
        def _consumable_content():
            st = get_state()
            cm = getattr(st, "consumable_manager", None)
            if cm is None:
                with ui.card().classes("w-full q-pa-sm q-mt-md"):
                    ui.label("耗材管理未就绪").classes("text-grey")
                return
            snap = cm.snapshot()
            powder_total = snap.powder_available
            bottle_total = snap.bottle_available
            powder_max, bottle_max = 24, 24

            def _bar_color(val, mx):
                ratio = val / mx if mx else 1
                if ratio < 0.1:
                    return "red"
                if ratio < 0.2:
                    return "orange"
                return "positive"

            with ui.card().classes("w-full q-pa-sm q-mt-md"):
                with ui.row().classes("w-full justify-between items-center"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("inventory_2", size="sm")
                        ui.label("耗材状态").classes("text-subtitle2 text-weight-bold")
                    # 导航到耗材 Tab
                    tab_consumable = getattr(st, "_tab_consumable", None)
                    tab_panels = getattr(st, "_tab_panels", None)
                    if tab_consumable and tab_panels:
                        ui.button(
                            "查看详情",
                            on_click=lambda: tab_panels.set_value(tab_consumable),
                        ).props("flat dense size=sm color=primary")

                with ui.column().classes("w-full gap-2 q-mt-sm"):
                    # 粉末收集器
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.label("粉末收集器").classes("w-24 text-caption")
                        ui.linear_progress(
                            value=powder_total / powder_max if powder_max else 0,
                        ).props(f"color={_bar_color(powder_total, powder_max)}").classes("flex-1")
                        ui.label(f"{powder_total}/{powder_max}").classes("text-caption w-12 text-right")
                        if snap.staging.get("A"):
                            sp = snap.staging["A"]
                            ui.label(f"暂存:板{sp.plate_id}(余{sp.remaining_available})").classes(
                                "text-caption text-grey"
                            )
                    # 玻璃收集瓶
                    with ui.row().classes("w-full items-center gap-2"):
                        ui.label("玻璃收集瓶").classes("w-24 text-caption")
                        ui.linear_progress(
                            value=bottle_total / bottle_max if bottle_max else 0,
                        ).props(f"color={_bar_color(bottle_total, bottle_max)}").classes("flex-1")
                        ui.label(f"{bottle_total}/{bottle_max}").classes("text-caption w-12 text-right")
                        if snap.staging.get("B"):
                            sb = snap.staging["B"]
                            ui.label(f"暂存:板{sb.plate_id}(余{sb.remaining_available})").classes(
                                "text-caption text-grey"
                            )

        ref_cm = ui.refreshable(_consumable_content)
        _dash_cards["consumable"] = ref_cm
        ref_cm()

    def _tick_stage_view() -> None:
        st = get_state()
        # dashboard 模式：per-card 指纹脏检查——仅刷新状态变化的卡片，保留其他卡片 expansion 展开态
        if _view_mode["value"] == "dashboard":
            if not _dash_cards:
                # 首次进入或视图切换后，需全量构建
                flow_content.refresh()
                return
            try:
                _tick_dashboard_cards(st)
            except Exception as e:
                log.debug("[Flow] dashboard 卡片刷新异常: %s", e)
            return
        snap = StageStateRegistry(st.log_store).snapshot(_MONITORED_STAGES)
        any_running = any(snap[s].state == "running" for s in _MONITORED_STAGES)
        if not any_running:
            return  # 无运行阶段，由 _periodic_refresh 负责
        flow_content.refresh()

    ui.timer(1.0, _tick_stage_view)

    @ui.refreshable
    def flow_content() -> None:
        """主内容区域（甘特 / 时间轴 / 工位卡片 / 系统总览）。"""
        state = get_state()

        # 系统总览：构建 per-card refreshable，后续由 _tick_dashboard_cards 选择性刷新
        if _view_mode["value"] == "dashboard":
            _build_dashboard_cards()
            return

        sid = _selected_sample["value"]
        if not sid:
            ui.label("暂无样品数据").classes("text-grey")
            return

        entries = state.log_store.get_sample(sid)
        if not entries:
            ui.label(f"样品 {sid} 暂无流程数据").classes("text-grey")
            return

        if _view_mode["value"] == "gantt":
            _render_gantt(entries, sid)
        elif _view_mode["value"] == "stage":
            _render_stage_cards(state.log_store)
        else:
            _render_timeline(entries, sid)

    def _on_sample_change(value: str) -> None:
        _selected_sample["value"] = value
        flow_content.refresh()

    def _on_view_change(value: str) -> None:
        _view_mode["value"] = value
        _dash_cards.clear()   # 切换视图时清理卡片引用
        _dash_fps.clear()
        flow_content.refresh()

    # 渲染
    flow_content()

    return {
        "flow_content": flow_content,
        "sample_selector": sample_sel,
        "flow_view_mode": lambda: _view_mode["value"],
    }


def _render_gantt(entries, sample_id: str) -> None:
    """甘特视图：每阶段一行色带，子步骤为行内色块。"""
    # 解析阶段和步骤事件
    stages_data = _parse_stage_events(entries)

    if not stages_data:
        ui.label("暂无阶段事件数据").classes("text-grey")
        return

    with ui.card().classes("w-full q-pa-md"):
        ui.label(f"样品 {sample_id} - 流程甘特图").classes(
            "text-subtitle1 text-weight-bold q-mb-md"
        )
        for stage_name in STAGE_ORDER:
            if stage_name not in stages_data:
                continue
            stage = stages_data[stage_name]
            color = _STAGE_COLORS.get(stage_name, "grey")

            with ui.row().classes("items-center gap-2 w-full q-mb-sm"):
                ui.label(f"{stage_name}").classes(
                    "text-caption font-mono w-20 shrink-0"
                )
                # 阶段状态色带
                status = stage.get("status", "running")
                bar_color = _EVENT_STATUS_COLOR.get(status, "blue")
                with ui.row().classes("flex-1 gap-1 items-center"):
                    for step in stage.get("steps", []):
                        step_status = step.get("status", "running")
                        step_color = _EVENT_STATUS_COLOR.get(step_status, "blue")
                        step_label = step.get("label", str(step.get("action_id", "")))
                        with ui.badge(
                            step_label[:12], color=step_color
                        ).classes("text-xs").style("cursor: default;"):
                            ui.tooltip(
                                f"ActionID: {step.get('action_id', '?')}  "
                                f"状态: {step_status}  "
                                f"耗时: {step.get('duration_ms', '?')}ms"
                            )

                    # 阶段状态标签
                    if status == "OK":
                        ui.icon("check_circle", color="green", size="xs")
                    elif status == "ERROR":
                        ui.icon("error", color="red", size="xs")
                    elif status == "ESTOP":
                        ui.icon("warning", color="deep-orange", size="xs")
                    elif status == "CANCELLED":
                        ui.icon("cancel", color="orange", size="xs")
                    elif status == "running":
                        ui.icon("hourglass_empty", color="blue", size="xs")


def _render_timeline(entries, sample_id: str) -> None:
    """时间轴视图：列表展示所有事件。"""
    with ui.card().classes("w-full q-pa-md"):
        ui.label(f"样品 {sample_id} - 事件时间轴").classes(
            "text-subtitle1 text-weight-bold q-mb-md"
        )
        with ui.column().classes("w-full gap-1"):
            for e in entries:
                with ui.row().classes("items-start gap-2 text-caption"):
                    ui.label(
                        e.timestamp.strftime("%H:%M:%S.%f")[:-3]
                    ).classes("text-grey font-mono shrink-0")
                    # 事件颜色
                    evt_color = "secondary"
                    if e.event in (fe.STAGE_DONE, fe.STEP_DONE):
                        evt_color = "positive"
                    elif e.event in ("ERROR",):
                        evt_color = "negative"
                    elif e.event in (fe.STAGE_START, fe.STEP_START):
                        evt_color = "primary"
                    elif e.event in (fe.STAGE_SKIPPED, fe.STEP_SKIPPED):
                        evt_color = "grey"
                    ui.badge(e.event, color=evt_color).classes(
                        "shrink-0 text-xs"
                    )
                    if e.detail:
                        ui.label(e.detail).classes("text-grey")


def _extract_kv(detail: str, key: str) -> Optional[str]:
    """从 detail 字符串提取 key=value 对的值。"""
    if not detail:
        return None
    for part in detail.split():
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return None


# 工位卡片：状态色（与 _EVENT_STATUS_COLOR 对齐）
_STAGE_STATE_COLOR = {
    "idle":    "grey",
    "running": "blue",
    "done":    "positive",
    "error":   "negative",
    "estop":   "deep-orange",
}

# 工位卡片的主干子步（排除 idle=0 / error=90）
_COLLECT_TIMELINE_STEPS = [10, 20, 30]
_DEVELOP_TIMELINE_STEPS = [10, 20, 30, 40, 50, 55, 60, 65]
_SPOTTING_TIMELINE_STEPS = [10, 20, 30, 40, 50]
_BEFORE_PHOTO_TIMELINE_STEPS = [10, 15]
_SCRAPE_TIMELINE_STEPS = [10, 15, 20, 30, 40]

# 工位 → (SUB_STEPS, TIMELINE_STEPS) 映射
# 插入顺序与 STAGE_ORDER 对齐（spotting→before_photo→develop→scrape→collect），
# 确保工位卡片按管线流程顺序显示
_STAGE_STEP_MAP = {
    "spotting": (SPOTTING_SUB_STEPS, _SPOTTING_TIMELINE_STEPS),
    "before_photo": (BEFORE_PHOTO_SUB_STEPS, _BEFORE_PHOTO_TIMELINE_STEPS),
    "develop": (DEVELOP_SUB_STEPS, _DEVELOP_TIMELINE_STEPS),
    "scrape": (SCRAPE_SUB_STEPS, _SCRAPE_TIMELINE_STEPS),
    "collect": (COLLECT_SUB_STEPS, _COLLECT_TIMELINE_STEPS),
}


def _render_stage_card(stage_name: str, st, sub_steps: dict, timeline_steps: list) -> None:
    """渲染单个工位卡片（节点高亮 + 占用 sample_id + 累计耗时）。"""
    from datetime import datetime

    # 耗时：running→从 since 到当前；done/error→duration_ms
    if st.state == "running" and st.since is not None:
        secs = (datetime.now() - st.since).total_seconds()
        elapsed_txt = f"{secs:0.1f} s"
    elif st.duration_ms is not None:
        elapsed_txt = f"{st.duration_ms / 1000:0.1f} s"
    else:
        elapsed_txt = "—"

    border_color = {
        "running": "#3b82f6",
        "done":    "#10b981",
        "error":   "#ef4444",
        "estop":   "#ea580c",
        "idle":    "#9ca3af",
    }[st.state]

    with ui.card().classes("w-full q-pa-md").style(
        f"border-left: 6px solid {border_color};"
    ):
        # 标题行：工位名 + 状态徽章
        with ui.row().classes("items-center gap-3 w-full"):
            ui.label(stage_name).classes("text-h6 text-weight-bold")
            ui.badge(
                st.state.upper(),
                color=_STAGE_STATE_COLOR.get(st.state, "grey"),
            ).classes("text-xs")
            if st.state == "error":
                ui.icon("error", color="red")

        # 样品 ID + 累计耗时
        # done/idle 态：工位已释放，不再显示占用样品
        sample_display = st.sample_id if st.state in ("running", "error") else "—"
        with ui.row().classes("items-center gap-6 q-mt-sm"):
            ui.label(f"占用样品：{sample_display}").classes("text-body2")
            ui.label(f"累计耗时：{elapsed_txt}").classes("text-body2")
            if st.step is not None:
                sub = sub_steps.get(st.step)
                if sub is not None:
                    _, label = sub
                    ui.label(f"当前子步：{st.step} ({label})").classes(
                        "text-body2 text-primary"
                    )

        # 子步节点高亮
        with ui.row().classes("items-center gap-1 q-mt-md"):
            for idx, code in enumerate(timeline_steps):
                if code not in sub_steps:
                    log.warning("timeline step %d not in SUB_STEPS, skip", code)
                    continue
                key, label = sub_steps[code]
                passed = st.step is not None and st.step >= code and st.step != 90
                active = st.step == code and st.state == "running"
                if st.state == "error" and st.step is not None and st.step >= code:
                    color = "negative"
                elif active:
                    color = "blue"
                elif passed or st.state == "done":
                    color = "positive"
                else:
                    color = "grey-4"
                ui.badge(f"{code} {label}", color=color).classes(
                    "text-xs"
                ).style("padding: 6px 10px;")
                if idx < len(timeline_steps) - 1:
                    ui.icon("chevron_right", color="grey").classes("text-xs")

        # error/estop 态提示
        if st.state == "error":
            ui.label(
                f"状态机进入故障态，请在 Debug Tab 点击"
                f"「Reset {stage_name}」清除锁存。"
            ).classes("text-negative text-caption q-mt-sm")
        elif st.state == "estop":
            ui.label(
                "急停强制中止，请在 Recovery Tab 处理后解除急停。"
            ).classes("text-deep-orange text-caption q-mt-sm")


def _render_stage_cards(log_store: LogStore) -> None:
    """渲染所有已注册工位卡片。"""
    registry = StageStateRegistry(log_store)
    snapshot = registry.snapshot(list(_STAGE_STEP_MAP.keys()))
    for stage_name, (sub_steps, timeline_steps) in _STAGE_STEP_MAP.items():
        _render_stage_card(stage_name, snapshot[stage_name], sub_steps, timeline_steps)


def _parse_stage_events(entries) -> dict:
    """从 LogEntry 列表解析阶段/步骤事件，返回结构化数据。

    Returns:
        {stage_name: {"status": "OK"/"ERROR"/"running",
                      "steps": [{"action_id", "label", "status", "duration_ms"}]}}
    """
    stages: dict = {}

    for e in entries:
        if e.event == fe.STAGE_START:
            stage_name = _extract_kv(e.detail, "stage")
            if stage_name and stage_name not in stages:
                stages[stage_name] = {"status": "running", "steps": []}

        elif e.event == fe.STAGE_DONE:
            stage_name = _extract_kv(e.detail, "stage")
            status = _extract_kv(e.detail, "status") or "OK"
            if stage_name and stage_name in stages:
                stages[stage_name]["status"] = status

        elif e.event == fe.STEP_START:
            stage_name = _extract_kv(e.detail, "stage")
            action_id = _extract_kv(e.detail, "action_id")
            label = _extract_kv(e.detail, "label") or str(action_id)
            if stage_name and stage_name in stages:
                stages[stage_name]["steps"].append({
                    "action_id": action_id,
                    "label": label,
                    "status": "running",
                    "duration_ms": None,
                })

        elif e.event == fe.STEP_DONE:
            stage_name = _extract_kv(e.detail, "stage")
            action_id = _extract_kv(e.detail, "action_id")
            duration = _extract_kv(e.detail, "duration_ms")
            if stage_name and stage_name in stages:
                # 找到最后一个匹配的 running 步骤
                for step in reversed(stages[stage_name]["steps"]):
                    if step["action_id"] == action_id and step["status"] == "running":
                        step["status"] = "OK"
                        step["duration_ms"] = duration
                        break

        elif e.event == fe.STEP_SKIPPED:
            stage_name = _extract_kv(e.detail, "stage")
            action_id = _extract_kv(e.detail, "action_id")
            label = _extract_kv(e.detail, "label") or str(action_id)
            if stage_name and stage_name in stages:
                stages[stage_name]["steps"].append({
                    "action_id": action_id,
                    "label": label,
                    "status": "skipped",
                    "duration_ms": None,
                })

    return stages


# ══════════════════════════════════════════════════════════════════════
# 系统总览 Dashboard
# ══════════════════════════════════════════════════════════════════════

# 物理工位序列（before_photo 与 scrape 合并为“拍照刮板”工位）
_PHYSICAL_STATIONS = [
    ("spotting",  "上样点样",   "colorize"),
    ("develop",   "展开",       "science"),
    ("scrape",    "拍照刮板",   "photo_camera"),
    ("collect",   "收集",       "filter_alt"),
]

# 展缸状态色块映射
_TANK_STATUS_STYLE = {
    TankStatus.IDLE:        ("#e5e7eb", "#374151", "空闲"),
    TankStatus.PREPPING:    ("#fef08a", "#854d0e", "准备中"),
    TankStatus.DEVELOPING:  ("#93c5fd", "#1e3a5f", "展开中"),
    TankStatus.DRAINING:    ("#67e8f9", "#164e63", "排液中"),
    TankStatus.BLOW_AIR:    ("#a5f3fc", "#155e75", "吹气中"),
    TankStatus.CYLINDER:    ("#c4b5fd", "#4c1d95", "气缸退回"),
    TankStatus.ROBOT_PICKUP:("#fcd34d", "#78350f", "机器人取板"),
    TankStatus.ERROR:       ("#fca5a5", "#991b1b", "故障"),
    TankStatus.NEEDS_DRAIN: ("#fdba74", "#9a3412", "待排液"),
    TankStatus.DONE:        ("#86efac", "#166534", "完成"),
}

# 工位占用状态边框色
_STATION_BORDER = {
    "idle":    "#d1d5db",
    "running": "#3b82f6",
    "done":    "#10b981",
    "error":   "#ef4444",
    "estop":   "#ea580c",
}


def _derive_waiting_for_station(state) -> dict[str, list[str]]:
    """  推导每个物理工位的排队等待样品列表。

    逻辑：对所有 raw_status=="RUNNING" 的样品，查 LogStore 事件流：
    - 最后事件是 STAGE_START → 该样品正在执行该工位（非“等待”）
    - 最后事件是 STAGE_DONE → 正在等下一个工位的锁
    - 无任何 STAGE_START → 等第一个工位 (spotting)

    before_photo 与 scrape 共享物理工位，合并为 "scrape" 键。

    Returns:
        {"spotting": ["S002"], "develop": [], "scrape": ["S004"], "collect": []}
    """
    # before_photo 等待者合并到 scrape（共享物理工位）
    _NEXT_STATION = {
        "spotting":      "scrape",     # before_photo 共享 scrape 工位
        "before_photo":  "develop",
        "develop":       "scrape",
        "scrape":        "collect",
    }

    result: dict[str, list[str]] = {s[0]: [] for s in _PHYSICAL_STATIONS}

    for sid, raw_status in state.sample_statuses.items():
        if raw_status != "RUNNING":
            continue

        # 扫描样品事件流：找最后一条阶段事件
        last_stage_event = None   # (event_type, stage_name)
        for entry in reversed(state.log_store.get_sample(sid)):
            if entry.event == fe.STAGE_DONE:
                stage = _extract_kv(entry.detail, "stage")
                if stage:
                    last_stage_event = ("DONE", stage)
                    break
            if entry.event == fe.STAGE_START:
                stage = _extract_kv(entry.detail, "stage")
                if stage:
                    last_stage_event = ("START", stage)
                    break

        if last_stage_event is None:
            # worker 已接管但尚未启动任何工位 → 等 spotting
            result["spotting"].append(sid)
        elif last_stage_event[0] == "START":
            # 正在执行中，不是“等待” → 跳过
            pass
        else:
            # STAGE_DONE → 等下一个工位
            done_stage = last_stage_event[1]
            next_station = _NEXT_STATION.get(done_stage)
            if next_station and next_station in result:
                result[next_station].append(sid)

    return result


def _render_station_card(
    display_name: str,
    icon_name: str,
    stage_state,
    waiting_samples: list[str],
) -> None:
    """  渲染单工位卡片（spotting / scrape / collect）。

    - 占用中：高亮边框 + 样品 ID 加粗
    - 空闲：灰色边框
    - 排队样品：折叠列表
    """
    occupied = stage_state.state == "running"
    border = _STATION_BORDER.get(stage_state.state, "#d1d5db")
    sample_id = stage_state.sample_id if occupied else None

    with ui.card().classes("q-pa-md").style(
        f"border-left: 5px solid {border}; min-height: 140px;"
    ):
        # 标题行
        with ui.row().classes("items-center gap-2"):
            ui.icon(icon_name, size="sm", color="primary" if occupied else "grey")
            ui.label(display_name).classes("text-subtitle1 text-weight-bold")
            if occupied:
                ui.badge("RUN", color="blue").classes("text-xs")
            elif stage_state.state == "error":
                ui.badge("ERR", color="red").classes("text-xs")
            elif stage_state.state == "estop":
                ui.badge("ESTOP", color="deep-orange").classes("text-xs")

        # 占用样品
        if sample_id:
            with ui.row().classes("items-center gap-2 q-mt-xs"):
                ui.icon("person", size="xs", color="blue")
                ui.label(sample_id).classes(
                    "text-body1 text-weight-bold text-primary font-mono"
                )
        else:
            ui.label("空闲").classes("text-body2 text-grey q-mt-xs")

        # 排队样品（折叠）
        if waiting_samples:
            with ui.expansion(
                f"排队 ({len(waiting_samples)})",
                icon="queue",
            ).classes("w-full q-mt-xs").props("dense"):
                for ws in waiting_samples:
                    ui.label(ws).classes("text-caption text-grey font-mono")


def _render_develop_station(
    state,
    stage_state,
    waiting_samples: list[str],
) -> None:
    """  渲染展开工位卡片：2组 x 4 缸网格 + 排队折叠。"""
    rm = getattr(state, "resource_manager", None)
    border = _STATION_BORDER.get(stage_state.state, "#d1d5db")

    with ui.card().classes("q-pa-md").style(
        f"border-left: 5px solid {border}; min-height: 140px;"
    ):
        with ui.row().classes("items-center gap-2"):
            ui.icon("science", size="sm", color="primary" if stage_state.state == "running" else "grey")
            ui.label("展开工位").classes("text-subtitle1 text-weight-bold")
            if stage_state.state == "running":
                ui.badge("RUN", color="blue").classes("text-xs")

        if rm is None:
            ui.label("ResourceManager 未连接").classes("text-grey text-caption q-mt-sm")
            return

        tank_info = rm.all_tank_info()

        # 两组渲染
        for group_id, tank_range in [(1, range(1, 5)), (2, range(5, 9))]:
            ui.label(f"Group {group_id}").classes("text-caption text-grey q-mt-sm")
            with ui.row().classes("gap-2 flex-wrap"):
                for tid in tank_range:
                    info = tank_info[tid]
                    # handoff_pending 优先：PLC 侧 Tank_State=99（排液 FSM 已完成 + 机器人已取板），
                    # 但展缸资源还绑定样品等 RecipeTask 在 _scrape_lock 内 release。
                    # PLC 视角是 "完成"，样品视角是 "等待接管" —— UI 采后者避免与 IDLE 混淆。
                    if info.handoff_pending:
                        bg, fg, label = ("#bbf7d0", "#14532d", "等待接管")
                    else:
                        bg, fg, label = _TANK_STATUS_STYLE.get(
                            info.state, ("#e5e7eb", "#374151", "?")
                        )

                    # 缸格子
                    with ui.element("div").style(
                        f"background: {bg}; color: {fg}; "
                        f"border-radius: 8px; padding: 8px 12px; "
                        f"min-width: 90px; text-align: center; "
                        f"border: 2px solid {'#3b82f6' if info.state == TankStatus.DEVELOPING else 'transparent'};"
                    ):
                        ui.label(f"T{tid}").classes("text-caption text-weight-bold")
                        ui.label(label).classes("text-xs")
                        if info.sample_id:
                            ui.label(info.sample_id).classes(
                                "text-xs font-mono text-weight-medium"
                            )
                        # 悬停 tooltip
                        ui.tooltip(
                            f"Tank {tid} | {info.state.name}\n"
                            f"样品: {info.sample_id or '—'}"
                        )

        # 排队样品
        if waiting_samples:
            with ui.expansion(
                f"等待分配展缸 ({len(waiting_samples)})",
                icon="queue",
            ).classes("w-full q-mt-xs").props("dense"):
                for ws in waiting_samples:
                    ui.label(ws).classes("text-caption text-grey font-mono")


def _render_dashboard(state) -> None:
    """  渲染系统总览：4 大物理工位并发占用状态 + 8 缸网格。"""
    # 1. 工位状态快照
    registry = StageStateRegistry(state.log_store)
    all_stages = ["spotting", "before_photo", "develop", "scrape", "collect"]
    snapshot = registry.snapshot(all_stages)

    # 2. 排队推导
    waiting = _derive_waiting_for_station(state)

    # 3. 合并 before_photo + scrape 状态（取 running 优先）
    bp = snapshot["before_photo"]
    sc = snapshot["scrape"]
    if bp.state == "running":
        merged_scrape = bp  # before_photo 正在用工位
    else:
        merged_scrape = sc
    # before_photo 的等待者也合并到 scrape
    scrape_waiting = waiting.get("scrape", [])

    # 4. 统计概览
    active_count = sum(
        1 for s in state.sample_statuses.values() if s == "RUNNING"
    )
    pending_count = sum(
        1 for s in state.sample_statuses.values() if s == "PENDING"
    )

    with ui.card().classes("w-full q-pa-sm q-mb-md").style(
        "background: #f8fafc;"
    ):
        with ui.row().classes("items-center gap-4"):
            ui.icon("dashboard", size="sm")
            ui.label("pTLC 工作站总览").classes("text-subtitle1 text-weight-bold")
            if active_count:
                ui.badge(f"{active_count} 样品执行中", color="blue").classes("text-xs")
            if pending_count:
                ui.badge(f"{pending_count} 待执行", color="grey-6").classes("text-xs")

    # 5. 2x2 网格布局
    with ui.grid(columns=2).classes("w-full gap-3"):
        # 左上：上样点样
        _render_station_card(
            "上样点样", "colorize",
            snapshot["spotting"],
            waiting.get("spotting", []),
        )
        # 右上：展开（8 缸）
        _render_develop_station(
            state,
            snapshot["develop"],
            waiting.get("develop", []),
        )
        # 左下：拍照刮板
        _render_station_card(
            "拍照刮板", "photo_camera",
            merged_scrape,
            scrape_waiting,
        )
        # 右下：收集
        _render_station_card(
            "收集", "filter_alt",
            snapshot["collect"],
            waiting.get("collect", []),
        )
