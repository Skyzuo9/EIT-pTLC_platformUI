/**
 * 功能: 注射泵柱塞位置模型的单元测试.
 *
 * 这一层值得单测的原因有两个, 都不是靠肉眼验收能发现的:
 *   1. **往复运动只看终值发现不了.** develop.fill 一趟"吸满→打空"起点终点都是 0 ——
 *      相位脚本要是没生效, 末值同样是 0, 画面上柱塞纹丝不动却没有任何报错. 所以这里
 *      的用例一律断言**中途峰值**, 不只断言终值.
 *   2. **相对相位必须基于 committed(逻辑位)而不是 channel.value(动画位).** 动作首尾
 *      相接时动画常常还没走完, 读动画位起算会一次漂掉几 mL, 而且越接越远.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PumpSyringeModel, expandPumpPlan } from '../../src/three-d/twin/bindings/PumpSyringeModel.js'

if (typeof performance === 'undefined') {
  globalThis.performance = { now: () => 0 }
}

/** 与 gen_twin_manifest.PUMP_SYRINGE_ACTIONS 同形的配置(截取会用到的几条) */
function makeConfig(overrides = {}) {
  return {
    syringeMl: 25,
    strokeMm: 60,
    stepsPerStroke: 6000,
    estimated: true,
    // 逐字抄 app.yaml 的 pump 段 —— 相位时长按 步数/V + M/1000 算
    speeds: {
      develop: { asp_speed: 100, disp_speed: 100, step_delay: 500 },
      collect: { asp_speed: 500, disp_speed: 500, step_delay: 1000 },
      sampling: { asp_speed: 250, disp_speed: 100, spot_disp_speed: 9,
                  step_delay: 1500, flush_disp_speed: 300,
                  spot_head_disp_speed: 100 },
    },
    pumps: [
      // rigged 泵带 plungerNode/liquidNode: 与真实 manifest 同形 —— expandPumpPlan 的
      // rigged 判定沿用实时链的"rigged 且有柱塞节点"(TwinBindings._bindPumps 同款)
      { index: 0, id: 'DEV1', label: '展开泵 1', station: 'PUMP', dtAddr: 1, valve: 'T-06',
        tankGroup: [1, 2, 3, 4], travelAxis: [0, 1, 0], travelM: 0.06, strokeMm: 60,
        valvePorts: 6, outputPort: 6, valveAxis: [0, 0, 1], rigged: true,
        plungerNode: 'ST_PUMP/P2/ACTUATOR_PUMP_PLUNGER_DEV1',
        liquidNode: 'ST_PUMP/P2/LIQUID_PUMP_DEV1',
        speedStation: 'develop', leadTurnsPerStroke: 10 },
      { index: 1, id: 'DEV2', label: '展开泵 2', station: 'PUMP', dtAddr: 2, valve: 'T-06',
        tankGroup: [5, 6, 7, 8], travelAxis: [0, 1, 0], travelM: 0.06, strokeMm: 60,
        valvePorts: 6, outputPort: 1, valveAxis: [0, 0, 1], rigged: true,
        plungerNode: 'ST_PUMP/P1/ACTUATOR_PUMP_PLUNGER_DEV2',
        liquidNode: 'ST_PUMP/P1/LIQUID_PUMP_DEV2',
        speedStation: 'develop', leadTurnsPerStroke: 10 },
      { index: 2, id: 'SMP', label: '上样泵', station: 'SAMPLING', dtAddr: 4, valve: 'T-04',
        tankGroup: [], travelAxis: [0, 1, 0], travelM: 0.06, strokeMm: 60,
        valvePorts: 4, outputPort: 3, valveAxis: [0, 0, 1], rigged: true,
        plungerNode: 'ST_SAMPLING/C6/ACTUATOR_PUMP_PLUNGER_SMP',
        liquidNode: 'ST_SAMPLING/C6/LIQUID_PUMP_SMP',
        speedStation: 'sampling', leadTurnsPerStroke: 10 },
      { index: 3, id: 'COL', label: '收集泵', station: 'COLLECT', dtAddr: 3, valve: 'T-04',
        tankGroup: [], travelAxis: [0, 1, 0], travelM: 0, strokeMm: 60,
        valvePorts: 4, outputPort: null, valveAxis: [0, 0, 1], rigged: false,
        speedStation: 'collect', leadTurnsPerStroke: 0 },
    ],
    actions: {
      'develop.init': {
        pump: { from: 'tankGroup', arg: 'target_tank' },
        phases: [{ op: 'home', to: 0, rampS: 2 }],
      },
      'develop.fill': {
        pump: { from: 'tankGroup', arg: 'target_tank' },
        repeatFrom: 'up_liquid_repeat_count',
        phases: [
          { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, port: 2, rampS: 4, speed: 'asp_speed' },
          { op: 'dispense', to: 0, port: 'output', rampS: 4, speed: 'disp_speed' },
        ],
      },
      'sampling.init': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [{ op: 'home', to: 0, rampS: 2 }],
      },
      'sampling.clean': {
        pump: { from: 'fixed', id: 'SMP' },
        repeatFrom: 'cleaning_count',
        phases: [
          { op: 'aspirate', toFrom: { add: ['wash_volume_ml'] }, rampS: 4 },
          { op: 'dispense', to: 0, rampS: 4 },
          { op: 'aspirate', toFrom: { add: ['wash_volume_ml'] }, rampS: 4 },
          { op: 'dispense', to: 0, rampS: 4 },
        ],
      },
      'sampling.flush': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [
          { op: 'aspirate',
            toFrom: { add: ['flush_volume_ml', 'outer_wash_volume_ml', 'spot_head_volume_ml'],
                      fallback: [17, 5, 3] }, rampS: 8 },
          { op: 'dispense',
            toFrom: { add: ['outer_wash_volume_ml', 'spot_head_volume_ml'], fallback: [5, 3] },
            rampS: 6 },
          { op: 'dispense', toFrom: { add: ['spot_head_volume_ml'], fallback: [3] }, rampS: 4 },
          { op: 'dispense', to: 0, rampS: 3, speed: 'spot_head_disp_speed' },
        ],
      },
      'sampling.prep': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [{ op: 'aspirate', toFrom: { add: ['air_buffer_ml'], fallback: [0.2] }, port: 3, rampS: 2, speed: 'asp_speed' }],
      },
      'sampling.aspirate': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [
          { op: 'aspirate', toFrom: { add: ['air_gap_ml'] }, skipIfMissing: true, rampS: 2 },
          { op: 'aspirate', byFrom: { add: ['sample_volume_ml'] }, rampS: 4 },
        ],
      },
      'sampling.spot': {
        pump: { from: 'fixed', id: 'SMP' },
        phases: [{ op: 'dispense', byFrom: { add: ['sample_volume_ml'] }, rampS: 8, speed: 'spot_disp_speed' }],
      },
    },
    ...overrides,
  }
}

