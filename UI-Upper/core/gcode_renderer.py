"""G-code 路径可视化渲染 — 复用 View/pTLC_Viewing/gcode_plot.py。

封装 gcode_plot.py 的 parse_gcode + plot 逻辑，输出 PNG 供 ui.image() 加载。
"""

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_VIEW_DIR = Path(__file__).parent.parent.parent / "View" / "pTLC_Viewing"


def _ensure_gcode_plot():
    """动态注入 gcode_plot 所在目录并导入。"""
    view_dir_str = str(_VIEW_DIR)
    if view_dir_str not in sys.path:
        sys.path.insert(0, view_dir_str)
    try:
        import gcode_plot  # type: ignore  # noqa: PLC0415
        return gcode_plot
    except ImportError as e:
        raise RuntimeError(f"无法导入 gcode_plot，请检查路径 {_VIEW_DIR}: {e}") from e


def render_gcode_path(
    gcode_path: Path,
    output_path: Path | None = None,
) -> Path:
    """基于 gcode_plot.py 生成刮取路径 2D 可视化 PNG。

    Args:
        gcode_path: .gcode 文件路径。
        output_path: 输出 PNG 路径，默认为 gcode_path 同名 .png。

    Returns:
        生成的 PNG 文件路径。
    """
    gcode_plot = _ensure_gcode_plot()

    if output_path is None:
        output_path = gcode_path.with_suffix(".png")

    # 使用 gcode_plot.parse_gcode 解析，手动渲染以控制输出路径
    bands = gcode_plot.parse_gcode(gcode_path)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))
    for bid, pts in bands.items():
        if not pts:
            continue
        xs, ys = zip(*pts)
        ax.plot(xs, ys, marker=".", markersize=2, label=bid)
    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(gcode_path.stem)
    ax.legend(fontsize=7)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    log.info("[GCodeRenderer] 生成路径图: %s", output_path)
    return output_path


def render_scrape_arrays_path(
    arrays,
    output_path: Path,
    title: str = "CNC Path Preview",
) -> Path:
    """从 ScrapeArrays 直接渲染刮取+收集路径 2D PNG。

    与 render_gcode_path() 的区别：
      - 输入是 ScrapeArrays（PLC 实际消费的点位数组），不是 .gcode 文本
      - 确保预览路径 = PLC 执行路径（统一数据源）

    Args:
        arrays: ScrapeArrays 实例（来自 core.cnc_path_generator）
        output_path: 输出 PNG 路径
        title: 图片标题

    Returns:
        生成的 PNG 文件路径
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))

    # 刮取路径（蓝色）
    if arrays.g_sx and arrays.g_sy:
        ax.plot(arrays.g_sx, arrays.g_sy, "b.-", markersize=2,
                label=f"Scrape ({len(arrays.g_sx)} pts)", alpha=0.7)

    # 收集路径（红色）
    if arrays.g_cx and arrays.g_cy:
        ax.plot(arrays.g_cx, arrays.g_cy, "r.-", markersize=2,
                label=f"Collect ({len(arrays.g_cx)} pts)", alpha=0.7)

    ax.set_aspect("equal")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(f"{title} | passes={arrays.g_pass_count} depth={arrays.g_total_depth}mm")
    ax.legend(fontsize=8)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    log.info("[GCodeRenderer] 生成 ScrapeArrays 路径图: %s", output_path)
    return output_path
