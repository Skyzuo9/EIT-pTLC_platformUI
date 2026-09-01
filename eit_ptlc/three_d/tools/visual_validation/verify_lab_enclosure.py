"""
功能:
    实验室背景"封闭罩不穿帮"的整机验收 —— 场景图探针与像素判据两条独立成立才算过.

    背景: 旧实现是开口圆筒 + 有限方板地面, 而相机上限(modelRadius*12)比房间半径大好几倍,
    缩到最小必穿帮. 现在罩体封闭且相机上限由罩体剖面反推, 本脚本就是这个不变量的整机门禁.

    三条判据(前两条是门禁, 第三条出图给人看):
      1. 包含性: 相机在极限位上逐点落在罩体剖面内 —— 点在多边形内判定, 与
         laboratorySafeDistance 的最近距离算法完全无关, 不构成自证.
      2. 视线: 从相机往画面上打一片射线, 每一条都必须打到东西. 只要有一条打空,
         就说明那个方向能看到背景 —— 即看穿了壳体. 这条判据不渲染任何一帧, 因此
         不受无头软件 GL 的帧率影响, 也不受色板调整影响(拿背景色做容差比对是不行的:
         渐变背景 0xdce3eb 与壳体 0xdce9f7 差不到一档, 任何容差都分不开
         "看穿了"和"壳体本来就这个色").
      3. 像素: 把渲染器清屏色换成哨兵洋红并置空 scene.background, 截图里出现洋红
         同样等于看穿. 这条要真渲染, 只在稀疏机位上跑, 顺带留下可目检的图.

用法:
    & "C:/ProgramData/miniforge3/python.exe" verify_lab_enclosure.py [--url http://127.0.0.1:15173] [--headed]

    必须打 vite dev(15173): window.__ptlcTwin 只在 DEV 构建里挂, 18080 的 dist 拍不到探针.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy
from playwright.sync_api import sync_playwright
from PIL import Image

# 无头 Chromium 走软件 GL 必然掉帧, 自动降档会把 shadows 关掉 —— 测之前钉死档位,
# 否则分不清"功能没生效"还是"这档本来就不渲"
PIN_QUALITY = """() => {
  const m = window.__ptlcTwin?.manager
  if (!m) return false
  m.autoDegrade = false
  m.setQuality('high')
  return true
}"""

# 视线判据: 往整个画面打一片射线, 每一条都必须命中**一体罩本身**.
# 打空 = 那个方向的画面上没有壳体 = 看得到背景 = 穿帮. 不渲染任何一帧, 与画面质量无关.
# 只对 LAB_SHELL 求交(而不是整个场景)有两个好处: 判据更严(设备挡住不算数), 且只有
# 七千来个三角形, 一百多条射线瞬间跑完 —— 对整机求交会慢到不可用.
# 复用 picker 的 Raycaster 实例是为了拿到构造器: 页面里没有裸的 THREE 命名空间可用.
RAY_ESCAPE_PROBE = """() => {
  const m = window.__ptlcTwin.manager
  const camera = m.cameraRig.camera
  camera.updateMatrixWorld(true)
  const shell = m.scene.getObjectByName('LAB_SHELL')
  const raycaster = m.picker?.raycaster
  if (!shell || !raycaster) return {error: !shell ? '未找到 LAB_SHELL' : '未找到 raycaster'}

  // 取格心而不是格点: 格点会落在 ndc.x === 0 上, 而相机方位角对着 Lathe 接缝(phi=0)时
  // 这一整列射线正好擦着接缝那条共享棱过去, 背面剔除的三角求交在浮点上两个三角都判不中,
  // 于是报出一列"打空". 2026-08-14 实测: 8 条打空全部落在 x===0, 给 0.001 抖动即全部消失,
  // 且同机位的哨兵像素判据一个洋红都没有 —— 是求交的刀刃工况, 不是壳体真有洞.
  let escaped = 0
  let total = 0
  const steps = 12
  for (let ix = 0; ix < steps; ix += 1) {
    for (let iy = 0; iy < steps; iy += 1) {
      raycaster.setFromCamera(
        {x: ((ix + 0.5) / steps) * 2 - 1, y: ((iy + 0.5) / steps) * 2 - 1},
        camera,
      )
      raycaster.far = Infinity
      total += 1
      if (!raycaster.intersectObject(shell, false).length) escaped += 1
    }
  }
  const p = camera.position
  return {escaped, total, camera: {x: p.x, y: p.y, z: p.z}}
}"""

# 取样机位: 极角自顶视到接近水平, 方位绕一圈; 全部拉到 maxDistance 极限位.
# 场景图判定是纯算术, 跑满密网格; 像素判定要落一次盘 + 软件 GL 渲一帧, 取子网格.
POLAR_STEPS = 8
AZIMUTH_STEPS = 12
SHOT_POLAR_EVERY = 2
SHOT_AZIMUTH_EVERY = 3
# 哨兵色: 场景里不可能自然出现的洋红
SENTINEL_RGB = (255, 0, 255)
SENTINEL_TOLERANCE = 40
# 无头 Chromium 走 SwiftShader 软件 GL, 高画质档一帧要好几秒, 截图默认 30s 会超时
SHOT_TIMEOUT_MS = 180_000


def _profile_points(layout: dict) -> list[tuple[float, float]]:
    """
    功能:
        复刻 laboratoryProfile 的剖面折线, 用于点在多边形内判定.
    参数:
        layout 浏览器侧读回的罩体布局
    返回:
        List[Tuple[float, float]], 每项为 (离轴半径, 世界高度)
    """
    radius = layout["radius"]
    height = layout["height"]
    dome_rise = layout["domeRise"]
    fillet = min(layout["filletRadius"], radius * 0.45, height * 0.9)
    floor_y = layout["shellBaseY"]

    points = [(0.0, floor_y), (radius - fillet, floor_y)]
    fillet_segments = 14
    for index in range(1, fillet_segments):
        angle = (index / fillet_segments) * math.pi * 0.5
        points.append((
            radius - fillet + math.sin(angle) * fillet,
            floor_y + fillet - math.cos(angle) * fillet,
        ))
    points.append((radius, floor_y + fillet))
    points.append((radius, floor_y + height))
    dome_segments = 20
    for index in range(1, dome_segments):
        angle = (index / dome_segments) * math.pi * 0.5
        points.append((
            math.cos(angle) * radius,
            floor_y + height + math.sin(angle) * dome_rise,
        ))
    points.append((0.0, floor_y + height + dome_rise))
    return points


def _inside_shell(layout: dict, point: dict) -> bool:
    """
    功能:
        判定世界点是否落在罩体内部(投到"离轴距-高度"半平面后做射线穿越计数).
    参数:
        layout 罩体布局; point 含 x/y/z 的世界坐标
    返回:
        bool, True 表示在罩内
    """
    polygon = _profile_points(layout)
    radius = math.hypot(point["x"] - layout["centerX"], point["z"] - layout["centerZ"])
    height = point["y"]

    inside = False
    count = len(polygon)
    for index in range(count):
        previous = polygon[index - 1]
        current = polygon[index]
        if (current[1] > height) == (previous[1] > height):
            continue
        cross = current[0] + (height - current[1]) / (previous[1] - current[1]) * (previous[0] - current[0])
        if radius < cross:
            inside = not inside
    return inside


def _count_sentinel(path: Path) -> int:
    """
    功能:
        统计截图里落在哨兵洋红容差内的像素数.
    参数:
        path 截图路径
    返回:
        int, 命中像素数
    """
    pixels = numpy.asarray(Image.open(path).convert("RGB"), dtype=numpy.int16)
    hit_mask = (
        (pixels[:, :, 0] >= SENTINEL_RGB[0] - SENTINEL_TOLERANCE)
        & (pixels[:, :, 1] <= SENTINEL_RGB[1] + SENTINEL_TOLERANCE)
        & (pixels[:, :, 2] >= SENTINEL_RGB[2] - SENTINEL_TOLERANCE)
    )
    return int(hit_mask.sum())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:15173")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / "work" / "previews" / "lab_enclosure"
    out_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    with sync_playwright() as playwright:
        # 无头默认走 SwiftShader 软件 GL, 整机高画质一帧要好几秒, 截图必然超时;
        # 显式要 ANGLE/D3D11 后交给真显卡, 截图才跑得动
        browser = playwright.chromium.launch(
            headless=not args.headed,
            args=[
                "--use-gl=angle",
                "--use-angle=d3d11",
                "--enable-gpu",
                "--ignore-gpu-blocklist",
            ],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto(f"{args.url}/3d/live", wait_until="domcontentloaded")

        # 等整机加载完成: manager.machineRoot 有值才说明 GLB 已挂上
        page.wait_for_function(
            "() => Boolean(window.__ptlcTwin?.manager?.machineRoot)",
            timeout=120_000,
        )
        assert page.evaluate(PIN_QUALITY), "未能钉死画质档位"

        page.evaluate("() => window.__ptlcTwin.manager.display.set('backgroundScene', 'laboratory')")
        # 开场动画每帧都改写相机, 不等它跑完摆的机位会被顶掉(它最后落在 iso 预设上)
        page.wait_for_function(
            "() => window.__ptlcTwin.manager.intro?.isRunning?.() !== true",
            timeout=60_000,
        )
        page.wait_for_timeout(600)

        probe = page.evaluate("""() => {
          const m = window.__ptlcTwin.manager
          const rig = m.cameraRig
          const layout = m.environment.getEnclosureLayout
            ? m.environment.getEnclosureLayout()
            : null
          return {
            maxDistance: rig.controls.maxDistance,
            minDistance: rig.controls.minDistance,
            maxPolarAngle: rig.controls.maxPolarAngle,
            modelRadius: rig.modelRadius,
            enclosureRadius: rig.enclosureRadius,
            center: {x: rig.modelCenter.x, y: rig.modelCenter.y, z: rig.modelCenter.z},
            quality: m.quality,
            envReady: Boolean(m.scene.environment),
            layout,
          }
        }""")
        print("[探针] " + json.dumps(probe, ensure_ascii=False))

        if probe["layout"] is None:
            failures.append("Environment 未暴露 getEnclosureLayout, 无法做场景图判据")
        if probe["enclosureRadius"] is None:
            failures.append("切到实验室背景后 CameraRig.enclosureRadius 仍为 null, 罩体约束没接上")
        if not probe["envReady"]:
            failures.append("scene.environment 为空, HDRI 环境贴图没有到位")

        layout = probe["layout"]
        max_distance = probe["maxDistance"]

        # 背景换成哨兵洋红: 置空 scene.background 后渲染器用 clearColor 清屏,
        # 之后画面里出现洋红就等于看穿了壳体
        page.evaluate("""() => {
          const m = window.__ptlcTwin.manager
          m.scene.background = null
          m.renderer.setClearColor(0xff00ff, 1)
        }""")

        canvas = page.locator("canvas").first
        shots = 0
        for polar_step in range(POLAR_STEPS + 1):
            polar = (polar_step / POLAR_STEPS) * probe["maxPolarAngle"]
            for azimuth_step in range(AZIMUTH_STEPS):
                azimuth = (azimuth_step / AZIMUTH_STEPS) * math.pi * 2
                page.evaluate(
                    """([polar, azimuth, distance]) => {
                      const rig = window.__ptlcTwin.manager.cameraRig
                      // transition=false 直接落位: 带过渡的运镜会被页面里别的相机动作打断,
                      // 于是在"相机还在飘"的中间态上做判定, 假阳性/假阴性都可能
                      rig.controls.rotateTo(azimuth, Math.max(polar, 1e-3), false)
                      rig.controls.dollyTo(distance, false)
                      rig.controls.update(0)
                    }""",
                    [polar, azimuth, max_distance],
                )
                state = page.evaluate(RAY_ESCAPE_PROBE)
                if state.get("error"):
                    failures.append(f"视线探针无法运行: {state['error']}")
                    break
                camera = state["camera"]
                if layout is not None and not _inside_shell(layout, camera):
                    failures.append(
                        f"相机捅出罩外: 极角 {polar:.3f} 方位 {azimuth:.3f} 距离 {max_distance:.3f} "
                        f"位置 {camera}"
                    )
                if state["escaped"]:
                    failures.append(
                        f"视线打空 {state['escaped']}/{state['total']} 条: 极角 {polar:.3f} "
                        f"方位 {azimuth:.3f} —— 这些方向能直接看到背景, 即壳体被看穿"
                    )

                if polar_step % SHOT_POLAR_EVERY or azimuth_step % SHOT_AZIMUTH_EVERY:
                    continue
                page.wait_for_timeout(400)
                shot = out_dir / f"p{polar_step}_a{azimuth_step}.png"
                canvas.screenshot(path=str(shot), timeout=SHOT_TIMEOUT_MS)
                shots += 1
                hits = _count_sentinel(shot)
                if hits > 0:
                    failures.append(f"{shot.name}: 哨兵背景像素 {hits} 个 —— 壳体被看穿")

        print(f"[取样] 场景图 {(POLAR_STEPS + 1) * AZIMUTH_STEPS} 个极限机位, 像素 {shots} 张")
        browser.close()

    if failures:
        print("\n[失败]")
        for line in failures:
            print("  - " + line)
        return 1
    print("\n[通过] 全部极限机位: 相机在罩内, 且画面里没有一个哨兵像素")
    return 0


if __name__ == "__main__":
    sys.exit(main())
