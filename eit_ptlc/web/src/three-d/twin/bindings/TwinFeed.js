/**
 * 功能: 三维视图的高频数据通道 —— 把上位机事件流转成场景可直接消费的纯数据.
 *
 * 性能约定(整个模块最重要的一条): 本文件里的所有状态都是普通对象, 绝不经过 Vue 的
 * 响应式代理. 渲染循环每帧要读几十个通道, 若这些数据是 reactive 的, 每次读写都会
 * 触发依赖收集与触发器检查, 在 60 fps 下是纯粹的浪费. 需要展示给用户的低频信息
 * (选中工位/面板字段/连接状态)才走 Vue 响应式, 由 useTwinScene 单独桥接.
 */
import { createChannel, push } from './interp.js'
import { TankLiquidModel } from './TankLiquidModel.js'
import { PumpSyringeModel } from './PumpSyringeModel.js'
import { AxisPoseBuffer } from './AxisPoseBuffer.js'
import { MechanismStateStore } from './MechanismStateStore.js'
import { MaterialStateStore } from './MaterialStateStore.js'
import { RobotPoseBuffer } from './RobotPoseBuffer.js'
import { SignalLightStore } from './SignalLightStore.js'
import { declaredToolFor } from '../../anim/MachineStateDriver.js'

/** enter→done 入参配对表的驻留上限; 超出按插入序淘汰最旧的(仅在事件丢失时才会触发)。 */
export const PENDING_ARGS_MAX = 512

