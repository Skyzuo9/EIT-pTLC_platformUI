/**
 * 功能: 物料实体 -> 三维工位归属的单元测试.
 *
 * 拿**真的** device-manifest 跑推导, 不用手搓夹具 —— 这条链的价值就在于"管线换了摆位
 * 它自己跟着走", 用假 manifest 测等于把这个价值测没了.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  DECLARED_STATION,
  deriveSeatStations,
  materialSectionsFor,
  presenceLabel,
  stationHasMaterial,
  stationOfEntity,
  stationOfLocation,
  stationOfNode,
} from '../../src/three-d/twin/materialStations.js'

const MANIFEST = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../../three_d/models/device-manifest.official-cr5.json', import.meta.url)),
  'utf8',
))

test('stationOfNode: 取最长前缀 —— ROBOT 挂在 ST_RAIL 之下, 短前缀不许抢', () => {
  const robotNode = 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT/SOMETHING'
  assert.equal(stationOfNode(MANIFEST, robotNode), 'ROBOT')
  assert.equal(stationOfNode(MANIFEST, 'ST_RAIL/OTHER'), 'RAIL')
})

test('stationOfNode: 前缀必须落在路径分段边界上', () => {
  // ST_RACKXYZ 不是 ST_RACK 的子节点
  assert.notEqual(stationOfNode(MANIFEST, 'ST_RACKXYZ/A'), 'RACK')
  assert.equal(stationOfNode(MANIFEST, 'ST_RACK'), 'RACK')
  assert.equal(stationOfNode(MANIFEST, ''), null)
})

test('deriveSeatStations: 真 manifest 推出货架/中转/板仓/液体/内容物的归属', () => {
  const derived = deriveSeatStations(MANIFEST)
  assert.equal(derived.rack, 'RACK')
  assert.equal(derived['staging-a'], 'STAGINGA')
  assert.equal(derived.feed, 'FEEDLIFT')
  assert.equal(derived.waste, 'FEEDLIFT')
  assert.equal(derived['collect-bottle'], 'COLLECT')
  assert.equal(derived['collect-holder'], 'COLLECT')
  assert.equal(derived['scrape-holder'], 'PHOTOSCRAPE')
})

test('stationOfEntity: 声明兜底覆盖没有几何的实体', () => {
  assert.equal(stationOfEntity(MANIFEST, 'solvent_1'), 'DEVELOP')
  assert.equal(stationOfEntity(MANIFEST, 'eluent'), 'COLLECT')
  assert.equal(stationOfEntity(MANIFEST, 'spot_seat'), 'SAMPLING')
  assert.equal(stationOfEntity(MANIFEST, 'scrape_table'), 'PHOTOSCRAPE')
  assert.equal(stationOfEntity(MANIFEST, 'feed-1'), 'RACK')
  assert.equal(stationOfEntity(MANIFEST, 'staging-b'), 'STAGINGA')
  assert.equal(stationOfEntity(MANIFEST, '不存在的'), null)
})

test('topology 里的每个实体都有归属 (漏一个就是某个工位物料页少一段)', () => {
  const ENTITIES = [
    'rack', 'staging-a', 'staging-b',
    'scrape-holder', 'collect-holder', 'collect-bottle',
    'feed-1', 'feed-2',
    'feed', 'waste',
    'solvent_1', 'solvent_2', 'solvent_3', 'solvent_4', 'eluent',
    'spot_seat', 'scrape_table',
  ]
  for (const id of ENTITIES) {
    assert.ok(stationOfEntity(MANIFEST, id), `${id} 没有工位归属`)
  }
})

test('归属的工位 id 必须真的存在于 manifest (防手误写错大小写)', () => {
  const known = new Set(MANIFEST.stations.map((s) => s.id))
  for (const [id, station] of Object.entries(DECLARED_STATION)) {
    assert.ok(known.has(station), `${id} 归到了不存在的工位 ${station}`)
  }
})

test('stationOfLocation: rack.<kind>.<plate> 归料架', () => {
  assert.equal(stationOfLocation(MANIFEST, 'rack.collector.3'), 'RACK')
  assert.equal(stationOfLocation(MANIFEST, 'staging-a'), 'STAGINGA')
  assert.equal(stationOfLocation(MANIFEST, 'collect-bottle'), 'COLLECT')
})

test('stationHasMaterial: 料架有(所以要出第 10 个工位标签), 机架没有', () => {
  assert.equal(stationHasMaterial(MANIFEST, 'RACK'), true)
  assert.equal(stationHasMaterial(MANIFEST, 'FEEDLIFT'), true)
  assert.equal(stationHasMaterial(MANIFEST, 'DEVELOP'), true)
  assert.equal(stationHasMaterial(MANIFEST, 'FRAME'), false)
  assert.equal(stationHasMaterial(MANIFEST, 'VISION'), false)
  assert.equal(stationHasMaterial(MANIFEST, 'TOOLING'), false)
})

test('stationHasMaterial: 后端没连(快照 null)时结论不变', () => {
  assert.equal(stationHasMaterial(MANIFEST, 'RACK'), true)
})

/** 造一份最小可用快照 */
function snapshot() {
  const cells = []
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 6; plate += 1) {
      for (let hole = 1; hole <= 6; hole += 1) {
        cells.push({ kind, plate, hole, state: 'FRESH', sample_id: '', powder_mm3: 0, liquid_ml: 0, eluted: false })
      }
    }
  }
  const rack = { collector: [], bottle: [] }
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 6; plate += 1) {
      rack[kind].push({ kind, plate, fresh: 6, used: 0, filled: 0, loaded: 0, present: true, expected: true, verified: false, ok: null })
    }
  }
  return {
    cells, rack,
    staging: { 'staging-a': { plate: 3, kind: 'collector' }, 'staging-b': { plate: null, kind: '' } },
    magazines: [{ magazine: 'feed', count: 12, capacity: 30 }, { magazine: 'waste', count: 4, capacity: 30 }],
    bottles: [
      { bottle: 'solvent_1', volume_ml: 800 }, { bottle: 'solvent_2', volume_ml: 750 },
      { bottle: 'solvent_3', volume_ml: 900 }, { bottle: 'solvent_4', volume_ml: 100 },
      { bottle: 'eluent', volume_ml: 500 },
    ],
    payloadSeats: [{ seat: 'collect-holder', kind: 'collector', plate: 2, hole: 4 }],
    seats: [{ seat: 'spot_seat', present: true }, { seat: 'scrape_table', present: false }],
    presence: [
      { location_id: 'rack.collector.1', present: true, expected: true, ok: null, verified: false },
      { location_id: 'staging-a', present: true, expected: true, ok: true, verified: true },
      { location_id: 'feed-1', present: true, expected: null, ok: null, verified: true },
    ],
  }
}

