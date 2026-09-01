"""上样注射泵 v2 空气驱动点样策略指令翻译器

将用户输入（样品体积、安全余量、清洗体积）翻译为 SY-03B (T-04) 注射泵 DT 协议指令序列。

硬件规格：
    - SY-03B 注射泵 (25mL / 6000步) + T-04 阀头（4 通道分配型流路）
    - 外部三通阀（独立控制，不在本脚本范围）

历史一体序列（``translate_sample_v2_cmd`` / ``sampling.spot`` 兼容保留）：
    利用长管路（体积 > 25mL）暂存样品，泵腔内仅处理清洗液和空气。
    样品始终停留在管路中，由空气段驱动进入点样流路，避免样品进入泵腔造成交叉污染。

    Step 1: 清洗 — 从清洗液口吸入 wash_vol mL，从输出口打出（PLC 控制循环次数）
    Step 2: 回抽空气 — 从输出口吸入 air_buffer mL 空气（上样针在空气中，建立隔离段）
    Step 3: 吸取样品 — 从输出口吸入 sample_vol mL 样品（上样针入样品液面）
    Step 4: 排废液 — 将泵腔内全部液体/空气从废液口打出（清空泵腔）
    Step 5: 驱动空气 — 从空气口吸入 sample_vol mL 空气（驱动段）
    Step 6: 点样打出 — 将驱动空气从输出口打出，推动管路中样品进入点样流路

关键原则：
    - 样品始终在管路中（>25mL），不进入泵腔
    - 泵腔仅处理清洗液和空气，杜绝交叉污染
    - 安全空气隔离段 (air_buffer) 防止样品进入泵腔，保证点样精度

当前 L2 活动路径（``sampling.prep -> sampling.aspirate -> sampling.spot_band_layer``）：
    - prep 从已清洗输出管路绝对回抽并保留驱动清洗液，不再 A0 排废
    - aspirate 用 P<n> 在当前活塞位上相对叠加样品，PLC 以真位置做 6000 步行程闸
    - spot_band_layer 分程向 A0 打出，直至真活塞位回到 0

端口映射（T-04 四通道分配阀）：
    端口 1（WASH_PORT）：清洗液
    端口 2（WASTE_PORT）：废液
    端口 3（OUTPUT_PORT）：输出 → 三通阀 → 上样/点样流路
    端口 4（AIR_PORT）：空气（直通大气）
    公共端 C：注射泵

DT 协议参考：
    - 吸液指令：/1V{speed}I{port}A{steps}M{delay}R
    - 打液归零：/1V{speed}I{port}A0M{delay}R
    - 复合指令（吸→打）：吸至绝对位置 A{steps}，再从输出口归零
    - 速度上限：disp_speed <= 500

参考文档：docs/sample_bubble_strategy.md
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 从 v1 导入基础构建模块 (移植: 包内绝对导入)
# ---------------------------------------------------------------------------
from eit_ptlc.tools.pump.dt_codec import EMPTY_ENTRY, CmdBuilder, PlanEntry, PumpPlan
from eit_ptlc.tools.pump.sample_translator import (
    # 常量
    T04_WASH_PORT,
    T04_WASTE_PORT,
    T04_OUTPUT_PORT,
    T04_AIR_PORT,
    SYRINGE_STEPS,
    SYRINGE_ML,
    SAMPLE_PUMP_ADDR,
    ASP_SPEED,
    DISP_SPEED,
    STEP_DELAY,
    # 指令构建函数
    build_segment_cmd,
    build_aspirate_cmd,
    build_relative_aspirate_cmd,
    build_dispense_all_cmd,
    # 结构化计划 (plan-first, 阶段①泵链路归真)
    plan_segment_cmd,
    plan_aspirate_cmd,
    plan_relative_aspirate_cmd,
    plan_dispense_all_cmd,
    _steps_per_ml,
    # 辅助函数
    pump_init_cmd,
    pump_query_cmd,
    _ml_to_steps,
)

# ---------------------------------------------------------------------------
# v2 常量
# ---------------------------------------------------------------------------
WASH_PORT = T04_WASH_PORT       # 端口 1：清洗液
WASTE_PORT = T04_WASTE_PORT     # 端口 2：废液
OUTPUT_PORT = T04_OUTPUT_PORT   # 端口 3：输出口 → 三通阀
AIR_PORT = T04_AIR_PORT         # 端口 4：空气

DEFAULT_AIR_BUFFER_ML = 3.0    # 默认空气隔离段体积 (mL)，Step 2 回抽空气，与样品体积无关
DEFAULT_WASH_ML = 25.0          # 默认清洗体积 (mL)
DEFAULT_PUMP_ADDR = SAMPLE_PUMP_ADDR  # 默认上样泵站号（泵 4）
DEFAULT_RETRACT_ML = 1.0        # 默认点样后回抽体积 (mL)，释放点样器/公共腔正压
DEFAULT_DISPENSE_DISP_SPEED = 50  # 点样打液速度（0 = 跟随 disp_speed，>0 则独立控制 Step 6）

DEFAULT_RINSE_AIR_GAP_ML = 0.2     # 润洗混匀: 抬针后吸入的气隔断体积, 隔离混合液与共管清洗液柱

DEFAULT_FLUSH_ML = 17.0            # 轻清洗: 上样流路充液体积 (泵→三通 loop 环 15.7 实测 + 针流路 1.125 ≈ 16.8mL 的 1.01×)
DEFAULT_OUTER_WASH_ML = 5.0        # 轻清洗: 针外壁清洗体积 (外壁流路 2-4mL)
DEFAULT_SPOT_HEAD_ML = 3.0         # 轻清洗: 点样头清洗体积
FLUSH_DISP_SPEED = 300             # 轻清洗充液/外壁打速 (偏高冲刷贴壁气泡; 守卫上限 500)
FLUSH_SPOT_HEAD_DISP_SPEED = 100   # 轻清洗点样头打速


# ---------------------------------------------------------------------------
# 参数验证
# ---------------------------------------------------------------------------
def validate_sample_v2_params(
    sample_volume_ml: float,
    air_buffer_ml: float,
    wash_volume_ml: float,
    syringe_ml: float = SYRINGE_ML,
) -> None:
    """验证 v2 空气驱动策略参数合法性。

    Args:
        sample_volume_ml: 样品体积 (mL)，必须 > 0
        air_buffer_ml: 空气隔离段体积 (mL)，必须 > 0
        wash_volume_ml: 清洗体积 (mL)，必须在 (0, syringe_ml] 范围内
        syringe_ml: 注射泵量程 (mL)

    Raises:
        ValueError: 参数超出合法范围（中文错误信息）
    """
    if sample_volume_ml <= 0:
        raise ValueError(f"样品体积必须 > 0，收到 {sample_volume_ml} mL")

    if air_buffer_ml <= 0:
        raise ValueError(f"空气隔离段体积必须 > 0，收到 {air_buffer_ml} mL")

    if wash_volume_ml <= 0 or wash_volume_ml > syringe_ml:
        raise ValueError(
            f"清洗体积必须在 (0, {syringe_ml}] mL 范围内，收到 {wash_volume_ml} mL"
        )

    peak_ml = air_buffer_ml + sample_volume_ml
    if peak_ml > syringe_ml:
        raise ValueError(
            f"泵腔峰值体积 {peak_ml:.1f} mL 超出注射泵量程 {syringe_ml} mL"
            f"（空气隔离 {air_buffer_ml} mL + 样品 {sample_volume_ml} mL"
            f" = {peak_ml:.1f} mL > {syringe_ml} mL）"
        )


# ---------------------------------------------------------------------------
# 体积预算
# ---------------------------------------------------------------------------
def calc_v2_volume_budget(
    sample_volume_ml: float,
    air_buffer_ml: float = DEFAULT_AIR_BUFFER_ML,
    retract_volume_ml: float = 0.0,
) -> dict:
    """计算 v2 各步骤体积预算。

    Args:
        sample_volume_ml: 样品体积 (mL)
        air_buffer_ml: 空气隔离段体积 (mL)，默认 3.0 mL
        retract_volume_ml: 点样后回抽体积 (mL)，默认 0（不回抽）

    Returns:
        dict，包含以下键：
            step2_air_ml: Step 2 回抽空气体积 (mL)
            step3_sample_ml: Step 3 吸取样品体积 (mL)
            step4_waste_ml: Step 4 排废液体积 (mL)
            step5_drive_air_ml: Step 5 驱动空气体积 (mL)
            step6_dispense_ml: Step 6 点样打出体积 (mL)
            step7_retract_ml: Step 7 回抽释压体积 (mL)
            peak_pump_ml: 泵腔峰值体积 (mL)
    """
    step2_air_ml = air_buffer_ml
    step3_sample_ml = sample_volume_ml
    step4_waste_ml = air_buffer_ml + sample_volume_ml
    step5_drive_air_ml = sample_volume_ml
    step6_dispense_ml = sample_volume_ml  # 驱动空气推出等体积样品
    step7_retract_ml = retract_volume_ml  # 点样后回抽释压
    peak_pump_ml = step4_waste_ml  # 峰值在 Step 4，不受回抽影响

    return {
        "step2_air_ml": step2_air_ml,
        "step3_sample_ml": step3_sample_ml,
        "step4_waste_ml": step4_waste_ml,
        "step5_drive_air_ml": step5_drive_air_ml,
        "step6_dispense_ml": step6_dispense_ml,
        "step7_retract_ml": step7_retract_ml,
        "peak_pump_ml": peak_pump_ml,
    }


# ---------------------------------------------------------------------------
# 核心翻译函数
# ---------------------------------------------------------------------------
def translate_sample_v2_cmd(
    sample_volume_ml: float,
    *,
    air_buffer_ml: float = DEFAULT_AIR_BUFFER_ML,
    wash_volume_ml: float = DEFAULT_WASH_ML,
    retract_volume_ml: float = DEFAULT_RETRACT_ML,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    dispense_disp_speed: int = 0,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """生成历史 v2 空气驱动点样完整 DT 指令序列（7 步，兼容保留）。

    当前 L2 活动路径不调用本函数，而使用 ``build_prep_array``、
    ``build_sample_array`` 与 ``build_spot_band_run_cmd`` 的拆分契约。

    Step 1: 清洗 — 复合指令从清洗口吸 wash_vol，输出口打出（PLC 控制循环）
    Step 2: 回抽空气 — 从输出口吸 air_buffer mL（上样针在空气中，建立隔离段）
    Step 3: 吸取样品 — 从输出口吸 sample_vol mL（上样针进入样品液面）
    Step 4: 排废液 — 全打出至废液口（清空泵腔）
    Step 5: 驱动空气 — 从空气口吸 sample_vol mL（驱动空气段）
    Step 6: 点样打出 — 全打出至输出口（驱动空气推样品进入点样流路）
    Step 7: 回抽释压 — 从输出口回抽 retract_vol mL（释放点样器/公共腔正压）

    Step 2 空气隔离段物理意义：在上样针仍在空气中时吸入固定体积空气，
    在泵柱塞和即将吸入的样品之间建立隔离屏障，防止样品进入泵腔。
    该体积与样品体积无关，固定值即可满足隔离需求。

    Step 7 物理意义：点样完成后分配阀仍指向点样器，注射泵反抽一小段空气，
    在点样器/公共腔端产生负压，消除残留正压导致的滴液风险。
    回抽完成后 PLC 才将分配阀切回上样针。

    Args:
        sample_volume_ml: 样品体积 (mL)，必须 > 0
        air_buffer_ml: 空气隔离段体积 (mL)，默认 3.0 mL
        wash_volume_ml: 清洗体积 (mL)，默认 25.0 mL，范围 (0, syringe_ml]
        retract_volume_ml: 回抽体积 (mL)，默认 1.0 mL，0 则跳过回抽
        pump_addr: DT 协议地址，默认 '4'（上样泵站号）
        syringe_ml: 注射泵量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度（上限 500），用于 Step 1/4 等非点样步骤
        dispense_disp_speed: 点样打液速度（上限 500），仅用于 Step 6 点样打出。
            默认 0 表示与 disp_speed 相同（向后兼容）
        step_delay: 步骤间延迟 (ms)
        wash_port: 清洗液端口号
        waste_port: 废液端口号
        air_port: 空气端口号
        output_port: 输出端口号

    Returns:
        DT 协议指令字符串列表（6 或 7 条），按执行顺序排列。

    Raises:
        ValueError: 参数超出合法范围
    """
    # 验证打液速度
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    # 解析点样打液速度：0 表示跟随 disp_speed
    _spot_disp_speed = dispense_disp_speed if dispense_disp_speed > 0 else disp_speed
    if _spot_disp_speed > 500:
        raise ValueError(f"点样打液速度不能超过 500，收到 {_spot_disp_speed}")

    # 验证参数
    validate_sample_v2_params(
        sample_volume_ml, air_buffer_ml, wash_volume_ml, syringe_ml
    )

    commands: list[str] = []

    # ---- Step 1: 清洗（复合吸→打，PLC 控制循环） ----
    commands.append(
        build_segment_cmd(
            wash_volume_ml, wash_port,
            pump_addr, asp_speed, disp_speed, step_delay,
            output_port,
        )
    )

    # ---- Step 2: 回抽空气（上样针在空气中，建立隔离段） ----
    commands.append(
        build_aspirate_cmd(
            air_buffer_ml, output_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 3: 吸取样品（上样针进入样品液面） ----
    commands.append(
        build_aspirate_cmd(
            sample_volume_ml, output_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 4: 排废液（全打出至废液口） ----
    commands.append(
        build_dispense_all_cmd(
            pump_addr, disp_speed, step_delay, waste_port,
        )
    )

    # ---- Step 5: 驱动空气（从空气口吸入） ----
    commands.append(
        build_aspirate_cmd(
            sample_volume_ml, air_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 6: 点样打出（全打出至输出口，使用点样专用打液速度） ----
    commands.append(
        build_dispense_all_cmd(
            pump_addr, _spot_disp_speed, step_delay, output_port,
        )
    )

    # ---- Step 7: 回抽释压（分配阀仍指向点样器，反抽释放正压） ----
    if retract_volume_ml > 0:
        commands.append(
            build_aspirate_cmd(
                retract_volume_ml, output_port,
                pump_addr, asp_speed, step_delay,
            )
        )

    return commands


# ---------------------------------------------------------------------------
# 4 数组构建函数（协议 v1.5：每步消费一个 1×2 STRING 数组）
#
# plan-first (阶段①泵链路归真): 每个 build_*_array 的结构与数值唯一产地是同名
# plan_*_array (返回 dt_codec.PumpPlan, 语义段带 吸/排/端口/速度参数名/mL);
# build_* 只序列化, 输出逐字节冻结于 tests/test_pump_dt_golden_offline.py。
# 三维演示相位表与行为级虚拟泵都以 plan 为真源, 不再各抄一份。
# ---------------------------------------------------------------------------
def plan_clean_array(
    wash_volume_ml: float,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """清洗数组的结构化计划 (build_clean_array 的语义源)。"""
    return PumpPlan(entries=(
        plan_segment_cmd(
            wash_volume_ml, wash_port,
            pump_addr, asp_speed, disp_speed, step_delay,
            output_port, note="内壁清洗"),
        plan_segment_cmd(
            wash_volume_ml, wash_port,
            pump_addr, asp_speed, disp_speed, step_delay,
            waste_port, note="外壁清洗"),
    ))


def build_clean_array(
    wash_volume_ml: float,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """清洗数组 [内壁清洗, 外壁清洗]（Step 10 消费）。

    [1] 内壁清洗：从清洗液口吸入 wash_vol → 输出口打出（冲洗管路内壁）
    [2] 外壁清洗：从清洗液口吸入 wash_vol → 废液口打出（冲洗上样针外壁）
    """
    return plan_clean_array(
        wash_volume_ml, pump_addr=pump_addr, asp_speed=asp_speed,
        disp_speed=disp_speed, step_delay=step_delay, wash_port=wash_port,
        waste_port=waste_port, output_port=output_port,
    ).commands()


def plan_flush_array(
    flush_volume_ml: float = DEFAULT_FLUSH_ML,
    outer_wash_volume_ml: float = DEFAULT_OUTER_WASH_ML,
    spot_head_volume_ml: float = DEFAULT_SPOT_HEAD_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    flush_disp_speed: int = FLUSH_DISP_SPEED,
    spot_head_disp_speed: int = FLUSH_SPOT_HEAD_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """轻清洗充液数组的结构化计划 (build_flush_array 的语义源)。"""
    for label, v in (("上样流路充液", flush_volume_ml),
                     ("针外壁清洗", outer_wash_volume_ml),
                     ("点样头清洗", spot_head_volume_ml)):
        if v <= 0:
            raise ValueError(f"{label}体积必须 > 0，收到 {v} mL")
    for label, v in (("充液/外壁打液速度", flush_disp_speed),
                     ("点样头打液速度", spot_head_disp_speed)):
        if v > 500:
            raise ValueError(f"{label}不能超过 500，收到 {v}")

    n_flush = _ml_to_steps(flush_volume_ml)
    n_outer = _ml_to_steps(outer_wash_volume_ml)
    n_spot = _ml_to_steps(spot_head_volume_ml)
    total = n_flush + n_outer + n_spot
    if total > SYRINGE_STEPS:
        raise ValueError(
            f"三段体积之和 {flush_volume_ml + outer_wash_volume_ml + spot_head_volume_ml:.1f} mL"
            f" 超出注射泵量程 {SYRINGE_ML} mL"
        )
    p1 = total - n_flush
    p2 = p1 - n_outer
    chained = (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
        .speed(asp_speed, "asp_speed").port(wash_port)
        .move_abs(total, op="aspirate", delay_ms=step_delay)
        .speed(flush_disp_speed, "flush_disp_speed").port(output_port)
        .move_abs(p1, op="dispense", delay_ms=step_delay)
        .speed(flush_disp_speed, "flush_disp_speed").port(waste_port)
        .move_abs(p2, op="dispense", delay_ms=step_delay)
        .entry(note="链式三合一: 吸满→充上样流路→冲外壁")
    )
    spot_head = plan_dispense_all_cmd(
        pump_addr, spot_head_disp_speed, step_delay, output_port,
        speed_key="spot_head_disp_speed", note="冲点样头至A0")
    return PumpPlan(entries=(chained, spot_head))


def build_flush_array(
    flush_volume_ml: float = DEFAULT_FLUSH_ML,
    outer_wash_volume_ml: float = DEFAULT_OUTER_WASH_ML,
    spot_head_volume_ml: float = DEFAULT_SPOT_HEAD_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    flush_disp_speed: int = FLUSH_DISP_SPEED,
    spot_head_disp_speed: int = FLUSH_SPOT_HEAD_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """轻清洗充液数组 [吸满+充上样流路+冲外壁(链式), 冲点样头至A0](clean mode=1 消费)。

    [1] 链式三合一: 自清洗口吸满(=三段之和) → 充液上样流路(高速冲刷贴壁气泡)
        → 冲针外壁(废液口)。三步间无外部阀动作, 全程三通=上样位, 原子执行。
    [2] 冲点样头: 打到 A0。派发本条前 PLC 须已切三通→点样位(Q 确认空闲后)。
    终态不变量: 活塞必回 A0; entry[2] 体积恒等于 spot_head_volume_ml(逐段取整守恒)。
    契约: docs/superpowers/specs/2026-07-14-sampling-light-flush-design.md §3.2
    """
    return plan_flush_array(
        flush_volume_ml, outer_wash_volume_ml, spot_head_volume_ml,
        pump_addr=pump_addr, asp_speed=asp_speed,
        flush_disp_speed=flush_disp_speed,
        spot_head_disp_speed=spot_head_disp_speed, step_delay=step_delay,
        wash_port=wash_port, waste_port=waste_port, output_port=output_port,
    ).commands()


def plan_prep_array(
    air_buffer_ml: float = DEFAULT_AIR_BUFFER_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """上样准备数组的结构化计划 (build_prep_array 的语义源)。"""
    if air_buffer_ml <= 0 or air_buffer_ml > SYRINGE_ML:
        raise ValueError(f"准备保留体积必须在 (0, {SYRINGE_ML}] mL，收到 {air_buffer_ml} mL")
    return PumpPlan(entries=(
        plan_aspirate_cmd(
            air_buffer_ml, output_port, pump_addr, asp_speed, step_delay,
            note="绝对回抽: 泵侧留驱动液/针侧建气隔断"),
        EMPTY_ENTRY,
    ))


def build_prep_array(
    air_buffer_ml: float = DEFAULT_AIR_BUFFER_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """上样准备数组 [绝对回抽建立气隔断, 空占位]（A40 仅消费第 1 项）。

    充液润洗后输出管路已满液；A40 先抬针使针尖悬空，再从输出口绝对吸至
    ``A{air_buffer}``。液柱不可压缩，这一次回抽在两端同时成立：

    - 泵腔侧：吸入等量清洗液，作为点样驱动液储备；
    - 针尖侧：吸入等量空气，形成隔离样品与共管清洗液柱的气隔断。

    现行过阀排空点样流程按后者（气隔断）语义消费本参数，取值域与
    ``sampling.rinse_mix`` 的 ``air_gap_ml`` 同为 [0.1, 1.0] mL。参数名
    ``air_buffer_ml`` 为兼容既有 operation 与动作声明保留。
    """
    return plan_prep_array(
        air_buffer_ml, pump_addr=pump_addr, asp_speed=asp_speed,
        step_delay=step_delay, output_port=output_port,
    ).commands()


def build_sample_array(
    sample_volume_ml: float,
    air_gap_ml: float | None = None,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """上样数组 [相对回抽样品, 绝对吸气隔断]（A50 按 [2] -> [1] 顺序消费）。

    下标语义固定 ``[1]=样品``（不破坏既有编排与 legacy 调用），执行顺序由 PLC 决定：

    - ``[2]`` 在移向孔位【之前】于原位空气中发出，绝对吸至 ``A{gap}`` 建立气隔断。
      必须先吸气再移动：吸气前针尖内为满液，带液移动途中的挂壁滴液会滴进样品孔。
      绝对语义使润洗轮天然幂等——A55 终态活塞已在 ``A{gap}``，再绝对吸至同位为零位移。
    - ``[1]`` 下探入液后以 ``P<n>`` 在当前活塞位上相对叠加样品；最终绝对位置由 PLC A50
      查询真活塞位后做 ``current + relative <= 6000`` 双重校验。

    ``air_gap_ml`` 为 None 时 ``[2]`` 留空串，PLC 跳过吸气段（兼容先调 ``sampling.prep``
    建立气隔断的旧编排）。
    """
    return plan_sample_array(
        sample_volume_ml, air_gap_ml, pump_addr=pump_addr,
        asp_speed=asp_speed, step_delay=step_delay, output_port=output_port,
    ).commands()


def plan_sample_array(
    sample_volume_ml: float,
    air_gap_ml: float | None = None,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """上样数组的结构化计划 (build_sample_array 的语义源)。

    段序按数组下标 ([1]=样品 P 相对, [2]=气隔断 A 绝对); PLC 实际消费序是
    [2] -> [1] —— 演示/仿真侧按消费序重排由消费方负责 (与 PLC 同一条约定)。
    """
    aspirate_sample = plan_relative_aspirate_cmd(
        sample_volume_ml, output_port, pump_addr, asp_speed, step_delay,
        note="下探后 P 相对叠加样品")
    if air_gap_ml is None:
        return PumpPlan(entries=(aspirate_sample, EMPTY_ENTRY))
    if air_gap_ml <= 0 or air_gap_ml > SYRINGE_ML:
        raise ValueError(f"气隔断体积必须在 (0, {SYRINGE_ML}] mL，收到 {air_gap_ml} mL")
    gap_cmd = plan_aspirate_cmd(
        air_gap_ml, output_port, pump_addr, asp_speed, step_delay,
        note="移孔前绝对吸气隔断")
    return PumpPlan(entries=(aspirate_sample, gap_cmd))


def build_rinse_mix_array(
    rinse_volume_ml: float,
    mix_volume_ml: float,
    air_gap_ml: float = DEFAULT_RINSE_AIR_GAP_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """点样后润洗吹打数组 [回打余量, 加润洗液, 吸气隔断, 单次吹打]（A55 消费）。

    物理前置: PLC 已把上样针插入第一次取样的同一孔/管，并把外部三通置于
    上样针流路。四条命令语义：

    1. 将上一轮点样后泵腔当前余量(纯驱动清洗液)经口3回打原孔，终态 A0；
    2. 从口1吸润洗液，经口3全部加入原孔，终态 A0；
    3. 抬针后从口3吸 air_gap 空气建立混匀隔断，终态 A{gap}
       (PLC 在派发本条前抬 5Z、派发后再下针)；
    4. 从口3吸一份混合液到 A{gap+mix} 再打回 A{gap}。PLC 按 mix_count 重复第4条。

    终态不变量: 活塞停在 A{gap}，气隔断保留在针尖端；后续编排直接接
    sampling.aspirate(P 相对叠加)，不再调 sampling.prep。
    """
    return plan_rinse_mix_array(
        rinse_volume_ml, mix_volume_ml, air_gap_ml, pump_addr=pump_addr,
        asp_speed=asp_speed, disp_speed=disp_speed, step_delay=step_delay,
        wash_port=wash_port, output_port=output_port,
    ).commands()


def plan_rinse_mix_array(
    rinse_volume_ml: float,
    mix_volume_ml: float,
    air_gap_ml: float = DEFAULT_RINSE_AIR_GAP_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """润洗吹打数组的结构化计划 (build_rinse_mix_array 的语义源)。

    entry[4] 是单次吹打; PLC 按 mix_count 重复消费它 —— 轮数不在 plan 里,
    由动作参数 mix_count 表达 (演示/仿真侧与 PLC 同一条约定)。
    """
    for label, volume in (("润洗液体积", rinse_volume_ml), ("吹打体积", mix_volume_ml),
                          ("混匀气隔断体积", air_gap_ml)):
        if volume <= 0 or volume > SYRINGE_ML:
            raise ValueError(
                f"{label}必须在 (0, {SYRINGE_ML}] mL 范围内，收到 {volume} mL"
            )
    if air_gap_ml + mix_volume_ml > SYRINGE_ML:
        raise ValueError(
            f"气隔断 {air_gap_ml} mL + 吹打体积 {mix_volume_ml} mL"
            f" 超出注射泵量程 {SYRINGE_ML} mL"
        )
    for label, speed in (("吸液速度", asp_speed), ("打液速度", disp_speed)):
        if speed < 1 or speed > 500:
            raise ValueError(f"{label}必须在 [1, 500] 范围内，收到 {speed}")
    if step_delay < 0 or step_delay > 10000:
        raise ValueError(f"步间延时必须在 [0, 10000] ms 范围内，收到 {step_delay}")

    gap_steps = _ml_to_steps(air_gap_ml)
    mix_top_steps = gap_steps + _ml_to_steps(mix_volume_ml)
    # [4] 混匀在 A{gap}↔A{gap+mix} 间循环, 不回 A0, 保住针尖端气隔断
    mix_entry = (
        CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
        .speed(asp_speed, "asp_speed").port(output_port)
        .move_abs(mix_top_steps, op="aspirate", delay_ms=step_delay)
        .speed(disp_speed, "disp_speed").port(output_port)
        .move_abs(gap_steps, op="dispense", delay_ms=step_delay)
        .entry(note="单次吹打 A{gap}↔A{gap+mix}")
    )
    return PumpPlan(entries=(
        plan_dispense_all_cmd(
            pump_addr, disp_speed, step_delay, output_port,
            note="回打余量至A0"),
        plan_segment_cmd(
            rinse_volume_ml, wash_port,
            pump_addr, asp_speed, disp_speed, step_delay,
            output_port, note="加润洗液入原孔"),
        plan_aspirate_cmd(
            air_gap_ml, output_port, pump_addr, asp_speed, step_delay,
            note="抬针吸混匀气隔断"),
        mix_entry,
    ))


def build_dispense_array(
    sample_volume_ml: float,
    retract_volume_ml: float = DEFAULT_RETRACT_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    dispense_disp_speed: int = 0,
    step_delay: int = STEP_DELAY,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """点样数组 [抽取驱动空气, 打气点样+回抽释压]（Step 50 消费）。

    [1] 抽取空气：从空气口吸入 sample_vol mL（驱动空气段）
    [2] 打气+回抽：复合指令——先全打出至输出口（A0），再回抽 retract_vol mL
        回抽在分配阀仍指向点样器时执行，释放点样器/公共腔正压，防止滴液。
        retract_volume_ml=0 时退化为纯 dispense_all（兼容旧行为）。

    Args:
        sample_volume_ml: 样品体积 (mL)
        retract_volume_ml: 回抽体积 (mL)，默认 1.0 mL，0 则跳过回抽
        pump_addr: DT 协议地址
        asp_speed: 吸液速度
        disp_speed: 打液速度（上限 500），用于回抽等非点样动作
        dispense_disp_speed: 点样打液速度（上限 500），仅用于点样打出。
            默认 0 表示与 disp_speed 相同（向后兼容）
        step_delay: 步骤间延迟 (ms)
        air_port: 空气端口号
        output_port: 输出端口号

    Returns:
        DT 协议指令字符串列表（2 条）。

    Raises:
        ValueError: 打液速度超过 500
    """
    return plan_dispense_array(
        sample_volume_ml, retract_volume_ml, pump_addr=pump_addr,
        asp_speed=asp_speed, disp_speed=disp_speed,
        dispense_disp_speed=dispense_disp_speed, step_delay=step_delay,
        air_port=air_port, output_port=output_port,
    ).commands()


def plan_dispense_array(
    sample_volume_ml: float,
    retract_volume_ml: float = DEFAULT_RETRACT_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    dispense_disp_speed: int = 0,
    step_delay: int = STEP_DELAY,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> PumpPlan:
    """点样数组的结构化计划 (build_dispense_array 的语义源)。"""
    # 解析点样打液速度：0 表示跟随 disp_speed (语义键随之切换)
    _spot_disp_speed = dispense_disp_speed if dispense_disp_speed > 0 else disp_speed
    _spot_key = "spot_disp_speed" if dispense_disp_speed > 0 else "disp_speed"
    if _spot_disp_speed > 500:
        raise ValueError(f"点样打液速度不能超过 500，收到 {_spot_disp_speed}")

    aspirate_air = plan_aspirate_cmd(
        sample_volume_ml, air_port, pump_addr, asp_speed, step_delay,
        note="抽取驱动空气")
    if retract_volume_ml > 0:
        # 复合指令：全打出(A0) → 回抽释压（泵停在 A{retract_steps}）
        retract_steps = _ml_to_steps(retract_volume_ml)
        dispense_and_retract = (
            CmdBuilder(pump_addr, steps_per_ml=_steps_per_ml())
            .speed(_spot_disp_speed, _spot_key).port(output_port)
            .move_abs(0, op="dispense", delay_ms=step_delay)
            .speed(asp_speed, "asp_speed").port(output_port)
            .move_abs(retract_steps, op="aspirate", delay_ms=step_delay)
            .entry(note="打气点样至A0 + 回抽释压")
        )
    else:
        dispense_and_retract = plan_dispense_all_cmd(
            pump_addr, _spot_disp_speed, step_delay, output_port,
            speed_key=_spot_key, note="打气点样至A0")
    return PumpPlan(entries=(aspirate_air, dispense_and_retract))


SPOT_END_POSITION_MAX_ML = 5.0  # 死体积补偿终点上限 (留足 prep 缺省 3mL 驱动液 + 余量)


def spot_band_end_steps(end_position_ml: float) -> int:
    """点样活塞终点 mL -> 步数(单一换算真源: 指令 A{N} 与 PLC 节点共用)。

    合法域 [0, SPOT_END_POSITION_MAX_ML] mL; 越界 ValueError (防误配大值一程不点)。
    """
    if not (0.0 <= end_position_ml <= SPOT_END_POSITION_MAX_ML):
        raise ValueError(
            f"点样活塞终点必须在 [0, {SPOT_END_POSITION_MAX_ML}] mL, 收到 {end_position_ml} mL")
    return _ml_to_steps(end_position_ml)


def build_spot_band_run_cmd(
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    disp_speed: int = DEFAULT_DISPENSE_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    end_position_ml: float = 0.0,
) -> str:
    """单条带点样供液指令: 从当前位置绝对打出到 A{N}(缺省 N=0)。

    该指令用于 PLC 条带级动作: PLC 发送有限 A{N}R 后, 以 Q 查询确认
    注射泵空闲, 再进入只吹气干燥段。%MW1300 只表示转发邮箱可用,
    不能表示 A{N} 物理动作完成。N>0 = 死体积补偿, PLC 判终同步用
    Sampling_band_end_position (spec 2026-07-14-spot-end-position)。
    """
    return plan_spot_band_run(
        pump_addr=pump_addr, disp_speed=disp_speed, step_delay=step_delay,
        output_port=output_port, end_position_ml=end_position_ml,
    ).entries[0].command()


def plan_spot_band_run(
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    disp_speed: int = DEFAULT_DISPENSE_DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    end_position_ml: float = 0.0,
) -> PumpPlan:
    """条带点样供液指令的结构化计划 (build_spot_band_run_cmd 的语义源)。

    速度语义键固定 spot_disp_speed —— 唯一消费方 profiles._build_sampling_spot_band_layer
    的 disp_speed 实参就来自 spot_disp_speed 回退链。
    """
    return PumpPlan(entries=(
        plan_dispense_all_cmd(
            pump_addr, disp_speed, step_delay, output_port,
            end_steps=spot_band_end_steps(end_position_ml),
            speed_key="spot_disp_speed", note="条带供液: 绝对打出到 A{N}"),
    ))


def build_pump_stop_cmd(*, pump_addr: str = DEFAULT_PUMP_ADDR) -> str:
    """SY-03B DT 协议立即停止指令, 仅供异常/人工中止路径使用。"""
    return f"/{pump_addr}T\r"


# ---------------------------------------------------------------------------
# 命令行预览
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sample_vol = 5.0
    air_buffer = DEFAULT_AIR_BUFFER_ML
    wash_vol = 25.0
    retract_vol = DEFAULT_RETRACT_ML
    if len(sys.argv) >= 2:
        sample_vol = float(sys.argv[1])
    if len(sys.argv) >= 3:
        air_buffer = float(sys.argv[2])
    if len(sys.argv) >= 4:
        wash_vol = float(sys.argv[3])
    if len(sys.argv) >= 5:
        retract_vol = float(sys.argv[4])

    cmds = translate_sample_v2_cmd(
        sample_vol, air_buffer_ml=air_buffer, wash_volume_ml=wash_vol,
        retract_volume_ml=retract_vol,
    )
    budget = calc_v2_volume_budget(sample_vol, air_buffer, retract_vol)

    print(f"# 上样注射泵 v2 (空气驱动)")
    print(f"# 参数: sample={sample_vol}mL, air_buffer={air_buffer}mL, wash={wash_vol}mL, retract={retract_vol}mL")
    print(f"# 泵腔峰值: {budget['peak_pump_ml']:.1f} mL / {SYRINGE_ML} mL")
    print(f"# 指令数: {len(cmds)}")
    print()
    step_labels = [
        f"Step 1 清洗 (吸{wash_vol}mL→打出)",
        f"Step 2 回抽空气 ({budget['step2_air_ml']:.1f}mL, 隔离段)",
        f"Step 3 吸取样品 ({budget['step3_sample_ml']:.1f}mL, 上样针入样品)",
        f"Step 4 排废液 ({budget['step4_waste_ml']:.1f}mL, 全打出至废液口)",
        f"Step 5 驱动空气 ({budget['step5_drive_air_ml']:.1f}mL, 从空气口吸入)",
        f"Step 6 点样打出 ({budget['step6_dispense_ml']:.1f}mL, 全打出至点样流路)",
    ]
    if retract_vol > 0:
        step_labels.append(
            f"Step 7 回抽释压 ({budget['step7_retract_ml']:.1f}mL, 分配阀仍指向点样器)"
        )
    for i, cmd in enumerate(cmds):
        print(f"[{i:02d}] {step_labels[i]}")
        print(f"    {cmd}")
        print()

    # 4 数组构建（协议 v1.5）
    clean_arr = build_clean_array(wash_vol)
    prep_arr = build_prep_array(air_buffer)
    sample_arr = build_sample_array(sample_vol)
    disp_arr = build_dispense_array(sample_vol, retract_vol)
    print("# ---- 协议 v1.5 4 数组 ----")
    for label, arr in [
        ("Sampling_clean_instructions", clean_arr),
        ("Sampling_prep_instructions", prep_arr),
        ("Sampling_sample_instructions", sample_arr),
        ("Sampling_dispense_instructions", disp_arr),
    ]:
        print(f"\n{label} (ARRAY[1..2]):")
        for j, c in enumerate(arr):
            print(f"  [{j+1}] {c.strip()}")

    print(f"\n初始化: {pump_init_cmd(DEFAULT_PUMP_ADDR, output_port=OUTPUT_PORT)}")
    print(f"状态查: {pump_query_cmd(DEFAULT_PUMP_ADDR)}")
