/**
 * 功能: rig_map.yaml 的写回补丁集 —— 动作/标定界面对唯一固化真源的全部写入口.
 *
 * 与 workbench/yamlPatch 同范式: yaml Document API 原地打补丁, 只动明确拥有的键,
 * 注释与键序一个字不碰(rig_map 里的"为什么这么绑"比数据本身更值钱).
 *
 * 契约要点(对齐 pipeline/blender_clean.py::build_axis_carriages):
 *   - 滑车成员写 `carriage_members`(匹配器对象数组 {equals|contains, expect_count}),
 *     **不是**早期未接线的 `carriage_nodes`(裸字符串数组, 管线根本不读 —— 已废弃);
 *   - 成员在该轴 station 的 ST_<station> 子树内匹配, 命中数 ≠ expect_count 时管线
 *     硬失败 —— 这是写回质量的天然守门;
 *   - 标定三字段 sign/zero_offset_mm/range_mm 是 manifest camelCase 的 snake_case 对应.
 */
import { parseDocument } from 'yaml'

/**
 * 功能: 在顶层序列段里按 id 找条目.
 * @param {import('yaml').Document} doc 文档
 * @param {string} section 段名
 * @param {string} id 条目 id
 * @returns {object|null} YAMLMap 条目
 */
function findById(doc, section, id) {
  const seq = doc.get(section, true)
  if (!seq || !seq.items) return null
  return seq.items.find((item) => item.get?.('id') === id) || null
}

/**
 * 功能: 把一条轴的滑车成员写回 rig_map(指认流程的落盘出口).
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {string} axisId 轴 id(如 axis_1z)
 * @param {Array<{equals?: string, contains?: string, expect_count: number}>} members
 *        匹配器数组; equals 优先(防子件重复命中), 装配根节点用 equals 选整组
 * @returns {string} 新 YAML 文本
 * @throws {Error} 轴不存在或成员为空
 */
