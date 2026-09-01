/**
 * 功能: 视口内 1-DOF 约束拖拽 —— 抓住滑块组沿其轴线拖动, 直驱 MachineStateDriver.
 *
 * 只做平移轴(关节旋转 v1 用滑杆). 数学: **拖拽平面投影**(three.js TransformControls 同法) ——
 * 按下时取命中点 Pg 与轴向 d, 造一张过 Pg、含 d、法向最正对相机的平面
 *     n = normalize(viewDir − (viewDir·d)·d)      (n·d ≡ 0, 故 d 在平面内)
 * 每帧把指针射线与该平面求交得 X, 拖拽量 s = (X − Pg)·d 米,
 * 换算 mm: Δmm = (s − s0) / axisUnitPerMm(spec). clamp 由 setAxisMm 天然完成.
 * (axisUnitPerMm = sign · scaleMm · mmToUnit, 与 setAxisMm **同源**; scaleMm 是
 *  控制侧 mm→物理 mm 的增益, 目前只有 axis_4x=2.0。若这里各写各的, 4X 拖拽会差一倍。)
 *
 * ⚠ 不要退回"指针射线与轴线的最近点"闭式解(2026-08-05 前的实现). 那个解有两处硬伤,
 *   已用 tests/three-d/axisDrag.test.js 逐档量化复现:
 *   (a) 它跟的是**轴线**而不是抓取点, 而滑车零件从不正好骑在枢轴上 —— 增益随
 *       "相机↔轴线距离"塌缩, 实测同一次 20 mm 的拖拽在 22.2 m 处得 20.1 mm、
 *       在 minDistance(0.222 m)处得 29.3 mm, 枢轴偏离 1 m 时更到 98.9 mm(5 倍);
 *   (b) 解含 1/(1−(d·rd)²), 射线近平行于轴时发散, 旧代码用 PARALLEL_EPS 硬切到
 *       另一套"1 米探针 + NDC 位移"的估计器 —— 那根 1 米探针近距时会落到眼平面之后,
 *       project() 除以负 w 把 NDC 整体镜像, **拖拽方向直接翻 180°**.
 *       实测俯视 12° 时: 22.2/4.23/1.0/0.5 m 都给 +20 mm, 到 0.3 m 与 0.222 m 变成
 *       −27.1/−26.1 mm, 与用户"缩小正常、放大变反"的报告逐字吻合.
 *   这条不是手感问题: AXIS_ZERO_CALIBRATION 七步法第 2 步靠"jog 看虚拟动向"定 sign,
 *   拖拽会翻向就意味着标定出的 sign 会被写错并传到现场.
 *
 * 视角与轴近平行(|n| < AXIS_FACING_EPS)时轴在屏幕上几乎没有投影长度, 任何解法都病态:
 * 本实现**明确拒动并回报 blocked**, 由 HUD 提示旋转视角, 不再静默乱走.
 *
 * 手势互斥: 命中可动件才进入拖拽, 进入即禁相机 + setPointerCapture; Esc 归位取消.
 */
import * as THREE from 'three'

import { axisUnitPerMm } from '../anim/MachineStateDriver.js'

/** 平面法向的最小模长 = 视线与轴夹角的正弦; 0.15 ≈ 8.6°, 与旧 PARALLEL_EPS 的锥角相当 */
const AXIS_FACING_EPS = 0.15

export class AxisDragController {
  /**
   * 功能: 绑定到画布(即刻生效).
   * @param {object} options 参数
   * @param {import('../twin/scene/SceneManager.js').SceneManager} options.manager 场景管理器
   * @param {import('../anim/MachineStateDriver.js').MachineStateDriver} options.rig 状态驱动层
   * @param {(state: {axisId: string, mm: number}|null) => void} [options.onDrag] 拖拽反馈(HUD 浮字)
   */
  constructor({ manager, rig, onDrag }) {
    this.manager = manager
    this.rig = rig
    this.onDrag = onDrag

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()
    /** @type {Map<THREE.Mesh, string>} 可拖网格 -> 轴 id */
    this.meshAxis = new Map()
    this._meshList = []
    this._drag = null
    this._line = null

    this.refresh()
    this._bind()
  }

  /**
   * 功能: 重建可拖网格索引(rig 的 rigged 轴 carriage 子树).
   * @returns {void}
   */
  refresh() {
    this.meshAxis.clear()
    for (const [axisId, entry] of this.rig.axes) {
      entry.node.traverse((child) => {
        if (child.isMesh) this.meshAxis.set(child, axisId)
      })
    }
    this._meshList = [...this.meshAxis.keys()]
  }

