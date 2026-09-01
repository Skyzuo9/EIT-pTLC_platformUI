# Sample Pump V2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 创建 sample_pump_translator_v2.py（空气驱动上样策略翻译器）和 test_sample_v2.py（测试脚本）

**Architecture:** v2 复用 v1 的 DT 指令构建函数（build_segment_cmd, build_aspirate_cmd, build_dispense_all_cmd, pump_init_cmd, pump_query_cmd），新增 translate_sample_v2_cmd 主翻译函数、体积预算计算和参数校验。测试脚本沿用 v1 test_sample.py 的 argparge + 交互模式结构。

**Tech Stack:** Python 3.11+, 无外部依赖（仅标准库）

**Spec:** `docs/superpowers/specs/2026-05-31-sample-pump-v2-design.md`

---

### 文件结构

```
UI-Upper/scripts/
├── sample_pump_translator.py      # v1 (不变)
├── sample_pump_translator_v2.py   # v2 (新建)
├── test_sample.py                 # v1 测试 (不变)
└── test_sample_v2.py              # v2 测试 (新建)
```

- `sample_pump_translator_v2.py` — 从 v1 导入构建函数和硬件常量，定义 v2 专用常量和翻译逻辑
- `test_sample_v2.py` — 命令行测试脚本，可命令行传参或交互输入

---

### Task 1: 创建 translator v2 模块

**Files:**
- Create: `UI-Upper/scripts/sample_pump_translator_v2.py`

- [ ] **Step 1: 写 v2 核心函数（先写代码，用 --addr 参数快速验证）**

由于 v2 所有构建函数都复用 v1，无新增构建函数，核心逻辑是组合已有函数。采用"先写实现→命令行动态验证"的方式。

完整文件内容：

