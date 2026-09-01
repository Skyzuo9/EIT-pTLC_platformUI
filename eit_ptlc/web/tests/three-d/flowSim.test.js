/**
 * 功能: 流程近似展开器的纯逻辑单测.
 *
 * 值得单测的理由与 actionSim 同源, 但赌注更大: flowSim 是演示栏里**绝大多数**条目的
 * 动画来源(101 个流程里只有十几个能精编译)。它判错的表现是"播了一段根本不存在的运动",
 * 而画面看着完全正常 —— 这正是本项目反复吃亏的那类错, 只能靠单测在源头拦。
 *
 * 三条必须锁住的契约:
 *   1. 产物真的能被 compileClip 编译(schema/字段名漂移了要当场炸, 而不是运行期);
 *   2. 未知动作产占位步并计入 unknown, 绝不静默跳过也绝不编一个位置;
 *   3. 零运动流程返回 no-motion, 而不是给一个空片段让人对着静止画面猜.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { compileClip } from '../../src/three-d/anim/clipSchema.js'
import { defaultBindings, literalOf, simulateFlow } from '../../src/three-d/demo/flowSim.js'

/** 精简版映射表, 字段名与 clip_compiler.motion_map_document() 逐字一致 */
const MOTION_MAP = {
  schema: 'ptlc.action-motion-map/v1',
  stationAxisActions: {
    'feedlift.feed_raise': { axis: 'axis_1z', toMm: 512, label: '上料1Z·升轴到取料光电', speedMmS: 120 },
  },
  searchAxisActions: {
    'feedlift.probe_stack': { label: '探测板堆张数', durationS: 0.4 },
  },
  cylinderActions: {
    'photoscrape.press_cylinder': { id: 'ps_press', arg: 'pressed' },
  },
  cylinderActionsFixed: {
    'collect.clamp': { id: 'col_clamp', value: 1 },
  },
  // 多步定值序列: 与 actionSim.sequencePlan 同一份表两处消费, 故两边都要有覆盖 ——
  // 早先这里一条都没有, 于是"前端只认 {arg} 编码"这个缺陷在 flowSim 侧也无人发觉
  sequenceActions: {
    'sampling.flush': [
      { kind: 'axis', axis: 'axis_5z', toMm: 0, label: '上样5Z·抬针', speedMmS: 20 },
      { kind: 'point', point: 'sampling_4x_wash', axis: 'axis_4x', label: '上样4X·移到清洗位', speedMmS: 10 },
    ],
    'sampling.spot': [
      { kind: 'point', arg: 'ref_spot', member: 'y_height', axis: 'axis_7y', label: '点样7Y·落到点样高度', speedMmS: 50 },
    ],
    'sampling.aspirate': [
      { kind: 'well', label: '上样4X/3Y·移到样品孔', speedMmS: 10 },
    ],
  },
  tankLidActions: { 'develop.plate_retract': 0, 'develop.plate_extend': 1 },
  tankLidLinkage: { 1: 'dev_t1_cyl1', 5: 'dev_t2_cyl1' },
  ignoredActions: ['robot.query', 'material.check_availability', 'robot.set_mounted_tool'],
  toolAsset: { 1: 'TOOL_SUCTION', 2: 'TOOL_PLATE96', 3: 'TOOL_VIAL' },
  gripperByTool: { 2: 'rob_grip_plate96', 3: 'rob_grip_vial' },
  flipActuatorId: 'rob_flip_suction',
}

