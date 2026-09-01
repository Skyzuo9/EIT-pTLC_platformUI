/**
 * 功能: 零件索引 —— 把原始 GLB 的两千多个节点整理成可搜索、可批选、可统计的清单.
 *
 * 工作台加载的是**未优化的原始模型**(2271 节点 / 2024 网格), 因为要点选到单个零件.
 * 代价是绘制调用数很高(约 2000), 帧率会掉到 30~45 —— 对授权工具而言完全可以接受,
 * 而且它换来的是"你点的就是管线里那个名字", 中间没有任何转译.
 *
 * 索引粒度: **每一个在子树里含有几何的节点都是一个可选中的零件**.
 * 早期版本只索引到第二层, 结果紧固件、拖链节这些真正想批量删掉的东西全在更深处,
 * 规则批选一个也命中不了 —— 那正是这个工具最该干的活.
 *
 * 父子重复计数的处理: 每个节点同时记录
 *   own*     —— 直接挂在自己身上的网格(不含后代)
 *   subtree* —— 含全部后代的总量
 * 统计规模时从根往下走并只累加 own*, 因此不会重复; 删除一个节点则整棵子树一起消失.
 */
import * as THREE from 'three'

/** OCCT 给未命名供应商件起的自动名, 是批量删减的主要靶子 */
const VENDOR_AUTO = /Open[_ ]CASCADE[_ ]STEP[_ ]translator/i

/** 临时复用对象, 避免建索引时产生大量垃圾 */
const TMP_BOX = new THREE.Box3()
const TMP_SIZE = new THREE.Vector3()

export class PartIndex {
  /**
   * 功能: 遍历模型建立索引.
   * @param {THREE.Object3D} root 模型根节点
   * @param {Map<string, string>} [chineseNames] slug -> 中文原名
   */
  constructor(root, chineseNames = new Map()) {
    /** @type {Map<string, object>} 零件名 -> 零件信息 */
    this.parts = new Map()
    /** @type {Map<THREE.Object3D, string>} 网格 -> 所属零件名(拾取用) */
    this.ownerOf = new Map()
    /** @type {object[]} 顶层装配, 按子树三角形数降序 */
    this.assemblies = []
    /** @type {string[]} 全部零件名, 供规则查询遍历 */
    this.allNames = []

    this.root = root
    this.chineseNames = chineseNames
    /**
     * @type {Map<string, string>} 中文原名 -> 拼音 slug 的反查表.
     * 原生 GLB 的节点是中文名, 而 prune_list/批选预设的正则多为拼音 ——
     * 管线侧靠 name_variants 的别名表命中, 浏览器侧靠这张反查表对齐口径.
     */
    this.slugOf = new Map()
    for (const [slug, chinese] of chineseNames) {
      if (chinese && !this.slugOf.has(chinese)) this.slugOf.set(chinese, slug)
    }
    this._build(root)
  }

  /**
   * 功能: 求节点的拼音别名(slug). names.csv 存的是产品名, 实例名带 `-N` 后缀,
   * 逐段剥掉尾部 `-数字` 再查, 直到命中或剥无可剥.
   * @param {string} origName glTF 原名
   * @param {string} baseName three 名
   * @returns {string} 拼音 slug; 查不到为空串
   */
  _aliasFor(origName, baseName) {
    if (!this.slugOf.size) return ''
    for (const start of [origName, baseName]) {
      let candidate = start
      while (candidate) {
        const slug = this.slugOf.get(candidate)
        if (slug) return slug
        const stripped = candidate.replace(/-\d+$/, '')
        if (stripped === candidate) break
        candidate = stripped
      }
    }
    return ''
  }

