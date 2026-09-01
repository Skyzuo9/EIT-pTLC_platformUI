"""展缸编号自洽性验收: 机器人点表 P11..P18 ↔ 三维 TANK_1..8 ↔ 缸盖 dev_t{架}_cyl{层}。

为什么单独成一个可重复跑的脚本: 这条链错了**画面看着完全正常** —— 板稳稳落进一个缸、
缸盖也照常开合, 只是那不是机器实际用的那个缸, 没有任何自动指标会报警(见 three_d/docs
CLAUDE.md 第 26 条)。2026-08-03 实测就撞上过一次: 三维按"架内自上而下"编号, 而现场
1 号缸在最下面, 两套编号首尾颠倒。

三条断言:
  1. 同一架内 4 个缸的"法兰 → 缸内板锚点"竖直偏置必须相同(判据见 clip_compiler
     .verify_tank_pairing 的注释: 只用架内相对量, 因为绝对量那条链有系统偏差);
  2. 缸盖机构号必须与缸号同源: TANK_n 的盖是 dev_t{1 if n<=4 else 2}_cyl{(n-1)%4+1};
  3. 板锚点(玻璃-*)必须挂在对应的 TANK_n 之下, 8 个缸一个不缺。

用法: PTLC_CONTROL_ROOT=<上位机根> python verify_tank_numbering.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import clip_compiler
from scene_kinematics import GlbScene, RobotPosture
from sync_ptlc_robot import ROOT, _control_root, _load_registry


def main() -> int:
    control_root = _control_root(None)
    registry = _load_registry(control_root)
    manifest = json.loads(
        (ROOT / "models" / "device-manifest.official-cr5.json").read_text(encoding="utf-8"))
    scene = GlbScene(ROOT / "models" / "machine.official-cr5.glb")
    rail_slots = clip_compiler.load_rail_slots(control_root)

    failures: list[str] = []

    # 1. 架内偏置一致性
    problems = clip_compiler.verify_tank_pairing(
        scene, RobotPosture(scene, manifest), registry, rail_slots[5])
    failures.extend(problems)

    by_name = {point.robot_name: point for point in registry.points}
    posture = RobotPosture(scene, manifest)
    anchors = clip_compiler.resolve_plate_anchors(scene)
    print("缸号  取放点  板锚点            法兰-锚点竖直偏置")
    for tank in range(1, 9):
        point = by_name.get(f"P{10 + tank}")
        anchor = anchors.get(f"tank:{tank}")
        if point is None or anchor is None:
            failures.append(f"tank:{tank} 缺点位或缺板锚点(点={point is not None} 锚点={anchor})")
            continue
        mount = posture.mount_world(joints_deg=list(point.joint), rail_mm=rail_slots[5])[:3, 3]
        vertical = (mount[1] - scene.world_matrix(anchor)[:3, 3][1]) * 1000.0
        print(f"  {tank}   P{10 + tank:<5} {anchor:<16} {vertical:+8.1f} mm")

    # 2. 缸盖机构号与缸号同源
    lids = {item["id"] for item in manifest.get("linkages") or [] if item["id"].startswith("dev_t")}
    for tank in range(1, 9):
        wanted = f"dev_t{1 if tank <= 4 else 2}_cyl{(tank - 1) % 4 + 1}"
        if wanted not in lids:
            failures.append(f"manifest 里没有 {wanted}(tank:{tank} 的盖)")

    # 3. 锚点齐全
    missing = [f"tank:{n}" for n in range(1, 9) if f"tank:{n}" not in anchors]
    if missing:
        failures.append(f"板锚点缺失: {missing}")

    print()
    if failures:
        print(f"[!] 展缸编号验收未通过({len(failures)} 项):")
        for item in failures:
            print(f"    {item}")
        return 1
    print("[ok] 展缸编号三方自洽: 点表 ↔ TANK_n ↔ dev_t*_cyl*")
    return 0


if __name__ == "__main__":
    sys.exit(main())
