"""板位对位零点示教 — 离线单测。

覆盖:
    1. local_plate_vision.write_reference: ruamel 往返只改 reference, 保注释与其余字段。
    2. PlateAlignService.teach: 取板→拍姿→放回 的动作序列与顺序; sane 判定; 无板仍放回不抛;
       取板步失败即中止 (无拍照/放回); 拍照抛错仍放回 (finally)。
    3. PlateAlignService.apply: 合理值写回 + 热更; 越界拒写。
    4. 路由 DEBUG / confirm 门控 (409)。
"""

from __future__ import annotations

import asyncio
import shutil

from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.controller import local_plate_vision as lpv
from eit_ptlc.controller import plate_align_service as pas
from eit_ptlc.controller.plate_align_service import PlateAlignError, PlateAlignService


# ------------------------------------------------------------------ write_reference
def test_write_reference_round_trip(tmp_path):
    """write_reference 只改 reference.u0/v0/theta0, calib/detect/camera 与注释/结构全保留。"""
    dst = tmp_path / "lpv.yaml"
    shutil.copy(lpv._CFG_PATH, dst)
    before_cfg = lpv.load_cfg(dst)
    before_text = dst.read_text(encoding="utf-8")

    res = lpv.write_reference(1580.53, 970.31, -89.12, path=dst)
    assert res == {"u0": 1580.5, "v0": 970.3, "theta0": -89.12}

    after_cfg = lpv.load_cfg(dst)
    assert (after_cfg.u0, after_cfg.v0, after_cfg.theta0) == (1580.5, 970.3, -89.12)
    # 只改 reference: 其余字段逐一等于原值
    for field in ("ax", "bx", "ay", "by", "arz", "sign_xy", "sign_rz", "threshold",
                  "min_area", "roi", "expect_center", "ip", "exposure_us", "gain", "err_fail_code"):
        assert getattr(after_cfg, field) == getattr(before_cfg, field), field
    after_text = dst.read_text(encoding="utf-8")
    assert "PALLASVision" in after_text  # 顶部注释保留
    assert len(before_text.splitlines()) == len(after_text.splitlines())  # 结构行数不变


# ------------------------------------------------------------------ fakes
class _Cfg:
    """模拟 LocalVisionCfg 的 teach 相关字段 (零点 + 名义板位)。"""

    def __init__(self, u0=1571.7, v0=967.2, theta0=-89.4, expect_center=(1571.0, 967.0)):
        self.u0, self.v0, self.theta0 = u0, v0, theta0
        self.expect_center = expect_center


class _FakeExec:
    """伪执行器: 记录 execute 调用; fail_at=第几次(0基)返回 REJECTED。"""

    def __init__(self, calls, fail_at=None):
        self.calls = calls
        self._fail_at = fail_at
        self._n = 0

    async def execute(self, name, params=None, *, request_id=None, current_mode=None):
        self.calls.append(("exec", name, dict(params or {}), current_mode))
        i = self._n
        self._n += 1
        if self._fail_at is not None and i == self._fail_at:
            return ActionResult(action=name, request_id="x", status=ActionStatus.REJECTED,
                                accepted=False, message="测试注入失败", result={})
        return ActionResult(action=name, request_id="x", status=ActionStatus.DONE,
                            accepted=True, message="ok", result={})


class _FakeVision:
    def __init__(self, calls, pose):
        self.calls = calls
        self._pose = pose
        self.reloaded = False

    async def capture_plate_pose(self):
        self.calls.append(("capture",))
        return dict(self._pose)

    async def bridge_reload(self):
        self.reloaded = True
        return {"reloaded": True}

    async def bridge_status(self):
        return {"enabled": True}


class _RaisingVision(_FakeVision):
    async def capture_plate_pose(self):
        self.calls.append(("capture",))
        raise RuntimeError("camera boom")


# pickup(含 place_axis) → capture → return; 由步表长度算出, 随步表增删自适应
_KINDS_OK = ["exec"] * len(pas._PICKUP_STEPS) + ["capture"] + ["exec"] * len(pas._RETURN_STEPS)


