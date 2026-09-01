/**
 * 功能: 把展缸盖气缸的机构反馈解释成"开/关"显示档 —— 实时页展缸区块的唯一判定口径.
 *
 * 语义链(三层逐字一致, 错一层就会显示反): PLC 气缸"动点"到位 = DO 侧激活 =
 * mechanism_state 的 effective=true = 盖压在缸口(关); "原点" = effective=false =
 * 盖被摆臂提起(开). 三维那侧同源 —— manifest linkage 的 outputRange 是反向的
 * [行程, 0], 值 1 落在 GLB 建模态(关盖), 所以几何与这里的文字永远同相.
 *
 * 展缸气缸双端都有磁性开关(feedbackAvailable), 所以正常情况下 effective 取的是
 * 真实到位反馈而非命令态. 反馈过期(estimated)时必须显式降级为"命令态", 不能让
 * 一个没到位的命令在界面上冒充实测 —— 这正是"和实际设备联系起来"的分寸.
 */

/** 显示档: 关/开/命令态/断流/无数据 */
export const LID_STATES = {
  closed: { key: 'closed', label: '关闭', tone: 'closed' },
  open: { key: 'open', label: '开启', tone: 'open' },
  stale: { key: 'stale', label: '断流', tone: 'stale' },
  unknown: { key: 'unknown', label: '无数据', tone: 'stale' },
}

/**
 * 功能: 由机构采样解出盖的显示状态.
 * @param {object|null} mechanism realtime.mechanisms.items 里的一条(含 effective/stale/estimated)
 * @returns {{key: string, label: string, tone: string, estimated: boolean, stale: boolean}} 显示档
 */
export function lidStatusOf(mechanism) {
  if (!mechanism || typeof mechanism.effective !== 'boolean') {
    return { ...LID_STATES.unknown, estimated: true, stale: true }
  }
  if (mechanism.stale) {
    return { ...LID_STATES.stale, estimated: Boolean(mechanism.estimated), stale: true }
  }
  const base = mechanism.effective ? LID_STATES.closed : LID_STATES.open
  const estimated = Boolean(mechanism.estimated)
  return {
    ...base,
    // 无到位反馈时标注命令态: 界面上"开启*"读作"已下令但磁开关没确认"
    label: estimated ? `${base.label}*` : base.label,
    estimated,
    stale: false,
  }
}

/**
 * 功能: 把 manifest 的展缸清单与实时机构表拼成展缸区块的行.
 * @param {object[]} tanks manifest.tanks
 * @param {object[]} mechanisms realtime.mechanisms.items
 * @returns {object[]} 每缸一行(含 lid 显示档; 无 lidMechanismId 时 lid 为 null)
 */
export function tankLidRows(tanks, mechanisms) {
  const byId = new Map((mechanisms || []).map((item) => [item.id, item]))
  return (tanks || []).map((tank) => ({
    ...tank,
    lidMechanism: tank.lidMechanismId ? byId.get(tank.lidMechanismId) || null : null,
    lid: tank.lidMechanismId ? lidStatusOf(byId.get(tank.lidMechanismId)) : null,
  }))
}

/**
 * 功能: 8 缸盖状态的一句话汇总(HUD/标题用).
 * @param {object[]} rows tankLidRows 的产物
 * @returns {{open: number, closed: number, unknown: number, text: string}} 汇总
 */
export function lidSummary(rows) {
  let open = 0
  let closed = 0
  let unknown = 0
  for (const row of rows || []) {
    if (!row.lid) { unknown += 1; continue }
    if (row.lid.key === 'open') open += 1
    else if (row.lid.key === 'closed') closed += 1
    else unknown += 1
  }
  const parts = []
  if (open) parts.push(`${open} 开`)
  if (closed) parts.push(`${closed} 关`)
  if (unknown) parts.push(`${unknown} 未知`)
  return { open, closed, unknown, text: parts.join(' · ') || '—' }
}
