import test from 'node:test'
import assert from 'node:assert/strict'

import { AxisPoseBuffer } from '../../src/three-d/twin/bindings/AxisPoseBuffer.js'
import { MechanismStateStore } from '../../src/three-d/twin/bindings/MechanismStateStore.js'
import { TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'


test('AxisPoseBuffer 以 100ms 缓冲处理乱序、重复、回退、stale 与重连直达', () => {
  const base = 1_700_000_000_000
  const buffer = new AxisPoseBuffer({ delayMs: 100, staleMs: 500 })
  assert.equal(buffer.push({
    type: 'axis_pose', seq: 1, ts: base,
    positions: { axis_11y: 0 }, velocities: { axis_11y: 20 },
  }, base), true)
  buffer.push({ type: 'axis_pose', seq: 3, ts: base + 100, positions: { axis_11y: 20 } }, base + 100)
  buffer.push({ type: 'axis_pose', seq: 2, ts: base + 50, positions: { axis_11y: 10 } }, base + 100)
  assert.equal(buffer.push({
    type: 'axis_pose', seq: 2, ts: base + 50, positions: { axis_11y: 10 },
  }, base + 100), false, '同 seq 重复帧必须丢弃')

  const middle = buffer.sample(base + 175) // render time = base + 75
  assert.ok(Math.abs(middle.positions.axis_11y - 15) < 1e-9)
  assert.equal(middle.stale.axis_11y, false)
  assert.equal(buffer.pushTelemetry({ axis_11y: 999 }, base + 120, base + 120), false,
    '高频源健康时 1Hz 回退不得把轴拉回去')

  assert.equal(buffer.push({
    type: 'axis_pose', seq: 3, ts: base + 100, positions: { axis_11y: 20 },
  }, base + 500), false)
  assert.equal(buffer.sample(base + 601).stale.axis_11y, true,
    '重复帧不能刷新最后有效到达时间')

  assert.equal(buffer.sample(base + 701).stale.axis_11y, true)
  assert.equal(buffer.push({
    type: 'axis_pose', seq: 1, ts: base + 800, positions: { axis_11y: 500 },
  }, base + 800), true, '重连后允许 seq 从 1 重新开始')
  const reconnected = buffer.sample(base + 800)
  assert.equal(reconnected.positions.axis_11y, 500, '重连首帧直接恢复，不从旧位置补间')
  assert.deepEqual(reconnected.resynced, ['axis_11y'])
})


test('显式断连后即使 500ms 内重连也不在轴旧新位置之间补间', () => {
  const base = 1_700_000_000_000
  const buffer = new AxisPoseBuffer({ delayMs: 100, staleMs: 500 })
  buffer.push({ type: 'axis_pose', seq: 90, ts: base, positions: { axis_11y: 10 } }, base)
  buffer.markDisconnected()
  buffer.push({ type: 'axis_pose', seq: 1, ts: base + 100, positions: { axis_11y: 900 } }, base + 100)
  const sample = buffer.sample(base + 100)
  assert.equal(sample.positions.axis_11y, 900)
  assert.deepEqual(sample.resynced, ['axis_11y'])
})


test('MechanismStateStore 反馈优先于命令态并保留 estimated/stale 真值标签', () => {
  const base = 1_700_000_000_000
  const store = new MechanismStateStore({ staleMs: 500, knownIds: ['ps_shade'] })
  store.push({
    type: 'mechanism_state', seq: 1, ts: base,
    states: { ps_shade: { commanded: true, confirmed: false, source: 'feedback' } },
  }, base)
  store.pushCommand('ps_shade', true, base + 50)
  let state = store.sample(base + 100).ps_shade
  assert.equal(state.effective, false, '新命令不得覆盖仍新鲜的传感器反馈')
  assert.equal(state.estimated, false)

  store.push({
    type: 'mechanism_state', seq: 2, ts: base + 150,
    states: { ps_shade: { commanded: true, confirmed: null, source: 'feedback' } },
  }, base + 150)
  state = store.sample(base + 150).ps_shade
  assert.equal(state.effective, true, '离开两端传感器时应立即清除旧 confirmed 并回退命令态')
  assert.equal(state.estimated, true)

  state = store.sample(base + 651).ps_shade
  assert.equal(state.effective, true, '反馈陈旧后可回退到命令态，但必须标 estimated')
  assert.equal(state.estimated, true)
  assert.equal(state.stale, true)

  assert.equal(store.push({
    type: 'mechanism_state', seq: 1, ts: base + 700,
    states: { ps_shade: { commanded: true, confirmed: true, source: 'feedback' } },
  }, base + 700), true, '重连后 seq 可重置')
  state = store.sample(base + 700).ps_shade
  assert.equal(state.effective, true)
  assert.equal(state.resynced, true)
})


test('MechanismStateStore 渲染卡顿不得让姿态从实测值退回命令态', () => {
  const base = 1_700_000_000_000
  const store = new MechanismStateStore({ staleMs: 500, knownIds: ['col_lift'] })
  // 现场实况(2026-08-13 实测): 收集升降气缸线圈断电但停在动点 —— 命令态与反馈态刻意不一致。
  // 全机 52 个机构里只有它两者打架, 因此只有它会把"换源"暴露成整程 70mm 的位移。
  store.push({
    type: 'mechanism_state', seq: 1, ts: base,
    states: { col_lift: { commanded: false, confirmed: true, source: 'feedback' } },
  }, base)

  // 主线程卡顿 700ms(GC / 重帧 / 后台标签页节流): 没有新消息, 后端也没说过 confirmed:null
  const state = store.sample(base + 700).col_lift
  assert.equal(state.effective, true, '卡顿不是位移, 姿态必须保持最后一次实测值')
  assert.equal(state.estimated, false, 'confirmed 仍是实测值, 不该标推定')
  assert.equal(state.stale, true, '数据确实旧了, 由 stale 如实告知面板')
})


test('MechanismStateStore 透传在途位 moving, 缺省视同已就位', () => {
  const base = 1_700_000_000_000
  const store = new MechanismStateStore({ staleMs: 500, knownIds: ['rob_flip_suction'] })

  // 发令: 命令已下发、行程未结束。confirmed 仍是 null —— moving 绝不能冒充到位
  store.push({
    type: 'mechanism_state', seq: 1, ts: base,
    states: { rob_flip_suction: { commanded: true, confirmed: null, source: 'commanded', moving: true } },
  }, base)
  let state = store.sample(base + 10).rob_flip_suction
  assert.equal(state.moving, true)
  assert.equal(state.effective, true, 'moving 不参与 effective 的推导')
  assert.equal(state.estimated, true, '在途仍是估计态')

  // 动作返回: 清在途位。dwell 兜底那一路 confirmed 依然是 null, 所以收尾只能靠 moving
  store.push({
    type: 'mechanism_state', seq: 2, ts: base + 900,
    states: { rob_flip_suction: { commanded: true, confirmed: null, source: 'commanded', moving: false } },
  }, base + 900)
  state = store.sample(base + 910).rob_flip_suction
  assert.equal(state.moving, false)

  // 阶段位不粘: 在途中途来一帧不带该键的快照, 必须落回已就位而不是残留 true。
  // 粘住的后果是动画永久钉在终点前 —— 行程中卸刀就会走到这个分支。
  store.push({
    type: 'mechanism_state', seq: 3, ts: base + 1000,
    states: { rob_flip_suction: { commanded: true, confirmed: null, source: 'commanded', moving: true } },
  }, base + 1000)
  assert.equal(store.sample(base + 1010).rob_flip_suction.moving, true)
  store.push({
    type: 'mechanism_state', seq: 4, ts: base + 1100,
    states: { rob_flip_suction: { commanded: true, confirmed: null, source: 'commanded' } },
  }, base + 1100)
  assert.equal(store.sample(base + 1110).rob_flip_suction.moving, false, '缺省必须视同已就位')
})


test('TwinFeed 同时接收三种高频协议并把单点气缸审计仅记为 commanded', () => {
  const feed = new TwinFeed({
    axes: [{ id: 'axis_11y', telemetry: { node: 'plc.rail', key: 'Rail_ActPos' } }],
    stations: [],
    realtime: { mechanisms: [{ id: 'ps_shade' }] },
  })
  const now = Date.now()
  feed.handleEvent({
    type: 'robot_pose', seq: 1, ts: now, joint: [1, 2, 3, 4, 5, 6],
    pose: [0, 0, 0, 0, 0, 0], tool: 2, mode: 7,
  })
  feed.handleEvent({
    type: 'axis_pose', seq: 1, ts: now, positions: { axis_11y: 500 },
    velocities: { axis_11y: 20 },
  })
  feed.handleEvent({
    type: 'mechanism_state', seq: 1, ts: now,
    states: { ps_shade: { commanded: false, confirmed: false, source: 'feedback' } },
  })
  feed.handleEvent({
    type: 'step_done', action: 'manual.cylinder.ps_shade',
    result: { id: 'ps_shade', on: true },
  })

  assert.deepEqual(feed.sampleRobotPose(now).joint, [1, 2, 3, 4, 5, 6])
  assert.equal(feed.sampleAxisPose(now).positions.axis_11y, 500)
  const mechanism = feed.sampleMechanismStates(now).ps_shade
  assert.equal(mechanism.commanded, true)
  assert.equal(mechanism.effective, false, '反馈仍优先')
  assert.equal(feed.mountedTool, 2)
  assert.equal(feed.robotMode, 7)
  const status = feed.realtimeStatus(now)
  assert.equal(status.axes.items[0].position, 500)
  assert.equal(status.axes.items[0].velocity, 20)
  assert.equal(status.mechanisms.items[0].effective, false)
  assert.equal(status.mechanisms.items[0].estimated, false)
})


test('TwinFeed 传输层断连会让三类数据在下一帧统一重新同步', () => {
  const feed = new TwinFeed({
    axes: [{ id: 'axis_11y', telemetry: { node: 'plc.rail', key: 'Rail_ActPos' } }],
    stations: [],
    realtime: { mechanisms: [{ id: 'ps_shade' }] },
  })
  const base = 1_700_000_000_000
  feed.setTransportState(true)
  feed.handleEvent({ type: 'robot_pose', seq: 9, ts: base, joint: [0, 0, 0, 0, 0, 0] })
  feed.handleEvent({ type: 'axis_pose', seq: 9, ts: base, positions: { axis_11y: 10 } })
  feed.handleEvent({
    type: 'mechanism_state', seq: 9, ts: base,
    states: { ps_shade: { commanded: false, confirmed: false } },
  })
  feed.setTransportState(false)
  feed.setTransportState(true)
  feed.handleEvent({ type: 'robot_pose', seq: 1, ts: base + 100, joint: [90, 0, 0, 0, 0, 0] })
  feed.handleEvent({ type: 'axis_pose', seq: 1, ts: base + 100, positions: { axis_11y: 900 } })
  feed.handleEvent({
    type: 'mechanism_state', seq: 1, ts: base + 100,
    states: { ps_shade: { commanded: true, confirmed: true } },
  })

  assert.equal(feed.sampleRobotPose(base + 100).joint[0], 90)
  assert.equal(feed.sampleRobotPose(base + 100).resynced, true)
  assert.equal(feed.sampleAxisPose(base + 100).positions.axis_11y, 900)
  assert.equal(feed.sampleMechanismStates(base + 100).ps_shade.resynced, true)
})
