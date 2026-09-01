// 物料右键菜单映射测试 (twin/materialMenu.js): 七类实体的菜单表 / danger 判级 /
// 在途只剩清在途 / 离线全禁用。菜单行是可序列化描述 (op 名 + 参数, 无闭包),
// 与 MaterialInteraction 的 OP_RUNNERS 键集对应。
import test from 'node:test'
import assert from 'node:assert/strict'
import { buildMaterialMenu, describeIdentity } from '../../src/three-d/twin/materialMenu.js'

/** 快速取非标题的可执行行 */
function ops(rows) {
  const flat = []
  for (const row of rows) {
    if (row.children?.length) flat.push(...row.children)
    else if (row.op) flat.push(row)
  }
  return flat
}

test('耗材件 (FRESH): 三态显式入口(隐藏当前态) + 编辑数量, 均非 danger', () => {
  const rows = buildMaterialMenu({
    type: 'item', loc: 'rack', kind: 'collector', plate: 3, hole: 5,
    cell: { state: 'FRESH' }, transitCarrier: null, seatedAt: null,
  })
  const byKey = Object.fromEntries(ops(rows).map((row) => [row.key, row]))
  assert.equal(byKey['mark-fresh'], undefined, '当前态不该出现在菜单里')
  assert.equal(byKey['mark-used'].args.state, 'USED')
  assert.equal(byKey['mark-used'].danger, undefined)
  assert.equal(byKey['mark-absent'].args.state, 'ABSENT')
  assert.equal(byKey.edit.op, 'edit')
})

test('空孔: 放入未用耗材 (mark FRESH)', () => {
  const rows = buildMaterialMenu({
    type: 'hole', loc: 'rack', kind: 'bottle', plate: 2, hole: 1,
    cell: { state: 'USED', sample_id: '' }, transitCarrier: null, seatedAt: null,
  })
  const mark = ops(rows).find((row) => row.op === 'mark')
  assert.equal(mark.args.state, 'FRESH')
  assert.equal(mark.label, '放入未用耗材')
})

test('成品孔: 取走语义 (标回未用)', () => {
  const rows = buildMaterialMenu({
    type: 'item', loc: 'rack', kind: 'bottle', plate: 2, hole: 1,
    cell: { state: 'USED', sample_id: 's7' }, transitCarrier: null, seatedAt: null,
  })
  const mark = ops(rows).find((row) => row.op === 'mark')
  assert.equal(mark.args.state, 'FRESH')
  assert.match(mark.label, /成品取走/)
})

test('在途件: 只剩清在途 (禁改格账), 三去向全 danger', () => {
  const rows = buildMaterialMenu({
    type: 'item', loc: 'rack', kind: 'collector', plate: 3, hole: 5,
    cell: { state: 'FRESH' }, transitCarrier: 'gripper_vial', transitStale: true,
    seatedAt: null,
  })
  const actions = ops(rows)
  assert.ok(actions.every((row) => row.op === 'transit'), '在途件不得出现 mark/edit')
  assert.deepEqual(actions.map((row) => row.args.landAt), ['rack', 'staging', ''])
  assert.ok(actions.every((row) => row.danger === true))
  assert.ok(rows.some((row) => row.key === 'stale'), '陈旧在途要有提示行')
})

test('座位件: 只剩清件位 (danger)', () => {
  const rows = buildMaterialMenu({
    type: 'item', loc: 'rack', kind: 'collector', plate: 2, hole: 6,
    cell: { state: 'USED', sample_id: '' }, transitCarrier: null,
    seatedAt: { seat: 'scrape-holder', label: '刮板夹具' },
  })
  const actions = ops(rows)
  assert.equal(actions.length, 1)
  assert.equal(actions[0].op, 'payloadSeat')
  assert.equal(actions[0].danger, true)
  assert.deepEqual(actions[0].args, { seat: 'scrape-holder' })
})

test('货架托盘: 在架双入口 + 整板三态 (已用/清空均 danger)', () => {
  const rows = buildMaterialMenu({
    type: 'tray', loc: 'rack', kind: 'collector', plate: 4,
    transitCarrier: null, seatedAt: null,
  })
  const byKey = Object.fromEntries(ops(rows).map((row) => [row.key, row]))
  assert.equal(byKey['rack-on'].args.present, true)
  assert.equal(byKey['rack-off'].args.present, false)
  assert.equal(byKey['plate-fresh'].danger, undefined)
  assert.equal(byKey['plate-used'].danger, true, '整板已用必须 danger (照二维页裁决)')
  assert.equal(byKey['plate-absent'].args.state, 'ABSENT')
  assert.equal(byKey['plate-absent'].danger, true, '整板清空(拿走)同样 danger')
})

test('中转托盘: 改板号子菜单 (当前板禁用) + 置空 danger', () => {
  const rows = buildMaterialMenu({
    type: 'tray', loc: 'staging', area: 'staging-a', kind: 'collector',
    plate: 3, stagingPlate: 3, transitCarrier: null, seatedAt: null,
  })
  const set = rows.find((row) => row.key === 'staging-set')
  assert.equal(set.children.length, 6)
  assert.equal(set.children[2].disabled, true, '现记 3 号板 -> 3 号项禁用')
  assert.equal(set.children[0].args.plate, 1)
  const clear = rows.find((row) => row.key === 'staging-clear')
  assert.equal(clear.danger, true)
  assert.equal(clear.args.plate, null)
})

test('板仓堆: ±1 按现账面算, 0 张时 −1 禁用', () => {
  const rows = buildMaterialMenu({ type: 'magazine', magazine: 'feed',
                                   magazineRow: { count: 0, capacity: 30 } })
  const byKey = Object.fromEntries(ops(rows).map((row) => [row.key, row]))
  assert.equal(byKey['mag-up'].args.count, 1)
  assert.equal(byKey['mag-down'].disabled, true)
})

test('账本离线: 全部写项禁用带提示', () => {
  const rows = buildMaterialMenu({
    type: 'item', loc: 'rack', kind: 'collector', plate: 3, hole: 5,
    cell: { state: 'FRESH' }, transitCarrier: null, seatedAt: null,
  }, { available: false })
  for (const row of ops(rows)) {
    assert.equal(row.disabled, true, `${row.key} 应禁用`)
  }
})

test('中转空位: 无孔账可改, 只给提示行', () => {
  const rows = buildMaterialMenu({
    type: 'hole', loc: 'staging', area: 'staging-a', kind: 'collector',
    plate: null, hole: 2, stagingPlate: null, cell: null,
    transitCarrier: null, seatedAt: null,
  })
  assert.equal(ops(rows).length, 0)
  assert.ok(rows.some((row) => row.key === 'no-plate'))
})

test('describeIdentity: 标题行覆盖在途/座位/成品三态', () => {
  assert.match(describeIdentity({
    type: 'item', loc: 'rack', kind: 'bottle', plate: 4, hole: 2,
    transitCarrier: 'gripper_vial',
  }), /在小夹爪上/)
  assert.match(describeIdentity({
    type: 'item', loc: 'rack', kind: 'collector', plate: 2, hole: 6,
    seatedAt: { seat: 'scrape-holder', label: '刮板夹具' },
  }), /在刮板夹具上/)
  assert.match(describeIdentity({
    type: 'item', loc: 'rack', kind: 'bottle', plate: 1, hole: 1,
    cell: { state: 'USED', sample_id: 's9' },
  }), /成品 s9/)
})
