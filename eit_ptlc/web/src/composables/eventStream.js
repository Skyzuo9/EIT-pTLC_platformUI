// 单 WebSocket 事件流
// =====================
// 全应用共享一条到 /api/ws/events 的连接, 断线自动重连; 事件 (流程 operation_*/step_* +
// 节点 telemetry) 按 type 交由订阅者处理. 取代各视图各自建 WS 的旧做法, 使常驻监视器持续在线.
// 重连指数退避 (1.5s→3→6→12→封顶 15s, ±20% 抖动, 成功即复位): 后端整体重启时全部
// 标签页不再以固定 0.67Hz 齐射; document.hidden 期间挂起重连尝试, 回见沿立即连
// (连接成功沿会触发 App.vue 的补种收口, 断线窗口丢的事件由权威记录重放补齐)。
import { eventsWsUrl } from '../api.js'

const RECONNECT_BASE_MS = 1500
const RECONNECT_MAX_MS = 15000

let ws = null
let reconnectTimer = null
let started = false
let connected = false
let attemptCount = 0 // 连续失败次数 (驱动退避; onopen 复位)
let pendingWhileHidden = false // hidden 期间欠下的重连, 回见沿立即偿还
const handlers = new Set() // (event) => void
const statusHandlers = new Set() // (connected: boolean) => void

function dispatchStatus(next) {
  connected = next
  for (const handler of statusHandlers) {
    try {
      handler(connected)
    } catch (err) {
      console.error('[eventStream] 状态处理器异常', err)
    }
  }
}

function dispatch(event) {
  for (const handler of handlers) {
    try {
      handler(event)
    } catch (err) {
      // 单个处理器异常不应影响其它处理器
      console.error('[eventStream] 处理器异常', err)
    }
  }
}

function connect() {
  ws = new WebSocket(eventsWsUrl())
  ws.onopen = () => {
    attemptCount = 0
    dispatchStatus(true)
  }
  ws.onmessage = (ev) => {
    let event
    try {
      event = JSON.parse(ev.data)
    } catch (err) {
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
      if (ws) ws.close()
    } catch (err) {
      /* 忽略关闭异常, 交由 onclose 走重连 */
    }
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return
  if (document.hidden) {
    // 后台标签页不重试 (省后端); 欠账记下, 回见沿立即连
    pendingWhileHidden = true
    return
  }
  const base = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** attemptCount)
  attemptCount += 1
  const jitter = base * 0.2 * (Math.random() * 2 - 1) // ±20%: 多标签页/多工位不齐射
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, Math.round(base + jitter))
}

function onVisibility() {
  if (document.hidden || !pendingWhileHidden) return
  pendingWhileHidden = false
  connect()
}

// 启动事件流 (幂等; 多次调用只建一条连接).
export function startEventStream() {
  if (started) return
  started = true
  document.addEventListener('visibilitychange', onVisibility)
  connect()
}

// 订阅事件; 返回取消订阅函数
export function onEvent(handler) {
  handlers.add(handler)
  return () => handlers.delete(handler)
}

// 订阅连接状态并立即回放当前值; 返回取消订阅函数.
export function onEventStreamStatus(handler) {
  statusHandlers.add(handler)
  handler(connected)
  return () => statusHandlers.delete(handler)
}
