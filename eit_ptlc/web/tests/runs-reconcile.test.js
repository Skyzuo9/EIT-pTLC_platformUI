import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'

import { useRunsStore } from '../src/stores/runs.js'
import { api } from '../src/api.js'

// 事件构造 (与 runs-reseed.test.js 同构)
const opStart = (rid = 'r1', extra = {}) =>
  ({ type: 'operation_start', run_id: rid, operation: 'root', label: 'root', ...extra })
const enter = (aid, op, action, script = 'root', rid = 'r1') =>
  ({ type: 'vm_node_enter', run_id: rid, op, aid, action, script })
const done = (aid, op, action, script = 'root', status = 'DONE', rid = 'r1') =>
  ({ type: 'vm_node_done', run_id: rid, op, aid, action, script, status, message: '完成', result: {} })
const opDone = (rid = 'r1', status = 'DONE') => ({ type: 'operation_done', run_id: rid, status })

function runningSteps(steps, out = []) {
  for (const s of steps) {
    if (s.status === 'RUNNING') out.push(`${s.script}|${s.step_id}`)
    if (s.children && s.children.length) runningSteps(s.children, out)
  }
  return out
}

function freshStore() {
  setActivePinia(createPinia())
  api.listRuns = async () => []
  api.getRun = async () => { throw new Error('未设 mock') }
  return useRunsStore()
}

// 冲刷 promise 微任务链 (mock 定时器不劫持 setImmediate)
const flush = () => new Promise((resolve) => setImmediate(resolve))

// 卡死复现素材: WS 静默丢掉终态三连 (done b/7 / operation_done), 树残留 RUNNING
const liveTruncated = [
  opStart(),
  enter('b/6', 'run_script', 'rail_move_safe'), done('b/6', 'run_script', 'rail_move_safe'),
  enter('b/7', 'run_script', 'robot_suction_pick'),
  enter('b/1', 'call', 'robot.home_ensure', 'robot_suction_pick'),
  done('b/1', 'call', 'robot.home_ensure', 'robot_suction_pick'),
]
// 权威存储 (RunStore): 完整含终态
const storedFull = [
  ...liveTruncated,
  done('b/7', 'run_script', 'robot_suction_pick'),
  opDone(),
]

test('对账收口: 存储已终态而投影仍 RUNNING -> reseedLive 整树重放, 闪烁消除', async () => {
  const runs = freshStore()
  for (const ev of liveTruncated) runs.ingest(ev)
  assert.deepEqual(runningSteps(runs.live.steps), ['root|b/7'])   // b/7 卡 RUNNING (子步已收)
  assert.equal(runs.live.status, 'RUNNING')

  api.listRuns = async () => [{ run_id: 'r1', operation: 'root', status: 'DONE' }]
  api.getRun = async () => ({ run_id: 'r1', status: 'DONE', events: storedFull })
  await runs.seedRecent()
  await runs.reconcileFromRecent()

  assert.equal(runs.live.status, 'DONE')
  assert.deepEqual(runningSteps(runs.live.steps), [])
})

test('对账守卫: 补种在途不重入 (防 epoch 互相作废活锁)', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  runs.ingest(enter('b/0', 'call', 'A'))

  let getRunCalls = 0
  api.getRun = () => { getRunCalls += 1; return new Promise(() => {}) }   // 永不 resolve: 补种一直在途
  api.listRuns = async () => [{ run_id: 'r1', status: 'DONE' }]
  runs.reseedLive()                       // 第一次补种在途 (reseedBuffer 激活)
  await runs.seedRecent()
  await runs.reconcileFromRecent()        // 在途守卫: 不得再发起 getRun
  assert.equal(getRunCalls, 1)
  runs.resetLive()                        // 清态停表: 防本例真实 interval 泄漏到后续用例污染共享 api mock
})

test('对账不动作: 存储记录仍 RUNNING / 记录缺失 / 投影已终态', async () => {
  const runs = freshStore()
  runs.ingest(opStart())
  runs.ingest(enter('b/0', 'call', 'A'))
  let getRunCalls = 0
  api.getRun = async () => { getRunCalls += 1; return { run_id: 'r1', status: 'RUNNING', events: [] } }

  api.listRuns = async () => [{ run_id: 'r1', status: 'RUNNING' }]   // 存储也 RUNNING: 无失配
  await runs.seedRecent()
  await runs.reconcileFromRecent()
  assert.equal(getRunCalls, 0)

  api.listRuns = async () => [{ run_id: 'other', status: 'DONE' }]   // 列表无本 run
  await runs.seedRecent()
  await runs.reconcileFromRecent()
  assert.equal(getRunCalls, 0)

  runs.ingest(done('b/0', 'call', 'A'))
  runs.ingest(opDone())                                              // 投影已终态: 无需对账
  api.listRuns = async () => [{ run_id: 'r1', status: 'DONE' }]
  await runs.seedRecent()
  await runs.reconcileFromRecent()
  assert.equal(getRunCalls, 0)
})

test('轮询自愈: RUNNING 期间 5s tick 自动对账收口, 终态后停表', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] })
  const runs = freshStore()
  let listCalls = 0
  api.listRuns = async () => { listCalls += 1; return [{ run_id: 'r1', operation: 'root', status: 'DONE' }] }
  api.getRun = async () => ({ run_id: 'r1', status: 'DONE', events: storedFull })

  for (const ev of liveTruncated) runs.ingest(ev)
  await flush()                            // ingest(opStart) 沿路的 seedRecent 落定
  const baseline = listCalls
  assert.deepEqual(runningSteps(runs.live.steps), ['root|b/7'])

  t.mock.timers.tick(5000)                 // 第一个 tick: seedRecent -> reconcile -> reseedLive
  await flush()
  await flush()
  assert.equal(listCalls, baseline + 1)
  assert.equal(runs.live.status, 'DONE')
  assert.deepEqual(runningSteps(runs.live.steps), [])

  t.mock.timers.tick(15000)                // 终态后停表: 不再产生轮询请求
  await flush()
  assert.equal(listCalls, baseline + 1)
})

test('手动单动作 (atomic) 不启表: 不入 RunStore 无对账源', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] })
  const runs = freshStore()
  let listCalls = 0
  api.listRuns = async () => { listCalls += 1; return [] }

  runs.ingest(opStart('m1', { atomic: true }))
  runs.ingest(enter('b/0', 'call', 'robot.home_ensure'))
  await flush()
  const baseline = listCalls               // ingest(opStart) 沿路 seedRecent 计入基线

  t.mock.timers.tick(20000)                // atomic 运行不启表: 无任何轮询请求
  await flush()
  assert.equal(listCalls, baseline)
  assert.equal(runs.live.status, 'RUNNING')   // 现状不受影响 (终态由 WS 四连事件自带)
})