  /**
   * 功能: 建立索引.
   * @param {THREE.Object3D} root 根节点
   * @returns {void}
   */
  _build(root) {
    root.updateMatrixWorld(true)

    // 一路穿过"只有一个孩子"的包装层, 直到遇到真正分叉的那一层.
    // 加载器包了一层 MACHINE_ROOT, glTF 自己包了一层 scene, CAD 又有一层总装根 ——
    // 只下探固定层数会漏, 循环下探才能稳定命中那 45 个顶层装配.
    let container = root
    while (container.children.length === 1 && container.children[0].children.length > 0) {
      container = container.children[0]
    }
    const topLevel = container.children

    for (const node of topLevel) {
      const info = this._visit(node, null, 0)
      if (info && info.subtreeTriangles > 0) this.assemblies.push(info)
    }
    this.assemblies.sort((a, b) => b.subtreeTriangles - a.subtreeTriangles)
  }

  /**
   * 功能: 递归访问一个节点, 登记为零件并回传其统计.
   * @param {THREE.Object3D} node 节点
   * @param {string|null} parentName 父零件名
   * @param {number} depth 层级深度
   * @returns {object|null} 零件信息; 子树无几何时返回 null
   */
  _visit(node, parentName, depth) {
    // 同名节点在 GLB 里是可能存在的(同一零件用了多次); 加后缀保证索引键唯一,
    // 但 baseName 保持原样, 写回 yaml 时用它 —— 管线侧按基础名匹配整族实例
    const baseName = node.name || `_node_${node.id}`
    let key = baseName
    let suffix = 2
    while (this.parts.has(key)) key = `${baseName}#${suffix++}`

    let ownMeshes = 0
    let ownTriangles = 0
    TMP_BOX.makeEmpty()

    // 只统计直接挂在本节点上的网格; 后代的量由递归回传
    const collectOwn = (object) => {
      if (!object.isMesh || !object.geometry) return
      ownMeshes += 1
      this.ownerOf.set(object, key)
      const geometry = object.geometry
      const count = geometry.index
        ? geometry.index.count
        : geometry.attributes.position?.count || 0
      ownTriangles += Math.floor(count / 3)
      if (!geometry.boundingBox) geometry.computeBoundingBox()
      if (geometry.boundingBox) {
        TMP_BOX.union(geometry.boundingBox.clone().applyMatrix4(object.matrixWorld))
      }
    }
    if (node.isMesh) collectOwn(node)

    const childNames = []
    let subtreeMeshes = ownMeshes
    let subtreeTriangles = ownTriangles
    const subtreeBox = TMP_BOX.clone()

    for (const child of node.children) {
      const info = this._visit(child, key, depth + 1)
      if (!info) continue
      childNames.push(info.key)
      subtreeMeshes += info.subtreeMeshes
      subtreeTriangles += info.subtreeTriangles
      if (info.box && !info.box.isEmpty()) subtreeBox.union(info.box)
    }

    // 子树里一点几何都没有的节点(纯变换空节点)不登记, 免得树里全是空壳
    if (subtreeTriangles === 0 && subtreeMeshes === 0) return null

    const size = subtreeBox.isEmpty() ? TMP_SIZE.set(0, 0, 0) : subtreeBox.getSize(new THREE.Vector3())
    const info = {
      key,
      name: baseName,
      object: node,
      depth,
      parentName,
      childNames,
      ownMeshes,
      ownTriangles,
      subtreeMeshes,
      subtreeTriangles,
      box: subtreeBox,
      // 场景已归一到米, 这里统一换成毫米便于人读("这零件才 4 毫米")
      sizeMm: [size.x * 1000, size.y * 1000, size.z * 1000],
      longestMm: Math.max(size.x, size.y, size.z) * 1000,
      chinese: this.chineseNames.get(baseName) || '',
      // glTF 原名(three 加载时会把空格消毒成下划线); 写 prune 名单必须用它(硬约束 27)
      origName: node.userData?.origName || baseName,
      isVendorAuto: VENDOR_AUTO.test(baseName),
    }
    // 拼音别名: 原生 GLB 是中文名, prune/批选的拼音正则靠它命中(对齐管线 name_variants)
    info.alias = this._aliasFor(info.origName, baseName)

    this.parts.set(key, info)
    this.allNames.push(key)
    return info
  }

  /**
   * 功能: 按拾取到的网格反查零件名.
   * @param {THREE.Object3D} mesh 网格
   * @returns {string|undefined} 零件名
   */
  ownerOfMesh(mesh) {
    return this.ownerOf.get(mesh)
  }

