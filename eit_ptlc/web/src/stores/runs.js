// 执行 store: 实时运行多通道投影 (并行调度下同时多条) + 历史运行列表 (供执行视图/回放)
// 多通道化 (并行实验系统): 内部按 run_id 一条通道一棵树; 对外 activeById/runOrder/select,
// 兼容层 live = 选中通道 (未选中即最新), 旧消费者 (MonitorDock/StatusBar/单测) 读法不变。
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'

// 由有序事件序列重建一次运行 (回放与实时同源的纯函数)。
// 步骤树按脚本帧嵌套: run_script 步为父, 其子脚本内的 call/run_script 挂在它 children 下。
// 键按帧内 aid, 但每帧只在自己的 children 内匹配 -> 父子同号 aid (皆从 b/0 编号) 落不同数组, 不再互相覆盖。
export function reduceRun(events) {
  const run = { run_id: '', operation: '', label: '', status: '', message: '', steps: [] }
  const ctx = { stack: [{ children: run.steps }] }   // 栈底哨兵: children 即根步骤数组
  for (const event of events || []) applyEvent(run, ctx, event)
  return run
}

function makeStep(event) {
  return {
    step_id: event.aid,                        // 帧内地址 (供显示, 如 b/0/elif1/3)
    script: event.script || '',                // 所属脚本名 (跨帧区分)
    op: event.op,                              // call | run_script
    action: event.action || event.op,          // 动作名/子脚本名; 缺失退化为 op
    status: 'RUNNING',
    message: '',
    result: null,
    ts: event.ts || null,                      // 进入时刻 (epoch 秒); 三维时间线的"时间"列用
    doneTs: null,                              // 完成时刻; 与 ts 之差即该步耗时
    children: [],                              // 仅 run_script 非空
  }
}

function fillDone(step, event) {
  step.status = event.status
  step.message = event.message || ''
  step.result = event.result || null
  if (event.ts) step.doneTs = event.ts
  if (event.action) step.action = event.action   // done 亦带 action 时保名 (见 thread._emit_node_done)
}

// 流程终态收口: 递归把仍标 RUNNING 的步骤 (叶子 + run_script 容器) 收敛为流程终态, 停止黄底脉冲。
// 与后端 thread._finish 清活动节点、debug.js 终态清高光对称。
// 根因: 步骤树纯由 vm_node_enter/done 增量重建, 而终止/急停/并行取消等路径按设计不发在飞叶子的 done,
// 事件总线满时亦会丢最旧 done -> 后端无法保证每个 done 都到达, 故据流程终态在此收口是唯一全覆盖的层。
// 流程能到 DONE 即每个叶子确已跑完 (block 走完才置 DONE), 残留 RUNNING 纯是完成事件丢失, 着终态是准确而非掩盖。
function finalizeRunning(steps, terminal) {
  for (const s of steps || []) {
    if (s.children && s.children.length) finalizeRunning(s.children, terminal)
    if (s.status === 'RUNNING') s.status = terminal
  }
}

// 旧执行器扁平事件 (step_start/step_done): 落根帧, 无嵌套; 按 step id 就地更新或追加。
function upsertFlat(children, stepId, action, status, message, result, ts) {
  const existing = children.find((s) => s.step_id === stepId && !(s.children && s.children.length))
  if (existing) {
    existing.status = status
    if (action) existing.action = action
    existing.message = message || ''
    existing.result = result || null
    if (ts) existing.doneTs = ts                 // 扁平路径的 done 就地补完成时刻
    return
  }
  children.push({ step_id: stepId, script: '', op: 'call', action: action || 'call',
                  status, message: message || '', result: result || null,
                  ts: ts || null, doneTs: null, children: [] })
}

