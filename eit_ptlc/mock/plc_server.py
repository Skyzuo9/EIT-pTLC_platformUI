"""Mock OPC UA PLC 服务器
=========================
功能:
    按 PlcNodeMap 构建同构的 Host_Computer 节点树 (跨命名空间路径 + 全部变量),
    供 opcua_driver 离线读写/心跳/急停测试. P4 在此基础上叠加 L2 动作 FSM 与故障注入.
    迁移并简化自 UI-Upper/mock/plc_server.py.

使用方式:
    server = await build_mock_server("opc.tcp://127.0.0.1:48400/", node_map)
    async with server:
        ...  # 客户端连接读写

说明:
    所有变量按节点表类型创建为可写; 标量给类型默认值, 数组给定长默认值.
"""

from __future__ import annotations

import logging

from asyncua import Server, ua

from eit_ptlc.config.models import PlcNodeMap
from eit_ptlc.driver.opcua_driver import _INT_VARIANTS, _VARIANT_BY_NAME

log = logging.getLogger(__name__)


def _default_for(vtype: ua.VariantType):
    """返回某 VariantType 的标量默认值."""
    if vtype in (ua.VariantType.Float, ua.VariantType.Double):
        return 0.0
    if vtype in _INT_VARIANTS:
        return 0
    if vtype == ua.VariantType.Boolean:
        return False
    if vtype == ua.VariantType.String:
        return ""
    return 0


def _mock_initial_value(name: str, vtype: ua.VariantType, array_len: int):
    """返回节点的仿真初值；启动诊断默认模拟一台已经正常就绪的 PLC。"""
    if name == "PLC_Startup_State":
        return 60
    if name == "PLC_Ready":
        return True
    if name == "PLC_Axis_CommOperational" and array_len > 0:
        return [True] * array_len
    scalar = _default_for(vtype)
    return [scalar] * array_len if array_len > 0 else scalar


async def build_mock_server(url: str, node_map: PlcNodeMap, namespace: str = "eit_ptlc_mock") -> Server:
    """构建并初始化 Mock OPC UA 服务器 (未启动; 用 async with 启动).

    功能:
        创建 gvl_path 嵌套对象树, 并按 node_map 在末级容器下创建全部可写变量.
    参数:
        url: 监听地址; node_map: PLC 节点表; namespace: 命名空间名
    返回:
        已 init 的 asyncua.Server (调用方负责 async with 启动)
    """
    server = Server()
    await server.init()
    server.set_endpoint(url)
    idx = await server.register_namespace(namespace)

    # 构建 gvl_path 嵌套对象树 (BrowseName 文本与 driver.resolve_gvl_node 对齐)
    # 逐层记录 路径 -> 节点: 单点控制 mock (mock/manual_plc.py) 要在 Application /
    # GlobalVars 这些中间层下挂兄弟容器 (cyinder_date / servoaxisdate / PLC_PCManual ...)
    levels: dict[tuple[str, ...], object] = {(): server.nodes.objects}
    parent = server.nodes.objects
    for i, part in enumerate(node_map.gvl_path):
        parent = await parent.add_object(idx, part)
        levels[tuple(node_map.gvl_path[: i + 1])] = parent
    gvl = parent
    server._eit_idx = idx          # type: ignore[attr-defined]  # 命名空间索引 (建兄弟容器用)
    server._eit_levels = levels    # type: ignore[attr-defined]  # 路径元组 -> 对象节点

    # 按节点表创建全部变量 (可写); 同时保留节点引用与类型供 FSM/测试直接读写
    nodes: dict[str, object] = {}
    types: dict[str, ua.VariantType] = {}
    for name, spec in node_map.nodes.items():
        vtype = _VARIANT_BY_NAME[spec.var_type]
        value = ua.Variant(_mock_initial_value(name, vtype, spec.array_len), vtype)
        var = await gvl.add_variable(idx, name, value)
        await var.set_writable()
        nodes[name] = var
        types[name] = vtype

    server._eit_nodes = nodes      # type: ignore[attr-defined]  # name -> 节点对象
    server._eit_types = types      # type: ignore[attr-defined]  # name -> VariantType
    log.info("[MockPLC] 已构建 %d 个节点于 %s", len(node_map.nodes), "/".join(node_map.gvl_path))
    return server


async def mock_read(server, name: str):
    """从 Mock 服务器直接读取一个变量 (供测试/FSM 模拟 PLC 侧)."""
    return await server._eit_nodes[name].read_value()  # type: ignore[attr-defined]


