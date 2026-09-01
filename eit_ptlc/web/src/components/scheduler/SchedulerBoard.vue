<script setup>
// 运行看板: 样品×段流水线矩阵 + 资源占用条 (含持有者) + 实际执行甘特 + 段作业详情右栏
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import GanttChart from '../planner/GanttChart.vue'
import StepTree from '../StepTree.vue'
import Splitter from '../Splitter.vue'
import { useSchedulerStore } from '../../stores/scheduler'
import { useRunsStore } from '../../stores/runs'
import { useLayoutStore } from '../../stores/layout'
import { confirmAction } from '../../composables/confirmService.js'
import { api, errText } from '../../api.js'
import { reduceRun } from '../../stores/runs.js'
import { buildActualPlacements, chipStateOf, shortSegLabel, waitReasonText } from '../../utils/scheduler.js'
import { fmtDur } from '../../utils/planner.js'

const scheduler = useSchedulerStore()
const runs = useRunsStore()
const layout = useLayoutStore()
const router = useRouter()

const batches = computed(() => scheduler.activeBatches)

// 1s 本地 tick: 只推动运行中块的开区间末端与占用时长显示 (快照 3s 到达时校正)
const tick = ref(0)
const tickTimer = setInterval(() => { tick.value += 1 }, 1000)
tickTimer.unref?.()
onBeforeUnmount(() => clearInterval(tickTimer))

// ---- 资源占用条 (含持有者 run_id 与已持有时长) ----
const resourceRows = computed(() => {
  void tick.value
  const out = []
  for (const [rid, item] of Object.entries(scheduler.resources)) {
    if (item.mode === 'shared') {
      if (item.holders) out.push({ id: rid, label: item.label, holder: `${item.holders} 个持有者`, elapsed: '' })
      continue
    }
    if (!item.locked) continue
    const since = item.since ? Math.max(0, scheduler.serverNow() - item.since) : null
    out.push({ id: rid, label: item.label, holder: item.holder || '?',
               elapsed: since != null ? fmtDur(since) : '' })
  }
  return out
})

const tankRows = computed(() =>
  Object.entries(scheduler.tanks).map(([t, owner]) => ({ tank: t, owner })))

// ---- 实际执行甘特 (readonly; 一个活动批一组泳道; v1 取首个活动批) ----
const ganttBatch = computed(() => batches.value.find((b) => b.status !== 'QUEUED') || batches.value[0])
const gantt = computed(() => {
  void tick.value
  if (!ganttBatch.value) return { placements: [], samples: [], makespan: 0, nowS: null }
  const { t0, placements } = buildActualPlacements(ganttBatch.value, scheduler.serverNow())
  const samples = (ganttBatch.value.samples || []).map((s) => ({ id: s.sample_id, label: s.sample_id }))
  const nowS = t0 ? Math.max(0, scheduler.serverNow() - t0) : null
  const makespan = Math.max(nowS || 0, ...placements.map((p) => p.end_s), 60)
  return { placements, samples, makespan, nowS }
})
const pxPerSec = ref(1)
const showGantt = ref(true)

// ---- 选中段作业 (右栏详情; 实时运行接 runs 多通道投影, 历史经 getRun 回放) ----
const picked = ref(null)   // {batchId, sample, job}
const pickedReplay = ref(null)
async function pick(batchId, sample, job) {
  picked.value = { batchId, sample, job }
  pickedReplay.value = null
  const rid = job.run_id
  if (rid && runs.activeById[rid]) {
    runs.select(rid)   // 底部监视器联动选中该运行
    return
  }
  if (rid) {
    try {
      const rec = await api.getRun(rid)
      pickedReplay.value = reduceRun(rec.events || [])
    } catch (e) { pickedReplay.value = null }
  }
}
function onGanttSelect(p) {
  const b = ganttBatch.value
  if (!b) return
  const sample = (b.samples || []).find((s) => s.sample_id === p.sampleId)
  const job = sample && (sample.jobs || []).find((j) => j.flow_id === p.label)
  if (sample && job) pick(b.batch_id, sample, job)
}
const pickedLive = computed(() => {
  const rid = picked.value?.job?.run_id
  return rid ? runs.activeById[rid] : null
})

