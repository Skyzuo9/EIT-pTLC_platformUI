/**
 * 功能: 片段(clip)里的薄层板舞台 —— 让虚拟板按 `plate` 原语出现、跟手、落位、消失.
 *
 * 与实时页 PlateBinding 的分工:
 *   PlateBinding 是**投影**: 板在哪由上位机调度器的权威账本决定, 三维只跟着画;
 *   PlateStage   是**编排**: 片段是标称轨迹演示, 没有账本可投影, 板的行踪写在 YAML 里。
 * 两者共用同一个 PlateFaceLayer(几何/材质/厚度)与同一份锚点解析(plateAnchors.js),
 * 差别只在"谁说了算"。
 *
 * ⚠ **本层刻意不做落位补间**, 与 PlateBinding 的 0.25s "坐正"不同。
 * 理由是片段播放必须是时刻 t 的纯函数(ClipPlayer 的 seek 语义: 向后跳 = home 清场 +
 * 重放 [0,t] 全部事件)。补间是带记忆的状态, 拖进度条时会漂。
 *
 * 这条纪律**没有**因为 2026-08-06 补的"落点面内保持"(见 _seatHold)而放松: 那个修正的
 * 权重只由**当帧**的板↔落点法向间距算出, 不存任何上一帧的量, 与 plateContact 同一类,
 * 所以复合起来仍只依赖 t。真要加的是按时间衰减的补间时, 请回头读这一段。
 *
 * ⚠ 另外, 上面那句"示教残差只有毫米级"当年只对**法向**成立。面内实测 4~21mm,
 * 硬就位在观感上非常明显(用户 2026-08-06 报的上料位取板穿模就是它)。
 */
import * as THREE from 'three'

import { reparentPreservingWorld } from '../../../anim/MachineStateDriver.js'
import { bindPlateAnchors, findFlipSuctionNode, readPlateGrip } from './plateAnchors.js'
import { PlateContact } from './plateContact.js'
import { standardPlateGeom, suctionMountLocal } from './plateGeometry.js'
import { bandToUv, gravityDirsWorld, machineDirsWorld, troughDirsWorld } from './scrapeOverlay.js'

/**
 * 取板后仍算"板还在这个工位里"的三维距离(米) —— 这以内持板修正**恒定不变**。
 *
 * ⚠ 判据必须是"离落点多远", **不能**是"板↔落点的法向间距"(2026-08-06 第一版就栽在这):
 * 取板紧接着是"上料1Z降轴5mm让位", 落点自己往下跑、机械臂同时上抬, 法向间距 0.15s 内
 * 就涨过 10mm, 而此刻板**仍被料仓侧壁四面围着** —— 于是修正在兜里泄掉, 板横扫 14.6mm
 * 进侧壁, 实测撞出 11.2mm 的相交(probe_plate_overlap 的 STATIC_MAT_STEEL_PLATE_D0D0C8)。
 * 间距大 ≠ 脱离兜。
 *
 * 120mm 的由来: 板 200×200, 料仓兜壁高出板面几十毫米; 实测退出轨迹上板扫到离落点 120mm
 * 时早已完全出兜(probe_plate_overlap 全程 0 相交即为证)。
 */
const CARRY_HOLD_M = 0.12

/**
 * 彻底交还刀具常量的三维距离(米)。CARRY_HOLD_M → 本值之间走 smoothstep。
 *
 * 那笔 4~21mm 的示教残差消不掉, 只能选它在**哪里**发生。取板瞬间、退出途中、落缸途中
 * 三个位置周围都有几何, 唯一无害的位置是**自由空间** —— 250mm 开外机械臂正在长距离
 * 转运, 板周围什么都没有。
 */
const CARRY_RELEASE_M = 0.25

/**
 * 板"完全坐在落点里"的法向间距(米) —— 这以内面内位置 100% 归落点, 放板那一帧零跳变。
 *
 * 只用于**放板**那一端(取板端走上面 CARRY_* 那套捕获逻辑)。
 * 取 3mm: 实测放板落座帧 0、离座 4.05mm 时权重仍需接近 1。
 */
const SEAT_HOLD_FULL_M = 0.003

/**
 * 落点彻底放手的法向间距(米) —— 超过它面内完全交给刀具常量; 两者之间走 smoothstep。
 *
 * ⚠ 10mm 是**实测定的, 不能随手放大**。放大会引入一个新毛病: 机械臂进出工位那一段是
 * 斜着走的, 离座还远时"板到落点"的面内距离里混着**尚未走完的行程**, 而不只是示教残差。
 * 实测 develop_load 放板段(展缸1): 离座 16.1mm 处面内还差 38.6mm(仍在接近),
 * 12.2mm 处收敛到 9.96mm, 4.1mm 处 10.07mm —— 与该落点的真实残差 10.11mm 吻合。
 * 即残差要到离座 ~12mm 以内才"干净"。首版写 40mm, 于是板在落进缸的最后 1.1s 里被
 * 横着拖了 25mm(看着像板在吸盘上打滑) —— 那是修一个穿模又造一个新毛病。
 *
 * 反过来也不能太小: 这一段同时是"离站时把修正交还刀具常量"的过渡, 太短会变成硬跳。
 */
const SEAT_HOLD_GAP_M = 0.010