/** 功能: 按 60 fps 推进若干秒, 并回传过程中某泵 level 的极值. 返回 {min, max} */
function advance(model, seconds, index = 0, fps = 60) {
  const dt = 1 / fps
  let min = model.level(index)
  let max = min
  for (let i = 0; i < Math.round(seconds * fps); i += 1) {
    model.step(dt)
    const level = model.level(index)
    if (level < min) min = level
    if (level > max) max = level
  }
  return { min, max }
}

// --- 降级与解析 ------------------------------------------------------------

test('缺 manifest.pumpSyringe 时静默降级, 不抛错', () => {
  const model = new PumpSyringeModel(undefined)
  assert.equal(model.enabled, false)
  assert.equal(model.onActionEnter('develop.fill', { target_tank: 1 }), false)
  assert.equal(model.level(0), 0)
  model.step(0.016)
  assert.deepEqual(model.snapshot(), [])
})

test('无关动作与非法缸号一律不接管', () => {
  const model = new PumpSyringeModel(makeConfig())
  assert.equal(model.onActionEnter('robot.tool_pickup', {}), false)
  assert.equal(model.onActionEnter('develop.fill', { target_tank: 0 }), false)
  assert.equal(model.onActionEnter('develop.fill', { target_tank: 9 }), false)
  assert.equal(model.onActionEnter('develop.fill', {}), false)
})

test('缸号按 manifest 的 tankGroup 路由到对应泵, 不重算 //4', () => {
  const model = new PumpSyringeModel(makeConfig())
  for (const tank of [1, 2, 3, 4]) {
    assert.equal(model._pumpIndex({ from: 'tankGroup', arg: 'target_tank' }, { target_tank: tank }), 0)
  }
  for (const tank of [5, 6, 7, 8]) {
    assert.equal(model._pumpIndex({ from: 'tankGroup', arg: 'target_tank' }, { target_tank: tank }), 1)
  }
})

// --- 往复运动(本模型的存在理由) --------------------------------------------