export class TwinFeed {
  /**
   * 功能: 依据 manifest 建立所有数据通道.
   * @param {object} manifest device-manifest.json 内容
   */
  constructor(manifest, { now = null } = {}) {
    this.manifest = manifest

    /**
     * 本实例的"现在"。实时模式是墙钟; 回放模式由 DVR 传输层换成回放时钟。
     *
     * 之所以做成实例时钟而不是给每个 buffer 逐个注入: 入口路径上每一处 Date.now()
     * 本就是**方法的默认参数**, 而方法本来就接收这个值 —— 只要 TwinFeed 在 push 时
     * 显式传 this.now()、在 sampleX 的默认值里用 this.now(), 下游
     * AxisPoseBuffer / RobotPoseBuffer / MechanismStateStore / SignalLightStore /
     * MaterialStateStore 的签名一行都不用改, TwinBindings 也完全不用动
     * (它调的是 this.feed.sampleX(), 默认值自然走这里)。
     *
     * 硬约束: 回放时钟必须与录像同在**绝对纪元毫秒**域。各 store 的 stampMs 把
     * < 1e12 的值判定为秒并乘 1000, 用 0 基时钟会让 renderTs 远小于每一帧的 ts,
     * 采样器于是永远钳在第一帧 —— 画面卡住却不报任何错。
     */
    this.now = typeof now === 'function' ? now : () => Date.now()

    /** @type {Record<string, string>} 节点 id -> 健康度(ok/busy/error/offline) */
    this.health = {}
    /** @type {Record<string, object>} 节点 id -> 最近一次遥测 data(供面板读取) */
    this.snapshots = {}

    /**
     * 工艺灯的真机 DO 状态(灯 id -> 稳态布尔)。目前只有 `vision_fill`(机器人 DO7 补光)。
     *
     * 与 signalLightStore 的刻意差异: **不建 store、不设 staleness 时钟**。补光每块板
     * 才开关两三次, 后端是"变化即发、无心跳"(见 PTLC_REALTIME_PROTOCOL §7), 没有心跳
     * 就没有可信的断流判据 —— 硬造一个只会在两次拍照之间误判成"断流"。
     * @type {Record<string, boolean>}
     */
    this.processLights = {}

    /** 10–20 Hz axis_pose 的时间缓冲；1 Hz telemetry 只作逐轴回退。 */
    this.axisPose = new AxisPoseBuffer()
    this.axisPoseStale = Object.fromEntries((manifest.axes || []).map((axis) => [axis.id, true]))
    this.axisVelocities = {}

    const mechanismIds = (manifest.realtime?.mechanisms || []).map((item) => item.id)
    this.mechanismStore = new MechanismStateStore({ knownIds: mechanismIds })
    this.mechanismStates = {}

    // 夹爪三态的持料位: controllerTool(2=大爪/3=小爪) -> 机构 id 来自 manifest
    // realtime.mechanisms(rig_map catalog 下发), 避免第四份硬编码 id 契约。
    // 必须同时按 kind 过滤: 1 号刀的吸盘真空(kind: vacuum)也带 controllerTool,
    // 不筛掉的话 gripper-close 事件会错落到吸盘机构上(真机虽被 TOOL_ALLOWED_ACTIONS
    // 挡住, 但仿真/面板直发没有这道门, 是条真实的暗坑)。
    this._gripperByTool = new Map()
    for (const item of manifest.realtime?.mechanisms || []) {
      if (item.kind !== 'gripper') continue
      if (Number.isFinite(Number(item.controllerTool))) {
        this._gripperByTool.set(Number(item.controllerTool), item.id)
      }
    }
    /** @type {Map<string, boolean>} 机构 id -> 是否夹持物料(流程事件包络推断) */
    this.gripHolding = new Map()

    // 1 号刀的玻璃吸盘真空(DO3)。id 同样从 manifest 反查而不是写死 —— 与上面夹爪那段
    // 同一条纪律。它是 rigged:false 的纯状态机构: 没有几何, 存在的唯一意义是让三维在
    // **页面刷新后**仍然知道吸盘还带着电, 从而把"手上那块板"放回去(见 PlateBinding._syncSuction)。
    this._suctionMechId = (manifest.realtime?.mechanisms || [])
      .find((item) => item.kind === 'vacuum' && Number(item.controllerTool) === 1)?.id || ''
    /** @type {boolean} 吸盘真空是否通电(= 手上有板) */
    this.suctionHeld = false

    /**
     * 节点入参的 enter→done 配对表: `${run_id}|${script}|${aid}` -> args[]。
     *
     * 为什么必须自己配对: `vm_node_done` **不带 args** —— thread.py 的 _emit_node_done
     * 只发 type/run_id/script/aid/op/action/status/message/result/... , args 只出现在
     * `vm_node_enter`(_emit_node_enter)。WS 全程原样转发, 不做任何 enrichment。
     * 直接读 `event.args` 在真实事件流里恒为 undefined(离线 fixture 自带 args 才看着像能用),
     * 这正是 2026-08 之前夹爪持料推断从未生效过的原因。
     * 范式照抄上位机 runtime/material_store.py::on_event 的 self._pending。
     *
     * 用数组而非单值: 递归 run_script 会让同一 (run_id, script, aid) 重入, 后进先出各消一条。
     * @type {Map<string, object[]>}
     */
    this._pendingNodeArgs = new Map()

    /**
     * 额外的节点事件消费者(如薄层板搬运推断)。它们收到的是**已配对好入参**的事件,
     * 因此不必各自再建一份 pending 表 —— 配对在本类里只做一次。
     * @type {Set<Function>}
     */
    this._nodeSinks = new Set()

    /** 上位机物料账本的完整快照；断线冻结而不清空。 */
    this.materialStore = new MaterialStateStore({
      staleMs: manifest.realtime?.materialStaleMs ?? 12_000,
    })

    /** 整机三色塔灯 = PLC 输出位的镜像；从未收帧与断流是两个语义(见 store 注释)。 */
    this.signalLightStore = new SignalLightStore({
      staleMs: manifest.signalLight?.staleMs ?? 3000,
    })

    /** @type {object[]} 机器人 6 个关节角的插值通道(单位度) */
    this.joints = Array.from({ length: 6 }, () => createChannel(0))
    /** 20 Hz robot_pose 的 100 ms 时间缓冲；1 Hz telemetry 只作回退。 */
    this.robotPose = new RobotPoseBuffer()
    this.robotPoseStale = true
    /** @type {number} 当前挂载工具编号 */
    this.mountedTool = 0
    /** @type {boolean} 机械臂是否在线 */
    this.robotConnected = false
    this.robotMode = null
    this.transportConnected = false

    /** @type {number[]} 8 个展缸的状态码 */
    this.tankStates = new Array(8).fill(0)
    /**
     * 8 个展缸的液体体积模型. 动作包络(带缸号与配方体积)当主源画注/排液的过程,
     * Tank_State 当相位锚点兜底 —— 单靠后者画不出过程, 见 TankLiquidModel 文件头.
     */
    this.tankLiquid = new TankLiquidModel(manifest.tankLiquid)

    /**
     * 三台注射泵的柱塞位置模型. 与 tankLiquid 吃同一批动作事件, 但只有动作包络这一路
     * 信号 —— 泵位置全程无反馈, 见 PumpSyringeModel 文件头.
     */
    this.pumpSyringe = new PumpSyringeModel(manifest.pumpSyringe)
    // 相位时长按 PLC 的 V/M 换算, 而 V/M 的真源是 config.pump(可在线改). manifest 里
    // 只有构建期快照, 这里补拉一次实时值 —— 与后端 tools/pump/profiles.py 的回退链同形:
    // 动作入参 > config.pump 实时 > 构建期快照. 拉不到就静默用快照, 绝不阻断出图.
    this._loadPumpSpeeds()

    /** @type {Record<string, number>} 工位 id -> 活跃度(1 = 刚有步骤开始, 随时间衰减) */
    this.activity = {}
    /** @type {number[]} 地轨命中的站位码 */
    this.railSlots = []

    /** @type {number} 版本号, 每次有数据写入自增, 供渲染层判断是否需要重算 */
    this.version = 0

    // 预先建立"遥测键 -> 轴"的索引, 避免每帧在 manifest 里线性查找
    this._axisByTelemetry = new Map()
    for (const axis of manifest.axes || []) {
      const key = axis.telemetry?.key
      const node = axis.telemetry?.node
      if (key && node) this._axisByTelemetry.set(`${node}::${key}`, axis)
    }

    // 工位 id -> 上位机节点 id 的双向索引
    this._stationByNode = new Map()
    for (const station of manifest.stations || []) {
      if (station.nodeId) this._stationByNode.set(station.nodeId, station.id)
    }
  }

