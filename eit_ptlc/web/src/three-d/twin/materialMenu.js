/**
 * 功能: 物料右键菜单的纯映射层 —— 身份信息 -> 可序列化菜单描述 (node --test 可测).
 *
 * 输出行结构 {key, label, op?, args?, danger?, disabled?, hint?, divider?, children?}:
 * 不含闭包 —— op 是动作名, 由 MaterialInteraction 映射到 materialWriteApi 的动词并
 * 套确认级 (danger=true 走危险确认)。确认级逐条对齐二维物料页的既有裁决:
 * 可逆翻转不确认, 覆盖/清空/清在途 danger。
 *
 * 硬规则:
 *   在途件只许"清在途", 禁改格账 (件在爪上是唯一能确认的事实);
 *   账本离线/陈旧时全部写项禁用;
 *   板仓堆整体一个目标 (账本只有张数, 无逐板身份)。
 */

const KIND_LABEL = { collector: '接粉收集器', bottle: '收集瓶' }
const CARRIER_LABEL = { gripper_plate96: '大夹爪', gripper_vial: '小夹爪' }
const AREA_LABEL = { 'staging-a': '中转托盘位A', 'staging-b': '中转托盘位B' }
const PLATES = [1, 2, 3, 4, 5, 6]

/** kind 的显示名 */
export function kindLabel(kind) { return KIND_LABEL[kind] || String(kind || '') }

/**
 * 功能: 身份信息的标题行文本.
 * @param {object} info identityAtMenuTime 的输出
 * @returns {string} 标题
 */
export function describeIdentity(info) {
  if (info.type === 'magazine') {
    const row = info.magazineRow
    const label = info.magazine === 'feed' ? '上料仓' : '下料仓'
    return row ? `${label} · ${row.count} 张` : label
  }
  const where = info.loc === 'staging' ? (AREA_LABEL[info.area] || info.area) : '货架'
  if (info.type === 'tray') {
    const plate = info.plate != null ? ` ${info.plate} 号板` : ' (空)'
    return `${where} · ${kindLabel(info.kind)}托盘${plate}`
  }
  const plate = info.plate != null ? `${info.plate} 号板` : '?'
  const base = `${kindLabel(info.kind)} ${plate} · ${info.hole} 号孔`
  if (info.transitCarrier) {
    return `${base} · 在${CARRIER_LABEL[info.transitCarrier] || info.transitCarrier}上`
  }
  if (info.seatedAt) return `${base} · 在${info.seatedAt.label || info.seatedAt.seat}上`
  const cell = info.cell
  if (cell) {
    const state = cell.state === 'FRESH' ? '未用'
      : (cell.sample_id ? `成品 ${cell.sample_id}` : '空孔')
    return `${base} · ${state}`
  }
  return base
}

/**
 * 功能: 组装菜单描述.
 * @param {object} info identityAtMenuTime 的输出
 * @param {object} [ctx] 上下文
 * @param {boolean} [ctx.available] 账本可写 (在线且非陈旧)
 * @param {string} [ctx.unavailableHint] 不可写时的原因文案; 缺省是"账本离线/陈旧"。
 *   工位物料页有未保存草稿时会传别的原因 —— 照搬"账本离线"会让人去追一个根本不存在的
 *   连接问题。
 * @returns {Array<object>} 菜单行
 */
