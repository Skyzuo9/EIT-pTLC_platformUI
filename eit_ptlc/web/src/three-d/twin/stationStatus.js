/**
 * 功能: 把设备遥测快照里的裸数值翻成操作员读得懂的中文.
 *
 * 这是本次改造的第一诉求: 旧面板把快照剩下的标量**原样**倒出来, 于是机械臂那张卡片写着
 * `check_result 0 / last_action 24 / robot_mode 5 / speed_factor 20` —— 全仓当时没有任何
 * 一张 robot_mode / last_action / check_result 的释义表, 数值真源只在 Python 驱动里。
 *
 * 三条纪律:
 *
 * ① **合并散表, 不新增第 N 份。** L2_STATE 的真源从 sim/simDiagRows.js 搬到这里 (那边
 *    改为从这里派生, 形状一字不变); 健康度/MODE_State/地轨站位并进 utils/deviceLabels.js;
 *    展缸状态码继续只认 manifest.tankStateStyles, 一个字都不重述。
 *
 * ② **开放世界: 认不出的字段降级, 绝不丢弃。** 没有 fieldSpec 的快照键自动落进
 *    engineer 层原样显示。单测断言 `ops ∪ engineer === 快照全部非空键` —— 后端新加一个
 *    镜像字段永远不会人间蒸发。这与 MaterialStateStore 那两张白名单是同一种绊线纪律。
 *    顺带修掉一个既有 bug: error_ids 是数组, 旧实现被 `typeof === 'object'` 滤掉了,
 *    而它正是后端 derive_health 判故障的依据 —— 报警时面板上什么都不显示。
 *
 * ③ **数值真源在 Python, 这里是副本, 靠看门狗锁住。** 见
 *    tests/three-d/plcStatusLabels.contract.json 与两侧的漂移测试。
 *    中文措辞不进契约 (那是 UI 文案), 进契约的是数字键集与英文名。
 */
import { healthText, railStationText } from '../../utils/deviceLabels.js'
import { robotFaultText } from '../../stores/alarms.js'
import { PLC_SEMANTICS } from './plcSemantics.generated.js'

/**
 * 工位 L2 动作状态机.
 * 真源: eit_ptlc/controller/plc_controller.py::PLCActionState
 */
export const L2_STATE = Object.freeze({
  0: { en: 'IDLE', zh: '空闲', tone: 'muted' },
  10: { en: 'RUNNING', zh: '执行中', tone: 'busy' },
  20: { en: 'DONE', zh: '已完成', tone: 'ok' },
  30: { en: 'REJECTED', zh: '被拒绝', tone: 'warn' },
  40: { en: 'ERROR', zh: '故障', tone: 'bad' },
  50: { en: 'INTERRUPTED', zh: '被中断', tone: 'warn' },
})

/**
 * 工位安全态 —— 描述"板还在不在爪里"这类没法自动确认的状态.
 * 真源: eit_ptlc/controller/plc_controller.py::PLCActionSafeState
 */
export const L2_SAFE_STATE = Object.freeze({
  0: { en: 'UNKNOWN', zh: '未知', tone: 'muted' },
  10: { en: 'READY', zh: '就绪', tone: 'ok' },
  20: { en: 'PLATE_HELD_UNVERIFIED', zh: '夹着板 · 未确认', tone: 'warn' },
  30: { en: 'RELEASE_READY_UNVERIFIED', zh: '可松开 · 未确认', tone: 'warn' },
  90: { en: 'RECOVERY_REQUIRED', zh: '需人工恢复', tone: 'bad' },
})

/**
 * 机器人控制器工作模式.
 * 真源: eit_ptlc/driver/dobot_tcp_driver.py::RobotMode
 */
export const ROBOT_MODE = Object.freeze({
  1: { en: 'INIT', zh: '初始化中', tone: 'muted' },
  2: { en: 'BRAKE_OPEN', zh: '抱闸已松开', tone: 'warn' },
  3: { en: 'POWEROFF', zh: '本体未上电', tone: 'muted' },
  4: { en: 'DISABLED', zh: '未使能', tone: 'muted' },
  5: { en: 'ENABLED_IDLE', zh: '已使能 · 待命', tone: 'ok' },
  6: { en: 'BACKDRIVE', zh: '拖动示教中', tone: 'warn' },
  7: { en: 'RUNNING', zh: '运行中', tone: 'busy' },
  8: { en: 'SINGLE_MOVE', zh: '单步运动中', tone: 'busy' },
  9: { en: 'ERROR', zh: '故障', tone: 'bad' },
  10: { en: 'PAUSE', zh: '已暂停', tone: 'warn' },
  11: { en: 'COLLISION', zh: '碰撞停机', tone: 'bad' },
})

