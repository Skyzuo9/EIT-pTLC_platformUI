/**
 * 功能: 零件级材质覆盖与材质快捷功能的纯逻辑单测.
 *
 * 值得单测的理由: part_overrides 是新落进 material_semantics.yaml 的段, 写回吃掉
 * 注释或碰坏相邻段会静默丢经验; 预设参数若过不了 sanitizePatch 会被静默丢字段,
 * 表现为"点了预设只变了一半".
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { cadColorOf, MATERIAL_PRESETS } from '../../src/three-d/materials/materialPresets.js'
import { OverrideModel, sanitizePatch } from '../../src/three-d/materials/overrideModel.js'
import {
  patchAppearanceOverrides,
  patchPartOverrides,
  readAppearanceOverrides,
  readPartOverrides,
} from '../../src/three-d/materials/yamlPatch.js'

const SAMPLE = `# 这段注释很值钱, 写回时一个字都不能动
rules:
  - id: MAT_ALUMINUM
    label: 铝合金   # 行内注释也要保住
    base_color: "#c5cad2"
appearance_overrides: {}
`

test('part_overrides 写回后往返一致, 且不碰其他段与注释', () => {
  const partModel = new OverrideModel()
  partModel.setMany('展缸清洗组件-1', { base_color: '#2F6FB2', roughness: 0.35 })
  partModel.setMany('jia_zhua_qi_gang', { metalness: 0.92 })

  const out = patchPartOverrides(SAMPLE, partModel)
  assert.match(out, /这段注释很值钱/)
  assert.match(out, /行内注释也要保住/)
  assert.match(out, /rules:/)

  const back = readPartOverrides(out)
  assert.deepEqual(back['展缸清洗组件-1'], { base_color: '#2F6FB2', roughness: 0.35 })
  assert.deepEqual(back['jia_zhua_qi_gang'], { metalness: 0.92 })
})

test('两段共存: 串联打补丁互不覆盖', () => {
  const classModel = new OverrideModel()
  classModel.setMany('MAT_ALUMINUM', { roughness: 0.2 })
  const partModel = new OverrideModel()
  partModel.setMany('零件甲', { base_color: '#112233' })

  const out = patchPartOverrides(patchAppearanceOverrides(SAMPLE, classModel), partModel)
  assert.deepEqual(readAppearanceOverrides(out), { MAT_ALUMINUM: { roughness: 0.2 } })
  assert.deepEqual(readPartOverrides(out), { 零件甲: { base_color: '#112233' } })
})

test('readPartOverrides 容错: 缺段/坏文本返回空对象', () => {
  assert.deepEqual(readPartOverrides(''), {})
  assert.deepEqual(readPartOverrides('rules: []'), {})
  assert.deepEqual(readPartOverrides(':::not yaml:::'), {})
})

test('全部预设经 sanitizePatch 无损(不会被静默丢字段)', () => {
  for (const preset of MATERIAL_PRESETS) {
    const clean = sanitizePatch(preset.patch)
    assert.deepEqual(
      Object.keys(clean).sort(),
      Object.keys(preset.patch).sort(),
      `预设「${preset.label}」有字段被 sanitizePatch 丢弃`,
    )
  }
})

test('setMany 批量写入只记一步撤销', () => {
  const model = new OverrideModel()
  model.set('MAT_X', 'roughness', 0.1)
  const n = model.setMany('MAT_X', { base_color: '#FF0000', metalness: 0.9, roughness: 0.3 })
  assert.equal(n, 3)
  assert.deepEqual(model.get('MAT_X'), { base_color: '#FF0000', metalness: 0.9, roughness: 0.3 })
  // 一次撤销整体回退到 setMany 之前
  assert.equal(model.undo(), true)
  assert.deepEqual(model.get('MAT_X'), { roughness: 0.1 })
})

test('cadColorOf 从实例名解码量化色', () => {
  assert.equal(cadColorOf('MAT_DEFAULT_FFFFFF'), '#FFFFFF')
  assert.equal(cadColorOf('MAT_CADGLASS_FFFFFF_A20'), '#FFFFFF')
  assert.equal(cadColorOf('MAT_NAT_00FFFF'), '#00FFFF')
  assert.equal(cadColorOf('MAT_STEEL_PLATE'), null)
  assert.equal(cadColorOf('MAT_PART_zhan_gang'), null)
  assert.equal(cadColorOf(''), null)
})
