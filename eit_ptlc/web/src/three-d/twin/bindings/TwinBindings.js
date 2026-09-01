/**
 * 功能: 状态到视觉的映射层 —— 每帧把 TwinFeed 里的数据写进 three.js 场景对象.
 *
 * 这是整个三维模块的"心脏": 所有"设备状态长什么样"的决定都集中在这里, 场景管理器
 * 只负责渲染, 数据层只负责搬运. 想改某个状态的表现形式, 只需要改本文件与 manifest,
 * 不必碰渲染或数据管道.
 *
 * 映射一览:
 *   健康度        -> 工位状态灯的自发光颜色/强度(错误时按频率闪烁)
 *   Tank_State[8] -> 展缸液面的高度(scale.y)与颜色
 *   轴实际位置    -> 对应 CARRIAGE 节点沿声明轴向平移
 *   机器人关节角  -> 关节节点旋转(需模型侧完成关节链重建后启用)
 *   执行器反馈    -> actuator/linkage 绝对值；无几何声明时只保留真实状态台账
 *   mounted_tool  -> 工具所有权转移到 TOOL_MOUNT；重连错位直接恢复真实挂载位
 *   步骤活跃度    -> 工位状态灯短暂增亮, 提示"这里正在动"
 */
import * as THREE from 'three'

import { ARRIVE_FACTOR, clamp, createChannel, push, step } from './interp.js'
import { MachineStateDriver } from '../../anim/MachineStateDriver.js'
// 液面几何(枢轴补偿/空缸显隐)与离线链共用同一份实现 —— 缘由见那个文件的模块头
import { applyLiquidLevel, applyLiquidVisible, captureLiquidBase } from './liquidPivot.js'
import { levelFromMl } from './TankLiquidModel.js'
// 粉柱的落点(恒锚在腔的 c1 端)/换算/账本取量与离线链共用同一份纯函数(理由同 liquidPivot):
// 各写一遍的表现是"演示里粉贴着底、实况页粉浮在中间", 没有任何指标会报警。
import { applyPowderColumn, contentAmount, levelFromMm3 } from './powderPivot.js'

/**
 * 工艺灯 0↔1 的斜坡时长(秒)。数值照抄离线片段 `clip_compiler.emit_vision_capture`
 * 的 VISION_LIGHT_RISE_S / FALL_S —— 同一盏灯, 两条链观感不该不一样。
 */
const LIGHT_RISE_S = 0.25
const LIGHT_FALL_S = 0.35

/** "算不算亮着"的阈值; 必须与 MachineStateDriver.bloomLights 的判据一致 */
const BLOOM_LIT_EPS = 0.01

/**
 * 已用粉桶的"倒扣"旋转: 绕单件局部 X 轴转 π(桶的立轴是局部 Y, 绕水平轴翻即头朝下)。
 * 用户定案(2026-08-15): 粉桶三态 = FRESH 直立 / USED 倒扣在位 / ABSENT 不画。
 */
const FLIP_X = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), Math.PI)

/**
 * 驻位液体朝账本值趋近的时间常数(秒)。
 *
 * 账本是 0.5s 一帧的阶跃(material_feedback 的推流周期), 直接赋值会让液面一跳一跳。
 * 取 0.8s: 比推流周期长, 足以把阶跃抹平; 又远短于一轮注液的真实时长(排液 20s + 沉淀 5s),
 * 所以不会让人觉得"液面追不上"。终值永远是账本值 —— 与包络驱动不同, 这条不会漂。
 */
const STATION_LIQUID_RAMP_S = 0.8

/** 复用的临时对象, 避免每帧产生垃圾 */
const TMP_COLOR = new THREE.Color()
const TMP_QUAT = new THREE.Quaternion()

/**
 * 机构在途(mechanism_state 的 `moving: true`)时, 动画保持在离终点多远处等到位信号.
 * 取 inputRange 跨度的比例, 吸盘翻转的 180° 上就是 27°.
 *
 * 纯观感旋钮, 调它只影响"停一下"有多明显: 太小看不出在等, 太大像卡住了.
 * 它**不影响终态正确性** —— 到位信号一到就走完全程, 与这个数无关.
 *
 * 2026-08-05 由 0.1 提到 0.15: 头段改成匀速(见 _updateMechanisms)之后, 保持段是按
 * 同一速度铺开的一小段可见行程, 而不再是指数尾巴上几乎看不见的一点点.
 */
const MECHANISM_APPROACH_GAP = 0.15

/**
 * 在途配速兜底(秒): 既没有 expectedS 实测样本、spec 也没给 transitionS 时用.
 * 正常路径永远轮不到它 —— rig_map 的每个机构都写了 transitionS.
 */
const MECHANISM_FALLBACK_STROKE_S = 0.6

/**
 * 到位放行后收尾段的加速倍率.
 *
 * 为什么要 >1: 放行时实物**已经到位了**(DI 已置位), 画面还差最后一段. 用头段的速度慢慢
 * 补, 画面就整体滞后于实物; 略快收口才能追上. 又不能太大, 否则最后一下"啪"地弹过去,
 * 与前面的匀速之间出现明显速度断点 —— 2.5 是"追得上又看不出断点"的折中.
 */
const MECHANISM_CLOSING_BOOST = 2.5

export class TwinBindings {
  /**
   * 功能: 建立绑定层, 预解析所有需要驱动的场景节点.
   *
   * 预解析很重要: 把 manifest 里的字符串路径一次性解析成对象引用并缓存, 渲染循环里
   * 就只剩纯粹的数值计算与属性赋值, 不再有查表开销.
   *
   * @param {object} manifest device-manifest.json 内容
   * @param {Map<string, THREE.Object3D>} nodeIndex 节点路径索引
   * @param {import('./TwinFeed.js').TwinFeed} feed 数据源
   */
  constructor(manifest, nodeIndex, feed) {
    this.manifest = manifest
    this.feed = feed
    this.elapsed = 0

    /** @type {Array<{station: object, mesh: THREE.Mesh, material: THREE.Material}>} */
    this.statusLights = []
    /**
     * 整机三色塔灯(真实零件, 由 PLC 输出位经 signal_light 事件驱动).
     * @type {{spec: object, mesh: THREE.Mesh, material: THREE.Material,
     *         lastKey: string|null, takenOver: boolean}|null}
     */
    this.signalLight = null
    /** 辉光选集需要重放的标记(塔灯首次被实时数据接管时置位, 读后即清) */
    this._bloomDirty = false
    /** @type {Array<{tank: object, mesh: THREE.Object3D, material: THREE.Material,
     *   baseScale: THREE.Vector3, basePosition: THREE.Vector3, baseMinY: number}>} */
    this.tanks = []
    /**
     * 注射泵可动件. plunger 走 position(基准是**局部**坐标, 上样泵还骑在 6X 轴上),
     * liquid 走 scale.y **加**枢轴补偿(出厂 GLB 的枢轴在几何中心, 见 liquidPivot.js)
     * —— 两者由同一个 level 驱动, 见 _updatePumps.
     * @type {Array<{spec: object, index: number, plunger: THREE.Object3D,
     *   plungerBase: THREE.Vector3, travel: THREE.Vector3, liquid: THREE.Object3D,
     *   material: THREE.Material, baseScale: THREE.Vector3, basePosition: THREE.Vector3,
     *   baseMinY: number, lastLevel: number|undefined}>}
     */
    this.pumps = []
    /**
     * 驻位液体(工位座位实例腔内的液柱; 现役只有收集工位那只 40mL 样品瓶)。
     * 由**物料账本**而非动作包络驱动, 理由见 _bindStationLiquids 的头注。
     * @type {Array<{spec: object, mesh: THREE.Object3D, material: THREE.Material,
     *   seat: string, exaggeration: number, ml: number, baseScale: THREE.Vector3,
     *   basePosition: THREE.Vector3, baseMinY: number, lastLevel: number|undefined}>}
     */
    this.stationLiquids = []
    /**
     * 耗材内容物里的**粉柱**(粉桶内刮下来的硅胶粉)。与驻位液体同一条驱动纪律(物料账本),
     * 多两样东西: 落点锚在腔的 c1 端(吹气头那一头, 翻桶也不动), 且带洗脱色相位。
     * @type {Array<{spec: object, mesh: THREE.Object3D, material: THREE.Material,
     *   seat: string, kind: string, exaggeration: number, mm3: number, tint: number,
     *   baseColor: THREE.Color|null, elutedColor: THREE.Color|null,
     *   baseScale: THREE.Vector3, basePosition: THREE.Vector3, baseMinY: number,
     *   lastLevel: number|undefined}>}
     */
    this.consumablePowders = []
    /** @type {Array<{axis: object, node: THREE.Object3D, basePosition: THREE.Vector3, direction: THREE.Vector3}>} */
    this.axes = []
    /** @type {Map<string, THREE.Object3D>} 工位 id -> 工位根节点(供拾取与飞行使用) */
    this.stationRoots = new Map()
    /** 物料 CAD 刚体；仅在 material_state 完整快照变化时更新。 */
    this.materialRack = []
    this.materialStaging = []
    this.materialMagazines = []
    /** 料仓堆叠是否已交给薄层板层绘制(见 delegateMagazines)。 */
    this.magazinesDelegated = false
    /**
     * @type {Set<string>} 此刻由 TrayBinding 接管显隐的载荷节点路径(见 setTransitOwned)。
     * 在途的托盘/耗材挂在机械臂上, 而账本此刻说它"既不在货架也不在中转位",
     * 本层按账本判显隐会把它判成隐藏 —— 两边逐帧互顶的结果是闪烁。让位范式与
     * delegateMagazines 一致: 谁画谁负责, 另一方完全不碰。
     */
    this.transitOwned = new Set()
    /** @type {Record<string, object>} 最近一帧的料仓张数(magazine id -> {count, capacity}) */
    this.magazineCounts = {}
    this.materialVisibleStates = new Set(this.manifest.inventory?.visibleStates || ['FRESH'])
    this.materialVisibleWhenSampleId = this.manifest.inventory?.visibleWhenSampleId !== false
    this._lastMaterialSnapshot = null

    this.nodeIndex = nodeIndex
    this.missing = []
    // Twin 与 Studio 共用唯一机器状态写入层；本文件只负责从实时缓冲取样。
    this.machine = new MachineStateDriver({
      manifest,
      resolve: (path) => this._resolve(path),
    })
    this.robot = this.machine.robot
    this.missing.push(...this.machine.missing)

    /**
     * 外罩透视: 工位大多位于机器内部, 被机架钣金与外罩挡住. 选中某个工位时把外壳
     * 淡化为半透明, 内部机构就露出来了 —— 既解决遮挡, 也是很有辨识度的视觉效果.
     * @type {Array<{material: THREE.Material, baseOpacity: number, baseTransparent: boolean}>}
     */
    this.enclosure = []
    /** @type {Array<{mesh: THREE.Mesh, baseCast: boolean}>} 外壳网格(透视时切投影用) */
    this.enclosureMeshes = []
    this.enclosureOpacity = 1
    this.enclosureTarget = 1
    /** 外壳当前是否投影(淡化到半透明以下时关掉, 否则鬼影壳会投一片实影) */
    this._enclosureCasting = true

    /**
     * 本帧是否真的动了场景几何(轴/机器人/液面/外壳投影切换). 供 SceneManager 的
     * 按需阴影更新使用: 目标值收敛后这里不再置位, 阴影贴图自动停止重渲.
     */
    this._moved = false
    /** @type {number[]|null} 上一帧应用的机器人关节角(变化检测用) */
    this._lastJoints = null
    /** @type {(() => void)|null} 主轴事件订阅的退订函数(见 _bindSpindles) */
    this._offSpindleNodes = null

    /** @type {Map<string, object>} 机构两态信号的缓动通道(值域 = inputRange 的 0..1) */
    this._mechanismChannels = new Map()
    /**
     * 正走匀速路径的机构 id(见 _updateMechanisms)。
     *
     * 为什么要跨帧记: `moving` 转 false 那一刻还差最后一段没走完, 若当帧就掉回指数曲线,
     * 收尾又会"啪"地弹过去 —— 正是本次要修的观感。所以进场靠 moving:true, **退场靠
     * 真正贴住终点**, 而不是靠 moving 变化。
     */
    this._inflightMechanisms = new Set()
    this._warnedHoldValue = new Set()
    /** 已标 rigged 却查不到执行器绑定的机构 id(每个只告警一次, 锁"静默不动") */
    this._warnedMechanisms = new Set()
    this._riggedMechanismIds = new Set(
      (manifest.realtime?.mechanisms || []).filter((m) => m?.rigged).map((m) => m.id),
    )

    this._bindStations(nodeIndex)
    this._bindSignalLight()
    this._bindTanks(nodeIndex)
    this._bindStationLiquids()
    this._bindConsumablePowders()
    this._bindPumps(nodeIndex)
    this._bindAxes(nodeIndex)
    this._bindMaterials()
    this._bindEnclosure()
    this._bindSpindles()

    if (this.missing.length) {
      console.warn(`[twin] manifest 中有 ${this.missing.length} 个节点在模型里找不到:`, this.missing)
    }
  }

