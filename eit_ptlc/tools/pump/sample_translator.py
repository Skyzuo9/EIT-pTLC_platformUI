"""上样注射泵气泡分段清洗策略指令翻译器

将用户输入（液柱体积、气泡体积、周期数）翻译为 SY-03B (T-04) 注射泵 DT 协议指令序列。

硬件规格：
    - SY-03B 注射泵 (25mL / 6000步) + T-04 阀头（4 通道分配型流路）
    - 外部三通阀（独立控制，不在本脚本范围）

策略：
    利用长管路（体积 > 25mL）暂存预制的 [清洗液-气泡-清洗液-气泡-...] 分段结构。
    上样时泵吸入纯清洗液尾段，样品从管路前端进入；点样时样品先出，分段清洗液
    在后方润洗管路。

端口映射（T-04）：
    端口 1：清洗液
    端口 2：废液
    端口 3：输出 → 三通阀 → 上样/点样流路
    端口 4：空气（直通大气）
    公共端 C：注射泵

协议：DT (Data Terminal) 协议

参考文档：docs/sample_bubble_strategy.md
"""

from __future__ import annotations

from eit_ptlc.tools.pump.dt_codec import CmdBuilder, PlanEntry

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
# T-04 分配阀端口（4通道）
T04_WASH_PORT = 1          # 清洗液端口
T04_WASTE_PORT = 2         # 废液端口
T04_OUTPUT_PORT = 3        # 输出口 → 三通阀
T04_AIR_PORT = 4           # 空气端口（直通大气）

# 默认使用 T-04
WASH_PORT = T04_WASH_PORT
AIR_PORT = T04_AIR_PORT
OUTPUT_PORT = T04_OUTPUT_PORT
WASTE_PORT = T04_WASTE_PORT

SYRINGE_STEPS = 6000       # 25mL 满行程步数
SYRINGE_ML = 25.0          # 注射泵量程

# 上样注射泵站号（DT 协议地址，对应硬件拨码）
SAMPLE_PUMP_ADDR = "4"      # 泵 4（上样注射泵）

ASP_SPEED = 250           # 吸液速度
DISP_SPEED = 100           # 打液速度（上限 500）
STEP_DELAY = 1500           # 步骤间延迟 (ms)

TAIL_VOLUME_ML = 26.0      # 纯清洗液尾段体积（必须 > SYRINGE_ML）


# ---------------------------------------------------------------------------
# 体积 → 步数
# ---------------------------------------------------------------------------
def _ml_to_steps(volume_ml: float, syringe_ml: float = SYRINGE_ML) -> int:
    """毫升转绝对步数。"""
    return int(round(volume_ml * SYRINGE_STEPS / syringe_ml))


# ---------------------------------------------------------------------------
# 指令构建 (plan-first: 结构化 plan_* 是唯一产地, build_* 是其序列化壳)
#
# 仿真模块阶段①"泵链路归真": DT 字符串与三维动画相位必须同源。plan_* 返回
# dt_codec.PlanEntry —— 逐段柱塞运动带 吸/排语义、端口、速度语义键(参数名) 与
# mL 换算; build_* 仅做 .command() 序列化, 输出逐字节不变
# (tests/test_pump_dt_golden_offline.py 冻结)。
# speed_key 缺省即本站通用档参数名; 上层按工艺覆写 (如 flush_disp_speed)。
# ---------------------------------------------------------------------------
def _steps_per_ml(syringe_ml: float = SYRINGE_ML) -> float:
    """该泵量程下的 步/mL (25mL/6000步 -> 240)。"""
    return SYRINGE_STEPS / syringe_ml


def plan_segment_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    *,
    asp_speed_key: str = "asp_speed",
    disp_speed_key: str = "disp_speed",
    note: str = "",
) -> PlanEntry:
    """"吸→打"复合指令的结构化计划 (build_segment_cmd 的语义源)。"""
    steps = _ml_to_steps(volume_ml)
    return (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
        .speed(asp_speed, asp_speed_key).port(src_port)
        .move_abs(steps, op="aspirate", delay_ms=step_delay)
        .speed(disp_speed, disp_speed_key).port(output_port)
        .move_abs(0, op="dispense", delay_ms=step_delay)
        .entry(note=note)
    )


def build_segment_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
) -> str:
    """构建一条"吸→打"复合指令：从 src_port 吸 volume_ml，切输出口打出。

    复合指令原子执行：设置吸速 → 切源口 → 吸至绝对位置 → 设打速 → 切输出口 → 归零。
    泵腔在指令结束后为空（A0），可直接用于下一段吸气泡。
    """
    return plan_segment_cmd(
        volume_ml, src_port, pump_addr, asp_speed, disp_speed, step_delay,
        output_port,
    ).command()


def plan_aspirate_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    *,
    speed_key: str = "asp_speed",
    op: str = "aspirate",
    note: str = "",
) -> PlanEntry:
    """纯吸液指令的结构化计划 (build_aspirate_cmd 的语义源)。"""
    steps = _ml_to_steps(volume_ml)
    return (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
        .speed(asp_speed, speed_key).port(src_port)
        .move_abs(steps, op=op, delay_ms=step_delay)
        .entry(note=note)
    )


