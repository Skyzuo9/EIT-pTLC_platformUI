/**
 * 功能: 刮取遮罩的几何换算(scrapeOverlay) —— 机床方向、cm→UV 映射、前沿子矩形与画布绘制.
 *
 * 最要害的是**方向**: 条带画反了 90° 或前沿走反了, 画面照样"很真"(一条灰带在动),
 * 没有任何运行期指标会报警 —— 所以四个朝向、8Y 取反、收集回扫 −X 全部钉成单测。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import {
  SCRAPE_LOOSEN_FILL, SPOT_BAND_FILL, WET_FILL, bandComplement, bandToUv, drawScrape,
  drawTrace, drawWetRoughness, gravityDirsWorld, machineDirsWorld, pathToUv, progressRect,
  progressStroke, troughDirsWorld,
  residualLevels, scrapeRects, uvRectToLocal,
} from '../../src/three-d/twin/scene/plates/scrapeOverlay.js'

/** 与 clip_compiler 产物同形的条带声明(板 cm 帧)。 */
const REGION = {
  plateSizeCm: [20, 20],
  bandCm: [2, 8, 18, 10],
  loosen: { axis: 'x', dir: 1 },
  clear: { axis: 'x', dir: -1 },
}

/**
 * 造两根轴的最小场景: 滑车挂在各自父级下, 父级可带旋转(验证"axis 表达在父空间")。
 * 轴向取与真机同构的语义: 9X 沿某个水平轴, 8Y 沿另一个。
 */
function makeAxes({ sign9 = 1, sign8 = 1, parentQuat = null } = {}) {
  const root = new THREE.Group()
  const nodes = new Map()
  for (const [axisId, leaf, axis, sign] of [
    ['axis_9x', 'CARR9', [1, 0, 0], sign9],
    ['axis_8y', 'CARR8', [0, 0, 1], sign8],
  ]) {
    const parent = new THREE.Group()
    if (parentQuat) parent.quaternion.copy(parentQuat)
    const carriage = new THREE.Group()
    carriage.name = leaf
    parent.add(carriage)
    root.add(parent)
    nodes.set(`ST_PS/${axisId.toUpperCase()}/${leaf}`, carriage)
    nodes.set(leaf, carriage)
  }
  root.updateMatrixWorld(true)
  const manifest = {
    axes: [
      { id: 'axis_9x', axis: [1, 0, 0], sign: sign9, glbNode: 'ST_PS/AXIS_9X/CARR9' },
      { id: 'axis_8y', axis: [0, 0, 1], sign: sign8, glbNode: 'ST_PS/AXIS_8Y/CARR8' },
    ],
  }
  return { manifest, resolve: (name) => nodes.get(name) }
}

const close = (vec, expected, msg) => {
  assert.ok(vec.distanceTo(new THREE.Vector3(...expected)) < 1e-9,
    `${msg}: ${vec.toArray()} vs ${expected}`)
}

test('machineDirsWorld: 9X 顺轴向, 8Y 取反(板动刀不动)', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  close(dirs.xCm, [1, 0, 0], '机床 X 应顺 9X 轴向')
  close(dirs.yCm, [0, 0, -1], '机床 Y 应是 8Y 轴向取反 —— 8Y 驮着板, 接触点相对板反着走')
})

test('machineDirsWorld: sign 参与方向(9X 真机 sign=-1 的形态)', () => {
  const { manifest, resolve } = makeAxes({ sign9: -1 })
  const dirs = machineDirsWorld(manifest, resolve)
  close(dirs.xCm, [-1, 0, 0], 'sign=-1 应翻转轴向')
})

test('machineDirsWorld: axis 表达在滑车父级空间, 父级带旋转要转到世界', () => {
  const quat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2)
  const { manifest, resolve } = makeAxes({ parentQuat: quat })
  const dirs = machineDirsWorld(manifest, resolve)
  // 父级绕 Y 转 90°: 局部 +X → 世界 −Z, 局部 +Z → 世界 +X(再取反成 −X)
  close(dirs.xCm, [0, 0, -1], '9X 方向应随父级旋转')
  close(dirs.yCm, [-1, 0, 0], '8Y 方向应随父级旋转后再取反')
})

