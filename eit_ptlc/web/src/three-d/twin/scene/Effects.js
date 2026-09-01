/**
 * 功能: 后期处理管线 —— SSAO、选择性辉光(状态灯)、悬停/选中描边、抗锯齿与色调映射.
 *
 * 选用 pmndrs/postprocessing 而非 three/examples 的 EffectComposer:
 *   - 自带 SelectiveBloomEffect / OutlineEffect, 三/examples 需要靠 layers 技巧且
 *     OutlinePass 会额外整场景重绘一遍, 是已知的性能陷阱;
 *   - 多个 Effect 会被合并进同一个全屏 Pass, 明显少几趟带宽.
 *
 * 视觉约定:
 *   - 辉光只作用于状态灯(自发光小面片), 设备本体不参与, 保证信息可读不糊;
 *   - 选中描边用主题强调色且**常驻**(2026-08-02 用户定夺: 旋转/缩放/运镜期间
 *     不隐藏, 只在点击空白取消选中时消失); 悬停描边已取消(描边不跟随鼠标,
 *     点击选中后才显示 —— 顺带每帧少一次全场景深度+掩码 pass);
 *   - SSAO(2026-08-01 影棚化新增)负责零件缝隙与机架内部的暗部 —— 两千个零件互相
 *     插接的设备没有 AO 就是"贴纸感"的直接来源. 代价是 NormalPass 要把场景按法线
 *     重绘一遍(几何 pass ×2), 只在 high 档开.
 */
import * as THREE from 'three'
import {
  BlendFunction,
  EffectComposer,
  EffectPass,
  NormalPass,
  OutlineEffect,
  RenderPass,
  SMAAEffect,
  SSAOEffect,
  SelectiveBloomEffect,
  ToneMappingEffect,
  ToneMappingMode,
  VignetteEffect,
} from 'postprocessing'

import { getTheme } from '../../theme.js'

/**
 * 描边配色, 分昼夜两组: 深色主题选中湖蓝; 冷色描边在浅色背景上不可见, 浅色主题
 * 换成加深的蓝. hidden 是被遮挡部分的描边色(x-ray 时可见).
 * (悬停描边 2026-08-02 已取消, hover 色随之移除 —— 只保留点击选中描边.)
 */
export const OUTLINE_COLORS = {
  dark: {
    selected: 0x36d1ff,
    selectedHidden: 0x10405a,
  },
  light: {
    selected: 0x0899cc,
    selectedHidden: 0x9cccdf,
  },
}

/** 可实时调的效果参数默认值(显示设置面板的基准来源) */
export const EFFECT_DEFAULTS = {
  // 2.0 → 1.4: postprocessing 的 SSAO 没有降噪 pass, intensity 对噪声是线性放大器
  // (合成端 ao=clamp(ao*intensity)), 2.0 会把采样噪声推成整面"麻点"(2026-08-01
  // 对照矩阵目检实锤: 只关 SSAO 麻点即消失, 阴影/量化均未命中)
  ssaoIntensity: 1.4,
  vignetteOffset: 0.3,
  vignetteDarkness: 0.25,
}

