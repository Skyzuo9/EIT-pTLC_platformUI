/**
 * 功能: 液面/液柱"底面钉住"的缩放 —— 枢轴测量、缩放+补偿写入、空缸显隐.
 *
 * ⚠ 枢轴补偿是一条**必须存在**的补偿, 不是可选优化 ——
 * 液面靠 `scale.y × level` 表示涨落, 而缩放是绕**枢轴**做的, 所以枢轴必须在底面。
 * blender_clean 里确实是按底面枢轴建的(`cyl(..., anchor="base")`), 但
 * `04_optimize.mjs` 的 `quantize({quantizePosition: 14})` 会把**每个网格归一化到以原点
 * 为中心的单位立方**, 再把偏移与缩放推到节点 TRS 上 —— 枢轴就此被挪到了几何正中。
 * 出厂 GLB 实测: 11 个 `LIQUID*` 节点的"枢轴在跨度中的比例"**全是 0.500**。
 * 于是缩放变成朝中心收缩, 现象是"液面悬在半空"外加"顶部糊进柱塞里"(2026-08-05 报障)。
 *
 * 柱塞/阀指针/丝杆不受影响, 是因为它们都是 `Empty + 网格子件`: quantize 只重定位子件、
 * 并在子件自己的 TRS 上补偿, 父 Empty 的枢轴原样保留。只有 `LIQUID*` 是裸网格。
 *
 * measureLiquidPivot 按**实际加载到的几何**量, 不假设枢轴在哪 —— 枢轴真在底面时返回 0,
 * 补偿恒为零、行为与改前逐位相同。因此它对 quantize 的行为免疫, 优化器再改也不会重新坏掉。
 *
 * 为什么整套提成模块级函数(与 levelFromMl 同一条理由, 见 TankLiquidModel.js 第 37~43 行):
 * 实时链(TwinBindings._updateTanks/_updatePumps)与离线链(anim/MachineStateDriver 的
 * liquid 通道)必须写出**逐位相同**的液面几何。2026-08-05 第一版补偿只落在实时链上,
 * 动作页/演示页照旧"往中心收缩"、排空后还剩一层 —— 那次漂移的根因就是"补偿只留了一份,
 * 另一条链压根没有"。现在连 entry 的三个基准字段都由 captureLiquidBase 统一发放。
 */
import * as THREE from 'three'

import { HIDE_OWNER, setHidden } from '../scene/visibilityIntent.js'

/**
 * 空缸时的最小缩放。
 *
 * 0 缩放会让法线矩阵退化(某些驱动上出黑面), 所以留一个下限而不是真的乘 0。
 * 它**不**负责"看不见"那件事 —— 压扁的盒子仍有一张满尺寸的不透明顶面, 见 applyLiquidVisible。
 * 下游 three_d/tools/visual_validation/verify_tank_liquid.py 的 EMPTY_RATIO 与本值同源。
 */
export const LIQUID_EMPTY_FACTOR = 1e-4

/** "还算看得见液"的判据: 低于它整体隐藏 */
export const LIQUID_VISIBLE_LEVEL = 0.005

/** 复用的临时向量: 本模块调用都是同步的, 不可重入, 安全 */
const TMP_VEC = new THREE.Vector3()

/**
 * 功能: 算出"液面底相对节点枢轴的偏移量"(父系单位), 供缩放时把底面钉住.
 *
 * @param {THREE.Object3D} node 液面节点(可能是裸网格, 也可能是带网格子件的空节点)
 * @returns {number} 底面相对枢轴的 y 偏移(已乘节点自身 scale.y); 无几何时为 0
 */
