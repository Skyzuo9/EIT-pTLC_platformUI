/**
 * 功能: 吸盘柔性接触的测试 —— 纯代数 + 一次真场景射线求解.
 *
 * 锁住的核心不变量:
 *   1. 板悬空时零压缩, 位姿逐位等于刚性钉在唇口那一版(关掉开关的回归护栏);
 *   2. 板顶到硬表面时**板停在表面上**, 让开的是吸盘 —— 这正是用户 2026-08-05 指出的
 *      "刚性钉死只是把穿模从吸盘搬到了展缸面";
 *   3. 需要的压缩超过行程时**不被吸收**: 板照样停在表面, 吸盘压到上限就停, 于是露出缝。
 *      把"这个示教点太深"显出来, 而不是让吸盘无限压缩把错误藏掉。
 *   4. 每帧从自由位姿重算, 连续多帧不累乘(累乘的表现是板一路往回缩, 且拖进度条会漂)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import {
  PlateContact,
  compressionOf,
  lipSupportedFraction,
  plateRestCompression,
  rubberScale,
} from '../../src/three-d/twin/scene/plates/plateContact.js'
import {
  plateFaceLocalY,
  standardPlateGeom,
  suctionMountLocal,
} from '../../src/three-d/twin/scene/plates/plateGeometry.js'

const STROKE_M = 0.006
const RUBBER_LEN_M = 0.035
/** 射线求解走顶点/矩阵, 微米级容差; 纯代数另按逐位比。 */
const TOL_M = 1e-6

const GRIP = {
  axisLocal: [0, -1, 0],
  contactLocalM: [0, -0.07157172, -0.16254141],
  spanAxisLocal: [0, 0, -1],
  cupCount: 2,
  cupDiameterM: 0.024,
  cupSpanM: 0.085,
  strokeM: STROKE_M,
  rubbers: [{
    node: 'RUBBER_1',
    scaleAxis: 1,
    freeLenM: RUBBER_LEN_M,
    mountOffsetParent: [0, 0.02857136, 0],
  }],
}

// ── 纯代数 ─────────────────────────────────────────────────────────────────

test('compressionOf: 行程内全吸收, 超出部分不吸收(留给"露缝")', () => {
  assert.deepEqual(compressionOf(0, STROKE_M), { compressionM: 0, overshootM: 0 })
  assert.deepEqual(compressionOf(0.003, STROKE_M), { compressionM: 0.003, overshootM: 0 })
  assert.deepEqual(compressionOf(STROKE_M, STROKE_M), { compressionM: STROKE_M, overshootM: 0 })
  const over = compressionOf(0.009, STROKE_M)
  assert.ok(Math.abs(over.compressionM - STROKE_M) < 1e-12, '压缩必须封顶在行程')
  assert.ok(Math.abs(over.overshootM - 0.003) < 1e-12, '超出的 3mm 要如实报出来')
})

test('compressionOf: 负穿透与非有限值一律当作没接触(不许倒着把板拉出来)', () => {
  assert.deepEqual(compressionOf(-0.005, STROKE_M), { compressionM: 0, overshootM: 0 })
  assert.deepEqual(compressionOf(Number.NaN, STROKE_M), { compressionM: 0, overshootM: 0 })
})

test('rubberScale: 压缩 c 时比例正好让唇口回缩 c', () => {
  assert.equal(rubberScale(RUBBER_LEN_M, 0), 1)
  assert.ok(Math.abs(rubberScale(RUBBER_LEN_M, 0.0035) - 0.9) < 1e-12)
  assert.equal(rubberScale(RUBBER_LEN_M, RUBBER_LEN_M * 2), 0, '压过头夹到 0, 不给负长度')
  assert.equal(rubberScale(0, 0.003), 1, '自由长度为 0 时退化为不缩放, 不产生 NaN')
})

test('plateFaceLocalY: 远端面永远比接触面更靠 +axis 一整个板厚', () => {
  for (const silicaUp of [true, false]) {
    const geom = { ...standardPlateGeom(), silicaUp }
    const { contactY, farY, totalM } = plateFaceLocalY(geom)
    assert.ok(Math.abs(Math.abs(farY - contactY) - totalM) < 1e-12, '两面相距一个板厚')
    // 板局部 +Y 映到 axis×(silicaUp?1:-1); 远端面在 +axis 一侧 => 这个乘积必须为正
    assert.ok((farY - contactY) * (silicaUp ? 1 : -1) > 0, '远端面站错边了')
  }
})

