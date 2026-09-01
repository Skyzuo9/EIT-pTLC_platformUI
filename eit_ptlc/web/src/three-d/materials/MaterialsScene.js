/**
 * 功能: 材质工作台的场景控制器 —— 枚举模型里的材质、高亮某材质用在哪些零件、实时改观感.
 *
 * 与装配工作台的关键差别: 那边要**隔离**材质(点一个零件只该它变色), 这边恰恰相反 ——
 * 材质是共享的, 改 MAT_STEEL_PLATE 就该让用它的 266 个零件一起变, 这正是我们要的效果.
 * 所以这里不做 _isolateMaterials.
 *
 * 所有修改都是直接写 three.js 材质对象的属性, 下一帧即可见, 不需要重跑管线.
 * 保存时才落成 YAML, 由管线烘进 GLB.
 */
import * as THREE from 'three'

/** 面板字段 -> three.js 材质属性的映射 */
const PROP_MAP = {
  base_color: 'color',
  roughness: 'roughness',
  metalness: 'metalness',
  alpha: 'opacity',
  transmission: 'transmission',
  ior: 'ior',
  emission: 'emissive',
  emission_strength: 'emissiveIntensity',
}

/**
 * 功能: 按合成值推导透明三元组(transparent/opacity/depthWrite)并写进材质.
 *
 * GLTFLoader 对 alphaMode=BLEND 的材质会同时置 transparent=true 与 depthWrite=false;
 * 若把 alpha 拖回 1.0 时只切 transparent, 网格进不透明队列却仍不写深度,
 * 后画的内部件会盖穿外壁(表现为"不透明度 100% 仍穿模"). 反向同理: 原本不透明的
 * 材质拖成半透明时 depthWrite 停在 true, 半透明件之间互相硬遮挡.
 * 三个标志只能一起从 alpha/transmission 推导, 不留单独手设的口子.
 *
 * @param {THREE.Material} material 目标材质
 * @param {object} merged 合成后的字段值(至少含 alpha/transmission 的最终态)
 * @returns {void}
 */
export function syncAlphaFlags(material, merged) {
  const alpha = Number(merged.alpha ?? 1)
  const translucent = alpha < 1 || Number(merged.transmission ?? 0) > 0
  material.transparent = translucent
  material.opacity = alpha
  material.depthWrite = !translucent
  material.needsUpdate = true
}

export class MaterialsScene {
  /**
   * 功能: 绑定到已加载模型的场景, 建立材质索引.
   * @param {object} options 参数
   * @param {import('../twin/scene/SceneManager.js').SceneManager} options.manager 场景管理器
   */
  constructor({ manager, onPick }) {
    this.manager = manager
    this.onPick = onPick
    /** @type {Map<string, {material: THREE.Material, meshes: THREE.Mesh[], triangles: number}>} */
    this.index = new Map()
    /** @type {Map<string, object>} 材质名 -> 初始属性快照, 用于"恢复原值" */
    this._baseline = new Map()
    /**
     * @type {Map<THREE.Mesh, {original: THREE.Material, clone: THREE.Material, patch: object}>}
     * 零件级覆盖的克隆台账: 覆盖的零件把类材质克隆成专属实例(name 带 @part 后缀),
     * 类材质本体不动 —— 同类其余零件不受影响. 补丁清空即还原并回收克隆.
     */
    this._partClones = new Map()
    /**
     * @type {Map<string, {clone: THREE.Material, baseName: string,
     *                     members: Map<THREE.Mesh, THREE.Material>, patch: object}>}
     * 材质组的共享克隆台账: 一组一个材质实例(GROUP_<名>@part), 成员统一换装.
     * members 的值 = 接管前的材质(类共享材质), 还原凭证. 已有件克隆的成员不换装,
     * 改把件克隆的 original 重指组材质(件底=组, 与管线叠加序一致).
     */
    this._groupClones = new Map()
    this.selected = null

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()
    this._down = null

    this._buildIndex()
    this._bindPicking()
  }

  /**
   * 功能: 绑定三维拾取 —— 点零件反查它用的是哪种材质.
   *
   * 光有材质列表是调不动的: 你看到实物某处颜色不对, 得能直接点上去问"这是哪种材质",
   * 而不是在二十来个 MAT_* 里挨个试.
   *
   * @returns {void}
   */
  _bindPicking() {
    const canvas = this.manager.canvas
    if (!canvas) return

    this._onDown = (event) => {
      this._down = { x: event.clientX, y: event.clientY }
    }
    this._onUp = (event) => {
      // 拖动了就是在转视角, 不该当成点选; 右键语义归视图层的 contextmenu 路径
      if (!this._down) return
      const moved = Math.hypot(event.clientX - this._down.x, event.clientY - this._down.y)
      this._down = null
      if (moved > 4 || event.button !== 0) return
      this._pick(event)
    }
    canvas.addEventListener('pointerdown', this._onDown)
    canvas.addEventListener('pointerup', this._onUp)
  }

