/**
 * 功能: 板停放位词表、相邻性与 CAD 锚点解析的测试.
 *
 * 这里钉死的最重要一条: **缸锚点按 parent 名反查, 不按实例序号推**。
 * CAD 实测的 玻璃-1.00x → TANK_n 对应关系是乱的, 且 .007 压根不是缸板而是废板仓。
 * 推错了画面依然"看起来很真", 只是每块板都躺错缸 —— 没有任何自动指标会报警,
 * 只能靠这条测试挡。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  MAGAZINE_ANCHOR_NAMES,
  PLATE_SLOT,
  TANK_COUNT,
  isAdjacent,
  isKnownSlot,
  isMagazineSlot,
  isSilicaUp,
  resolveAnchors,
  tankOf,
} from '../../src/three-d/twin/bindings/PlateSlots.js'

/** 与 three_d/work/structure.json 实测一致的 13 个锚点(顺序刻意打乱)。 */
const REAL_NODES = [
  { name: '玻璃-1.005', parentName: 'TANK_5', path: 'ST_DEVELOP/展缸架总装-1/TANK_5/玻璃-1.005' },
  { name: '玻璃-1.004', parentName: 'TANK_6', path: 'ST_DEVELOP/展缸架总装-1/TANK_6/玻璃-1.004' },
  { name: '玻璃-1.003', parentName: 'TANK_7', path: 'ST_DEVELOP/展缸架总装-1/TANK_7/玻璃-1.003' },
  { name: '玻璃-1.006', parentName: 'TANK_8', path: 'ST_DEVELOP/展缸架总装-1/TANK_8/玻璃-1.006' },
  { name: '玻璃-1.010', parentName: 'TANK_1', path: 'ST_DEVELOP/展缸架总装-2/TANK_1/玻璃-1.010' },
  { name: '玻璃-1.009', parentName: 'TANK_2', path: 'ST_DEVELOP/展缸架总装-2/TANK_2/玻璃-1.009' },
  { name: '玻璃-1.008', parentName: 'TANK_3', path: 'ST_DEVELOP/展缸架总装-2/TANK_3/玻璃-1.008' },
  { name: '玻璃-1.011', parentName: 'TANK_4', path: 'ST_DEVELOP/展缸架总装-2/TANK_4/玻璃-1.011' },
  { name: '玻璃-1', parentName: '抽液机构总装-1', path: 'ST_SAMPLING/抽液机构总装-1/玻璃-1' },
  { name: '玻璃-1.002', parentName: '刮板机构总装-1', path: 'ST_PHOTOSCRAPE/刮板机构总装-1/玻璃-1.002' },
  { name: '玻璃-2', parentName: '玻璃上料抽拉机构-1', path: 'ST_FEEDLIFT/玻璃上料抽拉机构-1/玻璃-2' },
  { name: 'INV_MAGAZINE_FEED_TEMPLATE', parentName: '玻璃上料机构-1', path: 'ST_FEEDLIFT/玻璃上料机构-1/INV_MAGAZINE_FEED_TEMPLATE' },
  { name: 'INV_MAGAZINE_WASTE_TEMPLATE', parentName: '玻璃下料机构-1', path: 'ST_FEEDLIFT/玻璃下料机构-1/INV_MAGAZINE_WASTE_TEMPLATE' },
]

test('tankOf: 解析 tank:N, 未分缸的 tank:? 与越界一律 null', () => {
  assert.equal(tankOf('tank:3'), 3)
  assert.equal(tankOf('tank:8'), 8)
  assert.equal(tankOf('tank:?'), null, '调度器未分缸时的占位不得当成缸号')
  assert.equal(tankOf('tank:0'), null)
  assert.equal(tankOf('tank:9'), null)
  assert.equal(tankOf('spot_seat'), null)
  assert.equal(tankOf(''), null)
  assert.equal(tankOf(undefined), null)
})

test('仓态判定: 只有 feedlift / waste 是仓', () => {
  assert.equal(isMagazineSlot(PLATE_SLOT.FEEDLIFT), true)
  assert.equal(isMagazineSlot(PLATE_SLOT.WASTE), true)
  assert.equal(isMagazineSlot(PLATE_SLOT.SPOT_SEAT), false)
  assert.equal(isMagazineSlot('tank:1'), false)
})

test('未知位置词一律不认(防调度器改词表后前端静默画错)', () => {
  assert.equal(isKnownSlot('spot_seat'), true)
  assert.equal(isKnownSlot('tank:8'), true)
  assert.equal(isKnownSlot('carried'), true)
  assert.equal(isKnownSlot('tank:?'), false)
  assert.equal(isKnownSlot('some_new_slot'), false)
  assert.equal(isKnownSlot(''), false)
})

test('相邻性: 就是配方里那条被静态校验保住的位置轨迹', () => {
  // feedlift → spot_seat → scrape_table → tank:N → scrape_table → waste
  assert.equal(isAdjacent('feedlift', 'spot_seat'), true)
  assert.equal(isAdjacent('spot_seat', 'scrape_table'), true)
  assert.equal(isAdjacent('scrape_table', 'tank:3'), true)
  assert.equal(isAdjacent('tank:3', 'scrape_table'), true)
  assert.equal(isAdjacent('scrape_table', 'waste'), true)
})

