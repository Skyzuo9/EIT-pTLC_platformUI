"""板坐标映射单一真源 — px ↔ 板cm ↔ 机床mm。

此前同一组公式存在 3 份拷贝(vision_controller 内部闭包 / sketch_path / cnc_preview,
后者连 _CORNER_FLIP 查表都自带一份)。刮后对账照片是测量仪器, 不能建立在"约定对齐"上,
故收编于此; 三处消费者全部引用本模块 (契约 C-4, spec 2026-07-15-photoscrape-scrape-closedloop)。

flip 查表唯一来源 cnc_path._flip_from_corner; 机床正变换 _to_machine 仍在 cnc_path
(路径生成职责), 本模块只做它的代数逆。
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import _flip_from_corner

Point = tuple[float, float]


# ---------------------------------------------------------------------------
# plate_bbox_px 归一化
# ---------------------------------------------------------------------------

def plate_bbox_xywh(plate_bbox_px: Any) -> tuple[float, float, float, float]:
    """把 summary 的 plate_bbox_px({x,y,w,h} 或 [x0,y0,x1,y1]) 归一为 (x, y, w, h)。"""
    if isinstance(plate_bbox_px, dict):
        return (
            float(plate_bbox_px["x"]), float(plate_bbox_px["y"]),
            float(plate_bbox_px["w"]), float(plate_bbox_px["h"]),
        )
    if isinstance(plate_bbox_px, (list, tuple)) and len(plate_bbox_px) == 4:
        x0, y0, x1, y1 = (float(v) for v in plate_bbox_px)
        return (x0, y0, x1 - x0, y1 - y0)
    raise ValueError(f"plate_bbox_px 格式无法解析: {plate_bbox_px!r}")


# ---------------------------------------------------------------------------
# 轴对齐仿射(有 plate_bbox_px): px ↔ cm, 与 vision_controller.cm_to_px 同式
# ---------------------------------------------------------------------------

def px_to_cm_affine(
    px_pts: Sequence[Point], plate_bbox_px: Any, plate_size_cm: float,
) -> list[Point]:
    """像素 → 板 cm(轴对齐)。vision 的 cm_to_px 逆变换, Y 轴翻转(图像下方=cm 小)。"""
    x, y, w, h = plate_bbox_xywh(plate_bbox_px)
    if w == 0 or h == 0:
        raise ValueError("plate_bbox_px 宽或高为 0, 无法建立像素→cm 映射")
    out: list[Point] = []
    for px, py in px_pts:
        cx = (float(px) - x) / w * plate_size_cm
        cy = (h - (float(py) - y)) / h * plate_size_cm
        out.append((cx, cy))
    return out


def cm_to_px_affine(
    cm_pts: Sequence[Point], plate_bbox_px: Any, plate_size_cm: float,
) -> list[Point]:
    """板 cm → 像素(轴对齐)。与 vision 渲染同式; 退化板框/尺寸直接拒绝。"""
    x, y, w, h = plate_bbox_xywh(plate_bbox_px)
    if w <= 0 or h <= 0 or plate_size_cm <= 0:
        raise ValueError("板框或 plate_size_cm 无效，无法建立 cm→px 映射")
    out: list[Point] = []
    for cx, cy in cm_pts:
        px = x + (float(cx) / plate_size_cm) * w
        py = y + h - (float(cy) / plate_size_cm) * h
        out.append((px, py))
    return out


# ---------------------------------------------------------------------------
# 透视单应(无 plate_bbox_px, 4 角点手动标板): 纯 numpy DLT, 不依赖 cv2
# ---------------------------------------------------------------------------

def _solve_homography(src: Sequence[Point], dst: Sequence[Point]) -> np.ndarray:
    """解 3x3 单应 H, 使 dst ~ H·src(齐次)。4 对点标准 DLT(8x8 线性系统, h33=1)。"""
    if len(src) != 4 or len(dst) != 4:
        raise ValueError("单应需要恰好 4 对点")
    a = np.zeros((8, 8), dtype=float)
    b = np.zeros(8, dtype=float)
    for i, ((sx, sy), (dx, dy)) in enumerate(zip(src, dst)):
        a[2 * i] = [sx, sy, 1, 0, 0, 0, -dx * sx, -dx * sy]
        a[2 * i + 1] = [0, 0, 0, sx, sy, 1, -dy * sx, -dy * sy]
        b[2 * i] = dx
        b[2 * i + 1] = dy
    try:
        h = np.linalg.solve(a, b)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"4 角点退化(共线/重合), 无法建立透视映射: {exc}") from exc
    return np.array([[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]], dtype=float)


def _apply_homography(mat: np.ndarray, pts: Sequence[Point]) -> list[Point]:
    arr = np.array([[px, py, 1.0] for px, py in pts], dtype=float)
    mapped = arr @ mat.T
    w = mapped[:, 2]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return [(float(u / wi), float(v / wi)) for (u, v, _), wi in zip(mapped, w)]


def _corner_cm_targets(plate_size_cm: float) -> list[Point]:
    """4 角点约定顺序 [左上, 右上, 右下, 左下] → 对应板 cm(Y 向上为大)。"""
    s = float(plate_size_cm)
    return [(0.0, s), (s, s), (s, 0.0), (0.0, 0.0)]


def px_to_cm_corners(
    px_pts: Sequence[Point], plate_corners_px: Sequence[Point], plate_size_cm: float,
) -> list[Point]:
    """像素 → 板 cm(透视)。plate_corners_px 顺序 [左上,右上,右下,左下]。"""
    if len(plate_corners_px) != 4:
        raise ValueError("plate_corners_px 需恰好 4 个角点 [左上,右上,右下,左下]")
    mat = _solve_homography(list(plate_corners_px), _corner_cm_targets(plate_size_cm))
    return _apply_homography(mat, px_pts)


def cm_to_px_corners(
    cm_pts: Sequence[Point], plate_corners_px: Sequence[Point], plate_size_cm: float,
) -> list[Point]:
    """板 cm → 像素(透视, px_to_cm_corners 的反向单应)。"""
    if len(plate_corners_px) != 4:
        raise ValueError("plate_corners_px 需恰好 4 个角点 [左上,右上,右下,左下]")
    mat = _solve_homography(_corner_cm_targets(plate_size_cm), list(plate_corners_px))
    return _apply_homography(mat, cm_pts)


def cm_to_px(
    cm_pts: Sequence[Point],
    *,
    plate_size_cm: float,
    plate_bbox_px: Any = None,
    plate_corners_px: Sequence[Point] | None = None,
) -> list[Point]:
    """板 cm → 像素, 按可用的板参照(bbox 轴对齐优先, 否则 4 角透视)分派。"""
    if plate_bbox_px is not None:
        return cm_to_px_affine(cm_pts, plate_bbox_px, plate_size_cm)
    if plate_corners_px is not None:
        return cm_to_px_corners(cm_pts, plate_corners_px, plate_size_cm)
    raise ValueError("缺少 plate_bbox_px 与 plate_corners_px, 无法把 cm 映射回像素")


# ---------------------------------------------------------------------------
# 机床 mm → px(预览叠加): cnc_path._to_machine 的逆 + cm→px
# ---------------------------------------------------------------------------

def machine_mm_to_cm(pts_mm: Sequence[Point], gcode_cfg: GCodeCfg) -> list[Point]:
    """机床(mm) → 板 cm。cnc_path._to_machine 的代数逆(按 origin_corner 翻转 + plate_origin)。"""
    flip_x, flip_y = _flip_from_corner(gcode_cfg.origin_corner)
    ox, oy = gcode_cfg.plate_origin_x, gcode_cfg.plate_origin_y
    out: list[Point] = []
    for mx, my in pts_mm:
        cx = (ox - mx) / 10.0 if flip_x else (mx - ox) / 10.0
        cy = (oy - my) / 10.0 if flip_y else (my - oy) / 10.0
        out.append((cx, cy))
    return out


def machine_mm_to_px(
    pts_mm: Sequence[Point], gcode_cfg: GCodeCfg, plate_bbox_px: Any = None,
    plate_size_cm: float = 20.0, *, plate_corners_px: Sequence[Point] | None = None,
) -> list[Point]:
    """机床(mm) → 像素。预览把真机将跑的路径叠回板照片(所见即所跑)。

    有 plate_bbox_px 走轴对齐; 否则用 plate_corners_px 走透视(手动标板兜底)。
    """
    return cm_to_px(
        machine_mm_to_cm(pts_mm, gcode_cfg),
        plate_size_cm=plate_size_cm,
        plate_bbox_px=plate_bbox_px, plate_corners_px=plate_corners_px,
    )


# ---------------------------------------------------------------------------
# 板坐标系标注几何(HITL 画布/叠加图): 原点/±轴箭头/四角 cm 标签
# ---------------------------------------------------------------------------

def plate_axes_annotation(plate_bbox_px: Any, plate_size_cm: float) -> dict[str, Any]:
    """标注几何(px), 全部经本模块同一 cm→px 映射 — 标注即同源探针, 映射错则箭头立错。

    只核标角(相机侧): cm(0,0) 按仿射约定恒在 bbox 图像左下角, 与 origin_corner 无关
    (flip 只活在机床↔cm 变换)。对刀偏差在图像域不可见, 用「对位检查」核对
    (spec 2026-07-16-photoscrape-align-check §3)。
    """
    s = float(plate_size_cm)
    arrow_cm = min(3.0, s * 0.15)
    pts = cm_to_px_affine(
        [(0.0, 0.0), (arrow_cm, 0.0), (0.0, arrow_cm), (s, 0.0), (0.0, s), (s, s)],
        plate_bbox_px, s,
    )

    def _xy(p: Point) -> list[float]:
        return [round(p[0], 1), round(p[1], 1)]

    return {
        "origin_px": _xy(pts[0]),
        "x_tip_px": _xy(pts[1]),
        "y_tip_px": _xy(pts[2]),
        "corners": [
            {"px": _xy(pts[0]), "label": "cm(0,0)"},
            {"px": _xy(pts[3]), "label": f"cm({s:g},0)"},
            {"px": _xy(pts[4]), "label": f"cm(0,{s:g})"},
            {"px": _xy(pts[5]), "label": f"cm({s:g},{s:g})"},
        ],
    }
