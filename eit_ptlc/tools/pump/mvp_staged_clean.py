"""一次抽液·分段清洗 MVP 指令生成器 (SY-03B / DT 协议)
====================================================================
目的:
    上机验证轻清洗方案: 满行程一次吸清洗液, 分段打向不同流路, 把管路
    重新充满液体(消除空气顺应性), 顺带完成外壁/点样头冲洗。
    默认分段 = 17mL→端口3(上样流路充液) + 5mL→端口2(针外壁) + 3mL→端口3(点样头)。

    脚本只打印指令文本, 不连泵; 粘进串口助手发送 (行尾需回车 CR, \\r)。
    默认输出"分段独立指令"(段间可手动切三通阀), 同时附原子链式版本
    (仅当全程无需外部阀切换时可用)。

用法示例 (任意 Python 3, 无第三方依赖):
    python mvp_staged_clean.py
    python mvp_staged_clean.py --stage 17,3,400 --stage 5,2,300 --stage 3,3,100
    python mvp_staged_clean.py --asp-speed 250 --delay 1500

--stage 格式: 体积mL,打液端口[,打速] (可重复, 按顺序执行; 打速缺省用 --disp-speed)

注意:
    - 各段体积之和 = 一次吸入总量, 不得超过量程 25 mL。
    - 打液速度守卫上限 500 (与主线 translator 一致); 充液段建议偏高速
      (V300-500) 以冲刷贴壁气泡, 点样头段可降速。
    - 分段执行前泵活塞应在 0 位; 吸液默认从端口 1 (清洗液)。
"""

from __future__ import annotations

import argparse

SYRINGE_STEPS = 6000        # 25 mL 满行程半步数 (N0 正常模式)
SYRINGE_ML = 25.0           # 注射泵量程 (mL)
DEFAULT_ADDR = "4"          # 上样泵 DT 地址
WASH_PORT = 1               # T-04 清洗液口
MAX_DISP_SPEED = 500        # 打液速度守卫上限 (同主线 translator)


def ml_to_steps(volume_ml: float) -> int:
    """毫升 → 半步数 (N0)。"""
    return int(round(volume_ml * SYRINGE_STEPS / SYRINGE_ML))


def steps_to_ml(steps: int) -> float:
    return steps * SYRINGE_ML / SYRINGE_STEPS


def parse_stage(text: str, default_speed: int) -> tuple[float, int, int]:
    """解析 --stage '体积,端口[,打速]' → (volume_ml, port, speed)。"""
    parts = text.split(",")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError(f"--stage 需要 '体积,端口[,打速]', 收到 {text!r}")
    volume_ml = float(parts[0])
    port = int(parts[1])
    speed = int(parts[2]) if len(parts) == 3 else default_speed
    if volume_ml <= 0:
        raise argparse.ArgumentTypeError(f"段体积必须 > 0, 收到 {volume_ml}")
    if not 1 <= port <= 4:
        raise argparse.ArgumentTypeError(f"端口须在 1..4, 收到 {port}")
    if not 1 <= speed <= MAX_DISP_SPEED:
        raise argparse.ArgumentTypeError(f"打速须在 1..{MAX_DISP_SPEED}, 收到 {speed}")
    return volume_ml, port, speed


def main() -> None:
    ap = argparse.ArgumentParser(description="一次抽液·分段清洗 MVP 指令生成")
    ap.add_argument("--stage", action="append", default=None, metavar="V,PORT[,SPD]",
                    help="一段: 体积mL,打液端口[,打速]; 可重复。缺省 = 17,3 / 5,2 / 3,3,100")
    ap.add_argument("--asp-speed", type=int, default=250, help="吸液速度 半步/s (默认 250)")
    ap.add_argument("--disp-speed", type=int, default=300,
                    help=f"打液默认速度 半步/s (默认 300, 上限 {MAX_DISP_SPEED})")
    ap.add_argument("--delay", type=int, default=1500, help="段间/结束 M 延时 ms (默认 1500)")
    ap.add_argument("--addr", default=DEFAULT_ADDR, help="泵 DT 地址 (默认 4)")
    ap.add_argument("--wash-port", type=int, default=WASH_PORT, help="吸液端口 (默认 1 清洗液)")
    args = ap.parse_args()

    if not 1 <= args.disp_speed <= MAX_DISP_SPEED:
        ap.error(f"--disp-speed 须在 1..{MAX_DISP_SPEED}")

    stage_texts = args.stage or ["17,3", "5,2", "3,3,100"]
    try:
        stages = [parse_stage(t, args.disp_speed) for t in stage_texts]
    except argparse.ArgumentTypeError as e:
        ap.error(str(e))

    total_ml = sum(v for v, _, _ in stages)
    if total_ml > SYRINGE_ML:
        ap.error(f"各段体积之和 {total_ml} mL 超过量程 {SYRINGE_ML} mL")
    total_steps = ml_to_steps(total_ml)

    # 各段的目标绝对位置 (从吸满位向 0 递减); 取整误差归最后一段 (终点恒为余量位)
    marks: list[int] = []
    pos = total_steps
    for volume_ml, _, _ in stages:
        pos -= ml_to_steps(volume_ml)
        marks.append(max(pos, 0))
    marks[-1] = total_steps - sum(ml_to_steps(v) for v, _, _ in stages)
    marks[-1] = max(marks[-1], 0)

    print(f"# SY-03B 一次抽液·分段清洗 MVP | 泵{args.addr} | 1 mL = {SYRINGE_STEPS / SYRINGE_ML:.0f} 半步")
    print(f"# 吸液: {total_ml} mL @V{args.asp_speed} 自端口{args.wash_port} | 段间延时 {args.delay} ms")
    print("# 指令行尾需回车(CR)。执行前活塞应在 0 位。")
    print()

    print("## 方式一: 分段独立指令 (段间可手动/由PLC切三通阀) —— 推荐先用这个做台架实验")
    print()
    asp_cmd = f"/{args.addr}V{args.asp_speed}I{args.wash_port}A{total_steps}M{args.delay}R"
    asp_secs = total_steps / args.asp_speed + args.delay / 1000.0
    print(f"[吸] 吸满 {total_ml} mL (至 A{total_steps}), 约 {asp_secs:.0f} s")
    print(f"    {asp_cmd}")
    print()
    prev = total_steps
    chain_moves: list[str] = []
    for i, ((volume_ml, port, speed), mark) in enumerate(zip(stages, marks), start=1):
        seg_steps = prev - mark
        secs = seg_steps / speed + args.delay / 1000.0
        cmd = f"/{args.addr}V{speed}I{port}A{mark}M{args.delay}R"
        print(f"[打{i}] {volume_ml} mL → 端口{port} @V{speed} (A{prev}→A{mark}, "
              f"{steps_to_ml(seg_steps):.2f} mL), 约 {secs:.0f} s")
        print(f"    {cmd}")
        print()
        chain_moves.append(f"V{speed}I{port}A{mark}M{args.delay}")
        prev = mark

    print("## 方式二: 原子链式指令 (一条到底, 中途不等外部阀切换 —— 仅当全程无需切三通时可用)")
    print()
    chain = (f"/{args.addr}V{args.asp_speed}I{args.wash_port}A{total_steps}M{args.delay}"
             + "".join(chain_moves) + "R")
    print(f"    {chain}")
    print(f"    (指令长度 {len(chain)} 字符, 缓冲区上限 255)")


if __name__ == "__main__":
    main()