test('machineDirsWorld: 滑车解析不到时返回 null(留白, 不猜)', () => {
  const { manifest } = makeAxes()
  assert.equal(machineDirsWorld(manifest, () => undefined), null)
  assert.equal(machineDirsWorld({ axes: [] }, () => undefined), null)
})

test('bandToUv: 板未旋转时 cm x→u、cm y→v, 条带落在正确的 UV 矩形', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  const uv = bandToUv(REGION, new THREE.Quaternion(), dirs)
  // cm x ↔ +localX → u=f; cm y(世界 −Z) ↔ −localZ → v=f
  assert.ok(Math.abs(uv.u0 - 0.1) < 1e-12 && Math.abs(uv.u1 - 0.9) < 1e-12, `u ${uv.u0}..${uv.u1}`)
  assert.ok(Math.abs(uv.v0 - 0.4) < 1e-12 && Math.abs(uv.v1 - 0.5) < 1e-12, `v ${uv.v0}..${uv.v1}`)
  assert.deepEqual(uv.loosen, { coord: 'u', dir: 1 }, '刮松沿 +u 推进')
  assert.deepEqual(uv.clear, { coord: 'u', dir: -1 }, '收集回扫沿 −u')
})

test('bandToUv: 板面内转 90° 后条带跟着转到另一根 UV 轴, 前沿方向同步换算', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  const quat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2)
  const uv = bandToUv(REGION, quat, dirs)
  // 板转 90°: 世界 +X(cm x) 现在对着板局部 +Z → v=1−f; 世界 −Z(cm y) 对着局部 +X → u=f
  assert.ok(Math.abs(uv.v0 - 0.1) < 1e-12 && Math.abs(uv.v1 - 0.9) < 1e-12, `v ${uv.v0}..${uv.v1}`)
  assert.ok(Math.abs(uv.u0 - 0.4) < 1e-12 && Math.abs(uv.u1 - 0.5) < 1e-12, `u ${uv.u0}..${uv.u1}`)
  assert.deepEqual(uv.loosen, { coord: 'v', dir: -1 }, 'cm x 映射带负号(v=1−f), 前沿方向要跟着翻')
  assert.deepEqual(uv.clear, { coord: 'v', dir: 1 })
})

test('bandToUv: 板斜摆 45° 或两根 cm 轴撞同一根局部轴时返回 null(宁可不画)', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  const skew = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4)
  assert.equal(bandToUv(REGION, skew, dirs), null, '45° 谁都不贴, 必须留白')
  const clash = { xCm: new THREE.Vector3(1, 0, 0), yCm: new THREE.Vector3(1, 0, 0) }
  assert.equal(bandToUv(REGION, new THREE.Quaternion(), clash), null, '两轴撞同一根局部轴')
})

test('bandToUv: 声明不完整(缺尺寸/缺 bbox)返回 null', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  assert.equal(bandToUv({ bandCm: [0, 0, 1, 1] }, new THREE.Quaternion(), dirs), null)
  assert.equal(bandToUv({ plateSizeCm: [20, 20] }, new THREE.Quaternion(), dirs), null)
  assert.equal(bandToUv(REGION, new THREE.Quaternion(), null), null)
})

/** 未旋转板的标准 uvBand(下面几条共用)。 */
function plainUv() {
  const { manifest, resolve } = makeAxes()
  return bandToUv(REGION, new THREE.Quaternion(), machineDirsWorld(manifest, resolve))
}