test('develop.fill 重复 2 趟: 必须升-降-升-降, 只看终值会漏掉整类 bug', () => {
  const model = new PumpSyringeModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 2 }
  model.onActionEnter('develop.fill', args)

  // 时长按实机算: 20mL × 240 步/mL ÷ V100 = 48s 一段, 段间还有 M500 = 0.5s 稳液,
  // 所以一趟往复 ≈ 97s. 这里的秒数不是拍的, 是换算出来的.
  const first = advance(model, 55, 0)
  assert.ok(first.max > 0.5, `第一趟应吸到半程以上, 实际峰值 ${first.max}`)
  const rest = advance(model, 150, 0)
  assert.ok(rest.min < 0.05, `中途应回到近零(打空), 实际最低 ${rest.min}`)
  assert.ok(rest.max > 0.5, `第二趟应再次吸起, 实际峰值 ${rest.max}`)

  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 0)
})

test('sampling.clean 每轮内壁+外壁两次吸排, 相位数随次数增长', () => {
  const model = new PumpSyringeModel(makeConfig())
  const plan = model._resolve('sampling.clean', { wash_volume_ml: 4, cleaning_count: 3 })
  assert.equal(plan.index, 2)
  assert.equal(plan.phases.length, 12)          // 3 轮 × 4 相位
  assert.equal(plan.phases[0].targetMl, 4)
  assert.equal(plan.phases[1].targetMl, 0)
})

test('sampling.flush 峰值 = 三段之和; 缺项走 fallback 后峰值不变', () => {
  const model = new PumpSyringeModel(makeConfig())
  const full = model._resolve('sampling.flush',
    { flush_volume_ml: 17, outer_wash_volume_ml: 5, spot_head_volume_ml: 3 })
  assert.equal(full.phases[0].targetMl, 25)
  assert.equal(full.phases[1].targetMl, 8)
  assert.equal(full.phases[2].targetMl, 3)
  assert.equal(full.phases[3].targetMl, 0)

  const partial = model._resolve('sampling.flush', { flush_volume_ml: 17 })
  assert.equal(partial.phases[0].targetMl, 25, '缺项应由 fallback 补齐, 峰值不塌')
})

// --- 相对相位与累加态 ------------------------------------------------------

test('相对相位基于 committed 而非动画位 —— 本模型最容易写错的一行', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  model.onActionDone('sampling.prep', { air_buffer_ml: 3 }, 'DONE')
  assert.equal(model.volumeMl(2), 3)

  // 故意不等动画收敛: 只推进 0.1s, 此时 value 远不到 3
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  model.committed[2] = 3
  model.plungers[2].value = 0.9
  const plan = model._resolve('sampling.aspirate', { sample_volume_ml: 5 })
  assert.equal(plan.phases[plan.phases.length - 1].targetMl, 8,
    '应是 committed(3) + 5 = 8, 读动画位会得到 5.9')
})

test('sampling.aspirate 的可缺省气隙相位: 给了就走, 没给就跳过', () => {
  const model = new PumpSyringeModel(makeConfig())
  const withGap = model._resolve('sampling.aspirate', { air_gap_ml: 0.2, sample_volume_ml: 5 })
  assert.equal(withGap.phases.length, 2)
  assert.equal(withGap.phases[1].targetMl, 5.2)

  const noGap = model._resolve('sampling.aspirate', { sample_volume_ml: 5 })
  assert.equal(noGap.phases.length, 1, 'skipIfMissing 的相位应被跳过')
  assert.equal(noGap.phases[0].targetMl, 5)
})

test('dispense 的相对相位是减法, 气隙留在筒里', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.committed[2] = 5.2
  const plan = model._resolve('sampling.spot', { sample_volume_ml: 5 })
  assert.ok(Math.abs(plan.phases[0].targetMl - 0.2) < 1e-9)
})

// --- 包络冲突与失败 --------------------------------------------------------

test('同一泵上新包络接管旧包络, 目标不来回抖', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 5 })
  advance(model, 0.5, 2)
  model.onActionEnter('sampling.clean', { wash_volume_ml: 10, cleaning_count: 1 })
  const before = model.plungers[2].target
  advance(model, 0.2, 2)
  assert.equal(model.active[2].action, 'sampling.clean')
  assert.equal(model.plungers[2].target, before, '旧包络不得再写目标')
})

test('不同泵互不干扰', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('develop.fill', { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 })
  advance(model, 3, 0)
  const dev1 = model.volumeMl(0)
  model.onActionEnter('develop.fill', { target_tank: 5, solvent_volume_ml: 10, up_liquid_repeat_count: 1 })
  assert.equal(model.volumeMl(0), dev1)
  assert.equal(model.volumeMl(1), 0)
})