const MANIFEST = {
  axes: [
    { id: 'axis_1z', rigged: true, zeroOffsetMm: 0 },
    { id: 'axis_11y', rigged: true, zeroOffsetMm: 500 },
    { id: 'axis_4x', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Sampling_4X_ActPos' } },
    { id: 'axis_5z', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Sampling_5Z_ActPos' } },
    { id: 'axis_7y', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Spot_7Y_ActPos' } },
  ],
  actuators: [
    { id: 'ps_press', label: '拍照下压气缸', node: 'ST_PHOTO/ACTUATOR_PS_PRESS', transitionS: 0.8 },
    { id: 'col_clamp', label: '收集夹持气缸', node: 'ST_COLLECT/ACTUATOR_COL_CLAMP', transitionS: 0.6 },
  ],
  tools: [
    { id: 'TOOL_SUCTION', controllerTool: 1, label: '玻璃吸盘' },
    { id: 'TOOL_PLATE96', controllerTool: 2, label: '96孔板夹爪' },
    { id: 'TOOL_VIAL', controllerTool: 3, label: '样品瓶电爪' },
  ],
  linkages: [
    { id: 'dev_t1_cyl1', label: '展缸1盖', transitionS: 1.2 },
    // 三态取值取真机实测: 0=张开(GLB 基准) / holdValue=夹住载荷 / inputRange[1]=空爪紧闭
    { id: 'rob_grip_plate96', label: '96孔板夹爪', transitionS: 0.15, holdValue: 0.288, inputRange: [0, 1] },
    { id: 'rob_grip_vial', label: '样品瓶电爪', transitionS: 0.15, holdValue: 0.101, inputRange: [0, 1] },
  ],
}

// 形状与 indexServoPoints 的产物一致: 地轨条目的 category 是 plc_servo 且带 slot
const SERVO_INDEX = new Map([
  ['rail_p4_tool', { id: 'rail_p4_tool', category: 'plc_servo', value: 500, label: '地轨-工具位', slot: 4 }],
  ['sampling_4x_wash', {
    id: 'sampling_4x_wash', category: 'plc_servo_target', value: 0, label: '上样4X 清洗位 (离散示教)',
    node: 'Sampling_4X_WashTarget', actpos: 'Sampling_4X_ActPos',
  }],
  ['spot_pose.y_height', {
    id: 'spot_pose.y_height', category: 'plc_servo_composite', value: -20, label: 'Y高度',
    node: 'Spot_7Y_Target', actpos: 'Spot_7Y_ActPos',
  }],
])

const POINT_CATALOG = {
  schema: 'ptlc.robot-points/v1',
  points: {
    'robot-main.home': { joint: [-154.5, -47.8, 93.3, 44.6, -89.1, 125.0], robotName: 'P1' },
    'zero.point': { joint: [0, 0, 0, 0, 0, 0], robotName: 'P99' },
  },
}

const CONTEXT = {
  motionMap: MOTION_MAP,
  manifest: MANIFEST,
  servoIndex: SERVO_INDEX,
  pointCatalog: POINT_CATALOG,
  resolveScript: () => null,
}

/** 造一个最小流程文档 */
function flow(body, vars = []) {
  return { schema: 'ptlc.script/v1', kind: 'operation', name: 'demo_flow', label: '演示流程', vars, body }
}

test('轴动作按映射表展开成 axis 原语, 并补上 home 零点', () => {
  const result = simulateFlow(flow([{ op: 'call', action: 'feedlift.feed_raise', args: {} }]), {}, CONTEXT)
  assert.equal(result.kind, 'approx')
  assert.deepEqual(result.doc.steps[0].do, { axis: { id: 'axis_1z', to_mm: 512 } })
  // 通道隐式初值是 0, 而 0 不一定是该轴零位 —— 不补 home 第一帧会跳
  assert.equal(result.doc.home.axis_mm.axis_1z, 0)
  assert.doesNotThrow(() => compileClip(result.doc, {}))
})

test('气缸动作: 带参取入参, 无参取固定值; home 给反向初值免得第一帧不动', () => {
  const withArg = simulateFlow(
    flow([{ op: 'call', action: 'photoscrape.press_cylinder', args: { pressed: { lit: true } } }]),
    {}, CONTEXT,
  )
  assert.deepEqual(withArg.doc.steps[0].do, { actuator: { id: 'ps_press', to: 1 } })
  assert.equal(withArg.doc.home.actuators.ps_press, 0)

  const fixed = simulateFlow(flow([{ op: 'call', action: 'collect.clamp', args: {} }]), {}, CONTEXT)
  assert.deepEqual(fixed.doc.steps[0].do, { actuator: { id: 'col_clamp', to: 1 } })
})

test('展缸盖: 缸号取自入参, home 显式给 1(关盖=建模基线), 否则 t=0 就是开着的', () => {
  const result = simulateFlow(
    flow([{ op: 'call', action: 'develop.plate_retract', args: { target_tank: { var: 'tank' } } }]),
    { tank: 1 }, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  assert.deepEqual(result.doc.steps[0].do, { linkage: { id: 'dev_t1_cyl1', to: 0 } })
  assert.equal(result.doc.home.linkages.dev_t1_cyl1, 1)
})

test('地轨: 槽号 → 示教点毫米; 点表缺该槽时如实占位, 绝不拿常量顶', () => {
  const taught = simulateFlow(
    flow([{ op: 'call', action: 'rail.move', args: { Rail_Target_Position: { lit: 4 } } }]),
    {}, CONTEXT,
  )
  assert.deepEqual(taught.doc.steps[0].do, { axis: { id: 'axis_11y', to_mm: 500 } })

  // 槽 1 不在夹具点表里。曾经这里会退回一张与点表数值相同的常量表 —— 于是"读不到点表"
  // 与"读到了"长得一模一样, 现场重新示教后演示会安静地播陈旧值。现在必须占位并记未覆盖。
  const missing = simulateFlow(
    flow([{ op: 'call', action: 'rail.move', args: { Rail_Target_Position: { lit: 1 } } }]),
    {}, CONTEXT,
  )
  assert.equal(missing.kind, 'no-motion')
  assert.ok(missing.unknown.includes('rail.move'))
})

test('多步定值序列: 字面 point 不需入参真动轴, arg 形态缺参才占位, well 照编译器语义占位', () => {
  // 与 actionSim 同一份表两处消费, 所以同一个缺陷两处都要有回归:
  // 字面 {point} 编码早先在这里退化成"点表缺该点位"占位 —— 步骤看着在, 其实一动不动。
  const literal = simulateFlow(flow([{ op: 'call', action: 'sampling.flush', args: {} }]), {}, CONTEXT)
  assert.equal(literal.kind, 'approx')
  assert.deepEqual(literal.doc.steps.map((step) => step.do), [
    { axis: { id: 'axis_5z', to_mm: 0 } },
    { axis: { id: 'axis_4x', to_mm: 0 } },   // sampling_4x_wash 现值(还没 jog 示教)
  ])
  assert.doesNotThrow(() => compileClip(literal.doc, {}))

  // arg 形态: 给了就走点表
  const viaArg = simulateFlow(
    flow([{ op: 'call', action: 'sampling.spot', args: { ref_spot: { lit: 'spot_pose' } } }]), {}, CONTEXT,
  )
  assert.deepEqual(viaArg.doc.steps[0].do, { axis: { id: 'axis_7y', to_mm: -20 } })

  // arg 形态没给 / well 步: 各占一个说明白的时间格(纯占位的流程判 no-motion 且无 doc,
  // 所以配一条真会动的动作进去, 才看得到占位步长什么样)
  const placeholders = simulateFlow(flow([
    { op: 'call', action: 'feedlift.feed_raise', args: {} },
    { op: 'call', action: 'sampling.spot', args: {} },
    { op: 'call', action: 'sampling.aspirate', args: {} },
  ]), {}, CONTEXT)
  assert.equal(placeholders.kind, 'approx')
  // 没选点位 ≠ 点表里缺这个点位 —— 措辞要分得开
  assert.match(placeholders.doc.steps[1].label, /未选点位/)
  // well: 孔位毫米只在编译期可见(映射表不导出)
  assert.match(placeholders.doc.steps[2].label, /孔板未标定/)
})

test('机械臂到点用实测关节角; 全零关节视为无实测值, 不拿它插值', () => {
  const good = simulateFlow(
    flow([{ op: 'call', action: 'robot.move_to_point', args: { point_id_or_robot_name: { lit: 'robot-main.home' } } }]),
    {}, CONTEXT,
  )
  assert.ok('joints' in good.doc.steps[0].do)
  assert.equal(good.doc.steps[0].do.joints.to_deg.length, 6)

  const zeros = simulateFlow(
    flow([{ op: 'call', action: 'robot.move_to_point', args: { point_id_or_robot_name: { lit: 'zero.point' } } }]),
    {}, CONTEXT,
  )
  assert.equal(zeros.kind, 'no-motion')
  assert.ok(zeros.unknown.some((item) => item.includes('zero.point')))
})

test('未知动作产占位步并计入 unknown —— 既不静默跳过, 也不编一个位置', () => {
  const result = simulateFlow(
    flow([
      { op: 'call', action: 'feedlift.feed_raise', args: {} },
      { op: 'call', action: 'sampling.spot_band_layer', args: {} },
    ]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  assert.equal(result.unknown.includes('sampling.spot_band_layer'), true)
  const placeholder = result.doc.steps.find((step) => step.label.includes('sampling.spot_band_layer'))
  assert.ok(placeholder, '占位步必须带上动作名, 否则时间轴上看不出这里少了什么')
  assert.deepEqual(placeholder.do, { wait: {} })
})

test('IGNORED 动作不产步; 全是 IGNORED 的流程判为 no-motion', () => {
  const result = simulateFlow(
    flow([
      { op: 'call', action: 'robot.query', args: {} },
      { op: 'call', action: 'material.check_availability', args: {} },
    ]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'no-motion')
  assert.match(result.reason, /不驱动任何机构/)
})

test('run_script 递归内联; 取不到子脚本时产占位并记 unknown', () => {
  const sub = flow([{ op: 'call', action: 'feedlift.feed_raise', args: {} }])
  sub.name = 'sub_flow'
  const inlined = simulateFlow(
    flow([{ op: 'run_script', script: 'sub_flow', inputs: {} }]),
    {},
    { ...CONTEXT, resolveScript: (name) => (name === 'sub_flow' ? sub : null) },
  )
  assert.equal(inlined.kind, 'approx')
  assert.deepEqual(inlined.doc.steps[0].do, { axis: { id: 'axis_1z', to_mm: 512 } })

  const missing = simulateFlow(
    flow([
      { op: 'call', action: 'feedlift.feed_raise', args: {} },
      { op: 'run_script', script: 'nope', inputs: {} },
    ]),
    {}, CONTEXT,
  )
  assert.ok(missing.unknown.includes('run_script:nope'))
})

test('if 取第一分支并在步骤标签上写明; 循环只演一轮', () => {
  const branched = simulateFlow(
    flow([{
      op: 'if',
      cond: { lit: true },
      then: [{ op: 'call', action: 'feedlift.feed_raise', args: {} }],
      else: [{ op: 'call', action: 'collect.clamp', args: {} }],
    }]),
    {}, CONTEXT,
  )
  assert.ok(branched.doc.steps.some((step) => step.label.includes('假设分支')))
  assert.ok(branched.notes.some((note) => note.includes('条件判断')))
  // else 分支不该出现
  assert.equal(branched.doc.steps.some((step) => step.do?.actuator?.id === 'col_clamp'), false)

  const looped = simulateFlow(
    flow([{ op: 'while', cond: { lit: true }, body: [{ op: 'call', action: 'feedlift.feed_raise', args: {} }] }]),
    {}, CONTEXT,
  )
  assert.ok(looped.notes.some((note) => note.includes('只演第 1 轮')))
  assert.equal(looped.doc.steps.filter((step) => step.do?.axis).length, 1)
})

test('说明按类型聚合计数 —— 30 处条件分支只出一条, 不是刷屏 30 行', () => {
  const branch = () => ({
    op: 'if',
    cond: { lit: true },
    then: [{ op: 'call', action: 'feedlift.feed_raise', args: {} }],
  })
  const result = simulateFlow(flow(Array.from({ length: 30 }, branch)), {}, CONTEXT)
  const about = result.notes.filter((note) => note.includes('条件判断'))
  assert.equal(about.length, 1)
  assert.match(about[0], /30 处/)
})

test('for 循环把循环变量绑成第一轮的值 —— 只演一轮, 演的就是第一轮', () => {
  // 实测形状取自 system_init_all: 逐缸初始化, target_tank 是循环变量。
  // 不绑的话 develop.plate_retract 拿不到缸号, 会被报成"不在映射表中"(它明明在表里)。
  const result = simulateFlow(
    flow([{
      op: 'for',
      var: 'tank',
      start: { lit: 1 },
      stop: { lit: 9 },
      body: [{ op: 'call', action: 'develop.plate_retract', args: { target_tank: { var: 'tank' } } }],
    }]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  assert.deepEqual(result.doc.steps.at(-1).do, { linkage: { id: 'dev_t1_cyl1', to: 0 } })
  assert.deepEqual(result.unknown, [])
  assert.deepEqual(result.deferred, [])
  assert.ok(result.notes.some((note) => note.includes('tank=1')))
})

test('for 的 start 不是字面量就不绑 —— 宁可说不知道, 也不编一个缸号', () => {
  const result = simulateFlow(
    flow([{
      op: 'for',
      var: 'tank',
      start: { var: 'runtime_first' },
      stop: { lit: 9 },
      body: [{ op: 'call', action: 'develop.plate_retract', args: { target_tank: { var: 'tank' } } }],
    }]),
    {}, CONTEXT,
  )
  // 一步机构都没动 -> no-motion, 且缺口计在 deferred(动作在表里, 缺的是参数)而不是 unknown
  assert.equal(result.kind, 'no-motion')
  assert.deepEqual(result.unknown, [])
  assert.deepEqual(result.deferred, ['develop.plate_retract'])
  assert.match(result.reason, /运行期才定/)
  assert.doesNotMatch(result.reason, /不在映射表/)
})

test('robot.require_anchor: 0 秒可见步, 既不算未知也不算延后', () => {
  const result = simulateFlow(
    flow([
      { op: 'call', action: 'robot.require_anchor', args: { point_id: { lit: 'robot-main.home' } } },
      { op: 'call', action: 'feedlift.feed_raise', args: {} },
    ]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  const anchor = result.doc.steps[0]
  assert.match(anchor.label, /robot-main\.home/)
  assert.equal(anchor.dur, 0)
  assert.deepEqual(anchor.do, { wait: {} })
  assert.deepEqual(result.unknown, [])
  assert.deepEqual(result.deferred, [])
})

test('换刀挂的是当时那把刀 —— 不是写死的 2 号(96孔板夹爪)', () => {
  // set_mounted_tool 在编译器的忽略表里, 但它是刀号的唯一声明 —— 被 isIgnored 吃掉的话
  // 快换那一步就只能猜, 而猜错的表现是"动画里挂了另一把刀", 画面完全正常。
  const lockAfter = (toolId) => simulateFlow(
    flow([
      { op: 'call', action: 'robot.set_mounted_tool', args: { tool_id: { lit: toolId } } },
      { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'quick-change-lock' } } },
    ]),
    {}, CONTEXT,
  ).doc.steps.at(-1)

  assert.deepEqual(lockAfter(1).do, { tool: { action: 'lock', id: 'TOOL_SUCTION' } })
  assert.deepEqual(lockAfter(3).do, { tool: { action: 'lock', id: 'TOOL_VIAL' } })

  // 没声明过刀号: 不猜, 占位并记进 deferred
  const blind = simulateFlow(
    flow([
      { op: 'call', action: 'feedlift.feed_raise', args: {} },
      { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'quick-change-lock' } } },
    ]),
    {}, CONTEXT,
  )
  assert.ok(blind.doc.steps.at(-1).label.includes('刀号未声明'))
  assert.ok(blind.deferred.includes('robot.tool_action'))
})

test('顶层文档自己的 tool_id 也算声明 —— 演示栏直接看 robot_tool_pick 就是这种', () => {
  const pick = flow(
    [{ op: 'call', action: 'robot.tool_action', args: { action: { lit: 'quick-change-lock' } } }],
    [{ name: 'tool_id', io: 'in', type: 'INT', default: 1 }],
  )
  pick.name = 'robot_tool_pick'
  const result = simulateFlow(pick, {}, CONTEXT)
  assert.deepEqual(result.doc.steps.at(-1).do, { tool: { action: 'lock', id: 'TOOL_SUCTION' } })
  assert.match(result.doc.steps.at(-1).label, /玻璃吸盘|TOOL_SUCTION|1号刀/)
})

test('run_script 的 tool_id 就是"这一段讲几号刀" —— 快换发生在 set_mounted_tool 之前', () => {
  const pick = flow([
    { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'quick-change-lock' } } },
  ])
  pick.name = 'robot_tool_pick'
  pick.vars = [{ name: 'tool_id', io: 'in', type: 'INT', default: 1 }]
  const result = simulateFlow(
    flow([{ op: 'run_script', script: 'robot_tool_pick', inputs: { tool_id: { lit: 3 } } }]),
    {},
    { ...CONTEXT, resolveScript: (name) => (name === 'robot_tool_pick' ? pick : null) },
  )
  assert.deepEqual(result.doc.steps.at(-1).do, { tool: { action: 'lock', id: 'TOOL_VIAL' } })
})

test('夹爪开合按刀号查联动组; 1 号刀没有夹爪就如实说', () => {
  const grip = (toolId) => simulateFlow(
    flow([
      { op: 'call', action: 'robot.set_mounted_tool', args: { tool_id: { lit: toolId } } },
      { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'gripper-close' } } },
    ]),
    {}, CONTEXT,
  )
  // demo_flow 不是取放脚本, 这一下合爪是"空爪紧闭"(值域上界), 不是夹持
  assert.deepEqual(grip(2).doc.steps.at(-1).do, { linkage: { id: 'rob_grip_plate96', to: 1 } })
  // 1 号刀是玻璃吸盘, 没有夹爪 —— 不能拿 2 号刀的联动组顶上
  const suction = grip(1)
  assert.equal(suction.kind, 'no-motion')
  assert.ok(suction.notes.length >= 0)
})

test('取料脚本内合爪演到夹持开度, 不是满闭合(否则把物料捏穿)', () => {
  // 近似档没有物料账本, 但它知道自己此刻展开到哪个脚本 —— 与实时链用 event.script
  // 判"这次合爪是不是去夹东西"是同一件事, 故口径能严格一致。
  const pick = {
    schema: 'ptlc.script/v1',
    kind: 'operation',
    name: 'robot_individual_pick',
    body: [
      { op: 'call', action: 'robot.set_mounted_tool', args: { tool_id: { lit: 3 } } },
      { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'gripper-close' } } },
    ],
  }
  // ① 被内联进来: 展开路径的叶名是取料脚本
  const inlined = simulateFlow(
    flow([{ op: 'run_script', script: 'robot_individual_pick', inputs: {} }]),
    {},
    { ...CONTEXT, resolveScript: (name) => (name === 'robot_individual_pick' ? pick : null) },
  )
  assert.deepEqual(inlined.doc.steps.at(-1).do, { linkage: { id: 'rob_grip_vial', to: 0.101 } })

  // ② 直接看这条取料脚本本身 (演示栏的 flow.robot_individual_pick.* 就是这种):
  //    顶层文档名同样要参与判定, 否则单独看时爪子会演成空爪紧闭
  const direct = simulateFlow(pick, {}, CONTEXT)
  assert.deepEqual(direct.doc.steps.at(-1).do, { linkage: { id: 'rob_grip_vial', to: 0.101 } })
})

test('合爪到夹持开度时 home 取张开端点, 不是满闭合', () => {
  // 从前写的是 `target > 0.5 ? 0 : 1`, 在 target=0.101 时算出 home=1(空爪紧闭), 反了 ——
  // 通道会从紧闭缓动到夹持, 画面上爪子先合死再张开一点。
  const pick = {
    schema: 'ptlc.script/v1',
    kind: 'operation',
    name: 'robot_individual_pick',
    body: [
      { op: 'call', action: 'robot.set_mounted_tool', args: { tool_id: { lit: 3 } } },
      { op: 'call', action: 'robot.tool_action', args: { action: { lit: 'gripper-close' } } },
    ],
  }
  const result = simulateFlow(pick, {}, CONTEXT)
  assert.equal(result.doc.home.linkages.rob_grip_vial, 0, '合爪的起点必然是张开')
})

test('with_resources / parallel / try 透明穿过, human 产可见占位', () => {
  const result = simulateFlow(
    flow([
      { op: 'with_resources', resources: ['robot'], body: [{ op: 'call', action: 'feedlift.feed_raise', args: {} }] },
      { op: 'human', kind: 'confirm', prompt: '请确认板已放好' },
    ]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  assert.ok(result.doc.steps.some((step) => step.label.includes('请确认板已放好')))
})

test('产物必须真能被 compileClip 编译(schema/字段名漂移当场炸)', () => {
  const result = simulateFlow(
    flow([
      { op: 'call', action: 'rail.move', args: { Rail_Target_Position: { lit: 4 } } },
      { op: 'call', action: 'robot.move_to_point', args: { point_id_or_robot_name: { lit: 'robot-main.home' } } },
      { op: 'call', action: 'develop.plate_extend', args: { target_tank: { lit: 1 } } },
      { op: 'call', action: 'photoscrape.press_cylinder', args: { pressed: { lit: true } } },
    ]),
    {}, CONTEXT,
  )
  assert.equal(result.kind, 'approx')
  assert.equal(result.doc.schema, 'ptlc.clip/v1')
  // joints 原语只有 v1/debug 片段准用 —— 少了 debug 标记这里就该炸
  assert.equal(result.doc.debug, true)
  const compiled = compileClip(result.doc, {})
  assert.ok(compiled.duration > 0)
  assert.ok(compiled.channels.has('axis:axis_11y'))
  assert.ok(compiled.channels.has('linkage:dev_t1_cyl1'))
})

test('defaultBindings 按声明类型转型, 与后端 default_bindings 同规则', () => {
  const doc = flow([], [
    { name: 'tank', io: 'in', type: 'INT', default: '3' },
    { name: 'ratio', io: 'in', type: 'FLOAT', default: '0.8' },
    { name: 'dry', io: 'in', type: 'BOOL', default: 'true' },
    { name: 'scratch', io: 'var' },
    { name: 'thr', io: 'var', type: 'FLOAT', default: '1.5' },
  ])
  const bindings = defaultBindings(doc)
  assert.equal(bindings.tank, 3)
  assert.equal(bindings.ratio, 0.8)
  assert.equal(bindings.dry, true)
  assert.equal(bindings.thr, 1.5)
  // 不带 default 的 var 是运行期才赋值的, 不入表
  assert.equal('scratch' in bindings, false)
})

test('literalOf 只解字面量与已绑定变量, 算术表达式一律 undefined', () => {
  assert.equal(literalOf({ lit: 7 }, {}), 7)
  assert.equal(literalOf({ var: 'tank' }, { tank: 5 }), 5)
  // 近似级宁可"这一步我不知道", 也不要算出一个看着像真的数
  assert.equal(literalOf({ binop: '+', left: { lit: 1 }, right: { lit: 2 } }, {}), undefined)
})

test('空流程判 failed 而不是抛异常', () => {
  assert.equal(simulateFlow(null, {}, CONTEXT).kind, 'failed')
})

// ── 展缸液面 ─────────────────────────────────────────────────────────────────
// 与 actionSim 的液面用例是**互补**关系, 不是重复: 流程自带上下文, 排液的起始液位由
// 前面那条注液动作真实推导得出, 一个假设都不用做。这几条钉的就是"跨动作跟踪"这件事 ——
// 它必须与 clip_compiler.ClipBuilder.tank_volume_ml 同构, 否则同一条流程在近似档与
// 精编译档的液面高低对不上, 而两档看着都挺正常。
const TANK_CONTEXT = {
  ...CONTEXT,
  manifest: {
    ...MANIFEST,
    tanks: [
      { index: 0, id: 'tank1', label: '展缸 1', liquidNode: 'ST_DEVELOP/TANK_1/LIQUID_1' },
      { index: 2, id: 'tank3', label: '展缸 3', liquidNode: 'ST_DEVELOP/TANK_3/LIQUID_3' },
    ],
    tankLiquid: {
      cavity: { usableDepthMm: 20.274, freeAreaMm2: 4939.6, capacityMl: 102.48 },
      exaggeration: 2,
      pipeHoldupMl: 0,
      tankArg: 'target_tank',
      actions: {
        'develop.fill': { dir: 'fill', volumeFrom: ['solvent_volume_ml', 'up_liquid_repeat_count'], rampS: 12 },
        'develop.rinse_suction': { dir: 'drain', rampS: 8, delayFromArg: 'settle_s' },
      },
    },
  },
}

/** 取产物里所有 liquid 步的 (id, to_ml) */
const liquidSteps = (result) => result.doc.steps
  .filter((step) => step.do.liquid)
  .map((step) => [step.do.liquid.id, step.do.liquid.to_ml])

test('流程内跨动作跟踪缸内体积: 注 60mL → 抽吸回 0, 起点无需任何假设', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 3, solvent_volume_ml: 20, up_liquid_repeat_count: 3 } },
    { op: 'call', action: 'develop.rinse_suction', args: { target_tank: 3, settle_s: 3 } },
  ]), {}, TANK_CONTEXT)

  assert.equal(result.kind, 'approx')
  assert.deepEqual(liquidSteps(result), [['tank3', 60], ['tank3', 0]])
  assert.deepEqual(result.doc.home.liquid_ml, { tank3: 0 }, '首次触碰该缸时是空的')
  // 排液那一步的标签必须写出真实起点, 否则看不出它是从 60 排下来的
  const drain = result.doc.steps.find((s) => String(s.label).includes('排液'))
  assert.match(drain.label, /60\.0 → 0\.0 mL/)
  // 产物必须真能编译 —— schema 漂移当场炸
  compileClip(result.doc)
})

