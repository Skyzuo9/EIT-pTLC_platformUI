/**
 * 功能: 运动语义着色控制器 —— 把整机涂成"静止/可动/耗材"三色近白模.
 *
 * 与装配台 WorkbenchScene 的涂色机制刻意不同: 那边逐网格改克隆材质的 color(零件
 * 各自要能变色), 这边是**纯材质指针替换** —— 全场景共享 4 个分类材质, drawCalls
 * 不升反可能降, 还原就是把原材质指针换回去. Map<mesh, 原材质> 是唯一台账.
 *
 * 透明件(玻璃罩/透射材质)单独给半透明静止材质: 涂成不透明灰会把柜内的可动件全挡住,
 * 而"看清哪些东西会动"正是本模式的目的.
 */
import * as THREE from 'three'

import { SEMANTIC_COLORS } from './motionSemantics.js'

/**
 * 程序化网格的语义标签键(写方: twin/scene/plates/PlateFaceLayer.js, 两边字面量必须同步改)。
 * 程序化板不在 manifest 的 glbNodes 子树里(锚点模板已被 plateAnchors 隐藏成纯位姿源),
 * 只能靠网格自带标签认领。
 */
const SEMANTIC_TAG_KEY = '__ptlcSemantic'

/**
 * CAD 里残留的薄层板实例 —— 管线对板的命名是裸的 `玻璃-N[.M]`(三 侧点号被剥, 如
 * 玻璃-1006), 13 个落点板都按此命名且已被 plateAnchors 隐藏; 但上料抽屉总装里还有
 * 一块**可见**的 玻璃-2 不在任何 manifest 耗材节点里, 不认它就会掉进透明兜底。
 * 部件名(PTLC-xx_玻璃放置板 等钢件)与石英玻璃缸盖都带前缀, 不会误中。
 * 长期解法是把抽屉板并进 rig_map 的 inventory(需要重跑模型链), 这里先按命名认领。
 */
const CAD_PLATE_NAME_RE = /^玻璃-\d+$/

export class MotionPaint {
  /**
   * 功能: 初始化(不改场景, apply 时才生效).
   * @param {object} options 参数
   * @param {import('../twin/scene/SceneManager.js').SceneManager} options.manager 场景管理器
   * @param {(path: string) => THREE.Object3D|undefined} options.resolve 节点解析器(带末段兜底)
   */
  constructor({ manager, resolve }) {
    this.manager = manager
    this.resolve = resolve
    this.active = false

    /** @type {Map<THREE.Mesh, THREE.Material>} 原材质台账 */
    this._original = new Map()
    /** @type {Map<THREE.Mesh, string>} 网格 -> 语义条目 id(hover/拾取反查用) */
    this.meshEntry = new Map()

    const make = (color, extra = {}) =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(color),
        roughness: 0.75,
        metalness: 0.05,
        ...extra,
      })
    /** 分类共享材质(4 个实例服务全场景) */
    this._materials = {
      static: make(SEMANTIC_COLORS.static, { roughness: 0.85, metalness: 0 }),
      movable: make(SEMANTIC_COLORS.movable),
      consumable: make(SEMANTIC_COLORS.consumable),
      glass: make('#eef2f6', {
        transparent: true,
        opacity: 0.1,
        depthWrite: false,
        roughness: 0.2,
      }),
    }
  }

  /**
   * 功能: 按语义条目表给整机换装(幂等: 先还原再重涂).
   * @param {Array} entries classifySemantics 产物
   * @returns {{movable: number, consumable: number, static: number}} 各类网格数
   */
  apply(entries) {
    this.restore()

    // 先按条目认领网格(movable 优先于 consumable —— 语义上不该重叠, 保险起见定序)
    const claims = new Map() // mesh -> {category, entryId}
    const claim = (entry) => {
      for (const path of entry.glbNodes || []) {
        const node = this.resolve(path)
        node?.traverse((child) => {
          if (!child.isMesh) return
          if (!claims.has(child)) claims.set(child, { category: entry.category, entryId: entry.id })
        })
      }
    }
    for (const entry of entries) if (entry.category === 'movable') claim(entry)
    for (const entry of entries) if (entry.category === 'consumable') claim(entry)

    const counts = { movable: 0, consumable: 0, static: 0 }
    const root = this.manager.machineRoot
    root?.traverse((mesh) => {
      if (!mesh.isMesh || !mesh.material || Array.isArray(mesh.material)) return
      const original = mesh.material
      // 自带语义标签的程序化网格(薄层板)与 CAD 残留板优先于子树认领: 板是耗材本体,
      // 不因骑在滑车/吸盘(movable 子树)上改类, 也不落进 transmission 的透明兜底
      const tag = mesh.userData?.[SEMANTIC_TAG_KEY]
        || (CAD_PLATE_NAME_RE.test(mesh.name || '') ? 'consumable' : '')
      const claimed = tag && this._materials[tag] ? { category: tag, entryId: '' } : claims.get(mesh)
      let next
      if (claimed) {
        next = this._materials[claimed.category] || this._materials.static
        if (claimed.entryId) this.meshEntry.set(mesh, claimed.entryId)
        counts[claimed.category] = (counts[claimed.category] || 0) + 1
      } else if (original.transmission > 0 || (original.transparent && original.opacity < 0.5)) {
        next = this._materials.glass
        counts.static += 1
      } else {
        next = this._materials.static
        counts.static += 1
      }
      this._original.set(mesh, original)
      mesh.material = next
    })

    this.active = true
    return counts
  }

  /**
   * 功能: 还原全部网格的原材质.
   * @returns {void}
   */
  restore() {
    for (const [mesh, material] of this._original) mesh.material = material
    this._original.clear()
    this.meshEntry.clear()
    this.active = false
  }

  /**
   * 功能: 取一个语义条目的全部网格(描边强调/取景用, 展平数组).
   * @param {object} entry 语义条目
   * @returns {THREE.Mesh[]} 网格数组
   */
  entryMeshes(entry) {
    const meshes = new Set()
    for (const path of entry?.glbNodes || []) {
      const node = this.resolve(path)
      node?.traverse((child) => {
        if (child.isMesh) meshes.add(child)
      })
    }
    return [...meshes]
  }

  /**
   * 功能: 释放(还原 + dispose 自建分类材质).
   * @returns {void}
   */
  dispose() {
    this.restore()
    for (const material of Object.values(this._materials)) material.dispose()
  }
}
