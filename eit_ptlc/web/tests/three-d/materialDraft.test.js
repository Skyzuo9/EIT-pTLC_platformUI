/**
 * 功能: 物料改账草稿模型的单元测试 —— 逐动词叠加 / 幂等键覆盖 / 重放次序 / 身份保持.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  applyDraft,
  clearDraft,
  createDraft,
  describeEntry,
  draftKey,
  putEntry,
  removeEntry,
  replayOrder,
} from '../../src/three-d/twin/materialDraft.js'

/** 造一份最小的原始 material_state 事件 (snake_case, 与后端 grid() 同形) */
function rawEvent() {
  const cells = []
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 2; plate += 1) {
      for (let hole = 1; hole <= 6; hole += 1) {
        cells.push({
          kind, plate, hole, state: 'FRESH', sample_id: '', updated_at: 0, run_id: '',
          powder_mm3: 0, liquid_ml: 0, eluted: 0,
        })
      }
    }
  }
  return {
    type: 'material_state', ts: 1, seq: 1, cells,
    staging: { 'staging-a': { plate: null, kind: 'collector' }, 'staging-b': { plate: 2, kind: 'bottle' } },
    magazines: [{ magazine: 'feed', count: 10, capacity: 30 }, { magazine: 'waste', count: 3, capacity: 30 }],
    bottles: [{ bottle: 'solvent_1', volume_ml: 800, capacity_ml: 1000 }],
    seats: [{ seat: 'spot_seat', present: false }],
    presence: [
      { location_id: 'rack.collector.1', present: true, expected: true, ok: null, verified: false },
      { location_id: 'staging-a', present: false, expected: false, ok: true, verified: true },
    ],
    rack: [
      { kind: 'collector', plate: 1, present: 1, updated_at: 0, run_id: '' },
      { kind: 'collector', plate: 2, present: 1, updated_at: 0, run_id: '' },
      { kind: 'bottle', plate: 1, present: 1, updated_at: 0, run_id: '' },
    ],
    payload_seats: [], transit: {}, transit_stale: 0, summary: {}, presence_mismatches: 0,
  }
}

test('空草稿返回**同一个对象** (身份保持是逐帧性能的承重件)', () => {
  const event = rawEvent()
  assert.equal(applyDraft(event, createDraft()), event)
  assert.equal(applyDraft(null, createDraft()), null)
})

test('applyDraft 是纯函数: 入参一个字节都不动', () => {
  const event = rawEvent()
  const before = JSON.stringify(event)
  const draft = createDraft()
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, hole: 3, state: 'USED' })
  applyDraft(event, draft)
  assert.equal(JSON.stringify(event), before)
})

test('mark 单孔: 只改那一个孔', () => {
  const draft = createDraft()
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, hole: 3, state: 'USED' })
  const out = applyDraft(rawEvent(), draft)
  const hit = out.cells.find((c) => c.kind === 'collector' && c.plate === 1 && c.hole === 3)
  assert.equal(hit.state, 'USED')
  assert.equal(out.cells.filter((c) => c.state === 'USED').length, 1)
})

test('mark 整板: 6 个孔全刷, 且清 sample_id (与后端 mark_plate 一致)', () => {
  const draft = createDraft()
  putEntry(draft, 'mark', { kind: 'bottle', plate: 2, state: 'FRESH' })
  const out = applyDraft(rawEvent(), draft)
  const plate = out.cells.filter((c) => c.kind === 'bottle' && c.plate === 2)
  assert.equal(plate.length, 6)
  for (const cell of plate) {
    assert.equal(cell.state, 'FRESH')
    assert.equal(cell.sample_id, '')
  }
})

test('单孔改动压过同板的整板改动 (整板是底色, 单孔是覆盖)', () => {
  const draft = createDraft()
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, state: 'USED' })
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, hole: 2, state: 'FRESH' })
  const out = applyDraft(rawEvent(), draft)
  const plate = out.cells.filter((c) => c.kind === 'collector' && c.plate === 1)
  assert.equal(plate.find((c) => c.hole === 2).state, 'FRESH')
  assert.equal(plate.filter((c) => c.state === 'USED').length, 5)
})

test('setCellAmount: 粉/液/已淋洗三件套, 未给的字段不动', () => {
  const draft = createDraft()
  putEntry(draft, 'setCellAmount', { kind: 'collector', plate: 1, hole: 1, powder_mm3: 500, eluted: true })
  const out = applyDraft(rawEvent(), draft)
  const hit = out.cells.find((c) => c.kind === 'collector' && c.plate === 1 && c.hole === 1)
  assert.equal(hit.powder_mm3, 500)
  assert.equal(hit.eluted, 1, 'eluted 要归一成后端的 0/1 整数')
  assert.equal(hit.liquid_ml, 0, '没给的字段应保持原值')
  assert.equal(hit.state, 'FRESH', 'setCellAmount 不该动状态')
})

test('setStaging: 置板与置空; 并让该点位的对账结论作废', () => {
  const draft = createDraft()
  putEntry(draft, 'setStaging', { area: 'staging-a', plate: 3 })
  putEntry(draft, 'setStaging', { area: 'staging-b', plate: null })
  const out = applyDraft(rawEvent(), draft)
  assert.equal(out.staging['staging-a'].plate, 3)
  assert.equal(out.staging['staging-a'].kind, 'collector', '同区其余字段应保留')
  assert.equal(out.staging['staging-b'].plate, null)
  assert.equal(out.presence.find((r) => r.location_id === 'staging-a').ok, null,
    '被草稿碰过的点位不该显示过期的对账结论')
})

