/**
 * 功能: 构建可昼夜切换的舞台环境 —— 环境光照、影子主光、地面、雾与背景.
 *
 * 参数分两层(2026-08-05 用户定案 "白天和晚上使用同一套材质设置, 只是环境不同"):
 *   - RIG    机器怎么被照亮 —— 灯色/主光方向/各光源强度/影子浓度柔度, **昼夜共用一套**.
 *     取向沿用 2026-08-01 的影棚配方(对照产品渲染图): 主光独大且从左上打, 填充只留
 *     一点点, 暗部交给环境反射; 灯色中性白(实机在白墙白顶灯的实验室里, 铝件亮银、
 *     外罩纯白, 早期的冷蓝三点光会把整机罩上灰蓝调, 对照照片一眼就是"洗过一样"的假).
 *   - STAGES 周围环境什么样 —— 背景渐变/雾/地面/网格, **昼夜各一套**(dark 夜幕舞台 /
 *     light 浅灰摄影棚). 用户正视图反馈"背景太亮看不清设备"后, 浅色侧的背景压过一档
 *     (白色设备的剪影要能从背景里立出来).
 *   src/theme.js 全局切换, 场景运行时热切不重建; 切主题现在只换环境, 机器观感不动.
 * 公共取向(2026-08-01 影棚化升级, 推翻两条旧决策):
 *   - 环境贴图从 RoomEnvironment 换成程序化影棚灯板(StudioEnvironment.js):
 *     小灰房间反射不出高光形状, 金属只能得到一团均匀灰 —— "金属像灰泥"的直接来源.
 *     2026-08-14 曾试过换成实拍 HDRI, **已回退**: 环境贴图是设备与房间共用的, 而
 *     铝型材(metalness 0.85)的亮度几乎全部来自它 —— 换成白墙影棚 HDRI 后框架整片泛白,
 *     正中 StudioEnvironment 里那条"0x9aa0a6×0.85 泛白"的标定记录. 结论: 房间怎么改都行,
 *     **环境贴图不能动** —— 它是设备观感的地基.
 *   - 启用实时阴影(旧注释"关阴影是最大的性能红利"): 性能初衷用另一种方式保住 ——
 *     shadowMap.autoUpdate=false 按需重渲(SceneManager 统一调度), 模型静止时
 *     阴影零每帧开销, 只有动画/交互帧才重算; 低画质档整个关闭.
 * 运行时调节(2026-08-01 显示设置面板):
 *   - 旧的"亮度×全部灯/反射×环境"两旋钮控制器已退役, 升级为 applyDisplay(eff) ——
 *     分光源强度/主光角度/阴影浓度柔度/背景亮度/雾/网格 的统一生效入口, 有效值由
 *     SceneManager 从 displaySettings(基准 ⊕ 用户覆盖)合成后灌入.
 */
import * as THREE from 'three'

import { getTheme } from '../../theme.js'
import { deriveKeyAngles, fromKeyAngles } from './displaySettings.js'
import { createLaboratoryBackground, laboratorySafeDistance } from './LaboratoryBackground.js'
import { createStudioEnvTexture } from './StudioEnvironment.js'

/**
 * 布光台(RIG): **昼夜共用**的一套灯光/观感参数.
 *
 * 2026-08-05 用户定案: "白天和晚上使用同一套材质设置, 只是环境不同". 机器怎么被照亮
 * 与周围环境什么样是两件事 —— 前者进 RIG(昼夜同一份), 后者进 STAGES(昼夜各一份).
 * 日后调参的规矩就这一条: 改机器观感动 RIG, 改周围环境动 STAGES.
 *
 * intensity 是各光源基准强度, shadow 是影子的浓度/柔度基准 —— 它们经
 * getDisplayBaseline() 变成显示设置的"基准值", 用户在面板里的调整以覆盖形式叠加.
 * keyPos 是主光方向(也是影子的方向), 模型加载后按整机半径重新定距(fitShadowToModel).
 *
 * 已退役的夜景布光性格(2026-08-01 立, 2026-08-05 昼夜统一后退役) —— 结论仍有价值:
 *   曾经认为夜景的关键不是"把白天调暗"而是换布光性格(暖主光 + 冷补光 + 蓝轮廓光).
 *   去色偏实测否掉了它: 暖主光与饱和蓝轮廓光装在设备两侧, 绕机位一圈地面冷暖指数
 *   (R−B)从前/左 +7.4 甩到后 −54.3(用户原话"两边环境两种完全不同的颜色"); 关轮廓光
 *   把后侧 −54.3 拉回 −15.2(它独占 39 点), 关主光把前侧 +7.4 拉回 −4.4.
 *   这正是"中性灯色胜出"的证据, 也是本次能昼夜共用一套灯的前提.
 */
