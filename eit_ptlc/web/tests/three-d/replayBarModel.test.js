/**
 * 功能: 回放条的纯计算 —— 时区、标记优先级、密度条最低可见高度、刻度。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  utilizationHeights,
  axisTicks,
  dayRange,
  formatClock,
  formatSpan,
  layoutMarkers,
} from '../../src/three-d/replay/replayBarModel.js'

test('dayRange 按分量构造本地半开区间, 不能被 UTC 解析偏掉', () => {
  const range = dayRange('2026-08-13')
  const start = new Date(range.since * 1000)
  assert.equal(start.getFullYear(), 2026)
  assert.equal(start.getMonth(), 7)
  assert.equal(start.getDate(), 13)
  assert.equal(start.getHours(), 0, '必须是本地 00:00, 而不是 UTC 00:00')
  assert.equal(range.until - range.since, 86400)

  // 对照: new Date('2026-08-13') 按 UTC 解析, 东八区会落到前一天 08:00
  const utcParsed = new Date('2026-08-13').getTime() / 1000
  if (new Date().getTimezoneOffset() !== 0) {
    assert.notEqual(utcParsed, range.since, '这正是不能用字符串解析的原因')
  }
  assert.equal(dayRange('nonsense'), null)
})

test('formatSpan 覆盖秒到天', () => {
  assert.equal(formatSpan(12.34), '12.3 秒')
  assert.match(formatSpan(125), /2 分/)
  assert.match(formatSpan(7200), /2 小时/)
  assert.match(formatSpan(180000), /2.1 天/)
  assert.equal(formatSpan(-1), '--')
  assert.equal(formatSpan(NaN), '--')
})

test('formatClock 处理非法值而不是抛错', () => {
  assert.equal(formatClock(NaN), '--:--:--')
  assert.match(formatClock(1786000000), /^\d{2}:\d{2}:\d{2}$/)
  assert.match(formatClock(1786000000, true), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
})

test('标记按优先级去重 —— 红点绝不会被灰点盖住', () => {
  const t0 = 1786000000
  const markers = [
    { ts: t0 + 10.0, kind: 'step', label: '步骤' },
    { ts: t0 + 10.001, kind: 'alarm', label: '撞了' },
    { ts: t0 + 10.002, kind: 'operation', label: '流程' },
  ]
  const laid = layoutMarkers(markers, t0, t0 + 100, 100)
  assert.equal(laid.length, 1, '同一像素桶只保留一条')
  assert.equal(laid[0].kind, 'alarm')
  assert.equal(laid[0].label, '撞了')
  assert.equal(laid[0].color, '#ff5a5f')
})

test('标记按半开区间过滤并落到 [0,1]', () => {
  const t0 = 1786000000
  const laid = layoutMarkers([
    { ts: t0 - 1, kind: 'alarm' },
    { ts: t0, kind: 'alarm' },
    { ts: t0 + 50, kind: 'hold' },
    { ts: t0 + 100, kind: 'alarm' },   // 上界开区间, 应排除
  ], t0, t0 + 100, 400)
  assert.deepEqual(laid.map((m) => m.offset), [0, 0.5])
})

test('区间非法时标记布局返回空而不是崩', () => {
  assert.deepEqual(layoutMarkers([{ ts: 1, kind: 'alarm' }], 5, 5), [])
  assert.deepEqual(layoutMarkers(null, 0, 10), [])
})

test('利用率条: 空闲是空白, 满负荷是满格, 分母固定不随窗口漂', () => {
  const bars = utilizationHeights([0, 1, 9], 9, [[], ['rail'], [
    'collect', 'develop', 'feedlift', 'photoscrape', 'pump', 'rail', 'robot',
    'sampling', 'staginga']])
  assert.equal(bars[0].height, 0, '有录像但没动 = 空白')
  assert.equal(bars[0].count, 0)
  assert.equal(bars[1].height, 12, '一个工位在动占 1/9, 抬到最低可见高度')
  assert.equal(bars[2].height, 100)
  assert.deepEqual(bars[1].stations, ['rail'])
  // 同一批数据换个窗口(峰值只有 1)高度必须不变 —— 按峰值缩放就会变成 100
  assert.equal(utilizationHeights([1], 9)[0].height, 12)
})

test('利用率条: "没录到" / "没补算" / "确实没动" 三者不许混成一种', () => {
  // 把录像空洞画成"空闲", 等于用一段没录到的时间证明设备当时是好的
  const bars = utilizationHeights([null, null, 0], 9, [], [false, true, true])
  assert.equal(bars[0].gap, true, '该时段根本没有录像')
  assert.equal(bars[0].unknown, false)
  assert.equal(bars[1].unknown, true, '有块但还没补算过活动度')
  assert.equal(bars[1].gap, false)
  assert.equal(bars[2].unknown, false)
  assert.equal(bars[2].gap, false)
  assert.deepEqual(utilizationHeights(null, 9), [])
})

test('刻度跨度超过一天时带上日期', () => {
  const t0 = 1786000000
  const short = axisTicks(t0, t0 + 600, 4)
  assert.equal(short.length, 5)
  assert.match(short[0].label, /^\d{2}:\d{2}:\d{2}$/)
  assert.equal(short[4].offset, 1)

  const long = axisTicks(t0, t0 + 3 * 86400, 4)
  assert.match(long[0].label, /^\d{4}-\d{2}-\d{2} /, '跨天必须带日期, 否则 03:00 是哪天分不清')
  assert.deepEqual(axisTicks(5, 5), [])
})
