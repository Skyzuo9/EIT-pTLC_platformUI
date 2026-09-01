/**
 * 功能: 薄层板分层几何的代数与锚点实测测试.
 *
 * 锁住的核心不变量: **板底面钉死在 CAD 盒底面**, 厚度只向 +Y 生长。
 * 若哪天有人把基准改成"从中心两边长", 调厚硅胶就会让板陷进缸底/托盘 ——
 * 那是一眼看不出、但每个落点都错半层的病。
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import {
  GLASS_MM,
  SILICA_MM,
  UNIT_BOX,
  clampSilicaMm,
  layerTransforms,
  measurePlateAnchor,
  plateTotalM,
} from '../../src/three-d/twin/scene/plates/plateGeometry.js'
import { DEQUANT_SCALE, makeQuantizedAnchor } from './plateFixtures.js'

/**
 * 实测值的容差(米)。顶点存在 Float32Array 里, 0.2 m 处的 float32 eps 约 1.2e-8,
 * 所以拿 1e-9 去比"实测 vs 名义"必然假红。1e-6 m = 1 µm, 比任何真实几何误差小三个
 * 数量级, 又稳稳高于浮点噪声。纯常数算术(两层是否严丝合缝)另用 EXACT。
 */
const MEASURED_TOL = 1e-6
/** 纯常数运算的容差: 不涉及顶点数据, 应当逐位相等。 */
const EXACT = 1e-12

/** 造一个与 CAD 同规格的板锚点: 200 × 3 × 200 mm, 厚度在局部 Y。 */
function makeAnchor({ rotate = 0, offset = null } = {}) {
  const parent = new THREE.Group()
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.003, 0.2), new THREE.MeshBasicMaterial())
  if (offset) mesh.position.copy(offset)
  if (rotate) mesh.rotation.y = rotate
  parent.add(mesh)
  parent.updateMatrixWorld(true)
  return { parent, mesh }
}

test('共享单位盒只有一个, 且是 12 个三角形', () => {
  assert.equal(UNIT_BOX.index.count / 3, 12)
  assert.equal(UNIT_BOX.attributes.position.count, 24)
})

test('厚度夹取: 越界收到边界, 非法值回落默认', () => {
  assert.equal(clampSilicaMm(0.05), SILICA_MM.min)
  assert.equal(clampSilicaMm(5), SILICA_MM.max)
  assert.equal(clampSilicaMm('abc'), SILICA_MM.default)
  assert.equal(clampSilicaMm(undefined), SILICA_MM.default)
  assert.equal(clampSilicaMm(0.75), 0.75)
})

test('标准板总厚 = 2 + 1 = 3mm, 与 CAD 实测的 0.003 完全吻合', () => {
  assert.ok(Math.abs(plateTotalM(SILICA_MM.default) - 0.003) < EXACT)
  assert.ok(Math.abs(plateTotalM(0.5) - 0.0025) < EXACT)
})

test('锚点实测: 拿到 200×3×200 的局部尺寸', () => {
  const { mesh } = makeAnchor()
  const geom = measurePlateAnchor(mesh)
  assert.ok(Math.abs(geom.widthM - 0.2) < MEASURED_TOL)
  assert.ok(Math.abs(geom.lengthM - 0.2) < MEASURED_TOL)
  assert.ok(Math.abs(geom.thickM - 0.003) < MEASURED_TOL)
})

test('锚点实测对旋转免疫(不是世界轴对齐包围盒)', () => {
  // 绕 Y 转 30°: 世界 AABB 会膨胀到约 0.273, 局部实测必须仍是 0.2
  const { mesh } = makeAnchor({ rotate: Math.PI / 6 })
  const geom = measurePlateAnchor(mesh)
  assert.ok(Math.abs(geom.widthM - 0.2) < MEASURED_TOL, `旋转后宽度不得膨胀, 实得 ${geom.widthM}`)
  assert.ok(Math.abs(geom.lengthM - 0.2) < MEASURED_TOL)

  const worldBox = new THREE.Box3().setFromObject(mesh, true).getSize(new THREE.Vector3())
  assert.ok(worldBox.x > 0.26, '前提校验: 世界 AABB 确实会膨胀, 所以不能用它')
})