export const RIG = {
  keyLight: 0xffffff,
  fillLight: 0xf4f7fb,
  rimLight: 0xe4ecf6,
  hemiSky: 0xffffff,
  hemiGround: 0xcfd6df,
  // 仰角折中(校准记录: y=10 影子甩一大片, y=12 影子全躲进设备底下):
  // 影棚顶光要的是"贴着设备向右后方铺一小片软影".
  // 2026-08-05 用户手调至 方位 −51° / 仰角 85°(近乎顶光), 本向量由这两角反解、
  // 模长保持原 light 的 12.2984 —— 注意 85° 恰好压在 DISPLAY_FIELDS 的 max 上,
  // 合法但无余量: 固化后仰角滑块只能往下调.
  // 2026-08-14 曾压到 55° 求"体积感", **已回退**: 这是用户手调的值, 且它改的是**设备本身**
  // 的着色, 不在"只改环境"的范围内.
  keyPos: [-0.833, 12.2516, 0.6746],
  // 顶视过曝像素实测(machine.glb): key1.10/env0.85/hemi0.25 = 12715;
  // 只降 env 到 0.45 仍有 11256(几乎无效); key 降到 0.60 = 2103;
  // key0.60+env0.55+hemi0.45 = 1526(−88%), 而等轴测对比度 41.2→42.2 反升,
  // 半球光补到 0.45 是为了把主光让出的环境照度找回来, 不让画面发闷.
  // 这组数原是"浅色主题脚注", 昼夜统一后升格为共用数值的主要依据.
  // 2026-08-05 用户在此之上手调: key 0.60→0.70, env 0.55→0.85(总亮度另有 1.1 倍).
  intensity: { hemi: 0.45, key: 0.7, fill: 0.28, rim: 0.15, env: 0.85 },
  // 夜间影子曾单独降浓加柔到 0.7/7: 0.85 的浓度在深色地面上近乎纯黑, 与淡淡的接触影
  // 完全脱节(用户原话"场景的亮和阴影不匹配"). 本次统一为 0.8/5(用户所见的那组);
  // 若日后仍要给夜间单独放浓度, 回退单点是 STAGE_BASELINE.dark 而不是这里.
  shadow: { intensity: 0.8, radius: 5 },
}

/**
 * 舞台(STAGES): 周围环境, **昼夜各一套** —— 背景渐变/雾/地面/网格.
 * 这里只有"机器周围长什么样", 不含任何 intensity/shadow/灯色.
 * ⚠️ 别往 STAGES 里加 RIG 的键(intensity/shadow/keyPos/*Light/hemi*): 派生 PALETTES 时
 *    RIG 在后展开, 加了会被静默覆盖回共用值; displayBaseline.test.js 锁着这条.
 */
export const STAGES = {
  dark: {
    // 背景渐变: 中心比边缘亮一档 —— 纯色背景像虚空, 亮白设备像悬浮的剪贴画
    // (用户反馈"突兀"); 径向渐变给出"影棚背景纸"的空间感, 夜幕下同样适用
    bgCenter: 0x161c26,
    bgEdge: 0x0b0f16,
    fog: 0x10151e,
    groundBase: 0x1a2130,
    groundRoughness: 0.55,
    groundMetalness: 0.1,
    gridMajor: 0x3d4d70,
    gridMinor: 0x27324a,
    gridOpacity: 0.42,
  },
  light: {
    // 背景压暗一档(0xf4f6f8 → 0xe9edf2): 正视图下白色设备顶部结构的剪影会融进
    // 近白背景(用户原话"外面光太强看不清设备"); 边缘/雾色同族下移保持渐变比例.
    // 2026-08-01 二轮: 平视仍整屏洗白(用户原话"白色的光晕导致什么也看不清").
    // 归因实验(显示面板逐项切): 关雾几乎无感, 压背景立竿见影 —— 元凶是近白的
    // 渐变背景本身. 中心半档、边缘一档下压, 白色机顶在上半屏才有剪影可立
    bgCenter: 0xdce3eb, // 0xe9edf2 → 半档(等轴测下设备遮住中心, 观感影响最小)
    bgEdge: 0xaab4c2, // 0xcfd5dc → 上半屏融化带主要落在渐变外段, 边缘是主杠杆
    fog: 0xc2c9d4, // 0xdde2e8 → 平视地平线带从近白落到中灰"地脚线"
    // 地面受光摄影台(要接实时阴影). 边缘淡出交给径向 alphaMap(在雾生效前融进背景
    // 渐变), 规避旧版"过曝地平线弧"的翻车路径 —— 若再见弧, 调淡出起点而不是把雾调近
    groundBase: 0xd4d9e0, // 0xdfe3e9 → 与设备底座拉开半档
    groundRoughness: 0.75, // 0.6 → 杀掉平视掠射角的环境高光条
    groundMetalness: 0.0,
    gridMajor: 0x8797ae,
    gridMinor: 0xb9c4d3,
    gridOpacity: 0.45,
  },
}

