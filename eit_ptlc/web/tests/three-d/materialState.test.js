import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  EVENT_CELL_KEY_TO_SNAPSHOT_KEY, EVENT_KEY_TO_SNAPSHOT_KEY, MaterialStateStore,
} from '../../src/three-d/twin/bindings/MaterialStateStore.js'
import { TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'
import { TwinBindings } from '../../src/three-d/twin/bindings/TwinBindings.js'
import { TrayBinding } from '../../src/three-d/twin/bindings/TrayBinding.js'
import * as THREE from 'three'

/** 一条整板在途行(大爪拿着货架 1 号收集器托盘), 形状照后端 MaterialStore.grid()["transit"]。 */
const TRANSIT_TRAY = {
  gripper_plate96: {
    carrier: 'gripper_plate96', payload: 'tray', kind: 'collector', plate: 1,
    hole: null, from_loc: 'rack', to_loc: '', since_at: 1_700_000_000,
    run_id: 'r1', script: 'robot_group_rack_pick',
  },
}

/** 一件停在刮板夹具上的粉桶, 形状照后端 grid()["payload_seats"] 的一行。 */
const SEATED_ITEM = {
  seat: 'scrape-holder', label: '刮板夹具 (接粉收集器位)', accepts: 'collector',
  payload: 'item', kind: 'collector', plate: 3, hole: 6,
  since_at: 1_700_000_000, run_id: 'r1', script: 'robot_scrape_holder_put_exit',
  epoch: '1700000000-1-1', stale: false,
}

const CONTRACT_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)), 'materialGrid.contract.json',
)

function event(overrides = {}) {
  const cells = []
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 6; plate += 1) {
      for (let hole = 1; hole <= 6; hole += 1) {
        cells.push({ kind, plate, hole, state: hole <= 2 ? 'FRESH' : 'USED', sample_id: '' })
      }
    }
  }
  return {
    type: 'material_state', seq: 1, ts: 1_700_000_000,
    cells,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: 3 },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    summary: {},
    presence: [
      { location_id: 'rack.collector.3', present: false, expected: false, ok: true },
      { location_id: 'staging-a', present: true, expected: true, ok: true, verified: true },
    ],
    presence_mismatches: 0,
    magazines: [
      { magazine: 'feed', count: 6, capacity: 30 },
      { magazine: 'waste', count: 8, capacity: 30 },
    ],
    bottles: [],
    ...overrides,
  }
}

test('MaterialStateStore 投影两类 6 张托盘、中转占用和板仓数量', () => {
  const store = new MaterialStateStore({ staleMs: 12_000 })
  const now = 1_700_000_000_000
  assert.equal(store.push(event(), now), true)
  const status = store.status(now)
  assert.equal(status.stale, false)
  assert.equal(status.snapshot.rack.collector.length, 6)
  assert.equal(status.snapshot.rack.collector[2].fresh, 2)
  assert.equal(status.snapshot.rack.collector[2].present, false)
  assert.equal(status.snapshot.staging['staging-a'].plate, 3)
  assert.equal(status.snapshot.magazines.find((item) => item.magazine === 'feed').count, 6)
})

test('物料断线冻结末帧、乱序快照不覆盖新值、initial 允许重启 seq', () => {
  const store = new MaterialStateStore()
  const base = 1_700_000_000_000
  store.push(event(), base)
  assert.equal(store.push(event({ seq: 0, ts: 1_699_999_999 }), base + 100), false)
  store.markDisconnected()
  assert.equal(store.status(base + 100).snapshot.magazines[0].count, 6)
  assert.equal(store.status(base + 100).stale, true)
  assert.equal(store.push(event({ seq: 0, ts: 1_700_000_001, initial: true }), base + 1000), true)
  assert.equal(store.status(base + 1000).stale, false)
})

test('TwinFeed 接收 material_state 并纳入实时状态', () => {
  const feed = new TwinFeed({ axes: [], stations: [], realtime: { mechanisms: [] } })
  feed.setTransportState(true)
  feed.handleEvent(event())
  const status = feed.realtimeStatus(1_700_000_000_000)
  assert.equal(status.materials.available, true)
  assert.equal(status.materials.snapshot.staging['staging-a'].plate, 3)
})

