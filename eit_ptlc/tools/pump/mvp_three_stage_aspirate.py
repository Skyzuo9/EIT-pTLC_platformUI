"""三段速抽吸 MVP 指令生成器 (SY-03B / DT 协议, 只生成"抽"方向指令)
====================================================================
目的:
    上机验证"前慢-中快-尾慢"抽吸能否像全程 V3 一样压掉停泵后的液柱回落,
    同时把中段时间省回来。脚本只打印指令文本, 不连泵; 把指令粘进串口
    助手发送 (行尾需回车 CR, 即 \\r)。

物理背景 (为什么是这个形状):
    气塞是气体弹簧。抽吸时粘性压降 ∝ 流速, 弹簧被拉伸; 活塞骤停时压降
    消失, 弹簧回缩 → 液柱回落/滴液。尾段低速让压差在停泵前就衰减到接近
    静态, 停泵瞬间无落差可回; 前段低速避免起步压差阶跃拉断液柱。

用法示例 (任意 Python 3, 无第三方依赖):
    python mvp_three_stage_aspirate.py
    python mvp_three_stage_aspirate.py --total 3 --lead 0.2 --tail 0.3 --slow 3
    python mvp_three_stage_aspirate.py --sweep            # 慢速 × 尾段体积 扫参矩阵
    python mvp_three_stage_aspirate.py --absolute         # 用绝对 A 指令 (从 0 位开始)

注意:
    - 默认生成 P 相对指令, 在当前活塞位上叠加; 最终位置超 6000 泵报错 3 拒动。
    - 每组实验之间请手动排空回零 (例如打废液口: /4V100I2A0R), 本脚本按需求
      只生成抽的指令。
    - 一切都在 N0 正常模式下, 不涉及细分模式, 无需改泵配置。
"""

from __future__ import annotations

import argparse

SYRINGE_STEPS = 6000        # 25 mL 满行程半步数 (N0 正常模式)
SYRINGE_ML = 25.0           # 注射泵量程 (mL)
DEFAULT_ADDR = "4"          # 上样泵 DT 地址
DEFAULT_PORT = 3            # T-04 输出口 (上样/点样流路)


def ml_to_steps(volume_ml: float) -> int:
    """毫升 → 半步数 (N0)。"""
    return int(round(volume_ml * SYRINGE_STEPS / SYRINGE_ML))


def steps_to_ml(steps: int) -> float:
    """半步数 → 毫升。"""
    return steps * SYRINGE_ML / SYRINGE_STEPS


def est_seconds(stages: list[tuple[int, int]], settle_ms: int) -> float:
    """粗估耗时 (忽略斜坡): Σ(步数/速度) + 驻留。"""
    return sum(n / v for n, v in stages if n > 0) + settle_ms / 1000.0


def build_single(
    total_steps: int, speed: int, settle_ms: int,
    addr: str, port: int, absolute: bool,
) -> tuple[str, list[tuple[int, int]]]:
    """单段速抽吸 (对照组), 返回 (指令, 分段列表[(步数,速度)])。"""
    move = f"A{total_steps}" if absolute else f"P{total_steps}"
    cmd = f"/{addr}V{speed}I{port}{move}M{settle_ms}R"
    return cmd, [(total_steps, speed)]


def build_three_stage(
    total_steps: int, lead_steps: int, tail_steps: int,
    fast: int, slow: int, settle_ms: int,
    addr: str, port: int, absolute: bool,
) -> tuple[str, list[tuple[int, int]]]:
    """三段速抽吸: 前 lead 慢 → 中段快 → 尾 tail 慢 → 驻留 settle。

    步数守恒: mid = total - lead - tail, 取整误差全部归中段;
    lead + tail >= total 时退化为全程慢速。
    """
    mid_steps = total_steps - lead_steps - tail_steps
    if mid_steps <= 0:
        return build_single(total_steps, slow, settle_ms, addr, port, absolute)
    if absolute:
        m1, m2, m3 = (
            f"A{lead_steps}",
            f"A{lead_steps + mid_steps}",
            f"A{total_steps}",
        )
    else:
        m1, m2, m3 = f"P{lead_steps}", f"P{mid_steps}", f"P{tail_steps}"
    cmd = (
        f"/{addr}V{slow}I{port}{m1}"
        f"V{fast}{m2}"
        f"V{slow}{m3}M{settle_ms}R"
    )
    return cmd, [(lead_steps, slow), (mid_steps, fast), (tail_steps, slow)]


