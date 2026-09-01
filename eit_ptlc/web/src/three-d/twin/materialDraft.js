/**
 * 功能: 物料改账的**草稿**模型 —— 改了先在三维里预览, 点保存才写账本, 点取消就丢弃.
 *
 * ⚠ 与仓内"不做乐观渲染"那条纪律的关系, 必须说清楚:
 *   PTLC_REALTIME_PROTOCOL.md §5.1 与 MaterialInteraction 的头注定的是"**写完**不要抢先
 *   画成功, 等推流回读". 那条依旧生效 —— 保存成功后草稿**立刻丢弃**, 画面回落到推流账本。
 *   本模块做的是**提交之前**的编辑预览: 全程有横幅声明"这是你的草稿, 不是设备实况",
 *   而且它从不代表任何"已写入"的状态。两者不冲突。
 *
 * 关键形状选择: applyDraft 作用在**原始 material_state 事件**(snake_case)上, 而不是
 * 归一化后的快照。于是 rack 板级汇总与 presence 连接由 MaterialStateStore 里那**一个**
 * normalizeSnapshot 重算 —— 预览与真相永远不可能用两套算法算出来; 而且两张事件键白名单
 * 一个字都不用动, materialGrid.contract.json 与 materialState.test.js 零改动。
 *
 * 刻意**不含** clearTransit / clearPayloadSeat: 在途与件位是"此刻爪上/座上有什么"的事实
 * 陈述, 不是可预览的账面编辑 —— 它们留在右键菜单的即时 + danger 路径。
 */

/** 草稿支持的写动词闭集 (与 materialWriteApi 的动词同名) */
export const DRAFT_VERBS = Object.freeze([
  'mark', 'setCellAmount', 'setStaging', 'setRack', 'setMagazine', 'setBottle', 'setSeat',
])

/**
 * 保存时的重放次序. 次序不是随便排的, 每一条都有理由:
 *   setStaging  先清后赋, 两个中转区不会瞬时持有同一板号
 *   setRack     板级在前, 孔级在后
 *   markPlate   **必须**在单孔之前 —— 后端 mark_plate 会把 6 个孔全刷成 sample_id='',
 *               放在单孔编辑后面会把它整片抹掉 (material_store.py mark_plate)
 *   mark        单孔
 *   setCellAmount 在 mark 之后, 让操作员填的粉量/液量/已淋洗压过状态重置
 *   其余        互不相干
 */
const REPLAY_ORDER = ['setStaging', 'setRack', 'markPlate', 'mark', 'setCellAmount',
  'setMagazine', 'setBottle', 'setSeat']

/** 哪些动词改完在三维里看得见 —— 界面据此告诉用户"这条只改账面数字" */
const VISIBLE_IN_3D = new Set(['mark', 'setCellAmount', 'setStaging', 'setRack', 'setMagazine'])

/**
 * 功能: 算一条改动的幂等键. 同一目标的后写覆盖先写.
 * @param {string} verb 写动词
 * @param {object} args 参数
 * @returns {string} 幂等键
 */
export function draftKey(verb, args) {
  switch (verb) {
    case 'mark':
    case 'setCellAmount':
      return args.hole === null || args.hole === undefined
        ? `${verb}:${args.kind}:${args.plate}`
        : `${verb}:${args.kind}:${args.plate}:${args.hole}`
    case 'setStaging': return `setStaging:${args.area}`
    case 'setRack': return `setRack:${args.kind}:${args.plate}`
    case 'setMagazine': return `setMagazine:${args.magazine}`
    case 'setBottle': return `setBottle:${args.bottle}`
    case 'setSeat': return `setSeat:${args.seat}`
    default: return `${verb}:${JSON.stringify(args)}`
  }
}

/**
 * 功能: 新建一份空草稿.
 * @returns {{entries: Map<string, object>, revision: number}} 草稿
 */
export function createDraft() {
  return { entries: new Map(), revision: 0 }
}

/**
 * 功能: 放入一条改动(同键覆盖).
 * @param {object} draft 草稿
 * @param {string} verb 写动词
 * @param {object} args 参数
 * @returns {string} 该条的幂等键
 */
export function putEntry(draft, verb, args) {
  if (!DRAFT_VERBS.includes(verb)) throw new Error(`不支持的草稿动词: ${verb}`)
  const key = draftKey(verb, args)
  draft.entries.set(key, { key, verb, args: { ...args } })
  draft.revision += 1
  return key
}

/**
 * 功能: 撤掉一条改动.
 * @param {object} draft 草稿
 * @param {string} key 幂等键
 * @returns {boolean} 是否真的删掉了
 */
export function removeEntry(draft, key) {
  const had = draft.entries.delete(key)
  if (had) draft.revision += 1
  return had
}

