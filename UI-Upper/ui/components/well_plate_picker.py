"""可视化孔板选择器 - 单选模式（NiceGUI）。

设计要点：
- 就地 DOM 更新（修改 props + text），不依赖 ``@ui.refreshable``，避免
  NiceGUI 在 dialog / 后台 task 中重渲染丢失 client context 的问题。
- 单选模式，无 W1 试剂瓶。
- ``on_change(x, y)`` 是唯一对外接口，外层无需感知内部 button 集合。
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

from core.well_plate import WELL_PLATE_24, xy_to_label, xy_to_well_id


def render_well_plate_picker(
    x: int,
    y: int,
    on_change: Callable[[int, int], None],
    spec: dict = WELL_PLATE_24,
) -> ui.element:
    """渲染孔板矩阵，返回外层 ``ui.column``。

    参数：
        x, y       : 初始选中坐标（X=列, Y=行，1-based）
        on_change  : 点击新孔位时回调 ``(x, y) -> None``
        spec       : 孔板规格字典，默认 24 孔板
    """
    # 越界则回退到 (1, 1)，避免上游传脏数据导致渲染异常
    if not (1 <= x <= spec["cols"] and 1 <= y <= spec["rows"]):
        x, y = 1, 1

    buttons: dict[tuple[int, int], ui.button] = {}

    with ui.column().classes("gap-2") as root:
        sel_label = ui.label(
            f"当前选中: {xy_to_label(x, y, spec)} (X={x}, Y={y})"
        ).classes("text-caption text-weight-medium")

        with ui.grid(columns=spec["cols"]).classes("gap-1"):
            for row in range(1, spec["rows"] + 1):
                for col in range(1, spec["cols"] + 1):
                    label = f"{spec['row_labels'][row - 1]}{col}"
                    well_no = xy_to_well_id(col, row, spec)
                    btn = (
                        ui.button(label)
                        .props("dense round size=sm")
                        .classes("w-10 h-10 text-xs")
                    )
                    btn.tooltip(f"#{well_no} ({label})")
                    buttons[(col, row)] = btn

                    def _make_handler(cx: int, cy: int):
                        def _on_click() -> None:
                            sel_label.text = (
                                f"当前选中: {xy_to_label(cx, cy, spec)} (X={cx}, Y={cy})"
                            )
                            _repaint(buttons, cx, cy)
                            on_change(cx, cy)
                        return _on_click

                    btn.on("click", _make_handler(col, row))

        _repaint(buttons, x, y)

    return root


def _repaint(buttons: dict[tuple[int, int], ui.button], sel_x: int, sel_y: int) -> None:
    """按当前选中坐标刷新所有按钮的样式（选中=primary unelevated, 其余=grey-4 flat）。"""
    for (cx, cy), btn in buttons.items():
        if (cx, cy) == (sel_x, sel_y):
            btn.props(remove="color=grey-4 flat")
            btn.props("color=primary unelevated")
        else:
            btn.props(remove="color=primary unelevated")
            btn.props("color=grey-4 flat")
