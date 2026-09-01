"""Dobot 30004 反馈重同步离线测试
==============================
功能:
    用 fake socket 验证 _FeedbackChannel.read_frame 在 30004 流持续错位时不崩溃:
    先吐若干轮纯错位字节 (无合法帧), 再吐一个合法帧 -> read_frame 应返回该帧,
    且全程不抛 RecursionError (修复前真递归取下一帧会栈无限增长).
    不依赖真机或网络.

运行:
    & "E:/Anaconda/envs/platformupper/python.exe" -m eit_ptlc.tests.test_dobot_feedback_resync_offline
期望:
    全部用例打印 PASS, 退出码 0.
"""

from __future__ import annotations

import struct
import sys

from eit_ptlc.driver.dobot_tcp_driver import (
    FEEDBACK_MAGIC,
    FEEDBACK_SIZE,
    DobotFeedbackFrame,
    _FeedbackChannel,
    parse_feedback_packet,
)
from eit_ptlc.driver.robot_transport import RobotTransportError


def _valid_packet(robot_mode: int = 5, command_id: int = 123) -> bytes:
    """构造一个能通过 parse_feedback_packet 的合法 1440 字节反馈包 (按官方 V4 小端布局)."""
    data = bytearray(FEEDBACK_SIZE)
    struct.pack_into("<H", data, 0, FEEDBACK_SIZE)          # len
    struct.pack_into("<Q", data, 48, FEEDBACK_MAGIC)        # TestValue
    struct.pack_into("<Q", data, 24, robot_mode)            # robot_mode
    struct.pack_into("<Q", data, 1112, command_id)          # current_command_id
    return bytes(data)


class _FakeSocket:
    """fake 30004 socket: 按预设 chunk 序列逐次返回, recv 耗尽后再调用即视为编程错误."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self._closed = False

    def recv(self, _bufsize: int) -> bytes:
        if not self._chunks:
            raise AssertionError("fake socket recv 被调用次数超出预设 (read_frame 未在合法帧处返回)")
        return self._chunks.pop(0)

    def close(self) -> None:
        self._closed = True


def _drain_no_data(monkeypatch) -> None:
    """让 select.select 始终报告"无后续可读", 使 read_frame 走纯阻塞 recv 路径."""
    import eit_ptlc.driver.dobot_tcp_driver as drv

    monkeypatch.setattr(drv.select, "select", lambda *a, **k: ((), (), ()))


def test_persistent_misalignment_then_valid_frame(monkeypatch) -> None:
    # 先若干轮纯错位字节 (每轮 >=FEEDBACK_SIZE, 全无合法包头), 再给一个合法帧
    _drain_no_data(monkeypatch)
    valid = _valid_packet(robot_mode=7, command_id=456)
    noise_rounds = 50
    chunks = [b"\x00" * FEEDBACK_SIZE for _ in range(noise_rounds)]
    chunks.append(valid)

    ch = _FeedbackChannel(_FakeSocket(chunks))
    try:
        frame = ch.read_frame()  # 修复前: 50 层真递归; 大量错位时会 RecursionError
    except RecursionError:
        raise AssertionError("持续错位不应触发 RecursionError, 应循环重试")
    assert isinstance(frame, DobotFeedbackFrame), type(frame)
    assert frame.robot_mode == 7, frame.robot_mode
    assert frame.current_command_id == 456, frame.current_command_id


def test_many_noise_rounds_no_recursion_error(monkeypatch) -> None:
    # 远超默认递归上限的错位轮数: 修复前必 RecursionError, 修复后恒定栈深通过
    _drain_no_data(monkeypatch)
    rounds = sys.getrecursionlimit() + 200
    chunks = [b"\x7f" * FEEDBACK_SIZE for _ in range(rounds)]
    chunks.append(_valid_packet(robot_mode=5, command_id=1))

    ch = _FeedbackChannel(_FakeSocket(chunks))
    frame = ch.read_frame()
    assert frame.robot_mode == 5, frame.robot_mode
    assert frame.current_command_id == 1, frame.current_command_id


def test_socket_closed_raises_transport_error(monkeypatch) -> None:
    # socket 关闭 (recv 返回空) 仍抛 RobotTransportError, 不被循环吞掉
    _drain_no_data(monkeypatch)
    ch = _FeedbackChannel(_FakeSocket([b""]))
    try:
        ch.read_frame()
    except RobotTransportError:
        return
    raise AssertionError("socket 关闭应抛 RobotTransportError")


def test_valid_packet_roundtrips() -> None:
    # 自检: 构造的合法包确实能被解析器接受 (避免测试因构包错误而假阳性)
    frame = parse_feedback_packet(_valid_packet(robot_mode=8, command_id=99))
    assert frame.robot_mode == 8 and frame.current_command_id == 99


class _Monkeypatch:
    """无 pytest 依赖时的极简 monkeypatch 兜底 (仅支持 setattr + 自动还原)."""

    def __init__(self) -> None:
        self._undo: list = []

    def setattr(self, target, name, value) -> None:
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)
        self._undo.clear()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    import inspect

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        mp = _Monkeypatch()
        try:
            if "monkeypatch" in inspect.signature(fn).parameters:
                fn(mp)
            else:
                fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
        finally:
            mp.undo()
    print(f"\n共 {len(tests)} 用例, 失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
