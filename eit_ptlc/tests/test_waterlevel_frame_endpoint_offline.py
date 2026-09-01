"""香橙派单帧端点离线测试 (HTTP 往返, fake detector)
=====================================================
功能:
    验证 mjpeg_streamer 新增的 GET /frame/ch{N} 端点 (P1):
      - 有帧通道 → 200 image/jpeg, 可 imdecode 回原尺寸
      - 无帧通道 → 503; 越界通道 → 404; 非法编号 → 400

    用 importlib 从文件路径加载 mjpeg_streamer.py (该目录是香橙派"独立载荷",
    不作为 eit_ptlc 子包 import)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_waterlevel_frame_endpoint_offline
"""

from __future__ import annotations

import http.client
import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np

_PAYLOAD = (Path(__file__).resolve().parent.parent
            / "driver" / "water_level_payload" / "mjpeg_streamer.py")
_spec = importlib.util.spec_from_file_location("mjpeg_streamer", _PAYLOAD)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
MJPEGStreamer = _mod.MJPEGStreamer


class _FakeDetector:
    def __init__(self, frame):
        self._frame = frame

    def get_frame(self):
        return None if self._frame is None else self._frame.copy()


class _FakeManager:
    def __init__(self, detectors):
        self.channels = detectors
        self.num_channels = len(detectors)


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, resp.getheader("Content-Type"), body
    finally:
        conn.close()


def _run() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"PASS {name}")
        else:
            failures.append(name)
            print(f"FAIL {name}: {detail}")

    # CH1 有帧 (48 高 × 64 宽 BGR 渐变), CH2 无帧
    frame = np.zeros((48, 64, 3), np.uint8)
    frame[:, :32] = (200, 200, 200)
    mgr = _FakeManager([_FakeDetector(frame), _FakeDetector(None)])

    streamer = MJPEGStreamer(port=0, multi_channel_manager=mgr)
    streamer.start()
    port = streamer._server.server_address[1]
    try:
        # 有帧 → 200 image/jpeg, 可解码回原尺寸
        status, ctype, body = _get(port, "/frame/ch1")
        check("ch1_status_200", status == 200, str(status))
        check("ch1_content_type", ctype == "image/jpeg", str(ctype))
        dec = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        check("ch1_decodable", dec is not None and dec.shape == (48, 64, 3),
              None if dec is None else str(dec.shape))

        # 无帧 → 503
        status, _, _ = _get(port, "/frame/ch2")
        check("ch2_no_frame_503", status == 503, str(status))

        # 越界通道 → 404
        status, _, _ = _get(port, "/frame/ch9")
        check("ch9_out_of_range_404", status == 404, str(status))

        # 非法编号 → 400
        status, _, _ = _get(port, "/frame/chX")
        check("chX_bad_request_400", status == 400, str(status))
    finally:
        streamer.shutdown()

    total = 6
    print(f"\n共 {total} 用例, 失败 {len(failures)}")
    return 1 if failures else 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    return _run()


if __name__ == "__main__":
    sys.exit(main())
