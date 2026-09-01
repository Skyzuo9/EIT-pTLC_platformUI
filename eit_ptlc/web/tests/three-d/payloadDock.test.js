/**
 * 功能: 载荷(托盘/单件耗材)被夹爪携带并落位的单测 —— 契约校验、落位补间、seek 确定性.
 *
 * 为什么值得单测: 载荷落位与工具吸附不同, 它的目标是**目的地座位**而不是"自己加载时
 * 的位姿" —— 一块托盘从货架搬到中转, 落位是中转位。这条一旦写错, 表现是托盘飞回货架
 * 或悬在半空, 而且因为终态最后会被账本快照/实例交换盖掉, 很容易被误判成"偶发闪烁"。
 *
 * 落位阈值(10mm)是实测定的: 工位摆位校正后, 24 条整板转移的"示教↔CAD 平移残差"实测
 * ≤7.9mm(校正前是 6~23mm), 阈值要包住它又不能松到漏掉坏数据。真正的硬门禁在编译期
 * (校正后几何落位残差 ≤ 0.5mm, 超差拒绝生成片段)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { ClipPlayer } from '../../src/three-d/anim/ClipPlayer.js'
import { compileClip, parseClip } from '../../src/three-d/anim/clipSchema.js'
import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'

/** 中转座位的世界 X; 托盘在货架上的世界 X 是 1。 */
const STAGING_X = 10
const DOCK = { position: [0, 0, 0], quaternion: [0, 0, 0, 1] }

/**
 * 功能: 造一个"货架托盘 + 中转位 + 地轨托架上的夹爪"的最小场景.
 *
 * 必须带地轨托架: 载荷要**真的被搬过去**, 落位残差才有意义。夹爪原地不动直接 dock,
 * 量出来的是货架到中转的 9 米整段距离, 测不到"到位残差"这件事。
 *
 * @returns {{driver, tray, mount, rack, staging, root, carryTo: (worldX: number) => void}}
 */
function makeScene() {
  const root = new THREE.Object3D()
  const carriage = new THREE.Object3D(); carriage.name = 'CARRIAGE'
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const rack = new THREE.Object3D(); rack.name = 'ST_RACK'
  const staging = new THREE.Object3D(); staging.name = 'ST_COLLECT'; staging.position.set(STAGING_X, 0, 0)
  const tray = new THREE.Object3D(); tray.name = 'INV_RACK_COLLECTOR_1'; tray.position.set(1, 0, 0)
  root.add(carriage, rack, staging); carriage.add(mount); rack.add(tray)
  root.updateMatrixWorld(true)

  const nodes = new Map([
    ['CARRIAGE', carriage], ['TOOL_MOUNT', mount], ['ST_RACK', rack], ['ST_COLLECT', staging],
    ['INV_RACK_COLLECTOR_1', tray],
  ])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [{
        id: 'axis_rail', glbNode: 'CARRIAGE', rigged: true, axis: [1, 0, 0],
        sign: 1, mmToUnit: 0.001, zeroOffsetMm: 0, rangeMm: [0, 20000],
      }],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [],
      attachments: [{ id: 'INV_RACK_COLLECTOR_1', node: 'INV_RACK_COLLECTOR_1' }],
    },
  })
  // 托盘夹在爪里时随托架走; carryTo 把托盘搬到指定世界 X(托盘在爪里的局部偏移是 1)。
  const carryTo = (worldX) => {
    carriage.position.set(worldX - 1, 0, 0)
    root.updateMatrixWorld(true)
  }
  return { driver, tray, mount, rack, staging, root, carryTo }
}

test('detach.dock 形状非法在编译期就拒绝', () => {
  const bad = (dock) => `
schema: ptlc.clip/v1
name: t.bad
steps:
  - { dur: 1, do: { detach: { id: P, parent: ST_COLLECT, dock: ${dock} } } }
`
  assert.throws(() => compileClip(parseClip(bad('{ position: [0,0], quaternion: [0,0,0,1] }'))), /dock/)
  assert.throws(() => compileClip(parseClip(bad('{ position: [0,0,0] }'))), /dock/)
  assert.throws(() => compileClip(parseClip(bad('{ position: [0,0,null], quaternion: [0,0,0,1] }'))), /非有限数/)
  assert.throws(
    () => compileClip(parseClip('schema: ptlc.clip/v1\nname: t\nsteps:\n  - { dur: 1, do: { attach: { parent: X } } }')),
    /缺 id/,
  )
  // attach 不接受 dock: 挂到夹爪上是"保世界变换换父", 没有落位目标可言。
  assert.throws(
    () => compileClip(parseClip(
      'schema: ptlc.clip/v1\nname: t\nsteps:\n'
      + '  - { dur: 1, do: { attach: { id: P, dock: { position: [0,0,0], quaternion: [0,0,0,1] } } } }',
    )),
    /只有 detach 支持 dock/,
  )
})

