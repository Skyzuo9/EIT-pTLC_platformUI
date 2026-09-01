#!/usr/bin/env python3
"""PALLASVision correction operation contract tests.

These tests intentionally avoid running the full robot VM route. The production
contract here is structural: PALLAS correction captures Rz first, re-captures
after Rz correction, gates residual Rz, and only then carries the final
correction into the spotting contact segment.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402


CFG_DIR = _PKG / "config"


def _load_operation(name: str) -> dict:
    path = CFG_DIR / "operation" / "06_robot" / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _calls(node, action: str | None = None):
    out = []
    for item in _walk(node):
        if item.get("op") == "call" and (action is None or item.get("action") == action):
            out.append(item)
    return out


def _branch(script: dict, selector: str, value) -> list[dict]:
    # 入口 prologue (comment + home_ensure + tool_ensure) 后, 首个业务 if 不再是 body[0]; 按 op 定位
    root = next(n for n in script["body"] if n.get("op") == "if")
    if root["cond"]["left"] == {"var": selector} and root["cond"]["right"] == {"lit": value}:
        return root["then"]
    for branch in root.get("elifs", []):
        if branch["cond"]["left"] == {"var": selector} and branch["cond"]["right"] == {"lit": value}:
            return branch["body"]
    raise AssertionError(f"branch {selector}={value!r} not found")


def _move_to(body: list[dict], point: str) -> dict:
    for item in body:
        if item.get("op") == "call" and item.get("action") == "robot.move_to_point":
            args = item.get("args", {})
            if args.get("point_id_or_robot_name") == {"lit": point}:
                return item
    raise AssertionError(f"move_to_point {point!r} not found")


def _moves_to(body: list[dict], point: str) -> list[dict]:
    return [
        item
        for item in body
        if item.get("op") == "call"
        and item.get("action") == "robot.move_to_point"
        and item.get("args", {}).get("point_id_or_robot_name") == {"lit": point}
    ]


def _assign_vars(calls: list[dict]) -> list[str | None]:
    return [item.get("assign", {}).get("var") for item in calls]


class PallasVisionOperationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(CFG_DIR / "app.yaml")
        cls.registry = ActionRegistry.load(cfg.plc.nodes_file.parent / "actions")
        cls.valid_actions = {a.name for a in cls.registry.list()}

    def test_actions_are_registered_on_formal_vision_path(self) -> None:
        self.assertEqual(self.registry.get("vision.capture_plate_offset").kind, "vision")
        with self.assertRaises(KeyError):
            self.registry.get("robot.capture_plate_offset")

    def test_robot_operations_validate_against_action_registry(self) -> None:
        for name in ("robot_suction_put", "robot_tank_put"):
            validate_script(_load_operation(name), valid_actions=self.valid_actions)

    def test_spotting_moves_to_photo_point_then_calls_pallas(self) -> None:
        script = _load_operation("robot_suction_put")
        body = _branch(script, "station_id", "spotting")
        points = [
            item.get("args", {}).get("point_id_or_robot_name", {}).get("lit")
            for item in body
            if item.get("op") == "call" and item.get("action") == "robot.move_to_point"
        ]
        p86_idx = points.index("P86")
        p19_idx = points.index("P19")
        self.assertLess(p86_idx, p19_idx)
        actions = [item.get("action") for item in body if item.get("op") == "call"]
        self.assertIn("vision.capture_plate_offset", actions)
        self.assertNotIn("robot.capture_plate_offset", actions)

    def test_spotting_correction_recaptures_after_rz_then_gates_residual(self) -> None:
        body = _branch(_load_operation("robot_suction_put"), "station_id", "spotting")
        captures = [item for item in body if item.get("op") == "call" and item.get("action") == "vision.capture_plate_offset"]
        self.assertEqual(_assign_vars(captures[:2]), ["voff_rz", "voff_xy"])
        self.assertTrue(all(item.get("args", {}).get("apply_rz") == {"lit": True} for item in captures[:2]))

        threshold_checks = [
            item for item in body
            if item.get("op") == "if"
            and item.get("cond", {}).get("binop") == ">"
            and item.get("cond", {}).get("left", {}).get("call") == "abs"
        ]
        self.assertEqual(len(threshold_checks), 1)
        self.assertEqual(threshold_checks[0]["cond"]["right"], {"var": "drz_threshold_deg"})
        self.assertEqual(threshold_checks[0]["then"][0]["error"], "VISION_RZ_NOT_CONVERGED")

        p86_correction_moves = [
            item for item in _moves_to(body, "P86")
            if item.get("args", {}).get("motion") == {"lit": "move_l"}
        ]
        self.assertEqual(len(p86_correction_moves), 2)

        rz_args = p86_correction_moves[0]["args"]
        self.assertEqual(rz_args["dx_mm"], {"lit": 0.0})
        self.assertEqual(rz_args["dy_mm"], {"lit": 0.0})
        self.assertEqual(rz_args["drz_deg"], {"field": {"var": "voff_rz"}, "name": "drz_deg"})

        xy_args = p86_correction_moves[1]["args"]
        self.assertEqual(xy_args["dx_mm"], {"field": {"var": "voff_xy"}, "name": "dx_mm"})
        self.assertEqual(xy_args["dy_mm"], {"field": {"var": "voff_xy"}, "name": "dy_mm"})
        self.assertEqual(xy_args["drz_deg"], {"field": {"var": "voff_rz"}, "name": "drz_deg"})

    def test_spotting_contact_segment_carries_closed_loop_offset(self) -> None:
        body = _branch(_load_operation("robot_suction_put"), "station_id", "spotting")
        for point in ("spotting.put.approach_near", "P19", "spotting.put.retreat_near"):
            args = _move_to(body, point)["args"]
            self.assertEqual(args["dx_mm"], {"field": {"var": "voff_xy"}, "name": "dx_mm"})
            self.assertEqual(args["dy_mm"], {"field": {"var": "voff_xy"}, "name": "dy_mm"})
            self.assertEqual(args["drz_deg"], {"field": {"var": "voff_rz"}, "name": "drz_deg"})
        self.assertNotIn("dx_mm", _move_to(body, "spotting.put.approach_far")["args"])
        self.assertNotIn("dx_mm", _move_to(body, "spotting.put.retreat_far")["args"])

    def test_scrape_and_tank_do_not_call_later_correction(self) -> None:
        suction = _load_operation("robot_suction_put")
        scrape = _branch(suction, "station_id", "scrape")
        self.assertFalse(_calls(scrape, "vision.capture_plate_offset"))
        self.assertFalse(_calls(scrape, "robot.capture_plate_offset"))
        for point in ("scrape.plate-put.approach_near", "P65", "scrape.plate-put.retreat_near"):
            self.assertNotIn("dx_mm", _move_to(scrape, point)["args"])

        tank = _load_operation("robot_tank_put")
        self.assertNotIn("voff", {v.get("name") for v in tank.get("vars", []) if isinstance(v, dict)})
        self.assertFalse(_calls(tank, "vision.capture_plate_offset"))
        self.assertFalse(_calls(tank, "robot.capture_plate_offset"))
        self.assertFalse(any(k in item.get("args", {}) for item in _calls(tank, "robot.move_to_point") for k in ("dx_mm", "dy_mm", "drz_deg")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
