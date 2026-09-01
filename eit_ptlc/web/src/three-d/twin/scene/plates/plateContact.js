/**
 * 功能: 吸盘的**柔性接触** —— 板顶到硬表面时吸盘压缩, 而不是把板顶进去.
 *
 * 为什么需要它: 上一轮把持板位姿刚性钉死在吸盘唇口(见 plateGeometry.suctionMountLocal),
 * 治好了"吸盘扎穿板面", 却把穿模搬了个家 —— 放板时板会直接扎进展缸/座面。用户指出根因:
 * **SAB22 是波纹吸盘, 末端本来就有柔性**。板悬空时它就在唇口; 一旦碰到硬东西, 该缩的是
 * 吸盘, 不是把板压进去。
 *
 * 行程 6.0mm 有两条独立依据(见 rig_map 的 cup_stroke_mm 注释): CAD 波纹段实测 18mm/2 褶,
 * 以及 verify_plate_seats 实测各站需要吸收 0~5.4mm。
 *
 * ⚠ **不许有记忆**。ClipPlayer 的 seek 语义是"向后跳 = home 清场 + 重放 [0,t]"
 * (见 PlateStage.js 头注释), 所以这里每帧都从重算的**自由位姿**出发再修一次 ——
 * 是 g(f(t)), 仍是 t 的纯函数。绝不允许弹簧/阻尼/按 delta 累加, 也绝不允许"在上一帧
 * 结果上再修一次"(连续帧会把修正累乘, 板会一路往回缩)。
 *
 * ⚠ **板的回退与吸盘的压缩必须同帧、由同一个 penetration 分发**。这是 TwinBindings 泵那段
 * 头注释记的同一条纪律: 让两个自由度分开取值, 迟早有一帧对不上, 表现是"柱塞和液面之间
 * 脱开一条缝" —— 这里则是"板浮起来了但吸盘没压"。
 */
import * as THREE from 'three'
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from 'three-mesh-bvh'

import { plateFaceLocalY } from './plateGeometry.js'

// 与 PickController 同款安装(重复赋值无害, 且两边都装才不依赖加载顺序)
THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree
THREE.Mesh.prototype.raycast = acceleratedRaycast

/** 射线起点相对板远端面往回让的距离(米) = 行程 + 余量。余量给示教残差留地方。 */
const BACK_MARGIN_M = 0.004
/** 射线越过板远端面继续看多远(米)。只用来确认"还没碰上", 不需要看远。 */
const LOOK_AHEAD_M = 0.002
/** 采样点从板边往里收多少(米) —— 贴着边取样会被相邻件的倒角/缝隙误命中。 */
const SAMPLE_INSET_M = 0.002
/** 小于这个值的穿透当作没有(浮点噪声与 CAD 贴合公差)。 */
const EPS_M = 1e-5

const _v = new THREE.Vector3()
const _center = new THREE.Vector3()
const _size = new THREE.Vector3()
const _axisWorld = new THREE.Vector3()
const _origin = new THREE.Vector3()
const _sphereCenter = new THREE.Vector3()
const _quat = new THREE.Quaternion()
const _box = new THREE.Box3()
// 断吸后求"唇口压在哪块落座板上"用的暂存(与上面同一套复用约定, 不每帧 new)
const _lip = new THREE.Vector3()
const _lipLocal = new THREE.Vector3()
const _inv = new THREE.Matrix4()

/** overlap() 专用暂存(只在探针里跑, 但照样别在里面 new) */
const _toPlate = new THREE.Matrix4()
const _plateBox = new THREE.Box3()
const _probeBox = new THREE.Box3()
const _ta = new THREE.Vector3()
const _tb = new THREE.Vector3()
const _tc = new THREE.Vector3()
const _cut0 = new THREE.Vector3()
const _cut1 = new THREE.Vector3()
const _sample = new THREE.Vector3()

/** 交线取样点数。与 blender_plate_clearance._SLICE_SAMPLES 同一口径。 */
const SLICE_SAMPLES = 9

/**
 * 功能: 静止三角形与**板中面**的交线, 伸进板轮廓内最深多少(米). 纯函数, 可脱离场景单测.
 *
 * 与 `pipeline/blender_plate_clearance.py::slice_intrusion()` 是同一套代数, 逐句对应 ——
 * 那边的头注释论证了为什么量"离板沿多远"而不是"交叠了多少面":
 *   · 板进出仓口必然与仓壁擦肩, 交线贴着板沿, 离沿零点几毫米, 眼睛看不出来;
 *   · 侧壁捅进板面, 交线落在板内, 离沿十几毫米, 一眼就是穿模。
 * 三角形个数分不开这两者。**改这里必须同步改那边**, 否则前端与管线会给出两个数。
 *
 * 板局部系里薄轴恒为 y(板根的标准帧), 面内是 x/z, 板心在 (0, midY, 0)。
 *
 * @param {import('three').Vector3} a 三角形三顶点(板局部系)
 * @param {import('three').Vector3} b
 * @param {import('three').Vector3} c
 * @param {number} midY 板中面在板局部系的 y
 * @param {number} halfW 面内半宽(x)
 * @param {number} halfL 面内半长(z)
 * @returns {number} 最深内侵(米); 不相交或只擦到板外为 0
 */
