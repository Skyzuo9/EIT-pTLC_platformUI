/**
 * 功能: 带耦合约束的联动组运动学 —— 由**一个**主参数解出全部成员的输出行程.
 *
 * 为什么需要这一层: 一般联动组(双侧夹爪)的成员是对称的, 改一个行程套给所有成员
 * 就对. 但展缸盖这类机构的成员被几何锁死 —— 摆角 θ、盖抬升 h、滑车行程 s 三者
 * 由 |铰点−枢轴| = R 一条约束联系, 只有一个自由度. 分别调会让盖与摆臂脱节
 * (现象: 连接处错位), 所以动作页只暴露主参数, 其余由这里解算.
 *
 * 公式与 pipeline/gen_twin_manifest.solve_lid_kinematics 完全一致, 改一处必须
 * 同步改另一处(两侧各有回归测试锁着).
 */

/** 曲柄滑块提盖: 摆臂上端随滑车水平走, 下端铰在只能竖直升降的盖上 */
export const CRANK_SLIDER_LIFT = 'crank-slider-lift'

/**
 * 功能: 由盖抬升解出滑车行程与摆角.
 * @param {object} kin manifest linkage.kinematics
 * @param {number} liftMm 盖抬升(mm)
 * @returns {{liftMm: number, travelMm: number, thetaDeg: number}} 解
 * @throws {Error} 越出 [minLiftMm, maxLiftMm]
 */
export function solveLift(kin, liftMm) {
  const d0 = Number(kin?.d0Mm)
  const v0 = Number(kin?.v0Mm)
  const radius = Number(kin?.radiusMm)
  if (![d0, v0, radius].every(Number.isFinite)) throw new Error('kinematics 缺 d0Mm/v0Mm/radiusMm')
  const lift = Number(liftMm)
  const maxLift = Number(kin.maxLiftMm)
  const minLift = Number(kin.minLiftMm ?? 0)
  if (!Number.isFinite(lift)) throw new Error('抬升必须是数字')
  if (lift < minLift || lift > maxLift) {
    throw new Error(`抬升 ${lift}mm 越界 [${minLift}, ${maxLift}]mm`)
  }
  const travelMm = Math.sqrt(Math.max(radius ** 2 - (v0 - lift) ** 2, 0)) - d0
  const thetaDeg =
    (Math.asin((d0 + travelMm) / radius) - Math.asin(d0 / radius)) * (180 / Math.PI)
  return { liftMm: lift, travelMm, thetaDeg }
}

/**
 * 功能: 把主参数摊成与 members 同序的 outputRange 数组.
 *
 * 反相语义(值 1=关盖=GLB 基准态)由 [行程, 0] 的降序区间表达, 与 rig_map 一致.
 *
 * @param {object} kin manifest linkage.kinematics(含 roles)
 * @param {number} liftMm 盖抬升(mm)
 * @returns {number[][]} 每个成员的 outputRange
 */
export function outputRangesForLift(kin, liftMm) {
  const { thetaDeg, travelMm, liftMm: lift } = solveLift(kin, liftMm)
  const byRole = { rocker: thetaDeg, lid: lift, carriage: travelMm }
  return (kin.roles || []).map((role) => {
    if (!(role in byRole)) throw new Error(`未知成员角色 ${role}`)
    return [Number(byRole[role].toFixed(2)), 0]
  })
}

/**
 * 功能: 主参数的展示元信息(UI 用).
 * @param {object} kin manifest linkage.kinematics
 * @returns {{label: string, unit: string, min: number, max: number, step: number}|null}
 */
export function primaryParam(kin) {
  if (kin?.model !== CRANK_SLIDER_LIFT) return null
  return {
    key: 'liftMm',
    label: '盖抬升',
    unit: 'mm',
    min: Number(kin.minLiftMm ?? 0),
    max: Number(kin.maxLiftMm),
    step: 1,
  }
}
