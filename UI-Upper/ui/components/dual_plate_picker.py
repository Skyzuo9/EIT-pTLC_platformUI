"""双 24 孔板可视化选择器 - 上样工位（NiceGUI）。

硬件布局：
- 2 个 24 孔板并排放置（每板 4 列 × 6 行 = 24 孔）
- PLC 坐标：人的视角右上角 = (1, 1)，左下角 = (8, 6)
- 板 1 (Plate 1): PLC X = 1..4, Y = 1..6（人的视角右侧）
- 板 2 (Plate 2): PLC X = 5..8, Y = 1..6（人的视角左侧）

UI 渲染：
- 列顺序 X = 8 → 1（右→左），使屏幕布局与人的视角一致
- 板 2 显示在屏幕左侧，板 1 显示在屏幕右侧
- 每板内孔位编号 1..24（行优先）
- 就地 DOM 更新，不依赖 @ui.refreshable
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

# ── 硬件常量 ────────────────────────────────────────────────
_ROWS = 6           # 每板行数 (Y 轴 1..6 → A..F)
_COLS_PER_PLATE = 4  # 每板列数
_TOTAL_COLS = _COLS_PER_PLATE * 2   # 双板总列数 = 8
_ROW_LABELS = ["A", "B", "C", "D", "E", "F"]

# 屏幕列渲染顺序（index 0 = 最左列）：X=8,7,6,5,4,3,2,1
# 使 Plate 2（X 5..8）在屏幕左侧，Plate 1（X 1..4）在屏幕右侧
_SCREEN_COLS = list(range(_TOTAL_COLS, 0, -1))

# 板间隙左右各留的间隔宽度（Quasar gap 单位）
_PLATE_GAP_CLASS = "q-ml-md"


def _plate_of(x: int) -> int:
    """返回板号 (1 or 2)。"""
    return 1 if x <= _COLS_PER_PLATE else 2


def _local_xy(x: int, y: int) -> tuple[int, int]:
    """PLC 坐标 → 板内局部坐标 (local_col 1..4, row 1..6)。"""
    local_col = x if x <= _COLS_PER_PLATE else x - _COLS_PER_PLATE
    return local_col, y


def _well_label(x: int, y: int) -> str:
    """PLC 坐标 → 人类可读标签，如 A1, B3。"""
    local_col, row = _local_xy(x, y)
    return f"{_ROW_LABELS[row - 1]}{local_col}"


def _well_id(x: int, y: int) -> int:
    """PLC 坐标 → 板内孔位编号 (1..24, 行优先)。"""
    local_col, row = _local_xy(x, y)
    return (row - 1) * _COLS_PER_PLATE + local_col


def _repaint(buttons: dict[tuple[int, int], ui.button], sel_x: int, sel_y: int) -> None:
    """按当前选中坐标刷新所有按钮样式。

    选中 = primary unelevated；同板非选中 = grey-4 flat；异板 = grey-3 flat outline。
    """
    sel_plate = _plate_of(sel_x)
    for (cx, cy), btn in buttons.items():
        if (cx, cy) == (sel_x, sel_y):
            btn.props(remove="color=grey-4 flat color=grey-3 outline")
            btn.props("color=primary unelevated")
        elif _plate_of(cx) == sel_plate:
            btn.props(remove="color=primary unelevated color=grey-3 outline")
            btn.props("color=grey-4 flat")
        else:
            btn.props(remove="color=primary unelevated color=grey-4 flat")
            btn.props("color=grey-3 flat outline")


def render_dual_plate_picker(
    x: int,
    y: int,
    on_change: Callable[[int, int], None],
) -> ui.element:
    """渲染双 24 孔板矩阵选择器，返回外层 ``ui.column``。

    参数：
        x, y       : 初始选中 PLC 坐标（X=1..8, Y=1..6）
        on_change  : 点击新孔位时回调 ``(x, y) -> None``
    """
    # 越界回退
    if not (1 <= x <= _TOTAL_COLS and 1 <= y <= _ROWS):
        x, y = 1, 1

    buttons: dict[tuple[int, int], ui.button] = {}

    with ui.column().classes("gap-2") as root:
        # ── 当前选中信息 ──
        plate_no = _plate_of(x)
        sel_label = ui.label(
            f"当前选中: 板{plate_no} {_well_label(x, y)} "
            f"(PLC X={x}, Y={y}, #{_well_id(x, y)})"
        ).classes("text-caption text-weight-medium")

        # ── 板标题行 ──
        # 屏幕左 = Plate 2, 屏幕右 = Plate 1 (匹配人的视角)
        with ui.row().classes("w-full gap-0 items-center"):
            ui.label("板 2").classes(
                f"text-caption text-grey-7 text-weight-bold {_PLATE_GAP_CLASS}"
            ).style(f"width: {_COLS_PER_PLATE * 44}px; text-align: center")
            ui.label("").style("width: 16px")  # 间隙占位
            ui.label("板 1").classes(
                "text-caption text-grey-7 text-weight-bold"
            ).style(f"width: {_COLS_PER_PLATE * 44}px; text-align: center")

        # ── 孔板网格 ──
        # 使用 flex column 布局，每行一个 flex row，列顺序为 X=8→1
        with ui.column().classes("gap-1"):
            for row in range(1, _ROWS + 1):
                with ui.row().classes("gap-1 items-center no-wrap"):
                    # 行标签 (A-F)
                    ui.label(_ROW_LABELS[row - 1]).classes(
                        "text-xs text-grey-6"
                    ).style("width: 16px; text-align: center")

                    for col_idx, col_x in enumerate(_SCREEN_COLS):
                        # 板间隙：在 X=4 和 X=5 之间 (col_idx=3 和 col_idx=4)
                        gap_cls = _PLATE_GAP_CLASS if col_idx == _COLS_PER_PLATE else ""

                        label = _well_label(col_x, row)
                        well_no = _well_id(col_x, row)

                        btn = (
                            ui.button(label)
                            .props("dense round size=sm")
                            .classes(f"w-10 h-10 text-xs {gap_cls}")
                        )
                        btn.tooltip(
                            f"板{_plate_of(col_x)} #{well_no} ({label})"
                        )
                        buttons[(col_x, row)] = btn

                        def _make_handler(cx: int, cy: int):
                            def _on_click() -> None:
                                p = _plate_of(cx)
                                sel_label.text = (
                                    f"当前选中: 板{p} {_well_label(cx, cy)} "
                                    f"(PLC X={cx}, Y={cy}, #{_well_id(cx, cy)})"
                                )
                                _repaint(buttons, cx, cy)
                                on_change(cx, cy)
                            return _on_click

                        btn.on("click", _make_handler(col_x, row))

        # ── 底部坐标标注 ──
        with ui.row().classes("w-full gap-0 items-center q-mt-xs"):
            ui.label("← 板 2 (X 5-8)").classes("text-xs text-grey-5").style(
                f"width: {_COLS_PER_PLATE * 44 + 16}px; text-align: center"
            )
            ui.label("|").classes("text-xs text-grey-4").style("width: 16px; text-align: center")
            ui.label("板 1 (X 1-4) →").classes("text-xs text-grey-5").style(
                f"width: {_COLS_PER_PLATE * 44}px; text-align: center"
            )

        _repaint(buttons, x, y)

    return root
