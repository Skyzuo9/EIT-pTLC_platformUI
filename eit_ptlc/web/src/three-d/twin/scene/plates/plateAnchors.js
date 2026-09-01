/**
 * 功能: 从场景节点索引里解析 13 个薄层板落点的实测位姿, 以及吸盘翻转节点.
 *
 * 为什么单独成模块: **两条链都要它**, 而且必须是同一份规则 ——
 *   实时页 PlateBinding 按调度器账本把板摆到落点;
 *   动作页 PlateStage 按片段里的 `plate` 原语把板摆到落点。
 * 缸号"按 parent 名反查"那条纪律(见 PlateSlots.resolveAnchors 的警告)一旦两处各写
 * 一份, 迟早有一处被改错 —— 而错了画面照样"看起来很真", 只是每块板都躺错缸。
 */
import { isSilicaUp, resolveAnchors } from '../../bindings/PlateSlots.js'
import { measurePlateAnchor } from './plateGeometry.js'

/** 翻转气缸的机构 id; 板挂在它的几何节点下就自动跟着翻。 */
export const FLIP_ACTUATOR_ID = 'rob_flip_suction'

/**
 * 功能: 解析全部板锚点, 实测尺寸后把 CAD 盒子隐藏起来只当位姿来源.
 *
 * @param {Map<string, import('three').Object3D>} nodeIndex loadModel 建的节点索引
 * @returns {{anchors: Map<string, object>, missing: string[], nodes: import('three').Object3D[]}}
 *          落点 -> 实测几何; 未解析到的落点; 以及被隐藏掉的那些 CAD 盒本身
 *          (接触判据要把它们排除在可碰几何之外 —— 拿看不见的东西去顶板, 现象无从解释)
 */
export function bindPlateAnchors(nodeIndex) {
  const descriptors = []
  for (const [path, node] of (nodeIndex || new Map()).entries()) {
    descriptors.push({
      path,
      name: node?.userData?.origName || node?.name || '',
      parentName: node?.parent?.userData?.origName || node?.parent?.name || '',
    })
  }
  const { anchors: paths, missing } = resolveAnchors(descriptors)

  const anchors = new Map()
  const unresolved = [...missing]
  const nodes = []
  for (const [slot, path] of paths.entries()) {
    const node = nodeIndex.get(path)
    const geom = measurePlateAnchor(node)
    if (!geom) {
      unresolved.push(slot)
      continue
    }
    // 硅胶朝哪面是**落点语义**(取放动作的 rotary 态), CAD 的对称长方体本身表达不了
    geom.silicaUp = isSilicaUp(slot)
    node.visible = false          // 只留位姿, 真正的板由 PlateFaceLayer 程序化生成
    anchors.set(slot, geom)
    nodes.push(node)
  }
  return { anchors, missing: unresolved, nodes }
}

/**
 * 功能: 解析吸盘翻转节点(板挂它下面就随 rob_flip_suction 同步反转).
 * @param {object} manifest device-manifest
 * @param {Map<string, import('three').Object3D>} nodeIndex 节点索引
 * @returns {import('three').Object3D|null} 翻转节点
 */
export function findFlipSuctionNode(manifest, nodeIndex) {
  const spec = (manifest?.actuators || []).find((item) => item.id === FLIP_ACTUATOR_ID)
  if (!spec?.node) return null
  return nodeIndex?.get(spec.node) || null
}

/**
 * 功能: 读取"板相对吸盘"的实测刚体常量(管线产出, 见 gen_twin_manifest.resolve_plate_grip).
 *
 * 读不到就返回 null —— 调用方据此退回旧的"保世界位姿换父", 于是老 manifest 仍能加载,
 * 只是回到"每站带各自示教残差"的老行为, 不会崩也不会画错位置。
 *
 * @param {object} manifest device-manifest
 * @returns {object|null} plateGrip 块
 */
export function readPlateGrip(manifest) {
  const spec = (manifest?.actuators || []).find((item) => item.id === FLIP_ACTUATOR_ID)
  return spec?.plateGrip || null
}
