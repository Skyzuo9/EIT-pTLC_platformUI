/**
 * 功能: /3d/live 开场动画 —— "幽灵整机自上而下逐像素实体化 + 相机环绕 + 科技蓝扫描平面".
 *
 * 移植自效果预览沙盒 three-d-fx-preview/fx/intro.js(v3 定案形态), 阶段B收窄版只搬本效果:
 *   1. 双层裁剪(逐像素, 非逐零件): **实体层** = 真网格保持原材质, 每个原材质临时挂
 *      solidPlane(只保留分解线以上); **幽灵层** = 私有幽灵材质的克隆网格, 挂反向
 *      ghostPlane(只保留线以下). 分解线下移时零件被逐像素切换成实体, 真网格的
 *      material 全程不动 —— 与绑定层(灯/液面/外壳的材质克隆)天然不冲突.
 *   2. 相机绕机心环绕推近(方位角自 azFromDeg 偏转处转回 iso 常态机位), 与分解线
 *      同一进度 —— 转到位 = 实体化完成; 终点经 CameraRig.presetPose 计算, 与页面
 *      常态机位数值一致(含竖屏 aspectPenalty).
 *   3. 科技蓝加色平面骑在分解线上跟随下扫(颜色 = Effects.OUTLINE_COLORS 主题强调色),
 *      扫完 0.3s 淡出; high/medium 档经 SelectiveBloom 出光晕(逐帧幂等 add, 防塔灯
 *      接管时 selection.set 把它顶掉), low 档直渲照常可见.
 *
 * 正式页特有的四处修正(沙盒没有的坑):
 *   - 快照跳过 PLATE_* 板层自建网格(在制物料非设备)与 visible=false 的节点(空缸液面盒);
 *   - 幽灵克隆逐帧同步 matrixWorld(实时绑定驱动机构在动, 冻结矩阵会与真件分离);
 *   - 双击选工位的 PickController 绕过 controls.enabled —— SceneManager.flyToStation
 *     入口有 interlock(开场中先 abort);
 *   - 点击画面/Esc 立即跳过(平滑落到 iso 终点).
 *
 * 收尾/中止必须清干净: 原材质 clippingPlanes/clipShadows 还原、克隆层与扫描平面
 * 移除释放、controls.enabled 回填 —— cleanup 是唯一出口, abort/正常收尾共用.
 */
import * as THREE from 'three'

import { getTheme } from '../../theme.js'
import { OUTLINE_COLORS } from './Effects.js'

/** 开场参数(与沙盒 fxConfig.intro 定案值一致, 唯 durS 按需求放慢一倍; 时长单位秒, 角度单位度) */
const INTRO = {
  durS: 5.6, // 分解线顶到底 = 相机环绕到位 的共同时长(沙盒定案 2.8, 正式页放慢至 1/2 速度)
  tailS: 0.4, // 扫完(平面淡出)后再静置多少秒收尾(还原输入)
  azFromDeg: -130, // 相机起始方位角偏移(相对终点 iso 机位; 环绕途中掠过正面)
  elFromDeg: 34, // 相机起始仰角(俯瞰进场, 落回 iso 仰角≈24°)
  camStartScale: 1.35, // 起始距离 = iso 机位距离 x 该系数
  planeScale: 1.14, // 扫描平面相对整机脚印的放大倍率
  planeOpacity: 0.42, // 扫描平面不透明度(加色混合)
}

const DEG = Math.PI / 180
const _pos = new THREE.Vector3()
const _offset = new THREE.Vector3()

/** smoothstep(0..1): 分解线用(起步缓、中段匀、右端收) */
function smoothstep(u) {
  const t = Math.min(Math.max(u, 0), 1)
  return t * t * (3 - 2 * t)
}

/** easeInOutSine(0..1): 环绕用(起停柔) */
function easeInOutSine(u) {
  const t = Math.min(Math.max(u, 0), 1)
  return -(Math.cos(Math.PI * t) - 1) / 2
}

