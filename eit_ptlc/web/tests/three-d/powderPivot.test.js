/**
 * 功能: 粉柱落点与体积换算的单元测试(twin/bindings/powderPivot.js).
 *
 * 本模块要被**两条链**共用(实时链 TwinBindings 与离线链 MachineStateDriver 的 powder
 * 通道), 与 liquidPivot 同一处境, 所以这里验的是数学性质本身。
 *
 * 断言的判据一律是**不变量**(占位区间上端恒等于 c1 / 恒在腔内 / 世界底面等于 y0),
 * 而不是"position 等于某个数" —— 后者换个枢轴或换个腔长就红, 前者才是真正要的性质。
 *
 * 三条最要紧的:
 *   1. **粉恒定贴 c1 端.** 粉被滤纸内衬拦在吹气头那一头, 桶翻不翻都不动 —— 落点因此
 *      **不吃任何姿态输入**。2026-08-13 之前这里是一套重力+休止角的滑动模型, 连同那条
 *      "不许 90° 突跳"的 400 点看门狗一起删掉了。
 *   2. **永不穿出腔外.** 由 powderBaseAxial 的构造保证(占位区间恒为 [c1-h, c1]),
 *      在 level 上逐点验。桶壁 alpha 0.64 是半透明的, 穿出去一眼就看见。
 *   3. **枢轴补偿对两种枢轴都成立.** 与 liquidPivot.test.js 同款双桩: 出厂 GLB 的
 *      quantize 会把枢轴挪到几何正中, 而 Blender 原状在底面。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { captureLiquidBase } from '../../src/three-d/twin/bindings/liquidPivot.js'
import {
  applyPowderColumn, contentAmount, levelFromMm3, powderBaseAxial,
} from '../../src/three-d/twin/bindings/powderPivot.js'

/** 自由粉腔: GLB 实测(径向射线)滤纸内衬孔的等径段, item 局部 Y [+5.0, +78.0]mm = 73mm */
const CHAMBER = { c0: 0.005, c1: 0.078 }
const SPAN = CHAMBER.c1 - CHAMBER.c0

/** 粉桶腔体: 内衬孔 Ø18.4 自由截面 π·9.2² = 265.90mm², 可用深 73mm */
const CAVITY = { usableDepthMm: 73, freeAreaMm2: Math.PI * 9.2 * 9.2 }

/**
 * 功能: 造一个粉柱节点. pivot='center' 复刻出厂 GLB(quantize 之后), 'base' 是 Blender 原状.
 * @param {'center'|'base'} pivot 枢轴位置
 * @returns {THREE.Mesh}
 */
function makePowder(pivot) {
  const geom = new THREE.CylinderGeometry(0.0092, 0.0092, SPAN, 8)
  if (pivot === 'base') geom.translate(0, SPAN / 2, 0)
  const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial())
  mesh.name = 'POWDER_BED_INV_RACK_COLLECTOR_1_ITEM_1'
  return mesh
}

// ---------------------------------------------------------------------------
// powderBaseAxial: 三条恒等式
// ---------------------------------------------------------------------------

test('powderBaseAxial: 占位区间的上端恒等于 c1 —— 粉从吹气头那一头往回长', () => {
  for (let j = 0; j <= 20; j += 1) {
    const level = j / 20
    const y0 = powderBaseAxial(CHAMBER, level)
    assert.ok(Math.abs(y0 + SPAN * level - CHAMBER.c1) < 1e-12,
      `level=${level}: 顶面 ${y0 + SPAN * level} 应恒等于 c1 ${CHAMBER.c1}`)
  }
})

test('powderBaseAxial: 两个端点 —— 空桶退化成零厚贴 c1, 满腔铺满整段', () => {
  assert.ok(Math.abs(powderBaseAxial(CHAMBER, 0) - CHAMBER.c1) < 1e-12)
  assert.ok(Math.abs(powderBaseAxial(CHAMBER, 1) - CHAMBER.c0) < 1e-12)
})

test('powderBaseAxial: 任意粉量, 占位区间恒在腔内(永不穿壁)', () => {
  for (let j = 0; j <= 40; j += 1) {
    const level = j / 40
    const y0 = powderBaseAxial(CHAMBER, level)
    const y1 = y0 + SPAN * level
    assert.ok(y0 >= CHAMBER.c0 - 1e-12, `level=${level}: 底 ${y0} < c0`)
    assert.ok(y1 <= CHAMBER.c1 + 1e-12, `level=${level}: 顶 ${y1} > c1`)
  }
})

test('powderBaseAxial: level 越界按 0/1 夹, 不外推', () => {
  assert.ok(Math.abs(powderBaseAxial(CHAMBER, -3) - CHAMBER.c1) < 1e-12)
  assert.ok(Math.abs(powderBaseAxial(CHAMBER, 7) - CHAMBER.c0) < 1e-12)
})

test('powderBaseAxial: 腔段非法时返回 0 而不是 NaN', () => {
  assert.equal(powderBaseAxial({ c0: 1, c1: 1 }, 0.5), 0)
  assert.equal(powderBaseAxial(null, 0.5), 0)
})

// ---------------------------------------------------------------------------
// levelFromMm3: 与 levelFromMl 同源
// ---------------------------------------------------------------------------

test('levelFromMm3: 1mL = 1000mm³, 且不重写高度公式', () => {
  // 典型带 768.4mm³ 在 Ø18.4 内衬孔里真实堆高 = 768.4 / 265.90 = 2.890mm
  const level = levelFromMm3(CAVITY, 768.4)
  assert.ok(Math.abs(level - 2.890 / 73) < 1e-3, `真实堆高比例 ${level}`)
})

