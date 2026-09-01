// 按住点动 composable: 钉住"代次令牌"这条不变量。
//
// jogKeeper 那层测的是"定时器句柄不丢" (tests/jog-keeper.test.js), 这层测的是**谁来装**
// 定时器: jogDown 里 `await api.pcManualJogStart(...)` 是个竞态窗口 —— 快速点一下时
// pointerup → stopJog() 会在 await 期间整个跑完。若不作废这次 jogDown, 它恢复执行后
// 还会装上续订器, 而那时 jogging 已空, 再没有任何路径去停它 (真机上出过: 定时器跨页面
// 永生, 一直往后端刷 409)。
//
// 本测试直接调 composable, 不挂载组件: Vue 的 onMounted/onBeforeUnmount 在无组件实例时
// 是 no-op (只打一条 warning), 而窗口级监听本来就只在真实浏览器里才有意义。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { api } from '../src/api.js'
import { useAxisJog } from '../src/composables/useAxisJog.js'

const AXIS = { id: 'axis_4x', label: '上样轴4X' }
const KEEP_PERIOD_MS = 300 // 与 useAxisJog 内常量一致

// pointerdown 事件替身: currentTarget 要能吃下 pointer capture 三件套
function fakeEvent() {
  return {
    pointerId: 1,
    preventDefault() {},
    currentTarget: {
      setPointerCapture() {},
      hasPointerCapture: () => true,
      releasePointerCapture() {},
    },
  }
}

// api 的点动三件套换成可控替身; start 的 resolve 时机由调用方掌握
function stubApi({ startDelayMs = 0 } = {}) {
  const calls = { start: 0, keep: 0, stop: 0 }
  const orig = {
    pcManualJogStart: api.pcManualJogStart,
    pcManualJogKeep: api.pcManualJogKeep,
    pcManualJogStop: api.pcManualJogStop,
  }
  api.pcManualJogStart = () => {
    calls.start += 1
    return new Promise((resolve) => setTimeout(resolve, startDelayMs))
  }
  api.pcManualJogKeep = () => { calls.keep += 1; return Promise.resolve() }
  api.pcManualJogStop = () => { calls.stop += 1; return Promise.resolve() }
  return { calls, restore: () => Object.assign(api, orig) }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

test('快速点一下 (松手落在 jogStart 的 await 窗口里) 不留下续订定时器', async () => {
  // start 慢 60ms, 期间 stopJog 整个跑完 —— 正是那次事故的时序
  const s = stubApi({ startDelayMs: 60 })
  try {
    const { jogDown, stopJog, jogging } = useAxisJog({ canDrive: { value: true } })
    const pending = jogDown(AXIS, 'pos', fakeEvent())
    await stopJog() // 松手: 此刻 jogDown 还卡在 await 上
    await pending // 让 jogDown 恢复执行, 走到"该不该装续订器"的分叉
    assert.equal(jogging.value, '', '松手后不应还认为自己在点动')

    // 关键断言: 再等两个续订周期, keep 必须一次都没发
    await sleep(KEEP_PERIOD_MS * 2 + 80)
    assert.equal(s.calls.keep, 0, '作废的 jogDown 不得装上续订器')
    // 且这条被作废的路径要补一次 stop, 免得轴留在 PLC 里继续走
    assert.equal(s.calls.stop, 2, '松手一次 + 作废路径补一次')
  } finally {
    s.restore()
  }
})

test('正常按住: 装上续订器并周期续订, 松手即停', async () => {
  const s = stubApi()
  try {
    const { jogDown, stopJog, jogging } = useAxisJog({ canDrive: { value: true } })
    await jogDown(AXIS, 'neg', fakeEvent())
    assert.equal(jogging.value, AXIS.id)
    assert.equal(s.calls.start, 1)

    await sleep(KEEP_PERIOD_MS + 80)
    assert.ok(s.calls.keep >= 1, `按住期间应至少续订一次, 实际 ${s.calls.keep}`)

    await stopJog()
    assert.equal(jogging.value, '')
    assert.equal(s.calls.stop, 1)

    const keepAtRelease = s.calls.keep
    await sleep(KEEP_PERIOD_MS * 2 + 80)
    assert.equal(s.calls.keep, keepAtRelease, '松手后不得再续订')
  } finally {
    s.restore()
  }
})

test('canDrive 为假时不下发 (未进单点模式的按钮点击是空操作)', async () => {
  const s = stubApi()
  try {
    const { jogDown, jogging } = useAxisJog({ canDrive: { value: false } })
    await jogDown(AXIS, 'pos', fakeEvent())
    assert.equal(s.calls.start, 0)
    assert.equal(jogging.value, '')
  } finally {
    s.restore()
  }
})

test('jogStart 失败: 清点动态、回调错误、不装续订器', async () => {
  const s = stubApi()
  api.pcManualJogStart = () => Promise.reject(new Error('boom'))
  try {
    let reported = ''
    const { jogDown, jogging } = useAxisJog({
      canDrive: { value: true },
      onError: (m) => { reported = m },
    })
    await jogDown(AXIS, 'pos', fakeEvent())
    assert.equal(jogging.value, '')
    assert.ok(reported.includes(AXIS.label), `错误应带轴名, 实际 "${reported}"`)
    await sleep(KEEP_PERIOD_MS + 80)
    assert.equal(s.calls.keep, 0)
  } finally {
    s.restore()
  }
})
