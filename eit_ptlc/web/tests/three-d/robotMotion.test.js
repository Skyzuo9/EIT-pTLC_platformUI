import test from 'node:test'
import assert from 'node:assert/strict'

import * as THREE from 'three'

import { compileClip } from '../../src/three-d/anim/clipSchema.js'
import { RobotJointDriver, unwrapAngleDeg } from '../../src/three-d/anim/RobotJointDriver.js'
import { MachineRig } from '../../src/three-d/anim/MachineRig.js'
import { MachineStateDriver, reparentPreservingWorld } from '../../src/three-d/anim/MachineStateDriver.js'
import { RobotPoseBuffer } from '../../src/three-d/twin/bindings/RobotPoseBuffer.js'


test('clip/v2 resolves move_j from catalog and move_l only from compiled continuous IK', () => {
  const hash = 'point-sha'
  const catalog = {
    schema: 'ptlc.robot-points/v1',
    referencePointHash: hash,
    points: {
      ready: { joint: [1, 2, 3, 4, 5, 6], allowedMotion: ['move_j'] },
      target: { joint: null, allowedMotion: ['move_l'] },
    },
  }
  const doc = {
    schema: 'ptlc.clip/v2',
    name: 'production',
    source: { referencePointHash: hash },
    home: { joints_deg: [0, 0, 0, 0, 0, 0] },
    steps: [
      { dur: 1, do: { robot_point: { id: 'ready', motion: 'move_j' } } },
      { dur: 1, do: { robot_point: { id: 'target', motion: 'move_l' } } },
    ],
    compiled: {
      moveLTrajectories: {
        1: [[1, 2, 3, 4, 5, 6], [2, 3, 4, 5, 6, 7], [3, 4, 5, 6, 7, 8]],
      },
    },
  }
  const clip = compileClip(doc, { pointCatalog: catalog })
  assert.equal(clip.schema, 'ptlc.clip/v2')
  assert.deepEqual(clip.channels.get('joint:0').map((frame) => frame.v), [0, 1, 1, 2, 3])
  assert.throws(
    () => compileClip({ ...doc, source: { referencePointHash: 'stale' } }, { pointCatalog: catalog }),
    /SHA 不一致/,
  )
})


test('RobotJointDriver rotates local rotor axes absolutely and keeps rigid hierarchy', () => {
  const root = new THREE.Object3D()
  const rotor1 = new THREE.Object3D(); rotor1.name = 'J1'
  const link1 = new THREE.Object3D(); link1.position.set(0, 1, 0)
  const rotor2 = new THREE.Object3D(); rotor2.name = 'J2'; rotor2.position.set(0, 2, 0)
  const tip = new THREE.Object3D(); tip.position.set(0, 1, 0)
  root.add(rotor1); rotor1.add(link1); rotor1.add(rotor2); rotor2.add(tip)
  root.updateMatrixWorld(true)
  const upstreamBefore = new THREE.Vector3(); link1.getWorldPosition(upstreamBefore)
  const tipBefore = new THREE.Vector3(); tip.getWorldPosition(tipBefore)

  const nodes = new Map([['J1', rotor1], ['J2', rotor2]])
  const driver = new RobotJointDriver({ joints: [
    { id: 'J1', node: 'J1', axis: [0, 1, 0], sign: 1, zeroOffsetDeg: 0, limitDeg: [-360, 360] },
    { id: 'J2', node: 'J2', axis: [0, 0, 1], sign: -1, zeroOffsetDeg: 10, limitDeg: [-360, 360] },
  ] }, (name) => nodes.get(name))
  driver.setJointsDeg([0, 20], { continuous: false })
  root.updateMatrixWorld(true)

  const upstreamAfter = new THREE.Vector3(); link1.getWorldPosition(upstreamAfter)
  const tipAfter = new THREE.Vector3(); tip.getWorldPosition(tipAfter)
  assert.ok(upstreamBefore.distanceTo(upstreamAfter) < 1e-12, '上游连杆不得被下游关节带动')
  assert.ok(tipBefore.distanceTo(tipAfter) > 0.1, '下游应发生刚体运动')
  assert.deepEqual(tip.scale.toArray(), [1, 1, 1])
  assert.ok(Math.abs(THREE.MathUtils.radToDeg(rotor2.rotation.z) + 10) < 1e-9)
})