export function sliceIntrusion(a, b, c, midY, halfW, halfL) {
  const tri = [a, b, c]
  const signed = [a.y - midY, b.y - midY, c.y - midY]
  const crossings = []
  for (let i = 0; i < 3; i += 1) {
    const j = (i + 1) % 3
    if (Math.abs(signed[i]) < 1e-9) crossings.push(tri[i].clone())
    if ((signed[i] > 0) !== (signed[j] > 0) && Math.abs(signed[i] - signed[j]) > 1e-12) {
      crossings.push(tri[i].clone().lerp(tri[j], signed[i] / (signed[i] - signed[j])))
    }
  }
  if (crossings.length < 2) return 0

  _cut0.copy(crossings[0])
  _cut1.copy(crossings[crossings.length - 1])
  let best = 0
  for (let step = 0; step < SLICE_SAMPLES; step += 1) {
    _sample.copy(_cut0).lerp(_cut1, step / (SLICE_SAMPLES - 1))
    // 到最近那条板沿的距离; 落在板外时为负
    const inside = Math.min(halfW - Math.abs(_sample.x), halfL - Math.abs(_sample.z))
    if (inside > best) best = inside
  }
  return Math.max(best, 0)
}

/**
 * 功能: 由穿透量算吸盘压缩与"超行程"的余量(纯函数, 可脱离 three 单测).
 *
 * 超出行程的部分**不被吸收** —— 板照样停在硬表面上, 于是吸盘与板之间露出可见的缝。
 * 这是用户定的表现: 把"这个示教点太深"显出来, 而不是让吸盘无限压缩把错误藏掉。
 *
 * @param {number} penetrationM 自由位姿下板扎进硬表面多深(米, ≥0)
 * @param {number} strokeM 吸盘可压缩行程(米)
 * @returns {{compressionM: number, overshootM: number}}
 */
export function compressionOf(penetrationM, strokeM) {
  const penetration = Number.isFinite(penetrationM) ? Math.max(0, penetrationM) : 0
  const stroke = Number.isFinite(strokeM) ? Math.max(0, strokeM) : 0
  const compression = Math.min(penetration, stroke)
  return { compressionM: compression, overshootM: penetration - compression }
}

/**
 * 功能: 橡胶段的缩放比例. 压缩 c 时唇口正好往回缩 c(见 mountOffsetParent 的补偿平移).
 * @param {number} freeLenM 自由长度(米)
 * @param {number} compressionM 压缩量(米)
 * @returns {number} 0..1 的缩放比
 */
export function rubberScale(freeLenM, compressionM) {
  const free = Number(freeLenM)
  if (!Number.isFinite(free) || free <= 0) return 1
  return Math.min(1, Math.max(0, (free - Math.max(0, compressionM || 0)) / free))
}

/**
 * 功能: 唇口盘还有多少压在板面上(0..1) —— 横向滑出板边时的渐变系数.
 *
 * 唇口是个 ø24mm 的盘, 不是一个点。盘心刚跨过板边缘时它其实还压着大半个面, 完全离开
 * 要再走一个直径。所以按"盘心到板边的有符号距离"在 **±半径** 的带内线性收敛:
 * 盘心还在板内一个半径 → 1, 盘心出板外一个半径 → 0。两轴各算一次再相乘。
 *
 * 这样横向退避时吸盘是平滑长回去的, 与向上抬那条路观感一致 —— 而且仍是纯几何,
 * 不引入任何状态(本文件头注释那条"不许有记忆"的纪律)。
 *
 * 用线性而不是精确的圆-矩形重叠面积: 后者是分段解析式, 代码量大出一个量级, 而这里
 * 只是个观感权重, 单调、连续、两端取到 0/1 就够了。
 *
 * @param {number} offAxisXM 盘心沿板面 X 的 |偏移| 减去板半宽(米, 负=还在板内)
 * @param {number} offAxisZM 同上, 板面 Z 方向
 * @param {number} radiusM 唇口半径(米)
 * @returns {number} 0..1
 */
