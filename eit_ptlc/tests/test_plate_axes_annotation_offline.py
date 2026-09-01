"""板坐标系标注几何 — 黄金值 (spec 2026-07-16 §3): cm(0,0)=bbox 图像左下角, 不依赖 origin_corner。"""

from __future__ import annotations

import pytest

from eit_ptlc.controller import plate_coords as pc

BBOX = {"x": 0, "y": 0, "w": 200, "h": 200}   # 20cm 板 × 10px/cm


def test_axes_golden_values_full_frame():
    a = pc.plate_axes_annotation(BBOX, 20.0)
    assert a["origin_px"] == [0.0, 200.0]          # cm(0,0) = 图像左下角
    assert a["x_tip_px"] == [30.0, 200.0]          # cm(3,0): +x 沿图像向右
    assert a["y_tip_px"] == [0.0, 170.0]           # cm(0,3): +y 沿图像向上
    labels = [c["label"] for c in a["corners"]]
    assert labels == ["cm(0,0)", "cm(20,0)", "cm(0,20)", "cm(20,20)"]
    assert [c["px"] for c in a["corners"]] == [[0.0, 200.0], [200.0, 200.0], [0.0, 0.0], [200.0, 0.0]]


def test_axes_offset_bbox_and_small_plate():
    # 偏置 bbox(视觉分支典型): 原点=左下 (10, 10+80)=(10,90); 小板 5cm → 箭头=min(3, 0.75)=0.75cm
    a = pc.plate_axes_annotation({"x": 10, "y": 10, "w": 80, "h": 80}, 5.0)
    assert a["origin_px"] == [10.0, 90.0]
    assert a["x_tip_px"] == [22.0, 90.0]           # 0.75cm × 16px/cm = 12px
    assert a["corners"][3]["label"] == "cm(5,5)"


def test_axes_rejects_degenerate_bbox():
    with pytest.raises(ValueError):
        pc.plate_axes_annotation({"x": 0, "y": 0, "w": 0, "h": 100}, 20.0)
