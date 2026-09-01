// 实验/调度页的纯函数层 (无 DOM/网络; node --test 可测)
// 甘特 placements 构造 / 样品ID预览 / 旋钮聚合 / 等待原因文案 / 段 chip 状态映射

// 样品ID预览: 与后端 scheduler.submit_batch 的 {prefix}-{02d} 规则一致 (最终以响应为准)
export function genSampleIds(prefix, count, startAt = 1) {
  const n = Math.max(0, Math.floor(Number(count) || 0))
  const width = Math.max(2, String(startAt + n - 1).length)
  const out = []
  for (let i = 0; i < n; i++) out.push(`${prefix}-${String(startAt + i).padStart(width, '0')}`)
  return out
}

// 段中文短标签: 正式段标签已自带执行序号短名 ("3 展开前拍照" / 并行支线 "2-1 点样执行"), 原样透传;
// 兼容旧式/冒烟标签: 剥"并行段-"前缀、截到首个"("前。无标签回退原值 (id/脚本名)。全流程可读性的唯一真源在此。
export function shortSegLabel(label) {
  if (!label) return ''
  let s = String(label)
  const dash = s.indexOf('-')
  if (s.startsWith('并行段') && dash >= 0) s = s.slice(dash + 1)
  const paren = s.search(/[(（]/)
  if (paren > 0) s = s.slice(0, paren)
  return s.trim() || String(label)
}

// 可并行段对: 互相无传递依赖的段对 (DAG 可达性推导; 调度方案即"谁能并行"的唯一定义处)。
// segments: [{id, label, depends_on}] (方案序)。返回 [[labelA, labelB], ...] 按方案序;
// 链式方案返回 [] (零并行)。batch 段照常参与 (af0 在所有 sample 段上游, 天然不成对)。
export function parallelPairs(segments) {
  const segs = segments || []
  const up = new Map()   // id -> Set(全部传递上游)
  for (const s of segs) {
    const acc = new Set()
    for (const d of s.depends_on || []) {
      acc.add(d)
      for (const t of up.get(d) || []) acc.add(t)
    }
    up.set(s.id, acc)
  }
  const out = []
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const a = segs[i], b = segs[j]
      if (!up.get(a.id).has(b.id) && !up.get(b.id).has(a.id)) {
        out.push([a.label || a.id, b.label || b.id])
      }
    }
  }
  return out
}

// 旋钮聚合: 方案各段脚本旋钮的并集, 同名归首个声明段 (徽标标注其余引用段)。
// **全段成组**: 无旋钮的段也保留空 knobs 组 —— 否则参数区看起来像"流程被截断"
// (实测 parallel_v1 仅 4/12 段有旋钮, 曾被误读为流程缺段)。
// segments: [{seq, id, op, label}] (方案序); knobsByOp: {opName: knobs[]}
// -> { groups: [{seq, id, op, label, knobs: [knob]}], reuse: {knobName: [段label...]} }
export function aggregateKnobs(segments, knobsByOp) {
  const seen = new Map()          // knobName -> 首个声明段 label
  const reuse = {}
  const groups = []
  for (const seg of segments || []) {
    const knobs = knobsByOp[seg.op] || []
    const mine = []
    for (const k of knobs) {
      if (!seen.has(k.name)) {
        seen.set(k.name, seg.label || seg.op)
        mine.push(k)
      } else {
        ;(reuse[k.name] = reuse[k.name] || []).push(seg.label || seg.op)
      }
    }
    groups.push({ seq: seg.seq, id: seg.id, op: seg.op, label: seg.label || seg.op, knobs: mine })
  }
  return { groups, reuse }
}

// 只收"非空且 != 默认"的批参数 (照 SamplingMultiPanel collectOverrides 约定)
export function collectChangedParams(draft, knobIndex) {
  const out = {}
  for (const [name, raw] of Object.entries(draft || {})) {
    if (raw == null || String(raw).trim() === '') continue
    const knob = knobIndex[name]
    if (knob && knob.default != null && String(knob.default) === String(raw).trim()) continue
    out[name] = coerceParam(knob, String(raw).trim())
  }
  return out
}

function coerceParam(knob, s) {
  const t = knob && knob.type
  if (t === 'INT') return parseInt(s, 10)
  if (t === 'FLOAT') return Number(s)
  if (t === 'BOOL') return ['true', '1', 'yes', 'on'].includes(s.toLowerCase())
  return s
}

