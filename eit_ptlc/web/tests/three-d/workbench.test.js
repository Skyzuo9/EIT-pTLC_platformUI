/**
 * 功能: 装配工作台的核心逻辑单测 —— 标记模型与 YAML 回写.
 *
 * 这两处值得单测的理由: 它们是"授权决策"的载体. 标记算错会让用户删掉不该删的零件,
 * 回写把注释吃掉会让 prune_list.yaml 里那些"为什么这么删"的经验丢失 ——
 * 而那些注释比规则本身更值钱, 一旦丢了很难再补回来.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { PartIndex } from '../../src/three-d/workbench/PartIndex.js'
import { MARKS, restoreMarks, SelectionModel } from '../../src/three-d/workbench/selectionModel.js'
import { parseYaml, patchPruneList } from '../../src/three-d/workbench/yamlPatch.js'

// -- 标记模型 ---------------------------------------------------------------

test('选中与标记是两件事: 选中不改标记', () => {
  const model = new SelectionModel()
  model.select(['a', 'b'])
  assert.equal(model.counts().total, 0)
  model.markSelected(MARKS.DELETE)
  assert.equal(model.counts().delete, 2)
})

test('Ctrl 点击切换单个选中态', () => {
  const model = new SelectionModel()
  model.select(['a'])
  model.toggle('b')
  assert.deepEqual([...model.selected].sort(), ['a', 'b'])
  model.toggle('a')
  assert.deepEqual([...model.selected], ['b'])
})

test('重新标记会覆盖旧标记而不是叠加', () => {
  const model = new SelectionModel()
  model.markNames(['a'], MARKS.DELETE)
  model.markNames(['a'], MARKS.KEEP)
  const counts = model.counts()
  assert.equal(counts.delete, 0)
  assert.equal(counts.keep, 1)
  assert.equal(counts.total, 1)
})

test('标记 null 表示清除, 回到待定', () => {
  const model = new SelectionModel()
  model.markNames(['a', 'b'], MARKS.DELETE)
  model.markNames(['a'], null)
  assert.equal(model.counts().delete, 1)
  assert.equal(model.markOf('a'), undefined)
})

test('减面标记带比例, 缺省用默认值', () => {
  const model = new SelectionModel({ defaultDecimateRatio: 0.25 })
  model.markNames(['a'], MARKS.DECIMATE)
  model.markNames(['b'], MARKS.DECIMATE, 0.5)
  assert.equal(model.markOf('a').ratio, 0.25)
  assert.equal(model.markOf('b').ratio, 0.5)
})

test('撤销能回到上一步', () => {
  const model = new SelectionModel()
  model.markNames(['a'], MARKS.DELETE)
  model.markNames(['b'], MARKS.DELETE)
  assert.equal(model.counts().delete, 2)
  assert.equal(model.undo(), true)
  assert.equal(model.counts().delete, 1)
  assert.equal(model.undo(), true)
  assert.equal(model.counts().delete, 0)
  assert.equal(model.undo(), false, '栈空时应返回 false')
})

test('namesWithMark 结果已排序, 保证写出的 YAML 可 diff', () => {
  const model = new SelectionModel()
  model.markNames(['zebra', 'alpha', 'mid'], MARKS.DELETE)
  assert.deepEqual(model.namesWithMark(MARKS.DELETE), ['alpha', 'mid', 'zebra'])
})

// -- YAML 回写 --------------------------------------------------------------

const SAMPLE = `# 顶部说明注释, 必须保住
delete_patterns:
  # 紧固件: 数量极多但看不见
  - "luo_shuan"
  - "screw"

min_dimension_mm: 6.0

keep_patterns:
  - "sensor"
`

test('回写保留原文件的注释与既有段落', () => {
  const model = new SelectionModel()
  model.markNames(['bolt_a'], MARKS.DELETE)

  const next = patchPruneList(SAMPLE, model)
  assert.ok(next.includes('# 顶部说明注释, 必须保住'), '顶部注释丢了')
  assert.ok(next.includes('# 紧固件: 数量极多但看不见'), '规则内的注释丢了')
  assert.ok(next.includes('luo_shuan'), '原有正则规则丢了')
  assert.ok(next.includes('min_dimension_mm'), '原有标量丢了')
})

test('回写生成的 explicit 段可被重新解析', () => {
  const model = new SelectionModel()
  model.markNames(['part_a', 'part_b'], MARKS.DELETE)
  model.markNames(['keep_me'], MARKS.KEEP)
  model.markNames(['heavy'], MARKS.DECIMATE, 0.4)

  const parsed = parseYaml(patchPruneList(SAMPLE, model))
  assert.deepEqual(parsed.explicit_delete, ['part_a', 'part_b'])
  assert.deepEqual(parsed.explicit_keep, ['keep_me'])
  assert.deepEqual(parsed.explicit_decimate, [{ name: 'heavy', ratio: 0.4 }])
})

test('清空标记后 explicit 段整个消失, 不留空壳', () => {
  const model = new SelectionModel()
  model.markNames(['gone'], MARKS.DELETE)
  const withMark = patchPruneList(SAMPLE, model)
  assert.ok(withMark.includes('explicit_delete'))

  model.clearMarks()
  const cleared = patchPruneList(withMark, model)
  assert.ok(!cleared.includes('explicit_delete'), '标记清空后段落应被删掉')
  assert.ok(cleared.includes('luo_shuan'), '清空授权段不应影响正则规则')
})

test('索引键的唯一化后缀在写回时被剥掉', () => {
  // 索引给同名节点加了 #2 #3 后缀保证唯一; 但管线按原始名匹配,
  // 且"删掉这个型号的螺栓"本来就该对全部同名实例生效
  const model = new SelectionModel()
  model.markNames(['bolt', 'bolt#2', 'bolt#3'], MARKS.DELETE)
  const parsed = parseYaml(patchPruneList(SAMPLE, model))
  assert.deepEqual(parsed.explicit_delete, ['bolt'], '同名实例应折叠成一条')
})

test('同名实例被标了不同减面比例时取最激进的', () => {
  const model = new SelectionModel()
  model.markNames(['mod'], MARKS.DECIMATE, 0.6)
  model.markNames(['mod#2'], MARKS.DECIMATE, 0.2)
  const parsed = parseYaml(patchPruneList(SAMPLE, model))
  assert.deepEqual(parsed.explicit_decimate, [{ name: 'mod', ratio: 0.2 }])
})

// -- 恢复 -------------------------------------------------------------------

test('从 YAML 恢复标记, 并展开到全部同名实例', () => {
  const model = new SelectionModel()
  // 假索引: 三个同名实例
  const index = { allNames: ['bolt', 'bolt#2', 'bolt#3', 'other'] }
  const restored = restoreMarks({ explicit_delete: ['bolt'] }, model, index)

  assert.equal(restored, 3, '一个名字应展开成三个实例')
  assert.equal(model.markOf('bolt').mark, MARKS.DELETE)
  assert.equal(model.markOf('bolt#3').mark, MARKS.DELETE)
  assert.equal(model.markOf('other'), undefined)
})

test('恢复时无索引则按原名直接标记', () => {
  const model = new SelectionModel()
  restoreMarks({ explicit_keep: ['x'], explicit_decimate: [{ name: 'y', ratio: 0.5 }] }, model)
  assert.equal(model.markOf('x').mark, MARKS.KEEP)
  assert.equal(model.markOf('y').ratio, 0.5)
})

test('写回后再恢复能还原出等价的标记集(往返一致)', () => {
  const original = new SelectionModel()
  original.markNames(['a', 'b'], MARKS.DELETE)
  original.markNames(['c'], MARKS.KEEP)
  original.markNames(['d'], MARKS.DECIMATE, 0.35)

  const text = patchPruneList(SAMPLE, original)
  const restoredModel = new SelectionModel()
  restoreMarks(parseYaml(text), restoredModel)

  assert.deepEqual(restoredModel.namesWithMark(MARKS.DELETE), ['a', 'b'])
  assert.deepEqual(restoredModel.namesWithMark(MARKS.KEEP), ['c'])
  assert.equal(restoredModel.markOf('d').ratio, 0.35)
})

test('写盘走 glTF 原名, 恢复时翻译回 three 名(空格消毒的往返)', () => {
  // three 把 glTF 原名里的空格消毒成下划线: 工作台里的键是 three 名,
  // 但 prune_list 必须写原名, Blender 侧才能按名命中(硬约束 27)
  const origOf = new Map([['支架__A-1', '支架  A-1']])
  const fakeIndex = {
    savedNameOf: (key) => origOf.get(key) ?? key,
    keysForSavedName: (name) =>
      [...origOf.entries()].filter(([, orig]) => orig === name).map(([key]) => key),
  }

  const original = new SelectionModel()
  original.markNames(['支架__A-1'], MARKS.DELETE)
  const text = patchPruneList(SAMPLE, original, (name) => fakeIndex.savedNameOf(name))
  assert.match(text, /支架 {2}A-1/, 'yaml 里应是带空格的原名')
  assert.doesNotMatch(text, /支架__A-1/, 'yaml 里不应出现 three 消毒名')

  const restoredModel = new SelectionModel()
  restoreMarks(parseYaml(text), restoredModel, fakeIndex)
  assert.deepEqual(restoredModel.namesWithMark(MARKS.DELETE), ['支架__A-1'])
})

// -- 隐藏集合(层级树闭眼图标) ------------------------------------------------

/**
 * 功能: 造一个带一个三角形的网格, 名字即索引键.
 * @param {string} name 节点名
 * @returns {THREE.Mesh} 网格
 */