test('J1-J6 each rotate +/-10deg as a rigid local-axis subtree', () => {
  const root = new THREE.Object3D()
  const nodes = new Map()
  const rotors = []
  const markers = []
  let parent = root
  for (let index = 0; index < 6; index += 1) {
    const origin = new THREE.Object3D()
    origin.position.set(0.12 + index * 0.01, 0.08, 0.05)
    const rotor = new THREE.Object3D(); rotor.name = `J${index + 1}`
    const marker = new THREE.Object3D(); marker.position.set(0.07, 0.03, 0.02)
    parent.add(origin); origin.add(rotor); rotor.add(marker)
    nodes.set(rotor.name, rotor)
    rotors.push(rotor); markers.push(marker)
    parent = rotor
  }
  const driver = new RobotJointDriver({ joints: rotors.map((rotor, index) => ({
    id: rotor.name,
    node: rotor.name,
    axis: [0, 1, 0],
    sign: 1,
    zeroOffsetDeg: 0,
    limitDeg: [-360, 360],
  })) }, (name) => nodes.get(name))

  for (let jointIndex = 0; jointIndex < 6; jointIndex += 1) {
    for (const angle of [-10, 10]) {
      driver.home(); root.updateMatrixWorld(true)
      const before = markers.map((marker) => marker.getWorldPosition(new THREE.Vector3()))
      const beforeRigidDistance = before[jointIndex].distanceTo(before[5])
      const command = Array(6).fill(null); command[jointIndex] = angle
      driver.setJointsDeg(command, { continuous: false }); root.updateMatrixWorld(true)
      const after = markers.map((marker) => marker.getWorldPosition(new THREE.Vector3()))
      for (let upstream = 0; upstream < jointIndex; upstream += 1) {
        assert.ok(before[upstream].distanceTo(after[upstream]) < 1e-12)
      }
      assert.ok(before[jointIndex].distanceTo(after[jointIndex]) > 1e-4)
      assert.ok(Math.abs(after[jointIndex].distanceTo(after[5]) - beforeRigidDistance) < 1e-12)
      for (const rotor of rotors) assert.deepEqual(rotor.scale.toArray(), [1, 1, 1])
    }
  }
})


test('MachineRig quick-change closes at TOOL_MOUNT and restores deterministic dock pose', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const station = new THREE.Object3D(); station.name = 'ST_TOOLING'
  const tool = new THREE.Object3D(); tool.name = 'TOOL_PLATE96'
  tool.position.set(2, 3, 4); tool.rotation.set(0.1, 0.2, 0.3)
  mount.position.copy(tool.position); mount.quaternion.copy(tool.quaternion)
  root.add(mount, station); station.add(tool); root.updateMatrixWorld(true)
  const homePosition = tool.position.clone(); const homeQuaternion = tool.quaternion.clone()
  const mountHomePosition = mount.position.clone(); const mountHomeQuaternion = mount.quaternion.clone()
  const byName = new Map([['TOOL_MOUNT', mount], ['TOOL_PLATE96', tool]])
  const manager = { getNode: (name) => byName.get(name), effects: { setSelected: () => {} } }
  const rig = new MachineRig({ manager, manifest: {
    axes: [],
    robot: { joints: [], toolMount: 'TOOL_MOUNT' },
    tools: [{ id: 'TOOL_PLATE96', glbNode: 'TOOL_PLATE96' }],
  } })

  const worldQuaternionBeforeLock = tool.getWorldQuaternion(new THREE.Quaternion())
  assert.equal(rig.lockTool('TOOL_PLATE96'), true)
  assert.equal(tool.parent, mount)
  assert.ok(tool.position.length() < 1e-12, '标定对接位锁紧后工具接口应闭合到 TOOL_MOUNT')
  assert.ok(1 - Math.abs(tool.getWorldQuaternion(new THREE.Quaternion()).dot(
    worldQuaternionBeforeLock,
  )) < 1e-12, '锁紧瞬间必须保持夹爪世界朝向连续')
  const lockedLocalQuaternion = tool.quaternion.clone()
  mount.position.set(0.5, 0.25, -0.5); mount.rotation.y = 0.7; root.updateMatrixWorld(true)
  assert.ok(tool.getWorldPosition(new THREE.Vector3()).distanceTo(
    mount.getWorldPosition(new THREE.Vector3()),
  ) < 1e-12)
  assert.ok(1 - Math.abs(tool.quaternion.dot(lockedLocalQuaternion)) < 1e-12,
    '锁紧后局部姿态不变，世界姿态随 J6/TOOL_MOUNT 刚性旋转')

  // 实机释放发生在机械臂重新回到工具停靠位之后。
  mount.position.copy(mountHomePosition); mount.quaternion.copy(mountHomeQuaternion); root.updateMatrixWorld(true)
  assert.equal(rig.releaseTool('TOOL_PLATE96'), true)
  assert.equal(tool.parent, station)
  assert.ok(tool.position.distanceTo(homePosition) < 1e-12)
  assert.ok(1 - Math.abs(tool.quaternion.dot(homeQuaternion)) < 1e-12)
})


