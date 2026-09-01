"""对位检查 — 配置/回显/端点/编排离线测试 (spec 2026-07-16-photoscrape-align-check)。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.config.loader import _parse_gcode
from eit_ptlc.controller.align_check import build_align_readout
from eit_ptlc.controller.plc_controller import PlcController

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
_ACTIONS_DIR = _PKG / "config" / "actions"


def _load_registry() -> ActionRegistry:
    """从真实 config/actions 目录加载动作注册表 (照 test_action_dto_offline.py)。"""
    return ActionRegistry.load(_ACTIONS_DIR)


def test_align_clearance_default_and_parse():
    assert _parse_gcode({}).align_clearance_mm == 2.5
    assert _parse_gcode({"align_clearance_mm": 4.0}).align_clearance_mm == 4.0


class _FakeDriver:
    """最小伪驱动: read_variable 从预置字典取值 (构造形态照 test_plc_l2_missed_done_offline.py)。"""

    def __init__(self, vals: dict[str, object]) -> None:
        self._vals = vals

    async def read_many(self, names: list[str]) -> list:
        """批量读 (替身实现: 逐点转 read_variable, 完整保留本替身模拟的语义)."""
        return [await self.read_variable(n) for n in names]

    async def read_variable(self, name: str):
        return self._vals[name]


def _make_plc_with_values(vals: dict[str, object]) -> PlcController:
    return PlcController(_FakeDriver(vals))


def test_read_scrape_axes_reads_three_actpos_nodes():
    plc = _make_plc_with_values({
        "PhotoScrape_9X_ActPos": 91.24,
        "PhotoScrape_8Y_ActPos": -75.2,
        "PhotoScrape_10Z_ActPos": 0.0,
    })
    x, y, z = asyncio.run(plc.read_scrape_axes())
    assert (x, y, z) == (91.24, -75.2, 0.0)


def test_align_readout_delta_and_text():
    g = _parse_gcode({"plate_origin_x": 91.24, "plate_origin_y": -75.2,
                      "plate_surface_z_mm": 20.5, "align_clearance_mm": 2.5})
    ro = build_align_readout((92.34, -75.9, 0.0), g)
    assert ro["origin_x_mm"] == 91.24 and ro["origin_y_mm"] == -75.2
    assert ro["inspect_z_mm"] == 18.0
    assert round(ro["dx_vs_origin_mm"], 3) == 1.1
    assert round(ro["dy_vs_origin_mm"], 3) == -0.7
    assert "X=92.34" in ro["text"] and "plate_origin" in ro["text"]


def test_align_actions_registered():
    reg = _load_registry()   # 复用既有测试的 registry 加载 helper
    mv = reg.get("photoscrape.align_move")
    assert mv.kind == "plc_l2" and mv.action_code == 42
    assert {p.name: p.channel for p in mv.params} == {
        "x_mm": "PhotoScrape_Align_TargetX", "y_mm": "PhotoScrape_Align_TargetY"}
    assert reg.get("photoscrape.align_home").action_code == 43
    az = reg.get("photoscrape.align_z")
    assert az.action_code == 44
    assert [p.channel for p in az.params] == ["PhotoScrape_Align_TargetZ"]
    assert reg.get("photoscrape.align_readout").kind == "host"


def _client_with_plc(tmp_path, *, values):
    """FastAPI + register_photoscrape_routes;plc stub 挂 app.state.plc(values=None → 无 PLC)。
    照 test_sketch_rectify_offline.py `_client`,额外挂 read_scrape_axes 只读 stub。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from eit_ptlc.api.photoscrape_routes import register_photoscrape_routes

    class _CfgStub:
        def read_section(self, name):
            return {"output_dir": str(tmp_path)}

    class _PlcStub:
        async def read_scrape_axes(self):
            return values

    app = FastAPI()
    app.state.config_svc = _CfgStub()
    app.state.plc = _PlcStub() if values is not None else None
    register_photoscrape_routes(app)
    return TestClient(app), app


def test_axes_endpoint_reads_plc(tmp_path):
    client, app = _client_with_plc(tmp_path, values=(91.24, -75.2, 0.0))
    r = client.get("/api/photoscrape/axes")
    assert r.status_code == 200
    assert r.json() == {"x_mm": 91.24, "y_mm": -75.2, "z_mm": 0.0}


def test_axes_endpoint_503_when_plc_absent(tmp_path):
    client, app = _client_with_plc(tmp_path, values=None)   # app.state.plc = None
    assert client.get("/api/photoscrape/axes").status_code == 503
