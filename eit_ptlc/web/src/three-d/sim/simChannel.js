/**
 * 功能: 仿真沙盒的独立 WebSocket 通道 (/api/sim/ws/events).
 *
 * 为什么不用宿主单例 (composables/eventStream.js): 沙盒事件与真机事件**必须物理
 * 隔离** —— 宿主单例扇出给 nodes/runs/debug/alarms 等全局 store, 沙盒的
 * axis_pose/vm_* 一旦混入, DebugDock 与状态条会被仿真数据抢占。
 *
 * 重连纪律照抄宿主单例 (指数退避 1.5s→15s ±20% 抖动、hidden 欠账、onopen 复位),
 * 出处: src/composables/eventStream.js。差异只有两点: 非单例(每次 create 新通道)、
 * 多一个 stop() —— 离开 /3d/sim 必须断沙盒连接, 不能像宿主那样常驻。
 */

const RECONNECT_BASE_MS = 1500
const RECONNECT_MAX_MS = 15000

/**
 * 功能: 建一条可停止的沙盒 WS 通道.
 * @param {object} [options]
 * @param {string} [options.url] WS 地址 (缺省由调用方传 simEventsWsUrl())
 * @param {Function} [options.WebSocketImpl] 注入 WebSocket 替身 (离线单测)
 * @returns {{start: Function, stop: Function, onEvent: Function, onStatus: Function}}
 */
export function createSimChannel({ url, WebSocketImpl = globalThis.WebSocket } = {}) {
  let ws = null
  let reconnectTimer = null
  let stopped = false
  let connected = false
  let attemptCount = 0
  let pendingWhileHidden = false
  const handlers = new Set()
  const statusHandlers = new Set()

  function dispatchStatus(next) {
    connected = next
    for (const handler of statusHandlers) {
      try {
        handler(connected)
      } catch (err) {
        console.error('[simChannel] 状态处理器异常', err)
      }
    }
  }

  function dispatch(event) {
    for (const handler of handlers) {
      try {
        handler(event)
      } catch (err) {
        console.error('[simChannel] 处理器异常', err)
      }
    }
  }

  function connect() {
    if (stopped) return
    ws = new WebSocketImpl(url)
    ws.onopen = () => {
      attemptCount = 0
      dispatchStatus(true)
    }
    ws.onmessage = (ev) => {
      let event
      try {
        event = JSON.parse(ev.data)
      } catch {
        return
      }
      dispatch(event)
    }
    ws.onclose = () => {
      dispatchStatus(false)
      scheduleReconnect()
    }
    ws.onerror = () => {
      try {
        ws?.close()
      } catch {
        /* 交由 onclose 走重连 */
      }
    }
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return
    if (typeof document !== 'undefined' && document.hidden) {
      pendingWhileHidden = true
      return
    }
    const base = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attemptCount)
    attemptCount += 1
    const jitter = base * 0.2 * (Math.random() * 2 - 1)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, Math.round(base + jitter))
  }

  function onVisibility() {
    if (stopped || document.hidden || !pendingWhileHidden) return
    pendingWhileHidden = false
    connect()
  }

  return {
    start() {
      if (ws || stopped) return
      if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibility)
      }
      connect()
    },
    stop() {
      stopped = true
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibility)
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      try {
        ws?.close()
      } catch {
        /* 已断无妨 */
      }
      ws = null
      dispatchStatus(false)
    },
    onEvent(handler) {
      handlers.add(handler)
      return () => handlers.delete(handler)
    },
    onStatus(handler) {
      statusHandlers.add(handler)
      handler(connected)
      return () => statusHandlers.delete(handler)
    },
  }
}
