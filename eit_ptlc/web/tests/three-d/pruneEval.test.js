/**
 * 功能: 减配口径求值(pruneEval)与规模预估(estimate)的单测.
 *
 * 值得单测的理由: 「减配后」视图声称"所见即管线产物", 靠的就是这里对
 * 显式保留 > 显式删除 > 正则保留 > 正则删除 > 尺寸阈值 这条优先级链的复刻.
 * 次序错一档, 预览就会骗人 —— 尤其是"正则保留挡不住显式删除"这种边界.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PartIndex } from '../../src/three-d/workbench/PartIndex.js'
import {
  compilePruneRules,
  evalEffectiveDeletes,
  previewStatus,
  ruleFingerprint,
  sourceStamp,
} from '../../src/three-d/workbench/pruneEval.js'
import { MARKS, SelectionModel } from '../../src/three-d/workbench/selectionModel.js'

/**
 * 功能: 用普通对象拼一个假零件索引(避开 three 场景图).
 * @param {object[]} roots 顶层节点描述树
 * @returns {object} 形状与 PartIndex 兼容的假索引
 */
function makeIndex(roots) {
  const parts = new Map()
  const visit = (node, parentName) => {
    const info = {
      key: node.key,
      name: node.name ?? node.key,
      chinese: node.chinese ?? '',
      origName: node.origName ?? node.name ?? node.key,
      alias: node.alias ?? '',
      longestMm: node.longestMm ?? 100,
      ownMeshes: node.ownMeshes ?? 1,
      ownTriangles: node.ownTriangles ?? 10,
      childNames: (node.children ?? []).map((child) => child.key),
      parentName,
    }
    parts.set(info.key, info)
    for (const child of node.children ?? []) visit(child, info.key)
    return info
  }
  const assemblies = roots.map((root) => visit(root, null))
  return { parts, assemblies, allNames: [...parts.keys()], get: (key) => parts.get(key) }
}

// -- 规则编译 ---------------------------------------------------------------

test('compilePruneRules: 坏正则被丢弃, 其余照常编译', () => {
  const rules = compilePruneRules({
    delete_patterns: ['luo_ding', '[无效('],
    keep_patterns: ['sensor'],
    min_dimension_mm: 6.0,
  })
  assert.equal(rules.deleteRes.length, 1)
  assert.equal(rules.keepRes.length, 1)
  assert.equal(rules.minDimensionMm, 6)
})

test('compilePruneRules: 空配置返回 null, 非法阈值归 null', () => {
  assert.equal(compilePruneRules(null), null)
  assert.equal(compilePruneRules({ min_dimension_mm: '不是数' }).minDimensionMm, null)
})

// -- 有效删除集 -------------------------------------------------------------

test('rules 为 null 时退化为只算显式标记, 且删除沿子树连带', () => {
  const index = makeIndex([
    { key: 'asm', children: [{ key: 'child_a' }, { key: 'child_b' }] },
    { key: 'other' },
  ])
  const model = new SelectionModel()
  model.markNames(['asm'], MARKS.DELETE)

  const set = evalEffectiveDeletes(index, model, null)
  assert.deepEqual([...set].sort(), ['asm', 'child_a', 'child_b'])
})

test('正则命中非叶节点时整棵子树进集合', () => {
  const index = makeIndex([
    { key: 'tuo_lian_asm', children: [{ key: 'link_1' }, { key: 'link_2' }] },
    { key: 'frame' },
  ])
  const rules = compilePruneRules({ delete_patterns: ['tuo_lian'] })

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules)
  assert.deepEqual([...set].sort(), ['link_1', 'link_2', 'tuo_lian_asm'])
})

test('显式保留能豁免祖先的正则删除, 其余兄弟照删', () => {
  const index = makeIndex([
    { key: 'tuo_lian_asm', children: [{ key: 'link_keep' }, { key: 'link_gone' }] },
  ])
  const rules = compilePruneRules({ delete_patterns: ['tuo_lian'] })
  const model = new SelectionModel()
  model.markNames(['link_keep'], MARKS.KEEP)

  const set = evalEffectiveDeletes(index, model, rules)
  assert.equal(set.has('link_keep'), false)
  assert.equal(set.has('link_gone'), true)
  assert.equal(set.has('tuo_lian_asm'), true)
})

test('正则保留挡不住显式删除(优先级: 显式删除 > 正则保留)', () => {
  const index = makeIndex([{ key: 'sensor_x' }])
  const rules = compilePruneRules({ keep_patterns: ['sensor'] })
  const model = new SelectionModel()
  model.markNames(['sensor_x'], MARKS.DELETE)

  const set = evalEffectiveDeletes(index, model, rules)
  assert.equal(set.has('sensor_x'), true)
})

