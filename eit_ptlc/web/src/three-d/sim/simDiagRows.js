/**
 * 功能: 诊断面板的行构造 (纯函数, node 可测).
 *
 * 它要回答的是"门为什么不满足"。三条呈现纪律:
 *   1. 三态而不是两态 —— true / false / **未知**(读不到)。把"读不到"画成"不满足"
 *      会把人引到错误的地方查, 这正是真机上那段标定话术害人的方式;
 *   2. 传感器位**语义在前、裸位在后**并排 —— 只给语义则现场对着 PLC 屏对不上位号,
 *      只给裸位就是让人拿位号去猜;
 *   3. 释义为空就留空, 不编。
 */

/**
 * L2 State 码 -> 显示名 (与 controller/plc_controller.PLCActionState 同表)。
 *
 * 真源已收编到 twin/stationStatus.js 的 L2_STATE (那边还带中文与色调, 且有金样看门狗);
 * 这里**派生**而不是重抄一份 —— 沙盒诊断面板要的是英文码名, 形状保持 {码: 英文} 不变。
 */
import { L2_STATE } from '../twin/stationStatus.js'

export const L2_STATE_TEXT = Object.freeze(
  Object.fromEntries(Object.entries(L2_STATE).map(([code, meta]) => [code, meta.en])),
)

/** 门项的三态标记: 未知与不满足必须看得出区别。 */
export function gateMark(value) {
  if (value === null || value === undefined) return '?'
  return value ? '✓' : '✗'
}

/**
 * 功能: 工位段号条的行.
 * @param {object} report GET /api/sim/diagnostics
 * @returns {object[]} [{station, state, stateText, code, step, stepText, errorCode,
 *                       errorText, actionName, attention, error}]
 */
export function stationRows(report) {
  return (report?.stations || []).map((row) => {
    const l2 = row.l2 || {}
    const state = Number(l2.State ?? 0)
    const errorCode = Number(l2.ErrorCode ?? 0)
    return {
      station: row.station,
      error: l2.error || '',
      state,
      stateText: L2_STATE_TEXT[state] || `state=${state}`,
      code: Number(l2.ActiveCode ?? 0),
      actionName: row.action_name || '',
      step: Number(l2.Step ?? 0),
      stepText: row.step_text || '',
      errorCode,
      errorText: row.error_text || '',
      // 需要展开门明细的: 出错或被拒的工位
      attention: state === 40 || state === 30 || errorCode > 0,
    }
  })
}

/**
 * 功能: 某工位的前置门逐条.
 * @param {object} report GET /api/sim/diagnostics
 * @param {string} station 工位名
 * @returns {object[]} [{key, spec, value, mark, because, unknown}]
 */
export function gateRows(report, station) {
  const row = (report?.stations || []).find((item) => item.station === station)
  return (row?.gate || []).map((item) => ({
    key: item.key,
    spec: item.spec,
    value: item.value ?? null,
    mark: gateMark(item.value),
    because: item.because || '',
    unknown: item.value === null || item.value === undefined,
  }))
}

/**
 * 功能: 传感器位表, 按字节分组 (语义在前、裸位在后).
 * @param {object} report GET /api/sim/diagnostics
 * @returns {object[]} [{byte, value, bits, rows: [{name, label, bit, on, source, address}]}]
 */
export function sensorGroups(report) {
  const bytes = report?.sensors?.bytes || {}
  const groups = new Map()
  for (const name of Object.keys(bytes)) {
    groups.set(name, {
      byte: name,
      value: bytes[name]?.value ?? null,
      bits: bytes[name]?.bits || '',
      rows: [],
    })
  }
  for (const entry of report?.sensors?.bits || []) {
    const group = groups.get(entry.byte)
    if (!group) continue
    group.rows.push({
      name: entry.name,
      label: entry.label,
      bit: entry.bit,
      on: entry.on ?? null,
      source: entry.source || '',
      // 现场对着 PLC 屏要能对上位号, 所以地址与字节都写出来
      address: `${entry.byte}.${entry.bit}`,
    })
  }
  return [...groups.values()]
}

/**
 * 功能: 合成值台账行 —— 本次会话有几处答案是沙盒编的.
 *
 * 沙盒没有对位相机/液位相机, 那几个 host 方法给的是合成值。**必须在界面上留痕**:
 * 看不见的合成值只是一个更隐蔽的零偏桩 —— 与直接拒绝相比, 无非把"跑不通"换成了
 * "跑通了但不知道有几处是编的"。
 *
 * @param {object} report GET /api/sim/diagnostics
 * @returns {{total: number, items: object[]}}
 */
export function syntheticBlock(report) {
  const block = report?.synthetic || {}
  return {
    total: Number(block.total) || 0,
    items: (block.items || []).map((item) => ({
      host: String(item.host || ''),
      reason: String(item.reason || ''),
      count: Number(item.count) || 0,
    })),
  }
}

/**
 * 功能: 泵积分量与账本扣减量并排 —— 差异只呈现, 不回写.
 *
 * 账本按动作参数扣是**真机的真实盲区**(没有流量计), 沙盒刻意不改这个口径; 泵按真实
 * DT 指令积分。两个数摆在一起, 配错档速这类事才看得出来。
 * `diverged` 是单向的: 只有"账本扣的比泵取过的还多"才算错 —— 反方向 (清洗润洗抽液
 * 但不记账) 是正常的, 双向判据会天天误报。
 *
 * @param {object} report GET /api/sim/diagnostics
 * @returns {{aspiratedMl, dispensedMl, ledgerMl, diverged, note, items}}
 */
export function pumpLedgerBlock(report) {
  const block = report?.pumps || {}
  return {
    aspiratedMl: Number(block.aspirated_total_ml) || 0,
    dispensedMl: Number(block.dispensed_total_ml) || 0,
    ledgerMl: Number(block.ledger_drawn_ml) || 0,
    diverged: Boolean(block.diverged),
    note: String(block.note || ''),
    items: (block.items || []).map((item) => ({
      id: String(item.id || ''),
      plungerMl: Number(item.plunger_ml) || 0,
      aspiratedMl: Number(item.aspirated_ml) || 0,
      dispensedMl: Number(item.dispensed_ml) || 0,
      busy: Boolean(item.busy),
    })),
  }
}

/**
 * 功能: 展缸液量行 (后端积分出来的真值, 非前端包络).
 * @param {object} report GET /api/sim/diagnostics
 * @returns {object[]} [{tank, volumeMl, level, soakS}]; 只列有液或泡过的缸
 */
export function tankRows(report) {
  const volumes = report?.tanks?.volumes || {}
  return Object.keys(volumes)
    .map(Number)
    .sort((a, b) => a - b)
    .map((tank) => ({
      tank,
      volumeMl: Number(volumes[String(tank)]?.volume_ml) || 0,
      level: Number(volumes[String(tank)]?.level) || 0,
      soakS: Number(volumes[String(tank)]?.soak_s) || 0,
    }))
    .filter((row) => row.volumeMl > 0 || row.soakS > 0)
}

/**
 * 功能: 板堆模型行 (账面已回灌的可视化: count 与物料页的板仓数应恒相等).
 * @param {object} report GET /api/sim/diagnostics
 * @returns {object[]}
 */
export function feedliftRows(report) {
  const block = report?.feedlift || {}
  return Object.keys(block).sort().map((magazine) => ({
    magazine,
    ...block[magazine],
  }))
}
