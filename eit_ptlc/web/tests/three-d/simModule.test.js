// 仿真页 (three-d/sim) 离线单测: API 动词映射 / 事件流注入 / 运行状态机 / 行与补丁构造
// / 入参表单契约 / 泵反馈合成
import assert from 'node:assert/strict'
import test from 'node:test'

import { EventStream } from '../../src/three-d/twin/bindings/eventStream.js'
import { PumpSyringeModel } from '../../src/three-d/twin/bindings/PumpSyringeModel.js'
import {
  coerceParam, collectFlowInputs, collectParams, rowsFromParams, rowsFromVars,
} from '../../src/three-d/sim/runFormRows.js'
import { createSimApi } from '../../src/three-d/sim/simApi.js'
import {
  createRunState, ingest, isFinal, reconcileActiveRuns,
} from '../../src/three-d/sim/simRunState.js'
import {
  axisRows, buildAxisPatch, buildJointPatch, buildMechanismPatch, buildPumpPatch,
  buildToolPatch, jointRows, mechanismGroups, poseRows, pumpRows,
} from '../../src/three-d/sim/simStateRows.js'

if (typeof performance === 'undefined') {
  globalThis.performance = { now: () => 0 }
}

// ---------------------------------------------------------------------------
// simApi: 动词 → URL/方法 映射 (仿 manualSession 测试手法, 注入 request 替身)
// ---------------------------------------------------------------------------
test('simApi 动词映射与请求方法', async () => {
  const calls = []
  const api = createSimApi(async (path, options = {}) => {
    calls.push([options.method || 'GET', path, options.body])
    return { ok: true }
  })
  await api.createSession({ adopt: true })
  await api.sessionStatus()
  await api.destroySession()
  await api.fetchState()
  await api.patchState({ axes: { axis_4x: 1 } })
  await api.adoptLive()
  await api.resetHome()
  await api.setTimeScale(4)
  await api.runAction('sampling.flush', { flush_volume_ml: 17 })
  await api.startRun('sampling_prepare', { inputs: { a: 1 }, modeRun: 'step' })
  await api.runVerb('r1', 'pause')
  await api.humanReply('r1', 'q1', { choice: 'ok' })

  assert.deepEqual(calls.map(([method, path]) => `${method} ${path}`), [
    'POST /api/sim/session',
    'GET /api/sim/session',
    'DELETE /api/sim/session',
    'GET /api/sim/state',
    'PUT /api/sim/state',
    'POST /api/sim/adopt',
    'POST /api/sim/reset',
    'POST /api/sim/time_scale',
    'POST /api/sim/actions/sampling.flush/run',
    'POST /api/sim/scripts/sampling_prepare/debug/run',
    'POST /api/sim/debug/r1/pause',
    'POST /api/sim/debug/r1/human/q1',
  ])
  const startBody = calls.find(([, path]) => path.includes('/debug/run'))[2]
  assert.equal(startBody.mode_run, 'step')
  assert.deepEqual(startBody.inputs, { a: 1 })
})

// ---------------------------------------------------------------------------
// EventStream 注入口: transport/seeder 可换源, 默认行为不变的护栏由既有
// materialFallback.test.js 把守, 这里只测注入路径
// ---------------------------------------------------------------------------
test('EventStream 接受注入 transport 与 seeder', async () => {
  let statusHandler = null
  const seen = []
  const seeded = []
  const transport = {
    onEvent: (fn) => {
      transport._emit = fn
      return () => { transport._emit = null }
    },
    onStatus: (fn) => {
      statusHandler = fn
      fn(false)
      return () => { statusHandler = null }
    },
  }
  const stream = new EventStream({
    transport,
    seeder: async ({ dispatch }) => {
      seeded.push(true)
      dispatch({ type: 'telemetry', seeded: true })
    },
  })
  stream.onEvent((event) => seen.push(event))
  statusHandler(true)                       // 连接沿 → 走注入的播种器
  await Promise.resolve()
  transport._emit({ type: 'axis_pose', positions: { axis_4x: 1 } })
  assert.equal(seeded.length, 1)
  assert.equal(seen.length, 2)
  assert.equal(seen[0].seeded, true)
  assert.equal(seen[1].type, 'axis_pose')
  stream.dispose()
})

