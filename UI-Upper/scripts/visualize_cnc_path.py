"""visualize_cnc_path.py — CNC 路径离线可视化（不连 PLC，不挂 NiceGUI）

针对任意 summary.json + band + 策略 + keep_ratio 组合，调用 generate_scrape_arrays
得到最终下发给 PLC 的 400 点 (X, Y) 序列，并以 matplotlib 输出 PNG：
  - CNC 路径折线（按下标顺序，含方向箭头）
  - 路径有效作业区外包络（按列分组取上/下端点连成闭合多边形 + 半透明填充）
  - 400 点凸包（虚线，几何外包参考）
  - bbox 矩形（点划线，对照基准）
不画 contour_cm（用户明确要求："不是识别到的条带区域路径"）。

奥卡姆剃刀：
  - 不引入 scipy / shapely 新依赖；凸包用 Andrew's monotone chain（纯 numpy）
  - 不画刀具直径扫掠包络（cutter_diameter 无真机标定）
  - 单图双子图：刮扫（g_sx/g_sy）+ 收集（g_cx/g_cy）

CLI 范例：
    cd UI-Upper
    python scripts/visualize_cnc_path.py \\
        --summary View/pTLC_Viewing/analysis_output/case1/summary.json \\
        --band band_01 --strategy contour --keep-ratio 1.0
    python scripts/visualize_cnc_path.py \\
        --summary View/pTLC_Viewing/analysis_output/case1/summary.json \\
        --band band_01 --strategy contour --keep-ratio 0.5

退出码：0 成功 / 1 找不到 summary / 2 路径生成失败
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

# 让本脚本能 import core 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

# matplotlib：本地导入（避免不需要时引入开销 / 让 ImportError 信息更清晰）
try:
    import matplotlib  # noqa: E402
    matplotlib.use("Agg")  # headless / CI 友好
    import matplotlib.pyplot as plt  # noqa: E402
except ImportError as e:  # pragma: no cover
    print(f"[visualize_cnc_path] 缺少 matplotlib 依赖：{e}", file=sys.stderr)
    sys.exit(2)

from core.cnc_path_generator import (  # noqa: E402
    SCRAPE_POINT_COUNT,
    COLLECT_POINT_COUNT,
    generate_scrape_arrays,
    _compute_coverage_columns,
    _effective_step_mm,
)
from core.config import GCodeCfg, load_config  # noqa: E402

log = logging.getLogger("visualize_cnc_path")


# ---------------------------------------------------------------------------
# 辅助：路径外包络多边形 + 凸包
# ---------------------------------------------------------------------------

def _envelope_polygon(
    xs: list[float], ys: list[float], columns: int,
) -> tuple[list[float], list[float]]:
    """按列分组取上/下端点连成闭合多边形（用于刮取/收集有效作业区可视化）。

    路径生成器约定：400 点 = columns × per_col，列内 Y 在上下端点之间走（boustrophedon /
    contour 列扫策略）。每列取 max(Y) 为上沿、min(Y) 为下沿，按 X 顺序连接成闭合多边形。
    zigzag 策略下 columns 仍可任意指定，效果是把路径分组取每段包络。
    """
    n = len(xs)
    if n == 0 or columns < 1 or n % columns != 0:
        return [], []
    per_col = n // columns

    upper_xs: list[float] = []
    upper_ys: list[float] = []
    lower_xs: list[float] = []
    lower_ys: list[float] = []
    for col in range(columns):
        seg_xs = xs[col * per_col:(col + 1) * per_col]
        seg_ys = ys[col * per_col:(col + 1) * per_col]
        if not seg_xs:
            continue
        # 列内 X 通常恒定（boustrophedon / contour），取首点作为列代表 X
        rep_x = float(np.mean(seg_xs))
        upper_xs.append(rep_x)
        upper_ys.append(float(max(seg_ys)))
        lower_xs.append(rep_x)
        lower_ys.append(float(min(seg_ys)))

    # 上沿正向 X、下沿反向 X 闭合
    poly_xs = upper_xs + list(reversed(lower_xs)) + [upper_xs[0]]
    poly_ys = upper_ys + list(reversed(lower_ys)) + [upper_ys[0]]
    return poly_xs, poly_ys


def _convex_hull(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Andrew's monotone chain 凸包，O(N log N)，返回闭合多边形（首末点重复）。"""
    pts = sorted(set(zip(xs, ys)))
    if len(pts) < 3:
        # 退化：返回输入或空
        if not pts:
            return [], []
        cx = [p[0] for p in pts] + [pts[0][0]]
        cy = [p[1] for p in pts] + [pts[0][1]]
        return cx, cy

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    hull.append(hull[0])  # 闭合
    return [p[0] for p in hull], [p[1] for p in hull]


# ---------------------------------------------------------------------------
# bbox 机床矩形：把 bbox_cm + 偏移转为机床坐标矩形（用于参考层）
# ---------------------------------------------------------------------------

