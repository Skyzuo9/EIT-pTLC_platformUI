"""Collect / StagingA / Pump 三工位的动作表 (阶段③ D 步)
========================================================
功能:
    这三个工位没有 flat Target 轴, 动作全是"写气缸/阀 + 等到位反馈 + 计时相位",
    故可一次复刻完整。步序与互锁逐条来自编排说明书 (specs/*.yaml 的 notes)。

    PhotoScrape/Develop 的气缸类动作**刻意不在这里做**: 那两个工位还有轴序与
    排液 FSM, 半接线会把现有的 make_station_motion 轴运动掐掉 (dispatch 旁路
    motion 钩子), 留给各自工位整体落地时一起做。

真机不可见的量不模拟:
    泵总线内部量 (%MW1300 / 泵站位符 / %MX2005.5 / 大真空泵站位[]) 都不在
    plc_nodes.yaml 与 manual_points.yaml 里 —— 上位机看不见它们。泵的**可观测
    后果** (柱塞/阀位随真实 DT 指令积分) 已由 behavior/pump.py 模拟, 本模块只负责
    调用它并复刻其前后的阀位与计时相位。
"""

from __future__ import annotations

import logging

from eit_ptlc.mock.behavior.cylinders import make_cylinder_dispatcher, wait_feedback
from eit_ptlc.mock.plc_server import mock_read

log = logging.getLogger(__name__)

_L2_DONE, _L2_ERROR = 20, 40

#: Collect 的气缸类动作表 (逐条对应 specs/collect.yaml 的 notes)
#: ⚠ 命名不对称是真机事实: 输出叫"收集伸缩气缸自动", 反馈叫"收集平台推出气缸原点/动点"
#: (同一个气缸), 点表 id 统一为 col_extend。
_COLLECT_CYLINDERS = {
    21: [  # A21 夹持夹紧
        {"step": 0}, {"write": ("col_clamp", True)},
        {"step": 10}, {"wait": ("col_clamp", "fb_on")},
    ],
    41: [  # A41 复位伸出: 下压回原点 -> 升降回原点 -> 伸缩伸出
        {"step": 0}, {"write": ("col_press", False)},
        {"step": 5}, {"wait": ("col_press", "fb_off")}, {"write": ("col_lift", False)},
        {"step": 10}, {"wait": ("col_lift", "fb_off")}, {"write": ("col_extend", True)},
        {"step": 20}, {"wait": ("col_extend", "fb_on")},
    ],
    42: [  # A42 伸缩缩回
        {"step": 0}, {"write": ("col_extend", False)},
        {"step": 10}, {"wait": ("col_extend", "fb_off")},
    ],
    43: [  # A43 松夹持
        {"step": 0}, {"write": ("col_clamp", False)},
        {"step": 10}, {"wait": ("col_clamp", "fb_off")},
    ],
}

#: 收集平台瓶子有无传感器 (%IX8.1): TRUE = 有瓶
_IX8_BOTTLE_BIT = 1


