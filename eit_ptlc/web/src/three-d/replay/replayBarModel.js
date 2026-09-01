/**
 * 功能: 时间线的纯计算 —— 时间轴刻度、标记归位、工位利用率条、时刻格式化。
 *
 * 与组件分开是刻意的: 时区、半开区间、密度归一这几处最容易错, 且错了以后在界面上
 * 只表现为"条画得不太对", 没人会当成 bug 报。放在纯函数里就能离线断言。
 */

/** 标记类型 -> 展示配色与中文名。事故追溯要一眼看出哪一条是报警。 */
export const MARKER_KINDS = {
  alarm: { label: '报警/失败', color: '#ff5a5f', priority: 0 },
  hold: { label: '暂停', color: '#ffb020', priority: 1 },
  human: { label: '人工干预', color: '#8b5cf6', priority: 2 },
  operation: { label: '流程', color: '#22d3ee', priority: 3 },
  camera: { label: '拍照', color: '#a3e635', priority: 4 },
  step: { label: '步骤', color: '#64748b', priority: 5 },
  transport: { label: '连接变化', color: '#94a3b8', priority: 6 },
}

/**
 * 功能: 把纪元秒格式化成本地时刻.
 * @param {number} epoch 纪元秒
 * @param {boolean} [withDate] 是否带日期
 * @returns {string}
 */
export function formatClock(epoch, withDate = false) {
  if (!Number.isFinite(epoch)) return '--:--:--'
  const d = new Date(epoch * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  if (!withDate) return time
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`
}

/**
 * 功能: 时长的人读形式 (回放跨度可能从几秒到几十天).
 * @param {number} seconds
 * @returns {string}
 */
export function formatSpan(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '--'
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时 ${Math.round((seconds % 3600) / 60)} 分`
  return `${(seconds / 86400).toFixed(1)} 天`
}

/**
 * 功能: 把某天的本地 [00:00, 次日00:00) 换算成纪元秒半开区间.
 *
 * 必须按分量构造 —— `new Date('YYYY-MM-DD')` 按 **UTC** 解析, 东八区会整体偏 8 小时,
 * 于是"今天"的录像有 8 小时落在区间外。这条与 ExplorerDock 里既有的 dayRange 同源,
 * 那边也是踩过才写成分量式的。
 *
 * @param {string} dateStr 'YYYY-MM-DD'
 * @returns {{since: number, until: number}|null}
 */
export function dayRange(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || ''))
  if (!m) return null
  const start = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 0, 0, 0, 0)
  const end = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + 1, 0, 0, 0, 0)
  return { since: start.getTime() / 1000, until: end.getTime() / 1000 }
}

/**
 * 功能: 把标记落到 [0,1] 的横向位置, 并按优先级去重同位置的密集标记.
 *
 * 同一毫秒可能挤着 step/operation 好几条, 全画出来就是一堵墙; 按像素桶取优先级最高
 * 的那条(报警 > 暂停 > 人工 > 流程 …), 保证"红点绝不会被灰点盖住"。
 *
 * @param {object[]} markers 标记数组
 * @param {number} t0 区间起
 * @param {number} t1 区间止
 * @param {number} [buckets] 横向像素桶数
 * @returns {object[]} {ts, kind, label, offset, color}
 */
export function layoutMarkers(markers, t0, t1, buckets = 400) {
  const span = t1 - t0
  if (!(span > 0)) return []
  const best = new Map()
  for (const marker of markers || []) {
    const ts = Number(marker?.ts)
    if (!Number.isFinite(ts) || ts < t0 || ts >= t1) continue
    const offset = (ts - t0) / span
    const bucket = Math.min(buckets - 1, Math.floor(offset * buckets))
    const meta = MARKER_KINDS[marker.kind] || MARKER_KINDS.step
    const prev = best.get(bucket)
    const prevPriority = prev ? (MARKER_KINDS[prev.kind]?.priority ?? 99) : 99
    if (!prev || meta.priority < prevPriority) {
      best.set(bucket, {
        ts,
        kind: marker.kind,
        label: marker.label || meta.label,
        run_id: marker.run_id || null,
        offset,
        color: meta.color,
      })
    }
  }
  return [...best.values()].sort((a, b) => a.ts - b.ts)
}

/**
 * 功能: 把后端的"每桶有几个工位在动"换算成柱子的高度与提示.
 *
 * 归一化分母是**固定的模块总数**(8 个 PLC 工位 + 机器人 = 9), 不是窗口峰值。按峰值
 * 缩放会让"整小时只有一根轴动过"的一段看起来跟满负荷一样满 —— 那正是原先按块字节数
 * 画出来的那种"处处一样高"的假象换了个形式。
 *
 * **四种**状态必须画得不一样, 混起来就会让人得出相反结论:
 *   count > 0   在动 -> 按比例出柱子
 *   count = 0   有录像但空闲 -> 只留一条基线, 表示"这段确实录了, 确实没动"
 *   unknown     有块但还没补算过活动度 -> 底纹
 *   gap         该时段根本没有录像 -> 完全空白
 * 后两种最容易被合并成"空闲", 而那等于把一段录像空洞说成"当时机器没动"。
 *
 * @param {(number|null)[]} active 每桶在动的模块数
 * @param {number} total 模块总数(归一化分母)
 * @param {string[][]} [stations] 每桶具体是哪几个工位, 用于悬停提示
 * @param {boolean[]} [covered] 每桶是否有录像块
 * @returns {{height, count, unknown, gap, stations}[]}
 */
export function utilizationHeights(active, total, stations = [], covered = []) {
  const denominator = Math.max(Number(total) || 0, 1)
  return (active || []).map((value, index) => {
    const names = stations[index] || []
    // covered 缺省视作"有录像": 老响应体没有这个字段时不该把整条画成空洞
    const isCovered = covered.length ? Boolean(covered[index]) : true
    if (!isCovered) {
      return { height: 0, count: 0, unknown: false, gap: true, stations: [] }
    }
    if (value === null || value === undefined) {
      return { height: 0, count: 0, unknown: true, gap: false, stations: [] }
    }
    const count = Math.max(Number(value) || 0, 0)
    // 最低可见高度 12%: 一个工位在动占 1/9 ≈ 11%, 不抬一下在 44px 高的轨道上只有 5px
    const height = count > 0
      ? Math.max(12, Math.min(100, Math.round((count / denominator) * 100)))
      : 0
    return { height, count, unknown: false, gap: false, stations: names }
  })
}

/**
 * 功能: 依据录像覆盖区间给出可选的时间轴刻度 (5~8 个整点).
 * @param {number} t0
 * @param {number} t1
 * @param {number} [count]
 * @returns {{offset: number, label: string}[]}
 */
export function axisTicks(t0, t1, count = 6) {
  const span = t1 - t0
  if (!(span > 0)) return []
  const withDate = span > 86400
  const out = []
  for (let i = 0; i <= count; i += 1) {
    const at = t0 + (span * i) / count
    out.push({ offset: i / count, label: formatClock(at, withDate) })
  }
  return out
}