export class Effects {
  /**
   * 功能: 建立后期处理链.
   * @param {THREE.WebGLRenderer} renderer 渲染器
   * @param {THREE.Scene} scene 场景
   * @param {THREE.Camera} camera 相机
   * @param {object} [options] 可选项
   * @param {boolean} [options.bloom=true] 是否启用辉光
   * @param {boolean} [options.outline=true] 是否启用描边
   * @param {boolean} [options.smaa=true] 是否启用抗锯齿
   * @param {boolean} [options.ssao=false] 是否启用环境光遮蔽(带 NormalPass 几何重绘)
   * @param {boolean} [options.vignette=false] 是否启用暗角
   */
  constructor(renderer, scene, camera, options = {}) {
    const { bloom = true, outline = true, smaa = true, ssao = false, vignette = false } = options

    this.renderer = renderer
    this.scene = scene
    this.camera = camera
    this.enabledFeatures = { bloom, outline, smaa, ssao, vignette }

    this.composer = new EffectComposer(renderer, {
      // 半浮点缓冲: 辉光需要 HDR 亮度信息, 8 位缓冲会把高光削平
      frameBufferType: THREE.HalfFloatType,
    })
    this.composer.addPass(new RenderPass(scene, camera))

    /** @type {NormalPass|null} SSAO 的法线来源(整场景按法线材质重绘一遍) */
    this.normalPass = null
    if (ssao) {
      this.normalPass = new NormalPass(scene, camera)
      this.composer.addPass(this.normalPass)
    }

    /** @type {SelectiveBloomEffect|null} */
    this.bloomEffect = null
    /** @type {OutlineEffect|null} 悬停描边(2026-08-02 取消, 恒 null; 字段保留兼容调试读数) */
    this.hoverOutline = null
    /** @type {OutlineEffect|null} */
    this.selectOutline = null
    /** @type {SSAOEffect|null} */
    this.ssaoEffect = null
    /** @type {VignetteEffect|null} */
    this.vignetteEffect = null
    /**
     * 软开关状态(显示设置面板驱动, 不重建效果链):
     *   - blendFunction 换成 DST 会被 EffectPass 从合成着色器里摘除(postprocessing
     *     官方手法), 且 setter 自己会触发重编译 —— 赋值前必须同值守卫;
     *   - 但 DST 不会阻止 effect.update() 每帧照跑内部 pass(SSAO 的降采样/AO,
     *     Bloom 的亮度/mipmap 链), 所以还要经 _gated 做 update 门控才真省开销.
     */
    this._gated = new Set()
    /** @type {Map<object, number>} 各可开关 effect 的原生混合方式(恢复用) */
    this._nativeBlend = new Map()

    const effects = []

    if (ssao) {
      // 参数按"米制整机(~3m)"标定: radius 是视空间比例, world* 系列是世界空间米.
      // MULTIPLY 放在链头 —— 先把缝隙压暗, 再做辉光/描边, AO 不污染状态灯.
      // 降噪约束(库内无模糊/降噪 pass, 只能从采样端压): radius 是"相对 AO 缓冲高度
      // 的比例", 0.05 在 DPR2 下折 ~100 屏幕像素半径, 9 采样严重欠采样, 噪声再被
      // 8 位半分辨率 RT + 法线不连续处的最近邻上采样钉成硬麻点 —— 收半径 + 加采样
      // 是唯一有效杠杆, 别指望 SMAA(它只看 RenderPass 原始输出, 管不到 AO 噪声).
      this.ssaoEffect = new SSAOEffect(camera, this.normalPass.texture, {
        blendFunction: BlendFunction.MULTIPLY,
        samples: 16,
        rings: 7,
        resolutionScale: 0.5, // 半分辨率采样 + 深度感知上采样, 开销减 3/4
        depthAwareUpsampling: true,
        worldDistanceThreshold: 24,
        worldDistanceFalloff: 6,
        worldProximityThreshold: 0.08,
        worldProximityFalloff: 0.04,
        radius: 0.02,
        minRadiusScale: 0.33,
        bias: 0.025,
        fade: 0.03,
        intensity: EFFECT_DEFAULTS.ssaoIntensity,
        // 亮面少吃 AO: 白钣金是整机主体, AO 全强度会把浅色面涂脏
        luminanceInfluence: 0.7,
      })
      effects.push(this.ssaoEffect)
    }

    if (bloom) {
      this.bloomEffect = new SelectiveBloomEffect(scene, camera, {
        blendFunction: BlendFunction.ADD,
        mipmapBlur: true,
        luminanceThreshold: 0.35,
        luminanceSmoothing: 0.25,
        intensity: 1.6,
        radius: 0.62,
      })
      // 只有显式加入 selection 的对象参与辉光, 默认全场景不发光
      this.bloomEffect.inverted = false
      // 库默认 ignoreBackground=false 会把深度遮罩设成 KEEP_MAX_DEPTH: 背景像素
      // (depth==1)无条件进辉光输入, 而设备几何要 abs(d1-d0)<=1e-4 才留、选择集为空
      // 时全被 discard —— "选择性辉光"就此退化成"只给背景发光". 浅色主题背景线性
      // 亮度 0.82 远超 smoothstep(0.35,0.60) 阈值, 整片 ×1.6 叠回再大半径模糊糊过
      // 设备轮廓, 就是用户报的"平视整屏白光晕"(实测前视上半屏 214.6 -> 188.7,
      // 等轴测 0 变化 —— 等轴测地面写深度占满画面, 本就没多少背景进辉光).
      this.bloomEffect.ignoreBackground = true
      effects.push(this.bloomEffect)
    }

    if (outline) {
      // SCREEN 混合只能提亮, 在浅色主题的白底上描边会彻底消失, 故浅色改用逐像素
      // alpha 合成. 注意必须是 ALPHA 而不是 NORMAL: postprocessing 的 NORMAL 按全局
      // opacity 整屏替换, 无描边处会输出黑色 —— 表现为一切正常却整个画面全黑.
      const theme = getTheme()
      const colors = OUTLINE_COLORS[theme] || OUTLINE_COLORS.dark
      const outlineBlend = theme === 'light' ? BlendFunction.ALPHA : BlendFunction.SCREEN
      this.selectOutline = new OutlineEffect(scene, camera, {
        blendFunction: outlineBlend,
        edgeStrength: 4.0,
        pulseSpeed: 0.0,
        visibleEdgeColor: colors.selected,
        hiddenEdgeColor: colors.selectedHidden,
        blur: true,
        xRay: true,
      })
      // 悬停描边已取消(点击选中才描边): 少一个 OutlineEffect = 非空时每帧少一次
      // 全场景深度重绘 + 掩码遍历, raw 模型 2000+ 绘制调用下不是小数.
      effects.push(this.selectOutline)
    }

    // 色调映射放在链尾: 先在线性空间做辉光/描边, 最后统一映射到显示空间.
    // 用 Khronos PBR Neutral 而不是 AGX: AGX 会明显压饱和压对比, 白色机身被拍成灰蒙蒙
    // 一片(用户对照实物照片直接看出来了); Neutral 专为产品展示设计, 白就是白.
    // 影棚化的对比不靠换映射曲线, 靠光比/阴影/AO/暗角.
    effects.push(new ToneMappingEffect({ mode: ToneMappingMode.NEUTRAL ?? ToneMappingMode.ACES_FILMIC }))

    // 暗角放在色调映射之后(LDR 域): 压四角不影响辉光阈值与 AO 的亮度判断
    if (vignette) {
      this.vignetteEffect = new VignetteEffect({
        offset: EFFECT_DEFAULTS.vignetteOffset,
        darkness: EFFECT_DEFAULTS.vignetteDarkness,
      })
      effects.push(this.vignetteEffect)
    }

    if (smaa) effects.push(new SMAAEffect())

    this.composer.addPass(new EffectPass(camera, ...effects))

    // 软开关准备: 记原生混合方式 + 给"有重内部 pass"的 effect 包 update 门控
    for (const effect of [this.ssaoEffect, this.bloomEffect, this.vignetteEffect]) {
      if (effect) this._nativeBlend.set(effect, effect.blendMode.getBlendFunction())
    }
    if (this.ssaoEffect) this._gateUpdate(this.ssaoEffect)
    if (this.bloomEffect) this._gateUpdate(this.bloomEffect)
  }

