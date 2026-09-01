/**
 * 功能: 8 个展缸的液体体积模型 —— 把"动作在跑"和"缸处于哪个相位"两路信号合成一条
 *       连续的液面曲线, 供三维按体积缩放液面盒、面板显示 mL.
 *
 * 为什么需要两路信号:
 *   Tank_State(1 Hz 遥测)知道相位, 但整个"润洗+上液+放板"阶段它恒等于 10(PREPPING),
 *   注液全程只会跳一次就不动了 —— 表达不出"过程". 真正带缸号与体积的是动作事件的
 *   args(VM 的 vm_node_enter / 单动作路径的 step_start), 但它只有起止两拍, 断线重连
 *   后又什么都收不到. 于是: **动作包络当主源画过程, Tank_State 当锚点兜底**.
 *
 * 两源冲突规则(整个文件最要紧的一条): 动作包络在途时, Tank_State 只允许"提前收尾",
 * 不允许上抬 —— 98(已排空)/0(空闲) 立刻归零, 90(故障) 保持当前, 其余一律忽略.
 * 否则注液刚涨到一半, 下一拍 Tank_State=10 的锚点值就会把它拽回去, 液面来回抽搐.
 *
 * 时长不是真实流量: 泵动作全程 L2 字段静默(见 config/actions/02_develop/plc_develop.yaml
 * 的 stall_timeout 注释), 上位机拿不到任何进度反馈. 这里用 interp 的指数趋近, 先快后
 * 缓、永不过冲; 动作 done 时吸附到终值. 真实动作比 rampS 长时液面就停在目标位 ——
 * 那恰是物理事实(缸已满, 泵在跑后续循环).
 *
 * 性能: 与 TwinFeed 同一约定, 本文件所有状态都是普通对象, 绝不进 Vue 响应式.
 */
import {
  ARRIVE_FACTOR, DEFAULT_SAMPLE_PERIOD, clamp, createChannel, push, step,
} from './interp.js'

const TANK_COUNT = 8

/** 没有 manifest.tankLiquid 时的退化参数: 只保证不炸, 液面不会动 */
const FALLBACK_CAVITY = { usableDepthMm: 1, freeAreaMm2: 1, capacityMl: 0, mlPerMm: 1 }

/**
 * 功能: 体积(mL) -> 液面缩放比 0~1 —— 三维缩放 scale.y 用.
 *
 * 物理高度 = 体积 / 自由截面积; 再乘观感放大系数并按槽深封顶. 整机远景下溶液槽
 * 只有 210×40mm, 物理真值的涨落只有几个像素, 放大系数就是为此留的.
 *
 * 为什么提成模块级纯函数: 实时链(本文件 + TwinBindings)与离线链
 * (anim/MachineStateDriver 的 liquid 通道)要写出**逐位相同**的液面高度, 否则同一条
 * 动作在演示页与实况页高低不一, 而两边都看着挺正常. 本仓已经为"同一条公式留两份"
 * 付过一次代价(linkageKinematics.js ↔ gen_twin_manifest.solve_lid_kinematics, 只能靠
 * 两侧各挂一个回归测试锁住) —— 那是跨语言不得已, 这里两个消费方同在一个 bundle,
 * 抽出来就根除了这类漂移.
 *
 * @param {object} cavity manifest.tankLiquid.cavity(需含 usableDepthMm / freeAreaMm2)
 * @param {number} volumeMl 体积 mL
 * @param {number} [exaggeration] 观感放大系数; 面板显示的 mL 不受它影响
 * @returns {number} 0~1
 */
export function levelFromMl(cavity, volumeMl, exaggeration = 1) {
  const depth = Number(cavity?.usableDepthMm)
  const area = Number(cavity?.freeAreaMm2)
  const ml = Number(volumeMl)
  if (!(depth > 0) || !(area > 0) || !Number.isFinite(ml)) return 0
  const heightMm = (Math.max(0, ml) * 1000) / area
  return clamp((heightMm * (Number(exaggeration) || 1)) / depth, 0, 1)
}