// ---- 段/样品动词 (确认门文案如实描述后果) ----
const verbErr = ref('')
async function jobAct(verb) {
  const p = picked.value
  if (!p) return
  const texts = {
    retry: `整段重跑「${p.job.flow_id}」。请先确认现场物理状态与段前置一致 (样品位置/夹具/缸)。`,
    resume: `从失败断点续跑「${p.job.flow_id}」(${p.job.failed_step || '?'} 起)。请先人工确认物理态。`,
    skip: `跳过「${p.job.flow_id}」: 该段视为已满足, 后续段照常调度。仅当已人工完成或确认可略过时使用。`,
    mark_done: `把「${p.job.flow_id}」标记为完成 (人工代完成)。后续段照常调度。`,
  }
  const ok = await confirmAction({ title: `段作业: ${verb}`, message: texts[verb], level: 'danger',
                                   confirmText: '执行' })
  if (!ok) return
  verbErr.value = ''
  try {
    await scheduler.jobVerb(p.batchId, p.sample.sample_id, p.job.flow_id, verb,
                            verb === 'retry' ? { confirm: true } : {})
  } catch (e) { verbErr.value = errText(e) }
}
async function sampleAct(verb) {
  const p = picked.value
  if (!p) return
  const texts = {
    hold: '样品段边界软停: 跑完当前段后不再推进; 可随时恢复。',
    resume: '恢复该样品的段派发。',
    abort: '终止样品: 后续段全部取消, 释放其耗材预留; 在飞段跑完当前动作后停。物理残留需经批次对账清理。',
  }
  const ok = await confirmAction({ title: `样品: ${verb}`, message: texts[verb],
                                   level: verb === 'abort' ? 'danger' : 'default', confirmText: '执行' })
  if (!ok) return
  try {
    await scheduler.sampleVerb(p.batchId, p.sample.sample_id, verb)
  } catch (e) { verbErr.value = errText(e) }
}

