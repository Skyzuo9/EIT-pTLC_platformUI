/**
 * 功能: 工作台的场景控制器 —— 零件级拾取、白模/原色双模式、删减着色、
 *       「全部零件/减配后」双视图.
 *
 * 展示范式(2026-08 起): 默认**白模** —— 机身统一哑光白, 只给"会被删减的零件"上色
 * (删除红/保留绿/减面黄, 与层级树色点同一张 MARK_STYLES 色表), 前端工程师一眼看清
 * 性能删减策略的真实覆盖面. 早期方案曾在原色模型上给标记刷红色幽灵, 整机标删几百个
 * 紧固件后满屏泛红而废弃; 白底+纯色标注反转了图底关系, 数量再大也不吵.
 * 「原色」模式用于对照真实外观(2026-08 起 raw 已赋管线材质, 对照的是与正式
 * 产物同规则的配色), 不做删减着色(树色点与顶部计数照常).
 *
 * 选中用后期描边(Effects.setSelected, 与材质台一致), 不再涂色; 描边链不存在时
 * (low 档兜底)退回涂青色的旧路径. 悬停描边已取消(2026-08-02 用户定夺: 描边不再
 * 跟随鼠标, 点击选中后才显示), 悬停只改光标与拾取目标; 选中描边**常驻**(同日
 * 用户定夺: 旋转/缩放等视角调整不隐藏, 仅点击空白取消选中时消失).
 *
 * 外观改动的四本台账按**属性**正交, 互不侵入:
 *   ViewTools._hidden      → visible
 *   ViewTools._ghosted     → opacity/transparent/depthWrite(透视)
 *   ViewTools._wireframed  → wireframe
 *   本类 _whiteBase        → color/roughness/metalness/emissive(白模基线, 材质级)
 *   本类 _touched          → color/opacity(标记着色) + visible(减配隐藏), 网格级
 * 白模先于一切着色施加, 是 _touched 快照捕获到的"原色" —— 还原自动回到白模.
 *
 * 与演示视图的 PickController 的区别: 那边拾取粒度是"工位"(用户关心的是整个工站),
 * 这边是"零件"(用户要精确删掉某个拖链). 因此不能复用, 但两者都挂在同一个 SceneManager 上.
 */
import * as THREE from 'three'

import { MARK_TINTS, MARKS } from './selectionModel.js'

/** 选中高亮色(描边链不可用时的涂色 fallback) */
const SELECT_COLOR = 0x36d1ff

/** 白模基线: 哑光白, 微弱金属度让棱线在无阴影档位下仍可读 */
const WHITE_BASE = { color: 0xeef0f3, roughness: 0.6, metalness: 0.05 }

/**
 * 描边选择集上限: 规则批选可一次选中数百个零件, OutlineEffect 的 mask pass 逐件
 * 绘制会把帧率打穿. 超限时跳过描边(树高亮与计数照常表达选中).
 */
const OUTLINE_MESH_CAP = 300

export class WorkbenchScene {
  /**
   * 功能: 绑定到已加载模型的场景.
   * @param {object} options 参数
   * @param {import('../twin/scene/SceneManager.js').SceneManager} options.manager 场景管理器
   * @param {import('./PartIndex.js').PartIndex} options.index 零件索引
   * @param {import('./selectionModel.js').SelectionModel} options.model 选择模型
   * @param {(name: string|null, additive: boolean) => void} [options.onPick] 拾取回调
   * @param {() => Set<string>|null} [options.getEffectiveDeletes]
   *        有效删除集 getter(「减配后」视图按它隐藏, 白模按它着色; 惰性取, 保证拿到最新集合)
   * @param {boolean} [options.whiteMode=true] 初始是否白模
   */
  constructor({ manager, index, model, onPick, getEffectiveDeletes, whiteMode = true }) {
    this.manager = manager
    this.index = index
    this.model = model
    this.onPick = onPick
    this.getEffectiveDeletes = getEffectiveDeletes
    /** @type {'all'|'reduced'} 当前视图模式 */
    this.viewMode = 'all'
    /** 白模模式(默认开): 机身白 + 删减件着色; 关闭 = CAD 原色对照, 不着色 */
    this.whiteMode = whiteMode

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()
    this._pending = null
    this._down = null
    this.hovered = null

    /** @type {Map<THREE.Mesh, object>} 被改过外观的网格 -> 原始外观, 用于还原 */
    this._touched = new Map()
    /** @type {Map<THREE.Material, object>} 白模基线台账: 材质 -> CAD 原色快照 */
    this._whiteBase = new Map()
    /** @type {THREE.Material[]} 本类克隆出来的材质, 释放时要 dispose */
    this._clones = []

    this._isolateMaterials()
    if (this.whiteMode) this._applyWhiteBase()

    this._appliedVersion = -1
    this._bind()
    this._unhook = manager.addFrameHook(() => this._tick())
  }

