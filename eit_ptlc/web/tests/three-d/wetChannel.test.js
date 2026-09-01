/**
 * 功能: 溶剂润湿 `wet` 连续通道 —— 编译、求值、region 透传与播放器分发.
 *
 * 钉住两个设计决定(与 spotChannel/scrapeChannel 同一族):
 *   1. 通道值是 0..1 的**前沿进度**而不是液位百分比: 展开中没有板面高度真值
 *      (液位视觉给的是 ROI 百分比, 无 cm 映射), 前沿目标高度是编译器的显式演示假设,
 *      放 compiled.wetRegions 不烘进通道 —— 假设改了只动 region, 片段通道不陈旧;
 *   2. 通道值是 t 的纯函数, seek 安全。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ClipPlayer } from '../../src/three-d/anim/ClipPlayer.js'
import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'

/** 润湿区声明(与 clip_compiler 的 wetRegions 产物同形, 数值无需一致)。 */
const REGION = {
  frame: 'plate-cm',
  plateSizeCm: [20, 20],
  bandCm: [0, 0, 20, 14.7],
  fill: { axis: 'y', dir: 1 },
}

/** 一段"注液 → 液位等待(润湿上行)"的最小片段(与 emit_wet 产物同形)。 */
function wetClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'wet_demo',
    steps: [
      { label: '注液', dur: 2, do: { wait: {} } },
      { label: '展开(前沿上行)', dur: 6, ease: 'linear', do: { wet: { id: 'plate', to: 1 } } },
    ],
    compiled: { wetRegions: { plate: REGION } },
  }
}

test('wet 是连续通道: 编译进 channels 而不是 events', () => {
  const clip = compileClip(wetClip())
  assert.equal(clip.events.length, 0)
  assert.ok(clip.channels.has('wet:plate'))
})

test('前沿进度按关键帧插值, 任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(wetClip())
  const at = (t) => evaluateChannels(clip, t).wets.plate

  assert.equal(at(0), 0, '起点恒为干板(不设 home 段)')
  assert.equal(at(1.5), 0, '注液期间前沿不动(from_t 保持帧)')
  assert.ok(Math.abs(at(5) - 0.5) < 1e-9, '展开中程前沿到一半')
  assert.equal(at(8), 1, '展开结束保持 1')
  assert.equal(at(99), 1, '排液后前沿界线仍在(终值保持)')
})

test('wetRegions 从片段 compiled 块透传到编译产物', () => {
  const clip = compileClip(wetClip())
  assert.deepEqual(clip.wetRegions, { plate: REGION })
  const bare = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bare',
    steps: [{ label: 's', dur: 1, do: { wet: { id: 'plate', to: 1 } } }],
  })
  assert.equal(bare.wetRegions, null)
})

test('wet 缺 id/to、进度越界都在编译期报错', () => {
  const build = (body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { wet: body } }],
  })
  assert.throws(build({ to: 1 }), /缺 id\/to/)
  assert.throws(build({ id: 'plate' }), /缺 id\/to/)
  assert.throws(build({ id: 'plate', to: 1.2 }), /0\.\.1 的进度/)
  assert.throws(build({ id: 'plate', to: -0.1 }), /0\.\.1 的进度/)
})

/** 只带 wet 分发所需方法的最小 rig。 */
function stubRig() {
  const calls = []
  return {
    calls,
    joints: [],
    home() {},
    setAxisMm() {},
    setJointsDeg() {},
    setNodeOffset() {},
    setActuator() {},
    setLinkage() {},
    setWet(id, front, region) { calls.push({ id, front, region }) },
  }
}

test('ClipPlayer 把前沿进度与 region 一起发给 rig.setWet(连续分发)', () => {
  const rig = stubRig()
  const player = new ClipPlayer({ rig })
  player.load(compileClip(wetClip()))

  player.seek(5)
  const mid = rig.calls[rig.calls.length - 1]
  assert.equal(mid.id, 'plate')
  assert.ok(Math.abs(mid.front - 0.5) < 1e-9)
  assert.deepEqual(mid.region, REGION)

  player.seek(0)
  player.seek(5)
  assert.deepEqual(rig.calls[rig.calls.length - 1], mid)
})
