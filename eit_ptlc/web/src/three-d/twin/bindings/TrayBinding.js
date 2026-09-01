/**
 * 功能: 把"托盘/单件此刻在哪把夹爪上"接到"它画在哪" —— 换父吸附与落位补间.
 *
 * 与薄层板 (PlateBinding) 的分工:
 *   薄层板走 1 号吸盘刀, 位置权威在调度器 samples.position (experiments.db);
 *   本模块走 2 号大夹爪 (整板) 与 3 号小夹爪 (单件), 位置权威在物料账本
 *   material_state.transit —— 两条链路的账本各自独立, 谁也不代管谁。
 *
 * 只有 L1: 权威就是 material_state.transit, 三维不做任何推断
 * ------------------------------------------------------------------
 * 后端 material_feedback_loop 是 0.5 s 轮询 + 变更即发, 所以合爪到画面跟手最坏差半秒。
 * 刻意**不**做薄层板那套 L2 事件包络推断, 因为这半秒在观感上落不到实处:
 * 取放脚本在夹爪开合前后跑的是 near 段慢速逼近 (vel 5~10), 半秒里机械臂只走几毫米,
 * 而 L2 会引入第二套身份推断 —— 与 PTLC_REALTIME_PROTOCOL §5 "三维不维护第二套账本"
 * 的硬约定相悖, 代价远大于收益。若将来现场觉得跟手迟滞, 再补 L2 是个受控的增量改动。
 *
 * 吸附实现是**纯换父**: 托盘挂到 TOOL_MOUNT 之下, 于是机械臂一动、快换一转,
 * 托盘作为子级刚性跟随; 6 个耗材本就是托盘节点的子级, 免费跟着走。
 *
 * ⚠ 换父保世界位姿 = 如实反映标定残差。若工位水平偏移那 23~41 mm 仍在,
 *   托盘看起来会被"偏着夹住" —— 那是真的偏, 不是画错, 别去补一个假的偏置把它藏起来。
 */
import * as THREE from 'three'

import { reparentPreservingWorld } from '../../anim/MachineStateDriver.js'

/** 落位补间时长(秒)。放下的托盘要"坐正"回 CAD 位姿, 而不是留着换父时的残差。 */
const SETTLE_S = 0.25

/**
 * 走落位补间的最大行程(米)。与 MachineStateDriver 的 PAYLOAD_DOCK_MAX_TRAVEL_M 同款判据:
 * 松爪那一刻夹爪停在目的座上, 要吃掉的只是毫米级示教残差; 行程大就说明这次落位不在座位
 * 跟前(账本比动作晚时会这样), 硬走补间会让托盘横穿整台机器。
 */
const MAX_SETTLE_TRAVEL_M = 0.05

/** 整板的搬运器; 与上位机 material_store.CARRIER_PLATE96 逐字一致。 */
const CARRIER_PLATE96 = 'gripper_plate96'
/** 单件的搬运器; 与上位机 material_store.CARRIER_VIAL 逐字一致。 */
const CARRIER_VIAL = 'gripper_vial'

/**
 * L2 取料脚本表: 脚本名 -> 用它的入参解出"这次要夹哪件"。
 *
 * 为什么需要 L2: L1(material_state.transit)是在**脚本 DONE** 时才落账的, 而取料脚本以
 * `P7 → P1 → require_anchor(P1)` 收尾 —— 等账本到货, 机械臂已经拎着托盘退回 home 走了
 * 十几秒。只靠 L1, 这十几秒里爪子是空的(用户 2026-08-05 实测报的正是这个)。
 * L2 只把**时刻**提前到合爪那一帧, 身份仍与 L1 同源(同一套 kind/plate/hole 键),
 * 不构成第二套账本 —— L1 一到就以它为准。
 *
 * 与上位机 config/material_bindings.yaml 的 transit_pick 绑定一一对应, 改一边要改另一边。
 */
/** 两把爪的固定顺序, 逐爪仲裁时用。 */
const CARRIERS = Object.freeze([CARRIER_PLATE96, CARRIER_VIAL])

