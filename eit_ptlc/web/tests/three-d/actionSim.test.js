/**
 * 功能: 动作模拟规划器的纯逻辑单测.
 *
 * 值得单测的理由: planSimulation 决定演示子页"哪些动作能播", 判错会让用户拿一个
 * 播不动/播错轴的模拟去怀疑标定; 伪片段必须真的能被 compileClip 编译 —— 两个
 * 模块的契约(schema/字段名)一旦漂移, 运行时才炸就晚了.
 *
 * ⚠ 点表夹具必须是 **GET /api/points 的真实响应形状**(id / category / actpos / 复合
 * members), 不许照 config/points/plc/*.yaml 手写。上一版夹具正是照 YAML 写的 `key:`,
 * 于是"索引匹配了错误的字段名"这个根因缺陷在全绿的单测下活了下来 —— 前端一个 PLC
 * 示教点都解析不到, 而地轨恰好有常量兜底顶着, 缺陷被伪装成正常。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'
import { indexServoPoints, jointsOfPoint, planSimulation, velocityMaxOf } from '../../src/three-d/demo/actionSim.js'

/** GET /api/points 的响应片段(逐字取自现役后端, 只删了与本测无关的字段) */
const POINTS = {
  robot: {
    label: '机器人点位',
    groups: [{
      points: [{
        category: 'robot', id: 'robot-main.home', robot_name: 'P1', pose: [1, 2, 3, 4, 5, 6],
      }],
    }],
  },
  plc_servo: {
    label: 'PLC 伺服',
    groups: [
      {
        label: '上下料位',
        points: [{
          category: 'plc_servo_target', id: 'feedlift_1z_search_high', label: 'FeedLift 1Z 光电搜索上界',
          node: 'FeedLift_1Z_SearchHighTarget', actpos: 'FeedLift_1Z_ActPos', value: 512.0, pending: false,
        }],
      },
      {
        label: '上样伺服',
        points: [
          // pending=true 只表示"PLC 侧 flat 节点待建, 不能下发"; 值是 2026-08-05 从在线 PLC
          // 实读补上的真值, 拿来演是对的 —— 与 clip_compiler.load_servo_points 一致
          {
            category: 'plc_servo_target', id: 'sample_5z', label: '上样5Z 升降',
            node: 'Sampling_5Z_Target', actpos: 'Sampling_5Z_ActPos', value: 45.0,
            hmi_node: 'HMI_上样轴5Z轴', hmi_slot: 1, pending: true,
          },
          {
            category: 'plc_servo_target', id: 'sample_5z_dip', label: '上样5Z 吸样下探深度',
            node: 'Sampling_5Z_Target', actpos: 'Sampling_5Z_ActPos', value: 46.5,
            hmi_node: 'HMI_上样轴5Z轴', hmi_slot: 2, pending: true,
          },
          {
            // 清洗位: flat 节点 0624 已下载(pending 已清), 但**还没 jog 示教**, 值仍是 0.0 占位
            category: 'plc_servo_target', id: 'sampling_4x_wash', label: '上样4X 清洗位 (离散示教)',
            node: 'Sampling_4X_WashTarget', actpos: 'Sampling_4X_ActPos', value: 0.0,
            hmi_node: 'HMI_上样轴4X轴', hmi_slot: 9, pending: false,
          },
        ],
      },
      {
        label: '点样工位',
        points: [{
          category: 'plc_servo_composite', id: 'spot_pose', label: '点样位置',
          members: [
            { key: 'x_start', label: 'X起点', node: 'Spot_6X_StartTarget', actpos: 'Spot_6X_ActPos', value: 70.0 },
            { key: 'x_end', label: 'X终点', node: 'Spot_6X_EndTarget', actpos: 'Spot_6X_ActPos', value: 240.0 },
            { key: 'y_height', label: 'Y高度', node: 'Spot_7Y_Target', actpos: 'Spot_7Y_ActPos', value: -20.0 },
          ],
        }],
      },
      {
        label: '拍照工位',
        points: [{
          category: 'plc_servo_target', id: 'photo_8y', label: '拍照8Y',
          node: 'Photo_8Y_Target', actpos: 'Photo_8Y_ActPos', value: 420.0, pending: false,
        }],
      },
      {
        label: '地轨',
        points: [
          {
            category: 'plc_servo', id: 'rail_p1_sampling', label: '地轨-上样位',
            node: 'HMI_地轨轴11Y', slot: 1, value: 168.0,
          },
          {
            category: 'plc_servo', id: 'rail_p4_tool', label: '地轨-工具位',
            node: 'HMI_地轨轴11Y', slot: 4, value: 500.0,
          },
        ],
      },
    ],
  },
}