  /**
   * 功能: 给每个网格分配独立的材质实例.
   *
   * 必须做这一步: raw 模型里共享材质随处可见(原生 GLB 有 735 种材质但网格两千多个),
   * 直接改共享材质的颜色, 同材质的零件会一起变色. 克隆两千来个无贴图的标准材质开销
   * 很小, 换来的是后续每次上色都只是赋值, 交互过程零分配.
   *
   * @returns {void}
   */
  _isolateMaterials() {
    const root = this.manager.machineRoot
    if (!root) return

    const shared = new Map()
    let cloned = 0
    root.traverse((child) => {
      if (!child.isMesh || !child.material || Array.isArray(child.material)) return
      const count = (shared.get(child.material.uuid) || 0) + 1
      shared.set(child.material.uuid, count)
      // 第一次见到的材质原样保留, 之后每次都换成克隆 —— 这样共享的那份也不会被改到
      if (count > 1) {
        child.material = child.material.clone()
        this._clones.push(child.material)
        cloned += 1
      }
    })
    if (cloned) console.info(`[workbench] 已隔离 ${cloned} 个共享材质实例`)
  }

  /**
   * 功能: 把整机刷成哑光白(白模基线), 逐材质快照原值供还原.
   *
   * 只动 color/roughness/metalness/emissive 四个属性 —— 与透视(opacity 组)、
   * 线框(wireframe)、隐藏(visible)三本台账按属性正交. 透明件的 opacity/transmission
   * 不动: 玻璃罩在白模下保持透明, 反而利于看清内部的删减对象.
   * emissive 必须一并压掉, 否则原生自发光件(灯罩等)在白模里还亮着.
   *
   * @returns {void}
   */
  _applyWhiteBase() {
    const root = this.manager.machineRoot
    if (!root) return
    root.traverse((child) => {
      if (!child.isMesh || !child.material || Array.isArray(child.material)) return
      const material = child.material
      if (this._whiteBase.has(material)) return
      this._whiteBase.set(material, {
        color: material.color?.getHex() ?? 0xffffff,
        roughness: material.roughness,
        metalness: material.metalness,
        emissive: material.emissive?.getHex() ?? 0x000000,
      })
      material.color?.setHex(WHITE_BASE.color)
      if ('roughness' in material) material.roughness = WHITE_BASE.roughness
      if ('metalness' in material) material.metalness = WHITE_BASE.metalness
      material.emissive?.setHex(0x000000)
    })
  }

  /**
   * 功能: 还原白模基线, 回到 CAD 原色.
   * @returns {void}
   */
  _restoreWhiteBase() {
    for (const [material, saved] of this._whiteBase) {
      material.color?.setHex(saved.color)
      if ('roughness' in material && saved.roughness !== undefined) material.roughness = saved.roughness
      if ('metalness' in material && saved.metalness !== undefined) material.metalness = saved.metalness
      material.emissive?.setHex(saved.emissive)
    }
    this._whiteBase.clear()
  }

