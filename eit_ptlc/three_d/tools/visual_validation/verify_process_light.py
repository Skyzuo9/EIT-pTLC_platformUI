"""
功能: 孪生实时页「视觉补光(DO7)」的可见性验收 —— 注入 process_light 事件, 量化下相机
      盖板玻璃到底有没有在画面里亮起来.

为什么必须量化而不是目检: 这条链坏掉时**画面完全正常**, 数据也全对 —— 材质被别的绑定层
二次克隆后, 亮度写进一份被丢弃的孤儿材质, 探针读它照样返回 1.8(2026-08-05 实测栽过一轮).
所以这里有两道互相独立的判据:

  1. **场景图判据**: 从 manager.machineRoot traverse 找到那块玻璃, 断言它当前挂着的
     material 就是绑定层持有的那份, 且 emissiveIntensity 随事件变化;
  2. **像素判据**: 对准玻璃截图, 开灯前后逐像素比对. 比对前**切掉左侧 HUD** ——
     fps / 绘制调用数字每帧都在变, 会把"视口零变化"伪装成"变了几百像素".

前提: vite 开发服务器在 15173 (`__ptlcTwin` 注入口只存在于 DEV 构建).
用法: C:/ProgramData/miniforge3/python.exe verify_process_light.py [--url ...]
返回值: 无; 任一判据不过以退出码 1 结束.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SHOT_DIR = os.path.normpath(os.path.join(APP_DIR, "..", "..", "work", "previews", "review"))

LIGHT_ID = "vision_fill"
GLASS_HINT = "PTLC-08-010"          # 下相机盖板玻璃
HUD_WIDTH = 420                     # 左侧 HUD 宽度(含余量), 像素比对时切掉

# 场景图真值探针: 亮度 + "场景里那个网格挂的是不是绑定层持有的那份材质"
JS_PROBE = """
() => {
  const bindings = window.__ptlcTwin.manager.bindings
  const entry = bindings.machine.lights.get(%(id)r)
  const owned = new Map()
  owned.set(entry.mesh.name, entry.material)
  for (const t of entry.lit || []) owned.set(t.mesh.name, t.material)

  const out = { level: entry.value, meshes: {} }
  window.__ptlcTwin.manager.machineRoot.traverse((n) => {
    if (!n.isMesh) return
    const mine = owned.get(n.name)
    if (!mine) return
    out.meshes[n.name] = {
      intensity: n.material.emissiveIntensity,
      // 孤儿材质检测: 场景图上挂的必须就是绑定层写入的那一份
      sameMaterial: n.material === mine,
      visible: n.visible,
    }
  })
  out.bloom = bindings.getBloomTargets().map((m) => m.name)
  return out
}
""" % {"id": LIGHT_ID}

# 取景刻意不走 ViewTools —— 那个是各 View 自己 new 的, 实时页没有挂到 manager 上.
# 直接用 camera-controls 的 fitToBox(只动相机, 不改 modelBox/雾范围). Box3 的构造器
# 从页面里现成的实例上取, 免得在注入脚本里 import three.
JS_FRAME = """
(hint) => {
  const targets = []
  window.__ptlcTwin.manager.machineRoot.traverse((n) => {
    if (n.isMesh && n.name.includes(hint)) targets.push(n)
  })
  if (!targets.length) return 0
  const controls = window.__ptlcTwin.manager.cameraRig?.controls
  if (!controls) return null
  targets[0].geometry.computeBoundingBox()
  const Box3 = Object.getPrototypeOf(targets[0].geometry.boundingBox).constructor
  const box = new Box3()
  for (const t of targets) box.expandByObject(t, true)
  const Vec3 = Object.getPrototypeOf(box.min).constructor
  const c = box.getCenter(new Vec3())
  const size = box.getSize(new Vec3())
  // 这扇窗朝上(下相机透过它向上看板), 所以必须从斜上方近距离怼着看。
  // fitToBox 的带过渡飞行在这台机器上会被别的相机动作打断, 干脆显式落位、transition=false。
  const d = Math.max(size.x, size.z) * 1.6 + 0.12
  controls.setLookAt(c.x + d * 0.45, c.y + d, c.z + d * 0.45, c.x, c.y, c.z, false)
  return { count: targets.length, center: [c.x, c.y, c.z], size: [size.x, size.y, size.z] }
}
"""


def inject(page, on: bool) -> None:
    """功能: 往 TwinFeed 注入一帧 process_light. 参数: page, on. 返回值: None"""
    page.evaluate(
        "(on) => window.__ptlcTwin.feed.handleEvent("
        f"  {{ type: 'process_light', id: '{LIGHT_ID}', on, channel: 7, ts: Date.now() / 1000 }})",
        on,
    )


def diff_pixels(before: str, after: str) -> tuple[int, float]:
    """功能: 切掉左侧 HUD 后逐像素比差. 参数: 两张图路径. 返回值: (变化像素数, 最大通道差)"""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(before).convert("RGB"), dtype=np.int16)[:, HUD_WIDTH:, :]
    b = np.asarray(Image.open(after).convert("RGB"), dtype=np.int16)[:, HUD_WIDTH:, :]
    delta = np.abs(b - a)
    return int((delta.max(axis=2) > 3).sum()), float(delta.max())


def main() -> None:
    """功能: 命令行入口. 参数: 无(读 sys.argv). 返回值: None"""
    parser = argparse.ArgumentParser(description="补光可见性验收")
    parser.add_argument("--url", default="http://localhost:15173/3d/live")
    parser.add_argument("--wait", type=int, default=180)
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    os.makedirs(SHOT_DIR, exist_ok=True)
    failures: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--enable-gpu", "--ignore-gpu-blocklist"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(args.url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_function(
            "() => window.__ptlcTwin?.manager?.bindings?.machine?.lights?.size",
            timeout=args.wait * 1000,
        )
        page.wait_for_timeout(3000)

        framed = page.evaluate(JS_FRAME, GLASS_HINT)
        print(f"取景: {json.dumps(framed, ensure_ascii=False)}")
        if not framed:
            failures.append(f"场景里找不到含「{GLASS_HINT}」的网格(或相机不可用), 取景失败")
        # fitToBox 是带过渡的飞行, 且场上有别的常驻动画(塔灯呼吸/液面). 必须等到画面
        # 真正静下来再拍第一张, 否则相机漂移会被算成"灯亮了"(实测 4000+ 像素的假阳性).
        page.wait_for_timeout(6000)

        # -- 灭(未收帧, 应保持烘焙态) ----------------------------------------
        noise_shot = os.path.join(SHOT_DIR, "proclight_noise.png")
        page.screenshot(path=noise_shot)
        page.wait_for_timeout(1200)
        off_shot = os.path.join(SHOT_DIR, "proclight_off.png")
        page.screenshot(path=off_shot)
        probe_off = page.evaluate(JS_PROBE)
        print("灭:", json.dumps(probe_off, ensure_ascii=False))

        # -- 亮(斜坡 0.25s, 留足余量) ----------------------------------------
        inject(page, True)
        page.wait_for_timeout(1200)
        on_shot = os.path.join(SHOT_DIR, "proclight_on.png")
        page.screenshot(path=on_shot)
        probe_on = page.evaluate(JS_PROBE)
        print("亮:", json.dumps(probe_on, ensure_ascii=False))

        # -- 复灭(下降沿 0.35s) ----------------------------------------------
        inject(page, False)
        page.wait_for_timeout(1500)
        back_shot = os.path.join(SHOT_DIR, "proclight_off2.png")
        page.screenshot(path=back_shot)
        probe_back = page.evaluate(JS_PROBE)
        print("复灭:", json.dumps(probe_back, ensure_ascii=False))
        browser.close()

    # -- 判据 1: 场景图 ------------------------------------------------------
    if not probe_on["meshes"]:
        failures.append("探针在场景图里没找到任何被工艺灯独占的网格")
    for name, info in probe_on["meshes"].items():
        if not info["sameMaterial"]:
            failures.append(f"{name}: 场景里挂的材质≠绑定层写入的那份(被二次克隆顶掉)")
        if not info["visible"]:
            failures.append(f"{name}: 网格不可见, 亮了也看不到")
        if info["intensity"] <= 0.01:
            failures.append(f"{name}: 开灯后 emissiveIntensity={info['intensity']}, 没亮")
    if probe_on["level"] < 0.99:
        failures.append(f"斜坡 1.2s 后 level={probe_on['level']}, 未到满亮")
    if probe_back["level"] > 0.01:
        failures.append(f"灭灯后 level={probe_back['level']}, 未回落")
    # 辉光选集只看**本盏灯的**成员进出: 塔灯与紫外面光源是常亮的, 它们一直在集合里,
    # 直接断言"灭灯后集合为空"会被那两盏长期占位的灯判错.
    mine = set(probe_on["meshes"])
    if not (mine & set(probe_on["bloom"])):
        failures.append("开灯后本盏灯没进辉光选集 —— 它不会发光晕")
    still_lit = mine & set(probe_back["bloom"])
    if still_lit:
        failures.append(f"灭灯后仍留在辉光选集里: {sorted(still_lit)}")

    # -- 判据 2: 像素 --------------------------------------------------------
    # 噪声底: 同一静止画面连拍两张的差. 场上有常驻动画(塔灯/液面), 不减掉这个底
    # 就分不清"灯亮了"和"别的东西在动".
    noise, noise_peak = diff_pixels(noise_shot, off_shot)
    print(f"噪声底(灭态连拍两张): {noise} 像素, 最大通道差 {noise_peak}")
    floor = max(500, noise * 3)

    changed, peak = diff_pixels(off_shot, on_shot)
    print(f"开灯前后(已切掉左侧 {HUD_WIDTH}px HUD): 变化 {changed} 像素, 最大通道差 {peak}"
          f" [判据 >{floor}]")
    if changed < floor:
        failures.append(f"开灯前后仅 {changed} 像素变化(噪声底 {noise}), 视口上看不出来")
    changed_back, peak_back = diff_pixels(on_shot, back_shot)
    print(f"熄灭后相对亮态: {changed_back} 像素, 最大通道差 {peak_back} [判据 >{floor}]")
    if changed_back < floor:
        failures.append(f"熄灭后相对亮态仅 {changed_back} 像素变化(噪声底 {noise}), 灯没真灭")

    if failures:
        print("\n".join(f"FAIL {f}" for f in failures))
        raise SystemExit(1)
    print("PASS 补光在实时页可见, 且场景图材质归属正确")


if __name__ == "__main__":
    main()
