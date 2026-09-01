/**
 * 功能: 展缸盖开/关显示档的回归 —— 实时页那句"开启还是关闭"的判定口径.
 *
 * 这是最容易显示反的一环: PLC 的"动点到位"= effective=true = 盖压在缸口(关),
 * 直觉上却容易读成"动作了 = 开". 三维那侧同源(manifest linkage 的 outputRange 是
 * 反向 [行程, 0], 值 1 落在 GLB 建模态=关盖), 所以文字与几何必须同相 —— 本测试
 * 把这条对应关系钉死, 谁改反了都会红.
 *
 * 另两条: 反馈过期必须降级成"命令态"(加星), 不能让没到位的命令冒充实测;
 * 断流单独成档, 不能沿用末态假装还活着.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { lidStatusOf, lidSummary, tankLidRows } from '../../src/three-d/twin/lidStatus.js'

const FRESH = { stale: false, estimated: false }

test('动点到位(effective=true)= 盖关闭; 原点 = 开启', () => {
  assert.equal(lidStatusOf({ ...FRESH, effective: true }).key, 'closed')
  assert.equal(lidStatusOf({ ...FRESH, effective: true }).label, '关闭')
  assert.equal(lidStatusOf({ ...FRESH, effective: false }).key, 'open')
  assert.equal(lidStatusOf({ ...FRESH, effective: false }).label, '开启')
})

test('无到位反馈时降级为命令态(加星), 不冒充实测', () => {
  const commanded = lidStatusOf({ effective: false, stale: false, estimated: true })
  assert.equal(commanded.key, 'open', '命令态仍然报开/关, 只是标注来源')
  assert.equal(commanded.label, '开启*')
  assert.equal(commanded.estimated, true)
})

test('断流与无数据各自成档, 不沿用末态', () => {
  const stale = lidStatusOf({ effective: true, stale: true, estimated: false })
  assert.equal(stale.key, 'stale')
  assert.equal(stale.label, '断流')
  assert.equal(lidStatusOf(null).key, 'unknown')
  assert.equal(lidStatusOf({}).key, 'unknown', 'effective 缺失即无数据')
})

test('tankLidRows 按 lidMechanismId 关联缸与气缸; 未声明的缸 lid 为 null', () => {
  const tanks = [
    { id: 'tank1', label: '展缸 1', index: 0, lidMechanismId: 'dev_t1_cyl1' },
    { id: 'tank2', label: '展缸 2', index: 1, lidMechanismId: 'dev_t2_cyl1' },
    { id: 'tank3', label: '展缸 3', index: 2 },
  ]
  const mechanisms = [
    { id: 'dev_t1_cyl1', ...FRESH, effective: true },
    { id: 'dev_t2_cyl1', ...FRESH, effective: false },
    { id: 'ps_shade', ...FRESH, effective: true },
  ]
  const rows = tankLidRows(tanks, mechanisms)
  assert.equal(rows[0].lid.key, 'closed')
  assert.equal(rows[1].lid.key, 'open')
  assert.equal(rows[2].lid, null, '没声明盖气缸的缸不猜状态')
  assert.equal(rows[0].label, '展缸 1', '缸号不得被状态文字顶掉')
})

test('汇总只数确认档, 断流/未知不计入开或关', () => {
  const rows = tankLidRows(
    [
      { id: 'tank1', lidMechanismId: 'a' },
      { id: 'tank2', lidMechanismId: 'b' },
      { id: 'tank3', lidMechanismId: 'c' },
      { id: 'tank4', lidMechanismId: 'missing' },
    ],
    [
      { id: 'a', ...FRESH, effective: false },
      { id: 'b', ...FRESH, effective: true },
      { id: 'c', effective: true, stale: true },
    ],
  )
  const totals = lidSummary(rows)
  assert.deepEqual(
    { open: totals.open, closed: totals.closed, unknown: totals.unknown },
    { open: 1, closed: 1, unknown: 2 },
  )
  assert.equal(totals.text, '1 开 · 1 关 · 2 未知')
})
