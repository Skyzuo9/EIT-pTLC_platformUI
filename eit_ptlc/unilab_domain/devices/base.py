"""Shared runtime behavior for statically generated proxy device contracts."""

from __future__ import annotations

import uuid
import json
from pathlib import Path
from typing import Any

import yaml

from eit_ptlc.unilab_domain.runtime_port import PtlcRuntimePort, get_runtime_port


class PlatformUIProxyBase:
    """Thin proxy: no hardware connection and no copied business behavior."""

    platformui_namespace = ""

    def __init__(
        self,
        device_id: str | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.device_id = device_id or self.platformui_namespace.replace(".", "_")
        self.config = dict(config or {})
        self.config.update(kwargs)
        injected = self.config.get("runtime_port")
        self._runtime: PtlcRuntimePort = (
            injected
            if isinstance(injected, PtlcRuntimePort)
            else get_runtime_port(self.config.get("platformui_url"))
        )
        self._last_online = False

    @property
    def online(self) -> bool:
        """Whether the most recent proxy call reached PlatformUI."""

        return self._last_online

    async def _invoke(self, action_name: str, params: dict[str, Any]) -> dict[str, Any]:
        command_id = f"unilab-{uuid.uuid4().hex}"
        try:
            result = await self._runtime.invoke_action(
                action_name,
                {key: value for key, value in params.items() if value is not None},
                command_id=command_id,
            )
        except Exception:
            self._last_online = False
            raise
        self._last_online = True
        return {
            "action": action_name,
            "request_id": str(result.get("request_id") or command_id),
            "command_id": str(result.get("command_id") or command_id),
            "status": str(
                result.get("status")
                or ("DONE" if result.get("accepted", True) else "ERROR")
            ),
            "accepted": bool(result.get("accepted", True)),
            "result_json": json.dumps(
                dict(result.get("result") or {}), ensure_ascii=False, sort_keys=True
            ),
        }

    async def _run_station_operation(
        self,
        operation_name: str,
        inputs_json: str,
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        """Run one non-motion PlatformUI root for exact station semantics.

        This guard is what prevents the generic stage facade from becoming a
        second transport backdoor.  Any root that declares robot or rail is
        rejected and must go through ``transport_resource_v4`` instead.
        """

        document = _load_operation_document(operation_name)
        resources = {str(value) for value in document.get("resources") or []}
        if resources & {"robot", "station:rail"}:
            raise ValueError(
                f"含运动资源的 operation 只能经通用转运 v4 执行: {operation_name}"
            )
        _validate_station_ownership(self.platformui_namespace, operation_name, document)
        inputs = json.loads(inputs_json or "{}")
        if not isinstance(inputs, dict):
            raise ValueError("inputs_json 必须编码 JSON object")
        command_id = f"station-v4-{uuid.uuid4().hex}"
        result = await self._runtime.run_root_operation(
            operation_name,
            inputs,
            command_id=command_id,
            timeout_s=timeout_s,
        )
        status = str(result.get("status") or "UNKNOWN").upper()
        if status != "DONE":
            raise RuntimeError(
                f"PlatformUI 工位 operation 未完成: {operation_name} status={status} command_id={command_id}"
            )
        return {
            "operation_name": operation_name,
            "command_id": command_id,
            "run_id": str(result.get("run_id") or command_id),
            "status": status,
            "result_json": json.dumps(
                dict(result.get("result") or {}), ensure_ascii=False, sort_keys=True
            ),
        }

    async def _run_typed_station_operation(
        self,
        operation_name: str,
        inputs: dict[str, Any],
        *,
        timeout_s: float,
    ) -> dict[str, Any]:
        """Encode a typed UniLab Action contract for the unchanged PlatformUI VM."""

        inputs_json = json.dumps(
            {key: value for key, value in inputs.items() if value is not None},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return await self._run_station_operation(
            operation_name,
            inputs_json,
            timeout_s=timeout_s,
        )


def _load_operation_document(operation_name: str) -> dict[str, Any]:
    operations = Path(__file__).resolve().parents[2] / "config" / "operation"
    matches: list[dict[str, Any]] = []
    for path in operations.rglob("*.yaml"):
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream) or {}
        if raw.get("name") == operation_name:
            matches.append(raw)
    if len(matches) != 1:
        raise ValueError(f"PlatformUI operation 必须唯一存在: {operation_name}")
    return matches[0]


def _validate_station_ownership(
    namespace: str, operation_name: str, document: dict[str, Any]
) -> None:
    ui_station = str((document.get("ui") or {}).get("station") or "")
    namespace = namespace.removeprefix("plc.")
    aliases = {"photoscrape": "photo_scrape"}
    expected = aliases.get(namespace, namespace)
    prefixes = {
        "sampling": ("sampling_", "pf_s2_"),
        "develop": ("develop_", "tank_", "pf_s3_", "pf_s6_"),
        "photoscrape": ("photoscrape_", "pf_s9_"),
        "collect": ("collect_",),
        "feedlift": ("feedlift_",),
    }
    owned = ui_station == expected or operation_name.startswith(
        prefixes.get(namespace, ())
    )
    if not owned:
        raise ValueError(
            f"operation 不属于代理工位 {namespace}: {operation_name} (ui.station={ui_station!r})"
        )


__all__ = ["PlatformUIProxyBase"]
