/**
 * 功能: 展缸液体体积模型的单元测试.
 *
 * 这一层值得单测的原因: 它把两路语义不同的信号(动作包络 / Tank_State 相位)合成一条
 * 液面曲线, 而两者的优先级规则一旦写反, 表现是"注液涨到一半被拽回去"这种肉眼看着
 * 像卡顿、实际是数据打架的问题 —— 靠人工验收很难定位到具体代码.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { TankLiquidModel, resolveLiquidPlan } from '../../src/three-d/twin/bindings/TankLiquidModel.js'

if (typeof performance === 'undefined') {
  globalThis.performance = { now: () => 0 }
}

/** 与 gen_twin_manifest.TANK_LIQUID_* 同形的配置(数值取 2026-08-03 实测值) */
function makeConfig(overrides = {}) {
  return {
    cavity: {
      floorZMm: 654.721,
      rimZMm: 674.995,
      usableDepthMm: 20.274,
      freeAreaMm2: 4939.6,
      capacityMl: 102.48,
      mlPerMm: 4.94,
    },
    exaggeration: 1,
    pipeHoldupMl: 0,
    tankArg: 'target_tank',
    actions: {
      'develop.fill': {
        dir: 'fill',
        volumeFrom: ['solvent_volume_ml', 'up_liquid_repeat_count'],
        rampS: 12,
      },
      'develop.rinse_suction': { dir: 'drain', rampS: 8, delayFromArg: 'settle_s' },
      'develop.drain': { dir: 'drain', rampS: 10, rampFromArg: 'drain_duration_s' },
    },
    ...overrides,
  }
}

const STYLES = {
  0: { level: 0 },
  10: { level: 0.35 },
  40: { level: 0.75 },
  98: { level: 0 },
  default: { level: 0.6 },
}

/** 推进 seconds 秒(按 60 fps 分帧, 与真实渲染循环同量级) */
function advance(model, seconds) {
  const frames = Math.round(seconds * 60)
  for (let i = 0; i < frames; i += 1) model.step(1 / 60)
}

test('缺少 manifest.tankLiquid 时静默降级, 液面恒为 0 且不抛错', () => {
  const model = new TankLiquidModel(undefined)
  assert.equal(model.enabled, false)
  model.onActionEnter('develop.fill', { target_tank: 1, solvent_volume_ml: 25 })
  model.onTankStates([10, 0, 0, 0, 0, 0, 0, 0], STYLES)
  advance(model, 2)
  assert.equal(model.level(0), 0)
})

test('上液: 体积 = 配方体积 × 重复次数, 过程是渐近而非跳变', () => {
  const model = new TankLiquidModel(makeConfig())
  model.onActionEnter('develop.fill', {
    target_tank: 3, solvent_volume_ml: 20, up_liquid_repeat_count: 2,
  })

  // 起步瞬间还没涨
  assert.equal(model.volumeMl(2), 0)

  advance(model, 2)
  const mid = model.volumeMl(2)
  assert.ok(mid > 0 && mid < 40, `中途应在 0~40mL 之间, 实际 ${mid}`)

  advance(model, 10)
  assert.ok(model.volumeMl(2) > 38, `rampS 后应基本到位, 实际 ${model.volumeMl(2)}`)

  // 只影响目标缸
  assert.equal(model.volumeMl(0), 0)
})

test('动作 DONE 时吸附到终值; 非 DONE 停在当前液位不假装完成', () => {
  const model = new TankLiquidModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 25, up_liquid_repeat_count: 1 }

  model.onActionEnter('develop.fill', args)
  advance(model, 1)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 25)

  const failing = new TankLiquidModel(makeConfig())
  failing.onActionEnter('develop.fill', args)
  advance(failing, 1)
  const before = failing.volumeMl(0)
  failing.onActionDone('develop.fill', args, 'FAILED')
  advance(failing, 5)
  assert.ok(Math.abs(failing.volumeMl(0) - before) < 1e-6,
    `失败后应停在原位 ${before}, 实际 ${failing.volumeMl(0)}`)
})

