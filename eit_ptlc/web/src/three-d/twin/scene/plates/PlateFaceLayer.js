/**
 * 功能: 薄层板的场景实体层 —— 建板、板池、料仓堆叠, 以及硅胶厚度的实时改写.
 *
 * 分工: 本层只管"三维对象长什么样、在不在", **不判断板该在哪** —— 位置由
 * PlateBinding 依 L1 账本 + L2 包络仲裁后告诉它。这样位置逻辑可以脱离 three 单测。
 *
 * 两个刻意的取舍:
 *   1. **料仓走 InstancedMesh 而不是逐张 clone**。满仓 30 张 × 2 仓, 逐张 clone 是
 *      60 个绘制调用(现行实现就是这样), 分层后会翻倍到 120; 换成每仓每层一个
 *      InstancedMesh 后只要 4 个 —— 不但没变贵, 还比现状省 56 个。
 *   2. **料仓里的板硅胶朝下**(玻璃面朝上, 供吸盘 rotary-down 从上方贴玻璃吸取)。
 *      实现上不做 180° 翻转, 而是直接把硅胶层实例摆在玻璃层实例**下面** —— 等价且更省。
 */
import * as THREE from 'three'

import {
  SILICA_MM,
  UNIT_BOX,
  clampSilicaMm,
  layerTransforms,
  plateTotalM,
  standardPlateGeom,
} from './plateGeometry.js'
import { createGlassMaterial, createSilicaMaterial, setGlassTransmission } from './plateMaterials.js'
import {
  SCRAPE_CANVAS_SIZE,
  bandComplement,
  drawTrace,
  drawWetRoughness,
  progressRect,
  progressStroke,
  residualLevels,
  scrapeRects,
  uvRectToLocal,
} from './scrapeOverlay.js'

/** 料仓单仓最大堆叠张数(与上位机 material_topology.yaml 的 capacity 同量级)。 */
const MAX_STACK = 40

/** 补光打满时硅胶面的自发光强度。克制取值, 理由见 setFlash 的注释。 */
const FLASH_PEAK = 0.55

/**
 * 程序化板网格的语义标签键: 动作页语义着色(motion/MotionPaint.js)据此把板刷成耗材色,
 * 并使其免于按所在子树认领(板骑在滑车/吸盘上不该跟着变蓝)与透明兜底(玻璃层
 * transmission>0 不该被涂成半透明静止)。键带 __ptlc 前缀避免与 glTF extras 撞名
 * (与 visibilityIntent 同一条理由); 值与 motionSemantics 的分类键同域, 两边字面量必须同步改。
 */
const SEMANTIC_TAG_KEY = '__ptlcSemantic'

const _pos = new THREE.Vector3()
const _quat = new THREE.Quaternion()
const _scale = new THREE.Vector3()
const _mat = new THREE.Matrix4()

/**
 * 功能: 给板的一层设阴影标志位 —— 不透明层投影, 透射层豁免.
 *
 * 判据与 SceneManager 对 CAD 网格那次遍历同源(`transmission > 0 || opacity < 0.5`
 * 算幽灵件, 不投影): 玻璃层 transmission 0.86 挡不住光 → 不投影; 硅胶层纯不透明 → 投影。
 *
 * ⚠ **决定投影的是板的投影面积(整块 200×200mm), 不是它 1mm 的厚度。** 此处一度按
 * "1mm 层的投影贡献为零"把两层一起关掉, 表现是板悬在半空没有任何影子, 像一张贴在画面上
 * 的白色剪贴画(2026-08-09 用户报)。而 `layerTransforms` 给硅胶层的**面内 scale 就是整块板**
 * (只有厚度是 1mm), 所以单让硅胶层投影就已经是完整的板形剪影 —— 再开玻璃层不会改变轮廓,
 * 只是白白违反上面那条规则。物理上也对: 无论硅胶朝上(点样座/刮板台)还是朝下(料仓/展缸),
 * 挡光的都是那层不透明硅胶。
 *
 * 三处建板(单板/料仓堆叠/刮取残余)共用本函数, 理由只写这一份 —— 否则改一处漏两处。
 *
 * @param {THREE.Object3D} mesh 板的一层
 * @param {boolean} opaque 该层是否不透明(硅胶 true / 玻璃 false)
 * @returns {THREE.Object3D} 原对象, 便于在建对象时直接包一层
 */
function applyShadowFlags(mesh, opaque) {
  mesh.castShadow = Boolean(opaque)
  mesh.receiveShadow = true
  return mesh
}

