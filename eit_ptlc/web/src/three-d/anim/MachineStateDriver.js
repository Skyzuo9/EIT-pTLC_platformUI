/**
 * PTLC 唯一机器状态驱动层。
 *
 * Studio 的离线片段与 Twin 的实时反馈都只向本类写“绝对状态”。本类负责把状态
 * 映射为 three.js 局部刚体变换，并统一处理轴、CR5 关节、气缸/旋转执行器、连杆、
 * 工具与载荷所有权。禁止在调用侧直接累加 position/quaternion。
 */
import * as THREE from 'three'

import { RobotJointDriver } from './RobotJointDriver.js'
// 液面 mL→液位 的换算与实时链共用同一份实现(理由见那里的注释); anim → twin/bindings
// 的方向已有先例: clipSchema.js 就是从那里取 validatePlateStep 的.
import { levelFromMl } from '../twin/bindings/TankLiquidModel.js'
// 枢轴补偿与空缸显隐同样与实时链共用一份 —— 液面几何是"两条链逐位相同"这条约束里
// 最容易漂的一块, 2026-08-05 就是补偿只落了实时链一边.
import {
  applyLiquidLevel, applyLiquidVisible, captureLiquidBase, restoreLiquidBase,
} from '../twin/bindings/liquidPivot.js'
// 粉柱的落点(恒锚在腔的 c1 端)与 mm³→液位换算同样两条链共用一份(同上一条理由):
// 各写一遍的表现是"演示里粉贴着底、实况页粉浮在中间", 没有任何指标会报警.
import { applyPowderColumn, levelFromMm3 } from '../twin/bindings/powderPivot.js'

const EPS = 1e-9
const TMP_VEC = new THREE.Vector3()
const TMP_QUAT = new THREE.Quaternion()
const TMP_MATRIX = new THREE.Matrix4()
const TMP_MATRIX_2 = new THREE.Matrix4()

/** 快换吸附时长(片段时间秒)。锁紧步 dur=0.45s, 吸附须在其内完成。 */
const TOOL_TWEEN_SECONDS = 0.25
/** 吸附最大行程: 示教残差量级为 0.3~2.6mm, 超过 20mm 说明数据坏了, 直接就位并告警。 */
const TOOL_TWEEN_MAX_TRAVEL_M = 0.02
/**
 * 载荷落位最大行程。
 *
 * 这个数是**实测定的**, 不是拍的: 24 条整板转移逐条量过"示教点推算的落位"与"CAD 托盘
 * 位"之间的平移残差(见片段里的 `compiled.dockResiduals[].alignment_mm`)。
 *
 * 2026-08-03 工位摆位校正之后, 该残差从 6~23 mm 降到 **≤7.9 mm**(货架/中转A/中转B 三个
 * 工位各按实机示教点整体平移了 82.6 / 65.8 / 77.7 mm, 见 rig_map 的 station_alignment)。
 * 阈值随之从 30 mm 收到 10 mm —— 30 mm 是校正前的量级, 留着会漏掉真正的坏数据。
 *
 * 编译期已经有更硬的门禁: 校正后的几何落位残差必须 ≤ 0.5 mm, 否则 sync_ptlc_robot
 * 直接拒绝生成片段。运行期还超这个阈值, 说明片段数据本身坏了 —— 直接就位保证终态正确,
 * 并高声告警。
 *
 * ⚠ 单件耗材(粉桶要坐进刮板接粉夹具的凹槽, press_cylinder 才压得住)对落位的要求比
 * 整板严得多, 且它的目的地当前在 GLB 里没有节点、无法做 CAD 复核。等那部分 socket
 * 几何从 CAD 分离出来之后, 单件应当走一条独立的、更紧的阈值, 不要直接复用本常量。
 */
const PAYLOAD_DOCK_MAX_TRAVEL_M = 0.01
/**
 * 单件**取件吸附**最大行程(与落位阈值分开): 吸附量 = "CAD 座位 vs 取料示教点"的平移
 * 失配, 2026-08-06 编译日志实测中转 B 取瓶为 ~57mm(法兰-孔心偏置 y≈179mm vs 四销笼
 * 中心 122.5mm) —— 这正是要修的量, 阈值必须容它通过; 100mm 以上则说明座位/轴起手态
 * 数据坏了(如托座轴没声明 home), 就位后高声告警让人去查, 而不是安静演一个假抓取。
 */
const PAYLOAD_GRAB_MAX_TRAVEL_M = 0.1

function clamp(value, range) {
  if (!Array.isArray(range) || range.length !== 2) return value
  return Math.min(Math.max(value, Number(range[0])), Number(range[1]))
}

/**
 * 功能: 一根轴**画得出来**的毫米区间 = rangeMm ∩ 几何下界.
 *
 * 为什么要分两个量: `rangeMm` 镜像控制侧的 limits, 是真源, 三维不得擅自收窄 —— 实机
 * 确实能走到那儿。`geometryMinMm` 说的是另一件事: 再往下, 滑车驮着的板会扎进固定结构
 * (上下料 1Z/2Z 实测比 rangeMm 下限高 18mm, 见 pipeline/verify_plate_clearance.py)。
 * 那 18mm 的差额来自三维侧把板简化成 200×200 的实心盒(实机放置板在光电处有让位孔),
 * 属于模型精度, 不是机器的事 —— 所以约束画面, 不动真源。
 *
 * 标定页走 `unclamped` 分支, 不受本条影响, 仍能试探全行程。
 */
function axisDrawableRange(spec) {
  const range = spec?.rangeMm
  if (!Array.isArray(range) || range.length !== 2) return range
  const floor = Number(spec?.geometryMinMm)
  if (!Number.isFinite(floor) || floor <= Number(range[0])) return range
  return [floor, Number(range[1])]
}

/**
 * 功能: 一根轴"控制侧 1mm"对应的**局部单位位移**(含方向) —— 驱动与反算的唯一口径.
 *
 * `= sign × scaleMm × mmToUnit`。三个因子各管一件事,别合并:
 *   · `sign`     纯方向(±1);
 *   · `scaleMm`  控制侧 mm → 物理 mm 的增益,缺省 1。目前只有 `axis_4x` 是 2.0 ——
 *                那根轴是自制同步带 + 步进,标度把每转行程配成了实际的一半
 *                (2026-08-06 卡尺实测:轴读 11.28mm 实走 ≈22.6mm)。**临时补偿**,
 *                换伺服后改回 1.0,见 docs/上样4X_5Z临时标度增益_换伺服后作废_20260806.md;
 *   · `mmToUnit` 物理 mm → 场景单位(米制整机恒 0.001)。
 *
 * 抽成函数是因为它有**两个使用方且方向相反**:`setAxisMm` 乘它、`AxisDragController`
 * 除它。分别手写迟早漂,而漂了不报错 —— 只表现为拖拽跟手感差一倍。
 */
export function axisUnitPerMm(spec) {
  return Number(spec?.sign ?? 1)
    * Number(spec?.scaleMm ?? 1)
    * Number(spec?.mmToUnit || 0.001)
}

function normalized(value, range) {
  const [from, to] = Array.isArray(range) && range.length === 2 ? range.map(Number) : [0, 1]
  if (Math.abs(to - from) < EPS) return 0
  return (clamp(value, [from, to]) - from) / (to - from)
}

function mapRange(value, inputRange, outputRange) {
  const [from, to] = Array.isArray(outputRange) && outputRange.length === 2
    ? outputRange.map(Number)
    : [0, 1]
  return from + (to - from) * normalized(value, inputRange)
}

/**
 * 功能: 取节点自身或其子树里的第一个网格(灯与受照物都可能是装配节点而非叶子网格).
 * @param {object} node three 对象
 * @returns {object|null} 网格; 子树里一个都没有返回 null
 */
function firstMeshOf(node) {
  if (!node) return null
  if (node.isMesh) return node
  let mesh = null
  node.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
  return mesh
}

function captureLocal(node) {
  return {
    parent: node.parent,
    position: node.position.clone(),
    quaternion: node.quaternion.clone(),
    scale: node.scale.clone(),
  }
}

function restoreLocal(node, pose) {
  if (pose.parent && node.parent !== pose.parent) pose.parent.add(node)
  node.position.copy(pose.position)
  node.quaternion.copy(pose.quaternion)
  node.scale.copy(pose.scale)
  node.updateMatrix()
  node.updateMatrixWorld(true)
}

/**
 * 保持世界矩阵不变地更换父级。与 Object3D.attach 不同，这里显式保存/还原世界矩阵，
 * 并在重挂后检查数值误差；工具和载荷因此不会在 attach 当帧改变方向或位置。
 */
export function reparentPreservingWorld(node, parent) {
  if (!node || !parent || node === parent || node.parent === parent) return true
  node.updateWorldMatrix(true, false)
  parent.updateWorldMatrix(true, false)
  const worldBefore = node.matrixWorld.clone()
  TMP_MATRIX.copy(parent.matrixWorld).invert()
  TMP_MATRIX_2.multiplyMatrices(TMP_MATRIX, worldBefore)
  parent.add(node)
  TMP_MATRIX_2.decompose(node.position, node.quaternion, node.scale)
  node.updateMatrix()
  node.updateMatrixWorld(true)

  // ⚠ 取"换父前"的朝向必须走 decompose 而不是 Quaternion.setFromRotationMatrix:
  // 后者要求传进去的 3×3 是**纯旋转**, 而载荷节点的世界矩阵里烤着 GLB 量化 scale
  // (04_optimize 的 meshopt 量化把瓶子这类件压成 node.scale≈0.0475), 带缩放的 3×3
  // 会解出一个完全无关的四元数 —— 实测瓶子 1−|dot| = 0.6954, 位置残差却只有 4.4e-16。
  // 于是这道闸对所有量化件恒定假失败, 而 parent.add() 早在上面就执行完了: attach 在
  // 写 entry.owner 与登记磁吸补间之前 return false, 表现成"件确实挂到了 TOOL_MOUNT
  // 上、却既不归属工具也不吸附", 且一声不响。
  const beforePosition = new THREE.Vector3()
  const beforeQuaternion = new THREE.Quaternion()
  worldBefore.decompose(beforePosition, beforeQuaternion, new THREE.Vector3())
  const afterPosition = node.getWorldPosition(new THREE.Vector3())
  const afterQuaternion = node.getWorldQuaternion(new THREE.Quaternion())
  return beforePosition.distanceTo(afterPosition) <= 1e-7
    && 1 - Math.abs(beforeQuaternion.dot(afterQuaternion)) <= 1e-7
}