  /**
   * 功能: 给 effect 的 update 包一层门控 —— 被软关的 effect 跳过内部 pass.
   * @param {object} effect 目标 effect
   * @returns {void}
   */
  _gateUpdate(effect) {
    const original = effect.update.bind(effect)
    effect.update = (...args) => {
      if (!this._gated.has(effect)) original(...args)
    }
  }

  /**
   * 功能: 软开关一个效果(不重建效果链, 无 dispose/new 的丢帧).
   *       有效状态 = 画质档位允许(链里有它) 且 用户开 —— 档位不含该效果时是 no-op.
   * @param {'ssao'|'bloom'|'vignette'} name 效果名
   * @param {boolean} on 是否启用
   * @returns {boolean} 链里是否存在该效果
   */
  setFeature(name, on) {
    const effect = { ssao: this.ssaoEffect, bloom: this.bloomEffect, vignette: this.vignetteEffect }[name]
    if (!effect) return false
    const native = this._nativeBlend.get(effect)
    const current = effect.blendMode.getBlendFunction()
    if (on) {
      // 同值守卫: setBlendFunction 会触发 EffectPass 重编译, 重复赋值就是重复编译
      if (current !== native) effect.blendMode.setBlendFunction(native)
      this._gated.delete(effect)
      if (name === 'ssao' && this.normalPass) this.normalPass.enabled = true
    } else {
      if (current !== BlendFunction.DST) effect.blendMode.setBlendFunction(BlendFunction.DST)
      this._gated.add(effect)
      // SSAO 的大头开销是 NormalPass 的整场景法线重绘, 必须一起停
      if (name === 'ssao' && this.normalPass) this.normalPass.enabled = false
    }
    return true
  }

  /**
   * 功能: AO 强度(纯 uniform, 无重编译).
   * @param {number} value 强度
   * @returns {void}
   */
  setSsaoIntensity(value) {
    if (this.ssaoEffect && Number.isFinite(value)) this.ssaoEffect.intensity = value
  }

