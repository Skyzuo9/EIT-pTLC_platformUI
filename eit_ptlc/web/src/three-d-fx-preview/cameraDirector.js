/**
 * 功能: 运镜执行器 —— 包装 camera-controls, 提供视角预设/工位定制视角/整机取景.
 * focus/tour/intro 共用这一个出口, 补间全部由 camera-controls 的 smoothTime 承担
 * (与正式页 CameraRig 同手感, 不引 tween 库).
 *
 * 预设方向与距离公式照抄 CameraRig(方向向量 x R/sin(fov/2) x fill), 但不 import
 * 它 —— 保持沙盒与 twin/scene 零耦合.
 *
 * 第四轮(用户定夺"聚焦不能随机视角"): 聚焦/巡检主口换 **applyStationView** ——
 * 每工位从 config.stationViews 读定制机位(azDeg/elDeg/fill/radiusM), 保证
 * "完整看到模块 + 看到正面"; 视角表缺项时回退 fitStation(保持方位角框住工位).
 * 旧 flyToStation("中心向外"启发式)已退役 —— 对近中心的 VISION 与盒面极宽的
 * ROBOT 都不成立, 正是用户嫌"随机"的另一半病根.
 *
 * 球坐标约定(与 THREE.Spherical/camera-controls 同向): azDeg 0 = +Z(整机正面),
 * 正角向 +X(右端)转; elDeg 为仰角. dir = (sin az·cos el, sin el, cos az·cos el).
 */
import * as THREE from 'three'

/** 标准视角预设(方向向量, 照 CameraRig.VIEW_PRESETS) */
export const VIEW_PRESETS = {
  iso: [1.0, 0.72, 1.25],
  front: [0, 0.35, 1.9],
  back: [0, 0.35, -1.9],
  left: [-1.9, 0.35, 0],
  right: [1.9, 0.35, 0],
  top: [0.001, 2.1, 0.001],
}

const DEG = Math.PI / 180
const UP = new THREE.Vector3(0, 1, 0)

const _dir = new THREE.Vector3()
const _pos = new THREE.Vector3()
const _target = new THREE.Vector3()
const _box = new THREE.Box3()
const _anchorTmp = new THREE.Vector3()
const _right = new THREE.Vector3()
const _upv = new THREE.Vector3()
const _corner = new THREE.Vector3()

/**
 * 功能: 创建运镜执行器.
 * @param {object} options 参数对象
 * @param {import('camera-controls').default} options.controls 相机控件
 * @param {THREE.PerspectiveCamera} options.camera 相机
 * @param {THREE.Box3} options.machineBounds 整机世界包围盒
 * @param {Map<string, object>} options.stations 工位表
 * @param {object} options.config 运行配置(读 stationViews)
 * @returns {object} director 实例
 */
