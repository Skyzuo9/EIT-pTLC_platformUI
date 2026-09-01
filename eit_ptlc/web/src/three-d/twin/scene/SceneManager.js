/**
 * 功能: 三维视图的总协调器 —— 渲染器、渲染循环、画质档位、资源生命周期.
 *
 * 这是整个三维模块唯一持有 WebGL 上下文的地方. 上位机是常驻不刷新的控制台页面,
 * 反复进出三维页而不彻底释放资源会让显存持续增长直至上下文丢失, 因此:
 *   - 所有 GPU 资源的创建都汇聚到本类;
 *   - dispose() 是强契约: 停循环 -> 解事件 -> 释放场景/后期/渲染器 -> 断引用;
 *   - 监听 webglcontextlost/restored, 上下文丢失时暂停循环而不是继续空转报错.
 *
 * 画质档位(2026-08-01 影棚化升级, 见 Environment.js 头注释):
 *   high   —— DPR 上限 2, 辉光 + 描边 + 抗锯齿 + SSAO + 实时阴影 2048 + 暗角 + 倒影
 *   medium —— DPR 上限 1.5, 辉光 + 描边 + 实时阴影 1024 + 暗角
 *   low    —— DPR 1, 直接渲染不走后期、无阴影(接触阴影回满浓度兜底落地感)
 * 实时阴影是按需更新的(shadowMap.autoUpdate=false): 相机转动不触发重渲, 只有
 * 模型/可见性/主题变化时 invalidateShadows() 才重算一次 —— 静止时零每帧开销.
 */
import * as THREE from 'three'

import { getTheme, onThemeChange } from '../../theme.js'
import { TwinBindings } from '../bindings/TwinBindings.js'
import { CameraRig } from './CameraRig.js'
import { CONTACT_STRENGTH, ContactShadow } from './ContactShadow.js'
import { EFFECT_DEFAULTS, Effects } from './Effects.js'
import { createEnvironment, getDisplayBaseline } from './Environment.js'
import { DeltaProbe, GpuMeter } from './GpuMeter.js'
import { GroundReflection } from './GroundReflection.js'
import { collectStats, disposeObject, loadMachine } from './loadModel.js'
import { OutlineArbiter } from './OutlineArbiter.js'
import { PlateFaceLayer } from './plates/PlateFaceLayer.js'
import {
  PLATE_FIELDS,
  PLATE_FIELD_BY_KEY,
  clampPlateValue,
  effectivePlateSpec,
  loadPlateOverrides,
  plateToggle,
  savePlateOverrides,
} from './plates/plateSettings.js'
import { PlateBinding } from '../bindings/PlateBinding.js'
import { TrayBinding } from '../bindings/TrayBinding.js'
import { PickController } from './PickController.js'
import {
  DEFAULT_BACKGROUND_SCENE,
  DISPLAY_FIELDS,
  FIELD_BY_KEY,
  clampValue,
  effectiveSettings,
  exportPayload,
  loadBackgroundScene,
  loadDisplayState,
  overridesFor,
  saveBackgroundScene,
  saveDisplayState,
  setOverride,
} from './displaySettings.js'

/** 画质档位定义 */
export const QUALITY_TIERS = {
  high: {
    maxDpr: 2.0, bloom: true, outline: true, smaa: true,
    ssao: true, vignette: true, shadows: true, shadowMapSize: 2048, reflection: true,
    label: '高',
  },
  medium: {
    maxDpr: 1.5, bloom: true, outline: true, smaa: false,
    ssao: false, vignette: true, shadows: true, shadowMapSize: 1024, reflection: false,
    label: '中',
  },
  low: {
    maxDpr: 1.0, bloom: false, outline: false, smaa: false,
    ssao: false, vignette: false, shadows: false, shadowMapSize: 1024, reflection: false,
    label: '低',
  },
  // 仅描边的轻量档: 装配台专用 —— raw 模型两千多个绘制调用, bloom/SSAO 是纯负担,
  // 但选中/悬停需要与材质台一致的描边. 不复用 low: low 是自动降档的最后兜底档
  // ("零后期"语义), 给它开 outline 会让弱机兜底档也背上 composer 开销.
  lite: {
    maxDpr: 1.0, bloom: false, outline: true, smaa: false,
    ssao: false, vignette: false, shadows: false, shadowMapSize: 1024, reflection: false,
    label: '轻',
  },
}

/** 金属反射增强的判定阈值: materials.yaml 里金属 0.85~0.97, 非金属 ≤0.2, 界线干净 */
const ENV_BOOST_METALNESS = 0.6

/** 自动降档判据: 平均帧率低于该值并持续若干秒则降一档 */
const DEGRADE_FPS_THRESHOLD = 45
const DEGRADE_SUSTAIN_MS = 5000

/**
 * 位于台面以下、被机壳挡住的工位(manifest bounds 中心 y 为负: 泵站 -0.62 /
 * 上下料位 -0.34, 其余工位全为正). 只有选中它们才需要淡化外壳露出内部机构;
 * 台面上的工位本就看得见, 一律淡化会把桌面也虚化掉, 纯属误伤.
 */
const ENCLOSED_STATIONS = new Set(['PUMP', 'FEEDLIFT'])

