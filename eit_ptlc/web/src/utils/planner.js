// 排程纯函数 (无 DOM/网络, node --test 可测)
// ============================================
// 功能: FIFO 贪心排程 / 手动编排后的冲突检测 / 甘特时间轴刻度 / 时长格式化。
// 模型: 编排单元是流程块; 块整段持有其根部 resources (与 ResourceGate 的
//       "exclusive 只能声明在脚本根且整程持有"语义一致); shared 资源不阻塞。
// 对齐: 与 docs 落地计划 §9.2 一致, 严格 FIFO 贪心, 不做优化算法。

const EPS = 1e-6

// 无历史耗时的流程用该估计时长 (秒), 块标 estimated 由前端虚线显示
export const FALLBACK_DURATION_S = 60

// 资源是否按独占对待: 未知资源保守当 exclusive, 只有明确 shared 才不阻塞
function isExclusive(resource, resourceModes) {
  return (resourceModes || {})[resource] !== 'shared'
}

// 把 /api/planner/stats 响应折成排程用的时长索引 (口径在此一次性定死,
// 排程算法只认 duration_s, 不关心是平均还是最新)。
// 参数: stats: 端点响应 (可为 null); mode: 'avg' 取 avg_s, 'last' 取 last_s。
// 返回: {流程名: {duration_s, resources, count}}; 无有效耗时时 duration_s 为 null。
export function buildDurationIndex(stats, mode) {
  const index = {}
  for (const op of (stats && stats.operations) || []) {
    const raw = mode === 'last' ? op.last_s : op.avg_s
    index[op.name] = {
      duration_s: typeof raw === 'number' && raw > 0 ? raw : null,
      resources: op.resources || [],
      count: op.count || 0,
    }
  }
  return index
}

// 取流程的块时长与资源; 无有效时长 (无历史/基线清空) 时回落估计值
function blockOf(opName, durationIndex, fallbackS) {
  const entry = (durationIndex || {})[opName]
  const hasDur = entry && typeof entry.duration_s === 'number' && entry.duration_s > 0
  return {
    duration_s: hasDur ? entry.duration_s : fallbackS,
    resources: (entry && entry.resources) || [],
    estimated: !hasDur,
  }
}

// FIFO 贪心排程。
// 参数: samples: [{id, label, chain: [流程名]}]; durationIndex: buildDurationIndex 的输出
//       ({流程名: {duration_s, resources}}); resourceModes: {资源id: 'exclusive'|'shared'};
//       opts.fallbackS 无历史时的估计时长。
// 返回: {placements: [{key, sampleId, index, opName, start_s, end_s, duration_s,
//        resources, estimated}], makespan_s}。
// 性质: 构造即无冲突; 每轮取"最早可开始"的下一块, 平局按样品定义序 (严格 FIFO);
//       样品内顺序由 readyAt 内建; shared 资源不占用。确定性: 同输入同输出。
export function scheduleGreedy(samples, durationIndex, resourceModes, opts = {}) {
  const fallbackS = typeof opts.fallbackS === 'number' ? opts.fallbackS : FALLBACK_DURATION_S
  const list = (samples || []).filter((s) => s && Array.isArray(s.chain))
  const ptr = list.map(() => 0)
  const readyAt = list.map(() => 0)
  const resFree = {}                       // 资源 → 最早空闲时刻 (惰性, 仅 exclusive)
  const placements = []
  let remaining = list.reduce((acc, s) => acc + s.chain.length, 0)
  while (remaining > 0) {
    let best = null
    for (let i = 0; i < list.length; i++) {
      if (ptr[i] >= list[i].chain.length) continue
      const opName = list[i].chain[ptr[i]]
      const block = blockOf(opName, durationIndex, fallbackS)
      let est = readyAt[i]
      for (const r of block.resources) {
        if (isExclusive(r, resourceModes)) est = Math.max(est, resFree[r] || 0)
      }
      if (best === null || est < best.est - EPS) best = { i, opName, block, est }
    }
    const { i, opName, block, est } = best
    const placement = {
      key: `${list[i].id}#${ptr[i]}`,
      sampleId: list[i].id,
      index: ptr[i],
      opName,
      start_s: est,
      end_s: est + block.duration_s,
      duration_s: block.duration_s,
      resources: block.resources,
      estimated: block.estimated,
    }
    placements.push(placement)
    readyAt[i] = placement.end_s
    for (const r of block.resources) {
      if (isExclusive(r, resourceModes)) resFree[r] = placement.end_s
    }
    ptr[i] += 1
    remaining -= 1
  }
  const makespan_s = placements.reduce((acc, p) => Math.max(acc, p.end_s), 0)
  return { placements, makespan_s }
}