/**
 * 认定"就是这个落点"的面内容差(米)。
 *
 * 各落点实测面内残差最大 20.9mm(tank:8, 见 diagnose_plate_grip), 而相邻落点间距 ≥180mm
 * (展缸节距) —— 45mm 卡在两者中间, 既咬得住本落点, 又不可能咬到隔壁那个。
 */
const SEAT_HOLD_LATERAL_M = 0.045

const _normal = new THREE.Vector3()
const _seat = new THREE.Vector3()
const _delta = new THREE.Vector3()
const _inPlane = new THREE.Vector3()
const _axis = new THREE.Vector3()
const _plateWorld = new THREE.Vector3()
const _mountNormal = new THREE.Vector3()
const _seatNormal = new THREE.Vector3()
const _tilt = new THREE.Quaternion()
const _q0 = new THREE.Quaternion()
const _q1 = new THREE.Quaternion()

export class PlateStage {
  /**
   * @param {object} opts
   * @param {object} opts.manifest device-manifest(取 rob_flip_suction 的节点路径)
   * @param {Map<string, import('three').Object3D>} opts.nodeIndex loadModel 建的节点索引
   * @param {import('./PlateFaceLayer.js').PlateFaceLayer} opts.layer 板实体层
   * @param {import('three').Object3D} [opts.root] 整机根(接触判据的可碰几何来源; 不给则不做接触)
   */
  constructor({ manifest, nodeIndex, layer, root = null } = {}) {
    this.layer = layer || null
    /** manifest 引用(刮取方向要实读 axes[].axis/sign, 见 setScrape) */
    this.manifest = manifest || null
    /** 节点解析(nodeIndex 双索引: 先按全路径, 再退叶名由调用方处理) */
    this._resolveNode = (name) => (name ? nodeIndex?.get?.(name) : undefined)
    /** 机床方向缓存: undefined=未算过, null=解析失败(留白), 其余={xCm,yCm} */
    this._machineDirs = undefined
    /** @type {Map<string, object>} plateId -> 条带 UV 映射缓存(见 setScrape 的落座门槛) */
    this._scrapeUv = new Map()
    /** @type {Map<string, object[]>} plateId -> 点样色带 UV 映射缓存(setSpot, 同一门槛) */
    this._spotUv = new Map()
    /** @type {Map<string, object>} plateId -> 润湿区 UV 映射缓存(setWet, 同一门槛) */
    this._wetUv = new Map()
    const { anchors, missing, nodes } = bindPlateAnchors(nodeIndex)
    /** @type {Map<string, object>} 落点 -> 实测几何 */
    this.anchors = anchors
    /** @type {string[]} 解析不到的落点(如实上报, 不用近似锚点顶替) */
    this.missing = missing
    /** @type {import('three').Object3D|null} 吸盘翻转节点 */
    this.suctionNode = findFlipSuctionNode(manifest, nodeIndex)
    /** @type {object|null} 板相对吸盘的实测刚体常量(见 plateAnchors.readPlateGrip) */
    this.plateGrip = readPlateGrip(manifest)
    /** @type {PlateContact|null} 吸盘柔性接触; root 没给(单测/无场景)时为 null */
    this.contact = root
      ? new PlateContact({ manifest, nodeIndex, root, grip: this.plateGrip, excludeExtra: nodes })
      : null
    /** 接触判据的开关(见 plateSettings.contactEnabled); 关掉即回到刚性钉在唇口 */
    this.contactEnabled = true
    /** @type {Map<string, string>} plateId -> 当前落点(carried 表示在手上) */
    this.placed = new Map()
    /** @type {object|null} 当帧"落点还抓着板"的修正(诊断/验收用, 见 _seatHold) */
    this.seatHold = null
    /** @type {object|null} 取板那一刻捕获的三轴残差(见 _captureCarryOffset) */
    this.carryHold = null
    /** @type {string[]} 片段引用了但解析不到的落点(HUD 用: 宁可留白也不猜位置) */
    this.unresolved = []
  }

  /**
   * 功能: 执行一条 `plate` 原语.
   * @param {{id: string, at?: string, carry?: boolean, hide?: boolean,
   *          from?: string, mount?: object}} payload 原语参数
   * @returns {boolean} 是否生效
   */
  apply(payload = {}) {
    const plateId = String(payload.id || '')
    if (!plateId || !this.layer) return false
    if (payload.hide === true) return this.hide(plateId)
    if (payload.carry === true) {
      return this.carry(plateId, payload.mount, payload.from ? String(payload.from) : '')
    }
    if (payload.at) return this.show(plateId, String(payload.at))
    return false
  }

  /**
   * 功能: 把板摆到某落点的 CAD 位姿上(首次出现 / 放板都走这里).
   * @param {string} plateId 板号
   * @param {string} slot 落点(feedlift / spot_seat / scrape_table / waste / tank:N)
   * @returns {boolean} 是否生效
   */
  show(plateId, slot) {
    const geom = this.anchors.get(slot)
    if (!geom) {
      // 落点解析不到就**什么都不画**: 摆到一个猜的位置比不画更坏 —— 画面照样"很真",
      // 只是板躺在错的地方, 没有任何自动指标会报警。
      if (!this.unresolved.includes(slot)) this.unresolved.push(slot)
      return false
    }
    this.layer.place(plateId, geom)
    this.placed.set(plateId, slot)
    // 板已落座, 取板时捕获的那份残差到此为止 —— 留着会在下一次取板前被误用
    this.carryHold = null
    this.seatHold = null
    return true
  }

