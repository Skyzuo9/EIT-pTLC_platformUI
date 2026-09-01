"""
功能: 板面痕迹(点样色带/展开润湿)的演示页截图验收 —— 板在场、色带渐现、润湿上行.

轻量拍片脚本(照 verify_scrape_band.py 的驱动方式, 不做像素断言 —— 几何换算的正确性
已由 tests/three-d/{scrapeOverlay,spotChannel,wetChannel}.test.js 逐位钉死, 这里出
截图供人眼核对两件事: ①色带两端与喷头扫线端点是否同位(SPOT_BAND_CALIB 锚对没对);
②缸内润湿是否从下沿向上、前沿线可读):
  1. flow.sampling_execute: 起手(板在点样座) / 扫线中程(色带长了一半) / 终态(整条带);
  2. flow.develop_execute.tank1: 前沿上行中程 / 终态(排液后前沿界线仍在)。

⚠ 必须对 vite 开发服务器跑(window.__anim 仅 DEV): 先 `npm run dev`(127.0.0.1:15173)。

用法: python shot_plate_traces.py [--headless]
产物: work/previews/review/trace_*.png + work/shot_plate_traces.json
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))
SHOT_DIR = os.path.join(WORK_DIR, "previews", "review")
CLIP_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "clips"))


def clip_band_center_cm(clip_name: str) -> float | None:
    """读编译产物 spotRegions 的首条带, 返回带中心 y_cm(同线断言的"带"侧真源)。"""
    with io.open(os.path.join(CLIP_DIR, f"{clip_name}.yaml"), encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    bands = (((doc.get("compiled") or {}).get("spotRegions") or {}).get("plate") or {}).get("bands") or []
    if not bands:
        return None
    box = bands[0].get("bandCm") or []
    return (float(box[1]) + float(box[3])) / 2 if len(box) == 4 else None


def clip_steps(clip_name: str) -> tuple[list[dict], float]:
    """读编译产物, 按前端 compileClip 的 at/dur 光标规则算各步区间与总时长。"""
    with io.open(os.path.join(CLIP_DIR, f"{clip_name}.yaml"), encoding="utf-8") as handle:
        doc = yaml.safe_load(handle)
    cursor = 0.0
    out = []
    duration = 0.0
    for step in doc.get("steps") or []:
        at = float(step.get("at", cursor))
        dur = float(step.get("dur", 0.0))
        out.append({"label": str(step.get("label", "")), "at": at, "dur": dur})
        cursor = at + dur
        duration = max(duration, cursor)
    return out, duration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--base", default="http://127.0.0.1:15173/3d/demo")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    report: dict = {"shots": [], "issues": []}

    def note(issue: str) -> None:
        report["issues"].append(issue)
        print(f"  ⚠ {issue}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=args.headless)
        page = browser.new_page(viewport={"width": 1600, "height": 900})

        def ev(expr, arg=None):
            return page.evaluate(expr, arg) if arg is not None else page.evaluate(expr)

        def load(url: str) -> None:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_function("() => !!window.__anim", timeout=120_000)
            # 片段装载完(transport 报出时长)再动
            page.wait_for_function("() => (window.__anim.state()?.duration || 0) > 0",
                                   timeout=120_000)
            time.sleep(1.2)

        def face_view(view_label: str) -> None:
            """点工具栏机位钮定朝向(frame 只调距离不调朝向, 板面截图必须先摆对朝向)。

            直接在 DOM 里找**可见的**同文本按钮点(offsetParent 非空 = 没被藏), 绕开
            locator 的可见性等待 —— 页面别处存在同字的隐藏节点时 .first 会永远等下去。
            """
            hit = ev(
                "label => { const btn = [...document.querySelectorAll('button')]"
                ".find(b => b.textContent.trim() === label && b.offsetParent); "
                "if (btn) { btn.click(); return true } return false }",
                view_label,
            )
            if not hit:
                note(f"工具栏找不到可见按钮: {view_label}")
            time.sleep(0.5)

        def shot(name: str, frame_node: str | None = None, view: str | None = None) -> None:
            if view:
                face_view(view)
            if frame_node:
                ev("n => window.__anim.frame(n, 0.45)", frame_node)
                time.sleep(0.4)
            path = os.path.join(SHOT_DIR, f"{name}.png")
            page.screenshot(path=path)
            report["shots"].append(path)
            print(f"  📷 {name}")

        def seek(t: float) -> None:
            ev(f"window.__anim.seek({max(0.0, t)})")
            time.sleep(0.6)

        def mid_of(steps: list[dict], fragment: str) -> float:
            for step in steps:
                if fragment in step["label"]:
                    return step["at"] + step["dur"] / 2
            note(f"片段里找不到步: {fragment}")
            return -1.0

        # ── 上样-执行: 板 + 色带 ────────────────────────────────────────────
        print("[1/2] flow.sampling_execute")
        steps, duration = clip_steps("flow.sampling_execute")
        load(f"{args.base}/sampling_execute")
        seek(0.2)
        rows = (ev("window.__anim.plates()") or {}).get("rows") or []
        if not any(row.get("slot") == "spot_seat" for row in rows):
            note(f"起手板不在点样座: {rows}")
        report["sampling_rows_t0"] = rows
        shot("trace_spot_t0_seed", "玻璃-1", view="顶")
        mid = mid_of(steps, "色带渐现")
        if mid > 0:
            seek(mid)
            traces = (ev("window.__anim.plates()") or {}).get("traces") or []
            report["spot_mid_traces"] = traces
            fills = (traces[0].get("spotFills") or [0]) if traces else [0]
            if not (0.15 < fills[0] < 0.95):
                note(f"扫线中程色带填充不在中段: {fills}")
            # 色带线必须与喷嘴尖同线(SPOT_BAND_CALIB 的在景自洽判据): worldBox 量喷嘴尖
            # 轴线, 转板局部横向, 与片段 spotRegions 声明的带中心比, 差 >2mm 即标定漂了。
            box = ev("n => window.__anim.worldBox(n)", "喷射头-1")
            plate = ev("p => window.__anim.plateWorld(p)", "plate")
            band = clip_band_center_cm("flow.sampling_execute")
            if box and plate and band is not None:
                tip = [(box["min"][0] + box["max"][0]) / 2,
                       (box["min"][2] + box["max"][2]) / 2]
                # 板 quat=[0,±1,0,0](绕 Y 180°): 世界Δ → 板局部 = (−Δx, −Δz)
                qy = plate["quaternion"][1]
                if abs(abs(qy) - 1.0) > 1e-3:
                    note(f"板姿态非绕Y整转, 简式局部换算不适用: {plate['quaternion']}")
                else:
                    local_x = -(tip[0] - plate["position"][0])
                    nozzle_y_cm = (local_x + 0.1) * 100
                    offset_mm = abs(nozzle_y_cm - band) * 10
                    report["band_vs_nozzle_mm"] = round(offset_mm, 2)
                    if offset_mm > 2.0:
                        note(f"色带线偏离喷嘴尖 {offset_mm:.1f}mm(>2mm): "
                             f"喷嘴 y_cm={nozzle_y_cm:.2f}, 带中心={band:.2f}")
            else:
                note("喷嘴/板/带几何取不到, 同线断言未执行")
            shot("trace_spot_mid_sweep", "玻璃-1", view="顶")
        # 近景: 前视紧框板锚点 —— 喷嘴与色带同框, 供人眼核对"同线"(与自动断言互证)
        face_view("前")
        ev("n => window.__anim.frame(n, 0.3)", "玻璃-1")
        time.sleep(0.4)
        shot("trace_spot_mid_closeup")
        seek(duration - 0.1)
        traces = (ev("window.__anim.plates()") or {}).get("traces") or []
        report["spot_full_traces"] = traces
        if not (traces and (traces[0].get("spotFills") or [0])[0] >= 0.999):
            note(f"终态色带未满: {traces}")
        shot("trace_spot_full", "玻璃-1", view="顶")
        # 向后 seek 复位: 色带不留记忆
        seek(0)
        traces = (ev("window.__anim.plates()") or {}).get("traces") or []
        if traces:
            note(f"seek(0) 后痕迹未复位: {traces}")
        shot("trace_spot_seek0", "玻璃-1", view="顶")

        # ── 展开-执行: 缸内润湿 ────────────────────────────────────────────
        print("[2/2] flow.develop_execute.tank1")
        steps, duration = clip_steps("flow.develop_execute.tank1")
        load(f"{args.base}/develop_execute")
        face_view("透视")  # 缸有盖有壳, 不透视看不到板 —— 与人工核对时的用法一致
        mid = mid_of(steps, "溶剂前沿上行")
        if mid > 0:
            seek(mid)
            traces = (ev("window.__anim.plates()") or {}).get("traces") or []
            report["wet_mid_traces"] = traces
            front = traces[0].get("wetFront") if traces else None
            if front is None or not (0.15 < front < 0.95):
                note(f"前沿上行中程不在中段: {traces}")
            shot("trace_wet_mid_rise", "玻璃-1.010", view="前")
        seek(duration - 0.1)
        traces = (ev("window.__anim.plates()") or {}).get("traces") or []
        report["wet_final_traces"] = traces
        if not (traces and (traces[0].get("wetFront") or 0) >= 0.999):
            note(f"终态前沿未到位(排液后界线应保持): {traces}")
        shot("trace_wet_final", "玻璃-1.010", view="前")

        browser.close()

    out = os.path.join(WORK_DIR, "shot_plate_traces.json")
    with io.open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"报告: {out}; issues: {len(report['issues'])}")


if __name__ == "__main__":
    main()
