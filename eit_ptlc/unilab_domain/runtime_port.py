"""One shared PlatformUI runtime port for every UniLab proxy device.

The production adapter deliberately has only two effectful commands:
``invoke_action`` for explicit single-action debugging and
``run_root_operation`` for an operation whose resources are acquired once by
PlatformUI's existing :class:`ResourceGate`.  Transport code must use the
second command exactly once; it must never loop over ``invoke_action``.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


TERMINAL_STATES = frozenset({"DONE", "ERROR", "KILLED", "CANCELLED", "TIMEOUT", "UNKNOWN"})


def _has_running_asyncio_loop() -> bool:
    """Return whether this coroutine is owned by a real asyncio event loop.

    UniLab's ROS action executor can drive async device methods without
    installing an asyncio loop in the worker thread.  Those coroutines still
    need to reach PlatformUI, but ``asyncio.to_thread`` and ``asyncio.sleep``
    are unavailable in that execution mode.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


async def _cooperative_sleep(delay_s: float) -> None:
    if _has_running_asyncio_loop():
        await asyncio.sleep(delay_s)
        return
    time.sleep(delay_s)


class PtlcRuntimeError(RuntimeError):
    """PlatformUI rejected a command or returned a malformed envelope."""


@runtime_checkable
class PtlcRuntimePort(Protocol):
    """Transport-independent boundary shared by all eleven proxy devices."""

    async def invoke_action(
        self,
        action_name: str,
        params: Mapping[str, Any],
        *,
        command_id: str,
    ) -> dict[str, Any]: ...

    async def run_root_operation(
        self,
        operation_name: str,
        inputs: Mapping[str, Any],
        *,
        command_id: str,
        timeout_s: float | None = None,
    ) -> dict[str, Any]: ...

    async def snapshot(self) -> dict[str, Any]: ...

    async def subscribe_events(self, *, cursor: int = 0) -> AsyncIterator[dict[str, Any]]: ...

    async def reconcile_command(self, command_id: str) -> dict[str, Any]: ...


