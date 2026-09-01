"""
功能: 表面"麻点"归因的对照截图矩阵 —— 同机位逐项切显示开关, 把四类嫌疑
(SSAO 噪点 / PCF·IGN 阴影颗粒 / 抗锯齿缺失 / join 后量化 z-fighting) 拆开看.

矩阵(全部 ?theme=light, 高档, 轴测+前视两机位):
  A  基线(清除全部覆盖)            —— 现状
  B  ssaoEnabled=false             —— 隔离 SSAO 全链
  C  shadowRadius=0                —— 隔离 PCF·IGN 半影抖动(阴影仍在)
  D  shadowsEnabled=false          —— 隔离实时阴影整体(抖动+acne)
  E  SSAO off + 阴影 off           —— 残噪底: 几何/锯齿/量化
  F  HUD 切「中」                  —— 无 SSAO 无 SMAA, 1024 阴影, DPR1.5
  G  HUD 切「低」                  —— 无 composer 无阴影, DPR1
  HA /3d/live 基线                 —— 正式实时模型 A/B
  HE /3d/live + E 同开关           —— 正式实时模型的残噪底
  I  /3d/workbench                 —— raw.glb + low 档, 几何对照兜底

判据: 对每张图的 3 个固定裁剪区算"椒盐分" = |亮度 - 3×3中值| 超阈值的像素数,
偏暗/偏亮分开统计(SSAO 只贡献暗点, IGN 半影双向, 镜面锯齿只贡献亮点 ——
方向本身就是归因证据). 产物: PNG + 裁剪图 + scores.csv + manifest.json.

用法: C:\\ProgramData\\miniforge3\\python.exe diag_speckle_matrix.py [--tag before]
      [--url-base http://localhost:18080] [--score-only]
坑位提示(全部来自实测): dev server 只绑 [::1]; 无头默认 DPR=1 会让高档退化,
必须 device_scale_factor=2; WebGL rAF 吃满主线程时 locator.click 会饿死,
一律用 dispatch_event; __ptlcDisplay 要先点开「显示」面板才注册.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.normpath(os.path.join(ROOT, "..", "..", "work", "previews", "speckle"))

VIEWS = [("轴测", "iso"), ("前", "front")]

# 裁剪区: (视图, 名字, 左, 上, 右, 下) 全部为画面宽高的比例, 取样"平整表面"
# 而非轮廓密集区 —— 轮廓区的高频是正常细节, 会淹没麻点信号.
CROPS = {
    "iso": [
        ("column", 0.46, 0.18, 0.62, 0.52),   # 铝型材立柱区
        ("motor", 0.30, 0.38, 0.44, 0.60),    # 白色电机圆柱区
        ("plate", 0.55, 0.72, 0.85, 0.92),    # 底板大平面
    ],
    "front": [
        ("column", 0.40, 0.15, 0.60, 0.50),
        ("motor", 0.22, 0.45, 0.40, 0.68),
        ("plate", 0.55, 0.75, 0.90, 0.95),
    ],
    # 近景(materials 页 focus 工位): 避开左侧材质列表与右侧显示面板, 只取画面中带
    "close": [
        ("center", 0.30, 0.12, 0.72, 0.88),
    ],
}

# 近景采集: (工位节点, 取景边距米, 文件前缀) —— 用户截图就是这种"凑近单工位"视角
CLOSEUPS = [
    ("ST_SAMPLING", 0.45, "S"),
    ("ST_PHOTOSCRAPE", 0.45, "P"),
]

THRESHOLDS = (8, 12, 16)


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def probe_port(start: int = 18080, end: int = 18080) -> int | None:
    """功能: 探测 [::1] 上的 dev server. 参数: 端口区间. 返回值: 命中端口或 None"""
    for port in range(start, end + 1):
        try:
            with socket.create_connection(("::1", port), timeout=1.0):
                return port
        except OSError:
            continue
    return None


def wait_overlay_gone(page, wait_s: int) -> None:
    """功能: 等加载遮罩消失(一次性 evaluate 轮询, 不用会被饿死的注入轮询).
    参数: page, wait_s. 返回值: None"""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        n = page.evaluate("document.querySelectorAll('[class*=overlay]').length")
        if n == 0:
            return
        time.sleep(0.5)
    log("警告: 加载遮罩超时未消失, 继续硬闯")


def wait_js(page, expr: str, wait_s: float, what: str) -> bool:
    """功能: 一次性 evaluate 轮询直到 expr 为真. 参数: page, expr, wait_s, what.
    返回值: 是否等到"""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if page.evaluate(expr):
            return True
        time.sleep(0.4)
    log(f"警告: 等待 {what} 超时")
    return False


def click_text_button(page, label: str) -> None:
    """功能: 按文案点 HUD 按钮(dispatch_event 绕过 rAF 饿死). 参数: page, label.
    返回值: None"""
    page.get_by_role("button", name=label, exact=True).first.dispatch_event("click")


def assert_quality(page, expected_label: str) -> None:
    """功能: 断言 HUD 激活档位, 被 autoDegrade 抢档就点回去. 参数: page, 期望文案.
    返回值: None"""
    active = page.evaluate(
        "[...document.querySelectorAll('.hud__btn--active')].map(b => b.textContent.trim())"
    )
    if expected_label not in active:
        log(f"档位被抢({active}), 点回「{expected_label}」")
        click_text_button(page, expected_label)
        time.sleep(1.2)


def display_set(page, key: str, value) -> None:
    """功能: 经 __ptlcDisplay 设/清显示覆盖. 参数: page, key, value(None=清).
    返回值: None"""
    payload = json.dumps(value)
    page.evaluate(f"window.__ptlcDisplay && window.__ptlcDisplay.set('{key}', {payload})")


def clear_overrides(page) -> None:
    """功能: 清掉本脚本会动的三个字段的覆盖. 参数: page. 返回值: None"""
    for key in ("ssaoEnabled", "shadowsEnabled", "shadowRadius"):
        display_set(page, key, None)


def shoot_views(page, out_dir: str, cell: str, tier_label: str | None) -> None:
    """功能: 对当前状态截轴测+前视两张. 参数: page, out_dir, cell, tier_label.
    返回值: None"""
    for label, key in VIEWS:
        click_text_button(page, label)
        time.sleep(1.6)
        if tier_label:
            assert_quality(page, tier_label)
        path = os.path.join(out_dir, f"{cell}_{key}.png")
        page.screenshot(path=path)
        log(f"截图: {path}")


def open_display_panel(page) -> None:
    """功能: 点开「显示」面板让 __ptlcDisplay 注册. 参数: page. 返回值: None"""
    page.locator(".hud [data-display-toggle]").first.dispatch_event("click")
    wait_js(page, "Boolean(window.__ptlcDisplay)", 8, "__ptlcDisplay 注册")


def setup_show(page, url: str, wait_s: int) -> None:
    """功能: 进演示页并钉高档/开面板. 参数: page, url, wait_s. 返回值: None"""
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(2.5)
    wait_overlay_gone(page, wait_s)
    time.sleep(5)
    click_text_button(page, "高")
    time.sleep(1.2)
    assert_quality(page, "高")
    open_display_panel(page)


def capture_matrix(url_base: str, out_dir: str, wait_s: int) -> None:
    """功能: 产出整个对照矩阵的截图. 参数: url_base, out_dir, wait_s. 返回值: None"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,  # 无头默认 DPR=1, 高档 min(dpr,2) 会退化
        )

        # -- 实时台高档: A~E 同会话逐项切 ----------------------------------
        setup_show(page, f"{url_base}/3d/live", wait_s)
        page.evaluate("localStorage.setItem('ptlc.theme', 'light'); document.documentElement.dataset.theme = 'light'")
        cells = [
            ("A", {}),
            ("B", {"ssaoEnabled": False}),
            ("C", {"shadowRadius": 0}),
            ("D", {"shadowsEnabled": False}),
            ("E", {"ssaoEnabled": False, "shadowsEnabled": False}),
        ]
        for cell, overrides in cells:
            clear_overrides(page)
            for key, value in overrides.items():
                display_set(page, key, value)
            time.sleep(0.9)
            shoot_views(page, out_dir, cell, "高")

        # -- F/G 档位对照 ----------------------------------------------------
        clear_overrides(page)
        for cell, label in (("F", "中"), ("G", "低")):
            click_text_button(page, label)
            time.sleep(1.5)
            shoot_views(page, out_dir, cell, label)

        # -- H: 正式实时模型, 重放 A 与 E ------------------------------------
        setup_show(page, f"{url_base}/3d/live", wait_s)
        clear_overrides(page)
        time.sleep(0.9)
        shoot_views(page, out_dir, "HA", "高")
        display_set(page, "ssaoEnabled", False)
        display_set(page, "shadowsEnabled", False)
        time.sleep(0.9)
        shoot_views(page, out_dir, "HE", "高")
        clear_overrides(page)

        # -- I: 装配台(raw.glb, low 档, 无后处理无阴影) -----------------------
        page.goto(f"{url_base}/3d/workbench", wait_until="domcontentloaded", timeout=60_000)
        time.sleep(2)
        wait_overlay_gone(page, wait_s)
        time.sleep(3)
        path = os.path.join(out_dir, "I_default.png")
        page.screenshot(path=path)
        log(f"截图: {path}")

        browser.close()

    manifest = {
        "theme": "light",
        "viewport": [1600, 1000],
        "device_scale_factor": 2,
        "cells": {
            "A": "高档基线",
            "B": "高档 + ssaoEnabled=false",
            "C": "高档 + shadowRadius=0",
            "D": "高档 + shadowsEnabled=false",
            "E": "高档 + SSAO off + 阴影 off",
            "F": "中档",
            "G": "低档",
            "HA": "official(no-join) 高档基线",
            "HE": "official(no-join) + SSAO off + 阴影 off",
            "I": "/3d/workbench raw.glb low 档默认取景",
        },
        "crops": CROPS,
        "thresholds": THRESHOLDS,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)


