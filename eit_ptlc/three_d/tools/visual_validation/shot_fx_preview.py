"""
功能: AR 增强显示效果预览沙盒的截图矩阵(第四轮) —— 给用户出一册可挑选的"效果图".

每张图 = 独立 goto 一条完整 URL(状态零残留) + 等 window.__fx.ready + 可选的
__fx.api 调用/悬停模拟 + 定长 settle + 截图. 产物落 three_d/work/previews/fx/,
附 fx_shots.json 记录每图的复现凭据.

第四轮变化: 页面套仿正式外壳(所有镜头都带侧栏/顶栏/页签 —— 这就是产品形态);
开场换"幽灵整机→左→右实体化"扫场(intro_mid 播放 1.2s 定在半幽灵半实体);
聚焦/巡检 = 每工位定制视角; 新增开关门镜头(门动画走真实时间, 不能 freezetime).

悬停镜头: hover 字段指定工位 —— 先等 BVH 就绪, 用 api.hoverProbe 在该工位顶部带
包络里扫格找实心点, 再把鼠标移过去(与真实用户行为同路径).

前提: vite 15173 + 后端 18080 均在线.
用法: C:/ProgramData/miniforge3/python.exe shot_fx_preview.py [--only 子串] [--list]
"""

from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews", "fx"))
BASE = "http://localhost:15173/fx-preview.html"

# 截图矩阵: dict(name, params, api=[], settle=毫秒, hover=工位id或None)
SHOTS = [
    # 常态: 仿真外壳里的干净机器(左右两个标准机位)
    dict(name="showcase_iso", params="scenario=showcase&freezetime=2.2&intro=0&panel=0", settle=1200),
    dict(name="showcase_front", params="scenario=showcase&cam=front&freezetime=2.2&intro=0&panel=0", settle=1200),
    # 悬停白卡(realvirtual 风格): 运行中工位 / 故障工位
    dict(name="hover_sampling", params="scenario=showcase&freezetime=2.2&intro=0&panel=0", hover="SAMPLING", settle=600),
    dict(name="hover_error_develop", params="scenario=showcase&freezetime=2.083&intro=0&panel=0", hover="DEVELOP", settle=600),
    # 聚焦 = 每工位定制视角(正面半球 + 完整入画): 幽灵/隐藏/机械臂/中转/右端上样
    dict(name="focus_vision", params="scenario=showcase&focus=VISION&freezetime=2.5&intro=0&panel=0", settle=1500),
    dict(name="focus_develop_ghost", params="scenario=showcase&focus=DEVELOP&freezetime=2.5&intro=0&panel=0", settle=1500),
    dict(name="focus_develop_hide", params="scenario=showcase&focus=DEVELOP&isolate=hide&freezetime=2.5&intro=0&panel=0", settle=1500),
    dict(name="focus_robot_rail", params="scenario=showcase&focus=ROBOT&freezetime=2.5&intro=0&panel=0", settle=1500),
    dict(name="focus_staginga", params="scenario=showcase&focus=STAGINGA&freezetime=2.5&intro=0&panel=0", settle=1500),
    dict(name="focus_sampling", params="scenario=showcase&focus=SAMPLING&freezetime=2.5&intro=0&panel=0", settle=1500),
    # 开关门(动画走真实时间 —— 不能 freezetime; idle 剧本保持画面安静)
    # 对开门只驱一扇 —— 另一扇靠 pair 连动跟上. 少开一扇就是连动断了, 图上一眼看得见.
    dict(name="door_open_side", params="scenario=idle&cam=left&intro=0&panel=0",
         api=["window.__fx.api.setDoor('sideL1', true)"], settle=1800),
    # 正面三扇全开: feed(右, 铰链在右沿) + 左半对开门一对; 看的是"把手侧张开、朝机外开"
    dict(name="door_open_front", params="scenario=idle&cam=front&intro=0&panel=0",
         api=["window.__fx.api.setDoor('feed', true)", "window.__fx.api.setDoor('frontL1', true)"], settle=1800),
    # 背面三扇全开(与正面镜像)
    dict(name="door_open_back", params="scenario=idle&cam=back&intro=0&panel=0",
         api=["window.__fx.api.setDoor('back', true)", "window.__fx.api.setDoor('backL1', true)"], settle=1800),
    # 流程片段播放(真机构动画 + 悬停卡/顶栏联动)
    dict(name="clip_sampling", params="clip=flow.sampling_execute&clipt=11&freezetime=2.2&intro=0&panel=0", settle=1400),
    dict(name="clip_panel", params="clip=flow.sampling_execute&clipt=11&freezetime=2.2&intro=0", settle=1400),
    # 新开场扫场中段: 播放 1.2s 时前沿约 30%, 左实体右幽灵最有叙事感
    dict(name="intro_mid", params="scenario=running&intro=0&panel=0",
         api=["window.__fx.api.playIntro()"], settle=1200),
    # 主题与降级
    dict(name="showcase_light", params="theme=light&scenario=showcase&freezetime=2.2&intro=0&panel=0", settle=1200),
    dict(name="showcase_low", params="quality=low&scenario=showcase&freezetime=2.2&intro=0&panel=0", settle=1200),
    # 带控制面板工作照(第四轮: 面板已是正式页卡片皮, 顶栏计数/运行指示活动中)
    dict(name="with_panel", params="scenario=running&freezetime=2.2&intro=0", settle=1200),
]