test('失败不假装完成: 停在当前位, committed 落到当前位', () => {
  const model = new PumpSyringeModel(makeConfig())
  const args = { wash_volume_ml: 10, cleaning_count: 1 }
  model.onActionEnter('sampling.clean', args)
  advance(model, 1, 2)
  const mid = model.volumeMl(2)
  assert.ok(mid > 0 && mid < 10)
  model.onActionDone('sampling.clean', args, 'FAILED')
  assert.equal(model.committed[2], model.plungers[2].value)
  advance(model, 5, 2)
  assert.ok(Math.abs(model.volumeMl(2) - mid) < 1e-9, '失败后不得继续移动')
})

test('*.init 是唯一的绝对位置锚点: 立即归零并置为可信', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  model.onActionDone('sampling.prep', { air_buffer_ml: 3 }, 'DONE')
  assert.equal(model.volumeMl(2), 3)
  model.onActionEnter('sampling.init', {})
  model.onActionDone('sampling.init', {}, 'DONE')
  assert.equal(model.volumeMl(2), 0)
  assert.equal(model.isKnown(2), true)
})

// --- 重放与帧率无关性 ------------------------------------------------------

test('同一事件序列重放两次, 末值逐位相同', () => {
  const run = () => {
    const model = new PumpSyringeModel(makeConfig())
    const seq = [
      ['sampling.init', {}],
      ['sampling.prep', { air_buffer_ml: 0.2 }],
      ['sampling.aspirate', { air_gap_ml: 0.2, sample_volume_ml: 5 }],
      ['sampling.spot', { sample_volume_ml: 5 }],
    ]
    for (const [action, args] of seq) {
      model.onActionEnter(action, args)
      advance(model, 2, 2)
      model.onActionDone(action, args, 'DONE')
    }
    return model.snapshot().map((p) => p.volumeMl)
  }
  assert.deepEqual(run(), run())
})

test('单相位内严格帧率无关(守 step 里不许出现按帧计的逻辑)', () => {
  const drive = (fps) => {
    const model = new PumpSyringeModel(makeConfig())
    const args = { wash_volume_ml: 10, cleaning_count: 1 }
    model.onActionEnter('sampling.clean', args)
    advance(model, 2, 2, fps)     // 2s 时还在第 0 相位, 没跨过任何相位边界
    assert.equal(model.active[2].phase, 0)
    return model.volumeMl(2)
  }
  // interp 的指数衰减本就与帧率无关; 2026-08-05 实测 20/60/144fps 三者差 1.8e-15
  assert.ok(Math.abs(drive(60) - drive(20)) < 1e-9)
  assert.ok(Math.abs(drive(144) - drive(20)) < 1e-9)
})

test('跨相位的帧率偏差有界(相位切换按帧量化, 不是 bug)', () => {
  // 相位边界的判据是"距目标小于量程 1%", 这个判定每帧只做一次, 因此切换时刻最多差
  // 一帧, 后续相位整体平移这么多. 动作 done 时的吸附是赋值, 末态严格相等(由"反复吸→排
  // 二十次后精确回零"那条守着). 这里只守住"偏差不许失控".
  //
  // 2026-08-05 相位间加了 M 延时停顿(实机每段移动后停 1.5s 稳液)之后界放宽到 4%:
  // 停顿是**按时间**放行的(elapsed >= holdUntil), 20fps 下每个边界最多晚 50ms 放行,
  // 四个边界累计 0.2s; 落在 4s 斜坡上就是约 0.5mL. 之前只有值判据(两种帧率都在同一个
  // 值阈上切), 所以偏差才只有 5.65e-2 mL. 放宽是这项新行为的必然代价, 不是回归.
  const drive = (fps, secs) => {
    const model = new PumpSyringeModel(makeConfig())
    const args = { wash_volume_ml: 10, cleaning_count: 1 }
    model.onActionEnter('sampling.clean', args)
    advance(model, secs, 2, fps)
    return model.volumeMl(2)
  }
  for (const secs of [6, 12, 20]) {
    const drift = Math.abs(drive(60, secs) - drive(20, secs))
    assert.ok(drift < 25 * 0.04, `t=${secs}s 偏差 ${drift} 超过量程的 4%`)
  }
})