// ── 真场景射线求解 ─────────────────────────────────────────────────────────

/**
 * 板远端面在测试场景里的世界 y(吸盘节点在原点且无旋转)。
 * **由代数现算而不是抄一个圆整过的常量** —— 手抄 −0.07457 会差 1.72µm,
 * 于是"穿透 3mm"的用例实际造出 3.0017mm, 断言按微米比就假红(2026-08-05 踩过)。
 */
function farFaceWorldY(silicaUp = false) {
  const geom = { ...standardPlateGeom(), silicaUp }
  const mount = suctionMountLocal(GRIP, geom)
  const { farY } = plateFaceLocalY(geom)
  return new THREE.Vector3(0, farY, 0).applyQuaternion(mount.quaternion).add(mount.position).y
}

const FAR_FACE_Y = farFaceWorldY()

/**
 * 造一个最小场景: 吸盘节点(带一只橡胶网格) + 一块可碰的地板盒。
 * `floorTopY` 给地板上表面的世界 y; 它比板远端面(FAR_FACE_Y)高多少, 穿透就是多少。
 */
function makeScene({ floorTopY }) {
  const root = new THREE.Group()

  const tool = new THREE.Group()
  tool.name = 'TOOL_SUCTION'
  root.add(tool)
  const suction = new THREE.Group()
  suction.name = 'ACTUATOR_FLIP_SUCTION'
  tool.add(suction)
  const rubber = new THREE.Mesh(new THREE.BoxGeometry(0.024, RUBBER_LEN_M, 0.024),
    new THREE.MeshBasicMaterial())
  rubber.name = 'RUBBER_1'
  suction.add(rubber)

  const floor = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.1, 0.5), new THREE.MeshBasicMaterial())
  floor.name = 'FLOOR'
  floor.position.set(0, floorTopY - 0.05, -0.16254141)
  root.add(floor)

  root.updateMatrixWorld(true)

  const nodeIndex = new Map([['RUBBER_1', rubber], ['TOOL_SUCTION', tool]])
  const manifest = { robot: {}, tools: [{ glbNode: 'TOOL_SUCTION' }] }
  const contact = new PlateContact({ manifest, nodeIndex, root, grip: GRIP })
  return { root, suction, rubber, floor, contact }
}

/** 把一块标准板按自由位姿挂到吸盘下(= suctionMountLocal 的结果)。 */
function mountPlate(suction, silicaUp = false) {
  const geom = { ...standardPlateGeom(), silicaUp }
  const plate = new THREE.Group()
  plate.name = 'PLATE_test'
  suction.add(plate)
  const mount = suctionMountLocal(GRIP, geom)
  plate.position.copy(mount.position)
  plate.quaternion.copy(mount.quaternion)
  plate.updateMatrixWorld(true)
  return { plate, geom, freePosition: mount.position.clone() }
}

test('悬空: 零穿透零压缩, 板停在自由位姿上(= 关掉开关那一版的行为)', () => {
  const { suction, rubber, contact } = makeScene({ floorTopY: -0.5 })
  const { plate, geom, freePosition } = mountPlate(suction)

  const result = contact.resolve(plate, geom, 1.0)
  assert.equal(result.penetrationM, 0)
  assert.equal(result.compressionM, 0)
  assert.ok(plate.position.distanceTo(freePosition) < 1e-12, '悬空时不许动板')
  assert.ok(Math.abs(rubber.scale.y - 1) < 1e-12, '悬空时吸盘不许被压扁')
})

test('顶到硬表面: 板停在表面上, 让开的是吸盘', () => {
  const penetration = 0.003
  const { suction, rubber, contact } = makeScene({ floorTopY: FAR_FACE_Y + penetration })
  const { plate, geom, freePosition } = mountPlate(suction)

  const result = contact.resolve(plate, geom, 1.0)
  assert.ok(Math.abs(result.penetrationM - penetration) < TOL_M,
    `穿透实测 ${result.penetrationM}, 期望 ${penetration}`)
  assert.ok(Math.abs(result.compressionM - penetration) < TOL_M, '行程内应当全部由吸盘吸收')
  assert.equal(result.overshootM, 0)
  // 板沿 −axis(=+y) 退回整个穿透量
  assert.ok(Math.abs(plate.position.y - (freePosition.y + penetration)) < TOL_M,
    '板没有停在表面上')
  assert.ok(Math.abs(rubber.scale.y - (RUBBER_LEN_M - penetration) / RUBBER_LEN_M) < TOL_M,
    '吸盘没有按压缩量缩短')
})