function makeMesh(name) {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute(
    'position',
    new THREE.BufferAttribute(new Float32Array([0, 0, 0, 1, 0, 0, 0, 1, 0]), 3),
  )
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial())
  mesh.name = name
  return mesh
}

/**
 * 功能: 搭一个最小装配 root > [asm(m1, m2), m3] 并建索引.
 * @returns {{index: PartIndex, m1: THREE.Mesh, m2: THREE.Mesh, m3: THREE.Mesh}}
 */
function makeIndex() {
  const root = new THREE.Group()
  root.name = 'MACHINE_ROOT'
  const asm = new THREE.Group()
  asm.name = 'asm'
  const m1 = makeMesh('m1')
  const m2 = makeMesh('m2')
  const m3 = makeMesh('m3')
  asm.add(m1, m2)
  root.add(asm, m3)
  return { index: new PartIndex(root), m1, m2, m3 }
}

test('hiddenKeys: 没有隐藏时为空集', () => {
  const { index } = makeIndex()
  assert.equal(index.hiddenKeys(new Set()).size, 0)
})

test('hiddenKeys: 只隐藏部分子件时, 父装配不算隐藏', () => {
  const { index, m1 } = makeIndex()
  const hidden = index.hiddenKeys(new Set([m1]))
  assert.deepEqual([...hidden].sort(), ['m1'])
})

test('hiddenKeys: 子树全部被藏时, 父装配一并计入', () => {
  const { index, m1, m2 } = makeIndex()
  const hidden = index.hiddenKeys(new Set([m1, m2]))
  assert.deepEqual([...hidden].sort(), ['asm', 'm1', 'm2'])
})

test('hiddenKeys: 兼容 ViewTools 隐藏台账的 Map 形态', () => {
  // ViewTools._hidden 是 Map<Object3D, 原可见性>, has() 语义与 Set 一致
  const { index, m3 } = makeIndex()
  const ledger = new Map([[m3, true]])
  assert.deepEqual([...index.hiddenKeys(ledger)], ['m3'])
})