/**
 * 按控制器工具号查 manifest 里的工具声明。0 = 裸腕，永远返回 null。
 *
 * 驱动层与 HUD 诊断共用这一个判定：manifest 少声明一把刀时，前端只会"取刀后什么都
 * 没有"，两处若各写一套判据就可能一边挂不上、另一边还显示正常。
 *
 * @param {object} manifest device-manifest
 * @param {number} controllerTool 上位机 mounted_tool
 * @returns {object|null} 工具声明
 */
export function declaredToolFor(manifest, controllerTool) {
  const toolNumber = Number(controllerTool)
  if (!Number.isInteger(toolNumber) || toolNumber <= 0) return null
  return (manifest?.tools || []).find((tool) => Number(tool.controllerTool) === toolNumber) || null
}

/**
 * 功能: 把一段吸附/落位补间推进到片段时刻 t(easeOutCubic).
 *
 * t 的单调性不作假设 —— 向后跳由播放器的"回家重放"负责, 这里只是 t 的纯函数。
 *
 * @param {{entry: object, from: object, to: object, t0: number}} tween 补间
 * @param {number} t 片段时刻(秒)
 * @returns {boolean} 是否已完成(调用方据此清除)
 */
function advanceTween(tween, t) {
  const raw = (Number(t) - tween.t0) / TOOL_TWEEN_SECONDS
  const k = Math.min(Math.max(raw, 0), 1)
  const eased = 1 - (1 - k) ** 3
  const node = tween.entry.node
  node.position.lerpVectors(tween.from.position, tween.to.position, eased)
  node.quaternion.slerpQuaternions(tween.from.quaternion, tween.to.quaternion, eased)
  node.updateMatrix()
  node.updateMatrixWorld(true)
  return k >= 1
}

function bindMotion(spec, resolve) {
  const nodePath = spec.node || spec.glbNode
  const node = resolve(nodePath)
  if (!node) return null
  return {
    spec,
    node,
    base: captureLocal(node),
    axis: new THREE.Vector3(...(spec.axis || [1, 0, 0])).normalize(),
    value: Number.NaN,
  }
}

/** 将一个绝对输入值写入平移或旋转运动件。 */
function applyMotion(entry, value) {
  if (!entry || !Number.isFinite(value)) return false
  const { spec, node, base, axis } = entry
  const output = mapRange(value, spec.inputRange || spec.range, spec.outputRange || [0, 1])
  const motion = spec.motion || spec.kind || 'translate'
  if (motion === 'rotate' || motion === 'rotary') {
    const radians = THREE.MathUtils.degToRad(output * Number(spec.sign ?? 1))
    TMP_QUAT.setFromAxisAngle(axis, radians)
    node.quaternion.copy(base.quaternion).multiply(TMP_QUAT)
  } else {
    const scale = Number(spec.unitScale ?? spec.mmToUnit ?? 1)
    TMP_VEC.copy(axis).multiplyScalar(output * scale * Number(spec.sign ?? 1))
    node.position.copy(base.position).add(TMP_VEC)
  }
  const changed = !Number.isFinite(entry.value) || Math.abs(entry.value - value) > EPS
  entry.value = value
  return changed
}

export class MachineStateDriver {
  /**
   * @param {object} options
   * @param {object} options.manifest device-manifest
   * @param {(path:string)=>THREE.Object3D|undefined} options.resolve 场景节点解析器
   * @param {(names:string[])=>void} [options.onHighlight] 高亮桥接
   * @param {(id:string,value:any,spec?:object)=>void} [options.onState] 状态视觉桥接
   */
  constructor({ manifest, resolve, onHighlight, onState }) {
    this.manifest = manifest || {}
    this.resolve = resolve
    this.onHighlight = onHighlight
    this.onState = onState
    this.missing = []
    this.axes = new Map()
    this.nodes = new Map()
    this.actuators = new Map()
    this.linkages = new Map()
    this.attachments = new Map()
    /** @type {Map<string, object>} 工艺灯(拍照补光/紫外面光源); 材质各自克隆独占 */
    this.lights = new Map()
    /**
     * 主轴(铣刀自转)。与 actuators 的 `motion: rotate` 分属两类:
     * 那边是有限角、绝对值写入、值是 t 的纯函数; 这里是无限角、按 rpm 对时间积分。
     * 因此**只有开关是状态**(走片段通道 / 实时事件), 相位是渲染层装饰 —— 与 setFlash
     * 同一类, home() 清零, 不参与 seek 幂等契约。
     * @type {Map<string, object>}
     */
    this.spindles = new Map()
    /** @type {Map<string, object>} 可按体积伸缩的液体几何(展缸溶液槽液面); 值单位 mL */
    this.liquids = new Map()
    /** @type {Map<string, object>} 注射泵(柱塞+液柱+丝杆+阀指针); 主值单位 mL, 阀位单位端口号 */
    this.pumps = new Map()
    /**
     * 耗材内容物里的**粉柱**(粉桶内刮下来的硅胶粉); 值单位 mm³, 另带 0..1 洗脱色相位。
     * 与液面分家而不是塞进 this.liquids: 粉多一个自由度(tint)、落点锚在腔的 c1 端而不是
     * 液面那种底端(见 powderPivot), 且**克隆了材质**故有配对的 dispose 义务。
     * @type {Map<string, object>}
     */
    this.powders = new Map()
    /**
     * 料仓托边停靠: axisId → [{rest, ledgeAxisMm, localPerMm}]。板堆锚点被 rig_map 收进
     * 滑车(否则"板堆升、板不动"), 但真机里板不被滑车顶着时坐在料仓口的固定托边上 ——
     * 轴 mm 低于交接值 ledgeAxisMm 后板停在托边、滑车继续走。见 _bindMagazineRests。
     * @type {Map<string, object[]>}
     */
    this.magazineRests = new Map()
    this.states = new Map()
    this.stateSpecs = new Map()
    this.mount = null
    this.activeControllerTool = 0
    this.activeAttachmentId = null
    /** @type {number|null} 控制器报了、但 manifest 里没有声明的工具号(裸腕 0 不算) */
    this.unknownControllerTool = null
    /**
     * 取放吸附补间(锁紧→mount_transform / 释放→停靠位)。以片段时间参数化,
     * 由 updateToolTween(t) 推进 —— 位姿是 t 的纯函数, 倒放重放可精确复现。
     * @type {{entry:object, from:{position:THREE.Vector3,quaternion:THREE.Quaternion}, to:{position:THREE.Vector3,quaternion:THREE.Quaternion}, t0:number}|null}
     */
    this.toolTween = null
    /**
     * 载荷落位补间, 与 toolTween 同构但独立成表: 工具吸附与载荷落位可以同帧发生
     * (松爪放料的同一步里工具仍挂在腕上), 单槽会互相顶掉。键是载荷 id。
     * @type {Map<string, {entry:object, from:object, to:object, t0:number}>}
     */
    this.payloadTweens = new Map()

    this._bind()
  }

  _resolve(path) {
    return path ? this.resolve?.(path) : undefined
  }

  _bind() {
    for (const spec of this.manifest.axes || []) {
      if (!spec.rigged || !spec.glbNode) continue
      const node = this._resolve(spec.glbNode)
      if (!node) {
        this.missing.push(spec.glbNode)
        continue
      }
      this.axes.set(spec.id, {
        spec,
        node,
        base: node.position.clone(),
        direction: new THREE.Vector3(...(spec.axis || [1, 0, 0])).normalize(),
        valueMm: Number.NaN,
      })
    }

    this.robot = new RobotJointDriver(this.manifest.robot, (path) => this._resolve(path))
    this.joints = this.robot.joints
    this.missing.push(...this.robot.missing)

    const mountName = this.manifest.robot?.toolMount || 'TOOL_MOUNT'
    this.mount = this._resolve(mountName) || null
    if (!this.mount) this.missing.push(mountName)

    for (const spec of this.manifest.nodes || []) this._bindNode(spec.id, spec.node || spec.glbNode)

    for (const spec of this.manifest.actuators || []) {
      const entry = bindMotion(spec, (path) => this._resolve(path))
      if (entry) this.actuators.set(spec.id, entry)
      else this.missing.push(spec.node || spec.glbNode || spec.id)
    }

    for (const spec of this.manifest.linkages || []) {
      const members = (spec.members || []).map((member) => bindMotion(member, (path) => this._resolve(path)))
      if (!members.length || members.some((member) => !member)) {
        this.missing.push(spec.id)
        continue
      }
      this.linkages.set(spec.id, { spec, members, value: Number.NaN })
    }

    const declarations = [...(this.manifest.attachments || [])]
    for (const tool of this.manifest.tools || []) {
      if (!declarations.some((entry) => entry.id === tool.id)) {
        declarations.push({ ...tool, node: tool.glbNode, defaultParent: tool.dockNode })
      }
    }
    for (const spec of declarations) this._bindAttachment(spec)

    for (const spec of this.manifest.states || []) {
      this.stateSpecs.set(spec.id, spec)
      this.states.set(spec.id, spec.initial ?? null)
    }

    for (const spec of this.manifest.lights || []) this._bindLight(spec)
    for (const spec of this.manifest.spindles || []) this._bindSpindle(spec)

    this._bindLiquids()
    this._bindPumps()
    this._bindPowders()
    this._bindMagazineRests()
  }