export class SceneManager {
  /**
   * 功能: 创建渲染器与场景, 但不立即加载模型(模型由 loadMachineModel 异步加载).
   * @param {HTMLElement} container 画布容器元素
   * @param {object} [options] 可选项
   * @param {keyof typeof QUALITY_TIERS} [options.quality='high'] 初始画质档位
   * @param {boolean} [options.autoDegrade=true] 帧率不足时是否自动降档
   * @param {(stats: object) => void} [options.onStats] 每秒回调一次运行时指标
   */
  constructor(container, options = {}) {
    const { quality = 'high', autoDegrade = true, onStats } = options

    this.container = container
    this.onStats = onStats
    this.autoDegrade = autoDegrade
    this.quality = QUALITY_TIERS[quality] ? quality : 'high'
    this.disposed = false
    this.contextLost = false

    /** 背景是全局偏好: 不按主题分槽, 所有 SceneManager 实例从同一键加载 */
    this.backgroundScene = loadBackgroundScene(window.localStorage)
    /**
     * 显示设置状态(基准 ⊕ 用户覆盖, 单槽), 面板经 this.display 操作.
     * 2026-08-05 起不再按主题分槽 —— 昼夜共用同一套观感参数, 也就共用同一组滑块值.
     */
    this.displayState = loadDisplayState(window.localStorage)
    /** 负载增量测量的运行态 */
    this._probe = null
    this._probeInfo = null
    this._shadowMeasure = null
    /** @type {Map<string, object>} 已测得的逐项开销(档位/主题切换时失效) */
    this._loadCache = new Map()

    // -- 渲染器 -----------------------------------------------------------
    this.renderer = new THREE.WebGLRenderer({
      antialias: false, // 抗锯齿交给后期的 SMAA, 避免与 MSAA 叠加浪费带宽
      alpha: false,
      powerPreference: 'high-performance',
      stencil: false,
    })
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    // 色调映射在后期链尾统一处理, 渲染器这里保持线性输出
    this.renderer.toneMapping = THREE.NoToneMapping
    // 实时阴影(按需更新): enabled 常开(没有 castShadow 光时零成本), 是否真的投影
    // 由各档位经 environment.setShadows 切 key 光. autoUpdate 关掉后, 只有
    // invalidateShadows() 置 needsUpdate 的那一帧才渲阴影贴图 —— 纯轨道浏览免费.
    // 注意 three 0.185 已废弃 PCFSoftShadowMap(会警告并回退), 软化靠 PCFShadowMap
    // 的 shadow.radius(新版 Vogel 盘采样下生效).
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFShadowMap
    this.renderer.shadowMap.autoUpdate = false
    // 局部裁剪面常开: 只有开场动画(IntroReveal)的双层裁剪在用; 无裁剪面的材质零开销
    this.renderer.localClippingEnabled = true
    /** 渲染耗时计量: 负载条与"开某项加多少"的实测数据源 */
    this.gpuMeter = new GpuMeter(this.renderer.getContext())
    // 关掉自动重置: 后期处理一帧内会多次调用 render, 自动重置会让统计只剩最后一趟
    // 全屏三角形的数据(表现为"绘制调用 1 / 三角形 1"). 改为每帧开头手动重置一次.
    this.renderer.info.autoReset = false
    this.canvas = this.renderer.domElement
    this.canvas.style.display = 'block'
    this.canvas.style.width = '100%'
    this.canvas.style.height = '100%'
    container.appendChild(this.canvas)

    // -- 场景与相机 -------------------------------------------------------
    const environment = createEnvironment(this.renderer)
    this.environment = environment
    this.scene = environment.scene
    this.disposeEnvironment = environment.dispose

    /** 烘焙式地面接触阴影(模型加载后 bake 一次, 零每帧开销) */
    this.contactShadow = new ContactShadow(this.renderer, this.scene)
    this.contactShadow.setTheme(getTheme())

    /** 烘焙式地面淡倒影(同为一次性烘焙, 仅 high 档显示) */
    this.groundReflection = new GroundReflection(this.renderer, this.scene)
    this.groundReflection.setTheme(getTheme())

    // 昼夜主题热切: 场景配色/灯光、描边配色、阴影浓度一起换, 不重建场景.
    // 切完在同一同步链内重放显示设置(换到新主题的覆盖槽), 末尾挂起阴影重渲;
    // 主题变了负载测量的口径也变了, 缓存与在飞测量一并作废.
    this._offTheme = onThemeChange((theme) => {
      environment.setTheme(theme)
      this.effects?.setTheme(theme)
      this.contactShadow.setTheme(theme)
      this.groundReflection.setTheme(theme)
      this._resetMeasurement()
      this._applyDisplaySettings()
    })

    this.cameraRig = new CameraRig(this.canvas)
    this.camera = this.cameraRig.camera

    /** @type {object|null} 开场动画控制器(useTwinScene 装配; IntroReveal 实例) */
    this.intro = null
    /** 自动环绕开关(HUD「环绕」钮; 用户一动相机即自停) */
    this.autoRotate = false
    /** @type {((on: boolean) => void)|null} 环绕被用户接管自停时的回调(HUD 高亮同步) */
    this.onAutoRotateChange = null
    // 用户让位: 拖拽/滚轮触发 controlstart 即停环绕; 程序化 setLookAt 不触发, 无自锁
    this._onUserControl = () => this._stopAutoRotate()
    this.cameraRig.controls.addEventListener('controlstart', this._onUserControl)

    this.effects = null
    /**
     * 描边选中的分层仲裁 —— 实时页有工位/零件/物料三个写者共用同一条描边通道.
     * 挂在 manager 上而不是各页自建, 是因为写者(TwinView / StationActionsTab /
     * MaterialInteraction)本来就都持有 manager, 这样零 prop 管道; 单写者的
     * 材质台/工作台/动作台照旧直接调 effects.setSelected, 不经过它。
     */
    this.outline = new OutlineArbiter(null)
    this._buildEffects()

    /**
     * 薄层板规格与表现的用户覆盖(单槽, 不按主题分 —— 换个深浅主题板不该变厚,
     * 吸盘柔性也不该被关掉)。见 plates/plateSettings.js 的头注释。
     */
    this.plateOverrides = loadPlateOverrides(window.localStorage)
    /** @type {Set<{layer?: object, stage?: object}>} 在场的板消费者, 见 registerPlateConsumer */
    this._plateConsumers = new Set()

    /**
     * 显示设置面板的唯一操作面(面板不直接摸 environment/effects)。
     *
     * 薄层板那几项**合并在同一个操作面里**但**分开存**: 面板对用户是一个,
     * 存储语义却不同(观感单槽 / 背景全局 / 工件规格单槽), 所以按 key 路由。
     */
    this.display = {
      fields: [...DISPLAY_FIELDS, ...PLATE_FIELDS],
      effective: () => ({ ...this._effectiveDisplay(), ...this._effectivePlate() }),
      baseline: () => this._displayBaseline(getTheme()),
      overrides: () => ({ ...this._displayOverrides(), ...this.plateOverrides }),
      set: (key, value) => (key === 'backgroundScene'
        ? this._setBackgroundScene(value)
        : PLATE_FIELD_BY_KEY.has(key)
          ? this._setPlate(key, value)
          : this._setDisplay(key, value)),
      clear: (key) => (key === 'backgroundScene'
        ? this._setBackgroundScene(null)
        : PLATE_FIELD_BY_KEY.has(key)
          ? this._setPlate(key, null)
          : this._setDisplay(key, null)),
      // 覆盖收成单槽后这就是"恢复全部默认"(名字保留, 面板文案已去掉主题名)
      resetTheme: () => {
        this.displayState.overrides = {}
        saveDisplayState(window.localStorage, this.displayState)
        this._resetMeasurement()
        this._applyDisplaySettings()
      },
      exportJson: () => {
        const theme = getTheme()
        return JSON.stringify(
          exportPayload(theme, this.quality, this._displayBaseline(theme), this._displayOverrides()),
          null,
          2,
        )
      },
      tier: () => QUALITY_TIERS[this.quality],
      setQuality: (next) => this.setQuality(next),
      measureShadows: () => this.measureShadows(),
    }

    /** @type {THREE.Group|null} 整机模型根节点 */
    this.machineRoot = null
    /** @type {Map<string, THREE.Object3D>} 节点路径索引 */
    this.nodeIndex = new Map()
    /** @type {object|null} 模型统计信息 */
    this.modelStats = null
    /** @type {TwinBindings|null} 状态到视觉的绑定层 */
    this.bindings = null
    /** @type {PlateFaceLayer|null} 薄层板实体层(程序化分层板 + 料仓堆叠); 仅实时页 opt-in */
    this.plateLayer = null
    /** @type {PlateBinding|null} 板位置绑定层(L1 账本 + L2 包络仲裁) */
    this.plates = null
    /** @type {TrayBinding|null} 在途托盘/耗材绑定层(只吃 material_state.transit, 无推断) */
    this.trays = null
    /** @type {PickController|null} 拾取控制器 */
    this.picker = null

    // -- 循环与计时 -------------------------------------------------------
    this.clock = new THREE.Clock()
    this.rafId = 0
    this.frameCount = 0
    this.fps = 0
    this._fpsWindowStart = performance.now()
    this._lowFpsSince = 0
    /** @type {Array<(delta: number, elapsed: number) => void>} 每帧回调(状态绑定层挂在这里) */
    this.frameHooks = []
    /**
     * 播放倍速 —— 只有回放会改它 (1 = 实时)。见 _renderFrame 里对 delta 的处理:
     * 帧钩子是所有时间积分器的唯一入口, 在这里乘一次即可覆盖全部消费者。
     * @type {number}
     */
    this.timeScale = 1
    /** 单帧 delta 上限(秒); 倍速播放时用来挡住切标签页回来的秒级跳变。 */
    this.maxFrameDelta = 0.1

    this._bindEvents()
    this.resize()
    this.start()
  }

