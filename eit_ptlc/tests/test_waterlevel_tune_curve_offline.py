"""整定台曲线渲染/纯逻辑离线测试 (需 cv2+matplotlib, 无 GUI 窗口)
====================================================================
'c' 卡死根治的可测半: Figure(Agg)→BGR ndarray 形状正确; 其余 (事件泵/
Esc 中断/imshow) 为 GUI 行为, 见 plan 的人工验证清单。

运行 (pytest):
    E:/Anaconda/envs/platformupper/python.exe -m pytest eit_ptlc/tests/test_waterlevel_tune_curve_offline.py -q
"""

from __future__ import annotations

import numpy as np
import pytest

from eit_ptlc.tools.wl_replay_tune import _fig_to_bgr, _mark_lines, _parse_marks_arg


def test_fig_to_bgr_shape_and_dtype():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(2, 1), dpi=50)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.plot([0, 1], [0, 1])
    img = _fig_to_bgr(fig)
    assert img.shape == (50, 100, 3) and img.dtype == np.uint8


def test_parse_marks_arg():
    assert _parse_marks_arg("5,4,3,2,1") == (5.0, 4.0, 3.0, 2.0, 1.0)
    assert _parse_marks_arg("6, 4, 2") == (6.0, 4.0, 2.0)
    for bad in ("5,4.5", "0,3", "10,3", "5,5", "", "abc"):
        with pytest.raises(SystemExit):
            _parse_marks_arg(bad)


def test_mark_lines():
    series = {"t0": 100.0}
    marks = {"events": [{"cm": 5.0, "frame_idx": 10, "ts": 110.0},
                        {"cm": 3.0, "frame_idx": 50, "ts": None}]}   # ts 缺 → 跳过
    assert _mark_lines(series, marks) == [(10.0, "5cm")]
    assert _mark_lines({"t0": None}, marks) == []                    # 无墙钟 → 不叠线


def test_run_series_contract(tmp_path):
    """_run_series 契约冒烟: 合成小 AVI + jsonl → 抽帧整段跑 → 断言返回 dict 契约。

    堵住放走 replay(stride=) 半边的测试缺口 (F1/F2): 若 recorder 侧未收编 stride,
    此处 stride=2 会 TypeError 而红。interactive=False 关闭 GUI 事件泵与 Esc 中断,
    故 headless (opencv-python-headless 无 highgui) 下不触碰 cv2.waitKey。
    """
    from math import ceil

    import cv2
    import numpy as np

    from eit_ptlc.controller.waterlevel_detector import (
        ChannelCalibration,
        WaterLevelDetectParams,
    )
    from eit_ptlc.tools.wl_replay_tune import _run_series

    w, h, n = 64, 48, 6
    avi = tmp_path / "ch1_20260717_000000.avi"
    writer = cv2.VideoWriter(str(avi), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (w, h))
    assert writer.isOpened(), "VideoWriter 打不开 (缺 MJPG 编解码)"
    frames = []
    for i in range(n):
        arr = np.zeros((h, w, 3), np.uint8)
        arr[:, : w // 2] = (40, 90, 200)                        # 左半着色, 造内容
        arr[h // 3:, : (i + 1) * w // (n + 1)] = (10, 10, 10)   # 逐帧推进的暗区
        writer.write(arr)
        frames.append(arr)
    writer.release()
    # 旁挂 jsonl: 每行 {"i": i, "t": 100.0 + i} (replay 按帧序取时间戳)
    avi.with_suffix(".jsonl").write_text(
        "".join(f'{{"i": {i}, "t": {100.0 + i}}}\n' for i in range(n)),
        encoding="utf-8")

    calib = ChannelCalibration(roi_frac=(0.25, 0.1, 0.5, 0.8),
                               flow_direction="left_to_right")
    params = WaterLevelDetectParams()                            # 默认 (log)
    series = _run_series(avi, calib, params, frames[0], stride=2, n_total=n,
                         interactive=False)
    assert series is not None                                    # interactive=False 不中断 → 非 None
    assert set(series) == {"ts", "pct", "front", "diff", "drifts", "gains",
                           "valid", "frozen_at", "guard_reason", "t0"}
    assert len(series["ts"]) == ceil(n / 2)                      # stride=2 抽帧
    assert series["t0"] == 100.0                                 # 首采样帧墙钟