  /**
   * 功能: 把板交给吸盘 —— 换父到翻转节点之下.
   *
   * 之后 `actuator: rob_flip_suction` 一转, 板作为子级刚性跟随, 翻转由构造成立,
   * 不需要任何"硅胶朝上/朝下"的状态位。
   *
   * 三种落法, 按优先级:
   *   1. 片段显式给了 `mount` —— 钉到该局部位姿(留着不删: 将来若有片段要摆一个刻意
   *      偏离刀具基准的持板姿态, 这是唯一出口)。
   *   2. manifest 有 `plateGrip` —— 按**吸盘自己的几何**算局部位姿(常态)。这条与"板从
   *      哪来"无关, 于是各站的示教残差(实测 4~67mm)不会再被冻进板与吸盘的相对关系里。
   *   3. 都没有 —— 退回旧的保世界位姿换父(老 manifest 兼容路径)。
   *
   * ⚠ 走第 2 条时, 吸气那一帧板会从锚点位姿跳到刀具位姿。**这个跳只在法向上是纠错**
   * (跳掉的是持板压缩那一段, 2026-08-05 已由 carry_compression_mm 收干净); 面内那一份
   * 不是残差而是真实工况 —— 杯本就落在板上偏 4~21mm 的位置, 板并不会因此挪窝。
   * 所以面内由 _seatHold 在板还坐在落点里时交还给落点, 见那里的长注释。
   * 仍然**不要**给它加按时间衰减的补间(带记忆, 拖进度条会漂, 见本文件头注释)。
   *
   * @param {string} plateId 板号
   * @param {{position: number[], quaternion: number[]}} [mount] 相对翻转节点的局部位姿
   * @param {string} [from] 板来自/去往的落点 —— 只用来定尺寸与硅胶朝向(板池是复用的,
   *        不给这个提示时会沿用上一块板的朝向)。给不出锚点时静默忽略。
   * @returns {boolean} 是否生效
   */
  carry(plateId, mount = null, from = '') {
    if (!this.suctionNode) return false
    const plate = this.layer.get(plateId) || this.layer.acquire(plateId)
    const hint = from ? this.anchors.get(from) : null
    if (hint) this.layer.setGeom(plateId, hint)
    const usable = Array.isArray(mount?.position) && mount.position.length === 3
      && Array.isArray(mount?.quaternion) && mount.quaternion.length === 4

    if (usable) {
      this._pin(plate, mount.position, mount.quaternion)
      this.placed.set(plateId, 'carried')
      return true
    }

    const grip = suctionMountLocal(
      this.plateGrip,
      plate.geom || standardPlateGeom(),
      this.layer.silicaMm,
    )
    if (grip) {
      // 先捕获: 此刻板还好好坐在落点上, 落点位姿就是真值(见 _captureCarryOffset)。
      // 必须在 _applySeatHold 之前 —— 后者要用捕获的结果。
      this._captureCarryOffset(grip, from)
      // 吸气那一帧就要带上修正, 否则会先跳一帧再被 update() 拉回来 —— 单帧的跳变
      // 截图/像素判据照样抓得到, 而且拖进度条停在那一帧时就是错的。
      this._applySeatHold(grip)
      this._pin(plate, grip.position.toArray(), grip.quaternion.toArray())
      this.placed.set(plateId, 'carried')
      return true
    }

    if (!plate?.root.parent) {
      // 既没有世界位姿可保, 也没有刀具常量 —— 挂到吸盘原点是唯一不猜的选择,
      // 但那意味着板会长在旋转气缸轴心上。正常情况下 plateGrip 一定在。
      this._pin(plate, [0, 0, 0], [0, 0, 0, 1])
      this.placed.set(plateId, 'carried')
      return true
    }
    if (!reparentPreservingWorld(plate.root, this.suctionNode)) return false
    this.placed.set(plateId, 'carried')
    return true
  }

