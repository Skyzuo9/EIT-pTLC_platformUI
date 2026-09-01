/**
 * 功能: "板相对吸盘"刚体常量的代数测试(suctionMountLocal).
 *
 * 锁住的核心不变量: **被吸的那一面正好落在吸盘的"工作接触面"上, 一丝不差**。
 * 这条一旦破, 表现就是用户 2026-08-05 报的"吸盘扎穿板面" —— 而且它不会报任何错,
 * 只能靠这里的断言看着。
 *
 * ⚠ 工作接触面 = `contactLocalM − carryCompressionM · axisLocal`, **不是** contactLocalM
 *   本身。CAD 里这只波纹杯是自由态(逐顶点实测 35.0mm, contactLocalM 正落在自由唇口上),
 *   而真机抽着真空夹板, 波纹早已压瘪 —— 板骑的是压缩后的唇口。少扣这一段, 板会被画在
 *   自由唇口上, 放板时整块板扎进座面(2026-08-05 实测 17.82mm, 见 rig_map 的出处注释)。
 *   常量缺席(老 manifest)时该量为 0, 退回"贴自由唇口"的老行为。
 *
 * 另一条同样重要: 吸盘**永远贴玻璃面**, 从不贴硅胶(那是要被点样/刮取的粉末面)。
 * 于是两个翻转态贴的是板的两个不同面, 但板体永远在接触面的 +axis 一侧。
 * 画反了不会有任何自动指标报警 —— 画面照样"很真", 只是吸盘在吸粉。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import {
  GLASS_MM,
  SILICA_MM,
  plateTotalM,
  standardPlateGeom,
  suctionMountLocal,
} from '../../src/three-d/twin/scene/plates/plateGeometry.js'

/** 纯常数运算, 应当逐位相等(不涉及顶点数据)。 */
const EXACT = 1e-12
const MM = 0.001

/**
 * 与管线实测同形的 plateGrip(数值取 2026-08-05 在 machine.official-cr5.glb 上的实测值):
 * 两只 SAB22 沿节点局部 −Y 伸出, 唇口平面 y=−71.57mm, 对中心 z=−162.54mm, 中心距 85mm。
 */
const GRIP = Object.freeze({
  axisLocal: [0, -1, 0],
  contactLocalM: [0.000031, -0.07157172, -0.16254141],
  spanAxisLocal: [0, 0, -1],
  cupCount: 2,
  cupDiameterM: 0.024,
  cupSpanM: 0.085,
})

/** 造一个与 CAD 同规格的 geom(200×3×200mm), silicaUp 由落点语义给。 */
function geomOf(silicaUp) {
  return { ...standardPlateGeom(), silicaUp }
}

/** 板局部点 -> 翻转节点局部坐标。 */
function toActuator(mount, local) {
  return local.clone().applyQuaternion(mount.quaternion).add(mount.position)
}

/**
 * 工作接触面到某点的有符号距离, 沿 axisLocal(正 = 在板体那一侧)。
 * 基准取**压缩后**的唇口 —— 板骑的就是它, 见文件头注释。
 */
function alongAxis(point, grip = GRIP) {
  const axis = new THREE.Vector3().fromArray(grip.axisLocal).normalize()
  const carry = Number(grip.carryCompressionM) || 0
  const contact = new THREE.Vector3().fromArray(grip.contactLocalM).addScaledVector(axis, -carry)
  return point.clone().sub(contact).dot(axis)
}

