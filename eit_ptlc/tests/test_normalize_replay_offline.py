"""normalize_applied 持久化 + replay_normalization 帧回放 (契约 C-1/C-3)。

错帧坑: auto_rectify_tilt 角度从当张图现测且只打 stdout; 刮后板绿掩膜已变,
重测角度不同 → 对账叠加错帧被误读成物理 bias。故: 分析时落实际应用参数,
回放只消费参数、禁重新检测。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

_VIEW_DIR = Path(__file__).resolve().parents[2] / "View" / "pTLC_Viewing"
if str(_VIEW_DIR) not in sys.path:
    sys.path.insert(0, str(_VIEW_DIR))

cv2 = pytest.importorskip("cv2")
import tlc_analyze as ta  # noqa: E402


def _img(w=200, h=160):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (30, 20), (170, 140), (60, 200, 60), -1)  # 绿"板"
    return img


def test_normalize_returns_applied_dict_identity():
    before, after, applied = ta._normalize_plate_image(_img(), _img(), orientation="rot0")
    assert applied == {
        "orientation": "rot0", "tilt_deg": 0.0,
        "rotation_center": "image_center", "frame_size": [200, 160],
    }


def test_normalize_applied_records_fixed_tilt_and_rot90():
    _, after, applied = ta._normalize_plate_image(
        _img(), _img(), orientation="rot90cw", fixed_rotation_deg=2.0, min_angle_deg=0.5,
    )
    assert applied["orientation"] == "rot90cw"
    assert applied["tilt_deg"] == 2.0
    # rot90 后帧宽高互换
    assert applied["frame_size"] == [160, 200]
    assert [after.shape[1], after.shape[0]] == [160, 200]


def test_normalize_applied_fixed_below_threshold_is_zero():
    _, _, applied = ta._normalize_plate_image(
        _img(), _img(), fixed_rotation_deg=0.2, min_angle_deg=0.5,
    )
    assert applied["tilt_deg"] == 0.0


def test_write_manual_summary_inherits_normalize_applied(tmp_path):
    from eit_ptlc.controller.sketch_path import write_manual_summary
    napplied = {"orientation": "rot0", "tilt_deg": 0.0,
                "rotation_center": "image_center", "frame_size": [200, 160]}
    sp = write_manual_summary(
        [(1.0, 1.0), (5.0, 1.0), (5.0, 3.0)], tmp_path,
        plate_bbox_px={"x": 0, "y": 0, "w": 100, "h": 100},
        normalize_applied=napplied,
    )
    assert json.loads(sp.read_text(encoding="utf-8"))["normalize_applied"] == napplied


def _write_case(tmp_path, applied, manual_rectify=None, img=None):
    raw = tmp_path / "scraped.jpg"
    cv2.imwrite(str(raw), _img() if img is None else img)
    summary = {"ok": True, "normalize_applied": applied}
    if manual_rectify is not None:
        summary["manual_rectify"] = manual_rectify
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps(summary), encoding="utf-8")
    return raw, sp


def test_replay_is_deterministic_and_matches_normalize(tmp_path):
    # 同参数: _normalize_plate_image 与 replay 输出逐像素一致 (同源 by construction)
    src = _img()
    _, expect, applied = ta._normalize_plate_image(
        src.copy(), src.copy(), orientation="rot180", fixed_rotation_deg=1.5, min_angle_deg=0.5,
    )
    raw, sp = _write_case(tmp_path, applied, img=src)
    out1 = ta.replay_normalization(raw, sp, tmp_path / "n1.png")
    out2 = ta.replay_normalization(raw, sp, tmp_path / "n2.png")
    got1 = cv2.imread(str(out1)); got2 = cv2.imread(str(out2))
    assert np.array_equal(got1, got2)                       # 确定性
    # 与在线归一化一致 (jpg 输入有量化损失, 允许极小差)
    assert got1.shape == expect.shape
    assert float(np.mean(np.abs(got1.astype(int) - expect.astype(int)))) < 3.0


def test_replay_missing_applied_raises(tmp_path):
    raw = tmp_path / "scraped.jpg"; cv2.imwrite(str(raw), _img())
    sp = tmp_path / "summary.json"
    sp.write_text(json.dumps({"ok": True}), encoding="utf-8")   # 旧 summary 无字段
    with pytest.raises(ValueError):
        ta.replay_normalization(raw, sp, tmp_path / "out.png")


def test_replay_frame_size_mismatch_raises(tmp_path):
    applied = {"orientation": "rot0", "tilt_deg": 0.0,
               "rotation_center": "image_center", "frame_size": [999, 999]}
    raw, sp = _write_case(tmp_path, applied)
    with pytest.raises(ValueError):
        ta.replay_normalization(raw, sp, tmp_path / "out.png")


def test_replay_applies_manual_rectify_second_stage(tmp_path):
    applied = {"orientation": "rot0", "tilt_deg": 0.0,
               "rotation_center": "image_center", "frame_size": [200, 160]}
    manual = {"plate_corners_px": [[30, 20], [170, 20], [170, 140], [30, 140]],
              "px_per_cm": 4, "frame_size": [80, 80]}
    # 非对称图案: 仅在 manual 角点"左上角"([30,20]) 附近画白块, 其余全黑 —— 角序回归(如 dst 翻转)
    # 会把白块搬到别的角, 静默通过被这一断言捕获。
    src = np.zeros((160, 200, 3), dtype=np.uint8)
    cv2.rectangle(src, (30, 20), (75, 65), (255, 255, 255), -1)
    raw, sp = _write_case(tmp_path, applied, manual_rectify=manual, img=src)
    out = cv2.imread(str(ta.replay_normalization(raw, sp, tmp_path / "out.png")))
    assert [out.shape[1], out.shape[0]] == [80, 80]         # 二级回放到手动矫正帧
    # 左上角白块回放后应落在矫正帧 (0,0) 角邻域, 对角(右下)仍黑 —— 钉死角点映射方向
    assert float(out[0:20, 0:20].mean()) > 120
    assert float(out[-20:, -20:].mean()) < 40