# ------------------------------------------------------------------ teach
def test_teach_sequence_and_sane(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg(expect_center=(1571.0, 967.0)))
    calls = []
    ex = _FakeExec(calls)
    vis = _FakeVision(calls, {"u": 1575.0, "v": 969.0, "theta": -89.2, "valid": True})
    svc = PlateAlignService(executor=ex, vision_client=vis)

    res = asyncio.run(svc.teach(current_mode="DEBUG"))

    n_pick = len(pas._PICKUP_STEPS)
    assert [c[0] for c in calls] == _KINDS_OK  # 顺序: 取板→拍照→放回
    assert calls[0][1] == "robot.require_anchor" and calls[-1][1] == "robot.require_anchor"
    assert "sampling.place_axis" in [c[1] for c in calls[:n_pick]]  # 取板段先推出 7Y
    pickup_tool = [c[2].get("action") for c in calls[:n_pick] if c[1] == "robot.tool_action"]
    return_tool = [c[2].get("action") for c in calls[n_pick + 1:] if c[1] == "robot.tool_action"]
    assert "rotary-up" in pickup_tool and "suction-on" in pickup_tool
    assert "suction-off" in return_tool and "rotary-down" in return_tool
    assert all(c[3] == "DEBUG" for c in calls if c[0] == "exec")  # current_mode 透传
    assert res["measured"]["valid"] is True and res["sane"] is True
    assert res["current_reference"] == {"u0": 1571.7, "v0": 967.2, "theta0": -89.4}
    assert res["delta_px"] is not None


def test_teach_no_plate_still_returns(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg())
    calls = []
    vis = _FakeVision(calls, {"u": 0.0, "v": 0.0, "theta": 0.0, "valid": False})
    svc = PlateAlignService(executor=_FakeExec(calls), vision_client=vis)

    res = asyncio.run(svc.teach(current_mode="DEBUG"))

    assert [c[0] for c in calls] == _KINDS_OK  # 无板也走完放回
    assert res["measured"]["valid"] is False and res["sane"] is False and res["delta_px"] is None


def test_teach_pickup_fail_aborts(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg())
    calls = []
    ex = _FakeExec(calls, fail_at=3)  # 取板段第4步失败即中止
    vis = _FakeVision(calls, {"u": 1571.0, "v": 967.0, "theta": -89.4, "valid": True})
    svc = PlateAlignService(executor=ex, vision_client=vis)

    try:
        asyncio.run(svc.teach(current_mode="DEBUG"))
        assert False, "应抛 PlateAlignError"
    except PlateAlignError:
        pass
    assert [c[0] for c in calls] == ["exec"] * 4  # 失败即停: 无拍照/无放回


def test_teach_capture_fail_runs_return(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg())
    calls = []
    svc = PlateAlignService(executor=_FakeExec(calls), vision_client=_RaisingVision(calls, {}))

    try:
        asyncio.run(svc.teach(current_mode="DEBUG"))
        assert False, "应抛 RuntimeError"
    except RuntimeError:
        pass
    assert [c[0] for c in calls] == _KINDS_OK  # 拍照失败仍 finally 放回


def test_grip_release_at_p19_reuses_production_pick_put():
    """抓/放同点 P19; 取板复用生产 pick(从下方 pick.approach→pick.retreat), 放回复用生产 put(从上方
    put.approach→put.retreat 空爪下潜); 全程不碰喷涂位 P20。"""

    def grip_point(steps, tool_action):
        pt = None
        for name, args in steps:
            if name == "robot.move_to_point":
                pt = args["point_id_or_robot_name"]
            elif name == "robot.tool_action" and args.get("action") == tool_action:
                return pt
        return None

    pick_pt = grip_point(pas._PICKUP_STEPS, "suction-on")
    put_pt = grip_point(pas._RETURN_STEPS, "suction-off")
    assert pick_pt == "P19", f"取板点应为 P19, 实为 {pick_pt}"
    assert put_pt == "P19", f"放回点应为 P19 (原位), 实为 {put_pt}"
    assert pick_pt == put_pt

    pickup_pts = [args.get("point_id_or_robot_name", "")
                  for name, args in pas._PICKUP_STEPS if name == "robot.move_to_point"]
    return_pts = [args.get("point_id_or_robot_name", "")
                  for name, args in pas._RETURN_STEPS if name == "robot.move_to_point"]
    # 取板从下方: pick.approach 进近 + pick.retreat 提板 (= 生产 robot_suction_pick); 绝不从上方 put.* 压
    assert any("pick.approach" in p for p in pickup_pts), pickup_pts
    assert any("pick.retreat" in p for p in pickup_pts), pickup_pts
    assert not any("put." in p for p in pickup_pts), f"取板段不应从上方 put 进近: {pickup_pts}"
    # 放回从上方: put.approach 进近 + put.retreat 空爪下潜退出 (= 生产 robot_suction_put)
    assert any("put.approach" in p for p in return_pts), return_pts
    assert any("put.retreat" in p for p in return_pts), return_pts
    # 全程不碰喷涂位 P20
    assert "P20" not in pickup_pts + return_pts, "示教不应触及喷涂位 P20"


