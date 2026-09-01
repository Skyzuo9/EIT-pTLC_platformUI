"""持板期间的**全向**相交扫描: 板在轨迹中间有没有扎进/扫过任何静止件。

为什么要有它(2026-08-06 的教训, 值得原样记着):
    此前"板穿模"这类问题只有三个量看着, 而三个都结构性看不见轨迹中间的横向相交:
      · 前端 plateContact 只沿**吸盘轴**打 5 条射线 —— 板横着扫进料仓侧壁时它恒返回 0;
      · verify_plate_clearance 只扫**静止**板随料仓轴升降, 不看被吸盘持着的板;
      · verify_plate_seats / diagnose_plate_grip 只看**示教点**上的残差, 不看中间。
    于是"取板帧面内偏移 = 0"验收全绿, 而用户看到的穿模发生在 0.1s 之后板横扫过侧壁那一档。
    **判据量错了, 修法再对也白搭** —— 本脚本就是补上那个量。

深度口径见 PlateContact.overlap / blender_plate_clearance.slice_intrusion(同一套代数):
取静止三角形与板中面的交线, 量它伸进板轮廓内最深多少。

⚠ 开发钩子 window.__anim 只在 **dev 构建**(15173)存在, 打 18080 会一直等不到。

用法:
    python probe_plate_overlap.py                       # 默认扫几条带取放板的流程
    python probe_plate_overlap.py --flow sampling_load --from 17 --to 22 --step 0.05
    python probe_plate_overlap.py --flow plate.feed_pick --tol 1.0
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.normpath(os.path.join(ROOT, "..", "..", "work"))

#: 默认扫这几条 —— 都真的走了"料仓取板 / 放板"这条路。
DEFAULT_FLOWS = ("sampling_load", "plate.feed_pick", "develop_load")

#: 判红阈值(mm)。1.0 与 verify_plate_clearance.MAX_PENETRATION_MM 同一口径:
#: 擦边实测只有零点几毫米, 真扎进去是毫米到厘米级, 1.0 落在两者中间。
DEFAULT_TOL_MM = 1.0

READ = """
() => {
  const a = window.__anim
  const o = a.plateOverlap()
  const p = a.plates()
  const local = a.plateLocal('plate')
  return {
    overlap: o,
    carried: (p.rows || []).some(r => r.slot === 'carried'),
    seatHold: p.seatHold || null,
    axialMm: (p.contact?.penetrationM || 0) * 1000,
    parent: local ? local.parent : '',
  }
}
"""


def scan(page, flow: str, t0: float, t1: float, step: float) -> list[dict]:
    url = f"http://127.0.0.1:15173/3d/demo/{flow}"
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => !!window.__anim", timeout=240_000)
    page.wait_for_function("() => (window.__anim.state()?.duration||0) > 0", timeout=240_000)
    page.wait_for_timeout(4000)
    duration = float(page.evaluate("window.__anim.state().duration"))
    start = 0.0 if t0 is None else t0
    end = duration if t1 is None else min(t1, duration)
    print(f"\n=== {flow}  全长 {duration:.2f}s, 扫 {start:.2f}~{end:.2f}s 步长 {step:.3f}s ===")

    rows = []
    t = start
    while t <= end + 1e-9:
        page.evaluate(f"window.__anim.seek({t})")
        data = page.evaluate(READ)
        if data and data.get("carried"):
            overlap = data.get("overlap") or {}
            rows.append({
                "t": round(t, 3),
                "maxDepthMm": round(float(overlap.get("maxDepthMm") or 0), 3),
                "hits": [{"name": h["name"], "depthMm": round(float(h["depthMm"]), 3)}
                         for h in (overlap.get("hits") or [])],
                "axialMm": round(float(data.get("axialMm") or 0), 3),
                "seatHold": data.get("seatHold"),
            })
        t += step
    return rows


def report(flow: str, rows: list[dict], tol: float) -> int:
    bad = [row for row in rows if row["maxDepthMm"] > tol]
    print(f"  持板档位 {len(rows)} 个; 超 {tol:.1f}mm 的 {len(bad)} 个")
    for row in bad:
        names = ", ".join(f"{h['name']}({h['depthMm']:.2f}mm)" for h in row["hits"][:3])
        hold = row["seatHold"]
        held = (f" [落点保持 {hold['slot']} w={hold['weight']:.3f}]") if hold else ""
        print(f"    t={row['t']:6.2f}s  最深 {row['maxDepthMm']:7.2f}mm  {names}{held}")
    if not bad:
        deepest = max((row["maxDepthMm"] for row in rows), default=0.0)
        print(f"  [ok] 全程无超限相交(最深 {deepest:.2f}mm)")
    return len(bad)


def main() -> int:
    parser = argparse.ArgumentParser(description="持板全向相交扫描(只读)")
    parser.add_argument("--flow", action="append", help="流程名或片段名; 可重复")
    parser.add_argument("--from", dest="t0", type=float, default=None)
    parser.add_argument("--to", dest="t1", type=float, default=None)
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--tol", type=float, default=DEFAULT_TOL_MM)
    args = parser.parse_args()
    flows = args.flow or list(DEFAULT_FLOWS)

    from playwright.sync_api import sync_playwright

    out: dict = {"tolMm": args.tol, "flows": {}}
    total_bad = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda e: print("PAGEERROR:", e))
        for flow in flows:
            rows = scan(page, flow, args.t0, args.t1, args.step)
            total_bad += report(flow, rows, args.tol)
            out["flows"][flow] = rows
        browser.close()

    os.makedirs(WORK_DIR, exist_ok=True)
    path = os.path.join(WORK_DIR, "plate_overlap.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    print(f"\n[{'ok' if not total_bad else '!!'}] 明细已写 {path}; 超限档位合计 {total_bad}")
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
