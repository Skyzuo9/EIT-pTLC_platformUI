/**
 * 功能: 锁住"昼夜共用一套观感参数"这件事 —— 显示设置基准两主题必须一致,
 *       且每个数值基准都落在面板滑块范围内.
 *
 * 为什么值得单独一个文件: 这三类回归都是**静默**的 ——
 *   1. 有人往 STAGES.dark 里加个 intensity, 派生 PALETTES 时被 RIG 盖掉, 表面看不出;
 *   2. 新默认值落在 DISPLAY_FIELDS 范围外, 面板一读就被夹掉, 用户看到的与代码写的不同
 *      (RIG.keyPos 解出的仰角 85° 恰好压在 max 上, 无余量).
 * 都不会抛错, 只会让"其他浏览器打开就是这个效果"这句话悄悄失效.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  PALETTES,
  RIG,
  STAGE_BASELINE,
  getDisplayBaseline,
} from '../../src/three-d/twin/scene/Environment.js'
import { SceneManager } from '../../src/three-d/twin/scene/SceneManager.js'
import {
  DISPLAY_KEY,
  FIELD_BY_KEY,
  LEGACY_DISPLAY_V1_KEY,
  LEGACY_LIGHTING_KEY,
  clampValue,
  defaultState,
  loadDisplayState,
} from '../../src/three-d/twin/scene/displaySettings.js'

/** RIG 里的键: 两套 PALETTES 在这些键上必须逐一相等 */
const RIG_KEYS = Object.keys(RIG)

test('PALETTES: 两主题在 RIG 的每个键上相等(STAGES 不许盖回来)', () => {
  for (const key of RIG_KEYS) {
    assert.deepEqual(
      PALETTES.dark[key],
      PALETTES.light[key],
      `${key} 昼夜不一致 —— 大概是 STAGES 里混进了 RIG 的键`,
    )
    assert.deepEqual(PALETTES.light[key], RIG[key], `${key} 没取到 RIG 的值`)
  }
})

test('getDisplayBaseline: 两主题深等(扣掉 STAGE_BASELINE 白名单)', () => {
  const dark = getDisplayBaseline('dark')
  const light = getDisplayBaseline('light')
  const exempt = new Set([
    ...Object.keys(STAGE_BASELINE.dark),
    ...Object.keys(STAGE_BASELINE.light),
  ])
  assert.deepEqual(Object.keys(dark).sort(), Object.keys(light).sort())
  for (const key of Object.keys(dark)) {
    if (exempt.has(key)) continue
    assert.deepEqual(dark[key], light[key], `${key} 昼夜基准不一致`)
  }
})

test('_displayBaseline: 两主题一致', () => {
  // prototype 直调: 该方法只读 getDisplayBaseline/常量, 不摸 WebGL 与 DOM
  const dark = SceneManager.prototype._displayBaseline.call({}, 'dark')
  const light = SceneManager.prototype._displayBaseline.call({}, 'light')
  const exempt = new Set([
    ...Object.keys(STAGE_BASELINE.dark),
    ...Object.keys(STAGE_BASELINE.light),
  ])
  assert.ok(Object.keys(dark).length > 20, '基准键数异常, 拼装可能被改坏')
  for (const key of Object.keys(dark)) {
    if (exempt.has(key)) continue
    assert.deepEqual(dark[key], light[key], `${key} 昼夜基准不一致`)
  }
})

test('每个数值基准都落在滑块范围内(不会被面板静默夹掉)', () => {
  for (const theme of ['dark', 'light']) {
    const baseline = SceneManager.prototype._displayBaseline.call({}, theme)
    for (const [key, value] of Object.entries(baseline)) {
      if (!FIELD_BY_KEY.has(key)) continue // 非面板字段(如 silicaMm 那批)跳过
      assert.deepEqual(
        clampValue(key, value),
        value,
        `${theme}.${key} = ${value} 会被 DISPLAY_FIELDS 夹取`,
      )
    }
  }
})

test('存储键为 v2, 且老浏览器的旧键一律不迁移', () => {
  assert.equal(DISPLAY_KEY, 'ptlc.display.v2')
  const map = new Map([
    [LEGACY_DISPLAY_V1_KEY, JSON.stringify({
      version: 1,
      dark: { brightness: 0.8, keyIntensity: 0.9 },
      light: { brightness: 1.2, envIntensity: 0.4 },
    })],
    [LEGACY_LIGHTING_KEY, JSON.stringify({ brightness: 0.7, reflection: 1.6 })],
  ])
  const storage = { getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: () => {} }
  assert.deepEqual(
    loadDisplayState(storage),
    defaultState(),
    '装着旧存档的浏览器也应看到代码默认外观',
  )
})