def capture_closeup(url_base: str, out_dir: str, wait_s: int) -> None:
    """功能: /3d/materials 页 focus 工位近景, 重放开关矩阵(A~E 同一套).
    参数: url_base, out_dir, wait_s. 返回值: None"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
        )
        page.goto(f"{url_base}/3d/materials", wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_selector(".mt__mask", state="attached", timeout=15_000)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if page.evaluate("document.querySelectorAll('.mt__mask').length === 0"):
                break
            time.sleep(0.5)
        time.sleep(2.5)
        page.locator("[data-display-toggle]").first.dispatch_event("click")
        wait_js(page, "Boolean(window.__ptlcDisplay)", 8, "__ptlcDisplay 注册(materials)")

        cells = [
            ("A", {}),
            ("B", {"ssaoEnabled": False}),
            ("C", {"shadowRadius": 0}),
            ("D", {"shadowsEnabled": False}),
            ("E", {"ssaoEnabled": False, "shadowsEnabled": False}),
        ]
        for node, padding, prefix in CLOSEUPS:
            page.evaluate("window.__ptlc && window.__ptlc.view('iso')")
            time.sleep(1.2)
            ok = page.evaluate(f"window.__ptlc ? window.__ptlc.focus('{node}', {padding}) : false")
            time.sleep(1.6)
            if not ok:
                log(f"近景 {node} 取景失败(节点不存在?), 跳过")
                continue
            for cell, overrides in cells:
                clear_overrides(page)
                for key, value in overrides.items():
                    display_set(page, key, value)
                time.sleep(0.9)
                path = os.path.join(out_dir, f"{prefix}{cell}_close.png")
                page.screenshot(path=path)
                log(f"截图: {path}")
            clear_overrides(page)
        browser.close()


def salt_pepper(image, box) -> dict:
    """功能: 对一个裁剪区算椒盐分(暗/亮分开, 多阈值). 参数: PIL 图, 像素框.
    返回值: {t{T}_dark/t{T}_bright: 每百万像素计数}"""
    import numpy as np
    from PIL import ImageFilter

    crop = image.crop(box).convert("L")
    med = crop.filter(ImageFilter.MedianFilter(3))
    arr = np.asarray(crop, dtype=np.int16)
    diff = arr - np.asarray(med, dtype=np.int16)
    total = arr.size
    result = {}
    for t in THRESHOLDS:
        result[f"t{t}_dark"] = round(int((diff < -t).sum()) * 1e6 / total)
        result[f"t{t}_bright"] = round(int((diff > t).sum()) * 1e6 / total)
    return result


def score(out_dir: str) -> None:
    """功能: 给矩阵里所有 PNG 的裁剪区打椒盐分, 落 CSV 与裁剪图. 参数: out_dir.
    返回值: None"""
    from PIL import Image

    crop_dir = os.path.join(out_dir, "crops")
    os.makedirs(crop_dir, exist_ok=True)
    rows = []
    for name in sorted(os.listdir(out_dir)):
        if not name.endswith(".png"):
            continue
        stem = name[:-4]
        parts = stem.rsplit("_", 1)
        view = parts[1] if len(parts) == 2 and parts[1] in ("iso", "front", "close") else "iso"
        cell = parts[0]
        image = Image.open(os.path.join(out_dir, name))
        width, height = image.size
        for crop_name, l, t, r, b in CROPS.get(view, CROPS["iso"]):
            box = (int(l * width), int(t * height), int(r * width), int(b * height))
            image.crop(box).save(os.path.join(crop_dir, f"{stem}_{crop_name}.png"))
            row = {"cell": cell, "view": view, "crop": crop_name}
            row.update(salt_pepper(image, box))
            rows.append(row)
    if not rows:
        log("没有可打分的 PNG")
        return
    csv_path = os.path.join(out_dir, "scores.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log(f"打分完成: {csv_path}")
    # 顺手在 stdout 给一份 t12 摘要, 方便直接看
    print(f"{'cell':<4}{'view':<7}{'crop':<8}{'dark':>8}{'bright':>8}")
    for row in rows:
        print(f"{row['cell']:<4}{row['view']:<7}{row['crop']:<8}"
              f"{row['t12_dark']:>8}{row['t12_bright']:>8}")


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="麻点归因对照矩阵")
    parser.add_argument("--url-base", default=None)
    parser.add_argument("--tag", default="before", help="产物子目录名(before/after)")
    parser.add_argument("--wait", type=int, default=240)
    parser.add_argument("--score-only", action="store_true", help="只对已有 PNG 重新打分")
    parser.add_argument("--set", dest="capture_set", default="full",
                        choices=("full", "closeup", "both"), help="采集哪组矩阵")
    args = parser.parse_args()

    out_dir = os.path.join(OUT_ROOT, args.tag)
    os.makedirs(out_dir, exist_ok=True)

    if not args.score_only:
        url_base = args.url_base
        if not url_base:
            port = probe_port()
            if port is None:
                log("错误: [::1]:15200-15210 上没有 dev server, 先启动再来")
                sys.exit(1)
            url_base = f"http://localhost:{port}"
        log(f"目标 dev server: {url_base}")
        if args.capture_set in ("full", "both"):
            capture_matrix(url_base, out_dir, args.wait)
        if args.capture_set in ("closeup", "both"):
            capture_closeup(url_base, out_dir, args.wait)

    score(out_dir)
    log("矩阵完成")


if __name__ == "__main__":
    main()
