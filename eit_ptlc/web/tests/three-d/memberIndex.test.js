/**
 * 功能: 合并块成员服务(memberIndex)的纯逻辑单测.
 *
 * 值得单测的理由: 三级兜底的块键解析是从 MaterialsView 的 staticMembers 逐行
 * 移植出来的, 等价性要钉死(尤其 .001 顺序漂移的后缀兜底); 两代报告格式的归一
 * 一旦回归, 成员卡会渲染 [object Object]; 候选排序是"点门板出把手"体验的核心.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  baseName,
  buildMemberIndex,
  loadMemberData,
  normalizeMember,
  rankCandidates,
  resolveMembers,
} from '../../src/three-d/materials/memberIndex.js'

test('baseName 只剥末尾 .00N 后缀', () => {
  assert.equal(baseName('门板-1.001'), '门板-1')
  assert.equal(baseName('门板-1'), '门板-1')
  assert.equal(baseName('v1.2 盖板'), 'v1.2 盖板')
  assert.equal(baseName(''), '')
  assert.equal(baseName(null), '')
})

test('normalizeMember 兼容两代格式', () => {
  assert.deepEqual(normalizeMember('门板-1'), { name: '门板-1', tris: 0, bbox: null })
  const rich = { name: '门板-1', tris: 120, bbox: { c: [1, 2, 3], s: [10, 20, 30] } }
  assert.deepEqual(normalizeMember(rich), rich)
  assert.deepEqual(normalizeMember({}), { name: '', tris: 0, bbox: null })
})

test('buildMemberIndex 建双向索引, byBase 按剥后缀的 base 名聚合', () => {
  const index = buildMemberIndex({
    'ST_A/STATIC_MAT_X': ['门板-1', '把手-2.001'],
    'ST_B/STATIC_MAT_X.001': [{ name: '把手-2', tris: 9 }],
  })
  assert.equal(index.blocks.size, 2)
  assert.equal(index.blocks.get('ST_A/STATIC_MAT_X').length, 2)
  assert.equal(index.byBase.get('把手-2').length, 2)
  assert.deepEqual(
    index.byBase.get('把手-2').map((e) => e.blockKey),
    ['ST_A/STATIC_MAT_X', 'ST_B/STATIC_MAT_X.001'],
  )
  assert.equal(buildMemberIndex(null), null)
})

test('resolveMembers 三级兜底: 原名全路径 → three 消毒名 → 后缀扫描', () => {
  const index = buildMemberIndex({
    'ST_COLLECT/STATIC_MAT_X.003': ['甲'],
    'ST_FRAME/STATIC_MAT_Y': ['乙'],
  })
  // 一级: 原名全路径直中
  assert.deepEqual(
    resolveMembers(index, 'ST_FRAME', 'STATIC_MAT_Y', 'ST_FRAME', 'STATIC_MAT_Y')[0].name,
    '乙',
  )
  // 二级: 原名失配(.001 漂移成 .003), three 消毒名命中
  assert.equal(
    resolveMembers(index, 'ST_COLLECT', 'STATIC_MAT_X.001', 'ST_COLLECT', 'STATIC_MAT_X.003')[0]
      .name,
    '甲',
  )
  // 三级: 两级全失配, 按 `/块名` 后缀扫描仍可命中
  assert.equal(
    resolveMembers(index, 'ST_XXX', 'STATIC_MAT_X.003', 'ST_YYY', 'STATIC_MAT_X003')[0].name,
    '甲',
  )
  // 未命中返回 [], 索引缺失返回 null
  assert.deepEqual(resolveMembers(index, 'ST_A', 'NOPE', 'ST_A', 'NOPE'), [])
  assert.equal(resolveMembers(null, 'ST_A', 'X', 'ST_A', 'X'), null)
})

test('rankCandidates: 含点优先且小件在前, 不含点按超出量补位, 截断生效', () => {
  const members = [
    { name: '门板', tris: 900, bbox: { c: [0, 0, 0], s: [800, 600, 20] } },
    { name: '把手', tris: 90, bbox: { c: [300, 0, 12], s: [30, 120, 25] } },
    { name: '远处支架', tris: 50, bbox: { c: [5000, 0, 0], s: [40, 40, 40] } },
    { name: '旧格式无盒', tris: 0, bbox: null },
  ]
  // 点在把手上(也落在门板盒内): 把手体积小, 排第一
  const onHandle = rankCandidates(members, [300, 10, 10])
  assert.deepEqual(
    onHandle.list.map((m) => m.name),
    ['把手', '门板', '远处支架'],
  )
  assert.equal(onHandle.containCount, 2)
  assert.equal(onHandle.total, 4)
  // 点在门板中央(把手盒外): 只有门板含点, 其余按距离补位
  const onDoor = rankCandidates(members, [-300, 0, 0])
  assert.equal(onDoor.list[0].name, '门板')
  assert.equal(onDoor.containCount, 1)
  // 截断
  assert.equal(rankCandidates(members, [0, 0, 0], { limit: 1 }).list.length, 1)
  // 容差: 点在盒外 1mm 内仍算含点(吸收 04 量化/焊接漂移)
  const nearEdge = rankCandidates(
    [{ name: '薄板', tris: 1, bbox: { c: [0, 0, 0], s: [10, 10, 2] } }],
    [0, 0, 1.9],
    { tol: 2 },
  )
  assert.equal(nearEdge.containCount, 1)
})

test('loadMemberData: 中间件优先, 失败回退部署产物, 全无返回 null', async () => {
  const blocks = { 'ST_A/STATIC_X': ['甲'] }
  let requestedPath = ''
  // 中间件可用
  const fromApi = await loadMemberData(
    { readFile: async () => JSON.stringify({ join: { members: blocks } }) },
    async () => ({ ok: false }),
  )
  assert.deepEqual(fromApi, blocks)
  // 中间件炸了 → 部署产物兜底
  const fromDeploy = await loadMemberData(
    { readFile: async () => { throw new Error('offline') } },
    async (path) => {
      requestedPath = path
      return { ok: true, json: async () => ({ version: 1, blocks }) }
    },
  )
  assert.deepEqual(fromDeploy, blocks)
  assert.equal(requestedPath, '/api/3d/assets/models/merge-members.json')
  // 无中间件 + 老部署(404) → null
  const nothing = await loadMemberData(null, async () => ({ ok: false }))
  assert.equal(nothing, null)
})
