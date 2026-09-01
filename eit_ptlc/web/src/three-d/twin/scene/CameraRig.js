/**
 * 功能: 相机与轨道控制封装. 提供工位飞行运镜(fly-to)、整机取景与视角预设.
 *
 * 选用 camera-controls 而非 OrbitControls 的原因: 它自带阻尼过渡的 setLookAt/fitToBox,
 * "点击工位 -> 平滑飞过去"这类运镜是一行调用, 不需要自己写补间.
 */
import * as THREE from 'three'
import CameraControls from 'camera-controls'

import { computeBounds } from './loadModel.js'

// camera-controls 需要注入所用到的 three 子集(库作者为了 tree-shaking 这样设计)
CameraControls.install({
  THREE: {
    Vector2: THREE.Vector2,
    Vector3: THREE.Vector3,
    Vector4: THREE.Vector4,
    Quaternion: THREE.Quaternion,
    Matrix4: THREE.Matrix4,
    Spherical: THREE.Spherical,
    Box3: THREE.Box3,
    Sphere: THREE.Sphere,
    Raycaster: THREE.Raycaster,
  },
})

/** 标准视角预设(相对于整机包围盒的方向向量, 会按包围盒尺寸自动缩放) */
export const VIEW_PRESETS = {
  iso: [1.0, 0.72, 1.25],
  front: [0, 0.35, 1.9],
  back: [0, 0.35, -1.9],
  left: [-1.9, 0.35, 0],
  right: [1.9, 0.35, 0],
  top: [0.001, 2.1, 0.001],
}

export class CameraRig {
  /**
   * 功能: 创建相机与控制器.
   * @param {HTMLElement} domElement 事件宿主(通常是 canvas)
   * @param {object} [options] 可选项
   * @param {number} [options.fov=42] 垂直视场角
   */
  constructor(domElement, options = {}) {
    const { fov = 42 } = options

    this.camera = new THREE.PerspectiveCamera(fov, 1, 0.05, 400)
    this.camera.position.set(4, 3, 5)

    this.controls = new CameraControls(this.camera, domElement)
    // camera-controls v3 起 dampingFactor/draggingDampingFactor 是废弃 no-op
    // (赋值只打 console.warn): 阻尼手感由 smoothTime(程序过渡)与
    // draggingSmoothTime(用户拖拽/滚轮, 保持库默认 0.125)决定.
    this.controls.smoothTime = 0.42
    this.controls.minDistance = 0.35
    this.controls.maxDistance = 60
    // 不允许翻到地面以下, 避免出现"从地板下看设备"的穿帮视角
    this.controls.maxPolarAngle = Math.PI * 0.495
    this.controls.infinityDolly = false

    /** @type {THREE.Box3|null} 整机包围盒, 由 frameObject 计算并缓存 */
    this.modelBox = null
    /** @type {THREE.Vector3} 包围盒中心 */
    this.modelCenter = new THREE.Vector3()
    /** @type {number} 包围盒对角线长度, 作为运镜距离的基准尺度 */
    this.modelRadius = 1
    /** @type {number|null} 封闭背景罩允许的轨道距离上限(米); null 表示无罩体约束 */
    this.enclosureRadius = null
  }

  /**
   * 功能: 声明当前背景是一个封闭罩, 相机不得退出它.
   *       罩体半径由 LaboratoryBackground.laboratorySafeDistance 从剖面反推,
   *       这里只负责与整机尺度的上限合并取小 —— "出不去"因此是几何事实, 不靠调参.
   * @param {number|null} radius 允许的最大轨道距离(米); null 解除约束
   * @returns {void}
   */
  setEnclosure(radius) {
    this.enclosureRadius = Number.isFinite(radius) && radius > 0 ? radius : null
    this.applyDistanceLimits()
  }

  /**
   * 功能: 按整机尺度与罩体约束重设轨道距离上下限.
   * @returns {void}
   */
  applyDistanceLimits() {
    const modelLimit = this.modelRadius * 12
    this.controls.minDistance = this.modelRadius * 0.12
    this.controls.maxDistance = this.enclosureRadius === null
      ? modelLimit
      : Math.min(modelLimit, this.enclosureRadius)
  }

  /**
   * 功能: 按视口尺寸更新相机投影.
   * @param {number} width 视口宽(像素)
   * @param {number} height 视口高(像素)
   * @returns {void}
   */
  resize(width, height) {
    this.camera.aspect = width / Math.max(height, 1)
    this.camera.updateProjectionMatrix()
  }

  /**
   * 功能: 记录模型包围盒并把相机拉到能看全整机的位置; 同时按模型尺度重设远近裁剪面.
   * @param {THREE.Object3D} object 目标对象(通常是整机根节点)
   * @param {boolean} [transition=false] 是否使用过渡动画
   * @returns {{center: THREE.Vector3, size: THREE.Vector3, radius: number}} 包围盒信息
   */
  frameObject(object, transition = false) {
    const box = computeBounds(object)
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())

    this.modelBox = box
    this.modelCenter.copy(center)
    // 用外接球半径(对角线的一半)作为取景基准, 保证任意角度都装得下
    this.modelRadius = Math.max(size.length() * 0.5, 0.001)

    // 裁剪面按模型尺度自适应: 近裁剪太小会引发深度精度问题(z-fighting)
    this.camera.near = Math.max(this.modelRadius / 800, 0.01)
    this.camera.far = this.modelRadius * 40
    this.camera.updateProjectionMatrix()

