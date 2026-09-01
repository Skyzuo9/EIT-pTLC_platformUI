// 物料拾取纯逻辑测试 (twin/scene/materialPick.js): 可见性守卫 / 祖先反查 /
// 最近孔吸附 / 菜单时刻身份补全。四条都是踩过坑的裁决, 离线锁死:
//   - three 的 Raycaster 根本不查 visible (空孔隐藏件会被"隔空命中");
//   - 瓶=单 mesh / 桶=4 mesh Group, 形态不一靠父链统一;
//   - 在途时节点已挂去 TOOL_MOUNT, 空孔反查必须用建索引时缓存的 home 局部位;
//   - 中转板号是流动的, 菜单时刻从快照现取。
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  HOLE_SNAP_MAX_DIST_M, cellDisplaySite, identityAtMenuTime, isShownUpTo, nearestHole, resolveHit,
} from '../../src/three-d/twin/scene/materialPick.js'

/** 造一棵普通对象树 (顶替 three Object3D: 只需要 visible/parent) */
function chain(...visibles) {
  let parent = null
  let leaf = null
  for (const visible of visibles) {
    leaf = { visible, parent }
    parent = leaf
  }
  return leaf
}

test('isShownUpTo: 任一祖先 invisible 即不可见 (Raycaster 不查 visible 的补刀)', () => {
  assert.equal(isShownUpTo(chain(true, true, true)), true)
  assert.equal(isShownUpTo(chain(true, false, true)), false, '父级隐藏 -> 子网格不可选')
  assert.equal(isShownUpTo(chain(false, true, true)), false)
  // root 截断: root 之上的隐藏不影响 (拾取只关心机器子树内的可见性)
  const root = { visible: true, parent: { visible: false, parent: null } }
  const mesh = { visible: true, parent: root }
  assert.equal(isShownUpTo(mesh, root), true)
})

test('resolveHit: item 登记比 tray 深, 命中未登记子网格时父链兜底', () => {
  const trayNode = { visible: true, parent: null }
  const itemNode = { visible: true, parent: trayNode }
  const subMesh = { visible: true, parent: itemNode }     // 桶 Group 里的网格
  const map = new Map()
  map.set(trayNode, { type: 'tray' })
  map.set(itemNode, { type: 'item', hole: 3 })
  assert.equal(resolveHit(subMesh, map).type, 'item', '未登记子网格沿父链先遇 item')
  const trayMesh = { visible: true, parent: trayNode }
  assert.equal(resolveHit(trayMesh, map).type, 'tray')
  assert.equal(resolveHit({ visible: true, parent: null }, map), null)
})

test('nearestHole: 孔隙吸附到最近孔, 超一个孔距算托盘本体', () => {
  // 6 孔行优先网格 (47.5 x 45 mm, 与协议文档孔距同数量级)
  const offsets = []
  let hole = 1
  for (const y of [0, -0.045]) {
    for (const x of [0, 0.0475, 0.095]) offsets.push({ hole: hole++, x, y, z: 0 })
  }
  assert.equal(nearestHole({ x: 0.001, y: 0.002, z: 0 }, offsets).hole, 1)
  assert.equal(nearestHole({ x: 0.07, y: -0.04, z: 0 }, offsets).hole, 5, '孔隙吸附最近孔')
  assert.equal(nearestHole({ x: 0.4, y: 0, z: 0 }, offsets), null, '超阈值 = 托盘本体')
  assert.equal(nearestHole({ x: 0, y: 0, z: 0 }, []), null)
  assert.ok(HOLE_SNAP_MAX_DIST_M > 0.04 && HOLE_SNAP_MAX_DIST_M <= 0.05,
            '阈值应是一个孔距的量级')
})

