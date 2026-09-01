import test from 'node:test'
import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'

import { useDebugStore } from '../src/stores/debug.js'
import { api } from '../src/api.js'

function freshStore(runId = 'run-1') {
  setActivePinia(createPinia())
  const debug = useDebugStore()
  debug.ingest({ type: 'operation_start', run_id: runId, operation: 'root', execution_generation: 1 })
  return debug
}

function enter(debug, script, aid, op, action) {
  debug.ingest({ type: 'vm_node_enter', run_id: debug.runId, script, aid, op, action })
}

function done(debug, script, aid, op, action) {
  debug.ingest({ type: 'vm_node_done', run_id: debug.runId, script, aid, op, action,
                 status: 'DONE', message: '', result: {} })
}

test('嵌套脚本保持全部祖先与叶子高光，并按 script 隔离同号 AID', () => {
  const debug = freshStore()
  enter(debug, 'root', 'b/0', 'run_script', 'middle')
  enter(debug, 'middle', 'b/0', 'run_script', 'leaf')
  enter(debug, 'leaf', 'b/0', 'call', 'robot.move')

  assert.equal(debug.isNodeHighlighted('root', 'b/0'), true)
  assert.equal(debug.isNodeHighlighted('middle', 'b/0'), true)
  assert.equal(debug.isNodeHighlighted('leaf', 'b/0'), true)
  assert.equal(debug.isNodeHighlighted('other', 'b/0'), false)

  done(debug, 'leaf', 'b/0', 'call', 'robot.move')
  assert.equal(debug.isNodeHighlighted('leaf', 'b/0'), false)
  assert.equal(debug.isNodeHighlighted('middle', 'b/0'), true)
  assert.equal(debug.isNodeHighlighted('root', 'b/0'), true)

  done(debug, 'middle', 'b/0', 'run_script', 'leaf')
  assert.equal(debug.isNodeHighlighted('middle', 'b/0'), false)
  assert.equal(debug.isNodeHighlighted('root', 'b/0'), true)

  done(debug, 'root', 'b/0', 'run_script', 'middle')
  assert.equal(debug.isNodeHighlighted('root', 'b/0'), false)
})

test('重复活动实例按计数语义逐个退出', () => {
  const debug = freshStore()
  enter(debug, 'shared', 'b/2', 'call', 'A')
  enter(debug, 'shared', 'b/2', 'call', 'A')

  done(debug, 'shared', 'b/2', 'call', 'A')
  assert.equal(debug.isNodeActive('shared', 'b/2'), true)
  assert.equal(debug.activeNodes.length, 1)

  done(debug, 'shared', 'b/2', 'call', 'A')
  assert.equal(debug.isNodeActive('shared', 'b/2'), false)
})

test('vm_state 快照可恢复活动调用链，终态清空高光', () => {
  const debug = freshStore()
  debug.ingest({
    type: 'vm_state', run_id: debug.runId, status: 'RUNNING',
    script: 'leaf', current_aid: 'b/0',
    active_nodes: [
      { script: 'root', aid: 'b/1', op: 'run_script', action: 'leaf' },
      { script: 'leaf', aid: 'b/0', op: 'call', action: 'A' },
    ],
  })

  assert.equal(debug.isNodeHighlighted('root', 'b/1'), true)
  assert.equal(debug.isNodeHighlighted('leaf', 'b/0'), true)

  debug.ingest({ type: 'operation_done', run_id: debug.runId, status: 'DONE' })
  assert.equal(debug.activeNodes.length, 0)
  assert.equal(debug.isNodeHighlighted('leaf', 'b/0'), false)
})

test('单步、断点与 HITL 使用当前停驻位置兜底', () => {
  const debug = freshStore()
  for (const status of ['STOPPED', 'PAUSED', 'WAITING_HUMAN']) {
    debug.ingest({ type: 'vm_state', run_id: debug.runId, status,
                   script: 'root', current_aid: 'b/3', active_nodes: [] })
    assert.equal(debug.isNodeHighlighted('root', 'b/3'), true)
    assert.equal(debug.isNodeHighlighted('child', 'b/3'), false)
  }

  debug.ingest({ type: 'vm_state', run_id: debug.runId, status: 'DONE',
                 script: 'root', current_aid: 'b/3', active_nodes: [] })
  assert.equal(debug.isNodeHighlighted('root', 'b/3'), false)
})

