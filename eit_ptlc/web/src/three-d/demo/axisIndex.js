/**
 * 功能: 由 manifest 派生「PLC 示教点 → 三维轴」的对照, 替代手工维护的对照表.
 *
 * 判据不是约定, 是**数据自证**的:
 *
 *   点位的 `actpos` 字段(该点位对应的实际位置反馈节点名)
 *     ===
 *   manifest.axes[].telemetry.key(该轴的实时反馈节点名)
 *
 * 两边说的是同一个 PLC 节点, 所以 join 一下就得到"这个点位是在给哪根轴下目标"。实测:
 *
 *   photo_8y          Photo_8Y_ActPos      -> axis_8y
 *   spot_pose.x_start Spot_6X_ActPos       -> axis_6x
 *   spot_pose.y_height Spot_7Y_ActPos      -> axis_7y
 *   feedlift_1z_*     FeedLift_1Z_ActPos   -> axis_1z
 *   sampling_4x*      Sampling_4X_ActPos   -> axis_4x
 *
 * 为什么不写一张手工表: 点位会随现场示教增删(sample_5z 现在还是 pending 占位), 而手工表
 * 漏一条的表现是"这个动作忽然说无法模拟", 多一条的表现是"驱错了轴" —— 两种都没有自动
 * 指标会报警。派生则是漏了就没有, 不会错。
 *
 * 地轨是唯一的例外: 它的点位挂在 HMI 数组节点上(node: HMI_地轨轴11Y), **没有 actpos**,
 * 按 slot 走 actionSim 里的既有路径。
 *
 * 零依赖纯函数, 可 node --test.
 */

/** manifest 对象 -> 派生表. manifest 是构建产物, 同一份对象重复问就直接命中 */
const cache = new WeakMap()

/**
 * 功能: 建 actpos 节点名 -> 轴 id 的对照.
 * @param {object} manifest device-manifest
 * @returns {Map<string, string>} actpos -> axisId
 */
export function buildAxisByTelemetry(manifest) {
  if (!manifest || typeof manifest !== 'object') return new Map()
  const hit = cache.get(manifest)
  if (hit) return hit
  const index = new Map()
  for (const axis of manifest.axes || []) {
    const key = axis?.telemetry?.key
    if (typeof key === 'string' && key && axis.id) index.set(key, axis.id)
  }
  cache.set(manifest, index)
  return index
}

/**
 * 功能: 一个点位(或复合点成员)对应哪根轴.
 * @param {object} manifest device-manifest
 * @param {object} point 点位条目(indexServoPoints 产物的值, 或复合点的一个成员)
 * @returns {string} 轴 id; 派生不出返回空串
 */
export function axisOfPoint(manifest, point) {
  const actpos = point?.actpos
  if (typeof actpos !== 'string' || !actpos) return ''
  return buildAxisByTelemetry(manifest).get(actpos) || ''
}
