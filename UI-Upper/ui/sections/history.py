"""历史样品 Tab - 浏览 DB 中已完成的样品并触发对比。

UI 结构：
  - 顶部筛选条：配方下拉 / 起止日期 / sample_id 子串搜索
  - 中部样品表格（多选，2-4 个启用对比按钮）
  - 底部操作栏：[对比选中样品]（Phase 2 实现 Dialog）
  - 右侧详情面板：单选时显示 before/after/annotated 三图 + bands 表

设计原则：
  - 数据加载为按需触发（"应用筛选" / "刷新" 按钮 + 首次进入），不订阅 timer
  - DB 未启用时降级为提示文本，不崩溃
  - DB 中路径为相对 UI-Upper 的 posix 字符串，UI 拼接为绝对路径
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from nicegui import ui

from core import log_query
from ui.state import get_state

log = logging.getLogger(__name__)

# UI-Upper 根目录（与 core/database.py 中 _PROJECT_ROOT 对齐）
_UI_UPPER_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SAMPLES_ROOT = _UI_UPPER_ROOT / "data" / "samples"


def _resolve_path(rel_or_abs: Optional[str]) -> Optional[Path]:
    """将 DB 中的相对 posix 路径解析为绝对路径。"""
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = _UI_UPPER_ROOT / p
    return p


def _format_recipe_name(name: Optional[str]) -> str:
    """空/None 显示为'未知配方'。"""
    if name and str(name).strip():
        return str(name).strip()
    return "未知配方"


def render() -> dict:
    """渲染历史样品 Tab。返回 refs 字典（当前不参与周期 timer 刷新）。"""
    refs: dict[str, Any] = {}

    with ui.row().classes("w-full gap-4 items-start no-wrap h-[calc(100vh-200px)]"):
        # ── 左列：筛选 + 表格 + 操作栏 ──
        with ui.column().classes("flex-1 gap-3 h-full overflow-y-auto"):
            # 筛选条
            with ui.card().classes("w-full"):
                ui.label("筛选").classes("text-subtitle1")
                with ui.row().classes("w-full items-end gap-2 flex-wrap"):
                    recipe_select = ui.select(
                        options=["全部"],
                        value="全部",
                        label="配方",
                    ).classes("min-w-[160px]")
                    refs["recipe_select"] = recipe_select

                    date_from = ui.input(
                        label="起始日期", placeholder="YYYY-MM-DD"
                    ).classes("min-w-[120px]")
                    with date_from:
                        with ui.menu().props("no-parent-event") as menu_from:
                            with ui.date().bind_value(date_from):
                                with ui.row().classes("justify-end"):
                                    ui.button("关闭", on_click=menu_from.close).props("flat")
                        with date_from.add_slot("append"):
                            ui.icon("edit_calendar").on(
                                "click", menu_from.open
                            ).classes("cursor-pointer")
                    refs["date_from"] = date_from

                    date_to = ui.input(
                        label="终止日期", placeholder="YYYY-MM-DD"
                    ).classes("min-w-[120px]")
                    with date_to:
                        with ui.menu().props("no-parent-event") as menu_to:
                            with ui.date().bind_value(date_to):
                                with ui.row().classes("justify-end"):
                                    ui.button("关闭", on_click=menu_to.close).props("flat")
                        with date_to.add_slot("append"):
                            ui.icon("edit_calendar").on(
                                "click", menu_to.open
                            ).classes("cursor-pointer")
                    refs["date_to"] = date_to

                    id_search = ui.input(
                        label="sample_id 子串", placeholder="子串匹配"
                    ).classes("min-w-[160px]")
                    refs["id_search"] = id_search

                    ui.button(
                        "应用筛选",
                        on_click=lambda: _on_apply_filter(refs),
                    ).props("color=primary")
                    ui.button(
                        "重置",
                        on_click=lambda: _on_reset_filter(refs),
                    ).props("flat")
                    ui.button(
                        "刷新",
                        on_click=lambda: asyncio.create_task(
                            _refresh_data(refs)
                        ),
                    ).props("flat icon=refresh")

                # Phase 5B: 显示已删除复选框
                with ui.row().classes("w-full items-center"):
                    include_deleted_cb = ui.checkbox(
                        "显示已删除",
                        value=False,
                        on_change=lambda e: _on_include_deleted_change(refs, e.value),
                    ).classes("text-caption")
                    refs["include_deleted_cb"] = include_deleted_cb

            # 样品表格
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center w-full"):
                    ui.label("样品列表").classes("text-subtitle1")
                    ui.space()
                    count_label = ui.label("加载中…").classes(
                        "text-caption text-grey"
                    )
                    refs["count_label"] = count_label

                columns = [
                    {"name": "sample_id", "label": "样品ID",
                     "field": "sample_id", "align": "left", "sortable": True},
                    {"name": "recipe_name", "label": "配方",
                     "field": "recipe_name", "align": "left", "sortable": True},
                    {"name": "created_at", "label": "创建时间",
                     "field": "created_at", "align": "left", "sortable": True},
                    {"name": "band_count", "label": "Band数",
                     "field": "band_count", "align": "right", "sortable": True},
                    {"name": "selected_bands_str", "label": "选中Band",
                     "field": "selected_bands_str", "align": "left"},
                ]
                table = ui.table(
                    columns=columns,
                    rows=[],
                    row_key="sample_id",
                    selection="multiple",
                    pagination={
                        "rowsPerPage": 20,
                        "sortBy": "created_at",
                        "descending": True,
                    },
                    on_select=lambda e: _on_selection_change(refs, e),
                ).classes("w-full")
                refs["table"] = table

            # 操作栏
            with ui.row().classes("items-center gap-3"):
                # 注：on_click 必须传 async 函数引用才能被 NiceGUI
                # 自动调度并保留 client/slot context；若传 sync lambda
                # 包一层，返回的 coroutine 对象会被静默丢弃，导致点击无响应。
                async def _on_compare_click() -> None:
                    await _on_compare(refs)

                compare_btn = ui.button(
                    "对比选中样品",
                    on_click=_on_compare_click,
                ).props("color=primary")
                compare_btn.set_enabled(False)
                refs["compare_btn"] = compare_btn

                compare_hint = ui.label("已选 0 个（请选 2-4 个）").classes(
                    "text-caption text-grey"
                )
                refs["compare_hint"] = compare_hint

        # ── 右列：详情面板 ──
        with ui.column().classes("flex-1 gap-3 h-full overflow-y-auto"):
            with ui.card().classes("w-full"):
                ui.label("详情").classes("text-subtitle1")
                detail_placeholder = ui.label(
                    "选中单个样品查看详情"
                ).classes("text-grey")
                refs["detail_placeholder"] = detail_placeholder
                detail_container = ui.column().classes("w-full gap-2")
                refs["detail_container"] = detail_container

    # 首次进入时加载（DB 在后台 task 中启动，需延迟）
    async def _initial_load() -> None:
        await _populate_recipe_options(refs)
        await _refresh_data(refs)

    ui.timer(
        0.5,
        lambda: asyncio.create_task(_initial_load()),
        once=True,
    )

    return refs


# ──────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────

async def _populate_recipe_options(refs: dict) -> None:
    """加载 recipe 下拉选项。"""
    state = get_state()
    sel = refs.get("recipe_select")
    if sel is None:
        return
    options = ["全部"]
    db = state.database
    if db is not None and getattr(db, "connected", False):
        try:
            recipes = await db.list_recipes_used()
            options.extend(recipes)
        except Exception as e:
            log.warning("[history] list_recipes_used 失败: %s", e)
    sel.options = options
    if sel.value not in options:
        sel.value = "全部"
    sel.update()


async def _refresh_data(refs: dict) -> None:
    """根据 state.history_filter 重新加载样品列表。"""
    state = get_state()
    table = refs.get("table")
    count_label = refs.get("count_label")
    if table is None:
        return

    db = state.database
    if db is None or not getattr(db, "connected", False):
        table.rows = []
        table.selected = []
        table.update()
        if count_label:
            count_label.text = "数据库未启用"
        state.history_selected_ids = set()
        _update_compare_btn(refs)
        _clear_detail(refs)
        return

    try:
        samples = await db.list_samples(
            filter=state.history_filter or {},
            include_deleted=state.history_include_deleted,
        )
    except Exception as e:
        log.warning("[history] list_samples 失败: %s", e)
        samples = []

    rows: list[dict] = []
    for s in samples:
        sid = s["sample_id"]
        meta: dict = {}
        try:
            meta = json.loads(s.get("metadata_json") or "{}")
        except Exception:
            meta = {}
        try:
            bands = await db.get_bands(sid)
        except Exception:
            bands = []
        try:
            selected = await db.get_selected_bands(sid)
        except Exception:
            selected = []
        is_deleted = bool(s.get("deleted_at"))
        rows.append({
            "sample_id": sid,
            "recipe_name": _format_recipe_name(meta.get("recipe_name")),
            "created_at": s.get("created_at") or "-",
            "band_count": len(bands),
            "selected_bands_str": ",".join(selected) if selected else "-",
            "_deleted": is_deleted,
        })

    table.rows = rows
    table.selected = []
    table.update()
    state.history_selected_ids = set()
    _update_compare_btn(refs)
    _clear_detail(refs)
    if count_label:
        del_count = sum(1 for r in rows if r.get("_deleted"))
        suffix = f"（含 {del_count} 条已删除）" if del_count else ""
        count_label.text = f"共 {len(rows)} 条记录{suffix}"


# ──────────────────────────────────────────────────────────────────────
# 筛选 / 重置 / 选择
# ──────────────────────────────────────────────────────────────────────

def _on_apply_filter(refs: dict) -> None:
    state = get_state()
    f: dict = {}
    rs = refs.get("recipe_select")
    if rs and rs.value and rs.value != "全部":
        f["recipe_name"] = rs.value
    df = (refs.get("date_from").value or "").strip() if refs.get("date_from") else ""
    if df:
        f["date_from"] = df
    dt = (refs.get("date_to").value or "").strip() if refs.get("date_to") else ""
    if dt:
        # 包含当天：拼成 'YYYY-MM-DDT23:59:59'
        f["date_to"] = dt + "T23:59:59"
    sub = (refs.get("id_search").value or "").strip() if refs.get("id_search") else ""
    if sub:
        f["id_substring"] = sub
    state.history_filter = f
    asyncio.create_task(_refresh_data(refs))


def _on_reset_filter(refs: dict) -> None:
    state = get_state()
    sel = refs.get("recipe_select")
    if sel:
        sel.value = "全部"
        sel.update()
    for key in ("date_from", "date_to", "id_search"):
        ctrl = refs.get(key)
        if ctrl is not None:
            ctrl.value = ""
            ctrl.update()
    state.history_filter = {}
    asyncio.create_task(_refresh_data(refs))


def _on_include_deleted_change(refs: dict, value: bool) -> None:
    """显示已删除复选框变化。"""
    state = get_state()
    state.history_include_deleted = value
    asyncio.create_task(_refresh_data(refs))


# ──────────────────────────────────────────────────────────────────────
# Phase 5B/5C: 软删 / 还原 / 硬删 处理函数
# ──────────────────────────────────────────────────────────────────────

async def _on_soft_delete(refs: dict, sample_id: str) -> None:
    """软删除样品（二次确认）。"""
    state = get_state()
    db = state.database
    if db is None or not getattr(db, "connected", False):
        ui.notify("数据库未启用", type="warning")
        return

    with ui.dialog() as dlg, ui.card():
        ui.label(f"确认软删样品 {sample_id}？").classes("text-h6")
        ui.label("软删后记录不会在默认列表中显示，但可通过‘显示已删除’复选框查看，并可还原。")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=lambda: dlg.submit(False)).props("flat")
            ui.button("确认删除", on_click=lambda: dlg.submit(True)).props("color=warning")

    result = await dlg
    if not result:
        return

    try:
        await db.soft_delete_sample(sample_id)
        ui.notify(f"已软删除 {sample_id}", type="positive")
    except Exception as e:
        ui.notify(f"软删失败: {e}", type="negative")
        return
    await _refresh_data(refs)


async def _on_restore(refs: dict, sample_id: str) -> None:
    """还原软删除样品。"""
    state = get_state()
    db = state.database
    if db is None or not getattr(db, "connected", False):
        ui.notify("数据库未启用", type="warning")
        return
    try:
        await db.restore_sample(sample_id)
        ui.notify(f"已还原 {sample_id}", type="positive")
    except Exception as e:
        ui.notify(f"还原失败: {e}", type="negative")
        return
    await _refresh_data(refs)


async def _on_hard_delete(refs: dict, sample_id: str) -> None:
    """硬删除样品（二步确认 Dialog）。仅对已软删样品可触发。"""
    state = get_state()
    db = state.database
    if db is None or not getattr(db, "connected", False):
        ui.notify("数据库未启用", type="warning")
        return

    # 获取样品目录信息
    sample_dir: Optional[Path] = None
    if getattr(state, "sample_store", None) is not None:
        sample_dir = state.sample_store.get_sample_dir(sample_id)
    else:
        sample_dir = _DEFAULT_SAMPLES_ROOT / sample_id

    dir_exists = sample_dir.is_dir() if sample_dir else False
    dir_size_str = "目录不存在"
    if dir_exists:
        try:
            total_bytes = sum(
                f.stat().st_size for f in sample_dir.rglob("*") if f.is_file()
            )
            if total_bytes < 1024:
                dir_size_str = f"{total_bytes} B"
            elif total_bytes < 1024 * 1024:
                dir_size_str = f"{total_bytes / 1024:.1f} KB"
            else:
                dir_size_str = f"{total_bytes / (1024*1024):.1f} MB"
        except Exception:
            dir_size_str = "无法计算"

    try:
        disk_info = await db.get_sample_disk_info(sample_id)
    except Exception:
        disk_info = {"db_records": "?"}

    # 第一步：预览将删除的内容
    with ui.dialog() as dlg1, ui.card().classes("min-w-[400px]"):
        ui.label("⚠️ 彻底删除（不可恢复）").classes("text-h6 text-negative")
        ui.label(f"样品: {sample_id}").classes("text-bold")
        ui.separator()
        ui.label("将永久删除以下内容：").classes("text-subtitle2")
        ui.label(f"  • DB 子表记录: {disk_info.get('db_records', '?')} 条")
        ui.label(
            f"  • 文件目录: {sample_dir}  ({dir_size_str})"
            if dir_exists
            else f"  • 文件目录: {sample_dir}  (不存在，仅删 DB)"
        )
        ui.separator()
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=lambda: dlg1.submit(False)).props("flat")
            ui.button("下一步", on_click=lambda: dlg1.submit(True)).props("color=negative")

    step1 = await dlg1
    if not step1:
        return

    # 第二步：输入 sample_id 确认
    with ui.dialog() as dlg2, ui.card().classes("min-w-[400px]"):
        ui.label("最终确认").classes("text-h6 text-negative")
        ui.label(f"请输入样品 ID “{sample_id}” 以确认彻底删除：")
        confirm_input = ui.input(
            label="确认样品 ID", placeholder=sample_id
        ).classes("w-full")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("取消", on_click=lambda: dlg2.submit(None)).props("flat")
            ui.button(
                "确认彻底删除",
                on_click=lambda: dlg2.submit(confirm_input.value),
            ).props("color=negative")

    confirm_value = await dlg2
    if confirm_value is None or str(confirm_value).strip() != sample_id:
        ui.notify("已取消（输入不匹配）", type="info")
        return

    # 执行删除：先 DB 后文件系统
    try:
        await db.hard_delete_sample(sample_id)
    except Exception as e:
        ui.notify(f"DB 删除失败: {e}", type="negative")
        return

    if dir_exists and sample_dir is not None:
        try:
            await asyncio.to_thread(shutil.rmtree, sample_dir)
        except Exception as e:
            ui.notify(
                f"DB 已删，但文件目录删除失败: {e}\n请手动删除: {sample_dir}",
                type="negative", close_button="知道了",
            )
            await _refresh_data(refs)
            return

    ui.notify(f"已彻底删除 {sample_id}", type="positive")
    await _refresh_data(refs)


def _on_selection_change(refs: dict, e: Any) -> None:
    """表格选中行变化：更新对比按钮 + 单选时显示详情。"""
    state = get_state()
    sel_rows = getattr(e, "selection", None)
    if sel_rows is None:
        # 兜底：从 table.selected 取
        table = refs.get("table")
        sel_rows = list(getattr(table, "selected", []) or [])
    state.history_selected_ids = {
        r.get("sample_id") for r in sel_rows if isinstance(r, dict)
    }
    _update_compare_btn(refs)
    if len(sel_rows) == 1 and isinstance(sel_rows[0], dict):
        sid = sel_rows[0].get("sample_id")
        if sid:
            asyncio.create_task(_show_detail(refs, sid))
    else:
        _clear_detail(refs)


def _update_compare_btn(refs: dict) -> None:
    state = get_state()
    btn = refs.get("compare_btn")
    hint = refs.get("compare_hint")
    n = len(state.history_selected_ids)
    if btn:
        btn.set_enabled(2 <= n <= 4)
    if hint:
        if 2 <= n <= 4:
            hint.text = f"已选 {n} 个（已就绪）"
        else:
            hint.text = f"已选 {n} 个（请选 2-4 个）"


async def _on_compare(refs: dict) -> None:
    """对比按钮 — 打开全屏 2x2 对比 Dialog（Phase 2）。

    采用 async handler 以保留 NiceGUI client/slot context；
    若改用 asyncio.create_task 后台调度，ui.dialog() 会报
    RuntimeError: slot stack is empty 并被吞，表现为点击无响应。
    """
    state = get_state()
    ids = sorted(state.history_selected_ids)
    if not (2 <= len(ids) <= 4):
        ui.notify("请选择 2-4 个样品", type="warning")
        return
    state.history_compare_ids = list(ids)
    # 延迟 import 避免 sibling 模块循环依赖
    from ui.sections import compare
    await compare.open_compare_dialog(state.history_compare_ids)


# ──────────────────────────────────────────────────────────────────────
# 详情面板
# ──────────────────────────────────────────────────────────────────────

def _clear_detail(refs: dict) -> None:
    placeholder = refs.get("detail_placeholder")
    container = refs.get("detail_container")
    if placeholder is not None:
        placeholder.visible = True
    if container is not None:
        container.clear()


async def _show_detail(refs: dict, sample_id: str) -> None:
    state = get_state()
    placeholder = refs.get("detail_placeholder")
    container = refs.get("detail_container")
    if container is None:
        return
    container.clear()
    if placeholder is not None:
        placeholder.visible = False

    db = state.database
    if db is None or not getattr(db, "connected", False):
        with container:
            ui.label("数据库未启用").classes("text-grey")
        return

    try:
        sample = await db.get_sample(sample_id)
    except Exception as e:
        log.warning("[history] get_sample 失败 (%s): %s", sample_id, e)
        sample = None
    if sample is None:
        with container:
            ui.label(f"样品 {sample_id} 未在数据库中").classes("text-grey")
        return

    meta: dict = {}
    try:
        meta = json.loads(sample.get("metadata_json") or "{}")
    except Exception:
        meta = {}

    try:
        bands = await db.get_bands(sample_id)
    except Exception:
        bands = []
    try:
        gcodes = await db.get_gcode_files(sample_id)
    except Exception:
        gcodes = []
    # v2 主路径：优先读 scrape_arrays 表。为空 → 回退 gcode_files（存量样品）。
    try:
        scrape_arrays = await db.get_scrape_arrays(sample_id)
    except Exception:
        scrape_arrays = []
    try:
        selected_bands = await db.get_selected_bands(sample_id)
    except Exception:
        selected_bands = []

    before_path = _resolve_path(sample.get("before_image_path"))
    after_path = _resolve_path(sample.get("after_image_path"))
    annotated_path = await _query_annotated_path(db, sample_id)

    with container:
        # 标题
        ui.label(
            f"{sample_id}  ·  {_format_recipe_name(meta.get('recipe_name'))}"
        ).classes("text-h6")
        ui.label(
            f"创建: {sample.get('created_at') or '-'}    "
            f"更新: {sample.get('updated_at') or '-'}"
        ).classes("text-caption text-grey")

        # 三图 Tab
        with ui.tabs().classes("w-full") as detail_tabs:
            tab_anno = ui.tab("标注图")
            tab_before = ui.tab("Before")
            tab_after = ui.tab("After")
        with ui.tab_panels(detail_tabs, value=tab_anno).classes("w-full"):
            with ui.tab_panel(tab_anno):
                _render_image_or_placeholder(annotated_path, "标注图缺失")
            with ui.tab_panel(tab_before):
                _render_image_or_placeholder(before_path, "Before 图像缺失")
            with ui.tab_panel(tab_after):
                _render_image_or_placeholder(after_path, "After 图像缺失")

        # G-code / ScrapeArrays 路径预览
        # v2 主路径：优先展示 scrape_arrays 表中的第一条（含 PNG，含参数总结）；
        # 仅在 scrape_arrays 为空（存量样品）时退到旧 gcode_files 展示。
        if scrape_arrays:
            sa = scrape_arrays[0]
            ui.separator()
            ui.label("点位数组预览 (ScrapeArrays)").classes("text-subtitle2")
            with ui.row().classes("items-center gap-3"):
                ui.label(
                    f"strategy={sa.get('strategy') or '-'}    "
                    f"passes={sa.get('num_passes') or 0}    "
                    f"depth={sa.get('total_depth_mm') or 0:.2f}mm    "
                    f"points={sa.get('scrape_point_count') or 0}+"
                    f"{sa.get('collect_point_count') or 0}"
                ).classes("text-caption")
            png_path = _resolve_path(sa.get("png_path"))
            if png_path and png_path.is_file():
                ui.image(str(png_path.resolve())).classes(
                    "max-h-[280px] max-w-full object-contain"
                )
        else:
            selected_gcode = next(
                (g for g in gcodes if g.get("is_selected")), None
            )
            if selected_gcode:
                path_image = _resolve_path(selected_gcode.get("path_image"))
                if path_image and path_image.is_file():
                    ui.separator()
                    ui.label("G-code 路径预览（存量）").classes("text-subtitle2")
                    ui.image(str(path_image.resolve())).classes(
                        "max-h-[280px] max-w-full object-contain"
                    )

        # bands 表
        ui.separator()
        if bands:
            ui.label(f"Bands（{len(bands)}）").classes("text-subtitle2")
            sel_set = set(selected_bands)
            band_cols = [
                {"name": "band_id", "label": "ID",
                 "field": "band_id", "align": "left"},
                {"name": "is_origin", "label": "原点",
                 "field": "is_origin", "align": "center"},
                {"name": "distance", "label": "距原点(cm)",
                 "field": "distance", "align": "right"},
                {"name": "centroid", "label": "质心(px)",
                 "field": "centroid", "align": "left"},
                {"name": "selected", "label": "选中",
                 "field": "selected", "align": "center"},
            ]
            band_rows = []
            for b in bands:
                cx = b.get("centroid_x_px")
                cy = b.get("centroid_y_px")
                d = b.get("distance_to_origin_cm")
                band_rows.append({
                    "band_id": b.get("band_id"),
                    "is_origin": "是" if b.get("is_origin") else "",
                    "distance": f"{d:.2f}" if d is not None else "-",
                    "centroid": (
                        f"({cx:.0f}, {cy:.0f})"
                        if cx is not None and cy is not None
                        else "-"
                    ),
                    "selected": "✓" if b.get("band_id") in sel_set else "",
                })
            ui.table(
                columns=band_cols,
                rows=band_rows,
                row_key="band_id",
                pagination={"rowsPerPage": 10},
            ).classes("w-full")
        else:
            ui.label("无 band 数据").classes("text-grey")

        # ── 运行日志（Phase 3）──
        ui.separator()
        samples_root = (
            state.sample_store.root_dir
            if getattr(state, "sample_store", None) is not None
            else _DEFAULT_SAMPLES_ROOT
        )
        try:
            log_entries = await asyncio.to_thread(
                log_query.load_sample_logs, sample_id, samples_root
            )
        except Exception as e:
            log.warning("[history] load_sample_logs 失败 (%s): %s", sample_id, e)
            log_entries = []
        _render_log_section(sample_id, log_entries)

        # ── Phase 5B/5C: 操作区（软删 / 还原 / 硬删）──
        ui.separator()
        is_deleted = bool(sample.get("deleted_at"))
        with ui.row().classes("w-full items-center gap-2"):
            if not is_deleted:
                ui.button(
                    "从索引中删除",
                    on_click=lambda sid=sample_id: _on_soft_delete(refs, sid),
                ).props("color=warning flat icon=delete_outline")
            else:
                ui.label("☠ 已软删除").classes("text-negative text-bold")
                ui.button(
                    "还原",
                    on_click=lambda sid=sample_id: _on_restore(refs, sid),
                ).props("color=positive flat icon=restore")
                ui.button(
                    "彻底删除",
                    on_click=lambda sid=sample_id: _on_hard_delete(refs, sid),
                ).props("color=negative flat icon=delete_forever")


def _render_log_section(sample_id: str, entries: list) -> None:
    """渲染运行日志区：事件类型下拉 + 文本搜索 + 表格。

    奥卡姆：单样品同步过滤即可；不订阅 timer，不跨样品聚合。
    """
    ui.label(f"运行日志（{sample_id}）").classes("text-subtitle2")
    if not entries:
        ui.label(
            "无日志记录（样品未跑过或日志目录为空）"
        ).classes("text-grey")
        return

    total = len(entries)
    truncated = total >= log_query.MAX_ENTRIES_PER_SAMPLE
    unique_events = log_query.list_unique_events(entries)

    log_cols = [
        {"name": "ts", "label": "时间", "field": "ts",
         "align": "left", "sortable": True},
        {"name": "event", "label": "事件", "field": "event",
         "align": "left", "sortable": True},
        {"name": "detail", "label": "详情", "field": "detail",
         "align": "left"},
        {"name": "extra", "label": "extra", "field": "extra",
         "align": "left"},
    ]

    event_sel: dict = {}    # 闭包占位，赋值在创建后
    search_input: dict = {}
    log_table: dict = {}
    count_label: dict = {}

    def _apply_filter() -> None:
        ev = event_sel["w"].value or "全部"
        kw = search_input["w"].value or ""
        filtered = log_query.filter_logs(entries, ev, kw)
        log_table["w"].rows = _entries_to_rows(filtered)
        log_table["w"].update()
        suffix = (
            f"（已截断至上限 {log_query.MAX_ENTRIES_PER_SAMPLE}）"
            if truncated else ""
        )
        count_label["w"].text = (
            f"显示 {len(filtered)} / 共 {total} 条{suffix}"
        )

    def _reset_filter() -> None:
        event_sel["w"].value = "全部"
        search_input["w"].value = ""
        event_sel["w"].update()
        search_input["w"].update()
        _apply_filter()

    with ui.row().classes("w-full items-end gap-2 flex-wrap"):
        event_sel["w"] = ui.select(
            options=["全部"] + unique_events,
            value="全部",
            label="事件类型",
            on_change=lambda _: _apply_filter(),
        ).classes("min-w-[200px]")
        search_input["w"] = ui.input(
            label="搜索",
            placeholder="event/detail/extra 子串",
            on_change=lambda _: _apply_filter(),
        ).classes("min-w-[220px]")
        ui.button(
            "过滤", on_click=_apply_filter
        ).props("flat color=primary icon=filter_alt")
        ui.button(
            "重置", on_click=_reset_filter
        ).props("flat icon=clear")

    log_table["w"] = ui.table(
        columns=log_cols,
        rows=_entries_to_rows(entries),
        row_key="_idx",
        pagination={
            "rowsPerPage": 25,
            "sortBy": "ts",
            "descending": False,
        },
    ).classes("w-full")

    suffix = (
        f"（已截断至上限 {log_query.MAX_ENTRIES_PER_SAMPLE}）"
        if truncated else ""
    )
    count_label["w"] = ui.label(
        f"显示 {total} / 共 {total} 条{suffix}"
    ).classes("text-caption text-grey")


def _entries_to_rows(entries: list) -> list[dict]:
    """日志条目 → 表格行：附 _idx 作 row_key，extra 序列化为 JSON 字符串。"""
    rows: list[dict] = []
    for i, e in enumerate(entries):
        extra = e.get("extra") or {}
        if extra:
            try:
                extra_str = json.dumps(extra, ensure_ascii=False)
            except Exception:
                extra_str = str(extra)
        else:
            extra_str = ""
        rows.append({
            "_idx": i,
            "ts": str(e.get("ts", "")),
            "event": str(e.get("event", "")),
            "detail": str(e.get("detail", "")),
            "extra": extra_str,
        })
    return rows


def _render_image_or_placeholder(
    path: Optional[Path], placeholder_text: str
) -> None:
    """统一图像渲染：文件可读则 ui.image，否则文字占位。"""
    if path and path.is_file():
        ui.image(str(path.resolve())).classes(
            "max-h-[480px] max-w-full object-contain"
        )
    else:
        ui.label(placeholder_text).classes("text-grey")


async def _query_annotated_path(db: Any, sample_id: str) -> Optional[Path]:
    """从 analyses 表读取 annotated_image_path（DB 未提供专门接口，直接 SQL）。"""
    try:
        cursor = await db._conn.execute(
            "SELECT annotated_image_path FROM analyses WHERE sample_id = ?",
            (sample_id,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return _resolve_path(row[0])
    except Exception as e:
        log.debug("[history] 查询 annotated_image_path 失败 (%s): %s",
                  sample_id, e)
    return None
