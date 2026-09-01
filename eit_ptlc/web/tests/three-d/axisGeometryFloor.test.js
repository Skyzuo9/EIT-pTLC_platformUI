/**
 * 功能: 直线轴"几何下界"(geometryMinMm)的钳制测试.
 *
 * 为什么它与 rangeMm 是两个量: `rangeMm` 镜像控制侧 limits, 是真源 —— 实机确实能走到
 * 那儿, 三维不得擅自收窄。`geometryMinMm` 说的是另一件事: 再往下, 滑车驮着的板会扎进
 * 固定结构。上下料 1Z/2Z 实测这个界比 rangeMm 下限高 18mm(见
 * pipeline/verify_plate_clearance.py), 差额来自三维把板简化成 200×200 的实心盒
 * (实机放置板在光电处有让位孔) —— 属于模型精度, 不是机器的事。
 *
 * 锁住两条: 常规链路必须夹; 标定页的 unclamped 试探必须**不**夹(否则标定时越界探不到,
 * 而"探不到"在界面上与"没越界"长得一模一样)。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { MachineStateDriver } from '../../src/three-d/anim/MachineStateDriver.js'

/** 造一根 1:1 米制的竖直轴; geometryMinMm 可选。 */
function makeRig({ geometryMinMm } = {}) {
  const parent = new THREE.Group()
  const carriage = new THREE.Group()
  carriage.name = 'CARRIAGE_TEST'
  parent.add(carriage)
  parent.updateMatrixWorld(true)

  const axis = {
    id: 'axis_1z',
    glbNode: 'CARRIAGE_TEST',
    rigged: true,
    axis: [0, 1, 0],
    sign: 1,
    mmToUnit: 0.001,
    zeroOffsetMm: -22,
    rangeMm: [-50, 550],
  }
  if (geometryMinMm !== undefined) axis.geometryMinMm = geometryMinMm
  const rig = new MachineStateDriver({
    manifest: { axes: [axis] },
    resolve: (path) => (path === 'CARRIAGE_TEST' ? carriage : undefined),
  })
  return { rig, carriage }
}

/** 轴写下去之后滑车相对 CAD 停靠态的位移(mm)。 */
function offsetMm(carriage) {
  return carriage.position.y * 1000
}

test('没声明几何下界时: 与从前一致, 只按 rangeMm 夹', () => {
  const { rig, carriage } = makeRig()
  rig.setAxisMm('axis_1z', -50)
  assert.ok(Math.abs(offsetMm(carriage) - (-50 + 22)) < 1e-9, '应走到 rangeMm 下限 −50')
  rig.setAxisMm('axis_1z', -80)
  assert.ok(Math.abs(offsetMm(carriage) - (-50 + 22)) < 1e-9, '越界仍夹在 −50')
})

test('声明几何下界后: 常规链路夹在它上面, 而不是 rangeMm 下限', () => {
  const { rig, carriage } = makeRig({ geometryMinMm: -32 })
  rig.setAxisMm('axis_1z', -50)
  assert.ok(Math.abs(offsetMm(carriage) - (-32 + 22)) < 1e-9, '−50 应被夹到 −32')
  rig.setAxisMm('axis_1z', -32)
  assert.ok(Math.abs(offsetMm(carriage) - (-32 + 22)) < 1e-9, '正好在界上不动')
})

test('上界与界内取值不受影响', () => {
  const { rig, carriage } = makeRig({ geometryMinMm: -32 })
  rig.setAxisMm('axis_1z', 512)
  assert.ok(Math.abs(offsetMm(carriage) - (512 + 22)) < 1e-9, '取料位 512 照走')
  rig.setAxisMm('axis_1z', 600)
  assert.ok(Math.abs(offsetMm(carriage) - (550 + 22)) < 1e-9, '上界仍是 rangeMm 的 550')
})

test('标定页的 unclamped 试探不受几何下界影响', () => {
  const { rig, carriage } = makeRig({ geometryMinMm: -32 })
  rig.setAxisMm('axis_1z', -50, { unclamped: true })
  assert.ok(Math.abs(offsetMm(carriage) - (-50 + 22)) < 1e-9,
    'unclamped 必须能探到 rangeMm 的真下限, 否则标定时越界与不越界长得一样')
})

test('几何下界比 rangeMm 下限还低时忽略它(不许反把行程放宽)', () => {
  const { rig, carriage } = makeRig({ geometryMinMm: -80 })
  rig.setAxisMm('axis_1z', -80)
  assert.ok(Math.abs(offsetMm(carriage) - (-50 + 22)) < 1e-9, '仍夹在 rangeMm 的 −50')
})