test('带片段时刻的锁紧/释放走吸附补间: 平滑滑入且是 t 的纯函数', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const station = new THREE.Object3D(); station.name = 'ST_TOOLING'
  const tool = new THREE.Object3D(); tool.name = 'TOOL_PLATE96'
  // 示教残差场景: 锁紧瞬间工具离 mount_transform 目标位差 2mm。
  tool.position.set(2, 3, 4)
  mount.position.set(2.002, 3, 4)
  root.add(mount, station); station.add(tool); root.updateMatrixWorld(true)
  const homePosition = tool.position.clone()
  const nodes = new Map([['TOOL_MOUNT', mount], ['TOOL_PLATE96', tool]])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [{
        id: 'TOOL_PLATE96', glbNode: 'TOOL_PLATE96',
        mountPosition: [0, 0, 0], mountQuaternion: [0, 0, 0, 1],
      }],
    },
  })

  assert.equal(driver.lockTool('TOOL_PLATE96', 3.0), true)
  assert.equal(tool.parent, mount)
  // 锁紧当帧(t=t0)不跳变: 仍在换父保持的世界位姿上(局部残差 2mm)。
  driver.updateToolTween(3.0)
  assert.ok(Math.abs(tool.position.length() - 0.002) < 1e-9, '吸附起点应保持锁紧瞬间位姿')
  // 中途: 单调滑向目标。
  driver.updateToolTween(3.1)
  const midway = tool.position.length()
  assert.ok(midway > 0 && midway < 0.002, '吸附过程应介于起点与目标之间')
  // 纯函数复现: 同一时刻重复求值得到同一位姿。
  const snapshot = tool.position.clone()
  driver.updateToolTween(3.1)
  assert.ok(tool.position.distanceTo(snapshot) < 1e-12, '同一 t 必须复现同一位姿')
  // 完成: 精确落位并清除补间。
  driver.updateToolTween(3.3)
  assert.ok(tool.position.length() < 1e-12, '吸附结束必须精确闭合到 mount_transform')
  assert.equal(driver.toolTween, null)

  // 释放对称: 滑回精确停靠位, 吃掉到位残差。
  mount.position.set(2.0015, 3, 4); root.updateMatrixWorld(true)
  assert.equal(driver.releaseTool('TOOL_PLATE96', 8.0), true)
  assert.equal(tool.parent, station)
  driver.updateToolTween(8.3)
  assert.ok(tool.position.distanceTo(homePosition) < 1e-12, '释放吸附结束必须精确回到停靠位')

  // 行程超限保险: 坏数据直接就位, 不做拉扯补间。
  mount.position.set(2.5, 3, 4); root.updateMatrixWorld(true)
  assert.equal(driver.lockTool('TOOL_PLATE96', 12.0), true)
  assert.equal(driver.toolTween, null, '超限行程不建立补间')
  assert.ok(tool.position.length() < 1e-12, '超限行程直接精确就位')
})


