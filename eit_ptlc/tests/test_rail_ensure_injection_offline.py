#!/usr/bin/env python3
"""rail.ensure 注入正确性契约 (地轨第 7 维 Win B · B1)
=====================================================
功能:
    断言 tools/insert_rail_ensure 已把 rail.ensure(N) 正确注入所有空手接缝机器人原子的 enter 处。
    这是 B1 的"注入齐全且值正确"守卫, 也是 B3 契约翻面 (删字面量后由"字面量==点 rail"改判为
    "每原子·分支有正确 ensure") 的雏形。与注入脚本、rail_derive 同一真源 (branch_bodies /
    branch_rail / entry_anchor / is_home_anchor), 不另起走图。

三条断言:
    A) 每个非排除原子·每条空手接缝分支 (entry 为 home 且分支有带 rail 的 work 点): entry 锚之后
       紧跟 rail.ensure(N), 且 N == branch_rail(该分支)。—— 注入齐全 + 值正确。
    B) 非空手接缝分支 (entry 非 home / 无 rail) 的 entry 后不得是 rail.ensure。—— 未过度注入
       (非 P1 处移轨会撞 rail.move 的 P1 硬门)。
    C) 排除原子 (tank 持板 / check) 全文档无 rail.ensure。—— 排除被尊重。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.rail_derive import (  # noqa: E402
    branch_bodies, branch_rail, entry_anchor, is_home_anchor)

_POINTS = _PKG / "config" / "points" / "robot"
_ROBOT = _PKG / "config" / "operation" / "06_robot"

# 显式排除集: 呈空手接缝形态但故意不注入 rail.ensure 的机器人原子 (原 tools/insert_rail_ensure
# 一次性注入器的排除策略; 该脚本为一次性已删除, 策略随本契约测试内联留存):
#   - robot_home_check / robot_startup_check: 安全检查, 非工位取放
# 注: robot_tank_pick / robot_tank_put 曾以「持板中途显影, 保留显式 rail.move(5)」为由排除, 但那句
#     rail.move(5) 从未写进过文件 (唯一一句被 hoist 到 ptlc_full_v2 的 develop_cycle 之外), 于是单跑
#     展开-上料/下料时 auto_rail 要到臂已伸出持板才发现需移轨, 被 rail.move 的 P1 硬门拒死。现已按常规
#     在每条分支 entry 注入 rail.ensure(5), 由下面测试 A 强制 —— 排除即豁免, 豁免过的不变式没人守。
EXCLUDED_ATOMICS = frozenset({
    "robot_home_check", "robot_startup_check",
})


def _is_ensure(node) -> bool:
    return (isinstance(node, dict) and node.get("op") == "call"
            and node.get("action") == "rail.ensure")


def _ensure_target(node):
    """rail.ensure 节点的 Rail_Target_Position 字面量 (非 ensure 或缺失返回 None)。"""
    if not _is_ensure(node):
        return None
    tgt = (node.get("args") or {}).get("Rail_Target_Position")
    return tgt.get("lit") if isinstance(tgt, dict) else None


def _any_ensure(obj) -> bool:
    """递归判断结构里是否存在任一 rail.ensure 节点。"""
    if isinstance(obj, list):
        return any(_any_ensure(x) for x in obj)
    if isinstance(obj, dict):
        return _is_ensure(obj) or any(_any_ensure(v) for v in obj.values())
    return False


class RailEnsureInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = PointRegistry.load(
            _POINTS / "robot_points.json", source_version="v0.11",
            meta_path=_POINTS / "robot_points_meta.json",
        )
        cls.docs: dict[str, dict] = {}
        for f in sorted(_ROBOT.glob("robot_*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if d.get("kind") == "operation":
                cls.docs[f.stem] = d

    def test_home_seam_branches_have_correct_ensure(self) -> None:
        """A) 每条空手接缝分支 entry 后紧跟 rail.ensure(该分支 rail)。"""
        violations: list[str] = []
        for stem, doc in self.docs.items():
            if stem in EXCLUDED_ATOMICS:
                continue
            for idx, branch in enumerate(branch_bodies(doc)):
                if not is_home_anchor(entry_anchor(branch), self.reg):
                    continue
                rail = branch_rail(branch, self.reg)
                if rail is None:
                    continue
                node = branch[1] if len(branch) > 1 else None
                target = _ensure_target(node)
                if target != rail:
                    violations.append(
                        f"{stem} 分支#{idx}: entry 后应为 rail.ensure({rail}), 实得 target={target}")
        self.assertEqual(violations, [], "空手接缝原子缺正确 rail.ensure:\n  " + "\n  ".join(violations))

    def test_no_over_injection_on_non_seam_branches(self) -> None:
        """B) 非空手接缝分支 (entry 非 home / 无 rail) entry 后不得是 rail.ensure。"""
        violations: list[str] = []
        for stem, doc in self.docs.items():
            if stem in EXCLUDED_ATOMICS:
                continue
            for idx, branch in enumerate(branch_bodies(doc)):
                is_seam = is_home_anchor(entry_anchor(branch), self.reg) and branch_rail(branch, self.reg) is not None
                if is_seam:
                    continue
                node = branch[1] if len(branch) > 1 else None
                if _is_ensure(node):
                    violations.append(f"{stem} 分支#{idx}: 非空手接缝却在 entry 后注入了 rail.ensure")
        self.assertEqual(violations, [], "过度注入 rail.ensure:\n  " + "\n  ".join(violations))

    def test_excluded_atomics_have_no_ensure(self) -> None:
        """C) 排除原子 (安全检查, 非工位取放) 全文档无 rail.ensure。"""
        for stem in ("robot_home_check", "robot_startup_check"):
            doc = self.docs.get(stem)
            if doc is None:
                continue
            self.assertFalse(_any_ensure(doc.get("body")), f"{stem} 不应含 rail.ensure (安全检查, 非工位取放)")

    def test_tank_atomics_have_entry_ensure(self) -> None:
        """D) tank 系列每条分支 entry 后必须是 rail.ensure(5) —— 锁死曾漏掉入口移轨的回归。

        测试 A 已按通用规则覆盖, 此处再逐分支点名断言: tank 缸内点 (P11-P18/tank.N.*) 为 rail=5, 而
        中途点 P75/P84/P59 为 rail=None; 缺入口移轨则 auto_rail 要到臂已伸出持板才发现需移轨, 必被拒。
        """
        for stem in ("robot_tank_pick", "robot_tank_put"):
            doc = self.docs.get(stem)
            self.assertIsNotNone(doc, f"{stem} 缺失")
            # branch_bodies 含末尾 else (选择值越界 raise), 其 entry 非 require_anchor, 不参与判定
            seams = [(idx, branch) for idx, branch in enumerate(branch_bodies(doc))
                     if is_home_anchor(entry_anchor(branch), self.reg)]
            self.assertEqual(len(seams), 8, f"{stem} 应为 8 条 tank 取放分支, 实得 {len(seams)}")
            for idx, branch in seams:
                self.assertEqual(_ensure_target(branch[1]), 5,
                                 f"{stem} 分支#{idx}: entry 后应为 rail.ensure(5)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
