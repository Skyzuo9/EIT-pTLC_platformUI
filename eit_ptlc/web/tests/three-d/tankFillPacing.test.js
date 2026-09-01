/**
 * 展缸注液的**节拍**回归测试 —— 锁的是"泵打一趟、缸涨一截", 不是终点体积.
 *
 * 为什么单独一个文件而不是塞进 tankLiquid.test.js: 那边锁的是体积规则
 * (resolveLiquidPlan 的连乘/夹取/holdup)与渲染层换算, 全部只看**终值**;
 * 本文件锁的是**时间上的分布**, 两件事的失效形状不同.
 *
 * 病史(2026-08-09): 编译器与 flowSim 原先把一条动作的泵行程**全部发完, 才发那一条
 * 整段液面斜坡**. 于是 flow.develop_prepare.tank1 的 170.6s 里有 140.6s(82%)缸内恒为 0
 * —— 4 趟 10mL 润洗泵行程期间缸里一动不动, 而展缸泵的几何在 ST_PUMP 工位, 镜头对着
 * 展缸时根本不在画面里. 用户看到的就是"吸 10mL 没有任何动画, 20mL 才有"(那个 20 其实
 * 是随后那条整段斜坡的终点). 终点体积当时**完全正确**, 所以现有的液面断言(全部按
 * 20mL 标定, 只看终值)一条都没红.
 *
 * 三层各锁一环:
 *   1. flowSim 逐趟 —— 每趟 dispense 与它那一截液面同 at 同 dur; 时间轴光标不被拨回;
 *   2. actionSim 逐趟 —— 单动作页没有泵步可并行, 顺序发 N 段, 总时长不变;
 *   3. 片段语料 —— 真产物 flow.develop_prepare.tank1 的缸内液面不许长时间平在 0.
 *
 * 与 stationLiquid/gripperCorpus 同一条产物门禁约定: 管线产物不存在时静默跳过.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { compileClip, parseClip, sampleChannel } from '../../src/three-d/anim/clipSchema.js'
import { planSimulation } from '../../src/three-d/demo/actionSim.js'
import { simulateFlow } from '../../src/three-d/demo/flowSim.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CLIP_PATH = path.join(WORKSPACE_ROOT, 'clips', 'flow.develop_prepare.tank1.yaml')
const CATALOG_PATH = path.join(WORKSPACE_ROOT, 'generated', 'robot-points.json')

/**
 * 缸内液面恒为 0 的**最长连续时长**(秒) —— 这次 bug 的直接度量.
 * 按 0.1s 步长采样编译后的通道, 与播放器 sampleChannel 用同一条插值.
 * @param {Array<{t: number, v: number, ease: string}>} frames 通道关键帧
 * @param {number} duration 片段总时长
 * @returns {number} 秒
 */
function longestDrySpanS(frames, duration) {
  const STEP = 0.1
  let worst = 0
  let run = 0
  for (let t = 0; t <= duration; t += STEP) {
    if (sampleChannel(frames, t) <= 1e-6) {
      run += STEP
      if (run > worst) worst = run
    } else {
      run = 0
    }
  }
  return Math.round(worst * 10) / 10
}

/**
 * 时间轴末端 —— 与 clipSchema.compileClip / 编译器 _timeline_end_s 同一条光标规则.
 * 显式 at 把光标拨回去就是"后面每一步都错位"的形状, 这里当断言用.
 * @param {object[]} steps 步骤表
 * @returns {number} 秒
 */
function cursorEnd(steps) {
  let cursor = 0
  for (const step of steps) {
    cursor = (step.at === undefined ? cursor : Number(step.at)) + (Number(step.dur) || 0)
  }
  return Math.round(cursor * 1000) / 1000
}

// --- 契约夹具: 与 device-manifest 的 tankLiquid / pumpSyringe / tanks 同形 --------- //

const CAVITY = { usableDepthMm: 20.274, freeAreaMm2: 4939.6, capacityMl: 102.48, mlPerMm: 4.94 }

