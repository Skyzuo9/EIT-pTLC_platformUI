/**
 * 功能: L2 亚秒过渡 —— 从流程事件包络推断"板这一刻被吸起 / 放下到哪".
 *
 * 为什么需要 L2: L1(调度器 samples.position)是权威且跨刷新的, 但它的粒度是
 * "一段原子流程 DONE 才记一笔", 而一段可能跑十几分钟。只靠 L1, 板会在展缸里静止十分钟
 * 然后瞬移到刮板台。L2 只负责把这十几分钟里"板正跟着手走"画出来, **不构成第二套账本** ——
 * 它给出的迁移意图必须由 PlateBinding 拿 L1 的相邻性闸门校验后才生效。
 *
 * 落点判据用"末点映射"而不是脚本名, 因为一个脚本服务多个落点:
 *   robot_suction_pick/put 的 station_id ∈ {spotting, scrape, waste};
 *   robot_tank_put/pick 的 tank_id ∈ 1..8。
 * 而实读全部取放脚本确认: **每个吸/放动作都紧跟在它的基准点之后, 无一例外**
 *   feed 仓 P21 / 点样座 P19 / 刮板台 P65 / 展缸 P11-P18 / 废板仓 P22。
 * 脚本入参只作交叉校验, 不一致时以末点为准并计数告警。
 *
 * 这套判据对**面板手动单发**同样正确: 人手动移到 P19 再手动 suction-on,
 * 那确实就是从点样座取板。
 */
import { PLATE_SLOT } from './PlateSlots.js'

/**
 * 取放基准点 → 停放位。
 * ⚠ **P64 故意不在表里**: robot_suction_pick.yaml:184 注明"刮板位取/放同基点 P65,
 *   P64 弃用保留在点表, 勿再引用"。真收到 P64 说明有人引用了废弃点, 走告警分支。
 */
export const POINT_TO_SLOT = Object.freeze({
  P21: PLATE_SLOT.FEEDLIFT,
  P19: PLATE_SLOT.SPOT_SEAT,
  P65: PLATE_SLOT.SCRAPE_TABLE,
  P22: PLATE_SLOT.WASTE,
  P11: 'tank:1',
  P12: 'tank:2',
  P13: 'tank:3',
  P14: 'tank:4',
  P15: 'tank:5',
  P16: 'tank:6',
  P17: 'tank:7',
  P18: 'tank:8',
})

/** 已弃用但仍在点表里的取放点; 命中即告警, 绝不当成刮板台。 */
export const DEPRECATED_POINTS = Object.freeze(new Set(['P64']))

/** robot_suction_* 的 station_id → 停放位(仅用于交叉校验)。 */
const STATION_ID_TO_SLOT = Object.freeze({
  spotting: PLATE_SLOT.SPOT_SEAT,
  scrape: PLATE_SLOT.SCRAPE_TABLE,
  waste: PLATE_SLOT.WASTE,
})

/** 1 号刀(玻璃吸盘)。driver 的 TOOL_ALLOWED_ACTIONS 只允许它做吸放与上下翻转。 */
const SUCTION_TOOL = 1

export class PlateTransferTracker {
  /**
   * @param {object} opts
   * @param {() => number} opts.getMountedTool 取当前挂载工具号(权威态来自 robot_pose/telemetry)
   */
  constructor({ getMountedTool } = {}) {
    this._getMountedTool = typeof getMountedTool === 'function' ? getMountedTool : () => 0
    /** @type {Map<string, string>} run_id -> 最近一次命中映射表的取放基准点对应的停放位 */
    this._lastSlot = new Map()
    /** @type {Map<string, object>} run_id -> 最内层 robot_* 脚本的入参上下文(交叉校验用) */
    this._scriptCtx = new Map()
    /** @type {Array<object>} 待消费的迁移意图 */
    this._pending = []
    this._mismatches = 0
    this._deprecatedPointHits = 0
  }

