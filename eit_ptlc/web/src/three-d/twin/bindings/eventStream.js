/**
 * 功能: 三维孪生到宿主单例事件流的多订阅者适配层.
 *
 * 本类不创建或关闭 WebSocket. 挂载及每次重连时拉取节点和物料快照播种,
 * 随后只消费宿主 `/api/ws/events` 增量; dispose 仅取消本页订阅.
 */

import { api } from '../../../api.js'
import {
  onEvent as onHostEvent,
  onEventStreamStatus,
} from '../../../composables/eventStream.js'

export class EventStream {
  /**
   * 功能: 订阅事件流并初始化三维页面状态.
   * @param {object} [options] 可选项; autoconnect=false 仅供离线单测使用
   * @param {object} [options.transport] 事件传输源 {onEvent(fn)→off, onStatus(fn)→off};
   *   缺省 = 宿主单例 /api/ws/events。仿真页传独立通道(simChannel)以隔离沙盒事件 ——
   *   沙盒的 axis_pose/vm_* 绝不能进宿主单例, 否则 DebugDock/物料页会被仿真数据污染。
   * @param {Function} [options.seeder] 连接沿播种器 async ({dispatch, reportError}) => void;
   *   缺省 = listNodes→telemetry + getMaterials→material_state 两路宿主快照。
   */
  constructor(options = {}) {
    this.listeners = new Set()
    this.statusListeners = new Set()
    this.closed = false
    this.status = {
      connected: false,
      reconnecting: false,
      generation: 0,
      lastError: '',
      lastMessageAt: 0,
    }
    this._offEvent = null
    this._offStatus = null
    this._transport = options.transport
      || { onEvent: onHostEvent, onStatus: onEventStreamStatus }
    this._seeder = options.seeder || null

    if (options.autoconnect !== false) {
      this._offEvent = this._transport.onEvent((event) => this._handleEvent(event))
      this._offStatus = this._transport.onStatus((connected) => this._handleStatus(connected))
    }
  }

  /** 订阅三维事件. */
  onEvent(handler) {
    this.listeners.add(handler)
    return () => this.listeners.delete(handler)
  }

  /** 订阅连接态并立即回放. */
  onStatus(handler) {
    this.statusListeners.add(handler)
    handler(this.status)
    return () => this.statusListeners.delete(handler)
  }

  /** 合并并广播连接状态. */
  _setStatus(patch) {
    this.status = { ...this.status, ...patch }
    for (const handler of this.statusListeners) handler(this.status)
  }

  /** 在宿主连接沿更新状态并播种快照. */
  _handleStatus(connected) {
    if (this.closed) return
    const wasConnected = this.status.connected
    this._setStatus({
      connected,
      reconnecting: connected === false,
      generation: connected === true && wasConnected === false
        ? this.status.generation + 1
        : this.status.generation,
      lastError: connected === true ? '' : this.status.lastError,
    })
    if (connected === true && wasConnected === false) {
      if (this._seeder) {
        void Promise.resolve(this._seeder({
          dispatch: (event) => this._dispatch(event),
          reportError: (message) => this._setStatus({ lastError: message }),
        })).catch((error) => {
          this._setStatus({ lastError: `播种失败: ${error?.message || error}` })
        })
      } else {
        void Promise.all([this.seed(), this.seedMaterials()])
      }
    }
  }

  /** 把宿主节点快照转成 telemetry 事件. */
  async seed() {
    try {
      const nodes = await api.listNodes()
      if (this.closed) return false
      for (const node of nodes || []) {
        this._dispatch({
          type: 'telemetry',
          node: node.id,
          health: node.health,
          data: node.data,
          ts: node.ts,
          seeded: true,
        })
      }
      return true
    } catch (error) {
      this._setStatus({ lastError: `节点快照播种失败: ${error.message}` })
      return false
    }
  }

  /** 把宿主物料账本快照转成 material_state 事件. */
  async seedMaterials() {
    try {
      const snapshot = await api.getMaterials()
      if (this.closed) return false
      this._dispatch({
        ...(snapshot || {}),
        type: 'material_state',
        initial: true,
        source: 'host_snapshot',
        ts: Date.now() / 1000,
      })
      return true
    } catch (error) {
      this._setStatus({ lastError: `物料快照播种失败: ${error.message}` })
      return false
    }
  }

  /** 消费宿主增量事件. */
  _handleEvent(event) {
    if (this.closed) return
    this._setStatus({ lastMessageAt: Date.now() })
    this._dispatch(event)
  }

  /** 分发一个事件, 单个处理器异常不会阻断其它订阅者. */
  _dispatch(event) {
    for (const handler of this.listeners) {
      try {
        handler(event)
      } catch (error) {
        console.error('[3D] 事件处理出错', error, event)
      }
    }
  }

  /** 取消三维页面订阅, 不关闭宿主全局连接. */
  dispose() {
    this.closed = true
    this._offEvent?.()
    this._offStatus?.()
    this._offEvent = null
    this._offStatus = null
    this.listeners.clear()
    this.statusListeners.clear()
  }
}