const MANIFEST = {
  tanks: [
    { index: 0, id: 'tank1', glbNode: 'ST_DEVELOP/T1', liquidNode: 'ST_DEVELOP/T1/LIQUID_1' },
  ],
  tankLiquid: {
    cavity: CAVITY,
    exaggeration: 2.0,
    pipeHoldupMl: 0.0,
    tankArg: 'target_tank',
    actions: {
      'develop.fill': { dir: 'fill', volumeFrom: ['solvent_volume_ml', 'up_liquid_repeat_count'], rampS: 12 },
      'develop.rinse_fill': { dir: 'fill', volumeFrom: ['solvent_volume_ml', 'rinse_repeat_count'], rampS: 10 },
    },
  },
  linkages: [{ id: 'dev_t1_cyl1', transitionS: 1.2 }],
  pumpSyringe: {
    syringeMl: 25,
    strokeMm: 60,
    stepsPerStroke: 6000,
    speeds: { develop: { asp_speed: 300, disp_speed: 300, step_delay: 500 } },
    pumps: [
      { index: 0, id: 'DEV1', label: '展开泵 1(缸 1-4)', tankGroup: [1, 2, 3, 4], rigged: true,
        plungerNode: 'ST_PUMP/P1/ACTUATOR_PUMP_PLUNGER_DEV1',
        liquidNode: 'ST_PUMP/P1/LIQUID_PUMP_DEV1',
        valvePorts: 6, outputPort: 6, speedStation: 'develop' },
    ],
    actions: {
      'develop.fill': {
        pump: { from: 'tankGroup', arg: 'target_tank' },
        repeatFrom: 'up_liquid_repeat_count',
        phases: [
          { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, port: 2, rampS: 4, speed: 'asp_speed' },
          { op: 'dispense', to: 0, port: 'output', rampS: 4, speed: 'disp_speed' },
        ],
      },
      'develop.rinse_fill': {
        pump: { from: 'tankGroup', arg: 'target_tank' },
        repeatFrom: 'rinse_repeat_count',
        phases: [
          { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, port: 2, rampS: 3, speed: 'asp_speed' },
          { op: 'dispense', to: 0, port: 'output', rampS: 3, speed: 'disp_speed' },
        ],
      },
    },
  },
}

// develop.rinse_fill 同时在 tankLidActions 里(既关盖又注液), 走 flowSim 的 tank-lid 分支
const MOTION_MAP = {
  tankLidActions: { 'develop.rinse_fill': 1 },
  tankLidLinkage: { 1: 'dev_t1_cyl1' },
}

const CONTEXT = { manifest: MANIFEST, motionMap: MOTION_MAP, servoIndex: {}, pointCatalog: null }

/** 一条最小流程壳 */
function flow(body) {
  return { schema: 'ptlc.script/v1', kind: 'operation', name: 'probe', body }
}

// --- 1. flowSim: 逐趟 + 与泵同拍 -------------------------------------------------- //

test('flowSim: 3 趟上液 -> 3 段液面, 每段与它那一趟 dispense 同 at 同 dur', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 } },
  ]), {}, CONTEXT)
  const steps = result.doc.steps

  const liquids = steps.filter((s) => s.do.liquid)
  assert.equal(liquids.length, 3, '3 趟上液必须出 3 段液面, 不是一条斜坡到底')
  assert.deepEqual(liquids.map((s) => s.do.liquid.to_ml), [20, 40, 60],
    '逐趟累加到契约总量 20×3')

  // 每段液面都必须并在某一条 dispense 泵步上: 同 at 同 dur.
  // 容差而不是严格相等: 隐式 at 是逐步累加出来的(17.299999999999997), 显式 at 是
  // timelineEnd 取整过的(17.3) —— 差 3e-15, 播放上无意义, 拿它判红只会是个假警报.
  let cursor = 0
  const pumpWindows = []
  for (const step of steps) {
    const at = step.at === undefined ? cursor : Number(step.at)
    const dur = Number(step.dur) || 0
    cursor = at + dur
    if (step.do.pump) pumpWindows.push({ at, dur })
  }
  for (const step of liquids) {
    assert.ok(step.at !== undefined, `液面步缺 at, 没有并行: ${step.label}`)
    const hit = pumpWindows.some(
      (w) => Math.abs(w.at - step.at) < 1e-6 && Math.abs(w.dur - step.dur) < 1e-6)
    assert.ok(hit,
      `液面步 ${step.label}(at=${step.at} dur=${step.dur}) 没有与任何泵行程同 at 同 dur `
      + `—— 它就该在打液那一拍涨. 泵窗口: ${JSON.stringify(pumpWindows)}`)
  }
})

test('flowSim: 并行液面步不得把时间轴光标拨回去(整条流程不错位)', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 } },
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 } },
  ]), {}, CONTEXT)
  const steps = result.doc.steps
  const realEnd = Math.max(...steps.map((s, i) => {
    let cursor = 0
    for (let k = 0; k <= i; k += 1) {
      cursor = (steps[k].at === undefined ? cursor : Number(steps[k].at)) + (Number(steps[k].dur) || 0)
    }
    return cursor
  }))
  assert.ok(Math.abs(cursorEnd(steps) - realEnd) < 1e-6,
    `末端光标 ${cursorEnd(steps)} ≠ 真实末端 ${realEnd} —— 有并行步被排到了它并的那一步之后`)
  // 第二条同量 fill 是**绝对目标**: 缸内已经是 60mL, 逐趟一趟都涨不动, 于是交还给
  // emitTankLiquid 出一条 60→60 的退化步(改前两条 fill 就是 [60, 60], 这一条没变).
  assert.deepEqual(steps.filter((s) => s.do.liquid).map((s) => s.do.liquid.to_ml), [20, 40, 60, 60],
    '同一缸连发两次同量 fill: 第二次不涨(绝对目标语义, 与编译器一致)')
})

