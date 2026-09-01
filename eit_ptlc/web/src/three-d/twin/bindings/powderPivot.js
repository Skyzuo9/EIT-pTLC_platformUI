/**
 * 功能: 粉桶内粉柱的**落点**与体积换算 —— 纯函数, 不碰场景图之外的任何状态.
 *
 * 与液面的三处不同, 每一处都决定了为什么不能直接复用 liquidPivot:
 *
 *   1. **粉不流, 它被滤纸内衬拦在固定的一端。** 粉是抽吸进桶、由内衬拦住的, 堆在
 *      吹气头那一头(腔的 c1)。刮板工位那只挂在 ps_rotate 上翻料倒粉时转 180°, 粉
 *      **跟着桶转、相对桶纹丝不动** —— 于是落点是**常量端**, 不是液面那种"重力低端"。
 *      (液面盒既不翻转、也永远贴底, setLiquidMl 只写 scale.y。)
 *   2. **自由粉腔不是整根筒身。** GLB 实测(径向射线, 见 rig_map station_seats 的剖面表):
 *      针筒 item 局部 Y 的 −20…0 是**细吸嘴**不是筒身, 而滤芯是**空心管**、它的孔才是
 *      粉腔 ⇒ 唯一的等径通道是 [+5.0, +78.0] 这 73mm, 孔 Ø18.88。
 *   3. **单位是 mm³ 不是 mL。** 量的来源是"轮廓面积 × 切深 × 松散系数", 天生就是立方毫米。
 *      levelFromMm3 只做 1mL=1000mm³ 的换算后转调 levelFromMl, **不重写高度公式** ——
 *      同一条公式留两份正是 TankLiquidModel 头注反复警告的那类漂移。
 *
 * 枢轴补偿一层**完全复用** liquidPivot 的 captureLiquidBase/applyLiquidLevel:
 * 04_optimize 的 quantize 把粉柱枢轴挪到几何正中这件事会一模一样地发生, 而
 * measureLiquidPivot 对它免疫。这里只换 basePosition, 不重写缩放。
 *
 * 与 liquidPivot / TankLiquidModel 同一条理由提成模块级纯函数: 实时链
 * (TwinBindings._updateConsumablePowders) 与离线链(anim/MachineStateDriver 的 powder
 * 通道)必须写出**逐位相同**的几何, 否则同一条动作在演示页与实况页高低不一,
 * 而两边都看着挺正常。
 */
import * as THREE from 'three'

import { levelFromMl } from './TankLiquidModel.js'
import { applyLiquidLevel, applyLiquidVisible } from './liquidPivot.js'

/** 复用的临时量: 本模块调用都是同步的, 不可重入, 安全 */
const TMP_BASE = new THREE.Vector3()

/**
 * 功能: 体积(mm³) -> 液位比 0~1. levelFromMl 的粉末孪生.
 *
 * **转调而不是重写**: 高度公式 (体积 / 自由截面积 / 可用深, 带观感放大与封顶) 只能有
 * 一份实现。这里只负责 1 mL = 1000 mm³ 这一步换算。
 *
 * ⚠ cavity 必须是**粉桶的** cavity —— manifest 里粉末那份的容量键故意叫
 *   capacityMm3 / mm3PerMm 而不是 capacityMl / mlPerMm, 就是为了让"把 mm³ 喂进
 *   levelFromMl"这种错立刻表现成 NaN 而不是悄悄画错高度。
 *
 * @param {object} cavity 需含 usableDepthMm / freeAreaMm2
 * @param {number} volumeMm3 体积 mm³
 * @param {number} [exaggeration] 观感放大系数; 面板显示的 mm³ 不受它影响
 * @returns {number} 0~1
 */
export function levelFromMm3(cavity, volumeMm3, exaggeration = 1) {
  const mm3 = Number(volumeMm3)
  if (!Number.isFinite(mm3)) return 0
  return levelFromMl(cavity, Math.max(0, mm3) / 1000, exaggeration)
}

