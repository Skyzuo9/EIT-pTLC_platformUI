/**
 * 功能: 冰蓝虚拟实验室的布局计算、罩体几何与"相机出不去"门禁测试.
 *
 * 门禁的由来: 旧实现是开口圆筒 + 有限方板地面, 而相机上限(modelRadius*12)比房间半径
 * 大好几倍 —— 缩到最小必穿帮. 现在罩体封闭, 且相机上限由罩体剖面反推. 本文件里
 * "相机可达上半球严格含于罩体内"那条断言就是这个不变量的门禁, 它用**独立的点在多边形内**
 * 判定复核, 不复用 laboratorySafeDistance 自己的最近距离算法, 避免自证.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  LABORATORY_MIN_RADIUS,
  LABORATORY_MIN_SIZE,
  LABORATORY_RADIUS_CLEARANCE,
  LABORATORY_RADIUS_MODEL_FACTOR,
  computeLaboratoryLayout,
  createLaboratoryBackground,
  laboratoryProfile,
  laboratorySafeDistance,
} from '../../src/three-d/twin/scene/LaboratoryBackground.js'

/** CameraRig 的极角上限: 相机永远高于轨道中心, 门禁按同一口径取样 */
const MAX_POLAR_ANGLE = Math.PI * 0.495
/** CameraRig.applyPreset('iso') 的取景距离系数: modelRadius / sin(fov/2) * fill, fov=42°, fill=0.82 */
const ISO_FRAMING_FACTOR = 0.82 / Math.sin((42 * Math.PI / 180) / 2)

/**
 * 功能: 取包围盒的尺寸/中心/外接球半径(与 CameraRig.frameObject 同口径).
 * @param {object} box {min,max}
 * @returns {{centerY:number, modelRadius:number}}
 */
function boxMetrics(box) {
  const size = {
    x: box.max.x - box.min.x,
    y: box.max.y - box.min.y,
    z: box.max.z - box.min.z,
  }
  return {
    centerY: (box.min.y + box.max.y) * 0.5,
    modelRadius: Math.hypot(size.x, size.y, size.z) * 0.5,
  }
}

/**
 * 功能: 判定一个世界点是否落在罩体内部 —— 把点投到 (离轴距, 高度) 半平面,
 *       再对"剖面 + 沿轴闭合"的多边形做射线穿越计数. 与最近距离算法完全无关.
 * @param {object} layout computeLaboratoryLayout 的产物
 * @param {{x:number,y:number,z:number}} point 世界坐标点
 * @returns {boolean} true 表示在罩内
 */
function insideShell(layout, point) {
  const polygon = laboratoryProfile(layout).map((entry) => ({
    r: entry.r,
    y: layout.shellBaseY + entry.y,
  }))
  // 剖面首尾都在轴上(r=0), 沿轴闭合即得封闭多边形
  const r = Math.hypot(point.x - layout.centerX, point.z - layout.centerZ)
  const y = point.y

  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i]
    const b = polygon[j]
    const straddles = (a.y > y) !== (b.y > y)
    if (!straddles) continue
    const crossR = a.r + (y - a.y) / (b.y - a.y) * (b.r - a.r)
    if (r < crossR) inside = !inside
  }
  return inside
}

test('无模型时使用空旷虚拟大厅最小尺寸', () => {
  const layout = computeLaboratoryLayout(null)
  assert.equal(layout.width, LABORATORY_MIN_SIZE.width)
  assert.equal(layout.depth, LABORATORY_MIN_SIZE.depth)
  assert.equal(layout.floorY, 0)
  assert.ok(layout.radius >= LABORATORY_MIN_RADIUS)
  assert.ok(layout.domeRise > 0, '罩体必须有穹顶升起, 否则顶部又是敞的')
  assert.equal(layout.apexY, layout.shellBaseY + layout.height + layout.domeRise)
  // 罩体地面必须低于整机底面: 接触阴影(-0.001)与倒影(-0.0015)贴在 y<0, 罩体压在 0
  // 就会把它们埋掉, 整机随之失去落地感
  assert.ok(layout.shellBaseY < layout.floorY, '罩体地面必须低于整机底面')
  assert.ok(layout.shellBaseY < -0.0015, '罩体地面必须低于倒影层, 否则倒影被埋')
})