/**
 * L2 放料脚本表: 脚本名 -> 松的是哪把爪。
 *
 * 与 PICK_SCRIPTS 对称, 且与上位机 config/material_bindings.yaml 的 transit_place 绑定
 * 一一对应(robot_collector_return_put 在那边绑的是 fill, 但物理上同样是小爪松料, 要收)。
 * 用脚本名而不是 mountedTool 来定爪: 松爪那一刻工具号可能还没刷新, 而脚本名是事件自带的。
 */
const PUT_SCRIPTS = Object.freeze({
  robot_group_staging_put: CARRIER_PLATE96,
  robot_group_rack_put: CARRIER_PLATE96,
  robot_individual_put: CARRIER_VIAL,
  robot_collector_return_put: CARRIER_VIAL,
})

const PICK_SCRIPTS = Object.freeze({
  robot_group_rack_pick: {
    carrier: CARRIER_PLATE96,
    key: (args) => `rack.${String(args?.rack_id || '')}.${Number(args?.slot_id)}`,
  },
  // 中转取整板没有 slot_id 入参(板号在账本里), 键就是中转区本身
  robot_group_staging_pick: {
    carrier: CARRIER_PLATE96,
    key: (args, areaOf) => areaOf(String(args?.rack_id || '')),
  },
  robot_individual_pick: {
    carrier: CARRIER_VIAL,
    key: (args, areaOf) => `${areaOf(String(args?.rack_id || ''))}#${Number(args?.slot_id)}`,
  },
})

const _pos = new THREE.Vector3()
const _quat = new THREE.Quaternion()

/**
 * 记下节点的初始局部位姿, 作为落位时的还原凭证。
 * 用节点自己的 CAD 变换而不是另找一份 dock 数据: 每个 INV_* 节点本来就摆在设计位上,
 * 那份变换就是最权威的落点, 也免掉"第二份几何真源会漂移"的老问题。
 * @param {THREE.Object3D} node 载荷节点
 * @returns {{parent: THREE.Object3D, position: THREE.Vector3, quaternion: THREE.Quaternion}}
 */
function captureHome(node) {
  return {
    parent: node.parent,
    position: node.position.clone(),
    quaternion: node.quaternion.clone(),
  }
}

export class TrayBinding {
  /**
   * @param {object} opts
   * @param {object} opts.manifest device-manifest
   * @param {(path: string) => THREE.Object3D|undefined} opts.resolve 节点路径解析(与 TwinBindings 同款)
   * @param {object} opts.feed TwinFeed 实例(取 materialStore 快照)
   */
  constructor({ manifest, resolve, feed } = {}) {
    this.manifest = manifest || {}
    this.feed = feed
    /** @type {string[]} 解析不到的节点路径(如实上报, 不用近似节点顶替) */
    this.missing = []

    /**
     * @type {Map<string, {node: THREE.Object3D, home: object, kind: string, plate: number|null}>}
     * 载荷键 -> 场景对象。键的构造与 material_state 对齐:
     *   整板  `rack.<kind>.<plate>` / `staging-a` / `staging-b`
     *   单件  `<上述整板键>#<hole>`
     */
    this.payloads = new Map()
    /** @type {Map<string, object>} 载荷键 -> 落位补间 */
    this._tweens = new Map()
    /** @type {Map<string, string>} carrier -> 当前挂在它上面的载荷键 */
    this._carried = new Map()
    /** @type {Set<string>} 本层此刻接管了显隐的节点路径, 供 TwinBindings 让位 */
    this.owned = new Set()

    this.toolMount = null
    this._lastSnapshot = null
    this._ownedDirty = false
    /** @type {Set<string>} 已经就"缺夹持位姿"警告过的节点(每个只喊一次, 不刷屏) */
    this._warnedNoGrip = new Set()
    /** @type {Map<string, {key: string, carrier: string}>} run_id -> 本次取料的载荷身份 */
    this._pickCtx = new Map()
    /**
     * @type {Map<string, string|null>}
     * L2 认为每把爪此刻拿着什么(值为 null = 空手)。**只在 L2 领先于账本时有条目**:
     * L1 说的与它一致就删掉、把这把爪交还给 L1。
     *
     * 为什么必须记"空手"而不只是"拿着": 松爪之后账本还会有一小段时间说"在途"
     * (在途行要等放料脚本 DONE 才清), 不记空手的话 _applyTransit 会立刻把托盘再抓回爪上,
     * 表现成松爪后托盘"粘"住不放。2026-08-05 第一版把它写成 Set(只记"抢跑挂上"),
     * 于是 L1 一追上就再也放不了早 —— 现象正是"松爪后托盘还夹着, 整个动作跑完才闪回落点"。
     */
    this._l2 = new Map()

    this._bindPayloads(resolve)
    this._bindToolMount(resolve)
  }

