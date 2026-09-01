"""录制器接入点: 必须挂总线 tap, 不能挂 VmController 的 event_sink。

这一组守的是一个会**静默**失败的接线错误。高频连续量 (axis_pose / robot_pose /
mechanism_state / signal_light) 由 realtime_feedback 与 30004 观察者**直接**
bus.publish, 完全不经过 event_sink。把录制器挂到 sink 上, 录出来的东西看着一切正常
(运行事件齐全、文件在长、状态端点显示"录制中"), 但连续量一条都没有 —— 而连续量正是
整个回放功能的全部意义所在。等发现时录像已经白录了。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from eit_ptlc.runtime.events import EventBus, make_event_sink
from eit_ptlc.runtime.recording.codec import decode_chunk
from eit_ptlc.runtime.recording.recorder import StateRecorder
from eit_ptlc.runtime.recording.store import RecordingStore

T0 = 1786000000.0
# 仓内真实的单点控制点表 —— 录制器按它把机构归到工位 (利用率条的分组依据)
_POINTS = Path(__file__).resolve().parents[1] / "config" / "manual_points.yaml"


@pytest.fixture()
def store(tmp_path):
    s = RecordingStore(tmp_path / "rec")
    yield s
    s.close()


def _drain(recorder, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if recorder.status()["queued"] == 0:
            time.sleep(0.05)
            if recorder.status()["queued"] == 0:
                return
        time.sleep(0.02)
    raise AssertionError("写盘线程未清空队列")


def test_high_rate_events_bypass_the_vm_event_sink():
    """把接线前提本身钉死: 连续量不经过 event_sink。

    这条不是测我们的代码, 是测我们赖以设计的那个事实。哪天连续量改走 sink 了, 这条
    会红, 提醒重新评估接入点 —— 而不是等到录像里没有轨迹才发现。
    """
    seen_by_sink = []
    bus = EventBus()
    sink = make_event_sink(seen_by_sink.append, bus.publish)

    tapped = []
    bus.add_tap(tapped.append)

    # realtime_feedback 与 _publish_robot_pose 的真实做法: 直接发总线
    bus.publish({"type": "axis_pose", "ts": T0, "positions": {"axis_1z": 1.0}})
    bus.publish({"type": "robot_pose", "ts": T0, "joint": [0] * 6, "pose": [0] * 6})
    # VM 事件的真实做法: 走 sink (sink 内部再转发给总线)
    sink({"type": "operation_start", "ts": T0, "run_id": "R1"})

    assert [e["type"] for e in seen_by_sink] == ["operation_start"], (
        "连续量若出现在 sink 里, 说明上游改了发布路径, 接入点需要重新评估")
    assert [e["type"] for e in tapped] == ["axis_pose", "robot_pose", "operation_start"], (
        "tap 必须同时看到直接发布的连续量与经 sink 转发的运行事件")


def test_tap_sees_events_before_subscriber_drop_policy():
    """tap 在按订阅者丢帧之前调用 —— 录到的要比任何前端客户端都全。"""
    bus = EventBus(max_queue=4)
    tapped = []
    bus.add_tap(tapped.append)

    async def _fill():
        async with bus.subscribe():
            for i in range(40):
                bus.publish({"type": "axis_pose", "ts": T0 + i,
                             "positions": {"axis_1z": float(i)}})

    import asyncio
    asyncio.run(_fill())
    assert len(tapped) == 40, f"tap 应看到全部 40 条, 实际 {len(tapped)}"


def test_droppable_sets_stay_in_sync_with_the_bus():
    """录制器与总线的丢帧取舍必须一致。

    两处各自维护一份可丢类型表, 一旦漂移就会出现"实时画面上有、录像里没有"(或反之)
    这种极难排查的现象。本仓常有第二个会话在同时改 events.py 的这张表 —— 这条断言
    就是那次漂移的告警器。
    """
    from eit_ptlc.runtime.events import _DROPPABLE_TYPES
    from eit_ptlc.runtime.recording.recorder import _DROPPABLE

    assert _DROPPABLE == _DROPPABLE_TYPES, (
        "录制器可丢类型与总线不一致: "
        f"仅总线有 {_DROPPABLE_TYPES - _DROPPABLE}; 仅录制器有 {_DROPPABLE - _DROPPABLE_TYPES}"
    )


def test_tap_isolates_observer_failures():
    """旁路观察者故障绝不能影响实时推送。"""
    bus = EventBus()
    delivered = []

    def boom(_event):
        raise RuntimeError("录制器炸了")

    bus.add_tap(boom)
    bus.add_tap(delivered.append)
    bus.publish({"type": "axis_pose", "ts": T0})
    assert len(delivered) == 1


def test_add_tap_is_idempotent_and_removable():
    bus = EventBus()
    first: list = []
    second: list = []

    def tap_a(event):
        first.append(event)

    def tap_b(event):
        second.append(event)

    bus.add_tap(tap_a)
    bus.add_tap(tap_a)          # 重复登记不应重复投递
    bus.add_tap(tap_b)
    bus.publish({"type": "x"})
    assert len(first) == 1 and len(second) == 1

    bus.remove_tap(tap_a)
    bus.publish({"type": "y"})
    assert len(first) == 1, "已摘除的 tap 不应再收到事件"
    assert len(second) == 2, "摘除一个不应影响其它 tap"

    bus.remove_tap(tap_a)       # 重复摘除不应抛错
    bus.publish({"type": "z"})
    assert len(second) == 3


def test_recorder_on_bus_tap_captures_continuous_state_end_to_end(store):
    """接线的最终验收: 经总线发布的轨迹, 必须能从录像里逐帧读回来。"""
    bus = EventBus()
    recorder = StateRecorder(store, chunk_seconds=2.0)
    recorder.start()
    bus.add_tap(recorder.on_event)
    truth = []
    try:
        for i in range(120):
            ts = T0 + i * 0.02
            pos = 250.0 - i * 0.75
            truth.append((ts, pos))
            bus.publish({"type": "axis_pose", "ts": ts, "positions": {"axis_11y": pos}})
        bus.publish({"type": "operation_start", "ts": T0 + 3, "run_id": "R9",
                     "operation": "collect"})
        _drain(recorder)
    finally:
        recorder.stop()
    store.flush()

    frames: list[tuple[float, float]] = []
    for meta in store.chunks_in_range(T0, T0 + 60):
        chunk = decode_chunk(store.read_chunk(meta["path"]))
        stream = chunk.streams.get("axis_pose")
        if stream:
            frames.extend(zip(stream["ts"], stream["channels"]["axis_11y.position"]))

    assert len(frames) == len(truth), (
        f"应录到 {len(truth)} 帧连续量, 实际 {len(frames)} —— 接错点就会是 0")
    for (want_ts, want_pos), (got_ts, got_pos) in zip(truth, sorted(frames)):
        assert got_ts == pytest.approx(want_ts, abs=1e-3)
        assert got_pos == pytest.approx(want_pos, abs=0.025)

    assert store.markers_in_range(T0, T0 + 60), "运行事件应同时打上时间轴标记"


def test_recorder_is_off_under_pytest_by_default(monkeypatch):
    """离线测试绝不该往仓库 var/ 里写真录像, 也不该几十个用例去抢同一个索引库。"""
    from eit_ptlc.runtime.bootstrap import _build_recorder

    monkeypatch.delenv("PTLC_RECORD_ENABLED", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "dummy::test (call)")
    assert _build_recorder(sim_mode=True, manual_points_file=_POINTS) is None


def test_explicit_flag_still_wins_under_pytest(monkeypatch, tmp_path):
    """显式打开时仍要能录 —— 否则没法在测试里验证录制本身。"""
    from eit_ptlc.runtime.bootstrap import _build_recorder

    monkeypatch.setenv("PTLC_RECORD_ENABLED", "1")
    monkeypatch.setenv("PTLC_RECORD_ROOT", str(tmp_path / "explicit"))
    recorder = _build_recorder(sim_mode=True, manual_points_file=_POINTS)
    assert recorder is not None
    try:
        assert recorder.running
    finally:
        recorder.stop()
        recorder.store.close()


def test_store_sets_busy_timeout_so_concurrent_writers_wait(tmp_path):
    """WAL 只解决读写并发; 两个写者仍会撞锁, 不设超时就直接抛 database is locked。"""
    from eit_ptlc.runtime.recording.store import RecordingStore

    store = RecordingStore(tmp_path / "busy")
    try:
        assert store._conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    finally:
        store.close()
