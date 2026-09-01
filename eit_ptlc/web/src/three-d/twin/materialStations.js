/**
 * 功能: 把物料账本里的实体 (库位/中转区/板仓/溶剂瓶/工位夹具/板位) 归到三维工位.
 *
 * 为什么这张表在前端而不是给 config/material_topology.yaml 加个 station 键:
 *   后端加字段要连带过 loader 校验 + topology_dto + materialGrid.contract.json 金样 +
 *   MaterialStateStore 白名单四道绊线, 而二维物料页是按**类别**分组的, 根本不要这个分组。
 *   这里只是三维页的展示归属, 改错了最坏是分错栏, 不会写错账。
 *   (将来若二维页也要按工位分, 再往 topology 里收编, 那时这张表整体删掉。)
 *
 * 两条来源, 能推的就推:
 *   ① deriveSeatStations —— manifest 里带 node 路径的实体 (货架/中转/板仓/液体/内容物)
 *      直接按 glbNode 前缀反查工位, 管线换了摆位它自己跟着走;
 *   ② DECLARED_STATION —— 没有三维几何的实体 (溶剂瓶/板位/上料架传感器) 只能显式声明,
 *      每条都在下面注明依据。
 */

/**
 * 没有 manifest 几何节点、只能显式声明归属的实体.
 *
 * 依据:
 *   rack / feed-1 / feed-2  货架 12 库位的人工账 与 上样料架检测1/2 光电 (IX9.0/9.1)
 *                           说的是同一排料架 —— manifest 里那 12 个库位挂在
 *                           ST_RACK/上料架-1/ 下, 与 feed-N 的中文名"上样料架N"同物。
 *   staging-a / staging-b   两个中转托盘位。A 有几何 (ST_STAGINGA) 会被 ① 推出来,
 *                           B (收集平台) 无几何; 两者同属"中转托盘位"这个概念, 放同一栏,
 *                           操作员找"中转"只需看一处。若现场更希望 B 跟着收集工位,
 *                           把下面这一行改成 'COLLECT' 即可, 无其它耦合。
 *   spot_seat               点样座 (上样板位) —— 名字即工位。
 *   scrape_table            刮板拍照台 (拍照板位) —— 同上。
 *   solvent_1..4            展开工位的展开剂: config/material_bindings.yaml 的
 *                           develop.fill / develop.rinse_fill 声明 bottles:[solvent_1..4]。
 *   eluent                  洗脱液: 同文件 collect.collect 声明 bottles:[eluent]。
 *   collect-bottle          收集工位样品瓶位 (件位与传感器同 id)。
 */
export const DECLARED_STATION = Object.freeze({
  rack: 'RACK',
  'feed-1': 'RACK',
  'feed-2': 'RACK',
  'staging-a': 'STAGINGA',
  'staging-b': 'STAGINGA',
  spot_seat: 'SAMPLING',
  scrape_table: 'PHOTOSCRAPE',
  solvent_1: 'DEVELOP',
  solvent_2: 'DEVELOP',
  solvent_3: 'DEVELOP',
  solvent_4: 'DEVELOP',
  eluent: 'COLLECT',
  'collect-bottle': 'COLLECT',
  'collect-holder': 'COLLECT',
  'scrape-holder': 'PHOTOSCRAPE',
})

/**
 * 功能: 按 glbNode 前缀把一条 manifest 节点路径归到工位.
 *
 * ⚠ 必须取**最长**匹配: ROBOT 的 glbNode 是 ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT,
 *   短前缀匹配会让 ST_RAIL 抢走机械臂下面的一切.
 * @param {object|null} manifest 绑定契约
 * @param {string} node 节点路径
 * @returns {string|null} 工位 id
 */
export function stationOfNode(manifest, node) {
  if (!node) return null
  let best = null
  let bestLen = -1
  for (const station of manifest?.stations || []) {
    const prefix = station.glbNode
    if (!prefix || prefix.length <= bestLen) continue
    if (node === prefix || node.startsWith(`${prefix}/`)) {
      best = station.id
      bestLen = prefix.length
    }
  }
  return best
}

/**
 * 功能: 从 manifest 推出"实体 id -> 工位 id".
 * @param {object|null} manifest 绑定契约
 * @returns {Record<string, string>} 映射表
 */
export function deriveSeatStations(manifest) {
  const out = {}
  const put = (id, node) => {
    if (!id) return
    const station = stationOfNode(manifest, node)
    if (station) out[id] = station
  }
  const inv = manifest?.inventory || {}
  // 货架 12 库位: 逐条都在 ST_RACK 下, 统一挂到 rack 这个总 id
  for (const row of inv.rack || []) put('rack', row.node)
  for (const row of inv.staging || []) put(row.area, row.node)
  for (const row of inv.magazines || []) put(row.id, row.node)
  for (const row of manifest?.liquids || []) put(row.seat, row.node)
  for (const row of manifest?.consumableContents?.kinds || []) put(row.seat, row.node)
  return out
}

