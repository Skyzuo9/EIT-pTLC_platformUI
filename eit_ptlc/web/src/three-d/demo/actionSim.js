/**
 * 功能: 上位机动作 → 可播放模拟的规划器(演示页与演示子页共用的纯逻辑).
 *
 * 四种结论:
 *   {kind:'clip', clipName}      已有 clip_compiler 编译的正式片段(实测示教点 + 离线 IK),
 *                                直接播, 几何精确
 *   {kind:'pseudo', doc, axes}   就地生成 ptlc.clip/v1 伪片段(home=当前位, 一步补间),
 *                                喂给既有 compileClip + ClipPlayer —— 不新造播放器
 *   {kind:'no-motion', reason}   这条动作本来就不驱动任何**机构**(纯读数/视觉/账本, 或
 *                                只驱泵阀这类无几何的流体件), 不是"做不到", 而是"没有可看
 *                                的东西". 两者必须分开, 否则用户会以为是模型坏了
 *   {kind:'unsupported', reason} 有机械运动但目标解析不出来 —— 明确说清缺口在哪, 并指向
 *                                「实机对照」. reason 必须是**这条动作**的实情, 不能拿一句
 *                                "目标毫米在 PLC 里"糊全部: 泵动作根本没有目标毫米
 *
 * 零 three 依赖、不发请求, 可 node --test; 点表/manifest/映射表/当前位都由调用方注入.
 *
 * 映射表(哪个动作驱动哪根轴)不在本文件里硬编码, 由 motionMap.js 从管线产物读入 ——
 * 见那里的头注释。点位到轴的对照也不手写, 由 axisIndex.js 从 manifest 派生。
 */
import { axisOfPoint } from './axisIndex.js'
import {
  fluidNote, isIgnored, lookupAction, paramAxisAction,
  sequencePointKey, sequenceSteps, tankLidLinkage, unresolvedReason,
} from './motionMap.js'
// 液面体积规则与实时页共用同一份(理由见那里的注释) —— 这张表在 manifest.tankLiquid 里,
// 刻意**不**走 action-motion-map: 同一件事导两条路就是新造一条漂移路径.
import { resolveLiquidPlan, resolveStationLiquidPlan } from '../twin/bindings/TankLiquidModel.js'
// 注液的"分几趟涨" 与 flowSim/编译器同一个来源: 泵那条动作真打出去几趟. 单动作页不发
// 泵步(它只播液面), 但趟数与单趟体积仍照泵的相位表算 —— 另起一套算法就是第二份真源.
import { expandPumpPlan } from '../twin/bindings/PumpSyringeModel.js'

/** 无机械动作的动作类别: 这些 kind 天然不驱动机构 */
const STILL_KINDS = new Set(['vision', 'camera', 'host'])

/** 只改控制器状态、不产生运动的机械臂动作 -> 说明 */
const ROBOT_STILL_ACTIONS = {
  'robot.stop': '停止只清运动队列, 停在哪取决于当时走到哪',
  'robot.pause': '暂停只挂起当前运动, 本身不产生位移',
  'robot.resume': '恢复只解除挂起, 本身不产生位移',
  'robot.emergency_stop': '急停只切使能与运动队列, 本身不产生位移',
  'robot.jog_stop': '点动停止只撤销速度指令, 本身不产生位移',
  'robot.set_speed_factor': '只改全局速度倍率, 不产生运动',
  'robot.dwell': '只在原位驻留等待, 不发运动和 IO',
  'robot.require_anchor': '只读当前反馈核对锚点位姿, 全程不运动',
}

/**
 * 功能: 从 /api/points 的载荷里索引全部 PLC 伺服示教点.
 *
 * ⚠ 字段名认的是 **`id`** 不是 `key`: 后端 DTO(api/dto.py)对外用 `id`, 只有**复合点的
 * 成员**才用 `key`; `key` 是 config/points/plc/*.yaml 里的写法, 从没出现在 API 载荷里。
 * 早先这里按 `node.key` 匹配, 结果是**一个 PLC 示教点都索引不到**, 而地轨恰好有一张
 * 数值相同的常量兜底表顶着, 于是缺陷被伪装成正常。夹具照着 YAML 写而不是照着响应写,
 * 单测也就一直是绿的 —— 所以 pointsIndex.test.js 的夹具是响应快照, 不许手写。
 *
 * 载荷分组形状不做强假设(按工位分组、字段随版本演进): 递归扫描, 认 category 前缀。
 * 复合点的成员**带点位 id 前缀**入索引(spot_pose.x_start), 避免第二个复合点静默撞名。
 *
 * `pending: true` 的点位**照样入索引**, 与 Python 侧 clip_compiler.load_servo_points 一致。
 * 早先这里排除它们, 理由是"那是 PLC 侧节点还没建的占位, 值是 0.0, 拿去驱轴等于演一个
 * 不存在的运动" —— 但 2026-08-05 从在线 PLC 实读补上真值(sample_5z=45.0 /
 * sample_5z_dip=46.5, 见 config/points/plc/sampling.yaml)之后那条理由就不成立了:
 * `pending` 现在只表示"flat 节点待建, 不能下发", 与"这个毫米值是不是真的"无关。
 * 真正的防线是下面 take() 的 Number.isFinite —— 没有值的点位本来就进不来。
 *
 * @param {*} payload /api/points 响应(或任意嵌套结构)
 * @returns {Map<string, object>} 点位 id -> 条目
 */
export function indexServoPoints(payload) {
  const index = new Map()
  const take = (id, source, category) => {
    const value = Number(source?.value)
    if (!Number.isFinite(value)) return
    index.set(id, {
      id,
      category,
      value,
      label: source.label,
      node: source.node,
      actpos: source.actpos,
      slot: Number.isFinite(Number(source.slot)) ? Number(source.slot) : undefined,
    })
  }
  const visit = (node) => {
    if (Array.isArray(node)) {
      for (const item of node) visit(item)
      return
    }
    if (!node || typeof node !== 'object') return
    const category = node.category
    if (typeof node.id === 'string' && typeof category === 'string'
      && category.startsWith('plc_servo')) {
      if (Array.isArray(node.members)) {
        const members = []
        for (const member of node.members) {
          if (typeof member?.key !== 'string') continue
          const key = `${node.id}.${member.key}`
          take(key, member, category)
          if (index.has(key)) members.push({ ...index.get(key), key: member.key })
        }
        index.set(node.id, {
          id: node.id, category, label: node.label, members, value: null,
        })
      } else {
        take(node.id, node, category)
      }
    }
    for (const child of Object.values(node)) {
      if (child && typeof child === 'object') visit(child)
    }
  }
  visit(payload)
  return index
}

