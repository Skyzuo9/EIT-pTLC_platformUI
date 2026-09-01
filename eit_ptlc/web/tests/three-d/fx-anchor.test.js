/**
 * 功能: 锚点"顶部带加权中心"纯函数单测 —— 高结构偏角/薄工位/加权/空输入.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { topBandAnchor } from '../../src/three-d-fx-preview/fx/anchorMath.js'

/** 造一个盒: 中心 (cx, cz), footprint w x d, 高度从 y0 到 y1 */
function box(cx, cz, w, d, y0, y1) {
  return { min: [cx - w / 2, y0, cz - d / 2], max: [cx + w / 2, y1, cz + d / 2] }
}

test('高塔偏角: 锚点落在塔顶而不是整盒中心', () => {
  // 收集工位的典型形态: 大底盘(0,0)占满 footprint, 细高立柱在 (0.3, 0.25)
  const anchor = topBandAnchor([
    box(0, 0, 0.7, 0.6, 0, 0.2), // 底盘: 高度只到 0.2
    box(0.3, 0.25, 0.08, 0.08, 0, 1.2), // 立柱: 顶到 1.2
  ])
  assert.ok(Math.abs(anchor.x - 0.3) < 1e-9, `锚点 x 应在立柱上, 实际 ${anchor.x}`)
  assert.ok(Math.abs(anchor.z - 0.25) < 1e-9)
  assert.equal(anchor.topY, 1.2)
})

test('顶部带内多结构: 按 footprint 面积加权', () => {
  const anchor = topBandAnchor([
    box(0, 0, 0.4, 0.4, 0, 1.0), // 大件 面积 0.16
    box(1, 0, 0.1, 0.1, 0, 1.0), // 小件 面积 0.01, 同高
  ])
  // 加权中心 = (0*0.16 + 1*0.01) / 0.17 ≈ 0.0588
  assert.ok(Math.abs(anchor.x - 0.01 / 0.17) < 1e-6)
})

test('薄工位: 顶部带至少 2cm, 不会取空', () => {
  const anchor = topBandAnchor([
    box(0.5, 0.5, 0.2, 0.2, 0, 0.01), // 总高 1cm < 2cm 下限
  ])
  assert.ok(anchor)
  assert.ok(Math.abs(anchor.x - 0.5) < 1e-9)
})

test('带外结构不参与: 低处大底盘不拉偏锚点', () => {
  const anchor = topBandAnchor([
    box(-0.5, 0, 2.0, 2.0, 0, 0.3), // 巨大但矮
    box(0.4, 0.1, 0.1, 0.1, 0, 1.0),
  ], 0.28)
  // 带 cut = 1.0 - 0.28 = 0.72, 底盘顶 0.3 < 0.72 被排除
  assert.ok(Math.abs(anchor.x - 0.4) < 1e-9)
})

test('空输入/空数组返回 null', () => {
  assert.equal(topBandAnchor([]), null)
  assert.equal(topBandAnchor(null), null)
})
