/**
 * 功能: 卡片锚点的"顶部带加权中心"纯函数.
 *
 * 病根(第一轮实拍): 锚点取"整工位包围盒的 xz 中心 + 盒顶 y" —— 当工位的高结构
 * 偏在一角(如收集工位: 底盘占满 xz 而立柱只在一端), 这个点必然悬在空处.
 * 订正: 只用**顶面落在最高点向下一条带内**的网格求 xz 加权中心 —— 锚点自然落在
 * "看起来最高的那个东西"头顶上. 零依赖, node --test 直接覆盖.
 */

/**
 * 功能: 求一批盒子的顶部带加权锚点.
 *
 * @param {Array<{min: number[], max: number[]}>} boxes 各网格的包围盒([x,y,z] 数组)
 * @param {number} [band=0.28] 顶部带占总高的比例(至少 2cm, 防薄工位取空)
 * @returns {{x: number, z: number, topY: number}|null} 锚点(与输入同一坐标系); 空输入返回 null
 */
export function topBandAnchor(boxes, band = 0.28) {
  let maxY = -Infinity
  let minY = Infinity
  for (const box of boxes || []) {
    if (!box) continue
    if (box.max[1] > maxY) maxY = box.max[1]
    if (box.min[1] < minY) minY = box.min[1]
  }
  if (!Number.isFinite(maxY) || !Number.isFinite(minY)) return null

  const height = Math.max(maxY - minY, 1e-6)
  const cut = maxY - Math.max(height * band, 0.02)

  let weightSum = 0
  let x = 0
  let z = 0
  for (const box of boxes) {
    if (!box || box.max[1] < cut) continue
    // 权重 = footprint 面积: 大结构说话声音大, 螺丝钉这类小件噪声被稀释
    const weight = Math.max((box.max[0] - box.min[0]) * (box.max[2] - box.min[2]), 1e-8)
    x += ((box.min[0] + box.max[0]) / 2) * weight
    z += ((box.min[2] + box.max[2]) / 2) * weight
    weightSum += weight
  }
  if (weightSum <= 0) return null
  return { x: x / weightSum, z: z / weightSum, topY: maxY }
}
