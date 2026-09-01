"""样品对比 Dialog（Phase 2）— 全屏 2x2 网格并排查看 2-4 个样品的图像。

调用方式（在 history.py 内）:
    from ui.sections import compare
    asyncio.create_task(compare.open_compare_dialog(sample_ids))

设计原则:
  - 每次调用新建 Dialog，避免数据残留与竞态（数量小，开销可忽略）
  - 仅渲染图像（标注图 / Before / After 三图 Tab），不并排 G-code / bands 表
  - "全部切到标注图" 按钮同步所有单元格 Tab，便于横向对比
  - DB 未启用 / 样品缺失走降级文字占位，不抛异常
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from nicegui import ui

from ui.state import get_state

log = logging.getLogger(__name__)

# UI-Upper 根目录（与 history.py / core/database.py 中 _PROJECT_ROOT 对齐）
_UI_UPPER_ROOT = Path(__file__).resolve().parents[2]


# ──────────────────────────────────────────────────────────────────────
# 路径与字段格式化（轻量复制自 history.py，避免 sibling 模块循环依赖）
# ──────────────────────────────────────────────────────────────────────

def _resolve_path(rel_or_abs: Optional[str]) -> Optional[Path]:
    """将 DB 中的相对 posix 路径解析为绝对路径。"""
    if not rel_or_abs:
        return None
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = _UI_UPPER_ROOT / p
    return p


def _format_recipe_name(name: Optional[str]) -> str:
    if name and str(name).strip():
        return str(name).strip()
    return "未知配方"


def _render_image_or_placeholder(
    path: Optional[Path], placeholder_text: str
) -> None:
    if path and path.is_file():
        ui.image(str(path.resolve())).classes("max-h-[360px] w-full object-contain")
    else:
        ui.label(placeholder_text).classes("text-grey")


async def _query_annotated_path(db: Any, sample_id: str) -> Optional[Path]:
    """从 analyses 表读取 annotated_image_path（与 history.py 同语义）。"""
    try:
        cursor = await db._conn.execute(
            "SELECT annotated_image_path FROM analyses WHERE sample_id = ?",
            (sample_id,),
        )
        row = await cursor.fetchone()
        if row and row[0]:
            return _resolve_path(row[0])
    except Exception as e:
        log.debug("[compare] 查询 annotated_image_path 失败 (%s): %s",
                  sample_id, e)
    return None


# ──────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────

async def _load_cell_data(db: Any, sample_id: str) -> dict:
    """加载单个样品的对比所需字段。失败/缺失时返回 missing=True。"""
    try:
        sample = await db.get_sample(sample_id)
    except Exception as e:
        log.warning("[compare] get_sample 失败 (%s): %s", sample_id, e)
        sample = None
    if sample is None:
        return {"sample_id": sample_id, "missing": True}

    meta: dict = {}
    try:
        meta = json.loads(sample.get("metadata_json") or "{}")
    except Exception:
        meta = {}

    annotated = await _query_annotated_path(db, sample_id)
    return {
        "sample_id": sample_id,
        "missing": False,
        "recipe_name": _format_recipe_name(meta.get("recipe_name")),
        "completed_at": (
            sample.get("updated_at")
            or sample.get("created_at")
            or "-"
        ),
        "before": _resolve_path(sample.get("before_image_path")),
        "after": _resolve_path(sample.get("after_image_path")),
        "annotated": annotated,
    }


# ──────────────────────────────────────────────────────────────────────
# 渲染
# ──────────────────────────────────────────────────────────────────────

def _render_cell(cell: dict, tabs_list: list) -> None:
    """渲染单个对比单元格（卡片：标题 + 元信息 + 三图 Tab）。"""
    sid = cell["sample_id"]
    with ui.card().classes("w-full"):
        if cell.get("missing"):
            ui.label(sid).classes("text-subtitle1 text-bold")
            ui.label("样品不在数据库中").classes("text-grey")
            return

        ui.label(
            f"{sid}  ·  {cell['recipe_name']}"
        ).classes("text-subtitle1 text-bold")
        ui.label(f"完成: {cell['completed_at']}").classes(
            "text-caption text-grey"
        )

        with ui.tabs().classes("w-full") as tabs:
            tab_anno = ui.tab("标注图")
            tab_before = ui.tab("Before")
            tab_after = ui.tab("After")
        # 记录 tabs 与 annotated tab 引用，供"全部切换"使用
        tabs_list.append((tabs, tab_anno))

        with ui.tab_panels(tabs, value=tab_anno).classes("w-full"):
            with ui.tab_panel(tab_anno):
                _render_image_or_placeholder(
                    cell["annotated"], "标注图缺失"
                )
            with ui.tab_panel(tab_before):
                _render_image_or_placeholder(
                    cell["before"], "Before 图像缺失"
                )
            with ui.tab_panel(tab_after):
                _render_image_or_placeholder(
                    cell["after"], "After 图像缺失"
                )


def _switch_all_to_annotated(tabs_list: list) -> None:
    """将所有单元格 Tab 切换到标注图。"""
    for tabs_widget, anno_tab in tabs_list:
        try:
            tabs_widget.set_value(anno_tab)
        except Exception as e:
            log.debug("[compare] 切换 annotated 失败: %s", e)


# ──────────────────────────────────────────────────────────────────────
# 公共入口
# ──────────────────────────────────────────────────────────────────────

async def open_compare_dialog(sample_ids: list[str]) -> None:
    """打开样品对比 Dialog（异步：先加载 DB 数据再渲染）。

    上限 4 个样品；2x2 网格；DB 未启用或样品全部缺失时降级。
    """
    state = get_state()
    if not (2 <= len(sample_ids) <= 4):
        ui.notify("请选择 2-4 个样品", type="warning")
        return

    db = state.database
    if db is None or not getattr(db, "connected", False):
        ui.notify("数据库未启用", type="warning")
        return

    # 1) 数据加载（顺序串行 — 数量 ≤ 4，无需并发）
    cells: list[dict] = []
    for sid in sample_ids:
        cells.append(await _load_cell_data(db, sid))

    # 2) 构建 Dialog
    dlg = ui.dialog().props("maximized")
    tabs_list: list[tuple[Any, Any]] = []  # [(tabs_widget, annotated_tab)]

    with dlg:
        with ui.card().classes("w-full h-full no-wrap"):
            with ui.row().classes("items-center justify-between w-full no-wrap"):
                ui.label(f"样品对比（{len(cells)}）").classes("text-h6")
                with ui.row().classes("items-center gap-2 no-wrap"):
                    with ui.button(
                        on_click=lambda: _switch_all_to_annotated(tabs_list),
                    ).props("flat dense color=primary"):
                        ui.icon("dashboard").classes("q-mr-xs")
                        ui.label("全部切到标注图")
                    with ui.button(on_click=dlg.close).props("flat dense"):
                        ui.icon("close").classes("q-mr-xs")
                        ui.label("关闭")
            ui.separator()

            with ui.grid(columns=2).classes("w-full gap-4"):
                for cell in cells:
                    _render_cell(cell, tabs_list)

    dlg.open()