test('反复 吸→排 二十次后精确回零(done 的吸附是赋值不是趋近)', () => {
  const model = new PumpSyringeModel(makeConfig())
  for (let i = 0; i < 20; i += 1) {
    const asp = { air_gap_ml: 0.5, sample_volume_ml: 0 }
    model.onActionEnter('sampling.prep', { air_buffer_ml: 0.5 })
    model.onActionDone('sampling.prep', { air_buffer_ml: 0.5 }, 'DONE')
    void asp
    model.onActionEnter('sampling.init', {})
    model.onActionDone('sampling.init', {}, 'DONE')
  }
  assert.equal(model.volumeMl(2), 0)
})

// --- 断线重连 --------------------------------------------------------------

test('断流冻结末态, 绝不回零; 重连后位置仍不可信', () => {
  const model = new PumpSyringeModel(makeConfig())
  const args = { wash_volume_ml: 10, cleaning_count: 1 }
  model.onActionEnter('sampling.clean', args)
  advance(model, 1, 2)
  const frozen = model.volumeMl(2)
  assert.ok(frozen > 0)

  model.markDisconnected()
  assert.equal(model.isKnown(2), false)
  assert.equal(model.active[2], null)
  advance(model, 5, 2)
  assert.equal(model.volumeMl(2), frozen, '断流后不得继续移动, 更不得回零')

  model.markReconnected()
  assert.equal(model.isKnown(2), false, '重连本身不恢复可信度')
  model.onActionEnter('sampling.init', {})
  model.onActionDone('sampling.init', {}, 'DONE')
  assert.equal(model.isKnown(2), true)
  assert.equal(model.volumeMl(2), 0)
})

test('断流后到达的 done 拿不到 args 时不接管, 不会把柱塞拉到任何位置', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('develop.fill',
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 })
  advance(model, 1, 0)
  const frozen = model.volumeMl(0)
  model.markDisconnected()
  // _pendingNodeArgs 被清空后, done 只带得出空 args -> 路由不出泵
  assert.equal(model.onActionDone('develop.fill', {}, 'DONE'), false)
  assert.equal(model.volumeMl(0), frozen)
})

// --- 边界与快照 ------------------------------------------------------------

test('超量参数被钳到量程, 不产生越界柱塞', () => {
  const model = new PumpSyringeModel(makeConfig())
  const plan = model._resolve('sampling.flush',
    { flush_volume_ml: 20, outer_wash_volume_ml: 10, spot_head_volume_ml: 5 })
  assert.equal(plan.phases[0].targetMl, 25)
  model.onActionEnter('sampling.flush',
    { flush_volume_ml: 20, outer_wash_volume_ml: 10, spot_head_volume_ml: 5 })
  advance(model, 30, 2)
  assert.ok(model.level(2) <= 1)
})

test('相位总数封顶时压缩重复次数, 但快照仍报真实次数', () => {
  const model = new PumpSyringeModel(makeConfig())
  const plan = model._resolve('sampling.clean', { wash_volume_ml: 4, cleaning_count: 40 })
  assert.ok(plan.phases.length <= 64, `相位数应封顶, 实际 ${plan.phases.length}`)
  assert.equal(plan.outerRepeat, 40, '真实次数不被改写')
})

test('snapshot 字段齐全: estimated 恒真, 收集泵 rigged=false', () => {
  const model = new PumpSyringeModel(makeConfig())
  const snap = model.snapshot()
  assert.equal(snap.length, 4)
  assert.ok(snap.every((p) => p.estimated === true))
  assert.equal(snap.find((p) => p.id === 'COL').rigged, false)
  assert.equal(snap.find((p) => p.id === 'SMP').rigged, true)
  assert.ok(snap.every((p) => p.known === false), '冷启动时一律不可信')
})

// --- 阀位(T-04 4 通 / T-06 6 通) -------------------------------------------

test('相位带 port 时切阀; "output" 解析成该泵自己的出口', () => {
  const model = new PumpSyringeModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 }
  const plan = model._resolve('develop.fill', args)
  assert.equal(plan.phases[0].port, 2, '吸溶剂走 2 号口')
  assert.equal(plan.phases[1].port, 6, 'DEV1 的出口是 6(单测钉死的 /1...I6A0)')

  // DEV2 同一条动作表, 出口却是 1 —— 出口号是**每台泵自己的**, 不能写死进动作表
  const plan2 = model._resolve('develop.fill',
    { target_tank: 5, solvent_volume_ml: 20, up_liquid_repeat_count: 1 })
  assert.equal(plan2.phases[1].port, 1)
})

