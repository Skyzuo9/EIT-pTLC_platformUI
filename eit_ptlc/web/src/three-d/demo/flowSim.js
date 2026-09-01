/**
 * 功能: 流程(operation 脚本) → 近似动画的即时展开器. 纯函数, 零 three 依赖, 可 node --test.
 *
 * 这是两级生成里的**第二级**。第一级是后端 clip_compiler 的精编译(实测示教点 + 离线 IK,
 * 几何精确, 有 SHA 门禁), 但它对 assign/human/while/for/try 直接 CompileError, 而 101 个
 * 流程里大多含这些语句 —— 只有第一级的话, 新加一个流程在演示栏里多半是一条红字。
 *
 * 所以这一级的目标不是"更准", 而是**新流程零等待可见**: 用户加完流程立刻能看到机构大致
 * 怎么动, 需要精确时再一键触发后端编译升级。
 *
 * 三条纪律(与编译器同源, 不能因为"只是近似"就放松):
 *   1. **不猜**. 轴到哪、气缸是哪个, 全查管线导出的映射表(motionMap.js); 表里没有的动作
 *      产一条带动作名的占位步, 而不是编一个位置。
 *   2. **每一处近似都写在步骤标签上**. 取了 if 的哪个分支、循环只演一轮、机械臂没有
 *      move_l 轨迹 —— 都要在时间轴上看得见, 不能让人以为看到的是实况。
 *   3. **产物不落盘**. 近似片段只活在内存里, 不写 clips/, 不进 index.json。落盘会让它
 *      在别处被当成正式片段, 那是本项目反复踩过的坑形状。
 *
 * 输出是一份 `ptlc.clip/v1` + `debug: true` 文档, 直接喂给既有 compileClip + ClipPlayer。
 * v1 才允许 `joints` 原语(v2/v3 只准 robot_point), `debug: true` 是它的准入标记。
 */
import { jointsOfPoint } from './actionSim.js'
import { axisOfPoint } from './axisIndex.js'
import {
  fluidNote, isIgnored, lookupAction, paramAxisAction,
  sequencePointKey, sequenceSteps, tankLidLinkage, unresolvedReason,
} from './motionMap.js'
// 液面体积规则与实时页、actionSim 共用同一份(表在 manifest.tankLiquid 里)
import { resolveLiquidPlan, resolveStationLiquidPlan } from '../twin/bindings/TankLiquidModel.js'
// 注射泵相位数学(目标体积/轮数压缩/V-M 时长/口号解析)与实时页共用同一份 ——
// 表在 manifest.pumpSyringe 里, 后端 clip_compiler.emit_pump_syringe 是它的 Python 镜像
import { expandPumpPlan } from '../twin/bindings/PumpSyringeModel.js'
// 夹爪三态与"是不是取料脚本"的判据: 与实时页、后端编译器同一份
import { gripperHome, gripperTarget, isPickScript, leafScript } from '../gripSemantics.js'

/** 子脚本内联深度上限; 与后端 clip_compiler.MAX_INLINE_DEPTH 一致 */
export const MAX_INLINE_DEPTH = 8

/** 液面演示时长上限(秒); 与 actionSim 的同名常量同义, 被压缩时在标签上写出真值 */
const LIQUID_MAX_RAMP_S = 20

/** 泵单相位演示时长上限(秒); 与编译器 PUMP_MAX_RAMP_S 同值同义 */
const PUMP_MAX_RAMP_S = LIQUID_MAX_RAMP_S

/** 换阀名义时长(秒); 与 PumpSyringeModel.VALVE_RAMP_S / 编译器 PUMP_VALVE_S 同值 */
const PUMP_VALVE_S = 0.4

/** 泵相位预算; 与编译器 PUMP_DEMO_MAX_PHASES 同值 —— 压缩轮数不截相位, 终点体积不变 */
const PUMP_DEMO_MAX_PHASES = 8

/** 单条流程最多展开多少步 —— 防住 while 写错导致的无限展开 */
const MAX_STEPS = 400

/** 占位步时长(秒): 让时间轴有节奏, 又不至于把一个占位拖得像真动作 */
const PLACEHOLDER_S = 0.35

/** 机械臂两点之间的名义时长(秒). 近似级没有 IK 轨迹, 只能给一个观感值 */
const ROBOT_MOVE_S = 1.2

/**
 * 功能: 取表达式的字面值; 拿不到确定值返回 undefined.
 *
 * 只解字面量与已绑定的变量 —— 算术/比较一律不算。近似级宁可"这一步我不知道",
 * 也不要算出一个看着像真的数。
 * @param {*} node 表达式节点
 * @param {object} bindings 变量绑定
 * @returns {*} 值或 undefined
 */
export function literalOf(node, bindings) {
  if (node === null || node === undefined) return undefined
  if (typeof node !== 'object') return node
  if ('lit' in node) return node.lit
  if ('var' in node) return bindings?.[node.var]
  return undefined
}

/**
 * 功能: 把 args 里的表达式解成普通值.
 * @param {object} args 动作入参
 * @param {object} bindings 变量绑定
 * @returns {object} 求值后的入参
 */
function resolveArgs(args, bindings) {
  const out = {}
  for (const [key, value] of Object.entries(args || {})) {
    const resolved = literalOf(value, bindings)
    if (resolved !== undefined) out[key] = resolved
  }
  return out
}

/**
 * 功能: 展开器上下文.
 * @typedef {object} FlowSimContext
 * @property {object|null} motionMap 动作→机构映射表
 * @property {object} manifest device-manifest
 * @property {Map} servoIndex plc 示教点索引(indexServoPoints 产物)
 * @property {object} pointCatalog 机器人点位目录(generated/robot-points.json)
 * @property {(name: string) => object|null} resolveScript 子脚本取用(同步; 调用方预取)
 */

/**
 * 功能: 把一个流程文档展开成近似片段.
 *
 * @param {object} document 流程 doc(GET /api/scripts/{name})
 * @param {object} inputs 入参覆盖(演示页右栏填的)
 * @param {FlowSimContext} context 环境
 * @returns {{kind: string, doc?: object, notes?: string[], unknown?: string[],
 *            deferred?: string[], reason?: string}}
 *   kind: 'approx'    可播的近似片段, doc 是 ptlc.clip/v1
 *         'no-motion' 展开成功但一步机构都不动 —— 该流程无机械动作
 *         'failed'    连展开都做不到(脚本取不到/结构不认识)
 *
 * `unknown` 与 `deferred` **必须分开**(与 actionSim 的 no-motion/unsupported 同一条纪律):
 *   unknown   这条动作压根没进任何映射表 —— 是待补的活
 *   deferred  进了表, 但它的参数(缸号/孔位/槽位)是运行期量, 静态取不到 —— 不是待补的活
 * 混在一起报"不在映射表中", 会让人去补一张其实已经有的表。
 */