  /**
   * 功能: 消费一条流程事件.
   * @param {object} event 事件(vm_node_enter / vm_node_done / operation_done|failed)
   * @param {object} args 该节点的入参(done 事件必须由调用方从 enter 配对取回)
   * @returns {void}
   */
  handleEvent(event, args = {}) {
    const type = String(event?.type || '')
    if (type === 'operation_done' || type === 'operation_failed') {
      const runId = String(event?.run_id || '')
      this._lastSlot.delete(runId)
      this._scriptCtx.delete(runId)
      return
    }
    if (type === 'vm_node_enter') {
      if (String(event?.op || '') === 'run_script') this._recordScriptCtx(event, args)
      return
    }
    if (type !== 'vm_node_done') return
    if (String(event?.op || '') !== 'call') return
    if (String(event?.status || '').toUpperCase() !== 'DONE') return

    const action = String(event?.action || '')
    if (action === 'robot.move_to_point') this._recordPoint(event, args)
    else if (action === 'robot.tool_action') this._recordToolAction(event, args)
  }

  /** 记住取放脚本的入参, 供交叉校验(只认得出落点的那几个)。 */
  _recordScriptCtx(event, args) {
    const script = String(event?.action || '')          // run_script 节点的 action 是被调脚本名
    const runId = String(event?.run_id || '')
    let hinted = ''
    if (/^robot_suction_(put|pick)$/.test(script)) {
      hinted = STATION_ID_TO_SLOT[String(args?.station_id || '')] || ''
    } else if (/^robot_tank_(put|pick)$/.test(script)) {
      const tank = Number(args?.tank_id)
      if (Number.isInteger(tank) && tank >= 1 && tank <= 8) hinted = `tank:${tank}`
    } else if (/^robot_feed_lift_pick_/.test(script)) {
      hinted = PLATE_SLOT.FEEDLIFT
    }
    if (hinted) this._scriptCtx.set(runId, { script, hinted })
  }

  /**
   * 记住"末点"。**只有命中 POINT_TO_SLOT 的点才更新** —— 命名进近点
   * (spotting.put.approach_far 等)与过渡点(P1/P4/P5/P63/P75/P84/P59/P86)一律不动它,
   * 否则退刀路径会在 suction-off 之前把末点冲掉。
   */
  _recordPoint(event, args) {
    const point = String(args?.point_id_or_robot_name || '')
    if (!point) return
    if (DEPRECATED_POINTS.has(point)) {
      this._deprecatedPointHits += 1
      return
    }
    const slot = POINT_TO_SLOT[point]
    if (!slot) return
    this._lastSlot.set(String(event?.run_id || ''), slot)
  }

  /** suction-on/off 完成的那一刻, 用末点定出板从哪来 / 放到哪去。 */
  _recordToolAction(event, args) {
    const toolAction = String(args?.action || '')
    if (toolAction !== 'suction-on' && toolAction !== 'suction-off') return
    if (Number(this._getMountedTool()) !== SUCTION_TOOL) return

    const runId = String(event?.run_id || '')
    const slot = this._lastSlot.get(runId) || ''
    if (!slot) {
      // 拿不到末点就绝不猜落点 —— 宁可不动画面, 也不把板挪到一个编出来的位置
      this._mismatches += 1
      return
    }

    const hinted = this._scriptCtx.get(runId)?.hinted || ''
    const disagrees = Boolean(hinted) && hinted !== slot
    if (disagrees) this._mismatches += 1

    this._pending.push({
      kind: toolAction === 'suction-on' ? 'pick' : 'put',
      slot,
      runId,
      script: String(event?.script || ''),
      hinted,
      disagrees,
      ts: Number(event?.ts) || 0,
    })
  }

  /** 取走本次积累的迁移意图(读后即清), 由 PlateBinding 过 L1 相邻性闸门后才落地。 */
  consumeTransfers() {
    const out = this._pending
    this._pending = []
    return out
  }

  /** 断流: 在途的末点与脚本上下文都不再可信。 */
  reset() {
    this._lastSlot.clear()
    this._scriptCtx.clear()
    this._pending.length = 0
  }

  /** 供 HUD 的只读诊断。 */
  status() {
    return {
      tracking: this._lastSlot.size,
      pending: this._pending.length,
      mismatches: this._mismatches,
      deprecatedPointHits: this._deprecatedPointHits,
    }
  }
}