for (const [name, silicaUp, faceSign] of [
  ['料仓/展缸(硅胶朝下, 玻璃在上, 吸盘从上方贴)', false, +1],
  ['点样座/刮板台(硅胶朝上, 玻璃在下, 吸盘从下方托)', true, -1],
]) {
  test(`${name}: 被吸的玻璃面正落在吸盘接触面上`, () => {
    const geom = geomOf(silicaUp)
    const mount = suctionMountLocal(GRIP, geom)
    assert.ok(mount, '实测常量齐全时必须解得出位姿')

    // 贴合面 = 玻璃层的外侧面。板局部 y: 底面 −thick/2, 顶面 +thick/2(标准板两者等厚)
    const half = plateTotalM() / 2
    const contactPoint = toActuator(mount, new THREE.Vector3(0, faceSign * half, 0))
    assert.ok(Math.abs(alongAxis(contactPoint)) < EXACT,
      `贴合面偏离接触面 ${alongAxis(contactPoint)} m`)
  })

  test(`${name}: 板体整个在接触面的 +axis 一侧(不许扎进吸盘)`, () => {
    const mount = suctionMountLocal(GRIP, geomOf(silicaUp))
    const half = plateTotalM() / 2
    for (const y of [-half, 0, half]) {
      assert.ok(alongAxis(toActuator(mount, new THREE.Vector3(0, y, 0))) >= -EXACT,
        `板上 y=${y} 的点落到了吸盘里侧`)
    }
  })
}

test('两个翻转态只差一个 180°: 位置相同, 朝向相反', () => {
  const down = suctionMountLocal(GRIP, geomOf(false))
  const up = suctionMountLocal(GRIP, geomOf(true))
  assert.ok(down.position.distanceTo(up.position) < EXACT,
    '标准板两层等厚时, 两态的板心应当重合')
  const yDown = new THREE.Vector3(0, 1, 0).applyQuaternion(down.quaternion)
  const yUp = new THREE.Vector3(0, 1, 0).applyQuaternion(up.quaternion)
  assert.ok(Math.abs(yDown.dot(yUp) + 1) < 1e-9, '两态的板面法线应当正好相反')
})

test('改硅胶厚度: 贴合面不动, 板往背离吸盘的方向长', () => {
  const geom = geomOf(false)
  const thin = suctionMountLocal(GRIP, geom, SILICA_MM.min)
  const thick = suctionMountLocal(GRIP, geom, SILICA_MM.max)
  // 贴的是玻璃面, 玻璃厚度不变 => 两个厚度下贴合面必须仍在接触面上
  for (const [mount, silicaMm] of [[thin, SILICA_MM.min], [thick, SILICA_MM.max]]) {
    const total = (GLASS_MM + silicaMm) * MM
    // silicaUp=false: 玻璃在上, 贴合面 = 盒底 + total(见 layerTransforms)
    const faceY = -geom.thickM / 2 + total
    const point = toActuator(mount, new THREE.Vector3(0, faceY, 0))
    assert.ok(Math.abs(alongAxis(point)) < 1e-12,
      `硅胶 ${silicaMm}mm 时贴合面偏离 ${alongAxis(point)} m`)
  }
  // 加厚只能往 +axis 长(远离吸盘), 不能把板顶进吸盘
  assert.ok(alongAxis(thick.position) > alongAxis(thin.position),
    '加厚硅胶应当让板心更远离吸盘, 而不是更近')
})

test('面内朝向由吸盘连线钉死(方板每次转载不许随机翻)', () => {
  const a = suctionMountLocal(GRIP, geomOf(false))
  const b = suctionMountLocal(GRIP, geomOf(false))
  assert.ok(a.quaternion.angleTo(b.quaternion) < EXACT, '同样输入必须给出同样朝向')
  const xAxis = new THREE.Vector3(1, 0, 0).applyQuaternion(a.quaternion)
  const span = new THREE.Vector3().fromArray(GRIP.spanAxisLocal).normalize()
  assert.ok(Math.abs(Math.abs(xAxis.dot(span)) - 1) < 1e-9, '板的面内 +X 应当就是吸盘连线')
})

/**
 * 持板压缩(2026-08-05 回归护栏)。
 *
 * 病征: 板被画在**自由长度**的唇口上, 于是放板时整块板扎进座面 —— 用户报的穿模。
 * 病因: CAD 杯是自由态, 真机抽真空后波纹压瘪, 板实际更靠近法兰 17.82mm。
 * 这一组锁住"扣了、且正好扣这么多、且方向朝法兰", 三条缺一不可 ——
 * 只断言"位置变了"会让符号写反(往远处挪 17.82mm, 穿模翻倍)照样全绿。
 */