test('重连优先恢复本地绑定 run，并忽略较旧 REST 活动快照', async () => {
  const debug = freshStore('run-a')
  const original = api.debugActive
  let resolveActive
  api.debugActive = () => new Promise((resolve) => { resolveActive = resolve })

  try {
    const seeding = debug.seedActive()
    debug.ingest({
      type: 'vm_node_enter', run_id: 'run-a', script: 'leaf', aid: 'b/0', op: 'call', action: 'A',
      active_revision: 3,
      active_nodes: [
        { script: 'root', aid: 'b/1', op: 'run_script', action: 'leaf' },
        { script: 'leaf', aid: 'b/0', op: 'call', action: 'A' },
      ],
    })
    resolveActive({ runs: [
      { run_id: 'run-a', operation: 'root', status: 'RUNNING', script: 'root', current_aid: 'b/1',
        active_revision: 2,
        active_nodes: [{ script: 'root', aid: 'b/1', op: 'run_script', action: 'leaf' }] },
      { run_id: 'run-b', operation: 'other', status: 'WAITING_HUMAN', pending_human: { req_id: 'h' },
        active_revision: 8, active_nodes: [] },
    ] })
    await seeding

    assert.equal(debug.runId, 'run-a')
    assert.equal(debug.isNodeActive('root', 'b/1'), true)
    assert.equal(debug.isNodeActive('leaf', 'b/0'), true)
  } finally {
    api.debugActive = original
  }
})

test('重连发现绑定运行已结束时清除旧活动高光', async () => {
  const debug = freshStore('run-ended')
  enter(debug, 'root', 'b/0', 'run_script', 'child')
  const original = api.debugActive
  api.debugActive = async () => ({ runs: [] })

  try {
    await debug.seedActive()
    assert.equal(debug.activeNodes.length, 0)
    assert.equal(debug.isNodeActive('root', 'b/0'), false)
  } finally {
    api.debugActive = original
  }
})

test('停驻运行在断线期间结束后空快照清除兜底高光', async () => {
  const debug = freshStore('run-stopped-ended')
  debug.ingest({ type: 'vm_state', run_id: 'run-stopped-ended', execution_generation: 1,
                 status: 'STOPPED', script: 'root', current_aid: 'b/3',
                 active_revision: 0, active_nodes: [] })
  assert.equal(debug.isNodeHighlighted('root', 'b/3'), true)

  const original = api.debugActive
  api.debugActive = async () => ({ runs: [] })
  try {
    await debug.seedActive()
    assert.equal(debug.status, 'idle')
    assert.equal(debug.currentAid, '')
    assert.equal(debug.currentScript, '')
    assert.equal(debug.isNodeHighlighted('root', 'b/3'), false)
  } finally {
    api.debugActive = original
  }
})

test('同活动版本的旧 REST 不回退 WebSocket 已更新的停驻行', async () => {
  const debug = freshStore('run-stop')
  const original = api.debugActive
  let resolveActive
  api.debugActive = () => new Promise((resolve) => { resolveActive = resolve })

  try {
    const seeding = debug.seedActive()
    debug.ingest({ type: 'vm_state', run_id: 'run-stop', execution_generation: 1,
                   status: 'STOPPED', script: 'root', current_aid: 'b/2',
                   active_revision: 0, active_nodes: [] })
    resolveActive({ runs: [{ run_id: 'run-stop', operation: 'root', execution_generation: 1,
                             status: 'STOPPED', script: 'root', current_aid: 'b/1',
                             active_revision: 0, active_nodes: [] }] })
    await seeding

    assert.equal(debug.currentAid, 'b/2')
    assert.equal(debug.isNodeHighlighted('root', 'b/2'), true)
    assert.equal(debug.isNodeHighlighted('root', 'b/1'), false)
  } finally {
    api.debugActive = original
  }
})

