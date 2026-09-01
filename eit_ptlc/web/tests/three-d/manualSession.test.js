/**
 * 功能: ManualSession(手动模式会话/点动状态机)的单测 —— fake timer 锁安全语义.
 *
 * 值得单测的理由: 这是唯一直接驱动实机硬件的前端状态机, "keep 断供必停"
 * "心跳失败必失联并停 jog" "退出幂等" 三条安全语义靠人肉回归成本太高.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ManualSession } from '../../src/three-d/twin/manualApi.js'

/** 手工步进的假计时器 */
function makeFakeTimers() {
  let nextId = 1
  const timers = new Map()
  return {
    setIntervalFn: (fn, ms) => {
      const id = nextId++
      timers.set(id, { fn, ms })
      return id
    },
    clearIntervalFn: (id) => timers.delete(id),
    /** 触发全部在册计时器一拍 */
    async tickAll() {
      for (const { fn } of [...timers.values()]) await fn()
    },
    count: () => timers.size,
  }
}

/** 记录请求并可编程失败的假请求器 */
function makeFakeRequest() {
  const calls = []
  const failures = new Set()
  return {
    calls,
    failOn: (substr) => failures.add(substr),
    healOn: (substr) => failures.delete(substr),
    request: async (path, body) => {
      calls.push({ path, body })
      for (const substr of failures) {
        if (path.includes(substr)) throw new Error(`fake fail: ${substr}`)
      }
      return { ok: true }
    },
  }
}

test('enter 成功 -> active 并起心跳; exit 停表并调 session/exit', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  const session = new ManualSession({ request: fake.request, ...timers })

  assert.equal(await session.enter(), true)
  assert.equal(session.state, 'active')
  assert.equal(timers.count(), 1)

  await timers.tickAll()
  assert.ok(fake.calls.some((c) => c.path.includes('keepalive')))

  await session.exit()
  assert.equal(session.state, 'idle')
  assert.equal(timers.count(), 0)
  assert.ok(fake.calls.some((c) => c.path.includes('session/exit')))
})

test('enter 403(非 DEBUG) -> 回 idle 带原因', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  fake.failOn('session/enter')
  const session = new ManualSession({ request: fake.request, ...timers })
  assert.equal(await session.enter(), false)
  assert.equal(session.state, 'idle')
  assert.match(session.reason, /fake fail/)
  assert.equal(timers.count(), 0)
})

test('jog: start 起续订表; keep 断供 -> 立即 stop 并记录原因', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  const session = new ManualSession({ request: fake.request, ...timers })
  await session.enter()

  assert.equal(await session.jogStart('axis_11y', 'pos'), true)
  assert.deepEqual(session.jogging, { axisId: 'axis_11y', direction: 'pos' })
  assert.equal(timers.count(), 2) // 心跳 + 续订

  await timers.tickAll()
  assert.ok(fake.calls.some((c) => c.path.includes('jog/keep')))

  // 续订断供 -> 必停
  fake.failOn('jog/keep')
  await timers.tickAll()
  assert.equal(session.jogging, null)
  assert.ok(fake.calls.some((c) => c.path.includes('jog/stop')))
  assert.match(session.reason, /续订失败/)
  assert.equal(timers.count(), 1) // 只剩心跳
})

test('心跳失败 -> lost + 自动停 jog + 全部停表', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  const session = new ManualSession({ request: fake.request, ...timers })
  await session.enter()
  await session.jogStart('axis_3y', 'neg')

  fake.failOn('keepalive')
  await timers.tickAll()
  assert.equal(session.state, 'lost')
  assert.equal(session.jogging, null)
  assert.equal(timers.count(), 0)
  assert.ok(fake.calls.some((c) => c.path.includes('jog/stop')))
})

test('松手 jogStop 幂等; 未 active 时 jogStart 拒绝', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  const session = new ManualSession({ request: fake.request, ...timers })
  assert.equal(await session.jogStart('axis_11y', 'pos'), false)

  await session.enter()
  await session.jogStart('axis_11y', 'pos')
  await session.jogStop()
  assert.equal(session.jogging, null)
  const stops = fake.calls.filter((c) => c.path.includes('jog/stop')).length
  await session.jogStop() // 幂等: 不再发第二次
  assert.equal(fake.calls.filter((c) => c.path.includes('jog/stop')).length, stops)
})

test('exit 幂等且 idle 态不发 session/exit', async () => {
  const timers = makeFakeTimers()
  const fake = makeFakeRequest()
  const session = new ManualSession({ request: fake.request, ...timers })
  await session.exit()
  assert.equal(fake.calls.filter((c) => c.path.includes('session/exit')).length, 0)
})