/**
 * 功能: 把一条动作事件的 args 解析成"这动作要把哪个缸的液体变成多少".
 *
 * 与 levelFromMl 同一条理由提成纯函数: 实时链吃 WS 事件、离线链
 * (demo/actionSim.js、demo/flowSim.js)吃面板入参, 但"体积 = 各来源参数连乘"
 * 这条规则只能有一份 —— 它漂了的表现是"演示里注了 40mL, 实况页显示 20mL",
 * 没有任何自动指标会报警.
 *
 * @param {object} config manifest.tankLiquid(需 actions / tankArg / cavity 等)
 * @param {string} action 动作名
 * @param {object} args 动作入参
 * @returns {null|{index: number, dir: string, targetMl: number, rampS: number, delayS: number}}
 */
export function resolveLiquidPlan(config, action, args) {
  const spec = config?.actions?.[action]
  if (!spec || !args) return null

  const tankArg = config.tankArg || 'target_tank'
  const tank = Number(args[tankArg])
  // 缸号是 1~8 的用户面编号, 数组下标要减 1
  if (!Number.isInteger(tank) || tank < 1 || tank > TANK_COUNT) return null

  const capacityMl = Number(config.cavity?.capacityMl) || 0
  const pipeHoldupMl = Number.isFinite(config.pipeHoldupMl) ? config.pipeHoldupMl : 0

  let targetMl = 0
  if (spec.dir === 'fill') {
    // 体积 = 各来源参数连乘(体积 × 重复次数). 缺哪个就按 1 算 —— 流程 YAML 只写了
    // 部分入参时, 其余由动作目录的 default 在执行器侧补齐, 事件里看不到.
    targetMl = (spec.volumeFrom || []).reduce((acc, key) => {
      const value = Number(args[key])
      return acc * (Number.isFinite(value) && value > 0 ? value : 1)
    }, 1)
    if (!(targetMl > 0)) return null
    targetMl = Math.max(0, targetMl - pipeHoldupMl)
    if (capacityMl > 0) targetMl = Math.min(targetMl, capacityMl)
  }

  let rampS = Number(spec.rampS) || 8
  const fromArg = Number(args[spec.rampFromArg])
  if (spec.rampFromArg && Number.isFinite(fromArg) && fromArg > 0) rampS = fromArg
  const delayRaw = Number(args[spec.delayFromArg])
  const delayS = spec.delayFromArg && Number.isFinite(delayRaw) && delayRaw > 0 ? delayRaw : 0

  return { index: tank - 1, dir: spec.dir, targetMl, rampS, delayS }
}

/**
 * 功能: 把一条动作解析成驻位液体(manifest.liquids[] 条目, 如收集样品瓶)的逐轮注液计划.
 *
 * 与 resolveLiquidPlan 的两处刻意不同(与 gen_twin_manifest.STATION_LIQUID_ACTIONS
 * 头注同一段话): volumeFrom 只给**单轮体积**, 轮数由 repeatFrom 单独表达; 时长不做
 * 任何本地换算 —— roundS(实机值, 写进标签)与 demoS(演示压缩值, 上时间轴)都由契约
 * 给出, 三个消费方(clip_compiler.emit_station_liquid / flowSim / actionSim)只读表.
 * 本函数是前端两个消费方共用的那一份; Python 侧按同一契约镜像, 由片段语料测试锁住.
 *
 * @param {object} liquidSpec manifest.liquids[] 的一条(需含 actions / cavity)
 * @param {string} action 动作名(如 collect.collect)
 * @param {object} args 动作入参
 * @returns {null|{liquidId: string, rounds: Array<{toMl: number, fromMl: number}>,
 *   roundsTotal: number, roundsShown: number, perRoundMl: number,
 *   real: {pump: number, transfer: number, settle: number},
 *   demo: {pump: number, transfer: number, settle: number}}}
 */