test('scrapeRects: 前沿子矩形随进度推进, dir=−1 从高端往回吃', () => {
  const uv = plainUv()
  assert.equal(scrapeRects(uv, 0, 0).loosen, null, '进度 0 什么都不画')
  const half = scrapeRects(uv, 0.5, 0)
  assert.ok(Math.abs(half.loosen.u1 - 0.5) < 1e-12, `+u 前沿走到带中: ${half.loosen.u1}`)
  assert.ok(Math.abs(half.loosen.u0 - 0.1) < 1e-12, '起点边不动')

  const collect = scrapeRects(uv, 1, 0.25)
  assert.deepEqual(collect.loosen, { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5 }, '刮完 = 整条带')
  assert.ok(Math.abs(collect.clear.u0 - 0.7) < 1e-12, `−u 前沿从 u1 往回吃 1/4: ${collect.clear.u0}`)
  assert.ok(Math.abs(collect.clear.u1 - 0.9) < 1e-12)
})

test('scrapeRects: 幂等且不改入参(seek 契约在几何层的形状)', () => {
  const uv = plainUv()
  const snapshot = JSON.stringify(uv)
  const a = scrapeRects(uv, 0.37, 0.11)
  const b = scrapeRects(uv, 0.37, 0.11)
  assert.deepEqual(a, b, '同入参必须同结果')
  assert.equal(JSON.stringify(uv), snapshot, 'uvBand 不许被原地修改')
})

/** 记录式画布 stub(node 环境没有 DOM, 生产画布行为由 verify_scrape_band.py 兜)。 */
function stubCanvas() {
  const ops = []
  const ctx = {
    fillStyle: '',
    globalCompositeOperation: '',
    fillRect(x, y, w, h) { ops.push({ op: 'fill', style: this.fillStyle, x, y, w, h }) },
    clearRect(x, y, w, h) { ops.push({ op: 'clear', x, y, w, h }) },
  }
  return { width: 256, height: 256, ops, getContext: () => ctx }
}

test('drawScrape: 白底整幅重画 → 灰 loosen → clearRect, 并做 flipY 换算', () => {
  const canvas = stubCanvas()
  const uv = plainUv()
  drawScrape(canvas, scrapeRects(uv, 1, 0.5))

  assert.equal(canvas.ops.length, 3)
  const [base, loosen, clear] = canvas.ops
  assert.deepEqual([base.op, base.style, base.w, base.h], ['fill', '#ffffff', 256, 256], '先铺白底')
  assert.equal(loosen.style, SCRAPE_LOOSEN_FILL)
  // v∈[0.4,0.5] → 画布 y 从 (1−0.5)*256=128 起, 高 0.1*256=25.6(CanvasTexture flipY)
  assert.ok(Math.abs(loosen.y - 128) < 1e-9 && Math.abs(loosen.h - 25.6) < 1e-9,
    `loosen y=${loosen.y} h=${loosen.h}`)
  assert.equal(clear.op, 'clear')
  // clear 从 u=0.5 往回到 0.9: x = 0.5*256 = 128, 宽 0.4*256 = 102.4
  assert.ok(Math.abs(clear.x - 128) < 1e-9 && Math.abs(clear.w - 102.4) < 1e-9,
    `clear x=${clear.x} w=${clear.w}`)
})

test('drawScrape: 进度 0 只铺白底(遮罩回到未刮态, 供 seek 重放复位)', () => {
  const canvas = stubCanvas()
  drawScrape(canvas, scrapeRects(plainUv(), 0, 0))
  assert.equal(canvas.ops.length, 1)
  assert.equal(canvas.ops[0].op, 'fill')
})

// ── 分层刮取(2026-08-06) ──────────────────────────────────────────────────
// 真机 num_passes 刀、每刀只吃 total_depth/N, 一刀刮不到玻璃。凹坑靠"遮罩挖洞 +
// 洞底垫残余薄板"表达, 下面三条钉住那套换算 —— 算错的表现是"薄板与坑错位"或
// "第一刀就见玻璃", 画面都很像, 没有运行期指标会报。

