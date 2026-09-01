/**
 * 功能: 刮取 `scrape` 连续通道 —— 编译、双相位求值、region 透传与播放器分发.
 *
 * 钉住三个设计决定(与 lightChannel/liquidChannel 同一族):
 *   1. 通道值是 t 的纯函数 —— 拖进度条到任意时刻直接算得出, 不依赖"回家重放";
 *   2. loosen(刮松)/clear(收粉)**双通道**而不是单通道+滞后: 真机收集段是刮完后
 *      平移 90mm 再**反向**回扫, 滞后模型表达不了方向反转与平移间歇;
 *   3. 条带矩形不进通道值: 几何住 compiled.scrapeRegions(板 cm 帧, 与
 *      controller/plate_coords.py 同帧), 播放器只按 id 透传, 换算留到写入层。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { ClipPlayer } from '../../src/three-d/anim/ClipPlayer.js'
import { compileClip, evaluateChannels } from '../../src/three-d/anim/clipSchema.js'

/** 演示标称条带(与 clip_compiler.SCRAPE_DEMO_BAND_CM 同形, 数值无需一致)。 */
const REGION = {
  frame: 'plate-cm',
  plateSizeCm: [20, 20],
  bandCm: [2, 8, 18, 10],
  loosen: { axis: 'x', dir: 1 },
  clear: { axis: 'x', dir: -1 },
}

/** 一段"下刀 → 列扫刮松 → 平移 → 收集回扫"的最小片段(与 emit_scrape 产物同形)。 */
function scrapeClip() {
  return {
    schema: 'ptlc.clip/v1',
    name: 'scrape_demo',
    steps: [
      { label: '下刀', dur: 1, do: { wait: {} } },
      { label: '列扫', dur: 4, ease: 'linear', do: { scrape: { id: 'plate', phase: 'loosen', to: 1 } } },
      { label: '平移对桶', dur: 1, do: { wait: {} } },
      { label: '收集回扫', dur: 2, ease: 'linear', do: { scrape: { id: 'plate', phase: 'clear', to: 1 } } },
    ],
    compiled: { scrapeRegions: { plate: REGION } },
  }
}

test('scrape 是连续通道: 编译进 channels 而不是 events, 两相位各自成通道', () => {
  const clip = compileClip(scrapeClip())
  assert.equal(clip.events.length, 0, '刮取不该产生离散事件')
  assert.ok(clip.channels.has('scrape:plate:loosen'))
  assert.ok(clip.channels.has('scrape:plate:clear'))
})

test('双相位按关键帧插值, 任意 t 都是纯函数(seek 安全)', () => {
  const clip = compileClip(scrapeClip())
  const at = (t) => evaluateChannels(clip, t).scrapes.plate

  assert.deepEqual(at(0), { loosen: 0, clear: 0 }, '起点恒为未刮(不设 home 段)')
  assert.deepEqual(at(0.5), { loosen: 0, clear: 0 }, '下刀期间前沿不动(from_t 保持帧)')
  assert.ok(Math.abs(at(3).loosen - 0.5) < 1e-9, '列扫中程 loosen 走到一半')
  assert.equal(at(3).clear, 0, '收集还没开始')
  assert.equal(at(6).loosen, 1, '列扫结束 loosen 保持 1')
  assert.ok(Math.abs(at(7).clear - 0.5) < 1e-9, '收集中程 clear 走到一半')
  assert.deepEqual(at(99), { loosen: 1, clear: 1 }, '末帧之后保持终值')

  for (const t of [0.5, 2, 3.5, 6.5, 7.5]) {
    assert.deepEqual(at(t), at(t), `t=${t} 求值不稳定`)
  }
})

test('scrapeRegions 从片段 compiled 块透传到编译产物', () => {
  const clip = compileClip(scrapeClip())
  assert.deepEqual(clip.scrapeRegions, { plate: REGION })
  // 不带 region 的片段透传 null(播放器随后把 null 发给写入层, 由它静默跳过)
  const bare = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bare',
    steps: [{ label: 's', dur: 1, do: { scrape: { id: 'plate', phase: 'loosen', to: 1 } } }],
  })
  assert.equal(bare.scrapeRegions, null)
})

