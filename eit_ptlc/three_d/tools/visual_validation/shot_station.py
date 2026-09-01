"""
功能: 对指定工位截图 —— 点击工位芯片, 等相机飞行结束后拍照, 用于人工审查每个工位的
      模型细节、状态灯与液面表现.

用法:
    python shot_station.py 展开工位
    python shot_station.py 展开工位 上样工位 拍照刮板工位
    python shot_station.py --all

参数: 见 argparse
返回值: 无(产出 work/previews/station_*.png)
"""

from __future__ import annotations

import argparse
import os
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews"))


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="按工位截图")
    parser.add_argument("stations", nargs="*", help="工位显示名, 如 展开工位")
    parser.add_argument("--all", action="store_true", help="遍历全部工位")
    parser.add_argument("--url", default="http://localhost:18080/3d/live")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".twin__overlay", state="detached", timeout=180_000)
        page.wait_for_timeout(2500)

        names = args.stations
        if args.all or not names:
            names = page.evaluate(
                "() => [...document.querySelectorAll('.hud__station-name')]"
                ".map((el) => el.textContent.trim())"
            )

        for name in names:
            chip = page.query_selector(f".hud__station-name:text-is('{name}')")
            if chip is None:
                print(f"未找到工位: {name}")
                continue
            chip.click()
            # 相机飞行有阻尼过渡, 需要等它稳定下来再拍
            page.wait_for_timeout(2200)
            safe = "".join(ch if ch.isalnum() else "_" for ch in name)
            shot = os.path.join(SHOT_DIR, f"station_{safe}.png")
            page.screenshot(path=shot)
            print(f"[{time.strftime('%H:%M:%S')}] {name} -> {shot}")

        browser.close()


if __name__ == "__main__":
    main()
