/**
 * 功能: 状态编辑器的行构造与补丁构造 (纯函数, node 可测).
 *
 * 全部由 manifest 驱动 (轴数/行程/关节限位/机构清单都不硬编码);
 * 补丁构造器负责 clamp —— 后端还有一道裁决, 前端 clamp 只是让滑杆不越界。
 */

/**
 * 功能: 轴编辑行 (manifest.axes ⨝ 沙盒状态).
 * @param {object} manifest device-manifest
 * @param {object} simAxes GET /api/sim/state 的 axes ({id:{mm,label}})
 * @returns {object[]} [{id, label, mm, min, max}]
 */
export function axisRows(manifest, simAxes) {
  const rows = []
  for (const axis of manifest?.axes || []) {
    const range = Array.isArray(axis.rangeMm) ? axis.rangeMm : [0, 0]
    const entry = simAxes?.[axis.id] || {}
    rows.push({
      id: axis.id,
      label: axis.label || entry.label || axis.id,
      mm: Number.isFinite(entry.mm) ? entry.mm : null,
      min: Number(range[0]) || 0,
      max: Number(range[1]) || 0,
    })
  }
  return rows
}

/**
 * 功能: 关节编辑行 (manifest.robot.joints).
 * @param {object} manifest device-manifest
 * @param {number[]} joint 当前六关节角
 * @returns {object[]} [{index, label, deg, min, max}]
 */
export function jointRows(manifest, joint) {
  const rows = []
  const joints = manifest?.robot?.joints || []
  for (let i = 0; i < joints.length; i += 1) {
    const limit = Array.isArray(joints[i]?.limitDeg) ? joints[i].limitDeg : [-360, 360]
    rows.push({
      index: i,
      label: joints[i]?.label || `J${i + 1}`,
      deg: Number.isFinite(joint?.[i]) ? joint[i] : 0,
      min: Number(limit[0]),
      max: Number(limit[1]),
    })
  }
  return rows
}

/**
 * 功能: 执行器 (气缸/联动) 编辑行, 按工位分组.
 * @param {object} manifest device-manifest
 * @param {object} mechanisms 沙盒 manual 快照的 mechanisms ({id:{commanded,confirmed}})
 * @returns {object[]} [{station, items: [{id, label, on}]}]
 */
export function mechanismGroups(manifest, mechanisms) {
  const groups = new Map()
  for (const spec of manifest?.realtime?.mechanisms || []) {
    // 只列会出现在单点快照里的执行器 (气缸类); 无反馈的数据机构不进编辑器
    const entry = mechanisms?.[spec.id]
    if (entry === undefined) continue
    const station = spec.station || '其它'
    if (!groups.has(station)) groups.set(station, [])
    const confirmed = entry?.confirmed
    groups.get(station).push({
      id: spec.id,
      label: spec.label || spec.id,
      on: confirmed !== null && confirmed !== undefined
        ? Boolean(confirmed)
        : Boolean(entry?.commanded),
    })
  }
  return [...groups.entries()].map(([station, items]) => ({ station, items }))
}

/**
 * 功能: 机器人末端执行器 (吸盘/夹爪/翻转) 编辑行.
 *
 * 行来自**后端发布的能力面** `simState.robot.effectors` —— 那是"当前这把刀能点哪几个"
 * 的权威答案, 与"写得动哪些"逐字同源。刀↔机构的映射刻意不在前端复抄: manifest 的
 * controllerTool 只声明了三把刀的夹爪与吸盘, 翻转气缸没有, 照它出行会漏。
 *
 * 取值来自 `simState.mechanisms`, 与气缸同一准则 (confirmed 优先, 缺则 commanded)。
 * 没被命令过的末端 (如刚建栈的 rob_suction) 后端刻意不发布显示态 —— 那不是"关着",
 * 是"还不知道", 于是 on 给 null 由界面标"未命令", 绝不画成确认态。
 * @param {object} manifest device-manifest (只用来取显示名)
 * @param {object} robot GET /api/sim/state 的 robot 段 ({tool, effectors})
 * @param {object} mechanisms 同一份状态的 mechanisms 段
 * @returns {object[]} [{id, label, on, source, known}]
 */
export function effectorRows(manifest, robot, mechanisms) {
  const labels = new Map()
  for (const spec of manifest?.realtime?.mechanisms || []) {
    labels.set(spec.id, spec.label || spec.id)
  }
  const rows = []
  for (const id of robot?.effectors || []) {
    const entry = mechanisms?.[id]
    const confirmed = entry?.confirmed
    const commanded = entry?.commanded
    let on = null
    let source = ''
    if (confirmed !== null && confirmed !== undefined) {
      on = Boolean(confirmed)
      source = 'feedback'
    } else if (commanded !== null && commanded !== undefined) {
      on = Boolean(commanded)
      source = 'commanded'
    }
    rows.push({ id, label: labels.get(id) || id, on, source, known: on !== null })
  }
  return rows
}

