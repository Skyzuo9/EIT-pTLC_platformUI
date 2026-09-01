"""Run-scoped water-level observations for visual/Rf diagnostics.

This collector listens to VM events.  It freezes the latest detector snapshot
immediately before ``develop.drain`` is dispatched, then attaches that immutable
observation to the later PhotoScrape vision case from the same run.  It does not
change the operation sequence and it does not participate in Rf calculation.
"""

from __future__ import annotations

import copy
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SCHEMA = "ptlc.water-level-observation/v1"
_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]+")


def _utc_iso(timestamp: float | None = None) -> str:
    dt = datetime.now(timezone.utc) if timestamp is None else datetime.fromtimestamp(
        float(timestamp), tz=timezone.utc,
    )
    return dt.isoformat()


def _age_seconds(observed_at: str | None, captured_at: str) -> float | None:
    if not observed_at:
        return None
    try:
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
        return round(max(0.0, (captured - observed).total_seconds()), 3)
    except (TypeError, ValueError):
        return None


def _safe_filename(value: str) -> str:
    cleaned = _SAFE_PART.sub("_", str(value)).strip("._")
    return cleaned[:120] or "run"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temp, path)


class WaterLevelObservationCollector:
    """Synchronous VM event sink; failures are isolated by ``make_event_sink``."""

    def __init__(self, detect_service: Any, output_dir: Path | str) -> None:
        self._detect = detect_service
        self._output_dir = Path(output_dir)
        self._by_run: dict[str, dict[str, Any]] = {}
        self._entered: dict[tuple[str, str], dict[str, Any]] = {}

    def on_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        run_id = str(event.get("run_id") or "")
        if not run_id:
            return
        if event_type == "vm_node_enter":
            action = str(event.get("action") or "")
            aid = str(event.get("aid") or "")
            args = dict(event.get("args") or {})
            self._entered[(run_id, aid)] = {"action": action, "args": args}
            if action == "develop.drain":
                self._capture_before_drain(run_id, args, event.get("ts"))
            return
        if event_type == "vm_node_done":
            aid = str(event.get("aid") or "")
            entered = self._entered.pop((run_id, aid), None) or {}
            if entered.get("action") == "photoscrape.analyze" and event.get("status") == "DONE":
                self._attach_to_vision_case(
                    run_id,
                    entered.get("args") or {},
                    event.get("result") or {},
                )
            return
        if event_type in ("operation_done", "operation_failed"):
            self._by_run.pop(run_id, None)
            for key in [key for key in self._entered if key[0] == run_id]:
                self._entered.pop(key, None)

    def _capture_before_drain(
        self, run_id: str, args: dict[str, Any], timestamp: float | None,
    ) -> None:
        channel = int(args.get("target_tank") or args.get("tank") or 0)
        captured_at = _utc_iso(timestamp)
        channel_data: dict[str, Any] | None = None
        if self._detect is not None and channel > 0:
            snapshot = self._detect.snapshot() or {}
            channels = snapshot.get("channels") or {}
            channel_data = channels.get(channel) or channels.get(str(channel))

        if channel_data is None:
            measurement = {
                "observed_at": None,
                "age_s": None,
                "front_percent": None,
                "valid": False,
                "reason": "detector_unavailable" if self._detect is None else "channel_has_no_result",
                "reachable": False,
                "calibrated": False,
                "flow_direction": None,
            }
        else:
            observed_at = channel_data.get("observed_at")
            measurement = {
                "observed_at": observed_at,
                "age_s": _age_seconds(observed_at, captured_at),
                "front_percent": channel_data.get("front_percent"),
                "valid": bool(channel_data.get("valid", False)),
                "reason": str(channel_data.get("reason") or ""),
                "reachable": bool(channel_data.get("reachable", False)),
                "calibrated": bool(channel_data.get("calibrated", False)),
                "flow_direction": channel_data.get("flow_direction"),
                "wet_ratio": channel_data.get("wet_ratio"),
                "diff_mean": channel_data.get("diff_mean"),
            }

        observation = {
            "schema": _SCHEMA,
            "observation_id": uuid.uuid4().hex,
            "run_id": run_id,
            "sample_id": None,
            "tank_id": channel if channel > 0 else None,
            "channel": channel if channel > 0 else None,
            "captured_at": captured_at,
            "capture_point": "before_develop_drain_dispatch",
            "measurement": measurement,
            "rf_usage": {
                "source": "image",
                "external_used_for_rf": False,
                "mapping_status": "not_configured",
            },
        }
        self._by_run[run_id] = observation
        _write_json_atomic(
            self._output_dir / f"{_safe_filename(run_id)}.json", observation,
        )

    def _attach_to_vision_case(
        self, run_id: str, args: dict[str, Any], result: dict[str, Any],
    ) -> None:
        observation = self._by_run.get(run_id)
        if observation is None:
            return
        case_dir_raw = result.get("case_dir")
        if not case_dir_raw:
            return
        payload = copy.deepcopy(observation)
        payload["sample_id"] = str(args.get("sample_id") or result.get("case_name") or "") or None
        case_dir = Path(str(case_dir_raw))
        _write_json_atomic(case_dir / "liquid_observation.json", payload)
        _write_json_atomic(
            self._output_dir / f"{_safe_filename(run_id)}.json", payload,
        )