  /** 解析 12 张货架托盘 + 2 个中转托盘, 以及它们各自的 6 个耗材件。 */
  _bindPayloads(resolve) {
    const inventory = this.manifest.inventory || {}
    // 夹持位姿按**载荷 id**(= INV_* 叶名)索引。必须逐节点取, 不能"每种耗材一个常量" ——
    // 14 个载荷节点里 13 个的局部系一致, 唯独 INV_STAGING_B 多转 90°(合成空节点的作者约定)。
    //
    // 排除 kind=item: 单件的 mountLocal 是 fit_item_grips 产出的**位置吸附**语义
    // (position=四销笼中心, quaternion 恒单位占位), 拿它当完整局部位姿钉上去会把瓶/桶
    // 绕安装轴摆成占位朝向。单件在实时链维持原"保世界换父"语义(片段链的磁吸在
    // MachineStateDriver.attach 里按同一条 kind 界线区分)。
    // 用排除法而不是"只收 tray": 缺省 kind 的旧条目/测试夹具一律按整板对待, 语义不变。
    const mountByPayload = new Map(
      (this.manifest.attachments || [])
        .filter((item) => item?.payload?.mountLocal && item.payload.kind !== 'item')
        .map((item) => [String(item.id), item.payload.mountLocal]),
    )
    const add = (key, path, kind, plate) => {
      const node = resolve?.(path)
      if (!node) {
        this.missing.push(path)
        return null
      }
      this.payloads.set(key, {
        node,
        path,
        home: captureHome(node),
        kind,
        plate,
        mountLocal: mountByPayload.get(String(path).split('/').pop()) || null,
      })
      return node
    }
    for (const spec of inventory.rack || []) {
      const key = `rack.${spec.kind}.${spec.plate}`
      if (!add(key, spec.node, spec.kind, Number(spec.plate))) continue
      ;(spec.items || []).forEach((path, index) => {
        add(`${key}#${index + 1}`, path, spec.kind, Number(spec.plate))
      })
    }
    for (const spec of inventory.staging || []) {
      // 中转位的板号是流动的(账本说了算), 建索引时记 null, 用时从快照现取
      if (!add(spec.area, spec.node, spec.kind, null)) continue
      ;(spec.items || []).forEach((path, index) => {
        add(`${spec.area}#${index + 1}`, path, spec.kind, null)
      })
    }
  }

  /** 解析快换安装座 —— 载荷挂它下面就自动跟着整条机械臂走。 */
  _bindToolMount(resolve) {
    const name = this.manifest.robot?.toolMount
    if (!name) return
    this.toolMount = resolve?.(name) || null
    if (!this.toolMount) this.missing.push(name)
  }

  // ── L2: 把挂载时刻提前到合爪那一帧 ──────────────────────────────────────