  /**
   * 功能: 拉一次 config.pump 的实时 V/M 档喂给泵模型.
   *
   * 失败一律静默 —— 这是"让相位时长更准"的增强, 不是必需品: 拉不到就用 manifest 里
   * 的构建期快照, 快照也没有才退回动作表写死的 rampS。三维绝不能因为一个配置接口
   * 没起就不动。
   *
   * @returns {Promise<void>}
   */
  async _loadPumpSpeeds() {
    try {
      const { api } = await import('../../../api.js')
      const values = (await api.getConfigSection('pump'))?.values
      if (values && typeof values === 'object') this.pumpSyringe.setLiveSpeeds(values)
    } catch {
      /* 离线打开 / 后端没起: 用 manifest 快照即可 */
    }
  }

  /**
   * 功能: 处理一条来自上位机的事件.
   * @param {object} event 事件对象
   * @returns {void}
   */
  handleEvent(event) {
    switch (event?.type) {
      case 'telemetry':
        this._handleTelemetry(event)
        break
      case 'robot_pose':
        this._handleRobotPose(event)
        break
      case 'axis_pose':
        this._handleAxisPose(event)
        break
      case 'mechanism_state':
        this._handleMechanismState(event)
        break
      case 'material_state':
        this._handleMaterialState(event)
        break
      case 'signal_light':
        this._handleSignalLight(event)
        break
      // 仿真沙盒专属的虚拟泵位置反馈(协议 §7c): 有反馈优先, 包络退位。
      // 主通道永远不发此事件(真机泵无位置回读), live 页零影响。
      case 'pump_state':
        this.pumpSyringe.pushFeedback(event)
        break
      // 仿真沙盒专属的展缸液量 (协议 §7d): 后端按"泵排出量 × 进液阀"积出的真值,
      // 收到即关掉包络与相位锚点两路合成。主通道永远不发此事件 (真机无流量计),
      // live 页零影响 —— 与 pump_state 同一条形制。
      case 'tank_liquid':
        this.tankLiquid.onTankVolume(event)
        break
      case 'process_light':
        this._handleProcessLight(event)
        break
      case 'step_done':
        this._handleActivity(event)
        this._handleManualResult(event)
        // 单动作路径(维护面板直发)的入参在 params 上, 与 VM 的 args 同形;
        // 后端 app.py 的合成事件 2026-08-03 起随事件带出。
        this._handleLiquidAction(event.action, event.params, false, event.status)
        break
      case 'step_start':
        this._handleActivity(event)
        this._handleLiquidAction(event.action, event.params, true)
        break
      case 'operation_start':
        this._handleActivity(event)
        break
      case 'vm_node_enter':
        this._handleVmNodeEnter(event)
        this._fanoutNode(event, event.args || {})
        break
      // 配对在这里做一次: 无论后面谁消费, done 事件的入参都只从这一处取回,
      // 且不论 op 类型都要取(否则 run_script 的进入记录会一直占着配对表)
      case 'vm_node_done': {
        const args = this._takeNodeArgs(event)
        this._handleVmNodeDone(event, args)
        this._fanoutNode(event, args)
        break
      }
      // 刮取条带(后端 cnc_path 在算出本次视觉谱带时发一条)。走 _fanoutNode 而不是自建
      // 订阅: 消费者(PlateBinding)本来就挂在那条 sink 上, 事件里也没有要配对的 args。
      // ⚠ 它**不在** runtime/events.py 的 _DROPPABLE_TYPES 里 —— 丢一条就永远画不出刮痕。
      case 'scrape_state':
        this._fanoutNode(event, {})
        break
      case 'operation_done':
      case 'operation_failed':
        this._clearRunPending(event)
        this._fanoutNode(event, {})
        break
      default:
        break
    }
  }

