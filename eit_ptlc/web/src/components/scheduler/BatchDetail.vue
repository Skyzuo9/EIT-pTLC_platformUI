<script setup>
// 批次详情: 状态/批级动词 + 参数快照 (只读) + 逐样品段链与结果指标 (Rf) + 对账收口
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useSchedulerStore } from '../../stores/scheduler'
import { confirmAction } from '../../composables/confirmService.js'
import { api, errText } from '../../api.js'
import { chipStateOf, shortSegLabel } from '../../utils/scheduler.js'

const props = defineProps({ batchId: { type: String, required: true } })
const scheduler = useSchedulerStore()
const router = useRouter()

const detail = ref(null)
const results = ref([])
const err = ref('')
const showParams = ref(false)

async function load() {
  err.value = ''
  try {
    detail.value = await scheduler.loadBatch(props.batchId)
    results.value = await api.experimentResults(props.batchId)
  } catch (e) {
    err.value = errText(e)
  }
}
watch(() => props.batchId, load, { immediate: true })
// 快照刷新沿路带动详情 (低频; 详情页开着时保持新鲜)
watch(() => scheduler.lastSyncAt, () => { if (detail.value) load() })

const rfBySample = computed(() => {
  const map = {}
  for (const r of results.value) {
    if (r.kind !== 'band' || r.rf == null) continue
    ;(map[r.sample_id] = map[r.sample_id] || []).push(r.rf)
  }
  return map
})

// 段 id -> 中文短标签 (实验库详情不带 label, 从调度方案段表映射; 方案缺失回退裸 id)
scheduler.ensureRecipes()
const segLabelById = computed(() => {
  const recipe = scheduler.recipes.find((r) => r.name === detail.value?.recipe)
  const map = {}
  for (const s of recipe?.segments || []) map[s.id] = shortSegLabel(s.label) || s.id
  return map
})

const VERB_TEXT = {
  start: '启动批次: 调度器开始派发段作业, 设备将实际运动。',
  pause: '暂停批次: 停止派发新段; 在飞段跑完当前段自然停在段边界。',
  resume: '恢复批次派发。',
  abort: '中止批次: 待派段全部取消, 释放耗材预留; 在飞段跑完记账。缸内板/夹具收集器等物理残留需随后人工对账清理。',
}
const verbErr = ref('')
async function act(verb) {
  const ok = await confirmAction({ title: `批次: ${verb}`, message: VERB_TEXT[verb],
                                   level: verb === 'abort' ? 'danger' : 'default',
                                   confirmText: '执行' })
  if (!ok) return
  verbErr.value = ''
  try {
    await scheduler.batchVerb(props.batchId, verb)
    await load()
  } catch (e) { verbErr.value = errText(e) }
}

// 对账收口: 各段处置请先在看板逐段完成 (重试/续跑/跳过), 此处清对账标志并按选择释放缸/占位
const releasePhysical = ref(true)
async function finishReconcile() {
  const tanks = releasePhysical.value
    ? Object.entries(scheduler.tanks).filter(([, o]) => o && sampleIds.value.includes(o)).map(([t]) => Number(t))
    : []
  const occ = releasePhysical.value
    ? Object.entries(scheduler.occupancy).filter(([, o]) => o && sampleIds.value.includes(o)).map(([n]) => n)
    : []
  const ok = await confirmAction({
    title: '完成对账',
    message: `确认全部中断段已逐一处置 (看板里重试/续跑/跳过), 且现场已人工核实。`
      + (tanks.length ? `\n将释放缸: ${tanks.join(', ')} (请确认缸已清理)` : '')
      + (occ.length ? `\n将清占位: ${occ.join(', ')} (请确认夹具已空)` : ''),
    level: 'danger', confirmText: '完成对账',
  })
  if (!ok) return
  try {
    await scheduler.reconcile(props.batchId, { decisions: [], release_tanks: tanks, clear_occupancy: occ })
    await load()
  } catch (e) { verbErr.value = errText(e) }
}
const sampleIds = computed(() => (detail.value?.samples || []).map((s) => s.sample_id))