  /**
   * 功能: 把主轴自转接到流程事件上 —— 实时页判定"刀在不在转"的唯一依据.
   *
   * 为什么不走 mechanism_state: **PLC 里根本没有主轴的独立信号**。
   * manual_points.photoscrape 六个机构里最像的是 `ps_motor`「刮板拍照无刷电机」, 但
   * plc_photoscrape.yaml 的 A40 动作注释写明它是**吸粉**的吸力源(%QX7.3, 真空阀 %QX7.2
   * 只管通断), 拿它驱主轴会在"停吸不停刀"的时刻显示反。
   *
   * 所以判据取 manifest.spindles[].triggerAction(现役 `photoscrape.scrape`)这条动作本身:
   * 它在跑 = CNC 在插补 = 刀在切削。用 vm_node_enter/done 而不是 vm_vars 的循环变量:
   * 后者在 runtime/events.py 的 _DROPPABLE_TYPES 里, 队列满会被丢, 当不了状态源。
   *
   * @returns {void}
   */
  _bindSpindles() {
    const byAction = new Map()
    for (const spec of this.manifest.spindles || []) {
      if (spec?.triggerAction) byAction.set(String(spec.triggerAction), String(spec.id))
    }
    if (!byAction.size) return
    this._offSpindleNodes = this.feed.addNodeSink?.((event) => {
      const id = byAction.get(String(event?.action || ''))
      if (!id) return
      if (event.type === 'vm_node_enter') this.machine.setSpindle(id, true)
      // done / failed 都停: 异常中止时刀当然也不转了
      else if (event.type === 'vm_node_done' || event.type === 'operation_failed') {
        this.machine.setSpindle(id, false)
      }
    }) || null
  }

  /**
   * 功能: 按 manifest 里的节点路径取场景对象, 找不到时退回按节点名匹配.
   *
   * 为什么需要退路: manifest 的路径来自 Blender 导出的层级, 而前端加载的是经过
   * gltf-transform 优化的模型 —— 其中 prune 会删掉没有网格也没有子节点的空节点,
   * join 会合并部分节点, 导致中间层级塌陷、完整路径对不上. 节点名本身是唯一的
   * (LIQUID_3、LIGHT_STATUS_DEVELOP 等都带明确后缀), 因此按名字兜底既安全又稳妥.
   *
   * 对外的名字是 resolveNode —— TrayBinding 也吃这套解析(共用一份兜底规则, 免得
   * 优化后的模型层级塌陷时两处各自失配); 类内旧调用点仍走 _resolve, 不做无谓改名。
   *
   * @param {string} path manifest 中声明的节点路径
   * @returns {THREE.Object3D|undefined} 命中的对象
   */
  resolveNode(path) {
    return this._resolve(path)
  }

  /** resolveNode 的内部实现; 语义与注释见上。 */
  _resolve(path) {
    if (!path) return undefined
    const direct = this.nodeIndex.get(path)
    if (direct) return direct
    const leaf = path.split('/').pop()
    return leaf ? this.nodeIndex.get(leaf) : undefined
  }

  /**
   * 功能: 解析工位根节点与状态灯.
   * @param {Map<string, THREE.Object3D>} nodeIndex 节点索引
   * @returns {void}
   */
  _bindStations(nodeIndex) {
    for (const station of this.manifest.stations || []) {
      // glbNode 为 null 表示该工位在模型里没有独立几何(如泵站的实体在柜内未单独建组),
      // 它仍然出现在工位列表里展示遥测与动作, 只是不参与拾取与相机飞行
      if (station.glbNode) {
        const root = this._resolve(station.glbNode)
        if (root) this.stationRoots.set(station.id, root)
        else this.missing.push(station.glbNode)
      }

      if (!station.statusLight) continue
      const lightNode = this._resolve(station.statusLight)
      if (!lightNode) {
        this.missing.push(station.statusLight)
        continue
      }
      // 状态灯可能是一个包着网格的节点, 取其下第一个网格
      let mesh = lightNode.isMesh ? lightNode : null
      if (!mesh) lightNode.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
      if (!mesh) continue

      // 每个灯独占一份材质, 否则改一个颜色会把所有灯一起改掉
      const material = mesh.material.clone()
      mesh.material = material
      this.statusLights.push({ station, mesh, material })
    }
  }

  /**
   * 功能: 解析整机三色塔灯的灯罩网格(manifest.signalLight).
   *
   * 与 stations[].statusLight(逐工位示意灯条, 已停用)是两回事: 这里绑定的是真实
   * 塔灯零件, 数据源是 PLC 三色灯输出位的 signal_light 事件. 绑定时只克隆材质、
   * 不改任何属性 —— 脱机演示与 live 收到首帧之前, 保持管线烘焙的静态观感.
   * @returns {void}
   */
  _bindSignalLight() {
    const spec = this.manifest.signalLight
    if (!spec?.glbNode) return
    const node = this._resolve(spec.glbNode)
    if (!node) {
      this.missing.push(spec.glbNode)
      return
    }
    let mesh = node.isMesh ? node : null
    if (!mesh) node.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
    if (!mesh) return

    // 独占一份材质: 即使 MAT_STATUS_LIGHT 将来被别的零件共用, 改色也不会互相污染
    const material = mesh.material.clone()
    mesh.material = material
    this.signalLight = { spec, mesh, material, lastKey: null, takenOver: false }
  }