test('超行程: 板照样停在表面, 吸盘压到上限就停 —— 于是露出缝并报出超量', () => {
  const penetration = 0.009
  const { suction, rubber, contact } = makeScene({ floorTopY: FAR_FACE_Y + penetration })
  const { plate, geom, freePosition } = mountPlate(suction)

  const result = contact.resolve(plate, geom, 1.0)
  assert.ok(Math.abs(result.penetrationM - penetration) < TOL_M)
  assert.ok(Math.abs(result.compressionM - STROKE_M) < TOL_M, '压缩必须封顶在行程')
  assert.ok(Math.abs(result.overshootM - (penetration - STROKE_M)) < TOL_M,
    '超出的量要如实报出来, 不许悄悄吸收')
  assert.ok(Math.abs(plate.position.y - (freePosition.y + penetration)) < TOL_M,
    '超行程时板仍不许扎进表面')
  assert.ok(Math.abs(rubber.scale.y - (RUBBER_LEN_M - STROKE_M) / RUBBER_LEN_M) < TOL_M)
})

test('连续多帧不累乘 —— 每帧都从自由位姿重算(拖进度条不漂的前提)', () => {
  const penetration = 0.003
  const { suction, rubber, contact } = makeScene({ floorTopY: FAR_FACE_Y + penetration })
  const { plate, geom, freePosition } = mountPlate(suction)

  let previous = null
  for (let frame = 0; frame < 5; frame += 1) {
    // 调用方每帧先回自由位姿(PlateStage.update / PlateBinding._resolveContact 就是这么做的)
    plate.position.copy(freePosition)
    plate.updateMatrixWorld(true)
    const result = contact.resolve(plate, geom, 1.0)
    if (previous) {
      assert.ok(Math.abs(result.penetrationM - previous) < 1e-12,
        `第 ${frame} 帧穿透量漂了: ${previous} -> ${result.penetrationM}`)
    }
    previous = result.penetrationM
  }
  assert.ok(Math.abs(rubber.scale.y - (RUBBER_LEN_M - penetration) / RUBBER_LEN_M) < TOL_M)
})

test('releaseCups 把吸盘还原 —— 驱动层的 home() 管不到这些孙节点', () => {
  const { suction, rubber, contact } = makeScene({ floorTopY: FAR_FACE_Y + 0.004 })
  const { plate, geom } = mountPlate(suction)
  contact.resolve(plate, geom, 1.0)
  assert.ok(rubber.scale.y < 0.99, '前置条件: 这时吸盘应当是被压扁的')

  contact.releaseCups()
  assert.ok(Math.abs(rubber.scale.y - 1) < 1e-12, '复位后吸盘必须回到自由长度')
  assert.ok(Math.abs(rubber.position.y) < 1e-12, '补偿平移也要一并还原')
})

// ── 持板压缩(2026-08-05 回归护栏) ─────────────────────────────────────────
//
// 板骑的是**压缩后**的唇口(见 suctionMountLocal), 所以杯子也必须照那个量画。
// 只按"本次穿透"写杯子, 杯子就会以自由长度戳穿板面 17.8mm —— 板与杯必须同帧、
// 由同一个量分发, 与本文件头注释那条纪律是同一条。

const CARRY_M = 0.01782
const GRIP_CARRY = { ...GRIP, carryCompressionM: CARRY_M }

/** 与 makeScene 同构, 但用带持板压缩的 grip。 */
function makeCarryScene({ floorTopY }) {
  const scene = makeScene({ floorTopY })
  const contact = new PlateContact({
    manifest: { robot: {}, tools: [{ glbNode: 'TOOL_SUCTION' }] },
    nodeIndex: new Map([['RUBBER_1', scene.rubber], ['TOOL_SUCTION', scene.root.children[0]]]),
    root: scene.root,
    grip: GRIP_CARRY,
  })
  return { ...scene, contact }
}

