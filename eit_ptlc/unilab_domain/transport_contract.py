"""Compile a parameter-only UniLab transfer request to one PlatformUI root.

The generated route catalog is a projection of PlatformUI's existing
operations.  This module only resolves and validates a request; it never
drives hardware and never mutates UniLab inventory.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


_CATALOG = Path(__file__).with_name("generated") / "transport_routes.v1.yaml"


class TransportContractError(ValueError):
    """A transfer cannot be mapped unambiguously to a published root."""


@dataclass(frozen=True, slots=True)
class TransportContract:
    resource_name: str
    source_site: str
    target_device: str
    target_site: str
    operation_name: str
    operation_inputs: Mapping[str, Any]
    required_tool: str
    source_rail_target: int
    target_rail_target: int
    safety_anchor: str
    resources: tuple[str, ...]
    command_id: str

    def operation_inputs_json(self) -> str:
        return json.dumps(dict(self.operation_inputs), ensure_ascii=False, sort_keys=True)


def compile_transport_contract(
    *,
    resource: object,
    target_device: str,
    target_mount: object,
    target_site: str,
    source_site_hint: str | None = None,
    catalog_path: str | Path | None = None,
) -> TransportContract:
    """Resolve one transfer using only resource state and its four public inputs."""

    catalog = _load_catalog(Path(catalog_path or _CATALOG))
    aliases = {str(key): str(value) for key, value in catalog["site_aliases"].items()}
    source_candidates = (
        [_normalise_site(source_site_hint)] if source_site_hint else []
    ) + _resource_site_candidates(resource)
    source = next((aliases[item] for item in source_candidates if item in aliases), "")
    target_mount_name = _normalise_site(getattr(target_mount, "name", ""))
    target_candidates = [
        f"{_normalise_site(target_device)}:{_normalise_site(target_site)}",
        f"{target_mount_name}:{_normalise_site(target_site)}" if target_mount_name else "",
        _normalise_site(target_site),
    ]
    target = next((aliases[item] for item in target_candidates if item in aliases), "")
    if not source:
        raise TransportContractError(
            f"无法从物料父载架推导 PlatformUI 源库位: candidates={source_candidates}"
        )
    if not target:
        raise TransportContractError(
            f"无法从 target_device/target_mount/target_site 推导 PlatformUI 目标库位: candidates={target_candidates}"
        )

    candidates = []
    for raw in catalog["routes"]:
        route = dict(raw)
        source_pattern = str(route["source"])
        target_pattern = str(route["target"])
        source_vars = _match_site(source_pattern, source)
        target_vars = _match_site(target_pattern, target)
        if source_vars is None or target_vars is None:
            continue
        if str(route["target_device"]) != str(target_device):
            continue
        candidates.append((route, {**source_vars, **target_vars}))
    if len(candidates) != 1:
        names = [str(item[0]["operation"]) for item in candidates]
        raise TransportContractError(
            f"转运路线必须唯一: {source!r} -> {target!r} / {target_device!r}; matches={names}"
        )

    route, values = candidates[0]
    operation_inputs: dict[str, Any] = {}
    for name, template in dict(route.get("inputs") or {}).items():
        if isinstance(template, str) and template.startswith("{") and template.endswith("}"):
            key = template[1:-1]
            operation_inputs[str(name)] = _coerce_route_value(values[key])
        else:
            operation_inputs[str(name)] = template
    resources = tuple(str(value) for value in route["resources"])
    if "robot" not in resources or "station:rail" not in resources:
        raise TransportContractError(f"转运根 operation 未声明完整运动锁: {route['operation']}")
    return TransportContract(
        resource_name=str(getattr(resource, "name", type(resource).__name__)),
        source_site=source,
        target_device=str(target_device),
        target_site=target,
        operation_name=str(route["operation"]),
        operation_inputs=operation_inputs,
        required_tool=str(route["tool"]),
        source_rail_target=int(route["source_rail_target"]),
        target_rail_target=int(route["target_rail_target"]),
        safety_anchor=str(route.get("safety_anchor") or "P1"),
        resources=resources,
        command_id=f"transport-v4-{uuid.uuid4().hex}",
    )


def _load_catalog(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    if raw.get("schema") != "unilab.ptlc-transport-routes/v1":
        raise TransportContractError("转运路线 catalog schema 非法")
    if not isinstance(raw.get("routes"), list) or not isinstance(raw.get("site_aliases"), dict):
        raise TransportContractError("转运路线 catalog 不完整")
    return raw


def _normalise_site(value: object) -> str:
    return str(value or "").strip().lower().replace("/", ":").replace("_", "-")


def _resource_site_candidates(resource: object) -> list[str]:
    values: list[str] = []
    for attr in ("ptlc_site", "site", "location"):
        value = getattr(resource, attr, None)
        if isinstance(value, str) and value.strip():
            values.append(_normalise_site(value))
    metadata = getattr(resource, "metadata", None)
    if isinstance(metadata, Mapping):
        for key in ("ptlc_site", "site", "location"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                values.append(_normalise_site(value))

    chain: list[str] = []
    current = getattr(resource, "parent", None)
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        name = getattr(current, "name", None)
        if isinstance(name, str) and name.strip():
            chain.append(_normalise_site(name))
        current = getattr(current, "parent", None)
    if chain:
        values.extend(chain)
        values.append(":".join(reversed(chain)))
    name = getattr(resource, "name", None)
    if isinstance(name, str) and name.strip():
        values.append(_normalise_site(name))
    # Prefer the most specific candidate, while keeping deterministic order.
    return list(dict.fromkeys(sorted(values, key=lambda item: (-item.count(":"), -len(item), item))))


def _match_site(pattern: str, value: str) -> dict[str, str] | None:
    p = _normalise_site(pattern).split(":")
    v = _normalise_site(value).split(":")
    if len(p) != len(v):
        return None
    found: dict[str, str] = {}
    for expected, actual in zip(p, v):
        if expected.startswith("{") and expected.endswith("}"):
            found[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return found


def _coerce_route_value(value: str) -> object:
    return int(value) if value.isdigit() else value


__all__ = ["TransportContract", "TransportContractError", "compile_transport_contract"]