  /**
   * 料仓托边停靠: 在滑车与板堆模板之间插一个 identity 的 REST 空节点。
   *
   * 真机里板不被滑车顶着时坐在料仓口的固定托边上 —— 滑车下行穿过托边平面, 板留在托边,
   * 滑车继续降; 上行时反之。而 rig_map 把板堆模板并进了滑车(否则"板堆升、板不动"),
   * 于是三维里板会刚性跟到底、穿过托边(2026-08-07 用户报的穿模)。
   *
   * 做法: setAxisMm 每次写轴时同步 REST.position = localPerMm × max(0, ledgeAxisMm − 轴mm);
   * 绑定时与 home() 按 CAD 停靠轴值(zeroOffsetMm)先托一次 —— 自驱轴的片段不在 home 里
   * 声明轴值, t=0 到首个轴步之间没有任何轴写入, 而 CAD 把模板建在托边下方 33mm 处,
   * 不先托就是开场埋板。要点:
   *   · **无记忆**: 补偿是当帧轴值的纯函数, 向后 seek 走 home() 清场重放, 位姿仍是 t 的
   *     纯函数 —— 与 PlateStage 的 seek 契约一致;
   *   · **保局部插入**: 模板保持原局部变换改挂 REST 下, REST 只动 position, 所以
   *     measurePlateAnchor 量到的局部位姿逐位不变, 单板(PlateStage/PlateBinding place)、
   *     板堆(setMagazine parent=geom.parent)、模板玻璃(fx 页可见)全部自动骑上 REST;
   *   · **3×3 完整变换**: 轴向 spec.axis 表达在滑车**父**空间, REST.position 在滑车局部
   *     空间, 换算必须过滑车局部旋转×缩放的逆 —— GLB 量化会给节点非 1 的 scale,
   *     transformDirection 会归一化把它抹掉, 禁用(见"GLB 反量化 scale 陷阱"教训);
   *   · **兜底**: manifest 的 magazines[] 没有 ledgeAxisMm/axisId(老 manifest)就不建 REST,
   *     行为与现行逐位相同; 数据由 blender_plate_clearance.ledge_probe 实测、
   *     gen_twin_manifest 落 manifest, 前端不藏第二份数值。
   */
  _bindMagazineRests() {
    for (const spec of this.manifest.inventory?.magazines || []) {
      // 严格类型判定(不做 Number() 强转): null/字符串都算"没有数据", 走兜底而不是被
      // 强转成 0 后建出一个交接值为 0 的 REST
      if (!Number.isFinite(spec.ledgeAxisMm)) continue
      const axisEntry = this.axes.get(spec.axisId)
      if (!axisEntry) continue
      const template = this._resolve(spec.node)
      if (!template) {
        this.missing.push(spec.node)
        continue
      }
      const carriage = axisEntry.node
      const restName = `REST_${template.name}`
      let rest = template.parent === carriage || template.parent?.name === restName
        ? carriage.children.find((child) => child.name === restName) || null
        : null
      if (!rest && template.parent !== carriage) {
        // 模板既不在滑车下也不在本机制的 REST 下 —— 场景结构与 manifest 声明对不上,
        // 宁可退回刚性随滑车也不猜着挂
        console.warn(`[MachineStateDriver] 料仓 ${spec.id} 模板 ${template.name} 的父级是 `
          + `${template.parent?.name || '(无)'}, 不是滑车 ${carriage.name} —— 托边停靠跳过`)
        continue
      }
      if (!rest) {
        rest = new THREE.Group()
        rest.name = restName
        carriage.add(rest)
      }
      if (template.parent !== rest) rest.add(template)

      // 滑车局部旋转×缩放终生不变(轴驱动只写 position), 逆矩阵缓存一次
      TMP_MATRIX.compose(TMP_VEC.set(0, 0, 0), carriage.quaternion, carriage.scale)
      const inverseBasis = new THREE.Matrix3().setFromMatrix4(TMP_MATRIX).invert()
      const localPerMm = axisEntry.direction.clone()
        .multiplyScalar(axisUnitPerMm(axisEntry.spec))
        .applyMatrix3(inverseBasis)

      const item = {
        rest,
        ledgeAxisMm: spec.ledgeAxisMm,
        localPerMm,
        // CAD 停靠位对应的轴值 = zeroOffsetMm。上下料轴 CAD 位(−22)本就在交接值之下,
        // 模板在 CAD 里是埋在托边下方建模的 —— 所以**加载态/home 态也要托**, 不能等
        // 第一次 setAxisMm: 自驱轴的片段不在 home 里声明轴值, t=0 到首个轴步之间
        // 没有任何轴写入, 等写轴就等于开场埋板。
        homeMm: Number(axisEntry.spec.zeroOffsetMm || 0),
      }
      this._applyMagazineRest(item, item.homeMm)
      const entries = this.magazineRests.get(spec.axisId) || []
      entries.push(item)
      this.magazineRests.set(spec.axisId, entries)
    }
  }

  /** 按当前轴值把一个 REST 托到位: max(0, 交接值 − 轴mm), 当帧纯函数。 */
  _applyMagazineRest(item, axisMm) {
    item.rest.position.copy(item.localPerMm)
      .multiplyScalar(Math.max(0, item.ledgeAxisMm - axisMm))
  }

  /**
   * 绑定一根主轴。节点由 03 步 build_spindle_cutters 现造(TOOL_ 前缀不参与静态合并)。
   *
   * 轴向取 **节点局部** 而非世界: 与 applyMotion 的 rotate 分支同一口径
   * (`quaternion = base × axisAngle`, 先在自身局部转再套基位), 于是主轴跟着 10Z/9X
   * 平移、跟着任何父级姿态走都不用重算。
   *
   * @param {object} spec manifest.spindles 的一条
   * @returns {void}
   */
  _bindSpindle(spec) {
    const node = this._resolve(spec.glbNode)
    if (!node) {
      this.missing.push(spec.glbNode || spec.id)
      return
    }
    this.spindles.set(spec.id, {
      spec,
      node,
      base: node.quaternion.clone(),
      axis: new THREE.Vector3(...(spec.axis || [0, 1, 0])).normalize(),
      radPerS: (Number(spec.rpm) || 0) * Math.PI / 30, // rpm → rad/s
      on: false,
      phase: 0,
    })
  }

  /**
   * 绑定 8 个展缸溶液槽的液面盒.
   *
   * 与实时链(TwinBindings._bindTanks)有两处**有意的分歧**, 别照抄过去:
   *
   *   1. **不克隆材质.** 实时侧克隆是因为 _updateTanks 要按 Tank_State 写相位色; 离线
   *      片段里没有 Tank_State, 一个颜色都不写. 不克隆就没有配对的 dispose 义务 ——
   *      而 rig 在每次改参时都会重建, 克隆一次就泄一份. 将来离线链真要写液面颜色时,
   *      照 _bindLight 克隆并在 dispose() 里释放.
   *
   * (曾经有第 2 条"不写 node.visible", 2026-08-05 作废: 那条让排空的缸留下一张压扁的
   *  满尺寸顶面。现在两条链都经 visibilityIntent 仲裁写显隐, 见 setLiquidMl.)
   *
   * 液面材质必须保持不透明 —— 缘由见 TwinBindings._bindTanks 上方那段深度排序警告
   * (玻璃缸壁 depthWrite=false, 液体一旦也进透明队列就会被画到缸壁之上).
   * 本函数只写 scale, 天然满足.
   *
   * @returns {void}
   */
  _bindLiquids() {
    const cavity = this.manifest.tankLiquid?.cavity
    // 与 TankLiquidModel.enabled 同一条判据: 管线可以按 rig_map 停用液面盒生成。
    // 注意只跳过展缸段, 不 return —— 下面的驻位液体表是独立开关(rig_map 座位 liquid)
    if (cavity) {
      for (const tank of this.manifest.tanks || []) {
        // 某个缸的溶液槽没认出来时 build_tanks 只跳过那一个, 别的缸照常有
        if (!tank.liquidNode) continue
        const node = this._resolve(tank.liquidNode)
        if (!node) {
          this.missing.push(tank.liquidNode)
          continue
        }
        this.liquids.set(tank.id, {
          tank,
          node,
          // 建模尺寸 = 满到槽口的液位, 运行时按体积比例缩 y。
          // basePosition/baseMinY 是**枢轴补偿**用的: 出厂 GLB 的液面枢轴被 quantize 挪到了
          // 几何正中, 只写 scale 就是"往中心收缩"而不是"液面往下降"(见 liquidPivot.js)。
          // 三个字段由 captureLiquidBase 统一发放, 与实时链 _bindTanks/_bindPumps 同源。
          ...captureLiquidBase(node),
          valueMl: Number.NaN,
        })
      }
    }
    // 驻位液体(manifest.liquids[], 如收集样品瓶液柱): 逐条自带 cavity/exaggeration,
    // 与展缸共用同一个 liquids Map 与 liquid 通道 id 空间 —— clipSchema 的 liquid 原语
    // 注释早就预告"同一个原语将来还要驱别的容器", id 用 liq_ 前缀与 tank1..8 隔开。
    // 液柱挂在瓶节点下: 随瓶显隐(state 直写 visible 父隐子隐)、随爪(attach/dock 换父)、
    // 随缸(瓶已过继进机构组), 三种跟随不需要这里做任何事。
    for (const spec of this.manifest.liquids || []) {
      if (!spec?.id || !spec.node) continue
      const node = this._resolve(spec.node)
      if (!node) {
        this.missing.push(spec.node)
        continue
      }
      this.liquids.set(spec.id, {
        spec,
        node,
        ...captureLiquidBase(node),
        valueMl: Number.NaN,
      })
    }
  }

  /**
   * 写一处液面的体积(mL).
   *
   * 写 `scale` **与 `position`**: 缩放绕枢轴做, 而出厂 GLB 的液面枢轴在几何正中,
   * 不补偿就是液面朝中心收、底面凭空悬起(见 liquidPivot.js). 与实时链
   * TwinBindings._updateTanks 调的是同一个 applyLiquidLevel, 逐位相同是硬约束.
   *
   * 空缸要**整体隐藏**而不是只把 scale 压到 1e-4: 那个下限是为了不让法线退化, 但压扁
   * 后的盒仍是一张 210×40mm 的不透明顶面, 隔着玻璃缸看就是"排干净了还剩薄薄一层".
   * 显隐经 applyLiquidVisible 走仲裁而不是直接写 node.visible —— 动作页可以隔离零件
   * (ViewTools.isolate 按 isMesh 收集, 液面盒是裸网格必被藏), 直接写会让它弹回画面.
   *
   * @param {string} id 液体 id(= manifest.tanks[].id)
   * @param {number} ml 体积 mL; 超过槽容按槽容夹
   * @returns {boolean} 本次是否真的改变(供调用方决定要不要重渲)
   */
  setLiquidMl(id, ml) {
    const entry = this.liquids.get(id)
    const value = Number(ml)
    if (!entry || !Number.isFinite(value)) return false
    // 驻位液体逐条自带 cavity/exaggeration(manifest.liquids[].spec); 展缸条目没有 spec,
    // 回退全局 tankLiquid —— 展缸的行为逐位不变
    const cavity = entry.spec?.cavity || this.manifest.tankLiquid?.cavity || {}
    const exaggeration = entry.spec?.exaggeration ?? this.manifest.tankLiquid?.exaggeration ?? 1
    const capacityMl = Number(cavity.capacityMl) || 0
    const clamped = capacityMl > 0 ? Math.min(Math.max(0, value), capacityMl) : Math.max(0, value)
    const changed = !Number.isFinite(entry.valueMl) || Math.abs(entry.valueMl - clamped) > EPS
    entry.valueMl = clamped
    if (!changed) return false
    const level = levelFromMl(cavity, clamped, exaggeration)
    applyLiquidLevel(entry, entry.node, level)
    applyLiquidVisible(entry.node, level)
    return true
  }