test('切阀走最短路径: 6 通阀从 6 号切 1 号只转 1/6 圈, 不倒转 5/6', () => {
  const model = new PumpSyringeModel(makeConfig())
  model._selectPort(0, 6)
  model.valves[0].value = model.valves[0].target     // 先到位
  const before = model.valves[0].value
  model._selectPort(0, 1)
  const delta = Math.abs(model.valves[0].target - before)
  assert.ok(Math.abs(delta - 1 / 6) < 1e-9, `应只转 1/6 圈, 实际 ${delta}`)
})

test('阀位角度是累计圈数 × 2π, 并随 step 缓动到位', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })   // 该相位 port: 3
  assert.equal(model.valvePort(2), 3)
  advance(model, 3, 2)
  // 4 通阀第 3 口 = (3-1)/4 = 0.5 圈 = π
  assert.ok(Math.abs(model.valveAngle(2) - Math.PI) < 1e-3,
    `应转到 π, 实际 ${model.valveAngle(2)}`)
})

test('越界或缺省的 port 一律不转阀 —— 转到不存在的口比不转更糟', () => {
  const model = new PumpSyringeModel(makeConfig())
  assert.equal(model._resolvePort(9, 2), null, '4 通阀的第 9 口不存在')
  assert.equal(model._resolvePort(undefined, 2), null)
  assert.equal(model._resolvePort(0, 2), null)
  // 收集泵没有 outputPort(指令串没被单测覆盖, 刻意不编) -> "output" 解析成 null
  assert.equal(model._resolvePort('output', 3), null)
  assert.equal(model.valvePort(0), null, '还没动作时阀位未知')
})

test('断流后阀停在当前口, 不回零也不继续转', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  advance(model, 3, 2)
  const frozen = model.valveAngle(2)
  model.markDisconnected()
  advance(model, 5, 2)
  assert.equal(model.valveAngle(2), frozen)
})

/** 03 几何真正建出来的角度表: 接口全挤在下半圈的 205°~335° 里均布, 不是 360° 均布 */
function withPortAngles(config) {
  const arc = (n) => Array.from({ length: n }, (_, k) => 205 + (335 - 205) * k / (n - 1))
  for (const pump of config.pumps) pump.valvePortAngles = arc(pump.valvePorts)
  return config
}

test('带 valvePortAngles 时指针转到该口的真实角, 而不是 360° 均布', () => {
  const model = new PumpSyringeModel(withPortAngles(makeConfig()))
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })   // 该相位 port: 3
  assert.equal(model.valvePort(2), 3)
  advance(model, 3, 2)
  // 4 通阀第 3 口的实际角 = 205 + 130×2/3 = 291.667°, 而按均布算会是 180° —— 差 111°,
  // 正好指到接针筒的平口那一侧, 那里一个口都没有
  const want = (205 + (335 - 205) * 2 / 3) / 360 * Math.PI * 2
  assert.ok(Math.abs(model.valveAngle(2) - want) < 1e-3,
    `应转到 ${want}, 实际 ${model.valveAngle(2)}`)
})

test('阀通道初值就落在 1 号口上 —— 0° 那边是平口, 没有口', () => {
  const model = new PumpSyringeModel(withPortAngles(makeConfig()))
  assert.ok(Math.abs(model.valveAngle(0) - 205 / 360 * Math.PI * 2) < 1e-9)
  // 缺角度表时退回老行为: 从 0 起手
  assert.equal(new PumpSyringeModel(makeConfig()).valveAngle(0), 0)
})

test('角度表长度对不上就退回均布, 绝不拿错位的角去转', () => {
  const config = withPortAngles(makeConfig())
  config.pumps[2].valvePortAngles = [205, 335]        // 4 通阀却只给了 2 个角
  const model = new PumpSyringeModel(config)
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  advance(model, 3, 2)
  assert.ok(Math.abs(model.valveAngle(2) - Math.PI) < 1e-3,
    `残缺的角度表必须整张作废并退回 (3-1)/4 圈, 实际 ${model.valveAngle(2)}`)
})

// --- 相位时长按 PLC 的 V/M 换算 ---------------------------------------------

test('相位时长 = |Δml| × 240 步/mL ÷ V + M/1000, 与实机 1:1', () => {
  const model = new PumpSyringeModel(makeConfig())
  assert.equal(model.stepsPerMl, 240, '6000 步 ÷ 25 mL = 240 步/mL')
  const plan = model._resolve('develop.fill',
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 })
  // 展开站 asp/disp 都是 V100, M500
  assert.ok(Math.abs(plan.phases[0].rampS - 48) < 1e-9,
    `吸 20mL @V100 应 48s, 实际 ${plan.phases[0].rampS}`)
  assert.ok(Math.abs(plan.phases[1].rampS - 48) < 1e-9)
  assert.equal(plan.phases[0].holdS, 0.5)
  assert.equal(plan.phases[0].speed, 100)
})