async def mock_write(server, name: str, value) -> None:
    """向 Mock 服务器直接写入一个变量 (带类型, 供测试/FSM 模拟 PLC 侧)."""
    vtype = server._eit_types[name]  # type: ignore[attr-defined]
    await server._eit_nodes[name].write_value(ua.DataValue(ua.Variant(value, vtype)))  # type: ignore[attr-defined]


# 下载安全握手状态码（与 PLC_Deploy_State 协议一致）
_DEPLOY_IDLE, _DEPLOY_PREPARING, _DEPLOY_SAFE, _DEPLOY_COMMITTED = 0, 10, 20, 25
_DEPLOY_REJECTED, _DEPLOY_ERROR = 30, 40


async def run_deploy_fsm(
    server,
    stop_event: "asyncio.Event",
    *,
    tick: float = 0.02,
    prepare_ticks: int = 2,
) -> None:
    """模拟完整下载前的安全握手及关键失败分支。

    契约与真 PLC 保持一致：

    * Start 上升沿只在 IDLE 接受；任一 L2 正在 RUNNING 时以状态 30 拒绝；
    * 接受后至少停留一个 PREPARING 扫描周期，再进入 SAFE_TO_DOWNLOAD；
    * PREPARING 期间任一轴通信丢失，以状态 40 / 错误 5 失败；
    * State=20 时 Host 写入与 AcceptedSeq 相同的 CommitSeq 后进入 25=COMMITTED；
      该状态忽略普通 HMI 取消，安全不变量丢失时留在 25 并锁存错误，只有明确
      未下载后按 ``CommitSeq=0 → Start=FALSE → Reset`` 才能退出，关闭最终复核与
      worker 调用之间的竞态。

    Mock 没有 ``MC_Power.Status`` 节点，因此用 ``prepare_ticks`` 模拟受控撤销使能
    所需的扫描周期；它不是一拍直达，测试可以可靠观察 PREPARING 状态。
    """
    import asyncio

    prev_start = False
    preparing_ticks = 0
    while not stop_event.is_set():
        try:
            reset = bool(await mock_read(server, "PLC_Deploy_Reset"))
            start = bool(await mock_read(server, "PLC_Deploy_Start"))
            commit_seq = int(await mock_read(server, "PLC_Deploy_CommitSeq"))
            state = int(await mock_read(server, "PLC_Deploy_State"))
            if reset and not start and commit_seq == 0:
                await mock_write(server, "PLC_Deploy_State", _DEPLOY_IDLE)
                await mock_write(server, "PLC_Deploy_ErrorCode", 0)
            elif start and not prev_start and state == _DEPLOY_IDLE:
                seq = int(await mock_read(server, "PLC_Deploy_RequestSeq"))
                await mock_write(server, "PLC_Deploy_AcceptedSeq", seq)
                l2_states = await asyncio.gather(*(
                    mock_read(server, f"{prefix}_L2_State")
                    for prefix in (
                        "Sampling", "Collect", "Develop", "PhotoScrape",
                        "FeedLift", "Pump", "Rail", "StagingA",
                    )
                ))
                l2_busy = any(int(value) == _L2_RUNNING for value in l2_states)
                if l2_busy:
                    await mock_write(server, "PLC_Deploy_State", _DEPLOY_REJECTED)
                    await mock_write(server, "PLC_Deploy_ErrorCode", 1)
                elif not bool(await mock_read(server, "PLC_Ready")):
                    await mock_write(server, "PLC_Deploy_State", _DEPLOY_ERROR)
                    await mock_write(server, "PLC_Deploy_ErrorCode", 5)
                else:
                    preparing_ticks = 0
                    await mock_write(server, "PLC_Deploy_ErrorCode", 0)
                    await mock_write(server, "PLC_Deploy_State", _DEPLOY_PREPARING)
            elif state == _DEPLOY_PREPARING:
                comm = list(await mock_read(server, "PLC_Axis_CommOperational"))
                if len(comm) != 11 or not all(bool(value) for value in comm):
                    await mock_write(server, "PLC_Deploy_State", _DEPLOY_ERROR)
                    await mock_write(server, "PLC_Deploy_ErrorCode", 5)
                else:
                    preparing_ticks += 1
                    if preparing_ticks >= max(1, int(prepare_ticks)):
                        await mock_write(server, "PLC_Deploy_State", _DEPLOY_SAFE)
            elif state == _DEPLOY_SAFE and start:
                accepted_seq = int(await mock_read(server, "PLC_Deploy_AcceptedSeq"))
                if commit_seq != 0 and commit_seq == accepted_seq:
                    await mock_write(server, "PLC_Deploy_State", _DEPLOY_COMMITTED)
            elif state == _DEPLOY_COMMITTED:
                comm = list(await mock_read(server, "PLC_Axis_CommOperational"))
                if len(comm) != 11 or not all(bool(value) for value in comm):
                    # COMMITTED is fail-closed: never fall into an ordinary error
                    # state that HMI can reset and thereby re-enable motion.
                    await mock_write(server, "PLC_Deploy_ErrorCode", 5)
            prev_start = start
        except Exception:
            log.debug("[MockPLC] Deploy FSM tick 异常", exc_info=True)
        await asyncio.sleep(tick)