test('排液把体积降到 0, 时长取 drain_duration_s', () => {
  const model = new TankLiquidModel(makeConfig())
  const fillArgs = { target_tank: 1, solvent_volume_ml: 50, up_liquid_repeat_count: 1 }
  model.onActionEnter('develop.fill', fillArgs)
  model.onActionDone('develop.fill', fillArgs, 'DONE')
  assert.equal(model.volumeMl(0), 50)

  model.onActionEnter('develop.drain', { target_tank: 1, drain_duration_s: 5 })
  advance(model, 1)
  assert.ok(model.volumeMl(0) < 50, '排液应已开始下降')
  advance(model, 5)
  assert.ok(model.volumeMl(0) < 3, `排液时长后应基本排空, 实际 ${model.volumeMl(0)}`)
})

test('润洗抽吸的 settle_s 期间液面保持不动, 到点才开始落', () => {
  const model = new TankLiquidModel(makeConfig())
  const fillArgs = { target_tank: 2, solvent_volume_ml: 30, up_liquid_repeat_count: 1 }
  model.onActionEnter('develop.fill', fillArgs)
  model.onActionDone('develop.fill', fillArgs, 'DONE')

  model.onActionEnter('develop.rinse_suction', { target_tank: 2, settle_s: 3 })
  advance(model, 2)
  assert.equal(model.volumeMl(1), 30, '沉降期内不应下降')

  advance(model, 2)
  assert.ok(model.volumeMl(1) < 30, '沉降结束后应开始下降')
})

// —— 双源冲突规则: 本文件最要紧的一组 ——————————————————————————————

test('动作在途时 Tank_State 不得把液面上抬', () => {
  const model = new TankLiquidModel(makeConfig())
  model.onActionEnter('develop.drain', { target_tank: 1, drain_duration_s: 5 })
  model.volumes[0].value = 10   // 假设排到一半

  // 相位仍报"展开中"(level 0.75 ≈ 77mL); 若被采纳, 液面会诡异地涨回去
  model.onTankStates([40, 0, 0, 0, 0, 0, 0, 0], STYLES)
  advance(model, 1)
  assert.ok(model.volumeMl(0) < 10, `应继续下降, 实际 ${model.volumeMl(0)}`)
})

test('动作在途时 Tank_State=98/0 允许提前收尾并结束包络', () => {
  const model = new TankLiquidModel(makeConfig())
  model.onActionEnter('develop.drain', { target_tank: 1, drain_duration_s: 60 })
  model.volumes[0].value = 40

  model.onTankStates([98, 0, 0, 0, 0, 0, 0, 0], STYLES)
  assert.equal(model.volumeMl(0), 0, '已排空应立即归零')
  assert.equal(model.active[0], null, '包络应随之结束')
})

test('从未见过动作时 Tank_State 作为锚点复位液面(冷启动/断线重连路径)', () => {
  const model = new TankLiquidModel(makeConfig())
  model.onTankStates([40, 0, 0, 0, 0, 0, 0, 0], STYLES)
  advance(model, 3)
  // level 0.75 × 102.48mL ≈ 76.9
  assert.ok(Math.abs(model.volumeMl(0) - 76.86) < 1.5,
    `应趋近相位锚点 76.9mL, 实际 ${model.volumeMl(0)}`)
})

test('动作结束后相位锚点不得把精确体积拽向观感档位', () => {
  // 回归用例: 上液 40mL 完成后, 缸相位仍是 10(准备中, level 0.35 ≈ 35.9mL).
  // 早前锚点无条件生效, 于是动作一结束液面就无端从 40 往 35.9 漂 —— 肉眼看着像"回落",
  // 实际是两路数据在打架。配方体积比观感档位精确, 必须压过它。
  const model = new TankLiquidModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 2 }
  model.onActionEnter('develop.fill', args)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 40)

  model.onTankStates([10, 0, 0, 0, 0, 0, 0, 0], STYLES)
  advance(model, 5)
  assert.equal(model.volumeMl(0), 40, `应稳在配方体积, 实际 ${model.volumeMl(0)}`)
})

