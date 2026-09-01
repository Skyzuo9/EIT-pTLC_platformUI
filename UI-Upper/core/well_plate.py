"""孔板规格定义 + 坐标映射（PC 侧查表，PLC 侧 X/Y 契约零改动）。

首版仅支持 24 孔板（4 行 × 6 列，A1..D6）。
扩展新规格只需新增常量字典并在 UI 处接入下拉切换，本模块的映射函数已通过
``spec`` 参数泛化。

X = 列号 (1..cols)，Y = 行号 (1..rows)，与 PLC 的
``Sampling_X_coordinate / Sampling_Y_coordinate`` 契约对齐。
"""

from __future__ import annotations

WELL_PLATE_24: dict = {
    "name": "24-well plate",
    "rows": 4,          # Y 轴，1..4 对应 A..D
    "cols": 6,          # X 轴，1..6
    "row_labels": ["A", "B", "C", "D"],
}


def well_id_to_xy(well_id: int, spec: dict = WELL_PLATE_24) -> tuple[int, int]:
    """孔位编号 1..N → (x, y)。

    编号顺序：A1=1, A2=2 ... A6=6, B1=7 ...（行优先，左→右、上→下）。
    """
    total = spec["rows"] * spec["cols"]
    if not 1 <= well_id <= total:
        raise ValueError(f"well_id {well_id} 越界 [1..{total}]")
    idx0 = well_id - 1
    y = idx0 // spec["cols"] + 1
    x = idx0 % spec["cols"] + 1
    return x, y


def xy_to_well_id(x: int, y: int, spec: dict = WELL_PLATE_24) -> int:
    """(x, y) → 孔位编号 1..N。"""
    if not (1 <= x <= spec["cols"] and 1 <= y <= spec["rows"]):
        raise ValueError(f"(x={x}, y={y}) 越界 cols=[1..{spec['cols']}] rows=[1..{spec['rows']}]")
    return (y - 1) * spec["cols"] + x


def xy_to_label(x: int, y: int, spec: dict = WELL_PLATE_24) -> str:
    """(x, y) → 人类可读标签，如 A1, B3。"""
    if not (1 <= x <= spec["cols"] and 1 <= y <= spec["rows"]):
        raise ValueError(f"(x={x}, y={y}) 越界")
    return f"{spec['row_labels'][y - 1]}{x}"