test('levelFromMm3: 观感放大按 ×6 时典型带落在腔深两成半上下, 且不饱和', () => {
  const level = levelFromMm3(CAVITY, 768.4, 6)
  assert.ok(level > 0.15 && level < 0.35, `×6 放大后 ${level} 不在可辨区间`)
  assert.ok(level < 1, '典型单条带不该饱和')
})

test('levelFromMm3: 超量被 clamp 到 1, 几何上不可能溢出腔口', () => {
  assert.equal(levelFromMm3(CAVITY, 1e9, 6), 1)
  assert.equal(levelFromMm3(CAVITY, -5), 0, '负量按空处理')
  assert.equal(levelFromMm3(CAVITY, NaN), 0)
})

// ---------------------------------------------------------------------------
// applyPowderColumn: 复用枢轴补偿, 两种枢轴都成立
// ---------------------------------------------------------------------------

for (const pivot of ['center', 'base']) {
  test(`applyPowderColumn(${pivot} 枢轴): 世界底面恒等于 y0, 顶面恒贴 c1`, () => {
    const node = makePowder(pivot)
    const parent = new THREE.Object3D()
    parent.add(node)
    parent.updateMatrixWorld(true)
    const base = captureLiquidBase(node)

    for (const level of [0.15, 0.4, 0.7, 1]) {
      applyPowderColumn(base, node, CHAMBER, level)
      parent.updateMatrixWorld(true)
      const box = new THREE.Box3().setFromObject(node)
      const expected = powderBaseAxial(CHAMBER, level)
      assert.ok(Math.abs(box.min.y - expected) < 1e-6,
        `level=${level}: 世界底面 ${box.min.y} 应等于 y0 ${expected}`)
      assert.ok(Math.abs(box.max.y - CHAMBER.c1) < 1e-6,
        `level=${level}: 顶面 ${box.max.y} 应恒贴 c1 ${CHAMBER.c1}`)
    }
  })
}

test('applyPowderColumn: 桶翻 180° 时粉的局部落点纹丝不动 —— 粉被内衬拦着, 不随重力滑', () => {
  const holder = new THREE.Object3D()        // 扮 ACTUATOR_PS_ROTATE 下的座位实例
  const node = makePowder('center')
  holder.add(node)
  holder.updateMatrixWorld(true)
  const base = captureLiquidBase(node)

  applyPowderColumn(base, node, CHAMBER, 0.24)
  const upright = { pos: node.position.clone(), scale: node.scale.clone() }

  holder.rotation.set(Math.PI, 0, 0)         // 翻料倒粉那 180°
  holder.updateMatrixWorld(true)
  applyPowderColumn(base, node, CHAMBER, 0.24)

  assert.ok(node.position.distanceTo(upright.pos) < 1e-12, '翻转后粉柱的局部位置漂了')
  assert.ok(node.scale.distanceTo(upright.scale) < 1e-12, '翻转后粉柱的局部缩放漂了')
})

test('applyPowderColumn: 不写 quaternion —— 粉柱与筒同轴, 任意倾角不穿壁', () => {
  const node = makePowder('center')
  node.updateMatrixWorld(true)
  const base = captureLiquidBase(node)
  const before = node.quaternion.clone()
  applyPowderColumn(base, node, CHAMBER, 0.5)
  assert.ok(node.quaternion.equals(before),
    '写了 quaternion: 90° 时角点半径 12.6 > 9.2 会戳出内衬孔外')
})

test('applyPowderColumn: 空桶被隐藏 —— 压扁的圆柱仍有一张满尺寸不透明顶面', () => {
  const node = makePowder('center')
  node.updateMatrixWorld(true)
  const base = captureLiquidBase(node)
  applyPowderColumn(base, node, CHAMBER, 0)
  assert.equal(node.visible, false)
  applyPowderColumn(base, node, CHAMBER, 0.5)
  assert.equal(node.visible, true)
})

// ---------------------------------------------------------------------------
// contentAmount: 两条链共用的回退梯
// ---------------------------------------------------------------------------

test('contentAmount: 账本直给优先', () => {
  const spec = { kind: 'powder', nominalMm3: 600, bulkFactor: 1.6 }
  assert.equal(contentAmount({ powder_mm3: 768.4, state: 'USED' }, spec), 768.4)
  assert.equal(contentAmount({ liquid_ml: 20.5, state: 'USED' }, { kind: 'liquid' }), 20.5)
})

test('contentAmount: 账本没这一列时按 面积×切深×松散 现算', () => {
  const spec = { kind: 'powder', bulkFactor: 1.6 }
  const cell = { powder_mm3: 0, band_area_mm2: 480, cut_depth_mm: 1, state: 'USED' }
  assert.ok(Math.abs(contentAmount(cell, spec) - 768) < 1e-9)
})

test('contentAmount: 都没有时才退到标称值, 且空件给 0', () => {
  const spec = { kind: 'powder', nominalMm3: 600 }
  assert.equal(contentAmount({ powder_mm3: 0, state: 'FRESH' }, spec), 600)
  assert.equal(contentAmount({ powder_mm3: 0, state: 'USED', sample_id: 'S-1' }, spec), 600)
  assert.equal(contentAmount({ powder_mm3: 0, state: 'USED', sample_id: '' }, spec), 0)
  // 没有标称值就老老实实给 0, 不编
  assert.equal(contentAmount({ powder_mm3: 0, state: 'FRESH' }, { kind: 'powder' }), 0)
})

test('contentAmount: 缺参不炸', () => {
  assert.equal(contentAmount(null, { kind: 'powder' }), 0)
  assert.equal(contentAmount({ powder_mm3: 5 }, null), 0)
})
