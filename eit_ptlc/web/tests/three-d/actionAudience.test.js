/**
 * 功能: 动作受众分类的漂移看门狗.
 *
 * 对着 actions.catalog.json 金样 (由 tools/gen_action_catalog_fixture.py 从
 * config/actions/**\/*.yaml 生成, pytest 侧逐字节比对防金样腐烂) 断言三件事:
 *   ① 目录里每个动作都有分类 —— 缺省归工程师, 所以这条恒真, 真正的价值是下一条;
 *   ② 白名单里每个名字都真的存在 —— 抓改名与手误 (写错一个字它就永远不出现在运维区);
 *   ③ 白名单里不许有 modes:[DEBUG] 的 —— 那种在运行模式下永远置灰, 放进"常用"是规格错误。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  ENGINEER_WARNING,
  NO_CONFIRM,
  OPS_ACTIONS,
  OPS_DEBUG_ONLY_ALLOWED,
  RESOURCE_GATE_ACTIONS,
  SUPERSEDED_BY,
  audienceOf,
  splitStationActions,
  supersededHint,
} from '../../src/three-d/twin/actionAudience.js'

const CATALOG = JSON.parse(readFileSync(
  fileURLToPath(new URL('./actions.catalog.json', import.meta.url)), 'utf8')).actions
const BY_NAME = new Map(CATALOG.map((a) => [a.name, a]))

/** 顶替件要到 manifest 里核实是否真的存在, 所以这里读的是真产物而不是夹具 */
const MANIFEST = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../../three_d/models/device-manifest.json', import.meta.url)), 'utf8'))
const AXIS_IDS = new Set((MANIFEST.axes || []).map((a) => a.id))
const MECHANISM_IDS = new Set((MANIFEST.realtime?.mechanisms || []).map((m) => m.id))

test('金样本身完好 (93 条, 每条有 name/kind)', () => {
  assert.ok(CATALOG.length >= 90, `动作数 ${CATALOG.length} 明显偏少, 金样可能没生成全`)
  for (const action of CATALOG) {
    assert.ok(action.name, '有动作缺 name')
    assert.ok(action.kind, `${action.name} 缺 kind`)
  }
})

test('① 目录里每个动作都能得到一个受众 (未登记的自动归工程师)', () => {
  for (const action of CATALOG) {
    assert.ok(['ops', 'engineer'].includes(audienceOf(action.name)),
      `${action.name} 分类结果非法`)
  }
})

test('② 运维白名单里的名字都真的存在 (抓改名/手误)', () => {
  for (const name of OPS_ACTIONS) {
    assert.ok(BY_NAME.has(name),
      `运维白名单里的 ${name} 在动作目录里不存在 —— 改名了还是拼错了?`)
  }
})

test('③ 运维白名单里的 DEBUG-only 动作必须逐条具名豁免 (其余混入即红)', () => {
  for (const name of OPS_ACTIONS) {
    const action = BY_NAME.get(name)
    if (OPS_DEBUG_ONLY_ALLOWED.has(name)) continue
    assert.ok(!(action.modes || []).includes('DEBUG'),
      `${name} 是 DEBUG-only, 放进常用区会在运行模式下永远置灰 —— 要么归工程师, `
      + '要么像 robot.home 一样进 OPS_DEBUG_ONLY_ALLOWED 并写明理由')
  }
  // 豁免集自身的卫生: 必须真是 DEBUG-only 且真在白名单里, 否则豁免名存实亡
  for (const name of OPS_DEBUG_ONLY_ALLOWED) {
    assert.ok(OPS_ACTIONS.has(name), `豁免集里的 ${name} 不在运维白名单, 豁免无意义`)
    assert.ok((BY_NAME.get(name)?.modes || []).includes('DEBUG'),
      `豁免集里的 ${name} 并非 DEBUG-only, 不需要豁免 —— 请把它移出豁免集`)
  }
  assert.deepEqual([...OPS_DEBUG_ONLY_ALLOWED], ['robot.home'],
    '豁免集扩员要走用户定案, 别悄悄加')
})

test('资源门钩子动作都真的存在于目录 (抓改名/手误)', () => {
  for (const name of RESOURCE_GATE_ACTIONS) {
    assert.ok(BY_NAME.has(name), `${name} 不在动作目录里`)
  }
})

test('资源钩子动作(真空泵开关)被整体隐藏, 没混进两个受众里', () => {
  for (const name of ['pump.vacuum_on', 'pump.vacuum_off']) {
    assert.ok(RESOURCE_GATE_ACTIONS.has(name), `${name} 应被标为资源门钩子`)
    assert.ok(!OPS_ACTIONS.has(name), `${name} 不该出现在运维白名单`)
    const { ops, engineer } = splitStationActions([{ name }])
    assert.equal(ops.length + engineer.length, 0, `${name} 不该被渲染到任何一堆`)
  }
})