/**
 * 机器人最近一次下发的动作码.
 * 真源: eit_ptlc/driver/dobot_tcp_driver.py 里的 last_action=N 赋值点
 * (404 查询 / 546 关节增量 / 555 直线或关节 / 632、738 工具动作 / 833 点位运动).
 * 这是遗留 Modbus/Lua MVP 的动作码, 对操作员无意义, 故恒归工程师层.
 */
export const ROBOT_LAST_ACTION = Object.freeze({
  24: '状态查询',
  25: '关节运动 (MovJ)',
  27: '直线运动 (MovL)',
  28: '工具动作 / DO 直控',
  29: '关节增量 (RelJointMovJ)',
})

/** 工位 L2 前缀 (plcSemantics 的键) <- 三维工位 id */
const STATION_L2_PREFIX = Object.freeze({
  SAMPLING: 'Sampling',
  DEVELOP: 'Develop',
  COLLECT: 'Collect',
  PHOTOSCRAPE: 'PhotoScrape',
  FEEDLIFT: 'FeedLift',
  PUMP: 'Pump',
  RAIL: 'Rail',
  STAGINGA: 'StagingA',
})

/**
 * 恒不进字段表的键 —— 它们**已经在别的区块里画了**, 不是被丢掉.
 *
 * pose/joint  机械臂位姿, 三维画面本身就是它;
 * *ActPos     轴当前位置, 「运动轴」区块有带行程条的专门呈现;
 * current_position  单数形式的旧字段, 后端已改用 current_positions.
 *
 * 这张表是**显式**的, 且被单测按三分断言 (ops ∪ engineer ∪ hidden === 全部非空键) ——
 * 这样"有意不显示"与"不小心漏了"永远分得清.
 * @param {string} key 字段名
 * @returns {boolean} 是否恒不显示
 */
export function isHiddenKey(key) {
  return key === 'pose' || key === 'joint' || key === 'current_position' || key.endsWith('ActPos')
}

/**
 * 功能: 取某工位在 plcSemantics 里的记录.
 * @param {string} stationId 三维工位 id
 * @returns {object|null} 工位语义记录
 */
export function semanticsOf(stationId) {
  const prefix = STATION_L2_PREFIX[stationId]
  return prefix ? PLC_SEMANTICS[prefix] || null : null
}

/**
 * 功能: 把 ActiveCode 翻成动作中文名.
 *
 * 优先用 /api/actions 目录里的中文 label (那是给人看的正式名), 回落到 spec 里的
 * POU 名, 再回落到"动作码 N" —— 每一层都比印一个裸数字强.
 * @param {string} stationId 三维工位 id
 * @param {number} code 动作码
 * @param {object[]} actionCatalog /api/actions 目录
 * @returns {string} 动作名
 */
export function actionCodeText(stationId, code, actionCatalog = []) {
  if (!Number.isFinite(Number(code)) || Number(code) === 0) return ''
  const num = Number(code)
  const prefix = (STATION_L2_PREFIX[stationId] || '').toLowerCase()
  const hit = (actionCatalog || []).find(
    (action) => Number(action.action_code) === num
      && String(action.station || '').toLowerCase().replace(/_/g, '') === prefix,
  )
  if (hit?.label) return hit.label
  const spec = semanticsOf(stationId)
  return spec?.actions?.[String(num)]?.name || `动作码 ${num}`
}

/**
 * 功能: 把 Step 翻成"第 k/n 段".
 *
 * 刻意不译 phase 的英文蛇形名 —— 手工翻译会造出一份没有看门狗的第二真源.
 * 给操作员的是**位置**(进行到哪一步了), phase 原文只在工程师层出现.
 * @param {string} stationId 三维工位 id
 * @param {number} activeCode 当前动作码
 * @param {number} step 当前段号
 * @returns {{text: string, phase: string}} 位置文本与 phase 原文
 */
