/**
 * 功能: 回放传输层 —— seek 的清场顺序、按播放头节流投喂、过期预取的丢弃。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ReplayChannel } from '../../src/three-d/replay/replayChannel.js'

const T0 = 1786000000

/** 造一份可控的录像 API 替身。 */
function makeApi({ t0 = T0, t1 = T0 + 60, onFrames = null, history = null } = {}) {
  const calls = { stateAt: [], frames: [], history: [] }
  return {
    calls,
    recordingCoverage: async () => ({ t0, t1, chunks: 6, bytes: 1234 }),
    recordingHistory: async (params) => {
      calls.history.push(params)
      return history || { t: params.t, session_id: 's1', events: [], truncated: false }
    },
    recordingStateAt: async (params) => {
      calls.stateAt.push(params)
      return {
        t: params.t,
        state: {
          axes: { axis_1z: { position: 42, velocity: 0 } },
          mechanisms: { v1: { commanded: true, confirmed: null, source: 'feedback' } },
          mountedTool: 2,
          gripHolding: { rob_grip_vial: true },
          streams: { axis_pose: { 'axis_1z.position': 43.5 } },
        },
      }
    },
    recordingFrames: async (params) => {
      calls.frames.push(params)
      if (onFrames) return onFrames(params)
      const ts = []
      for (let t = params.t0; t < params.t1; t += 1) ts.push(t)
      return {
        t0: params.t0,
        t1: params.t1,
        keyframe: {},
        streams: {
          axis_pose: {
            ts,
            channels: { 'axis_1z.position': ts.map((t) => 100 + (t - T0)) },
          },
        },
        events: [],
        truncated: false,
      }
    },
  }
}

test('open 拉取区间并把播放头停在起点', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  assert.equal(await channel.open(), true)
  assert.equal(channel.clock.t0, T0)
  assert.equal(channel.clock.playhead, T0)
})

test('seek 把种子暂存而不是直接投 —— 顺序不再取决于 await 是否让出一帧', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  const emitted = []
  channel.onEvent((event) => emitted.push(event.type))
  await channel.open()

  assert.deepEqual(emitted, [],
    'seek 期间一条都不该投: 清场在下一个 rAF, 直接投就会被抹掉(低帧率下必然发生)')
  assert.ok(channel.pendingSeed, '种子应暂存等宿主在清场同一帧里落地')
  assert.equal(channel.pendingSeed.token, channel.resetToken, '种子必须与本次清场配对')
  const types = channel.pendingSeed.events.map((e) => e.type)
  assert.ok(types.includes('axis_pose') && types.includes('mechanism_state'))
})

test('seek 自增 resetToken 并交出需要直接写入的标量', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  const token = channel.resetToken
  assert.deepEqual(channel.pendingSeed.scalars.gripHolding, { rob_grip_vial: true })
  assert.equal(channel.pendingSeed.scalars.mountedTool, 2)
  await channel.seek(T0 + 30)
  assert.equal(channel.resetToken, token + 1)
})

test('关键帧带上块内已推进到 t 的流末值, 而不是停在块首', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  const axis = channel.pendingSeed.events.filter((e) => e.type === 'axis_pose')
  assert.equal(axis[axis.length - 1].positions.axis_1z, 43.5, '应落在 t 时刻的值')
})

test('tick 按播放头节流投喂, 不整批灌', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  const got = []
  channel.onEvent((event) => { if (event.type === 'axis_pose') got.push(event.ts) })

  channel.play()
  channel.tick(3.0)              // 播放头推进 3 秒
  assert.ok(got.length > 0 && got.length <= 5,
    `只应投喂到期的几条, 实际 ${got.length}`)
  assert.ok(Math.max(...got) <= channel.clock.playhead)

  const before = got.length
  channel.tick(3.0)
  assert.ok(got.length > before, '继续推进应继续投喂')
})

test('暂停时 tick 不投喂', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  const got = []
  channel.onEvent((event) => { if (event.type === 'axis_pose') got.push(event) })
  channel.pause()
  channel.tick(5)
  assert.equal(got.length, 0)
})

test('倍速下播放头前进更快', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  channel.play()
  channel.setSpeed(4)
  channel.tick(2)
  assert.equal(channel.clock.playhead, T0 + 8)
})

test('过期预取被丢弃 —— 慢请求回来时若已 seek 过, 不能污染新时间线', async () => {
  // 注意: open()/seek() 都会 await 预取, 所以不能去挂住它们自己发起的那一次,
  // 否则测试自己就死锁了。这里等 open 完成后, 再让"播放中触发的那次预取"挂住。
  const api = makeApi()
  const channel = new ReplayChannel({ api })
  await channel.open()

  let release
  const gate = new Promise((resolve) => { release = resolve })
  api.recordingFrames = async () => {
    await gate
    return {
      streams: { axis_pose: { ts: [T0 + 1], channels: { 'stale.position': [999] } } },
      events: [],
    }
  }

  const slow = channel._prefetch()          // 播放中触发的预取, 被挂住
  await channel.seek(T0 + 40)               // 期间时间线切换
  release()
  await slow

  const stale = channel._pending.some((event) => event.positions?.stale !== undefined)
  assert.equal(stale, false, '旧时间线的数据必须丢弃')
})

