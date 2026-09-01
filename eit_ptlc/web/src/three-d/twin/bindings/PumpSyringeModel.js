/**
 * 功能: 三台注射泵(润泽 SY-03B)的柱塞位置模型 —— 把动作事件的相位脚本画成一条连续的
 *       柱塞位移曲线, 供三维平移柱塞组、缩放筒内液柱, 供面板显示当前抽取体积 mL.
 *
 * 单自由度: 柱塞位移与筒内液面高度是**同一个量** —— 阀头在下(本机三台泵均倒装), 柱塞
 * 上行即吸液, 液柱同步变长, 二者永远同相. 所以每台泵只有一个插值通道(单位 mL),
 * plungerMm / level / volumeMl 都是它的纯函数. 这比展缸简单一层: 展缸的截面积要体素
 * 实测才能由体积反算高度, 针筒则是标定过的量具 —— 25 mL / 6000 步 / 60 mm 行程,
 * 1 mL 恒等于 2.4 mm.
 *
 * 与 TankLiquidModel 的三处实质差异(照抄它之前先看这里):
 *   1. **无遥测锚点.** 展缸有 Tank_State 1Hz 相位广播当兜底, 泵没有任何对等物 ——
 *      config/plc_nodes.yaml 里没有一个柱塞位置回读通道(Sampling_band_end_position 是
 *      下发的目标步数, 不是反馈; PLC 内部用 /4? 查真位但不镜像给上位机). 唯一确凿的
 *      绝对位置事件是各 *.init 里的 DT `Z` 指令(活塞归零), 已作为 home 相位进动作表.
 *   2. **动作是相位脚本, 不是单一目标.** 展缸泵一趟 "吸满→打空" 起点终点都是 0, 单目标
 *      模型下柱塞一动不动 —— 而往复运动恰是这里唯一要看的东西.
 *   3. **位置是累加态.** sampling.prep 停在气隙位、sampling.aspirate 在其上做相对叠加、
 *      spot_band_layer 再打回去, 是一条跨越三四个动作的连续行程. 因此有 committed(逻辑位)
 *      与 channel.value(动画位)两个量, 相对相位一律基于 committed 推算, **绝不读动画位**
 *      —— 否则动作首尾相接时会按"动画还没走完的位置"起算, 一次就漂掉几 mL.
 *
 * 性能: 与 TwinFeed 同一约定, 本文件所有状态都是普通对象, 绝不进 Vue 响应式.
 */
import { ARRIVE_FACTOR, clamp, createChannel, step } from './interp.js'

/** 没有 manifest.pumpSyringe 时的退化参数: 只保证不炸, 柱塞不会动 */
const FALLBACK = { syringeMl: 25, strokeMm: 60 }

/**
 * 展开后的相位总数上限.
 *
 * cleaning_count / mix_count 这类次数由配方给, 现场填过 20 —— 20 轮 × 4 相位 = 80 个,
 * 观感上与 32 个没有任何区别, 却要多算一串. 超了就压缩重复次数(真实次数仍进 snapshot
 * 供面板显示), 不是截断丢弃.
 */
const MAX_PHASES = 64

/** 相位到位判据: 距目标小于量程的 1%, 与 rampS 的"95% 到位"语义配套 */
const ARRIVE_RATIO = 0.01

/** 换阀的名义时长(秒). 实物切液路很快, 与柱塞那种十几秒的行程不是一个量级 */
const VALVE_RAMP_S = 0.4

