/**
 * 功能: 现场事实面板的行构造与末端执行器行的测试(纯函数).
 *
 * 三条最要紧的:
 *   1. 末端执行器的行来自**后端能力面** robot.effectors, 不是前端按刀号复抄的映射 ——
 *      manifest 的 controllerTool 只声明了夹爪与吸盘, 翻转气缸没有, 照它出行会漏;
 *   2. 没被命令过的末端 on 必须是 null (未知), 绝不画成"关着" —— 那是把推定当确认;
 *   3. 残缺快照不抛 (会话未建时 material_state 就是空的)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  bottleRows, clampCount, magazineRows, payloadSeatRows, rackRows, seatRows,
  stagingRows, transitRows,
} from '../../src/three-d/sim/simFactRows.js'
import { buildEffectorPatch, effectorRows } from '../../src/three-d/sim/simStateRows.js'

const MANIFEST = {
  realtime: {
    mechanisms: [
      { id: 'rob_suction', label: '吸盘真空', station: 'robot' },
      { id: 'rob_flip_suction', label: '吸盘翻转', station: 'robot' },
      { id: 'col_press', label: '收集下压', station: 'collect' },
    ],
  },
}

/**
 * 一帧**推流**快照 (MaterialStateStore.normalizeSnapshot 的产物), 不是 REST
 * /api/materials 的 grid。两者形状不同, 而面板读的是前者:
 *   rack          {collector: [...], bottle: [...]} 按类分组, present 可为 null
 *   payloadSeats  驼峰 (后端字段是 payload_seats)
 * 2026-08-13 教训: 夹具照 REST 形状写 -> 单测全绿而页面当场
 * `.map is not a function` —— 与本轮那个 P0 (夹具替产品代码补了缺的一步) 同类。
 */
const GRID = {
  magazines: [
    { magazine: 'feed', label: '上料仓 (1Z)', count: 12, capacity: 30 },
    { magazine: 'waste', label: '下料仓 (2Z)', count: 3, capacity: 30 },
  ],
  seats: [
    { seat: 'spot_seat', label: '点样座', present: true },
    { seat: 'scrape_table', label: '刮板拍照台', present: false },
  ],
  staging: {
    'staging-b': { kind: 'bottle', plate: null },
    'staging-a': { kind: 'collector', plate: 4 },
  },
  rack: {
    collector: [{ kind: 'collector', plate: 1, present: true },
      { kind: 'collector', plate: 2, present: null }],
    bottle: [{ kind: 'bottle', plate: 1, present: false }],
  },
  bottles: [{ bottle: 'solvent_1', label: '溶剂1', volume_ml: 600, capacity_ml: 1000, percent: 60 }],
  payloadSeats: [{ seat: 'collect-bottle', label: '收集工位瓶位', kind: 'bottle', plate: 2, hole: 5 }],
  transit: { big: { label: '大爪', kind: 'collector', plate: 3, hole: null, stale: true } },
}

test('板仓行: 张数与容量都带出来', () => {
  const rows = magazineRows(GRID)
  assert.deepEqual(rows.map((r) => r.magazine), ['feed', 'waste'])
  assert.equal(rows[0].count, 12)
  assert.equal(rows[0].capacity, 30)
})

test('板位座行: present 折成布尔', () => {
  const rows = seatRows(GRID)
  assert.deepEqual(rows.map((r) => [r.seat, r.present]),
    [['spot_seat', true], ['scrape_table', false]])
})

test('中转行按区名排序, 空区 plate 保持 null(不折成 0)', () => {
  const rows = stagingRows(GRID)
  assert.deepEqual(rows.map((r) => r.area), ['staging-a', 'staging-b'])
  assert.equal(rows[0].plate, 4)
  assert.equal(rows[1].plate, null, '空区必须是 null —— 折成 0 会被读成 0 号盘')
})