  /**
   * 功能: 板还在落点里时, **面内**位置仍由落点说了算 —— 取放板那一瞬间不跳变的全部机理.
   *
   * 为什么要分轴对待(2026-08-06 定位, 见 docs/工位摆位偏差溯源_20260805.md 的面内一节):
   *   `plateGrip` 假定"板相对吸盘永远在同一个位置"。这条对**法向**成立 —— 杯必须贴住板面,
   *   是几何硬约束, 实测各站残差 ≤3mm。但对**面内两根轴不成立**: 板是 200×200 的光板,
   *   两只杯落在板面哪个位置**没有任何几何特征定位**, 纯由示教时人手停在哪决定, 实测各站
   *   面内 4~21mm(上料位 15.1mm)。
   *   于是刚性钉在刀具常量上, 等于强行要求"杯必须正对板心", 现实里却是**板不动、杯落偏**
   *   —— 因果反了。表现就是吸气那一帧板横着跳 15mm 扎进料仓侧壁。
   *
   * 修法: 硬轴(法向)仍归 plateGrip + plateContact; 软轴(面内)在板还坐在落点里时归落点,
   * 离站后按法向间距平滑交还给刀具常量。物理上讲得通 —— 板在兜里时是兜决定它在哪,
   * 离兜之后才由杯带着走; 放板则反过来, 落进兜里时被倒角自动对中。
   *
   * ⚠ **没有记忆**: 权重只由当帧的法向间距算, 不存"取板时刻"也不做时间补间。
   * 这是本文件头注释那条纪律的实质(补间是带记忆的状态, 拖进度条会漂) —— 本函数是当帧
   * 场景的纯函数, 与 plateContact.resolve 同一类, 于是 seek 仍是 t 的纯函数。
   * 顺带也避开了时间补间的一个具体毛病: 吸气有 0.35s 停顿, 按时间衰减会让板在机械臂
   * 一动不动时自己滑走几毫米。
   *
   * @param {THREE.Vector3} position 刀具常量算出的板根局部位置(翻转节点局部系)
   * @param {THREE.Quaternion} quaternion 同上的姿态(用来取板面法线)
   * @returns {{slot: string, gapM: number, weight: number, offset: THREE.Vector3}|null}
   *          没有任何落点咬住时返回 null
   */
  _seatHold(position, quaternion) {
    if (!this.suctionNode || !this.anchors.size) return null
    this.suctionNode.updateWorldMatrix(true, false)
    // 板面法线在翻转节点局部系的朝向 = 板局部 +Y 经该姿态转出来(与 suctionMountLocal 同源)
    _normal.set(0, 1, 0).applyQuaternion(quaternion)

    let best = null
    for (const [slot, geom] of this.anchors.entries()) {
      if (!geom?.parent) continue
      geom.parent.updateWorldMatrix(true, false)
      // 落点的"板心"位姿: 父空间 -> 世界 -> 翻转节点局部系, 与 position 同一个系里比
      _seat.copy(geom.position).applyMatrix4(geom.parent.matrixWorld)
      this.suctionNode.worldToLocal(_seat)
      _delta.subVectors(_seat, position)
      const along = _delta.dot(_normal)
      _inPlane.copy(_delta).addScaledVector(_normal, -along)
      const gap = Math.abs(along)
      if (gap > SEAT_HOLD_GAP_M) continue
      if (_inPlane.length() > SEAT_HOLD_LATERAL_M) continue
      if (!best || gap < best.gapM) {
        best = { slot, gapM: gap, weight: 0, offset: _inPlane.clone(), full: _delta.clone() }
      }
    }
    if (!best) return null

    // 平台 + smoothstep: 贴着落点(≤FULL)恒为 1, 到 GAP 归 0, 中间两端导数为 0 无折点。
    // 平台段不能省 —— 取放板那一帧本就离座 1~2mm(唇口压缩), 没有平台就只能拿到 0.95
    // 这种权重, 于是"零跳变"变成"跳 0.7mm", 白白让出一个可以说死的保证。
    const span = SEAT_HOLD_GAP_M - SEAT_HOLD_FULL_M
    const s = Math.min(1, Math.max(0, (best.gapM - SEAT_HOLD_FULL_M) / span))
    best.weight = 1 - s * s * (3 - 2 * s)
    best.offset.multiplyScalar(best.weight)
    return best
  }

  /**
   * 功能: 取板那一刻把"板相对刀具常量差多少"整个捕获下来(**三轴, 不只面内**).
   *
   * 为什么连法向也要捕获(2026-08-06 第二轮定位): 板坐在 `PTLC-04-015 玻璃放置板` 上,
   * CAD 净空只有 **0.01mm**, 而板中面离那块放置板顶面只有 1.51mm(半个板厚)。取板瞬间
   * 沿吸盘轴那 1.66mm 示教残差把板直接按了进去 —— 越过 1.51mm 的余量, 一块大平板穿过
   * 板中面, slice_intrusion 量到 **92.93mm** 的交线内侵, 画面上就是"板整个陷进上料机构"。
   *
   * 这本该由 plateContact 兜住(顶到硬表面就压吸盘而不是把板顶进去), 但它兜不住, 两层原因:
   *   1. `plate_contact.ignore` 曾把整个 ST_FEEDLIFT 排掉(已于本轮撤销, 前提是错的);
   *   2. 撤销之后仍然探不到 —— `_probe` 只打**板心 + 四角**五条射线, 而放置板只有
   *      140mm 宽、板四角(±98mm)全落在它外面, 板心那条又正对着中间的让位孔。
   *      五点采样对"细长/带孔的承托件"结构性不够, 这一条已记在 plateContact 里。
   *
   * 所以取板端不再指望射线: 板刚被吸起来的那一刻, 它**本来就好好坐在落点上**,
   * 落点位姿就是真值, 直接整段记下来。之后由 `_carryWeight` 按离站距离交还。
   *
   * @param {{position: THREE.Vector3, quaternion: THREE.Quaternion}} mount 刀具常量位姿
   * @param {string} slot 源落点
   */
  _captureCarryOffset(mount, slot) {
    this.carryHold = null
    const hold = this._seatHold(mount.position, mount.quaternion)
    if (!hold || (slot && hold.slot !== slot)) return
    const geom = this.anchors.get(hold.slot)
    if (!geom?.parent) return
    // 法向分量单独留一份: 板被抬回落点高度后, 吸盘要多压这么多才还贴着板面
    const axis = _axis.fromArray(this.plateGrip?.axisLocal || [0, -1, 0]).normalize()

    // 姿态也要捕获, 但**只取倾角那一份**(把刀具姿态的板面法线转到落点法线上)。
    //
    // 为什么不整个换成落点姿态: 方板面内转 90° 是同构的, 落点基底与刀具基底之间那个
    // 面内偏航没有物理含义, 整段 slerp 过去会让板在画面上凭空自转一下; 而刀具那一侧的
    // 偏航是钉死的(suctionMountLocal 拿两杯连线定 X, 为的就是 seek 可复现)。
    //
    // 为什么倾角非补不可: 实测该落点法线转角 1.006°, 200mm 板上折算到边缘就是 ±1.75mm,
    // 而板底离 `玻璃放置板` 顶面只有 1.51mm(半板厚 − 0.01mm 净空)。**平移归零之后,
    // 光这一度就足以让板的一条边扎进放置板**, slice_intrusion 实测 36.35mm。
    // 这条 2026-08-06 第一轮曾作为"未处理"记进文档, 第二轮就撞上了。
    _mountNormal.set(0, 1, 0).applyQuaternion(mount.quaternion)
    geom.parent.getWorldQuaternion(_q0)
    _seatNormal.set(0, 1, 0).applyQuaternion(geom.quaternion).applyQuaternion(_q0)
    this.suctionNode.getWorldQuaternion(_q1)
    _seatNormal.applyQuaternion(_q1.invert())        // 世界 -> 翻转节点局部系
    _tilt.setFromUnitVectors(_mountNormal.normalize(), _seatNormal.normalize())

    this.carryHold = {
      slot: hold.slot,
      offset: hold.full.clone(),                 // 三轴全量(翻转节点局部系)
      tilt: _tilt.clone(),                       // 只含倾角, 不含面内偏航
      extraCompressionM: -hold.full.dot(axis),   // 板朝杯体方向挪多少 = 杯要多压多少
    }
  }

