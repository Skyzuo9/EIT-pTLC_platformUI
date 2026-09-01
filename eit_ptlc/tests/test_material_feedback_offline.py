"""物料账本只读实时推送离线测试。"""

from __future__ import annotations

import asyncio

from eit_ptlc.runtime.events import EventBus
from eit_ptlc.runtime.material_feedback import material_feedback_loop, material_state_event


class _Store:
    def __init__(self, stop: asyncio.Event) -> None:
        self.stop = stop
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def grid(self) -> dict:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        count = 6 if self.calls < 2 else 5
        self.active -= 1
        if self.calls >= 3:
            self.stop.set()
        return {
            "cells": [],
            "staging": {"staging-a": {"area": "staging-a", "kind": "collector", "plate": None}},
            "summary": {"collector": {"fresh": 0, "used": 36, "filled": 0}},
            "presence": [],
            "presence_mismatches": 0,
            "magazines": [{"magazine": "feed", "count": count, "capacity": 30}],
            "bottles": [],
            "topology": {"categories": []},
        }


async def _exercise() -> None:
    stop = asyncio.Event()
    store = _Store(stop)
    bus = EventBus(max_queue=10)
    async with bus.subscribe() as queue:
        await material_feedback_loop(store, bus, stop, interval=0.001, heartbeat=60)
        events = list(queue._buf)
    assert store.max_active == 1
    assert [event["type"] for event in events] == ["material_state", "material_state"]
    assert [event["magazines"][0]["count"] for event in events] == [6, 5]
    assert [event["seq"] for event in events] == [1, 2]


def test_material_feedback_only_publishes_changes_without_backlog() -> None:
    asyncio.run(_exercise())


def test_initial_event_does_not_mutate_grid_snapshot() -> None:
    snapshot = {"cells": [], "staging": {}, "magazines": []}
    event = material_state_event(snapshot, ts=123.0, seq=0, initial=True)
    assert event["type"] == "material_state"
    assert event["initial"] is True
    assert snapshot == {"cells": [], "staging": {}, "magazines": []}