def make_collect_dispatcher(server, spec, *, manual_map, manual_paths, clock,
                            stop_event, set_step, pump_hook):
    """构造 Collect 工位的动作行为.

    参数:
        spec: StationSpec (specs/collect.yaml); pump_hook: async (code) -> None
            (behavior/pump.make_pump_hook 的产物; 泵段仍由它按真实 DT 串积分)
        其余同 make_cylinder_dispatcher
    返回:
        async (code) -> (term, error_code, safe_state)
    """
    constants = spec.constants
    drain_s = float(constants["a30_drain_s"])
    settle_s = float(constants["a30_settle_s"])

    async def _bottle_present() -> bool:
        """读收集平台瓶子有无传感器 (由 sensors 合成层按座位账推导)."""
        ix8 = int(await mock_read(server, "IX8") or 0)
        return bool(ix8 >> _IX8_BOTTLE_BIT & 1)

    async def _extend() -> tuple:
        """A22 伸缩伸出: 互锁 = 推出到原点 且 **无瓶**; 不满足则冻结 (真机无错误码)."""
        await set_step(0)
        while not stop_event.is_set():
            at_home = await wait_feedback(server, manual_map, manual_paths,
                                          "col_extend", "fb_off", clock, stop_event)
            if at_home and not await _bottle_present():
                break
            # 互锁不成立就停在 step 0 —— 与 ST 一致: 无错误码无 PLC 超时,
            # 由上位机绝对超时兜底。沙盒不自造 PLC 没有的错误分支。
            await clock.sleep(0.05)
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        await write_cylinder(server, manual_map, manual_paths, "col_extend", True)
        await set_step(10)
        await wait_feedback(server, manual_map, manual_paths, "col_extend", "fb_on",
                            clock, stop_event)
        return (_L2_DONE, 0, 10)

    async def _lift_press() -> tuple:
        """A23 缩回升降下压: 缩回到位那一刻判瓶 —— 缺瓶报 201 (真机同码)."""
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        await set_step(0)
        await write_cylinder(server, manual_map, manual_paths, "col_extend", False)
        await set_step(10)
        await wait_feedback(server, manual_map, manual_paths, "col_extend", "fb_off",
                            clock, stop_event)
        # 判瓶时机: 缩回未到位前不判 (ST 明写), 到位那一扫描才看传感器
        if not await _bottle_present():
            return (_L2_ERROR, 201, 90)
        await write_cylinder(server, manual_map, manual_paths, "col_lift", True)
        await set_step(20)
        await wait_feedback(server, manual_map, manual_paths, "col_lift", "fb_on",
                            clock, stop_event)
        # 下压置位即 DONE, **不等下压到位** (该气缸无动点传感器, 见 spec notes)
        await write_cylinder(server, manual_map, manual_paths, "col_press", True)
        return (_L2_DONE, 0, 10)

    async def _init() -> tuple:
        """A10 初始化: 清执行件 + 泵初始化串 + 等四个原点."""
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        await set_step(0)
        for mech_id in ("col_press", "col_clamp", "col_lift", "col_extend",
                        "col_fill", "col_drain"):
            try:
                await write_cylinder(server, manual_map, manual_paths, mech_id, False)
            except KeyError:
                log.debug("[沙盒·Collect] 点表无 %s, 跳过清零", mech_id)
        await set_step(10)
        await pump_hook(10)          # 泵初始化串 (真实 DT, 由虚拟泵积分)
        await set_step(20)
        for mech_id in ("col_press", "col_clamp", "col_lift", "col_extend"):
            await wait_feedback(server, manual_map, manual_paths, mech_id, "fb_off",
                                clock, stop_event)
        return (_L2_DONE, 0, 10)

    async def _collect() -> tuple:
        """A30 收集: [开进液+泵段] -> 关进液/开排液+正压 -> 排液 20s -> 沉淀 5s, ×count."""
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        count = int(await mock_read(server, "collect_count") or 1)
        for _ in range(max(1, count)):
            await set_step(0)
            await write_cylinder(server, manual_map, manual_paths, "col_fill", True)
            await set_step(10)
            await pump_hook(30)      # 进液: 真实 DT 串由虚拟泵积分
            await set_step(20)
            await write_cylinder(server, manual_map, manual_paths, "col_fill", False)
            await write_cylinder(server, manual_map, manual_paths, "col_drain", True)
            await set_step(30)
            await clock.sleep(drain_s)          # 排液 20 秒 (吃时间倍率)
            await clock.sleep(settle_s)         # 沉淀 5 秒
            await set_step(40)
        await write_cylinder(server, manual_map, manual_paths, "col_drain", False)
        return (_L2_DONE, 0, 10)

    async def _bottle_locator() -> tuple:
        """A24 (遗留通道): 写溶液收集瓶定位气缸目标态, 同扫描 DONE, 不读反馈."""
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        target = bool(await mock_read(server, "Collect_BottleLocate_Target"))
        try:
            await write_cylinder(server, manual_map, manual_paths,
                                 "col_bottle_locator", target)
        except KeyError:
            log.debug("[沙盒·Collect] 点表无 col_bottle_locator, 只走握手")
        return (_L2_DONE, 0, 10)

    return make_cylinder_dispatcher(
        server, spec, _COLLECT_CYLINDERS, manual_map=manual_map,
        manual_paths=manual_paths, clock=clock, stop_event=stop_event,
        set_step=set_step,
        extra={10: _init, 22: _extend, 23: _lift_press, 24: _bottle_locator,
               30: _collect})


def make_staging_a_dispatcher(server, spec, *, manual_map, manual_paths, clock,
                              stop_event, set_step):
    """构造 StagingA 工位 (两个定位气缸, 写完即 DONE 不读反馈).

    ⚠ 该工位的派发器与其它工位不同构 (平铺 IF 链, 有 BUSY 101/DUPLICATE 102,
    未知码是 103, Reset 产 INTERRUPTED+402) —— 那些差异在握手层, 由 run_l2_fsm
    统一承担; 本层只负责两个动作的物理效果与段号。
    """
    async def _locator(mech_id: str, target_node: str, code: int):
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        phases = {item["phase"]: item["step"] for item in spec.action(code).steps}
        await set_step(phases.get("accepted", 1))
        await set_step(phases.get("write_output", code))
        target = bool(await mock_read(server, target_node))
        try:
            await write_cylinder(server, manual_map, manual_paths, mech_id, target)
        except KeyError:
            log.debug("[沙盒·StagingA] 点表无 %s, 只走握手", mech_id)
        await set_step(phases.get("done", 99))
        return (_L2_DONE, 0, 10)

    async def dispatch(code: int):
        if code == 24:
            return await _locator("sta_powder_locator", "StagingA_LocatorA_Target", 24)
        if code == 25:
            return await _locator("col_bottle_locator", "StagingA_LocatorB_Target", 25)
        return (30, spec.unknown_code_error, 0)

    return dispatch


def make_pump_dispatcher(server, spec, *, manual_map, manual_paths, vacuum_slots):
    """构造 Pump 工位 (真空泵开关).

    真机写的是 大真空泵站位[11] 引用计数槽, 由 PLC_Pump_泵管理 每扫描聚合成线圈。
    那个数组不在 OPC 面上, 故沙盒用一个内存槽位集合表达同一语义, 并把聚合结果
    写到点表里的 pump_vacuum 机构上 (那个是上位机看得见的)。

    参数:
        vacuum_slots: set, 沙盒内的引用计数槽 (跨动作延续)
    """
    slot = int(spec.constants["vacuum_slot_index"])

    async def _apply() -> None:
        """聚合槽位 -> 真空泵机构 (与 PLC_Pump_泵管理 的 OR 逻辑同)."""
        from eit_ptlc.mock.behavior.cylinders import write_cylinder
        try:
            await write_cylinder(server, manual_map, manual_paths, "pump_vacuum",
                                 bool(vacuum_slots))
        except KeyError:
            log.debug("[沙盒·Pump] 点表无 pump_vacuum, 只记槽位")

    async def dispatch(code: int):
        if code == 10:
            vacuum_slots.add(slot)
            await _apply()
            return (_L2_DONE, 0, 10)
        if code == 20:
            vacuum_slots.discard(slot)
            await _apply()
            return (_L2_DONE, 0, 10)
        return (30, spec.unknown_code_error, 0)

    return dispatch