export function simulateFlow(document, inputs, context) {
  if (!document || typeof document !== 'object') {
    return { kind: 'failed', reason: '流程文档为空' }
  }
  const state = newState()
  const bindings = { ...defaultBindings(document), ...(inputs || {}) }
  // 顶层文档自己声明 tool_id 时(演示栏直接看 robot_tool_pick/put 就是这种), 与
  // run_script 那条路同一条规则: 这个入参就是在说"这一段讲的是几号刀"。不在这里接住的话,
  // 直接看这条流程时快换那一步只能报"刀号未声明"。
  if (Number.isInteger(Number(bindings.tool_id))) state.tool = Number(bindings.tool_id)
  seedEntryState(document, bindings, context, state)

  try {
    walk(document.body || [], bindings, context, state, {
      depth: 0,
      script: String(document.name || '?'),
    })
  } catch (err) {
    return { kind: 'failed', reason: err?.message || String(err) }
  }

  const moving = state.steps.filter((step) => !('wait' in (step.do || {}))).length
  if (moving === 0) {
    const gaps = [
      state.unknown.length ? `${new Set(state.unknown).size} 个动作不在映射表里` : '',
      state.deferred.length ? `${new Set(state.deferred).size} 个动作的参数要运行期才定` : '',
    ].filter(Boolean)
    return {
      kind: 'no-motion',
      reason: gaps.length
        ? `展开后没有任何机构运动(${gaps.join(', ')})`
        : '该流程的每一步都只读状态或改账本, 不驱动任何机构',
      notes: renderNotes(state),
      unknown: [...new Set(state.unknown)],
      deferred: [...new Set(state.deferred)],
    }
  }

  return {
    kind: 'approx',
    notes: renderNotes(state),
    unknown: [...new Set(state.unknown)],
    deferred: [...new Set(state.deferred)],
    doc: {
      schema: 'ptlc.clip/v1',
      debug: true,
      name: `approx.${document.name}`,
      label: `${document.label || document.name}（近似）`,
      description: '前端按流程脚本即时展开的近似动画；机械臂无 move_l 轨迹，分支与循环见步骤标签。',
      home: {
        axis_mm: state.home.axis_mm,
        actuators: state.home.actuators,
        linkages: state.home.linkages,
        liquid_ml: state.home.liquid_ml,
        pump_ml: state.home.pump_ml,
        pump_port: state.home.pump_port,
        ...(state.home.joints_deg ? { joints_deg: state.home.joints_deg } : {}),
      },
      steps: state.steps,
    },
  }
}

/**
 * 功能: 建一份空的展开累积状态.
 * @returns {object} 累积状态
 */
function newState() {
  return {
    steps: [],
    /** 近似之处按类型计数, 展开完再汇成人话 —— 见 countNote/renderNotes */
    noteCounts: new Map(),
    notes: [],
    unknown: [],
    deferred: [],
    home: {
      axis_mm: {}, actuators: {}, linkages: {}, liquid_ml: {},
      pump_ml: {}, pump_port: {}, joints_deg: null,
    },
    /** 当前挂的刀号(0 = 空手). 由 robot_tool_pick/put 的 tool_id 与 set_mounted_tool 声明 */
    tool: 0,
    /**
     * 每个展缸当前的液量(mL), 键是 manifest.tanks[].id.
     *
     * 有了它, 流程里的排液动作**不需要任何假设**: 起始液位就是前面那条注液动作留下的
     * 体积. 与编译器侧的 ClipBuilder.tank_volume_ml 同构 —— 两边都必须是"跨动作跟踪",
     * 否则同一条流程在近似档与精编译档的液面高低对不上.
     * @type {Map<string, number>}
     */
    tankMl: new Map(),
    /**
     * 每处驻位液体(manifest.liquids[], 如收集样品瓶)当前体积(mL), 键是 liquids[].id.
     * 与 tankMl 同一条理由跨动作跟踪; 编译器侧的同构物是 ClipBuilder.station_liquid_ml.
     * @type {Map<string, number>}
     */
    stationMl: new Map(),
    /**
     * 每台泵针筒内当前体积(mL)与阀指针当前口, 键是 manifest.pumpSyringe.pumps[].id.
     * 与 tankMl 同一条理由: sampling.prep 停在气隙位、aspirate 在其上相对叠加, 是一条
     * 跨动作的连续行程. 编译器侧的同构物是 ClipBuilder.pump_volume_ml/pump_valve_port.
     * @type {Map<string, number>}
     */
    pumpMl: new Map(),
    pumpPort: new Map(),
    truncated: false,
  }
}

/**
 * 功能: 把"前置段留下的状态"(缸里已注好液 / 板已在缸里)播种成起手态.
 *
 * 与后端 clip_compiler.ClipBuilder.seed_entry_state 同构, 声明本身也同源 ——
 * 真源是 Python 侧的 PHASE_ENTRY_STATE, 经 motion-map 的 phaseEntryState 导出, 这边只读。
 *
 * 为什么非播种不可: 单段流程不含前置段, 而运行期的清场是无条件的
 * (MachineStateDriver.home() 把 8 个缸清零、MachineRig.home() 清空板舞台, 且每一次向后
 * seek 都要走一遭)。不声明就永远是空缸无板 —— 展开-上料会把板放进一个空缸。
 *
 * 液量**不抄常量**: 拿前置段脚本的 body 走一遍同一个 walk, 取它留下的 tankMl。这样
 * 配方默认值改了近似档跟着变, 且与编译器算的是同一个数。
 *
 * @param {object} document 流程 doc
 * @param {object} bindings 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @returns {void}
 */
function seedEntryState(document, bindings, context, state) {
  const entry = context?.motionMap?.phaseEntryState?.[String(document?.name || '')]
  if (!entry) return

  if (entry.liquidAfter) {
    const upstream = context.resolveScript?.(entry.liquidAfter) || null
    if (!upstream) {
      // 归 deferred 而不是 unknown: 声明在表里、缺的是那份脚本(调用方没预取), 不是待补的表
      countNote(state, 'entry-liquid-unresolved', `前置段 ${entry.liquidAfter} 未取到`)
      state.deferred.push(`entry:${entry.liquidAfter}`)
    } else {
      const scratch = newState()
      const upstreamBindings = { ...defaultBindings(upstream) }
      for (const key of ['tank', 'target_tank']) {
        if (key in upstreamBindings && key in bindings) upstreamBindings[key] = bindings[key]
      }
      walk(upstream.body || [], upstreamBindings, context, scratch,
        { depth: 0, script: String(entry.liquidAfter) })
      for (const [id, ml] of scratch.tankMl) {
        state.tankMl.set(id, ml)
        if (!(id in state.home.liquid_ml)) state.home.liquid_ml[id] = ml
      }
      // 驻位液体同构承接(编译器侧是 seed_entry_state 收 prelude.station_liquid_ml):
      // collect_unload 起手瓶里带着 collect_execute 洗脱下来的液
      for (const [id, ml] of scratch.stationMl) {
        if (!(ml > 0)) continue
        state.stationMl.set(id, ml)
        if (!(id in state.home.liquid_ml)) state.home.liquid_ml[id] = ml
      }
    }
  }

  if (entry.plateAt) {
    // at:0/dur:0 —— 不占时间也不推后面的时间轴, 与编译器插起手式的做法一致
    const slot = String(entry.plateAt).replace(/\{(\w+)\}/g, (whole, key) => (
      key in bindings ? String(bindings[key]) : whole
    ))
    state.steps.push({
      label: '板在位(前置段已放入)', at: 0, dur: 0,
      do: { plate: { id: 'plate', at: slot } },
    })
  }

  // 前置段留在场上的载荷(如接粉收集器): 与编译器 seed_entry_state 的 states 分支同构。
  // 不点亮的话近似档同样在"空翻旋转气缸"(载荷 manifest 初始不可见, home() 又会清 states)。
  for (const stateId of entry.states || []) {
    state.steps.push({
      label: `${stateId} 显示(前置段已放入)`, at: 0, dur: 0,
      do: { state: { id: stateId, value: true } },
    })
  }
}

