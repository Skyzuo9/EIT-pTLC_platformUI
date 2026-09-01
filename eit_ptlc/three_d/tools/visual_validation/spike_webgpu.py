"""
功能: WebGPU 节点管线探底 —— 跑 spike 页, 收结构化结果与同机位截图.

必须**有头**跑: Playwright 自带的无头 Chromium 不暴露 navigator.gpu(加
--enable-unsafe-webgpu 也没用), 无头下只能测到 WebGL 回退档, 那就把结论测反了.

产出(work/previews/webgpu_spike/):
  <backend>_<fx>.png   同机位截图
  spike_result.json    每一档的后端/几何盘点/帧耗时/报错

用法: python spike_webgpu.py [--url-base http://127.0.0.1:15173]
返回值: 无(落盘 + stdout 汇总)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work", "previews", "webgpu_spike"))

# (backend, fx) —— webgpu 开/关后期 + webgl 回退档开后期
CASES = [
    ("webgpu", "off"),
    ("webgpu", "gtao"),
    ("webgpu", "ssgi"),
    ("webgl", "off"),
    ("webgl", "gtao"),
]


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def run_case(browser, url_base: str, backend: str, fx: str) -> dict:
    """
    功能: 跑一档并回收结果.

    参数: browser, url_base, backend, fx
    返回值: 结构化结果字典
    """
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    console: list[str] = []
    page.on("console", lambda m: console.append(f"[{m.type}] {m.text[:200]}")
            if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: console.append(f"[pageerror] {str(e)[:300]}"))

    url = f"{url_base}/spike-webgpu.html?backend={backend}&fx={fx}"
    log(f"→ {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)

    # 等 ready(模型加载 + 90 帧) 或超时
    deadline = time.time() + 180
    data = None
    while time.time() < deadline:
        data = page.evaluate("() => window.__spike || null")
        if data and (data.get("ready") or data.get("errors")):
            break
        page.wait_for_timeout(1000)
    # 再多跑一会儿让帧耗时样本攒够
    page.wait_for_timeout(4000)
    try:
        ms = page.evaluate("async () => window.__spike.measure ? await window.__spike.measure(60) : null")
        log(f"  吞吐测量: {ms:.2f} ms/帧" if ms else "  吞吐测量: 不可用")
    except Exception as err:  # noqa: BLE001
        log(f"  吞吐测量失败: {str(err)[:120]}")
    data = page.evaluate("() => window.__spike || null") or {}

    path = os.path.join(OUT_DIR, f"{backend}_{fx}.png")
    page.screenshot(path=path)
    data["screenshot"] = path
    data["console"] = console[:20]
    log(f"  实际后端={data.get('actualBackend')}  几何={data.get('geometry')}  "
        f"帧={data.get('frame')}  错误={len(data.get('errors') or [])}")
    for line in (data.get("errors") or [])[:3]:
        log(f"    ! {line}")
    page.close()
    return data


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="WebGPU 节点管线探底")
    parser.add_argument("--url-base", default="http://127.0.0.1:15173")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(OUT_DIR, exist_ok=True)
    results = {}
    with sync_playwright() as playwright:
        # headless=False 是硬要求, 见模块头注释
        browser = playwright.chromium.launch(
            headless=False,
            args=["--enable-unsafe-webgpu", "--enable-features=Vulkan", "--ignore-gpu-blocklist"],
        )
        for backend, fx in CASES:
            try:
                results[f"{backend}_{fx}"] = run_case(browser, args.url_base, backend, fx)
            except Exception as err:  # noqa: BLE001
                log(f"  该档整体失败: {err}")
                results[f"{backend}_{fx}"] = {"fatal": str(err)}
        browser.close()

    out = os.path.join(OUT_DIR, "spike_result.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)
    log(f"结果: {out}")


if __name__ == "__main__":
    main()
