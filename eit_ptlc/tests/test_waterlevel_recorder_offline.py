"""液位单通道原始录制器离线测试 (无设备)
===========================================
功能:
    monkeypatch 录制器的 HTTP 拉帧 (_grab) 为合成 JPEG 帧 (cv2.imencode 小 numpy 图),
    跑 start → 录几帧 → stop, 验证:
      - AVI 落盘且能被 OpenCV 重开、逐帧读出 (帧数与录制一致)
      - 旁挂 .jsonl 有 N 行带真实时间戳
      - 旁挂 .meta.json 结构完整 (含起止时刻/帧数/标定快照)
      - 模块级 replay() 能重开 AVI+jsonl 逐帧 yield, 帧数一致
      - start/stop 幂等; status 反映活跃录制

运行 (standalone):
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_recorder_offline
运行 (pytest):
    python -m pytest eit_ptlc/tests/test_waterlevel_recorder_offline.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from eit_ptlc.controller.waterlevel_recorder import WaterLevelRecorder, replay

_W, _H = 64, 48


def _jpeg_bytes():
    """合成一张带结构的 JPEG 帧 (质量 70, 与生产 /frame 端点同档)。"""
    arr = np.zeros((_H, _W, 3), np.uint8)
    arr[:, : _W // 2] = (40, 90, 200)   # 左半着色, 造点内容避免全黑
    ok, buf = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    assert ok, "imencode 失败"
    return buf


def _run() -> int:
    failures: list[str] = []
    tally = {"n": 0}

    def check(name: str, cond: bool, detail: str = "") -> None:
        tally["n"] += 1
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    buf = _jpeg_bytes()

    def fake_grab(_client, _ch):
        # 与真 _grab 同解码路径 (imdecode), 但帧源为合成 JPEG → 离线无设备
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)

    # 注入的标定快照桩: 验证 calib 快照能流进 meta (bootstrap 用同款注入读 detect service)
    def calib_fn(ch: int):
        return {"channel": ch, "calibrated": True}

    with tempfile.TemporaryDirectory() as td:
        rec = WaterLevelRecorder("127.0.0.1", 7070, cap_fps=25,
                                 cap_width=_W, cap_height=_H,
                                 recordings_dir=Path(td), calibration_snapshot=calib_fn)
        rec._grab = fake_grab   # monkeypatch HTTP 拉帧 → 合成帧

        path = rec.start(3, sample_id="unittest")
        check("start_returns_path", isinstance(path, str) and path.endswith(".avi"), path)
        check("start_idempotent", rec.start(3, sample_id="unittest") == path,
              "重复 start 应幂等返回同路径")

        st = rec.status()
        check("status_active",
              len(st["recordings"]) == 1 and st["recordings"][0]["channel"] == 3
              and st["recordings"][0]["recording"] is True, str(st))

        time.sleep(0.6)          # ~15 帧 @25fps
        summary = rec.stop(3)

        n = int(summary.get("frame_count", 0))
        check("recorded_a_few_frames", n >= 3, f"仅录到 {n} 帧")
        check("stop_summary_shape",
              summary.get("stopped") is True and summary.get("recording") is False, str(summary))
        check("summary_dims_fps",
              summary.get("width") == _W and summary.get("height") == _H
              and summary.get("fps") == 25.0, str(summary))
        check("status_empty_after_stop", rec.status()["recordings"] == [], str(rec.status()))

        avi = Path(path)
        jsonl = avi.with_suffix(".jsonl")
        meta = Path(str(avi.with_suffix("")) + ".meta.json")

        # 1) AVI 存在且能被 OpenCV 重开、逐帧读出
        check("avi_exists", avi.is_file(), str(avi))
        cap = cv2.VideoCapture(str(avi))
        opened = cap.isOpened()
        read_n = 0
        while opened:
            ok, fr = cap.read()
            if not ok or fr is None:
                break
            read_n += 1
        cap.release()
        check("avi_reopenable", opened, "VideoCapture 打不开")
        check("avi_frame_count", read_n == n, f"AVI {read_n} 帧 vs 录 {n} 帧")

        # 2) jsonl N 行带真实时间戳
        lines = [ln for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
        check("jsonl_line_count", len(lines) == n, f"{len(lines)} 行 vs {n} 帧")
        now = time.time()
        ts_ok = True
        for i, ln in enumerate(lines):
            d = json.loads(ln)
            if (d.get("i") != i or not isinstance(d.get("t"), (int, float))
                    or not (now - 3600 < float(d["t"]) <= now + 5)):
                ts_ok = False
                break
        check("jsonl_timestamps", ts_ok, "行序号/时间戳不符预期")

        # 3) meta.json 结构完整
        m = json.loads(meta.read_text(encoding="utf-8"))
        need = {"channel", "sample_id", "width", "height", "fps",
                "started_at", "stopped_at", "frame_count", "calibration_snapshot"}
        check("meta_keys", need.issubset(m.keys()), str(sorted(m.keys())))
        check("meta_values",
              m.get("channel") == 3 and m.get("sample_id") == "unittest"
              and m.get("frame_count") == n and m.get("stopped_at") >= m.get("started_at"), str(m))
        check("meta_calibration_snapshot",
              m.get("calibration_snapshot") == {"channel": 3, "calibrated": True},
              str(m.get("calibration_snapshot")))

        # 4) replay 逐帧回放, 帧数一致
        replayed = list(replay(avi))
        check("replay_frame_count", len(replayed) == n, f"replay {len(replayed)} vs {n}")
        if replayed:
            fr0, ts0 = replayed[0]
            check("replay_frame_shape", fr0.shape[:2] == (_H, _W), str(fr0.shape))
            check("replay_ts_float", isinstance(ts0, float), str(ts0))

        # 4b) replay stride 倍速抽帧: 帧数 = ceil(n/stride), 时间戳按真实帧序对齐
        strided = list(replay(avi, stride=3))
        want = (n + 2) // 3
        check("replay_stride_count", len(strided) == want, f"{len(strided)} vs {want}")
        if strided and replayed:
            check("replay_stride_ts0", strided[0][1] == replayed[0][1],
                  f"{strided[0][1]} vs {replayed[0][1]}")
        if len(strided) >= 2 and len(replayed) >= 4:
            check("replay_stride_ts_align", strided[1][1] == replayed[3][1],
                  f"{strided[1][1]} vs {replayed[3][1]}")

        # 5) 停非活跃通道 / stop_all → 幂等不报错
        again = rec.stop(3)
        check("stop_idempotent",
              again.get("recording") is False and again.get("stopped") is False, str(again))
        rec.stop_all()   # 无活跃, 应静默

    print(f"\n共 {tally['n']} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def test_waterlevel_recorder_offline():
    """pytest 入口: 复用 _run 的逐项断言 (失败明细见 stdout)。"""
    assert _run() == 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