export function stepText(stationId, activeCode, step) {
  const spec = semanticsOf(stationId)
  const action = spec?.actions?.[String(activeCode)]
  const steps = action?.steps || []
  const phase = (steps.find(([value]) => value === Number(step)) || [])[1] || ''
  if (!steps.length) return { text: `第 ${step} 段`, phase }
  const order = []
  for (const [value] of steps) if (!order.includes(value)) order.push(value)
  const index = order.indexOf(Number(step))
  if (index < 0) return { text: `第 ${step} 段`, phase }
  return { text: `第 ${index + 1}/${order.length} 段`, phase }
}

/**
 * 功能: 把 ErrorCode 翻成中文.
 * @param {string} stationId 三维工位 id
 * @param {number} activeCode 当前动作码
 * @param {number} errorCode 错误码
 * @returns {string} 中文说明; 查不到时给码本身
 */
export function errorCodeText(stationId, activeCode, errorCode) {
  const code = Number(errorCode)
  if (!Number.isFinite(code) || code === 0) return ''
  const spec = semanticsOf(stationId)
  if (!spec) return `错误码 ${code}`
  const own = spec.actions?.[String(activeCode)]?.errors?.[String(code)]
  if (own) return own
  const gate = spec.gateErrors?.[String(code)]
  if (gate) return gate
  // 派发器的"未登记动作码"错误
  if (code === spec.unknownCodeError) return '上位机下发了 PLC 不认识的动作码'
  // 同一个码可能在别的动作下登记过 —— 给出来并注明来源不确定, 好过只印数字
  for (const action of Object.values(spec.actions || {})) {
    const hit = action.errors?.[String(code)]
    if (hit) return `${hit}（按其他动作的同码释义）`
  }
  return `错误码 ${code}`
}

/**
 * 字段释义表. 每项 {label, tier, zh(value, ctx), tone(value, ctx)}.
 * tier: ops = 操作员看得懂且用得上; engineer = 只对排障有意义.
 */
const L2_FIELD_SPEC = {
  State: {
    label: '动作状态', tier: 'ops',
    zh: (v) => L2_STATE[v]?.zh || `未知状态 ${v}`,
    tone: (v) => L2_STATE[v]?.tone || 'muted',
  },
  ActiveCode: {
    label: '当前动作', tier: 'ops',
    zh: (v, ctx) => actionCodeText(ctx.stationId, v, ctx.actionCatalog) || '无',
    tone: () => 'muted',
  },
  Step: {
    label: '进行到', tier: 'ops',
    // 只在真的在跑的时候有意义; 空闲时段号是上一次的残留
    hidden: (v, ctx) => Number(ctx.snapshot?.State) !== 10,
    zh: (v, ctx) => stepText(ctx.stationId, ctx.snapshot?.ActiveCode, v).text,
    tone: () => 'muted',
  },
  ErrorCode: {
    label: '故障原因', tier: 'ops',
    hidden: (v) => !Number(v),
    zh: (v, ctx) => errorCodeText(ctx.stationId, ctx.snapshot?.ActiveCode, v),
    tone: () => 'bad',
  },
  Retryable: {
    label: '可重试', tier: 'ops',
    hidden: (v, ctx) => !Number(ctx.snapshot?.ErrorCode),
    zh: (v) => (v ? '是 —— 排除原因后可直接重发' : '否 —— 需先复位'),
    tone: (v) => (v ? 'warn' : 'bad'),
  },
  SafeState: {
    label: '安全状态', tier: 'ops',
    // 就绪是常态, 不占版面; 其余四档都要显眼
    hidden: (v) => Number(v) === 10,
    zh: (v) => L2_SAFE_STATE[v]?.zh || `未知 ${v}`,
    tone: (v) => L2_SAFE_STATE[v]?.tone || 'muted',
  },
  AcceptedSeq: { label: '已受理序号', tier: 'engineer' },
  CompletedSeq: { label: '已完成序号', tier: 'engineer' },
  Pump_Vacuum_On: {
    label: '真空泵', tier: 'ops',
    zh: (v) => (v ? '开' : '关'),
    tone: (v) => (v ? 'busy' : 'muted'),
  },
  Expand_Waste_Empty_G1: {
    label: '废液桶1', tier: 'ops',
    zh: (v) => (v ? '空 —— 需更换' : '有余量'),
    tone: (v) => (v ? 'warn' : 'ok'),
  },
  Expand_Waste_Empty_G2: {
    label: '废液桶2', tier: 'ops',
    zh: (v) => (v ? '空 —— 需更换' : '有余量'),
    tone: (v) => (v ? 'warn' : 'ok'),
  },
  current_positions: {
    label: '机械臂站位', tier: 'ops',
    zh: (v) => railStationText(v),
    tone: () => 'muted',
  },
}