export class PumpSyringeModel {
  /**
   * 功能: 依据 manifest 建立每台泵的体积通道.
   * @param {object} [config] manifest.pumpSyringe; 缺省时模型静默不动
   */
  constructor(config) {
    const cfg = config || {}
    this.specs = Array.isArray(cfg.pumps) ? cfg.pumps : []
    this.enabled = this.specs.length > 0
    this.syringeMl = Number.isFinite(cfg.syringeMl) ? cfg.syringeMl : FALLBACK.syringeMl
    this.strokeMm = Number.isFinite(cfg.strokeMm) ? cfg.strokeMm : FALLBACK.strokeMm
    this.actions = cfg.actions || {}
    this.count = this.specs.length
    /**
     * 步/mL. SY-03B 是 0.01mm/步, 6000 步 = 60mm 满行程 = 25 mL ⇒ **240 步/mL**.
     * 这个数被上位机的离线单测钉死(develop 1.0 mL → `A240`), 两侧同源于 rig_map。
     */
    this.stepsPerMl = (Number(cfg.stepsPerStroke) || 6000) / (this.syringeMl || 25)
    /** @type {object} 构建期从 app.yaml 快照的各工位 V/M 档(兜底用) */
    this.speedSnapshot = cfg.speeds || {}
    /** @type {object} 实时拉到的 config.pump(优先于快照); 由 setLiveSpeeds 注入 */
    this.liveSpeeds = {}

    /** @type {Map<string, number>} 泵 id -> 下标 */
    this.byId = new Map(this.specs.map((spec, i) => [spec.id, i]))

    /** @type {object[]} 每泵一个 mL 通道 —— 柱塞位移与液柱长度共用它(单自由度) */
    this.plungers = this.specs.map(() => createChannel(0))
    /**
     * 每泵一个阀位通道(单位: 圈).
     *
     * 用**累计圈数**而不是绝对角度, 是为了让 6→1 这种跨零切换走最短路径而不是倒转 5 格:
     * 每次换口时把目标折算到"离当前值最近的那个等价角", 通道本身仍是单调连续的实数.
     *
     * 初值取 1 号口的角度而不是 0 —— 实物阀头的接口全挤在下半圈, 0° 那边是接针筒的平口,
     * 根本没有口; 从 0 起手的话开机第一眼指针指着一个不存在的位置.
     * @type {object[]}
     */
    this.valves = this.specs.map((_, i) => createChannel(this._portTurns(i, 1) ?? 0))
    /** @type {(number|null)[]} 当前选中的口号(1 基); null = 还没有任何动作指定过 */
    this.ports = new Array(this.count).fill(null)
    /** @type {number[]} 逻辑位(mL): 只在相位边界与动作 done 跃迁; 相对相位基于它 */
    this.committed = new Array(this.count).fill(0)
    /** @type {boolean[]} 位置是否可信: 冷启动/断线重连后为 false, 面板显 "—" 而不是骗人的 0 */
    this.known = new Array(this.count).fill(false)
    /** @type {(null|object)[]} 在途包络 */
    this.active = new Array(this.count).fill(null)
    /**
     * 真实位置反馈的新鲜期截止 (elapsed 秒)。仿真沙盒 10Hz 推 pump_state 时,
     * 包络退位成只读节拍器 (相位推进与 phaseInfo 读数照常, 但不写通道) ——
     * 反馈停发 1s 后自然回落包络行为; live 页收不到反馈, 恒为 0, 行为不变。
     * @type {number[]}
     */
    this.feedbackFreshUntil = new Array(this.count).fill(0)
    /** 实时流是否已断: 断了就冻结末态, 绝不回零(与全仓一致) */
    this.frozen = false
    /** @type {number} 单调时钟(秒), 由 step() 累加 —— 不读 performance.now, 便于测试 */
    this.elapsed = 0
    /** @type {Set<string>} 已警告过的动作名, 去重防刷屏 */
    this._warned = new Set()
  }

  /**
   * 功能: 按动作表的 pump 段决定这条事件属于哪台泵.
   *
   * 缸号路由查每台泵自己的 tankGroup, **不重算 (target_tank-1)//4+1** —— 那个算术的
   * 权威在 tools/pump/develop_translator.py, 前端再抄一份就是两个真源, 改缸组必漂.
   *
   * @param {object} pumpSpec 动作表里的 pump 段
   * @param {object} args 动作入参
   * @returns {number} 泵下标; -1 表示不接管
   */
  _pumpIndex(pumpSpec, args) {
    if (!pumpSpec) return -1
    if (pumpSpec.from === 'fixed') {
      const index = this.byId.get(pumpSpec.id)
      return Number.isInteger(index) ? index : -1
    }
    if (pumpSpec.from === 'tankGroup') {
      const tank = Number(args?.[pumpSpec.arg])
      if (!Number.isInteger(tank)) return -1
      return this.specs.findIndex((spec) => (spec.tankGroup || []).includes(tank))
    }
    return -1
  }

