"""Dobot TCP-IP-V4 安全适配层。

官方源码快照仅作为协议依据。本模块复用 29999 指令格式和 30004 的
1440 字节反馈布局，但用有界 socket、流式组帧和显式重连确认规避官方
示例中的无限重连与单次 ``recv`` 假设。
"""

from __future__ import annotations

import json
import re
import socket
import struct
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Sequence

from .robot_transport import (
    MotionOptions,
    RobotActionError,
    RobotFeedback,
    RobotTransport,
    RobotTransportError,
    ToolAction,
    ToolState,
)


FEEDBACK_SIZE = 1440
FEEDBACK_MAGIC = 0x0123456789ABCDEF


class RobotMode:
    INIT = 1
    BRAKE_OPEN = 2
    POWEROFF = 3
    DISABLED = 4
    ENABLED_IDLE = 5
    BACKDRIVE = 6
    RUNNING = 7
    SINGLE_MOVE = 8
    ERROR = 9
    PAUSE = 10
    COLLISION = 11


@dataclass(frozen=True)
class DashboardReply:
    error_id: int
    values: tuple[float, ...]
    raw: str


@dataclass(frozen=True)
class DobotFeedbackFrame:
    robot_mode: int
    current_command_id: int
    digital_inputs: int
    digital_outputs: int
    pose: tuple[float, ...]
    joint: tuple[float, ...]
    error_status: bool
    collision_state: bool
    enable_status: bool
    auto_manual_mode: int
    safety_state: int


def parse_dashboard_reply(raw: str) -> DashboardReply:
    """解析 ``ErrorID,{values},Command(...);``，不从回显命令误抓数字。"""
    match = re.match(r"^\s*(-?\d+)\s*,\s*\{([^}]*)\}", raw.strip())
    if not match:
        if "Not Tcp" in raw:
            raise RobotTransportError("机器人不在 TCP 控制模式")
        raise RobotTransportError(f"无法解析 29999 响应: {raw!r}")
    values = tuple(
        float(item.strip())
        for item in match.group(2).split(",")
        if item.strip()
    )
    return DashboardReply(int(match.group(1)), values, raw.strip())


def parse_feedback_packet(data: bytes) -> DobotFeedbackFrame:
    """按官方 V4 ``MyType`` 小端布局解析一个完整反馈包。"""
    if len(data) != FEEDBACK_SIZE:
        raise RobotTransportError(f"30004 反馈长度错误: {len(data)} != {FEEDBACK_SIZE}")
    length = struct.unpack_from("<H", data, 0)[0]
    magic = struct.unpack_from("<Q", data, 48)[0]
    if length != FEEDBACK_SIZE or magic != FEEDBACK_MAGIC:
        raise RobotTransportError(
            f"30004 反馈包头错误: len={length}, test=0x{magic:x}"
        )
    return DobotFeedbackFrame(
        robot_mode=int(struct.unpack_from("<Q", data, 24)[0]),
        current_command_id=int(struct.unpack_from("<Q", data, 1112)[0]),
        digital_inputs=int(struct.unpack_from("<Q", data, 8)[0]),
        digital_outputs=int(struct.unpack_from("<Q", data, 16)[0]),
        pose=tuple(float(x) for x in struct.unpack_from("<6d", data, 624)),
        joint=tuple(float(x) for x in struct.unpack_from("<6d", data, 432)),
        error_status=bool(data[1029]),
        collision_state=bool(data[1038]),
        enable_status=bool(data[1026]),
        auto_manual_mode=int(struct.unpack_from("<H", data, 1416)[0]),
        safety_state=int(data[1420]),
    )