export class PlateFaceLayer {
  /**
   * @param {object} opts
   * @param {number} [opts.silicaMm] 硅胶层厚度(mm)
   * @param {THREE.Material|null} [opts.glassSource] CAD 锚点上的原玻璃材质, 用于克隆派生
   * @param {(() => HTMLCanvasElement)|null} [opts.canvasFactory] 刮取遮罩画布工厂
   *        (单测注 stub; 生产默认 document.createElement)
   */
  constructor({ silicaMm = SILICA_MM.default, glassSource = null, canvasFactory = null } = {}) {
    this.silicaMm = clampSilicaMm(silicaMm)
    /** 两种材质全场共用; 因为源码文本恒等, 后续着色器注入也只会编译出一份 program。 */
    this.glassMaterial = createGlassMaterial(glassSource)
    this.silicaMaterial = createSilicaMaterial()
    /**
     * 分层刮取留下的残余硅胶(凹坑底面)。与 silicaMaterial 同物性, 只是略暗一档 ——
     * 刚被刀犁过的断面比原始粉床压实、反光更少。**共用一份**: 它不带遮罩, 没有逐板状态,
     * 与 MAT_TLC_SILICA_SCRAPE 那种必须逐板克隆的情况不同。
     */
    this.cutSilicaMaterial = createSilicaMaterial()
    this.cutSilicaMaterial.name = 'MAT_TLC_SILICA_CUT'
    this.cutSilicaMaterial.color.multiplyScalar(0.88)
    // 残余层是实心的, 不参与 discard —— 留着 alphaTest 会让没有 map 的它整块消失
    this.cutSilicaMaterial.alphaTest = 0

    /** @type {Map<string, object>} plateId -> 板实体 */
    this._plates = new Map()
    /** @type {object[]} 已归还、可复用的板实体 */
    this._pool = []
    /** @type {Map<string, object>} magazineId -> 堆叠实体 */
    this._magazines = new Map()
    /** 当前补光强度(0..1); 见 setFlash */
    this._flash = 0
    /** 痕迹遮罩画布工厂(见构造参数) */
    this._canvasFactory = canvasFactory || (() => document.createElement('canvas'))
    /** @type {object[]} 已归还、可复用的痕迹遮罩资源(材质克隆 + 画布 + 纹理) */
    this._tracePool = []
  }

  // ── 板池 ────────────────────────────────────────────────────────────────

  /**
   * 功能: 取一块板(池里有就复用, 没有才新建).
   *
   * 池化不是过早优化: 峰值 = 8 缸 + 点样座 + 刮板台 + 手上 = 11 块, 每块 2 个 Mesh,
   * 一个样品跑完就销毁再建, 长跑批次下 GC 会周期性抖动。池上限不设硬顶,
   * 超出就新建 —— 宁可多几个对象, 也不能在并发调高后静默丢板。
   *
   * @param {string} plateId 板号
   * @returns {object} 板实体 {root, glass, silica}
   */
  acquire(plateId) {
    const key = String(plateId || '')
    const existing = this._plates.get(key)
    if (existing) return existing

    const plate = this._pool.pop() || this._createPlate()
    plate.root.name = `PLATE_${key}`
    plate.root.visible = true
    this._plates.set(key, plate)
    return plate
  }

  /** 归还一块板到池里(只隐藏与摘除父级, 不销毁几何)。 */
  release(plateId) {
    const key = String(plateId || '')
    const plate = this._plates.get(key)
    if (!plate) return false
    // 痕迹遮罩随板一起收: 板池是复用的, 不还原材质的话, 下一块从池里取的板
    // 会带着上一块的色带/刮痕出场(向后 seek 的重放路径每次都会经过这里)。
    this._releaseTrace(plate)
    plate.root.visible = false
    plate.root.parent?.remove(plate.root)
    this._plates.delete(key)
    this._pool.push(plate)
    return true
  }

  /** 当前在场的板号。 */
  plateIds() {
    return [...this._plates.keys()]
  }

  /** 取板实体; 不存在返回 null。 */
  get(plateId) {
    return this._plates.get(String(plateId || '')) || null
  }

  _createPlate() {
    const root = new THREE.Group()
    // 阴影标志位见 applyShadowFlags: 硅胶层(不透明)投影, 玻璃层(透射)豁免
    const glass = applyShadowFlags(new THREE.Mesh(UNIT_BOX, this.glassMaterial), false)
    const silica = applyShadowFlags(new THREE.Mesh(UNIT_BOX, this.silicaMaterial), true)
    for (const mesh of [glass, silica]) {
      mesh.userData[SEMANTIC_TAG_KEY] = 'consumable'
      root.add(mesh)
    }
    glass.name = 'PLATE_GLASS'
    silica.name = 'PLATE_SILICA'
    // 先按标准板铺一遍两层: 共享几何是 1×1×1 的单位盒, 不铺就是一个**一米见方的大盒子**。
    // 板正常都会经 place() 拿到实测尺寸, 但"从未 place 过就直接挂上吸盘"这条路是存在的
    // (PlateStage.carry / PlateBinding._attachToSuction 的首挂分支), 兜底不是可选的。
    // 用标准板规格(用户拍板的 2mm 玻璃 + 硅胶, 长宽取 CAD 名义 200mm)而不是猜一个数。
    // residual: 分层刮取的两块"残余硅胶"薄板(本刀已收 / 尚未收), 懒建于首次开刮
    // trace: 板面痕迹资源(点样色带/润湿/刮取共用一份画布与材质克隆), 懒建于首个非零痕迹
    const plate = { root, glass, silica, geom: standardPlateGeom(), trace: null, residual: null }
    this._applyLayers(plate)
    return plate
  }

