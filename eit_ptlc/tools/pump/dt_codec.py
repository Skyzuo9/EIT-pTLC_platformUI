"""SY-03B 注射泵 DT 协议编解码 + 结构化指令计划 (PumpPlan)
=========================================================
功能:
    1. parse/serialize —— DT 指令串 <-> 结构化 DtProgram 的双向无损转换
       (对全部真实产地串满足 serialize(parse(s)) == s, 由
       tests/test_pump_dt_golden_offline.py 的往返用例守护);
    2. PumpPlan/PlanEntry/PlanSegment —— 指令的**语义层**: 每段柱塞运动带
       op(吸/排)/端口/速度语义键(asp_speed 等参数名)/mL 换算, 供三维演示与
       仿真沙盒按真实指令推导动画, 不再手抄相位表;
    3. CmdBuilder —— translator 侧的构串器: 按 V/I/A/P/M 语法逐 token 组装,
       同步登记语义段。translator 的 build_* 改为 plan_* 的序列化壳后,
       DT 字符串与动画相位天然同源。

定位 (仿真模块阶段①):
    本模块是"泵链路归真"的枢纽 —— 上游 translator 用 CmdBuilder 产出
    PumpPlan; 下游 (a) build_* 壳序列化成 PLC 指令串, (b) 三维漂移门禁拿
    plan 的语义段对账手写相位表, (c) 阶段③行为级虚拟泵用 parse +
    motion_segments 逐段积分柱塞。

语法 (以真实产地为准, 不自造扩展):
    cmd  := '' | '/' addr token* term?
    addr := [0-9]+                                  # DT 站号
    token:= [VIAPM][0-9]+ | 'Z' n ',' n ',' n | [RQT]
        V=速度 I=切阀口 A=柱塞绝对步位 P=相对增量 M=段后延时(ms)
        Z=初始化(力度,入口,出口) R=执行 Q=状态查询 T=立即停止
    term := '\\r' | '$R'                            # 运行串回车 / 初始化查询尾
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 带整型参数的 token 码与裸 token 码 (次序无关, 仅词法分类)
_VALUE_CODES = frozenset("VIAPM")
_BARE_CODES = frozenset("RQT")


# ---------------------------------------------------------------------------
# 词法层
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DtTok:
    """一个 DT token。value 供 V/I/A/P/M; triple 供 Z; 裸 token 两者皆 None。"""
    code: str
    value: int | None = None
    triple: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class DtProgram:
    """一条 DT 指令串的结构化形式; 空串表现为 addr=None 无 token 无尾。"""
    addr: str | None
    toks: tuple[DtTok, ...] = ()
    terminator: str = ""


def parse(cmd: str) -> DtProgram:
    """DT 指令串 -> DtProgram; 语法外字符一律 ValueError (虚拟泵拒执行野串)。"""
    if cmd == "":
        return DtProgram(addr=None)
    if not cmd.startswith("/"):
        raise ValueError(f"DT 指令必须以 '/' 开头, 收到 {cmd!r}")
    pos = 1
    start = pos
    while pos < len(cmd) and cmd[pos].isdigit():
        pos += 1
    if pos == start:
        raise ValueError(f"DT 指令缺站号: {cmd!r}")
    addr = cmd[start:pos]

    toks: list[DtTok] = []
    terminator = ""
    while pos < len(cmd):
        ch = cmd[pos]
        if ch in _VALUE_CODES:
            pos += 1
            num_start = pos
            while pos < len(cmd) and cmd[pos].isdigit():
                pos += 1
            if pos == num_start:
                raise ValueError(f"token {ch} 缺数值: {cmd!r}")
            toks.append(DtTok(ch, value=int(cmd[num_start:pos])))
        elif ch == "Z":
            pos += 1
            fields: list[int] = []
            for i in range(3):
                num_start = pos
                while pos < len(cmd) and cmd[pos].isdigit():
                    pos += 1
                if pos == num_start:
                    raise ValueError(f"Z 初始化缺第 {i + 1} 个参数: {cmd!r}")
                fields.append(int(cmd[num_start:pos]))
                if i < 2:
                    if pos >= len(cmd) or cmd[pos] != ",":
                        raise ValueError(f"Z 初始化参数须以逗号分隔: {cmd!r}")
                    pos += 1
            toks.append(DtTok("Z", triple=(fields[0], fields[1], fields[2])))
        elif ch in _BARE_CODES:
            toks.append(DtTok(ch))
            pos += 1
        elif ch == "\r":
            terminator = "\r"
            pos += 1
            break
        elif ch == "$":
            if cmd[pos:] != "$R":
                raise ValueError(f"'$' 只允许作 '$R' 尾出现: {cmd!r}")
            terminator = "$R"
            pos += 2
            break
        else:
            raise ValueError(f"DT 指令含语法外字符 {ch!r}: {cmd!r}")
    if pos != len(cmd):
        raise ValueError(f"终止符后不允许再有内容: {cmd!r}")
    return DtProgram(addr=addr, toks=tuple(toks), terminator=terminator)


def serialize(program: DtProgram) -> str:
    """DtProgram -> DT 指令串 (parse 的精确逆)。"""
    if program.addr is None:
        return ""
    parts = [f"/{program.addr}"]
    for tok in program.toks:
        if tok.code in _VALUE_CODES:
            parts.append(f"{tok.code}{tok.value}")
        elif tok.code == "Z":
            a, b, c = tok.triple  # type: ignore[misc]
            parts.append(f"Z{a},{b},{c}")
        else:
            parts.append(tok.code)
    parts.append(program.terminator)
    return "".join(parts)


# ---------------------------------------------------------------------------
# 运动段 (机械推导, 无语义): 供虚拟泵按串执行 / 对账 plan 的语义段
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DtSegment:
    """一段柱塞运动: A(abs 绝对步位) 或 P(rel 相对增量), 携带当时生效的 V/I 与后随 M。"""
    kind: str                      # 'abs' | 'rel'
    steps: int
    port: int | None
    speed: int | None
    delay_ms: int | None


def motion_segments(program: DtProgram) -> tuple[DtSegment, ...]:
    """从 DtProgram 机械抽取柱塞运动段序列 (不判吸/排方向 —— 方向属语义层)。"""
    segments: list[DtSegment] = []
    speed: int | None = None
    port: int | None = None
    for index, tok in enumerate(program.toks):
        if tok.code == "V":
            speed = tok.value
        elif tok.code == "I":
            port = tok.value
        elif tok.code in ("A", "P"):
            delay = None
            nxt = program.toks[index + 1] if index + 1 < len(program.toks) else None
            if nxt is not None and nxt.code == "M":
                delay = nxt.value
            segments.append(DtSegment(
                kind="abs" if tok.code == "A" else "rel",
                steps=int(tok.value or 0), port=port, speed=speed, delay_ms=delay))
    return tuple(segments)


# ---------------------------------------------------------------------------
# 语义层: PumpPlan
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanSegment:
    """一段柱塞运动的语义描述。

    op: 'aspirate'(柱塞上行, 吸) | 'dispense'(下行, 排) —— 由 translator 按
        工艺语义声明, 不从步数推断 (abs 目标的方向取决于起点, 串里没有起点)。
    kind/steps: 同 DtSegment; ml 为 steps 按该泵量程换算的 mL (abs=绝对位, rel=增量)。
    speed_key: 速度的**语义参数名** (asp_speed/flush_disp_speed/...), 三维漂移
        门禁用它对账手写相位表的 speed 字段。
    """
    op: str
    kind: str
    steps: int
    ml: float
    port: int | None
    speed: int
    speed_key: str
    delay_ms: int | None


@dataclass(frozen=True)
class PlanEntry:
    """一条 DT 指令串 + 其语义段序列 (段序与串内 A/P 次序一一对应)。"""
    program: DtProgram
    segments: tuple[PlanSegment, ...] = ()
    note: str = ""

    def command(self) -> str:
        return serialize(self.program)


@dataclass(frozen=True)
class PumpPlan:
    """一个泵动作的完整指令计划 (entry 序 = PLC 消费序)。"""
    entries: tuple[PlanEntry, ...]

    def commands(self) -> list[str]:
        return [entry.command() for entry in self.entries]

    def flat_segments(self) -> tuple[PlanSegment, ...]:
        out: list[PlanSegment] = []
        for entry in self.entries:
            out.extend(entry.segments)
        return tuple(out)


EMPTY_ENTRY = PlanEntry(program=DtProgram(addr=None))   # 数组空串占位 ("")


# ---------------------------------------------------------------------------
# 构串器: translator 侧唯一的字符串产地
# ---------------------------------------------------------------------------
class CmdBuilder:
    """按 DT 语法逐 token 组装一条运行串, 同步登记语义段。

    用法 (与 f-string 时代逐字节等价, 由金测试背书):
        entry = (CmdBuilder(addr, steps_per_ml=240.0)
                 .speed(asp, "asp_speed").port(1).move_abs(6000, op="aspirate", delay_ms=d)
                 .speed(disp, "disp_speed").port(3).move_abs(0, op="dispense", delay_ms=d)
                 .entry(note="内壁清洗"))
    speed()/port() 都是显式发 token —— 同值重复调用也重复出 V/I (与历史串一致)。
    """

    def __init__(self, addr: str, *, steps_per_ml: float) -> None:
        self._addr = addr
        self._steps_per_ml = float(steps_per_ml)
        self._toks: list[DtTok] = []
        self._segments: list[PlanSegment] = []
        self._speed: int | None = None
        self._speed_key: str = ""
        self._port: int | None = None

    def speed(self, value: int, key: str) -> "CmdBuilder":
        self._speed = int(value)
        self._speed_key = key
        self._toks.append(DtTok("V", value=int(value)))
        return self

    def port(self, value: int) -> "CmdBuilder":
        self._port = int(value)
        self._toks.append(DtTok("I", value=int(value)))
        return self

    def _move(self, code: str, steps: int, op: str, delay_ms: int) -> "CmdBuilder":
        if self._speed is None:
            raise ValueError("柱塞运动段前必须先 speed() —— DT 串无默认速度")
        steps = int(steps)
        self._toks.append(DtTok(code, value=steps))
        self._toks.append(DtTok("M", value=int(delay_ms)))
        self._segments.append(PlanSegment(
            op=op, kind="abs" if code == "A" else "rel", steps=steps,
            ml=steps / self._steps_per_ml, port=self._port,
            speed=self._speed, speed_key=self._speed_key, delay_ms=int(delay_ms)))
        return self

    def move_abs(self, steps: int, *, op: str, delay_ms: int) -> "CmdBuilder":
        """A{steps}M{delay}: 柱塞移到绝对步位。op 按工艺语义传 'aspirate'/'dispense'。"""
        return self._move("A", steps, op, delay_ms)

    def move_rel(self, steps: int, *, op: str, delay_ms: int) -> "CmdBuilder":
        """P{steps}M{delay}: 柱塞相对增量 (仅上行语义, PLC 持真位置做行程闸)。"""
        return self._move("P", steps, op, delay_ms)

    def entry(self, note: str = "") -> PlanEntry:
        """收尾: 补 R 执行 token 与 '\\r', 产出 PlanEntry。"""
        toks = tuple(self._toks) + (DtTok("R"),)
        return PlanEntry(
            program=DtProgram(addr=self._addr, toks=toks, terminator="\r"),
            segments=tuple(self._segments), note=note)
