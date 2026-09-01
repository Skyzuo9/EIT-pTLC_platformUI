"""测试脚本：输入样品体积、空气隔离段 → 输出注射泵 DT 指令 (v2 空气驱动)

用法:
    python test_sample_v2.py
    python test_sample_v2.py 5.0 --air-buffer 3.0
    python test_sample_v2.py 5.0 --valve T06
    python test_sample_v2.py 23.0 --air-buffer 3.0    # 期望报错（峰值26>25）
    python test_sample_v2.py 5.0 --air-buffer 3.0 --addr 2 --asp-speed 500 --disp-speed 300
"""

import argparse
import sys

from sample_pump_translator_v2 import (
    translate_sample_v2_cmd, calc_v2_volume_budget, validate_sample_v2_params,
    build_clean_array, build_prep_array, build_sample_array, build_dispense_array,
    pump_init_cmd, pump_query_cmd,
    SYRINGE_ML, SYRINGE_STEPS, ASP_SPEED, DISP_SPEED, STEP_DELAY,
    WASH_PORT, WASTE_PORT, AIR_PORT, OUTPUT_PORT,
    DEFAULT_AIR_BUFFER_ML, DEFAULT_WASH_ML, DEFAULT_PUMP_ADDR, DEFAULT_RETRACT_ML,
)
from sample_pump_translator import (
    T04_WASH_PORT, T04_WASTE_PORT, T04_OUTPUT_PORT, T04_AIR_PORT,
)

VALVE_DEFAULTS = {
    "T04": {"wash": T04_WASH_PORT, "waste": T04_WASTE_PORT, "air": T04_AIR_PORT, "output": T04_OUTPUT_PORT},
    "T06": {"wash": 1, "waste": 3, "air": 2, "output": 6},
}

STEP_LABELS = [
    "Step1 [清洗] 吸清洗液→打输出口",
    "Step2 [回抽空气] 隔离段",
    "Step3 [吸取样品] 上样针入样品液",
    "Step4 [排废液] 全打出至废液口",
    "Step5 [驱动空气] 从空气口吸入",
    "Step6 [点样打出] 全打出至点样流路",
    "Step7 [回抽释压] 分配阀仍指向点样器",
]


def print_commands(cmds, budget, wash_vol):
    """Print each command with its step label and volume info from budget dict."""
    volumes = [
        f"{wash_vol:.1f} mL",
        f"{budget['step2_air_ml']:.1f} mL",
        f"{budget['step3_sample_ml']:.1f} mL",
        f"{budget['step4_waste_ml']:.1f} mL (A0)",
        f"{budget['step5_drive_air_ml']:.1f} mL",
        f"{budget['step6_dispense_ml']:.1f} mL (A0)",
    ]
    retract = budget.get('step7_retract_ml', 0)
    if retract > 0:
        volumes.append(f"{retract:.1f} mL")
    for i, cmd in enumerate(cmds):
        print(f"[{i:02d}] {STEP_LABELS[i]:30s} {volumes[i]:18s} {cmd}")