  /**
   * 造两块残余硅胶薄板(分层刮取用)。共享单位盒几何 + 一份共享材质, 每块板两个 Mesh。
   *
   * 为什么要两块而不是一块: 收粉是**推进式**的, 同一时刻条带里并存两级深度 ——
   * 前沿之后已落到第 k 层, 之前还停在第 k−1 层。一块板表达不了这个空间分界,
   * 拿平均值糊过去的现象是"整条带一起变薄", 与刀的位置对不上。
   *
   * @param {object} plate 板实体
   * @returns {void}
   */
  _createResidual(plate) {
    const make = (name) => {
      // 残余层与硅胶同物性(不透明), 一样投影; 平时 visible=false, 不进阴影 pass
      const mesh = applyShadowFlags(new THREE.Mesh(UNIT_BOX, this.cutSilicaMaterial), true)
      mesh.name = name
      mesh.visible = false
      mesh.userData[SEMANTIC_TAG_KEY] = 'consumable'
      plate.root.add(mesh)
      return mesh
    }
    plate.residual = { cut: make('PLATE_SILICA_RESIDUAL_CUT'), prior: make('PLATE_SILICA_RESIDUAL_PRIOR') }
  }

  /**
   * 功能: 把一块板摆到某个落点的位姿上(换父 + 对齐 + 按实测尺寸重算两层).
   * @param {string} plateId 板号
   * @param {object} geom measurePlateAnchor 的结果
   * @returns {boolean} 是否成功
   */
  place(plateId, geom) {
    const plate = this.acquire(plateId)
    if (!geom?.parent) return false
    plate.geom = geom
    if (plate.root.parent !== geom.parent) geom.parent.add(plate.root)
    plate.root.position.copy(geom.position)
    plate.root.quaternion.copy(geom.quaternion)
    plate.root.scale.copy(geom.scale)
    this._applyLayers(plate)
    return true
  }

  /**
   * 功能: 只换板的**几何语义**(尺寸 + 硅胶朝向), 不动它的位姿与父级.
   *
   * 给"板不在任何落点上、却需要按某个落点的规格来画"的那条路用 —— 典型是被吸盘持着
   * 的板: 它挂在翻转节点下, 但长宽与硅胶朝哪面仍应取自它来自/去往的那个落点。
   * 板池是复用的, 不重设 geom 的话会沿用上一块板的朝向, 于是从料仓取的板可能画成
   * 硅胶朝上(=吸盘去吸粉面), 而这在画面上看不出错。
   *
   * @param {string} plateId 板号
   * @param {object} geom measurePlateAnchor 的结果
   * @returns {boolean} 是否生效
   */
  setGeom(plateId, geom) {
    const plate = this._plates.get(String(plateId || ''))
    if (!plate || !geom) return false
    plate.geom = geom
    this._applyLayers(plate)
    return true
  }

  /** 按当前硅胶厚度重算某块板的两层 scale/position(有刮痕的话连残余薄板一起)。 */
  _applyLayers(plate) {
    if (!plate?.geom) return
    const layers = layerTransforms(plate.geom, this.silicaMm)
    plate.glass.scale.set(...layers.glass.scale)
    plate.glass.position.set(layers.x, layers.glass.y, layers.z)
    plate.silica.scale.set(...layers.silica.scale)
    plate.silica.position.set(layers.x, layers.silica.y, layers.z)
    const state = plate.residualState
    if (state && plate.residual) this._applyResidual(plate, state.uvBand, state.cut, state.levels)
  }

  // ── 硅胶厚度 ────────────────────────────────────────────────────────────

  /**
   * 功能: 改硅胶层厚度. 只动 scale.y 与 position.y, **不重建几何、不做顶点位移**,
   * 所以滑杆连续拖动不会产生任何分配, 也就不会有 GC 尖峰.
   * @param {number} mm 厚度(mm)
   * @returns {boolean} 是否真的变了
   */
  setSilicaThickness(mm) {
    const next = clampSilicaMm(mm)
    if (Math.abs(next - this.silicaMm) < 1e-9) return false
    this.silicaMm = next
    for (const plate of this._plates.values()) this._applyLayers(plate)
    for (const entry of this._magazines.values()) this._writeStack(entry)
    return true
  }

  /** 单板总厚(米), 料仓节距未标定时的回退值。 */
  plateThicknessM() {
    return plateTotalM(this.silicaMm)
  }

  /** 关掉板玻璃的透射(见 plateMaterials.setGlassTransmission 的注释)。 */
  setGlassTransmission(enabled) {
    setGlassTransmission(this.glassMaterial, enabled)
  }

  // ── 板面痕迹遮罩(点样色带 / 溶剂润湿 / 刮取) ─────────────────────────────