test('setRack 改的是账本一侧(expected + rack 行), 绝不动光电读数(present)', () => {
  const draft = createDraft()
  putEntry(draft, 'setRack', { kind: 'collector', plate: 1, present: false })
  const out = applyDraft(rawEvent(), draft)
  const row = out.presence.find((r) => r.location_id === 'rack.collector.1')
  assert.equal(row.expected, false, '账本期望应跟着改')
  assert.equal(row.present, true, '敲个数字不会让光电传感器动')
  assert.equal(row.ok, null)
  // 三维托盘显隐读的是 rack 行的投影(rackLedger), 草稿必须补丁到事件本体
  const ledger = out.rack.find((r) => r.kind === 'collector' && r.plate === 1)
  assert.equal(ledger.present, 0, 'rack 行要保持后端 0/1 整数形制')
  assert.equal(out.rack.find((r) => r.kind === 'collector' && r.plate === 2).present, 1,
    '别的库位不该被动')
})

test('setMagazine / setBottle / setSeat 各改各的表', () => {
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  putEntry(draft, 'setBottle', { bottle: 'solvent_1', volumeMl: 120 })
  putEntry(draft, 'setSeat', { seat: 'spot_seat', present: true })
  const out = applyDraft(rawEvent(), draft)
  assert.equal(out.magazines.find((m) => m.magazine === 'feed').count, 25)
  assert.equal(out.magazines.find((m) => m.magazine === 'waste').count, 3, '别的仓不该被动')
  assert.equal(out.bottles[0].volume_ml, 120)
  assert.equal(out.seats[0].present, true)
})

test('setMagazine 负数被夹到 0', () => {
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: -5 })
  assert.equal(applyDraft(rawEvent(), draft).magazines[0].count, 0)
})

test('幂等键: 同一目标后写覆盖先写, 条目数不涨', () => {
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 5 })
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 9 })
  assert.equal(draft.entries.size, 1)
  assert.equal(applyDraft(rawEvent(), draft).magazines[0].count, 9)
})

test('幂等键: 整板与单孔是两个不同的键', () => {
  assert.notEqual(
    draftKey('mark', { kind: 'collector', plate: 1 }),
    draftKey('mark', { kind: 'collector', plate: 1, hole: 1 }),
  )
})

test('revision: 每次增删改都递增 (记忆化靠它判失效)', () => {
  const draft = createDraft()
  assert.equal(draft.revision, 0)
  const key = putEntry(draft, 'setMagazine', { magazine: 'feed', count: 5 })
  assert.equal(draft.revision, 1)
  removeEntry(draft, key)
  assert.equal(draft.revision, 2)
  removeEntry(draft, key)
  assert.equal(draft.revision, 2, '删不存在的不该递增')
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 5 })
  clearDraft(draft)
  assert.equal(draft.revision, 4)
  clearDraft(draft)
  assert.equal(draft.revision, 4, '清空的空草稿不该递增')
})

test('replayOrder: 整板 mark 必须排在单孔 mark 之前 (否则整板会抹掉单孔编辑)', () => {
  const draft = createDraft()
  putEntry(draft, 'setCellAmount', { kind: 'collector', plate: 1, hole: 1, powder_mm3: 5 })
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, hole: 1, state: 'USED' })
  putEntry(draft, 'mark', { kind: 'collector', plate: 1, state: 'FRESH' })
  putEntry(draft, 'setStaging', { area: 'staging-a', plate: null })
  putEntry(draft, 'setRack', { kind: 'collector', plate: 1, present: true })
  const order = replayOrder(draft).map((e) => (
    e.verb === 'mark' ? (e.args.hole === undefined ? 'markPlate' : 'markHole') : e.verb))
  assert.deepEqual(order, ['setStaging', 'setRack', 'markPlate', 'markHole', 'setCellAmount'])
})

test('putEntry 拒绝不支持的动词 (在途/件位不是可预览的账面编辑)', () => {
  const draft = createDraft()
  assert.throws(() => putEntry(draft, 'clearTransit', { carrier: 'gripper_plate96' }), /不支持/)
  assert.throws(() => putEntry(draft, 'clearPayloadSeat', { seat: 'collect-holder' }), /不支持/)
})

test('describeEntry: 每条都有中文, 并标明改完三维看不看得见', () => {
  const cases = [
    ['mark', { kind: 'collector', plate: 1, hole: 3, state: 'USED' }, true],
    ['setCellAmount', { kind: 'collector', plate: 1, hole: 3, powder_mm3: 500 }, true],
    ['setStaging', { area: 'staging-a', plate: 3 }, true],
    ['setMagazine', { magazine: 'feed', count: 12 }, true],
    ['setRack', { kind: 'bottle', plate: 2, present: false }, true],
    ['setBottle', { bottle: 'solvent_1', volumeMl: 120 }, false],
    ['setSeat', { seat: 'spot_seat', present: true }, false],
  ]
  for (const [verb, args, visible] of cases) {
    const out = describeEntry({ verb, args })
    assert.ok(out.text && out.text.length > 3, `${verb} 的描述太短`)
    assert.ok(!/undefined|NaN|\[object/.test(out.text), `${verb} 的描述里漏了值: ${out.text}`)
    assert.equal(out.visible3d, visible, `${verb} 的三维可见性标注不对`)
  }
})
