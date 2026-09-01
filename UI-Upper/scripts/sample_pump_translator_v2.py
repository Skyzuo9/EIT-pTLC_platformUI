"""上样注射泵 v2 空气驱动点样策略指令翻译器

将用户输入（样品体积、安全余量、清洗体积）翻译为 SY-03B (T-04) 注射泵 DT 协议指令序列。

硬件规格：
    - SY-03B 注射泵 (25mL / 6000步) + T-04 阀头（4 通道分配型流路）
    - 外部三通阀（独立控制，不在本脚本范围）

策略（6步空气驱动）：
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
# 从 v1 导入基础构建模块
# ---------------------------------------------------------------------------
try:
    from scripts.sample_pump_translator import (  # type: ignore[import-not-found]
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
        build_dispense_all_cmd,
        # 辅助函数
        pump_init_cmd,
        pump_query_cmd,
        _ml_to_steps,
    )
except ImportError:
    # 直接运行脚本时（python sample_pump_translator_v2.py）回退到裸导入
    from sample_pump_translator import (  # type: ignore[import-not-found]
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
        build_dispense_all_cmd,
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
    """生成 v2 空气驱动点样完整 DT 指令序列（7 步）。

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
# ---------------------------------------------------------------------------
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
    inner = build_segment_cmd(
        wash_volume_ml, wash_port,
        pump_addr, asp_speed, disp_speed, step_delay,
        output_port,
    )
    outer = build_segment_cmd(
        wash_volume_ml, wash_port,
        pump_addr, asp_speed, disp_speed, step_delay,
        waste_port,
    )
    return [inner, outer]


def build_prep_array(
    sample_volume_ml: float,
    air_buffer_ml: float = DEFAULT_AIR_BUFFER_ML,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    waste_port: int = WASTE_PORT,
) -> list[str]:
    """上样准备数组 [吸取空气, 废液打出]（Step 20 消费）。

    [1] 吸取空气：从输出口吸入 air_buffer mL（上样针在空气中，建立隔离段）
    [2] 废液打出：将泵腔全部内容从废液口打出（清空泵腔）
    """
    aspirate_air = build_aspirate_cmd(
        air_buffer_ml, output_port,
        pump_addr, asp_speed, step_delay,
    )
    dispense_waste = build_dispense_all_cmd(
        pump_addr, disp_speed, step_delay, waste_port,
    )
    return [aspirate_air, dispense_waste]


def build_sample_array(
    sample_volume_ml: float,
    *,
    pump_addr: str = DEFAULT_PUMP_ADDR,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    output_port: int = OUTPUT_PORT,
    waste_port: int = WASTE_PORT,
) -> list[str]:
    """上样数组 [回抽样品, 废液排废]（Step 40 消费）。

    [1] 回抽样品：从输出口吸入 sample_vol mL（上样针入样品液面）
    [2] 废液排废：将泵腔内全部液体/空气从废液口打出（清空泵腔）
    """
    aspirate_sample = build_aspirate_cmd(
        sample_volume_ml, output_port,
        pump_addr, asp_speed, step_delay,
    )
    dispense_waste = build_dispense_all_cmd(
        pump_addr, disp_speed, step_delay, waste_port,
    )
    return [aspirate_sample, dispense_waste]


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
    # 解析点样打液速度：0 表示跟随 disp_speed
    _spot_disp_speed = dispense_disp_speed if dispense_disp_speed > 0 else disp_speed
    if _spot_disp_speed > 500:
        raise ValueError(f"点样打液速度不能超过 500，收到 {_spot_disp_speed}")

    aspirate_air = build_aspirate_cmd(
        sample_volume_ml, air_port,
        pump_addr, asp_speed, step_delay,
    )
    if retract_volume_ml > 0:
        # 复合指令：全打出(A0) → 回抽释压（泵停在 A{retract_steps}）
        retract_steps = _ml_to_steps(retract_volume_ml)
        dispense_and_retract = (
            f"/{pump_addr}V{_spot_disp_speed}"
            f"I{output_port}A0M{step_delay}"
            f"V{asp_speed}"
            f"I{output_port}A{retract_steps}M{step_delay}"
            f"R\r"
        )
    else:
        dispense_and_retract = build_dispense_all_cmd(
            pump_addr, _spot_disp_speed, step_delay, output_port,
        )
    return [aspirate_air, dispense_and_retract]


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
    prep_arr = build_prep_array(sample_vol, air_buffer)
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
