"""泵指令翻译服务 - 将用户友好的业务参数翻译为 SY-03B DT 协议指令

核心函数 translate_pump_cmd：纯函数、无副作用、可独立测试。
提取自 scripts/recipe2param.py，供 CollectStage 运行时调用。

硬件规格：25mL 进样器 + T-04 阀头（4 通道分配型流路）

端口映射（T-04 分配型流路）：
    端口 1-3：溶剂入口
    端口 4：输出口（打液）
    公共端 C：选择性连通 1-4 号端口

DEPRECATED: 上位机程序修改完成后将删除本文件。
请使用各泵专用翻译器：
    - develop_pump_translator.py  (泵 1 & 2, T-06, 展开)
    - sample_pump_translator.py   (泵 4, T-04, 上样)
    - collect_pump_translator.py  (泵 3, T-04, 收集)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
#  常量
# ---------------------------------------------------------------------------
T04_SOLVENT_PORTS = 3     # T-04 阀头溶剂入口数（端口 1-3）
T04_OUTPUT_PORT = 4       # T-04 阀头输出口（打液）
SYRINGE_STEPS = 6000      # 25 mL 进样器满行程步数
SYRINGE_ML = 25.0         # 进样器量程

# 泵运动速度与延迟
ASP_SPEED = 1500          # 吸液速度
DISP_SPEED = 500           # 打液速度（上限 500）
STEP_DELAY = 500          # 步骤间延迟 (ms)


def translate_pump_cmd(
    volume_ml: float,
    channel: int,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
) -> str:
    """将 (吸液体积, 通道号) 翻译为 SY-03B DT 协议复合指令。

    一条复合指令完成：吸液（绝对定位）→ 切输出口打液（活塞归零）。

    Args:
        volume_ml: 吸液体积，单位毫升，范围 (0, syringe_ml]
        channel:   通道号，T-04 阀头范围 1-3（溶剂入口）
        pump_addr: 泵地址，默认 '1'（对应硬件拨码 0）
        syringe_ml: 进样器量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度
        step_delay: 步骤间延迟 (ms)

    Returns:
        DT 协议复合指令字符串，如 '/1V1500I2A480M500V5000I4A0M500R\r'

    Raises:
        ValueError: 参数超出合法范围
    """
    if not (1 <= channel <= T04_SOLVENT_PORTS):
        raise ValueError(f"通道号必须在 1-{T04_SOLVENT_PORTS} 之间，收到 {channel}")
    if volume_ml <= 0 or volume_ml > syringe_ml:
        raise ValueError(f"吸液体积必须在 0-{syringe_ml} mL 之间，收到 {volume_ml}")
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")

    # 体积 → 步数（绝对定位：从 0 吸到 steps）
    volume_ul = volume_ml * 1000
    steps = int(round(volume_ul * SYRINGE_STEPS / (syringe_ml * 1000)))

    # 复合指令：吸液 + 打液
    # V<asp_speed>:              设置吸液速度
    # I<channel>A<steps>M<delay>: 切溶剂口 + 活塞移至绝对位置（吸液）
    # V<disp_speed>:             设置打液速度
    # I<output>A0M<delay>:       切输出口 + 活塞归零（打液）
    # R:                         执行
    return (
        f"/{pump_addr}V{asp_speed}"
        f"I{channel}A{steps}M{step_delay}"
        f"V{disp_speed}"
        f"I{T04_OUTPUT_PORT}A0M{step_delay}"
        f"R\r"
    )