  // -- 初始化辅助 ---------------------------------------------------------

  /**
   * 功能: 按当前画质档位重建后期处理链, 并联动阴影/接触影/倒影的档位开关.
   * @returns {void}
   */
  _buildEffects() {
    const tier = QUALITY_TIERS[this.quality]
    this.effects?.dispose()
    if (!tier.bloom && !tier.outline && !tier.smaa && !tier.ssao && !tier.vignette) {
      // 低档位彻底不走后期, 直接由渲染器出图. 后期链尾的色调映射也随之消失,
      // 必须在渲染器上补回来, 否则高光硬剪、整体发灰, 与中高档观感断层.
      this.effects = null
      this.renderer.toneMapping = THREE.NeutralToneMapping
    } else {
      // 走后期时色调映射由链尾的 ToneMappingEffect 统一处理, 渲染器保持线性输出
      this.renderer.toneMapping = THREE.NoToneMapping
      this.effects = new Effects(this.renderer, this.scene, this.camera, {
        bloom: tier.bloom,
        outline: tier.outline,
        smaa: tier.smaa,
        ssao: tier.ssao,
        vignette: tier.vignette,
      })
      const size = this._viewportSize()
      this.effects.resize(size.width, size.height)
    }

    // 档位切换后重放显示设置(档位与用户开关在 _applyDisplaySettings 里合成:
    // 有效状态 = 档位允许 且 用户开). 手动 setQuality 与自动降档都走到这里.
    this._applyDisplaySettings()

    // 重建后期链会丢掉旧链上的选择集, 从权威状态重放状态灯辉光目标,
    // 否则切档后状态灯不再发光(初次构造时绑定层尚未建立, 安全空转).
    this.effects?.setBloomTargets(this.bindings?.getBloomTargets() || [])
    // 描边选择集同理: 仲裁器持有的是权威状态, 重新指到新链上并重放,
    // 否则切一次画质档, 用户选中的工位/零件描边就没了(低档位本就没有描边链, attach(null) 空转)
    this.outline.attach(this.effects)
  }

  /**
   * 功能: 绑定尺寸变化、可见性与 WebGL 上下文事件.
   * @returns {void}
   */
  _bindEvents() {
    this._onResize = () => this.resize()
    this._resizeObserver = new ResizeObserver(this._onResize)
    this._resizeObserver.observe(this.container)

    // 页面切到后台时停渲染, 避免白白吃 GPU(常驻控制台页面这点很重要);
    // 在飞的负载测量随停渲作废(时钟继续走而样本断供, 测出来是脏的)
    this._onVisibility = () => {
      if (document.hidden) {
        this._resetMeasurement()
        this.stop()
      } else {
        this.start()
      }
    }
    document.addEventListener('visibilitychange', this._onVisibility)

    this._onContextLost = (event) => {
      event.preventDefault()
      this.contextLost = true
      this.stop()
      console.warn('[twin] WebGL 上下文丢失, 已暂停渲染')
    }
    this._onContextRestored = () => {
      this.contextLost = false
      this.start()
      console.info('[twin] WebGL 上下文已恢复')
    }
    this.canvas.addEventListener('webglcontextlost', this._onContextLost, false)
    this.canvas.addEventListener('webglcontextrestored', this._onContextRestored, false)
  }

  /**
   * 功能: 取容器当前像素尺寸.
   * @returns {{width: number, height: number}} 宽高
   */
  _viewportSize() {
    return {
      width: Math.max(this.container.clientWidth, 1),
      height: Math.max(this.container.clientHeight, 1),
    }
  }

  // -- 公开操作 -----------------------------------------------------------

  /**
   * 功能: 同步渲染器/相机/后期到当前容器尺寸与画质档位的像素比上限.
   * @returns {void}
   */
  resize() {
    if (this.disposed) return
    const { width, height } = this._viewportSize()
    const dpr = Math.min(window.devicePixelRatio || 1, QUALITY_TIERS[this.quality].maxDpr)

    this.renderer.setPixelRatio(dpr)
    this.renderer.setSize(width, height, false)
    this.cameraRig.resize(width, height)
    this.effects?.resize(width, height)
  }

  /**
   * 功能: 挂起一次阴影贴图重渲(下一帧生效). 按需更新策略的唯一入口:
   *       模型加载/主题热切/切档/隐藏隔离透视/动画帧 都应调它, 纯相机运动不必.
   * @returns {void}
   */
  invalidateShadows() {
    if (this.disposed) return
    this.renderer.shadowMap.needsUpdate = true
  }

  /**
   * 功能: 重算金属反射增强集合. 材质台把某个材质的 metalness 拖过阈值后调用,
   *       否则该材质的反射增强状态停留在加载时的判定上.
   * @returns {void}
   */
  refreshEnvBoost() {
    if (!this.machineRoot || this.disposed) return
    const materials = new Set()
    this.machineRoot.traverse((node) => {
      if (node.isMesh && node.material && node.material.metalness >= ENV_BOOST_METALNESS) {
        materials.add(node.material)
      }
    })
    this.environment.registerEnvBoost(materials)
  }

  // -- 显示设置 -----------------------------------------------------------

  /**
   * 功能: 拼装某主题的显示设置全量基准: 色板派生(灯光/角度/阴影/背景)
   *       + 效果默认 + 接触影基准 + 各开关默认全开.
   * @param {string} theme 主题名
   * @returns {object} 全量基准
   */
  _displayBaseline(theme) {
    return {
      ...getDisplayBaseline(theme),
      backgroundScene: DEFAULT_BACKGROUND_SCENE,
      shadowsEnabled: true,
      contactStrength: CONTACT_STRENGTH[theme] ?? CONTACT_STRENGTH.dark,
      ssaoEnabled: true,
      ssaoIntensity: EFFECT_DEFAULTS.ssaoIntensity,
      bloomEnabled: true,
      vignetteEnabled: true,
      vignetteDarkness: EFFECT_DEFAULTS.vignetteDarkness,
      reflectionEnabled: true,
    }
  }

  /**
   * 功能: 全量有效设置(基准 ⊕ 用户覆盖). 覆盖是单槽, 昼夜共用。
   * @returns {object} 有效设置
   */
  _effectiveDisplay() {
    return effectiveSettings(this._displayBaseline(getTheme()), {
      ...overridesFor(this.displayState),
      backgroundScene: this.backgroundScene,
    })
  }

  /** 用户覆盖 + 全局背景覆盖, 供面板高亮与参数导出共用。 */
  _displayOverrides() {
    return {
      ...overridesFor(this.displayState),
      ...(this.backgroundScene === DEFAULT_BACKGROUND_SCENE
        ? {}
        : { backgroundScene: this.backgroundScene }),
    }
  }

  /**
   * 功能: 写全局背景偏好并立刻切换场景; null 表示回到默认摄影棚。
   * @param {*} value 背景场景
   * @returns {'default'|'laboratory'} 生效值
   */
  _setBackgroundScene(value) {
    if (this.disposed) return this.backgroundScene
    const next = value === null || value === undefined
      ? DEFAULT_BACKGROUND_SCENE
      : clampValue('backgroundScene', value)
    if (next === null) return this.backgroundScene
    if (next === this.backgroundScene) return next
    this.backgroundScene = saveBackgroundScene(window.localStorage, next)
    // 房间会改变绘制负载与接收阴影的地面, 旧测量口径和阴影贴图都要作废。
    this._resetMeasurement()
    this._applyDisplaySettings('backgroundScene')
    return this.backgroundScene
  }