/**
 * 功能: 科技感扫描平面贴图(白色图案, 颜色由材质 color 乘出) —— 中心亮带 + 细网格.
 * 无随机噪声(逐帧确定).
 * @returns {THREE.CanvasTexture}
 */
function makeScanTexture() {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const g = canvas.getContext('2d')
  const radial = g.createRadialGradient(size / 2, size / 2, size * 0.05, size / 2, size / 2, size * 0.62)
  radial.addColorStop(0, 'rgba(255,255,255,0.9)')
  radial.addColorStop(0.55, 'rgba(255,255,255,0.34)')
  radial.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = radial
  g.fillRect(0, 0, size, size)
  g.strokeStyle = 'rgba(255,255,255,0.16)'
  g.lineWidth = 1
  for (let i = 0; i <= size; i += 16) {
    g.beginPath()
    g.moveTo(i + 0.5, 0)
    g.lineTo(i + 0.5, size)
    g.stroke()
    g.beginPath()
    g.moveTo(0, i + 0.5)
    g.lineTo(size, i + 0.5)
    g.stroke()
  }
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

/**
 * 功能: 创建开场动画控制器(挂在 SceneManager.intro 上).
 * @param {import('./SceneManager.js').SceneManager} manager 场景管理器
 * @returns {{play: Function, abort: Function, isRunning: Function, dispose: Function}}
 */
export function createIntroReveal(manager) {
  let active = false
  let clock = 0
  let tail = 0
  let unhook = null
  let prevControlsEnabled = true
  /** @type {Set<THREE.Material>|null} 挂了 solidPlane 的原材质集合(收尾还原) */
  let clippedMaterials = null
  /** @type {THREE.MeshStandardMaterial|null} 本模块私有幽灵材质(每次 play 重建, 跟主题) */
  let ghostMaterial = null
  /** @type {THREE.Group|null} 幽灵克隆层 */
  let ghostGroup = null
  /** @type {Array<{clone: THREE.Mesh, src: THREE.Mesh}>} 克隆-真件对(逐帧同步矩阵) */
  let ghostPairs = []
  /** @type {THREE.Mesh|null} 蓝色扫描平面 */
  let scanPlane = null
  /** 实体层裁剪面: 法向 +Y, 保留 y >= lineY(constant = -lineY) */
  const solidPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  /** 幽灵层裁剪面: 法向 -Y, 保留 y <= lineY(constant = +lineY) */
  const ghostPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0)
  /** 分解线 Y 行程 */
  const sweep = { top: 1, bottom: 0 }
  /** 相机球坐标行程(终点 = iso 常态机位) */
  const cam = {
    target: new THREE.Vector3(),
    endPos: new THREE.Vector3(),
    azStart: 0, azEnd: 0, elStart: 0, elEnd: 0, distStart: 1, distEnd: 1,
  }

  /** 按进度 v(0..1) 写相机位姿(球坐标插值绕机心; 逐帧 setLookAt 不用 smoothTime) */
  function poseCamera(v) {
    const az = cam.azStart + (cam.azEnd - cam.azStart) * v
    const el = cam.elStart + (cam.elEnd - cam.elStart) * v
    const dist = cam.distStart + (cam.distEnd - cam.distStart) * v
    _pos.set(
      Math.sin(az) * Math.cos(el),
      Math.sin(el),
      Math.cos(az) * Math.cos(el),
    ).multiplyScalar(dist).add(cam.target)
    manager.cameraRig.controls.setLookAt(_pos.x, _pos.y, _pos.z, cam.target.x, cam.target.y, cam.target.z, false)
  }

  function onSkipPointer() {
    api.abort({ snapCamera: true })
  }
  function onSkipKey(event) {
    if (event.key === 'Escape') api.abort({ snapCamera: true })
  }

  /** 全量清场(abort 与正常收尾共用的唯一出口) */
  function cleanup() {
    if (clippedMaterials) {
      for (const material of clippedMaterials) {
        material.clippingPlanes = null
        material.clipShadows = false
        material.needsUpdate = true
      }
      clippedMaterials = null
    }
    if (ghostGroup) {
      manager.scene?.remove(ghostGroup) // 克隆共享真件几何, 不 dispose
      ghostGroup = null
      ghostPairs = []
    }
    ghostMaterial?.dispose()
    ghostMaterial = null
    if (scanPlane) {
      manager.effects?.bloomEffect?.selection?.delete?.(scanPlane)
      manager.scene?.remove(scanPlane)
      scanPlane.geometry.dispose()
      scanPlane.material.map?.dispose()
      scanPlane.material.dispose()
      scanPlane = null
    }
    unhook?.()
    unhook = null
    manager.canvas?.removeEventListener('pointerdown', onSkipPointer)
    window.removeEventListener('keydown', onSkipKey)
    if (manager.cameraRig) manager.cameraRig.controls.enabled = prevControlsEnabled
    active = false
    manager.invalidateShadows?.()
  }

  function update(dt) {
    if (!active) return
    // 钳位帧间隔: SceneManager 的 clock.getDelta 不设上限, 模型解析/绑定装配会把
    // 主线程堵秒级 —— 首帧巨型 dt 会瞬间烧穿 6.0s 时间轴(实测开场"一闪而过")
    clock += Math.min(dt, 0.1)

    // 同一进度: 分解线到底 == 相机转到位. 线用 smoothstep, 环绕用 easeInOutSine
    const raw = Math.min(clock / INTRO.durS, 1)
    const u = smoothstep(raw)
    const lineY = sweep.top + (sweep.bottom - sweep.top) * u
    solidPlane.constant = -lineY
    ghostPlane.constant = lineY

    // 幽灵克隆逐帧贴住真件(实时绑定在驱动机构, 冻结矩阵会分离)
    for (const pair of ghostPairs) pair.clone.matrix.copy(pair.src.matrixWorld)

    if (scanPlane) {
      scanPlane.position.y = lineY
      // 扫描中带确定性脉动; 到底后 0.3s 内淡出
      scanPlane.material.opacity = raw >= 1
        ? INTRO.planeOpacity * Math.max(0, 1 - (clock - INTRO.durS) / 0.3)
        : INTRO.planeOpacity * (0.82 + 0.18 * Math.sin(clock * 7))
      // 逐帧幂等入辉光集合: 塔灯接管会 selection.set 整体替换, 这里每帧补回(Set 语义零开销)
      manager.effects?.addBloomTarget?.(scanPlane)
    }

    poseCamera(easeInOutSine(raw))
    manager.invalidateShadows?.()

    if (raw >= 1) {
      tail += Math.min(dt, 0.1)
      if (tail >= INTRO.tailS) cleanup() // 正常收尾(相机已在 iso 终点)
    }
  }

  const api = {
    isRunning: () => active,

    /** 功能: 播一次开场(可重播; 重播先全量清场). 模型未就绪时静默不播. */
    play() {
      if (active) api.abort()
      const rig = manager.cameraRig
      const root = manager.machineRoot
      if (!root || !rig?.modelBox) return

      clock = 0
      tail = 0
      root.updateWorldMatrix(true, true)
      const box = rig.modelBox
      sweep.top = box.max.y + 0.04
      sweep.bottom = box.min.y - 0.02
      solidPlane.constant = -sweep.top // 起始: 实体层空、幽灵层全
      ghostPlane.constant = sweep.top

      // 网格快照(绑定层材质克隆已完成后才调用本方法 —— useTwinScene 的接线保证):
      // 跳过板层自建网格(PLATE_* 前缀, 在制物料非设备)与不可见节点(空缸液面盒等)
      const meshes = []
      root.traverse((node) => {
        if (!node.isMesh || !node.visible) return
        if (node.name && node.name.startsWith('PLATE_')) return
        meshes.push(node)
      })
      if (!meshes.length) return

      // 实体层: 原材质临时挂 solidPlane(共享 Plane 实例, 之后只动 constant 零开销)
      clippedMaterials = new Set()
      for (const mesh of meshes) {
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        for (const material of materials) {
          if (!material || clippedMaterials.has(material)) continue
          clippedMaterials.add(material)
          material.clippingPlanes = [solidPlane]
          material.clipShadows = true // 影子也随分解线生长
          material.needsUpdate = true
        }
      }

      // 幽灵层: 共享几何的克隆(不进拾取/绑定, 只存在于开场期间), 反向裁剪
      const theme = getTheme()
      ghostMaterial = new THREE.MeshStandardMaterial({
        color: theme === 'light' ? 0x9aa8b8 : 0x6b7a8c,
        roughness: 0.9,
        metalness: 0,
        transparent: true,
        opacity: 0.1,
        depthWrite: false, // 半透明互相遮挡会出脏层叠
        clippingPlanes: [ghostPlane],
      })
      ghostGroup = new THREE.Group()
      ghostGroup.name = 'TWIN_INTRO_GHOST'
      ghostPairs = []
      for (const mesh of meshes) {
        const clone = new THREE.Mesh(mesh.geometry, ghostMaterial)
        clone.matrixAutoUpdate = false
        clone.matrix.copy(mesh.matrixWorld)
        clone.castShadow = false
        clone.receiveShadow = false
        ghostGroup.add(clone)
        ghostPairs.push({ clone, src: mesh })
      }
      manager.scene.add(ghostGroup)

      // 科技蓝扫描平面: 骑在分解线上, 加色混合; 颜色 = 主题强调色(与描边同源)
      const sizeX = (box.max.x - box.min.x) * INTRO.planeScale
      const sizeZ = (box.max.z - box.min.z) * INTRO.planeScale
      const planeMaterial = new THREE.MeshBasicMaterial({
        color: OUTLINE_COLORS[theme]?.selected ?? 0x36d1ff,
        map: makeScanTexture(),
        transparent: true,
        opacity: INTRO.planeOpacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.DoubleSide,
      })
      scanPlane = new THREE.Mesh(new THREE.PlaneGeometry(sizeX, sizeZ), planeMaterial)
      scanPlane.rotation.x = -Math.PI / 2
      scanPlane.position.set((box.min.x + box.max.x) / 2, sweep.top, (box.min.z + box.max.z) / 2)
      scanPlane.renderOrder = 20
      manager.scene.add(scanPlane)

      // 相机行程: 终点 = iso 常态机位(presetPose 与 applyPreset 共享公式, 含 aspectPenalty)
      rig.presetPose('iso', 0.82, cam.endPos, cam.target)
      _offset.copy(cam.endPos).sub(cam.target)
      cam.distEnd = _offset.length()
      cam.elEnd = Math.asin(_offset.y / cam.distEnd)
      cam.azEnd = Math.atan2(_offset.x, _offset.z)
      cam.azStart = cam.azEnd + INTRO.azFromDeg * DEG
      cam.elStart = INTRO.elFromDeg * DEG
      cam.distStart = cam.distEnd * INTRO.camStartScale
      poseCamera(0)
      rig.controls.update(0)
      prevControlsEnabled = rig.controls.enabled
      rig.controls.enabled = false // 锁相机输入; 双击飞入由 flyToStation 的 interlock 兜底

      // 点击画面/Esc 立即跳过
      manager.canvas.addEventListener('pointerdown', onSkipPointer)
      window.addEventListener('keydown', onSkipKey)

      active = true
      unhook = manager.addFrameHook((dt) => update(dt))
      manager.invalidateShadows?.()
    },

    /**
     * 功能: 中止开场 —— 全量清场, 世界即刻回到实体.
     * @param {{snapCamera?: boolean}} [options] snapCamera=true 时相机平滑落到 iso 终点
     *   (点击/Esc 跳过用); flyToStation interlock 不传 —— 飞入紧接着接管相机.
     * @returns {void}
     */
    abort(options = {}) {
      if (!active) return
      cleanup()
      if (options.snapCamera) {
        manager.cameraRig.controls.setLookAt(
          cam.endPos.x, cam.endPos.y, cam.endPos.z,
          cam.target.x, cam.target.y, cam.target.z,
          true,
        )
      }
    },

    /** 功能: 释放(等价 abort; 挂在 detachBindings/dispose 链上). */
    dispose() {
      api.abort()
    },
  }
  return api
}