const MANIFEST = {
  axes: [
    { id: 'axis_11y', rigged: true, zeroOffsetMm: 500, telemetry: { key: 'Rail_ActPos' } },
    { id: 'axis_1z', rigged: false, telemetry: { key: 'FeedLift_1Z_ActPos' } },
    { id: 'axis_4x', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Sampling_4X_ActPos' } },
    { id: 'axis_5z', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Sampling_5Z_ActPos' } },
    { id: 'axis_6x', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Spot_6X_ActPos' } },
    { id: 'axis_7y', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Spot_7Y_ActPos' } },
    { id: 'axis_8y', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'Photo_8Y_ActPos' } },
    { id: 'axis_10z', rigged: true, zeroOffsetMm: 0, telemetry: { key: 'PhotoScrape_10Z_ActPos' } },
  ],
  actuators: [
    { id: 'ps_shade', label: '遮光气缸', node: 'ST/ACTUATOR_PS_SHADE', transitionS: 1.2 },
    { id: 'rob_flip_suction', label: '吸盘翻转', node: 'ST/ACTUATOR_FLIP', transitionS: 0.6 },
  ],
  // col_clamp 是**联动组**(双指同步), 但动作映射表把它当气缸 —— 两处都要能找到
  linkages: [{ id: 'col_clamp', label: '收集夹持气缸', transitionS: 0.3, members: [1, 2] }],
  realtime: { axes: [{ id: 'axis_11y', velocityMax: 100 }, { id: 'axis_6x', velocityMax: 50 }] },
}

/** 精简映射表, 字段名与 clip_compiler.motion_map_document() 逐字一致 */
const MOTION_MAP = {
  schema: 'ptlc.action-motion-map/v1',
  sequenceActions: {
    'photoscrape.cam_photopos': [
      { kind: 'point', arg: 'ref_8y', axis: 'axis_8y', label: '拍照8Y·板送进暗箱', speedMmS: 120 },
      { kind: 'actuator', id: 'ps_shade', value: 1, label: '遮光气缸·落下' },
    ],
    // 字面 point 编码(点位编译期就定死): 这些动作**没有** point_ref 参数可选,
    // 逐字取自 generated/action-motion-map.json
    'sampling.flush': [
      { kind: 'axis', axis: 'axis_5z', toMm: 0, label: '上样5Z·抬针', speedMmS: 20 },
      { kind: 'point', point: 'sampling_4x_wash', axis: 'axis_4x', label: '上样4X·移到清洗位', speedMmS: 10 },
    ],
    'sampling.aspirate': [
      { kind: 'axis', axis: 'axis_5z', toMm: 0, label: '上样5Z·抬针(建气隔断)', speedMmS: 20 },
      { kind: 'well', label: '上样4X/3Y·移到样品孔', speedMmS: 10 },
      { kind: 'point', point: 'sample_5z_dip', axis: 'axis_5z', label: '上样5Z·下探进孔', speedMmS: 20 },
      { kind: 'axis', axis: 'axis_5z', toMm: 0, label: '上样5Z·抬针出孔', speedMmS: 20 },
    ],
    // 字面量里已内嵌成员(`spot_pose.y_height`), 不带 member 字段 —— 不许再拼一次
    'sampling.spray_axis': [
      { kind: 'point', point: 'spot_pose.y_height', axis: 'axis_7y', label: '点样7Y·移到喷涂位', speedMmS: 50 },
    ],
    // 步骤类型前端还不认识时: 明说, 不静默跳过
    'demo.future_kind': [{ kind: '将来的新类型', label: '未来步骤' }],
  },
  paramAxisActions: {
    'photoscrape.align_z': { axis: 'axis_10z', arg: 'z_mm', label: '对位10Z·升降', speedMmS: 5 },
  },
  cylinderActionsFixed: { 'collect.clamp': { id: 'col_clamp', value: 1 } },
  searchAxisActions: { 'feedlift.probe_stack': { label: '探测板堆张数', durationS: 0.4 } },
  fluidActions: { 'develop.fill': '所选缸的进液阀 + 按组的注射泵' },
  unresolvedActions: { 'photoscrape.align_move': '对位 XY 在 PLC 内部还要过 K/O 帧变换 —— 用「实机对照」' },
  ignoredActions: ['robot.query'],
  flipActuatorId: 'rob_flip_suction',
  toolAsset: { 1: 'TOOL_SUCTION', 2: 'TOOL_PLATE96', 3: 'TOOL_VIAL' },
  gripperByTool: { 2: 'rob_grip_plate96', 3: 'rob_grip_vial' },
  tankLidActions: {},
  tankLidLinkage: {},
}

const POINT_CATALOG = {
  schema: 'ptlc.robot-points/v1',
  points: {
    'robot-main.home': { joint: [-154.5, -47.8, 93.3, 44.6, -89.1, 125.0], robotName: 'P1' },
    // 派生点(接近位): 只有 pose, 关节角是管线离线反解出来的
    'derived.approach': {
      joint: null, jointSolved: [-66.78, 5.21, 114.61, -30.1, -90.09, 44.53],
      jointSolvedFrom: 'robot-main.home', robotName: 'FLOW_X', allowedMotion: ['move_l'],
    },
    // 两者都有: 实测的那份说了算
    'both.point': { joint: [10, 20, 30, 40, 50, 60], jointSolved: [1, 2, 3, 4, 5, 6], robotName: 'P77' },
    'zero.point': { joint: [0, 0, 0, 0, 0, 0], jointSolved: [0, 0, 0, 0, 0, 0], robotName: 'P99' },
  },
}

const CONTEXT = {
  servoIndex: indexServoPoints(POINTS),
  manifest: MANIFEST,
  clipNames: ['robot.tool_pickup', 'robot.tool_return'],
  motionMap: MOTION_MAP,
  pointCatalog: POINT_CATALOG,
  currentMmOf: () => null,
}

test('indexServoPoints 按 id 建索引(不是 key), 复合点成员带 id 前缀', () => {
  const index = CONTEXT.servoIndex
  assert.equal(index.get('rail_p4_tool').value, 500)
  assert.equal(index.get('rail_p4_tool').slot, 4)
  assert.equal(index.get('photo_8y').value, 420)
  assert.equal(index.get('photo_8y').actpos, 'Photo_8Y_ActPos')
  assert.equal(index.get('feedlift_1z_search_high').value, 512)
  // 复合点: 点位本身 + 各成员都可查, 成员带前缀避免第二个复合点撞名
  assert.equal(index.get('spot_pose.x_start').value, 70)
  assert.equal(index.get('spot_pose.y_height').value, -20)
  assert.equal(index.get('spot_pose').members.length, 3)
  // pending 点位**照样入索引**(与 clip_compiler.load_servo_points 一致): pending 只表示
  // "flat 节点待建, 不能下发", 值是实读真值; 能不能下发与能不能演是两件事。
  // (下拉里仍不出现 —— 那由后端 app._target_keys 滤, 前端不重复一遍。)
  assert.equal(index.get('sample_5z').value, 45)
  assert.equal(index.get('sample_5z_dip').value, 46.5)
  // 机器人点位不混进来
  assert.equal(index.has('robot-main.home'), false)
})

test('robot 组动作 -> 正式片段', () => {
  const plan = planSimulation({ name: 'robot.tool_pickup', kind: 'robot' }, {}, CONTEXT)
  assert.equal(plan.kind, 'clip')
  assert.equal(plan.clipName, 'robot.tool_pickup')
})

test('rail.move 槽号 -> 伪片段, 且能被 compileClip 编译', () => {
  const plan = planSimulation(
    { name: 'rail.move', kind: 'plc_l2', label: '地轨-移动到位' },
    { Rail_Target_Position: 4 },
    { ...CONTEXT, currentMmOf: () => 168 },
  )
  assert.equal(plan.kind, 'pseudo')
  assert.deepEqual(plan.axes, ['axis_11y'])
  assert.equal(plan.doc.home.axis_mm.axis_11y, 168)
  assert.equal(plan.doc.steps[0].do.axis.to_mm, 500)
  // 时长 = |500-168|/100 ≈ 3.32s
  assert.ok(Math.abs(plan.doc.steps[0].dur - 3.32) < 0.01)

  // 关键闭环: 伪片段必须真的能被既有编译器吃下
  const compiled = compileClip(plan.doc, {})
  assert.ok(compiled.duration > 3)
  const frames = compiled.channels.get('axis:axis_11y')
  assert.ok(frames?.length >= 1)
  assert.equal(frames[frames.length - 1].v, 500)
})

test('rail.move 缺槽号/点表缺失/轴未装配 -> unsupported 带原因, 没有常量兜底', () => {
  assert.equal(planSimulation({ name: 'rail.move' }, {}, CONTEXT).kind, 'unsupported')
  const noPoints = planSimulation(
    { name: 'rail.move' },
    { Rail_Target_Position: 4 },
    { ...CONTEXT, servoIndex: new Map() },
  )
  assert.equal(noPoints.kind, 'unsupported')
  assert.match(noPoints.reason, /点表/)
  const unrigged = planSimulation(
    { name: 'rail.move' },
    { Rail_Target_Position: 4 },
    { ...CONTEXT, manifest: { axes: [{ id: 'axis_11y', rigged: false }] } },
  )
  assert.match(unrigged.reason, /未装配/)
})

test('point_ref 入参 -> 点表 -> 轴(由 actpos 派生), 复合点出多轴片段', () => {
  const action = {
    name: 'sampling.spot_band_layer',
    kind: 'plc_l2',
    label: '上样-条带点样',
    params: [
      { name: 'ref_spot', type: 'point_ref', required: true },
      { name: 'y_height', type: 'float', required: false },
    ],
  }
  const plan = planSimulation(action, { ref_spot: 'spot_pose' }, CONTEXT)
  assert.equal(plan.kind, 'pseudo')
  // 6X 走 70 -> 240 的扫描带, 7Y 落到 -20; 轴全由 actpos 派生, 无手工映射
  assert.deepEqual(plan.axes.sort(), ['axis_6x', 'axis_7y'])
  assert.deepEqual(plan.doc.steps.map((step) => step.do.axis),
    [{ id: 'axis_6x', to_mm: 70 }, { id: 'axis_6x', to_mm: 240 }, { id: 'axis_7y', to_mm: -20 }])
  compileClip(plan.doc, {})

  // 成员覆盖: 同名入参临时改写示教基准, 演示要跟着走
  const overridden = planSimulation(action, { ref_spot: 'spot_pose', y_height: -35 }, CONTEXT)
  assert.equal(overridden.doc.steps[2].do.axis.to_mm, -35)

  // 没选点位 / 选了不存在的点位: 如实说, 不编一个位置
  assert.equal(planSimulation(action, {}, CONTEXT).kind, 'unsupported')
  assert.match(planSimulation(action, { ref_spot: '压根没这个点' }, CONTEXT).reason, /点表里没有点位/)
})

test('多步定值序列: point 步实读点表, 气缸步照表驱', () => {
  const plan = planSimulation(
    {
      name: 'photoscrape.cam_photopos',
      kind: 'plc_l2',
      label: '拍照-移到相机位',
      params: [{ name: 'ref_8y', type: 'point_ref', required: true }],
    },
    { ref_8y: 'photo_8y' },
    CONTEXT,
  )
  assert.equal(plan.kind, 'pseudo')
  assert.equal(plan.doc.steps[0].do.axis.to_mm, 420)   // 点表值, 不是常量
  assert.deepEqual(plan.doc.steps[1].do, { actuator: { id: 'ps_shade', to: 1 } })
  assert.equal(plan.doc.home.actuators.ps_shade, 0)
  compileClip(plan.doc, {})
})

test('多步定值序列: 字面 point 步不需要任何入参 —— 不许倒过来问用户要点位', () => {
  // 回归的是这个缺陷: 前端只认 {arg} 编码, 遇到 {point} 字面编码就取 params[undefined],
  // 于是七个参数里没有一个 point_ref 的"上样-充液润洗"被判 unsupported, 提示里还漏出
  // 一个字面量 undefined。Python 侧 emit_sequence 一直是两种编码都吃的。
  const action = {
    name: 'sampling.flush',
    kind: 'plc_l2',
    label: '上样-充液润洗',
    params: [{ name: 'pump_speed', type: 'int', required: false }],
  }
  const plan = planSimulation(action, {}, CONTEXT)   // ← 一个入参都不给
  assert.equal(plan.kind, 'pseudo')
  assert.deepEqual(plan.doc.steps.map((step) => step.do.axis), [
    { id: 'axis_5z', to_mm: 0 },
    { id: 'axis_4x', to_mm: 0 },   // sampling_4x_wash 的现值(还没 jog 示教)
  ])
  compileClip(plan.doc, {})

  // 字面量里已内嵌成员的形态: 取 `spot_pose.y_height` 本身, 不许再拼一次成员
  const spray = planSimulation(
    { name: 'sampling.spray_axis', kind: 'plc_l2', label: '上样-喷涂移轴' }, {}, CONTEXT,
  )
  assert.equal(spray.kind, 'pseudo')
  assert.deepEqual(spray.doc.steps[0].do.axis, { id: 'axis_7y', to_mm: -20 })

  // 点表整个不可用时仍要说清是哪个点位缺, 而不是问用户要参数
  const noPoints = planSimulation(action, {}, { ...CONTEXT, servoIndex: new Map() })
  assert.equal(noPoints.kind, 'unsupported')
  assert.match(noPoints.reason, /点表里没有点位 sampling_4x_wash/)
  assert.doesNotMatch(noPoints.reason, /undefined|请先在参数里/)
})

test('多步定值序列: well 步与未知步骤类型都要说清, 不静默跳过', () => {
  // 孔位毫米是编译期从 config/calibration.yaml 仿射算的, 映射表不导出 ——
  // 前端只能照编译器未标定分支占一个说明白的时间格, 不许半演一个编出来的孔位
  const plan = planSimulation(
    { name: 'sampling.aspirate', kind: 'plc_l2', label: '上样-吸样' }, {}, CONTEXT,
  )
  assert.equal(plan.kind, 'pseudo')
  assert.deepEqual(plan.doc.steps.map((step) => step.label), [
    '上样5Z·抬针(建气隔断)',
    '上样4X/3Y·移到样品孔(孔板未标定, 未表现)',
    '上样5Z·下探进孔 → 46.5 mm',   // pending 点位实读值, 不是抬针位 0
    '上样5Z·抬针出孔',
  ])
  compileClip(plan.doc, {})

  const future = planSimulation({ name: 'demo.future_kind', kind: 'plc_l2' }, {}, CONTEXT)
  assert.equal(future.kind, 'unsupported')
  assert.match(future.reason, /还不认识的步骤类型/)
})

test('目标毫米来自入参的轴动作', () => {
  const action = {
    name: 'photoscrape.align_z',
    kind: 'plc_l2',
    label: '对位-Z升降',
    params: [{ name: 'z_mm', type: 'float', required: true }],
  }
  const plan = planSimulation(action, { z_mm: 12 }, CONTEXT)
  assert.equal(plan.kind, 'pseudo')
  assert.equal(plan.doc.steps[0].do.axis.to_mm, 12)
  assert.equal(planSimulation(action, {}, CONTEXT).kind, 'unsupported')
})

test('col_clamp 在 linkages 里也要找得到, 并走 linkage 通道', () => {
  const plan = planSimulation(
    { name: 'collect.clamp', kind: 'plc_l2', label: '收集-夹紧' }, {}, CONTEXT,
  )
  assert.equal(plan.kind, 'pseudo')
  assert.deepEqual(plan.doc.steps[0].do, { linkage: { id: 'col_clamp', to: 1 } })
  assert.equal(plan.doc.home.linkages.col_clamp, 0)
  compileClip(plan.doc, {})
})

test('host 只读动作判无机械动作, 即使它也在搜索表里', () => {
  const plan = planSimulation({ name: 'feedlift.probe_stack', kind: 'host' }, {}, CONTEXT)
  assert.equal(plan.kind, 'no-motion')
})

test('泵/阀动作说清驱了什么, reason 里不许出现"目标毫米"', () => {
  const plan = planSimulation({ name: 'develop.fill', kind: 'plc_l2' }, {}, CONTEXT)
  assert.equal(plan.kind, 'no-motion')
  assert.match(plan.reason, /进液阀/)
  assert.doesNotMatch(plan.reason, /目标毫米/)
})

test('机械臂控制态动作判无机械动作; 到点用实测关节角, 全零视为无实测值', () => {
  assert.equal(planSimulation({ name: 'robot.stop', kind: 'robot' }, {}, CONTEXT).kind, 'no-motion')
  assert.equal(planSimulation({ name: 'robot.pause', kind: 'robot' }, {}, CONTEXT).kind, 'no-motion')

  const good = planSimulation(
    { name: 'robot.move_to_point', kind: 'robot' },
    { point_id_or_robot_name: 'robot-main.home' }, CONTEXT,
  )
  assert.equal(good.kind, 'pseudo')
  assert.equal(good.doc.steps[0].do.joints.to_deg[0], -154.5)

  const zero = planSimulation(
    { name: 'robot.move_to_point', kind: 'robot' },
    { point_id_or_robot_name: 'zero.point' }, CONTEXT,
  )
  assert.equal(zero.kind, 'unsupported')
  assert.match(zero.reason, /没有实测关节角/)
})

test('目标值在 PLC 内部的动作给出逐条实情, 不是一句话糊全部', () => {
  const plan = planSimulation({ name: 'photoscrape.align_move', kind: 'plc_l2' }, { x_mm: 1, y_mm: 2 }, CONTEXT)
  assert.equal(plan.kind, 'unsupported')
  assert.match(plan.reason, /K\/O 帧变换/)
})

test('jointsOfPoint: 实测优先于离线反解, 且必须说清用的是哪一种', () => {
  assert.deepEqual(jointsOfPoint(POINT_CATALOG, 'robot-main.home').joints.length, 6)
  assert.equal(jointsOfPoint(POINT_CATALOG, 'robot-main.home').source, 'taught')
  assert.equal(jointsOfPoint(POINT_CATALOG, 'P1').joints[0], -154.5)

  // 派生点只有反解值 -> 用它, 但来源标 solved
  const derived = jointsOfPoint(POINT_CATALOG, 'derived.approach')
  assert.equal(derived.source, 'solved')
  assert.equal(derived.joints[0], -66.78)

  // 实测在场时反解值不许抢
  const both = jointsOfPoint(POINT_CATALOG, 'both.point')
  assert.equal(both.source, 'taught')
  assert.equal(both.joints[0], 10)

  // 全零 = 占位, 两个字段都不算数
  assert.equal(jointsOfPoint(POINT_CATALOG, 'zero.point'), null)
  assert.equal(jointsOfPoint(POINT_CATALOG, '不存在'), null)
})

test('换刀/夹爪: 单条动作演示定不下来刀号时, 明说而不是挂一把错的', () => {
  const action = { name: 'robot.tool_action', kind: 'robot', label: '工具动作' }
  const lock = planSimulation(action, { action: 'quick-change-lock' }, CONTEXT)
  assert.equal(lock.kind, 'unsupported')
  assert.match(lock.reason, /刀号/)
  const grip = planSimulation(action, { action: 'gripper-close' }, CONTEXT)
  assert.equal(grip.kind, 'unsupported')
  assert.match(grip.reason, /几号刀/)
  // 翻转只有 1 号刀有, 机构固定 -> 照样能演
  const flip = planSimulation(action, { action: 'rotary-up' }, CONTEXT)
  assert.equal(flip.kind, 'pseudo')
})

test('velocityMaxOf 读 manifest.realtime, 缺失返回 null', () => {
  assert.equal(velocityMaxOf(MANIFEST, 'axis_11y'), 100)
  assert.equal(velocityMaxOf(MANIFEST, 'axis_none'), null)
  assert.equal(velocityMaxOf({}, 'axis_11y'), null)
})

// ── 展缸液面 ─────────────────────────────────────────────────────────────────
// 单动作演示的液面, 关键在"注液与排液的起点从哪来"这一处不对称:
//   注液: 起点 0 mL —— 空缸是一个没跑过任何东西的离线场景唯一能断言的状态, 不是猜;
//   排液: 动作入参里一滴体积都没有(只有 settle_s / drain_duration_s), 起点只能靠假设,
//         所以必须写进标签与 note, 且可由面板改。
const TANK_MANIFEST = {
  ...MANIFEST,
  tanks: [
    { index: 0, id: 'tank1', label: '展缸 1', liquidNode: 'ST_DEVELOP/TANK_1/LIQUID_1' },
    { index: 2, id: 'tank3', label: '展缸 3', liquidNode: 'ST_DEVELOP/TANK_3/LIQUID_3' },
    { index: 3, id: 'tank4', label: '展缸 4', liquidNode: null },
  ],
  tankLiquid: {
    cavity: { usableDepthMm: 20.274, freeAreaMm2: 4939.6, capacityMl: 102.48 },
    exaggeration: 2,
    pipeHoldupMl: 0,
    tankArg: 'target_tank',
    actions: {
      'develop.fill': { dir: 'fill', volumeFrom: ['solvent_volume_ml', 'up_liquid_repeat_count'], rampS: 12 },
      // 配对注液动作也必须在表里: 建议起始液位是拿它的体积规则算的, 不是另立一套
      'develop.rinse_fill': { dir: 'fill', volumeFrom: ['solvent_volume_ml', 'rinse_repeat_count'], rampS: 10 },
      'develop.rinse_suction': { dir: 'drain', rampS: 8, delayFromArg: 'settle_s', demoFillFrom: 'develop.rinse_fill' },
    },
  },
}

/** /api/actions 目录片段: 建议起始液位要从配对注液动作的 default 里推 */
const ACTION_CATALOG = [{
  name: 'develop.rinse_fill',
  label: '展缸-润洗注液',
  params: [
    { name: 'solvent_volume_ml', default: 10 },
    { name: 'rinse_repeat_count', default: 2 },
  ],
}]

const FILL_ACTION = { name: 'develop.fill', label: '展缸-上液', kind: 'plc_l2', params: [] }
const SUCTION_ACTION = { name: 'develop.rinse_suction', label: '展缸-润洗抽吸', kind: 'plc_l2', params: [] }

const tankCtx = (extra = {}) => ({
  servoIndex: new Map(), manifest: TANK_MANIFEST, clipNames: [], motionMap: MOTION_MAP, ...extra,
})

test('展缸-上液: 液面从 0 涨到 配方体积 × 趟数, 且伪片段真能编译', () => {
  const plan = planSimulation(FILL_ACTION,
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 }, tankCtx())
  assert.equal(plan.kind, 'pseudo')
  assert.deepEqual(plan.doc.home.liquid_ml, { tank1: 0 }, '注液起点是空缸')

  const clip = compileClip(plan.doc)
  const at = (t) => evaluateChannels(clip, t).liquids.tank1
  assert.equal(at(0), 0)
  assert.equal(at(clip.duration), 60, '20mL × 3 趟 = 60mL')
})

test('展缸-上液: 默认 2mL 在 102mL 的槽里几乎看不见, 必须在 note 里点名真实配方', () => {
  const plan = planSimulation(FILL_ACTION, { target_tank: 1, solvent_volume_ml: 2 }, tankCtx())
  assert.equal(plan.kind, 'pseudo')
  assert.match(plan.note, /几乎看不见/)
  assert.match(plan.note, /develop_prepare/, '要指出去哪儿看真实配方')
})

test('展缸-润洗抽吸: 起始液位按配对注液动作的默认配方假设, 且假设写进 note', () => {
  const plan = planSimulation(SUCTION_ACTION, { target_tank: 3, settle_s: 3 },
    tankCtx({ actionCatalog: ACTION_CATALOG }))
  assert.equal(plan.kind, 'pseudo')
  // 10mL × 2 趟 = 20mL, 走的是与实时页同一个 resolveLiquidPlan
  assert.deepEqual(plan.doc.home.liquid_ml, { tank3: 20 })
  assert.match(plan.note, /假设/)
  assert.match(plan.note, /展缸-润洗注液/, '要说清这个数出自哪条动作')
  assert.equal(plan.needsStartMl, true, '面板据此露出"起始液位"输入框')
  assert.equal(plan.startMlSuggested, 20)

  const clip = compileClip(plan.doc)
  assert.equal(evaluateChannels(clip, 0).liquids.tank3, 20)
  assert.equal(evaluateChannels(clip, clip.duration).liquids.tank3, 0, '排完归零')
  assert.equal(evaluateChannels(clip, 3).liquids.tank3, 20, 'settle_s 期间先静置再抽')
})

test('展缸-润洗抽吸: 面板给的起始液位压过建议值', () => {
  const plan = planSimulation(SUCTION_ACTION, { target_tank: 3, settle_s: 0 },
    tankCtx({ actionCatalog: ACTION_CATALOG, startMl: 55 }))
  assert.deepEqual(plan.doc.home.liquid_ml, { tank3: 55 })
  assert.match(plan.note, /由面板指定/)
})

test('展缸-润洗抽吸: 动作目录拿不到时不编体积, 如实说定不出起始液位', () => {
  const plan = planSimulation(SUCTION_ACTION, { target_tank: 3, settle_s: 3 }, tankCtx())
  assert.equal(plan.kind, 'no-motion', '宁可说定不下来, 也不凭空编一个体积')
  assert.match(plan.reason, /起始液位/)
  assert.match(plan.reason, /develop_prepare/, '要指一条真能看到的路')
  assert.equal(plan.needsStartMl, true, '仍要露输入框 —— 用户填了就能看')
})

test('该缸没有液面几何时退回"不表现", 不拿别的缸顶替', () => {
  const plan = planSimulation(FILL_ACTION,
    { target_tank: 4, solvent_volume_ml: 20 }, tankCtx())
  assert.notEqual(plan.kind, 'pseudo')
})
