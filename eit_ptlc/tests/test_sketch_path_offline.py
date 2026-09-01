"""手绘路径来源离线测试 — 证明 sketch(像素) → summary → cnc_path 全链贯通。

核心断言: 手绘产出的 summary/path_json 被**未改动的** cnc_path.generate_scrape_arrays
消费后, 得到非退化的 400 点真机路径, 且预览 machine(mm)→px 逆变换落回板像素框内。
"""

from __future__ import annotations

import math

import pytest

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller.cnc_path import SCRAPE_POINT_COUNT, generate_scrape_arrays
from eit_ptlc.controller import sketch_path as sp

PLATE_SIZE_CM = 20.0
# 400px 边 = 20cm 板; 板在图内偏移 (100,50)
PLATE_BBOX = {"x": 100.0, "y": 50.0, "w": 400.0, "h": 400.0}
# 手绘一个矩形区域(像素), 顺时针
REGION_PX = [(150.0, 100.0), (450.0, 100.0), (450.0, 400.0), (150.0, 400.0)]


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def _bary_inside(p, tri, eps=0.02):
    """点 p(cm) 是否落在三角形 tri(3×cm 顶点) 内 (含边, 容 eps 重心坐标误差)。"""
    (x, y) = p
    (x1, y1), (x2, y2), (x3, y3) = tri
    denom = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(denom) < 1e-12:
        return False
    a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / denom
    b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / denom
    c = 1.0 - a - b
    return a >= -eps and b >= -eps and c >= -eps


def test_px_cm_affine_is_true_inverse():
    """px→cm→px 往返应恒等(与 vision 的 cm_to_px 同式)。"""
    cm = sp.px_to_cm_affine(REGION_PX, PLATE_BBOX, PLATE_SIZE_CM)
    back = sp.cm_to_px_affine(cm, PLATE_BBOX, PLATE_SIZE_CM)
    for (px0, py0), (px1, py1) in zip(REGION_PX, back):
        assert _approx(px0, px1, 1e-4) and _approx(py0, py1, 1e-4)


def test_affine_maps_expected_cm():
    """已知像素点映射到手算 cm(Y 翻转)。"""
    cm = sp.px_to_cm_affine([(150.0, 100.0), (450.0, 400.0)], PLATE_BBOX, PLATE_SIZE_CM)
    # (150,100): x=(150-100)/400*20=2.5 ; y=(400-(100-50))/400*20=17.5
    assert _approx(cm[0][0], 2.5, 1e-4) and _approx(cm[0][1], 17.5, 1e-4)
    # (450,400): x=17.5 ; y=(400-350)/400*20=2.5
    assert _approx(cm[1][0], 17.5, 1e-4) and _approx(cm[1][1], 2.5, 1e-4)


def test_corner_homography_matches_affine_on_axis_aligned_plate():
    """4 角点 = 板 bbox 角 → 透视应退化到与轴对齐仿射一致。"""
    corners = [(100.0, 50.0), (500.0, 50.0), (500.0, 450.0), (100.0, 450.0)]  # TL,TR,BR,BL
    probe = [(300.0, 250.0), (150.0, 100.0), (450.0, 400.0)]
    via_corners = sp.px_to_cm_corners(probe, corners, PLATE_SIZE_CM)
    via_affine = sp.px_to_cm_affine(probe, PLATE_BBOX, PLATE_SIZE_CM)
    for (cx0, cy0), (cx1, cy1) in zip(via_corners, via_affine):
        assert _approx(cx0, cx1, 1e-3) and _approx(cy0, cy1, 1e-3)


def test_polygon_to_contour_cm_requires_a_plate_reference():
    with pytest.raises(ValueError):
        sp.polygon_to_contour_cm(REGION_PX, plate_size_cm=PLATE_SIZE_CM)


@pytest.mark.parametrize("strategy", ["boustrophedon", "contour"])
def test_sketch_roundtrip_yields_real_400_point_path(tmp_path, strategy):
    """核心契约: 手绘 → summary → 未改动 cnc_path → 非退化 400 点。"""
    contour_cm = sp.polygon_to_contour_cm(
        REGION_PX, plate_size_cm=PLATE_SIZE_CM, plate_bbox_px=PLATE_BBOX,
    )
    summary_path = sp.write_manual_summary(contour_cm, tmp_path, plate_bbox_px=PLATE_BBOX)
    assert summary_path.is_file()

    cfg = GCodeCfg(path_strategy=strategy)
    arrays = generate_scrape_arrays(summary_path, sp.MANUAL_BAND_ID, cfg)

    assert len(arrays.g_sx) == SCRAPE_POINT_COUNT
    assert len(arrays.g_sy) == SCRAPE_POINT_COUNT
    assert len(arrays.g_cx) == SCRAPE_POINT_COUNT
    assert arrays.pass_count == max(1, cfg.scrape.num_passes)
    assert len(arrays.pass_z_list) == arrays.pass_count
    # 非退化: 路径在 2D 上真正铺开(矩形区 auto-columns=200/per_col=2, 故 g_sy 仅取上下沿两值,
    # 判据应是 XY 跨度而非离散值个数 —— 200 列蛇形是合法覆盖)。
    assert max(arrays.g_sx) - min(arrays.g_sx) > 50.0
    assert max(arrays.g_sy) - min(arrays.g_sy) > 50.0
    # 区域 cm bbox 为 [2.5,17.5]²; lower-left/plate_origin=0 下 mm=cm*10 → 落在 [20,180]
    assert min(arrays.g_sx) >= 20.0 - 1.0 and max(arrays.g_sx) <= 180.0 + 1.0
    assert all(math.isfinite(v) for v in arrays.g_sx + arrays.g_sy)


