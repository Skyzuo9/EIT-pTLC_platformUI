<script setup>
// 调度编排器: 三层里的"调度"层编辑器 —— 段(流程)怎么组合、谁能和谁并行, 都在这里画出来。
//
// 结构化为主路 (画布 + 右栏表单, 走 /api/recipes/{name}/doc), 文本页签为高级路
// (原文 YAML, 保 # 注释, 走 .../raw)。两路都是"后端全链静态校验通过才落盘",
// 且被未完结批次引用的方案后端拒改 (409) —— 运行期按名重读方案, 半路换定义会与已落库段作业失配。
//
// doc 是本组件唯一写入口 (画布只 emit): 便于脏标记与整体 PUT。
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errText } from '../../api.js'
import { announce } from '../../composables/announcer.js'
import { confirmAction, promptAction } from '../../composables/confirmService.js'
import { useDirtyGuard } from '../../composables/useDirtyGuard.js'
import { useEditorStore } from '../../stores/editor'
import { useLayoutStore } from '../../stores/layout'
import { useSchedulerStore } from '../../stores/scheduler'
import { nextSegId } from '../../utils/dagLayout.js'
import { parallelPairs, shortSegLabel } from '../../utils/scheduler.js'
import CodeEditor from '../CodeEditor.vue'
import Splitter from '../Splitter.vue'
import DagCanvas from './DagCanvas.vue'
import SegmentPanel from './SegmentPanel.vue'

const props = defineProps({ name: { type: String, required: true } })
const router = useRouter()
const editor = useEditorStore()
const layout = useLayoutStore()
const scheduler = useSchedulerStore()

const tab = ref('canvas')        // canvas | text
const doc = ref(null)
const savedJson = ref('')        // 最近一次落盘/加载时的 doc 快照 (脏判据)
const text = ref('')             // 文本页签原文
const savedText = ref('')
const rawHasComments = ref(false) // 磁盘原文里有 # 注释 -> 首次结构化保存要告知会丢
const loadErr = ref('')
const opErr = ref('')
const busy = ref(false)
const checked = ref(null)        // 最近一次干跑校验 {ok, errors, recipe}
const selected = ref('')         // 选中段 id
const selectedEdge = ref(null)   // 选中边 {from, to}

const docDirty = computed(() => !!doc.value && JSON.stringify(doc.value) !== savedJson.value)
const textDirty = computed(() => text.value !== savedText.value)
const dirty = computed(() => (tab.value === 'text' ? textDirty.value : docDirty.value))
const { confirmDiscard } = useDirtyGuard(dirty, {
  message: '当前调度方案有未保存修改, 离开将丢弃。', paramKey: 'name',
})

// 段库 (调色板与右栏下拉共用): 流程树里 ui.role==='segment' 的流程
const segments = computed(() =>
  editor.operations.filter((s) => s.ui && s.ui.role === 'segment'))

// 段脚本元数据 (卡片展示 label/hitl/位置): 校验干净时用后端 DTO, 否则退回摘要 label
const meta = computed(() => {
  const out = {}
  for (const s of editor.operations) out[s.name] = { label: s.label }
  for (const seg of checked.value?.recipe?.segments || []) {
    out[seg.op] = { label: seg.label, hitl: seg.hitl, from: seg.from, to: seg.to }
  }
  return out
})

// 段流程的 in/out 变量 (摘要不含 vars, 按需取全 doc 并缓存)
const varsCache = ref({})
function varsOf(script) {
  if (!script) return []
  if (varsCache.value[script] === undefined) {
    varsCache.value[script] = null                 // 占位, 防重复请求
    // GET /api/scripts/{name} 直接返回 doc 本身 (repo.get)
    api.getScript(script)
      .then((d) => { varsCache.value = { ...varsCache.value, [script]: d?.vars || [] } })
      .catch(() => { varsCache.value = { ...varsCache.value, [script]: [] } })
  }
  return varsCache.value[script] || []
}

async function load() {
  loadErr.value = ''
  opErr.value = ''
  checked.value = null
  selected.value = ''
  selectedEdge.value = null
  try {
    const res = await api.getRecipeDoc(props.name)
    doc.value = res.doc
    savedJson.value = JSON.stringify(res.doc)
    validate()                                     // 一进来就给出层级/并行摘要
  } catch (e) {
    doc.value = null
    loadErr.value = errText(e)
  }
  try {
    const raw = await api.getRecipeRaw(props.name)
    text.value = raw.text
    savedText.value = raw.text
    rawHasComments.value = /^\s*#/m.test(raw.text)
  } catch { /* 文本页签取不到不阻塞画布 */ }
}
watch(() => props.name, load, { immediate: true })

