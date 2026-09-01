"""单原子动作运行事件标注离线测试 (pytest)
=================================================
功能:
    验证 POST /api/actions/{id}/run 的 operation_start 事件带 atomic=True 且 operation=动作 id
    (含 '.', 如 robot.move_to_point)。前端据此区分"单动作运行"与"VM 流程运行"(operation=脚本名,
    不带 atomic) —— 单动作无编辑页, jumpToRunning 不把动作 id 当流程名跳死路由 (审阅 #6)。

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m pytest eit_ptlc/tests/test_atomic_operation_event_offline.py -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from eit_ptlc.runtime.bootstrap import create_sim_app


@pytest.fixture
def client():
    app = create_sim_app(opcua_url="opc.tcp://127.0.0.1:48497/eit_ptlc/sim/")
    with TestClient(app) as c:  # 进入即触发 lifespan: 启动 Mock PLC + 仿真机器人 + EventBus
        yield c


def _capture(bus):
    """包裹 bus.publish 收集事件 (publish 同步; _execute_with_live_events 每次现取 bus.publish)。"""
    events: list[dict] = []
    orig = bus.publish

    def _wrapped(ev):
        events.append(ev)
        orig(ev)

    bus.publish = _wrapped
    return events


def test_single_action_run_emits_atomic_operation_start(client):
    bus = client.app.state.bus
    events = _capture(bus)
    resp = client.post(
        "/api/actions/robot.move_to_point/run",
        json={"params": {"point_id_or_robot_name": "robot-main.home", "motion": "move_j"}},
    )
    assert resp.status_code == 200, resp.text

    starts = [e for e in events if e.get("type") == "operation_start"]
    assert len(starts) == 1, [e.get("type") for e in events]
    # atomic=True 是标志, operation 是动作 id (含 '.') 而非流程脚本名
    assert starts[0].get("atomic") is True, starts[0]
    assert starts[0].get("operation") == "robot.move_to_point", starts[0]
    assert "." in starts[0].get("operation", ""), starts[0]


def test_single_action_run_carries_params_on_step_events(client):
    """step_start/step_done 必须带 params。

    VM 路径的 vm_node_enter 一直带 args, 而这条合成路径此前不带 —— 于是任何按入参做的
    旁路显示 (三维展缸液面要的 target_tank + 配方体积) 在维护面板手点动作时全瞎。
    """
    bus = client.app.state.bus
    events = _capture(bus)
    params = {"target_tank": 3, "solvent_volume_ml": 12.5, "up_liquid_repeat_count": 2}
    resp = client.post("/api/actions/develop.fill/run", json={"params": params})
    assert resp.status_code == 200, resp.text

    for kind in ("step_start", "step_done"):
        steps = [e for e in events if e.get("type") == kind]
        assert len(steps) == 1, [e.get("type") for e in events]
        assert steps[0].get("action") == "develop.fill", steps[0]
        assert steps[0].get("params") == params, steps[0]


def test_single_action_run_params_absent_is_empty_dict(client):
    """不带入参的动作也要有 params 键 (空字典), 前端才不用区分 undefined 与 {}。"""
    bus = client.app.state.bus
    events = _capture(bus)
    resp = client.post("/api/actions/develop.init/run", json={"params": {}})
    assert resp.status_code == 200, resp.text

    starts = [e for e in events if e.get("type") == "step_start"]
    assert len(starts) == 1
    assert starts[0].get("params") == {}, starts[0]