  /**
   * 功能: 注册一个节点事件消费者, 返回退订函数.
   * 消费者拿到的 args 已经配对好, 不需要自己再存一份 pending 表。
   * @param {(event: object, args: object) => void} sink 消费者
   * @returns {() => void} 退订
   */
  addNodeSink(sink) {
    if (typeof sink !== 'function') return () => {}
    this._nodeSinks.add(sink)
    return () => this._nodeSinks.delete(sink)
  }

  /** 扇出给节点事件消费者; 单个消费者抛错不影响其它(与上位机 event sink 同款 best-effort)。 */
  _fanoutNode(event, args) {
    for (const sink of this._nodeSinks) {
      try {
        sink(event, args)
      } catch (error) {
        console.warn('[twin] 节点事件消费者抛错(已隔离)', error)
      }
    }
  }

  /** 节点配对键; 与上位机 material_store 的 (run_id, script, aid) 三元组同构。 */
  _nodeKey(event) {
    return `${event?.run_id ?? ''}|${event?.script ?? ''}|${event?.aid ?? ''}`
  }

  /**
   * 功能: 暂存 `vm_node_enter` 的入参, 供同节点的 `vm_node_done` 取回(见 _pendingNodeArgs 注释).
   *
   * 只收 call / run_script 两种带入参的节点。上限 PENDING_ARGS_MAX 条, 超出按插入序淘汰最旧的 ——
   * 正常路径 enter/done 成对出现, 表里只会驻留"正在执行的调用栈", 淘汰只在事件丢失时兜底,
   * 目的是让长跑流程不至于无界增长。
   * @param {object} event vm_node_enter 事件
   * @returns {void}
   */
  _handleVmNodeEnter(event) {
    const op = String(event?.op || '')
    if (op !== 'call' && op !== 'run_script') return
    if (op === 'call') this._handleLiquidAction(event.action, event.args, true)
    const key = this._nodeKey(event)
    const stack = this._pendingNodeArgs.get(key)
    if (stack) stack.push({ ...(event.args || {}) })
    else this._pendingNodeArgs.set(key, [{ ...(event.args || {}) }])
    while (this._pendingNodeArgs.size > PENDING_ARGS_MAX) {
      const oldest = this._pendingNodeArgs.keys().next().value
      if (oldest === undefined) break
      this._pendingNodeArgs.delete(oldest)
    }
  }

  /**
   * 功能: 取回并消费某 done 节点对应的 enter 入参.
   * 回退到 `event.args` 是有意保留的: 若将来上位机给 vm_node_done 也补上 args, 本处自动受益;
   * 离线测试用自带 args 的 fixture 也仍然能跑。
   * @param {object} event vm_node_done 事件
   * @returns {object} 入参(缺失时为空对象)
   */
  _takeNodeArgs(event) {
    const key = this._nodeKey(event)
    const stack = this._pendingNodeArgs.get(key)
    if (stack?.length) {
      const args = stack.pop()
      if (!stack.length) this._pendingNodeArgs.delete(key)
      return args
    }
    return event?.args ? { ...event.args } : {}
  }

  /** 运行结束: 清掉该 run 残留的进入记录(异常路径会留下未配对的 enter)。 */
  _clearRunPending(event) {
    const prefix = `${event?.run_id ?? ''}|`
    for (const key of [...this._pendingNodeArgs.keys()]) {
      if (key.startsWith(prefix)) this._pendingNodeArgs.delete(key)
    }
  }

