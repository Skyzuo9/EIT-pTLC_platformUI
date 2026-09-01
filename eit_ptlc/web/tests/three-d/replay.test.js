/**
 * 功能: 状态录像回放的三块地基 —— 列式帧还原、播放头语义、向后 seek 的清场。
 *
 * 这里最要紧的是最后一组: MechanismStateStore 的逐机构时间戳闸门与两个位姿缓冲区的
 * 到达时刻锁存, 都会让向后 seek **静默失败** —— 关键帧被逐 id 跳过、stale 判定永远
 * 为假、1Hz telemetry 回退被永久压制, 三者都不抛错, 只是画面从此不再说实话。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { framesToEvents, keyframeToSeed } from '../../src/three-d/replay/replayEvents.js'
import { ReplayClock } from '../../src/three-d/replay/ReplayClock.js'
import { AxisPoseBuffer } from '../../src/three-d/twin/bindings/AxisPoseBuffer.js'
import { RobotPoseBuffer } from '../../src/three-d/twin/bindings/RobotPoseBuffer.js'
import { MechanismStateStore } from '../../src/three-d/twin/bindings/MechanismStateStore.js'

const T0 = 1786000000 // 绝对纪元秒 —— stampMs 按 <1e12 判秒, 相对时间会被误判

// -- 列式帧 -> 线上同构事件 -------------------------------------------------

test('列式帧还原成与实时逐字同构的 axis_pose', () => {
  const events = framesToEvents({
    streams: {
      axis_pose: {
        ts: [T0, T0 + 0.05],
        channels: {
          'axis_1z.position': [10.0, 10.5],
          'axis_1z.velocity': [0, 10],
          'axis_9x.position': [200.0, 201.0],
        },
      },
    },
  })
  assert.equal(events.length, 2)
  assert.deepEqual(events[0], {
    type: 'axis_pose',
    ts: T0,
    positions: { axis_1z: 10.0, axis_9x: 200.0 },
    velocities: { axis_1z: 0 },
  })
  assert.equal(events[1].positions.axis_9x, 201.0)
})

test('还原出的事件能被 AxisPoseBuffer 直接吃下', () => {
  const buffer = new AxisPoseBuffer()
  const events = framesToEvents({
    streams: {
      axis_pose: {
        ts: [T0, T0 + 0.05, T0 + 0.1],
        channels: { 'axis_1z.position': [10, 11, 12] },
      },
    },
  })
  const nowMs = (T0 + 0.1) * 1000
  for (const event of events) assert.equal(buffer.push(event, nowMs), true)
  const sampled = buffer.sample(nowMs)
  assert.ok(Number.isFinite(sampled.positions.axis_1z))
})

test('机构三态 null 必须原样穿过, 不能被当成缺帧滤掉', () => {
  const events = framesToEvents({
    streams: {
      mechanism_state: {
        ts: [T0],
        channels: {
          'dev_v1.commanded': [true],
          'dev_v1.confirmed': [null],  // 两个到位信号都不成立 = 运动途中
          'dev_v1.source': ['feedback'],
        },
      },
    },
  })
  assert.equal(events.length, 1)
  assert.deepEqual(events[0].states.dev_v1,
    { commanded: true, confirmed: null, source: 'feedback' })
})

test('robot_pose 半截帧不产出 (缺关节的帧会被 buffer 静默丢弃)', () => {
  const events = framesToEvents({
    streams: {
      robot_pose: {
        ts: [T0, T0 + 0.02],
        channels: {
          joint0: [1, 1], joint1: [2, 2], joint2: [3, 3],
          joint3: [4, 4], joint4: [5, 5], joint5: [6, null],
          pose_xyz0: [10, 10], pose_xyz1: [20, 20], pose_xyz2: [30, 30],
          pose_rpy0: [0, 0], pose_rpy1: [0, 0], pose_rpy2: [0, 0],
          tool: [1, 1],
        },
      },
    },
  })
  assert.equal(events.length, 1, '缺关节的那帧不应产出')
  assert.deepEqual(events[0].joint, [1, 2, 3, 4, 5, 6])
  assert.deepEqual(events[0].pose, [10, 20, 30, 0, 0, 0])
  assert.equal(events[0].tool, 1)
})

test('低频事件原样合并并按时间排序', () => {
  const events = framesToEvents({
    streams: { axis_pose: { ts: [T0 + 1], channels: { 'a.position': [1] } } },
    events: [
      { type: 'vm_node_enter', ts: T0, aid: 'a1', args: { action: 'gripper-close' } },
      { type: 'scrape_state', ts: T0 + 2, phase: 'pass' },
    ],
  })
  assert.deepEqual(events.map((e) => e.type),
    ['vm_node_enter', 'axis_pose', 'scrape_state'])
  assert.deepEqual(events[0].args, { action: 'gripper-close' }, 'enter 的 args 是唯一来源, 不可丢')
})

// -- 关键帧 -> 播种 ---------------------------------------------------------

test('关键帧还原出整份机构记录而非最后一条部分快照', () => {
  const { events, scalars } = keyframeToSeed({
    axes: { axis_1z: { position: 5, velocity: 0 } },
    robot: { joint: [1, 2, 3, 4, 5, 6], pose: [0, 0, 0, 0, 0, 0], tool: 2, mode: 5 },
    mechanisms: { v1: { commanded: true, confirmed: null, source: 'feedback' } },
    signalLight: { red: false, green: true, mode: 3 },
    materialState: { cells: { a: 1 } },
    mountedTool: 2,
    gripHolding: { rob_grip_vial: true },
  }, T0)

  const byType = Object.fromEntries(events.map((e) => [e.type, e]))
  assert.equal(byType.axis_pose.positions.axis_1z, 5)
  assert.equal(byType.robot_pose.tool, 2)
  assert.deepEqual(byType.mechanism_state.states.v1,
    { commanded: true, confirmed: null, source: 'feedback' })
  assert.equal(byType.signal_light.green, true)
  assert.equal(byType.material_state.initial, true, '需要 initial 才能越过倒退闸门')
  assert.equal(scalars.mountedTool, 2)
  assert.deepEqual(scalars.gripHolding, { rob_grip_vial: true })
})

// -- 播放头 -----------------------------------------------------------------

test('倍速: 墙钟前进量 × 倍速 = 录像前进量', () => {
  const clock = new ReplayClock({ t0: T0, t1: T0 + 100 })
  clock.play()
  clock.advance(1)
  assert.equal(clock.playhead, T0 + 1)
  clock.setSpeed(4)
  clock.advance(1)
  assert.equal(clock.playhead, T0 + 5)
  clock.setSpeed(0.25)
  clock.advance(2)
  assert.equal(clock.playhead, T0 + 5.5)
})

test('nowMs 是绝对纪元毫秒 (0 基会让采样器永远钳在第一帧)', () => {
  const clock = new ReplayClock({ t0: T0, t1: T0 + 10 })
  assert.ok(clock.nowMs() > 1e12, 'nowMs 必须落在纪元毫秒量级')
  assert.equal(clock.nowMs(), T0 * 1000)
})

test('seek 一律自增 epoch —— 向前跳也必须清场', () => {
  const clock = new ReplayClock({ t0: T0, t1: T0 + 100 })
  const before = clock.epoch
  clock.seek(T0 + 50)
  assert.equal(clock.epoch, before + 1)
  clock.seek(T0 + 60)
  assert.equal(clock.epoch, before + 2, '向前跳同样跨过了未喂入的事件')
})

test('seek 钳在可用区间内; 播到末尾停住且不算跳转', () => {
  const clock = new ReplayClock({ t0: T0, t1: T0 + 10 })
  assert.equal(clock.seek(T0 - 999), T0)
  assert.equal(clock.seek(T0 + 999), T0 + 10)
  clock.seek(T0 + 9)
  const epoch = clock.epoch
  clock.play()
  clock.advance(5)
  assert.equal(clock.playhead, T0 + 10)
  assert.equal(clock.playing, false, '到末尾应停住而不是绕回')
  assert.equal(clock.epoch, epoch, '连续到达末尾不是跳转, 不应自增 epoch')
})

test('暂停时不前进; 非法倍速被忽略', () => {
  const clock = new ReplayClock({ t0: T0, t1: T0 + 10 })
  clock.advance(5)
  assert.equal(clock.playhead, T0)
  clock.play()
  clock.setSpeed(0)
  clock.setSpeed(-2)
  clock.setSpeed(NaN)
  clock.advance(1)
  assert.equal(clock.playhead, T0 + 1, '非法倍速应保持原值 1')
})

// -- 向后 seek 的清场 (两个会静默失败的洞) ----------------------------------

test('洞1: 机构时间戳闸门 —— 不 reset 则关键帧被逐 id 静默丢弃', () => {
  const store = new MechanismStateStore()
  const late = (T0 + 100) * 1000
  store.push({ type: 'mechanism_state', ts: T0 + 100, states: { v1: { commanded: true } } }, late)

  // 向后跳: 喂一条更早的机构快照
  const early = { type: 'mechanism_state', ts: T0 + 1, states: { v1: { commanded: false } } }

  store.markDisconnected()   // 现状: 只标记, 清不掉 states[].ts
  store.push(early, (T0 + 1) * 1000)
  assert.equal(store.sample((T0 + 1) * 1000).v1.effective, true,
    '闸门确实会吃掉更早的快照 —— 这正是必须 reset 的原因')

  store.reset()
  store.push(early, (T0 + 1) * 1000)
  assert.equal(store.sample((T0 + 1) * 1000).v1.effective, false,
    'reset 之后关键帧必须生效')
})

test('洞2: 位姿缓冲区的到达时刻锁存 —— 不 reset 则 stale 永远判假', () => {
  const buffer = new AxisPoseBuffer()
  const late = (T0 + 100) * 1000
  buffer.push({ type: 'axis_pose', ts: T0 + 100, positions: { axis_1z: 50 } }, late)

  // 向后跳到 T0+1: 现在时刻比 lastArrival 小, 差值为负
  const early = (T0 + 1) * 1000
  buffer.markDisconnected()
  assert.equal(buffer.sample(early).stale.axis_1z, false,
    '负的时间差让 stale 恒为假 —— 这正是必须 reset 的原因')

  buffer.reset()
  assert.equal(buffer.frames.length, 0)
  assert.equal(buffer.lastArrivalByAxis.size, 0, 'reset 必须清掉单调累加的到达时刻')
  buffer.push({ type: 'axis_pose', ts: T0 + 1, positions: { axis_1z: 5 } }, early)
  const sampled = buffer.sample(early)
  assert.equal(sampled.stale.axis_1z, false)
  assert.ok(Math.abs(sampled.positions.axis_1z - 5) < 1e-6, '应取到关键帧的位置')
})

test('RobotPoseBuffer.reset 清掉全部单调量', () => {
  const buffer = new RobotPoseBuffer()
  const joint = [1, 2, 3, 4, 5, 6]
  buffer.push({ type: 'robot_pose', ts: T0 + 100, joint, pose: [0, 0, 0, 0, 0, 0], seq: 9 },
    (T0 + 100) * 1000)
  assert.ok(buffer.lastArrival > 0)

  buffer.reset()
  assert.equal(buffer.frames.length, 0)
  assert.equal(buffer.lastArrival, 0)
  assert.equal(buffer.lastHighRateArrival, 0)
  assert.equal(buffer.lastSequence, -1, 'seq 去重表不清会误杀回放帧')

  // 复位后同一个 seq 必须能重新被接受
  assert.equal(
    buffer.push({ type: 'robot_pose', ts: T0 + 1, joint, pose: [0, 0, 0, 0, 0, 0], seq: 9 },
      (T0 + 1) * 1000),
    true)
})