export function resolveStationLiquidPlan(liquidSpec, action, args) {
  const spec = liquidSpec?.actions?.[action]
  if (!spec || spec.dir !== 'fill' || !args) return null

  // 单轮体积 = volumeFrom 连乘; 缺省按 1(执行器侧由动作目录 default 补齐, 这里看不到)
  const perRoundMl = (spec.volumeFrom || []).reduce((acc, key) => {
    const value = Number(args[key])
    return acc * (Number.isFinite(value) && value > 0 ? value : 1)
  }, 1)
  if (!(perRoundMl > 0)) return null

  const repeatRaw = Number(args[spec.repeatFrom])
  const roundsTotal = Number.isInteger(repeatRaw) && repeatRaw > 0 ? repeatRaw : 1
  const maxRounds = Number(spec.demoMaxRounds) || roundsTotal
  const roundsShown = Math.min(roundsTotal, maxRounds)

  const capacityMl = Number(liquidSpec.cavity?.capacityMl) || 0
  const capped = (ml) => (capacityMl > 0 ? Math.min(ml, capacityMl) : ml)
  const rounds = []
  for (let round = 1; round <= roundsShown; round += 1) {
    rounds.push({ fromMl: capped(perRoundMl * (round - 1)), toMl: capped(perRoundMl * round) })
  }

  const real = { pump: 2.1, transfer: 20, settle: 5, ...(spec.roundS || {}) }
  const demo = { pump: 1, transfer: 6, settle: 2, ...(spec.demoS || {}) }
  return {
    liquidId: String(liquidSpec.id || ''),
    rounds, roundsTotal, roundsShown, perRoundMl, real, demo,
  }
}

export class TankLiquidModel {
  /**
   * 功能: 依据 manifest 建立 8 个缸的体积通道.
   * @param {object} [config] manifest.tankLiquid; 缺省时模型静默不动
   */
  constructor(config) {
    const cfg = config || {}
    this.cavity = { ...FALLBACK_CAVITY, ...(cfg.cavity || {}) }
    this.enabled = Boolean(config && cfg.cavity)
    /** 观感放大系数: 视觉高度 = 物理高度 × 本值, 到槽口封顶. 面板 mL 不受影响. */
    this.exaggeration = Number.isFinite(cfg.exaggeration) ? cfg.exaggeration : 1
    /** 管路残留(mL): 注入量里到不了槽的那部分 */
    this.pipeHoldupMl = Number.isFinite(cfg.pipeHoldupMl) ? cfg.pipeHoldupMl : 0
    this.tankArg = cfg.tankArg || 'target_tank'
    this.actions = cfg.actions || {}

    /** 液面到槽口时的体积(mL) —— 显示体积的上限 */
    this.capacityMl = this.cavity.capacityMl || 0

    /** @type {object[]} 每缸的体积插值通道(mL) */
    this.volumes = Array.from({ length: TANK_COUNT }, () => createChannel(0))
    /** @type {(null|{action: string, dir: string, targetMl: number, startAt: number, delayS: number})[]} */
    this.active = new Array(TANK_COUNT).fill(null)
    /**
     * 该缸的当前体积是否来自动作包络.
     *
     * 用途: 动作给出的是配方体积(如 20mL × 2 趟 = 40mL), 相位锚点给出的只是
     * tankStateStyles 里的观感档位(准备中 = 槽容的 35%). 前者精确得多, 所以一旦有过
     * 动作包络, 锚点就不再往回拽 —— 否则注完液的下一拍遥测就会把 40mL 拖向 35.9mL,
     * 液面在动作结束后无端漂移一段.
     * 只有 0(空闲)/98(已排空) 这两个语义确凿的状态能清掉它: 缸真空了, 谁说了都算.
     * @type {boolean[]}
     */
    this.fromAction = new Array(TANK_COUNT).fill(false)
    /**
     * 后端已经给过权威液量 (仅仿真沙盒会给, 见 onTankVolume).
     *
     * 一旦为真, 动作包络与 Tank_State 锚点两路合成信号全部让位 —— 有真值就不该再编。
     * 真机从不调 onTankVolume, 于是恒为 false, live 行为逐字不变。
     * @type {boolean}
     */
    this.authoritative = false
    /** @type {number} 单调时钟(秒), 由 step() 累加 —— 不读 performance.now, 便于测试 */
    this.elapsed = 0
  }