  /**
   * 取某处液面的当前体积(mL) —— 面板显示用的真实值, 不含观感放大.
   *
   * 与 TankLiquidModel 的 volumeMl()/level() 同一条分离: 几何缩放里带着 exaggeration,
   * 拿渲染出来的盒高反算体积一定是错的.
   *
   * @param {string} id 液体 id
   * @returns {number} 体积 mL; 未绑定或未写过返回 0
   */
  liquidMl(id) {
    const entry = this.liquids.get(id)
    return entry && Number.isFinite(entry.valueMl) ? entry.valueMl : 0
  }

  /**
   * 绑定注射泵可动组(柱塞+筒内液柱+丝杆+阀指针盘), 键是泵 id(DEV1/DEV2/SMP/COL).
   *
   * 结构照实时链 TwinBindings._bindPumps 逐字段对齐(柱塞记**局部** basePosition ——
   * 上样泵骑在 6X 轴的 CARRIAGE 下, 记世界坐标会在轴一动就错), 但与 _bindLiquids 同款
   * **有意不克隆材质**: 离线片段不写泵液颜色, 克隆一份就多一份 dispose 义务.
   *
   * rigged:false / 缺节点的泵跳过(与实时链同一条降级路径): 片段里它的通道照样存在,
   * setter 查不到 entry 就静默不动 —— 数据仍在, 三维不表现.
   *
   * @returns {void}
   */
  _bindPumps() {
    for (const spec of this.manifest.pumpSyringe?.pumps || []) {
      if (!spec.rigged || !spec.plungerNode || !spec.liquidNode) continue
      const plunger = this._resolve(spec.plungerNode)
      const liquidNode = this._resolve(spec.liquidNode)
      if (!plunger) {
        this.missing.push(spec.plungerNode)
        continue
      }
      if (!liquidNode) {
        this.missing.push(spec.liquidNode)
        continue
      }
      const axis = Array.isArray(spec.travelAxis) ? spec.travelAxis : [0, 1, 0]
      const valve = spec.valveNode ? this._resolve(spec.valveNode) : null
      if (spec.valveNode && !valve) this.missing.push(spec.valveNode)
      const valveAxis = Array.isArray(spec.valveAxis) ? spec.valveAxis : [0, 0, -1]
      const lead = spec.leadNode ? this._resolve(spec.leadNode) : null
      if (spec.leadNode && !lead) this.missing.push(spec.leadNode)
      const leadAxis = Array.isArray(spec.leadAxis) ? spec.leadAxis : [0, 1, 0]
      this.pumps.set(spec.id, {
        spec,
        plunger,
        plungerBase: plunger.position.clone(),
        travel: new THREE.Vector3(axis[0], axis[1], axis[2])
          .normalize()
          .multiplyScalar(Number(spec.travelM) || 0),
        liquid: liquidNode,
        // 三个基准字段(含枢轴补偿量)成套发放, 与展缸/实时链同源 —— 见 liquidPivot.js
        ...captureLiquidBase(liquidNode),
        valve,
        valveAxis: new THREE.Vector3(valveAxis[0], valveAxis[1], valveAxis[2]).normalize(),
        valveBase: valve ? valve.quaternion.clone() : null,
        lead,
        leadAxis: new THREE.Vector3(leadAxis[0], leadAxis[1], leadAxis[2]).normalize(),
        leadBase: lead ? lead.quaternion.clone() : null,
        valueMl: Number.NaN,
        port: Number.NaN,
      })
    }
  }

  /**
   * 写一台泵的针筒内体积(mL) —— 单自由度, 一次写入驱动三个节点:
   * 柱塞平移(base + travel×level)、液柱缩放(applyLiquidLevel, 无观感放大)、
   * 丝杆自转(level × leadTurnsPerStroke 圈, 与柱塞刚性传动不另设通道).
   *
   * 换算全部留在写入层: 通道里存的是毫升(见 clipSchema 的单位纪律),
   * travelM/leadTurnsPerStroke/syringeMl 都取自 manifest, 每次重跑 03 自动跟上.
   *
   * @param {string} id 泵 id
   * @param {number} ml 体积 mL; 超过针筒量程按量程夹
   * @returns {boolean} 本次是否真的改变
   */
  setPumpMl(id, ml) {
    const entry = this.pumps.get(id)
    const value = Number(ml)
    if (!entry || !Number.isFinite(value)) return false
    const syringeMl = Number(this.manifest.pumpSyringe?.syringeMl) || 25
    const clamped = Math.min(Math.max(0, value), syringeMl)
    const changed = !Number.isFinite(entry.valueMl) || Math.abs(entry.valueMl - clamped) > EPS
    entry.valueMl = clamped
    if (!changed) return false
    const level = clamped / syringeMl
    entry.plunger.position.copy(entry.plungerBase).addScaledVector(entry.travel, level)
    // 泵液柱**不带**展缸那套 exaggeration: 针筒是标定过的量具, 1mL 恒等于 2.4mm
    applyLiquidLevel(entry, entry.liquid, level)
    applyLiquidVisible(entry.liquid, level)
    if (entry.lead) {
      const turns = Number(entry.spec.leadTurnsPerStroke) || 0
      TMP_QUAT.setFromAxisAngle(entry.leadAxis, level * turns * Math.PI * 2)
      entry.lead.quaternion.copy(entry.leadBase).multiply(TMP_QUAT)
    }
    return true
  }

  /**
   * 写一台泵的阀指针位(端口号, 1 基; 过渡期间可为小数 —— 通道在两个口之间插值时).
   *
   * 端口→角度按 manifest 的 valvePortAngles 分段线性插值: 实物阀头的接口全挤在
   * 335°→205° 的下半弧, 不是 360° 均布; 缺角度表(旧 manifest)才退回均布.
   * 与 PumpSyringeModel._portTurns 同一判据, 只是这里要支持小数口号.
   *
   * @param {string} id 泵 id
   * @param {number} port 端口号
   * @returns {boolean} 本次是否真的改变
   */
  setPumpValvePort(id, port) {
    const entry = this.pumps.get(id)
    const value = Number(port)
    if (!entry || !entry.valve || !Number.isFinite(value)) return false
    const total = Number(entry.spec.valvePorts) || 0
    if (!(total > 0)) return false
    const clamped = Math.min(Math.max(1, value), total)
    const changed = !Number.isFinite(entry.port) || Math.abs(entry.port - clamped) > EPS
    entry.port = clamped
    if (!changed) return false
    const angles = entry.spec.valvePortAngles
    const angleAt = (p) => (
      Array.isArray(angles) && angles.length === total && Number.isFinite(angles[p - 1])
        ? Number(angles[p - 1])
        : ((p - 1) / total) * 360
    )
    const lower = Math.floor(clamped)
    const upper = Math.min(lower + 1, total)
    const deg = angleAt(lower) + (angleAt(upper) - angleAt(lower)) * (clamped - lower)
    TMP_QUAT.setFromAxisAngle(entry.valveAxis, (deg / 360) * Math.PI * 2)
    entry.valve.quaternion.copy(entry.valveBase).multiply(TMP_QUAT)
    return true
  }

  /**
   * 取一台泵针筒内的当前体积(mL) —— 面板/测试用的真实值.
   * @param {string} id 泵 id
   * @returns {number} 体积 mL; 未绑定或未写过返回 0
   */
  pumpMl(id) {
    const entry = this.pumps.get(id)
    return entry && Number.isFinite(entry.valueMl) ? entry.valueMl : 0
  }

  /**
   * 绑定耗材内容物里的**粉柱**(粉桶内刮下来的硅胶粉), 键是内容物 id.
   *
   * 与 _bindLiquids / _bindPumps 有一处**关键分歧**, 是那两处头注释亲口留的话:
   * 它们有意不克隆材质, 理由是"离线片段一个颜色都不写"; 而粉的 tint 相位**就是在写色**
   * (淋洗前后换色是本功能的需求之一) ⇒ 触发那句"将来离线链真要写液面颜色时, 照
   * _bindLight 克隆并在 dispose() 里释放". 不克隆的后果是共用同一份材质的别的粉桶
   * (货架上还有 5 只)跟着一起变色, 且探针查不出来.
   *
   * 缺节点的粉桶跳过(与泵同一条降级路径): 片段里它的通道照样存在, setter 查不到 entry
   * 就静默不动 —— 数据仍在, 三维不表现. 于是粉柱几何还没进管线时片段照编、前端空跑不报错.
   *
   * @returns {void}
   */
  _bindPowders() {
    for (const spec of this.manifest.consumableContents?.kinds || []) {
      if (spec?.kind !== 'powder' || !spec.id || !spec.node) continue
      const node = this._resolve(spec.node)
      if (!node) {
        this.missing.push(spec.node)
        continue
      }
      const mesh = firstMeshOf(node)
      if (!mesh) continue
      // 独占一份材质: tint 相位要写 color, 共用就会污染别处(见 _bindLight 的同款惯用法)
      const material = mesh.material.clone()
      mesh.material = material
      this.powders.set(spec.id, {
        spec,
        node,
        mesh,
        material,
        // 出厂色 = 未洗的硅胶白; 洗脱色由契约给, 缺省退回出厂色(= 不换色, 而不是变黑)
        baseColor: material.color ? material.color.clone() : null,
        elutedColor: spec.elutedColor ? new THREE.Color(spec.elutedColor) : null,
        // 三个基准字段成套发放, 与液面/泵同源(枢轴补偿见 liquidPivot.js)
        ...captureLiquidBase(node),
        valueMm3: Number.NaN,
        tint: Number.NaN,
      })
    }
  }

