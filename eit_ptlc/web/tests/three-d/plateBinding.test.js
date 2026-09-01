/**
 * 功能: 板绑定层的端到端测试(最小 three 场景, 不起渲染器).
 *
 * 覆盖用户明确要的那条链: 板从料仓被吸起 → 跟着机械臂走 → **随吸盘翻转同步反转** →
 * 放到点样座 → 再进展缸。以及刷新/断连/归属失败时的降级。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { PlateBinding } from '../../src/three-d/twin/bindings/PlateBinding.js'
import { PlateFaceLayer } from '../../src/three-d/twin/scene/plates/PlateFaceLayer.js'

const FLIP_PATH = 'ST_TOOLING/夹具总装-1/TOOL_SUCTION/TOOL_SUCTION_GEOMETRY/ACTUATOR_FLIP_SUCTION'

const MANIFEST = { actuators: [{ id: 'rob_flip_suction', node: FLIP_PATH }] }

/** 造一块 200×3×200 的板锚点网格。 */
function anchorMesh() {
  return new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.003, 0.2), new THREE.MeshBasicMaterial())
}

/** 造与真实模型同构(含乱序缸编号)的最小场景与 nodeIndex。 */
function makeScene() {
  const root = new THREE.Group()
  const nodeIndex = new Map()

  const add = (path, node, parent) => {
    parent.add(node)
    nodeIndex.set(path, node)
  }

  // 展缸: 刻意用实测的乱序对应关系
  const tankPairs = [[1, '玻璃-1.010'], [2, '玻璃-1.009'], [3, '玻璃-1.008'], [4, '玻璃-1.011'],
    [5, '玻璃-1.005'], [6, '玻璃-1.004'], [7, '玻璃-1.003'], [8, '玻璃-1.006']]
  for (const [n, part] of tankPairs) {
    const tank = new THREE.Group()
    tank.name = `TANK_${n}`
    root.add(tank)
    const mesh = anchorMesh()
    mesh.name = part
    mesh.position.set(n * 0.3, 0.5, 0)
    add(`ST_DEVELOP/TANK_${n}/${part}`, mesh, tank)
  }

  const seats = [
    ['玻璃-1', '抽液机构总装-1', 'ST_SAMPLING/抽液机构总装-1/玻璃-1', new THREE.Vector3(0, 1, 0)],
    ['玻璃-1.002', '刮板机构总装-1', 'ST_PHOTOSCRAPE/刮板机构总装-1/玻璃-1.002', new THREE.Vector3(1, 1, 0)],
    ['INV_MAGAZINE_FEED_TEMPLATE', '玻璃上料机构-1', 'ST_FEEDLIFT/玻璃上料机构-1/INV_MAGAZINE_FEED_TEMPLATE', new THREE.Vector3(-1, 0.2, 0)],
    ['INV_MAGAZINE_WASTE_TEMPLATE', '玻璃下料机构-1', 'ST_FEEDLIFT/玻璃下料机构-1/INV_MAGAZINE_WASTE_TEMPLATE', new THREE.Vector3(-1.5, 0.2, 0)],
  ]
  for (const [name, parentName, path, pos] of seats) {
    const holder = new THREE.Group()
    holder.name = parentName
    root.add(holder)
    const mesh = anchorMesh()
    mesh.name = name
    mesh.position.copy(pos)
    add(path, mesh, holder)
  }

  // 翻转气缸: 一个可转的空节点
  const flip = new THREE.Group()
  flip.name = 'ACTUATOR_FLIP_SUCTION'
  flip.position.set(0.4, 1.4, 0)
  add(FLIP_PATH, flip, root)

  root.updateMatrixWorld(true)
  return { root, nodeIndex, flip }
}

