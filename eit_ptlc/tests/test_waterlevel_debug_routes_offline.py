"""液位「识别」页两个只读端点的离线契约测试
==============================================
功能:
    钉死 GET /api/water_level/debug_frame/ch{N} 与 GET /api/water_level/history/{channel}
    的路由、状态码与响应形状。

为什么不用 create_sim_app:
    该装配会按真实 app.yaml 起 water_level (enabled: true), 可能真去连香橙派/MQTT。
    这两个端点的逻辑只依赖 app.state.water_level_detect, 故用裸 FastAPI + 桩对象直测,
    既零副作用也把断言聚焦在路由层本身。

重点覆盖 503 分支: 现场排查时"通道未激活"与"尚未产出检测帧"是两种完全不同的处置
(前者去开流/查 max_active, 后者只需等一轮), 文案混淆会把人带偏。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eit_ptlc.api.water_level_routes import register_water_level_routes


class _StubDetect:
    """拉帧检测服务桩: 只实现两个端点用到的三个只读方法。"""

    def __init__(self, jpeg=None, active=(2,), points=None):
        self._jpeg = jpeg
        self._active = list(active)
        self._points = points if points is not None else []
        self.history_calls = []
        self.frame_calls = []

    def debug_frame_jpeg(self, channel, inplace_overlay=True):
        self.frame_calls.append((channel, inplace_overlay))
        return self._jpeg

    def history(self, channel, limit):
        self.history_calls.append((channel, limit))
        return self._points

    def snapshot(self):
        return {"channels": {}, "active": self._active, "reachable_any": True}


def _client(detect) -> TestClient:
    app = FastAPI()
    register_water_level_routes(app)
    app.state.water_level_detect = detect
    app.state.water_level_client = None
    app.state.water_level_ctrl = None
    app.state.water_level_cfg = None
    app.state.water_level_recorder = None
    app.state.orangepi = None
    return TestClient(app)


class TestDebugFrame:
    def test_returns_jpeg_when_rendered(self):
        c = _client(_StubDetect(jpeg=b"\xff\xd8\xff\xe0fake-jpeg"))
        r = c.get("/api/water_level/debug_frame/ch2")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "no-cache"     # 不缓存, 否则画面会冻住
        assert r.content == b"\xff\xd8\xff\xe0fake-jpeg"

    def test_503_and_says_inactive_when_channel_not_active(self):
        c = _client(_StubDetect(jpeg=None, active=[1, 3]))
        r = c.get("/api/water_level/debug_frame/ch2")
        assert r.status_code == 503
        assert "未激活" in r.json()["detail"], "未激活的通道文案要指向开流, 别和'等一轮'混为一谈"

    def test_503_and_says_pending_when_active_but_no_frame_yet(self):
        c = _client(_StubDetect(jpeg=None, active=[2]))
        r = c.get("/api/water_level/debug_frame/ch2")
        assert r.status_code == 503
        assert "尚未产出" in r.json()["detail"]

    def test_503_when_detect_service_absent(self):
        c = _client(None)
        r = c.get("/api/water_level/debug_frame/ch2")
        assert r.status_code == 503
        assert "未就绪" in r.json()["detail"]

    def test_overlay_defaults_to_on(self):
        """缺省必须是开: 用户此前的痛点正是"看不见识别结果", 默认关等于退回原样。"""
        stub = _StubDetect(jpeg=b"x")
        _client(stub).get("/api/water_level/debug_frame/ch2")
        assert stub.frame_calls == [(2, True)]

    def test_overlay_zero_turns_inplace_off(self):
        stub = _StubDetect(jpeg=b"x")
        c = _client(stub)
        assert c.get("/api/water_level/debug_frame/ch2?overlay=0").status_code == 200
        assert stub.frame_calls == [(2, False)]

    def test_overlay_one_turns_inplace_on(self):
        stub = _StubDetect(jpeg=b"x")
        c = _client(stub)
        assert c.get("/api/water_level/debug_frame/ch2?overlay=1").status_code == 200
        assert stub.frame_calls == [(2, True)]

    def test_does_not_shadow_raw_frame_route(self):
        """debug_frame 与既有 /frame/{path:path} 是两条路由, 不得互相吞掉。"""
        c = _client(_StubDetect(jpeg=b"x"))
        # /frame/* 需要 water_level_cfg (此处为 None) → 503, 证明它没被 debug_frame 匹配走
        assert c.get("/api/water_level/frame/ch2").status_code == 503
        assert c.get("/api/water_level/debug_frame/ch2").status_code == 200


class TestHistory:
    def test_returns_points_envelope(self):
        pts = [
            {"t": "2026-07-25T15:00:00+00:00",
             "front_percent": 9.5, "valid": True, "reason": ""},
            {"t": "2026-07-25T15:00:02+00:00",
             "front_percent": None, "valid": False, "reason": "no_front"},
        ]
        c = _client(_StubDetect(points=pts))
        r = c.get("/api/water_level/history/2")
        assert r.status_code == 200
        body = r.json()
        assert body["channel"] == 2
        assert body["points"] == pts, "无效点必须原样透出 (前端据此断线, 抹平即失真)"

    def test_limit_is_passed_through(self):
        stub = _StubDetect(points=[])
        c = _client(stub)
        c.get("/api/water_level/history/3", params={"limit": 120})
        assert stub.history_calls == [(3, 120)]

    def test_default_limit_applied(self):
        stub = _StubDetect(points=[])
        c = _client(stub)
        c.get("/api/water_level/history/3")
        assert stub.history_calls == [(3, 900)]

    def test_503_when_detect_service_absent(self):
        c = _client(None)
        assert c.get("/api/water_level/history/2").status_code == 503
