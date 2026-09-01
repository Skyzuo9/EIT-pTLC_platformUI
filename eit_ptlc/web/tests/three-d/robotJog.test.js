/**
 * 功能: 机械臂点动状态机的单测.
 *
 * 它管的是一台真机械臂的"按住走 / 松手停", 从 RobotJogPanel.vue 抽出来共用之前
 * **一条测试都没有** —— 这份测试的第一目的就是把抽取前后的行为钉死。
 *
 * 测法照仓内既有惯例(见 tests/axis-jog.test.js 头注): **直接调 composable, 不挂载组件**。
 * Vue 的 onMounted/onBeforeUnmount 在没有组件实例时是 no-op, 所以那三条窗口级监听
 * (visibilitychange / blur / pagehide)在这里注册不上 —— 它们只在真实浏览器里才有意义,
 * 按仓内定案放到活页验收里逐条点(切标签页 / 切窗口 / 关页面 各看一次点动是否立刻停)。
 * 这里能测、也必须测的是它们共同调用的那个 `safetyStop()` 本身。
 */
import { strict as assert } from 'node:assert'
import test from 'node:test'

// composable 里 pressStep 用 window.setTimeout 清高亮; node 下补一个最小壳。
// ⚠ 千万别顺手补 globalThis.document: @vue/runtime-dom 在模块顶层按
//   `typeof document !== 'undefined'` 决定要不要 createElement, 补一个没有 createElement
//   的假 document 反而把那道守卫骗过去, 整个 vue 导入就炸了。不定义它才是对的。
globalThis.window = globalThis.window || { setTimeout: (fn, ms) => setTimeout(fn, ms) }

const { useRobotJog } = await import('../../src/composables/useRobotJog.js')

/** 假点动通道: 逐条记下发了什么 */
function fakeApi(overrides = {}) {
  const calls = []
  return {
    calls,
    async jogStart(token) { calls.push(['start', token]); return { status: 'DONE', token } },
    async jogStop() { calls.push(['stop']); return { status: 'DONE' } },
    async step(axis, distance, motion) {
      calls.push(['step', axis, distance, motion])
      return { status: 'DONE' }
    },
    ...overrides,
  }
}

/** 建一个会话(记录全部回显) */
function makeJog(api, options) {
  const results = []
  const jog = useRobotJog(api, { onResult: (r) => results.push(r), ...options })
  return { jog, results }
}

/** pointerdown 事件替身: currentTarget 要能吃下 pointer capture 三件套 */
function fakeEvent(pointerId = 1) {
  const captured = new Set()
  return {
    pointerId,
    preventDefault() {},
    currentTarget: {
      setPointerCapture(id) { captured.add(id) },
      hasPointerCapture(id) { return captured.has(id) },
      releasePointerCapture(id) { captured.delete(id) },
    },
  }
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

test('连续: 按住起 → 松手停', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressContinuous('X+', fakeEvent())
  assert.deepEqual(api.calls, [['start', 'X+']])
  assert.ok(jog.isActive('X+'))
  jog.releaseContinuous(fakeEvent())
  await tick()
  assert.deepEqual(api.calls, [['start', 'X+'], ['stop']])
  assert.equal(jog.activeDir.value, '')
})

test('换向: 先停旧方向再起新方向(后到者胜)', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressContinuous('X+', fakeEvent())
  await jog.pressContinuous('X-', fakeEvent())
  assert.deepEqual(api.calls, [['start', 'X+'], ['stop'], ['start', 'X-']],
    '换向必须先 stop 再 start, 否则两个方向的令牌会在控制器里打架')
})

test('松开只认按下时那个指针(多指触控不会误停)', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressContinuous('Y+', fakeEvent(7))
  jog.releaseContinuous(fakeEvent(9))
  await tick()
  assert.deepEqual(api.calls, [['start', 'Y+']], '另一根手指抬起不该停掉正在走的轴')
  jog.releaseContinuous(fakeEvent(7))
  await tick()
  assert.deepEqual(api.calls, [['start', 'Y+'], ['stop']])
})