/** 把板按**压缩后**的自由位姿挂上(= 新版 suctionMountLocal 的结果)。 */
function mountCarried(suction, silicaUp = false) {
  const geom = { ...standardPlateGeom(), silicaUp }
  const plate = new THREE.Group()
  plate.name = 'PLATE_carry'
  suction.add(plate)
  const mount = suctionMountLocal(GRIP_CARRY, geom)
  plate.position.copy(mount.position)
  plate.quaternion.copy(mount.quaternion)
  plate.updateMatrixWorld(true)
  return { plate, geom }
}

test('持板悬空: 杯子已按持板压缩画, 而不是自由长度(否则戳穿板面)', () => {
  const { suction, rubber, contact } = makeCarryScene({ floorTopY: -0.5 })
  const { plate, geom } = mountCarried(suction)

  const result = contact.resolve(plate, geom, 1.0)
  assert.equal(result.penetrationM, 0, '悬空不该有穿透')
  assert.equal(result.compressionM, 0, 'compressionM 只记本次再让的量, 不含持板基线')
  assert.ok(Math.abs(rubber.scale.y - rubberScale(RUBBER_LEN_M, CARRY_M)) < TOL_M,
    `杯子应当被画成压缩 ${CARRY_M}m, 实际 scale.y=${rubber.scale.y}`)
})

test('持板再顶到硬面: 压缩 = 持板基线 + 本次穿透, 不是二选一', () => {
  const penetration = 0.004
  // 板已按压缩唇口摆好, 远端面比自由态高了 CARRY_M, 地板要跟着抬
  const { suction, rubber, contact } = makeCarryScene({
    floorTopY: FAR_FACE_Y + CARRY_M + penetration,
  })
  const { plate, geom } = mountCarried(suction)

  const result = contact.resolve(plate, geom, 1.0)
  assert.ok(Math.abs(result.penetrationM - penetration) < TOL_M,
    `穿透应为 ${penetration}, 实为 ${result.penetrationM}`)
  assert.ok(Math.abs(rubber.scale.y - rubberScale(RUBBER_LEN_M, CARRY_M + penetration)) < TOL_M,
    '杯子必须按 持板压缩 + 穿透 的总量画')
})

test('手上没板才回自由长度; 有板但本层不可用时仍停在持板压缩态', () => {
  const { suction, rubber, contact } = makeCarryScene({ floorTopY: -0.5 })
  const { plate, geom } = mountCarried(suction)

  // 有板 + 本层不可用(掏空可碰几何): 杯子不许弹回自由长度
  contact._collidables = []
  contact.resolve(plate, geom, 1.0)
  assert.ok(Math.abs(rubber.scale.y - rubberScale(RUBBER_LEN_M, CARRY_M)) < TOL_M,
    '手上有板却把杯子放回自由长度, 会当场戳穿板面')

  // 手上没板: 回自由长度
  contact.resolve(null, geom, 1.0)
  assert.ok(Math.abs(rubber.scale.y - 1) < 1e-12, '没板时杯子必须回自由长度')
})

// ── 唇口代数(2026-08-06 回归护栏) ─────────────────────────────────────────
//
// 上面那条 `rubberScale: 压缩 c 时比例正好让唇口回缩 c` **名不副实**: 它只验了比例值
// (free−c)/free, 根本没算唇口落在哪。于是 mountOffsetParent 的**符号写反**时它照样绿 ——
// 2026-08-05 shipped manifest 里那个 +28.571mm(应为 −17.5mm)就是这么活下来的,
// 表现是持板时两只吸盘杯从板面里穿出来 33mm。
//
// ⚠ 夹具必须带上**真实的父链朝向**。橡胶段的父节点 SAB22-KQ2E06-N 相对翻转节点带一个
//   180° 旋转(实测四元数见下), 于是**杯局部 +Y 映射到 +吸盘轴(朝外)** —— 正号的
//   mountOffset 是把杯子往外推而不是往回缩。拿一个 identity 朝向的夹具去测, 符号错会
//   被朝向差抵消掉, 测了等于没测(与 actionSim.test.js 头注释记的"照 YAML 写夹具"同款坑)。
const CUP_QUAT = [-0.907898, 0, -0.419191, 0]   // 实测 SAB22-KQ2E06-1 局部四元数(xyzw)
const RUBBER_HALF_M = RUBBER_LEN_M / 2
/** 自由态唇口沿吸盘轴的位置(翻转局部, 米) —— 与下面夹具的几何自洽 */
const LIP_ALONG_M = RUBBER_LEN_M