  /**
   * 功能: 解析 8 个展缸的液面网格.
   *
   * ⚠ 绝不能把液面材质改成 transparent —— 那正是 2026-08-03 "液体糊在缸外面"的成因:
   * 缸体与溶液槽用的 MAT_TANK 是 BLEND(玻璃), 经 GLTFLoader 会拿到 depthWrite=false;
   * 液体一旦也进透明队列, 两者就只能按**物体中心**排序, 而液面盒在缸的前沿、中心比缸体
   * 更近相机, 于是液体被画在缸壁之上, 成了一条实心色带而非"透过玻璃看到的液体".
   * 保持液体不透明: 它走前置的实体队列正常写深度, 玻璃缸壁随后混合叠上去, 顺序天然正确.
   * 管线侧的 MAT_LIQUID 也因此锁死 alpha=1.0 且不带 transmission(见 material_semantics.yaml).
   *
   * @param {Map<string, THREE.Object3D>} nodeIndex 节点索引
   * @returns {void}
   */
  _bindTanks(nodeIndex) {
    for (const tank of this.manifest.tanks || []) {
      if (!tank.liquidNode) continue
      const node = this._resolve(tank.liquidNode)
      if (!node) {
        this.missing.push(tank.liquidNode)
        continue
      }
      let mesh = node.isMesh ? node : null
      if (!mesh) node.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
      if (!mesh) continue

      // 独占一份材质(改色不污染别的缸); 透明度/深度写入一律沿用 glTF 里的声明, 不覆写
      const material = mesh.material.clone()
      mesh.material = material
      this.tanks.push({
        tank,
        mesh: node,
        material,
        // 记下建模时的满液位尺寸(运行时按液位比例缩 y)与枢轴补偿量 —— 三个字段成套,
        // 由 captureLiquidBase 统一发放, 与离线链 _bindLiquids 同源. 见 liquidPivot.js
        ...captureLiquidBase(node),
      })
    }
  }

  /**
   * 功能: 解析**驻位液体**(工位座位实例腔内的液柱, 现役只有收集工位那只 40mL 样品瓶).
   *
   * 补的是一处长期缺口: manifest.liquids 此前**只有离线链**在消费
   * (anim/MachineStateDriver._bindLiquids + demo/flowSim + demo/actionSim), 实时链一处都
   * 没有 —— 于是 /3d/demo 上瓶里能看到淋洗液涨起来, /3d/live 上那只瓶永远是空的,
   * 而画面完全正常、没有任何指标会说它少画了东西。
   *
   * 驱动源刻意选**物料账本**而不是动作包络(展缸/泵那两条走的是包络):
   *   · 账本是持久态 —— 刷新页面、断线重连、甚至跑完一整批之后再打开三维, 瓶里该有多少
   *     还是多少; 包络只有动作在跑的那几拍有值, 之后归零。而"使用后的旧状态"这件事本身
   *     要的就是持久态。
   *   · 账本已经把"哪只瓶坐在收集位上"算好了(payload_seat), 不必在前端第二次推断身份。
   *   · 代价是没有注液过程的逐帧曲线 —— 用 interp 朝账本值趋近补上, 观感与包络接近,
   *     但终值永远由账本说了算, 不会出现"演示涨到一半、实况停在别处"。
   *
   * 深度排序的结论与展缸/泵**完全一致**: 液柱材质绝不能改成 transparent(玻璃瓶
   * MAT_SAMPLE_VIAL 罩在外面, 同一个拓扑)。这里只克隆材质留作将来按状态写色, 不改任何
   * 透明度声明。
   *
   * @returns {void}
   */
  _bindStationLiquids() {
    for (const spec of this.manifest.liquids || []) {
      if (!spec?.node) continue
      const node = this._resolve(spec.node)
      if (!node) {
        this.missing.push(spec.node)
        continue
      }
      let mesh = node.isMesh ? node : null
      if (!mesh) node.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
      if (!mesh) continue
      // 独占一份材质: 将来按状态写色时不污染展缸/泵那 11 处共用的 MAT_LIQUID
      const material = mesh.material.clone()
      mesh.material = material
      this.stationLiquids.push({
        spec,
        mesh: node,
        material,
        seat: String(spec.seat || ''),
        exaggeration: Number(spec.exaggeration) || 1,
        ml: 0,
        ...captureLiquidBase(node),
      })
    }
  }

  /**
   * 功能: 按物料账本把驻位液体的液面写到位.
   *
   * 身份链: manifest.liquids[].seat -> snapshot.payloadSeats 里那一行 -> (kind, plate, hole)
   * -> snapshot.cells 里那一格的 liquid_ml。座上没件就归零(瓶被搬走了, 液柱不该留在原地)。
   *
   * 用指数趋近而不是直接赋值: 账本是 0.5s 一帧的阶跃, 直接写会让液面一跳一跳。趋近的终值
   * 永远是账本值, 所以不会像纯包络那样漂 —— 慢一点, 但不会错。
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateStationLiquids(delta) {
    if (!this.stationLiquids.length) return
    const snapshot = this.feed.materialStore.status().snapshot
    const seated = new Map(
      (snapshot?.payloadSeats || []).map((row) => [row.seat, row]),
    )
    const cellByKey = new Map(
      (snapshot?.cells || []).map((cell) => [`${cell.kind}:${cell.plate}:${cell.hole}`, cell]),
    )

    for (const entry of this.stationLiquids) {
      const row = seated.get(entry.seat)
      const cell = row && row.hole
        ? cellByKey.get(`${row.kind}:${row.plate}:${row.hole}`)
        : null
      const targetMl = Math.max(0, Number(cell?.liquid_ml) || 0)
      // 指数趋近: 与 interp 的 ARRIVE 同款手感, 但这里只有一个标量不必上通道
      const k = 1 - Math.exp(-Math.max(0, delta) / STATION_LIQUID_RAMP_S)
      entry.ml += (targetMl - entry.ml) * k
      if (Math.abs(targetMl - entry.ml) < 1e-3) entry.ml = targetMl

      const level = clamp(levelFromMl(entry.spec.cavity, entry.ml, entry.exaggeration), 0, 1)
      if (entry.lastLevel === undefined || Math.abs(level - entry.lastLevel) > 1e-3) {
        entry.lastLevel = level
        this._moved = true
      }
      applyLiquidLevel(entry, entry.mesh, level)
      applyLiquidVisible(entry.mesh, level)
    }
  }

  /**
   * 功能: 解析**耗材内容物里的粉柱**(粉桶内刮下来的硅胶粉).
   *
   * 与 _bindStationLiquids 同一条驱动纪律(物料账本而非动作包络, 理由见那里的头注),
   * 但多两样东西:
   *   · **落点恒在腔的 c1 端** —— 粉被滤纸内衬拦在吹气头那一头, 刮完翻料倒粉时桶转
   *     180°, 粉跟着桶转、相对桶纹丝不动(powderPivot.powderBaseAxial 不吃任何姿态)。
   *   · **带洗脱色相位** —— 淋洗前后换色, 故这里克隆材质是**必须**而不是"留作将来"。
   *
   * 契约里没有 consumableContents(粉柱几何还没进管线)时整段空跑: 两条链同一条降级路径,
   * 数据仍在账本里、三维不表现, 等管线落地自动生效。
   *
   * @returns {void}
   */
  _bindConsumablePowders() {
    for (const spec of this.manifest.consumableContents?.kinds || []) {
      if (spec?.kind !== 'powder' || !spec.node) continue
      const node = this._resolve(spec.node)
      if (!node) {
        this.missing.push(spec.node)
        continue
      }
      let mesh = node.isMesh ? node : null
      if (!mesh) node.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
      if (!mesh) continue
      // 独占一份材质: tint 相位要写 color, 共用就会把货架上另外 5 只桶一起染色
      const material = mesh.material.clone()
      mesh.material = material
      this.consumablePowders.push({
        spec,
        mesh: node,
        material,
        seat: String(spec.seat || ''),
        kind: String(spec.accepts || 'collector'),
        exaggeration: Number(spec.exaggeration) || 1,
        baseColor: material.color ? material.color.clone() : null,
        elutedColor: spec.elutedColor ? new THREE.Color(spec.elutedColor) : null,
        mm3: 0,
        tint: 0,
        ...captureLiquidBase(node),
      })
    }
  }

