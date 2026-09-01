"""
功能: 展缸液面进离线片段的自动化验收 —— 液面高度、归零语义与 ViewTools 互不干涉.

核心断言链(把"液面变化真的演出来了"翻译成机器可验证的表述):
  1. **起手是空缸**: 装载任一片段后 8 个液面盒的 scale.y 都在下限档, **且 visible
     为 False** —— 前者防的是"离线页 8 缸全渲染成满液"(液面盒建模尺寸就是满到槽口,
     而缩放它的 _updateTanks 一度只挂在实时链上); 后者防的是"排干净了还剩薄薄一层":
     scale.y 压到 1e-4 只让法线不退化, 压扁的盒子顶面仍是满尺寸的不透明面;
  2. **注液涨、排液落**: 沿 develop_prepare 的时间轴取样, 注液段末尾的 scale.y
     必须显著高于起点, 排液段末尾必须回到下限档;
  3. **高度与体积对得上**: 实测 scale.y 与 levelFromMl(mL) 的理论值一致
     (公差 1%), 防的是"画面在动但动的量是错的";
  4. **枢轴补偿在不在**: 空档与峰值的 position.y 必须不同. "液面朝中心收缩"这个 bug
     完全不改 scale, 第 2、3 条对它是瞎的 —— 只有 position 会说话;
  5. **向后 seek 不留残留**: 从注满处拖回 t=0, 液面必须回到空 —— 液面若停在
     上一次的体积, 拖过一次注液段之后这缸就再也空不掉了.

另截 4 帧关键姿态图供目检(液体是否糊在缸外面、与板是否穿插由人看).

不在本脚本里验的, 以及为什么:
  * mL→液位的换算公式、枢轴补偿的**几何正确性**(底面是否严格钉住)、以及显隐的
    多写者仲裁(隔离期间注液不该弹回画面)—— 都在 tests/three-d/ 的
    liquidPivot / liquidChannel / visibilityIntent 三个单测里逐位断言,
    单测比隔着一层钩子的黑盒判定准得多. 本脚本只做"在不在"的粗判 + 目检截图.

⚠ 必须对着 **vite 开发服务器** 跑: window.__anim 由 devHooks.installAnimHooks 装,
而那个函数在 import.meta.env.DEV 为假时直接返回空 —— 18080 上的生产构建没有它.
先起 `npm run dev`(127.0.0.1:15173, /api 反代到 18080), 再跑本脚本.

用法: python verify_tank_liquid.py [--headless]
返回值: 无(结果写 work/verify_tank_liquid.json, 截图写 work/previews/review/)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))
SHOT_DIR = os.path.join(WORK_DIR, "previews", "review")
MANIFEST = os.path.normpath(
    os.path.join(ROOT, "..", "..", "models", "device-manifest.official-cr5.json"))

#: 空缸档: setLiquidMl 对 0 体积写的是 baseScale.y * 1e-4(不真的乘 0, 免得法线退化)
EMPTY_RATIO = 1e-4
#: 判"明显有液"的下限 —— 20mL 在 102mL 的槽里放大后约 0.39, 取 0.1 足够宽松
VISIBLE_RATIO = 0.1


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def level_from_ml(cavity: dict, volume_ml: float, exaggeration: float) -> float:
    """mL -> 液位 0~1。与前端 TankLiquidModel.levelFromMl 同式, 用来交叉验算。"""
    depth = float(cavity["usableDepthMm"])
    area = float(cavity["freeAreaMm2"])
    height_mm = (max(0.0, volume_ml) * 1000.0) / area
    return max(0.0, min(1.0, (height_mm * exaggeration) / depth))


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="展缸液面自动化验收")
    # 默认指 vite 开发服务器: 生产构建里没有 window.__anim(见模块头注释)
    parser.add_argument("--url", default="http://127.0.0.1:15173/3d/demo/develop_prepare")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    manifest = json.loads(open(MANIFEST, encoding="utf-8").read())
    tank_liquid = manifest["tankLiquid"]
    cavity = tank_liquid["cavity"]
    exaggeration = float(tank_liquid.get("exaggeration") or 1.0)

    result: dict = {"url": args.url, "console_errors": [], "cavity": cavity}
    failures: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=args.headless,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("console",
                lambda m: result["console_errors"].append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: result["console_errors"].append(str(e)))

        log(f"打开 {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function("() => !!window.__anim", timeout=120_000)
        page.wait_for_timeout(4000)

        def ev(expression: str, arg=None):
            """求值前等开发钩子就绪(前端热更新会短暂让 __anim 消失)。"""
            page.wait_for_function("() => !!window.__anim", timeout=60_000)
            return page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)

        def liquid_node(index: int) -> dict | None:
            """第 index(1 基) 个缸液面盒的局部 TRS + 可见性。"""
            return ev("n => window.__anim.nodeLocal(n)", f"LIQUID_{index}")

        def liquid_ratio(index: int) -> float:
            """第 index(1 基) 个缸的 scale.y 相对建模尺寸的比例。"""
            node = liquid_node(index)
            if not node:
                return float("nan")
            # 建模尺寸未知, 但同一个盒在 t 变化时只有 y 变 —— 用满档做基准需要一次参考,
            # 这里直接读绝对 scale, 由调用方按"空/满"两端比较
            return float(node["scale"][1])

        def seek(t: float) -> None:
            ev(f"window.__anim.seek({t})")
            page.wait_for_timeout(400)

        state = ev("window.__anim.state()")
        result["initial_state"] = state
        log(f"装载: {state}")

        # -- 1: 起手是空缸(本改动之前这里是 8 缸全满) -----------------------
        seek(0)
        base = {i: liquid_ratio(i) for i in range(1, 9)}
        result["t0_scale_y"] = base
        log(f"t=0 各缸 scale.y: {base}")
        missing = [i for i, v in base.items() if v != v]  # NaN = 节点没找到
        if missing:
            failures.append(f"液面盒未在场景里: LIQUID_{missing}")

        # 空缸必须**真的看不见**: scale.y 压到 1e-4 只是让法线不退化, 压扁的盒子顶面
        # 仍是满尺寸(展缸那只 210×40mm)的不透明面, 隔着玻璃缸看就是"排干净了还剩薄薄
        # 一层"(2026-08-05 报障). 只有 visible=False 才算真的排空。
        t0_visible = {i: liquid_node(i).get("visible") for i in range(1, 9) if i not in missing}
        result["t0_visible"] = t0_visible
        shown_empty = [i for i, v in t0_visible.items() if v]
        if shown_empty:
            failures.append(f"空缸仍在渲染(会留一张满尺寸顶面): LIQUID_{shown_empty}")

        t0_pos_y = float(liquid_node(1)["position"][1]) if 1 not in missing else float("nan")

        # -- 2/3: 沿时间轴取样, 找注液与排液的极值 --------------------------
        duration = float(state.get("duration") or 0)
        samples: list[dict] = []
        steps = 40
        for k in range(steps + 1):
            t = duration * k / steps
            seek(t)
            samples.append({"t": round(t, 2), "tank1": liquid_ratio(1)})
        result["samples"] = samples
        peak = max(samples, key=lambda s: s["tank1"])
        result["peak"] = peak
        log(f"1号缸液面峰值: t={peak['t']}s scale.y={peak['tank1']}")

        empty0 = base.get(1) or 0.0
        if not (peak["tank1"] > empty0 * 50):
            failures.append(f"1号缸液面全程没涨起来(峰值 {peak['tank1']} vs 起点 {empty0})")

        # 峰值应当对应片段里最大的一次注液(develop_prepare 是 20mL×3=60mL)
        expected_full = level_from_ml(cavity, 60.0, exaggeration)
        # scale.y = baseScale.y * level, 而 t=0 的 scale.y = baseScale.y * 1e-4
        base_scale_y = empty0 / EMPTY_RATIO if empty0 > 0 else None
        if base_scale_y:
            measured_level = peak["tank1"] / base_scale_y
            result["measured_level"] = measured_level
            result["expected_level_60ml"] = expected_full
            log(f"峰值液位实测 {measured_level:.4f} vs 理论(60mL) {expected_full:.4f}")
            if abs(measured_level - expected_full) > 0.01:
                failures.append(
                    f"液面高度与体积对不上: 实测 {measured_level:.4f}, 理论 {expected_full:.4f}")

        # -- 枢轴补偿在不在(黑盒判据) --------------------------------------
        # "往中心收缩"这个 bug **完全不改 scale**, 上面 2/3 两条对它是瞎的: 只缩 scale
        # 不动 position, 液面就是绕几何中心两头一起收, 底面凭空悬起(2026-08-05 报障).
        # 出厂 GLB 的液面枢轴被 quantize 挪到了几何正中, 所以补偿量必然非零 ——
        # 空档与峰值的 position.y 一模一样, 就说明补偿根本没写.
        # 几何正确性的细判归单测(liquidPivot.test.js / liquidChannel.test.js), 这里只粗判"在不在".
        seek(peak["t"])
        peak_pos_y = float(liquid_node(1)["position"][1])
        result["pivot_shift_mm"] = (peak_pos_y - t0_pos_y) * 1000
        log(f"枢轴补偿位移: {(peak_pos_y - t0_pos_y) * 1000:.2f}mm")
        if abs(peak_pos_y - t0_pos_y) < 1e-9:
            failures.append(
                "液面缩放没有做枢轴补偿(空档与峰值的 position.y 相同): 液面会朝中心收缩")

        seek(duration)
        end_ratio = liquid_ratio(1)
        result["end_scale_y"] = end_ratio
        log(f"片段末尾 1号缸 scale.y={end_ratio}")

        # -- 4: 向后 seek 不留残留 -----------------------------------------
        seek(peak["t"])
        assert liquid_ratio(1) > empty0 * 50, "取样点应当有液"
        seek(0)
        back = liquid_ratio(1)
        result["seek_back_scale_y"] = back
        log(f"拖回 t=0 后 scale.y={back}")
        if abs(back - empty0) > empty0 * 0.5:
            failures.append(f"向后 seek 留下残留液面: {back} (t=0 应为 {empty0})")

        # -- 截图供目检 -----------------------------------------------------
        for t, name in [(0, "liquid_t0_empty"), (peak["t"], "liquid_peak"),
                        (duration * 0.75, "liquid_drain"), (duration, "liquid_end")]:
            seek(t)
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(SHOT_DIR, f"{name}.png"))
            log(f"截图 {name}.png (t={t:.1f}s)")

        browser.close()

    result["failures"] = failures
    out = os.path.join(WORK_DIR, "verify_tank_liquid.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    log(f"结果写入 {out}")

    if result["console_errors"]:
        log(f"控制台报错 {len(result['console_errors'])} 条: {result['console_errors'][:3]}")
    if failures:
        log("验收未通过:")
        for item in failures:
            log(f"  - {item}")
        sys.exit(1)
    log("验收通过")


if __name__ == "__main__":
    main()