# L2 状态码 (与 controller.plc_controller.PLCActionState 一致)
_L2_IDLE, _L2_RUNNING, _L2_DONE, _L2_REJECTED, _L2_ERROR, _L2_INTERRUPTED = 0, 10, 20, 30, 40, 50
_L2_TERMINAL = {_L2_DONE, _L2_REJECTED, _L2_ERROR, _L2_INTERRUPTED}


async def run_l2_fsm(
    server,
    prefix: str,
    stop_event: "asyncio.Event",
    *,
    tick: float = 0.02,
    reject_codes: tuple[int, ...] = (),
    error_codes: tuple[int, ...] = (),
    hang_codes: tuple[int, ...] = (),
    slow_ticks: int = 0,
    mirror_on_done: tuple[tuple[str, str], ...] = (),
    develop_tank_semantics: bool = False,
    on_done=None,
    motion=None,
    dispatch=None,
) -> None:
    """模拟某工位 L2 动作状态机 (供离线验证 plc_controller).

    功能:
        监视 {prefix}_L2_Start 上升沿: IDLE 时接受动作 (写 AcceptedSeq/ActiveCode/State=RUNNING),
        随即根据动作码决定终态 (DONE / REJECTED / ERROR), 写 CompletedSeq 与终态;
        Start 下降沿且处于终态时回到 IDLE.
    参数:
        prefix: L2 变量前缀 (如 Sampling); reject_codes/error_codes: 注入拒绝/故障的动作码集合;
        hang_codes: 接受后停在 RUNNING 永不终态且不推进 Step (模拟卡死, 供看门狗判停);
        slow_ticks: 非拒绝/故障/卡死的动作, 接受后逐拍推进 Step (模拟慢但有进度的长动作),
                    持续 slow_ticks 拍后再写终态 (验证: 只要有进度就不被停滞看门狗误判)
        mirror_on_done: 动作正常 DONE 后, 把 (src→dst) 节点值逐对复制 (模拟 PLC 运动到位:
                    *_ActPos := *_Target), 供按孔推送链路离线核对.
        develop_tank_semantics: True 时 code 50/51 走 develop 排液语义桥 (_develop_drain_bridge),
                    与真 PLC Develop_L2 派发器同契约 (spec 2026-07-14); 其余码不受影响.
        on_done: async (code) -> None; 正常 DONE 后回调 (仿真沙盒用: 表达静态镜像对写不了的
                    到位语义, 如 Rail_ActPos := Rail_Pos_Target[Rail_Target_Position-1])。
                    回调异常只记 debug, 不影响状态机.
        motion: async (code) -> None; 将要 DONE 的动作在 RUNNING 态里的连续运动回调
                    (仿真沙盒阶段③: 把 *_ActPos 以真实 vel_max 匀速推进到 *_Target,
                    期间自行递增 Step 喂停滞看门狗), 完成后才写终态 —— 与真 PLC
                    "运动结束才报 DONE" 的次序一致。异常只记 debug, 照常写终态.
        dispatch: async (code) -> (term, error_code, safe_state) | None; **整段动作行为**
                    交给调用方 (仿真沙盒阶段③的工位行为模块: 按 CODESYS 提取的编排
                    说明书复刻段号/互锁/错误码)。给了它就旁路 motion/on_done/
                    mirror_on_done/slow_ticks —— 那些是"没有编排说明书时的近似",
                    与真编排并存只会互相打架。**返回 None = 本层不处理该码**, 落回
                    既有路径 (Develop 的 50/51 即如此: 排液另有独立后台 FSM 与桥)。
                    异常记 warning 并按 ERROR(500) 收尾, 不吞进静默 DONE。
                    ⚠ 挂在 190 全局门**之后**: 与真 PLC "启动门在派发器最前" 的次序一致。
    """
    import asyncio
    prev_start = False
    while not stop_event.is_set():
        try:
            start = bool(await mock_read(server, f"{prefix}_L2_Start"))
            state = int(await mock_read(server, f"{prefix}_L2_State"))
            if start and not prev_start and state == _L2_IDLE:
                seq = int(await mock_read(server, f"{prefix}_L2_RequestSeq"))
                code = int(await mock_read(server, f"{prefix}_L2_ActionCode"))
                await mock_write(server, f"{prefix}_L2_AcceptedSeq", seq)
                await mock_write(server, f"{prefix}_L2_ActiveCode", code)
                deploy_state = int(await mock_read(server, "PLC_Deploy_State"))
                ready = bool(await mock_read(server, "PLC_Ready"))
                if (not ready) or deploy_state != _DEPLOY_IDLE:
                    # 与真 PLC 的全局下载/启动门一致：请求被明确接收后以可重试拒绝结束，
                    # 绝不派发到泵、轴或气缸动作。
                    await mock_write(server, f"{prefix}_L2_Step", 0)
                    await mock_write(server, f"{prefix}_L2_ErrorCode", 190)
                    await mock_write(server, f"{prefix}_L2_SafeState", 0)
                    await mock_write(server, f"{prefix}_L2_Retryable", True)
                    await mock_write(server, f"{prefix}_L2_CompletedSeq", seq)
                    await mock_write(server, f"{prefix}_L2_State", _L2_REJECTED)
                    prev_start = start
                    await asyncio.sleep(tick)
                    continue
                await mock_write(server, f"{prefix}_L2_State", _L2_RUNNING)
                if dispatch is not None:
                    # 有编排说明书的工位: 整段行为 (含段号/互锁/错误码) 归行为模块,
                    # 本 FSM 只负责握手字段的读写次序
                    try:
                        outcome = await dispatch(code)
                    except Exception:
                        log.warning("[MockPLC] %s dispatch 异常 (code=%s)", prefix, code,
                                    exc_info=True)
                        outcome = (_L2_ERROR, 500, 90)
                    if outcome is not None:
                        term, err, safe = outcome
                        await mock_write(server, f"{prefix}_L2_ErrorCode", int(err))
                        await mock_write(server, f"{prefix}_L2_SafeState", int(safe))
                        await mock_write(server, f"{prefix}_L2_Retryable",
                                         term == _L2_REJECTED)
                        await mock_write(server, f"{prefix}_L2_CompletedSeq", seq)
                        await mock_write(server, f"{prefix}_L2_State", int(term))
                        prev_start = start
                        await asyncio.sleep(tick)
                        continue
                    # outcome 为 None = 行为模块声明"本层不处理该码", 落回既有路径
                    # (Develop 的 50/51 就走这条: 排液早有独立后台 FSM 与桥)
                if develop_tank_semantics and code in (50, 51):
                    await _develop_drain_bridge(server, prefix, seq, code, stop_event, tick)
                    prev_start = start
                    await asyncio.sleep(tick)
                    continue
                if code in hang_codes:
                    # 接受后永久 RUNNING, 不推进 Step / 不写终态 -> 看门狗应判停滞
                    prev_start = start
                    await asyncio.sleep(tick)
                    continue
                if code in reject_codes:
                    term, err, safe = _L2_REJECTED, 102, 0
                elif code in error_codes:
                    term, err, safe = _L2_ERROR, 201, 90
                else:
                    term, err, safe = _L2_DONE, 0, 10
                if term == _L2_DONE and motion is not None:
                    try:
                        await motion(code)
                    except Exception:
                        log.debug("[MockPLC] motion 回调异常", exc_info=True)
                # 慢动作: 逐拍推进 Step 制造可观测进度 (订阅会逐次推送, 复位停滞看门狗)
                for i in range(max(0, slow_ticks)):
                    await asyncio.sleep(tick)
                    await mock_write(server, f"{prefix}_L2_Step", i + 1)
                await mock_write(server, f"{prefix}_L2_Step", 90)
                await mock_write(server, f"{prefix}_L2_ErrorCode", err)
                await mock_write(server, f"{prefix}_L2_SafeState", safe)
                await mock_write(server, f"{prefix}_L2_Retryable", term == _L2_REJECTED)
                await mock_write(server, f"{prefix}_L2_CompletedSeq", seq)
                await mock_write(server, f"{prefix}_L2_State", term)
                if term == _L2_DONE:
                    for src, dst in mirror_on_done:
                        await mock_write(server, dst, await mock_read(server, src))
                    if on_done is not None:
                        try:
                            await on_done(code)
                        except Exception:
                            log.debug("[MockPLC] on_done 回调异常", exc_info=True)
            if not start and state in _L2_TERMINAL:
                await mock_write(server, f"{prefix}_L2_State", _L2_IDLE)
            prev_start = start
        except Exception:
            log.debug("[MockPLC] L2 FSM tick 异常", exc_info=True)
        await asyncio.sleep(tick)


