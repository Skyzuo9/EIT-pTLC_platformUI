/**
 * 功能: 时间线的视窗几何、拖动策略、动作分组与键盘映射 —— 全是纯函数.
 *
 * 放进纯模块不是洁癖: 这里每一条都属于"错了也不报错, 只是画面/交互微妙地不对"的类型
 * (锚点缩放漂移、向后擦洗少清一次场、本地时区被当成 UTC、空格键抢了输入框的焦点),
 * 在浏览器里复现要靠手感, 在单测里只要一行断言。
 *
 * 与 replayBarModel.js 的分工: 那边管"怎么显示"(格式化/配色/密度高度), 这边管
 * "看哪一段、拖到哪里、算哪条路"。
 */

/** 视窗最小跨度(秒): 比这更窄就没有帧可看了 */
export const MIN_SPAN_S = 2
/** 单次 drain 的最大跨度(秒): 再多不如直接 seek —— 一次投几千条会让位姿缓冲的逐次排序卡住主线程 */
export const MAX_DRAIN_S = 4
/** 擦洗目标的最小有效变化(秒): 小于它当没动, 免得手指微抖也发请求 */
export const SCRUB_EPS_S = 0.02

/**
 * @typedef {{t0: number, t1: number}} Window
 */

// ── 视窗几何 ────────────────────────────────────────────────────────

/**
 * 功能: 把视窗钳进可用边界, 并守住最小/最大跨度.
 *
 * 贴边时**保持跨度**而不是截断 —— 截断会让"缩放到底再往回拉"每次都少一截, 手感像漏气。
 *
 * @param {Window} view
 * @param {Window} bounds 可用边界(录像覆盖 .. 实时边缘); **不是** clock.t0/t1
 * @param {{minSpanS?: number}} [limits]
 * @returns {Window}
 */
export function clampWindow(view, bounds, { minSpanS = MIN_SPAN_S } = {}) {
  const full = Math.max(bounds.t1 - bounds.t0, 0)
  if (!(full > 0)) return { t0: bounds.t0, t1: bounds.t0 }
  let span = Math.min(Math.max(view.t1 - view.t0, minSpanS), full)
  let t0 = view.t0
  if (t0 < bounds.t0) t0 = bounds.t0
  if (t0 + span > bounds.t1) t0 = bounds.t1 - span
  return { t0, t1: t0 + span }
}

/**
 * 功能: 以光标下的**时刻**为锚缩放 —— 锚点处的像素不动.
 *
 * 与 components/ImageLightbox.vue 的锚点保持公式同构, 降到一维时间。
 *
 * @param {Window} view
 * @param {number} anchorRatio 锚点在轨道上的比例 [0,1]
 * @param {number} factor >1 放大(跨度变小), <1 缩小
 * @param {Window} bounds
 * @param {{minSpanS?: number}} [limits]
 * @returns {Window}
 */
export function zoomAt(view, anchorRatio, factor, bounds, limits = {}) {
  const ratio = Math.min(Math.max(Number(anchorRatio) || 0, 0), 1)
  const span = view.t1 - view.t0
  if (!(span > 0) || !(factor > 0)) return clampWindow(view, bounds, limits)
  const anchorT = view.t0 + span * ratio
  const nextSpan = span / factor
  return clampWindow({ t0: anchorT - nextSpan * ratio, t1: anchorT + nextSpan * (1 - ratio) },
                     bounds, limits)
}

/** 平移(秒); 撞边界就贴边, 跨度不变。 */
export function panBy(view, deltaS, bounds, limits = {}) {
  const shift = Number(deltaS) || 0
  return clampWindow({ t0: view.t0 + shift, t1: view.t1 + shift }, bounds, limits)
}

// px ↔ 时间。拆成四个一行函数而不是一个双向对象: 单测里各自都是一行断言。
export function timeToRatio(t, view) {
  const span = view.t1 - view.t0
  return span > 0 ? (t - view.t0) / span : 0
}
export function ratioToTime(ratio, view) {
  return view.t0 + (view.t1 - view.t0) * ratio
}
export function timeToPx(t, view, widthPx) {
  return timeToRatio(t, view) * widthPx
}
export function pxToTime(px, view, widthPx) {
  return ratioToTime(widthPx > 0 ? px / widthPx : 0, view)
}