  /**
   * 功能: 处理遥测事件 —— 更新健康度、轴位置、关节角、展缸状态.
   * @param {object} event 遥测事件
   * @returns {void}
   */
  _handleTelemetry(event) {
    const nodeId = event.node
    const data = event.data || {}
    // 回退值必须与 event.ts*1000 同域(绝对纪元毫秒)。原先用 performance.now()
    // (页面加载起算的 ~1e4) 与纪元毫秒(~1.79e12) 混进同一条插值通道, 算出的 gap
    // 是天文数字, 只因 interp 有 0.02~10 的区间过滤才没炸出来。回放时钟下更不能混。
    const stamp = typeof event.ts === 'number' ? event.ts * 1000 : this.now()

    this.health[nodeId] = event.health || 'unknown'
    this.snapshots[nodeId] = data
    this.version += 1

    // -- 轴位置 -----------------------------------------------------------
    const fallbackAxes = {}
    for (const [key, value] of Object.entries(data)) {
      const axis = this._axisByTelemetry.get(`${nodeId}::${key}`)
      if (axis && typeof value === 'number') {
        fallbackAxes[axis.id] = value
      }
    }
    if (Object.keys(fallbackAxes).length) this.axisPose.pushTelemetry(fallbackAxes, event.ts, this.now())

    // -- 机器人 -----------------------------------------------------------
    if (nodeId === 'robot') {
      this.robotConnected = Boolean(data.connected)
      if (Array.isArray(data.joint)) {
        for (let i = 0; i < Math.min(6, data.joint.length); i += 1) {
          push(this.joints[i], data.joint[i], stamp)
        }
        this.robotPose.pushTelemetry(data, event.ts, this.now())
      }
      const tool = data.tool_state?.mounted_tool
      if (typeof tool === 'number') this.mountedTool = tool
      if (typeof data.robot_mode === 'number') this.robotMode = data.robot_mode
    }

    // -- 展缸 -------------------------------------------------------------
    if (Array.isArray(data.Tank_State)) {
      for (let i = 0; i < Math.min(8, data.Tank_State.length); i += 1) {
        this.tankStates[i] = Number(data.Tank_State[i]) || 0
      }
      // 相位锚点: 无在途动作时按状态复位液面(断线重连/后端重启/纯手动 PLC 操作),
      // 有在途动作时只允许提前收尾 —— 冲突规则见 TankLiquidModel.onTankStates
      this.tankLiquid.onTankStates(this.tankStates, this.manifest.tankStateStyles)
    }

    // -- 地轨站位 ---------------------------------------------------------
    if (nodeId === 'plc.rail' && Array.isArray(data.current_positions)) {
      this.railSlots = data.current_positions
    }
  }

  /** 高频只读反馈；按 seq/ts 缓冲，乱序帧不会让模型回跳。 */
  _handleRobotPose(event) {
    if (!this.robotPose.push(event, this.now())) return
    this.robotConnected = true
    if (typeof event.tool === 'number') this.mountedTool = event.tool
    if (typeof event.mode === 'number') this.robotMode = event.mode
    this.version += 1
  }

  _handleAxisPose(event) {
    if (!this.axisPose.push(event, this.now())) return
    this.version += 1
  }

  _handleMechanismState(event) {
    if (!this.mechanismStore.push(event, this.now())) return
    this.version += 1
  }

  _handleMaterialState(event) {
    if (!this.materialStore.push(event, this.now())) return
    this.version += 1
  }

  _handleSignalLight(event) {
    if (!this.signalLightStore.push(event, this.now())) return
    this.version += 1
  }

  /**
   * 功能: 收下一条工艺灯的真机 DO 状态(视觉纠偏补光 = 机器人 DO7).
   *
   * 事件由 `bootstrap.pallas_light_setter` 与写 DO7 同一次调用发出, 所以这里的布尔
   * 就是**真机 DO 的实况**, 不是从流程包络猜出来的。`id` 与 manifest.lights[].id
   * 同名; 认不出的 id 照收不误 —— 绑定层查不到就自然忽略, 这里不做白名单, 免得
   * 将来新增一盏灯还要改两处。
   *
   * @param {object} event process_light 事件
   * @returns {void}
   */
  _handleProcessLight(event) {
    const id = event?.id
    if (typeof id !== 'string' || !id) return
    const on = Boolean(event.on)
    if (this.processLights[id] === on) return
    this.processLights[id] = on
    this.version += 1
  }

  /**
   * 功能: 取工艺灯当前的稳态布尔表(供绑定层做斜坡).
   * @returns {Record<string, boolean>} 灯 id -> 是否点亮; 从未收到过帧时为空对象
   */
  sampleProcessLights() {
    return this.processLights
  }

  /**
   * 功能: 从流程事件包络推断夹爪是否夹着物料(三态闭合的持料位, 用户拍板方案).
   *
   * 判据: robot_*_pick 脚本里完成的 gripper-close → 持料; 任意 gripper-open 完成
   * → 释放。为什么不用别的源: 物料账本在取放期间刻意不变(绑定在 transfer_* 层,
   * "板停在夹爪里"没有账目); 夹爪闭合限位 DI1 在仿真传输下恒 0 会误判"永远持料"。
   * 已知降级(可接受): 页面在搬运中途刷新 → 无包络可见, 显示空爪紧闭, 下一次开合
   * 自动归正; 流程中途取消 → 保持持料直到 gripper-open(物理属实: 爪没松料就在);
   * 面板手动单发 gripper-close(无 *_pick 脚本上下文)→ 空爪紧闭, 语义正确。
   *
   * ⚠ args 由 handleEvent 经 _takeNodeArgs 从对应的 vm_node_enter 取回后传入 ——
   * vm_node_done 事件本身不带 args。
   *
   * @param {object} event vm_node_done 事件
   * @param {object} args 该节点的入参(已配对)
   */
  _handleVmNodeDone(event, args) {
    if (event?.op !== 'call') return
    this._handleLiquidAction(event.action, args, false, event.status)
    if (event.action !== 'robot.tool_action') return
    if (String(event.status || '').toUpperCase() !== 'DONE') return
    const toolAction = args?.action
    if (toolAction !== 'gripper-open' && toolAction !== 'gripper-close') return
    const mechId = this._gripperByTool.get(this.mountedTool)
    if (!mechId) return
    const next = toolAction === 'gripper-close'
      ? /_pick/.test(String(event.script || ''))
      : false
    if (this.gripHolding.get(mechId) !== next) {
      this.gripHolding.set(mechId, next)
      this.version += 1
    }
  }