  /**
   * 有痕迹就把板的硅胶层换成克隆材质 + 遮罩画布(没有则懒建).
   *
   * 克隆而不是直接改共享材质(three_d/docs/CLAUDE.md 第 12 条 —— 那等于全场的板
   * 一起被"刮"); 三种痕迹共用**同一份**资源与画布, 整幅重画合成(见 _recompose)。
   *
   * @param {object} plate 板实体
   * @returns {object} 痕迹资源
   */
  _ensureTrace(plate) {
    if (plate.trace) return plate.trace
    plate.trace = this._acquireTrace()
    plate.silica.material = plate.trace.material
    return plate.trace
  }

  /**
   * 功能: 按前沿进度更新一块板的刮取遮罩 —— `scrape` 连续通道的落地点.
   *
   * 首次进度 > 0 才建资源。白底不改基色; loosen 区涂不透明暖灰(刮松未收粉);
   * clear 区 alpha=0, 由材质既有的 alphaTest 0.5 discard 露出下层玻璃盒 ——
   * 正是 plateMaterials 头注释预留"刮取穿透"的那条路, 不进透明队列, 无排序问题。
   *
   * 幂等: 画面只由 (uvBand, loosen, clear, pass) 决定; 值未变(1e-3)跳过重画, ClipPlayer
   * 每帧调用也只在前沿真的动了时才碰画布。向后 seek 走 release() 还原共享材质,
   * 重放时从进度 0 重建 —— 状态不带记忆(本文件与 PlateStage 的 seek 契约)。
   *
   * **分层刮取**(2026-08-06): 真机 num_passes 刀、每刀只吃 total_depth/N, 一刀刮不到
   * 玻璃。所以遮罩 discard 出来的洞底下还要垫一块**残余硅胶薄板**, 厚度 = 剩余层数比
   * × 当前硅胶厚 —— 洞 + 薄板合起来才是"凹坑", 只挖洞就成了"一刀见底"。
   * 只有最后一刀(pass == passes)残余厚度为 0, 薄板隐藏, 真正露出玻璃。
   *
   * @param {string} plateId 板号
   * @param {{loosen?: number, clear?: number, pass?: number}} phases 前沿进度与层号
   * @param {object} uvBand scrapeOverlay.bandToUv 的结果
   * @param {object} [region] compiled.scrapeRegions 的一项(要 passes; 缺省按单刀)
   * @returns {boolean} 是否生效(含"值未变跳过重画"的 true)
   */
  applyScrape(plateId, phases, uvBand, region = null) {
    const plate = this._plates.get(String(plateId || ''))
    if (!plate || !uvBand) return false
    const loosen = Math.min(1, Math.max(0, Number(phases?.loosen) || 0))
    const clear = Math.min(1, Math.max(0, Number(phases?.clear) || 0))
    const levels = residualLevels(phases, region?.passes)
    if (!plate.trace) {
      // 未开刮不建资源: scrape 通道从 t=0 就在逐帧求值, 起点恒为 0
      if (loosen < 1e-3 && clear < 1e-3) return false
    }
    const entry = this._ensureTrace(plate)
    if (entry.last
      && Math.abs(entry.last.loosen - loosen) < 1e-3
      && Math.abs(entry.last.clear - clear) < 1e-3
      && entry.last.pass === levels.pass) {
      return true
    }

    const rects = scrapeRects(uvBand, loosen, clear)
    // 第 2 刀起: 前几刀已把整条带都收过一遍, 满厚硅胶层在整条带上都该是空的 ——
    // 只 discard 本刀已扫段会让未扫段又冒出**原厚**的粉, 比刀还高。
    const cut = rects.clear
    const holed = levels.pass >= 2
      ? { u0: uvBand.u0, v0: uvBand.v0, u1: uvBand.u1, v1: uvBand.v1 }
      : cut
    entry.scrape = { loosen: rects.loosen, clear: holed }
    entry.last = { loosen, clear, pass: levels.pass }
    this._recompose(plate)

    this._applyResidual(plate, uvBand, cut, levels)
    return true
  }

  /**
   * 功能: 更新一块板的点样色带 —— `spot` 连续通道与实时页"点样板"的共同落地点.
   *
   * 两种形状(shape)由调用方显式声明, 本层不猜:
   *   'stroke'(默认) 喷头扫出来的标称色带 —— 一个直径=带厚的圆点滑过的轨迹(圆帽);
   *   'rect'          视觉实测的谱带 bbox —— 近似方形, 描边会把它压成胶囊或溢出带外。
   *
   * @param {string} plateId 板号
   * @param {Array<{uv: object, fill: number, shape?: 'stroke'|'rect'}>} bands 各条带的
   *        UV 矩形(bandToUv 的结果, 含 fill 前沿)与渐现进度 0..1 —— UV 由调用方
   *        (PlateStage/PlateBinding)在落座时算好缓存, 本层只管画
   * @returns {boolean} 是否生效(含"值未变跳过重画"的 true)
   */
  applySpot(plateId, bands) {
    const plate = this._plates.get(String(plateId || ''))
    if (!plate || !Array.isArray(bands) || !bands.length) return false
    if (!plate.trace && !bands.some((band) => Number(band?.fill) > 1e-3)) {
      // 全零不建资源: spot 通道从 t=0 就在逐帧求值, 起点恒为 0
      return false
    }
    const shapeOf = (band) => (band?.shape === 'rect' ? 'rect' : 'stroke')
    const entry = this._ensureTrace(plate)
    const prev = entry.spot
    if (prev && prev.length === bands.length
      && prev.every((band, i) => band.uv === bands[i]?.uv
        && band.shape === shapeOf(bands[i])
        && Math.abs(band.fill - (Number(bands[i]?.fill) || 0)) < 1e-3)) {
      return true
    }
    // shape 必须一起存进 entry: 这一层是 _recompose 唯一的入参来源, 漏了它分流就永远走默认
    entry.spot = bands.map((band) => ({
      uv: band.uv,
      fill: Math.min(1, Math.max(0, Number(band.fill) || 0)),
      shape: shapeOf(band),
    }))
    this._recompose(plate)
    return true
  }

