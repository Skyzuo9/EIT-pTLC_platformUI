/**
 * 功能: 状态录像的事件传输层 —— 形状与实时 WS 通道完全一致, 因此可以直接注入
 * EventStream 的 transport 口, 整条渲染链一行不动.
 *
 * 这一手是照抄仿真页的既有做法 (sim/simEventStream.js): EventStream 只是**默认**用
 * 宿主单例, transport/seeder 本来就可注入。仿真页已经证明整条
 * useTwinScene → TwinFeed → TwinBindings → MachineStateDriver 能跑在第二个事件源上,
 * 回放不过是再来一次。
 *
 * 与实时通道的唯一语义差别是"现在"由谁定义: 这里由 ReplayClock 说了算, 并经
 * TwinFeed.now 注入下游全部 staleness/插值判定 (见 TwinFeed 构造函数注释)。
 */
import { api as defaultApi } from '../../api.js'
import { ReplayClock } from './ReplayClock.js'
import { framesToEvents, keyframeToSeed } from './replayEvents.js'
import {
  MAX_DRAIN_S, SCRUB_EPS_S, planScrub, scrubTimeScale,
} from './timelineViewModel.js'

/** 擦洗预览的最小间隔(ms): 即便链路是 2 ms, 也不该让宿主的清场一秒跑十几次。 */
const SCRUB_MIN_INTERVAL_MS = 60

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/** 预取窗口(秒): 播放头前方至少备好这么多数据才不至于卡顿。 */
const PREFETCH_S = 20
/** 预取触发余量(秒): 剩余不足这么多就去拉下一窗。 */
const PREFETCH_MARGIN_S = 6

export class ReplayChannel {
  /**
   * @param {object} [options]
   * @param {object} [options.api] 注入 API 替身 (离线单测)
   * @param {string} [options.sessionId] 限定会话; 省略则跨会话按时间检索
   */
  constructor({ api = defaultApi, sessionId = null } = {}) {
    this.api = api
    this.sessionId = sessionId
    this.clock = new ReplayClock()
    this.listeners = new Set()
    this.statusListeners = new Set()

    /** @type {object[]} 已预取、尚未投喂的事件 (按 ts 升序) */
    this._pending = []
    /** 已预取到的时间上界 */
    this._loadedTo = 0
    /** 上一次处理过的 clock.epoch —— 变了就说明发生了不连续跳转 */
    this._epoch = -1
    this._seeding = false
    this._loading = false
    this._lastError = ''
    /**
     * 待落地的清场种子 —— 由宿主在**清场的同一帧**里投下去。
     * 刻意不在 seek 里直接 _emit: 那样顺序就取决于 await 是否恰好让出一帧(见 seek 注释)。
     * @type {{token: number, events: object[], scalars: object}|null}
     */
    this.pendingSeed = null
    /** 擦洗预览态: 宿主据此保留板面刀路缓存, 免得每拖一下就逐板重新取数 */
    this.previewing = false
    /** 擦洗单航班: 在飞一个, 排队最多一个(后来者直接覆盖) */
    this._scrubInFlight = false
    this._scrubQueued = null
    /** 每次 seek 自增, 宿主据此调用 feed.resetForSeek() + machine.home() */
    this.resetToken = 0
    /**
     * 是否处于回放态。宿主据此屏蔽实时事件并切换"现在"的定义。
     *
     * 用一个开关而不是重挂整个场景, 是因为整机 GLB 有 14.8 MB 且资产端点带
     * no-store —— 切一次模式就重下一次模型, 对用户是几秒钟的黑屏。
     */
    this.active = false
  }

  // -- EventStream transport 契约 ------------------------------------

  onEvent(handler) {
    this.listeners.add(handler)
    return () => this.listeners.delete(handler)
  }

  onStatus(handler) {
    this.statusListeners.add(handler)
    handler(true)
    return () => this.statusListeners.delete(handler)
  }

  _emit(event) {
    for (const handler of this.listeners) handler(event)
  }

  _emitStatus(connected) {
    for (const handler of this.statusListeners) handler(connected)
  }

  /** 供 TwinFeed.now 注入: 绝对纪元毫秒。 */
  now = () => this.clock.nowMs()

  // -- 生命周期 ------------------------------------------------------