/**
 * 功能: 清空草稿.
 * @param {object} draft 草稿
 * @returns {void}
 */
export function clearDraft(draft) {
  if (!draft.entries.size) return
  draft.entries.clear()
  draft.revision += 1
}

/**
 * 功能: 按安全次序排出待提交的改动.
 * @param {object} draft 草稿
 * @returns {object[]} 有序条目
 */
export function replayOrder(draft) {
  const rank = (entry) => {
    // 整板 mark 与单孔 mark 是两个次序档 (整板会刷掉 6 个孔)
    const bucket = entry.verb === 'mark'
      && (entry.args.hole === null || entry.args.hole === undefined) ? 'markPlate' : entry.verb
    const index = REPLAY_ORDER.indexOf(bucket)
    return index < 0 ? REPLAY_ORDER.length : index
  }
  return [...draft.entries.values()].sort((a, b) => rank(a) - rank(b))
}

/**
 * 功能: 一条改动的中文描述(草稿清单每行一句).
 * @param {object} entry 草稿条目
 * @returns {{text: string, visible3d: boolean}} 描述与是否影响三维
 */
export function describeEntry(entry) {
  const { verb, args } = entry
  const kindZh = { collector: '粉桶', bottle: '样品瓶' }[args.kind] || args.kind
  const where = args.hole === null || args.hole === undefined
    ? `${kindZh}托盘 ${args.plate}`
    : `${kindZh}托盘 ${args.plate} 第 ${args.hole} 孔`
  let text
  switch (verb) {
    case 'mark':
      text = `${where} → ${
        { FRESH: '未用(新的)', USED: '已用', ABSENT: '不在位' }[args.state] || args.state}`
      break
    case 'setCellAmount': {
      const bits = []
      if (args.powder_mm3 !== undefined) bits.push(`粉 ${args.powder_mm3} mm³`)
      if (args.liquid_ml !== undefined) bits.push(`液 ${args.liquid_ml} mL`)
      if (args.eluted !== undefined) bits.push(args.eluted ? '已淋洗' : '未淋洗')
      text = `${where} → ${bits.join(' · ') || '不变'}`
      break
    }
    case 'setStaging':
      text = args.plate === null || args.plate === undefined
        ? `中转区 ${args.area} → 置空`
        : `中转区 ${args.area} → ${args.plate} 号板`
      break
    case 'setRack':
      text = `${kindZh}库位 ${args.plate} → ${args.present ? '有板' : '无板'}`
      break
    case 'setMagazine':
      text = `${args.magazine === 'feed' ? '上料仓' : '下料仓'} → ${args.count} 张`
      break
    case 'setBottle':
      text = `溶剂瓶 ${args.bottle} → ${args.volumeMl} mL`
      break
    case 'setSeat':
      text = `板位 ${args.seat} → ${args.present ? '有板' : '无板'}`
      break
    default:
      text = `${verb} ${JSON.stringify(args)}`
  }
  return { text, visible3d: VISIBLE_IN_3D.has(verb) }
}

/**
 * 功能: 把草稿叠加到一份原始 material_state 事件上.
 *
 * 纯函数: 返回**新的**事件对象, 入参一个字节都不动.
 * 空草稿返回原对象本身 (身份保持是承重的 —— 见 MaterialStateStore.status 的记忆化说明).
 *
 * 刻意**不模拟**的东西:
 *   presence[].present / raw / checked_at —— **敲个数字不会让光电传感器动**;
 *   presence[].ok —— 被草稿碰过的行一律置 null 并在界面上写明"对账结论待保存后重算",
 *                    这样既不必在 JS 里重抄后端的比对规则, 也不会显示一个过期的判定。
 *   summary —— 汇总计数由二维页用, 三维不读。
 *
 * @param {object|null} event 原始 material_state 事件
 * @param {object} draft 草稿
 * @returns {object|null} 叠加后的事件
 */