/**
 * 默认舞台的雾距(相对**当前轨道距离**, 不是相对整机半径).
 *
 * 为什么不再乘整机半径(旧值 dark 3.2/12, light 3.4/7.0, 2026-08-14 退役):
 *   相机距离在 0.12r~12r 之间变化一百倍, 而那组倍率是照着**默认取景距离**(约 2.3r)
 *   定的. 缩到最小(12r)时整机远侧已经远在 fogFar 之外, 设备 100% 溶进雾色 —— 实测
 *   一张浅色主题的极限缩小图上只剩一个几乎看不见的小点. 反过来把倍率放大又会让
 *   近景放跑网格远端的硬边(雾在这里的唯一职责就是吃掉它).
 * 所以雾距改成跟着相机走: 起雾点永远压在"整机远侧之外", 终点永远落在"网格边缘之外".
 * 雾**色**仍逐主题(那是画风), 只有距离改成几何量 —— 它与昼夜无关.
 */
/** 起雾点 = 当前轨道距离 + 整机外接球半径 × 它. 大于 1 才保证设备永不吃雾 */
const FOG_NEAR_CLEARANCE = 1.35
/** 终雾点 = 当前轨道距离 + 地面尺寸 × 它. 要够到网格最远的那个角 */
const FOG_FAR_REACH = 0.6

/**
 * 昼夜两套完整色板 = 舞台 ⊕ 共用布光台(派生量, 不要手改).
 * 派生而不是改消费方: createEnvironment 里十余处 palette.keyLight / palette.intensity.env /
 * palette.shadow.radius 的读法零改动, setTheme 里那几行灯色重着色自动变成幂等空操作.
 */
export const PALETTES = {
  dark: { ...STAGES.dark, ...RIG },
  light: { ...STAGES.light, ...RIG },
}

/** 兼容旧引用: 深色色板曾以单数名导出 */
export const PALETTE = PALETTES.dark

/** 金属反射增强倍率: 显式 envMap 的金属件在 scene.environmentIntensity 基础上再乘它 */
const ENV_BOOST_FACTOR = 1.35



/**
 * 逐主题基准例外: 空 = 完全共用(当前状态, 即用户要的"昼夜同一套观感参数").
 * 日后若确实要给夜间单独放一项(最可能是 shadowIntensity), 填这里就是唯一改动点 ——
 * 别再把参数拆回 STAGES. displayBaseline.test.js 会自动把这里列出的键排除在"两主题
 * 基准必须深等"的断言之外.
 * @type {{dark: object, light: object}}
 */
export const STAGE_BASELINE = { dark: {}, light: {} }

/**
 * 功能: 派生某主题的显示设置基准(Environment 消费的那部分).
 *       数值一律取共用的 RIG, 只有 STAGE_BASELINE 列出的键才逐主题不同.
 *       SceneManager 会在此之上拼装 Effects/接触影等其余基准.
 * @param {string} themeName 主题名('dark'|'light'); 现仅用于取 STAGE_BASELINE 例外
 * @returns {object} 基准值
 */
export function getDisplayBaseline(themeName) {
  const angles = deriveKeyAngles(RIG.keyPos)
  return {
    // 总曝光乘数, 落在 applyDisplay 的每一盏灯上 —— 与 RIG.intensity 是相乘关系,
    // 2026-08-05 用户手调 1.0 → 1.1(别把这 1.1 二次乘进 RIG.intensity)
    brightness: 1.1,
    keyEnabled: true,
    fillEnabled: true,
    rimEnabled: true,
    hemiEnabled: true,
    envEnabled: true,
    keyIntensity: RIG.intensity.key,
    fillIntensity: RIG.intensity.fill,
    rimIntensity: RIG.intensity.rim,
    hemiIntensity: RIG.intensity.hemi,
    envIntensity: RIG.intensity.env,
    keyAzimuthDeg: angles.azimuthDeg,
    keyElevationDeg: angles.elevationDeg,
    shadowIntensity: RIG.shadow.intensity,
    shadowRadius: RIG.shadow.radius,
    bgIntensity: 1.0,
    fogEnabled: true,
    gridVisible: true,
    ...(STAGE_BASELINE[themeName] || {}),
  }
}

