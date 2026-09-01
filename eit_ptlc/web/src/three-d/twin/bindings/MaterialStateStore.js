/**
 * 功能: 保存上位机物料账本的最后完整快照，并生成界面/三维绑定共用的只读投影。
 *
 * 物料状态与机械轴不同：它是持久化账本快照，不做插值，也不在断线时回零。断线后
 * 保留最后快照并明确标记 stale，重新连接收到 initial 快照后原地恢复。
 *
 * ⚠ `normalizeSnapshot` 是一张**显式键白名单** —— 它逐个列出字段重建对象, 事件里有而
 *   这里没列的键会被静默丢掉。2026-08-05 踩过两次: 后端新增的 `transit`(在途载荷)没加进来,
 *   于是 TrayBinding 每帧读到 undefined、认为两把爪空手, 现象是"流程明明在搬托盘, 三维里
 *   托盘纹丝不动", 而且不报任何错; 同日又发现 `seats` 从来就没进过白名单。
 *   **后端 grid() 加字段时必须同步加这里** —— 靠人记住已经失败过两次, 所以下面那张
 *   EVENT_KEY_TO_SNAPSHOT_KEY 是强制表态表, 由 materialState.test.js 比对契约金样看门。
 *
 * ⚠ 同一个坑有**第二层**: 上面那张表只管顶层键, 而 cells 是**逐字段重建**的数组 ——
 *   后端给 cell 加一列时顶层键没变, 于是两道绊线一道都不响, 而新字段照样被丢掉。
 *   2026-08 加内容物余量三列时发现这一层完全没有门, 故补了 EVENT_CELL_KEY_TO_SNAPSHOT_KEY。
 */

/**
 * 事件键 -> 快照键的**强制表态表**。值为空串 = 有意不投影(信封字段/只给二维页用)。
 *
 * 它是承重件, 不是文档: 没有它, 测试分不清"消费了并改名"(presence_mismatches ->
 * presenceMismatches)与"整个丢掉了"。后端 grid() 新增顶层键时:
 *   1. pytest 的 TestGridContract 先红 -> 更新 materialGrid.contract.json 金样;
 *   2. npm test 的 materialState 契约用例接着红 -> 在这里显式表态;
 * 两道都过不去才可能悄悄漏掉一个字段。
 */
export const EVENT_KEY_TO_SNAPSHOT_KEY = Object.freeze({
  cells: 'cells',
  staging: 'staging',
  transit: 'transit',
  transit_stale: 'transitStale',
  payload_seats: 'payloadSeats',
  rack: 'rackLedger',             // 后端在架人工账的原样投影; 快照里另有同名 rack = 按孔位重算的板级汇总
                                  // (键名不能撞 —— materialStations.js 正消费 snapshot.rack), 三维托盘显隐读这份
  summary: 'summary',
  presence: 'presence',
  presence_mismatches: 'presenceMismatches',
  magazines: 'magazines',
  bottles: 'bottles',
  seats: 'seats',
  topology: 'topology',
})

/**
 * cells[] **行内**键 -> 快照键的强制表态表。值为空串 = 有意不投影。
 *
 * 与上面那张同一条理由, 只是低一层: cells 在 normalizeSnapshot 里是逐字段重建的,
 * 后端给 cell 加一列不会改变任何顶层键, 于是顶层那张表和 pytest 的 TestGridContract
 * 都不会响 —— 这一层没有门, 新列就静默消失在三维侧。
 * 由 materialState.test.js 与 materialGrid.contract.json 的 cellRow 逐键比对看门。
 */
export const EVENT_CELL_KEY_TO_SNAPSHOT_KEY = Object.freeze({
  kind: 'kind',
  plate: 'plate',
  hole: 'hole',
  state: 'state',
  sample_id: 'sample_id',
  updated_at: 'updated_at',
  run_id: '',                     // 追溯用, 只有二维物料页读; 三维不需要
  powder_mm3: 'powder_mm3',       // 粉桶里的硅胶粉 mm³ (bottle 恒 0)
  liquid_ml: 'liquid_ml',         // 样品瓶里的淋洗液 mL (collector 恒 0)
  eluted: 'eluted',               // 粉桶是否已被洗脱液淋过 -> 三维粉末换色
})

