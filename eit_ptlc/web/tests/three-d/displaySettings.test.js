/**
 * 功能: 显示设置状态机的单元测试 —— 夹取/单槽覆盖/序列化/不迁移旧键/角度换算.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { RIG } from '../../src/three-d/twin/scene/Environment.js'
import {
  BACKGROUND_KEY,
  DEFAULT_BACKGROUND_SCENE,
  DISPLAY_KEY,
  LEGACY_DISPLAY_V1_KEY,
  LEGACY_LIGHTING_KEY,
  DISPLAY_FIELDS,
  FIELD_BY_KEY,
  defaultState,
  clampValue,
  setOverride,
  overridesFor,
  effectiveSettings,
  loadBackgroundScene,
  loadDisplayState,
  saveBackgroundScene,
  saveDisplayState,
  deriveKeyAngles,
  fromKeyAngles,
  exportPayload,
} from '../../src/three-d/twin/scene/displaySettings.js'

/** 造一个内存 storage 假对象 */
function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    dump: () => Object.fromEntries(map),
  }
}

test('字段表自洽: key 唯一且 dependsOn/tierKey 引用有效', () => {
  assert.equal(FIELD_BY_KEY.size, DISPLAY_FIELDS.length)
  for (const field of DISPLAY_FIELDS) {
    if (field.dependsOn) assert.ok(FIELD_BY_KEY.has(field.dependsOn), `${field.key} 的 dependsOn 悬空`)
    if (field.type === 'range') assert.ok(field.min < field.max && field.step > 0)
    if (field.type === 'select') assert.ok(field.options?.length >= 2, `${field.key} 缺少枚举选项`)
  }
})

test('clampValue: 范围夹取与无效输入', () => {
  assert.equal(clampValue('brightness', 99), 1.6)
  assert.equal(clampValue('brightness', -5), 0.3)
  assert.equal(clampValue('keyAzimuthDeg', -720), -180)
  assert.equal(clampValue('brightness', 'abc'), null)
  assert.equal(clampValue('不存在的键', 1), null)
})

test('clampValue: toggle 归一成布尔, 非布尔拒绝', () => {
  assert.equal(clampValue('fogEnabled', true), true)
  assert.equal(clampValue('fogEnabled', 0), false)
  assert.equal(clampValue('fogEnabled', 1), true)
  assert.equal(clampValue('fogEnabled', 'yes'), null)
})

test('clampValue: 背景枚举只接受已声明场景', () => {
  assert.equal(clampValue('backgroundScene', 'default'), 'default')
  assert.equal(clampValue('backgroundScene', 'laboratory'), 'laboratory')
  assert.equal(clampValue('backgroundScene', 'warehouse'), null)
})

test('地面网格在默认场景和实验室场景都可操作', () => {
  const field = FIELD_BY_KEY.get('gridVisible')
  assert.ok(field)
  assert.equal(field.backgrounds, undefined)
})

test('背景场景全局存储往返, 非法或损坏数据回默认', () => {
  const storage = fakeStorage()
  assert.equal(loadBackgroundScene(storage), DEFAULT_BACKGROUND_SCENE)
  assert.equal(saveBackgroundScene(storage, 'laboratory'), 'laboratory')
  assert.equal(loadBackgroundScene(storage), 'laboratory')

  storage.setItem(BACKGROUND_KEY, JSON.stringify({ version: 1, scene: 'warehouse' }))
  assert.equal(loadBackgroundScene(storage), DEFAULT_BACKGROUND_SCENE)
  storage.setItem(BACKGROUND_KEY, '{bad json')
  assert.equal(loadBackgroundScene(storage), DEFAULT_BACKGROUND_SCENE)
})

test('setOverride: 写入/删除/无效即删', () => {
  const state = defaultState()
  assert.equal(setOverride(state, 'keyIntensity', 3.7), 2.5)
  assert.deepEqual(overridesFor(state), { keyIntensity: 2.5 })
  assert.equal(setOverride(state, 'keyIntensity', null), null)
  assert.deepEqual(overridesFor(state), {})
  setOverride(state, 'keyIntensity', 1.2)
  setOverride(state, 'keyIntensity', NaN)
  assert.deepEqual(overridesFor(state), {}, '无效值应删除该覆盖')
})

