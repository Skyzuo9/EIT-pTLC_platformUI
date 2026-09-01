/**
 * 功能: 工作台的选择与标记模型 —— 管"用户点了哪些零件、把它们标成了什么".
 *
 * 与三维场景解耦: 这里只处理节点名与标记, 不碰 three 对象. 场景那边按标记去改可见性
 * 和材质, 两边通过节点名对接. 这样标记逻辑可以单测, 也能在没有 WebGL 的环境里跑.
 *
 * 四种标记:
 *   delete   删除 —— 写进 prune_list.yaml 的 explicit_delete
 *   keep     强制保留 —— 写进 explicit_keep, 优先级高于所有正则删减规则
 *   decimate 减面 —— 写进 explicit_decimate, 带一个保留比例
 *   (无标记) 待定 —— 交给现有的正则规则决定
 */

/** 标记种类 */
export const MARKS = {
  DELETE: 'delete',
  KEEP: 'keep',
  DECIMATE: 'decimate',
}

/** 标记的显示配置(颜色供三维高亮与列表色块共用) */
export const MARK_STYLES = {
  [MARKS.DELETE]: { label: '删除', color: '#ff5c5c', opacity: 0.12 },
  [MARKS.KEEP]: { label: '保留', color: '#39d98a', opacity: 1 },
  [MARKS.DECIMATE]: { label: '减面', color: '#f4b740', opacity: 1 },
}

/** MARK_STYLES 的数值色形态(three 的 setHex 用), 与树色点同源, 保证两侧必然同色 */
export const MARK_TINTS = Object.fromEntries(
  Object.entries(MARK_STYLES).map(([mark, style]) => [
    mark,
    parseInt(style.color.slice(1), 16),
  ]),
)

/**
 * 功能: 求一个零件的"标记状态" —— 树色点与三维着色共用的单一判定.
 *
 * 显式标记(删/留/减面)优先; 无显式标记但落进有效删除集(正则/尺寸规则命中)的
 * 也算 delete —— 这样规则命中的几百个紧固件在树里同样带红点, 与三维着色一致,
 * 前端工程师才能一眼看清删减策略的真实覆盖面.
 *
 * @param {SelectionModel} model 选择模型
 * @param {Set<string>|null} effectiveDeletes 有效删除集(evalEffectiveDeletes 产物)
 * @param {string} key 零件索引键
 * @returns {string|null} MARKS 之一; 无标记返回 null
 */
export function markStateOf(model, effectiveDeletes, key) {
  const mark = model?.markOf(key)?.mark
  if (mark) return mark
  return effectiveDeletes?.has(key) ? MARKS.DELETE : null
}

export class SelectionModel {
  /**
   * 功能: 初始化.
   * @param {object} [options] 可选项
   * @param {number} [options.defaultDecimateRatio=0.3] 减面标记的默认保留比例
   */
  constructor({ defaultDecimateRatio = 0.3 } = {}) {
    /** @type {Map<string, {mark: string, ratio?: number}>} 节点名 -> 标记 */
    this.marks = new Map()
    /** @type {Set<string>} 当前高亮选中的节点名(与标记无关, 只是"正在看") */
    this.selected = new Set()
    this.defaultDecimateRatio = defaultDecimateRatio
    /** 变更版本号, 供视图判断是否需要重绘 */
    this.version = 0
    /** @type {Array<{marks: Array, selected: Array}>} 撤销栈 */
    this._undo = []
  }

  /**
   * 功能: 记一次快照, 供撤销.
   * @returns {void}
   */
  _snapshot() {
    this._undo.push({
      marks: [...this.marks.entries()].map(([k, v]) => [k, { ...v }]),
      selected: [...this.selected],
    })
    // 撤销栈不必无限长; 授权操作是低频的, 50 步足够
    if (this._undo.length > 50) this._undo.shift()
  }

  /**
   * 功能: 撤销上一次操作.
   * @returns {boolean} 是否有可撤销的操作
   */
  undo() {
    const snapshot = this._undo.pop()
    if (!snapshot) return false
    this.marks = new Map(snapshot.marks)
    this.selected = new Set(snapshot.selected)
    this.version += 1
    return true
  }

  // -- 选择 --------------------------------------------------------------

  /**
   * 功能: 设置当前选中集.
   * @param {string[]} names 节点名数组
   * @returns {void}
   */
  select(names) {
    this.selected = new Set(names)
    this.version += 1
  }

  /**
   * 功能: 切换单个节点的选中态(Ctrl+点击的语义).
   * @param {string} name 节点名
   * @returns {void}
   */
  toggle(name) {
    if (this.selected.has(name)) this.selected.delete(name)
    else this.selected.add(name)
    this.version += 1
  }