/**
 * 功能: 播放头越过视窗右缘时**翻页**(而不是连续滚动).
 *
 * 连续滚会让刻度一直爬、并且每帧触发一次密度取数; 翻页只在越界时动一次。
 *
 * @returns {{view: Window, paged: boolean}}
 */
export function followWindow(view, playhead, bounds, { edgeRatio = 0.9, leadRatio = 0.25 } = {}) {
  const span = view.t1 - view.t0
  if (!(span > 0)) return { view, paged: false }
  const ratio = timeToRatio(playhead, view)
  if (ratio >= 0 && ratio < edgeRatio) return { view, paged: false }
  return { view: clampWindow({ t0: playhead - span * leadRatio, t1: playhead + span * (1 - leadRatio) },
                             bounds), paged: true }
}

/** 视窗右缘贴住"实时"边; 跨度不变。 */
export function snapToLive(view, liveEdge, bounds) {
  const span = Math.max(view.t1 - view.t0, MIN_SPAN_S)
  return clampWindow({ t0: liveEdge - span, t1: liveEdge }, bounds)
}

/**
 * 功能: 视窗跨度 → 一档"整"的刻度步长.
 *
 * 不做这一步的话刻度会是 14:03:47 / 14:06:31 这种谁也读不出来的数。
 * @returns {number} 步长(秒)
 */
export function niceTickStep(spanS, targetCount = 6) {
  const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
                 3600, 7200, 21600, 43200, 86400]
  const want = Math.max(spanS / Math.max(targetCount, 1), 1)
  return steps.find((s) => s >= want) || steps[steps.length - 1]
}

/**
 * 功能: 落在视窗内的整点刻度.
 * @returns {{t: number, offset: number}[]}
 */
export function axisTicksIn(view, targetCount = 6) {
  const span = view.t1 - view.t0
  if (!(span > 0)) return []
  const step = niceTickStep(span, targetCount)
  const out = []
  // 对齐到本地整点边界: 用 UTC 对齐会让非整小时时区(如 +05:30)的刻度全是半点
  const offsetS = new Date(view.t0 * 1000).getTimezoneOffset() * 60
  let t = Math.ceil((view.t0 - offsetS) / step) * step + offsetS
  for (; t <= view.t1 && out.length < 64; t += step) {
    out.push({ t, offset: timeToRatio(t, view) })
  }
  return out
}

/**
 * 功能: 密度条该向后端要哪一段 —— 瓦片化 + 量化对齐, 免得每动一下就重取.
 * @returns {{t0: number, t1: number, buckets: number}|null}
 */
export function densityRequest(view, { buckets = 240, tileFactor = 2 } = {}) {
  const span = view.t1 - view.t0
  if (!(span > 0)) return null
  const tile = span * tileFactor
  const center = (view.t0 + view.t1) / 2
  // 量化到 tile/4: 小幅平移落在同一瓦片里就不必重取
  const grid = tile / 4
  const t0 = Math.floor((center - tile / 2) / grid) * grid
  return { t0, t1: t0 + tile, buckets }
}

// ── 拖动策略 ────────────────────────────────────────────────────────

/**
 * 功能: 决定一次拖动目标走哪条路 —— 这是整个擦洗性能的分水岭.
 *
 * 判据来自两条硬约束, 都不是可以商量的:
 *   1. AxisPoseBuffer.lastArrivalByAxis 是**单调取最大**, 而回放时 arrivalMs 就是
 *      播放头。向后走却不清场, staleness 判定会被永久污染(TwinFeed.resetForSeek
 *      的注释写着这条)。**所以向后一律 seek。**
 *   2. _loadedTo 之外没有缓存数据, 只能走网络。
 * 剩下的"向前且数据在手"才是免费的 —— 它本质就是快进, tick() 一直在做这件事。
 *
 * @returns {{mode: 'noop'|'drain'|'seek', target: number, reason: string}}
 */
