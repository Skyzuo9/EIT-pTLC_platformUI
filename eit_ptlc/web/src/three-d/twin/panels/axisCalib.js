/**
 * 功能: AxisCalibBoard(轴标定工作台)的纯逻辑 —— 轴参数快照、变更检测、
 *       零点匹配公式、rig_map 回填片段生成.
 *
 * 设计约定:
 *   - 本模块**零依赖、不摸 window/three**, 一切输入是普通对象 —— 因此可被
 *     node --test 直接单测(照 displaySettings.js 的范式).
 *   - 面板改的是 manifest axes[] 条目上的字段(运行时内存, 刷新即回), 本模块
 *     只负责"改了哪些、导出成什么样"; **唯一固化真源是 pipeline/rig_map.yaml**,
 *     导出片段就是给人工回填它用的.
 */

/** 参与标定的字段(camelCase=manifest 侧, snake_case=rig_map 侧), 顺序即导出顺序 */
export const CALIB_FIELDS = [
  { key: 'sign', yaml: 'sign' },
  { key: 'zeroOffsetMm', yaml: 'zero_offset_mm' },
  { key: 'rangeMm', yaml: 'range_mm' },
]

/** 浮点比较容差: 面板步进最小 0.1 mm, 1e-9 足够区分且不受累计误差干扰 */
const EPS = 1e-9

/** 零点/行程写入的量化步长(mm) —— 面板显示与 rig_map 回填的既定精度 */
export const ZERO_QUANT_MM = 0.001

/** 量化除数(1000). 用除法而非 ×0.001, 避免量化本身引入浮点噪声 */
const QUANT_DIV = 1 / ZERO_QUANT_MM

/**
 * 功能: 归一化一条轴的三个标定字段为纯数值(缺省按前端 MachineStateDriver 的默认).
 * @param {object} spec manifest axes[] 条目
 * @returns {{sign: number, zeroOffsetMm: number, rangeMm: [number, number]}} 纯值
 */
export function calibValuesOf(spec) {
  const range = Array.isArray(spec?.rangeMm) ? spec.rangeMm : [0, 0]
  return {
    sign: Number(spec?.sign ?? 1),
    zeroOffsetMm: Number(spec?.zeroOffsetMm ?? 0),
    rangeMm: [Number(range[0] ?? 0), Number(range[1] ?? 0)],
  }
}

/**
 * 功能: 面板挂载时对全部轴拍原值快照, 作为后续 diff 的基准.
 * @param {Array<object>} axes manifest 的 axes 列表
 * @returns {Map<string, object>} 轴 id -> calibValuesOf 结果
 */
export function snapshotAxes(axes) {
  const snapshot = new Map()
  for (const spec of axes || []) {
    if (spec?.id) snapshot.set(spec.id, calibValuesOf(spec))
  }
  return snapshot
}

/**
 * 功能: 两个标定值是否等价(浮点容差; rangeMm 逐元素).
 * @param {object} a calibValuesOf 结果
 * @param {object} b calibValuesOf 结果
 * @returns {boolean} 是否等价
 */
function sameCalib(a, b) {
  return (
    Math.abs(a.sign - b.sign) <= EPS &&
    Math.abs(a.zeroOffsetMm - b.zeroOffsetMm) <= EPS &&
    Math.abs(a.rangeMm[0] - b.rangeMm[0]) <= EPS &&
    Math.abs(a.rangeMm[1] - b.rangeMm[1]) <= EPS
  )
}

/**
 * 功能: 找出相对快照发生变更的轴.
 * @param {Array<object>} axes manifest 的 axes 列表(现值)
 * @param {Map<string, object>} snapshot snapshotAxes 的产物
 * @returns {Array<{id: string, label: string, before: object, after: object}>} 变更清单
 */
export function changedAxes(axes, snapshot) {
  const changed = []
  for (const spec of axes || []) {
    const before = spec?.id ? snapshot?.get?.(spec.id) : null
    if (!before) continue
    const after = calibValuesOf(spec)
    if (!sameCalib(before, after)) {
      changed.push({ id: spec.id, label: spec.label || spec.id, before, after })
    }
  }
  return changed
}

/**
 * 功能: "匹配"按钮的零点公式 —— 用户把虚拟轴 jog 到与实机目视重合后, 反算新零点.
 *
 * 严格推导(setAxisMm: pos = base + dir·(mm − zero)·sign·mmToUnit):
 *   匹配时虚拟位移 D_v = (P_v − zero_old)·sign·mmToUnit(P_v = 驱动层已应用值,
 *   不是滑杆原始值 —— clamp/越界以实际写入为准);
 *   要求此后 feed 写 setAxisMm(R) 呈现同一位移:
 *   (R − zero_new)·sign·mmToUnit = (P_v − zero_old)·sign·mmToUnit
 *   ⇒ zero_new = zero_old + (R − P_v)
 * sign 与 mmToUnit 消去 —— 前提是接管期间未翻转 sign(面板在接管态锁定 sign 编辑).
 * "zero = R − P_v" 的直觉式只在 zero_old = 0 时成立, 通式必须带 zero_old.
 *
 * @param {{liveMm: number, appliedMm: number, zeroOffsetMm: number}} input
 *        liveMm=实机反馈 R, appliedMm=驱动层已应用值 P_v, zeroOffsetMm=当前零点
 * @returns {number|null} 新零点(量化到 ZERO_QUANT_MM, 与面板既有精度一致); 输入非法返回 null
 */
export function matchedZeroOffset({ liveMm, appliedMm, zeroOffsetMm }) {
  const live = Number(liveMm)
  const applied = Number(appliedMm)
  const zero = Number(zeroOffsetMm ?? 0)
  if (!Number.isFinite(live) || !Number.isFinite(applied) || !Number.isFinite(zero)) return null
  return Math.round((zero + (live - applied)) * QUANT_DIV) / QUANT_DIV
}

