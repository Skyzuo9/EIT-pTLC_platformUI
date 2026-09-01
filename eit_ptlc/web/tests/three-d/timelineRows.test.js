/**
 * 功能: 三维时间线条带的"树 -> 行"摊平变换测试.
 *
 * 锁的是本次修复的根因: 条带曾自带一份事件白名单(只认 operation_ / step_ 两族), 而 VM 每步
 * 实际发 vm_node_enter/vm_node_done, 于是 91% 的步骤被静默丢掉 —— 一次 178 步的运行
 * 只显示起止两行。因此这里的核心断言是**行数等于真实步骤数**, 而非只断言"有行"。
 *
 * ⚠ 本文件的 fixture 必须发生产事件形状: 步骤事件是 vm_node_enter/vm_node_done, 且
 * 只有 op 为 call / run_script 的节点成步(控制流 if/for/parallel 不发 enter/done)。
 * 改成 step_start/step_done 等于把该 BUG 放回来 —— 那两个名字只剩维护面板单发动作在用。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { reduceRun } from '../../src/stores/runs.js'
import { flattenSteps, formatEpoch, isFailedStatus, runSummary } from '../../src/three-d/twin/timelineRows.js'

const MANIFEST = {
  stations: [
    { id: 'sampling', label: '上样站', actionPrefixes: ['sampling.', 'feedlift.'] },
    { id: 'robot', label: '机械臂', actionPrefixes: ['robot.'] },
  ],
}

/** 生产形状的 enter 事件 */
function enter(aid, action, op = 'call', ts = 1000) {
  return { type: 'vm_node_enter', aid, action, op, ts }
}

/** 生产形状的 done 事件 */
function done(aid, action, op = 'call', status = 'DONE', ts = 1001) {
  return { type: 'vm_node_done', aid, action, op, status, ts }
}

test('vm_node_* 事件全部成行: 行数等于真实步骤数, 而非只剩起止两行', () => {
  const events = [
    { type: 'operation_start', run_id: 'r1', operation: 'sampling_load', label: '上样', ts: 999 },
    enter('b/0', 'robot.feed_lift_pick'),
    done('b/0', 'robot.feed_lift_pick'),
    enter('b/1', 'feedlift.host'),
    done('b/1', 'feedlift.host'),
    enter('b/2', 'sampling.execute'),
    done('b/2', 'sampling.execute'),
    { type: 'operation_done', status: 'DONE', ts: 1010 },
  ]

  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)

  assert.equal(rows.length, 3, '三个 call 步应摊出三行')
  assert.deepEqual(
    rows.map((r) => r.action),
    ['robot.feed_lift_pick', 'feedlift.host', 'sampling.execute'],
  )
  assert.ok(rows.every((r) => r.status === 'DONE'))
})

test('run_script 嵌套: 容器行保留, 子步 depth 加一', () => {
  const events = [
    { type: 'operation_start', run_id: 'r2', operation: 'sampling_cycle', ts: 999 },
    enter('b/0', 'sampling_execute', 'run_script'),
    enter('b/0', 'sampling.draw'),          // 子帧内 aid 同样从 b/0 起
    done('b/0', 'sampling.draw'),
    enter('b/1', 'sampling.dispense'),
    done('b/1', 'sampling.dispense'),
    done('b/0', 'sampling_execute', 'run_script'),
  ]

  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)

  assert.equal(rows.length, 3, '容器行 + 两个子步')
  assert.deepEqual(
    rows.map((r) => [r.action, r.depth]),
    [['sampling_execute', 0], ['sampling.draw', 1], ['sampling.dispense', 1]],
  )
  assert.equal(rows[0].isGroup, true, '有子步的行标记为分组')
  assert.equal(rows[1].isGroup, false)
})

test('父子同号 aid 不互相覆盖(帧内匹配)', () => {
  const events = [
    enter('b/0', 'outer', 'run_script'),
    enter('b/0', 'inner'),
    done('b/0', 'inner'),
    done('b/0', 'outer', 'run_script'),
  ]

  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)
  assert.equal(rows.length, 2, '同号 aid 分属不同帧, 应各自成行')
  assert.deepEqual(rows.map((r) => r.action), ['outer', 'inner'])
})

