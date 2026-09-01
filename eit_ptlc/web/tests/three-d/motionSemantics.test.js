/**
 * 功能: 运动语义分类的纯逻辑单测.
 *
 * 值得单测的理由: classifySemantics 是动作界面的数据地基 —— 着色、列表、调试卡
 * 都吃它的产物. 分类错(rigged 判反/耗材漏掉)会让"哪些东西会动"这个核心答案静默出错.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CATEGORY_LABELS,
  classifySemantics,
  KIND_GROUPS,
  markAxisResolveFailures,
  SEMANTIC_COLORS,
} from '../../src/three-d/motion/motionSemantics.js'

const MANIFEST = {
  axes: [
    { id: 'axis_11y', label: '地轨', station: 'RAIL', rigged: true, glbNode: 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE', axis: [1, 0, 0], sign: -1, rangeMm: [0, 3000], zeroOffsetMm: 500 },
    { id: 'axis_1z', label: '上样Z', station: 'SAMPLING', rigged: false, glbNode: null, rangeMm: [0, 100] },
  ],
  robot: {
    label: 'CR5', glbNode: 'ST_ROBOT/CR5', jointsRigged: true,
    joints: [
      { id: 'J1', linkNode: 'CR5_LINK1', limitDeg: [-359, 359], sign: 1 },
      { id: 'J2', linkNode: 'CR5_LINK2', limitDeg: [-359, 359], sign: 1 },
    ],
  },
  tools: [{ id: 'TOOL_PLATE96', label: '96孔夹爪', controllerTool: 2, glbNode: 'ST_TOOLING/x/TOOL_PLATE96', dockNode: 'D', mountNode: 'TOOL_MOUNT' }],
  actuators: [{ id: 'rob_flip_suction', label: '吸盘翻转', node: 'ST_TOOLING/x/ACTUATOR_FLIP_SUCTION', motion: 'rotate', axis: [0, 0, 1], sign: 1, inputRange: [0, 1], outputRange: [0, 180], transitionS: 0.6 }],
  linkages: [{ id: 'rob_grip_vial', label: '瓶夹爪', inputRange: [0, 1], transitionS: 0.15, members: [
    { node: 'A/ACTUATOR_GRIP_VIAL_L', axis: [1, 0, 0], sign: 1, outputRange: [13.45, 0], unitScale: 0.001 },
    { node: 'A/ACTUATOR_GRIP_VIAL_R', axis: [1, 0, 0], sign: -1, outputRange: [13.45, 0], unitScale: 0.001 },
  ] }],
  inventory: {
    rack: [{ kind: 'collector', node: 'ST_RACK/r/INV_RACK_COLLECTOR_1', items: [] }],
    staging: [{ area: 'staging-a', node: 'ST_x/INV_STAGING_A', items: [] }],
    magazines: [{ id: 'feed', node: 'ST_FEEDLIFT/f/INV_MAGAZINE_FEED_TEMPLATE' }],
  },
  tanks: [
    { id: 'tank1', index: 0, label: '展缸1', glbNode: 'ST_DEVELOP/t/TANK_1', liquidNode: null },
    { id: 'tank2', index: 1, label: '展缸2', glbNode: 'ST_DEVELOP/t/TANK_2', liquidNode: 'ST_DEVELOP/t/LIQUID_2' },
  ],
  realtime: {
    mechanisms: [
      { id: 'rob_flip_suction', label: '吸盘翻转', kind: 'cylinder', rigged: true },
      { id: 'col_bottle_locator', label: '定位气缸', station: 'staginga', kind: 'cylinder', rigged: false },
    ],
  },
}

test('rigged 轴可动、未 rigged 轴待装配', () => {
  const entries = classifySemantics(MANIFEST)
  const rail = entries.find((e) => e.id === 'axis:axis_11y')
  assert.equal(rail.category, 'movable')
  assert.deepEqual(rail.glbNodes, ['ST_RAIL/AXIS_AXIS_11Y/CARRIAGE'])
  assert.equal(rail.params.axisId, 'axis_11y')
  const sampling = entries.find((e) => e.id === 'axis:axis_1z')
  assert.equal(sampling.category, 'declared-only')
  assert.equal(sampling.glbNodes.length, 0)
})

test('机械臂整臂着色 + 关节逐条可调', () => {
  const entries = classifySemantics(MANIFEST)
  const body = entries.find((e) => e.id === 'robot:body')
  assert.equal(body.category, 'movable')
  assert.deepEqual(body.glbNodes, ['ST_ROBOT/CR5'])
  const j2 = entries.find((e) => e.id === 'joint:J2')
  assert.equal(j2.params.jointIndex, 1)
  assert.deepEqual(j2.params.limitDeg, [-359, 359])
})

test('执行器/联动/工具全部归为可动, 联动收齐全部成员节点', () => {
  const entries = classifySemantics(MANIFEST)
  assert.equal(entries.find((e) => e.id === 'actuator:rob_flip_suction').category, 'movable')
  const vial = entries.find((e) => e.id === 'linkage:rob_grip_vial')
  assert.equal(vial.glbNodes.length, 2)
  assert.equal(vial.params.members.length, 2)
  assert.equal(entries.find((e) => e.id === 'tool:TOOL_PLATE96').category, 'movable')
})

test('耗材三组归类为 consumable', () => {
  const entries = classifySemantics(MANIFEST)
  for (const id of ['consumable:rack', 'consumable:staging', 'consumable:magazines']) {
    const entry = entries.find((e) => e.id === id)
    assert.equal(entry.category, 'consumable', id)
    assert.ok(entry.glbNodes.length >= 1)
  }
  // 料仓条目覆盖的就是玻璃板本身(不是料仓结构件), 文案照实叫"玻璃板"
  assert.equal(entries.find((e) => e.id === 'consumable:magazines').label, '玻璃板(1 仓)')
})

test('液面停用(liquidNode null)= 待装配, 有 liquidNode = 可动', () => {
  const entries = classifySemantics(MANIFEST)
  assert.equal(entries.find((e) => e.id === 'tank:tank1').category, 'declared-only')
  assert.equal(entries.find((e) => e.id === 'tank:tank2').category, 'movable')
})

test('数据侧机构只收 data-only 条目(已有 actuator/linkage 的不重复)', () => {
  const entries = classifySemantics(MANIFEST)
  assert.equal(entries.find((e) => e.id === 'mech:rob_flip_suction'), undefined)
  const mech = entries.find((e) => e.id === 'mech:col_bottle_locator')
  assert.equal(mech.category, 'declared-only')
})

test('颜色表与分组覆盖全部用到的键', () => {
  const entries = classifySemantics(MANIFEST)
  for (const entry of entries) {
    assert.ok(SEMANTIC_COLORS[entry.category], `缺分类色: ${entry.category}`)
    assert.ok(CATEGORY_LABELS[entry.category], `缺分类名: ${entry.category}`)
    assert.ok(KIND_GROUPS.some((g) => g.kind === entry.kind), `缺分组: ${entry.kind}`)
  }
})

test('空 manifest 不炸', () => {
  assert.deepEqual(classifySemantics(null), [])
  assert.deepEqual(classifySemantics({}), [])
})

// -- 解析失败防回归(markAxisResolveFailures) --------------------------------

test('manifest 声明 rigged 但驱动层没解析到 -> 降级 declared-only + resolveFailed', () => {
  const entries = classifySemantics(MANIFEST)
  // 驱动层只解析到 axis_11y(模拟 .001 后缀事故: 3y/5z 解析失败)
  markAxisResolveFailures(entries, new Set(['axis_11y']))
  const ok = entries.find((e) => e.id === 'axis:axis_11y')
  assert.equal(ok.category, 'movable')
  assert.equal(ok.resolveFailed, undefined)
  // MANIFEST 里只有 axis_11y rigged, 其余本就是 declared-only, 不该被打 resolveFailed
  const dataOnly = entries.find((e) => e.id === 'axis:axis_1z')
  assert.equal(dataOnly.resolveFailed, undefined)
})

test('movable 轴不在已解析集 -> 徽章亮起且不再着色', () => {
  const manifest = {
    axes: [
      { id: 'axis_a', label: 'A', rigged: true, glbNode: 'ST_X/AXIS_A/CARRIAGE' },
      { id: 'axis_b', label: 'B', rigged: true, glbNode: 'ST_X/AXIS_B/CARRIAGE' },
    ],
  }
  const entries = markAxisResolveFailures(classifySemantics(manifest), new Set(['axis_a']))
  const bad = entries.find((e) => e.id === 'axis:axis_b')
  assert.equal(bad.category, 'declared-only')
  assert.equal(bad.resolveFailed, true)
  assert.equal(bad.glbNodes.length, 0)
  const good = entries.find((e) => e.id === 'axis:axis_a')
  assert.equal(good.category, 'movable')
})