  /**
   * 功能: 按物料账本把粉柱的粉量/颜色/落点写到位.
   *
   * 身份链与驻位液体逐字相同: spec.seat -> payloadSeats 那一行 -> (kind, plate, hole)
   * -> cells 那一格。取量走 powderPivot.contentAmount 的回退梯(账本直给 → 现算 → 标称),
   * 两条链共用同一份规则。
   *
   * 落点**每帧都写**而不只在粉量变时写: 落点本身只由 level 决定, 但 applyLiquidLevel
   * 写的是节点的**局部** position/scale, 而 captureLiquidBase 的基准来自 quantize 之后的
   * 节点 —— 每帧照写一遍才与离线链(updatePowders 同样每帧写)逐位同源, 省下的那点开销
   * 不值得让两条链在"什么时候写"上分叉。
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateConsumablePowders(delta) {
    if (!this.consumablePowders.length) return
    const snapshot = this.feed.materialStore.status().snapshot
    const seated = new Map(
      (snapshot?.payloadSeats || []).map((row) => [row.seat, row]),
    )
    const cellByKey = new Map(
      (snapshot?.cells || []).map((cell) => [`${cell.kind}:${cell.plate}:${cell.hole}`, cell]),
    )

    for (const entry of this.consumablePowders) {
      const row = seated.get(entry.seat)
      const cell = row && row.hole
        ? cellByKey.get(`${row.kind}:${row.plate}:${row.hole}`)
        : null
      const targetMm3 = cell ? Math.max(0, contentAmount(cell, entry.spec)) : 0
      const targetTint = cell && cell.eluted ? 1 : 0
      // 指数趋近, 与驻位液体同一条手感与同一个时间常数
      const k = 1 - Math.exp(-Math.max(0, delta) / STATION_LIQUID_RAMP_S)
      entry.mm3 += (targetMm3 - entry.mm3) * k
      if (Math.abs(targetMm3 - entry.mm3) < 1e-3) entry.mm3 = targetMm3
      entry.tint += (targetTint - entry.tint) * k
      if (Math.abs(targetTint - entry.tint) < 1e-3) entry.tint = targetTint
      if (entry.baseColor && entry.elutedColor && entry.material.color) {
        entry.material.color.copy(entry.baseColor).lerp(entry.elutedColor, clamp(entry.tint, 0, 1))
      }

      const level = clamp(levelFromMm3(entry.spec.cavity, entry.mm3, entry.exaggeration), 0, 1)
      if (entry.lastLevel === undefined || Math.abs(level - entry.lastLevel) > 1e-3) {
        entry.lastLevel = level
        this._moved = true
      }
      applyPowderColumn(entry, entry.mesh, entry.spec.chamber, level)
    }
  }

  /**
   * 功能: 解析三台注射泵的可动柱塞组与筒内液柱.
   *
   * ⚠ 深度排序的结论与展缸**完全一致, 直接复用**: 液柱材质绝不能改成 transparent.
   * 这里是同一个拓扑 —— 玻璃针筒走 MAT_GLASS(transmission 0.92 / alpha 0.28, 经
   * GLTFLoader 拿到 depthWrite=false)罩在液柱外面, 与 MAT_TANK 罩着 MAT_LIQUID 是同一
   * 件事. 液柱一旦也进透明队列, 两者只能按物体中心排序, 柱塞一走中心就变, 于是液体翻到
   * 玻璃前面 —— 表现为"液体一半糊在筒外面". 保持液柱不透明即可天然正确.
   *
   * 柱塞与液柱的写入方式**不同**, 别搞混:
   *   柱塞 = 平移(position). 记 basePosition 是**局部**坐标 —— 上样泵那台骑在 6X 轴的
   *          CARRIAGE 下, 父节点带着它走, 两层变换叠加, 记世界坐标会在轴一动就错.
   *   液柱 = 缩放(scale.y). 原点在筒底(blender_clean 里 anchor="base" 定的), 只缩一个
   *          分量就是"从底往上涨", 与展缸同一套约定.
   *
   * @param {Map<string, THREE.Object3D>} nodeIndex 节点索引
   * @returns {void}
   */
  _bindPumps(nodeIndex) {
    void nodeIndex
    for (const spec of this.manifest.pumpSyringe?.pumps || []) {
      // CAD 未建模的收集泵在此跳过: 数据仍走模型, 面板可见, 三维不动
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
      let mesh = liquidNode.isMesh ? liquidNode : null
      if (!mesh) liquidNode.traverse((child) => { if (!mesh && child.isMesh) mesh = child })
      if (!mesh) continue

      // 独占一份材质(将来按泵液种类改色不互相污染); 透明度/深度一律沿用 glTF 声明, 不覆写
      const material = mesh.material.clone()
      mesh.material = material

      const axis = Array.isArray(spec.travelAxis) ? spec.travelAxis : [0, 1, 0]
      const valveAxis = Array.isArray(spec.valveAxis) ? spec.valveAxis : [0, 0, -1]
      // 阀指针盘可以缺(收集泵没建, 或 03 报告里没这一项): 缺了就只是不转
      const valve = spec.valveNode ? this._resolve(spec.valveNode) : null
      if (spec.valveNode && !valve) this.missing.push(spec.valveNode)
      const leadAxis = Array.isArray(spec.leadAxis) ? spec.leadAxis : [0, 1, 0]
      const lead = spec.leadNode ? this._resolve(spec.leadNode) : null
      if (spec.leadNode && !lead) this.missing.push(spec.leadNode)
      this.pumps.push({
        spec,
        index: Number.isInteger(spec.index) ? spec.index : this.pumps.length,
        plunger,
        plungerBase: plunger.position.clone(),
        travel: new THREE.Vector3(axis[0], axis[1], axis[2])
          .normalize()
          .multiplyScalar(Number(spec.travelM) || 0),
        liquid: liquidNode,
        material,
        // 三个基准字段(含枢轴补偿量)成套发放, 与展缸同源 —— 见 liquidPivot.js
        ...captureLiquidBase(liquidNode),
        lastLevel: undefined,
        valve,
        valveAxis: new THREE.Vector3(valveAxis[0], valveAxis[1], valveAxis[2]).normalize(),
        valveBase: valve ? valve.quaternion.clone() : null,
        lastAngle: undefined,
        // 丝杆: 与阀指针同法(base × axisAngle), 只是轴是自身竖轴、角度直接跟 level 走
        lead,
        leadAxis: new THREE.Vector3(leadAxis[0], leadAxis[1], leadAxis[2]).normalize(),
        leadBase: lead ? lead.quaternion.clone() : null,
        lastLead: undefined,
      })
    }
  }

  /**
   * 功能: 解析已装配的运动轴节点, 记录其零位与运动方向.
   * @param {Map<string, THREE.Object3D>} nodeIndex 节点索引
   * @returns {void}
   */
  _bindAxes(nodeIndex) {
    void nodeIndex
    this.axes = [...this.machine.axes.values()].map((entry) => ({ axis: entry.spec }))
  }

  /** 解析 12 张货架托盘、两个中转托盘与两块正式 CAD 玻璃模板。 */
  _bindMaterials() {
    const inventory = this.manifest.inventory || {}
    const resolveItems = (spec) => (spec.items || []).map((path) => {
      const item = this._resolve(path)
      if (!item) this.missing.push(path)
      return item
    }).filter(Boolean)
    /**
     * 单件的绑定期基准姿态 + 倒置枢轴补偿(与 items 平行的数组; items 保持纯节点
     * 数组不动 —— MaterialPickController 与测试都按节点消费它)。
     * 枢轴补偿是硬前提: 粉桶 item 节点原点**不在**几何中心(实测组合体中心 y≈+0.037m),
     * 绕原点翻 180° 会沉进托盘七厘米。翻转走纯四元数合成, 位置加 baseQuat 旋转后的
     * shift = c − F·c —— 不做世界矩阵分解、不用负 scale, 量化 GLB 的 mesh 级 scale
     * 陷阱(见 MachineStateDriver 附注)因此不触发。
     */
    const resolvePoses = (items) => items.map((item) => {
      item.updateWorldMatrix(true, true)
      const box = new THREE.Box3().setFromObject(item)
      // 空 Group(测试夹具)兜底零向量: 翻转退化为绕原点, 不炸
      const center = box.isEmpty()
        ? new THREE.Vector3()
        : item.worldToLocal(box.getCenter(new THREE.Vector3()))
      return {
        baseQuat: item.quaternion.clone(),
        basePos: item.position.clone(),
        // F = 绕局部 X 轴转 π ⇒ F·c = (cx, −cy, −cz) ⇒ c − F·c = (0, 2cy, 2cz)
        flipShift: new THREE.Vector3(0, 2 * center.y, 2 * center.z),
      }
    })
    for (const spec of inventory.rack || []) {
      const node = this._resolve(spec.node)
      if (node) {
        const items = resolveItems(spec)
        node.visible = false
        items.forEach((item) => { item.visible = false })
        this.materialRack.push({ spec, node, items, itemPoses: resolvePoses(items) })
      }
      else this.missing.push(spec.node)
    }
    for (const spec of inventory.staging || []) {
      const node = this._resolve(spec.node)
      if (node) {
        const items = resolveItems(spec)
        node.visible = false
        items.forEach((item) => { item.visible = false })
        this.materialStaging.push({ spec, node, items, itemPoses: resolvePoses(items) })
      }
      else this.missing.push(spec.node)
    }
    for (const spec of inventory.magazines || []) {
      const template = this._resolve(spec.node)
      if (!template) {
        this.missing.push(spec.node)
        continue
      }
      template.visible = false
      this.materialMagazines.push({
        spec,
        template,
        parent: template.parent,
        basePosition: template.position.clone(),
        axis: new THREE.Vector3(...(spec.stackAxis || [0, 1, 0])).normalize(),
        spacing: Math.max(Number(spec.spacingM) || 0, 1e-5),
        clones: [],
        count: null,
      })
    }
  }

  /**
   * 功能: 收集构成机器外壳的材质(机架/外罩/大面板), 供透视效果使用.
   *
   * 判定依据是材质名而非节点名: 03 步已按"工位 × 材质"合并静态几何, 外壳部分
   * 恰好落在 MAT_COVER / MAT_EXTRUSION / MAT_STEEL_PLATE 这几种材质上, 且只取
   * ST_FRAME 之下的那份, 不会误伤工位内部同材质的零件.
   *
   * @returns {void}
   */
  _bindEnclosure() {
    const frameRoot = this.stationRoots.get('FRAME')
    if (!frameRoot) return

    // 必须给外壳网格换上克隆材质: 管线在 Blender 里是"按工位 × 材质"合并的, 但材质
    // 本身(MAT_STEEL_PLATE 等)在各工位之间是共享的同一个对象. 直接改共享材质的透明度,
    // 会把所有工位里用同种材质的零件一起变透明 —— 现象是整台机器都变成鬼影.
    const cloned = new Map()
    // 已被工艺灯独占克隆的网格(灯本体 + 受照节点)。补光灯上方那扇下相机盖板玻璃
    // (PTLC-08-010)正是挂在 ST_FRAME 下的, 与塔灯同一个坑: 这里再换一次材质,
    // 实时链写的亮度就会写进一份被丢弃的克隆, 画面永远是烘焙色。
    // 它也确实不是"外壳" —— 那是个功能窗口, 不该跟着透视淡化变鬼影。
    const ownedByLights = new Set(this.machine.ownedLightMeshes())
    frameRoot.traverse((child) => {
      if (!child.isMesh || !child.material) return
      // 三色塔灯挂在 ST_FRAME 下但不是外壳: 它已被 _bindSignalLight 独占克隆,
      // 这里再换材质会把实时灯色顶掉(症状: 数据全对而画面永远是烘焙色),
      // 且透视淡化会把状态灯一起变鬼影.
      if (this.signalLight && child === this.signalLight.mesh) return
      if (ownedByLights.has(child)) return
      // 记下外壳网格与它加载时的投影基线(玻璃罩等在加载遍历时已被设为不投影,
      // 透视恢复时要回到基线而不是一律 true)
      this.enclosureMeshes.push({ mesh: child, baseCast: child.castShadow })

      const swap = (material) => {
        let copy = cloned.get(material.uuid)
        if (!copy) {
          copy = material.clone()
          cloned.set(material.uuid, copy)
          this.enclosure.push({
            material: copy,
            baseOpacity: copy.opacity ?? 1,
            baseTransparent: copy.transparent === true,
          })
        }
        return copy
      }

      child.material = Array.isArray(child.material)
        ? child.material.map(swap)
        : swap(child.material)
    })
  }