  /**
   * 功能: 把一条吸/排液动作事件转给展缸液体模型.
   *
   * 三条入口共用本函数, 因为它们的入参形状是一样的(都带 target_tank 与配方体积):
   *   - VM 的 vm_node_enter/vm_node_done (args; done 的 args 由 _takeNodeArgs 配对取回)
   *   - 维护面板单发动作的 step_start/step_done (params)
   * 与本模型无关的动作会在 TankLiquidModel._resolve 里被动作表挡掉, 这里不做过滤。
   *
   * @param {string} action 动作名
   * @param {object} args 入参(args 或 params)
   * @param {boolean} entering true=开始, false=结束
   * @param {string} [status] 结束状态(仅 entering=false 时有意义)
   * @returns {void}
   */
  _handleLiquidAction(action, args, entering, status) {
    if (!action || !args) return
    // 两个模型看同一批事件的**不同侧面**: develop.fill 既让缸里多 20mL, 也让泵柱塞往复
    // N 趟. 各自的动作表各挡各的, 互不知道对方存在, 所以两个都调、不做过滤或互斥.
    // 覆盖面本就不重合: sampling.*/collect.* 只动泵不动缸, develop.drain 只动缸不动泵
    // (排液是真空泵, 不是注射泵).
    const tankTouched = entering
      ? this.tankLiquid.onActionEnter(action, args)
      : this.tankLiquid.onActionDone(action, args, status)
    const pumpTouched = entering
      ? this.pumpSyringe.onActionEnter(action, args)
      : this.pumpSyringe.onActionDone(action, args, status)
    if (tankTouched || pumpTouched) this.version += 1
  }

  /** 单点控制的审计 step_done 可立即更新命令态；它不能冒充传感器反馈。 */
  _handleManualResult(event) {
    const action = String(event.action || '')
    const result = event.result || {}
    if (!action.startsWith('manual.cylinder.')) return
    const id = result.id || action.slice('manual.cylinder.'.length)
    if (typeof result.on !== 'boolean') return
    if (this.mechanismStore.pushCommand(id, result.on, this.now())) this.version += 1
  }

  /** 供渲染层逐帧采样；stale 时返回最后姿态（冻结），绝不回零。 */
  sampleRobotPose(nowMs = this.now()) {
    const sample = this.robotPose.sample(nowMs)
    this.robotPoseStale = sample.stale
    return sample
  }

  sampleAxisPose(nowMs = this.now()) {
    const sample = this.axisPose.sample(nowMs)
    this.axisPoseStale = sample.stale
    this.axisVelocities = sample.velocities
    return sample
  }

  sampleMechanismStates(nowMs = this.now()) {
    this.mechanismStates = this.mechanismStore.sample(nowMs)
    // 持料位并进夹爪条目(sample 每次返回新对象, 原地补字段安全); 绑定层据此在
    // 满闭合与 holdValue 之间选 target。
    for (const [id, holding] of this.gripHolding) {
      const state = this.mechanismStates[id]
      if (state) state.holding = holding
    }
    // 真空位: **刻意不看 stale**。它是个锁存位, 而 store 的既定约定就是断流冻结末态、
    // 绝不回零 —— 末次已知值就是当前真值, 按 stale 清掉等于每次断流都把板从手上扔了。
    // 吸盘没有任何 DI(_TOOL_DI_TARGET 无 SUCTION 条目), confirmed 恒 null, effective
    // 自然落到 commanded; 这是后端如实表达, 不是缺陷。
    // 机构只在挂 1 号刀时才发布(mechanism_snapshot), 所以条目在场本身就蕴含了工具号。
    const suction = this._suctionMechId ? this.mechanismStates[this._suctionMechId] : null
    this.suctionHeld = Boolean(suction && suction.available !== false && suction.effective)
    return this.mechanismStates
  }

  /** 供绑定层逐帧采样三色塔灯; received=false 时绑定层保持烘焙静态色. */
  sampleSignalLight(nowMs = this.now()) {
    return this.signalLightStore.sample(nowMs)
  }