test('materialSectionsFor: 料架给出两类托盘库位 + 光电只读段', () => {
  const s = materialSectionsFor(MANIFEST, 'RACK', snapshot())
  const types = s.map((x) => x.key)
  assert.deepEqual(types, ['rack-collector', 'rack-bottle', 'feed-sensors'])
  assert.equal(s[0].plates.length, 6)
  assert.equal(s[0].plates[0].cells.length, 6, '每个库位应带 6 个孔')
  assert.equal(s[0].plates[0].cells[0].hole, 1, '孔位应按孔号升序')
})

test('materialSectionsFor: 各工位只拿到自己那几段', () => {
  const snap = snapshot()
  const keysOf = (id) => materialSectionsFor(MANIFEST, id, snap).map((x) => x.key)
  assert.deepEqual(keysOf('STAGINGA'), ['staging'])
  assert.deepEqual(keysOf('FEEDLIFT'), ['magazine'])
  assert.deepEqual(keysOf('DEVELOP'), ['bottle'])
  assert.deepEqual(keysOf('COLLECT'), ['bottle', 'payload-seat'])
  assert.deepEqual(keysOf('SAMPLING'), ['seat'])
  assert.deepEqual(keysOf('FRAME'), [])
  assert.deepEqual(keysOf(null), [])
})

test('materialSectionsFor: 中转两个区都归中转托盘位一栏', () => {
  const [staging] = materialSectionsFor(MANIFEST, 'STAGINGA', snapshot())
  assert.deepEqual(staging.rows.map((r) => r.area), ['staging-a', 'staging-b'])
})

test('materialSectionsFor: 快照为空时不炸, 返回空段', () => {
  assert.deepEqual(materialSectionsFor(MANIFEST, 'RACK', null), [])
})

test('presenceLabel: verified=false 的点只转述读数, 不下判定', () => {
  const row = { present: false, expected: true, ok: null, verified: false }
  const out = presenceLabel(row)
  assert.match(out.text, /极性未核实/)
  assert.equal(out.tone, 'muted', '未核实的点不许标红 —— 那 12 个货架位实测就没接上')
})

test('presenceLabel: 已核实且不符时标红', () => {
  const out = presenceLabel({ present: false, expected: true, ok: false, verified: true })
  assert.equal(out.tone, 'bad')
  assert.match(out.text, /与账本不符/)
})

test('presenceLabel: 已核实且相符时为 ok; 无行时为 muted', () => {
  assert.equal(presenceLabel({ present: true, ok: true, verified: true }).tone, 'ok')
  assert.equal(presenceLabel(null).tone, 'muted')
})