/** rail 槽号 → 示教点(rail.yaml 的 plc_servo 条目带 slot) */
function railPointForSlot(servoIndex, slot) {
  for (const entry of servoIndex.values()) {
    if (entry.category === 'plc_servo' && entry.slot === slot) return entry
  }
  return null
}

/**
 * 功能: 查 manifest.realtime.axes 里的 velocityMax(mm/s).
 * @param {object} manifest device-manifest
 * @param {string} axisId 轴 id
 * @returns {number|null} velocityMax
 */
export function velocityMaxOf(manifest, axisId) {
  const item = (manifest?.realtime?.axes || []).find((axis) => axis.id === axisId)
  const value = Number(item?.velocityMax)
  return Number.isFinite(value) && value > 0 ? value : null
}

/**
 * 功能: 判一根轴是否已装配(rigged), 未装配的驱动不出效果.
 * @param {object} manifest device-manifest
 * @param {string} axisId 轴 id
 * @returns {boolean} 是否 rigged
 */
function axisRigged(manifest, axisId) {
  return Boolean((manifest?.axes || []).find((axis) => axis.id === axisId)?.rigged)
}

/**
 * 功能: 取一根轴的起始毫米(优先当前已应用位, 否则 manifest 零点).
 * @param {object} manifest device-manifest
 * @param {string} axisId 轴 id
 * @param {(id: string) => number|null} currentMmOf 当前位读取器
 * @returns {number} 毫米
 */
function axisStartMm(manifest, axisId, currentMmOf) {
  const current = Number(currentMmOf?.(axisId))
  if (Number.isFinite(current)) return current
  return Number((manifest?.axes || []).find((axis) => axis.id === axisId)?.zeroOffsetMm || 0)
}

/**
 * 功能: 按位移折算一步的时长(秒). 这是观感节拍不是物理量.
 * @param {number} travelMm 位移
 * @param {number} speedMmS 标称速度
 * @returns {number} 秒
 */
function secondsFor(travelMm, speedMmS) {
  const velocity = speedMmS > 0 ? speedMmS : 100
  return Math.round(Math.min(20, Math.max(0.5, Math.abs(travelMm) / velocity)) * 100) / 100
}

/**
 * 功能: 把若干步包成一份可编译的伪片段.
 * @param {object} options 参数
 * @returns {object} {kind:'pseudo', axes, doc, note}
 */
function pseudoClip({ name, label, home, steps, axes, note }) {
  return {
    kind: 'pseudo',
    axes: [...new Set(axes)],
    ...(note ? { note } : {}),
    doc: {
      schema: 'ptlc.clip/v1',
      name: `sim.${name}`,
      label: `模拟 · ${label}`,
      home,
      steps,
    },
  }
}

/**
 * 功能: 造一条单步的轴移动伪片段.
 *
 * @param {object} options 参数
 * @returns {object} {kind:'pseudo', axes, doc}
 */
function axisPseudo({ name, label, axisId, fromMm, toMm, stepLabel, speedMmS, manifest }) {
  return pseudoClip({
    name,
    label,
    axes: [axisId],
    home: { axis_mm: { [axisId]: fromMm } },
    steps: [{
      label: stepLabel,
      dur: secondsFor(toMm - fromMm, speedMmS || velocityMaxOf(manifest, axisId) || 100),
      ease: 'inout',
      do: { axis: { id: axisId, to_mm: toMm } },
    }],
  })
}

/**
 * 演示时长上限(秒). 排液闭环的 drain_duration_s 上限是 600s、吹气还有 30s,
 * 照实画会让一条流程在时间轴上彻底变形, 而画面看着完全正常. 与 FLUID_TIME_ACTIONS
 * 的时长同一条约定: 是观感值不是物理量, 被压缩时**在标签上写出真值**.
 */
const LIQUID_MAX_RAMP_S = 20

/** 泵相位预算; 与 flowSim / 编译器 PUMP_DEMO_MAX_PHASES 同值 —— 三方数出的趟数必须一样 */
const PUMP_DEMO_MAX_PHASES = 8

/**
 * 功能: 取一条排液动作的建议起始液位(mL) —— 单动作演示的预填值.
 *
 * 排液动作(develop.drain / develop.rinse_suction)的入参里**一滴体积都没有**, 只有
 * settle_s / drain_duration_s 这类时长: 缸里原本有多少液, 这条动作本身不知道. 于是按
 * manifest 声明的配对注液动作(demoFillFrom)去动作目录里取它的参数默认值, 走同一个
 * resolveLiquidPlan 算出体积 —— 这是个**假设**, 调用方必须把它写到标签与 note 上.
 *
 * @param {object} cfg manifest.tankLiquid
 * @param {string} name 排液动作名
 * @param {number} tank 缸号 1~8
 * @param {Array} catalog /api/actions 全量动作目录
 * @returns {{ml: number, from: string}|null} 建议体积与它出自哪条动作
 */
function suggestedStartMl(cfg, name, tank, catalog) {
  const pairName = cfg?.actions?.[name]?.demoFillFrom
  if (!pairName) return null
  const pair = (catalog || []).find((item) => item.name === pairName)
  if (!pair) return null
  const args = { [cfg.tankArg || 'target_tank']: tank }
  for (const param of pair.params || []) {
    if (param.default !== undefined && param.default !== null) args[param.name] = param.default
  }
  const plan = resolveLiquidPlan(cfg, pairName, args)
  if (!plan || !(plan.targetMl > 0)) return null
  return { ml: plan.targetMl, from: pair.label || pairName }
}

/**
 * 功能: 算出一条展缸注液动作要"分几趟涨、每趟涨到多少" —— 与 flowSim.tankFillPourer /
 * clip_compiler._tank_fill_pourer 同一口径: 单趟增量 = 泵那一趟真打向出液口的 delta.
 *
 * 单动作页没有泵步可并行(它只播液面), 所以只借相位表要趟数与增量, 不发泵步.
 * 另起一套"总量/趟数"的算法就是第二份真源 —— 轮数被 PUMP_DEMO_MAX_PHASES 压过时它会错.
 *
 * @param {object} pumpCfg manifest.pumpSyringe
 * @param {string} action 动作名
 * @param {object} params 动作入参
 * @param {number} fromMl 缸内起始体积
 * @param {number} toMl 缸内终点体积(契约总量)
 * @returns {number[]} 各趟的累计目标体积; 拆不出(泵不驱动/只有一趟/口号解不出)时返回 []
 */
