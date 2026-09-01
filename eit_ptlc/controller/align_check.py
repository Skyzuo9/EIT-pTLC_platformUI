"""对位检查回显 — Δ 与建议值单点产地 (spec 2026-07-16 §5)。

Δ = ActPos 实读 − plate_origin 指令原点; jog 对准物理板角(标注图金色双圈角)后,
建议 plate_origin 新值 = 当前实读直接照抄 (plate_origin 定义即该角机床坐标, flip 不进公式)。
只显示不回写: 修正家唯一 = 配置页 plate_origin_x/y。

⚠️ Δ/建议值的前提 = ActPos 与 plate_origin 同帧(B1 C2 上机首核项); 不同帧时以
PLC 侧帧变换收敛后此式自动成立。
"""

from __future__ import annotations

from eit_ptlc.config.models import GCodeCfg


def build_align_readout(axes: tuple[float, float, float], g: GCodeCfg) -> dict:
    """三轴实读 + gcode 配置 → 回显/Δ/建议 dict (纯函数, 无 IO; VM 零算术)。

    result 键集与 D1 内环 YAML `{field: {var: ro}, name: ...}` 取值逐字对齐:
    {x_mm, y_mm, z_mm, origin_x_mm, origin_y_mm, inspect_z_mm,
     dx_vs_origin_mm, dy_vs_origin_mm, text}
    """
    x, y, z = (round(float(v), 3) for v in axes)
    inspect_z = round(max(0.0, g.plate_surface_z_mm - g.align_clearance_mm), 3)
    dx = round(x - g.plate_origin_x, 3)
    dy = round(y - g.plate_origin_y, 3)
    text = (
        f"当前 X={x} Y={y} Z={z} (mm, Z向下) | "
        f"原点角=({g.plate_origin_x}, {g.plate_origin_y}) Δ=({dx}, {dy}) | "
        f"检查高度 Z={inspect_z} | "
        f"jog 对准原点角后建议 plate_origin: x→{x} y→{y} (只显示不回写, 到配置页人工修改)"
    )
    return {
        "x_mm": x, "y_mm": y, "z_mm": z,
        "origin_x_mm": g.plate_origin_x, "origin_y_mm": g.plate_origin_y,
        "inspect_z_mm": inspect_z,
        "dx_vs_origin_mm": dx, "dy_vs_origin_mm": dy,
        "text": text,
    }