export function applyDraft(event, draft) {
  if (!event || !draft || draft.entries.size === 0) return event
  const next = { ...event }
  /** 被草稿碰过的 presence.location_id, 它们的对账结论要置空 */
  const touchedLocations = new Set()

  // ── cells: mark(状态) 与 setCellAmount(余量) 都落在这里 ──────────────
  // 按 replayOrder 而不是插入序合并补丁: 保存时 mark 先于 setCellAmount 重放
  // (material_store.mark 对 FRESH/ABSENT 会清内容物), 预览必须算出同一个结果,
  // 否则"先填粉量再翻状态"的草稿会预览一套、落账另一套。
  const cellPatch = new Map()   // 'kind:plate:hole' -> patch
  const platePatch = new Map()  // 'kind:plate' -> patch (整板 mark)
  for (const entry of replayOrder(draft)) {
    const { verb, args } = entry
    if (verb !== 'mark' && verb !== 'setCellAmount') continue
    const patch = verb === 'mark'
      ? {
          state: args.state,
          // 与后端 mark() 同语义: FRESH=换新件、ABSENT=件被拿走, 内容物随件清零
          ...(args.state === 'FRESH' || args.state === 'ABSENT'
            ? { sample_id: '', powder_mm3: 0, liquid_ml: 0, eluted: 0 } : {}),
        }
      : {
          ...(args.powder_mm3 !== undefined ? { powder_mm3: Number(args.powder_mm3) } : {}),
          ...(args.liquid_ml !== undefined ? { liquid_ml: Number(args.liquid_ml) } : {}),
          ...(args.eluted !== undefined ? { eluted: args.eluted ? 1 : 0 } : {}),
        }
    if (args.hole === null || args.hole === undefined) {
      const key = `${args.kind}:${args.plate}`
      platePatch.set(key, { ...(platePatch.get(key) || {}), ...patch })
    } else {
      const key = `${args.kind}:${args.plate}:${args.hole}`
      cellPatch.set(key, { ...(cellPatch.get(key) || {}), ...patch })
    }
  }
  if (cellPatch.size || platePatch.size) {
    next.cells = (event.cells || []).map((cell) => {
      const plateKey = `${cell.kind}:${cell.plate}`
      const cellKey = `${plateKey}:${cell.hole}`
      const patch = { ...(platePatch.get(plateKey) || {}), ...(cellPatch.get(cellKey) || {}) }
      return Object.keys(patch).length ? { ...cell, ...patch } : cell
    })
  }

  // ── staging: 中转区停着几号板 ────────────────────────────────────────
  const stagingEntries = [...draft.entries.values()].filter((e) => e.verb === 'setStaging')
  if (stagingEntries.length) {
    next.staging = { ...(event.staging || {}) }
    for (const { args } of stagingEntries) {
      const before = next.staging[args.area] || {}
      next.staging[args.area] = { ...before, plate: args.plate ?? null }
      touchedLocations.add(args.area)
    }
  }

  // ── rack: 人工在架账 -> presence[].expected (present 是光电读数, 不许动)
  //          同时补丁 event.rack 行本体 —— 三维托盘显隐读的是它的投影(rackLedger) ──
  const rackEntries = [...draft.entries.values()].filter((e) => e.verb === 'setRack')
  if (rackEntries.length) {
    const wanted = new Map(
      rackEntries.map(({ args }) => [`rack.${args.kind}.${args.plate}`, Boolean(args.present)]),
    )
    next.presence = (event.presence || []).map((row) => {
      if (!wanted.has(row.location_id)) return row
      touchedLocations.add(row.location_id)
      return { ...row, expected: wanted.get(row.location_id) }
    })
    next.rack = (event.rack || []).map((row) => {
      const want = wanted.get(`rack.${row.kind}.${row.plate}`)
      // 保持后端 0/1 整数形制, 归一化交给 normalizeSnapshot 那一个出口
      return want === undefined ? row : { ...row, present: want ? 1 : 0 }
    })
  }

  // ── magazines / bottles / seats: 各自一张平表 ────────────────────────
  const magazineWanted = new Map([...draft.entries.values()]
    .filter((e) => e.verb === 'setMagazine')
    .map(({ args }) => [args.magazine, Math.max(0, Number(args.count) || 0)]))
  if (magazineWanted.size) {
    next.magazines = (event.magazines || []).map((row) => (
      magazineWanted.has(row.magazine) ? { ...row, count: magazineWanted.get(row.magazine) } : row
    ))
  }

  const bottleWanted = new Map([...draft.entries.values()]
    .filter((e) => e.verb === 'setBottle')
    .map(({ args }) => [args.bottle, Math.max(0, Number(args.volumeMl) || 0)]))
  if (bottleWanted.size) {
    next.bottles = (event.bottles || []).map((row) => (
      bottleWanted.has(row.bottle) ? { ...row, volume_ml: bottleWanted.get(row.bottle) } : row
    ))
  }

  const seatWanted = new Map([...draft.entries.values()]
    .filter((e) => e.verb === 'setSeat')
    .map(({ args }) => [args.seat, Boolean(args.present)]))
  if (seatWanted.size) {
    next.seats = (event.seats || []).map((row) => (
      seatWanted.has(row.seat) ? { ...row, present: seatWanted.get(row.seat) } : row
    ))
  }

  // 被碰过的点位: 对账结论作废(不在 JS 里重抄后端的比对规则, 也不显示过期判定)
  if (touchedLocations.size) {
    next.presence = (next.presence || event.presence || []).map((row) => (
      touchedLocations.has(row.location_id) ? { ...row, ok: null } : row
    ))
  }

  return next
}