test('Tank_State 归 0/98 后交回锚点管辖(缸已释放, 下次冷态由相位说了算)', () => {
  const model = new TankLiquidModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 40, up_liquid_repeat_count: 1 }
  model.onActionEnter('develop.fill', args)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.fromAction[0], true)

  model.onTankStates([98, 0, 0, 0, 0, 0, 0, 0], STYLES)
  assert.equal(model.volumeMl(0), 0)
  assert.equal(model.fromAction[0], false, '已排空后应交回锚点')

  // 此后相位锚点重新生效, 且按遥测节奏(而非上一个动作的 rampS)收敛
  assert.equal(model.volumes[0].period, 1.0, '通道节奏应交回遥测默认值')
  model.onTankStates([40, 0, 0, 0, 0, 0, 0, 0], STYLES)
  advance(model, 4)
  assert.ok(model.volumeMl(0) > 70, `锚点应重新接管, 实际 ${model.volumeMl(0)}`)
})

// —— 体积 → 液面高度的换算 ————————————————————————————————————

test('level 用实测自由截面积反算, 满槽容积对应满高', () => {
  const model = new TankLiquidModel(makeConfig())
  model.volumes[0].value = 102.48
  assert.ok(Math.abs(model.level(0) - 1) < 0.02, `满槽应到顶, 实际 ${model.level(0)}`)

  model.volumes[0].value = 51.24
  assert.ok(Math.abs(model.level(0) - 0.5) < 0.02, `半槽应到一半, 实际 ${model.level(0)}`)
})

test('exaggeration 放大视觉高度但不改面板 mL, 且到槽口封顶', () => {
  const model = new TankLiquidModel(makeConfig({ exaggeration: 2 }))
  model.volumes[0].value = 25.62      // 满槽的 1/4
  assert.ok(Math.abs(model.level(0) - 0.5) < 0.02, `×2 后应到一半, 实际 ${model.level(0)}`)
  assert.equal(model.volumeMl(0), 25.62, '面板 mL 不受放大影响')

  model.volumes[0].value = 80         // ×2 会超出槽口
  assert.equal(model.level(0), 1, '超出部分必须封顶, 不能画出槽外')
})

test('pipe_holdup_ml 从注入量里扣掉管路残留', () => {
  const model = new TankLiquidModel(makeConfig({ pipeHoldupMl: 3 }))
  const args = { target_tank: 1, solvent_volume_ml: 25, up_liquid_repeat_count: 1 }
  model.onActionEnter('develop.fill', args)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 22)
})

test('注入量超过槽容时按槽容封顶, 不产生越界液面', () => {
  const model = new TankLiquidModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 25, up_liquid_repeat_count: 20 }
  model.onActionEnter('develop.fill', args)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 102.48)
  assert.equal(model.level(0), 1)
})

// —— 不该被接管的输入 ——————————————————————————————————————

test('无关动作/缺缸号/越界缸号一律不接管', () => {
  const model = new TankLiquidModel(makeConfig())
  assert.equal(model.onActionEnter('develop.clean_line', { target_tank: 1 }), false,
    '清洗管路不动缸内液体')
  assert.equal(model.onActionEnter('robot.home', { target_tank: 1 }), false)
  assert.equal(model.onActionEnter('develop.fill', { solvent_volume_ml: 25 }), false,
    '缺缸号无法定位到缸')
  assert.equal(model.onActionEnter('develop.fill', { target_tank: 9, solvent_volume_ml: 25 }), false,
    '缸号越界')
  assert.equal(model.onActionEnter('develop.fill', { target_tank: 0, solvent_volume_ml: 25 }), false,
    '缸号是 1 基, 0 非法')
})

test('volumeFrom 里缺项按 1 倍算(流程 YAML 只写部分入参, 其余由执行器补默认值)', () => {
  const model = new TankLiquidModel(makeConfig())
  const args = { target_tank: 1, solvent_volume_ml: 12 }   // 没写 up_liquid_repeat_count
  model.onActionEnter('develop.fill', args)
  model.onActionDone('develop.fill', args, 'DONE')
  assert.equal(model.volumeMl(0), 12)
})

test('snapshotMl 给出 8 缸一位小数的读数', () => {
  const model = new TankLiquidModel(makeConfig())
  model.volumes[0].value = 12.3456
  const snapshot = model.snapshotMl()
  assert.equal(snapshot.length, 8)
  assert.equal(snapshot[0], 12.3)
  assert.equal(snapshot[7], 0)
})

