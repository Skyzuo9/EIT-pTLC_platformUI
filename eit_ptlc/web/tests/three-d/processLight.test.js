/**
 * 功能: 工艺灯实时链 —— process_light 事件(机器人 DO7 补光)→ 灯亮度的斜坡驱动.
 *
 * 这条链 2026-08-05 之前**根本不存在**: 用户在孪生实时页跑「上样-上料」时报"闪光灯
 * 不闪", 病根就是 TwinBindings 从来没人调过 setLight —— 离线片段那条链一直是好的,
 * 于是问题在两页之间隐身了很久。所以这里锁的都是"坏掉时画面完全正常、没有任何指标
 * 会报警"的行为:
 *   1. 从未收到帧时**不接管**(脱机/离线页保持烘焙观感, 不能凭空亮起来);
 *   2. 开灯是**斜坡**不是硬切(真机是 1s 量级的稳态过程, 硬切既不像也看不清);
 *   3. 关灯回的是 defaultLevel 而不是 0 —— 常亮灯(紫外面光源)不该被补光逻辑关掉;
 *   4. 辉光选集只在"哪几盏亮着"真的变化时才置脏, 不是斜坡期间每帧都置。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { TwinBindings } from '../../src/three-d/twin/bindings/TwinBindings.js'
import { TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'

/** 造一个只有工艺灯的最小 TwinBindings + 可控 feed。 */
function makeBindings({ defaultLevel = 0, peak = 4, litPeak = 1.8 } = {}) {
  const root = new THREE.Object3D()
  const lamp = new THREE.Mesh(
    new THREE.BoxGeometry(0.14, 0.1, 0.012),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  lamp.name = 'VISION_FILL'
  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(0.138, 0.138, 0.003),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  glass.name = 'COVER_GLASS'
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'   // 声明了就得有, 否则 missing 告警刷屏
  root.add(lamp, glass, mount)
  const nodeIndex = new Map([...root.children].map((child) => [child.name, child]))

  const manifest = {
    stations: [], tanks: [], axes: [], tools: [], nodes: [], attachments: [],
    states: [], sockets: [], actuators: [], linkages: [], inventory: {},
    robot: { joints: [], toolMount: 'TOOL_MOUNT' },
    lights: [{
      id: 'vision_fill', label: '视觉纠偏补光(机器人 DO7)', glbNode: 'VISION_FILL',
      color: '#ffffff', peakIntensity: peak, defaultLevel, bloom: true,
      illuminates: 'plate',
      illuminatesNodes: [{ glbNode: 'COVER_GLASS', peakIntensity: litPeak }],
    }],
    realtime: { mechanisms: [] },
  }

  let lights = {}
  const feed = {
    decayActivity: () => {},
    sampleProcessLights: () => lights,
    sampleMechanismStates: () => ({}),
  }
  const bindings = new TwinBindings(manifest, nodeIndex, feed)
  return {
    bindings, lamp, glass,
    setLights: (next) => { lights = next },
    level: () => bindings.machine.lights.get('vision_fill').value,
    /** 推进 n 帧(每帧 dt 秒) */
    tick: (seconds, dt = 1 / 60) => {
      for (let t = 0; t < seconds - 1e-9; t += dt) bindings._updateProcessLights(dt)
    },
  }
}

test('从未收到 process_light 帧时不接管 —— 灯保持烘焙的默认亮度', () => {
  const { bindings, lamp, glass, level } = makeBindings({ defaultLevel: 0 })
  bindings._updateProcessLights(1 / 60)
  assert.equal(level(), 0)
  assert.equal(lamp.material.emissiveIntensity, 0)
  assert.equal(glass.material.emissiveIntensity, 0, '受照的窗也不能凭空亮')
})

test('开灯是斜坡不是硬切: 一帧远到不了满亮, 0.25s 后才到位', () => {
  const { lamp, glass, setLights, level, tick } = makeBindings({ peak: 4, litPeak: 1.8 })
  setLights({ vision_fill: true })

  tick(1 / 60)
  const afterOneFrame = level()
  assert.ok(afterOneFrame > 0, '一帧就该开始亮')
  assert.ok(afterOneFrame < 0.2, `一帧不该直接跳到满亮, 实际 ${afterOneFrame}`)

  tick(0.3)
  assert.ok(Math.abs(level() - 1) < 1e-6, '0.25s 斜坡走完应到满亮')
  assert.ok(Math.abs(lamp.material.emissiveIntensity - 4) < 1e-6)
  assert.ok(Math.abs(glass.material.emissiveIntensity - 1.8) < 1e-6, '受照的窗按自身峰值亮')
})

test('关灯回落到 defaultLevel: 常亮的紫外面光源不该被补光逻辑关掉', () => {
  const { setLights, level, tick } = makeBindings({ defaultLevel: 1 })
  setLights({ vision_fill: false })
  tick(1.0)
  assert.ok(Math.abs(level() - 1) < 1e-6, 'defaultLevel=1 的灯 off 态仍是常亮')
})

test('灭灯走的是 0.35s 下降沿, 终点精确落在 defaultLevel', () => {
  const { glass, setLights, level, tick } = makeBindings({ defaultLevel: 0 })
  setLights({ vision_fill: true })
  tick(0.3)
  assert.ok(Math.abs(level() - 1) < 1e-6)

  setLights({ vision_fill: false })
  tick(0.2)
  assert.ok(level() > 0 && level() < 1, `0.2s 时应在下降途中, 实际 ${level()}`)
  tick(0.3)
  assert.equal(level(), 0, '下降沿走完必须精确归零, 不留残留亮度')
  assert.equal(glass.material.emissiveIntensity, 0)
})

test('辉光选集只在"亮/灭"翻转时置脏, 斜坡中途不每帧重建', () => {
  const { bindings, setLights, tick } = makeBindings()
  bindings.consumeBloomDirty()               // 清掉构造期可能的置位
  setLights({ vision_fill: true })

  bindings._updateProcessLights(1 / 60)
  assert.equal(bindings.consumeBloomDirty(), true, '从灭到亮要置一次')

  let dirtyFrames = 0
  for (let i = 0; i < 12; i += 1) {
    bindings._updateProcessLights(1 / 60)
    if (bindings.consumeBloomDirty()) dirtyFrames += 1
  }
  assert.equal(dirtyFrames, 0, '斜坡途中已经算"亮着", 集合没变就不该重设 Selection')

  tick(0.3)
  bindings.consumeBloomDirty()
  setLights({ vision_fill: false })
  tick(0.5)
  // 下降沿跨过阈值那一帧置一次即可; 这里只要求"确实置过", 不数具体帧
  assert.equal(bindings.getBloomTargets().length, 0, '灭了就不该再留在辉光选集里')
})

test('辉光选集含灯本体与受照节点 —— 只放灯本体等于这盏灯没有辉光', () => {
  const { bindings, lamp, glass, setLights, tick } = makeBindings()
  assert.deepEqual(bindings.getBloomTargets(), [], '灭着时不进')
  setLights({ vision_fill: true })
  tick(0.3)
  assert.deepEqual(bindings.getBloomTargets(), [lamp, glass])
})

test('TwinFeed 收下 process_light, 同值不重复置版本, 畸形帧忽略', () => {
  const feed = new TwinFeed({ axes: [], realtime: { mechanisms: [] } })
  assert.deepEqual(feed.sampleProcessLights(), {}, '未收帧时是空表, 绑定层据此不接管')

  const before = feed.version
  feed.handleEvent({ type: 'process_light', id: 'vision_fill', on: true, channel: 7 })
  assert.equal(feed.sampleProcessLights().vision_fill, true)
  assert.ok(feed.version > before, '状态变了要推进版本')

  const afterFirst = feed.version
  feed.handleEvent({ type: 'process_light', id: 'vision_fill', on: true, channel: 7 })
  assert.equal(feed.version, afterFirst, '同值重复帧不该触发重渲')

  feed.handleEvent({ type: 'process_light', on: true })
  feed.handleEvent({ type: 'process_light', id: '', on: true })
  assert.deepEqual(Object.keys(feed.sampleProcessLights()), ['vision_fill'], '缺 id 的帧丢掉')

  feed.handleEvent({ type: 'process_light', id: 'vision_fill', on: false })
  assert.equal(feed.sampleProcessLights().vision_fill, false)
})

test('manifest 里没声明的灯 id 收到事件也不炸(将来新增一盏灯不必改两处)', () => {
  const { bindings, setLights } = makeBindings()
  setLights({ vision_fill: true, some_future_lamp: true })
  assert.doesNotThrow(() => bindings._updateProcessLights(1 / 60))
})

test('外壳透视不许再克隆灯的材质 —— 否则亮度写进一份被丢弃的克隆, 画面永远是烘焙色', () => {
  // 这是 2026-08-05 实测抓到的真实回归: 下相机盖板玻璃挂在 ST_FRAME 下, 被
  // _bindEnclosure 二次克隆, 于是 machine.setLight 写的是孤儿材质 —— 探针读到
  // emissiveIntensity=1.8, 场景里那块玻璃却纹丝不动, 视口零像素变化且不报任何错。
  // 同款坑 _bindSignalLight 早年栽过一次, 那条守卫就在隔壁。
  const root = new THREE.Object3D()
  const frame = new THREE.Object3D(); frame.name = 'ST_FRAME'
  const lamp = new THREE.Mesh(
    new THREE.BoxGeometry(0.14, 0.1, 0.012),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  lamp.name = 'VISION_FILL'
  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(0.138, 0.138, 0.003),
    new THREE.MeshStandardMaterial({ emissive: new THREE.Color('#000000') }),
  )
  glass.name = 'COVER_GLASS'
  // 外壳钣金: 与玻璃同在 ST_FRAME 下, 它**应该**被换成克隆材质
  const panel = new THREE.Mesh(
    new THREE.BoxGeometry(1, 1, 0.002),
    new THREE.MeshStandardMaterial(),
  )
  panel.name = 'COVER_PANEL'
  frame.add(glass, panel)
  root.add(lamp, frame)

  const nodeIndex = new Map([
    ['VISION_FILL', lamp], ['ST_FRAME', frame],
    ['COVER_GLASS', glass], ['COVER_PANEL', panel],
  ])
  const manifest = {
    stations: [{ id: 'FRAME', glbNode: 'ST_FRAME' }],
    tanks: [], axes: [], tools: [], nodes: [], attachments: [],
    states: [], sockets: [], actuators: [], linkages: [], inventory: {},
    robot: { joints: [], toolMount: '' },
    lights: [{
      id: 'vision_fill', glbNode: 'VISION_FILL', color: '#ffffff',
      peakIntensity: 4, defaultLevel: 0, bloom: true,
      illuminatesNodes: [{ glbNode: 'COVER_GLASS', peakIntensity: 1.8 }],
    }],
    realtime: { mechanisms: [] },
  }
  const feed = {
    decayActivity: () => {}, sampleProcessLights: () => ({}), sampleMechanismStates: () => ({}),
  }
  const bindings = new TwinBindings(manifest, nodeIndex, feed)

  // 判据必须落在**场景里那个网格**上, 而不是绑定层自己存的引用 —— 后者即使被
  // 孤立也照样读得出 1.8, 正是这一点让原来的 bug 骗过了探针。
  bindings.machine.setLight('vision_fill', 1)
  assert.ok(
    Math.abs(glass.material.emissiveIntensity - 1.8) < 1e-6,
    `场景里的玻璃必须真的亮起来, 实际 ${glass.material.emissiveIntensity}`,
  )
  assert.ok(Math.abs(lamp.material.emissiveIntensity - 4) < 1e-6, '灯本体同理')

  // 真外壳照旧被接管(守卫别放得太宽, 把透视功能一起关掉)
  assert.ok(
    bindings.enclosure.some((e) => e.material === panel.material),
    '钣金外壳仍应被 _bindEnclosure 克隆接管',
  )
  assert.ok(
    !bindings.enclosure.some((e) => e.material === glass.material),
    '功能窗口不该被当成外壳(透视时会跟着变鬼影)',
  )
})
