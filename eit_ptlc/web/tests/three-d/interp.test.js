/**
 * 功能: 插值通道的单元测试. 覆盖首帧就位、与帧率无关的收敛、采样周期自适应、瞬移吸附.
 *
 * 这一层值得单测的原因: 它是"1 Hz 遥测看起来像连续运动"的唯一实现, 一旦收敛
 * 行为出错, 表现是轴运动发飘或滞后, 而这类问题在肉眼验收时很难定位到具体代码。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ARRIVE_FACTOR, clamp, createChannel, push, step } from '../../src/three-d/twin/bindings/interp.js'

// 测试环境没有 performance.now, 用固定时基替代, 保证结果可复现
if (typeof performance === 'undefined') {
  globalThis.performance = { now: () => 0 }
}

test('新建通道初始未就绪, 推进不产生变化', () => {
  const channel = createChannel(0)
  assert.equal(channel.initialized, false)
  assert.equal(step(channel, 0.016), 0)
})

test('首个采样直接就位, 不从初值慢慢爬过去', () => {
  const channel = createChannel(0)
  push(channel, 123.4, 1000)
  assert.equal(channel.value, 123.4)
  assert.equal(channel.target, 123.4)
  assert.equal(channel.initialized, true)
})

test('后续采样只改目标值, 当前值靠推进逼近', () => {
  const channel = createChannel(0)
  push(channel, 0, 1000)
  push(channel, 100, 2000)

  assert.equal(channel.target, 100)
  assert.equal(channel.value, 0)

  step(channel, 0.5)
  assert.ok(channel.value > 0 && channel.value < 100, `中间值应在区间内, 实际 ${channel.value}`)
})

test('收敛速度与帧率无关', () => {
  const makeChannel = () => {
    const channel = createChannel(0)
    push(channel, 0, 1000)
    push(channel, 100, 2000)
    return channel
  }

  // 同样推进 1 秒: 一次 1 秒 vs 60 次 1/60 秒, 结果应几乎一致
  const coarse = makeChannel()
  step(coarse, 1.0)

  const fine = makeChannel()
  for (let i = 0; i < 60; i += 1) step(fine, 1 / 60)

  assert.ok(
    Math.abs(coarse.value - fine.value) < 0.5,
    `帧率不应影响收敛: 粗 ${coarse.value.toFixed(3)} vs 细 ${fine.value.toFixed(3)}`,
  )
})

test('一个采样周期内应基本到位', () => {
  const channel = createChannel(0)
  push(channel, 0, 1000)
  push(channel, 100, 2000) // 采样周期估计为 1 秒

  // 推进 ARRIVE_FACTOR 个周期后, 误差应衰减到 1/e 以内
  for (let i = 0; i < 100; i += 1) step(channel, (ARRIVE_FACTOR * 1.0) / 100)
  assert.ok(channel.value > 60, `一个追赶周期后应接近目标, 实际 ${channel.value.toFixed(2)}`)
})

test('采样周期自适应: 加快采样后收敛也加快', () => {
  const slow = createChannel(0)
  push(slow, 0, 0)
  push(slow, 100, 1000) // 1 Hz

  const fast = createChannel(0)
  push(fast, 0, 0)
  push(fast, 0, 200)
  push(fast, 0, 400)
  push(fast, 100, 600) // 约 5 Hz

  assert.ok(fast.period < slow.period, `高频采样的周期估计应更小: ${fast.period} vs ${slow.period}`)

  step(slow, 0.1)
  step(fast, 0.1)
  assert.ok(fast.value > slow.value, '同样推进 0.1s, 高频通道应更接近目标')
})

test('超过阈值的跳变直接吸附, 不做插值', () => {
  const channel = createChannel(0)
  push(channel, 0, 1000)
  push(channel, 3000, 2000)

  step(channel, 0.016, 100) // 阈值 100, 差值 3000 -> 直接到位
  assert.equal(channel.value, 3000)
})

test('异常采样被忽略, 不污染通道', () => {
  const channel = createChannel(0)
  push(channel, 50, 1000)
  push(channel, Number.NaN, 2000)
  push(channel, Number.POSITIVE_INFINITY, 3000)
  assert.equal(channel.target, 50)
})

test('超长采样间隔不污染周期估计', () => {
  const channel = createChannel(0)
  push(channel, 0, 0)
  push(channel, 10, 1000)
  const before = channel.period
  // 页面切到后台再回来会产生几十秒的间隔, 不应被采纳
  push(channel, 20, 61000)
  assert.equal(channel.period, before)
})

test('clamp 正确钳制区间', () => {
  assert.equal(clamp(5, 0, 10), 5)
  assert.equal(clamp(-1, 0, 10), 0)
  assert.equal(clamp(99, 0, 10), 10)
})