test('MachineStateDriver drives node/actuator/linkage absolutely and restores deterministic home', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const node = new THREE.Object3D(); node.name = 'NODE_SLIDE'; node.position.set(1, 2, 3)
  const cylinder = new THREE.Object3D(); cylinder.name = 'ACT_CYLINDER'
  const linkA = new THREE.Object3D(); linkA.name = 'LINK_A'
  const linkB = new THREE.Object3D(); linkB.name = 'LINK_B'
  root.add(mount, node, cylinder, linkA, linkB)
  const nodes = new Map([...root.children].map((child) => [child.name, child]))
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      nodes: [{ id: 'slide', node: 'NODE_SLIDE' }],
      actuators: [{
        id: 'cylinder', node: 'ACT_CYLINDER', motion: 'translate', axis: [1, 0, 0],
        inputRange: [0, 1], outputRange: [0, 0.12],
      }],
      linkages: [{
        id: 'lid', inputRange: [0, 1], members: [
          { node: 'LINK_A', motion: 'rotate', axis: [0, 0, 1], inputRange: [0, 1], outputRange: [0, 60] },
          { node: 'LINK_B', motion: 'rotate', axis: [0, 0, 1], inputRange: [0, 1], outputRange: [0, -30] },
        ],
      }],
    },
  })

  driver.setNodeOffset('slide', [0.2, 0, -0.1])
  driver.setNodeOffset('slide', [0.2, 0, -0.1])
  assert.deepEqual(node.position.toArray(), [1.2, 2, 2.9], '重复绝对写不得累积漂移')
  driver.setActuator('cylinder', 0.5)
  assert.ok(Math.abs(cylinder.position.x - 0.06) < 1e-12)
  driver.setLinkage('lid', 0.5)
  assert.ok(Math.abs(THREE.MathUtils.radToDeg(linkA.rotation.z) - 30) < 1e-9)
  assert.ok(Math.abs(THREE.MathUtils.radToDeg(linkB.rotation.z) + 15) < 1e-9)
  assert.deepEqual(driver.rigidScaleViolations(), [])

  driver.home()
  assert.deepEqual(node.position.toArray(), [1, 2, 3])
  assert.deepEqual(cylinder.position.toArray(), [0, 0, 0])
  assert.ok(Math.abs(linkA.rotation.z) < 1e-12)
  assert.ok(Math.abs(linkB.rotation.z) < 1e-12)
})


test('reparentPreservingWorld keeps payload pose and then follows its new owner rigidly', () => {
  const root = new THREE.Object3D()
  const owner = new THREE.Object3D(); owner.name = 'OWNER'; owner.position.set(1, 0, 0)
  const payload = new THREE.Object3D(); payload.name = 'PAYLOAD'; payload.position.set(-0.2, 0.5, 0.1)
  root.add(owner, payload); root.updateMatrixWorld(true)
  const beforePosition = payload.getWorldPosition(new THREE.Vector3())
  const beforeQuaternion = payload.getWorldQuaternion(new THREE.Quaternion())

  assert.equal(reparentPreservingWorld(payload, owner), true)
  root.updateMatrixWorld(true)
  assert.ok(payload.getWorldPosition(new THREE.Vector3()).distanceTo(beforePosition) < 1e-12)
  assert.ok(1 - Math.abs(payload.getWorldQuaternion(new THREE.Quaternion()).dot(beforeQuaternion)) < 1e-12)
  owner.rotation.y = 0.6; owner.position.x += 0.3; root.updateMatrixWorld(true)
  assert.ok(payload.getWorldPosition(new THREE.Vector3()).distanceTo(beforePosition) > 0.1)
  assert.deepEqual(payload.scale.toArray(), [1, 1, 1])
})


test('RobotPoseBuffer interpolates at 100ms, handles disorder/wrap, and freezes stale pose', () => {
  const base = 1_700_000_000_000
  const buffer = new RobotPoseBuffer({ delayMs: 100, staleMs: 500 })
  buffer.push({ type: 'robot_pose', seq: 1, ts: base, joint: [170, 0, 0, 0, 0, 0], tool: 1 }, base)
  buffer.push({ type: 'robot_pose', seq: 3, ts: base + 100, joint: [-170, 0, 0, 0, 0, 0], tool: 1 }, base + 100)
  buffer.push({ type: 'robot_pose', seq: 2, ts: base + 50, joint: [180, 0, 0, 0, 0, 0], tool: 1 }, base + 100)

  const middle = buffer.sample(base + 175) // render time = base+75
  assert.ok(Math.abs(middle.joint[0] - 185) < 1e-9)
  assert.equal(middle.stale, false)
  assert.equal(buffer.pushTelemetry({ joint: [0, 0, 0, 0, 0, 0] }, base + 120, base + 120), false)

  const stale = buffer.sample(base + 701)
  assert.equal(stale.stale, true)
  assert.ok(stale.joint[0] >= 180, '断流冻结最后姿态，不回零')
  assert.equal(unwrapAngleDeg(-179, 179), 181)

  buffer.push({
    type: 'robot_pose', seq: 1, ts: base + 800,
    joint: [90, 10, 20, 30, 40, 50], tool: 2,
  }, base + 800)
  const reconnected = buffer.sample(base + 800)
  assert.deepEqual(reconnected.joint, [90, 10, 20, 30, 40, 50])
  assert.equal(reconnected.resynced, true)
})


