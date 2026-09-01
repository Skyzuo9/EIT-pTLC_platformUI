"""机器人原子动作传输接口与 Modbus TCP 回退实现。

The public interface contains robot semantics only. Register addresses remain an
implementation detail of :class:`ModbusRobotTransport`.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Iterable, Sequence


class RobotStatus(IntEnum):
    FREE = 0
    BUSY = 1
    DONE = 2
    ERROR = 3


class ToolAction(IntEnum):
    QUICK_CHANGE_LOCK = 1
    QUICK_CHANGE_RELEASE = 2
    SUCTION_ON = 3
    SUCTION_OFF = 4
    GRIPPER_OPEN = 5
    GRIPPER_CLOSE = 6
    GET_STATE = 7
    TOOL_CHANGE_AUX_ON = 8
    TOOL_CHANGE_AUX_OFF = 9
    ROTARY_UP = 10
    ROTARY_DOWN = 11


TOOL_ACTION_NAMES = {
    "quick-change-lock": ToolAction.QUICK_CHANGE_LOCK,
    "quick-change-release": ToolAction.QUICK_CHANGE_RELEASE,
    "suction-on": ToolAction.SUCTION_ON,
    "suction-off": ToolAction.SUCTION_OFF,
    "gripper-open": ToolAction.GRIPPER_OPEN,
    "gripper-close": ToolAction.GRIPPER_CLOSE,
    "get-state": ToolAction.GET_STATE,
    "tool-change-aux-on": ToolAction.TOOL_CHANGE_AUX_ON,
    "tool-change-aux-off": ToolAction.TOOL_CHANGE_AUX_OFF,
    "rotary-up": ToolAction.ROTARY_UP,
    "rotary-down": ToolAction.ROTARY_DOWN,
}


@dataclass(frozen=True)
class MotionProfile:
    """?????????????????????? user/tool?"""

    acc: int
    vel: int
    cp: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.acc <= 100 or not 1 <= self.vel <= 100 or not 0 <= self.cp <= 100:
            raise ValueError("motion profile acc/vel must be 1..100 and cp must be 0..100")


@dataclass(frozen=True)
class MotionOptions:
    user: int = 0
    tool: int = 1
    acc: int = 20
    vel: int = 20
    cp: int = 0


@dataclass(frozen=True)
class ToolState:
    commanded_bits: int
    actual_bits: int | None
    di_bits: int
    di_available: bool
    di_confirmed: bool


@dataclass(frozen=True)
class RobotFeedback:
    pose: tuple[float, ...]
    joint: tuple[float, ...]
    check_result: int
    last_action: int
    tool_state: ToolState
    robot_mode: int | None = None
    command_id: int | None = None
    error_ids: tuple[int, ...] = ()
    connected: bool = True
    details: dict[str, object] = field(default_factory=dict)


class RobotTransportError(RuntimeError):
    """Communication or protocol failure."""


class RobotActionError(RobotTransportError):
    def __init__(self, error_id: int, check_result: int, message: str | None = None) -> None:
        super().__init__(message or f"robot action failed: error_id={error_id}, check={check_result}")
        self.error_id = error_id
        self.check_result = check_result


class RobotTransport(ABC):
    """Single-owner robot atomic-action boundary."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback: ...

    @abstractmethod
    def home(self, options: MotionOptions = MotionOptions()) -> RobotFeedback: ...

    @abstractmethod
    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback: ...

    @abstractmethod
    def move_l(self, pose: Sequence[float], options: MotionOptions = MotionOptions()) -> RobotFeedback: ...

    @abstractmethod
    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback: ...


class _RegisterMap:
    EXECUTE = 3100
    RESET = 3101
    FUNCTION_ID = 3102
    STATUS = 3200
    ERROR_ID = 3202
    USER = 3400
    TOOL = 3401
    ACC = 3402
    VEL = 3403
    CP = 3404
    TOOL_ACTION = 3405
    TOOL_TIMEOUT_MS = 3406
    TARGET_POSE = (3410, 3412, 3414, 3416, 3418, 3420)
    TARGET_JOINT = (3422, 3424, 3426, 3428, 3430, 3432)
    USE_JOINT_TARGET = 3407
    FEEDBACK_POSE = (3440, 3442, 3444, 3446, 3448, 3450)
    FEEDBACK_JOINT = (3460, 3462, 3464, 3466, 3468, 3470)
    CHECK_RESULT = 3480
    LAST_ACTION = 3481
    TOOL_COMMANDED = 3482
    TOOL_ACTUAL = 3483
    TOOL_FLAGS = 3484
    TOOL_DI_BITS = 3485


