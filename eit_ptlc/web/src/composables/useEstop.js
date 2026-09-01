// 全局急停 (模块级单例, 照 confirmService 的 module current 先例)
// ================================================================
// 为什么抽: 模态 backdrop (z-index 1000) 打开期间盖死态势条上的急停按钮, 而机器运动
// 与当前模态语义无关 —— 急停必须在任何 UI 状态下可达。状态放模块级: StatusBar 与
// 各弹窗头部的 EstopButton 渲染**同一组状态** (下发中/已下发在所有按钮上同步显示)。
//
// 定案 (勿改): 急停永不确认、永不禁用、每次点击直发 (服务端幂等), 在途也不拦;
// 反馈是"下发回执"而非设备状态 (遥测暂无急停状态位, 不伪装设备真相)。
import { ref } from 'vue'
import { api, errText } from '../api.js'
import { announce } from './announcer.js'

const busy = ref(false)
const sent = ref(false)
const error = ref('')
let sentTimer = null

async function emergencyStop() {
  busy.value = true
  try {
    await api.robotEmergencyStop(true)
    error.value = ''
    sent.value = true
    announce('急停指令已下发', { assertive: true })
    if (sentTimer) clearTimeout(sentTimer)
    sentTimer = setTimeout(() => {
      sent.value = false
    }, 4000)
  } catch (e) {
    error.value = `急停下发失败: ${errText(e)}`
    announce(`急停下发失败, 请立即使用物理急停。${errText(e)}`, { assertive: true })
  } finally {
    busy.value = false
  }
}

export function useEstop() {
  return { busy, sent, error, emergencyStop }
}