test('flowSim: rinse_fill(既关盖又注液)也逐趟 —— 这就是用户报的 10mL 那一档', () => {
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.rinse_fill',
      args: { target_tank: 1, solvent_volume_ml: 10, rinse_repeat_count: 2 } },
  ]), {}, CONTEXT)
  const steps = result.doc.steps
  assert.ok(steps.some((s) => s.do.linkage), '关盖那件事不能被挤掉 —— 三件事是叠加')
  const liquids = steps.filter((s) => s.do.liquid)
  assert.deepEqual(liquids.map((s) => s.do.liquid.to_ml), [10, 20],
    '润洗 10mL × 2 趟必须走出 10 → 20 两档, 而不是一条 0→20')
  for (const step of liquids) {
    assert.ok(step.at !== undefined, `液面步缺 at, 没有并到打液那一拍: ${step.label}`)
  }
})

test('flowSim: 泵没几何时退回整段斜坡 —— 老路径逐字节不变', () => {
  const noPump = {
    ...CONTEXT,
    manifest: {
      ...MANIFEST,
      pumpSyringe: {
        ...MANIFEST.pumpSyringe,
        pumps: [{ ...MANIFEST.pumpSyringe.pumps[0], rigged: false, plungerNode: null }],
      },
    },
  }
  const result = simulateFlow(flow([
    { op: 'call', action: 'develop.fill', args: { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 } },
  ]), {}, noPump)
  const liquids = result.doc.steps.filter((s) => s.do.liquid)
  assert.equal(liquids.length, 1, '没有泵行程可并时只出一条整段斜坡')
  assert.equal(liquids[0].do.liquid.to_ml, 60)
  assert.equal(liquids[0].at, undefined, '兜底路径不该带 at')
})

// --- 2. actionSim: 单动作页也看得出趟数 -------------------------------------------- //

test('actionSim: 单播 develop.fill 出 3 段液面, 总时长与改前一致', () => {
  const plan = planSimulation(
    { name: 'develop.fill', label: '展缸-上液', kind: 'plc_l2', params: [] },
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 },
    { ...CONTEXT, actionCatalog: [] },
  )
  const liquids = plan.doc.steps.filter((s) => s.do.liquid)
  assert.equal(liquids.length, 3, '3 趟上液必须出 3 段')
  assert.deepEqual(liquids.map((s) => s.do.liquid.to_ml), [20, 40, 60])
  const total = liquids.reduce((sum, s) => sum + s.dur, 0)
  assert.ok(Math.abs(total - 12) < 0.05, `均分本动作的 rampS=12s, 实得 ${total}s`)
})

test('actionSim: 只有一趟时不拆 —— 拆了跟不拆一样, 白多一步', () => {
  const plan = planSimulation(
    { name: 'develop.fill', label: '展缸-上液', kind: 'plc_l2', params: [] },
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 },
    { ...CONTEXT, actionCatalog: [] },
  )
  const liquids = plan.doc.steps.filter((s) => s.do.liquid)
  assert.equal(liquids.length, 1)
  assert.equal(liquids[0].do.liquid.to_ml, 20)
})

// --- 3. 片段语料: 真产物不许长时间空缸 --------------------------------------------- //

test('片段语料: flow.develop_prepare.tank1 的缸内液面不许长时间平在 0', () => {
  // 产物不在就跳过(与其它语料测试同一条门禁); v3 片段编译要点位目录
  if (!fs.existsSync(CLIP_PATH) || !fs.existsSync(CATALOG_PATH)) return
  const catalog = JSON.parse(fs.readFileSync(CATALOG_PATH, 'utf-8'))
  const clip = compileClip(parseClip(fs.readFileSync(CLIP_PATH, 'utf-8')), { pointCatalog: catalog })
  const frames = clip.channels.get('liquid:tank1')
  assert.ok(frames?.length, '片段里没有 liquid:tank1 通道')

  // 病史值: 修之前最长空窗 101.4s / 总时长 170.6s. 阈值取 30s —— 既远低于病史,
  // 又给"润洗抽干之后到正式上液第一趟打出去"那段真实空窗(现状 17.3s)留出余量.
  const dry = longestDrySpanS(frames, clip.duration)
  assert.ok(dry <= 30,
    `缸内液面连续 ${dry}s 恒为 0(总时长 ${clip.duration}s) —— 泵在打液但缸里不动, `
    + '就是 2026-08-09 那个"吸 10mL 没有任何动画"的形状')

  // 润洗那两趟各 10mL: 缸里必须真出现过 10 这一档, 而不是直接跳到 20
  const targets = frames.map((f) => Math.round(f.v * 10) / 10)
  assert.ok(targets.includes(10),
    `液面通道从没经过 10mL 档(实得 ${[...new Set(targets)].join('/')}) —— `
    + '润洗 10mL × 2 趟被合并成了一条 0→20 的整段斜坡')
})