  /**
   * 功能: 绑定指针事件.
   * @returns {void}
   */
  _bind() {
    const dom = this.manager.canvas

    this._onDown = (event) => {
      if (event.button !== 0 || !this._meshList.length) return
      this._updatePointer(event)
      this.raycaster.setFromCamera(this.pointer, this.manager.camera)
      const hits = this.raycaster.intersectObjects(this._meshList, false)
      const hit = hits.find((item) => item.object.visible)
      if (!hit) return
      this._start(event, this.meshAxis.get(hit.object), hit.point)
    }
    this._onMove = (event) => {
      if (this._drag) this._update(event)
    }
    this._onUp = () => {
      if (this._drag) this._end(false)
    }
    this._onKey = (event) => {
      if (event.key === 'Escape' && this._drag) this._end(true)
    }

    dom.addEventListener('pointerdown', this._onDown)
    dom.addEventListener('pointermove', this._onMove)
    dom.addEventListener('pointerup', this._onUp)
    dom.addEventListener('pointercancel', this._onUp)
    window.addEventListener('keydown', this._onKey)
  }

  /**
   * 功能: 进入拖拽 —— 锁相机、捕获指针、造拖拽平面并标定起始参数.
   * @param {PointerEvent} event 指针事件
   * @param {string} axisId 轴 id
   * @param {THREE.Vector3} grabPoint 射线命中的世界表面点(拖拽平面过这一点)
   * @returns {void}
   */
  _start(event, axisId, grabPoint) {
    const entry = this.rig.axes.get(axisId)
    if (!entry) return

    // 轴线原点与世界方向: entry.direction 是父局部系方向(位移加在父局部 position 上),
    // 必须经父级世界旋转变换
    const origin = entry.node.getWorldPosition(new THREE.Vector3())
    const parentQuat = new THREE.Quaternion()
    entry.node.parent?.getWorldQuaternion(parentQuat)
    const dir = entry.direction.clone().applyQuaternion(parentQuat).normalize()

    const startMm = Number.isFinite(entry.valueMm)
      ? entry.valueMm
      : Number(entry.spec.zeroOffsetMm || 0)

    // 拖拽平面: 过抓取点、含轴向 d、法向最正对相机。|n| = sin(视线与轴夹角),
    // 它同时就是这次拖拽的条件数 —— 太小说明轴在屏幕上没有投影长度, 拒动。
    // viewDir 在此冻结: 拖拽期间相机被锁, 但 camera-controls 的 smoothTime 过渡
    // 可能仍在跑, 逐帧重算平面会让映射在拖拽中途漂移。
    const viewDir = this.manager.camera.getWorldDirection(new THREE.Vector3())
    const planeNormal = viewDir.clone().addScaledVector(dir, -viewDir.dot(dir))
    const facing = planeNormal.length()
    const blocked = !(facing >= AXIS_FACING_EPS)
    if (!blocked) planeNormal.divideScalar(facing)

    // 注意这里**不留** origin: 新算法只认抓取点 grab, 轴线原点仅用于画辅助线。
    // 旧实现把 origin 存进拖拽态并拿它当基准, 正是"跟轴线而不跟抓取点"那个增益病的来源。
    this._drag = {
      axisId,
      entry,
      dir,
      grab: grabPoint ? grabPoint.clone() : origin.clone(),
      planeNormal,
      blocked,
      startMm,
      s0: 0,
      pointerId: event.pointerId,
    }
    // 按下时指针射线恰好穿过抓取点(它就在平面上), 故 s0 理论上为 0;
    // 仍实算一次吸收浮点与 setFromCamera 的舍入。
    const s0 = blocked ? 0 : this._paramAt(event)
    this._drag.s0 = Number.isFinite(s0) ? s0 : 0

    const controls = this.manager.cameraRig?.controls
    if (controls) {
      this._drag.controlsEnabled = controls.enabled
      controls.enabled = false
    }
    this.manager.canvas.setPointerCapture?.(event.pointerId)
    this.manager.canvas.style.cursor = blocked ? 'not-allowed' : 'grabbing'
    this._showLine(entry, origin, dir)
    this.onDrag?.({ axisId, mm: startMm, blocked })
  }

