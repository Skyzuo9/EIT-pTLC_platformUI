/**
 * 功能: L1(调度器权威位置) 与 L2(流程事件亚秒过渡) 的仲裁 —— 纯 reducer, 不碰 three.
 *
 * 核心不变量: **"L1 落后" ≠ "冲突"**。
 * 调度器是"一段原子流程 DONE 才记一笔", 而 L2 在段中途就把板挪走了, 所以快照里出现
 * 板的**历史位置**是常态, 不是错误。判据只能是 `l2Trail`(本板经 L2 走过的槽位轨迹),
 * **绝不能用时间戳** —— scheduler_update 有 0.5s 节流 + 500ms 去抖 + 3s 轮询,
 * 事件时刻与快照时刻根本不可比。
 *
 * 只有 `l1Slot` 既不等于当前位置、也不在轨迹里, 才是真冲突 —— 那时以 L1 为准。
 *
 * 另有一条旁路 `recoverToSuction`: 页面刷新后 L2 包络全丢, 靠吸盘真空位(DO3)把
 * "手上有板"重建回来。它不是第三套账本, 只是把一位物理事实翻译成一次迁移。
 */
import { PLATE_SLOT, isAdjacent } from './PlateSlots.js'

/** 位置的权威来源。L3 = 无调度器上下文(手动直跑), 永不升级。 */
export const AUTHORITY = Object.freeze({ L1: 'L1', L2: 'L2', L3: 'L3' })

/**
 * 功能: 新建一块板的状态.
 * @param {object} init
 * @returns {object} 板状态(纯对象)
 */
export function createPlate({ plateId, sampleId = '', slot = '', authority = AUTHORITY.L1 } = {}) {
  return {
    plateId: String(plateId || ''),
    sampleId: String(sampleId || ''),
    slot: String(slot || ''),
    authority,
    l2Trail: [],
    suspect: false,
    /** 这块板是靠吸盘真空位恢复出来的(见 recoverToSuction), 而不是由 L2 包络取起来的。 */
    recovered: false,
  }
}

/**
 * 功能: 施加一次 L2 迁移意图.
 *
 * pick 的闸门是"板必须确实在那儿": 末点说从刮板台取, 而这块板账上在展缸, 说明推断错了 ——
 * **不迁移**, 计一次告警。put 的闸门是相邻性: 越级(如从料仓直接进废板仓)仍然照迁,
 * 但标 suspect 让 HUD 黄标, 因为物理上板确实被放下了, 藏起来只会更难查。
 *
 * @param {object} plate 板状态
 * @param {{kind: 'pick'|'put', slot: string}} transfer 迁移意图
 * @returns {{plate: object, accepted: boolean, reason: string}}
 */
export function applyTransfer(plate, transfer) {
  const kind = transfer?.kind
  const target = String(transfer?.slot || '')
  if (!plate || !target) return { plate, accepted: false, reason: 'invalid' }

  if (kind === 'pick') {
    if (plate.slot === PLATE_SLOT.CARRIED) {
      return { plate, accepted: false, reason: 'already_carried' }
    }
    if (plate.slot !== target) {
      return { plate, accepted: false, reason: 'slot_mismatch' }
    }
    return {
      plate: {
        ...plate,
        slot: PLATE_SLOT.CARRIED,
        authority: demote(plate.authority),
        l2Trail: [...plate.l2Trail, target],
        recovered: false,          // 有包络背书, 不再是真空位恢复出来的
      },
      accepted: true,
      reason: '',
    }
  }

  if (kind === 'put') {
    if (plate.slot !== PLATE_SLOT.CARRIED) {
      return { plate, accepted: false, reason: 'not_carried' }
    }
    const origin = plate.l2Trail[plate.l2Trail.length - 1] || ''
    const skipped = Boolean(origin) && !isAdjacent(origin, target)
    return {
      plate: {
        ...plate,
        slot: target,
        authority: demote(plate.authority),
        l2Trail: [...plate.l2Trail, target],
        suspect: plate.suspect || skipped,
        recovered: false,          // 板已落地, 恢复态到此为止
      },
      accepted: true,
      reason: skipped ? 'not_adjacent' : '',
    }
  }

  return { plate, accepted: false, reason: 'unknown_kind' }
}

