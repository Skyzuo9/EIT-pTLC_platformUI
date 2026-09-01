"""展开流程泵指令翻译服务

将 4 通道展开剂比例参数翻译为 SY-03B (T-06 阀头) 注射泵 DT 协议指令。

核心函数 translate_develop_cmd：纯函数、无副作用、可独立测试。

硬件规格：
- SY-03B 进样器 + T-06 阀头（6 通道分配型流路）—— 溶剂通道选择与体积吸取一体
- 2 台泵挂载于同一 RS-485 总线，各自管理独立展缸组

端口映射（T-06 分配型流路，泵1/泵2 不对称）：
    泵 1 (地址 "1", 展开组1)：端口 1=堵头, 端口 2-5=溶剂1-4, 端口 6=输出口
    泵 2 (地址 "2", 展开组2)：端口 1=输出口, 端口 2-5=溶剂1-4, 端口 6=堵头
    公共端 C：选择性连通 1-6 号端口

协议：DT (Data Terminal) 协议，9600/38400 bps, 8N1

参考文档：全陶瓷Smart SV04M-B (ASCII)_V1.0（阀指令同源）

DT 协议复合指令格式：
    /<addr>V<asp_speed>I<ch1>A<cum1>M<delay>...I<chN>A<cumN>M<delay>
    V<disp_speed>I<output>A0M<delay>R
    —— 吸液(绝对定位) + 打液(切输出口+活塞归零)，一条复合指令原子执行

变量语义：
    Expand_Mode_Flag   0=缸模式润洗, 1=管路模式润洗（仅影响 step 10）
    Expand_Target_Tank 目标缸号 (1-8)，PC 写入，PLC 自动推导 Group/Number
    Expand_forward_instructions  注射泵转发指令字符串

    Expand_Group / Expand_Number 已废弃（v1.3）：PLC 从 Target_Tank 自动推导，
    上位机不再写入。pump_translator 内部仍用 target_tank 推导泵地址。
"""

from __future__ import annotations

from eit_ptlc.tools.pump.dt_codec import CmdBuilder, PumpPlan

# ---------------------------------------------------------------------------
#  常量
# ---------------------------------------------------------------------------
T06_SOLVENT_PORTS = 4     # T-06 阀头物理溶剂入口数（端口 2-5）
T06_OUTPUT_PORT = 6       # T-06 阀头输出口（打液至展缸）
SYRINGE_STEPS = 6000      # 25 mL 进样器满行程步数
SYRINGE_ML = 25.0         # 进样器量程

# 泵运动速度与延迟
ASP_SPEED = 100          # 吸液速度
DISP_SPEED = 100           # 打液速度（上限 500）
STEP_DELAY = 500          # 步骤间延迟 (ms)，稳定液面

# 展开组号 → 泵 DT 协议地址映射
GROUP_PUMP_MAP: dict[int, str] = {
    1: "1",  # 展开组1 → 泵 DT 地址 "1" (拨码 0)
    2: "2",  # 展开组2 → 泵 DT 地址 "2" (拨码 1)
}

# 泵地址 → 输出端口映射（两台泵不对称）
PUMP_OUTPUT_PORT_MAP: dict[str, int] = {
    "1": 6,  # 泵 1：输出口 = 端口 6
    "2": 1,  # 泵 2：输出口 = 端口 1（与泵 1 不对称）
}


