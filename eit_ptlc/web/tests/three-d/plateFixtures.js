/**
 * 功能: 与**生产形态逐位一致**的板锚点夹具.
 *
 * 为什么要单独有这么个东西: 2026-08-03 板被画成一条线, 而单测全绿 —— 因为夹具是
 * `BoxGeometry(0.2, 0.003, 0.2)` + 节点 scale 1 + 薄轴在 Y, **恰好是代码假设的那种锚点,
 * 也恰好是真实 GLB 不是的那种**。测试把假设当成了事实, 于是量纲错了三年也测不出来。
 *
 * 真实 GLB(machine.official-cr5.glb, 12 个板锚点全一致)的形态是:
 *   - `POSITION` accessor: `SHORT` + `normalized: true`(KHR_mesh_quantization)
 *   - 顶点范围 `±32767, ±32767, ±492` → 反归一化后 `±1, ±1, ±0.015015`, **薄轴在 Z**
 *   - 节点 `scale ≈ 0.1`(反量化因子), 祖先链全是单位 scale
 *   - 四元数把局部 +Z 转成父空间 +Y, 且是有符号轴置换(父空间里轴对齐)
 *   - 于是父空间尺寸 = 200 × 3 × 200 mm
 */
import * as THREE from 'three'

/** 归一化 SHORT 的满量程。three 的 denormalize 用 max(v/32767, -1)。 */
const SHORT_MAX = 32767

/** 真实锚点的反量化 scale(实测 0.10000000149…, 这里取名义值)。 */
export const DEQUANT_SCALE = 0.1

/**
 * 功能: 造一个量化板锚点(默认与 CAD 同规格: 父空间 200 × 3 × 200 mm).
 *
 * @param {object} [opts]
 * @param {THREE.Vector3} [opts.offset] 锚点在父空间的位置
 * @param {number} [opts.spin] 绕**薄轴**(板面法线)的面内自转角(弧度), 用来验旋转免疫
 * @param {THREE.Quaternion} [opts.parentRotation] 父级自身的姿态(验"法线取世界朝上")
 * @returns {{parent: THREE.Group, mesh: THREE.Mesh}}
 */
export function makeQuantizedAnchor({ offset = null, spin = 0, parentRotation = null } = {}) {
  const parent = new THREE.Group()
  if (parentRotation) parent.quaternion.copy(parentRotation)

  // 局部盒: 面内 ±1, 薄轴(Z) ±0.015015 —— 与真实 accessor 的 min/max 一致
  const source = new THREE.BoxGeometry(2, 2, (492 / SHORT_MAX) * 2)
  const floats = source.attributes.position.array
  const shorts = new Int16Array(floats.length)
  for (let i = 0; i < floats.length; i += 1) shorts[i] = Math.round(floats[i] * SHORT_MAX)

  const geometry = new THREE.BufferGeometry()
  geometry.setIndex(source.getIndex())
  geometry.setAttribute('position', new THREE.BufferAttribute(shorts, 3, true))
  source.dispose()

  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial())
  mesh.scale.setScalar(DEQUANT_SCALE)
  // 局部 +Z(薄轴) → 父空间 +Y, 与真实锚点同款的轴置换
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 1, 0))
  if (spin) {
    // 绕薄轴自转: 板面内转, 父空间 AABB 会膨胀, 但局部实测必须纹丝不动
    mesh.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), spin))
  }
  if (offset) mesh.position.copy(offset)

  parent.add(mesh)
  parent.updateMatrixWorld(true)
  return { parent, mesh }
}

/** 一个对象子树在世界空间的实际尺寸(逐顶点, 精确模式)。 */
export function worldSize(object) {
  return new THREE.Box3().setFromObject(object, true).getSize(new THREE.Vector3())
}