function tankFillPours(pumpCfg, action, params, fromMl, toMl) {
  if (!pumpCfg?.pumps?.length) return []
  const pumpPlan = expandPumpPlan(pumpCfg, action, params, 0, { maxPhases: PUMP_DEMO_MAX_PHASES })
  if (!pumpPlan?.phases?.length) return []
  const spec = (pumpCfg.pumps || []).find((item) => item.id === pumpPlan.pumpId)
  const rawOut = Number(spec?.outputPort)
  if (!Number.isFinite(rawOut) || !(rawOut > 0)) return []

  // 判据用"阀这一刻真在哪个口"而不是 phase.port: 相位不写口时沿用上一个
  let prev = 0
  let port = null
  const deltas = []
  for (const phase of pumpPlan.phases) {
    if (phase.port != null) port = phase.port
    const delta = Math.abs(phase.targetMl - prev)
    if (delta >= 0.01 && phase.op === 'dispense' && port === rawOut) deltas.push(delta)
    prev = phase.targetMl
  }
  if (deltas.length < 2) return []          // 只有一趟, 拆了跟不拆一样

  const pours = []
  let ml = fromMl
  for (const delta of deltas) {
    const next = Math.min(ml + delta, toMl)
    if (Math.abs(next - ml) < 0.05) break   // 已封顶, 后面几趟不会再涨
    pours.push(next)
    ml = next
  }
  // 轮数被压缩时终点体积不许变(与泵那条"压缩轮数不截相位"同一条纪律)
  if (pours.length > 0 && toMl - pours[pours.length - 1] >= 0.05) pours[pours.length - 1] = toMl
  return pours.length > 1 ? pours : []
}

/**
 * 功能: 把一条展缸流体动作译成液面动画步(不含关盖等同时发生的机构动作).
 *
 * 体积规则不在这里定义 —— 整段查 manifest.tankLiquid, 与实时页 TankLiquidModel 共用
 * 同一个 resolveLiquidPlan. 这里只负责"译成关键帧步"这一件事.
 *
 * @param {object} context planSimulation 的上下文
 * @param {string} name 动作名
 * @param {object} params 动作入参
 * @returns {null|{steps: object[], homeMl: object, note: string, needsStartMl: boolean,
 *                 startMlSuggested: number|null, reason: string}}
 */
function tankLiquidSteps(context, name, params) {
  const cfg = context?.manifest?.tankLiquid
  // 与 TankLiquidModel.enabled 同一条判据: 管线可以按 rig_map 停用液面盒
  if (!cfg?.cavity) return null
  const plan = resolveLiquidPlan(cfg, name, params)
  if (!plan) return null
  const tankNo = plan.index + 1
  // 按 index 字段查而不是按数组下标: 两者在现役 manifest 里恰好一致, 但那是巧合 ——
  // 少认出一个缸就会错位, 表现是"往 3 号缸注液, 画面上涨的是 4 号"
  const tank = (context.manifest.tanks || []).find((item) => item.index === plan.index)
  // 某个缸的溶液槽没认出来时只有那一个缺 liquidNode —— 不能拿别的缸顶替
  if (!tank?.id || !tank.liquidNode) {
    return { reason: `展缸 ${tankNo} 没有液面几何(该缸的溶液槽未被管线识别), 不表现液面` }
  }

  const capacityMl = Number(cfg.cavity.capacityMl) || 0
  let fromMl = 0
  let note = ''
  let needsStartMl = false
  let startMlSuggested = null

  if (plan.dir !== 'fill') {
    // 排液: 起点只能来自外部. 优先用面板给的, 其次用配对注液动作的默认配方.
    needsStartMl = true
    const suggestion = suggestedStartMl(cfg, name, tankNo, context.actionCatalog)
    startMlSuggested = suggestion ? suggestion.ml : null
    const given = Number(context.startMl)
    if (Number.isFinite(given) && given > 0) {
      fromMl = capacityMl > 0 ? Math.min(given, capacityMl) : given
      note = `起始液位 ${fromMl.toFixed(1)} mL 由面板指定, 非实机数据 —— 排液动作本身不带体积`
    } else if (suggestion) {
      fromMl = suggestion.ml
      note = `起始液位按「${suggestion.from}」的目录默认配方假设为 ${fromMl.toFixed(1)} mL,`
        + ' 非实机数据 —— 缸内原有多少液, 这条动作本身不知道'
    } else {
      return {
        needsStartMl: true,
        startMlSuggested: null,
        reason: '排液动作本身不带体积, 单条动作演示定不出起始液位 ——'
          + ' 先播「展缸-上液」看注液, 整条注-排循环请到「演示」栏看 develop_prepare',
      }
    }
  }

  const toMl = plan.dir === 'fill' ? plan.targetMl : 0
  const steps = []
  // 沉降延时(润洗抽吸的 settle_s): 先静置再抽, 这是 TankLiquidModel.step() 里
  // running.delayS 的关键帧写法, 观感等价
  if (plan.delayS > 0) {
    steps.push({
      label: `${tankNo}号缸静置沉降 ${plan.delayS.toFixed(0)}s`,
      dur: Math.min(plan.delayS, LIQUID_MAX_RAMP_S),
      do: { wait: {} },
    })
  }

  const clamped = plan.rampS > LIQUID_MAX_RAMP_S
  const dur = clamped ? LIQUID_MAX_RAMP_S : plan.rampS
  const timeNote = clamped ? `(实机 ${plan.rampS.toFixed(0)}s, 演示压到 ${dur}s)` : ''
  const pct = capacityMl > 0 ? Math.round((Math.max(fromMl, toMl) / capacityMl) * 100) : null
  const pctNote = pct === null ? '' : `, 占槽容 ${pct}%`
  // 注液逐趟涨: 真实配方是"抽满一筒 → 打进缸 → 再抽一筒", 一条斜坡到底看不出趟数.
  // 拆不出趟(排液/泵不驱动/只有一趟)时 pours 为空, 走下面那条整段斜坡, 行为不变.
  const pours = plan.dir === 'fill'
    ? tankFillPours(context?.manifest?.pumpSyringe, name, params, fromMl, toMl)
    : []
  if (pours.length > 1) {
    // 均分本动作的 rampS: 单动作页没有泵步定节拍, 总时长与改前一致
    const each = Math.round((dur / pours.length) * 100) / 100
    let segFrom = fromMl
    pours.forEach((segTo, i) => {
      const segPct = capacityMl > 0 ? `, 占槽容 ${Math.round((segTo / capacityMl) * 100)}%` : ''
      steps.push({
        label: `${tankNo}号缸注液 ${segFrom.toFixed(1)} → ${segTo.toFixed(1)} mL`
          + `(第 ${i + 1}/${pours.length} 趟${segPct})${i === 0 ? timeNote : ''}`,
        dur: each,
        ease: 'out',
        do: { liquid: { id: tank.id, to_ml: segTo } },
      })
      segFrom = segTo
    })
  } else {
    steps.push({
      label: `${tankNo}号缸${plan.dir === 'fill' ? '注液' : '排液'} `
        + `${fromMl.toFixed(1)} → ${toMl.toFixed(1)} mL${pctNote}${timeNote}`,
      dur,
      // out(先快后缓、永不过冲)最接近实时侧 TankLiquidModel 的指数趋近观感;
      // 默认的 inout 会在起步处出现一段假的加速
      ease: 'out',
      do: { liquid: { id: tank.id, to_ml: toMl } },
    })
  }

  // 注液默认只有 2.0 mL —— 在 102.5 mL 的槽里放大后也就 0.8mm 高, 画面上基本看不见.
  // 不写这句的话它会被当成"功能没生效"来报, 而真实配方(develop_prepare)是 20mL × 3 趟.
  if (plan.dir === 'fill' && pct !== null && pct < 5) {
    const faint = `注入 ${toMl.toFixed(1)} mL 只占槽容 ${pct}%, 液面几乎看不见 ——`
      + ' 真实配方在 develop_prepare 里是 20 mL × 3 趟, 把入参调大再看'
    note = note ? `${note}; ${faint}` : faint
  }

  return { steps, homeMl: { [tank.id]: fromMl }, note, needsStartMl, startMlSuggested }
}