export function lipSupportedFraction(offAxisXM, offAxisZM, radiusM) {
  const radius = Number(radiusM)
  if (!Number.isFinite(radius) || radius <= 0) {
    // 没有半径信息时退化成"盘心在板内才算压着"的阶跃
    return (offAxisXM <= 0 && offAxisZM <= 0) ? 1 : 0
  }
  const axis = (off) => {
    if (!Number.isFinite(off)) return 0
    return Math.min(1, Math.max(0, (radius - off) / (2 * radius)))
  }
  return axis(offAxisXM) * axis(offAxisZM)
}

/**
 * 功能: 唇口压在一块**已落座**的板上时该压多少(米).
 *
 * 断吸之后吸盘不该立刻弹回自由长 —— 波纹段还被板面顶着, 要等机械臂抬到唇口脱离板面
 * 才逐渐长回去。压缩量就等于"自由唇口越过板贴合面的深度", 于是:
 *   放板那一刻 深度 == carryCompression ⇒ 与持板态**无缝**, 不跳变;
 *   机械臂抬起  深度递减              ⇒ 吸盘逐渐增长;
 *   抬过一个 carryCompression 深度归零 ⇒ 自然脱离。
 * 全程只依赖当帧的两个位姿, 没有积分器, seek 免费正确。
 *
 * @param {number} penetrationM 自由唇口越过板贴合面的深度(米, 正=扎进板体那一侧)
 * @param {number} supported 唇口盘压在板上的比例(见 lipSupportedFraction)
 * @param {number} maxM 压缩上限(持板压缩 + 行程)
 * @returns {number} 压缩量(米)
 */
export function plateRestCompression(penetrationM, supported, maxM) {
  const penetration = Number.isFinite(penetrationM) ? penetrationM : 0
  const limit = Number.isFinite(maxM) && maxM > 0 ? maxM : 0
  const weight = Number.isFinite(supported) ? Math.min(1, Math.max(0, supported)) : 0
  return Math.min(Math.max(penetration, 0), limit) * weight
}

export class PlateContact {
  /**
   * @param {object} opts
   * @param {object} opts.manifest device-manifest(取机器人/工具子树做排除集)
   * @param {Map<string, THREE.Object3D>} opts.nodeIndex loadModel 建的节点索引
   * @param {THREE.Object3D} opts.root 整机根节点
   * @param {object} opts.grip manifest 的 actuators[rob_flip_suction].plateGrip
   * @param {THREE.Object3D[]} [opts.excludeExtra] 额外要排除的子树(如板锚点)
   */
  constructor({ manifest, nodeIndex, root, grip, excludeExtra = [] } = {}) {
    this.grip = grip || null
    this.strokeM = Number(grip?.strokeM) || 0
    /**
     * 被吸住时波纹段**已经**压掉的量(米)。板骑的是压缩后的唇口(见 suctionMountLocal),
     * 所以杯子也必须照这个量画 —— 否则杯子会以自由长度戳穿板面 17.8mm。
     * 它是本层压缩的**基线**, strokeM 是在它之上还能再让的余量。
     */
    this.carryCompressionM = Number(grip?.carryCompressionM) || 0
    this.raycaster = new THREE.Raycaster()
    // 只要最近命中; BVH 据此提前返回, 是本方案性能的第一根支柱
    this.raycaster.firstHitOnly = true
    this.raycaster.near = 0
    this.raycaster.far = this.strokeM + BACK_MARGIN_M + LOOK_AHEAD_M

    /** @type {Set<THREE.BufferGeometry>} 本层建的 BVH(供 dispose 释放) */
    this._ownedTrees = new Set()
    this._collidables = this._collectCollidables(manifest, nodeIndex, root, excludeExtra)
    this._rubbers = this._bindRubbers(nodeIndex, grip, manifest)
    /**
     * 翻转节点 —— 断吸后求"唇口压在哪块落座板上"要用它把 contactLocalM 变到世界。
     * @type {THREE.Object3D|null}
     */
    this._flip = (() => {
      const spec = (manifest?.actuators || []).find((item) => item.plateGrip)
      return (spec?.node ? nodeIndex?.get(spec.node) : null) || null
    })()
    /**
     * 判"唇口压着这块板"的最大深度(米)。超过一整个橡胶段自由长就不是压着它了 ——
     * 典型是机械臂从板**下方**掠过, 那时唇口在板面另一侧几百毫米, 不该被当成压缩。
     */
    this._maxReachM = Math.max(...this._rubbers.map((cup) => cup.freeLenM), 0) || this.strokeM
    /** @type {object|null} 上一次求解结果(只读诊断, 不参与下一帧计算) */
    this.last = null
  }