/**
 * 功能: 查一个物料实体归哪个工位 (推导优先, 声明兜底).
 * @param {object|null} manifest 绑定契约
 * @param {string} id 实体 id (库位/中转区/板仓/瓶/座)
 * @returns {string|null} 工位 id
 */
export function stationOfEntity(manifest, id) {
  if (!id) return null
  const derived = deriveSeatStations(manifest)
  return derived[id] || DECLARED_STATION[id] || null
}

/**
 * 功能: 从 presence 行的 location_id 反查工位.
 *
 * location_id 形如 rack.<kind>.<plate> / staging-a / collect-bottle / feed-1.
 * @param {object|null} manifest 绑定契约
 * @param {string} locationId 传感器点位 id
 * @returns {string|null} 工位 id
 */
export function stationOfLocation(manifest, locationId) {
  if (!locationId) return null
  if (locationId.startsWith('rack.')) return stationOfEntity(manifest, 'rack')
  return stationOfEntity(manifest, locationId)
}

/** 板仓 id -> 中文名 (topology 的 glass.magazines) */
const MAGAZINE_LABEL = Object.freeze({ feed: '上料仓 (1Z)', waste: '下料仓 (2Z)' })
/** 中转区 id -> 中文名 (topology 的 tray.locations) */
const STAGING_LABEL = Object.freeze({
  'staging-a': '中转托盘位A (刮板拍照)',
  'staging-b': '中转托盘位B (收集平台)',
})
/** 托盘种类 -> 中文名 (topology 的 tray.contents) */
export const KIND_LABEL = Object.freeze({ collector: '粉桶', bottle: '样品瓶' })

/**
 * 功能: 把一条 presence 行渲染成人读文本.
 *
 * 尊重 verified=false: 货架那 12 个位实测信号未接到 PLC (material_store.py 记了
 * 2026-07-26 的三态 A/B 现场试验), 后端对它们一律回 ok=null —— 前端不许自己判定,
 * 只如实转述读数.
 * @param {object|null} row presence 行
 * @returns {{text: string, tone: string}} 文本与色调
 */
export function presenceLabel(row) {
  if (!row) return { text: '无传感器', tone: 'muted' }
  if (row.verified !== true) {
    const read = row.present === true ? '有' : row.present === false ? '无' : '—'
    return { text: `读数 ${read} · 极性未核实`, tone: 'muted' }
  }
  if (row.present === null || row.present === undefined) return { text: '读不到', tone: 'warn' }
  const read = row.present ? '有' : '无'
  if (row.ok === false) return { text: `光电读到「${read}」· 与账本不符`, tone: 'bad' }
  return { text: `光电读到「${read}」`, tone: 'ok' }
}

/**
 * 功能: 由光电与账本是否对得上, 推一个工位的物料健康度(给左栏小圆点用).
 *
 * 为什么要它: 料架(RACK)在 manifest 里 nodeId 为 null —— 它没有 PLC 遥测节点, 于是
 * TwinFeed.healthOf 一律回 'unknown', 圆点恒灰。但料架**有**光电, 帐实对不对得上正是
 * 操作员最该一眼看到的事。
 *
 * ⚠ 判据只认 `verified === true` 的行, 这条是承重的:
 *   货架那 12 路 (rack.collector.1..6 / rack.bottle.1..6) 是 `verified: false` ——
 *   2026-07-26 现场实测未供电、恒回 False, 后端已定案对它们一律 ok=null 且"只显读数
 *   不判定"。拿它们染色等于凭一堆恒假信号报平安, 比灰着更坏。
 *   所以料架的绿灯实际由**上样料架两路** feed-1 / feed-2 (IX9.0 / IX9.1, verified:true)
 *   决定 —— tooltip 必须如实说明依据几路, 别让人以为 72 个孔位都被光电盯着。
 *
 * ⚠ 绿的条件是"没有一路与账本打架"而**不是**"每一路都判定为一致":
 *   实测后端对 feed-1 / feed-2 回的是 ok=null —— topology 把 feed 类别标了"纯传感器
 *   读数, 无软件账", 没有账自然算不出一致与否。若要求 ok===true 才绿, 料架就永远绿不了,
 *   而那两路其实读得好好的。所以: 有一路明确打架就黄; 否则只要还有读得到的已核实光电就绿。
 *
 * @param {object|null} manifest 绑定契约
 * @param {object|null} snapshot 归一化后的物料快照
 * @param {string|null} stationId 工位 id
 * @returns {'ok'|'mismatch'|'unknown'} 健康度
 */
export function materialHealthOf(manifest, snapshot, stationId) {
  if (!stationId) return 'unknown'
  const rows = (snapshot?.presence || []).filter(
    (row) => row.verified === true && stationOfLocation(manifest, row.location_id) === stationId,
  )
  if (!rows.length) return 'unknown'
  // 明确打架的优先: 坏消息不能被别的行的"读得到"盖过去
  if (rows.some((row) => row.ok === false)) return 'mismatch'
  // present 为 null 才叫读不到; present=false 是"这里没东西", 是一次有效读数
  const readable = rows.filter((row) => row.present === true || row.present === false)
  return readable.length ? 'ok' : 'unknown'
}

