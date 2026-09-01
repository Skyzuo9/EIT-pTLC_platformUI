"""离线测: rf_spot_check 调试叠加 (合成图路径)。"""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from eit_ptlc.tools import rf_spot_check
from eit_ptlc.controller import rf_measure


def _synth(w=400, h=600, spots_uv=((0.5, 0.5),)):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 1] = 200
    for (u, v) in spots_uv:
        cv2.circle(img, (int(u * w), int(v * h)), 12, (0, 40, 0), -1)
    return img, {"x": 0, "y": 0, "w": w, "h": h}


def test_render_overlay_returns_same_shape():
    img, bbox = _synth()
    res = rf_measure.analyze_rf(img, bbox, origin_frac=0.9, d_f=0.8)
    overlay = rf_spot_check.render_overlay(img, bbox, res, origin_frac=0.9)
    assert overlay.shape == img.shape
    # 叠加应改变部分像素 (画了东西)
    assert bool((overlay != img).any())
