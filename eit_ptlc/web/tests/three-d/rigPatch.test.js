/**
 * 功能: rig_map 写回补丁集的纯逻辑单测.
 *
 * 值得单测的理由: rig_map 是运动学唯一固化真源, 写坏 = 重跑 40-60s 后管线烂掉;
 * 尤其 carriage_members 的对象格式契约(equals/expect_count)曾有过写错字段名
 * (carriage_nodes)从未生效的前科 —— 用测试把契约锁死.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { parseDocument } from 'yaml'

import {
  patchRigMapAxisCalib,
  patchRigMapAxisDirection,
  patchRigMapCarriage,
  patchRigMapLiquid,
  patchRigMapMotionParams,
  readRigMapAxis,
  readRigMapLiquidEnabled,
} from '../../src/three-d/motion/rigPatch.js'

const SAMPLE = `# rig_map 顶注释, 一个字都不能动
axes:
  - id: axis_11y
    station: RAIL
    label: 地轨轴11Y   # 行内注释也要保住
    carriage_members:
      - {equals: "WEF50-N-KL-1", expect_count: 1}
    axis: [1, 0, 0]
    sign: -1
    zero_offset_mm: 500.0
    range_mm: [0, 3000]
    rigged: true
  - id: axis_1z
    station: FEEDLIFT
    label: 玻璃上料轴1Z
    carriage_groups: []
    axis: [0, 1, 0]
    sign: 1
    range_mm: [0, 700]
    rigged: false
actuators:
  - id: rob_flip_suction
    node: A/ACTUATOR_FLIP_SUCTION
    motion: rotate
    sign: 1
    outputRange: [0, 180]
    transitionS: 0.6
linkages:
  - id: rob_grip_vial
    transitionS: 0.15
    members:
      - {node: A/L, axis: [1, 0, 0], sign: 1, outputRange: [0, 12.5], unitScale: 0.001}
      - {node: A/R, axis: [1, 0, 0], sign: -1, outputRange: [0, 12.5], unitScale: 0.001}
tanks:
  liquid:
    enabled: false
`

test('carriage 指认写对象格式匹配器 + rigged:true, 注释保全', () => {
  const out = patchRigMapCarriage(SAMPLE, 'axis_1z', [
    { equals: '同步带连接板-1', expect_count: 2 },
    { equals: '_LRM9BK-N-H-A-1', expect_count: 1 },
  ])
  assert.match(out, /rig_map 顶注释/)
  assert.match(out, /行内注释也要保住/)
  const axis = readRigMapAxis(out, 'axis_1z')
  assert.equal(axis.rigged, true)
  assert.equal(axis.assigned_by, 'workbench-assign')
  assert.deepEqual(axis.carriage_members, [
    { equals: '同步带连接板-1', expect_count: 2 },
    { equals: '_LRM9BK-N-H-A-1', expect_count: 1 },
  ])
  // 别的轴一个字段都不动
  assert.deepEqual(readRigMapAxis(out, 'axis_11y').carriage_members, [
    { equals: 'WEF50-N-KL-1', expect_count: 1 },
  ])
})

test('carriage 指认拒绝空成员(防止把轴打回 rigged:false)', () => {
  assert.throws(() => patchRigMapCarriage(SAMPLE, 'axis_1z', []), /拒绝写回/)
  assert.throws(() => patchRigMapCarriage(SAMPLE, 'axis_none', [{ equals: 'x', expect_count: 1 }]), /找不到轴/)
  assert.throws(
    () => patchRigMapCarriage(SAMPLE, 'axis_1z', [{ expect_count: 1 }]),
    /equals 或 contains/,
  )
})

test('运动参数写回: 执行器三字段 + 联动组成员对称行程', () => {
  const out = patchRigMapMotionParams(SAMPLE, {
    actuators: { rob_flip_suction: { sign: -1, outputRange: [0, 90], transitionS: 0.4 } },
    linkages: { rob_grip_vial: { transitionS: 0.2, outputRange: [0, 10] } },
  })
  const js = parseDocument(out).toJS()
  const actuator = js.actuators[0]
  assert.equal(actuator.sign, -1)
  assert.deepEqual(actuator.outputRange, [0, 90])
  assert.equal(actuator.transitionS, 0.4)
  const linkage = js.linkages[0]
  assert.equal(linkage.transitionS, 0.2)
  for (const member of linkage.members) {
    assert.deepEqual(member.outputRange, [0, 10])
    // node/sign/unitScale 原样
    assert.ok(member.node)
    assert.ok(member.unitScale)
  }
})

test('标定三字段按 id 回填(camelCase -> snake_case)', () => {
  const out = patchRigMapAxisCalib(SAMPLE, [
    { id: 'axis_11y', zeroOffsetMm: 512.4, sign: 1, rangeMm: [-10, 3000] },
  ])
  const axis = readRigMapAxis(out, 'axis_11y')
  assert.equal(axis.zero_offset_mm, 512.4)
  assert.equal(axis.sign, 1)
  assert.deepEqual(axis.range_mm, [-10, 3000])
  // 未列字段不动
  assert.equal(axis.rigged, true)
})

test('液体开关只改一行', () => {
  assert.equal(readRigMapLiquidEnabled(SAMPLE), false)
  const out = patchRigMapLiquid(SAMPLE, true)
  assert.equal(readRigMapLiquidEnabled(out), true)
  assert.match(out, /rig_map 顶注释/)
})

test('往返幂等: 同参数写两次产物一致', () => {
  const members = [{ equals: 'x-1', expect_count: 1 }]
  const once = patchRigMapCarriage(SAMPLE, 'axis_1z', members)
  const twice = patchRigMapCarriage(once, 'axis_1z', members)
  assert.equal(once, twice)
})

test('carriage 重指认保留既有成员的 within 限定(孪生机构约束不丢)', () => {
  const withWithin = patchRigMapCarriage(SAMPLE, 'axis_1z', [
    { equals: '滑块连接板-1', within: '玻璃上料机构', expect_count: 1 },
    { equals: '玻璃放置板-1', expect_count: 1 },
  ])
  // 前端重新指认时不带 within(尚不感知该字段) —— 同名 equals 的 within 要自动迁移
  const reassigned = patchRigMapCarriage(withWithin, 'axis_1z', [
    { equals: '滑块连接板-1', expect_count: 1 },
    { equals: '新增件-1', expect_count: 1 },
  ])
  assert.deepEqual(readRigMapAxis(reassigned, 'axis_1z').carriage_members, [
    { equals: '滑块连接板-1', within: '玻璃上料机构', expect_count: 1 },
    { equals: '新增件-1', expect_count: 1 },
  ])
  // 显式给出的 within 优先于迁移值
  const explicit = patchRigMapCarriage(withWithin, 'axis_1z', [
    { equals: '滑块连接板-1', within: '玻璃下料机构', expect_count: 1 },
  ])
  assert.deepEqual(readRigMapAxis(explicit, 'axis_1z').carriage_members, [
    { equals: '滑块连接板-1', within: '玻璃下料机构', expect_count: 1 },
  ])
})

test('运动方向写回: axis 向量 + sign 归一, 注释保全', () => {
  const out = patchRigMapAxisDirection(SAMPLE, 'axis_1z', [0, 0, 1], -3)
  assert.match(out, /rig_map 顶注释/)
  assert.match(out, /行内注释也要保住/)
  const axis = readRigMapAxis(out, 'axis_1z')
  assert.deepEqual(axis.axis, [0, 0, 1])
  assert.equal(axis.sign, -1)
  // 其余字段不动
  assert.deepEqual(axis.range_mm, [0, 700])
  assert.equal(readRigMapAxis(out, 'axis_11y').sign, -1)
})

test('运动方向写回: 非法向量与未知轴拒绝', () => {
  assert.throws(() => patchRigMapAxisDirection(SAMPLE, 'axis_1z', [0, 0, 0], 1), /非零三元组/)
  assert.throws(() => patchRigMapAxisDirection(SAMPLE, 'axis_1z', [0, 1], 1), /非零三元组/)
  assert.throws(() => patchRigMapAxisDirection(SAMPLE, 'axis_none', [1, 0, 0], 1), /找不到轴/)
})