  /**
   * 写一只粉桶里的粉量(mm³).
   *
   * 与 setLiquidMl 的**唯一分歧是不夹容量**: 腔容是目标自己的几何事实, 超量由
   * levelFromMm3 自然饱和到液位 1.0(粉柱顶到腔口就不再长), 与 clipSchema 里
   * "fill 不设上界"的通道纪律成对. 夹在这里会让"桶满了"与"账本记了多少"两个事实纠缠,
   * 而面板要显示的是后者.
   *
   * 位姿不在这里写 —— 粉的落点是**当帧世界姿态**的派生量, 必须等本帧所有轴/机构/吸附
   * 都写完才算得准, 故统一由 updatePowders 收尾. 这里只记值.
   *
   * @param {string} id 内容物 id
   * @param {number} mm3 粉量 mm³(非负; 负值按 0)
   * @returns {boolean} 本次是否真的改变
   */
  setPowderMm3(id, mm3) {
    const entry = this.powders.get(id)
    const value = Number(mm3)
    if (!entry || !Number.isFinite(value)) return false
    const clamped = Math.max(0, value)
    const changed = !Number.isFinite(entry.valueMm3) || Math.abs(entry.valueMm3 - clamped) > EPS
    entry.valueMm3 = clamped
    return changed
  }

  /**
   * 写一只粉桶的**洗脱色相位**(0 未洗 / 1 洗后), 中间值线性取色.
   *
   * 契约没给洗脱色时静默不写色(而不是退成黑/白): 换色是可选表现, 缺声明的正确降级是
   * "粉还在、只是不换色", 与缺节点跳过同一条降级纪律.
   *
   * @param {string} id 内容物 id
   * @param {number} tint 0..1
   * @returns {boolean} 本次是否真的改变
   */
  setPowderTint(id, tint) {
    const entry = this.powders.get(id)
    const value = Number(tint)
    if (!entry || !Number.isFinite(value)) return false
    const clamped = Math.max(0, Math.min(1, value))
    const changed = !Number.isFinite(entry.tint) || Math.abs(entry.tint - clamped) > EPS
    entry.tint = clamped
    if (!changed) return false
    if (entry.baseColor && entry.elutedColor && entry.material.color) {
      entry.material.color.copy(entry.baseColor).lerp(entry.elutedColor, clamped)
    }
    return true
  }

  /**
   * 取一只粉桶内的当前粉量(mm³) —— 面板/测试用的真实值, 不含观感放大.
   * @param {string} id 内容物 id
   * @returns {number} 粉量 mm³; 未绑定或未写过返回 0
   */
  powderMm3(id) {
    const entry = this.powders.get(id)
    return entry && Number.isFinite(entry.valueMm3) ? entry.valueMm3 : 0
  }

  /**
   * 按 evaluateChannels 的 powders 段成批写粉, 并**统一收尾算落点**.
   *
   * 两趟而不是一趟: 值(fill/tint)是通道给的, 而位姿要等本帧所有轴/机构/吸附都写完
   * (粉柱挂在桶下面, 桶的父级链每帧都在动)—— ClipPlayer 把本方法排在 updateToolTween
   * 之后正是为此(见那里的警告). 分两趟还让"只有 tint 变了"的帧少绕一圈.
   *
   * 位姿每帧都重写(不只在值变时): 与实时链 _updateConsumablePowders 保持同一条纪律,
   * 两条链在"什么时候写"上分叉的代价远大于省下的那点开销.
   *
   * @param {Object<string, {fill: number, tint: number}>} powders 通道求值产物
   * @returns {boolean} 本帧是否有任何改变(供调用方决定要不要重渲)
   */
  updatePowders(powders) {
    let changed = false
    for (const [id, value] of Object.entries(powders || {})) {
      if (this.setPowderMm3(id, value?.fill)) changed = true
      if (this.setPowderTint(id, value?.tint)) changed = true
    }
    for (const entry of this.powders.values()) {
      if (!Number.isFinite(entry.valueMm3)) continue
      const spec = entry.spec || {}
      const level = levelFromMm3(spec.cavity, entry.valueMm3, spec.exaggeration ?? 1)
      applyPowderColumn(entry, entry.node, spec.chamber, level)
    }
    return changed
  }

  /**
   * 绑定一盏工艺灯: **克隆一份材质独占**, 免得改亮度污染共用同材质的别的零件
   * (与 TwinBindings._bindSignalLight / _bindStations 同一套惯用法)。
   */
  _bindLight(spec) {
    const node = this._resolve(spec.glbNode || spec.node)
    if (!node) {
      this.missing.push(spec.glbNode || spec.id)
      return
    }
    const mesh = firstMeshOf(node)
    if (!mesh) return
    const material = mesh.material.clone()
    mesh.material = material
    this.lights.set(spec.id, {
      spec,
      mesh,
      material,
      color: new THREE.Color(spec.color || '#ffffff'),
      peak: Number(spec.peakIntensity ?? 1),
      value: Number.NaN,
      lit: this._bindIlluminated(spec),
    })
    this.setLight(spec.id, Number(spec.defaultLevel ?? 0))
  }

  /**
   * 绑定一盏灯的**节点级受照对象**(manifest.lights[].illuminatesNodes)。
   *
   * 为什么需要它: 视觉纠偏那盏补光灯埋在盖板玻璃下 37mm, 从任何正常机位看开/关两态
   * 画面几乎无差 —— 真机上人眼看见的"闪"其实是它上方那扇窗亮起来。把受照对象做成
   * 契约声明而不是某个 View 的私有 hack, 离线 Studio 链与实时 Twin 链才能共用同一份
   * 实现(TwinBindings 组合的正是本类)。
   *
   * 各自克隆材质、各自峰值: 受照物多半是被照亮而非自发光, 峰值一般低于灯本体。
   *
   * @param {object} spec manifest.lights 条目
   * @returns {Array<{mesh: object, material: object, peak: number}>} 受照条目; 未声明时空数组
   */
  _bindIlluminated(spec) {
    const lit = []
    for (const target of spec.illuminatesNodes || []) {
      const node = this._resolve(target.glbNode || target.node)
      if (!node) {
        this.missing.push(target.glbNode || `${spec.id}:illuminates`)
        continue
      }
      const mesh = firstMeshOf(node)
      if (!mesh) continue
      const material = mesh.material.clone()
      mesh.material = material
      lit.push({ mesh, material, peak: Number(target.peakIntensity ?? spec.peakIntensity ?? 1) })
    }
    return lit
  }

  /**
   * 写一盏工艺灯的亮度(0..1 系数, 峰值由 manifest 的 peakIntensity 定).
   *
   * 只动 `emissive` 与 `emissiveIntensity`, **不动 base color** —— 与
   * TwinBindings._updateSignalLight 同一条约定: 保留烘焙的 albedo, 全灭时就是
   * "断电灯罩"的物理观感, 而不是变成一块黑色塑料。
   *
   * 受照节点(illuminatesNodes)与灯本体同步写, 各按自己的峰值 —— 补光灯本体埋在盖板
   * 玻璃下几乎看不见, 那扇跟着亮的窗才是"闪"的可见形态。
   *
   * @param {string} id 灯 id
   * @param {number} level 0..1 亮度系数
   * @returns {boolean} 本次是否真的改变(供调用方决定要不要重渲)
   */
  setLight(id, level) {
    const entry = this.lights.get(id)
    const value = Number(level)
    if (!entry || !Number.isFinite(value)) return false
    const clamped = Math.min(1, Math.max(0, value))
    const changed = !Number.isFinite(entry.value) || Math.abs(entry.value - clamped) > EPS
    entry.value = clamped
    if (!changed) return false
    if (entry.material.emissive) {
      entry.material.emissive.copy(entry.color)
      entry.material.emissiveIntensity = clamped * entry.peak
    }
    for (const target of entry.lit || []) {
      if (!target.material.emissive) continue
      target.material.emissive.copy(entry.color)
      target.material.emissiveIntensity = clamped * target.peak
    }
    return true
  }

  /**
   * 已被工艺灯独占克隆材质的全部网格(灯本体 + 受照节点), 与亮度无关。
   *
   * 存在的唯一理由是让**后建的绑定层**知道"这几个别碰": 谁在本类之后再给同一个网格
   * `mesh.material = clone` 一次, 这盏灯就会永远停在烘焙色 —— 数据全对、画面不动、
   * 无任何报错。TwinBindings._bindEnclosure 已经因为塔灯栽过一次(那里有同款守卫),
   * 玻璃盖板挂在 ST_FRAME 下, 是第二次。
   *
   * @returns {object[]} 网格数组
   */
  ownedLightMeshes() {
    const meshes = []
    for (const entry of this.lights.values()) {
      meshes.push(entry.mesh)
      for (const target of entry.lit || []) meshes.push(target.mesh)
    }
    return meshes
  }

  /**
   * 当前参与辉光的灯网格(灭着的不进选集: 黑灯进辉光只是白费一次全屏 pass)。
   *
   * 受照节点一并进: 补光那盏灯**本体**几乎看不见, 只让它进辉光等于这盏灯没有辉光。
   */
  bloomLights() {
    const meshes = []
    for (const entry of this.lights.values()) {
      if (entry.spec.bloom === false || !(entry.value > 0.01)) continue
      meshes.push(entry.mesh)
      for (const target of entry.lit || []) meshes.push(target.mesh)
    }
    return meshes
  }

  _bindNode(id, path = id) {
    if (!id || this.nodes.has(id)) return this.nodes.get(id)
    const node = this._resolve(path)
    if (!node) return null
    const entry = { id, path, node, base: captureLocal(node) }
    this.nodes.set(id, entry)
    return entry
  }

  _bindAttachment(spec) {
    const node = this._resolve(spec.node || spec.glbNode || spec.id)
    if (!node) {
      this.missing.push(spec.node || spec.glbNode || spec.id)
      return
    }
    this.attachments.set(spec.id, {
      spec,
      node,
      home: captureLocal(node),
      owner: node.parent,
    })
  }