  /**
   * 功能: 更新一块板的溶剂润湿 —— `wet` 连续通道与实时页"展开板"的共同落地点.
   *
   * 除了颜色遮罩上的半透明压暗, 首次润湿还给克隆材质挂**第二张画布**当 roughnessMap
   * (湿区更光泽的那一半"湿感", 见 drawWetRoughness 的注释)。roughnessMap 一旦挂上就
   * 不摘 —— 归池后画布重画成全白(粗糙度不变), 避免材质程序反复重编译。
   *
   * @param {string} plateId 板号
   * @param {number} front 前沿进度 0..1(相对 region 声明的前沿目标高度)
   * @param {object} uv 润湿区整体的 UV 矩形(bandToUv 的结果, 含 fill 前沿)
   * @returns {boolean} 是否生效(含"值未变跳过重画"的 true)
   */
  applyWet(plateId, front, uv) {
    const plate = this._plates.get(String(plateId || ''))
    if (!plate || !uv) return false
    const value = Math.min(1, Math.max(0, Number(front) || 0))
    if (!plate.trace && value < 1e-3) return false
    const entry = this._ensureTrace(plate)
    if (entry.wet && entry.wet.uv === uv && Math.abs(entry.wet.front - value) < 1e-3) return true
    if (!entry.wetCanvas) {
      entry.wetCanvas = this._canvasFactory()
      entry.wetCanvas.width = SCRAPE_CANVAS_SIZE
      entry.wetCanvas.height = SCRAPE_CANVAS_SIZE
      entry.wetTexture = new THREE.CanvasTexture(entry.wetCanvas)
      // roughnessMap 是线性数据通道, 不设 SRGB(设了会把 0.56 的灰采成 0.27, 湿区亮过头)
      entry.material.roughnessMap = entry.wetTexture
      entry.material.needsUpdate = true
    }
    entry.wet = { uv, front: value }
    this._recompose(plate)
    return true
  }

  /**
   * 功能: 按**实际刀路**画一块板的刮取结果 —— 实时页"废板"的落地点.
   *
   * 与 applyScrape(演示通道的标称条带前沿)互斥使用: 实时页的废板是**终态**
   * (全部 pass 已刮完), 沿真实折线以刀宽描边擦除即是真机刮出的露玻璃区,
   * 不需要前沿动画也不需要残余薄板。
   *
   * @param {string} plateId 板号
   * @param {{points: Array<{u,v}>, widthUv: number}|null} path pathToUv 的结果 + 刀宽
   *        (UV 归一); null = 清掉刀路层
   * @returns {boolean} 是否生效
   */
  applyScrapePath(plateId, path) {
    const plate = this._plates.get(String(plateId || ''))
    if (!plate) return false
    if (!plate.trace && !path) return false
    const entry = this._ensureTrace(plate)
    if (entry.path === path) return true
    entry.path = path || null
    this._recompose(plate)
    return true
  }