  /**
   * 功能: 设置外壳透视程度(选中工位时调用).
   * @param {boolean} transparent 是否透视
   * @returns {void}
   */
  setEnclosureTransparent(transparent) {
    this.enclosureTarget = transparent ? 0.12 : 1
  }

  /**
   * 功能: 每帧更新 —— 由 SceneManager 的帧回调驱动.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  update(delta) {
    this.elapsed += delta
    this.feed.decayActivity(delta)

    this._updateStatusLights(delta)
    this._updateSignalLight(delta)
    this._updateProcessLights(delta)
    this._updateTanks(delta)
    this._updateStationLiquids(delta)
    this._updatePumps(delta)
    this._updateAxes(delta)
    this._updateRobot()
    this._updateMechanisms(delta)
    // 主轴相位: 与轴/机构不同, 它按 dt 累加而不是按目标值收敛(转角是无限增长量)
    if (this.machine.updateSpindles(delta)) this._moved = true
    this._updateMaterials()
    // ⚠ 粉柱必须排在 _updateMechanisms / _updateAxes **之后**(与离线链 ClipPlayer 把
    // updatePowders 放在 _applyContinuous 最后一行同一个理由): 粉的落点是当帧世界姿态的
    // 派生量, 翻料缸 ps_rotate 的角度就是 _updateMechanisms 这一帧刚写进去的 ——
    // 排在它前面等于拿上一帧姿态算这一帧, 倒粉时粉会贴着桶壁慢一拍。
    this._updateConsumablePowders(delta)
    this._updateEnclosure(delta)
  }

  /**
   * 功能: 取走"本帧动过几何"的标记(读后即清). SceneManager 用它决定要不要重渲
   *       阴影贴图 —— 状态灯只改材质颜色不动几何, 不参与该标记.
   * @returns {boolean} 本帧是否有几何变化
   */
  /**
   * 功能: 把全部插值通道标回"未初始化", 使**下一次**写入直接就位而不是缓动.
   *
   * 为什么跳转后必须这么做: interp.write 只在首帧直接就位(`!channel.initialized`),
   * 之后一律按 period 缓动, 而清场路径从来没解除过 initialized。于是每次 seek 之后,
   * 姿态要花 ~1.25 s 才收敛到播种值 —— 单击一次时读作"平滑落位"还挺好看, 拖动擦洗时
   * 就是画面永远追不上手指, 且越拖越滞后。
   *
   * 只清标志不改值: 值由紧随其后的关键帧种子写入, 这里提前动它反而会闪一下。
   *
   * @returns {void}
   */
  snapInterp() {
    for (const channel of this._mechanismChannels.values()) channel.initialized = false
    // 液位与泵柱塞的通道挂在 feed 上(不是 machine): 它们是数据侧模型, 由绑定层读取
    for (const channel of this.feed?.tankLiquid?.volumes || []) channel.initialized = false
    for (const channel of this.feed?.pumpSyringe?.plungers || []) channel.initialized = false
    for (const channel of this.feed?.pumpSyringe?.valves || []) channel.initialized = false
    for (const channel of this.feed?.joints || []) channel.initialized = false
  }

  consumeMoved() {
    const moved = this._moved
    this._moved = false
    return moved
  }

  /**
   * 功能: 取走"辉光选集需要重放"的标记(读后即清). 塔灯首次被实时数据接管时
   *       置位一次, SceneManager 用它把灯罩补进 Selective Bloom 的选集.
   * @returns {boolean} 是否需要重放辉光选集
   */
  consumeBloomDirty() {
    const dirty = this._bloomDirty
    this._bloomDirty = false
    return dirty
  }