/**
 * 功能: 把一条驻位液体动作(collect.collect)译成逐轮液面步 —— 单动作演示档.
 *
 * 规则同 flowSim.emitStationLiquid / clip_compiler.emit_station_liquid: 真源是
 * manifest.liquids[].actions(gen_twin_manifest.STATION_LIQUID_ACTIONS), 经
 * resolveStationLiquidPlan 解析, 这里只译步. 单动作没有流程上下文, 瓶内起手恒 0 mL ——
 * 这正是收集-执行的真实起点, 无需像排液那样做起始液位假设.
 *
 * @param {object} context planSimulation 的上下文
 * @param {string} name 动作名
 * @param {object} params 动作入参
 * @returns {null|{steps: object[], homeMl: object, note: string}}
 */
function stationLiquidSteps(context, name, params) {
  for (const spec of context?.manifest?.liquids || []) {
    const plan = resolveStationLiquidPlan(spec, name, params)
    if (!plan) continue
    const capacity = Number(spec.cavity?.capacityMl) || 0
    const steps = []
    let fromMl = 0
    for (let i = 0; i < plan.roundsShown; i += 1) {
      const toMl = capacity > 0
        ? Math.min(fromMl + plan.perRoundMl, capacity)
        : fromMl + plan.perRoundMl
      steps.push({
        label: `收集·泵吸排洗脱剂 ${plan.perRoundMl} mL`
          + `(第 ${i + 1}/${plan.roundsTotal} 轮, 实机≈${plan.real.pump}s)`,
        dur: Math.min(plan.demo.pump, LIQUID_MAX_RAMP_S),
        do: { wait: {} },
      })
      steps.push({
        label: `收集·正压排液入瓶 ${fromMl.toFixed(2)} → ${toMl.toFixed(2)} mL`
          + `(实机≈${plan.real.transfer}s, 演示压到 ${plan.demo.transfer}s)`,
        dur: Math.min(plan.demo.transfer, LIQUID_MAX_RAMP_S),
        ease: 'out',
        do: { liquid: { id: plan.liquidId, to_ml: toMl } },
      })
      steps.push({
        label: `收集·静置沉淀(实机≈${plan.real.settle}s)`,
        dur: Math.min(plan.demo.settle, LIQUID_MAX_RAMP_S),
        do: { wait: {} },
      })
      fromMl = toMl
    }
    const note = plan.roundsShown < plan.roundsTotal
      ? `共 ${plan.roundsTotal} 轮洗脱, 演示只演前 ${plan.roundsShown} 轮(轮内节拍不变)` : ''
    return { steps, homeMl: { [plan.liquidId]: 0 }, note }
  }
  return null
}

/**
 * 功能: 找一个机构的 manifest 条目 —— actuators 与 linkages 两处都找.
 *
 * 两处都找是必须的: col_clamp 是收集工位的双指夹持, 在 rig_map 里是一条**联动组**
 * (两个指爪同步), 而动作映射表把它当气缸(它在真机上确实就是一个气缸)。只查 actuators
 * 的话它会被报成"未绑定几何", 但几何明明在。
 *
 * @param {object} manifest device-manifest
 * @param {string} id 机构 id
 * @returns {{spec: object, channel: string}|null} 条目与它该走的通道名
 */
function mechanismOf(manifest, id) {
  const actuator = (manifest?.actuators || []).find((item) => item.id === id)
  if (actuator) return { spec: actuator, channel: 'actuator' }
  const linkage = (manifest?.linkages || []).find((item) => item.id === id)
  if (linkage) return { spec: linkage, channel: 'linkage' }
  return null
}

/**
 * 功能: 展开映射表里的多步定值序列(SEQUENCE_ACTIONS).
 *
 * @param {object} action 动作定义
 * @param {object} params 已归一的入参
 * @param {Array<object>} declared 步骤声明
 * @param {object} context 环境
 * @returns {object} plan
 */