  /**
   * 功能: 消费一条**已配对好入参**的流程事件(由 TwinFeed.addNodeSink 投递)。
   *
   * 判据与 TwinFeed 的 gripHolding 同源 —— `*_pick` 脚本里完成的 `gripper-close` 即持料,
   * 任何 `gripper-open` 即释放。身份取自取料脚本的入参, 与 L1 用的是同一套键。
   *
   * ⚠ 只在 L1 尚未给出该 carrier 的在途行时才抢跑; L1 一到就以 L1 为准(见 _applyTransit)。
   * 认不出身份就**什么都不做** —— 宁可晚半拍由 L1 补上, 也不挂一件猜出来的载荷。
   *
   * @param {object} event vm_node_enter / vm_node_done / operation_done|failed
   * @param {object} args 该节点的入参(done 事件的已由 TwinFeed 从 enter 配对取回)
   */
  handleEvent(event, args = {}) {
    const type = String(event?.type || '')
    const runId = String(event?.run_id || '')
    if (type === 'operation_done' || type === 'operation_failed') {
      this._pickCtx.delete(runId)
      return
    }
    // 面板直跑取料脚本时没有 run_script 节点包裹, 身份只能从根入参取(与上位机
    // material_store.on_event 的 operation_start 分支同理)
    if (type === 'operation_start') {
      this._rememberPick(runId, String(event?.operation || ''), event?.inputs || {})
      return
    }
    if (type === 'vm_node_enter') {
      if (String(event?.op || '') === 'run_script') {
        this._rememberPick(runId, String(event?.action || ''), args)
      }
      return
    }
    if (type !== 'vm_node_done') return
    if (String(event?.op || '') !== 'call') return
    if (String(event?.action || '') !== 'robot.tool_action') return
    if (String(event?.status || '').toUpperCase() !== 'DONE') return

    const toolAction = String(args?.action || '')
    const script = String(event?.script || '')
    if (toolAction === 'gripper-close') {
      // 只有在取料脚本里的合爪才是"夹起了东西"; 放料脚本开头也会合爪(空爪就位)
      const ctx = this._pickCtx.get(runId)
      if (!ctx || !/_pick$/.test(script)) return
      if (!this.payloads.has(ctx.key)) return
      this._l2.set(ctx.carrier, ctx.key)
      if (this._carried.get(ctx.carrier) === ctx.key) return
      if (this._attach(ctx.key)) this._carried.set(ctx.carrier, ctx.key)
      return
    }
    if (toolAction === 'gripper-open') {
      // 松爪即放 —— 这是**物理事实**, 与"当初是谁把它挂上去的"无关。
      // (第一版在这里加了"只放 L2 自己挂的"这道门, 而 L1 总会在搬运途中追上并撤掉那个标记,
      //  于是正常流程下这一支永远不执行, 只能等放料脚本 DONE。别再加回去。)
      const carrier = PUT_SCRIPTS[script]
      if (!carrier) return
      // 记成"空手": 在途行要等放料脚本 DONE 才清, 这中间账本仍说在途,
      // 不记的话下一帧 _applyTransit 会把托盘又抓回爪上。
      this._l2.set(carrier, null)
      const key = this._carried.get(carrier)
      if (key === undefined) return
      this._carried.delete(carrier)
      this._release(key)
    }
  }

  /** 记住某次运行的取料身份(供合爪那一帧用)。认不出脚本就不记。 */
  _rememberPick(runId, script, args) {
    const spec = PICK_SCRIPTS[script]
    if (!spec || !runId) return
    const areaOf = (kind) => {
      const staging = this._lastSnapshot?.staging || {}
      return Object.keys(staging).find((area) => staging[area]?.kind === kind) || ''
    }
    const key = spec.key(args, areaOf)
    if (key && this.payloads.has(key)) this._pickCtx.set(runId, { key, carrier: spec.carrier })
  }

  // ── 每帧 ────────────────────────────────────────────────────────────────

  /**
   * 功能: 每帧推进. 账本快照变了才重算归属, 其余帧只走补间.
   * @param {number} delta 帧间隔(秒)
   * @returns {boolean} 本帧是否动过场景(供调用方决定要不要重渲阴影)
   */
  update(delta = 0) {
    let moved = false
    const snapshot = this.feed?.materialStore?.status?.().snapshot || null
    if (snapshot && snapshot !== this._lastSnapshot) {
      this._lastSnapshot = snapshot
      moved = this._applyTransit(snapshot) || moved
    }
    return this._stepTweens(delta) || moved
  }

