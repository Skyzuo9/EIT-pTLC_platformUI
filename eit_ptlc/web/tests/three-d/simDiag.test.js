/**
 * 功能: 诊断面板行构造的测试(纯函数).
 *
 * 最要紧的一条: **三态**。未知(读不到)与不满足必须画成两种记号 —— 把"读不到"
 * 画成"不满足", 就是真机上那段标定话术害人的同一种方式。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  feedliftRows, gateMark, gateRows, pumpLedgerBlock, sensorGroups, stationRows,
  syntheticBlock, tankRows,
} from '../../src/three-d/sim/simDiagRows.js'

const REPORT = {
  stations: [
    {
      station: 'FeedLift',
      l2: { State: 40, ActiveCode: 11, Step: 14, ErrorCode: 301 },
      action_name: 'A11_feed_raise',
      step_text: '14 · fail',
      error_text: '前置门 10 秒未满足; 该动作要求: ...',
      gate: [
        { key: 'homed', spec: '玻璃上料轴1ZDATE.bHomed', value: true, because: '板堆模型 homed.feed = True' },
        { key: 'proximity', spec: '玻璃升降接近开关1 (仓底有板)', value: false, because: '板堆模型 counts.feed = 0 张 (仓是空的)' },
        { key: 'alarm', spec: 'NOT Alarm.0', value: null, because: '沙盒不合成该量' },
      ],
    },
    { station: 'Rail', l2: { State: 0, ActiveCode: 0, Step: 0, ErrorCode: 0 }, gate: [] },
    { station: 'Pump', l2: { error: '读不到' } },
  ],
  sensors: {
    bytes: { IX8: { value: 8, bits: '00001000' }, IX11: { value: 0, bits: '00000000' } },
    bits: [
      { name: 'feed_photo', label: '玻璃升降光电开关1', byte: 'IX8', bit: 3, on: true, source: '板堆模型' },
      { name: 'feed_proximity', label: '玻璃升降接近开关1 (仓底有板)', byte: 'IX8', bit: 5, on: false, source: '板堆模型 counts' },
    ],
    constant_zero: [{ range: 'IX11.0-7', reason: '真机未供电' }],
  },
  feedlift: {
    feed: { count: 0, capacity: 30, homed: true, z_mm: 0, z_trigger_mm: 512.127, proximity: false },
    waste: { count: 9, capacity: 30, homed: true, z_mm: 488, z_trigger_mm: 486.5, proximity: true },
  },
}

test('gateMark 是三态: 未知不能画成不满足', () => {
  assert.equal(gateMark(true), '✓')
  assert.equal(gateMark(false), '✗')
  assert.equal(gateMark(null), '?')
  assert.equal(gateMark(undefined), '?')
})

test('工位行: 出错的标 attention, IDLE 的不标', () => {
  const rows = stationRows(REPORT)
  const feed = rows.find((r) => r.station === 'FeedLift')
  assert.equal(feed.stateText, 'ERROR')
  assert.equal(feed.attention, true)
  assert.equal(feed.errorCode, 301)
  assert.equal(feed.stepText, '14 · fail')

  const rail = rows.find((r) => r.station === 'Rail')
  assert.equal(rail.stateText, 'IDLE')
  assert.equal(rail.attention, false)
})

test('读不到的工位如实带出 error, 不伪装成 IDLE', () => {
  const pump = stationRows(REPORT).find((r) => r.station === 'Pump')
  assert.equal(pump.error, '读不到')
})

test('门行: 未知项带 unknown 标记, 且真因原样带出', () => {
  const rows = gateRows(REPORT, 'FeedLift')
  const prox = rows.find((r) => r.key === 'proximity')
  assert.equal(prox.mark, '✗')
  assert.equal(prox.unknown, false)
  assert.match(prox.because, /counts\.feed = 0 张/)

  const alarm = rows.find((r) => r.key === 'alarm')
  assert.equal(alarm.mark, '?')
  assert.equal(alarm.unknown, true, '读不到必须与不满足分开')
})

test('传感器组: 语义在前、裸位在后, 地址写出来供现场对屏', () => {
  const groups = sensorGroups(REPORT)
  const ix8 = groups.find((g) => g.byte === 'IX8')
  assert.equal(ix8.bits, '00001000')
  const prox = ix8.rows.find((r) => r.name === 'feed_proximity')
  assert.equal(prox.address, 'IX8.5')
  assert.equal(prox.on, false)
  assert.ok(prox.source, '每一位都要说清由什么推导')

  const ix11 = groups.find((g) => g.byte === 'IX11')
  assert.deepEqual(ix11.rows, [], '无具名位的字节留空组, 由界面说明恒 0 的依据')
})

test('板堆行按仓名排序并带出全部诊断量', () => {
  const rows = feedliftRows(REPORT)
  assert.deepEqual(rows.map((r) => r.magazine), ['feed', 'waste'])
  assert.equal(rows[0].count, 0)
  assert.equal(rows[0].z_trigger_mm, 512.127)
})

test('残缺报告不抛(诊断端点未就绪或会话未建)', () => {
  for (const fn of [stationRows, sensorGroups, feedliftRows]) {
    assert.deepEqual(fn(null), [])
    assert.deepEqual(fn({}), [])
  }
  assert.deepEqual(gateRows(null, 'FeedLift'), [])
  assert.deepEqual(gateRows(REPORT, '不存在的工位'), [])
  assert.deepEqual(syntheticBlock(null), { total: 0, items: [] })
  assert.deepEqual(syntheticBlock({}), { total: 0, items: [] })
})

test('合成值台账: 有几处答案是沙盒编的, 界面上必须数得出来', () => {
  const block = syntheticBlock({
    synthetic: {
      total: 5,
      items: [
        { host: 'develop.wait_level', reason: '沙盒无液位相机', count: 2, last_ts: 1 },
        { host: 'vision.capture_plate_offset', reason: '沙盒无对位相机', count: 3, last_ts: 2 },
      ],
    },
  })
  assert.equal(block.total, 5)
  // 后端按次数降序给, 前端不重排 —— 最常被编的那一处排在最前
  assert.deepEqual(block.items.map((i) => i.host),
    ['develop.wait_level', 'vision.capture_plate_offset'])
  assert.equal(block.items[0].count, 2)
  // 理由必须逐字带过来: 只报次数不报为什么, 等于让人拿着一个数字去猜
  assert.equal(block.items[1].reason, '沙盒无对位相机')
})

test('泵积分 vs 账本扣减: 两个数并排, diverged 是单向判据', () => {
  const block = pumpLedgerBlock({
    pumps: {
      aspirated_total_ml: 12.5, dispensed_total_ml: 11.0, ledger_drawn_ml: 12.0,
      diverged: false, note: '账本按动作参数扣',
      items: [
        { id: 'COL', plunger_ml: 1.5, aspirated_ml: 12.5, dispensed_ml: 11.0, busy: true },
      ],
    },
  })
  assert.equal(block.aspiratedMl, 12.5)
  assert.equal(block.ledgerMl, 12.0)
  assert.equal(block.diverged, false, '泵吸得比账本多是正常的(清洗润洗不记账)')
  assert.equal(block.items[0].busy, true)
  assert.ok(block.note.length > 0, '口径说明要带过来, 只给两个数会让人以为是 bug')

  // diverged 由后端判定, 前端不重算 —— 判据只该有一处
  const bad = pumpLedgerBlock({ pumps: { diverged: true } })
  assert.equal(bad.diverged, true)
  assert.deepEqual(pumpLedgerBlock(null),
    { aspiratedMl: 0, dispensedMl: 0, ledgerMl: 0, diverged: false, note: '', items: [] })
})

test('展缸液量行: 只列有液或泡过的缸, 空缸不占版面', () => {
  const rows = tankRows({
    tanks: {
      volumes: {
        1: { volume_ml: 0, level: 0, soak_s: 0 },
        3: { volume_ml: 41.2, level: 0.402, soak_s: 120.5 },
        8: { volume_ml: 0, level: 0, soak_s: 8 },
      },
    },
  })
  assert.deepEqual(rows.map((r) => r.tank), [3, 8], '1 号缸既没液也没泡过, 不列')
  assert.equal(rows[0].volumeMl, 41.2)
  assert.equal(rows[0].soakS, 120.5)
  assert.deepEqual(tankRows(null), [])
})
