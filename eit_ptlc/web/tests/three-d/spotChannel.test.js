/**
 * 功能: 点样色带 `spot` 连续通道 —— 编译、多条带求值、region 透传与播放器分发.
 *
 * 钉住三个设计决定(与 scrapeChannel 同一族):
 *   1. 通道值是 t 的纯函数 —— 拖进度条到任意时刻直接算得出, 不依赖"回家重放";
 *   2. band 号 1 起数、**各自成通道**: 多样品多条带各自渐现, 单通道表达不了
 *      "第 1 条带已满、第 2 条带正在扫"的并存;
 *   3. 条带矩形不进通道值: 几何住 compiled.spotRegions(板 cm 帧, 与
 *      controller/plate_coords.py 同帧), 播放器只按 id 透传, 换算留到写入层。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ClipPlayer } from '../../src/three-d/anim/ClipPlayer.js'
import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'

/** 标称点样带(与 clip_compiler.SPOT_BAND_CALIB 产物同形, 数值无需一致)。 */
const REGION = {
  frame: 'plate-cm',
  plateSizeCm: [20, 20],
  bands: [{ bandCm: [1.6, 2.3, 18.6, 3.2], fill: { axis: 'x', dir: 1 } }],
  machine: { xAxis: 'axis_6x', yAxis: 'axis_7y', xDir: 1, yDir: 1 },
}

/** 一段"7Y 落位 → 6X 到起点 → 扫线点样"的最小片段(与 emit_spot 产物同形)。 */
function spotClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'spot_demo',
    steps: [
      { label: '7Y 落位', dur: 1, do: { wait: {} } },
      { label: '6X 到起点', dur: 1, do: { wait: {} } },
      { label: '扫线点样', dur: 4, ease: 'linear', do: { spot: { id: 'plate', band: 1, to: 1 } } },
    ],
    compiled: { spotRegions: { plate: REGION } },
  }
}

test('spot 是连续通道: 编译进 channels 而不是 events, band 号进通道键', () => {
  const clip = compileClip(spotClip())
  assert.equal(clip.events.length, 0, '点样色带不该产生离散事件')
  assert.ok(clip.channels.has('spot:plate:band1'))
})

test('渐现进度按关键帧插值, 任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(spotClip())
  const at = (t) => evaluateChannels(clip, t).spots.plate

  assert.deepEqual(at(0), { 1: 0 }, '起点恒为净板(不设 home 段)')
  assert.deepEqual(at(1.5), { 1: 0 }, '就位期间色带不动(from_t 保持帧)')
  assert.ok(Math.abs(at(4)[1] - 0.5) < 1e-9, '扫线中程渐现到一半')
  assert.equal(at(6)[1], 1, '扫完保持 1')
  assert.equal(at(99)[1], 1, '末帧之后保持终值(润洗轮重点同带不再发步)')
})

test('多条带各自成通道、各自渐现', () => {
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'multi',
    steps: [
      { label: '带1', dur: 2, ease: 'linear', do: { spot: { id: 'plate', band: 1, to: 1 } } },
      { label: '带2', dur: 2, ease: 'linear', do: { spot: { id: 'plate', band: 2, to: 1 } } },
    ],
  })
  const mid = evaluateChannels(clip, 3).spots.plate
  assert.equal(mid[1], 1, '第 1 条带已满')
  assert.ok(Math.abs(mid[2] - 0.5) < 1e-9, '第 2 条带正在扫')
})

test('spotRegions 从片段 compiled 块透传到编译产物', () => {
  const clip = compileClip(spotClip())
  assert.deepEqual(clip.spotRegions, { plate: REGION })
  const bare = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bare',
    steps: [{ label: 's', dur: 1, do: { spot: { id: 'plate', to: 1 } } }],
  })
  assert.equal(bare.spotRegions, null)
})

test('spot 缺 id/to、band 非法、进度越界都在编译期报错; band 缺省为 1', () => {
  const build = (body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { spot: body } }],
  })
  assert.throws(build({ to: 1 }), /缺 id\/to/)
  assert.throws(build({ id: 'plate' }), /缺 id\/to/)
  assert.throws(build({ id: 'plate', band: 0, to: 1 }), /≥1 的整数条带号/)
  assert.throws(build({ id: 'plate', band: 1.5, to: 1 }), /≥1 的整数条带号/)
  assert.throws(build({ id: 'plate', to: 1.2 }), /0\.\.1 的进度/)
  assert.throws(build({ id: 'plate', to: -0.1 }), /0\.\.1 的进度/)
  // band 缺省 = 1(单带流程不必写 band)
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'default-band',
    steps: [{ label: 's', dur: 1, do: { spot: { id: 'plate', to: 1 } } }],
  })
  assert.ok(clip.channels.has('spot:plate:band1'))
})

/** 只带 spot 分发所需方法的最小 rig(记录每次 setSpot 的入参)。 */
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
    setSpot(id, fills, region) { calls.push({ id, fills: { ...fills }, region }) },
  }
}

test('ClipPlayer 把 fills 与 region 一起发给 rig.setSpot(连续分发)', () => {
  const rig = stubRig()
  const player = new ClipPlayer({ rig })
  player.load(compileClip(spotClip()))

  player.seek(4)
  const mid = rig.calls[rig.calls.length - 1]
  assert.equal(mid.id, 'plate')
  assert.ok(Math.abs(mid.fills[1] - 0.5) < 1e-9)
  assert.deepEqual(mid.region, REGION, '条带几何按 id 从 compiled.spotRegions 取')

  // 向后 seek(回家重放)后同一 t 的分发值逐位一致 —— seek 契约在分发层同样成立
  player.seek(0)
  player.seek(4)
  assert.deepEqual(rig.calls[rig.calls.length - 1], mid)
})