export class MaterialStateStore {
  constructor({ staleMs = 12_000 } = {}) {
    this.staleMs = staleMs
    this.snapshot = null
    this.receivedAt = 0
    this.sourceTs = 0
    this.lastSeq = -1
    this.disconnected = true
    /** 最后一帧的**原始**事件; 草稿叠加作用在它上面(见 setDraftOverlay) */
    this.lastEvent = null
    /** 草稿叠加函数 (rawEvent) => rawEvent'; null = 无草稿 */
    this._draftApply = null
    /** 叠加结果的记忆化: {event, revision, snapshot} */
    this._draftMemo = null
  }

  push(event, nowMs = Date.now()) {
    if (!event || event.type !== 'material_state') return false
    if (!Array.isArray(event.cells) || !event.staging || !Array.isArray(event.magazines)) return false

    const sourceTs = normalizeTimestamp(event.ts, nowMs)
    const seq = Number.isFinite(Number(event.seq)) ? Number(event.seq) : 0
    const restarted = this.disconnected || event.initial === true || sourceTs > this.sourceTs + 1000
    if (!restarted && sourceTs < this.sourceTs) return false
    if (!restarted && sourceTs === this.sourceTs && seq <= this.lastSeq) return false

    this.lastEvent = event
    this.snapshot = normalizeSnapshot(event)
    this.receivedAt = nowMs
    this.sourceTs = sourceTs
    this.lastSeq = seq
    this.disconnected = false
    // 基准换了, 叠加结果作废
    this._draftMemo = null
    return true
  }

  markDisconnected() {
    this.disconnected = true
    // 基准快照已不可信, 挂在它上面的草稿预览不该继续作画
    this.setDraftOverlay(null)
  }

  /**
   * 功能: 装/卸物料改账的草稿叠加层.
   *
   * ⚠ 这是**提交前的编辑预览**, 不是"已写入"的乐观渲染: 界面全程有横幅声明它不是设备
   *   实况, 保存成功后调用方立刻卸掉, 画面回落到推流账本 (见 twin/materialDraft.js 头注)。
   *
   * ⚠ 叠加作用在**原始事件**上, 再走同一个 normalizeSnapshot —— 预览与真相不可能用两套
   *   算法算出来, 两张事件键白名单也一个字都不用动。
   *
   * @param {Function|null} applyFn (rawEvent) => rawEvent'; 传 null 卸载
   * @param {number} [revision=0] 草稿版本号; 变了才重算 (记忆化的键)
   * @returns {void}
   */
  setDraftOverlay(applyFn, revision = 0) {
    this._draftApply = typeof applyFn === 'function' ? applyFn : null
    this._draftRevision = revision
    this._draftMemo = null
  }

  /** 当前是否有草稿叠加 */
  get hasDraftOverlay() {
    return this._draftApply !== null
  }

  /**
   * 功能: 取当前(可能带草稿叠加的)快照与新鲜度.
   *
   * ⚠ 性能承重: 本方法每帧被 TwinBindings 调 3 次 + TrayBinding 1 次。
   *   - 无草稿时必须返回**同一个** this.snapshot 引用 —— 下游 _updateMaterials 与
   *     _applyTransit 都用 `snapshot === this._last` 做身份短路, 换了对象就等于
   *     每帧全量重算托盘/单件显隐;
   *   - 有草稿时按 (基准事件, 草稿版本) 记忆化, 同样只在真的变了才重算。
   *   materialDraftOverlay.test.js 把这两条钉死了。
   *
   * @param {number} [nowMs] 当前时刻
   * @returns {object} {available, stale, disconnected, receivedAt, sourceTs, snapshot, draft}
   */
  status(nowMs = Date.now()) {
    const available = Boolean(this.snapshot)
    let snapshot = this.snapshot
    if (this._draftApply && this.lastEvent) {
      if (!this._draftMemo
        || this._draftMemo.event !== this.lastEvent
        || this._draftMemo.revision !== this._draftRevision) {
        const merged = this._draftApply(this.lastEvent)
        this._draftMemo = {
          event: this.lastEvent,
          revision: this._draftRevision,
          // 草稿没实际改动时 applyDraft 会原样返回入参, 这时不必再归一化一遍
          snapshot: merged === this.lastEvent ? this.snapshot : normalizeSnapshot(merged),
        }
      }
      snapshot = this._draftMemo.snapshot
    }
    return {
      available,
      stale: !available || this.disconnected || nowMs - this.receivedAt > this.staleMs,
      disconnected: this.disconnected,
      receivedAt: this.receivedAt,
      sourceTs: this.sourceTs,
      snapshot,
      /** 当前画面是不是草稿预览 —— 界面据此挂横幅与画布角标 */
      draft: this.hasDraftOverlay,
    }
  }
}

