/**
 * 功能: 开场动画 v3(第五轮) —— "幽灵整机**自上而下**渐进实体化 + 相机环绕 + 科技蓝扫描平面":
 *   1. 双层裁剪(逐像素, 非逐零件 —— 用户否掉了 v2 的"按零件硬切"):
 *      **实体层** = 真网格保持原材质, 每个原材质挂 solidPlane(只保留分解线**以上**);
 *      **幽灵层** = 共享幽灵材质的克隆网格, 挂 ghostPlane(只保留分解线**以下**).
 *      分解线下移时, 每个零件被逐像素"切换"成实体 —— 真网格的 material 全程不动
 *      (比 v2 的换材质台账更干净, 与聚焦隔离天然不冲突).
 *   2. 相机绕机心环绕推近(方位角自 azFromDeg 偏转处转回 **iso 机位** —— 与页面
 *      默认常态机位一致, 开场结束画面即常态画面), **转到位 = 实体化完成**
 *      (同一进度参数驱动, 用户原话"等到全部旋转到位也就全部实体化了").
 *   3. 科技蓝半透明加色平面骑在分解线上跟随下扫(遮住裁剪硬边+辉光), 扫完淡出.
 *
 * 逐帧 setLookAt(false) 不用 smoothTime 过渡 —— freezeAt 快进走 update(dt),
 * 只有逐帧写位姿才能精确定格中段机位(截图矩阵 intro_mid 依赖).
 * 总时长 = durS + tailS, 默认 2.8+0.4 = 3.2s —— 与 main.freezeAt 的快进窗口(3.2s)
 * 绑定; 改长必须同步 main.js 的窗口常量.
 *
 * 互斥: 本版不再改 mesh.material, 但仍保留 v2 的输入门控(emit 'intro')与
 * isolation interlock(聚焦入口先 abort) —— 幽灵克隆层/裁剪面在场时聚焦观感是错的.
 * 收尾/中止必须清干净: 原材质与共享幽灵材质的 clippingPlanes 置回 null(幽灵材质
 * 与 isolation 共享, 残留裁剪面会把之后的聚焦幽灵切掉半截).
 */
import * as THREE from 'three'

import { ghostMaterial } from './ghostMaterial.js'

const DEG = Math.PI / 180
const _pos = new THREE.Vector3()
const _offset = new THREE.Vector3()

/** smoothstep(0..1) */
function smoothstep(u) {
  const t = Math.min(Math.max(u, 0), 1)
  return t * t * (3 - 2 * t)
}

/** easeInOutSine(0..1) —— 环绕用(起停柔) */
function easeInOutSine(u) {
  const t = Math.min(Math.max(u, 0), 1)
  return -(Math.cos(Math.PI * t) - 1) / 2
}

/**
 * 功能: 科技感扫描平面贴图(白色图案, 颜色由材质 color 乘出) —— 中心亮带 + 细网格.
 * 无随机噪声(freezeAt 定格要求逐帧确定).
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
 * 功能: 创建开场动画.
 * @param {object} ctx 沙盒上下文
 * @param {object} deps { director }
 * @returns {object} 特效实例(另暴露 play/abort/isRunning/duration)
 */
