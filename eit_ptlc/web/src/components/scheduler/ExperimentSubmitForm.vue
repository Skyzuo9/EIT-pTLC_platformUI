<script setup>
// 实验提交表单: 调度方案 -> 工艺参数 (旋钮并集按段分组) -> 样品数/ID -> 逐样品覆盖 -> 运行选项
// -> 预估时间线 (复用离线排程贪心) -> 确认门 (如实告知) -> 提交
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import GanttChart from '../planner/GanttChart.vue'
import { useSchedulerStore } from '../../stores/scheduler'
import { usePlannerStore } from '../../stores/planner'
import { confirmAction } from '../../composables/confirmService.js'
import { errText } from '../../api.js'
import { validateValue, toDisplay, toRaw } from '../../utils/runInputs.js'
import { aggregateKnobs, buildOverridesPayload, buildSubmitSummary, collectChangedParams,
         genSampleIds, parallelPairs, shortSegLabel } from '../../utils/scheduler.js'
import { buildDurationIndex, scheduleGreedy } from '../../utils/planner.js'

const DRAFT_KEY = 'ptlc.scheduler.submitDraft.v1'   // 只存表单草稿, 不存任何运行状态

const scheduler = useSchedulerStore()
const planner = usePlannerStore()
const router = useRouter()

const draft = reactive({
  recipe: '',
  params: {},          // knobName -> 原始字符串 (显示值; scale 换算在收集时做)
  sampleCount: 2,
  idPrefix: defaultPrefix(),
  overrides: [],       // 逐样品 [{knobName: raw}]
  overrideCols: [],    // 已启用的覆盖列
  autoDrain: true,
  wipLimit: null,
  tankSubset: [],
  priority: 0,
  note: '',
})
const submitErr = ref('')
const okMsg = ref('')