  /**
   * 整幅重画一块板的痕迹画布(点样色带 → 润湿 → 刮取, 次序即工艺次序).
   *
   * 全量合成而不是增量补画: 画面只由当前痕迹状态决定, 与到达顺序无关 ——
   * 这是三种痕迹共用一张画布还能保持幂等(seek 契约)的关键。
   *
   * @param {object} plate 板实体
   * @returns {void}
   */
  _recompose(plate) {
    const entry = plate.trace
    if (!entry) return
    const layers = {}
    if (entry.spot) {
      // 按 applySpot 存下的 shape 分流: 扫线带走"圆点滑过"的圆帽轨迹, 实测谱带走矩形
      const strokes = entry.spot.filter((band) => band.shape !== 'rect')
      const rects = entry.spot.filter((band) => band.shape === 'rect')
      if (strokes.length) {
        layers.spotStrokes = strokes
          .map((band) => progressStroke(band.uv, band.uv.fill, band.fill))
          .filter(Boolean)
      }
      if (rects.length) {
        layers.spotRects = rects
          .map((band) => progressRect(band.uv, band.uv.fill, band.fill))
          .filter(Boolean)
      }
    }
    if (entry.wet) {
      const rect = progressRect(entry.wet.uv, entry.wet.uv.fill, entry.wet.front)
      if (rect) {
        layers.wetRect = rect
        const fill = entry.wet.uv.fill
        // 前沿线画在推进沿上: 推进沿是被进度裁的那条边(dir≥0 裁高端, 反之低端)
        layers.wetFront = fill?.coord === 'v'
          ? { coord: 'v', at: (fill?.dir ?? 1) >= 0 ? rect.v1 : rect.v0 }
          : { coord: 'u', at: (fill?.dir ?? 1) >= 0 ? rect.u1 : rect.u0 }
      }
    }
    if (entry.scrape) {
      layers.loosen = entry.scrape.loosen
      layers.clear = entry.scrape.clear
    }
    if (entry.path) layers.path = entry.path
    drawTrace(entry.canvas, layers)
    entry.texture.needsUpdate = true
    if (entry.wetTexture) {
      drawWetRoughness(entry.wetCanvas, layers.wetRect || null)
      entry.wetTexture.needsUpdate = true
    }
  }

  /**
   * 功能: 摆两块残余硅胶薄板 —— 分层刮取"凹坑"的底。
   *
   * 薄板从**硅胶与玻璃的交界面**往外长(与 layerTransforms 的"厚度一律向外生长"同源),
   * 所以坑越深、薄板越薄, 玻璃面始终不动。silicaUp=false(料仓里硅胶朝下)时生长方向
   * 取反 —— 虽然刮取只发生在刮板台(硅胶朝上), 但板会被搬走, 搬走后仍要画对。
   *
   * @param {object} plate 板实体
   * @param {object} uvBand bandToUv 的结果
   * @param {object|null} cut 本刀已收的 UV 子矩形
   * @param {object} levels residualLevels 的结果
   * @returns {void}
   */
  _applyResidual(plate, uvBand, cut, levels) {
    const needed = levels.cut > 1e-6 || (levels.pass >= 2 && levels.prior > 1e-6)
    if (!plate.residual) {
      if (!needed) return
      this._createResidual(plate)
    }
    const layers = layerTransforms(plate.geom, this.silicaMm)
    const [width, silicaM, length] = layers.silica.scale
    const silicaUp = plate.geom?.silicaUp !== false
    // 交界面(贴玻璃那一侧)的 y, 薄板由此向外生长
    const seamY = silicaUp ? layers.silica.y - silicaM / 2 : layers.silica.y + silicaM / 2

    const put = (mesh, rect, ratio) => {
      const local = ratio > 1e-6 ? uvRectToLocal(rect, width, length) : null
      if (!local) {
        mesh.visible = false
        return
      }
      const thick = silicaM * ratio
      mesh.visible = true
      mesh.scale.set(local.width, thick, local.length)
      mesh.position.set(
        layers.x + local.x,
        silicaUp ? seamY + thick / 2 : seamY - thick / 2,
        layers.z + local.z,
      )
    }
    // 本刀已收段落到第 pass 层; 未收段仍停在第 pass−1 层(第 1 刀时它还是原厚的满硅胶层,
    // 由未被 discard 的遮罩区表达, 不用薄板)
    put(plate.residual.cut, cut, levels.cut)
    put(plate.residual.prior, levels.pass >= 2 ? bandComplement(uvBand, cut) : null, levels.prior)
    // 记下入参: 板被搬走/换规格/改硅胶厚度时 _applyLayers 要按新盒重摆薄板。
    // 不记的话 applyScrape 的幂等早返回会让薄板停在旧盒的位置上(板动了、坑没跟着动)。
    plate.residualState = { uvBand, cut, levels }
  }

  /** 取一份痕迹遮罩资源(池里有就复用), 复位痕迹状态并接住当下的补光亮度。 */
  _acquireTrace() {
    const entry = this._tracePool.pop() || this._createTrace()
    if (entry.material.emissive) {
      entry.material.emissive.setRGB(this._flash, this._flash, this._flash)
      entry.material.emissiveIntensity = this._flash * FLASH_PEAK
    }
    entry.last = null
    entry.spot = null
    entry.wet = null
    entry.scrape = null
    entry.path = null
    if (entry.wetCanvas) {
      // 归池的资源可能带着上一块板的湿区粗糙度 —— 白化(粗糙度不变)后再入场
      drawWetRoughness(entry.wetCanvas, null)
      entry.wetTexture.needsUpdate = true
    }
    return entry
  }