function applyEvent(run, ctx, event) {
  const type = event.type || ''
  if (type === 'operation_start') {
    run.run_id = event.run_id
    run.operation = event.operation
    run.label = event.label || ''
    run.status = 'RUNNING'
    run.message = ''
    run.steps.splice(0)                          // 就地清空 (保 reactive 引用)
    ctx.stack = [{ children: run.steps }]         // 重置帧栈
    return
  }
  if (type === 'operation_done' || type === 'operation_failed') {
    run.status = event.status || (type === 'operation_done' ? 'DONE' : 'FAILED')
    run.message = event.message || ''
    finalizeRunning(run.steps, run.status)   // 收口: 漏发/迟到/丢弃的 done 留下的残留 RUNNING 随流程终态收敛, 停止脉冲
    return
  }
  // 终态 vm_state 收口: 实时总线丢最旧可能挤掉 operation_done, 而末条 vm_state (最新) 通常仍到达。
  // debug.js 已据终态 vm_state 收口 (见其 ingest vm_state 分支); 步骤树同样据它收口, 保证"徽标 DONE 时树必收口",
  // 与具体丢了哪条终态事件无关。非终态 vm_state (RUNNING/PAUSED/…) 忽略, 不干扰增量重建。
  if (type === 'vm_state') {
    const vmStatus = event.status
    if (vmStatus === 'DONE' || vmStatus === 'ERROR' || vmStatus === 'KILLED' || vmStatus === 'CANCELLED') {
      if (!run.status || run.status === 'RUNNING') run.status = vmStatus   // operation_done 已到则不覆盖其终态
      finalizeRunning(run.steps, run.status)
    }
    return
  }
  if (type === 'step_start' || type === 'step_done') {
    const root = ctx.stack[0]
    if (!root) return
    const st = type === 'step_start' ? 'RUNNING' : (event.status || 'DONE')
    upsertFlat(root.children, event.step, event.action, st, event.message, event.result, event.ts)
    return
  }
  const isEnter = type === 'vm_node_enter'
  const isDone = type === 'vm_node_done'
  // 控制流 (if/for/parallel/...) 不发 enter/done, 不入步列表; 仅 call/run_script 成步
  if (!(isEnter || isDone) || (event.op !== 'call' && event.op !== 'run_script')) return
  if (!ctx.stack || !ctx.stack.length) ctx.stack = [{ children: run.steps }]   // 无 start 前缀兜底

  if (isEnter) {
    const parent = ctx.stack[ctx.stack.length - 1]
    const step = makeStep(event)
    parent.children.push(step)
    // 开子帧: 后续子步挂它 children 下。经 parent.children 读回入栈而非直接 push(step):
    // run 为 reactive 时读回的是 proxy, 嵌套帧内的 enter/done 变更才走代理可被追踪
    // (直接持 raw step 会让子脚本内整段变更静默, 树冻结到下一根级事件才突跳);
    // run 为纯对象时 [len-1] === step, 行为零变化。
    if (event.op === 'run_script') ctx.stack.push(parent.children[parent.children.length - 1])
    return
  }
  // isDone
  if (event.op === 'run_script') {
    // 关子帧: run_script 严格嵌套 (子脚本 enter/done 成对且先于父 done), 正常即栈顶; 容错向下找并弹到它
    for (let i = ctx.stack.length - 1; i >= 1; i--) {
      if (ctx.stack[i].step_id === event.aid) {
        fillDone(ctx.stack[i], event)
        ctx.stack.length = i                              // 弹出该帧 (含其上未闭合帧)
        return
      }
    }
    return
  }
  // call done: 在栈顶父的 children 内命中该 aid 的 call 步
  const kids = ctx.stack[ctx.stack.length - 1].children
  for (let i = kids.length - 1; i >= 0; i--) {
    if (kids[i].step_id === event.aid && kids[i].op === 'call') { fillDone(kids[i], event); return }
  }
}
export { applyEvent } // 供 RunDetail 历史回放增量播放复用 (与实时 ingest/reseed 同一状态机)

// 运行事件类型过滤: ingest 与补种重放共用同一判定, 保证"缓冲区/存储重放"两个宇宙一致
// (否则存储里的 vm_vars 等会破坏重叠去重的对齐)。
// 导出供三维时间线复用: 它重建历史运行时同样要先滤掉 vm_vars/vm_hold 等非步骤事件。
export function isRunEvent(type) {
  return type.startsWith('operation') || type.startsWith('step')
    || type === 'vm_node_enter' || type === 'vm_node_done' || type === 'vm_state'
}