test('覆盖是单槽: 不按主题分, 也没有 dark/light 键', () => {
  const state = defaultState()
  setOverride(state, 'brightness', 1.4)
  assert.equal(overridesFor(state).brightness, 1.4)
  assert.deepEqual(Object.keys(state).sort(), ['overrides', 'version'])
  assert.equal(state.version, 2)
})

test('effectiveSettings: 覆盖压过基准, 未覆盖跟随基准', () => {
  const eff = effectiveSettings({ a: 1, b: 2 }, { b: 9 })
  assert.deepEqual(eff, { a: 1, b: 9 })
})

test('save -> load 往返一致, 越界值在 load 时被夹取', () => {
  const storage = fakeStorage()
  const state = defaultState()
  setOverride(state, 'shadowIntensity', 0.5)
  setOverride(state, 'gridVisible', false)
  saveDisplayState(storage, state)

  // 手工污染: 越界数值与未知键
  const raw = JSON.parse(storage.getItem(DISPLAY_KEY))
  raw.overrides.shadowIntensity = 42
  raw.overrides.evilKey = 1
  storage.setItem(DISPLAY_KEY, JSON.stringify(raw))

  const loaded = loadDisplayState(storage)
  assert.equal(loaded.overrides.shadowIntensity, 1, '越界被夹到上限')
  assert.ok(!('evilKey' in loaded.overrides), '未知键被丢弃')
  assert.equal(loaded.overrides.gridVisible, false)
})

test('坏 JSON 回默认', () => {
  const storage = fakeStorage({ [DISPLAY_KEY]: '{{{not json' })
  assert.deepEqual(loadDisplayState(storage), defaultState())
})

test('v2 缺失时不从任何旧键迁移(旧值按旧基准调, 换算不过来)', () => {
  // 老浏览器的真实形态: v1 分槽覆盖填满 + 更远古的 lighting 旋钮都还在
  const legacy = fakeStorage({
    [LEGACY_DISPLAY_V1_KEY]: JSON.stringify({
      version: 1,
      dark: { brightness: 0.8, keyIntensity: 0.9, envIntensity: 0.9 },
      light: { brightness: 1.2, keyIntensity: 0.5 },
    }),
    [LEGACY_LIGHTING_KEY]: JSON.stringify({ brightness: 0.8, reflection: 1.5 }),
  })
  assert.deepEqual(loadDisplayState(legacy), defaultState(), '老浏览器也应看到代码默认外观')
  // 旧键不删除, 供回滚
  assert.ok(legacy.getItem(LEGACY_DISPLAY_V1_KEY))
  assert.ok(legacy.getItem(LEGACY_LIGHTING_KEY))
})

test('deriveKeyAngles: 共用布光台的 keyPos 换算(期望值从 RIG 派生)', () => {
  const norm = Math.hypot(...RIG.keyPos)
  const unit = RIG.keyPos.map((v) => v / norm)
  // 单位化前后同角: 换算只看方向, 与模长(影子定距用)无关
  assert.deepEqual(deriveKeyAngles(RIG.keyPos), deriveKeyAngles(unit))
  // 用户 2026-08-05 手调的那组角度, 固化后必须原样解出来
  assert.deepEqual(deriveKeyAngles(RIG.keyPos), { azimuthDeg: -51, elevationDeg: 85 })
})

test('fromKeyAngles 与 deriveKeyAngles 互逆(1° 取整容差)', () => {
  const source = RIG.keyPos
  const norm = Math.hypot(...source)
  const unit = source.map((v) => v / norm)
  const { azimuthDeg, elevationDeg } = deriveKeyAngles(source)
  const back = fromKeyAngles(azimuthDeg, elevationDeg)
  for (let i = 0; i < 3; i += 1) {
    assert.ok(Math.abs(back[i] - unit[i]) < 0.02, `分量 ${i} 偏差过大: ${back[i]} vs ${unit[i]}`)
  }
})

test('exportPayload 结构: 带覆盖与全量有效值', () => {
  const payload = exportPayload('light', 'high', { a: 1, b: 2 }, { b: 3 })
  assert.equal(payload.version, 2)
  assert.equal(payload.theme, 'light')
  assert.equal(payload.quality, 'high')
  assert.deepEqual(payload.overrides, { b: 3 })
  assert.deepEqual(payload.effective, { a: 1, b: 3 })
  assert.equal(typeof JSON.stringify(payload), 'string')
})