function makeBinding({ tool = 1 } = {}) {
  const { root, nodeIndex, flip } = makeScene()
  const layer = new PlateFaceLayer()
  /** 可变的吸盘真空位(后端 rob_suction); 测试里随时翻。 */
  const suction = { held: false }
  const binding = new PlateBinding({
    manifest: MANIFEST,
    nodeIndex,
    layer,
    getMountedTool: () => tool,
    getSuctionHeld: () => suction.held,
  })
  return { binding, layer, root, flip, nodeIndex, suction }
}

/** 一帧调度器快照。 */
function ledgerSnapshot(samples, revision = 1) {
  return {
    revision,
    batches: [{
      batch_id: 'B-1',
      status: 'RUNNING',
      samples: samples.map((s, i) => ({
        sample_id: s.id, seq: i + 1, status: s.status || 'ACTIVE',
        position: s.position, tank: null,
        jobs: [{ flow_id: 's1', seq: 1, run_id: s.run || 'run-1', status: 'RUNNING' }],
      })),
    }],
  }
}

const movePoint = (binding, point, runId = 'run-1') => binding.handleEvent(
  { type: 'vm_node_done', run_id: runId, op: 'call', action: 'robot.move_to_point', status: 'DONE' },
  { point_id_or_robot_name: point },
)
const toolAction = (binding, action, runId = 'run-1') => binding.handleEvent(
  { type: 'vm_node_done', run_id: runId, op: 'call', action: 'robot.tool_action', status: 'DONE' },
  { action },
)

test('锚点解析: 13 个落点全部就位, 且 CAD 盒子被隐藏只当位姿源', () => {
  const { binding, nodeIndex } = makeBinding()
  assert.deepEqual(binding.status().missingAnchors, [])
  assert.equal(binding.anchors.size, 12, '4 个固定落点 + 8 个缸')
  assert.equal(nodeIndex.get('ST_SAMPLING/抽液机构总装-1/玻璃-1').visible, false)
  assert.equal(binding.status().suctionBound, true)
})

test('锚点解析: 缸号按 parent 反查, 3 号缸拿到的是 玻璃-1.008', () => {
  const { binding } = makeBinding()
  const geom = binding.anchors.get('tank:3')
  assert.ok(geom, '3 号缸必须解析到')
  assert.ok(Math.abs(geom.position.x - 0.9) < 1e-6, 'TANK_3 下那块板的位置')
})

test('仓态不建独立板实例(避免与料仓堆叠双记账)', () => {
  const { binding, layer } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'feedlift' }]))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 0)
})

test('落到工位的板被摆到对应锚点位姿上', () => {
  const { binding, layer, nodeIndex } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)

  const entity = layer.get('sample:S-01')
  assert.ok(entity, '应该建出板实体')
  assert.equal(entity.root.parent, nodeIndex.get('ST_SAMPLING/抽液机构总装-1/玻璃-1').parent)
  assert.ok(Math.abs(entity.root.position.y - 1) < 1e-6)
})

test('吸起: 板被挂到翻转气缸下, 且换父当帧世界位姿不跳变', () => {
  const { binding, layer, flip } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)

  const root = layer.get('sample:S-01').root
  root.updateWorldMatrix(true, false)
  const before = new THREE.Vector3().setFromMatrixPosition(root.matrixWorld)

  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  assert.equal(root.parent, flip, '板必须成为翻转节点的子级')
  root.updateWorldMatrix(true, false)
  const after = new THREE.Vector3().setFromMatrixPosition(root.matrixWorld)
  assert.ok(before.distanceTo(after) < 1e-6, `换父当帧不得跳变, 实测位移 ${before.distanceTo(after)}`)
})

