import { unwrapAngleDeg } from '../../anim/RobotJointDriver.js'

export const ROBOT_RENDER_DELAY_MS = 100
export const ROBOT_STALE_MS = 500

function stampMs(value, fallback) {
  if (!Number.isFinite(value)) return fallback
  return value < 1e12 ? value * 1000 : value
}

function interpolateJoint(a, b, fraction) {
  return a.map((value, index) => value + (b[index] - value) * fraction)
}

/** 机器人反馈的短时间缓冲；乱序可重排、跨周可展开、断流只冻结不回零。 */
export class RobotPoseBuffer {
  constructor({ delayMs = ROBOT_RENDER_DELAY_MS, staleMs = ROBOT_STALE_MS } = {}) {
    this.delayMs = delayMs
    this.staleMs = staleMs
    this.frames = []
    this.lastSequence = -1
    this.lastHighRateArrival = 0
    this.lastArrival = 0
    this.lastResyncArrival = 0
    this.forceResync = false
  }

  /**
   * 彻底复位: 清轨迹**并清到达时刻锁存**。向后 seek 的唯一正确入口。
   *
   * lastArrival / lastHighRateArrival 都是 Math.max 单调累加, markDisconnected()
   * 清不掉。回放向后跳后 nowMs 变小, stale 恒为 false, 且 1Hz telemetry 回退被永久
   * 压制 —— 两者都不报错, 只是画面不再说实话。lastSequence 一并复位, 否则重连语义
   * 下的 seq 去重会误杀回放帧。
   */
  reset() {
    this.frames.length = 0
    this.lastSequence = -1
    this.lastHighRateArrival = 0
    this.lastArrival = 0
    this.lastResyncArrival = 0
    this.forceResync = false
  }

  push(event, arrivalMs = Date.now()) {
    if (!Array.isArray(event?.joint) || event.joint.length !== 6 || !event.joint.every(Number.isFinite)) return false
    const ts = stampMs(event.ts, arrivalMs)
    const seq = Number.isFinite(event.seq) ? Number(event.seq) : null

    // 断流后第一帧是新的真实基准。旧帧必须清掉，否则 100ms 缓冲会在旧/新位姿间
    // 生成一段并不存在的补间轨迹，机械臂可能穿过设备。
    if (this.forceResync || (this.lastArrival && arrivalMs - this.lastArrival > this.staleMs)) {
      this.frames.length = 0
      this.lastResyncArrival = arrivalMs
      this.lastSequence = -1
      this.forceResync = false
    }
    if (seq !== null && this.frames.some((frame) => frame.seq === seq)) return false

    const frame = {
      ts,
      seq,
      rawJoint: [...event.joint],
      joint: [...event.joint],
      pose: Array.isArray(event.pose) ? [...event.pose] : null,
      tool: event.tool,
      mode: event.mode,
      arrivalMs,
      highRate: event.type === 'robot_pose',
    }
    this.frames.push(frame)
    this.frames.sort((a, b) => a.ts - b.ts || (a.seq ?? 0) - (b.seq ?? 0))
    // 乱序插帧后从时间最早帧重新展开全部关节，避免后到的中间帧造成 ±360° 分支不一致。
    for (let frameIndex = 1; frameIndex < this.frames.length; frameIndex += 1) {
      const prior = this.frames[frameIndex - 1]
      const current = this.frames[frameIndex]
      current.joint = current.rawJoint.map((value, index) => unwrapAngleDeg(value, prior.joint[index]))
    }
    if (this.frames.length > 64) this.frames.splice(0, this.frames.length - 64)
    if (seq !== null) this.lastSequence = Math.max(this.lastSequence, seq)
    if (frame.highRate) this.lastHighRateArrival = arrivalMs
    this.lastArrival = Math.max(this.lastArrival, arrivalMs)
    return true
  }

  /** 连接断开时保留末帧冻结；下一条有效帧不与旧位姿做插值。 */
  markDisconnected() {
    if (this.frames.length) this.forceResync = true
  }

  pushTelemetry(data, ts, arrivalMs = Date.now()) {
    // 高频流健康时忽略 1 Hz 回退，避免旧遥测把连续轨迹拉回去。
    if (arrivalMs - this.lastHighRateArrival <= this.staleMs) return false
    return this.push({ type: 'telemetry', joint: data?.joint, tool: data?.tool_state?.mounted_tool, ts }, arrivalMs)
  }

  sample(nowMs = Date.now()) {
    if (!this.frames.length) {
      return { joint: null, pose: null, tool: null, mode: null, stale: true, resynced: false, ts: null }
    }
    const stale = nowMs - this.lastArrival > this.staleMs
    const renderTs = nowMs - this.delayMs

    let before = this.frames[0]
    let after = null
    for (const frame of this.frames) {
      if (frame.ts <= renderTs) before = frame
      if (frame.ts >= renderTs) {
        after = frame
        break
      }
    }
    if (!after || after === before || after.ts <= before.ts) {
      return {
        joint: [...before.joint],
        pose: before.pose ? [...before.pose] : null,
        tool: before.tool,
        mode: before.mode,
        stale,
        resynced: Boolean(this.lastResyncArrival && nowMs - this.lastResyncArrival <= this.staleMs),
        ts: before.ts,
      }
    }
    const fraction = Math.min(1, Math.max(0, (renderTs - before.ts) / (after.ts - before.ts)))
    return {
      joint: interpolateJoint(before.joint, after.joint, fraction),
      pose: fraction < 0.5 ? before.pose : after.pose,
      tool: fraction < 0.5 ? before.tool : after.tool,
      mode: fraction < 0.5 ? before.mode : after.mode,
      stale,
      resynced: Boolean(this.lastResyncArrival && nowMs - this.lastResyncArrival <= this.staleMs),
      ts: renderTs,
    }
  }
}
