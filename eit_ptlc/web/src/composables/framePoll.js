// 单帧轮询 (瞬时连接, fetch → blob → objectURL)
// ================================================
// 取代旧 "<img :src> 加 ?_=tick 直挂" 轮询: 那种写法任何一次请求失败 (上游 502/503、
// 网络瞬断) 都会把 <img> 打进破图态 → 画面黑闪一拍, 下一拍成功又恢复。这里只在拉帧
// 成功时才换 src —— 失败保持最后一帧, 中断/恢复走 console 边沿日志 (宿主侧对应日志在
// waterlevel_service 拉帧循环), 持续中断时由调用方用 stale 标记给出角标而非黑屏。
// 后台标签页自动暂停 (8 路网格 400ms + 单路 100ms 合计 20+ req/s, 切走没有理由继续拉),
// 回见沿立即补一拍; 监听按实例挂 (setup 中调用, onBeforeUnmount 对称卸)。
import { onBeforeUnmount, reactive } from 'vue'

const STALE_AFTER = 5 // 连续失败达此数才亮 stale 角标 (单次瞬断完全不打扰用户)

export function useFramePoll(getUrl, periodMs, label = '') {
  const state = reactive({ src: '', stale: false })
  let timer = null
  let inflight = false
  let failCount = 0
  let failStartedAt = 0
  let nextAttemptAt = 0
  let objectUrl = ''

  async function attempt() {
    // 上一拍未返回则跳过本拍 (慢链路下不堆积并发); 持续失败时按 nextAttemptAt 降频
    if (inflight || Date.now() < nextAttemptAt) return
    inflight = true
    try {
      const resp = await fetch(getUrl(), {
        cache: 'no-store',
        // 超时上限: 防 TCP 黑洞挂死 inflight 致"无角标静默冻结" (超时按失败计入退避/角标)
        signal: AbortSignal.timeout(Math.max(5000, periodMs * 2)),
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const blob = await resp.blob()
      const prev = objectUrl
      objectUrl = URL.createObjectURL(blob)
      state.src = objectUrl
      if (prev) URL.revokeObjectURL(prev)
      if (failCount) {
        console.info(`[WL] ${label} 取帧恢复 (中断 ${((Date.now() - failStartedAt) / 1000).toFixed(1)}s, 连续失败 ${failCount} 次)`)
      }
      failCount = 0
      state.stale = false
    } catch (e) {
      failCount += 1
      if (failCount === 1) {
        failStartedAt = Date.now()
        console.info(`[WL] ${label} 取帧失败, 画面保持最后一帧: ${e.message || e}`)
      }
      if (failCount >= STALE_AFTER) state.stale = true
      // 失败退避: 200ms×连续次数, 封顶 2s —— 设备离线时不高频打代理
      nextAttemptAt = Date.now() + Math.min(2000, 200 * failCount)
    } finally {
      inflight = false
    }
  }

  // wanted = 调用方意图位 (start 过且未 stop); hidden 只影响是否实际在表 (arm/disarm),
  // 回见沿立即补一拍 (attempt 自带 inflight 单飞与失败退避门, 补拍天然限流)
  let wanted = false

  function arm() {
    if (timer) return
    attempt()
    timer = window.setInterval(attempt, periodMs)
  }
  function disarm() {
    if (timer) {
      window.clearInterval(timer)
      timer = null
    }
  }
  function onVisibility() {
    if (document.hidden) disarm()
    else if (wanted) arm()
  }

  function start() {
    wanted = true
    if (!document.hidden) arm()
  }
  function stop() {
    wanted = false
    disarm()
  }
  document.addEventListener('visibilitychange', onVisibility)
  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibility)
    if (objectUrl) URL.revokeObjectURL(objectUrl)
  })
  return { state, start, stop }
}