export function measureLiquidPivot(node) {
  node.updateMatrixWorld(true)
  const box = new THREE.Box3()
  const walk = (obj, matrix) => {
    if (obj.isMesh && obj.geometry) {
      obj.geometry.computeBoundingBox()
      if (obj.geometry.boundingBox) {
        box.union(obj.geometry.boundingBox.clone().applyMatrix4(matrix))
      }
    }
    for (const child of obj.children) {
      walk(child, new THREE.Matrix4().multiplyMatrices(matrix, child.matrix))
    }
  }
  // 起手是单位阵: node 自身的 TRS **不计入**, 这样量到的是"节点局部、未乘 scale"的跨度
  walk(node, new THREE.Matrix4())
  return box.isEmpty() ? 0 : box.min.y * node.scale.y
}

/**
 * 功能: 采集一处液面的"加载态基准" —— 三个字段必须成套.
 *
 * 缺 baseMinY 就是 2026-08-05 那个 bug 的形状, 所以不给调用方逐字段抄的机会。
 *
 * @param {THREE.Object3D} node 须处于加载态(还没被写过 scale/position)
 * @returns {{baseScale: THREE.Vector3, basePosition: THREE.Vector3, baseMinY: number}}
 */
export function captureLiquidBase(node) {
  return {
    baseScale: node.scale.clone(),
    basePosition: node.position.clone(),
    baseMinY: measureLiquidPivot(node),
  }
}

/**
 * 功能: 把液面节点缩放到 level 并把底面钉在原处.
 *
 * @param {object} base 基准(须含 baseScale/basePosition/baseMinY; captureLiquidBase 的产物)
 * @param {THREE.Object3D} node 液面节点
 * @param {number} level 0~1
 * @returns {void}
 */
export function applyLiquidLevel(base, node, level) {
  const factor = Math.max(level, LIQUID_EMPTY_FACTOR)
  node.scale.set(base.baseScale.x, base.baseScale.y * factor, base.baseScale.z)
  // 底面本应恒在 basePosition + baseMinY, 缩放后跑到了 basePosition + baseMinY×factor,
  // 差额沿节点自身 +Y 补回去(节点有旋转时也成立)
  TMP_VEC.set(0, base.baseMinY * (1 - factor), 0).applyQuaternion(node.quaternion)
  node.position.copy(base.basePosition).add(TMP_VEC)
}

/**
 * 功能: 还原到加载态 —— scale 与 position **必须成对**还原.
 *
 * 只还原 scale 的后果不是"差一点点": rig 每次改参/换模都重建, 重建时 captureLiquidBase
 * 会把"上一次的补偿位"当成新的 basePosition, 于是每重建一次就多偏一截, 越用越歪。
 *
 * @param {object} base captureLiquidBase 的产物
 * @param {THREE.Object3D} node 液面节点
 * @returns {void}
 */
export function restoreLiquidBase(base, node) {
  node.scale.copy(base.baseScale)
  node.position.copy(base.basePosition)
  // 摘掉本层登记的"空缸隐藏"; 别人(隔离/示意体开关)登记的隐藏仍然生效
  setHidden(node, HIDE_OWNER.EMPTY, false)
}

/**
 * 功能: 按液位登记/撤销"空缸隐藏"意图.
 *
 * 为什么必须隐藏而不是只把 scale 压到下限: 液面盒是实心盒, 压扁之后**顶面尺寸不变**
 * —— 展缸那只是 210 × 40 mm 的不透明面, 隔着玻璃缸看就是"排干净了还剩薄薄一层"
 * (2026-08-05 报障的第二个现象)。压得再扁也解决不了, 只能让它不进渲染。
 *
 * 走仲裁而不是直接写 `node.visible`: 用户在动作页隔离过零件之后, 液面盒是被
 * ViewTools 藏着的, 直接写会让它在下一次注液时自己弹回画面。见 visibilityIntent.js。
 *
 * @param {THREE.Object3D} node 液面节点
 * @param {number} level 0~1
 * @returns {void}
 */
export function applyLiquidVisible(node, level) {
  setHidden(node, HIDE_OWNER.EMPTY, !(level > LIQUID_VISIBLE_LEVEL))
}