test('★ 翻转吸盘, 板同步反转 —— 由父子关系构造成立, 零专门代码', () => {
  const { binding, layer, flip } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  const root = layer.get('sample:S-01').root
  root.updateWorldMatrix(true, false)
  const upBefore = new THREE.Vector3(0, 1, 0).applyQuaternion(
    new THREE.Quaternion().setFromRotationMatrix(root.matrixWorld),
  )

  // 吸盘翻 180°(rob_flip_suction 的 outputRange 就是 [0,180])
  flip.rotateZ(Math.PI)
  flip.updateMatrixWorld(true)
  root.updateWorldMatrix(true, false)
  const upAfter = new THREE.Vector3(0, 1, 0).applyQuaternion(
    new THREE.Quaternion().setFromRotationMatrix(root.matrixWorld),
  )

  assert.ok(upBefore.dot(upAfter) < -0.99, '板的法线必须整个翻过来(硅胶面朝向随之翻转)')
})

test('放板: 落到目标锚点, 并走短补间坐正到 CAD 位姿', () => {
  const { binding, layer } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  movePoint(binding, 'P65')
  toolAction(binding, 'suction-off')
  binding.update(0.016)

  const target = binding.anchors.get('scrape_table')
  const root = layer.get('sample:S-01').root
  assert.equal(root.parent, target.parent)
  // 补间还没跑完时不应立刻等于终值
  binding.update(1.0)
  assert.ok(root.position.distanceTo(target.position) < 1e-6, '补间跑完应严格坐正')
})

test('L1 落后不打断画面: 账本仍报旧位置时板继续跟着手走', () => {
  const { binding, layer, flip } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  // 段还没 DONE, 账本仍是 spot_seat
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 2))
  binding.update(0.016)
  assert.equal(layer.get('sample:S-01').root.parent, flip, '不得把板从手上拽回点样座')
})

test('真冲突以账本为准并计数', () => {
  const { binding, layer } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)
  // 账本忽然说它在 5 号缸 —— 既不是当前位置也不在 L2 轨迹里
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'tank:5' }], 2))
  binding.update(0.016)

  assert.equal(binding.status().corrections, 1)
  assert.equal(layer.get('sample:S-01').root.parent, binding.anchors.get('tank:5').parent)
})

test('取板时板不在那儿 → 拒绝迁移并计数, 绝不硬挪', () => {
  const { binding } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'tank:2' }]))
  binding.update(0.016)
  movePoint(binding, 'P65')          // 末点在刮板台
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  assert.equal(binding.status().rejected, 1)
  assert.equal(binding.plates.get('sample:S-01').slot, 'tank:2', '板应原地不动')
})

test('归属不到 run 时落到 L3 推断板, 并如实标注', () => {
  const { binding } = makeBinding()
  movePoint(binding, 'P19', 'run-手动')
  toolAction(binding, 'suction-on', 'run-手动')
  binding.update(0.016)

  const rows = binding.status().rows
  assert.equal(rows.length, 1)
  assert.match(rows[0].plateId, /^inferred:/)
  assert.equal(rows[0].authority, 'L3')
  assert.equal(rows[0].sampleId, '')
})

test('L3 推断板不被账本回收, 也不被账本接管', () => {
  const { binding } = makeBinding()
  movePoint(binding, 'P19', 'run-手动')
  toolAction(binding, 'suction-on', 'run-手动')
  binding.update(0.016)
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'tank:1' }]))
  binding.update(0.016)

  const rows = binding.status().rows
  assert.equal(rows.filter((r) => r.authority === 'L3').length, 1, '推断板还在')
  assert.equal(rows.filter((r) => r.authority === 'L1').length, 1, '账本板另算一块')
})

test('样品跑完离开账本 → 板实例回收', () => {
  const { binding, layer } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'tank:1' }], 1))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 1)

  binding.pushLedger(ledgerSnapshot([], 2))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 0)
  assert.equal(binding.status().rows.length, 0)
})

test('后端重启(revision 回退): 全部板按账本归位并清 L2 轨迹', () => {
  const { binding, layer, flip } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 90))
  binding.update(0.016)
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)
  assert.equal(layer.get('sample:S-01').root.parent, flip)

  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)
  assert.notEqual(layer.get('sample:S-01').root.parent, flip, '重启后只信账本, 板回到点样座')
})

