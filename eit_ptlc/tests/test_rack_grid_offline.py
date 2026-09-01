#!/usr/bin/env python3
"""货架库位仿射网格迁移离线测试
=================================
功能:
    校验 P25-P36 由"固定示教点"迁移为"3角标定仿射网格 + 每库位偏置"后:
      1) 网格算出的 12 库位位姿 **精确复现** 迁移前的示教点 (零位移迁移, 用户验收要点);
      2) 库位为网格托管 (无 joint, 仅 move_l, derived_from=group-rack), 与货架流程一致;
      3) P25-P36 已移出 robot_points.json (改由 meta.grids 拥有), 但仍可按名解析;
      4) offset 派生接近点 (group-rack.pXX.far/mid/near) 照旧从库位偏移解析;
      5) point_grid 求解器: 3角精确解 / 播种偏置往返 / 共线退化与点数不足报错。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_grid import (  # noqa: E402
    GridAnchor,
    grid_pose,
    seed_offset,
    solve_grid_planes,
)
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402

_CFG = _PKG / "config"

# 迁移前 P25-P36 的示教位姿真值 (来自 robot_points.json v0.11, 现场批量验收通过)。
# 迁移后这 12 点由 meta.grids 仿射算出, 必须逐点复现这些值 (零位移)。
_TAUGHT = {
    "P25": [-706.004822, 138.183212, 438.692474, -179.635666, -0.070574, 69.315048],
    "P26": [-706.004761, -0.899999, 438.692474, -179.635666, -0.070574, 69.315048],
    "P27": [-701.504761, -139.814102, 438.692474, -179.635666, -0.070574, 69.315048],
    "P28": [-709.004700, 138.152817, 279.450562, -179.635666, -0.070574, 69.315048],
    "P29": [-706.004761, -0.509638, 279.474365, -179.635666, -0.070574, 69.315048],
    "P30": [-703.004700, -139.981369, 279.450623, -179.635666, -0.070574, 69.315048],
    "P31": [-710.004700, 136.450226, 118.365082, -179.635666, -0.070574, 68.715050],
    "P32": [-707.004639, -1.834902, 118.112038, -179.635666, -0.070574, 68.715050],
    "P33": [-704.504700, -141.241379, 119.111984, -179.874054, 0.265840, 68.714996],
    "P34": [-712.004761, 137.337341, -40.292572, -179.635666, -0.070574, 68.715050],
    "P35": [-709.004700, -2.574367, -40.792374, -179.635666, -0.070574, 68.715050],
    "P36": [-706.004761, -142.099640, -40.975506, -179.635666, -0.070574, 68.715050],
}
_ANCHORS = ("P25", "P34", "P36")


class RackGridMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_CFG / "app.yaml").robot
        cls.points_file = cfg.points_file
        cls.registry = PointRegistry.load(
            cfg.points_file, source_version=cfg.point_source_version,
            meta_path=cfg.points_meta_file)

    def test_rack_slots_reproduce_taught_poses(self) -> None:
        """核心验收: 仿射网格算出的 12 库位逐点复现迁移前示教位姿 (<1e-3)。"""
        for name, taught in _TAUGHT.items():
            with self.subTest(slot=name):
                p = self.registry.get(name)
                worst = max(abs(p.pose[k] - taught[k]) for k in range(6))
                self.assertLess(worst, 1e-3, f"{name} 复现偏差 {worst} 超限 (应零位移)")

    def test_anchor_slots_exact(self) -> None:
        """3 个标定锚点应无偏置、精确落在示教位 (它们定义仿射平面)。"""
        for name in _ANCHORS:
            with self.subTest(anchor=name):
                p = self.registry.get(name)
                for k in range(6):
                    self.assertAlmostEqual(p.pose[k], _TAUGHT[name][k], places=6)

    def test_rack_slots_are_grid_managed_move_l(self) -> None:
        """库位为网格托管: 无 joint、仅 move_l、validated、derived_from=group-rack。"""
        for name in _TAUGHT:
            with self.subTest(slot=name):
                p = self.registry.get(name)
                self.assertIsNone(p.joint, f"{name} 计算库位不应带 joint")
                self.assertEqual(tuple(p.allowed_motion), ("move_l",))
                self.assertEqual(p.status, "validated")
                self.assertEqual(p.derived_from, "group-rack")

    def test_rack_slots_removed_from_robot_points_json(self) -> None:
        """P25-P36 已移出 robot_points.json (设备导出), 改由 meta.grids 拥有。"""
        raw = json.loads(self.points_file.read_text(encoding="utf-8-sig"))
        names = {r.get("name") for r in raw}
        for name in _TAUGHT:
            self.assertNotIn(name, names, f"{name} 不应再作为示教点留在 robot_points.json")
            self.assertIsNotNone(self.registry.get(name))  # 但仍可按名解析 (来自网格)

    def test_approach_points_chain_off_grid_slots(self) -> None:
        """offset 派生接近点仍从库位偏移解析 (基点=网格库位)。"""
        # group-rack.p28.mid = P28 + [200,0,10,0,0,0]
        base = self.registry.get("P28").pose
        mid = self.registry.get("group-rack.p28.mid").pose
        self.assertAlmostEqual(mid[0], base[0] + 200, places=3)
        self.assertAlmostEqual(mid[2], base[2] + 10, places=3)
        # near = P25 + Z 10
        near = self.registry.get("group-rack.p25.near").pose
        self.assertAlmostEqual(near[2], self.registry.get("P25").pose[2] + 10, places=3)

    def test_total_point_count_preserved(self) -> None:
        """迁移不改变点位总数 (12 示教点移出 + 12 网格库位注入)。"""
        self.assertEqual(len(self.registry.points), 239)

    # ------------------------------------------------------------------
    # point_grid 求解器单元
    # ------------------------------------------------------------------

    def test_solver_seed_offset_roundtrip(self) -> None:
        """播种偏置后 grid_pose 精确复现示教位姿 (6 分量)。"""
        anchors = [GridAnchor(1, 1, tuple(_TAUGHT["P25"])),
                   GridAnchor(4, 1, tuple(_TAUGHT["P34"])),
                   GridAnchor(4, 3, tuple(_TAUGHT["P36"]))]
        planes = solve_grid_planes(anchors)
        rc = {"P26": (1, 2), "P29": (2, 2), "P33": (3, 3)}
        for name, (r, c) in rc.items():
            off = seed_offset(planes, r, c, tuple(_TAUGHT[name]))
            recon = grid_pose(planes, r, c, off)
            for k in range(6):
                self.assertAlmostEqual(recon[k], _TAUGHT[name][k], places=3)

    def test_solver_rejects_degenerate_and_insufficient(self) -> None:
        with self.assertRaises(ValueError):
            solve_grid_planes([GridAnchor(1, 1, (0,) * 6), GridAnchor(1, 1, (1,) * 6)])  # <3
        with self.assertRaises(ValueError):
            # 三点共线 (同一行) -> 退化
            solve_grid_planes([GridAnchor(1, 1, (0,) * 6),
                               GridAnchor(1, 2, (1,) * 6),
                               GridAnchor(1, 3, (2,) * 6)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