  /**
   * 功能: 薄层板那几项的有效值(manifest 契约 ⊕ 用户覆盖).
   * @returns {{silicaMm: number, contactEnabled: boolean}}
   */
  _effectivePlate() {
    const spec = effectivePlateSpec(this.manifest?.plateSpec, this.plateOverrides)
    return {
      silicaMm: spec.silicaMm,
      contactEnabled: plateToggle('contactEnabled', this.plateOverrides),
    }
  }

  /**
   * 功能: 写一个薄层板覆盖并立刻生效.
   *
   * 与 _setDisplay 分开是因为存储语义不同(单槽 vs 按主题分槽), 见 plateSettings 头注释。
   * @param {string} key 字段名
   * @param {*} value 新值; null 表示清除覆盖回到契约基准
   * @returns {*} 实际生效的值
   */
  _setPlate(key, value) {
    if (value === null || value === undefined) delete this.plateOverrides[key]
    else {
      const clamped = clampPlateValue(key, value)
      if (clamped === null) return this._effectivePlate()[key]
      this.plateOverrides[key] = clamped
    }
    savePlateOverrides(window.localStorage, this.plateOverrides)
    this._applyPlateSettings()
    return this._effectivePlate()[key]
  }

  /**
   * 功能: 登记一组板消费者(实体层 + 接触判据的持有者), 设置改动时一并灌进去.
   *
   * 为什么要登记而不是直接写 `this.plateLayer`: 实时页的板层归 SceneManager,
   * 而动作/演示页的板层归 useMotionStack 自己造(两条链互斥, 见其头注释)。
   * 面板只有一个, 所以设置得能同时找到两边 —— 谁在场谁登记。
   *
   * @param {{layer?: object, stage?: object}} consumer 板实体层与接触判据持有者
   * @returns {() => void} 注销函数
   */
  registerPlateConsumer(consumer) {
    if (!consumer) return () => {}
    this._plateConsumers.add(consumer)
    this._applyPlateSettings()
    return () => this._plateConsumers.delete(consumer)
  }

  /** 把薄层板设置灌进所有在场的板层与接触判据。 */
  _applyPlateSettings() {
    if (this.disposed) return
    const eff = this._effectivePlate()
    let moved = false
    for (const consumer of this._plateConsumers) {
      if (consumer.layer?.setSilicaThickness(eff.silicaMm)) moved = true
      consumer.stage?.setContactEnabled(eff.contactEnabled)
    }
    if (moved) this.invalidateShadows()
  }

  /**
   * 功能: 把当前有效设置灌进场景各层. 有效状态 = 画质档位允许 且 用户开.
   * @param {string|null} [changedKey] 本次变更的字段(省重渲判断用; 空表示全量重放)
   * @returns {void}
   */
  _applyDisplaySettings(changedKey = null) {
    if (this.disposed || !this.displayState || !this.environment) return
    const tier = QUALITY_TIERS[this.quality]
    const eff = this._effectiveDisplay()

    this.environment.applyDisplay(eff)
    // 背景可能刚从"默认"切到"实验室"(或切回来): 相机的退让上限随之改变
    this._syncCameraEnclosure()
    this.effects?.applyDisplay(eff)
    this.contactShadow?.setStrength(eff.contactStrength)
    this.groundReflection?.setEnabled(tier.reflection && eff.reflectionEnabled)

    // 主光是唯一影子光, 它被开关关掉时阴影贴图一并停渲(接触影自动回满浓度)
    const shadowsOn = tier.shadows && eff.shadowsEnabled && eff.keyEnabled
    this.environment.setShadows(shadowsOn, tier.shadowMapSize)
    this.contactShadow?.setRealtimeShadow(shadowsOn)

    // 阴影贴图只在必要时重渲: 主光角度/阴影开关变了才有新内容, 浓度/柔度是
    // 着色期 uniform 不进贴图(three 实现细节, 已核实)
    const meta = changedKey ? FIELD_BY_KEY.get(changedKey) : null
    if (!changedKey || meta?.invalidatesShadows) this.invalidateShadows()
  }

  /**
   * 功能: 把当前背景罩体允许的最大轨道距离喂给相机.
   *
   *       实验室背景是一个封闭罩, 相机退到罩外就会看穿它(旧版"缩到最小必穿帮"的根因).
   *       上限由 LaboratoryBackground 从罩体剖面反推, 这里只负责接线. 轨道中心会被
   *       flyToStation/focusObjects 移到设备各处, 所以按整机外接球半径给出最大离轴量,
   *       取最保守的一档. 默认背景是屏幕空间渐变, 无罩体约束, 返回 null 即解除限制.
   * @returns {void}
   */
  _syncCameraEnclosure() {
    if (!this.environment || !this.cameraRig) return
    const rig = this.cameraRig
    rig.setEnclosure(this.environment.getEnclosureDistance(rig.modelCenter.y, rig.modelRadius))
  }

  /**
   * 功能: 面板写入一个设置项(经 clamp 与稀疏覆盖), 必要时启动被动负载测量.
   * @param {string} key 字段名
   * @param {*} value 新值(null 表示清除覆盖回到基准)
   * @returns {*} 生效后的值
   */
  _setDisplay(key, value) {
    const meta = FIELD_BY_KEY.get(key)
    if (!meta || this.disposed) return null
    if (meta.scope === 'global') return this._setBackgroundScene(value)
    const prev = this._effectiveDisplay()
    setOverride(this.displayState, key, value)
    // 调回与基准相等的值不留覆盖 —— 保持稀疏, 以后再校默认值时不被旧存档钉住
    const slot = this.displayState.overrides
    if (key in slot && slot[key] === this._displayBaseline(getTheme())[key]) delete slot[key]
    saveDisplayState(window.localStorage, this.displayState)
    const next = this._effectiveDisplay()

    // 被动增量测量: 在切换生效前快照基线, recompile 尖峰落进 settle 丢弃窗
    if (meta.type === 'toggle' && meta.measurable === 'passive' && prev[key] !== next[key]) {
      this._startPassiveProbe(meta, Boolean(next[key]))
    }
    this._applyDisplaySettings(key)
    return next[key]
  }

  // -- 负载测量 -----------------------------------------------------------

  /**
   * 功能: 启动被动增量测量(扳开关触发): 记切换前中位数为基线, 清窗重采.
   * @param {object} meta 字段元数据
   * @param {boolean} turningOn 本次是开还是关
   * @returns {void}
   */
  _startPassiveProbe(meta, turningOn) {
    this._abortPassiveProbe()
    const metric = this.gpuMeter.gpuAvailable ? 'gpu' : 'cpu'
    const snap = this.gpuMeter.snapshot()
    const before = metric === 'gpu' ? snap.gpuMs : snap.frameMs
    // 窗口还没热(刚进页面/刚切档)就扳开关: 这次不测, 下次扳还有机会
    if (before === null || snap.samples < 15) return
    this.gpuMeter.reset()
    this._probe = new DeltaProbe({})
    this._probe.start(before)
    this._probeInfo = { key: meta.key, label: meta.label, turningOn, metric }
  }

  /**
   * 功能: 中止在飞的被动测量.
   * @returns {void}
   */
  _abortPassiveProbe() {
    this._probe?.abort()
    this._probe = null
    this._probeInfo = null
  }

