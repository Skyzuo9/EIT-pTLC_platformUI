"""液位单帧代理契约离线测试 (TestClient + 假上游)
=====================================================
功能:
    验证 GET /api/water_level/frame/{ch} 代理契约 —— 单路实时视图改用 /frame 低频轮询
    (取代旧持久 MJPEG /stream) 后, 画面来源全押在这条路径上, 故须守住:
      - 上游 200 → 代理 200 + image/jpeg, body 原样转发
      - 上游 503 (通道未激活/无帧) → 代理 503 (透传, 不吞成空 200); 轮询下一拍自愈
      - 上游连不上 → 代理 502 (不是空 200)

    背景 (Plan B, 2026-07-09): 持久 MJPEG 流瞬态停帧后 <img> 不报错→永久冻结, 且前端看门狗
    只守首帧; 改无状态单帧轮询后, 任何一次失败 (503/502) 下一拍即重试, 天生自愈。此测试
    锁死轮询所依赖的代理状态语义 (对照 test_waterlevel_stream_proxy_offline 的 /stream 版)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_waterlevel_frame_proxy_offline.py
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    """假香橙派: /frame/ch1 → 200+jpeg, 其余通道 → 503 (模拟未激活/无帧)。"""

    def log_message(self, *args):
        pass  # 静默

    def do_GET(self):
        if self.path.startswith("/frame/ch1"):
            body = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            msg = b"No frame (channel idle or not capturing)"
            self.send_response(503)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)


class _Cfg:
    def __init__(self, ip, port):
        self.orangepi_ip = ip
        self.stream_port = port


class _Upstream:
    def __enter__(self):
        self._srv = HTTPServer(("127.0.0.1", 0), _FakeUpstreamHandler)
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._t.start()
        self.port = self._srv.server_address[1]
        return self

    def __exit__(self, *a):
        self._srv.shutdown()
        self._srv.server_close()


def _client(port) -> TestClient:
    app = create_app(ActionRegistry({}), control_mode="DEBUG")
    app.state.water_level_cfg = _Cfg("127.0.0.1", port)
    return TestClient(app)


def test_frame_upstream_200_forwarded():
    """上游有帧 200 → 代理 200 + image/jpeg, body 原样转发 (轮询正常取帧)。"""
    with _Upstream() as up:
        client = _client(up.port)
        resp = client.get("/api/water_level/frame/ch1")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"
        assert b"fake-jpeg-bytes" in resp.content


def test_frame_upstream_503_propagated_not_swallowed():
    """★核心: 无帧 503 必须透传为 503, 不能变成空的 200 (否则轮询显示假帧不自愈)。"""
    with _Upstream() as up:
        client = _client(up.port)
        resp = client.get("/api/water_level/frame/ch2")
        assert resp.status_code == 503, (
            f"上游 503 被吞成 {resp.status_code} → 轮询无法感知无帧/自愈")


def test_frame_upstream_unreachable_502():
    """上游连不上 (端口无监听) → 502, 而非空 200。"""
    client = _client(port=1)  # 端口 1 无监听
    resp = client.get("/api/water_level/frame/ch1")
    assert resp.status_code == 502