// 递归统计叶子步 (无 children 的实际设备调用) 的 {total, done}; done = 状态非 RUNNING。
// run_script 容器不计入 (仅分组); 供 StatusBar 进度条复用。
export function countSteps(steps) {
  let total = 0
  let done = 0
  for (const s of steps || []) {
    if (s.children && s.children.length) {
      const c = countSteps(s.children)
      total += c.total
      done += c.done
    } else {
      total += 1
      if (s.status && s.status !== 'RUNNING') done += 1
    }
  }
  return { total, done }
}

// 终态集合 (通道剪枝与对账启停判定)。INTERRUPTED 是后端启动收敛给孤儿 RUNNING 判的终态
// (run_store.reconcile_orphans), 没有对应的 operation_* 事件, 只出现在权威行的 status 里
const _FINAL = new Set(['DONE', 'ERROR', 'FAILED', 'KILLED', 'CANCELLED', 'INTERRUPTED'])
// 通道保留上限: 终态通道最多 3 条 (监视器 tab 不爆), 总数 16 条 (并行调度 8 缸 + 富余)
const _MAX_FINAL_CHANNELS = 3
const _MAX_CHANNELS = 16
// 空投影 (无任何运行时 live 兜底; 冻结防误写)
const _EMPTY_PROJ = Object.freeze({
  run_id: '', operation: '', label: '', status: '', message: '', steps: Object.freeze([]),
})