test('MachineStateDriver authoritative mounted_tool snaps on reconnect and restores dock on bare wrist', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'; mount.position.set(1, 0, 0)
  const dock = new THREE.Object3D(); dock.name = 'TOOL_DOCK'
  const tool = new THREE.Object3D(); tool.name = 'TOOL'; tool.position.set(-2, 0.5, 0)
  root.add(mount, dock); dock.add(tool); root.updateMatrixWorld(true)
  const dockLocal = tool.position.clone()
  const nodes = new Map([['TOOL_MOUNT', mount], ['TOOL_DOCK', dock], ['TOOL', tool]])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [{ id: 'TOOL', controllerTool: 2, glbNode: 'TOOL', dockNode: 'TOOL_DOCK' }],
    },
  })

  const mounted = driver.syncMountedTool(2, { forceSnap: true })
  assert.equal(mounted.changed, true)
  assert.equal(mounted.resynced, true)
  assert.equal(tool.parent, mount)
  assert.ok(tool.position.length() < 1e-12)
  mount.rotation.y = 0.5; root.updateMatrixWorld(true)
  assert.ok(tool.getWorldPosition(new THREE.Vector3()).distanceTo(
    mount.getWorldPosition(new THREE.Vector3()),
  ) < 1e-12)

  const released = driver.syncMountedTool(0)
  assert.equal(released.changed, true)
  assert.equal(tool.parent, dock)
  assert.ok(tool.position.distanceTo(dockLocal) < 1e-12)
})

test('MachineStateDriver applies the calibrated large-gripper mount pose and follows J6 rigidly', () => {
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'; root.add(mount)
  const dock = new THREE.Object3D(); dock.name = 'TOOL_DOCK'; root.add(dock)
  const tool = new THREE.Object3D(); tool.name = 'TOOL_PLATE96'; dock.add(tool)
  const mountPosition = [0.000420864, -0.000465401, -0.000431585]
  const mountQuaternion = [-0.707592304, 0.000684711, 0.000743800, 0.706620202]
  const nodes = new Map([
    ['TOOL_MOUNT', mount], ['TOOL_DOCK', dock], ['TOOL_PLATE96', tool],
  ])
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: [{
        id: 'TOOL_PLATE96', controllerTool: 2, glbNode: 'TOOL_PLATE96',
        dockNode: 'TOOL_DOCK', mountPosition, mountQuaternion,
      }],
    },
  })

  driver.syncMountedTool(2, { forceSnap: true })
  assert.equal(tool.parent, mount)
  assert.ok(tool.position.distanceTo(new THREE.Vector3(...mountPosition)) < 1e-12)
  assert.ok(1 - Math.abs(tool.quaternion.dot(new THREE.Quaternion(...mountQuaternion))) < 1e-12)

  const localPosition = tool.position.clone()
  const localQuaternion = tool.quaternion.clone()
  mount.rotation.z = 0.7
  root.updateMatrixWorld(true)
  assert.ok(tool.position.distanceTo(localPosition) < 1e-12, 'J6 转动不得改变工具局部位置')
  assert.ok(1 - Math.abs(tool.quaternion.dot(localQuaternion)) < 1e-12,
    'J6 转动不得改变工具局部朝向')
})

/**
 * 三把刀共用一组快换耦合位姿, 建一个三工位的迷你工具站.
 * @returns {{root: THREE.Object3D, mount: THREE.Object3D, docks: object, tools: object, driver: object}}
 */
