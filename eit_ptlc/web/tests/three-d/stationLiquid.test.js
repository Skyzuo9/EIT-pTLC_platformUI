/**
 * 驻位液体(收集样品瓶)链路的回归测试.
 *
 * 三层各锁一环:
 *   1. resolveStationLiquidPlan 纯函数 —— 前端两个消费方(flowSim/actionSim)共用的
 *      那一份规则(单轮体积连乘 / repeatFrom 轮数 / demoMaxRounds 截断 / 容量夹取);
 *      clip_compiler.emit_station_liquid 是它的 Python 镜像, 由下面的语料测试锁形.
 *   2. manifest.liquids 契约 —— gen_twin_manifest 产出的形状(cavity/exaggeration/
 *      actions 带 roundS 实机值与 demoS 演示值).
 *   3. 片段语料 —— flow.collect_execute 必须带座位起手式与液面斜坡,
 *      flow.collect_unload 起手瓶里必须带着洗脱液(PHASE_ENTRY_STATE.liquid_after).
 *
 * 与 gripperCorpus 同一条产物门禁约定: 管线产物不存在时静默跳过, 不算失败.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import { parseClip } from '../../src/three-d/anim/clipSchema.js'
import { resolveStationLiquidPlan } from '../../src/three-d/twin/bindings/TankLiquidModel.js'

const WORKSPACE_ROOT = process.env.PTLC_THREE_D_WORKSPACE || 'E:/eit_lab/pTLC_platformUI/eit_ptlc/three_d'
const CLIPS_DIR = path.join(WORKSPACE_ROOT, 'clips')
const MANIFEST_PATH = path.join(WORKSPACE_ROOT, 'models', 'device-manifest.official-cr5.json')

const BOTTLE_LIQUID_ID = 'liq_collect_bottle'

/** 读 JSON 产物; 不存在返回 null(产物门禁的通用形态: 不在就跳过) */
function readJson(file) {
  if (!fs.existsSync(file)) return null
  return JSON.parse(fs.readFileSync(file, 'utf-8'))
}

/** 读片段文档; 不存在返回 null */
function readClip(name) {
  const file = path.join(CLIPS_DIR, `${name}.yaml`)
  if (!fs.existsSync(file)) return null
  return parseClip(fs.readFileSync(file, 'utf-8'))
}

/**
 * 语料测试的上线开关: 正式 manifest 里已有 liquids 段才检片段.
 * 链路未上线(或片段还没按新 manifest 重编)时静默跳过 —— 与"产物不存在就跳过"
 * 同一条门禁约定, 避免在重编前的过渡窗口里误报红.
 */
function stationLiquidLive() {
  const manifest = readJson(MANIFEST_PATH)
  return Boolean(manifest?.liquids?.length)
}

/** 契约样例: 与 gen_twin_manifest.STATION_LIQUID_ACTIONS 的 collect-bottle 条目同形 */
function sampleSpec() {
  return {
    id: BOTTLE_LIQUID_ID,
    // 可用深 78 = 实测肩高 83.0 − 瓶底 5.0(瓶颈那 12mm 不计体积); π·11²·78 = 29.65mL
    cavity: { usableDepthMm: 78, freeAreaMm2: 380.1, capacityMl: 29.65, mlPerMm: 0.3801 },
    exaggeration: 1,
    actions: {
      'collect.collect': {
        dir: 'fill',
        volumeFrom: ['solvent_volume_ml'],
        repeatFrom: 'liquid_repeat_count',
        roundS: { pump: 2.1, transfer: 20.0, settle: 5.0 },
        demoS: { pump: 1.0, transfer: 6.0, settle: 2.0 },
        demoMaxRounds: 3,
      },
    },
  }
}

test('resolveStationLiquidPlan: 单轮体积×轮数逐轮累加, 时长照契约不换算', () => {
  const plan = resolveStationLiquidPlan(sampleSpec(), 'collect.collect',
    { solvent_volume_ml: 0.1, liquid_repeat_count: 2 })
  assert.ok(plan, '默认入参必须解析出计划')
  assert.equal(plan.liquidId, BOTTLE_LIQUID_ID)
  assert.equal(plan.roundsTotal, 2)
  assert.equal(plan.roundsShown, 2)
  assert.deepEqual(plan.rounds, [
    { fromMl: 0, toMl: 0.1 },
    { fromMl: 0.1, toMl: 0.2 },
  ])
  // 时长是契约值的原样透传: roundS 写标签(实机), demoS 上时间轴(演示)
  assert.deepEqual(plan.real, { pump: 2.1, transfer: 20.0, settle: 5.0 })
  assert.deepEqual(plan.demo, { pump: 1.0, transfer: 6.0, settle: 2.0 })
})

test('resolveStationLiquidPlan: demoMaxRounds 截断轮数, 容量夹取封顶', () => {
  const truncated = resolveStationLiquidPlan(sampleSpec(), 'collect.collect',
    { solvent_volume_ml: 0.1, liquid_repeat_count: 20 })
  assert.equal(truncated.roundsTotal, 20)
  assert.equal(truncated.roundsShown, 3, 'demoMaxRounds=3 必须截断')

  const capped = resolveStationLiquidPlan(sampleSpec(), 'collect.collect',
    { solvent_volume_ml: 25, liquid_repeat_count: 2 })
  assert.equal(capped.rounds[0].toMl, 25)
  assert.equal(capped.rounds[1].toMl, 29.65, '超过瓶容必须夹到 capacityMl')
})