test('在途段必须原样活过 normalizeSnapshot —— 它是显式白名单, 漏一个键下游就永远看不到', () => {
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  assert.equal(store.push(event({ transit: TRANSIT_TRAY }), now), true)
  const transit = store.status(now).snapshot.transit
  assert.deepEqual(Object.keys(transit), ['gripper_plate96'])
  const row = transit.gripper_plate96
  assert.equal(row.payload, 'tray')
  assert.equal(row.kind, 'collector')
  assert.equal(row.plate, 1)
  assert.equal(row.hole, null)
  assert.equal(row.from_loc, 'rack')
  assert.equal(row.script, 'robot_group_rack_pick')
})

test('后端没有 transit 段时降级为空手, 不得整帧拒收', () => {
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  assert.equal(store.push(event(), now), true, '旧后端的快照仍须收下')
  assert.deepEqual(store.status(now).snapshot.transit, {})
})

test('契约绊线: grid() 的每个顶层键都必须在 EVENT_KEY_TO_SNAPSHOT_KEY 里显式表态', () => {
  // 双段绊线的第二段 (第一段是 pytest 的 TestGridContract)。
  // 金样是从真 grid() dump 的键集, Python 与 Node 读同一份字节。
  // 重新生成金样(后端有意加字段时):
  //   $env:PYTHONIOENCODING='utf-8'
  //   & C:/ProgramData/miniforge3/python.exe -c "见 tests 里 TestGridContract 的 _full_grid"
  // 表态而不是"存在即可": 没有这一步, 测试分不清"消费了并改名"与"整个丢掉了"。
  const golden = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf-8'))
  for (const key of golden.top) {
    assert.ok(
      key in EVENT_KEY_TO_SNAPSHOT_KEY,
      `grid() 的 ${key} 没在 EVENT_KEY_TO_SNAPSHOT_KEY 里表态 —— `
      + '要么投影它, 要么显式写成空串说明有意不投影',
    )
  }
  // 表了态说要投影的, 必须真的出现在产物里
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  store.push(event({
    transit: TRANSIT_TRAY,
    transit_stale: 0,
    payload_seats: [SEATED_ITEM],
    seats: [{ seat: 'spot_seat', label: '点样座', present: true, updated_at: 1 }],
    topology: { categories: [] },
  }), now)
  const snapshot = store.status(now).snapshot
  for (const [eventKey, snapshotKey] of Object.entries(EVENT_KEY_TO_SNAPSHOT_KEY)) {
    if (!snapshotKey) continue
    assert.ok(snapshotKey in snapshot,
      `${eventKey} 表态要投影成 ${snapshotKey}, 但快照里没有这个键`)
  }
})

test('契约绊线(行内层): cells 的每个列名都必须在 EVENT_CELL_KEY_TO_SNAPSHOT_KEY 里显式表态', () => {
  // 上面那条只管**顶层**键, 而 cells 在 normalizeSnapshot 里是逐字段重建的数组:
  // 后端给 cell 加一列时顶层键一个没变, 于是 pytest 的 TestGridContract 与上面那条
  // 全都不响, 新列静默消失在三维侧。这一层此前完全没有门 —— 2026-08 加内容物余量
  // 三列时补的就是它。
  const golden = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf-8'))
  for (const column of golden.cellRow) {
    assert.ok(
      column in EVENT_CELL_KEY_TO_SNAPSHOT_KEY,
      `cells 的 ${column} 没在 EVENT_CELL_KEY_TO_SNAPSHOT_KEY 里表态 —— `
      + '要么投影它, 要么显式写成空串说明有意不投影',
    )
  }
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  store.push(event(), now)
  const [cell] = store.status(now).snapshot.cells
  for (const [column, snapshotKey] of Object.entries(EVENT_CELL_KEY_TO_SNAPSHOT_KEY)) {
    if (!snapshotKey) continue
    assert.ok(snapshotKey in cell,
      `cells.${column} 表态要投影成 ${snapshotKey}, 但归一化后的 cell 里没有这个键`)
  }
})