function sequencePlan(action, params, declared, context) {
  const { manifest, servoIndex, currentMmOf } = context
  const home = { axis_mm: {}, actuators: {}, linkages: {} }
  const steps = []
  const axes = []
  const skipped = []
  const axisNow = new Map()

  for (const step of declared) {
    if (step.kind === 'axis' || step.kind === 'point') {
      let axisId = step.axis
      let toMm = Number(step.toMm)
      if (step.kind === 'point') {
        // 两种编码(字面点位 / 入参间接)由 sequencePointKey 统一, 与编译器同式;
        // 复合点位(点样位置)的成员按 `<点位key>.<成员key>` 索引, 与 indexServoPoints 同规则
        const { key, arg } = sequencePointKey(step, params)
        if (!key) {
          // 只有 arg 形态才可能"用户还没选"; 字面形态取不到 key 是表坏了, 别栽给用户
          return arg
            ? { kind: 'unsupported', reason: `请先在参数里选一个点位(${arg})` }
            : { kind: 'unsupported', reason: `映射表里这一步没写点位(${step.label || action.name})` }
        }
        const point = servoIndex?.get(String(key))
        if (!point || !Number.isFinite(Number(point.value))) {
          return { kind: 'unsupported', reason: `点表里没有点位 ${key} —— /api/points 不可用, 或该点还没示教` }
        }
        toMm = Number(point.value)
        axisId = axisOfPoint(manifest, point) || axisId
      }
      if (!axisId || !axisRigged(manifest, axisId)) {
        skipped.push(axisId || step.label || step.arg || step.point)
        continue
      }
      if (!(axisId in home.axis_mm)) {
        home.axis_mm[axisId] = axisStartMm(manifest, axisId, currentMmOf)
        axisNow.set(axisId, home.axis_mm[axisId])
      }
      steps.push({
        label: `${step.label}${step.kind === 'point' ? ` → ${toMm} mm` : ''}`,
        dur: secondsFor(toMm - axisNow.get(axisId), Number(step.speedMmS)),
        ease: 'inout',
        do: { axis: { id: axisId, to_mm: toMm } },
      })
      axisNow.set(axisId, toMm)
      axes.push(axisId)
      continue
    }
    if (step.kind === 'well') {
      // 孔位是从孔板标定仿射算出来的, 而标定只在编译期可见(clip_compiler.load_demo_well_mm
      // 读 config/calibration.yaml), 映射表**不导出**这个毫米值。所以前端只能照编译器
      // 未标定分支的语义占一个说明白的时间格 —— 编一个孔位比不动更糟。
      steps.push({ label: `${step.label}(孔板未标定, 未表现)`, dur: 0.4, do: { wait: {} } })
      continue
    }
    if (step.kind !== 'actuator' && step.kind !== 'linkage') {
      // 表是 Python 侧长的, 将来新增步骤类型时这里要跟上; 静默跳过会让演示少演一段而
      // 毫无迹象(正是 point 字面编码那个缺陷的病理)
      return { kind: 'unsupported', reason: `映射表里有前端还不认识的步骤类型: ${step.kind} —— 用「实机对照」` }
    }
    // 气缸/联动组: 表里写的是"该动作把它驱到哪", 存放位置以 manifest 为准
    const found = mechanismOf(manifest, step.id)
    if (!found) {
      skipped.push(step.id)
      continue
    }
    const target = Number(step.value)
    const bucket = found.channel === 'linkage' ? home.linkages : home.actuators
    // 值语义: 1 = 动点 = 建模基线. home 必须显式给, 通道隐式初值是 0
    if (!(step.id in bucket)) bucket[step.id] = target > 0.5 ? 0 : 1
    steps.push({
      label: step.label,
      dur: Number(found.spec.transitionS) || 0.5,
      ease: 'inout',
      do: { [found.channel]: { id: step.id, to: target } },
    })
  }

  if (!steps.length) {
    return {
      kind: 'unsupported',
      reason: `该动作驱动的 ${skipped.join('、')} 在三维里没有几何(rig_map 里是纯状态条目) —— 用「实机对照」`,
    }
  }
  return pseudoClip({
    name: action.name,
    label: action.label || action.name,
    home,
    steps,
    axes,
    note: skipped.length ? `其中 ${skipped.join('、')} 在三维里没有几何, 未表现` : '',
  })
}

/**
 * 功能: 把 point_ref 入参指向的示教点直接变成动画(无需手工映射).
 *
 * 轴由 axisIndex 从 manifest 派生(点位 actpos === 轴 telemetry.key), 所以现场新增一个
 * 目标点位、动作加一个 point_ref 参数, 这里不用改一行就能播。
 *
 * @param {object} action 动作定义
 * @param {object} params 已归一的入参
 * @param {object} context 环境
 * @returns {object|null} plan; 该动作没有 point_ref 参数时返回 null
 */
function pointRefPlan(action, params, context) {
  const param = (action.params || []).find((item) => item?.type === 'point_ref')
  if (!param) return null
  const { manifest, servoIndex, currentMmOf } = context
  const key = params?.[param.name]
  if (!key) {
    return { kind: 'unsupported', reason: `请先在参数里选一个点位(${param.label || param.name})` }
  }
  const point = servoIndex?.get(String(key))
  if (!point) {
    return { kind: 'unsupported', reason: `点表里没有点位 ${key} —— /api/points 不可用, 或该点还没示教` }
  }

  // 复合点(如点样位置)按成员声明序逐条走: x_start → x_end 正是那条扫描带
  const members = Array.isArray(point.members) && point.members.length
    ? point.members
    : [{ ...point, key: point.id }]
  const home = { axis_mm: {} }
  const steps = []
  const axes = []
  const skipped = []
  const axisNow = new Map()

  for (const member of members) {
    const axisId = axisOfPoint(manifest, member)
    if (!axisId || !axisRigged(manifest, axisId)) {
      skipped.push(member.label || member.key)
      continue
    }
    // 成员覆盖: spot_band_layer 允许用同名入参临时改写示教基准, 演示要跟着走
    const override = Number(params?.[member.key])
    const toMm = Number.isFinite(override) ? override : Number(member.value)
    if (!Number.isFinite(toMm)) {
      skipped.push(member.label || member.key)
      continue
    }
    if (!(axisId in home.axis_mm)) {
      home.axis_mm[axisId] = axisStartMm(manifest, axisId, currentMmOf)
      axisNow.set(axisId, home.axis_mm[axisId])
    }
    steps.push({
      label: `${member.label || member.key} → ${toMm} mm`,
      dur: secondsFor(toMm - axisNow.get(axisId), velocityMaxOf(manifest, axisId) || 50),
      ease: 'inout',
      do: { axis: { id: axisId, to_mm: toMm } },
    })
    axisNow.set(axisId, toMm)
    axes.push(axisId)
  }

  if (!steps.length) {
    return { kind: 'unsupported', reason: `点位 ${key} 派生不出任何已装配的轴(缺 actpos 或轴未 rigged)` }
  }
  return pseudoClip({
    name: action.name,
    label: `${action.label || action.name}(${point.label || key})`,
    home,
    steps,
    axes,
    note: skipped.length ? `点位成员 ${skipped.join('、')} 派生不出轴, 未表现` : '',
  })
}

/**
 * 功能: 机械臂动作的规划(点位关节角 / 工具动作 / 纯控制态).
 * @param {object} action 动作定义
 * @param {object} params 已归一的入参
 * @param {object} context 环境
 * @returns {object|null} plan; 不是本函数管的动作返回 null
 */
