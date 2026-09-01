/**
 * 功能: 沙盒迷你宿主 —— renderer/场景/相机控件/灯光/地面/帧循环/可控时钟/显示设置.
 *
 * 刻意不 import twin/scene 的 SceneManager/Environment(会拖进整棵依赖树), 但灯光与
 * 显示口径**逐值对齐正式页**(第二轮订正: 浅色曝光过度的病根是照抄了 spike 的
 * key 1.15, 而正式页浅色实际生效 0.7x1.1; 且过曝对 key 强敏感、对 env 几乎不敏感):
 *   - 灯光量级/灯色 = Environment.RIG(昼夜共用, 中性色);
 *   - 背景 = 径向渐变 CanvasTexture(照 makeBackgroundTexture 配方, 边缘是防过曝主杠杆);
 *   - 环境贴图 = StudioEnvironment 程序化影棚灯板(RoomEnvironment 会把金属拍成灰泥);
 *   - 雾距/主光摆位随整机半径(fitWorld), 摆位 = RIG.keyPos 方向 x 半径x2.4;
 *   - applyDisplay 消费 config.display(总亮度/各灯/背景/阴影/曝光), 压暗因子(聚焦)
 *     并入同一条计算 —— 面板改亮度与聚焦压暗永不打架.
 * 其余契约不变: addFrameHook 同 SceneManager 签名、按需阴影、可控时钟(freezeTime).
 */
import * as THREE from 'three'
import CameraControls from 'camera-controls'

import { createStudioEnvTexture } from '../three-d/twin/scene/StudioEnvironment.js'

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

/** 灯光基准(昼夜共用, 数值/灯色照正式页 Environment.RIG; 冷蓝灯色已被正式页否决) */
const RIG = {
  keyColor: 0xffffff,
  fillColor: 0xf4f7fb,
  rimColor: 0xe4ecf6,
  hemiSky: 0xffffff,
  hemiGround: 0xcfd6df,
  keyDir: new THREE.Vector3(-0.833, 12.2516, 0.6746).normalize(), // az -51° / el 85°
  shadowRadius: 5,
}

/** 周围环境分主题(数值照正式页 Environment.STAGES; 雾距是整机半径的倍率) */
const STAGES = {
  dark: {
    bgCenter: 0x161c26,
    bgEdge: 0x0b0f16,
    fog: 0x10151e,
    ground: 0x1a2130,
    groundRoughness: 0.55,
    groundMetalness: 0.1,
    gridMajor: 0x3d4d70,
    gridMinor: 0x27324a,
    gridOpacity: 0.42,
    fogNearR: 3.2,
    fogFarR: 12,
  },
  light: {
    bgCenter: 0xdce3eb,
    bgEdge: 0xaab4c2,
    fog: 0xc2c9d4,
    ground: 0xd4d9e0,
    groundRoughness: 0.75,
    groundMetalness: 0.0,
    gridMajor: 0x8797ae,
    gridMinor: 0xb9c4d3,
    gridOpacity: 0.45,
    fogNearR: 3.4,
    fogFarR: 7.0,
  },
}

/**
 * 功能: 径向渐变背景贴图(照正式页 makeBackgroundTexture 配方: 亮心略低于画面中心,
 * ±1 灰阶抖动防 8 位色带). 贴图背景才吃 scene.backgroundIntensity(纯色 Color 不吃).
 * @param {number} centerHex 中心色
 * @param {number} edgeHex 边缘色
 * @returns {THREE.CanvasTexture} SRGB 背景纹理
 */