test('急停在运维区, 且被豁免二次确认 (急停路径上不许有对话框)', () => {
  assert.ok(OPS_ACTIONS.has('robot.emergency_stop'))
  assert.ok(NO_CONFIRM.has('robot.emergency_stop'))
})

test('splitStationActions: 两堆互斥, 资源钩子被丢弃', () => {
  const input = [
    { name: 'robot.stop' }, { name: 'robot.set_do' },
    { name: 'pump.vacuum_on' }, { name: 'develop.init' }, { name: 'develop.fill' },
  ]
  const { ops, engineer } = splitStationActions(input)
  assert.deepEqual(ops.map((a) => a.name), ['robot.stop', 'develop.init'])
  assert.deepEqual(engineer.map((a) => a.name), ['robot.set_do', 'develop.fill'])
  assert.equal(ops.length + engineer.length, input.length - 1, '除资源钩子外不丢件')
})

test('splitStationActions: 空输入不炸', () => {
  assert.deepEqual(splitStationActions(null), { ops: [], engineer: [] })
})

test('泵站没有任何动作入口 (它那两条都是资源钩子, 人工开关走模块状态区的泵行)', () => {
  const pump = CATALOG.filter((a) => a.name.startsWith('pump.'))
  const { ops, engineer } = splitStationActions(pump)
  assert.equal(ops.length, 0)
  assert.equal(engineer.length, 0)
})

test('每个有动作的工位组, 运维区不该是空的 (泵站除外)', () => {
  const groups = new Map()
  for (const action of CATALOG) {
    if (!action.group) continue
    if (!groups.has(action.group)) groups.set(action.group, [])
    groups.get(action.group).push(action)
  }
  // 这些组要么是纯 VM 主机动作, 要么是全资源钩子, 要么两条动作都被同页的气缸行顶替,
  // 没有面向操作员的**动作**入口 —— 不代表该工位没事可做 (中转托盘的两只定位气缸就在
  // 「气缸开合」区, 见 SUPERSEDED_BY)
  const EXEMPT = new Set(['08_pump', '10_vision', '12_material', '11_staging_a'])
  for (const [group, actions] of groups) {
    if (EXEMPT.has(group)) continue
    const { ops } = splitStationActions(actions)
    assert.ok(ops.length > 0, `${group} 一条运维动作都没有 —— 该工位的常用区会是空的`)
  }
})

test('工程师提示语提到了"工程师指导"', () => {
  assert.match(ENGINEER_WARNING, /工程师指导/)
})

// ── 降级溯源 (SUPERSEDED_BY) ────────────────────────────────────────────────

test('降级表里的动作都真的存在, 且都已不在运维区', () => {
  for (const [name, entry] of SUPERSEDED_BY) {
    assert.ok(BY_NAME.has(name), `降级表里的 ${name} 在动作目录里不存在 —— 改名了还是拼错了?`)
    assert.ok(!OPS_ACTIONS.has(name), `${name} 既被标为已降级又还在运维白名单里, 自相矛盾`)
    assert.ok(entry.hint && entry.hint.length > 6, `${name} 的降级说明太短, 操作员看不懂去哪找`)
    assert.ok(['axis', 'mechanism', 'view'].includes(entry.kind), `${name} 的 kind 非法`)
  }
})

test('顶替件必须真的存在于 manifest —— 顶替件被改名时立刻红', () => {
  for (const [name, entry] of SUPERSEDED_BY) {
    if (entry.kind === 'view') {
      assert.equal(entry.id, null, `${name} 是 view 型, 不该带 id`)
      continue
    }
    const pool = entry.kind === 'axis' ? AXIS_IDS : MECHANISM_IDS
    assert.ok(pool.has(entry.id),
      `${name} 声称已被 ${entry.kind} 「${entry.id}」顶替, 但 manifest 里没有这个 id —— `
      + '要么顶替件被改名了, 要么当初就写错了; 无论哪种, 这条降级的理由已经不成立')
  }
})

test('supersededHint: 没降级过的动作返回空串', () => {
  assert.equal(supersededHint('develop.init'), '')
  assert.equal(supersededHint('不存在的动作'), '')
  assert.match(supersededHint('photoscrape.cam_x335'), /axis_9x/)
})

test('本轮降级的 11 条一条不多一条不少 (改动这张表要连带改计划与文案)', () => {
  assert.equal(SUPERSEDED_BY.size, 11)
  assert.equal(OPS_ACTIONS.size, 20)
})

test('④ 运维白名单里每条都带操作员短说明 hint (新动作进白名单前必须写)', () => {
  for (const name of OPS_ACTIONS) {
    assert.equal(BY_NAME.get(name)?.has_hint, true,
      `${name} 在 YAML 里没写 hint —— 常用区的动作必须有一句话短说明, `
      + '否则操作员面对的又是工程师排障长文')
  }
})