  /**
   * 功能: 求一组入参之和(缺项走 fallback).
   *
   * 是**求和**不是连乘 —— 展缸那边 volumeFrom 是"体积 × 趟数"故用乘法且缺项按 1 兜底;
   * 这里 flush 是三段体积相加、aspirate 是气隙 + 样品, 缺项按 0 会把峰值直接抹平, 所以
   * 动作表里给了 fallback.
   *
   * @param {object} source {add: string[], fallback?: number[]}
   * @param {object} args 动作入参
   * @returns {null|number} 全部缺失且无兜底时为 null
   */
  _sum(source, args) {
    const keys = source?.add || []
    let total = 0
    let hit = 0
    keys.forEach((key, i) => {
      const raw = Number(args?.[key])
      if (Number.isFinite(raw) && raw > 0) {
        total += raw
        hit += 1
        return
      }
      const fallback = Number(source?.fallback?.[i])
      if (Number.isFinite(fallback) && fallback > 0) total += fallback
    })
    if (hit === 0 && !(total > 0)) return null
    return total
  }

  /**
   * 功能: 把一个相位算成绝对目标体积(mL).
   * @param {object} phase 相位定义
   * @param {object} args 动作入参
   * @param {number} prevMl 前一相位的终点(相对相位的起算点)
   * @returns {null|number} null = 本相位跳过
   */
  _phaseTarget(phase, args, prevMl) {
    if (phase.op === 'home') return 0
    // aspirate 抽(柱塞上行, 体积增); dispense 排(体积减)
    const dir = phase.op === 'dispense' ? -1 : 1

    if (Number.isFinite(phase.to)) return clamp(phase.to, 0, this.syringeMl)
    if (Number.isFinite(phase.by)) return clamp(prevMl + dir * phase.by, 0, this.syringeMl)

    if (phase.toFrom) {
      const amount = this._sum(phase.toFrom, args)
      if (amount === null) return phase.skipIfMissing ? null : clamp(prevMl, 0, this.syringeMl)
      return clamp(amount, 0, this.syringeMl)
    }
    if (phase.byFrom) {
      const amount = this._sum(phase.byFrom, args)
      if (amount === null) return phase.skipIfMissing ? null : clamp(prevMl, 0, this.syringeMl)
      return clamp(prevMl + dir * amount, 0, this.syringeMl)
    }
    return null
  }

  /**
   * 功能: 注入实时拉到的 config.pump(GET /api/config/pump 的 values).
   *
   * 与后端 tools/pump/profiles.py 的回退链保持同形: 动作入参 > config.pump 实时值 >
   * 构建期快照。拉不到就不调用本方法, 自动退到快照。
   *
   * @param {object} values {工位: {档名: 数值}}
   * @returns {void}
   */
  setLiveSpeeds(values) {
    this.liveSpeeds = values && typeof values === 'object' ? values : {}
  }

  /**
   * 功能: 取某台泵某一档的速度值(步/秒)或延时(ms).
   * @param {number} index 泵下标
   * @param {string} key 档名, 如 asp_speed / spot_disp_speed / step_delay
   * @param {object} [args] 动作入参(最高优先级)
   * @returns {number|null} 取不到返回 null, 调用方退回 rampS
   */
  _speedOf(index, key, args) {
    if (!key) return null
    const fromArgs = Number(args?.[key])
    if (Number.isFinite(fromArgs) && fromArgs > 0) return fromArgs
    const station = this.specs[index]?.speedStation
    if (!station) return null
    for (const table of [this.liveSpeeds, this.speedSnapshot]) {
      const value = Number(table?.[station]?.[key])
      if (Number.isFinite(value) && value > 0) return value
    }
    return null
  }

  /**
   * 功能: 按 PLC 的 V/M 算一个相位的真实时长.
   *
   * 换算真源在上位机 `tools/pump/mvp_staged_clean.py:106`:
   *     asp_secs = total_steps / asp_speed + delay / 1000
   * V 是**步/秒**, M 是每段移动后的稳液延时(ms)。
   *
   * 取不到 V 时退回动作表里写死的 rampS —— 那是老行为, 不准但不会停摆。
   *
   * @param {number} index 泵下标
   * @param {object} phase 动作表相位
   * @param {number} deltaMl 该相位的体积变化量(绝对值)
   * @param {object} args 动作入参
   * @returns {{rampS: number, holdS: number, speed: number|null}}
   */
  _phaseTiming(index, phase, deltaMl, args) {
    const fallback = Number(phase.rampS) > 0 ? Number(phase.rampS) : 3
    const speed = this._speedOf(index, phase.speed, args)
    const delayMs = this._speedOf(index, 'step_delay', args)
    const holdS = Number.isFinite(delayMs) && delayMs > 0 ? delayMs / 1000 : 0
    if (!speed || !(deltaMl > 0)) return { rampS: fallback, holdS, speed }
    return { rampS: (deltaMl * this.stepsPerMl) / speed, holdS, speed }
  }