# ── develop 排液语义 (spec 2026-07-14-develop-drain-l2-migration) ──
_TANK_DRAIN_START_STATES = (0, 40)   # 0=L2路径, 40=legacy路径; 与真 PLC FSM 同契约


async def _develop_drain_bridge(server, prefix: str, seq: int, code: int,
                                stop_event, tick: float) -> None:
    """develop L2 桥: code 50 桥接 Tank_Drain 数组等排液 FSM, code 51 释放缸.

    契约 (与真 PLC Develop_L2 派发器一致):
        50: Tank_State ∈ {10,90} → REJECTED 501; ∈ {98,99} → 幂等 DONE;
            其余置 Tank_Drain_Enable 并等 run_tank_drain_fsm 推到 98/Done (90 → ERROR 502)。
        51: Tank_State ∈ {98,99,0} → 清 Enable/Done + 写 0 → DONE; 否则 REJECTED 511。
    真 PLC 在 Start 落沿清 Enable; sim 在终态前顺手清, 时序差异离线无影响。
    """
    import asyncio
    tank = int(await mock_read(server, "Expand_Target_Tank"))
    idx = tank - 1
    term, err, safe = _L2_DONE, 0, 10
    if not (1 <= tank <= 8):
        term, err, safe = _L2_REJECTED, 102, 0
    elif code == 50:
        st = int((await mock_read(server, "Tank_State"))[idx])
        if st in (10, 90):
            term, err, safe = _L2_REJECTED, 501, 0
        elif st in (98, 99):
            term, err, safe = _L2_DONE, 0, 10   # 幂等直通
        else:
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            enables[idx] = True
            await mock_write(server, "Tank_Drain_Enable", enables)
            while not stop_event.is_set():
                st = int((await mock_read(server, "Tank_State"))[idx])
                await mock_write(server, f"{prefix}_L2_Step", st)
                done = bool((await mock_read(server, "Tank_Drain_Done"))[idx])
                if st == 90:
                    term, err, safe = _L2_ERROR, 502, 90
                    break
                if st in (98, 99) or done:
                    term, err, safe = _L2_DONE, 0, 10
                    break
                await asyncio.sleep(tick)
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            enables[idx] = False
            await mock_write(server, "Tank_Drain_Enable", enables)
    else:  # code == 51
        states = list(await mock_read(server, "Tank_State"))
        if int(states[idx]) in (98, 99, 0):
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            dones = list(await mock_read(server, "Tank_Drain_Done"))
            enables[idx] = False
            dones[idx] = False
            states[idx] = 0
            await mock_write(server, "Tank_Drain_Enable", enables)
            await mock_write(server, "Tank_Drain_Done", dones)
            await mock_write(server, "Tank_State", states)
        else:
            term, err, safe = _L2_REJECTED, 511, 0
    await mock_write(server, f"{prefix}_L2_ErrorCode", err)
    await mock_write(server, f"{prefix}_L2_SafeState", safe)
    await mock_write(server, f"{prefix}_L2_Retryable", term == _L2_REJECTED)
    await mock_write(server, f"{prefix}_L2_CompletedSeq", seq)
    await mock_write(server, f"{prefix}_L2_State", term)