  /**
   * 功能: 切换白模/原色模式.
   *
   * 时序是唯一的坑: 必须**先还原 _touched**(它的快照色是在旧基线下捕获的),
   * 再翻转白模基线, 最后重涂 —— 顺序错了会把零件还原成上一个模式的颜色.
   *
   * @param {boolean} on 是否白模
   * @returns {void}
   */
  setWhiteMode(on) {
    if (this.whiteMode === !!on) return
    this._restoreTouched()
    if (on) this._applyWhiteBase()
    else this._restoreWhiteBase()
    this.whiteMode = !!on
    this.applyMarks()
  }

  /**
   * 功能: 绑定指针事件.
   * @returns {void}
   */
  _bind() {
    const dom = this.manager.canvas

    this._onMove = (event) => {
      const rect = dom.getBoundingClientRect()
      this._pending = {
        x: ((event.clientX - rect.left) / rect.width) * 2 - 1,
        y: -((event.clientY - rect.top) / rect.height) * 2 + 1,
      }
    }
    this._onDown = (event) => {
      this._down = { x: event.clientX, y: event.clientY }
    }
    this._onUp = (event) => {
      if (!this._down) return
      const moved =
        Math.abs(event.clientX - this._down.x) + Math.abs(event.clientY - this._down.y)
      this._down = null
      const hoveredAtUp = this.hovered
      // 置空迫使下一次 pointermove 重新拾取悬停目标(_setHovered 有同值早退)
      this.hovered = null
      // 只有左键短击才是选择; 右键语义归视图层的 contextmenu 路径
      if (event.button === 0 && moved <= 4) {
        // Ctrl/Shift = 加选, 与文件管理器一致
        this.onPick?.(hoveredAtUp, event.ctrlKey || event.metaKey || event.shiftKey)
      }
    }
    this._onCancel = () => {
      this._down = null
      this.hovered = null
    }
    this._onLeave = () => {
      this._pending = null
      this._setHovered(null)
    }

    dom.addEventListener('pointermove', this._onMove)
    dom.addEventListener('pointerdown', this._onDown)
    dom.addEventListener('pointerup', this._onUp)
    dom.addEventListener('pointercancel', this._onCancel)
    dom.addEventListener('pointerleave', this._onLeave)
  }

  /**
   * 功能: 收集当前选中集的描边网格(超上限返回空数组 = 跳过描边).
   * @returns {THREE.Mesh[]} 展平网格数组
   */
  _selectedOutlineMeshes() {
    const meshes = new Set()
    for (const name of this.model.selected) {
      const part = this.index.get(name)
      part?.object?.traverse((child) => {
        if (child.isMesh) meshes.add(child)
      })
      if (meshes.size > OUTLINE_MESH_CAP) return []
    }
    return meshes.size <= OUTLINE_MESH_CAP ? [...meshes] : []
  }

  /**
   * 功能: 每帧处理拾取与标记同步.
   * @returns {void}
   */
  _tick() {
    this._pick()
    if (this.model.version !== this._appliedVersion) {
      this._appliedVersion = this.model.version
      this.applyMarks()
    }
  }

  /**
   * 功能: 执行一次射线拾取.
   * @returns {void}
   */
  _pick() {
    // 按住鼠标(旋转视角/框选)期间不做 hover: 描边抖动又浪费射线求交
    if (this._down || !this._pending || !this.manager.machineRoot) return
    this.pointer.set(this._pending.x, this._pending.y)
    this._pending = null

    this.raycaster.setFromCamera(this.pointer, this.manager.camera)
    const hits = this.raycaster.intersectObject(this.manager.machineRoot, true)

    let name = null
    for (const hit of hits) {
      // 隐藏中的网格(减配视图/手动隐藏)不参与拾取, 也不该挡住后面的零件.
      // 已标删除的零件在「全部零件」视图里外观正常, **必须**可点选 —— 反悔全靠它.
      if (!this._isShown(hit.object)) continue
      const owner = this.index.ownerOfMesh(hit.object)
      if (owner) {
        name = owner
        break
      }
    }

    this._setHovered(name)
  }

