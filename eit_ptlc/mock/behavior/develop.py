"""Develop 工位的虚拟 PLC 行为 (阶段③ E 步)
============================================
功能:
    复刻展缸工位里"上位机能看见后果"的那部分工序:
      31/32 放板缸回原点/到动点 (按 Expand_Group/Expand_Number 选缸, 等到位反馈);
      26    抽吸四相 (沉降 -> 等废液走空 -> 吹扫 -> 收尾), 含 402 硬上限;
      10/20/21/22 初始化与注液/润洗/上液的阀位与泵段。
    50/51 排液**不在此处**: 它早有独立后台 FSM (plc_server.run_tank_drain_fsm) 与桥,
    本模块把这两个码原样交回派发器的既有路径 (返回 None 表示"本层不管")。

    时长常量分两类, 与真机同源:
      ST 里写死的 (a20/a21/a22 的首查延时与静置) 从 spec.constants 取;
      经 OPC 通道下发的 (Tank_Suction_Settle_S 等四个) **运行时活读节点** ——
      那才是真源, 落进 spec 会让"改通道值不生效"。

废液走空判据:
    Expand_Waste_Empty_G1/G2 是真机上位机可见的镜像量 (PLC_Pump_泵管理 每扫描写)。
    沙盒里由本模块按"排液已开且过了一段时间"推导 —— 那是抽吸这件事的物理后果,
    不是凭空的定时器: 没开排液阀就永远走不空, 与真机一致。
"""

from __future__ import annotations

import logging

from eit_ptlc.mock.behavior.cylinders import valve_state, wait_feedback, write_cylinder
from eit_ptlc.mock.plc_server import mock_read, mock_write

log = logging.getLogger(__name__)

_L2_DONE, _L2_REJECTED, _L2_ERROR = 20, 30, 40
_TICK_S = 0.05

#: 抽吸四相的时长通道 (LREAL 秒; PLC 侧初值 3/10/30/120 是通道写不进时的兜底)
_SUCTION_NODES = {
    "settle": "Tank_Suction_Settle_S",
    "empty": "Tank_Suction_Empty_S",
    "blow": "Tank_Suction_Blow_S",
    "cap": "Tank_Suction_Cap_S",
}


def _cylinder_id(group: int, number: int) -> str:
    """按组号与缸号拼点表 id (dev_t{组}_cyl{号})."""
    return f"dev_t{int(group)}_cyl{int(number)}"