test('内容物余量: 数值原样活过归一化, eluted 归一成布尔; 旧后端缺字段降级为 0/false', () => {
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  const cells = []
  for (const kind of ['collector', 'bottle']) {
    for (let plate = 1; plate <= 6; plate += 1) {
      for (let hole = 1; hole <= 6; hole += 1) {
        cells.push({
          kind, plate, hole, state: 'USED', sample_id: '',
          // 粉桶有粉、洗过 (后端发的是 0/1 整数); 样品瓶有淋洗液
          powder_mm3: kind === 'collector' ? 768.4 : 0,
          liquid_ml: kind === 'bottle' ? 20.5 : 0,
          eluted: kind === 'collector' ? 1 : 0,
        })
      }
    }
  }
  store.push(event({ cells }), now)
  const snapshot = store.status(now).snapshot
  const collector = snapshot.cells.find((c) => c.kind === 'collector')
  const bottle = snapshot.cells.find((c) => c.kind === 'bottle')
  assert.equal(collector.powder_mm3, 768.4)
  assert.equal(collector.eluted, true, '0/1 整数必须归一成布尔')
  assert.equal(bottle.liquid_ml, 20.5)
  assert.equal(bottle.eluted, false)

  // 旧后端(没有这三列)必须降级为 0/false, 而不是 NaN/undefined, 更不能整帧拒收
  store.push(event({ seq: 2 }), now + 1)
  const [old] = store.status(now + 1).snapshot.cells
  assert.equal(old.powder_mm3, 0)
  assert.equal(old.liquid_ml, 0)
  assert.equal(old.eluted, false)
})

test('陈旧在途行的 stale 必须原样活过归一化 —— 三维据它决定挂不挂载', () => {
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  const stale = {
    gripper_plate96: { ...TRANSIT_TRAY.gripper_plate96, epoch: '1-2-3', stale: true },
  }
  store.push(event({ transit: stale, transit_stale: 1 }), now)
  const snapshot = store.status(now).snapshot
  assert.equal(snapshot.transit.gripper_plate96.stale, true)
  assert.equal(snapshot.transit.gripper_plate96.epoch, '1-2-3')
  assert.equal(snapshot.transitStale, 1)
  // 旧后端不发这两个字段时降级为"可信", 而不是整帧拒收
  store.push(event({ transit: TRANSIT_TRAY, seq: 2 }), now + 1)
  assert.equal(store.status(now + 1).snapshot.transit.gripper_plate96.stale, false)
})

test('工位座段必须原样活过归一化 —— 漏了它站侧的件会仍显示在托盘孔里', () => {
  const store = new MaterialStateStore()
  const now = 1_700_000_000_000
  store.push(event({ payload_seats: [SEATED_ITEM] }), now)
  const seats = store.status(now).snapshot.payloadSeats
  assert.equal(seats.length, 1)
  assert.equal(seats[0].seat, 'scrape-holder')
  assert.equal(seats[0].kind, 'collector')
  assert.equal(seats[0].plate, 3)
  assert.equal(seats[0].hole, 6)
  assert.equal(seats[0].accepts, 'collector')
  // 座位陈旧的语义与在途**相反**: 瓶子停在工位上, 后端重启它不会自己跑掉, 仍然可信
  assert.equal(seats[0].stale, false)
  // 旧后端没有这一段时降级为空表
  store.push(event({ seq: 2 }), now + 1)
  assert.deepEqual(store.status(now + 1).snapshot.payloadSeats, [])
})