  /**
   * 功能: 把一条动作事件的 args 解析成"这动作要把哪个缸的液体变成多少".
   *
   * 规则本身在模块级的 resolveLiquidPlan 里(离线近似档共用同一份, 见那里的注释).
   *
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @returns {null|{index: number, dir: string, targetMl: number, rampS: number, delayS: number}}
   */
  _resolve(action, args) {
    return resolveLiquidPlan({
      actions: this.actions,
      tankArg: this.tankArg,
      cavity: { capacityMl: this.capacityMl },
      pipeHoldupMl: this.pipeHoldupMl,
    }, action, args)
  }

  /**
   * 功能: 动作开始 —— 起一段趋向目标体积的斜坡.
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @returns {boolean} 是否被本模型接管
   */
  onActionEnter(action, args) {
    // 后端已给权威液量时不再合成 (见 onTankVolume); 仍返回 true 表示"本模型认领了
    // 这条动作", 免得调用方去找别的消费者
    if (this.authoritative) return Boolean(this._resolve(action, args))
    const plan = this._resolve(action, args)
    if (!plan) return false

    const channel = this.volumes[plan.index]
    // period 的含义见 interp.step: tau = period × ARRIVE_FACTOR, 经 tau 秒衰减到 1/e.
    // 取 rampS/(3×ARRIVE_FACTOR) 让 rampS 秒后剩余误差约 5% —— 与 TwinBindings
    // _updateMechanisms 处理 transitionS 用的是同一个换算, 两处观感一致.
    channel.period = Math.max(plan.rampS / (3 * ARRIVE_FACTOR), 0.05)
    channel.initialized = true
    this.fromAction[plan.index] = true
    this.active[plan.index] = {
      action,
      dir: plan.dir,
      targetMl: plan.targetMl,
      startAt: this.elapsed,
      delayS: plan.delayS,
    }
    // 有沉降延时的(润洗抽吸)先保持原位, 到点再由 step() 放行
    if (plan.delayS <= 0) channel.target = plan.targetMl
    return true
  }

  /**
   * 功能: 动作结束 —— 成功则吸附到终值, 失败则停在当前液位.
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @param {string} [status] 结束状态(DONE 之外都按"停在原地"处理)
   * @returns {boolean} 是否被本模型接管
   */
  onActionDone(action, args, status) {
    if (this.authoritative) return Boolean(this._resolve(action, args))
    const plan = this._resolve(action, args)
    if (!plan) return false

    const channel = this.volumes[plan.index]
    if (String(status || 'DONE').toUpperCase() === 'DONE') {
      channel.value = plan.targetMl
      channel.target = plan.targetMl
    } else {
      // 失败/中止: 液体停在当前位置, 不假装排干净了, 也不假装注满了
      channel.target = channel.value
    }
    this.active[plan.index] = null
    return true
  }

  /**
   * 功能: 吃一拍 Tank_State 遥测, 作为相位锚点.
   *
   * 锚点只在"没有更好的信息"时才生效 —— 冷启动、断线重连、后端重启、纯手动 PLC 操作
   * 走的都是这条; 只要该缸有过动作包络, 精确的配方体积就压过观感档位.
   * 详见文件头的冲突规则与 fromAction 的注释.
   *
   * @param {number[]} states 长度 8 的 Tank_State 数组
   * @param {object} styles manifest.tankStateStyles
   * @returns {void}
   */
  onTankStates(states, styles) {
    // 有后端权威液量时锚点整条让位 (见 onTankVolume)
    if (this.authoritative) return
    if (!this.enabled || !Array.isArray(states)) return
    const table = styles || {}
    for (let i = 0; i < Math.min(TANK_COUNT, states.length); i += 1) {
      const state = Number(states[i]) || 0
      const channel = this.volumes[i]

      // 0=空闲 / 98=已排空: 这两个语义确凿, 无条件归零并交回锚点管辖
      if (state === 0 || state === 98) {
        channel.target = 0
        channel.value = 0
        channel.initialized = true
        // 节奏也要交回去: 通道的 period 还停在上一个动作的 rampS 上(注液可能是 12 秒),
        // 不复位的话之后由 1 Hz 遥测驱动的锚点运动会以那个慢节奏爬, 看着像迟钝.
        // 归零后 push 会按实际采样间隔重新自适应, 这里只需给回默认起点.
        channel.period = DEFAULT_SAMPLE_PERIOD
        channel.lastStamp = 0
        this.active[i] = null
        this.fromAction[i] = false
        continue
      }

      // 动作在途 或 体积来自已完成的动作: 锚点一律不上手, 免得把液面往观感档位拽
      if (this.active[i] || this.fromAction[i]) continue

      const style = table[String(state)] || table.default || { level: 0 }
      push(channel, clamp(style.level ?? 0, 0, 1) * this.capacityMl)
    }
  }