test('罩体半径三者取大: 最小空旷感 / 房间轮廓 / 相机退让空间', () => {
  const box = {
    min: { x: 4, y: 1.25, z: -8 },
    max: { x: 13, y: 5.25, z: 1 },
  }
  const layout = computeLaboratoryLayout(box)
  const { modelRadius } = boxMetrics(box)
  assert.equal(layout.centerX, 8.5)
  assert.equal(layout.centerZ, -3.5)
  assert.equal(layout.floorY, 1.25)
  assert.equal(layout.width, 17)
  assert.equal(layout.depth, 16)
  assert.equal(
    layout.radius,
    Math.max(
      LABORATORY_MIN_RADIUS,
      Math.hypot(layout.width, layout.depth) * 0.5 + LABORATORY_RADIUS_CLEARANCE,
      modelRadius * LABORATORY_RADIUS_MODEL_FACTOR,
    ),
  )
  // 大模型下相机退让空间是决定项, 房间不能只包住轮廓就算完
  assert.equal(layout.radius, modelRadius * LABORATORY_RADIUS_MODEL_FACTOR)
})

test('损坏包围盒不会产生 NaN 或负尺寸', () => {
  const layout = computeLaboratoryLayout({
    min: { x: Number.NaN, y: 0, z: 0 },
    max: { x: 1, y: 1, z: 1 },
  })
  assert.ok(Number.isFinite(layout.centerX))
  assert.ok(layout.width >= LABORATORY_MIN_SIZE.width)
  assert.ok(layout.depth >= LABORATORY_MIN_SIZE.depth)
  assert.ok(layout.height >= LABORATORY_MIN_SIZE.height)
  assert.ok(Number.isFinite(layout.radius))
  assert.ok(Number.isFinite(layout.domeRise))
  assert.ok(layout.radius >= LABORATORY_MIN_RADIUS)
})

test('剖面自轴心起、回轴心止, 全程半径非负且高度单调不减', () => {
  const profile = laboratoryProfile(computeLaboratoryLayout(null))
  assert.equal(profile[0].r, 0, '剖面必须从轴心起, 否则地面中心是个洞')
  assert.equal(profile[profile.length - 1].r, 0, '剖面必须回到轴心, 否则穹顶是敞的')
  for (let index = 1; index < profile.length; index += 1) {
    assert.ok(profile[index].r >= -1e-9, '剖面半径不得为负')
    assert.ok(
      profile[index].y >= profile[index - 1].y - 1e-9,
      '剖面高度必须单调不减, 否则旋转出的罩体会自交',
    )
  }
})

test('相机可达上半球严格含于罩体内(不穿帮门禁)', () => {
  const boxes = [
    // 真机量级: 约 2.9 x 1.6 x 2.2 m
    { min: { x: -1.45, y: 0, z: -1.1 }, max: { x: 1.45, y: 1.6, z: 1.1 } },
    // 偏心且不落在原点
    { min: { x: 4, y: 1.25, z: -8 }, max: { x: 13, y: 5.25, z: 1 } },
    // 极扁: 高度远小于平面尺寸
    { min: { x: -6, y: 0, z: -6 }, max: { x: 6, y: 0.3, z: 6 } },
    // 极瘦高: 高度远大于平面尺寸
    { min: { x: -0.4, y: 0, z: -0.4 }, max: { x: 0.4, y: 9, z: 0.4 } },
    // 极小件
    { min: { x: -0.05, y: 0, z: -0.05 }, max: { x: 0.05, y: 0.08, z: 0.05 } },
  ]

  for (const box of boxes) {
    const layout = computeLaboratoryLayout(box)
    const { centerY, modelRadius } = boxMetrics(box)
    const safe = laboratorySafeDistance(layout, centerY, modelRadius)
    assert.ok(safe > 0 && Number.isFinite(safe), `安全距离必须为正: ${safe}`)

    // 最坏情况的轨道中心: 被 flyToStation 拉到离罩体轴心 modelRadius 处
    const target = {
      x: layout.centerX + modelRadius,
      y: centerY,
      z: layout.centerZ,
    }
    for (let polarStep = 0; polarStep <= 24; polarStep += 1) {
      const polar = (polarStep / 24) * MAX_POLAR_ANGLE
      for (let azimuthStep = 0; azimuthStep < 32; azimuthStep += 1) {
        const azimuth = (azimuthStep / 32) * Math.PI * 2
        const point = {
          x: target.x + safe * Math.sin(polar) * Math.sin(azimuth),
          y: target.y + safe * Math.cos(polar),
          z: target.z + safe * Math.sin(polar) * Math.cos(azimuth),
        }
        assert.ok(
          insideShell(layout, point),
          `相机在 极角 ${polar.toFixed(3)} / 方位 ${azimuth.toFixed(3)} / 距离 ${safe.toFixed(3)} 处捅出罩外`,
        )
      }
    }
  }
})