  /**
   * 功能: 口号 -> 指针该停的圈数(1 圈 = 360°).
   *
   * 优先用 manifest 带下来的 valvePortAngles —— 实物阀头的接口**全挤在下半圈**, 不是
   * 360° 均布. 仍按 (port-1)/N 算的话指针会指到接针筒的平口那侧, 一个口都没有.
   * 缺这一项(旧 manifest / 没建几何的泵)才退回均布, 保持老行为不回归.
   *
   * @param {number} index 泵下标
   * @param {number} port 口号(1 基)
   * @returns {number|null} 圈数; null = 这台泵没有阀位可言
   */
  _portTurns(index, port) {
    const spec = this.specs[index]
    const total = Number(spec?.valvePorts) || 0
    if (!(total > 0) || !Number.isInteger(port) || port < 1 || port > total) return null
    const angles = spec?.valvePortAngles
    if (Array.isArray(angles) && angles.length === total && Number.isFinite(angles[port - 1])) {
      return angles[port - 1] / 360
    }
    return (port - 1) / total
  }

  /**
   * 功能: 把相位声明的 port 解析成具体口号.
   * @param {number|string|undefined} port 字面口号 / "output" / 缺省
   * @param {number} index 泵下标
   * @returns {number|null} null = 这一相位不换阀
   */
  _resolvePort(port, index) {
    if (port === 'output') return this.specs[index]?.outputPort ?? null
    const value = Number(port)
    if (!Number.isInteger(value) || value < 1) return null
    const total = Number(this.specs[index]?.valvePorts) || 0
    // 越界的口号一律当没写 —— 转到一个不存在的口比不转更糟
    return total > 0 && value > total ? null : value
  }

  /**
   * 功能: 把动作表的相位脚本(含 repeatFrom / loop)一次性摊平成绝对目标序列.
   *
   * 为什么在 enter 时就摊平而不是运行时求值: onActionDone 要能直接取末项当吸附值 ——
   * 真实动作往往比 rampS 之和长得多(spot_band_layer 实测 500~700s), 那时动画早已停在
   * 终点, 吸附是空操作; 反之泵速拉满时会一把拉到终点, 那恰是物理事实.
   *
   * @param {object} spec 动作表条目
   * @param {object} args 动作入参
   * @param {number} startMl 起算体积(必须是 committed, 不是动画位)
   * @param {number} index 泵下标(解析 "output" 口号要用)
   * @returns {{phases: object[], outerRepeat: number, innerRepeat: number}}
   */
  _expand(spec, args, startMl, index, maxPhases = MAX_PHASES) {
    const countOf = (key) => {
      const raw = Number(args?.[key])
      return Number.isInteger(raw) && raw > 0 ? raw : 1
    }
    const outerWanted = spec.repeatFrom ? countOf(spec.repeatFrom) : 1
    const innerWanted = spec.loop?.repeatFrom ? countOf(spec.loop.repeatFrom) : (spec.loop ? 1 : 0)

    const outerLen = (spec.phases || []).length
    const innerLen = (spec.loop?.phases || []).length
    // 压缩重复次数而不是截断相位: 保住"往复很多次"的观感, 只是次数少几轮.
    // maxPhases 可由调用方收紧(离线片段/近似档的演示预算比实时台小得多), 缺省仍是 MAX_PHASES.
    let outer = outerWanted
    let inner = innerWanted
    while (outer * outerLen + inner * innerLen > maxPhases && (outer > 1 || inner > 1)) {
      if (inner * innerLen >= outer * outerLen && inner > 1) inner -= 1
      else if (outer > 1) outer -= 1
      else break
    }

    const phases = []
    let prev = startMl
    const push = (list) => {
      for (const phase of list) {
        const target = this._phaseTarget(phase, args, prev)
        if (target === null) continue
        // 时长按 PLC 的 V/M 算真值, 不再用动作表里写死的 rampS(那只是取不到 V 时的兜底).
        // 展开泵吸 20mL @V100 = 48s, 实机就是 48s —— 实时台是镜像真机的, 快了反而先到位干等.
        const timing = this._phaseTiming(index, phase, Math.abs(target - prev), args)
        phases.push({
          targetMl: target,
          rampS: timing.rampS,
          // 实机每段移动后会停 M 毫秒稳液; 连续动画看不出"一段一段"的节奏
          holdS: timing.holdS,
          speed: timing.speed,
          op: phase.op || null,
          // "output" = 该泵的打液出口(每台不同, 由 manifest 的 outputPort 给);
          // 数字 = 字面口号; 缺省 = 这一相位不换阀(宁可不转也不编一个口号)
          port: this._resolvePort(phase.port, index),
        })
        prev = target
      }
    }
    for (let r = 0; r < outer; r += 1) push(spec.phases || [])
    for (let r = 0; r < inner; r += 1) push(spec.loop?.phases || [])
    // outerUsed/innerUsed = 压缩后真正编入的轮数; 与 wanted 不等即"演示压缩了轮数",
    // 调用方(离线编译/近似档)据此写 flowNotes, 面板显示仍用 wanted
    return {
      phases,
      outerRepeat: outerWanted,
      innerRepeat: innerWanted,
      outerUsed: outer,
      innerUsed: inner,
    }
  }