/**
 * 功能: 取脚本自己的入参默认值(镜像后端 clip_compiler.default_bindings).
 * @param {object} document 流程 doc
 * @returns {object} 变量名 -> 默认值
 */
export function defaultBindings(document) {
  const out = {}
  for (const item of document?.vars || []) {
    if (item?.io === 'in') out[item.name] = coerceDefault(item)
    else if ((item?.io === 'var' || item?.io === 'out')
      && item.default !== null && item.default !== undefined) {
      out[item.name] = coerceDefault(item)
    }
  }
  return out
}

/**
 * 功能: 按声明类型把 YAML 默认值转成真实类型.
 * @param {object} item 变量定义
 * @returns {*} 值
 */
function coerceDefault(item) {
  const value = item?.default
  if (typeof value !== 'string') return value
  const kind = String(item?.type || '').toUpperCase()
  if (kind === 'FLOAT') return Number.isFinite(Number(value)) ? Number(value) : value
  if (kind === 'INT') return Number.isInteger(Number(value)) ? Number(value) : value
  if (kind === 'BOOL') return ['true', '1', 'yes'].includes(value.trim().toLowerCase())
  return value
}

/**
 * 功能: 递归展开一个语句块.
 * @param {Array} nodes 语句数组
 * @param {object} bindings 变量绑定
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @param {{depth: number, script: string}} where 位置
 * @returns {void}
 */
function walk(nodes, bindings, context, state, where) {
  for (const node of nodes || []) {
    if (state.steps.length >= MAX_STEPS) {
      if (!state.truncated) {
        state.truncated = true
        countNote(state, 'truncated')
      }
      return
    }
    if (!node || typeof node !== 'object') continue
    const op = node.op

    if (op === 'call') {
      emitCall(node, bindings, context, state, where)
    } else if (op === 'run_script') {
      const name = node.script
      if (where.depth >= MAX_INLINE_DEPTH) {
        push(state, `${name}（嵌套过深，未展开）`, PLACEHOLDER_S, { wait: {} })
        continue
      }
      const sub = context.resolveScript?.(name)
      if (!sub) {
        push(state, `${name}（子流程未取到，未展开）`, PLACEHOLDER_S, { wait: {} })
        state.unknown.push(`run_script:${name}`)
        continue
      }
      const subBindings = { ...defaultBindings(sub) }
      for (const [key, value] of Object.entries(node.inputs || {})) {
        const resolved = literalOf(value, bindings)
        if (resolved !== undefined) subBindings[key] = resolved
      }
      // 声明了 tool_id 的子流程(全仓只有 robot_tool_pick / robot_tool_put)就是在说
      // "这一段讲的是几号刀" —— 快换锁紧发生在 set_mounted_tool **之前**, 不在这里
      // 接住的话, 锁紧那一刻还不知道挂的是哪把刀, 只能猜, 而猜错没有任何指标会报警。
      if (Number.isInteger(Number(subBindings.tool_id))) {
        state.tool = Number(subBindings.tool_id)
      }
      walk(sub.body || [], subBindings, context, state, {
        depth: where.depth + 1,
        script: `${where.script}/${name}`,
      })
    } else if (op === 'if') {
      // 分支条件多半依赖运行期反馈, 静态取不到 —— 取第一条并**在标签上写明**
      const branch = node.then || []
      countNote(state, 'branch')
      push(state, '↳ 假设分支：条件成立', 0, { wait: {} })
      walk(branch, bindings, context, state, where)
    } else if (op === 'for') {
      // 只演示一轮 —— 那么演的就是**第一轮**, 把循环变量绑成 start 的字面值正是这句话的
      // 字面意思, 不是猜。不绑的后果实测可见: system_init_all 的逐缸初始化里 target_tank
      // 取不到, develop.init 落进"缸号无效"兜底, 再被报成"不在映射表中" —— 而它明明在表里。
      // start 不是字面量时照旧不绑, 标签写"未知": 宁可这一步说不知道, 也不编一个缸号。
      const first = literalOf(node.start, bindings)
      const scoped = first === undefined ? bindings : { ...bindings, [node.var]: first }
      const shown = first === undefined ? '未知' : first
      countNote(state, 'loop', `${node.var}=${shown}`)
      push(state, `↳ 循环仅演示第一轮（${node.var}=${shown}）`, 0, { wait: {} })
      walk(node.body || [], scoped, context, state, where)
    } else if (op === 'while' || op === 'repeat') {
      // 这两种没有循环变量可绑
      countNote(state, 'loop')
      push(state, `↳ 循环仅演示一轮（${op}）`, 0, { wait: {} })
      walk(node.body || [], bindings, context, state, where)
    } else if (op === 'with_resources') {
      walk(node.body || [], bindings, context, state, where)
    } else if (op === 'parallel') {
      countNote(state, 'parallel')
      for (const branch of node.branches || []) {
        walk(branch, bindings, context, state, where)
      }
    } else if (op === 'try') {
      walk(node.body || [], bindings, context, state, where)
    } else if (op === 'human') {
      push(state, `人工确认：${node.prompt || node.kind || 'confirm'}`, PLACEHOLDER_S, { wait: {} })
    } else if (op === 'assign' || op === 'comment' || op === 'raise') {
      // 不占时间: assign 是纯数据、comment 是注释、raise 是异常路径
      continue
    }
  }
}

/**
 * 功能: 把一条 call 语句变成动画步.
 * @param {object} node call 节点
 * @param {object} bindings 变量绑定
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @param {object} where 展开位置 {depth, script}; 夹爪三态要靠它判是不是取料脚本
 * @returns {void}
 */
