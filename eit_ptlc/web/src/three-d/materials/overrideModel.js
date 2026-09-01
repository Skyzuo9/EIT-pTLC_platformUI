/**
 * 功能: 材质人工覆盖的数据模型 —— 解析、编辑、序列化回 YAML.
 *
 * 与工作台的 selectionModel 同构: 浏览器只写"意图"(这种材质该长什么样), 落成
 * `material_semantics.yaml` 的 `appearance_overrides` 段, 由管线在生成 materials.yaml
 * 时盖上去. 所以调过的颜色可复现、可 diff、可撤销, 而不是只活在这一次会话里.
 *
 * 键是**最终材质名**(MAT_DEFAULT / MAT_STEEL_PLATE / MAT_NAT_00FFFF …), 与它由哪条
 * 规则产生无关 —— 不论来自 rules / native_materials / 颜色直采, 调法都一样.
 */

/** 可调字段及其取值范围; 顺序即面板上的排列顺序 */
export const FIELDS = [
  { key: 'base_color', label: '基色', type: 'color' },
  { key: 'roughness', label: '粗糙度', type: 'range', min: 0, max: 1, step: 0.01 },
  { key: 'metalness', label: '金属度', type: 'range', min: 0, max: 1, step: 0.01 },
  { key: 'alpha', label: '不透明度', type: 'range', min: 0, max: 1, step: 0.01 },
  { key: 'transmission', label: '透射', type: 'range', min: 0, max: 1, step: 0.01 },
  { key: 'ior', label: '折射率', type: 'range', min: 1, max: 2.5, step: 0.01 },
  { key: 'emission', label: '自发光色', type: 'color' },
  { key: 'emission_strength', label: '自发光强度', type: 'range', min: 0, max: 12, step: 0.1 },
]

const FIELD_KEYS = new Set(FIELDS.map((f) => f.key))

/**
 * 功能: 把 #RGB / #RRGGBB / 带空格的写法规整成大写 #RRGGBB.
 * @param {string} value 颜色字符串
 * @returns {string|null} 规整后的颜色; 非法返回 null
 */
export function normalizeHex(value) {
  if (typeof value !== 'string') return null
  const text = value.trim().replace(/^#/, '')
  if (/^[0-9a-f]{3}$/i.test(text)) {
    return `#${text.split('').map((c) => c + c).join('').toUpperCase()}`
  }
  if (/^[0-9a-f]{6}$/i.test(text)) return `#${text.toUpperCase()}`
  return null
}

/**
 * 功能: 校验并规整一条覆盖补丁, 丢掉不认识的字段与越界的值.
 *
 * 面板是唯一写入口, 但 YAML 也允许手改, 所以读回来时要防脏数据 ——
 * 一个越界的 roughness 会让整台机器看起来"莫名其妙不对", 且极难排查.
 *
 * @param {object} patch 原始补丁
 * @returns {object} 规整后的补丁(可能为空对象)
 */
export function sanitizePatch(patch) {
  const clean = {}
  if (!patch || typeof patch !== 'object') return clean

  for (const field of FIELDS) {
    if (!(field.key in patch)) continue
    const raw = patch[field.key]
    if (field.type === 'color') {
      const hex = normalizeHex(raw)
      if (hex) clean[field.key] = hex
      continue
    }
    const num = Number(raw)
    if (!Number.isFinite(num)) continue
    clean[field.key] = Math.min(field.max, Math.max(field.min, num))
  }
  return clean
}

export class OverrideModel {
  /**
   * 功能: 建立一个空的覆盖模型.
   */
  constructor() {
    /** @type {Map<string, object>} 材质名 -> 补丁 */
    this.entries = new Map()
    /** 每次变更自增, 供场景侧判断是否需要重新上色 */
    this.version = 0
    /** @type {Array<Map<string, object>>} 撤销栈 */
    this._undo = []
  }

  /**
   * 功能: 从 appearance_overrides 段装入.
   * @param {object} section YAML 里的 appearance_overrides
   * @returns {number} 装入的条数
   */
  load(section) {
    this.entries.clear()
    for (const [name, patch] of Object.entries(section || {})) {
      const clean = sanitizePatch(patch)
      if (Object.keys(clean).length) this.entries.set(name, clean)
    }
    this.version += 1
    this._undo.length = 0
    return this.entries.size
  }

  /**
   * 功能: 取某材质当前的覆盖补丁.
   * @param {string} name 材质名
   * @returns {object} 补丁副本(可能为空)
   */
  get(name) {
    return { ...(this.entries.get(name) || {}) }
  }

  /**
   * 功能: 改一个字段. 传 null 表示清掉该字段(回到规则原值).
   * @param {string} name 材质名
   * @param {string} key 字段名
   * @param {string|number|null} value 值
   * @returns {void}
   */
  set(name, key, value) {
    if (!FIELD_KEYS.has(key)) return
    this._pushUndo()

    const patch = { ...(this.entries.get(name) || {}) }
    if (value === null || value === undefined || value === '') {
      delete patch[key]
    } else {
      const clean = sanitizePatch({ [key]: value })
      if (!(key in clean)) return
      patch[key] = clean[key]
    }

    if (Object.keys(patch).length) this.entries.set(name, patch)
    else this.entries.delete(name)
    this.version += 1
  }

  /**
   * 功能: 一次设置多个字段(预设/复制参数用), 只记一步撤销.
   *
   * 逐字段调 set() 会把一次"应用预设"拆成 N 步撤销, 用户按一次撤销只回退一个
   * 滑块, 体验是坏的; 这里单快照批量写入, 撤销一步整体回退.
   *
   * @param {string} name 材质名
   * @param {object} patch 字段补丁(经 sanitizePatch 清洗, 非法字段丢弃)
   * @returns {number} 实际写入的字段数
   */
  setMany(name, patch) {
    const clean = sanitizePatch(patch)
    const keys = Object.keys(clean)
    if (!keys.length) return 0
    this._pushUndo()
    this.entries.set(name, { ...(this.entries.get(name) || {}), ...clean })
    this.version += 1
    return keys.length
  }

  /**
   * 功能: 清掉某材质的全部覆盖, 回到规则原值.
   * @param {string} name 材质名
   * @returns {void}
   */
  reset(name) {
    if (!this.entries.has(name)) return
    this._pushUndo()
    this.entries.delete(name)
    this.version += 1
  }

  /**
   * 功能: 清掉全部覆盖.
   * @returns {void}
   */
  resetAll() {
    if (!this.entries.size) return
    this._pushUndo()
    this.entries.clear()
    this.version += 1
  }

  /**
   * 功能: 撤销上一步.
   * @returns {boolean} 是否发生了撤销
   */
  undo() {
    const previous = this._undo.pop()
    if (!previous) return false
    this.entries = previous
    this.version += 1
    return true
  }

  /**
   * 功能: 记一份快照进撤销栈(最多留 50 步).
   * @returns {void}
   */
  _pushUndo() {
    this._undo.push(new Map([...this.entries].map(([k, v]) => [k, { ...v }])))
    if (this._undo.length > 50) this._undo.shift()
  }

  /**
   * 功能: 导出成可写回 YAML 的普通对象, 键已排序以保证产物可 diff.
   * @returns {object} appearance_overrides 段
   */
  toSection() {
    const out = {}
    for (const name of [...this.entries.keys()].sort()) {
      const patch = this.entries.get(name)
      const ordered = {}
      // 字段也按固定顺序输出, 免得每次保存都产生无意义的 diff
      for (const field of FIELDS) {
        if (field.key in patch) ordered[field.key] = patch[field.key]
      }
      out[name] = ordered
    }
    return out
  }
}