// 每样品覆盖载荷: 空 cell 不写键 (缺键 = 继承批级; 照 buildSamples 约定)
export function buildOverridesPayload(rows, knobIndex) {
  return (rows || []).map((row) => {
    const cells = {}
    for (const [name, raw] of Object.entries(row || {})) {
      if (raw == null || String(raw).trim() === '') continue
      cells[name] = coerceParam(knobIndex[name], String(raw).trim())
    }
    return cells
  })
}

// 实际执行 placements (甘特 variant:'actual'): 快照的段作业数组 -> 时间块。
// t0 = 批内最早 started_at; RUNNING 段 end = nowS (开区间随刷新增长); 未开跑/取消不出块。
export function buildActualPlacements(batch, nowEpoch) {
  const rows = []
  for (const s of batch?.samples || []) {
    for (const j of s.jobs || []) {
      if (!j.started_at) continue
      rows.push({ sample: s.sample_id, ...j })
    }
  }
  if (!rows.length) return { t0: 0, placements: [] }
  const t0 = Math.min(...rows.map((r) => r.started_at))
  const placements = rows.map((r) => {
    const endEpoch = r.finished_at || nowEpoch
    return {
      key: `act:${r.sample}#${r.flow_id}`,
      sampleId: r.sample,
      index: r.seq,
      opName: r.script,
      label: r.flow_id,
      status: r.status,
      start_s: Math.max(0, r.started_at - t0),
      duration_s: Math.max(1, endEpoch - r.started_at),
      end_s: Math.max(1, endEpoch - t0),
      resources: [],            // 实际块不进资源泳道 (资源占用有专门条)
      estimated: false,
      variant: 'actual',
      running: !r.finished_at,
    }
  })
  return { t0, placements }
}

// 等待原因闭集 -> 中文 (后端 operation/scheduler.py 的 WAIT_* 常量); 未知码原样透出
const WAIT_TEXT = {
  queued: '排队中',
  depends_on: (d) => `等待前段 ${d || ''}`.trim(),
  waiting_resource: (d) => `等待资源: ${d || ''}`.trim(),
  no_slot: (d) => `停放位被占: ${d || ''}`.trim(),
  no_tank: '等待空展开缸',
  wip_limit: (d) => `在制上限 (${d || ''})`,
  hold: '样品已暂停',
  paused: '批次已暂停',
  position: (d) => `位置不符: ${d || ''}`.trim(),
  occupancy: (d) => `占位未清: ${d || ''}`.trim(),
  maintenance: '维护态 (PLC 部署中)',
}

export function waitReasonText(wait) {
  if (!wait || !wait.reason) return ''
  const entry = WAIT_TEXT[wait.reason]
  if (!entry) return `${wait.reason}${wait.detail ? `: ${wait.detail}` : ''}`
  return typeof entry === 'function' ? entry(wait.detail) : entry
}

// 段 chip 状态 -> 样式类与短文案
const CHIP = {
  PENDING: { cls: 'pending', label: '待派' },
  RUNNING: { cls: 'running', label: '运行' },
  DISPATCHED: { cls: 'running', label: '派发' },
  WAITING_HUMAN: { cls: 'human', label: '等人' },
  DONE: { cls: 'done', label: '完成' },
  ERROR: { cls: 'failed', label: '失败' },
  SKIPPED: { cls: 'skipped', label: '跳过' },
  INTERRUPTED: { cls: 'failed', label: '中断' },
  CANCELLED: { cls: 'skipped', label: '取消' },
}

export function chipStateOf(status) {
  return CHIP[status] || { cls: 'pending', label: status || '?' }
}

// 提交确认门多行文案 (如实告知; 可测)
export function buildSubmitSummary(draft, recipe, sampleIds, changedCount) {
  const lines = [
    `调度方案: ${recipe?.label || draft.recipe}`,
    `样品: ${sampleIds.length} 个 (${sampleIds[0]} ~ ${sampleIds[sampleIds.length - 1]})`,
    `改动参数: ${changedCount} 项`,
    `自动排液: ${draft.autoDrain ? '开 (无人值守)' : '关 (每样品人工确认)'}`,
    draft.tankSubset?.length ? `展开缸: ${draft.tankSubset.join(', ')}` : '展开缸: 全部',
    draft.wipLimit ? `在制上限: ${draft.wipLimit}` : '',
    '',
    '批次将实际驱动机构。确认设备就绪、料仓有板、机械臂停在安全位。',
  ]
  return lines.filter(Boolean).join('\n')
}