  /** 本层是否可用(常量齐、橡胶段找得到、有可碰几何)。 */
  get ready() {
    return Boolean(this.grip && this._rubbers.length && this._collidables.length)
  }

  /**
   * 功能: 收集可碰几何 —— 整机, 但排除机器人子树、工具子树与调用方指定的节点.
   *
   * 排除集**从 manifest 派生**(`robot.glbNode` / `tools[].glbNode` / `plateContactIgnore`),
   * 不硬编码节点名。排机器人与工具是因为板本来就被它们拿着, 算自碰撞没有意义;
   * 排板锚点是因为那些 CAD 玻璃盒已被 bindPlateAnchors 隐藏, 拿看不见的东西去顶板,
   * 现象无从解释。
   *
   * `plateContactIgnore` 排的是"板本来就该待在里面/坐在上面"的结构 —— 那里的"扎进去"
   * 是建模约定或正常工况而非错误, 不排掉就会每次经过闪一下缝(2026-08-06 实测两处:
   * 点样座/刮板台把玻璃画成沉进放置平台 1.5mm; 取板时板本就嵌在料仓框架内 25.7mm)。
   * 出处、实测值与"什么时候该把它删掉"写在 rig_map 的 `plate_contact` 段。
   *
   * 用**对象身份**而不是路径判断: 工具会在停放位与法兰之间换父, 路径会变, 对象不会。
   */
  _collectCollidables(manifest, nodeIndex, root, excludeExtra) {
    // 两级排除, 语义完全不同, 不能混:
    //   excluded —— 机器人/工具/板锚点。这些**根本不是障碍物**(工具本来就该贴着板,
    //               锚点是看不见的位姿来源), 任何用途下都要排。
    //   ignored  —— rig_map 的 `plate_contact.ignore`。这些是"已知的 CAD 建模重叠",
    //               排掉只是为了让**接触求解**别抖; 它们是实打实的几何, 诊断必须看得见。
    // ⚠ 2026-08-06: 这两级此前是一锅排的, 而 ignore 里有一条 `subtree: ST_FEEDLIFT`
    //   —— 整个上下料仓站。于是"板与料仓相不相交"这件事**没有任何判据看得见**,
    //   用户报了两轮穿模都查不到。诊断用的 overlap() 走 _allCollidables, 不吃 ignore。
    const excluded = new Set()
    const ignored = new Set()
    for (const node of [
      nodeIndex?.get(manifest?.robot?.glbNode),
      ...((manifest?.tools || []).map((tool) => nodeIndex?.get(tool.glbNode))),
      ...excludeExtra,
    ]) node?.traverse((child) => excluded.add(child))
    for (const path of manifest?.plateContactIgnore || []) {
      nodeIndex?.get(path)?.traverse((child) => ignored.add(child))
    }

    const contact = []
    const all = []
    root?.traverse((child) => {
      if (!child.isMesh || excluded.has(child)) return
      if (!child.geometry?.attributes?.position) return
      if (!child.geometry.boundingSphere) child.geometry.computeBoundingSphere()
      // 与 PickController 同款守卫: 建过树的不重复建(两层共用同一棵)
      if (!child.geometry.boundsTree) {
        child.geometry.computeBoundsTree()
        this._ownedTrees.add(child.geometry)
      }
      all.push(child)
      if (!ignored.has(child)) contact.push(child)
    })
    // 两个数组共用同一批 mesh 与同一批 BVH 树, 多存一份引用不额外占几何内存
    this._allCollidables = all
    return contact
  }

  /** 解析两只橡胶段并缓存 base(绝对写的基准; home/放板时要还原回去)。 */
  _bindRubbers(nodeIndex, grip, manifest) {
    // 翻转节点: 吸盘轴与接触面都表达在它的局部系里
    const flipSpec = (manifest?.actuators || []).find((item) => item.plateGrip)
    const flip = flipSpec?.node ? nodeIndex?.get(flipSpec.node) : null
    flip?.updateWorldMatrix(true, false)

    const out = []
    for (const spec of grip?.rubbers || []) {
      const node = nodeIndex?.get(spec.node)
      if (!node) continue
      node.updateWorldMatrix(true, false)
      out.push({
        node,
        scaleAxis: ['x', 'y', 'z'][Number(spec.scaleAxis) || 0],
        freeLenM: Number(spec.freeLenM) || 0,
        mountOffset: this._mountOffsetOf(node, spec, grip, flip),
        baseScale: node.scale.clone(),
        basePosition: node.position.clone(),
      })
    }
    return out
  }