function defaultPrefix() {
  const d = new Date()
  return `B${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
}

// 草稿回填 (knobs 到位无关: 参数字符串按名存取)
try {
  const saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null')
  if (saved && typeof saved === 'object') Object.assign(draft, saved)
} catch { /* 草稿损坏即弃 */ }
watch(draft, () => {
  try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)) } catch { /* 满/禁用即弃 */ }
}, { deep: true })

const recipe = computed(() => scheduler.recipes.find((r) => r.name === draft.recipe) || null)
watch(() => scheduler.recipes, (list) => {
  // 默认选配置默认方案 (default 标) 而非列表第一个 —— 字母序会让冒烟方案排最前
  if (!draft.recipe && list.length) draft.recipe = (list.find((r) => r.default) || list[0]).name
}, { immediate: true })
watch(recipe, (r) => { if (r) scheduler.loadRecipeKnobs(r) }, { immediate: true })

// 段间并行提示: 从选中方案的 DAG 推导 (方案即"谁能并行"的定义处, 不硬编码具体方案内容)
const segPairsText = computed(() => {
  const pairs = parallelPairs(recipe.value?.segments || [])
  if (!pairs.length) return '全链式 (段间零并行, 逐段顺序执行)'
  return '依赖上可并行: ' + pairs.map((p) => p.map(shortSegLabel).join('∥')).join('、')
    + ' — 实际重叠由调度器按资源裁定'
})

// 旋钮聚合 (并集归首段) 与索引
const agg = computed(() => aggregateKnobs(recipe.value?.segments || [], scheduler.knobsByOp))
const knobIndex = computed(() => {
  const idx = {}
  for (const g of agg.value.groups) for (const k of g.knobs) idx[k.name] = k
  return idx
})

// 逐格校验 (scale 皮肤: 输入框吃显示值, 校验按显示范围)
function knobError(k, raw) {
  if (raw == null || String(raw).trim() === '') return ''
  const scale = k.ui && k.ui.scale
  if (scale) {
    const rawVal = toRaw(raw, scale, k.ui.min, k.ui.max)
    return rawVal == null ? '数值非法或超出范围' : ''
  }
  return validateValue(k.type, raw, k.ui)
}
const paramErrors = computed(() => {
  let n = 0
  for (const [name, raw] of Object.entries(draft.params)) {
    const k = knobIndex.value[name]
    if (k && knobError(k, raw)) n += 1
  }
  return n
})

// 收集载荷: 显示值 -> 原始值 (scale 反算), 只发改动项
function collectParams() {
  const display = {}
  for (const [name, raw] of Object.entries(draft.params)) {
    if (raw == null || String(raw).trim() === '') continue
    const k = knobIndex.value[name]
    const scale = k && k.ui && k.ui.scale
    display[name] = scale ? String(toRaw(raw, scale, k.ui.min, k.ui.max)) : raw
  }
  return collectChangedParams(display, knobIndex.value)
}

// 样品 ID 预览 (最终以后端响应为准) + 覆盖表行随数量对齐 (按下标保留已填)
const sampleIds = computed(() => genSampleIds(draft.idPrefix || 'B', draft.sampleCount || 0))
watch(() => draft.sampleCount, (n) => {
  const rows = draft.overrides.slice(0, n)
  while (rows.length < n) rows.push({})
  draft.overrides = rows
}, { immediate: true })

const prefixError = computed(() => {
  const p = String(draft.idPrefix || '')
  if (!p) return 'ID 前缀不能为空'
  if (!/^[A-Za-z0-9_-]{1,24}$/.test(p)) return '仅限字母数字_-'
  return ''
})

// 预估时间线: 离线排程贪心 (计划块; 段无历史耗时时按 60s 估计虚线)
const est = computed(() => {
  if (!recipe.value || !planner.stats) return null
  const chain = recipe.value.segments.filter((s) => s.scope === 'sample').map((s) => s.op)
  const samples = sampleIds.value.map((id) => ({ id, label: id, chain }))
  const durationIndex = buildDurationIndex(planner.stats, planner.plan.settings.durationMode)
  const modes = {}
  for (const r of planner.stats.resources || []) modes[r.id] = r.mode
  const { placements, makespan_s: makespanS } = scheduleGreedy(samples, durationIndex, modes)
  return { placements, makespanS, samples }
})
planner.ensureStats()

async function submit() {
  submitErr.value = ''
  okMsg.value = ''
  if (prefixError.value || paramErrors.value) return
  const params = collectParams()
  const summary = buildSubmitSummary(draft, recipe.value, sampleIds.value, Object.keys(params).length)
  const ok = await confirmAction({ title: '提交批量实验', message: summary, level: 'danger',
                                   confirmText: '提交批次' })
  if (!ok) return
  try {
    const res = await scheduler.submitExperiment({
      recipe: draft.recipe,
      name: draft.note || `${recipe.value?.label || draft.recipe} x${draft.sampleCount}`,
      sample_count: draft.sampleCount,
      id_prefix: draft.idPrefix,
      params,
      per_sample_overrides: draft.overrideCols.length
        ? buildOverridesPayload(draft.overrides, knobIndex.value) : [],
      auto_drain: draft.autoDrain,
      wip_limit: draft.wipLimit || null,
      tank_subset: draft.tankSubset.length ? draft.tankSubset : null,
      priority: Number(draft.priority) || 0,
      note: draft.note,
    })
    okMsg.value = `批次 ${res.batch_id} 已提交 (${res.sample_ids.length} 样品, 排队中)`
    router.push(`/experiment/batch/${res.batch_id}`)
  } catch (e) {
    submitErr.value = errText(e)
  }
}

function toggleTank(t) {
  const i = draft.tankSubset.indexOf(t)
  if (i >= 0) draft.tankSubset.splice(i, 1)
  else draft.tankSubset.push(t)
}
function addOverrideCol(name) {
  if (name && !draft.overrideCols.includes(name)) draft.overrideCols.push(name)
}
</script>

<template>
  <div class="sub-form">
    <div class="sub-head">
      <span class="group-title">新建并行实验</span>
      <button class="mini" @click="router.push('/experiment')">← 返回看板</button>
    </div>

    <!-- 1. 调度方案 (段清单 = 全流程总览: 序号+中文短名, 悬停看停放位/依赖/HITL) -->
    <section>
      <h4>1. 调度方案</h4>
      <div class="row-line">
        <select v-model="draft.recipe">
          <option v-for="r in scheduler.recipes" :key="r.name" :value="r.name">{{ r.label }} ({{ r.name }})</option>
        </select>
        <router-link v-if="draft.recipe" class="mini" :to="`/schedule/${draft.recipe}`"
                     title="到调度栏用画布改段组合与并行结构">编排…</router-link>
      </div>
      <div v-if="recipe" class="seg-list">
        <span v-for="s in recipe.segments" :key="s.id" class="seg-chip"
              :title="`${s.id} · ${s.op}\n${s.from || ''} → ${s.to || ''}\n依赖: ${s.depends_on.join(', ') || '无'}${s.hitl === 'confirm' ? '\n含人工门' : ''}`">
          {{ shortSegLabel(s.label) || s.id
          }}<small v-if="s.hitl === 'confirm'" title="可能等待人工确认">👤</small>
        </span>
      </div>
      <p v-if="recipe" class="muted seg-hint">共 {{ recipe.segments.length }} 段;
        {{ segPairsText }}; 依赖见段悬停提示</p>
    </section>

    <!-- 2. 工艺参数 (旋钮并集, 按段分组, 全段列出; 留空 = 用流程声明默认) -->
    <section>
      <h4>2. 工艺参数 <small class="muted">(留空即用默认; 同名旋钮全方案同值)</small></h4>
      <div v-for="g in agg.groups" :key="g.id" class="knob-group">
        <div class="knob-group-title">{{ shortSegLabel(g.label) || g.label }}
          <small v-if="!g.knobs.length" class="muted"> — 本段无可调工艺参数 (仍在流程中执行)</small>
        </div>
        <div v-for="k in g.knobs" :key="k.name" class="knob-row">
          <label :title="k.name">{{ (k.ui && k.ui.label) || k.name }}</label>
          <select v-if="k.ui && k.ui.enum" v-model="draft.params[k.name]">
            <option value="">(默认 {{ k.default }})</option>
            <option v-for="opt in k.ui.enum" :key="opt" :value="String(opt)">{{ opt }}</option>
          </select>
          <select v-else-if="k.type === 'BOOL'" v-model="draft.params[k.name]">
            <option value="">(默认 {{ k.default }})</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
          <input v-else v-model="draft.params[k.name]"
                 :placeholder="k.ui && k.ui.scale ? String(toDisplay(k.default, k.ui.scale) ?? '') : String(k.default ?? '')" />
          <small v-if="agg.reuse[k.name]" class="muted" :title="`亦作用于: ${agg.reuse[k.name].join('、')} (覆盖按名注入, 同名即同值)`">共用</small>
          <small class="err-inline">{{ knobError(k, draft.params[k.name]) }}</small>
        </div>
      </div>
      <p v-if="!agg.groups.length" class="empty">方案段加载中…</p>
    </section>

    <!-- 3. 样品 -->
    <section>
      <h4>3. 样品</h4>
      <div class="row-line">
        <label>数量</label>
        <input type="number" min="1" max="24" v-model.number="draft.sampleCount" class="w-s num" />
        <label>ID 前缀</label>
        <input v-model="draft.idPrefix" class="w-m" />
        <small class="err-inline">{{ prefixError }}</small>
      </div>
      <div class="seg-list">
        <span v-for="id in sampleIds" :key="id" class="seg-chip num">{{ id }}</span>
        <small class="muted">(预览; 最终以后端返回为准, 重名会被 409 拒绝)</small>
      </div>
    </section>

    <!-- 4. 逐样品覆盖 (可选) -->
    <section>
      <h4>4. 逐样品覆盖 <small class="muted">(留空格 = 继承批级)</small></h4>
      <div class="row-line">
        <select @change="addOverrideCol($event.target.value); $event.target.value = ''">
          <option value="">＋ 添加覆盖列…</option>
          <option v-for="(k, name) in knobIndex" :key="name" :value="name"
                  :disabled="draft.overrideCols.includes(name)">{{ (k.ui && k.ui.label) || name }}</option>
        </select>
      </div>
      <table v-if="draft.overrideCols.length" class="ovr-table">
        <thead>
          <tr>
            <th>样品</th>
            <th v-for="c in draft.overrideCols" :key="c">
              {{ (knobIndex[c] && knobIndex[c].ui && knobIndex[c].ui.label) || c }}
              <button class="mini" title="移除列" @click="draft.overrideCols = draft.overrideCols.filter((x) => x !== c)">×</button>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(id, i) in sampleIds" :key="id">
            <td class="num">{{ id }}</td>
            <td v-for="c in draft.overrideCols" :key="c">
              <input v-model="draft.overrides[i][c]" :placeholder="String(draft.params[c] || knobIndex[c]?.default || '')" />
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 5. 运行选项 (串/并行的另一半: 段间结构在调度方案里, 样品间并发度在这里) -->
    <section>
      <h4>5. 运行选项</h4>
      <div class="row-line">
        <label :title="'关 = 每个样品展开完成时流水线等待人工确认排液'">
          <input type="checkbox" v-model="draft.autoDrain" /> 自动排液 (无人值守流水线)
        </label>
      </div>
      <div class="row-line">
        <label title="同时在制的样品数上限: 1 = 样品间完全串行 (一个做完再做下一个), 8 = 全并行; 留空用配置默认">样品间并发</label>
        <input type="number" min="1" max="8" v-model.number="draft.wipLimit" class="w-s num" placeholder="默认" />
        <label>优先级</label>
        <select v-model.number="draft.priority" class="w-s">
          <option :value="0">普通</option>
          <option :value="1">高</option>
          <option :value="-1">低</option>
        </select>
      </div>
      <div class="row-line">
        <label>展开缸</label>
        <label v-for="t in [1, 2, 3, 4, 5, 6, 7, 8]" :key="t" class="tank-cb num">
          <input type="checkbox" :checked="draft.tankSubset.includes(t)" @change="toggleTank(t)" />{{ t }}
        </label>
        <small class="muted">(全不选 = 全部可用缸)</small>
      </div>
      <div class="row-line">
        <label>备注</label>
        <input v-model="draft.note" class="w-l" placeholder="批次名/实验目的 (进实验记录)" />
      </div>
    </section>

    <!-- 6. 预估时间线 (离线贪心; 历史耗时缺失的段按 60s 虚线估计) -->
    <section v-if="est && est.placements.length">
      <h4>6. 预估时间线 <small class="muted num">(贪心估算, 实际以调度为准)</small></h4>
      <div class="est-gantt">
        <GanttChart :placements="est.placements" :samples="est.samples" :px-per-sec="0.35"
                    :makespan-s="est.makespanS" readonly
                    :resources-meta="planner.stats?.resources || []" />
      </div>
    </section>

    <div class="sub-actions">
      <button class="primary" :disabled="scheduler.submitting || !!prefixError || paramErrors > 0 || !recipe"
              @click="submit">
        {{ scheduler.submitting ? '提交中…' : `提交批次 (${sampleIds.length} 样品)` }}
      </button>
      <span v-if="paramErrors" class="err-inline">{{ paramErrors }} 个参数有误</span>
      <span v-if="submitErr" class="err-inline">{{ submitErr }}</span>
      <span v-if="okMsg" class="ok-inline">{{ okMsg }}</span>
    </div>
  </div>
</template>

<style scoped>
.sub-form { height: 100%; overflow: auto; padding: 12px 16px; max-width: 980px; }
.sub-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
section { margin-bottom: 16px; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
section h4 { margin: 0 0 8px; }
.seg-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; align-items: center; }
.seg-chip { border: 1px solid var(--border); border-radius: 999px; padding: 2px 9px; font-size: var(--fs-11); background: var(--surface-2); }
.seg-chip b { color: var(--accent); margin-right: 2px; }
.seg-hint { font-size: var(--fs-11); margin: 6px 0 0; }
.knob-group { margin-bottom: 8px; }
.knob-group-title { font-size: var(--fs-12); font-weight: 600; color: var(--subtle); margin: 6px 0 4px; }
.knob-row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
.knob-row label { flex: 0 0 220px; font-size: var(--fs-12); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.knob-row input, .knob-row select { width: 150px; }
.row-line { display: flex; align-items: center; gap: 8px; margin: 6px 0; flex-wrap: wrap; }
.w-s { width: 70px; } .w-m { width: 140px; } .w-l { width: 380px; }
.tank-cb { display: inline-flex; align-items: center; gap: 2px; }
.ovr-table { border-collapse: collapse; margin-top: 6px; }
.ovr-table th, .ovr-table td { border: 1px solid var(--border); padding: 3px 6px; font-size: var(--fs-12); }
.ovr-table input { width: 110px; }
.est-gantt { height: 220px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.sub-actions { display: flex; align-items: center; gap: 10px; margin: 12px 0 24px; }
.err-inline { color: var(--bad); font-size: var(--fs-12); }
.ok-inline { color: var(--ok); font-size: var(--fs-12); }
button.primary { padding: 8px 18px; font-weight: 600; }
</style>