export function buildMaterialMenu(info, ctx = {}) {
  const available = ctx.available !== false
  const offline = { disabled: true, hint: ctx.unavailableHint || '账本离线/陈旧, 暂不可写' }
  const guard = (row) => (available ? row : { ...row, ...offline })
  const rows = [{ key: 'head', label: describeIdentity(info), disabled: true }]

  // 在途件/在途整板: 只许清在途 (身份从当前快照读回, 去向必须人选)
  if (info.transitCarrier) {
    if (info.transitStale) {
      rows.push({ key: 'stale', label: '上一进程遗留, 请先盘点', disabled: true })
    }
    rows.push(guard({
      key: 'transit', label: '清在途…', danger: true,
      children: [
        { key: 'transit-rack', label: '记回货架', op: 'transit', danger: true,
          args: { carrier: info.transitCarrier, landAt: 'rack' } },
        { key: 'transit-staging', label: '记入中转', op: 'transit', danger: true,
          args: { carrier: info.transitCarrier, landAt: 'staging' } },
        { key: 'transit-clear', label: '只清行 (去向不明)', op: 'transit', danger: true,
          args: { carrier: info.transitCarrier, landAt: '' } },
      ],
    }))
    return rows
  }

  if (info.type === 'magazine') {
    const count = Number(info.magazineRow?.count ?? 0)
    rows.push(guard({ key: 'mag-up', label: '板数 +1', op: 'magazine',
                      args: { magazine: info.magazine, count: count + 1 } }))
    rows.push(guard({ key: 'mag-down', label: '板数 −1', op: 'magazine',
                      disabled: !available || count <= 0,
                      args: { magazine: info.magazine, count: Math.max(0, count - 1) } }))
    rows.push(guard({ key: 'edit', label: '盘点张数…', op: 'edit', args: {} }))
    return rows
  }

  if (info.type === 'tray') {
    if (info.loc === 'staging') {
      rows.push(guard({
        key: 'staging-set', label: '改记为…',
        children: PLATES.map((plate) => ({
          key: `staging-${plate}`, label: `${plate} 号板`, op: 'staging',
          disabled: !available || info.stagingPlate === plate,
          args: { area: info.area, plate },
        })),
      }))
      rows.push(guard({ key: 'staging-clear', label: '置空中转位', op: 'staging',
                        danger: true, disabled: !available || info.stagingPlate == null,
                        args: { area: info.area, plate: null } }))
      return rows
    }
    // 货架托盘: 在架账已投影进快照(rackLedger, 三维托盘显隐读它), 有板/无板给显式双入口
    rows.push(guard({
      key: 'rack', label: '在架标记…',
      children: [
        { key: 'rack-on', label: '标记有板', op: 'rack',
          args: { kind: info.kind, plate: info.plate, present: true } },
        { key: 'rack-off', label: '标记无板', op: 'rack',
          args: { kind: info.kind, plate: info.plate, present: false } },
      ],
    }))
    rows.push(guard({ key: 'plate-fresh', label: '整板全新', op: 'mark',
                      args: { kind: info.kind, plate: info.plate, state: 'FRESH' } }))
    // 三态词汇(2026-08-15): USED=已用件在位(粉桶画成倒扣), ABSENT=件全被拿走(不画)。
    // 旧"整板清空"就是拿走的意思, 对应现在的 ABSENT 而不是 USED。
    rows.push(guard({ key: 'plate-used', label: '整板标为已用', op: 'mark', danger: true,
                      args: { kind: info.kind, plate: info.plate, state: 'USED' } }))
    rows.push(guard({ key: 'plate-absent', label: '整板清空 (件已拿走)', op: 'mark', danger: true,
                      args: { kind: info.kind, plate: info.plate, state: 'ABSENT' } }))
    return rows
  }

  // 单件 / 空孔 (type: item | hole)
  if (info.plate == null) {
    rows.push({ key: 'no-plate', label: '该中转位为空, 无孔账可改', disabled: true })
    return rows
  }
  if (info.seatedAt) {
    rows.push(guard({ key: 'seat-clear', label: '清件位 (件已被拿走)', op: 'payloadSeat',
                      danger: true, args: { seat: info.seatedAt.seat } }))
    return rows
  }
  // 三态显式入口(隐藏当前态那一项): 新的=直立 / 已用=粉桶倒扣在位 / 不在位=不画
  const state = info.cell?.state
  const cellArgs = (next) => ({ kind: info.kind, plate: info.plate, hole: info.hole, state: next })
  if (state !== 'FRESH') {
    rows.push(guard({
      key: 'mark-fresh',
      label: info.cell?.sample_id ? '成品取走, 放入新件' : '放入未用耗材',
      op: 'mark', args: cellArgs('FRESH'),
    }))
  }
  if (state !== 'USED') {
    rows.push(guard({ key: 'mark-used', label: '标记为已用 (留在位上)', op: 'mark',
                      args: cellArgs('USED') }))
  }
  if (state !== 'ABSENT') {
    rows.push(guard({ key: 'mark-absent', label: '标记为不在位 (件已拿走)', op: 'mark',
                      args: cellArgs('ABSENT') }))
  }
  rows.push(guard({ key: 'edit', label: '编辑数量…', op: 'edit', args: {} }))
  return rows
}