  /** 造一份痕迹遮罩资源。克隆而不是新建材质: 带痕迹的板与普通板必须同物性, 只多遮罩。 */
  _createTrace() {
    const canvas = this._canvasFactory()
    canvas.width = SCRAPE_CANVAS_SIZE
    canvas.height = SCRAPE_CANVAS_SIZE
    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    const material = this.silicaMaterial.clone()
    material.name = 'MAT_TLC_SILICA_TRACE'
    material.map = texture
    material.needsUpdate = true
    return {
      canvas,
      texture,
      material,
      // 润湿粗糙度画布(applyWet 首用时懒建; 建了就跟资源走, 归池只白化不摘)
      wetCanvas: null,
      wetTexture: null,
      // 各痕迹层的当前状态(_recompose 的唯一输入)
      spot: null,
      wet: null,
      scrape: null,
      path: null,
      // scrape 通道的幂等比较帧(loosen/clear/pass); PlateStage._scrapeStatus 也读它
      last: null,
    }
  }

  /**
   * 摘掉一块板的痕迹遮罩并把资源归池。
   *
   * 归池不 dispose: 向后 seek 的重放路径每次都经 release() 走到这里, 逐次销毁
   * 材质/纹理会造成 seek 级 GC 与重编译抖动 —— 与板池不销毁几何同一条理由。
   */
  _releaseTrace(plate) {
    // 残余薄板与遮罩同生同灭: 板池是复用的, 薄板不收的话下一块板出场就自带一个凹坑
    // (向后 seek 的重放路径每次都经这里)。Mesh 留着不删, 只隐藏 —— 与板池不销毁几何同理。
    if (plate?.residual) {
      plate.residual.cut.visible = false
      plate.residual.prior.visible = false
    }
    plate.residualState = null
    if (!plate?.trace) return
    plate.silica.material = this.silicaMaterial
    this._tracePool.push(plate.trace)
    plate.trace = null
  }

  /**
   * 功能: 补光打在板上的响应 —— 硅胶面按 0..1 短暂提亮.
   *
   * 为什么闪光要落在板上而不是灯上: 视觉纠偏那盏补光灯装在**下相机周围、机台盖板玻璃
   * 下方 44.5mm**, 从任何正常机位看过去都被台面挡着(实测开/关两态画面几乎无差)。
   * 真机上人眼看见的"闪"也正是光打在板上的那一下, 不是看见灯泡本身。
   *
   * 只提亮**硅胶层**: 它是不透明哑光白的粉末面, 是接光的那一面; 玻璃层透射, 提亮它
   * 只会发灰。峰值取得克制 —— 硅胶 base 已经是接近白的 #f1f3f5, 再叠太多会顶到
   * Neutral 色调映射的削波, 读起来像自发光片而不是被照亮的粉面。
   *
   * ⚠ 硅胶材质是全场共享的(全部板共用一份), 所以这是"整场板一起亮"。片段里只有一块板,
   * 无影响; 将来实时页要按板分别打光, 得先给受照那块板克隆一份材质。
   *
   * @param {number} level 0..1 补光强度
   * @returns {boolean} 是否真的变了
   */
  setFlash(level) {
    const value = Math.min(1, Math.max(0, Number(level) || 0))
    if (Math.abs(value - this._flash) < 1e-4) return false
    this._flash = value
    const material = this.silicaMaterial
    if (material.emissive) {
      material.emissive.setRGB(value, value, value)
      material.emissiveIntensity = value * FLASH_PEAK
    }
    // 带痕迹的板用的是克隆材质, 补光要一并写到(_acquireTrace 也会接住当下值, 两处
    // 闭环)。演示页不挂 TwinBindings 的外壳绑定, 不存在 ownedByLights 式互顶; 两条
    // 链将来合流时, 以"痕迹克隆归本层独占"为界(参照 TwinBindings._bindEnclosure)。
    for (const plate of this._plates.values()) {
      const cloned = plate.trace?.material
      if (cloned?.emissive) {
        cloned.emissive.setRGB(value, value, value)
        cloned.emissiveIntensity = value * FLASH_PEAK
      }
    }
    return true
  }

  // ── 料仓堆叠 ────────────────────────────────────────────────────────────

  /**
   * 功能: 按张数更新一个料仓的堆叠.
   *
   * @param {string} magazineId 'feed' | 'waste'
   * @param {object} spec
   * @param {object} spec.geom 料仓模板锚点的 measurePlateAnchor 结果
   * @param {THREE.Object3D} spec.parent 堆叠挂载的父级(应为 1Z/2Z 滑车, 这样堆随轴升降)
   * @param {number} spec.count 张数
   * @param {number} [spec.pitchM] 实测堆叠节距(米); 未标定(<=0)时回退单板总厚
   * @returns {boolean} 是否更新
   */
  setMagazine(magazineId, { geom, parent, count = 0, pitchM = 0 } = {}) {
    const key = String(magazineId || '')
    if (!key || !geom || !parent) return false

    let entry = this._magazines.get(key)
    if (!entry) {
      entry = this._createStack(key)
      this._magazines.set(key, entry)
    }
    if (entry.glass.parent !== parent) {
      parent.add(entry.glass)
      parent.add(entry.silica)
    }
    entry.geom = geom
    entry.count = Math.max(0, Math.min(MAX_STACK, Math.floor(Number(count) || 0)))
    entry.pitchM = Number(pitchM) > 0 ? Number(pitchM) : 0
    this._writeStack(entry)
    return true
  }

