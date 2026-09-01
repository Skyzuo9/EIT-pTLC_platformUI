/**
 * 功能: 仿真沙盒会话胶水 (Vue 组合式函数).
 *
 * 职责: 会话生命周期 (创建/销毁/状态轮询)、状态快照拉取、采纳/复位/倍率动词、
 * 消息条。事件流的建立在 SimView 里经 streamFactory 交给 useTwinScene ——
 * 本模块只管 REST 面。
 */
import { onBeforeUnmount, ref } from 'vue'

import { simApi as defaultApi } from './simApi.js'

const STATUS_POLL_MS = 5000

/**
 * 功能: 建会话胶水.
 * @param {object} [options]
 * @param {object} [options.api] 注入 API 替身
 * @returns {object} 响应式状态与动词
 */
export function useSimSession({ api = defaultApi } = {}) {
  const active = ref(false)
  const busy = ref(false)
  const timeScale = ref(1)
  const runs = ref([])
  const message = ref('')
  const simState = ref(null)          // GET /api/sim/state 的最近快照
  let pollTimer = 0

  function report(text) {
    message.value = text
  }

  async function refreshStatus() {
    try {
      const status = await api.sessionStatus()
      active.value = Boolean(status?.active)
      if (status?.active) {
        timeScale.value = Number(status.time_scale) || 1
        runs.value = status.runs?.runs || []
      } else {
        runs.value = []
      }
    } catch (error) {
      report(`沙盒状态读取失败: ${error.message}`)
    }
  }

  async function refreshState() {
    if (!active.value) return
    try {
      simState.value = await api.fetchState()
    } catch (error) {
      report(`状态快照失败: ${error.message}`)
    }
  }

  async function _verb(label, fn, { refresh = true } = {}) {
    busy.value = true
    try {
      const result = await fn()
      report(`${label}完成`)
      if (refresh) {
        await refreshStatus()
        await refreshState()
      }
      return result
    } catch (error) {
      report(`${label}失败: ${error.message}`)
      throw error
    } finally {
      busy.value = false
    }
  }

  const create = (options = {}) => _verb('创建沙盒', () => api.createSession(options))
  const destroy = () => _verb('销毁沙盒', () => api.destroySession())
  const adopt = () => _verb('采纳实时状态', () => api.adoptLive())
  const reset = () => _verb('复位 home', () => api.resetHome())
  const patchState = (patch) => _verb('写状态', () => api.patchState(patch))
  const setRate = (rate) => _verb(`倍率 ${rate}×`, () => api.setTimeScale(rate))

  pollTimer = window.setInterval(refreshStatus, STATUS_POLL_MS)
  void refreshStatus().then(refreshState)

  onBeforeUnmount(() => {
    clearInterval(pollTimer)
  })

  return {
    api,
    active,
    busy,
    timeScale,
    runs,
    message,
    simState,
    refreshStatus,
    refreshState,
    create,
    destroy,
    adopt,
    reset,
    patchState,
    setRate,
  }
}
