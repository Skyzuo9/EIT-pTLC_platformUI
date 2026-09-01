#!/usr/bin/env python3
"""中转A/B 定位气缸: transfer 层自守卫契约检查.

背景:
    中转A/B 各有一个定位气缸 (StagingA_L2 动作码 24/25), 把整板顶到基准面。原先气缸开关只在顶层
    编排 (ptlc_full_v2) 成对调用, 7 个 transfer 里 6 个零引用 —— 单跑某条
    transfer 时气缸态取决于上一次谁留下的, 会出现"往夹紧的气缸里放整板"。

    现改为每条 transfer 自持: 放板前松、放毕夹、取板前松、取单件前夹。顶层编排的同名调用保留为幂等
    段级兜底 (写是直接赋值, 同扫描周期 DONE)。

判据全静态: 只读 YAML 节点树, 不涉 PLC 或现场闭环。
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
from eit_ptlc.operation.resources import load_resource_specs  # noqa: E402
from eit_ptlc.operation.vm.schema import validate_script  # noqa: E402

_ACTIONS_DIR = _PKG / "config" / "actions"
_OPERATION_DIR = _PKG / "config" / "operation"
_TRANSFER_DIR = _OPERATION_DIR / "05_transfer"
_COLLECT_DIR = _OPERATION_DIR / "04_collect"
_RESOURCES_PATH = _PKG / "config" / "resources.yaml"

_LOCATOR_A = "staging_a.locator_a"
_LOCATOR_B = "staging_a.locator_b"


def _load_doc(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _event(node: dict) -> tuple[str, str, dict]:
    if node.get("op") == "call":
        return ("call", node.get("action", ""), node.get("args") or {})
    if node.get("op") == "run_script":
        return ("run_script", node.get("script", ""), node.get("inputs") or {})
    return (node.get("op", ""), "", {})


def _events(doc: dict) -> list[tuple[str, str, dict]]:
    """transfer 均为扁平 body (无 if/for), 直接取顶层 call / run_script."""
    return [_event(node) for node in doc.get("body", []) if node.get("op") in {"call", "run_script"}]


def _index(events: list[tuple[str, str, dict]], kind: str, name: str, *, start: int = 0) -> int:
    for i in range(start, len(events)):
        event_kind, event_name, _args = events[i]
        if event_kind == kind and event_name == name:
            return i
    raise AssertionError(f"missing event {kind}:{name}")


def _locator_calls(events: list[tuple[str, str, dict]], action: str) -> list[tuple[int, bool]]:
    """返回 [(下标, target 字面量)], 按出现顺序."""
    return [
        (i, bool(args["target"]["lit"]))
        for i, (kind, name, args) in enumerate(events)
        if kind == "call" and name == action
    ]


# 整板进出: (脚本, 气缸动作, 被守卫的机器人整板动作, 期望的 target 序列)
_PLATE_CASES = (
    ("transfer_collector_rack_to_staging_a", _LOCATOR_A, "robot_group_staging_put", [False, True]),
    ("transfer_bottle_rack_to_staging_b", _LOCATOR_B, "robot_group_staging_put", [False, True]),
    ("transfer_collector_staging_a_to_rack", _LOCATOR_A, "robot_group_staging_pick", [False]),
    ("transfer_bottle_staging_b_to_rack", _LOCATOR_B, "robot_group_staging_pick", [False]),
)

# 单件取放: (脚本, 气缸动作, 被守卫的机器人单件动作)
_ITEM_CASES = (
    ("transfer_collector_staging_a_to_scrape", _LOCATOR_A, "robot_individual_pick"),
    ("transfer_bottle_staging_b_to_collect", _LOCATOR_B, "robot_individual_pick"),
    ("transfer_bottle_collect_to_staging_b", _LOCATOR_B, "robot_individual_put"),
)

# 脚本 -> 必须声明的中转区独占资源
_REQUIRED_RESOURCE = {
    "transfer_collector_rack_to_staging_a": "staging-a",
    "transfer_collector_staging_a_to_rack": "staging-a",
    "transfer_collector_staging_a_to_scrape": "staging-a",
    "transfer_bottle_rack_to_staging_b": "staging-b",
    "transfer_bottle_staging_b_to_rack": "staging-b",
    "transfer_bottle_staging_b_to_collect": "staging-b",
    "transfer_bottle_collect_to_staging_b": "staging-b",
}


class StagingLocatorTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_ACTIONS_DIR)
        cls.docs = {path.stem: _load_doc(path) for path in sorted(_TRANSFER_DIR.glob("*.yaml"))}
        cls.collect_docs = {path.stem: _load_doc(path) for path in sorted(_COLLECT_DIR.glob("*.yaml"))}
        cls.specs = load_resource_specs(_RESOURCES_PATH)

    def test_transfer_scripts_validate(self) -> None:
        valid_actions = {action.name for action in self.registry.list()}
        for name, doc in self.docs.items():
            with self.subTest(script=name):
                self.assertEqual(validate_script(doc, valid_actions=valid_actions), [])

    def test_plate_transfers_release_before_and_clamp_after(self) -> None:
        """整板: 放板 = 松→放→夹; 取板 = 松→取 (终态松开, 区已空不夹空气)."""
        for script, action, guarded, expected in _PLATE_CASES:
            with self.subTest(script=script):
                events = _events(self.docs[script])
                calls = _locator_calls(events, action)
                self.assertEqual([target for _i, target in calls], expected)

                guarded_at = _index(events, "run_script", guarded)
                # 第一次调用必为松开, 且在被守卫动作之前
                self.assertLess(calls[0][0], guarded_at)
                self.assertIs(calls[0][1], False)
                if len(expected) == 2:
                    # 放板类: 夹紧在放板之后, 且是脚本最后一个事件 (终态自包含)
                    self.assertGreater(calls[1][0], guarded_at)
                    self.assertEqual(calls[1][0], len(events) - 1)

    def test_item_transfers_clamp_plate_before_touching_it(self) -> None:
        """单件: 取/放单件前必须压住整板, 否则小夹爪会把整板带走 / 插孔失准."""
        for script, action, guarded in _ITEM_CASES:
            with self.subTest(script=script):
                events = _events(self.docs[script])
                calls = _locator_calls(events, action)
                self.assertTrue(calls, f"{script} 缺少 {action} 调用")
                self.assertIs(calls[0][1], True)
                self.assertLess(calls[0][0], _index(events, "run_script", guarded))

    def test_every_staging_transfer_declares_its_staging_resource(self) -> None:
        """中转区独占资源须声明在脚本根 (schema 只允许 exclusive 出现在根)."""
        for script, resource in _REQUIRED_RESOURCE.items():
            with self.subTest(script=script):
                self.assertEqual(self.specs[resource].mode, "exclusive")
                self.assertIn(resource, self.docs[script].get("resources") or [])

    def test_no_staging_transfer_is_left_unguarded(self) -> None:
        """回归网: 05_transfer 下每条脚本都必须碰过 locator —— 新增 transfer 不许漏守卫."""
        for script, doc in self.docs.items():
            with self.subTest(script=script):
                actions = {name for kind, name, _args in _events(doc) if kind == "call"}
                self.assertTrue(
                    actions & {_LOCATOR_A, _LOCATOR_B},
                    f"{script} 未声明中转定位气缸目标态 (进入时自守卫, 勿依赖调用方留下的气缸态)",
                )

    def test_collect_four_stage_still_delegates_locator_upward(self) -> None:
        """所有权边界不变: 站内四段式仍不碰 locator (与 test_collect_four_stage_offline 同守)."""
        for script in ("collect_load", "collect_execute", "collect_unload"):
            with self.subTest(script=script):
                actions = {name for kind, name, _args in _events(self.collect_docs[script]) if kind == "call"}
                self.assertFalse(actions & {_LOCATOR_A, _LOCATOR_B, "collect.bottle_locator"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
