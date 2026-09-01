// 全局系统状态: 控制模式 + 健康
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from './api'

export const CONTROL_MODES = ['RUN', 'DEBUG']
// 模式中文显示标签 (枚举值保持英文, 界面显示中文)
export const MODE_LABELS = { RUN: '运行', DEBUG: '调试' }

export const useSystemStore = defineStore('system', () => {
  const mode = ref('DEBUG')
  const health = ref(null)
  const connected = ref(false)        // REST 健康可达
  const streamConnected = ref(false)  // WebSocket 事件流在线 (实时数据是否新鲜)

  async function refresh() {
    try {
      health.value = await api.health()
      mode.value = health.value.control_mode
      connected.value = true
    } catch (e) {
      connected.value = false
    }
  }

  async function setMode(m) {
    const r = await api.setMode(m)
    mode.value = r.control_mode
  }

  function setStreamConnected(on) {
    streamConnected.value = !!on
  }

  return { mode, health, connected, streamConnected, refresh, setMode, setStreamConnected }
})