class _FunctionId(IntEnum):
    QUERY = 24
    MOVE_J = 25
    HOME = 26
    MOVE_L = 27
    TOOL_ACTION = 28


class _ModbusTcpClient:
    def __init__(self, host: str, port: int, unit_id: int, timeout: float) -> None:
        self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
        self._socket: socket.socket | None = None
        self._transaction_id = 0
        self._io_lock = threading.Lock()

    def connect(self) -> None:
        self._socket = socket.create_connection((self.host, self.port), self.timeout)
        self._socket.settimeout(self.timeout)

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def read(self, start: int, count: int) -> list[int]:
        response = self._request(struct.pack(">BHH", 3, start, count))
        if len(response) != count * 2 + 2 or response[:2] != bytes((3, count * 2)):
            raise RobotTransportError(f"invalid FC03 response: {response.hex()}")
        return [struct.unpack(">H", response[i:i + 2])[0] for i in range(2, len(response), 2)]

    def write(self, start: int, values: Iterable[int]) -> None:
        words = [int(value) & 0xFFFF for value in values]
        if not 1 <= len(words) <= 123:
            raise ValueError("Modbus write count must be 1..123")
        if len(words) == 1:
            request = struct.pack(">BHH", 6, start, words[0])
            if self._request(request) != request:
                raise RobotTransportError("invalid FC06 response")
            return
        payload = b"".join(struct.pack(">H", value) for value in words)
        request = struct.pack(">BHHB", 16, start, len(words), len(payload)) + payload
        if self._request(request) != struct.pack(">BHH", 16, start, len(words)):
            raise RobotTransportError("invalid FC16 response")

    def _request(self, pdu: bytes) -> bytes:
        with self._io_lock:
            if self._socket is None:
                raise RobotTransportError("robot transport is not connected")
            self._transaction_id = (self._transaction_id + 1) & 0xFFFF
            tid = self._transaction_id
            self._socket.sendall(struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id) + pdu)
            header = self._recv_exact(7)
            rx_tid, protocol, length, unit = struct.unpack(">HHHB", header)
            if (rx_tid, protocol, unit) != (tid, 0, self.unit_id):
                raise RobotTransportError("invalid Modbus MBAP header")
            response = self._recv_exact(length - 1)
            if response[0] & 0x80:
                raise RobotTransportError(f"Modbus exception code={response[1]}")
            return response

    def _recv_exact(self, size: int) -> bytes:
        assert self._socket is not None
        data = bytearray()
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise RobotTransportError("robot closed the Modbus connection")
            data.extend(chunk)
        return bytes(data)


