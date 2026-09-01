/**
 * 功能: 烘焙式地面接触阴影 —— 一次渲染出俯视软阴影贴在地面, 零每帧开销.
 *
 * 本项目刻意不用阴影贴图(性能红利), 代价是设备像飘在地上. 这里用最便宜的替代:
 * 模型加载完成后, 用正交相机从正上方把整机以灰色覆盖材质渲进一张小 RT(白底),
 * 经 Kawase 模糊得到软边剪影, 以乘法混合贴在地面上 —— 白色区域对地面无影响,
 * 灰色区域把地面压暗成阴影. 只在加载/换模型时烘一次, 之后就是一张静态贴图.
 *
 * 阴影浓度是着色器 uniform 而非烘进贴图, 因此昼夜切换只改一个数, 不用重烘.
 */
import * as THREE from 'three'
import { KawaseBlurPass, KernelSize } from 'postprocessing'

/** 烘焙分辨率: 阴影本来就要糊, 512 足够 */
const BAKE_SIZE = 512
/** 阴影平面比整机足迹外扩的比例, 给模糊留淡出空间 */
const EXPAND = 1.45
/** 接触影浓度基准(0=无, 1=全黑). 2026-08-05 昼夜统一为 0.3(用户当前所见):
 *  dark 曾单独抬到 0.32(2026-08-01 用户反馈夜间方向影与场景不贴合 —— 接触影抬一档
 *  与降浓后的方向影衔接), 而方向影本次已统一, 这一档补偿也就没了由头。
 *  两键 map 形状保留: _applyStrength 拿它做显示设置灌入前的兜底(见 setTheme)。
 *  导出供显示设置拼基准 */
export const CONTACT_STRENGTH = { dark: 0.3, light: 0.3 }
/** 实时阴影开启时的再衰减: 方向影+接触影叠加, 不降浓度会在设备底下叠出死黑 */
const REALTIME_SCALE = 0.65