function emitCall(node, bindings, context, state, where) {
  const action = String(node.action || '')
  const args = resolveArgs(node.args, bindings)
  const { motionMap, manifest } = context

  // ⚠ 必须排在 isIgnored 之前: set_mounted_tool 在编译器的忽略表里(它不产生运动),
  // 但它是**刀号的唯一声明**, 被忽略表吃掉就等于全程不知道挂的是哪把刀 —— 从前正是
  // 这样, 于是快换那一步只能写死 2 号(96 孔板夹爪), 上样取 1 号玻璃吸盘也照挂错的。
  if (action === 'robot.set_mounted_tool') {
    const tool = Number(args.tool_id)
    if (Number.isInteger(tool)) state.tool = tool
    return
  }

  if (isIgnored(motionMap, action)) return

  // 锚点校验: 只读当前反馈核对位姿, 全程不运动(动作 desc 原话)。**不能进 IGNORED_ACTIONS**
  // —— 后端 emit_call 要用它当起手姿态声明(见 clip_compiler.apply_anchor), 忽略掉会让
  // 第一段 move_l 的起点错掉。这里出一条 0 秒的可见步: 它声明"本段起于哪个点",
  // 是理解后面轨迹的前提, 但确实不占运动时间。
  if (action === 'robot.require_anchor') {
    push(state, `锚点校验：${args.point_id || '?'}（只读反馈，不运动）`, 0, { wait: {} })
    return
  }

  // 地轨: 槽号 → 示教点毫米. 点表读不到就如实占一格, **不拿常量顶** ——
  // 顶上去的那个数在现场重新示教后不会报错, 只会安静地演一个陈旧位置。
  if (action === 'rail.move' || action === 'rail.ensure') {
    const slot = Number(args.Rail_Target_Position)
    const point = railPointForSlot(context.servoIndex, slot)
    if (!point) {
      // 槽号本身取不到(运行期量) 与 点表真缺这一站, 是两回事
      const missingSlot = !Number.isInteger(slot)
      push(state, missingSlot ? '地轨 →（槽号运行期才定）' : `地轨 → 槽${slot}（点表缺该站位）`,
        PLACEHOLDER_S, { wait: {} })
      ;(missingSlot ? state.deferred : state.unknown).push(action)
      return
    }
    seedAxisHome(state, manifest, 'axis_11y')
    push(state, `地轨 → 槽${slot}（${point.value} mm）`, 1.6,
      { axis: { id: 'axis_11y', to_mm: point.value } }, 'inout')
    return
  }

  // 机械臂到点: 用点位目录的关节角(实测优先, 派生点用管线离线反解的那份)
  if (action === 'robot.move_to_point') {
    const pointId = args.point_id_or_robot_name
    const hit = jointsOfPoint(context.pointCatalog, pointId)
    if (!hit) {
      push(state, `机械臂 → ${pointId || '?'}（点位既无实测关节角也反解不出）`, PLACEHOLDER_S, { wait: {} })
      state.unknown.push(`${action}:${pointId}`)
      return
    }
    if (!state.home.joints_deg) state.home.joints_deg = [...hit.joints]
    const motion = String(args.motion || 'move_j')
    if (motion === 'move_l') countNote(state, 'move_l')
    if (hit.source === 'solved') countNote(state, 'solved-joint')
    push(state, `机械臂 → ${pointId}${hit.source === 'solved' ? '（反解）' : ''}`,
      ROBOT_MOVE_S, { joints: { to_deg: hit.joints } }, 'inout')
    return
  }

  if (action === 'robot.dwell') {
    const ms = Number(args.duration_ms) || 0
    push(state, `等待 ${Math.round(ms)} ms`, Math.min(3, ms / 1000), { wait: {} })
    return
  }

  if (action === 'robot.tool_action') {
    emitToolAction(String(args.action || ''), context, state, where)
    return
  }

  // 映射表里的定值动作
  const mapped = lookupAction(motionMap, action)
  if (mapped?.kind === 'axis') {
    seedAxisHome(state, manifest, mapped.axis)
    push(state, mapped.label || `${mapped.axis} → ${mapped.toMm} mm`, 1.2,
      { axis: { id: mapped.axis, to_mm: Number(mapped.toMm) } }, 'inout')
    return
  }
  if (mapped?.kind === 'search') {
    push(state, `${mapped.label}（行程由运行期决定）`, Number(mapped.durationS) || PLACEHOLDER_S, { wait: {} })
    return
  }
  if (mapped?.kind === 'actuator') {
    const target = mapped.value !== undefined ? Number(mapped.value) : Number(Boolean(args[mapped.arg]))
    const spec = (manifest?.actuators || []).find((item) => item.id === mapped.id)
    if (!(mapped.id in state.home.actuators)) state.home.actuators[mapped.id] = target > 0.5 ? 0 : 1
    push(state, `${spec?.label || mapped.id} → ${target > 0.5 ? '动点' : '原点'}`,
      Number(spec?.transitionS) || 1, { actuator: { id: mapped.id, to: target } }, 'inout')
    return
  }
  if (mapped?.kind === 'tank-lid') {
    const tank = Number(args.target_tank)
    const linkageId = tankLidLinkage(motionMap, tank)
    if (!linkageId) {
      // 动作**在**映射表里, 缺的只是缸号 —— 记进 deferred 而不是 unknown, 否则会有人
      // 去补一张已经存在的表(实测: system_init_all 里 develop.init 就是这样被误报的)
      push(state, `${action}（缸号运行期才定，未表现）`, PLACEHOLDER_S, { wait: {} })
      state.deferred.push(action)
      return
    }
    const spec = (manifest?.linkages || []).find((item) => item.id === linkageId)
    // 值语义: 1 = 动点 = 关盖 = 建模基线, 0 = 原点 = 开盖. home 必须显式给 ——
    // 通道隐式初值是 0, 缺省会让盖在 t=0 就已经开着.
    if (!(linkageId in state.home.linkages)) {
      state.home.linkages[linkageId] = mapped.value > 0.5 ? 0 : 1
    }
    push(state, `${tank}号缸${mapped.value > 0.5 ? '关盖' : '开盖'}`,
      Number(spec?.transitionS) || 1.2, { linkage: { id: linkageId, to: mapped.value } }, 'inout')
    // develop.rinse_fill 既关盖又抽排又注液 —— 三件事叠加; 顺序与编译器一致: 盖→泵→液。
    // 注液不再排在泵段之后单发一条整段斜坡, 而是每趟 dispense 涨一截(见 tankFillPourer);
    // 逐趟一趟都没涨成才退回 emitTankLiquid。
    const pourer = tankFillPourer(action, args, context, state)
    const pumpShown = emitPumpSyringe(action, args, context, state, pourer?.pour)
    const shown = (pourer?.finish() ?? false) || emitTankLiquid(action, args, context, state)
    noteFluid(motionMap, action, state, shown, pumpShown)
    return
  }

  // 映射表里的多步定值序列(目标是烧在 PLC 里的常量)
  const declared = sequenceSteps(motionMap, action)
  if (declared) {
    emitSequence(declared, args, context, state)
    // 轴先泵后, 与编译器 SEQUENCE 分支的织入一致(sampling.aspirate: 下探进孔后才回抽)
    const pumpShown = emitPumpSyringe(action, args, context, state)
    noteFluid(motionMap, action, state, false, pumpShown)
    return
  }
  // 目标毫米直接来自入参的轴动作
  const paramAxis = paramAxisAction(motionMap, action)
  if (paramAxis) {
    const target = Number(args[paramAxis.arg])
    if (Number.isFinite(target)) {
      seedAxisHome(state, manifest, paramAxis.axis)
      push(state, `${paramAxis.label} → ${target} mm`, 1.0,
        { axis: { id: paramAxis.axis, to_mm: target } }, 'inout')
      return
    }
  }

  // 注射泵柱塞行程与缸液面: 与编译器 emit_call 的织入顺序一致 —— develop.fill 的注液
  // 与它那一趟 dispense 同 at 同 dur 并行(见 tankFillPourer); clean_line/rinse_mix 只有泵。
  const pourer = tankFillPourer(action, args, context, state)
  const pumpShown = emitPumpSyringe(action, args, context, state, pourer?.pour)
  if (pourer?.finish()) return
  // 展缸注/排液与驻位液体(收集瓶): 液面看得见 —— 排在泛化的流体兜底之前。
  // 两表按动作互斥(一个动作只往一只容器注液), 先具体后泛化。
  if (emitTankLiquid(action, args, context, state)
    || emitStationLiquid(action, args, context, state, pumpShown)
    || pumpShown) return

  // 只驱泵/阀/真空且没编出行程(泵没几何/入参未解出): 占一个说明白的时间格
  const fluid = fluidNote(motionMap, action)
  if (fluid) {
    push(state, `${action}（泵/阀：${fluid}）`, PLACEHOLDER_S, { wait: {} })
    return
  }
  // 有机械运动但目标值 PC 侧拿不到: 缺口是**已知且写下来了**的, 不是"没进表"
  if (unresolvedReason(motionMap, action)) {
    push(state, `${action}（目标在 PLC 内部，未表现）`, PLACEHOLDER_S, { wait: {} })
    state.deferred.push(action)
    return
  }

  // 表里真没有: 产一条带动作名的占位, 并计入"未覆盖"
  push(state, `${action}（未在映射表中）`, PLACEHOLDER_S, { wait: {} })
  state.unknown.push(action)
}