class ModbusRobotTransport(RobotTransport):
    """Synchronous, serialized adapter for robot_mvp_minimal.lua."""

    def __init__(
        self,
        host: str,
        port: int = 502,
        unit_id: int = 1,
        timeout: float | None = None,
        socket_timeout: float = 5.0,
        ack_timeout: float = 10.0,
        byte_order: str = "word-swap",
        status_callback: Callable[[RobotStatus, float], None] | None = None,
    ) -> None:
        if byte_order not in {"be", "word-swap"}:
            raise ValueError("byte_order must be 'be' or 'word-swap'")
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive or None")
        if ack_timeout <= 0:
            raise ValueError("ack_timeout must be positive")
        self._client = _ModbusTcpClient(host, port, unit_id, socket_timeout)
        self.timeout = timeout
        self.ack_timeout = ack_timeout
        self.byte_order = byte_order
        self._status_callback = status_callback
        self._last_reported_status: RobotStatus | None = None
        self._next_status_report_at = 0.0
        self._action_lock = threading.Lock()

    def connect(self) -> None:
        self._client.connect()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ModbusRobotTransport":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def query(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        return self._run(_FunctionId.QUERY, options)

    def home(self, options: MotionOptions = MotionOptions()) -> RobotFeedback:
        return self._run(_FunctionId.HOME, options)

    def move_j(
        self,
        pose: Sequence[float],
        options: MotionOptions = MotionOptions(),
        *,
        joint: Sequence[float] | None = None,
    ) -> RobotFeedback:
        return self._run(_FunctionId.MOVE_J, options, pose=pose, joint=joint)

    def move_l(self, pose: Sequence[float], options: MotionOptions = MotionOptions()) -> RobotFeedback:
        return self._run(_FunctionId.MOVE_L, options, pose=pose)

    def tool_action(self, action: ToolAction, timeout_ms: int = 3000) -> RobotFeedback:
        if not 100 <= timeout_ms <= 60000:
            raise ValueError("tool timeout_ms must be 100..60000")
        return self._run(
            _FunctionId.TOOL_ACTION,
            MotionOptions(),
            tool_action=ToolAction(action),
            tool_timeout_ms=timeout_ms,
        )

    def _run(
        self,
        function_id: _FunctionId,
        options: MotionOptions,
        *,
        pose: Sequence[float] | None = None,
        joint: Sequence[float] | None = None,
        tool_action: ToolAction | None = None,
        tool_timeout_ms: int = 3000,
    ) -> RobotFeedback:
        with self._action_lock:
            self._wait_status({RobotStatus.FREE}, 5.0)
            self._write_u16(_RegisterMap.USE_JOINT_TARGET, 0)
            if pose is not None:
                self._write_pose(pose)
            if joint is not None and function_id == _FunctionId.MOVE_J:
                self._write_joint(joint)
                self._write_u16(_RegisterMap.USE_JOINT_TARGET, 1)
            if tool_action is not None:
                self._write_u16(_RegisterMap.TOOL_ACTION, int(tool_action))
                self._write_u16(_RegisterMap.TOOL_TIMEOUT_MS, tool_timeout_ms)
            self._prepare(function_id, options)
            started_at = time.monotonic()
            # 将 EXECUTE=1、RESET=0、FUNCTION_ID 原子写入相邻寄存器
            # (3100/3101/3102)，消除 FC06 分次写入时 Lua 读到
            # EXECUTE=1 但 FUNCTION_ID 尚未对 Client 可见的竞态窗口。
            #
            # 写入后回读验证 + 最多 2 次重试，防止 Modbus Server 缓存
            # 未刷新导致机器人 WaitValue(REG_EXECUTE,1) 永远读不到 1。
            _EXECUTE_RETRIES = 2
            for _attempt in range(1 + _EXECUTE_RETRIES):
                self._client.write(_RegisterMap.EXECUTE, (1, 0, int(function_id)))
                time.sleep(0.02)  # 等待 Modbus Server 传播（匹配 Lua Wait(20)）
                if self._read_u16(_RegisterMap.EXECUTE) == 1:
                    break
            else:
                raise RobotTransportError(
                    f"EXECUTE=1 write not reflected after {1 + _EXECUTE_RETRIES} attempts"
                )
            try:
                # 接单超时和运动超时独立配置：机器人应在 ack_timeout 内进入
                # BUSY，但低速/长距离运动默认可以一直执行到 DONE/ERROR。
                # 如果接单超时，尝试重写 EXECUTE（最多一次），应对 Modbus
                # 缓存窗口导致机器人漏读的边界情况。
                for _ack_attempt in range(2):
                    try:
                        status = self._wait_status(
                            {RobotStatus.BUSY, RobotStatus.DONE, RobotStatus.ERROR},
                            self.ack_timeout,
                            started_at=started_at,
                        )
                        break
                    except TimeoutError:
                        if _ack_attempt == 0:
                            # 重写 EXECUTE 再试一次
                            self._client.write(
                                _RegisterMap.EXECUTE, (1, 0, int(function_id))
                            )
                            time.sleep(0.02)
                        else:
                            raise
                if status == RobotStatus.BUSY:
                    status = self._wait_status(
                        # 部分现场机器人运行时在动作结束后直接回 FREE，未按
                        # Lua 合同锁存 DONE。允许 BUSY->FREE 进入反馈校验，
                        # 但仍必须由 last_action 证明本条命令确实完成。
                        {RobotStatus.FREE, RobotStatus.DONE, RobotStatus.ERROR},
                        self.timeout,
                        started_at=started_at,
                    )
                if status == RobotStatus.ERROR:
                    error_id = self._read_u16(_RegisterMap.ERROR_ID)
                    check = self._read_u16(_RegisterMap.CHECK_RESULT)
                    self._pulse_reset()
                    raise RobotActionError(error_id, check)
                feedback = self._read_feedback()
                if feedback.last_action != int(function_id):
                    raise RobotTransportError(
                        "robot returned FREE/DONE without matching feedback: "
                        f"expected last_action={int(function_id)}, got {feedback.last_action}; "
                        "check whether the deployed Lua program latches DONE"
                    )
                return feedback
            finally:
                # 清理失败不能覆盖原始动作异常（尤其是显式硬超时）。
                has_pending_error = sys.exc_info()[0] is not None
                try:
                    self._write_u16(_RegisterMap.EXECUTE, 0)
                    self._wait_status({RobotStatus.FREE}, 5.0)
                except BaseException:
                    if not has_pending_error:
                        raise

    def _prepare(self, function_id: _FunctionId, options: MotionOptions) -> None:
        if not 1 <= options.acc <= 100:
            raise ValueError("acc must be 1..100")
        if not 1 <= options.vel <= 100:
            raise ValueError("vel must be 1..100")
        if not 0 <= options.cp <= 100:
            raise ValueError("cp must be 0..100")
        # RESET=0 必须在 EXECUTE=1 原子写之前落盘，防止机器人 Lua
        # 在 EXECUTE=1 和 RESET=0 之间读到竞争窗口。
        # FUNCTION_ID 由 EXECUTE 原子写一并下发，此处不再单独写，避免
        # FC06 写 3102 紧随 FC16 写 3100-3102 引发 Modbus 缓存刷新窗口。
        for addr, value in (
            (_RegisterMap.RESET, 0), (_RegisterMap.USER, options.user),
            (_RegisterMap.TOOL, options.tool), (_RegisterMap.ACC, options.acc),
            (_RegisterMap.VEL, options.vel), (_RegisterMap.CP, options.cp),
        ):
            self._write_u16(addr, value)

    def _write_pose(self, pose: Sequence[float]) -> None:
        if len(pose) != 6:
            raise ValueError("pose must contain six values")
        for addr, value in zip(_RegisterMap.TARGET_POSE, pose):
            self._write_f32(addr, float(value))

    def _write_joint(self, joint: Sequence[float]) -> None:
        if len(joint) != 6:
            raise ValueError("joint must contain six values")
        for addr, value in zip(_RegisterMap.TARGET_JOINT, joint):
            self._write_f32(addr, float(value))

    def _read_feedback(self) -> RobotFeedback:
        pose = tuple(self._read_f32(addr) for addr in _RegisterMap.FEEDBACK_POSE)
        joint = tuple(self._read_f32(addr) for addr in _RegisterMap.FEEDBACK_JOINT)
        flags = self._read_u16(_RegisterMap.TOOL_FLAGS)
        actual_raw = self._read_u16(_RegisterMap.TOOL_ACTUAL)
        return RobotFeedback(
            pose=pose,
            joint=joint,
            check_result=self._read_u16(_RegisterMap.CHECK_RESULT),
            last_action=self._read_u16(_RegisterMap.LAST_ACTION),
            tool_state=ToolState(
                commanded_bits=self._read_u16(_RegisterMap.TOOL_COMMANDED),
                actual_bits=None if actual_raw == 0xFFFF else actual_raw,
                di_bits=self._read_u16(_RegisterMap.TOOL_DI_BITS),
                di_available=bool(flags & 2),
                di_confirmed=bool(flags & 4),
            ),
        )

    def _wait_status(
        self,
        expected: set[RobotStatus],
        timeout: float | None,
        *,
        started_at: float | None = None,
    ) -> RobotStatus:
        wait_started = time.monotonic()
        action_started = wait_started if started_at is None else started_at
        deadline = None if timeout is None else wait_started + timeout
        last_status: RobotStatus | None = None
        while deadline is None or time.monotonic() < deadline:
            raw = self._read_u16(_RegisterMap.STATUS)
            try:
                status = RobotStatus(raw)
            except ValueError as exc:
                raise RobotTransportError(f"unknown robot status: {raw}") from exc
            last_status = status
            now = time.monotonic()
            if self._status_callback is not None and (
                status != self._last_reported_status
                or now >= self._next_status_report_at
            ):
                self._status_callback(status, now - action_started)
                self._last_reported_status = status
                self._next_status_report_at = now + 5.0
            if status in expected:
                return status
            time.sleep(0.05)
        elapsed = time.monotonic() - wait_started
        raise TimeoutError(
            f"timed out waiting for robot status {sorted(int(x) for x in expected)} "
            f"(current={last_status.name if last_status is not None else '?'}, "
            f"elapsed={elapsed:.1f}s, timeout={timeout}s)"
        )

    def _pulse_reset(self) -> None:
        self._write_u16(_RegisterMap.RESET, 1)
        time.sleep(0.2)
        self._write_u16(_RegisterMap.RESET, 0)

    def _read_u16(self, addr: int) -> int:
        return self._client.read(addr, 1)[0]

    def _write_u16(self, addr: int, value: int) -> None:
        self._client.write(addr, (value,))

    def _write_f32(self, addr: int, value: float) -> None:
        hi, lo = struct.unpack(">HH", struct.pack(">f", value))
        self._client.write(addr, (lo, hi) if self.byte_order == "word-swap" else (hi, lo))

    def _read_f32(self, addr: int) -> float:
        hi, lo = self._client.read(addr, 2)
        if self.byte_order == "word-swap":
            hi, lo = lo, hi
        return struct.unpack(">f", struct.pack(">HH", hi, lo))[0]