test('截断被如实上报, 不静默', async () => {
  const api = makeApi({
    onFrames: async () => ({ streams: {}, events: [], truncated: true }),
  })
  const channel = new ReplayChannel({ api })
  await channel.open()
  assert.match(channel.snapshot().lastError, /截断/)
})

test('没有录像时 open 返回 false 并给出原因', async () => {
  const api = makeApi()
  api.recordingCoverage = async () => ({ t0: null, t1: null, chunks: 0, bytes: 0 })
  const channel = new ReplayChannel({ api })
  assert.equal(await channel.open(), false)
  assert.match(channel.snapshot().lastError, /没有可回放的录像/)
})

test('now() 出的是绝对纪元毫秒, 可直接注入 TwinFeed.now', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  assert.ok(channel.now() > 1e12)
  assert.equal(channel.now(), T0 * 1000)
})

test('state_at 失败时 open 返回 false 且不进入回放态', async () => {
  const api = makeApi()
  api.recordingStateAt = async () => { throw new Error('Request failed with status code 500') }
  const channel = new ReplayChannel({ api })
  assert.equal(await channel.open(), false, 'seek 失败必须往上传')
  assert.equal(channel.active, false, '不能停在"按钮变了但一帧数据都没有"的半死状态')
  assert.match(channel.snapshot().lastError, /快照读取失败/)
})

test('后端报了缺块时给出可执行的下一步, 而不是甩一句英文', async () => {
  const api = makeApi({
    onFrames: async () => ({ streams: {}, events: [], truncated: false, skipped: 3 }),
  })
  const channel = new ReplayChannel({ api })
  await channel.open()
  const msg = channel.snapshot().lastError
  assert.match(msg, /缺失 3 块/)
  assert.match(msg, /reconcile/, '要告诉用户怎么修')
})

// ── 拖动擦洗 (以及它暴露出来的两个老缺陷) ──────────────────────────

test('乱序 state_at: 后到的旧响应不得覆盖新的', async () => {
  // 单击一次时两次 seek 不可能重叠, 所以这道守卫一直没被用到; 拖动时响应必然乱序,
  // 少了它就是"擦洗发黏、随机往回跳", 而且没有任何报错。
  const api = makeApi()
  let gateOld
  const oldPending = new Promise((resolve) => { gateOld = resolve })
  let call = 0
  api.recordingStateAt = async (params) => {
    call += 1
    if (call === 1) {
      await oldPending
      return { t: params.t, state: { axes: { axis_1z: { position: 111 } } } }
    }
    return { t: params.t, state: { axes: { axis_1z: { position: 999 } } } }
  }
  const channel = new ReplayChannel({ api })
  channel.clock.setRange(T0, T0 + 60)
  channel.active = true

  const stale = channel.seek(T0 + 5)     // 第一次(会被挂住)
  await channel.seek(T0 + 40)            // 第二次先返回
  const newSeed = channel.pendingSeed
  gateOld()
  assert.equal(await stale, false, '旧的那次必须自认失效')
  assert.equal(channel.pendingSeed, newSeed, '旧快照不得覆盖新种子')
  assert.equal(channel.pendingSeed.events[0].positions.axis_1z, 999)
})

test('resetToken 不得先于种子自增 —— 这一步是"拖动时疯狂闪初始画面"的根因', async () => {
  // 宿主是靠 resetToken 变化触发清场的: machine.home() 把整机摆回原点、板与托盘全部
  // 释放。token 先自增就等于宣布"清吧", 而种子还在网络上飞(state_at 实测 p50 23 ms,
  // 一帧 16.7 ms) —— 中间那一两帧渲染的就是初始画面。擦洗 60 ms 一次 = 频闪。
  const api = makeApi()
  let release
  const gate = new Promise((resolve) => { release = resolve })
  const inner = api.recordingStateAt
  api.recordingStateAt = async (params) => { await gate; return inner(params) }
  const channel = new ReplayChannel({ api })
  channel.clock.setRange(T0, T0 + 60)
  channel.active = true

  const token = channel.resetToken
  const pending = channel.seek(T0 + 10, { prefetch: false })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(channel.resetToken, token, '快照没到手就自增 = 给宿主开了一个 home 位姿的空窗')
  assert.equal(channel.pendingSeed, null)

  release()
  assert.equal(await pending, true)
  assert.equal(channel.resetToken, token + 1, '拿到快照才允许自增')
  assert.equal(channel.pendingSeed.token, channel.resetToken, '清场与种子必须是同一次')
})

