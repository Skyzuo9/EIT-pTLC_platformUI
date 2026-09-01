/**
 * 功能: 薄层板规格的运行时覆盖(目前只有硅胶层厚度)的纯状态机.
 *
 * 与 displaySettings.js 的关系: 写法照抄(零依赖、不摸 window/three、存稀疏覆盖、
 * 可被 node --test 直接 import), 但**刻意不合进它**, 因为两者语义不同:
 *   displaySettings 是**观感**参数, 按 dark/light 分槽 —— 深浅主题的合理光照差一个数量级。
 *   硅胶层厚度是**工件规格**(真实 TLC 板 0.1~2mm 都有), 与主题毫无关系,
 *   记两份值只会让"换个主题板就变厚了"这种荒谬现象出现。所以这里是单槽。
 *
 * 基准值来自 manifest.plateSpec(契约), 本模块只存"用户动过的那一项"。
 */

/** localStorage 键(v1: {version, silicaMm?}) */
export const PLATE_KEY = 'ptlc.plate.v1'

/**
 * 字段元数据: 面板渲染与夹取范围的唯一来源。
 * 与 displaySettings.DISPLAY_FIELDS 同形, 便于面板复用同一套渲染组件。
 */
export const PLATE_FIELDS = [
  {
    key: 'silicaMm',
    group: 'plate',
    label: '硅胶层厚度',
    type: 'range',
    min: 0.1,
    max: 2.0,
    step: 0.05,
    unit: 'mm',
  },
  {
    // 吸盘柔性接触: 板顶到硬表面时吸盘压缩, 而不是把板顶进去(见 plateContact.js)。
    // 默认开 —— 这是物理上对的那种表现; 开关是逃生口, 关掉即回到"刚性钉在唇口"。
    // 关掉的代价明说: 放板时板会重新扎进展缸/座面(那正是 2026-08-05 用户报的现象)。
    key: 'contactEnabled',
    group: 'plate',
    label: '吸盘柔性接触',
    type: 'toggle',
    default: true,
  },
]

/** key -> 字段元数据 */
export const PLATE_FIELD_BY_KEY = new Map(PLATE_FIELDS.map((field) => [field.key, field]))

/**
 * 功能: 按字段元数据夹取一个值; 非法值返回 null(调用方据此忽略该覆盖).
 * @param {string} key 字段名
 * @param {*} value 待夹取的值
 * @returns {number|null}
 */
export function clampPlateValue(key, value) {
  const field = PLATE_FIELD_BY_KEY.get(key)
  if (!field) return null
  if (field.type === 'toggle') {
    // 与 displaySettings.clampValue 同款: 只认布尔与 0/1, 其它一律判非法。
    // 宽松判(Boolean(value))会把 '' / 'false' / null 悄悄读成一个值, 而开关读错
    // 在画面上与"用户就是这么设的"长得一模一样。
    if (typeof value !== 'boolean' && value !== 0 && value !== 1) return null
    return Boolean(value)
  }
  const num = Number(value)
  if (!Number.isFinite(num)) return null
  return Math.min(field.max, Math.max(field.min, num))
}

/**
 * 功能: 取某个开关的生效值(用户覆盖优先, 否则字段默认).
 * @param {string} key 字段名
 * @param {Record<string, *>} overrides 稀疏覆盖
 * @returns {boolean}
 */
export function plateToggle(key, overrides = {}) {
  const field = PLATE_FIELD_BY_KEY.get(key)
  const override = clampPlateValue(key, overrides?.[key])
  return override ?? Boolean(field?.default)
}

/**
 * 功能: 从存储读稀疏覆盖; 存储不可用或内容损坏时返回空覆盖(绝不抛).
 * @param {Storage|null} storage localStorage 或兼容对象
 * @returns {Record<string, number>}
 */
export function loadPlateOverrides(storage) {
  if (!storage) return {}
  let raw = null
  try {
    raw = storage.getItem(PLATE_KEY)
  } catch {
    return {}
  }
  if (!raw) return {}
  let parsed = null
  try {
    parsed = JSON.parse(raw)
  } catch {
    return {}
  }
  const out = {}
  for (const field of PLATE_FIELDS) {
    const clamped = clampPlateValue(field.key, parsed?.[field.key])
    if (clamped !== null) out[field.key] = clamped
  }
  return out
}

/**
 * 功能: 把稀疏覆盖写回存储; 空覆盖时删除整条记录(不留空壳).
 * @param {Storage|null} storage localStorage 或兼容对象
 * @param {Record<string, number>} overrides 稀疏覆盖
 * @returns {void}
 */
export function savePlateOverrides(storage, overrides) {
  if (!storage) return
  const payload = {}
  for (const field of PLATE_FIELDS) {
    const clamped = clampPlateValue(field.key, overrides?.[field.key])
    if (clamped !== null) payload[field.key] = clamped
  }
  try {
    if (!Object.keys(payload).length) storage.removeItem(PLATE_KEY)
    else storage.setItem(PLATE_KEY, JSON.stringify({ version: 1, ...payload }))
  } catch {
    /* 存储写不进去(隐私模式/配额)不该影响画面, 静默降级为"本次会话有效" */
  }
}

/**
 * 功能: 契约基准 ⊕ 用户覆盖 = 本次生效的板规格.
 *
 * 基准缺失时不编默认值, 而是走字段元数据的中位区间? —— 不。缺失就用 manifest 该有的
 * 标准板值 1.0(= 2+1 总厚 3mm, 与 CAD 实测吻合), 这是唯一有依据的回退。
 *
 * @param {object|null} spec manifest.plateSpec
 * @param {Record<string, number>} overrides 稀疏覆盖
 * @returns {{silicaMm: number, glassMm: number}}
 */
export function effectivePlateSpec(spec, overrides = {}) {
  const baseSilica = clampPlateValue('silicaMm', spec?.silicaMm)
  const override = clampPlateValue('silicaMm', overrides?.silicaMm)
  return {
    glassMm: Number.isFinite(Number(spec?.glassMm)) ? Number(spec.glassMm) : 2.0,
    silicaMm: override ?? baseSilica ?? 1.0,
  }
}
