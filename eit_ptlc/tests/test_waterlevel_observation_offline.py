from __future__ import annotations

import asyncio
import json
from pathlib import Path

from eit_ptlc.controller.waterlevel_observation import WaterLevelObservationCollector
from eit_ptlc.action.models import ActionResult, ActionStatus
from eit_ptlc.operation.resources import ResourceGate
from eit_ptlc.operation.vm.thread import VmThread


class _Detect:
    def snapshot(self):
        return {"channels": {1: {
            "front_percent": 60.0,
            "valid": True,
            "reason": "",
            "reachable": True,
            "calibrated": True,
            "flow_direction": "bottom_to_top",
            "wet_ratio": 0.625,
            "diff_mean": 18.2,
            "observed_at": "2026-07-12T10:00:00+00:00",
        }}}


def test_collector_freezes_before_drain_and_attaches_to_same_run(tmp_path):
    collector = WaterLevelObservationCollector(_Detect(), tmp_path / "observations")
    collector.on_event({
        "type": "vm_node_enter", "run_id": "run-1", "aid": "b/1",
        "action": "develop.drain", "args": {"target_tank": 1},
        "ts": 1783850401.0,
    })

    run_file = tmp_path / "observations" / "run-1.json"
    assert run_file.is_file()
    frozen = json.loads(run_file.read_text(encoding="utf-8"))
    assert frozen["capture_point"] == "before_develop_drain_dispatch"
    assert frozen["measurement"]["front_percent"] == 60.0
    assert frozen["rf_usage"]["external_used_for_rf"] is False

    case_dir = tmp_path / "vision" / "S1"
    case_dir.mkdir(parents=True)
    collector.on_event({
        "type": "vm_node_enter", "run_id": "run-1", "aid": "b/2",
        "action": "photoscrape.analyze", "args": {"sample_id": "S1"},
        "ts": 1783850410.0,
    })
    collector.on_event({
        "type": "vm_node_done", "run_id": "run-1", "aid": "b/2",
        "status": "DONE", "result": {"case_dir": str(case_dir)},
        "ts": 1783850412.0,
    })

    attached = json.loads((case_dir / "liquid_observation.json").read_text(encoding="utf-8"))
    assert attached["run_id"] == "run-1"
    assert attached["sample_id"] == "S1"
    assert attached["channel"] == 1


def test_collector_marks_unavailable_detector_without_claiming_validity(tmp_path):
    collector = WaterLevelObservationCollector(None, tmp_path)
    collector.on_event({
        "type": "vm_node_enter", "run_id": "sim-run", "aid": "b/1",
        "action": "develop.drain", "args": {"target_tank": 2}, "ts": 1.0,
    })
    payload = json.loads((tmp_path / "sim-run.json").read_text(encoding="utf-8"))
    assert payload["measurement"]["valid"] is False
    assert payload["measurement"]["reason"] == "detector_unavailable"


def test_vm_node_enter_exposes_evaluated_action_args():
    class _Executor:
        async def execute(self, name, params=None, **_kwargs):
            return ActionResult(
                action=name, request_id="x", status=ActionStatus.DONE,
                accepted=True, message="ok", result={},
            )

    events = []
    doc = {
        "schema": "ptlc.script/v1", "kind": "operation", "name": "obs_test",
        "vars": [{"name": "tank", "scope": "local", "type": "INT", "io": "in", "default": 1}],
        "body": [{
            "op": "call", "action": "develop.drain",
            "args": {"target_tank": {"var": "tank"}},
        }],
    }
    thread = VmThread(
        doc, executor=_Executor(), res_gate=ResourceGate(), emit=events.append,
    )
    asyncio.run(thread.run({"tank": 3}))
    entered = next(event for event in events if event["type"] == "vm_node_enter")
    assert entered["args"] == {"target_tank": 3}