test('点样走 spot_disp_speed(9) 而不是 disp_speed(100) —— 差 11 倍', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.committed[2] = 3            // 先有 3mL 才打得出去(空筒打液会被 clamp 成 Δ=0)
  const plan = model._resolve('sampling.spot', { sample_volume_ml: 3 })
  assert.equal(plan.phases[0].targetMl, 0)
  // 3mL × 240 ÷ 9 = 80s; 若错用 disp_speed 只有 7.2s
  assert.equal(plan.phases[0].speed, 9)
  assert.ok(Math.abs(plan.phases[0].rampS - 80) < 1e-9,
    `点样 3mL @V9 应 80s, 实际 ${plan.phases[0].rampS}`)
})

test('速度取值链: 入参 > config.pump 实时 > manifest 快照 > 写死 rampS', () => {
  const model = new PumpSyringeModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 1 }
  assert.equal(model._resolve('develop.fill', args).phases[0].speed, 100)   // 快照

  model.setLiveSpeeds({ develop: { asp_speed: 400, disp_speed: 100, step_delay: 500 } })
  assert.equal(model._resolve('develop.fill', args).phases[0].speed, 400)   // 实时压过快照

  const withArg = model._resolve('develop.fill', { ...args, asp_speed: 1200 })
  assert.equal(withArg.phases[0].speed, 1200)                               // 入参压过实时

  // 完全取不到速度档时退回动作表写死的 rampS(老行为), 绝不停摆
  const bare = new PumpSyringeModel(makeConfig({ speeds: {} }))
  const fb = bare._resolve('develop.fill', args)
  assert.equal(fb.phases[0].speed, null)
  assert.equal(fb.phases[0].rampS, 4)
})

test('相位到位后先停 M 延时再进下一相', () => {
  // 不猜"第几秒到位": 逐帧跑, 记下"开始停顿"与"进入下一相"两个时刻, 断言其差 = M.
  // 展开站 M500 = 0.5s.
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('develop.fill',
    { target_tank: 1, solvent_volume_ml: 1, up_liquid_repeat_count: 1 })
  const dt = 1 / 240
  let holdStart = null
  let phase2At = null
  for (let i = 0; i < 240 * 10 && phase2At === null; i += 1) {
    model.step(dt)
    const info = model.phaseInfo(0)
    if (!info) break
    if (holdStart === null && info.holding) holdStart = model.elapsed
    if (info.index === 2) phase2At = model.elapsed
  }
  assert.ok(holdStart !== null, '应出现过"正停在 M 延时里"的状态')
  assert.ok(phase2At !== null, '延时结束后应进第 2 相')
  const held = phase2At - holdStart
  assert.ok(Math.abs(held - 0.5) < 2 * dt, `停顿应 ≈ M500 = 0.5s, 实际 ${held}`)
})

test('丝杆角度 = level × 满行程圈数 × 2π(导程 6mm / 行程 60mm = 10 圈)', () => {
  const model = new PumpSyringeModel(makeConfig())
  assert.equal(model.leadAngle(0), 0)
  model.plungers[0].value = model.syringeMl          // 满量程
  assert.ok(Math.abs(model.leadAngle(0) - 10 * Math.PI * 2) < 1e-9,
    `满行程应转 10 圈, 实际 ${model.leadAngle(0) / (Math.PI * 2)} 圈`)
  assert.equal(model.leadAngle(3), 0, '收集泵未装配, 圈数 0')
})

test('snapshot 带相位读数, 供面板显示"吸液 · V250 · 剩 N 秒"', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  const smp = model.snapshot().find((p) => p.id === 'SMP')
  assert.equal(smp.phase.op, 'aspirate')
  assert.equal(smp.phase.speed, 250)                // 上样站 asp_speed
  assert.equal(smp.phase.count, 1)
  // 3mL × 240 ÷ 250 = 2.88s
  assert.ok(Math.abs(smp.phase.remainS - 2.88) < 1e-9, `实际 ${smp.phase.remainS}`)
  assert.equal(model.snapshot().find((p) => p.id === 'DEV1').phase, null, '没在途时为 null')
})

