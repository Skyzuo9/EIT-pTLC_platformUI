"""一次性探针: 在真场景里量吸盘柔性接触的压缩量与每帧开销。

不是门禁 —— 门禁是 verify_plate_suction.py。这个只回答两个问题:
  1. 真实示教点上, 各落点实际需要压缩多少(判断 6.0mm 行程够不够);
  2. 接触判据每帧多花多少时间(判断要不要按计划降级)。
"""
from __future__ import annotations

import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "http://localhost:15173/3d/demo/{flow}"
FLOWS = ("sampling_load", "sampling_unload", "photoscrape_plate_load", "develop_load")


def main() -> int:
    from playwright.sync_api import sync_playwright

    report: dict = {"flows": {}}
    contact_time = 0.0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda e: print("PAGEERROR:", e))

        for flow in FLOWS:
            page.goto(URL.format(flow=flow), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_function("() => !!window.__anim", timeout=240_000)
            page.wait_for_function("() => (window.__anim.state()?.duration||0) > 0", timeout=240_000)
            page.wait_for_timeout(4000)
            duration = float(page.evaluate("window.__anim.state().duration"))

            samples = []
            steps = 90
            for i in range(steps + 1):
                t = duration * i / steps
                page.evaluate(f"window.__anim.seek({t})")
                status = page.evaluate("window.__anim.plates()")
                contact = (status or {}).get("contact")
                if contact and contact.get("penetrationM", 0) > 1e-6:
                    samples.append({
                        "t": round(t, 2),
                        "penetrationMm": round(contact["penetrationM"] * 1000, 3),
                        "compressionMm": round(contact["compressionM"] * 1000, 3),
                        "overshootMm": round(contact["overshootM"] * 1000, 3),
                        "hit": contact.get("hit", ""),
                    })
            report["flows"][flow] = {
                "durationS": round(duration, 2),
                "contactSamples": len(samples),
                "maxPenetrationMm": max((s["penetrationMm"] for s in samples), default=0.0),
                "maxOvershootMm": max((s["overshootMm"] for s in samples), default=0.0),
                "samples": samples[:12],
            }
            hits = sorted({s["hit"] for s in samples if s["hit"]})
            report["flows"][flow]["hitObjects"] = hits
            print(f"{flow}: 接触 {len(samples)}/{steps + 1} 档, "
                  f"最深穿透 {report['flows'][flow]['maxPenetrationMm']}mm, "
                  f"最大超行程 {report['flows'][flow]['maxOvershootMm']}mm"
                  f"{('; 顶在 ' + ', '.join(hits)) if hits else ''}")
            if samples:
                contact_time = max(samples, key=lambda s: s["penetrationMm"])["t"]

        # -- 每帧开销: 必须在**真有接触**的那一刻测, 否则 update() 提前返回, 测出来是假的快
        page.evaluate(f"window.__anim.seek({contact_time})")
        page.wait_for_timeout(500)
        timing = page.evaluate(
            """() => {
              const run = (n) => {
                const t0 = performance.now()
                for (let i = 0; i < n; i += 1) window.__anim.plateContactTick?.()
                return (performance.now() - t0) / n
              }
              run(20)                       // 预热(BVH 首次下降 / JIT)
              return { msPerCall: run(200) }
            }"""
        )
        report["timing"] = timing
        print(f"接触判据每帧 {timing.get('msPerCall')} ms")
        browser.close()

    print()
    print(json.dumps(report, ensure_ascii=False, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