  /** 拉取可回放区间并把播放头停到起点。 */
  async open({ t0 = null, t1 = null } = {}) {
    try {
      const coverage = await this.api.recordingCoverage()
      const from = t0 ?? coverage.t0
      const to = t1 ?? coverage.t1
      if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) {
        this._lastError = '没有可回放的录像'
        return false
      }
      this.clock.setRange(from, to)
      this.active = true
      // seek 的成败必须往上传: 吞掉它会让 UI 认为进了回放态, 实际上一帧数据都没有,
      // 表现成"按钮变了、画面不动、只有一行英文报错", 用户根本判断不出发生了什么。
      const ok = await this.seek(from)
      if (!ok) {
        this.active = false
        return false
      }
      return true
    } catch (error) {
      this._lastError = `录像区间读取失败: ${error?.message || error}`
      return false
    }
  }

  /**
   * 功能: 跳到某时刻 —— 清场 → 关键帧播种 → 重新预取.
   *
   * 顺序不能变: 必须先让宿主 resetForSeek()(清掉机构时间戳闸门与位姿缓冲的到达时刻
   * 锁存), 再投关键帧, 否则关键帧会被那道闸门逐 id 静默丢弃。
   *
   * **resetToken 必须与 pendingSeed 一起、在拿到快照之后才自增。** 这是本函数唯一的
   * 要害。token 一旦先自增, 宿主下一帧就会清场 —— machine.home() 把整机摆回原点、
   * 板与托盘全部释放 —— 而种子还在网络上飞(实测 state_at p50 23 ms, 一帧 16.7 ms),
   * 于是中间那一两帧渲染的就是**初始画面**。单击时是一闪而过没人报, 擦洗时 60 ms
   * 一次, 就是用户看到的"疯狂闪初始画面"。把两者绑成同一次赋值, 空窗从"很短"变成
   * "不存在": 宿主看到新 token 时种子必然已在手, 清场与播种永远同帧。
   *
   * @param {number} t 目标时刻(纪元秒)
   * @param {{prefetch?: boolean, preview?: boolean}} [options]
   *   prefetch=false: 只播种不预取(擦洗预览用, 省一个 RTT)
   *   preview=true:   擦洗预览态。宿主据此跳过板/托盘的拆卸, 本函数据此跳过派生态
   *                   历史的重放 —— 两件事是配套的: 不重建就绝不能拆。
   * @returns {Promise<boolean>}
   */
  async seek(t, { prefetch = true, preview = false } = {}) {
    const target = this.clock.seek(t)
    this._pending.length = 0
    this._loadedTo = target
    const epoch = this.clock.epoch

    this._seeding = true
    try {
      // 两个请求并发: 派生态历史与关键帧互不依赖, 串起来会让每次跳转多等一个 RTT
      const [snapshot, history] = await Promise.all([
        this.api.recordingStateAt({
          t: target, ...(this.sessionId ? { session_id: this.sessionId } : {}),
        }),
        preview ? null : this.api.recordingHistory({ t: target }),
      ])
      // 乱序守卫。单击一次时两次 seek 不可能重叠, 所以这道守卫一直没被用到; 拖动时
      // 响应必然乱序返回, 少了它就是**旧快照后到即覆盖新的** —— 表现为擦洗发黏、
      // 随机往回跳, 而没有任何报错。_prefetch 早就有同款守卫, 这里当初漏了。
      if (epoch !== this.clock.epoch) return false

      const { events: seedEvents, scalars } = keyframeToSeed(snapshot?.state || {}, target)
      // 关键帧里还带着"块内已推进到 t"的流末值, 补一遍才能精确落在 t 而不是块首
      for (const [stream, latest] of Object.entries(snapshot?.state?.streams || {})) {
        const patch = framesToEvents({
          streams: { [stream]: { ts: [target], channels: Object.fromEntries(
            Object.entries(latest).map(([key, value]) => [key, [value]])) } },
        })
        seedEvents.push(...patch)
      }
      // 历史在前、关键帧在后。顺序是硬的: 历史重放出来的是派生锁存态(板在谁手里、
      // 托盘挂载、夹爪持握), 关键帧才是连续量的权威, 必须最后落, 否则历史里那些
      // 旧的轴位姿会把刚播下去的当前位姿盖掉。
      const events = [...(history?.events || []), ...seedEvents]
      // 清场标志与种子同时置位 —— 见函数头注释, 这两句之间不允许出现 await
      this.previewing = Boolean(preview)
      this.resetToken += 1
      this.pendingSeed = { token: this.resetToken, events, scalars }
      this._lastError = history?.truncated
        ? '派生态历史超上限已截断, 板/托盘归属可能不完整'
        : ''                 // 成功即清; 否则一次右缘 404 会挂住整个会话
      if (prefetch) await this._prefetch()
      return true
    } catch (error) {
      if (epoch !== this.clock.epoch) return false
      this._lastError = `快照读取失败: ${error?.message || error}`
      return false
    } finally {
      this._seeding = false
    }
  }

  /** 退出回放, 交还给实时。宿主看到 active=false 后恢复投喂实时事件与墙钟。 */
  close() {
    this.active = false
    this.clock.pause()
    this._pending.length = 0
    this.previewing = false
    // 交还前再自增一次: 实时接管时同样要清掉回放留下的时间单调锁存, 否则
    // 回放时钟(历史时刻)留下的 lastArrival 会让实时帧一路判成"来自过去"。
    this.resetToken += 1
  }

  play() { this.clock.play() }
  pause() { this.clock.pause() }
  setSpeed(speed) { this.clock.setSpeed(speed) }

  // -- 拖动擦洗 ------------------------------------------------------

  /**
   * 功能: 拖动中把播放头挪到 t —— 按方向分流, 向前免费, 向后才付网络.
   *
   * 决定性的不对称: AxisPoseBuffer.lastArrivalByAxis 是**单调取最大**, 而回放时
   * arrivalMs 就是播放头, 所以**向后必须清场**; 而向前只是快进 —— tick() 一直在做
   * 的事, 数据在手时零成本。planScrub 把这个判据固化成纯函数并有单测钉着。
   *
   * 节流不设固定 Hz: 单航班 + 尾沿最新优先。LAN 上自然跑到 ~15 Hz, 链路差时自动
   * 降速且**永不排队** —— 固定 Hz 在慢链路上会让请求堆积, 松手后画面还在放几秒前的位置。
   *
   * @param {number} t 目标时刻(纪元秒)
   * @returns {'noop'|'drain'|'queued'}
   */
  scrubTo(t) {
    const plan = planScrub({
      playhead: this.clock.playhead, target: t, loadedTo: this._loadedTo,
      maxDrainS: MAX_DRAIN_S, epsS: SCRUB_EPS_S,
    })
    if (plan.mode === 'noop') return 'noop'
    if (plan.mode === 'drain') {
      this.clock.scrub(plan.target)
      this._drain(plan.target)
      return 'drain'
    }
    this._scrubQueued = plan.target
    void this._pumpScrub()
    return 'queued'
  }

  async _pumpScrub() {
    if (this._scrubInFlight) return
    this._scrubInFlight = true
    try {
      while (this._scrubQueued !== null) {
        const target = this._scrubQueued
        this._scrubQueued = null
        // 预览: 不预取(省一个 RTT)、宿主不拆板与托盘(它们由事件历史驱动, 预览不重建)
        await this.seek(target, { prefetch: false, preview: true })
        // 下限: 即便链路是 2 ms, 也不该让宿主的清场(位姿缓冲/机构闸门/插值通道)
        // 一秒跑十几次
        if (this._scrubQueued !== null) await sleep(SCRUB_MIN_INTERVAL_MS)
      }
    } finally {
      this._scrubInFlight = false
    }
  }

  /**
   * 功能: 松手收尾 —— 把队列排空, 再按非预览态重新落一次种.
   *
   * 这里**必须走完整的 seek**, 哪怕最终位置与最后一次预览完全相同。原先为省一个 RTT
   * 写成"位置没变就只 resetToken += 1 + 预取": 那次自增**不带种子**, 宿主清了场却
   * 没人播种, 于是松手后整机停在 home 位姿再也不动(暂停态下没有任何事件会到期)。
   * 一个 RTT 换不来这个。
   *
   * @param {{resume?: boolean}} [options] resume=true 则恢复播放
   */
  async endScrub({ resume = false } = {}) {
    while (this._scrubInFlight || this._scrubQueued !== null) {
      await sleep(SCRUB_MIN_INTERVAL_MS)
    }
    await this.seek(this.clock.playhead)
    if (resume) this.clock.play()
  }

  /**
   * 功能: 把 _pending 里到期的事件投下去(tick 与 drain 共用这一段).
   * @param {number} playhead
   */
  _drain(playhead) {
    let index = 0
    while (index < this._pending.length && (this._pending[index].ts ?? 0) <= playhead) {
      this._emit(this._pending[index])
      index += 1
    }
    if (index) this._pending.splice(0, index)
  }

  /** 供宿主写 SceneManager.timeScale —— 擦洗时不能是 1(积分器脱节)也不能是 0(interp 停摆)。 */
  effectiveRate(deltaPlayheadS = 0, wallDeltaS = 0) {
    if (this._scrubInFlight || this._scrubQueued !== null) {
      return scrubTimeScale(deltaPlayheadS, wallDeltaS)
    }
    return this.clock.playing ? this.clock.speed : 1
  }

  /**
   * 功能: 由渲染循环每帧驱动 —— 推进播放头并把到期事件投喂下去.
   *
   * 严格按播放头节流投喂, 绝不整批灌: AxisPoseBuffer.push 每次都会对整个窗口重排序,
   * sample 又要逐轴 filter, 一次性灌几万条会让主线程直接卡住。
   *
   * @param {number} realDeltaS 墙钟前进秒数 (已含倍速由 clock 处理)
   */
  tick(realDeltaS) {
    if (this._seeding || !this.clock.playing) return
    // 暂停 = 画面完全冻结。不能只靠 advance() 不推进播放头就了事: 排在播放头**当前
    // 时刻**上的那些帧仍会满足 ts <= playhead 而被投喂出去。它们的状态其实已由关键帧
    // 表达过, 再投一次虽不改变结果, 却让"暂停"变成一个会动的状态, 后面所有关于
    // "暂停时画面是否稳定"的推理都不再成立。
    const playhead = this.clock.advance(realDeltaS)
    this._drain(playhead)
    if (this.clock.playing && this._loadedTo - playhead < PREFETCH_MARGIN_S) {
      void this._prefetch()
    }
  }

  async _prefetch() {
    if (this._loading) return
    const from = this._loadedTo
    const to = Math.min(from + PREFETCH_S, this.clock.t1)
    if (to <= from) return
    this._loading = true
    const epoch = this.clock.epoch
    try {
      const payload = await this.api.recordingFrames({
        t0: from, t1: to, ...(this.sessionId ? { session_id: this.sessionId } : {}),
      })
      // 预取回来时若已经又 seek 过, 这批数据属于旧时间线, 直接丢弃
      if (epoch !== this.clock.epoch) return
      this._pending.push(...framesToEvents(payload))
      this._pending.sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))
      this._loadedTo = to
      if (payload?.truncated) {
        this._lastError = '该时间窗数据量超上限, 已截断 —— 请缩小范围'
      } else if (payload?.skipped) {
        // 索引里有、磁盘上读不出来。给出可执行的下一步, 而不是让人对着一句英文发呆。
        this._lastError = `录像缺失 ${payload.skipped} 块(索引与文件不一致), `
          + '可 POST /api/recording/reconcile?deep=true 整理'
      }
    } catch (error) {
      this._lastError = `帧流读取失败: ${error?.message || error}`
    } finally {
      this._loading = false
    }
  }

  snapshot() {
    return { ...this.clock.snapshot(), lastError: this._lastError,
             buffered: this._pending.length, loadedTo: this._loadedTo,
             previewing: this.previewing, scrubbing: this._scrubQueued !== null }
  }

  dispose() {
    this.listeners.clear()
    this.statusListeners.clear()
    this._pending.length = 0
  }
}

/**
 * 功能: 建一条回放事件流 (与 createSimEventStream 同形).
 * @param {object} [options]
 * @returns {{stream: import('../twin/bindings/eventStream.js').EventStream, channel: ReplayChannel}}
 */
export async function createReplayEventStream(options = {}) {
  const { EventStream } = await import('../twin/bindings/eventStream.js')
  const channel = new ReplayChannel(options)
  const stream = new EventStream({
    transport: channel,
    // 回放不做任何播种: 状态一律来自录像关键帧。走宿主默认播种器会把**今天**的节点
    // 与物料快照灌进历史画面, 那正是"回放在说谎"最典型的一种。
    seeder: async () => {},
  })
  const dispose = stream.dispose.bind(stream)
  stream.dispose = () => { dispose(); channel.dispose() }
  return { stream, channel }
}