def _json_request(
    method: str,
    url: str,
    body: Mapping[str, Any] | None = None,
    *,
    timeout_s: float,
) -> Any:
    payload = None if body is None else json.dumps(dict(body), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise PtlcRuntimeError(f"PlatformUI HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise PtlcRuntimeError(f"PlatformUI unavailable: {error}") from error
    return json.loads(raw or b"{}")


class HttpPtlcRuntimePort:
    """HTTP/WS adapter for a running PlatformUI sidecar.

    HTTP owns commands and snapshots.  WS is only a notification stream; a
    reconnecting consumer still reconciles command state over HTTP and never
    retries an effect whose outcome is unknown.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:18080",
        *,
        request_timeout_s: float = 30.0,
        poll_interval_s: float = 0.1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout_s = float(request_timeout_s)
        self.poll_interval_s = float(poll_interval_s)

    def _url(self, path: str) -> str:
        """Resolve a main-runtime path against either PlatformUI API plane.

        Production endpoints live below ``/api``.  The richer local simulator
        is intentionally isolated below ``/api/sim`` but otherwise mirrors the
        action/debug contracts.  A graph opts into that plane by setting
        ``platformui_url`` to ``.../api/sim``; translating here keeps every
        proxy and operation contract identical and avoids ``/api/sim/api``.
        """

        if self.base_url.endswith("/api/sim") and path.startswith("/api/"):
            return f"{self.base_url}/{path.removeprefix('/api/')}"
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        request_args = (
            method,
            self._url(path),
            body,
        )
        if _has_running_asyncio_loop():
            return await asyncio.to_thread(
                _json_request,
                *request_args,
                timeout_s=self.request_timeout_s,
            )
        return _json_request(
            *request_args,
            timeout_s=self.request_timeout_s,
        )

    async def invoke_action(
        self,
        action_name: str,
        params: Mapping[str, Any],
        *,
        command_id: str,
    ) -> dict[str, Any]:
        encoded = urllib.parse.quote(action_name, safe="")
        result = await self._request(
            "POST",
            f"/api/actions/{encoded}/run",
            {"params": dict(params), "command_id": command_id},
        )
        if not isinstance(result, dict):
            raise PtlcRuntimeError("PlatformUI action response must be a JSON object")
        result.setdefault("command_id", command_id)
        return result

    async def run_root_operation(
        self,
        operation_name: str,
        inputs: Mapping[str, Any],
        *,
        command_id: str,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        encoded = urllib.parse.quote(operation_name, safe="")
        start = await self._request(
            "POST",
            f"/api/scripts/{encoded}/debug/run",
            {
                "inputs": dict(inputs),
                "mode_run": "run",
                "command_id": command_id,
            },
        )
        if not isinstance(start, dict):
            raise PtlcRuntimeError("PlatformUI run response must be a JSON object")
        run_id = str(start.get("run_id") or command_id)
        deadline = None if timeout_s is None else time.monotonic() + float(timeout_s)
        while True:
            state = await self._request("GET", f"/api/debug/{urllib.parse.quote(run_id, safe='')}/state")
            if not isinstance(state, dict):
                raise PtlcRuntimeError("PlatformUI run state must be a JSON object")
            terminal = str(state.get("status") or "").upper()
            if terminal in TERMINAL_STATES:
                result: dict[str, Any] = {}
                if terminal == "DONE":
                    try:
                        raw_vars = await self._request(
                            "GET",
                            f"/api/debug/{urllib.parse.quote(run_id, safe='')}/vars",
                        )
                    except PtlcRuntimeError:
                        raw_vars = {}
                    if isinstance(raw_vars, dict) and isinstance(
                        raw_vars.get("vars"), dict
                    ):
                        result = dict(raw_vars["vars"])
                return {
                    **state,
                    "command_id": command_id,
                    "run_id": run_id,
                    "operation": operation_name,
                    "result": result,
                }
            if deadline is not None and time.monotonic() >= deadline:
                # Physical execution may still be running.  The result is
                # intentionally UNKNOWN and must be reconciled, never retried.
                return {
                    "command_id": command_id,
                    "run_id": run_id,
                    "operation": operation_name,
                    "status": "UNKNOWN",
                    "message": "timed out while operation continues; reconcile required",
                }
            await _cooperative_sleep(self.poll_interval_s)

    async def snapshot(self) -> dict[str, Any]:
        actions, nodes, resources = await asyncio.gather(
            self._request("GET", "/api/actions"),
            self._request("GET", "/api/nodes"),
            self._request("GET", "/api/resources"),
            return_exceptions=True,
        )
        return {
            "online": not any(isinstance(item, Exception) for item in (actions, nodes, resources)),
            "actions": [] if isinstance(actions, Exception) else actions,
            "nodes": [] if isinstance(nodes, Exception) else nodes,
            "resources": {} if isinstance(resources, Exception) else resources,
        }

    async def subscribe_events(self, *, cursor: int = 0) -> AsyncIterator[dict[str, Any]]:
        # PlatformUI's current socket is live-only.  The local cursor gives
        # every event a stable adapter position; callers reconcile run state
        # after reconnect before consuming new notifications.
        try:
            import websockets
        except ImportError as error:  # pragma: no cover - dependency is declared by PlatformUI
            raise PtlcRuntimeError("websockets is required for event subscription") from error
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        events_path = "/ws/events" if self.base_url.endswith("/api/sim") else "/api/ws/events"
        next_cursor = int(cursor)
        async with websockets.connect(f"{ws_url}{events_path}") as socket:
            async for raw in socket:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    continue
                next_cursor += 1
                yield {**event, "cursor": next_cursor}

    async def reconcile_command(self, command_id: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(command_id, safe="")
        try:
            result = await self._request("GET", f"/api/debug/{encoded}/state")
        except PtlcRuntimeError:
            return {"command_id": command_id, "status": "UNKNOWN"}
        if not isinstance(result, dict):
            return {"command_id": command_id, "status": "UNKNOWN"}
        return {**result, "command_id": command_id}


@dataclass
class InMemoryPtlcRuntimePort:
    """Deterministic test adapter implementing the same runtime contract."""

    action_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    operation_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    invocations: list[dict[str, Any]] = field(default_factory=list)
    root_runs: list[dict[str, Any]] = field(default_factory=list)
    _commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    _events: list[dict[str, Any]] = field(default_factory=list)

    async def invoke_action(
        self,
        action_name: str,
        params: Mapping[str, Any],
        *,
        command_id: str,
    ) -> dict[str, Any]:
        if command_id in self._commands:
            return dict(self._commands[command_id])
        row = {"action": action_name, "params": dict(params), "command_id": command_id}
        self.invocations.append(row)
        result = {
            "action": action_name,
            "request_id": command_id,
            "command_id": command_id,
            "status": "DONE",
            "accepted": True,
            "result": {},
            **self.action_results.get(action_name, {}),
        }
        self._commands[command_id] = dict(result)
        self._append_event({"type": "step_done", **row, "status": result["status"]})
        return result

    async def run_root_operation(
        self,
        operation_name: str,
        inputs: Mapping[str, Any],
        *,
        command_id: str,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        if command_id in self._commands:
            return dict(self._commands[command_id])
        row = {
            "operation": operation_name,
            "inputs": dict(inputs),
            "command_id": command_id,
            "timeout_s": timeout_s,
        }
        self.root_runs.append(row)
        result = {
            "operation": operation_name,
            "run_id": command_id,
            "command_id": command_id,
            "status": "DONE",
            **self.operation_results.get(operation_name, {}),
        }
        self._commands[command_id] = dict(result)
        self._append_event({"type": "operation_done", **row, "status": result["status"]})
        return result

    async def snapshot(self) -> dict[str, Any]:
        return {"online": True, "commands": len(self._commands)}

    async def subscribe_events(self, *, cursor: int = 0) -> AsyncIterator[dict[str, Any]]:
        for event in self._events:
            if int(event["cursor"]) > int(cursor):
                yield dict(event)

    async def reconcile_command(self, command_id: str) -> dict[str, Any]:
        return dict(self._commands.get(command_id, {"command_id": command_id, "status": "UNKNOWN"}))

    def _append_event(self, event: Mapping[str, Any]) -> None:
        self._events.append({**dict(event), "cursor": len(self._events) + 1})


_PORTS: dict[str, PtlcRuntimePort] = {}
_PORTS_LOCK = threading.Lock()


def get_runtime_port(
    base_url: str | None = None,
    *,
    factory: type[HttpPtlcRuntimePort] = HttpPtlcRuntimePort,
) -> PtlcRuntimePort:
    """Return the process-wide adapter shared by all proxy instances."""

    endpoint = (base_url or os.environ.get("PTLC_PLATFORMUI_URL") or "http://127.0.0.1:18080").rstrip("/")
    with _PORTS_LOCK:
        port = _PORTS.get(endpoint)
        if port is None:
            port = factory(endpoint)
            _PORTS[endpoint] = port
        return port


def install_runtime_port(port: PtlcRuntimePort, *, base_url: str = "memory://ptlc") -> None:
    """Install a shared adapter explicitly (used by tests and embedded deployments)."""

    with _PORTS_LOCK:
        _PORTS[base_url.rstrip("/")] = port


__all__ = [
    "HttpPtlcRuntimePort",
    "InMemoryPtlcRuntimePort",
    "PtlcRuntimeError",
    "PtlcRuntimePort",
    "TERMINAL_STATES",
    "get_runtime_port",
    "install_runtime_port",
]