test('residualLevels: 逐刀变浅, 只有最后一刀露玻璃', () => {
  assert.deepEqual(residualLevels({ pass: 0 }, 2), { pass: 0, passes: 2, cut: 1, prior: 1 })
  assert.deepEqual(residualLevels({ pass: 1 }, 2), { pass: 1, passes: 2, cut: 0.5, prior: 1 })
  assert.deepEqual(residualLevels({ pass: 2 }, 2), { pass: 2, passes: 2, cut: 0, prior: 0.5 })
  // 三刀: 中间两刀都留残余
  assert.equal(residualLevels({ pass: 1 }, 3).cut, 2 / 3)
  assert.equal(residualLevels({ pass: 3 }, 3).cut, 0)
})

test('residualLevels: 老片段没有 pass 通道时按最后一刀算(与分层前行为逐帧一致)', () => {
  assert.equal(residualLevels({}, 2).pass, 2)
  assert.equal(residualLevels({}, 2).cut, 0, '露玻璃')
  assert.equal(residualLevels({ pass: undefined }, 1).cut, 0)
  // 层号越界一律夹住, 不让脏值把薄板算成负厚度
  assert.equal(residualLevels({ pass: 9 }, 2).cut, 0)
  assert.equal(residualLevels({ pass: -3 }, 2).cut, 1)
})

test('bandComplement: 已收矩形的补集仍是矩形, 收满则为 null', () => {
  const uv = plainUv()   // 必须带 loosen/clear 前沿声明, 否则 scrapeRects 会退到 +dir 默认
  // clear 走 −u: 从高端往回吃, 补集顶在低端
  const half = scrapeRects(uv, 0, 0.5).clear
  assert.deepEqual(half, { u0: 0.5, v0: 0.4, u1: 0.9, v1: 0.5 }, '已收段顶在高端')
  assert.deepEqual(bandComplement(uv, half), { u0: 0.1, v0: 0.4, u1: 0.5, v1: 0.5 })
  assert.equal(bandComplement(uv, scrapeRects(uv, 0, 1).clear), null, '收满没有补集')
  assert.deepEqual(bandComplement(uv, null),
    { u0: uv.u0, v0: uv.v0, u1: uv.u1, v1: uv.v1 }, '还没开收 = 整条带')
})

test('uvRectToLocal: UV→板局部 —— u 随 +x 增, v 随 +z 减(BoxGeometry 顶面实测)', () => {
  // 整幅 UV = 整块板
  assert.deepEqual(uvRectToLocal({ u0: 0, v0: 0, u1: 1, v1: 1 }, 0.2, 0.2),
    { x: 0, z: 0, width: 0.2, length: 0.2 })
  // u 高端 → +x
  assert.equal(uvRectToLocal({ u0: 0.5, v0: 0, u1: 1, v1: 1 }, 0.2, 0.2).x, 0.05)
  // v 高端 → −z(取反是本函数唯一的符号推理, 由 three BoxGeometry 顶面 UV 实测钉死)
  assert.equal(uvRectToLocal({ u0: 0, v0: 0.5, u1: 1, v1: 1 }, 0.2, 0.2).z, -0.05)
  assert.equal(uvRectToLocal({ u0: 0.2, v0: 0, u1: 0.2, v1: 1 }, 0.2, 0.2), null, '零宽不画')
})

// ── 痕迹层扩展(spot/wet/实际刀路) ──────────────────────────────────────────

test('machineDirsWorld: 轴 id 可换(点样座 6X/7Y), 标定方向 xDir/yDir 参与符号', () => {
  // 复用 makeAxes 的场景但把 manifest 轴 id 换成点样座的
  const { manifest, resolve } = makeAxes()
  manifest.axes[0].id = 'axis_6x'
  manifest.axes[1].id = 'axis_7y'
  const dirs = machineDirsWorld(manifest, resolve, { xAxis: 'axis_6x', yAxis: 'axis_7y' })
  close(dirs.xCm, [1, 0, 0], '6X 载喷射头, 顺轴向')
  close(dirs.yCm, [0, 0, -1], '7Y 载点样座(板), 取反 —— 与 8Y 同一条"板动刀不动"推理')
  const flipped = machineDirsWorld(manifest, resolve,
    { xAxis: 'axis_6x', yAxis: 'axis_7y', xDir: -1, yDir: -1 })
  close(flipped.xCm, [-1, 0, 0], 'xDir=-1 翻转 cm x')
  close(flipped.yCm, [0, 0, 1], 'yDir=-1 再翻一次 cm y')
})

