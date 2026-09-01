/**
 * 功能: 仿真沙盒 REST 客户端 (/api/sim/*).
 *
 * 自带 fetch 传输层且可注入替身(离线单测断言 动词→URL/方法 映射, 仿 manualApi 手法);
 * 全部路径集中在本文件 —— 后端契约变更只改一处。
 */

/** 默认传输: fetch + JSON; 非 2xx 抛带 status 的 Error. */
async function fetchJson(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  let data = null
  try {
    data = await response.json()
  } catch {
    /* 空响应体容忍 */
  }
  if (!response.ok) {
    const error = new Error(data?.detail || `HTTP ${response.status}`)
    error.status = response.status
    error.payload = data
    throw error
  }
  return data
}

/**
 * 功能: 构造一套沙盒 API (request 可注入).
 * @param {Function} [request] (path, {method, body}) => Promise<any>
 * @returns {object} 动词表
 */
export function createSimApi(request = fetchJson) {
  return {
    // 会话
    createSession: (options = {}) => request('/api/sim/session', { method: 'POST', body: options }),
    sessionStatus: () => request('/api/sim/session'),
    destroySession: () => request('/api/sim/session', { method: 'DELETE' }),
    // 状态
    fetchState: () => request('/api/sim/state'),
    patchState: (patch) => request('/api/sim/state', { method: 'PUT', body: patch }),
    adoptLive: () => request('/api/sim/adopt', { method: 'POST' }),
    resetHome: () => request('/api/sim/reset', { method: 'POST' }),
    // 只读诊断 (与状态面分家: 那边是可设面的回读, 这边是门为什么不满足)
    diagnostics: () => request('/api/sim/diagnostics'),
    setTimeScale: (rate) => request('/api/sim/time_scale', { method: 'POST', body: { rate } }),
    // 运行
    runAction: (name, params) => request(
      `/api/sim/actions/${encodeURIComponent(name)}/run`,
      { method: 'POST', body: { params } }),
    startRun: (operation, { inputs = {}, overrides = {}, modeRun = 'run', startAid = null } = {}) =>
      request(`/api/sim/scripts/${encodeURIComponent(operation)}/debug/run`, {
        method: 'POST',
        body: { inputs, overrides, mode_run: modeRun, start_aid: startAid },
      }),
    runVerb: (runId, verb) => request(
      `/api/sim/debug/${encodeURIComponent(runId)}/${verb}`, { method: 'POST' }),
    runState: (runId) => request(`/api/sim/debug/${encodeURIComponent(runId)}/state`),
    runVars: (runId) => request(`/api/sim/debug/${encodeURIComponent(runId)}/vars`),
    activeRuns: () => request('/api/sim/debug/active'),
    setBreakpoints: (runId, aids) => request(
      `/api/sim/debug/${encodeURIComponent(runId)}/breakpoints`,
      { method: 'POST', body: { aids } }),
    humanReply: (runId, reqId, { choice = null, values = null } = {}) => request(
      `/api/sim/debug/${encodeURIComponent(runId)}/human/${encodeURIComponent(reqId)}`,
      { method: 'POST', body: { choice, values } }),
  }
}

export const simApi = createSimApi()

/** 沙盒事件流 WS 地址 (与宿主 eventsWsUrl 同构). */
export function simEventsWsUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/api/sim/ws/events`
}