/**
 * 功能: 数字色值转 CSS 颜色串.
 * @param {number} hex 如 0xe9edf2
 * @returns {string} 如 "#e9edf2"
 */
function hexToCss(hex) {
  return `#${hex.toString(16).padStart(6, '0')}`
}

/**
 * 功能: 生成影棚渐变背景纹理. scene.background 的普通贴图按屏幕空间全屏绘制、
 *       不随相机转 —— 正是"影棚背景纸"的观感, 比穹顶球实现简单得多.
 *       亮心略低于画面中心(设备所在), 四角沉下去自带一点暗角.
 * @param {number} centerHex 中心色
 * @param {number} edgeHex 边缘色
 * @returns {THREE.CanvasTexture} 背景纹理(SRGB)
 */
function makeBackgroundTexture(centerHex, edgeHex) {
  const size = 512
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const gradient = ctx.createRadialGradient(
    size * 0.5, size * 0.56, size * 0.1,
    size * 0.5, size * 0.56, size * 0.78,
  )
  gradient.addColorStop(0, hexToCss(centerHex))
  gradient.addColorStop(1, hexToCss(edgeHex))
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)

  // ±1 灰阶的随机抖动: 浅灰大渐变在 8 位量化下会出明显色带(实测), 抖动打散它
  const image = ctx.getImageData(0, 0, size, size)
  const data = image.data
  for (let i = 0; i < data.length; i += 4) {
    const noise = (Math.random() - 0.5) * 2
    data[i] += noise
    data[i + 1] += noise
    data[i + 2] += noise
  }
  ctx.putImageData(image, 0, 0)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  return texture
}

/**
 * 功能: 生成地面圆盘的径向淡出 alphaMap(中心不透明, 55% 半径起渐隐到边缘全透).
 *       地面在雾生效之前就融进背景渐变, 是"无缝影棚地面"的关键.
 * @returns {THREE.CanvasTexture} 灰度纹理(alphaMap 采样绿通道, 灰度即可)
 */
function makeGroundAlphaTexture() {
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = size
  canvas.height = size
  const ctx = canvas.getContext('2d')
  const gradient = ctx.createRadialGradient(
    size / 2, size / 2, 0,
    size / 2, size / 2, size / 2,
  )
  gradient.addColorStop(0.0, '#ffffff')
  gradient.addColorStop(0.45, '#ffffff')
  gradient.addColorStop(0.96, '#000000')
  gradient.addColorStop(1.0, '#000000')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, size, size)
  return new THREE.CanvasTexture(canvas)
}

/**
 * 功能: 创建场景并布置灯光/地面/环境贴图, 返回的 setTheme 可整套热切昼夜画风.
 *       灯光强度/主光角度/阴影/背景亮度/雾/网格的运行时值统一经 applyDisplay 灌入
 *       (SceneManager 在构造尾、切档尾、切主题尾各重放一次).
 * @param {THREE.WebGLRenderer} renderer 渲染器(生成 PMREM 需要)
 * @param {object} [options] 可选项
 * @param {number} [options.groundSize=24] 地面尺寸(米)
 * @param {boolean} [options.grid=true] 是否创建网格
 * @returns {{scene: THREE.Scene, dispose: Function, envTexture: THREE.Texture,
 *           setTheme: (name: string) => void,
 *           applyFogRange: (radius?: number) => void,
 *           fitBackgroundToModel: (box: THREE.Box3) => void,
 *           getEnclosureDistance: (targetY: number, targetDrift: number) => number|null,
 *           applyDisplay: (eff: object) => void,
 *           setShadows: (enabled: boolean, mapSize?: number) => void,
 *           fitShadowToModel: (box: THREE.Box3) => void,
 *           registerEnvBoost: (materials: Iterable<THREE.Material>) => void,
 *           clearEnvBoost: () => void}}
 *          场景对象、释放函数与各控制函数
 */
