"""录制器与录像库: 丢帧策略、关键帧合并、保留策略、跨机可移植性。"""

from __future__ import annotations

import json
import time

import pytest

from eit_ptlc.runtime.recording.codec import decode_chunk
from eit_ptlc.runtime.recording.recorder import StateRecorder, _flatten
from eit_ptlc.runtime.recording.store import RecordingStore, default_root

T0 = 1786000000.0


@pytest.fixture()
def store(tmp_path):
    s = RecordingStore(tmp_path / "rec", retention_days=30)
    yield s
    s.close()


def _drain(recorder: StateRecorder, timeout=3.0):
    """等后台线程把队列吃干净。"""
    end = time.time() + timeout
    while time.time() < end:
        if recorder.status()["queued"] == 0:
            time.sleep(0.05)
            if recorder.status()["queued"] == 0:
                return
        time.sleep(0.02)
    raise AssertionError("后台写盘线程未能及时清空队列")


# -- 摊平 -------------------------------------------------------------

def test_flatten_axis_and_robot_and_mechanism():
    stream, ts, values = _flatten({"type": "axis_pose", "ts": T0,
                                   "positions": {"axis_1z": 12.5},
                                   "velocities": {"axis_1z": -3.25}})
    assert stream == "axis_pose" and ts == T0
    assert values == {"axis_1z.position": 12.5, "axis_1z.velocity": -3.25}

    _s, _t, values = _flatten({"type": "robot_pose", "ts": T0,
                               "joint": [1, 2, 3, 4, 5, 6],
                               "pose": [10, 20, 30, 40, 50, 60],
                               "tool": 1, "mode": 5})
    assert values["joint0"] == 1 and values["joint5"] == 6
    assert values["pose_xyz0"] == 10 and values["pose_rpy2"] == 60
    assert values["tool"] == 1 and values["mode"] == 5

    _s, _t, values = _flatten({"type": "mechanism_state", "ts": T0,
                               "states": {"dev_v1": {"commanded": True, "confirmed": None}}})
    assert values == {"dev_v1.commanded": True, "dev_v1.confirmed": None}

    assert _flatten({"type": "vm_node_enter", "ts": T0}) is None
    assert _flatten({"type": "axis_pose"}) is None  # 无 ts 不入帧


# -- 丢帧策略 ---------------------------------------------------------

def test_drop_policy_never_drops_incremental_events(store):
    """scrape_state 丢一条就永远画不出刮痕; vm_node_enter 是 args 的唯一来源。"""
    rec = StateRecorder(store, chunk_seconds=1e9, queue_max=50)
    rec._active = True  # 只开收事件, 不起写盘线程, 以便直接观察队列内容
    try:
        for i in range(200):
            rec.on_event({"type": "axis_pose", "ts": T0 + i * 0.02,
                          "positions": {"axis_1z": float(i)}})
        rec.on_event({"type": "scrape_state", "ts": T0 + 9, "phase": "pass"})
        rec.on_event({"type": "vm_node_enter", "ts": T0 + 9.1, "aid": "a1",
                      "args": {"action": "gripper-close"}})
        for i in range(200):
            rec.on_event({"type": "mechanism_state", "ts": T0 + 10 + i * 0.1, "states": {}})

        kept = [e["type"] for e in rec._queue]
        assert "scrape_state" in kept, "scrape_state 被丢了"
        assert "vm_node_enter" in kept, "vm_node_enter 被丢了"
        assert rec.dropped > 0, "高频快照类应当被挤掉"
        assert all(t in ("axis_pose", "mechanism_state", "scrape_state", "vm_node_enter")
                   for t in kept)
    finally:
        rec._active = False


def test_dropped_count_is_reported(store):
    rec = StateRecorder(store, queue_max=10)
    rec._active = True
    try:
        for i in range(50):
            rec.on_event({"type": "telemetry", "ts": T0 + i, "node": "n"})
        assert rec.status()["dropped"] == 40
    finally:
        rec._active = False