  /**
   * 按 material_state.transit 决定谁该挂在爪上、谁该回座.
   * @param {object} snapshot MaterialStore.grid() 的只读投影
   * @returns {boolean} 是否动过场景
   */
  _applyTransit(snapshot) {
    const transit = snapshot.transit || {}
    const wanted = new Map()      // carrier -> 载荷键
    for (const carrier of CARRIERS) {
      const key = this._payloadKeyOf(transit[carrier], snapshot)
      if (key) wanted.set(carrier, key)
    }

    // 逐爪仲裁 L2 与 L1 的分歧。两个方向都要挡:
    //   合爪后账本还没记上在途   -> L1 的"没有这一行"不得把托盘丢回货架;
    //   松爪后账本还没清掉在途   -> L1 的"还有这一行"不得把托盘再抓回爪上。
    // 说到底 L2 领先账本的那一段(取料/放料脚本的整段退刀), 账本描述的是过去。
    // 两边说的一致了就删掉条目, 把这把爪交还给 L1 —— L1 始终是权威, L2 只抢时刻。
    const deferred = new Set()
    for (const carrier of CARRIERS) {
      if (!this._l2.has(carrier)) continue
      if ((wanted.get(carrier) || null) === this._l2.get(carrier)) this._l2.delete(carrier)
      else deferred.add(carrier)
    }

    let moved = false
    // 先落位再吸附: 同一帧里一个载荷从 A 爪换到 B 爪时, 顺序反了会先挂后摘
    for (const [carrier, key] of [...this._carried]) {
      if (deferred.has(carrier)) continue
      if (wanted.get(carrier) === key) continue
      this._carried.delete(carrier)
      moved = this._release(key) || moved
    }
    for (const [carrier, key] of wanted) {
      if (deferred.has(carrier)) continue
      if (this._carried.get(carrier) === key) continue
      // 挂不上(缺 TOOL_MOUNT / 缺节点)就**不记**这一笔: 记了会让 status() 谎报
      // "托盘在爪上", 而画面上它还在原处 —— 下一帧账本再来时自然重试。
      if (!this._attach(key)) continue
      this._carried.set(carrier, key)
      moved = true
    }
    return moved
  }

  /**
   * 把一条在途行翻译成载荷键。认不出就返回空串 —— **不猜**:
   * 宁可这一帧不动画面, 也不把一块编出来的托盘挂到机械臂上。
   * @param {object|undefined} row material_state.transit 的一行
   * @param {object} snapshot 完整快照(单件要用它反查中转板号)
   * @returns {string} 载荷键; 认不出为空串
   */
  _payloadKeyOf(row, snapshot) {
    if (!row) return ''
    const kind = String(row.kind || '')
    const plate = Number(row.plate)
    if (!kind || !Number.isInteger(plate)) return ''

    // 在途载荷画的是**源**节点: 板从货架搬到中转位, 全程飞的是那张货架托盘,
    // 落位后才由 TwinBindings 的显隐把身份交给中转位托盘 (与编译片段的做法一致)。
    let base = ''
    if (row.from_loc === 'rack') {
      base = `rack.${kind}.${plate}`
    } else {
      base = Object.keys(snapshot.staging || {})
        .find((area) => snapshot.staging[area]?.kind === kind) || ''
    }
    if (!base || !this.payloads.has(base)) return ''
    if (String(row.payload) !== 'item') return base

    const hole = Number(row.hole)
    if (!Number.isInteger(hole)) return ''
    const key = `${base}#${hole}`
    return this.payloads.has(key) ? key : ''
  }