def main():
    parser = argparse.ArgumentParser(
        description="sample_pump_translator_v2 DT 指令测试 (空气驱动策略)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_sample_v2.py
  python test_sample_v2.py 5.0 --air-buffer 3.0
  python test_sample_v2.py 5.0 --valve T06
  python test_sample_v2.py 5.0 --air-buffer 3.0 --addr 2 --asp-speed 500 --disp-speed 300
        """,
    )
    parser.add_argument("sample", nargs="?", type=float, default=None,
                        help="上样体积 (mL)")
    parser.add_argument("--air-buffer", type=float, default=DEFAULT_AIR_BUFFER_ML,
                        help=f"空气隔离段体积 (mL)，默认 {DEFAULT_AIR_BUFFER_ML}")
    parser.add_argument("--wash", type=float, default=25.0,
                        help=f"单次清洗体积 (mL)，默认 {DEFAULT_WASH_ML}")
    parser.add_argument("--valve", type=str, default="T04", choices=["T04", "T06"],
                        help="分配阀类型: T04 (4通道) 或 T06 (6通道)，默认 T04")
    parser.add_argument("--addr", type=str, default=DEFAULT_PUMP_ADDR,
                        help=f"泵 DT 地址，默认 {DEFAULT_PUMP_ADDR}")
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
    parser.add_argument("--retract", type=float, default=DEFAULT_RETRACT_ML,
                        help=f"点样后回抽释压体积 (mL)，默认 {DEFAULT_RETRACT_ML}，0=不回抽")

    args = parser.parse_args()

    # 参数获取：命令行 > 交互输入
    if args.sample is not None:
        sample_vol = args.sample
        air_buffer = args.air_buffer
        wash = args.wash
    else:
        print("上样注射泵 v2 空气驱动策略 DT 指令测试")
        print("-" * 50)
        sample_vol = float(input("上样体积 (mL, >0): ") or "5.0")
        air_buffer = float(input(f"空气隔离段 (mL, 默认 {DEFAULT_AIR_BUFFER_ML}): ") or DEFAULT_AIR_BUFFER_ML)
        wash = float(input(f"单次清洗体积 (mL, 默认 {DEFAULT_WASH_ML}): ") or DEFAULT_WASH_ML)
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

    # 解析端口：命令行 > 交互输入 > 阀类型默认
    vd = VALVE_DEFAULTS.get(args.valve, VALVE_DEFAULTS["T04"])
    wash_port = args.wash_port if args.wash_port is not None else vd["wash"]
    waste_port = args.waste_port if args.waste_port is not None else vd["waste"]
    air_port = args.air_port if args.air_port is not None else vd["air"]
    output_port = args.output_port if args.output_port is not None else vd["output"]

    # 验证参数
    validate_sample_v2_params(sample_vol, air_buffer, wash)

    # 生成指令
    cmds = translate_sample_v2_cmd(
        sample_vol,
        air_buffer_ml=air_buffer,
        wash_volume_ml=wash,
        retract_volume_ml=args.retract,
        pump_addr=args.addr,
        asp_speed=args.asp_speed,
        disp_speed=args.disp_speed,
        step_delay=args.delay,
        wash_port=wash_port,
        waste_port=waste_port,
        air_port=air_port,
        output_port=output_port,
    )
    budget = calc_v2_volume_budget(sample_vol, air_buffer, args.retract)

    # 输出摘要
    print()
    print(f"{'='*70}")
    retract_info = f"  |  回抽: {args.retract} mL" if args.retract > 0 else "  |  回抽: 关闭"
    print(f"  阀类型: {args.valve}  |  泵地址: {args.addr}  |  样品体积: {sample_vol} mL  |  空气隔离段: {air_buffer} mL  |  清洗体积: {wash} mL{retract_info}")
    print(f"  端口: wash={wash_port} waste={waste_port} air={air_port} output={output_port}")
    print(f"  泵腔峰值: {budget['peak_pump_ml']:.1f} mL / {SYRINGE_ML} mL  |  指令数: {len(cmds)}")
    print(f"{'='*70}")
    print()

    print_commands(cmds, budget, wash)

    # 协议 v1.5：4 数组输出
    clean_arr = build_clean_array(
        wash, pump_addr=args.addr, asp_speed=args.asp_speed,
        disp_speed=args.disp_speed, step_delay=args.delay,
        wash_port=wash_port, waste_port=waste_port, output_port=output_port,
    )
    prep_arr = build_prep_array(
        sample_vol, air_buffer, pump_addr=args.addr, asp_speed=args.asp_speed,
        disp_speed=args.disp_speed, step_delay=args.delay,
        output_port=output_port, waste_port=waste_port,
    )
    sample_arr = build_sample_array(
        sample_vol, pump_addr=args.addr, asp_speed=args.asp_speed,
        disp_speed=args.disp_speed, step_delay=args.delay,
        output_port=output_port, waste_port=waste_port,
    )
    disp_arr = build_dispense_array(
        sample_vol, args.retract, pump_addr=args.addr, asp_speed=args.asp_speed,
        disp_speed=args.disp_speed, step_delay=args.delay,
        air_port=air_port, output_port=output_port,
    )

    print(f"{'='*70}")
    print(f"  协议 v1.5 — 4 个 1×2 数组（PLC 工程师校对用）")
    print(f"{'='*70}")
    for label, arr in [
        ("Sampling_clean_instructions    (Step 10)", clean_arr),
        ("Sampling_prep_instructions     (Step 20)", prep_arr),
        ("Sampling_sample_instructions   (Step 40)", sample_arr),
        ("Sampling_dispense_instructions (Step 50)", disp_arr),
    ]:
        print(f"\n  {label}:")
        for j, c in enumerate(arr):
            print(f"    [{j+1}] {c.strip()}")

    # 初始化 / 状态查询
    print()
    print(f"  初始化: {pump_init_cmd(args.addr, output_port=output_port)}")
    print(f"  状态查: {pump_query_cmd(args.addr)}")
    print()


if __name__ == "__main__":
    main()