  /**
   * 功能: 索引键(或基础名) -> 写盘用的 glTF 原名.
   *
   * three 名与原名在含空格等字符时不同; prune 名单写 three 名的话
   * Blender 侧按名匹配会 0 命中且毫无报错(踩过).
   *
   * @param {string} key 索引键或基础名
   * @returns {string} glTF 原名
   */
  savedNameOf(key) {
    const base = key.includes('#') ? key.slice(0, key.indexOf('#')) : key
    return this.parts.get(base)?.origName || base
  }

  /**
   * 功能: 把 yaml 里保存的名字展开成对应的全部索引键.
   *
   * 兼容两代格式: 新格式存 glTF 原名(按 origName 匹配), 旧格式存 three 名
   * (按 name/键匹配); "删这个型号"要对全部同名实例生效.
   *
   * @param {string} name 保存的名字
   * @returns {string[]} 索引键数组
   */
  keysForSavedName(name) {
    const hits = []
    for (const [key, part] of this.parts) {
      if (part.origName === name || part.name === name) hits.push(key)
    }
    return hits
  }

  /**
   * 功能: 取零件信息.
   * @param {string} key 零件索引键
   * @returns {object|undefined} 零件信息
   */
  get(key) {
    return this.parts.get(key)
  }

  /**
   * 功能: 取一个零件的子零件信息数组(按面数降序).
   * @param {string} key 零件索引键
   * @returns {object[]} 子零件
   */
  childrenOf(key) {
    const part = this.parts.get(key)
    if (!part) return []
    return part.childNames
      .map((name) => this.parts.get(name))
      .filter(Boolean)
      .sort((a, b) => b.subtreeTriangles - a.subtreeTriangles)
  }

  /**
   * 功能: 给定一组被隐藏的网格, 算出"整棵子树都被藏起"的零件键集合.
   *
   * 供层级树画闭眼图标: 只有子树里每一个网格都在隐藏台账里, 该零件才算隐藏 ——
   * 部分子件被藏的父装配不算(它在三维里还能看到剩余部分).
   * 空节点无空真陷阱: 索引只登记子树含几何的节点(_visit 末尾过滤),
   * 而自有网格就是 part.object 本身(0 或 1 个).
   *
   * @param {{has(object: THREE.Object3D): boolean}} hiddenMeshes 隐藏网格集(Set/Map 均可)
   * @returns {Set<string>} 被整体隐藏的零件键
   */
  hiddenKeys(hiddenMeshes) {
    const result = new Set()
    const walk = (key) => {
      const part = this.parts.get(key)
      if (!part) return true
      let hidden = !part.object.isMesh || hiddenMeshes.has(part.object)
      for (const childKey of part.childNames) {
        // 不能短路: 本层已确定可见时, 深处仍可能有整棵被藏的子件要标记
        if (!walk(childKey)) hidden = false
      }
      if (hidden) result.add(key)
      return hidden
    }
    for (const assembly of this.assemblies) walk(assembly.key)
    return result
  }

  /**
   * 功能: 按规则批量选择零件.
   *
   * 规则查询是精简模型的主力: 螺栓垫圈、拖链节、供应商无名件动辄成百上千个,
   * 逐个点选不现实.
   *
   * @param {object} rule 规则
   * @param {string} [rule.pattern] 名称正则(不区分大小写), 中文原名也参与匹配
   * @param {number} [rule.maxLongestMm] 最长边小于此值
   * @param {number} [rule.minTriangles] 子树三角形数大于此值
   * @param {boolean} [rule.vendorAutoOnly] 只要 OCCT 自动命名件
   * @param {boolean} [rule.leafOnly=true] 只要叶子零件(没有再往下的子零件)
   * @returns {string[]} 命中的零件索引键
   */
  query(rule = {}) {
    let regex = null
    if (rule.pattern) {
      try {
        regex = new RegExp(rule.pattern, 'i')
      } catch {
        return [] // 用户还在输入中的半截正则, 静默返回空而不是报错
      }
    }
    const leafOnly = rule.leafOnly !== false

    const hits = []
    for (const key of this.allNames) {
      const part = this.parts.get(key)
      if (!part) continue
      // 默认只选叶子: 选中一个父节点会连带整棵子树, 规则批选时那通常不是本意
      if (leafOnly && part.childNames.length > 0) continue
      if (rule.vendorAutoOnly && !part.isVendorAuto) continue
      if (rule.maxLongestMm !== undefined && part.longestMm >= rule.maxLongestMm) continue
      if (rule.minTriangles !== undefined && part.subtreeTriangles <= rule.minTriangles) continue
      if (
        regex &&
        !regex.test(part.name) &&
        !regex.test(part.chinese) &&
        !(part.alias && regex.test(part.alias))
      ) {
        continue
      }
      hits.push(key)
    }
    return hits
  }