  /**
   * 写直线轴毫米绝对值。返回本次是否真的改变。
   * options.unclamped 仅供标定接管期的越界试探(rangeMm 本身可能未标对) ——
   * 常规链路(片段/实时/调试)一律走 clamp。
   */
  setAxisMm(id, mm, { unclamped = false } = {}) {
    const entry = this.axes.get(id)
    if (!entry || !Number.isFinite(Number(mm))) return false
    const value = unclamped
      ? Number(mm)
      : clamp(Number(mm), axisDrawableRange(entry.spec))
    const offset = (value - Number(entry.spec.zeroOffsetMm || 0)) * axisUnitPerMm(entry.spec)
    TMP_VEC.copy(entry.direction).multiplyScalar(offset)
    entry.node.position.copy(entry.base).add(TMP_VEC)
    // 料仓托边停靠: 轴低于交接值后板堆留在托边高度、滑车继续走(见 _bindMagazineRests)。
    // 用夹后的 value: 补偿与滑车实际画到哪儿始终一致, unclamped 试探时同样成立。
    const rests = this.magazineRests.get(id)
    if (rests) for (const item of rests) this._applyMagazineRest(item, value)
    const changed = !Number.isFinite(entry.valueMm) || Math.abs(entry.valueMm - value) > EPS
    entry.valueMm = value
    return changed
  }

  /**
   * 参数编辑后重算运动件的缓存轴向。applyMotion 读 spec.sign/outputRange 是活的,
   * 唯 axis 在 bindMotion 时被缓存成 Vector3 —— 动作界面改了 spec.axis 后必须调这里。
   * @param {'actuator'|'linkage'} kind 运动件类别
   * @param {string} id 运动件 id
   * @returns {boolean} 是否命中
   */
  refreshMotionAxis(kind, id) {
    if (kind === 'actuator') {
      const entry = this.actuators.get(id)
      if (!entry) return false
      entry.axis.set(...(entry.spec.axis || [1, 0, 0])).normalize()
      return true
    }
    if (kind === 'linkage') {
      const entry = this.linkages.get(id)
      if (!entry) return false
      for (const member of entry.members) {
        member.axis.set(...(member.spec.axis || [1, 0, 0])).normalize()
      }
      return true
    }
    return false
  }

  /** 写 CR5 六轴控制器绝对角。 */
  setJointsDeg(degrees, options) {
    return this.robot.setJointsDeg(degrees, options)
  }

  /** 写通用节点相对加载态的绝对平移（场景单位为米）。 */
  setNodeOffset(id, offset) {
    const entry = this.nodes.get(id) || this._bindNode(id, id)
    if (!entry || !Array.isArray(offset) || offset.length !== 3) return false
    TMP_VEC.set(Number(offset[0]), Number(offset[1]), Number(offset[2]))
    entry.node.position.copy(entry.base.position).add(TMP_VEC)
    return true
  }

  setActuator(id, value) {
    return applyMotion(this.actuators.get(id), Number(value))
  }

  /**
   * 主轴开/关。只记状态, 不写几何 —— 几何由 updateSpindles 逐帧推进。
   *
   * @param {string} id 主轴 id
   * @param {boolean} on 是否在转
   * @returns {boolean} 状态是否改变
   */
  setSpindle(id, on) {
    const entry = this.spindles.get(id)
    if (!entry) return false
    const next = Boolean(on)
    if (entry.on === next) return false
    entry.on = next
    return true
  }

  /**
   * 逐帧推进主轴相位。**这是本类唯一一处非 t 的纯函数的写入** —— 转角是无限增长量,
   * 表达不成时间的函数(见 clipSchema 里 spindle 原语的注释)。相位在 home() 清零,
   * 所以向后 seek 之后刀从 0 相位重新转起, 与"相位不是状态"的定位一致。
   *
   * @param {number} deltaS 距上一帧秒数(离线链要乘播放倍速)
   * @returns {boolean} 是否有主轴在转(供调用方决定要不要重渲)
   */
  updateSpindles(deltaS) {
    const dt = Number(deltaS)
    if (!Number.isFinite(dt) || dt <= 0) return false
    let spinning = false
    for (const entry of this.spindles.values()) {
      if (!entry.on || entry.radPerS <= 0) continue
      spinning = true
      // 相位取模: 浮点相位无限增长会在长时间播放后丢精度(转角抖动)
      entry.phase = (entry.phase + entry.radPerS * dt) % (Math.PI * 2)
      TMP_QUAT.setFromAxisAngle(entry.axis, entry.phase)
      entry.node.quaternion.copy(entry.base).multiply(TMP_QUAT)
    }
    return spinning
  }

  setLinkage(id, value) {
    const entry = this.linkages.get(id)
    if (!entry || !Number.isFinite(Number(value))) return false
    const progress = normalized(Number(value), entry.spec.inputRange || entry.spec.range || [0, 1])
    let changed = !Number.isFinite(entry.value) || Math.abs(entry.value - Number(value)) > EPS
    for (const member of entry.members) {
      const memberInput = mapRange(progress, [0, 1], member.spec.inputRange || member.spec.range || [0, 1])
      changed = applyMotion(member, memberInput) || changed
    }
    entry.value = Number(value)
    return changed
  }

  /**
   * 保持世界变换地把工具/载荷交给新父级。
   *
   * kind=item 且带 mountLocal 的载荷(fit_item_grips 产出, **位置吸附**语义: position =
   * 小夹爪四销笼中心, TOOL_MOUNT 系)在换父后再做一步磁吸: 把物件的**抓取特征点**
   * (payload.grabLocal, 瓶=瓶颈中点、收集器=注射器桶身; 缺字段才退回 Box3 几何中心)
   * 平移到该点, 姿态保留当刻世界朝向, 且 mountLocal.freeAxes 上的分量放手不修 ——
   * 长度轴上咬哪段由示教点决定(2026-08-05 定案), 桶身类连销轴也放开。
   * 给了 atTime 才吸附(片段链); 旧调用/实时链不传, 保持纯换父语义。
   * 与整板 mountLocal(完整局部位姿, TrayBinding 消费)刻意不同, 按 payload.kind 区分。
   * 修正公式与 clip_compiler._grab_corrected **逐字同式**(那边烤 dock) —— 不同式的
   * 表现是放件瞬间硬弹回 + "dock 与实际取料位姿不同源"误告警。
   */
  attach(id, parent = this.mount, atTime = null) {
    const entry = this.attachments.get(id)
    const parentNode = typeof parent === 'string' ? this._resolve(parent) : parent
    if (!entry || !parentNode) return false
    // 换父的数值残差不是"要不要接管"的判据: reparentPreservingWorld 里 parent.add() 已经
    // 执行完了, 此处再 return false 只会让件挂在工具下却没有 owner、没有磁吸补间, 一声不响
    // (与 TrayBinding._attach 同一条定案)。所以只告警, 照常接管。
    if (!reparentPreservingWorld(entry.node, parentNode)) {
      console.warn(
        `[MachineStateDriver] 载荷 ${id} 换父到 ${parentNode.name || '(匿名)'} 的世界位姿残差超限, `
        + '已照常接管 —— 换父那刻的世界位姿被改动了, 检查父级链是否在同帧被别的层写过',
      )
    }
    entry.owner = parentNode
    const payload = entry.spec.payload
    const mountLocal = payload?.kind === 'item' ? payload?.mountLocal : null
    if (atTime == null || !Array.isArray(mountLocal?.position)) return true
    // 锚点在 TOOL_MOUNT 系里表达; 挂到别的父级(理论上不存在)时不吸附, 不猜坐标系
    if (parentNode !== this.mount) return true
    entry.node.updateMatrixWorld(true)
    if (!entry.grabLocalCenter) {
      // 吸附基准优先取 manifest 的 payload.grabLocal(fit_item_grips 逐件实测的抓取
      // 特征: 瓶=瓶颈中点, 收集器=注射器桶身) —— 包围盒中心不是抓取基准, 瓶会被抬到
      // 销子跨瓶身中段(2026-08-06 用户报障)。缺字段(旧 manifest)才退回 Box3 中心。
      // 该值是**本份 GLB**(models/machine.official-cr5.glb)的节点局部系坐标, 下面靠
      // node.localToWorld 消费。管线侧在 machine.full.glb 上拟合、出厂前搬帧到这一份
      // (量化件两边节点原点/scale 不同, 瓶实测差 37.3mm), 见 fit_item_grips 头注。
      const grabLocal = Array.isArray(payload?.grabLocal) && payload.grabLocal.length === 3
        ? payload.grabLocal : null
      if (grabLocal) entry.grabLocalCenter = new THREE.Vector3().fromArray(grabLocal)
    }
    if (!entry.grabLocalCenter) {
      // 物件几何中心(节点局部系, 求一次即可): 与管线 payload-poses 的 localCenter 同口径。
      // INV_* 空节点的原点是任意的(离几何可达数百毫米), 绝不能拿节点原点当抓取基准。
      const box = new THREE.Box3().setFromObject(entry.node)
      if (box.isEmpty()) return true
      entry.grabLocalCenter = entry.node.worldToLocal(box.getCenter(new THREE.Vector3()))
    }
    const centerMount = this.mount.worldToLocal(
      entry.node.localToWorld(entry.grabLocalCenter.clone()))
    const shift = new THREE.Vector3().fromArray(mountLocal.position).sub(centerMount)
    // freeAxes(TOOL_MOUNT 系)上的分量放手不修: 长度轴上咬哪段由示教点决定
    // (2026-08-05 定案, 强拉即用户报障的"到位后自动往后对齐"); 桶身类连销轴也放开。
    if (Array.isArray(mountLocal.freeAxes)) {
      for (const axis of mountLocal.freeAxes) {
        if (!Array.isArray(axis) || axis.length !== 3) continue
        TMP_VEC.set(Number(axis[0]), Number(axis[1]), Number(axis[2]))
        if (TMP_VEC.lengthSq() < EPS) continue
        TMP_VEC.normalize()
        shift.addScaledVector(TMP_VEC, -shift.dot(TMP_VEC))
      }
    }
    const travel = shift.length()
    const to = {
      position: entry.node.position.clone().add(shift),
      quaternion: entry.node.quaternion.clone(),
    }
    if (travel > PAYLOAD_GRAB_MAX_TRAVEL_M) {
      console.warn(
        `[MachineStateDriver] 载荷 ${id} 距在手锚点 ${(travel * 1000).toFixed(1)} mm, `
        + `超出取件吸附阈值 ${(PAYLOAD_GRAB_MAX_TRAVEL_M * 1000).toFixed(0)} mm, 直接就位 —— `
        + '座位/托座轴的起手态与取料示教点失配异常大, 检查片段 home 声明与 rig_map 座位',
      )
      entry.node.position.copy(to.position)
      entry.node.updateMatrix()
      entry.node.updateMatrixWorld(true)
      this.payloadTweens.delete(id)
      return true
    }
    this.payloadTweens.set(id, {
      entry,
      from: { position: entry.node.position.clone(), quaternion: entry.node.quaternion.clone() },
      to,
      t0: Number(atTime),
    })
    return true
  }