test('gravityDirsWorld: 竖直板 +y_cm=世界上方向投影, x 由右手系+粉面法线钉死', () => {
  // 板绕 X 转 -90°: 局部 +Y(法线) → 世界 −Z(板"竖插", 面朝 −Z)
  const quat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 2)
  const dirs = gravityDirsWorld(quat, true)
  close(dirs.yCm, [0, 1, 0], '+y_cm 应指世界上方')
  // n̂=−Z(世界), ŷ=+Y ⇒ x̂ = ŷ×n̂ = −X(从粉面那侧看过去 x 向右)
  close(dirs.xCm, [-1, 0, 0], '+x_cm 由右手系补全')
  // 粉面朝另一侧(silicaUp=false → n̂=−局部Y→世界+Z)时 x 镜像
  const flipped = gravityDirsWorld(quat, false)
  close(flipped.xCm, [1, 0, 0], '粉面反侧, x 镜像')
  close(flipped.yCm, [0, 1, 0], 'y 仍指上')
})

test('gravityDirsWorld: 板近水平时拒画(留白纪律)', () => {
  assert.equal(gravityDirsWorld(new THREE.Quaternion(), true), null, '躺平的板没有重力锚定')
  // 斜 45° 的板仍可锚定(缸内板有小倾角)
  const tilted = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -Math.PI / 4)
  assert.ok(gravityDirsWorld(tilted, true), '45° 斜插仍应给出方向')
})

test('bandToUv: region.fill 换算成 UV 前沿(带出 fill 键), 不声明则不带', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  const quat = new THREE.Quaternion()
  const withFill = bandToUv(
    { plateSizeCm: [20, 20], bandCm: [2, 8, 18, 10], fill: { axis: 'x', dir: 1 } }, quat, dirs)
  assert.ok(withFill.fill, 'fill 声明应换算带出')
  assert.equal(withFill.fill.coord, 'u')
  const without = bandToUv({ plateSizeCm: [20, 20], bandCm: [2, 8, 18, 10] }, quat, dirs)
  assert.equal(without.fill, undefined)
})

test('progressRect: 按前沿方向裁子矩形, 0 进度不画、满进度整幅', () => {
  const rect = { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5 }
  assert.equal(progressRect(rect, { coord: 'u', dir: 1 }, 0), null)
  assert.deepEqual(progressRect(rect, { coord: 'u', dir: 1 }, 1), rect)
  assert.deepEqual(progressRect(rect, { coord: 'u', dir: 1 }, 0.5),
    { u0: 0.1, v0: 0.4, u1: 0.5, v1: 0.5 }, '+u 前沿从低端起步')
  assert.deepEqual(progressRect(rect, { coord: 'u', dir: -1 }, 0.5),
    { u0: 0.5, v0: 0.4, u1: 0.9, v1: 0.5 }, '−u 前沿从高端起步')
  assert.deepEqual(progressRect(rect, { coord: 'v', dir: 1 }, 0.5),
    { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.45 }, 'v 向前沿')
})

// ── progressStroke: 点样色带的"圆点滑过"轨迹 ───────────────────────────────
// 与 progressRect 的不变量对齐: 0 进度不画、满进度不越界、front 缺省时两者可互换。
// 厚度那一维是**垂直于前沿**的跨度, 圆点中心走 [lo+r, hi−r] —— 这两条是"圆帽外沿恰好
// 贴住带端"的全部依据, 算错了画面照样像条带, 只是悄悄画到 bandCm 外面去。
const STROKE_RECT = { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5 }

