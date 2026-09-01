/**
 * 功能: 材质工作台核心逻辑的单元测试 —— 覆盖模型的增删改撤销, 与 YAML 定点回写.
 *
 * 这两块是纯函数, 不依赖 three/DOM, 所以能在 node --test 里直接跑.
 * 场景侧(MaterialsScene)依赖 WebGL, 由端到端验证覆盖.
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { normalizeHex, OverrideModel, sanitizePatch } from '../../src/three-d/materials/overrideModel.js'
import {
  patchAppearanceOverrides,
  readAppearanceOverrides,
} from '../../src/three-d/materials/yamlPatch.js'

test('颜色写法一律规整成大写 #RRGGBB', () => {
  assert.equal(normalizeHex('#abc'), '#AABBCC')
  assert.equal(normalizeHex('ff8800'), '#FF8800')
  assert.equal(normalizeHex('  #Ff8800  '), '#FF8800')
  assert.equal(normalizeHex('#12345'), null)
  assert.equal(normalizeHex('红色'), null)
  assert.equal(normalizeHex(null), null)
})

test('补丁校验丢掉不认识的字段并把数值夹进范围', () => {
  const clean = sanitizePatch({
    base_color: '#abc',
    roughness: 1.7,
    metalness: -0.4,
    ior: 99,
    不认识的字段: 1,
    emission_strength: '3.5',
  })
  assert.deepEqual(clean, {
    base_color: '#AABBCC',
    roughness: 1,
    metalness: 0,
    ior: 2.5,
    emission_strength: 3.5,
  })
})

test('非法数值被丢弃而不是变成 NaN', () => {
  assert.deepEqual(sanitizePatch({ roughness: '不是数' }), {})
  assert.deepEqual(sanitizePatch(null), {})
})

test('设值 / 清字段 / 清整条', () => {
  const model = new OverrideModel()
  model.set('MAT_A', 'base_color', '#112233')
  model.set('MAT_A', 'roughness', 0.3)
  assert.deepEqual(model.get('MAT_A'), { base_color: '#112233', roughness: 0.3 })

  // 传 null 表示清掉该字段, 回到规则原值
  model.set('MAT_A', 'roughness', null)
  assert.deepEqual(model.get('MAT_A'), { base_color: '#112233' })

  // 最后一个字段被清掉时, 整条覆盖应当消失, 而不是留个空壳
  model.set('MAT_A', 'base_color', null)
  assert.equal(model.entries.has('MAT_A'), false)
})

test('reset 清掉单条, resetAll 清空全部', () => {
  const model = new OverrideModel()
  model.set('MAT_A', 'roughness', 0.2)
  model.set('MAT_B', 'metalness', 0.9)
  model.reset('MAT_A')
  assert.equal(model.entries.has('MAT_A'), false)
  assert.equal(model.entries.has('MAT_B'), true)
  model.resetAll()
  assert.equal(model.entries.size, 0)
})

test('撤销能回到上一步', () => {
  const model = new OverrideModel()
  model.set('MAT_A', 'roughness', 0.2)
  model.set('MAT_A', 'roughness', 0.8)
  assert.equal(model.get('MAT_A').roughness, 0.8)
  assert.equal(model.undo(), true)
  assert.equal(model.get('MAT_A').roughness, 0.2)
  assert.equal(model.undo(), true)
  assert.equal(model.entries.size, 0)
  assert.equal(model.undo(), false)
})

test('版本号随每次变更自增, 供场景侧判断是否要重新上色', () => {
  const model = new OverrideModel()
  const before = model.version
  model.set('MAT_A', 'roughness', 0.2)
  assert.ok(model.version > before)
})

test('导出的段落键与字段都已排序, 保证产物可 diff', () => {
  const model = new OverrideModel()
  model.set('MAT_Z', 'roughness', 0.5)
  model.set('MAT_A', 'metalness', 0.1)
  model.set('MAT_A', 'base_color', '#FF0000')

  const section = model.toSection()
  assert.deepEqual(Object.keys(section), ['MAT_A', 'MAT_Z'])
  // 字段按 FIELDS 定义的顺序输出, 而不是按写入顺序
  assert.deepEqual(Object.keys(section.MAT_A), ['base_color', 'metalness'])
})

test('装入时丢掉脏数据', () => {
  const model = new OverrideModel()
  const loaded = model.load({
    MAT_OK: { base_color: '#00ff00' },
    MAT_BAD: { base_color: '不是颜色' },
    MAT_EMPTY: {},
  })
  assert.equal(loaded, 1)
  assert.deepEqual(model.get('MAT_OK'), { base_color: '#00FF00' })
})

test('回写只动 appearance_overrides 段, 其余注释与内容原样保留', () => {
  const original = [
    '# 顶部说明注释',
    'schema: ptlc.material-semantics/v1',
    '',
    '# 这段规则的来历说明, 比规则本身更值钱',
    'rules:',
    '  - id: MAT_ALUMINUM',
    '    patterns: ["6061"]',
    '',
    'appearance_overrides: {}',
  ].join('\n')

  const model = new OverrideModel()
  model.set('MAT_DEFAULT', 'base_color', '#5A6070')

  const next = patchAppearanceOverrides(original, model)
  assert.match(next, /# 顶部说明注释/)
  assert.match(next, /# 这段规则的来历说明/)
  assert.match(next, /MAT_ALUMINUM/)
  assert.match(next, /MAT_DEFAULT/)
  assert.match(next, /'?#5A6070'?/)
})

test('回写生成的段落能被重新读出来(往返一致)', () => {
  const model = new OverrideModel()
  model.set('MAT_A', 'base_color', '#112233')
  model.set('MAT_A', 'roughness', 0.35)
  model.set('MAT_B', 'metalness', 0.9)

  const text = patchAppearanceOverrides('schema: x\n', model)
  const back = readAppearanceOverrides(text)
  assert.deepEqual(back, {
    MAT_A: { base_color: '#112233', roughness: 0.35 },
    MAT_B: { metalness: 0.9 },
  })
})

test('清空后段落仍保留为空映射, 让下次看文件的人知道有这机制', () => {
  const model = new OverrideModel()
  model.set('MAT_A', 'roughness', 0.5)
  const withData = patchAppearanceOverrides('schema: x\n', model)
  assert.match(withData, /MAT_A/)

  model.resetAll()
  const cleared = patchAppearanceOverrides(withData, model)
  assert.match(cleared, /appearance_overrides/)
  assert.equal(readAppearanceOverrides(cleared).MAT_A, undefined)
})

test('读一个没有该段的文件返回空对象而不是抛异常', () => {
  assert.deepEqual(readAppearanceOverrides('schema: x\nrules: []\n'), {})
  assert.deepEqual(readAppearanceOverrides(''), {})
  assert.deepEqual(readAppearanceOverrides('这不是: [合法 yaml'), {})
})