test('贯穿链: material_state 事件 -> TwinFeed -> TrayBinding, 托盘挂上 TOOL_MOUNT', () => {
  // 这一条才是本类 bug 的守门人。只测 TrayBinding 自身(手搓 snapshot)会绕开
  // MaterialStateStore 的归一化, 而 2026-08-05 那次"托盘不跟手"正是丢在那一层。
  const root = new THREE.Group()
  const nodeIndex = new Map()
  const add = (name, parent) => {
    const node = new THREE.Group()
    node.name = name
    parent.add(node)
    nodeIndex.set(name, node)
    return node
  }
  const holder = add('上料架-1', root)
  const tray = add('INV_RACK_COLLECTOR_1', holder)
  tray.position.set(-1, 0.8, 0)
  const mount = add('TOOL_MOUNT', root)
  mount.position.set(0, 1.4, 0)
  root.updateMatrixWorld(true)

  const manifest = {
    robot: { toolMount: 'TOOL_MOUNT' },
    inventory: {
      rack: [{ kind: 'collector', plate: 1, node: 'INV_RACK_COLLECTOR_1', items: [] }],
      staging: [],
    },
    axes: [], stations: [], realtime: { mechanisms: [] },
  }
  const feed = new TwinFeed(manifest)
  feed.setTransportState(true)
  const trays = new TrayBinding({ manifest, resolve: (path) => nodeIndex.get(path), feed })

  feed.handleEvent(event())
  trays.update(0.016)
  assert.equal(tray.parent, holder, '账本说没有在途载荷时托盘不该动')

  feed.handleEvent(event({ seq: 2, ts: 1_700_000_001, transit: TRANSIT_TRAY }))
  trays.update(0.016)
  assert.equal(tray.parent, mount, '在途行到了, 托盘必须挂到快换安装座下跟手走')
  assert.equal(tray.visible, true)
  assert.ok(trays.owned.has('INV_RACK_COLLECTOR_1'))

  // 落位: 在途行消失 -> 换回原父级
  feed.handleEvent(event({ seq: 3, ts: 1_700_000_002 }))
  trays.update(0.016)
  assert.equal(tray.parent, holder)
})

test('实时链: 驻位液体由物料账本驱动 —— 补上 manifest.liquids 长期只有离线链消费的缺口', () => {
  // 此前 manifest.liquids 的消费方只有 MachineStateDriver / flowSim / actionSim 三处,
  // TwinBindings 一处都没有 ⇒ /3d/demo 上瓶里能看到淋洗液, /3d/live 上那只瓶永远是空的。
  // 驱动源用**账本**而不是动作包络: 账本是持久态, 刷新/重连/跑完一整批之后再打开三维,
  // 瓶里该有多少还是多少 —— "使用后的旧状态"要的就是这个。
  const scene = new THREE.Group()
  const bottle = new THREE.Group(); bottle.name = '样品瓶-2'; scene.add(bottle)
  const liquid = new THREE.Mesh(
    new THREE.CylinderGeometry(0.011, 0.011, 0.078, 8), new THREE.MeshStandardMaterial())
  liquid.name = 'LIQUID_COLLECT_BOTTLE'
  bottle.add(liquid)
  scene.updateMatrixWorld(true)

  const manifest = {
    stations: [], axes: [], tools: [], robot: { jointsRigged: false },
    realtime: { mechanisms: [] },
    inventory: { visibleStates: ['FRESH'], rack: [], staging: [] },
    // 形状照 gen_twin_manifest 落的 liquids[] 一条 (内径 22 / 可用深 78 ⇒ 29.65mL;
    // 78 = 实测肩高 83.0 − 瓶底 5.0, 瓶颈那 12mm 不计体积)
    liquids: [{
      id: 'liq_collect_bottle', seat: 'collect-bottle', node: 'LIQUID_COLLECT_BOTTLE',
      cavity: { usableDepthMm: 78, freeAreaMm2: 380.1, capacityMl: 29.65, mlPerMm: 0.3801 },
      exaggeration: 1, actions: {},
    }],
  }
  const index = new Map([['样品瓶-2', bottle], ['LIQUID_COLLECT_BOTTLE', liquid]])
  const feed = new TwinFeed(manifest)
  const bindings = new TwinBindings(manifest, index, feed)
  assert.equal(bindings.stationLiquids.length, 1, 'manifest.liquids 必须被实时链解析')
  assert.notEqual(bindings.stationLiquids[0].material, liquid.material.constructor.prototype,
    '材质必须克隆, 否则将来写色会污染展缸/泵共用的 MAT_LIQUID')

  // 座上没件 ⇒ 液柱归零并隐藏 (瓶被搬走了, 液不该留在原地)
  feed.handleEvent(event({ payload_seats: [] }))
  bindings.update(1)
  assert.equal(liquid.visible, false)

  // 收集位上坐着 bottle 板1孔2, 账本记 20.5mL ⇒ 液面涨起来
  const cells = event().cells
  cells.find((c) => c.kind === 'bottle' && c.plate === 1 && c.hole === 2).liquid_ml = 20.5
  feed.handleEvent(event({
    seq: 2,
    ts: 1_700_000_001,
    cells,
    payload_seats: [{
      seat: 'collect-bottle', label: '收集工位 (样品瓶位)', accepts: 'bottle',
      payload: 'item', kind: 'bottle', plate: 1, hole: 2,
      since_at: 1_700_000_000, run_id: 'r1', script: 'robot_collect_bottle_put',
      epoch: 'e1', stale: false,
    }],
  }))
  for (let i = 0; i < 40; i += 1) bindings.update(0.2)   // 趋近到位
  assert.equal(liquid.visible, true)
  // 20.5mL / 380.1mm² = 53.9mm 高, 占可用深 78mm 的 69.1%(放大系数 1 ⇒ 真实高度)。
  // 2026-08-07 由 0.634 改来: 分母从 85 换成 78(瓶颈不计体积), 不是回归。
  assert.ok(Math.abs(bindings.stationLiquids[0].lastLevel - 0.691) < 0.01,
    `液位 ${bindings.stationLiquids[0].lastLevel} 应≈0.691`)

  // 瓶被取走 ⇒ 回零 (而不是把上一只瓶的液留在座上)
  feed.handleEvent(event({ seq: 3, ts: 1_700_000_002, payload_seats: [] }))
  for (let i = 0; i < 40; i += 1) bindings.update(0.2)
  assert.equal(liquid.visible, false)
})