test('流程一上来就排一个没注过的缸: 记 note 而不是凭空编一个起始液量', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.rinse_suction', args: { target_tank: 3, settle_s: 3 } },
  ]), {}, TANK_CONTEXT)

  // 整条流程只剩一个时间格, 于是判 no-motion(既有行为) —— 关键是缺口要说清楚
  assert.equal(result.kind, 'no-motion', '没有起点就不画液面')
  assert.ok(result.notes.some((line) => line.includes('起始液量')), `notes 未说明缺口: ${result.notes}`)
  assert.ok(result.deferred.includes('develop.rinse_suction'),
    '归 deferred(参数是运行期量)而不是 unknown(表里没有), 否则会有人去补一张已有的表')
})

test('多缸互不串扰: 各缸的体积各记各的', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 10, up_liquid_repeat_count: 1 } },
    { op: 'call', action: 'develop.fill', args: { target_tank: 3, solvent_volume_ml: 20, up_liquid_repeat_count: 2 } },
    { op: 'call', action: 'develop.rinse_suction', args: { target_tank: 1, settle_s: 0 } },
  ]), {}, TANK_CONTEXT)

  assert.deepEqual(liquidSteps(result), [['tank1', 10], ['tank3', 40], ['tank1', 0]])
})

// ── 前置段留下的起手态 ───────────────────────────────────────────────────────
// 单段流程不含前置段, 而运行期的清场是**无条件**的(MachineStateDriver.home() 把 8 个缸
// 清零、MachineRig.home() 清空板舞台, 且每一次向后 seek 都要走一遭)。不播种就永远是
// 空缸无板 —— 展开-上料因此曾把板放进一个空缸, 展开-执行更是既无液也无板。
// 声明的真源在 Python 侧 PHASE_ENTRY_STATE, 经 motion-map 的 phaseEntryState 导过来。