  /**
   * 功能: 清空选中集(不影响标记).
   * @returns {void}
   */
  clearSelection() {
    this.selected.clear()
    this.version += 1
  }

  // -- 标记 --------------------------------------------------------------

  /**
   * 功能: 给当前选中集打标记.
   * @param {string} mark MARKS 之一; 传 null 表示清除标记(回到"待定")
   * @param {number} [ratio] 减面比例(仅 DECIMATE 有意义)
   * @returns {number} 受影响的节点数
   */
  markSelected(mark, ratio) {
    if (!this.selected.size) return 0
    this._snapshot()
    for (const name of this.selected) {
      if (mark === null) this.marks.delete(name)
      else {
        this.marks.set(name, {
          mark,
          ...(mark === MARKS.DECIMATE
            ? { ratio: ratio ?? this.defaultDecimateRatio }
            : {}),
        })
      }
    }
    this.version += 1
    return this.selected.size
  }

  /**
   * 功能: 给一批节点直接打标记(按规则批选时用).
   * @param {string[]} names 节点名数组
   * @param {string} mark 标记
   * @param {number} [ratio] 减面比例
   * @returns {number} 受影响的节点数
   */
  markNames(names, mark, ratio) {
    if (!names.length) return 0
    this._snapshot()
    for (const name of names) {
      if (mark === null) this.marks.delete(name)
      else {
        this.marks.set(name, {
          mark,
          ...(mark === MARKS.DECIMATE ? { ratio: ratio ?? this.defaultDecimateRatio } : {}),
        })
      }
    }
    this.version += 1
    return names.length
  }

  /**
   * 功能: 取某节点的标记.
   * @param {string} name 节点名
   * @returns {{mark: string, ratio?: number}|undefined} 标记
   */
  markOf(name) {
    return this.marks.get(name)
  }

  /**
   * 功能: 按标记种类取节点名列表.
   * @param {string} mark 标记
   * @returns {string[]} 节点名数组(已排序, 保证写出的 YAML 稳定可 diff)
   */
  namesWithMark(mark) {
    return [...this.marks.entries()]
      .filter(([, value]) => value.mark === mark)
      .map(([name]) => name)
      .sort()
  }

  /**
   * 功能: 统计各标记的数量.
   * @returns {{delete: number, keep: number, decimate: number, total: number}} 计数
   */
  counts() {
    const result = { delete: 0, keep: 0, decimate: 0, total: this.marks.size }
    for (const value of this.marks.values()) result[value.mark] += 1
    return result
  }

  /**
   * 功能: 清空全部标记.
   * @returns {void}
   */
  clearMarks() {
    this._snapshot()
    this.marks.clear()
    this.version += 1
  }
}

/**
 * 功能: 从既有的 prune_list.yaml 内容里恢复标记, 使工作台重开后还能接着上次改.
 *
 * yaml 里存的是 GLB 的原始节点名, 而索引为保证唯一给同名节点加了 `#2` 后缀,
 * 因此要把一个名字展开回它对应的所有索引键 —— 这也符合语义:
 * "删掉这个型号的螺栓"本来就该对全部同名实例生效.
 *
 * @param {object} pruneConfig 已解析的 prune_list 配置
 * @param {SelectionModel} model 目标模型
 * @param {import('./PartIndex.js').PartIndex} [index] 零件索引; 缺省则按原名直接标记
 * @returns {number} 恢复的标记数
 */
export function restoreMarks(pruneConfig, model, index) {
  /**
   * 功能: 把一个原始节点名展开成它对应的全部索引键.
   * @param {string} name 原始节点名
   * @returns {string[]} 索引键数组
   */
  const expand = (name) => {
    if (!index) return [name]
    // 新格式存 glTF 原名, 旧格式存 three 名 —— PartIndex 两种都认
    const keys = index.keysForSavedName
      ? index.keysForSavedName(name)
      : index.allNames.filter((key) => key === name || key.startsWith(`${name}#`))
    return keys.length ? keys : [name]
  }

  let count = 0
  for (const name of pruneConfig?.explicit_delete || []) {
    for (const key of expand(name)) {
      model.marks.set(key, { mark: MARKS.DELETE })
      count += 1
    }
  }
  for (const name of pruneConfig?.explicit_keep || []) {
    for (const key of expand(name)) {
      model.marks.set(key, { mark: MARKS.KEEP })
      count += 1
    }
  }
  for (const entry of pruneConfig?.explicit_decimate || []) {
    if (!entry?.name) continue
    for (const key of expand(entry.name)) {
      model.marks.set(key, { mark: MARKS.DECIMATE, ratio: entry.ratio ?? 0.3 })
      count += 1
    }
  }
  model.version += 1
  return count
}
