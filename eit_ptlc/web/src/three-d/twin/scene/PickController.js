/**
 * 功能: 鼠标拾取 —— 悬停高亮、点击选中、双击飞行到工位.
 *
 * 拾取粒度是"工位"而不是"零件": 用户关心的是"点开展开工位看它的状态", 而不是
 * "选中第 37 号安装板". 因此射线命中任意网格后, 沿父级链向上找到最近的 ST_* 工位根,
 * 高亮整个工位.
 *
 * 性能: 整机有两百多万三角形, three 默认的逐三角形求交单次要几十毫秒, 指针一动主线程
 * 就卡一格. 因此这里必须上 BVH(three-mesh-bvh): 构造时给每个可拾取网格建包围盒树,
 * 建树约一秒(发生在加载遮罩还在的阶段), 换来每次射线检测亚毫秒. 另外两条节流:
 *   - pointermove 只记位置, 在渲染帧里统一处理(每帧至多一次);
 *   - 按住拖拽(旋转视角)期间完全跳过检测 —— 拖拽时用户要的是转镜头, 不是悬停高亮.
 */
import * as THREE from 'three'
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh'

// 全局补丁是幂等的: 没建过 boundsTree 的几何走 three 原生路径,
// 材质台/装配台的点击拾取不受影响
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree
THREE.Mesh.prototype.raycast = acceleratedRaycast

/** 判定为"点击"而非"拖拽旋转"的位移阈值(像素) */
const CLICK_MOVE_TOLERANCE = 4

export class PickController {
  /**
   * 功能: 绑定指针事件.
   * @param {object} options 参数对象
   * @param {HTMLElement} options.domElement 事件宿主(canvas)
   * @param {THREE.Camera} options.camera 相机
   * @param {Map<string, THREE.Object3D>} options.stationRoots 工位 id -> 根节点
   * @param {(stationId: string|null) => void} [options.onHover] 悬停回调
   * @param {(stationId: string|null) => void} [options.onSelect] 选中回调
   * @param {(stationId: string) => void} [options.onActivate] 双击回调
   */
  constructor({ domElement, camera, stationRoots, onHover, onSelect, onActivate }) {
    this.domElement = domElement
    this.camera = camera
    this.stationRoots = stationRoots
    this.onHover = onHover
    this.onSelect = onSelect
    this.onActivate = onActivate

    this.raycaster = new THREE.Raycaster()
    // BVH 找到最近命中即可提前返回; 悬停只关心 hits[0], 不需要完整命中列表
    this.raycaster.firstHitOnly = true
    this.pointer = new THREE.Vector2()
    this.enabled = true

    this.hovered = null
    this.selected = null

    /** 待处理的指针位置; 在渲染帧里统一处理, 天然完成节流 */
    this._pendingPointer = null
    this._downPosition = null
    /** 按住拖拽(旋转视角)期间跳过悬停检测 */
    this._dragging = false

    // 反向索引: 网格 -> 工位 id, 一次建好, 拾取时 O(1) 命中;
    // 同一次遍历为每个几何建 BVH, 建过树的记下来供 dispose 释放
    this._ownerByObject = new Map()
    this._bvhGeometries = new Set()
    for (const [stationId, root] of stationRoots) {
      root.traverse((child) => {
        if (!child.isMesh) return
        this._ownerByObject.set(child, stationId)
        if (child.geometry && !child.geometry.boundsTree) {
          child.geometry.computeBoundsTree()
          this._bvhGeometries.add(child.geometry)
        }
      })
    }
    this._pickables = [...stationRoots.values()]

    this._bind()
  }