function robotPlan(action, params, context) {
  const name = action.name
  if (name in ROBOT_STILL_ACTIONS) {
    return { kind: 'no-motion', reason: ROBOT_STILL_ACTIONS[name] }
  }
  if (name === 'robot.move_to_point' || name === 'robot.home') {
    const pointId = name === 'robot.home' ? 'robot-main.home' : params?.point_id_or_robot_name
    if (!pointId) return { kind: 'unsupported', reason: '请先在参数里填一个点位' }
    const hit = jointsOfPoint(context.pointCatalog, pointId)
    if (!hit) {
      return {
        kind: 'unsupported',
        reason: `点位 ${pointId} 既没有实测关节角也反解不出来 —— 用「实机对照」`,
      }
    }
    const motion = String(params?.motion || 'move_j')
    const notes = []
    if (motion === 'move_l') notes.push('直线段按关节插值, 实机走空间直线 —— 起终点一样, 中间路径不同')
    if (hit.source === 'solved') notes.push('该点位的关节角是离线反解的, 不是现场示教值')
    return {
      kind: 'pseudo',
      axes: [],
      ...(notes.length ? { note: notes.join('; ') } : {}),
      doc: {
        schema: 'ptlc.clip/v1',
        debug: true,
        name: `sim.${name}`,
        label: `模拟 · ${action.label || name}`,
        home: { joints_deg: hit.joints },
        steps: [{
          label: `机械臂 → ${pointId}${hit.source === 'solved' ? '（反解）' : ''}`,
          dur: 1.2,
          ease: 'inout',
          do: { joints: { to_deg: hit.joints } },
        }],
      },
    }
  }
  if (name === 'robot.tool_action') {
    return toolActionPlan(action, String(params?.action || ''), context)
  }
  return null
}

/**
 * 功能: robot.tool_action 按 verb 分流.
 * @param {object} action 动作定义
 * @param {string} verb 工具动作名
 * @param {object} context 环境
 * @returns {object} plan
 */
function toolActionPlan(action, verb, context) {
  if (!verb) return { kind: 'unsupported', reason: '请先在参数里选一个工具动作' }
  if (verb === 'rotary-up' || verb === 'rotary-down') {
    const id = String(context.motionMap?.flipActuatorId || '')
    const found = mechanismOf(context.manifest, id)
    if (!found) return { kind: 'unsupported', reason: `翻转机构 ${id || '未映射'} 不在 manifest 里` }
    const target = verb === 'rotary-up' ? 1 : 0
    return pseudoClip({
      name: action.name,
      label: `${action.label || action.name} · ${verb}`,
      home: { actuators: { [id]: target > 0.5 ? 0 : 1 } },
      steps: [{
        label: verb === 'rotary-up' ? '吸盘上翻(托板朝上)' : '吸盘下翻(持板朝下)',
        dur: Number(found.spec.transitionS) || 0.6,
        ease: 'inout',
        do: { actuator: { id, to: target } },
      }],
      axes: [],
    })
  }
  // 快换锁的是哪把刀、夹爪是哪条联动组, 都取决于**当前挂的是几号刀** —— 而单条动作
  // 演示没有上下文可以告诉我们那件事(流程里是 robot_tool_pick 的 tool_id 声明的)。
  // 从前这里写死 2 号刀(96 孔板夹爪), 于是上样取 1 号玻璃吸盘时动画照样挂 96 孔板夹爪,
  // 画面看着完全正常。宁可说"定不下来", 也不挂一把错的。
  if (verb === 'quick-change-lock' || verb === 'quick-change-release') {
    return {
      kind: 'unsupported',
      reason: '快换锁/放的是哪把刀取决于当前挂的刀号, 单条动作演示没有这个上下文 —— 到「演示」栏看整条换刀流程',
    }
  }
  if (verb.startsWith('gripper-')) {
    // 拒的是"挂的是几号刀"定不下来, 不是"合多少"定不下来 —— gripSemantics 的三态补的是
    // 后者, 补不上前者。而且合爪的开度还要知道爪里有没有载荷 (夹持 0.101/0.288 vs
    // 空爪紧闭 1.0), 单条动作同样没有这个上下文。两个未知量, 这里一个都拿不到。
    return {
      kind: 'unsupported',
      reason: '夹爪开合取决于当前挂的是几号刀(2 号板夹爪 / 3 号瓶电爪), 且合爪开度还取决于爪里有没有载荷; 单条动作演示两者都定不下来 —— 到「演示」栏看整条流程',
    }
  }
  return { kind: 'no-motion', reason: `${verb} 只写末端 DO, 没有几何可动` }
}

/**
 * 功能: 从点位目录取一个点位的关节角, 并说明这组角是**实测**还是**离线反解**的.
 *
 * 两种来源必须分得开:
 *   taught  现场示教出来的实测值, 点位目录的 `joint` 字段
 *   solved  管线用官方运动学离线反解出来的, `jointSolved` 字段(接近位/退离位/货架库位
 *           这些派生点只有 pose, 全靠它才动得起来 —— 见 sync_ptlc_robot._solve_derived_joints)
 * 反解值残差为零、位形分支由父示教点的种子定死, 拿来放动画是可靠的; 但它终究不是现场
 * 量出来的那个数, 所以时间轴上要标出来, 不能与实测点混为一谈.
 *
 * 全零一律当占位丢弃(与 clipSchema 的 move_j 门禁同判据), 拿它插值会把臂甩到一个不存在
 * 的姿态.
 *
 * @param {object} catalog ptlc.robot-points/v1 目录
 * @param {string} pointId 点位 id / 示教名 / 别名
 * @returns {{joints: number[], source: 'taught'|'solved'}|null} 关节角与来源; 都没有返回 null
 */
export function jointsOfPoint(catalog, pointId) {
  const points = catalog?.points || {}
  const point = points[pointId]
    || Object.values(points).find((item) => item?.robotName === pointId || item?.alias === pointId)
  const usable = (values) => Array.isArray(values) && values.length === 6
    && values.some((value) => Math.abs(Number(value)) > 1e-9)
  if (usable(point?.joint)) return { joints: point.joint.map(Number), source: 'taught' }
  if (usable(point?.jointSolved)) return { joints: point.jointSolved.map(Number), source: 'solved' }
  return null
}

/**
 * 功能: 规划一个动作的模拟方式.
 *
 * 判定顺序即优先级, 顺序本身是有讲究的:
 *   正式片段 > 编译器声明的无动作 > 各类机构映射 > 按 kind 判无动作 > 流体 > 说不清的
 * 「按 kind 判无动作」必须排在 SEARCH_AXIS 之前 —— feedlift.probe_stack 是 host 只读
 * 动作, 却因为在搜索表里而曾被报成"无法模拟"。
 *
 * @param {object} action 动作定义(ActionDefDTO: {name, kind, label, params...})
 * @param {object} params 用户填的参数值(已按 schema 归一)
 * @param {object} context 环境
 * @param {Map} context.servoIndex indexServoPoints 产物
 * @param {object} context.manifest device-manifest
 * @param {string[]} context.clipNames 已有正式片段名
 * @param {object|null} context.motionMap 动作→机构映射表(管线产物)
 * @param {object|null} context.pointCatalog 机器人点位目录(generated/robot-points.json)
 * @param {(axisId: string) => number|null} context.currentMmOf 轴当前已应用 mm
 * @returns {{kind: string, clipName?: string, doc?: object, axes?: string[], reason?: string, note?: string}}
 */
