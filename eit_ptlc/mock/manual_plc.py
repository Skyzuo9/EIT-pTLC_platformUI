"""Mock OPC UA: 单点控制 (PC Manual Mode) 容器树与 PLC 侧仿真
===========================================================
功能:
    在 mock/plc_server.build_mock_server 建好的树上, 按 manual_points.yaml 追加
    Host_Computer 之外的兄弟容器 (cyinder_date / servoaxisdate / GVL / IO / PLC_PCManual),
    并用一个 FSM 复刻 PLC 侧 POU `PLC_PCManual` 的行为 + 气缸/伺服的物理响应,
    使单点控制在 sim 模式下可全链路闭环 (无需真机)。

对应的 PLC 真源:
    Application/40_Man/PLC_PCManual        —— Active 判定 / 心跳看门狗 / 下降沿清扫
    Application/40_Man/PLC_Cyinder_气缸动作 —— FB_cylinder 单控二态 + 到位反馈
    Application/30_Ethercat任务/PLC_Servo_伺服/伺服调用 —— FB_SERVOAXIS 点动/回零/定位

说明:
    容器挂载层次与真机一致 (2026-07-28 连 192.168.0.50 实测): GVL 类容器挂在
    …/Application/GlobalVars 下, PROGRAM 实例 (PLC_PCManual) 挂在 …/Application/Programs 下。
    真机还有一层 mock 模拟不了的差异 —— 含中文的 BrowseName 是 GBK 字节被按 UTF-8 解码,
    由 driver._recover_browse_name 还原, 其单测在 tests/test_manual_points_config_offline.py。
"""

from __future__ import annotations

import asyncio
import logging

from asyncua import ua

from eit_ptlc.config.models import ManualPointMap
from eit_ptlc.driver.opcua_driver import _VARIANT_BY_NAME

log = logging.getLogger(__name__)

# servo 结构体成员 (与 PLC 的 TYPE servo 一致): 名 -> 类型名
SERVO_MEMBERS: dict[str, str] = {
    # PC→PLC 命令
    "xHome": "Boolean", "xJogPos": "Boolean", "xJogNeg": "Boolean", "xStop": "Boolean",
    "xMoveAbs": "Boolean", "xMoveRel": "Boolean", "XReset": "Boolean",
    "fAbsTarget": "Double", "fRelTarget": "Double", "fVelocity": "Double",
    "fAcc": "Double", "fDec": "Double", "fJogVel": "Double",
    # PLC→PC 反馈
    "bEnabled": "Boolean", "bHomed": "Boolean", "bBusy": "Boolean", "bError": "Boolean",
    "iErrorCode": "Int32", "fActPos": "Double", "fActVel": "Double",
    "bAbMoveDone": "Boolean", "bReMoveDone": "Boolean",
}

# PLC_PCManual 的拒绝码 (与 POU 内 PC_Manual_Reject 一致)
REJECT_NONE, REJECT_KEEPALIVE, REJECT_L2_BUSY = 0, 1, 2
REJECT_NOT_READY, REJECT_DEPLOY, REJECT_RUNNING = 3, 4, 5

_L2_PREFIXES = ("Sampling", "Collect", "Develop", "PhotoScrape",
                "FeedLift", "Pump", "Rail", "StagingA")
_MODE_RUNNING = 1


def _container_parent_path(manual_map: ManualPointMap, key: str) -> tuple[str, ...]:
    """mock 里某容器的父路径: PROGRAM 实例挂 root/Programs, GVL 挂 root/GlobalVars (与真机一致)."""
    if key == manual_map.host.get("container"):
        return manual_map.root + ("Programs",)
    return manual_map.root + ("GlobalVars",)


async def _ensure_object(server, path: tuple[str, ...]):
    """按路径逐级取/建对象节点, 复用 build_mock_server 记录的层级缓存."""
    levels: dict = server._eit_levels  # type: ignore[attr-defined]
    idx: int = server._eit_idx         # type: ignore[attr-defined]
    node = levels[()]
    for i, part in enumerate(path):
        key = tuple(path[: i + 1])
        if key not in levels:
            levels[key] = await node.add_object(idx, part)
        node = levels[key]
    return node


async def _add_var(server, parent, parent_path: tuple[str, ...], name: str, var_type: str):
    """在 parent 下建一个可写变量并登记到 _eit_manual_nodes (幂等: 同名只建一次)."""
    reg: dict = server._eit_manual_nodes  # type: ignore[attr-defined]
    key = parent_path + (name,)
    if key in reg:
        return reg[key]
    idx: int = server._eit_idx  # type: ignore[attr-defined]
    vtype = _VARIANT_BY_NAME[var_type]
    default = 0.0 if vtype == ua.VariantType.Double else (
        False if vtype == ua.VariantType.Boolean else 0)
    var = await parent.add_variable(idx, name, ua.Variant(default, vtype))
    await var.set_writable()
    reg[key] = var
    return var