  /**
   * 功能: 算"缩放时要补的平移" —— **在运行期场景里实测**, 不用 manifest 那个数.
   *
   * 为什么不能用 manifest 的 `mountOffsetParent`(2026-08-06 定案):
   *   它是**节点局部**量, 而管线是拿 `work/machine.full.glb` 算的, 前端加载的却是
   *   04 压缩后的 `models/machine.official-cr5.glb`。KHR_mesh_quantization 会把反量化
   *   scale 烘进节点、并顺带挪走节点原点 —— 同一只橡胶杯, 原点在 full 里距唇口 63.57mm,
   *   在压缩版里只有 17.50mm。于是管线算出的 +28.57mm 用在压缩版上就把杯子往**外**推,
   *   持板时两只杯从板面里穿出去(用户 2026-08-05/06 连报两次)。
   *   **节点局部的平移量在两份 GLB 之间不可搬运。**
   *   而且管线也修不了这一条: 04 压缩排在两条 manifest **之后**(见 _rebuild_steps),
   *   生成契约的时候压缩版还不存在。只有运行期知道自己那份 GLB 的节点原点。
   *
   * 代数: 缩放绕节点原点发生, 于是 唇口(s) = 原点 + offset·(1−s) + d·s, 其中 d = 原点→唇口。
   * 要求 唇口(s) = 唇口(1) − c 且 c = freeLen·(1−s), 解得 **offset = (d − freeLen)·轴**。
   * d 由运行期实测(接触面与节点原点都在场景里), 于是与量化与否无关。
   *
   * @returns {THREE.Vector3} 父空间的补偿平移; 取不到翻转节点时退回 manifest 值
   */
  _mountOffsetOf(node, spec, grip, flip) {
    const fallback = () => new THREE.Vector3().fromArray(spec.mountOffsetParent || [0, 0, 0])
    if (!flip || !Array.isArray(grip?.axisLocal) || !Array.isArray(grip?.contactLocalM)) {
      return fallback()
    }
    const freeLen = Number(spec.freeLenM) || 0
    if (!(freeLen > 0)) return fallback()

    const axisWorld = new THREE.Vector3().fromArray(grip.axisLocal).normalize()
      .applyQuaternion(flip.getWorldQuaternion(new THREE.Quaternion())).normalize()
    const contactWorld = new THREE.Vector3().fromArray(grip.contactLocalM)
      .applyMatrix4(flip.matrixWorld)
    const originWorld = node.getWorldPosition(new THREE.Vector3())
    // d = 原点→唇口 沿吸盘轴的有符号距离(米)
    const d = contactWorld.sub(originWorld).dot(axisWorld)

    const parent = node.parent
    if (!parent) return fallback()
    // 用**两点之差**换算到父空间: 父级带旋转/缩放时也对(比只转方向稳)
    const from = parent.worldToLocal(originWorld.clone())
    const to = parent.worldToLocal(
      originWorld.clone().addScaledVector(axisWorld, d - freeLen),
    )
    return to.sub(from)
  }

  /**
   * 功能: 求解一块持板的接触, 并**同帧**把板回退与吸盘压缩都写下去.
   *
   * 调用前板必须已经摆在**自由位姿**上(suctionMountLocal 的结果)且世界矩阵已更新 ——
   * 本方法在它基础上只做一次减法, 不读上一帧的任何结果。
   *
   * @param {THREE.Object3D} plateRoot 板的根 Group(已挂在翻转节点下)
   * @param {object} geom 板的实测 geom(要 widthM/lengthM/silicaUp)
   * @param {number} silicaMm 当前硅胶层厚度(mm)
   * @returns {{penetrationM: number, compressionM: number, overshootM: number}}
   */
  resolve(plateRoot, geom, silicaMm, extraCompressionM = 0) {
    const idle = { penetrationM: 0, compressionM: 0, overshootM: 0 }
    if (!this.ready || !plateRoot?.parent) {
      // 手上有板但本层不可用(常量缺/无可碰几何)时, 杯子仍要停在**持板压缩态** ——
      // 板已经按压缩后的唇口摆好了, 这时把杯子放回自由长度就会当场戳穿板面。
      // 真正"手上没板"才复位到自由长度。
      if (plateRoot?.parent) this._writeCups(this.carryCompressionM)
      else this.releaseCups()
      this.last = idle
      return idle
    }

    plateRoot.updateWorldMatrix(true, false)
    // 吸盘轴(局部) -> 世界。板体在接触面的 +axis 一侧, 所以"往回退"就是 −axisWorld。
    _axisWorld.fromArray(this.grip.axisLocal).normalize()
      .applyQuaternion(plateRoot.parent.getWorldQuaternion(_quat)).normalize()

    const penetration = this._probe(plateRoot, geom, silicaMm)
    if (penetration > EPS_M) {
      // 板停在硬表面上: 沿 −axis 退回整个穿透量(局部系里减, 因为 position 是父空间量)
      _v.fromArray(this.grip.axisLocal).normalize().multiplyScalar(-penetration)
      plateRoot.position.add(_v)
      plateRoot.updateMatrix()
      plateRoot.updateWorldMatrix(true, true)
    }

    const { compressionM, overshootM } = compressionOf(penetration, this.strokeM)
    // 杯子按**持板基线 + 本次再让的量 + 调用方额外要的量**画。只写 compressionM 会让
    // 杯子回到自由长度, 以 17.8mm 戳穿板面 —— 板与杯必须同帧、由同一个量分发
    // (见本文件头注释那条纪律)。
    //
    // extraCompressionM 是给"板被别的机制挪过"用的: PlateStage._seatHold 在板还坐在
    // 落点里时按落点摆板(那一段射线探不到, 见 _probe 的五点采样局限), 板因此比刀具
    // 常量位姿更靠近杯体, 杯必须多压同样多才还贴着板面。不透传的话杯会悬在板上方。
    this._writeCups(this.carryCompressionM + compressionM + Math.max(0, extraCompressionM))
    this.last = {
      penetrationM: penetration, compressionM, overshootM,
      extraCompressionM: Math.max(0, extraCompressionM), hit: this._hitName || '',
    }
    return this.last
  }

