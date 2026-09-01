/**
 * 功能: WebGPU 节点管线探底 spike —— 回答"迁不迁"这个决策所需的四组数据.
 *
 * 这是**一次性调研代码**, 不进生产构建, 也不复用现役任何模块(现役整条后期链绑在
 * pmndrs/postprocessing 上, 与 WebGPURenderer 互斥). 刻意与 twin/scene/* 零耦合,
 * 结论拿到之后整个目录可以直接删。
 *
 * 要拿到的四组数据(对应计划里的 B2):
 *   1. 观感    —— 与现役 high 档同机位截图并排(SSGI 看机架内部/台面下方, SSR 看金属互反)
 *   2. 帧耗时  —— 4090 上的 ms/帧; 乘 3~5 倍才是入门独显工控机的预期
 *   3. 几何兼容 —— meshopt + KHR_mesh_quantization 的产物(InterleavedBufferAttribute +
 *      Int16/Int8 normalized)在 WebGPURenderer 下渲不渲得出来。**这是资产层面的真风险**,
 *      不兼容整条路就断了
 *   4. 回退档  —— 同一份代码传 forceWebGL:true 再跑一遍。这一步不需要现场机就能回答
 *      "没有 WebGPU 时迁移是不是白干"
 *
 * URL 参数: ?backend=webgpu|webgl  &fx=on|off
 * 验收脚本读 window.__spike 取结构化结果。
 */
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { ao } from 'three/addons/tsl/display/GTAONode.js'
import { ssgi } from 'three/addons/tsl/display/SSGINode.js'
import { ssr } from 'three/addons/tsl/display/SSRNode.js'
import { traa } from 'three/addons/tsl/display/TRAANode.js'
import { metalness, mrt, output, pass, roughness, transformedNormalView, velocity } from 'three/tsl'
import * as THREE from 'three/webgpu'

const MODEL_URL = '/api/3d/assets/models/machine.official-cr5.glb'

const params = new URLSearchParams(location.search)
const wantWebGL = params.get('backend') === 'webgl'
// fx 逐级累加: 0=关 1=+GTAO 2=+SSGI 3=+SSR 4=+TRAA。
// 逐级才能定位是哪一节点断链 —— 一次性开满只会得到"全黑且不报错"这种无信息的结果
const FX_LEVELS = { off: 0, none: 0, ao: 1, gtao: 1, ssgi: 2, ssr: 3, traa: 4, on: 4 }
const fxLevel = FX_LEVELS[params.get('fx') ?? 'on'] ?? 4
const wantFx = fxLevel > 0

/** 结构化结果, 供 Playwright 读 */
const result = {
  requestedBackend: wantWebGL ? 'webgl' : 'webgpu',
  actualBackend: null,
  fx: params.get("fx") ?? "on",
  fxLevel,
  stages: null,
  ready: false,
  errors: [],
  warnings: [],
  geometry: null,
  frame: null,
}
window.__spike = result

const hud = document.getElementById('hud')
/**
 * 功能: 刷新 HUD 文本.
 * @param {string} extra 追加行
 * @returns {void}
 */
function paint(extra = '') {
  hud.textContent = [
    `请求后端: ${result.requestedBackend}   实际: ${result.actualBackend ?? '…'}`,
    `节点后期: ${result.stages ? result.stages.join(' → ') : (wantFx ? '构建中' : '关')}`,
    result.geometry
      ? `三角形 ${result.geometry.triangles.toLocaleString()}   网格 ${result.geometry.meshes}   交错属性 ${result.geometry.interleaved}`
      : '模型加载中…',
    result.frame ? `GPU 帧耗时 中位 ${result.frame.medianMs.toFixed(2)} ms  (${result.frame.samples} 帧)` : '',
    result.errors.length ? `错误 ${result.errors.length}: ${result.errors[0]}` : '',
    extra,
  ].filter(Boolean).join('\n')
}
paint()

window.addEventListener('error', (e) => { result.errors.push(String(e.message)); paint() })
window.addEventListener('unhandledrejection', (e) => { result.errors.push(String(e.reason)); paint() })

/**
 * 功能: 主流程.
 * @returns {Promise<void>}
 */
