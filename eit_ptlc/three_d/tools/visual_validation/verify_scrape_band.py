"""
功能: 拍照刮板-执行 片段的条带刮取自动化验收 —— 板在场、粉桶可见、双前沿与轴同步、露玻璃像素、seek 复位.

断言链(把"刮取真的演出来了"翻译成机器可验证的表述):
  1. **起手态**: 板在 scrape_table(plates().rows), 粉桶(STA_SCRAPE_HOLDER=硅胶收集-1.008)
     可见 —— 此前该片段是"空台演出 + 空翻旋转气缸";
  2. **映射建立**: plates().scrape.uvBand 非空 —— cm→UV 映射解析失败时前端刻意留白不画
     (与"落点解析不到就不画"同一条纪律), 这里就该红;
  3. **前沿与轴同步**: loosen/clear 都单调不减; 刮松段内前沿与刮刀 9X 列位对得上
     (±0.35 = 1.5 列宽 + 冲程内斜坡), 收集段内前沿与粉桶位置(9X + bottle_x_offset)
     对得上(±0.15, 两边都是线性连续量) —— 编译器不取 emit_axis 实际时长时这条会红
     (max_s 钳制让 clear 比桶快一倍);
  4. **像素**: 收集结束后条带中心比未刮时显著变暗(硅胶粉没了露出下层玻璃);
     刮松中程条带起始侧比末端侧暗(刮松灰可见且前沿方向对);
  5. **向后 seek**: 拖回 t=0 后刮取状态清零、板唯一(seek = home 清场 + 重放的契约);
  6. **photoscrape_cycle 抽查**: t=0 不得有"板已在刮板台"的起手式、刮取状态必须为空 ——
     防 PHASE_ENTRY_STATE 被错误提前到含上料段的父流程。t=0 有 carried 的板是**合法的**
     (它内联的板上料段自己声明"板起手时已在机器人手上", plate.flow.photoscrape_load 同款)。

像素判据带**在屏守卫**(three-d 像素验收的第一类假信号是"取景没落位"): 相机先经工具栏
「顶」按钮定朝向(frame 走 fitToBox, 只调距离不调朝向), 再框住刮板台锚点; 随后把条带
两端点投到屏幕上, 跨度不足或出视口就显式报"取景没落位"并跳过像素断言 —— 宁可红得明白,
也不拿采在无关几何上的亮度下结论。

几何换算的**正确性**(machineDirsWorld 的 8Y 取反、bandToUv 四朝向、scrapeRects 前沿代数)
全部在 tests/three-d/scrapeOverlay.test.js 逐位断言 —— 本脚本只验"接在真实模型上仍成立"。

⚠ 必须对 **vite 开发服务器** 跑(window.__anim 仅 DEV, 理由见 verify_tank_liquid.py 头注)。
先起 `npm run dev`(127.0.0.1:15173, /api 反代 18080), 再跑本脚本。

用法: python verify_scrape_band.py [--headless]
返回值: 无(结果写 work/verify_scrape_band.json, 截图写 work/previews/review/scrape_*.png)
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
CLIP = os.path.normpath(os.path.join(ROOT, "..", "..", "clips", "flow.photoscrape_process.yaml"))
APP_YAML = os.path.normpath(os.path.join(ROOT, "..", "..", "..", "config", "app.yaml"))

#: 粉桶 GLB 叶名(rig_map station_seats: STA_SCRAPE_HOLDER)
HOLDER_NODE = "硅胶收集-1.008"
#: 板名义边长(米), 与前端 plateGeometry.PLATE_NOMINAL_M 同源
PLATE_M = 0.2

#: 刮松前沿容差: 半列(0.1) + 冲程内斜坡(0.2) + 列间重定位保持(0.05)
LOOSEN_TOL = 0.35
#: 收集前沿容差: 两边都是线性连续量, 只剩采样相位差
CLEAR_TOL = 0.15


def log(message: str) -> None:
    """功能: 带时间戳打印. 参数: message. 返回值: None"""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def quat_apply(quaternion: list, vector: tuple) -> tuple:
    """功能: 四元数(xyzw)旋转一个向量 —— 免拉 scipy, 公式即 three 的 applyQuaternion.

    Args:
        quaternion: [x, y, z, w]
        vector: (x, y, z)
    Returns:
        旋转后的 (x, y, z)
    """
    qx, qy, qz, qw = quaternion
    vx, vy, vz = vector
    # t = 2 q × v; v' = v + w t + q × t
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return (
        vx + qw * tx + (qy * tz - qz * ty),
        vy + qw * ty + (qz * tx - qx * tz),
        vz + qw * tz + (qx * ty - qy * tx),
    )


def band_world_point(plate_pose: dict, uv_band: dict, front_frac: float) -> tuple:
    """功能: 把"条带内沿前沿方向 front_frac 处的中线点"换算成世界坐标.

    UV → 板局部用 BoxGeometry 顶面的固定映射(u=+x, v=−z, 与 scrapeOverlay.bandToUv
    的注释同源); 点取在板顶面上方 0.1mm 处, 只用于 screenOf 投影采像素。

    Args:
        plate_pose: __anim.plateWorld 的结果 {position, quaternion}
        uv_band: plates().scrape.uvBand
        front_frac: 0..1, 自前沿起点边起
    Returns:
        世界坐标 (x, y, z)
    """
    front = uv_band.get("loosen") or {"coord": "u", "dir": 1}
    coord = front.get("coord", "u")
    lo, hi = (uv_band["u0"], uv_band["u1"]) if coord == "u" else (uv_band["v0"], uv_band["v1"])
    start = lo if front.get("dir", 1) >= 0 else hi
    end = hi if front.get("dir", 1) >= 0 else lo
    along = start + (end - start) * front_frac
    if coord == "u":
        u, v = along, (uv_band["v0"] + uv_band["v1"]) / 2.0
    else:
        u, v = (uv_band["u0"] + uv_band["u1"]) / 2.0, along
    local = ((u - 0.5) * PLATE_M, 0.0016, (0.5 - v) * PLATE_M)
    rotated = quat_apply(plate_pose["quaternion"], local)
    position = plate_pose["position"]
    return (position[0] + rotated[0], position[1] + rotated[1], position[2] + rotated[2])


def brightness_at(image, xy: list, radius: int = 3) -> float:
    """功能: 截图上某客户端坐标周围 (2r+1)² 窗口的平均亮度(0..255)."""
    x0, y0 = int(round(xy[0])), int(round(xy[1]))
    width, height = image.size
    total, count = 0.0, 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = x0 + dx, y0 + dy
            if 0 <= x < width and 0 <= y < height:
                r, g, b = image.getpixel((x, y))[:3]
                total += (r + g + b) / 3.0
                count += 1
    return total / max(count, 1)


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="拍照刮板条带刮取自动化验收")
    parser.add_argument("--url", default="http://127.0.0.1:15173/3d/demo/photoscrape_process")
    parser.add_argument("--cycle-url", default="http://127.0.0.1:15173/3d/demo/photoscrape_cycle")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    from PIL import Image
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)

    clip = yaml.safe_load(open(CLIP, encoding="utf-8").read())
    region = (clip.get("compiled") or {}).get("scrapeRegions", {}).get("plate")
    if not region:
        log("片段里没有 compiled.scrapeRegions.plate —— 先跑 sync_ptlc_robot --flows --only flow.photoscrape_process")
        sys.exit(2)
    x0_cm, _y0, x1_cm, _y1 = region["bandCm"]
    span_cm = x1_cm - x0_cm

    gcode = (yaml.safe_load(open(APP_YAML, encoding="utf-8").read()) or {}).get("gcode") or {}
    origin_x = float(gcode["plate_origin_x"])
    bottle_offset = float((gcode.get("tool") or {})["bottle_x_offset_mm"])

    result: dict = {"url": args.url, "console_errors": [], "region": region}
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
            page.wait_for_function("() => !!window.__anim", timeout=60_000)
            return page.evaluate(expression, arg) if arg is not None else page.evaluate(expression)

        def seek(t: float, settle_ms: int = 0) -> None:
            ev(f"window.__anim.seek({t})")
            if settle_ms:
                page.wait_for_timeout(settle_ms)

        def scrape_status() -> dict:
            status = ev("window.__anim.plates()") or {}
            return status.get("scrape") or {"loosen": 0.0, "clear": 0.0, "uvBand": None}

        state = ev("window.__anim.state()")
        result["initial_state"] = state
        duration = float(state.get("duration") or 0)
        log(f"装载: {state.get('clip')} duration={duration:.1f}s")
        if duration < 30:
            failures.append(f"片段时长 {duration:.1f}s 太短 —— 刮取展开可能没编进去")

        # -- 1: 起手态 ------------------------------------------------------
        seek(0, settle_ms=300)
        rows = (ev("window.__anim.plates()") or {}).get("rows") or []
        result["t0_rows"] = rows
        if not any(row.get("plateId") == "plate" and row.get("slot") == "scrape_table" for row in rows):
            failures.append(f"t=0 板不在刮板台上: {rows}")
        holder = ev("n => window.__anim.nodeLocal(n)", HOLDER_NODE)
        result["t0_holder"] = holder
        if not holder:
            failures.append(f"粉桶节点 {HOLDER_NODE} 解析不到")
        elif not holder.get("visible"):
            failures.append("t=0 粉桶不可见 —— STA_SCRAPE_HOLDER 起手式没生效, 翻料倒粉又是空翻")

        # -- 2: 映射建立 ----------------------------------------------------
        uv_band = scrape_status().get("uvBand")
        result["uvBand"] = uv_band
        if not uv_band:
            failures.append("uvBand 为空 —— cm→UV 映射没建立(机床方向或板轴对不上, 前端留白了)")

        # -- 3: 采样时间轴, 验单调与轴同步 ----------------------------------
        samples: list[dict] = []
        steps = 80
        for k in range(steps + 1):
            t = duration * k / steps
            seek(t)
            status = scrape_status()
            samples.append({
                "t": round(t, 2),
                "loosen": round(float(status.get("loosen") or 0), 4),
                "clear": round(float(status.get("clear") or 0), 4),
                "axis9x": ev("window.__anim.axisValue('axis_9x')"),
            })
        result["samples"] = samples

        for key in ("loosen", "clear"):
            values = [s[key] for s in samples]
            drops = [i for i in range(1, len(values)) if values[i] < values[i - 1] - 1e-6]
            if drops:
                failures.append(f"{key} 前沿不单调(自然播放序内倒退): 样本 {drops[:4]}")
        if samples[-1]["clear"] < 0.999:
            failures.append(f"片段末尾 clear={samples[-1]['clear']} —— 收集段没把粉收尽")

        loosen_sync, clear_sync = [], []
        for sample in samples:
            axis = sample["axis9x"]
            if axis is None:
                continue
            if 0.05 < sample["loosen"] < 0.95 and sample["clear"] < 0.01:
                blade_frac = ((axis - origin_x) / 10.0 - x0_cm) / span_cm
                loosen_sync.append(abs(blade_frac - sample["loosen"]))
            if 0.05 < sample["clear"] < 0.95:
                bucket_cm = (axis + bottle_offset - origin_x) / 10.0
                clear_sync.append(abs((x1_cm - bucket_cm) / span_cm - sample["clear"]))
        result["loosen_sync_max"] = max(loosen_sync) if loosen_sync else None
        result["clear_sync_max"] = max(clear_sync) if clear_sync else None
        log(f"前沿-轴同步偏差: loosen≤{result['loosen_sync_max']}, clear≤{result['clear_sync_max']}")
        if not loosen_sync:
            failures.append("没采到任何刮松中程样本 —— loosen 通道疑似没动")
        elif max(loosen_sync) > LOOSEN_TOL:
            failures.append(f"刮松前沿与刮刀 9X 列位脱节: 偏差 {max(loosen_sync):.3f} > {LOOSEN_TOL}")
        if not clear_sync:
            failures.append("没采到任何收集中程样本 —— clear 通道疑似没动")
        elif max(clear_sync) > CLEAR_TOL:
            failures.append(f"收集前沿与粉桶位置脱节: 偏差 {max(clear_sync):.3f} > {CLEAR_TOL}")

        # -- 4: 像素 —— 露玻璃与前沿方向 ------------------------------------
        # 时刻: 刮前(下刀前一点)、刮松中程(loosen≈0.5)、收集结束(clear 首次=1 之后)
        t_before = next((s["t"] for s in samples if s["loosen"] > 0), duration * 0.3) - 2.0
        t_mid = min(samples, key=lambda s: abs(s["loosen"] - 0.5) + (1 if s["clear"] > 0 else 0))["t"]
        t_done = next((s["t"] for s in samples if s["clear"] >= 0.999), duration) + 0.5

        def aim_at_plate(view_label: str) -> None:
            """点工具栏视图按钮定**朝向**, 再框住刮板台锚点定**距离**。

            两步缺一不可: frame 走 camera-controls 的 fitToBox, 只调距离与目标点、
            不调朝向(ViewTools.frameObjects) —— 首版只 frame('CARRIAGE.008') 沿用了
            加载默认侧视角, 板整个被机构挡住, 三处采样全落在无关几何上。
            """
            try:
                page.get_by_role("button", name=view_label, exact=True).click(timeout=5_000)
            except Exception:
                page.get_by_text(view_label, exact=True).first.click(timeout=5_000)
            page.wait_for_timeout(500)
            ev("n => window.__anim.frame(n, 0.35)", "玻璃-1.002")
            page.wait_for_timeout(900)

        def band_screen_span() -> float:
            """条带两端点的屏幕跨度(px); 任一端投影失败或出视口返回 0(= 取景没落位)。"""
            pose = ev("p => window.__anim.plateWorld(p)", "plate")
            if not pose or not uv_band:
                return 0.0
            ends = []
            for frac in (0.05, 0.95):
                screen = ev("w => window.__anim.screenOf(w)",
                            list(band_world_point(pose, uv_band, frac)))
                if not screen or not (0 <= screen[0] < 1600 and 0 <= screen[1] < 1000):
                    return 0.0
                ends.append(screen)
            return ((ends[0][0] - ends[1][0]) ** 2 + (ends[0][1] - ends[1][1]) ** 2) ** 0.5

        # 板要先在场才能投影(plateWorld 找的是运行期造的板) —— 停在刮松中程取景
        seek(t_mid, settle_ms=300)
        span = 0.0
        for view in ("顶", "等轴测"):
            aim_at_plate(view)
            span = band_screen_span()
            result["band_screen_span"] = {"view": view, "px": round(span, 1)}
            if span >= 60.0:
                break
        log(f"取景: {result.get('band_screen_span')}")
        pixels_ok = span >= 60.0
        if not pixels_ok:
            failures.append(
                f"取景没落位(条带在屏跨度 {span:.0f}px < 60): 像素判据跳过 —— "
                "先修取景再谈亮度, 采在无关几何上的数不作数")

        def shot(name: str, t: float):
            seek(t, settle_ms=600)
            data = page.screenshot(path=os.path.join(SHOT_DIR, f"{name}.png"))
            log(f"截图 {name}.png (t={t:.1f}s)")
            return Image.open(io.BytesIO(data)) if data else Image.open(
                os.path.join(SHOT_DIR, f"{name}.png"))

        def probe(image, frac: float) -> float | None:
            pose = ev("p => window.__anim.plateWorld(p)", "plate")
            if not pose or not uv_band:
                return None
            world = band_world_point(pose, uv_band, frac)
            screen = ev("w => window.__anim.screenOf(w)", list(world))
            return brightness_at(image, screen) if screen else None

        image = shot("scrape_before", max(t_before, 0.5))
        bright_before = probe(image, 0.5)
        image = shot("scrape_loosen_mid", t_mid)
        bright_mid_head = probe(image, 0.2)
        bright_mid_tail = probe(image, 0.85)
        image = shot("scrape_cleared", min(t_done, duration))
        bright_done = probe(image, 0.5)
        result["pixels"] = {
            "before_center": bright_before, "mid_head": bright_mid_head,
            "mid_tail": bright_mid_tail, "done_center": bright_done,
        }
        log(f"亮度: 刮前中心={bright_before}, 中程起始侧={bright_mid_head}, "
            f"中程末端侧={bright_mid_tail}, 收尽中心={bright_done}")
        if pixels_ok:
            if bright_before is None or bright_done is None:
                failures.append("像素采样失败(plateWorld/screenOf 返回空)")
            else:
                if bright_before - bright_done < 12:
                    failures.append(
                        f"收集后条带中心没有露玻璃迹象: 亮度 {bright_before:.0f} → {bright_done:.0f}"
                        "(应显著变暗)")
                if (bright_mid_head is not None and bright_mid_tail is not None
                        and bright_mid_head > bright_mid_tail - 2):
                    failures.append(
                        f"刮松中程前沿方向可疑: 起始侧 {bright_mid_head:.0f} 应暗于末端侧 "
                        f"{bright_mid_tail:.0f}(灰层该先出现在起始侧)")

        # -- 5: 向后 seek 复位 ----------------------------------------------
        seek(0, settle_ms=300)
        status = ev("window.__anim.plates()") or {}
        back = status.get("scrape")
        rows = status.get("rows") or []
        result["seek_back"] = {"scrape": back, "rows": rows}
        if back and (back.get("loosen", 0) > 1e-3 or back.get("clear", 0) > 1e-3):
            failures.append(f"向后 seek 留下刮取残留: {back}")
        if len(rows) != 1:
            failures.append(f"向后 seek 后板数不为 1: {rows}")

        # -- 6: cycle 抽查 --------------------------------------------------
        log(f"抽查 {args.cycle_url}")
        page.goto(args.cycle_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_function("() => !!window.__anim", timeout=120_000)
        page.wait_for_timeout(3000)
        seek(0, settle_ms=300)
        cycle_status = ev("window.__anim.plates()") or {}
        cycle_rows = cycle_status.get("rows") or []
        cycle_scrape = cycle_status.get("scrape")
        result["cycle_t0"] = {"rows": cycle_rows, "scrape": cycle_scrape}
        # t=0 有 carried 的板是合法的: cycle 内联的板上料段自己声明"板起手时已在机器人
        # 手上"(plate.flow.photoscrape_load 同款)。要防的只是 PHASE_ENTRY_STATE 把
        # "板已在刮板台"的起手式错误提前到含上料段的父流程里。
        if any(row.get("slot") == "scrape_table" for row in cycle_rows):
            failures.append(f"photoscrape_cycle t=0 板已在刮板台 —— 起手式被错误提前: {cycle_rows}")
        if cycle_scrape and (cycle_scrape.get("loosen", 0) > 1e-3
                             or cycle_scrape.get("clear", 0) > 1e-3):
            failures.append(f"photoscrape_cycle t=0 就有刮取状态: {cycle_scrape}")

        browser.close()

    result["failures"] = failures
    out = os.path.join(WORK_DIR, "verify_scrape_band.json")
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
