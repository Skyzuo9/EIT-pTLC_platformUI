"""气缸类 L2 动作的虚拟 PLC 行为 (阶段③)
=========================================
功能:
    把"写气缸自动位 + 等到位反馈"这类动作做成一张**声明式动作表**:
    每个动作 = 若干步, 每步 = (写哪个气缸成什么态) 与 (等哪个反馈)。
    步序与等待条件逐条来自编排说明书 (specs/*.yaml 的 notes), 不在此处发明。

    物理响应**不重写**: manual_plc.run_manual_fsm 早已复刻 FB_cylinder ——
    命令位变化 0.2 秒后翻到位反馈, 且非会话态吃 auto_ro 自动位。阶段③做的只是
    "终于有人写 auto_ro 了"。

不设超时是刻意的:
    真 PLC 的这些气缸等待**没有错误分支** (spec 里 errors 多为空): 不到位就冻结在
    该步, 由上位机的停滞看门狗判。沙盒照做 —— 自造一个 PLC 没有的超时码, 会让
    演练出来的处置动作在真机上对不上。故障注入用 server._eit_cylinder_stuck。
"""

from __future__ import annotations

import logging

from eit_ptlc.mock.manual_plc import manual_read, manual_write

log = logging.getLogger(__name__)

_L2_DONE, _L2_ERROR = 20, 40
_TICK_S = 0.05


async def write_cylinder(server, manual_map, manual_paths, mech_id: str,
                         value: bool) -> None:
    """写某气缸的自动位 (与 SimStack._write_cylinder 同口径: 自动位优先).

    参数:
        server: Mock OPC 服务器; manual_map: 单点点表; manual_paths: 容器路径表
        mech_id: 点表里的气缸 id (如 col_clamp); value: 目标态
    返回:
        None
    Raises:
        KeyError: 点表无该气缸 (调用方转 REJECTED)
    """
    cylinder = manual_map.cylinders[mech_id]
    ref = cylinder.auto_ro or cylinder.manual
    await manual_write(server, manual_paths[ref.container] + (ref.name,), value)


async def read_feedback(server, manual_map, manual_paths, mech_id: str,
                        which: str):
    """读某气缸的到位反馈 (which: fb_on 动点 / fb_off 原点); 该口悬空回 None."""
    cylinder = manual_map.cylinders.get(mech_id)
    ref = getattr(cylinder, which, None) if cylinder is not None else None
    if ref is None:
        return None
    try:
        return bool(await manual_read(server, manual_paths[ref.container] + (ref.name,)))
    except Exception:
        return None


async def valve_state(server, manual_map, manual_paths, mech_id: str):
    """某阀/气缸此刻的开合态; 点位不存在或读不到时 **None**.

    参数:
        mech_id: 点表机构 id
    返回:
        bool | None —— None 表示"无从判定", 由调用方决定该默认成什么

    判据的次序是 到位反馈 -> 命令位: 多数电磁阀没有到位传感器, 退到命令位与真机的
    可观测面一致 (上位机对这类阀本来也只知道自己发了什么)。**不在这里替调用方兜底**
    —— 展缸走空判据把"无从判定"当成"排液在跑"(与真机默认注液后抽吸的编排一致),
    而液量积分必须把它当成"没在排"(否则没接阀的缸会凭空漏光), 两个默认相反。
    """
    cylinder = manual_map.cylinders.get(mech_id) if manual_map else None
    if cylinder is None:
        return None
    state = await read_feedback(server, manual_map, manual_paths, mech_id, "fb_on")
    if state is not None:
        return bool(state)
    ref = cylinder.auto_ro or cylinder.manual
    try:
        return bool(await manual_read(server, manual_paths[ref.container] + (ref.name,)))
    except Exception:
        return None


async def wait_feedback(server, manual_map, manual_paths, mech_id: str, which: str,
                        clock, stop_event, *, on_tick=None) -> bool:
    """等某气缸的到位反馈成立.

    **刻意不设超时**: 真 PLC 这些等待没有错误分支, 不到位就冻结 (见模块头)。
    返回 False 只发生在沙盒停机时。
    """
    while not stop_event.is_set():
        # 该口悬空 (真机没接这个到位传感器) 时视同已到位 —— 与 PLC 的
        # "反馈=命令回声" 同语义, 不能在此凭空等一个永不到来的信号
        state = await read_feedback(server, manual_map, manual_paths, mech_id, which)
        if state is None or state:
            return True
        if on_tick is not None:
            await on_tick()
        await clock.sleep(_TICK_S)
    return False


def make_cylinder_dispatcher(server, spec, table, *, manual_map, manual_paths,
                             clock, stop_event, set_step, extra=None):
    """构造某工位的气缸类动作行为.

    参数:
        spec: StationSpec; table: {动作码: [步, ...]}, 步的形状见下
        set_step: async (段号) -> None (写 {prefix}_L2_Step)
        extra: {动作码: async () -> (term, err, safe)}, 非气缸类动作的自定义实现
    步的形状 (声明式, 与 spec.notes 逐条对应):
        {"write": (气缸 id, 目标态)}          写自动位
        {"wait": (气缸 id, "fb_on"|"fb_off")} 等到位反馈
        {"step": 段号}                        写段号
        {"guard": async () -> int | None}     互锁; 返回错误码即 ERROR, None 继续
    返回:
        async (code) -> (term, error_code, safe_state)
    """
    extra = extra or {}

    async def _run_steps(steps: list) -> tuple:
        for item in steps:
            if "step" in item:
                await set_step(item["step"])
            if "guard" in item:
                error_code = await item["guard"]()
                if error_code is not None:
                    return (_L2_ERROR, int(error_code), 90)
            if "write" in item:
                mech_id, value = item["write"]
                if mech_id in getattr(server, "_eit_cylinder_stuck", ()):
                    # 故障注入: 命令发出但气缸不动 -> 后续 wait 永不成立 (卡死演练)
                    log.info("[沙盒·气缸] %s 被注入卡死, 命令不生效", mech_id)
                    continue
                await write_cylinder(server, manual_map, manual_paths, mech_id, value)
            if "wait" in item:
                mech_id, which = item["wait"]
                ok = await wait_feedback(server, manual_map, manual_paths,
                                         mech_id, which, clock, stop_event)
                if not ok:
                    return (_L2_ERROR, 500, 90)
        return (_L2_DONE, 0, 10)

    async def dispatch(code: int) -> tuple:
        """按动作码派发; 未登记码回 REJECTED (与真派发器的 ELSE 分支同)."""
        if code not in spec.accepts:
            return (30, spec.unknown_code_error, 0)
        if code in extra:
            return await extra[code]()
        steps = table.get(code)
        if steps is None:
            # 该码在 accepts 里但本层没实现 (如泵类/轴类): 交回调用方兜底
            return None
        return await _run_steps(steps)

    return dispatch
