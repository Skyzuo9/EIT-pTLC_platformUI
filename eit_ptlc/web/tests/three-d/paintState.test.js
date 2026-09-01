/**
 * 功能: 白模删减着色的判定逻辑单测 —— markStateOf 与 MARK_TINTS.
 *
 * 值得单测的理由: markStateOf 是层级树色点与三维着色共用的单一判定, 它判错的话
 * 两侧会一起错且视觉上"看起来一致"而难以发现; MARK_TINTS 是 MARK_STYLES 的数值
 * 色派生, 两表漂移会导致"树上红点、三维橙块"这类静默的不同色.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MARK_STYLES,
  MARK_TINTS,
  MARKS,
  markStateOf,
  SelectionModel,
} from '../../src/three-d/workbench/selectionModel.js'

test('显式标记优先于规则命中', () => {
  const model = new SelectionModel()
  model.select(['a'])
  model.markSelected(MARKS.KEEP)
  const deletes = new Set(['a', 'b'])
  // a 显式保留, 即便有效删除集里有它(理论上不会, 但判定必须稳)也显示保留
  assert.equal(markStateOf(model, deletes, 'a'), MARKS.KEEP)
  // b 无显式标记但被规则命中 -> delete
  assert.equal(markStateOf(model, deletes, 'b'), MARKS.DELETE)
})

test('无标记且不在删除集 -> null(不画色点/不着色)', () => {
  const model = new SelectionModel()
  assert.equal(markStateOf(model, new Set(['x']), 'y'), null)
  assert.equal(markStateOf(model, null, 'y'), null)
  assert.equal(markStateOf(null, null, 'y'), null)
})

test('显式减面在删除集之外也能显出来', () => {
  const model = new SelectionModel()
  model.select(['m'])
  model.markSelected(MARKS.DECIMATE)
  assert.equal(markStateOf(model, new Set(), 'm'), MARKS.DECIMATE)
})

test('MARK_TINTS 与 MARK_STYLES 数值一致(树与三维同源同色)', () => {
  for (const [mark, style] of Object.entries(MARK_STYLES)) {
    assert.equal(MARK_TINTS[mark], parseInt(style.color.slice(1), 16))
  }
  // 三种标记一个都不能少
  assert.deepEqual(Object.keys(MARK_TINTS).sort(), [...Object.values(MARKS)].sort())
})
