// 多运行通道化 (并行调度) 的新语义: 按 run_id 路由、互不串扰、选中/跟随、剪枝、逐通道补种
import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'

import { useRunsStore } from '../src/stores/runs.js'
import { api } from '../src/api.js'

const opStart = (rid, extra = {}) => ({ type: 'operation_start', run_id: rid, operation: `op-${rid}`, label: rid, ...extra })
const enter = (rid, aid, action) => ({ type: 'vm_node_enter', run_id: rid, op: 'call', aid, action, script: 'root' })
const done = (rid, aid, action, status = 'DONE') =>
  ({ type: 'vm_node_done', run_id: rid, op: 'call', aid, action, script: 'root', status, message: '', result: {} })
const opDone = (rid, status = 'DONE') => ({ type: 'operation_done', run_id: rid, status })

function freshStore() {
  setActivePinia(createPinia())
  api.listRuns = async () => []
  return useRunsStore()
}

test('双运行交错事件: 两棵树互不污染, live 跟随最新启动', () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.ingest(opStart('B'))
  runs.ingest(enter('A', 'b/0', 'sampling.init'))
  runs.ingest(enter('B', 'b/0', 'develop.init'))
  runs.ingest(done('A', 'b/0', 'sampling.init'))
  assert.equal(runs.activeById['A'].steps[0].action, 'sampling.init')
  assert.equal(runs.activeById['A'].steps[0].status, 'DONE')
  assert.equal(runs.activeById['B'].steps[0].action, 'develop.init')
  assert.equal(runs.activeById['B'].steps[0].status, 'RUNNING')
  // 未 pin: live 跟随最新启动 (B)
  assert.equal(runs.live.run_id, 'B')
  assert.deepEqual(runs.runOrder, ['A', 'B'])
})

test('select pin 后不被新 operation_start 抢走; 通道消失回退跟随', () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.select('A')
  runs.ingest(opStart('B'))
  assert.equal(runs.live.run_id, 'A', 'pin 在 A, 新运行 B 不得抢焦点')
  runs.select('C')                       // 不存在的通道 -> 清 pin 回退跟随
  assert.equal(runs.live.run_id, 'B')
})

test('未知 run_id 事件丢弃 (不产生幽灵通道/状态残留)', () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.ingest(opDone('GHOST', 'FAILED'))
  assert.equal(runs.runOrder.length, 1)
  assert.equal(runs.activeById['A'].status, 'RUNNING')
})

test('终态通道保序剪枝: 终态最多 3 条, RUNNING 永不剪', () => {
  const runs = freshStore()
  for (const rid of ['R1', 'R2', 'R3', 'R4']) {
    runs.ingest(opStart(rid))
    runs.ingest(opDone(rid))
  }
  runs.ingest(opStart('LIVE'))
  // R1..R4 终态 4 条 > 3, 最旧 R1 被剪; LIVE 运行中保留
  assert.ok(!runs.activeById['R1'], 'R1 应被剪枝')
  assert.ok(runs.activeById['R2'] && runs.activeById['R3'] && runs.activeById['R4'])
  assert.equal(runs.live.run_id, 'LIVE')
  assert.equal(runs.activeRuns.length, 4)
})

test('单通道补种不动他通道 (mock getRun 按 id 分流)', async () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.ingest(enter('A', 'b/0', 'x'))
  runs.ingest(opStart('B'))
  runs.ingest(enter('B', 'b/0', 'y'))
  api.getRun = async (id) => {
    assert.equal(id, 'A')
    return { run_id: 'A', status: 'DONE', events: [
      opStart('A'), enter('A', 'b/0', 'x'), done('A', 'b/0', 'x'), opDone('A'),
    ] }
  }
  await runs.reseedLive('A')
  assert.equal(runs.activeById['A'].status, 'DONE')
  assert.equal(runs.activeById['A'].steps[0].status, 'DONE')
  assert.equal(runs.activeById['B'].status, 'RUNNING', 'B 通道不得被 A 的补种触碰')
  assert.equal(runs.activeById['B'].steps[0].status, 'RUNNING')
})

test('对账只补终态失配的通道 (A 终态而 B 仍运行)', async () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.ingest(opStart('B'))
  const fetched = []
  api.listRuns = async () => [{ run_id: 'A', status: 'DONE' }, { run_id: 'B', status: 'RUNNING' }]
  api.getRun = async (id) => {
    fetched.push(id)
    return { run_id: id, status: 'DONE', events: [opStart(id), opDone(id)] }
  }
  await runs.seedRecent()
  await runs.reconcileFromRecent()
  assert.deepEqual(fetched, ['A'], '只有权威说终态的 A 被补种')
  assert.equal(runs.activeById['A'].status, 'DONE')
  assert.equal(runs.activeById['B'].status, 'RUNNING')
})

test('atomic 手动运行不入对账; meta 随 operation_start 透传不破坏投影', () => {
  const runs = freshStore()
  runs.ingest(opStart('M', { atomic: true }))
  runs.ingest(opStart('S', { meta: { origin: 'scheduler', sample_id: 'T-01', batch_id: 'B1' } }))
  api.listRuns = async () => [{ run_id: 'M', status: 'DONE' }]
  const fetched = []
  api.getRun = async (id) => { fetched.push(id); throw new Error('404') }
  runs.reconcileFromRecent()
  assert.deepEqual(fetched, [], 'atomic 通道不发对账请求')
  assert.equal(runs.activeById['S'].operation, 'op-S')
})

test('resetLive 清空全部通道', () => {
  const runs = freshStore()
  runs.ingest(opStart('A'))
  runs.ingest(opStart('B'))
  runs.resetLive()
  assert.equal(runs.runOrder.length, 0)
  assert.equal(runs.live.run_id, '')
})
