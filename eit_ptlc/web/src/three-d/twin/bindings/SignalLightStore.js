export const SIGNAL_LIGHT_STALE_MS = 3000

function stampMs(value, fallback) {
  if (!Number.isFinite(value)) return fallback
  return value < 1e12 ? value * 1000 : value
}

/**
 * 整机三色塔灯的只读状态账本 —— 上位机 signal_light 事件(变化即发 + 1s 心跳)的镜像.
 * 颜色由 PLC 的 MODE_State 状态机在上位机侧推导(原始色位与实体灯脱钩, 2026-08-02
 * 取证, 见 eit_ptlc manual_service._SIGNAL_BY_MODE); flash 表示该态实体灯是闪烁的.
 *
 * 两个语义必须分开: received=false 表示从未收到过帧(脱机演示 / live 首帧前),
 * 绑定层此时保持管线烘焙的静态观感; stale 表示收到过但断流(断线或心跳丢失),
 * 绑定层转灰色未知态. 断流保留末态布尔值, 供 HUD 诊断显示"最后已知灯态".
 */
export class SignalLightStore {
  constructor({ staleMs = SIGNAL_LIGHT_STALE_MS } = {}) {
    this.staleMs = staleMs
    this.frame = null
    this.disconnected = false
  }

  /**
   * 功能: 接收一条 signal_light 事件.
   * @param {object} event 事件对象 {type, red, yellow, green, buzzer?, ts, seq}
   * @param {number} [arrivalMs] 到达时刻(毫秒)
   * @returns {boolean} 是否接受并更新
   */
  push(event, arrivalMs = Date.now()) {
    if (!event || event.type !== 'signal_light') return false
    if (typeof event.red !== 'boolean' || typeof event.yellow !== 'boolean'
      || typeof event.green !== 'boolean') return false

    const ts = stampMs(event.ts, arrivalMs)
    const seq = Number.isFinite(event.seq) ? Number(event.seq) : null
    const current = this.frame
    // 断线重连或长时间断流后, 上位机可能已重启, 允许 ts/seq 回退重置
    const reconnect = this.disconnected
      || (current !== null && arrivalMs - current.arrivalMs > this.staleMs)
    if (current && !reconnect) {
      if (ts < current.ts) return false
      if (seq !== null && current.seq !== null && ts === current.ts && seq <= current.seq) return false
    }

    this.frame = {
      red: event.red,
      yellow: event.yellow,
      green: event.green,
      buzzer: typeof event.buzzer === 'boolean' ? event.buzzer : null,
      // flash: 该态在实体灯上是闪烁的(如故障红闪), 由绑定层做 1Hz 强度调制
      flash: event.flash === true,
      // mode: 上位机 MODE_State 原始码, 供 HUD 诊断显示
      mode: Number.isFinite(event.mode) ? Number(event.mode) : null,
      ts,
      seq,
      arrivalMs,
    }
    this.disconnected = false
    return true
  }

  /** 保留末态, 但 sample 立即报 stale —— 断流转灰不必等心跳超时. */
  markDisconnected() {
    this.disconnected = true
  }

  /**
   * 功能: 采样当前灯态. active 是"红>黄>绿"优先级的唯一实现点.
   * @param {number} [nowMs] 当前时刻(毫秒)
   * @returns {{received: boolean, red: boolean, yellow: boolean, green: boolean,
   *            buzzer: boolean|null, active: 'red'|'yellow'|'green'|'off'|null, stale: boolean}}
   */
  sample(nowMs = Date.now()) {
    const frame = this.frame
    if (!frame) {
      return {
        received: false, red: false, yellow: false, green: false,
        buzzer: null, flash: false, mode: null, active: null, stale: false,
      }
    }
    const stale = this.disconnected || nowMs - frame.arrivalMs > this.staleMs
    const active = frame.red ? 'red' : frame.yellow ? 'yellow' : frame.green ? 'green' : 'off'
    return {
      received: true,
      red: frame.red,
      yellow: frame.yellow,
      green: frame.green,
      buzzer: frame.buzzer,
      flash: frame.flash === true,
      mode: frame.mode ?? null,
      active,
      stale,
    }
  }
}