test('货架行: 按类分组的对象要摊平, present=null 是"不知道"不是"没有"', () => {
  const rows = rackRows(GRID)
  assert.equal(rows.length, 3, 'collector 2 + bottle 1')
  assert.deepEqual(rows.map((r) => [r.kind, r.plate, r.present, r.unknown]), [
    ['collector', 1, true, false],
    ['collector', 2, false, true],
    ['bottle', 1, false, false],
  ])
})

test('瓶行 / 件位行 (驼峰 payloadSeats) / 在途行', () => {
  assert.equal(bottleRows(GRID)[0].volumeMl, 600)
  assert.equal(payloadSeatRows(GRID)[0].hole, 5, '件位读的是推流的驼峰键')
  const transit = transitRows(GRID)
  assert.equal(transit[0].carrier, 'big')
  assert.equal(transit[0].stale, true, '陈旧在途要标出来')
})

test('照 REST 形状喂进来也不许抛 (rack 是数组时视为无行)', () => {
  const restShaped = { rack: [{ kind: 'collector', plate: 1, present: 1 }], payload_seats: [{ seat: 'x' }] }
  assert.deepEqual(rackRows(restShaped), [], '数组形态不是推流形状, 不认但也不抛')
  assert.deepEqual(payloadSeatRows(restShaped), [])
})

test('残缺快照不抛(会话未建时 material_state 是空的)', () => {
  for (const fn of [magazineRows, seatRows, stagingRows, rackRows, bottleRows,
    payloadSeatRows, transitRows]) {
    assert.deepEqual(fn(null), [])
    assert.deepEqual(fn({}), [])
  }
})

test('clampCount: 负数归零, 超容量拉回上限, 非数字归零', () => {
  assert.equal(clampCount(-5, 30), 0)
  assert.equal(clampCount(40, 30), 30)
  assert.equal(clampCount('12', 30), 12)
  assert.equal(clampCount('abc', 30), 0)
  assert.equal(clampCount(12.6, 30), 13)
  assert.equal(clampCount(999, 0), 999, '容量为 0 表示不限, 不该拉回')
})

test('末端行来自后端能力面, 不按 manifest 的刀号复抄', () => {
  const robot = { tool: 1, effectors: ['rob_flip_suction', 'rob_suction'] }
  const rows = effectorRows(MANIFEST, robot, {
    rob_flip_suction: { commanded: false, confirmed: null },
  })
  assert.deepEqual(rows.map((r) => r.id), ['rob_flip_suction', 'rob_suction'])
  assert.equal(rows[0].label, '吸盘翻转')
  assert.equal(rows[0].on, false)
  assert.equal(rows[0].source, 'commanded')
})

test('没被命令过的末端 on = null(未知), 绝不画成关着', () => {
  const robot = { tool: 1, effectors: ['rob_suction'] }
  const rows = effectorRows(MANIFEST, robot, {})
  assert.equal(rows[0].on, null)
  assert.equal(rows[0].known, false)
  assert.equal(rows[0].source, '')
})

test('有反馈时 confirmed 优先于 commanded', () => {
  const robot = { tool: 2, effectors: ['rob_grip_plate96'] }
  const rows = effectorRows(MANIFEST, robot, {
    rob_grip_plate96: { commanded: true, confirmed: false },
  })
  assert.equal(rows[0].on, false)
  assert.equal(rows[0].source, 'feedback')
  assert.equal(rows[0].label, 'rob_grip_plate96', 'manifest 里没有就退回 id, 不编名字')
})

test('裸腕: 能力面为空 -> 一行都不出', () => {
  assert.deepEqual(effectorRows(MANIFEST, { tool: 0, effectors: [] }, {}), [])
  assert.deepEqual(effectorRows(MANIFEST, null, {}), [])
})

test('末端补丁走 robot.effectors, 与气缸的 mechanisms 分开', () => {
  assert.deepEqual(buildEffectorPatch('rob_suction', true),
    { robot: { effectors: { rob_suction: true } } })
})