test('实时链: 粉桶里的粉由物料账本驱动, 洗脱后换色', () => {
  // 与上面那条驻位液体同一条驱动纪律(账本是持久态), 多两样东西: 粉量单位是 mm³、
  // 洗脱色由 cells.eluted 决定。两条链共用 powderPivot 的纯函数, 这里钉住实时链这一半。
  const scene = new THREE.Group()
  const holder = new THREE.Group(); holder.name = '硅胶收集-1'; scene.add(holder)
  const shared = new THREE.MeshStandardMaterial({ color: '#e8e4dc' })
  const column = new THREE.Mesh(
    new THREE.CylinderGeometry(0.0092, 0.0092, 0.073, 8), shared)
  column.name = 'POWDER_COLLECT_HOLDER'
  holder.add(column)
  scene.updateMatrixWorld(true)

  const manifest = {
    stations: [], axes: [], tools: [], robot: { jointsRigged: false },
    realtime: { mechanisms: [] },
    inventory: { visibleStates: ['FRESH'], rack: [], staging: [] },
    // 形状照 gen_twin_manifest 落的 consumableContents.kinds 一条(腔段实测 73mm、
    // 内衬孔 Ø18.4 ⇒ 自由截面 265.9mm²; 容量键叫 capacityMm3 以免误喂进 levelFromMl)
    consumableContents: {
      kinds: [{
        id: 'powder_collect_holder', kind: 'powder', seat: 'collect-holder',
        node: 'POWDER_COLLECT_HOLDER', accepts: 'collector',
        cavity: { usableDepthMm: 73, freeAreaMm2: 265.9, capacityMm3: 19410.7, mm3PerMm: 265.9 },
        chamber: { c0: 0.005, c1: 0.078 },
        exaggeration: 6, bulkFactor: 1.6, elutedColor: '#8a7d6b',
      }],
    },
  }
  const index = new Map([['硅胶收集-1', holder], ['POWDER_COLLECT_HOLDER', column]])
  const feed = new TwinFeed(manifest)
  const bindings = new TwinBindings(manifest, index, feed)
  assert.equal(bindings.consumablePowders.length, 1, 'consumableContents 必须被实时链解析')
  assert.notEqual(column.material, shared, '材质必须克隆, 否则洗脱换色会把货架上别的桶一起染色')

  // 座上没件 ⇒ 粉归零并隐藏(桶被搬走了, 粉不该留在原地)
  feed.handleEvent(event({ payload_seats: [] }))
  bindings.update(1)
  assert.equal(column.visible, false)

  // 收集夹具上坐着 collector 板3孔6, 账本记 768mm³ 且已洗脱 ⇒ 粉涨起来并换色
  const cells = event().cells
  const cell = cells.find((c) => c.kind === 'collector' && c.plate === 3 && c.hole === 6)
  cell.powder_mm3 = 768
  cell.eluted = 1
  const dry = column.material.color.getHex()
  feed.handleEvent(event({
    seq: 2,
    ts: 1_700_000_001,
    cells,
    payload_seats: [{
      seat: 'collect-holder', label: '收集工位 (粉桶位)', accepts: 'collector',
      payload: 'item', kind: 'collector', plate: 3, hole: 6,
      since_at: 1_700_000_000, run_id: 'r1', script: 'robot_collect_holder_put_exit',
      epoch: 'e1', stale: false,
    }],
  }))
  for (let i = 0; i < 40; i += 1) bindings.update(0.2)   // 趋近到位
  assert.equal(column.visible, true)
  // 768mm³ / 265.9mm² = 2.888mm 真实高, ×6 观感放大 / 腔深 73mm = 0.237
  assert.ok(Math.abs(bindings.consumablePowders[0].lastLevel - 0.237) < 0.01,
    `粉位 ${bindings.consumablePowders[0].lastLevel} 应≈0.237`)
  assert.notEqual(column.material.color.getHex(), dry, '账本说洗过了, 粉必须换色')
  assert.equal(shared.color.getHex(), 0xe8e4dc, '共用材质一个通道都不许被改')

  bindings.dispose()
})

