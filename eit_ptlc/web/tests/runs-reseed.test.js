import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'

import { useRunsStore } from '../src/stores/runs.js'
import { api } from '../src/api.js'

// 事件构造 (字段对照后端 thread.py; 与 runs-reduce.test.js 同构)
const opStart = (rid = 'r1') => ({ type: 'operation_start', run_id: rid, operation: 'root', label: 'root' })
const enter = (aid, op, action, script = 'root', rid = 'r1') =>
  ({ type: 'vm_node_enter', run_id: rid, op, aid, action, script })
const done = (aid, op, action, script = 'root', status = 'DONE', rid = 'r1') =>
  ({ type: 'vm_node_done', run_id: rid, op, aid, action, script, status, message: '完成', result: {} })
const opDone = (rid = 'r1', status = 'DONE') => ({ type: 'operation_done', run_id: rid, status })

function findStep(steps, script, aid) {
  for (const s of steps) {
    if (s.script === script && s.step_id === aid) return s
    if (s.children && s.children.length) {
      const hit = findStep(s.children, script, aid)
      if (hit) return hit
    }
  }
  return null
}

// 递归收集仍 RUNNING 的步骤
function runningSteps(steps, out = []) {
  for (const s of steps) {
    if (s.status === 'RUNNING') out.push(`${s.script}|${s.step_id}`)
    if (s.children && s.children.length) runningSteps(s.children, out)
  }
  return out
}

function freshStore() {
  setActivePinia(createPinia())
  api.listRuns = async () => []   // seedRecent 由 ingest 沿路调用, 测试中回空即可
  return useRunsStore()
}

test('断线丢终态: 重连沿补种整树重放, b/7 收口不再闪烁', async () => {
  const runs = freshStore()
  // 实时阶段: 只收到 enter(b/7), 其 done 与 operation_done 在断线窗口丢失
  runs.ingest(opStart())
  runs.ingest(enter('b/3', 'call', 'sampling.spot_band_layer'))
  runs.ingest(done('b/3', 'call', 'sampling.spot_band_layer'))
  runs.ingest(enter('b/7', 'run_script', 'sampling_unload'))
  assert.equal(findStep(runs.live.steps, 'root', 'b/7').status, 'RUNNING')

  // 权威记录 (RunStore 无损): 含子步/容器 done 与终态
  api.getRun = async (id) => {
    assert.equal(id, 'r1')
    return { run_id: 'r1', status: 'DONE', events: [
      opStart(),
      enter('b/3', 'call', 'sampling.spot_band_layer'), done('b/3', 'call', 'sampling.spot_band_layer'),
      enter('b/7', 'run_script', 'sampling_unload'),
      enter('b/0', 'call', 'robot.place', 'sampling_unload'), done('b/0', 'call', 'robot.place', 'sampling_unload'),
      done('b/7', 'run_script', 'sampling_unload'),
      opDone(),
    ] }
  }
  await runs.reseedLive()

  assert.equal(runs.live.status, 'DONE')
  assert.equal(findStep(runs.live.steps, 'root', 'b/7').status, 'DONE')
  assert.equal(findStep(runs.live.steps, 'sampling_unload', 'b/0').status, 'DONE')
  assert.deepEqual(runningSteps(runs.live.steps), [])   // 无残留脉冲行
})

test('启动收敛出的 INTERRUPTED 行: 事件日志没有终态事件, 补种采纳权威行状态', async () => {
  const runs = freshStore()
  // 实机形态 (2026-08-14 取证): 单步停驻被遗弃的运行, 末条事件是 vm_state STOPPED,
  // 永远没有 operation_done; 后端启动收敛把行 UPDATE 成 INTERRUPTED —— 行是终态,
  // 事件流不是。只重放事件的话投影会停在 RUNNING, 顶栏假 ▶ 就是这么来的。
  runs.ingest(opStart())
  runs.ingest(enter('b/2', 'call', 'robot.place'))
  runs.ingest(done('b/2', 'call', 'robot.place'))

  api.getRun = async () => ({ run_id: 'r1', status: 'INTERRUPTED',
    message: '后端重启时该运行仍未终结, 已判为中断',
    events: [
      opStart(),
      enter('b/2', 'call', 'robot.place'), done('b/2', 'call', 'robot.place'),
      // 没有 opDone —— 这正是被收敛行的特征
    ] })
  await runs.reseedLive()

  assert.equal(runs.live.status, 'INTERRUPTED', '必须采纳权威行的终态, 不能停在 RUNNING')
  assert.match(runs.live.message, /中断/)
  // 终态通道不再算 active (顶栏 ▶ 与物料门禁都以此判)
  assert.equal(runs.activeRuns.filter((r) => r.status === 'RUNNING').length, 0)
})

test('权威行仍是 RUNNING 时, 补种不会误收口 (采纳只认终态)', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  runs.ingest(enter('b/1', 'call', 'sampling.init'))
  api.getRun = async () => ({ run_id: 'r1', status: 'RUNNING', events: [
    opStart(), enter('b/1', 'call', 'sampling.init'),
  ] })
  await runs.reseedLive()
  assert.equal(runs.live.status, 'RUNNING', '在跑的运行不能被补种误杀')
})