  /**
   * 功能: 取板修正的权重 —— 只由"板心离源落点多远"决定, 与法向间距无关.
   *
   * 用**板心**(而不是翻转节点原点)量距离: 两者差着整把刀的长度, 拿节点算会让同一个
   * 阈值在换刀后含义就变了。
   *
   * @param {THREE.Vector3} localPosition 板心在翻转节点局部系的位置(刀具常量算出来的那个)
   * @returns {number} 1 = 还在工位里(修正恒定); 0 = 已在自由空间(完全归刀具常量)
   */
  _carryWeight(localPosition) {
    const geom = this.carryHold ? this.anchors.get(this.carryHold.slot) : null
    if (!geom?.parent || !this.suctionNode) return 0
    geom.parent.updateWorldMatrix(true, false)
    this.suctionNode.updateWorldMatrix(true, false)
    _seat.copy(geom.position).applyMatrix4(geom.parent.matrixWorld)
    _plateWorld.copy(localPosition).applyMatrix4(this.suctionNode.matrixWorld)
    const d = _plateWorld.distanceTo(_seat)
    if (d <= CARRY_HOLD_M) return 1
    if (d >= CARRY_RELEASE_M) return 0
    const s = (d - CARRY_HOLD_M) / (CARRY_RELEASE_M - CARRY_HOLD_M)
    return 1 - s * s * (3 - 2 * s)
  }

  /**
   * 功能: 把刀具常量算出的持板位姿, 按"落点还抓着没有"补上面内修正.
   * @param {{position: THREE.Vector3, quaternion: THREE.Quaternion}} mount suctionMountLocal 的结果
   * @returns {{position: THREE.Vector3, quaternion: THREE.Quaternion}} 原地改过 position 的同一对象
   */
  _applySeatHold(mount) {
    // 优先级: 取板时捕获的那一份(三轴, 按离站距离释放) > 放板端的近落点面内收敛。
    // 两者不叠加 —— 叠加等于对同一笔残差修两次。
    const weight = this._carryWeight(mount.position)
    if (this.carryHold && weight > 0) {
      _delta.copy(this.carryHold.offset).multiplyScalar(weight)
      mount.position.add(_delta)
      // 倾角按同一个权重从单位四元数 slerp 过去; 左乘, 因为 tilt 表达在翻转节点局部系
      _q0.identity().slerp(this.carryHold.tilt, weight)
      mount.quaternion.premultiply(_q0)
      this.seatHold = {
        slot: this.carryHold.slot,
        source: 'carry',
        weight,
        offsetMm: _delta.length() * 1000,
        extraCompressionM: this.carryHold.extraCompressionM * weight,
      }
      return mount
    }

    const hold = this._seatHold(mount.position, mount.quaternion)
    this.seatHold = hold
      ? { slot: hold.slot, source: 'seat', gapMm: hold.gapM * 1000, weight: hold.weight,
        offsetMm: hold.offset.length() * 1000, extraCompressionM: 0 }
      : null
    if (hold) mount.position.add(hold.offset)
    return mount
  }

  /** 把板钉到翻转节点下的一个局部位姿。 */
  _pin(plate, position, quaternion) {
    this.suctionNode.add(plate.root)
    plate.root.position.fromArray(position)
    plate.root.quaternion.fromArray(quaternion).normalize()
    plate.root.updateMatrix()
    plate.root.updateMatrixWorld(true)
  }