const CARRY_M = 0.01782
const GRIP_CARRY = Object.freeze({ ...GRIP, carryCompressionM: CARRY_M })

for (const [name, silicaUp] of [['料仓/展缸', false], ['点样座/刮板台', true]]) {
  test(`${name}: 板骑在**压缩后**的唇口上, 而不是自由唇口`, () => {
    const geom = geomOf(silicaUp)
    const mount = suctionMountLocal(GRIP_CARRY, geom)
    const half = plateTotalM() / 2
    const faceSign = silicaUp ? -1 : +1
    const face = toActuator(mount, new THREE.Vector3(0, faceSign * half, 0))
    // 相对**工作**接触面(已扣压缩): 仍然一丝不差
    assert.ok(Math.abs(alongAxis(face, GRIP_CARRY)) < EXACT,
      `贴合面偏离压缩后唇口 ${alongAxis(face, GRIP_CARRY)} m`)
    // 相对**自由**唇口: 正好退回一个压缩量(负号 = 朝法兰那侧, 即没那么伸出去)
    assert.ok(Math.abs(alongAxis(face, GRIP) + CARRY_M) < EXACT,
      `相对自由唇口应为 ${-CARRY_M} m, 实为 ${alongAxis(face, GRIP)} m`)
  })
}

test('持板压缩只沿吸盘轴挪板, 不动面内位置与朝向', () => {
  const geom = geomOf(false)
  const base = suctionMountLocal(GRIP, geom)
  const carried = suctionMountLocal(GRIP_CARRY, geom)
  const axis = new THREE.Vector3().fromArray(GRIP.axisLocal).normalize()
  const shift = carried.position.clone().sub(base.position)
  assert.ok(Math.abs(shift.dot(axis) + CARRY_M) < EXACT, '沿轴位移应正好是 −carryCompression')
  // 去掉沿轴分量后应当一无所剩 —— 否则就是把板顺带挪偏了对中心
  assert.ok(shift.clone().addScaledVector(axis, -shift.dot(axis)).length() < EXACT,
    '不许有面内位移')
  assert.ok(carried.quaternion.angleTo(base.quaternion) < EXACT, '不许改朝向')
})

test('carryCompressionM 缺席/非法时按 0 处理(老 manifest 仍走老行为)', () => {
  const geom = geomOf(false)
  const base = suctionMountLocal(GRIP, geom).position
  for (const value of [undefined, null, 0, NaN, 'abc']) {
    const mount = suctionMountLocal({ ...GRIP, carryCompressionM: value }, geom)
    assert.ok(mount, `carryCompressionM=${String(value)} 不该让整个位姿解不出来`)
    assert.ok(mount.position.distanceTo(base) < EXACT,
      `carryCompressionM=${String(value)} 应当等价于 0`)
  }
})

test('常量缺失或不成形时返回 null, 让调用方退回旧路径而不是摆错位置', () => {
  const geom = geomOf(false)
  assert.equal(suctionMountLocal(null, geom), null)
  assert.equal(suctionMountLocal(undefined, geom), null)
  assert.equal(suctionMountLocal({}, geom), null)
  assert.equal(suctionMountLocal({ ...GRIP, axisLocal: [0, 0] }, geom), null, '分量少一个')
  assert.equal(suctionMountLocal({ ...GRIP, axisLocal: [0, 0, 0] }, geom), null, '零向量')
  assert.equal(suctionMountLocal({ ...GRIP, contactLocalM: null }, geom), null)
  // 连线与轴向平行时定不出面内朝向 —— 宁可不摆也不摆一个随机的
  assert.equal(suctionMountLocal({ ...GRIP, spanAxisLocal: [0, -1, 0] }, geom), null)
})