# ------------------------------------------------------------------ apply
def test_apply_writes_and_reloads(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg(expect_center=(1571.0, 967.0)))
    written = {}

    def _fake_write(u, v, theta, path=None):
        written.update(u0=u, v0=v, theta0=theta)
        return {"u0": round(u, 1), "v0": round(v, 1), "theta0": round(theta, 2)}

    monkeypatch.setattr(pas.local_plate_vision, "write_reference", _fake_write)
    calls = []
    vis = _FakeVision(calls, {})
    svc = PlateAlignService(executor=_FakeExec(calls), vision_client=vis)

    res = asyncio.run(svc.apply(1575.0, 969.0, -89.2))

    assert written == {"u0": 1575.0, "v0": 969.0, "theta0": -89.2}
    assert vis.reloaded is True
    assert res["reloaded"] is True and res["reference"]["u0"] == 1575.0


def test_apply_rejects_out_of_band(monkeypatch):
    monkeypatch.setattr(pas.local_plate_vision, "load_cfg", lambda: _Cfg(expect_center=(1571.0, 967.0)))
    called = {"n": 0}

    def _fake_write(*a, **k):
        called["n"] += 1
        return {}

    monkeypatch.setattr(pas.local_plate_vision, "write_reference", _fake_write)
    calls = []
    svc = PlateAlignService(executor=_FakeExec(calls), vision_client=_FakeVision(calls, {}))

    try:
        asyncio.run(svc.apply(3000.0, 969.0, -89.2))  # 偏离名义板位远超 250px
        assert False, "应抛 PlateAlignError"
    except PlateAlignError:
        pass
    assert called["n"] == 0  # 越界不写


# ------------------------------------------------------------------ routes 门控
class _FakeSvc:
    async def status(self):
        return {"reference": {"u0": 1.0}, "bridge": {}}

    async def teach(self, *, current_mode):
        return {"ok": True, "mode": current_mode}

    async def apply(self, u, v, theta):
        return {"reference": {"u0": u}}


def _make_client(mode):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from eit_ptlc.api.plate_align_routes import register_plate_align_routes

    app = FastAPI()
    register_plate_align_routes(app)
    app.state.plate_align = _FakeSvc()
    app.state.control_mode = mode
    return TestClient(app)


def test_routes_gating_non_debug():
    client = _make_client("RUN")
    assert client.get("/api/plate_align/status").status_code == 200            # status 不门控
    assert client.post("/api/plate_align/teach").status_code == 409            # teach 需 DEBUG
    assert client.post("/api/plate_align/apply",
                       json={"u": 1, "v": 2, "theta": 3, "confirm": True}).status_code == 409


def test_routes_gating_debug():
    client = _make_client("DEBUG")
    # apply 无 confirm → 409
    assert client.post("/api/plate_align/apply",
                       json={"u": 1, "v": 2, "theta": 3, "confirm": False}).status_code == 409
    # apply DEBUG + confirm → 200
    assert client.post("/api/plate_align/apply",
                       json={"u": 1, "v": 2, "theta": 3, "confirm": True}).status_code == 200
    # teach DEBUG → 200, current_mode 透传为 DEBUG
    r = client.post("/api/plate_align/teach")
    assert r.status_code == 200 and r.json()["mode"] == "DEBUG"