export function planScrub({ playhead, target, loadedTo, maxDrainS = MAX_DRAIN_S,
                            epsS = SCRUB_EPS_S }) {
  const delta = target - playhead
  if (Math.abs(delta) < epsS) return { mode: 'noop', target, reason: '变化小于阈值' }
  if (delta < 0) return { mode: 'seek', target, reason: '向后必须清场' }
  if (target > loadedTo) return { mode: 'seek', target, reason: '超出已预取窗口' }
  if (delta > maxDrainS) return { mode: 'seek', target, reason: '前跳过大, drain 会卡主线程' }
  return { mode: 'drain', target, reason: '向前且数据在手' }
}

/**
 * 功能: 擦洗时给场景的 timeScale.
 *
 * 上下限都是硬要求: 取 1 会让泵/液位这些按 delta 积分的模型与事件流脱节(SceneManager
 * 注释里警告的"画面逐渐撕裂"); 取 0 会让 interp 完全停摆、姿态永远收敛不到播种值。
 */
export function scrubTimeScale(deltaPlayheadS, wallDeltaS, { min = 4, max = 16 } = {}) {
  if (!(wallDeltaS > 0)) return min
  const rate = Math.abs(deltaPlayheadS) / wallDeltaS
  return Math.min(Math.max(rate, min), max)
}

// ── A-B 循环 ────────────────────────────────────────────────────────

/** 归一化 A/B(自动排序; 过短或退化返回 null)。 */
export function normalizeLoop(a, b, { minSpanS = 0.5 } = {}) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  const lo = Math.min(a, b)
  const hi = Math.max(a, b)
  return hi - lo >= minSpanS ? { a: lo, b: hi } : null
}

/**
 * 功能: 播放头是否该绕回 A.
 * @returns {{playhead: number, wrapped: boolean}}
 */
export function abLoopNext(playhead, loop) {
  if (!loop || !Number.isFinite(playhead)) return { playhead, wrapped: false }
  if (playhead >= loop.b) return { playhead: loop.a, wrapped: true }
  return { playhead, wrapped: false }
}

// ── 动作泳道 ────────────────────────────────────────────────────────

const FAILED = new Set(['FAILED', 'ERROR', 'KILLED', 'CANCELLED', 'REJECTED'])
/** 合成运行组: 手动单发的动作没有 run_id, 归它, 而不是被丢掉 */
export const MANUAL_RUN = '__manual__'

/** 一个动作的规范化视图 (ts/doneTs 一律绝对纪元秒)。 */
function normalizeAction(item) {
  if (!item || !Number.isFinite(item.ts)) return null
  const doneTs = Number.isFinite(item.done_ts) ? item.done_ts : null
  return {
    runId: item.run_id || MANUAL_RUN,
    script: item.script || '',
    aid: item.aid ?? null,
    op: item.op || '',
    action: item.action || item.op || '',
    status: item.status || (doneTs === null ? 'RUNNING' : 'DONE'),
    failed: FAILED.has(String(item.status || '').toUpperCase()),
    ts: item.ts,
    doneTs,
    // 未闭合动作的"证据末端", 由后端按"该运行最后一条标记"算出。缺了就退化成一个
    // 点 —— 绝不能拿视窗右缘去补, 那样段长会随缩放变长(缩到 1.3 天时横贯全条)。
    openUntil: Number.isFinite(item.open_until) ? item.open_until : null,
    duration: Number.isFinite(item.duration) ? item.duration : null,
  }
}

/**
 * 功能: 把动作排进甘特泳道 —— 与时间轴共用同一套 x 映射.
 *
 * 为什么是泳道而不是列表: 后续是并行流程, 同一时刻可能有好几件事在跑。列表读不出
 * "此刻有几件事", 泳道一眼就看得出 —— 播放头那条竖线扫过几个色块就是几件。
 *
 * 组内贪心装箱(标准区间划分): 一个动作放进第一个"上一段已经结束"的子泳道, 都占着
 * 就新开一条。顺序流程自然只占一行, 并行分支才分行。
 *
 * 窄段合并是硬要求而不是优化: 一小时的忙碌运行能有几千个动作, 全渲染成 DOM 节点会
 * 把 3D 画布挤到掉帧。窄于 minSegPx 的段与同泳道前一段并成一个带计数的聚合块, 于是
 * 每条泳道的段数被**轨道像素宽**封顶, 再密也不会失控。
 *
 * @param {object[]} actions /api/recording/actions 的 actions 数组
 * @param {{view: Window, trackPx?: number, minSegPx?: number, maxLanes?: number,
 *          collapsed?: Set<string>}} options
 * @returns {{lanes: object[], total: number, clipped: number}}
 *   lanes: [{runId, label, failed, count, rows: [[segment]]}]
 *   segment: {left, width, ts, doneTs, action, status, failed, count, open}
 */