def _bbox_machine_rect(
    bbox_cm: tuple[float, float, float, float],
    cfg: GCodeCfg,
    x_offset_mm: float = 0.0,
) -> tuple[list[float], list[float]]:
    """返回 bbox 在机床坐标系下的闭合矩形（按 origin_corner 的 flip 处理）。"""
    from core.cnc_path_generator import _flip_from_corner, _to_machine
    flip_x, flip_y = _flip_from_corner(cfg.origin_corner)
    x_min, y_min, x_max, y_max = bbox_cm
    offset_cm = x_offset_mm / 10.0
    pts_cm = [
        (x_min + offset_cm, y_min),
        (x_max + offset_cm, y_min),
        (x_max + offset_cm, y_max),
        (x_min + offset_cm, y_max),
        (x_min + offset_cm, y_min),
    ]
    xs, ys = [], []
    for x, y in pts_cm:
        mx, my = _to_machine(x, y, cfg.plate_origin_x, cfg.plate_origin_y, flip_x, flip_y)
        xs.append(mx)
        ys.append(my)
    return xs, ys


# ---------------------------------------------------------------------------
# 子图渲染
# ---------------------------------------------------------------------------

def _render_subplot(
    ax,
    xs: list[float], ys: list[float],
    bbox_rect_xs: list[float], bbox_rect_ys: list[float],
    columns: int,
    title: str,
) -> None:
    """渲染单个子图（路径折线 + 外包络 + 凸包 + bbox 矩形）。"""
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, linestyle=":", alpha=0.4)

    # bbox 矩形（最浅，作底层参考）
    ax.plot(bbox_rect_xs, bbox_rect_ys, color="#888", linestyle="-.", linewidth=0.8, label="bbox")

    # 凸包
    hull_xs, hull_ys = _convex_hull(xs, ys)
    if hull_xs:
        ax.plot(hull_xs, hull_ys, color="#666", linestyle="--", linewidth=0.9, label="convex hull")

    # 路径有效作业区外包络（按列上/下端点）
    poly_xs, poly_ys = _envelope_polygon(xs, ys, columns)
    if poly_xs:
        ax.fill(poly_xs, poly_ys, color="#4a90e2", alpha=0.18, label=f"envelope (cols={columns})")
        ax.plot(poly_xs, poly_ys, color="#2a6cb6", linewidth=1.0)

    # CNC 路径折线
    ax.plot(xs, ys, color="#d6336c", linewidth=1.2, marker="o", markersize=2.5, label="CNC path")

    # 方向箭头：每 8 点 1 个
    for i in range(0, len(xs) - 1, 8):
        dx = xs[i + 1] - xs[i]
        dy = ys[i + 1] - ys[i]
        if abs(dx) + abs(dy) < 1e-9:
            continue
        ax.annotate(
            "", xy=(xs[i + 1], ys[i + 1]), xytext=(xs[i], ys[i]),
            arrowprops=dict(arrowstyle="->", color="#d6336c", alpha=0.6, lw=0.8),
        )

    # 起点 / 终点
    if xs:
        ax.scatter([xs[0]], [ys[0]], marker="^", s=80, color="#28a745",
                   zorder=5, label=f"start ({xs[0]:.1f}, {ys[0]:.1f})")
        ax.scatter([xs[-1]], [ys[-1]], marker="s", s=80, color="#dc3545",
                   zorder=5, label=f"end ({xs[-1]:.1f}, {ys[-1]:.1f})")

    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=8, framealpha=0.85)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _bbox_from_summary(summary_path: Path, band_id: str) -> tuple[float, float, float, float]:
    """轻量取 bbox_cm（仅供 _bbox_machine_rect 用，不重复 path_json 解析复杂度）。"""
    from core.cnc_path_generator import _load_band_geometry
    from core.gcode_generator import _patch_summary_paths
    patched = _patch_summary_paths(summary_path, summary_path.parent)
    try:
        bbox_cm, _contour = _load_band_geometry(patched, band_id)
    finally:
        try:
            patched.unlink()
        except OSError:
            pass
    return bbox_cm


def _load_gcode_cfg(args: argparse.Namespace) -> GCodeCfg:
    """从 yaml 加载 GCodeCfg，再按 CLI 参数覆写。"""
    cfg: GCodeCfg
    if args.config:
        config_path = Path(args.config)
        if not config_path.is_file():
            log.warning("config 不存在 %s，使用 GCodeCfg() 默认值", config_path)
            cfg = GCodeCfg()
        else:
            cfg = load_config(config_path).gcode
    else:
        cfg = GCodeCfg()

    if args.strategy is not None:
        cfg = replace(cfg, path_strategy=str(args.strategy).strip().lower())
    if args.keep_ratio is not None:
        cfg = replace(cfg, scrape_keep_ratio=float(args.keep_ratio))
    if args.columns is not None:
        cfg = replace(cfg, boustrophedon_columns=int(args.columns))
    return cfg