// ---- doc 编辑 (画布/右栏的唯一写入口) ----
function touch() {
  checked.value = null            // 结构变了, 旧校验结果作废
}
function addEdge({ from, to }) {
  const f = doc.value.flows.find((x) => x.id === to)
  if (!f) return
  ;(f.depends_on || (f.depends_on = [])).push(from)
  touch()
  announce(`${to} 现在依赖 ${from}`)
}
function removeEdge({ from, to }) {
  const f = doc.value.flows.find((x) => x.id === to)
  const deps = f?.depends_on || []
  const i = deps.indexOf(from)
  if (i >= 0) deps.splice(i, 1)
  selectedEdge.value = null
  touch()
}
async function removeNode(id) {
  const f = doc.value.flows.find((x) => x.id === id)
  if (!f) return
  const refs = doc.value.flows.filter((x) => (x.depends_on || []).includes(id)).map((x) => x.id)
  if (!(await confirmAction({
    title: `从方案里移除段 ${id}`,
    message: refs.length
      ? `将同时解除 ${refs.join(', ')} 对它的依赖 (这些段会提前变为可派发, 注意位置连续性)。`
      : '该段不再属于本方案 (流程本身仍在流程库里, 不受影响)。',
    confirmText: '移除',
  }))) return
  doc.value.flows = doc.value.flows.filter((x) => x.id !== id)
  for (const other of doc.value.flows) {
    const deps = other.depends_on || []
    const i = deps.indexOf(id)
    if (i >= 0) deps.splice(i, 1)
  }
  if (selected.value === id) selected.value = ''
  touch()
}
function addSegment(script) {
  if (!script || !doc.value) return
  const id = nextSegId(doc.value.flows)
  // 新段先落成孤立节点 (第 0 层), 由工程师拖线连入 —— 不猜依赖
  doc.value.flows.push({ id, script, scope: 'sample', depends_on: [] })
  selected.value = id
  selectedEdge.value = null
  touch()
  announce(`已添加段 ${id}, 从卡片下端口拖线连出依赖`)
}

// ---- 校验 / 保存 ----
async function validate() {
  if (!doc.value) return
  busy.value = true
  opErr.value = ''
  try {
    checked.value = await api.validateRecipeDoc(doc.value)
  } catch (e) {
    opErr.value = errText(e)
    checked.value = null
  } finally {
    busy.value = false
  }
}
async function save() {
  if (tab.value === 'text') return saveText()
  if (rawHasComments.value && !(await confirmAction({
    title: '结构化保存会丢弃原文注释',
    message: `${props.name}.yaml 里的 # 注释在结构化保存后会被规范化输出取代 (段结构与接线一字不差保留)。`
      + ' 要保留注释, 改用「文本」页签编辑。',
    confirmText: '继续保存',
  }))) return
  busy.value = true
  opErr.value = ''
  try {
    await api.saveRecipeDoc(props.name, doc.value)
    savedJson.value = JSON.stringify(doc.value)
    rawHasComments.value = false
    scheduler.loadRecipes().catch(() => {})   // 实验提交页下拉/段清单跟上新定义
    const raw = await api.getRecipeRaw(props.name).catch(() => null)
    if (raw) { text.value = raw.text; savedText.value = raw.text }
    validate()
    announce('调度方案已保存')
  } catch (e) {
    opErr.value = errText(e)
  } finally {
    busy.value = false
  }
}
async function saveText() {
  busy.value = true
  opErr.value = ''
  try {
    await api.saveRecipeRaw(props.name, text.value)
    savedText.value = text.value
    rawHasComments.value = /^\s*#/m.test(text.value)
    scheduler.loadRecipes().catch(() => {})
    const res = await api.getRecipeDoc(props.name).catch(() => null)
    if (res) { doc.value = res.doc; savedJson.value = JSON.stringify(res.doc) }
    validate()
    announce('调度方案已保存 (原文)')
  } catch (e) {
    opErr.value = errText(e)
  } finally {
    busy.value = false
  }
}
async function saveAs() {
  const next = await promptAction({
    title: '另存为新调度方案',
    initial: `${props.name}_copy`,
    validate: (v) => (/^[A-Za-z0-9_-]+$/.test(v.trim()) ? '' : '方案名仅限字母/数字/下划线/连字符'),
  })
  if (next === null) return
  const target = next.trim()
  busy.value = true
  opErr.value = ''
  try {
    if (tab.value === 'text') {
      await api.saveRecipeRaw(target, text.value.replace(/^name:\s*\S+\s*$/m, `name: ${target}`))
      savedText.value = text.value
    } else {
      await api.saveRecipeDoc(target, { ...doc.value, name: target })
      savedJson.value = JSON.stringify(doc.value)
    }
    scheduler.loadRecipes().catch(() => {})
    router.push(`/schedule/${target}`)
  } catch (e) {
    opErr.value = errText(e)
  } finally {
    busy.value = false
  }
}

// 页签切换: 两边各自有未保存改动时先过放弃门 (不做双向实时同步 —— 会互相盖写)
async function switchTab(next) {
  if (next === tab.value) return
  if (dirty.value && !(await confirmDiscard(
    '切换编辑方式会重载另一侧的内容, 当前未保存修改将丢弃。'))) return
  if (dirty.value) await load()
  tab.value = next
}

