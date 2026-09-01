/**
 * 功能: 物料实体的按需拾取 —— 右键点选托盘孔位/耗材件/中转托盘/板仓堆.
 *
 * 与工位 PickController 的差异 (刻意):
 *   - **按需**拾取 (菜单一击才 raycast 一次), 无悬停、无事件监听、无帧钩子 ——
 *     零每帧开销, 这是 live 页零回归的最强保证;
 *   - 不建 BVH: INV 节点挂在 ST_RACK/ST_STAGINGA 工位根之下, PickController 构造时
 *     已给它们建过 boundsTree 且全局 acceleratedRaycast 补丁生效 (白拿加速);
 *     板仓堆是运行时新建的 InstancedMesh (≤40 实例单位盒), 原生路径已够快。
 *     树的生命周期归 PickController 管, 本控制器**绝不重复建/释放**。
 *
 * 命中裁决顺序 (纯函数在 materialPick.js): 可见性守卫 -> item 祖先优先 ->
 * tray 兜底 -> 最近孔反查 (空孔无可见实体, 点托盘本体吸附到孔) -> 阈值外算托盘本体。
 */
import * as THREE from 'three'

import { cellDisplaySite, isShownUpTo, nearestHole, resolveHit } from './materialPick.js'

export class MaterialPickController {
  /**
   * 功能: 建反向索引 (mesh -> 物料身份) 与孔位 home 局部位缓存.
   * @param {object} options 参数对象
   * @param {THREE.Camera} options.camera 相机
   * @param {object} options.bindings TwinBindings (materialRack/materialStaging 已解析)
   * @param {object|null} [options.plateLayer] PlateFaceLayer (板仓堆拾取目标)
   */
  constructor({ camera, bindings, plateLayer = null }) {
    this.camera = camera
    this.raycaster = new THREE.Raycaster()
    /** mesh/节点 -> 身份; item 按网格逐个登记 (深者优先), tray 登记整个 entry 节点 */
    this._ownerByMesh = new Map()
    /** entry 节点 -> 孔位 home 局部位 (在途时节点已挂去 TOOL_MOUNT, 必须用建索引时的缓存) */
    this._holeOffsets = new Map()
    this._pickables = []

    /** 正向索引: 'kind:plate:hole' -> 货架 item 节点 (面板选孔反向定位描边目标) */
    this._rackItemIndex = new Map()
    /** 正向索引: 'area:hole' -> 中转 item 节点 (板号流动, 键里不含 plate) */
    this._stagingItemIndex = new Map()

    const indexEntry = (entry, base) => {
      const offsets = []
      ;(entry.items || []).forEach((item, index) => {
        const identity = { ...base, type: 'item', hole: index + 1, node: item }
        item.traverse((child) => {
          if (child.isMesh) this._ownerByMesh.set(child, identity)
        })
        // Group (粉桶 4 mesh) 与单 mesh (收集瓶) 形态不一: 节点本身也登记, 供父链兜底
        this._ownerByMesh.set(item, identity)
        offsets.push({ hole: index + 1,
                       x: item.position.x, y: item.position.y, z: item.position.z })
        if (base.loc === 'rack') {
          this._rackItemIndex.set(`${base.kind}:${base.plate}:${index + 1}`, item)
        } else {
          this._stagingItemIndex.set(`${base.area}:${index + 1}`, item)
        }
      })
      const trayIdentity = { ...base, type: 'tray', hole: null, node: entry.node }
      entry.node.traverse((child) => {
        if (child.isMesh && !this._ownerByMesh.has(child)) {
          this._ownerByMesh.set(child, trayIdentity)
        }
      })
      this._holeOffsets.set(entry.node, offsets)
      this._pickables.push(entry.node)
    }

    for (const entry of bindings?.materialRack || []) {
      indexEntry(entry, { loc: 'rack', kind: entry.spec.kind,
                          plate: entry.spec.plate, area: null })
    }
    for (const entry of bindings?.materialStaging || []) {
      // 中转板号是流动的: 建索引恒 null, 菜单时刻从快照现取 (materialPick.identityAtMenuTime)
      indexEntry(entry, { loc: 'staging', kind: entry.spec.kind,
                          plate: null, area: entry.spec.area })
    }
    // 板仓堆是收到第一帧账本后才懒创建的 InstancedMesh, 构造期查会拿到空表 ——
    // 留引用在 pickAt 时现查 (拾取本就按需, 每击一次的组装成本可忽略)
    this._plateLayer = plateLayer
  }