/**
 * 造真实父链: 翻转节点 → 吸盘总成(带 180° 翻转) → 橡胶段。
 *
 * 几何自洽: 橡胶盒心在翻转系沿轴 +17.5mm, 盒半长 17.5mm ⇒ 自由态唇口在 +35mm,
 * 于是 contactLocalM 必须就是那个点(axisLocal=[0,−1,0] ⇒ 翻转系 y = −35mm)。
 *
 * @param {number[]} mountOffsetParent manifest 里那个值 —— 只在**取不到翻转节点**时才被用到
 * @param {boolean} withActuator 是否把机构放进 manifest/nodeIndex(即走运行期实测那条路)
 */
function makeCupChain(mountOffsetParent, withActuator = true) {
  const suction = new THREE.Group()
  suction.name = 'ACTUATOR_FLIP_SUCTION'
  const cup = new THREE.Group()
  cup.name = 'SAB22-KQ2E06-1'
  cup.quaternion.fromArray(CUP_QUAT).normalize()
  suction.add(cup)
  const rubber = new THREE.Mesh(new THREE.BoxGeometry(0.024, RUBBER_LEN_M, 0.024),
    new THREE.MeshBasicMaterial())
  rubber.name = 'RUBBER_1'
  // 盒心距原点半个自由长 ⇒ 自由态唇口正好在 +35mm 处(杯局部 +Y = +吸盘轴)
  rubber.position.set(0, RUBBER_HALF_M, 0)
  cup.add(rubber)
  suction.updateMatrixWorld(true)

  const grip = {
    ...GRIP,
    contactLocalM: [0, -LIP_ALONG_M, 0],
    rubbers: [{
      node: 'RUBBER_1', scaleAxis: 1, freeLenM: RUBBER_LEN_M,
      mountOffsetParent,
    }],
  }
  const nodeIndex = new Map([['RUBBER_1', rubber]])
  const manifest = { robot: {}, tools: [] }
  if (withActuator) {
    nodeIndex.set('ACTUATOR_FLIP_SUCTION', suction)
    manifest.actuators = [{ id: 'rob_flip_suction', node: 'ACTUATOR_FLIP_SUCTION', plateGrip: grip }]
  }
  const contact = new PlateContact({ manifest, nodeIndex, root: suction, grip })
  return { suction, rubber, contact }
}

/** 唇口(沿吸盘轴伸得最远的那一端)在**翻转节点局部系**里的位置, mm。 */
function lipAlongMm(suction, rubber) {
  suction.updateMatrixWorld(true)
  const axis = new THREE.Vector3().fromArray(GRIP.axisLocal).normalize()
  const toSuction = new THREE.Matrix4().copy(suction.matrixWorld).invert()
  const ends = [RUBBER_HALF_M, -RUBBER_HALF_M].map((y) => new THREE.Vector3(0, y, 0)
    .applyMatrix4(rubber.matrixWorld).applyMatrix4(toSuction).dot(axis) * 1000)
  return Math.max(...ends)
}

test('唇口代数: 压缩 c 时唇口正好回缩 c —— 且不理会 manifest 里那个错值', () => {
  // 故意喂 shipped manifest 里那个**错值**(+28.571mm, 是拿 work/machine.full.glb 算的,
  // 用在压缩版 GLB 上会把杯子往外推)。运行期实测那条路必须把它盖掉。
  const { suction, rubber, contact } = makeCupChain([0, 0.02857136, 0])
  contact._writeCups(0)
  const free = lipAlongMm(suction, rubber)
  assert.ok(Math.abs(free - LIP_ALONG_M * 1000) < 1e-9,
    `自由态唇口应在 ${LIP_ALONG_M * 1000}mm, 实为 ${free}`)

  for (const c of [0, 0.003, 0.006, 0.01782, 0.02382]) {
    contact._writeCups(c)
    const lip = lipAlongMm(suction, rubber)
    assert.ok(Math.abs((free - lip) - c * 1000) < 1e-6,
      `压缩 ${c * 1000}mm 时唇口该回缩同样多, 实际回缩 ${(free - lip).toFixed(3)}mm`)
  }
})

