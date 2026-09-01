"""
功能: 昼夜观感的前后对照截图集 —— 服务于 STAGES(环境) 与 RIG(布光) 的调参回路.

产出(全部写入 work/previews/review/):
  mat_front_light_<tag>.png / mat_iso_light_<tag>.png    材质台 浅色主题 前视/等轴测
  mat_front_dark_<tag>.png  / mat_iso_dark_<tag>.png     材质台 深色主题
  show_front_light_<tag>.png / show_iso_light_<tag>.png  演示页 浅色主题
  wb_front_light_<tag>.png  / wb_iso_light_<tag>.png     装配台(顺带核对机械臂折叠姿态)

对照口径随本轮改动**极性反转**, 别照旧读:
  本脚本原为"浅色平视洗白"而生, 口径曾是"front_light 洗白缓解 / dark 两张逐像素一致"
  (dark 当金丝雀). 2026-08-05 昼夜统一为同一套布光后, **light 才是基本不变的那侧**
  (只差表面细节关掉), dark 侧则会明显变化 —— 那正是本次改动的目的, 不是失败.
这是流程性工具, 不做断言 —— 判断交给人(或读图的 AI)逐张目检.

用法: python verify_light_front.py [--url-base http://localhost:18080] --tag before|after
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work", "previews", "review"))


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def shoot(page, name: str) -> None:
    """功能: 截图并报路径. 参数: page, name(文件名). 返回值: None"""
    path = os.path.join(OUT_DIR, name)
    page.screenshot(path=path)
    log(f"截图: {path}")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="平视洗白调参对照截图集")
    parser.add_argument("--url-base", default="http://localhost:18080")
    parser.add_argument("--tag", required=True, help="截图名后缀, 如 before / after")
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
        # 防御: 万一以后换成持久 profile, 用户自己的显示覆盖不能污染对照.
        # 两个键都清: v2 是现役槽, v1 是回滚用的旧槽(现在不读, 清掉无副作用)
        page.add_init_script(
            "try{localStorage.removeItem('ptlc.display.v2');"
            "localStorage.removeItem('ptlc.display.v1')}catch(e){}"
        )

        # -- 材质台: light 主症状 + dark 金丝雀 ------------------------------
        for theme in ("light", "dark"):
            page.goto(f"{args.url_base}/3d/materials", wait_until="domcontentloaded", timeout=60_000)
            page.evaluate(f"localStorage.setItem('ptlc.theme', '{theme}'); document.documentElement.dataset.theme = '{theme}'")
            page.wait_for_selector(".mt__mask", state="attached", timeout=15_000)
            page.wait_for_selector(".mt__mask", state="detached", timeout=args.wait * 1000)
            page.wait_for_timeout(2500)
            page.evaluate("window.__ptlc && window.__ptlc.view('front')")
            page.wait_for_timeout(1600)
            shoot(page, f"mat_front_{theme}_{args.tag}.png")
            page.evaluate("window.__ptlc && window.__ptlc.view('iso')")
            page.wait_for_timeout(1600)
            shoot(page, f"mat_iso_{theme}_{args.tag}.png")

        # -- 演示页: light 前视 + 等轴测 -------------------------------------
        page.goto(f"{args.url_base}/3d/live", wait_until="domcontentloaded", timeout=60_000)
        page.evaluate("localStorage.setItem('ptlc.theme', 'light'); document.documentElement.dataset.theme = 'light'")
        page.wait_for_timeout(2500)
        try:
            page.wait_for_selector("[class*=overlay]", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(5000)
        for label, key in (("前", "front"), ("轴测", "iso")):
            try:
                page.get_by_role("button", name=label, exact=True).first.click()
                page.wait_for_timeout(1600)
            except Exception as err:  # noqa: BLE001
                log(f"演示页视角「{label}」点击失败: {err}")
            shoot(page, f"show_{key}_light_{args.tag}.png")

        # -- 装配台: 顺带核对机械臂折叠姿态与台面高光 -------------------------
        page.goto(f"{args.url_base}/3d/workbench", wait_until="domcontentloaded", timeout=60_000)
        page.evaluate("localStorage.setItem('ptlc.theme', 'light'); document.documentElement.dataset.theme = 'light'")
        try:
            page.wait_for_selector(".wb__overlay", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(3000)
        for label, key in (("前", "front"), ("等轴测", "iso")):
            try:
                page.get_by_role("button", name=label, exact=True).first.click()
                page.wait_for_timeout(1600)
            except Exception as err:  # noqa: BLE001
                log(f"装配台视角「{label}」点击失败: {err}")
            shoot(page, f"wb_{key}_light_{args.tag}.png")

        browser.close()
    log("对照截图集完成")


if __name__ == "__main__":
    main()