  /**
   * 功能: 在指定屏幕坐标做一次拾取.
   * @param {number} clientX 屏幕 X
   * @param {number} clientY 屏幕 Y
   * @param {HTMLElement} domElement 画布 (取矩形换算 NDC)
   * @returns {{identity: object, meshes: THREE.Object3D[]}|null} 命中身份与描边目标
   */
  pickAt(clientX, clientY, domElement) {
    const rect = domElement.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    )
    this.raycaster.setFromCamera(ndc, this.camera)
    // 板仓堆现查 (懒创建的 InstancedMesh); 身份临时并进索引, 拾取按需故成本可忽略
    const magazineMeshes = []
    for (const target of this._plateLayer?.magazineHitTargets?.() || []) {
      const identity = { type: 'magazine', magazine: target.magazine }
      for (const mesh of target.meshes) {
        this._ownerByMesh.set(mesh, identity)
        magazineMeshes.push(mesh)
      }
    }
    const hits = this.raycaster.intersectObjects(
      [...this._pickables, ...magazineMeshes], true)
    // 空孔回退: 96 孔板是真通孔, 指着孔心的射线会从孔里穿出去打不到托盘面 ——
    // 但它必然穿过该孔隐藏件自己的网格。被可见性守卫滤掉的 item 命中记下来,
    // 全部可见命中都落空时按"点这个孔"处理 (绝不当可见 item 选中, 守卫语义不变)。
    let hiddenItemHit = null
    for (const hit of hits) {
      const owner = resolveHit(hit.object, this._ownerByMesh)
      if (!owner) continue
      // Raycaster 不查 visible: 空孔位的隐藏件必须滤掉, 否则会"隔空点到看不见的瓶子"
      if (!isShownUpTo(hit.object)) {
        if (owner.type === 'item' && hiddenItemHit === null) hiddenItemHit = owner
        continue
      }
      if (owner.type === 'item') {
        return { identity: { ...owner }, meshes: this._meshesOf(owner.node) }
      }
      if (owner.type === 'magazine') {
        return { identity: { ...owner }, meshes: [hit.object] }
      }
      // 托盘本体命中: 在托盘局部系吸附最近孔 (孔隙处的空孔拾取通路)
      const local = owner.node.worldToLocal(hit.point.clone())
      const snap = nearestHole(local, this._holeOffsets.get(owner.node) || [])
      if (snap) {
        return { identity: { ...owner, type: 'hole', hole: snap.hole },
                 meshes: [hit.object] }
      }
      return { identity: { ...owner }, meshes: [hit.object] }
    }
    if (hiddenItemHit !== null) {
      // 无可见目标可描边: 菜单本身就是反馈
      return { identity: { ...hiddenItemHit, type: 'hole' }, meshes: [] }
    }
    return null
  }

  /**
   * 功能: 反向解析 —— 面板选中的 (kind, plate, hole) 此刻对应哪个三维实体.
   *
   * 裁决镜像 TwinBindings 的显示裁决(纯函数 cellDisplaySite): 板被搬到中转区时
   * 实体画在中转托盘的 item 上, 否则在货架; 整板在途(爪上)时无处可指, 返回空表 ——
   * 描边落空由面板高亮承担反馈(与右键"菜单即反馈"同款约定)。
   * @param {string} kind 耗材种类
   * @param {number} plate 板号
   * @param {number} hole 孔号 1-6
   * @param {object|null} snapshot MaterialStateStore 快照
   * @returns {{node: THREE.Object3D|null, meshes: THREE.Object3D[]}} 实体与描边目标
   */
  resolveCell(kind, plate, hole, snapshot) {
    const site = cellDisplaySite(kind, plate, snapshot)
    if (!site) return { node: null, meshes: [] }
    const node = site.site === 'staging'
      ? this._stagingItemIndex.get(`${site.area}:${hole}`)
      : this._rackItemIndex.get(`${kind}:${plate}:${hole}`)
    if (!node) return { node: null, meshes: [] }
    // 空孔(件隐藏)不描边 —— 描一个看不见的网格会画出悬空轮廓
    if (!isShownUpTo(node)) return { node, meshes: [] }
    return { node, meshes: this._meshesOf(node) }
  }

  /**
   * 功能: 收集某 item 节点下的全部网格 (描边目标; 瓶=单 mesh, 桶=4 mesh Group).
   * @param {THREE.Object3D} node item 节点
   * @returns {THREE.Object3D[]} 网格列表
   */
  _meshesOf(node) {
    const meshes = []
    node.traverse((child) => {
      if (child.isMesh) meshes.push(child)
    })
    return meshes
  }

  /** 功能: 释放索引 (不碰 boundsTree —— 树归 PickController 管). */
  dispose() {
    this._ownerByMesh.clear()
    this._holeOffsets.clear()
    this._pickables.length = 0
    this._rackItemIndex.clear()
    this._stagingItemIndex.clear()
  }
}
