"""plate_coords 单一真源 — 往返恒等 + 黄金值。

坐标映射公式此前有 3 份拷贝(vision_controller 闭包 / sketch_path / cnc_preview);
收编后本套件是唯一实现的守卫: px↔cm 与 machine↔cm 往返恒等 × 4 种 origin_corner。
"""

from __future__ import annotations

import math
import random

import pytest

from eit_ptlc.config.models import GCodeCfg
from eit_ptlc.controller import plate_coords as pc

_BBOX = {"x": 120.0, "y": 80.0, "w": 900.0, "h": 880.0}
_CORNERS = [(130.0, 90.0), (1010.0, 105.0), (1000.0, 955.0), (118.0, 940.0)]  # 左上,右上,右下,左下
_SIZE = 20.0


def _rand_cm(n=20, seed=7):
    rng = random.Random(seed)
    return [(rng.uniform(0.0, _SIZE), rng.uniform(0.0, _SIZE)) for _ in range(n)]


def test_affine_roundtrip_px_cm_px():
    cm = _rand_cm()
    px = pc.cm_to_px_affine(cm, _BBOX, _SIZE)
    back = pc.px_to_cm_affine(px, _BBOX, _SIZE)
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-9) and math.isclose(y0, y1, abs_tol=1e-9)


def test_corners_roundtrip_px_cm_px():
    cm = _rand_cm(seed=11)
    px = pc.cm_to_px_corners(cm, _CORNERS, _SIZE)
    back = pc.px_to_cm_corners(px, _CORNERS, _SIZE)
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-6) and math.isclose(y0, y1, abs_tol=1e-6)


# origin_corner 取 cnc_path._CORNER_FLIP 的 4 个真源键(命名不对称: lower/top/bottom 混用),
# 覆盖全部翻转组合; 非法名会在 _flip_from_corner 直接抛 ValueError。
@pytest.mark.parametrize("corner", ["lower-left", "top-right", "top-left", "bottom-right"])
def test_machine_roundtrip_all_origin_corners(corner):
    cfg = GCodeCfg(origin_corner=corner, plate_origin_x=137.5, plate_origin_y=42.0)
    cm = _rand_cm(seed=13)
    from eit_ptlc.controller.cnc_path import _flip_from_corner, _to_machine
    flip_x, flip_y = _flip_from_corner(corner)
    mm = [_to_machine(x, y, cfg.plate_origin_x, cfg.plate_origin_y, flip_x, flip_y) for x, y in cm]
    back = pc.machine_mm_to_cm(mm, cfg)
    # abs_tol=1e-3 cm 容 _to_machine 的 round(mm,3)(≈5e-5 cm 量级); 翻转/符号错会差 cm 级, 仍被抓。
    for (x0, y0), (x1, y1) in zip(cm, back):
        assert math.isclose(x0, x1, abs_tol=1e-3) and math.isclose(y0, y1, abs_tol=1e-3)


def test_affine_golden_values():
    # 黄金值: cm(0,0) → bbox 左下角; cm(S,S) → bbox 右上角 (图像 y 向下)
    px = pc.cm_to_px_affine([(0.0, 0.0), (_SIZE, _SIZE)], _BBOX, _SIZE)
    assert px[0] == (120.0, 80.0 + 880.0)
    assert px[1] == (120.0 + 900.0, 80.0)


def test_cm_to_px_affine_rejects_degenerate_bbox():
    with pytest.raises(ValueError):
        pc.cm_to_px_affine([(1.0, 1.0)], {"x": 0, "y": 0, "w": 0, "h": 100}, _SIZE)