function fmtClock(epoch) {
  if (!epoch) return '—'
  return new Date(epoch * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="sch-board" :style="{ '--sch-right-w': layout.sizes.schedulerRightW + 'px' }">
    <div class="sch-main">
      <div class="sch-toolbar">
        <span class="group-title">运行看板</span>
        <span v-if="scheduler.snapshot?.boot_report?.jobs" class="badge WARN"
              title="进程重启时有在飞段作业被标 INTERRUPTED, 相关批次待人工对账">
          重启对账: {{ scheduler.snapshot.boot_report.jobs }} 段中断
        </span>
        <span class="muted sch-sync">{{ scheduler.error ? scheduler.error : (scheduler.lastSyncAt ? `已同步 ${Math.round((Date.now() - scheduler.lastSyncAt) / 1000)}s 前` : '同步中…') }}</span>
        <button class="mini" @click="scheduler.loadSnapshot()">⟳ 刷新</button>
        <button class="mini" @click="router.push('/experiment/submit')">＋ 新建实验</button>
      </div>

      <p v-if="!batches.length" class="empty">
        暂无活动批次。点「＋ 新建实验」提交批量样品; 历史批次在左侧列表。
      </p>

      <!-- 样品×段 流水线矩阵 (每批一组) -->
      <div v-for="b in batches" :key="b.batch_id" class="sch-batch">
        <div class="sch-batch-head">
          <span class="badge" :class="b.status">{{ b.status }}</span>
          <button type="button" class="btn-bare sch-batch-title" :title="b.batch_id"
                  @click="router.push(`/experiment/batch/${b.batch_id}`)">{{ b.name || b.batch_id }}</button>
          <small class="muted num">{{ b.sample_done }}/{{ b.sample_total }} 完成</small>
          <span v-if="b.needs_reconcile" class="badge ERROR" title="重启/中止后待人工对账 (进批次详情处理)">待对账</span>
        </div>
        <div class="sch-grid-scroll">
          <table class="sch-grid">
            <tbody>
              <!-- 批级段行 (af0 批次起手等): 一批一次, 不属于任何样品 -->
              <tr v-if="(b.batch_jobs || []).length">
                <th class="sch-sample">
                  <span class="sch-sample-id muted">批级段</span>
                </th>
                <td>
                  <div class="sch-chips">
                    <span v-for="j in b.batch_jobs" :key="j.flow_id" class="sch-chip"
                          :class="chipStateOf(j.status).cls"
                          :title="`${j.flow_id} · ${j.script} · ${j.status}${j.wait ? ' · ' + waitReasonText(j.wait) : ''}${j.message ? ' · ' + j.message : ''}`">
                      <span class="sch-chip-id">{{ shortSegLabel(j.label) || j.flow_id }}</span>
                      <span class="sch-chip-st">{{ chipStateOf(j.status).label }}</span>
                    </span>
                  </div>
                </td>
              </tr>
              <tr v-for="s in b.samples" :key="s.sample_id">
                <th class="sch-sample" :title="`位置: ${s.position || '?'}${s.tank ? ' · 缸' + s.tank : ''} · ${s.status}`">
                  <span class="sch-sample-id">{{ s.sample_id }}</span>
                  <small class="sch-sample-pos">{{ s.position || '—' }}{{ s.tank ? ` · 缸${s.tank}` : '' }}</small>
                </th>
                <td>
                  <div class="sch-chips">
                    <button v-for="j in s.jobs" :key="j.flow_id" type="button" class="sch-chip"
                            :class="[chipStateOf(j.status).cls, { picked: picked && picked.sample?.sample_id === s.sample_id && picked.job?.flow_id === j.flow_id }]"
                            :title="`${j.flow_id} · ${j.script} · ${j.status}${j.wait ? ' · ' + waitReasonText(j.wait) : ''}${j.message ? ' · ' + j.message : ''}`"
                            @click="pick(b.batch_id, s, j)">
                      <span class="sch-chip-id">{{ shortSegLabel(j.label) || j.flow_id }}</span>
                      <span class="sch-chip-st">{{ chipStateOf(j.status).label }}</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 资源占用 + 缸池 -->
      <div v-if="batches.length" class="sch-res">
        <div class="group-title">资源占用</div>
        <div class="sch-res-rows">
          <span v-for="r in resourceRows" :key="r.id" class="sch-res-chip"
                :title="`${r.id} · 持有者 ${r.holder}${r.elapsed ? ' · 已持 ' + r.elapsed : ''}`">
            {{ r.label }} ← <b>{{ r.holder }}</b><small v-if="r.elapsed" class="num"> {{ r.elapsed }}</small>
          </span>
          <span v-if="!resourceRows.length" class="muted">全部空闲</span>
          <span class="sch-tanks num" :title="Object.entries(scheduler.tanks).map(([t, o]) => `缸${t}: ${o || '空'}`).join('\n')">
            缸池 {{ tankRows.filter((t) => t.owner).length }}/{{ tankRows.length }} 占用
          </span>
          <span v-for="(owner, name) in scheduler.occupancy" :key="name">
            <span v-if="owner" class="sch-res-chip warn" :title="`跨段占位: ${name} 被 ${owner} 占用 (收集段取走后释放)`">{{ name }} ← <b>{{ owner }}</b></span>
          </span>
        </div>
      </div>

      <!-- 实际执行时间线 (readonly 甘特 + 当前时刻线) -->
      <div v-if="ganttBatch" class="sch-gantt">
        <button type="button" class="btn-bare group-title clickable" :aria-expanded="showGantt"
                @click="showGantt = !showGantt">
          <span class="chev">{{ showGantt ? '▾' : '▸' }}</span>实际时间线 ({{ ganttBatch.name || ganttBatch.batch_id }})
          <span class="muted sch-zoom" @click.stop>
            <button class="mini" @click="pxPerSec = Math.min(8, pxPerSec * 1.5)">＋</button>
            <button class="mini" @click="pxPerSec = Math.max(0.05, pxPerSec / 1.5)">－</button>
          </span>
        </button>
        <div v-show="showGantt" class="sch-gantt-body">
          <GanttChart :placements="gantt.placements" :samples="gantt.samples"
                      :px-per-sec="pxPerSec" :makespan-s="gantt.makespan"
                      :now-s="gantt.nowS" readonly @select="onGanttSelect" />
        </div>
      </div>
    </div>

    <!-- 右栏: 选中段作业详情 -->
    <aside class="sch-right">
      <div v-if="!picked" class="empty">点击左侧任一段 chip 查看详情与恢复动词</div>
      <div v-else>
        <div class="sch-job-head">
          <b>{{ picked.sample.sample_id }}</b> · {{ shortSegLabel(picked.job.label) || picked.job.flow_id }}
          <small class="muted num">({{ picked.job.flow_id }})</small>
          <span class="badge" :class="picked.job.status">{{ picked.job.status }}</span>
        </div>
        <table class="kv">
          <tbody>
            <tr><td>脚本</td><td>{{ picked.job.script }}</td></tr>
            <tr><td>运行</td><td>
              <router-link v-if="picked.job.run_id" :to="`/runs/${picked.job.run_id}`">{{ picked.job.run_id }}</router-link>
              <span v-else class="muted">未派发</span>
            </td></tr>
            <tr><td>起止</td><td class="num">{{ fmtClock(picked.job.started_at) }} → {{ fmtClock(picked.job.finished_at) }}</td></tr>
            <tr v-if="picked.job.wait"><td>等待</td><td>{{ waitReasonText(picked.job.wait) }}</td></tr>
            <tr v-if="picked.job.failed_step"><td>断点</td><td class="num">{{ picked.job.failed_step }}</td></tr>
            <tr v-if="picked.job.message"><td>消息</td><td>{{ picked.job.message }}</td></tr>
          </tbody>
        </table>
        <div class="sch-verbs">
          <button v-if="['ERROR', 'INTERRUPTED', 'CANCELLED'].includes(picked.job.status)"
                  class="mini" @click="jobAct('retry')">整段重试</button>
          <button v-if="['ERROR', 'INTERRUPTED'].includes(picked.job.status) && picked.job.failed_step"
                  class="mini" @click="jobAct('resume')">断点续跑</button>
          <button v-if="!['DONE', 'SKIPPED'].includes(picked.job.status)"
                  class="mini" @click="jobAct('skip')">跳过</button>
          <button v-if="!['DONE', 'SKIPPED'].includes(picked.job.status)"
                  class="mini" @click="jobAct('mark_done')">标记完成</button>
          <button v-if="picked.sample.status === 'ACTIVE'" class="mini" @click="sampleAct('hold')">暂停样品</button>
          <button v-if="picked.sample.status === 'HOLD'" class="mini ok" @click="sampleAct('resume')">恢复样品</button>
          <button v-if="!['DONE', 'ABORTED'].includes(picked.sample.status)"
                  class="mini danger" @click="sampleAct('abort')">终止样品</button>
        </div>
        <p v-if="verbErr" class="empty err">{{ verbErr }}</p>
        <div class="group-title">步骤树</div>
        <StepTree v-if="pickedLive" :steps="pickedLive.steps" />
        <StepTree v-else-if="pickedReplay" :steps="pickedReplay.steps" />
        <p v-else class="empty">{{ picked.job.run_id ? '回放加载中/无记录' : '该段尚未运行' }}</p>
      </div>
    </aside>
    <Splitter skey="schedulerRightW" dir="x" :sign="-1" class="sch-seam" />
  </div>
</template>

<style scoped>
.sch-board { display: grid; grid-template-columns: 1fr var(--sch-right-w); height: 100%; position: relative; }
.sch-main { overflow: auto; padding: 10px 12px; min-width: 0; }
.sch-right { border-left: 1px solid var(--border); padding: 10px 12px; overflow: auto; }
.sch-seam { position: absolute; top: 0; bottom: 0; right: calc(var(--sch-right-w) - 5px); width: 10px; }

.sch-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.sch-sync { margin-left: auto; font-size: var(--fs-11); }

.sch-batch { margin-bottom: 12px; border: 1px solid var(--border); border-radius: 8px; padding: 8px; }
.sch-batch-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.sch-batch-title { font-weight: 600; cursor: pointer; }
.sch-batch-title:hover { text-decoration: underline; }

.sch-grid-scroll { overflow-x: auto; }
.sch-grid { border-collapse: collapse; width: 100%; }
.sch-sample { text-align: left; padding: 4px 10px 4px 0; white-space: nowrap; vertical-align: top; width: 130px; }
.sch-sample-id { display: block; font-weight: 600; font-size: var(--fs-12); }
.sch-sample-pos { display: block; color: var(--muted); font-size: 10px; }
.sch-chips { display: flex; flex-wrap: wrap; gap: 4px; padding: 2px 0; }
.sch-chip {
  display: inline-flex; flex-direction: column; align-items: center; min-width: 44px;
  border: 1px solid var(--border); border-radius: 6px; padding: 2px 6px;
  background: var(--surface-2); cursor: pointer; font-size: var(--fs-11); line-height: 1.25;
}
.sch-chip-id { font-weight: 600; }
.sch-chip-st { font-size: 10px; color: var(--muted); }
.sch-chip.picked { outline: 2px solid var(--accent); }
.sch-chip.running { border-color: var(--warn); background: color-mix(in srgb, var(--warn) 12%, var(--surface-2)); animation: pulse 1.4s ease-in-out infinite; }
.sch-chip.human { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, var(--surface-2)); }
.sch-chip.done { border-color: var(--ok); }
.sch-chip.done .sch-chip-st { color: var(--ok); }
.sch-chip.failed { border-color: var(--bad); }
.sch-chip.failed .sch-chip-st { color: var(--bad); }
.sch-chip.skipped { opacity: 0.55; }

.sch-res { margin: 10px 0; }
.sch-res-rows { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.sch-res-chip { border: 1px solid var(--warn); border-radius: 999px; padding: 2px 8px; font-size: var(--fs-11); }
.sch-res-chip.warn { border-color: var(--bad); }
.sch-tanks { margin-left: auto; color: var(--muted); font-size: var(--fs-11); }

.sch-gantt-body { height: 260px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.sch-zoom { margin-left: 8px; }
.sch-job-head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
.sch-verbs { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.chev { display: inline-block; width: 1em; color: var(--muted); }
.empty.err { color: var(--bad); }
</style>
