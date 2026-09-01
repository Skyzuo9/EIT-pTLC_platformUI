// 调试 store: VM 运行/单步/暂停/停止/复位 + 实时当前节点 (AID) / 变量快照 / 日志 / HITL
import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { api } from '../api.js'
import { isIdle } from '../utils/runControl.js'

const LOG_CAP = 500
const STOPPED_HIGHLIGHT_STATES = new Set(['STOPPED', 'PAUSED', 'WAITING_HUMAN'])

export const useDebugStore = defineStore('debug', () => {
  const runId = ref('')
  const operation = ref('')           // 本次运行归属的流程名 (调试坞据此判断"运行"是起跑当前流程还是别处已在跑)
  const operationAtomic = ref(false)  // 本次运行是否单原子动作 (operation=动作 id 而非脚本名; 前端不据此跳编辑页, 审阅 #6)
  const status = ref('idle')          // idle | NEW | RUNNING | STOPPED | PAUSED | WAITING_HUMAN | DONE | ERROR | KILLED
  const currentAid = ref('')
  const currentScript = ref('')
  const activeNodes = ref([])         // 尚未完成的 call/run_script；允许重复实例，身份为 script+aid+op+action
  const snapshot = reactive({})       // 变量名 -> {value,type,scope}
  const logs = ref([])                // 执行日志行
  const hitl = ref(null)              // {req_id, kind, prompt, fields, image, aid}
  const breakpoints = ref([])
  const hold = ref('none')            // none | frozen(冻结在飞运动) | at_boundary(跑完当前动作停在边界)
  const hitlMinimized = ref(false)    // HITL「稍后处理」最小化标记; 新门到达/hitl 清空时复位

  // 服务端活动快照单调版本；旧 REST/WS 快照不得覆盖较新的节点事件。
  let activeNodesRevision = -1
  // 同一 run_id 的 reset 代次，以及已接收的实时调试事件代数。
  let executionGeneration = 0
  let wsStateGeneration = 0

  function _replaceActiveNodes(nodes, revision = null) {
    const serverRevision = Number.isInteger(revision) ? revision : null
    if (serverRevision != null && serverRevision < activeNodesRevision) return false
    activeNodes.value = (nodes || []).map((node) => ({
      script: node.script || '', aid: node.aid || '', op: node.op || '', action: node.action || '',
    }))
    activeNodesRevision = serverRevision ?? (activeNodesRevision + 1)
    return true
  }

  function _clearActiveNodes(revision = null) {
    return _replaceActiveNodes([], revision)
  }

  function _resetActiveNodes() {
    activeNodes.value = []
    activeNodesRevision = 0
  }

  function _prepareExecution(state, { allowRunChange = false } = {}) {
    const incomingRun = state?.run_id || ''
    if (incomingRun && incomingRun !== runId.value) {
      if (!allowRunChange && runId.value) return false
      runId.value = incomingRun
      executionGeneration = 0
      _resetActiveNodes()
    }
    const incomingGeneration = Number.isInteger(state?.execution_generation)
      ? state.execution_generation : null
    if (incomingGeneration != null && incomingGeneration < executionGeneration) return false
    if (incomingGeneration != null && incomingGeneration > executionGeneration) {
      executionGeneration = incomingGeneration
      _resetActiveNodes()
      // 断线重连可能先收到新代次的节点事件而错过 operation_start；此时旧终态不能压住新高光。
      // vm_node_done.status 是节点结果而非线程状态，不能据其 DONE 判断整个执行已结束。
      if (state?.type === 'vm_human_request') status.value = 'WAITING_HUMAN'
      else if (state?.type && !['vm_state', 'operation_done', 'operation_failed'].includes(state.type)) {
        status.value = 'RUNNING'
      }
    }
    return true
  }

  function _nodeRef(event) {
    return { script: event.script || '', aid: event.aid || '',
             op: event.op || '', action: event.action || '' }
  }

  function _sameNodeInstance(a, b) {
    return a.script === b.script && a.aid === b.aid && a.op === b.op && a.action === b.action
  }

  function _enterActiveNode(event) {
    if (!event.script || !event.aid) return
    activeNodes.value.push(_nodeRef(event))
    activeNodesRevision += 1
  }

  function _leaveActiveNode(event) {
    const ref = _nodeRef(event)
    for (let i = activeNodes.value.length - 1; i >= 0; i--) {
      if (_sameNodeInstance(activeNodes.value[i], ref)) {
        activeNodes.value.splice(i, 1)
        activeNodesRevision += 1
        return
      }
    }
  }

  function isNodeActive(script, aid) {
    return activeNodes.value.some((node) => node.script === script && node.aid === aid)
  }

  function isNodeHighlighted(script, aid) {
    if (isIdle(status.value)) return false
    if (isNodeActive(script, aid)) return true
    return STOPPED_HIGHLIGHT_STATES.has(status.value)
      && currentScript.value === script && currentAid.value === aid
  }

  function _apply(state, { applyActiveNodes = true, applyRuntimeState = true } = {}) {
    if (!state) return
    if (!_prepareExecution(state, { allowRunChange: true })) return false
    if (applyRuntimeState) {
      status.value = state.status || status.value
      currentAid.value = state.current_aid || ''
      if (state.script) currentScript.value = state.script
      if (state.hold != null) hold.value = state.hold
    }
    if (applyActiveNodes && Array.isArray(state.active_nodes)) {
      _replaceActiveNodes(state.active_nodes, state.active_revision)
    }
    return true
  }

  function _log(line) {
    logs.value.push(line)
    if (logs.value.length > LOG_CAP) logs.value.splice(0, logs.value.length - LOG_CAP)
  }

  // ---- 调试动词 ----
  async function start(name, inputs, mode, modeRun, startAid, overrides) {
    logs.value = []
    for (const k of Object.keys(snapshot)) delete snapshot[k]
    hitl.value = null
    hitlMinimized.value = false
    hold.value = 'none'
    _resetActiveNodes()
    const state = await api.debugRun(name, inputs, mode, modeRun, startAid, overrides)
    operation.value = name
    _apply(state)
    const nOver = overrides ? Object.keys(overrides).length : 0
    _log(`▶ 启动 ${name} (${modeRun}${startAid ? ' @' + startAid : ''}${nOver ? ` ·覆盖${nOver}项` : ''}) run=${runId.value}`)
  }
  async function step() { _apply(await api.debugStep(runId.value)) }            // 步入: 进入子流程逐叶停驻
  async function stepOver() { _apply(await api.debugStepOver(runId.value)) }     // 步过: 子流程一次跑完停在父流程下一步
  async function cont() { _apply(await api.debugContinue(runId.value)) }
  async function pause() { _apply(await api.debugPause(runId.value)) }          // 暂停: 冻结在飞运动
  async function stopAfter() { _apply(await api.debugStopAfter(runId.value)) }  // 运行后停止: 边界停驻
  async function resume() { _apply(await api.debugResume(runId.value)) }        // 继续: 按 hold 续跑/放行
  async function terminate() { _apply(await api.debugTerminate(runId.value)) }  // 终止运行: 软停 + 干净结束
  async function estop() { _apply(await api.debugEstop(runId.value)) }          // 急停: 失能报警 + 结束
  async function reset(aid) { _apply(await api.debugReset(runId.value, aid)) }
  // 显式结束本次调试会话 (软停后端 run + 清本地绑定回 idle)。
  // 注意: 不再在"切换被编辑流程"时调用 —— 浏览别的流程属只读导航, 不得终结在跑的运行。
  // (调试坞据 operation 归属判定"运行"语义, 见 utils/runControl.js。)
  async function endSession() {
    const id = runId.value
    const active = id && !['idle', 'NEW', 'DONE', 'ERROR', 'KILLED', ''].includes(status.value)
    if (active) { try { await api.debugTerminate(id) } catch (e) { /* 后端无此 run / 已结束: 直接清本地 */ } }
    runId.value = ''
    operation.value = ''
    operationAtomic.value = false
    status.value = 'idle'
    currentAid.value = ''
    currentScript.value = ''
    _resetActiveNodes()
    executionGeneration = 0
    hitl.value = null
    hitlMinimized.value = false
    hold.value = 'none'
    breakpoints.value = []
    logs.value = []
    for (const k of Object.keys(snapshot)) delete snapshot[k]
  }
  async function toggleBreakpoint(aid) {
    const i = breakpoints.value.indexOf(aid)
    if (i >= 0) breakpoints.value.splice(i, 1)
    else breakpoints.value.push(aid)
    if (runId.value) await api.setBreakpoints(runId.value, breakpoints.value)
  }
  async function replyHuman(payload) {
    if (!hitl.value) return
    // 清 hitl 前校验 req_id 未变: await 期间下一道门的请求可能到达 (新连门流程放大此竞态),
    // 无守卫地清会误清掉刚到的新请求 → VM 卡 WAITING_HUMAN 却无弹窗 (审阅 #5)。
    const rid = hitl.value.req_id
    await api.hitlReply(runId.value, rid, payload)
    if (hitl.value?.req_id === rid) { hitl.value = null; hitlMinimized.value = false }
  }

  // 从服务端重建活跃运行 + 挂起 HITL 门 (App 挂载与 WS 重连沿调用)。
  // HITL 仍只填充不清除 (spec D3)，避免旧 REST 快照覆盖在途 WS 门事件；active_nodes 则由
  // active_revision 判新旧，可安全恢复或在确认运行已结束后清空。
  async function seedActive() {
    const reqBefore = hitl.value?.req_id   // 发起 REST 前快照当前门 req_id (下方在途竞态守卫比对)
    const wsGenerationBefore = wsStateGeneration
    const runBefore = runId.value
    let runs
    try { runs = (await api.debugActive()).runs || [] } catch (e) { return }  // 拉取失败静默; 下个重连沿再试
    const localIdle = !runId.value || isIdle(status.value)
    // 即使本地刚收到旧代次的终态，同 run_id 也可能已经 reset 并启动了新代次；始终先找回绑定 run。
    // 只有服务端确认它不存在且本地已空闲时，才接管待人工确认或列表中的其它运行。
    const bound = runs.find((r) => r.run_id === runId.value)
    const target = bound || (localIdle
      ? (runs.find((r) => r.pending_human) || runs[runs.length - 1])
      : undefined)
    if (!target) {
      // 断线期间运行已经结束：只有在 REST 往返中没有更实时的本地变化时才收口旧会话。
      // 仅清 active_nodes 不够，STOPPED/PAUSED/HITL 的停驻位置兜底仍会留下黄色高光。
      if (runId.value === runBefore && wsStateGeneration === wsGenerationBefore) {
        _clearActiveNodes()
        status.value = 'idle'
        currentAid.value = ''
        currentScript.value = ''
        hold.value = 'none'
        hitl.value = null
        hitlMinimized.value = false
      }
      return
    }
    const targetGeneration = Number.isInteger(target.execution_generation)
      ? target.execution_generation : null
    const executionAdvanced = target.run_id !== runId.value
      || (targetGeneration != null && targetGeneration > executionGeneration)
    // active_revision 决定 REST/WS 新旧；节点事件本身也带完整快照，不会因漏收祖先 enter 而残缺。
    const applied = _apply(target, {
      applyRuntimeState: executionAdvanced || wsStateGeneration === wsGenerationBefore,
    })
    if (!applied) return
    operation.value = target.operation || operation.value
    operationAtomic.value = false                            // active 只含 VM 流程 (单动作不经 VmController)
    const p = target.pending_human
    // 在途竞态守卫: await 期间 WS 事件已更换门 (答旧门/来新门) — 实时序比 REST 快照新, 快照作废不回填
    if (hitl.value?.req_id !== reqBefore) return
    if (p && (!hitl.value || hitl.value.req_id !== p.req_id)) {
      hitl.value = { req_id: p.req_id, kind: p.kind, prompt: p.prompt, fields: p.fields || [],
                     image: p.image, options: p.options || [], context: p.context, aid: p.aid }
      hitlMinimized.value = false
    }
  }

  // ---- WS 事件消费 (在 App.vue onEvent 注册) ----
  function ingest(event) {
    const t = event.type || ''
    // operation_start 必须先于下面的 runId 守卫处理 (对照 runs.js): 被动标签/刷新页/他人屏幕此刻
    // runId 尚未绑定, 守卫会先 return, 之后的 vm_state 也进不来 —— 结果 operation='' 且 status 停在
    // idle, 归属守卫 (isRunActiveElsewhere) false-open, 在别的流程页点"运行"会误起跑/续跑 (审阅 #2)。
    // 故这里据 operation_start 回灌 runId+operation(+status) 让本地 latch 到在跑的 run;
    // 仅在本地空闲或正是本 run 时接管, 不抢占正在调试/挂起的本地会话。
    if (t === 'operation_start') {
      const localIdle = !runId.value || isIdle(status.value)
      if (localIdle || event.run_id === runId.value) {
        if (!_prepareExecution(event, { allowRunChange: true })) return
        operation.value = event.operation || ''
        operationAtomic.value = !!event.atomic   // VM 流程不带 atomic → false; 单动作 (app.py runAction) 带 true
        wsStateGeneration += 1
        if (localIdle) status.value = 'RUNNING'
      }
      return
    }
    if (!event.run_id || event.run_id !== runId.value) return
    if (!_prepareExecution(event)) return
    if (['vm_state', 'vm_hold', 'vm_node_enter', 'vm_node_done', 'vm_human_request',
         'vm_human_reply', 'operation_failed', 'operation_done'].includes(t)) {
      wsStateGeneration += 1
    }
    if (t === 'vm_state') {
      _apply(event)
      // 运行终结即清挂起 (自然 DONE 不发 vm_hold; terminate/resume 才发)
      if (['DONE', 'ERROR', 'KILLED'].includes(event.status)) {
        if (!Array.isArray(event.active_nodes)) _clearActiveNodes()
        hold.value = 'none'
        // 第 6 复位点: 门挂起时 terminate/estop 走 CancelledError 路径, 后端只发 operation_failed +
        // 终态 vm_state, 不发 vm_human_reply —— 终态是唯一收口。不清则等待人工徽标对着已死的 run
        // 持续脉冲, 且陈旧 HITL 弹窗留屏。后端终态时 _op_human 的 finally 必已清 pending payload, 本地与真源一致。
        hitl.value = null
        hitlMinimized.value = false
      }
    } else if (t === 'vm_hold') {
      hold.value = event.hold || 'none'
    } else if (t === 'vm_vars') {
      for (const k of Object.keys(snapshot)) delete snapshot[k]
      Object.assign(snapshot, event.vars || {})
    } else if (t === 'vm_node_enter') {
      // AID 为帧内地址 (父子脚本同从 b/0 编号), 必须与所属脚本成对; 否则子脚本叶子的 aid 会误高亮父流程同号行
      if (Array.isArray(event.active_nodes)) {
        _replaceActiveNodes(event.active_nodes, event.active_revision)
      } else {
        _enterActiveNode(event)
      }
      currentAid.value = event.aid || currentAid.value
      if (event.script) currentScript.value = event.script
    } else if (t === 'vm_node_done') {
      if (Array.isArray(event.active_nodes)) {
        _replaceActiveNodes(event.active_nodes, event.active_revision)
      } else {
        _leaveActiveNode(event)
      }
      const tag = event.status && event.status !== 'DONE' ? ` [${event.status}]` : ''
      // 前缀所属脚本名: 子流程与父流程的 AID 同为帧内地址 (如父子皆 b/1), 标出脚本名方能区分
      const where = event.script ? `${event.script} ` : ''
      _log(`· ${where}${event.aid} ${event.op}${event.action ? ' ' + event.action : ''}${tag}${event.message ? ' — ' + event.message : ''}`)
    } else if (t === 'vm_human_request') {
      hitl.value = { req_id: event.req_id, kind: event.kind, prompt: event.prompt, fields: event.fields || [], image: event.image, options: event.options || [], context: event.context, aid: event.aid }
      hitlMinimized.value = false
    } else if (t === 'vm_human_reply') {
      hitl.value = null; hitlMinimized.value = false
    } else if (t === 'operation_failed') {
      // 终态必须在此收口: 单动作运行 (runAction 路径, 如"回原点"/robot.home) 只发 operation_*,
      // 不发 vm_state; 若只靠 vm_state 收 status, 单动作跑完后 status 卡 RUNNING →
      // isRunActiveElsewhere 恒真, 别的流程"运行/步过"被锁并提示"上一个flow未完成"。
      // (VM 运行随后仍会来一帧 vm_state 覆盖, 终态值一致, 无副作用。)
      status.value = 'ERROR'
      if (Array.isArray(event.active_nodes)) {
        _replaceActiveNodes(event.active_nodes, event.active_revision)
      } else {
        _clearActiveNodes()
      }
      hold.value = 'none'
      hitl.value = null
      hitlMinimized.value = false
      _log(`✖ 结束: ${event.status} ${event.message || ''}`)
    } else if (t === 'operation_done') {
      status.value = 'DONE'
      if (Array.isArray(event.active_nodes)) {
        _replaceActiveNodes(event.active_nodes, event.active_revision)
      } else {
        _clearActiveNodes()
      }
      hold.value = 'none'
      _log('✔ 完成')
    }
  }

  return {
    runId, operation, operationAtomic, status, currentAid, currentScript, activeNodes,
    snapshot, logs, hitl, hitlMinimized, breakpoints, hold,
    isNodeActive, isNodeHighlighted,
    start, step, stepOver, cont, pause, stopAfter, resume, terminate, estop, reset, endSession, toggleBreakpoint, replyHuman, seedActive, ingest,
  }
})