test('锚点实测带出父级与局部位姿, 供板 Group 原位替身', () => {
  const { parent, mesh } = makeAnchor({ offset: new THREE.Vector3(0.5, 1.25, -0.25) })
  const geom = measurePlateAnchor(mesh)
  assert.equal(geom.parent, parent)
  assert.deepEqual(geom.position.toArray(), [0.5, 1.25, -0.25])
  assert.ok(Math.abs(geom.center.y) < MEASURED_TOL, 'center 是锚点自身坐标系里的, 不含父级偏移')
})

test('层变换: 板底面钉在 CAD 盒底面, 厚度只向上生长', () => {
  const { mesh } = makeAnchor()
  const geom = measurePlateAnchor(mesh)
  const bottom = geom.center.y - geom.thickM / 2

  for (const t of [0.1, 1.0, 2.0]) {
    const layers = layerTransforms(geom, t)
    const glassBottom = layers.glass.y - layers.glass.scale[1] / 2
    assert.ok(Math.abs(glassBottom - bottom) < EXACT, `t=${t} 时玻璃底面必须贴着 CAD 底面`)

    // 硅胶紧贴玻璃上表面, 中间不留缝也不穿插
    const glassTop = layers.glass.y + layers.glass.scale[1] / 2
    const silicaBottom = layers.silica.y - layers.silica.scale[1] / 2
    assert.ok(Math.abs(glassTop - silicaBottom) < EXACT, `t=${t} 时两层必须严丝合缝`)

    assert.ok(Math.abs(layers.glass.scale[1] - GLASS_MM * 0.001) < EXACT, '玻璃层厚固定 2mm')
    assert.ok(Math.abs(layers.silica.scale[1] - t * 0.001) < EXACT)
    assert.ok(Math.abs(layers.totalM - (GLASS_MM + t) * 0.001) < EXACT)
  }
})

test('层变换: 默认厚度下总厚正好填满 CAD 盒(既不高出也不缩水)', () => {
  const { mesh } = makeAnchor()
  const geom = measurePlateAnchor(mesh)
  const layers = layerTransforms(geom, SILICA_MM.default)
  const top = layers.silica.y + layers.silica.scale[1] / 2
  const cadTop = geom.center.y + geom.thickM / 2
  assert.ok(Math.abs(top - cadTop) < MEASURED_TOL, '标准板应与 CAD 盒完全重合')
})

test('层变换: 长宽沿用实测值, xz 落在盒中心', () => {
  const { mesh } = makeAnchor()
  const geom = measurePlateAnchor(mesh)
  const layers = layerTransforms(geom, 1.0)
  assert.ok(Math.abs(layers.glass.scale[0] - 0.2) < MEASURED_TOL)
  assert.ok(Math.abs(layers.glass.scale[2] - 0.2) < MEASURED_TOL)
  assert.ok(Math.abs(layers.x) < MEASURED_TOL)
  assert.ok(Math.abs(layers.z) < MEASURED_TOL)
})

test('无网格的锚点返回 null, 不产出假尺寸', () => {
  assert.equal(measurePlateAnchor(new THREE.Group()), null)
  assert.equal(measurePlateAnchor(null), null)
})

// ── 生产形态: 量化锚点 ─────────────────────────────────────────────────────
// 上面那些用例用的是未量化的 BoxGeometry(scale=1、薄轴在 Y) —— 恰好是代码假设的那种
// 锚点。真实 GLB 不是: 顶点是归一化 SHORT、反量化 scale 挂在节点上、薄轴在 Z。
// 2026-08-03 板被画成一条线就是栽在这个差别上, 以下用例是它的防回归网。

