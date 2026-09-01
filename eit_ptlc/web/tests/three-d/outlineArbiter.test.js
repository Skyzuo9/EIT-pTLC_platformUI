/**
 * 功能: 描边分层仲裁的单测.
 *
 * 承重的是"撤一层自动露出下一层" —— 这正是旧的 restoreSelection 补丁想做却做不全的事:
 * 那时每加一个写者, 所有旧写者的清空路径都得跟着改, 组合一多必漏, 表现为
 * "关掉物料卡片, 工位描边也一起没了"。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { OUTLINE_LAYERS, OutlineArbiter } from '../../src/three-d/twin/scene/OutlineArbiter.js'

/** 假 Effects: 只记最后一次被推了什么 */
function fakeEffects() {
  return { last: null, calls: 0, setSelected(objects) { this.last = objects; this.calls += 1 } }
}

const STATION = ['station-mesh']
const PART = ['part-mesh']
const MATERIAL = ['material-mesh']

test('优先级: 物料 > 零件 > 工位', () => {
  assert.deepEqual([...OUTLINE_LAYERS], ['material', 'part', 'station'])
})

test('单层: 声明什么就推什么', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  assert.deepEqual(fx.last, STATION)
  assert.equal(arb.winner(), 'station')
})

test('高层压过低层, 且低层没被丢掉', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  arb.set('part', PART)
  assert.deepEqual(fx.last, PART, '零件层应压过工位层')
  arb.set('material', MATERIAL)
  assert.deepEqual(fx.last, MATERIAL, '物料层应压过零件层')
  assert.equal(arb.winner(), 'material')
})

test('撤一层自动露出下一层(本模块存在的全部理由)', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  arb.set('part', PART)
  arb.set('material', MATERIAL)

  arb.clear('material')
  assert.deepEqual(fx.last, PART, '关掉物料卡片应露出零件描边, 而不是一片空白')
  arb.clear('part')
  assert.deepEqual(fx.last, STATION, '离开操作页应露出工位描边')
  arb.clear('station')
  assert.deepEqual(fx.last, [], '全撤光才是空')
  assert.equal(arb.winner(), null)
})

test('撤低层不影响正在生效的高层', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('material', MATERIAL)
  arb.set('station', STATION)
  assert.deepEqual(fx.last, MATERIAL)
  arb.clear('station')
  assert.deepEqual(fx.last, MATERIAL, '取消选中工位不该抹掉用户刚点开的物料描边')
})

test('空数组等价于撤销该层', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  arb.set('part', [])
  assert.deepEqual(fx.last, STATION, '空数组不该占住 part 层把工位层压下去')
  assert.equal(arb.winner(), 'station')
})

test('非数组(null/undefined)按撤销处理, 不炸', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  arb.set('station', null)
  assert.deepEqual(fx.last, [])
  arb.set('part', undefined)
  assert.equal(arb.winner(), null)
})

test('层名写错当场炸 —— 静默不生效会变成"描边偶尔不出现", 极难查', () => {
  const arb = new OutlineArbiter(fakeEffects())
  assert.throws(() => arb.set('parts', PART), /未知的描边层/)
  assert.throws(() => arb.clear('Station'), /未知的描边层/)
})

test('attach: 切画质档重建后期链后重放已声明的层', () => {
  const first = fakeEffects()
  const arb = new OutlineArbiter(first)
  arb.set('station', STATION)
  arb.set('part', PART)

  // 低档位: 没有后期链
  arb.attach(null)
  assert.equal(arb.winner(), 'part', '层状态是权威的, 不该因为没有链就丢')

  // 切回高档: 新链上必须立刻看到之前选中的东西
  const second = fakeEffects()
  arb.attach(second)
  assert.deepEqual(second.last, PART, '切档回来选中描边应自动重放, 而不是凭空消失')
})

test('effects 为 null 时全程空转不抛', () => {
  const arb = new OutlineArbiter(null)
  arb.set('station', STATION)
  arb.clear('station')
  arb.clearAll()
  assert.equal(arb.winner(), null)
})

test('clearAll 一次撤光(断线/卸载用)', () => {
  const fx = fakeEffects()
  const arb = new OutlineArbiter(fx)
  arb.set('station', STATION)
  arb.set('material', MATERIAL)
  arb.clearAll()
  assert.deepEqual(fx.last, [])
  assert.equal(arb.winner(), null)
})