  /** 从板的远端面打射线网格, 取最深的那一处穿透(米)。 */
  _probe(plateRoot, geom, silicaMm) {
    const { farY } = plateFaceLocalY(geom, silicaMm)
    const halfW = Math.max((geom?.widthM || 0) / 2 - SAMPLE_INSET_M, 0)
    const halfL = Math.max((geom?.lengthM || 0) / 2 - SAMPLE_INSET_M, 0)
    // 板心 + 四角: 四角是必须的 —— approach 略带倾角时先着地的是角, 只测板心会漏
    const samples = [[0, 0], [-halfW, -halfL], [-halfW, halfL], [halfW, -halfL], [halfW, halfL]]
    const back = this.strokeM + BACK_MARGIN_M

    const candidates = this._broadPhase(plateRoot, geom, back)
    if (!candidates.length) return 0

    let deepest = 0
    this._hitName = ''
    for (const [x, z] of samples) {
      _origin.set(x, farY, z).applyMatrix4(plateRoot.matrixWorld).addScaledVector(_axisWorld, -back)
      this.raycaster.set(_origin, _axisWorld)
      const hits = this.raycaster.intersectObjects(candidates, false)
      if (!hits.length) continue
      const depth = back - hits[0].distance
      if (depth > deepest) {
        deepest = depth
        // 记下顶到谁: 超行程报警只说"超了 3mm"没法查, 说"顶在哪个件上"才查得动
        this._hitName = hits[0].object?.userData?.origName || hits[0].object?.name || ''
      }
    }
    return Math.max(0, deepest)
  }