test('snapshot 带阀位, 供面板显示"第 N 口"', () => {
  const model = new PumpSyringeModel(makeConfig())
  model.onActionEnter('sampling.prep', { air_buffer_ml: 3 })
  const smp = model.snapshot().find((p) => p.id === 'SMP')
  assert.equal(smp.valvePort, 3)
  assert.equal(smp.valvePorts, 4)
  assert.equal(model.snapshot().find((p) => p.id === 'DEV1').valvePorts, 6)
})

test('收集泵虽未装配, 数据仍走模型(面板要显读数)', () => {
  const config = makeConfig()
  config.actions['collect.collect'] = {
    pump: { from: 'fixed', id: 'COL' },
    repeatFrom: 'liquid_repeat_count',
    phases: [
      { op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, rampS: 3 },
      { op: 'dispense', to: 0, rampS: 3, speed: 'spot_head_disp_speed' },
    ],
  }
  const model = new PumpSyringeModel(config)
  assert.equal(model.onActionEnter('collect.collect',
    { solvent_volume_ml: 12, liquid_repeat_count: 1 }), true)
  const swing = advance(model, 4, 3)
  assert.ok(swing.max > 0.3, '未装配不影响数据侧的体积包络')
})

// --- expandPumpPlan: 离线消费方(flowSim/编译器镜像)的共享入口 ---------------

test('expandPumpPlan 与实时台 onActionEnter 展出的相位逐项相同(同构主测)', () => {
  const config = makeConfig()
  const args = { target_tank: 2, solvent_volume_ml: 20, up_liquid_repeat_count: 2, asp_speed: 100 }
  const model = new PumpSyringeModel(config)
  model.onActionEnter('develop.fill', args)
  const live = model.active[0].phases
  const plan = expandPumpPlan(config, 'develop.fill', args, 0)
  assert.equal(plan.pumpId, 'DEV1')
  assert.equal(plan.rigged, true)
  assert.deepEqual(
    plan.phases.map((p) => [p.targetMl, p.port, p.op]),
    live.map((p) => [p.targetMl, p.port, p.op]),
    '两条链展出的目标/口号/相位类别必须逐项相同 —— 分叉的表现是近似档与实时台高低不一',
  )
  // 时长同源: 20mL×240步 ÷ V100 = 48s
  assert.ok(Math.abs(plan.phases[0].rampS - 48) < 1e-9)
})

test('expandPumpPlan 的 maxPhases 压缩轮数不截相位, 终点体积不变', () => {
  const config = makeConfig()
  const args = { wash_volume_ml: 20, cleaning_count: 20 }
  const plan = expandPumpPlan(config, 'sampling.clean', args, 0, { maxPhases: 8 })
  assert.ok(plan.phases.length <= 8, `相位数 ${plan.phases.length} 超出预算`)
  assert.equal(plan.phases.length % 4, 0, '压缩的是轮数, 单轮的 4 个相位必须完整')
  assert.equal(plan.phases.at(-1).targetMl, 0, '终点体积必须与全轮数时相同')
  assert.equal(plan.outerRepeat, 20, '真实轮数要留给调用方写注记')
  assert.ok(plan.outerUsed < plan.outerRepeat, '压缩过就要能看出来')
})

test('expandPumpPlan 对未装配的收集泵回 rigged:false, 对不驱泵的动作回 null', () => {
  const config = makeConfig()
  config.actions['collect.collect'] = {
    pump: { from: 'fixed', id: 'COL' },
    phases: [{ op: 'aspirate', toFrom: { add: ['solvent_volume_ml'] }, rampS: 3 }],
  }
  const plan = expandPumpPlan(config, 'collect.collect', { solvent_volume_ml: 5 }, 0)
  assert.equal(plan.rigged, false, '收集泵没几何 —— 调用方据此退回时间格')
  assert.equal(expandPumpPlan(config, 'robot.home', {}, 0), null)
  assert.equal(expandPumpPlan(undefined, 'develop.fill', {}, 0), null)
})

test('expandPumpPlan 的 startMl 起算: prep 停在气隙位, aspirate 在其上相对叠加', () => {
  const config = makeConfig()
  const prep = expandPumpPlan(config, 'sampling.prep', {}, 0)
  assert.equal(prep.phases.at(-1).targetMl, 0.2, 'prep 默认气隙 0.2mL')
  const aspirate = expandPumpPlan(
    config, 'sampling.aspirate', { sample_volume_ml: 5 }, prep.phases.at(-1).targetMl,
  )
  assert.equal(aspirate.phases.at(-1).targetMl, 5.2,
    '相对相位必须基于上一动作留下的累计体积, 与实时台 committed 语义一致')
})