/** TCP 位姿的六个分量 (Dobot 口径: 前三位 mm, 后三位固定 XYZ 欧拉角 deg). */
export const POSE_AXES = Object.freeze([
  { key: 'x', label: 'X', unit: 'mm' },
  { key: 'y', label: 'Y', unit: 'mm' },
  { key: 'z', label: 'Z', unit: 'mm' },
  { key: 'rx', label: 'RX', unit: '°' },
  { key: 'ry', label: 'RY', unit: '°' },
  { key: 'rz', label: 'RZ', unit: '°' },
])

/**
 * 功能: TCP 位姿**只读**行.
 *
 * 位姿一直被采纳进沙盒 (adopt 的 robot.pose), 但此前面板一行都不显示, 观感上就成了
 * "没采"。这里补上显示。
 *
 * **刻意不给输入框**: robot_sim.set_state 直写 pose 与 joint 两者且不做逆解, 在这里
 * 开第二个写入口会造出"改了 pose 而 joint 没跟着"的姿态 —— 三维照 joint 画、面板照
 * pose 显示, 两边说的不是同一件事。关节角滑杆是姿态的唯一写口。
 *
 * @param {number[]} pose GET /api/sim/state 的 robot.pose
 * @returns {object[]} [{key, label, unit, value}]; 位姿缺失或不足六位时返回空数组
 */
export function poseRows(pose) {
  if (!Array.isArray(pose) || pose.length < POSE_AXES.length) return []
  return POSE_AXES.map((axis, index) => ({
    ...axis,
    value: Number.isFinite(pose[index]) ? Number(pose[index]) : null,
  }))
}

/** 注射泵满程 mL (6000 步 ÷ 240 步每 mL, 与 mock/behavior/pump 同源常量). */
export const PUMP_STROKE_ML = 25

/**
 * 功能: 注射泵相位行 (柱塞 mL / 阀口).
 *
 * 泵此前只在读面出现、没有写口。"泵吸了一半停电重开"是个真实初态, 沙盒要能表达它。
 * 行直接来自沙盒读面 `simState.pumps` 而不是 manifest —— 泵的存在与否由沙盒说了算
 * (真机有几台就有几台), manifest 只管三维几何。
 *
 * busy 时**行被禁用**: 指令串跑到一半直写状态会与积分器打架, 后端也会拒。
 *
 * @param {object} pumps GET /api/sim/state 的 pumps ({id:{plunger_ml,valve_port,busy}})
 * @returns {object[]} [{id, plungerMl, valvePort, busy}]
 */
export function pumpRows(pumps) {
  return Object.keys(pumps || {}).sort().map((id) => {
    const entry = pumps[id] || {}
    return {
      id,
      plungerMl: Number.isFinite(entry.plunger_ml) ? entry.plunger_ml : 0,
      valvePort: Number.isFinite(entry.valve_port) ? entry.valve_port : null,
      busy: Boolean(entry.busy),
    }
  })
}

/** 功能: 泵相位补丁 (柱塞夹逼到 0~25mL 满程; 阀口下限 1). */
export function buildPumpPatch(id, field, raw) {
  const value = Number(raw)
  if (field === 'valve_port') {
    return { pumps: { [id]: { valve_port: Math.max(1, Math.round(value) || 1) } } }
  }
  return { pumps: { [id]: { plunger_ml: clamp(value || 0, 0, PUMP_STROKE_ML) } } }
}

/** 功能: 末端执行器补丁 (与气缸分开: 那条落 PLC 气缸自动位, 这条发 tool_action). */
export function buildEffectorPatch(id, on) {
  return { robot: { effectors: { [id]: Boolean(on) } } }
}

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

/** 功能: 单轴补丁 (clamp 到 rangeMm). */
export function buildAxisPatch(row, mm) {
  return { axes: { [row.id]: clamp(Number(mm), row.min, row.max) } }
}

/** 功能: 六关节补丁 (逐关节 clamp 到 limitDeg). */
export function buildJointPatch(rows, degrees) {
  const joint = rows.map((row, i) => clamp(Number(degrees[i] ?? row.deg), row.min, row.max))
  return { robot: { joint } }
}

/** 功能: 工具补丁. */
export function buildToolPatch(tool) {
  return { robot: { tool: Number(tool) || 0 } }
}

/** 功能: 执行器开合补丁. */
export function buildMechanismPatch(id, on) {
  return { mechanisms: { [id]: Boolean(on) } }
}