  /**
   * 功能: 把一条动作事件解析成"哪台泵按什么相位脚本走".
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @returns {null|{index: number, phases: object[], outerRepeat: number, innerRepeat: number}}
   */
  _resolve(action, args) {
    const spec = this.actions[action]
    if (!spec) return null
    const index = this._pumpIndex(spec.pump, args || {})
    if (index < 0) return null
    // 起算点必须是逻辑位: 动作首尾相接时动画常常还没走完
    const plan = this._expand(spec, args || {}, this.committed[index], index)
    if (!plan.phases.length) {
      if (!this._warned.has(action)) {
        this._warned.add(action)
        console.warn(`[pumpSyringe] 动作 ${action} 命中动作表但展不出任何相位, 入参可能改名了`)
      }
      return null
    }
    return { index, ...plan }
  }

  /**
   * 功能: 动作开始 —— 起一段相位脚本.
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @returns {boolean} 是否被本模型接管
   */
  onActionEnter(action, args) {
    if (!this.enabled) return false
    const plan = this._resolve(action, args)
    if (!plan) return false
    const channel = this.plungers[plan.index]
    channel.initialized = true
    this.known[plan.index] = true
    this.active[plan.index] = {
      action,
      phases: plan.phases,
      phase: -1,
      outerRepeat: plan.outerRepeat,
      innerRepeat: plan.innerRepeat,
      startAt: this.elapsed,
    }
    this._enterPhase(plan.index, 0)
    return true
  }

  /**
   * 功能: 动作结束 —— DONE 吸附到脚本终值, 其余停在当前位置.
   *
   * 失败/中止时 committed 也跟着落到当前值: 否则下一个相对相位会从一个从未到达的位置
   * 起算, 越错越远.
   *
   * @param {string} action 动作名
   * @param {object} args 动作入参
   * @param {string} [status] 结束状态
   * @returns {boolean} 是否被本模型接管
   */
  onActionDone(action, args, status) {
    if (!this.enabled) return false
    const plan = this._resolve(action, args)
    if (!plan) return false
    const index = plan.index
    const channel = this.plungers[index]
    if (this._feedbackFresh(index)) {
      // 反馈新鲜期: 位置以真实反馈为准, done 只收包络账 (不跳变通道)
      this.committed[index] = channel.target
    } else if (String(status || 'DONE').toUpperCase() === 'DONE') {
      const end = plan.phases[plan.phases.length - 1].targetMl
      channel.value = end
      channel.target = end
      this.committed[index] = end
    } else {
      channel.target = channel.value
      this.committed[index] = channel.value
    }
    this.active[index] = null
    return true
  }

