/**
 * 功能: 孤立清单的数据模型 —— "只脱离静态合并、不改观感"的零件名集合.
 *
 * 与 OverrideModel 同构: 浏览器只写"意图", 落成 material_semantics.yaml 的
 * part_isolate 段(字符串列表), 管线的 apply_part_isolate 据此给零件换专属实例
 * MAT_SOLO_<slug>, 使其在静态合并时自然独立. 重跑后该零件成为可寻址的独立节点.
 *
 * 名字一律存剥掉 Blender 重名后缀 .00N 的 base 名 —— 后缀跨次运行会漂移, base 名
 * 才稳定; 同 base 的多个实例会被管线一并孤立(调用方负责向用户提示数量).
 */

import { baseName } from './memberIndex.js'

export class IsolateModel {
  /**
   * 功能: 建立一个空的孤立清单.
   */
  constructor() {
    /** @type {Set<string>} 零件 base 名集合 */
    this.names = new Set()
    /** 每次变更自增, 供 computed 侧判断是否需要刷新 */
    this.version = 0
    /** @type {Array<Set<string>>} 撤销栈 */
    this._undo = []
  }

  /**
   * 功能: 从 part_isolate 段装入(列表正写法; 手改成 map 时取键; 缺段传空对象也可).
   * @param {Array|object|null} section YAML 里的 part_isolate
   * @returns {number} 装入的条数
   */
  load(section) {
    this.names.clear()
    const raw = Array.isArray(section) ? section : Object.keys(section || {})
    for (const item of raw) {
      const base = baseName(String(item).trim())
      if (base) this.names.add(base)
    }
    this.version += 1
    this._undo.length = 0
    return this.names.size
  }

  /**
   * 功能: 判断某零件是否已标孤立.
   * @param {string} name 零件名(可带 .00N)
   * @returns {boolean} 是否已标
   */
  has(name) {
    return this.names.has(baseName(name))
  }

  /**
   * 功能: 标记孤立.
   * @param {string} name 零件名(可带 .00N, 内部剥后缀)
   * @returns {boolean} 是否发生了变化
   */
  add(name) {
    const base = baseName(String(name || '').trim())
    if (!base || this.names.has(base)) return false
    this._pushUndo()
    this.names.add(base)
    this.version += 1
    return true
  }

  /**
   * 功能: 取消孤立标记.
   * @param {string} name 零件名(可带 .00N)
   * @returns {boolean} 是否发生了变化
   */
  remove(name) {
    const base = baseName(name)
    if (!this.names.has(base)) return false
    this._pushUndo()
    this.names.delete(base)
    this.version += 1
    return true
  }

  /**
   * 功能: 撤销上一步.
   * @returns {boolean} 是否发生了撤销
   */
  undo() {
    const previous = this._undo.pop()
    if (!previous) return false
    this.names = previous
    this.version += 1
    return true
  }

  /**
   * 功能: 记一份快照进撤销栈(最多留 50 步, 与 OverrideModel 同限).
   * @returns {void}
   */
  _pushUndo() {
    this._undo.push(new Set(this.names))
    if (this._undo.length > 50) this._undo.shift()
  }

  /**
   * 功能: 导出成可写回 YAML 的字符串数组, 排序以保证产物可 diff.
   * @returns {string[]} part_isolate 段
   */
  toSection() {
    return [...this.names].sort()
  }
}