```python
"""上样注射泵 v2 — 空气驱动上样点样策略指令翻译器

将用户输入（上样体积、余量）翻译为 SY-03B (T-04) 注射泵 DT 协议指令序列。

硬件规格：
    - SY-03B 注射泵 (25mL / 6000步) + T-04 阀头（4 通道分配型流路）
    - 外部三通阀（独立控制，不在本脚本范围）

策略（v2 空气驱动）：
    1. 清洗管路：PLC 循环调用单次复合清洗指令（吸清洗液→打输出口）
    2. 上样针在空气中，泵回抽 sample_vol + margin 空气，空气进入管路，
       等体积清洗液被置换入泵腔
    3. 上样针入样品液，泵回抽 sample_vol，样品进入管路前端，
       等体积清洗液被置换入泵腔
    4. 泵切换废液口，全打出排掉被置换入泵腔的清洗液
    5. 泵切换空气口，抽取 sample_vol 驱动空气
    6. 三通阀切点样路，泵全打出——驱动空气推动管路中的样品从点样头排出

关键原理：样品不进入注射泵，始终暂存在长管路（>25mL）中。
泵只处理清洗液和空气。

端口映射（T-04）：
    端口 1：清洗液
    端口 2：废液
    端口 3：输出 → 三通阀 → 上样/点样流路
    端口 4：空气（直通大气）
    公共端 C：注射泵

协议：DT (Data Terminal) 协议

参考文档：docs/superpowers/specs/2026-05-31-sample-pump-v2-design.md
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 导入 v1 构建函数和硬件常量（复用）
# ---------------------------------------------------------------------------
from sample_pump_translator import (
    # 端口常量
    T04_WASH_PORT,
    T04_WASTE_PORT,
    T04_OUTPUT_PORT,
    T04_AIR_PORT,
    # 硬件常量
    SYRINGE_STEPS,
    SYRINGE_ML,
    ASP_SPEED,
    DISP_SPEED,
    STEP_DELAY,
    # 构建函数
    build_segment_cmd,
    build_aspirate_cmd,
    build_dispense_all_cmd,
    # 辅助函数
    pump_init_cmd,
    pump_query_cmd,
    # 体积转换
    _ml_to_steps,
)

# ---------------------------------------------------------------------------
# v2 专用常量别名（与 v1 一致，但语义更清晰）
# ---------------------------------------------------------------------------
WASH_PORT = T04_WASH_PORT     # 端口 1：清洗液
WASTE_PORT = T04_WASTE_PORT   # 端口 2：废液
OUTPUT_PORT = T04_OUTPUT_PORT # 端口 3：输出口 → 三通阀
AIR_PORT = T04_AIR_PORT       # 端口 4：空气

# v2 默认参数
DEFAULT_MARGIN_ML = 1.0       # 空气余量 (mL)
DEFAULT_WASH_ML = 25.0        # Step 1 单次清洗体积 (mL)


# ---------------------------------------------------------------------------
# 参数校验
# ---------------------------------------------------------------------------
def validate_sample_v2_params(
    sample_volume_ml: float,
    margin_volume_ml: float,
    wash_volume_ml: float = DEFAULT_WASH_ML,
    syringe_ml: float = SYRINGE_ML,
) -> None:
    """校验 v2 策略参数合法性。

    Raises:
        ValueError: 参数超出合法范围
    """
    if sample_volume_ml <= 0:
        raise ValueError(
            f"上样体积必须 > 0 mL，收到 {sample_volume_ml}"
        )
    if margin_volume_ml < 0:
        raise ValueError(
            f"空气余量必须 >= 0 mL，收到 {margin_volume_ml}"
        )
    if wash_volume_ml <= 0 or wash_volume_ml > syringe_ml:
        raise ValueError(
            f"清洗体积必须在 0-{syringe_ml} mL 之间，收到 {wash_volume_ml}"
        )

    peak = 2 * sample_volume_ml + margin_volume_ml
    if peak > syringe_ml:
        raise ValueError(
            f"泵腔峰值体积 {peak:.1f} mL 超出量程 {syringe_ml} mL "
            f"(sample={sample_volume_ml}, margin={margin_volume_ml})"
        )


# ---------------------------------------------------------------------------
# 体积预算
# ---------------------------------------------------------------------------
def calc_v2_volume_budget(
    sample_volume_ml: float,
    margin_volume_ml: float,
) -> dict:
    """计算 v2 流程各阶段体积。

    Args:
        sample_volume_ml: 上样体积 (mL)
        margin_volume_ml: 空气余量 (mL)

    Returns:
        dict with keys:
            step2_air_ml:       Step 2 回抽空气体积
            step3_sample_ml:    Step 3 吸取样品体积
            step4_waste_ml:     Step 4 排废液体积
            step5_drive_air_ml: Step 5 驱动空气体积
            step6_dispense_ml:  Step 6 点样打出体积
            peak_pump_ml:       泵腔峰值体积
    """
    return {
        "step2_air_ml": sample_volume_ml + margin_volume_ml,
        "step3_sample_ml": sample_volume_ml,
        "step4_waste_ml": 2 * sample_volume_ml + margin_volume_ml,
        "step5_drive_air_ml": sample_volume_ml,
        "step6_dispense_ml": sample_volume_ml,
        "peak_pump_ml": 2 * sample_volume_ml + margin_volume_ml,
    }


# ---------------------------------------------------------------------------
# 核心翻译函数
# ---------------------------------------------------------------------------
def translate_sample_v2_cmd(
    sample_volume_ml: float,
    *,
    margin_volume_ml: float = DEFAULT_MARGIN_ML,
    wash_volume_ml: float = DEFAULT_WASH_ML,
    pump_addr: str = "1",
    syringe_ml: float = SYRINGE_ML,
    asp_speed: int = ASP_SPEED,
    disp_speed: int = DISP_SPEED,
    step_delay: int = STEP_DELAY,
    wash_port: int = WASH_PORT,
    waste_port: int = WASTE_PORT,
    air_port: int = AIR_PORT,
    output_port: int = OUTPUT_PORT,
) -> list[str]:
    """生成 v2 空气驱动上样点样完整 DT 指令序列。

    Step 1: 单次复合清洗（PLC 循环调用）
    Step 2: 上样针在空气中，回抽空气段 (sample + margin)
    Step 3: 上样针入样品液，吸取样品
    Step 4: 切换废液口，排掉被置换入泵腔的清洗液
    Step 5: 切换空气口，抽取驱动空气
    Step 6: 三通阀切点样路，打出驱动空气，推动样品点出

    Args:
        sample_volume_ml: 上样体积 (mL)，典型 5mL
        margin_volume_ml: 空气余量 (mL)，默认 1mL
        wash_volume_ml: Step 1 单次清洗体积 (mL)，默认 25mL
        pump_addr: DT 协议地址，默认 '1'
        syringe_ml: 注射泵量程 (mL)
        asp_speed: 吸液速度
        disp_speed: 打液速度（上限 500）
        step_delay: 步骤间延迟 (ms)
        wash_port: 清洗液端口号
        waste_port: 废液端口号
        air_port: 空气端口号
        output_port: 输出端口号

    Returns:
        DT 协议指令字符串列表（固定 6 条），按执行顺序排列。

    Raises:
        ValueError: 参数超出合法范围
    """
    # 参数校验
    if disp_speed > 500:
        raise ValueError(f"打液速度不能超过 500，收到 {disp_speed}")
    validate_sample_v2_params(
        sample_volume_ml, margin_volume_ml, wash_volume_ml, syringe_ml
    )

    commands: list[str] = []

    # ---- Step 1: 单次复合清洗（PLC 外部循环） ----
    # 从清洗液端口吸 wash_volume → 打向输出口清洗上样针和点样器
    commands.append(
        build_segment_cmd(
            wash_volume_ml, wash_port,
            pump_addr, asp_speed, disp_speed, step_delay,
            output_port,
        )
    )

    # ---- Step 2: 从上样针侧回抽空气（上样针在空气中） ----
    # 空气进入管路，等体积清洗液被置换入泵腔
    step2_vol = sample_volume_ml + margin_volume_ml
    commands.append(
        build_aspirate_cmd(
            step2_vol, output_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 3: 上样针入样品液，吸取样品 ----
    # 样品进入管路前端，等体积清洗液继续被置换入泵腔
    commands.append(
        build_aspirate_cmd(
            sample_volume_ml, output_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 4: 切换废液口，排出泵腔内的清洗液 ----
    # 全打出归零，将 Step 2+3 中置换入泵腔的清洗液排到废液
    commands.append(
        build_dispense_all_cmd(
            pump_addr, disp_speed, step_delay, waste_port,
        )
    )

    # ---- Step 5: 切换空气口，抽取驱动空气 ----
    commands.append(
        build_aspirate_cmd(
            sample_volume_ml, air_port,
            pump_addr, asp_speed, step_delay,
        )
    )

    # ---- Step 6: 三通阀切点样路，打出驱动空气 ----
    # 驱动空气推动管路中的样品从点样头排出
    commands.append(
        build_dispense_all_cmd(
            pump_addr, disp_speed, step_delay, output_port,
        )
    )

    return commands


# ---------------------------------------------------------------------------
# 命令行预览
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    sample_vol = 5.0
    margin_vol = 1.0
    wash_vol = 25.0

    if len(sys.argv) >= 2:
        sample_vol = float(sys.argv[1])
    if len(sys.argv) >= 3:
        margin_vol = float(sys.argv[2])
    if len(sys.argv) >= 4:
        wash_vol = float(sys.argv[3])

    cmds = translate_sample_v2_cmd(
        sample_vol,
        margin_volume_ml=margin_vol,
        wash_volume_ml=wash_vol,
    )
    budget = calc_v2_volume_budget(sample_vol, margin_vol)

    print(f"# 上样注射泵 v2 (空气驱动)")
    print(f"# 参数: sample={sample_vol}mL, margin={margin_vol}mL, wash={wash_vol}mL")
    print(f"# 泵腔峰值: {budget['peak_pump_ml']:.1f} mL / {SYRINGE_ML} mL")
    print(f"# 指令数: {len(cmds)}")
    print()

    step_labels = [
        f"Step 1 清洗 (吸{wash_vol}mL→打出)",
        f"Step 2 回抽空气 ({budget['step2_air_ml']:.1f}mL, 上样针空气中)",
        f"Step 3 吸取样品 ({budget['step3_sample_ml']:.1f}mL, 上样针入样品)",
        f"Step 4 排废液 ({budget['step4_waste_ml']:.1f}mL, 全打出至废液口)",
        f"Step 5 驱动空气 ({budget['step5_drive_air_ml']:.1f}mL, 从空气口吸入)",
        f"Step 6 点样打出 ({budget['step6_dispense_ml']:.1f}mL, 全打出至点样流路)",
    ]

    for i, cmd in enumerate(cmds):
        label = step_labels[i]
        print(f"[{i:02d}] {label}")
        print(f"    {cmd}")
        print()

    print(f"初始化: {pump_init_cmd('1', output_port=OUTPUT_PORT)}")
    print(f"状态查: {pump_query_cmd('1')}")
```

