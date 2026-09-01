/**
 * 功能: 沙盒运行状态的纯 reducer (node 可测, 不碰 Vue/全局 store).
 *
 * 词汇表与 stores/debug.js 的 ingest 分支同构的单会话简化版: 只跟一个 run_id,
 * 供 /3d/sim 的运行面板画 状态/当前节点/日志/HITL 门。绝不喂给全局 debug store ——
 * 那是真机调试台的地盘, 沙盒运行不该出现在那里。
 */

/** 功能: 空运行状态. @returns {object} */
export function createRunState() {
  return {
    runId: null,
    operation: '',
    status: 'IDLE',            // IDLE | RUNNING | PAUSED | WAITING_HUMAN | DONE | ERROR | KILLED
    currentAid: null,
    activeNodes: [],           // [{aid, label, action, script}] 入栈序
    human: null,               // {reqId, kind, title, message, options}
    error: '',
    logs: [],                  // [{ts, text}] 最近 N 条
  }
}

const MAX_LOGS = 80
const FINAL = new Set(['DONE', 'ERROR', 'KILLED'])

function pushLog(state, ts, text) {
  state.logs.push({ ts: ts || Date.now() / 1000, text })
  if (state.logs.length > MAX_LOGS) state.logs.splice(0, state.logs.length - MAX_LOGS)
}

/**
 * 功能: 用 /api/sim/session 返回的活动运行快照恢复单运行面板.
 *
 * 页面可能在 UniLab 从外部启动 operation 之后才打开，此时 WebSocket 不会重放已经发生的
 * operation_start / vm_human_request。轮询快照是刷新后的权威恢复面，待人工确认的运行优先
 * 于其它并发运行，避免安全门藏在 IDLE 面板后面。
 *
 * @param {object} state createRunState 的产物
 * @param {Array<object>} runs 活动运行快照
 * @returns {boolean} 是否更新了状态
 */
export function reconcileActiveRuns(state, runs) {
  const active = Array.isArray(runs) ? runs.filter((run) => run?.run_id) : []
  if (!active.length) {
    if (state.runId && !FINAL.has(state.status)) {
      state.runId = null
      state.operation = ''
      state.status = 'IDLE'
      state.currentAid = null
      state.activeNodes = []
      state.human = null
      state.error = ''
      return true
    }
    return false
  }

  const current = active.find((run) => run.run_id === state.runId)
  const target = current
    || active.find((run) => String(run.status || '').toUpperCase() === 'WAITING_HUMAN')
    || active[0]
  const changedRun = state.runId !== target.run_id
  const pending = target.pending_human

  state.runId = target.run_id
  state.operation = target.operation || target.script || ''
  state.status = String(target.status || 'RUNNING').toUpperCase()
  state.currentAid = target.current_aid ?? null
  state.activeNodes = Array.isArray(target.active_nodes)
    ? target.active_nodes.map((node) => ({
      aid: node.aid,
      label: node.label || node.action || node.script || node.aid,
      action: node.action || null,
      script: node.script || null,
    }))
    : []
  state.human = pending ? {
    reqId: pending.req_id,
    kind: pending.kind || 'confirm',
    title: pending.title || '',
    message: pending.prompt || pending.message || pending.text || '',
    options: pending.options ?? pending.choices ?? null,
  } : null
  state.error = target.error || ''
  if (changedRun) {
    state.logs.splice(0)
    pushLog(state, target.ts, `恢复活动运行 ${state.operation}`)
  }
  return true
}

/**
 * 功能: 吞一条沙盒事件, 就地更新状态.
 * @param {object} state createRunState 的产物
 * @param {object} event 沙盒事件
 * @returns {boolean} 是否有变化 (供 Vue 侧决定要不要触发响应式版本号)
 */
export function ingest(state, event) {
  const type = event?.type
  if (!type) return false
  if (type === 'operation_start') {
    // 只认自己启动的那次运行 (runId 由 start 返回后写入); 未绑定时首个 start 认领
    if (state.runId && event.run_id !== state.runId) return false
    state.runId = event.run_id
    state.operation = event.operation || event.name || state.operation
    state.status = 'RUNNING'
    state.error = ''
    state.activeNodes = []
    state.human = null
    pushLog(state, event.ts, `开始运行 ${state.operation}`)
    return true
  }
  if (state.runId && event.run_id && event.run_id !== state.runId) return false
  switch (type) {
    case 'vm_state': {
      const status = String(event.status || '').toUpperCase()
      if (status) state.status = status
      if (event.current_aid !== undefined) state.currentAid = event.current_aid
      return true
    }
    case 'vm_node_enter': {
      state.activeNodes.push({
        aid: event.aid, label: event.label || event.action || event.script || event.aid,
        action: event.action || null, script: event.script || null,
      })
      pushLog(state, event.ts, `▶ ${event.label || event.action || event.aid}`)
      return true
    }
    case 'vm_node_done': {
      const index = state.activeNodes.findLastIndex((n) => n.aid === event.aid)
      if (index >= 0) state.activeNodes.splice(index, 1)
      if (event.ok === false) pushLog(state, event.ts, `✗ ${event.label || event.aid}: ${event.error || '失败'}`)
      return true
    }
    case 'vm_human_request': {
      state.status = 'WAITING_HUMAN'
      state.human = {
        reqId: event.req_id, kind: event.kind || 'confirm',
        title: event.title || '', message: event.message || event.text || '',
        options: event.options || event.choices || null,
      }
      pushLog(state, event.ts, `⏸ 人工门: ${state.human.title || state.human.kind}`)
      return true
    }
    case 'vm_human_reply': {
      state.human = null
      return true
    }
    case 'operation_done': {
      state.status = 'DONE'
      state.human = null
      pushLog(state, event.ts, '✓ 运行完成')
      return true
    }
    case 'operation_failed': {
      state.status = 'ERROR'
      state.error = event.error || event.message || '运行失败'
      state.human = null
      pushLog(state, event.ts, `✗ 运行失败: ${state.error}`)
      return true
    }
    default:
      return false
  }
}

/** 功能: 是否终态. @param {object} state @returns {boolean} */
export function isFinal(state) {
  return FINAL.has(state.status)
}