  /**
   * 功能: 每帧推进接触求解 —— 板顶到硬表面时吸盘压缩, 而不是把板顶进去.
   *
   * 必须在 rig 写完这一帧的 transform **之后**调(见 useMotionStack 的帧钩子)。
   *
   * ⚠ **每帧都从自由位姿重新算起**, 不在上一帧结果上再修 —— 否则连续帧会把修正累乘,
   * 板会一路往回缩。这同时也是它不破坏 ClipPlayer「seek 是 t 的纯函数」的原因:
   * 自由位姿是 t 的函数, 接触修正是当帧场景的函数, 复合起来仍只依赖 t。
   *
   * @returns {object|null} 接触状态(诊断用); 没在持板或没开时为 null
   */
  update() {
    if (!this.contact) return null
    // 功能关掉/没有吸盘节点: 彻底复位, 不留一个压扁的吸盘在画面上
    if (!this.contactEnabled || !this.suctionNode) {
      this.contact.releaseCups()
      return null
    }
    const plateId = [...this.placed.entries()].find(([, slot]) => slot === 'carried')?.[0]
    const plate = plateId ? this.layer?.get(plateId) : null
    if (!plate) {
      // 手上没板 ≠ 吸盘该立刻弹回自由长。断吸之后波纹段仍被板面顶着, 要等机械臂抬到
      // 唇口脱离才逐渐长回去 —— 一步弹回会让杯子当场穿过刚放下的那块板(2026-08-06)。
      return this.contact.relaxOnPlates(this._seatedPlates(), this.layer?.silicaMm)
    }
    // 先回到自由位姿(贴唇口), 再由接触判据往回退 —— 这一步就是"不累乘"的保证。
    // 面内修正加在这里而不是加在接触判据之后: 两者正交(它只动面内, 接触只动法向),
    // 但接触判据要沿板面法线打射线, 必须打在**面内已经就位**的那块板上。
    const mount = suctionMountLocal(this.plateGrip, plate.geom, this.layer.silicaMm)
    if (mount) {
      this._applySeatHold(mount)
      this._pin(plate, mount.position.toArray(), mount.quaternion.toArray())
    }
    // 板被抬回落点高度之后, 杯子要跟着多压这么多才还贴在板面上 —— 板与杯必须同帧、
    // 由同一个量分发(本文件与 plateContact 头注释那条纪律), 否则杯会悬在板上方。
    return this.contact.resolve(plate.root, plate.geom, this.layer.silicaMm,
      this.seatHold?.extraCompressionM || 0)
  }

  /**
   * 功能: 当帧手上那块板与整机静止几何的全向相交(诊断/验收用, 见 PlateContact.overlap).
   *
   * 为什么不在 update() 里顺手算: 它比每帧那 5 条射线贵得多, 而且**只有探针要它**。
   * 手上没板时返回空 —— 落座的板与座面本来就贴着, 那不是穿模。
   *
   * @returns {{hits: Array<{name: string, depthMm: number}>, maxDepthMm: number, plateId: string}}
   */
  overlap() {
    const empty = { hits: [], maxDepthMm: 0, plateId: '', slot: '' }
    if (!this.contact) return empty
    // 手上那块优先; 没有就看落座的那块 —— "落座态本来就穿"与"取板才穿"是完全不同的
    // 两个病, 只看持板态会把前者整个漏掉(2026-08-06 就这么绕了一圈)。
    const rows = [...this.placed.entries()]
    const [plateId, slot] = rows.find(([, s]) => s === 'carried') || rows[0] || ['', '']
    const plate = plateId ? this.layer?.get(plateId) : null
    if (!plate?.root || !plate?.geom) return empty
    return { ...this.contact.overlap(plate.root, plate.geom, this.layer.silicaMm), plateId, slot }
  }

  /**
   * 功能: 当前**已落座**的板(不含手上那块) —— 断吸后求渐进回弹的约束面.
   * @returns {Array<{root: object, geom: object}>}
   */
  _seatedPlates() {
    const out = []
    for (const [plateId, slot] of this.placed.entries()) {
      if (slot === 'carried') continue
      const plate = this.layer?.get(plateId)
      if (plate?.root && plate?.geom) out.push(plate)
    }
    return out
  }

  /** 开关接触判据; 关掉时立刻把吸盘复位, 不留一个压扁的吸盘在画面上。 */
  setContactEnabled(enabled) {
    this.contactEnabled = Boolean(enabled)
    if (!this.contactEnabled) this.contact?.releaseCups()
  }

  /**
   * 功能: 写一块板的刮取前沿(`scrape` 连续通道经 MachineRig 落到这里).
   *
   * 条带 UV 映射**在板坐在具体落点上时算一次并缓存**(实践中即 scrape_table):
   * 此刻板的世界姿态就是刮取发生时的姿态。条带是板的属性 —— 板之后被吸走搬运,
   * 姿态变了花纹也不许重投影, 所以沿用缓存; 缓存与 placed 同生命周期, clear()
   * 一起清, 向后 seek 的重放会按同样的落座姿态重建, 逐位可复现。
   *
   * 留白纪律(与 show() 同源): 机床方向解析不到、或条带与板轴对不上(bandToUv 返回
   * null)就**什么都不画**并记入 unresolved —— 画一个猜的方向比不画更坏。
   *
   * @param {string} plateId 板号
   * @param {{loosen?: number, clear?: number, pass?: number}} phases 前沿进度与层号
   * @param {object|null} region compiled.scrapeRegions 的一项(板 cm 帧, 含分层的 passes)
   * @returns {boolean} 是否生效
   */
  setScrape(plateId, phases, region) {
    if (!this.layer || !region) return false
    const key = String(plateId || '')
    const plate = this.layer.get(key)
    if (!plate) return false

    let uvBand = this._scrapeUv.get(key)
    if (!uvBand) {
      // 落座门槛: 没落到具体落点(还在手上/从未出场)时不建映射 —— 等它落座
      const slot = this.placed.get(key)
      if (!slot || slot === 'carried') return false
      if (this._machineDirs === undefined) {
        this._machineDirs = machineDirsWorld(this.manifest, this._resolveNode)
        if (!this._machineDirs && !this.unresolved.includes('scrape:machine-dirs')) {
          this.unresolved.push('scrape:machine-dirs')
        }
      }
      if (!this._machineDirs) return false
      plate.root.updateWorldMatrix(true, false)
      uvBand = bandToUv(region, plate.root.getWorldQuaternion(_q0), this._machineDirs)
      if (!uvBand) {
        if (!this.unresolved.includes(`scrape:${key}`)) this.unresolved.push(`scrape:${key}`)
        return false
      }
      this._scrapeUv.set(key, uvBand)
    }
    // region 透传到实体层: 分层刮取的总刀数(passes)在那里换算成残余硅胶厚度
    return this.layer.applyScrape(key, phases, uvBand, region)
  }