- [ ] **Step 2: 命令行验证 translator v2**

```bash
cd /e/PHD/PKU/MoGroup/pTLC_platform/EIT_Project/UI-Upper/scripts
python sample_pump_translator_v2.py 5.0 1.0 25.0
```

预期：输出 6 条 DT 指令，带 Step 1~6 标签，泵腔峰值 11.0 mL。

- [ ] **Step 3: 验证超量程报错**

```bash
python sample_pump_translator_v2.py 13.0 1.0
```

预期：ValueError，提示 27.0 mL 超出 25 mL 量程。

- [ ] **Step 4: 验证零余量边界**

```bash
python sample_pump_translator_v2.py 5.0 0.0
```

预期：6 条指令，peak=10.0 mL，margin=0 仍正常。

- [ ] **Step 5: Commit**

```bash
git add UI-Upper/scripts/sample_pump_translator_v2.py
git commit -m "feat(sample-pump): add v2 air-driven sample spotting translator

- translate_sample_v2_cmd: 6-step air-driven spotting strategy
- calc_v2_volume_budget: pump volume budget calculation
- validate_sample_v2_params: parameter validation with peak capacity check
- reuses v1 build functions (build_segment_cmd, build_aspirate_cmd, build_dispense_all_cmd)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: 创建 test_sample_v2.py 测试脚本

**Files:**
- Create: `UI-Upper/scripts/test_sample_v2.py`

- [ ] **Step 1: 写测试脚本**

完整文件内容：

```python
"""测试脚本：v2 空气驱动上样策略 → 输出注射泵 DT 指令

用法:
    python test_sample_v2.py
    python test_sample_v2.py 5.0
    python test_sample_v2.py 5.0 --margin 1.0
    python test_sample_v2.py 5.0 --margin 1.0 --addr 1 --wash 25.0
    python test_sample_v2.py 5.0 --valve T06 --wash-port 1 --waste-port 3 --air-port 2 --output-port 6
"""

