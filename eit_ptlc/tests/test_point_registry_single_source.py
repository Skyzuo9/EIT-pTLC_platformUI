#!/usr/bin/env python3
"""点位单一来源加载回归测试
==========================
功能:
    校验 Phase 0 "派生点单一来源合并" 的正确性:
      1) PointRegistry.load(robot_points.json + meta) 直接包含全部派生点
         (派生点已从 robot_flows_v2.yaml 并入 meta.supplement);
      2) 旧的 RobotPlanCatalog.load(flows, registry) 叠加路径幂等:
         不再新增/改变任何点位 (与单一来源点集业务字段逐项一致),
         从而离线工具/测试仍可用 flows, 而运行期单一来源不重复。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.operation.robot_routes.robot_plan import RobotPlanCatalog  # noqa: E402

_CFG = _PKG / "config"


def _biz(p):
    """点位业务字段 (不含 source_file/source_version/source_sha256 等来源元数据)。"""
    return (
        p.point_id, p.robot_name,
        tuple(round(x, 6) for x in p.pose),
        None if p.joint is None else tuple(round(x, 6) for x in p.joint),
        p.workstation, p.role, tuple(p.allowed_motion), p.status,
        p.user, p.tool, p.acc, p.vel, p.cp,
    )


class SingleSourcePointsTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = load_config(_CFG / "app.yaml").robot
        self.registry = PointRegistry.load(
            cfg.points_file, source_version=cfg.point_source_version,
            meta_path=cfg.points_meta_file,
        )
        self.flows = _CFG / "backup" / "robot_flows_v2.yaml"
        self.src_ver = cfg.point_source_version
        self.points_file = cfg.points_file
        self.meta_file = cfg.points_meta_file

    def test_single_source_contains_all_derived(self) -> None:
        ids = {p.point_id for p in self.registry.points}
        # 代表性派生点 (来自原 robot_flows_v2.yaml, 已并入 meta.supplement)
        for pid in (
            "tank.1.approach_far", "collect-bottle-pick.far", "collect-bottle-pick.near",
            "group-rack.p25.near", "staging-a.p46.high", "scrape-holder-pick.retreat-2",
        ):
            self.assertIn(pid, ids, f"派生点 {pid} 应已并入单一来源点表")
        # 86 示教点 + 6 原 supplement + 147 迁入派生点
        self.assertEqual(len(self.registry.points), 239)

    def test_catalog_overlay_is_idempotent(self) -> None:
        # 旧路径: 在单独加载的 registry 上叠加 flows 派生点 (应被幂等跳过)
        base = PointRegistry.load(
            self.points_file, source_version=self.src_ver, meta_path=self.meta_file)
        overlaid = RobotPlanCatalog.load(self.flows, base).registry
        single = {p.point_id: _biz(p) for p in self.registry.points}
        overlay = {p.point_id: _biz(p) for p in overlaid.points}
        self.assertEqual(set(single), set(overlay), "叠加 flows 不应新增/丢失点位")
        for pid in single:
            self.assertEqual(single[pid], overlay[pid], f"{pid} 业务字段应一致")


if __name__ == "__main__":
    unittest.main()
