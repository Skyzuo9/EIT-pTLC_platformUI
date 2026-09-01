"""液位标记板真值标注模块离线测试 (纯函数, 无 cv2/numpy)
==========================================================
覆盖: 旁挂路径推导 / jsonl 时间戳载入 / marks 新建-打标-覆盖-取消 /
原子写盘与读回 / 缺文件与坏文件语义 / (Task 2 追加) 拟合-残差-速度-报告。

运行 (pytest):
    E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_marks_offline.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eit_ptlc.tools import wl_marks


def test_pure_stdlib():
    """全局约束守卫: wl_marks 不得依赖 cv2/numpy。"""
    src = Path(wl_marks.__file__).read_text(encoding="utf-8")
    assert "import cv2" not in src
    assert "import numpy" not in src


def test_sidecar_paths(tmp_path):
    avi = tmp_path / "ch3_20260717_101500.avi"
    assert wl_marks.jsonl_path(avi).name == "ch3_20260717_101500.jsonl"
    assert wl_marks.marks_path(avi).name == "ch3_20260717_101500.marks.json"
    assert wl_marks.report_path(avi).name == "ch3_20260717_101500.marks_report.json"
    assert wl_marks.curve_png_path(avi).name == "ch3_20260717_101500.curve.png"


def test_load_timestamps_tolerant(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"i": 0, "t": 100.5}\n\n{"i": 2, "t": 102.0}\n{oops\n', encoding="utf-8")
    assert wl_marks.load_timestamps(p) == {0: 100.5, 2: 102.0}
    assert wl_marks.load_timestamps(tmp_path / "missing.jsonl") == {}


def test_toggle_set_move_clear():
    m = wl_marks.new_marks(3, "a.avi", (5.0, 4.0, 3.0, 2.0, 1.0))
    assert wl_marks.toggle_event(m, 5.0, 210, 100.5) == "set"
    assert wl_marks.get_event(m, 5.0) == {"cm": 5.0, "frame_idx": 210, "ts": 100.5}
    assert wl_marks.toggle_event(m, 5.0, 250, 101.0) == "moved"      # 换帧 = 覆盖
    assert wl_marks.get_event(m, 5.0)["frame_idx"] == 250
    assert wl_marks.toggle_event(m, 5.0, 250, 101.0) == "cleared"    # 同帧重按 = 取消
    assert wl_marks.get_event(m, 5.0) is None
    wl_marks.toggle_event(m, 2.0, 731, None)                          # ts 缺 (jsonl 缺行)
    assert wl_marks.get_event(m, 2.0)["ts"] is None


def test_events_sorted_cm_desc():
    m = wl_marks.new_marks(1, "a.avi")
    wl_marks.toggle_event(m, 2.0, 731, 300.0)
    wl_marks.toggle_event(m, 5.0, 210, 100.0)
    assert [e["cm"] for e in m["events"]] == [5.0, 2.0]


def test_save_load_roundtrip_atomic(tmp_path):
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 210, 100.5)
    p = tmp_path / "a.marks.json"
    wl_marks.save_marks(p, m)
    assert not list(tmp_path.glob("*.tmp"))          # 原子写不留临时文件
    m2 = wl_marks.load_marks(p)
    assert m2["schema"] == wl_marks.MARKS_SCHEMA
    assert m2["channel"] == 3 and m2["events"] == m["events"]
    assert m2["updated_at"]                          # save 时已刷


def test_load_marks_missing_and_corrupt(tmp_path):
    assert wl_marks.load_marks(tmp_path / "none.marks.json") is None
    bad = tmp_path / "bad.marks.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        wl_marks.load_marks(bad)
    wrong = tmp_path / "wrong.marks.json"
    wrong.write_text(json.dumps({"schema": "other/v9"}), encoding="utf-8")
    with pytest.raises(ValueError):
        wl_marks.load_marks(wrong)


# ---- Task 2: 计算层 ----

def _perfect_pairs():
    """front = −4·d + 90 的理想直线 (5..1cm)。"""
    return [(5.0, 70.0), (4.0, 74.0), (3.0, 78.0), (2.0, 82.0), (1.0, 86.0)]


def test_linear_fit_perfect_and_invert():
    fit = wl_marks.linear_fit(_perfect_pairs())
    assert abs(fit["slope_pct_per_cm"] + 4.0) < 1e-9
    assert abs(fit["intercept_pct"] - 90.0) < 1e-9
    assert fit["n"] == 5 and fit["r2"] > 0.999999
    assert abs(wl_marks.invert_fit(fit, 80.0) - 2.5) < 1e-9


def test_linear_fit_degenerate():
    assert wl_marks.linear_fit([]) is None
    assert wl_marks.linear_fit([(5.0, 70.0)]) is None                 # 1 点不拟合
    assert wl_marks.linear_fit([(5.0, 70.0), (5.0, 71.0)]) is None    # 同 cm 两点
    fit2 = wl_marks.linear_fit([(5.0, 70.0), (3.0, 78.0)])            # 2 点: 有拟合无 R²
    assert fit2["n"] == 2 and fit2["r2"] is None
    with pytest.raises(ValueError):
        wl_marks.invert_fit({"slope_pct_per_cm": 0.0, "intercept_pct": 50.0}, 60.0)


def test_residuals():
    pairs = [(5.0, 70.0), (3.0, 78.5), (2.0, 82.0)]
    fit = {"slope_pct_per_cm": -4.0, "intercept_pct": 90.0, "r2": None, "n": 3}
    res = {r["cm"]: r["residual"] for r in wl_marks.residuals(pairs, fit)}
    assert abs(res[5.0]) < 1e-9 and abs(res[3.0] - 0.5) < 1e-9


def test_segment_velocities_gaps_and_missing_ts():
    # 只标 5/3/2 (缺 4、1): 段按实际 Δcm; 5→3 = 2cm/120s = 1.0 cm/min
    events = [{"cm": 5.0, "frame_idx": 10, "ts": 100.0},
              {"cm": 3.0, "frame_idx": 50, "ts": 220.0},
              {"cm": 2.0, "frame_idx": 80, "ts": 300.0}]
    segs = wl_marks.segment_velocities(events)
    assert segs[0]["from_cm"] == 5.0 and segs[0]["to_cm"] == 3.0
    assert abs(segs[0]["cm_per_min"] - 1.0) < 1e-9 and segs[0]["dt_s"] == 120.0
    assert abs(segs[1]["cm_per_min"] - 0.75) < 1e-9
    # ts 缺失段跳过并注明
    events[1]["ts"] = None
    segs2 = wl_marks.segment_velocities(events)
    assert segs2[0]["skipped"] == "ts_missing" and segs2[1]["skipped"] == "ts_missing"
    # dt<=0 (时序倒挂) 跳过
    bad = [{"cm": 5.0, "frame_idx": 1, "ts": 200.0},
           {"cm": 4.0, "frame_idx": 2, "ts": 100.0}]
    assert "skipped" in wl_marks.segment_velocities(bad)[0]


def test_build_report_full_path():
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 10, 100.0)
    wl_marks.toggle_event(m, 3.0, 50, 220.0)
    wl_marks.toggle_event(m, 2.0, 80, 300.0)     # 缺 4cm、1cm
    fronts = {5.0: 70.0, 3.0: 78.0, 2.0: 82.0}   # 落在 front=−4d+90 上
    rep = wl_marks.build_report(m, fronts, calib_snapshot={"x": 1},
                                params_snapshot={"y": 2}, ref_frame_idx=42)
    assert rep["ref_frame_idx"] == 42            # 现算 front 所用参考帧, 报告可复现
    assert wl_marks.build_report(m, fronts)["ref_frame_idx"] is None   # 不传 → None
    assert rep["schema"] == wl_marks.REPORT_SCHEMA
    assert rep["fit"]["n"] == 3 and abs(rep["fit"]["slope_pct_per_cm"] + 4.0) < 1e-6
    assert rep["r2_warning"] is False
    assert rep["front_source"] == "single_frame"
    assert rep["marks"][0]["cm"] == 5.0 and abs(rep["marks"][0]["residual"]) < 1e-6
    # 建议: 最靠板顶可用段 3→2cm (0.75 cm/min) × |−4| %/cm ÷ 60 = 0.05 %/s
    assert abs(rep["suggestion"]["speed_pct_per_s"] - 0.05) < 1e-6
    assert rep["suggestion"]["segment"] == [3.0, 2.0]
    txt = wl_marks.format_report(rep)
    assert "d(front%)" in txt and "cm/min" in txt and "就位时间" in txt


def test_build_report_invalid_front_excluded_and_no_reference():
    m = wl_marks.new_marks(3, "a.avi")
    wl_marks.toggle_event(m, 5.0, 10, 100.0)
    wl_marks.toggle_event(m, 3.0, 50, 220.0)
    # 某帧检测 invalid → front None → 不入拟合
    rep = wl_marks.build_report(m, {5.0: 70.0, 3.0: None})
    assert rep["fit"] is None                      # 只剩 1 有效点
    # 全 None (未设参考帧) → 无拟合, 文本给提示
    rep2 = wl_marks.build_report(m, {5.0: None, 3.0: None})
    assert rep2["fit"] is None
    assert "无拟合" in wl_marks.format_report(rep2)


def test_format_hud_line():
    m = wl_marks.new_marks(3, "a.avi")
    for cm, f in ((5.0, 210), (4.0, 388), (3.0, 560), (2.0, 731)):
        wl_marks.toggle_event(m, cm, f, None)
    assert wl_marks.format_hud_line(m) == \
        "marks: 5cm@f210 4cm@f388 3cm@f560 2cm@f731 (1cm 缺)"
    empty = wl_marks.new_marks(3, "a.avi", (5.0, 3.0))
    assert wl_marks.format_hud_line(empty) == "marks: (无) (5cm/3cm 缺)"