  /**
   * 功能: 平滑过渡外壳透明度.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateEnclosure(delta) {
    if (!this.enclosure.length) return
    const diff = this.enclosureTarget - this.enclosureOpacity
    if (Math.abs(diff) < 0.002) {
      if (this.enclosureOpacity !== this.enclosureTarget) this.enclosureOpacity = this.enclosureTarget
      else return
    } else {
      // 约 0.35 秒完成过渡, 与帧率无关
      this.enclosureOpacity += diff * (1 - Math.exp(-delta / 0.12))
    }

    for (const entry of this.enclosure) {
      const opacity = entry.baseOpacity * this.enclosureOpacity
      entry.material.opacity = opacity
      entry.material.transparent = entry.baseTransparent || opacity < 0.999
      // 半透明时关掉深度写入, 否则外壳会挡住它后面的内部机构
      entry.material.depthWrite = opacity > 0.9
    }

    // 外壳淡化过半后不再投影: 演示视图里"透明壳投一片实影"非常出戏.
    // 只在跨越阈值那一刻切 castShadow 并标脏一次, 过渡动画本身不逐帧重渲阴影.
    const casting = this.enclosureOpacity > 0.5
    if (casting !== this._enclosureCasting) {
      this._enclosureCasting = casting
      for (const entry of this.enclosureMeshes) {
        entry.mesh.castShadow = casting && entry.baseCast
      }
      this._moved = true
    }
  }

  /**
   * 功能: 按健康度更新状态灯的颜色与亮度.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateStatusLights(delta) {
    const styles = this.manifest.healthStyles || {}
    for (const entry of this.statusLights) {
      const health = this.feed.healthOf(entry.station)
      const style = styles[health] || styles.unknown || { color: '#7b8aa5', intensity: 1 }

      let intensity = style.intensity ?? 1
      // 呼吸/频闪: pulse 为每秒的振荡次数, 0 表示常亮
      if (style.pulse > 0) {
        const wave = 0.5 + 0.5 * Math.sin(this.elapsed * Math.PI * 2 * style.pulse)
        intensity *= 0.45 + 0.55 * wave
      }
      // 该工位刚有步骤开始时短暂增亮, 让"正在动的地方"一眼可见
      const activity = this.feed.activity[entry.station.id] || 0
      if (activity > 0) intensity *= 1 + activity * 1.8

      TMP_COLOR.set(style.color)
      entry.material.color.copy(TMP_COLOR)
      if (entry.material.emissive) {
        entry.material.emissive.copy(TMP_COLOR)
        entry.material.emissiveIntensity = intensity
      }
    }
  }

  /**
   * 功能: 把上位机 signal_light 事件(MODE_State 推导)映射到塔灯灯罩的自发光.
   * 整罩单色, 红>黄>绿; sample.flash 为真时(如故障红闪)按 1Hz 做强度呼吸,
   * 频率对齐 PLC FB_Mode 的 tFlashTimer(T#500MS 翻转 = 1Hz 周期).
   *
   * 与 _updateStatusLights 的刻意差异: 只写 emissive/emissiveIntensity, 不动
   * base color —— 烘焙的浅色灯罩 albedo 保留, 全灭(off)就是"断电灯罩"的物理观感;
   * 绿态与烘焙同配方(#35d17a×2.5; GLB 内被 glTF 导出归一化为 ~43ff96×2.05,
   * 接管瞬间仅轻微亮度差, 观感连续).
   * 从未收到 signal_light 帧(实时页首帧前)时不接管, 烘焙观感原样.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateSignalLight(delta) {
    const entry = this.signalLight
    if (!entry) return
    const sample = this.feed.sampleSignalLight?.()
    if (!sample?.received) return

    if (!entry.takenOver) {
      entry.takenOver = true
      // 灯罩此刻才进入辉光选集: 提前登记会让脱机页的烘焙灯凭空多出光晕
      this._bloomDirty = true
    }

    const key = sample.stale ? 'stale' : sample.active
    const style = entry.spec.styles?.[key]
      || entry.spec.styles?.stale
      || { color: '#5a6472', intensity: 0.3 }
    // 断流态不闪(灰色常亮更像"未知"), 只有新鲜的闪烁态才做呼吸
    const pulse = (!sample.stale && sample.flash) ? 1.0 : (style.pulse || 0)
    // 短路键必须含闪烁维度: 故障红闪→急停红常亮 同为 'red', 只比颜色键会把
    // 稳态写入跳过, 强度冻结在闪烁波形中段(实测 3.12)——E2E 抓过一次
    const stateKey = pulse > 0 ? `${key}#flash` : key
    // 灯态未变且不闪烁时跳过材质写入; 闪烁需要逐帧改亮度, 不能跳
    if (stateKey === entry.lastKey && !(pulse > 0)) return
    entry.lastKey = stateKey

    let intensity = style.intensity ?? 1
    if (pulse > 0) {
      const wave = 0.5 + 0.5 * Math.sin(this.elapsed * Math.PI * 2 * pulse)
      intensity *= 0.45 + 0.55 * wave
    }
    if (entry.material.emissive) {
      entry.material.emissive.set(style.color)
      entry.material.emissiveIntensity = intensity
    }
  }

  /**
   * 功能: 把工艺灯的真机 DO 状态(process_light)渲染成灯亮度 —— 目前只有视觉纠偏补光(DO7).
   *
   * 为什么要在这里做斜坡而不是直接写 0/1: 真机补光是 1s 量级的稳态过程(开 DO7 → 等
   * light_settle_ms → 拍 → 关), 硬切既不像也看不清 —— 与离线片段
   * `clip_compiler.emit_vision_capture` 同源的理由。上升/下降时长也照抄那份片段
   * (0.25s / 0.35s), 两条链观感一致。
   *
   * 亮度的**可见形态**由 manifest.lights[].illuminatesNodes 承担(灯本体埋在盖板玻璃下
   * 37mm 看不见, 亮的是它上方那扇窗) —— 那是 MachineStateDriver.setLight 的事, 这里
   * 只管把 0..1 交给它。
   *
   * 从未收到过 process_light 帧时**不接管**, 保持管线烘焙的静态观感, 与
   * _updateSignalLight "首帧前不接管" 同一条约定。断流不做处理: 后端是"变化即发、
   * 无心跳", 没有心跳就没有可信的断流判据(见 TwinFeed.processLights 的注释)。
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateProcessLights(delta) {
    const samples = this.feed.sampleProcessLights?.()
    if (!samples) return
    for (const [id, on] of Object.entries(samples)) {
      const entry = this.machine.lights.get(id)
      if (!entry) continue
      const target = on ? 1 : Number(entry.spec.defaultLevel ?? 0)
      const current = Number.isFinite(entry.value) ? entry.value : target
      if (Math.abs(current - target) < 1e-3) {
        if (current !== target) this.machine.setLight(id, target)
        continue
      }
      const rate = delta / (target > current ? LIGHT_RISE_S : LIGHT_FALL_S)
      const next = target > current
        ? Math.min(target, current + rate)
        : Math.max(target, current - rate)
      if (!this.machine.setLight(id, next)) continue
      // 只在"哪几盏亮着"这个集合真的变了时才重设辉光选集(阈值与 bloomLights 的
      // `value > 0.01` 同一个) —— 斜坡中途每帧都置位等于每帧重建一次 Selection,
      // 纯白费; 离线链 useMotionStack 用 uuid key 做的也是同一件事。
      if ((current > BLOOM_LIT_EPS) !== (next > BLOOM_LIT_EPS)) this._bloomDirty = true
    }
  }

  /**
   * 功能: 更新 8 个展缸溶液槽里的液面高度与颜色.
   *
   * 液位来自 TankLiquidModel(动作包络 + Tank_State 双源合成的体积), 颜色仍按
   * Tank_State 取相位色 —— 前者表达"有多少液", 后者表达"这缸在干什么".
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updateTanks(delta) {
    const styles = this.manifest.tankStateStyles || {}
    const liquid = this.feed.tankLiquid
    if (!liquid) return
    liquid.step(delta)

    for (const entry of this.tanks) {
      const index = entry.tank.index ?? 0
      const level = clamp(liquid.level(index), 0, 1)
      if (entry.lastLevel === undefined || Math.abs(level - entry.lastLevel) > 1e-3) {
        entry.lastLevel = level
        this._moved = true
      }
      // 缩放 y + 枢轴补偿, 合起来才是"从底往上涨"(出厂 GLB 的枢轴在几何中心,
      // 见 liquidPivot.js —— 8 个展缸液面与三台泵液柱同病同治)
      applyLiquidLevel(entry, entry.mesh, level)
      // 空缸整体隐藏(压扁的盒子仍有一张满尺寸顶面); 经仲裁写, 不与 ViewTools 抢
      applyLiquidVisible(entry.mesh, level)

      const state = String(this.feed.tankStates[index] ?? 0)
      const style = styles[state] || styles.default
      if (style?.color) {
        TMP_COLOR.set(style.color)
        entry.material.color.copy(TMP_COLOR)
      }
    }
  }

  /**
   * 功能: 把三台注射泵的柱塞平移到位、把筒内液柱缩放到位.
   *
   * 两个自由度其实是一个: level 既是柱塞行程比例, 也是液柱长度比例(阀头在下, 柱塞上行
   * 即吸液). 所以只取**一次** level, 一次决定两处写入 —— 任何让它们分开取值的写法都会
   * 在某帧对不上, 表现为"柱塞和液面之间脱开一条缝".
   *
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  _updatePumps(delta) {
    const model = this.feed.pumpSyringe
    if (!model) return
    // 无论有没有几何都要推进: 面板/HUD 的 mL 读数靠它, 收集泵就是这种只有数据的情况
    model.step(delta)

    for (const entry of this.pumps) {
      const level = clamp(model.level(entry.index), 0, 1)
      if (entry.lastLevel === undefined || Math.abs(level - entry.lastLevel) > 1e-3) {
        entry.lastLevel = level
        this._moved = true
      }
      // 柱塞: 平移. travel 已含方向与总行程(米), 乘 level 即当前位移
      entry.plunger.position.copy(entry.plungerBase).addScaledVector(entry.travel, level)
      // 液柱: 缩放 + 枢轴补偿, 合起来才是"从筒底往上涨"(见 liquidPivot.js 的说明)
      applyLiquidLevel(entry, entry.liquid, level)
      applyLiquidVisible(entry.liquid, level)

      // ③ 丝杆: 绕自身竖轴转, 满行程 10 圈. 与柱塞是**刚性传动**, 所以角度直接跟 level
      //    走、不另设通道 —— 光杆芯留在静态组里, 转的是螺纹那一层(光面圆柱绕自身轴转
      //    在画面上完全看不出来).
      if (entry.lead) {
        const lead = model.leadAngle(entry.index)
        if (entry.lastLead === undefined || Math.abs(lead - entry.lastLead) > 1e-4) {
          entry.lastLead = lead
          this._moved = true
        }
        TMP_QUAT.setFromAxisAngle(entry.leadAxis, lead)
        entry.lead.quaternion.copy(entry.leadBase).multiply(TMP_QUAT)
      }

      // ④ 阀指针盘: 绕进深轴旋转到当前口. 与柱塞/液柱是**独立自由度**(切液路与推液是
      //    两件事), 所以单独取一次角度, 不能挂在 level 上.
      if (!entry.valve) continue
      const angle = model.valveAngle(entry.index)
      if (entry.lastAngle === undefined || Math.abs(angle - entry.lastAngle) > 1e-4) {
        entry.lastAngle = angle
        this._moved = true
      }
      TMP_QUAT.setFromAxisAngle(entry.valveAxis, angle)
      entry.valve.quaternion.copy(entry.valveBase).multiply(TMP_QUAT)
    }
  }

  /**
   * 功能: 按实际位置把各轴的 CARRIAGE 节点平移到位.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  /**
   * 功能: 挂起/恢复某条轴的实时覆写 —— 标定"接管"的唯一改动点.
   *
   * live 下 feed 每帧覆写轴位置, 用户不可能拖动虚拟模型去对齐实机; 接管把该轴
   * 从每帧覆写里摘出来(数据仍在收, HUD 照常), 释放后下一帧有数据即自动复位.
   * @param {string} id 轴 id
   * @param {boolean} on 是否挂起
   * @returns {void}
   */
  setAxisHold(id, on) {
    if (!this._heldAxes) this._heldAxes = new Set()
    if (on) this._heldAxes.add(id)
    else this._heldAxes.delete(id)
  }

  /**
   * 功能: 挂起/恢复机器人位姿的实时覆写(标定页播放模拟片段时用).
   * @param {boolean} on 是否挂起
   * @returns {void}
   */
  setRobotHold(on) {
    this._holdRobot = Boolean(on)
  }

  /**
   * 功能: 清除全部接管(路由离开/组件卸载的兜底).
   * @returns {void}
   */
  clearHolds() {
    this._heldAxes?.clear()
    this._holdRobot = false
  }

  _updateAxes(delta) {
    void delta
    const sample = this.feed.sampleAxisPose()
    for (const entry of this.axes) {
      const { axis } = entry
      if (this._heldAxes?.has(axis.id)) continue
      const rawPosition = sample.positions[axis.id]
      if (!Number.isFinite(rawPosition)) continue

      const [minMm, maxMm] = axis.rangeMm || [0, 0]
      const positionMm = clamp(rawPosition, minMm, maxMm)
      if (this.machine.setAxisMm(axis.id, positionMm)) this._moved = true
    }
  }

  /** Studio 与实时孪生共用 RobotJointDriver；断流时 sample 保留末帧。 */
  _updateRobot() {
    if (this._holdRobot) return
    const pose = this.feed.sampleRobotPose()
    if (!pose.joint) return
    this.machine.setJointsDeg(pose.joint, { continuous: true })

    const last = this._lastJoints
    let changed = !last || last.length !== pose.joint.length
    if (!changed) {
      for (let i = 0; i < pose.joint.length; i += 1) {
        if (Math.abs((pose.joint[i] ?? 0) - (last[i] ?? 0)) > 1e-3) {
          changed = true
          break
        }
      }
    }
    if (changed) {
      this._lastJoints = Array.from(pose.joint)
      this._moved = true
    }

    if (Number.isFinite(Number(pose.tool))) {
      const toolResult = this.machine.syncMountedTool(Number(pose.tool), {
        forceSnap: pose.resynced,
      })
      if (toolResult.changed) this._moved = true
    }
  }