test('断连: 冻结账本并丢弃在途末点', () => {
  const { binding } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)
  movePoint(binding, 'P19')
  binding.markDisconnected()
  toolAction(binding, 'suction-on')
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').slot, 'spot_seat', '断流后不该再凭旧末点搬板')
  assert.equal(binding.status().frozen, true)
})

test('料仓透传: 张数与实测节距进实体层', () => {
  const { binding, layer } = makeBinding()
  assert.equal(binding.setMagazine('feed', 6, 0.00285), true)
  assert.equal(layer.magazineCount('feed'), 6)
})

// ── 吸盘真空位: 跨页面刷新把"手上那块板"放回去 ────────────────────────────────
// L2 包络刷新即丢, 而 L1 的位置词表里根本没有 `carried` —— 于是刷新后板要么瞬移回上一个
// 停放位, 要么(上一位是料仓时)一块都不画, 后者就是用户看到的"板凭空消失"。真空位 DO3
// 是唯一跨刷新还在的证据。

test('刷新后真空仍通电: 归属不到时补一块推断板挂回吸盘', () => {
  const { binding, layer, flip, suction } = makeBinding()
  suction.held = true
  binding.update(0.016)                     // 刷新后的第一帧: 账本还没到

  const rows = binding.status().rows
  assert.equal(rows.length, 1)
  assert.match(rows[0].plateId, /^inferred:/)
  assert.equal(rows[0].slot, 'carried')
  assert.equal(rows[0].authority, 'L3')
  assert.equal(rows[0].recovered, true, '必须标出来是真空位恢复的, 不许冒充正常持板')
  assert.equal(binding.status().suctionHeld, true)
  assert.equal(layer.get(rows[0].plateId).root.parent, flip, '板要真挂在翻转节点下')
})

test('刷新后真空仍通电: 恰好一个在跑的样品 → 归属到它(仓态样品也算)', () => {
  const { binding, layer, flip, suction } = makeBinding()
  suction.held = true
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'feedlift' }], 1))
  binding.update(0.016)

  assert.equal(binding.plates.get('sample:S-01').slot, 'carried')
  assert.equal(binding.plates.get('sample:S-01').recovered, true)
  assert.equal(layer.get('sample:S-01').root.parent, flip)
})

test('恢复出来的板不被账本每 3s 拽回去, 也不被当成消失回收', () => {
  const { binding, layer, flip, suction } = makeBinding()
  suction.held = true
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'feedlift' }], 1))
  binding.update(0.016)

  // 段还没 DONE, 账本一直说板在上料仓。这既不是冲突(l2Trail 兜着), 也不是"样品消失"
  // (仓态只是不画独立实例) —— 两条路径都不许动这块板。
  for (const revision of [2, 3, 4]) {
    binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'feedlift' }], revision))
    binding.update(0.016)
  }
  assert.equal(binding.plates.get('sample:S-01')?.slot, 'carried')
  assert.equal(layer.get('sample:S-01').root.parent, flip)
  assert.equal(binding.status().corrections, 0, '账本落后不是冲突, 不该计订正')
  assert.equal(binding.status().recoveries, 1, '只该恢复一次, 不许每帧重建')
})

test('刷新后真空仍通电: 多个样品在跑 → 不猜归属, 退回推断板', () => {
  const { binding, suction } = makeBinding()
  suction.held = true
  binding.pushLedger(ledgerSnapshot([
    { id: 'S-01', position: 'feedlift', run: 'run-1' },
    { id: 'S-02', position: 'tank:3', run: 'run-2' },
  ], 1))
  binding.update(0.016)

  const carried = binding.status().rows.filter((row) => row.slot === 'carried')
  assert.equal(carried.length, 1, '手上只能有一块板')
  assert.match(carried[0].plateId, /^inferred:/, '归属不到就如实推断, 不许硬挑一个样品')
})