def build_aspirate_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
) -> str:
    """构建纯吸液指令（不打出）。用于 Phase 3 上样。"""
    return plan_aspirate_cmd(
        volume_ml, src_port, pump_addr, asp_speed, step_delay,
    ).command()


def plan_relative_aspirate_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    *,
    syringe_ml: float = SYRINGE_ML,
    speed_key: str = "asp_speed",
    note: str = "",
) -> PlanEntry:
    """相对吸液指令 ``P<n>`` 的结构化计划 (build_relative_aspirate_cmd 的语义源)。"""
    if volume_ml <= 0 or volume_ml > syringe_ml:
        raise ValueError(f"相对吸液体积必须在 (0, {syringe_ml}] mL，收到 {volume_ml} mL")
    steps = _ml_to_steps(volume_ml, syringe_ml)
    return (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml(syringe_ml))
        .speed(asp_speed, speed_key).port(src_port)
        .move_rel(steps, op="aspirate", delay_ms=step_delay)
        .entry(note=note)
    )


def build_relative_aspirate_cmd(
    volume_ml: float,
    src_port: int,
    pump_addr: str = "1",
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    *,
    syringe_ml: float = SYRINGE_ML,
) -> str:
    """构建相对吸液指令 ``P<n>``（当前位置增加 n 步）。

    ``P`` 只表达增量；运行时的 ``当前位置 + n <= 6000`` 必须由 PLC
    在持有泵通信槽时查询真实活塞位置后再次校验。
    """
    return plan_relative_aspirate_cmd(
        volume_ml, src_port, pump_addr, asp_speed, step_delay,
        syringe_ml=syringe_ml,
    ).command()


def plan_dispense_all_cmd(
    pump_addr: str = "1",
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    *,
    end_steps: int = 0,
    speed_key: str = "disp_speed",
    note: str = "",
) -> PlanEntry:
    """全打液指令的结构化计划 (build_dispense_all_cmd 的语义源)。"""
    return (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
        .speed(disp_speed, speed_key).port(output_port)
        .move_abs(end_steps, op="dispense", delay_ms=step_delay)
        .entry(note=note)
    )


def build_dispense_all_cmd(
    pump_addr: str = "1",
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    *,
    end_steps: int = 0,
) -> str:
    """构建全打液指令（打到绝对位 end_steps, 缺省 0=归零）。用于 Phase 4 点样。

    end_steps > 0 用于点样死体积补偿: 活塞停在 N 保留纯驱动液不点到板上
    (spec 2026-07-14-spot-end-position)。
    """
    return plan_dispense_all_cmd(
        pump_addr, disp_speed, step_delay, output_port, end_steps=end_steps,
    ).command()