  /**
   * 功能: 更新悬停零件 —— 只改光标与拾取目标. 悬停描边已取消(2026-08-02):
   *       描边不再跟随鼠标, 点击选中后才显示(_applySelection 路径).
   * @param {string|null} name 零件键
   * @returns {void}
   */
  _setHovered(name) {
    if (name === this.hovered) return
    this.hovered = name
    this.manager.canvas.style.cursor = name ? 'pointer' : 'default'
  }

  /**
   * 功能: 判断一个对象在场景里是否真正可见(自身与全部祖先都 visible).
   *
   * three 的 Raycaster 根本不检查 visible; 只查网格自身的话, 被隐藏的若是
   * 父级 Group, 其子网格照样会被命中 —— 看不见的零件还能被 hover/点选.
   * @param {THREE.Object3D} object 对象
   * @returns {boolean} 是否可见
   */
  _isShown(object) {
    const root = this.manager.machineRoot
    for (let node = object; node; node = node.parent) {
      if (!node.visible) return false
      if (node === root) break
    }
    return true
  }

  /**
   * 功能: 把 _touched 台账整体还原(applyMarks 头部与模式切换/释放共用).
   * @returns {void}
   */
  _restoreTouched() {
    for (const [mesh, saved] of this._touched) {
      if ('color' in saved && mesh.material && !Array.isArray(mesh.material)) {
        mesh.material.color.setHex(saved.color)
        mesh.material.opacity = saved.opacity
        mesh.material.transparent = saved.transparent
        mesh.material.depthWrite = saved.depthWrite
      }
      if ('visible' in saved) mesh.visible = saved.visible
    }
    this._touched.clear()
  }

  /**
   * 功能: 把当前的视图模式/白模着色/选中状态刷到三维外观上.
   *
   * 执行序(每次 model.version 变化):
   *   ① 按快照还原上一轮改动
   *   ② 「减配后」视图按有效删除集逐网格隐藏
   *   ③ 白模下着色: 先"删除"(逐网格, 有效删除集口径)再"保留/减面"(显式标记, 整子树)
   *      —— _touched 的快照守卫是 first-write-wins, 先涂的优先, 恰与管线的
   *      删除>保留>减面 生效优先级同向; 减配视图里删除件已隐藏, 跳过删除着色省一遍循环
   *   ④ 选中走描边(超上限跳过); 描边链不存在时退回涂青色
   *
   * 做法是直接改材质的 color/opacity 而不是换材质对象: 原始模型有 2000 多个网格,
   * 快照按"改过什么恢复什么"记键 —— 只有我们自己藏过的网格才带 visible 键,
   * 无条件置回 true 会把 ViewTools 手动隐藏的对象弹回来.
   *
   * @returns {void}
   */
  applyMarks() {
    this._restoreTouched()

    // 「减配后」: 按网格归属(ownerOf)逐网格隐藏, 不能按被删节点的子树遍历 ——
    // 有效删除集是逐节点完备的, 被更高优先级"保留"豁免的子件不在集合里,
    // 子树遍历会把它们连坐藏掉. 隐藏也必须落在 mesh 级: _pick 只检查网格自身的 visible.
    const deletes = this.getEffectiveDeletes?.()
    if (this.viewMode === 'reduced' && deletes && deletes.size) {
      for (const [mesh, owner] of this.index.ownerOf) {
        if (!deletes.has(owner)) continue
        let saved = this._touched.get(mesh)
        if (!saved) {
          saved = {}
          this._touched.set(mesh, saved)
        }
        if (!('visible' in saved)) saved.visible = mesh.visible
        mesh.visible = false
      }
    }

    /** 给单个网格上色(快照守卫: 只在首次触碰时记原值, first-write-wins) */
    const paintMesh = (mesh, color) => {
      if (!mesh.isMesh || !mesh.material || Array.isArray(mesh.material)) return
      let saved = this._touched.get(mesh)
      if (!saved) {
        saved = {}
        this._touched.set(mesh, saved)
      }
      if (!('color' in saved)) {
        saved.color = mesh.material.color.getHex()
        saved.opacity = mesh.material.opacity
        saved.transparent = mesh.material.transparent
        saved.depthWrite = mesh.material.depthWrite
      }
      mesh.material.color.setHex(color)
    }

    // 上色作用于整棵子树: 标记一个装配, 它下面的零件应当一起变色
    const paint = (key, color) => {
      const part = this.index.get(key)
      part?.object?.traverse((child) => paintMesh(child, color))
    }

    if (this.whiteMode) {
      // 删除着色: 与减配隐藏同口径(有效删除集, 含正则/尺寸规则命中), 自动尊重 keep 豁免.
      // 用不透明纯红而不是 MARK_STYLES 的 0.12 半透明 —— 两千网格半透明会产生排序脏叠,
      // 白底上纯色本身已足够低噪声.
      if (this.viewMode === 'all' && deletes && deletes.size) {
        for (const [mesh, owner] of this.index.ownerOf) {
          if (deletes.has(owner)) paintMesh(mesh, MARK_TINTS[MARKS.DELETE])
        }
      }
      for (const [key, info] of this.model.marks) {
        if (info.mark === MARKS.KEEP) paint(key, MARK_TINTS[MARKS.KEEP])
        else if (info.mark === MARKS.DECIMATE) paint(key, MARK_TINTS[MARKS.DECIMATE])
      }
    }

    this._applySelection(paint)
  }