export function patchRigMapCarriage(originalText, axisId, members) {
  if (!Array.isArray(members) || !members.length) {
    throw new Error('滑车成员为空, 拒绝写回(会把轴打成 rigged:false)')
  }
  const doc = parseDocument(originalText)
  const item = findById(doc, 'axes', axisId)
  if (!item) throw new Error(`rig_map.yaml 里找不到轴 ${axisId}`)

  // 保留既有成员的 within 限定(孪生机构同名件的祖先子装配约束): 前端指认流程
  // 不感知该字段, 整段覆盖会静默丢掉它, 下一次全链重跑就按"命中 2 个"硬失败.
  const oldWithin = new Map()
  try {
    for (const old of item.get('carriage_members', true)?.toJSON() || []) {
      if (old?.equals && old?.within) oldWithin.set(String(old.equals), String(old.within))
    }
  } catch {
    /* 旧段缺失或形态异常时不迁移 */
  }

  const clean = members.map((member) => {
    const out = {}
    if (member.equals) out.equals = String(member.equals)
    else if (member.contains) out.contains = String(member.contains)
    else throw new Error('成员匹配器必须有 equals 或 contains')
    const within = member.within ?? (member.equals ? oldWithin.get(String(member.equals)) : null)
    if (within) out.within = String(within)
    out.expect_count = Math.max(1, Math.round(Number(member.expect_count) || 1))
    return out
  })
  item.set('carriage_members', doc.createNode(clean))
  item.set('rigged', true)
  item.set('assigned_by', 'workbench-assign')
  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 把一条轴的运动方向(axis 单位向量 + sign)写回 rig_map.
 *
 * 动作页「运动方向」选择器的落盘出口. axis/sign 只进 manifest 不进 GLB ——
 * 写回后只需重跑 manifest 两步+部署(秒级), 不必动 Blender.
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {string} axisId 轴 id
 * @param {number[]} axis glTF 系单位轴向量(如 [0,0,1])
 * @param {number} sign 方向符号(mm 增大沿 axis 正向=+1, 反向=-1)
 * @returns {string} 新 YAML 文本
 */
export function patchRigMapAxisDirection(originalText, axisId, axis, sign) {
  if (!Array.isArray(axis) || axis.length !== 3 || !axis.some((v) => Number(v))) {
    throw new Error('轴向必须是非零三元组')
  }
  const doc = parseDocument(originalText)
  const item = findById(doc, 'axes', axisId)
  if (!item) throw new Error(`rig_map.yaml 里找不到轴 ${axisId}`)
  item.set('axis', doc.createNode(axis.map(Number)))
  item.set('sign', Number(sign) >= 0 ? 1 : -1)
  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 把执行器/联动组的运动学数值参数写回 rig_map.
 *
 * 只动给出的键(sign/outputRange/transitionS...), 成员 node 改选是 v2 —— 这里
 * 不碰 node 字段. 联动组的 outputRange 写到每个成员上(双侧对称行程).
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {object} changes {actuators: {id: {sign?, outputRange?, transitionS?}},
 *                          linkages: {id: {transitionS?, outputRange?}}}
 * @returns {string} 新 YAML 文本
 */
export function patchRigMapMotionParams(originalText, changes) {
  const doc = parseDocument(originalText)

  for (const [id, patch] of Object.entries(changes?.actuators || {})) {
    const item = findById(doc, 'actuators', id)
    if (!item) throw new Error(`rig_map.yaml 里找不到执行器 ${id}`)
    if (typeof patch.sign === 'number') item.set('sign', patch.sign)
    if (Array.isArray(patch.outputRange)) {
      item.set('outputRange', doc.createNode(patch.outputRange.map(Number)))
    }
    if (typeof patch.transitionS === 'number') item.set('transitionS', patch.transitionS)
  }

  for (const [id, patch] of Object.entries(changes?.linkages || {})) {
    const item = findById(doc, 'linkages', id)
    if (!item) throw new Error(`rig_map.yaml 里找不到联动组 ${id}`)
    if (typeof patch.transitionS === 'number') item.set('transitionS', patch.transitionS)
    if (Array.isArray(patch.outputRange)) {
      const membersSeq = item.get('members', true)
      for (const member of membersSeq?.items || []) {
        member.set('outputRange', doc.createNode(patch.outputRange.map(Number)))
      }
    }
  }

  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 把标定三字段写回 rig_map(标定页「写回」按钮的落盘出口).
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {Array<{id: string, sign?: number, zeroOffsetMm?: number, rangeMm?: number[]}>} changedAxes
 *        变更轴数组(axisCalib.changedAxes 的口径, camelCase)
 * @returns {string} 新 YAML 文本
 */
export function patchRigMapAxisCalib(originalText, changedAxes) {
  const doc = parseDocument(originalText)
  for (const change of changedAxes || []) {
    const item = findById(doc, 'axes', change.id)
    if (!item) throw new Error(`rig_map.yaml 里找不到轴 ${change.id}`)
    if (typeof change.sign === 'number') item.set('sign', change.sign)
    if (typeof change.zeroOffsetMm === 'number') item.set('zero_offset_mm', change.zeroOffsetMm)
    if (Array.isArray(change.rangeMm)) {
      item.set('range_mm', doc.createNode(change.rangeMm.map(Number)))
    }
  }
  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 把展缸盖的抬升量写回 rig_map(tank_lids.lift_mm).
 *
 * 展缸盖的 8 条 linkage 不在 rig_map.linkages 段里 —— 它们由 03 报告展开, 所以
 * patchRigMapMotionParams 那条通路对它们会"找不到联动组"而抛错. 抬升是整段共用的
 * 单一主参数(摆角/滑车行程都是它的函数), 因此写一个数即可, 重跑 manifest 生效.
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {number} liftMm 盖抬升(mm)
 * @returns {string} 新 YAML 文本
 */
export function patchRigMapTankLidLift(originalText, liftMm) {
  const value = Number(liftMm)
  if (!Number.isFinite(value) || value <= 0) throw new Error('展缸盖抬升必须是正数')
  const doc = parseDocument(originalText)
  if (!doc.getIn(['tank_lids'], true)) throw new Error('rig_map.yaml 里找不到 tank_lids 段')
  doc.setIn(['tank_lids', 'lift_mm'], Number(value.toFixed(2)))
  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 液面示意几何的总开关(tanks.liquid.enabled).
 *
 * 开关只改一行, 但生效要重跑 03(liquidNode 是管线生成的示意几何) —— UI 侧注明.
 *
 * @param {string} originalText rig_map.yaml 原文
 * @param {boolean} enabled 是否启用
 * @returns {string} 新 YAML 文本
 */
export function patchRigMapLiquid(originalText, enabled) {
  const doc = parseDocument(originalText)
  if (!doc.getIn(['tanks', 'liquid'], true)) {
    throw new Error('rig_map.yaml 里找不到 tanks.liquid 段')
  }
  doc.setIn(['tanks', 'liquid', 'enabled'], Boolean(enabled))
  return doc.toString({ lineWidth: 0 })
}

/**
 * 功能: 读取 rig_map 里一条轴的现值(指认前回显既有成员用).
 * @param {string} text rig_map.yaml 原文
 * @param {string} axisId 轴 id
 * @returns {object|null} 轴条目的普通对象
 */
export function readRigMapAxis(text, axisId) {
  try {
    const doc = parseDocument(text)
    const axes = doc.toJS()?.axes || []
    return axes.find((axis) => axis?.id === axisId) || null
  } catch {
    return null
  }
}

/**
 * 功能: 读取液面开关现值.
 * @param {string} text rig_map.yaml 原文
 * @returns {boolean} enabled
 */
export function readRigMapLiquidEnabled(text) {
  try {
    return Boolean(parseDocument(text).toJS()?.tanks?.liquid?.enabled)
  } catch {
    return false
  }
}
