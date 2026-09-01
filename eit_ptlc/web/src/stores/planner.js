// 排程 store: 耗时统计拉取 + 样品/流程链计划 (localStorage 持久) + 排布与冲突计算
// 计划与显示口径只存前端 (键 eit_planner_plan_v1); 统计、资源模式与统计基线来自
// /api/planner/*; 排布计算全部走 utils/planner.js 纯函数, 后端只读不执行。
// 布局分工: 左 Dock 是流程库 (点行加入选中样品 + 口径/基线操作), 中区管排布。
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import { api, errText } from '../api.js'
import { loadJson, saveJson } from '../utils/storage.js'
import { buildDurationIndex, scheduleGreedy, detectConflicts } from '../utils/planner.js'

const PLAN_KEY = 'eit_planner_plan_v1'
const WINDOW_MIN = 1
const WINDOW_MAX = 200
const DURATION_MODES = ['avg', 'last']

let idSeq = 0
// 样品 id: 时间戳 + 递增序号, 删除后新增不撞旧 key
function genId() {
  idSeq += 1
  return `s_${Date.now().toString(36)}_${idSeq.toString(36)}`
}

export const usePlannerStore = defineStore('planner', () => {
  const stats = ref(null)      // /api/planner/stats 原始响应
  const loading = ref(false)
  const error = ref('')

  // 计划 (持久化部分): 样品链与显示设置; loadJson 只兜底解析, 形状在此守卫
  const plan = reactive(loadJson(PLAN_KEY, null) || {})
  if (!Array.isArray(plan.samples)) plan.samples = []
  if (!plan.settings || typeof plan.settings !== 'object') plan.settings = {}
  if (!(plan.settings.window >= WINDOW_MIN)) plan.settings.window = 50
  if (!(plan.settings.pxPerSec > 0)) plan.settings.pxPerSec = 2
  if (!DURATION_MODES.includes(plan.settings.durationMode)) plan.settings.durationMode = 'avg'

  // 排布结果 (非持久): 自动排程或手动拖动后的块布局
  const placements = ref([])
  const conflicts = ref([])
  const makespanS = ref(0)

  const selectedSampleId = ref('')   // 左侧点流程时的目标样品 (内存态)
  const timelineOp = ref('')         // 打开步骤时间线弹窗的流程名 (左 Dock 与甘特共用)

  // 流程名 → 统计项
  const opIndex = computed(() => {
    const map = {}
    for (const op of (stats.value && stats.value.operations) || []) map[op.name] = op
    return map
  })
  // 排程算法用的时长索引 (按当前口径定死时长)
  const durationIndex = computed(() => buildDurationIndex(stats.value, plan.settings.durationMode))
  // 资源 id → mode (exclusive|shared)
  const resourceModes = computed(() => {
    const map = {}
    for (const r of (stats.value && stats.value.resources) || []) map[r.id] = r.mode
    return map
  })
  // 资源元数据 [{id, label, mode}] (甘特资源泳道)
  const resourcesMeta = computed(() => (stats.value && stats.value.resources) || [])
  // 可排的流程: 滤隐藏与 legacy (左 Dock 流程库与排程共用同一集合)
  const pickerOps = computed(() =>
    ((stats.value && stats.value.operations) || []).filter((op) => !op.hidden && op.role !== 'legacy'))
  // 是否存在全局统计基线 (任一流程的基线来自全局时为真; 用于「清除全部/撤销全部」切换)
  const hasGlobalBaseline = computed(() => !!(stats.value && stats.value.global_baseline_ts))
  // 冲突涉及的块 key 集合 (甘特高亮)
  const conflictKeys = computed(() => {
    const keys = new Set()
    for (const c of conflicts.value) {
      keys.add(c.a)
      keys.add(c.b)
    }
    return keys
  })
  const selectedSample = computed(() =>
    plan.samples.find((s) => s.id === selectedSampleId.value) || null)

  function persist() {
    saveJson(PLAN_KEY, { samples: plan.samples, settings: plan.settings })
  }

  // 选中样品失效 (删除/首次) 时归到第一个样品
  function syncSelection() {
    if (!plan.samples.some((s) => s.id === selectedSampleId.value)) {
      selectedSampleId.value = plan.samples.length ? plan.samples[0].id : ''
    }
  }

  // 拉取统计; 已有样品时随后自动重排 (统计变化会改变块时长)
  async function loadStats() {
    loading.value = true
    error.value = ''
    try {
      stats.value = await api.plannerStats(plan.settings.window)
      syncSelection()
      if (plan.samples.length > 0) autoSchedule()
    } catch (e) {
      error.value = errText(e)
    } finally {
      loading.value = false
    }
  }

  // 左 Dock 与排程页共用: 已有数据或正在加载时不重复请求
  function ensureStats() {
    if (stats.value === null && !loading.value) {
      return loadStats()
    }
    return Promise.resolve()
  }

  // ---- 样品/链 CRUD (每次结构变更: 持久化 + 重排, 手动拖动结果被覆盖) ----

  function addSample() {
    const item = { id: genId(), label: `样品${plan.samples.length + 1}`, chain: [] }
    plan.samples.push(item)
    selectedSampleId.value = item.id       // 新建即选中, 左侧点流程直接落到它
    persist()
    autoSchedule()
    return item
  }

  function removeSample(id) {
    const idx = plan.samples.findIndex((s) => s.id === id)
    if (idx >= 0) {
      plan.samples.splice(idx, 1)
      syncSelection()
      persist()
      autoSchedule()
    }
  }

  function renameSample(id, label) {
    const item = plan.samples.find((s) => s.id === id)
    if (item) {
      item.label = label || item.label
      persist()
    }
  }

  function moveSample(id, dir) {
    const idx = plan.samples.findIndex((s) => s.id === id)
    const to = idx + dir
    if (idx < 0 || to < 0 || to >= plan.samples.length) {
      return
    }
    const [item] = plan.samples.splice(idx, 1)
    plan.samples.splice(to, 0, item)
    persist()
    autoSchedule()   // 样品顺序影响 FIFO 平局
  }

  function selectSample(id) {
    if (plan.samples.some((s) => s.id === id)) {
      selectedSampleId.value = id
    }
  }

  function addOp(sampleId, opName) {
    const item = plan.samples.find((s) => s.id === sampleId)
    if (item && opName) {
      item.chain.push(opName)
      persist()
      autoSchedule()
    }
  }

  // 左 Dock 点流程行: 追加到当前选中样品; 一个样品都没有时先自动建一个
  function addOpToSelected(opName) {
    if (!opName) {
      return
    }
    syncSelection()
    if (!selectedSampleId.value) {
      addSample()
    }
    addOp(selectedSampleId.value, opName)
  }

  function removeOp(sampleId, index) {
    const item = plan.samples.find((s) => s.id === sampleId)
    if (item && index >= 0 && index < item.chain.length) {
      item.chain.splice(index, 1)
      persist()
      autoSchedule()
    }
  }

  function moveOp(sampleId, index, dir) {
    const item = plan.samples.find((s) => s.id === sampleId)
    const to = index + dir
    if (!item || to < 0 || to >= item.chain.length) {
      return
    }
    const [op] = item.chain.splice(index, 1)
    item.chain.splice(to, 0, op)
    persist()
    autoSchedule()
  }

  // ---- 排布 ----

  // FIFO 贪心自动排程 (构造即无冲突, 覆盖手动拖动结果)
  function autoSchedule() {
    const out = scheduleGreedy(plan.samples, durationIndex.value, resourceModes.value)
    placements.value = out.placements
    makespanS.value = out.makespan_s
    conflicts.value = []
  }

  // 手动拖动: 只改该块开始时间 (钳 >= 0), 重算冲突与总时长
  function moveBlock(key, newStartS) {
    const p = placements.value.find((item) => item.key === key)
    if (!p) {
      return
    }
    const start = Math.max(0, newStartS)
    p.end_s = start + p.duration_s
    p.start_s = start
    conflicts.value = detectConflicts(placements.value, resourceModes.value)
    makespanS.value = placements.value.reduce((acc, item) => Math.max(acc, item.end_s), 0)
  }

  // ---- 统计口径与基线 ----

  function setWindow(n) {
    const win = Math.max(WINDOW_MIN, Math.min(Math.round(n) || 50, WINDOW_MAX))
    if (win !== plan.settings.window) {
      plan.settings.window = win
      persist()
      loadStats()   // 窗口变化需要重拉统计
    }
  }

  // 时间口径: avg 用最近 N 次平均, last 用最新一次实测
  function setDurationMode(mode) {
    if (DURATION_MODES.includes(mode) && mode !== plan.settings.durationMode) {
      plan.settings.durationMode = mode
      persist()
      autoSchedule()   // 时长变了, 直接重排
    }
  }

  function setPxPerSec(v) {
    if (v > 0 && isFinite(v)) {
      plan.settings.pxPerSec = Math.max(0.001, Math.min(v, 100000))
      persist()
    }
  }

  // 适配缩放: 让总时长正好占满可视宽度
  function fitToWidth(px) {
    if (px > 0) setPxPerSec(px / Math.max(makespanS.value, 0.001))
  }

  // 清除耗时记录 = 把统计基线设到当前时刻 (不删运行记录, 可撤销)
  // operation 省略/为空 → 全局基线, 作废全部流程的旧耗时
  async function resetBaseline(operation) {
    error.value = ''
    try {
      await api.plannerSetBaseline(operation || null)
      await loadStats()
    } catch (e) {
      error.value = errText(e)
    }
  }

  // 撤销基线; operation 省略/为空 → 清空全部基线, 恢复全部历史统计
  async function clearBaseline(operation) {
    error.value = ''
    try {
      await api.plannerClearBaseline(operation || null)
      await loadStats()
    } catch (e) {
      error.value = errText(e)
    }
  }

  function openTimeline(name) {
    timelineOp.value = name || ''
  }

  function closeTimeline() {
    timelineOp.value = ''
  }

  return {
    stats, loading, error, plan, placements, conflicts, makespanS,
    selectedSampleId, selectedSample, timelineOp,
    opIndex, durationIndex, resourceModes, resourcesMeta, pickerOps,
    hasGlobalBaseline, conflictKeys,
    loadStats, ensureStats,
    addSample, removeSample, renameSample, moveSample, selectSample,
    addOp, addOpToSelected, removeOp, moveOp,
    autoSchedule, moveBlock,
    setWindow, setDurationMode, setPxPerSec, fitToWidth,
    resetBaseline, clearBaseline, openTimeline, closeTimeline,
  }
})