/** L3 的板永不升级到 L2/L1: 它压根没有账本背书, 别让 HUD 看起来更可信。 */
function demote(authority) {
  return authority === AUTHORITY.L3 ? AUTHORITY.L3 : AUTHORITY.L2
}

/**
 * 功能: 施加一帧 L1 权威位置.
 *
 * @param {object} plate 板状态
 * @param {string} l1Slot 调度器给出的位置
 * @returns {{plate: object, outcome: 'agree'|'lagging'|'corrected'|'ignored'}}
 */
export function applyLedger(plate, l1Slot) {
  const target = String(l1Slot || '')
  if (!plate || !target) return { plate, outcome: 'ignored' }
  if (plate.authority === AUTHORITY.L3) return { plate, outcome: 'ignored' }

  if (plate.slot === target) {
    return {
      plate: { ...plate, authority: AUTHORITY.L1, l2Trail: [], suspect: false, recovered: false },
      outcome: 'agree',
    }
  }

  // L1 报的是这块板刚离开的某个位置 —— 段还没 DONE, 账本本就该落后。画面不动, 也不告警。
  if (plate.l2Trail.includes(target)) {
    return { plate, outcome: 'lagging' }
  }

  // 既不等于当前位置也不在轨迹里 = 真冲突。以账本为准, 清掉 L2 的推断痕迹。
  return {
    plate: { ...plate, slot: target, authority: AUTHORITY.L1, l2Trail: [], suspect: false, recovered: false },
    outcome: 'corrected',
  }
}

/**
 * 功能: 按吸盘真空位把板恢复到手上 —— 刷新后重建"手上有板"的唯一入口.
 *
 * 真空位(DO3)是**物理事实**而不是推断: 它说吸盘带电, 那手上就有板。所以这条迁移
 * 不设 pick 那样的"板必须确实在那儿"闸门 —— 页面刚刷新时账本还没到, 拿什么闸都是空的。
 * 但"是哪块板"仍旧只能由调用方按账本归属, 归属不到就是 L3, 本函数一个字都不猜。
 *
 * ⚠ `fromSlot` 必须写进 `l2Trail`: 账本 3s 一帧, 它眼里这块板还停在 fromSlot。没有轨迹,
 * `applyLedger` 会判成真冲突, 每 3 秒把板从手上拽回停放位 —— 画面来回抽搐。有了轨迹
 * 就判 `lagging`(画面不动、不告警), 与 L2 正常取起来的板完全同构。
 *
 * @param {object} plate 板状态
 * @param {string} [fromSlot] 板的来处(账本位置); 给了才有轨迹背书与落点提示
 * @returns {object} 恢复后的板状态; 已经在手上则原样返回
 */
export function recoverToSuction(plate, fromSlot = '') {
  if (!plate || plate.slot === PLATE_SLOT.CARRIED) return plate
  const origin = String(fromSlot || '')
  return {
    ...plate,
    slot: PLATE_SLOT.CARRIED,
    authority: demote(plate.authority),
    l2Trail: origin ? [...plate.l2Trail, origin] : [...plate.l2Trail],
    recovered: true,
  }
}

/**
 * 功能: 重连 / 首帧 / 后端重启后的强制重同步 —— 只信 L1.
 *
 * 刷新页面时机器人可能正持着板, 但包络已经丢了。此时把板画在**上一个停放位**而不是
 * 画在手上: 账本说它在那儿, 那就是当前唯一有依据的说法。下一次 suction 事件自动归正。
 *
 * @param {object} plate 板状态
 * @param {string} l1Slot 调度器给出的位置
 * @returns {object} 重同步后的板状态
 */
export function resyncToLedger(plate, l1Slot) {
  const target = String(l1Slot || '')
  if (!plate || !target || plate.authority === AUTHORITY.L3) return plate
  return { ...plate, slot: target, authority: AUTHORITY.L1, l2Trail: [], suspect: false, recovered: false }
}
