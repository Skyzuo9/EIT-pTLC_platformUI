"""L2 动作的轴连续运动 (阶段③: 瞬移 → 匀速积分)。

原则 —— **零编造数据**:
    目标位仍取上位机真实下推的 *_Target (与瞬移同源);
    速度取 manual_points.yaml 各轴 vel_max (定位速度限幅, 真实配置值);
    没有 flat Target 的轴 (行程烧在 PLC 里的 FeedLift 等) 本层不动 ——
    那要等编排说明书从 CODESYS 源码提取, 宁缺毋假。

接线: run_l2_fsm 的 motion 回调 —— 接受动作后、写 DONE 前, 在 RUNNING 态里
把各 (Target→ActPos) 对匀速推进到位, 期间递增 {prefix}_L2_Step 喂停滞看门狗。
struct fActPos 由 sim_stack 的 flat→struct 链任务随动, axis_pose 因此是连续曲线。
"""

from __future__ import annotations

import asyncio
import logging

from eit_ptlc.mock.plc_server import mock_read, mock_write

log = logging.getLogger(__name__)

_TICK_S = 0.05          # 名义积分步长 (真实等待 = tick / clock.rate)
_ARRIVE_EPS = 1e-6


async def ramp_node(server, node: str, target: float, speed_mm_s: float, clock,
                    stop_event, *, aliases: tuple[str, ...] = (),
                    on_tick=None) -> None:
    """把 flat 位置节点从当前值匀速推进到 target (mm), 别名节点每拍同写。"""
    pos = float(await mock_read(server, node))
    speed = max(float(speed_mm_s), 1e-6)
    while abs(target - pos) > _ARRIVE_EPS and not stop_event.is_set():
        await clock.sleep(_TICK_S)
        step = speed * _TICK_S
        if abs(target - pos) <= step:
            pos = target
        else:
            pos += step if target > pos else -step
        await mock_write(server, node, pos)
        for alias in aliases:
            await mock_write(server, alias, pos)
        if on_tick is not None:
            await on_tick()


def _group_pairs(pairs: tuple[tuple[str, str], ...]) -> list[tuple[str, list[str]]]:
    """按 Target 源分组 (同源多目的 = 别名对, 只积分一次)。"""
    grouped: dict[str, list[str]] = {}
    for src, dst in pairs:
        grouped.setdefault(src, []).append(dst)
    return list(grouped.items())


def make_station_motion(server, prefix: str, pairs, speed_of, clock, stop_event):
    """构造某工位的 L2 运动回调。

    参数:
        pairs: 该工位的 (Target 源, ActPos 目的) 对表 (sim_axes.TELEPORT_MIRRORS)
        speed_of: (act_pos_node) -> mm/s (取 manual_points vel_max; 取不到给保守值)
    返回:
        async (code) -> None; 逐组匀速推进, Step 随之递增
    """
    grouped = _group_pairs(tuple(pairs))

    async def motion(code: int) -> None:
        step_state = {"n": 0}

        async def bump_step() -> None:
            step_state["n"] += 1
            await mock_write(server, f"{prefix}_L2_Step", min(step_state["n"], 80))

        for src, dsts in grouped:
            try:
                target = float(await mock_read(server, src))
            except Exception:
                continue
            primary = dsts[0]
            try:
                await ramp_node(server, primary, target, speed_of(primary), clock,
                                stop_event, aliases=tuple(dsts[1:]), on_tick=bump_step)
            except Exception:
                log.debug("[SimMotion] %s %s 推进异常", prefix, primary, exc_info=True)

    return motion


def make_rail_motion(server, speed_of, clock, stop_event):
    """Rail 工位的运动回调: 目标 = Rail_Pos_Target[Rail_Target_Position-1] (数组索引)。"""

    async def motion(code: int) -> None:
        try:
            slot = int(await mock_read(server, "Rail_Target_Position"))
            targets = await mock_read(server, "Rail_Pos_Target")
        except Exception:
            return
        if not (isinstance(targets, (list, tuple)) and 1 <= slot <= len(targets)):
            return
        step_state = {"n": 0}

        async def bump_step() -> None:
            step_state["n"] += 1
            await mock_write(server, "Rail_L2_Step", min(step_state["n"], 80))

        try:
            await ramp_node(server, "Rail_ActPos", float(targets[slot - 1]),
                            speed_of("Rail_ActPos"), clock, stop_event, on_tick=bump_step)
            await mock_write(server, "Rail_Homed", True)
        except Exception:
            log.debug("[SimMotion] Rail 推进异常", exc_info=True)

    return motion