test('量化锚点: 尺寸必须乘回节点 scale 才是米(不乘就是 10 倍)', () => {
  const { mesh } = makeQuantizedAnchor()
  const geom = measurePlateAnchor(mesh)
  assert.ok(Math.abs(geom.widthM - 0.2) < 1e-6, `widthM=${geom.widthM}`)
  assert.ok(Math.abs(geom.lengthM - 0.2) < 1e-6, `lengthM=${geom.lengthM}`)
  // 量化把 3mm 存成了 3.003mm, 1e-5 的容差刚好容得下而挡得住 10 倍错
  assert.ok(Math.abs(geom.thickM - 0.003) < 1e-5, `thickM=${geom.thickM}`)
  // 反量化 scale 必须已经烘进尺寸, 不能再传给下游乘第二遍
  assert.ok(Math.abs(geom.scale.x - 1) < 1e-9, `scale 必须是单位, 实际 ${geom.scale.x}`)
  assert.ok(Math.abs(DEQUANT_SCALE - 0.1) < 1e-9)
})

test('量化锚点: 薄轴在局部 Z, 产出的标准帧必须把它转成 +Y', () => {
  const { mesh, parent } = makeQuantizedAnchor()
  const geom = measurePlateAnchor(mesh)
  const normal = new THREE.Vector3(0, 1, 0).applyQuaternion(geom.quaternion)
  // 该锚点的局部 +Z 已经指向父空间 +Y, 所以标准帧就是单位阵
  assert.ok(normal.y > 0.999, `板面法线应朝上, 实际 ${normal.toArray()}`)
  assert.ok(parent.children.includes(mesh))
})

test('量化锚点: 盒心折进 position, center 归零', () => {
  const offset = new THREE.Vector3(1, 2, 3)
  const { mesh } = makeQuantizedAnchor({ offset })
  const geom = measurePlateAnchor(mesh)
  assert.ok(geom.center.length() < 1e-9, 'center 应归零')
  assert.ok(geom.position.distanceTo(offset) < 1e-9, `position=${geom.position.toArray()}`)
})

test('量化锚点: 绕薄轴面内自转 30° 后实测不变(旋转免疫仍在)', () => {
  // 父空间 AABB 会膨胀到约 0.273; 局部实测必须仍是 0.2
  const { mesh } = makeQuantizedAnchor({ spin: Math.PI / 6 })
  const geom = measurePlateAnchor(mesh)
  assert.ok(Math.abs(geom.widthM - 0.2) < 1e-6, `widthM=${geom.widthM}`)
  assert.ok(Math.abs(geom.thickM - 0.003) < 1e-5, `thickM=${geom.thickM}`)
})

test('不是板的锚点返回 null —— 宁可不画, 不摆一块尺寸可疑的板', () => {
  const parent = new THREE.Group()
  const cube = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.1, 0.1), new THREE.MeshBasicMaterial())
  parent.add(cube)
  parent.updateMatrixWorld(true)
  assert.equal(measurePlateAnchor(cube), null)
})

test('硅胶朝向: silicaUp 决定两层上下, 底面都钉在 CAD 盒底面', () => {
  const { mesh } = makeQuantizedAnchor()
  const geom = measurePlateAnchor(mesh)
  const bottom = -geom.thickM / 2

  const up = layerTransforms({ ...geom, silicaUp: true }, 1.0)
  assert.ok(up.silica.y > up.glass.y, '朝上时硅胶在玻璃之上')
  assert.ok(Math.abs((up.glass.y - GLASS_MM * 0.0005) - bottom) < 1e-9, '玻璃底面钉在盒底')

  const down = layerTransforms({ ...geom, silicaUp: false }, 1.0)
  assert.ok(down.silica.y < down.glass.y, '朝下时硅胶在玻璃之下')
  assert.ok(Math.abs((down.silica.y - 0.0005) - bottom) < 1e-9, '硅胶底面钉在盒底')

  // 两种朝向的总厚一致, 且都严丝合缝
  assert.ok(Math.abs(up.totalM - down.totalM) < EXACT)
})
