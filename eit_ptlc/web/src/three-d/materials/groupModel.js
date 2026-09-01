/**
 * 功能: 材质组的数据模型 —— "工程师定义合并规则"的前端载体.
 *
 * 一个组 = 一批零件(glTF 原名) + 一份观感参数(8 字段子集). 语义: 组内成员共享
 * 一个专属材质实例(管线侧 MAT_GROUP_<slug>), 重跑后按工位合并成同一 STATIC 块 ——
 * 这正是"哪些零件合并在一起"的决定权.
 *
 * 生效叠加序(与管线一致): 材质类 ⊂ 材质组(part_groups) ⊂ 单件覆盖(part_overrides).
 * 组底 = parts 列表首个可解析成员的类材质快照 ⊕ 组参数(两侧同一规则).
 *
 * 实现: 参数复用 OverrideModel(键=组名, sanitize/字段序/白名单全白拿), 成员另存
 * Map<组名, parts[]>; makeSectionPatcher 只认 toSection(), 本类合并输出
 * {组名: {parts: [...], 字段...}}. 一零件至多属一组(入新组自动离旧组).
 */
import { FIELDS, OverrideModel, sanitizePatch } from './overrideModel.js'

export class GroupModel {
  /**
   * 功能: 建一个空的组模型.
   */
  constructor() {
    /** 组参数(键=组名), 撤销/清洗/排序全复用 */
    this.params = new OverrideModel()
    /** @type {Map<string, string[]>} 组名 -> 成员原名列表(保序去重) */
    this.parts = new Map()
    /** 变更版本号(视图 tick 扳机) */
    this.version = 0
    /** @type {Array<{parts: Array, params: Map}>} 结构+参数联合撤销栈 */
    this._undo = []
  }

  /**
   * 功能: 从 part_groups 段装入.
   * @param {object} section {组名: {parts: [...], 字段...}}
   * @returns {number} 装入的组数
   */
  load(section) {
    this.parts.clear()
    const paramSection = {}
    for (const [name, entry] of Object.entries(section || {})) {
      if (!entry || typeof entry !== 'object') continue
      const parts = [...new Set((entry.parts || []).map((p) => String(p).trim()).filter(Boolean))]
      if (!parts.length) continue
      this.parts.set(name, parts)
      const patch = sanitizePatch(entry)
      if (Object.keys(patch).length) paramSection[name] = patch
    }
    this.params.load(paramSection)
    this._undo.length = 0
    this.version += 1
    return this.parts.size
  }

  /**
   * 功能: 记联合快照(结构+参数)进撤销栈.
   * @returns {void}
   */
  _snapshot() {
    this._undo.push({
      parts: [...this.parts].map(([k, v]) => [k, [...v]]),
      params: new Map([...this.params.entries].map(([k, v]) => [k, { ...v }])),
    })
    if (this._undo.length > 50) this._undo.shift()
  }

  /**
   * 功能: 撤销上一步(结构与参数一起回退).
   * @returns {boolean} 是否发生了撤销
   */
  undo() {
    const snapshot = this._undo.pop()
    if (!snapshot) return false
    this.parts = new Map(snapshot.parts)
    this.params.entries = snapshot.params
    this.params.version += 1
    this.version += 1
    return true
  }

  /**
   * 功能: 从其他组摘除一批成员(单一隶属的执行处; 空组顺带删除).
   * @param {string[]} names 成员原名
   * @param {string} [except] 豁免的组名
   * @returns {void}
   */
  _evict(names, except) {
    const set = new Set(names)
    for (const [group, members] of this.parts) {
      if (group === except) continue
      const kept = members.filter((m) => !set.has(m))
      if (kept.length !== members.length) {
        if (kept.length) this.parts.set(group, kept)
        else {
          this.parts.delete(group)
          this.params.entries.delete(group)
        }
      }
    }
  }