test('唇口代数: 取不到翻转节点时退回 manifest 值 —— 那条路好坏全看 manifest', () => {
  // 这条不是"期望的行为", 而是把**退化路径的代价**钉下来: manifest 的
  // mountOffsetParent 是按 work/machine.full.glb 的节点原点算的, 拿到压缩版 GLB 上
  // 就是错的(杯子往外跑, 从板面里穿出去 —— 用户 2026-08-05/06 连报两次)。
  // 所以运行期实测那条路必须始终可用; 真掉进这条退回路径, 表现就是下面这样。
  const { suction, rubber, contact } = makeCupChain([0, 0.02857136, 0], false)
  contact._writeCups(0)
  const free = lipAlongMm(suction, rubber)
  contact._writeCups(0.01782)
  const lip = lipAlongMm(suction, rubber)
  assert.ok(lip > free,
    '前提: 这个错值本该让唇口反而伸出去 —— 若它不再伸出, 说明夹具朝向失真了')
  assert.ok(Math.abs((free - lip) - 17.82) > 1,
    '退回路径确实给不出"回缩 17.82mm", 这正是不能依赖它的理由')
})

// ── 断吸后的渐进回弹(2026-08-06) ──────────────────────────────────────────
//
// 用户报: 放板那一瞬间吸盘立刻弹回自由长, 当场穿过刚放下的板。物理上断吸只是没了吸力,
// 波纹段仍被板面顶着, 该等机械臂抬到唇口脱离才逐渐长回去。
//
// 实现是**纯几何**的: 压缩量 = 自由唇口越过板贴合面的深度 × 唇口压在板上的比例。
// 于是放板那一刻深度恰好 = carryCompression(与持板态无缝), 抬起时单调归零。

test('lipSupportedFraction: 盘心在板内一个半径=1, 出板外一个半径=0, 中间线性', () => {
  const r = 0.012
  assert.equal(lipSupportedFraction(-r, -r, r), 1, '两轴都深在板内')
  assert.equal(lipSupportedFraction(r, -r, r), 0, 'X 已完全滑出')
  assert.equal(lipSupportedFraction(-r, r, r), 0, 'Z 已完全滑出')
  // 盘心正好压在板边缘 => 每轴各一半
  assert.ok(Math.abs(lipSupportedFraction(0, -r, r) - 0.5) < 1e-12)
  assert.ok(Math.abs(lipSupportedFraction(0, 0, r) - 0.25) < 1e-12, '两轴各半 => 0.25')
  // 单调: 越往外越小
  let prev = 1
  for (let off = -r; off <= r; off += r / 8) {
    const value = lipSupportedFraction(off, -r, r)
    assert.ok(value <= prev + 1e-12, `滑出过程必须单调不增, off=${off}`)
    prev = value
  }
  assert.equal(lipSupportedFraction(-r, -r, 0), 1, '半径缺失时退化成阶跃(盘心在内)')
  assert.equal(lipSupportedFraction(0.001, -r, 0), 0, '半径缺失时退化成阶跃(盘心在外)')
})

test('plateRestCompression: 负穿透=0, 封顶在上限, 按支撑比例缩放', () => {
  assert.equal(plateRestCompression(-0.005, 1, 0.024), 0, '唇口还没碰到板')
  assert.equal(plateRestCompression(0.01, 1, 0.024), 0.01)
  assert.equal(plateRestCompression(0.03, 1, 0.024), 0.024, '超过上限要封顶')
  assert.ok(Math.abs(plateRestCompression(0.01, 0.5, 0.024) - 0.005) < 1e-12)
  assert.equal(plateRestCompression(0.01, 0, 0.024), 0, '完全滑出板外 => 自由长')
  assert.equal(plateRestCompression(Number.NaN, 1, 0.024), 0)
})

