"""录制编解码器: 保真契约、块独立性与压缩率。

这里断言的"往返误差 <= (deadband + 0.5) * quantum"是回放精度的**契约**, 不是实现
细节 —— 三维回放能不能算 1:1, 就以它为准。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from eit_ptlc.runtime.recording.channels import spec_for, tolerance
from eit_ptlc.runtime.recording.codec import (
    CHUNK_MAGIC,
    ChunkBuilder,
    decode_chunk,
    is_missing,
    iter_frames,
)

AXES = ("axis_1z", "axis_3y", "axis_9x", "axis_11y")
T0 = 1786000000.0  # 绝对纪元秒 —— 前端 stampMs 按 <1e12 判秒, 必须落在真实纪元上


def _trapezoid(n: int, hz: float, seed: int, span: float = 400.0) -> np.ndarray:
    """停一段 → 平滑走一段的轴位置, 叠加编码器噪声。"""
    rng = np.random.default_rng(seed)
    out = np.zeros(n)
    pos = rng.uniform(0, span)
    i = 0
    while i < n:
        hold = int(rng.uniform(0.5, 4.0) * hz)
        out[i:i + hold] = pos
        i += hold
        if i >= n:
            break
        target = rng.uniform(0, span)
        steps = int(max(0.3, abs(target - pos) / 250.0) * hz)
        k = np.linspace(0, 1, max(steps, 2))
        seg = pos + (target - pos) * (3 * k**2 - 2 * k**3)
        m = max(0, min(len(seg), n - i))
        out[i:i + m] = seg[:m]
        i += len(seg)
        pos = target
    return out[:n] + rng.normal(0, 0.004, n)


def _build_axis_chunk(n=500, hz=50.0, seed=0):
    signals = {ax: _trapezoid(n, hz, seed + j) for j, ax in enumerate(AXES)}
    builder = ChunkBuilder(T0, keyframe={"mountedTool": 1})
    for i in range(n):
        builder.add_frame(
            "axis_pose",
            T0 + i / hz,
            {f"{ax}.position": float(signals[ax][i]) for ax in AXES},
        )
    return builder, signals


def test_axis_roundtrip_within_precision_contract():
    builder, signals = _build_axis_chunk()
    chunk = decode_chunk(builder.encode())
    spec = spec_for("axis_pose", "position")
    limit = tolerance(spec)
    assert limit == pytest.approx(0.025)

    for ax in AXES:
        got = np.array(chunk.streams["axis_pose"]["channels"][f"{ax}.position"])
        err = np.abs(got - signals[ax])
        assert err.max() <= limit, f"{ax} 最大误差 {err.max():.5f} 超出契约 {limit}"


def test_timestamps_are_absolute_epoch_seconds():
    """相对时间会被前端 stampMs 误判为纪元秒并乘 1000, 必须存绝对纪元秒。"""
    builder, _ = _build_axis_chunk(n=64)
    chunk = decode_chunk(builder.encode())
    stamps = chunk.streams["axis_pose"]["ts"]
    assert stamps[0] > 1e9, "时间戳必须是绝对纪元秒"
    assert all(s < 1e12 for s in stamps), "纪元秒不应落进毫秒量级"
    for i, ts in enumerate(stamps):
        assert ts == pytest.approx(T0 + i / 50.0, abs=1e-3)


def test_tri_state_confirmed_survives_roundtrip():
    """confirmed 的 None 是真实状态(运动途中), 压成 False 会把它错画成已到位。"""
    pattern = [True, False, None, True, None, False]
    builder = ChunkBuilder(T0)
    for i, value in enumerate(pattern):
        builder.add_frame("mechanism_state", T0 + i * 0.1,
                          {"dev_valve_1.confirmed": value,
                           "dev_valve_1.commanded": bool(i % 2),
                           "dev_valve_1.source": "feedback" if value is not None else "commanded"})
    chunk = decode_chunk(builder.encode())
    got = chunk.streams["mechanism_state"]["channels"]["dev_valve_1.confirmed"]
    assert got == pattern
    assert None in got and got.count(None) == 2

    src = chunk.streams["mechanism_state"]["channels"]["dev_valve_1.source"]
    assert src == ["feedback", "feedback", "commanded", "feedback", "commanded", "feedback"]


def test_missing_frames_are_distinct_from_none_value():
    """缺帧与 tri 的 None 必须可区分, 否则回放分不清'没数据'和'到位信号都不成立'。"""
    builder = ChunkBuilder(T0)
    builder.add_frame("mechanism_state", T0 + 0.0, {"a.confirmed": True})
    builder.add_frame("mechanism_state", T0 + 0.1, {"b.confirmed": None})
    builder.add_frame("mechanism_state", T0 + 0.2, {"a.confirmed": None, "b.confirmed": False})
    chunk = decode_chunk(builder.encode())
    col_a = chunk.streams["mechanism_state"]["channels"]["a.confirmed"]
    col_b = chunk.streams["mechanism_state"]["channels"]["b.confirmed"]

    assert col_a[0] is True
    assert is_missing(col_a[1]), "a 在第 2 帧没有数据"
    assert col_a[2] is None and not is_missing(col_a[2]), "第 3 帧是真实的 None 值"
    assert is_missing(col_b[0]), "b 在第 1 帧还没出现"
    assert col_b[1] is None and col_b[2] is False

    rows = list(iter_frames(chunk, "mechanism_state"))
    assert "b.confirmed" not in rows[0][1], "缺帧通道不应出现在该帧里"
    assert rows[1][1]["b.confirmed"] is None


def test_channel_appearing_mid_chunk_stays_frame_aligned():
    builder = ChunkBuilder(T0)
    for i in range(6):
        values = {"axis_1z.position": float(i)}
        if i >= 3:
            values["axis_9x.position"] = float(100 + i)
        builder.add_frame("axis_pose", T0 + i * 0.02, values)
    chunk = decode_chunk(builder.encode())
    late = chunk.streams["axis_pose"]["channels"]["axis_9x.position"]
    assert len(late) == 6
    assert all(is_missing(v) for v in late[:3])
    assert late[3] == pytest.approx(103.0, abs=0.025)


def test_unknown_channel_is_recorded_not_dropped():
    """通道目录会随工程演进; 白名单式设计会让新增通道静默消失, 事后无法补救。"""
    builder = ChunkBuilder(T0)
    builder.add_frame("axis_pose", T0, {"axis_99q.position": 12.5,
                                        "brand_new_thing": 7.25})
    chunk = decode_chunk(builder.encode())
    channels = chunk.streams["axis_pose"]["channels"]
    assert channels["axis_99q.position"][0] == pytest.approx(12.5, abs=0.025)
    assert channels["brand_new_thing"][0] == pytest.approx(7.25, abs=0.001)


def test_each_chunk_decodes_independently():
    """块必须自足: seek 只解一块, 不能依赖前序块。"""
    blobs = []
    for c in range(3):
        builder = ChunkBuilder(T0 + c * 10, keyframe={"chunk": c, "mountedTool": c})
        for i in range(50):
            builder.add_frame("axis_pose", T0 + c * 10 + i * 0.02,
                              {"axis_1z.position": float(c * 100 + i)})
        blobs.append(builder.encode())

    # 逆序解码, 中间跳过一块 —— 任何跨块状态残留都会在这里暴露
    for c in (2, 0, 1):
        chunk = decode_chunk(blobs[c])
        assert chunk.keyframe == {"chunk": c, "mountedTool": c}
        got = chunk.streams["axis_pose"]["channels"]["axis_1z.position"]
        assert got[0] == pytest.approx(c * 100.0, abs=0.025)
        assert got[-1] == pytest.approx(c * 100.0 + 49, abs=0.025)


def test_events_are_preserved_verbatim():
    """vm_node_enter 带 args 且 done 不带, 配对表是唯一来源 —— 一条都不能改。"""
    events = [
        {"type": "vm_node_enter", "run_id": "R1", "aid": "a1", "op": "call",
         "action": "robot.tool_action", "args": {"action": "gripper-close"}, "ts": T0},
        {"type": "scrape_state", "phase": "pass", "band_cm": [1.0, 2.0, 3.0, 4.5], "ts": T0 + 1},
        {"type": "vm_node_done", "run_id": "R1", "aid": "a1", "status": "DONE", "ts": T0 + 2},
    ]
    builder = ChunkBuilder(T0)
    for event in events:
        builder.add_event(event)
    chunk = decode_chunk(builder.encode())
    assert chunk.events == events


def test_magic_and_version_are_enforced():
    builder = ChunkBuilder(T0)
    builder.add_frame("axis_pose", T0, {"axis_1z.position": 1.0})
    blob = builder.encode()
    assert blob.startswith(CHUNK_MAGIC)
    with pytest.raises(ValueError, match="magic"):
        decode_chunk(b"NOPE" + blob[4:])


def test_empty_builder_is_detectable_and_encodes():
    builder = ChunkBuilder(T0)
    assert builder.is_empty()
    chunk = decode_chunk(builder.encode())
    assert chunk.streams == {} and chunk.events == []


def test_idle_machine_compresses_far_better_than_json():
    """静止 = 差分全 0。这一条守的是"编码方式才是杠杆"这个前提。"""
    import json

    n, hz = 500, 50.0
    builder = ChunkBuilder(T0)
    rows = []
    for i in range(n):
        row = {f"{ax}.position": 100.0 + 0.003 * math.sin(i * 0.7 + j)  # 纯编码器噪声
               for j, ax in enumerate(AXES)}
        rows.append(row)
        builder.add_frame("axis_pose", T0 + i / hz, row)
    encoded = len(builder.encode())
    as_json = len(json.dumps([{"ts": T0 + i / hz, **rows[i]} for i in range(n)]).encode())
    assert encoded * 20 < as_json, (
        f"静止机器应压到 JSON 的 5% 以内, 实际 {encoded} vs {as_json}"
    )


def test_moving_machine_still_compresses_and_stays_accurate():
    builder, signals = _build_axis_chunk(n=500, hz=50.0, seed=7)
    blob = builder.encode()
    raw_floats = 500 * len(AXES) * 8
    assert len(blob) < raw_floats, "编码后不应大于等量 float64 原始数据"
    chunk = decode_chunk(blob)
    limit = tolerance(spec_for("axis_pose", "position"))
    for ax in AXES:
        got = np.array(chunk.streams["axis_pose"]["channels"][f"{ax}.position"])
        assert np.abs(got - signals[ax]).max() <= limit


def test_storage_budget_for_full_machine_stays_in_range():
    """整机码率守门。

    编码链一旦退化 (死区失效 / 量化步长写错 / 忘了差分), 表现不是报错而是**悄悄变
    大几十倍**, 而录制本身照跑不误 —— 只有码率能发现。整机实测约 3.7 MB/h, 这里
    留 3 倍余量。
    """
    hz_axis, hz_robot, hz_mech = 20.0, 50.0, 10.0
    seconds = 10.0
    axes = [f"axis_{i}" for i in range(11)]
    mechs = [f"mech_{i}" for i in range(55)]
    signals = {ax: _trapezoid(int(seconds * hz_axis), hz_axis, i) for i, ax in enumerate(axes)}
    joints = [_trapezoid(int(seconds * hz_robot), hz_robot, 50 + i, 180) for i in range(6)]

    builder = ChunkBuilder(T0)
    for i in range(int(seconds * hz_axis)):
        builder.add_frame("axis_pose", T0 + i / hz_axis,
                          {f"{ax}.position": float(signals[ax][i]) for ax in axes})
    for i in range(int(seconds * hz_robot)):
        builder.add_frame("robot_pose", T0 + i / hz_robot,
                          {f"joint{k}": float(joints[k][i]) for k in range(6)})
    for i in range(int(seconds * hz_mech)):
        builder.add_frame("mechanism_state", T0 + i / hz_mech,
                          {f"{m}.commanded": bool((i // 30 + j) % 2)
                           for j, m in enumerate(mechs)})

    mb_per_hour = len(builder.encode()) / seconds * 3600 / 1e6
    assert mb_per_hour < 12.0, (
        f"整机码率 {mb_per_hour:.2f} MB/h 远超实测基线 (~3.7)，编码链可能已退化"
    )


def test_deadband_suppresses_encoder_jitter_when_stationary():
    """静止轴在量化边界上翻动会让回放里的轴不停抖 —— 死区是保真手段。"""
    rng = np.random.default_rng(3)
    n = 300
    truth = 123.456 + rng.normal(0, 0.004, n)
    builder = ChunkBuilder(T0)
    for i in range(n):
        builder.add_frame("axis_pose", T0 + i * 0.02, {"axis_1z.position": float(truth[i])})
    chunk = decode_chunk(builder.encode())
    got = np.array(chunk.streams["axis_pose"]["channels"]["axis_1z.position"])
    assert len(set(np.round(got, 6))) <= 2, "静止轴解码后不应有多个抖动台阶"
    assert np.abs(got - truth).max() <= tolerance(spec_for("axis_pose", "position"))