  /**
   * 功能: 统计当前规模, 以及预估删减后的规模.
   *
   * 从顶层往下走累加自有几何, 父子不重复计数. 剪枝口径二选一:
   *   - 传入 effectiveDeletes(pruneEval 的有效删除集, 含正则与尺寸阈值)时按集合判剪,
   *     且**不整树剪断** —— 被"保留"豁免的子件可能存活于被删祖先之下, 必须继续下走;
   *   - 缺省时保持旧口径: 只认显式删除标记, 命中即整棵子树跳过.
   * 减面始终按显式标记估算(正则减面规则不参与, 属已知近似).
   *
   * @param {import('./selectionModel.js').SelectionModel} model 选择模型
   * @param {Set<string>|null} [effectiveDeletes] 有效删除集(索引键)
   * @returns {{meshes: number, triangles: number, afterMeshes: number, afterTriangles: number}}
   */
  estimate(model, effectiveDeletes = null) {
    let meshes = 0
    let triangles = 0
    let afterMeshes = 0
    let afterTriangles = 0

    /**
     * @param {object} part 零件
     * @param {number} inheritedRatio 从祖先继承的减面比例
     * @param {boolean} inheritedCut 祖先是否已被剪掉(仅旧口径用, 连带整棵子树)
     */
    const walk = (part, inheritedRatio, inheritedCut) => {
      // 删减前的总量恒定全量统计, 不随标记变化 —— cut 只决定 after 侧
      meshes += part.ownMeshes
      triangles += part.ownTriangles

      const mark = model.markOf(part.key)
      const cut = effectiveDeletes
        ? effectiveDeletes.has(part.key)
        : inheritedCut || mark?.mark === 'delete'

      let ratio = inheritedRatio
      if (mark?.mark === 'decimate') ratio = Math.min(ratio, mark.ratio ?? 0.3)

      if (!cut) {
        afterMeshes += part.ownMeshes
        afterTriangles += Math.round(part.ownTriangles * ratio)
      }

      for (const childKey of part.childNames) {
        const child = this.parts.get(childKey)
        if (child) walk(child, ratio, cut)
      }
    }

    for (const assembly of this.assemblies) walk(assembly, 1, false)
    return { meshes, triangles, afterMeshes, afterTriangles }
  }

  /**
   * 功能: 解析 names.csv, 建立 slug -> 中文原名 的映射.
   * @param {string} csvText CSV 原文(首行是表头)
   * @returns {Map<string, string>} 映射
   */
  static parseNamesCsv(csvText) {
    const map = new Map()
    const lines = csvText.split(/\r?\n/)
    for (let i = 1; i < lines.length; i += 1) {
      const line = lines[i]
      if (!line.trim()) continue
      // slug,original_name,is_vendor_auto —— 中文名里不会有逗号
      const firstComma = line.indexOf(',')
      const lastComma = line.lastIndexOf(',')
      if (firstComma < 0 || lastComma <= firstComma) continue
      const slug = line.slice(0, firstComma).replace(/^﻿/, '').trim()
      const chinese = line.slice(firstComma + 1, lastComma).trim()
      if (slug) map.set(slug, chinese)
    }
    return map
  }
}
