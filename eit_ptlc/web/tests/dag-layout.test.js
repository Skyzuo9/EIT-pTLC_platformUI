// 调度画布布局纯函数: 分层 / 边 / 成环判定 / 新段 id
import test from 'node:test'
import assert from 'node:assert/strict'

import { ancestorSets, hasCycle, layerOf, layoutDag, nextSegId, wouldCycle,
         NODE_H, NODE_W, GAP_X, GAP_Y, PAD } from '../src/utils/dagLayout.js'

// parallel_v1 的真实形状 (s3∥s2, s7∥s6)
const PAR = [
  { id: 'af0', script: 'pf_af0_batch_startup', scope: 'batch', depends_on: [] },
  { id: 's1', script: 'pf_s1_load', scope: 'sample', depends_on: ['af0'] },
  { id: 's2', script: 'pf_s2_spot', scope: 'sample', depends_on: ['s1'] },
  { id: 's3', script: 'pf_s3_tank_prep', scope: 'sample', depends_on: ['s1'] },
  { id: 's4', script: 'pf_s4_photo_before', scope: 'sample', depends_on: ['s2'] },
  { id: 's5', script: 'pf_s5_to_tank', scope: 'sample', depends_on: ['s4', 's3'] },
  { id: 's6', script: 'pf_s6_develop_wait', scope: 'sample', depends_on: ['s5'] },
  { id: 's7', script: 'pf_s7_consumables', scope: 'sample', depends_on: ['s5'] },
  { id: 's8', script: 'pf_s8_to_scrape', scope: 'sample', depends_on: ['s6'] },
  { id: 's9', script: 'pf_s9_scrape', scope: 'sample', depends_on: ['s8', 's7'] },
  { id: 's10', script: 'pf_s10_collect', scope: 'sample', depends_on: ['s9'] },
  { id: 's11', script: 'pf_s11_unload', scope: 'sample', depends_on: ['s10'] },
]

const CHAIN = [
  { id: 'a', depends_on: [] },
  { id: 'b', depends_on: ['a'] },
  { id: 'c', depends_on: ['b'] },
]

test('layerOf: 最长路径分层, 并行段同层', () => {
  const lv = layerOf(PAR)
  assert.equal(lv.get('af0'), 0)
  assert.equal(lv.get('s1'), 1)
  assert.equal(lv.get('s2'), 2)
  assert.equal(lv.get('s3'), 2, 's3 与 s2 同层 (都依赖 s1) = 画布上横向并列')
  assert.equal(lv.get('s4'), 3)
  assert.equal(lv.get('s5'), 4, 's5 取 max(s4=3, s3=2)+1 —— 最长路径而非最短')
  assert.equal(lv.get('s6'), 5)
  assert.equal(lv.get('s7'), 5)
  assert.equal(lv.get('s11'), 9)
})

test('layoutDag: 层=行/层内并排居中, 边端点接出入口', () => {
  const { nodes, edges, layers, width, height } = layoutDag(PAR)
  assert.equal(nodes.length, 12)
  assert.deepEqual(layers.map((l) => l.length), [1, 1, 2, 1, 1, 2, 1, 1, 1, 1])
  assert.deepEqual(layers[2], ['s2', 's3'], '层内保声明序 (与 YAML 一致, 编辑时不跳位)')

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  assert.equal(byId.s2.y, byId.s3.y, '同层同一行')
  assert.notEqual(byId.s2.x, byId.s3.x)
  assert.equal(byId.s3.x - byId.s2.x, NODE_W + GAP_X)
  assert.equal(byId.s1.y - byId.af0.y, NODE_H + GAP_Y, '相邻层纵距 = 卡高+间隙')
  // 单节点层在最宽层 (2 个) 中居中
  assert.equal(byId.af0.x, PAD + (NODE_W + GAP_X) / 2)

  // 边数 = 全部 depends 条数; 端点吻合出入口
  assert.equal(edges.length, PAR.reduce((n, f) => n + f.depends_on.length, 0))
  const e = edges.find((x) => x.key === 's1->s2')
  assert.ok(e.d.startsWith(`M ${byId.s1.outPort.x} ${byId.s1.outPort.y}`))
  assert.ok(e.d.endsWith(`${byId.s2.inPort.x} ${byId.s2.inPort.y}`))

  assert.ok(width > NODE_W && height > NODE_H)
})

test('layoutDag: 链式 = 单列; 空/孤立节点不炸', () => {
  const { layers, nodes } = layoutDag(CHAIN)
  assert.deepEqual(layers, [['a'], ['b'], ['c']])
  assert.equal(new Set(nodes.map((n) => n.x)).size, 1, '链式全在一列')

  assert.deepEqual(layoutDag([]).nodes, [])
  assert.deepEqual(layoutDag([]).layers, [])
  // 刚从调色板加进来的孤立段: 无依赖 -> 落第 0 层, 与其它根并排
  const withLoose = layoutDag([...CHAIN, { id: 'x', depends_on: [] }])
  assert.deepEqual(withLoose.layers[0], ['a', 'x'])
})

test('ancestorSets: 传递闭包 (依赖是否已存在的判据)', () => {
  const anc = ancestorSets(PAR)
  assert.deepEqual([...anc.get('s5')].sort(), ['af0', 's1', 's2', 's3', 's4'])
  assert.ok(!anc.get('s2').has('s3'), 's2/s3 互不为祖先 = 可并行')
  assert.deepEqual([...anc.get('af0')], [])
})

test('hasCycle / wouldCycle: 拖线成环必须拦得住', () => {
  assert.equal(hasCycle(PAR), false)
  assert.equal(hasCycle(CHAIN), false)
  const cyc = CHAIN.map((f) => (f.id === 'a' ? { ...f, depends_on: ['c'] } : f))
  assert.equal(hasCycle(cyc), true)
  // 自环
  assert.equal(hasCycle([{ id: 'a', depends_on: ['a'] }]), true)

  // 加边 from -> to: from 是 to 的下游时成环
  assert.equal(wouldCycle(CHAIN, 'c', 'a'), true, 'c 依赖 a, 再让 a 依赖 c = 环')
  assert.equal(wouldCycle(CHAIN, 'a', 'a'), true, '自环')
  assert.equal(wouldCycle(CHAIN, 'a', 'c'), false, 'a->c 是已有的传递方向, 加直接边不成环')
  assert.equal(wouldCycle(PAR, 's2', 's3'), false, '并行两段之间加边合法 (变串行)')
  assert.equal(wouldCycle(PAR, 's9', 's5'), true)
})

test('nextSegId: 取最小空闲编号', () => {
  assert.equal(nextSegId(PAR), 's12')
  assert.equal(nextSegId(CHAIN), 's1')
  assert.equal(nextSegId([{ id: 's1' }, { id: 's3' }]), 's2', '中间有空洞就补空洞')
  assert.equal(nextSegId([], 'af'), 'af1')
})
