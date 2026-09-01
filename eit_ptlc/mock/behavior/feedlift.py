"""FeedLift 工位的虚拟 PLC 行为 (阶段③)
=======================================
功能:
    复刻 CODESYS 现役工程 Application/50_action/FeedLift_L2 的内部工序:
    JOG 搜索光电边沿 + 停住确认 + 抖动重捕获 + 前置互锁门 + 错误码 301~308。
    段号/门条件/时序常量一律从编排说明书 (specs/feedlift.yaml) 取, **不在本模块
    复抄数字** —— 两份真源必然漂移。

    另含板堆物理模型 FeedLiftModel: 板越多平台停得越低, 光电触发位
    z_trigger = 空仓基准位 − 张数 × 堆叠节距 (与 controller/feedlift_count 的换算式
    互为逆运算, 标定常数同读 config/feedlift_calib.json, 不复制数字)。

板堆增减的判据 (设计决策, 与账本刻意解耦):
    模型自有计数是**物理真源**, 账本只做初始化与人工改写入口 (改写入口 =
    make_ledger_reflow, 挂在 MaterialStore.set_magazine_observer 上)。理由: 账本扣减绑在
    feedlift_load_cycle 脚本 DONE (material_bindings plate_take), 而流程中段第二次
    probe(expect_taken=1) 发生在扣账之前 —— 纯账本驱动的堆高在第二次 feed_raise 时
    不变, 差分必得 taken=0 判空吸, 流程永远过不去。物理上板离堆的时刻是"吸住后降轴
    让位"(A12 DONE 且吸盘 ON), 不是记账那一刻。

接线:
    run_l2_fsm(..., dispatch=make_feedlift_dispatcher(...)) —— 整段行为归本模块,
    不与 motion/mirror_on_done 并存 (那些是没有编排说明书时的近似)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from eit_ptlc.controller.feedlift_count import MAGAZINE_AXIS, load_calib
from eit_ptlc.mock.plc_server import mock_read, mock_write

log = logging.getLogger(__name__)

# L2 状态码 (与 plc_server / plc_controller 同值)
_L2_DONE, _L2_REJECTED, _L2_ERROR = 20, 30, 40

_TICK_S = 0.05          # 名义积分步长 (真实等待 = tick / clock.rate)

#: 光电回差 (mm) —— **全方案唯一自定常数, 非 ST 提取值**。
#: 真机光电有 0.2~1mm 量级的回差 (见 feedlift_count 注释), 取中值 0.5:
#: 清零动作停在触发位下方 ε 处, 逼近动作再走 ε 回到触发位。
#: 它必须 > MIN_APPROACH_MM(0.02), 否则真机链的"陈旧读数守卫"会把正常逼近判成陈旧。
PHOTO_HYSTERESIS_MM = 0.5

#: 各板仓的轴号与位置节点。
#: ⚠ ST 里的 JOG 命令位 (GVL.Z1JOG_pos/neg 等) **刻意不写**: 它们是 PLC 内部量,
#: 既不在 plc_nodes.yaml 也不在 manual_points.yaml (只在点表注释里被提到),
#: 真机 OPC 面上根本没有这几个节点。为了"看起来更像"而发明节点就是造假数据 ——
#: JOG 的可观测后果 (轴在动) 本模块已如实模拟, 那才是上位机能看见的东西。
_JOG_NODES = {
    "feed": {"axis": 1, "act": "FeedLift_1Z_ActPos"},
    "waste": {"axis": 2, "act": "FeedLift_2Z_ActPos"},
}
#: 动作码 -> (板仓, 搜索方向, 期望的光电终态)
#: 方向 +1 = 向上 (ActPos 增大), -1 = 向下
_SEARCH_BY_CODE = {
    11: ("feed", +1, True),     # 升到取料位: 光电 TRUE
    13: ("feed", -1, False),    # 退让: 光电 FALSE
    21: ("waste", +1, True),    # 升到接料位: 光电 TRUE
    22: ("waste", -1, False),   # 埋料: 光电 FALSE
}


@dataclass
class FeedLiftModel:
    """板堆与升降轴的物理模型 (沙盒内的"现场事实").

    参数:
        calib: {板仓: FeedLiftCalib}, 从 config/feedlift_calib.json 读 (与真机同源)
        counts: {板仓: 张数}, 初值取自物料账本, 之后由物理事件增减
        capacity: {板仓: 容量上限}, 拓扑真源 (material_topology.yaml)
        homed: {板仓: 该轴是否已回零}
        waste_armed: A21 完成后置位; 机器人放板 (吸盘 ON->OFF) 时 waste+1 并清零
    """
    calib: dict
    counts: dict = field(default_factory=lambda: {"feed": 0, "waste": 0})
    capacity: dict = field(default_factory=dict)
    homed: dict = field(default_factory=lambda: {"feed": True, "waste": True})
    calibration_source: dict = field(default_factory=dict)
    waste_armed: bool = False

    def z_trigger(self, magazine: str) -> float:
        """该板仓当前张数下的光电触发位 (mm); 与 count_from_pos 互为逆运算."""
        entry = self.calib[magazine]
        return entry.z_empty_mm - self.counts[magazine] * entry.pitch_mm

    def photo(self, magazine: str, z_mm: float) -> bool:
        """侧面光电: 顶板是否已升到取料/接料位 (空仓恒 False —— 没板可挡光)."""
        if self.counts[magazine] <= 0:
            return False
        return z_mm >= self.z_trigger(magazine) - 1e-9

    def proximity(self, magazine: str) -> bool:
        """仓底接近开关: 仓内有没有板."""
        return self.counts[magazine] > 0

    def alarm_ok(self, magazine: str) -> bool:
        """PLC 侧 Alarm.N 为 FALSE (即"没有报警")的沙盒推导.

        参数:
            magazine: feed | waste
        返回:
            bool; True = Alarm 位为 FALSE, 门这一项成立

        ⚠ 推定: Alarm 的产生逻辑不在 FeedLift_L2 的任何 POU 内 (未提取到), 上位机也无
        OPC 节点。此处按 PLC 注释原文「上料机构无物料」/「下料机构已满料」的**字面含义**
        由板堆张数推导 —— 是 docs/仿真保真度审查 第 5 节第 7 条"进料传感器/Alarm 位简并
        映射"在下料侧的对称延伸, 不是新发明的判据。
        """
        if magazine == "feed":
            return self.counts["feed"] > 0
        capacity = self.capacity.get(magazine)
        if capacity is None:
            return True
        return self.counts[magazine] < capacity

    def take_one(self, magazine: str) -> None:
        """取走一张 (板离堆); 空仓不再减."""
        if self.counts[magazine] > 0:
            self.counts[magazine] -= 1

    def put_one(self, magazine: str) -> None:
        """放入一张; 满仓不再加.

        与 make_ledger_reflow 的"不夹逼"刻意不对称: 这里加的是**沙盒自己模拟出来的**
        一张板, 越过物理上限就是自造不可能状态; 而回灌收下的是外部权威的断言, 沙盒
        无权静默改正。
        """
        capacity = self.capacity.get(magazine)
        if capacity is not None and self.counts[magazine] >= capacity:
            log.warning("[沙盒·板堆] %s 已满 (%d 张), 本次放板未计入 —— "
                        "真机此时 Alarm.1 置位, A21 会报 302", magazine, capacity)
            return
        self.counts[magazine] += 1


async def _read_z(server, magazine: str) -> float:
    """读某板仓升降轴的当前位置 (mm)."""
    return float(await mock_read(server, _JOG_NODES[magazine]["act"]))




def make_feedlift_dispatcher(server, spec, model, *, clock, stop_event,
                             write_axis, suction_on):
    """构造 FeedLift 的 L2 动作行为 (run_l2_fsm 的 dispatch 回调).

    参数:
        server: Mock OPC 服务器; spec: StationSpec (specs/feedlift.yaml)
        model: FeedLiftModel; clock: SimClock (吃时间倍率)
        stop_event: 停机事件; write_axis: async (轴号, mm) -> None
        suction_on: () -> bool, 吸盘此刻是否吸住 (板堆增减的物理判据)
    返回:
        async (code) -> (term, error_code, safe_state)
    """
    constants = spec.constants
    stable_s = float(constants["stable_confirm_ms"]) / 1000.0
    gate_timeout_s = float(constants["gate_timeout_s"])
    init_timeout_s = float(constants["init_homed_timeout_s"])
    lower_rel_mm = float(constants["feed_lower_rel_mm"])
    debug_stable_s = float(constants["debug_stable_ms"]) / 1000.0
    # JOG 速度取点表 jog_vel_fixed (真实配置值, 不编造)
    jog_speed = float(constants.get("jog_speed_mm_s") or 15.0)

    async def _write_z(magazine: str, value: float) -> None:
        """写轴位置 (经注入的三写函数: flat + 别名 + struct)."""
        await write_axis(_JOG_NODES[magazine]["axis"], value)

    async def _set_step(value: int) -> None:
        """写段号 (喂上位机停滞看门狗; 值来自编排说明书)."""
        await mock_write(server, "FeedLift_L2_Step", int(value))

    def _steps(code: int) -> dict:
        """该动作的 {阶段名: 段号} 映射."""
        return {item["phase"]: item["step"] for item in spec.action(code).steps}

    async def _wait_gate(magazine: str, code: int, phases: dict) -> int | None:
        """等前置门满足; 超时返回错误码, 满足返回 None.

        门条件逐条来自 spec.gate: A11 查进料传感器而 A13 刻意不查 (向下退让不该被
        仓内有无料卡住), A21 查出料传感器而 A22 查接近开关 —— 四个动作四张门。
        """
        gate = spec.action(code).gate
        timeout_error = int(gate.get("timeout_error") or 301)
        waited = 0.0
        while waited <= gate_timeout_s:
            ok = True
            if "homed" in gate and not model.homed[magazine]:
                ok = False
            # 上料侧的两个等价物理量 (接近开关1 / 上料进料传感器) 简并为"仓内有板" ——
            # 依据是 docs/仿真保真度审查 第 5 节第 7 条; 真机那两个信号上位机也只能读到
            # 接近开关, 进料传感器是 PLC 内部量。A22 的接近开关2 走同一条 (埋料要仓内有板)。
            if ("proximity" in gate or "feed_sensor" in gate) and not model.proximity(magazine):
                ok = False
            # ⚠ 下料出料传感器: PLC 内部量, 沙盒无对应现场事实, 按恒成立处理。
            # **绝不能**把它也简并成"仓内有板" —— A21 的门刻意不查接近开关2
            # (specs/feedlift.yaml A21 notes 原文), 正是为了让空的下料仓也能升到接料位;
            # 简并之后空仓永远接不了第一张板, 那是可证伪的错。
            if "alarm" in gate and not model.alarm_ok(magazine):
                ok = False
            if ok:
                return None
            await clock.sleep(_TICK_S)
            waited += _TICK_S
            await _set_step(phases.get("preflight_and_search_up")
                            or phases.get("preflight_and_search_down") or 0)
        return timeout_error

    async def _search(code: int) -> tuple:
        """JOG 搜索光电边沿 + 停住确认 (A11/A13/A21/A22 共用)."""
        magazine, direction, want_photo = _SEARCH_BY_CODE[code]
        action = spec.action(code)
        phases = _steps(code)
        search_step = (phases.get("preflight_and_search_up")
                       or phases.get("preflight_and_search_down"))
        confirm_step = phases.get("confirm_stable")
        fail_step = phases.get("fail")
        # 失败码: 该动作 errors 里除去 301/302/303 的那个 (304/305/307)
        search_error = next((c for c in action.errors if c not in (301, 302, 303)), 305)
        gate_error_default = 301 if magazine == "feed" else 302

        await _set_step(search_step)
        # 判定 1: 搜索区间非法 (SearchLow >= SearchHigh) -> 303
        axis = _JOG_NODES[magazine]["axis"]
        low = float(await mock_read(server, f"FeedLift_{axis}Z_SearchLowTarget"))
        high = float(await mock_read(server, f"FeedLift_{axis}Z_SearchHighTarget"))
        if low >= high:
            await _set_step(fail_step)
            return (_L2_ERROR, 303, 90)
        # 判定 2: 前置门
        gate_error = await _wait_gate(magazine, code, phases)
        if gate_error is not None:
            await _set_step(fail_step)
            return (_L2_ERROR, gate_error or gate_error_default, 90)

        # 搜索: 已在目标侧则原地确认 (真机的幂等直通 —— "陈旧读数"坑的来源, 必须保留)
        z = await _read_z(server, magazine)
        if model.photo(magazine, z) != want_photo:
            while model.photo(magazine, z) != want_photo:
                if stop_event.is_set():
                    return (_L2_ERROR, search_error, 90)
                await clock.sleep(_TICK_S)
                z += direction * jog_speed * _TICK_S
                # 出界即失败 (与 ST 的 SearchLow/High 守卫同判据)
                if z > high or z < low:
                    await _write_z(magazine, min(max(z, low), high))
                    await _set_step(fail_step)
                    return (_L2_ERROR, search_error, 90)
                await _write_z(magazine, z)
                await _set_step(search_step)
            # 停在边沿: 向上搜停在触发位, 向下搜停在触发位下方一个回差
            trigger = model.z_trigger(magazine)
            await _write_z(magazine,
                           trigger if want_photo else trigger - PHOTO_HYSTERESIS_MM)

        # 停住确认 (真机 300ms; 沙盒里光电不抖, 确认必过 —— 抖动分支靠故障注入触发)
        await _set_step(confirm_step)
        await clock.sleep(stable_s)
        return (_L2_DONE, 0, 10)

    async def _init() -> tuple:
        """A10: 清残留命令位 + 校验双轴已回零 (不产生任何轴运动)."""
        phases = _steps(10)
        # ST 的 step 0 清六个残留命令位; 沙盒里那些位不存在 (见 _JOG_NODES 头注),
        # 故本段只走段号 —— 它对上位机的可观测面 (Step 值) 是一致的
        await _set_step(phases.get("clear_residual_commands"))
        await _set_step(phases.get("check_homed"))
        waited = 0.0
        while waited <= init_timeout_s:
            if model.homed["feed"] and model.homed["waste"]:
                return (_L2_DONE, 0, 10)
            await clock.sleep(_TICK_S)
            waited += _TICK_S
        await _set_step(phases.get("fail"))
        return (_L2_ERROR, 308, 90)

    async def _feed_lower() -> tuple:
        """A12: 1Z 相对下降 5mm 让位; DONE 且吸盘吸住即扣一张 (板离堆的物理时刻)."""
        z = await _read_z(server, "feed")
        target = z + lower_rel_mm
        while abs(target - z) > 1e-6:
            if stop_event.is_set():
                break
            await clock.sleep(_TICK_S)
            step = jog_speed * _TICK_S
            z = target if abs(target - z) <= step else z - step
            await _write_z("feed", z)
        taken = False
        if suction_on():
            model.take_one("feed")
            taken = True
        log.debug("[沙盒·FeedLift] feed_lower 完成, 吸盘=%s, 余 %d 张",
                  taken, model.counts["feed"])
        return (_L2_DONE, 0, 10)

    async def _endcheck() -> tuple:
        """A91: DEBUG —— 不动轴, 只确认指定轴光电稳定处于期望值 (200ms)."""
        await _set_step(_steps(91).get("debug_confirm", 91))
        axis = int(await mock_read(server, "FeedLift_DebugAxis") or 0)
        magazine = next((name for name, a in MAGAZINE_AXIS.items() if a == axis), None)
        if magazine is None:
            return (_L2_ERROR, 306, 90)
        expected = bool(await mock_read(server, "FeedLift_DebugExpectedFinal"))
        z = await _read_z(server, magazine)
        if model.photo(magazine, z) != expected:
            # 与真机同: 不满足就一直等, 由上位机停滞看门狗判 (无专属错误码)
            while model.photo(magazine, await _read_z(server, magazine)) != expected:
                if stop_event.is_set():
                    return (_L2_ERROR, 306, 90)
                await clock.sleep(_TICK_S)
        await clock.sleep(debug_stable_s)
        return (_L2_DONE, 0, 10)

    async def dispatch(code: int) -> tuple:
        """按动作码派发; 未登记码回 REJECTED (与真派发器的 ELSE 分支同)."""
        if code not in spec.accepts:
            return (_L2_REJECTED, spec.unknown_code_error, 0)
        if code == 10:
            return await _init()
        if code == 12:
            return await _feed_lower()
        if code == 91:
            return await _endcheck()
        if code in _SEARCH_BY_CODE:
            outcome = await _search(code)
            # A21 完成 = 接料位就绪; 放板 (吸盘 ON->OFF) 时才真加一张
            if code == 21 and outcome[0] == _L2_DONE:
                model.waste_armed = True
            if code == 22 and outcome[0] == _L2_DONE:
                model.waste_armed = False
            return outcome
        return (_L2_REJECTED, spec.unknown_code_error, 0)

    return dispatch


async def run_stack_watch_loop(model: FeedLiftModel, suction_on, *, clock, stop_event,
                               tick: float = _TICK_S) -> None:
    """板堆的机器人侧增量观察者: 监视吸盘 ON->OFF 沿, 在下料仓已就绪时 +1.

    参数:
        model: 板堆模型; suction_on: () -> bool, 吸盘此刻是否吸住
        clock: SimClock (吃时间倍率); stop_event: 停机事件; tick: 采样周期 (秒)
    返回:
        None

    判据出自编排说明书: specs/feedlift.yaml 的 A21 notes 原文 ——
    "沙盒的 waste 计数在本动作 DONE 时置 armed 标志, 真正 +1 在放板 (吸盘 ON->OFF 沿) 时"。

    三条设计理由 (与 take_one 的对称性一并记在这里):
      * **为什么是独立任务而不是塞进 sensors**: sensors.py 头注自称"沙盒唯一的 IX 写者",
        它是只读合成器; 让它顺手改板堆模型会毁掉那条单写者纪律。
      * **为什么不绑 A22 DONE**: 那会让埋料行程从"一个节距 + 回差"缩成"只有回差",
        随后 waste 侧的 probe 差分会量到错误节距。板入堆确实发生在 A21 与 A22 之间。
      * ⚠ 推定: "armed 窗口内的松手 = 放到了下料仓"。沙盒没有空间推理; A21 DONE 到
        A22 DONE 之间正是真实编排里机械臂在下料仓上方的那一段
        (config/actions/05_feedlift/plc_feedlift.yaml 头注: 下料编排 = unload_ready(21)
        -> [机器人放废料] -> unload_bury(22)), 故以 armed 作代理。
    """
    previous = bool(suction_on())
    while not stop_event.is_set():
        await clock.sleep(tick)
        try:
            current = bool(suction_on())
        except Exception:
            log.debug("[沙盒·板堆] 吸盘态读取异常", exc_info=True)
            continue
        if previous and not current and model.waste_armed:
            model.put_one("waste")
            model.waste_armed = False
            log.info("[沙盒·板堆] 吸盘松开: 下料仓 +1 -> %d 张", model.counts["waste"])
        previous = current


def build_model(calib_dir, magazines: dict, counts: dict) -> FeedLiftModel:
    """按标定文件与账本初值造板堆模型.

    参数:
        calib_dir: 含 feedlift_calib.json 的目录 (config/)
        magazines: {板仓: (显示名, 容量)} —— 拓扑真源, 取容量用
        counts: {板仓: 初始张数} (通常来自物料账本)
    返回:
        FeedLiftModel
    """
    field_path = calib_dir / "feedlift_calib.json"
    fixture_path = Path(__file__).resolve().parent / "specs" / "feedlift_sim_calib.json"
    calib = {}
    calibration_source = {}
    for name in MAGAZINE_AXIS:
        field_calib = load_calib(field_path, name, magazines[name][1])
        if field_calib.calibrated:
            calib[name] = field_calib
            calibration_source[name] = "field_calibration"
            continue
        # The checked-in field file intentionally ships uncalibrated so a
        # deployment can never inherit another machine's measurements.  The
        # isolated simulator still needs non-zero geometry to exercise JOG
        # search, probe, and take/put behavior.  Its deterministic nominal
        # fixture is explicitly separate and is never read by the real PLC
        # runtime.
        calib[name] = load_calib(fixture_path, name, magazines[name][1])
        calibration_source[name] = "simulation_fixture"
    return FeedLiftModel(calib=calib,
                         counts={name: int(counts.get(name, 0)) for name in MAGAZINE_AXIS},
                         capacity={name: int(magazines[name][1]) for name in MAGAZINE_AXIS},
                         calibration_source=calibration_source)


def make_ledger_reflow(model: FeedLiftModel):
    """构造"账面 -> 板堆模型"的回灌器 (MaterialStore.set_magazine_observer 的入参).

    参数:
        model: 板堆模型
    返回:
        (counts, detail) -> None

    为什么需要它: 模型的 counts 只在建栈那一刻从账本取过一次初值 (build_model),
    此后 adopt / 人工盘点 / 光电盘点校正把账面改成什么, 模型都不知道 —— 于是
    "采纳了真机的 30 张板" 在沙盒里仍是 0 张, 仓底接近开关恒 FALSE, A11/A13/A21/A22
    的前置门必然 10 秒超时报 301/302。回灌器是这三条路唯一的汇合点。

    ⚠ 反方向已经通了 (probe(reconcile=True) 用光电实测回写账本), 所以本回灌器
    **值相等即跳过** —— 否则 "实测写账本 -> 账本回灌模型" 会绕成一个回环。
    """
    def reflow(counts: dict, detail: str) -> None:
        for magazine, value in dict(counts).items():
            if magazine not in model.counts:
                continue
            new_count = int(value)
            if model.counts[magazine] == new_count:
                continue                      # 切断 probe 回写账本 -> 回灌模型 的回环
            log.info("[沙盒·板堆] %s 张数按账面改写 %d -> %d (%s)",
                     magazine, model.counts[magazine], new_count, detail)
            # **刻意不夹逼 capacity**: 回灌是"外部权威声称现场如此", 沙盒无权静默改正。
            # 收下之后 z_trigger 会落到搜索窗外, A11 如实报 304 到界 —— 与真机同款失败面。
            # (put_one 反过来要夹逼: 那是沙盒自己的物理上限, 不是外部断言。)
            capacity = model.capacity.get(magazine)
            if capacity is not None and new_count > capacity:
                log.warning("[沙盒·板堆] %s 账面 %d 张超过容量 %d 张: 已照收, "
                            "该仓的光电触发位将落在搜索窗外", magazine, new_count, capacity)
            model.counts[magazine] = new_count
    return reflow