  /**
   * 功能: 求指针射线与拖拽平面的交点在轴向上的参数 s(米, 相对抓取点).
   * @param {PointerEvent} event 指针事件
   * @returns {number|null} s; 射线与平面近平行或交点在相机背后时为 null
   */
  _paramAt(event) {
    this._updatePointer(event)
    const drag = this._drag
    if (drag.blocked) return null
    this.raycaster.setFromCamera(this.pointer, this.manager.camera)
    const { origin: ro, direction: rd } = this.raycaster.ray
    const denom = rd.dot(drag.planeNormal)
    if (Math.abs(denom) < 1e-6) return null
    const t = drag.grab.clone().sub(ro).dot(drag.planeNormal) / denom
    if (!(t > 0)) return null // 交点落到相机背后, 这一帧不可信
    return ro.clone().addScaledVector(rd, t).sub(drag.grab).dot(drag.dir)
  }

  /**
   * 功能: 拖拽中 —— 参数差换算 mm 并写入驱动层.
   * @param {PointerEvent} event 指针事件
   * @returns {void}
   */
  _update(event) {
    const drag = this._drag
    const s = this._paramAt(event)
    if (s === null || !Number.isFinite(s)) {
      // 病态姿态: 如实回报, 不写驱动层 —— 静默乱走会把错误 sign 标进 rig_map
      this.onDrag?.({ axisId: drag.axisId, mm: drag.entry.valueMm, blocked: true })
      return
    }
    const spec = drag.entry.spec
    // 与 setAxisMm 共用同一口径(含 scaleMm 增益), 一乘一除必须同源 —— 见 axisUnitPerMm
    const perMm = axisUnitPerMm(spec)
    if (!perMm) return
    const mm = drag.startMm + (s - drag.s0) / perMm
    this.rig.setAxisMm(drag.axisId, mm)
    this.manager.invalidateShadows()
    this.onDrag?.({ axisId: drag.axisId, mm: drag.entry.valueMm, blocked: false })
  }

  /**
   * 功能: 结束拖拽.
   * @param {boolean} cancel 是否取消(Esc 归位到拖始值)
   * @returns {void}
   */
  _end(cancel) {
    const drag = this._drag
    this._drag = null
    if (cancel) {
      this.rig.setAxisMm(drag.axisId, drag.startMm)
      this.manager.invalidateShadows()
    }
    const controls = this.manager.cameraRig?.controls
    if (controls) controls.enabled = drag.controlsEnabled ?? true
    this.manager.canvas.releasePointerCapture?.(drag.pointerId)
    this.manager.canvas.style.cursor = 'default'
    this._hideLine()
    this.onDrag?.(null)
  }

  /**
   * 功能: 拖拽期间显示轴线辅助线(行程两端).
   * @param {object} entry 轴条目
   * @param {THREE.Vector3} origin 世界原点
   * @param {THREE.Vector3} dir 世界方向
   * @returns {void}
   */
  _showLine(entry, origin, dir) {
    const spec = entry.spec
    const [minMm, maxMm] = spec.rangeMm || [0, 0]
    const perMm = Number(spec.sign ?? 1) * Number(spec.mmToUnit || 0.001)
    const current = Number.isFinite(entry.valueMm) ? entry.valueMm : Number(spec.zeroOffsetMm || 0)
    const a = origin.clone().add(dir.clone().multiplyScalar((minMm - current) * perMm))
    const b = origin.clone().add(dir.clone().multiplyScalar((maxMm - current) * perMm))
    const geometry = new THREE.BufferGeometry().setFromPoints([a, b])
    const material = new THREE.LineBasicMaterial({ color: 0x3f8cff, transparent: true, opacity: 0.7 })
    this._line = new THREE.Line(geometry, material)
    this._line.renderOrder = 999
    this.manager.scene.add(this._line)
  }

  /**
   * 功能: 移除轴线辅助线.
   * @returns {void}
   */
  _hideLine() {
    if (!this._line) return
    this.manager.scene.remove(this._line)
    this._line.geometry.dispose()
    this._line.material.dispose()
    this._line = null
  }

  /**
   * 功能: 指针位置 -> NDC.
   * @param {PointerEvent} event 指针事件
   * @returns {void}
   */
  _updatePointer(event) {
    const rect = this.manager.canvas.getBoundingClientRect()
    this.pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
  }

  /**
   * 功能: 解绑并清理.
   * @returns {void}
   */
  dispose() {
    if (this._drag) this._end(true)
    const dom = this.manager.canvas
    dom.removeEventListener('pointerdown', this._onDown)
    dom.removeEventListener('pointermove', this._onMove)
    dom.removeEventListener('pointerup', this._onUp)
    dom.removeEventListener('pointercancel', this._onUp)
    window.removeEventListener('keydown', this._onKey)
    this._hideLine()
  }
}