  /**
   * 将机构反馈写到已具备正式 CAD 绑定的执行器；未装配项保持数据可见但不猜几何。
   *
   * 信号 → 行程缓动: 复用 interp 通道做与帧率无关的指数追赶, 但周期不走采样
   * 自适应(10 Hz 心跳会把周期压到 0.1s), 而是每帧按 spec.transitionS 覆写 ——
   * 语义为"到位约 95% 的时间"(τ = transitionS/3)。首见直跳(页面加载不播历史动画),
   * 断流重连直跳末态(与机器人 forceSnap 同语义, 不沿一条不存在的路径补间)。
   *
   * 夹爪是三态: 0=张开(GLB 基准位) / spec.holdValue=夹持物料(部分闭合, 持料位由
   * TwinFeed 的流程事件包络给出) / 1=空爪紧闭。holdValue 缺失时回退满闭合并告警
   * 一次 —— interp 的 push 会静默吞非有限值, 决不能把 NaN 送进通道。
   *
   * `moving: true` 的机构(当前只有吸盘翻转)走**另一条曲线**: 匀速推进 + 在途保持段。
   * 发令即起步、按上位机实测的真实行程速度匀速铺开、保持在终点前 MECHANISM_APPROACH_GAP
   * 处, 到位信号到了才合上最后一段。这样画面与实物同起同止, 不必知道行程要走多久;
   * 气缸是恒速撞硬限位, 指数缓动对它是错的曲线 —— 详见那段的注释。
   * @param {number} delta 帧间隔(秒)
   */
  _updateMechanisms(delta) {
    const states = this.feed.sampleMechanismStates()
    for (const [id, state] of Object.entries(states)) {
      if (typeof state.effective !== 'boolean') continue
      const isActuator = this.machine.actuators.has(id)
      const isLinkage = !isActuator && this.machine.linkages.has(id)
      if (!isActuator && !isLinkage) {
        // manifest 判了 rigged 却没绑上几何 = 声明与绑定脱节, 必须可见(只吵一次)
        if (this._riggedMechanismIds.has(id) && !this._warnedMechanisms.has(id)) {
          this._warnedMechanisms.add(id)
          console.warn(`[twin] 机构 ${id} 已标记 rigged, 但没有对应的 actuator/linkage 绑定`)
        }
        continue
      }
      const spec = isActuator
        ? this.machine.actuators.get(id).spec
        : this.machine.linkages.get(id).spec
      let target = state.effective ? 1 : 0
      if (target === 1 && state.holding === true) {
        // holdValue 是载荷无关的兜底层(布尔 holding 拿不到载荷身份); 精编译片段的取件
        // 闭合已逐件化(clip_compiler._close_value_for) —— 实时链停在兜底层是有意的
        const holdValue = Number(spec?.holdValue)
        if (Number.isFinite(holdValue)) {
          target = holdValue
        } else if (!this._warnedHoldValue.has(id)) {
          this._warnedHoldValue.add(id)
          console.warn(`[twin] 机构 ${id} 报告持料但 spec 缺 holdValue, 回退满闭合`)
        }
      }
      // 在途保持: 后端报 moving 时先停在离终点 MECHANISM_APPROACH_GAP 的地方, 收到
      // moving:false 再走完最后一段。为什么不能只按固定时长播: 吸盘翻转的实际行程
      // 0.6~10.8s 不定(app.yaml 的 rotary 是 di_or_dwell, 等 DI 上限 tool_di_timeout=10s)。
      // 保持短 + 到位放行是唯一与行程快慢无关的做法。缺省(没有 moving 键)= 已就位。
      const inflight = state.moving === true
      const range = Array.isArray(spec?.inputRange) && spec.inputRange.length === 2
        ? spec.inputRange.map(Number)
        : [0, 1]
      // 按 inputRange 两端算保持点而不是写死 1-gap: 不假设机构值域是 [0,1]
      const other = Math.abs(target - range[1]) < Math.abs(target - range[0]) ? range[0] : range[1]
      const endpoint = target
      if (inflight && Number.isFinite(other)) {
        target += (other - target) * MECHANISM_APPROACH_GAP
      }

      let channel = this._mechanismChannels.get(id)
      if (!channel) {
        // 首见分两种, 不能一律直跳:
        //   · 静态首见(没有 moving) = 页面加载/重连时的既有姿态 -> 直跳, 不补播历史动画;
        //   · 首见就在途(moving:true) = 这一程正从对面端出发, 我们恰好从它起步那一刻
        //     开始看 -> 必须**从对面端起步**再走过去。
        // 否则 push() 的首见直跳会把**整段行程**吃掉, 表现为"瞬移到位"。
        // 实际最常咬到的就是上翻: 这只缸在收到第一条命令之前根本不在 mechanism_state
        // 里(mechanism_snapshot 只发缓存里已有的条目), 而开机后第一条命令通常正是
        // rotary-up(CAD 基准态是下翻位) —— 于是表现成"上翻瞬移、下翻正常"的方向性错觉。
        const seed = (inflight && Number.isFinite(other)) ? other : target
        channel = createChannel(seed)
        push(channel, seed)          // 先把 initialized 立起来并把 value 钉在起点
        this._mechanismChannels.set(id, channel)
        if (channel.target !== target) push(channel, target)  // 此时已 initialized, 不再直跳
      } else if (channel.target !== target) {
        push(channel, target)
      }
      const transitionS = Number(spec?.transitionS) > 0 ? Number(spec.transitionS) : 0.3
      channel.period = transitionS / (3 * ARRIVE_FACTOR)
      if (state.resynced) channel.value = channel.target

      // 公告过在途的机构(当前只有吸盘翻转)走**匀速**推进, 而不是指数追赶。
      //
      // 为什么指数曲线在这里是错的: 那条曲线的形状是"越接近终点越慢", 描述的是一阶惯性
      // 系统; 而气缸是通气后近似恒速推进、直到**撞上硬限位**才停 —— 两头都不像。叠上
      // 保持点后更糟: τ=transitionS/3 的换算让它在 0.6s 内就扫掉 180° 中的 153°, 然后
      // 冻住干等 DI。用户看到的"第一下翻转太快、跟实物对不上"就是这一段。
      //
      // 配速优先级: state.expectedS(上位机量的**上一程真实耗时**, 自校准)
      //           → spec.transitionS(rig_map 标称) → 兜底常量。
      // 速度按**整个行程全长**算而不是按剩余距离, 所以保持段与收尾段是同一个速度,
      // 放行瞬间不会出现速度断点。
      //
      // 收尾(moving 已转 false, 实物到位了)按 MECHANISM_CLOSING_BOOST 略微加速: 此时
      // 画面还差最后一段, 用头段速度慢慢补就会整体滞后于实物。
      // DI 早到 -> 余程加速补齐, 追得上; DI 晚到 -> 停在保持点等, 不空走。两者都不需要
      // 事先知道这一程要走多久, 这正是"保持 + 放行"设计原本的好处, 这里只换了曲线。
      let value
      if (this._inflightMechanisms.has(id) || inflight) {
        const span = Math.abs(range[1] - range[0]) || 1
        // expectedS 是**上位机量出来的**, 前端必须自己兜住下限: 一个假的小样本会让
        // speed 大到一帧走完全程, 于是"匀速"退化成瞬移 —— 2026-08-05 上翻瞬移就是
        // 一个 ~0.01s 的假样本造成的。后端已在两处挡(驱动不记"没真走"的程、控制器
        // 有 0.2s 下限), 这里是最后一道: 就算将来又冒出一个坏值, 画面最多是偏快,
        // 不会再瞬移。取标称值的一半为底 —— 实物再快也不会快过标称的一半。
        const nominalS = Number(spec?.transitionS) > 0
          ? Number(spec.transitionS)
          : MECHANISM_FALLBACK_STROKE_S
        const measuredS = Number(state.expectedS) > 0 ? Number(state.expectedS) : 0
        const strokeS = measuredS > 0 ? Math.max(measuredS, nominalS * 0.5) : nominalS
        const speed = (span / strokeS) * (inflight ? 1 : MECHANISM_CLOSING_BOOST)
        const diff = channel.target - channel.value
        const stepMax = speed * delta
        channel.value += Math.abs(diff) <= stepMax ? diff : Math.sign(diff) * stepMax
        if (Math.abs(channel.target - channel.value) < 1e-6) channel.value = channel.target
        value = channel.value
        // 收尾走完(已贴住真终点)才退出匀速路径, 否则 moving 一转 false 就会掉回指数曲线,
        // 最后那一小段又变回"啪"地弹过去。
        if (inflight) this._inflightMechanisms.add(id)
        else if (Math.abs(channel.value - endpoint) < 1e-6) this._inflightMechanisms.delete(id)
      } else {
        value = step(channel, delta)
      }

      const moved = isActuator
        ? this.machine.setActuator(id, value)
        : this.machine.setLinkage(id, value)
      if (moved) this._moved = true
    }
  }

  /**
   * 功能: 告知本层哪些载荷节点此刻由 TrayBinding 接管显隐(在途中, 挂在机械臂上).
   *
   * 让位而不是"两边都写": 在途期间账本说这块板既不在货架也不在中转位, 本层照账本
   * 判必然判成隐藏, 与那边每帧互顶就是闪烁。范式照 delegateMagazines —— 谁画谁负责。
   *
   * @param {Set<string>} paths 由 TrayBinding 接管的节点路径集合
   * @returns {void}
   */
  setTransitOwned(paths) {
    this.transitOwned = paths instanceof Set ? paths : new Set(paths || [])
    // 让位集合变了要重算一遍显隐, 否则落位后那张托盘要等下一帧账本变化才被接管回来
    this._lastMaterialSnapshot = null
  }