# ---------------------------------------------------------------------------
#  核心翻译函数
# ---------------------------------------------------------------------------
def translate_develop_cmd(
    ratios: list[float],
    total_volume_ml: float,
    *,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> list[dict]:
    """将展开剂比例翻译为 SY-03B (T-06) 泵吸液+打液复合指令。

    一条复合指令完成全部流程：逐通道吸液（绝对定位）→ 切输出口打液。
    DT 协议原子执行，PLC 只需发送一次。

    溶剂端口 2-5（泵 1）/ 2-5（泵 2），输出口泵 1=6, 泵 2=1。

    Args:
        ratios: 4 个溶剂通道的比例值，对应物理端口 2-5。
                例如 [3, 2, 1, 0] 表示 端口2:端口3:端口4 = 3:2:1。
                值为 0 表示该通道不参与混合。
        total_volume_ml: 展开剂总体积，单位毫升，范围 (0, syringe_ml]。
        pump_addr: SY-03B 泵 DT 协议地址，默认 '1'。
        syringe_ml: 进样器量程，默认 25 mL。
        asp_speed: 吸液速度，默认 1500。
        disp_speed: 打液速度，默认 5000。
        step_delay: 步骤间延迟 (ms)，默认 500。

    Returns:
        指令序列列表，按执行顺序排列。每个元素为字典::

            {
                "channel":    int,    # 溶剂端口号 (2-5) 或输出口
                "volume_ml":  float,  # 该通道吸取体积 (mL)；打液步为 0
                "command":    str,    # DT 协议子指令 (不含地址前缀和 R 后缀)
            }

    Raises:
        ValueError: 参数超出合法范围
    """
    _validate_ratios(ratios)
    if total_volume_ml <= 0 or total_volume_ml > syringe_ml:
        raise ValueError(
            f"总体积必须在 0-{syringe_ml} mL 之间，收到 {total_volume_ml}"
        )
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    output_port = PUMP_OUTPUT_PORT_MAP.get(pump_addr, T06_OUTPUT_PORT)

    commands: list[dict] = [
        {
            "channel": channel,
            "volume_ml": round(volume_ml, 4),
            # I<port>A<cum_position>M<delay>: 切换端口 + 活塞移至累计绝对位置
            "command": f"I{channel}A{cum_steps}M{step_delay}",
        }
        for channel, volume_ml, _steps, cum_steps
        in _solvent_steps(ratios, total_volume_ml, syringe_ml)
    ]

    # 打液步骤：切输出口 + 活塞归零（A0 = 全部打出）
    commands.append({
        "channel": output_port,
        "volume_ml": 0.0,
        "command": f"I{output_port}A0M{step_delay}",
    })

    return commands


def _solvent_steps(
    ratios: list[float],
    total_volume_ml: float,
    syringe_ml: float = SYRINGE_ML,
) -> list[tuple[int, float, int, int]]:
    """按配比展开逐通道吸液: (端口, 体积mL, 步数, 累计绝对步位)。

    translate_develop_cmd(分析视图) 与 plan_forward_instructions(指令计划) 的
    共同单一真源 —— 0 配比与凑整后 0 步的通道一律跳过。
    """
    total_ratio = sum(r for r in ratios if r > 0)
    steps_per_ul = SYRINGE_STEPS / (syringe_ml * 1000)
    out: list[tuple[int, float, int, int]] = []
    cum_steps = 0
    for i, ratio in enumerate(ratios, start=2):
        if ratio <= 0:
            continue
        volume_ml = total_volume_ml * ratio / total_ratio
        volume_ul = volume_ml * 1000
        steps = int(round(volume_ul * steps_per_ul))
        if steps <= 0:
            continue
        cum_steps += steps
        out.append((i, volume_ml, steps, cum_steps))
    return out


# ---------------------------------------------------------------------------
#  辅助翻译：生成 Expand_forward_instructions 注射泵转发指令
# ---------------------------------------------------------------------------
def build_forward_instructions(
    ratios: list[float],
    total_volume_ml: float,
    *,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> str:
    """生成 Expand_forward_instructions 注射泵转发复合指令字符串。

    一条复合指令：吸液(绝对定位) + 打液(切输出口+活塞归零)。
    PLC 发送一次，泵原子执行完整流程。

    Args:
        ratios: 4 个溶剂通道比例值
        total_volume_ml: 展开剂总体积 (mL)
        pump_addr: SY-03B 泵 DT 协议地址
        syringe_ml: 进样器量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度
        step_delay: 步骤间延迟 (ms)

    Returns:
        DT 协议复合指令字符串，如 '/1V1500I1A360M500I2A600M500V5000I6A0M500R\r'
    """
    return plan_forward_instructions(
        ratios, total_volume_ml, pump_addr=pump_addr, syringe_ml=syringe_ml,
        asp_speed=asp_speed, disp_speed=disp_speed, step_delay=step_delay,
    ).entries[0].command()


def plan_forward_instructions(
    ratios: list[float],
    total_volume_ml: float,
    *,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> PumpPlan:
    """展开剂转发复合指令的结构化计划 (build_forward_instructions 的语义源)。

    结构: V{asp} + 逐溶剂通道 I/A(累计绝对位)/M (通道间**不**重发 V) +
    V{disp} + 切输出口 A0。多溶剂时柱塞逐段上行到各累计位 —— 这正是手写
    相位表无法表达的部分 (它只能写"单段吸到总量"), 漂移门禁对此具名豁免。
    """
    _validate_ratios(ratios)
    if total_volume_ml <= 0 or total_volume_ml > syringe_ml:
        raise ValueError(
            f"总体积必须在 0-{syringe_ml} mL 之间，收到 {total_volume_ml}"
        )
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    output_port = PUMP_OUTPUT_PORT_MAP.get(pump_addr, T06_OUTPUT_PORT)
    builder = CmdBuilder(pump_addr, steps_per_ml=SYRINGE_STEPS / syringe_ml)
    builder.speed(asp_speed, "asp_speed")
    for channel, _volume_ml, _steps, cum_steps in _solvent_steps(
            ratios, total_volume_ml, syringe_ml):
        builder.port(channel).move_abs(cum_steps, op="aspirate", delay_ms=step_delay)
    builder.speed(disp_speed, "disp_speed").port(output_port)
    builder.move_abs(0, op="dispense", delay_ms=step_delay)
    return PumpPlan(entries=(builder.entry(note="按配比逐通道吸液→切输出口打空"),))


def translate_develop_params(
    ratios: list[float],
    total_volume_ml: float,
    rinse_mode: str = "cylinder",
    expand_group: int = 1,
    target_tank: int = 1,
    rinse_repeat_count: int = 1,
    up_liquid_repeat_count: int = 1,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> dict:
    """将 UI 输入翻译为 PLC 可用参数字典。

    由 DevelopStage.translate_params 调用，输出与 PLC Host_Computer 变量对齐。

    变量语义（v1.3）：
        Expand_Mode_Flag       0=缸模式润洗, 1=管路模式润洗（仅影响 step 10）
        Expand_Target_Tank     目标缸号 (1-8)，PC 写入，PLC 自动推导 Group/Number
        Expand_forward_instructions  注射泵转发指令字符串
        Expand_rinse_count     润洗注射泵重复执行次数（Step 10）
        Expand_up_liquid_count 上液注射泵重复执行次数（Step 20）

    Expand_Group / Expand_Number 不再由上位机写入。PLC 从 Target_Tank 自动推导。
    pump_translator 内部仍用 target_tank 推导泵地址。

    Args:
        ratios: 4 个溶剂通道比例值（UI 输入，不直接写 PLC）
        total_volume_ml: 展开剂总体积 (mL)
        rinse_mode: 润洗模式 "cylinder" | "line"
        expand_group: 展开组号 (1-2)，仅用于泵地址推导（不再写 PLC）
        target_tank: 目标缸号 (1-8)，写入 Expand_Target_Tank
        rinse_repeat_count: 润洗注射泵重复执行次数，写入 Expand_rinse_count
        up_liquid_repeat_count: 上液注射泵重复执行次数，写入 Expand_up_liquid_count

    Returns:
        PLC 参数字典，键为 PLC 变量名
    """
    mode_flag = 1 if rinse_mode.lower() == "line" else 0

    # target_tank → 泵地址推导：Group 1 (Tank 1-4) → 泵1，Group 2 (Tank 5-8) → 泵2
    derived_group = (target_tank - 1) // 4 + 1
    pump_addr = GROUP_PUMP_MAP.get(derived_group, "1")

    forward_instructions = (
        build_forward_instructions(
            ratios, total_volume_ml, pump_addr=pump_addr,
            asp_speed=asp_speed, disp_speed=disp_speed, step_delay=step_delay,
        )
        if total_volume_ml > 0 else ""
    )

    return {
        "Expand_Mode_Flag":               mode_flag,
        "Expand_Target_Tank":             target_tank,
        "Expand_forward_instructions":    forward_instructions,
        "Expand_rinse_count":             rinse_repeat_count,
        "Expand_up_liquid_count":         up_liquid_repeat_count,
    }


# ---------------------------------------------------------------------------
#  单条指令生成（供 executor 按需调用或 Debug 单步调试）
# ---------------------------------------------------------------------------
def pump_init_cmd(
    pump_addr: str = "1",
    init_speed: int = 0,
    input_port: int = 0,
    output_port: int | None = None,
) -> str:
    """生成 SY-03B (T-06) 泵 Z 初始化指令。

    Z<n1,n2,n3> 顺时针初始化活塞驱动和阀门：
      n1 = 初始化活塞力度/速度（0=满力度/默认1400脉冲每秒）
      n2 = 初始化输入端口（0=默认）
      n3 = 初始化输出端口（泵1=6, 泵2=1）

    初始化后需通过 Q 指令确认初始化成功（PLC pumpCmd FB 自动完成）。

    Args:
        pump_addr: SY-03B 泵 DT 协议地址
        init_speed: 初始化力度/速度（0=满力度）
        input_port: 初始化输入端口（0=默认）
        output_port: 初始化输出端口（None=从 pump_addr 自动推导）

    Returns:
        DT 协议初始化指令字符串
    """
    if output_port is None:
        output_port = PUMP_OUTPUT_PORT_MAP.get(pump_addr, T06_OUTPUT_PORT)
    return f"/{pump_addr}Z{init_speed},{input_port},{output_port}R$R"


def pump_query_cmd(pump_addr: str = "1") -> str:
    """生成 SY-03B (T-06) 泵状态查询指令。

    查询泵是否空闲以及错误代码。
    报告/查询指令不需要 R 后缀（协议规定）。

    状态字节: bit5=1 空闲, bit3-0 为错误代码 (0=无错误)

    Args:
        pump_addr: SY-03B 泵 DT 协议地址

    Returns:
        DT 协议状态查询指令字符串
    """
    return f"/{pump_addr}Q$R"


# ---------------------------------------------------------------------------
#  内部校验
# ---------------------------------------------------------------------------
def _validate_ratios(ratios: list[float]) -> None:
    """校验溶剂比例列表。"""
    if len(ratios) != T06_SOLVENT_PORTS:
        raise ValueError(
            f"ratios 必须包含 {T06_SOLVENT_PORTS} 个值，收到 {len(ratios)}"
        )
    if all(r == 0 for r in ratios):
        raise ValueError("至少一个溶剂通道的比例必须大于 0")
    for i, r in enumerate(ratios, start=1):
        if r < 0:
            raise ValueError(f"通道 {i} 的比例不能为负数，收到 {r}")