// ---------------------------------------------------------------------------
// simRunState: 状态机
// ---------------------------------------------------------------------------
test('simRunState 吞事件推进状态与日志', () => {
  const state = createRunState()
  state.runId = 'r1'
  assert.equal(ingest(state, { type: 'operation_start', run_id: 'r1', operation: 'x' }), true)
  assert.equal(state.status, 'RUNNING')
  ingest(state, { type: 'vm_node_enter', run_id: 'r1', aid: 'b/0', label: '动作A' })
  assert.equal(state.activeNodes.length, 1)
  ingest(state, { type: 'vm_human_request', run_id: 'r1', req_id: 'q1', kind: 'confirm', title: '确认' })
  assert.equal(state.status, 'WAITING_HUMAN')
  assert.equal(state.human.reqId, 'q1')
  ingest(state, { type: 'vm_human_reply', run_id: 'r1', req_id: 'q1' })
  assert.equal(state.human, null)
  ingest(state, { type: 'vm_node_done', run_id: 'r1', aid: 'b/0', ok: true })
  assert.equal(state.activeNodes.length, 0)
  // 其它运行的事件不串台
  assert.equal(ingest(state, { type: 'operation_done', run_id: 'r2' }), false)
  ingest(state, { type: 'operation_done', run_id: 'r1' })
  assert.equal(state.status, 'DONE')
  assert.equal(isFinal(state), true)
  assert.ok(state.logs.length >= 3)
})

test('simRunState 从活动快照恢复 UniLab 外部运行的人工确认门', () => {
  const state = createRunState()
  reconcileActiveRuns(state, [
    { run_id: 'running', status: 'RUNNING', operation: 'ordinary' },
    {
      run_id: 'human', status: 'WAITING_HUMAN', operation: 'pf_s6_develop_wait',
      current_aid: 'b/2/then/0', active_nodes: [],
      pending_human: {
        req_id: 'q1', kind: 'confirm', prompt: '确认开始排液', options: [],
      },
    },
  ])
  assert.equal(state.runId, 'human', '未绑定时优先展示需要操作员处理的运行')
  assert.equal(state.status, 'WAITING_HUMAN')
  assert.equal(state.currentAid, 'b/2/then/0')
  assert.equal(state.human.reqId, 'q1')
  assert.equal(state.human.message, '确认开始排液')
  assert.deepEqual(state.human.options, [])

  reconcileActiveRuns(state, [{
    run_id: 'human', status: 'RUNNING', operation: 'pf_s6_develop_wait',
    current_aid: 'b/3', active_nodes: [
      { aid: 'b/3', script: 'pf_s6_develop_wait', action: 'develop.drain' },
    ],
  }])
  assert.equal(state.status, 'RUNNING')
  assert.equal(state.human, null)
  assert.equal(state.activeNodes[0].action, 'develop.drain')
})

// ---------------------------------------------------------------------------
// runFormRows: 入参表单契约 (教训 2026-08-09: robot_tool_ensure 的 needed 报"留空")
// ---------------------------------------------------------------------------
test('rowsFromVars 归一 {value,label} 取值域并以字符串初值预选默认', () => {
  const rows = rowsFromVars([
    { name: 'needed', io: 'in', type: 'INT', default: 1,
      enum: [{ value: 1, label: '1 吸盘' }, { value: 2, label: '2 大夹爪' }] },
    { name: 'well', io: 'in', type: 'STRING', default: 'A1' },
    { name: 'fb', io: 'var', type: 'INT' },              // 非 in: 不进表单
  ])
  assert.equal(rows.length, 2)
  const needed = rows[0]
  // 归一后 option 是 {value:String,label:String}, 初值同型字符串 → 下拉能选中默认
  assert.deepEqual(needed.enum, [
    { value: '1', label: '1 吸盘' },
    { value: '2', label: '2 大夹爪' },
  ])
  assert.equal(needed.value, '1')
  assert.equal(rows[1].value, 'A1')
})

test('collectFlowInputs 空值整键不提交, 其余原样字符串 (类型交后端 coerce)', () => {
  const inputs = collectFlowInputs([
    { name: 'needed', value: '2' },
    { name: 'skip_me', value: '' },        // 取默认 = 不提交该键
    { name: 'blank', value: '   ' },
    { name: 'none', value: null },
    { name: 'count', value: '3' },
  ])
  assert.deepEqual(inputs, { needed: '2', count: '3' })
})

