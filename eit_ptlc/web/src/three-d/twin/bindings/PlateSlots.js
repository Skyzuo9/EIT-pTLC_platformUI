/**
 * 功能: 薄层板停放位的词表、相邻性与 CAD 锚点解析规则(纯函数, 不依赖 three).
 *
 * 词表不是这里发明的 —— 它是上位机**调度器的权威位置账**:
 *   config/recipes/parallel_v1.yaml 头注释写明位置轨迹
 *     `feedlift → spot_seat → scrape_table → tank → scrape_table → waste`
 *     由校验器静态保证连续;
 *   每个原子流程段在 config/operation/11_parallel/pf_s*.yaml 的 `flow.from/to` 里
 *     逐字声明这些值(tank 形态为 `tank:{tank}`);
 *   operation/scheduler.py 的 _SINGLE_SLOTS = {spot_seat, scrape_table} 保证这两处
 *     恒至多一块板, 缸由缸池管, feedlift/waste 是不限容量的仓;
 *   samples.position 持久化在 experiments.db, 经 GET /api/scheduler/snapshot 下发。
 *
 * 所以三维**不维护第二套账本**(PTLC_REALTIME_PROTOCOL.md §5 的硬约定), 只做投影。
 * 本模块就是投影所需的那点词法知识。
 */

/** L1 位置词表; 与 pf_s*.yaml 的 flow.from/to 逐字一致。 */
export const PLATE_SLOT = Object.freeze({
  FEEDLIFT: 'feedlift',
  SPOT_SEAT: 'spot_seat',
  SCRAPE_TABLE: 'scrape_table',
  WASTE: 'waste',
  /** L2 派生态: 板正被吸盘带着走。后端词表里没有这个值。 */
  CARRIED: 'carried',
})

/** 展缸数量(缸池 1..8)。 */
export const TANK_COUNT = 8

/** 面板/HUD 显示名。 */
export const SLOT_LABELS = Object.freeze({
  [PLATE_SLOT.FEEDLIFT]: '上料仓',
  [PLATE_SLOT.SPOT_SEAT]: '点样座',
  [PLATE_SLOT.SCRAPE_TABLE]: '刮板台',
  [PLATE_SLOT.WASTE]: '废板仓',
  [PLATE_SLOT.CARRIED]: '机械臂持板',
})

/** 两个"仓": 不限容量, 三维由料仓堆叠承担, **不为它们建独立板实例**。 */
const MAGAZINE_SLOTS = new Set([PLATE_SLOT.FEEDLIFT, PLATE_SLOT.WASTE])

/**
 * 硅胶面朝上的落点。
 *
 * 依据不是观感, 是 `config/operation/06_robot/*.yaml` 里每个取放动作的**翻转态**:
 *   rotary-up  (点样座 P19 / 刮板台 P65) —— 板坐在吸盘上方, 硅胶朝上(点样与刮取都在硅胶面上做);
 *   rotary-down(上料仓 P21 / 废板仓 P22 / 展缸 P11-P18) —— 持板朝下, 硅胶朝下。
 * 料仓那条尤其要紧: 板在仓里必须**玻璃面朝上**, 吸盘才能从上方贴玻璃面吸起
 * (用户第 3 条要求"吸盘靠近玻璃板"), 画反了就成了吸盘去吸硅胶粉面。
 */
const SILICA_UP_SLOTS = new Set([PLATE_SLOT.SPOT_SEAT, PLATE_SLOT.SCRAPE_TABLE])

/**
 * 功能: 该落点上板的硅胶面是否朝上.
 * @param {string} position L1 位置串
 * @returns {boolean} true=硅胶在玻璃上方
 */
export function isSilicaUp(position) {
  return SILICA_UP_SLOTS.has(String(position || ''))
}

/**
 * 功能: 解析 `tank:N` 形态的缸号.
 * `tank:?` 是调度器在样品尚未分缸时给出的占位(scheduler.py::_resolve_loc), 视为未知。
 * @param {string} position L1 位置串
 * @returns {number|null} 1..8, 非缸位或未分缸时 null
 */
export function tankOf(position) {
  const match = /^tank:(\d+)$/.exec(String(position || ''))
  if (!match) return null
  const n = Number(match[1])
  return Number.isInteger(n) && n >= 1 && n <= TANK_COUNT ? n : null
}

/** 是否是"仓"态(feedlift / waste)。 */
export function isMagazineSlot(position) {
  return MAGAZINE_SLOTS.has(String(position || ''))
}