test('真空掉电但落点事件稍后才到: 宽限期内不得提前销毁, 板照样落到台上', () => {
  const { binding, layer, suction } = makeBinding()
  suction.held = true
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'feedlift' }], 1))
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').slot, 'carried')

  suction.held = false            // 真空位(10Hz)先到
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').slot, 'carried', '宽限期内不许动')

  movePoint(binding, 'P19')       // 落点包络随后才到
  toolAction(binding, 'suction-off')
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').slot, 'spot_seat')
  assert.equal(layer.get('sample:S-01').root.parent, binding.anchors.get('spot_seat').parent)
})

test('真空掉电且无人接手: 推断板销毁(没有账本背书就没有证据说它还在)', () => {
  const { binding, layer, suction } = makeBinding()
  suction.held = true
  binding.update(0.016)
  const inferredId = binding.status().rows[0].plateId

  suction.held = false
  binding.update(0.6)                         // 过宽限
  assert.equal(binding.plates.size, 0)
  assert.equal(layer.get(inferredId), null)
})

test('真空掉电且无人接手: 有账本背书的板交还账本', () => {
  const { binding, suction } = makeBinding()
  suction.held = true
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').slot, 'carried')

  suction.held = false
  binding.update(0.6)
  const plate = binding.plates.get('sample:S-01')
  assert.equal(plate.slot, 'spot_seat', '账本说它在点样座, 那就在点样座')
  assert.equal(plate.authority, 'L1')
  assert.equal(plate.recovered, false)
})

test('真空位先到、账本后到: 推断板被认领, 不许留成"手上一块 + 台上一块"', () => {
  const { binding, layer, flip, suction } = makeBinding()
  suction.held = true
  binding.update(0.016)                     // 真空位(WS 10Hz)先到 → 只能先画无归属板
  assert.match(binding.status().rows[0].plateId, /^inferred:/)

  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)                     // 快照(3s 轮询)随后到

  const rows = binding.status().rows
  assert.equal(rows.length, 1, '认领后场上只能剩一块板')
  assert.equal(rows[0].plateId, 'sample:S-01')
  assert.equal(rows[0].slot, 'carried')
  assert.equal(layer.plateIds().length, 1, '被顶掉的推断板实体必须一并回收')
  assert.equal(layer.get('sample:S-01').root.parent, flip)
})

test('认领只针对自己恢复的板: L2 取起来但归属不到 run 的推断板不被账本领走', () => {
  const { binding, suction } = makeBinding()
  suction.held = true
  movePoint(binding, 'P19', 'run-手动')
  toolAction(binding, 'suction-on', 'run-手动')
  binding.update(0.016)
  assert.equal(binding.status().rows[0].recovered, false, '这块是包络取起来的, 不是恢复的')

  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)

  const rows = binding.status().rows
  assert.equal(rows.filter((r) => r.authority === 'L3').length, 1, '推断板原样留着')
  assert.equal(rows.find((r) => r.plateId === 'sample:S-01').slot, 'spot_seat')
})

test('真空位不插手 L2 正常取起来的板', () => {
  const { binding, layer, flip, suction } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }], 1))
  binding.update(0.016)
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)
  assert.equal(binding.plates.get('sample:S-01').recovered, false)

  suction.held = false
  binding.update(1.0)               // 远超宽限
  assert.equal(layer.get('sample:S-01').root.parent, flip, '不是它恢复的板, 真空位无权收掉')
})

// ── L1 覆盖面: "缺"与"空"的分界 ──────────────────────────────────────────────
//
// 仿真沙盒不装调度器, 缸里有哪块板它真不知道。把"不知道"当成"没有"会让板在缸里
// 凭空蒸发。下面每条正面用例都配一条 live 护栏(无 coverage 时行为必须逐字不变)。

