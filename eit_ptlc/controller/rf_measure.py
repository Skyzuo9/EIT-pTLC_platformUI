"""Rf 测量核心 (纯算 + spot 检测)
================================
把两段迁移距离都放进同一「板归一化坐标系」→ 尺度约掉 → Rf = D_s / D_f。
坐标: u∈[0,1] 左→右, v∈[0,1] 上→下 (图像惯例)。
本模块不做 D_f/origin_frac 的来源或存储 (属 Phase 2), 只消费传入常量。
imaging 导入 lazy/guarded, 顶层无 cv2 依赖。

Usage::

    from eit_ptlc.controller.rf_measure import analyze_rf
    results = analyze_rf(
        image_bgr, plate_bbox,
        origin_frac=0.9,   # 伺服常量 (Phase 2 提供)
        d_f=0.8,           # 前沿迁移幅值 (Phase 2 标定)
        axis="v", direction=-1,
    )
    for r in results:
        print(r.index, r.rf)
"""

from __future__ import annotations

from dataclasses import dataclass


def to_plate_uv(px: float, py: float, plate_bbox: dict[str, int]) -> tuple[float, float]:
    """把图像像素 (px,py) 映到板归一化 (u,v)。

    plate_bbox: {"x","y","w","h"} (同 vision_quality.plate_bbox_px)。
    复用现有去旋转/透视归一化后的分析帧, 故轴对齐仿射足够。
    """
    w = plate_bbox["w"]
    h = plate_bbox["h"]
    if w <= 0 or h <= 0:
        raise ValueError(f"plate_bbox 宽高须为正: w={w} h={h}")
    u = (px - plate_bbox["x"]) / w
    v = (py - plate_bbox["y"]) / h
    return (u, v)


@dataclass
class SpotHit:
    """一个斑点在板归一化系里的位置。"""
    u: float
    v: float
    area_frac: float           # blob 面积 / 板面积
    center_px: tuple[float, float]  # 原图绝对像素中心 (调试用)


@dataclass
class RfResult:
    index: int
    u: float
    v: float
    d_s: float
    rf: float | None           # d_f<=0 时为 None


def migration(coord: float, origin_frac: float, direction: int) -> float:
    """迁移量 = (coord - origin_frac) * direction。取号使迁移为正。"""
    return (coord - origin_frac) * direction


def compute_rf(
    spots: list[SpotHit],
    *,
    origin_frac: float,
    d_f: float,
    axis: str = "v",
    direction: int = -1,
) -> list[RfResult]:
    """由斑点板归一化位置算 Rf。

    axis: 展开方向轴 ("u" 或 "v")。origin_frac: 原点在该轴的坐标。
    d_f: 前沿迁移幅值 (板归一化, 正)。direction: 迁移取号 (+1/-1)。
    """
    if axis not in ("u", "v"):
        raise ValueError(f"axis 须为 'u' 或 'v', got {axis!r}")
    results: list[RfResult] = []
    for i, s in enumerate(spots):
        coord = s.v if axis == "v" else s.u
        d_s = migration(coord, origin_frac, direction)
        rf = (d_s / d_f) if d_f > 0 else None
        results.append(RfResult(index=i, u=s.u, v=s.v, d_s=d_s, rf=rf))
    return results


def detect_spots(
    image_bgr,
    plate_bbox: dict[str, int],
    *,
    min_area_frac: float = 1e-4,
    max_area_frac: float = 0.05,
    darkness_k: float = 2.0,
) -> list[SpotHit]:
    """在 plate_bbox 内检测 UV 暗斑 (暗打亮底), 返回板归一化中心。

    algorithm: 裁剪→灰度→比局部均值暗 darkness_k*std 的像素二值化→
    形态学开去噪→连通域→按面积占比过滤→质心。
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 环境保证有 cv2
        raise RuntimeError("detect_spots 需要 cv2/numpy") from exc

    x, y, w, h = plate_bbox["x"], plate_bbox["y"], plate_bbox["w"], plate_bbox["h"]
    if w <= 0 or h <= 0:
        raise ValueError(f"plate_bbox 宽高须为正: w={w} h={h}")
    roi = image_bgr[y : y + h, x : x + w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    mean = float(gray.mean())
    std = float(gray.std())
    thresh_val = max(0.0, mean - darkness_k * std)
    # 暗斑 = 低于阈值
    dark = (gray < thresh_val).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opened = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)

    num, labels, stats, centroids = cv2.connectedComponentsWithStats(opened, connectivity=8)
    plate_area = float(w * h)
    hits: list[SpotHit] = []
    for lbl in range(1, num):  # 0 = 背景
        area = float(stats[lbl, cv2.CC_STAT_AREA])
        frac = area / plate_area
        if frac < min_area_frac or frac > max_area_frac:
            continue
        cx_roi, cy_roi = centroids[lbl]
        abs_px = (x + float(cx_roi), y + float(cy_roi))
        u, v = to_plate_uv(abs_px[0], abs_px[1], plate_bbox)
        hits.append(SpotHit(u=u, v=v, area_frac=frac, center_px=abs_px))
    return hits


def analyze_rf(
    image_bgr,
    plate_bbox: dict[str, int],
    *,
    origin_frac: float,
    d_f: float,
    axis: str = "v",
    direction: int = -1,
    spot_params: dict | None = None,
) -> list[RfResult]:
    """端到端: 检测斑点 → 算 Rf → 按迁移量 d_s 升序返回。"""
    params = spot_params or {}
    spots = detect_spots(image_bgr, plate_bbox, **params)
    results = compute_rf(
        spots, origin_frac=origin_frac, d_f=d_f, axis=axis, direction=direction,
    )
    results.sort(key=lambda r: r.d_s)
    # 排序后重编 index 以反映输出顺序
    for new_i, r in enumerate(results):
        r.index = new_i
    return results