/** 点列近似比较 —— 这里钉的是几何, 不该被 0.1+0.05 的浮点尾差判红。 */
function assertPoints(seg, expected, message) {
  assert.ok(seg, `${message}: 不该留白`)
  assert.equal(seg.points.length, expected.length, message)
  seg.points.forEach((point, i) => {
    assert.ok(Math.abs(point.u - expected[i][0]) < 1e-9 && Math.abs(point.v - expected[i][1]) < 1e-9,
      `${message}: 第 ${i} 点 (${point.u}, ${point.v}) ≠ (${expected[i][0]}, ${expected[i][1]})`)
  })
}

test('progressStroke: 圆点中心两端各内缩半个厚度, 满进度恰好铺满不越界', () => {
  const full = progressStroke(STROKE_RECT, { coord: 'u', dir: 1 }, 1)
  assert.ok(Math.abs(full.widthUv - 0.1) < 1e-9, '厚度取垂直于前沿的那一维(v 跨度)')
  assertPoints(full, [[0.15, 0.45], [0.85, 0.45]], '中心线走 [u0+r, u1−r], 中心 v 居中')
  // 圆帽外沿 = 端点 ± r, 正好落在原矩形两端 —— 这才是"bandCm 仍等于实绘包络"的依据
  assert.ok(Math.abs((full.points[0].u - full.widthUv / 2) - STROKE_RECT.u0) < 1e-9)
  assert.ok(Math.abs((full.points[1].u + full.widthUv / 2) - STROKE_RECT.u1) < 1e-9)
})

test('progressStroke: 进度 0 不画; 起手是一个零长圆点(两端重合)', () => {
  assert.equal(progressStroke(STROKE_RECT, { coord: 'u', dir: 1 }, 0), null, '0 进度留白')
  assert.equal(progressStroke(null, { coord: 'u', dir: 1 }, 0.5), null, '无 rect 留白')
  const seed = progressStroke(STROKE_RECT, { coord: 'u', dir: 1 }, 1e-9)
  assertPoints(seed, [[0.15, 0.45], [0.15, 0.45]],
    '刚起手时两点重合于 u0+r = 画一个圆点(而不是贴着 u0 的细缝)')
})

test('progressStroke: 半程与反向 —— dir=−1 从高端往回滑', () => {
  assertPoints(progressStroke(STROKE_RECT, { coord: 'u', dir: 1 }, 0.5),
    [[0.15, 0.45], [0.5, 0.45]], '行程是 [u0+r, u1−r] 的一半, 不是带长的一半')
  assertPoints(progressStroke(STROKE_RECT, { coord: 'u', dir: -1 }, 0.5),
    [[0.85, 0.45], [0.5, 0.45]], '−u 从高端起步')
})

test('progressStroke: v 向前沿 / front 缺省 / rect 反序', () => {
  const along = progressStroke({ u0: 0.4, v0: 0.1, u1: 0.5, v1: 0.9 },
    { coord: 'v', dir: 1 }, 1)
  assert.ok(Math.abs(along.widthUv - 0.1) < 1e-9, '沿 v 时厚度取 u 跨度')
  assertPoints(along, [[0.45, 0.15], [0.45, 0.85]], 'v 向中心线')
  // front 缺省要与 progressRect 逐字同源(沿 u、+向), 否则两者不可互换
  assert.deepEqual(progressStroke(STROKE_RECT, null, 1),
    progressStroke(STROKE_RECT, { coord: 'u', dir: 1 }, 1), 'front 缺省 = 沿 u、+向')
  // 端点反序只是安全网: 跨度与次序无关, 不归一会算出负线宽
  assert.deepEqual(progressStroke({ u0: 0.9, v0: 0.5, u1: 0.1, v1: 0.4 }, null, 1),
    progressStroke(STROKE_RECT, null, 1), '反序的 rect 与正序等价')
})