export function planSimulation(action, params, context) {
  const { servoIndex, manifest, clipNames, motionMap, currentMmOf } = context
  const name = action?.name || ''
  if (!name) return { kind: 'unsupported', reason: '动作定义为空' }

  // 1) 已有 clip_compiler 编译的正式片段, 优先播它
  if ((clipNames || []).includes(name)) {
    return { kind: 'clip', clipName: name }
  }

  // 2) 编译器明确列为"不产生机构运动"的动作
  if (isIgnored(motionMap, name)) {
    return { kind: 'no-motion', reason: '该动作只读状态或改账本, 不驱动任何机构' }
  }

  // 3) 地轨移动: 槽号 → 示教点毫米 → axis_11y 伪片段
  //    这里**没有常量兜底**: 点表读不到就如实说读不到。曾经有一张与点表数值相同的常量表
  //    顶在这儿, 结果是现场重新示教后演示继续显示陈旧值, 且没有任何提示。
  if (name === 'rail.move' || name === 'rail.ensure') {
    const slot = Number(params?.Rail_Target_Position)
    if (!Number.isInteger(slot) || slot < 1 || slot > 6) {
      return { kind: 'unsupported', reason: '缺少有效的地轨目标位(1~6)' }
    }
    const point = railPointForSlot(servoIndex || new Map(), slot)
    if (!point) {
      return { kind: 'unsupported', reason: `点表里找不到槽 ${slot} 的地轨示教点(/api/points 不可用?)` }
    }
    if (!axisRigged(manifest, 'axis_11y')) {
      return { kind: 'unsupported', reason: '地轨轴未装配(rigged:false)' }
    }
    return axisPseudo({
      name,
      label: `${action.label || name}(槽${slot} ${point.label || ''})`.trim(),
      axisId: 'axis_11y',
      fromMm: axisStartMm(manifest, 'axis_11y', currentMmOf),
      toMm: point.value,
      stepLabel: `地轨 → ${point.value} mm(${point.label || `槽${slot}`})`,
      manifest,
    })
  }

  // 4) 映射表里的多步定值序列(目标烧在 PLC 程序里的常量)
  const declared = sequenceSteps(motionMap, name)
  if (declared) {
    const plan = sequencePlan(action, params, declared, context)
    return withFluidNote(plan, motionMap, name)
  }

  // 5) 目标毫米直接来自入参的轴动作
  const paramAxis = paramAxisAction(motionMap, name)
  if (paramAxis) {
    const target = Number(params?.[paramAxis.arg])
    if (!Number.isFinite(target)) {
      return { kind: 'unsupported', reason: `请先填入参 ${paramAxis.arg}` }
    }
    if (!axisRigged(manifest, paramAxis.axis)) {
      return { kind: 'unsupported', reason: `${paramAxis.axis} 未装配(rigged:false), 无几何可动` }
    }
    return axisPseudo({
      name,
      label: action.label || name,
      axisId: paramAxis.axis,
      fromMm: axisStartMm(manifest, paramAxis.axis, currentMmOf),
      toMm: target,
      stepLabel: `${paramAxis.label} → ${target} mm`,
      speedMmS: Number(paramAxis.speedMmS) || 0,
      manifest,
    })
  }

  // 6) 映射表里的单条定值动作: 轴到位 / 气缸 / 缸盖
  const mapped = lookupAction(motionMap, name)
  if (mapped?.kind === 'axis') {
    if (!axisRigged(manifest, mapped.axis)) {
      return { kind: 'unsupported', reason: `${mapped.axis} 未装配(rigged:false), 无几何可动` }
    }
    return axisPseudo({
      name,
      label: action.label || name,
      axisId: mapped.axis,
      fromMm: axisStartMm(manifest, mapped.axis, currentMmOf),
      toMm: Number(mapped.toMm),
      stepLabel: mapped.label || `${mapped.axis} → ${mapped.toMm} mm`,
      speedMmS: Number(mapped.speedMmS) || 0,
      manifest,
    })
  }
  if (mapped?.kind === 'actuator') {
    const target = mapped.value !== undefined
      ? Number(mapped.value)
      : Number(Boolean(params?.[mapped.arg]))
    const found = mechanismOf(manifest, mapped.id)
    if (!found) {
      return { kind: 'unsupported', reason: `机构 ${mapped.id} 未绑定几何, 无动画可播` }
    }
    const bucket = found.channel === 'linkage' ? 'linkages' : 'actuators'
    return pseudoClip({
      name,
      label: action.label || name,
      home: { [bucket]: { [mapped.id]: target > 0.5 ? 0 : 1 } },
      steps: [{
        label: `${found.spec.label || mapped.id} → ${target > 0.5 ? '动点' : '原点'}`,
        dur: Number(found.spec.transitionS) || 1,
        ease: 'inout',
        do: { [found.channel]: { id: mapped.id, to: target } },
      }],
      axes: [],
    })
  }
  if (mapped?.kind === 'tank-lid') {
    const tank = Number(params?.target_tank)
    if (!Number.isInteger(tank) || tank < 1 || tank > 8) {
      return { kind: 'unsupported', reason: '缺少有效的展缸号(1~8)' }
    }
    const linkageId = tankLidLinkage(motionMap, tank)
    const spec = (manifest?.linkages || []).find((item) => item.id === linkageId)
    if (!spec) {
      return { kind: 'unsupported', reason: `展缸 ${tank} 的缸盖联动组未在 manifest 里(${linkageId || '未映射'})` }
    }
    // develop.rinse_fill 既关盖又注液 —— 两件事**叠加**而不是二选一: 它同时在
    // TANK_LID_ACTIONS 与 tankLiquid.actions 两张表里. 液面步显式给 at: 0 与关盖并行.
    const liquid = tankLiquidSteps(context, name, params)
    const liquidSteps = (liquid?.steps || []).map((step, i) => (i === 0 ? { ...step, at: 0 } : step))
    // 值语义: 1 = 动点 = 关盖 = 建模基线, 0 = 原点 = 开盖. home 必须显式给,
    // 通道隐式初值是 0, 缺省会让盖在 t=0 就已经开着.
    return withFluidNote(pseudoClip({
      name,
      label: `${action.label || name}(${tank}号缸)`,
      home: {
        linkages: { [linkageId]: mapped.value > 0.5 ? 0 : 1 },
        ...(liquid?.homeMl ? { liquid_ml: liquid.homeMl } : {}),
      },
      steps: [{
        label: `${spec.label || linkageId} → ${mapped.value > 0.5 ? '关盖' : '开盖'}`,
        dur: Number(spec.transitionS) || 1,
        ease: 'inout',
        do: { linkage: { id: linkageId, to: mapped.value } },
      }, ...liquidSteps],
      axes: [],
      note: liquid?.note || '',
    }), motionMap, name, Boolean(liquidSteps.length))
  }

  // 7) 机械臂: 到点用实测关节角, 工具动作按 verb 分流, 纯控制态如实说不动
  if (action?.kind === 'robot') {
    const plan = robotPlan(action, params, context)
    if (plan) return plan
  }

  // 8) point_ref 入参 → 点表 → 轴(由 actpos 派生, 无需手工映射)
  const byPoint = pointRefPlan(action, params, context)
  if (byPoint) return withFluidNote(byPoint, motionMap, name)

  // 9) 本来就没有机械动作的类别. 必须排在 SEARCH_AXIS 之前
  if (STILL_KINDS.has(action?.kind)) {
    const why = {
      vision: '视觉动作只出识别结果, 不驱动机构',
      camera: '相机动作只触发采集, 不驱动机构',
      host: '上位机动作只读状态或算数, 不驱动机构',
    }
    return { kind: 'no-motion', reason: why[action.kind] }
  }

  // 10) 有机械运动但目标值 PC 侧拿不到 —— 逐条说清缺口在哪.
  //     排在 search 之前: 一条动作若两张表都进了, 说得具体的那条赢
  //     (sampling.place_axis 就是: 它不是"运行期才知道", 是"值在 PLC 的数组槽里")
  const unresolved = unresolvedReason(motionMap, name)
  if (unresolved) return { kind: 'unsupported', reason: unresolved }

  // 11) 行程由运行期光电/视觉决定, 编译期根本没有目标值
  if (mapped?.kind === 'search') {
    return {
      kind: 'unsupported',
      reason: `${mapped.label || '该动作'}的行程由运行期光电/视觉决定, 编译期没有目标值 —— 用「实机对照」`,
    }
  }

  // 12) 展缸注/排液: 泵与阀本体没有几何, 但**缸里的液面是看得见的**, 那正是要演的.
  //     排在下面那条泛化的流体兜底之前 —— 说得具体的那条赢.
  const liquid = tankLiquidSteps(context, name, params)
  if (liquid?.steps) {
    const plan = withFluidNote(pseudoClip({
      name,
      label: action.label || name,
      home: { liquid_ml: liquid.homeMl },
      steps: liquid.steps,
      axes: [],
      note: liquid.note,
    }), motionMap, name, true)
    // 排液即使已按建议值播起来了, 也要让面板知道"这个数可以改"
    return liquid.needsStartMl
      ? { ...plan, needsStartMl: true, startMlSuggested: liquid.startMlSuggested }
      : plan
  }

  // 12b) 驻位液体(收集样品瓶): 与展缸同位阶, 两表按动作互斥 —— 说得具体的那条赢
  const station = stationLiquidSteps(context, name, params)
  if (station?.steps) {
    return withFluidNote(pseudoClip({
      name,
      label: action.label || name,
      home: { liquid_ml: station.homeMl },
      steps: station.steps,
      axes: [],
      note: station.note,
    }), motionMap, name, true)
  }

  const fluid = fluidNote(motionMap, name)

  // 13) 液面本该能演、但缺一个定不出来的量(典型: 排液动作没有起始液位).
  //     必须**独立于 fluidNote 成立** —— 否则这条动作一旦不在 fluidActions 表里,
  //     具体的缺口说明就被下面的兜底吞成一句"还没有进映射表", 而那是错的.
  //     与 UNRESOLVED_ACTIONS 里 robot.step("步进没有起点 —— 用实机对照")同一条纪律:
  //     说清缺在哪、去哪能看到, 而不是编一个体积出来.
  if (liquid?.reason) {
    return {
      kind: 'no-motion',
      reason: fluid ? `${liquid.reason}。(该动作驱动 ${fluid})` : liquid.reason,
      ...(liquid.needsStartMl ? { needsStartMl: true, startMlSuggested: liquid.startMlSuggested } : {}),
    }
  }

  // 14) 只驱泵/阀/真空: 有事发生, 单动作演示暂不表现 —— 注意措辞别写成"三维不表现":
  //     注射泵柱塞行程在流程演示(精编译片段与近似档)与实时页都会动, 只有本单动作面板
  //     缺跨动作的累计体积上下文, 才退到文字说明。
  if (fluid) {
    return {
      kind: 'no-motion',
      reason: `该动作驱动 ${fluid}; 单动作演示缺跨动作的体积上下文暂不表现, `
        + '注射泵柱塞行程请在流程演示或实时页查看',
    }
  }

  // 15) 写点动作: 只把数值写进 PLC, 机构由后续 L2 动作驱动
  if (action?.kind === 'plc_write') {
    return { kind: 'no-motion', reason: '写点动作只下发数值到 PLC, 机构由后续 L2 动作驱动' }
  }

  return {
    kind: 'unsupported',
    reason: `${action?.kind || '未知'} 动作 ${name} 还没有进映射表 —— `
      + '要么补进 clip_compiler 的映射表, 要么用「实机对照」',
  }
}