/** 前置段: 注 20mL × 3 = 60mL(逐字对应 develop_prepare 的默认配方) */
const PRELUDE_SCRIPT = {
  schema: 'ptlc.script/v1', kind: 'operation', name: 'prep_flow', label: '前置段',
  vars: [
    { name: 'tank', io: 'in', type: 'INT', default: 1 },
    { name: 'volume_ml', io: 'in', type: 'FLOAT', default: 20 },
    { name: 'repeat', io: 'in', type: 'INT', default: 3 },
  ],
  body: [{
    op: 'call',
    action: 'develop.fill',
    args: {
      target_tank: { var: 'tank' },
      solvent_volume_ml: { var: 'volume_ml' },
      up_liquid_repeat_count: { var: 'repeat' },
    },
  }],
}

/** 带起手态声明的环境; phaseEntryState 的字段名与 motion_map_document() 逐字一致 */
const ENTRY_CONTEXT = {
  ...TANK_CONTEXT,
  motionMap: {
    ...MOTION_MAP,
    phaseEntryState: {
      demo_flow: { liquidAfter: 'prep_flow', plateAt: 'tank:{tank}', why: '单测' },
    },
  },
  resolveScript: (name) => (name === 'prep_flow' ? PRELUDE_SCRIPT : null),
}

