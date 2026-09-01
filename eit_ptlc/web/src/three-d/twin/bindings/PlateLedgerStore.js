/**
 * 功能: L1 权威板位置的只读投影 —— 消费上位机调度器快照, 不维护任何账本.
 *
 * 为什么位置的真源在调度器而不在三维: 见 PlateSlots.js 头注释。这里只做三件事:
 *   1. 按 revision 仲裁快照新旧(见 push 的注释, 那个字段有个反直觉的坑);
 *   2. 把 samples[] 折成"哪块板在哪"的只读表;
 *   3. 建 run_id → sample_id 索引, 供 L2 的流程事件归属到正确的板。
 *
 * 建板实例的判据是 **position 是已知的非仓态**, 与样品 status 无关:
 *   PENDING 时 position=feedlift(仓态) 自然不建 —— 板还在料仓堆里;
 *   DONE 时 position=waste(仓态) 自然不建 —— 板已进废板仓堆;
 *   HOLD / ABORTED 时板**确实还停在那个工位上**, 必须照画并在 HUD 标注,
 *   中止不会让一块玻璃板凭空消失, 这是物理事实。
 */
import { isKnownSlot, isMagazineSlot, tankOf } from './PlateSlots.js'
import { STAGE, stageFromJobs } from './plateTraceState.js'

/** 合法阶段值集合: 载荷里写错的字一律忽略并退回推导, 不把脏值画上板面 */
const STAGE_VALUES = new Set(Object.values(STAGE))

/** 快照多久没更新算陈旧(ms)。与物料账本同量级 —— 都是低频持久化数据, 不插值。 */
const DEFAULT_STALE_MS = 12_000

/** 需要在 HUD 上标注"待人工处理"的样品状态。 */
const ATTENTION_STATUSES = new Set(['HOLD', 'ABORTED'])

/** 作业正在跑(scheduler.snapshot 的 job.status)。 */
const RUNNING_JOB_STATUS = 'RUNNING'

export class PlateLedgerStore {
  constructor({ staleMs = DEFAULT_STALE_MS } = {}) {
    this.staleMs = staleMs
    /** @type {Map<string, object>} sample_id -> 板账目 */
    this._bySample = new Map()
    /** @type {Map<string, string>} run_id -> sample_id */
    this._runIndex = new Map()
    /** @type {Array<{slot: string, sampleIds: string[]}>} 停放位冲突(账本异常, 必须可见) */
    this._conflicts = []
    /** @type {Map<string, string>} sample_id -> 未识别的 position 原文 */
    this._unknown = new Map()
    this._revision = null
    this._receivedAt = 0
    this._received = false
    this._disconnected = false
    /**
     * L1 能 authoritative 回答的落点集; **null = 全覆盖**(调度器快照没有这个字段,
     * live 因此逐字维持原行为)。仿真沙盒的板位投影给得出它 —— 沙盒不装调度器,
     * 缸里有哪块板它是真不知道, 于是必须把"不知道"与"那里没有板"分开:
     * 直接少报一个落点, _syncLedger 会把那里的板回收掉, 板消失且无任何线索。
     * @type {Set<string>|null}
     */
    this._coveredSlots = null
    /** L1 的身份是不是合成的(沙盒按位置编的), 决定 L2 迁移能不能按落点归属。 */
    this._syntheticIdentity = false
  }

  /**
   * 功能: 消费一帧 `/api/scheduler/snapshot`.
   *
   * ⚠ revision 只能比大小, **不能判连续**: scheduler.py 的 `self._revision += 1` 执行在
   * 节流 return **之前**, 所以发出来的 revision 会跳号, `revision === last + 1` 这种
   * 连续性判据必然误判。回退(变小)意味着**后端重启**(_revision 构造时归 0), 也要接受,
   * 并按重连语义处理。
   *
   * @param {object} snapshot 调度器快照
   * @param {number} nowMs 现在(ms)
   * @returns {boolean} 是否更新了内部状态
   */
  push(snapshot, nowMs = Date.now()) {
    if (!snapshot || !Array.isArray(snapshot.batches)) return false

    const revision = Number(snapshot.revision)
    const hasRevision = Number.isFinite(revision)
    let restarted = false
    if (hasRevision && this._revision !== null) {
      if (revision === this._revision) return false          // 幂等丢弃, 省一次全量 diff
      if (revision < this._revision) restarted = true         // 后端重启
    }

    const bySample = new Map()
    const runIndex = new Map()
    const unknown = new Map()
    const occupancy = new Map()

    for (const batch of snapshot.batches) {
      for (const sample of batch?.samples || []) {
        const sampleId = String(sample?.sample_id || '')
        if (!sampleId) continue
        const position = String(sample?.position || '')

        let running = false
        for (const job of sample.jobs || []) {
          const runId = String(job?.run_id || '')
          if (runId) runIndex.set(runId, sampleId)
          if (String(job?.status || '').toUpperCase() === RUNNING_JOB_STATUS) running = true
        }
        // 工艺阶段(空白/点样/展开/刮取)驱动板面痕迹外观 —— 与位置仲裁完全无关。
        // 两个来源, **载荷显式给的优先**:
        //   · sample.stage —— 仿真沙盒的板位投影直读账本 seat_occupancy.stage;
        //   · 缺席则从调度器 jobs 推导 (plateTraceState.stageFromJobs)。
        // live 的调度器快照没有 stage 字段 ⇒ 恒走后者, 逐字零变化。
        const derived = stageFromJobs(sample.jobs)
        const explicit = String(sample?.stage || '')
        const stage = STAGE_VALUES.has(explicit) ? explicit : derived.stage
        const spottingRunning = derived.spottingRunning

        if (position && !isKnownSlot(position)) {
          // 不认识的词一律不迁移、不猜, 只记下来让 HUD 显式报出去 ——
          // 调度器改了词表而前端没跟上时, 这是唯一能看见的信号。
          unknown.set(sampleId, position)
          continue
        }

        const entry = {
          sampleId,
          batchId: String(batch?.batch_id || ''),
          seq: Number(sample?.seq) || 0,
          position,
          tank: tankOf(position) ?? (Number.isFinite(Number(sample?.tank)) ? Number(sample.tank) : null),
          status: String(sample?.status || ''),
          message: String(sample?.message || ''),
          needsAttention: ATTENTION_STATUSES.has(String(sample?.status || '')),
          onPlate: Boolean(position) && !isMagazineSlot(position),
          running,
          stage,
          spottingRunning,
        }
        bySample.set(sampleId, entry)
        if (entry.onPlate) {
          if (!occupancy.has(position)) occupancy.set(position, [])
          occupancy.get(position).push(sampleId)
        }
      }
    }

    // 停放位冲突: 调度器的 _SINGLE_SLOTS 本应保证台上恒至多一块板。真出现两块说明
    // 账本异常 —— 两块都画、都报, **绝不隐藏也不去重**, 让人看见比画面好看重要。
    this._conflicts = [...occupancy.entries()]
      .filter(([, ids]) => ids.length > 1)
      .map(([slot, sampleIds]) => ({ slot, sampleIds: [...sampleIds] }))

    const covered = snapshot?.coverage?.slots
    this._coveredSlots = Array.isArray(covered) ? new Set(covered.map(String)) : null
    this._syntheticIdentity = snapshot?.identity === 'synthetic'

    this._bySample = bySample
    this._runIndex = runIndex
    this._unknown = unknown
    this._revision = hasRevision ? revision : this._revision
    this._receivedAt = nowMs
    this._received = true
    this._disconnected = false
    this._restarted = restarted
    return true
  }

