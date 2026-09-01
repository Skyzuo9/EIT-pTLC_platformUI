"""物料实时 WebSocket 的离线契约测试。"""

from fastapi.testclient import TestClient

from eit_ptlc.action.registry import ActionRegistry
from eit_ptlc.api.app import create_app
from eit_ptlc.runtime.events import EventBus


class _MaterialStoreStub:
    def grid(self) -> dict:
        return {
            "cells": [],
            "staging": {
                "staging-a": {"area": "staging-a", "kind": "collector", "plate": 2},
                "staging-b": {"area": "staging-b", "kind": "bottle", "plate": None},
            },
            "summary": {},
            "presence": [],
            "presence_mismatches": 0,
            "magazines": [
                {"magazine": "feed", "count": 6, "capacity": 30},
                {"magazine": "waste", "count": 8, "capacity": 30},
            ],
            "bottles": [],
            "topology": {},
        }


def test_websocket_seeds_current_material_snapshot_immediately() -> None:
    app = create_app(ActionRegistry({}), bus=EventBus())
    app.state.material_store = _MaterialStoreStub()

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws/events") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            event = websocket.receive_json()

    assert event["type"] == "material_state"
    assert event["initial"] is True
    assert event["seq"] == 0
    assert event["staging"]["staging-a"]["plate"] == 2
    assert event["magazines"][0] == {"magazine": "feed", "count": 6, "capacity": 30}
