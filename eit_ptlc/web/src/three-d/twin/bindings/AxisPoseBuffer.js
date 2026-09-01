export const AXIS_RENDER_DELAY_MS = 100
export const AXIS_STALE_MS = 500

function stampMs(value, fallback) {
  if (!Number.isFinite(value)) return fallback
  return value < 1e12 ? value * 1000 : value
}

function finiteRecord(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key, item]) => key && Number.isFinite(Number(item)))
      .map(([key, item]) => [key, Number(item)]),
  )
}

/**
 * 11 根 PLC 轴的时间缓冲。高频 axis_pose 与 1 Hz telemetry 共用此入口；每根轴
 * 独立插值、独立判 stale。断流后收到的新帧会清掉旧轨迹并直接恢复真实位置，避免
 * 浏览器沿一条并不存在的补间路径穿模。
 */
export class AxisPoseBuffer {
  constructor({ delayMs = AXIS_RENDER_DELAY_MS, staleMs = AXIS_STALE_MS } = {}) {
    this.delayMs = delayMs
    this.staleMs = staleMs
    this.frames = []
    this.lastHighRateByAxis = new Map()
    this.lastArrivalByAxis = new Map()
    this.resyncedAtByAxis = new Map()
    this.forceResync = false
  }

  push(event, arrivalMs = Date.now()) {
    const positions = finiteRecord(event?.positions)
    if (!Object.keys(positions).length) return false
    const velocities = finiteRecord(event?.velocities)
    const ts = stampMs(event.ts, arrivalMs)
    const seq = Number.isFinite(event.seq) ? Number(event.seq) : null

    const highRate = event.type === 'axis_pose'
    const explicitResync = this.forceResync
    const resetAxes = new Set()
    for (const axisId of Object.keys(positions)) {
      const lastArrival = this.lastArrivalByAxis.get(axisId) || 0
      if (explicitResync || (lastArrival && arrivalMs - lastArrival > this.staleMs)) {
        resetAxes.add(axisId)
      }
    }

    if (!explicitResync && !resetAxes.size && seq !== null
      && this.frames.some((frame) => frame.seq === seq && frame.highRate)) return false

    if (explicitResync) {
      this.frames.length = 0
      this.forceResync = false
    } else if (resetAxes.size) {
      for (const frame of this.frames) {
        for (const axisId of resetAxes) {
          delete frame.positions[axisId]
          delete frame.velocities[axisId]
        }
      }
      this.frames = this.frames.filter((frame) => Object.keys(frame.positions).length)
    }

    // 只有通过校验并真正入缓冲的帧才能刷新新鲜度；重复 seq 不能把断流伪装成 live。
    for (const axisId of Object.keys(positions)) {
      const lastArrival = this.lastArrivalByAxis.get(axisId) || 0
      this.lastArrivalByAxis.set(axisId, Math.max(lastArrival, arrivalMs))
      if (highRate) this.lastHighRateByAxis.set(axisId, arrivalMs)
      if (resetAxes.has(axisId)) this.resyncedAtByAxis.set(axisId, arrivalMs)
    }

    this.frames.push({ ts, seq, positions, velocities, arrivalMs, highRate })
    this.frames.sort((a, b) => a.ts - b.ts || (a.seq ?? 0) - (b.seq ?? 0))
    if (this.frames.length > 128) this.frames.splice(0, this.frames.length - 128)
    return true
  }

  /** 连接断开时保留末帧冻结；下一条有效帧清空旧轨迹并直达真实位置。 */
  /**
   * 彻底复位: 清轨迹**并清到达时刻锁存**。向后 seek 的唯一正确入口。
   *
   * markDisconnected() 只置 forceResync、清不掉 lastArrivalByAxis —— 而后者是
   * Math.max 单调累加的。回放向后跳之后 nowMs 变小, nowMs - lastArrival 变成负数,
   * 于是 stale 永远判 false、`arrivalMs - lastHighRate <= staleMs` 也恒成立把 1Hz
   * telemetry 回退通道永久压制。两个症状都不报错, 只是画面从此不再说实话。
   */
  reset() {
    this.frames.length = 0
    this.lastHighRateByAxis.clear()
    this.lastArrivalByAxis.clear()
    this.resyncedAtByAxis.clear()
    this.forceResync = false
  }

  markDisconnected() {
    if (this.frames.length) this.forceResync = true
  }

  pushTelemetry(positions, ts, arrivalMs = Date.now()) {
    const fallback = finiteRecord(positions)
    for (const axisId of Object.keys(fallback)) {
      const lastHighRate = this.lastHighRateByAxis.get(axisId) || 0
      if (arrivalMs - lastHighRate <= this.staleMs) delete fallback[axisId]
    }
    if (!Object.keys(fallback).length) return false
    return this.push({ type: 'telemetry', positions: fallback, ts }, arrivalMs)
  }

  sample(nowMs = Date.now()) {
    const renderTs = nowMs - this.delayMs
    const axisIds = new Set()
    for (const frame of this.frames) {
      for (const axisId of Object.keys(frame.positions)) axisIds.add(axisId)
    }

    const positions = {}
    const velocities = {}
    const stale = {}
    const resynced = []
    for (const axisId of axisIds) {
      const samples = this.frames.filter((frame) => axisId in frame.positions)
      if (!samples.length) continue
      let before = samples[0]
      let after = null
      for (const frame of samples) {
        if (frame.ts <= renderTs) before = frame
        if (frame.ts >= renderTs) {
          after = frame
          break
        }
      }

      let value = before.positions[axisId]
      let velocity = before.velocities[axisId]
      if (after && after !== before && after.ts > before.ts) {
        const fraction = Math.min(1, Math.max(0, (renderTs - before.ts) / (after.ts - before.ts)))
        value += (after.positions[axisId] - value) * fraction
        if (Number.isFinite(after.velocities[axisId]) && Number.isFinite(velocity)) {
          velocity += (after.velocities[axisId] - velocity) * fraction
        } else if (Number.isFinite(after.velocities[axisId])) {
          velocity = after.velocities[axisId]
        }
      }
      positions[axisId] = value
      if (Number.isFinite(velocity)) velocities[axisId] = velocity
      stale[axisId] = nowMs - (this.lastArrivalByAxis.get(axisId) || 0) > this.staleMs
      const resyncedAt = this.resyncedAtByAxis.get(axisId) || 0
      if (resyncedAt && nowMs - resyncedAt <= this.staleMs) resynced.push(axisId)
    }
    return { positions, velocities, stale, resynced, ts: renderTs }
  }
}