  /**
   * 功能: 切到第 n 个相位.
   *
   * period 的换算与 TankLiquidModel 和 TwinBindings._updateMechanisms 是同一个公式:
   * tau = period × ARRIVE_FACTOR, 取 rampS/(3×ARRIVE_FACTOR) 让 rampS 秒后残差约 5%.
   * 三处必须一致, 否则同一台机器上不同部件的"到位感"对不上.
   *
   * @param {number} index 泵下标
   * @param {number} n 相位序号
   * @returns {void}
   */
  _enterPhase(index, n) {
    const run = this.active[index]
    if (!run) return
    const phase = run.phases[n]
    if (!phase) return
    // 相位边界提交: 到这里为止的目标都已经是"逻辑上到过"的位置
    if (n > 0) this.committed[index] = run.phases[n - 1].targetMl
    run.phase = n
    run.holdUntil = 0                 // 本相位还没到位, 谈不上停顿
    run.startedAt = this.elapsed
    // 反馈新鲜期内包络不写通道 (位置归真实反馈驱动); 相位推进/读数照常
    if (!this._feedbackFresh(index)) {
      const channel = this.plungers[index]
      channel.period = Math.max(phase.rampS / (3 * ARRIVE_FACTOR), 0.05)
      channel.target = phase.targetMl
    }
    if (phase.port) this._selectPort(index, phase.port)
  }

  /**
   * 功能: 把阀指针切到某个口.
   *
   * 目标用**离当前值最近的等价角**: 阀位通道存的是累计圈数, 6 口阀从 6 号切 1 号若按
   * 绝对值算要倒转 5/6 圈, 而实物走的是最短路径(1/6 圈). 折算一次即可, 通道本身仍连续.
   *
   * @param {number} index 泵下标
   * @param {number} port 口号(1 基)
   * @returns {void}
   */
  _selectPort(index, port) {
    const want = this._portTurns(index, port)
    if (want === null) return
    this.ports[index] = port
    const channel = this.valves[index]
    const current = channel.value
    // 取与 current 相差最小的那个 want + k 圈
    const turns = Math.round(current - want)
    channel.target = want + turns
    channel.initialized = true
    // 切阀是快动作: 0.4s 到位, 比柱塞快得多
    channel.period = Math.max(VALVE_RAMP_S / (3 * ARRIVE_FACTOR), 0.05)
  }

  /**
   * 功能: 吃一帧真实位置反馈(协议 §7c `pump_state`, 目前只有仿真沙盒发).
   *
   * 有反馈优先, 但**不杀包络**(2026-08-09 教训: 曾 active=null 永久掐死相位推进,
   * 且没设 channel.period —— 通道继承包络遗留的十几秒 tau, 10Hz 反馈流看着纹丝不动):
   *   · 通道目标直设反馈值, period 压到 0.1 (tau≈0.125s, 匹配 10Hz 采样);
   *   · 包络保留: 相位推进与 phaseInfo 读数照常, 只是新鲜期内不写通道
   *     (_enterPhase/onActionDone 各有对应豁免);
   *   · 反馈停发 1s 后自然回落包络行为 —— live 页收不到反馈, 一行不变.
   *
   * @param {object} event {id, plunger_ml, valve_port}
   * @returns {void}
   */
  pushFeedback(event) {
    if (!this.enabled) return
    const index = this.byId.get(event?.id)
    if (!Number.isInteger(index)) return
    const ml = Number(event?.plunger_ml)
    if (Number.isFinite(ml)) {
      const channel = this.plungers[index]
      channel.target = clamp(ml, 0, this.syringeMl)
      channel.initialized = true
      // 反馈采样约 10Hz: tau 必须小于采样间隔量级, 否则永远追不上流
      channel.period = 0.1
      this.committed[index] = clamp(ml, 0, this.syringeMl)
      this.known[index] = true
      this.feedbackFreshUntil[index] = this.elapsed + 1.0
    }
    const port = Number(event?.valve_port)
    if (Number.isInteger(port) && port >= 1) this._selectPort(index, port)
  }

  /**
   * 功能: 该泵此刻是否处于真实反馈新鲜期(通道归反馈驱动, 包络只读).
   * @param {number} index 泵下标
   * @returns {boolean}
   */
  _feedbackFresh(index) {
    return this.elapsed < (this.feedbackFreshUntil[index] || 0)
  }