function buildThreeSlotStation() {
  const mountPosition = [0.000420864, -0.000465401, -0.000431585]
  const mountQuaternion = [-0.707592304, 0.000684711, 0.000743800, 0.706620202]
  const slots = [
    { id: 'TOOL_SUCTION', controllerTool: 1, x: -0.546 },
    { id: 'TOOL_PLATE96', controllerTool: 2, x: -0.404 },
    { id: 'TOOL_VIAL', controllerTool: 3, x: -0.244 },
  ]
  const root = new THREE.Object3D()
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'; root.add(mount)
  const nodes = new Map([['TOOL_MOUNT', mount]])
  const docks = {}
  const tools = {}
  for (const slot of slots) {
    const dock = new THREE.Object3D(); dock.name = `${slot.id}_DOCK`
    dock.position.set(slot.x, 0.257, -0.4215)
    const tool = new THREE.Object3D(); tool.name = slot.id
    root.add(dock); dock.add(tool)
    nodes.set(dock.name, dock); nodes.set(slot.id, tool)
    docks[slot.id] = dock; tools[slot.id] = tool
  }
  root.updateMatrixWorld(true)
  const driver = new MachineStateDriver({
    resolve: (name) => nodes.get(name),
    manifest: {
      axes: [],
      robot: { joints: [], toolMount: 'TOOL_MOUNT' },
      tools: slots.map((slot) => ({
        id: slot.id,
        controllerTool: slot.controllerTool,
        glbNode: slot.id,
        dockNode: `${slot.id}_DOCK`,
        mountPosition,
        mountQuaternion,
      })),
    },
  })
  return { root, mount, docks, tools, driver, mountPosition, mountQuaternion }
}

test('MachineStateDriver 换到 1 号吸盘: 上一把刀回停靠位, 吸盘挂上标定位姿', () => {
  const { root, mount, docks, tools, driver, mountPosition, mountQuaternion } = buildThreeSlotStation()

  driver.syncMountedTool(2, { forceSnap: true })
  assert.equal(tools.TOOL_PLATE96.parent, mount)

  // 实机换刀会经过裸腕, 但即使直接 2 -> 1 也必须两件事同时发生:
  // 大夹爪回到自己的停靠位, 吸盘挂到法兰上。回归前吸盘根本没有声明, 这里会挂不上。
  const swapped = driver.syncMountedTool(1)
  assert.equal(swapped.missing, false, '1 号吸盘必须在 manifest 里有声明')
  assert.equal(tools.TOOL_PLATE96.parent, docks.TOOL_PLATE96, '上一把刀必须回停靠位')
  assert.equal(tools.TOOL_SUCTION.parent, mount, '吸盘必须挂到 TOOL_MOUNT')
  assert.ok(tools.TOOL_SUCTION.position.distanceTo(new THREE.Vector3(...mountPosition)) < 1e-12)
  assert.ok(1 - Math.abs(
    tools.TOOL_SUCTION.quaternion.dot(new THREE.Quaternion(...mountQuaternion)),
  ) < 1e-12)
  assert.equal(driver.unknownControllerTool, null)

  // 随 J6 刚体转动
  const localPosition = tools.TOOL_SUCTION.position.clone()
  mount.rotation.z = 0.7
  root.updateMatrixWorld(true)
  assert.ok(tools.TOOL_SUCTION.position.distanceTo(localPosition) < 1e-12)
})

test('MachineStateDriver 小夹爪挂载用标定四元数, 不退回单位四元数', () => {
  const { mount, tools, driver, mountQuaternion } = buildThreeSlotStation()

  driver.syncMountedTool(3, { forceSnap: true })
  assert.equal(tools.TOOL_VIAL.parent, mount)
  const identity = new THREE.Quaternion()
  assert.ok(1 - Math.abs(tools.TOOL_VIAL.quaternion.dot(new THREE.Quaternion(...mountQuaternion))) < 1e-12)
  assert.ok(1 - Math.abs(tools.TOOL_VIAL.quaternion.dot(identity)) > 0.2,
    '退回单位四元数会让小夹爪绕安装轴错转约 90°')
})

test('MachineStateDriver 对未声明的工具号留痕而不冒充其它工具', () => {
  const { mount, docks, tools, driver } = buildThreeSlotStation()

  driver.syncMountedTool(2, { forceSnap: true })
  const unknown = driver.syncMountedTool(7)
  assert.equal(unknown.missing, true)
  assert.equal(driver.unknownControllerTool, 7, '未声明的工具号必须留痕供 HUD 告警')
  assert.equal(tools.TOOL_PLATE96.parent, docks.TOOL_PLATE96, '上一把刀仍要回停靠位')
  for (const tool of Object.values(tools)) {
    assert.notEqual(tool.parent, mount, '绝不能用别的工具冒充')
  }
})