  /**
   * 按物料账本更新实体：托盘的**位置**由 CAD 定死、由账本控显隐，在途期间则交给
   * TrayBinding 换父跟手；玻璃板从正式 CAD 模板克隆成实际张数。
   * 未验证的 12 路货架光电不覆盖账本；中转 A/B 已验证光电可用于标红，但几何仍按
   * 账本板号确定，避免传感器只能回答“有/无”时丢失具体托盘身份。
   */
  _updateMaterials() {
    const snapshot = this.feed.materialStore.status().snapshot
    if (!snapshot || snapshot === this._lastMaterialSnapshot) return
    this._lastMaterialSnapshot = snapshot

    const cellByKey = new Map(
      (snapshot.cells || []).map((cell) => [`${cell.kind}:${cell.plate}:${cell.hole}`, cell]),
    )
    // 件在别处(工位座上 / 爪上在途)的孔。USED 粉桶改为常显后必须显式排除它们:
    // _do_consume 在件离孔上工位那一刻就置 USED, 不查这个集合, 座上那只桶会同时
    // 画在托盘孔里 —— payload_seats 的语义是"有座位行 ⇒ 该孔画空"。
    const away = new Set()
    for (const row of snapshot.payloadSeats || []) {
      if (row.hole !== null && row.hole !== undefined) {
        away.add(`${row.kind}:${row.plate}:${row.hole}`)
      }
    }
    for (const row of Object.values(snapshot.transit || {})) {
      if (row.payload === 'item' && row.hole !== null && row.hole !== undefined) {
        away.add(`${row.kind}:${row.plate}:${row.hole}`)
      }
    }
    /**
     * 单件显示裁决: 粉桶(collector)三态 = FRESH 直立 / USED 倒扣在位 / ABSENT 不画
     * (用户定案 2026-08-15); 瓶类维持 visibleStates/带样品号 规则, 不倒置。
     * ABSENT 不用点名: 它不在 visibleStates 里, 走既有规则自然隐藏。
     */
    const itemState = (kind, plate, hole) => {
      const key = `${kind}:${plate}:${hole}`
      const cell = cellByKey.get(key)
      if (!cell || away.has(key)) return { visible: false, flipped: false }
      const flipped = kind === 'collector' && cell.state === 'USED'
      const visible = flipped
        || this.materialVisibleStates.has(cell.state)
        || (this.materialVisibleWhenSampleId && Boolean(cell.sample_id))
      return { visible, flipped }
    }
    /**
     * 姿态写入是**比较后写**的自愈式(不记"已翻过"标志): TrayBinding 落位补间把姿态
     * 还原成直立后, 下一次快照重算自动纠回。隐藏的 item 也照写(不渲染无成本),
     * 免得显形瞬间闪一帧直立。
     */
    const setItemPose = (item, pose, flipped) => {
      if (!pose) return
      const wantQuat = flipped ? pose.baseQuat.clone().multiply(FLIP_X) : pose.baseQuat
      const wantPos = flipped
        ? pose.basePos.clone().add(pose.flipShift.clone().applyQuaternion(pose.baseQuat))
        : pose.basePos
      if (!item.quaternion.equals(wantQuat) || !item.position.equals(wantPos)) {
        item.quaternion.copy(wantQuat)
        item.position.copy(wantPos)
        this._moved = true
      }
    }
    // 在途节点整棵让出: 托盘让出时它的 6 个耗材是子级, 一并由那边负责
    const owned = (spec, index = -1) => this.transitOwned.has(
      index < 0 ? spec.node : (spec.items || [])[index],
    ) || this.transitOwned.has(spec.node)
    const setVisible = (node, visible) => {
      if (node.visible === visible) return
      node.visible = visible
      this._moved = true
    }

    // 在架人工账 (kind:plate -> 行)。查无行 = 视为在架 —— 降级方向只许这么定,
    // 反过来的话回放老录像(事件里没有 rack 段)会 12 张托盘全消失。
    const ledger = new Map(
      (snapshot.rackLedger || []).map((row) => [`${row.kind}:${row.plate}`, row]),
    )
    for (const entry of this.materialRack) {
      const { kind, plate } = entry.spec
      const stagedArea = kind === 'collector' ? 'staging-a' : 'staging-b'
      const stagedPlate = snapshot.staging?.[stagedArea]?.plate
      if (!owned(entry.spec)) {
        const row = ledger.get(`${kind}:${plate}`)
        const ledgerPresent = row ? row.present : null
        // 账本记无板(人工标注/被搬走/在爪上都记 0) -> 托盘连同 6 个子级单件整棵隐藏;
        // staged 判据保留为账缺段时的降级双保险, 与 ledger 永不矛盾(搬走时后端本就置 0)
        setVisible(entry.node, ledgerPresent !== false && Number(stagedPlate) !== Number(plate))
      }
      entry.items.forEach((item, index) => {
        if (owned(entry.spec, index)) return
        const state = itemState(kind, plate, index + 1)
        setVisible(item, state.visible)
        setItemPose(item, entry.itemPoses[index], state.flipped)
      })
    }

    for (const entry of this.materialStaging) {
      const row = snapshot.staging?.[entry.spec.area]
      const visible = row?.plate !== null && row?.plate !== undefined
      if (!owned(entry.spec)) setVisible(entry.node, visible)
      entry.items.forEach((item, index) => {
        if (owned(entry.spec, index)) return
        const state = itemState(entry.spec.kind, row?.plate, index + 1)
        setVisible(item, visible && state.visible)
        setItemPose(item, entry.itemPoses[index], state.flipped)
      })
    }

      const magazineById = Object.fromEntries(
        (snapshot.magazines || []).map((item) => [item.magazine, item]),
      )
      this.magazineCounts = magazineById
      // 板层接管后本路径停手: 两边同时画会出现双份板堆(见 delegateMagazines)
      if (this.magazinesDelegated) return
      for (const entry of this.materialMagazines) {
        const magazine = magazineById[entry.spec.id]
        this._setMagazineCount(entry, magazine?.count ?? 0, magazine?.capacity)
      }
    }

    /**
     * 功能: 把料仓堆叠的绘制权交给薄层板层(PlateFaceLayer 的 InstancedMesh).
     *
     * 本类原有的实现是逐张 `template.clone(true)` —— 满仓 30 张 × 2 仓 = 60 个绘制调用,
     * 换成分层板后还会翻倍。板层用每仓每层一个 InstancedMesh 只要 4 个, 且那边的板是
     * 真正的"2mm 玻璃 + 硅胶"分层件、硅胶朝下, 与真机一致。
     * 接管时把本类已经克隆出来的堆叠收起来, 避免残留。
     *
     * @param {boolean} delegated 是否交出绘制权
     * @returns {void}
     */
    delegateMagazines(delegated = true) {
      this.magazinesDelegated = Boolean(delegated)
      if (!this.magazinesDelegated) return
      for (const entry of this.materialMagazines) {
        entry.template.visible = false
        for (const clone of entry.clones) clone.visible = false
        entry.count = null
      }
      this._moved = true
    }

    /** 最近一帧各料仓的张数(供板层取用, 免得再解析一次 material_state)。 */
    magazineSnapshot() {
      return this.magazineCounts || {}
    }

    _setMagazineCount(entry, rawCount, rawCapacity) {
      const capacity = Math.max(0, Math.floor(Number(rawCapacity) || 0))
      const count = Math.max(0, Math.min(capacity, Math.floor(Number(rawCount) || 0)))
    if (entry.count === count) return
    entry.count = count
    entry.template.visible = count > 0
    const needed = Math.max(0, count - 1)
    while (entry.clones.length < needed) {
      const clone = entry.template.clone(true)
      clone.name = `${entry.template.name}_STACK_${entry.clones.length + 2}`
      entry.parent?.add(clone)
      entry.clones.push(clone)
    }
    const sign = Number(entry.spec.stackSign) < 0 ? -1 : 1
    for (let index = 0; index < entry.clones.length; index += 1) {
      const clone = entry.clones[index]
      clone.visible = index < needed
      clone.position.copy(entry.basePosition).addScaledVector(
        entry.axis,
        entry.spacing * (index + 1) * sign,
      )
    }
    this._moved = true
  }

  /**
   * 功能: 取某工位的根节点(供拾取高亮与相机飞行使用).
   * @param {string} stationId 工位 id
   * @returns {THREE.Object3D|undefined} 根节点
   */
  getStationRoot(stationId) {
    return this.stationRoots.get(stationId)
  }

  /**
   * 功能: 取所有状态灯网格(供后期辉光只作用于它们).
   * @returns {THREE.Object3D[]} 网格数组
   */
  getBloomTargets() {
    const targets = this.statusLights.map((entry) => entry.mesh)
    // 塔灯只在被实时数据接管后参与辉光, 脱机页保持烘焙观感不新增光晕
    if (this.signalLight?.takenOver) targets.push(this.signalLight.mesh)
    // 工艺灯(补光/紫外面光源)与它们的受照节点; bloomLights 自己滤掉灭着的
    targets.push(...this.machine.bloomLights())
    return targets
  }

  /**
   * 功能: 释放本层克隆出来的材质.
   * @returns {void}
   */
  dispose() {
    for (const entry of this.statusLights) entry.material.dispose()
    this.signalLight?.material.dispose()
    this.signalLight = null
    for (const entry of this.tanks) entry.material.dispose()
    // 驻位液体也是逐处克隆的材质, 漏了它每次重建 rig 就泄一份
    for (const entry of this.stationLiquids) entry.material.dispose()
    // 粉柱材质是 _bindConsumablePowders 克隆的(tint 要写色), 克隆一次就有一份释放义务
    for (const entry of this.consumablePowders) entry.material.dispose()
    for (const entry of this.enclosure) entry.material.dispose()
    this.statusLights.length = 0
    this.tanks.length = 0
    this.stationLiquids.length = 0
    this.consumablePowders.length = 0
    this.axes.length = 0
    this.enclosure.length = 0
    this.enclosureMeshes.length = 0
    for (const entry of this.materialMagazines) {
      for (const clone of entry.clones) clone.parent?.remove(clone)
      entry.clones.length = 0
    }
    this.materialRack.length = 0
    this.materialStaging.length = 0
    this.materialMagazines.length = 0
    this._offSpindleNodes?.()
    this._offSpindleNodes = null
    this.machine.dispose()
    this.stationRoots.clear()
  }
}
