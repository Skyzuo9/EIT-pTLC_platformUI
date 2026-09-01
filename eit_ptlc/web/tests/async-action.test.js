// useAsyncAction: 钉住 在途去重 / minInterval / arm 两段式 / 错误必捕获 四条不变量。
// 直接裸调 (无组件实例), getCurrentInstance 分支自动跳过。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { useAsyncAction } from '../src/composables/useAsyncAction.js'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

test('busy 期间重入被忽略 (连发保护)', async () => {
  let calls = 0
  let release
  const gate = new Promise((r) => (release = r))
  const act = useAsyncAction(async () => {
    calls += 1
    await gate
  })
  const p1 = act.run()
  assert.equal(act.busy, true)
  await act.run() // 在途重入: 立即返回, 不再调 fn
  assert.equal(calls, 1)
  release()
  await p1
  assert.equal(act.busy, false)
})

test('minInterval: 完成后窗口内的再次触发被忽略', async () => {
  let calls = 0
  const act = useAsyncAction(async () => { calls += 1 }, { minInterval: 80 })
  await act.run()
  await act.run() // 距上次完成 < 80ms → 忽略
  assert.equal(calls, 1)
  await sleep(100)
  await act.run()
  assert.equal(calls, 2)
})

test('arm 两段式: 首点只武装, 二点执行, 超时自动撤防', async () => {
  let calls = 0
  const act = useAsyncAction(async () => { calls += 1 }, { arm: { label: '再点确认', timeoutMs: 60 } })
  await act.run()
  assert.equal(calls, 0, '首点不执行')
  assert.equal(act.armed, true)
  assert.equal(act.armedLabel, '再点确认')
  await act.run()
  assert.equal(calls, 1, '武装期内二点执行')
  assert.equal(act.armed, false, '执行后撤防')

  await sleep(100) // 越过 minInterval=0 无影响; 重新武装并等超时
  await act.run()
  assert.equal(act.armed, true)
  await sleep(90)
  assert.equal(act.armed, false, '超时自动撤防')
  assert.equal(calls, 1)
})

test('fn 抛错必被捕获: error 置文案, run 返回 undefined, 无未处理拒绝', async () => {
  const act = useAsyncAction(async () => {
    throw new Error('boom')
  }, { errorPrefix: '执行失败' })
  const r = await act.run()
  assert.equal(r, undefined)
  assert.ok(act.error.startsWith('执行失败: '), `error 应带前缀, 实际: ${act.error}`)
  assert.equal(act.busy, false)
})