import argparse
import sys

from sample_pump_translator_v2 import (
    translate_sample_v2_cmd,
    calc_v2_volume_budget,
    validate_sample_v2_params,
    pump_init_cmd,
    pump_query_cmd,
    SYRINGE_ML,
    SYRINGE_STEPS,
    ASP_SPEED,
    DISP_SPEED,
    STEP_DELAY,
    WASH_PORT,
    WASTE_PORT,
    AIR_PORT,
    OUTPUT_PORT,
    DEFAULT_MARGIN_ML,
    DEFAULT_WASH_ML,
)
from sample_pump_translator import (
    T04_WASH_PORT,
    T04_WASTE_PORT,
    T04_OUTPUT_PORT,
    T04_AIR_PORT,
)

# 分配阀默认端口（按阀类型）
VALVE_DEFAULTS = {
    "T04": {
        "wash": T04_WASH_PORT,
        "waste": T04_WASTE_PORT,
        "air": T04_AIR_PORT,
        "output": T04_OUTPUT_PORT,
    },
    "T06": {
        "wash": 1,
        "waste": 3,
        "air": 2,
        "output": 6,
    },
}

STEP_LABELS = [
    "Step1 [清洗] 吸清洗液→打输出口",
    "Step2 [回抽空气] 上样针在空气中",
    "Step3 [吸取样品] 上样针入样品液",
    "Step4 [排废液] 全打出至废液口",
    "Step5 [驱动空气] 从空气口吸入",
    "Step6 [点样打出] 全打出至点样流路",
]


def print_commands(cmds, budget):
    """打印指令序列，含阶段标签和体积信息。"""
    step_vols = [
        ("wash", budget.get("wash_ml", budget.get("step1_wash_ml", "?"))),
        ("air gap", f"{budget['step2_air_ml']:.1f} mL"),
        ("sample", f"{budget['step3_sample_ml']:.1f} mL"),
        ("waste", f"{budget['step4_waste_ml']:.1f} mL (A0)"),
        ("drive air", f"{budget['step5_drive_air_ml']:.1f} mL"),
        ("spot", f"{budget['step6_dispense_ml']:.1f} mL (A0)"),
    ]

    for i, cmd in enumerate(cmds):
        label = STEP_LABELS[i]
        vol_label = step_vols[i]
        print(f"[{i:02d}] {label:40s} {str(vol_label):24s} {cmd}")