  /** 显式断连: 冻结末态, 不清空、不回零(与 MaterialStateStore 同款约定)。 */
  markDisconnected() {
    this._disconnected = true
  }

  /** 重连/首帧: 调用方据此把全部板 snap 回 L1 并清掉 L2 的轨迹。 */
  consumeResync() {
    const value = this._restarted || false
    this._restarted = false
    return value
  }

  /** 应当画出独立板实例的样品(非仓态)。 */
  plates() {
    return [...this._bySample.values()].filter((entry) => entry.onPlate)
  }

  /**
   * 功能: 这一落点是不是 L1 说得清的.
   *
   * 全覆盖(调度器快照)时恒 true —— live 的回收规则因此逐字不变。
   * @param {string} slot 落点
   * @returns {boolean}
   */
  covers(slot) {
    if (this._coveredSlots === null) return true
    return this._coveredSlots.has(String(slot || ''))
  }

  /** L1 的身份是否为合成(沙盒按位置编的); 决定 L2 迁移能否按落点归属。 */
  syntheticIdentity() {
    return this._syntheticIdentity
  }

  /** L1 覆盖面(诊断用); null = 全覆盖。 */
  coveredSlots() {
    return this._coveredSlots
  }

  /** 全部在制样品(含仓态), 供 HUD 诊断。 */
  all() {
    return [...this._bySample.values()]
  }

  /**
   * 功能: 有作业正在跑的样品(**含仓态**, 与 plates() 的过滤不同).
   *
   * 用途只有一个: 真空位说吸盘上有板、而画面上没有时(刷新), 拿它归属那块板。
   * 机器人只有一台, 恰好一条时这不是猜 —— 是调度器自己声明的在制品; 0 条或多条
   * 时调用方必须退回"无归属的推断板", 绝不硬挑一个。
   *
   * 含仓态是必须的: 板从上料仓被吸起时账本仍记 `feedlift`, 而那正是最常见的一步。
   * @returns {Array<object>} 板账目
   */
  runningSamples() {
    return [...this._bySample.values()].filter((entry) => entry.running)
  }

  /** 某样品的账目; 不存在返回 null。 */
  get(sampleId) {
    return this._bySample.get(String(sampleId || '')) || null
  }

  /**
   * 功能: 由流程 run_id 反解样品号.
   * 子脚本沿用父 run_id(VmThread.run_id 全程不变), 所以 robot_suction_put 深处的
   * tool_action 事件也带得到正确的 run_id。
   * @param {string} runId 运行号
   * @returns {string} 样品号; 归属不到时空串(调用方落到 inferred 板并标注, 绝不猜)
   */
  sampleIdForRun(runId) {
    return this._runIndex.get(String(runId || '')) || ''
  }

  /** 停放位冲突清单(账本异常)。 */
  conflicts() {
    return this._conflicts.map((item) => ({ ...item, sampleIds: [...item.sampleIds] }))
  }

  /** 未识别的位置词: sample_id -> 原文。 */
  unknownPositions() {
    return [...this._unknown.entries()].map(([sampleId, position]) => ({ sampleId, position }))
  }

  /**
   * 功能: 供 HUD 的只读状态.
   * @param {number} nowMs 现在(ms)
   * @returns {{received:boolean, stale:boolean, frozen:boolean, revision:number|null,
   *            plates:number, samples:number, conflicts:number, unknown:number}}
   */
  status(nowMs = Date.now()) {
    const age = this._received ? nowMs - this._receivedAt : Infinity
    return {
      received: this._received,
      stale: this._received && age > this.staleMs,
      frozen: this._disconnected,
      revision: this._revision,
      plates: this.plates().length,
      samples: this._bySample.size,
      conflicts: this._conflicts.length,
      unknown: this._unknown.size,
    }
  }
}
