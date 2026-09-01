/**
 * 功能: 展缸盖悬吊平行四连杆的"水平保持"数学回归.
 *
 * 盖刚体(LID)嵌套在前摆杆(ROCKER_F)下**同轴反向**旋转: W(LID) = ΔQ(X, sθ)·ΔQ(X, −sθ)
 * 恒为常量 —— 任意开度下盖保持水平, 位置沿弧线纯平移(平行四连杆的耦连运动).
 * 该性质依赖三个前提: 空对象以单位局部旋转导出、父子绕同一世界轴、outputRange 同幅
 * 反号. 本测试把前提锁进回归: 轴不一致/幅值不等/嵌套关系丢失, 都会让 LID 世界旋转
 * 偏离单位阵而立刻翻红.
 *
 * 值语义与真 manifest 同构(rig_map tank_lids): 1=DO 动点=关盖=GLB 基准态(输出 0),
 * 0=原点=开盖(输出 θ/行程) —— 反相由 outputRange 反向 [θ, 0] 表达, 与夹爪同约定.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import * as THREE from 'three'

import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'

const THETA = 24.7
const STROKE_MM = 90

/** 构造与 blender_clean.build_tank_lids 产物同构的最小场景(实测量级, glTF Y-up) */
function makeRig() {
  const root = new THREE.Object3D(); root.name = 'ST_DEVELOP'
  const mount = new THREE.Object3D(); mount.name = 'TOOL_MOUNT'
  const rockerF = new THREE.Object3D(); rockerF.name = 'LINKAGE_TANK1_ROCKER_F'
  const rockerR = new THREE.Object3D(); rockerR.name = 'LINKAGE_TANK1_ROCKER_R'
  const lid = new THREE.Object3D(); lid.name = 'LINKAGE_TANK1_LID'
  const carriage = new THREE.Object3D(); carriage.name = 'LINKAGE_TANK1_CARRIAGE'
  rockerF.position.set(0, 0.234, -0.449)      // 前吊点(缸口上方 ~125mm)
  rockerR.position.set(0, 0.234, -0.649)      // 后吊点(排距 200mm)
  lid.position.set(0, -0.1092, 0.0609)        // ROCKER_F 局部系下的铰点偏移(垂 109/前 61mm)
  carriage.position.set(0, 0.1, -0.4)
  root.add(mount, rockerF, rockerR, carriage)
  rockerF.add(lid)

  const manifest = {
    stations: [], tanks: [], axes: [], tools: [], inventory: {},
    robot: { joints: [], toolMount: 'TOOL_MOUNT' },
    nodes: [], actuators: [], attachments: [], states: [], sockets: [],
    linkages: [{
      id: 'dev_t1_cyl1', label: '展缸1盖(dev_t1_cyl1)', inputRange: [0, 1], transitionS: 1.0,
      members: [
        { node: 'LINKAGE_TANK1_ROCKER_F', motion: 'rotate', axis: [1, 0, 0], sign: -1, inputRange: [0, 1], outputRange: [THETA, 0] },
        { node: 'LINKAGE_TANK1_ROCKER_R', motion: 'rotate', axis: [1, 0, 0], sign: -1, inputRange: [0, 1], outputRange: [THETA, 0] },
        { node: 'LINKAGE_TANK1_LID', motion: 'rotate', axis: [1, 0, 0], sign: 1, inputRange: [0, 1], outputRange: [THETA, 0] },
        { node: 'LINKAGE_TANK1_CARRIAGE', motion: 'translate', axis: [0, 0, 1], sign: 1, inputRange: [0, 1], outputRange: [STROKE_MM, 0], unitScale: 0.001 },
      ],
    }],
  }
  const byName = new Map()
  root.traverse((node) => byName.set(node.name, node))
  const rig = new MachineStateDriver({
    manifest,
    resolve: (path) => byName.get(String(path).split('/').pop()),
  })
  assert.deepEqual(rig.missing, [], '夹具场景不应有未解析节点')
  return { rig, root, rockerF, rockerR, lid, carriage }
}

test('任意开度下盖保持水平: LID 世界旋转恒为单位阵, 前后摆杆同角', () => {
  const { rig, root, rockerF, rockerR, lid } = makeRig()
  const quat = new THREE.Quaternion()
  for (const value of [0, 0.25, 0.5, 0.77, 1]) {
    rig.setLinkage('dev_t1_cyl1', value)
    root.updateMatrixWorld(true)
    lid.getWorldQuaternion(quat)
    // 阈值 1e-6 rad: acos 在 1 附近极敏感, 相同四元数的 angleTo 也有 ~1e-8 浮点噪声
    const angle = 2 * Math.acos(Math.min(1, Math.abs(quat.w)))
    assert.ok(angle < 1e-6, `value=${value} 时盖世界旋转应为零, 实得 ${angle} rad`)
    assert.ok(
      rockerF.quaternion.angleTo(rockerR.quaternion) < 1e-6,
      `value=${value} 时前后摆杆必须同角(平行四边形)`
    )
  }
})

test('值 1=关盖=GLB 基准态; 值 0=开盖(上抬+前移), 滑车走满行程', () => {
  const { rig, root, rockerF, lid, carriage } = makeRig()

  rig.setLinkage('dev_t1_cyl1', 1)
  root.updateMatrixWorld(true)
  assert.ok(
    rockerF.quaternion.angleTo(new THREE.Quaternion()) < 1e-6,
    'DO=1(动点=关盖)时摆杆必须停在 GLB 基准姿态'
  )
  assert.ok(Math.abs(carriage.position.z - -0.4) < 1e-12, '关盖时滑车在基准位')
  const closed = lid.getWorldPosition(new THREE.Vector3()).clone()

  rig.setLinkage('dev_t1_cyl1', 0)
  root.updateMatrixWorld(true)
  const open = lid.getWorldPosition(new THREE.Vector3())
  // 实测几何期望: 24.7° 开角 → 铰点上抬 ~35mm、向机器中心(+Z)前移 ~40mm
  assert.ok(open.y - closed.y > 0.02, `开盖应上抬 ≥20mm: Δy=${(open.y - closed.y) * 1000}mm`)
  assert.ok(open.z - closed.z > 0.02, `开盖应前移 ≥20mm: Δz=${(open.z - closed.z) * 1000}mm`)
  assert.ok(
    Math.abs(carriage.position.z - (-0.4 + STROKE_MM / 1000)) < 1e-12,
    '开盖时滑车应沿 +Z 位移满行程 90mm'
  )
})

test('home() 恢复关盖基准位(值账本清 NaN, 几何回加载态)', () => {
  const { rig, root, rockerF, lid, carriage } = makeRig()
  rig.setLinkage('dev_t1_cyl1', 0)
  root.updateMatrixWorld(true)
  rig.home()
  root.updateMatrixWorld(true)
  assert.ok(rockerF.quaternion.angleTo(new THREE.Quaternion()) < 1e-6, 'home 后摆杆回基准姿态')
  assert.ok(Math.abs(carriage.position.z - -0.4) < 1e-12, 'home 后滑车回基准位')
  const quat = lid.getWorldQuaternion(new THREE.Quaternion())
  assert.ok(2 * Math.acos(Math.min(1, Math.abs(quat.w))) < 1e-6, 'home 后盖仍水平')
})