export function createEnvironment(renderer, options = {}) {
  const { groundSize = 24, grid = true } = options

  let palette = PALETTES[getTheme()] || PALETTES.dark

  const scene = new THREE.Scene()
  const laboratory = createLaboratoryBackground()
  laboratory.setTheme(getTheme())
  scene.add(laboratory.root)
  /** 全局背景偏好: default 保留原摄影棚, laboratory 显示程序化洁净室 */
  let backgroundScene = 'default'

  // -- 背景与雾 -----------------------------------------------------------
  let backgroundTexture = null

  /**
   * 功能: 按当前色板重建渐变背景(热切主题时释放旧纹理).
   * @returns {void}
   */
  function applyBackground() {
    backgroundTexture?.dispose()
    backgroundTexture = makeBackgroundTexture(palette.bgCenter, palette.bgEdge)
    scene.background = backgroundTexture
  }
  applyBackground()

  // 远处淡出到背景色, 避免网格远端出现生硬截断; 起雾距离要远于"取景距离+整机半径",
  // 否则整机远侧被雾洗灰(模型加载后 applyFogRange 会按整机半径重设)
  scene.fog = new THREE.Fog(palette.fog, groundSize * 0.85, groundSize * 2.2)

  // -- 环境贴图: 程序化影棚灯板(金属反射的高光形状来源) ----------------------
  const envTexture = createStudioEnvTexture(renderer)
  scene.environment = envTexture
  scene.environmentIntensity = palette.intensity.env

  // -- 灯光: 影子主光 + 低比例填充, 颜色与基准强度随主题切换 -----------------
  // 层次靠光比: key 是唯一的方向主角(也是唯一的影子光), hemi/fill/rim 只保底.
  const hemi = new THREE.HemisphereLight(palette.hemiSky, palette.hemiGround, palette.intensity.hemi)
  scene.add(hemi)

  const key = new THREE.DirectionalLight(palette.keyLight, palette.intensity.key)
  key.position.set(...palette.keyPos)
  // 阴影参数设好但默认不投(castShadow 由 SceneManager 按画质档经 setShadows 开关):
  //   - three 0.185 已废弃 PCFSoftShadowMap, 软化靠 PCFShadowMap 的 radius(新版生效);
  //   - normalBias 按"米"给, 用于压量化网格(KHR_mesh_quantization)的阴影麻点;
  //   - intensity/radius 是着色期 uniform 不进阴影贴图, 面板滑块改它们无需重渲.
  key.shadow.mapSize.set(2048, 2048)
  key.shadow.bias = -0.0001
  key.shadow.normalBias = 0.02
  key.shadow.radius = palette.shadow.radius
  key.shadow.intensity = palette.shadow.intensity
  key.shadow.camera.near = 0.5
  scene.add(key)
  scene.add(key.target)

  const fill = new THREE.DirectionalLight(palette.fillLight, palette.intensity.fill)
  fill.position.set(7, 4, -5)
  scene.add(fill)

  const rim = new THREE.DirectionalLight(palette.rimLight, palette.intensity.rim)
  rim.position.set(2, 3, -9)
  scene.add(rim)

  /** 面板可调的主光角度(度); null 表示尚未灌入, 用色板 keyPos 方向 */
  let keyAngle = null
  /** 最近一次 fitShadowToModel 的整机包络(重摆主光时沿用) */
  let shadowFit = null

  /**
   * 功能: 当前主光方向单位向量(面板角度优先, 否则色板方向).
   * @returns {THREE.Vector3} 方向
   */
  function keyDirection() {
    if (keyAngle) {
      return new THREE.Vector3(...fromKeyAngles(keyAngle.az, keyAngle.el))
    }
    return new THREE.Vector3(...palette.keyPos).normalize()
  }

  /**
   * 功能: 摆主光位置; 模型已加载(shadowFit 有值)时按整机尺度定距.
   * @returns {void}
   */
  function applyKeyPlacement() {
    const dir = keyDirection()
    if (shadowFit) {
      const { center, radius } = shadowFit
      key.position.copy(center).addScaledVector(dir, radius * 2.4)
      key.target.position.copy(center)
    } else {
      const reach = new THREE.Vector3(...palette.keyPos).length()
      key.position.copy(dir).multiplyScalar(reach)
      key.target.position.set(0, 0, 0)
    }
  }

  /**
   * 功能: 模型加载后按整机包围盒收紧影子相机(覆盖范围越小, 同样 2048 贴图越锐利).
   *       视锥按外接球取(±1.2r), 方向无关 —— 面板改主光角度只需重摆位置.
   * @param {THREE.Box3} box 整机包围盒(世界坐标)
   * @returns {void}
   */
  function fitShadowToModel(box) {
    if (!box || box.isEmpty()) return
    const sphere = box.getBoundingSphere(new THREE.Sphere())
    shadowFit = { center: sphere.center.clone(), radius: Math.max(sphere.radius, 0.5) }
    applyKeyPlacement()

    const { radius } = shadowFit
    const cam = key.shadow.camera
    const half = radius * 1.2
    cam.left = -half
    cam.right = half
    cam.top = half
    cam.bottom = -half
    cam.near = Math.max(0.1, radius * 0.8)
    cam.far = radius * 4.5
    cam.updateProjectionMatrix()
  }

  /**
   * 功能: 开关实时阴影(画质档位与面板开关合成后驱动). 关闭时阴影渲染路径零成本.
   * @param {boolean} enabled 是否投影
   * @param {number} [mapSize] 阴影贴图边长(档位切换时可降清)
   * @returns {void}
   */
  function setShadows(enabled, mapSize) {
    key.castShadow = Boolean(enabled)
    if (mapSize && key.shadow.mapSize.x !== mapSize) {
      key.shadow.mapSize.set(mapSize, mapSize)
      // 已分配的贴图不会自动跟随尺寸, 置空强制下次重建
      key.shadow.map?.dispose()
      key.shadow.map = null
    }
  }

  // -- 金属反射增强 -------------------------------------------------------
  // three 的实现细节: 材质只吃 scene.environment 时, envMapIntensity 每帧被
  // scene.environmentIntensity 覆盖 —— 想给金属单独加反射必须显式赋 mat.envMap.
  // 赋了之后该材质就脱离全局环境强度, 所以每次强度变化都要替它们补乘.
  /** @type {Set<THREE.Material>} 被显式赋 envMap 的金属材质 */
  let boostedMaterials = new Set()

  /**
   * 功能: 按当前 scene.environmentIntensity 刷新增强材质的反射强度.
   * @returns {void}
   */
  function applyBoostIntensity() {
    const boosted = scene.environmentIntensity * ENV_BOOST_FACTOR
    for (const material of boostedMaterials) material.envMapIntensity = boosted
  }

  /**
   * 功能: 登记一批金属材质做反射增强(整组替换). 被移出集合的材质要摘掉 envMap
   *       并把 envMapIntensity 归位, 否则它会带着过期的增强值继续渲染.
   * @param {Iterable<THREE.Material>} materials 目标材质
   * @returns {void}
   */
  function registerEnvBoost(materials) {
    const next = new Set(materials)
    for (const material of boostedMaterials) {
      if (next.has(material)) continue
      material.envMap = null
      material.envMapIntensity = 1
      material.needsUpdate = true
    }
    for (const material of next) {
      if (material.envMap === envTexture) continue
      material.envMap = envTexture
      material.needsUpdate = true
    }
    boostedMaterials = next
    applyBoostIntensity()
  }

  /**
   * 功能: 解除反射增强. 必须在模型 disposeObject 之前调用 —— 那里会 dispose 材质上
   *       一切纹理, 不先摘掉 envMap 会把共享的 PMREM 环境贴图一起杀掉.
   * @returns {void}
   */
  function clearEnvBoost() {
    for (const material of boostedMaterials) {
      material.envMap = null
      material.envMapIntensity = 1
      material.needsUpdate = true
    }
    boostedMaterials.clear()
  }

  // -- 地面: 受光摄影台圆盘, 径向 alphaMap 淡出融进背景渐变 -------------------
  const groundAlpha = makeGroundAlphaTexture()
  const groundMaterial = new THREE.MeshStandardMaterial({
    color: palette.groundBase,
    roughness: palette.groundRoughness,
    metalness: palette.groundMetalness,
    transparent: true,
    alphaMap: groundAlpha,
  })
  const ground = new THREE.Mesh(new THREE.CircleGeometry(groundSize * 0.75, 96), groundMaterial)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.002 // 略低于零平面, 防止与设备底座 z-fighting
  ground.receiveShadow = true
  // 地面/倒影/接触阴影三层靠 renderOrder 定序(-3/-2/-1), 不靠微小高度差
  ground.renderOrder = -3
  ground.name = 'STAGE_GROUND'
  scene.add(ground)

  /** 面板的网格开关状态(GridHelper 在切主题时重建, 状态要存在这里并重放) */
  let gridVisible = true
  let gridHelper = null
  /** 最近一次建网格的签名(尺寸+原点+主题色); 相同就不重建, 否则每次 applyDisplay 都白扔一次几何 */
  let gridSignature = ''

  /**
   * 功能: 按当前色板与背景场景重建网格. GridHelper 的颜色烘在顶点色里改不了, 只能重建;
   *       实验室场景下网格要按罩体的**平地面**定尺 —— 死的 24 m 会扎穿 8~12 m 的地墙圆角.
   * @returns {void}
   */
  function rebuildGrid() {
    const inLaboratory = backgroundScene === 'laboratory'
    const layout = laboratory.getLayout()
    const size = inLaboratory
      ? Math.max(Math.round((layout.radius - layout.filletRadius) * 2), 2)
      : groundSize
    const originX = inLaboratory ? layout.centerX : 0
    const originY = inLaboratory ? layout.floorY + 0.002 : 0
    const originZ = inLaboratory ? layout.centerZ : 0
    const signature = [size, originX, originY, originZ, palette.gridMajor, palette.gridMinor].join('|')
    if (gridHelper && signature === gridSignature) {
      gridHelper.visible = gridVisible
      return
    }

    if (gridHelper) {
      scene.remove(gridHelper)
      gridHelper.geometry.dispose()
      gridHelper.material.dispose()
      gridHelper = null
    }
    if (!grid) return
    gridHelper = new THREE.GridHelper(size, size * 2, palette.gridMajor, palette.gridMinor)
    gridHelper.material.transparent = true
    gridHelper.material.opacity = palette.gridOpacity
    gridHelper.material.depthWrite = false
    gridHelper.name = 'STAGE_GRID'
    gridHelper.position.set(originX, originY, originZ)
    gridHelper.visible = gridVisible
    scene.add(gridHelper)
    gridSignature = signature
  }

  /** 按背景场景切换两套地面; 所有用户开关值保留, 返回默认时原样恢复。 */
  function applyBackgroundScene() {
    const laboratoryVisible = backgroundScene === 'laboratory'
    laboratory.setVisible(laboratoryVisible)
    ground.visible = !laboratoryVisible
    rebuildGrid()
    applyFogRange()
  }

  /** 最近一次 applyFogRange 的整机半径 */
  let fogRadius = 0
  /** 相机到轨道中心的当前距离: 雾距跟着它走(见 FOG_NEAR_CLEARANCE 的说明) */
  let orbitDistance = 0
  /** 面板的雾开关. 关雾不置 scene.fog=null: USE_FOG define 翻转会让全场材质程序
   *  重编译(一次可见卡顿), 把雾推到无穷远等效关闭且程序不变 */
  let fogEnabled = true

  /**
   * 功能: 按整机尺度与当前主题的倍率设置雾距(尊重面板雾开关).
   * @param {number} [radius] 整机外接球半径(米)
   * @returns {void}
   */
  function applyFogRange(radius) {
    if (Number.isFinite(radius) && radius > 0) fogRadius = radius
    if (!scene.fog) return
    if (!fogEnabled) {
      // near 与 far 不能相等: GLSL smoothstep 在 edge0 >= edge1 时结果未定义
      scene.fog.near = 1e6
      scene.fog.far = 1e7
      return
    }
    if (!fogRadius) return
    if (backgroundScene === 'laboratory') {
      // 实验室场景不起雾. 雾在默认舞台的职责是把地面圆盘的边缘融进背景 —— 封闭罩根本
      // 没有边可藏, 雾只剩副作用: 雾距按整机半径算(近 3.4r ≈ 6.4 m), 而相机退到极限位时
      // 整机远侧已在 10 m 开外, 整台设备连同内壁一起被洗成一块平色, 正是"廉价感"的一部分.
      // 空气感改由罩体的竖向顶点色渐变承担, 那条不碰设备.
      // near/far 不能相等: GLSL smoothstep 在 edge0 >= edge1 时结果未定义
      scene.fog.near = 1e6
      scene.fog.far = 1e7
      return
    }
    scene.fog.near = orbitDistance + fogRadius * FOG_NEAR_CLEARANCE
    scene.fog.far = orbitDistance + groundSize * FOG_FAR_REACH
  }

  /**
   * 功能: 轨道距离变了就重算雾距(每帧由 SceneManager 喂进来).
   *       只在变化超过 1% 时才真的写, 免得每帧无谓地动 uniform.
   * @param {number} distance 相机到轨道中心的当前距离(米)
   * @returns {void}
   */
  function updateFogForDistance(distance) {
    if (!Number.isFinite(distance) || distance <= 0) return
    if (Math.abs(distance - orbitDistance) < orbitDistance * 0.01) return
    orbitDistance = distance
    applyFogRange()
  }

  applyBackgroundScene()

  /**
   * 功能: 显示设置的统一生效入口. eff 是"基准 ⊕ 用户覆盖"的全量值
   *       (SceneManager 合成), 这里只管把 Environment 关心的那部分落到场景上.
   * @param {object} eff 全量有效设置
   * @returns {void}
   */
  function applyDisplay(eff) {
    // 开关走"强度乘 0"而不是 light.visible: visible 翻转改变灯计数, 触发全场
    // 材质重编译一次可见卡顿(与下方关雾不置 null 是同一个考量)
    hemi.intensity = (eff.hemiEnabled ? eff.hemiIntensity : 0) * eff.brightness
    key.intensity = (eff.keyEnabled ? eff.keyIntensity : 0) * eff.brightness
    fill.intensity = (eff.fillEnabled ? eff.fillIntensity : 0) * eff.brightness
    rim.intensity = (eff.rimEnabled ? eff.rimIntensity : 0) * eff.brightness
    scene.environmentIntensity = (eff.envEnabled ? eff.envIntensity : 0) * eff.brightness
    applyBoostIntensity()

    keyAngle = { az: eff.keyAzimuthDeg, el: eff.keyElevationDeg }
    applyKeyPlacement()
    key.shadow.intensity = eff.shadowIntensity
    key.shadow.radius = eff.shadowRadius

    backgroundScene = eff.backgroundScene === 'laboratory' ? 'laboratory' : 'default'
    laboratory.setIntensity(eff.bgIntensity)
    applyBackgroundScene()
    scene.backgroundIntensity = eff.bgIntensity
    // 雾色跟随背景亮度下压, 否则调暗背景后网格远端淡向一个错误的亮色
    scene.fog.color.set(palette.fog).multiplyScalar(Math.min(eff.bgIntensity, 1))
    fogEnabled = Boolean(eff.fogEnabled)
    applyFogRange()

    gridVisible = Boolean(eff.gridVisible)
    if (gridHelper) gridHelper.visible = gridVisible
  }

  /**
   * 功能: 热切整套画风 —— 背景/雾/地面/网格/灯光颜色与阴影基准, 面板覆盖值保留.
   *       调用方(SceneManager)在切完主题后要重放 applyDisplay + invalidateShadows.
   * @param {string} name 主题名('dark' | 'light')
   * @returns {void}
   */
  function setTheme(name) {
    palette = PALETTES[name] || PALETTES.dark
    laboratory.setTheme(name)
    applyBackground()
    scene.fog.color.set(palette.fog)
    applyFogRange()

    groundMaterial.color.set(palette.groundBase)
    groundMaterial.roughness = palette.groundRoughness
    groundMaterial.metalness = palette.groundMetalness
    rebuildGrid()

    hemi.color.set(palette.hemiSky)
    hemi.groundColor.set(palette.hemiGround)
    key.color.set(palette.keyLight)
    fill.color.set(palette.fillLight)
    rim.color.set(palette.rimLight)
    applyKeyPlacement()
  }

  /**
   * 功能: 模型加载后让实验室按整机包围盒居中并扩展, 同时更新设备安全边界。
   * @param {THREE.Box3} box 整机世界坐标包围盒
   * @returns {void}
   */
  function fitBackgroundToModel(box) {
    laboratory.fitToModel(box)
    // 罩体尺寸变了: 网格要按新地面重新定尺, 雾也要重新够到新的内壁
    rebuildGrid()
    applyFogRange()
  }

  /**
   * 功能: 当前背景若是封闭罩, 返回相机允许的最大轨道距离(超过它就会捅出罩外); 否则返回 null.
   *       调用方(SceneManager)把它喂给 CameraRig.setEnclosure —— "出不去"由此成为几何事实.
   * @param {number} targetY 轨道中心的世界高度(整机包围盒中心高度)
   * @param {number} targetDrift 轨道中心可能偏离罩体轴心的最大水平距离(整机外接球半径)
   * @returns {number|null} 允许的最大轨道距离(米), 无罩体约束时为 null
   */
  function getEnclosureDistance(targetY, targetDrift) {
    if (backgroundScene !== 'laboratory') return null
    return laboratorySafeDistance(laboratory.getLayout(), targetY, targetDrift)
  }

  /**
   * 功能: 释放本模块创建的全部 GPU 资源.
   * @returns {void}
   */
  function dispose() {
    clearEnvBoost()
    laboratory.dispose()
    ground.geometry.dispose()
    groundMaterial.dispose()
    groundAlpha.dispose()
    if (gridHelper) {
      gridHelper.geometry.dispose()
      gridHelper.material.dispose()
    }
    backgroundTexture?.dispose()
    scene.background = null
    envTexture.dispose()
    scene.environment = null
    scene.clear()
  }

  return {
    scene,
    dispose,
    envTexture,
    setTheme,
    applyFogRange,
    fitBackgroundToModel,
    updateFogForDistance,
    getEnclosureDistance,
    // 罩体布局的只读快照, 供验收脚本(verify_lab_enclosure.py)复刻剖面做包含性判定
    getEnclosureLayout: () => laboratory.getLayout(),
    applyDisplay,
    setShadows,
    fitShadowToModel,
    registerEnvBoost,
    clearEnvBoost,
  }
}
