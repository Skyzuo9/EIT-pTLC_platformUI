"""
功能: 补光在**默认整机机位**下的可读性目检 —— verify_process_light.py 是怼着窗口拍的
      (证明"确实亮了"), 这个是用户真实机位拍的(证明"看得出来")。

产出 work/previews/review/proclight_wide_{off,on}.png, 附切掉 HUD 后的像素变化量.
不做断言: 灯在整机机位下该有多显眼是审美判断, 交给人(或读图的 AI)看.

前提: vite 开发服务器在 15173.
用法: C:/ProgramData/miniforge3/python.exe shot_process_light_wide.py
"""

from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews", "review"))
URL = "http://localhost:15173/3d/live"
HUD_WIDTH = 420


def main() -> None:
    """功能: 命令行入口. 参数: 无. 返回值: None"""
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    shots = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"]
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_function(
            "() => window.__ptlcTwin?.manager?.bindings?.machine?.lights?.size", timeout=180_000
        )
        page.wait_for_timeout(6000)

        for tag, on in (("off", False), ("on", True)):
            if on:
                page.evaluate(
                    "() => window.__ptlcTwin.feed.handleEvent({ type: 'process_light',"
                    " id: 'vision_fill', on: true, channel: 7, ts: Date.now() / 1000 })"
                )
                page.wait_for_timeout(1500)
            shots[tag] = os.path.join(SHOT_DIR, f"proclight_wide_{tag}.png")
            page.screenshot(path=shots[tag])
            print(f"截图: {shots[tag]}")
        browser.close()

    import numpy as np
    from PIL import Image

    a, b = (
        np.asarray(Image.open(shots[t]).convert("RGB"), dtype=np.int16)[:, HUD_WIDTH:, :]
        for t in ("off", "on")
    )
    delta = np.abs(b - a)
    print(f"整机机位下开灯引起的变化: {int((delta.max(axis=2) > 3).sum())} 像素, "
          f"最大通道差 {float(delta.max())}")


if __name__ == "__main__":
    main()