/**
 * 功能: 展开一条 SEQUENCE_ACTIONS 声明(与 actionSim.sequencePlan 同一份表, 两处消费).
 * @param {Array<object>} declared 步骤声明
 * @param {object} args 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @returns {void}
 */
function emitSequence(declared, args, context, state) {
  const { manifest, servoIndex } = context
  for (const step of declared) {
    if (step.kind === 'axis' || step.kind === 'point') {
      let axisId = step.axis
      let toMm = Number(step.toMm)
      if (step.kind === 'point') {
        // 字面点位 / 入参间接两种编码由 sequencePointKey 统一(与编译器同式);
        // 复合点位的成员带 `<点位key>.<成员key>` 前缀, 与 indexServoPoints 同规则
        const { key } = sequencePointKey(step, args)
        const point = key ? servoIndex?.get(String(key)) : null
        if (!point || !Number.isFinite(Number(point.value))) {
          push(state, `${step.label}（${key ? `点表缺点位 ${key}` : '未选点位'}）`, PLACEHOLDER_S, { wait: {} })
          continue
        }
        toMm = Number(point.value)
        axisId = axisOfPoint(manifest, point) || axisId
      }
      if (!axisId) continue
      seedAxisHome(state, manifest, axisId)
      push(state, `${step.label}${step.kind === 'point' ? ` → ${toMm} mm` : ''}`, 1.0,
        { axis: { id: axisId, to_mm: toMm } }, 'inout')
      continue
    }
    if (step.kind === 'well') {
      // 孔位毫米只在编译期可见(映射表不导出), 照编译器未标定分支的语义占一格
      push(state, `${step.label}（孔板未标定，未表现）`, PLACEHOLDER_S, { wait: {} })
      continue
    }
    if (step.kind !== 'actuator' && step.kind !== 'linkage') {
      // 表长在 Python 侧, 新增步骤类型时这里要跟上 —— 静默跳过等于少演一段还毫无迹象
      push(state, `${step.label || step.kind}（步骤类型 ${step.kind} 前端还不认识）`, PLACEHOLDER_S, { wait: {} })
      continue
    }
    const channel = step.kind === 'linkage' ? 'linkage' : 'actuator'
    const bucket = channel === 'linkage' ? state.home.linkages : state.home.actuators
    const target = Number(step.value)
    if (!(step.id in bucket)) bucket[step.id] = target > 0.5 ? 0 : 1
    push(state, step.label, 0.5, { [channel]: { id: step.id, to: target } }, 'inout')
  }
}

/**
 * 功能: 给"既动机构又动流体"的动作补一条说明步.
 * @param {object|null} motionMap 映射表
 * @param {string} action 动作名
 * @param {object} state 累积状态
 * @param {boolean} [liquidShown] 本条是否已经出了液面步
 * @param {boolean} [pumpShown] 本条是否已经出了泵行程步
 * @returns {void}
 */
function noteFluid(motionMap, action, state, liquidShown = false, pumpShown = false) {
  const fluid = fluidNote(motionMap, action)
  if (!fluid) return
  let tail
  if (pumpShown && liquidShown) tail = '柱塞行程与缸内液面均已按配方表现'
  else if (pumpShown) tail = '柱塞行程已按配方表现'
  else if (liquidShown) tail = '柱塞行程未表现（泵未建几何或入参未解出），缸内液面已按配方体积表现'
  else tail = '三维暂不表现流体'
  push(state, `↳ 同时驱动 ${fluid}（${tail}）`, 0, { wait: {} })
}

/**
 * 功能: 为一条展缸**注液**动作造"逐趟涨液面"的发射器 —— clip_compiler._tank_fill_pourer
 * 的 JS 镜像, 两侧逐形对应(同一趟 dispense、同 at 同 dur、同封顶规则).
 *
 * 为什么要逐趟而不是一条斜坡到底(2026-08-09 之前的写法): 泵行程原先**全部发完才发那条
 * 整段液面斜坡**, 于是 develop_prepare 的 170.6s 里 140.6s(82%)缸内恒为 0 —— 4 趟
 * 10mL 润洗泵行程期间缸里一动不动, 而展缸泵的几何在 ST_PUMP 工位, 镜头对着展缸时根本
 * 不在画面里, 表现就是"吸 10mL 没有任何动画". 节拍与 emitStationLiquid 同构.
 *
 * 每趟增量取**泵这一趟真打出去的 delta**而非"总量/趟数": 轮数被 PUMP_DEMO_MAX_PHASES
 * 压过时前者自动对; 差额由 finish() 按契约总量补一条.
 *
 * @param {string} action 动作名
 * @param {object} args 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @returns {null|{pour: Function, finish: Function}} 不该走逐趟(不在表里/是排液/该缸没有
 *   液面几何)时返回 null, 由调用方退回 emitTankLiquid 的整段斜坡
 */
function tankFillPourer(action, args, context, state) {
  const cfg = context.manifest?.tankLiquid
  if (!cfg?.cavity) return null
  const plan = resolveLiquidPlan(cfg, action, args)
  if (!plan || plan.dir !== 'fill' || !(plan.targetMl > 0)) return null
  const tank = (context.manifest.tanks || []).find((item) => item.index === plan.index)
  if (!tank?.id || !tank.liquidNode) return null

  const tankNo = plan.index + 1
  const totalMl = plan.targetMl        // 已含扣管路存液与封顶槽容, 由 resolveLiquidPlan 出
  const startMl = state.tankMl.get(tank.id) ?? 0
  let ml = startMl
  let poured = 0

  /** 泵打出去一趟 -> 缸里同 at 同 dur 涨一截. */
  const pour = (at, dur, deltaMl) => {
    const toMl = Math.min(ml + Math.max(0, Number(deltaMl) || 0), totalMl)
    // 零位移不发假斜坡(与 emitTankLiquid/编译器同一条)
    if (Math.abs(toMl - ml) < 0.05) return
    push(state, `${tankNo}号缸注液 ${ml.toFixed(1)} → ${toMl.toFixed(1)} mL`,
      dur, { liquid: { id: tank.id, to_ml: toMl } }, 'out', at)
    ml = toMl
    poured += 1
  }

  /** 收尾: 记账 + 补足被压缩掉的余量. 一趟都没涨成就交还给整段斜坡. */
  const finish = () => {
    if (!poured) return false
    // home 只在首次触碰该缸时播种(与 emitTankLiquid 同构): 起点是驱动前的累计值
    if (!(tank.id in state.home.liquid_ml)) state.home.liquid_ml[tank.id] = startMl
    if (totalMl - ml >= 0.05) {
      push(state, `${tankNo}号缸注液 ${ml.toFixed(1)} → ${totalMl.toFixed(1)} mL（泵段已压缩轮数，补足余量）`,
        Math.min(plan.rampS, LIQUID_MAX_RAMP_S), { liquid: { id: tank.id, to_ml: totalMl } }, 'out')
      ml = totalMl
    }
    state.tankMl.set(tank.id, ml)
    return true
  }

  return { pour, finish }
}