/** 一帧沙盒板位投影(带 coverage/identity, 且样品没有 jobs)。 */
function simSnapshot(seats, revision = 1) {
  return {
    revision,
    source: 'sandbox-projection/v1',
    identity: 'synthetic',
    coverage: { slots: ['spot_seat', 'scrape_table', 'feedlift', 'waste'], uncovered: [] },
    batches: [{
      batch_id: 'sandbox',
      status: 'RUNNING',
      samples: seats.map((seat, i) => ({
        sample_id: `sim:seat:${seat}`, seq: i + 1, status: 'PRESENT',
        position: seat, tank: null, synthetic: true, jobs: [],
      })),
    }],
  }
}

test('覆盖外的落点: 板留着不回收, 并计入 uncoveredHeld', () => {
  const { binding, layer, suction } = makeBinding()
  binding.pushLedger(simSnapshot(['spot_seat']))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 1, '座上应有一块 L1 板')

  // 取走 -> 送进 3 号缸 (L2 包络)
  suction.held = true
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  movePoint(binding, 'P13')
  toolAction(binding, 'suction-off')
  suction.held = false
  binding.update(0.016)

  // 座位账已空 (沙盒的 seat_occupancy 是人工账, 流程不自动写), 板此刻在 tank:3
  binding.pushLedger(simSnapshot([], 2))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 1, '板在 L1 覆盖外的缸里, 不该被回收')
  assert.equal(binding.status().uncoveredHeld, 1)
})

test('live 护栏: 无 coverage 时同一序列里板照常被回收', () => {
  const { binding, layer, suction } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat' }]))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 1)

  suction.held = true
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  movePoint(binding, 'P13')
  toolAction(binding, 'suction-off')
  suction.held = false
  binding.update(0.016)

  binding.pushLedger(ledgerSnapshot([], 2))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 0, '调度器快照没有 coverage -> 回收规则逐字不变')
  assert.equal(binding.status().uncoveredHeld, 0)
})

test('合成身份 + 座上恰好一块: L2 取板归属到那块 L1 板, 不长第二块', () => {
  const { binding, layer, suction } = makeBinding()
  binding.pushLedger(simSnapshot(['spot_seat']))
  binding.update(0.016)

  suction.held = true
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)

  const ids = layer.plateIds()
  assert.equal(ids.length, 1, '不该在座上那块之外再长一块 inferred 板')
  assert.equal(ids[0], 'sample:sim:seat:spot_seat')
  const row = binding.status().rows.find((r) => r.plateId === ids[0])
  assert.equal(row.slot, 'carried')
})

test('合成身份但座上两块: 退回 L3 推断板, 一个字都不硬挑', () => {
  const { binding, layer, suction } = makeBinding()
  const frame = simSnapshot(['spot_seat'])
  frame.batches[0].samples.push({
    sample_id: 'sim:seat:dup', seq: 2, status: 'PRESENT',
    position: 'spot_seat', tank: null, synthetic: true, jobs: [],
  })
  binding.pushLedger(frame)
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 2, '停放位冲突要两块都画')

  suction.held = true
  movePoint(binding, 'P19')
  toolAction(binding, 'suction-on')
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 3, '归属不明时另起一块 L3 推断板')
  const inferred = binding.status().rows.filter((r) => r.authority === 'L3')
  assert.equal(inferred.length, 1)
})

test('live 护栏: 非合成身份 + 无 run 归属时仍建 L3 推断板(不按落点认领)', () => {
  const { binding, layer, suction } = makeBinding()
  binding.pushLedger(ledgerSnapshot([{ id: 'S-01', position: 'spot_seat', run: 'run-known' }]))
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 1)

  // 用一个账本不认识的 run_id 直跑: live 语义是"确实无归属", 不该顺手认领座上那块
  suction.held = true
  movePoint(binding, 'P19', 'run-manual')
  toolAction(binding, 'suction-on', 'run-manual')
  binding.update(0.016)
  assert.equal(layer.plateIds().length, 2, 'live 必须另起一块 L3, 不按落点认领')
})
