// 按钮级异步动作包装: busy/连发保护/最小间隔/两段式武装/错误捕获+读屏播报
// ==========================================================================
// 为什么抽: 全仓的按钮动作在"整页 busy 锁死 80+ 控件"与"完全没有 busy 可连点双发"
// 两个极端之间摇摆; 且 134 处 loading 状态无一处对读屏可见。本原语把这四件事
// 收敛成一处: 每个动作自带独立 busy、在途去重、结果播报、错误落点。
//
// 模板接法 (约定; 返回值是 reactive 对象, 模板/脚本一律 x.busy 直取, **不要解构** — 解构丢响应性):
//   const save = useAsyncAction(() => api.saveX(...), { announce: '已保存', errorPrefix: '保存失败' })
//   <button :disabled="save.busy || !canSave" :aria-busy="save.busy"
//           @click="save.run()">{{ save.busy ? '保存中…' : '保存' }}</button>
//
// 不变量:
//   1. busy 期间 run() 直接忽略 —— 在途去重就是连发保护的核心。
//   2. fn 抛错必被捕获: error 置文案 + assertive 播报, 绝不外泄 unhandled rejection。
//   3. arm 两段式 (高频危险调试操作防"确认疲劳"): 首次 run() 只置 armed
//      (按钮原地变 armedLabel), 超时自动撤防; 二次 run() 才真执行。
//      适用: DO 直控/夹爪这类每次弹模态会被文化性绕过的操作。全量确认仍走 confirmAction。
import { getCurrentInstance, onBeforeUnmount, reactive, ref } from 'vue'
import { errText } from '../api.js'
import { announce } from './announcer.js'

/**
 * @param {Function} fn async (...args) => result
 * @param {object} [opts]
 * @param {string|Function|false} [opts.announce] 成功播报文案 (或 (result)=>string); 缺省不播报
 * @param {string} [opts.errorPrefix] 失败文案前缀, 组装为 `${errorPrefix}: ${errText(e)}`
 * @param {Function} [opts.onError] (msg, e) => void, 覆盖/追加错误落点 (如写入面板 .result)
 * @param {number} [opts.minInterval] 完成后 N ms 内忽略再次触发 (机器人单发动作建议 350)
 * @param {{label?: string, timeoutMs?: number}} [opts.arm] 两段式武装配置
 */
export function useAsyncAction(fn, opts = {}) {
  const { announce: ann, errorPrefix = '', onError, minInterval = 0, arm = null } = opts
  const busy = ref(false)
  const error = ref('')
  const armed = ref(false)
  const armedLabel = arm ? arm.label || '再点一次确认' : ''
  let armTimer = null
  let lastDone = 0

  function disarm() {
    armed.value = false
    if (armTimer) {
      clearTimeout(armTimer)
      armTimer = null
    }
  }

  async function run(...args) {
    if (busy.value) return undefined
    if (minInterval && Date.now() - lastDone < minInterval) return undefined
    if (arm && !armed.value) {
      armed.value = true
      armTimer = setTimeout(disarm, arm.timeoutMs || 3000)
      return undefined
    }
    disarm()
    busy.value = true
    error.value = ''
    try {
      const result = await fn(...args)
      if (ann) {
        const text = typeof ann === 'function' ? ann(result) : ann
        if (text) announce(text)
      }
      return result
    } catch (e) {
      const msg = (errorPrefix ? `${errorPrefix}: ` : '') + errText(e)
      error.value = msg
      announce(msg, { assertive: true })
      if (onError) onError(msg, e)
      return undefined
    } finally {
      busy.value = false
      lastDone = Date.now()
    }
  }

  // 组件内使用时随卸载撤防 (armTimer 只翻 ref 本无害, 清掉更干净); 裸用 (测试) 时跳过
  if (getCurrentInstance()) {
    onBeforeUnmount(disarm)
  }

  // reactive 包装: 模板与脚本统一 x.busy / x.error 直取 (内部 ref 自动解包), 勿解构
  return reactive({ run, busy, error, armed, armedLabel, disarm })
}