export function packActionLanes(actions, { view, trackPx = 800, minSegPx = 3,
                                           maxLanes = 6, collapsed = new Set() } = {}) {
  const span = view ? view.t1 - view.t0 : 0
  if (!(span > 0)) return { lanes: [], total: 0, clipped: 0 }
  const minSegS = (minSegPx / Math.max(trackPx, 1)) * span

  const byRun = new Map()
  let total = 0
  for (const raw of actions || []) {
    const item = normalizeAction(raw)
    if (item === null) continue
    // 段的右端**只来自数据**: 闭合了取 done_ts, 没闭合取证据末端 open_until。
    // 视窗只负责裁剪, 绝不参与定长 —— 一旦掺进 view.t1, 缩得越狠段越长, 缩到最小时
    // 一条 27 小时前没闭合的动作会画成横贯整个时间轴的色带(用户报的就是这个)。
    const end = item.doneTs !== null ? item.doneTs : (item.openUntil ?? item.ts)
    if (end < view.t0 || item.ts >= view.t1) continue
    total += 1
    if (!byRun.has(item.runId)) byRun.set(item.runId, [])
    byRun.get(item.runId).push({ ...item, end })
  }

  const lanes = []
  let clipped = 0
  for (const [runId, items] of byRun) {
    items.sort((x, y) => x.ts - y.ts)
    const rows = []
    for (const item of items) {
      let placed = false
      for (const row of rows) {
        const last = row[row.length - 1]
        if (item.ts < last.endT) continue        // 与本泳道上一段重叠, 换一条
        // 并进来之后**整块仍不超过一个 minSeg 宽**才允许合并。
        // 原先的判据是"与上一段的间隔 < minSegS", 而 endT 每合并一次就往后长, 于是
        // 一串密集动作会滚雪球: 实测 300 个间隔 0.05 秒的动作并成了**一条 14.97 秒**
        // 的段(minSeg 只有 0.3 秒)。按块起点算就封死了 —— 聚合块恒定只有几个像素宽。
        if (item.end - last.ts <= minSegS) {
          last.endT = Math.max(last.endT, item.end)
          last.count += 1
          last.failed = last.failed || item.failed
          placed = true
          break
        }
        row.push({ ...item, endT: item.end, count: 1 })
        placed = true
        break
      }
      if (!placed) {
        if (rows.length >= maxLanes) { clipped += 1; continue }
        rows.push([{ ...item, endT: item.end, count: 1 }])
      }
    }
    lanes.push({
      runId,
      label: items[0]?.script || items[0]?.action || runId,
      ts: items[0]?.ts ?? 0,
      count: items.length,
      failed: items.some((i) => i.failed),
      collapsed: collapsed.has(runId),
      rows: collapsed.has(runId) ? [] : rows.map((row) => row.map((seg) => ({
        ts: seg.ts,
        // 段的真实右端(秒), 与视窗无关。width 是**渲染**宽度, 带 3px 下限, 不能拿它
        // 反推时长 —— 一个 2 秒的动作在 1.3 天的视窗里照样要占 3px 才看得见。
        endTs: seg.endT,
        doneTs: seg.doneTs,
        action: seg.count > 1 ? `${seg.action} 等 ${seg.count} 步` : seg.action,
        status: seg.status,
        failed: seg.failed,
        count: seg.count,
        open: seg.doneTs === null,
        duration: seg.duration,
        left: timeToRatio(seg.ts, view),
        width: Math.max((seg.endT - seg.ts) / span, minSegPx / Math.max(trackPx, 1)),
      }))),
    })
  }
  lanes.sort((x, y) => x.ts - y.ts)
  return { lanes, total, clipped }
}