test('identityAtMenuTime: 中转板号从快照现取', () => {
  const snapshot = {
    staging: { 'staging-a': { area: 'staging-a', kind: 'collector', plate: 3 } },
    cells: [{ kind: 'collector', plate: 3, hole: 2, state: 'FRESH',
              powder_mm3: 0, liquid_ml: 0, eluted: 0 }],
    transit: {}, payloadSeats: [], magazines: [],
  }
  const info = identityAtMenuTime(
    { type: 'item', loc: 'staging', area: 'staging-a', kind: 'collector',
      plate: null, hole: 2 }, snapshot)
  assert.equal(info.plate, 3, '建索引时恒 null, 菜单时刻从 staging 现取')
  assert.equal(info.cell.state, 'FRESH')
  const empty = identityAtMenuTime(
    { type: 'item', loc: 'staging', area: 'staging-a', kind: 'collector',
      plate: null, hole: 2 },
    { ...snapshot, staging: { 'staging-a': { plate: null } } })
  assert.equal(empty.plate, null, '中转空着 -> 无孔账可指')
})

test('identityAtMenuTime: 整板在途覆盖其 6 件, 单件在途只覆盖同孔', () => {
  const base = { type: 'item', loc: 'rack', kind: 'bottle', plate: 4, hole: 1 }
  const trayTransit = {
    staging: {}, cells: [], payloadSeats: [], magazines: [],
    transit: { gripper_plate96: { carrier: 'gripper_plate96', payload: 'tray',
                                  kind: 'bottle', plate: 4, hole: null, stale: false } },
  }
  assert.equal(identityAtMenuTime(base, trayTransit).transitCarrier, 'gripper_plate96')
  const itemTransit = {
    staging: {}, cells: [], payloadSeats: [], magazines: [],
    transit: { gripper_vial: { carrier: 'gripper_vial', payload: 'item',
                               kind: 'bottle', plate: 4, hole: 2, stale: true } },
  }
  assert.equal(identityAtMenuTime(base, itemTransit).transitCarrier, null,
               '单件在途只覆盖同孔 (hole 2 != 1)')
  const hit = identityAtMenuTime({ ...base, hole: 2 }, itemTransit)
  assert.equal(hit.transitCarrier, 'gripper_vial')
  assert.equal(hit.transitStale, true)
})

test('identityAtMenuTime: 座位与板仓行补全', () => {
  const snapshot = {
    staging: {}, cells: [], transit: {},
    payloadSeats: [{ seat: 'scrape-holder', label: '刮板夹具', kind: 'collector',
                     plate: 2, hole: 6 }],
    magazines: [{ magazine: 'feed', label: '上料仓', count: 12, capacity: 30 }],
  }
  const seated = identityAtMenuTime(
    { type: 'item', loc: 'rack', kind: 'collector', plate: 2, hole: 6 }, snapshot)
  assert.equal(seated.seatedAt.seat, 'scrape-holder')
  const magazine = identityAtMenuTime({ type: 'magazine', magazine: 'feed' }, snapshot)
  assert.equal(magazine.magazineRow.count, 12)
  // 无快照 (断流) 时不炸, 全部补全字段为空
  const offline = identityAtMenuTime({ type: 'magazine', magazine: 'feed' }, null)
  assert.equal(offline.magazineRow, null)
})

test('cellDisplaySite: 在架/在中转/在途三态裁决 (面板反向定位描边目标)', () => {
  // 在架: 没被搬走就画在货架
  assert.deepEqual(cellDisplaySite('collector', 2, { staging: {}, transit: {} }),
    { site: 'rack', area: null })
  // 在中转: 该板号停在对应中转区 -> 实体画在中转 item 上
  const staged = { staging: { 'staging-a': { plate: 2, kind: 'collector' } }, transit: {} }
  assert.deepEqual(cellDisplaySite('collector', 2, staged), { site: 'staging', area: 'staging-a' })
  // 别的板在中转不影响本板
  assert.deepEqual(cellDisplaySite('collector', 5, staged), { site: 'rack', area: null })
  // 瓶类走 staging-b, 与 collector 的区不串
  assert.deepEqual(cellDisplaySite('bottle', 2, staged), { site: 'rack', area: null })
  // 整板在途(爪上): 两边都不画, 无处可指
  const inTransit = {
    staging: {},
    transit: { gripper_plate96: { payload: 'tray', kind: 'collector', plate: 3 } },
  }
  assert.equal(cellDisplaySite('collector', 3, inTransit), null)
  // 断流/入参不全: 不炸, 返回 null
  assert.equal(cellDisplaySite('collector', null, staged), null)
  assert.deepEqual(cellDisplaySite('collector', 1, null), { site: 'rack', area: null })
})