test('progressStroke: 带长短于带厚时厚度收到带长(圆点不许画出带外)', () => {
  const stub = progressStroke({ u0: 0.40, v0: 0.3, u1: 0.44, v1: 0.5 },
    { coord: 'u', dir: 1 }, 1)
  assert.ok(Math.abs(stub.widthUv - 0.04) < 1e-9, '厚度 = min(垂直跨度, 沿轴跨度)')
  assertPoints(stub, [[0.42, 0.4], [0.42, 0.4]], '退化成正中一个圆点')
  assert.equal(progressStroke({ u0: 0.2, v0: 0.4, u1: 0.2, v1: 0.5 }, null, 1), null,
    '零跨度是脏数据, 留白')
})

test('pathToUv: 折线与 bandToUv 同一套仿射(角点互证), 越界/非法点拒画', () => {
  const { manifest, resolve } = makeAxes()
  const dirs = machineDirsWorld(manifest, resolve)
  const quat = new THREE.Quaternion()
  // 板 cm (0,0)(左下角) 与 (20,20)(右上角) 应映射到与整板矩形一致的两角
  const frame = bandToUv({ plateSizeCm: [20, 20], bandCm: [0, 0, 20, 20] }, quat, dirs)
  const path = pathToUv([[0, 0], [20, 20]], [20, 20], quat, dirs)
  assert.ok(path, '正对机床的板应可映射')
  const us = path.points.map((p) => p.u).sort((a, b) => a - b)
  const vs = path.points.map((p) => p.v).sort((a, b) => a - b)
  assert.ok(Math.abs(us[0] - frame.u0) < 1e-9 && Math.abs(us[1] - frame.u1) < 1e-9, 'u 两端对齐整板')
  assert.ok(Math.abs(vs[0] - frame.v0) < 1e-9 && Math.abs(vs[1] - frame.v1) < 1e-9, 'v 两端对齐整板')
  assert.equal(pathToUv([[0, 0]], [20, 20], quat, dirs), null, '单点不是折线')
  assert.equal(pathToUv([[0, 0], [NaN, 1]], [20, 20], quat, dirs), null, '脏点整条拒画')
})

/** 记录式画布(与 plateFaceLayer.test.js 的 stub 同构, 多支持折线描边)。 */
function recordCanvas(size = 512) {
  const ops = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    lineCap: '',
    lineJoin: '',
    globalCompositeOperation: 'source-over',
    fillRect(x, y, w, h) { ops.push({ op: 'fill', style: this.fillStyle, x, y, w, h }) },
    clearRect(x, y, w, h) { ops.push({ op: 'clear', x, y, w, h }) },
    beginPath() { ops.push({ op: 'begin' }) },
    moveTo(x, y) { ops.push({ op: 'move', x, y }) },
    lineTo(x, y) { ops.push({ op: 'line', x, y }) },
    stroke() {
      ops.push({
        op: 'stroke',
        mode: this.globalCompositeOperation,
        width: this.lineWidth,
        style: this.strokeStyle,
        cap: this.lineCap,
      })
    },
  }
  return { width: size, height: size, ops, getContext: () => ctx }
}

