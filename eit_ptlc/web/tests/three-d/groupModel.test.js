/**
 * 功能: 材质组模型(GroupModel)与 part_groups 段写回的单测.
 *
 * 值得单测的理由: 组是"工程师定义合并规则"的载体, 单一隶属/往返一致/撤销联动
 * 任何一条坏掉都会让保存出去的合并规则与预览不一致 —— 而重跑一次要一分钟,
 * 靠肉眼对不出来.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { GroupModel } from '../../src/three-d/materials/groupModel.js'
import { patchPartGroups, readPartGroups } from '../../src/three-d/materials/yamlPatch.js'

const SAMPLE_YAML = `# 注释一个字都不能动
rules:
  - id: MAT_ALUMINUM
    label: 铝合金
appearance_overrides: {}
`

test('load → toSection 往返一致(parts 保序, 组名排序, 字段按 FIELDS 序)', () => {
  const model = new GroupModel()
  const n = model.load({
    面板铝件: { parts: ['右盖板', '左盖板'], roughness: 0.35, base_color: '#C8CCD2' },
    黑色件: { parts: ['拖链-1'], metalness: 0.2 },
    空组丢弃: { parts: [] },
    脏值: { parts: ['x'], roughness: 99 },
  })
  assert.equal(n, 3) // 空组被丢
  const section = model.toSection()
  // 组名按 UTF-16 码序排序(稳定可 diff 即可, 不追求拼音序)
  assert.deepEqual(Object.keys(section), ['面板铝件', '脏值', '黑色件'].sort())
  assert.deepEqual(section['面板铝件'].parts, ['右盖板', '左盖板']) // 保序
  // 字段按 FIELDS 序: base_color 在 roughness 前
  assert.deepEqual(Object.keys(section['面板铝件']), ['parts', 'base_color', 'roughness'])
  // 越界值被 clamp
  assert.equal(section['脏值'].roughness, 1)
})

test('单一隶属: 加入新组自动离开旧组, 旧组空则删除', () => {
  const model = new GroupModel()
  model.createGroup('A', ['x', 'y'])
  model.createGroup('B', ['y', 'z'])
  assert.deepEqual(model.partsOf('A'), ['x'])
  assert.deepEqual(model.partsOf('B'), ['y', 'z'])
  assert.equal(model.groupOfPart('y'), 'B')

  model.addParts('B', ['x'])
  assert.equal(model.names().includes('A'), false) // A 被掏空即删
  assert.deepEqual(model.partsOf('B'), ['y', 'z', 'x'])
})

test('createGroup 拒绝重名/空名/空成员', () => {
  const model = new GroupModel()
  assert.equal(model.createGroup('A', ['x']), true)
  assert.equal(model.createGroup('A', ['y']), false)
  assert.equal(model.createGroup('  ', ['y']), false)
  assert.equal(model.createGroup('B', []), false)
})

test('removePart/removeGroup 与参数联动清理', () => {
  const model = new GroupModel()
  model.createGroup('A', ['x', 'y'])
  model.setParam('A', 'roughness', 0.5)
  model.removePart('A', 'x')
  assert.deepEqual(model.partsOf('A'), ['y'])
  model.removePart('A', 'y') // 组空 → 组与参数一起删
  assert.equal(model.names().length, 0)
  assert.deepEqual(model.getParams('A'), {})
})

test('undo 同时回退结构与参数', () => {
  const model = new GroupModel()
  model.createGroup('A', ['x'])
  model.setParam('A', 'roughness', 0.3)
  model.createGroup('B', ['y'])
  assert.equal(model.undo(), true) // 回退建 B
  assert.deepEqual(model.names(), ['A'])
  assert.equal(model.getParams('A').roughness, 0.3)
})

test('part_groups 写回 YAML: 注释保全 + 三段共存 + 往返一致', () => {
  const model = new GroupModel()
  model.createGroup('面板铝件', ['左盖板', '右盖板'])
  model.setParam('面板铝件', 'base_color', '#C8CCD2')

  const out = patchPartGroups(SAMPLE_YAML, model)
  assert.match(out, /注释一个字都不能动/)
  assert.match(out, /rules:/)
  assert.match(out, /appearance_overrides:/)

  const back = readPartGroups(out)
  assert.deepEqual(back['面板铝件'], { parts: ['左盖板', '右盖板'], base_color: '#C8CCD2' })

  // 重新装入 → 再导出等价
  const model2 = new GroupModel()
  model2.load(back)
  assert.deepEqual(model2.toSection(), model.toSection())
})

test('readPartGroups 容错', () => {
  assert.deepEqual(readPartGroups(''), {})
  assert.deepEqual(readPartGroups('rules: []'), {})
})
