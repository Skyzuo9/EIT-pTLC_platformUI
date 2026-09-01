"""
功能: fx-preview 沙盒第四轮的程序化验收 —— 截图之外的硬断言.

检查项(对应用户第四轮反馈, 含三轮遗产回归):
  1. 工位归属(重建产物): 小铁片 033-3 已离开 COLLECT 落进 FEEDLIFT; 三轮的
     VISION/STAGINGA/COLLECT 归属不回退; 门体+把手十七件独立(不在任何合并块);
     八扇门的合页门叶各自成组(每组 2 片)
  2. 仿真外壳: 侧栏 13 项/顶栏 4 计数/页签 5 个, 画布非满屏(视口偏移>0) ——
     悬停/锚点断言在偏移视口下通过 = 视口重构的页面像素契约被真实检验
  3. 无圆点: DOM 里 .fxdot 数量为 0
  4. 锚点准度(iso/front) + 工位清单(无 RAIL/合并机械臂/VISION) —— 三轮口径
  5. 曝光健康 —— 二轮口径
  6. 悬停白卡: 移上出卡内容对, 移开消失 —— 三轮口径(偏移视口下跑)
  7. 定制视角: 逐站聚焦后相机在正面半球(|azDeg|<90) + 工位投影完整入画(ROBOT
     因定半径框臂体豁免整轨入画, 改断锚点可见)
  8. 聚焦实体化 + 无压暗 + hide 隔离 + blur 还原 —— 三轮口径
  9. 开场扫场: 播放中输入被门控(focus 无效且不投毒), Esc/abort 全量还原,
     完整播完后聚焦仍实体(幽灵无泄漏)
 10. 开关门: 八扇全解析, toggleDoor 后 t->1, 对开门点一扇两扇同开同关,
     开门态下聚焦/退出不留台账, 再关回 t->0
 11. 流程片段播放 —— 二轮口径
 12. 全程 __fx.errors 为空

前提: vite 15173 + 后端 18080 均在线.
用法: C:/ProgramData/miniforge3/python.exe verify_fx_preview.py
"""

from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "models"))
BASE = "http://localhost:15173/fx-preview.html"

PASS = []
FAIL = []

STATION_VIEW_IDS = ["RACK", "DEVELOP", "PUMP", "TOOLING", "ROBOT", "VISION",
                    "COLLECT", "STAGINGA", "FEEDLIFT", "PHOTOSCRAPE", "SAMPLING"]


def check(name: str, ok: bool, detail: str = "") -> None:
    """功能: 记一条断言结果. 参数: 名字/结果/细节. 返回值: None"""
    (PASS if ok else FAIL).append(name)
    print(f"{'✓' if ok else '✗'} {name}" + (f"   {detail}" if detail else ""))


def goto(page, params: str):
    """功能: 打开一条沙盒 URL 并等 ready, 回传 __fx.errors. 参数: page/查询串. 返回值: errors"""
    page.goto(f"{BASE}?{params}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => window.__fx?.ready", timeout=120_000)
    return page.evaluate("() => window.__fx.errors")


def assert_anchors(page, tag: str) -> None:
    """功能: 锚点准度断言(当前页面; debugAnchors 出参为页面像素, 平移不变). 返回值: None"""
    data = page.evaluate("() => window.__fx.api.debugAnchors()")
    checked = 0
    bad = []
    for sid, entry in data.items():
        anchor = entry["anchor"]
        top = entry["top"]
        if not anchor["visible"] or top["x1"] > top["x2"]:
            continue
        checked += 1
        x_ok = (top["x1"] - 24) <= anchor["x"] <= (top["x2"] + 24)
        y_span = max(top["y2"] - top["y1"], 1)
        y_ok = (top["y1"] - 140) <= anchor["y"] <= (top["y1"] + max(40, 0.4 * y_span))
        if not (x_ok and y_ok):
            bad.append(f"{sid}(x={anchor['x']:.0f} 带=[{top['x1']:.0f},{top['x2']:.0f}] y={anchor['y']:.0f}/{top['y1']:.0f})")
    check(f"锚点准度[{tag}]: 全部落在顶部带包络内", not bad and checked >= 6,
          f"检查 {checked} 个" + (f", 越界: {bad}" if bad else ""))