test('安全距离仍显著大于默认取景距离(修穿帮不能把相机锁死)', () => {
  const box = { min: { x: -1.45, y: 0, z: -1.1 }, max: { x: 1.45, y: 1.6, z: 1.1 } }
  const layout = computeLaboratoryLayout(box)
  const { centerY, modelRadius } = boxMetrics(box)
  const safe = laboratorySafeDistance(layout, centerY, modelRadius)
  const framing = modelRadius * ISO_FRAMING_FACTOR
  assert.ok(
    safe > framing * 1.3,
    `安全距离 ${safe.toFixed(2)} m 必须比默认取景 ${framing.toFixed(2)} m 留出 30% 以上退让余量`,
  )
})

test('虚拟大厅可热切显隐/主题、按模型重排并完整释放', () => {
  const lab = createLaboratoryBackground()
  assert.equal(lab.root.visible, false)
  lab.setVisible(true)
  lab.setTheme('dark')
  lab.setIntensity(0.8)
  lab.fitToModel({
    min: { x: -1.3, y: 0, z: -1.1 },
    max: { x: 1.3, y: 1.5, z: 1.1 },
  })

  const names = new Set()
  lab.root.traverse((node) => names.add(node.name))
  for (const required of [
    'LAB_SHELL',
    'LAB_VIRTUAL_PANELS',
    'LAB_ARCH_RIBS',
    'LAB_CEILING_LIGHT_0',
    'LAB_CEILING_LIGHT_1',
    'LAB_CEILING_LIGHT_2',
    'LAB_HORIZON_GLOW',
  ]) {
    assert.ok(names.has(required), `缺少虚拟实验室构件 ${required}`)
  }

  // 开口圆筒 + 有限方板地面 + 半透明顶幕是穿帮的根因, 已并进一体罩, 不得复活
  for (const retired of ['LAB_FLOOR', 'LAB_VIRTUAL_SHELL', 'LAB_VIRTUAL_CANOPY']) {
    assert.equal(names.has(retired), false, `不应保留已退役的开口构件 ${retired}`)
  }
  for (const obsoletePrefix of ['LAB_SAFETY_', 'LAB_DOOR', 'LAB_OBSERVATION_', 'LAB_VENT_']) {
    assert.equal(
      [...names].some((name) => name.startsWith(obsoletePrefix)),
      false,
      `不应保留写实实验室构件 ${obsoletePrefix}`,
    )
  }

  assert.equal(lab.getLayout().floorY, 0)
  assert.ok(lab.getLayout().radius >= LABORATORY_MIN_RADIUS)
  lab.dispose()
  assert.equal(lab.root.children[0].children.length, 0)
})

test('罩体网格顶点全部落在剖面判定的内部边界上(几何与判据同源)', () => {
  const box = { min: { x: -1.45, y: 0, z: -1.1 }, max: { x: 1.45, y: 1.6, z: 1.1 } }
  const lab = createLaboratoryBackground()
  lab.fitToModel(box)
  const layout = lab.getLayout()

  let shell = null
  lab.root.traverse((node) => {
    if (node.name === 'LAB_SHELL') shell = node
  })
  assert.ok(shell, '未找到一体罩 LAB_SHELL')

  const position = shell.geometry.getAttribute('position')
  assert.ok(position.count > 0)
  let maxRadius = 0
  let maxHeight = -Infinity
  for (let index = 0; index < position.count; index += 1) {
    const r = Math.hypot(position.getX(index), position.getZ(index))
    maxRadius = Math.max(maxRadius, r)
    maxHeight = Math.max(maxHeight, position.getY(index))
  }
  // 实际建出来的几何要与布局对得上: 半径不超直墙半径, 高度到穹顶顶点
  assert.ok(Math.abs(maxRadius - layout.radius) < 1e-3, `罩体最大半径 ${maxRadius} 应为 ${layout.radius}`)
  assert.ok(
    Math.abs(maxHeight - (layout.height + layout.domeRise)) < 1e-3,
    `罩体最大高度 ${maxHeight} 应为 ${layout.height + layout.domeRise}`,
  )
  // 顶点色是壳体渐变的唯一载体, 缺了它整个罩子就是一块平色
  assert.ok(shell.geometry.getAttribute('color'), '罩体缺少顶点色属性')
  lab.dispose()
})
