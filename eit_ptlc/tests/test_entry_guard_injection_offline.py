#!/usr/bin/env python3
"""入口保证 prologue 结构契约离线测试
=====================================
功能:
    以单一真源常量表锁定 06_robot 各子流程入口 prologue 的注入形态, 防手改遗漏或误注入:
      A) 固定 P1 入口文件 (15): body 顶部三节点 = comment + call robot.home_ensure +
         run_script robot_tool_ensure(needed=表值);
      B) 可变 enter_anchor 文件 (3): body 顶部 = comment + if(enter_anchor==P1) 包裹的
         home_ensure + tool_ensure(needed=3);
      C) 不动名单 (exit 5 + tool 3 + home_check): 全文无 home_ensure / tool_ensure 引用;
      D) 卡点文件: robot_startup_check 恰含一处 home_ensure 且无 tool_ensure, 且无 require_anchor
         残留; rail_move_safe 含 home_ensure 且无 require_anchor 残留 (出口断言无, 二者无出口)。
    纯静态 YAML 解析, 不执行。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

_ROBOT_DIR = _PKG / "config" / "operation" / "06_robot"
_RAIL_DIR = _PKG / "config" / "operation" / "08_rail"

# 固定 P1 入口 -> 该流程固定工具 (1=吸盘/2=大夹爪/3=小夹爪)
ENTRY_TOOL = {
    "robot_suction_pick": 1, "robot_suction_put": 1,
    "robot_tank_pick": 1, "robot_tank_put": 1,
    "robot_feed_lift_pick_enter": 1,
    "robot_group_rack_pick": 2, "robot_group_rack_put": 2,
    "robot_group_staging_pick": 2, "robot_group_staging_put": 2,
    "robot_individual_pick": 3, "robot_collect_bottle_pick": 3,
    "robot_collect_holder_pick_enter": 3, "robot_collect_holder_put_enter": 3,
    "robot_scrape_holder_pick_enter": 3, "robot_scrape_holder_put_enter": 3,
}
# 可变 enter_anchor 入口 (条件式 prologue) -> needed
CONDITIONAL_ENTRY = {
    "robot_individual_put": 3, "robot_collect_bottle_put": 3, "robot_collector_return_put": 3,
}
# 不加 prologue 的名单 (exit 工位内入口 / 换刀原语自身防递归 / DEBUG helper)
NO_PROLOGUE = {
    "robot_collect_holder_pick_exit", "robot_collect_holder_put_exit",
    "robot_scrape_holder_pick_exit", "robot_scrape_holder_put_exit",
    "robot_feed_lift_pick_exit",
    "robot_tool_pick", "robot_tool_put", "robot_tool_ensure",
    "robot_home_check",
}


def _load(name: str, directory: Path = _ROBOT_DIR) -> dict:
    return yaml.safe_load((directory / f"{name}.yaml").read_text(encoding="utf-8")) or {}


def _text(name: str, directory: Path = _ROBOT_DIR) -> str:
    return (directory / f"{name}.yaml").read_text(encoding="utf-8")


class EntryGuardInjectionTests(unittest.TestCase):

    def test_fixed_p1_prologue_shape(self) -> None:
        """A) 固定 P1 入口: body[0..2] = comment + home_ensure + tool_ensure(needed=表值)。"""
        for name, needed in ENTRY_TOOL.items():
            with self.subTest(script=name):
                body = _load(name)["body"]
                self.assertEqual(body[0].get("op"), "comment")
                self.assertEqual(body[1].get("op"), "call")
                self.assertEqual(body[1].get("action"), "robot.home_ensure")
                self.assertEqual(body[2].get("op"), "run_script")
                self.assertEqual(body[2].get("script"), "robot_tool_ensure")
                self.assertEqual(body[2]["inputs"]["needed"]["lit"], needed)
                # 分支入口断言保留 (第一个业务 if 仍在)
                self.assertTrue(any(n.get("op") == "if" for n in body))

    def test_conditional_prologue_shape(self) -> None:
        """B) 可变 enter_anchor 入口: body[1] = if(enter_anchor==P1){home_ensure + tool_ensure}。"""
        for name, needed in CONDITIONAL_ENTRY.items():
            with self.subTest(script=name):
                body = _load(name)["body"]
                self.assertEqual(body[0].get("op"), "comment")
                guard = body[1]
                self.assertEqual(guard.get("op"), "if")
                self.assertEqual(guard["cond"]["left"]["var"], "enter_anchor")
                self.assertEqual(guard["cond"]["right"]["lit"], "P1")
                then = guard["then"]
                self.assertEqual(then[0].get("action"), "robot.home_ensure")
                self.assertEqual(then[1].get("script"), "robot_tool_ensure")
                self.assertEqual(then[1]["inputs"]["needed"]["lit"], needed)

    def test_no_prologue_files_clean(self) -> None:
        """C) 不动名单: 无 home_ensure 调用、无 tool_ensure 注入 (匹配 run_script 模式, 非文件自身 name)。"""
        for name in NO_PROLOGUE:
            with self.subTest(script=name):
                text = _text(name)
                self.assertNotIn("robot.home_ensure", text)
                self.assertNotIn("script: robot_tool_ensure", text)   # 注入模式; robot_tool_ensure 自身不递归

    def test_startup_check_gate(self) -> None:
        """D) robot_startup_check: 恰一处 home_ensure, 无 tool_ensure, 无 require_anchor 残留。"""
        text = _text("robot_startup_check")
        self.assertEqual(text.count("robot.home_ensure"), 1)
        self.assertNotIn("robot_tool_ensure", text)
        self.assertNotIn("robot.require_anchor", text)

    def test_rail_move_safe_gate(self) -> None:
        """D) rail_move_safe: 含 home_ensure, 无 require_anchor 残留 (确保式卡点)。"""
        text = _text("rail_move_safe", _RAIL_DIR)
        self.assertIn("robot.home_ensure", text)
        self.assertNotIn("robot.require_anchor", text)

    def test_all_06robot_files_classified(self) -> None:
        """完整性: 06_robot 下每个 yaml 恰属 ENTRY_TOOL / CONDITIONAL_ENTRY / NO_PROLOGUE 之一
        (robot_startup_check 单列为卡点, 不在三表)。防新增文件漏归类。"""
        known = set(ENTRY_TOOL) | set(CONDITIONAL_ENTRY) | set(NO_PROLOGUE) | {"robot_startup_check"}
        on_disk = {p.stem for p in _ROBOT_DIR.glob("*.yaml")}
        self.assertEqual(on_disk, known, f"未归类差异: {on_disk ^ known}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