test('相邻性: 三对明确不相邻的组合必须挡住', () => {
  assert.equal(isAdjacent('feedlift', 'waste'), false, '板不可能从上料仓直接进废板仓')
  assert.equal(isAdjacent('spot_seat', 'tank:1'), false, '进缸前必须先过刮板台拍 before')
  assert.equal(isAdjacent('tank:1', 'tank:2'), false, '缸之间不能直接倒板')
})

test('相邻性: 未知词参与时一律 false, 不放行', () => {
  assert.equal(isAdjacent('tank:?', 'scrape_table'), false)
  assert.equal(isAdjacent('scrape_table', '乱写'), false)
  assert.equal(isAdjacent('', 'spot_seat'), false)
})

test('锚点解析: 缸号按 parent 名反查, 与乱序的实例编号无关', () => {
  const { anchors, missing } = resolveAnchors(REAL_NODES)
  assert.deepEqual(missing, [], '13 个落点应全部解析到')

  // 逐个对照 blender_inspect 实测的乱序映射
  assert.match(anchors.get('tank:1'), /玻璃-1\.010$/)
  assert.match(anchors.get('tank:2'), /玻璃-1\.009$/)
  assert.match(anchors.get('tank:3'), /玻璃-1\.008$/)
  assert.match(anchors.get('tank:4'), /玻璃-1\.011$/)
  assert.match(anchors.get('tank:5'), /玻璃-1\.005$/)
  assert.match(anchors.get('tank:6'), /玻璃-1\.004$/)
  assert.match(anchors.get('tank:7'), /玻璃-1\.003$/)
  assert.match(anchors.get('tank:8'), /玻璃-1\.006$/)
})

test('锚点解析: 玻璃-1.007 是废板仓而不是缸板(按序号推必踩的坑)', () => {
  const { anchors } = resolveAnchors(REAL_NODES)
  const tankPaths = Array.from({ length: 8 }, (_, i) => anchors.get(`tank:${i + 1}`))
  assert.ok(
    tankPaths.every((path) => !/玻璃-1\.007/.test(path || '')),
    '.007 绝不能被认成缸板',
  )
  assert.equal(anchors.get(PLATE_SLOT.WASTE), MAGAZINE_ANCHOR_NAMES[PLATE_SLOT.WASTE]
    ? 'ST_FEEDLIFT/玻璃下料机构-1/INV_MAGAZINE_WASTE_TEMPLATE'
    : undefined)
})

test('锚点解析: 点样座/刮板台/两个料仓各就各位', () => {
  const { anchors } = resolveAnchors(REAL_NODES)
  assert.equal(anchors.get(PLATE_SLOT.SPOT_SEAT), 'ST_SAMPLING/抽液机构总装-1/玻璃-1')
  assert.equal(anchors.get(PLATE_SLOT.SCRAPE_TABLE), 'ST_PHOTOSCRAPE/刮板机构总装-1/玻璃-1.002')
  assert.equal(anchors.get(PLATE_SLOT.FEEDLIFT), 'ST_FEEDLIFT/玻璃上料机构-1/INV_MAGAZINE_FEED_TEMPLATE')
  assert.equal(anchors.get(PLATE_SLOT.WASTE), 'ST_FEEDLIFT/玻璃下料机构-1/INV_MAGAZINE_WASTE_TEMPLATE')
})

test('锚点解析: 抽拉屉不进任何停放位(它不参与流程)', () => {
  const { anchors } = resolveAnchors(REAL_NODES)
  const paths = [...anchors.values()]
  assert.ok(paths.every((path) => !/玻璃-2$/.test(path)), '玻璃-2 是人工上料的抽屉, 不是停放位')
})

test('锚点解析: 缺件时如实报 missing, 不静默补一个近似锚点', () => {
  const partial = REAL_NODES.filter((node) => node.parentName !== 'TANK_4')
  const { anchors, missing } = resolveAnchors(partial)
  assert.deepEqual(missing, ['tank:4'])
  assert.equal(anchors.has('tank:4'), false)
})

test('锚点解析: 空输入不抛, 报全缺', () => {
  const { anchors, missing } = resolveAnchors([])
  assert.equal(anchors.size, 0)
  assert.equal(missing.length, 12, '4 个固定落点 + 8 个缸')
  assert.equal(resolveAnchors(null).missing.length, 12)
})

// ── 硅胶朝哪一面 ───────────────────────────────────────────────────────────
// 依据是取放动作的 rotary 态, 不是观感。画反了画面看不出异样, 但"吸盘去吸硅胶粉面"
// 这条语义整条链都错(用户第 3 条明确要求吸盘贴玻璃面)。

test('硅胶朝向: 只有点样座与刮板台朝上, 其余(含全部展缸)朝下', () => {
  assert.equal(isSilicaUp(PLATE_SLOT.SPOT_SEAT), true)
  assert.equal(isSilicaUp(PLATE_SLOT.SCRAPE_TABLE), true)
  assert.equal(isSilicaUp(PLATE_SLOT.FEEDLIFT), false, '料仓里玻璃面必须朝上供吸盘贴')
  assert.equal(isSilicaUp(PLATE_SLOT.WASTE), false)
  for (let n = 1; n <= TANK_COUNT; n += 1) {
    assert.equal(isSilicaUp(`tank:${n}`), false, `展缸 ${n} 是 rotary-down`)
  }
})

test('硅胶朝向: 未知词一律按朝下处理, 不抛错', () => {
  assert.equal(isSilicaUp(''), false)
  assert.equal(isSilicaUp(null), false)
  assert.equal(isSilicaUp('nowhere'), false)
})
