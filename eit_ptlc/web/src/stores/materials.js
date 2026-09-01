// 物料账本 store: 首屏拉一次 + 订阅 material_state 推流 (App.vue 扇出接入)
//
// 为什么需要它: 物料页此前只有 onMounted(reload) 与手动刷新按钮, 而后端
// material_feedback_loop 每 0.5 s 就在推完整快照 —— 那份推流在二维侧一直没人接,
// 于是"流程正在取放托盘"这件事在账本页上完全看不出来, 得靠人去点刷新。
// (三维侧的 MaterialPanel 反倒一直是实时的, 两边同一份账本却两种时效, 正是脱节所在。)
//
// 事件走宿主 SPA 的唯一事件流单例 (composables/eventStream.js), 不另开 WebSocket。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api.js'

/** material_state 事件里属于信封的字段, 不进账本投影。 */
const ENVELOPE = new Set(['type', 'ts', 'seq', 'initial', 'source'])

/** 记账流水的重拉去抖(毫秒): 推流最快 0.5 s 一帧, 流水没必要跟这么紧。 */
const EVENTS_DEBOUNCE_MS = 2000

export const useMaterialsStore = defineStore('materials', () => {
  const grid = ref(null)          // MaterialStore.grid() 的完整快照
  const events = ref([])          // 记账流水 (倒序)
  const error = ref('')
  /** 收到过至少一帧推流没有 —— 与 sys.streamConnected 合起来才是"实时中" */
  const pushed = ref(false)
  const sourceTs = ref(0)
  const lastSeq = ref(-1)

  /** 此刻有没有载荷挂在夹爪上 (供页面显示"在途"提示与人工清账入口) */
  const transit = computed(() => grid.value?.transit || {})
  const hasTransit = computed(() => Object.keys(transit.value).length > 0)

  async function load() {
    grid.value = await api.getMaterials()
    error.value = ''
  }

  async function loadEvents(limit = 40) {
    events.value = await api.getMaterialEvents({ limit })
  }

  let eventsTimer = null
  function scheduleEvents() {
    if (eventsTimer) return
    eventsTimer = setTimeout(() => {
      eventsTimer = null
      loadEvents().catch(() => { /* 流水拉不到不该让账本页空白 */ })
    }, EVENTS_DEBOUNCE_MS)
    eventsTimer.unref?.()
  }

  /**
   * 消费一帧 material_state。
   *
   * 快照是完整的且属于可丢旧事件 (runtime/events.py 的 _DROPPABLE_TYPES), 所以只需
   * 保留最新一帧; 但仍要挡住乱序到达的旧帧, 否则页面会在两个版本之间来回跳。
   * initial=true 是新连接的补种帧, 一律接受 (后端重启后 ts 可能回退)。
   *
   * ⚠ 时间大跳也算重启: 后端重启后新进程的时钟可能**前进**一大截, 那时 ts 不回退,
   *   前两条判据都拦不住它 —— 但它同样是新一轮的起点, 该无条件接受。判据与三维侧的
   *   MaterialStateStore.push 拉平 (那边一直有这一条), 免得两层对"重启"的定义不一致。
   */
  function ingest(event) {
    if (event?.type !== 'material_state') return
    const ts = Number(event.ts) || 0
    const seq = Number(event.seq) || 0
    const restarted = event.initial === true || !pushed.value || ts > sourceTs.value + 1000
    if (!restarted) {
      if (ts < sourceTs.value) return
      if (ts === sourceTs.value && seq <= lastSeq.value) return
    }
    const next = {}
    for (const [key, value] of Object.entries(event)) {
      if (!ENVELOPE.has(key)) next[key] = value
    }
    grid.value = next
    sourceTs.value = ts
    lastSeq.value = seq
    pushed.value = true
    scheduleEvents()
  }

  return {
    grid, events, error, pushed, transit, hasTransit,
    load, loadEvents, ingest,
  }
})
