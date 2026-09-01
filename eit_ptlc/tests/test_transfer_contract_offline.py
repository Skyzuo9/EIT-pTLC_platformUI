#!/usr/bin/env python3
"""Transfer helper contract checks.

These checks guard handoff/helper scripts only. They do not claim field
clearance; robot points and PLC L2 actions still need real-machine STEP runs.
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
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"
_OPERATION_DIR = _PKG / "config" / "operation"
_TRANSFER_DIR = _OPERATION_DIR / "05_transfer"


def _load_doc(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _walk(nodes):
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("body", "then", "else", "finally"):
            yield from _walk(node.get(key))
        for branch in node.get("branches") or []:
            yield from _walk(branch)
        for handler in node.get("catch") or []:
            yield from _walk(handler.get("body"))
        for elif_branch in node.get("elifs") or []:
            yield from _walk(elif_branch.get("body"))


def _events(doc: dict) -> list[tuple[str, str, dict]]:
    events = []
    for node in _walk(doc.get("body")):
        if node.get("op") == "call":
            events.append(("call", node.get("action", ""), node.get("args") or {}))
        elif node.get("op") == "run_script":
            events.append(("run_script", node.get("script", ""), node.get("inputs") or {}))
    return events


class TransferContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.docs = {path.stem: _load_doc(path) for path in sorted(_TRANSFER_DIR.glob("*.yaml"))}

    def test_transfer_scripts_validate(self) -> None:
        valid_actions = {action.name for action in self.registry.list()}
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_transfer_rail_migrated_to_ensure(self) -> None:
        """Win B (B2/B3): 转运编排层删 rail_move_safe, 地轨改由途经 robot 原子 enter 的 rail.ensure
        接管; 仅白名单暂留 (中间夹工位气缸 PLC 动作, 待刮板站一并迁移 + 真机确认)。

        rail 语义正确性 (途经点 rail == 设槽) 由 test_rail_point_consistency (走图认 rail.ensure) +
        test_rail_ensure_injection 全局守护; 端到端接管由 test_rail_ensure_flow_takeover 于 sim 佐证。
        本用例只守"迁移进度": 非白名单转运编排层零 rail_move_safe/rail.move, 白名单暂留。
        """
        # 暂留白名单: staging_a locator / photoscrape press 等工位气缸夹在移轨与取放之间, 逐处判定+真机确认后再删
        still_wrapped = {"transfer_collector_staging_a_to_scrape"}
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                events = _events(doc)
                has_safe = any(kind == "run_script" and script == "rail_move_safe"
                               for kind, script, _ in events)
                has_direct = any(kind == "call" and action == "rail.move"
                                 for kind, action, _ in events)
                if name in still_wrapped:
                    self.assertTrue(has_safe, f"{name} 应仍含 rail_move_safe (白名单暂留)")
                else:
                    self.assertFalse(has_safe, f"{name} 编排层应已无 rail_move_safe (迁移到 rail.ensure)")
                    self.assertFalse(has_direct, f"{name} 编排层不应有裸 rail.move")
                self.assertIn("station:rail", doc.get("resources") or [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