def _resolve_output_path(args: argparse.Namespace, cfg: GCodeCfg) -> Path:
    if args.output:
        return Path(args.output)
    summary = Path(args.summary)
    name = (
        f"{args.band}_{cfg.path_strategy}"
        f"_k{cfg.scrape_keep_ratio:.2f}"
        f"_cols{cfg.boustrophedon_columns}.png"
    )
    return summary.parent / name


def main() -> int:
    p = argparse.ArgumentParser(
        description="CNC 路径可视化（离线，不连 PLC）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--summary", required=True, help="summary.json 路径")
    p.add_argument("--band", required=True, help="band_id（如 band_01）")
    p.add_argument(
        "--strategy", default=None,
        choices=["zigzag", "boustrophedon", "contour"],
        help="覆盖 gcode_cfg.path_strategy（默认走 yaml）",
    )
    p.add_argument("--keep-ratio", type=float, default=None,
                   help="覆盖 gcode_cfg.scrape_keep_ratio（contour 策略生效）")
    p.add_argument("--columns", type=int, default=None,
                   help="覆盖 gcode_cfg.boustrophedon_columns（必须能整除 200）")
    p.add_argument("--config", default=None,
                   help="config.yaml 路径（默认走 GCodeCfg() 类默认值）")
    p.add_argument("--output", default=None, help="输出 PNG 路径（默认放 summary 同目录）")
    p.add_argument("--verbose", "-v", action="store_true", help="DEBUG 日志")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    summary_path = Path(args.summary)
    if not summary_path.is_file():
        log.error("summary 不存在: %s", summary_path)
        return 1

    cfg = _load_gcode_cfg(args)
    log.info(
        "[visualize] strategy=%s keep_ratio=%.2f columns=%d band=%s",
        cfg.path_strategy, cfg.scrape_keep_ratio, cfg.boustrophedon_columns, args.band,
    )

    try:
        arrays = generate_scrape_arrays(summary_path, args.band, cfg)
    except (FileNotFoundError, KeyError, ValueError) as e:
        log.error("[visualize] 路径生成失败: %s", e)
        return 2

    bbox_cm = _bbox_from_summary(summary_path, args.band)

    # bbox 机床矩形：刮扫用 offset=0，收集用 bottle_x_offset_mm
    # 收集参考矩形须与实际 collect_bbox 一致（含 margin + Y 膨胀）
    scrape_bbox_xs, scrape_bbox_ys = _bbox_machine_rect(bbox_cm, cfg, x_offset_mm=0.0)

    # 复刻 cnc_path_generator 中 collect_bbox 的计算
    x_min, y_min, x_max, y_max = bbox_cm
    margin_cm = cfg.tool.cutter_diameter_mm / 2.0 / 10.0
    y_center = (y_min + y_max) / 2.0
    y_half = (y_max - y_min) / 2.0 * cfg.collect_expand_ratio
    collect_bbox_adj = (x_min - margin_cm, y_center - y_half,
                        x_max + margin_cm, y_center + y_half)
    collect_bbox_xs, collect_bbox_ys = _bbox_machine_rect(
        collect_bbox_adj, cfg, x_offset_mm=cfg.tool.bottle_x_offset_mm,
    )

    # 收集路径实际列数（基于 bottle_diameter + collection.overlap_ratio）
    collect_step_mm = _effective_step_mm(
        cfg.tool.bottle_diameter_mm, cfg.collection.overlap_ratio,
    )
    collect_x_span_mm = (collect_bbox_adj[2] - collect_bbox_adj[0]) * 10.0
    collect_columns = max(_compute_coverage_columns(
        collect_x_span_mm, collect_step_mm, COLLECT_POINT_COUNT,
    ), 1)
    if COLLECT_POINT_COUNT % collect_columns != 0:
        max_cols = COLLECT_POINT_COUNT // 2
        for d in range(collect_columns, max_cols + 1):
            if COLLECT_POINT_COUNT % d == 0:
                collect_columns = d
                break
        else:
            collect_columns = max_cols

    # 渲染
    fig, axes = plt.subplots(1, 2, figsize=(16, 7), dpi=120)
    title_meta = (
        f"strategy={cfg.path_strategy} | k={cfg.scrape_keep_ratio:.2f} | "
        f"cols={cfg.boustrophedon_columns} | band={args.band}"
    )
    fig.suptitle(title_meta, fontsize=11)

    _render_subplot(
        axes[0], list(arrays.g_sx), list(arrays.g_sy),
        scrape_bbox_xs, scrape_bbox_ys,
        cfg.boustrophedon_columns,
        f"Scrape path ({SCRAPE_POINT_COUNT} pts)",
    )
    _render_subplot(
        axes[1], list(arrays.g_cx), list(arrays.g_cy),
        collect_bbox_xs, collect_bbox_ys,
        collect_columns,
        f"Collect path ({COLLECT_POINT_COUNT} pts)",
    )

    plt.tight_layout(rect=(0, 0, 1, 0.96))
    out_path = _resolve_output_path(args, cfg)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)

    log.info("[visualize] PNG 已写出: %s", out_path)
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