# ---------------------------------------------------------------------------
# 核心翻译函数
# ---------------------------------------------------------------------------
def translate_sample_bubble_cmd(
    liquid_volume_ml: float,
    bubble_volume_ml: float,
    num_cycles: int,
    *,
    pump_addr: str = "1",
    tail_volume_ml: float = TAIL_VOLUME_ML,
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """生成气泡分段上样完整 DT 指令序列。

    Phase 1: 逐段制备 [清洗液-气泡]×N 分段柱（管路中）
    Phase 2: 补纯清洗液尾段（>25mL，保证上样时泵腔只吸入纯液）
    Phase 3: 上样吸液（从输出口吸满泵腔；三通阀 → A，外部切换）
    Phase 4: 点样打液（从输出口全部打出；三通阀 → B，外部切换）

    Args:
        liquid_volume_ml: 每段清洗液体积 (mL)，范围 (0, syringe_ml]
        bubble_volume_ml: 每段气泡体积 (mL)，范围 (0, syringe_ml]
        num_cycles: 气-液循环次数
        pump_addr: DT 协议地址，默认 '1'
        tail_volume_ml: 纯清洗液尾段总体积 (mL)，必须 > syringe_ml
        syringe_ml: 注射泵量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度（上限 500）
        step_delay: 步骤间延迟 (ms)
        wash_port: 清洗液端口号
        air_port: 空气端口号
        output_port: 输出端口号

    Returns:
        DT 协议指令字符串列表，按执行顺序排列。

    Raises:
        ValueError: 参数超出合法范围
    """
    if liquid_volume_ml <= 0 or liquid_volume_ml > syringe_ml:
        raise ValueError(
            f"液柱体积必须在 0-{syringe_ml} mL 之间，收到 {liquid_volume_ml}"
        )
    if bubble_volume_ml <= 0 or bubble_volume_ml > syringe_ml:
        raise ValueError(
            f"气泡体积必须在 0-{syringe_ml} mL 之间，收到 {bubble_volume_ml}"
        )
    if num_cycles <= 0:
        raise ValueError(f"循环次数必须 > 0，收到 {num_cycles}")
    if tail_volume_ml <= syringe_ml:
        raise ValueError(
            f"尾段体积必须 > {syringe_ml} mL，收到 {tail_volume_ml}"
        )
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    commands: list[str] = []

    # ---- Phase 1: 制备气-液分段柱 ----
    # 每段：从源口吸 → 从输出口打出。打出后泵腔为空，满足下一次吸气泡条件。
    for _ in range(num_cycles):
        commands.append(
            build_segment_cmd(liquid_volume_ml, wash_port,
                               pump_addr, asp_speed, disp_speed, step_delay,
                               output_port)
        )
        commands.append(
            build_segment_cmd(bubble_volume_ml, air_port,
                               pump_addr, asp_speed, disp_speed, step_delay,
                               output_port)
        )

    # ---- Phase 2: 补纯清洗液尾段 ----
    # 总体积 > 25mL，需拆分多个满行程
    remaining = tail_volume_ml
    while remaining > 0:
        vol = min(remaining, syringe_ml)
        commands.append(
            build_segment_cmd(vol, wash_port,
                               pump_addr, asp_speed, disp_speed, step_delay,
                               output_port)
        )
        remaining -= vol

    # ---- Phase 3: 上样 ----
    # 三通阀 → A（上样流路），由外部控制
    commands.append(
        build_aspirate_cmd(syringe_ml, output_port,
                            pump_addr, asp_speed, step_delay)
    )

    # ---- Phase 4: 点样 ----
    # 三通阀 → B（点样流路），由外部控制
    commands.append(
        build_dispense_all_cmd(pump_addr, disp_speed, step_delay, output_port)
    )

    return commands


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------
def calc_total_prep_volume(
    liquid_volume_ml: float,
    bubble_volume_ml: float,
    num_cycles: int,
    tail_volume_ml: float = TAIL_VOLUME_ML,
) -> float:
    """计算总制备体积（Phase 1 + Phase 2）。

    与管路体积做对比，判断管路预充是否完全：
        - 总制备体积 >= 管路体积 → 空气全排出，分段前端可预期
        - 总制备体积 <  管路体积 → 前端残留空气

    Returns:
        总制备体积 (mL)
    """
    segment_total = (liquid_volume_ml + bubble_volume_ml) * num_cycles
    return segment_total + tail_volume_ml


def pump_init_cmd(
    pump_addr: str = "1",
    init_speed: int = 0,
    input_port: int = 0,
    output_port: int = OUTPUT_PORT,
) -> str:
    """生成 SY-03B (T-04) 泵 Z 初始化指令。

    Z<n1,n2,n3> 顺时针初始化活塞驱动和阀门：
      n1 = 初始化活塞力度/速度（0=满力度/默认1400脉冲每秒）
      n2 = 初始化输入端口（0=默认）
      n3 = 初始化输出端口（T-04=3, T-06=6）

    初始化后需通过 Q 指令确认初始化成功（PLC pumpCmd FB 自动完成）。

    Args:
        pump_addr: SY-03B 泵 DT 协议地址
        init_speed: 初始化力度/速度（0=满力度）
        input_port: 初始化输入端口（0=默认）
        output_port: 初始化输出端口（T-04=3）

    Returns:
        DT 协议初始化指令字符串
    """
    return f"/{pump_addr}Z{init_speed},{input_port},{output_port}R$R"


def pump_query_cmd(pump_addr: str = "1") -> str:
    """生成 SY-03B (T-04) 泵状态查询指令。"""
    return f"/{pump_addr}Q$R"


# ---------------------------------------------------------------------------
# 命令行预览
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    # 默认示例参数
    liquid = 2.0
    bubble = 1.0
    cycles = 3

    if len(sys.argv) >= 4:
        liquid = float(sys.argv[1])
        bubble = float(sys.argv[2])
        cycles = int(sys.argv[3])

    cmds = translate_sample_bubble_cmd(liquid, bubble, cycles,
                                        wash_port=WASH_PORT,
                                        air_port=AIR_PORT,
                                        output_port=OUTPUT_PORT)
    prep_vol = calc_total_prep_volume(liquid, bubble, cycles)

    print(f"# 参数: 液柱={liquid}mL, 气泡={bubble}mL, 周期={cycles}")
    print(f"# 总制备体积: {prep_vol:.1f} mL")
    print(f"# 指令数: {len(cmds)}")
    print()

    import math
    seg_per_cycle = 2  # 每周期 2 条（液+气）
    phase1_end = cycles * seg_per_cycle
    tail_cmds = math.ceil(TAIL_VOLUME_ML / SYRINGE_ML)
    phase2_end = phase1_end + tail_cmds

    for i, cmd in enumerate(cmds):
        if i < phase1_end:
            seg_type = "L" if i % 2 == 0 else "G"
            cyc = i // 2 + 1
            label = f"Phase1 seg={seg_type} cyc={cyc}"
        elif i < phase2_end:
            label = "Phase2 tail"
        elif i == phase2_end:
            label = "Phase3 load"
        else:
            label = "Phase4 spot"

        print(f"[{i:02d}] {label}")
        print(f"    {cmd}")
        print()
