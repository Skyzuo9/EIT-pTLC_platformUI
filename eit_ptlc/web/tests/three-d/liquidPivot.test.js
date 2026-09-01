/**
 * 功能: 液面/液柱"缩放 + 枢轴补偿"的单元测试(twin/bindings/liquidPivot.js).
 *
 * 本模块被**两条链**共用(实时链 TwinBindings._updateTanks/_updatePumps 与离线链
 * MachineStateDriver.setLiquidMl), 所以这里验的是补偿本身; 离线链真的在调它、
 * 且与实时链逐位相同, 由 liquidChannel.test.js 那几条锁住.
 *
 * 为什么这一层必须单测, 而不是靠肉眼验收:
 *   1. **枢轴位置不是我们说了算的.** Blender 侧把液柱枢轴设在底面, 但 04_optimize.mjs 的
 *      `quantize({quantizePosition: 14})` 会把每个网格归一化到"以原点为中心的单位立方",
 *      再把偏移推到节点 TRS 上 —— 出厂 GLB 里 11 个 LIQUID 节点的枢轴**全部**落在几何
 *      中心(实测 origin/span = 0.500). 于是 scale.y 是朝中心收缩, 不是自底往上涨:
 *      半程时液柱底悬空 15mm、顶端插进柱塞头 15mm, 正是 2026-08-05 用户截图里的两个 bug.
 *   2. **补偿公式必须对两种枢轴都成立.** 所以这里用两个桩分别断言: 枢轴在中心(出厂现状)
 *      与枢轴在底面(优化器哪天改了行为). 后者的补偿量恒为 0 —— 这条是"将来别再坏"的锚.
 *
 * 断言的判据一律是**世界底面坐标恒定**, 而不是"position 等于某个数" —— 后者换个枢轴就红,
 * 前者才是我们真正要的性质.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import {
  LIQUID_EMPTY_FACTOR, applyLiquidLevel, captureLiquidBase, measureLiquidPivot,
} from '../../src/three-d/twin/bindings/liquidPivot.js'

/** 液柱在泵局部系里的真实尺寸(mm→m): Ø22 × 60 行程 */
const SPAN = 0.06

/**
 * 功能: 造一个液面节点. pivot='center' 复刻出厂 GLB(quantize 之后), 'base' 是 Blender 原状.
 *
 * 刻意用 BufferGeometry 而不是 Mesh 的 boundingBox 捷径 —— measureLiquidPivot 走的是
 * traverse + 顶点包围盒, 桩必须让它真的算一遍.
 *
 * @param {'center'|'base'} pivot 枢轴位置
 * @returns {THREE.Mesh} 液面网格
 */
function makeLiquid(pivot) {
  const geom = new THREE.BoxGeometry(0.022, SPAN, 0.022)
  if (pivot === 'base') geom.translate(0, SPAN / 2, 0)
  const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial())
  mesh.name = 'LIQUID_PUMP_SMP'
  return mesh
}

/**
 * 功能: 建一个与 _bindPumps/_bindTanks/_bindLiquids 同形的 entry.
 *
 * 直接用出厂那只采集器而不是自己拼三个字段 —— 这样断言的 entry 形状就是三个绑定点
 * 真正拿到的形状, 又多一道锁.
 */
function makeEntry(node) {
  return captureLiquidBase(node)
}

/** 功能: 取节点缩放后的世界底面 y */
function worldBottomY(node) {
  node.updateMatrixWorld(true)
  return new THREE.Box3().setFromObject(node).min.y
}

test('出厂枢轴(几何中心)下, 液面底恒定不动 —— 修的就是"凭空从中间消失"', () => {
  const node = makeLiquid('center')
  assert.ok(Math.abs(measureLiquidPivot(node) + SPAN / 2) < 1e-6,
    '中心枢轴的 baseMinY 应为 -span/2')

  const entry = makeEntry(node)
  applyLiquidLevel(entry, node, 1)
  const full = worldBottomY(node)

  for (const level of [0.75, 0.5, 0.25, 0.05]) {
    applyLiquidLevel(entry, node, level)
    // 判据取 1e-6 m(1 微米): 顶点是 float32, 再细就是在测浮点噪声不是测逻辑
    assert.ok(Math.abs(worldBottomY(node) - full) < 1e-6,
      `level=${level} 时底面漂了 ${((worldBottomY(node) - full) * 1000).toFixed(2)}mm`)
  }
})

test('液面高度随 level 线性, 且顶面单调下降(不是两头一起缩)', () => {
  const node = makeLiquid('center')
  const entry = makeEntry(node)
  let lastTop = Infinity
  for (const level of [1, 0.75, 0.5, 0.25]) {
    applyLiquidLevel(entry, node, level)
    node.updateMatrixWorld(true)
    const box = new THREE.Box3().setFromObject(node)
    assert.ok(Math.abs((box.max.y - box.min.y) - SPAN * level) < 1e-6,
      `level=${level} 高度应为 ${SPAN * level}, 实际 ${box.max.y - box.min.y}`)
    assert.ok(box.max.y < lastTop, '顶面必须单调下降')
    lastTop = box.max.y
  }
})

test('枢轴在底面时补偿量恒为 0 —— 优化器哪天不再 quantize 也不会坏', () => {
  const node = makeLiquid('base')
  // 不用 assert.equal(..., 0): geom.translate 后顶点仍是 float32, 底面落在 ±1e-9 而非精确 0
  assert.ok(Math.abs(measureLiquidPivot(node)) < 1e-6, '底面枢轴的 baseMinY 应约为 0')

  const entry = makeEntry(node)
  const before = node.position.clone()
  for (const level of [1, 0.5, 0.1]) {
    applyLiquidLevel(entry, node, level)
    assert.ok(node.position.distanceTo(before) < 1e-6,
      '底面枢轴不该被平移, 否则等于补偿了两次')
  }
})

test('level=0 不塌成零缩放(法线退化会出黑面), 但底面仍不动', () => {
  const node = makeLiquid('center')
  const entry = makeEntry(node)
  applyLiquidLevel(entry, node, 1)
  const full = worldBottomY(node)

  applyLiquidLevel(entry, node, 0)
  assert.equal(node.scale.y, entry.baseScale.y * LIQUID_EMPTY_FACTOR,
    'level=0 应钳到 LIQUID_EMPTY_FACTOR 而不是 0')
  assert.ok(Math.abs(worldBottomY(node) - full) < 1e-6, 'level=0 时底面也必须钉住')
  // 下限只保住法线, 保不住观感: 压扁的盒子顶面仍是满尺寸, 所以"看不见"由
  // applyLiquidVisible 另管一路 —— 见 liquidChannel.test.js 的空缸隐藏用例
})

test('节点带旋转时, 补偿沿节点自身 +Y 而不是世界 +Y', () => {
  const node = makeLiquid('center')
  // 绕 +Z 转 90°: 局部 +Y -> 世界 -X, 所以液柱的**底面**(局部 -Y 那面)落到世界 +X.
  // 该钉住的是 max.x —— 写 min.x 会盯住顶面, 那面本来就该动.
  node.rotation.z = Math.PI / 2
  const entry = makeEntry(node)
  applyLiquidLevel(entry, node, 1)
  node.updateMatrixWorld(true)
  const fullMaxX = new THREE.Box3().setFromObject(node).max.x

  applyLiquidLevel(entry, node, 0.25)
  node.updateMatrixWorld(true)
  assert.ok(Math.abs(new THREE.Box3().setFromObject(node).max.x - fullMaxX) < 1e-6,
    '躺倒后"底面"是世界 +X 面, 它才是该钉住的那一面')
})