  /**
   * 吸附: 把载荷挂到 TOOL_MOUNT 之下并**钉到实测的夹持位姿**, 同时强制可见.
   *
   * 两级阶梯(与 PlateStage.carry 的三级同构, 少的那级是"片段显式给 mount", 实时链没有片段):
   *   1. manifest 的 `attachments[].payload.mountLocal` —— 由 fit_station_alignment
   *      `--emit-grips` 从**取料示教位姿**实测(`inv(mount_world) @ node_world`), 与工位无关;
   *   2. 没有该常量 —— 退回保世界位姿换父(老 manifest 兼容路径)。
   *
   * ⚠ **不能只靠第 2 级**。保世界位姿只在"换父那一刻载荷与夹爪正好重合"时才对, 而在途行是
   *   在 `robot_group_rack_pick` **DONE** 时才落账 —— 那个脚本以 `P7 → P1 → require_anchor(P1)`
   *   收尾, 换父时机械臂已退回 home、离取料点一米开外。于是托盘被冻在货架的世界位置却挂在
   *   home 处的法兰下, 表现就是"托盘在虚空里跟着机械臂转"(2026-08-05 现场实测)。
   *   演示页不受影响是因为片段的 attach 紧跟合爪、那一刻臂正停在示教点 ——
   *   **演示靠时刻, 实时页没有那个时刻**, 所以位姿必须显式给出。
   *
   * 强制可见是必须的 —— TwinBindings 按账本判显隐, 而账本此刻说"板既不在货架也不在
   * 中转位"(它在爪上), 两处都会被判成隐藏; 单件被 consume 后同理会转隐。
   * 谁接管显隐由 owned 集合告知 TwinBindings, 避免两边逐帧互相顶。
   */
  _attach(key) {
    const entry = this.payloads.get(key)
    if (!entry || !this.toolMount) return false
    const mount = entry.mountLocal
    if (mount) {
      this.toolMount.add(entry.node)
      entry.node.position.fromArray(mount.position)
      entry.node.quaternion.fromArray(mount.quaternion).normalize()
      entry.node.updateMatrix()
      entry.node.updateMatrixWorld(true)
    } else {
      // 返回值语义是"本层是否接管了这件载荷", 不是换父的数值精度 ——
      // reparentPreservingWorld 报 false 时换父其实已经发生, 只是残差超了 1e-7,
      // 那种情况必须照常接管, 否则显隐两边都撒手, 托盘会闪。
      if (!reparentPreservingWorld(entry.node, this.toolMount)) {
        console.warn(`[twin] 在途换父残差超限: ${entry.path}`)
      }
      if (!this._warnedNoGrip.has(entry.path)) {
        this._warnedNoGrip.add(entry.path)
        console.warn(
          `[twin] ${entry.path} 没有 manifest 夹持位姿(attachments[].payload.mountLocal), `
          + '已退回保世界位姿 —— 换父时机械臂若不在取料点, 托盘会挂错位置。'
          + '跑 fit_station_alignment.py --emit-grips 后重跑 gen_twin_manifest。',
        )
      }
    }
    entry.node.visible = true
    this.owned.add(entry.path)
    this._ownedDirty = true
    this._tweens.delete(key)
    return true
  }

  /**
   * 落位: 换回原父级并坐正回 CAD 位姿, 随后把显隐控制权交还 TwinBindings.
   *
   * 补间只在"行程短"时走。判据抄 MachineStateDriver 的 PAYLOAD_DOCK_MAX_TRAVEL_M:
   * 松爪那一刻夹爪本就停在目的座上, 需要吃掉的只是毫米级示教残差 —— 行程大说明这次
   * 落位不是发生在座位跟前(例如账本比动作晚, 落位时臂已退回 home), 那就直接就位。
   * 硬拖一条 0.25s 的补间会让托盘横穿整台机器, 比瞬间就位更误导人。
   *
   * ⚠ 交权时机 = **落位补间走完**, 不是本函数返回(2026-08-15 改): 补间每帧写位姿,
   *   早交权会让 TwinBindings 的姿态写入(如已用粉桶倒扣)当帧被补间抹回直立, 要等
   *   下一次账本变化才自愈。接管期 = 挂载 + 落位补间; 补间完成 → ownedDirty →
   *   SceneManager 同步 setTransitOwned → 强制重算, 显隐与倒扣一次落定。
   */
  _release(key) {
    const entry = this.payloads.get(key)
    if (!entry?.home?.parent) return false
    const node = entry.node
    const hadPose = Boolean(node.parent)
    reparentPreservingWorld(node, entry.home.parent)

    const handOver = () => {
      this.owned.delete(entry.path)
      this._ownedDirty = true
    }
    const snap = () => {
      node.position.copy(entry.home.position)
      node.quaternion.copy(entry.home.quaternion)
      node.updateMatrix()
      node.updateMatrixWorld(true)
      this._tweens.delete(key)
      handOver()
    }
    if (!hadPose) {
      snap()
      return true
    }
    if (node.position.distanceTo(entry.home.position) > MAX_SETTLE_TRAVEL_M) {
      snap()
      return true
    }
    this._tweens.set(key, {
      t: 0,
      path: entry.path,
      fromPos: _pos.copy(node.position).clone(),
      fromQuat: _quat.copy(node.quaternion).clone(),
      toPos: entry.home.position.clone(),
      toQuat: entry.home.quaternion.clone(),
    })
    return true
  }

