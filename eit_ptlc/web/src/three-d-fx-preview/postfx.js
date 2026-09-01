/**
 * 功能: 沙盒最小后期链 —— SelectiveBloom + Vignette + ToneMapping(NEUTRAL) [+ SMAA].
 *
 * 参数逐项对齐正式页 Effects.js(阈值/强度/半径/ignoreBackground/链序/HalfFloat 缓冲),
 * 保证沙盒里调出的 emissive/boost 数值搬进正式页不整体失真. 刻意不 import Effects.js.
 *
 * quality=low 时整链不建(与正式页 low 档"完全不走 composer"一致), renderer 的
 * 色调映射改回 NeutralToneMapping 补偿; bloom 适配器退化为 no-op —— 特效必须
 * 在无辉光下依然成立(additive 自发光就是降级形态).
 *
 * bloom 适配器内部 traverse 收真实 mesh: pmndrs 的 Selection **不递归 Group**,
 * 塞工位根 Group 会静默画不出任何东西(正式页 SceneManager 里有血泪注释).
 */
import * as THREE from 'three'
import {
  BlendFunction,
  EffectComposer,
  EffectPass,
  OutlineEffect,
  RenderPass,
  SMAAEffect,
  SelectiveBloomEffect,
  ToneMappingEffect,
  ToneMappingMode,
  VignetteEffect,
} from 'postprocessing'

/**
 * 功能: 建立后期链(或 low 档的 no-op 替身).
 * @param {object} options 参数对象
 * @param {THREE.WebGLRenderer} options.renderer 渲染器
 * @param {THREE.Scene} options.scene 场景
 * @param {THREE.Camera} options.camera 相机
 * @param {string} options.quality 'high' | 'low'
 * @param {boolean} [options.aa=true] 是否启用 SMAA
 * @param {object} options.config 运行配置(fxConfig.postfx 段)
 * @returns {object} postfx 实例
 */
export function createPostFx({ renderer, scene, camera, quality, aa = true, config, theme = 'dark' }) {
  if (quality === 'low') {
    // low 档: 无 composer, 色调映射回 renderer(与 SceneManager._buildEffects 行为一致)
    renderer.toneMapping = THREE.NeutralToneMapping
    return {
      composer: null,
      bloom: { add() {}, remove() {}, clear() {} },
      render: null,
      resize() {},
      setVignetteDarkness() {},
      setBloomIntensity() {},
      setOutline() {},
      dispose() {},
    }
  }

  renderer.toneMapping = THREE.NoToneMapping
  const composer = new EffectComposer(renderer, {
    frameBufferType: THREE.HalfFloatType, // 辉光需要 HDR 亮度, 8 位缓冲会把高光削平
  })
  composer.addPass(new RenderPass(scene, camera))

  const p = config.postfx
  const bloomEffect = new SelectiveBloomEffect(scene, camera, {
    blendFunction: BlendFunction.ADD,
    mipmapBlur: true,
    luminanceThreshold: p.bloomThreshold,
    luminanceSmoothing: 0.25,
    intensity: p.bloomIntensity,
    radius: p.bloomRadius,
  })
  bloomEffect.inverted = false
  // 不设 ignoreBackground 会退化成"只给背景发光"(正式页 Effects.js 有完整病理注释)
  bloomEffect.ignoreBackground = true

  const vignetteEffect = new VignetteEffect({
    offset: p.vignetteOffset,
    darkness: p.vignetteDarkness,
  })

  // 聚焦描边(参数照正式页 Effects.js): SCREEN 只能提亮在白底上会消失, 浅色改 ALPHA;
  // 用 NORMAL 会整屏黑 —— 正式页注释里的血泪原话
  const outlineEffect = new OutlineEffect(scene, camera, {
    blendFunction: theme === 'light' ? BlendFunction.ALPHA : BlendFunction.SCREEN,
    edgeStrength: 4.0,
    pulseSpeed: 0.0,
    visibleEdgeColor: theme === 'light' ? 0x0899cc : 0x36d1ff,
    hiddenEdgeColor: theme === 'light' ? 0x9cccdf : 0x10405a,
    blur: true,
    xRay: true,
  })

  const effects = [
    bloomEffect,
    outlineEffect,
    // 色调映射在暗角之前(链序照正式页): 线性空间做辉光/描边, NEUTRAL 映射后再压四角
    new ToneMappingEffect({ mode: ToneMappingMode.NEUTRAL ?? ToneMappingMode.ACES_FILMIC }),
    vignetteEffect,
  ]
  if (aa) effects.push(new SMAAEffect())
  composer.addPass(new EffectPass(camera, ...effects))

  /** @type {Map<THREE.Object3D, THREE.Mesh[]>} 对象 -> 展开后的真实网格(去重/可撤销) */
  const tracked = new Map()

  return {
    composer,
    bloomEffect,
    vignetteEffect,

    bloom: {
      /**
       * 功能: 把对象(或其整棵子树的网格)加入辉光选集.
       * @param {THREE.Object3D} object 目标对象
       * @returns {void}
       */
      add(object) {
        if (!object || tracked.has(object)) return
        const meshes = []
        if (object.isMesh) meshes.push(object)
        else object.traverse((node) => { if (node.isMesh) meshes.push(node) })
        for (const mesh of meshes) bloomEffect.selection.add(mesh)
        tracked.set(object, meshes)
      },
      remove(object) {
        const meshes = tracked.get(object)
        if (!meshes) return
        for (const mesh of meshes) bloomEffect.selection.delete(mesh)
        tracked.delete(object)
      },
      clear() {
        bloomEffect.selection.clear()
        tracked.clear()
      },
    },

    render(delta) {
      composer.render(delta)
    },
    resize(width, height) {
      composer.setSize(width, height)
    },
    setVignetteDarkness(value) {
      if (Number.isFinite(value)) vignetteEffect.darkness = value
    },
    setBloomIntensity(value) {
      if (Number.isFinite(value)) bloomEffect.intensity = value
    },
    /**
     * 功能: 设置描边选集(聚焦/开场点亮用). pmndrs Selection 不递归 Group,
     * 调用方必须传真实 mesh 数组(station.meshes 正是).
     * @param {THREE.Mesh[]} meshes 网格数组(空数组清除)
     * @returns {void}
     */
    setOutline(meshes) {
      outlineEffect.selection.set(meshes || [])
    },
    dispose() {
      composer.dispose()
    },
  }
}