/**
 * 功能: 展开一条展缸注/排液动作的液面步.
 *
 * 与 actionSim 的同名逻辑分开写是有理由的: **流程自带上下文**, 排液的起始液位由前面
 * 那条注液动作真实推导得出(state.tankMl 累加器), 一个假设都不用做. 单动作演示没有这个
 * 上下文, 才需要那边的"按配对注液动作的默认配方假设".
 *
 * **注液的常规路径已不在这里**: 有泵行程可并的注液走 tankFillPourer 逐趟发, 本函数只在
 * 那条路走不通(泵没几何/入参未解出/一趟都没涨成)时兜底, 以及排液(走真空不走泵).
 *
 * @param {string} action 动作名
 * @param {object} args 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @returns {boolean} 是否出了液面步
 */
function emitTankLiquid(action, args, context, state) {
  const cfg = context.manifest?.tankLiquid
  if (!cfg?.cavity) return false
  const plan = resolveLiquidPlan(cfg, action, args)
  if (!plan) return false
  const tankNo = plan.index + 1
  // 按 index 字段查而不是按数组下标(理由见 actionSim.tankLiquidSteps 的同款注释)
  const tank = (context.manifest.tanks || []).find((item) => item.index === plan.index)
  if (!tank?.id || !tank.liquidNode) return false

  const fromMl = state.tankMl.get(tank.id) ?? 0
  if (plan.dir !== 'fill' && !(fromMl > 0)) {
    // 这条流程还没往这缸注过液就要排 —— 起始液量无从得知. 归 deferred(动作在表里、
    // 缺的是运行期事实)而不是 unknown, 免得有人去补一张已经存在的表.
    push(state, `${tankNo}号缸排液（缸内起始液量未知，未表现液面）`, PLACEHOLDER_S, { wait: {} })
    countNote(state, 'tank-start-unknown', `${tankNo}号缸`)
    state.deferred.push(action)
    return true
  }
  const toMl = plan.dir === 'fill' ? plan.targetMl : 0

  // home 只在首次触碰该缸时播种: 之后的起点由上一步的末帧保持, 不该被覆盖
  if (!(tank.id in state.home.liquid_ml)) state.home.liquid_ml[tank.id] = fromMl
  state.tankMl.set(tank.id, toMl)

  if (plan.delayS > 0) {
    push(state, `${tankNo}号缸静置沉降 ${plan.delayS.toFixed(0)}s`,
      Math.min(plan.delayS, LIQUID_MAX_RAMP_S), { wait: {} })
  }
  const clamped = plan.rampS > LIQUID_MAX_RAMP_S
  const dur = clamped ? LIQUID_MAX_RAMP_S : plan.rampS
  const timeNote = clamped ? `（实机 ${plan.rampS.toFixed(0)}s，演示压到 ${dur}s）` : ''
  push(state, `${tankNo}号缸${plan.dir === 'fill' ? '注液' : '排液'} `
    + `${fromMl.toFixed(1)} → ${toMl.toFixed(1)} mL${timeNote}`,
  dur, { liquid: { id: tank.id, to_ml: toMl } }, 'out')
  return true
}

/**
 * 功能: 展开一条驻位液体动作(collect.collect: 洗脱液经滤芯正压排进收集样品瓶)的逐轮步序.
 *
 * 规则(单轮体积/轮数/实机 roundS 与演示 demoS 时长)全部来自 manifest.liquids[].actions
 * (真源 gen_twin_manifest.STATION_LIQUID_ACTIONS), 经 resolveStationLiquidPlan 解析;
 * 后端 clip_compiler.emit_station_liquid 是它的 Python 镜像, 同构由片段语料测试锁住.
 * 每轮三拍: 泵吸排(占位 wait, 柱塞行程已单独表现时省掉) → 液面斜坡(对应实机正压排液
 * 20s 窗口, 不是泵 dispense 那一秒) → 静置沉淀.
 *
 * @param {string} action 动作名
 * @param {object} args 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @param {boolean} [pumpShown] 柱塞行程是否已编出(编出了就省掉泵占位拍, 免得双份泵戏)
 * @returns {boolean} 是否出了液面步
 */
function emitStationLiquid(action, args, context, state, pumpShown = false) {
  for (const spec of context.manifest?.liquids || []) {
    const plan = resolveStationLiquidPlan(spec, action, args)
    if (!plan) continue
    const capacity = Number(spec.cavity?.capacityMl) || 0
    let fromMl = state.stationMl.get(plan.liquidId) ?? 0
    // home 只在首次触碰时播种(与 tankMl 同构): 起手体积是驱动前的累计值
    if (!(plan.liquidId in state.home.liquid_ml)) state.home.liquid_ml[plan.liquidId] = fromMl
    if (plan.roundsShown < plan.roundsTotal) {
      countNote(state, 'station-liquid-rounds',
        `${action} 共 ${plan.roundsTotal} 轮洗脱, 演示只演前 ${plan.roundsShown} 轮`)
    }
    for (let i = 0; i < plan.roundsShown; i += 1) {
      const toMl = capacity > 0
        ? Math.min(fromMl + plan.perRoundMl, capacity)
        : fromMl + plan.perRoundMl
      if (!pumpShown) {
        push(state, `收集·泵吸排洗脱剂 ${plan.perRoundMl} mL`
          + `（第 ${i + 1}/${plan.roundsTotal} 轮，实机≈${plan.real.pump}s）`,
        Math.min(plan.demo.pump, LIQUID_MAX_RAMP_S), { wait: {} })
      }
      push(state, `收集·正压排液入瓶 ${fromMl.toFixed(2)} → ${toMl.toFixed(2)} mL`
        + `（实机≈${plan.real.transfer}s，演示压到 ${plan.demo.transfer}s）`,
      Math.min(plan.demo.transfer, LIQUID_MAX_RAMP_S),
      { liquid: { id: plan.liquidId, to_ml: toMl } }, 'out')
      push(state, `收集·静置沉淀（实机≈${plan.real.settle}s）`,
        Math.min(plan.demo.settle, LIQUID_MAX_RAMP_S), { wait: {} })
      fromMl = toMl
    }
    state.stationMl.set(plan.liquidId, fromMl)
    return true
  }
  return false
}

/**
 * 功能: 展开一条注射泵动作的柱塞行程步与换阀步.
 *
 * 相位数学(目标体积/轮数压缩/V-M 时长/口号解析)不在这里: 全部经 expandPumpPlan 复用
 * 实时页 PumpSyringeModel 的实现, 真源是 manifest.pumpSyringe.actions —— 后端
 * clip_compiler.emit_pump_syringe 是它的 Python 镜像, 三方消费同一张表. 这里只负责
 * 把相位计划落成步骤, 与编译器逐形对应: 端口变化先发换阀步(解不出口号就只动柱塞,
 * "宁可阀指针不转, 也不编一个"), 行程按 V/M 真值、超上限压缩并在标签写真值,
 * 每段移动后按 M 出稳液步.
 *
 * 跨动作跟踪与 tankMl 同构: state.pumpMl 记各泵当前体积(sampling.prep 停在气隙位,
 * aspirate 在其上相对叠加), 首次驱动某泵时把驱动前的体积播种进 home.pump_ml.
 *
 * @param {string} action 动作名
 * @param {object} args 已求值的入参
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @param {Function} [onDispense] 每发完一条**打向本泵 outputPort** 的 dispense 行程步就
 *   回调一次 (at, dur, deltaMl). 展缸注液靠它把液面斜坡并到同一拍上, 见 tankFillPourer.
 *   回调必须在这里、紧跟泵步之后 push —— 理由见 push 的 at 参数说明.
 * @returns {boolean} 是否出了泵步(动作不驱泵/泵没几何/全零行程时 false, 由调用方兜底)
 */