test('resolveStationLiquidPlan: 不认识的动作/非 fill 方向返回 null', () => {
  assert.equal(resolveStationLiquidPlan(sampleSpec(), 'develop.fill', { solvent_volume_ml: 1 }), null)
  assert.equal(resolveStationLiquidPlan(sampleSpec(), 'collect.collect', null), null)
})

test('manifest.liquids: 收集瓶条目的契约形状(cavity/exaggeration/actions 双时长)', () => {
  const manifest = readJson(MANIFEST_PATH)
  if (!manifest) return // 还没跑过管线
  const liquids = manifest.liquids || []
  assert.ok(liquids.length >= 1, 'manifest.liquids 为空 —— gen_twin_manifest 没接到 03 的 bottle_liquid 段')
  const bottle = liquids.find((item) => item.id === BOTTLE_LIQUID_ID)
  assert.ok(bottle, `manifest.liquids 里没有 ${BOTTLE_LIQUID_ID}`)
  assert.match(String(bottle.node), /LIQUID_/, '液柱节点名必须带 LIQUID_ 前缀(材质规则+合并保护双重要求)')
  for (const key of ['usableDepthMm', 'freeAreaMm2', 'capacityMl', 'mlPerMm']) {
    assert.ok(Number(bottle.cavity?.[key]) > 0, `cavity.${key} 必须为正`)
  }
  assert.ok(Number(bottle.exaggeration) >= 1, 'exaggeration 缺失 —— 0.1mL 物理只有 0.26mm, 不放大等于看不见')
  const rule = bottle.actions?.['collect.collect']
  assert.ok(rule, 'actions 里必须有 collect.collect')
  assert.equal(rule.dir, 'fill')
  assert.ok(rule.roundS && rule.demoS, '实机 roundS 与演示 demoS 必须都在契约里 —— 消费方只读不换算')
})

test('语料: flow.collect_execute 座位起手式 + 逐轮液面斜坡', () => {
  if (!stationLiquidLive()) return // 链路未上线(正式 manifest 无 liquids)
  const doc = readClip('flow.collect_execute')
  if (!doc) return
  const steps = doc.steps || []

  // 起手式: 两个座位在 t=0 点亮(PHASE_ENTRY_STATE.states 播种)
  for (const id of ['STA_COLLECT_BOTTLE', 'STA_COLLECT_HOLDER']) {
    const intro = steps.find((step) => step.do?.state?.id === id && step.do.state.value === true)
    assert.ok(intro, `缺 ${id} 的 state:true 起手式 —— 执行段又要对着虚空操作了`)
    assert.equal(intro.at ?? 0, 0, `${id} 起手式必须在 t=0`)
  }

  // 液面: 至少一条指向收集瓶的斜坡, 默认配方终点 0.1 mL
  const liquidSteps = steps.filter((step) => step.do?.liquid?.id === BOTTLE_LIQUID_ID)
  assert.ok(liquidSteps.length >= 1,
    '没有任何瓶内液面步 —— collect.collect 还停在 6 秒纯 wait 的时间格')
  const last = liquidSteps[liquidSteps.length - 1]
  assert.ok(Math.abs(Number(last.do.liquid.to_ml) - 0.1) < 1e-6,
    `默认配方(0.1mL×1轮)的液面终点应为 0.1, 实际 ${last.do.liquid.to_ml}`)

  // home 播种: 通道不建就停在"满瓶"建模位(clipSchema 对 home.liquid_ml 逐条建通道)
  assert.equal(Number(doc.home?.liquid_ml?.[BOTTLE_LIQUID_ID]), 0,
    'home.liquid_ml 必须把收集瓶播种为 0(执行段起手是空瓶)')
})

test('语料: flow.collect_unload 起手瓶里带着洗脱液(liquid_after 承接)', () => {
  if (!stationLiquidLive()) return
  const doc = readClip('flow.collect_unload')
  if (!doc) return
  const homeMl = Number(doc.home?.liquid_ml?.[BOTTLE_LIQUID_ID])
  assert.ok(Number.isFinite(homeMl) && homeMl > 0,
    'collect_unload 的 home.liquid_ml 里收集瓶应带着 collect_execute 洗脱下来的液量 —— '
    + '否则下料时瓶又空了(PHASE_ENTRY_STATE.liquid_after 没生效)')
})

test('语料: flow.collect_cycle 内嵌执行段同样有液面', () => {
  if (!stationLiquidLive()) return
  const doc = readClip('flow.collect_cycle')
  if (!doc) return
  const liquidSteps = (doc.steps || []).filter((step) => step.do?.liquid?.id === BOTTLE_LIQUID_ID)
  assert.ok(liquidSteps.length >= 1, '周期片段的执行段没有液面步 —— 两条编译路径漂开了')
})
