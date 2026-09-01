/**
 * 功能: 时间线视窗几何 / 拖动策略 / 分组 / 键盘映射.
 *
 * 这一组守的全是"错了也不报错"的东西: 锚点缩放漂移、向后擦洗少清一次场、本地时区被
 * 当成 UTC、空格键抢了输入框焦点。在浏览器里靠手感发现, 在这里只要一行断言。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAX_DRAIN_S,
  abLoopNext,
  axisTicksIn,
  packActionLanes,
  actionsAt,
  MANUAL_RUN,
  clampWindow,
  densityRequest,
  followWindow,
  formatInstantInput,
  keyIntent,
  niceTickStep,
  normalizeLoop,
  panBy,
  parseInstant,
  planScrub,
  pxToTime,
  ratioToTime,
  scrubTimeScale,
  snapToLive,
  timeToPx,
  timeToRatio,
  zoomAt,
} from '../../src/three-d/replay/timelineViewModel.js'

const T0 = 1786000000
const BOUNDS = { t0: T0, t1: T0 + 86400 }   // 一整天

// ── 视窗几何 ────────────────────────────────────────────────────────

test('zoomAt: 锚点下的时刻在缩放前后不动', () => {
  const view = { t0: T0, t1: T0 + 3600 }
  for (const ratio of [0, 0.25, 0.5, 0.83, 1]) {
    const anchorT = ratioToTime(ratio, view)
    const zoomed = zoomAt(view, ratio, 2, BOUNDS)
    assert.ok(Math.abs(ratioToTime(ratio, zoomed) - anchorT) < 1e-6,
      `锚点 ${ratio} 漂了: ${ratioToTime(ratio, zoomed)} != ${anchorT}`)
  }
})

test('zoomAt: 放大再缩小回到原跨度', () => {
  const view = { t0: T0 + 100, t1: T0 + 3700 }
  const back = zoomAt(zoomAt(view, 0.4, 2, BOUNDS), 0.4, 0.5, BOUNDS)
  assert.ok(Math.abs((back.t1 - back.t0) - (view.t1 - view.t0)) < 1e-6)
  assert.ok(Math.abs(back.t0 - view.t0) < 1e-6)
})

test('zoomAt: 缩不出边界, 也放不到比最小跨度更窄', () => {
  const huge = zoomAt({ t0: T0, t1: T0 + 3600 }, 0.5, 0.0001, BOUNDS)
  assert.equal(huge.t0, BOUNDS.t0)
  assert.equal(huge.t1, BOUNDS.t1)
  const tiny = zoomAt({ t0: T0, t1: T0 + 3600 }, 0.5, 1e9, BOUNDS)
  assert.ok(tiny.t1 - tiny.t0 >= 2 - 1e-9)
})

test('clampWindow: 贴右缘时保持跨度而不是截断', () => {
  const out = clampWindow({ t0: BOUNDS.t1 - 100, t1: BOUNDS.t1 + 500 }, BOUNDS)
  assert.equal(out.t1, BOUNDS.t1)
  assert.equal(out.t1 - out.t0, 600, '跨度被截断会让"拉到底再往回"每次都少一截')
})

test('clampWindow: 跨度超过可用范围就贴满', () => {
  const out = clampWindow({ t0: T0 - 1e6, t1: T0 + 1e6 }, BOUNDS)
  assert.deepEqual(out, { t0: BOUNDS.t0, t1: BOUNDS.t1 })
})

test('panBy: 撞边界贴边, 跨度不变', () => {
  const view = { t0: T0 + 1000, t1: T0 + 2000 }
  const left = panBy(view, -1e9, BOUNDS)
  assert.equal(left.t0, BOUNDS.t0)
  assert.equal(left.t1 - left.t0, 1000)
  const right = panBy(view, 1e9, BOUNDS)
  assert.equal(right.t1, BOUNDS.t1)
  assert.equal(right.t1 - right.t0, 1000)
})

test('px ↔ 时间 互为逆运算', () => {
  const view = { t0: T0, t1: T0 + 600 }
  for (const px of [0, 137, 640, 1280]) {
    assert.ok(Math.abs(timeToPx(pxToTime(px, view, 1280), view, 1280) - px) < 1e-6)
  }
  assert.equal(timeToRatio(T0 + 300, view), 0.5)
})

test('followWindow: 越过右缘才翻页, 且把播放头放到前段', () => {
  const view = { t0: T0, t1: T0 + 600 }
  assert.equal(followWindow(view, T0 + 100, BOUNDS).paged, false, '视窗内不该翻页')
  const out = followWindow(view, T0 + 590, BOUNDS)
  assert.equal(out.paged, true)
  assert.ok(timeToRatio(T0 + 590, out.view) < 0.3, '翻页后播放头应落在前段')
  assert.equal(out.view.t1 - out.view.t0, 600, '翻页不改跨度')
})

test('snapToLive: 右缘贴住实时边, 跨度不变', () => {
  const out = snapToLive({ t0: T0, t1: T0 + 600 }, BOUNDS.t1, BOUNDS)
  assert.equal(out.t1, BOUNDS.t1)
  assert.equal(out.t1 - out.t0, 600)
})

test('niceTickStep / axisTicksIn: 刻度落在整步长上', () => {
  assert.equal(niceTickStep(60, 6), 10)
  assert.equal(niceTickStep(86400, 6), 21600)
  const ticks = axisTicksIn({ t0: T0, t1: T0 + 600 }, 6)
  assert.ok(ticks.length >= 4 && ticks.length <= 12)
  const step = niceTickStep(600, 6)
  for (const tick of ticks) {
    assert.ok(tick.offset >= 0 && tick.offset <= 1)
    const local = tick.t - new Date(tick.t * 1000).getTimezoneOffset() * 60
    assert.equal(local % step, 0, '刻度必须落在整步长上, 否则读出来是 14:03:47 这种数')
  }
  assert.deepEqual(axisTicksIn({ t0: 5, t1: 5 }), [])
})

test('densityRequest: 瓦片量化后小幅平移不重取', () => {
  const a = densityRequest({ t0: T0, t1: T0 + 600 })
  const b = densityRequest({ t0: T0 + 5, t1: T0 + 605 })
  assert.deepEqual(a, b, '同一瓦片内的小平移应命中同一请求')
  assert.ok(a.t1 - a.t0 >= 600 * 2, '瓦片要比视窗宽, 才经得起平移')
  assert.equal(densityRequest({ t0: 5, t1: 5 }), null)
})

// ── 拖动策略 ────────────────────────────────────────────────────────

test('planScrub: 向后哪怕 0.1 秒也必须 seek', () => {
  const plan = planScrub({ playhead: T0 + 100, target: T0 + 99.9, loadedTo: T0 + 200 })
  assert.equal(plan.mode, 'seek',
    'AxisPoseBuffer 的到达时刻是单调取最大, 向后不清场会永久污染 staleness')
})

test('planScrub: 向前且数据在手走免费的 drain', () => {
  const plan = planScrub({ playhead: T0 + 100, target: T0 + 102, loadedTo: T0 + 200 })
  assert.equal(plan.mode, 'drain')
})

test('planScrub: 越过已预取窗口 / 前跳过大 都要 seek', () => {
  assert.equal(planScrub({ playhead: T0, target: T0 + 1, loadedTo: T0 + 0.5 }).mode, 'seek')
  assert.equal(planScrub({ playhead: T0, target: T0 + MAX_DRAIN_S + 1,
                           loadedTo: T0 + 999 }).mode, 'seek')
})

test('planScrub: 微小抖动当没动', () => {
  assert.equal(planScrub({ playhead: T0, target: T0 + 0.001, loadedTo: T0 + 99 }).mode, 'noop')
})

test('scrubTimeScale: 下限保 interp 收敛, 上限防积分器失控', () => {
  assert.equal(scrubTimeScale(0, 0.016), 4, '静止时也不能是 0 —— 0 会让 interp 完全停摆')
  assert.equal(scrubTimeScale(100, 0.016), 16)
  assert.ok(scrubTimeScale(0.16, 0.016) >= 4 && scrubTimeScale(0.16, 0.016) <= 16)
})

// ── A-B 循环 ────────────────────────────────────────────────────────

test('normalizeLoop: 自动排序, 过短返回 null', () => {
  assert.deepEqual(normalizeLoop(T0 + 20, T0 + 10), { a: T0 + 10, b: T0 + 20 })
  assert.equal(normalizeLoop(T0, T0 + 0.1), null)
  assert.equal(normalizeLoop(T0, NaN), null)
})

test('abLoopNext: 到 b 才绕, b 之前不绕', () => {
  const loop = { a: T0 + 10, b: T0 + 20 }
  assert.deepEqual(abLoopNext(T0 + 19.99, loop), { playhead: T0 + 19.99, wrapped: false })
  assert.deepEqual(abLoopNext(T0 + 20, loop), { playhead: T0 + 10, wrapped: true })
  assert.deepEqual(abLoopNext(T0 + 5, null), { playhead: T0 + 5, wrapped: false })
})

// ── 动作泳道 ────────────────────────────────────────────────────────

const VIEW = { t0: T0, t1: T0 + 100 }

test('packActionLanes: 一个运行一行, 段与时间轴共用同一套 x 映射', () => {
  const { lanes, total } = packActionLanes([
    { run_id: 'R2', aid: 'a1', action: 'robot.pick', ts: T0 + 50, done_ts: T0 + 60, status: 'DONE', script: 'collect' },
    { run_id: 'R1', aid: 'b2', action: 'pump.draw', ts: T0 + 20, done_ts: T0 + 30, status: 'DONE', script: 'sampling' },
    { run_id: 'R1', aid: 'b1', action: 'robot.home', ts: T0 + 5, done_ts: T0 + 15, status: 'DONE', script: 'sampling' },
  ], { view: VIEW, trackPx: 1000 })

  assert.equal(total, 3)
  assert.deepEqual(lanes.map((l) => l.runId), ['R1', 'R2'], '按首个动作时刻排')
  assert.equal(lanes[0].rows.length, 1, '顺序流程只占一行')
  const [first, second] = lanes[0].rows[0]
  assert.equal(first.left, 0.05, 'T0+5 落在 5%')
  assert.equal(first.width, 0.10)
  assert.equal(second.action, 'pump.draw')
})

test('packActionLanes: 同一运行里重叠的动作分到不同子泳道', () => {
  const { lanes } = packActionLanes([
    { run_id: 'R1', action: 'a', ts: T0 + 10, done_ts: T0 + 60, script: 'p' },
    { run_id: 'R1', action: 'b', ts: T0 + 20, done_ts: T0 + 40, script: 'p' },
    { run_id: 'R1', action: 'c', ts: T0 + 70, done_ts: T0 + 80, script: 'p' },
  ], { view: VIEW, trackPx: 1000 })
  assert.equal(lanes[0].rows.length, 2, '并行的两段不许画在同一行上互相盖住')
  assert.deepEqual(lanes[0].rows[0].map((s) => s.action), ['a', 'c'], '不重叠的接着排第一行')
  assert.deepEqual(lanes[0].rows[1].map((s) => s.action), ['b'])
})

test('packActionLanes: 未闭合的动作标成 open, 右端取证据末端', () => {
  const { lanes } = packActionLanes([
    { run_id: 'R1', action: 'moving', ts: T0 + 90, done_ts: null,
      open_until: T0 + 100, script: 'p' },
  ], { view: VIEW, trackPx: 1000 })
  const seg = lanes[0].rows[0][0]
  assert.equal(seg.open, true)
  assert.equal(seg.status, 'RUNNING')
  assert.equal(seg.endTs - seg.ts, 10, '证据止于 open_until')
})

test('packActionLanes: 窄段合并, 且聚合块不许滚雪球', () => {
  // 100 秒窗口 / 1000px -> 1px = 0.1s; 造 300 个 0.02s 的动作紧挨着排
  const dense = []
  for (let i = 0; i < 300; i += 1) {
    dense.push({ run_id: 'R1', action: `s${i}`, ts: T0 + i * 0.05,
                 done_ts: T0 + i * 0.05 + 0.02, status: 'DONE', script: 'p' })
  }
  const { lanes, total } = packActionLanes(dense, { view: VIEW, trackPx: 1000, minSegPx: 3 })
  assert.equal(total, 300)
  const segs = lanes[0].rows.flat()
  assert.ok(segs.length < 60, `窄段必须合并, 实际 ${segs.length} 段`)
  assert.equal(segs.reduce((sum, s) => sum + s.count, 0), 300, '合并不许吞掉动作')
  assert.match(segs[0].action, /等 \d+ 步/, '聚合块要说清里面有几步')

  // 合并判据若写成"与上一段的间隔 < minSegS", endT 每合并一次就往后长, 一串密集动作
  // 会滚雪球成一条横跨数小时的段。实测旧实现把这 300 个并成了**一条 14.97 秒**的段,
  // 而一个 minSeg 只有 0.3 秒。
  const minSegS = (3 / 1000) * 100
  const widest = Math.max(...segs.map((s) => s.endTs - s.ts))
  assert.ok(widest <= minSegS + 0.05,
    `聚合块最宽 ${widest.toFixed(3)} 秒, 超过一个 minSeg (${minSegS}) —— 滚雪球了`)
})

test('packActionLanes: 段长只来自数据, 缩放不许把它拉长', () => {
  // 这是"缩到最小时底下出现十几条横贯全宽的色带"的直接病根: 未闭合段原先画到 view.t1
  const items = [{ run_id: 'R1', action: 'x', ts: T0 + 10, done_ts: null,
                   open_until: T0 + 12, script: 'p' }]
  const narrow = packActionLanes(items, { view: { t0: T0, t1: T0 + 100 }, trackPx: 1000 })
  const wide = packActionLanes(items, { view: { t0: T0, t1: T0 + 100000 }, trackPx: 1000 })
  const seg = (r) => r.lanes[0].rows[0][0]
  assert.equal(seg(narrow).endTs - seg(narrow).ts, 2, '取 open_until - ts')
  assert.equal(seg(wide).endTs - seg(wide).ts, 2, '视窗放大 1000 倍, 段长必须一模一样')
  assert.equal(seg(wide).open, true)
})

test('packActionLanes: 没给 open_until 的未闭合段退化成一个点, 而不是视窗那么长', () => {
  const items = [{ run_id: 'R1', action: 'x', ts: T0 + 10, done_ts: null, script: 'p' }]
  const { lanes } = packActionLanes(items, { view: { t0: T0, t1: T0 + 100000 }, trackPx: 1000 })
  const seg = lanes[0].rows[0][0]
  assert.equal(seg.endTs - seg.ts, 0, '缺证据就是一个点; 绝不能拿视窗右缘去补')
})

test('packActionLanes: 缺 run_id 的落到合成组而不是被丢', () => {
  const { lanes } = packActionLanes([
    { action: 'manual.cylinder.dev_t1_cyl1', ts: T0 + 1, done_ts: T0 + 2, status: 'DONE' },
  ], { view: VIEW, trackPx: 1000 })
  assert.equal(lanes.length, 1)
  assert.equal(lanes[0].runId, MANUAL_RUN)
})

test('packActionLanes: 视窗外的动作不进泳道', () => {
  const { lanes, total } = packActionLanes([
    { run_id: 'R1', action: 'before', ts: T0 - 50, done_ts: T0 - 10, script: 'p' },
    { run_id: 'R1', action: 'after', ts: T0 + 200, done_ts: T0 + 210, script: 'p' },
    { run_id: 'R1', action: 'cross', ts: T0 - 10, done_ts: T0 + 10, script: 'p' },
  ], { view: VIEW, trackPx: 1000 })
  assert.equal(total, 1, '跨进视窗的要留, 完全在外的要滤掉')
  assert.equal(lanes[0].rows[0][0].action, 'cross')
})

test('packActionLanes: 失败在段与运行两级都标出来', () => {
  const { lanes } = packActionLanes([
    { run_id: 'R1', action: 'ok', ts: T0 + 1, done_ts: T0 + 2, status: 'DONE', script: 'p' },
    { run_id: 'R1', action: 'bad', ts: T0 + 50, done_ts: T0 + 60, status: 'FAILED', script: 'p' },
  ], { view: VIEW, trackPx: 1000 })
  assert.equal(lanes[0].failed, true, '收起时也要能一眼看出里面有失败')
  assert.equal(lanes[0].rows[0][1].failed, true)
})

test('packActionLanes: 折叠的运行不产出段, 但那一行还在', () => {
  const { lanes } = packActionLanes([
    { run_id: 'R1', action: 'x', ts: T0, done_ts: T0 + 1, status: 'DONE', script: 'p' },
  ], { view: VIEW, trackPx: 1000, collapsed: new Set(['R1']) })
  assert.equal(lanes.length, 1)
  assert.equal(lanes[0].collapsed, true)
  assert.deepEqual(lanes[0].rows, [])
})

test('packActionLanes: 空输入与非法视窗都不炸', () => {
  assert.deepEqual(packActionLanes(null, { view: VIEW }).lanes, [])
  assert.deepEqual(packActionLanes([{ ts: NaN }], { view: VIEW }).lanes, [])
  assert.deepEqual(packActionLanes([], { view: { t0: 5, t1: 5 } }).lanes, [])
})

test('actionsAt: 半开区间 —— 交接的那一刻不算两件事同时在跑', () => {
  const items = [
    { run_id: 'R1', action: 'a', ts: T0, done_ts: T0 + 10, script: 'p' },
    { run_id: 'R1', action: 'b', ts: T0 + 10, done_ts: T0 + 20, script: 'p' },
    { run_id: 'R2', action: 'c', ts: T0 + 5, done_ts: null, script: 'q' },
  ]
  assert.deepEqual(actionsAt(items, T0 + 10).map((a) => a.action), ['c', 'b'])
  assert.deepEqual(actionsAt(items, T0 + 7).map((a) => a.action), ['a', 'c'])
  assert.deepEqual(actionsAt(items, T0 - 1), [])
  assert.deepEqual(actionsAt(items, NaN), [])
})

// ── 键盘 ────────────────────────────────────────────────────────────

test('keyIntent: 焦点在可编辑元素里一律不拦', () => {
  assert.equal(keyIntent({ key: ' ', inEditable: true }), null,
    '否则用户在时刻输入框里打空格会让视频开始播放')
  assert.equal(keyIntent({ key: 'ArrowLeft', inEditable: true }), null)
})

test('keyIntent: 组合键留给浏览器与系统', () => {
  assert.equal(keyIntent({ key: ' ', ctrlKey: true }), null)
  assert.equal(keyIntent({ key: 'l', metaKey: true }), null)
  assert.equal(keyIntent({ key: 'ArrowRight', altKey: true }), null)
})

test('keyIntent: 常用播放键映射', () => {
  assert.deepEqual(keyIntent({ key: ' ' }), { kind: 'toggle' })
  assert.deepEqual(keyIntent({ key: 'k' }), { kind: 'toggle' })
  assert.deepEqual(keyIntent({ key: 'ArrowLeft' }), { kind: 'nudge', seconds: -10 })
  assert.deepEqual(keyIntent({ key: 'ArrowRight', shiftKey: true }), { kind: 'nudge', seconds: 1 })
  assert.deepEqual(keyIntent({ key: 'j' }), { kind: 'speed', direction: -1 })
  assert.deepEqual(keyIntent({ key: 'Home' }), { kind: 'jump', to: 'start' })
  assert.deepEqual(keyIntent({ key: 'End' }), { kind: 'jump', to: 'live' })
  assert.deepEqual(keyIntent({ key: 'a' }), { kind: 'loopMark', which: 'a' })
  assert.equal(keyIntent({ key: 'q' }), null)
  assert.equal(keyIntent(null), null)
})

// ── 时刻输入 ────────────────────────────────────────────────────────

test('parseInstant: 按本地时区解析, 不是 UTC', () => {
  const out = parseInstant('2026-08-13T00:00:00')
  assert.ok('t' in out)
  const d = new Date(out.t * 1000)
  assert.equal(d.getHours(), 0, '必须是本地零点 —— 与 dayRange 同一个陷阱')
  assert.equal(d.getDate(), 13)
  // 对照: 字符串解析会按 UTC 走, 非零时区必然不等
  if (new Date().getTimezoneOffset() !== 0) {
    assert.notEqual(out.t, Date.parse('2026-08-13') / 1000)
  }
})

test('parseInstant: 秒可省略; 格式不对给中文原因', () => {
  assert.ok('t' in parseInstant('2026-08-13T08:30'))
  assert.ok('t' in parseInstant('2026-08-13 08:30:15'))
  assert.match(parseInstant('八月十三').error, /格式/)
  assert.match(parseInstant('').error, /格式/)
})

test('parseInstant: 超出录像范围要明说, 而不是悄悄钳到边上', () => {
  const bounds = { t0: T0, t1: T0 + 100 }
  assert.match(parseInstant(formatInstantInput(T0 - 5000), bounds).error, /不在录像范围/)
  assert.ok('t' in parseInstant(formatInstantInput(T0 + 50), bounds))
})

test('formatInstantInput ↔ parseInstant 往返一致', () => {
  const t = Math.floor(T0 + 12345)
  const out = parseInstant(formatInstantInput(t))
  assert.equal(out.t, t)
  assert.equal(formatInstantInput(NaN), '')
})
