#!/usr/bin/env python3
"""同工位取放吸附基准一致性守卫 (P64 事故根因封印).

功能:
    锁死"同一工位取板与放板必须共用同一基点"的不变量, 防止再次教出双基点
    造成吸附基准跳变 (历史事故: 刮板位取板点 P64 = P65 - 22mm, 照抄点样位
    P20-P19 差值而无载具移动正当性, 下游展缸/下料示教全部继承该偏差).
断言:
    1) robot_suction_pick/put 的 spotting 分支吸/放基准均为 P19, scrape 分支均为 P65;
    2) meta 派生族共基: scrape.plate-pick.*/plate-put.* base 全为 P65,
       spotting.pick.*/put.* base 全为 P19;
    3) robot_tank_pick/put 第 N 缸分支吸/放基准相同且为 P11..P18;
    4) 弃用点 P64/P20 不再被任何 operation 的运动/锚定参数引用
       (只查 args 字面量, 不查 comment 文本).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

_OPDIR = _PKG / "config" / "operation"
_META = _PKG / "config" / "points" / "robot" / "robot_points_meta.json"


def _load_operation(name: str) -> dict:
    path = _OPDIR / "06_robot" / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _walk(nodes):
    # 拷自 test_photoscrape_four_stage_offline._walk: 按文档序深度优先, 覆盖全部分支容器
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        yield node
        for key in ("then", "else", "body", "finally"):
            yield from _walk(node.get(key))
        for branch in node.get("branches") or []:
            yield from _walk(branch)
        for handler in node.get("catch") or []:
            yield from _walk(handler.get("body"))
        for elif_branch in node.get("elifs") or []:
            yield from _walk(elif_branch.get("body"))


def _branch(script: dict, selector: str, value) -> list[dict]:
    # 拷自 test_spotting_vision_correct_offline._branch: 入口 prologue 后按 op 定位首个业务 if
    root = next(n for n in script["body"] if n.get("op") == "if")
    if root["cond"]["left"] == {"var": selector} and root["cond"]["right"] == {"lit": value}:
        return root["then"]
    for branch in root.get("elifs", []):
        if branch["cond"]["left"] == {"var": selector} and branch["cond"]["right"] == {"lit": value}:
            return branch["body"]
    raise AssertionError(f"branch {selector}={value!r} not found")


def _lit(args: dict, key: str):
    value = args.get(key)
    return value.get("lit") if isinstance(value, dict) else None


def _grip_basis(body: list[dict], tool_act: str) -> str:
    """返回分支内紧邻 tool_action==tool_act 之前的 move_to_point 目标, 即吸/放发生点。"""
    last_move = None
    for node in _walk(body):
        if node.get("op") != "call":
            continue
        args = node.get("args") or {}
        if node.get("action") == "robot.move_to_point":
            last_move = _lit(args, "point_id_or_robot_name")
        elif node.get("action") == "robot.tool_action" and _lit(args, "action") == tool_act:
            if last_move is None:
                raise AssertionError(f"{tool_act} 之前没有 move_to_point")
            return last_move
    raise AssertionError(f"分支内未找到 tool_action {tool_act}")


class PickPutBasisConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suction_pick = _load_operation("robot_suction_pick")
        cls.suction_put = _load_operation("robot_suction_put")
        cls.tank_pick = _load_operation("robot_tank_pick")
        cls.tank_put = _load_operation("robot_tank_put")

    def test_station_pick_put_share_basis(self) -> None:
        """1) 同工位吸附点 == 释放点: spotting=P19, scrape=P65。"""
        expected = {"spotting": "P19", "scrape": "P65"}
        for station, point in expected.items():
            pick = _grip_basis(_branch(self.suction_pick, "station_id", station), "suction-on")
            put = _grip_basis(_branch(self.suction_put, "station_id", station), "suction-off")
            self.assertEqual((station, pick), (station, point), "取板吸附基准漂移")
            self.assertEqual((station, put), (station, point), "放板释放基准漂移")

    def test_meta_derived_families_share_base(self) -> None:
        """2) meta 派生族共基: 同工位 pick/put 进退点必须挂同一 base。"""
        supplement = json.loads(_META.read_text(encoding="utf-8")).get("supplement") or []
        expected_prefix_base = {
            "scrape.plate-pick.": "P65",
            "scrape.plate-put.": "P65",
            "spotting.pick.": "P19",
            "spotting.put.": "P19",
        }
        seen = {prefix: 0 for prefix in expected_prefix_base}
        for record in supplement:
            point_id = str(record.get("point_id", ""))
            for prefix, base in expected_prefix_base.items():
                if point_id.startswith(prefix):
                    seen[prefix] += 1
                    self.assertEqual(
                        record.get("base_point"), base,
                        f"{point_id} 的 base_point 应为 {base}")
        for prefix, count in seen.items():
            self.assertEqual(count, 4, f"派生族 {prefix}* 应有 4 条记录")

    def test_tank_pick_put_share_basis_per_tank(self) -> None:
        """3) 展缸逐缸: 第 N 缸吸附点 == 释放点 == P(10+N)。"""
        for n in range(1, 9):
            pick = _grip_basis(_branch(self.tank_pick, "tank_id", n), "suction-on")
            put = _grip_basis(_branch(self.tank_put, "tank_id", n), "suction-off")
            self.assertEqual((n, pick), (n, put), "同缸取放基点不一致")
            self.assertEqual((n, pick), (n, f"P{10 + n}"), "缸位与点号配对漂移")

    def test_retired_points_not_referenced(self) -> None:
        """4) 弃用点封印: P64/P20 不出现在任何 operation 的运动/锚定参数里。"""
        retired = {"P64", "P20"}
        violations: list[str] = []
        for path in sorted(_OPDIR.rglob("*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if doc.get("kind") != "operation":
                continue
            for node in _walk(doc.get("body")):
                if node.get("op") != "call":
                    continue
                args = node.get("args") or {}
                target = None
                if node.get("action") == "robot.move_to_point":
                    target = _lit(args, "point_id_or_robot_name")
                elif node.get("action") in {"robot.require_anchor", "robot.home_ensure"}:
                    target = _lit(args, "point_id")
                if target in retired:
                    violations.append(f"{path.name}: {node.get('action')} -> {target}")
        self.assertEqual(violations, [], "弃用点被引用:\n  " + "\n  ".join(violations))


if __name__ == "__main__":
    unittest.main()