const ROBOT_FIELD_SPEC = {
  connected: {
    label: '控制器连接', tier: 'ops',
    zh: (v) => (v ? '已连接' : '未连接'),
    tone: (v) => (v ? 'ok' : 'bad'),
  },
  robot_mode: {
    label: '工作模式', tier: 'ops',
    zh: (v) => ROBOT_MODE[v]?.zh || `未知模式 ${v}`,
    tone: (v) => ROBOT_MODE[v]?.tone || 'muted',
  },
  error_ids: {
    label: '控制器报警', tier: 'ops',
    // 旧实现把它整个滤掉了 —— 数组过不了 typeof !== 'object' 那道判断
    hidden: (v) => !Array.isArray(v) || v.length === 0,
    zh: (v) => `${v.length} 项：${v.join(', ')}`,
    tone: () => 'bad',
  },
  speed_factor: {
    label: '全局速度', tier: 'ops',
    zh: (v) => `${v}%`,
    tone: (v) => (Number(v) >= 100 ? 'warn' : 'muted'),
  },
  check_result: {
    label: '自检结果', tier: 'ops',
    // 0 = 正常, 不占版面; 非 0 才是事
    hidden: (v) => Number(v) === 0,
    zh: (v) => `异常 (code ${v})`,
    tone: () => 'bad',
  },
  last_action: {
    label: '最近下发动作', tier: 'engineer',
    zh: (v) => ROBOT_LAST_ACTION[v] || `动作码 ${v}`,
  },
  tool_state: { label: '末端工具', tier: 'engineer' },
  collision_state: {
    label: '碰撞标志', tier: 'ops',
    hidden: (v) => !v,
    zh: () => '已触发',
    tone: () => 'bad',
  },
}

/**
 * 功能: 查一个字段的释义规格.
 * @param {string} nodeKind 'robot' | 'plc'
 * @param {string} key 字段名
 * @returns {object|null} 规格; 未登记返回 null (调用方据此归工程师层)
 */
export function fieldSpec(nodeKind, key) {
  const table = nodeKind === 'robot' ? ROBOT_FIELD_SPEC : L2_FIELD_SPEC
  return table[key] || null
}

/**
 * 功能: 把遥测快照拆成"操作员行"与"工程师原始行".
 *
 * ⚠ 开放世界: 未登记的键一律落进 engineer 并原样显示, 绝不丢弃.
 *   返回的第三个数组 hidden 是**有意不显示**的键名, 只为让单测能三分断言
 *   (ops ∪ engineer ∪ hidden === 快照全部非空键), 从而把"有意"与"漏了"分开.
 * @param {string} nodeKind 'robot' | 'plc'
 * @param {object|null} snapshot 遥测 data 快照
 * @param {object} [ctx] 上下文 {stationId, actionCatalog}
 * @returns {{ops: object[], engineer: object[], hidden: string[]}} 三层字段
 */
export function statusRows(nodeKind, snapshot, ctx = {}) {
  if (!snapshot) return { ops: [], engineer: [], hidden: [] }
  const full = { ...ctx, snapshot }
  const ops = []
  const engineer = []
  const hidden = []
  for (const [key, value] of Object.entries(snapshot)) {
    if (value === null || value === undefined) continue
    if (isHiddenKey(key)) {
      hidden.push(key)
      continue
    }
    const spec = fieldSpec(nodeKind, key)
    if (!spec || spec.tier === 'engineer') {
      engineer.push({
        key,
        label: spec?.label || key,
        text: spec?.zh ? spec.zh(value, full) : formatRaw(value),
      })
      continue
    }
    // 条件隐藏(如 ErrorCode=0、SafeState=就绪): 不占版面, 但仍降到工程师层保底,
    // 否则"面板上没有"与"这个量不存在"又混为一谈了
    if (spec.hidden?.(value, full)) {
      engineer.push({ key, label: spec.label || key, text: formatRaw(value) })
      continue
    }
    ops.push({
      key,
      label: spec.label,
      text: spec.zh ? spec.zh(value, full) : formatRaw(value),
      tone: spec.tone ? spec.tone(value, full) : 'muted',
    })
  }
  return { ops, engineer, hidden }
}

