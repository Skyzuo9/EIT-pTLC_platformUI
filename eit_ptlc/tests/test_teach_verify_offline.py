#!/usr/bin/env python3
"""示教复核 (teach-verify) 离线测试
==================================
功能:
    校验"当前点示教 + 退到进近点 + 二次进入 + 回位漂移 + 提交"闭环的后端:
      1) capture 支持基础示教点与网格库位 (返回 is_grid/is_anchor/has_approach);
         offset 派生接近点不可独立示教 (拒);
      2) teach_plan 用"新"捕获位算进近航点 (捕获位 + 各进近点相对当前目标的偏移), near→far 排序;
      3) teach_move 安全包络: 离当前点过远的位姿拒发;
      4) commit 多态: 基础点→robot_points.json; 网格锚点→改 anchor 位姿整架重解 (锚点精确落位,
         其余锚点不动); 网格非锚位→改该库位 offset (精确落位, 锚点不动) —— 均写回 meta.grids。
    用临时 config 拷贝, 绝不改仓库真源。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.config.loader import load_config  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry  # noqa: E402
from eit_ptlc.controller.points_service import PointsService  # noqa: E402
from eit_ptlc.controller.robot_controller import RobotController  # noqa: E402
from eit_ptlc.driver.robot_sim import SimRobotTransport  # noqa: E402

_CFG = _PKG / "config"


class TeachVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = load_config(_CFG / "app.yaml").robot
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.pts_file = tmp / "robot_points.json"
        self.meta_file = tmp / "robot_points_meta.json"
        shutil.copy(cfg.points_file, self.pts_file)
        shutil.copy(cfg.points_meta_file, self.meta_file)
        self.registry = PointRegistry.load(
            self.pts_file, source_version=cfg.point_source_version, meta_path=self.meta_file)
        home = self.registry.get(cfg.home_point)
        transport = SimRobotTransport(pose=home.pose, joint=home.joint)
        transport.connect()
        self.robot = RobotController(transport, self.registry, home_point=cfg.home_point)
        self.svc = PointsService(
            _CFG / "points", self.registry, robot=self.robot,
            robot_points_file=self.pts_file, robot_meta_file=self.meta_file)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _pid(self, robot_name: str) -> str:
        return self.svc._registry.get(robot_name).point_id

    # —— capture ——
    def test_capture_classifies_grid_anchor_slot_and_base(self) -> None:
        anchor = self.svc.capture_robot_point(self._pid("P25"))
        self.assertTrue(anchor["is_grid"])
        self.assertTrue(anchor["is_anchor"])
        self.assertTrue(anchor["has_approach"])
        slot = self.svc.capture_robot_point(self._pid("P29"))
        self.assertTrue(slot["is_grid"])
        self.assertFalse(slot["is_anchor"])
        base = self.svc.capture_robot_point(self._pid("P1"))
        self.assertFalse(base["is_grid"])

    def test_capture_rejects_offset_approach_point(self) -> None:
        with self.assertRaises(PermissionError):
            self.svc.capture_robot_point("group-rack.p25.near")

    # —— plan ——
    def test_teach_plan_uses_new_captured_pose(self) -> None:
        p25 = self.svc._registry.get("P25")
        captured = [p25.pose[k] + (5.0 if k < 3 else 0.0) for k in range(6)]  # 假想"新"示教位 (整体平移 5mm)
        plan = self.svc.teach_plan(self._pid("P25"), captured)
        self.assertTrue(plan["has_approach"])
        self.assertEqual(len(plan["waypoints"]), 3)
        # near→far 递增
        dists = [w["dist_mm"] for w in plan["waypoints"]]
        self.assertEqual(dists, sorted(dists))
        # 每个航点 = 新捕获位 + (进近点 − 当前目标) 偏移: 相对当前目标进近点应平移了同样的 +5mm
        near = self.svc._registry.get("group-rack.p25.near")
        near_wp = min(plan["waypoints"], key=lambda w: w["dist_mm"])
        for k in range(3):
            self.assertAlmostEqual(near_wp["pose"][k], near.pose[k] + 5.0, places=3)

    # —— move 安全包络 ——
    def test_teach_move_rejects_out_of_envelope(self) -> None:
        p25 = self.svc._registry.get("P25")
        far = [p25.pose[0] + 9999.0] + list(p25.pose[1:])
        with self.assertRaises(ValueError):
            self.svc.teach_move(self._pid("P25"), far, "move_l")

    # —— commit 多态 ——
    def test_commit_grid_anchor_reteach_resolves_whole_rack(self) -> None:
        p25 = self.svc._registry.get("P25")
        p34_before = list(self.svc._registry.get("P34").pose)
        p36_before = list(self.svc._registry.get("P36").pose)
        new = [p25.pose[k] + (1.0 + k) for k in range(3)] + list(p25.pose[3:])
        res = self.svc.commit_robot_point_capture(self._pid("P25"), pose=new, joint=None, confirm=True)
        self.assertEqual(res["commit_mode"], "anchor")
        reg = self.svc._registry
        for k in range(6):  # 锚点精确落在重示教位
            self.assertAlmostEqual(reg.get("P25").pose[k], new[k], places=3)
        for k in range(6):  # 其余两锚点不动
            self.assertAlmostEqual(reg.get("P34").pose[k], p34_before[k], places=3)
            self.assertAlmostEqual(reg.get("P36").pose[k], p36_before[k], places=3)
        # 持久化到 meta.grids 的 anchor
        anchors = json.loads(self.meta_file.read_text(encoding="utf-8"))["grids"][0]["anchors"]
        a11 = next(a for a in anchors if a["row"] == 1 and a["col"] == 1)
        for k in range(6):
            self.assertAlmostEqual(a11["pose"][k], new[k], places=3)

    def test_commit_grid_nonanchor_updates_only_that_slot_offset(self) -> None:
        p26 = self.svc._registry.get("P26")
        p25_before = list(self.svc._registry.get("P25").pose)
        new = [p26.pose[k] + (1.5 if k < 3 else 0.0) for k in range(6)]
        res = self.svc.commit_robot_point_capture(self._pid("P26"), pose=new, joint=None, confirm=True)
        self.assertEqual(res["commit_mode"], "offset")
        reg = self.svc._registry
        for k in range(6):  # 非锚位精确落在重示教位
            self.assertAlmostEqual(reg.get("P26").pose[k], new[k], places=3)
        for k in range(6):  # 锚点纹丝不动 (只改了该库位的 offset)
            self.assertAlmostEqual(reg.get("P25").pose[k], p25_before[k], places=3)

    def test_commit_base_point_writes_points_json(self) -> None:
        p1 = self.svc._registry.get("P1")
        new = [p1.pose[k] + (0.5 if k < 3 else 0.0) for k in range(6)]
        res = self.svc.commit_robot_point_capture(
            self._pid("P1"), pose=new, joint=list(p1.joint), confirm=True)
        self.assertTrue(res["saved"])
        self.assertNotIn("commit_mode", res)  # 走基础点路径, 非网格
        for k in range(6):
            self.assertAlmostEqual(self.svc._registry.get("P1").pose[k], new[k], places=3)
        raw = json.loads(self.pts_file.read_text(encoding="utf-8-sig"))
        rec = next(r for r in raw if r["name"] == "P1")
        for k in range(6):
            self.assertAlmostEqual(rec["pose"][k], new[k], places=3)

    def test_commit_requires_confirm(self) -> None:
        with self.assertRaises(PermissionError):
            self.svc.commit_robot_point_capture(self._pid("P26"), pose=list(range(6)), joint=None, confirm=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