  /** 保持世界变换地转交到指定父级；未指定则回原停靠父级。 */
  detach(id, parent = null) {
    const entry = this.attachments.get(id)
    if (!entry) return false
    const parentNode = typeof parent === 'string' ? this._resolve(parent) : (parent || entry.home.parent)
    if (!parentNode || !reparentPreservingWorld(entry.node, parentNode)) return false
    entry.owner = parentNode
    return true
  }

  /**
   * 锁紧: 换父到 TOOL_MOUNT 保持世界变换; 带片段时刻(atTime)时再从当前位姿平滑
   * 吸附到标定锁紧位(mount_transform)。示教点与 CAD 料架间存在 0.3~2.6mm 的真实
   * 残差, 吸附把它做成 0.25s 的磁吸滑入而非瞬间跳变。不带 atTime 的旧调用保持
   * "只换父"语义(实时链走 syncMountedTool, 不经这里)。
   */
  lockTool(id, atTime = null, { snap = false } = {}) {
    if (!this.attach(id, this.mount)) return false
    const entry = this.attachments.get(id)
    const spec = entry.spec
    if (snap === true) {
      // 片段起手式: "本段一开始刀就已经装在腕上"。这不是取刀动作, 从停靠位到法兰
      // 的距离本来就有几百毫米, 走吸附补间既没有意义(没有取刀轨迹)又会触发超限告警。
      if (Array.isArray(spec.mountPosition) && Array.isArray(spec.mountQuaternion)) {
        entry.node.position.fromArray(spec.mountPosition)
        entry.node.quaternion.fromArray(spec.mountQuaternion).normalize()
        entry.node.updateMatrix()
        entry.node.updateMatrixWorld(true)
      }
      this.toolTween = null
      return true
    }
    if (atTime == null) return true
    if (!Array.isArray(spec.mountPosition) || !Array.isArray(spec.mountQuaternion)) return true
    this._beginToolTween(entry, {
      position: new THREE.Vector3().fromArray(spec.mountPosition),
      quaternion: new THREE.Quaternion().fromArray(spec.mountQuaternion).normalize(),
    }, atTime)
    return true
  }

  /**
   * 释放: 换父回停靠父级保持世界变换; 带片段时刻时再平滑吸附回精确停靠位姿,
   * 吃掉到位残差(与锁紧对称)。不带 atTime 的旧调用绝不在释放当帧吸附/跳向,
   * home() 才负责强制恢复精确加载态, 供 seek 回放使用。
   */
  releaseTool(id, atTime = null) {
    const entry = this.attachments.get(id)
    if (!entry) return false
    if (!this.detach(id, entry.home.parent)) return false
    if (atTime == null) return true
    this._beginToolTween(entry, {
      position: entry.home.position.clone(),
      quaternion: entry.home.quaternion.clone(),
    }, atTime)
    return true
  }

  /**
   * 载荷落位: 保世界变换换父到目的地, 再平滑吸附到编译期算好的局部位姿。
   *
   * 与 releaseTool 的区别: 工具的停靠位是"它自己加载时的位姿"(entry.home), 而载荷的
   * 落位是**目的地座位的位姿**, 与它加载时在哪无关 —— 一块托盘从货架搬到中转, 目的地
   * 是中转位而不是它的货架原位。所以落位位姿必须由调用方(clip)显式给出。
   *
   * @param {string} id 载荷 id(须在 manifest.attachments 中声明)
   * @param {THREE.Object3D|string} parent 目的父级(节点或路径)
   * @param {{position: number[], quaternion: number[]}} dock 相对目的父级的局部位姿
   * @param {number|null} [atTime=null] 片段时刻; 给了才做补间, 否则直接就位
   * @returns {boolean} 是否成功
   */
  dockPayload(id, parent, dock, atTime = null, { snap = false } = {}) {
    const entry = this.attachments.get(id)
    if (!entry) return false
    if (!this.detach(id, parent)) return false
    if (!dock || !Array.isArray(dock.position) || !Array.isArray(dock.quaternion)) {
      // 没给落位位姿 = 退化成普通 detach(只换父保世界变换)。不猜一个位置。
      return true
    }
    const to = {
      position: new THREE.Vector3().fromArray(dock.position),
      quaternion: new THREE.Quaternion().fromArray(dock.quaternion).normalize(),
    }
    if (snap === true) {
      // 片段起手式: "本段一开始件就已经在爪中"(编译器 preload_payload 的 detach+snap)。
      // 没有取件轨迹, 从座位到法兰的行程本来就有几百毫米 —— 走吸附补间没有意义,
      // 超限告警更是误报(与 lockTool 的 snap 同一条理由)。
      entry.node.position.copy(to.position)
      entry.node.quaternion.copy(to.quaternion)
      entry.node.updateMatrix()
      entry.node.updateMatrixWorld(true)
      this.payloadTweens.delete(id)
      return true
    }
    const from = {
      position: entry.node.position.clone(),
      quaternion: entry.node.quaternion.clone(),
    }
    const travel = from.position.distanceTo(to.position)
    if (atTime == null || travel > PAYLOAD_DOCK_MAX_TRAVEL_M) {
      if (travel > PAYLOAD_DOCK_MAX_TRAVEL_M) {
        console.warn(
          `[MachineStateDriver] 载荷 ${id} 距落位目标 ${(travel * 1000).toFixed(1)} mm, `
          + `超出落位阈值 ${(PAYLOAD_DOCK_MAX_TRAVEL_M * 1000).toFixed(1)} mm, 直接就位 —— `
          + 'clip 的 dock 与实际取料位姿不同源, 重新生成片段',
        )
      }
      entry.node.position.copy(to.position)
      entry.node.quaternion.copy(to.quaternion)
      entry.node.updateMatrix()
      entry.node.updateMatrixWorld(true)
      this.payloadTweens.delete(id)
      return true
    }
    this.payloadTweens.set(id, { entry, from, to, t0: Number(atTime) })
    return true
  }

  /** 建立一段吸附补间; 行程异常大说明数据坏了, 直接就位并告警(防拉着工具横穿场景)。 */
  _beginToolTween(entry, to, atTime) {
    const from = {
      position: entry.node.position.clone(),
      quaternion: entry.node.quaternion.clone(),
    }
    const travel = from.position.distanceTo(to.position)
    if (travel > TOOL_TWEEN_MAX_TRAVEL_M) {
      console.warn(
        `[MachineStateDriver] 工具 ${entry.spec.id} 距吸附目标 ${(travel * 1000).toFixed(1)} mm, `
        + '超出吸附阈值, 直接就位',
      )
      entry.node.position.copy(to.position)
      entry.node.quaternion.copy(to.quaternion)
      entry.node.updateMatrix()
      entry.node.updateMatrixWorld(true)
      this.toolTween = null
      return
    }
    this.toolTween = { entry, from, to, t0: Number(atTime) }
  }

  /**
   * 按片段时间推进吸附补间(ClipPlayer 每次连续求值时调用)。easeOutCubic;
   * 补间完成即精确落到目标位姿并清除。t 单调性不作假设 —— 回退由播放器的
   * "回家重放"负责, 这里只是 t 的纯函数。
   */
  updateToolTween(t) {
    if (this.toolTween && advanceTween(this.toolTween, t)) this.toolTween = null
    for (const [id, tween] of this.payloadTweens) {
      if (advanceTween(tween, t)) this.payloadTweens.delete(id)
    }
  }

  /**
   * 将上位机 mounted_tool 权威态同步到场景所有权。正常取刀时工具与 TOOL_MOUNT 已
   * 几何重合，保持世界变换即可；首次接入/重连若两者相距过大，则直接恢复到真实挂载
   * 位，不播放可能穿模的补间路径。
   */
  syncMountedTool(controllerTool, { forceSnap = false, toleranceM = 0.005 } = {}) {
    const toolNumber = Number(controllerTool)
    if (!Number.isInteger(toolNumber) || toolNumber < 0) {
      return { changed: false, resynced: false, missing: true }
    }

    const declared = declaredToolFor(this.manifest, toolNumber)
    const target = declared ? this.attachments.get(declared.id) : null
    let changed = false
    let resynced = false

    // 裸腕或换成另一把刀时，上一把工具必须回到其版本化停靠位。
    if (this.activeAttachmentId && this.activeAttachmentId !== declared?.id) {
      const prior = this.attachments.get(this.activeAttachmentId)
      if (prior) {
        restoreLocal(prior.node, prior.home)
        prior.owner = prior.home.parent
        changed = true
        resynced = true
      }
      this.activeAttachmentId = null
    }

    this.activeControllerTool = toolNumber
    if (toolNumber === 0) {
      this.unknownControllerTool = null
      for (const entry of this.attachments.values()) {
        if (entry.node.parent !== this.mount) continue
        restoreLocal(entry.node, entry.home)
        entry.owner = entry.home.parent
        changed = true
        resynced = true
      }
      return { changed, resynced, missing: false }
    }
    // manifest 没有声明这把刀时，绝不复制其它工具冒充；但必须留痕：以前这里静默返回，
    // 现象是"后端说挂着吸盘、前端法兰上空空如也"，既无日志也无 UI，查了很久才定位。
    // unknownControllerTool 由 TwinBindings 透出到 HUD 只读诊断。
    if (!target || !this.mount) {
      this.unknownControllerTool = toolNumber
      return { changed, resynced, missing: true }
    }
    this.unknownControllerTool = null

    if (target.node.parent !== this.mount) {
      if (!reparentPreservingWorld(target.node, this.mount)) {
        return { changed, resynced, missing: true }
      }
      changed = true
    }
    const mountPosition = target.spec.mountPosition || [0, 0, 0]
    const mountQuaternion = target.spec.mountQuaternion || [0, 0, 0, 1]
    const expectedPosition = TMP_VEC.fromArray(mountPosition)
    const expectedQuaternion = TMP_QUAT.fromArray(mountQuaternion).normalize()
    const positionError = target.node.position.distanceTo(expectedPosition)
    const orientationError = 1 - Math.abs(target.node.quaternion.dot(expectedQuaternion))
    if (forceSnap || positionError > toleranceM || orientationError > 1e-5) {
      target.node.position.copy(expectedPosition)
      target.node.quaternion.copy(expectedQuaternion)
      target.node.scale.copy(target.home.scale)
      target.node.updateMatrix()
      target.node.updateMatrixWorld(true)
      changed = true
      resynced = true
    }
    target.owner = this.mount
    this.activeAttachmentId = declared.id
    return { changed, resynced, missing: false }
  }

