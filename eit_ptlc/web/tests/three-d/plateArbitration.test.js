/**
 * 功能: L1/L2 仲裁 reducer 的测试.
 *
 * 全篇最重要的两条(写反了都会让画面"看起来正常"但语义是错的):
 *   1. **L1 落后不改画面** —— 账本报出板刚离开的位置是常态, 不是冲突, 更不该把板拽回去;
 *   2. **真冲突以 L1 为准并清轨迹** —— 三维不许拿自己的推断压过后端账本。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PLATE_SLOT } from '../../src/three-d/twin/bindings/PlateSlots.js'
import {
  AUTHORITY,
  applyLedger,
  applyTransfer,
  createPlate,
  recoverToSuction,
  resyncToLedger,
} from '../../src/three-d/twin/bindings/plateArbitration.js'

const plateAt = (slot, extra = {}) => ({
  ...createPlate({ plateId: 'sample:S-01', sampleId: 'S-01', slot }),
  ...extra,
})

test('取板: 板确实在那儿才迁到 carried, 并把来源压进轨迹', () => {
  const { plate, accepted } = applyTransfer(plateAt('spot_seat'), { kind: 'pick', slot: 'spot_seat' })
  assert.equal(accepted, true)
  assert.equal(plate.slot, PLATE_SLOT.CARRIED)
  assert.equal(plate.authority, AUTHORITY.L2)
  assert.deepEqual(plate.l2Trail, ['spot_seat'])
})

test('取板: 末点说的位置与板账上位置不符 → 不迁移', () => {
  const before = plateAt('tank:3')
  const { plate, accepted, reason } = applyTransfer(before, { kind: 'pick', slot: 'scrape_table' })
  assert.equal(accepted, false)
  assert.equal(reason, 'slot_mismatch')
  assert.equal(plate, before, '拒绝时应原样返回, 不产生新对象')
})

test('取板: 已经在手上的板不能再被取一次', () => {
  const carried = plateAt(PLATE_SLOT.CARRIED, { l2Trail: ['spot_seat'] })
  assert.equal(applyTransfer(carried, { kind: 'pick', slot: 'spot_seat' }).accepted, false)
})

test('放板: 相邻落点正常落地', () => {
  const carried = plateAt(PLATE_SLOT.CARRIED, { l2Trail: ['scrape_table'] })
  const { plate, accepted } = applyTransfer(carried, { kind: 'put', slot: 'tank:5' })
  assert.equal(accepted, true)
  assert.equal(plate.slot, 'tank:5')
  assert.equal(plate.suspect, false)
  assert.deepEqual(plate.l2Trail, ['scrape_table', 'tank:5'])
})

test('放板: 越级落点仍然照放, 但标 suspect(板物理上确实被放下了)', () => {
  const carried = plateAt(PLATE_SLOT.CARRIED, { l2Trail: ['feedlift'] })
  const { plate, accepted, reason } = applyTransfer(carried, { kind: 'put', slot: 'waste' })
  assert.equal(accepted, true, '不能因为不相邻就假装板还在手上')
  assert.equal(reason, 'not_adjacent')
  assert.equal(plate.suspect, true)
  assert.equal(plate.slot, 'waste')
})

test('放板: 手上没板时不接受', () => {
  assert.equal(applyTransfer(plateAt('spot_seat'), { kind: 'put', slot: 'scrape_table' }).accepted, false)
})

test('L1 与当前一致 → 升为 L1 并清轨迹', () => {
  const plate = plateAt('tank:2', { authority: AUTHORITY.L2, l2Trail: ['scrape_table', 'tank:2'] })
  const { plate: next, outcome } = applyLedger(plate, 'tank:2')
  assert.equal(outcome, 'agree')
  assert.equal(next.authority, AUTHORITY.L1)
  assert.deepEqual(next.l2Trail, [])
})

test('L1 落后(报的是轨迹里的历史位置)→ 画面不动, 也不算冲突', () => {
  const plate = plateAt('tank:2', { authority: AUTHORITY.L2, l2Trail: ['scrape_table', 'tank:2'] })
  const { plate: next, outcome } = applyLedger(plate, 'scrape_table')
  assert.equal(outcome, 'lagging')
  assert.equal(next, plate, '必须原样返回, 不得把板拽回历史位置')
})

test('真冲突(既非当前也不在轨迹里)→ 以 L1 为准并清轨迹', () => {
  const plate = plateAt('tank:2', { authority: AUTHORITY.L2, l2Trail: ['scrape_table', 'tank:2'] })
  const { plate: next, outcome } = applyLedger(plate, 'spot_seat')
  assert.equal(outcome, 'corrected')
  assert.equal(next.slot, 'spot_seat')
  assert.equal(next.authority, AUTHORITY.L1)
  assert.deepEqual(next.l2Trail, [])
  assert.equal(next.suspect, false, '按账本纠正后疑点应清除')
})

test('L3(手动直跑)的板永不被 L1 接管, 也永不升级权威', () => {
  const inferred = { ...createPlate({ plateId: 'inferred:1', slot: 'spot_seat', authority: AUTHORITY.L3 }) }
  assert.equal(applyLedger(inferred, 'tank:1').outcome, 'ignored')
  assert.equal(resyncToLedger(inferred, 'tank:1'), inferred)

  const { plate } = applyTransfer(inferred, { kind: 'pick', slot: 'spot_seat' })
  assert.equal(plate.authority, AUTHORITY.L3, '搬运不得把推断态伪装成有账本背书')
})

test('重同步: 刷新/重连后只信 L1, 持板中的板落回上一个停放位', () => {
  const carried = plateAt(PLATE_SLOT.CARRIED, { authority: AUTHORITY.L2, l2Trail: ['scrape_table'], suspect: true })
  const next = resyncToLedger(carried, 'scrape_table')
  assert.equal(next.slot, 'scrape_table', '不画在手上 —— 账本说它在刮板台, 那是唯一有依据的说法')
  assert.equal(next.authority, AUTHORITY.L1)
  assert.deepEqual(next.l2Trail, [])
  assert.equal(next.suspect, false)
})

test('一整轮真实搬运: 点样座 → 刮板台, L1 沿途落后不打断画面', () => {
  let plate = plateAt('spot_seat')
  ;({ plate } = applyTransfer(plate, { kind: 'pick', slot: 'spot_seat' }))
  assert.equal(plate.slot, PLATE_SLOT.CARRIED)

  // 段还没 DONE, 账本仍报 spot_seat
  let outcome
  ;({ plate, outcome } = applyLedger(plate, 'spot_seat'))
  assert.equal(outcome, 'lagging')
  assert.equal(plate.slot, PLATE_SLOT.CARRIED, '板应继续跟着手走')

  ;({ plate } = applyTransfer(plate, { kind: 'put', slot: 'scrape_table' }))
  assert.equal(plate.slot, 'scrape_table')

  // 段 DONE, 账本追上
  ;({ plate, outcome } = applyLedger(plate, 'scrape_table'))
  assert.equal(outcome, 'agree')
  assert.equal(plate.authority, AUTHORITY.L1)
  assert.deepEqual(plate.l2Trail, [])
})

test('真空位恢复: 迁到 carried 并标 recovered', () => {
  const plate = recoverToSuction(plateAt(PLATE_SLOT.FEEDLIFT), PLATE_SLOT.FEEDLIFT)
  assert.equal(plate.slot, PLATE_SLOT.CARRIED)
  assert.equal(plate.recovered, true)
  assert.equal(plate.authority, AUTHORITY.L2, '位置已不是账本说的那个, 权威降到 L2')
})

test('★ 真空位恢复必须把来处压进轨迹 —— 否则账本每 3s 把板从手上拽回去', () => {
  const plate = recoverToSuction(plateAt(PLATE_SLOT.FEEDLIFT), PLATE_SLOT.FEEDLIFT)
  assert.deepEqual(plate.l2Trail, [PLATE_SLOT.FEEDLIFT])

  // 段还没 DONE, 账本仍报 feedlift: 这是落后, 不是冲突
  const { plate: next, outcome } = applyLedger(plate, PLATE_SLOT.FEEDLIFT)
  assert.equal(outcome, 'lagging')
  assert.equal(next.slot, PLATE_SLOT.CARRIED)

  // 没有轨迹的话同一帧会被判成真冲突并把板拽回去 —— 这就是要防的那个 bug
  const naive = { ...plate, l2Trail: [] }
  assert.equal(applyLedger(naive, PLATE_SLOT.FEEDLIFT).outcome, 'corrected')
})

test('真空位恢复: L3 的板恢复后仍是 L3, 权威永不升级', () => {
  const l3 = { ...plateAt(''), authority: AUTHORITY.L3 }
  assert.equal(recoverToSuction(l3, '').authority, AUTHORITY.L3)
})

test('真空位恢复: 已经在手上就原样返回(每帧调用必须幂等)', () => {
  const carried = plateAt(PLATE_SLOT.CARRIED)
  assert.equal(recoverToSuction(carried, PLATE_SLOT.SPOT_SEAT), carried)
})

test('板与账本对齐后 recovered 即清零', () => {
  const recovered = recoverToSuction(plateAt(PLATE_SLOT.SPOT_SEAT), PLATE_SLOT.SPOT_SEAT)
  assert.equal(resyncToLedger(recovered, PLATE_SLOT.SPOT_SEAT).recovered, false)
  // 走 L2 正常放板同理: 落地了就不再是"恢复出来的"
  const put = applyTransfer(recovered, { kind: 'put', slot: PLATE_SLOT.SCRAPE_TABLE })
  assert.equal(put.accepted, true)
  assert.equal(put.plate.recovered, false)
})

test('残缺输入不抛', () => {
  assert.equal(applyTransfer(null, { kind: 'pick', slot: 'x' }).accepted, false)
  assert.equal(applyTransfer(plateAt('x'), {}).accepted, false)
  assert.equal(applyLedger(null, 'x').outcome, 'ignored')
  assert.equal(applyLedger(plateAt('x'), '').outcome, 'ignored')
  assert.equal(resyncToLedger(null, 'x'), null)
  assert.equal(recoverToSuction(null), null)
})