  /**
   * 功能: 吃后端**权威**液量 (仿真沙盒的 tank_liquid 事件), 并从此关掉包络合成.
   *
   * 为什么要有这条: 动作包络与 Tank_State 锚点两路信号都是**推的**(文件头第三段
   * 明写"时长不是真实流量"), 真机上没别的可用 —— 上位机拿不到任何流量反馈。而仿真
   * 沙盒里缸液量是后端按"泵排出量 × 进液阀开合"积出来的真值, 有真值就不该再合成。
   *
   * **live 零回归**靠"真机从不调本方法": 不调 -> authoritative 恒 false -> 包络与锚点
   * 逐字按今天的规则走。这与板层 coverage 字段是同一条护栏形制, 测试里有专门的用例。
   *
   * @param {object} payload {tank: 1..8, volume_ml: number} —— 缸号是 1 基 (后端口径)
   * @returns {void}
   */
  onTankVolume(payload) {
    if (!this.enabled) return
    const index = Number(payload?.tank) - 1
    const ml = Number(payload?.volume_ml)
    if (!Number.isInteger(index) || index < 0 || index >= TANK_COUNT) return
    if (!Number.isFinite(ml)) return
    this.authoritative = true
    // 权威值直接就位而不做插值: 后端 10Hz 推, 已经比任何插值都密; 再插一层只会滞后
    const channel = this.volumes[index]
    channel.target = Math.max(0, ml)
    channel.value = Math.max(0, ml)
    channel.initialized = true
    this.active[index] = null
    this.fromAction[index] = false
  }

  /**
   * 功能: 按帧推进所有通道.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  step(delta) {
    this.elapsed += delta
    for (let i = 0; i < TANK_COUNT; i += 1) {
      const running = this.active[i]
      // 沉降延时到点后才放行目标值(润洗抽吸: 先静置 settle_s 再抽)
      if (running && running.delayS > 0 && this.elapsed - running.startAt >= running.delayS) {
        this.volumes[i].target = running.targetMl
        running.delayS = 0
      }
      step(this.volumes[i], delta)
      if (this.volumes[i].value < 0) this.volumes[i].value = 0
    }
  }

  /**
   * 功能: 取某个缸的当前体积(mL) —— 面板显示用的真实值, 不含观感放大.
   * @param {number} index 缸下标(0 基)
   * @returns {number} 体积 mL
   */
  volumeMl(index) {
    const channel = this.volumes[index]
    return channel ? Math.max(0, channel.value) : 0
  }

  /**
   * 功能: 取某个缸的液面缩放比 0~1 —— 三维缩放 scale.y 用.
   *
   * 换算本身在模块级的 levelFromMl 里(离线链共用同一份, 见那里的注释).
   *
   * @param {number} index 缸下标(0 基)
   * @returns {number} 0~1
   */
  level(index) {
    if (!this.enabled) return 0
    return levelFromMl(this.cavity, this.volumeMl(index), this.exaggeration)
  }

  /**
   * 功能: 取 8 个缸的体积快照(mL), 供 useTwinScene 低频桥接给面板.
   * @returns {number[]} 长度 8
   */
  snapshotMl() {
    return this.volumes.map((_, i) => Math.round(this.volumeMl(i) * 10) / 10)
  }
}