def make_develop_dispatcher(server, spec, *, manual_map, manual_paths, clock,
                            stop_event, set_step, pump_hook):
    """构造 Develop 工位的动作行为.

    参数:
        spec: StationSpec (specs/develop.yaml); pump_hook: async (code) -> None
        其余同 behavior/cylinders
    返回:
        async (code) -> (term, error_code, safe_state) | None
        返回 None 表示"本层不处理该码", 调用方 (sim_stack 的组合器) 走既有路径。
    """
    constants = spec.constants

    async def _tank_context() -> tuple:
        """读当前目标缸并推导组号/缸号 (真 PLC 由 Target_Tank 推导这两个量)."""
        tank = int(await mock_read(server, "Expand_Target_Tank") or 1)
        group = (tank - 1) // 4 + 1
        number = (tank - 1) % 4 + 1
        return tank, group, number

    async def _read_seconds(key: str, fallback: float) -> float:
        """活读时长通道 (真源在通道上, 不落 spec —— 否则改通道值不生效)."""
        try:
            value = float(await mock_read(server, _SUCTION_NODES[key]))
        except Exception:
            return fallback
        return value if value > 0 else fallback

    async def _plate_cylinder(target: bool) -> tuple:
        """A31/A32: 按组号缸号写放板缸自动位并等到位反馈 (无错误码, 不到位即冻结)."""
        _, group, number = await _tank_context()
        mech_id = _cylinder_id(group, number)
        try:
            await write_cylinder(server, manual_map, manual_paths, mech_id, target)
        except KeyError:
            log.warning("[沙盒·Develop] 点表无 %s, 只走握手", mech_id)
            return (_L2_DONE, 0, 10)
        which = "fb_on" if target else "fb_off"
        await wait_feedback(server, manual_map, manual_paths, mech_id, which,
                            clock, stop_event)
        return (_L2_DONE, 0, 10)

    async def _set_waste_empty(group: int, value: bool) -> None:
        """写该组的废液走空镜像量 (上位机可见, A26 与排液共用此电平)."""
        try:
            await mock_write(server, f"Expand_Waste_Empty_G{int(group)}", bool(value))
        except Exception:
            log.debug("[沙盒·Develop] 废液镜像量写失败", exc_info=True)

    async def _suction() -> tuple:
        """A26 抽吸四相: 沉降 -> 等走空 (cap 上限, 超时 402) -> 吹扫 -> 关阀.

        ⚠ 402 的最早触发时刻是 max(settle, cap) 而非裸 cap: ST 里 cap 看门狗与沉降
        同起点并行计时, 但判定嵌在"沉降期满"之后 (spec notes 点过这条, desc 未提)。
        """
        _, group, number = await _tank_context()
        settle_s = await _read_seconds("settle", 3.0)
        empty_s = await _read_seconds("empty", 10.0)
        blow_s = await _read_seconds("blow", 30.0)
        cap_s = await _read_seconds("cap", 120.0)

        # 相位 0: 沉降 (期满前什么都不评估)
        await clock.sleep(settle_s)

        # 相位 0 续: 等废液走空判据连续满足 empty_s
        # 沙盒的物理推导: 排液阀开着才会走空 (没开阀就永远走不空, 与真机一致);
        # 注入 server._eit_drain_wet_groups 可让某组永不走空 (故障演练)
        drain_on = await _drain_valve_open(group, number)
        wet_groups = getattr(server, "_eit_drain_wet_groups", set())
        elapsed = 0.0
        satisfied = 0.0
        while satisfied < empty_s:
            if stop_event.is_set():
                return (_L2_ERROR, 402, 90)
            if elapsed >= cap_s:
                await _set_waste_empty(group, False)
                return (_L2_ERROR, 402, 90)
            await clock.sleep(_TICK_S)
            elapsed += _TICK_S
            empty_now = drain_on and group not in wet_groups
            satisfied = satisfied + _TICK_S if empty_now else 0.0
            await _set_waste_empty(group, empty_now)

        # 相位 10: 关进液 + 开吹气, 吹扫 blow_s 后关排液与吹气
        await _write_valve(group, number, "fill", False)
        await _write_valve(group, number, "blow", True)
        await clock.sleep(blow_s)
        await _write_valve(group, number, "drain", False)
        await _write_valve(group, number, "blow", False)
        await _set_waste_empty(group, False)
        return (_L2_DONE, 0, 10)

    async def _write_valve(group: int, number: int, kind: str, value: bool) -> None:
        """写某缸的阀 (进液/排液/吹气); 点表无该阀则跳过 (只写上位机看得见的)."""
        mech_id = f"dev_t{int(group)}_{kind}{int(number)}"
        try:
            await write_cylinder(server, manual_map, manual_paths, mech_id, value)
        except KeyError:
            log.debug("[沙盒·Develop] 点表无 %s, 跳过", mech_id)

    async def _drain_valve_open(group: int, number: int) -> bool:
        """该缸的排液阀此刻是否开着 (走空判据的物理前提)."""
        state = await valve_state(server, manual_map, manual_paths,
                                  f"dev_t{int(group)}_drain{int(number)}")
        # 无从判定 -> 按"排液在跑"处理 (与真机默认注液后抽吸的编排一致)。
        # ⚠ 液量积分那边的默认与此相反, 理由见 cylinders.valve_state 的注释。
        return True if state is None else bool(state)

    async def _liquid_action(code: int) -> tuple:
        """A20/A21/A22: 阀位 + 泵段 + 静置 (泵仍由既有 hook 按真实 DT 串积分)."""
        _, group, number = await _tank_context()
        if code == 21:
            # 润洗: 进液+排液+气缸自动全开, 保持到退出 (供随后的抽吸承接)
            for kind in ("fill", "drain", "blow"):
                await _write_valve(group, number, kind, kind != "blow")
            repeat = int(await mock_read(server, "Expand_rinse_count") or 1)
            settle_key = "a21_settle_after_pump_s"
        elif code == 22:
            await _write_valve(group, number, "fill", True)
            repeat = int(await mock_read(server, "Expand_up_liquid_count") or 1)
            settle_key = None
        else:                                    # code 20: 清洗管路, 不开阀
            repeat = 1
            settle_key = "a20_settle_after_pump_s"

        for _ in range(max(1, repeat)):
            await pump_hook(code)
        if settle_key is not None:
            await clock.sleep(float(constants[settle_key]))
        if code == 22:
            await _write_valve(group, number, "fill", False)
        return (_L2_DONE, 0, 10)

    async def _init() -> tuple:
        """A10: 清所选缸的气缸与三阀, 再发泵初始化串."""
        _, group, number = await _tank_context()
        try:
            await write_cylinder(server, manual_map, manual_paths,
                                 _cylinder_id(group, number), False)
        except KeyError:
            pass
        for kind in ("fill", "drain", "blow"):
            await _write_valve(group, number, kind, False)
        await pump_hook(10)
        return (_L2_DONE, 0, 10)

    async def dispatch(code: int):
        """按动作码派发; 50/51 交回既有排液桥 (返回 None)."""
        if code in (50, 51):
            return None
        if code not in spec.accepts:
            return (_L2_REJECTED, spec.unknown_code_error, 0)
        tank = int(await mock_read(server, "Expand_Target_Tank") or 0)
        if not 1 <= tank <= 8:
            # 与真派发器一致: 缸号越界 102 (拒绝, 可重试)
            return (_L2_REJECTED, 102, 0)
        if code == 10:
            return await _init()
        if code in (20, 21, 22):
            return await _liquid_action(code)
        if code == 26:
            return await _suction()
        if code == 31:
            return await _plate_cylinder(False)
        if code == 32:
            return await _plate_cylinder(True)
        return (_L2_REJECTED, spec.unknown_code_error, 0)

    return dispatch
