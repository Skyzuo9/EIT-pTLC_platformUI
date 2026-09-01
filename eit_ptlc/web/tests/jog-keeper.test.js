// 按住点动续订器: 钉住"任何时刻最多一个定时器, 且句柄一定可达"这条不变量。
//
// 为什么单独测: 真机上出过一次事故 —— 快速点一下点动按钮, pointerup 在 jogStart 的
// await 窗口里跑完, 随后装上的定时器再没有任何路径能停它, 于是它跨页面永生, 一直
// 往后端刷 409。定时器泄漏不会自己暴露, 只能靠断言把它钉住。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { createJogKeeper } from '../src/utils/jogKeeper.js'

// 假定时器: 记录所有被创建过的句柄与仍存活的句柄, 以便断言"没有孤儿"
function fakeTimers() {
  let next = 1
  const alive = new Map()      // handle -> fn
  const created = []
  return {
    api: {
      setInterval: (fn) => {
        const h = next++
        alive.set(h, fn)
        created.push(h)
        return h
      },
      clearInterval: (h) => { alive.delete(h) },
    },
    alive,
    created,
    tickAll: () => [...alive.values()].forEach((fn) => fn()),
  }
}

test('start 两次不会留下孤儿定时器', () => {
  const t = fakeTimers()
  const k = createJogKeeper(t.api)
  k.start('axis_4x', () => Promise.resolve())
  k.start('axis_8y', () => Promise.resolve())
  assert.equal(t.created.length, 2, '应当确实创建了两次')
  assert.equal(t.alive.size, 1, '旧定时器必须已被清掉')
  assert.equal(k.runningId(), 'axis_8y')
  k.stop()
  assert.equal(t.alive.size, 0)
})

test('stop 之后不再有 tick', () => {
  const t = fakeTimers()
  const k = createJogKeeper(t.api)
  let ticks = 0
  k.start('axis_4x', () => { ticks += 1; return Promise.resolve() })
  t.tickAll()
  assert.equal(ticks, 1)
  k.stop()
  assert.equal(k.isRunning(), false)
  t.tickAll()
  assert.equal(ticks, 1, 'stop 后不应再被调用')
})

test('续订失败自动收摊 (不再刷请求)', async () => {
  const t = fakeTimers()
  const k = createJogKeeper(t.api)
  let ticks = 0
  k.start('axis_4x', () => { ticks += 1; return Promise.reject(new Error('409')) })
  t.tickAll()
  await Promise.resolve()   // 让 .catch 落地
  await Promise.resolve()
  assert.equal(k.isRunning(), false, '失败一次即应停掉')
  assert.equal(t.alive.size, 0)
  t.tickAll()
  assert.equal(ticks, 1, '停掉后不应再发第二次')
})

test('onTick 同步抛异常也要收摊', () => {
  const t = fakeTimers()
  const k = createJogKeeper(t.api)
  k.start('axis_4x', () => { throw new Error('boom') })
  t.tickAll()
  assert.equal(k.isRunning(), false)
  assert.equal(t.alive.size, 0)
})