test('coerceParam 对非数字文本返回 undefined 而不是 NaN (NaN 会 JSON 成 null)', () => {
  assert.equal(coerceParam({ type: 'INT', value: '[object Object]' }), undefined)
  assert.equal(coerceParam({ type: 'FLOAT', value: 'abc' }), undefined)
  assert.equal(coerceParam({ type: 'INT', value: '17' }), 17)
  assert.equal(coerceParam({ type: 'FLOAT', value: '2.5' }), 2.5)
  assert.equal(coerceParam({ type: 'BOOL', value: 'true' }), true)
  assert.equal(coerceParam({ type: 'STRING', value: 'x' }), 'x')
  assert.equal(coerceParam({ type: 'INT', value: '' }), undefined)
  const params = collectParams([
    { name: 'good', type: 'INT', value: '5' },
    { name: 'bad', type: 'INT', value: 'oops' },
  ])
  assert.deepEqual(params, { good: 5 })
})

test('rowsFromParams 摊平 options 并字符串化初值 (enum 下拉可选中)', () => {
  const rows = rowsFromParams([
    { name: 'mode', type: 'enum', default: 1,
      options: [{ value: 1, label: 'a' }, { value: 2, label: 'b' }] },
  ])
  assert.deepEqual(rows[0].enum, ['1', '2'])
  assert.equal(rows[0].value, '1')
})

// ---------------------------------------------------------------------------
// PumpSyringeModel.pushFeedback: 反馈优先但不杀包络 (教训 2026-08-09: 曾 active=null
// 永久掐死相位推进, 且没设 period —— 10Hz 反馈流对着十几秒 tau 视觉纹丝不动)
// ---------------------------------------------------------------------------
function makePumpConfig() {
  return {
    syringeMl: 25, strokeMm: 60, stepsPerStroke: 6000,
    speeds: { sampling: { asp_speed: 250, disp_speed: 100, step_delay: 1500 } },
    pumps: [{
      index: 0, id: 'SMP', label: '上样泵', station: 'SAMPLING', dtAddr: 4,
      valve: 'T-04', tankGroup: [], travelAxis: [0, 1, 0], travelM: 0.06,
      strokeMm: 60, valvePorts: 4, outputPort: 3, valveAxis: [0, 0, 1],
      rigged: true, plungerNode: 'P', liquidNode: 'L',
      speedStation: 'sampling', leadTurnsPerStroke: 10,
    }],
    actions: {
      'x.fill': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [{ op: 'aspirate', to: 20, port: 1, rampS: 4, speed: 'asp_speed' }],
      },
    },
  }
}

test('pushFeedback 直设目标/period 并保留包络 (相位读数不灭)', () => {
  const model = new PumpSyringeModel(makePumpConfig())
  model.onActionEnter('x.fill', {})
  assert.ok(model.active[0], '包络应已建立')
  model.pushFeedback({ id: 'SMP', plunger_ml: 10, valve_port: 3 })
  const channel = model.plungers[0]
  assert.equal(channel.target, 10)               // 反馈优先: 目标=真实值, 不是包络的 20
  assert.equal(channel.period, 0.1)              // tau≈0.125s, 追得上 10Hz 流
  assert.equal(model.known[0], true)
  assert.ok(model.active[0], '包络不再被反馈杀死 (phaseInfo 读数保留)')
  assert.equal(model.ports[0], 3)
})

test('反馈新鲜期内 done 不跳变通道; 过期后包络恢复写通道', () => {
  const model = new PumpSyringeModel(makePumpConfig())
  model.onActionEnter('x.fill', {})
  model.pushFeedback({ id: 'SMP', plunger_ml: 5 })
  model.step(0.1)
  const valueBefore = model.plungers[0].value
  model.onActionDone('x.fill', {}, 'DONE')
  // 新鲜期: 位置归反馈, done 不把 value 硬拉到包络终点 20
  assert.ok(model.plungers[0].value < 15, `done 不应跳变, 得到 ${model.plungers[0].value}`)
  assert.ok(Math.abs(model.plungers[0].value - valueBefore) < 1,
    'done 只收账不动通道')
  // 反馈停发 >1s 后, 包络重新接管通道写
  model.step(2.0)
  model.onActionEnter('x.fill', {})
  assert.equal(model.plungers[0].target, 20, '新鲜期过后包络恢复写目标')
})

// ---------------------------------------------------------------------------
// simStateRows: manifest 驱动的行构造 + clamp 补丁
// ---------------------------------------------------------------------------
const MANIFEST = {
  axes: [
    { id: 'axis_4x', label: '上样4X', rangeMm: [-15.75, 143.75] },
    { id: 'axis_11y', label: '地轨11Y', rangeMm: [-54.9, 845.1] },
  ],
  robot: { joints: [{ label: 'J1', limitDeg: [-180, 180] }, { label: 'J2', limitDeg: [-90, 90] }] },
  realtime: {
    mechanisms: [
      { id: 'smp_clamp', label: '上样夹紧', station: 'SAMPLING' },
      { id: 'dev_lid_1', label: '缸盖1', station: 'DEVELOP' },
      { id: 'no_snapshot', label: '无快照机构', station: 'DEVELOP' },
    ],
  },
}