  setTransportState(connected) {
    const next = Boolean(connected)
    if (this.transportConnected && !next) {
      this.robotPose.markDisconnected()
      this.axisPose.markDisconnected()
      this.mechanismStore.markDisconnected()
      this.materialStore.markDisconnected()
      this.signalLightStore.markDisconnected()
      // 泵没有任何遥测锚点, 断流后连"估计"都不成立: 冻结末态并标不可信, 且必须清掉在途
      // 包络 —— 下面 _pendingNodeArgs 一清, 重连后那条 done 就拿不到 args, 永远不会来收尾
      this.pumpSyringe.markDisconnected()
      // 断流时在途的 vm_node_enter 永远等不到它的 done, 留着只会污染重连后的配对
      this._pendingNodeArgs.clear()
    } else if (!this.transportConnected && next) {
      // 重连: 位置仍不可信, 直到收到下一条 *.init(DT 的 Z 归零)或任一动作包络
      this.pumpSyringe.markReconnected()
    }
    this.transportConnected = next
  }

  /**
   * 功能: 为"向后 seek"清场 —— 丢弃一切带时间单调性的锁存, 之后由关键帧重新播种.
   *
   * 与 setTransportState(false) 的区别是决定性的: 后者只是"标记断流、保留末态",
   * 清不掉三处会让回放**静默失败**的东西 ——
   *   1. MechanismStateStore 逐机构的 ts 闸门: 比末态更早的机构快照被逐 id 跳过,
   *      关键帧整个失效, 气缸/阀停在未来的状态上;
   *   2. Axis/RobotPoseBuffer 的 lastArrival 单调最大值: 回放时钟往回走后差值为负,
   *      stale 恒判 false, 且 1Hz telemetry 回退被永久压制;
   *   3. _pendingNodeArgs 里残留的 enter 帧: 下一条 done 会弹到错误的入参。
   * 三者都不抛错, 只是画面从此不再说实话。
   *
   * @returns {void}
   */
  resetForSeek() {
    this.robotPose.reset()
    this.axisPose.reset()
    this.mechanismStore.reset()
    this.materialStore.markDisconnected()   // 下一帧带 initial:true 即可越过其倒退闸门
    this.signalLightStore.markDisconnected()
    this.pumpSyringe.markDisconnected()
    this._pendingNodeArgs.clear()
    this.mechanismStates = {}
    this.gripHolding.clear()
    this.suctionHeld = false
    this.processLights = {}
    this.railSlots = []
    // 工位活跃度是 ~6 秒的衰减量, 不清的话向后跳之后会有一圈并不存在的余辉
    this.activity = {}
    this.version += 1
  }

  /**
   * 功能: 直接写入那些**没有任何事件能置位**的锁存量(回放关键帧用).
   *
   * 典型是 gripHolding: 唯一的置位通路是合成一条脚本名匹配 /_pick/、且 mountedTool
   * 已经正确的 vm_node_done —— 靠合成事件去凑太脆。与其伪造事件, 不如老实给一个
   * 写入口, 它同时也让实时模式有了可测试的复位路径。
   *
   * @param {object} snapshot 录像块关键帧
   * @returns {void}
   */
  applySnapshot(snapshot) {
    if (!snapshot || typeof snapshot !== 'object') return
    if (Number.isFinite(snapshot.mountedTool)) this.mountedTool = Number(snapshot.mountedTool)
    if (snapshot.robotMode !== undefined) this.robotMode = snapshot.robotMode
    if (Array.isArray(snapshot.tankStates)) this.tankStates = snapshot.tankStates.slice(0, 8)
    if (Array.isArray(snapshot.railSlots)) this.railSlots = snapshot.railSlots.slice()
    if (snapshot.processLights && typeof snapshot.processLights === 'object') {
      this.processLights = { ...snapshot.processLights }
    }
    if (snapshot.gripHolding && typeof snapshot.gripHolding === 'object') {
      this.gripHolding = new Map(Object.entries(snapshot.gripHolding))
    }
    if (typeof snapshot.suctionHeld === 'boolean') this.suctionHeld = snapshot.suctionHeld
    // 泵速: 实时模式下由构造函数里 fire-and-forget 的 fetch 拉取, 与第一个泵包络竞争。
    // 回放必须用录像里的那一份, 否则同一段录像两次回放可能算出不同的相位时长。
    if (snapshot.pumpSpeeds && typeof snapshot.pumpSpeeds === 'object') {
      this.pumpSyringe.setLiveSpeeds(snapshot.pumpSpeeds)
    }
    this.version += 1
  }