  attachmentParentName(id) {
    return this.attachments.get(id)?.node.parent?.name || ''
  }

  attachmentWorldPosition(id) {
    const entry = this.attachments.get(id)
    if (!entry) return null
    return entry.node.getWorldPosition(new THREE.Vector3()).toArray()
  }

  setState(id, value) {
    this.states.set(id, value)
    const spec = this.stateSpecs.get(id)
    const node = spec ? this._resolve(spec.node || spec.glbNode) : null
    if (node && spec.property === 'visible') node.visible = Boolean(value)
    this.onState?.(id, value, spec)
    return true
  }

  setHighlight(names) {
    this.onHighlight?.(names || [])
  }

  /** 恢复加载态，是向后 seek 的唯一清场入口。 */
  home() {
    for (const entry of this.axes.values()) {
      entry.node.position.copy(entry.base)
      entry.valueMm = Number.NaN
    }
    // 托边停靠 REST 回"CAD 停靠轴值对应的托位"而不是零: 加载态板就该坐在托边上
    // (CAD 把模板建在托边下方 33mm 处, 归零等于开场埋板)。REST 节点留在图里供
    // dispose 后重建的 driver 复用; 它不进任何 base 采集路径, 不破坏"不留痕"纪律。
    for (const entries of this.magazineRests.values()) {
      for (const item of entries) this._applyMagazineRest(item, item.homeMm)
    }
    this.robot.home()
    for (const entry of this.nodes.values()) restoreLocal(entry.node, entry.base)
    for (const entry of this.actuators.values()) {
      restoreLocal(entry.node, entry.base)
      entry.value = Number.NaN
    }
    for (const entry of this.linkages.values()) {
      for (const member of entry.members) {
        restoreLocal(member.node, member.base)
        member.value = Number.NaN
      }
      entry.value = Number.NaN
    }
    for (const entry of this.attachments.values()) {
      restoreLocal(entry.node, entry.home)
      entry.owner = entry.home.parent
      // 吸附基准缓存随 home 失效: Box3 兜底路径依赖当刻世界朝向, 站侧件被翻料缸转过
      // 180° 后复用旧缓存会把锚点打反(grabLocal 路径无此依赖, 清了也只是重建一次)
      entry.grabLocalCenter = null
    }
    this.toolTween = null
    this.payloadTweens.clear()
    // 灯回默认亮度: 向后 seek 是"home 清场 + 重放", 灯若停在上一次的亮度,
    // 拖过一次补光段之后它就再也不灭了
    for (const [id, entry] of this.lights) {
      entry.value = Number.NaN
      this.setLight(id, Number(entry.spec.defaultLevel ?? 0))
    }
    // 主轴停转并把相位与姿态一起清回基位: 相位不是状态(它不是 t 的函数), 留着只会让
    // 向后 seek 后的刀停在上一次的随机角度 —— 不出错, 但也不是"回到加载态"。
    for (const entry of this.spindles.values()) {
      entry.on = false
      entry.phase = 0
      entry.node.quaternion.copy(entry.base)
    }
    // 液面归零, 与灯同理: 向后 seek 是"home 清场 + 重放", 液面若停在上一次的体积,
    // 拖过一次注液段之后这缸就再也空不掉了.
    //
    // 归零而不是 restoreLocal(baseScale): 液面盒的建模位是**满到槽口**, 那不是中性态,
    // 只是盒被建成那么大. 空缸才是这台机器的静止态(实时侧 Tank_State=0/98 同此).
    // 也正因如此, 离线页在本函数落地前是 8 个缸全渲染成满液的.
    //
    // 归零同时会把液面盒隐藏、并把底面钉回原位(都在 setLiquidMl 里) —— 向后 seek 是
    // ClipPlayer 唯一的清场入口, 这里漏一样, 那一样就永远回不到空缸态.
    for (const [id, entry] of this.liquids) {
      entry.valueMl = Number.NaN
      this.setLiquidMl(id, 0)
    }
    // 泵与液面同理: 0 mL 是这台机器的静止态(每个 *.init 都是 DT `Z` 归零指令), 阀指针
    // 回 1 号口(与 PumpSyringeModel 的通道初值同一条约定 —— 0° 那边是平口, 没有口).
    // "只在 home 里声明、片段不驱动"的泵靠 clipSchema 的 home 播种通道回到声明值.
    for (const [id, entry] of this.pumps) {
      entry.valueMl = Number.NaN
      this.setPumpMl(id, 0)
      entry.port = Number.NaN
      this.setPumpValvePort(id, 1)
    }
    // 粉与液面同理: 空桶是静止态(桶出厂就是空的, 粉是刮取过程里一点点吸进去的)。
    // tint 也一并回 0(未洗) —— 它与粉量是同一个状态的两个面, 只清一半会让下一段片段
    // 起手就演一只"空着却是洗过色"的桶。声明了起手粉量的片段靠 clipSchema 的 home
    // 播种通道回到声明值(与泵同一条路径)。
    for (const [id, entry] of this.powders) {
      entry.valueMm3 = Number.NaN
      entry.tint = Number.NaN
      this.setPowderMm3(id, 0)
      this.setPowderTint(id, 0)
    }
    // 归零后落点也要跟着回位: setPowderMm3 只记值不写位姿(位姿统一由 updatePowders 收尾
    // 写), 漏了这一趟, 向后 seek 的清场就只清了粉量、粉柱还停在上一帧的高度上。
    this.updatePowders({})
    this.activeControllerTool = 0
    this.activeAttachmentId = null
    this.unknownControllerTool = null
    for (const spec of this.manifest.states || []) this.setState(spec.id, spec.initial ?? null)
    this.setHighlight([])
  }

  /**
   * 阶段 1 刚体门禁：所有可动节点局部缩放必须保持单位值。
   *
   * ⚠ 液面盒(this.liquids)**故意不在这个集合里** —— 它天生就是靠非单位缩放表达体积的.
   * 顺手"补全"这个函数会让门禁在液面上线当天变红, 而红的不是缺陷.
   * 粉柱(this.powders)同此: 它也是靠非单位缩放表达粉量的, 同样不进门禁.
   */
  rigidScaleViolations(tolerance = 1e-6) {
    const nodes = new Set()
    for (const entry of this.axes.values()) nodes.add(entry.node)
    for (const joint of this.joints) nodes.add(joint.node)
    for (const entry of this.actuators.values()) nodes.add(entry.node)
    for (const entry of this.linkages.values()) for (const member of entry.members) nodes.add(member.node)
    for (const entry of this.attachments.values()) nodes.add(entry.node)
    // 泵的柱塞/阀/丝杆是刚体, 进门禁; 筒内液柱与展缸液面盒同理**故意不进**(见上)
    for (const entry of this.pumps.values()) {
      nodes.add(entry.plunger)
      if (entry.valve) nodes.add(entry.valve)
      if (entry.lead) nodes.add(entry.lead)
    }
    return [...nodes]
      .filter((node) => Math.max(Math.abs(node.scale.x - 1), Math.abs(node.scale.y - 1), Math.abs(node.scale.z - 1)) > tolerance)
      .map((node) => node.name)
  }

  dispose() {
    this.home()
    for (const entry of this.lights.values()) {
      entry.material.dispose()
      // 受照节点的材质也是 _bindIlluminated 克隆出来的, 克隆一次就有一份配对的释放义务
      for (const target of entry.lit || []) target.material.dispose()
    }
    this.lights.clear()
    // 液面还原到加载态: dispose 在每次换模/改参时都跑, 与 actuator 走 restoreLocal
    // 是同一条"不留痕"纪律 —— home() 留下的是空缸, 那是**播放态**不是加载态.
    //
    // ⚠ position 必须与 scale 一起还原(restoreLiquidBase 保证成对): setLiquidMl 会沿节点
    // +Y 做枢轴补偿, 只还 scale 的话, 下一次 _bindLiquids 会把"补偿后的位置"采成新的
    // basePosition, 于是 useMotionStack 每改一次参、重建一次 rig 就多偏一截, 越用越歪.
    for (const entry of this.liquids.values()) restoreLiquidBase(entry, entry.node)
    this.liquids.clear()
    // 泵同理: 液柱经 restoreLiquidBase 成对还原(scale+position+显隐), 柱塞/阀/丝杆
    // 回捕获时的基位 —— home() 留下的 0mL 是播放态, 加载态是建模位.
    for (const entry of this.pumps.values()) {
      restoreLiquidBase(entry, entry.liquid)
      entry.plunger.position.copy(entry.plungerBase)
      if (entry.valve && entry.valveBase) entry.valve.quaternion.copy(entry.valveBase)
      if (entry.lead && entry.leadBase) entry.lead.quaternion.copy(entry.leadBase)
    }
    this.pumps.clear()
    // 粉柱: 几何照液面成对还原(同上那条"越用越歪"的警告一字不差地适用), 外加**材质释放**
    // —— _bindPowders 克隆了一份材质(tint 要写色), 克隆一次就有一份配对的释放义务。
    for (const entry of this.powders.values()) {
      restoreLiquidBase(entry, entry.node)
      entry.material.dispose()
    }
    this.powders.clear()
  }
}
