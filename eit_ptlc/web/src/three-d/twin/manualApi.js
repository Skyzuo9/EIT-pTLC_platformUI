/**
 * 功能: 上位机手动模式(/api/manual/*)的浏览器侧封装 —— REST 包装 + 会话/点动状态机.
 *
 * 后端契约(api/manual_routes.py, 不发明新安全机制, 前端只做提前置灰与心跳冗余):
 *   会话   enter(403=非 DEBUG, 409=前置不满足) → keepalive(停发 3.5s 后端优雅退出,
 *          PLC 3s 看门狗兜底) → exit(不限模式: 收敛动作永远放行)
 *   点动   jog/start {direction: pos|neg} → 按住期间续订 jog/keep(后端窗口 0.8s)
 *          → jog/stop(不限模式)
 *   定位   move {mode: abs|rel, target, vel?}(vel 后端按点表 vel_max 限幅)
 *   收敛   axis stop/reset 不限模式; home/home_all/machine stop·resume 须 DEBUG,
 *          后三者须 {confirm: true}
 *
 * ManualSession 把「enter→心跳→异常→退出」「jog start→keep→stop」做成显式状态机,
 * 计时器与请求函数可注入 —— node --test 用 fake timer 锁 "keep 断供必停" 的安全语义.
 */

import { requestJson } from '../../api.js'

/**
 * 功能: 发起一次 JSON 请求(与 twin/api.js 同口径, 独立出来便于注入替身).
 * @param {string} path 接口路径
 * @param {object|null} [body] 请求体; null 发 POST 空体, undefined 发 GET
 * @returns {Promise<any>} 响应体
 */
export async function manualRequest(path, body) {
  return requestJson(path, body)
}

/** 点表回显(面板结构数据源) */
export const fetchManualPoints = (station) =>
  manualRequest(`/api/manual/points${station ? `?station=${encodeURIComponent(station)}` : ''}`)
/** 气缸二态 */
export const setCylinder = (id, on) =>
  manualRequest(`/api/manual/cylinder/${encodeURIComponent(id)}`, { on: Boolean(on) })
/** 定位(vel 由后端按点表限幅) */
export const moveAxis = (id, { mode = 'abs', target, vel = null }) =>
  manualRequest(`/api/manual/axis/${encodeURIComponent(id)}/move`, { mode, target, vel })
/** 单轴停止(不限模式) */
export const stopAxis = (id) => manualRequest(`/api/manual/axis/${encodeURIComponent(id)}/stop`, {})
/** 单轴清错(不限模式) */
export const resetAxis = (id) => manualRequest(`/api/manual/axis/${encodeURIComponent(id)}/reset`, {})
/** 单轴回零 */
export const homeAxis = (id) => manualRequest(`/api/manual/axis/${encodeURIComponent(id)}/home`, {})
/** 一键回原点(二次确认后调用) */
export const homeAll = () => manualRequest('/api/manual/home_all', { confirm: true })
/** 停机/恢复(二次确认后调用) */
export const machineStop = () => manualRequest('/api/manual/machine/stop', { confirm: true })
export const machineResume = () => manualRequest('/api/manual/machine/resume', { confirm: true })

/** 会话心跳周期: 后端 3.5s 优雅退出 → 1s 给 3 次冗余 */
const KEEPALIVE_MS = 1000
/** 点动续订周期: 后端窗口 0.8s → 250ms 给 3 次冗余 */
const JOG_KEEP_MS = 250

export class ManualSession {
  /**
   * 功能: 建立会话状态机(不发请求; enter() 才动网络).
   * @param {object} [options] 注入项(测试用)
   * @param {Function} [options.request] 请求函数(默认 manualRequest)
   * @param {Function} [options.setIntervalFn] 计时器
   * @param {Function} [options.clearIntervalFn] 计时器
   * @param {(state: object) => void} [options.onChange] 状态回调
   */
  constructor({ request = manualRequest, setIntervalFn, clearIntervalFn, onChange } = {}) {
    this.request = request
    this._setInterval = setIntervalFn || ((fn, ms) => setInterval(fn, ms))
    this._clearInterval = clearIntervalFn || ((id) => clearInterval(id))
    this.onChange = onChange

    /** @type {'idle'|'entering'|'active'|'lost'} 会话态 */
    this.state = 'idle'
    /** 会话失效原因(lost 态) */
    this.reason = ''
    /** @type {{axisId: string, direction: string}|null} 进行中的点动 */
    this.jogging = null
    this._keepTimer = null
    this._jogTimer = null
    /** 心跳在飞标记: 上一拍还没回来就不再叠发 */
    this._keepInFlight = false
  }