  /**
   * 功能: 当帧板与整机静止几何的**全向**相交测量 —— 纯查询, 不改任何东西.
   *
   * 为什么必须单独有它(2026-08-06 的教训): `resolve()`/`_probe()` 只沿**吸盘轴**打 5 条
   * 射线, 那是为"板顶到硬表面、吸盘该压多少"设计的, 结构上**看不见面内/斜向相交** ——
   * 板横着扫进料仓侧壁时它恒返回 0。于是"取板帧面内偏移=0"验收全绿, 而用户看到的
   * 穿模发生在 0.1s 之后板横扫过侧壁的那一档。判据量错了, 修法再对也白搭。
   *
   * 深度口径与 `pipeline/blender_plate_clearance.py::slice_intrusion()` **逐字相同**:
   * 取静止三角形与**板中面**的交线, 量它伸进板轮廓内最深多少。
   * 不用"交叠三角形个数"(擦边同样能数出几十个面), 也不用"包围盒轴向交叠"(平面三角形
   * 沿自身法向厚度为 0, 任何轴对齐壁面都会被算成 0 深度 —— 那边注释里记着这个坑)。
   *
   * ⚠ 只给探针/验收用, **不要塞进帧循环**: 它对每个候选网格做 BVH shapecast, 比
   * `_probe()` 的 5 条射线贵得多; 而且 `resolve()` 那条链有"不许有记忆/不许累乘"的纪律,
   * 本函数不参与那条链, 也不该去动它。
   *
   * @param {import('three').Object3D} plateRoot 板根(位姿已由调用方写好)
   * @param {object} geom measurePlateAnchor 的结果(要 widthM/lengthM/silicaUp)
   * @param {number} silicaMm 当前硅胶层厚度(mm)
   * @returns {{hits: Array<{name: string, depthMm: number}>, maxDepthMm: number}}
   */
  overlap(plateRoot, geom, silicaMm) {
    const out = { hits: [], maxDepthMm: 0 }
    if (!plateRoot || !geom) return out
    const halfW = (geom.widthM || 0) / 2
    const halfL = (geom.lengthM || 0) / 2
    if (halfW <= 0 || halfL <= 0) return out
    const { contactY, farY } = plateFaceLocalY(geom, silicaMm)
    const midY = (contactY + farY) / 2
    const halfT = Math.abs(farY - contactY) / 2

    plateRoot.updateWorldMatrix(true, false)
    _plateBox.min.set(-halfW, midY - halfT, -halfL)
    _plateBox.max.set(halfW, midY + halfT, halfL)
    _inv.copy(plateRoot.matrixWorld).invert()

    // 粗筛复用射线那条链的实现: 这里不是扫掠而是当帧相交, 所以 back 给 0。
    // 池子走 _allCollidables —— 诊断要看见 plate_contact.ignore 排掉的那些(整个料仓站
    // 就在里面), 否则本判据会与它要查的那个盲区同盲。
    const candidates = this._broadPhase(plateRoot, geom, 0, this._allCollidables)
    for (const mesh of candidates) {
      const tree = mesh.geometry?.boundsTree
      if (!tree) continue
      _toPlate.multiplyMatrices(_inv, mesh.matrixWorld)
      let deepest = 0
      tree.shapecast({
        // 保守粗筛: 把 BVH 节点盒变换进板局部系再与板盒比。Box3.applyMatrix4 取的是
        // 变换后 8 角的 AABB, 只会放大不会漏。
        intersectsBounds: (box) => {
          _probeBox.copy(box).applyMatrix4(_toPlate)
          return _probeBox.intersectsBox(_plateBox)
        },
        intersectsTriangle: (tri) => {
          _ta.copy(tri.a).applyMatrix4(_toPlate)
          _tb.copy(tri.b).applyMatrix4(_toPlate)
          _tc.copy(tri.c).applyMatrix4(_toPlate)
          const depth = sliceIntrusion(_ta, _tb, _tc, midY, halfW, halfL)
          if (depth > deepest) deepest = depth
          return false          // 不早退: 要的是最深那一处, 不是"有没有"
        },
      })
      if (deepest > EPS_M) {
        out.hits.push({
          name: mesh.userData?.origName || mesh.name || '(无名网格)',
          depthMm: deepest * 1000,
          // 这件在不在**接触求解**的池子里。false = 相交了但求解器看不见它, 于是吸盘
          // 不会为它压缩、板也不会被顶回去 —— 是"为什么明明穿了却没人报"的直接答案。
          seenByContact: this._collidables.includes(mesh),
        })
        if (deepest * 1000 > out.maxDepthMm) out.maxDepthMm = deepest * 1000
      }
    }
    out.hits.sort((a, b) => b.depthMm - a.depthMm)
    return out
  }

  /**
   * 粗筛: 只留包围球与"板扫掠体"相交的网格。
   *
   * 这是性能的第二根支柱 —— 整机几百个网格逐个进 BVH 也不便宜, 而真正可能挡路的
   * 每帧只有个位数。球-盒判定比射线-BVH 便宜一两个数量级。
   */
  _broadPhase(plateRoot, geom, back, pool = this._collidables) {
    const reach = back + LOOK_AHEAD_M
    // 世界轴对齐盒, 所以三轴都按板的最长边放 —— 粗筛只要不漏, 宁可宽一点
    const span = Math.max(geom?.widthM || 0, geom?.lengthM || 0) + reach * 2
    _center.set(0, 0, 0).applyMatrix4(plateRoot.matrixWorld)
    _size.set(span, span, span)
    _box.setFromCenterAndSize(_center, _size)
    const out = []
    for (const mesh of pool) {
      if (!mesh.visible) continue
      const sphere = mesh.geometry.boundingSphere
      if (!sphere) continue
      _sphereCenter.copy(sphere.center).applyMatrix4(mesh.matrixWorld)
      const scale = Math.max(
        Math.abs(mesh.matrixWorld.elements[0]),
        Math.abs(mesh.matrixWorld.elements[5]),
        Math.abs(mesh.matrixWorld.elements[10]),
      ) || 1
      if (_box.distanceToPoint(_sphereCenter) <= sphere.radius * scale) out.push(mesh)
    }
    return out
  }

  /** 按压缩量写两只橡胶段: 单轴缩放 + 绕安装端的补偿平移。 */
  _writeCups(compressionM) {
    for (const cup of this._rubbers) {
      const s = rubberScale(cup.freeLenM, compressionM)
      cup.node.scale.copy(cup.baseScale)
      cup.node.scale[cup.scaleAxis] = cup.baseScale[cup.scaleAxis] * s
      cup.node.position.copy(cup.basePosition).addScaledVector(cup.mountOffset, 1 - s)
      cup.node.updateMatrix()
    }
  }