function emitPumpSyringe(action, args, context, state, onDispense = null) {
  const cfg = context.manifest?.pumpSyringe
  if (!cfg?.pumps?.length) return false
  // 两段式: 先探出这条动作路由到哪台泵, 再拿该泵的累计体积做真正的展开(展开是纯函数,
  // 起算体积影响每一相位的相对目标与时长)
  const probe = expandPumpPlan(cfg, action, args, 0, { maxPhases: PUMP_DEMO_MAX_PHASES })
  if (!probe) return false
  if (!probe.rigged) {
    // 泵在数据上照跑(实时页面板可见), 三维没几何(收集泵) —— 交回调用方出时间格
    countNote(state, 'pump-unrigged', probe.pumpId)
    return false
  }
  const startMl = state.pumpMl.get(probe.pumpId) ?? 0
  const plan = startMl > 0
    ? expandPumpPlan(cfg, action, args, startMl, { maxPhases: PUMP_DEMO_MAX_PHASES })
    : probe
  if (!plan?.phases?.length) return false

  const spec = (cfg.pumps || []).find((item) => item.id === plan.pumpId)
  const label = String(spec?.label || plan.pumpId)
  // 本泵的出液口. onDispense 只对打向它的那一趟回调 —— 别的口是溶剂口/废液口, 打过去
  // 缸里不该涨. manifest 没给 outputPort 时恒为 null, 一趟都不回调, 调用方自然退回整段斜坡.
  const rawOut = Number(spec?.outputPort)
  const outputPort = Number.isFinite(rawOut) && rawOut > 0 ? rawOut : null
  let prev = startMl
  let currentPort = state.pumpPort.get(plan.pumpId)
  let emitted = false
  for (const phase of plan.phases) {
    if (phase.port != null && phase.port !== currentPort) {
      push(state, `${label}·阀→${phase.port}号口`, PUMP_VALVE_S,
        { pump_valve: { id: plan.pumpId, port: phase.port } }, 'inout')
      currentPort = phase.port
      emitted = true
    }
    const delta = Math.abs(phase.targetMl - prev)
    if (delta < 0.01) {
      // 零行程不发假斜坡(与 emitTankLiquid/编译器同一条); 换阀步照发
      prev = phase.targetMl
      continue
    }
    // rampS 已由 _phaseTiming 按 V/M 算成真值(取不到 V 才是动作表的名义值)
    const realS = Number(phase.rampS) || 3
    const dur = Math.min(realS, PUMP_MAX_RAMP_S)
    const timeNote = realS > dur ? `（实机 ${realS.toFixed(0)}s，演示压到 ${dur.toFixed(0)}s）` : ''
    const verb = phase.op === 'home' ? '柱塞归零' : phase.op === 'dispense' ? '排液' : '吸液'
    // 行程步的起点 —— 要在 push 它之前取. 只有真有人要并行才算(顺序扫描, 不白花)
    const strokeAt = onDispense ? timelineEnd(state) : 0
    push(state, `${label}·${verb} ${prev.toFixed(1)} → ${phase.targetMl.toFixed(1)} mL${timeNote}`,
      dur, { pump: { id: plan.pumpId, to_ml: Math.round(phase.targetMl * 1000) / 1000 } }, 'out')
    // 缸内液面与这一趟 dispense 同 at 同 dur 并行. **不能挪到下面的稳液步之后**: 那样
    // 光标会被从 strokeAt+dur+holdS 拨回 strokeAt+dur, 之后每一步都错位 holdS.
    // 判据用 currentPort(阀这一刻真在哪个口)而不是 phase.port: 相位不写口时沿用上一个.
    if (onDispense && phase.op === 'dispense' && outputPort !== null && currentPort === outputPort) {
      onDispense(strokeAt, dur, delta)
    }
    if (Number(phase.holdS) > 0) {
      push(state, `${label}·稳液 ${Number(phase.holdS).toFixed(1)}s`, Number(phase.holdS), { wait: {} })
    }
    prev = phase.targetMl
    emitted = true
  }
  if (!emitted) return false

  // home 只在首次触碰该泵时播种(与 liquid_ml 同构); 阀起手恒 1 号口
  if (!(plan.pumpId in state.home.pump_ml)) {
    state.home.pump_ml[plan.pumpId] = Math.round(startMl * 1000) / 1000
  }
  if (!(plan.pumpId in state.home.pump_port)) state.home.pump_port[plan.pumpId] = 1
  state.pumpMl.set(plan.pumpId, prev)
  if (currentPort != null) state.pumpPort.set(plan.pumpId, currentPort)
  if (plan.outerUsed < plan.outerRepeat || plan.innerUsed < plan.innerRepeat) {
    countNote(state, 'pump-rounds-compressed',
      `${action} ${plan.outerRepeat}${plan.innerRepeat ? `×${plan.innerRepeat}` : ''} 轮压到 `
      + `${plan.outerUsed}${plan.innerRepeat ? `×${plan.innerUsed}` : ''} 轮`)
  }
  return true
}

/**
 * 功能: 追加一步.
 * @param {object} state 累积状态
 * @param {string} label 步骤标签
 * @param {number} dur 时长(秒)
 * @param {object} body do 原语
 * @param {string} [ease] 缓动
 * @param {number} [at] 显式起点(秒); 缺省 = 上一步结束. 给了就是**并行**步 ——
 *   与 clipSchema.compileClip 的光标规则、编译器 ClipBuilder.emit 的 at 同一条约定.
 *   ⚠ 并行步必须紧跟在它并的那一步之后 push: timelineEnd 是顺序扫描, 显式 at 会把
 *   光标拨回去, 隔着别的步补会让后面每一步都错位.
 * @returns {void}
 */
function push(state, label, dur, body, ease = 'linear', at = undefined) {
  const step = { label, dur: Math.round(Math.max(0, dur) * 100) / 100, ease, do: body }
  if (at !== undefined) step.at = Math.round(Math.max(0, at) * 100) / 100
  state.steps.push(step)
}

/**
 * 功能: 当前时间轴末端(秒) —— 与 clipSchema.compileClip 及编译器 _timeline_end_s 逐字一致:
 * 每步 at 缺省为上一步(声明序)的 at+dur, 显式 at 则直接采用.
 * @param {object} state 累积状态
 * @returns {number} 秒
 */
function timelineEnd(state) {
  let cursor = 0
  for (const step of state.steps) {
    cursor = (step.at === undefined ? cursor : Number(step.at)) + (Number(step.dur) || 0)
  }
  return Math.round(cursor * 100) / 100
}

/**
 * 功能: 记一次"这里做了近似", 按类型计数.
 *
 * 逐条 push 的老写法在真实流程上会刷出三十几行一模一样的话(实测 system_init_all 那一屏),
 * 于是没人看 —— 而这些恰恰是"别把动画当实况"的唯一提示。计数聚合是为了让它被读进去。
 * @param {object} state 累积状态
 * @param {string} kind 近似类型
 * @param {*} [detail] 附带信息(如循环变量的取值)
 * @returns {void}
 */
function countNote(state, kind, detail) {
  const entry = state.noteCounts.get(kind) || { count: 0, details: [] }
  entry.count += 1
  if (detail !== undefined && entry.details.length < 3) entry.details.push(detail)
  state.noteCounts.set(kind, entry)
}