def test_machine_mm_to_px_lands_back_in_plate_bbox(tmp_path):
    """预览逆变换: 生成路径的 mm → px 应落回板像素框内(所见即所跑)。"""
    contour_cm = sp.polygon_to_contour_cm(
        REGION_PX, plate_size_cm=PLATE_SIZE_CM, plate_bbox_px=PLATE_BBOX,
    )
    summary_path = sp.write_manual_summary(contour_cm, tmp_path, plate_bbox_px=PLATE_BBOX)
    cfg = GCodeCfg(path_strategy="contour")
    arrays = generate_scrape_arrays(summary_path, sp.MANUAL_BAND_ID, cfg)

    pts_mm = list(zip(arrays.g_sx, arrays.g_sy))
    px = sp.machine_mm_to_px(pts_mm, cfg, PLATE_BBOX, PLATE_SIZE_CM)
    x0, y0, w, h = PLATE_BBOX["x"], PLATE_BBOX["y"], PLATE_BBOX["w"], PLATE_BBOX["h"]
    for u, v in px:
        assert x0 - 5 <= u <= x0 + w + 5
        assert y0 - 5 <= v <= y0 + h + 5


def test_machine_mm_to_cm_inverts_to_machine_under_flips():
    """machine_mm_to_cm 应是 cnc_path._to_machine 的逆(覆盖翻转角)。"""
    from eit_ptlc.controller.cnc_path import _to_machine

    for corner in ("lower-left", "top-right", "top-left", "bottom-right"):
        cfg = GCodeCfg(origin_corner=corner, plate_origin_x=12.0, plate_origin_y=34.0)
        flip_x, flip_y = sp._flip_from_corner(corner)
        cm_in = [(3.0, 7.0), (15.5, 1.25)]
        mm = [_to_machine(x, y, cfg.plate_origin_x, cfg.plate_origin_y, flip_x, flip_y)
              for x, y in cm_in]
        cm_back = sp.machine_mm_to_cm(mm, cfg)
        for (x0, y0), (x1, y1) in zip(cm_in, cm_back):
            assert _approx(x0, x1, 1e-3) and _approx(y0, y1, 1e-3)


def test_triangle_three_points_is_accepted(tmp_path):
    """#8: 三角形(3 点)是合法多边形; polygon_to_contour_cm 不再要求 ≥4 点, 且产出非退化 400 点路径。"""
    triangle = [(150.0, 100.0), (450.0, 100.0), (300.0, 400.0)]
    contour = sp.polygon_to_contour_cm(triangle, plate_size_cm=PLATE_SIZE_CM, plate_bbox_px=PLATE_BBOX)
    assert len(contour) == 3
    summary_path = sp.write_manual_summary(contour, tmp_path, plate_bbox_px=PLATE_BBOX)
    arrays = generate_scrape_arrays(summary_path, sp.MANUAL_BAND_ID, GCodeCfg())
    assert len(arrays.g_sx) == SCRAPE_POINT_COUNT


def test_triangle_contour_strategy_hugs_shape_not_bbox(tmp_path):
    """T1.2/#2: 生产 contour 策略下, 3 点三角形手绘必须**贴合三角形**而非静默退化成外接矩形。

    退化成 bbox 蛇形会把刀走到三角形外的角区 → 刮到相邻带/交叉污染。根因是 cnc_path 的
    `contour.shape[0] < 4` 守卫把 3 点 contour 丢成 None → contour 策略回落 bbox (扫描线本身
    对三角形鲁棒, 见 _sample_contour_y_scanline)。断言: contour 策略下刮取点几乎全在三角形内,
    且显著优于 bbox 蛇形对照 (证明"贴合"非平凡, 非两条路径都在刮 bbox)。
    """
    triangle_px = [(150.0, 100.0), (450.0, 100.0), (300.0, 400.0)]
    contour_cm = sp.polygon_to_contour_cm(
        triangle_px, plate_size_cm=PLATE_SIZE_CM, plate_bbox_px=PLATE_BBOX,
    )
    assert len(contour_cm) == 3
    summary_path = sp.write_manual_summary(contour_cm, tmp_path, plate_bbox_px=PLATE_BBOX)

    cfg_contour = GCodeCfg(path_strategy="contour")
    arr_c = generate_scrape_arrays(summary_path, sp.MANUAL_BAND_ID, cfg_contour)
    pts_c = sp.machine_mm_to_cm(list(zip(arr_c.g_sx, arr_c.g_sy)), cfg_contour)
    inside_c = sum(_bary_inside(p, contour_cm) for p in pts_c) / len(pts_c)

    cfg_bbox = GCodeCfg(path_strategy="boustrophedon")
    arr_b = generate_scrape_arrays(summary_path, sp.MANUAL_BAND_ID, cfg_bbox)
    pts_b = sp.machine_mm_to_cm(list(zip(arr_b.g_sx, arr_b.g_sy)), cfg_bbox)
    inside_b = sum(_bary_inside(p, contour_cm) for p in pts_b) / len(pts_b)

    # contour: 仅 x_min/x_max 两端退化列落在形外, 占比极小 → ≥95% 贴形 (实测 ~99.5%)
    assert inside_c >= 0.95, f"contour 策略应贴合三角形, 但仅 {inside_c:.1%} 刮取点在形内 (疑静默退化 bbox)"
    # 对照 bbox 蛇形约 ~52% 贴形 (三角形约占外接矩形一半); 二者接近即 contour 也在刮 bbox
    assert inside_c - inside_b >= 0.30, (
        f"contour({inside_c:.1%}) 必须显著优于 bbox 蛇形({inside_b:.1%}); 接近 = contour 未真正贴形"
    )