  _emit() {
    this.onChange?.({ state: this.state, reason: this.reason, jogging: this.jogging })
  }

  /**
   * 功能: 进入单点模式并启动心跳.
   * @returns {Promise<boolean>} 是否成功
   */
  async enter() {
    if (this.state === 'active' || this.state === 'entering') return this.state === 'active'
    this.state = 'entering'
    this.reason = ''
    this._emit()
    try {
      await this.request('/api/manual/session/enter', {})
      this.state = 'active'
      this._keepTimer = this._setInterval(() => this._keepaliveTick(), KEEPALIVE_MS)
      this._emit()
      return true
    } catch (err) {
      this.state = 'idle'
      this.reason = err.message
      this._emit()
      return false
    }
  }

  async _keepaliveTick() {
    if (this.state !== 'active' || this._keepInFlight) return
    this._keepInFlight = true
    try {
      await this.request('/api/manual/session/keepalive', {})
    } catch (err) {
      // 心跳失败 = 会话不可信: 立即停 jog 并标记失联(后端看门狗同向兜底)
      await this._stopJogInternal(true)
      this._teardownTimers()
      this.state = 'lost'
      this.reason = `心跳失败: ${err.message}`
      this._emit()
    } finally {
      this._keepInFlight = false
    }
  }

  /**
   * 功能: 按住点动开始(pointerdown).
   * @param {string} axisId 轴 id
   * @param {'pos'|'neg'} direction 方向
   * @returns {Promise<boolean>} 是否成功
   */
  async jogStart(axisId, direction) {
    if (this.state !== 'active' || this.jogging) return false
    try {
      await this.request(`/api/manual/axis/${encodeURIComponent(axisId)}/jog/start`, { direction })
      this.jogging = { axisId, direction }
      this._jogTimer = this._setInterval(() => this._jogKeepTick(), JOG_KEEP_MS)
      this._emit()
      return true
    } catch (err) {
      this.reason = `点动失败: ${err.message}`
      this._emit()
      return false
    }
  }

  async _jogKeepTick() {
    const jog = this.jogging
    if (!jog) return
    try {
      await this.request(`/api/manual/axis/${encodeURIComponent(jog.axisId)}/jog/keep`, {})
    } catch (err) {
      // 续订失败 = 窗口不可信: 立即 stop + 报警(后端 0.8s 窗口自动松开是兜底)
      this.reason = `点动续订失败, 已停止: ${err.message}`
      await this._stopJogInternal(true)
      this._emit()
    }
  }

  /**
   * 功能: 松开点动(pointerup/cancel/blur 任一).
   * @returns {Promise<void>} 完成
   */
  async jogStop() {
    await this._stopJogInternal(false)
    this._emit()
  }

  async _stopJogInternal(silent) {
    const jog = this.jogging
    this.jogging = null
    if (this._jogTimer !== null) {
      this._clearInterval(this._jogTimer)
      this._jogTimer = null
    }
    if (!jog) return
    try {
      await this.request(`/api/manual/axis/${encodeURIComponent(jog.axisId)}/jog/stop`, {})
    } catch (err) {
      if (!silent) this.reason = `停止指令失败(后端 0.8s 窗口会自动松开): ${err.message}`
    }
  }

  _teardownTimers() {
    if (this._keepTimer !== null) {
      this._clearInterval(this._keepTimer)
      this._keepTimer = null
    }
    if (this._jogTimer !== null) {
      this._clearInterval(this._jogTimer)
      this._jogTimer = null
    }
  }

  /**
   * 功能: 退出会话(卸载/路由离开/页签隐藏都要调; 幂等).
   * @returns {Promise<void>} 完成
   */
  async exit() {
    await this._stopJogInternal(true)
    this._teardownTimers()
    const wasActive = this.state === 'active' || this.state === 'entering'
    this.state = 'idle'
    this.jogging = null
    this._emit()
    if (wasActive) {
      try {
        await this.request('/api/manual/session/exit', {})
      } catch {
        // 退出失败不致命: 后端 3.5s 看门狗会优雅清扫
      }
    }
  }
}
