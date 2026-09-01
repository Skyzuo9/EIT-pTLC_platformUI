/**
 * 功能: 三维观察辅助 —— 视角预设、隐藏/隔离、透视(X 光)、线框、辅助体开关.
 *
 * 这些是 SolidWorks/CAD 里的常规操作, 但在三维演示页里同样必需: 整机两千多个零件层层
 * 遮挡, 没有"隔离显示"和"透视"就根本看不到里面在发生什么, 更别提对着实物核对材质.
 *
 * 设计原则: **一切改动都可完全还原**. 每种效果都记下被改对象的原状态, 关掉时逐一恢复,
 * 而不是重新加载模型 —— 后者会丢掉用户当前的选择与镜头.
 *
 * 显隐不直接写 `visible` 而走 visibilityIntent 的仲裁: `LIQUID_*` 还有第二个写方
 * (驱动层的"空缸就别画了"), 谁最后写谁赢的结果是"隔离期间播一段注液, 液面盒自己弹回来".
 * 对没有第二个写方的对象(绝大多数零件), 仲裁的结果与直接写逐位相同.
 */
import * as THREE from 'three'

import {
  HIDE_OWNER, hasHideIntent, holdHidden, releaseHidden, setHidden,
} from './visibilityIntent.js'

/** 视角预设: 名称 -> 相机方向单位向量(模型坐标系, Y 轴向上) */
export const VIEW_PRESETS = {
  iso: { label: '等轴测', dir: [1, 0.8, 1] },
  front: { label: '前', dir: [0, 0, 1] },
  back: { label: '后', dir: [0, 0, -1] },
  left: { label: '左', dir: [-1, 0, 0] },
  right: { label: '右', dir: [1, 0, 0] },
  top: { label: '顶', dir: [0, 1, 0.001] },
}

/** 透视模式下非重点对象的不透明度 */
const GHOST_OPACITY = 0.12

export class ViewTools {
  /**
   * 功能: 绑定到一个已加载模型的场景管理器.
   * @param {import('./SceneManager.js').SceneManager} manager 场景管理器
   */
  constructor(manager) {
    this.manager = manager
    /** @type {Map<THREE.Object3D, boolean>} 被本类隐藏的对象 -> 原可见性 */
    this._hidden = new Map()
    /** @type {Map<THREE.Material, object>} 被改成透视的材质 -> 原状态 */
    this._ghosted = new Map()
    /** @type {Map<THREE.Material, boolean>} 被改成线框的材质 -> 原状态 */
    this._wireframed = new Map()
    this.xray = false
    this.wireframe = false
    this.isolated = null
  }

  /**
   * 功能: 把相机切到某个预设视角.
   * @param {keyof typeof VIEW_PRESETS} key 预设名
   * @returns {boolean} 是否切换成功
   */
  setView(key) {
    const preset = VIEW_PRESETS[key]
    const rig = this.manager.cameraRig
    if (!preset || !rig?.controls) return false

    const center = rig.modelCenter || new THREE.Vector3()
    const distance = (rig.modelRadius || 3) * 1.9
    const dir = new THREE.Vector3(...preset.dir).normalize().multiplyScalar(distance)

    rig.controls.setLookAt(
      center.x + dir.x, center.y + dir.y, center.z + dir.z,
      center.x, center.y, center.z,
      true,
    )
    return true
  }

  /**
   * 功能: 回到能看全整机的默认取景.
   * @returns {void}
   */
  resetView() {
    const root = this.manager.machineRoot
    if (root) this.manager.cameraRig?.frameObject(root, true)
  }

  /**
   * 功能: 把镜头对准一组对象的整体包围盒.
   *
   * 刻意不用 CameraRig.frameObject —— 那个会顺带改写 modelBox/modelRadius,
   * 而雾的范围与远近裁剪面都依赖它们, 用来取景子集会污染全局尺度.
   * camera-controls 的 fitToBox 只动相机.
   *
   * @param {THREE.Object3D[]} objects 目标对象
   * @returns {boolean} 是否成功取景
   */
  frameObjects(objects, padding = 0.4) {
    const controls = this.manager.cameraRig?.controls
    if (!controls || !objects?.length) return false

    const box = new THREE.Box3()
    // 精确模式: 量化过的局部包围盒经旋转重新拟合会明显膨胀
    for (const obj of objects) box.expandByObject(obj, true)
    if (box.isEmpty()) return false

    controls.fitToBox(box, true, {
      paddingTop: padding, paddingBottom: padding, paddingLeft: padding, paddingRight: padding,
    })
    return true
  }