function makeBackgroundTexture(centerHex, edgeHex) {
  const size = 512
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const css = (hex) => `#${hex.toString(16).padStart(6, '0')}`
  const gradient = ctx.createRadialGradient(size * 0.5, size * 0.56, size * 0.1, size * 0.5, size * 0.56, size * 0.78)
  gradient.addColorStop(0, css(centerHex))
  gradient.addColorStop(1, css(edgeHex))
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  const image = ctx.getImageData(0, 0, size, size)
  for (let i = 0; i < image.data.length; i += 4) {
    const noise = (Math.random() - 0.5) * 2
    image.data[i] += noise
    image.data[i + 1] += noise
    image.data[i + 2] += noise
  }
  ctx.putImageData(image, 0, 0)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

/**
 * 功能: 地面圆盘径向淡出 alphaMap(中心不透明, 55% 起渐隐) —— 地面在雾生效前
 * 就融进背景渐变, 消掉第一轮实拍里那条突兀的"地台边缘线".
 * @returns {THREE.CanvasTexture} 灰度纹理
 */
function makeGroundAlphaTexture() {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0.0, '#ffffff')
  gradient.addColorStop(0.45, '#ffffff')
  gradient.addColorStop(0.96, '#000000')
  gradient.addColorStop(1.0, '#000000')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  return new THREE.CanvasTexture(canvas)
}

/**
 * 功能: 创建沙盒宿主.
 * @param {object} options 参数对象
 * @param {HTMLElement} options.container 画布容器
 * @param {string} options.theme 'dark' | 'light'
 * @param {number|null} [options.dpr] DPR 上限覆写(默认 min(devicePixelRatio, 2))
 * @param {object} options.display 显示设置对象(config.display 的引用, 面板直接改它)
 * @returns {object} stage 实例
 */
