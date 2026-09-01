// 调度页纯函数: 样品ID / 旋钮聚合 / 参数收集 / 实际 placements / 等待文案 / chip 映射
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  aggregateKnobs, buildActualPlacements, buildOverridesPayload, buildSubmitSummary,
  chipStateOf, collectChangedParams, genSampleIds, parallelPairs, shortSegLabel, waitReasonText,
} from '../src/utils/scheduler.js'

test('genSampleIds: 前缀+补零, 与后端 {prefix}-{02d} 规则一致', () => {
  assert.deepEqual(genSampleIds('B0729', 2), ['B0729-01', 'B0729-02'])
  assert.equal(genSampleIds('X', 10)[9], 'X-10')
  assert.equal(genSampleIds('X', 100)[99], 'X-100')   // 宽度随规模走
  assert.deepEqual(genSampleIds('X', 0), [])
})

test('shortSegLabel: 编号标签透传, 旧式剥前缀截括号, 无标签回退', () => {
  assert.equal(shortSegLabel('3 展开前拍照'), '3 展开前拍照')       // 正式段编号标签原样透传
  assert.equal(shortSegLabel('2-1 点样执行'), '2-1 点样执行')       // 并行支线 N-M 同样透传
  assert.equal(shortSegLabel('并行冒烟段A-占上样位 (集成验收用)'), '并行冒烟段A-占上样位')
  assert.equal(shortSegLabel('并行段-取板+展开前拍照 (板留台夹紧)'), '取板+展开前拍照')   // 旧式标签兼容
  assert.equal(shortSegLabel('普通标签'), '普通标签')
  assert.equal(shortSegLabel(''), '')
  assert.equal(shortSegLabel(null), '')
})

test('parallelPairs: DAG 可达性推导可并行段对; 链式方案零对', () => {
  // parallel_v1 形状 (拓扑序): s3∥s2, s7∥s6 是刻意并行; s3∥s4, s7∥s8 是 DAG 上同样成立的自由度
  const par = [
    { id: 'af0', label: '0', depends_on: [] },
    { id: 's1', label: '1', depends_on: ['af0'] },
    { id: 's2', label: '2-1', depends_on: ['s1'] },
    { id: 's3', label: '2-2', depends_on: ['s1'] },
    { id: 's4', label: '3', depends_on: ['s2'] },
    { id: 's5', label: '4', depends_on: ['s4', 's3'] },
    { id: 's6', label: '5-1', depends_on: ['s5'] },
    { id: 's7', label: '5-2', depends_on: ['s5'] },
    { id: 's8', label: '6', depends_on: ['s6'] },
    { id: 's9', label: '7', depends_on: ['s8', 's7'] },
    { id: 's10', label: '8', depends_on: ['s9'] },
    { id: 's11', label: '9', depends_on: ['s10'] },
  ]
  assert.deepEqual(parallelPairs(par),
    [['2-1', '2-2'], ['2-2', '3'], ['5-1', '5-2'], ['5-2', '6']])
  // 全链式 (serial_v1 形状) 零并行对
  const chain = [
    { id: 'a', label: 'A', depends_on: [] },
    { id: 'b', label: 'B', depends_on: ['a'] },
    { id: 'c', label: 'C', depends_on: ['b'] },
  ]
  assert.deepEqual(parallelPairs(chain), [])
  assert.deepEqual(parallelPairs([]), [])
})