function normalizeTimestamp(value, fallbackMs) {
  const number = Number(value)
  if (!Number.isFinite(number)) return fallbackMs
  return number > 10_000_000_000 ? number : number * 1000
}

function normalizeSnapshot(event) {
  const cells = event.cells.map((cell) => ({
    kind: String(cell.kind || ''),
    plate: Number(cell.plate),
    hole: Number(cell.hole),
    state: String(cell.state || ''),
    sample_id: String(cell.sample_id || ''),
    updated_at: Number(cell.updated_at) || 0,
    // 内容物余量三件套。旧后端不发这三个字段时降级为 0/false 而不是整帧拒收 ——
    // 与 transit.stale 的降级约定拉平: 少一个可视化, 不是断掉整条账本。
    powder_mm3: Number(cell.powder_mm3) || 0,
    liquid_ml: Number(cell.liquid_ml) || 0,
    eluted: Boolean(cell.eluted),   // 后端是 0/1 整数, 这里归一成布尔与其它字段拉平
  }))
  const presence = Array.isArray(event.presence) ? event.presence.map((item) => ({ ...item })) : []
  const presenceByLocation = Object.fromEntries(
    presence.filter((item) => item.location_id).map((item) => [item.location_id, item]),
  )

  const rack = { collector: [], bottle: [] }
  for (const kind of Object.keys(rack)) {
    for (let plate = 1; plate <= 6; plate += 1) {
      const plateCells = cells.filter((cell) => cell.kind === kind && cell.plate === plate)
      const location = presenceByLocation[`rack.${kind}.${plate}`]
      rack[kind].push({
        kind,
        plate,
        fresh: plateCells.filter((cell) => cell.state === 'FRESH').length,
        used: plateCells.filter((cell) => cell.state === 'USED').length,
        filled: plateCells.filter((cell) => cell.state === 'USED' && cell.sample_id).length,
        // 装着内容物的格数 (粉桶看粉量, 样品瓶看液量) —— 与 fresh/used/filled 并列的第四个
        // 计数, 面板只显示它而不是逐格画条(520px 悬浮面板放不下 36 条)
        loaded: plateCells.filter(
          (cell) => (kind === 'collector' ? cell.powder_mm3 : cell.liquid_ml) > 0).length,
        present: typeof location?.present === 'boolean' ? location.present : null,
        expected: typeof location?.expected === 'boolean' ? location.expected : null,
        verified: location?.verified === true,
        ok: typeof location?.ok === 'boolean' ? location.ok : null,
      })
    }
  }

  const staging = {}
  for (const [area, row] of Object.entries(event.staging || {})) {
    const presenceRow = presenceByLocation[area]
    staging[area] = {
      ...row,
      plate: row?.plate !== null && row?.plate !== undefined && Number.isFinite(Number(row.plate))
        ? Number(row.plate)
        : null,
      present: typeof presenceRow?.present === 'boolean' ? presenceRow.present : null,
      verified: presenceRow?.verified === true,
      ok: typeof presenceRow?.ok === 'boolean' ? presenceRow.ok : null,
    }
  }

  // 在途载荷(载荷此刻在哪把夹爪上)。缺段时给空对象而不是 undefined ——
  // 旧后端没有这一段时应降级为"两把爪都空手", 而不是让下游每处都写一遍 `|| {}`。
  // ⚠ hole 必须**先判 null 再转数字**: 整板在途时后端给的就是 null, 而 `Number(null)` 是 0 ——
  //   宽松判会把"整板"悄悄变成"1 号孔的单件", 三维就去飞那个耗材件而不是整张托盘。
  const numberOrNull = (value) => (
    value === null || value === undefined || !Number.isFinite(Number(value))
      ? null
      : Number(value)
  )
  const transit = {}
  for (const [carrier, row] of Object.entries(event.transit || {})) {
    transit[carrier] = {
      carrier: String(row?.carrier || carrier),
      payload: String(row?.payload || ''),
      kind: String(row?.kind || ''),
      plate: numberOrNull(row?.plate),
      hole: numberOrNull(row?.hole),
      from_loc: String(row?.from_loc || ''),
      to_loc: String(row?.to_loc || ''),
      since_at: Number(row?.since_at) || 0,
      run_id: String(row?.run_id || ''),
      script: String(row?.script || ''),
      epoch: String(row?.epoch || ''),
      // 上一个进程留下的在途行: 内容可信, 但"此刻还在爪上"这件事没人能确认。
      // 三维据此拒绝挂载(见 TrayBinding._payloadKeyOf), 物料页据此标红请人核实。
      stale: row?.stale === true,
    }
  }

  // 单件耗材停在工位夹具上 (刮板夹具 / 收集工位)。
  // ⚠ 语义与 transit.stale **相反**, 别照搬处置方式: 在途陈旧 = 可疑(不挂载),
  //   座位陈旧 = 仍可信(瓶子停在工位上, 后端重启它不会自己跑掉)。
  //   有座位行 ⇒ 该件不在托盘孔里, 三维必须把那个孔画空。
  const payloadSeats = (Array.isArray(event.payload_seats) ? event.payload_seats : []).map(
    (row) => ({
      seat: String(row?.seat || ''),
      label: String(row?.label || ''),
      accepts: String(row?.accepts || ''),
      payload: String(row?.payload || ''),
      kind: String(row?.kind || ''),
      plate: numberOrNull(row?.plate),
      hole: numberOrNull(row?.hole),
      since_at: Number(row?.since_at) || 0,
      run_id: String(row?.run_id || ''),
      script: String(row?.script || ''),
      epoch: String(row?.epoch || ''),
      stale: row?.stale === true,
    }),
  )

  // 在架人工账的原样投影 (板级 present; 中转/在爪上/人工标无板都记 0)。
  // 缺段恒发空数组 —— 与 transit/payloadSeats 的降级约定拉平: 回放老录像时
  // 少一个可视化(托盘全按在架画), 不是断掉账本。消费方(TwinBindings)对"查无行"
  // 必须按在架处理, 降级方向不许反过来。
  const rackLedger = (Array.isArray(event.rack) ? event.rack : []).map((row) => ({
    kind: String(row?.kind || ''),
    plate: Number(row?.plate),
    present: Boolean(row?.present),
    updated_at: Number(row?.updated_at) || 0,
  }))

  return {
    cells,
    staging,
    transit,
    transitStale: Number(event.transit_stale) || 0,
    payloadSeats,
    rack,
    rackLedger,
    summary: { ...(event.summary || {}) },
    presence,
    presenceMismatches: Number(event.presence_mismatches) || 0,
    // 薄层板单板停放位的人工账。2026-08-05 核查发现它从来没进过白名单 —— 后端一直在发,
    // 三维一直收不到; 今天只是展示用所以没炸, 但那正是"白名单靠人记"必然的结局。
    seats: Array.isArray(event.seats) ? event.seats.map((item) => ({ ...item })) : [],
    magazines: event.magazines.map((item) => ({
      ...item,
      count: Math.max(0, Number(item.count) || 0),
      capacity: Math.max(0, Number(item.capacity) || 0),
    })),
    bottles: Array.isArray(event.bottles) ? event.bottles.map((item) => ({ ...item })) : [],
    topology: event.topology || null,
  }
}