test('步进模式下按住不发 jogStart', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  jog.mode.value = 'step'
  await jog.pressContinuous('X+', fakeEvent())
  assert.deepEqual(api.calls, [], '步进模式下按住不该起连续点动')
})

test('步进: 平移取 mm、旋转与关节取 deg, motion 按 l / j 分流', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  jog.mode.value = 'step'
  jog.stepMm.value = 2.5
  jog.stepDeg.value = 3
  await jog.pressStep({ axis: 'X', kind: 'translate' }, 1, { detail: 1 })
  await jog.pressStep({ axis: 'J2', kind: 'joint' }, -1, { detail: 1 })
  await jog.pressStep({ axis: 'Rx', kind: 'rotate' }, 1, { detail: 1 })
  assert.deepEqual(api.calls, [
    ['step', 'X', 2.5, 'l'],
    ['step', 'J2', -3, 'j'],
    ['step', 'Rx', 3, 'l'],
  ])
})

test('连续模式下不会误发步进', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressStep({ axis: 'X', kind: 'translate' }, 1, { detail: 1 })
  assert.deepEqual(api.calls, [])
})

test('步进高亮到点自动灭(无结束回包, 只能定时清)', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  jog.mode.value = 'step'
  await jog.pressStep({ axis: 'X', kind: 'translate' }, 1, { detail: 1 })
  assert.ok(jog.isActive('X+'), '刚发完应亮着')
  await new Promise((resolve) => setTimeout(resolve, 260))
  assert.equal(jog.activeDir.value, '', '超时后高亮必须灭, 否则界面上永远显示"在走"')
})

// ── 安全停: 四路事件的共同落点 ────────────────────────────────────────────────
// (三条窗口级监听本身在活页验收里点; 这里钉的是它们调用的这个函数的语义)
test('安全停: 正在点动时会真的发停止', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressContinuous('Z+', fakeEvent())
  jog.safetyStop()
  await tick()
  assert.deepEqual(api.calls, [['start', 'Z+'], ['stop']])
  assert.equal(jog.activeDir.value, '')
})

test('安全停: 没在动时不空发 jogStop', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  jog.safetyStop()
  jog.safetyStop()
  await tick()
  assert.deepEqual(api.calls, [], '没在点动就不该对机器人空发停止')
})

test('重复停止只发一次(松手 + 安全停撞在一起也不会连发)', async () => {
  const api = fakeApi()
  const { jog } = makeJog(api)
  await jog.pressContinuous('J1+', fakeEvent())
  await jog.stopContinuous()
  await jog.stopContinuous()
  jog.safetyStop()
  await tick()
  assert.deepEqual(api.calls, [['start', 'J1+'], ['stop']])
})

test('jogStart 失败回显 ERROR, 不静默', async () => {
  const api = fakeApi({ async jogStart() { throw new Error('通信断了') } })
  const { jog, results } = makeJog(api)
  await jog.pressContinuous('X+', fakeEvent())
  assert.equal(results.at(-1).status, 'ERROR')
  assert.match(results.at(-1).message, /通信断了/)
})

test('step 失败回显 ERROR, 且高亮仍会灭', async () => {
  const api = fakeApi({ async step() { throw new Error('步进被拒') } })
  const { jog, results } = makeJog(api)
  jog.mode.value = 'step'
  await jog.pressStep({ axis: 'X', kind: 'translate' }, 1, { detail: 1 })
  assert.equal(results.at(-1).status, 'ERROR')
  await new Promise((resolve) => setTimeout(resolve, 260))
  assert.equal(jog.activeDir.value, '')
})

test('松手时 jogStop 失败不覆盖上一条回显, 但本地必须认为已停', async () => {
  const api = fakeApi({ async jogStop() { throw new Error('停止失败') } })
  const { jog, results } = makeJog(api)
  await jog.pressContinuous('X+', fakeEvent())
  const before = results.length
  await jog.stopContinuous()
  assert.equal(results.length, before, 'jogStop 的异常不该产生新回显')
  assert.equal(jog.activeDir.value, '', '即便下发失败, 高亮也必须灭 —— 否则界面显示"还在走"')
})