test('aggregateKnobs: 并集归首个声明段, reuse 记录其余引用段; 无旋钮段保留空组 (全流程可见)', () => {
  const segments = [
    { seq: 1, id: 's1', op: 'op_a', label: '段A' },
    { seq: 2, id: 's2', op: 'op_b', label: '段B' },
    { seq: 3, id: 's3', op: 'op_c', label: '段C-无旋钮' },
  ]
  const knobsByOp = {
    op_a: [{ name: 'speed', type: 'FLOAT' }, { name: 'well', type: 'STRING' }],
    op_b: [{ name: 'speed', type: 'FLOAT' }, { name: 'auto_drain', type: 'BOOL' }],
    op_c: [],
  }
  const { groups, reuse } = aggregateKnobs(segments, knobsByOp)
  assert.equal(groups.length, 3, '无旋钮的段也必须成组 — 否则参数区看起来像流程被截断')
  assert.deepEqual(groups[0].knobs.map((k) => k.name), ['speed', 'well'])
  assert.deepEqual(groups[1].knobs.map((k) => k.name), ['auto_drain'])
  assert.deepEqual(groups[2].knobs, [])
  assert.equal(groups[2].label, '段C-无旋钮')
  assert.deepEqual(reuse.speed, ['段B'])
})

test('collectChangedParams: 空值与等于默认值的不收, 类型按旋钮强转', () => {
  const idx = {
    n: { name: 'n', type: 'INT', default: 3 },
    f: { name: 'f', type: 'FLOAT', default: 1.5 },
    b: { name: 'b', type: 'BOOL', default: false },
  }
  const out = collectChangedParams({ n: '5', f: '1.5', b: 'true', ghost: '' }, idx)
  assert.deepEqual(out, { n: 5, b: true })   // f 等于默认不收; ghost 空值不收
})

test('buildOverridesPayload: 空 cell 不写键 (缺键=继承批级)', () => {
  const idx = { v: { name: 'v', type: 'FLOAT' } }
  const rows = buildOverridesPayload([{ v: '2.5' }, { v: '' }, {}], idx)
  assert.deepEqual(rows, [{ v: 2.5 }, {}, {}])
})

test('buildActualPlacements: t0 相对化, RUNNING 段末端=now 开区间, 未开跑不出块', () => {
  const batch = { samples: [{ sample_id: 'S1', jobs: [
    { flow_id: 's1', seq: 1, script: 'a', status: 'DONE', started_at: 100, finished_at: 160 },
    { flow_id: 's2', seq: 2, script: 'b', status: 'RUNNING', started_at: 160, finished_at: null },
    { flow_id: 's3', seq: 3, script: 'c', status: 'PENDING', started_at: null },
  ] }] }
  const { t0, placements } = buildActualPlacements(batch, 220)
  assert.equal(t0, 100)
  assert.equal(placements.length, 2)
  const [p1, p2] = placements
  assert.equal(p1.start_s, 0)
  assert.equal(p1.duration_s, 60)
  assert.equal(p2.start_s, 60)
  assert.equal(p2.duration_s, 60)      // 220 - 160: 随 now 增长
  assert.equal(p2.running, true)
  assert.equal(p2.variant, 'actual')
  assert.deepEqual(p2.resources, [], '实际块不进资源泳道')
})

test('waitReasonText: 闭集映射; 未知码原样透出', () => {
  assert.equal(waitReasonText({ reason: 'no_tank' }), '等待空展开缸')
  assert.match(waitReasonText({ reason: 'waiting_resource', detail: 'robot 被 X 占用' }), /robot/)
  assert.match(waitReasonText({ reason: 'future_code', detail: 'x' }), /future_code/)
  assert.equal(waitReasonText(null), '')
})

test('chipStateOf 与 buildSubmitSummary', () => {
  assert.equal(chipStateOf('WAITING_HUMAN').cls, 'human')
  assert.equal(chipStateOf('未知态').label, '未知态')
  const text = buildSubmitSummary(
    { recipe: 'parallel_v1', autoDrain: true, tankSubset: [1, 2], wipLimit: 3 },
    { label: '并行全流程 v1' }, ['B-01', 'B-02'], 4)
  assert.match(text, /并行全流程 v1/)
  assert.match(text, /B-01 ~ B-02/)
  assert.match(text, /改动参数: 4 项/)
  assert.match(text, /展开缸: 1, 2/)
  assert.match(text, /实际驱动机构/)
})
