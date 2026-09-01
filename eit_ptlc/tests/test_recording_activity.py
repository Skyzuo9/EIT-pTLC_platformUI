"""设备活动度: "那十秒里有几个工位在动"的判据。

这一组守的是时间轴上那条利用率条的可信度。判据错了不会报任何错, 只会让人对着一段
其实很忙(或其实很闲)的时间得出相反结论 —— 而这正是回放最常被用来回答的问题。
"""

from __future__ import annotations

from pathlib import Path

from eit_ptlc.runtime.recording.activity import chunk_activity, load_station_map
from eit_ptlc.runtime.recording.codec import ChunkBuilder, decode_chunk

_POINTS = Path(__file__).resolve().parents[1] / "config" / "manual_points.yaml"


def _map() -> dict[str, str]:
    return load_station_map(_POINTS)


def test_station_map_covers_every_plc_mechanism_and_axis():
    """映射不新建, 直接读单点控制点表 —— 单点控制页用的就是它。"""
    station_map = _map()
    assert station_map["col_lift"] == "collect"
    assert station_map["axis_11y"] == "rail"
    assert station_map["dev_t1_cyl1"] == "develop"
    assert station_map["axis_9x"] == "photoscrape"
    # 8 个 PLC 工位 + 机器人 = 9 个模块, 与三维页左上角 HUD 的工位清单同源
    assert len(set(station_map.values())) == 8


def test_axis_jitter_inside_the_deadband_is_not_movement():
    """编码器噪声实测 ±0.004 mm; 轴位置容差 0.025 mm。

    死区之内的抖动本来就被编码器当成"没动"丢掉了。这里若用另一个阈值, 就会出现
    "条上说在动, 回放里那根轴一动不动"的自相矛盾。
    """
    streams = {"axis_pose": {"axis_9x.position": [100.0, 100.01, 99.995, 100.02]}}
    assert chunk_activity(streams, _map()) == ([], [])


def test_axis_beyond_the_deadband_counts_its_station():
    streams = {"axis_pose": {"axis_9x.position": [100.0, 100.5, 101.0]}}
    assert chunk_activity(streams, _map()) == (["photoscrape"], [])


def test_velocity_column_does_not_count_by_itself():
    """只认位置: 速度列噪声更大且死区更宽, 拿它判会把停着的轴判成在动。"""
    streams = {"axis_pose": {"axis_9x.position": [100.0, 100.0],
                             "axis_9x.velocity": [0.0, 30.0]}}
    assert chunk_activity(streams, _map()) == ([], [])


def test_confirmed_leaving_a_limit_switch_means_in_transit():
    """True -> None = 离开到位点, 正在行程中。"""
    streams = {"mechanism_state": {"col_lift.confirmed": [True, None, None]}}
    assert chunk_activity(streams, _map()) == (["collect"], [])


def test_permanently_none_confirmed_is_not_motion():
    """没接到位传感器的机构 confirmed 恒为 None, 不能因此判它 24 小时都在动。

    真机实测 rob_flip_suction 的 confirmed 恒 None、source 恒 commanded。早先按
    "出现过 None"判在途, 结果 28.4 小时的录像里机器人有 79/120 个桶算在动 —— 而那
    一夜机器根本没开。这正是这条利用率条想取代的那种假象, 判据必须是**变过**。
    """
    streams = {"mechanism_state": {
        "rob_flip_suction.confirmed": [None] * 8,
        "rob_flip_suction.commanded": [False] * 8,
        "rob_flip_suction.source": ["commanded"] * 8,
    }}
    assert chunk_activity(streams, _map()) == ([], [])


def test_settled_cylinder_is_idle():
    streams = {"mechanism_state": {"col_lift.confirmed": [True, True],
                                   "col_lift.commanded": [True, True]}}
    assert chunk_activity(streams, _map()) == ([], [])


def test_commanded_flip_counts_even_without_feedback():
    """PLC 有几个口悬空(没接到位传感器), 只能靠指令位翻转判它动过。"""
    streams = {"mechanism_state": {"col_press.commanded": [False, False, True]}}
    assert chunk_activity(streams, _map()) == (["collect"], [])


def test_robot_joints_count_as_one_module():
    """六个关节一起动也只是"机器人在动"一个模块, 不该按关节数灌水。"""
    streams = {"robot_pose": {f"joint{i}": [0.0, 5.0] for i in range(6)}}
    assert chunk_activity(streams, _map()) == (["robot"], [])


def test_robot_end_effectors_belong_to_the_robot():
    """rob_* 由 RobotController 发布, 不在 PLC 点表里, 按前缀归机器人。"""
    streams = {"mechanism_state": {"rob_flip_suction.moving": [False, True]}}
    assert chunk_activity(streams, _map()) == (["robot"], [])


def test_unknown_mechanism_is_reported_not_swallowed():
    """工程演进会新增机构。悄悄漏计等于让利用率条长期偏低而没人知道。"""
    streams = {"mechanism_state": {"brand_new_valve.confirmed": [True, None]}}
    active, unmapped = chunk_activity(streams, _map())
    assert active == [] and unmapped == ["brand_new_valve"]


def test_missing_frames_are_not_movement():
    """通道中途才出现时前面补的是缺帧标记, 不能被当成一次值变化。"""
    builder = ChunkBuilder(1786000000.0)
    builder.add_frame("mechanism_state", 1786000000.0, {"col_press.commanded": True})
    builder.add_frame("mechanism_state", 1786000000.5,
                      {"col_press.commanded": True, "col_lift.commanded": True})
    assert chunk_activity(builder.columns(), _map()) == ([], [])


def test_builder_and_decoded_chunk_agree():
    """录制侧从原值算、补算侧从解码值算, 两条路必须给同一个答案。

    这正是 ChunkBuilder.columns() 与 decode_chunk 保持同一形状的理由 —— 两处各写
    一遍判据必然会飘, 而飘了以后"补算过的段"和"新录的段"会画出两种高度。
    """
    t0 = 1786000000.0
    builder = ChunkBuilder(t0, keyframe={})
    for i in range(20):
        builder.add_frame("axis_pose", t0 + i * 0.05, {"axis_11y.position": 200.0 + i * 0.4})
        builder.add_frame("mechanism_state", t0 + i * 0.05,
                          {"col_lift.confirmed": None if i > 5 else True})
    from_builder = chunk_activity(builder.columns(), _map())

    chunk = decode_chunk(builder.encode())
    decoded = {stream: data["channels"] for stream, data in chunk.streams.items()}
    assert chunk_activity(decoded, _map()) == from_builder
    assert from_builder[0] == ["collect", "rail"]
