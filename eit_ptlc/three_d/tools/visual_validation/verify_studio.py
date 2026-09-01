"""
功能: 动画工作室的自动化验收 —— 换夹爪片段的 attach 语义与 seek 确定性.

核心断言链(用户点名的"真实性"翻译成机器可验证的表述):
  1. 锁紧前: 夹爪的父节点**不是** TOOL_MOUNT(还停在工具站);
  2. 锁紧后: 父节点**是** TOOL_MOUNT(场景图上成了法兰的孩子);
  3. 提臂后: 夹爪世界高度上升 > 5cm("被机械臂带起来");
  4. 回拖到锁紧前: 父节点还原(seek 的回家重放语义).
另截 5 帧关键姿态图供目检(对接是否穿模/姿态是否自然由人看).

用法: python verify_studio.py [--headless]
返回值: 无(结果写 work/verify_studio.json, 截图写 work/previews/review/)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))
SHOT_DIR = os.path.join(WORK_DIR, "previews", "review")

TOOL = "TOOL_PLATE96"
TOOL_DOCK = "TOOL_PLATE96_DOCK"
# 关键时刻(与 robot.tool_pickup.yaml 的编排对齐; 改片段后跑一遍会自动暴露漂移)
T_APPROACH = 7.9    # 近接近点悬停(示教点在对接位上方 +20mm, 缝隙属设计而非错位)
T_DOCKED = 9.1      # 大夹爪到 2 号工具位，尚未锁紧
T_BEFORE_LOCK = 9.12
T_AFTER_LOCK = 9.4
T_LIFTED = 12.5
SHOTS = [(3.2, "anim_rail"), (T_APPROACH, "anim_approach"), (T_DOCKED, "anim_docked"),
         (T_AFTER_LOCK, "anim_locked"), (T_LIFTED, "anim_lifted"), (99, "anim_final")]


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def quaternion_error_deg(first: list[float], second: list[float]) -> float:
    """返回两个单位四元数的最短夹角（度），并兼容 q/-q 等价表示。"""
    dot = abs(sum(a * b for a, b in zip(first, second)))
    dot = max(0.0, min(1.0, dot))
    return math.degrees(2.0 * math.acos(dot))


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="动画工作室自动化验收")
    parser.add_argument("--url", default="http://localhost:18080/3d/motion/robot.tool_pickup")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    result: dict = {"url": args.url, "console_errors": []}
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console", lambda m: result["console_errors"].append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(str(e)))

        log(f"打开 {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".st__mask", state="attached", timeout=15_000)
        page.wait_for_selector(".st__mask", state="detached", timeout=240_000)
        page.wait_for_timeout(2000)

        state = page.evaluate("window.__anim ? window.__anim.state() : null")
        result["initial"] = state
        log(f"装载片段: {state}")
        if not state or state.get("clip") != "robot.tool_pickup":
            failures.append(f"未自动装载 robot.tool_pickup: {state}")

        clip_names = page.locator(".st__item").all_inner_texts()
        result["clips"] = clip_names
        if "robot.tool_return" not in clip_names:
            failures.append(f"片段清单缺 robot.tool_return: {clip_names}")

        def ev(expression: str, arg=None):
            """求值前等开发钩子就绪: 前端热更新会触发整页重载,
            重载窗口里 __anim 短暂消失(remount 后自动回来), 直接求值会误崩."""
            page.wait_for_function("() => !!window.__anim", timeout=60_000)
            return page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)

        def seek(t: float) -> None:
            ev(f"window.__anim.seek({t})")
            page.wait_for_timeout(300)

        def tool_parent() -> str:
            return ev(f"window.__anim.toolParent('{TOOL}')") or ""

        def tool_y() -> float:
            pos = ev(f"window.__anim.toolWorld('{TOOL}')")
            return float(pos[1]) if pos else float("nan")

        def node_world(name: str) -> list[float] | None:
            return ev("name => window.__anim.nodeWorld(name)", name)

        # -- 1/2: attach 前后父节点 -----------------------------------------
        seek(T_BEFORE_LOCK)
        parent_before = tool_parent()
        tool_pose_before_lock = ev("name => window.__anim.nodeWorldPose(name)", TOOL)
        mount_world = node_world("TOOL_MOUNT")
        dock_world = node_world(TOOL_DOCK)
        dock_error_m = (
            math.sqrt(sum((a - b) ** 2 for a, b in zip(mount_world, dock_world)))
            if mount_world and dock_world
            else float("inf")
        )
        result["dock_probe"] = {
            "tool_root": ev(f"window.__anim.toolWorld('{TOOL}')"),
            "tool_mount": node_world("TOOL_MOUNT"),
            "robot_base": node_world("CR5_BASE_FRAME"),
            "rail_carriage": node_world("CARRIAGE"),
            "tool_dock": dock_world,
            "dock_error_mm": round(dock_error_m * 1000.0, 3),
            "robot_quick_change": ev("window.__anim.nodesWorldMatching('QT2191876')"),
            "tool_quick_change": ev("window.__anim.nodesWorldMatching('QT2091392')"),
        }
        result["parent_before_lock"] = parent_before
        log(f"锁紧前父节点: {parent_before}")
        log(f"法兰/工具对接误差: {dock_error_m * 1000.0:.3f} mm")
        if dock_error_m > 0.005:
            failures.append(f"TOOL_MOUNT 与 CAD 对接点相差 {dock_error_m * 1000.0:.3f}mm (>5mm)")
        if parent_before == "TOOL_MOUNT":
            failures.append("锁紧前夹爪就已挂在 TOOL_MOUNT 上")

        # 锁紧连续性按吸附语义拆成两条(2026-08-02):
        #   a) 锁紧**瞬间**世界姿态连续(不跳帧) —— 事件前后一小步各采一帧比较;
        #   b) 吸附补间在 0.25s 内**平滑**修正到 mount_transform, 总修正量应在
        #      标定残差量级内(≤0.5°), 过大说明锁紧位数据坏了.
        # 旧断言"锁紧前后 0.28s 姿态零变化"属无吸附时代语义, 会把刻意的平滑吸附误报.
        seek(9.125)
        pose_instant_before = ev("name => window.__anim.nodeWorldPose(name)", TOOL)
        seek(9.131)
        pose_instant_after = ev("name => window.__anim.nodeWorldPose(name)", TOOL)
        instant_jump_deg = quaternion_error_deg(
            pose_instant_before["quaternion"], pose_instant_after["quaternion"]
        )

        seek(T_AFTER_LOCK)
        parent_after = tool_parent()
        y_locked = tool_y()
        tool_pose_after_lock = ev("name => window.__anim.nodeWorldPose(name)", TOOL)
        adsorption_correction_deg = quaternion_error_deg(
            tool_pose_before_lock["quaternion"], tool_pose_after_lock["quaternion"]
        )
        result["parent_after_lock"] = parent_after
        result["lock_instant_jump_deg"] = round(instant_jump_deg, 6)
        result["adsorption_correction_deg"] = round(adsorption_correction_deg, 6)
        result["tool_local_after_lock"] = ev(f"window.__anim.nodeLocal('{TOOL}')")
        log(f"锁紧后父节点: {parent_after}")
        log(f"锁紧瞬间跳变: {instant_jump_deg:.6f}°; 吸附总修正: {adsorption_correction_deg:.6f}°")
        if parent_after != "TOOL_MOUNT":
            failures.append(f"锁紧后夹爪父节点不是 TOOL_MOUNT: {parent_after}")
        if instant_jump_deg > 0.01:
            failures.append(f"锁紧瞬间夹爪方向突变 {instant_jump_deg:.6f}° (>0.01°)")
        if adsorption_correction_deg > 0.5:
            failures.append(
                f"吸附总修正量 {adsorption_correction_deg:.4f}° (>0.5°), 锁紧位标定可能已坏"
            )

        # -- 3: 被带起来 ------------------------------------------------------
        seek(T_LIFTED)
        y_lifted = tool_y()
        lifted_mount = node_world("TOOL_MOUNT")
        lifted_dock = node_world(TOOL_DOCK)
        lifted_dock_error_m = math.sqrt(
            sum((a - b) ** 2 for a, b in zip(lifted_mount, lifted_dock))
        )
        result["tool_rise_m"] = round(y_lifted - y_locked, 4)
        result["lifted_dock_error_mm"] = round(lifted_dock_error_m * 1000.0, 3)
        result["lifted_mount"] = lifted_mount
        result["lifted_dock"] = lifted_dock
        result["lifted_tool_root"] = ev(f"window.__anim.toolWorld('{TOOL}')")
        result["tool_local_lifted"] = ev(f"window.__anim.nodeLocal('{TOOL}')")
        local_orientation_drift_deg = quaternion_error_deg(
            result["tool_local_after_lock"]["quaternion"],
            result["tool_local_lifted"]["quaternion"],
        )
        result["locked_local_orientation_drift_deg"] = round(local_orientation_drift_deg, 6)
        log(f"提臂后夹爪抬升: {result['tool_rise_m']} m")
        log(f"提臂后法兰/工具对接误差: {lifted_dock_error_m * 1000.0:.3f} mm")
        if not (y_lifted - y_locked > 0.05):
            failures.append(f"提臂后夹爪没有被带起来(Δy={y_lifted - y_locked:.3f}m)")
        if lifted_dock_error_m > 0.005:
            failures.append(f"提臂后工具脱离 TOOL_MOUNT {lifted_dock_error_m * 1000.0:.3f}mm")
        if local_orientation_drift_deg > 0.001:
            failures.append(
                f"锁紧后夹爪未刚性跟随 J6，局部方向漂移 {local_orientation_drift_deg:.6f}°"
            )

        # -- 4: 回拖还原 ------------------------------------------------------
        seek(T_BEFORE_LOCK)
        parent_rewound = tool_parent()
        result["parent_after_rewind"] = parent_rewound
        log(f"回拖后父节点: {parent_rewound}")
        if parent_rewound == "TOOL_MOUNT":
            failures.append("回拖到锁紧之前, 夹爪却还挂在 TOOL_MOUNT 上(seek 重放失效)")

        # -- 关键帧截图(目检用) ----------------------------------------------
        for t, name in SHOTS:
            seek(t)
            page.wait_for_timeout(500)
            path = os.path.join(SHOT_DIR, f"{name}.png")
            page.screenshot(path=path)
            log(f"截图: {path}")

        browser.close()

    real_errors = [e for e in result["console_errors"] if "Missing optional extension" not in e]
    result["real_console_errors"] = real_errors
    if real_errors:
        failures.append(f"控制台有 {len(real_errors)} 条报错")
        for item in real_errors[:5]:
            log(f"  控制台: {item[:160]}")

    result["failures"] = failures
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, "verify_studio.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    if failures:
        log(f"验收未通过, {len(failures)} 项:")
        for item in failures:
            log(f"  x {item}")
        raise SystemExit(1)
    log("动画工作室验收通过")


if __name__ == "__main__":
    main()
