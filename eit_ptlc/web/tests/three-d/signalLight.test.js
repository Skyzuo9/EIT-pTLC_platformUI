import test from 'node:test'
import assert from 'node:assert/strict'

import { SignalLightStore } from '../../src/three-d/twin/bindings/SignalLightStore.js'
import { TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'


test('SignalLightStore 按红>黄>绿优先级取色, 全灭为 off, 未收帧为 null', () => {
  const base = 1_700_000_000_000
  const store = new SignalLightStore({ staleMs: 3000 })

  const empty = store.sample(base)
  assert.equal(empty.received, false, '从未收帧时 received 必须为 false(绑定层据此保持烘焙色)')
  assert.equal(empty.active, null)
  assert.equal(empty.stale, false)

  store.push({ type: 'signal_light', red: false, yellow: false, green: true, ts: base, seq: 1 }, base)
  assert.equal(store.sample(base).active, 'green')

  store.push({ type: 'signal_light', red: false, yellow: true, green: true, ts: base + 100, seq: 2 }, base + 100)
  assert.equal(store.sample(base + 100).active, 'yellow', '黄绿同亮取黄')

  store.push({ type: 'signal_light', red: true, yellow: true, green: false, ts: base + 200, seq: 3 }, base + 200)
  assert.equal(store.sample(base + 200).active, 'red', '红黄同亮取红')

  store.push({ type: 'signal_light', red: false, yellow: false, green: false, ts: base + 300, seq: 4 }, base + 300)
  const sample = store.sample(base + 300)
  assert.equal(sample.active, 'off', '全灭是明确的熄灯态, 不是未知态')
  assert.equal(sample.received, true)
})


test('SignalLightStore 心跳超时与显式断连都转 stale 且保留末态', () => {
  const base = 1_700_000_000_000
  const store = new SignalLightStore({ staleMs: 3000 })
  store.push({ type: 'signal_light', red: true, yellow: false, green: false, ts: base, seq: 1 }, base)

  assert.equal(store.sample(base + 2999).stale, false)
  const timedOut = store.sample(base + 3001)
  assert.equal(timedOut.stale, true, '3 个 1s 心跳丢失即判 stale')
  assert.equal(timedOut.red, true, 'stale 保留末态布尔, 供 HUD 显示最后已知灯态')

  store.markDisconnected()
  const disconnected = store.sample(base + 100)
  assert.equal(disconnected.stale, true, '显式断连立即 stale, 不等超时')
  assert.equal(disconnected.received, true)
  assert.equal(disconnected.active, 'red')
})


test('SignalLightStore 丢弃回退帧, 但断流/断连后允许上位机重启导致的 ts/seq 重置', () => {
  const base = 1_700_000_000_000
  const store = new SignalLightStore({ staleMs: 3000 })
  store.push({ type: 'signal_light', red: false, yellow: false, green: true, ts: base + 500, seq: 5 }, base + 500)

  assert.equal(
    store.push({ type: 'signal_light', red: true, yellow: false, green: false, ts: base + 400, seq: 6 }, base + 600),
    false, '正常连接中 ts 回退帧必须丢弃',
  )
  assert.equal(
    store.push({ type: 'signal_light', red: true, yellow: false, green: false, ts: base + 500, seq: 5 }, base + 600),
    false, '同 ts 同 seq 的重复帧必须丢弃',
  )
  assert.equal(store.sample(base + 600).active, 'green')

  assert.equal(
    store.push({ type: 'signal_light', red: true, yellow: false, green: false, ts: base - 10_000, seq: 1 }, base + 9000),
    true, '到达间隔超过 staleMs 视为重连, 接受 ts/seq 重置',
  )
  assert.equal(store.sample(base + 9000).active, 'red')

  store.markDisconnected()
  assert.equal(
    store.push({ type: 'signal_light', red: false, yellow: true, green: false, ts: base - 20_000, seq: 1 }, base + 9100),
    true, '显式断连后的首帧同样允许重置',
  )
  const sample = store.sample(base + 9100)
  assert.equal(sample.active, 'yellow')
  assert.equal(sample.stale, false, '重连首帧后立即恢复新鲜')
})


test('SignalLightStore 透传 flash/mode, 缺省时回退 false/null(旧事件兼容)', () => {
  const base = 1_700_000_000_000
  const store = new SignalLightStore({ staleMs: 3000 })

  store.push({ type: 'signal_light', red: true, yellow: false, green: false, flash: true, mode: 2, ts: base, seq: 1 }, base)
  let sample = store.sample(base)
  assert.equal(sample.flash, true, '故障红闪帧必须带 flash')
  assert.equal(sample.mode, 2, 'MODE_State 原始码透传给 HUD')
  assert.equal(sample.active, 'red')

  store.push({ type: 'signal_light', red: false, yellow: false, green: true, ts: base + 100, seq: 2 }, base + 100)
  sample = store.sample(base + 100)
  assert.equal(sample.flash, false, '不带 flash 字段的旧事件缺省为不闪')
  assert.equal(sample.mode, null)

  store.push({ type: 'signal_light', red: false, yellow: true, green: false, flash: 'yes', mode: '4', ts: base + 200, seq: 3 }, base + 200)
  sample = store.sample(base + 200)
  assert.equal(sample.flash, false, '非布尔 flash 一律当 false, 不猜')
  assert.equal(sample.mode, null, '非数值 mode 一律当 null')
})


test('SignalLightStore 拒绝缺布尔字段的畸形事件, 蜂鸣器字段可选', () => {
  const base = 1_700_000_000_000
  const store = new SignalLightStore()
  assert.equal(store.push({ type: 'signal_light', red: true, ts: base }, base), false)
  assert.equal(store.push({ type: 'mechanism_state', red: true, yellow: false, green: false }, base), false)

  store.push({ type: 'signal_light', red: false, yellow: false, green: true, buzzer: true, ts: base, seq: 1 }, base)
  assert.equal(store.sample(base).buzzer, true)
  store.push({ type: 'signal_light', red: false, yellow: false, green: true, ts: base + 100, seq: 2 }, base + 100)
  assert.equal(store.sample(base + 100).buzzer, null, '缺蜂鸣器字段时报 null 而不是猜 false')
})


test('TwinFeed 分派 signal_light 事件并在断连时统一标记', () => {
  const feed = new TwinFeed({
    axes: [],
    stations: [],
    realtime: {},
    signalLight: { glbNode: 'ST_FRAME/RYG', staleMs: 3000, styles: {} },
  })
  const now = Date.now()

  assert.equal(feed.sampleSignalLight(now).received, false)

  const before = feed.version
  feed.handleEvent({ type: 'signal_light', red: false, yellow: false, green: true, ts: now / 1000, seq: 1 })
  assert.equal(feed.version, before + 1, '接受帧后 version 自增, 渲染层据此感知变化')
  const sample = feed.sampleSignalLight(now)
  assert.equal(sample.active, 'green', '秒级 ts 需被归一成毫秒后正常采样')
  assert.equal(sample.stale, false)

  assert.equal(feed.realtimeStatus(now).signalLight.active, 'green', 'HUD 诊断走 realtimeStatus 免费获得灯态')

  feed.setTransportState(true)
  feed.setTransportState(false)
  assert.equal(feed.sampleSignalLight(now).stale, true, '传输层断连后塔灯与其余通道一致转 stale')
})
