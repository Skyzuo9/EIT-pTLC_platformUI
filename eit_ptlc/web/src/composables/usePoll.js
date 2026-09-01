// 纯读取轮询 (可见性暂停 + 在途单飞)
// ====================================
// 为什么抽: 全库 14+ 处 setInterval 轮询无一查页面可见性, 后台标签页合计 ~10+ req/s
// 持续打后端。本原语把「hidden 沿停表、可见沿立即补一拍再续表」「上一拍未返回跳过本拍」
// 「单拍失败不许杀轮询」三件事收敛成一处。
//
// 适用边界 (头注定案, 勿迁入以下三类):
//   1. 心跳/续订 (stores/manual.js keepalive、utils/jogKeeper.js) —— 停 = 会话被收/轴卡死,
//      语义是"证明活着"不是"读取数据"。
//   2. 恢复兜底 (stores/runs.js syncPoll) —— WS 无关的收口路径, 有自己的幂等启停与 unref。
//   3. store 自管生命周期的轮询 (stores/manual.js refresh、stores/scheduler.js) ——
//      onBeforeUnmount 挂不进 store; manual.refresh 的 500/2000ms 是档位不是开关。
//
// 不变量:
//   - document.hidden 沿自动停; 可见沿**立即补一拍**再续表 (回来先见新数据, 不等一个 interval)。
//   - enabled ref (可选) 为假沿停、真沿补拍 —— 面板级开关 (如页签切走)。
//   - overlap='skip': 在途未返回跳过本拍 (慢链路不堆积并发)。
//   - fn 异常吞掉不停表 (单拍失败不许杀轮询; 错误展示是调用方 fn 内部的事)。
//   - onBeforeUnmount 无条件停 + 卸监听。
import { onBeforeUnmount, unref, watch } from 'vue'

/**
 * @param {Function} fn async () => void, 单拍逻辑 (含错误落点)
 * @param {number} interval 拍间隔 ms
 * @param {object} [opts]
 * @param {boolean} [opts.immediate] start()/恢复沿是否立即补一拍, 默认 true
 * @param {import('vue').Ref<boolean>} [opts.enabled] 面板级开关; 省略 = 恒开
 * @param {'skip'} [opts.overlap] 在途策略, 目前仅 skip
 * @returns {{ start: Function, stop: Function, tick: Function, running: () => boolean }}
 */
export function usePoll(fn, interval, { immediate = true, enabled } = {}) {
  let timer = null
  let wanted = false // start() 过且未 stop(): 意图位, hidden/enabled 只影响是否实际在表
  let inflight = false

  function allowed() {
    return wanted && !document.hidden && (enabled === undefined || !!unref(enabled))
  }

  async function tick() {
    if (inflight) return // 在途单飞 = 不堆积并发
    inflight = true
    try {
      await fn()
    } catch (_e) {
      /* 单拍失败不停表; 错误展示由 fn 自理 */
    } finally {
      inflight = false
    }
  }

  function arm() {
    if (timer) return
    if (immediate) tick()
    timer = window.setInterval(tick, interval)
  }

  function disarm() {
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }

  function sync() {
    if (allowed()) arm()
    else disarm()
  }

  function start() {
    wanted = true
    sync()
  }

  function stop() {
    wanted = false
    disarm()
  }

  document.addEventListener('visibilitychange', sync)
  if (enabled !== undefined) watch(enabled, sync)

  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', sync)
  })

  return { start, stop, tick, running: () => timer !== null }
}
