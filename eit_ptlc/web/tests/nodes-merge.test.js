// 遥测字段级合并 (nodes store 的 mergeInto/sameArray): 钉住四条语义 —
// 值不同才写(reactive 依赖只在真实变化处失效)、数组浅比较保身份、嵌套一层递归、
// src 消失的 key 删除; 外加 reactive 下"无变化帧零触发"的行为断言。
import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, reactive } from 'vue'

import { mergeInto, sameArray } from '../src/stores/nodes.js'

test('sameArray: 长度/逐元素 Object.is', () => {
  assert.equal(sameArray([1, 2, 3], [1, 2, 3]), true)
  assert.equal(sameArray([1, 2], [1, 2, 3]), false)
  assert.equal(sameArray([1, NaN], [1, NaN]), true) // Object.is 语义
  assert.equal(sameArray([1, 2], [1, 3]), false)
})

test('mergeInto: 标量值不同才写, 相同数组保身份, 不同数组整替', () => {
  const target = { a: 1, arr: [1, 2, 3], gone: 'x' }
  const keepArr = target.arr
  mergeInto(target, { a: 1, arr: [1, 2, 3], b: 'new' }, 1)
  assert.equal(target.a, 1)
  assert.equal(target.arr, keepArr, '内容相同的数组必须保留旧身份')
  assert.equal(target.b, 'new')
  assert.equal('gone' in target, false, 'src 里消失的 key 应删除')
  mergeInto(target, { a: 2, arr: [1, 2, 4], b: 'new' }, 1)
  assert.equal(target.a, 2)
  assert.notEqual(target.arr, keepArr)
  assert.deepEqual(target.arr, [1, 2, 4])
})

test('mergeInto: 嵌套对象一层递归 (保外层身份), 深于 depth 整替', () => {
  const tool = { mounted_tool: 1, di_bits: 3 }
  const target = { tool_state: tool }
  mergeInto(target, { tool_state: { mounted_tool: 2, di_bits: 3 } }, 1)
  assert.equal(target.tool_state, tool, '一层内递归合并, 嵌套对象身份保留')
  assert.equal(target.tool_state.mounted_tool, 2)
  const deep = { lvl2: { x: 1 } }
  const origLvl2 = deep.lvl2
  const t2 = { nest: deep }
  mergeInto(t2, { nest: { lvl2: { x: 2 } } }, 1)
  assert.equal(t2.nest, deep, '一层内 nest 本身仍递归合并保身份')
  assert.notEqual(t2.nest.lvl2, origLvl2, 'depth 用尽后第二层整替 (不再递归)')
  assert.equal(t2.nest.lvl2.x, 2)
})

test('reactive 行为: 帧间无变化时依赖 computed 不重算, 有变化时精确失效', () => {
  const data = reactive({ pos: 10, flags: [0, 1], tool_state: { mounted_tool: 1 } })
  let evals = 0
  const view = computed(() => {
    evals += 1
    return `${data.pos}|${data.flags.join(',')}|${data.tool_state.mounted_tool}`
  })
  assert.equal(view.value, '10|0,1|1')
  const before = evals
  // 无变化帧: 合并后 computed 不应失效
  mergeInto(data, { pos: 10, flags: [0, 1], tool_state: { mounted_tool: 1 } }, 1)
  assert.equal(view.value, '10|0,1|1')
  assert.equal(evals, before, '无变化帧不得触发重算')
  // 单字段变化: 失效且值正确
  mergeInto(data, { pos: 11, flags: [0, 1], tool_state: { mounted_tool: 1 } }, 1)
  assert.equal(view.value, '11|0,1|1')
  assert.equal(evals, before + 1)
})
