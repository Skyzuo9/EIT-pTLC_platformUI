/**
 * 功能: 设备侧枚举值的中文标签 —— 二维页与三维页共用的**唯一**一份.
 *
 * 建这个文件的理由是仓里同一张表被抄了好几份且措辞已经分叉:
 *   健康态  ExplorerDock {busy:'忙碌', error:'故障'} / NodeDetail {busy:'忙碌', error:'错误'}
 *           / StationPanel {busy:'运行中', error:'故障'}  —— 三份三种写法
 *   MODE_State  StationManualPanel 与 CalibratePanel 各一份(内容相同, 但会各自漂)
 *   地轨站位    只在 StatusBar 里, 三维的工位一句话概述也要用
 * 定案取 StationPanel 那一套(busy=运行中 / error=故障), 因为"忙碌"在中文语境里
 * 更像"没空", 而这里的语义是"正在执行动作"; unknown 一档必须有, 否则遥测还没到的
 * 那几秒会把 undefined 直接印到界面上。
 *
 * 只放**值→中文**的死表, 不放任何取数逻辑 —— 谁去读 PLC、读哪个字段, 是调用方的事。
 */

/**
 * 设备节点健康度(后端 runtime/node_registry.derive_health 的闭集).
 * 纯色圆点对读屏与色弱不可辨, 所以每个点旁都要补这段文字.
 */
export const HEALTH_TEXT = Object.freeze({
  ok: '正常',
  busy: '运行中',
  error: '故障',
  offline: '离线',
  unknown: '未知',
})

/**
 * 功能: 取健康度中文; 未知取值原样直出而不是吞成"正常"(骗人比不说更糟).
 * @param {string} health 健康度枚举值
 * @returns {string} 中文标签
 */
export function healthText(health) {
  return HEALTH_TEXT[health] || health || HEALTH_TEXT.unknown
}

/**
 * 由光电与账本是否对得上推出的**物料**健康度.
 *
 * 与 HEALTH_TEXT 刻意分开成两张表: 那张是后端 derive_health 的设备节点健康(连不连得上、
 * 有没有报警), 这张说的是"账本可不可信"。料架这类没有 PLC 遥测节点的工位只有后者。
 * 混成一张表会让二维设备页凭空多出一档它永远不会遇到的取值。
 */
export const MATERIAL_HEALTH_TEXT = Object.freeze({
  ok: '物料一致',
  mismatch: '帐实不一',
  unknown: '无可用光电',
})

/**
 * PLC 设备状态机 GVL.MODE_State.
 * 真源: config/manual_points.yaml globals.mode_state + controller/manual_service.py
 * (_MODE_RUNNING = 1; _SIGNAL_BY_MODE 按这五档点塔灯).
 */
export const MODE_STATE_LABEL = Object.freeze({
  0: '停止',
  1: '运行',
  2: '故障',
  3: '急停',
  4: '初始化',
})

/** MODE_State 里代表"整机正在跑"的那一档 —— 物料改账门禁认它 */
export const MODE_STATE_RUNNING = 1

/**
 * 功能: 把 MODE_State 渲染成"码 + 中文"(界面惯例是两个都给, 便于对着电柜核).
 * @param {number|null|undefined} value MODE_State 原值
 * @returns {string} 形如 "1 运行"; 无值时 "—"
 */
export function modeStateText(value) {
  if (value === undefined || value === null) return '—'
  return `${value} ${MODE_STATE_LABEL[value] ?? '未知'}`
}

/**
 * 地轨站位码 → 站名.
 * 来源 plc.rail 的 current_positions(后端据地轨实际位算出的命中站位码列表, 重位可多个).
 */
export const RAIL_STATION_NAMES = Object.freeze({
  1: '上样',
  2: '拍照',
  3: '收集',
  4: '工具',
  5: '展开',
  6: '仓库',
})

/**
 * 功能: 把 current_positions 数组渲染成一句站位描述.
 * @param {number[]|null|undefined} positions 命中站位码列表
 * @returns {string} 形如 "拍照" 或 "拍照/收集"; 空时 "—"
 */
export function railStationText(positions) {
  if (!Array.isArray(positions) || positions.length === 0) return '—'
  return positions.map((code) => RAIL_STATION_NAMES[code] ?? `位${code}`).join('/')
}
