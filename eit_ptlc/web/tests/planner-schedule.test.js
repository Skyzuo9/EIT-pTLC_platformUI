import test from 'node:test'
import assert from 'node:assert/strict'

import { scheduleGreedy, detectConflicts, niceTicks, fmtDur, buildDurationIndex, FALLBACK_DURATION_S } from '../src/utils/planner.js'

// 时长索引构造小工具: {流程名: {duration_s, resources}} (口径已在 buildDurationIndex 定死)
const stats = (entries) => Object.fromEntries(entries.map(([name, dur, res]) => [name, { duration_s: dur, resources: res }]))
const MODES = { robot: 'exclusive', 'station:a': 'exclusive', 'station:b': 'exclusive', 'device:pump': 'shared' }
const sample = (id, chain) => ({ id, label: id, chain })
const byKey = (out) => Object.fromEntries(out.placements.map((p) => [p.key, p]))

test('同 exclusive 资源: 两样品严格串行, makespan = 2×avg', () => {
  const idx = stats([['opX', 100, ['robot']]])
  const out = scheduleGreedy([sample('A', ['opX']), sample('B', ['opX'])], idx, MODES)
  const m = byKey(out)
  assert.equal(m['A#0'].start_s, 0)
  assert.equal(m['A#0'].end_s, 100)
  assert.equal(m['B#0'].start_s, 100)   // B 等 A 释放 robot
  assert.equal(out.makespan_s, 200)
})

test('不同资源: 两样品并行, makespan = 较长者', () => {
  const idx = stats([['opX', 100, ['station:a']], ['opY', 40, ['station:b']]])
  const out = scheduleGreedy([sample('A', ['opX']), sample('B', ['opY'])], idx, MODES)
  const m = byKey(out)
  assert.equal(m['A#0'].start_s, 0)
  assert.equal(m['B#0'].start_s, 0)
  assert.equal(out.makespan_s, 100)
})

test('样品内链序: 后块不早于前块结束, 即使资源空闲', () => {
  const idx = stats([['opX', 100, ['station:a']], ['opY', 40, ['station:b']]])
  const out = scheduleGreedy([sample('A', ['opX', 'opY'])], idx, MODES)
  const m = byKey(out)
  assert.equal(m['A#1'].start_s, 100)   // station:b 空闲, 但要等 opX 结束
  assert.equal(out.makespan_s, 140)
})

test('FIFO 平局: 先定义的样品先占资源', () => {
  const idx = stats([['opX', 50, ['robot']]])
  const out = scheduleGreedy([sample('B', ['opX']), sample('A', ['opX'])], idx, MODES)
  const m = byKey(out)
  assert.equal(m['B#0'].start_s, 0)     // B 定义在前, 先占
  assert.equal(m['A#0'].start_s, 50)
})

test('shared 资源不阻塞: 可重叠', () => {
  const idx = stats([['opX', 60, ['device:pump']]])
  const out = scheduleGreedy([sample('A', ['opX']), sample('B', ['opX'])], idx, MODES)
  const m = byKey(out)
  assert.equal(m['A#0'].start_s, 0)
  assert.equal(m['B#0'].start_s, 0)
  assert.equal(out.makespan_s, 60)
})

test('无历史流程: 回落估计时长并标 estimated', () => {
  const out = scheduleGreedy([sample('A', ['opUnknown'])], {}, MODES)
  const p = out.placements[0]
  assert.equal(p.duration_s, FALLBACK_DURATION_S)
  assert.equal(p.estimated, true)
  // duration_s 为 null (count=0 或基线清空) 同样回落
  const out2 = scheduleGreedy([sample('A', ['opZ'])], { opZ: { duration_s: null, resources: [] } }, MODES)
  assert.equal(out2.placements[0].estimated, true)
})

test('buildDurationIndex: 平均/最新两种口径取不同字段', () => {
  const payload = {
    operations: [
      { name: 'opX', avg_s: 100, last_s: 130, count: 3, resources: ['robot'] },
      { name: 'opY', avg_s: 40, last_s: 40, count: 1, resources: [] },
    ],
  }
  const avg = buildDurationIndex(payload, 'avg')
  assert.equal(avg.opX.duration_s, 100)
  assert.deepEqual(avg.opX.resources, ['robot'])
  assert.equal(avg.opX.count, 3)
  const last = buildDurationIndex(payload, 'last')
  assert.equal(last.opX.duration_s, 130)
  assert.equal(last.opY.duration_s, 40)
  // 口径切换直接改变排布: 最新口径下块更长
  const s = [sample('A', ['opX'])]
  assert.equal(scheduleGreedy(s, avg, MODES).makespan_s, 100)
  assert.equal(scheduleGreedy(s, last, MODES).makespan_s, 130)
})