/**
 * 功能: 跨过 t 那一刻的动作 —— "此刻有哪些在跑"。
 *
 * 半开区间 [ts, doneTs): 首尾相接的两步在交接的那一毫秒不该同时算在跑。未闭合的
 * 动作只要开始过就算在跑。
 *
 * @param {object[]} actions
 * @param {number} t 纪元秒
 * @returns {object[]} 规范化后的动作, 按开始时刻升序
 */
export function actionsAt(actions, t) {
  if (!Number.isFinite(t)) return []
  const out = []
  for (const raw of actions || []) {
    const item = normalizeAction(raw)
    if (item === null || item.ts > t) continue
    if (item.doneTs !== null && item.doneTs <= t) continue
    out.push(item)
  }
  return out.sort((x, y) => x.ts - y.ts)
}

// ── 键盘 ────────────────────────────────────────────────────────────

/**
 * 功能: 键事件描述 → 播放意图. 纯映射, 不碰 DOM.
 *
 * 做成纯函数是为了让"焦点在输入框里时空格不许抢"这类判定也能离线断言 —— 这条错了
 * 的表现是用户在时刻输入框里打空格, 结果视频开始播放。
 *
 * @param {{key: string, shiftKey?: boolean, ctrlKey?: boolean, altKey?: boolean,
 *          metaKey?: boolean, inEditable?: boolean}} desc
 * @returns {{kind: string, [k: string]: any}|null}
 */
export function keyIntent(desc) {
  if (!desc || desc.inEditable) return null
  // 组合键留给浏览器与系统(ctrl+滚轮是页面缩放, meta 是系统快捷键)
  if (desc.ctrlKey || desc.metaKey || desc.altKey) return null
  const shift = Boolean(desc.shiftKey)
  switch (desc.key) {
    case ' ':
    case 'k': case 'K':
      return { kind: 'toggle' }
    case 'ArrowLeft':
      return { kind: 'nudge', seconds: shift ? -1 : -10 }
    case 'ArrowRight':
      return { kind: 'nudge', seconds: shift ? 1 : 10 }
    case 'j': case 'J':
      return { kind: 'speed', direction: -1 }
    case 'l': case 'L':
      return { kind: 'speed', direction: 1 }
    case 'Home':
      return { kind: 'jump', to: 'start' }
    case 'End':
      return { kind: 'jump', to: 'live' }
    case ',':
      return { kind: 'step', direction: -1 }
    case '.':
      return { kind: 'step', direction: 1 }
    case 'a': case 'A':
      return { kind: 'loopMark', which: 'a' }
    case 'b': case 'B':
      return { kind: 'loopMark', which: 'b' }
    default:
      return null
  }
}

/**
 * 功能: 'YYYY-MM-DDTHH:mm(:ss)' → 纪元秒.
 *
 * 必须按分量构造。`new Date('2026-08-13')` 按 **UTC** 解析, 东八区会整体偏 8 小时 ——
 * 这与 replayBarModel.dayRange 是同一个陷阱, 那边已经踩过一次。
 *
 * @param {string} text  datetime-local 的值
 * @param {Window} [bounds] 给了就钳进去
 * @returns {{t: number}|{error: string}}
 */
export function parseInstant(text, bounds = null) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(text || '').trim())
  if (!m) return { error: '时刻格式不对 (应为 YYYY-MM-DD HH:mm[:ss])' }
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]),
                     Number(m[4]), Number(m[5]), Number(m[6] || 0), 0)
  if (Number.isNaN(d.getTime())) return { error: '时刻不合法' }
  let t = d.getTime() / 1000
  if (bounds) {
    if (t < bounds.t0 || t > bounds.t1) return { error: '该时刻不在录像范围内' }
    t = Math.min(Math.max(t, bounds.t0), bounds.t1)
  }
  return { t }
}

/** 纪元秒 → datetime-local 的值(本地时区, 秒级)。 */
export function formatInstantInput(t) {
  if (!Number.isFinite(t)) return ''
  const d = new Date(t * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    + `T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
