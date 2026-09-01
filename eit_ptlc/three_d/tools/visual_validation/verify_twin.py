"""
功能: 三维前端的自动化验收脚本. 启动开发服务器, 用真实浏览器打开页面, 等模型加载完成,
      读取 HUD 指标(帧率/绘制调用/三角形/加载耗时), 并从多个机位截图.

为什么用有头(headed)浏览器: 无头 Chromium 默认走 SwiftShader 软件光栅化, 测出来的帧率
毫无意义. M0 的出口条件里有"≥45fps", 必须用真实 GPU 才能验证.

用法:
    python verify_twin.py                       # 验收已启动的 PTLC 上位机
    python verify_twin.py --url http://localhost:18080/3d/live
    python verify_twin.py --headless            # 只要截图不看帧率时可用
    python verify_twin.py --model /models/raw.glb        # 验收指定模型

参数: 见 main() 中的 argparse 定义
返回值: 无; 未达出口条件时以退出码 1 结束
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews"))

# M0 出口条件
EXIT_CRITERIA = {
    "load_seconds": 5.0,
    "fps": 45,
}

# 截图机位: (预设按钮文案, 文件名后缀)
VIEWS = [("轴测", "iso"), ("前", "front"), ("左", "left"), ("俯", "top")]


def log(message: str) -> None:
    """
    功能: 打印带时间戳的日志.
    参数:
        message: 日志内容
    返回值: None
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    """
    功能: 检测端口是否已被监听.
    参数:
        port: 端口号
        host: 主机
    返回值: bool
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def require_host(port: int) -> None:
    """
    功能: 确认 PTLC 上位机已经在目标端口监听.
    参数:
        port: 上位机端口.
    返回值:
        无.
    """
    if port_open(port) is False:
        raise SystemExit(
            f"PTLC 上位机端口 {port} 未监听, 请先构建前端并运行 "
            'C:/ProgramData/miniforge3/python.exe eit_ptlc/main.py --no-browser'
        )
    log(f"PTLC 上位机已就绪: http://localhost:{port}")


def run_checks(url: str, headless: bool, wait_seconds: int) -> dict:
    """
    功能: 用 Playwright 打开页面, 等待模型加载, 采集指标并截图.
    参数:
        url: 页面地址
        headless: 是否无头模式
        wait_seconds: 等待模型加载的最长秒数
    返回值: dict, 采集到的指标与截图路径
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    result: dict = {"url": url, "console_errors": [], "screenshots": []}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=[
                "--use-gl=angle",
                "--enable-gpu",
                "--ignore-gpu-blocklist",
                "--enable-unsafe-swiftshader",  # 无头回退时避免 WebGL 直接不可用
            ],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        page.on(
            "console",
            lambda msg: result["console_errors"].append(msg.text)
            if msg.type == "error"
            else None,
        )
        page.on("pageerror", lambda err: result["console_errors"].append(str(err)))

        log(f"打开 {url}")
        started = time.time()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        # 先等三维视图组件本身挂载. 集成进上位机 SPA 后整个控制台要先启动,
        # 若直接等"遮罩消失", 组件还没渲染时遮罩根本不存在, detached 会立刻满足,
        # 于是在场景尚未初始化时就去读指标, 读到的全是 0.
        try:
            page.wait_for_selector(".twin", state="attached", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            result["load_seconds"] = None
            result["load_error"] = f"三维视图组件未挂载: {exc}"
            log(result["load_error"])
            browser.close()
            return result

        # 加载遮罩消失即代表模型解析完毕
        try:
            page.wait_for_selector(".twin__overlay", state="detached", timeout=wait_seconds * 1000)
            result["load_seconds"] = round(time.time() - started, 2)
            log(f"模型加载完成, 耗时 {result['load_seconds']}s")
        except Exception:  # noqa: BLE001
            error = page.query_selector(".twin__error-detail")
            result["load_seconds"] = None
            result["load_error"] = error.inner_text() if error else "加载超时且未显示错误信息"
            log(f"模型加载失败: {result['load_error']}")
            browser.close()
            return result

        # 让渲染循环与遥测都稳定下来再读指标: HUD 每秒刷新一次帧率,
        # 工位健康度每 500 ms 同步一次, 遥测本身是 1 Hz, 留足两轮
        page.wait_for_timeout(6000)

        metrics = page.evaluate(
            """() => {
              const read = (label) => {
                for (const row of document.querySelectorAll('.hud__metric')) {
                  if (row.querySelector('dt')?.textContent?.trim() === label) {
                    return row.querySelector('dd')?.textContent?.trim() || null
                  }
                }
                return null
              }
              return {
                fps: read('帧率'),
                drawCalls: read('绘制调用'),
                triangles: read('三角形'),
                loadTime: read('加载耗时'),
                size: read('整机尺寸'),
                axesRigged: read('已装配轴'),
              }
            }"""
        )
        result["hud"] = metrics
        log(f"HUD 指标: {json.dumps(metrics, ensure_ascii=False)}")

        # 实时接入情况: 连接状态 + 工位芯片及其健康度
        live = page.evaluate(
            """() => {
              const chips = [...document.querySelectorAll('.hud__station')].map((el) => {
                const dot = el.querySelector('.hud__station-dot')
                const health = [...(dot?.classList || [])]
                  .find((c) => c.startsWith('hud__station-dot--'))
                  ?.replace('hud__station-dot--', '') || 'unknown'
                return { name: el.querySelector('.hud__station-name')?.textContent?.trim(), health }
              })
              return {
                connected: document.querySelector('.hud__live')?.textContent?.trim() || '',
                stations: chips,
              }
            }"""
        )
        result["live"] = live
        log(f"事件流: {live['connected']}; 工位芯片 {len(live['stations'])} 个")
        for chip in live["stations"]:
            log(f"    {chip['name']:<12} {chip['health']}")

        # 多机位截图, 供人工审查外观
        for label, suffix in VIEWS:
            button = page.query_selector(f".hud__btn:text-is('{label}')")
            if button:
                button.click()
                page.wait_for_timeout(1400)  # 等相机阻尼过渡结束
            shot = os.path.join(SHOT_DIR, f"twin_{suffix}.png")
            page.screenshot(path=shot)
            result["screenshots"].append(shot)
            log(f"截图: {shot}")

        # 交互验证: 点第一个工位芯片, 检查详情面板是否弹出并有内容
        chip = page.query_selector(".hud__station")
        if chip:
            chip.click()
            page.wait_for_timeout(1800)
            panel = page.evaluate(
                """() => {
                  const el = document.querySelector('.panel')
                  if (!el) return null
                  return {
                    title: el.querySelector('.panel__title')?.textContent?.trim(),
                    node: el.querySelector('.panel__node')?.textContent?.trim(),
                    fields: el.querySelectorAll('.panel__field').length,
                    axes: el.querySelectorAll('.panel__axis').length,
                    tanks: el.querySelectorAll('.panel__tank').length,
                    hasActions: Boolean(el.querySelector('.panel__toggle')),
                  }
                }"""
            )
            result["panel"] = panel
            log(f"工位面板: {json.dumps(panel, ensure_ascii=False)}")
            shot = os.path.join(SHOT_DIR, "twin_panel.png")
            page.screenshot(path=shot)
            result["screenshots"].append(shot)
            log(f"截图: {shot}")

        browser.close()

    return result


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="三维前端自动化验收")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--url", default=None, help="直接指定三维实时页面地址")
    parser.add_argument("--headless", action="store_true", help="无头模式(帧率不可信)")
    parser.add_argument("--wait", type=int, default=180, help="等待模型加载的最长秒数")
    args = parser.parse_args()

    if args.url:
        url = args.url
    else:
        require_host(args.port)
        url = f"http://localhost:{args.port}/3d/live"

    try:
        result = run_checks(url, args.headless, args.wait)

        print("\n" + "=" * 60)
        print("出口条件核对")
        print("=" * 60)

        failures = []
        # 有工位芯片却没弹出面板才算失败; 完全没有芯片说明 manifest 未接入, 单独报
        chip_expected = bool((result.get("live") or {}).get("stations"))
        load_seconds = result.get("load_seconds")
        if load_seconds is None:
            print(f"加载        : 失败 —— {result.get('load_error')}")
            failures.append("模型未能加载")
        else:
            passed = load_seconds <= EXIT_CRITERIA["load_seconds"]
            print(
                f"加载耗时    : {load_seconds:.2f}s  (上限 {EXIT_CRITERIA['load_seconds']}s)  "
                f"{'通过' if passed else '不通过'}"
            )
            if not passed:
                failures.append("加载耗时超标")

            fps_text = (result.get("hud") or {}).get("fps") or ""
            fps = int("".join(ch for ch in fps_text if ch.isdigit()) or 0)
            passed = fps >= EXIT_CRITERIA["fps"]
            print(
                f"帧率        : {fps} fps  (下限 {EXIT_CRITERIA['fps']} fps)  "
                f"{'通过' if passed else '不通过'}"
                + ("   [无头模式下帧率不可信]" if args.headless else "")
            )
            if not passed and not args.headless:
                failures.append("帧率不达标")

            hud = result.get("hud") or {}
            print(f"绘制调用    : {hud.get('drawCalls')}")
            print(f"三角形      : {hud.get('triangles')}")
            print(f"整机尺寸    : {hud.get('size')}")
            print(f"已装配轴    : {hud.get('axesRigged')}")

            live = result.get("live") or {}
            online = [c for c in live.get("stations", []) if c["health"] not in ("offline", "unknown")]
            print(
                f"事件流      : {live.get('connected')}  "
                f"工位 {len(live.get('stations', []))} 个, 其中有实时状态 {len(online)} 个"
            )
            if live.get("connected") != "实时":
                failures.append("未接入上位机事件流")

            panel = result.get("panel")
            if panel:
                print(
                    f"工位面板    : {panel.get('title')} · 状态字段 {panel.get('fields')} 项 · "
                    f"轴 {panel.get('axes')} 条 · 展缸 {panel.get('tanks')} 个 · "
                    f"动作列表 {'有' if panel.get('hasActions') else '无'}"
                )
            elif chip_expected:
                failures.append("点击工位后未弹出详情面板")

        errors = [e for e in result["console_errors"] if "favicon" not in e.lower()]
        if errors:
            print(f"\n控制台错误 ({len(errors)} 条):")
            for message in errors[:8]:
                print(f"  {message[:200]}")

        print(f"\n截图: {len(result['screenshots'])} 张, 位于 {SHOT_DIR}")

        report_path = os.path.join(SHOT_DIR, "verify_twin.json")
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"报告: {report_path}")

        if failures:
            print(f"\n未通过: {', '.join(failures)}")
            raise SystemExit(1)
        print("\nM0 出口条件全部通过")
    finally:
        # Playwright 在 run_checks 内完成释放, 此处保留统一异常边界.
        pass


if __name__ == "__main__":
    main()