def find_hover_point(page, station: str):
    """功能: 在工位顶部带包络里扫格找一个 hoverProbe 命中的实心点. 返回 (x,y)|None"""
    page.wait_for_function("() => window.__fx.api.stats().bvhReady", timeout=60_000)
    top = page.evaluate(f"() => window.__fx.api.debugAnchors().{station}.top")
    for fx_ in (0.5, 0.4, 0.6, 0.25, 0.75):
        for fy_ in (0.5, 0.3, 0.7):
            px = top["x1"] + (top["x2"] - top["x1"]) * fx_
            py = top["y1"] + (top["y2"] - top["y1"]) * fy_
            if page.evaluate(f"() => window.__fx.api.hoverProbe({px}, {py})") == station:
                return px, py
    return None


def main() -> None:
    """功能: 命令行入口. 参数: --only 子串 / --list. 返回值: None"""
    only = ""
    if "--list" in sys.argv:
        for shot in SHOTS:
            print(f"{shot['name']}\n    {BASE}?{shot['params']}")
        return
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    manifest = []
    failures = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"]
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        for shot in SHOTS:
            if only and only not in shot["name"]:
                continue
            url = f"{BASE}?{shot['params']}"
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_function("() => window.__fx?.ready", timeout=120_000)
            errors = page.evaluate("() => window.__fx.errors")
            if errors:
                failures.append((shot["name"], errors))
                print(f"✗ {shot['name']}: __fx.errors = {errors}")
                continue
            for call in shot.get("api", []):
                page.evaluate(call)
            hover = shot.get("hover")
            if hover:
                point = find_hover_point(page, hover)
                if not point:
                    failures.append((shot["name"], [f"找不到 {hover} 的悬停实心点"]))
                    print(f"✗ {shot['name']}: 找不到 {hover} 悬停点")
                    continue
                page.mouse.move(*point)
            page.wait_for_timeout(shot["settle"])
            path = os.path.join(SHOT_DIR, f"fx_{shot['name']}.png")
            page.screenshot(path=path)
            print(f"✓ fx_{shot['name']}.png")
            manifest.append({"name": shot["name"], "url": url, "api": shot.get("api", []),
                             "hover": hover, "file": f"fx_{shot['name']}.png"})

        browser.close()

    with open(os.path.join(SHOT_DIR, "fx_shots.json"), "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)
    print(f"\n共 {len(manifest)} 张, 产物目录: {SHOT_DIR}")
    if failures:
        print(f"失败 {len(failures)} 张: {[f[0] for f in failures]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
