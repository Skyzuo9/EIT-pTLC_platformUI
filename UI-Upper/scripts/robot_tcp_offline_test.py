#!/usr/bin/env python3
"""Dobot TCP transport 的标准库 fake/mock 离线验证。"""

from __future__ import annotations

import struct
import sys
import threading
import time
import unittest
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
if str(UI_ROOT) not in sys.path:
    sys.path.insert(0, str(UI_ROOT))

from core.dobot_tcp_transport import (  # noqa: E402
    FEEDBACK_MAGIC,
    FEEDBACK_SIZE,
    DashboardReply,
    DobotFeedbackFrame,
    DobotTcpRobotTransport,
    RobotMode,
    parse_dashboard_reply,
    parse_feedback_packet,
)
from core.point_registry import PointRegistry  # noqa: E402
from core.robot_service import RobotActionService  # noqa: E402
from core.robot_transport import (  # noqa: E402
    MotionOptions,
    RobotActionError,
    RobotTransportError,
    ToolAction,
)


def frame(mode: int = 5, command_id: int = 0, *, di: int = 0, do: int = 0) -> DobotFeedbackFrame:
    return DobotFeedbackFrame(
        robot_mode=mode,
        current_command_id=command_id,
        digital_inputs=di,
        digital_outputs=do,
        pose=(1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        joint=(11.0, 12.0, 13.0, 14.0, 15.0, 16.0),
        error_status=mode == RobotMode.ERROR,
        collision_state=mode == RobotMode.COLLISION,
        enable_status=mode in (RobotMode.ENABLED_IDLE, RobotMode.RUNNING),
        auto_manual_mode=1,
        safety_state=0,
    )


class FakeDashboard:
    def __init__(self, replies: dict[str, DashboardReply] | None = None) -> None:
        self.replies = replies or {}
        self.commands: list[str] = []
        self.closed = False

    def command(self, command: str) -> DashboardReply:
        self.commands.append(command)
        for prefix, reply in self.replies.items():
            if command.startswith(prefix):
                return reply
        return DashboardReply(0, (42.0,), f"0,{{42}},{command};")

    def close(self) -> None:
        self.closed = True


class FakeFeedback:
    def __init__(self, frames: list[DobotFeedbackFrame], *, repeat_last: bool = False) -> None:
        self.frames = list(frames)
        self.repeat_last = repeat_last
        self.last = self.frames[-1] if self.frames else frame()
        self.closed = False

    def read_frame(self) -> DobotFeedbackFrame:
        if self.frames:
            self.last = self.frames.pop(0)
            return self.last
        if self.repeat_last:
            return self.last
        raise RobotTransportError("fake disconnect")

    def close(self) -> None:
        self.closed = True


class SerializedDashboard(FakeDashboard):
    def __init__(self) -> None:
        super().__init__()
        self.command_id = 0
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def command(self, command: str) -> DashboardReply:
        with self.guard:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self.guard:
            self.active -= 1
            self.command_id += 1
            command_id = self.command_id
        self.commands.append(command)
        return DashboardReply(0, (float(command_id),), f"0,{{{command_id}}},{command};")


class SerializedFeedback:
    def __init__(self, dashboard: SerializedDashboard) -> None:
        self.dashboard = dashboard
        self.completed = 0
        self.running_sent = False

    def read_frame(self) -> DobotFeedbackFrame:
        pending = self.dashboard.command_id
        if pending == self.completed:
            return frame(RobotMode.ENABLED_IDLE, self.completed)
        if not self.running_sent:
            self.running_sent = True
            return frame(RobotMode.RUNNING, pending)
        self.completed = pending
        self.running_sent = False
        return frame(RobotMode.ENABLED_IDLE, pending)

    def close(self) -> None:
        pass


def connected_transport(
    frames: list[DobotFeedbackFrame],
    replies: dict[str, DashboardReply] | None = None,
    **kwargs: object,
) -> DobotTcpRobotTransport:
    transport = DobotTcpRobotTransport("fake", **kwargs)
    transport._dashboard = FakeDashboard(replies)  # type: ignore[attr-defined]
    transport._feedback = FakeFeedback(frames)  # type: ignore[attr-defined]
    return transport


class ParsingTests(unittest.TestCase):
    def test_dashboard_parser_does_not_capture_echoed_numbers(self) -> None:
        reply = parse_dashboard_reply("0,{123},MovJ(pose={1,2,3,4,5,6});")
        self.assertEqual(reply.error_id, 0)
        self.assertEqual(reply.values, (123.0,))

    def test_feedback_packet_offsets(self) -> None:
        packet = bytearray(FEEDBACK_SIZE)
        struct.pack_into("<H", packet, 0, FEEDBACK_SIZE)
        struct.pack_into("<Q", packet, 8, 0b10)
        struct.pack_into("<Q", packet, 16, 0b101)
        struct.pack_into("<Q", packet, 24, RobotMode.RUNNING)
        struct.pack_into("<Q", packet, 48, FEEDBACK_MAGIC)
        struct.pack_into("<6d", packet, 432, *range(1, 7))
        struct.pack_into("<6d", packet, 624, *range(11, 17))
        struct.pack_into("<Q", packet, 1112, 77)
        packet[1026] = 1
        struct.pack_into("<H", packet, 1416, 1)
        packet[1420] = 2
        parsed = parse_feedback_packet(bytes(packet))
        self.assertEqual(parsed.current_command_id, 77)
        self.assertEqual(parsed.robot_mode, RobotMode.RUNNING)
        self.assertEqual(parsed.joint, tuple(float(x) for x in range(1, 7)))
        self.assertEqual(parsed.pose, tuple(float(x) for x in range(11, 17)))
        self.assertEqual(parsed.auto_manual_mode, 1)
        self.assertEqual(parsed.safety_state, 2)


class TransportTests(unittest.TestCase):
    def test_command_id_and_idle_mean_motion_complete(self) -> None:
        transport = connected_transport(
            [
                frame(),
                frame(RobotMode.ENABLED_IDLE, 41),  # 指令接收前允许短暂保留上一 ID
                frame(RobotMode.RUNNING, 42),
                frame(RobotMode.ENABLED_IDLE, 42),
            ],
        )
        result = transport.move_j(range(6), MotionOptions(), joint=range(10, 16))
        self.assertEqual(result.command_id, 42)
        self.assertEqual(result.last_action, 25)
        command = transport._dashboard.commands[-1]  # type: ignore[attr-defined]
        self.assertIn("MovJ(joint={10.000000", command)

    def test_error_mode_maps_to_action_error_without_auto_clear(self) -> None:
        replies = {"GetErrorID": DashboardReply(0, (6010.0,), "0,{6010},GetErrorID();")}
        transport = connected_transport([frame(RobotMode.ERROR)], replies)
        transport._get_error_ids = lambda: (6010,)  # type: ignore[method-assign]
        with self.assertRaises(RobotActionError) as caught:
            transport.move_l(range(6))
        self.assertEqual(caught.exception.error_id, 6010)
        commands = transport._dashboard.commands  # type: ignore[attr-defined]
        self.assertFalse(any(command.startswith("ClearError") for command in commands))

    def test_error_mode_allows_readonly_connect_reconciliation(self) -> None:
        transport = DobotTcpRobotTransport("fake")
        transport._reconcile_after_connect(frame(RobotMode.ERROR))
        self.assertEqual(transport._last_frame.robot_mode, RobotMode.ERROR)  # type: ignore[union-attr]

    def test_collision_flag_is_not_hidden_even_if_mode_is_idle(self) -> None:
        collision = frame(RobotMode.ENABLED_IDLE)
        collision = DobotFeedbackFrame(**{**collision.__dict__, "collision_state": True})
        transport = connected_transport([collision])
        transport._get_error_ids = lambda: ()  # type: ignore[method-assign]
        with self.assertRaises(RobotActionError):
            transport.move_j(range(6), joint=range(6))

    def test_timeout_closes_uncertain_connection(self) -> None:
        transport = connected_transport(
            [frame(), frame(RobotMode.RUNNING, 42)],
            action_timeout=0.01,
            poll_interval=0.001,
        )
        transport._feedback.repeat_last = True  # type: ignore[attr-defined]
        with self.assertRaises(TimeoutError):
            transport.move_l(range(6))
        self.assertIsNone(transport._dashboard)
        self.assertIsNone(transport._feedback)

    def test_disconnect_closes_both_channels(self) -> None:
        transport = connected_transport([])
        with self.assertRaises(RobotTransportError):
            transport.query()
        self.assertIsNone(transport._dashboard)
        self.assertIsNone(transport._feedback)

    def test_tool_whitelist_rejects_unknown_action(self) -> None:
        transport = connected_transport([frame()])
        with self.assertRaises(ValueError):
            transport.tool_action(999)  # type: ignore[arg-type]

    def test_gripper_uses_only_whitelisted_do_and_di(self) -> None:
        transport = connected_transport(
            [
                frame(),
                frame(RobotMode.RUNNING, 42),
                frame(RobotMode.ENABLED_IDLE, 42),
                frame(RobotMode.ENABLED_IDLE, 42, di=1),
            ],
            tool_di_feedback_enabled=True,
        )
        result = transport.tool_action(ToolAction.GRIPPER_OPEN)
        commands = transport._dashboard.commands  # type: ignore[attr-defined]
        self.assertEqual(commands[:2], ["DO(6,1)", "DO(2,0)"])
        self.assertTrue(result.tool_state.di_confirmed)

    def test_unvalidated_di_mapping_is_not_reported_available(self) -> None:
        transport = connected_transport(
            [frame(), frame(RobotMode.RUNNING, 42), frame(RobotMode.ENABLED_IDLE, 42, di=1)]
        )
        result = transport.tool_action(ToolAction.GRIPPER_OPEN)
        self.assertFalse(result.tool_state.di_available)
        self.assertFalse(result.tool_state.di_confirmed)

    def test_quick_change_and_aux_match_legacy_do_sequence(self) -> None:
        sleeps: list[float] = []
        quick = connected_transport(
            [
                frame(),
                frame(RobotMode.RUNNING, 42),
                frame(RobotMode.ENABLED_IDLE, 42),
            ],
            sleep_fn=sleeps.append,
        )
        quick.tool_action(ToolAction.QUICK_CHANGE_RELEASE)
        self.assertEqual(quick._dashboard.commands, ["DO(1,1)"])  # type: ignore[attr-defined]
        self.assertEqual(sleeps, [1.0, 1.0])

        aux = connected_transport(
            [
                frame(),
                frame(RobotMode.RUNNING, 42),
                frame(RobotMode.ENABLED_IDLE, 42),
            ],
            sleep_fn=lambda _: None,
        )
        aux.tool_action(ToolAction.TOOL_CHANGE_AUX_ON)
        self.assertEqual(aux._dashboard.commands, ["DO(6,1)"])  # type: ignore[attr-defined]

    def test_enable_and_clear_error_need_double_confirmation(self) -> None:
        transport = connected_transport([frame()])
        with self.assertRaises(PermissionError):
            transport.enable_robot(confirm=True)
        with self.assertRaises(PermissionError):
            transport.clear_error(confirm=True)

    def test_action_lock_serializes_callers(self) -> None:
        transport = DobotTcpRobotTransport("fake")
        dashboard = SerializedDashboard()
        transport._dashboard = dashboard  # type: ignore[attr-defined]
        transport._feedback = SerializedFeedback(dashboard)  # type: ignore[attr-defined]
        errors: list[BaseException] = []

        def run_motion(index: int) -> None:
            try:
                transport.move_l((index, 2, 3, 4, 5, 6))
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=run_motion, args=(index,)) for index in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(dashboard.max_active, 1)
        self.assertEqual(len(dashboard.commands), 3)


class PointSafetyTests(unittest.TestCase):
    def test_unvalidated_point_is_rejected_before_transport(self) -> None:
        source = UI_ROOT.parent / "机器人程序" / "机器人程序v0.11" / "roboprogram" / "point.json"
        meta = UI_ROOT / "config" / "robot_points_meta.json"
        registry = PointRegistry.load(source, source_version="v0.11", meta_path=meta)
        service = RobotActionService(object(), registry, home_point="robot-main.home")  # type: ignore[arg-type]
        with self.assertRaises(PermissionError):
            service.move_j("P6")


if __name__ == "__main__":
    unittest.main(verbosity=2)