  /**
   * 功能: 手上**没板**时, 按"唇口还压在哪块已落座的板上"求压缩量 —— 断吸后的渐进回弹.
   *
   * 为什么不是直接 releaseCups(): 断吸只是没了吸力, 波纹段仍被板面顶着。一步弹回自由长
   * 会让杯子当场穿过刚放下的那块板(用户 2026-08-06 报的就是这一下)。物理上它该等机械臂
   * 抬到唇口脱离板面才逐渐长回去。
   *
   * 为什么不打射线: 落座的板**不在** `_collidables` 里 —— 那是构造期快照, 当时一块板都
   * 还没建(PlateFaceLayer 懒建), 而且 `intersectObjects(..., false)` 是非递归的。把板补进
   * 可碰集又会给全场共享的 UNIT_BOX 建 BVH, 而 dispose() 会把它 disposeBoundsTree() 掉,
   * 顺手废掉 PickController 的树。板是个位姿已知的薄长方体, 解析算更便宜也更稳。
   *
   * ⚠ 仍是**纯几何**: 只读当帧的吸盘与板位姿, 不读上一帧(见本文件头注释的"不许有记忆")。
   * 同一位姿调两次结果逐位相同, 所以拖进度条来回跨放板段仍可复现。
   *
   * 顺带也管**取板**那一侧: 机械臂下降去吸板时唇口同样被板面顶着, 于是吸盘随接近逐渐
   * 压缩而不是扎进板里, 到吸气那一帧正好接上 carryCompression, 两侧对称。
   *
   * @param {Array<{root: THREE.Object3D, geom: object}>} plates 已落座的板(不含手上那块)
   * @param {number} silicaMm 当前硅胶层厚度(mm)
   * @returns {object|null} 接触状态(诊断用)
   */
  relaxOnPlates(plates, silicaMm) {
    const idle = { penetrationM: 0, compressionM: 0, overshootM: 0 }
    if (!this.grip || !this._flip || !this._rubbers.length || !plates?.length) {
      this.releaseCups()
      return null
    }
    this._flip.updateWorldMatrix(true, false)
    // 自由长唇口的世界位置: contactLocalM 就是自由态唇口(见 suctionMountLocal 头注释)
    const lipWorld = _lip.fromArray(this.grip.contactLocalM).applyMatrix4(this._flip.matrixWorld)
    const radius = (Number(this.grip.cupDiameterM) || 0) / 2
    const maxM = this.carryCompressionM + this.strokeM

    let best = 0
    let hit = ''
    for (const plate of plates) {
      const root = plate?.root
      const geom = plate?.geom
      if (!root || !geom) continue
      root.updateWorldMatrix(true, false)
      // 唇口转进板的局部系: 那里贴合面是一个常数 y, 面内就是 x/z
      const lipLocal = _lipLocal.copy(lipWorld).applyMatrix4(_inv.copy(root.matrixWorld).invert())
      const { contactY, farY } = plateFaceLocalY(geom, silicaMm)
      // 板体在 contactY 的哪一侧, 唇口越过去多少就是穿透
      const inward = Math.sign(farY - contactY) || 1
      const penetration = (lipLocal.y - contactY) * inward
      // 超过一整个自由长就不是"压着这块板"了(典型是从板下方飞过), 不许误判成压缩
      if (penetration <= 0 || penetration > this._maxReachM) continue
      const supported = lipSupportedFraction(
        Math.abs(lipLocal.x) - (geom.widthM || 0) / 2,
        Math.abs(lipLocal.z) - (geom.lengthM || 0) / 2,
        radius,
      )
      const compression = plateRestCompression(penetration, supported, maxM)
      if (compression > best) {
        best = compression
        hit = root.name || ''
      }
    }

    this._writeCups(best)
    this.last = { ...idle, compressionM: best, hit }
    return this.last
  }

  /** 吸盘复位到自由长度。清场/关开关时必须调 —— 驱动层的 home() 不管这些孙节点。 */
  releaseCups() {
    this._writeCups(0)
    this.last = { penetrationM: 0, compressionM: 0, overshootM: 0 }
  }

  /** 本层自己建的 BVH 要自己释放(PickController 建的那些归它)。 */
  dispose() {
    this.releaseCups()
    for (const geometry of this._ownedTrees) geometry.disposeBoundsTree?.()
    this._ownedTrees.clear()
    this._collidables = []
    this._rubbers = []
  }
}