class _DashboardChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock
        self._buffer = bytearray()

    def close(self) -> None:
        self._socket.close()

    def command(self, command: str) -> DashboardReply:
        self._socket.sendall(command.encode("utf-8"))
        while b";" not in self._buffer:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise RobotTransportError("机器人关闭 29999 连接")
            self._buffer.extend(chunk)
        marker = self._buffer.index(ord(";")) + 1
        raw = bytes(self._buffer[:marker]).decode("utf-8", errors="replace")
        del self._buffer[:marker]
        return parse_dashboard_reply(raw)


class _FeedbackChannel:
    def __init__(self, sock: socket.socket) -> None:
        self._socket = sock
        self._buffer = bytearray()

    def close(self) -> None:
        self._socket.close()

    def read_frame(self) -> DobotFeedbackFrame:
        # TCP 是字节流；允许粘包、半包，并通过官方 len/TestValue 重新对齐。
        while True:
            while len(self._buffer) < FEEDBACK_SIZE:
                chunk = self._socket.recv(65536)
                if not chunk:
                    raise RobotTransportError("机器人关闭 30004 连接")
                self._buffer.extend(chunk)
            candidate = bytes(self._buffer[:FEEDBACK_SIZE])
            try:
                frame = parse_feedback_packet(candidate)
            except RobotTransportError:
                del self._buffer[0]
                continue
            del self._buffer[:FEEDBACK_SIZE]
            return frame


