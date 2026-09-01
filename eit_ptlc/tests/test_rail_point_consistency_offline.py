#!/usr/bin/env python3
"""Rail<->point consistency contract (Win A: 地轨作为机器人点第7维).

Kills the decoupling bug class ("改一腿崩另一腿"): the rail a point is taught at
(`point.rail`, single source of truth in robot_points_meta) and the rail an
operation commands (`rail_move_safe(N)` literal) must agree — checked here, so a
mismatch fails offline instead of crashing on the machine.

Two assertions, both reading point.rail (never inferring rail by walking, which
polymorphic atomics would corrupt):

  A) 每原子·每分支 rail 恒定 — walking an atomic with rack_id/slot bound, the set
     of visited points' rails is a singleton (refined 决策#6: per executable path).
  B) 每流程 字面量匹配 — walking a flow in order with current_rail = last
     rail_move_safe(N), every visited point with a non-null rail has point.rail ==
     current_rail.

Branch-aware: run_script inputs are constant-propagated and `if` guards evaluated,
so only the taken branch is asserted. rack_id (the family selector) comes from the
caller's literal; slot is injected 1..6 so slot guards resolve. Guards that stay
unknown mark the subtree uncertain -> skipped (never a false positive). Points with
rail=None (transit/home/hub anchors, unmigrated stations) are exempt.
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
from eit_ptlc.controller.rail_derive import rail_of, walk  # noqa: E402

_POINTS = _PKG / "config" / "points" / "robot"
_OPDIR = _PKG / "config" / "operation"


class RailPointConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = PointRegistry.load(
            _POINTS / "robot_points.json", source_version="v0.11",
            meta_path=_POINTS / "robot_points_meta.json",
        )
        cls.docs: dict[str, dict] = {}
        for f in sorted(_OPDIR.rglob("*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            if d.get("kind") == "operation" and d.get("name"):
                cls.docs[str(d["name"])] = d

    # ------------------------------------------------------------------
    def test_flow_rail_literals_match_point_rails(self) -> None:
        """B) 每条流程的 rail_move_safe(N) 字面量, 与它引导到达的每个点的 point.rail 一致。

        走每条 operation, current_rail 随 rail_move_safe 变; 到某点(rail 非空)时断言
        point.rail == current_rail。slot 注入 1..6 使分支 guard 解析(certain), 消多态歧义。
        """
        violations: list[str] = []
        for name, doc in self.docs.items():
            # 注入索引变量让分支 guard 解析: slot_id 1..6 (货架/中转/收集), tank 1..8 (显影缸)
            for idx in range(1, 9):
                env = {"slot_id": idx if idx <= 6 else idx - 6, "tank": idx}

                def on_move(ref, rail, certain, _n=name, _i=idx):
                    if not certain or rail is None:
                        return
                    pr = rail_of(self.reg, ref)
                    if pr is not None and pr != rail:
                        violations.append(
                            f"{_n} (idx={_i}): 地轨在位{rail} 却移动到 {ref} (示教在位{pr})")
                walk(doc.get("body"), None, env, [name], True, on_move, self.docs)
        # 去重 (同一违规 slot 无关时会重复)
        uniq = sorted(set(violations))
        self.assertEqual(uniq, [], "地轨字面量与点位 rail 不一致:\n  " + "\n  ".join(uniq))

    # ------------------------------------------------------------------
    def _rack_id_values(self, doc) -> list:
        """收集 doc 中与 {var: rack_id} 比较过的所有 {lit} 值 (分支族选择子)。"""
        vals: set = set()

        def scan(node):
            if isinstance(node, dict):
                if node.get("binop") == "==" and node.get("left") == {"var": "rack_id"}:
                    r = node.get("right") or {}
                    if "lit" in r:
                        vals.add(r["lit"])
                for v in node.values():
                    scan(v)
            elif isinstance(node, list):
                for v in node:
                    scan(v)

        scan(doc.get("body"))
        return sorted(vals) or [None]

    def test_atomic_branch_rail_is_singleton(self) -> None:
        """A) 每个原子·每条可执行分支(按 rack_id/slot)内, 到达点的 rail 是单值。

        跨点 rail 不一致 = 原子内混轨 (决策#6 违背)。只看被选中分支(certain)。
        """
        violations: list[str] = []
        for name, doc in self.docs.items():
            if not str(name).startswith("robot_"):
                continue  # 只查机器人原子
            for rack in self._rack_id_values(doc):
                for slot in range(1, 7):
                    rails: dict[int, set] = {}

                    def on_move(ref, _rail, certain, _r=rails):
                        if not certain:
                            return
                        pr = rail_of(self.reg, ref)
                        if pr is not None:
                            _r.setdefault(pr, set()).add(ref)

                    env = {"slot_id": slot}
                    if rack is not None:
                        env["rack_id"] = rack
                    walk(doc.get("body"), None, env, [name], True, on_move, self.docs)
                    if len(rails) > 1:
                        detail = "; ".join(f"位{k}:{sorted(v)}" for k, v in sorted(rails.items()))
                        violations.append(f"{name} (rack_id={rack}, slot={slot}) 混轨: {detail}")
        uniq = sorted(set(violations))
        self.assertEqual(uniq, [], "原子内跨点地轨不一致:\n  " + "\n  ".join(uniq))

    # ------------------------------------------------------------------
    def test_migrated_families_have_expected_rail(self) -> None:
        """回填哨兵: 关键工位族的 rail 已收编 (防回退到 null; 真机金标准 §5)。"""
        expected = {
            "P39": 3, "P37": 3, "P38": 3, "P40": 3,          # group-staging
            "P46": 2, "P51": 2,                                # 中转A 个体
            "P53": 3, "P58": 3,                                # 中转B
            "P78": 3, "P83": 3,                                # 中转A return
            "P71": 3, "P74": 3,                                # 收集
            "P8": 4, "P10": 4,                                 # 换刀
            "P68": 2, "P77": 2,                                # 刮板夹具
            "P21": 1,                                          # 升降上料
            "P25": 6, "P36": 6,                                # 货架网格
            "P19": 1, "P20": 1, "P22": 1,                      # 点样 + 废料
            "P64": 2, "P65": 2,                                # 刮板拍照板
            "P11": 5, "P18": 5,                                # 显影缸 (展开位5)
        }
        for name, rail in expected.items():
            self.assertEqual(self.reg.get(name).rail, rail, f"{name} 应回填 rail={rail}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