    this.applyDistanceLimits()

    this.applyPreset('iso', transition)
    return { center, size, radius: this.modelRadius }
  }

  /**
   * 功能: 应用一个标准视角预设, 距离按视场角推算, 保证模型稳定地填满画面.
   *
   * 距离公式: 要让半径 R 的包围球恰好塞进垂直视场角 f, 需要 distance = R / sin(f/2).
   * 乘以 fill 系数(<1)让模型略微溢出画面, 视觉上更饱满 —— 直接用固定倍数乘半径
   * 会随视场角和模型比例失控, 这也是早期取景偏远的原因.
   *
   * @param {keyof typeof VIEW_PRESETS} name 预设名
   * @param {boolean} [transition=true] 是否平滑过渡
   * @param {number} [fill=0.82] 画面填充系数, 越小模型越大
   * @returns {Promise<void>|void} camera-controls 的过渡 Promise
   */
  applyPreset(name, transition = true, fill = 0.82) {
    const pos = new THREE.Vector3()
    const target = new THREE.Vector3()
    this.presetPose(name, fill, pos, target)
    return this.controls.setLookAt(pos.x, pos.y, pos.z, target.x, target.y, target.z, transition)
  }

  /**
   * 功能: 计算(不应用)一个预设的机位 —— 与 applyPreset 共享同一份方向+距离公式
   * (含竖屏 aspectPenalty), 开场动画(IntroReveal)用它保证"终点 = 常态机位"逐值一致.
   * @param {keyof typeof VIEW_PRESETS} name 预设名
   * @param {number} [fill=0.82] 画面填充系数
   * @param {THREE.Vector3} outPos 输出: 相机位置
   * @param {THREE.Vector3} outTarget 输出: 目标点
   * @returns {void}
   */
  presetPose(name, fill = 0.82, outPos, outTarget) {
    const preset = VIEW_PRESETS[name] || VIEW_PRESETS.iso
    const dir = new THREE.Vector3(preset[0], preset[1], preset[2]).normalize()

    const halfFov = THREE.MathUtils.degToRad(this.camera.fov) / 2
    // 画面较宽时垂直方向是约束; 较窄(竖屏)时要按宽高比补偿, 否则模型会被裁掉
    const aspectPenalty = this.camera.aspect < 1 ? 1 / Math.max(this.camera.aspect, 0.3) : 1
    const distance = (this.modelRadius / Math.sin(halfFov)) * fill * aspectPenalty

    outTarget.copy(this.modelCenter)
    outPos.copy(this.modelCenter).addScaledVector(dir, distance)
  }

  /**
   * 功能: 飞到指定的相机预设(来自 device-manifest 的工位机位).
   * @param {{pos: number[], target: number[]}} preset 机位定义(世界坐标)
   * @param {boolean} [transition=true] 是否平滑过渡
   * @returns {Promise<void>|void}
   */
  flyTo(preset, transition = true) {
    if (!preset?.pos || !preset?.target) return
    const [px, py, pz] = preset.pos
    const [tx, ty, tz] = preset.target
    return this.controls.setLookAt(px, py, pz, tx, ty, tz, transition)
  }

  /**
   * 功能: 把镜头对准某个具体对象(用于点击工位后聚焦), 自动留出边距.
   * @param {THREE.Object3D} object 目标对象
   * @param {boolean} [transition=true] 是否平滑过渡
   * @returns {Promise<void>|void}
   */
  fitTo(object, transition = true) {
    return this.fitToObjects([object], transition)
  }

  /**
   * 功能: 把镜头对准一组对象的合并包围盒(联动机构由多个节点组成, 单个节点框不住它).
   *
   * 与 fitTo 同一条实现 —— fitTo 是它的单参包装, 免得出现两套取景口径。
   * @param {THREE.Object3D[]} objects 目标对象数组(空数组或全空盒直接不动相机)
   * @param {boolean} [transition=true] 是否平滑过渡
   * @returns {Promise<void>|void}
   */
  fitToObjects(objects, transition = true) {
    const box = new THREE.Box3()
    for (const object of objects || []) {
      if (!object) continue
      box.union(new THREE.Box3().setFromObject(object))
    }
    if (box.isEmpty()) return
    const padding = this.modelRadius * 0.06
    return this.controls.fitToBox(box, transition, {
      paddingTop: padding,
      paddingBottom: padding,
      paddingLeft: padding,
      paddingRight: padding,
    })
  }

  /**
   * 功能: 读出当前机位(与 manifest 的 stations[].camera 及 flyTo() 入参逐字同构).
   *
   * 三位小数是照 manifest 生成器的口径 —— 保存后的 diff 才不会因为浮点尾数抖动。
   * @returns {{pos: number[], target: number[]}} 机位与目标点(世界坐标, 米)
   */
  getState() {
    const round = (v) => Math.round(v * 1000) / 1000
    const pos = new THREE.Vector3()
    const target = new THREE.Vector3()
    this.controls.getPosition(pos)
    this.controls.getTarget(target)
    return { pos: pos.toArray().map(round), target: target.toArray().map(round) }
  }

  /**
   * 功能: 每帧推进控制器阻尼.
   * @param {number} delta 帧间隔(秒)
   * @returns {boolean} 本帧相机是否发生了变化(可用于按需渲染)
   */
  update(delta) {
    return this.controls.update(delta)
  }

  /**
   * 功能: 释放控制器绑定的事件监听.
   * @returns {void}
   */
  dispose() {
    this.controls.dispose()
  }
}
