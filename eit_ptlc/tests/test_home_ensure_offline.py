#!/usr/bin/env python3
"""确保式回零 ensure_home 离线单测
=================================
功能:
    校验 RobotController.ensure_home 的确保式回零谓词: P1 容差内直接过 (零运动) /
    吸盘持真空拒回 / 安全点邻域内自动 move_j 回 home 并复验 / 邻域外拒回 /
    派生安全点 (joint=None) 走位姿比较路径 / point_id 非 home 显式拒绝;
    并校验 PointRegistry.safe_anchor_points 枚举恰为 meta 标注的 7 点且全 validated。
    用真配置点表 + SimRobotTransport (可注入起始位姿与工具态), 不连真机。
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
from eit_ptlc.controller.robot_controller import RobotController  # noqa: E402
from eit_ptlc.driver.robot_sim import SimRobotTransport  # noqa: E402
from eit_ptlc.driver.robot_transport import (  # noqa: E402
    MotionOptions,
    RobotFeedback,
    ToolState,
)


class _VacuumSuctionTransport(SimRobotTransport):
    """query 回报吸盘挂载 (mounted_tool=1) + 真空在 (commanded_bits=2), 位姿沿用内部 _pose/_joint。"""

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        self.calls.append(("query",))
        ts = ToolState(commanded_bits=2, actual_bits=0, di_bits=0, di_available=False,
                       di_confirmed=False, mounted_tool=1)
        return RobotFeedback(pose=tuple(self._pose), joint=tuple(self._joint),
                             check_result=0, last_action=24, tool_state=ts,
                             robot_mode=5, connected=True)


class HomeEnsureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_PKG / "config" / "app.yaml")
        cls.points = PointRegistry.load(cfg.robot.points_file,
                                        source_version=cfg.robot.point_source_version,
                                        meta_path=cfg.robot.points_meta_file)
        cls.home_point = cfg.robot.home_point
        cls.home = cls.points.get(cls.home_point)

    def _robot(self, transport):
        transport.connect()
        return RobotController(transport, self.points, home_point=self.home_point,
                               jog_speed_percent=20, step_distance_mm=1.0, step_angle_deg=1.0)

    # ---- 枚举 ----

    def test_safe_anchor_enumeration(self) -> None:
        """safe_anchor_points 恰为 meta 标注 7 点, 全 validated (P1/P2/P52/P70 + 3 个 slot approach-high)。"""
        pts = self.points.safe_anchor_points()
        ids = sorted(p.point_id for p in pts)
        self.assertEqual(len(pts), 7)
        self.assertTrue(all(p.status == "validated" for p in pts))
        self.assertIn("robot-main.home", ids)
        self.assertIn("robot-main.tool-change.ready", ids)
        self.assertEqual(sum(1 for i in ids if i.endswith(".approach-high")), 3)

    # ---- ensure_home ----

    def test_at_home_passes_without_motion(self) -> None:
        """已在 home 容差内: 直接返回, 不产生 move_j (零运动)。"""
        transport = SimRobotTransport(pose=self.home.pose, joint=self.home.joint)
        robot = self._robot(transport)
        robot.ensure_home()
        self.assertNotIn("move_j", [c[0] for c in transport.calls])

    def test_safe_point_auto_returns(self) -> None:
        """臂在安全点 P2 (关节比较) 空腕: 自动 move_j 回 home 并复验通过。"""
        p2 = self.points.get("P2")
        transport = SimRobotTransport(pose=p2.pose, joint=p2.joint)
        robot = self._robot(transport)
        robot.ensure_home()
        move_js = [c[1] for c in transport.calls if c[0] == "move_j"]
        self.assertEqual(move_js[0], tuple(self.home.pose))    # 自动回零 move_j 到 home

    def test_derived_safe_point_pose_compare(self) -> None:
        """臂在派生安全点 slot-1.approach-high (joint=None) 邻域: 走位姿比较路径, 自动回零成功。"""
        high = self.points.get("robot-main.tool-change.slot-1.approach-high")
        self.assertIsNone(high.joint)                          # 派生点无 joint, 必走位姿比较
        # 反馈 joint 置空 (len!=6) 强制 _check_anchor 退化到位姿比较分支
        transport = SimRobotTransport(pose=high.pose, joint=())
        robot = self._robot(transport)
        robot.ensure_home()
        move_js = [c[1] for c in transport.calls if c[0] == "move_j"]
        self.assertEqual(move_js[0], tuple(self.home.pose))

    def test_vacuum_held_blocks(self) -> None:
        """臂在安全点 P2 但吸盘持真空 (疑似吸板): 拒绝自动回零, 无运动。"""
        p2 = self.points.get("P2")
        transport = _VacuumSuctionTransport(pose=p2.pose, joint=p2.joint)
        robot = self._robot(transport)
        with self.assertRaises(PermissionError) as ctx:
            robot.ensure_home()
        self.assertIn("真空", str(ctx.exception))
        self.assertNotIn("move_j", [c[0] for c in transport.calls])

    def test_suction_mounted_no_vacuum_returns(self) -> None:
        """挂吸盘但无真空 (commanded_bits=0): 允许自动回零 (真空守卫只挡真空在)。"""
        p52 = self.points.get("P52")
        transport = SimRobotTransport(pose=p52.pose, joint=p52.joint)
        transport.set_mounted_tool(1)                          # 挂吸盘, 但默认 commanded_bits=0 无真空
        robot = self._robot(transport)
        robot.ensure_home()
        move_js = [c[1] for c in transport.calls if c[0] == "move_j"]
        self.assertEqual(move_js[0], tuple(self.home.pose))

    def test_outside_neighborhood_blocks(self) -> None:
        """臂在任意非安全位姿 (全零): 不在任何安全点邻域内 -> 拒绝自动回零, 无运动。"""
        transport = SimRobotTransport(pose=(0.0,) * 6, joint=(0.0,) * 6)
        robot = self._robot(transport)
        with self.assertRaises(PermissionError) as ctx:
            robot.ensure_home()
        self.assertIn("安全点邻域", str(ctx.exception))
        self.assertNotIn("move_j", [c[0] for c in transport.calls])

    def test_point_id_non_home_rejected(self) -> None:
        """point_id 传非 home 锚点 (P2): 显式拒绝 (确保式回零仅支持 home)。"""
        transport = SimRobotTransport(pose=self.home.pose, joint=self.home.joint)
        robot = self._robot(transport)
        with self.assertRaises(PermissionError) as ctx:
            robot.ensure_home("P2")
        self.assertIn("仅支持 home 锚点", str(ctx.exception))

    def test_point_id_home_alias_accepted(self) -> None:
        """point_id 传 home 别名 (P1 或 robot-main.home): 接受, 已在位零运动 (供 executor safety_anchor 透传)。"""
        transport = SimRobotTransport(pose=self.home.pose, joint=self.home.joint)
        robot = self._robot(transport)
        robot.ensure_home("P1")                                # 应不抛
        self.assertNotIn("move_j", [c[0] for c in transport.calls])


if __name__ == "__main__":
    unittest.main(verbosity=2)