export const useRunsStore = defineStore('runs', () => {
  const recent = ref([]) // 历史运行列表 (倒序)

  // ---- 多通道: 每 run 一条 (树 + 补种簿记) ----
  // channels 非响应式 (簿记不进渲染); activeById 是响应式投影表 (proj 本身 reactive,
  // steps 就地变更保引用, 与旧单例 live 同一套增量语义)。
  const channels = new Map()          // run_id -> {proj, ctx, atomic, reseedEpoch, reseedBuffer, reseedTarget, replayedGate}
  const activeById = reactive({})     // run_id -> proj (供多运行监视器/调度看板)
  const runOrder = ref([])            // 启动序 (最新在尾; 监视器 tab 序)
  const selectedRunId = ref('')       // 用户 pin; '' = 跟随最新

  const selectedEffectiveId = computed(() => {
    if (selectedRunId.value && channels.has(selectedRunId.value)) return selectedRunId.value
    return runOrder.value[runOrder.value.length - 1] || ''
  })
  // 兼容层: 旧消费者 (MonitorDock/StatusBar/单测) 的 runs.live.* 读法零改动
  const live = computed(() => activeById[selectedEffectiveId.value] || _EMPTY_PROJ)
  const activeRuns = computed(() => runOrder.value.map((id) => activeById[id]).filter(Boolean))

  function select(id) {
    selectedRunId.value = id && channels.has(id) ? id : ''
  }

  function openChannel(runId) {
    let ch = channels.get(runId)
    if (ch) return ch
    const proj = reactive({ run_id: runId, operation: '', label: '', status: '', message: '', steps: [] })
    ch = {
      proj,
      ctx: { stack: [{ children: proj.steps }] },
      atomic: false,          // 手动单动作运行: 不入 RunStore, 无对账源
      reseedEpoch: 0,         // 在途补种作废代次
      reseedBuffer: null,     // 非 null 即补种中: 实时事件先入缓冲
      reseedTarget: '',
      replayedGate: null,     // 快照/实时重叠窗口去重门
    }
    channels.set(runId, ch)
    activeById[runId] = proj
    runOrder.value = [...runOrder.value, runId]
    return ch
  }

  function closeChannel(runId) {
    channels.delete(runId)
    delete activeById[runId]
    runOrder.value = runOrder.value.filter((id) => id !== runId)
    if (selectedRunId.value === runId) selectedRunId.value = ''
  }

  // 剪枝: 只剪终态通道 (保序从最旧起), RUNNING/未知永不剪; 监视器 tab 与内存双上界
  function pruneChannels() {
    const finals = runOrder.value.filter((id) => _FINAL.has(channels.get(id)?.proj.status))
    let excessFinal = finals.length - _MAX_FINAL_CHANNELS
    let excessTotal = runOrder.value.length - _MAX_CHANNELS
    for (const id of finals) {
      if (excessFinal <= 0 && excessTotal <= 0) break
      closeChannel(id)
      excessFinal -= 1
      excessTotal -= 1
    }
  }

  // ---- 对账轮询: 单一定时器服务全部通道 (一次 listRuns 全体对账, 天然防 N 表) ----
  let pollTimer = null
  let pollInflight = false // tick 单飞: 弱网下请求不堆积

  async function seedRecent() {
    recent.value = await api.listRuns({ limit: 50 })
  }

  // 清空全部通道 (测试/兜底; 旧 API 名保留, 语义升级为"清全部")
  function resetLive() {
    for (const id of [...channels.keys()]) closeChannel(id)
    selectedRunId.value = ''
    syncPoll()
  }

  // 应用一条实时事件到通道 (含快照重叠去重门); ingest 正常路与补种续灌共用
  function applyToChannel(ch, event) {
    if (ch.replayedGate) {
      const key = JSON.stringify(event)
      if (ch.replayedGate.has(key)) {
        ch.replayedGate.delete(key)   // 重放已含此事件: 吸收重复投递
        return
      }
      ch.replayedGate = null          // 越过快照点, 关门
    }
    applyEvent(ch.proj, ch.ctx, event)
  }

  // 从权威运行记录 (RunStore) 整树重放补种单通道; 机制与旧单例逐行同构, 簿记落通道。
  async function reseedOne(id) {
    const ch = channels.get(id)
    if (!ch) return
    if (ch.atomic) return             // 手动单动作不入 RunStore, 补种没有真源
    ch.reseedEpoch += 1
    const epoch = ch.reseedEpoch
    ch.reseedTarget = id
    ch.reseedBuffer = []
    let rec
    try {
      rec = await api.getRun(id)
    } catch (e) {
      // 404 / 网络失败: 放弃补种; 从 recent 挂载补种进来的空通道顺手关掉 (防空 tab 残留)
      if (epoch === ch.reseedEpoch) { ch.reseedBuffer = null; ch.reseedTarget = '' }
      if (!ch.proj.status && !ch.proj.steps.length) closeChannel(id)
      syncPoll()
      return
    }
    if (epoch !== ch.reseedEpoch) { syncPoll(); return }   // 期间同 run 重跑/新补种: 本次作废
    const buffered = ch.reseedBuffer
    ch.reseedBuffer = null
    ch.reseedTarget = ''
    ch.proj.steps.splice(0)                          // 就地重建 (保 reactive 引用)
    ch.ctx = { stack: [{ children: ch.proj.steps }] }
    ch.proj.run_id = id                              // 存储事件缺 operation_start 时的兜底绑定
    const events = (rec.events || []).filter((e) => isRunEvent(e.type || ''))
    for (const ev of events) applyEvent(ch.proj, ch.ctx, ev)
    // 采纳权威行的终态: 启动收敛出的 INTERRUPTED 行没有 operation_done/failed 事件
    // (它是被 UPDATE 出来的, 不是被事件收尾的), 只重放事件投影会停在 RUNNING ——
    // 那正是本机制要治的"库对、投影错", 只是过去假设终态事件一定在日志里
    if (_FINAL.has(rec.status) && !_FINAL.has(ch.proj.status)) {
      ch.proj.status = rec.status
      if (rec.message && !ch.proj.message) ch.proj.message = rec.message
    }
    // 门集合取重放尾部 (重叠窗口 = 新订阅后到快照点的在途事件, 量级为一次往返, 100 富余)
    ch.replayedGate = new Set(events.slice(-100).map((e) => JSON.stringify(e)))
    for (const ev of buffered) applyToChannel(ch, ev)
    syncPoll()
  }

  // 补种入口: 带 id 补单通道 (通道不存在则开 —— 挂载时从 recent 补种依赖此路径);
  // 无参补全部通道 (重连沿), 串行防 N 路 getRun 突发。
  async function reseedLive(runId) {
    if (runId) {
      openChannel(runId)
      return reseedOne(runId)
    }
    for (const id of [...channels.keys()]) {
      await reseedOne(id)   // eslint-disable-line no-await-in-loop -- 串行: 重连风暴防护
    }
  }

  // 终态对账: 权威列表说某通道已终态而投影仍 RUNNING -> 该通道整树重放收口。
  function reconcileFromRecent() {
    const jobs = []
    for (const [id, ch] of channels) {
      if (ch.reseedBuffer || ch.atomic) continue          // 补种在途/无真源
      if (ch.proj.status && ch.proj.status !== 'RUNNING') continue
      const rec = recent.value.find((r) => r.run_id === id)
      if (rec && rec.status && rec.status !== 'RUNNING') jobs.push(reseedOne(id))
    }
    if (jobs.length) return Promise.all(jobs)             // 返回 promise 供单测等待
  }

  // 幂等启停对账轮询: 任一通道 (疑似) 运行中即确保 5s 表在跑, 否则停表。
  function syncPoll() {
    let shouldRun = false
    for (const ch of channels.values()) {
      if (!ch.atomic && (ch.proj.status === 'RUNNING' || ch.proj.status === '')) {
        shouldRun = true
        break
      }
    }
    if (shouldRun && !pollTimer) {
      pollTimer = setInterval(() => {
        if (pollInflight) return
        pollInflight = true
        seedRecent()
          .then(() => reconcileFromRecent())
          .catch(() => {})                    // 拉取失败静默, 下个 tick 再试
          .finally(() => { pollInflight = false })
      }, 5000)
      pollTimer.unref?.()   // Node (单测) 下不阻止进程退出; 浏览器返回数字, 可选链短路
    } else if (!shouldRun && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // 消费 operation_*/step_*/vm_node_* 事件; 按 run_id 路由到通道 (并行多运行互不串扰)
  function ingest(event) {
    const type = event.type || ''
    if (!isRunEvent(type)) return
    if (type === 'operation_start') {
      const id = event.run_id
      if (!id) return
      let ch = channels.get(id)
      if (ch) {
        // 同 run 复位重跑: 就地清树 (保引用), 作废在途补种
        ch.reseedEpoch += 1
        ch.reseedBuffer = null
        ch.reseedTarget = ''
        ch.replayedGate = null
        ch.proj.steps.splice(0)
        ch.ctx = { stack: [{ children: ch.proj.steps }] }
      } else {
        ch = openChannel(id)
      }
      ch.atomic = !!event.atomic   // 手动单动作: 不入 RunStore 无对账源
      applyEvent(ch.proj, ch.ctx, event)
      pruneChannels()
      seedRecent()
      syncPoll()
      return
    }
    // 路由: 有 run_id 找对应通道; 旧执行器扁平事件无 run_id 落最新通道 (兼容兜底)。
    // 未知 run 丢弃 (防已清通道被迟到终态写出状态残留 —— 旧单例语义的按通道版)。
    const id = event.run_id || runOrder.value[runOrder.value.length - 1]
    const ch = id ? channels.get(id) : null
    if (!ch) return
    if (ch.reseedBuffer) {
      ch.reseedBuffer.push(event)   // 补种中: 先入缓冲, 重放后经门去重续灌
      return
    }
    applyToChannel(ch, event)
    if (type === 'operation_done' || type === 'operation_failed') seedRecent()
    syncPoll()   // 终态事件到达且无其他运行中通道即停表; 其余为幂等空转
  }

  return { recent, live, activeById, runOrder, selectedRunId, selectedEffectiveId,
           activeRuns, select, seedRecent, resetLive, reseedLive, reconcileFromRecent,
           ingest }
})
