"""派生点关节角的离线反解 — 离线测试。

背景: 机器人点表里 239 个点位有 **169 个只有 pose、没有实测关节角** —— 接近位、退离位、
货架各库位都是从示教点派生出来的(`derivedFrom`), 只允许 move_l。三维演示页的近似展开靠
关节角驱动机械臂, 拿不到就只能跳过, 于是机械臂在少数几个示教点之间瞬移, 接近/退离整段
丢失。这正是"上样取的夹爪全是错的、根本不可用"那个现象的一半。

出路不是往浏览器里再塞一份 IK, 而是**用仓里已有的那一份**(官方 CR5 xacro 链 +
cr5_ptlc_v1 标定 + 关节限位 + 失败即拒)在管线里解一次, 随点位目录落盘。

本文件锁住三件事:
  1. 派生点解得出来, 且 **FK 回代残差 ~0** —— 反解不是"差不多", 是精确回到示教 pose;
  2. 解出来的值写进 `jointSolved` 而**不许覆盖 `joint`** —— `joint` 的语义是"现场示教
     的实测值", 精编译片段的 move_j 门禁(clipSchema)与 pose/joint 半新态检查都建立在
     那个语义上, 灌进去会让它们从此形同虚设且没有任何指标会报警;
  3. 解不出来的点位保持 null —— 未示教占位(pose 全是同一个不可达值)绝不能被编出一个
     "看着能播"的姿态。

运行: & "C:/ProgramData/miniforge3/python.exe" -m pytest eit_ptlc/tests/test_derived_point_ik_offline.py -q
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_PIPELINE = Path(__file__).resolve().parents[1] / "three_d" / "pipeline"
sys.path.insert(0, str(_PIPELINE))

import numpy as np  # noqa: E402

from robot_kinematics import (  # noqa: E402  pylint: disable=import-error
    forward_kinematics, load_calibration, pose_matrix, solve_ik,
)
import sync_ptlc_robot  # noqa: E402  pylint: disable=import-error


class DerivedPointIkTest(unittest.TestCase):
    """反解本身的精度与"解不出来就认账"的行为。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.calibration = load_calibration()

    def test_derived_approach_point_solves_back_to_its_taught_pose(self) -> None:
        # 1 号工具位的高位接近点: 派生自 P8(tool-change.slot-1.target), 只有 pose。
        # 种子取父示教点的关节角 —— 那正是"同一个位形分支"的保证, 不是凑一个初值。
        target = pose_matrix([-315.385223, 420.250977, 138.003296, -179.803116, 0.232015, -21.152111])
        seed = [-63.041, 12.548, 108.62, -31.168, -90.092, 44.534]
        joints = solve_ik(target, seed, self.calibration, tool=1)
        actual = forward_kinematics(joints, self.calibration, tool=1)
        error_mm = float(np.linalg.norm(actual[:3, 3] - target[:3, 3]) * 1000.0)
        self.assertLess(error_mm, 0.01, f"派生点反解位置残差 {error_mm:.4f}mm —— 反解链或标定漂了")

    def test_unreachable_placeholder_pose_is_rejected_not_approximated(self) -> None:
        # 点表里 4 个未示教占位共用这个 pose, 机械臂够不到。solve_ik 必须**拒绝**,
        # 而不是给一个残差 120mm 的"最接近解" —— 那个姿态在动画里看着完全正常。
        target = pose_matrix([0.0, -246.0, 1047.0, -90.0, 0.0, 180.0])
        seed = [-154.523621, -47.783794, 93.294029, 44.639656, -89.062752, 124.999908]
        with self.assertRaises(ValueError):
            solve_ik(target, seed, self.calibration, tool=1)


class CatalogFieldSeparationTest(unittest.TestCase):
    """反解值与实测值必须分字段 —— 这条比精度更要紧。"""

    def test_solver_fills_jointsolved_and_never_touches_joint(self) -> None:
        points = {
            # 实测点: 一个字段都不许动
            "taught": {
                "robotName": "P8", "pose": [-315.385223, 420.250977, 168.0, -179.8, 0.23, -21.15],
                "joint": [-63.041, 12.548, 108.62, -31.168, -90.092, 44.534],
                "jointSolved": None, "jointSolvedFrom": None, "tool": 1, "derivedFrom": None,
            },
            # 派生点: 只有 pose, 靠父点做种子
            "derived": {
                "robotName": "FLOW_TOOL_1_HIGH",
                "pose": [-315.385223, 420.250977, 138.003296, -179.803116, 0.232015, -21.152111],
                "joint": None, "jointSolved": None, "jointSolvedFrom": None,
                "tool": 1, "derivedFrom": "P8",
            },
        }
        report = sync_ptlc_robot._solve_derived_joints(points, load_calibration())

        self.assertEqual(report["solved"], 1)
        self.assertEqual(report["failed"], [])
        # 实测点原样不动
        self.assertIsNone(points["taught"]["jointSolved"])
        self.assertEqual(points["taught"]["joint"][0], -63.041)
        # 派生点拿到反解值, 但 joint 仍然是 null —— "没测过"就是没测过
        self.assertIsNone(points["derived"]["joint"])
        self.assertEqual(len(points["derived"]["jointSolved"]), 6)
        self.assertEqual(points["derived"]["jointSolvedFrom"], "taught")

    def test_all_zero_joint_counts_as_placeholder_not_measurement(self) -> None:
        # 与 clipSchema 的 move_j 门禁同判据: 全零是占位, 拿它插值会把臂甩到不存在的姿态
        self.assertFalse(sync_ptlc_robot._has_joint({"joint": [0, 0, 0, 0, 0, 0]}))
        self.assertFalse(sync_ptlc_robot._has_joint({"joint": None}))
        self.assertTrue(sync_ptlc_robot._has_joint({"joint": [0, 0, 1e-3, 0, 0, 0]}))


if __name__ == "__main__":
    unittest.main()