// 冲突检测 (手动拖动后)。
// 参数: placements 同 scheduleGreedy 输出; resourceModes 同上。
// 返回: [{type: 'resource', resource, a, b} | {type: 'order', sampleId, a, b}],
//       a/b 为 placement.key; 首尾相接 (b.start == a.end) 不算冲突。
export function detectConflicts(placements, resourceModes) {
  const conflicts = []
  const items = placements || []
  // 资源重叠: 逐 exclusive 资源做扫描线 (维护运行中最大 end, 覆盖跨多块的长区间)
  const byResource = {}
  for (const p of items) {
    for (const r of p.resources || []) {
      if (!isExclusive(r, resourceModes)) continue
      if (!byResource[r]) byResource[r] = []
      byResource[r].push(p)
    }
  }
  for (const [resource, group] of Object.entries(byResource)) {
    group.sort((a, b) => a.start_s - b.start_s || a.end_s - b.end_s)
    let holder = null
    for (const p of group) {
      if (holder !== null && p.start_s < holder.end_s - EPS) {
        conflicts.push({ type: 'resource', resource, a: holder.key, b: p.key })
      }
      if (holder === null || p.end_s > holder.end_s) holder = p
    }
  }
  // 样品内顺序违反: 链序靠后的块不得早于前一块结束
  const bySample = {}
  for (const p of items) {
    if (!bySample[p.sampleId]) bySample[p.sampleId] = []
    bySample[p.sampleId].push(p)
  }
  for (const [sampleId, group] of Object.entries(bySample)) {
    group.sort((a, b) => a.index - b.index)
    for (let i = 1; i < group.length; i++) {
      if (group[i].start_s < group[i - 1].end_s - EPS) {
        conflicts.push({ type: 'order', sampleId, a: group[i - 1].key, b: group[i].key })
      }
    }
  }
  return conflicts
}

// 时间轴刻度候选步长 (秒), 取第一个满足 step*pxPerSec >= minPx 的
const TICK_STEPS = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600,
                    900, 1800, 3600, 7200, 14400, 28800, 86400]

function pad2(n) {
  return String(n).padStart(2, '0')
}

// 单个刻度标签: 亚秒步长带一位小数; 分钟级用 m:ss; 小时级用 h:mm:ss
function tickLabel(t, stepS) {
  if (t >= 3600) {
    const h = Math.floor(t / 3600)
    const m = Math.floor((t % 3600) / 60)
    const s = Math.round(t % 60)
    return `${h}:${pad2(m)}:${pad2(s)}`
  }
  if (t >= 60 || stepS >= 60) return `${Math.floor(t / 60)}:${pad2(Math.round(t % 60))}`
  if (stepS >= 1) return `${Math.round(t)}s`
  return `${t.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')}s`
}

// 生成时间轴刻度。
// 参数: spanS 总时长(秒); pxPerSec 缩放; minPx 相邻刻度最小像素间距。
// 返回: {stepS, ticks: [{t, label}]} (含 0, 到 spanS 为止)。
export function niceTicks(spanS, pxPerSec, minPx = 70) {
  const scale = pxPerSec > 0 ? pxPerSec : 1
  let stepS = TICK_STEPS[TICK_STEPS.length - 1]
  for (const step of TICK_STEPS) {
    if (step * scale >= minPx) { stepS = step; break }
  }
  const ticks = []
  const span = Math.max(spanS || 0, 0)
  for (let t = 0; t <= span + EPS; t += stepS) {
    const tt = Math.round(t * 1000) / 1000  // 抑制浮点累加误差
    ticks.push({ t: tt, label: tickLabel(tt, stepS) })
  }
  return { stepS, ticks }
}

// 时长格式化 (支持 sim 的毫秒级): 850ms / 12.7s / 4m32s / 1h02m
export function fmtDur(s) {
  if (typeof s !== 'number' || !isFinite(s) || s < 0) return '—'
  if (s < 1) return `${Math.round(s * 1000)}ms`
  if (s < 60) return `${(Math.round(s * 10) / 10)}s`
  if (s < 3600) {
    const m = Math.floor(s / 60)
    return `${m}m${pad2(Math.round(s % 60))}s`
  }
  const h = Math.floor(s / 3600)
  return `${h}h${pad2(Math.floor((s % 3600) / 60))}m`
}
