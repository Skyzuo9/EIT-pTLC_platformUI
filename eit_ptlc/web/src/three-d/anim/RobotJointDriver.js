/**
 * 唯一的 CR5 关节写入层：Studio 离线片段和 Twin 实时反馈都只经过这里。
 *
 * 关节节点是官方链中的单位 ROTOR，轴定义在节点局部坐标中。因此旋转必须后乘到
 * 加载时四元数；前乘会把 local-Z 当成父/世界轴，正是旧模型扭曲和绕错轴的来源。
 */
import * as THREE from 'three'

const TMP_QUAT = new THREE.Quaternion()

/** 取与 reference 等价且最近的角，跨 +/-180 时保持连续。 */
export function unwrapAngleDeg(value, reference) {
  if (!Number.isFinite(reference)) return value
  return reference + ((((value - reference) + 180) % 360) + 360) % 360 - 180
}

export class RobotJointDriver {
  /**
   * @param {object} robotSpec device-manifest.robot
   * @param {(path: string) => THREE.Object3D|undefined} resolve 节点解析器
   */
  constructor(robotSpec, resolve) {
    this.spec = robotSpec || {}
    this.joints = []
    this.missing = []

    for (const joint of this.spec.joints || []) {
      const node = resolve(joint.node)
      if (!node) {
        this.missing.push(joint.node)
        continue
      }
      this.joints.push({
        spec: joint,
        node,
        axis: new THREE.Vector3(...(joint.axis || [0, 1, 0])).normalize(),
        baseQuat: node.quaternion.clone(),
        controllerDeg: Number.NaN,
      })
    }
  }

  /**
   * 写控制器六轴绝对角。continuous 仅选择等价周次，不会累加旋转。
   * @param {Array<number|null>} degrees
   * @param {{continuous?: boolean}} [options]
   */
  setJointsDeg(degrees, options = {}) {
    const continuous = options.continuous !== false
    let changed = false
    for (let index = 0; index < this.joints.length; index += 1) {
      const raw = degrees?.[index]
      if (!Number.isFinite(raw)) continue
      const joint = this.joints[index]
      const controllerDeg = continuous ? unwrapAngleDeg(raw, joint.controllerDeg) : raw
      const sign = Number(joint.spec.sign ?? 1)
      const offset = Number(joint.spec.zeroOffsetDeg ?? 0)
      const modelDeg = controllerDeg * sign + offset
      const limit = joint.spec.limitDeg
      if (Array.isArray(limit) && limit.length === 2 && (modelDeg < limit[0] - 1e-6 || modelDeg > limit[1] + 1e-6)) {
        console.warn(`[robot] ${joint.spec.id} 越限，冻结该轴: ${modelDeg.toFixed(3)}°`, limit)
        continue
      }
      TMP_QUAT.setFromAxisAngle(joint.axis, THREE.MathUtils.degToRad(modelDeg))
      joint.node.quaternion.copy(joint.baseQuat).multiply(TMP_QUAT)
      changed = changed || !Number.isFinite(joint.controllerDeg)
        || Math.abs(joint.controllerDeg - controllerDeg) > 1e-9
      joint.controllerDeg = controllerDeg
    }
    return changed
  }

  home() {
    for (const joint of this.joints) {
      const offset = Number(joint.spec.zeroOffsetDeg ?? 0)
      TMP_QUAT.setFromAxisAngle(joint.axis, THREE.MathUtils.degToRad(offset))
      joint.node.quaternion.copy(joint.baseQuat).multiply(TMP_QUAT)
      joint.controllerDeg = 0
    }
  }
}