  /**
   * 功能: 按帧推进所有泵.
   * @param {number} delta 帧间隔(秒)
   * @returns {void}
   */
  step(delta) {
    if (!this.enabled) return
    this.elapsed += delta
    if (this.frozen) return
    const arrive = this.syringeMl * ARRIVE_RATIO
    for (let i = 0; i < this.count; i += 1) {
      const channel = this.plungers[i]
      const run = this.active[i]
      if (run && Math.abs(channel.target - channel.value) < arrive
          && run.phase + 1 < run.phases.length) {
        // 到位后先停 M 毫秒再进下一相 —— 实机每段移动后都要停下稳液, 连着跑就少了
        // "一段一段"的节奏. holdUntil 在到位那一帧才落下来, 之后到点才推进.
        const hold = Number(run.phases[run.phase]?.holdS) || 0
        if (hold > 0 && !run.holdUntil) run.holdUntil = this.elapsed + hold
        if (!run.holdUntil || this.elapsed >= run.holdUntil) {
          this._enterPhase(i, run.phase + 1)
        }
      }
      step(channel, delta)
      channel.value = clamp(channel.value, 0, this.syringeMl)
      step(this.valves[i], delta)
    }
  }

  /**
   * 功能: 阀指针盘应转到的角度(弧度), 供三维绕进深轴写旋转.
   * @param {number} index 泵下标
   * @returns {number}
   */
  valveAngle(index) {
    const channel = this.valves[index]
    return channel ? channel.value * Math.PI * 2 : 0
  }

  /**
   * 功能: 当前选中的阀口号(1 基); null = 还没有任何动作指定过.
   * @param {number} index 泵下标
   * @returns {number|null}
   */
  valvePort(index) {
    return this.ports[index] ?? null
  }

  /**
   * 功能: 丝杆应转到的角度(弧度), 供三维绕自身竖轴写旋转.
   *
   * 梯形丝杆导程 6mm、行程 60mm ⇒ 满行程 10 圈, 圈数由 manifest 的 leadTurnsPerStroke
   * 给(几何那边同源于 lead_pitch)。角度直接跟 level 走, 不另设通道 —— 丝杆与柱塞是
   * 刚性传动, 本来就是同一个自由度。
   *
   * @param {number} index 泵下标
   * @returns {number}
   */
  leadAngle(index) {
    const turns = Number(this.specs[index]?.leadTurnsPerStroke) || 0
    return this.level(index) * turns * Math.PI * 2
  }

  /**
   * 功能: 当前相位的读数(面板用): 吸/排、口号、速度、剩余秒、目标体积.
   * @param {number} index 泵下标
   * @returns {object|null} 没有在途动作时为 null
   */
  phaseInfo(index) {
    const run = this.active[index]
    const phase = run?.phases?.[run.phase]
    if (!phase) return null
    const channel = this.plungers[index]
    const remainMl = Math.abs(phase.targetMl - channel.value)
    // 剩余时间按**当前这一相位自己的速度**折算, 不拿总时长按比例摊 —— 各相位速度可以不同
    const remainS = phase.speed && this.stepsPerMl
      ? (remainMl * this.stepsPerMl) / phase.speed
      : null
    return {
      op: phase.op,
      index: run.phase + 1,
      count: run.phases.length,
      speed: phase.speed ?? null,
      targetMl: phase.targetMl,
      remainS,
      // 到位后正停在 M 延时里
      holding: Boolean(run.holdUntil && this.elapsed < run.holdUntil),
    }
  }

  /**
   * 功能: 当前抽取体积(mL).
   * @param {number} index 泵下标
   * @returns {number}
   */
  volumeMl(index) {
    const channel = this.plungers[index]
    return channel ? clamp(channel.value, 0, this.syringeMl) : 0
  }

  /**
   * 功能: 柱塞行程比例, 同时就是液柱长度比例(单自由度, 同一个数).
   * @param {number} index 泵下标
   * @returns {number} 0~1
   */
  level(index) {
    return this.syringeMl > 0 ? this.volumeMl(index) / this.syringeMl : 0
  }

  /**
   * 功能: 柱塞离零位的位移(mm), 供面板显示.
   * @param {number} index 泵下标
   * @returns {number}
   */
  plungerMm(index) {
    const stroke = Number(this.specs[index]?.strokeMm) || this.strokeMm
    return this.level(index) * stroke
  }

  /**
   * 功能: 该泵的位置是否可信.
   *
   * 与 volumeMl 分开是有意的: 冷启动/断线重连后模型算不出任何有依据的位置, 这时候
   * 显示 "0 mL" 是在骗人 —— 面板据此显 "—".
   *
   * @param {number} index 泵下标
   * @returns {boolean}
   */
  isKnown(index) {
    return Boolean(this.known[index]) && !this.frozen
  }

