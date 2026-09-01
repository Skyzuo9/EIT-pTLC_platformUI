#!/usr/bin/env python3
"""move_to_point 视觉纠偏偏移叠加 离线测试
=============================================
功能:
    校验 RobotController.move_to_point(offset=(dx,dy,drz)) 在该点 user 系下把平移(X/Y)与
    旋转(Rz)叠加到目标位姿 (复刻旧 RelPointUser), 仅 move_l 生效, 不改点表;
    并校验 ActionExecutor 把 robot.move_to_point 的 dx_mm/dy_mm/drz_deg 合成 offset 下传.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]                 # eit_ptlc/
if str(_PKG.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))

from eit_ptlc.action.executor import ActionExecutor  # noqa: E402
from eit_ptlc.action.models import ActionStatus  # noqa: E402
from eit_ptlc.action.registry import ActionRegistry  # noqa: E402
from eit_ptlc.controller.point_registry import PointRegistry, RobotPoint  # noqa: E402
from eit_ptlc.controller.robot_controller import RobotController  # noqa: E402
from eit_ptlc.driver.robot_sim import SimRobotTransport  # noqa: E402

_PLACE = "robot-main.place"          # move_l 放板点
_BASE_POSE = (10.0, 20.0, 30.0, 0.0, 0.0, 45.0)


def _place_point() -> RobotPoint:
    return RobotPoint(
        point_id=_PLACE, source_id="t", robot_name="PLACE", alias="place",
        workstation="sampling", role="target", pose=_BASE_POSE,
        joint=(0.0,) * 6, user=0, tool=1, acc=20, vel=20, cp=0,
        allowed_motion=("move_l",), status="validated", source_file="t",
        source_version="t", source_sha256="t",
    )


def _build() -> tuple[RobotController, SimRobotTransport]:
    transport = SimRobotTransport(pose=(0.0,) * 6, joint=(0.0,) * 6)
    transport.connect()
    robot = RobotController(transport, PointRegistry([_place_point()]), home_point=_PLACE)
    return robot, transport


class MoveToPointOffsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = ActionRegistry.load(_PKG / "config" / "actions")

    def test_offset_adds_xy_and_rz_in_user_frame(self) -> None:
        robot, transport = _build()
        robot.move_to_point(_PLACE, motion="move_l", offset=(1.5, -2.0, 3.0))
        last = [c for c in transport.calls if c[0] == "move_l"][-1]
        # pose = 点位 pose + (dx, dy, 0, 0, 0, drz)
        self.assertEqual(last[1], (11.5, 18.0, 30.0, 0.0, 0.0, 48.0))

    def test_no_offset_keeps_nominal_pose(self) -> None:
        robot, transport = _build()
        robot.move_to_point(_PLACE, motion="move_l")
        last = [c for c in transport.calls if c[0] == "move_l"][-1]
        self.assertEqual(last[1], _BASE_POSE)             # 无偏移=标称, 不改点表

    def test_offset_rejected_for_move_j(self) -> None:
        robot, _ = _build()
        with self.assertRaises(ValueError):
            robot.move_to_point(_PLACE, motion="move_j", offset=(1.0, 1.0, 0.0))

    def test_executor_forwards_offset(self) -> None:
        """robot.move_to_point 的 dx_mm/dy_mm/drz_deg 经执行器合成 offset 下传."""
        robot, transport = _build()
        ex = ActionExecutor(self.registry, robot=robot)
        res = asyncio.run(ex.execute(
            "robot.move_to_point",
            {"point_id_or_robot_name": _PLACE, "motion": "move_l",
             "dx_mm": 1.5, "dy_mm": -2.0, "drz_deg": 3.0},
            current_mode="RUN"))
        self.assertEqual(res.status, ActionStatus.DONE)
        last = [c for c in transport.calls if c[0] == "move_l"][-1]
        self.assertEqual(last[1], (11.5, 18.0, 30.0, 0.0, 0.0, 48.0))

    def test_executor_partial_offset_fills_zero(self) -> None:
        """只给 dx_mm 也成立: 缺省 dy/drz 补 0."""
        robot, transport = _build()
        ex = ActionExecutor(self.registry, robot=robot)
        res = asyncio.run(ex.execute(
            "robot.move_to_point",
            {"point_id_or_robot_name": _PLACE, "motion": "move_l", "dx_mm": 5.0},
            current_mode="RUN"))
        self.assertEqual(res.status, ActionStatus.DONE)
        last = [c for c in transport.calls if c[0] == "move_l"][-1]
        self.assertEqual(last[1], (15.0, 20.0, 30.0, 0.0, 0.0, 45.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