test('_resolve 委托共享实现 —— 实时模型不许偷偷长出自己的一份体积规则', () => {
  // 离线链(demo/actionSim.js、demo/flowSim.js、clip_compiler)与本模型都要按同一条
  // "体积 = 各来源参数连乘"算. 两边各留一份的表现是"演示里注了 40mL、实况页显示 20mL",
  // 两边都看着挺正常, 没有任何自动指标会报警 —— 这条用例就是那个指标.
  const config = makeConfig()
  const model = new TankLiquidModel(config)
  const cases = [
    ['develop.fill', { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 3 }],
    ['develop.fill', { target_tank: 2, solvent_volume_ml: 12 }],            // 缺项按 1 倍
    ['develop.fill', { target_tank: 3, solvent_volume_ml: 999 }],           // 超槽容封顶
    ['develop.rinse_suction', { target_tank: 4, settle_s: 3 }],
    ['develop.drain', { target_tank: 5, drain_duration_s: 42 }],
    ['develop.fill', { target_tank: 9, solvent_volume_ml: 20 }],            // 缸号越界
    ['robot.home', { target_tank: 1 }],                                     // 无关动作
  ]
  for (const [action, args] of cases) {
    assert.deepEqual(
      model._resolve(action, args),
      resolveLiquidPlan(config, action, args),
      `${action} 的解析与共享实现不一致`,
    )
  }
})

// ---------------------------------------------------------------------------
// 后端权威液量 (仿真沙盒的 tank_liquid 事件) —— 有真值就不该再合成
// ---------------------------------------------------------------------------

test('onTankVolume: 后端权威液量直接就位, 并关掉包络与相位锚点两路合成', () => {
  const model = new TankLiquidModel(makeConfig())
  assert.equal(model.authoritative, false, '默认不是权威模式')

  model.onTankVolume({ type: 'tank_liquid', tank: 3, volume_ml: 41.2 })
  assert.equal(model.authoritative, true)
  // 直接就位而不插值: 后端 10Hz 推已经比任何插值都密, 再插一层只会滞后
  assert.equal(model.volumeMl(2), 41.2, '缸号是 1 基, 落到下标 2')

  // 此后动作包络不再改液面 (仍认领动作, 免得调用方去找别的消费者)
  const claimed = model.onActionEnter('develop.fill',
    { target_tank: 3, solvent_volume_ml: 20, up_liquid_repeat_count: 3 })
  assert.equal(claimed, true, '仍认领这条动作')
  model.step(30)
  assert.equal(model.volumeMl(2), 41.2, '包络不许把权威值拽走')

  // 相位锚点同样让位 —— 连 0/98 这两个"语义确凿"的也不许归零
  model.onTankStates([0, 0, 0, 0, 0, 0, 0, 0], {})
  assert.equal(model.volumeMl(2), 41.2, '锚点不许覆盖后端真值')

  // 新的一帧照常跟随
  model.onTankVolume({ tank: 3, volume_ml: 12.5 })
  assert.equal(model.volumeMl(2), 12.5)
})

test('onTankVolume: 脏载荷一律丢弃, 不污染液面', () => {
  const model = new TankLiquidModel(makeConfig())
  for (const bad of [null, {}, { tank: 0, volume_ml: 5 }, { tank: 9, volume_ml: 5 },
    { tank: 1, volume_ml: NaN }, { tank: 1 }, { tank: 1.5, volume_ml: 5 }]) {
    model.onTankVolume(bad)
  }
  assert.equal(model.authoritative, false, '脏帧不该把模型切进权威模式')
  assert.equal(model.volumeMl(0), 0)
})

test('★live 护栏: 从不调 onTankVolume 时, 包络与锚点逐字按老规则走', () => {
  // 真机通道永远不发 tank_liquid, 所以 live 页的行为必须与本次改动前完全一致。
  const model = new TankLiquidModel(makeConfig())
  model.onActionEnter('develop.fill',
    { target_tank: 1, solvent_volume_ml: 20, up_liquid_repeat_count: 2 })
  model.step(60)
  assert.ok(model.volumeMl(0) > 30, `包络仍该把 1 号缸注到 40mL 附近, 实际 ${model.volumeMl(0)}`)

  // 0=空闲 仍无条件归零并交回锚点管辖 (老规则原文)
  model.onTankStates([0, 0, 0, 0, 0, 0, 0, 0], {})
  assert.equal(model.volumeMl(0), 0)
  assert.equal(model.fromAction[0], false)
  assert.equal(model.authoritative, false, 'live 路径全程不该进权威模式')
})