test('drawTrace: 次序=白底→色带→润湿→刮松→收粉擦除→刀路擦除(工艺次序)', () => {
  const canvas = recordCanvas()
  drawTrace(canvas, {
    spotRects: [{ u0: 0.1, v0: 0.1, u1: 0.9, v1: 0.15 }],
    spotStrokes: [{ points: [{ u: 0.1, v: 0.3 }, { u: 0.5, v: 0.3 }], widthUv: 0.05 }],
    wetRect: { u0: 0, v0: 0, u1: 1, v1: 0.7 },
    wetFront: { coord: 'v', at: 0.7 },
    loosen: { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5 },
    clear: { u0: 0.1, v0: 0.4, u1: 0.5, v1: 0.5 },
    path: { points: [{ u: 0.2, v: 0.45 }, { u: 0.8, v: 0.45 }], widthUv: 0.01 },
  })
  const fills = canvas.ops.filter((op) => op.op === 'fill').map((op) => op.style)
  assert.equal(fills[0], '#ffffff', '第一笔永远是白底')
  assert.equal(fills[1], SPOT_BAND_FILL, '实测谱带矩形在白底之上')
  assert.equal(fills[2], WET_FILL, '润湿罩在色带之上')
  assert.ok(fills.includes(SCRAPE_LOOSEN_FILL), '刮松灰在润湿之后')
  // 扫线色带走圆帽描边, 夹在"实测谱带矩形"与"润湿罩"之间
  const bandStroke = canvas.ops.find((op) => op.op === 'stroke' && op.style === SPOT_BAND_FILL)
  assert.ok(bandStroke, '扫线色带以描边落笔')
  assert.equal(bandStroke.mode, 'source-over', '色带只动 RGB, 绝不碰 alpha')
  assert.equal(bandStroke.cap, 'round', '圆帽 —— 这就是"圆点滑过"的观感来源')
  assert.ok(Math.abs(bandStroke.width - 0.05 * canvas.width) < 1e-9, '线宽=带厚×画布')
  const bandStrokeIdx = canvas.ops.indexOf(bandStroke)
  const wetIdx = canvas.ops.findIndex((op) => op.op === 'fill' && op.style === WET_FILL)
  assert.ok(bandStrokeIdx < wetIdx, '色带描边要排在润湿罩之前')
  const clearIdx = canvas.ops.findIndex((op) => op.op === 'clear')
  const cutIdx = canvas.ops.findIndex((op) => op.op === 'stroke' && op.mode === 'destination-out')
  assert.ok(clearIdx > 0 && cutIdx > clearIdx, '擦除类(收粉/刀路)最后画')
  const stroke = canvas.ops[cutIdx]
  assert.equal(stroke.mode, 'destination-out', '刀路以擦除模式描边(露玻璃)')
  assert.ok(Math.abs(stroke.width - 0.01 * canvas.width) < 1e-9, '线宽=刀宽×画布')
})

test('drawScrape 兼容入口: 等价于 drawTrace 只带刮取两层', () => {
  const a = recordCanvas()
  const b = recordCanvas()
  const loosen = { u0: 0.1, v0: 0.4, u1: 0.9, v1: 0.5 }
  drawScrape(a, { loosen, clear: null })
  drawTrace(b, { loosen, clear: null })
  assert.deepEqual(a.ops, b.ops)
})

test('drawWetRoughness: 白底 G=1, 湿区中灰; 无湿区=全白', () => {
  const wet = recordCanvas(256)
  drawWetRoughness(wet, { u0: 0, v0: 0, u1: 1, v1: 0.5 })
  assert.equal(wet.ops[0].style, '#ffffff')
  assert.equal(wet.ops[1].style, '#8f8f8f')
  const dry = recordCanvas(256)
  drawWetRoughness(dry, null)
  assert.equal(dry.ops.length, 1, '全干只画白底')
})

test('troughDirsWorld: 卧式缸的槽向锚定 —— +y_cm 背离槽心, 平躺的板也能锚', () => {
  // 平躺的板(绕 Y 转 180°, 与缸位锚点实测同构), 粉面朝下(silicaUp=false → n̂=−Y)
  const quat = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI)
  assert.equal(gravityDirsWorld(quat, false), null, '平躺的板重力锚定必然退化')
  const dirs = troughDirsWorld(quat, [0, 1, 0.4], [0, 1, 0.55], false)
  close(dirs.yCm, [0, 0, -1], '+y_cm 应从槽指向板心(水平)')
  // n̂=(0,−1,0), ŷ=(0,0,−1) ⇒ x̂ = ŷ×n̂ = (0,0,−1)×(0,−1,0) = (−1,0,0)
  close(dirs.xCm, [-1, 0, 0], '+x_cm 由右手系补全')
  // 槽心与板心几乎重合(数据不对)→ 留白
  assert.equal(troughDirsWorld(quat, [0, 1, 0.4], [0, 1, 0.401], false), null)
})
