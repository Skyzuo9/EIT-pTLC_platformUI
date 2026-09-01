"""设备活动度: 一块录像里有几个工位在动。

时间轴上那条密度条原先画的是**块字节数** —— "机器动得越多差分越大, 块就越大"听着
成立, 实际上连续录制下字节数近似常量(高频噪声占了大头), 于是整条是一样高的噪声,
看图的人得不到任何信息。这里换成真正的问题: **那十秒里有几个工位在动**。

判据不新造。"动没动"直接用编解码器自己的死区容差 (channels.tolerance()):

    编码器噪声实测 ±0.004 mm, 轴位置死区 2 步 x 0.01 mm -> 容差 0.025 mm

死区之内的抖动本来就被编码器当成"没动"丢掉了, 再用别的阈值判一遍只会得到两套互相
矛盾的说法。同一个数, 一处定义。

工位映射同样不新建: manual_points.yaml 已经把 62 个气缸与轴按工位分好组(单点控制页
用的就是它), ManualCylinder.station / ManualAxis.station 直接可读。机器人及其末端
执行器归 robot。合计 **9 个模块**, 与三维页左上角 HUD 的工位清单同源。
"""

from __future__ import annotations

import logging
from pathlib import Path

from eit_ptlc.runtime.recording.channels import spec_for, tolerance
from eit_ptlc.runtime.recording.codec import is_missing

log = logging.getLogger(__name__)

# 机器人自成一个模块。它的末端执行器 (rob_grip_plate96 / rob_grip_vial /
# rob_flip_suction) 由 RobotController 发布, 不在 PLC 点表里, 按前缀归到机器人。
ROBOT_STATION = "robot"
_ROBOT_PREFIX = "rob_"

# 轴位置 / 关节角的"动了"判据, 与编解码器的死区同源
_AXIS_TOL = tolerance(spec_for("axis_pose", "position"))
_JOINT_TOL = tolerance(spec_for("robot_pose", "joint"))


def load_station_map(manual_points_file: Path | str) -> dict[str, str]:
    """从单点控制点表读出 {机构或轴 id: 工位 key}。

    参数:
        manual_points_file: manual_points.yaml 路径
    返回:
        dict[str, str], 例如 {"col_lift": "collect", "axis_11y": "rail"}
    """
    from eit_ptlc.config.loader import load_manual_points

    point_map = load_manual_points(Path(manual_points_file))
    out: dict[str, str] = {}
    for mech_id, cylinder in point_map.cylinders.items():
        out[str(mech_id)] = str(cylinder.station)
    for axis_id, axis in point_map.axes.items():
        out[str(axis_id)] = str(axis.station)
    return out


def _station_of(entity_id: str, station_map: dict[str, str]) -> str | None:
    """实体 id -> 工位; 认不出来的返回 None 由调用方计数上墙。"""
    hit = station_map.get(entity_id)
    if hit is not None:
        return hit
    if entity_id.startswith(_ROBOT_PREFIX):
        return ROBOT_STATION
    return None


def _split(channel_key: str) -> tuple[str, str]:
    """把 "col_lift.commanded" 拆成 ("col_lift", "commanded")。"""
    dot = channel_key.rfind(".")
    if dot < 0:
        return channel_key, ""
    return channel_key[:dot], channel_key[dot + 1:]


def _spread_exceeds(values, limit: float) -> bool:
    """列内极差是否超过容差 (缺帧与非数值一律跳过)。"""
    lo = None
    hi = None
    for value in values:
        if is_missing(value) or isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        if lo is None or value < lo:
            lo = value
        if hi is None or value > hi:
            hi = value
    if lo is None or hi is None:
        return False
    return (hi - lo) > limit


def _changed(values) -> bool:
    """列内出现过不同的值 (布尔/枚举类通道用它); 缺帧不算变化。"""
    seen = None
    started = False
    for value in values:
        if is_missing(value):
            continue
        if not started:
            seen = value
            started = True
        elif value != seen:
            return True
    return False


def chunk_activity(streams: dict, station_map: dict[str, str]) -> tuple[list[str], list[str]]:
    """一块录像里"在动"的工位集合。

    入参形状同时适配两条路径, 因此录制侧与补算侧共用这一个实现, 判据不会各飘各的:
        ChunkBuilder 侧      {流: {通道: [值]}}   (编码前的原值)
        decode_chunk 侧      chunk.streams[流]["channels"]  (解码后的值)

    判据:
        axis_pose        某轴 position 块内极差 > 0.025 mm  -> 该轴所属工位
        robot_pose       任一 joint 块内极差 > 0.0055 deg   -> robot
        mechanism_state  commanded 变过 / confirmed 出现过 None (两个到位信号都不
                         成立 = 正在途中) / moving 为真      -> 该机构所属工位

    参数:
        streams: {流名: {通道名: [值, ...]}}
        station_map: load_station_map 的结果
    返回:
        (工位 key 升序列表, 认不出工位的实体 id 升序列表)
    """
    active: set[str] = set()
    unmapped: set[str] = set()

    for key, values in (streams.get("axis_pose") or {}).items():
        entity, field = _split(key)
        if field != "position" or not _spread_exceeds(values, _AXIS_TOL):
            continue
        station = _station_of(entity, station_map)
        if station is None:
            unmapped.add(entity)
        else:
            active.add(station)

    for key, values in (streams.get("robot_pose") or {}).items():
        if key.startswith("joint") and _spread_exceeds(values, _JOINT_TOL):
            active.add(ROBOT_STATION)
            break

    for key, values in (streams.get("mechanism_state") or {}).items():
        entity, field = _split(key)
        moving = False
        if field == "commanded":
            moving = _changed(values)
        elif field == "confirmed":
            # 判据是**变过**, 不是"出现过 None"。None 确实表示"两个到位信号都不成立",
            # 但相当一部分机构压根没接到位传感器 (rob_flip_suction 实测 confirmed 恒为
            # None、source 恒为 commanded), 用"出现过 None"会让它们 24 小时都算在动 ——
            # 那正是这条利用率条想取代的那种假象。真的一次行程是 True -> None -> False,
            # 必然变; 而气缸行程约 1 秒、块 10 秒, 不会出现整块都夹在途中的情况。
            moving = _changed(values)
        elif field == "moving":
            moving = any(v is True for v in values)
        if not moving:
            continue
        station = _station_of(entity, station_map)
        if station is None:
            unmapped.add(entity)
        else:
            active.add(station)

    return sorted(active), sorted(unmapped)