  /**
   * 功能: 隐藏一组对象(可反复调用, 累加).
   * @param {THREE.Object3D[]} objects 要隐藏的对象
   * @returns {number} 本次新隐藏的数量
   */
  hide(objects) {
    let count = 0
    for (const obj of objects || []) {
      if (!obj || this._hidden.has(obj)) continue
      // 台账记的是"还原时该恢复成什么". 对**参与仲裁**的对象(液面盒), 这个问题不归
      // 本类回答 —— 记 true 表示"本类没意见, 交给仲裁裁决". 记 obj.visible 会记下一个
      // 会过期的快照: 空缸时藏起来记到 false, 等缸注满了再还原, 它就再也显示不出来了.
      this._hidden.set(obj, hasHideIntent(obj) ? true : obj.visible)
      holdHidden(obj, HIDE_OWNER.VIEW)
      count += 1
    }
    // 可见性变了, 投影集合也变了(透视/线框只改材质外观, 不需要这一步)
    if (count) this.manager.invalidateShadows?.()
    return count
  }

  /**
   * 功能: 恢复一组对象的显示(hide 的逆操作).
   *
   * 只作用于本类隐藏台账里的对象, 且还原成隐藏前记录的可见性 ——
   * 别的机制(如减配视图)藏起来的东西不归这里管, 不会被误点亮.
   *
   * @param {THREE.Object3D[]} objects 要恢复的对象
   * @returns {number} 本次恢复的数量
   */
  show(objects) {
    let count = 0
    for (const obj of objects || []) {
      if (!obj || !this._hidden.has(obj)) continue
      // 撤销本类的意图, 但别人(驱动层的"空缸")还登记着时仍保持隐藏 —— 否则"还原"会把
      // 已排空的液面盒点成一张薄膜。无人登记时才用台账里记的原值。
      releaseHidden(obj, HIDE_OWNER.VIEW, this._hidden.get(obj))
      this._hidden.delete(obj)
      count += 1
    }
    if (count) this.manager.invalidateShadows?.()
    return count
  }

  /**
   * 功能: 只显示这组对象, 其余全部隐藏(CAD 里的"隔离").
   *
   * 与 hide 的区别: 隔离是"反选隐藏", 再次调用会先还原上一次的隔离, 避免层层叠加
   * 之后无法回到原状.
   *
   * @param {THREE.Object3D[]} objects 要保留显示的对象
   * @returns {number} 被隐藏的对象数
   */
  isolate(objects) {
    this.showAll()
    const keep = new Set()
    for (const obj of objects || []) {
      // 保留它自身、全部祖先(否则父级一隐藏它也跟着没了)与全部后代
      let node = obj
      while (node) {
        keep.add(node)
        node = node.parent
      }
      obj.traverse?.((child) => keep.add(child))
    }
    if (!keep.size) return 0

    const targets = []
    this.manager.machineRoot?.traverse((child) => {
      if (child.isMesh && !keep.has(child)) targets.push(child)
    })
    this.isolated = objects
    return this.hide(targets)
  }

  /**
   * 功能: 取消全部隐藏与隔离.
   * @returns {number} 恢复的对象数
   */
  showAll() {
    const count = this._hidden.size
    for (const [obj, visible] of this._hidden) releaseHidden(obj, HIDE_OWNER.VIEW, visible)
    this._hidden.clear()
    this.isolated = null
    if (count) this.manager.invalidateShadows?.()
    return count
  }

