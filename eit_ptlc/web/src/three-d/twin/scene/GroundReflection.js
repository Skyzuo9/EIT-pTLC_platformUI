/**
 * 功能: 烘焙式地面淡倒影 —— 从设备正下方仰拍一张彩色剪影, 重模糊后淡淡贴在地面.
 *
 * 与 ContactShadow 同一套"烘一次零每帧开销"的思路: 模型加载后从 box 底部用正交相机
 * 朝上渲一帧彩色(只有整机可见, 透明底), 两遍 Kawase 模糊, 以低透明度叠在地面上.
 *
 * 为什么是"底视烘焙"而不是真镜像: 平面反射是视角相关的, 真镜像要么每帧镜像重绘
 * 整个场景(Reflector, GPU 开销近乎翻倍), 要么烘死在某个视角、换个角度就穿帮.
 * 底视投影是视角无关的近似 —— 它表达的是"设备底部的颜色在地面上的淡淡映像",
 * 任意环绕角都不出错; 在强模糊 + ≤14% 透明度下, 与真镜像的观感差距可以忽略.
 * 代价是动画时倒影不跟动(已与用户确认接受), 动画停止后由调用方触发重烘.
 */
import * as THREE from 'three'
import { KawaseBlurPass, KernelSize } from 'postprocessing'

/** 烘焙分辨率: 倒影本来就要糊, 512 足够 */
const BAKE_SIZE = 512
/** 倒影平面比整机足迹外扩的比例 */
const EXPAND = 1.3
/** 各主题的倒影强度(叠加不透明度上限) */
const STRENGTH = { dark: 0.1, light: 0.14 }
/** 烘焙时环境强度的临时倍率: 设备底面本来就背光, 不补一档倒影会黑得看不见 */
const BAKE_ENV_SCALE = 2.2