function fmtClock(epoch) {
  return epoch ? new Date(epoch * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
</script>

<template>
  <div class="bd">
    <div class="bd-head">
      <button class="mini" @click="router.push('/experiment')">← 看板</button>
      <span class="group-title">{{ detail?.name || batchId }}</span>
      <span v-if="detail" class="badge" :class="detail.status">{{ detail.status }}</span>
      <span v-if="detail?.needs_reconcile" class="badge ERROR">待对账</span>
      <span class="bd-verbs">
        <button v-if="detail && ['QUEUED', 'PAUSED'].includes(detail.status) && !detail.needs_reconcile"
                class="mini ok" @click="act(detail.status === 'QUEUED' ? 'start' : 'resume')">
          {{ detail.status === 'QUEUED' ? '▶ 启动' : '▶ 继续' }}</button>
        <button v-if="detail?.status === 'RUNNING'" class="mini" @click="act('pause')">⏸ 暂停</button>
        <button v-if="detail && ['QUEUED', 'RUNNING', 'PAUSED'].includes(detail.status)"
                class="mini danger" @click="act('abort')">■ 中止</button>
      </span>
    </div>
    <p v-if="err" class="empty err">{{ err }}</p>
    <p v-if="verbErr" class="empty err">{{ verbErr }}</p>

    <div v-if="detail" class="bd-body">
      <div v-if="detail.needs_reconcile" class="bd-reconcile">
        <b>重启/中止对账:</b> 先在看板对每个「中断/失败」段选择 重试 / 断点续跑 / 跳过 / 标记完成,
        再回此处收口。
        <label><input type="checkbox" v-model="releasePhysical" /> 同时释放本批占用的缸与夹具占位 (须现场确认已清理)</label>
        <button class="mini danger" @click="finishReconcile">完成对账</button>
      </div>

      <table class="kv bd-meta">
        <tbody>
          <tr><td>批次号</td><td class="num">{{ detail.batch_id }}</td></tr>
          <tr><td>调度方案</td><td>{{ detail.recipe }}</td></tr>
          <tr><td>提交</td><td class="num">{{ fmtClock(detail.submitted_at) }}</td></tr>
          <tr><td>起止</td><td class="num">{{ fmtClock(detail.started_at) }} → {{ fmtClock(detail.finished_at) }}</td></tr>
          <tr><td>自动排液</td><td>{{ detail.auto_drain ? '开' : '关 (每样品人工确认)' }}</td></tr>
          <tr v-if="detail.note"><td>备注</td><td>{{ detail.note }}</td></tr>
        </tbody>
      </table>

      <button type="button" class="btn-bare group-title clickable" :aria-expanded="showParams"
              @click="showParams = !showParams">
        <span class="chev">{{ showParams ? '▾' : '▸' }}</span>参数快照 (提交时冻结, 复现实验用)
      </button>
      <div v-show="showParams" class="bd-params">
        <div class="bd-param-block">
          <div class="knob-group-title">批级工艺参数</div>
          <pre class="num">{{ JSON.stringify(detail.params || {}, null, 2) }}</pre>
        </div>
        <div v-if="(detail.overrides || []).some((o) => o && Object.keys(o).length)" class="bd-param-block">
          <div class="knob-group-title">逐样品覆盖</div>
          <pre class="num">{{ JSON.stringify(detail.overrides, null, 2) }}</pre>
        </div>
        <div class="bd-param-block">
          <div class="knob-group-title">设备参数快照 (gcode/pump/vision)</div>
          <pre class="num">{{ JSON.stringify(detail.config_snapshot || {}, null, 2) }}</pre>
        </div>
      </div>

      <div class="group-title">样品 ({{ detail.samples.length }})</div>
      <div v-for="s in detail.samples" :key="s.sample_id" class="bd-sample">
        <div class="bd-sample-head">
          <b class="num">{{ s.sample_id }}</b>
          <span class="badge" :class="s.status">{{ s.status }}</span>
          <small class="muted">{{ s.position || '—' }}{{ s.tank ? ` · 缸${s.tank}` : '' }}</small>
          <small v-if="s.message" class="muted">· {{ s.message }}</small>
          <span v-if="rfBySample[s.sample_id]" class="bd-rf num"
                :title="'条带 Rf (视觉结果摄取)'">Rf: {{ rfBySample[s.sample_id].map((v) => v.toFixed(3)).join(' / ') }}</span>
        </div>
        <div class="bd-jobs">
          <span v-for="j in s.jobs" :key="j.job_id" class="sch-chip" :class="chipStateOf(j.status).cls"
                :title="`${j.flow_id} · ${j.script} · ${j.status}${j.message ? ' · ' + j.message : ''}`">
            <span class="sch-chip-id">{{ segLabelById[j.flow_id] || j.flow_id }}</span>
            <router-link v-if="j.run_id" class="sch-chip-run num" :to="`/runs/${j.run_id}`"
                         title="打开运行回放">{{ chipStateOf(j.status).label }}</router-link>
            <span v-else class="sch-chip-st">{{ chipStateOf(j.status).label }}</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bd { height: 100%; overflow: auto; padding: 12px 16px; max-width: 1080px; }
.bd-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }
.bd-verbs { margin-left: auto; display: flex; gap: 6px; }
.bd-reconcile { border: 1px solid var(--bad); border-radius: 8px; padding: 8px 10px; margin: 8px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: var(--fs-13); }
.bd-meta { margin: 8px 0; }
.bd-params { display: flex; gap: 12px; flex-wrap: wrap; }
.bd-param-block pre { max-height: 240px; overflow: auto; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: var(--fs-11); max-width: 420px; }
.knob-group-title { font-size: var(--fs-12); font-weight: 600; color: var(--subtle); margin: 6px 0 4px; }
.bd-sample { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; }
.bd-sample-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.bd-rf { margin-left: auto; color: var(--accent); font-weight: 600; }
.bd-jobs { display: flex; flex-wrap: wrap; gap: 4px; }
.sch-chip { display: inline-flex; flex-direction: column; align-items: center; min-width: 44px; border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px; background: var(--surface-2); font-size: var(--fs-11); line-height: 1.25; }
.sch-chip-id { font-weight: 600; }
.sch-chip-st, .sch-chip-run { font-size: 10px; color: var(--muted); }
.sch-chip.running { border-color: var(--warn); animation: pulse 1.4s ease-in-out infinite; }
.sch-chip.human { border-color: var(--accent); }
.sch-chip.done { border-color: var(--ok); }
.sch-chip.failed { border-color: var(--bad); }
.sch-chip.skipped { opacity: 0.55; }
.chev { display: inline-block; width: 1em; color: var(--muted); }
.empty.err { color: var(--bad); }
</style>