  /**
   * 功能: 新建组.
   * @param {string} name 组名
   * @param {string[]} parts 成员原名
   * @returns {boolean} 是否成功(重名/空名/空成员拒绝)
   */
  createGroup(name, parts) {
    const trimmed = String(name || '').trim()
    const clean = [...new Set((parts || []).map((p) => String(p).trim()).filter(Boolean))]
    if (!trimmed || this.parts.has(trimmed) || !clean.length) return false
    this._snapshot()
    this._evict(clean, trimmed)
    this.parts.set(trimmed, clean)
    this.version += 1
    return true
  }

  /**
   * 功能: 往既有组追加成员.
   * @param {string} name 组名
   * @param {string[]} parts 成员原名
   * @returns {number} 实际新增数
   */
  addParts(name, parts) {
    const members = this.parts.get(name)
    if (!members) return 0
    const clean = (parts || []).map((p) => String(p).trim()).filter(Boolean)
    const fresh = [...new Set(clean)].filter((p) => !members.includes(p))
    if (!fresh.length) return 0
    this._snapshot()
    this._evict(fresh, name)
    this.parts.set(name, [...(this.parts.get(name) || members), ...fresh])
    this.version += 1
    return fresh.length
  }

  /**
   * 功能: 从组里移除一个成员(组空即删组).
   * @param {string} name 组名
   * @param {string} part 成员原名
   * @returns {boolean} 是否移除了
   */
  removePart(name, part) {
    const members = this.parts.get(name)
    if (!members || !members.includes(part)) return false
    this._snapshot()
    const kept = members.filter((m) => m !== part)
    if (kept.length) this.parts.set(name, kept)
    else {
      this.parts.delete(name)
      this.params.entries.delete(name)
    }
    this.version += 1
    return true
  }

  /**
   * 功能: 解散一个组.
   * @param {string} name 组名
   * @returns {boolean} 是否删除了
   */
  removeGroup(name) {
    if (!this.parts.has(name)) return false
    this._snapshot()
    this.parts.delete(name)
    this.params.entries.delete(name)
    this.params.version += 1
    this.version += 1
    return true
  }

  /**
   * 功能: 反查一个零件所属的组.
   * @param {string} savedName 零件原名
   * @returns {string|null} 组名
   */
  groupOfPart(savedName) {
    for (const [group, members] of this.parts) {
      if (members.includes(savedName)) return group
    }
    return null
  }

  /**
   * 功能: 取组成员(副本).
   * @param {string} name 组名
   * @returns {string[]} 成员原名
   */
  partsOf(name) {
    return [...(this.parts.get(name) || [])]
  }

  /**
   * 功能: 全部组名.
   * @returns {string[]} 组名数组
   */
  names() {
    return [...this.parts.keys()]
  }

  /**
   * 功能: 改组参数(薄代理; 撤销走 params 自己的栈 —— 参数改动不含结构).
   * @param {string} name 组名
   * @param {string} key 字段
   * @param {*} value 值
   * @returns {void}
   */
  setParam(name, key, value) {
    if (!this.parts.has(name)) return
    this.params.set(name, key, value)
    this.version += 1
  }

  /**
   * 功能: 批量改组参数(预设用).
   * @param {string} name 组名
   * @param {object} patch 补丁
   * @returns {number} 写入字段数
   */
  setParams(name, patch) {
    if (!this.parts.has(name)) return 0
    const n = this.params.setMany(name, patch)
    if (n) this.version += 1
    return n
  }

  /**
   * 功能: 取组参数.
   * @param {string} name 组名
   * @returns {object} 补丁副本
   */
  getParams(name) {
    return this.params.get(name)
  }

  /**
   * 功能: 清掉组参数(成员保留).
   * @param {string} name 组名
   * @returns {void}
   */
  resetParams(name) {
    this.params.reset(name)
    this.version += 1
  }

  /**
   * 功能: 导出成 part_groups 段(组名排序, parts 保序, 字段按 FIELDS 序).
   * @returns {object} 段内容
   */
  toSection() {
    const out = {}
    for (const name of [...this.parts.keys()].sort()) {
      const patch = this.params.get(name)
      const ordered = { parts: [...this.parts.get(name)] }
      for (const field of FIELDS) {
        if (field.key in patch) ordered[field.key] = patch[field.key]
      }
      out[name] = ordered
    }
    return out
  }
}