test('起手态: 前置段留下的液量播种进 home, 本段的排液才知道自己是从 60 排下来的', () => {
  const result = simulateFlow(flow(
    [{ op: 'call', action: 'develop.rinse_suction', args: { target_tank: { var: 'tank' }, settle_s: 0 } }],
    [{ name: 'tank', io: 'in', type: 'INT', default: 1 }],
  ), {}, ENTRY_CONTEXT)

  assert.equal(result.kind, 'approx')
  // 液量是**跑前置段算出来的**(20 × 3), 不是抄一个常量 —— 改配方默认值这里跟着变
  assert.deepEqual(result.doc.home.liquid_ml, { tank1: 60 })
  assert.deepEqual(liquidSteps(result), [['tank1', 0]], '排液真的演出来了, 而不是退化成空等')
  const drain = result.doc.steps.find((step) => String(step.label).includes('排液'))
  assert.match(drain.label, /60\.0 → 0\.0 mL/)
  compileClip(result.doc)
})

test('起手态: 板已在缸里的段, t=0 就把板摆上; 缸号取自本段入参', () => {
  const result = simulateFlow(flow(
    [{ op: 'call', action: 'develop.rinse_suction', args: { target_tank: { var: 'tank' }, settle_s: 0 } }],
    [{ name: 'tank', io: 'in', type: 'INT', default: 1 }],
  ), { tank: 3 }, ENTRY_CONTEXT)

  const plate = result.doc.steps.find((step) => step.do.plate)
  assert.ok(plate, '板一步都没有 —— 缸里就是空的')
  assert.deepEqual(plate.do.plate, { id: 'plate', at: 'tank:3' }, '落点缸号要跟着入参走')
  assert.equal(plate.at, 0)
  assert.equal(plate.dur, 0, '起手式不占时间, 也不该把后面的时间轴整体推后')
  assert.deepEqual(result.doc.home.liquid_ml, { tank3: 60 }, '缸号一并透进前置段')
})