test('endScrub 落一份新种子 —— 松手后画面不能停在 home 位姿', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  channel.clock.scrub(T0 + 30)
  channel.scrubTo(T0 + 20)                 // 向后 -> 预览 seek
  await new Promise((resolve) => setTimeout(resolve, 0))
  channel.pendingSeed = null               // 模拟宿主已把预览那次的种子落了地

  await channel.endScrub()
  assert.ok(channel.pendingSeed, '松手必须带种子: 只自增 token 会让宿主清场后无人播种')
  assert.equal(channel.pendingSeed.token, channel.resetToken)
  assert.equal(channel.previewing, false, '收尾要退出预览态, 否则宿主一直不重建板与托盘')
})

test('派生态历史排在关键帧之前 —— 关键帧是连续量的权威, 必须最后落', async () => {
  const api = makeApi({
    history: {
      session_id: 's1',
      events: [
        { type: 'vm_node_done', ts: T0 - 30, op: 'call', action: 'plate_pick' },
        { type: 'axis_pose', ts: T0 - 30, positions: { axis_1z: 7 } },
      ],
      truncated: false,
    },
  })
  const channel = new ReplayChannel({ api })
  await channel.open()

  const types = channel.pendingSeed.events.map((e) => e.type)
  assert.equal(types[0], 'vm_node_done', '历史在最前')
  const lastAxis = channel.pendingSeed.events.filter((e) => e.type === 'axis_pose').pop()
  assert.equal(lastAxis.positions.axis_1z, 43.5,
    '历史里的旧轴位姿绝不能盖住关键帧的当前位姿')
})

test('擦洗预览不拉派生态历史, 松手才拉', async () => {
  const api = makeApi()
  const channel = new ReplayChannel({ api })
  await channel.open()
  const before = api.calls.history.length

  channel.clock.scrub(T0 + 30)
  channel.scrubTo(T0 + 20)
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(api.calls.history.length, before, '预览态多打一个 RTT 会拖慢拖动手感')

  await channel.endScrub()
  assert.equal(api.calls.history.length, before + 1, '松手必须补上派生态重建')
})

test('历史被截断时如实上墙, 不装作派生态是全的', async () => {
  const api = makeApi({ history: { session_id: 's1', events: [], truncated: true } })
  const channel = new ReplayChannel({ api })
  await channel.open()
  assert.match(channel.snapshot().lastError, /截断/)
})

test('scrubTo: 向前且数据在手 = 零网络的 drain', async () => {
  const api = makeApi()
  const channel = new ReplayChannel({ api })
  await channel.open()
  const before = api.calls.stateAt.length
  const got = []
  channel.onEvent((event) => { if (event.type === 'axis_pose') got.push(event.ts) })

  assert.equal(channel.scrubTo(T0 + 2), 'drain')
  assert.equal(api.calls.stateAt.length, before, 'drain 不该打网络')
  assert.ok(got.length > 0, 'drain 要把到期事件投下去')
  assert.equal(channel.clock.playhead, T0 + 2)
})

test('scrubTo: 向后一律走 seek', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  channel.clock.scrub(T0 + 30)
  assert.equal(channel.scrubTo(T0 + 29), 'queued', '向后必须清场, 不能 drain')
})

test('scrubTo: 单航班 —— 连发 10 个目标只留最后一个', async () => {
  const api = makeApi()
  let inFlight = 0
  let maxInFlight = 0
  const inner = api.recordingStateAt
  api.recordingStateAt = async (params) => {
    inFlight += 1
    maxInFlight = Math.max(maxInFlight, inFlight)
    try { await new Promise((r) => setTimeout(r, 5)); return inner(params) }
    finally { inFlight -= 1 }
  }
  const channel = new ReplayChannel({ api })
  await channel.open()
  channel.clock.scrub(T0 + 50)
  for (let i = 0; i < 10; i += 1) channel.scrubTo(T0 + 40 - i)   // 一路向后
  await channel.endScrub()

  assert.equal(maxInFlight, 1, '任何时刻只许一个在飞, 否则慢链路上会堆积')
  assert.ok(api.calls.stateAt.length < 10, `不该每个目标都发一次, 实际 ${api.calls.stateAt.length}`)
})

test('effectiveRate: 擦洗时不为 1 也不为 0', async () => {
  const channel = new ReplayChannel({ api: makeApi() })
  await channel.open()
  assert.equal(channel.effectiveRate(), 1, '未擦洗且暂停时就是 1')
  channel._scrubQueued = T0 + 1
  const rate = channel.effectiveRate(0, 0.016)
  assert.ok(rate >= 4, '为 0 会让 interp 停摆, 姿态永远收敛不到播种值')
  assert.ok(rate <= 16, '为 1 会让泵/液位积分器与事件流脱节')
  channel._scrubQueued = null
})