/**
 * 功能: 粉柱**底面**在 item 局部系里的轴向坐标(米). 纯标量, 不碰 three 对象.
 *
 * 关键设计: **占位区间的上端恒等于 c1**, 粉从吹气头那一头往回长:
 *
 *     占位区间恒为 [c1 − h, c1],  h = (c1 − c0) × level
 *
 * 三条恒等式(单测逐条锁死):
 *   level = 0 ⇒ 占位 [c1, c1]                        空桶, 退化成零厚
 *   level = 1 ⇒ 占位 [c0, c1]                        满腔
 *   ∀level∈[0,1] ⇒ [c1−h, c1] ⊆ [c0, c1]            由构造保证, 永不穿出腔外
 *
 * 与桶的姿态**无关**: 粉被滤纸内衬拦在 c1 那一端, 翻料倒粉转 180° 时粉跟着桶一起转、
 * 相对桶不动。于是"声明腔长 ≥ 可用深"是建模期唯一需要的守卫(与 build_station_bottle_liquid
 * 同款), 运行期不需要任何姿态输入。
 *
 * @param {{c0: number, c1: number}} chamber 腔段(item 局部 Y, 米; c0 < c1)
 * @param {number} level 0~1
 * @returns {number} 底面轴向坐标(米)
 */
export function powderBaseAxial(chamber, level) {
  const c0 = Number(chamber?.c0)
  const c1 = Number(chamber?.c1)
  if (!Number.isFinite(c0) || !Number.isFinite(c1) || c1 <= c0) return 0
  return c1 - (c1 - c0) * Math.max(0, Math.min(1, Number(level) || 0))
}

/**
 * 功能: 写一根粉柱的位姿 —— 复用 applyLiquidLevel 的枢轴补偿, 只换 basePosition.
 *
 * **刻意不写 quaternion**: 粉柱与筒同轴, 任意倾角都不会穿壁。若强行让粉面保持世界水平
 * (setFromUnitVectors(+Y, -gLocal)), 在正好 90° 时 Ø18.4 孔里一根 r=9.2 / h=17.3 的圆柱,
 * 角点半径 √(9.2²+8.65²)=12.6 > 9.2, 会戳出内衬孔外 —— alpha 0.64 的半透明桶壁藏不住。
 *
 * applyLiquidLevel 把"基准底面"钉在 basePosition + baseMinY, 故这里传
 * basePosition.y = y0 − baseMinY, 钉住的正好是 y0。
 *
 * @param {object} base captureLiquidBase(node) 的产物(须含 baseScale/basePosition/baseMinY)
 * @param {THREE.Object3D} node 粉柱节点
 * @param {{c0: number, c1: number}} chamber 腔段(item 局部 Y, 米)
 * @param {number} level 0~1
 * @returns {void}
 */
export function applyPowderColumn(base, node, chamber, level) {
  const y0 = powderBaseAxial(chamber, level)
  TMP_BASE.set(base.basePosition.x, y0 - base.baseMinY, base.basePosition.z)
  applyLiquidLevel({ ...base, basePosition: TMP_BASE }, node, level)
  applyLiquidVisible(node, level)
}

/**
 * 功能: 从物料账本的一格算出该件里有多少内容物 —— 两条链共用的**同一份回退梯**.
 *
 * 有序回退(先到先得):
 *   1. 账本直给 (powder_mm3 / liquid_ml) —— 后端按 视觉轮廓面积×切深×松散系数 估出来的
 *   2. 现算 (band_area_mm2 × cut_depth_mm × bulkFactor) —— 账本还没这一列时的过渡路径
 *   3. 标称值 —— 只在"有料"(FRESH 或带样品号)时给, 否则 0
 *
 * 提成纯函数而不是各写各的: 实时链吃 WS 账本、离线链吃片段通道值, 但"这一格该显示多少"
 * 只能有一份规则 —— 它漂了的表现是"演示里桶满着, 实况页桶是空的", 没有任何指标会报警。
 *
 * @param {object} cell grid().cells 的一行(经 MaterialStateStore.normalizeSnapshot 归一)
 * @param {object} kindSpec manifest.consumableContents.kinds[kind]
 * @returns {number} 内容物量 (粉 mm³ / 液 mL, 由 kindSpec.kind 决定)
 */
export function contentAmount(cell, kindSpec) {
  if (!cell || !kindSpec) return 0
  const isPowder = kindSpec.kind === 'powder'
  const ledger = Number(isPowder ? cell.powder_mm3 : cell.liquid_ml)
  if (Number.isFinite(ledger) && ledger > 0) return ledger

  if (isPowder) {
    const area = Number(cell.band_area_mm2)
    const depth = Number(cell.cut_depth_mm)
    if (area > 0 && depth > 0) return area * depth * (Number(kindSpec.bulkFactor) || 1)
  }
  const nominal = Number(isPowder ? kindSpec.nominalMm3 : kindSpec.nominalMl)
  if (!(nominal > 0)) return 0
  const hasStock = cell.state === 'FRESH' || Boolean(cell.sample_id)
  return hasStock ? nominal : 0
}