  /**
   * 功能: 绑定 DOM 事件.
   * @returns {void}
   */
  _bind() {
    this._onPointerMove = (event) => {
      if (!this.enabled) return
      const rect = this.domElement.getBoundingClientRect()
      this._pendingPointer = {
        x: ((event.clientX - rect.left) / rect.width) * 2 - 1,
        y: -((event.clientY - rect.top) / rect.height) * 2 + 1,
      }
    }

    this._onPointerDown = (event) => {
      this._downPosition = { x: event.clientX, y: event.clientY }
      this._dragging = true
    }

    this._onPointerUp = (event) => {
      this._dragging = false
      // 只认左键: 右键语义已归 平移相机/物料快捷菜单 (MaterialInteraction), 右键单击
      // 不该顺带把悬停工位设为选中弹出 StationPanel (缺陷修正, 右键选工位从非文档化行为)
      if (event.button !== 0) return
      if (!this.enabled || !this._downPosition) return
      const moved =
        Math.abs(event.clientX - this._downPosition.x) +
        Math.abs(event.clientY - this._downPosition.y)
      this._downPosition = null
      // 拖拽旋转视角时不应触发选中
      if (moved > CLICK_MOVE_TOLERANCE) return

      this.selected = this.hovered
      this.onSelect?.(this.selected)
    }

    this._onDoubleClick = () => {
      if (this.enabled && this.hovered) this.onActivate?.(this.hovered)
    }

    this._onPointerLeave = () => {
      this._pendingPointer = null
      this._dragging = false
      if (this.hovered !== null) {
        this.hovered = null
        this.onHover?.(null)
      }
    }

    this.domElement.addEventListener('pointermove', this._onPointerMove)
    this.domElement.addEventListener('pointerdown', this._onPointerDown)
    this.domElement.addEventListener('pointerup', this._onPointerUp)
    this.domElement.addEventListener('dblclick', this._onDoubleClick)
    this.domElement.addEventListener('pointerleave', this._onPointerLeave)
  }

  /**
   * 功能: 每帧处理一次待定的指针位置(由 SceneManager 帧回调驱动).
   * @returns {void}
   */
  update() {
    if (!this.enabled || !this._pendingPointer) return
    // 拖拽旋转期间指针每帧都在动, 悬停结果没人看; 丢弃待定位置, 松手后再恢复检测
    if (this._dragging) {
      this._pendingPointer = null
      return
    }
    this.pointer.set(this._pendingPointer.x, this._pendingPointer.y)
    this._pendingPointer = null

    this.raycaster.setFromCamera(this.pointer, this.camera)
    const hits = this.raycaster.intersectObjects(this._pickables, true)

    let stationId = null
    for (const hit of hits) {
      const owner = this._ownerByObject.get(hit.object)
      if (owner) {
        stationId = owner
        break
      }
    }

    if (stationId !== this.hovered) {
      this.hovered = stationId
      this.domElement.style.cursor = stationId ? 'pointer' : 'default'
      this.onHover?.(stationId)
    }
  }

  /**
   * 功能: 以编程方式设置选中工位(供列表点击等外部入口使用).
   * @param {string|null} stationId 工位 id
   * @returns {void}
   */
  setSelected(stationId) {
    this.selected = stationId
    this.onSelect?.(stationId)
  }

  /**
   * 功能: 解绑事件.
   * @returns {void}
   */
  dispose() {
    this.domElement.removeEventListener('pointermove', this._onPointerMove)
    this.domElement.removeEventListener('pointerdown', this._onPointerDown)
    this.domElement.removeEventListener('pointerup', this._onPointerUp)
    this.domElement.removeEventListener('dblclick', this._onDoubleClick)
    this.domElement.removeEventListener('pointerleave', this._onPointerLeave)
    this.domElement.style.cursor = 'default'
    // BVH 是纯 CPU 内存(几十 MB), 随本控制器一起释放; 必须在场景几何 dispose 之前
    // (SceneManager.unloadMachineModel 保证了这个顺序)
    for (const geometry of this._bvhGeometries) geometry.disposeBoundsTree()
    this._bvhGeometries.clear()
    this._ownerByObject.clear()
    this._pickables.length = 0
  }
}