test('落位: 换父到目的座位并平滑吸附, 是 t 的纯函数', () => {
  const { driver, tray, mount, staging, carryTo } = makeScene()
  assert.equal(driver.attach('INV_RACK_COLLECTOR_1', mount), true)
  assert.equal(tray.parent, mount)
  // 搬到中转位上方: 松爪瞬间托盘世界位于 10.002, 目的座位在 10.000 —— 2mm 示教残差。
  carryTo(STAGING_X + 0.002)

  assert.equal(driver.dockPayload('INV_RACK_COLLECTOR_1', staging, DOCK, 5.0), true)
  assert.equal(tray.parent, staging, '落位必须换父到目的地, 而不是回它的加载父级')

  // 起点保持松爪瞬间的世界位姿(局部残差 2mm), 不跳变。
  driver.updateToolTween(5.0)
  assert.ok(Math.abs(tray.position.length() - 0.002) < 1e-9, '落位起点应保持松爪瞬间位姿')

  driver.updateToolTween(5.1)
  const midway = tray.position.length()
  assert.ok(midway > 0 && midway < 0.002, '落位过程应介于起点与座位之间')

  const snapshot = tray.position.clone()
  driver.updateToolTween(5.1)
  assert.ok(tray.position.distanceTo(snapshot) < 1e-12, '同一 t 必须复现同一位姿')

  driver.updateToolTween(5.3)
  assert.ok(tray.position.length() < 1e-12, '落位结束必须精确闭合到座位位姿')
  assert.equal(driver.payloadTweens.size, 0)
})

test('落位行程超阈值: 直接就位并告警, 不做拉扯补间', () => {
  const warnings = []
  const original = console.warn
  console.warn = (message) => warnings.push(String(message))
  try {
    // 50mm: 远超实测的示教↔CAD 残差(校正后最大 7.9mm), 属于坏数据 —— 必须直接就位并告警。
    const { driver, tray, mount, staging, carryTo } = makeScene()
    driver.attach('INV_RACK_COLLECTOR_1', mount)
    carryTo(STAGING_X + 0.05)
    driver.dockPayload('INV_RACK_COLLECTOR_1', staging, DOCK, 5.0)
    assert.ok(tray.position.length() < 1e-12, '超限行程直接精确就位, 终态仍然正确')
    assert.equal(driver.payloadTweens.size, 0, '超限行程不建立补间')
    assert.ok(warnings.some((line) => line.includes('超出落位阈值')), '超限必须留痕, 不能静默')
  } finally {
    console.warn = original
  }
})

test('不给 dock 的 detach 退化成纯换父, 不猜位置', () => {
  const { driver, tray, mount, staging, carryTo } = makeScene()
  driver.attach('INV_RACK_COLLECTOR_1', mount)
  carryTo(STAGING_X + 0.002)
  const worldBefore = tray.getWorldPosition(new THREE.Vector3())
  assert.equal(driver.dockPayload('INV_RACK_COLLECTOR_1', staging, null, 5.0), true)
  assert.equal(tray.parent, staging)
  assert.ok(tray.getWorldPosition(new THREE.Vector3()).distanceTo(worldBefore) < 1e-9)
  assert.equal(driver.payloadTweens.size, 0)
})

test('home() 清空落位补间并把载荷确定性复原到加载态', () => {
  const { driver, tray, mount, staging, rack, carryTo } = makeScene()
  driver.attach('INV_RACK_COLLECTOR_1', mount)
  carryTo(STAGING_X + 0.002)
  driver.dockPayload('INV_RACK_COLLECTOR_1', staging, DOCK, 5.0)
  assert.equal(driver.payloadTweens.size, 1)

  driver.home()
  assert.equal(driver.payloadTweens.size, 0, 'home 必须清空补间, 否则回放会被上一次的补间污染')
  assert.equal(tray.parent, rack, 'home 后载荷回到加载时的父级')
  assert.ok(tray.position.distanceTo(new THREE.Vector3(1, 0, 0)) < 1e-12)
})