def main():
    parser = argparse.ArgumentParser(
        description="sample_pump_translator_v2 DT 指令测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_sample_v2.py
  python test_sample_v2.py 5.0
  python test_sample_v2.py 5.0 --margin 1.0 --wash 25.0
  python test_sample_v2.py 5.0 --valve T06 --wash-port 1 --waste-port 3 --air-port 2 --output-port 6
        """,
    )
    parser.add_argument("sample", nargs="?", type=float, default=None,
                        help="上样体积 (mL)，典型 5mL")
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN_ML,
                        help=f"空气余量 (mL)，默认 {DEFAULT_MARGIN_ML}")
    parser.add_argument("--wash", type=float, default=DEFAULT_WASH_ML,
                        help=f"单次清洗体积 (mL)，默认 {DEFAULT_WASH_ML}")
    parser.add_argument("--valve", type=str, default="T04", choices=["T04", "T06"],
                        help="分配阀类型: T04 (4通道) 或 T06 (6通道)，默认 T04")
    parser.add_argument("--addr", type=str, default="1",
                        help="泵 DT 地址，默认 1")
    parser.add_argument("--wash-port", type=int, default=None,
                        help="清洗液端口号（默认随 --valve 自动设置）")
    parser.add_argument("--waste-port", type=int, default=None,
                        help="废液端口号（默认随 --valve 自动设置）")
    parser.add_argument("--air-port", type=int, default=None,
                        help="空气端口号（默认随 --valve 自动设置）")
    parser.add_argument("--output-port", type=int, default=None,
                        help="输出端口号（默认随 --valve 自动设置）")
    parser.add_argument("--asp-speed", type=int, default=ASP_SPEED,
                        help=f"吸液速度，默认 {ASP_SPEED}")
    parser.add_argument("--disp-speed", type=int, default=DISP_SPEED,
                        help=f"打液速度，默认 {DISP_SPEED}")
    parser.add_argument("--delay", type=int, default=STEP_DELAY,
                        help=f"步骤间延迟 (ms)，默认 {STEP_DELAY}")

    args = parser.parse_args()

    # 参数获取：命令行 > 交互输入
    if args.sample is not None:
        sample_vol = args.sample
    else:
        print("上样注射泵 v2 (空气驱动) DT 指令测试")
        print("-" * 50)
        sample_vol = float(
            input(f"上样体积 (mL, >0): ") or "5.0"
        )
        args.margin = float(
            input(f"空气余量 (mL, 默认 {DEFAULT_MARGIN_ML}): ") or DEFAULT_MARGIN_ML
        )
        args.wash = float(
            input(f"单次清洗体积 (mL, 默认 {DEFAULT_WASH_ML}): ") or DEFAULT_WASH_ML
        )
        args.valve = input("分配阀类型 (T04/T06, 默认 T04): ").strip().upper() or "T04"
        vd = VALVE_DEFAULTS.get(args.valve, VALVE_DEFAULTS["T04"])
        args.wash_port = int(input(f"清洗液端口 (默认 {vd['wash']}): ") or vd["wash"])
        args.waste_port = int(input(f"废液端口 (默认 {vd['waste']}): ") or vd["waste"])
        args.air_port = int(input(f"空气端口 (默认 {vd['air']}): ") or vd["air"])
        args.output_port = int(input(f"输出端口 (默认 {vd['output']}): ") or vd["output"])
        args.addr = input("泵 DT 地址 (默认 1): ") or "1"
        args.asp_speed = int(input(f"吸液速度 (默认 {ASP_SPEED}): ") or ASP_SPEED)
        args.disp_speed = int(input(f"打液速度 (默认 {DISP_SPEED}, 上限 500): ") or DISP_SPEED)
        args.delay = int(input(f"步骤间延迟 ms (默认 {STEP_DELAY}): ") or STEP_DELAY)

    # 解析端口
    vd = VALVE_DEFAULTS.get(args.valve, VALVE_DEFAULTS["T04"])
    wash_port = args.wash_port if args.wash_port is not None else vd["wash"]
    waste_port = args.waste_port if args.waste_port is not None else vd["waste"]
    air_port = args.air_port if args.air_port is not None else vd["air"]
    output_port = args.output_port if args.output_port is not None else vd["output"]

    # 校验参数
    validate_sample_v2_params(sample_vol, args.margin, args.wash)

    # 生成指令
    cmds = translate_sample_v2_cmd(
        sample_vol,
        margin_volume_ml=args.margin,
        wash_volume_ml=args.wash,
        pump_addr=args.addr,
        asp_speed=args.asp_speed,
        disp_speed=args.disp_speed,
        step_delay=args.delay,
        wash_port=wash_port,
        waste_port=waste_port,
        air_port=air_port,
        output_port=output_port,
    )
    budget = calc_v2_volume_budget(sample_vol, args.margin)
    # 补充清洗体积到 budget 用于显示
    budget["wash_ml"] = args.wash

    # 输出
    print()
    print(f"{'='*70}")
    print(f"  阀类型: {args.valve}  |  泵地址: {args.addr}  |  上样: {sample_vol} mL  |  余量: {args.margin} mL")
    print(f"  端口: wash={wash_port} waste={waste_port} air={air_port} output={output_port}")
    print(f"  清洗: {args.wash} mL  |  泵腔峰值: {budget['peak_pump_ml']:.1f} mL / {SYRINGE_ML} mL  |  指令数: {len(cmds)}")
    print(f"{'='*70}")
    print()

    print_commands(cmds, budget)

    # 初始化 / 状态查询
    print()
    print(f"  初始化: {pump_init_cmd(args.addr, output_port=output_port)}")
    print(f"  状态查: {pump_query_cmd(args.addr)}")
    print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证测试脚本 — 命令行模式**

```bash
cd /e/PHD/PKU/MoGroup/pTLC_platform/EIT_Project/UI-Upper/scripts
python test_sample_v2.py 5.0 --margin 1.0
```

预期：输出参数摘要、体积预算、6 条指令带标签、初始化/状态查询。

- [ ] **Step 3: 验证测试脚本 — T06 阀**

```bash
python test_sample_v2.py 5.0 --valve T06
```

预期：端口自动切换为 T06 默认值 (wash=1, waste=3, air=2, output=6)。

- [ ] **Step 4: 验证报错用例**

```bash
python test_sample_v2.py 13.0 --margin 1.0
```

预期：ValueError（超量程）。

- [ ] **Step 5: Commit**

```bash
git add UI-Upper/scripts/test_sample_v2.py
git commit -m "test(sample-pump): add v2 test script with CLI and interactive modes

- Supports positional sample_vol and optional --margin, --wash flags
- Supports --valve T04/T06 with automatic port mapping
- Interactive mode when no CLI arguments provided
- Displays volume budget and step-labeled DT commands

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: 最终验证与收尾

- [ ] **Step 1: 运行完整验证**

```bash
cd /e/PHD/PKU/MoGroup/pTLC_platform/EIT_Project/UI-Upper/scripts

echo "=== Test 1: 典型参数 (5mL sample, 1mL margin) ==="
python test_sample_v2.py 5.0 --margin 1.0

echo ""
echo "=== Test 2: 零余量 ==="
python test_sample_v2.py 5.0 --margin 0.0

echo ""
echo "=== Test 3: 大体积 ==="
python test_sample_v2.py 10.0 --margin 2.0

echo ""
echo "=== Test 4: 超量程报错 ==="
python test_sample_v2.py 13.0 --margin 1.0 2>&1 || echo "Expected error caught"

echo ""
echo "=== Test 5: T06 阀 ==="
python test_sample_v2.py 5.0 --valve T06

echo ""
echo "=== Test 6: v2 translator CLI ==="
python sample_pump_translator_v2.py 5.0 1.0 25.0
```

预期：Test 1-3, 5-6 正常输出 6 条指令；Test 4 抛出 ValueError。

- [ ] **Step 2: 对比 v1/v2 指令差异**

```bash
echo "=== v1 (气泡分段) ==="
python sample_pump_translator.py 2.0 1.0 3

echo ""
echo "=== v2 (空气驱动) ==="
python test_sample_v2.py 5.0 --margin 1.0
```

确认 v1 输出多条指令（分段制备），v2 固定输出 6 条。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-31-sample-pump-v2-design.md
git add docs/superpowers/plans/2026-05-31-sample-pump-v2-plan.md
git commit -m "docs: add sample pump v2 design spec and implementation plan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