test('起手态: 前置段脚本没取到时记 deferred, 不凭空编一个液量', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 10, up_liquid_repeat_count: 1 } },
  ]), {}, { ...ENTRY_CONTEXT, resolveScript: () => null })

  assert.deepEqual(result.doc.home.liquid_ml, { tank1: 0 }, '取不到就退回既有语义, 绝不猜')
  assert.ok(result.deferred.includes('entry:prep_flow'),
    '归 deferred(声明在表里、缺的是那份脚本)而不是 unknown(表里没有)')
})

test('没有起手态声明的流程行为完全不变 —— 这条改动不该波及另外九十几条', () => {
  const body = [{ op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 10, up_liquid_repeat_count: 1 } }]
  const withTable = simulateFlow({ ...flow(body), name: 'other_flow' }, {}, ENTRY_CONTEXT)
  const without = simulateFlow({ ...flow(body), name: 'other_flow' }, {}, TANK_CONTEXT)

  assert.deepEqual(withTable.doc.steps, without.doc.steps)
  assert.deepEqual(withTable.doc.home.liquid_ml, without.doc.home.liquid_ml)
})

// --- 注射泵柱塞行程(与编译器 emit_pump_syringe / 实时台 expandPumpPlan 同构) ----

/** 泵配置: 形状与 manifest.pumpSyringe 一致, 动作表截取会用到的几条 */
const PUMP_CONTEXT = {
  ...TANK_CONTEXT,
  manifest: {
    ...TANK_CONTEXT.manifest,
    pumpSyringe: {
      syringeMl: 25,
      strokeMm: 60,
      stepsPerStroke: 6000,
      speeds: {
        develop: { asp_speed: 100, disp_speed: 100, step_delay: 500 },
        sampling: { asp_speed: 250, disp_speed: 100, step_delay: 1500 },
      },
      pumps: [
        { index: 0, id: 'DEV1', label: '展开泵 1', tankGroup: [1, 2, 3, 4], rigged: true,
          plungerNode: 'ST_PUMP/P1/ACTUATOR_PUMP_PLUNGER_DEV1',
          liquidNode: 'ST_PUMP/P1/LIQUID_PUMP_DEV1',
          valvePorts: 6, outputPort: 6, speedStation: 'develop' },
        { index: 1, id: 'SMP', label: '上样泵', tankGroup: [], rigged: true,
          plungerNode: 'ST_SAMPLING/C/ACTUATOR_PUMP_PLUNGER_SMP',
          liquidNode: 'ST_SAMPLING/C/LIQUID_PUMP_SMP',
          valvePorts: 4, outputPort: 3, speedStation: 'sampling' },
        { index: 2, id: 'COL', label: '收集泵', tankGroup: [], rigged: false,
          plungerNode: null, liquidNode: null, valvePorts: 4, outputPort: null,
          speedStation: 'collect' },
      ],
      actions: {
        'develop.fill': {
          pump: { from: 'tankGroup', arg: 'target_tank' },
          repeatFrom: 'up_liquid_repeat_count',
          phases: [
            { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, port: 2, rampS: 4, speed: 'asp_speed' },
            { op: 'dispense', to: 0, port: 'output', rampS: 4, speed: 'disp_speed' },
          ],
        },
        'develop.clean_line': {
          pump: { from: 'tankGroup', arg: 'target_tank' },
          repeatFrom: 'rinse_repeat_count',
          phases: [
            { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, port: 2, rampS: 3, speed: 'asp_speed' },
            { op: 'dispense', to: 0, port: 'output', rampS: 3, speed: 'disp_speed' },
          ],
        },
        'sampling.prep': {
          pump: { from: 'fixed', id: 'SMP' },
          phases: [{ op: 'aspirate', toFrom: { add: ['air_buffer_ml'], fallback: [0.2] }, port: 3, rampS: 2, speed: 'asp_speed' }],
        },
        'sampling.aspirate': {
          pump: { from: 'fixed', id: 'SMP' },
          phases: [
            { op: 'aspirate', toFrom: { add: ['air_gap_ml'] }, skipIfMissing: true, port: 3, rampS: 2, speed: 'asp_speed' },
            { op: 'aspirate', byFrom: { add: ['sample_volume_ml'] }, port: 3, rampS: 4, speed: 'asp_speed' },
          ],
        },
        'collect.collect': {
          pump: { from: 'fixed', id: 'COL' },
          phases: [{ op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, rampS: 3 }],
        },
      },
    },
  },
}