test('工具吸附与载荷落位同帧并存, 互不顶掉', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'; mount.position.set(10.002, 0, 0)
  const dock = new THREE.Object3D(); dock.name = 'ST_TOOLING'
  const tool = new THREE.Object3D(); tool.name = 'TOOL_PLATE96'; tool.position.set(10, 0, 0)
  const staging = new THREE.Object3D(); staging.name = 'ST_COLLECT'; staging.position.set(10, 0, 0)
  const tray = new THREE.Object3D(); tray.name = 'TRAY'
  root.add(mount, dock, staging); dock.add(tool); mount.add(tray)
  root.updateMatrixWorld(true)

  const nodes = new Map([
    ['TOOL_MOUNT', mount], ['ST_TOOLING', dock], ['ST_COLLECT', staging],
    ['TOOL_PLATE96', tool], ['TRAY', tray],
  ])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [{ id: 'TOOL_PLATE96', glbNode: 'TOOL_PLATE96', dockNode: 'ST_TOOLING', mountPosition: [0, 0, 0], mountQuaternion: [0, 0, 0, 1] }],
      attachments: [{ id: 'TRAY', node: 'TRAY' }],
    },
  })

  driver.lockTool('TOOL_PLATE96', 2.0)
  driver.dockPayload('TRAY', staging, { position: [0, 0, 0], quaternion: [0, 0, 0, 1] }, 2.0)
  assert.ok(driver.toolTween, '工具补间应存在')
  assert.equal(driver.payloadTweens.size, 1, '载荷补间应独立存在, 不被工具补间顶掉')

  driver.updateToolTween(2.3)
  assert.ok(tool.position.length() < 1e-12, '工具补间已闭合')
  assert.ok(tray.position.length() < 1e-12, '载荷补间同样闭合')
  assert.equal(driver.toolTween, null)
  assert.equal(driver.payloadTweens.size, 0)
})

/**
 * 功能: 造"夹爪 + 单件瓶(带网格, 节点原点故意偏离几何)"的最小场景.
 *
 * 节点原点偏离是刻意的: INV_* 空节点的原点是任意的(实测离几何可达数百毫米), 磁吸必须
 * 以**几何中心**为抓取基准 —— 拿节点原点当基准正是这类缺陷的老病根。
 *
 * @param {number[]} seatPos 座位世界位置
 * @param {{grabLocal?: number[], freeAxes?: number[][], nodeScale?: number}} [extras]
 *   抓取锚点扩展字段; nodeScale 模拟 04 量化件(运行期 GLB 节点 scale≈0.0475)
 * @returns {{driver, vial, mount, seat, anchor: number[]}}
 */
function makeItemScene(seatPos, extras = {}) {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const seat = new THREE.Object3D(); seat.name = 'ST_SEAT'; seat.rotation.z = 0.3
  seat.position.set(...seatPos)
  const vial = new THREE.Object3D(); vial.name = 'INV_STAGING_B_ITEM_1'
  // 量化件的节点 scale 不是 1: 04_optimize 把几何缩进 int16 码值、补偿塞进节点 TRS。
  // 缺省 1 是拟合帧的样子; 传 nodeScale 才是运行期那份 GLB 的样子。
  if (extras.nodeScale) vial.scale.setScalar(extras.nodeScale)
  const meshScale = extras.nodeScale ? 1 / extras.nodeScale : 1
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(
    0.02 * meshScale, 0.09 * meshScale, 0.02 * meshScale))
  mesh.position.set(0, 0.05 * meshScale, 0) // 几何中心在节点局部 (0, 0.05, 0)/scale, 原点不在几何上
  vial.add(mesh)
  root.add(mount, seat); seat.add(vial)
  root.updateMatrixWorld(true)
  const anchor = [0, 0, -0.12] // 四销笼中心(TOOL_MOUNT 系)
  const mountLocal = { position: anchor, quaternion: [0, 0, 0, 1] }
  if (extras.freeAxes) mountLocal.freeAxes = extras.freeAxes
  const payload = { kind: 'item', grip: 'rob_grip_vial', seat: 'hole:staging-b:1', mountLocal }
  if (extras.grabLocal) payload.grabLocal = extras.grabLocal
  const nodes = new Map([['TOOL_MOUNT', mount], ['ST_SEAT', seat], ['INV_STAGING_B_ITEM_1', vial]])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [],
      attachments: [{ id: 'INV_STAGING_B_ITEM_1', node: 'INV_STAGING_B_ITEM_1', payload }],
    },
  })
  return { driver, vial, mount, seat, anchor }
}