  /**
   * 功能: 主动测量实时阴影的开销. 按需阴影静止时不渲阴影 pass, 被动式测不到 ——
   *       这里双相(当前状态/翻转状态)都强制逐帧重渲再取差值, 结果标注"仅运动帧".
   * @returns {boolean} 是否成功启动
   */
  measureShadows() {
    if (this._shadowMeasure || this.disposed) return false
    const tier = QUALITY_TIERS[this.quality]
    if (!tier.shadows) return false
    const eff = this._effectiveDisplay()
    const unhook = this.addFrameHook(() => {
      this.renderer.shadowMap.needsUpdate = true
    })
    this.gpuMeter.reset()
    this._shadowMeasure = {
      phase: 'A',
      metric: this.gpuMeter.gpuAvailable ? 'gpu' : 'cpu',
      unhook,
      originalOn: Boolean(tier.shadows && eff.shadowsEnabled),
      probe: new DeltaProbe({}),
      medianA: null,
    }
    this._shadowMeasure.probe.start(0)
    return true
  }

  /**
   * 功能: 每帧推进在飞的负载测量(被动 probe 与阴影双相测量).
   * @returns {void}
   */
  _tickMeasurement() {
    if (this._probe && this._probeInfo) {
      const sample = this._probeInfo.metric === 'gpu' ? this.gpuMeter.lastGpuMs : this.gpuMeter.lastCpuMs
      const result = this._probe.tick(sample)
      if (result.phase === 'done') {
        if (result.deltaMs !== null) {
          // 方向归一: "关掉后省了 X" 与 "打开后多了 X" 都记为该项的开销 X
          const cost = Math.max(this._probeInfo.turningOn ? result.deltaMs : -result.deltaMs, 0)
          this._loadCache.set(this._probeInfo.key, {
            key: this._probeInfo.key,
            label: this._probeInfo.label,
            deltaMs: cost,
            pct: cost / 16.7,
          })
        }
        this._probe = null
        this._probeInfo = null
      }
    }

    const sm = this._shadowMeasure
    if (sm) {
      const sample = sm.metric === 'gpu' ? this.gpuMeter.lastGpuMs : this.gpuMeter.lastCpuMs
      const result = sm.probe.tick(sample)
      if (result.phase === 'done') {
        if (sm.phase === 'A') {
          sm.medianA = result.afterMedian
          sm.phase = 'B'
          this.environment.setShadows(!sm.originalOn, QUALITY_TIERS[this.quality].shadowMapSize)
          this.gpuMeter.reset()
          sm.probe = new DeltaProbe({})
          sm.probe.start(0)
        } else {
          this._finishShadowMeasure(result.afterMedian)
        }
      }
    }
  }

  /**
   * 功能: 阴影测量收尾 —— 恢复用户原开关状态, 计算并缓存开销.
   * @param {number|null} medianB 翻转状态的中位数
   * @returns {void}
   */
  _finishShadowMeasure(medianB) {
    const sm = this._shadowMeasure
    if (!sm) return
    sm.unhook()
    this._shadowMeasure = null
    this._applyDisplaySettings('shadowsEnabled')
    if (sm.medianA !== null && medianB !== null) {
      const withOn = sm.originalOn ? sm.medianA : medianB
      const withOff = sm.originalOn ? medianB : sm.medianA
      const cost = Math.max(withOn - withOff, 0)
      this._loadCache.set('shadowsEnabled', {
        key: 'shadowsEnabled',
        label: '实时阴影',
        deltaMs: cost,
        pct: cost / 16.7,
        note: '仅运动帧',
      })
    }
  }

  /**
   * 功能: 中止阴影测量并恢复现场.
   * @returns {void}
   */
  _abortShadowMeasure() {
    const sm = this._shadowMeasure
    if (!sm) return
    sm.probe.abort()
    sm.unhook()
    this._shadowMeasure = null
    this._applyDisplaySettings('shadowsEnabled')
  }

  /**
   * 功能: 作废全部测量态(档位/主题/尺寸变化后, 旧口径的样本与缓存都不再可比).
   * @returns {void}
   */
  _resetMeasurement() {
    this._abortPassiveProbe()
    this._abortShadowMeasure()
    this._loadCache?.clear()
    this.gpuMeter?.reset()
  }

  /**
   * 功能: 切换画质档位并重建后期链.
   * @param {keyof typeof QUALITY_TIERS} quality 档位名
   * @returns {void}
   */
  setQuality(quality) {
    if (!QUALITY_TIERS[quality] || quality === this.quality || this.disposed) return
    // 档位一换, 负载测量的口径全变: 缓存与在飞测量作废(要在重建效果链之前中止)
    this._resetMeasurement()
    this.quality = quality
    this._buildEffects()
    this.resize()
    // 手动切档后重置降档计时, 避免刚切上去又被判定为低帧率
    this._lowFpsSince = 0
  }

  /**
   * 功能: 异步加载整机模型, 完成后自动取景.
   * @param {string} url 模型地址
   * @param {(fraction: number) => void} [onProgress] 加载进度回调
   * @returns {Promise<object>} 含 stats/unit/loadMs/box 的加载结果
   */
  async loadMachineModel(url, onProgress) {
    const result = await loadMachine({ url, onProgress })
    if (this.disposed) {
      // 加载期间组件已卸载: 立刻释放, 不要把资源挂进场景
      disposeObject(result.root)
      return result
    }

    this.unloadMachineModel()
    this.machineRoot = result.root
    this.nodeIndex = result.nodeIndex
    this.modelStats = result.stats
    this.scene.add(result.root)

    // 阴影标志与金属反射增强在同一次遍历里做:
    //   - 透明件(玻璃罩/透射材质)不投影, 否则罩子底下一片死黑;
    //   - 金属件收集起来交给 environment 做显式 envMap 增强(见其注释).
    const boostMaterials = new Set()
    result.root.traverse((node) => {
      if (!node.isMesh) return
      const material = node.material
      const ghost = Boolean(material) && (material.transmission > 0 || material.opacity < 0.5)
      node.castShadow = !ghost
      // 机械臂官方连杆(CR5_*)不接收投影: 大半径软阴影落在光顺壳体上会糊成
      // "脏渐变"(自遮挡与机架投影皆然), 深灰大臂上尤其像污渍; 官方产品渲染
      // 的通行处理就是本体不受影, 只保留它对地面/设备的投影.
      node.receiveShadow = !node.name.startsWith('CR5_')
      if (material && material.metalness >= ENV_BOOST_METALNESS) boostMaterials.add(material)
    })
    this.environment.registerEnvBoost(boostMaterials)

    const framed = this.cameraRig.frameObject(result.root, false)
    // 雾距随整机尺度与主题倍率自适应(雾太近会把网格洗掉, 这是浅色主题的实测教训)
    this.environment.applyFogRange(framed.radius)
    // 房间尺寸/中心与安全边界必须使用同一份世界坐标包围盒。
    this.environment.fitBackgroundToModel(this.cameraRig.modelBox)
    // 罩体尺寸随整机重算完毕, 相机退让上限必须跟着重设(frameObject 刚把它复位过)
    this._syncCameraEnclosure()
    // 影子相机按整机包围盒收紧, 同样的 2048 贴图覆盖范围越小越锐利
    this.environment.fitShadowToModel(this.cameraRig.modelBox)

    // 两个烘焙按序执行(都以"藏全场只留整机"的方式抢渲染器, 不可重入):
    // 接触阴影先、倒影后; 最后挂起一次实时阴影重渲
    this.contactShadow.bake(result.root, this.cameraRig.modelBox)
    this.groundReflection.bake(result.root, this.cameraRig.modelBox)
    this.invalidateShadows()

    return { ...result, box: framed }
  }

