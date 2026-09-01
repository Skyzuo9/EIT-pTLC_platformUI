"""Effectful half of the v4 transport boundary."""

from __future__ import annotations

import json
from typing import Any

from eit_ptlc.unilab_domain.runtime_port import PtlcRuntimePort
from eit_ptlc.unilab_domain.transport_contract import compile_transport_contract


class TransportOutcomeUnknown(RuntimeError):
    """The root may still be moving; inventory must remain unchanged."""


_LAST_PHYSICAL_SITES: dict[str, str] = {}


def preflight_transport(
    *, resource: object, target_device: str, target_mount: object, target_site: str
) -> dict[str, Any]:
    key = _resource_key(resource)
    contract = compile_transport_contract(
        resource=resource,
        target_device=target_device,
        target_mount=target_mount,
        target_site=target_site,
        source_site_hint=_LAST_PHYSICAL_SITES.get(key),
    )
    return {
        "operation_name": contract.operation_name,
        "operation_inputs_json": contract.operation_inputs_json(),
        "source_site": contract.source_site,
        "target_site": contract.target_site,
        "required_tool": contract.required_tool,
        "source_rail_target": contract.source_rail_target,
        "target_rail_target": contract.target_rail_target,
        "safety_anchor": contract.safety_anchor,
        "command_id": contract.command_id,
    }


async def execute_transport_root(
    runtime: PtlcRuntimePort,
    *,
    resource: object,
    operation_name: str,
    operation_inputs_json: str,
    command_id: str,
    target_site: str,
    timeout_s: float = 3600.0,
) -> dict[str, Any]:
    """Submit exactly one root; never decompose it or retry UNKNOWN."""

    inputs = json.loads(operation_inputs_json or "{}")
    if not isinstance(inputs, dict):
        raise ValueError("operation_inputs_json 必须编码 JSON object")
    result = await runtime.run_root_operation(
        operation_name,
        inputs,
        command_id=command_id,
        timeout_s=timeout_s,
    )
    status = str(result.get("status") or "UNKNOWN").upper()
    if status == "UNKNOWN":
        raise TransportOutcomeUnknown(
            f"转运结果未知，禁止重试和提交库存: command_id={command_id}"
        )
    if status != "DONE":
        raise RuntimeError(f"转运未完成，库存保持原位: {operation_name} status={status}")
    _LAST_PHYSICAL_SITES[_resource_key(resource)] = target_site
    metadata = getattr(resource, "metadata", None)
    if isinstance(metadata, dict):
        # This is only a durable routing hint on the same material identity;
        # the HostNode call remains the sole inventory authority.
        metadata["ptlc_site"] = target_site
    return {
        "resource": resource,
        "target_site": target_site,
        "operation_name": operation_name,
        "command_id": command_id,
        "status": status,
    }


def _resource_key(resource: object) -> str:
    for attr in ("unilabos_uuid", "uuid", "id", "name"):
        value = getattr(resource, attr, None)
        if value:
            return f"{attr}:{value}"
    return f"object:{id(resource)}"


__all__ = ["TransportOutcomeUnknown", "execute_transport_root", "preflight_transport"]