  /**
   * 功能: 板仓堆的拾取目标 (供 MaterialPickController 建索引).
   *
   * 账本对板仓只有"张数"没有逐板身份, 故语义上整堆是一个拾取目标 —— 调用方拿到
   * instanceId 也不该当板号用。count=0 时 InstancedMesh 天然不可命中 (空仓无 3D
   * 入口, 二维物料页兜底)。
   * @returns {Array<{magazine: string, meshes: THREE.Object3D[]}>} 拾取目标
   */
  magazineHitTargets() {
    return [...this._magazines.entries()].map(([magazine, entry]) => ({
      magazine,
      meshes: [entry.glass, entry.silica],
    }))
  }

  _createStack(magazineId) {
    // 阴影标志位与单板同一条规则(见 applyShadowFlags); 堆叠是 InstancedMesh,
    // 让硅胶层投影只多 1 个绘制调用, 与张数无关
    const glass = applyShadowFlags(
      new THREE.InstancedMesh(UNIT_BOX, this.glassMaterial, MAX_STACK), false,
    )
    const silica = applyShadowFlags(
      new THREE.InstancedMesh(UNIT_BOX, this.silicaMaterial, MAX_STACK), true,
    )
    for (const mesh of [glass, silica]) {
      mesh.frustumCulled = true
      mesh.count = 0
      mesh.userData[SEMANTIC_TAG_KEY] = 'consumable'
    }
    glass.name = `PLATE_STACK_${magazineId}_GLASS`
    silica.name = `PLATE_STACK_${magazineId}_SILICA`
    return { glass, silica, geom: null, count: 0, pitchM: 0 }
  }

  /**
   * 写堆叠的实例矩阵。
   *
   * 两层的上下顺序与单板走同一条规则(layerTransforms 读 geom.silicaUp) —— 料仓是
   * **硅胶朝下**, 于是玻璃面朝上, 正好给 rotary-down 的吸盘贴。
   *
   * ⚠ 偏移**必须先按锚点标准帧旋转**再加到盒心上。此前是逐分量相加, 那隐含假定
   * 四元数是单位阵 —— 只有恰好轴对齐时才碰巧对, 锚点一带旋转整堆板就会飞到别处。
   *
   * 节距优先用现场实测值 —— 三维堆高必须与真机 feedlift.probe_stack 的板数换算同源,
   * 否则堆出来的高度和实机对不上。
   */
  _writeStack(entry) {
    const { geom } = entry
    if (!geom) return
    const layers = layerTransforms(geom, this.silicaMm)
    const pitch = entry.pitchM > 0 ? entry.pitchM : layers.totalM
    const bottom = geom.center.y - geom.thickM / 2

    _quat.copy(geom.quaternion)
    for (let i = 0; i < entry.count; i += 1) {
      const lift = bottom + i * pitch     // 第 i 张板的底面(沿标准帧 +Y)

      for (const [mesh, layer] of [[entry.silica, layers.silica], [entry.glass, layers.glass]]) {
        _pos.set(layers.x, lift + (layer.y - bottom), layers.z)
          .applyQuaternion(_quat)
          .add(geom.position)
        _scale.set(...layer.scale)
        mesh.setMatrixAt(i, _mat.compose(_pos, _quat, _scale))
      }
    }
    entry.glass.count = entry.count
    entry.silica.count = entry.count
    entry.glass.instanceMatrix.needsUpdate = true
    entry.silica.instanceMatrix.needsUpdate = true
    entry.glass.computeBoundingSphere()
    entry.silica.computeBoundingSphere()
  }

  /** 某料仓当前画了几张(供测试与 HUD 核对)。 */
  magazineCount(magazineId) {
    return this._magazines.get(String(magazineId || ''))?.count ?? 0
  }

  /** 本层新增的绘制调用数(供性能核算: 活动板 ×2 + 每仓 ×2)。 */
  drawCallEstimate() {
    let calls = this._plates.size * 2
    for (const entry of this._magazines.values()) {
      if (entry.count > 0) calls += 2
    }
    return calls
  }

  /** 释放本层自造的材质与实例网格。几何是全场共享的 UNIT_BOX, 不在这里 dispose。 */
  dispose() {
    for (const plateId of [...this._plates.keys()]) this.release(plateId)
    this._pool.length = 0
    // release 已把活动板的痕迹资源归池, 这里统一销毁(池化只到本层生命周期为止)
    for (const entry of this._tracePool) {
      entry.texture.dispose()
      entry.wetTexture?.dispose()
      entry.material.dispose()
    }
    this._tracePool.length = 0
    for (const entry of this._magazines.values()) {
      entry.glass.parent?.remove(entry.glass)
      entry.silica.parent?.remove(entry.silica)
      entry.glass.dispose()
      entry.silica.dispose()
    }
    this._magazines.clear()
    this.glassMaterial.dispose()
    this.silicaMaterial.dispose()
    this.cutSilicaMaterial.dispose()
  }
}
