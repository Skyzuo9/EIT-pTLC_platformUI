/**
 * 功能: 聚焦/巡检的周围结构隔离(第三轮重做) —— 默认"幽灵换材质":
 * 周围网格整体换成**单一共享幽灵材质**(白灰半透明), 聚焦工位保持原材质实体.
 *
 * 为什么换引用而不是改材质(第二轮的教训): official-cr5 里 87 个材质有 43 个
 * **跨工位共享**(实测), 就地改共享材质的 opacity 会把聚焦工位自己也拖成半透明
 * (用户截图实锤). 换 mesh.material 引用 + Map<mesh, 原引用> 台账原样写回,
 * 不克隆、不碰共享实例 —— 聚焦对象绝对实体.
 *
 * 三种模式(fxConfig focus.isolation): ghost(默认) / hide(visibilityIntent 仲裁,
 * 与液面盒等驱动层写方共存) / off. keep-set 用 station.meshes 集合(配合归属
 * 修正后的网格集), 不再按子树 traverse.
 *
 * 幽灵材质自第四轮起与 intro(开场扫场)共享单例(fx/ghostMaterial.js); 互斥双层防线:
 * L1 setStation 施加前经 setIntroInterlock 注入的回调中止开场; L2 apply 跳过已是
 * 幽灵材质的 mesh —— 谁都不许把幽灵记成"原材质"(否则退出时永久写回).
 */
import { holdHidden, releaseHidden, hasHideIntent } from '../../three-d/twin/scene/visibilityIntent.js'
import { ghostMaterial, isGhostMaterial, syncGhostOpacity } from './ghostMaterial.js'

/** 本模块在 visibilityIntent 登记表里的写方名 */
const OWNER = 'fxFocus'

/**
 * 功能: 创建隔离器.
 * @param {object} ctx 沙盒上下文
 * @returns {object} 特效实例(另暴露 setStation/setMode/current/counts/setIntroInterlock)
 */
export function createIsolation(ctx) {
  const cfg = ctx.config.focus

  const ghost = ghostMaterial(ctx)
  /** @type {(() => void)|null} 开场互斥回调(main 接线: () => intro.abort()) */
  let introInterlock = null

  /** @type {Map<object, boolean>} hide 台账: 节点 -> 还原值 */
  const hiddenLedger = new Map()
  /** @type {Map<object, object|object[]>} ghost 台账: 网格 -> 原材质引用(数组材质原样存) */
  const ghostLedger = new Map()
  let current = null
  let appliedMode = null

  /** 全量还原两本台账 */
  function clear() {
    for (const [node, fallback] of hiddenLedger) releaseHidden(node, OWNER, fallback)
    hiddenLedger.clear()
    for (const [mesh, material] of ghostLedger) mesh.material = material
    ghostLedger.clear()
  }

  /** 对 id 之外的机身施加当前模式 */
  function apply(id) {
    const station = ctx.stations.get(id)
    if (!station?.meshes?.length) return
    const keep = new Set(station.meshes)

    if (appliedMode === 'hide') {
      ctx.machineRoot.traverse((child) => {
        if (!child.isMesh || keep.has(child)) return
        hiddenLedger.set(child, hasHideIntent(child) ? true : child.visible)
        holdHidden(child, OWNER)
      })
    } else if (appliedMode === 'ghost') {
      syncGhostOpacity(cfg.ghostOpacity)
      ctx.machineRoot.traverse((child) => {
        if (!child.isMesh || keep.has(child) || ghostLedger.has(child)) return
        // L2 兜底: 已是幽灵材质 = 开场扫场还没还原它(互斥协议被绕过) —— 不入台账
        if (isGhostMaterial(child.material)) {
          if (ctx.debug) console.warn('[fx-isolation] 跳过幽灵材质 mesh(互斥协议被绕过?)', child.name)
          return
        }
        ghostLedger.set(child, child.material)
        child.material = ghost
      })
    }
  }

  return {
    name: 'isolation',
    current: () => current,
    /** 功能: 台账规模(验收断言用). */
    counts: () => ({ hidden: hiddenLedger.size, ghosted: ghostLedger.size }),

    /**
     * 功能: 隔离到某工位(null = 全部还原).
     * @param {string|null} id 工位 id
     * @returns {void}
     */
    setStation(id) {
      if (id) introInterlock?.() // L1: 施加前先中止开场(它会全量还原自己的台账)
      const mode = cfg.isolation
      if (id === current && mode === appliedMode) return // 幂等守卫
      clear()
      current = id || null
      appliedMode = mode
      if (current && mode !== 'off') apply(current)
      ctx.invalidateShadows()
    },

    /**
     * 功能: 切换隔离模式(ghost/hide/off); 聚焦中则立即按新模式重施加.
     * @param {string} mode 模式名
     * @returns {void}
     */
    setMode(mode) {
      cfg.isolation = mode
      if (current) {
        const id = current
        current = null
        this.setStation(id)
      }
    },

    /**
     * 功能: 注入开场互斥回调(main 接线).
     * @param {() => void} fn 中止开场的回调
     * @returns {void}
     */
    setIntroInterlock(fn) {
      introInterlock = fn
    },

    update() {
      // 幽灵浓度滑杆即时生效(共享单例, 幂等同步, 谁在场谁生效)
      syncGhostOpacity(cfg.ghostOpacity)
    },
    setStationState() {},
    setEnabled(on) {
      if (!on) this.setStation(null)
    },
    setParams() {},

    dispose() {
      clear()
      current = null // 共享幽灵材质归 ghostMaterial 模块管, 这里不 dispose
    },
  }
}