test('正则保留能挡住正则删除与尺寸阈值', () => {
  const index = makeIndex([
    { key: 'guang_dian_kai_guan', longestMm: 3 },
    { key: 'sui_pian', longestMm: 3 },
  ])
  const rules = compilePruneRules({
    delete_patterns: ['kai_guan'],
    keep_patterns: ['guang_dian'],
    min_dimension_mm: 6.0,
  })

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules)
  assert.equal(set.has('guang_dian_kai_guan'), false) // 保留规则赢
  assert.equal(set.has('sui_pian'), true) // 6mm 阈值删掉
})

test('尺寸阈值只对叶子生效, 小包围盒的装配不受它牵连', () => {
  const index = makeIndex([
    { key: 'tiny_asm', longestMm: 3, children: [{ key: 'tiny_leaf', longestMm: 3 }] },
  ])
  const rules = compilePruneRules({ min_dimension_mm: 6.0 })

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules)
  assert.equal(set.has('tiny_asm'), false)
  assert.equal(set.has('tiny_leaf'), true)
})

test('拼音正则经 alias 命中中文名零件(原生 GLB 的口径对齐)', () => {
  const index = makeIndex([
    { key: '30高X25宽线槽1260-1', alias: '30_gao_X25_kuan_xian_cao_1260' },
    { key: '某个支架-1' },
  ])
  const rules = compilePruneRules({ delete_patterns: ['xian_cao'] })

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules)
  assert.equal(set.has('30高X25宽线槽1260-1'), true)
  assert.equal(set.has('某个支架-1'), false)
})

test('_aliasFor 会剥掉实例后缀 -N 再查反查表', () => {
  const fake = {
    slugOf: new Map([['30高X25宽线槽1260', '30_gao_X25_kuan_xian_cao_1260']]),
  }
  const alias = PartIndex.prototype._aliasFor.call(fake, '30高X25宽线槽1260-3', '30高X25宽线槽1260-3')
  assert.equal(alias, '30_gao_X25_kuan_xian_cao_1260')
  assert.equal(PartIndex.prototype._aliasFor.call(fake, '别的零件-1', '别的零件-1'), '')
})

test('正则对中文名与 glTF 原名同样命中', () => {
  const index = makeIndex([
    { key: 'slug_a', chinese: '内六角螺钉M4' },
    { key: 'slug_b', origName: 'GB-T70 螺钉' },
    { key: 'slug_c' },
  ])
  const rules = compilePruneRules({ delete_patterns: ['螺钉'] })

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules)
  assert.deepEqual([...set].sort(), ['slug_a', 'slug_b'])
})

// -- 标红基线 ---------------------------------------------------------------

test('sourceStamp 与管线 03_clean_model.source_stamp 逐位一致', () => {
  // 值取自 Python 侧实跑, 钉住的是跨语言等价 —— 两边算法一漂, 戳就永远对不上,
  // 页面会挂着一条修不掉的"预览为近似", 而那正是本来要避免的噪声.
  assert.equal(sourceStamp(''), '0:811c9dc5')
  assert.equal(sourceStamp('min_dimension_mm: 6.0\n'), '22:cf2b3c63')
  // 含中文: 长度前缀按 UTF-8 字节数(44)而非字符数(38)
  assert.equal(sourceStamp('keep_patterns:\n  - san_se_deng  # 三色灯\n'), '44:ca596eb1')
})

test('previewStatus: 缺基线/缺戳/戳不符/一致 四态分明, 且缺戳不判绿', () => {
  const stamp = sourceStamp('rules')
  assert.equal(previewStatus(null, stamp).state, 'missing')
  assert.equal(previewStatus({}, stamp).state, 'unstamped')
  assert.equal(previewStatus({ source_stamp: stamp }, '').state, 'unstamped')
  assert.equal(previewStatus({ source_stamp: '1:deadbeef' }, stamp).state, 'stale')
  assert.equal(previewStatus({ source_stamp: stamp }, stamp).state, 'ok')
})

test('基线可用时接管规则与尺寸: 管线说留的小零件不再被标红', () => {
  // 现实原型: 注射泵指示灯只有 4mm, 却是管线在 prune **之后**才造的合成零件, 从没
  // 经过删减; 早先浏览器拿尺寸阈值套它, 三颗灯常年顶着红色.
  const index = makeIndex([
    { key: '注射泵指示灯红-DEV1-3', longestMm: 4 },
    { key: 'luo_ding-1', longestMm: 4 },
  ])
  const rules = compilePruneRules({ delete_patterns: ['luo_ding'], min_dimension_mm: 6.0 })
  const baseline = { deleted: ['luo_ding-1'], reasons: { 'luo_ding-1': 'pattern' } }

  const set = evalEffectiveDeletes(index, new SelectionModel(), rules, baseline)
  assert.equal(set.has('注射泵指示灯红-DEV1-3'), false)
  assert.equal(set.has('luo_ding-1'), true)
})