def luminance_of(page, tmp: str, name: str, rect=None):
    """功能: 截图求亮度统计(rect 非空时只统计 3D 画布区 —— 外壳顶栏浅色是纯白 UI,
    混进来会把'过曝'指标顶爆). 参数: page/临时目录/名字/画布矩形. 返回值: (mean, 过曝占比)"""
    import numpy as np
    from PIL import Image

    path = os.path.join(tmp, f"{name}.png")
    page.screenshot(path=path)
    img = Image.open(path).convert("RGB")
    if rect:
        img = img.crop((int(rect["left"]), int(rect["top"]),
                        int(rect["left"] + rect["width"]), int(rect["top"] + rect["height"])))
    rgb = np.asarray(img, dtype=np.uint8)
    return float(rgb.mean()), float((rgb.max(axis=2) >= 250).mean())


def main() -> None:
    """功能: 命令行入口. 参数: 无. 返回值: None(断言失败以退出码 1 结束)"""
    import tempfile

    from playwright.sync_api import sync_playwright

    # -- 1. 工位归属与门分离(直接读重建产物, 不经浏览器) -----------------------------
    manifest = json.load(open(os.path.join(MODELS_DIR, "device-manifest.official-cr5.json"), encoding="utf-8"))
    station_ids = [s["id"] for s in manifest["stations"]]
    check("manifest 含 VISION 视觉定位组", "VISION" in station_ids, str(station_ids))
    blocks = json.load(open(os.path.join(MODELS_DIR, "merge-members.json"), encoding="utf-8"))["blocks"]
    names_of = lambda st: [m["name"] for path, ms in blocks.items() if path.startswith(st) for m in ms]
    col = names_of("ST_COLLECT/")
    fee = names_of("ST_FEEDLIFT/")
    sta = names_of("ST_STAGINGA/")
    vis = names_of("ST_VISION/")
    piece = "瓶子检测光电传感器安装板-3"
    check("小铁片 033-3 已离开 COLLECT", not any(piece in n for n in col), "")
    check("小铁片 033-3 落进 FEEDLIFT", any(piece in n for n in fee), "")
    check("COLLECT 无中转座残留(PTLC-07)", not any("PTLC-07" in n for n in col), "")
    sta_kinds = sorted({n.split(" ")[0] for n in sta if "PTLC-07" in n})
    check("STAGINGA 收齐中转座固定件", len(sta_kinds) == 7, str(sta_kinds))
    check("VISION 含下相机支架件", any("PTLC-08-001" in n or "下相机" in n for n in vis), str(vis[:3]))
    all_merged = [m["name"] for ms in blocks.values() for m in ms]
    # 九件门体 + 八只把手必须全部脱离静态合并块, 否则 fx/doors.js 挂不上枢轴
    # (整块只能一起动, 而它们分属 8 扇不同的门).
    # 名带"固定"的那 4 扇一度被判为不可开而漏掉, 实为误判 —— CAD 里每扇都带合页带把手.
    door_parts = ("上料门板-1", "侧门-1", "侧门-2", "侧门板-1", "门板-5",
                  "固定门板-2", "固定门板-3", "固定门板-5", "固定门板-6",
                  "XAD51-A100-1", "XAD51-A100-2", "XAD51-A100-3", "XAD51-A100-4",
                  "XAD51-A100-5", "XAD51-A100-6", "XAD51-A100-7", "XAD51-A100-8")
    doors_free = [d for d in door_parts if not any(d == n for n in all_merged)]
    check("门体与把手共十七件独立(不在任何合并块)", len(doors_free) == len(door_parts),
          "仍被合并: " + str([d for d in door_parts if d not in doors_free]))
    # 合页门叶: 16 片在 CAD 里同名, 由 blender_clean.rename_door_hinge_leaves 按几何改成
    # DOOR_HINGE_<门键>, 同扇两片同名 -> 合并成一个块. 每扇必须恰好 2 片, 少了就是归属错.
    door_keys = ("feed", "back", "sideL1", "sideL2", "frontL1", "frontL2", "backL1", "backL2")
    hinge_bad = []
    for key in door_keys:
        blk = [b for b in blocks if b.endswith(f"STATIC_MAT_SOLO_DOOR_HINGE_{key}")]
        members = sum(len(blocks[b]) for b in blk)
        if len(blk) != 1 or members != 2:
            hinge_bad.append(f"{key}:块{len(blk)}/片{members}")
    check("八扇门的合页门叶各成一组(每组 2 片)", not hinge_bad, str(hinge_bad))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"]
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})

        # -- 2+3. 外壳与无圆点 ------------------------------------------------------
        errors = goto(page, "scenario=showcase&freezetime=2.2&intro=0")
        check("showcase 页无 JS 错误", not errors, str(errors))
        shellinfo = page.evaluate(
            "() => ({ rail: document.querySelectorAll('#fxsh-rail .rail-tab').length,"
            " chips: document.querySelectorAll('#fxsh-status .chip').length,"
            " tabs: document.querySelectorAll('#fxsh-tabs .app__tab').length,"
            " dots: document.querySelectorAll('.fxdot').length,"
            " estop: !!document.querySelector('#fxsh-status .estop') })")
        check("仿真外壳就位(侧栏13/计数4/页签5/急停)",
              shellinfo["rail"] == 13 and shellinfo["chips"] == 4 and shellinfo["tabs"] == 5 and shellinfo["estop"],
              str(shellinfo))
        check("状态圆点已全部退役", shellinfo["dots"] == 0, "")
        rect = page.evaluate(
            "() => { const r = document.querySelector('#fx-app canvas').getBoundingClientRect();"
            " return { left: r.left, top: r.top, width: r.width, height: r.height } }")
        check("画布非满屏(外壳生效, 视口偏移>0)", rect["left"] > 40 and rect["top"] > 60, str(rect))

        # -- 4. 锚点准度 + 工位清单(在偏移视口下跑 = 视口契约检验) ---------------------
        anchors = page.evaluate("() => window.__fx.api.debugAnchors()")
        check("清单: 无 RAIL / 有合并机械臂 / 有 VISION",
              "RAIL" not in anchors and anchors.get("ROBOT", {}).get("label") == "机械臂·地轨"
              and "VISION" in anchors,
              f"ROBOT={anchors.get('ROBOT', {}).get('label')}")
        assert_anchors(page, "iso")
        goto(page, "scenario=showcase&cam=front&freezetime=2.2&intro=0&panel=0")
        assert_anchors(page, "front")

        # -- 5. 曝光 ----------------------------------------------------------------
        with tempfile.TemporaryDirectory() as tmp:
            goto(page, "theme=light&scenario=showcase&freezetime=2.2&intro=0&panel=0")
            page.wait_for_timeout(1200)
            mean, over = luminance_of(page, tmp, "light", rect)
            check("浅色主题不过曝(画布区)", over < 0.03 and 90 <= mean <= 205, f"过曝 {over*100:.2f}%, 均值 {mean:.0f}")
            goto(page, "theme=dark&scenario=showcase&freezetime=2.2&intro=0&panel=0")
            page.wait_for_timeout(1200)
            mean_d, over_d = luminance_of(page, tmp, "dark", rect)
            check("深色主题亮度健康(画布区)", over_d < 0.03 and 12 <= mean_d <= 95, f"过曝 {over_d*100:.2f}%, 均值 {mean_d:.0f}")

            # -- 6. 悬停白卡(先等 BVH 建完, 悬停射线才启用) -----------------------------
            goto(page, "scenario=showcase&freezetime=2.2&intro=0&panel=0")
            page.wait_for_function("() => window.__fx.api.stats().bvhReady", timeout=60_000)
            # 展开工位是两座塔架, 包络中心/锚点正下方都可能落在缝里穿空(实测) ——
            # 先用 hoverProbe 在顶部带包络里扫格找一个确定打中 DEVELOP 的实心点
            top = page.evaluate("() => window.__fx.api.debugAnchors().DEVELOP.top")
            hx = hy = None
            for fx_ in (0.25, 0.4, 0.5, 0.6, 0.75):
                for fy_ in (0.3, 0.5, 0.7):
                    px = top["x1"] + (top["x2"] - top["x1"]) * fx_
                    py = top["y1"] + (top["y2"] - top["y1"]) * fy_
                    if page.evaluate(f"() => window.__fx.api.hoverProbe({px}, {py})") == "DEVELOP":
                        hx, hy = px, py
                        break
                if hx is not None:
                    break
            check("找到打中展开工位的悬停点", hx is not None, "")
            page.mouse.move(hx or 0, hy or 0)
            page.wait_for_timeout(400)
            hovered = page.evaluate("() => window.__fx.api.hoveredStation()")
            card_text = page.evaluate(
                "() => { const c = document.querySelector('.fxwcard[data-mode=hover]');"
                " return c && c.dataset.visible === '1' ? c.textContent : '' }")
            check("悬停出白卡且指向展开工位", hovered == "DEVELOP" and "展开工位" in card_text,
                  f"hovered={hovered}, 卡文含展开工位={'展开工位' in card_text}")
            page.mouse.move(30, 970)  # 空白角落
            page.wait_for_timeout(300)
            gone = page.evaluate(
                "() => document.querySelector('.fxwcard[data-mode=hover]').dataset.visible !== '1'")
            check("移开后白卡消失", bool(gone), "")

            # -- 7. 定制视角逐站: 正面半球 + 完整入画 -----------------------------------
            bad_az = []
            bad_fit = []
            for sid in STATION_VIEW_IDS:
                page.evaluate(f"() => window.__fx.api.focus('{sid}')")
                page.wait_for_timeout(200)
                view = page.evaluate(f"() => window.__fx.api.captureStationView('{sid}')")
                if view is None or abs(view["azDeg"]) >= 90:
                    bad_az.append(f"{sid}(az={view and view['azDeg']})")
                entry = page.evaluate(f"() => window.__fx.api.debugAnchors()['{sid}']")
                if sid == "ROBOT":
                    # 定半径只框臂体, 整条地轨允许出画 —— 改断锚点(臂体)可见
                    if not entry["anchor"]["visible"]:
                        bad_fit.append(f"{sid}(锚点不可见)")
                else:
                    whole = entry["whole"]
                    inside = (whole["x1"] >= rect["left"] - 8 and whole["x2"] <= rect["left"] + rect["width"] + 8
                              and whole["y1"] >= rect["top"] - 8 and whole["y2"] <= rect["top"] + rect["height"] + 8)
                    if not inside:
                        bad_fit.append(f"{sid}([{whole['x1']:.0f},{whole['y1']:.0f}]-[{whole['x2']:.0f},{whole['y2']:.0f}])")
            check("定制视角: 11 站全部正面半球(|az|<90°)", not bad_az, str(bad_az))
            check("定制视角: 模块完整入画(ROBOT 断锚点)", not bad_fit, str(bad_fit))
            page.evaluate("() => window.__fx.api.blur()")

            # -- 8. 聚焦实体化 + 无压暗(同机位前后亮度; 关掉卡片层 —— 白色详情卡
            #        本身会抬均值 +4, 混进来测不出"是否压暗") ----------------------------
            goto(page, "cam=station:DEVELOP&scenario=showcase&freezetime=2.2&isolate=off&fx=focus&intro=0&panel=0")
            mean_a, _ = luminance_of(page, tmp, "prefocus", rect)
            page.evaluate("() => window.__fx.api.focus('DEVELOP')")
            page.wait_for_timeout(500)
            mean_b, _ = luminance_of(page, tmp, "postfocus", rect)
            drift = abs(mean_b - mean_a) / max(mean_a, 1)
            check("聚焦不压暗(isolate=off 同机位亮度漂移<5%)", drift < 0.05,
                  f"{mean_a:.1f} -> {mean_b:.1f} ({drift*100:.1f}%)")

        errors = goto(page, "scenario=showcase&focus=DEVELOP&freezetime=2.5&intro=0&panel=0")
        check("聚焦页无 JS 错误", not errors, str(errors))
        vis_g = page.evaluate("() => window.__fx.api.debugVisibility()")
        check("ghost 隔离: 周围幽灵化且聚焦工位保持实体",
              vis_g["selected"] == "DEVELOP" and vis_g["ghosted"] > 0
              and vis_g["visible"] == vis_g["total"] and vis_g["selectedSolid"],
              f"幽灵 {vis_g['ghosted']}, 可见 {vis_g['visible']}/{vis_g['total']}, 实体={vis_g['selectedSolid']}")
        page.evaluate("() => window.__fx.api.blur()")
        page.wait_for_timeout(200)
        vis_g2 = page.evaluate("() => window.__fx.api.debugVisibility()")
        check("blur 后幽灵台账清零", vis_g2["ghosted"] == 0 and vis_g2["hidden"] == 0, "")

        goto(page, "scenario=showcase&focus=DEVELOP&isolate=hide&freezetime=2.5&intro=0&panel=0")
        vis_h = page.evaluate("() => window.__fx.api.debugVisibility()")
        check("hide 隔离: 可见网格骤降到选中工位量级",
              vis_h["hidden"] > 0 and vis_h["selectedMeshes"] <= vis_h["visible"] <= vis_h["total"] * 0.6,
              f"{vis_h['visible']}/{vis_h['total']}, 台账 {vis_h['hidden']}")

        # 合并机械臂聚焦: 地轨+机械臂一起保实体
        goto(page, "scenario=showcase&focus=ROBOT&freezetime=2.5&intro=0&panel=0")
        vis_r = page.evaluate("() => window.__fx.api.debugVisibility()")
        check("机械臂·地轨合并聚焦成立", vis_r["selected"] == "ROBOT" and vis_r["selectedMeshes"] > 40
              and vis_r["selectedSolid"], f"组网格 {vis_r['selectedMeshes']}")

        # -- 9. 开场扫场: 门控/中止还原/播完无泄漏 ---------------------------------------
        errors = goto(page, "scenario=showcase&intro=0&panel=0")
        page.wait_for_function("() => window.__fx.api.stats().bvhReady", timeout=60_000)
        page.evaluate("() => window.__fx.api.playIntro()")
        page.wait_for_timeout(300)
        mid = page.evaluate(
            "() => ({ running: window.__fx.api.introRunning(), vis: window.__fx.api.debugVisibility() })")
        page.evaluate("() => window.__fx.api.focus('DEVELOP')")  # 门控下应被忽略且不投毒
        page.wait_for_timeout(150)
        gated = page.evaluate(
            "() => ({ running: window.__fx.api.introRunning(), vis: window.__fx.api.debugVisibility() })")
        check("扫场中输入被门控(focus 无效且台账零)",
              mid["running"] and gated["running"] and gated["vis"]["ghosted"] == 0 and gated["vis"]["selected"] is None,
              f"running={gated['running']} ghosted={gated['vis']['ghosted']}")
        page.evaluate("() => window.__fx.api.abortIntro()")
        page.wait_for_timeout(200)
        aborted = page.evaluate("() => ({ running: window.__fx.api.introRunning(), vis: window.__fx.api.debugVisibility() })")
        check("中止扫场即全量还原", not aborted["running"] and aborted["vis"]["visible"] == aborted["vis"]["total"], "")
        page.evaluate("() => window.__fx.api.playIntro()")
        page.wait_for_timeout(3800)
        done = page.evaluate("() => window.__fx.api.introRunning()")
        page.evaluate("() => window.__fx.api.focus('DEVELOP')")
        page.wait_for_timeout(200)
        after = page.evaluate("() => window.__fx.api.debugVisibility()")
        page.evaluate("() => window.__fx.api.blur()")
        check("扫场播完无幽灵泄漏(聚焦仍实体)",
              (not done) and after["selectedSolid"] and after["visible"] == after["total"],
              f"done={not done} solid={after['selectedSolid']}")

        # -- 10. 开关门 -----------------------------------------------------------------
        doors0 = page.evaluate("() => window.__fx.api.doorStates()")
        # 少一扇 = fxConfig 的节点路径没命中(doors.js 只 console.warn 不抛), 这条是唯一的网
        check("八扇门全部解析成功", all(d["found"] for d in doors0.values()) and len(doors0) == 8,
              str({k: d["found"] for k, d in doors0.items()}))
        page.evaluate("() => window.__fx.api.toggleDoor('sideL1')")
        page.evaluate("() => window.__fx.api.toggleDoor('feed')")
        page.wait_for_timeout(1400)
        opened = page.evaluate("() => window.__fx.api.doorStates()")
        check("开门动画到位(sideL1/feed t=1)",
              opened["sideL1"]["t"] == 1 and opened["feed"]["t"] == 1, str(opened))
        # 对开门连动: 只点一扇, 配对那扇必须跟着走(只写单侧 pair 会退化成半错状态)
        check("对开门连动开(点 sideL1 带上 sideL2)", opened["sideL2"]["t"] == 1, str(opened["sideL2"]))
        page.evaluate("() => window.__fx.api.toggleDoor('frontL1')")
        page.wait_for_timeout(1400)
        paired = page.evaluate("() => window.__fx.api.doorStates()")
        check("前面对开门连动(点 frontL1 两扇同开)",
              paired["frontL1"]["t"] == 1 and paired["frontL2"]["t"] == 1,
              str({k: paired[k] for k in ("frontL1", "frontL2")}))
        page.evaluate("() => window.__fx.api.toggleDoor('frontL2')")  # 再点另一扇 -> 两扇同关
        page.wait_for_timeout(1400)
        paired2 = page.evaluate("() => window.__fx.api.doorStates()")
        check("前面对开门连动关(点 frontL2 两扇同关)",
              paired2["frontL1"]["t"] == 0 and paired2["frontL2"]["t"] == 0,
              str({k: paired2[k] for k in ("frontL1", "frontL2")}))
        # 开门态下聚焦/退出: 枢轴重挂不得扰乱隔离台账
        page.evaluate("() => window.__fx.api.focus('DEVELOP')")
        page.wait_for_timeout(250)
        page.evaluate("() => window.__fx.api.blur()")
        page.wait_for_timeout(250)
        vis_d = page.evaluate("() => window.__fx.api.debugVisibility()")
        check("开门态聚焦退出后台账清零", vis_d["ghosted"] == 0 and vis_d["hidden"] == 0, "")
        page.evaluate("() => window.__fx.api.setDoor('sideL1', false)")
        page.evaluate("() => window.__fx.api.setDoor('feed', false)")
        page.wait_for_timeout(1400)
        closed = page.evaluate("() => window.__fx.api.doorStates()")
        check("关门动画归零", closed["sideL1"]["t"] == 0 and closed["feed"]["t"] == 0, str(closed))
        errors = page.evaluate("() => window.__fx.errors")
        check("开场/门交互页无 JS 错误", not errors, str(errors))

        # -- 11. 流程片段播放 -----------------------------------------------------------
        errors = goto(page, "clip=flow.sampling_execute&clipt=3&intro=0&panel=0")
        check("片段页无 JS 错误", not errors, str(errors))
        status = page.evaluate("() => window.__fx.api.clipStatus()")
        check("片段载入并定格在 3s",
              status["active"] and status["duration"] > 5 and abs(status["time"] - 3) < 0.05
              and bool(status["stepLabel"]) and bool(status["station"]),
              f"time={status['time']:.2f}/{status['duration']:.1f}s 步[{status['stepLabel']}] 工位={status['station']}")
        page.evaluate("() => window.__fx.api.clipToggle()")
        page.wait_for_timeout(900)
        status2 = page.evaluate("() => window.__fx.api.clipStatus()")
        check("播放在推进", status2["playing"] and status2["time"] > status["time"] + 0.4,
              f"{status['time']:.2f}s -> {status2['time']:.2f}s")
        page.evaluate("() => window.__fx.api.clipExit()")
        status3 = page.evaluate("() => window.__fx.api.clipStatus()")
        errors = page.evaluate("() => window.__fx.errors")
        check("退出片段模式干净", (not status3["active"]) and not errors, str(errors))

        browser.close()

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