/**
 * 功能: 给已产出动画的 plan 附上"另外还驱了泵/阀"的注脚.
 *
 * 有些动作既动机构又动流体(如 develop.rinse_fill 关盖 + 开进液阀): 动画照播, 但必须
 * 说明有一半没画出来, 否则用户会以为三维已经把这条动作演全了.
 *
 * liquidShown 分流是必须的: 展缸液面上线后, "三维暂不表现流体"这句话对那几条动作就
 * **半错了** —— 泵体与阀确实没有几何, 但缸里的液面已经按配方体积演出来了. 一句笼统的
 * "不表现流体"会让人以为画面上那段涨落是假的.
 *
 * @param {object} plan 规划结果
 * @param {object|null} map 映射表
 * @param {string} name 动作名
 * @param {boolean} [liquidShown] 本次是否已经出了液面通道
 * @returns {object} plan
 */
function withFluidNote(plan, map, name, liquidShown = false) {
  const fluid = fluidNote(map, name)
  if (!fluid) return plan
  if (plan.kind !== 'pseudo') {
    return {
      kind: 'no-motion',
      reason: `该动作驱动 ${fluid}; 单动作演示暂不表现, `
        + '注射泵柱塞行程请在流程演示或实时页查看',
    }
  }
  const extra = liquidShown
    ? `另外驱动 ${fluid} —— 缸内液面已按配方体积表现, 泵柱塞行程见流程演示/实时页`
    : `另外驱动 ${fluid} —— 单动作演示暂不表现(泵柱塞行程见流程演示/实时页)`
  return { ...plan, note: plan.note ? `${plan.note}; ${extra}` : extra }
}