export function createStage({ container, theme, dpr = null, display }) {
  const palette = STAGES[theme] || STAGES.dark

  const renderer = new THREE.WebGLRenderer({
    antialias: false, // 抗锯齿交给后期 SMAA(与正式页一致); low 档认了锯齿(降级形态)
    alpha: false,
    powerPreference: 'high-performance',
    stencil: false,
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, dpr || 2))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.NoToneMapping // 色调映射交给后期链尾; low 档由 postfx 改回
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  renderer.shadowMap.autoUpdate = false // 按需重渲: 动了几何必须 invalidateShadows()
  renderer.info.autoReset = false
  renderer.localClippingEnabled = true // 开场扫描的双层裁剪面用(无裁剪面的材质零开销)
  container.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  const backgroundTexture = makeBackgroundTexture(palette.bgCenter, palette.bgEdge)
  scene.background = backgroundTexture
  scene.fog = new THREE.Fog(palette.fog, 13, 32) // 占位, fitWorld 后按整机半径重设
  const fogBase = new THREE.Color(palette.fog)

  // -- 灯光(RIG 口径, 强度全部由 applyDisplay 灌入) ---------------------------
  const hemi = new THREE.HemisphereLight(RIG.hemiSky, RIG.hemiGround, 0.45)
  scene.add(hemi)
  const key = new THREE.DirectionalLight(RIG.keyColor, 0.77)
  key.position.copy(RIG.keyDir).multiplyScalar(12)
  key.castShadow = true
  key.shadow.mapSize.set(2048, 2048)
  key.shadow.bias = -0.0002
  key.shadow.radius = RIG.shadowRadius
  scene.add(key)
  scene.add(key.target)
  const fill = new THREE.DirectionalLight(RIG.fillColor, 0.3)
  fill.position.set(7, 4, -5)
  scene.add(fill)
  const rim = new THREE.DirectionalLight(RIG.rimColor, 0.17)
  rim.position.set(2, 3, -9)
  scene.add(rim)

  // 程序化影棚灯板 -> PMREM(金属高光形状的来源; RoomEnvironment 只会给一团均匀灰)
  const envTexture = createStudioEnvTexture(renderer)
  scene.environment = envTexture

  // -- 地面: 软边圆盘 + 细网格 ------------------------------------------------
  const groundMat = new THREE.MeshStandardMaterial({
    color: palette.ground,
    roughness: palette.groundRoughness,
    metalness: palette.groundMetalness,
    alphaMap: makeGroundAlphaTexture(),
    transparent: true,
  })
  const ground = new THREE.Mesh(new THREE.CircleGeometry(14, 72), groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.002
  ground.receiveShadow = true
  scene.add(ground)

  const grid = new THREE.GridHelper(24, 48, palette.gridMajor, palette.gridMinor)
  grid.material.transparent = true
  grid.material.opacity = palette.gridOpacity
  grid.material.depthWrite = false
  grid.position.y = 0.0005
  scene.add(grid)

  // -- 相机与控件 ------------------------------------------------------------
  const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 400)
  camera.position.set(4, 3, 5)
  const controls = new CameraControls(camera, renderer.domElement)
  controls.smoothTime = 0.42 // 与正式页 CameraRig 同手感; v3 起 dampingFactor 是废弃 no-op
  controls.minDistance = 0.35
  controls.maxDistance = 60
  controls.maxPolarAngle = Math.PI * 0.495 // 不允许翻到地面以下
  controls.infinityDolly = false

  // -- 显示设置与压暗因子(聚焦) ------------------------------------------------
  /** 聚焦压暗乘数(dimmer 每帧驱动); 1 = 常态 */
  const dimMul = { light: 1, env: 1, bg: 1 }
  /** 世界尺度(fitWorld 灌入); null = 模型未加载 */
  let worldFit = null

  /**
   * 功能: 把 config.display 的当前值(x 压暗因子)一次性落到灯光/环境/背景/雾/阴影/曝光.
   * 面板滑杆与聚焦压暗都最终走这一条 —— 两者天然不打架.
   * @returns {void}
   */
  function applyDisplay() {
    const d = display
    hemi.intensity = d.hemiIntensity * d.brightness * dimMul.light
    key.intensity = d.keyIntensity * d.brightness * dimMul.light
    fill.intensity = d.fillIntensity * d.brightness * dimMul.light
    rim.intensity = d.rimIntensity * d.brightness * dimMul.light
    scene.environmentIntensity = d.envIntensity * d.brightness * dimMul.env
    scene.backgroundIntensity = d.bgIntensity * dimMul.bg // 贴图背景才吃这个值
    scene.fog.color.copy(fogBase).multiplyScalar(Math.min(d.bgIntensity, 1) * dimMul.bg)
    key.shadow.intensity = d.shadowIntensity
    renderer.toneMappingExposure = d.exposure // NEUTRAL 链尾照乘曝光(已核实), low 档同义
  }
  applyDisplay()

  // -- 可控时钟与帧循环 --------------------------------------------------------
  const clockState = { elapsed: 0, frozen: false }
  const clock = {
    get elapsed() {
      return clockState.elapsed
    },
    get frozen() {
      return clockState.frozen
    },
    /**
     * 功能: 把动画时间钉在 t 秒(shader/剧本/CSS 动画统一定格). 截图矩阵的定格入口.
     * @param {number} t 目标时刻(秒)
     * @returns {void}
     */
    freezeTime(t) {
      if (Number.isFinite(t)) clockState.elapsed = t
      clockState.frozen = true
      document.documentElement.classList.add('fx-frozen')
    },
    unfreeze() {
      clockState.frozen = false
      document.documentElement.classList.remove('fx-frozen')
    },
  }

  /** @type {Set<(delta: number, elapsed: number) => void>} */
  const frameHooks = new Set()
  /** @type {{render: (delta: number) => void}|null} 后期链(main 装配后注入) */
  let composer = null
  let shadowDirty = true
  let autorotate = false

  const stats = { fps: 0, drawCalls: 0, triangles: 0 }
  let fpsFrames = 0
  let fpsLast = performance.now()

  let rafId = 0
  let last = performance.now()

  /** 每帧: 时钟 -> 控件 -> 帧钩子 -> 按需阴影 -> 渲染 -> 指标 */
  function frame(now) {
    rafId = requestAnimationFrame(frame)
    const rawDelta = Math.min((now - last) / 1000, 0.1)
    last = now

    // 冻结时特效拿到 delta=0(动画定格), 但相机控件仍用真实 dt(允许人工调机位后截图)
    const delta = clockState.frozen ? 0 : rawDelta
    if (!clockState.frozen) clockState.elapsed += rawDelta
    if (autorotate && !clockState.frozen) controls.azimuthAngle += rawDelta * 0.12
    controls.update(rawDelta)

    for (const hook of frameHooks) hook(delta, clockState.elapsed)

    if (shadowDirty) {
      renderer.shadowMap.needsUpdate = true
      shadowDirty = false
    }
    renderer.info.reset()
    if (composer) composer.render(delta)
    else renderer.render(scene, camera)

    stats.drawCalls = renderer.info.render.calls
    stats.triangles = renderer.info.render.triangles
    fpsFrames += 1
    if (now - fpsLast >= 1000) {
      stats.fps = Math.round((fpsFrames * 1000) / (now - fpsLast))
      fpsFrames = 0
      fpsLast = now
    }
  }

  function resize() {
    const width = container.clientWidth || window.innerWidth
    const height = container.clientHeight || window.innerHeight
    renderer.setSize(width, height)
    camera.aspect = width / Math.max(height, 1)
    camera.updateProjectionMatrix()
    composer?.resize?.(width, height)
  }
  window.addEventListener('resize', resize)
  // 套外壳后画布容器的尺寸变化(侧栏折叠/面板动画)不派发 window resize, 靠 RO 补上
  const resizeObserver = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => resize()) : null
  resizeObserver?.observe(container)
  resize()

  return {
    scene,
    camera,
    renderer,
    canvas: renderer.domElement,
    controls,
    lights: { hemi, key, fill, rim },
    clock,
    stats,
    palette,
    applyDisplay,

    /**
     * 功能: 模型加载后按整机尺度定雾距/主光摆位/影子相机(照正式页 fitShadowToModel 口径).
     * @param {THREE.Box3} box 整机世界包围盒
     * @returns {void}
     */
    fitWorld(box) {
      const sphere = box.getBoundingSphere(new THREE.Sphere())
      worldFit = { center: sphere.center.clone(), radius: Math.max(sphere.radius, 0.5) }
      scene.fog.near = worldFit.radius * palette.fogNearR
      scene.fog.far = worldFit.radius * palette.fogFarR
      key.position.copy(worldFit.center).addScaledVector(RIG.keyDir, worldFit.radius * 2.4)
      key.target.position.copy(worldFit.center)
      const cam = key.shadow.camera
      const extent = worldFit.radius * 1.2
      cam.left = -extent
      cam.right = extent
      cam.top = extent
      cam.bottom = -extent
      cam.near = worldFit.radius * 0.5
      cam.far = worldFit.radius * 5
      cam.updateProjectionMatrix()
      shadowDirty = true
    },

    /**
     * 功能: 聚焦压暗因子(dimmer 每帧驱动; {light, env, bg} 均为 0..1 乘数).
     * @param {{light: number, env: number, bg: number}} mul 乘数组
     * @returns {void}
     */
    setDim(mul) {
      dimMul.light = mul.light
      dimMul.env = mul.env
      dimMul.bg = mul.bg
      applyDisplay()
    },

    /**
     * 功能: 注册每帧回调(与 SceneManager.addFrameHook 同签名).
     * @param {(delta: number, elapsed: number) => void} fn 回调
     * @returns {() => void} 注销函数
     */
    addFrameHook(fn) {
      frameHooks.add(fn)
      return () => frameHooks.delete(fn)
    },

    /** 功能: 声明几何/可见性动过, 下一帧重渲阴影贴图(只改材质颜色/emissive 不用调). */
    invalidateShadows() {
      shadowDirty = true
    },

    /**
     * 功能: 注入后期链({render, resize} 形状; null = 直渲).
     * @param {object|null} fx postfx 实例
     * @returns {void}
     */
    setComposer(fx) {
      composer = fx
      resize()
    },

    setAutorotate(on) {
      autorotate = !!on
    },

    start() {
      last = performance.now()
      rafId = requestAnimationFrame(frame)
    },

    /** 功能: 释放全部 GPU 资源与监听(与 SceneManager.dispose 同标准的强契约). */
    dispose() {
      cancelAnimationFrame(rafId)
      window.removeEventListener('resize', resize)
      resizeObserver?.disconnect()
      frameHooks.clear()
      controls.dispose()
      ground.geometry.dispose()
      groundMat.alphaMap?.dispose()
      groundMat.dispose()
      grid.geometry.dispose()
      grid.material.dispose()
      backgroundTexture.dispose()
      envTexture.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    },
  }
}