class DobotTcpRobotTransport(RobotTransport):
    """串行、单控制者的 Dobot 29999 + 30004 transport。"""

    _TOOL_BITS = {
        ToolAction.QUICK_CHANGE_LOCK: (1, False),   # DO1=false(0)=锁紧快换
        ToolAction.QUICK_CHANGE_RELEASE: (1, True),  # DO1=true(1)=松开快换
        ToolAction.SUCTION_ON: (3, True),
        ToolAction.SUCTION_OFF: (3, False),
    }
    _QUICK_CHANGE_ACTIONS = {
        ToolAction.QUICK_CHANGE_LOCK,
        ToolAction.QUICK_CHANGE_RELEASE,
    }

    def __init__(
        self,
        host: str,
        *,
        command_port: int = 29999,
        feedback_port: int = 30004,
        error_http_port: int = 22000,
        connect_timeout: float = 3.0,
        command_timeout: float = 5.0,
        action_timeout: float = 300.0,
        poll_interval: float = 0.05,
        allow_enable_command: bool = False,
        allow_clear_error_command: bool = False,
        tool_di_feedback_enabled: bool = False,
        socket_factory: Callable[..., socket.socket] = socket.create_connection,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.command_port = command_port
        self.feedback_port = feedback_port
        self.error_http_port = error_http_port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.action_timeout = action_timeout
        self.poll_interval = poll_interval
        self.allow_enable_command = allow_enable_command
        self.allow_clear_error_command = allow_clear_error_command
        self.tool_di_feedback_enabled = tool_di_feedback_enabled
        self._socket_factory = socket_factory
        self._sleep = sleep_fn
        self._dashboard: _DashboardChannel | object | None = None
        self._feedback: _FeedbackChannel | object | None = None
        self._action_lock = threading.Lock()
        self._last_frame: DobotFeedbackFrame | None = None
        self._last_dispatched_command_id: int | None = None
        self._clean_close = True
        self._tool_commanded_bits = 0

    def connect(self) -> None:
        with self._action_lock:
            if self._dashboard is not None or self._feedback is not None:
                raise RobotTransportError("机器人 transport 已连接")
            try:
                command_socket = self._socket_factory(
                    (self.host, self.command_port), self.connect_timeout
                )
                feedback_socket = self._socket_factory(
                    (self.host, self.feedback_port), self.connect_timeout
                )
                command_socket.settimeout(self.command_timeout)
                feedback_socket.settimeout(self.command_timeout)
                self._dashboard = _DashboardChannel(command_socket)
                self._feedback = _FeedbackChannel(feedback_socket)
                frame = self._read_frame()
                self._reconcile_after_connect(frame)
                self._clean_close = False
            except BaseException:
                self._close_channels()
                raise

    def close(self) -> None:
        with self._action_lock:
            self._clean_close = True
            self._close_channels()

    def __enter__(self) -> "DobotTcpRobotTransport":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        with self._action_lock:
            self._require_connected()
            try:
                mode = self._command_scalar("RobotMode()")
                pose = self._command_vector(
                    f"GetPose(user={options.user},tool={options.tool})", 6
                )
                joint = self._command_vector("GetAngle()", 6)
                frame = self._read_frame()
                if mode != frame.robot_mode:
                    # 29999 与 30004 非原子采样；以更新的反馈帧为最终状态并保留差异。
                    details = {"dashboard_robot_mode": mode}
                else:
                    details = {}
                return self._feedback_from(
                    frame, pose=pose, joint=joint, last_action=24, details=details
                )
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def home(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        raise RobotTransportError("TCP home 必须由 RobotActionService 解析已验收 home 点")

    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback:
        if joint is None:
            raise ValueError(
                "DobotTCP move_j requires joint values; "
                "pass joint= to specify calibrated joint angles"
            )
        return self._move("MovJ", joint, "joint", options)

    def move_l(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
    ) -> RobotFeedback:
        return self._move("MovL", pose, "pose", options)

    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        action = ToolAction(action)
        if not 100 <= timeout_ms <= 60000:
            raise ValueError("tool timeout_ms must be 100..60000")
        with self._action_lock:
            self._assert_action_ready()
            try:
                final_command_id: int | None = None
                expected_di: tuple[int, bool] | None = None
                if action in self._TOOL_BITS:
                    if action in self._QUICK_CHANGE_ACTIONS:
                        self._sleep(1.0)
                    channel, enabled = self._TOOL_BITS[action]
                    final_command_id = self._queue_do(channel, enabled)
                    self._set_tool_bit(channel, enabled)
                elif action == ToolAction.GRIPPER_OPEN:
                    self._queue_do(6, True)
                    final_command_id = self._queue_do(2, False)
                    self._set_tool_bit(2, False)
                    if self.tool_di_feedback_enabled:
                        expected_di = (1, True)
                elif action == ToolAction.GRIPPER_CLOSE:
                    self._queue_do(6, False)
                    final_command_id = self._queue_do(2, True)
                    self._set_tool_bit(2, True)
                    if self.tool_di_feedback_enabled:
                        expected_di = (2, True)
                elif action == ToolAction.TOOL_CHANGE_AUX_ON:
                    final_command_id = self._queue_do(6, True)
                elif action == ToolAction.TOOL_CHANGE_AUX_OFF:
                    final_command_id = self._queue_do(6, False)
                elif action == ToolAction.ROTARY_UP:
                    self._queue_do(6, False)
                    final_command_id = self._queue_do(2, True)
                elif action == ToolAction.ROTARY_DOWN:
                    self._queue_do(2, False)
                    final_command_id = self._queue_do(6, True)
                elif action != ToolAction.GET_STATE:
                    raise PermissionError(f"工具动作不在语义白名单: {action}")

                if final_command_id is not None:
                    frame = self._wait_command(final_command_id, self.action_timeout)
                    if action in self._QUICK_CHANGE_ACTIONS:
                        self._sleep(1.0)
                else:
                    frame = self._read_frame()
                confirmed = False
                if expected_di is not None:
                    frame = self._wait_di(expected_di[0], expected_di[1], timeout_ms / 1000)
                    confirmed = True
                return self._feedback_from(
                    frame,
                    last_action=28,
                    tool_confirmed=confirmed,
                )
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def enable_robot(self, *, confirm: bool = False) -> RobotFeedback:
        """显式使能；配置和调用确认缺一不可。"""
        if not self.allow_enable_command or not confirm:
            raise PermissionError("EnableRobot 未经配置允许或缺少显式 confirm")
        with self._action_lock:
            try:
                reply = self._command("EnableRobot()")
                self._raise_dashboard_error(reply, "EnableRobot")
                return self._feedback_from(self._wait_mode(RobotMode.ENABLED_IDLE, 15.0))
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def clear_error(self, *, confirm: bool = False) -> RobotFeedback:
        """显式清警；绝不在 connect 或动作失败时自动调用。"""
        if not self.allow_clear_error_command or not confirm:
            raise PermissionError("ClearError 未经配置允许或缺少显式 confirm")
        with self._action_lock:
            try:
                reply = self._command("ClearError()")
                self._raise_dashboard_error(reply, "ClearError")
                frame = self._read_frame()
                if frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION) or frame.collision_state:
                    raise RobotActionError(
                        9000 + frame.robot_mode,
                        frame.robot_mode,
                        "报警原因仍存在，ClearError 后机器人未恢复",
                    )
                return self._feedback_from(frame)
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def _move(
        self,
        command_name: str,
        target: Sequence[float],
        coordinate: str,
        options: MotionOptions,
    ) -> RobotFeedback:
        values = self._six(target, coordinate)
        self._validate_options(options)
        with self._action_lock:
            self._assert_action_ready()
            command = (
                f"{command_name}({coordinate}={{{','.join(self._fmt(v) for v in values)}}},"
                f"user={options.user},tool={options.tool},a={options.acc},"
                f"v={options.vel},cp={options.cp})"
            )
            try:
                reply = self._command(command)
                self._raise_dashboard_error(reply, command_name)
                command_id = self._reply_command_id(reply, command_name)
                frame = self._wait_command(command_id, self.action_timeout)
                return self._feedback_from(
                    frame,
                    last_action=25 if command_name == "MovJ" else 27,
                )
            except BaseException:
                self._mark_uncertain_on_io_error()
                raise

    def _wait_command(self, command_id: int, timeout: float) -> DobotFeedbackFrame:
        self._last_dispatched_command_id = command_id
        deadline = time.monotonic() + timeout
        accept_deadline = time.monotonic() + min(timeout, self.command_timeout)
        accepted = False
        while time.monotonic() < deadline:
            frame = self._read_frame()
            self._raise_for_mode(frame)
            if frame.current_command_id == command_id or frame.robot_mode in (
                RobotMode.RUNNING,
                RobotMode.SINGLE_MOVE,
            ):
                accepted = True
            if frame.current_command_id == command_id and frame.robot_mode == RobotMode.ENABLED_IDLE:
                return frame
            if (
                frame.robot_mode == RobotMode.ENABLED_IDLE
                and frame.current_command_id != command_id
                and accepted
            ):
                raise RobotTransportError(
                    "机器人已空闲但 CurrentCommandId 不匹配，可能存在其他控制者: "
                    f"expected={command_id}, actual={frame.current_command_id}"
                )
            if not accepted and time.monotonic() >= accept_deadline:
                raise TimeoutError(f"机器人未在 {self.command_timeout}s 内接收命令 {command_id}")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"等待机器人命令 {command_id} 完成超时")

    def _wait_di(self, channel: int, enabled: bool, timeout: float) -> DobotFeedbackFrame:
        deadline = time.monotonic() + timeout
        last = self._last_frame
        while time.monotonic() < deadline:
            last = self._read_frame()
            self._raise_for_mode(last)
            if self._io_bit(last.digital_inputs, channel) == enabled:
                return last
        raise TimeoutError(f"等待 DI{channel}={int(enabled)} 超时")

    def _wait_mode(self, mode: int, timeout: float) -> DobotFeedbackFrame:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            frame = self._read_frame()
            if frame.robot_mode == mode:
                return frame
            self._raise_for_mode(frame)
        raise TimeoutError(f"等待 RobotMode={mode} 超时")

    def _assert_action_ready(self) -> None:
        self._require_connected()
        frame = self._read_frame()
        self._raise_for_mode(frame)
        if frame.robot_mode != RobotMode.ENABLED_IDLE:
            raise RobotActionError(
                9000 + frame.robot_mode,
                frame.robot_mode,
                f"机器人不是使能空闲状态，RobotMode={frame.robot_mode}",
            )

    def _reconcile_after_connect(self, frame: DobotFeedbackFrame) -> None:
        # 报警/碰撞允许建立只读连接，便于 status/GetError 和负责人显式清警；
        # 运动入口仍由 _assert_action_ready 严格拒绝。
        if frame.robot_mode in (RobotMode.RUNNING, RobotMode.SINGLE_MOVE, RobotMode.PAUSE):
            raise RobotTransportError(
                f"重连时机器人仍在运行/暂停，拒绝取得控制权: RobotMode={frame.robot_mode}"
            )
        if (
            self._last_frame is not None
            and self._last_dispatched_command_id is not None
            and frame.current_command_id != self._last_dispatched_command_id
        ):
            raise RobotTransportError(
                "重连后 CurrentCommandId 已变化，可能存在其他控制者；需人工确认"
            )
        self._last_frame = frame

    def _raise_for_mode(self, frame: DobotFeedbackFrame) -> None:
        if (
            frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION)
            or frame.error_status
            or frame.collision_state
        ):
            ids = self._get_error_ids()
            is_collision = frame.robot_mode == RobotMode.COLLISION or frame.collision_state
            error_id = ids[0] if ids else 9000 + (RobotMode.COLLISION if is_collision else frame.robot_mode)
            label = "碰撞" if is_collision else "报警"
            raise RobotActionError(
                error_id,
                frame.robot_mode,
                f"机器人{label}，未自动 ClearError: RobotMode={frame.robot_mode}, errors={ids}",
            )

    def _get_error_ids(self) -> tuple[int, ...]:
        # 官方 V4 的 GetError 实际使用 22000 HTTP；失败时回退到 29999 GetErrorID。
        try:
            url = f"http://{self.host}:{self.error_http_port}/protocol/getAlarm"
            with urllib.request.urlopen(url, timeout=min(self.command_timeout, 5.0)) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return tuple(int(item["id"]) for item in payload.get("errMsg", []) if "id" in item)
        except Exception:
            try:
                reply = self._command("GetErrorID()")
                return tuple(int(value) for value in reply.values)
            except Exception:
                return ()

    def _feedback_from(
        self,
        frame: DobotFeedbackFrame,
        *,
        pose: Sequence[float] | None = None,
        joint: Sequence[float] | None = None,
        last_action: int = 0,
        tool_confirmed: bool = False,
        details: dict[str, object] | None = None,
    ) -> RobotFeedback:
        output_bits = frame.digital_outputs
        tool_actual = 0
        if self._io_bit(output_bits, 1):
            tool_actual |= 1
        if self._io_bit(output_bits, 3):
            tool_actual |= 2
        if self._io_bit(output_bits, 2):
            tool_actual |= 4
        return RobotFeedback(
            pose=tuple(pose or frame.pose),
            joint=tuple(joint or frame.joint),
            check_result=0,
            last_action=last_action,
            tool_state=ToolState(
                commanded_bits=self._tool_commanded_bits,
                actual_bits=tool_actual,
                di_bits=frame.digital_inputs & 0xFFFF,
                di_available=self.tool_di_feedback_enabled,
                di_confirmed=tool_confirmed,
            ),
            robot_mode=frame.robot_mode,
            command_id=frame.current_command_id,
            error_ids=self._get_error_ids()
            if frame.robot_mode in (RobotMode.ERROR, RobotMode.COLLISION) or frame.collision_state
            else (),
            connected=True,
            details={
                "auto_manual_mode": frame.auto_manual_mode,
                "safety_state": frame.safety_state,
                "collision_state": frame.collision_state,
                **(details or {}),
            },
        )

    def _queue_do(self, channel: int, enabled: bool) -> int:
        if channel not in {1, 2, 3, 6}:
            raise PermissionError(f"DO{channel} 不在白名单")
        reply = self._command(f"DO({channel},{int(enabled)})")
        self._raise_dashboard_error(reply, f"DO{channel}")
        return self._reply_command_id(reply, f"DO{channel}")

    def _set_tool_bit(self, channel: int, enabled: bool) -> None:
        semantic_mask = {1: 1, 3: 2, 2: 4}.get(channel)
        if semantic_mask is None:
            return
        if enabled:
            self._tool_commanded_bits |= semantic_mask
        else:
            self._tool_commanded_bits &= ~semantic_mask

    def _command(self, command: str) -> DashboardReply:
        self._require_connected()
        assert self._dashboard is not None
        return self._dashboard.command(command)  # type: ignore[attr-defined]

    def _command_scalar(self, command: str) -> int:
        reply = self._command(command)
        self._raise_dashboard_error(reply, command)
        if len(reply.values) != 1:
            raise RobotTransportError(f"{command} 返回值数量错误: {reply.raw}")
        return int(reply.values[0])

    def _command_vector(self, command: str, size: int) -> tuple[float, ...]:
        reply = self._command(command)
        self._raise_dashboard_error(reply, command)
        if len(reply.values) != size:
            raise RobotTransportError(f"{command} 返回值数量错误: {reply.raw}")
        return reply.values

    def _read_frame(self) -> DobotFeedbackFrame:
        self._require_connected()
        assert self._feedback is not None
        frame = self._feedback.read_frame()  # type: ignore[attr-defined]
        self._last_frame = frame
        return frame

    def _require_connected(self) -> None:
        if self._dashboard is None or self._feedback is None:
            raise RobotTransportError("机器人 TCP transport 未连接")

    def _mark_uncertain_on_io_error(self) -> None:
        # 参数/权限/机器人显式拒绝不等于链路未知；I/O、断线和超时才封锁连接。
        import sys

        error = sys.exc_info()[1]
        if isinstance(error, (OSError, socket.timeout, TimeoutError, RobotTransportError)) and not isinstance(error, RobotActionError):
            self._clean_close = False
            self._close_channels()

    def _close_channels(self) -> None:
        for channel in (self._dashboard, self._feedback):
            if channel is not None:
                try:
                    channel.close()  # type: ignore[attr-defined]
                except OSError:
                    pass
        self._dashboard = None
        self._feedback = None

    @staticmethod
    def _raise_dashboard_error(reply: DashboardReply, action: str) -> None:
        if reply.error_id != 0:
            raise RobotActionError(
                reply.error_id,
                reply.error_id,
                f"机器人拒绝 {action}: {reply.raw}",
            )

    @staticmethod
    def _reply_command_id(reply: DashboardReply, action: str) -> int:
        if len(reply.values) != 1 or not reply.values[0].is_integer():
            raise RobotTransportError(f"{action} 未返回唯一 CommandId: {reply.raw}")
        return int(reply.values[0])

    @staticmethod
    def _validate_options(options: MotionOptions) -> None:
        if not 1 <= options.acc <= 100 or not 1 <= options.vel <= 100:
            raise ValueError("acc/vel 必须在 1..100")
        if not 0 <= options.cp <= 100:
            raise ValueError("cp 必须在 0..100")
        if options.user < 0 or options.tool < 0:
            raise ValueError("user/tool 不能为负数")

    @staticmethod
    def _six(values: Sequence[float], label: str) -> tuple[float, ...]:
        if len(values) != 6:
            raise ValueError(f"{label} 必须包含 6 个数值")
        return tuple(float(value) for value in values)

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{float(value):.6f}"

    @staticmethod
    def _io_bit(bits: int, one_based_channel: int) -> bool:
        return bool(bits & (1 << (one_based_channel - 1)))
