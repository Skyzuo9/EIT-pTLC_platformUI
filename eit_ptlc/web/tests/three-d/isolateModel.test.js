/**
 * 功能: 孤立清单模型(IsolateModel)与 part_isolate 段写回的纯逻辑单测.
 *
 * 值得单测的理由: 拆出标记的键是"剥 .00N 的 base 名", 这是跨次运行稳定性的
 * 唯一保证 —— 带后缀写进 YAML 会在下次重跑时失配且不报错; 四段共存的往返
 * 若碰坏相邻段或吃掉注释, 会静默丢掉工程师的调色经验.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { IsolateModel } from '../../src/three-d/materials/isolateModel.js'
import {
  patchPartGroups,
  patchPartIsolate,
  patchPartOverrides,
  readPartGroups,
  readPartIsolate,
  readPartOverrides,
} from '../../src/three-d/materials/yamlPatch.js'
import { GroupModel } from '../../src/three-d/materials/groupModel.js'
import { OverrideModel } from '../../src/three-d/materials/overrideModel.js'

test('add/remove/has 一律按剥 .00N 的 base 名', () => {
  const model = new IsolateModel()
  assert.equal(model.add('门板-1.001'), true)
  assert.equal(model.has('门板-1'), true)
  assert.equal(model.has('门板-1.002'), true)
  // 同 base 重复添加无效
  assert.equal(model.add('门板-1'), false)
  assert.equal(model.remove('门板-1.003'), true)
  assert.equal(model.names.size, 0)
})

test('load 兼容列表正写法与手改成 map 的写法', () => {
  const model = new IsolateModel()
  assert.equal(model.load(['a-1', 'b-2.001', '  ', 'a-1']), 2)
  assert.deepEqual(model.toSection(), ['a-1', 'b-2'])
  assert.equal(model.load({ 'c-3': {}, 'd-4.005': null }), 2)
  assert.deepEqual(model.toSection(), ['c-3', 'd-4'])
  assert.equal(model.load(null), 0)
})

test('undo 快照回退, load 清空撤销栈', () => {
  const model = new IsolateModel()
  model.add('甲')
  model.add('乙')
  assert.equal(model.undo(), true)
  assert.deepEqual(model.toSection(), ['甲'])
  assert.equal(model.undo(), true)
  assert.deepEqual(model.toSection(), [])
  assert.equal(model.undo(), false)
  model.add('丙')
  model.load(['丁'])
  assert.equal(model.undo(), false)
})

test('part_isolate 写回后往返一致, 且不碰其他段与注释', () => {
  const sample = `# 这段注释很值钱, 写回时一个字都不能动
rules:
  - id: MAT_ALUMINUM
    label: 铝合金   # 行内注释也要保住
`
  const model = new IsolateModel()
  model.add('左盖板-1')
  model.add('PTLC-01-001 门板-2.001')

  const out = patchPartIsolate(sample, model)
  assert.match(out, /这段注释很值钱/)
  assert.match(out, /行内注释也要保住/)
  assert.match(out, /rules:/)
  assert.deepEqual(readPartIsolate(out), ['PTLC-01-001 门板-2', '左盖板-1'])
})

test('四段共存: 串联打补丁互不覆盖', () => {
  const partModel = new OverrideModel()
  partModel.setMany('零件甲', { base_color: '#112233' })
  const groupModel = new GroupModel()
  groupModel.createGroup('面板铝件', ['右盖板'])
  const isoModel = new IsolateModel()
  isoModel.add('门板-1')

  const out = patchPartIsolate(
    patchPartGroups(patchPartOverrides('', partModel), groupModel),
    isoModel,
  )
  assert.deepEqual(readPartOverrides(out), { 零件甲: { base_color: '#112233' } })
  assert.deepEqual(readPartGroups(out).面板铝件.parts, ['右盖板'])
  assert.deepEqual(readPartIsolate(out), ['门板-1'])
})

test('readPartIsolate 容错: 缺段/坏文本返回空, IsolateModel.load 均可吞', () => {
  const model = new IsolateModel()
  assert.equal(model.load(readPartIsolate('')), 0)
  assert.equal(model.load(readPartIsolate('rules: []')), 0)
  assert.equal(model.load(readPartIsolate(':::not yaml:::')), 0)
})

test('空清单也写出空段(留键给下个读文件的人)', () => {
  const out = patchPartIsolate('', new IsolateModel())
  assert.match(out, /part_isolate/)
})