test('控制流节点不成步(if/for/parallel 不入行)', () => {
  const events = [
    { type: 'vm_node_enter', aid: 'b/0', op: 'if', ts: 1000 },
    { type: 'vm_node_enter', aid: 'b/1', op: 'for', ts: 1000 },
    enter('b/2', 'sampling.draw'),
    done('b/2', 'sampling.draw'),
    { type: 'vm_vars', vars: { i: 1 } },
  ]

  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].action, 'sampling.draw')
})

test('工位反查按 actionPrefixes 命中; manifest 缺失时工位列留空', () => {
  const events = [enter('b/0', 'sampling.draw'), done('b/0', 'sampling.draw')]
  const tree = reduceRun(events).steps

  const withManifest = flattenSteps(tree, MANIFEST)
  assert.equal(withManifest[0].stationId, 'sampling')
  assert.equal(withManifest[0].stationLabel, '上样站')

  const without = flattenSteps(tree, null)
  assert.equal(without[0].stationId, null)
  assert.equal(without[0].stationLabel, '', 'manifest 缺失不应抛错')
})

test('未匹配任何前缀的动作不报错, 工位留空', () => {
  const events = [enter('b/0', 'unknown.thing'), done('b/0', 'unknown.thing')]
  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)
  assert.equal(rows[0].stationId, null)
  assert.equal(rows[0].stationLabel, '')
})

test('失败态标红: FAILED/ERROR/KILLED/CANCELLED 皆算失败', () => {
  for (const status of ['FAILED', 'ERROR', 'KILLED', 'CANCELLED']) {
    assert.equal(isFailedStatus(status), true, `${status} 应算失败`)
  }
  assert.equal(isFailedStatus('DONE'), false)
  assert.equal(isFailedStatus('RUNNING'), false)

  const events = [
    enter('b/0', 'sampling.draw'),
    done('b/0', 'sampling.draw', 'call', 'FAILED', 1005),
  ]
  const rows = flattenSteps(reduceRun(events).steps, MANIFEST)
  assert.equal(rows[0].failed, true, '失败行应可被模板标红')
})

test('在途步骤(只有 enter)也成行, 状态为 RUNNING', () => {
  const rows = flattenSteps(reduceRun([enter('b/0', 'sampling.draw')]).steps, MANIFEST)
  assert.equal(rows.length, 1, '流程跑到一半时条带就该有行, 不必等 done')
  assert.equal(rows[0].status, 'RUNNING')
})

test('ts 透传到行上, 时间列才有值', () => {
  const rows = flattenSteps(reduceRun([enter('b/0', 'sampling.draw', 'call', 1750000000)]).steps, MANIFEST)
  assert.equal(rows[0].ts, 1750000000, '时间戳缺失会让整列恒为占位符')
})

test('flattenSteps 对空输入与缺字段稳健', () => {
  assert.deepEqual(flattenSteps(null), [])
  assert.deepEqual(flattenSteps([]), [])
  const rows = flattenSteps([{}], MANIFEST)
  assert.equal(rows.length, 1)
  assert.equal(rows[0].action, '')
  assert.equal(rows[0].ts, null)
})

test('formatEpoch: 无时间戳给占位, 有则取时分秒', () => {
  assert.equal(formatEpoch(null), '--:--:--')
  assert.equal(formatEpoch(0), '--:--:--')
  assert.equal(formatEpoch(Number.NaN), '--:--:--')
  assert.match(formatEpoch(1750000000), /^\d{2}:\d{2}:\d{2}$/)
})

test('runSummary: label 优先于 operation, 缺 id 的行可被过滤掉', () => {
  assert.equal(runSummary({ run_id: 'r1', label: '上样', operation: 'sampling_load' }).name, '上样')
  assert.equal(runSummary({ run_id: 'r1', operation: 'sampling_load' }).name, 'sampling_load')
  assert.equal(runSummary({ id: 'r2' }).id, 'r2', 'id 与 run_id 两种字段名都要认')
  assert.equal(runSummary({}).id, '')
  assert.equal(runSummary(null).id, '')
})