/** 该位置串是否属于已知词表(含 tank:N)。未知词一律不迁移, 只计数告警。 */
export function isKnownSlot(position) {
  const value = String(position || '')
  if (!value) return false
  if (value === PLATE_SLOT.CARRIED) return true
  if (MAGAZINE_SLOTS.has(value)) return true
  if (value === PLATE_SLOT.SPOT_SEAT || value === PLATE_SLOT.SCRAPE_TABLE) return true
  return tankOf(value) !== null
}

/**
 * 邻接表(无向): 板一次搬运只能在相邻两态之间走。
 * 依据就是配方里那条被静态校验保住的位置轨迹, 不是拍脑袋定的。
 */
const ADJACENCY = new Map([
  [PLATE_SLOT.FEEDLIFT, new Set([PLATE_SLOT.SPOT_SEAT])],
  [PLATE_SLOT.SPOT_SEAT, new Set([PLATE_SLOT.FEEDLIFT, PLATE_SLOT.SCRAPE_TABLE])],
  [PLATE_SLOT.SCRAPE_TABLE, new Set([PLATE_SLOT.SPOT_SEAT, PLATE_SLOT.WASTE, 'tank:*'])],
  [PLATE_SLOT.WASTE, new Set([PLATE_SLOT.SCRAPE_TABLE])],
])

/** 把 tank:N 折成通配键, 便于用一条规则表达"任意缸只与刮板台相邻"。 */
function adjacencyKey(position) {
  return tankOf(position) === null ? String(position || '') : 'tank:*'
}

/**
 * 功能: L1 两态之间是否只隔一次搬运.
 *
 * 用途是给 L2 的落点推断加一道闸: 板只允许从"账本认可的上一处"迁到相邻处。
 * 明确不相邻的几对(它们一旦出现就说明推断错了): feedlift↔waste、spot_seat↔tank、tank↔tank。
 *
 * @param {string} from 起点位置串
 * @param {string} to 终点位置串
 * @returns {boolean}
 */
export function isAdjacent(from, to) {
  if (!isKnownSlot(from) || !isKnownSlot(to)) return false
  const a = adjacencyKey(from)
  const b = adjacencyKey(to)
  if (a === 'tank:*' && b === 'tank:*') return false      // 缸之间不能直接倒板
  return Boolean(ADJACENCY.get(a)?.has(b) || ADJACENCY.get(b)?.has(a))
}

/**
 * 功能: 校验片段里的一条 `plate` 原语(编译期 fail-fast).
 *
 * 为什么要在编译期拦: 落点名写错在运行期的表现是"板压根没出现", 既不报错也难归因 ——
 * 与 attach 缺 id 是同一类坑(见 clipSchema.validateOwnership 的注释)。
 *
 * 放在本模块而不是 PlateStage: 校验只用到落点词表, 是纯函数; clipSchema 编译期要调它,
 * 而 clipSchema 必须保持零 three 依赖(它的单测直接 `node --test` 跑)。
 *
 * @param {object} body 原语参数
 * @param {number} index 步骤下标(报错定位用)
 * @returns {void}
 * @throws {Error} 缺 id / 动作不唯一 / 落点不在词表
 */
export function validatePlateStep(body, index) {
  if (!body?.id) throw new Error(`步骤 #${index} plate 缺 id`)
  const actions = ['at', 'carry', 'hide'].filter((key) => body[key] !== undefined && body[key] !== null)
  if (actions.length !== 1) {
    throw new Error(`步骤 #${index} plate 必须恰好含一个动作(at / carry / hide), 实际: [${actions}]`)
  }
  if (body.mount !== undefined && body.carry !== true) {
    throw new Error(`步骤 #${index} plate.mount 只能配 carry: true 使用`)
  }
  // `from` 是**尺寸与硅胶朝向的来源提示**, 不是位置 —— 位置由刀具常量定(见
  // plateGeometry.suctionMountLocal)。板池是复用的, 少了它会沿用上一块板的朝向,
  // 于是从料仓取的板可能被画成硅胶朝上(=吸盘去吸粉面), 而那在画面上看不出错。
  if (body.from !== undefined) {
    if (body.carry !== true) {
      throw new Error(`步骤 #${index} plate.from 只能配 carry: true 使用`)
    }
    if (!isKnownSlot(String(body.from))) {
      throw new Error(`步骤 #${index} plate.from 不是已知落点: ${body.from}`)
    }
  }
  if (body.mount !== undefined) {
    const { position, quaternion } = body.mount || {}
    // 严格判 number: YAML 的 null 经 Number() 是 0, 宽松判会把"缺一个分量"放行,
    // 表现是板挂在吸盘原点 —— 看着像"板长在旋转气缸轴心上", 查起来毫无线索。
    if (!Array.isArray(position) || position.length !== 3
      || !Array.isArray(quaternion) || quaternion.length !== 4
      || [...position, ...quaternion].some((v) => typeof v !== 'number' || !Number.isFinite(v))) {
      throw new Error(`步骤 #${index} plate.mount 必须是 {position:[3], quaternion:[4]} 且全为有限数`)
    }
  }
  if (body.at === undefined || body.at === null) return
  const slot = String(body.at)
  // carried 走 carry:true; 不接受写成 at: carried —— 一件事两种写法只会让读片段的人猜。
  if (slot === PLATE_SLOT.CARRIED) {
    throw new Error(`步骤 #${index} plate 持板请写 carry: true, 不要写 at: carried`)
  }
  if (!isKnownSlot(slot)) throw new Error(`步骤 #${index} plate.at 不是已知落点: ${slot}`)
}