/** 物件几何中心的世界坐标(与实现同口径: Box3 中心)。 */
function itemWorldCenter(vial) {
  vial.updateMatrixWorld(true)
  return new THREE.Box3().setFromObject(vial).getCenter(new THREE.Vector3())
}

test('单件取件磁吸: 几何中心平移到四销笼锚点, 姿态保留, 是 t 的纯函数', () => {
  const { driver, vial, mount } = makeItemScene([0, -0.07, -0.1])
  const quatBefore = vial.getWorldQuaternion(new THREE.Quaternion())
  const centerBefore = itemWorldCenter(vial)

  assert.equal(driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0), true)
  assert.equal(vial.parent, mount, '磁吸不改变换父语义')
  assert.equal(driver.payloadTweens.size, 1, '给了 atTime 应建立位置补间')

  driver.updateToolTween(3.0)
  assert.ok(itemWorldCenter(vial).distanceTo(centerBefore) < 1e-9, '起点保持取件瞬间位姿')

  driver.updateToolTween(3.5)
  const anchorWorld = mount.localToWorld(new THREE.Vector3(0, 0, -0.12))
  assert.ok(itemWorldCenter(vial).distanceTo(anchorWorld) < 1e-9,
    '补间闭合后物件几何中心精确落在锚点')
  const quatAfter = vial.getWorldQuaternion(new THREE.Quaternion())
  assert.ok(1 - Math.abs(quatBefore.dot(quatAfter)) < 1e-12, '磁吸只平移, 不得转动物件')
  assert.equal(driver.payloadTweens.size, 0)
})

test('单件磁吸超阈值(>100mm): 直接就位到锚点并告警', () => {
  const warnings = []
  const original = console.warn
  console.warn = (message) => warnings.push(String(message))
  try {
    const { driver, vial, mount } = makeItemScene([0, 0.2, 0])
    driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0)
    assert.equal(driver.payloadTweens.size, 0, '超限不建立补间')
    const anchorWorld = mount.localToWorld(new THREE.Vector3(0, 0, -0.12))
    assert.ok(itemWorldCenter(vial).distanceTo(anchorWorld) < 1e-9,
      '锚点是夹爪几何的确定量, 超限也要就位到锚点(终态正确), 只是要留痕')
    assert.ok(warnings.some((line) => line.includes('取件吸附阈值')), '超限必须告警')
  } finally {
    console.warn = original
  }
})

test('不给 atTime 的单件 attach 保持纯换父(实时链语义不变)', () => {
  const { driver, vial, mount } = makeItemScene([0, -0.07, -0.1])
  const centerBefore = itemWorldCenter(vial)
  assert.equal(driver.attach('INV_STAGING_B_ITEM_1', mount), true)
  assert.equal(vial.parent, mount)
  assert.equal(driver.payloadTweens.size, 0)
  assert.ok(itemWorldCenter(vial).distanceTo(centerBefore) < 1e-9, '保世界变换, 不磁吸')
})

test('单件磁吸: 有 payload.grabLocal 时以抓取特征点(瓶颈)为基准, 不再用 Box3 中心', () => {
  // 特征点 = 瓶颈中点(节点局部 0, 0.089, 0), 与几何中心(0, 0.05, 0)差 39mm ——
  // 包围盒中心不是抓取基准(fit_item_grips 头注, 2026-08-06 用户按实机指认夹瓶口)
  const { driver, vial, mount } = makeItemScene([0, -0.07, -0.1], { grabLocal: [0, 0.089, 0] })
  driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0)
  driver.updateToolTween(3.5)
  vial.updateMatrixWorld(true)
  const featureWorld = vial.localToWorld(new THREE.Vector3(0, 0.089, 0))
  const anchorWorld = mount.localToWorld(new THREE.Vector3(0, 0, -0.12))
  assert.ok(featureWorld.distanceTo(anchorWorld) < 1e-9, '特征点精确落在四销笼锚点')
  assert.ok(itemWorldCenter(vial).distanceTo(anchorWorld) > 0.03,
    '几何中心不该再落在锚点上(吸附基准已换成特征点)')
})