  /**
   * 功能: 射线拾取, 命中后回报"零件名 + 它的材质名".
   * @param {PointerEvent} event 指针事件
   * @returns {void}
   */
  _pick(event) {
    const canvas = this.manager.canvas
    const root = this.manager.machineRoot
    if (!canvas || !root) return

    const rect = canvas.getBoundingClientRect()
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.manager.camera)

    const hits = this.raycaster.intersectObject(root, true)
    // Ctrl/Shift = 加选(与装配台/文件管理器一致)
    const additive = Boolean(event.ctrlKey || event.metaKey || event.shiftKey)
    // 跳过被隐藏的对象 —— 隔离/隐藏之后不该还能点到看不见的东西
    const hit = hits.find((item) => item.object?.isMesh && item.object.visible)
    if (!hit) {
      this.onPick?.(null, additive)
      return
    }

    const mesh = hit.object
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    const material = list[hit.face?.materialIndex ?? 0] || list[0]
    // 零件覆盖/组的克隆材质带 @part 后缀, 反查材质类时剥掉 —— 编辑器切到的应是类
    const materialName = (material?.name || '').replace(/@part$/, '')
    // 带上命中的网格对象: 视图侧要用 PartIndex.ownerOfMesh 反查零件键, 在层级树里定位
    this.onPick?.({ part: mesh.name, material: materialName, mesh }, additive)
  }

  /**
   * 功能: 取某个零件名对应的网格对象(用于隐藏/隔离/取景).
   * @param {string} partName 零件名(可不含 .001 后缀)
   * @returns {THREE.Mesh[]} 匹配到的网格
   */
  meshesOfPart(partName) {
    const found = []
    this.manager.machineRoot?.traverse((child) => {
      if (!child.isMesh) return
      if ((child.name || '').replace(/\.\d{3}$/, '') === partName) found.push(child)
    })
    return found
  }

  /**
   * 功能: 取某材质用到的全部网格(用于隔离/透视时指定重点).
   * @param {string} name 材质名
   * @returns {THREE.Mesh[]} 网格数组
   */
  meshesOf(name) {
    return this.index.get(name)?.meshes || []
  }

  /**
   * 功能: 遍历模型, 按材质名归集用到它的网格, 并记下每种材质的初始状态.
   * @returns {void}
   */
  _buildIndex() {
    const root = this.manager.machineRoot
    if (!root) return

    root.traverse((child) => {
      if (!child.isMesh || !child.material) return
      const list = Array.isArray(child.material) ? child.material : [child.material]
      for (const material of list) {
        if (!material?.name) continue
        let entry = this.index.get(material.name)
        if (!entry) {
          entry = { material, meshes: [], triangles: 0 }
          this.index.set(material.name, entry)
          this._baseline.set(material.name, this._snapshot(material))
        }
        entry.meshes.push(child)
        const position = child.geometry?.attributes?.position
        if (position) entry.triangles += Math.round(position.count / 3)
      }
    })
  }

  /**
   * 功能: 记录一份材质的可调属性快照.
   * @param {THREE.Material} material 材质
   * @returns {object} 快照
   */
  _snapshot(material) {
    const snap = {}
    for (const [field, prop] of Object.entries(PROP_MAP)) {
      if (!(prop in material)) continue
      const value = material[prop]
      snap[field] = value?.isColor ? `#${value.getHexString().toUpperCase()}` : value
    }
    return snap
  }

  /**
   * 功能: 列出全部材质, 按使用零件数从多到少排序 —— 先调影响面大的.
   * @returns {Array<{name: string, meshes: number, triangles: number, current: object}>}
   */
  list() {
    return [...this.index.entries()]
      .map(([name, entry]) => ({
        name,
        meshes: entry.meshes.length,
        triangles: entry.triangles,
        current: this._snapshot(entry.material),
      }))
      .sort((a, b) => b.meshes - a.meshes || a.name.localeCompare(b.name))
  }

  /**
   * 功能: 取某材质的初始值(未被人工覆盖前的样子).
   * @param {string} name 材质名
   * @returns {object} 快照副本
   */
  baseline(name) {
    return { ...(this._baseline.get(name) || {}) }
  }

  /**
   * 功能: 高亮某材质用到的全部零件 —— 直接回答"这个材质用在哪儿".
   * @param {string|null} name 材质名; null 表示取消高亮
   * @returns {number} 被高亮的网格数
   */
  select(name) {
    this.selected = name
    const entry = name ? this.index.get(name) : null
    this.manager.effects?.setSelected(entry ? entry.meshes : [])
    return entry ? entry.meshes.length : 0
  }


  /**
   * 功能: 把一份补丁实时应用到材质上; 补丁里没有的字段回到初始值.
   *
   * 每次都从初始值重建而不是增量改, 这样"清掉某个字段"能正确回退 ——
   * 增量改法会让被清掉的字段停在上一次的值上, 表现为"改了但撤不回去".
   *
   * @param {string} name 材质名
   * @param {object} patch 覆盖补丁
   * @returns {boolean} 是否命中该材质
   */
  apply(name, patch) {
    const entry = this.index.get(name)
    if (!entry) return false

    const material = entry.material
    const merged = { ...this.baseline(name), ...(patch || {}) }

    for (const [field, prop] of Object.entries(PROP_MAP)) {
      if (!(prop in material) || !(field in merged)) continue
      const value = merged[field]
      if (material[prop]?.isColor) material[prop].set(value)
      else material[prop] = Number(value)
    }

    syncAlphaFlags(material, merged)
    // metalness 可能被拖过金属反射增强的阈值, 让 SceneManager 按新值重算增强集合
    if (patch && 'metalness' in patch) this.manager.refreshEnvBoost?.()
    return true
  }

  /**
   * 功能: 按整份覆盖表刷新全部材质(加载时或撤销后调用), 并重放全部零件克隆.
   * @param {import('./overrideModel.js').OverrideModel} model 覆盖模型
   * @returns {number} 实际命中的材质数
   */
  applyAll(model) {
    let hits = 0
    for (const name of this.index.keys()) {
      if (this.apply(name, model.get(name))) hits += 1
    }
    this.reapplyPartsFor(null)
    return hits
  }

  // -- 零件级覆盖(克隆层) ------------------------------------------------

  /**
   * 功能: 把补丁写进一个克隆条目 —— 底 = 类材质**实时**快照, 叠零件补丁.
   *
   * 底每次都从类材质现值取而不是缓存: 类调整之后, 零件未覆盖的字段要自动跟随类.
   *
   * @param {{original: THREE.Material, clone: THREE.Material, patch: object}} entry 克隆条目
   * @returns {void}
   */
  _writeMerged(entry) {
    const merged = { ...this._snapshot(entry.original), ...entry.patch }
    const material = entry.clone
    for (const [field, prop] of Object.entries(PROP_MAP)) {
      if (!(prop in material) || !(field in merged)) continue
      const value = merged[field]
      if (material[prop]?.isColor) material[prop].set(value)
      else material[prop] = Number(value)
    }
    syncAlphaFlags(material, merged)
  }

  /**
   * 功能: 给一组网格(通常是一个零件的子树)应用零件级覆盖补丁.
   *
   * 补丁非空 → 确保克隆(类材质克隆为 `<类名>@part`)并写合成值;
   * 补丁为空 → 还原类材质并回收克隆.
   *
   * @param {THREE.Mesh[]} meshes 零件网格
   * @param {object} patch 覆盖补丁
   * @returns {number} 实际处理的网格数
   */
  applyPart(meshes, patch) {
    const list = (meshes || []).filter(
      (mesh) => mesh.isMesh && mesh.material && !Array.isArray(mesh.material),
    )
    if (!list.length) return 0

    const empty = !patch || !Object.keys(patch).length
    for (const mesh of list) {
      let entry = this._partClones.get(mesh)
      if (empty) {
        if (entry) {
          mesh.material = entry.original
          entry.clone.dispose()
          this._partClones.delete(mesh)
        }
        continue
      }
      if (!entry) {
        const original = mesh.material
        const clone = original.clone()
        clone.name = `${original.name}@part`
        entry = { original, clone, patch: {} }
        this._partClones.set(mesh, entry)
        mesh.material = clone
      }
      entry.patch = { ...patch }
      this._writeMerged(entry)
    }
    if (!empty && 'metalness' in patch) this.manager.refreshEnvBoost?.()
    return list.length
  }

  /**
   * 功能: 重放零件克隆(类材质调整之后底变了, 合成值要跟着变).
   * @param {string|null} materialName 只重放底为该类的克隆; null = 全部
   * @returns {void}
   */
  reapplyPartsFor(materialName = null) {
    for (const entry of this._partClones.values()) {
      if (!materialName || entry.original.name === materialName) this._writeMerged(entry)
    }
  }

  /**
   * 功能: 零件覆盖编辑器的"原值"列 —— 类材质当前状态(覆盖前的底).
   * @param {THREE.Mesh[]} meshes 零件网格
   * @returns {object} 快照
   */
  partBaseline(meshes) {
    const mesh = (meshes || []).find((m) => m.isMesh && m.material)
    if (!mesh) return {}
    const entry = this._partClones.get(mesh)
    const material = entry
      ? entry.original
      : Array.isArray(mesh.material)
        ? mesh.material[0]
        : mesh.material
    return material ? this._snapshot(material) : {}
  }

  /**
   * 功能: 零件当前生效值(克隆存在时取克隆).
   * @param {THREE.Mesh[]} meshes 零件网格
   * @returns {object} 快照
   */
  partSnapshot(meshes) {
    const mesh = (meshes || []).find((m) => m.isMesh && m.material)
    if (!mesh) return {}
    const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
    return material ? this._snapshot(material) : {}
  }

  // -- 材质组(共享克隆层) ------------------------------------------------

  /**
   * 功能: 把组合成值(底=类材质实时快照 ⊕ 组参数)写进组共享克隆.
   * @param {object} entry 组条目
   * @returns {void}
   */
  _writeGroupMerged(entry) {
    const base = this.index.get(entry.baseName)?.material
    if (!base) return
    const merged = { ...this._snapshot(base), ...entry.patch }
    const material = entry.clone
    for (const [field, prop] of Object.entries(PROP_MAP)) {
      if (!(prop in material) || !(field in merged)) continue
      const value = merged[field]
      if (material[prop]?.isColor) material[prop].set(value)
      else material[prop] = Number(value)
    }
    syncAlphaFlags(material, merged)
  }

  /**
   * 功能: 应用/更新一个材质组 —— 成员统一换装组共享克隆并写合成值.
   *
   * @param {string} name 组名
   * @param {THREE.Mesh[]} meshes 本次要纳入的成员网格
   * @param {object} patch 组参数
   * @param {string} baseClassName 组底的材质类名(parts 首个可解析成员的类)
   * @returns {number} 组内成员网格数
   */
  applyGroup(name, meshes, patch, baseClassName) {
    let entry = this._groupClones.get(name)
    if (!entry) {
      const base = this.index.get(baseClassName)?.material
      if (!base) return 0
      const clone = base.clone()
      clone.name = `GROUP_${name}@part`
      entry = { clone, baseName: baseClassName, members: new Map(), patch: {} }
      this._groupClones.set(name, entry)
    }
    entry.patch = { ...(patch || {}) }

    const list = (meshes || []).filter(
      (mesh) => mesh.isMesh && mesh.material && !Array.isArray(mesh.material),
    )
    for (const mesh of list) {
      if (entry.members.has(mesh)) continue
      const partEntry = this._partClones.get(mesh)
      if (partEntry) {
        // 件克隆在场: 不动 mesh.material(件压过组), 只把件的底重指组
        entry.members.set(mesh, partEntry.original)
        partEntry.original = entry.clone
      } else {
        entry.members.set(mesh, mesh.material)
        mesh.material = entry.clone
      }
    }

    this._writeGroupMerged(entry)
    // 底变了: 重放组内成员的件克隆合成值
    for (const mesh of entry.members.keys()) {
      const partEntry = this._partClones.get(mesh)
      if (partEntry) this._writeMerged(partEntry)
    }
    if (patch && 'metalness' in patch) this.manager.refreshEnvBoost?.()
    return entry.members.size
  }

  /**
   * 功能: 把一批网格移出组(还原到接管前材质; 件克隆的底指回原处).
   * @param {string} name 组名
   * @param {THREE.Mesh[]} meshes 网格
   * @returns {void}
   */
  removeGroupMember(name, meshes) {
    const entry = this._groupClones.get(name)
    if (!entry) return
    for (const mesh of meshes || []) {
      const preGroup = entry.members.get(mesh)
      if (preGroup === undefined) continue
      const partEntry = this._partClones.get(mesh)
      if (partEntry) {
        partEntry.original = preGroup
        this._writeMerged(partEntry)
      } else {
        mesh.material = preGroup
      }
      entry.members.delete(mesh)
    }
    if (!entry.members.size) {
      entry.clone.dispose()
      this._groupClones.delete(name)
    }
  }

  /**
   * 功能: 解散一个组(全部成员还原并回收克隆).
   * @param {string} name 组名
   * @returns {void}
   */
  dissolveGroup(name) {
    const entry = this._groupClones.get(name)
    if (!entry) return
    this.removeGroupMember(name, [...entry.members.keys()])
  }

  /**
   * 功能: 重放组合成值(类材质调整之后底变了).
   * @param {string|null} classMaterialName 只重放底为该类的组; null = 全部
   * @returns {void}
   */
  reapplyGroupsFor(classMaterialName = null) {
    for (const entry of this._groupClones.values()) {
      if (classMaterialName && entry.baseName !== classMaterialName) continue
      this._writeGroupMerged(entry)
      for (const mesh of entry.members.keys()) {
        const partEntry = this._partClones.get(mesh)
        if (partEntry) this._writeMerged(partEntry)
      }
    }
  }

  /**
   * 功能: 组当前生效值(编辑器 current 列).
   * @param {string} name 组名
   * @returns {object} 快照
   */
  groupSnapshot(name) {
    const entry = this._groupClones.get(name)
    return entry ? this._snapshot(entry.clone) : {}
  }

  /**
   * 功能: 某材质类的**当前**快照(初始值 ⊕ 类覆盖后的现值; 组编辑器的"原值"列).
   * @param {string} name 材质类名
   * @returns {object} 快照
   */
  classSnapshot(name) {
    const material = this.index.get(name)?.material
    return material ? this._snapshot(material) : {}
  }

  /**
   * 功能: 场景侧现存的组名(数据→场景同步的对账用).
   * @returns {string[]} 组名数组
   */
  groupNames() {
    return [...this._groupClones.keys()]
  }

  /**
   * 功能: 组底的材质类名.
   * @param {string} name 组名
   * @returns {string} 类名
   */
  groupBaseClass(name) {
    return this._groupClones.get(name)?.baseName || ''
  }

  /**
   * 功能: 组成员网格(高亮/取景用).
   * @param {string} name 组名
   * @returns {THREE.Mesh[]} 网格数组
   */
  groupMeshes(name) {
    return [...(this._groupClones.get(name)?.members.keys() || [])]
  }

  /**
   * 功能: 只读射线拾取(右键菜单用) —— 不改任何选中状态.
   * @param {number} clientX 屏幕坐标
   * @param {number} clientY 屏幕坐标
   * @returns {{mesh: THREE.Mesh, material: string, point: THREE.Vector3}|null} 命中信息
   *          (point 为世界坐标命中点, 合并块的成员候选按它比对 bbox)
   */
  pickAt(clientX, clientY) {
    const canvas = this.manager.canvas
    const root = this.manager.machineRoot
    if (!canvas || !root) return null
    const rect = canvas.getBoundingClientRect()
    this.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.manager.camera)
    const hits = this.raycaster.intersectObject(root, true)
    const hit = hits.find((item) => item.object?.isMesh && item.object.visible)
    if (!hit) return null
    const list = Array.isArray(hit.object.material) ? hit.object.material : [hit.object.material]
    return {
      mesh: hit.object,
      material: (list[0]?.name || '').replace(/@part$/, ''),
      point: hit.point.clone(),
    }
  }

  /**
   * 功能: 零件所属的材质类名(克隆存在时取克隆的底).
   * @param {THREE.Mesh[]} meshes 零件网格
   * @returns {string} 材质类名
   */
  partClassNameOf(meshes) {
    const mesh = (meshes || []).find((m) => m.isMesh && m.material)
    if (!mesh) return ''
    const entry = this._partClones.get(mesh)
    const material = entry
      ? entry.original
      : Array.isArray(mesh.material)
        ? mesh.material[0]
        : mesh.material
    return material?.name || ''
  }

  /**
   * 功能: 解除高亮并把材质恢复到初始状态.
   * @returns {void}
   */
  dispose() {
    const canvas = this.manager.canvas
    if (canvas) {
      if (this._onDown) canvas.removeEventListener('pointerdown', this._onDown)
      if (this._onUp) canvas.removeEventListener('pointerup', this._onUp)
    }
    this.manager.effects?.setSelected([])
    // 还原顺序: 件 → 组 → 类. 件克隆的 original 可能是组克隆, 先把 mesh.material
    // 指回它; 组还原再把成员统一退回类共享材质; 最后类材质刷回初始值.
    for (const [mesh, entry] of this._partClones) {
      mesh.material = entry.original
      entry.clone.dispose()
    }
    this._partClones.clear()
    for (const name of [...this._groupClones.keys()]) this.dissolveGroup(name)
    for (const name of this.index.keys()) this.apply(name, {})
    this.index.clear()
    this._baseline.clear()
  }
}
