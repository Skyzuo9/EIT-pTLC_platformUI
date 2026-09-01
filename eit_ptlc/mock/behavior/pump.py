"""虚拟注射泵 (阶段③): 逐 DT 指令积分柱塞与阀位。

归真原则:
    执行器经 PUMP_PROFILES → translator 写进 PLC 节点的**真实 DT 指令串**就是
    虚拟泵的唯一输入 —— 用 tools/pump/dt_codec.parse (与串产地同语法真源) 解析,
    按 V(步/秒) 对 A/P 段积分、M 段停拍、I 段转阀。配置错误 (错档速/错端口)
    会原样表现在柱塞速度与阀指针上, 这正是仿真模块存在的意义。

触发语义 (2026-08-09 订正): **L2 动作码派发即消费** —— run_l2_fsm 的 motion 钩子
    在 RUNNING 态内调 make_pump_hook 的回调, 按 (工位前缀, action_code) 查
    PUMP_BY_CODE 取指令节点并**无条件**执行, 泵积分完 FSM 才写 DONE (与真 PLC
    "泵空闲上升沿才 DONE" 同序)。此前按"节点值变更"轮询触发有三个病根, 都在
    用户实测里现形: 同参数重复执行值不变即漏触发; Develop 三动作共用指令节点
    却分属两个轮数节点, 按值变更无从判别; 与 L2 无因果、DONE 不等泵完成。

事件: 沙盒 bus 的 `pump_state` (仅沙盒通道; 真机泵无位置回读, 主通道诚实缺席):
    {"type":"pump_state","id":"SMP","plunger_ml":x,"valve_port":p,"busy":b,"ts","seq"}
    busy 期间 ~10Hz, 终态补一帧。协议注记见 three_d/docs/PTLC_REALTIME_PROTOCOL.md。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from eit_ptlc.mock.plc_server import mock_read, mock_write
from eit_ptlc.tools.pump import dt_codec

log = logging.getLogger(__name__)

#: DT 站号 → manifest.pumpSyringe 泵 id (rig_map pumps.items 的 dt_addr 逐字对照)
ADDR_TO_PUMP_ID = {"1": "DEV1", "2": "DEV2", "3": "COL", "4": "SMP"}

_STEPS_PER_ML = 240.0        # 6000 步 / 25 mL (translator 常量, 三处同源)
_MAX_PLUNGER_STEPS = 6000.0  # 满程 (dt_codec 的 move_abs(6000) 即吸满, 同一条常量)
_VALVE_S = 0.4               # 换阀名义时长 (与三维 PUMP_VALVE_S 同值)
_PUBLISH_S = 0.1             # busy 期事件节奏 (真实秒, 不随倍率缩 —— 是采样率不是物理量)
_TICK_S = 0.05               # 柱塞积分名义步长


@dataclass(frozen=True)
class PumpFeed:
    """一条 (工位, 动作码) 的指令消费声明 (与 PLC POU 的消费方式逐条对照)。"""
    node: str
    order: tuple[int, ...] | None = None    # 数组消费序; None = 自然序
    count_node: str | None = None           # 重复次数节点
    repeat: str = "array"                   # array=整组×count | last=末条×count


#: (L2 前缀, action_code) → 指令消费声明。码表与 config/actions/**/plc_*.yaml 的
#: action_code、profiles.py 各 builder 的落点逐字对照 (2026-08-09 勘察定稿):
#:   Sampling 20 = clean(mode 0)/flush(mode 1, count 恒写 1) 共用 clean 通道;
#:   Sampling 50 消费序 [2]气隔断→[1]样品 (PLC A50 契约);
#:   Sampling 55 只循环末条吹打 (rinse_mix_count);
#:   Develop 20/21(润洗/清管) 吃 Expand_rinse_count, 22(上液) 吃 Expand_up_liquid_count
#:   —— 旧"按节点值变更"触发无从判别的轮数二义, 随动作码天然消解。
PUMP_BY_CODE: dict[tuple[str, int], PumpFeed] = {
    ("Sampling", 20): PumpFeed("Sampling_clean_instructions", count_node="Sampling_clean_count"),
    ("Sampling", 40): PumpFeed("Sampling_prep_instructions"),
    ("Sampling", 50): PumpFeed("Sampling_sample_instructions", order=(1, 0)),
    ("Sampling", 55): PumpFeed("Sampling_rinse_mix_instructions",
                               count_node="Sampling_rinse_mix_count", repeat="last"),
    ("Sampling", 60): PumpFeed("Sampling_dispense_instructions"),
    ("Sampling", 62): PumpFeed("Sampling_band_run_instruction"),
    ("Collect", 30): PumpFeed("collect_forward_instructions", count_node="collect_count"),
    ("Develop", 20): PumpFeed("Expand_forward_instructions", count_node="Expand_rinse_count"),
    ("Develop", 21): PumpFeed("Expand_forward_instructions", count_node="Expand_rinse_count"),
    ("Develop", 22): PumpFeed("Expand_forward_instructions", count_node="Expand_up_liquid_count"),
}


class PumpModel:
    """一台泵的柱塞/阀状态 + 逐段积分执行。"""

    def __init__(self, pump_id: str) -> None:
        self.pump_id = pump_id
        self.plunger_steps = 0.0
        self.valve_port: int | None = None
        self.busy = False
        #: 累计排出/吸入步数 (只增, 建栈起算) —— 与瞬时位置 plunger_steps 是两回事
        self.dispensed_steps = 0.0
        self.aspirated_steps = 0.0

    @property
    def dispensed_ml(self) -> float:
        """建栈以来累计**排出**体积 mL (柱塞下行段之和); 展缸进液量的来源."""
        return self.dispensed_steps / _STEPS_PER_ML

    @property
    def aspirated_ml(self) -> float:
        """建栈以来累计**吸入**体积 mL (柱塞上行段之和).

        它才是与账本 liquid_draw ("从溶剂瓶抽液") 语义对得上的那个量 —— 排出量对应的
        是"送到哪里去了"。两者在一个完整取送周期后趋近相等, 但中途必然不等。
        """
        return self.aspirated_steps / _STEPS_PER_ML

    def snapshot(self) -> dict:
        return {
            "id": self.pump_id,
            "plunger_ml": round(self.plunger_steps / _STEPS_PER_ML, 4),
            "dispensed_ml": round(self.dispensed_ml, 4),
            "aspirated_ml": round(self.aspirated_ml, 4),
            "valve_port": self.valve_port,
            "busy": self.busy,
        }

    def set_state(self, *, plunger_ml=None, valve_port=None) -> None:
        """直写柱塞位与阀位 —— 沙盒"设初态"用, **不发 DT 指令**.

        参数:
            plunger_ml: 柱塞位置 mL, 夹逼到 [0, 满程]; None 表示不动
            valve_port: 阀口号 (>=1); None 表示不动
        返回:
            None
        Raises:
            RuntimeError: 泵正忙。指令串跑到一半改状态会与积分器打架, 且改完那一拍
                就被下一次积分覆盖 —— 是个"看起来生效实际没生效"的写, 不如直接拒。
            ValueError: 阀口号非正整数

        为什么不用"发一条 A 指令去凑初态": 那等于让**设状态**变成**跑动作**, 时序与
        副作用一并跟来 (换阀 0.4s、pump_state 事件流、L2 段号)。设初态就该是瞬时赋值。
        "泵吸了一半停电重开"是个真实初态, 沙盒必须能表达它。
        """
        if self.busy:
            raise RuntimeError(f"泵 {self.pump_id} 正在执行指令串, 此刻不接受直写状态")
        if plunger_ml is not None:
            steps = float(plunger_ml) * _STEPS_PER_ML
            self.plunger_steps = min(max(steps, 0.0), _MAX_PLUNGER_STEPS)
        if valve_port is not None:
            port = int(valve_port)
            if port < 1:
                raise ValueError(f"阀口号应为正整数, 收到 {valve_port!r}")
            self.valve_port = port

    async def run_program(self, program: dt_codec.DtProgram, clock, publish,
                          *, on_tick=None) -> None:
        """按 DT 语义执行一条指令串 (V 速度/I 阀/A 绝对/P 相对/M 延时/Z 归零)。

        on_tick: 可选 async 回调, 随事件节奏调用 —— 沙盒用它递增 {prefix}_L2_Step
        喂 PlcController 的停滞看门狗 (60s), 让长泵段不被误判"结果不明确"。
        """
        speed_steps_s = 0.0
        self.busy = True
        publish()
        try:
            for tok in program.toks:
                if tok.code == "V":
                    speed_steps_s = float(tok.value or 0)
                elif tok.code == "I":
                    if self.valve_port != int(tok.value or 0):
                        await clock.sleep(_VALVE_S)
                        self.valve_port = int(tok.value or 0)
                        publish()
                        if on_tick is not None:
                            await on_tick()
                elif tok.code in ("A", "P"):
                    target = (float(tok.value or 0) if tok.code == "A"
                              else self.plunger_steps + float(tok.value or 0))
                    await self._ramp(target, speed_steps_s, clock, publish, on_tick)
                elif tok.code == "M":
                    await clock.sleep(float(tok.value or 0) / 1000.0)
                    if on_tick is not None:
                        await on_tick()
                elif tok.code == "Z":
                    self.plunger_steps = 0.0
                    self.valve_port = int(tok.triple[2]) if tok.triple else self.valve_port
                    publish()
                # R/Q/T: 执行标记/查询/停 —— 批式积分下无事可做
        finally:
            self.busy = False
            publish()

    async def _ramp(self, target_steps: float, speed_steps_s: float, clock, publish,
                    on_tick=None) -> None:
        """柱塞以 V 匀速走到 target; V 缺失/为 0 时按名义 3s 兜底 (不该发生, 留痕即可)。"""
        if speed_steps_s <= 0:
            log.warning("[SimPump] %s 收到无速度段, 按 3s 兜底", self.pump_id)
            speed_steps_s = abs(target_steps - self.plunger_steps) / 3.0 or 1.0
        last_pub = 0.0
        while abs(target_steps - self.plunger_steps) > 1e-6:
            await clock.sleep(_TICK_S)
            step = speed_steps_s * _TICK_S
            delta = target_steps - self.plunger_steps
            previous = self.plunger_steps
            self.plunger_steps = (target_steps if abs(delta) <= step
                                  else self.plunger_steps + (step if delta > 0 else -step))
            # 排出量累计: 柱塞**下行**(步数减少)才是往外推液, 上行是吸入。
            # 这个量有两个下游: ① 展缸液量的进液源 (泵推了多少缸里就多多少);
            # ② 与账本扣减并排显示的那个数 —— 账本仍按动作参数扣 (真机没有流量计,
            #    照参数扣是真机的真实盲区, 沙盒不许比真机聪明), 差异只呈现不回写。
            if self.plunger_steps < previous:
                self.dispensed_steps += previous - self.plunger_steps
            else:
                self.aspirated_steps += self.plunger_steps - previous
            now = time.monotonic()
            if now - last_pub >= _PUBLISH_S:
                last_pub = now
                publish()
                if on_tick is not None:
                    await on_tick()
        publish()


def create_pumps() -> dict[str, PumpModel]:
    """建全套虚拟泵注册表 (栈级持有: 柱塞/阀状态跨动作延续)。"""
    return {pump_id: PumpModel(pump_id) for pump_id in ADDR_TO_PUMP_ID.values()}


def make_pump_publisher(bus):
    """构造 pump_state 广播器: (model) -> publish() 闭包, seq 全栈单调。"""
    seq = {"n": 0}

    def publisher(model: PumpModel):
        def publish() -> None:
            seq["n"] += 1
            bus.publish({"type": "pump_state", **model.snapshot(),
                         "ts": time.time(), "seq": seq["n"]})
        return publish

    return publisher


def make_pump_hook(server, prefix: str, pumps: dict, clock, publisher):
    """构造某工位的 L2 泵消费回调 async (code) -> None (挂 run_l2_fsm 的 motion 钩)。

    真 PLC 语义: 动作码派发即消费 —— 按 (prefix, code) 查 PUMP_BY_CODE, **无条件**
    读节点执行 (不做值去重: 同参数重跑指令串不变, 泵照样要动)。指令串自带 DT 站号
    (/{addr}), 按 ADDR_TO_PUMP_ID 路由到泵 —— Develop 双泵共用一个转发节点天然分流。
    执行期经 on_tick 递增 {prefix}_L2_Step (与轴 motion 的 Step 各数各的, 停滞看门狗
    只认"有变化", 数值回卷无妨)。
    """
    async def hook(code: int) -> None:
        feed = PUMP_BY_CODE.get((prefix, int(code)))
        if feed is None:
            return
        try:
            raw = await mock_read(server, feed.node)
        except Exception:
            return
        entries = [str(v) for v in (raw if isinstance(raw, (list, tuple)) else [raw])]
        if not any(entry.strip() for entry in entries):
            return
        if feed.order is not None:
            entries = [entries[i] for i in feed.order if i < len(entries)]
        count = 1
        if feed.count_node is not None:
            try:
                count = max(1, int(await mock_read(server, feed.count_node)))
            except Exception:
                count = 1
        programs: list[dt_codec.DtProgram] = []
        for entry in entries:
            if not entry.strip():
                continue
            try:
                programs.append(dt_codec.parse(entry))
            except ValueError as exc:
                # 野串拒执行并留痕 —— 虚拟泵只认合法 DT (与真泵拒帧同义)
                log.warning("[SimPump] %s 含非法 DT 串, 已拒: %s", feed.node, exc)
        if not programs:
            return
        if feed.repeat == "last" and count > 1:
            rounds = programs[:-1] + [programs[-1]] * count
        else:
            rounds = programs * count

        step_state = {"n": 0}

        async def bump_step() -> None:
            step_state["n"] += 1
            await mock_write(server, f"{prefix}_L2_Step", min(step_state["n"], 80))

        for program in rounds:
            pump_id = ADDR_TO_PUMP_ID.get(str(program.addr))
            if pump_id is None:
                continue
            model = pumps[pump_id]
            try:
                await model.run_program(program, clock, publisher(model), on_tick=bump_step)
            except Exception:
                log.debug("[SimPump] %s 执行异常", pump_id, exc_info=True)

    return hook
