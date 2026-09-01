"""
功能: 材质目检截图集 —— 供"对照实物照片逐区域过检查单"的审查闭环使用.

产出(全部写入 work/previews/review/):
  show_<机位>.png        演示页 5 个全局机位(轴测/前/左/右/俯)
  mat_global_iso.png     材质台全局等轴测
  region_<工位>.png      材质台对 6 个点名区域的放大图(经 window.__ptlc.focus)
  workbench_iso.png      装配台默认取景 —— 用于"材质图不得比装配图差"的同屏对比

这是流程性工具, 不做断言 —— 判断"像不像实物"必须由人(或读图的 AI)逐张目检,
自动断言只会给出虚假的安全感.

用法: python review_visual.py [--url-base http://localhost:18080]
返回值: 无(截图落盘, stdout 报每张的路径)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work", "previews", "review"))

# 演示页 HUD 的视角按钮文案 -> 截图名
SHOW_VIEWS = [("轴测", "iso"), ("前", "front"), ("左", "left"), ("右", "right"), ("俯", "top")]

# 用户点名的审查区域: (节点, 取景边距[米], 先切到的机位, 截图名) —— 与实物照片对照.
# 机位决定看哪个面: 机械臂要从左前看(等轴测方向会被上样机构挡住).
REGIONS = [
    ("TANK_3", 0.8, "front", "develop_tanks"),      # 展缸: 缸体透明/包裹件白色
    ("ST_RACK", 0.6, "iso", "rack_trays"),          # 料架: 托盘白盘钢棍
    ("ST_ROBOT", 0.5, "left", "robot"),             # 机械臂: 白壳/藏蓝环层次
    ("ST_TOOLING", 0.8, "iso", "gripper"),          # 夹爪: 快换金色
    ("ST_FEEDLIFT", 0.8, "front", "feedlift_glass"),  # 升降料: 前玻璃透明
    ("ST_COLLECT", 0.8, "iso", "collect_bottles"),  # 收集区: 瓶/白塑料件
]


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def shoot(page, path: str) -> None:
    """功能: 截图并报路径. 参数: page, path. 返回值: None"""
    page.screenshot(path=path)
    log(f"截图: {path}")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="材质目检截图集")
    parser.add_argument("--url-base", default="http://localhost:18080")
    parser.add_argument("--wait", type=int, default=240)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(OUT_DIR, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        # -- 演示页: 5 个全局机位 -------------------------------------------
        page.goto(f"{args.url_base}/3d/live", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector("[class*=overlay]", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(5000)
        for label, key in SHOW_VIEWS:
            try:
                page.get_by_role("button", name=label, exact=True).first.click()
                page.wait_for_timeout(1600)
            except Exception as err:  # noqa: BLE001
                log(f"演示页视角「{label}」点击失败: {err}")
            shoot(page, os.path.join(OUT_DIR, f"show_{key}.png"))

        # -- 材质台: 全局 + 6 个点名区域 ------------------------------------
        page.goto(f"{args.url_base}/3d/materials", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".mt__mask", state="attached", timeout=15_000)
        page.wait_for_selector(".mt__mask", state="detached", timeout=args.wait * 1000)
        page.wait_for_timeout(2500)

        page.evaluate("window.__ptlc && window.__ptlc.view('iso')")
        page.wait_for_timeout(1600)
        shoot(page, os.path.join(OUT_DIR, "mat_global_iso.png"))

        for node, padding, view, key in REGIONS:
            # 先隔离该区域再取景 —— 整机层层遮挡, 不隔离的话机械臂永远躲在料架后面
            page.evaluate(f"window.__ptlc && window.__ptlc.isolate('{node}')")
            page.evaluate(f"window.__ptlc && window.__ptlc.view('{view}')")
            page.wait_for_timeout(900)
            ok = page.evaluate(f"window.__ptlc ? window.__ptlc.focus('{node}', {padding}) : false")
            page.wait_for_timeout(1600)
            if not ok:
                log(f"区域 {node} 取景失败(节点不存在?)")
            shoot(page, os.path.join(OUT_DIR, f"region_{key}.png"))
            page.evaluate("window.__ptlc && window.__ptlc.showAll()")

        # -- 装配台: 默认取景, 供"材质图 ≥ 装配图"对比 -----------------------
        page.goto(f"{args.url_base}/3d/workbench", wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_selector(".wb__overlay", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(3000)
        shoot(page, os.path.join(OUT_DIR, "workbench_iso.png"))

        browser.close()
    log("目检截图集完成")


if __name__ == "__main__":
    main()
