"""离线: 原子流程校验器 (flowspec.validate_flow) 合成用例.

覆盖:
    1. R1 资源闭合律: 动作足迹缺声明 -> 报; with_resources 覆盖 -> 过; 后代脚本根声明并入
    2. R2 HITL 一致律 (双向)
    3. W1/W2 树级复查 (跨 run_script 边界)
    4. flow 块形状 (schema._validate_flow_block, 经 validate_script)
    5. 动作足迹推导 (robot 并入地轨 / plc_l2 按 station / host 为空)

运行:
    & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_flowspec_offline.py -v
"""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.operation.flowspec import action_footprint, validate_flow  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402

_MODES = {
    "robot": "exclusive", "station:rail": "exclusive", "station:sampling": "exclusive",
    "station:develop": "exclusive", "device:vacuum_pump": "shared",
}


@dataclass
class _ADef:
    name: str
    kind: str
    station: str = ""


class _Registry:
    def __init__(self, defs: list[_ADef]) -> None:
        self._map = {d.name: d for d in defs}

    def get(self, name: str) -> _ADef:
        return self._map[name]


_REGISTRY = _Registry([
    _ADef("robot.move", "robot"),
    _ADef("sampling.init", "plc_l2", "sampling"),
    _ADef("develop.drain", "plc_l2", "develop"),
    _ADef("develop.wait_level", "host"),
])


def _flow_doc(body: list, *, resources=None, flow=None, name="t") -> dict:
    return {"schema": "ptlc.script/v1", "kind": "operation", "name": name, "vars": [],
            "resources": resources if resources is not None else [],
            "flow": flow or {"atomic": True, "sample": "none", "from": "none",
                             "to": "none", "hitl": "none", "retry": "restart"},
            "body": body}


def _validate(doc, index=None) -> list[str]:
    index = index or {}
    return validate_flow(doc, resolve=lambda n: index[n], registry=_REGISTRY,
                         resource_modes=_MODES)


class ClosureLawTest(unittest.TestCase):
    def test_missing_footprint_rejected(self) -> None:
        doc = _flow_doc([{"op": "call", "action": "sampling.init"}])
        errors = _validate(doc)
        self.assertTrue(any("R1" in e and "station:sampling" in e for e in errors), errors)

    def test_declared_footprint_passes(self) -> None:
        doc = _flow_doc([{"op": "call", "action": "sampling.init"}],
                        resources=["station:sampling"])
        self.assertEqual(_validate(doc), [])

    def test_robot_footprint_includes_rail(self) -> None:
        self.assertEqual(action_footprint(_ADef("x", "robot")),
                         frozenset({"robot", "station:rail"}))
        doc = _flow_doc([{"op": "call", "action": "robot.move"}], resources=["robot"])
        errors = _validate(doc)
        self.assertTrue(any("station:rail" in e for e in errors), "robot 足迹须并入地轨")

    def test_region_covers_footprint(self) -> None:
        doc = _flow_doc([{"op": "with_resources", "resources": ["station:develop"],
                          "body": [{"op": "call", "action": "develop.drain"}]}])
        self.assertEqual(_validate(doc), [], "区间覆盖的足迹不要求根声明 (s6 形态)")

    def test_descendant_root_declaration_merged(self) -> None:
        sub = {"name": "sub", "resources": ["station:sampling"],
               "body": [{"op": "call", "action": "develop.wait_level"}]}
        doc = _flow_doc([{"op": "run_script", "script": "sub"}])
        errors = _validate(doc, {"sub": sub})
        self.assertTrue(any("R1" in e and "station:sampling" in e for e in errors),
                        "后代脚本根声明必须并入闭合律")

    def test_host_action_no_footprint(self) -> None:
        doc = _flow_doc([{"op": "call", "action": "develop.wait_level"}])
        self.assertEqual(_validate(doc), [])


class HitlLawTest(unittest.TestCase):
    def test_human_requires_confirm(self) -> None:
        doc = _flow_doc([{"op": "human", "kind": "confirm"}])
        errors = _validate(doc)
        self.assertTrue(any("R2" in e for e in errors))

    def test_confirm_requires_human(self) -> None:
        doc = _flow_doc([], flow={"atomic": True, "sample": "none", "from": "none",
                                  "to": "none", "hitl": "confirm", "retry": "restart"})
        errors = _validate(doc)
        self.assertTrue(any("R2" in e for e in errors))

    def test_human_in_descendant_counts(self) -> None:
        sub = {"name": "sub", "body": [{"op": "human", "kind": "confirm"}]}
        doc = _flow_doc([{"op": "run_script", "script": "sub"}],
                        flow={"atomic": True, "sample": "none", "from": "none",
                              "to": "none", "hitl": "confirm", "retry": "restart"})
        self.assertEqual(_validate(doc, {"sub": sub}), [])


class DeadlockLawTest(unittest.TestCase):
    def test_w2_root_exclusive_forbids_region_exclusive_in_descendant(self) -> None:
        sub = {"name": "sub", "body": [
            {"op": "with_resources", "resources": ["station:develop"], "body": []}]}
        doc = _flow_doc([{"op": "run_script", "script": "sub"}], resources=["robot"])
        errors = _validate(doc, {"sub": sub})
        self.assertTrue(any("W2" in e for e in errors), errors)

    def test_w1_nested_same_exclusive(self) -> None:
        doc = _flow_doc([
            {"op": "with_resources", "resources": ["station:develop"], "body": [
                {"op": "with_resources", "resources": ["station:develop"], "body": []}]}])
        errors = _validate(doc)
        self.assertTrue(any("W1" in e for e in errors), errors)

    def test_region_exclusive_ok_when_root_empty(self) -> None:
        doc = _flow_doc([
            {"op": "with_resources", "resources": ["station:develop"],
             "body": [{"op": "call", "action": "develop.drain"}]}])
        self.assertEqual(_validate(doc), [])

    def test_non_atomic_rejected(self) -> None:
        doc = _flow_doc([])
        doc.pop("flow")
        errors = _validate(doc)
        self.assertTrue(any("不是原子流程" in e for e in errors))


class FlowBlockShapeTest(unittest.TestCase):
    """flow 块单文件形状 (schema 层)."""

    def _errors(self, flow) -> list[str]:
        doc = {"schema": "ptlc.script/v1", "kind": "operation", "name": "t",
               "vars": [{"name": "tank", "scope": "local", "type": "INT", "io": "in",
                         "default": 1}],
               "flow": flow, "body": []}
        return validate_script(doc)

    def test_valid_shapes(self) -> None:
        self.assertEqual(self._errors({"atomic": True, "sample": "required",
                                       "from": "tank:{tank}", "to": "scrape_table",
                                       "hitl": "none", "retry": "manual"}), [])
        self.assertEqual(self._errors({"atomic": True, "sample": "required",
                                       "from": "same", "to": "same",
                                       "hitl": "none", "retry": "restart"}), [])

    def test_bad_shapes(self) -> None:
        self.assertTrue(self._errors({"atomic": True, "sample": "none",
                                      "from": "feedlift", "to": "none"}))
        self.assertTrue(self._errors({"atomic": True, "sample": "required",
                                      "from": "same", "to": "waste"}))
        self.assertTrue(self._errors({"atomic": True, "retry": "loop"}))
        self.assertTrue(self._errors({"atomic": True, "from": "tank:{nope}",
                                      "to": "waste", "sample": "required"}))
        self.assertTrue(self._errors({"atomic": True, "unknown_key": 1}))


if __name__ == "__main__":
    unittest.main()