test('补种期间实时事件入缓冲: 快照重叠经门去重, 不产生重复步骤', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  runs.ingest(enter('b/0', 'call', 'A'))

  let resolveGet
  api.getRun = () => new Promise((res) => { resolveGet = res })
  const pending = runs.reseedLive()

  // 补种在途: WS 陆续到达 —— 前两条也在快照里 (重叠), 第三条是快照点之后的新事件
  runs.ingest(done('b/0', 'call', 'A'))
  runs.ingest(enter('b/1', 'call', 'B'))
  runs.ingest(done('b/1', 'call', 'B'))
  resolveGet({ run_id: 'r1', status: 'RUNNING', events: [
    opStart(),
    enter('b/0', 'call', 'A'), done('b/0', 'call', 'A'),
    enter('b/1', 'call', 'B'),                    // 快照止于 b/1 进入
  ] })
  await pending

  // b/0 与 b/1 各恰一份; 缓冲中的重叠 (done b/0, enter b/1) 被吸收, 新事件 (done b/1) 已续灌
  assert.equal(runs.live.steps.length, 2)
  assert.equal(findStep(runs.live.steps, 'root', 'b/0').status, 'DONE')
  assert.equal(findStep(runs.live.steps, 'root', 'b/1').status, 'DONE')

  // 补种后实时流继续推进 (liveCtx 已衔接): 后续 enter/done 正常入树
  runs.ingest(enter('b/2', 'call', 'C'))
  runs.ingest(done('b/2', 'call', 'C'))
  runs.ingest(opDone())
  assert.equal(findStep(runs.live.steps, 'root', 'b/2').status, 'DONE')
  assert.equal(runs.live.status, 'DONE')
})

test('补种在途遇到新 operation_start: 本次补种作废, 新运行优先', async () => {
  const runs = freshStore()
  runs.ingest(opStart('r1'))
  runs.ingest(enter('b/0', 'call', 'A'))

  let resolveGet
  api.getRun = () => new Promise((res) => { resolveGet = res })
  const pending = runs.reseedLive()

  runs.ingest(opStart('r2'))                       // 新运行到达
  runs.ingest(enter('b/0', 'call', 'X', 'root', 'r2'))
  resolveGet({ run_id: 'r1', status: 'DONE', events: [opStart('r1'), opDone('r1')] })
  await pending

  assert.equal(runs.live.run_id, 'r2')             // 不被 r1 的旧重放覆盖
  assert.equal(runs.live.status, 'RUNNING')
  assert.equal(findStep(runs.live.steps, 'root', 'b/0').action, 'X')
})

test('权威记录缺失 (404 手动单动作) 或网络失败: 放弃补种维持现状, 实时流不受影响', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  runs.ingest(enter('b/0', 'call', 'A'))

  api.getRun = async () => { throw new Error('404') }
  await runs.reseedLive()

  assert.equal(runs.live.run_id, 'r1')
  assert.equal(findStep(runs.live.steps, 'root', 'b/0').status, 'RUNNING')   // 现状保留
  runs.ingest(done('b/0', 'call', 'A'))            // 缓冲已清: 实时流直通
  assert.equal(findStep(runs.live.steps, 'root', 'b/0').status, 'DONE')
})

test('手动单动作 live: 重连沿补种直接跳过, 不发注定 404 的 getRun', async () => {
  const runs = freshStore()
  // atomic 标记来自 manual_service._audit 合成的 operation_start (run_id = manual-*)
  runs.ingest({ ...opStart('manual-224439961'), atomic: true })

  let calls = 0
  api.getRun = async () => { calls += 1; throw new Error('404') }
  await runs.reseedLive()                          // App.vue 重连沿的无参调用
  assert.equal(calls, 0)                           // 请求根本没发出去

  // 显式带真流程 id (App.vue 挂载时取 recent[0]) 仍照常补种, 不被 atomic 标记误伤
  api.getRun = async () => { calls += 1; return { run_id: 'r1', status: 'DONE', events: [opStart(), opDone()] } }
  await runs.reseedLive('r1')
  assert.equal(calls, 1)
  assert.equal(runs.live.run_id, 'r1')
  assert.equal(runs.live.status, 'DONE')
})

test('挂载补种 RUNNING 运行 (刷新页恢复): 重放至当前进度, 后续实时事件衔接收口', async () => {
  const runs = freshStore()                        // 刷新后 live 为空
  api.getRun = async () => ({ run_id: 'r1', status: 'RUNNING', events: [
    opStart(),
    enter('b/0', 'call', 'A'), done('b/0', 'call', 'A'),
    enter('b/1', 'run_script', 'sub'),
    enter('b/0', 'call', 'inner', 'sub'),
  ] })
  await runs.reseedLive('r1')

  assert.equal(runs.live.run_id, 'r1')
  assert.equal(runs.live.status, 'RUNNING')
  assert.equal(findStep(runs.live.steps, 'sub', 'b/0').status, 'RUNNING')

  // 实时流衔接: 子步完成 -> 容器完成 -> 终态, 全树收口
  runs.ingest(done('b/0', 'call', 'inner', 'sub'))
  runs.ingest(done('b/1', 'run_script', 'sub'))
  runs.ingest(opDone())
  assert.equal(runs.live.status, 'DONE')
  assert.deepEqual(runningSteps(runs.live.steps), [])
})

test('去重门语义: 门开时吸收快照重复投递, 首条新事件即关门', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  const storedTail = done('b/0', 'call', 'A')
  api.getRun = async () => ({ run_id: 'r1', status: 'RUNNING', events: [
    opStart(), enter('b/0', 'call', 'A'), storedTail,
  ] })
  await runs.reseedLive()

  // 快照点前的在途重复 (与存储尾部同串): 到达即被吸收, 状态不重复冲写
  runs.ingest(JSON.parse(JSON.stringify(storedTail)))
  assert.equal(runs.live.steps.length, 1)
  // 首条快照点之后的新事件: 正常应用并关门
  runs.ingest(enter('b/1', 'call', 'B'))
  assert.equal(runs.live.steps.length, 2)
  assert.equal(findStep(runs.live.steps, 'root', 'b/1').status, 'RUNNING')
})