async function main() {
  const container = document.getElementById('app')

  // -- 渲染器 -------------------------------------------------------------
  // forceWebGL 走的是同一份代码的 WebGLBackend 回退路径, 正是要实测的那一档
  const renderer = new THREE.WebGPURenderer({
    antialias: false,
    forceWebGL: wantWebGL,
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
  renderer.setSize(window.innerWidth, window.innerHeight)
  renderer.toneMapping = THREE.NeutralToneMapping
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFShadowMap
  container.appendChild(renderer.domElement)
  // 跨后端 timestamp 抽象要显式打开, 否则 info.render.timestamp 恒 0
  renderer.trackTimestamp = true
  await renderer.init()
  result.actualBackend = renderer.backend?.isWebGPUBackend ? 'webgpu' : 'webgl'
  paint()

  // -- 场景与灯光(照现役 dark 色板的量级, 不求逐值一致) --------------------
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x161c26)

  const hemi = new THREE.HemisphereLight(0xb8cce6, 0x2a313d, 0.18)
  scene.add(hemi)
  const key = new THREE.DirectionalLight(0xfff6ec, 1.15)
  key.position.set(-6, 10, 5)
  key.castShadow = true
  key.shadow.mapSize.set(2048, 2048)
  scene.add(key)
  const fill = new THREE.DirectionalLight(0xa9c3e6, 0.12)
  fill.position.set(7, 4, -5)
  scene.add(fill)
  const rim = new THREE.DirectionalLight(0xa9bed6, 0.4)
  rim.position.set(2, 3, -9)
  scene.add(rim)

  // 环境贴图: 用 three 自带的 RoomEnvironment 顶一下(spike 不复刻正式页的 HDRI 环境贴图,
  // 观感对比时要记得现役是程序化影棚灯板, 金属高光形状会比这里更有形)
  const { RoomEnvironment } = await import('three/addons/environments/RoomEnvironment.js')
  const pmrem = new THREE.PMREMGenerator(renderer)
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
  scene.environmentIntensity = 0.6

  const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.05, 200)

  // -- 模型 ---------------------------------------------------------------
  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  const gltf = await loader.loadAsync(MODEL_URL)
  const root = gltf.scene
  scene.add(root)

  // 几何盘点: 交错属性数是"资产兼容性"这一问的直接证据
  let triangles = 0
  let meshes = 0
  let interleaved = 0
  let quantized = 0
  root.traverse((node) => {
    if (!node.isMesh) return
    meshes += 1
    const g = node.geometry
    const index = g.getIndex()
    triangles += index ? index.count / 3 : g.attributes.position.count / 3
    for (const name of Object.keys(g.attributes)) {
      const attr = g.attributes[name]
      if (attr.isInterleavedBufferAttribute) interleaved += 1
      if (attr.normalized) quantized += 1
    }
    node.castShadow = true
    node.receiveShadow = true
  })
  result.geometry = { triangles, meshes, interleaved, quantized }
  paint()

  // 取景: 照现役 CameraRig 的等轴测机位口径(精确包围盒, 见硬约束 6)
  const box = new THREE.Box3().setFromObject(root, true)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  const radius = size.length() / 2
  const dist = radius / Math.sin((camera.fov * Math.PI) / 360) * 0.85
  camera.position.copy(center).add(new THREE.Vector3(1, 0.72, 1).normalize().multiplyScalar(dist))
  camera.lookAt(center)
  key.target.position.copy(center)
  scene.add(key.target)

  // -- 节点后期 -----------------------------------------------------------
  let post = null
  if (fxLevel > 0) {
    const scenePass = pass(scene, camera)
    // MRT: 深度/法线/金属度/粗糙度/速度 是 GTAO/SSR/SSGI/TRAA 的输入, 一趟几何拿齐.
    // velocity 漏了 TRAA 会拿到空节点 —— 这是第一轮全黑的元凶之一
    scenePass.setMRT(mrt({
      output,
      normal: transformedNormalView,
      metalness,
      roughness,
      velocity,
    }))
    const depth = scenePass.getTextureNode('depth')
    const normal = scenePass.getTextureNode('normal')
    const metal = scenePass.getTextureNode('metalness')
    const rough = scenePass.getTextureNode('roughness')

    let node = scenePass.getTextureNode('output')
    result.stages = ['beauty']

    if (fxLevel >= 1) {
      // GTAO 返回的是 AO 节点, 要取它的纹理再乘回 beauty
      node = node.mul(ao(depth, normal, camera).getTextureNode())
      result.stages.push('gtao')
    }
    if (fxLevel >= 2) {
      node = ssgi(node, depth, normal, camera)
      result.stages.push('ssgi')
    }
    if (fxLevel >= 3) {
      // ssr 第四参是 options 对象, camera 必须显式传(不传报 "No camera found");
      // metalness/roughness 走 options 而不是位置参数
      node = ssr(node, depth, normal, { camera, metalnessNode: metal, roughnessNode: rough })
      result.stages.push('ssr')
    }
    if (fxLevel >= 4) {
      node = traa(node, depth, scenePass.getTextureNode('velocity'), camera)
      result.stages.push('traa')
    }

    post = new THREE.PostProcessing(renderer)
    post.outputNode = node
  }

  // -- 循环与计时 ---------------------------------------------------------
  const samples = []
  let frames = 0
  renderer.setAnimationLoop(async () => {
    frames += 1
    if (post) post.render()
    else renderer.render(scene, camera)

    // three 的节点管线自带跨后端 timestamp 抽象; 没有该能力时 info.render.timestamp 恒 0
    const t = renderer.info?.render?.timestamp
    if (frames > 60 && typeof t === 'number' && t > 0) {
      samples.push(t)
      if (samples.length > 240) samples.shift()
      if (samples.length % 30 === 0) {
        const sorted = [...samples].sort((a, b) => a - b)
        result.frame = { medianMs: sorted[Math.floor(sorted.length / 2)], samples: samples.length }
        paint()
      }
    }
    if (frames > 90) result.ready = true
  })

  // 脱开 vsync 的吞吐测量: renderAsync 会等 GPU 完成, 连续跑 n 帧的墙钟时间
  // 就是真实的 GPU 帧耗时(setAnimationLoop 被 vsync 钉在 16.7 ms, 测不出余量)
  result.measure = async (n = 60) => {
    renderer.setAnimationLoop(null)
    // 无后期时用 renderAsync(等 GPU 完成 = 真帧耗时); 有后期时 PostProcessing 的
    // renderAsync 实测是空转(读数 0.02 ms/帧 不可信), 只能退回同步路径横向比
    const once = async () => { if (post) post.render(); else await renderer.renderAsync(scene, camera) }
    for (let i = 0; i < 10; i += 1) await once()
    const t0 = performance.now()
    for (let i = 0; i < n; i += 1) await once()
    const ms = (performance.now() - t0) / n
    result.frame = { medianMs: ms, samples: n, gpuBound: !post }
    paint()
    return ms
  }

  renderer.debug = renderer.debug || {}
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight
    camera.updateProjectionMatrix()
    renderer.setSize(window.innerWidth, window.innerHeight)
  })
}

main().catch((err) => {
  result.errors.push(String(err && err.stack ? err.stack.split('\n')[0] : err))
  result.ready = true
  paint()
  console.error('[spike] 失败', err)
})
