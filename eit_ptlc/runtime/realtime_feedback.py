"""PTLC 数字孪生只读高频反馈发布器。"""

from __future__ import annotations

import asyncio
import logging
import math
import time

log = logging.getLogger(__name__)


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _advance(deadline: float, interval: float, now: float) -> float:
    """按固定频率推进截止时刻。

    从**上一个截止时刻**递推而非从"本轮采完"起算 —— 后者是固定延迟, 会把每轮
    OPC 批读耗时永久累加进周期 (实际周期 = interval + 采样耗时), 因此配置的
    20Hz/10Hz 现场只跑到 15.5Hz/7.8Hz。

    落后一个周期以上时对齐到下一个整节拍, 丢弃已经错过的节拍而不是补采 ——
    保持本模块"慢采样周期直接跳过, 不创建积压任务"的既有语义。
    """
    deadline += interval
    if deadline <= now:
        missed = math.floor((now - deadline) / interval) + 1
        deadline += missed * interval
        if deadline <= now:
            # (now - deadline) / interval 落在整数上时浮点会向下取整少算一拍,
            # 使返回值恰好等于 now、下一轮立刻再触发一次。兜一拍保证严格大于 now。
            deadline += interval
    return deadline


async def realtime_feedback_loop(
    manual,
    bus,
    stop: asyncio.Event,
    *,
    axis_interval: float = 0.05,
    mechanism_interval: float = 0.10,
    signal_heartbeat: float = 1.0,
    robot_states=None,
) -> None:
    """发布 11 轴与 51 机构快照；慢采样周期直接跳过，不创建积压任务。

    三色灯输出位随机构快照采集(snapshot["signals"]), 但按"变化即发 + 心跳"发布
    signal_light: 灯态每小时才变几次, 10Hz 重复帧是纯噪声; 心跳兼作新连接的
    初始播种(首帧 ≤ signal_heartbeat)与前端 staleness 时钟(3 个心跳丢失转灰)。

    robot_states: 可选的同步快照函数(RobotController.mechanism_snapshot), 返回机器人
    末端执行器(rob_grip_plate96/rob_grip_vial/rob_flip_suction)的机构状态 dict, 与
    PLC 机构合并进**同一个** mechanism_state 事件 —— 前端 MechanismStateStore 按 id
    合并快照, 双发布者会互相顶掉, 必须单源. 该函数必须轻量无阻塞(不得持机器人动作锁)。
    """
    if axis_interval <= 0 or mechanism_interval <= 0:
        raise ValueError("实时反馈周期必须为正数")
    loop = asyncio.get_running_loop()
    next_axis = loop.time()
    next_mechanism = loop.time()
    axis_seq = 0
    mechanism_seq = 0
    signal_seq = 0
    last_signal: tuple | None = None
    last_signal_at = 0.0
    log.info(
        "[realtime] 启动: axis=%.1fHz mechanism=%.1fHz",
        1.0 / axis_interval,
        1.0 / mechanism_interval,
    )

    while not stop.is_set():
        now = loop.time()
        axis_due = now >= next_axis
        mechanism_due = now >= next_mechanism
        if not axis_due and not mechanism_due:
            timeout = max(0.0, min(next_axis, next_mechanism) - now)
            try:
                await asyncio.wait_for(stop.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            continue

        try:
            snapshot = await manual.realtime_snapshot(
                include_axes=axis_due,
                include_mechanisms=mechanism_due,
            )
            captured_at = time.time()
            if axis_due:
                axes = snapshot.get("axes") or {}
                positions = {}
                velocities = {}
                for key, value in axes.items():
                    position = _finite(value.get("position"))
                    velocity = _finite(value.get("velocity"))
                    if position is not None:
                        positions[key] = position
                    if velocity is not None:
                        velocities[key] = velocity
                if positions:
                    axis_seq += 1
                    bus.publish({
                        "type": "axis_pose",
                        "positions": positions,
                        "velocities": velocities,
                        "ts": captured_at,
                        "seq": axis_seq,
                    })
            if mechanism_due:
                states = dict(snapshot.get("mechanisms") or {})
                if robot_states is not None:
                    try:
                        states.update(robot_states() or {})
                    except Exception:
                        # 末端执行器快照失败只影响本轮, 不得杀掉整个反馈循环
                        log.exception("[realtime] 机器人末端执行器快照失败")
                if states:
                    mechanism_seq += 1
                    bus.publish({
                        "type": "mechanism_state",
                        "states": states,
                        "ts": captured_at,
                        "seq": mechanism_seq,
                    })
                signals = snapshot.get("signals")
                if signals:
                    key = (
                        signals.get("red"),
                        signals.get("yellow"),
                        signals.get("green"),
                        signals.get("buzzer"),
                        signals.get("flash"),
                        signals.get("mode"),
                    )
                    if key != last_signal or loop.time() - last_signal_at >= signal_heartbeat:
                        signal_seq += 1
                        bus.publish({
                            "type": "signal_light",
                            **signals,
                            "ts": captured_at,
                            "seq": signal_seq,
                        })
                        last_signal = key
                        last_signal_at = loop.time()
        except Exception:
            # OPC UA 断线或慢周期只影响本轮；不并发补采、不让后台任务永久退出。
            log.exception("[realtime] 只读采样失败")
        finally:
            finished = loop.time()
            if axis_due:
                next_axis = _advance(next_axis, axis_interval, finished)
            if mechanism_due:
                next_mechanism = _advance(next_mechanism, mechanism_interval, finished)

    log.info("[realtime] 退出")
