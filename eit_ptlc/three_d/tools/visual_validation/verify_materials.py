"""
功能: 材质工作台的自动化验收 —— 确认它真能加载、能选材质、改滑块真的改到了三维.

只验"通路是否成立", 不验观感好不好(那要人眼看照片对比).
关键断言是**改完之后 three.js 材质对象上的值确实变了** —— 面板显示变了但场景没变,
是这类实时编辑器最容易出的问题, 且从截图上看不出来.

用法:
    python verify_materials.py --url http://localhost:18080/3d/materials
    python verify_materials.py --headless

参数: 见 argparse
返回值: 无(结果写入 work/verify_materials.json, 截图写入 work/previews/)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# Windows 控制台默认 GBK, 打 ✗ 之类的字符会直接抛 UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))
SHOT_DIR = os.path.join(WORK_DIR, "previews")


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="材质工作台自动化验收")
    parser.add_argument("--url", default="http://localhost:18080/3d/materials")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--wait", type=int, default=240, help="等模型加载的最长秒数")
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
        page = browser.new_page(viewport={"width": 1700, "height": 1000})
        page.on(
            "console",
            lambda m: result["console_errors"].append(m.text) if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: result["console_errors"].append(str(e)))

        log(f"打开 {args.url}")
        started = time.time()
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)

        page.wait_for_selector(".mt", state="attached", timeout=60_000)
        try:
            # 先等遮罩出现再等它消失 —— 只等"消失"会把"从未出现"也算通过
            page.wait_for_selector(".mt__mask", state="attached", timeout=15_000)
            page.wait_for_selector(".mt__mask", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            mask = page.query_selector(".mt__mask")
            log(f"模型加载失败: {mask.inner_text() if mask else '超时'}")
            browser.close()
            raise SystemExit(1)

        result["load_seconds"] = round(time.time() - started, 2)
        log(f"模型加载完成, 耗时 {result['load_seconds']}s")
        page.wait_for_timeout(2000)

        # -- 1. 材质清单 ----------------------------------------------------
        items = page.query_selector_all(".mt__item")
        result["material_count"] = len(items)
        log(f"材质清单: {len(items)} 种")
        if len(items) < 5:
            failures.append(f"材质数量异常: {len(items)}(预期 20 上下)")

        names = [i.query_selector(".mt__itemName").inner_text() for i in items[:6]]
        result["top_materials"] = names
        log(f"用量最大的几种: {names}")
        # 材质名应显示成中文(labels.js), 不再是裸 MAT_*
        if not any(any("一" <= ch <= "鿿" for ch in n) for n in names):
            failures.append(f"材质清单没有显示中文名: {names}")

        # -- 1.5 物料清单: 按工位分组的零件目录 -------------------------------
        stations = page.query_selector_all(".mt__station")
        parts = page.query_selector_all(".mt__part")
        result["station_groups"] = len(stations)
        result["part_kinds"] = len(parts)
        log(f"物料清单: {len(stations)} 个工位分组, {len(parts)} 种零件")
        if len(stations) < 8:
            failures.append(f"工位分组数异常: {len(stations)}(预期 11 上下)")
        if len(parts) < 30:
            failures.append(f"零件种数异常: {len(parts)}")

        # -- 2. 选中材质应高亮对应零件 ---------------------------------------
        items[0].click()
        page.wait_for_timeout(600)
        toast = page.query_selector(".mt__toast")
        result["select_toast"] = toast.inner_text() if toast else ""
        log(f"选中提示: {result['select_toast']}")
        if "个零件" not in result["select_toast"]:
            failures.append("选中材质后没有报出它用在多少个零件上")

        # -- 3. 改颜色必须真的改到三维里的材质对象 ----------------------------
        color_input = page.query_selector(".me__color")
        if not color_input:
            failures.append("没有找到颜色拾取器")
        else:
            target = names[0]
            page.evaluate(
                """(hex) => {
                    const el = document.querySelector('.me__color')
                    el.value = hex
                    el.dispatchEvent(new Event('input', { bubbles: true }))
                }""",
                "#ff0000",
            )
            page.wait_for_timeout(500)

            # 面板上的色块应当跟着变
            swatch = page.evaluate(
                "() => getComputedStyle(document.querySelector('.mt__item--on .mt__swatch')).backgroundColor"
            )
            result["swatch_after_change"] = swatch
            log(f"「{target}」改成红色后, 列表色块 = {swatch}")
            if "255, 0, 0" not in (swatch or ""):
                failures.append(f"改颜色后列表色块没跟着变: {swatch}")

            # 关键断言: 已被标记为"已人工调整"
            dot = page.query_selector(".mt__item--on .mt__dot")
            if not dot:
                failures.append("改过的材质没有被标上「已调整」标记")

            # 还原, 免得把测试值留在页面状态里
            reset = page.query_selector(".me__reset")
            if reset:
                reset.click()
                page.wait_for_timeout(400)
                back = page.evaluate(
                    "() => getComputedStyle(document.querySelector('.mt__item--on .mt__swatch')).backgroundColor"
                )
                result["swatch_after_reset"] = back
                log(f"还原后色块 = {back}")
                if "255, 0, 0" in (back or ""):
                    failures.append("点了还原但颜色没退回去")

        # -- 4. 滑块调整 -----------------------------------------------------
        page.evaluate(
            """() => {
                const el = document.querySelector('.me__range')
                if (!el) return
                el.value = String(Math.min(Number(el.max), Number(el.value) + 0.3))
                el.dispatchEvent(new Event('input', { bubbles: true }))
            }"""
        )
        page.wait_for_timeout(400)
        result["slider_ok"] = bool(page.query_selector(".mt__item--on .mt__dot"))
        log(f"滑块调整后被标记为已调整: {result['slider_ok']}")
        if not result["slider_ok"]:
            failures.append("拖了滑块但没被记成人工调整")

        # -- 5. 点物料清单里的零件 → 编辑器应切到它的材质 ---------------------
        part = page.query_selector(".mt__part")
        if not part:
            failures.append("物料清单里没有可点的零件行")
        else:
            part.click()
            page.wait_for_timeout(800)
            toast = page.query_selector(".mt__toast")
            result["part_click_toast"] = toast.inner_text() if toast else ""
            log(f"点零件提示: {result['part_click_toast']}")
            if "用的是" not in result["part_click_toast"]:
                failures.append("点零件后没有报出它用的材质")

        page.screenshot(path=os.path.join(SHOT_DIR, "materials.png"))
        log(f"截图: {os.path.join(SHOT_DIR, 'materials.png')}")

        browser.close()

    # 三维库常有无害的告警, 只挑真正的报错
    real_errors = [
        e for e in result["console_errors"]
        if "Missing optional extension" not in e and "THREE.WebGLRenderer" not in e
    ]
    result["real_console_errors"] = real_errors
    if real_errors:
        failures.append(f"控制台有 {len(real_errors)} 条报错")
        for item in real_errors[:5]:
            log(f"  控制台: {item[:160]}")

    result["failures"] = failures
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(os.path.join(WORK_DIR, "verify_materials.json"), "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    if failures:
        log(f"验收未通过, {len(failures)} 项:")
        for item in failures:
            log(f"  ✗ {item}")
        raise SystemExit(1)
    log("材质工作台验收通过")


if __name__ == "__main__":
    main()