/**
 * 功能: 匹配后"不动性校验"的位移容差(场景单位/米).
 *
 * 零点被 matchedZeroOffset 量化到 ZERO_QUANT_MM, 残差最大半个步长; 经 setAxisMm 的
 * (mm − zero)·sign·mmToUnit 折算成节点位移就是 0.5·ZERO_QUANT_MM·mmToUnit ——
 * **阈值必须大于它, 否则校验的是自己写入值的舍入而不是 bug**. 2026-08-05 踩过:
 * 阈值写死 1e-9 m, 比量化步长(1e-3 mm = 1e-6 m)严 1000 倍, 真机上 R 是 PLC 的
 * REAL(小数位远不止 3 位), 匹配几乎必然报"校验失败 位移 4.95e-7 m, 已撤销".
 * 这里取一整个步长(对量化残差是 2× 余量); 真 bug(clamp 咬住/sign 错/认错节点)
 * 量级 1e-3 m 起, 与本容差仍差三个数量级, 照样抓得到.
 *
 * @param {object} spec manifest axes[] 条目(只读 mmToUnit)
 * @returns {number} 容差(米)
 */
export function matchDriftToleranceM(spec) {
  const mmToUnit = Math.abs(Number(spec?.mmToUnit)) || 0.001
  return ZERO_QUANT_MM * mmToUnit
}

/**
 * 功能: 扩界建议 —— 让 rangeMm 覆盖给定 mm(带余量), 已覆盖则原样返回.
 *
 * 匹配前实机反馈落在 range 外时, feed 的 setAxisMm(R) 会被 clamp, 模型立刻跳变 ——
 * 必须先扩界(工作表里 8 根轴 range 需扩负值就是这类情况).
 *
 * 量化**向外**取整(下界 floor / 上界 ceil): 用 round 会让 −14.0004 的新下界回到
 * −14.000, 名叫 covering 却盖不住原值, clamp 照咬 0.4 µm —— 那点残差又会被
 * 匹配的不动性校验当成 bug 报出来.
 *
 * @param {[number, number]} rangeMm 现行程
 * @param {number} mm 要覆盖的值
 * @param {number} [marginMm=0] 余量
 * @returns {[number, number]} 新行程(量化到 ZERO_QUANT_MM, 保证覆盖 mm±margin)
 */
export function rangeCovering(rangeMm, mm, marginMm = 0) {
  const [lo, hi] = Array.isArray(rangeMm) ? rangeMm.map(Number) : [0, 0]
  const value = Number(mm)
  const margin = Math.max(0, Number(marginMm) || 0)
  if (!Number.isFinite(value)) return [lo, hi]
  // 先抹掉 1e-6 mm 以下的浮点噪声再向外取整, 否则 −20 会被 floor 成 −20.001
  const snap = (n) => Number((n * QUANT_DIV).toFixed(6))
  const floorMm = (n) => Math.floor(snap(n)) / QUANT_DIV
  const ceilMm = (n) => Math.ceil(snap(n)) / QUANT_DIV
  return [floorMm(Math.min(lo, value - margin)), ceilMm(Math.max(hi, value + margin))]
}

/**
 * 功能: 毫米数值的通用显示 —— 整数不带小数点, 其余最多 3 位小数去尾零.
 * @param {*} value 数值
 * @returns {string} 文案(非数值返回 '—')
 */
export function formatMm(value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return '—'
  if (Number.isInteger(num)) return String(num)
  return String(Number(num.toFixed(3)))
}

/**
 * 功能: zero_offset_mm 的 YAML 写法 —— 恒带小数点(rig_map 现有风格是 500.0).
 * @param {number} value 数值
 * @returns {string} 文案
 */
function formatOffsetYaml(value) {
  const text = formatMm(value)
  return text.includes('.') || text === '—' ? text : `${text}.0`
}

/**
 * 功能: 生成 rig_map 回填片段 —— 只含变更轴、只含标定三字段, 缩进与 rig_map
 *       轴条目内字段对齐(4 空格), 头部写明用法与"内存态不落盘"的语义.
 * @param {Array<object>} changed changedAxes 的产物
 * @param {string} timestamp 导出时刻(ISO 文本, 由调用方注入以便测试)
 * @returns {string} YAML 片段; 无变更时返回空串
 */
export function buildYamlFragment(changed, timestamp) {
  if (!changed?.length) return ''
  const lines = [
    `# ==== AxisDebugPanel 标定导出 ${timestamp} ====`,
    '# 回填: 用下列字段替换 pipeline/rig_map.yaml 对应 id 轴条目的同名字段,',
    '#   然后重跑 gen_twin_manifest.py(若同时改了 carriage/rigged, 需先重跑 03 与 04).',
    '# 本导出不落盘, 刷新即回 manifest 值; rig_map.yaml 是唯一固化真源.',
  ]
  for (const entry of changed) {
    const { before, after } = entry
    lines.push('')
    lines.push(
      `# ${entry.id} (${entry.label})  原: sign=${formatMm(before.sign)}  ` +
        `zero_offset_mm=${formatOffsetYaml(before.zeroOffsetMm)}  ` +
        `range_mm=[${formatMm(before.rangeMm[0])}, ${formatMm(before.rangeMm[1])}]`,
    )
    lines.push(`    sign: ${formatMm(after.sign)}`)
    lines.push(`    zero_offset_mm: ${formatOffsetYaml(after.zeroOffsetMm)}`)
    lines.push(`    range_mm: [${formatMm(after.rangeMm[0])}, ${formatMm(after.rangeMm[1])}]`)
  }
  return `${lines.join('\n')}\n`
}