test('simStateRows 行构造与补丁 clamp', () => {
  const axes = axisRows(MANIFEST, { axis_4x: { mm: 12.5 } })
  assert.equal(axes.length, 2)
  assert.equal(axes[0].mm, 12.5)
  assert.equal(axes[1].mm, null)

  const patch = buildAxisPatch(axes[0], 999)
  assert.equal(patch.axes.axis_4x, 143.75)          // clamp 到 rangeMm 上限
  assert.equal(buildAxisPatch(axes[0], -999).axes.axis_4x, -15.75)

  const joints = jointRows(MANIFEST, [10, 20])
  assert.equal(joints[1].deg, 20)
  const jointPatch = buildJointPatch(joints, [200, -200])
  assert.deepEqual(jointPatch.robot.joint, [180, -90])  // 逐关节 clamp

  assert.deepEqual(buildToolPatch('2'), { robot: { tool: 2 } })
  assert.deepEqual(buildMechanismPatch('smp_clamp', 1), { mechanisms: { smp_clamp: true } })

  const groups = mechanismGroups(MANIFEST, {
    smp_clamp: { commanded: true, confirmed: null },
    dev_lid_1: { commanded: false, confirmed: true },
  })
  assert.equal(groups.length, 2)                    // 无快照的机构不出现
  const sampling = groups.find((g) => g.station === 'SAMPLING')
  assert.equal(sampling.items[0].on, true)          // confirmed null → 退 commanded
  const develop = groups.find((g) => g.station === 'DEVELOP')
  assert.equal(develop.items[0].on, true)           // confirmed 优先
})

test('poseRows: TCP 位姿只读行, 位数不足即留空', () => {
  const rows = poseRows([1.234, -2, 300, 180, 0.5, -90])
  assert.deepEqual(rows.map((r) => r.key), ['x', 'y', 'z', 'rx', 'ry', 'rz'])
  assert.deepEqual(rows.map((r) => r.unit), ['mm', 'mm', 'mm', '°', '°', '°'])
  assert.equal(rows[0].value, 1.234)
  assert.equal(rows[5].value, -90)
  // 行里**不带任何写口字段** —— 位姿只读是刻意的 (见 poseRows 注释: 开写口会造出
  // pose 与 joint 不自洽的姿态), 有人日后加了 min/max/step 想做滑杆, 这条会红
  for (const row of rows) {
    assert.deepEqual(Object.keys(row).sort(), ['key', 'label', 'unit', 'value'])
  }
  assert.deepEqual(poseRows([1, 2, 3]), [], '位数不足不硬凑')
  assert.deepEqual(poseRows(null), [])
  assert.equal(poseRows([1, 2, 3, 4, 5, null])[5].value, null, '单个分量缺失记 null')
})

test('pumpRows/buildPumpPatch: 泵相位可设, 满程夹逼, 忙态透出', () => {
  const rows = pumpRows({
    SMP: { id: 'SMP', plunger_ml: 3.5, valve_port: 2, busy: false },
    COL: { id: 'COL', plunger_ml: 0, valve_port: null, busy: true },
  })
  assert.deepEqual(rows.map((r) => r.id), ['COL', 'SMP'], '按 id 排序, 顺序稳定')
  assert.equal(rows[0].busy, true, '忙态要透出 —— 面板据此禁写, 后端也会拒')
  assert.equal(rows[0].valvePort, null, '没转过阀就是未知, 不许折算成 1 口')
  assert.equal(rows[1].plungerMl, 3.5)

  assert.deepEqual(buildPumpPatch('SMP', 'plunger_ml', 999),
    { pumps: { SMP: { plunger_ml: 25 } } }, '柱塞夹逼到满程')
  assert.deepEqual(buildPumpPatch('SMP', 'plunger_ml', -5),
    { pumps: { SMP: { plunger_ml: 0 } } })
  assert.deepEqual(buildPumpPatch('SMP', 'valve_port', 0),
    { pumps: { SMP: { valve_port: 1 } } }, '阀口下限 1')
  assert.deepEqual(pumpRows(null), [], '沙盒未就绪不抛')
})
