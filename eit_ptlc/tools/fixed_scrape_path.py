"""固定刮取路径 — 回收率实验用。

把一个已知起点、固定尺寸的矩形(板 cm)变成与视觉/手绘**同契约**的 summary.json,
交给**未改动的** cnc_path 消费。零新几何代码: 落盘复用 sketch_path.write_manual_summary,
预览复用 cnc_path.generate_scrape_arrays。

用法:
    python -m eit_ptlc.tools.fixed_scrape_path --x0 3 --y0 4 --w 10 --h 5 \
        [--band-id fixed_01] [--out DIR] [--preview]

坐标系: 板 cm, 原点在 gcode.origin_corner, +x/+y 入板(与视觉/手绘同框)。
输出(stdout): summary_path=<abs> / band_id=<id> / [preview pass_count=.. point_count=.. feed=..]
把 summary_path 传给 photoscrape_process 的 fixed_summary_path 输入变量即用固定路径跑刮取+收集。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eit_ptlc.controller import sketch_path as sp

DEFAULT_BAND_ID = "fixed_01"
DEFAULT_OUT = "vision_output/fixed_scrape"  # 与 config vision.output_dir 默认对齐; 自定义 output_dir 时用 --out
_PKG_DIR = Path(__file__).resolve().parent.parent          # eit_ptlc/
DEFAULT_CONFIG = _PKG_DIR / "config" / "app.yaml"           # 与其他 tools/ 定位方式一致


def build_fixed_contour_cm(x0: float, y0: float, w: float, h: float) -> list[tuple[float, float]]:
    """矩形 4 角(板 cm), 顺序 [左下→右下→右上→左上](按 x0,y0 起点 + w,h 展开)。"""
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def write_fixed_summary(
    x0: float, y0: float, w: float, h: float, out_dir: Path, *, band_id: str = DEFAULT_BAND_ID,
) -> Path:
    """落固定矩形的 summary.json + <band_id>_path.json, 返回 summary.json 绝对路径。

    直接用 cm 指定, 跳过像素↔cm 映射(plate_bbox_px=None); 产物与视觉/手绘完全同形。
    """
    contour_cm = build_fixed_contour_cm(x0, y0, w, h)
    return sp.write_manual_summary(contour_cm, Path(out_dir), band_id=band_id).resolve()


def _preview(summary_path: Path, band_id: str, config_path: Path) -> str:
    """跑未改动的 generate_scrape_arrays, 返回可读预览串; 需要 gcode 配置(仅 --preview 时)。"""
    from eit_ptlc.config.loader import load_config
    from eit_ptlc.controller.cnc_path import generate_scrape_arrays

    gcode_cfg = load_config(config_path).gcode  # 读 app.yaml 的实时 gcode 标定
    arr = generate_scrape_arrays(summary_path, band_id, gcode_cfg)
    return f"preview pass_count={arr.pass_count} point_count={len(arr.g_sx)} feed={arr.g_scrape_feed}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成固定矩形刮取路径 summary(回收率实验)")
    ap.add_argument("--x0", type=float, required=True, help="起点 X(板 cm)")
    ap.add_argument("--y0", type=float, required=True, help="起点 Y(板 cm)")
    ap.add_argument("--w", type=float, default=10.0, help="沿 X 宽度 cm(默认 10)")
    ap.add_argument("--h", type=float, default=5.0, help="沿 Y 高度 cm(默认 5)")
    ap.add_argument("--band-id", default=DEFAULT_BAND_ID, help="band_id(默认 fixed_01)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="summary 输出目录(默认 vision_output/fixed_scrape)")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="app.yaml 路径(仅 --preview 用)")
    ap.add_argument("--preview", action="store_true", help="额外打印 pass数/点数/进给(需 gcode 配置)")
    a = ap.parse_args(argv)

    # 非正尺寸 = 退化矩形(--preview 也可能掩盖), 是纯输入错误而非板几何判断, 快速失败。
    if a.w <= 0 or a.h <= 0:
        ap.error(f"--w/--h 必须为正数(得到 w={a.w}, h={a.h})")

    summary_path = write_fixed_summary(a.x0, a.y0, a.w, a.h, Path(a.out), band_id=a.band_id)
    print(f"summary_path={summary_path}")
    print(f"band_id={a.band_id}")
    if a.preview:
        print(_preview(summary_path, a.band_id, Path(a.config)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