test('基线里的区域分离节点照常标红(前端不需要任何特例)', () => {
  const name = 'Open CASCADE STEP translator 7.6 138.2-1__REGION_DELETE'
  const index = makeIndex([{ key: 'motor' }, { key: 'cable', origName: name }])
  const baseline = { deleted: [name], reasons: { [name]: 'region' } }

  const set = evalEffectiveDeletes(index, new SelectionModel(), null, baseline)
  assert.equal(set.has('cable'), true)
  assert.equal(set.has('motor'), false)
})

test('基线里 reason=explicit 的条目不算数, 取消标记后红色立刻退', () => {
  // 显式那一档与 model.marks 同源(都来自 prune_list.yaml 的 explicit_delete),
  // 两边都采信的话取消标记也退不掉红, 得等重跑 raw —— 而工作台的活正是反复标了又改.
  const index = makeIndex([{ key: 'bracket' }])
  const baseline = { deleted: ['bracket'], reasons: { bracket: 'explicit' } }

  const model = new SelectionModel()
  model.markNames(['bracket'], MARKS.DELETE)
  assert.equal(evalEffectiveDeletes(index, model, null, baseline).has('bracket'), true)

  model.markNames(['bracket'], null) // 取消标记
  assert.equal(evalEffectiveDeletes(index, model, null, baseline).has('bracket'), false)
})

test('未保存的显式保留压得住基线, 未保存的显式删除与它同向叠加', () => {
  const index = makeIndex([{ key: 'a' }, { key: 'b' }])
  const baseline = { deleted: ['a'], reasons: { a: 'size' } }
  const model = new SelectionModel()
  model.markNames(['a'], MARKS.KEEP)
  model.markNames(['b'], MARKS.DELETE)

  const set = evalEffectiveDeletes(index, model, null, baseline)
  assert.equal(set.has('a'), false)
  assert.equal(set.has('b'), true)
})

test('基线名字带空格时按归一名对齐(与管线 _norm 同口径)', () => {
  const index = makeIndex([{ key: 'Open_CASCADE_1', origName: 'Open CASCADE 1' }])
  const baseline = { deleted: ['Open CASCADE 1'], reasons: { 'Open CASCADE 1': 'size' } }

  assert.equal(evalEffectiveDeletes(index, new SelectionModel(), null, baseline).has('Open_CASCADE_1'), true)
})

test('ruleFingerprint 只认规则档: 改显式名单不算变, 改阈值算变', () => {
  const base = { delete_patterns: ['luo_ding'], min_dimension_mm: 6, explicit_delete: ['x'] }
  assert.equal(
    ruleFingerprint(base),
    ruleFingerprint({ ...base, explicit_delete: ['x', 'y'], explicit_keep: ['z'] }),
  )
  assert.notEqual(ruleFingerprint(base), ruleFingerprint({ ...base, min_dimension_mm: 8 }))
  assert.notEqual(ruleFingerprint(base), ruleFingerprint({ ...base, region_delete: [{ node: 'n' }] }))
})

// -- 规模预估 ---------------------------------------------------------------

test('estimate 带有效删除集时不整树剪断: 被豁免的子件仍计入删减后规模', () => {
  const index = makeIndex([
    {
      key: 'asm',
      ownTriangles: 100,
      children: [
        { key: 'kept_child', ownTriangles: 40 },
        { key: 'gone_child', ownTriangles: 60 },
      ],
    },
  ])
  const model = new SelectionModel()
  const set = new Set(['asm', 'gone_child']) // kept_child 被豁免, 不在集合里

  const result = PartIndex.prototype.estimate.call(index, model, set)
  assert.equal(result.triangles, 200)
  assert.equal(result.afterTriangles, 40) // 只有被豁免的子件活下来
  assert.equal(result.afterMeshes, 1)
})

test('estimate 缺省口径保持旧行为: 显式删除整树剪断', () => {
  const index = makeIndex([
    { key: 'asm', ownTriangles: 100, children: [{ key: 'child', ownTriangles: 50 }] },
  ])
  const model = new SelectionModel()
  model.markNames(['asm'], MARKS.DELETE)

  const result = PartIndex.prototype.estimate.call(index, model)
  assert.equal(result.triangles, 150)
  assert.equal(result.afterTriangles, 0)
})