/** 造"翻转节点 + 一块已落座的板", 板面法线朝上, 唇口自上而下压它。 */
function makeSeatedScene() {
  const root = new THREE.Group()
  const suction = new THREE.Group()
  suction.name = 'ACTUATOR_FLIP_SUCTION'
  root.add(suction)
  const rubber = new THREE.Mesh(new THREE.BoxGeometry(0.024, RUBBER_LEN_M, 0.024),
    new THREE.MeshBasicMaterial())
  rubber.name = 'RUBBER_1'
  suction.add(rubber)

  // 落座的板: 用标准 geom(200×3×200), 摆在世界原点, 板面法线 = 局部 +Y
  const geom = { ...standardPlateGeom(), silicaUp: false }
  const plate = new THREE.Group()
  plate.name = 'PLATE_seated'
  root.add(plate)
  root.updateMatrixWorld(true)

  const grip = { ...GRIP, carryCompressionM: CARRY_M }
  const contact = new PlateContact({
    manifest: {
      robot: {}, tools: [],
      actuators: [{ id: 'rob_flip_suction', node: 'ACTUATOR_FLIP_SUCTION', plateGrip: grip }],
    },
    nodeIndex: new Map([['RUBBER_1', rubber], ['ACTUATOR_FLIP_SUCTION', suction]]),
    root,
    grip,
  })
  return { root, suction, rubber, plate, geom, contact }
}

/**
 * 把吸盘摆到"自由唇口距板贴合面 gap 米"的位置(gap<0 = 唇口越过板面)。
 *
 * ⚠ contactLocalM 不只有 y: 它的 z = −162.54mm 是**两只吸盘的对中心**。不把这一项
 * 补偿掉, 唇口会落在板(200×200)的轮廓外, supported 恒为 0 —— 首版夹具就是这么写的,
 * 于是"压着板"的用例全部读到 0 压缩, 看着像生产代码坏了, 其实是夹具没对准。
 */
const LIP_LOCAL = GRIP.contactLocalM

function placeSuction(scene, gapM, xOffsetM = 0) {
  const { contactY } = plateFaceLocalY(scene.geom, 1.0)
  const lipY = contactY + gapM                      // 板局部(= 世界)里唇口该在的 y
  scene.suction.position.set(
    xOffsetM - LIP_LOCAL[0],
    lipY - LIP_LOCAL[1],
    -LIP_LOCAL[2],
  )
  scene.suction.updateMatrixWorld(true)
}

test('断吸后: 唇口任一帧都不越过板面, 且随抬起单调归零(用户要的硬限制)', () => {
  const scene = makeSeatedScene()
  const { contactY } = plateFaceLocalY(scene.geom, 1.0)
  let prev = Infinity
  // 从"唇口扎进板面 CARRY_M"一路抬到脱离
  for (let gap = -CARRY_M; gap <= CARRY_M; gap += CARRY_M / 12) {
    placeSuction(scene, gap)
    const state = scene.contact.relaxOnPlates([{ root: scene.plate, geom: scene.geom }], 1.0)
    const compression = state?.compressionM ?? 0
    assert.ok(compression <= prev + 1e-12,
      `抬起过程压缩量必须单调不增: gap=${gap.toFixed(5)} ${compression} > ${prev}`)
    prev = compression
    // 硬限制: 压缩后的实际唇口不许低于板贴合面(板心正上方 ⇒ supported=1, 压缩=穿透)
    const lipY = scene.suction.position.y + LIP_LOCAL[1] + compression
    assert.ok(lipY >= contactY - 1e-9,
      `唇口越过板面了: lipY=${lipY.toFixed(6)} < contactY=${contactY.toFixed(6)}`)
  }
  assert.equal(prev, 0, '抬够之后必须回到自由长')
})

test('断吸那一刻与持板态无缝: 压缩量正好等于 carryCompression, 不跳变', () => {
  const scene = makeSeatedScene()
  // 放板那一刻: 板面就贴在**压缩后**的唇口上 => 自由唇口越过板面正好 CARRY_M
  placeSuction(scene, -CARRY_M)
  const state = scene.contact.relaxOnPlates([{ root: scene.plate, geom: scene.geom }], 1.0)
  assert.ok(Math.abs(state.compressionM - CARRY_M) < 1e-9,
    `放板瞬间该是 ${CARRY_M}, 实为 ${state?.compressionM}`)
})