/**
 * 功能: 数一个工位有几路已核实光电(给 tooltip 交代判据来源).
 * @param {object|null} manifest 绑定契约
 * @param {object|null} snapshot 归一化后的物料快照
 * @param {string|null} stationId 工位 id
 * @returns {number} 已核实光电路数
 */
export function verifiedSensorCount(manifest, snapshot, stationId) {
  if (!stationId) return 0
  return (snapshot?.presence || []).filter(
    (row) => row.verified === true && stationOfLocation(manifest, row.location_id) === stationId,
  ).length
}

/**
 * 功能: 列出某工位要渲染的物料分段.
 *
 * 返回的是**描述符**而不是 DOM —— 便于 node --test 断言"料架有 12 个库位分段、
 * 上下料位有 2 个板仓分段"这类结构事实, 而不必渲染组件.
 * @param {object|null} manifest 绑定契约
 * @param {string|null} stationId 工位 id
 * @param {object|null} snapshot 归一化后的物料快照
 * @returns {object[]} 分段描述符
 */
export function materialSectionsFor(manifest, stationId, snapshot) {
  if (!stationId) return []
  const sections = []
  const owns = (id) => stationOfEntity(manifest, id) === stationId
  const presenceOf = (locationId) =>
    (snapshot?.presence || []).find((row) => row.location_id === locationId) || null

  // ① 货架库位: 板级在架 + 逐孔状态 (用户描述的"有没有托盘/几个物料/在哪些空位"就是这里)
  if (owns('rack')) {
    for (const kind of ['collector', 'bottle']) {
      const plates = (snapshot?.rack?.[kind] || []).map((plate) => ({
        ...plate,
        cells: (snapshot?.cells || [])
          .filter((cell) => cell.kind === kind && cell.plate === plate.plate)
          .sort((a, b) => a.hole - b.hole),
        presence: presenceOf(`rack.${kind}.${plate.plate}`),
      }))
      if (plates.length) {
        sections.push({
          type: 'rack', key: `rack-${kind}`, kind,
          title: `${KIND_LABEL[kind] || kind}托盘库位 (${plates.length})`, plates,
        })
      }
    }
    // 上样料架光电: 只读, 无账本 (topology 明确 feed 类别不设软件账)
    const sensors = ['feed-1', 'feed-2'].map((id) => ({ id, presence: presenceOf(id) }))
      .filter((row) => row.presence)
    if (sensors.length) {
      sections.push({ type: 'sensor', key: 'feed-sensors', title: '上样料架光电 (只读)', rows: sensors })
    }
  }

  // ② 中转托盘位: 区上停着几号板
  const stagingRows = Object.entries(snapshot?.staging || {})
    .filter(([area]) => owns(area))
    .map(([area, row]) => ({
      area, label: STAGING_LABEL[area] || area, ...row, presence: presenceOf(area),
    }))
  if (stagingRows.length) {
    sections.push({ type: 'staging', key: 'staging', title: '中转区托盘', rows: stagingRows })
  }

  // ③ 玻璃板仓张数
  const magazineRows = (snapshot?.magazines || [])
    .filter((row) => owns(row.magazine))
    .map((row) => ({ ...row, label: MAGAZINE_LABEL[row.magazine] || row.magazine }))
  if (magazineRows.length) {
    sections.push({ type: 'magazine', key: 'magazine', title: '玻璃板仓', rows: magazineRows })
  }

  // ④ 溶剂/洗脱液瓶余量
  const bottleRows = (snapshot?.bottles || []).filter((row) => owns(row.bottle))
  if (bottleRows.length) {
    sections.push({ type: 'bottle', key: 'bottle', title: '溶剂瓶', rows: bottleRows })
  }

  // ⑤ 工位夹具上停着的单件 (粉桶/样品瓶) —— 只读, 清空走右键菜单的 danger 路径
  const seatRows = (snapshot?.payloadSeats || [])
    .filter((row) => owns(row.seat))
    .map((row) => ({ ...row, presence: presenceOf(row.seat) }))
  if (seatRows.length) {
    sections.push({ type: 'payloadSeat', key: 'payload-seat', title: '工位夹具上的件', rows: seatRows })
  }

  // ⑥ 薄层板停放位有板/无板
  const plateSeatRows = (snapshot?.seats || []).filter((row) => owns(row.seat))
  if (plateSeatRows.length) {
    sections.push({ type: 'seat', key: 'seat', title: '薄层板停放位', rows: plateSeatRows })
  }

  return sections
}

/**
 * 功能: 该工位是否管着任何物料 (决定工位页要不要出"物料"页签).
 *
 * 判据刻意**不看快照** —— 后端没连时快照是 null, 但料架该有物料页这件事不随连接状态变.
 * @param {object|null} manifest 绑定契约
 * @param {string|null} stationId 工位 id
 * @returns {boolean} 是否有物料
 */
export function stationHasMaterial(manifest, stationId) {
  if (!stationId) return false
  const derived = deriveSeatStations(manifest)
  for (const table of [derived, DECLARED_STATION]) {
    for (const owner of Object.values(table)) {
      if (owner === stationId) return true
    }
  }
  return false
}