  /**
   * 功能: 写一块板的点样色带渐现进度(`spot` 连续通道经 MachineRig 落到这里).
   *
   * UV 映射与 setScrape 同一条纪律: 板落座在点样座时算一次并缓存(此刻板正对 6X/7Y
   * 机床轴), 之后板被搬走也不重投影 —— 色带是板的属性。机床轴 id 与标定方向由
   * region.machine 声明(编译器 SPOT_BAND_CALIB 的一部分, 不在前端猜)。
   *
   * @param {string} plateId 板号
   * @param {Object<number, number>} fills 各条带的渐现进度(键=1 起数的条带号)
   * @param {object|null} region compiled.spotRegions 的一项(板 cm 帧, bands 数组)
   * @returns {boolean} 是否生效
   */
  setSpot(plateId, fills, region) {
    if (!this.layer || !Array.isArray(region?.bands) || !region.bands.length) return false
    const key = String(plateId || '')
    const plate = this.layer.get(key)
    if (!plate) return false

    let uvBands = this._spotUv.get(key)
    if (!uvBands) {
      // 落座门槛: 没落到具体落点(还在手上/从未出场)时不建映射 —— 等它落座
      const slot = this.placed.get(key)
      if (!slot || slot === 'carried') return false
      const machine = region.machine || {}
      const dirs = machineDirsWorld(this.manifest, this._resolveNode, {
        xAxis: machine.xAxis || 'axis_6x',
        yAxis: machine.yAxis || 'axis_7y',
        xDir: machine.xDir ?? 1,
        yDir: machine.yDir ?? 1,
      })
      if (!dirs) {
        if (!this.unresolved.includes('spot:machine-dirs')) this.unresolved.push('spot:machine-dirs')
        return false
      }
      plate.root.updateWorldMatrix(true, false)
      const quat = plate.root.getWorldQuaternion(_q0)
      const mapped = region.bands.map((band) => bandToUv(
        { plateSizeCm: region.plateSizeCm, bandCm: band.bandCm, fill: band.fill },
        quat,
        dirs,
      ))
      if (mapped.some((uv) => !uv)) {
        if (!this.unresolved.includes(`spot:${key}`)) this.unresolved.push(`spot:${key}`)
        return false
      }
      uvBands = mapped
      this._spotUv.set(key, uvBands)
    }
    const bands = uvBands.map((uv, index) => ({ uv, fill: Number(fills?.[index + 1]) || 0 }))
    return this.layer.applySpot(key, bands)
  }

  /**
   * 功能: 写一块板的溶剂润湿前沿(`wet` 连续通道经 MachineRig 落到这里).
   *
   * 展缸里的板与刮台机床轴不对齐, machine 锚定必然拒画 —— 锚定按板的实际姿态选:
   * 竖插的板走重力锚定(下沿浸槽), **本机的卧式缸**(板平躺, 溶剂从槽端水平爬)走
   * 槽向锚定(troughDirsWorld, 槽心取 manifest.tanks[].liquidNode)。落座时算一次并缓存。
   *
   * @param {string} plateId 板号
   * @param {number} front 前沿进度 0..1(相对 region 的前沿目标高度)
   * @param {object|null} region compiled.wetRegions 的一项(板 cm 帧)
   * @returns {boolean} 是否生效
   */
  setWet(plateId, front, region) {
    if (!this.layer || !region) return false
    const key = String(plateId || '')
    const plate = this.layer.get(key)
    if (!plate) return false

    let uv = this._wetUv.get(key)
    if (!uv) {
      const slot = this.placed.get(key)
      if (!slot || slot === 'carried') return false
      plate.root.updateWorldMatrix(true, false)
      const quat = plate.root.getWorldQuaternion(_q0)
      const silicaUp = plate.geom?.silicaUp !== false
      const dirs = gravityDirsWorld(quat, silicaUp)
        || this._troughDirs(slot, plate, quat, silicaUp)
      if (!dirs) {
        // 两种锚定都解不出时留白 —— 与 machine 锚定的对齐门槛同一条"宁可不画"纪律
        if (!this.unresolved.includes(`wet:${key}`)) this.unresolved.push(`wet:${key}`)
        return false
      }
      uv = bandToUv(
        { plateSizeCm: region.plateSizeCm, bandCm: region.bandCm, fill: region.fill || { axis: 'y', dir: 1 } },
        quat,
        dirs,
      )
      if (!uv) {
        if (!this.unresolved.includes(`wet:${key}`)) this.unresolved.push(`wet:${key}`)
        return false
      }
      this._wetUv.set(key, uv)
    }
    return this.layer.applyWet(key, front, uv)
  }

