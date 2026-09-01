/**
 * 功能: 薄层板规格覆盖(硅胶层厚度)的纯状态机测试.
 *
 * 重点锁两条:
 *   1. **单槽**, 不按 dark/light 分槽 —— 换主题不得改变板的物理厚度;
 *   2. 存储不可用/内容损坏时静默降级, 绝不抛(画面不该因为隐私模式打不开而白屏)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PLATE_FIELDS,
  PLATE_KEY,
  clampPlateValue,
  effectivePlateSpec,
  loadPlateOverrides,
  savePlateOverrides,
} from '../../src/three-d/twin/scene/plates/plateSettings.js'

/** 极简内存存储, 兼 API 兼容 localStorage。 */
function memoryStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    _map: map,
  }
}

test('字段范围与用户拍板一致: 0.1 ~ 2.0 mm', () => {
  const field = PLATE_FIELDS.find((item) => item.key === 'silicaMm')
  assert.equal(field.min, 0.1)
  assert.equal(field.max, 2.0)
  assert.equal(field.unit, 'mm')
})

test('夹取: 越界收边, 非法值返回 null(调用方据此忽略)', () => {
  assert.equal(clampPlateValue('silicaMm', 0), 0.1)
  assert.equal(clampPlateValue('silicaMm', 9), 2.0)
  assert.equal(clampPlateValue('silicaMm', 0.4), 0.4)
  assert.equal(clampPlateValue('silicaMm', 'x'), null)
  assert.equal(clampPlateValue('未知字段', 1), null)
})

test('读写往返一致, 且写入的是稀疏覆盖', () => {
  const storage = memoryStorage()
  savePlateOverrides(storage, { silicaMm: 0.6 })
  assert.deepEqual(loadPlateOverrides(storage), { silicaMm: 0.6 })
  assert.match(storage.getItem(PLATE_KEY), /"silicaMm":0\.6/)
})

test('空覆盖时删除整条记录, 不留空壳', () => {
  const storage = memoryStorage()
  savePlateOverrides(storage, { silicaMm: 0.6 })
  savePlateOverrides(storage, {})
  assert.equal(storage.getItem(PLATE_KEY), null)
  assert.deepEqual(loadPlateOverrides(storage), {})
})

test('存储里是损坏 JSON / 越界值时静默降级, 不抛', () => {
  assert.deepEqual(loadPlateOverrides(memoryStorage({ [PLATE_KEY]: '{坏' })), {})
  assert.deepEqual(loadPlateOverrides(memoryStorage({ [PLATE_KEY]: '{"silicaMm":99}' })), { silicaMm: 2.0 })
  assert.deepEqual(loadPlateOverrides(null), {})
})

test('存储写入抛异常时不影响调用方', () => {
  const hostile = {
    getItem: () => { throw new Error('blocked') },
    setItem: () => { throw new Error('quota') },
    removeItem: () => { throw new Error('blocked') },
  }
  assert.deepEqual(loadPlateOverrides(hostile), {})
  savePlateOverrides(hostile, { silicaMm: 1 })   // 不抛即通过
})

test('生效值 = 契约基准 ⊕ 用户覆盖', () => {
  const spec = { glassMm: 2.0, silicaMm: 0.25 }
  assert.deepEqual(effectivePlateSpec(spec, {}), { glassMm: 2.0, silicaMm: 0.25 })
  assert.deepEqual(effectivePlateSpec(spec, { silicaMm: 1.5 }), { glassMm: 2.0, silicaMm: 1.5 })
})

test('契约缺失时回落标准板 2 + 1(唯一有依据的默认), 不编造中位值', () => {
  assert.deepEqual(effectivePlateSpec(null, {}), { glassMm: 2.0, silicaMm: 1.0 })
  assert.deepEqual(effectivePlateSpec({}, {}), { glassMm: 2.0, silicaMm: 1.0 })
})

test('单槽: 覆盖与主题无关(存储里没有 dark/light 分槽)', () => {
  const storage = memoryStorage()
  savePlateOverrides(storage, { silicaMm: 1.75 })
  const raw = JSON.parse(storage.getItem(PLATE_KEY))
  assert.equal(raw.dark, undefined)
  assert.equal(raw.light, undefined)
  assert.equal(raw.silicaMm, 1.75)
})