test('scrape 缺 id/phase/to、相位非法、进度越界都在编译期报错', () => {
  const build = (body) => () => compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bad',
    steps: [{ label: 'x', dur: 1, do: { scrape: body } }],
  })
  assert.throws(build({ phase: 'loosen', to: 1 }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'plate', to: 1 }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'plate', phase: 'loosen' }), /缺 id\/phase\/to/)
  assert.throws(build({ id: 'plate', phase: 'collect', to: 1 }), /必须是 loosen \/ clear \/ pass/)
  assert.throws(build({ id: 'plate', phase: 'loosen', to: 1.2 }), /0\.\.1 的进度/)
  assert.throws(build({ id: 'plate', phase: 'loosen', to: -0.1 }), /0\.\.1 的进度/)
  assert.throws(build({ id: 'plate', phase: 'loosen', to: 'x' }), /0\.\.1 的进度/)
  // pass 相位是**层号**(1 起数的整数), 与两条 0..1 前沿分开校验
  assert.throws(build({ id: 'plate', phase: 'pass', to: 1.5 }), /≥0 的整数层号/)
  assert.throws(build({ id: 'plate', phase: 'pass', to: -1 }), /≥0 的整数层号/)
})

test('分层刮取: pass 相位单独成通道, 老片段(无 pass)按最后一刀处理', () => {
  const clip = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'layered',
    steps: [
      { label: '第1刀收', dur: 1, do: { scrape: { id: 'plate', phase: 'clear', to: 1 } } },
      { label: '落第1层', dur: 1, at: 0, ease: 'step', do: { scrape: { id: 'plate', phase: 'pass', to: 1 } } },
      { label: '第2刀收', dur: 1, do: { scrape: { id: 'plate', phase: 'clear', to: 1 } } },
      { label: '落第2层', dur: 1, at: 1, ease: 'step', do: { scrape: { id: 'plate', phase: 'pass', to: 2 } } },
    ],
  })
  assert.equal(evaluateChannels(clip, 0.5).scrapes.plate.pass, 1)
  assert.equal(evaluateChannels(clip, 1.5).scrapes.plate.pass, 2)

  // 老片段: 只有 loosen/clear 两条通道, pass 必须**缺席**而不是 0 ——
  // 写入层据此认出"分层之前编的", 按 clear 到底即露玻璃处理(residualLevels 的兜底)
  const legacy = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'legacy',
    steps: [{ label: '收', dur: 1, do: { scrape: { id: 'plate', phase: 'clear', to: 1 } } }],
  })
  assert.equal(evaluateChannels(legacy, 1).scrapes.plate.pass, undefined)
})

/** 只带 scrape 分发所需方法的最小 rig(记录每次 setScrape 的入参)。 */
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
    setScrape(id, phases, region) { calls.push({ id, phases: { ...phases }, region }) },
  }
}

test('ClipPlayer 把 scrapes 与 region 一起发给 rig.setScrape(连续分发)', () => {
  const rig = stubRig()
  const player = new ClipPlayer({ rig })
  player.load(compileClip(scrapeClip()))

  player.seek(3)
  const mid = rig.calls[rig.calls.length - 1]
  assert.equal(mid.id, 'plate')
  assert.ok(Math.abs(mid.phases.loosen - 0.5) < 1e-9)
  assert.equal(mid.phases.clear, 0)
  assert.deepEqual(mid.region, REGION, '条带矩形按 id 从 compiled.scrapeRegions 取')

  // 向后 seek(回家重放)后同一 t 的分发值逐位一致 —— seek 契约在分发层同样成立
  player.seek(0)
  player.seek(3)
  const replay = rig.calls[rig.calls.length - 1]
  assert.deepEqual(replay, mid)
})

test('片段没有 region 时照常分发, region 为 null(写入层自行留白)', () => {
  const rig = stubRig()
  const player = new ClipPlayer({ rig })
  player.load(compileClip({
    schema: 'ptlc.clip/v1',
    name: 'bare',
    steps: [{ label: 's', dur: 2, ease: 'linear', do: { scrape: { id: 'plate', phase: 'loosen', to: 1 } } }],
  }))
  player.seek(1)
  const last = rig.calls[rig.calls.length - 1]
  assert.equal(last.region, null)
  assert.ok(Math.abs(last.phases.loosen - 0.5) < 1e-9)
})
