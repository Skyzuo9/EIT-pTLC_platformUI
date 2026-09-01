// 实验/调度 store: 快照轮询 (视图挂载期 3s + WS 去抖触发) + 批次列表/详情 + 方案/旋钮缓存 + 动词
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import { api } from '../api.js'

export const useSchedulerStore = defineStore('scheduler', () => {
  const recipes = ref([])            // GET /api/recipes
  const snapshot = ref(null)         // GET /api/scheduler/snapshot (看板权威投影)
  const batches = ref([])            // GET /api/experiments (含历史终态批)
  const batchDetails = reactive({})  // batch_id -> 详情缓存 (打开即刷新)
  const knobsByOp = reactive({})     // opName -> knobs[] (提交表单聚合缓存)
  const selectedJob = ref(null)      // 看板选中 {batchId, sampleId, flowId, runId}
  const error = ref('')
  const submitting = ref(false)
  const verbBusy = reactive({})      // `${scope}:${id}:${verb}` -> bool
  const lastSyncAt = ref(0)          // Date.now() (最后一次快照到达)
  const clockSkew = ref(0)           // 服务端 now - 本地 now (秒); elapsed 计算用

  const activeBatches = computed(() => (snapshot.value?.batches || []))
  const resources = computed(() => snapshot.value?.resources || {})
  const tanks = computed(() => snapshot.value?.tanks || {})
  const occupancy = computed(() => snapshot.value?.occupancy || {})
  // 服务端校正后的"当前 epoch 秒" (甘特 nowS 与占用时长都以它为基准, 不信本地钟)
  function serverNow() {
    return Date.now() / 1000 + clockSkew.value
  }

  async function loadRecipes() {
    recipes.value = await api.listRecipes()
  }
  function ensureRecipes() {
    if (!recipes.value.length) loadRecipes().catch((e) => { error.value = String(e) })
  }

  let snapInflight = false
  async function loadSnapshot() {
    if (snapInflight) return
    snapInflight = true
    try {
      const snap = await api.schedulerSnapshot()
      snapshot.value = snap
      lastSyncAt.value = Date.now()
      if (snap.now) clockSkew.value = snap.now - Date.now() / 1000
      error.value = ''
    } catch (e) {
      error.value = String(e)
    } finally {
      snapInflight = false
    }
  }
  function ensureSnapshot() {
    if (!snapshot.value) loadSnapshot()
  }

  // 轮询: 仅调度视图挂载期间 3s (引用计数); 其余时间靠 scheduler_update 事件去抖拉取
  let pollTimer = null
  let pollRefs = 0
  function startPolling() {
    pollRefs += 1
    if (!pollTimer) {
      pollTimer = setInterval(() => loadSnapshot(), 3000)
      pollTimer.unref?.()
    }
  }
  function stopPolling() {
    pollRefs = Math.max(0, pollRefs - 1)
    if (pollRefs === 0 && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  // WS 事件: scheduler_update / experiment_update -> 去抖 500ms 刷新快照 (App.vue 扇出接入)
  let debounceTimer = null
  function ingest(event) {
    const type = event?.type || ''
    if (type !== 'scheduler_update' && type !== 'experiment_update') return
    if (debounceTimer) return
    debounceTimer = setTimeout(() => {
      debounceTimer = null
      loadSnapshot()
      loadBatches().catch(() => {})
    }, 500)
    debounceTimer.unref?.()
  }

  async function loadBatches() {
    batches.value = await api.listExperiments({ limit: 50 })
  }
  function ensureBatches() {
    if (!batches.value.length) loadBatches().catch((e) => { error.value = String(e) })
  }

  async function loadBatch(batchId) {
    const detail = await api.getExperiment(batchId)
    batchDetails[batchId] = detail
    return detail
  }

  // 提交表单的旋钮拉取: 对方案各段 op 并发 getKnobs (失败段回空数组, 不阻断)
  async function loadRecipeKnobs(recipe) {
    const ops = [...new Set((recipe?.segments || []).map((s) => s.op))]
    await Promise.all(ops.map(async (op) => {
      if (knobsByOp[op]) return
      try {
        const res = await api.getKnobs(op)
        knobsByOp[op] = res.knobs || []
      } catch (e) {
        knobsByOp[op] = []
      }
    }))
  }

  async function submitExperiment(payload) {
    submitting.value = true
    try {
      const res = await api.submitExperiment(payload)
      await Promise.all([loadBatches().catch(() => {}), loadSnapshot()])
      return res
    } finally {
      submitting.value = false
    }
  }

  async function _verb(key, fn) {
    if (verbBusy[key]) return null
    verbBusy[key] = true
    try {
      const res = await fn()
      await loadSnapshot()
      return res
    } finally {
      verbBusy[key] = false
    }
  }

  const batchVerb = (bid, verb) => _verb(`batch:${bid}:${verb}`, () => api.experimentVerb(bid, verb))
  const sampleVerb = (bid, sid, verb) => _verb(`sample:${sid}:${verb}`, () => api.sampleVerb(bid, sid, verb))
  const jobVerb = (bid, sid, flow, verb, body) =>
    _verb(`job:${sid}:${flow}:${verb}`, () => api.jobVerb(bid, sid, flow, verb, body))
  const reconcile = (bid, payload) => _verb(`batch:${bid}:reconcile`, () => api.experimentReconcile(bid, payload))

  function selectJob(ref_) {
    selectedJob.value = ref_
  }

  return {
    recipes, snapshot, batches, batchDetails, knobsByOp, selectedJob, error, submitting,
    verbBusy, lastSyncAt, activeBatches, resources, tanks, occupancy, serverNow,
    loadRecipes, ensureRecipes, loadSnapshot, ensureSnapshot, startPolling, stopPolling,
    ingest, loadBatches, ensureBatches, loadBatch, loadRecipeKnobs, submitExperiment,
    batchVerb, sampleVerb, jobVerb, reconcile, selectJob,
  }
})