/**
 * 功能: 把计数汇成面向使用者的说明.
 *
 * 措辞面向"看动画的人"而不是写代码的人: 说清**动画和实机差在哪**, 而不是说编译器做了
 * 什么。带上条数, 让人知道这条流程里这种近似有多普遍。
 * @param {object} state 累积状态
 * @returns {string[]} 说明
 */
function renderNotes(state) {
  const lines = []
  const of = (kind) => state.noteCounts.get(kind)
  const branch = of('branch')
  if (branch) {
    lines.push(`这条流程有 ${branch.count} 处条件判断（“板到位了吗”这类）。`
      + '动画统一按条件成立那一支演，实机按现场反馈选另一支。')
  }
  const loop = of('loop')
  if (loop) {
    lines.push(`循环只演第 1 轮${loop.details.length ? `（${loop.details.join('、')}）` : ''}，实机会跑完整轮数。`)
  }
  if (of('parallel')) {
    lines.push('有并行动作，动画里按先后依次演，实机是同时进行。')
  }
  const moveL = of('move_l')
  if (moveL) {
    lines.push(`有 ${moveL.count} 段直线走位。动画里各关节匀速转过去，实机走空间直线`
      + ' —— 起点终点一样，中间路径不同。')
  }
  const solved = of('solved-joint')
  if (solved) {
    lines.push(`有 ${solved.count} 步走的是接近位/退离位这类派生点，它们的关节角是官方运动学`
      + '离线反解出来的，不是现场示教值。')
  }
  const tankStart = of('tank-start-unknown')
  if (tankStart) {
    lines.push(`有 ${tankStart.count} 处排液动作`
      + `${tankStart.details.length ? `（${tankStart.details.join('、')}）` : ''}`
      + '的缸，在这条流程里没有被注过液，缸内起始液量无从得知，那几步没有画液面。')
  }
  const pumpRounds = of('pump-rounds-compressed')
  if (pumpRounds) {
    lines.push(`注射泵有 ${pumpRounds.count} 处多轮往复`
      + `${pumpRounds.details.length ? `（${pumpRounds.details.join('、')}）` : ''}`
      + '按演示预算压缩了轮数，终点体积不变，实机会跑完整轮数。')
  }
  const pumpUnrigged = of('pump-unrigged')
  if (pumpUnrigged) {
    lines.push(`有 ${pumpUnrigged.count} 处泵动作落在未建几何的泵上`
      + `${pumpUnrigged.details.length ? `（${pumpUnrigged.details.join('、')}）` : ''}`
      + '，行程只以时间格表现，面板读数不受影响。')
  }
  if (of('truncated')) {
    lines.push(`步骤超过 ${MAX_STEPS} 条已截断 —— 这条流程太长，精编译后再看完整版。`)
  }
  return [...lines, ...state.notes]
}

/**
 * 功能: 把一个工具动作变成动画步(锁刀/夹爪/翻转/吸盘).
 *
 * 每一种都按**当前挂的刀号**查表: 快换锁的是哪把刀、夹爪是哪条联动组, 都取决于它。
 * 刀号不知道时**不猜** —— 猜错的表现是"动画里挂了另一把刀", 画面完全正常。
 * @param {string} verb 工具动作名
 * @param {FlowSimContext} context 环境
 * @param {object} state 累积状态
 * @param {object} where 展开位置 {depth, script}; 夹爪三态要靠它判是不是取料脚本
 * @returns {void}
 */
function emitToolAction(verb, context, state, where) {
  const { motionMap, manifest } = context
  const tool = Number(state.tool) || 0

  if (verb === 'quick-change-lock' || verb === 'quick-change-release') {
    const lock = verb.endsWith('lock')
    const asset = motionMap?.toolAsset?.[String(tool)]
    if (!asset) {
      push(state, `${lock ? '快换锁紧' : '快换释放'}（刀号未声明，不猜挂的是哪把）`,
        PLACEHOLDER_S, { wait: {} })
      state.deferred.push('robot.tool_action')
      return
    }
    const label = (manifest?.tools || []).find((item) => item.id === asset)?.label || asset
    push(state, `${lock ? '快换锁紧' : '快换释放'}：${tool}号刀 ${label}`, 0.45,
      { tool: { action: lock ? 'lock' : 'release', id: asset } })
    if (!lock) state.tool = 0
    return
  }

  if (verb === 'gripper-open' || verb === 'gripper-close') {
    const linkageId = motionMap?.gripperByTool?.[String(tool)]
    if (!linkageId) {
      push(state, `${tool ? `${tool}号刀` : '当前刀'}没有夹爪，${verb} 只写 DO`, 0, { wait: {} })
      return
    }
    const spec = (manifest?.linkages || []).find((item) => item.id === linkageId)
    // 近似档没有物料账本, 但它知道自己此刻展开到哪个脚本 —— 与实时链用 event.script 判
    // "这次合爪是不是去夹东西"是同一件事, 故口径能严格一致, 不引入第二套推断。
    const holding = isPickScript(leafScript(where?.script))
    const target = gripperTarget(verb, spec, holding)
    if (!(linkageId in state.home.linkages)) {
      state.home.linkages[linkageId] = gripperHome(verb, spec)
    }
    const how = target === 0 ? '张开' : (holding ? '夹持载荷' : '空爪紧闭')
    push(state, `${spec?.label || linkageId} → ${how}`,
      Number(spec?.transitionS) || 0.15, { linkage: { id: linkageId, to: target } }, 'inout')
    return
  }

  if (verb === 'rotary-up' || verb === 'rotary-down') {
    const id = String(motionMap?.flipActuatorId || '')
    const spec = (manifest?.actuators || []).find((item) => item.id === id)
    if (!spec) {
      push(state, `吸盘翻转（${id || '未映射'} 不在 manifest 里）`, PLACEHOLDER_S, { wait: {} })
      return
    }
    const target = verb === 'rotary-up' ? 1 : 0
    if (!(id in state.home.actuators)) state.home.actuators[id] = target > 0.5 ? 0 : 1
    push(state, target ? '吸盘上翻（托板朝上）' : '吸盘下翻（持板朝下）',
      Number(spec.transitionS) || 0.6, { actuator: { id, to: target } }, 'inout')
    return
  }

  // 吸盘真空、辅助口: 纯 DO, 没有几何可动 —— 零秒占一格, 时间轴上看得见就够了
  push(state, `末端：${verb || '工具动作'}（只写 DO，无几何）`, 0, { wait: {} })
}

/**
 * 功能: 给一根轴补 home 初值(取 manifest 的零点), 只补一次.
 *
 * 不补的话通道初值是 0, 而 0 不一定是该轴的零位 —— 播出来第一帧就会跳一下.
 * @param {object} state 累积状态
 * @param {object} manifest device-manifest
 * @param {string} axisId 轴 id
 * @returns {void}
 */
function seedAxisHome(state, manifest, axisId) {
  if (axisId in state.home.axis_mm) return
  const spec = (manifest?.axes || []).find((axis) => axis.id === axisId)
  state.home.axis_mm[axisId] = Number(spec?.zeroOffsetMm ?? 0)
}

/**
 * 功能: 槽号 → 地轨示教点.
 * @param {Map} servoIndex 示教点索引(indexServoPoints 产物)
 * @param {number} slot 槽号
 * @returns {object|null} 条目
 */
function railPointForSlot(servoIndex, slot) {
  if (!servoIndex || !Number.isInteger(slot)) return null
  for (const entry of servoIndex.values()) {
    if (entry.category === 'plc_servo' && entry.slot === slot) return entry
  }
  return null
}