test('横向滑出板边: 按吸盘直径渐变长回去, 不是到边缘就跳', () => {
  const scene = makeSeatedScene()
  placeSuction(scene, -CARRY_M)
  const half = scene.geom.widthM / 2
  const radius = GRIP.cupDiameterM / 2
  const at = (x) => {
    placeSuction(scene, -CARRY_M, x)
    return scene.contact.relaxOnPlates([{ root: scene.plate, geom: scene.geom }], 1.0).compressionM
  }
  const inside = at(0)
  const edge = at(half)
  const outside = at(half + radius + 1e-4)
  assert.ok(Math.abs(inside - CARRY_M) < 1e-9, '板中心: 全压着')
  assert.ok(edge > 0 && edge < inside, `盘心压在板边时该是中间值, 实为 ${edge}`)
  assert.ok(Math.abs(outside) < 1e-12, '完全滑出后必须回到自由长')
})

test('从板下方掠过不算压着它(否则吸盘会莫名压扁)', () => {
  const scene = makeSeatedScene()
  placeSuction(scene, -RUBBER_LEN_M - 0.01)   // 唇口远在板面另一侧
  const state = scene.contact.relaxOnPlates([{ root: scene.plate, geom: scene.geom }], 1.0)
  assert.equal(state?.compressionM ?? 0, 0)
})

test('同一位姿调两次结果逐位相同(seek 可复现的前提)', () => {
  const scene = makeSeatedScene()
  placeSuction(scene, -CARRY_M / 2)
  const plates = [{ root: scene.plate, geom: scene.geom }]
  const a = scene.contact.relaxOnPlates(plates, 1.0).compressionM
  const scaleA = scene.rubber.scale.y
  const b = scene.contact.relaxOnPlates(plates, 1.0).compressionM
  assert.equal(a, b, '纯函数: 同输入同输出')
  assert.equal(scene.rubber.scale.y, scaleA, '写进场景的 scale 也不许漂')
})

test('没有任何落座的板时回自由长(不是维持上一次的压缩)', () => {
  const scene = makeSeatedScene()
  placeSuction(scene, -CARRY_M)
  scene.contact.relaxOnPlates([{ root: scene.plate, geom: scene.geom }], 1.0)
  assert.ok(scene.rubber.scale.y < 0.99, '前置条件: 这时该是压着的')
  scene.contact.relaxOnPlates([], 1.0)
  assert.ok(Math.abs(scene.rubber.scale.y - 1) < 1e-12, '场上没板了就该回自由长')
})

test('机器人与工具子树不参与碰撞(否则吸盘自己会把板顶开)', () => {
  const { contact } = makeScene({ floorTopY: -0.5 })
  const names = contact._collidables.map((mesh) => mesh.name)
  assert.ok(!names.includes('RUBBER_1'), '吸盘自己进了碰撞集')
  assert.ok(names.includes('FLOOR'), '真正该挡路的地板反而没进碰撞集')
})

test('manifest.plateContactIgnore 里的子树被排除(排除集从 manifest 派生, 不写死名字)', () => {
  // 2026-08-06: 点样座/刮板台把玻璃画成沉进放置平台 1.5mm, 取板时板本就嵌在料仓框架内 ——
  // 那几处的"扎进去"是建模约定/正常工况, 不排掉就每次经过闪一下缝。出处见 rig_map
  // 的 plate_contact 段。这里锁住"前端确实按 manifest 给的清单排"这个契约。
  const scene = makeScene({ floorTopY: -0.5 })
  const withIgnore = new PlateContact({
    manifest: {
      robot: {}, tools: [{ glbNode: 'TOOL_SUCTION' }],
      plateContactIgnore: ['FLOOR'],
    },
    nodeIndex: new Map([['RUBBER_1', scene.rubber], ['TOOL_SUCTION', scene.root.children[0]],
      ['FLOOR', scene.floor]]),
    root: scene.root,
    grip: GRIP,
  })
  assert.ok(!withIgnore._collidables.map((mesh) => mesh.name).includes('FLOOR'),
    'plateContactIgnore 点名的节点仍然留在碰撞集里')
  // 反证: 不给清单时它本该在 —— 否则这条测试是空的
  assert.ok(scene.contact._collidables.map((mesh) => mesh.name).includes('FLOOR'),
    '前提: 不排的时候地板本来就在碰撞集里')
})