  /**
   * 功能: 实时流断开 —— 冻结末态并标不可信.
   *
   * 清 active 是必须的: 断流时 TwinFeed 会清掉 _pendingNodeArgs, 重连后那条 done 拿不到
   * args, 永远不会来收尾 —— 不能指望 done 来结束包络.
   *
   * @returns {void}
   */
  markDisconnected() {
    this.frozen = true
    for (let i = 0; i < this.count; i += 1) {
      const channel = this.plungers[i]
      channel.target = channel.value
      this.active[i] = null
      this.committed[i] = channel.value
      // 阀也停在当前角度: 断流时它停在哪一口就是哪一口, 不回零也不继续转
      this.valves[i].target = this.valves[i].value
    }
  }

  /**
   * 功能: 实时流恢复 —— 位置**仍然不可信**, 直到收到下一条 *.init(Z 归零)或任一动作包络.
   * @returns {void}
   */
  markReconnected() {
    this.frozen = false
    this.known.fill(false)
  }

  /**
   * 功能: 低频快照, 供 useTwinScene 桥接给面板与 HUD.
   *
   * 每次返回新数组新对象(不原地改), Vue 才能触发; 数值已量化过, 500ms 一拍不会因为
   * 浮点尾数抖动而无谓重渲.
   *
   * @returns {object[]}
   */
  snapshot() {
    return this.specs.map((spec, i) => ({
      id: spec.id,
      label: spec.label || spec.id,
      station: spec.station,
      dtAddr: spec.dtAddr,
      valve: spec.valve,
      rigged: Boolean(spec.rigged),
      volumeMl: Math.round(this.volumeMl(i) * 100) / 100,
      plungerMm: Math.round(this.plungerMm(i) * 10) / 10,
      level: this.level(i),
      valvePort: this.valvePort(i),
      valvePorts: Number(spec.valvePorts) || 0,
      known: this.isKnown(i),
      busy: Boolean(this.active[i]),
      action: this.active[i]?.action || null,
      // 当前相位读数(吸/排 · 速度 · 剩余秒 · 目标体积), 没在途时为 null
      phase: this.phaseInfo(i),
      // 恒真: 柱塞位置永远没有传感器确认, 不是"暂时没收到反馈"
      estimated: true,
      stale: this.frozen,
    }))
  }
}

/**
 * 功能: 把一条泵动作展开成相位计划 —— 离线消费方(demo/flowSim 近似档)的共享入口.
 *
 * 相位数学(目标体积/repeat 压缩/真实时长/口号解析)只存在本文件一份; 这里用一个一次性
 * 模型实例把内部方法包成纯函数, 免得 flowSim 抄一遍 _expand 然后两边各自漂.
 * (片段编译器 clip_compiler.emit_pump_syringe 是它的 Python 镜像, 三方同源于
 * manifest.pumpSyringe.actions —— 改动作表不需要动这三处代码.)
 *
 * @param {object} config manifest.pumpSyringe
 * @param {string} action 动作名(如 develop.fill)
 * @param {object} args 动作入参
 * @param {number} [startMl] 起算体积(跨动作累加时传上一动作的终点)
 * @param {object} [options]
 * @param {number} [options.maxPhases] 相位预算(演示档比实时台的 64 小得多)
 * @returns {null|{pumpId: string, index: number, rigged: boolean, phases: object[],
 *          outerRepeat: number, innerRepeat: number, outerUsed: number, innerUsed: number}}
 *          null = 该动作不驱泵/入参路由不到任何一台泵/展不出相位
 */
export function expandPumpPlan(config, action, args, startMl = 0, { maxPhases = MAX_PHASES } = {}) {
  const model = new PumpSyringeModel(config)
  if (!model.enabled) return null
  const spec = model.actions?.[action]
  if (!spec) return null
  const index = model._pumpIndex(spec.pump, args || {})
  if (index < 0) return null
  const start = Number.isFinite(Number(startMl)) ? Number(startMl) : 0
  const plan = model._expand(spec, args || {}, start, index, maxPhases)
  if (!plan.phases.length) return null
  const pumpSpec = model.specs[index]
  return {
    pumpId: pumpSpec?.id ?? null,
    index,
    rigged: Boolean(pumpSpec?.rigged && pumpSpec?.plungerNode),
    phases: plan.phases,
    outerRepeat: plan.outerRepeat,
    innerRepeat: plan.innerRepeat,
    outerUsed: plan.outerUsed,
    innerUsed: plan.innerUsed,
  }
}