  /**
   * 功能: 建立状态绑定层与拾取控制器. 需在模型加载完成后调用.
   *
   * @param {object} manifest device-manifest.json 内容
   * @param {import('../bindings/TwinFeed.js').TwinFeed} feed 数据源
   * @param {object} [handlers] 交互回调
   * @param {(id: string|null) => void} [handlers.onHover] 悬停
   * @param {(id: string|null) => void} [handlers.onSelect] 选中
   * @returns {{missing: string[]}} 绑定结果(含未命中的节点路径)
   */
  attachBindings(manifest, feed, handlers = {}, { picking = true, plates = false } = {}) {
    if (!this.machineRoot) throw new Error('请先加载模型再建立绑定')

    // flyToStation 要按 stations[].camera.manual 分流取景, 得自己拿得到 manifest。
    // (_effectivePlate 里那句 this.manifest?.plateSpec 一直读的是 undefined —— 现产物没有
    //  plateSpec 这个键, 所以补上这行对薄层板规格零影响, 仍走 2.0/1.0 的缺省。)
    this.manifest = manifest
    this.bindings = new TwinBindings(manifest, this.nodeIndex, feed)

    // 在制物料层是 opt-in 的: SceneManager 被五个工作台共用(装配/材质/动作/标定/实时),
    // 只有实时孪生页需要在制板、料仓堆叠与在途托盘, 装配台与材质台要的是 CAD 原貌。
    // 两者同一个开关: TwinView 是 /3d/live 的唯一宿主, 它们永远同开同关。
    if (plates) {
      this._attachPlates(manifest, feed)
      this._attachTrays(manifest, feed)
    }

    // 辉光只作用于状态灯: 设备本体不发光, 信息才不会被糊掉
    this.effects?.setBloomTargets(this.bindings.getBloomTargets())

    // 工位不走 OutlineEffect 描边(产品决策: 选中反馈只有详情面板与柜内工位的
    // 外壳透视, 悬停反馈是光标与 HUD). 技术上若要重开描边, 必须传真实网格数组
    // (postprocessing 的 Selection 不递归 Group, 塞工位根 Group 画不出任何东西),
    // 且描边器在选择集非空期间每帧多做一次全场景深度重绘. 描边链本身保留,
    // 材质台传网格数组的用法不受影响.
    // picking=false 供标定页这类"不需要工位交互"的宿主关掉拾取(帧钩子与
    // flyToStation 对 picker 均已 null 安全).
    this.picker = picking
      ? new PickController({
          domElement: this.canvas,
          camera: this.camera,
          stationRoots: this.bindings.stationRoots,
          onHover: (stationId) => {
            handlers.onHover?.(stationId)
          },
          onSelect: (stationId) => {
            // 只有柜内工位需要淡化外壳露出机构, 台面上的工位淡化只会虚化桌面
            this.bindings?.setEnclosureTransparent(ENCLOSED_STATIONS.has(stationId))
            handlers.onSelect?.(stationId)
          },
          onActivate: (stationId) => this.flyToStation(stationId),
        })
      : null

    this._unhookBindings = this.addFrameHook((delta) => {
      this.picker?.update()
      this.bindings?.update(delta)
      // 绑定层这一帧真的动了东西(轴/机器人/液面/外壳)才重渲阴影;
      // 目标值收敛后 moved 不再置位, 阴影自动回到零开销
      if (this.bindings?.consumeMoved()) this.invalidateShadows()
      // 塔灯首次被实时数据接管时重放辉光选集(整个生命周期只发生一次)
      if (this.bindings?.consumeBloomDirty()) {
        this.effects?.setBloomTargets(this.bindings.getBloomTargets())
      }
      if (this.plates) {
        this._syncPlateMagazines()
        if (this.plates.update(delta)) this.invalidateShadows()
      }
      if (this.trays) {
        if (this.trays.update(delta)) this.invalidateShadows()
        // 在途接管集合变了才回传, 免得每帧都让 TwinBindings 重算一遍显隐
        if (this.trays.consumeOwnedDirty()) this.bindings?.setTransitOwned(this.trays.owned)
      }
    })

    return { missing: this.bindings.missing, plates: this.plates?.status()?.missingAnchors || [] }
  }

  /**
   * 功能: 建薄层板层 —— 程序化分层板 + 料仓 InstancedMesh 堆叠.
   *
   * 玻璃材质从 CAD 锚点的原材质**克隆**派生(硬约束 12: MAT_GLASS_FFFFFF 被 8 个缸盖
   * 石英玻璃共用, 直接改会波及整机); 拿不到就退回自建, 语义一样安全。
   * @param {object} manifest device-manifest
   * @param {object} feed TwinFeed
   * @returns {void}
   */
  _attachPlates(manifest, feed) {
    let glassSource = null
    for (const node of this.nodeIndex.values()) {
      const name = node?.userData?.origName || node?.name || ''
      if (name.startsWith('玻璃-') && node.isMesh && node.material) {
        glassSource = node.material
        break
      }
    }
    this.plateLayer = new PlateFaceLayer({ glassSource })
    this.plates = new PlateBinding({
      manifest,
      nodeIndex: this.nodeIndex,
      layer: this.plateLayer,
      getMountedTool: () => feed?.mountedTool ?? 0,
      // 吸盘真空位: 刷新后重建"手上有板"的唯一依据。取值时机是安全的 —— 帧循环里
      // bindings.update(delta) 内部会先 feed.sampleMechanismStates(), 排在
      // plates.update(delta) 之前, 所以板层读到的永远是本帧的真空位。
      getSuctionHeld: () => Boolean(feed?.suctionHeld),
      // 6X 活轴值: 点样段 RUNNING 时色带随扫线渐进(只在那几秒里被读)
      // 走 feed 的实例时钟: 回放下 Date.now() 是墙钟, 会让这一路取样与其余通道错位
      getAxisMm: (axisId) => feed?.axisPose?.sample?.(feed.now?.() ?? Date.now())
        ?.positions?.[axisId] ?? null,
      root: this.machineRoot,                       // 接触判据的可碰几何来源
    })
    // 料仓堆叠改由板层用 InstancedMesh 承担, 让 TwinBindings 停掉逐张 clone 的旧路径
    // (两边同时画会出现双份板堆)
    this.bindings?.delegateMagazines?.(true)
    // 板层刚建好, 登记进设置面板的消费者集合(登记即灌一遍已存的覆盖)
    this._unregisterLivePlates?.()
    this._unregisterLivePlates = this.registerPlateConsumer({
      layer: this.plateLayer, stage: this.plates,
    })
    /** @type {Record<string, number>} 现场实测堆叠节距(米); 由宿主从 /api/feedlift/calib 灌入 */
    this._platePitchM = {}
    this._plateStackApplied = {}
  }

  /**
   * 功能: 建在途载荷层 —— 托盘/耗材件跟着夹爪走.
   *
   * 与板层的区别: 板层自己造几何(程序化分层板), 本层直接飞 CAD 里那些 INV_* 刚体,
   * 因为托盘与耗材在整机模型里本来就是齐全的正式零件, 位置也是设计位, 没有再造一份的理由。
   * @param {object} manifest device-manifest
   * @param {object} feed TwinFeed
   * @returns {void}
   */
  _attachTrays(manifest, feed) {
    this.trays = new TrayBinding({
      manifest,
      // 与 TwinBindings 共用同一套路径解析(含"整路径打不中就退回按叶子名找"的兜底),
      // 免得优化后的模型层级塌陷时两处各自失配
      resolve: (path) => this.bindings?.resolveNode(path),
      feed,
    })
    this.bindings?.setTransitOwned(this.trays.owned)
  }

