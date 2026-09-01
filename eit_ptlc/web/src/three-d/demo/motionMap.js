/**
 * 功能: 动作 → 三维机构映射表的加载与查表 —— 单一真源在 Python 侧.
 *
 * 表本身(哪个动作驱动哪根轴到多少毫米、哪个动作是气缸、哪些动作根本没有机械动作)
 * 长在 three_d/pipeline/clip_compiler.py 里, 由管线导出成
 * generated/action-motion-map.json。前端**只读不抄**。
 *
 * 为什么不在 JS 里再写一份: 本仓被"两边各留一份"咬过 —— linkageKinematics.js 与
 * gen_twin_manifest.solve_lid_kinematics 是同一条曲柄滑块公式的两个副本, 只能靠
 * 两侧各挂一个回归测试锁住。映射表有近百条, 手抄必漂。
 *
 * 拿不到表时一律降级(返回 null), 不编默认值: 猜一个"大概是这根轴"比不动更糟,
 * 因为看着像在演示, 实际在演示一个不存在的运动。
 */

/** 表地址; 与 clips/models 同走 /api/3d/assets 白名单 */
const MAP_URL = '/api/3d/assets/generated/action-motion-map.json'

/**
 * 进程内缓存: 表是构建产物, 一次会话内**通常**不变.
 *
 * 例外是页内触发的 --flows 重编译(演示页的"重新编译"按钮) —— 那之后表可能真变了,
 * 调用方必须自己 resetMotionMap(), 否则整个会话都拿着旧表且毫无迹象.
 */
let cached = null
let pending = null

/**
 * 功能: 取动作→机构映射表(带缓存).
 * @returns {Promise<object|null>} 映射表; 不可用时 null
 */
export function loadMotionMap() {
  if (cached !== null) return Promise.resolve(cached)
  if (pending !== null) return pending
  // 强刷: 表是 --flows 的产物, 后端 FileResponse 不发 Cache-Control, 不加戳会在
  // 重编译后继续吃磁盘缓存里的旧表(下面那层进程内缓存又把它钉死一整个会话)
  pending = fetch(`${MAP_URL}?t=${Date.now()}`)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      return response.json()
    })
    .then((doc) => {
      if (doc?.schema !== 'ptlc.action-motion-map/v1') {
        throw new Error(`映射表 schema 不认识: ${doc?.schema}`)
      }
      cached = doc
      return doc
    })
    .catch(() => {
      cached = null
      return null
    })
    .finally(() => {
      pending = null
    })
  return pending
}

/**
 * 功能: 清掉缓存(测试与重跑后用).
 * @returns {void}
 */
export function resetMotionMap() {
  cached = null
  pending = null
}

/**
 * 功能: 判断一个动作是否已知"无机械动作".
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {boolean} 是否在忽略表里
 */
export function isIgnored(map, name) {
  return Array.isArray(map?.ignoredActions) && map.ignoredActions.includes(name)
}

/**
 * 功能: 查一个动作的机构映射.
 *
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {object|null} {kind, ...} 之一:
 *   {kind:'axis', axis, toMm, label, speedMmS}          定值轴移动
 *   {kind:'search', label, durationS}                    行程由运行期决定, 只占时间
 *   {kind:'actuator', id, arg}                           气缸, 目标态取自动作参数 arg
 *   {kind:'actuator', id, value}                         气缸, 目标态由动作本身固定
 *   {kind:'tank-lid', value}                             展缸盖, 缸号取自动作参数
 *   null                                                  表里没有
 */
export function lookupAction(map, name) {
  if (!map || !name) return null
  const axis = map.stationAxisActions?.[name]
  if (axis) return { kind: 'axis', ...axis }
  const search = map.searchAxisActions?.[name]
  if (search) return { kind: 'search', ...search }
  const cylinder = map.cylinderActions?.[name]
  if (cylinder) return { kind: 'actuator', ...cylinder }
  const fixed = map.cylinderActionsFixed?.[name]
  if (fixed) return { kind: 'actuator', ...fixed }
  const lid = map.tankLidActions?.[name]
  if (lid !== undefined && lid !== null) return { kind: 'tank-lid', value: Number(lid) }
  return null
}

/**
 * 功能: 缸号 → 缸盖联动组 id.
 * @param {object|null} map 映射表
 * @param {number} tank 缸号 1..8
 * @returns {string} 联动组 id; 查不到返回空串
 */
export function tankLidLinkage(map, tank) {
  return String(map?.tankLidLinkage?.[String(tank)] || '')
}

/**
 * 功能: 查一个动作的多步定值序列(目标是烧在 PLC 里的常量).
 *
 * 步骤形态见 clip_compiler.SEQUENCE_ACTIONS 的头注释 —— 字段名就是前后端的契约。
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {Array<object>|null} 步骤序列; 表里没有返回 null
 */
export function sequenceSteps(map, name) {
  const steps = map?.sequenceActions?.[name]
  return Array.isArray(steps) && steps.length ? steps : null
}

/**
 * 功能: 取一条 point 步骤要查的示教点 key.
 *
 * point 步骤有**两种编码**, 契约见 clip_compiler.SEQUENCE_ACTIONS 的头注释:
 *   {kind:'point', arg:'ref_spot', member:'x_start'}  点位由运行期入参间接给出
 *   {kind:'point', point:'sampling_4x_wash'}          点位在编译期就定死(示教点 id)
 * 前端早先只认第一种, 于是第二种一律取到 `params[undefined]` → 报"请先在参数里选一个
 * 点位(undefined)", 而那些动作压根没有 point_ref 参数可选 —— 五条动作因此播不了。
 *
 * 与 clip_compiler.emit_sequence 逐字同式(字面优先, member 无条件后缀), 两边**不许**
 * 各写一套: 同一份表两处消费, 分歧就是下一个"看着在演其实没动"。
 *
 * @param {object} step 步骤声明
 * @param {object} params 已归一的入参
 * @returns {{key: string, arg: string}} key 为空表示 arg 形态且用户还没选点位;
 *   arg 为空表示这是字面形态(缺 key 就是表本身坏了, 不该怪用户没选)
 */
export function sequencePointKey(step, params) {
  const arg = typeof step?.arg === 'string' ? step.arg : ''
  const base = step?.point || (arg ? params?.[arg] : undefined)
  if (!base) return { key: '', arg }
  return { key: step?.member ? `${base}.${step.member}` : String(base), arg }
}

/**
 * 功能: 查一个"目标毫米直接来自入参"的轴动作.
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {{axis: string, arg: string, label: string, speedMmS: number}|null} 条目
 */
export function paramAxisAction(map, name) {
  return map?.paramAxisActions?.[name] || null
}

/**
 * 功能: 查一个动作驱动了哪些流体执行件(泵/阀/真空).
 *
 * 有值就说明这条动作确实在做事, 只是做的事三维暂不表现 —— 与"做不到"是两回事。
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {string} 说明文本; 不是流体动作返回空串
 */
export function fluidNote(map, name) {
  return String(map?.fluidActions?.[name] || '')
}

/**
 * 功能: 查一个动作"有机械运动但目标值 PC 侧拿不到"的具体原因.
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @returns {string} 原因文本; 不在表里返回空串
 */
export function unresolvedReason(map, name) {
  return String(map?.unresolvedActions?.[name] || '')
}