/** 乘法混合的阴影着色器: 采样剪影 + 矩形边缘淡出, 输出 [shadow..1] 的灰度 */
const SHADOW_SHADER = {
  uniforms: {
    uMask: { value: null },
    uStrength: { value: CONTACT_STRENGTH.dark },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D uMask;
    uniform float uStrength;
    varying vec2 vUv;
    void main() {
      // 剪影图: 机器处为 0, 空白处为 1
      float mask = texture2D(uMask, vUv).r;
      // 距平面边缘的淡出, 保证贴图边界处阴影必然归零, 不露矩形硬边
      vec2 edge = abs(vUv - 0.5);
      float fade = 1.0 - smoothstep(0.32, 0.5, max(edge.x, edge.y));
      float shadow = 1.0 - uStrength * (1.0 - mask) * fade;
      gl_FragColor = vec4(vec3(shadow), 1.0);
    }
  `,
}

export class ContactShadow {
  /**
   * 功能: 准备烘焙管线与阴影平面(此时还没有内容, bake 后才可见).
   * @param {THREE.WebGLRenderer} renderer 渲染器
   * @param {THREE.Scene} scene 目标场景
   */
  constructor(renderer, scene) {
    this.renderer = renderer
    this.scene = scene

    /** 剪影原图与模糊结果; 都不需要深度缓冲 */
    this.maskTarget = new THREE.WebGLRenderTarget(BAKE_SIZE, BAKE_SIZE, { depthBuffer: true })
    this.blurTarget = new THREE.WebGLRenderTarget(BAKE_SIZE, BAKE_SIZE, { depthBuffer: false })

    this.blurPass = new KawaseBlurPass({ kernelSize: KernelSize.HUGE })
    this.blurPass.setSize(BAKE_SIZE, BAKE_SIZE)

    /** 烘焙用正交相机, 每次 bake 时按整机包围盒重设 */
    this.bakeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10)

    /** 烘焙用覆盖材质: 纯白剪影底上的黑色轮廓由清屏色与本材质共同构成 */
    this.overrideMaterial = new THREE.MeshBasicMaterial({ color: 0x000000, fog: false })

    this.material = new THREE.ShaderMaterial({
      uniforms: THREE.UniformsUtils.clone(SHADOW_SHADER.uniforms),
      vertexShader: SHADOW_SHADER.vertexShader,
      fragmentShader: SHADOW_SHADER.fragmentShader,
      blending: THREE.MultiplyBlending,
      premultipliedAlpha: true,
      transparent: true,
      depthWrite: false,
      fog: false,
    })
    this.material.uniforms.uMask.value = this.blurTarget.texture

    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.material)
    this.plane.rotation.x = -Math.PI / 2
    this.plane.name = 'STAGE_CONTACT_SHADOW'
    this.plane.visible = false
    this.plane.raycast = () => {} // 拾取永远不该命中阴影面
    // 地面(-3)/倒影(-2)/接触阴影(-1)三层靠 renderOrder 定序, 不靠微小高度差
    this.plane.renderOrder = -1
    scene.add(this.plane)

    /** 当前主题与实时阴影开关(浓度 = (面板覆盖 ?? 主题基准) × 实时衰减) */
    this.theme = 'dark'
    this.realtimeShadow = false
    /** @type {number|null} 显示设置面板给的浓度覆盖 */
    this.strengthOverride = null
  }

  /**
   * 功能: 对整机烘一次接触阴影.
   *
   * 渲染时把场景里除目标以外的一切(地面/网格/本阴影面)藏起来, 用黑色覆盖材质
   * 出剪影, 再整体模糊. 结束后完整还原场景与渲染器状态.
   *
   * @param {THREE.Object3D} machineRoot 整机根节点
   * @param {THREE.Box3} box 整机包围盒(世界坐标)
   * @returns {void}
   */
  bake(machineRoot, box) {
    if (!machineRoot || !box || box.isEmpty()) return
    const { renderer, scene } = this

    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const halfW = Math.max(size.x, 0.001) * 0.5 * EXPAND
    const halfD = Math.max(size.z, 0.001) * 0.5 * EXPAND

    // 相机罩住外扩后的足迹, 从包围盒顶上方垂直向下看;
    // up 取 -Z, 使贴图 V 轴与被 -90° 翻转的平面 UV 一致
    const camera = this.bakeCamera
    camera.left = -halfW
    camera.right = halfW
    camera.top = halfD
    camera.bottom = -halfD
    camera.near = 0.1
    camera.far = Math.max(size.y, 0.001) + 2
    camera.position.set(center.x, box.max.y + 1, center.z)
    camera.up.set(0, 0, -1)
    camera.lookAt(center.x, box.min.y, center.z)
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld(true)

    // -- 保存并改写场景/渲染器状态 ------------------------------------------
    const prevState = {
      background: scene.background,
      fog: scene.fog,
      override: scene.overrideMaterial,
      target: renderer.getRenderTarget(),
      toneMapping: renderer.toneMapping,
      clearColor: renderer.getClearColor(new THREE.Color()),
      clearAlpha: renderer.getClearAlpha(),
      // 阴影按需更新的挂起标记也要保存并暂清: 不清的话, 烘焙这趟 render 会在
      // "只剩整机可见 + 黑色覆盖材质"的状态下顺手把阴影贴图渲了
      shadowNeedsUpdate: renderer.shadowMap.needsUpdate,
      visibility: new Map(),
    }
    renderer.shadowMap.needsUpdate = false
    for (const child of scene.children) {
      prevState.visibility.set(child, child.visible)
      child.visible = child === machineRoot
    }
    scene.background = null
    scene.fog = null
    scene.overrideMaterial = this.overrideMaterial
    renderer.toneMapping = THREE.NoToneMapping
    renderer.setClearColor(0xffffff, 1)

    renderer.setRenderTarget(this.maskTarget)
    renderer.clear()
    renderer.render(scene, camera)

    // -- 还原 ---------------------------------------------------------------
    for (const [child, visible] of prevState.visibility) child.visible = visible
    scene.background = prevState.background
    scene.fog = prevState.fog
    scene.overrideMaterial = prevState.override
    renderer.toneMapping = prevState.toneMapping
    renderer.setClearColor(prevState.clearColor, prevState.clearAlpha)
    renderer.shadowMap.needsUpdate = prevState.shadowNeedsUpdate

    // 剪影 → 软阴影
    this.blurPass.render(renderer, this.maskTarget, this.blurTarget)
    renderer.setRenderTarget(prevState.target)

    // 阴影面对准足迹, 略高于地面(-0.002)避免 z-fighting, 也不遮住零平面上的底座
    this.plane.scale.set(halfW * 2, halfD * 2, 1)
    this.plane.position.set(center.x, -0.001, center.z)
    this.plane.visible = true
  }

  /**
   * 功能: 阴影浓度随主题切换(贴图不变, 只改 uniform).
   * @param {string} theme 主题名('dark' | 'light')
   * @returns {void}
   */
  setTheme(theme) {
    this.theme = theme
    this._applyStrength()
  }

  /**
   * 功能: 实时阴影开关联动(画质档位驱动). 开实时影时接触影自动调淡, 关时回满 ——
   *       低画质档没有实时影, 接触影是唯一的落地感来源, 不能一起弱.
   * @param {boolean} enabled 实时阴影是否开启
   * @returns {void}
   */
  setRealtimeShadow(enabled) {
    this.realtimeShadow = Boolean(enabled)
    this._applyStrength()
  }

  /**
   * 功能: 显示设置面板的浓度覆盖(null 回到主题基准); 实时衰减仍在其上生效.
   * @param {number|null} strength 浓度基准覆盖
   * @returns {void}
   */
  setStrength(strength) {
    this.strengthOverride = Number.isFinite(strength) ? strength : null
    this._applyStrength()
  }

  /**
   * 功能: 按(覆盖 ?? 主题基准)与实时阴影衰减刷新浓度 uniform.
   * @returns {void}
   */
  _applyStrength() {
    const base = this.strengthOverride ?? CONTACT_STRENGTH[this.theme] ?? CONTACT_STRENGTH.dark
    this.material.uniforms.uStrength.value = this.realtimeShadow ? base * REALTIME_SCALE : base
  }

  /**
   * 功能: 换模型/卸载时隐藏阴影(旧剪影不再有效).
   * @returns {void}
   */
  clear() {
    this.plane.visible = false
  }

  /**
   * 功能: 释放全部 GPU 资源.
   * @returns {void}
   */
  dispose() {
    this.scene.remove(this.plane)
    this.plane.geometry.dispose()
    this.material.dispose()
    this.overrideMaterial.dispose()
    this.maskTarget.dispose()
    this.blurTarget.dispose()
    this.blurPass.dispose()
  }
}
