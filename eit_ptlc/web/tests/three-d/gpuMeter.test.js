/**
 * 功能: GpuMeter 纯逻辑件的单元测试 —— 中位数/滚动窗口/增量测量状态机/CPU 退化通道.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { median, RollingStat, DeltaProbe, GpuMeter } from '../../src/three-d/twin/scene/GpuMeter.js'

test('median: 奇偶与空', () => {
  assert.equal(median([3, 1, 2]), 2)
  assert.equal(median([4, 1, 3, 2]), 2.5)
  assert.equal(median([]), null)
  assert.equal(median(null), null)
})

test('RollingStat: 淘汰最旧、忽略非有限值', () => {
  const stat = new RollingStat(3)
  stat.push(1)
  stat.push(NaN)
  stat.push(2)
  stat.push(3)
  stat.push(4) // 挤掉 1
  assert.equal(stat.size, 3)
  assert.equal(stat.median(), 3)
  stat.reset()
  assert.equal(stat.size, 0)
  assert.equal(stat.median(), null)
})

test('DeltaProbe: settle 丢样 -> sampling 收样 -> done 出差值', () => {
  let clock = 0
  const probe = new DeltaProbe({ settleMs: 300, sampleMs: 700, now: () => clock })
  probe.start(10)

  clock = 100
  assert.equal(probe.tick(99).phase, 'settle', 'settle 相样本必须被丢弃')

  clock = 400
  assert.equal(probe.tick(12).phase, 'sampling')
  clock = 600
  assert.equal(probe.tick(14).phase, 'sampling')
  clock = 800
  probe.tick(null) // null 样本只推进时间
  assert.equal(probe.samples.length, 2)

  clock = 1001
  const done = probe.tick(999) // 超时帧的样本不再计入
  assert.equal(done.phase, 'done')
  assert.equal(done.afterMedian, 13)
  assert.equal(done.deltaMs, 3)

  assert.equal(probe.tick(1).phase, 'done', 'done 后不再变化')
})

test('DeltaProbe: 无样本时 done 给 null; abort 后不再推进', () => {
  let clock = 0
  const probe = new DeltaProbe({ settleMs: 10, sampleMs: 10, now: () => clock })
  probe.start(5)
  clock = 100
  const done = probe.tick(null)
  assert.equal(done.phase, 'done')
  assert.equal(done.deltaMs, null)

  const probe2 = new DeltaProbe({ now: () => 0 })
  probe2.start(1)
  probe2.abort()
  assert.equal(probe2.tick(3).phase, 'aborted')
})

test('GpuMeter: 无 gl 时退化为纯 CPU 通道且不抛错', () => {
  const meter = new GpuMeter(null)
  assert.equal(meter.gpuAvailable, false)
  meter.beginFrame()
  meter.endFrame()
  const snap = meter.snapshot()
  assert.equal(snap.gpuMs, null)
  assert.equal(snap.gpuAvailable, false)
  assert.equal(snap.samples, 1)
  assert.ok(Number.isFinite(snap.frameMs) && snap.frameMs >= 0)
  meter.reset()
  assert.equal(meter.snapshot().samples, 0)
  meter.dispose()
})

test('GpuMeter: endFrame 未配对 beginFrame 时安全跳过', () => {
  const meter = new GpuMeter(null)
  meter.endFrame()
  assert.equal(meter.snapshot().samples, 0)
})