// ---------------------------------------------------------------------------
// CAD 锚点解析
// ---------------------------------------------------------------------------

/**
 * 固定落点的 CAD 零件名(glTF 原名, 非 three 消毒后的名)。
 * ⚠ 实例编号是**乱的**, 别按序号推 —— 见 resolveAnchors 的注释。
 */
export const FIXED_ANCHOR_NAMES = Object.freeze({
  [PLATE_SLOT.SPOT_SEAT]: '玻璃-1',
  [PLATE_SLOT.SCRAPE_TABLE]: '玻璃-1.002',
})

/** 两个料仓模板节点(03 步已改成稳定的 INV_* 名, 不会被静态合并吃掉)。 */
export const MAGAZINE_ANCHOR_NAMES = Object.freeze({
  [PLATE_SLOT.FEEDLIFT]: 'INV_MAGAZINE_FEED_TEMPLATE',
  [PLATE_SLOT.WASTE]: 'INV_MAGAZINE_WASTE_TEMPLATE',
})

/** 缸内板锚点的父节点名规则: TANK_1 .. TANK_8。 */
const TANK_PARENT_RE = /^TANK_(\d)$/

/**
 * 功能: 从节点清单解析"停放位 → CAD 锚点路径"的映射.
 *
 * ⚠ **缸号必须按 parent 名反查, 绝不能按实例序号推。** CAD 实测的对应关系是乱的:
 *     玻璃-1.003→TANK_7   玻璃-1.004→TANK_6   玻璃-1.005→TANK_5   玻璃-1.006→TANK_8
 *     玻璃-1.008→TANK_3   玻璃-1.009→TANK_2   玻璃-1.010→TANK_1   玻璃-1.011→TANK_4
 *   而且 **玻璃-1.007 根本不是缸板, 是废板仓模板**(已改名 INV_MAGAZINE_WASTE_TEMPLATE)。
 *   按 `.003~.011 依次对应 TANK_1..8` 推必错 —— 错了画面照样"看起来很真",
 *   只是每块板都躺错缸, 没有任何自动指标会报警。
 *
 * @param {Array<{name: string, parentName: string, path: string}>} nodes 节点描述清单
 * @returns {{anchors: Map<string, string>, missing: string[]}} 停放位 -> 路径; 以及未解析到的停放位
 */
export function resolveAnchors(nodes) {
  const anchors = new Map()
  for (const node of nodes || []) {
    const name = String(node?.name || '')
    const path = String(node?.path || '')
    if (!name || !path) continue

    const tank = TANK_PARENT_RE.exec(String(node?.parentName || ''))
    if (tank && name.startsWith('玻璃-')) {
      anchors.set(`tank:${Number(tank[1])}`, path)
      continue
    }
    for (const [slot, anchorName] of Object.entries(FIXED_ANCHOR_NAMES)) {
      if (name === anchorName) anchors.set(slot, path)
    }
    for (const [slot, anchorName] of Object.entries(MAGAZINE_ANCHOR_NAMES)) {
      if (name === anchorName) anchors.set(slot, path)
    }
  }

  const expected = [
    PLATE_SLOT.SPOT_SEAT,
    PLATE_SLOT.SCRAPE_TABLE,
    PLATE_SLOT.FEEDLIFT,
    PLATE_SLOT.WASTE,
    ...Array.from({ length: TANK_COUNT }, (_, i) => `tank:${i + 1}`),
  ]
  return { anchors, missing: expected.filter((slot) => !anchors.has(slot)) }
}