  /**
   * 功能: 暗角参数(纯 uniform).
   * @param {number} offset 起始半径
   * @param {number} darkness 强度
   * @returns {void}
   */
  setVignette(offset, darkness) {
    if (!this.vignetteEffect) return
    if (Number.isFinite(offset)) this.vignetteEffect.offset = offset
    if (Number.isFinite(darkness)) this.vignetteEffect.darkness = darkness
  }

  /**
   * 功能: 显示设置的批量生效入口(SceneManager 合成 eff 后调用).
   * @param {object} eff 全量有效设置
   * @returns {void}
   */
  applyDisplay(eff) {
    this.setFeature('ssao', eff.ssaoEnabled)
    this.setFeature('bloom', eff.bloomEnabled)
    this.setFeature('vignette', eff.vignetteEnabled)
    this.setSsaoIntensity(eff.ssaoIntensity)
    this.setVignette(EFFECT_DEFAULTS.vignetteOffset, eff.vignetteDarkness)
  }

  /**
   * 功能: 设置参与辉光的对象集合(通常是各工位的状态灯).
   * @param {THREE.Object3D[]} objects 对象数组
   * @returns {void}
   */
  setBloomTargets(objects) {
    if (!this.bloomEffect) return
    this.bloomEffect.selection.set(objects)
  }

  /**
   * 功能: 把一个对象加入辉光集合.
   * @param {THREE.Object3D} object 目标对象
   * @returns {void}
   */
  addBloomTarget(object) {
    if (this.bloomEffect && object) this.bloomEffect.selection.add(object)
  }

  /**
   * 功能: 描边配色与混合方式随主题热切(SCREEN 在白底上不可见, 浅色主题用 NORMAL).
   *       setBlendFunction 会触发 EffectPass 重编译, 只在切主题时发生, 频率极低.
   * @param {string} theme 主题名('dark' | 'light')
   * @returns {void}
   */
  setTheme(theme) {
    const colors = OUTLINE_COLORS[theme] || OUTLINE_COLORS.dark
    const blend = theme === 'light' ? BlendFunction.ALPHA : BlendFunction.SCREEN
    if (this.selectOutline) {
      this.selectOutline.visibleEdgeColor.setHex(colors.selected)
      this.selectOutline.hiddenEdgeColor.setHex(colors.selectedHidden)
      this.selectOutline.blendMode.setBlendFunction(blend)
    }
  }

  /**
   * 功能: 设置悬停高亮的对象集合. 悬停描边已取消(2026-08-02 用户定夺), hoverOutline
   *       恒 null, 本方法是自然 no-op —— 保留 API 兼容既有清空调用.
   * @param {THREE.Object3D[]} objects 对象数组(空数组表示取消悬停)
   * @returns {void}
   */
  setHover(objects) {
    if (this.hoverOutline) this.hoverOutline.selection.set(objects || [])
  }

  /**
   * 功能: 设置选中高亮的对象集合. 描边常驻(2026-08-02 用户定夺): 旋转/缩放/
   *       运镜等一切视角调整期间不隐藏, 只随取消选中(空数组)消失.
   * @param {THREE.Object3D[]} objects 对象数组(空数组表示取消选中)
   * @returns {void}
   */
  setSelected(objects) {
    if (this.selectOutline) this.selectOutline.selection.set(objects || [])
  }

  /**
   * 功能: 同步视口尺寸.
   *
   * 第三个参数 updateStyle 必须显式传 false: 画布的 CSS 盒子归布局(SceneManager 建画布时
   * 写死 width/height 为 100%), 绘图缓冲才归尺寸同步, 任何人都不许写 canvas.style.
   * 省掉这个参数的后果是 postprocessing 原样透传 undefined 给 renderer.setSize, 触发 three
   * 那边 updateStyle = true 的默认值, 把 100% 覆盖成挂载那一刻的固定像素 —— 此后容器再变
   * 也只有缓冲跟着变, CSS 盒子永远停在旧尺寸, 表现为缩窗后画面被非等比拉伸且只能刷新恢复.
   *
   * @param {number} width 宽(像素)
   * @param {number} height 高(像素)
   * @returns {void}
   */
  resize(width, height) {
    this.composer.setSize(width, height, false)
  }

  /**
   * 功能: 渲染一帧.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  render(delta) {
    this.composer.render(delta)
  }

  /**
   * 功能: 释放后期处理占用的渲染目标等资源.
   * @returns {void}
   */
  dispose() {
    this.composer.dispose()
  }
}
