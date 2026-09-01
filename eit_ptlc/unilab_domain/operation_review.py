"""Safe PlatformUI operation review and atomic execution boundary.

The generated UniLab review workflows contain the real PlatformUI action
catalog as *disabled* nodes so operators can inspect the complete expansion.
Only :func:`run_review_root` is executable: it submits the unchanged root
operation once, leaving branching, HITL and the root ``ResourceGate`` inside
PlatformUI.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import yaml

from eit_ptlc.unilab_domain.runtime_port import PtlcRuntimePort


OPERATIONS_DIR = Path(__file__).resolve().parents[1] / "config" / "operation"


def load_operation_document(operation_name: str) -> dict[str, Any]:
    """Load one uniquely named PlatformUI operation from the active source tree."""

    matches: list[dict[str, Any]] = []
    for path in OPERATIONS_DIR.rglob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("name") == operation_name:
            matches.append(raw)
    if len(matches) != 1:
        raise ValueError(f"PlatformUI operation 必须唯一存在: {operation_name}")
    return matches[0]


def canonical_node_sha256(node: dict[str, Any]) -> str:
    """Return the stable digest used by generated review provenance markers."""

    payload = yaml.safe_dump(
        node,
        allow_unicode=True,
        sort_keys=True,
        width=120,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verify_review_node(
    *,
    operation_name: str,
    node_path: str,
    control_kind: str,
    expected_sha256: str,
) -> dict[str, str]:
    """Verify that a disabled review marker still names its source VM node.

    This action is deliberately read-only.  Review workflows keep it disabled,
    but a manual invocation is still meaningful: it detects source drift rather
    than acting as a no-op placeholder.
    """

    value: Any = load_operation_document(operation_name)
    tokens = [token for token in node_path.split("/") if token]
    for token in tokens:
        if isinstance(value, list):
            try:
                value = value[int(token)]
            except (ValueError, IndexError) as error:
                raise ValueError(
                    f"无效 PlatformUI 节点路径: {operation_name}@{node_path}"
                ) from error
        elif isinstance(value, dict) and token in value:
            value = value[token]
        else:
            raise ValueError(f"无效 PlatformUI 节点路径: {operation_name}@{node_path}")
    if not isinstance(value, dict):
        raise ValueError(f"PlatformUI 节点不是对象: {operation_name}@{node_path}")
    actual_kind = str(value.get("op") or "")
    if actual_kind != control_kind:
        raise ValueError(
            f"PlatformUI 节点类型漂移: {operation_name}@{node_path} "
            f"expected={control_kind} actual={actual_kind}"
        )
    actual_sha256 = canonical_node_sha256(value)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"PlatformUI 节点内容漂移: {operation_name}@{node_path}"
        )
    return {
        "operation_name": operation_name,
        "node_path": node_path,
        "control_kind": control_kind,
        "status": "VERIFIED",
    }


def verify_operation_call(
    *,
    operation_name: str,
    inputs_json: str,
    expected_sha256: str,
) -> dict[str, str]:
    """Verify one display-only operation call and its formatted arguments."""

    document = load_operation_document(operation_name)
    inputs = json.loads(inputs_json or "{}")
    if not isinstance(inputs, dict):
        raise ValueError("inputs_json 必须编码 JSON object")
    if canonical_node_sha256(document) != expected_sha256:
        raise ValueError(f"PlatformUI operation 内容漂移: {operation_name}")
    return {
        "operation_name": operation_name,
        "inputs_json": json.dumps(inputs, ensure_ascii=False, sort_keys=True),
        "status": "VERIFIED",
    }


def bind_parallel_operation_inputs(
    *,
    inputs_json: str,
    before_path: str = "",
    collector_hole: int = 0,
    bottle_hole: int = 0,
) -> dict[str, str]:
    """Overlay live cross-segment outputs onto a caller's JSON parameters."""

    inputs = json.loads(inputs_json or "{}")
    if not isinstance(inputs, dict):
        raise ValueError("inputs_json 必须编码 JSON object")
    if before_path:
        inputs["before_path"] = before_path
    if collector_hole > 0:
        inputs["collector_hole"] = int(collector_hole)
    if bottle_hole > 0:
        inputs["bottle_hole"] = int(bottle_hole)
    return {
        "inputs_json": json.dumps(inputs, ensure_ascii=False, sort_keys=True),
    }


def _operation_output(
    result_payload: dict[str, Any], name: str, default: Any
) -> Any:
    value = result_payload.get(name, default)
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    return value


async def run_review_root(
    runtime: PtlcRuntimePort,
    *,
    operation_name: str,
    inputs_json: str,
    timeout_s: float,
) -> dict[str, Any]:
    """Submit one unchanged PlatformUI root operation and require completion."""

    # Fail before command submission if the reviewed source disappeared.
    load_operation_document(operation_name)
    inputs = json.loads(inputs_json or "{}")
    if not isinstance(inputs, dict):
        raise ValueError("inputs_json 必须编码 JSON object")
    command_id = f"operation-review-v1-{uuid.uuid4().hex}"
    result = await runtime.run_root_operation(
        operation_name,
        inputs,
        command_id=command_id,
        timeout_s=timeout_s,
    )
    status = str(result.get("status") or "UNKNOWN").upper()
    if status != "DONE":
        raise RuntimeError(
            f"PlatformUI 根 operation 未完成: {operation_name} "
            f"status={status} command_id={command_id}"
        )
    result_payload = result.get("result")
    if not isinstance(result_payload, dict):
        result_payload = {}
    return {
        "operation_name": operation_name,
        "command_id": command_id,
        "run_id": str(result.get("run_id") or command_id),
        "status": status,
        "result_json": json.dumps(result_payload, ensure_ascii=False, sort_keys=True),
        "before_path": str(_operation_output(result_payload, "before_path", "")),
        "collector_hole": int(
            _operation_output(result_payload, "collector_hole", 0) or 0
        ),
        "bottle_hole": int(
            _operation_output(result_payload, "bottle_hole", 0) or 0
        ),
    }


__all__ = [
    "bind_parallel_operation_inputs",
    "canonical_node_sha256",
    "load_operation_document",
    "run_review_root",
    "verify_operation_call",
    "verify_review_node",
]