async def run_tank_drain_fsm(server, stop_event, *, tick: float = 0.02, clock=None) -> None:
    """模拟 Develop_TankDrain per-tank 排液 FSM (spec 2026-07-14).

    相位: Enable ∧ State∈{0,40} → 50 → (判据 Tank_Drain_S / 挟持走 Tank_Drain_Cap_S
    并锁存 CapHit) → 55 → (Tank_Blow_S) → 56 → (Tank_Dry_S; 0=一拍直通) → 98 + Done。
    Enable 撤销: 清 Done; 50/55/56/90 安全归位到 0 (98 为静止终态不动)。
    时长直读 Tank_*_S 节点 (测试写小值)。**clock 给了才吃时间倍率** ——
    缺省 None 时逐字保持旧行为 (真实 monotonic 计时), 既有测试零改动;
    仿真沙盒传 SimClock 后, 默认 35 秒的排液在 8 倍率下 4.4 秒走完
    (此前它是全沙盒唯一不吃倍率的环节, 比真机还慢)。
    传感器挟持注入: server._eit_drain_wet_groups = {1} 表示组1 (缸1-4) 废液线持续
    "有液", 该组缸 Phase A 无法经判据完成, 只能走硬上限。
    并发写回: 判定逻辑基于本 tick 开始时的快照读, 但回写不再整组覆盖 ——
    只记录本 FSM 本 tick 改动的索引 (state_updates/done_updates/caphit_updates),
    结束前重新读取最新数组、仅在这些索引上应用改动后写回, 避免覆盖同 tick 内
    code-51 桥 (_develop_drain_bridge) 或测试对同一数组其他索引的并发写 (lost update)。
    """
    import asyncio
    import time

    def _now() -> float:
        """名义时刻 (秒): 有 clock 时按倍率折算, 使相位时长与其它行为层同步缩放."""
        raw = time.monotonic()
        return raw * float(getattr(clock, "rate", 1.0) or 1.0)

    phase_t0 = [0.0] * 9   # 下标 1..8
    while not stop_event.is_set():
        try:
            enables = list(await mock_read(server, "Tank_Drain_Enable"))
            states = list(await mock_read(server, "Tank_State"))
            dones = list(await mock_read(server, "Tank_Drain_Done"))
            caphits = list(await mock_read(server, "Tank_Drain_CapHit"))
            drain_s = float(await mock_read(server, "Tank_Drain_S"))
            cap_s = float(await mock_read(server, "Tank_Drain_Cap_S"))
            blow_s = float(await mock_read(server, "Tank_Blow_S"))
            dry_s = float(await mock_read(server, "Tank_Dry_S"))
            wet_groups = getattr(server, "_eit_drain_wet_groups", set())
            state_updates: dict[int, int] = {}
            done_updates: dict[int, bool] = {}
            caphit_updates: dict[int, bool] = {}
            for i in range(1, 9):
                idx = i - 1
                st = int(states[idx])
                if not enables[idx]:
                    if dones[idx]:
                        dones[idx] = False
                        done_updates[idx] = False
                    if st in (50, 55, 56, 90):
                        states[idx] = 0
                        state_updates[idx] = 0
                    continue
                if st in _TANK_DRAIN_START_STATES:
                    states[idx] = 50
                    caphits[idx] = False
                    phase_t0[i] = _now()
                    state_updates[idx] = 50
                    caphit_updates[idx] = False
                elif st == 50:
                    elapsed = _now() - phase_t0[i]
                    group = 1 if i <= 4 else 2
                    if group in wet_groups:
                        if elapsed >= cap_s:          # 挟持 → 硬上限兜底
                            caphits[idx] = True
                            states[idx] = 55
                            phase_t0[i] = _now()
                            caphit_updates[idx] = True
                            state_updates[idx] = 55
                    elif elapsed >= drain_s:          # 判据: 持续走空满时长
                        states[idx] = 55
                        phase_t0[i] = _now()
                        state_updates[idx] = 55
                elif st == 55:
                    if _now() - phase_t0[i] >= blow_s:
                        states[idx] = 56
                        phase_t0[i] = _now()
                        state_updates[idx] = 56
                elif st == 56:
                    if _now() - phase_t0[i] >= dry_s:
                        states[idx] = 98
                        dones[idx] = True
                        state_updates[idx] = 98
                        done_updates[idx] = True
            if state_updates:
                latest_states = list(await mock_read(server, "Tank_State"))
                for idx, val in state_updates.items():
                    latest_states[idx] = val
                await mock_write(server, "Tank_State", [int(x) for x in latest_states])
            if done_updates:
                latest_dones = list(await mock_read(server, "Tank_Drain_Done"))
                for idx, val in done_updates.items():
                    latest_dones[idx] = val
                await mock_write(server, "Tank_Drain_Done", [bool(x) for x in latest_dones])
            if caphit_updates:
                latest_caphits = list(await mock_read(server, "Tank_Drain_CapHit"))
                for idx, val in caphit_updates.items():
                    latest_caphits[idx] = val
                await mock_write(server, "Tank_Drain_CapHit", [bool(x) for x in latest_caphits])
        except Exception:
            log.debug("[MockPLC] TankDrain FSM tick 异常", exc_info=True)
        await asyncio.sleep(tick)