const pairsText = computed(() => {
  const segs = checked.value?.recipe?.segments
  if (!segs) return ''
  const pairs = parallelPairs(segs)
  return pairs.length
    ? '可并行: ' + pairs.map((p) => p.map(shortSegLabel).join('∥')).join('、')
    : '全链式 (段间零并行)'
})
</script>

<template>
  <div class="so">
    <div class="so-head">
      <button class="mini" @click="router.push('/schedule')">← 方案列表</button>
      <span class="group-title">{{ doc?.label || name }}</span>
      <small class="muted num">{{ name }}</small>
      <span v-if="dirty" class="badge WARN" title="有未保存修改">未保存</span>
      <span class="so-tabs" role="tablist" aria-label="编辑方式">
        <button class="mini" role="tab" :aria-selected="tab === 'canvas'"
                :class="{ active: tab === 'canvas' }" @click="switchTab('canvas')">画布</button>
        <button class="mini" role="tab" :aria-selected="tab === 'text'"
                :class="{ active: tab === 'text' }" @click="switchTab('text')"
                title="原文 YAML (保留 # 注释); 高级用法">文本</button>
      </span>
      <span class="so-btns">
        <select v-if="tab === 'canvas'" class="so-add" aria-label="添加段"
                :disabled="busy || !doc" @change="addSegment($event.target.value); $event.target.value = ''">
          <option value="">＋ 添加段…</option>
          <option v-for="s in segments" :key="s.name" :value="s.name">
            {{ shortSegLabel(s.label) || s.name }}
          </option>
        </select>
        <button class="mini" :disabled="busy || !doc" @click="validate">校验</button>
        <button class="mini" :disabled="busy || !dirty" @click="save">保存</button>
        <button class="mini" :disabled="busy" @click="saveAs">另存为…</button>
      </span>
    </div>

    <p v-if="loadErr" class="empty err">{{ loadErr }}</p>
    <template v-else>
      <!-- 画布 + 右栏 -->
      <div v-if="tab === 'canvas'" class="so-mid"
           :style="{ '--so-right-w': layout.sizes.scheduleRightW + 'px' }">
        <div class="so-canvas">
          <DagCanvas v-if="doc" :flows="doc.flows" :meta="meta" :selected="selected"
                     :selected-edge="selectedEdge"
                     @select="selected = $event" @select-edge="selectedEdge = $event"
                     @add-edge="addEdge" @remove-edge="removeEdge" @remove-node="removeNode" />
        </div>
        <div class="so-right">
          <SegmentPanel v-if="doc" :doc="doc" :selected="selected" :segments="segments"
                        :vars-of="varsOf" @touch="touch" @select="selected = $event" />
        </div>
        <Splitter skey="scheduleRightW" dir="x" :sign="-1" />
      </div>

      <!-- 文本页签 -->
      <div v-else class="so-text">
        <CodeEditor v-model="text" lang="yaml" label="调度方案 YAML 编辑器" />
      </div>

      <!-- 底部状态条: 校验结果 / 层级摘要 / 操作错误 -->
      <div class="so-foot">
        <pre v-if="opErr" class="so-errors">{{ opErr }}</pre>
        <template v-if="checked">
          <p v-if="checked.ok" class="so-ok">
            ✓ 校验通过 · {{ checked.recipe.segments.length }} 段 · {{ pairsText }}
          </p>
          <pre v-else class="so-errors">{{ checked.errors.join('\n') }}</pre>
        </template>
        <p v-else-if="!opErr" class="muted so-hint">
          结构已改动, 点「校验」看层级与并行结果; 保存前后端会再全链校验一次。
        </p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.so { height: 100%; display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; overflow: hidden; }
.so-head { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.so-tabs { display: flex; gap: 4px; margin-left: 8px; }
.so-tabs .mini.active { border-color: var(--accent, #58a); color: var(--accent, #58a); }
.so-btns { margin-left: auto; display: flex; gap: 6px; align-items: center; }
.so-add { max-width: 180px; }
.so-mid { position: relative; flex: 1 1 auto; min-height: 0; display: grid;
          grid-template-columns: minmax(0, 1fr) var(--so-right-w); }
.so-canvas { min-width: 0; border: 1px solid var(--border, #4443); border-radius: 4px; overflow: hidden; }
.so-right { min-width: 0; border: 1px solid var(--border, #4443); border-left: 0;
            border-radius: 0 4px 4px 0; overflow: hidden; }
.so-text { flex: 1 1 auto; min-height: 0; overflow: auto;
           border: 1px solid var(--border, #4443); border-radius: 4px; }
.so-foot { flex: 0 0 auto; max-height: 150px; overflow: auto; }
.so-foot > * { margin: 0; }
.so-ok { color: var(--ok, #2a2); }
.so-errors { white-space: pre-wrap; color: var(--danger, #d33); font-size: var(--fs-12, 12px); }
</style>
