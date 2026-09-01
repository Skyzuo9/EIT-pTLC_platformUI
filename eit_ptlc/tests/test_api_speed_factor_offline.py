"""speed_factor 路由参数校验离线测试 (pytest)
=================================================
功能:
    验证 POST /api/robot/speed_factor 的必填 ratio 前置校验: 缺失/非数值 → 422 (HTTP 码与
    result.status 一致), 正常数值 → 200 且 status=DONE. 范围 (1-100) 仍由 action 内部校验.

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_api_speed_factor_offline.py -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app


@pytest.fixture
def client():
    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48496/eit_ptlc/sim/")
    with TestClient(app) as c:  # 进入即触发 lifespan: 启动 Mock PLC + 仿真机器人
        yield c


def test_speed_factor_missing_ratio_422(client):
    resp = client.post("/api/robot/speed_factor", json={})
    assert resp.status_code == 422, resp.text


def test_speed_factor_non_numeric_422(client):
    resp = client.post("/api/robot/speed_factor", json={"ratio": "fast"})
    assert resp.status_code == 422, resp.text


def test_speed_factor_bool_ratio_422(client):
    # bool 会被 float() 接受, 但语义非法 → 422
    resp = client.post("/api/robot/speed_factor", json={"ratio": True})
    assert resp.status_code == 422, resp.text


def test_speed_factor_valid_ratio_200(client):
    resp = client.post("/api/robot/speed_factor", json={"ratio": 35})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "DONE", resp.text
