/**
 * 功能: 把录像的列式帧还原成与实时**逐字同构**的事件, 供 TwinFeed.handleEvent 消费.
 *
 * 这是整个回放最要紧的一段代码: 它是后端 recording/recorder.py::_flatten 的严格逆
 * 运算。只要这里还原出的事件形状与线上事件一致, 下游 TwinBindings(68.9KB) +
 * MachineStateDriver(76.9KB) + 各 buffer 就原样复用, 一行都不用改 —— 回放与实时因此
 * 天然 1:1, 而不是靠两套代码"尽量画得像"。
 *
 * 时间戳一律保持**绝对纪元秒**, 与线上 JSON 完全一致: 各 store 的 stampMs 把 < 1e12
 * 的值判定为秒并乘 1000, 改成相对时间会被误判并乘出天文数字。
 */

/** 缺帧在列里显式记为 null(与 tri 通道的真实 null 值由 kind 区分, 见后端 codec)。 */
function present(value) {
  return value !== null && value !== undefined
}

/**
 * 功能: 把一个流的列式数据还原成逐帧事件.
 * @param {string} stream 流名
 * @param {object} data {ts: number[], channels: {id: any[]}}
 * @returns {object[]} 与线上同构的事件数组
 */
function streamToEvents(stream, data) {
  const stamps = Array.isArray(data?.ts) ? data.ts : []
  const channels = data?.channels || {}
  const out = []

  for (let i = 0; i < stamps.length; i += 1) {
    const ts = stamps[i]
    if (stream === 'axis_pose') {
      const positions = {}
      const velocities = {}
      for (const [key, column] of Object.entries(channels)) {
        const value = column[i]
        if (!present(value)) continue
        const dot = key.lastIndexOf('.')
        if (dot < 0) continue
        const axis = key.slice(0, dot)
        const field = key.slice(dot + 1)
        if (field === 'position') positions[axis] = value
        else if (field === 'velocity') velocities[axis] = value
      }
      if (Object.keys(positions).length) {
        out.push({ type: 'axis_pose', ts, positions, velocities })
      }
    } else if (stream === 'robot_pose') {
      const joint = []
      const pose = []
      let tool = null
      let mode = null
      for (let k = 0; k < 6; k += 1) {
        const value = channels[`joint${k}`]?.[i]
        joint[k] = present(value) ? value : null
      }
      for (let k = 0; k < 3; k += 1) {
        const xyz = channels[`pose_xyz${k}`]?.[i]
        const rpy = channels[`pose_rpy${k}`]?.[i]
        pose[k] = present(xyz) ? xyz : null
        pose[k + 3] = present(rpy) ? rpy : null
      }
      if (present(channels.tool?.[i])) tool = channels.tool[i]
      if (present(channels.mode?.[i])) mode = channels.mode[i]
      // 关节缺一个都不成立: RobotPoseBuffer.push 要求 6 个全是有限数, 半截帧只会被它
      // 静默丢弃, 不如在这里就不产出, 免得计数对不上让人以为丢帧了。
      if (joint.every((v) => Number.isFinite(v))) {
        const event = { type: 'robot_pose', ts, joint, pose }
        if (tool !== null) event.tool = tool
        if (mode !== null) event.mode = mode
        out.push(event)
      }
    } else if (stream === 'mechanism_state') {
      const states = {}
      for (const [key, column] of Object.entries(channels)) {
        const value = column[i]
        if (value === undefined) continue
        const dot = key.lastIndexOf('.')
        if (dot < 0) continue
        const id = key.slice(0, dot)
        const field = key.slice(dot + 1)
        // 这里**不能**用 present() 过滤: confirmed 的 null 是"两个到位信号都不成立"
        // 这一真实状态, 前端据此回退 commanded+estimated。滤掉它会把运动途中错画成
        // 已到位。缺帧在后端就已经不写进该帧的列里了(见 codec 的 present 位图)。
        if (!states[id]) states[id] = {}
        states[id][field] = value
      }
      if (Object.keys(states).length) out.push({ type: 'mechanism_state', ts, states })
    } else if (stream === 'signal_light') {
      const event = { type: 'signal_light', ts }
      let any = false
      for (const [key, column] of Object.entries(channels)) {
        const value = column[i]
        if (!present(value)) continue
        event[key] = value
        any = true
      }
      if (any) out.push(event)
    }
  }
  return out
}

/**
 * 功能: 把 /api/recording/frames 的返回整体转成按时间排好序的事件流.
 *
 * @param {object} payload frames 端点返回体
 * @returns {object[]} 按 ts 升序的事件数组 (含低频原样事件)
 */
export function framesToEvents(payload) {
  const out = []
  for (const [stream, data] of Object.entries(payload?.streams || {})) {
    out.push(...streamToEvents(stream, data))
  }
  for (const event of payload?.events || []) {
    if (event && typeof event === 'object') out.push(event)
  }
  // 稳定排序: 同一时刻的多条事件保持产出顺序, 否则同 ts 的 enter/done 可能被调换,
  // 导致入参配对表弹错。Array.prototype.sort 在现代 V8 上是稳定的。
  out.sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0))
  return out
}

/**
 * 功能: 把关键帧快照还原成一组"播种事件" + 一份需要直接写入的标量快照.
 *
 * 机构必须整份重放合并后的记录, 而不是最后一条线上事件 —— commanded/confirmed/
 * expectedS 都是刻意粘滞的, 最后那条可能只带了一部分键。
 *
 * @param {object} keyframe 录像块关键帧
 * @param {number} ts 播种时刻(绝对纪元秒)
 * @returns {{events: object[], scalars: object}}
 */
export function keyframeToSeed(keyframe, ts) {
    const events = []
  if (!keyframe || typeof keyframe !== 'object') return { events, scalars: {} }

  const axes = keyframe.axes || {}
  const positions = {}
  const velocities = {}
  for (const [axis, record] of Object.entries(axes)) {
    if (present(record?.position)) positions[axis] = record.position
    if (present(record?.velocity)) velocities[axis] = record.velocity
  }
  if (Object.keys(positions).length) {
    events.push({ type: 'axis_pose', ts, positions, velocities })
  }

  const robot = keyframe.robot || {}
  if (Array.isArray(robot.joint) && robot.joint.length === 6) {
    const event = { type: 'robot_pose', ts, joint: robot.joint, pose: robot.pose || [] }
    if (present(robot.tool)) event.tool = robot.tool
    if (present(robot.mode)) event.mode = robot.mode
    events.push(event)
  }

  const mechanisms = keyframe.mechanisms || {}
  if (Object.keys(mechanisms).length) {
    events.push({ type: 'mechanism_state', ts, states: mechanisms })
  }

  if (keyframe.signalLight && Object.keys(keyframe.signalLight).length) {
    events.push({ type: 'signal_light', ...keyframe.signalLight, ts })
  }

  for (const snapshot of Object.values(keyframe.telemetry || {})) {
    if (snapshot && typeof snapshot === 'object') events.push({ ...snapshot, ts })
  }

  if (keyframe.materialState) {
    // initial:true 是 MaterialStateStore 既有的"绕过时间戳倒退闸门"通路
    events.push({ ...keyframe.materialState, type: 'material_state', ts, initial: true })
  }

  const scalars = {}
  for (const key of ['mountedTool', 'robotMode', 'tankStates', 'railSlots',
                     'processLights', 'gripHolding', 'suctionHeld', 'pumpSpeeds']) {
    if (keyframe[key] !== undefined) scalars[key] = keyframe[key]
  }
  return { events, scalars }
}