  /**
   * 功能: 设置某料仓的现场实测堆叠节距.
   *
   * 为什么不用板的名义厚度: 三维堆高必须与真机 `feedlift.probe_stack` 的板数换算同源 ——
   * 那边是靠 `(z_empty − z_trigger) / pitch_mm` 反算张数的。出厂 pitch_mm 是 0(未标定),
   * 此时板层自己回退到"玻璃 + 硅胶"的总厚。
   * @param {string} magazineId 'feed' | 'waste'
   * @param {number} pitchM 节距(米); 0 或负数表示未标定
   * @returns {void}
   */
  setPlateStackPitch(magazineId, pitchM) {
    if (!this.plates) return
    this._platePitchM[String(magazineId)] = Number(pitchM) > 0 ? Number(pitchM) : 0
    delete this._plateStackApplied[String(magazineId)]
  }

  /** 每帧把料仓张数从物料账本透传给板层(变了才写)。 */
  _syncPlateMagazines() {
    const snapshot = this.bindings?.magazineSnapshot?.() || {}
    for (const id of ['feed', 'waste']) {
      const count = Number(snapshot[id]?.count) || 0
      const pitch = this._platePitchM[id] || 0
      const key = `${count}|${pitch}`
      if (this._plateStackApplied[id] === key) continue
      this._plateStackApplied[id] = key
      this.plates.setMagazine(id, count, pitch)
    }
  }

  /**
   * 功能: 飞入某个工位(左栏点击与画布双击共用这一条).
   *
   * 两种取景, 按 manifest 里有没有人工设过机位分流:
   *   ① `camera.manual` 为真 —— 用「显示 → 模块视角设定」存下来的机位, 原样飞过去;
   *   ② 否则 —— 框住工位的**实时**包围盒。不能拿管线自动烘的静态机位当缺省:
   *      机械臂骑着地轨滑座移动, 生成时刻的机位会对准早已人去楼空的位置;
   *      fitToBox 保持方位角只推近/平移, 也不会出现"强制转成俯视"的突兀运镜。
   * @param {string} stationId 工位 id
   * @returns {void}
   */
  flyToStation(stationId) {
    // 开场动画 interlock: 双击经 PickController 绕过 controls.enabled, 这里是唯一闸口.
    // 先中止(材质/克隆层即刻还原)再飞入, 飞入运镜紧接着接管相机
    if (this.intro?.isRunning()) this.intro.abort({ snapCamera: false })
    this._stopAutoRotate()
    const station = (this.manifest?.stations || []).find((item) => item.id === stationId)
    if (station?.camera?.manual && station.camera.pos && station.camera.target) {
      this.cameraRig.flyTo(station.camera, true)
      return
    }
    const root = this.bindings?.getStationRoot(stationId)
    if (root) this.cameraRig.fitToObjects([root], true)
  }

  /**
   * 功能: 聚焦到一组具体节点(点「运动轴」或「气缸开合」里的名字时用).
   *
   * 与 flyToStation 共用同一套闸口(开场中止 + 停环绕), 免得多一条相机路径就多一处漏判。
   * @param {THREE.Object3D[]} objects 目标节点(联动机构是多个)
   * @returns {void}
   */
  focusObjects(objects) {
    const list = (objects || []).filter(Boolean)
    if (!list.length) return
    if (this.intro?.isRunning()) this.intro.abort({ snapCamera: false })
    this._stopAutoRotate()
    this.cameraRig.fitToObjects(list, true)
  }

  /**
   * 功能: 开关自动环绕(HUD「环绕」钮; 用户一动相机会经 controlstart 自动关闭).
   * @param {boolean} on 是否开启
   * @returns {void}
   */
  setAutoRotate(on) {
    this.autoRotate = !!on
  }

  /**
   * 功能: 停掉自动环绕并通知 UI 同步高亮.
   *
   * 为什么程序化运镜也得显式调它: `fitToBox` / `setLookAt` 走的是**程序化**路径,
   * camera-controls 刻意不为它们派发 controlstart(见构造函数里那条注释), 于是环绕会
   * 活过整个飞入动作, 落位后立刻又把相机推离目标。setAutoRotate 只改字段不发回调,
   * 直接用它会让工具栏「环绕」钮停在高亮态与实际状态脱钩, 所以这里单独一份。
   * @returns {void}
   */
  _stopAutoRotate() {
    if (!this.autoRotate) return
    this.autoRotate = false
    this.onAutoRotateChange?.(false)
  }

  /**
   * 功能: 只拆实时绑定与拾取, 保留已加载的模型.
   *
   * 动作工作台的三个子页共用同一份模型, 但只有标定子页需要实时链: 切走时必须
   * 把绑定拆干净(否则 feed 会继续覆写轴, 与运动模式的手动驱动抢写), 又不能连
   * 模型一起卸掉(重新解析 14 MB GLB 是秒级停顿). unloadMachineModel 复用本方法
   * 保证两条路径的拆序完全一致.
   * @returns {void}
   */
  detachBindings() {
    // 开场动画依赖模型与材质在场, 拆绑定/卸模型前先清(还原裁剪面、撤克隆层)
    this.intro?.dispose()
    this.intro = null
    this._unhookBindings?.()
    this._unhookBindings = null
    this.picker?.dispose()
    this.picker = null
    // 板层必须排在 disposeObject 之前: 它的实例网格挂在模型子树上, 先拆干净才不会
    // 被连坐 dispose(与 clearEnvBoost 摘 envMap 同理)
    this.plates?.dispose()
    this.plates = null
    this.plateLayer?.dispose()
    this.plateLayer = null
    // 在途层同理: 它把 CAD 托盘换父挂到了 TOOL_MOUNT 下, 不还回原父级就会随机械臂
    // 一起被释放, 下次加载时那些托盘节点就没了
    this.trays?.dispose()
    this.trays = null
    this.bindings?.dispose()
    this.bindings = null
    // 辉光选集里全是绑定层给的状态灯网格, 绑定没了就得清空, 否则后期指着已释放的对象
    this.effects?.setBloomTargets([])
  }

  /**
   * 功能: 从场景移除并彻底释放整机模型与依赖它的绑定/拾取.
   * @returns {void}
   */
  unloadMachineModel() {
    this.detachBindings()
    this.contactShadow?.clear()
    this.groundReflection?.clear()
    // 必须先解除金属材质的显式 envMap 再 disposeObject:
    // 那里会 dispose 材质上一切纹理, 不摘掉会把共享的 PMREM 环境贴图一起杀掉
    this.environment?.clearEnvBoost()

    if (!this.machineRoot) return
    this.scene.remove(this.machineRoot)
    disposeObject(this.machineRoot)
    this.machineRoot = null
    this.nodeIndex = new Map()
    this.modelStats = null
  }

  /**
   * 功能: 按 device-manifest 里的节点路径取对象.
   * @param {string} path 节点路径, 如 "ST_SAMPLING/AXIS_4X/CARRIAGE"
   * @returns {THREE.Object3D|undefined} 命中的对象
   */
  getNode(path) {
    return this.nodeIndex.get(path)
  }