test('TwinBindings 隐藏已搬到中转的货架托盘并按真实模板堆叠玻璃板', () => {
  const scene = new THREE.Group()
  const rack = new THREE.Group(); rack.name = 'INV_RACK_COLLECTOR_1'; scene.add(rack)
  const staging = new THREE.Group(); staging.name = 'INV_STAGING_A'; scene.add(staging)
  const rackItems = Array.from({ length: 6 }, (_, index) => {
    const item = new THREE.Group(); item.name = `INV_RACK_COLLECTOR_1_ITEM_${index + 1}`; rack.add(item); return item
  })
  const stagingItems = Array.from({ length: 6 }, (_, index) => {
    const item = new THREE.Group(); item.name = `INV_STAGING_A_ITEM_${index + 1}`; staging.add(item); return item
  })
  const glass = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.003, 0.2)); glass.name = 'INV_FEED'; scene.add(glass)
  const toolMount = new THREE.Group(); toolMount.name = 'TOOL_MOUNT'; scene.add(toolMount)
  const manifest = {
    stations: [], axes: [], tools: [], robot: { jointsRigged: false },
    realtime: { mechanisms: [] },
    inventory: {
      visibleStates: ['FRESH'],
      visibleWhenSampleId: true,
      rack: [{ kind: 'collector', plate: 1, node: 'INV_RACK_COLLECTOR_1', items: rackItems.map((item) => item.name) }],
      staging: [{ area: 'staging-a', kind: 'collector', node: 'INV_STAGING_A', items: stagingItems.map((item) => item.name) }],
      magazines: [{ id: 'feed', node: 'INV_FEED', stackAxis: [0, 1, 0], spacingM: 0.003 }],
    },
  }
  const index = new Map([
    ['INV_RACK_COLLECTOR_1', rack], ['INV_STAGING_A', staging], ['INV_FEED', glass],
    ['TOOL_MOUNT', toolMount],
    ...rackItems.map((item) => [item.name, item]),
    ...stagingItems.map((item) => [item.name, item]),
  ])
  const feed = new TwinFeed(manifest)
  const bindings = new TwinBindings(manifest, index, feed)
  assert.equal(rack.visible, false, '收到第一帧物料真值前不能展示 CAD 默认库存')
  assert.equal(staging.visible, false, '中转位必须默认空，不能把 CAD 示例件冒充账本状态')
  assert.equal(glass.visible, false, '板仓模板必须等到账本数量后再显示')
  const cellsWithFilledItem = event().cells
  cellsWithFilledItem.find((cell) => (
    cell.kind === 'collector' && cell.plate === 1 && cell.hole === 3
  )).sample_id = 'S-001'
  feed.handleEvent(event({
    seq: 1,
    cells: cellsWithFilledItem,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: 1 },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    magazines: [{ magazine: 'feed', count: 3, capacity: 30 }],
  }))
  bindings.update(0)
  assert.equal(rack.visible, false)
  assert.equal(staging.visible, true)
  // 三态定案(2026-08-15): 孔 1-2 FRESH 直立, 孔 3 带样品号, 孔 4-6 USED 倒扣**常显**
  assert.deepEqual(stagingItems.map((item) => item.visible), [true, true, true, true, true, true])
  const flipAngle = (item) => item.quaternion.angleTo(new THREE.Quaternion())
  assert.ok(flipAngle(stagingItems[0]) < 1e-6, 'FRESH 件保持直立')
  assert.ok(Math.abs(flipAngle(stagingItems[5]) - Math.PI) < 1e-6, 'USED 粉桶要倒扣 180°')
  assert.equal(bindings.materialMagazines[0].clones.length, 2)
  assert.equal(bindings.materialMagazines[0].clones[1].position.y, 0.006)

  feed.handleEvent(event({
    seq: 2, ts: 1_700_000_001,
    magazines: [{ magazine: 'feed', count: 35, capacity: 30 }],
  }))
  bindings.update(0)
  assert.equal(bindings.materialMagazines[0].count, 30)

  feed.handleEvent(event({
    seq: 3, ts: 1_700_000_002,
    cells: cellsWithFilledItem,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: null },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    magazines: [{ magazine: 'feed', count: 1, capacity: 30 }],
  }))
  bindings.update(0)
  assert.equal(rack.visible, true)
  assert.equal(staging.visible, false)
  assert.deepEqual(rackItems.map((item) => item.visible), [true, true, true, true, true, true])
  assert.ok(Math.abs(rackItems[4].quaternion.angleTo(new THREE.Quaternion()) - Math.PI) < 1e-6,
    '回架后 USED 粉桶仍倒扣')
  assert.equal(stagingItems.every((item) => !item.visible), true)
  assert.equal(bindings.materialMagazines[0].clones.every((item) => !item.visible), true)

  // ── ABSENT 不画 + 座上件孔画空 + 在架人工账控托盘 ─────────────────────
  const triCells = event().cells
  triCells.find((c) => c.kind === 'collector' && c.plate === 1 && c.hole === 5).state = 'ABSENT'
  feed.handleEvent(event({
    seq: 4, ts: 1_700_000_003,
    cells: triCells,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: null },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    // 孔 4 的桶此刻停在刮板夹具上: 有座位行 ⇒ 该孔必须画空
    payload_seats: [{ ...SEATED_ITEM, plate: 1, hole: 4 }],
    magazines: [{ magazine: 'feed', count: 1, capacity: 30 }],
  }))
  bindings.update(0)
  assert.deepEqual(rackItems.map((item) => item.visible), [true, true, true, false, false, true],
    '孔4 在座上画空, 孔5 ABSENT 不画, 孔6 USED 倒扣常显')

  // 在架人工账记无板 -> 托盘整棵隐藏(rackLedger 投影)
  feed.handleEvent(event({
    seq: 5, ts: 1_700_000_004,
    staging: {
      'staging-a': { area: 'staging-a', kind: 'collector', plate: null },
      'staging-b': { area: 'staging-b', kind: 'bottle', plate: null },
    },
    rack: [{ kind: 'collector', plate: 1, present: 0, updated_at: 0, run_id: '' }],
    magazines: [{ magazine: 'feed', count: 1, capacity: 30 }],
  }))
  bindings.update(0)
  assert.equal(rack.visible, false, '账本记无板的库位托盘要隐藏')

  bindings.dispose()
  glass.geometry.dispose()
  glass.material.dispose()
})