  /** 推进落位补间(ease-out cubic, 与薄层板同款手感); 补间走完才交还显隐控制权。 */
  _stepTweens(delta) {
    if (!this._tweens.size || !(delta > 0)) return false
    let moved = false
    for (const [key, tween] of [...this._tweens.entries()]) {
      const entry = this.payloads.get(key)
      if (!entry) {
        // 载荷条目没了也要交权, 否则该路径永远卡在 owned 集合里
        this._tweens.delete(key)
        this.owned.delete(tween.path)
        this._ownedDirty = true
        continue
      }
      tween.t = Math.min(1, tween.t + delta / SETTLE_S)
      const k = 1 - (1 - tween.t) ** 3
      entry.node.position.lerpVectors(tween.fromPos, tween.toPos, k)
      entry.node.quaternion.slerpQuaternions(tween.fromQuat, tween.toQuat, k)
      moved = true
      if (tween.t >= 1) {
        this._tweens.delete(key)
        this.owned.delete(tween.path)
        this._ownedDirty = true
      }
    }
    return moved
  }

  /** 本层接管的节点路径集合变了没有(供调用方决定要不要同步给 TwinBindings)。 */
  consumeOwnedDirty() {
    const dirty = this._ownedDirty
    this._ownedDirty = false
    return dirty
  }

  /**
   * 断流: 刻意什么都不做 —— 与 MaterialStateStore "断线保末态不回零"同一约定。
   * 托盘绝不能在断线时自己掉回货架: 那是编出来的位置, 比冻结在末态更误导人。
   */
  markDisconnected() {
    // 载荷位置刻意不动(冻结末态)。但在途的取料上下文必须丢: 断流期间的合爪信号收不到,
    // 留着它会在重连后拿一个过期的身份去挂 —— 与 PlateTransferTracker.reset 同一条纪律。
    this._pickCtx.clear()
    // L2 的领先态也要丢, 否则断流期间错过的夹爪事件会让它与 L1 永远对不上,
    // 那把爪就被 deferred 永久挡住、再也不听账本 —— 重连后一律以 L1 重新起算。
    this._l2.clear()
  }

  /**
   * 功能: 向后 seek 的清场 —— 连"挂在爪上的载荷"一起归零.
   *
   * markDisconnected() 刻意冻结载荷位置(断线不该让托盘凭空掉下来), 但回放跳回过去时
   * 那份冻结就是错的: 会出现"还没取料就已经拎着托盘"的画面。owned 还直接控制着 CAD
   * 托盘件的显隐, 不清的话那些件会一直被本层接管着, TwinBindings 再也拿不回去。
   *
   * @returns {void}
   */
  resetForSeek() {
    this.markDisconnected()
    this._tweens.clear()
    this._carried.clear()
    this.payloads.clear()
    this.owned.clear()
    this._ownedDirty = true
    this._lastSnapshot = null
  }

  /** 供 HUD 的只读状态。 */
  status() {
    return {
      bound: this.payloads.size,
      missing: [...this.missing],
      toolMountBound: Boolean(this.toolMount),
      carried: Object.fromEntries(this._carried),
    }
  }

  dispose() {
    for (const payloadKey of this._carried.values()) this._release(payloadKey)
    this._carried.clear()
    this._tweens.clear()
    this.owned.clear()
    this.payloads.clear()
  }
}
