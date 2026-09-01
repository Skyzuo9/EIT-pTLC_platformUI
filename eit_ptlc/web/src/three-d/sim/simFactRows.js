/**
 * 功能: "现场事实"面板的行构造 (纯函数, node 可测).
 *
 * 现场事实 = 沙盒开跑前要摆好的那些物理前提: 仓里有几张板、座上有没有板、
 * 中转放着哪块、瓶里还有多少。它们的唯一写口是 /api/sim/materials/*, 与状态设定
 * (轴/关节/气缸, 走 PUT /api/sim/state) 是两条通道 —— 所以是两个面板, 不是一个。
 *
 * 显示源刻意取**推流投影** (material_state, 500ms 一帧) 而不是会话状态快照:
 * 前者与三维画面永远同一帧, 于是"面板显示变了"本身就证明了写入已经走完整条链,
 * 天然满足"写后不做乐观回写"。
 */

/** 危险等级: 会把账面清零/清空的操作要走 confirmService 的 danger 档。 */
export const DANGER = 'danger'

/**
 * 功能: 板仓张数行.
 * @param {object} grid material_state 快照
 * @returns {object[]} [{magazine, label, count, capacity}]
 */
export function magazineRows(grid) {
  return (grid?.magazines || []).map((row) => ({
    magazine: String(row.magazine || ''),
    label: row.label || row.magazine || '',
    count: Number(row.count) || 0,
    capacity: Number(row.capacity) || 0,
  }))
}

/**
 * 功能: 板位座行 (点样座 / 刮板拍照台) —— 薄层板在沙盒里唯一能被"摆"出来的地方.
 * @param {object} grid material_state 快照
 * @returns {object[]} [{seat, label, present}]
 */
export function seatRows(grid) {
  return (grid?.seats || []).map((row) => ({
    seat: String(row.seat || ''),
    label: row.label || row.seat || '',
    present: Boolean(row.present),
    // 工艺阶段: 无板的座后端一律报 blank (阶段是板的属性, 空座上无从谈起)
    stage: String(row.stage || 'blank'),
  }))
}

/** 工艺阶段词表 (与后端 material_store.PLATE_STAGES / plateTraceState.STAGE 同表) */
export const PLATE_STAGE_OPTIONS = Object.freeze([
  { value: 'blank', label: '空白' },
  { value: 'spotted', label: '已点样' },
  { value: 'developed', label: '已展开' },
  { value: 'scraped', label: '已刮取' },
])

/**
 * 功能: 中转区行 (A/B 各放着几号盘, null = 空).
 * @param {object} grid material_state 快照
 * @returns {object[]} [{area, kind, plate}]
 */
export function stagingRows(grid) {
  const staging = grid?.staging || {}
  return Object.keys(staging).sort().map((area) => ({
    area,
    kind: staging[area]?.kind || '',
    plate: staging[area]?.plate ?? null,
  }))
}

/**
 * 功能: 货架库位行 (12 个盘位的有无).
 *
 * ⚠ 推流快照里的 rack 是 **{collector: [...], bottle: [...]}** 的按类分组对象,
 * 不是 REST /api/materials 那张扁平数组 —— 它由 MaterialStateStore 按孔位重算,
 * 且 present 可能是 **null**(该位无已验证传感器, 属"不知道"而不是"没有")。
 * 照 REST 的形状写会当场 `.map is not a function`。
 * @param {object} grid material_state 快照 (MaterialStateStore 归一后的)
 * @returns {object[]} [{kind, plate, present, unknown}]
 */
export function rackRows(grid) {
  const rows = []
  for (const [kind, list] of Object.entries(grid?.rack || {})) {
    if (!Array.isArray(list)) continue
    for (const row of list) {
      const present = typeof row?.present === 'boolean' ? row.present : null
      rows.push({
        kind: String(row?.kind || kind),
        plate: Number(row?.plate) || 0,
        present: present === null ? false : present,
        // 无已验证传感器时后端给 null: 界面要能与"确实没板"分开
        unknown: present === null,
      })
    }
  }
  return rows
}

/**
 * 功能: 溶剂瓶余量行.
 * @param {object} grid material_state 快照
 * @returns {object[]} [{bottle, label, volumeMl, capacityMl, percent}]
 */
export function bottleRows(grid) {
  return (grid?.bottles || []).map((row) => ({
    bottle: String(row.bottle || ''),
    label: row.label || row.bottle || '',
    volumeMl: Number(row.volume_ml) || 0,
    capacityMl: Number(row.capacity_ml) || 0,
    percent: Number(row.percent) || 0,
  }))
}

/**
 * 功能: 件位行 (瓶/粉桶停在哪个工位夹具上); 只提供"清空", 放件走三维点选.
 * @param {object} grid material_state 快照
 * @returns {object[]} [{seat, label, kind, plate, hole}]
 */
export function payloadSeatRows(grid) {
  // ⚠ 推流快照把 payload_seats 归一成了驼峰 payloadSeats; 照后端字段名取会恒空
  return (grid?.payloadSeats || []).map((row) => ({
    seat: String(row.seat || ''),
    label: row.label || row.seat || '',
    kind: row.kind || '',
    plate: row.plate ?? null,
    hole: row.hole ?? null,
    stale: Boolean(row.stale),
  }))
}

/**
 * 功能: 在途行 (载荷此刻在哪把夹爪上); 只提供"清在途".
 * @param {object} grid material_state 快照
 * @returns {object[]} [{carrier, label, kind, plate, hole, stale}]
 */
export function transitRows(grid) {
  const transit = grid?.transit || {}
  return Object.keys(transit).sort().map((carrier) => ({
    carrier,
    label: transit[carrier]?.label || carrier,
    kind: transit[carrier]?.kind || '',
    plate: transit[carrier]?.plate ?? null,
    hole: transit[carrier]?.hole ?? null,
    stale: Boolean(transit[carrier]?.stale),
  }))
}

/**
 * 功能: 张数输入的边界收敛 (负数与超容量都拉回来).
 *
 * 后端还有一道裁决 (账面超容量会被照收并告警, 那是"外部权威声称现场如此");
 * 前端 clamp 只是不让输入框造出物理不可能的数。
 * @param {*} raw 输入值
 * @param {number} capacity 容量上限 (<=0 表示不限)
 * @returns {number} 收敛后的张数
 */
export function clampCount(raw, capacity) {
  const value = Math.round(Number(raw))
  if (!Number.isFinite(value) || value < 0) return 0
  if (capacity > 0 && value > capacity) return capacity
  return value
}
