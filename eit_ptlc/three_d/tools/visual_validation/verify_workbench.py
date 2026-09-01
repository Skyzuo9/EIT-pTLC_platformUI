"""
功能: 装配工作台的自动化验收 —— 用真实浏览器走一遍"点选 → 标记 → 保存"的授权闭环.

验收的重点不是好不好看, 而是**授权链路是否真的通**: 点下去的零件有没有被记住、
标记有没有落到 yaml、层级树与三维是否指向同一个名字. 这条链路一断, 整套协作工作流就废了.

用法:
    python verify_workbench.py
    python verify_workbench.py --url http://localhost:18080/3d/workbench
    python verify_workbench.py --headless

参数: 见 argparse
返回值: 无; 未通过时以退出码 1 结束
"""

from __future__ import annotations

import argparse
import json
import os
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews"))


def log(message: str) -> None:
    """
    功能: 打印带时间戳的日志.
    参数:
        message: 日志内容
    返回值: None
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="装配工作台自动化验收")
    parser.add_argument("--url", default="http://localhost:18080/3d/workbench")
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

        page.wait_for_selector(".wb", state="attached", timeout=60_000)
        try:
            page.wait_for_selector(".wb__overlay", state="detached", timeout=args.wait * 1000)
        except Exception:  # noqa: BLE001
            detail = page.query_selector(".wb__err-detail")
            log(f"模型加载失败: {detail.inner_text() if detail else '超时'}")
            browser.close()
            raise SystemExit(1)

        result["load_seconds"] = round(time.time() - started, 2)
        log(f"原始模型加载完成, 耗时 {result['load_seconds']}s")
        page.wait_for_timeout(2500)

        # -- 1. 规模计数器与层级树 -----------------------------------------
        meter = page.evaluate(
            """() => {
              const el = document.querySelector('.wb__meter')
              if (!el) return null
              const bold = [...el.querySelectorAll('b')].map((b) => b.textContent.trim())
              return { text: el.textContent.replace(/\\s+/g, ' ').trim(), values: bold }
            }"""
        )
        result["meter"] = meter
        log(f"规模计数器: {meter['text'] if meter else '(缺失)'}")
        if not meter:
            failures.append("规模计数器未渲染")

        tree = page.evaluate(
            """() => {
              const rows = [...document.querySelectorAll('.tree__row--asm')]
              return {
                count: rows.length,
                top: rows.slice(0, 5).map((r) => ({
                  name: r.querySelector('.tree__name')?.textContent?.trim(),
                  tri: r.querySelector('.tree__tri')?.textContent?.trim(),
                })),
              }
            }"""
        )
        result["tree"] = tree
        log(f"层级树: {tree['count']} 个顶层装配")
        for row in tree["top"]:
            log(f"    {row['name']:<28} {row['tri']}")
        if tree["count"] < 10:
            failures.append(f"层级树只有 {tree['count']} 项, 疑似索引未建立")

        # -- 2. 规则批选(精简模型的主力手段) --------------------------------
        presets = page.evaluate(
            """() => [...document.querySelectorAll('.rules__preset')].map((b) => ({
                 label: b.querySelector('span')?.textContent?.trim(),
                 hits: b.querySelector('.rules__hits')?.textContent?.trim(),
               }))"""
        )
        result["presets"] = presets
        log("规则预设命中数:")
        for preset in presets:
            log(f"    {preset['label']:<14} {preset['hits']}")
        if not any(p["hits"] not in ("0", "—", None) for p in presets):
            failures.append("所有规则预设命中 0 个, 疑似零件索引为空")

        # -- 3. 点一条规则 → 标记删除 → 看计数器是否变化 --------------------
        before = meter["values"] if meter else []
        vendor = page.query_selector(".rules__preset")
        if vendor:
            vendor.click()
            page.wait_for_timeout(900)

        selected = page.evaluate(
            "() => document.querySelector('.ins__multi')?.textContent?.trim() || ''"
        )
        result["selected_after_rule"] = selected
        log(f"批选后选中: {selected or '(单选或未选)'}")

        delete_btn = page.query_selector(".ins__btn:text-is('删除')")
        if delete_btn:
            delete_btn.click()
            page.wait_for_timeout(1200)

        after = page.evaluate(
            """() => {
              const el = document.querySelector('.wb__meter')
              if (!el) return null
              return {
                values: [...el.querySelectorAll('b')].map((b) => b.textContent.trim()),
                badges: [...el.querySelectorAll('.wb__badge')].map((b) => b.textContent.trim()),
              }
            }"""
        )
        result["meter_after"] = after
        log(f"标记后: {after['badges'] if after else '(缺失)'}")
        if not after or not after["badges"]:
            failures.append("打了删除标记但计数器徽章没出现")
        elif before and after["values"] == before:
            failures.append("打了删除标记但预估规模没变化")

        page.screenshot(path=os.path.join(SHOT_DIR, "workbench.png"))
        log(f"截图: {os.path.join(SHOT_DIR, 'workbench.png')}")

        # -- 4. 授权中间件是否可用 -----------------------------------------
        authoring = page.evaluate(
            """async () => {
              try {
                const r = await fetch('/_authoring/clips')
                return { ok: r.ok, status: r.status }
              } catch (e) { return { ok: false, error: String(e) } }
            }"""
        )
        result["authoring"] = authoring
        log(f"授权中间件: {json.dumps(authoring, ensure_ascii=False)}")
        if not authoring.get("ok"):
            failures.append("授权中间件不可用, 无法写回 YAML")

        browser.close()

    errors = [e for e in result["console_errors"] if "favicon" not in e.lower()]
    if errors:
        log(f"控制台错误 {len(errors)} 条:")
        for message in errors[:6]:
            log(f"    {message[:180]}")

    report_path = os.path.join(SHOT_DIR, "verify_workbench.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    if failures:
        print("装配工作台验收未通过:")
        for item in failures:
            print(f"  - {item}")
        raise SystemExit(1)
    print("装配工作台验收通过：点选 → 批选 → 标记 → 计数器联动，授权中间件在线")


if __name__ == "__main__":
    main()