/**
 * 功能: 原样格式化一个未登记的值 (工程师层用).
 * @param {any} value 原始值
 * @returns {string} 显示文本
 */
export function formatRaw(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.length ? `[${value.join(', ')}]` : '[]'
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2)
  return String(value)
}

/**
 * 功能: 拼出工位顶部那句人话.
 *
 * 形如「上样工位 · 运行中 · 正在执行 上样-点样(第 3/10 段)」——
 * 操作员扫一眼就知道这个工位此刻在干嘛, 不必去读六个字段自己拼。
 * @param {object|null} station manifest 工位项
 * @param {string} health 健康度
 * @param {object|null} snapshot 遥测快照
 * @param {object} [ctx] 上下文 {actionCatalog}
 * @returns {{text: string, tone: string}} 一句话与色调
 */
export function headline(station, health, snapshot, ctx = {}) {
  const label = station?.label || '未知工位'
  const healthZh = healthText(health)
  if (!station?.nodeId) {
    return { text: `${label} · 纯结构件，无遥测节点`, tone: 'muted' }
  }
  if (!snapshot) {
    return { text: `${label} · ${healthZh} · 无遥测数据（后端未连接或该节点离线）`, tone: 'muted' }
  }
  const stationId = station.id

  // 机器人: 模式 + 工具 + 速度; 有报警时报警压过一切
  if (stationId === 'ROBOT') {
    if (snapshot.connected === false) return { text: `${label} · 离线 · 控制器未连接`, tone: 'bad' }
    const faulty = (snapshot.error_ids || []).length > 0
      || Number(snapshot.check_result) !== 0
      || ROBOT_MODE[snapshot.robot_mode]?.tone === 'bad'
    if (faulty) return { text: `${label} · 故障 · ${robotFaultText(snapshot)}`, tone: 'bad' }
    const parts = [label, healthZh, ROBOT_MODE[snapshot.robot_mode]?.zh || '模式未知']
    if (Number.isFinite(Number(snapshot.speed_factor))) parts.push(`速度 ${snapshot.speed_factor}%`)
    return { text: parts.join(' · '), tone: ROBOT_MODE[snapshot.robot_mode]?.tone || 'muted' }
  }

  // L2 工位: 安全态 90 压过一切 -> 故障 -> 执行中 -> 空闲
  if (Number(snapshot.SafeState) === 90) {
    return { text: `${label} · ${L2_SAFE_STATE[90].zh} —— 需人工到现场处置`, tone: 'bad' }
  }
  const state = Number(snapshot.State)
  if (Number(snapshot.ErrorCode)) {
    const why = errorCodeText(stationId, snapshot.ActiveCode, snapshot.ErrorCode)
    return { text: `${label} · 故障 · ${why}`, tone: 'bad' }
  }
  if (state === 10) {
    const action = actionCodeText(stationId, snapshot.ActiveCode, ctx.actionCatalog)
    const step = stepText(stationId, snapshot.ActiveCode, snapshot.Step)
    const tail = action ? `正在执行 ${action}（${step.text}）` : '执行中'
    let text = `${label} · ${L2_STATE[10].zh} · ${tail}`
    if (stationId === 'RAIL' && snapshot.current_positions) {
      text += ` · 在 ${railStationText(snapshot.current_positions)} 站位`
    }
    return { text, tone: 'busy' }
  }
  const stateZh = L2_STATE[state]?.zh || '状态未知'
  let text = `${label} · ${healthZh} · ${stateZh}`
  if (stationId === 'RAIL' && snapshot.current_positions) {
    text += ` · 在 ${railStationText(snapshot.current_positions)} 站位`
  }
  return { text, tone: L2_STATE[state]?.tone || 'muted' }
}