  /**
   * 功能: 表达选中状态 —— 描边优先, 无描边链时涂色兜底.
   * @param {(key: string, color: number) => void} paint 涂色函数(fallback 用)
   * @returns {void}
   */
  _applySelection(paint) {
    if (this.manager.effects) {
      this.manager.effects.setSelected(this._selectedOutlineMeshes())
      return
    }
    // fallback: 描边链不存在(low 档), 沿用涂色高亮(藏起的网格被刷到也无害, 快照守卫在)
    for (const name of this.model.selected) paint(name, SELECT_COLOR)
  }

  /**
   * 功能: 切换「全部零件 / 减配后」视图.
   * @param {'all'|'reduced'} mode 视图模式
   * @returns {void}
   */
  setViewMode(mode) {
    if (this.viewMode === mode) return
    this.viewMode = mode
    this.applyMarks()
  }

  /**
   * 功能: 按当前状态强制重刷一遍外观(幂等: 先按快照恢复再重涂/重藏).
   *
   * 供"全显"这类外部可见性操作之后兜底 —— ViewTools.showAll 按它自己的台账恢复
   * 可见性, 可能把减配视图藏起的网格顺带点亮.
   *
   * @returns {void}
   */
  refresh() {
    this.applyMarks()
  }

  /**
   * 功能: 把镜头对准某个零件.
   * @param {string} name 零件名
   * @returns {void}
   */
  focus(name) {
    const part = this.index.get(name)
    if (part) this.manager.cameraRig.fitTo(part.object, true)
  }

  /**
   * 功能: 释放事件与外观改动(顺序: 还原标记着色 → 还原白模 → 释放克隆材质).
   * @returns {void}
   */
  dispose() {
    this._unhook?.()
    const dom = this.manager.canvas
    dom.removeEventListener('pointermove', this._onMove)
    dom.removeEventListener('pointerdown', this._onDown)
    dom.removeEventListener('pointerup', this._onUp)
    dom.removeEventListener('pointercancel', this._onCancel)
    dom.removeEventListener('pointerleave', this._onLeave)
    dom.style.cursor = 'default'

    this.manager.effects?.setSelected([])
    this.manager.effects?.setHover([])

    this._restoreTouched()
    this._restoreWhiteBase()

    for (const material of this._clones) material.dispose()
    this._clones.length = 0
  }
}