test('单件磁吸: freeAxes 分量放手 —— 实测 (−18.19, −1.92, +55.91)mm 修成 (0, −1.92, +55.91)', () => {
  // 数字与 eit_ptlc/tests/test_grab_anchor_formula.py 完全同组: 编译器烤 dock 与前端
  // 磁吸是同一公式的两份实现, 共享数值夹具锁住漂移(2026-08-06 中转B 取瓶实测偏移)。
  const target = new THREE.Vector3(0.01819, 0.00192, -0.17591) // 修正前特征点在 mount 系的位置
  const offset = new THREE.Vector3(0, 0.089, 0).applyAxisAngle(new THREE.Vector3(0, 0, 1), 0.3)
  const seatPos = target.clone().sub(offset)
  const { driver, vial, mount } = makeItemScene(seatPos.toArray(), {
    grabLocal: [0, 0.089, 0],
    freeAxes: [[1, 0, 0]],   // 长度轴(此场景 = mount X)
  })
  driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0)
  driver.updateToolTween(3.5)
  vial.updateMatrixWorld(true)
  const featureMount = mount.worldToLocal(vial.localToWorld(new THREE.Vector3(0, 0.089, 0)))
  assert.ok(Math.abs(featureMount.x - 0.01819) < 1e-9, '长度轴分量放手不修(咬哪段由示教定)')
  assert.ok(Math.abs(featureMount.y - 0) < 1e-9, '闭合轴分量已修')
  assert.ok(Math.abs(featureMount.z - (-0.12)) < 1e-9, '销轴分量已修到锚点')
})

test('单件磁吸: freeAxes 为空表 = 三轴全锚定(瓶居中, 2026-08-07 定案)', () => {
  // 与 eit_ptlc/tests/test_grab_anchor_formula.py 的 full_correction 用例同一组语义
  const { driver, vial, mount } = makeItemScene([0, -0.07, -0.1],
    { grabLocal: [0, 0.089, 0], freeAxes: [] })
  driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0)
  driver.updateToolTween(3.5)
  vial.updateMatrixWorld(true)
  const featureWorld = vial.localToWorld(new THREE.Vector3(0, 0.089, 0))
  const anchorWorld = mount.localToWorld(new THREE.Vector3(0, 0, -0.12))
  assert.ok(featureWorld.distanceTo(anchorWorld) < 1e-9, '空表与缺省同义: 特征点精确落锚点')
})

test('单件磁吸: 量化件(节点 scale≈0.0475)照样接管 —— 换父判据不得被烤进世界矩阵的缩放骗到', () => {
  // 2026-08-07 用户报"四指夹爪夹起瓶子没有在中心"的第一个根因。运行期那份 GLB 经 04
  // meshopt 量化, 瓶这类件的 node.scale≈0.0475(几何缩进 int16 码值, 补偿塞在节点 TRS)。
  // reparentPreservingWorld 原本用 Quaternion.setFromRotationMatrix(worldBefore) 取"换父
  // 前"的朝向, 而那个 API 要求 3×3 是纯旋转 —— 带 scale 的矩阵解出无关四元数, 实测
  // 1−|dot| = 0.6954(位置残差却只有 4.4e-16), 1e-7 这道闸对所有量化件恒定假失败。
  // 而 parent.add() 早已执行完: 件挂在 TOOL_MOUNT 下, 但 owner 没写、磁吸补间没登记、
  // 半声不吭。此前 1065 条绿测全用 scale=1 的夹具, 所以整条缺陷从测试底下穿过去了。
  const SCALE = 0.0475
  const warnings = []
  const original = console.warn
  console.warn = (message) => warnings.push(String(message))
  try {
    // grabLocal 是**节点局部系**的值, 局部系随 scale 一起缩 —— 同一个物理瓶颈点在量化帧
    // 里的坐标要除以 scale。管线侧由 fit_item_grips.rebase_grab_local 出厂前搬帧, 这里
    // 直接给搬好的值(搬帧算式本身由 pytest 侧锁, 本测试只管消费端)。
    const { driver, vial, mount } = makeItemScene([0, -0.07, -0.1], {
      grabLocal: [0, 0.089 / SCALE, 0], freeAxes: [], nodeScale: SCALE,
    })
    const quatBefore = vial.getWorldQuaternion(new THREE.Quaternion())

    assert.equal(driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0), true)
    assert.equal(vial.parent, mount, '换父照常发生')
    assert.equal(driver.attachments.get('INV_STAGING_B_ITEM_1').owner, mount,
      'owner 必须写上 —— 缺陷期它停在原座位, 件挂在爪下却不归爪')
    assert.equal(driver.payloadTweens.size, 1, '磁吸补间必须登记 —— 缺陷期是 0 且无告警')
    assert.equal(warnings.length, 0,
      '量化 scale 是正常数据, 不该触发残差告警(告警说明判据仍被 scale 骗)')

    driver.updateToolTween(3.5)
    vial.updateMatrixWorld(true)
    const featureWorld = vial.localToWorld(new THREE.Vector3(0, 0.089 / SCALE, 0))
    const anchorWorld = mount.localToWorld(new THREE.Vector3(0, 0, -0.12))
    assert.ok(featureWorld.distanceTo(anchorWorld) < 1e-9, '抓取特征点精确落在四销笼锚点')
    assert.ok(Math.abs(vial.scale.x - SCALE) < 1e-9, '换父不得改动件的缩放(几何会当场变大 21 倍)')
    const quatAfter = vial.getWorldQuaternion(new THREE.Quaternion())
    assert.ok(1 - Math.abs(quatBefore.dot(quatAfter)) < 1e-12, '磁吸只平移, 不得转动物件')
  } finally {
    console.warn = original
  }
})