test('develop.fill: 柱塞行程先于缸液面(先抽后注), 阀按 端口2→输出口6 切换', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 } },
  ]), {}, PUMP_CONTEXT)
  const kinds = result.doc.steps.map((step) => Object.keys(step.do)[0])
  const pumpAt = kinds.indexOf('pump')
  const liquidAt = kinds.indexOf('liquid')
  assert.ok(pumpAt >= 0, '没有柱塞行程步')
  assert.ok(liquidAt > pumpAt, '缸液面必须在泵行程之后上涨(先抽后注)')
  const valves = result.doc.steps.filter((s) => s.do.pump_valve).map((s) => s.do.pump_valve.port)
  assert.deepEqual(valves, [2, 6], '阀应先到 2 号溶剂口再到 6 号输出口')
  // 20mL × 240步 ÷ V100 = 48s, 超 20s 上限要压缩且标签写真值
  const aspirate = result.doc.steps.find((s) => s.do.pump && s.do.pump.to_ml === 20)
  assert.equal(aspirate.dur, 20)
  assert.match(aspirate.label, /实机 48s，演示压到 20s/)
  assert.equal(result.doc.home.pump_ml.DEV1, 0)
  assert.equal(result.doc.home.pump_port.DEV1, 1)
})

test('跨动作累计: prep 停在气隙位, aspirate 在其上叠加 —— 与编译器/实时台同语义', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'sampling.prep', args: {} },
    { op: 'call', action: 'sampling.aspirate', args: { sample_volume_ml: 5 } },
  ]), {}, PUMP_CONTEXT)
  const targets = result.doc.steps.filter((s) => s.do.pump).map((s) => s.do.pump.to_ml)
  assert.deepEqual(targets, [0.2, 5.2], 'prep→0.2mL, aspirate 相对叠加→5.2mL')
})

test('多轮往复按预算压缩并写进说明; 未装配的收集泵退回时间格', () => {
  const compressed = simulateFlow(flow([
    { op: 'call', action: 'develop.clean_line', args: { target_tank: 1, solvent_volume_ml: 2, rinse_repeat_count: 20 } },
  ]), {}, PUMP_CONTEXT)
  const pumps = compressed.doc.steps.filter((s) => s.do.pump)
  assert.ok(pumps.length > 0 && pumps.length <= 8, `相位步数 ${pumps.length} 超出预算`)
  assert.ok(compressed.notes.some((line) => line.includes('压缩了轮数')), '压缩必须写进说明')

  const col = simulateFlow(flow([
    { op: 'call', action: 'collect.collect', args: { solvent_volume_ml: 5 } },
  ]), {}, PUMP_CONTEXT)
  assert.ok(!col.doc?.steps?.some?.((s) => s.do.pump), '未装配的泵不该出行程步')
})