/** 倒影着色器: 采样模糊彩图, X 翻转对齐仰拍镜像, 矩形边缘淡出 */
const REFLECTION_SHADER = {
  uniforms: {
    uMap: { value: null },
    uStrength: { value: STRENGTH.dark },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D uMap;
    uniform float uStrength;
    varying vec2 vUv;
    void main() {
      // 仰拍相机的图像 X 轴与俯视地面相反, 采样时翻回来
      vec4 sample_ = texture2D(uMap, vec2(1.0 - vUv.x, vUv.y));
      // 距平面边缘的淡出, 保证贴图边界处必然归零
      vec2 edge = abs(vUv - 0.5);
      float fade = 1.0 - smoothstep(0.3, 0.5, max(edge.x, edge.y));
      gl_FragColor = vec4(sample_.rgb, sample_.a * fade * uStrength);
    }
  `,
}

export class GroundReflection {
  /**
   * 功能: 准备烘焙管线与倒影平面(此时还没有内容, bake 后才可见).
   * @param {THREE.WebGLRenderer} renderer 渲染器
   * @param {THREE.Scene} scene 目标场景
   */
  constructor(renderer, scene) {
    this.renderer = renderer
    this.scene = scene

    this.colorTarget = new THREE.WebGLRenderTarget(BAKE_SIZE, BAKE_SIZE, { depthBuffer: true })
    this.blurTarget = new THREE.WebGLRenderTarget(BAKE_SIZE, BAKE_SIZE, { depthBuffer: false })

    this.blurPass = new KawaseBlurPass({ kernelSize: KernelSize.HUGE })
    this.blurPass.setSize(BAKE_SIZE, BAKE_SIZE)

    /** 烘焙用正交相机, 每次 bake 时按整机包围盒重设(从底部朝上仰拍) */
    this.bakeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 10)

    this.material = new THREE.ShaderMaterial({
      uniforms: THREE.UniformsUtils.clone(REFLECTION_SHADER.uniforms),
      vertexShader: REFLECTION_SHADER.vertexShader,
      fragmentShader: REFLECTION_SHADER.fragmentShader,
      blending: THREE.NormalBlending,
      transparent: true,
      depthWrite: false,
      fog: false,
    })
    this.material.uniforms.uMap.value = this.colorTarget.texture

    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), this.material)
    this.plane.rotation.x = -Math.PI / 2
    this.plane.name = 'STAGE_GROUND_REFLECTION'
    this.plane.visible = false
    this.plane.raycast = () => {} // 拾取永远不该命中倒影面
    // 地面(-3)/倒影(-2)/接触阴影(-1)三层靠 renderOrder 定序, 不靠微小高度差
    this.plane.renderOrder = -2
    scene.add(this.plane)

    /** 档位开关与"已有有效烘焙"分开记, 二者都为真平面才显示 */
    this.enabled = true
    this.baked = false
  }

  /**
   * 功能: 对整机烘一次底视倒影. 状态保存/还原策略与 ContactShadow.bake 相同,
   *       两个 bake 都不可重入, 调用方按序调用(contact 先、reflection 后).
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

    // 相机从包围盒底下垂直向上看; up 取 -Z 与被 -90° 翻转的平面 V 轴一致
    // (X 轴镜像在着色器采样时翻回)
    const camera = this.bakeCamera
    camera.left = -halfW
    camera.right = halfW
    camera.top = halfD
    camera.bottom = -halfD
    camera.near = 0.1
    camera.far = Math.max(size.y, 0.001) + 2
    camera.position.set(center.x, box.min.y - 1, center.z)
    camera.up.set(0, 0, -1)
    camera.lookAt(center.x, box.max.y, center.z)
    camera.updateProjectionMatrix()
    camera.updateMatrixWorld(true)

    // -- 保存并改写场景/渲染器状态 ------------------------------------------
    const prevState = {
      background: scene.background,
      fog: scene.fog,
      envIntensity: scene.environmentIntensity,
      target: renderer.getRenderTarget(),
      toneMapping: renderer.toneMapping,
      clearColor: renderer.getClearColor(new THREE.Color()),
      clearAlpha: renderer.getClearAlpha(),
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
    // 灯都是 scene 子节点, 上面已全部藏掉 —— 仰拍只吃环境贴图, 补一档亮度
    scene.environmentIntensity = prevState.envIntensity * BAKE_ENV_SCALE
    renderer.toneMapping = THREE.NoToneMapping
    renderer.setClearColor(0x000000, 0)

    renderer.setRenderTarget(this.colorTarget)
    renderer.clear()
    renderer.render(scene, camera)

    // -- 还原 ---------------------------------------------------------------
    for (const [child, visible] of prevState.visibility) child.visible = visible
    scene.background = prevState.background
    scene.fog = prevState.fog
    scene.environmentIntensity = prevState.envIntensity
    renderer.toneMapping = prevState.toneMapping
    renderer.setClearColor(prevState.clearColor, prevState.clearAlpha)
    renderer.shadowMap.needsUpdate = prevState.shadowNeedsUpdate

    // 两遍重模糊: 彩图 → blur → 彩图, 最终展示的是 colorTarget
    this.blurPass.render(renderer, this.colorTarget, this.blurTarget)
    this.blurPass.render(renderer, this.blurTarget, this.colorTarget)
    renderer.setRenderTarget(prevState.target)

    this.plane.scale.set(halfW * 2, halfD * 2, 1)
    this.plane.position.set(center.x, -0.0015, center.z)
    this.baked = true
    this._applyVisible()
  }

  /**
   * 功能: 倒影强度随主题切换.
   * @param {string} theme 主题名('dark' | 'light')
   * @returns {void}
   */
  setTheme(theme) {
    this.material.uniforms.uStrength.value = STRENGTH[theme] ?? STRENGTH.dark
  }

  /**
   * 功能: 档位开关(仅 high 档显示; 烘焙结果保留, 升档回来即刻可见).
   * @param {boolean} enabled 是否启用
   * @returns {void}
   */
  setEnabled(enabled) {
    this.enabled = Boolean(enabled)
    this._applyVisible()
  }

  /**
   * 功能: 按"档位开 且 有有效烘焙"决定平面可见性.
   * @returns {void}
   */
  _applyVisible() {
    this.plane.visible = this.enabled && this.baked
  }

  /**
   * 功能: 换模型/卸载时隐藏倒影(旧烘焙不再有效).
   * @returns {void}
   */
  clear() {
    this.baked = false
    this._applyVisible()
  }

  /**
   * 功能: 释放全部 GPU 资源.
   * @returns {void}
   */
  dispose() {
    this.scene.remove(this.plane)
    this.plane.geometry.dispose()
    this.material.dispose()
    this.colorTarget.dispose()
    this.blurTarget.dispose()
    this.blurPass.dispose()
  }
}