test('断线期间同 run 复位后接受新执行代次的低版本活动快照', async () => {
  const debug = freshStore('run-reset')
  debug.ingest({ type: 'vm_node_enter', run_id: 'run-reset', execution_generation: 1,
                 script: 'old', aid: 'b/0', op: 'call', action: 'A',
                 active_revision: 5,
                 active_nodes: [{ script: 'old', aid: 'b/0', op: 'call', action: 'A' }] })
  const original = api.debugActive
  api.debugActive = async () => ({ runs: [{
    run_id: 'run-reset', operation: 'new', execution_generation: 2,
    status: 'STOPPED', script: 'new', current_aid: 'b/0',
    active_revision: 0, active_nodes: [],
  }] })

  try {
    await debug.seedActive()
    assert.equal(debug.currentScript, 'new')
    assert.equal(debug.currentAid, 'b/0')
    assert.equal(debug.activeNodes.length, 0)
    assert.equal(debug.isNodeHighlighted('new', 'b/0'), true)

    debug.ingest({ type: 'vm_node_enter', run_id: 'run-reset', execution_generation: 1,
                   script: 'old', aid: 'b/9', op: 'call', action: 'STALE',
                   active_revision: 99,
                   active_nodes: [{ script: 'old', aid: 'b/9', op: 'call', action: 'STALE' }] })
    assert.equal(debug.currentScript, 'new')
    assert.equal(debug.activeNodes.length, 0)
  } finally {
    api.debugActive = original
  }
})

test('漏收 operation_start 时新执行代次的节点事件仍重新开启高光', () => {
  const debug = freshStore('run-reconnect')
  debug.ingest({ type: 'operation_done', run_id: 'run-reconnect', execution_generation: 1,
                 status: 'DONE', active_revision: 0, active_nodes: [] })
  assert.equal(debug.status, 'DONE')

  debug.ingest({ type: 'vm_node_enter', run_id: 'run-reconnect', execution_generation: 2,
                 script: 'new', aid: 'b/0', op: 'call', action: 'A',
                 active_revision: 1,
                 active_nodes: [{ script: 'new', aid: 'b/0', op: 'call', action: 'A' }] })
  assert.equal(debug.status, 'RUNNING')
  assert.equal(debug.isNodeHighlighted('new', 'b/0'), true)
})

test('新代次首个事件为 node_done 时也不会沿用旧终态', () => {
  const debug = freshStore('run-reconnect-done-first')
  debug.ingest({ type: 'operation_done', run_id: 'run-reconnect-done-first', execution_generation: 1,
                 status: 'DONE', active_revision: 0, active_nodes: [] })

  debug.ingest({ type: 'vm_node_done', run_id: 'run-reconnect-done-first', execution_generation: 2,
                 script: 'new', aid: 'b/0', op: 'call', action: 'A', status: 'DONE',
                 active_revision: 1, active_nodes: [] })
  debug.ingest({ type: 'vm_node_enter', run_id: 'run-reconnect-done-first', execution_generation: 2,
                 script: 'new', aid: 'b/1', op: 'call', action: 'B',
                 active_revision: 2,
                 active_nodes: [{ script: 'new', aid: 'b/1', op: 'call', action: 'B' }] })

  assert.equal(debug.status, 'RUNNING')
  assert.equal(debug.isNodeHighlighted('new', 'b/1'), true)
})

test('旧代次刚结束时重连仍优先恢复同 run 的新代次', async () => {
  const debug = freshStore('run-a')
  debug.ingest({ type: 'operation_failed', run_id: 'run-a', execution_generation: 1,
                 status: 'ERROR', active_revision: 1, active_nodes: [] })
  const original = api.debugActive
  api.debugActive = async () => ({ runs: [
    { run_id: 'run-a', operation: 'new-root', execution_generation: 2,
      status: 'RUNNING', script: 'new-root', current_aid: 'b/0', active_revision: 0,
      active_nodes: [{ script: 'new-root', aid: 'b/0', op: 'run_script', action: 'leaf' }] },
    { run_id: 'run-b', operation: 'other', execution_generation: 1,
      status: 'WAITING_HUMAN', pending_human: { req_id: 'h' },
      active_revision: 3, active_nodes: [] },
  ] })

  try {
    await debug.seedActive()
    assert.equal(debug.runId, 'run-a')
    assert.equal(debug.operation, 'new-root')
    assert.equal(debug.status, 'RUNNING')
    assert.equal(debug.isNodeActive('new-root', 'b/0'), true)
  } finally {
    api.debugActive = original
  }
})