# -- 关键帧 -----------------------------------------------------------

def test_keyframe_merges_sticky_mechanism_fields(store):
    """机构字段刻意粘滞: 关键帧必须是逐字段合并结果, 不是最后一条事件。"""
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        rec.on_event({"type": "mechanism_state", "ts": T0,
                      "states": {"v1": {"commanded": True, "confirmed": True,
                                        "available": True, "source": "feedback"}}})
        # 第二条只带了 confirmed —— 关键帧不能因此丢掉 commanded/source
        rec.on_event({"type": "mechanism_state", "ts": T0 + 1, "states": {"v1": {"confirmed": None}}})
        rec.on_event({"type": "axis_pose", "ts": T0 + 2, "positions": {"axis_1z": 5.0}})
        _drain(rec)
        # 跨块: 下一块块首关键帧应带合并后的完整记录
        rec.on_event({"type": "axis_pose", "ts": T0 + 12, "positions": {"axis_1z": 6.0}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    chunks = store.chunks_in_range(T0 + 11, T0 + 20)
    assert chunks, "第二块应已落盘"
    chunk = decode_chunk(store.read_chunk(chunks[0]["path"]))
    v1 = chunk.keyframe["mechanisms"]["v1"]
    assert v1["confirmed"] is None, "最新的 confirmed 应生效"
    assert v1["commanded"] is True, "粘滞的 commanded 不应被后一条部分快照抹掉"
    assert v1["source"] == "feedback"


def test_material_state_keyframe_carries_initial_flag(store):
    """前端 MaterialStateStore 有时间戳倒退闸门, initial:true 是绕过它的既有通路。"""
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        rec.on_event({"type": "material_state", "ts": T0, "cells": {"a": 1}})
        rec.on_event({"type": "axis_pose", "ts": T0 + 1, "positions": {"axis_1z": 1.0}})
        _drain(rec)
        rec.on_event({"type": "axis_pose", "ts": T0 + 12, "positions": {"axis_1z": 2.0}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()
    chunks = store.chunks_in_range(T0 + 11, T0 + 20)
    chunk = decode_chunk(store.read_chunk(chunks[0]["path"]))
    assert chunk.keyframe["materialState"]["initial"] is True


# -- 端到端 -----------------------------------------------------------

def test_records_and_replays_a_motion_faithfully(store):
    rec = StateRecorder(store, chunk_seconds=2.0)
    rec.start()
    truth = []
    try:
        for i in range(150):
            ts = T0 + i * 0.02
            pos = 100.0 + i * 0.5
            truth.append((ts, pos))
            rec.on_event({"type": "axis_pose", "ts": ts, "positions": {"axis_9x": pos}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    got: list[tuple[float, float]] = []
    for meta in store.chunks_in_range(T0, T0 + 100):
        chunk = decode_chunk(store.read_chunk(meta["path"]))
        stamps = chunk.streams["axis_pose"]["ts"]
        values = chunk.streams["axis_pose"]["channels"]["axis_9x.position"]
        got.extend(zip(stamps, values))

    assert len(got) == len(truth), f"帧数不符 {len(got)} vs {len(truth)}"
    for (gt_ts, gt_pos), (ts, pos) in zip(truth, sorted(got)):
        assert ts == pytest.approx(gt_ts, abs=1e-3)
        assert pos == pytest.approx(gt_pos, abs=0.025)


def test_markers_are_written_for_run_lifecycle(store):
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        rec.on_event({"type": "operation_start", "ts": T0, "run_id": "R1", "operation": "collect"})
        rec.on_event({"type": "operation_failed", "ts": T0 + 3, "run_id": "R1",
                      "operation": "collect", "message": "boom"})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    marks = store.markers_in_range(T0 - 1, T0 + 10)
    kinds = {m["kind"] for m in marks}
    assert "operation" in kinds and "alarm" in kinds
    alarm = next(m for m in marks if m["kind"] == "alarm")
    assert alarm["run_id"] == "R1" and alarm["payload"]["message"] == "boom"


def test_on_event_is_noop_before_start(store):
    rec = StateRecorder(store)
    rec.on_event({"type": "axis_pose", "ts": T0, "positions": {"a": 1.0}})
    assert rec.status()["queued"] == 0 and rec.recorded == 0


# -- 库 ---------------------------------------------------------------

def test_sim_sessions_are_separable_from_real(store):
    real = store.start_session(kind="real")
    sim = store.start_session(kind="sim")
    assert {s["id"] for s in store.list_sessions(kind="real")} == {real.id}
    assert {s["id"] for s in store.list_sessions(kind="sim")} == {sim.id}


def test_chunk_before_finds_the_keyframe_for_seek(store):
    session = store.start_session()
    for seq, t in enumerate((T0, T0 + 10, T0 + 20)):
        store.append_chunk(session, seq, t, t + 10, b"PTCDVR01x", 1)
    store.flush()
    assert store.chunk_before(T0 + 15)["seq"] == 1
    assert store.chunk_before(T0 + 25)["seq"] == 2
    assert store.chunk_before(T0 - 5) is None


def test_range_query_is_half_open_like_runs_api(store):
    session = store.start_session()
    store.append_chunk(session, 0, T0, T0 + 10, b"x", 1)
    store.append_chunk(session, 1, T0 + 10, T0 + 20, b"x", 1)
    store.flush()
    assert [c["seq"] for c in store.chunks_in_range(T0 + 10, T0 + 20)] == [0, 1]
    assert [c["seq"] for c in store.chunks_in_range(T0 + 20, T0 + 30)] == [1]


def test_retention_sweep_removes_old_sessions_and_files(store):
    now = time.time()
    old = store.start_session(now=now - 40 * 86400)
    fresh = store.start_session(now=now)
    store.append_chunk(old, 0, now - 40 * 86400, now - 40 * 86400 + 5, b"olddata", 1)
    store.append_chunk(fresh, 0, now, now + 5, b"newdata", 1)
    store.end_session(old.id, now=now - 40 * 86400 + 5)
    store.flush()
    old_dir = store.root / old.dir
    assert old_dir.exists()

    result = store.sweep_retention(now=now)
    assert old.id in result["removed"] and fresh.id not in result["removed"]
    assert not old_dir.exists(), "过期会话目录应被整个删除"
    assert [s["id"] for s in store.list_sessions()] == [fresh.id]


def test_retention_respects_byte_cap(tmp_path):
    s = RecordingStore(tmp_path / "cap", retention_days=3650, max_bytes=100)
    try:
        now = time.time()
        for i in range(4):
            session = s.start_session(now=now + i)
            s.append_chunk(session, 0, now + i, now + i + 1, b"y" * 60, 1)
        s.flush()
        s.sweep_retention(now=now + 10)
        assert (s.coverage()["bytes"] or 0) <= 100
    finally:
        s.close()


def test_chunk_path_traversal_is_rejected(store):
    with pytest.raises(ValueError, match="越界"):
        store.read_chunk("../../etc/passwd")


def test_session_dir_is_self_contained_and_portable(store, tmp_path):
    """开发机不是部署机: 目录整体拷走后必须还能列出与回放。"""
    session = store.start_session(note="portability", manifest_hash="abc123")
    store.append_chunk(session, 0, T0, T0 + 1, b"PTCDVR01payload", 3)
    store.flush()
    meta = json.loads((store.root / session.dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["manifest_hash"] == "abc123" and meta["schema_ver"] >= 1

    import shutil
    moved = tmp_path / "moved_root"
    shutil.copytree(store.root, moved)
    other = RecordingStore(moved)
    try:
        assert [s["id"] for s in other.list_sessions()] == [session.id]
        assert other.read_chunk(other.chunks_in_range(T0, T0 + 2)[0]["path"]) == b"PTCDVR01payload"
    finally:
        other.close()


def test_storage_root_is_configurable_by_env(monkeypatch, tmp_path):
    """部署机盘符与开发机不同, 存储根绝不能写死。"""
    monkeypatch.setenv("PTLC_RECORD_ROOT", str(tmp_path / "custom"))
    assert default_root() == (tmp_path / "custom").resolve()
    monkeypatch.delenv("PTLC_RECORD_ROOT")
    assert default_root().name == "recordings"


def test_index_uses_wal_not_rollback_journal(store):
    """既有 store 是 delete 日志 + 逐事件 commit, 那套写法在本模块速率上会 fsync 抖死。"""
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


# -- 时间戳合理性门 ---------------------------------------------------

@pytest.mark.parametrize("bad", [1, 10, 20, 0, -5, True, False, "x", None, 1e18])
def test_implausible_timestamps_fall_back_to_wall_clock(store, bad):
    """一条坏 ts 就能把 coverage 的下界拖到 1970, 整条时间轴作废。

    True/False 尤其阴: isinstance(True, int) 在 Python 里为真, 不显式挡掉的话
    ts=True 会被当成 1.0。
    """
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        rec.on_event({"type": "axis_pose", "ts": bad, "positions": {"axis_1z": 1.0}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()

    assert rec.status()["bad_ts"] == 1, "坏时间戳必须被计数并可见"
    cov = store.coverage()
    assert cov["t0"] is not None
    assert cov["t0"] > 1_000_000_000, f"块 t0 被污染成 {cov['t0']}"


def test_plausible_timestamps_are_kept_verbatim(store):
    rec = StateRecorder(store, chunk_seconds=5.0)
    rec.start()
    try:
        for i in range(5):
            rec.on_event({"type": "axis_pose", "ts": T0 + i * 0.02,
                          "positions": {"axis_1z": float(i)}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()
    assert rec.status()["bad_ts"] == 0
    assert store.coverage()["t0"] == pytest.approx(T0, abs=1e-3)


def test_bad_ts_does_not_corrupt_the_frame_column(store):
    """帧时间戳会被差分成 int32 毫秒; 一条 1970 的值与邻帧差 -1.8e12 ms 会整数溢出。"""
    rec = StateRecorder(store, chunk_seconds=1e9)
    rec.start()
    try:
        for i in range(3):
            rec.on_event({"type": "axis_pose", "ts": T0 + i * 0.02,
                          "positions": {"axis_1z": float(i)}})
        rec.on_event({"type": "axis_pose", "ts": 1, "positions": {"axis_1z": 99.0}})
        _drain(rec)
    finally:
        rec.stop()
    store.flush()
    for meta in store.chunks_in_range(T0 - 10, T0 + 100):
        chunk = decode_chunk(store.read_chunk(meta["path"]))
        stamps = chunk.streams["axis_pose"]["ts"]
        assert all(s > 1_000_000_000 for s in stamps), f"列里混进了坏时间戳: {stamps}"
        assert stamps == sorted(stamps), "时间戳应单调"


# -- 删除顺序与整理 ---------------------------------------------------

def test_drop_session_deletes_rows_before_files(store, monkeypatch):
    """先删文件再删行 = 崩在中间就留下一堆读了必 500 的孤儿行。顺序必须反过来。"""
    import shutil as _shutil

    session = store.start_session()
    store.append_chunk(session, 0, T0, T0 + 5, b"PTCDVR01x", 1)
    store.flush()

    def boom(*_a, **_k):
        raise OSError("模拟删目录时被占用")

    monkeypatch.setattr(_shutil, "rmtree", boom)
    with pytest.raises(OSError):
        store._drop_session(session.id, session.dir)

    assert store.chunks_in_range(T0, T0 + 10) == [], "行必须已经删干净, 不能留孤儿"
    assert store.list_sessions() == []


def test_reconcile_drops_sessions_whose_directory_vanished(store):
    import shutil as _shutil
    gone = store.start_session()
    store.append_chunk(gone, 0, T0, T0 + 5, b"x", 1)
    kept = store.start_session()
    store.append_chunk(kept, 0, T0 + 10, T0 + 15, b"y", 1)
    store.flush()
    _shutil.rmtree(store.root / gone.dir)          # 只删目录, 索引留着

    result = store.reconcile()
    assert result["sessions_dropped"] == 1
    assert [s["id"] for s in store.list_sessions()] == [kept.id]


def test_reconcile_drops_bad_timestamp_rows(store):
    session = store.start_session()
    store.append_chunk(session, 0, 1.0, 1.0, b"x", 0)        # 1970
    store.append_chunk(session, 1, T0, T0 + 5, b"y", 3)
    store.flush()
    assert store.coverage()["t0"] == 1.0

    result = store.reconcile()
    assert result["bad_ts_dropped"] == 1
    assert store.coverage()["t0"] == pytest.approx(T0)


def test_reconcile_closes_zombie_sessions_but_spares_the_active_one(store):
    zombie = store.start_session()
    store.append_chunk(zombie, 0, T0, T0 + 5, b"x", 1)
    active = store.start_session()
    store.append_chunk(active, 0, T0 + 10, T0 + 15, b"y", 1)
    store.flush()

    result = store.reconcile(active_session_id=active.id)
    assert result["sessions_closed"] == 1
    rows = {s["id"]: s for s in store.list_sessions()}
    assert rows[zombie.id]["ended_at"] == pytest.approx(T0 + 5)
    assert rows[active.id]["ended_at"] is None, "正在录的会话不能被收口"


def test_reconcile_deep_is_opt_in(store):
    session = store.start_session()
    store.append_chunk(session, 0, T0, T0 + 5, b"x", 1)
    store.flush()
    (store.root / store.chunks_in_range(T0, T0 + 10)[0]["path"]).unlink()

    assert store.reconcile(deep=False)["chunks_dropped"] == 0, "浅整理不该逐块 stat"
    assert store.reconcile(deep=True)["chunks_dropped"] == 1


def test_lowfreq_index_takes_incremental_events_only(store):
    """seek 重建派生态的唯一数据源。

    收录判据直接复用 _DROPPABLE: 需要重建派生态的事件, 与录制器承诺"一条都不许丢"
    的事件, 本来就是同一批。快照类(轴/机构/物料)由关键帧表达, 再存一份是纯浪费 ——
    按帧率算一天几百万条, 索引会比块本身还大。
    """
    rec = StateRecorder(store, chunk_seconds=1.0)
    session = rec.start()
    rec.on_event({"type": "axis_pose", "ts": T0, "positions": {"axis_1z": 1.0}})
    rec.on_event({"type": "telemetry", "ts": T0, "node": "plc.rail", "value": 3})
    rec.on_event({"type": "material_state", "ts": T0, "plates": []})
    rec.on_event({"type": "vm_node_enter", "ts": T0 + 0.5, "run_id": "R9",
                  "op": "call", "action": "plate_pick", "args": {"slot": 3}})
    _drain(rec)
    rec.stop()

    events, truncated = store.lowfreq_before(session.id, T0 + 10)
    assert truncated is False
    assert [e["type"] for e in events] == ["vm_node_enter"]
    # args 只在 enter 上出现, 是持握/转移推断的唯一来源, 必须原样带着
    assert events[0]["args"] == {"slot": 3}
    assert rec.status()["lowfreq_written"] == 1


def test_lowfreq_rows_die_with_their_session(store):
    """保留策略删会话时索引必须一起走, 否则留下指向空气的历史。"""
    rec = StateRecorder(store, chunk_seconds=1.0)
    session = rec.start()
    rec.on_event({"type": "operation_start", "ts": T0, "run_id": "R1", "operation": "x"})
    _drain(rec)
    rec.stop()
    assert store.lowfreq_before(session.id, T0 + 10)[0]

    store._drop_session(session.id, session.dir)
    assert store.lowfreq_before(session.id, T0 + 10)[0] == []