test('buildDurationIndex: 无历史/基线清空 (null 或 0) 落成 null, 资源仍保留', () => {
  const payload = {
    operations: [
      { name: 'opNone', avg_s: null, last_s: null, count: 0, resources: ['station:a'] },
      { name: 'opZero', avg_s: 0, last_s: 0, count: 0, resources: [] },
    ],
  }
  const idx = buildDurationIndex(payload, 'avg')
  assert.equal(idx.opNone.duration_s, null)
  assert.deepEqual(idx.opNone.resources, ['station:a'])   // 资源不受清除影响, 仍参与互斥
  assert.equal(buildDurationIndex(payload, 'last').opZero.duration_s, null)
  // 排程时回落为估计块
  const out = scheduleGreedy([sample('A', ['opNone'])], idx, MODES)
  assert.equal(out.placements[0].duration_s, FALLBACK_DURATION_S)
  assert.equal(out.placements[0].estimated, true)
  assert.deepEqual(out.placements[0].resources, ['station:a'])
})

test('buildDurationIndex: 空/缺失响应返回空索引', () => {
  assert.deepEqual(buildDurationIndex(null, 'avg'), {})
  assert.deepEqual(buildDurationIndex({}, 'avg'), {})
  assert.deepEqual(buildDurationIndex({ operations: [] }, 'last'), {})
})

test('空链样品跳过, 未知资源保守当 exclusive', () => {
  const idx = stats([['opX', 30, ['mystery:res']]])
  const out = scheduleGreedy([sample('E', []), sample('A', ['opX']), sample('B', ['opX'])], idx, {})
  const m = byKey(out)
  assert.equal(out.placements.length, 2)
  assert.equal(m['B#0'].start_s, 30)    // mystery:res 未登记 → 按独占串行
})

test('确定性: 同输入两次调用深等', () => {
  const idx = stats([['opX', 100, ['robot']], ['opY', 40, ['station:a']]])
  const samples = [sample('A', ['opX', 'opY']), sample('B', ['opY', 'opX'])]
  assert.deepEqual(scheduleGreedy(samples, idx, MODES), scheduleGreedy(samples, idx, MODES))
})

test('冲突检测: 资源重叠命中, 首尾相接不算', () => {
  const mk = (key, start, end, res) => ({ key, sampleId: key.split('#')[0], index: +key.split('#')[1], start_s: start, end_s: end, resources: res })
  // 重叠
  const overlap = detectConflicts([mk('A#0', 0, 100, ['robot']), mk('B#0', 50, 120, ['robot'])], MODES)
  assert.equal(overlap.length, 1)
  assert.equal(overlap[0].type, 'resource')
  assert.equal(overlap[0].resource, 'robot')
  // 首尾相接: 不算
  const touch = detectConflicts([mk('A#0', 0, 100, ['robot']), mk('B#0', 100, 150, ['robot'])], MODES)
  assert.equal(touch.length, 0)
  // shared 重叠: 不算
  const shared = detectConflicts([mk('A#0', 0, 100, ['device:pump']), mk('B#0', 0, 100, ['device:pump'])], MODES)
  assert.equal(shared.length, 0)
})

test('冲突检测: 长块跨越多块时非相邻重叠也能命中', () => {
  const mk = (key, start, end) => ({ key, sampleId: key.split('#')[0], index: 0, start_s: start, end_s: end, resources: ['robot'] })
  const out = detectConflicts([mk('A#0', 0, 100), mk('B#0', 10, 20), mk('C#0', 30, 40)], MODES)
  // A-B 与 A-C 都重叠 (扫描线保持运行中最大 end, 不是只比相邻)
  assert.equal(out.length, 2)
  assert.deepEqual(out.map((c) => c.b).sort(), ['B#0', 'C#0'])
})

test('冲突检测: 样品内顺序倒置命中', () => {
  const mk = (key, index, start, end) => ({ key, sampleId: 'A', index, start_s: start, end_s: end, resources: [] })
  const out = detectConflicts([mk('A#0', 0, 50, 150), mk('A#1', 1, 0, 40)], MODES)
  assert.equal(out.length, 1)
  assert.equal(out[0].type, 'order')
  assert.equal(out[0].b, 'A#1')
})

test('niceTicks: 步长取第一个满足最小像素间距的候选', () => {
  const { stepS, ticks } = niceTicks(600, 1, 70)   // 60*1=60px 不够, 120*1=120px 够
  assert.equal(stepS, 120)
  assert.deepEqual(ticks.map((t) => t.t), [0, 120, 240, 360, 480, 600])
  assert.equal(ticks[1].label, '2:00')
  // 亚秒级 (sim 数据 + 适配缩放)
  const fine = niceTicks(0.5, 1600, 70)
  assert.ok(fine.stepS <= 0.1)
})

test('fmtDur: 毫秒/秒/分秒/时分', () => {
  assert.equal(fmtDur(0.4), '400ms')
  assert.equal(fmtDur(12.7), '12.7s')
  assert.equal(fmtDur(305.2), '5m05s')
  assert.equal(fmtDur(3725), '1h02m')
  assert.equal(fmtDur(null), '—')
})