export function createIntro(ctx, deps) {
  const { director } = deps

  let active = false
  let clock = 0
  let tail = 0
  let prevControlsEnabled = true
  /** @type {Set<object>|null} 挂了 solidPlane 的原材质集合(收尾还原用) */
  let clippedMaterials = null
  /** @type {THREE.Group|null} 幽灵克隆层 */
  let ghostGroup = null
  /** @type {THREE.Mesh|null} 蓝色扫描平面 */
  let scanPlane = null
  /** 实体层裁剪面: 法向 +Y, 保留 y >= lineY(constant = -lineY) */
  const solidPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
  /** 幽灵层裁剪面: 法向 -Y, 保留 y <= lineY(constant = +lineY) */
  const ghostPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0)
  /** 分解线 Y 行程(play 时按整机盒算定) */
  const sweep = { top: 1, bottom: 0 }
  /** 相机球坐标行程(绕机心; 终点 = 标准 front 机位) */
  const cam = {
    center: new THREE.Vector3(),
    target: new THREE.Vector3(),
    endPos: new THREE.Vector3(),
    azStart: 0, azEnd: 0, elStart: 0, elEnd: 0, distStart: 1, distEnd: 1,
  }

  /** 按进度 v(0..1) 写相机位姿(球坐标插值, 绕机心环绕推近) */
  function poseCamera(v) {
    const az = cam.azStart + (cam.azEnd - cam.azStart) * v
    const el = cam.elStart + (cam.elEnd - cam.elStart) * v
    const dist = cam.distStart + (cam.distEnd - cam.distStart) * v
    _pos.set(
      Math.sin(az) * Math.cos(el),
      Math.sin(el),
      Math.cos(az) * Math.cos(el),
    ).multiplyScalar(dist).add(cam.center)
    ctx.controls.setLookAt(_pos.x, _pos.y, _pos.z, cam.target.x, cam.target.y, cam.target.z, false)
  }

  /** 全量清场: 裁剪面/克隆层/扫描平面/输入(finish 与 abort 共用) */
  function cleanup() {
    if (clippedMaterials) {
      for (const material of clippedMaterials) {
        material.clippingPlanes = null
        material.clipShadows = false
        material.needsUpdate = true
      }
      clippedMaterials = null
    }
    const ghost = ghostMaterial(ctx)
    if (ghost.clippingPlanes) {
      ghost.clippingPlanes = null // 与 isolation 共享! 残留裁剪面会切掉聚焦幽灵
      ghost.needsUpdate = true
    }
    if (ghostGroup) {
      ctx.scene.remove(ghostGroup) // 克隆共享几何与共享幽灵材质, 无可 dispose 之物
      ghostGroup = null
    }
    if (scanPlane) {
      ctx.scene.remove(scanPlane)
      scanPlane.geometry.dispose()
      scanPlane.material.map?.dispose()
      scanPlane.material.dispose()
      scanPlane = null
    }
    active = false
    ctx.invalidateShadows()
    ctx.dom.cardHost.classList.remove('fx-pre-intro')
    ctx.controls.enabled = prevControlsEnabled
    ctx.events.emit('intro', false)
  }

  const self = {
    name: 'intro',
    isRunning: () => active,
    /** 功能: 名义总时长(秒) —— freezeAt 窗口对齐用. */
    duration() {
      const cfg = ctx.config.intro
      return cfg.durS + cfg.tailS
    },

    /** 功能: 播一次开场(可重播; 重播先全量清场). */
    play() {
      if (active) this.abort()
      const cfg = ctx.config.intro
      clock = 0
      tail = 0
      active = true

      ctx.machineRoot.updateWorldMatrix(true, true) // URL 自动播发生在首帧渲染之前

      // 分解线行程: 整机顶到底(两端各垫一点, 保证首尾像素确实越线)
      sweep.top = ctx.machineBounds.max.y + 0.04
      sweep.bottom = ctx.machineBounds.min.y - 0.02
      solidPlane.constant = -sweep.top // 起始: 实体层空
      ghostPlane.constant = sweep.top //        幽灵层全

      // 实体层: 每个原材质挂 solidPlane(共享 Plane 实例, 之后只动 constant 零开销)
      clippedMaterials = new Set()
      const ghost = ghostMaterial(ctx)
      for (const mesh of ctx.occluder.meshes) {
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        for (const material of materials) {
          if (!material || material === ghost || clippedMaterials.has(material)) continue
          clippedMaterials.add(material)
          material.clippingPlanes = [solidPlane]
          material.clipShadows = true // 影子也随分解线生长
          material.needsUpdate = true
        }
      }

      // 幽灵层: 共享几何的克隆(不进 occluder/BVH, 射线拾取不受扰), 反向裁剪
      ghost.clippingPlanes = [ghostPlane]
      ghost.needsUpdate = true
      ghostGroup = new THREE.Group()
      ghostGroup.name = 'FX_INTRO_GHOST'
      for (const mesh of ctx.occluder.meshes) {
        const clone = new THREE.Mesh(mesh.geometry, ghost)
        clone.matrixAutoUpdate = false
        clone.matrix.copy(mesh.matrixWorld)
        clone.castShadow = false
        clone.receiveShadow = false
        ghostGroup.add(clone)
      }
      ctx.scene.add(ghostGroup)

      // 科技蓝扫描平面: 骑在分解线上, 加色混合 + 辉光; 尺寸盖过整机脚印
      const sizeX = (ctx.machineBounds.max.x - ctx.machineBounds.min.x) * cfg.planeScale
      const sizeZ = (ctx.machineBounds.max.z - ctx.machineBounds.min.z) * cfg.planeScale
      const planeMat = new THREE.MeshBasicMaterial({
        color: ctx.theme === 'light' ? 0x0899cc : 0x36d1ff, // = --fx-accent
        map: makeScanTexture(),
        transparent: true,
        opacity: cfg.planeOpacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        side: THREE.DoubleSide,
      })
      scanPlane = new THREE.Mesh(new THREE.PlaneGeometry(sizeX, sizeZ), planeMat)
      scanPlane.rotation.x = -Math.PI / 2
      scanPlane.position.set(
        (ctx.machineBounds.min.x + ctx.machineBounds.max.x) / 2,
        sweep.top,
        (ctx.machineBounds.min.z + ctx.machineBounds.max.z) / 2,
      )
      scanPlane.renderOrder = 20
      ctx.scene.add(scanPlane)

      // 相机行程: 终点 = 标准 iso 机位(数值上与页面默认机位完全一致), 起点按偏转/抬高外推
      director.presetPose('iso', 0.82, 1, cam.endPos, cam.target)
      cam.center.copy(cam.target)
      _offset.copy(cam.endPos).sub(cam.center)
      cam.distEnd = _offset.length()
      cam.elEnd = Math.asin(_offset.y / cam.distEnd)
      cam.azEnd = Math.atan2(_offset.x, _offset.z)
      cam.azStart = cam.azEnd + cfg.azFromDeg * DEG
      cam.elStart = cfg.elFromDeg * DEG
      cam.distStart = cam.distEnd * cfg.camStartScale
      poseCamera(0)
      ctx.controls.update(0)
      prevControlsEnabled = ctx.controls.enabled
      ctx.controls.enabled = false // 相机输入锁死(环绕不被抢)

      ctx.dom.cardHost.classList.add('fx-pre-intro') // 悬浮卡在开场期间不冒头
      ctx.invalidateShadows()
      ctx.events.emit('intro', true)
    },

    /**
     * 功能: 中止开场 —— 全量清场, 世界即刻回到实体.
     * @param {{snapCamera?: boolean}} [options] snapCamera=true 时相机平滑落到终点机位
     *   (Esc 用); interlock 路径不传 —— 聚焦飞行紧接着接管相机.
     * @returns {void}
     */
    abort(options = {}) {
      if (!active) return
      cleanup()
      if (options.snapCamera) {
        ctx.controls.setLookAt(cam.endPos.x, cam.endPos.y, cam.endPos.z, cam.target.x, cam.target.y, cam.target.z, true)
      }
    },

    update(dt) {
      if (!active) return
      const cfg = ctx.config.intro
      clock += dt

      // 同一进度: 分解线到底 == 相机转到位(用户原话). 线用 smoothstep, 环绕用 easeInOutSine
      const raw = Math.min(clock / cfg.durS, 1)
      const u = smoothstep(raw)
      const lineY = sweep.top + (sweep.bottom - sweep.top) * u
      solidPlane.constant = -lineY
      ghostPlane.constant = lineY
      if (scanPlane) {
        scanPlane.position.y = lineY
        // 扫描中带一点确定性脉动; 到底后 0.3s 内淡出
        scanPlane.material.opacity = raw >= 1
          ? cfg.planeOpacity * Math.max(0, 1 - (clock - cfg.durS) / 0.3)
          : cfg.planeOpacity * (0.82 + 0.18 * Math.sin(clock * 7))
      }
      poseCamera(easeInOutSine(raw))
      if (raw < 1 || (scanPlane && scanPlane.material.opacity > 0)) ctx.invalidateShadows()

      if (raw >= 1) {
        tail += dt
        if (tail >= cfg.tailS) cleanup() // 正常收尾(相机已在终点)
      }
    },

    setStationState() {},
    setEnabled() {},
    setParams() {},

    dispose() {
      this.abort()
    },
  }
  return self
}
