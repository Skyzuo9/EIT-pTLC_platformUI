/**
 * 功能: 动画引擎纯函数层的单测 —— clip 编译、通道求值、seek 确定性、事件重放.
 *
 * 为什么值得单测: 播放器的正确性完全押在"evaluate(t) 是纯函数 + 事件回家重放"上;
 * 这两条一旦破了, 表现是"拖两次进度条模型姿态不一样"这类极难目测归因的漂移.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { ClipPlayer } from '../../src/three-d/anim/ClipPlayer.js'
import {
  compileClip,
  EASES,
  evaluateChannels,
  eventsUpTo,
  parseClip,
  sampleChannel,
  stepIndexAt,
} from '../../src/three-d/anim/clipSchema.js'

const SAMPLE = `
schema: ptlc.clip/v1
name: t.demo
label: 测试片段
home:
  axis_mm: { axis_11y: 100 }
  joints_deg: [0, 0, 0, 0, 0, 0]
steps:
  - { label: 移动, dur: 2, ease: linear, do: { axis: { id: axis_11y, to_mm: 300 } } }
  - { label: 镜头, at: 0, dur: 1, do: { camera: { preset: iso } } }
  - { label: 抬臂, dur: 2, ease: linear, do: { joints: { to_deg: [10, null, -20, null, null, null] } } }
  - { label: 锁紧, dur: 0.5, do: { tool: { action: lock, id: TOOL_X } } }
  - { label: 提起, dur: 1, ease: linear, do: { joints: { to_deg: [null, -30, null, null, null, null] } } }
`

test('schema 不符直接拒绝', () => {
  assert.throws(() => parseClip('schema: nope\nsteps: []'), /schema/)
})

test('at 缺省 = 上一步结束; duration = 最晚结束', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const [move, camera, arm, lock, lift] = clip.steps
  assert.equal(move.at, 0)
  assert.equal(camera.at, 0) // 显式 at 实现并行
  assert.equal(arm.at, 1)    // 跟在镜头步(0+1)之后
  assert.equal(lock.at, 3)
  assert.equal(lift.at, 3.5)
  assert.equal(clip.duration, 4.5)
})

test('通道编译含保持帧: 步骤开始前保持上一个值', () => {
  const clip = compileClip(parseClip(SAMPLE))
  // 关节 0 的动作发生在 1s~3s, 之前应保持 home(0)
  const state0 = evaluateChannels(clip, 0.99)
  assert.equal(state0.joints[0], 0)
  const state1 = evaluateChannels(clip, 3)
  assert.equal(state1.joints[0], 10)
})

test('线性插值中点取半程', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const state = evaluateChannels(clip, 1) // axis 0~2s, 100→300
  assert.ok(Math.abs(state.axes.axis_11y - 200) < 1e-9)
})

test('joints 的 null 表示保持, 不产生通道', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const state = evaluateChannels(clip, 4.5)
  assert.equal(state.joints[0], 10)   // 第一步抬到 10 后保持
  assert.equal(state.joints[1], -30)  // 提起那步只动 J2
  assert.equal(state.joints[2], -20)
  assert.equal(state.joints[3], 0)    // 从未被写, 保持 home
})

test('evaluate 是纯函数: 同一 t 反复求值结果一致(seek 不漂移)', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const a = evaluateChannels(clip, 2.34)
  evaluateChannels(clip, 4.2)
  evaluateChannels(clip, 0.1)
  const b = evaluateChannels(clip, 2.34)
  assert.deepEqual(a, b)
})

test('eventsUpTo 含边界且按时间排序', () => {
  const clip = compileClip(parseClip(SAMPLE))
  assert.equal(eventsUpTo(clip, 2.99).length, 1)  // 只有镜头(t=0)
  const due = eventsUpTo(clip, 3)                  // 锁紧事件在 t=3
  assert.equal(due.length, 2)
  assert.equal(due[1].kind, 'tool')
})

test('stepIndexAt 命中当前步', () => {
  const clip = compileClip(parseClip(SAMPLE))
  assert.equal(clip.steps[stepIndexAt(clip, 0.5)].label, '移动')
  assert.equal(clip.steps[stepIndexAt(clip, 3.6)].label, '提起')
})

test('缓动函数端点正确', () => {
  // step 不在此列: 它是**阶跃**, 恒返回 1(区间起点就跳到终值), 专给开关量通道用
  // (主轴自转 on/off —— 插值出来的中间值没有物理对应物)。端点约定只管插值型缓动。
  for (const [name, ease] of Object.entries(EASES)) {
    if (name === 'step') continue
    assert.ok(Math.abs(ease(0)) < 1e-9, `${name}(0) 应为 0`)
    assert.ok(Math.abs(ease(1) - 1) < 1e-9, `${name}(1) 应为 1`)
  }
})

test('step 缓动是阶跃: 区间内恒取终值', () => {
  assert.equal(EASES.step(0), 1)
  assert.equal(EASES.step(0.5), 1)
  assert.equal(EASES.step(1), 1)
  // 落到通道上: 起点当帧就是终值, 不留任何中间态
  const frames = [
    { t: 0, v: 0, ease: 'linear' },
    { t: 2, v: 1, ease: 'step' },
  ]
  assert.equal(sampleChannel(frames, 0), 0)
  assert.equal(sampleChannel(frames, 0.001), 1)
  assert.equal(sampleChannel(frames, 1), 1)
  assert.equal(sampleChannel(frames, 2), 1)
})

test('sampleChannel 在首帧前/末帧后取端点值', () => {
  const frames = [
    { t: 1, v: 5, ease: 'linear' },
    { t: 2, v: 7, ease: 'linear' },
  ]
  assert.equal(sampleChannel(frames, 0), 5)
  assert.equal(sampleChannel(frames, 9), 7)
})

test('clip/v3 compiles node/actuator/linkage plus attach/detach/state contracts', () => {
  const doc = parseClip(`
schema: ptlc.clip/v3
name: t.v3
source: { referencePointHash: point-sha }
home:
  joints_deg: [0, 0, 0, 0, 0, 0]
  actuators: { clamp: 0 }
  linkages: { lid: 0 }
steps:
  - { dur: 1, ease: linear, do: { node: { name: PAYLOAD_STAGE, move: [0.1, 0.2, 0.3] } } }
  - { dur: 1, ease: linear, do: { actuator: { id: clamp, to: 1 } } }
  - { dur: 1, ease: linear, do: { linkage: { id: lid, to: 1 } } }
  - { dur: 0, do: { attach: { id: PLATE, parent: TOOL } } }
  - { dur: 0, do: { state: { id: camera, value: capturing } } }
  - { dur: 0, do: { detach: { id: PLATE, to: SOCKET } } }
`)
  const clip = compileClip(doc, {
    pointCatalog: { schema: 'ptlc.robot-points/v1', referencePointHash: 'point-sha', points: {} },
  })
  const state = evaluateChannels(clip, 3)
  assert.deepEqual(state.nodes.PAYLOAD_STAGE, [0.1, 0.2, 0.3])
  assert.equal(state.actuators.clamp, 1)
  assert.equal(state.linkages.lid, 1)
  assert.deepEqual(clip.events.map((event) => event.kind), ['attach', 'state', 'detach'])

  const calls = []
  const rig = {
    joints: [],
    home: () => calls.push(['home']),
    setAxisMm: () => {},
    setNodeOffset: (id, value) => calls.push(['node', id, ...value]),
    setActuator: (id, value) => calls.push(['actuator', id, value]),
    setLinkage: (id, value) => calls.push(['linkage', id, value]),
    attach: (id, parent) => calls.push(['attach', id, parent]),
    detach: (id, parent) => calls.push(['detach', id, parent]),
    setState: (id, value) => calls.push(['state', id, value]),
    setHighlight: () => {},
  }
  const player = new ClipPlayer({ rig })
  player.load(clip)
  player.seek(clip.duration)
  assert.ok(calls.some(([kind, id, value]) => kind === 'actuator' && id === 'clamp' && value === 1))
  assert.ok(calls.some(([kind, id]) => kind === 'linkage' && id === 'lid'))
  assert.ok(calls.some(([kind, id, parent]) => kind === 'attach' && id === 'PLATE' && parent === 'TOOL'))
  assert.ok(calls.some(([kind, id, parent]) => kind === 'detach' && id === 'PLATE' && parent === 'SOCKET'))
  assert.ok(calls.some(([kind, id, value]) => kind === 'state' && id === 'camera' && value === 'capturing'))
})

// ---------------------------------------------------------------------------
// ClipPlayer 的事件重放语义(用假 rig, 不碰 three)
// ---------------------------------------------------------------------------

function fakeRig() {
  const calls = []
  let currentJoints = [0, 0, 0, 0, 0, 0]
  return {
    calls,
    joints: [1, 2, 3, 4, 5, 6], // 非空即可让 setJointsDeg 被调用
    home: () => calls.push(['home']),
    setAxisMm: (id, mm) => calls.push(['axis', id, Math.round(mm)]),
    setJointsDeg: (values) => {
      currentJoints = [...values]
      calls.push(['joints', ...values])
    },
    lockTool: (id) => calls.push(['lock', id, currentJoints[0]]),
    releaseTool: (id) => calls.push(['release', id]),
    setHighlight: () => {},
  }
}

test('首个事件前 seek 不重复 home，锁紧先应用事件时刻的关节姿态', () => {
  const clip = compileClip(parseClip(`
schema: ptlc.clip/v1
name: t.event-pose
home: { joints_deg: [0, 0, 0, 0, 0, 0] }
steps:
  - { label: 转腕, dur: 3, ease: linear, do: { joints: { to_deg: [90, 0, 0, 0, 0, 0] } } }
  - { label: 锁紧, dur: 0.5, do: { tool: { action: lock, id: TOOL_X } } }
`))
  const rig = fakeRig()
  const player = new ClipPlayer({ rig })
  player.load(clip)
  const homesAfterLoad = rig.calls.filter(([kind]) => kind === 'home').length

  player.seek(2.9)
  assert.equal(rig.calls.filter(([kind]) => kind === 'home').length, homesAfterLoad,
    '离散事件游标为 0 不代表播放器尚未初始化')

  player.seek(3.2)
  const lock = rig.calls.find(([kind]) => kind === 'lock')
  assert.equal(lock[2], 90, 'lockTool 必须看到事件 t=3 时已经完成的关节姿态')
})

test('正放跨过锁紧事件只触发一次; 回拖则回家重放', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const rig = fakeRig()
  const player = new ClipPlayer({ rig })
  player.load(clip)

  player.seek(3.2) // 向前跨过 t=3 的 lock
  const locks = rig.calls.filter(([kind]) => kind === 'lock')
  assert.equal(locks.length, 1)

  player.seek(4.0) // 继续前进, 不应重复 lock
  assert.equal(rig.calls.filter(([kind]) => kind === 'lock').length, 1)

  player.seek(1.0) // 回拖到锁紧之前: 必须 home + 不再处于锁定
  const lastHome = rig.calls.map(([kind]) => kind).lastIndexOf('home')
  const locksAfterHome = rig.calls.slice(lastHome).filter(([kind]) => kind === 'lock')
  assert.equal(locksAfterHome.length, 0, '回拖到事件之前后不应重放 lock')

  player.seek(3.5) // 再向前, lock 应重新触发一次
  assert.equal(rig.calls.filter(([kind]) => kind === 'lock').length, 2)
})

test('tick 推进到结尾自动停', () => {
  const clip = compileClip(parseClip(SAMPLE))
  const rig = fakeRig()
  const states = []
  const player = new ClipPlayer({ rig, onChange: (s) => states.push({ ...s }) })
  player.load(clip)
  player.toggle()
  for (let i = 0; i < 200; i += 1) player.tick(0.05)
  const last = states[states.length - 1]
  assert.equal(last.playing, false)
  assert.ok(Math.abs(last.time - clip.duration) < 1e-6)
})

test('move_l 终点钉到示教 joint; 轨迹与点表漂移超限则拒绝', () => {
  const hash = 'endpoint-sha'
  const catalog = {
    schema: 'ptlc.robot-points/v1',
    referencePointHash: hash,
    points: {
      grab: { joint: [10, 20, 30, 40, 50, 60], allowedMotion: ['move_l'] },
      hover: { joint: null, allowedMotion: ['move_l'] },
    },
  }
  const doc = {
    schema: 'ptlc.clip/v2',
    name: 'endpoint',
    source: { referencePointHash: hash },
    home: { joints_deg: [0, 0, 0, 0, 0, 0] },
    steps: [{ dur: 1, do: { robot_point: { id: 'grab', motion: 'move_l' } } }],
    compiled: {
      // 等距采样常见形态: 末样本离示教点差零点几度(实测取刀下插为 ~0.3°)
      moveLTrajectories: { 0: [[0, 0, 0, 0, 0, 0], [9.7, 19.8, 29.9, 39.8, 49.9, 59.9]] },
    },
  }
  const clip = compileClip(doc, { pointCatalog: catalog })
  const taught = [10, 20, 30, 40, 50, 60]
  for (let jointIndex = 0; jointIndex < 6; jointIndex += 1) {
    const frames = clip.channels.get(`joint:${jointIndex}`)
    assert.equal(frames[frames.length - 1].v, taught[jointIndex], '末帧必须精确等于示教值')
  }

  // joint=null 的接近点不做钉接(没有权威终点可钉)
  const hoverDoc = {
    ...doc,
    steps: [{ dur: 1, do: { robot_point: { id: 'hover', motion: 'move_l' } } }],
  }
  const hoverClip = compileClip(hoverDoc, { pointCatalog: catalog })
  const hoverFrames = hoverClip.channels.get('joint:0')
  assert.equal(hoverFrames[hoverFrames.length - 1].v, 9.7, 'joint=null 时保持轨迹原样')

  // 末样本与点表差 2°(>1.5°): 轨迹与点表不同源, 必须拒绝而不是静默硬拉
  const drifted = {
    ...doc,
    compiled: { moveLTrajectories: { 0: [[0, 0, 0, 0, 0, 0], [8, 20, 30, 40, 50, 60]] } },
  }
  assert.throws(() => compileClip(drifted, { pointCatalog: catalog }), /漂移/)
})

test('home 里只声明、没有任何步骤的连续量也要成通道 —— 否则被 rig.home() 抹掉', () => {
  // 背景: 向后 seek 与装载都走 rig.home(), 那里把**每一根**轴/机构复位到 CAD 基位并置
  // NaN(它是清场的唯一入口); 播放器随后只应用 clip 里**有通道**的量。所以"只在 home 里
  // 声明、没有任何步骤"的量若不建通道就会被静默丢掉, 停在建模位而画面看着完全正常。
  //
  // clip_compiler.SEAT_AXES 整套机制正建立在它上面 —— "片段自己不驱这些轴时, 就把它写进
  // home.axis_mm 声明成起手状态"。2026-08-05 实测: 上样-上料不动 7Y, 于是点样座整段停在
  // 建模位, 用户一眼看出"板托座不在放板位"。
  const compiled = compileClip({
    schema: 'ptlc.clip/v1',
    name: 'home-only',
    home: {
      axis_mm: { axis_7y: 56, axis_11y: 500 },
      actuators: { ps_shade: 1 },
      linkages: { col_clamp: 0 },
    },
    steps: [{ label: '只动地轨', dur: 1, ease: 'linear', do: { axis: { id: 'axis_11y', to_mm: 168 } } }],
  }, {})

  // 没被任何步骤驱动的量: 通道仍在, 值就是 home 声明的那个
  assert.equal(compiled.channels.get('axis:axis_7y')[0].v, 56)
  assert.equal(compiled.channels.get('actuator:ps_shade')[0].v, 1)
  assert.equal(compiled.channels.get('linkage:col_clamp')[0].v, 0)
  // t=0 与末刻都读得到(否则 seek 到任何时刻都会丢)
  assert.equal(evaluateChannels(compiled, 0).axes.axis_7y, 56)
  assert.equal(evaluateChannels(compiled, compiled.duration).axes.axis_7y, 56)
  assert.equal(evaluateChannels(compiled, compiled.duration).actuators.ps_shade, 1)
  // 被驱动的那根照常走完
  assert.equal(evaluateChannels(compiled, compiled.duration).axes.axis_11y, 168)
})