test('home() 清吸附基准缓存: Box3 兜底依赖当刻朝向, 旧缓存会把翻转过的件锚反', () => {
  const { driver, mount } = makeItemScene([0, -0.07, -0.1])
  driver.attach('INV_STAGING_B_ITEM_1', mount, 3.0)
  const entry = driver.attachments.get('INV_STAGING_B_ITEM_1')
  assert.ok(entry.grabLocalCenter, 'attach 后缓存已建立')
  driver.home()
  assert.equal(entry.grabLocalCenter, null, 'home() 必须清缓存')
})

test('ClipPlayer 端到端: 取放整板后向后 seek 再前进, 载荷所有权与位姿确定复现', () => {
  const { driver, tray, staging, rack } = makeScene()
  // 与真实转移同形: 夹住 → 地轨把整台车(连带夹爪和托盘)搬到中转位 → 松爪落位。
  const clip = compileClip(parseClip(`
schema: ptlc.clip/v1
name: t.transfer
label: 整板转移
home:
  axis_mm: { axis_rail: 0 }
steps:
  - { label: 显示源托盘, at: 0, dur: 0, do: { state: { id: INV_RACK_COLLECTOR_1, value: true } } }
  - { label: 夹住, at: 1, dur: 0, do: { attach: { id: INV_RACK_COLLECTOR_1, parent: TOOL_MOUNT } } }
  - { label: 地轨搬运, at: 1, dur: 1, ease: linear, do: { axis: { id: axis_rail, to_mm: 9002 } } }
  - { label: 松爪落位, at: 2, dur: 0.45, do: { detach: { id: INV_RACK_COLLECTOR_1, parent: ST_COLLECT, dock: { position: [0, 0, 0], quaternion: [0, 0, 0, 1] } } } }
`))
  const player = new ClipPlayer({ rig: driver })
  player.load(clip)

  player.seek(2.5)
  const settled = tray.position.clone()
  assert.equal(tray.parent, staging)
  assert.ok(settled.length() < 1e-12, '落位补间在 0.25s 内闭合到座位')

  // 向后跳: 播放器 home() 清场后逐事件重放, 载荷必须回到夹爪里。
  player.seek(1.5)
  assert.equal(tray.parent.name, 'TOOL_MOUNT', '回到取放之间时载荷应在夹爪里')

  // 再往回跳到取件之前: 载荷回货架。
  player.seek(0.5)
  assert.equal(tray.parent, rack, '取件之前载荷应在货架上')

  // 前进复现: 与第一次逐位一致。
  player.seek(2.5)
  assert.equal(tray.parent, staging)
  assert.ok(tray.position.distanceTo(settled) < 1e-12, '同一 t 的落位必须逐位复现')
})