  realtimeStatus(nowMs = this.now()) {
    const robot = this.robotPose.sample(nowMs)
    const axes = this.axisPose.sample(nowMs)
    const mechanisms = this.mechanismStore.sample(nowMs)
    const knownAxes = Object.keys(axes.positions)
    const knownMechanisms = Object.keys(mechanisms)
    const axisCatalog = this.manifest.realtime?.axes || this.manifest.axes || []
    const mechanismCatalog = this.manifest.realtime?.mechanisms || []
    // 高频帧优先, 1 Hz telemetry 兜底; 两路都没有时保留最后已知工具号
    const toolNumber = Number.isFinite(Number(robot.tool)) ? Number(robot.tool) : this.mountedTool
    const declaredTool = declaredToolFor(this.manifest, toolNumber)
    return {
      transportConnected: this.transportConnected,
      robot: {
        available: Boolean(robot.joint),
        stale: robot.stale,
        resynced: robot.resynced,
        mode: robot.mode ?? this.robotMode,
        // 关节角与位姿透传给机械臂操控面板: 这条是 20 Hz 的 robot_pose 插值结果,
        // 比 1 Hz 的 telemetry 快 20 倍 —— 点动时数值跟手与否全看它。
        // 已是 sample() 里 clone 过的新数组, 直接给出去不会被下一帧改写。
        joint: robot.joint,
        pose: robot.pose,
      },
      // 末端工具: 控制器报了模型没声明的刀时必须显式告警。以前这里什么都不显示,
      // 于是"后端挂着吸盘、前端法兰空空如也"只能靠肉眼发现。
      tool: {
        controllerTool: toolNumber,
        declared: Boolean(declaredTool) || toolNumber === 0,
        id: declaredTool?.id || null,
        label: toolNumber === 0 ? '裸腕' : (declaredTool?.label || null),
        stale: robot.stale,
      },
      axes: {
        known: knownAxes.length,
        total: (this.manifest.axes || []).length,
        stale: knownAxes.filter((id) => axes.stale[id]).length,
        resynced: axes.resynced,
        items: axisCatalog.map((item) => ({
          ...item,
          position: axes.positions[item.id],
          velocity: axes.velocities[item.id],
          stale: axes.stale[item.id] ?? true,
          resynced: axes.resynced.includes(item.id),
        })),
      },
      mechanisms: {
        known: knownMechanisms.length,
        total: mechanismCatalog.length,
        stale: knownMechanisms.filter((id) => mechanisms[id].stale).length,
        estimated: knownMechanisms.filter((id) => mechanisms[id].estimated).length,
        resynced: knownMechanisms.filter((id) => mechanisms[id].resynced),
        items: mechanismCatalog.map((item) => ({
          ...item,
          ...(mechanisms[item.id] || { stale: true, estimated: true }),
        })),
      },
      // 注射泵柱塞: estimated 恒等于 total —— 泵位置**永远**没有传感器确认
      // (plc_nodes.yaml 里没有任何回读通道), 这不是"暂时没收到反馈"而是"这条链路上
      // 不存在反馈". 所以不像机构那样按 feedbackFresh 算, 直接写死; 另给一个 known
      // 位区分"算得出来的估计值"与"冷启动/断线后连估计都不成立".
      pumps: (() => {
        const items = this.pumpSyringe.snapshot()
        return {
          total: items.length,
          known: items.filter((p) => p.known).length,
          rigged: items.filter((p) => p.rigged).length,
          estimated: items.length,
          stale: items.filter((p) => p.stale).length,
          items,
        }
      })(),
      materials: this.materialStore.status(nowMs),
      signalLight: this.signalLightStore.sample(nowMs),
    }
  }

  /**
   * 功能: 根据步骤/流程事件点亮对应工位的活跃度.
   *
   * 事件里没有工位字段, 只有动作名(如 develop.drain), 因此靠 manifest 里每个工位的
   * actionPrefixes 反查 —— 这也是 manifest 收录动作清单的用途之一.
   *
   * @param {object} event 事件对象
   * @returns {void}
   */
  _handleActivity(event) {
    const name = event.action || event.operation || ''
    if (!name) return
    for (const station of this.manifest.stations || []) {
      const hit = (station.actionPrefixes || []).some((prefix) => name.startsWith(prefix))
      if (hit) {
        this.activity[station.id] = 1
        this.version += 1
      }
    }
  }

  /**
   * 功能: 按帧衰减工位活跃度, 让高亮在若干秒内自然褪去.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  decayActivity(delta) {
    for (const key of Object.keys(this.activity)) {
      const next = this.activity[key] - delta / 6
      if (next <= 0) delete this.activity[key]
      else this.activity[key] = next
    }
  }

  /**
   * 功能: 取某工位当前的健康度.
   * @param {object} station manifest 中的工位条目
   * @returns {string} 健康度标识
   */
  healthOf(station) {
    if (!station.nodeId) return 'unknown'
    return this.health[station.nodeId] || 'offline'
  }
}