async def build_manual_mock_tree(server, manual_map: ManualPointMap) -> None:
    """按点表在 mock 树上补齐单点控制需要的全部容器与变量.

    参数:
        server: build_mock_server 返回的服务器 (须已记录 _eit_idx / _eit_levels)
        manual_map: load_manual_points 的结果
    """
    server._eit_manual_nodes = {}  # type: ignore[attr-defined]  # 完整路径 -> 节点

    # 各容器的完整路径
    paths: dict[str, tuple[str, ...]] = {}
    for key, name in manual_map.containers.items():
        paths[key] = _container_parent_path(manual_map, key) + (name,)
        await _ensure_object(server, paths[key])

    # 握手变量 (PLC_PCManual PROGRAM 实例)
    host = manual_map.host
    hp = paths[host["container"]]
    hnode = server._eit_levels[hp]  # type: ignore[attr-defined]
    await _add_var(server, hnode, hp, host["enable"], "Boolean")
    await _add_var(server, hnode, hp, host["keepalive"], "Int32")
    await _add_var(server, hnode, hp, host["active"], "Boolean")
    if host.get("reject"):
        await _add_var(server, hnode, hp, host["reject"], "Int16")

    # 全局状态
    for ref in manual_map.globals_.values():
        cp = paths[ref.container]
        await _add_var(server, server._eit_levels[cp], cp, ref.name, ref.var_type)  # type: ignore[attr-defined]
    # 仿真一台旋钮打在自动档、处于停止态的机器 (2026-07-28 真机实测就是自动档)。
    # 档位关系到 FB_Mode 只在自动档接受启动, 默认给 FALSE 的话 PLCStart 永远不生效。
    auto = manual_map.globals_.get("manual_auto")
    if auto is not None:
        await manual_write(server, paths[auto.container] + (auto.name,), True)

    # 气缸: 手动 / 自动 / 两个到位反馈
    for cyl in manual_map.cylinders.values():
        for ref in (cyl.manual, cyl.auto_ro, cyl.fb_on, cyl.fb_off):
            if ref is None:
                continue
            cp = paths[ref.container]
            await _add_var(server, server._eit_levels[cp], cp, ref.name, ref.var_type)  # type: ignore[attr-defined]

    # 伺服轴: 每根轴一个 Object, 下挂 servo 结构体成员
    servo_path = paths["servo"]
    for axis in manual_map.axes.values():
        apath = servo_path + (axis.struct,)
        anode = await _ensure_object(server, apath)
        for member, var_type in SERVO_MEMBERS.items():
            await _add_var(server, anode, apath, member, var_type)
        # 仿真一台已使能已回零的轴
        await manual_write(server, apath + ("bEnabled",), True)
        await manual_write(server, apath + ("bHomed",), True)

    log.info("[MockPLC] 单点控制树已构建: %d 容器 / %d 节点",
             len(paths), len(server._eit_manual_nodes))  # type: ignore[attr-defined]


async def manual_read(server, path: tuple[str, ...]):
    """直接读 mock 单点节点 (供 FSM / 测试模拟 PLC 侧)."""
    return await server._eit_manual_nodes[path].read_value()  # type: ignore[attr-defined]


async def manual_write(server, path: tuple[str, ...], value) -> None:
    """直接写 mock 单点节点 (供 FSM / 测试模拟 PLC 侧)."""
    node = server._eit_manual_nodes[path]  # type: ignore[attr-defined]
    vtype = await node.read_data_type_as_variant_type()
    if vtype == ua.VariantType.Double:
        value = float(value)
    elif vtype == ua.VariantType.Boolean:
        value = bool(value)
    else:
        value = int(value)
    await node.write_value(ua.DataValue(ua.Variant(value, vtype)))