def show(label: str, desc: str, cmd: str, stages: list[tuple[int, int]], settle_ms: int) -> None:
    parts = " + ".join(f"{n}步({steps_to_ml(n):.2f}mL)@V{v}" for n, v in stages)
    print(f"[{label}] {desc}")
    print(f"    {cmd}")
    print(f"    分段: {parts} | 驻留 {settle_ms} ms | 预计约 {est_seconds(stages, settle_ms):.0f} s")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="三段速抽吸 MVP 指令生成 (仅抽方向)")
    ap.add_argument("--total", type=float, default=3.0, help="总抽吸体积 mL (默认 3.0)")
    ap.add_argument("--lead", type=float, default=0.2, help="前段慢速体积 mL (默认 0.2)")
    ap.add_argument("--tail", type=float, default=0.3, help="尾段慢速体积 mL (默认 0.3)")
    ap.add_argument("--fast", type=int, default=250, help="中段速度 半步/s (默认 250, 现行 ASP_SPEED)")
    ap.add_argument("--slow", type=int, default=3, help="慢段速度 半步/s (默认 3, 即你验证过的 V3)")
    ap.add_argument("--settle", type=int, default=3000, help="尾段后驻留 ms (默认 3000)")
    ap.add_argument("--addr", default=DEFAULT_ADDR, help="泵 DT 地址 (默认 4)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="吸液端口 (默认 3 输出口)")
    ap.add_argument("--absolute", action="store_true", help="用绝对 A 指令 (须从 0 位开始); 默认相对 P")
    ap.add_argument("--sweep", action="store_true", help="额外输出 慢速{1,3,5} × 尾段{0.1,0.2,0.3}mL 扫参矩阵")
    args = ap.parse_args()

    if not 0 < args.total <= SYRINGE_ML:
        ap.error(f"--total 须在 (0, {SYRINGE_ML}] mL")
    for name in ("fast", "slow"):
        v = getattr(args, name)
        if not 1 <= v <= 6000:
            ap.error(f"--{name} 须在 1..6000 半步/s")

    total = ml_to_steps(args.total)
    lead = ml_to_steps(args.lead)
    tail = ml_to_steps(args.tail)

    print(f"# SY-03B 三段速抽吸 MVP | 泵{args.addr} 口{args.port} | "
          f"{'绝对A' if args.absolute else '相对P'} | 1 mL = {SYRINGE_STEPS / SYRINGE_ML:.0f} 半步")
    print(f"# 参数: total={args.total}mL lead={args.lead}mL tail={args.tail}mL "
          f"fast=V{args.fast} slow=V{args.slow} settle={args.settle}ms")
    print("# 指令行尾需回车(CR); 组间请自行排空回零。观察点: 停泵瞬间液柱回落行程 + 针尖是否滴液。")
    print()

    cmd, st = build_single(total, args.fast, args.settle, args.addr, args.port, args.absolute)
    show("A", f"对照: 全程快速 V{args.fast} (现行行为)", cmd, st, args.settle)

    cmd, st = build_single(total, args.slow, args.settle, args.addr, args.port, args.absolute)
    show("B", f"对照: 全程慢速 V{args.slow} (已验证有效, 但最慢)", cmd, st, args.settle)

    cmd, st = build_three_stage(total, lead, tail, args.fast, args.slow,
                                args.settle, args.addr, args.port, args.absolute)
    show("C", "三段速: 前慢-中快-尾慢 (待验证)", cmd, st, args.settle)

    if args.sweep:
        print("# ---- 扫参矩阵: 慢速 × 尾段体积 (lead 固定) ----")
        print()
        for slow in (1, 3, 5):
            for tail_ml in (0.1, 0.2, 0.3):
                cmd, st = build_three_stage(
                    total, lead, ml_to_steps(tail_ml), args.fast, slow,
                    args.settle, args.addr, args.port, args.absolute,
                )
                show(f"S{slow}-t{tail_ml}", f"slow=V{slow}, tail={tail_ml}mL",
                     cmd, st, args.settle)


if __name__ == "__main__":
    main()
