"""收集泵指令翻译服务 - 将收集参数翻译为 SY-03B DT 协议指令

核心函数 translate_collect_cmd：纯函数、无副作用、可独立测试。

硬件规格（Station 3, T-04 阀头, DT 地址 "3"）：
    端口 1：2-way 阀 → 收集器（输出口）
    端口 2：溶剂入口（单一溶剂）
    端口 3：堵头
    端口 4：堵头
    公共端 C：注射泵

协议：DT (Data Terminal) 协议
"""

from __future__ import annotations

from eit_ptlc.tools.pump.dt_codec import CmdBuilder, PumpPlan

# ---------------------------------------------------------------------------
#  常量
# ---------------------------------------------------------------------------
COLLECT_SOLVENT_PORT = 2   # 唯一溶剂入口（端口 2）
COLLECT_OUTPUT_PORT = 1    # 输出口 → 收集器（端口 1）
SYRINGE_STEPS = 6000       # 25 mL 进样器满行程步数
SYRINGE_ML = 25.0          # 进样器量程

ASP_SPEED = 500           # 吸液速度
DISP_SPEED = 500            # 打液速度（上限 500）
STEP_DELAY = 1000           # 步骤间延迟 (ms)


def plan_collect(
    volume_ml: float,
    pump_addr: str = "3",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> PumpPlan:
    """收集加液复合指令的结构化计划 (translate_collect_cmd 的语义源)。"""
    if volume_ml <= 0 or volume_ml > syringe_ml:
        raise ValueError(f"吸液体积必须在 0-{syringe_ml} mL 之间，收到 {volume_ml}")
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    volume_ul = volume_ml * 1000
    steps = int(round(volume_ul * SYRINGE_STEPS / (syringe_ml * 1000)))

    entry = (
        CmdBuilder(pump_addr, steps_per_ml=SYRINGE_STEPS / syringe_ml)
        .speed(asp_speed, "asp_speed").port(COLLECT_SOLVENT_PORT)
        .move_abs(steps, op="aspirate", delay_ms=step_delay)
        .speed(disp_speed, "disp_speed").port(COLLECT_OUTPUT_PORT)
        .move_abs(0, op="dispense", delay_ms=step_delay)
        .entry(note="吸溶剂→打至收集器")
    )
    return PumpPlan(entries=(entry,))


def translate_collect_cmd(
    volume_ml: float,
    pump_addr: str = "3",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> str:
    """将吸液体积翻译为 SY-03B DT 协议复合指令。

    从端口 2 吸溶剂 → 从端口 1 打出至收集器。
    DT 协议原子执行，PLC 只需发送一次。

    Args:
        volume_ml: 吸液体积，单位毫升，范围 (0, syringe_ml]
        pump_addr: 泵 DT 地址，默认 '3'
        syringe_ml: 进样器量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度（上限 500）
        step_delay: 步骤间延迟 (ms)

    Returns:
        DT 协议复合指令字符串，如 '/3V1500I2A480M500V500I1A0M500R\r'

    Raises:
        ValueError: 参数超出合法范围
    """
    return plan_collect(
        volume_ml, pump_addr, syringe_ml, asp_speed, disp_speed, step_delay,
    ).entries[0].command()


def pump_init_cmd(
    pump_addr: str = "3",
    init_speed: int = 0,
    input_port: int = 0,
    output_port: int = COLLECT_OUTPUT_PORT,
) -> str:
    """生成 SY-03B (T-04) 泵 Z 初始化指令。

    Z<n1,n2,n3> 顺时针初始化活塞驱动和阀门：
      n1 = 初始化活塞力度/速度（0=满力度/默认1400脉冲每秒）
      n2 = 初始化输入端口（0=默认）
      n3 = 初始化输出端口（T-04 收集泵=1）

    Args:
        pump_addr: SY-03B 泵 DT 协议地址，默认 '3'
        init_speed: 初始化力度/速度（0=满力度）
        input_port: 初始化输入端口（0=默认）
        output_port: 初始化输出端口（收集泵=1）

    Returns:
        DT 协议初始化指令字符串
    """
    return f"/{pump_addr}Z{init_speed},{input_port},{output_port}R$R"


def pump_query_cmd(pump_addr: str = "3") -> str:
    """生成 SY-03B (T-04) 泵状态查询指令。"""
    return f"/{pump_addr}Q$R"