export function createCameraDirector({ controls, camera, machineBounds, stations, config }) {
  const machineCenter = machineBounds.getCenter(new THREE.Vector3())
  const machineRadius = Math.max(machineBounds.getSize(new THREE.Vector3()).length() / 2, 0.001)

  // 裁剪面与推拉范围按整机尺度设定(照 CameraRig.frameObject 口径)
  camera.near = Math.max(machineRadius / 800, 0.01)
  camera.far = machineRadius * 40
  camera.updateProjectionMatrix()
  controls.minDistance = machineRadius * 0.12
  controls.maxDistance = machineRadius * 12

  /** 距离公式: 半径 R 的包围球塞进视场角, 取横竖视场角里更紧的那个 */
  function fitDistance(radius, fill = 0.82) {
    const fovV = (camera.fov * Math.PI) / 180
    const fovH = 2 * Math.atan(Math.tan(fovV / 2) * Math.max(camera.aspect, 0.1))
    return (radius / Math.sin(Math.min(fovV, fovH) / 2)) * fill
  }

  /**
   * 工位精确取景距离: 沿给定视线方向逐角点解"整盒入框"的最小距离 —— 数学上保证
   * "完整看到整个模块"(用户硬要求); 球拟合对扁长盒会大幅出画, 已弃用.
   * radiusM>0 时退回球公式(机械臂只框臂体的定半径口径).
   * @param {object} station 工位
   * @param {object} view 视角配置(读 radiusM)
   * @param {THREE.Vector3} dir 视线方向(目标->相机, 单位向量)
   * @param {THREE.Vector3} target 目标点
   * @returns {number} 贴边距离(米; 不含余量, 余量由 view.fill 乘)
   */
  function exactFitDistance(station, view, dir, target) {
    const fovV = (camera.fov * Math.PI) / 180
    const tanV = Math.tan(fovV / 2)
    const tanH = tanV * Math.max(camera.aspect, 0.1)
    if (view?.radiusM > 0) {
      const fovH = 2 * Math.atan(tanH)
      return view.radiusM / Math.sin(Math.min(fovV, fovH) / 2)
    }
    station.getWorldBounds(_box)
    // 相机基(dir 指向 目标->相机; 视角表俯仰 <=30°, 不会与竖直轴退化)
    _right.crossVectors(UP, dir)
    if (_right.lengthSq() < 1e-6) _right.set(1, 0, 0)
    _right.normalize()
    _upv.crossVectors(dir, _right).normalize()
    let dist = 0.1
    for (const cx of [_box.min.x, _box.max.x]) {
      for (const cy of [_box.min.y, _box.max.y]) {
        for (const cz of [_box.min.z, _box.max.z]) {
          _corner.set(cx, cy, cz).sub(target)
          const a = _corner.dot(dir) // 沿视线朝相机的深度(角点越靠相机, 需要的距离越大)
          const r = Math.abs(_corner.dot(_right))
          const u = Math.abs(_corner.dot(_upv))
          dist = Math.max(dist, a + r / tanH, a + u / tanV)
        }
      }
    }
    return dist
  }

  return {
    machineCenter,
    machineRadius,

    /**
     * 功能: 计算(不应用)一个标准预设的机位 —— 开场扫场的相机起/终点用.
     * @param {keyof typeof VIEW_PRESETS} name 预设名
     * @param {number} [fill=0.82] 画面填充系数
     * @param {number} [distScale=1] 距离额外倍率
     * @param {THREE.Vector3} outPos 输出: 相机位置
     * @param {THREE.Vector3} outTarget 输出: 目标点
     * @returns {void}
     */
    presetPose(name, fill = 0.82, distScale = 1, outPos, outTarget) {
      const preset = VIEW_PRESETS[name] || VIEW_PRESETS.iso
      _dir.set(preset[0], preset[1], preset[2]).normalize()
      const dist = fitDistance(machineRadius, fill) * distScale
      outTarget.copy(machineCenter)
      outPos.copy(machineCenter).addScaledVector(_dir, dist)
    },

    /**
     * 功能: 应用标准视角预设.
     * @param {keyof typeof VIEW_PRESETS} name 预设名
     * @param {boolean} [transition=true] 平滑过渡
     * @param {number} [fill=0.82] 画面填充系数(越小模型越大)
     * @param {number} [distScale=1] 距离额外倍率(远景用)
     * @returns {Promise<void>|void}
     */
    applyPreset(name, transition = true, fill = 0.82, distScale = 1) {
      const preset = VIEW_PRESETS[name] || VIEW_PRESETS.iso
      _dir.set(preset[0], preset[1], preset[2]).normalize()
      const dist = fitDistance(machineRadius, fill) * distScale
      _pos.copy(machineCenter).addScaledVector(_dir, dist)
      return controls.setLookAt(_pos.x, _pos.y, _pos.z, machineCenter.x, machineCenter.y, machineCenter.z, transition)
    },

    /**
     * 功能: 聚焦/巡检主口 —— 该工位的定制机位(config.stationViews[id]).
     * 目标点 = 工位包围盒中心(动态工位 xz 跟锚点/机械臂); 距离 = fitDistance(取景
     * 半径, fill), 半径默认盒外接球(保证完整入画), radiusM 可覆写(ROBOT 只框臂体).
     * @param {string} id 工位 id
     * @param {{instant?: boolean}} [options] instant=true 无过渡(截图定格用)
     * @returns {Promise<void>|void}
     */
    applyStationView(id, options = {}) {
      const view = config.stationViews?.[id]
      if (!view) return this.fitStation(id, !options.instant) // 视角表缺项(将来新工位)兜底
      const station = stations.get(id)
      if (!station) return undefined

      station.getWorldBounds(_box)
      _box.getCenter(_target)
      if (station.isDynamic && station.getAnchor) {
        station.getAnchor(_anchorTmp, 0) // 机械臂·地轨: 对准臂当前位置而不是整条轨的中点
        _target.x = _anchorTmp.x
        _target.z = _anchorTmp.z
      }
      const az = view.azDeg * DEG
      const el = view.elDeg * DEG
      _dir.set(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el))
      const dist = Math.min(Math.max(
        exactFitDistance(station, view, _dir, _target) * view.fill,
        controls.minDistance,
      ), controls.maxDistance)
      _pos.copy(_target).addScaledVector(_dir, dist)
      return controls.setLookAt(_pos.x, _pos.y, _pos.z, _target.x, _target.y, _target.z, !options.instant)
    },

    /**
     * 功能: 把**当前**相机机位反解成该工位的视角三元组(面板"复制机位"按钮用).
     * 已知局限: 用户平移(truck)过的目标点偏移不进三元组, 首版接受.
     * @param {string} id 工位 id
     * @returns {{azDeg: number, elDeg: number, fill: number}|null}
     */
    captureStationView(id) {
      const station = stations.get(id)
      if (!station) return null
      let azDeg = (controls.azimuthAngle / DEG) % 360 // azimuthAngle 会累积多圈, 归一到 ±180
      if (azDeg > 180) azDeg -= 360
      if (azDeg < -180) azDeg += 360
      const elDeg = 90 - controls.polarAngle / DEG
      // fill 反解 = 当前距离 / 当前方向的贴边距离(与 applyStationView 同口径往返)
      station.getWorldBounds(_box)
      _box.getCenter(_target)
      if (station.isDynamic && station.getAnchor) {
        station.getAnchor(_anchorTmp, 0)
        _target.x = _anchorTmp.x
        _target.z = _anchorTmp.z
      }
      _dir.set(
        Math.sin(azDeg * DEG) * Math.cos(elDeg * DEG),
        Math.sin(elDeg * DEG),
        Math.cos(azDeg * DEG) * Math.cos(elDeg * DEG),
      )
      const fit = exactFitDistance(station, config.stationViews?.[id], _dir, _target)
      const fill = controls.distance / Math.max(fit, 0.01)
      return {
        azDeg: Math.round(azDeg * 10) / 10,
        elDeg: Math.round(elDeg * 10) / 10,
        fill: Math.round(fill * 100) / 100,
      }
    },

    /**
     * 功能: 保持方位角框住某工位(applyStationView 的兜底; ?cam=station: 的旧语义).
     * @param {string} id 工位 id
     * @param {boolean} [transition=true] 平滑过渡
     * @returns {Promise<void>|void}
     */
    fitStation(id, transition = true) {
      const station = stations.get(id)
      if (!station) return undefined
      station.getWorldBounds(_box)
      const padding = machineRadius * 0.06
      return controls.fitToBox(_box, transition, {
        paddingTop: padding, paddingBottom: padding, paddingLeft: padding, paddingRight: padding,
      })
    },
  }
}