async def run_manual_fsm(
    server,
    stop_event: asyncio.Event,
    manual_map: ManualPointMap,
    node_map_read,
    node_map_write=None,
    *,
    tick: float = 0.05,
    keepalive_timeout: float = 3.0,
    feedback_delay: float = 0.2,
    init_delay: float = 0.6,
) -> None:
    """复刻 PLC 侧 PLC_PCManual + FB_cylinder + FB_SERVOAXIS + FB_Mode 的可观测行为.

    参数:
        server: mock 服务器
        stop_event: 置位后退出
        manual_map: 点表
        node_map_read: async (name) -> value, 读 Host_Computer 容器变量 (L2 状态 / PLC_Ready / PLCStop)
        node_map_write: async (name, value) -> None, 写 Host_Computer 变量; 省略则不模拟启停
        tick: 扫描周期; keepalive_timeout: 心跳判死时长; feedback_delay: 到位传感器响应延时
        init_delay: 模拟 FB_Mode 初始化态时长 (真机 3s, mock 缩短)
    说明:
        与真 PLC 的差异只在于时间粒度; 判定条件与清扫范围逐条对齐 POU 源码。
    """
    paths = {k: _container_parent_path(manual_map, k) + (v,)
             for k, v in manual_map.containers.items()}
    host = manual_map.host
    hp = paths[host["container"]]
    p_enable, p_alive = hp + (host["enable"],), hp + (host["keepalive"],)
    p_active = hp + (host["active"],)
    p_reject = hp + (host["reject"],) if host.get("reject") else None
    g = manual_map.globals_
    p_mode = paths[g["mode_state"].container] + (g["mode_state"].name,) if "mode_state" in g else None
    p_home = paths[g["one_key_home"].container] + (g["one_key_home"].name,) if "one_key_home" in g else None

    def ref_path(ref):
        return paths[ref.container] + (ref.name,)

    p_auto = (paths[manual_map.globals_["manual_auto"].container]
              + (manual_map.globals_["manual_auto"].name,)) if "manual_auto" in g else None

    last_alive = None
    alive_since = 0.0
    prev_active = False
    init_until = 0.0     # FB_Mode 初始化态的结束时刻 (0 = 不在初始化)
    # 气缸命令 -> 到位反馈的延时队列: path -> (生效时刻, 目标命令态)
    pending: dict[tuple[str, ...], tuple[float, bool]] = {}
    loop = asyncio.get_running_loop()

    while not stop_event.is_set():
        now = loop.time()
        try:
            enable = bool(await manual_read(server, p_enable))
            alive = int(await manual_read(server, p_alive))

            # 心跳看门狗: 只看值变没变 (回绕安全)
            if alive != last_alive:
                last_alive = alive
                alive_since = now
            ka_expired = enable and (now - alive_since) >= keepalive_timeout

            # 门条件
            l2_idle = True
            for prefix in _L2_PREFIXES:
                try:
                    if int(await node_map_read(f"{prefix}_L2_State")) == 10:
                        l2_idle = False
                        break
                except Exception:
                    pass
            try:
                plc_ready = bool(await node_map_read("PLC_Ready"))
            except Exception:
                plc_ready = True
            try:
                deploy = int(await node_map_read("PLC_Deploy_State"))
            except Exception:
                deploy = 0
            mode = int(await manual_read(server, p_mode)) if p_mode else 0

            # FB_Mode 子集: PLCStop/PLCStart 与柜面按钮并联驱动 MODE_State。
            # 启动须自动档 (FB_Mode 的 `ELSIF (bAuto AND xStart)`), 且要过一段初始化态。
            if node_map_write is not None and p_mode is not None:
                try:
                    if init_until and now >= init_until:
                        init_until = 0.0
                        mode = _MODE_RUNNING
                        await manual_write(server, p_mode, mode)
                    elif not init_until:
                        if bool(await node_map_read("PLCStop")) and mode == _MODE_RUNNING:
                            mode = 0
                            await manual_write(server, p_mode, mode)
                        elif bool(await node_map_read("PLCStart")) and mode == 0:
                            auto = bool(await manual_read(server, p_auto)) if p_auto else True
                            if auto:
                                init_until = now + init_delay
                                await manual_write(server, p_mode, 4)   # 初始化态
                                mode = 4
                except Exception as exc:
                    log.debug("[MockPLC] 启停仿真异常 (忽略): %s", exc)

            # 不含 MODE_State: 电子手动档下我们不写自动位, L2 派发器写什么都被 FB 忽略
            active = (enable and not ka_expired and l2_idle and plc_ready
                      and deploy in (0, 30))
            await manual_write(server, p_active, active)

            # 电子手动档: A00_设备状态显示及控制 里 xAutoMode := 手自动 AND NOT Active,
            # 经 FB_Mode 输出到 ManualAuto。mock 假定物理旋钮一直在自动档。
            if p_auto is not None:
                await manual_write(server, p_auto, not active)

            if p_reject is not None:
                if not enable:
                    reject = REJECT_NONE
                elif ka_expired:
                    reject = REJECT_KEEPALIVE
                elif not l2_idle:
                    reject = REJECT_L2_BUSY
                elif not plc_ready:
                    reject = REJECT_NOT_READY
                elif deploy not in (0, 30):
                    reject = REJECT_DEPLOY
                elif mode == _MODE_RUNNING:
                    reject = REJECT_RUNNING
                else:
                    reject = REJECT_NONE
                await manual_write(server, p_reject, reject)

            # Active 下降沿: 清扫全部执行器命令位与轴运动位 (对齐 POU 第 5 段)
            if prev_active and not active:
                for cyl in manual_map.cylinders.values():
                    await manual_write(server, ref_path(cyl.manual), False)   # 只清手动位
                for axis in manual_map.axes.values():
                    ap = paths["servo"] + (axis.struct,)
                    for m in ("xJogPos", "xJogNeg", "xMoveAbs", "xMoveRel", "xHome"):
                        await manual_write(server, ap + (m,), False)
                pending.clear()
            prev_active = active

            # 气缸物理响应: 复刻 FB_cylinder 的 `IF xManualAuto THEN 自动位 ELSE 手动位`。
            # active = 电子手动档 -> 吃手动位; 否则自动档 -> 吃自动位。
            for cyl in manual_map.cylinders.values():
                if active or cyl.auto_ro is None:
                    cmd = bool(await manual_read(server, ref_path(cyl.manual)))
                else:
                    cmd = bool(await manual_read(server, ref_path(cyl.auto_ro)))
                key = ref_path(cyl.manual)
                prev = pending.get(key)
                if prev is None or prev[1] != cmd:
                    pending[key] = (now + feedback_delay, cmd)
                elif now >= prev[0]:
                    if cyl.fb_on is not None:
                        await manual_write(server, ref_path(cyl.fb_on), cmd)
                    if cyl.fb_off is not None:
                        await manual_write(server, ref_path(cyl.fb_off), not cmd)

            # 伺服轴响应: jog 按 fJogVel 积分 fActPos; xHome/xMoveAbs 到位后置 Done
            for axis in manual_map.axes.values():
                ap = paths["servo"] + (axis.struct,)
                pos = float(await manual_read(server, ap + ("fActPos",)))
                jog_p = bool(await manual_read(server, ap + ("xJogPos",)))
                jog_n = bool(await manual_read(server, ap + ("xJogNeg",)))
                stop = bool(await manual_read(server, ap + ("xStop",)))
                home = bool(await manual_read(server, ap + ("xHome",)))
                mabs = bool(await manual_read(server, ap + ("xMoveAbs",)))
                busy = False
                if stop:
                    await manual_write(server, ap + ("fActVel",), 0.0)
                elif jog_p or jog_n:
                    # fJogVel 在真 PLC 里未接线 (常量), mock 用点表的 jog_vel_fixed 同构
                    vel = axis.jog_vel_fixed or 10.0
                    pos += vel * tick * (1 if jog_p else -1)
                    await manual_write(server, ap + ("fActPos",), pos)
                    await manual_write(server, ap + ("fActVel",), vel)
                    busy = True
                elif home:
                    await manual_write(server, ap + ("fActPos",), 0.0)
                    await manual_write(server, ap + ("bHomed",), True)
                    # 真 PLC 的 `伺服调用` 在回零完成时自清 xHome
                    await manual_write(server, ap + ("xHome",), False)
                elif mabs:
                    target = float(await manual_read(server, ap + ("fAbsTarget",)))
                    vel = float(await manual_read(server, ap + ("fVelocity",))) or 10.0
                    step = vel * tick
                    if abs(target - pos) <= step:
                        await manual_write(server, ap + ("fActPos",), target)
                        await manual_write(server, ap + ("bAbMoveDone",), True)
                    else:
                        pos += step if target > pos else -step
                        await manual_write(server, ap + ("fActPos",), pos)
                        busy = True
                else:
                    await manual_write(server, ap + ("bAbMoveDone",), False)
                    await manual_write(server, ap + ("fActVel",), 0.0)
                await manual_write(server, ap + ("bBusy",), busy)

            # 一键回原点: 触发后全轴归零并自清 (对齐 伺服一键回原点 的收尾条件)
            if p_home is not None and bool(await manual_read(server, p_home)):
                for axis in manual_map.axes.values():
                    ap = paths["servo"] + (axis.struct,)
                    await manual_write(server, ap + ("fActPos",), 0.0)
                    await manual_write(server, ap + ("bHomed",), True)
                await manual_write(server, p_home, False)

        except Exception as exc:  # mock 不应因单次异常整个停摆
            log.debug("[MockPLC] manual FSM 单轮异常 (忽略): %s", exc)

        await asyncio.sleep(tick)