  /** 卧式缸的槽向锚定: 槽心取该缸液面盒节点(manifest.tanks[].liquidNode)。 */
  _troughDirs(slot, plate, quat, silicaUp) {
    const match = /^tank:(\d+)$/.exec(String(slot || ''))
    if (!match) return null
    const spec = (this.manifest?.tanks || []).find((tank) => tank.id === `tank${match[1]}`)
    const path = String(spec?.liquidNode || '')
    const node = this._resolveNode(path) || this._resolveNode(path.split('/').pop() || '')
    if (!node) return null
    node.updateWorldMatrix(true, false)
    plate.root.updateWorldMatrix(true, false)
    return troughDirsWorld(
      quat,
      plate.root.getWorldPosition(_plateWorld),
      node.getWorldPosition(_seat),
      silicaUp,
    )
  }

  /** 补光打在板上的响应, 透传给实体层(见 PlateFaceLayer.setFlash)。 */
  setFlash(level) {
    return Boolean(this.layer?.setFlash(level))
  }

  /** 收走一块板(归还板池, 不销毁几何)。 */
  hide(plateId) {
    this.placed.delete(plateId)
    return this.layer.release(plateId)
  }

  /**
   * 清场 —— ClipPlayer 向后 seek 时 rig.home() 的一部分, 保证重放可复现。
   *
   * 吸盘必须一起复位: 驱动层的 `home()`/`restoreLocal` 只还原它认领的那五类节点,
   * 而橡胶段是 ACTUATOR_FLIP_SUCTION 的**孙节点**, 不在其中 —— 不自己复位, 拖过一次
   * 放板段之后吸盘就永远压扁着(与灯"拖过补光段就再也不灭"是同一类坑)。
   */
  clear() {
    for (const plateId of [...this.placed.keys()]) this.layer?.release(plateId)
    this.placed.clear()
    this.seatHold = null
    // 与 placed 同一类状态: 向后 seek 走 home()->clear()->重放事件, carry 会重新捕获,
    // 于是同一个 t 的结果逐位可复现(ClipPlayer 的 seek 契约)。
    this.carryHold = null
    // 痕迹 UV 映射与 placed 同生命周期: 重放时板按同样的落座姿态重建同一份映射。
    // 机床方向缓存(_machineDirs)刻意**不**清 —— 它只依赖装配结构, 与播放进度无关。
    this._scrapeUv.clear()
    this._spotUv.clear()
    this._wetUv.clear()
    this.contact?.releaseCups()
  }

  /** 供界面/验收的只读状态。 */
  status() {
    return {
      anchors: this.anchors.size,
      missingAnchors: [...this.missing],
      unresolved: [...this.unresolved],
      suctionBound: Boolean(this.suctionNode),
      contactEnabled: this.contactEnabled,
      contactReady: Boolean(this.contact?.ready),
      contact: this.contact?.last || null,
      // 面内修正是**有意为之**的横向偏离, 必须能被外部判据读到并核对(见
      // tools/visual_validation/verify_plate_suction.py 的"板心横向"那一节) ——
      // 不外露的话, 那条判据只能在"恒为 0"与"完全不判"之间二选一。
      seatHold: this.seatHold ? { ...this.seatHold } : null,
      rows: [...this.placed.entries()].map(([plateId, slot]) => ({ plateId, slot })),
      // 刮取状态同理外露(devHooks 的 plates() 因此自动可读, 验收脚本零新钩子):
      // 前沿进度取实体层的最近一次写入, uvBand 取本层缓存的映射。
      scrape: this._scrapeStatus(),
      // 点样色带/展开润湿同理外露 —— 缸内板被壳与盖挡着, 截图验收看不见,
      // 只能靠这里的数值断言(shot_plate_traces.py)。
      traces: this._traceStatus(),
    }
  }

  /** 供 status() 的痕迹快照: 各在场板的色带填充与润湿前沿(无痕迹的板不出现)。 */
  _traceStatus() {
    const out = []
    for (const [plateId] of this.placed.entries()) {
      const entry = this.layer?.get(plateId)?.trace
      if (!entry || (!entry.spot && !entry.wet)) continue
      out.push({
        plateId,
        spotFills: entry.spot ? entry.spot.map((band) => +band.fill.toFixed(4)) : null,
        wetFront: entry.wet ? +entry.wet.front.toFixed(4) : null,
      })
    }
    return out
  }

  /** 供 status() 的刮取快照; 场上最多一块板在被刮, 报第一个有状态的。 */
  _scrapeStatus() {
    for (const [plateId] of this.placed.entries()) {
      const uvBand = this._scrapeUv.get(plateId) || null
      const last = this.layer?.get(plateId)?.trace?.last || null
      if (!uvBand && !last) continue
      return {
        plateId,
        loosen: last ? last.loosen : 0,
        clear: last ? last.clear : 0,
        uvBand: uvBand ? { ...uvBand } : null,
      }
    }
    return null
  }

  dispose() {
    this.clear()
    this.contact?.dispose()
    this.contact = null
    this.anchors.clear()
    this.suctionNode = null
  }
}