  /**
   * 功能: 注册每帧回调(状态绑定层用它把遥测数据写进场景).
   * @param {(delta: number, elapsed: number) => void} hook 帧回调
   * @returns {() => void} 取消注册的函数
   */
  addFrameHook(hook) {
    this.frameHooks.push(hook)
    return () => {
      const index = this.frameHooks.indexOf(hook)
      if (index >= 0) this.frameHooks.splice(index, 1)
    }
  }

  // -- 渲染循环 -----------------------------------------------------------

  /**
   * 功能: 启动渲染循环(重复调用无副作用).
   * @returns {void}
   */
  start() {
    if (this.rafId || this.disposed || this.contextLost) return
    this.clock.start()
    const loop = () => {
      this.rafId = requestAnimationFrame(loop)
      this._renderFrame()
    }
    this.rafId = requestAnimationFrame(loop)
  }

  /**
   * 功能: 停止渲染循环.
   * @returns {void}
   */
  stop() {
    if (!this.rafId) return
    cancelAnimationFrame(this.rafId)
    this.rafId = 0
    this.clock.stop()
  }

  /**
   * 功能: 渲染单帧 —— 推进相机阻尼、执行帧回调、出图、统计帧率.
   * @returns {void}
   */
  _renderFrame() {
    const delta = this.clock.getDelta()
    const elapsed = this.clock.elapsedTime

    // 自动环绕: 直接推方位角(0.12 rad/s, 与预览沙盒同手感); 开场动画期间让位.
    // delta 钳位: 后台标签页恢复/主线程卡顿时 getDelta 会给出秒级值, 不钳会跳视角
    if (this.autoRotate && !this.intro?.isRunning()) {
      this.cameraRig.controls.azimuthAngle += Math.min(delta, 0.1) * 0.12
    }
    this.cameraRig.update(delta)
    // 默认舞台的雾距跟着轨道距离走(见 Environment.FOG_NEAR_CLEARANCE):
    // 相机距离能变一百倍, 固定雾距在远景会把整机整个洗进雾色
    this.environment.updateFogForDistance(this.cameraRig.controls.distance)
    // 帧钩子吃的 delta 必须乘播放倍速。所有按时间积分的东西都挂在这一条上:
    // interp 的指数追赶、PumpSyringeModel/TankLiquidModel 的 elapsed += delta、
    // updateSpindles、plates/trays 的补间、_updateEnclosure。回放若只换了
    // sample(nowMs) 的时钟而不动这里, 事件按 4 倍速到达、积分器仍按墙钟走, 画面会
    // 逐渐撕裂 —— 一行乘法在这里就把所有消费者一次性覆盖掉。
    // 回放下还要钳位: 切后台标签页回来时 getDelta 给出秒级值, 实时模式大体自愈,
    // 回放模式会让积分器越过事件流并一直错到下一个包络。
    const scaled = this.timeScale === 1
      ? delta
      : Math.min(delta, this.maxFrameDelta) * this.timeScale
    for (const hook of this.frameHooks) hook(scaled, elapsed)

    this.renderer.info.reset()
    this.gpuMeter.beginFrame()
    if (this.effects) this.effects.render(delta)
    else this.renderer.render(this.scene, this.camera)
    this.gpuMeter.endFrame()
    // 后期处理的全屏三角形也计入了统计, 这里扣掉以还原场景本身的开销
    this._lastRenderInfo = {
      calls: Math.max(this.renderer.info.render.calls - (this.effects ? 1 : 0), 0),
      triangles: Math.max(this.renderer.info.render.triangles - (this.effects ? 1 : 0), 0),
    }

    this._tickMeasurement()
    this._tickStats()
  }

  /**
   * 功能: 每秒汇总一次帧率与绘制调用, 必要时触发自动降档.
   * @returns {void}
   */
  _tickStats() {
    this.frameCount += 1
    const now = performance.now()
    const windowMs = now - this._fpsWindowStart
    if (windowMs < 1000) return

    this.fps = Math.round((this.frameCount * 1000) / windowMs)
    this.frameCount = 0
    this._fpsWindowStart = now

    if (this.onStats) {
      const meter = this.gpuMeter.snapshot()
      this.onStats({
        fps: this.fps,
        quality: this.quality,
        drawCalls: this._lastRenderInfo?.calls ?? 0,
        triangles: this._lastRenderInfo?.triangles ?? 0,
        geometries: this.renderer.info.memory.geometries,
        textures: this.renderer.info.memory.textures,
        pixelRatio: this.renderer.getPixelRatio(),
        // 负载指标: frameMs 是 render 调用的 CPU 提交耗时, gpuMs 是真 GPU 耗时
        // (仅支持计时扩展的浏览器), 面板据此画负载条与增量列表
        frameMs: meter.frameMs,
        gpuMs: meter.gpuMs,
        gpuAvailable: meter.gpuAvailable,
        measuring: this._probeInfo?.key || (this._shadowMeasure ? 'shadowsEnabled' : null),
        loadDeltas: [...this._loadCache.values()],
      })
    }

    this._maybeDegrade(now)
  }

  /**
   * 功能: 帧率持续低于阈值时自动降一档画质.
   * @param {number} now 当前时间戳(毫秒)
   * @returns {void}
   */
  _maybeDegrade(now) {
    if (!this.autoDegrade) return
    const order = ['high', 'medium', 'low']
    const current = order.indexOf(this.quality)
    // lite 等专用档不在降档序列里, indexOf 为 -1 时 order[current+1] 会取到
    // 'high' 反向升档 —— 序列外的档位不参与自动降档
    if (current < 0) return
    if (current >= order.length - 1) return

    if (this.fps >= DEGRADE_FPS_THRESHOLD) {
      this._lowFpsSince = 0
      return
    }
    if (!this._lowFpsSince) {
      this._lowFpsSince = now
      return
    }
    if (now - this._lowFpsSince >= DEGRADE_SUSTAIN_MS) {
      const next = order[current + 1]
      console.info(`[twin] 帧率持续低于 ${DEGRADE_FPS_THRESHOLD}, 自动降档: ${this.quality} -> ${next}`)
      this.setQuality(next)
    }
  }

  // -- 生命周期 -----------------------------------------------------------

  /**
   * 功能: 彻底释放本管理器持有的全部资源. 调用后实例不可再用.
   * @returns {void}
   */
  dispose() {
    if (this.disposed) return
    this.disposed = true

    this.stop()
    this._resetMeasurement()
    this.gpuMeter?.dispose()
    this.gpuMeter = null
    this.frameHooks.length = 0

    this._resizeObserver?.disconnect()
    document.removeEventListener('visibilitychange', this._onVisibility)
    this.canvas.removeEventListener('webglcontextlost', this._onContextLost)
    this.canvas.removeEventListener('webglcontextrestored', this._onContextRestored)

    this.unloadMachineModel()
    this._offTheme?.()
    this._offTheme = null
    this.contactShadow?.dispose()
    this.contactShadow = null
    this.groundReflection?.dispose()
    this.groundReflection = null
    this.cameraRig.controls.removeEventListener('controlstart', this._onUserControl)
    this.cameraRig.dispose()
    this.effects?.dispose()
    this.disposeEnvironment()

    this.renderer.dispose()
    // forceContextLoss 让驱动立刻回收上下文, 否则浏览器可能延迟很久才释放显存
    this.renderer.forceContextLoss?.()
    this.canvas.parentNode?.removeChild(this.canvas)

    this.scene = null
    this.effects = null
    this.machineRoot = null
    this.nodeIndex = new Map()
  }
}

export { collectStats }
