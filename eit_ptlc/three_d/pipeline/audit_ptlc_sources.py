"""PTLC 动画阶段 0 真源审计。

只读取上位机配置，不修改点表、动作或流程。输出中的 source 一律是相对路径，
避免把开发机绝对路径带入后续浏览器资产。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - 仅用于给部署环境清晰报错
    raise SystemExit("缺少 PyYAML；请在管线 Python 环境安装 pyyaml") from exc


EXPECTED = {
    "actions": 93,
    "operations": 101,
    "axes": 11,
    "mechanisms": 51,
    "robot_points": 74,
    "zero_joint_placeholders": 4,
}


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _tree_hash(root: Path, pattern: str = "*.yaml") -> str:
    """按相对路径和内容生成稳定 SHA-256；文件改名也会触发变化。"""
    digest = hashlib.sha256()
    for path in sorted(root.rglob(pattern)):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_calls(value: Any, actions: set[str], scripts: set[str]) -> None:
    if isinstance(value, dict):
        if value.get("op") == "call" and isinstance(value.get("action"), str):
            actions.add(value["action"])
        if value.get("op") == "run_script" and isinstance(value.get("script"), str):
            scripts.add(value["script"])
        for child in value.values():
            _walk_calls(child, actions, scripts)
    elif isinstance(value, list):
        for child in value:
            _walk_calls(child, actions, scripts)


def _actions(control_root: Path) -> list[dict[str, Any]]:
    base = control_root / "config" / "actions"
    result: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.yaml")):
        for action_id, spec in _read_yaml(path).items():
            if not isinstance(spec, dict) or "kind" not in spec:
                continue
            result.append(
                {
                    "id": action_id,
                    "kind": spec.get("kind"),
                    "label": spec.get("label", ""),
                    "params": [
                        item.get("name")
                        for item in spec.get("params", [])
                        if isinstance(item, dict) and item.get("name")
                    ],
                    "source": path.relative_to(control_root).as_posix(),
                }
            )
    return result


def _operations(control_root: Path) -> list[dict[str, Any]]:
    base = control_root / "config" / "operation"
    result: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.yaml")):
        document = _read_yaml(path)
        actions: set[str] = set()
        scripts: set[str] = set()
        _walk_calls(document, actions, scripts)
        result.append(
            {
                "name": document.get("name", path.stem),
                "group": path.parent.name,
                "label": document.get("label", ""),
                "direct_actions": sorted(actions),
                "scripts": sorted(scripts),
                "source": path.relative_to(control_root).as_posix(),
            }
        )
    return result


def _manual(control_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    path = control_root / "config" / "manual_points.yaml"
    stations = _read_yaml(path).get("stations", {})
    axes: list[dict[str, Any]] = []
    mechanisms: list[dict[str, Any]] = []
    for station, spec in stations.items():
        if not isinstance(spec, dict):
            continue
        for axis in spec.get("axes", []):
            axes.append(
                {
                    "id": axis["id"],
                    "station": station,
                    "label": axis.get("label", ""),
                    "struct": axis.get("struct", ""),
                    "note": axis.get("note", ""),
                }
            )
        for mechanism in spec.get("cylinders", []):
            has_on = mechanism.get("fb_on") is not None
            has_off = mechanism.get("fb_off") is not None
            mechanisms.append(
                {
                    "id": mechanism["id"],
                    "station": station,
                    "label": mechanism.get("label", ""),
                    "feedback": "both" if has_on and has_off else "partial" if has_on or has_off else "commanded",
                    "note": mechanism.get("note", ""),
                }
            )
    return axes, mechanisms


def _robot_points(control_root: Path) -> dict[str, Any]:
    path = control_root / "config" / "points" / "robot" / "robot_points.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    points = document if isinstance(document, list) else document.get("points", [])
    measured = [
        point
        for point in points
        if isinstance(point, dict)
        and isinstance(point.get("joint"), list)
        and len(point["joint"]) == 6
    ]
    zero = [
        point
        for point in measured
        if all(abs(float(value)) < 1e-12 for value in point["joint"])
    ]
    return {
        "count": len(measured),
        "zero_joint_placeholders": len(zero),
        "zero_joint_ids": [point.get("id") for point in zero],
        "valid_for_calibration": len(measured) - len(zero),
    }


def audit(control_root: Path) -> dict[str, Any]:
    action_base = control_root / "config" / "actions"
    operation_base = control_root / "config" / "operation"
    manual_path = control_root / "config" / "manual_points.yaml"
    point_path = control_root / "config" / "points" / "robot" / "robot_points.json"
    for required in (action_base, operation_base, manual_path, point_path):
        if not required.exists():
            raise FileNotFoundError(f"缺少 PTLC 真源: {required}")

    actions = _actions(control_root)
    operations = _operations(control_root)
    axes, mechanisms = _manual(control_root)
    points = _robot_points(control_root)

    action_ids = {item["id"] for item in actions}
    operation_ids = {item["name"] for item in operations}
    direct_action_refs = {
        action_id
        for operation in operations
        for action_id in operation["direct_actions"]
    }
    script_refs = {
        script
        for operation in operations
        for script in operation["scripts"]
    }
    used_by: dict[str, list[str]] = defaultdict(list)
    for operation in operations:
        for action_id in operation["direct_actions"]:
            used_by[action_id].append(operation["name"])
    for action in actions:
        action["used_by"] = sorted(used_by[action["id"]])

    return {
        "schema": "ptlc.source-audit/v1",
        "counts": {
            "actions": len(actions),
            "operations": len(operations),
            "referenced_actions": len(direct_action_refs),
            "unreferenced_actions": len(action_ids - direct_action_refs),
            "axes": len(axes),
            "mechanisms": len(mechanisms),
            "robot_points": points["count"],
            "zero_joint_placeholders": points["zero_joint_placeholders"],
            "valid_robot_points": points["valid_for_calibration"],
        },
        "groups": {
            "action_kinds": dict(sorted(Counter(item["kind"] for item in actions).items())),
            "operations": dict(sorted(Counter(item["group"] for item in operations).items())),
            "manual_axes": dict(sorted(Counter(item["station"] for item in axes).items())),
            "mechanisms": dict(sorted(Counter(item["station"] for item in mechanisms).items())),
        },
        "hashes": {
            "actions_tree": _tree_hash(action_base),
            "operations_tree": _tree_hash(operation_base),
            "manual_points": _file_hash(manual_path),
            "robot_points": _file_hash(point_path),
        },
        "unknown_action_refs": sorted(direct_action_refs - action_ids),
        "unknown_script_refs": sorted(script_refs - operation_ids),
        "unreferenced_actions": sorted(action_ids - direct_action_refs),
        "robot_points": points,
        "actions": actions,
        "operations": operations,
        "manual_axes": axes,
        "mechanisms": mechanisms,
    }


def _failures(report: dict[str, Any]) -> list[str]:
    failures = []
    counts = report["counts"]
    for key, expected in EXPECTED.items():
        if counts.get(key) != expected:
            failures.append(f"{key}: expected {expected}, got {counts.get(key)}")
    if report["unknown_action_refs"]:
        failures.append("未知动作引用: " + ", ".join(report["unknown_action_refs"]))
    if report["unknown_script_refs"]:
        failures.append("未知流程引用: " + ", ".join(report["unknown_script_refs"]))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 PTLC 动作、流程、手动点表和机器人点表")
    parser.add_argument(
        "--control-root",
        default=os.environ.get("PTLC_CONTROL_ROOT"),
        help="eit_ptlc 根目录；缺省读取 PTLC_CONTROL_ROOT",
    )
    parser.add_argument("--check", action="store_true", help="按阶段 0 基线严格验收")
    parser.add_argument("--summary", action="store_true", help="只输出摘要")
    args = parser.parse_args()
    if not args.control_root:
        parser.error("请传 --control-root 或设置 PTLC_CONTROL_ROOT")

    report = audit(Path(args.control_root).resolve())
    failures = _failures(report) if args.check else []
    if args.summary:
        payload = {
            key: report[key]
            for key in ("schema", "counts", "groups", "hashes", "unknown_action_refs", "unknown_script_refs", "unreferenced_actions")
        }
        payload["check"] = {"ok": not failures, "failures": failures}
    else:
        payload = report
        payload["check"] = {"ok": not failures, "failures": failures}
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