  /**
   * 功能: 开关透视(X 光) —— 把除重点之外的一切压成半透明, 看清内部结构.
   *
   * 必须逐材质记录原状态再恢复: 材质在零件之间是共享的, 直接改 opacity 会波及
   * 所有用同种材质的零件; 而恢复时若只是"设回 1", 会把本来就该半透明的外罩/玻璃也弄错.
   *
   * @param {boolean} enabled 是否开启
   * @param {THREE.Object3D[]} [focus] 保持不透明的重点对象; 省略则全部半透明
   * @returns {boolean} 当前状态
   */
  setXray(enabled, focus) {
    if (enabled === this.xray && !focus) return this.xray

    // 先还原, 再按新的重点集重新施加 —— 免得反复切换时状态越积越乱
    for (const [material, snap] of this._ghosted) {
      material.transparent = snap.transparent
      material.opacity = snap.opacity
      material.depthWrite = snap.depthWrite
      material.needsUpdate = true
    }
    this._ghosted.clear()
    this.xray = enabled
    if (!enabled) return false

    const keep = new Set()
    for (const obj of focus || []) obj.traverse?.((child) => keep.add(child))

    this.manager.machineRoot?.traverse((child) => {
      if (!child.isMesh || keep.has(child)) return
      const list = Array.isArray(child.material) ? child.material : [child.material]
      for (const material of list) {
        if (!material || this._ghosted.has(material)) continue
        this._ghosted.set(material, {
          transparent: material.transparent,
          opacity: material.opacity,
          depthWrite: material.depthWrite,
        })
        material.transparent = true
        material.opacity = Math.min(material.opacity, GHOST_OPACITY)
        // 关掉深度写入, 否则半透明零件之间会互相遮挡出很脏的层叠
        material.depthWrite = false
        material.needsUpdate = true
      }
    })
    return true
  }

  /**
   * 功能: 开关线框显示 —— 看结构轮廓时比实体清楚.
   * @param {boolean} enabled 是否开启
   * @returns {boolean} 当前状态
   */
  setWireframe(enabled) {
    if (enabled === this.wireframe) return this.wireframe

    if (!enabled) {
      for (const [material, snap] of this._wireframed) {
        material.wireframe = snap
        material.needsUpdate = true
      }
      this._wireframed.clear()
      this.wireframe = false
      return false
    }

    this.manager.machineRoot?.traverse((child) => {
      if (!child.isMesh) return
      const list = Array.isArray(child.material) ? child.material : [child.material]
      for (const material of list) {
        if (!material || this._wireframed.has(material)) continue
        this._wireframed.set(material, material.wireframe)
        material.wireframe = true
        material.needsUpdate = true
      }
    })
    this.wireframe = true
    return true
  }

  /**
   * 功能: 数一下模型里有多少示意体(状态灯条/液面盒).
   *
   * 管线可以按 rig_map 停用示意体生成; 模型里根本没有它们时, "隐藏示意体"按钮
   * 就不该出现 —— 由调用方用这个计数决定是否显示开关.
   *
   * @returns {number} 示意体对象数
   */
  countHelpers() {
    let count = 0
    this.manager.machineRoot?.traverse((child) => {
      if (/^(LIGHT_STATUS|LIQUID_)/.test(child.name || '')) count += 1
    })
    return count
  }

  /**
   * 功能: 开关"演示辅助体"(状态灯条与液面盒).
   *
   * 它们是管线生成的示意几何而非真实零件, 对着实物核对材质时会干扰判断,
   * 所以给一个单独开关随手关掉.
   *
   * @param {boolean} visible 是否显示
   * @returns {number} 受影响的对象数
   */
  setHelpersVisible(visible) {
    let count = 0
    this.manager.machineRoot?.traverse((child) => {
      if (!/^(LIGHT_STATUS|LIQUID_)/.test(child.name || '')) return
      setHidden(child, HIDE_OWNER.HELPERS, !visible)
      // 从隐藏台账里摘掉, 免得 showAll 又把它显示回来。连带撤销 VIEW 那条意图 ——
      // 台账没了却留着意图, 示意体开关再打开时它会永远藏着, 且再没人能撤销。
      if (this._hidden.has(child)) {
        this._hidden.delete(child)
        releaseHidden(child, HIDE_OWNER.VIEW, visible)
      }
      count += 1
    })
    if (count) this.manager.invalidateShadows?.()
    return count
  }

  /**
   * 功能: 还原一切改动.
   * @returns {void}
   */
  dispose() {
    this.showAll()
    this.setXray(false)
    this.setWireframe(false)
  }
}
