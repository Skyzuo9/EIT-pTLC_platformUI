/**
 * 功能: device-manifest.json 的加载、校验与查询辅助.
 *
 * manifest 是三维模型与上位机实时数据之间的唯一绑定契约: 它把"工位/轴/展缸"这些
 * 控制系统概念, 映射到 GLB 里的具体节点路径. 前端不应在别处硬编码任何节点名.
 */

/** manifest 必须具备的顶层字段 */
const REQUIRED_FIELDS = ['stations', 'axes', 'tanks']

/**
 * 功能: 加载并校验 manifest.
 * @param {string} [url='/api/3d/assets/models/device-manifest.json'] manifest 地址
 * @returns {Promise<object>} manifest 内容
 * @throws {Error} 网络失败或结构不合法时抛出
 */
export async function loadManifest(url = '/api/3d/assets/models/device-manifest.json') {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`加载 device-manifest 失败: HTTP ${response.status} (${url})`)
  }
  const manifest = await response.json()

  const missing = REQUIRED_FIELDS.filter((field) => !Array.isArray(manifest[field]))
  if (missing.length) {
    throw new Error(`device-manifest 结构不完整, 缺少字段: ${missing.join(', ')}`)
  }
  return manifest
}

/**
 * 功能: 按工位 id 取工位定义.
 * @param {object} manifest manifest 内容
 * @param {string} stationId 工位 id, 如 "DEVELOP"
 * @returns {object|undefined} 工位定义
 */
export function stationById(manifest, stationId) {
  return (manifest.stations || []).find((station) => station.id === stationId)
}

/**
 * 功能: 按上位机节点 id 取工位定义(遥测事件里给的是节点 id).
 * @param {object} manifest manifest 内容
 * @param {string} nodeId 节点 id, 如 "plc.develop"
 * @returns {object|undefined} 工位定义
 */
export function stationByNodeId(manifest, nodeId) {
  return (manifest.stations || []).find((station) => station.nodeId === nodeId)
}

/**
 * 功能: 反查一个动作名属于哪个工位.
 * @param {object} manifest manifest 内容
 * @param {string} actionName 动作全名, 如 "develop.drain"
 * @returns {object|undefined} 工位定义
 */
export function stationForAction(manifest, actionName) {
  return (manifest.stations || []).find((station) =>
    (station.actionPrefixes || []).some((prefix) => actionName.startsWith(prefix)),
  )
}

/**
 * 功能: 取某工位下的所有运动轴.
 * @param {object} manifest manifest 内容
 * @param {string} stationId 工位 id
 * @returns {object[]} 轴定义数组
 */
export function axesOfStation(manifest, stationId) {
  return (manifest.axes || []).filter((axis) => axis.station === stationId)
}

/**
 * 功能: 取某工位下的**单点控制轴**(manifest.realtime.axes).
 *
 * ⚠ 与 axesOfStation 是两张不同的表: 那张是三维绑定用的 axes[](station 为大写 id),
 *   这张是单点控制用的 realtime.axes[](station 是上位机小写 key, 与 manual_points.yaml
 *   逐字一致). 工位 id 空间在本仓有七套并存, 这个大小写差过去让人踩过坑, 故显式收口在此.
 * @param {object} manifest manifest 内容
 * @param {string} stationId 三维工位 id(大写)
 * @returns {object[]} 轴定义数组
 */
export function realtimeAxesOfStation(manifest, stationId) {
  const key = String(stationId || '').toUpperCase()
  return (manifest?.realtime?.axes || []).filter(
    (axis) => String(axis.station || '').toUpperCase() === key,
  )
}

/**
 * 功能: 取某工位下的执行器(manifest.realtime.mechanisms).
 * @param {object} manifest manifest 内容
 * @param {string} stationId 三维工位 id(大写)
 * @returns {object[]} 机构定义数组
 */
export function mechanismsOfStation(manifest, stationId) {
  const key = String(stationId || '').toUpperCase()
  return (manifest?.realtime?.mechanisms || []).filter(
    (mech) => String(mech.station || '').toUpperCase() === key,
  )
}

/**
 * 功能: 把带 station 的实时条目按 manifest.stations 顺序分组(手动控制面板用).
 *
 * realtime.axes/mechanisms 的 station 是上位机小写 key(如 "sampling"), 与
 * stations[].id 只差大小写; 组顺序跟随 stations 数组(与左侧工位列表一致),
 * 匹配不上的条目归入"其他"垫底, 空组剔除.
 * @param {object} manifest manifest 内容
 * @param {object[]} rows 带 station 字段的条目数组
 * @returns {{id: string, label: string, items: object[]}[]} 非空分组
 */
export function groupRowsByStation(manifest, rows) {
  const groups = (manifest?.stations || []).map((station) => ({
    id: station.id,
    label: station.label || station.id,
    items: [],
  }))
  const byId = new Map(groups.map((group) => [group.id, group]))
  const rest = { id: 'OTHER', label: '其他', items: [] }
  for (const row of rows || []) {
    const key = String(row?.station || '').toUpperCase()
    ;(byId.get(key) || rest).items.push(row)
  }
  return [...groups, rest].filter((group) => group.items.length > 0)
}

/**
 * 功能: 统计 manifest 的装配完成度, 用于在界面上提示还有多少轴没接上.
 * @param {object} manifest manifest 内容
 * @returns {{stations: number, tanks: number, axes: number, axesRigged: number, lights: number}}
 *          各项计数
 */
export function manifestSummary(manifest) {
  const axes = manifest.axes || []
  return {
    stations: (manifest.stations || []).length,
    tanks: (manifest.tanks || []).length,
    axes: axes.length,
    axesRigged: axes.filter((axis) => axis.rigged).length,
    realtimeAxes: (manifest.realtime?.axes || []).length,
    realtimeMechanisms: (manifest.realtime?.mechanisms || []).length,
    lights: (manifest.stations || []).filter((station) => station.statusLight).length,
    signalLight: Boolean(manifest.signalLight?.glbNode),
  }
}
