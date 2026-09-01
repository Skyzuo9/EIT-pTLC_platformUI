/**
 * 功能: 流程片段步骤 -> 工位的推导纯函数.
 *
 * 背景: compileClip 产出的 steps 丢掉了 `do` 载荷, 所以"现在哪个工位在动"
 * 必须留着 parseClip 的原始 doc, 按 do 的原语类型反查:
 *   axis            -> manifest.axes[].station
 *   robot_point / tool / joints / attach / detach -> ROBOT(机械臂在取放)
 *   actuator / linkage / node / light -> 该原语的节点路径里最后一个 ST_* 段
 *   liquid          -> 展缸(DEVELOP) 或注射泵(PUMP)
 *   camera / wait / state / plate -> null(不指向工位)
 * 零依赖(不碰 three/DOM), node --test 直接覆盖.
 */

/**
 * 工位显示别名: 地轨并入机械臂组(第三轮用户定夺) —— stationOfStep 仍按模型层
 * 返回 RAIL, 消费端(clipMode 分发/卡片路由)经本表折算到显示工位.
 */
export const STATION_ALIAS = { RAIL: 'ROBOT' }

/**
 * 功能: 从节点路径推工位 —— 取路径里最后一个能对上工位根名的 ST_* 段.
 * (机械臂的路径形如 ST_RAIL/.../ST_ROBOT/..., 取最后一个才不会误归地轨.)
 * @param {string} path 节点路径
 * @param {Map<string, string>} rootToStation ST_* 根名 -> 工位 id
 * @returns {string|null} 工位 id
 */
function stationFromPath(path, rootToStation) {
  if (!path) return null
  let found = null
  for (const segment of String(path).split('/')) {
    const hit = rootToStation.get(segment)
    if (hit) found = hit
  }
  return found
}

/**
 * 功能: 预建各原语 id -> 工位的查找表.
 * @param {object} manifest device-manifest JSON
 * @returns {object} lookup(交给 stationOfStep 用)
 */
export function buildStationLookup(manifest) {
  const rootToStation = new Map()
  for (const station of manifest.stations || []) {
    const leaf = (station.glbNode || '').split('/').pop()
    if (leaf) rootToStation.set(leaf, station.id)
  }

  const axisStation = {}
  for (const axis of manifest.axes || []) {
    if (axis.id && axis.station) axisStation[axis.id] = String(axis.station).toUpperCase()
  }

  const nodeOfId = {}
  for (const actuator of manifest.actuators || []) nodeOfId[`actuator:${actuator.id}`] = actuator.node
  for (const linkage of manifest.linkages || []) {
    nodeOfId[`linkage:${linkage.id}`] = linkage.members?.[0]?.node || ''
  }
  for (const light of manifest.lights || []) nodeOfId[`light:${light.id}`] = light.glbNode

  const liquidStation = {}
  for (const tank of manifest.tanks || []) {
    if (tank.id) liquidStation[tank.id] = stationFromPath(tank.glbNode, rootToStation) || 'DEVELOP'
  }
  for (const pump of manifest.pumpSyringe?.pumps || []) {
    if (pump.id) liquidStation[pump.id] = String(pump.station || 'PUMP').toUpperCase()
  }

  return { rootToStation, axisStation, nodeOfId, liquidStation }
}

/**
 * 功能: 片段第 index 步指向哪个工位.
 * @param {object} doc parseClip 的原始文档(steps[].do 仍在)
 * @param {number} index 步序号
 * @param {object} lookup buildStationLookup 的产物
 * @returns {string|null} 工位 id
 */
export function stationOfStep(doc, index, lookup) {
  const step = doc?.steps?.[index]
  const action = step?.do
  if (!action) return null

  if (action.axis) return lookup.axisStation[action.axis.id] || null
  if (action.robot_point || action.tool || action.joints || action.attach || action.detach) return 'ROBOT'
  if (action.actuator) return stationFromPath(lookup.nodeOfId[`actuator:${action.actuator.id}`], lookup.rootToStation)
  if (action.linkage) return stationFromPath(lookup.nodeOfId[`linkage:${action.linkage.id}`], lookup.rootToStation)
  if (action.light) return stationFromPath(lookup.nodeOfId[`light:${action.light.id}`], lookup.rootToStation)
  if (action.node) return stationFromPath(action.node.name, lookup.rootToStation)
  if (action.liquid) return lookup.liquidStation[action.liquid.id] || 'DEVELOP'
  return null // camera / wait / state / plate: 不指向工位
}
