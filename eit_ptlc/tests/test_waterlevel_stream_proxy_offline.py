"""液位 MJPEG 代理状态透传离线测试 (TestClient + 假上游)
==========================================================
功能:
    验证 GET /api/water_level/stream/{ch} 代理**原样透传上游状态码**:
      - 上游 200 → 代理 200, body 转发 (可流式)
      - 上游 503 (通道未 READY) → 代理 503, **不得**被吞成"空的 200"

    回归目标 (0708 定位): 旧实现在生成器里对非-200 只 `return`, 而 StreamingResponse
    已先发 200 → 浏览器收到"空的 200", <img> 既不 error 也不 load → 永久静默黑屏且
    不触发前端 onStreamError 重连。故单路视图开流后画面全黑、刷新/重启均无效。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_waterlevel_stream_proxy_offline.py
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app


class _FakeUpstreamHandler(BaseHTTPRequestHandler):
    """假香橙派: /stream/ch1 → 200+body, 其余通道 → 503 (模拟未 READY)。"""

    def log_message(self, *args):
        pass  # 静默

    def do_GET(self):
        if self.path.startswith("/stream/ch1"):
            body = b"--MJPEGBOUNDARY\r\nfake-jpeg-bytes\r\n"
            self.send_response(200)
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=MJPEGBOUNDARY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            msg = b"Channel not active"
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


def test_upstream_200_forwarded():
    with _Upstream() as up:
        client = _client(up.port)
        resp = client.get("/api/water_level/stream/ch1")
        assert resp.status_code == 200
        assert b"fake-jpeg-bytes" in resp.content


def test_upstream_503_propagated_not_swallowed():
    """★核心回归: 上游 503 必须透传为 503, 不能变成空的 200。"""
    with _Upstream() as up:
        client = _client(up.port)
        resp = client.get("/api/water_level/stream/ch2")
        assert resp.status_code == 503, (
            f"上游 503 被吞成 {resp.status_code} (空 body 长度={len(resp.content)}) "
            f"→ 前端永久静默黑屏")


def test_upstream_unreachable_502():
    """上游连不上 (端口无监听) → 502, 而非空 200。"""
    client = _client(port=1)  # 端口 1 无监听
    resp = client.get("/api/water_level/stream/ch1")
    assert resp.status_code == 502
