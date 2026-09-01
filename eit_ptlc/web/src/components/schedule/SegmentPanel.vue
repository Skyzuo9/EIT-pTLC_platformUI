<script setup>
// 调度编排器右栏: 选中段的属性/依赖/接线表单; 未选中时编方案级属性 (label/耗材)。
// 所有改动就地改 doc 对象后 emit('touch') 打脏 (照流程编辑器 ParamEditor 的 node.xxx + touch 范式)。
// 段脚本的 in/out 变量按需从 GET /api/scripts/{name} 取 (摘要不含 vars), 由壳传入 varsOf。
import { computed } from 'vue'
import { confirmAction } from '../../composables/confirmService.js'
import { shortSegLabel } from '../../utils/scheduler.js'
import { enumOf } from '../../utils/runInputs.js'

const props = defineProps({
  doc: { type: Object, required: true },
  selected: { type: String, default: '' },
  segments: { type: Array, default: () => [] },   // 可用段流程 [{name, label}] (ui.role==='segment')
  varsOf: { type: Function, required: true },     // (scriptName) -> [{name, io, type, comment}]
})
const emit = defineEmits(['touch', 'select'])

const SRC_KINDS = [
  ['ctx', '样品上下文'],
  ['batch', '批参数'],
  ['lit', '字面量'],
]

const flow = computed(() => (props.doc.flows || []).find((f) => f.id === props.selected) || null)
const others = computed(() => (props.doc.flows || []).filter((f) => f.id !== props.selected))
const inVars = computed(() => props.varsOf(flow.value?.script).filter((v) => v.io === 'in'))
// 接线行按变量名回查完整定义 (varsOf 透传的是完整 var 对象, 不是投影), 供取值域下拉用
function varDefOf(name) { return inVars.value.find((v) => v.name === name) || null }
const outVars = computed(() => props.varsOf(flow.value?.script).filter((v) => v.io === 'out'))

// 依赖勾选 (与画布连线同一份 depends_on, 双向同步): 照 ParamEditor with_resources 的 include/splice 范式
function hasDep(id) {
  return (flow.value.depends_on || []).includes(id)
}
function toggleDep(id) {
  const deps = flow.value.depends_on || (flow.value.depends_on = [])
  const i = deps.indexOf(id)
  if (i >= 0) deps.splice(i, 1)
  else deps.push(id)
  emit('touch')
}
// 成环的依赖不给勾 (画布拖线同款判据; 后端仍是最后一道)
function depWouldCycle(id) {
  const upstream = new Set()
  const walk = (fid) => {
    for (const f of props.doc.flows || []) {
      if (f.id !== fid) continue
      for (const d of f.depends_on || []) {
        if (upstream.has(d)) continue
        upstream.add(d)
        walk(d)
      }
    }
  }
  walk(id)
  return id === props.selected || upstream.has(props.selected)
}

// ---- 接线 ----
function addInput(varName) {
  if (!varName) return
  const inputs = flow.value.inputs || (flow.value.inputs = {})
  if (!inputs[varName]) inputs[varName] = { ctx: '' }
  emit('touch')
}
function srcKindOf(src) {
  return SRC_KINDS.map(([k]) => k).find((k) => k in (src || {})) || 'lit'
}
function setSrcKind(varName, kind) {
  const cur = flow.value.inputs[varName]
  const val = cur[srcKindOf(cur)]
  flow.value.inputs[varName] = { [kind]: kind === 'lit' ? val ?? '' : String(val ?? '') }
  emit('touch')
}
function setSrcValue(varName, value) {
  const kind = srcKindOf(flow.value.inputs[varName])
  flow.value.inputs[varName] = { [kind]: value }
  emit('touch')
}
function dropInput(varName) {
  delete flow.value.inputs[varName]
  if (!Object.keys(flow.value.inputs).length) delete flow.value.inputs
  emit('touch')
}
function addOutput(varName) {
  if (!varName) return
  const outputs = flow.value.outputs || (flow.value.outputs = {})
  if (!outputs[varName]) outputs[varName] = varName     // 缺省 ctx 键同名
  emit('touch')
}
function dropOutput(varName) {
  delete flow.value.outputs[varName]
  if (!Object.keys(flow.value.outputs).length) delete flow.value.outputs
  emit('touch')
}

// ---- 占位账 (逗号分隔编辑; 空则删键, 保持文件干净) ----
function listText(arr) {
  return (arr || []).join(', ')
}
function setList(key, text) {
  const items = String(text).split(',').map((s) => s.trim()).filter(Boolean)
  if (items.length) flow.value[key] = items
  else delete flow.value[key]
  emit('touch')
}
function setIngest(on) {
  if (on) flow.value.ingest_results = true
  else delete flow.value.ingest_results
  emit('touch')
}
function setScope(scope) {
  flow.value.scope = scope
  emit('touch')
}
// 段 id 就地改 (输入框 change 时提交): 连带改全部引用它的 depends_on, 否则依赖悬空
function commitId(raw) {
  const next = String(raw || '').trim()
  const cur = flow.value.id
  if (!next || next === cur) return
  if ((props.doc.flows || []).some((f) => f.id === next)) {
    emit('select', cur)     // 重名: 放弃改动 (重渲染回原值)
    return
  }
  for (const f of props.doc.flows || []) {
    const deps = f.depends_on || []
    const i = deps.indexOf(cur)
    if (i >= 0) deps.splice(i, 1, next)
  }
  flow.value.id = next
  emit('touch')
  emit('select', next)
}

async function dropConsumable(kind) {
  if (!(await confirmAction({
    title: `移除耗材种类 ${kind}`,
    message: '批次准入将不再按本方案逐样品预留该耗材。',
    confirmText: '移除',
  }))) return
  const list = props.doc.consumables
  const i = list.indexOf(kind)
  if (i >= 0) list.splice(i, 1)
  emit('touch')
}
function addConsumable(kind) {
  if (!kind) return
  const list = props.doc.consumables || (props.doc.consumables = [])
  if (!list.includes(kind)) list.push(kind)
  emit('touch')
}
const CONSUMABLE_KINDS = ['collector', 'bottle']
</script>

<template>
  <div class="sp">
    <!-- 选中某段 -->
    <template v-if="flow">
      <div class="sp-head">
        <span class="group-title">段 {{ flow.id }}</span>
        <button class="mini" title="回到方案属性" @click="emit('select', '')">方案属性</button>
      </div>

      <div class="field">
        <label :for="'sp-id'">段 id <small class="muted">(改名连带改引用)</small></label>
        <input id="sp-id" class="num" :value="flow.id" @change="commitId($event.target.value)" />
      </div>

      <div class="field">
        <label for="sp-script">流程 <small class="muted">(段库: 流程树 11_parallel 里 role=segment 的流程)</small></label>
        <select id="sp-script" :value="flow.script"
                @change="flow.script = $event.target.value; emit('touch')">
          <option value="">— 选择流程 —</option>
          <option v-for="s in segments" :key="s.name" :value="s.name">
            {{ shortSegLabel(s.label) || s.name }} ({{ s.name }})
          </option>
        </select>
      </div>

      <div class="field">
        <label for="sp-scope">作用域</label>
        <select id="sp-scope" :value="flow.scope" @change="setScope($event.target.value)">
          <option value="sample">每样品 (sample)</option>
          <option value="batch">每批次一次 (batch)</option>
        </select>
      </div>

      <div class="field"><label>依赖 <small class="muted">(勾上 = 本段等它做完; 与画布连线同一份)</small></label></div>
      <p v-if="!others.length" class="empty">方案里只有这一段</p>
      <div v-for="o in others" :key="o.id" class="sp-cb">
        <label :title="depWouldCycle(o.id) ? '会形成循环依赖' : o.script">
          <input type="checkbox" :checked="hasDep(o.id)" :disabled="depWouldCycle(o.id) && !hasDep(o.id)"
                 @change="toggleDep(o.id)" />
          <span class="num">{{ o.id }}</span> {{ shortSegLabel((segments.find((s) => s.name === o.script) || {}).label) || o.script }}
        </label>
      </div>

      <div class="field">
        <label>输入接线 <small class="muted">(流程 in 变量 ← 来源)</small></label>
        <select v-if="inVars.length" aria-label="添加输入接线"
                @change="addInput($event.target.value); $event.target.value = ''">
          <option value="">＋ 接线…</option>
          <option v-for="v in inVars" :key="v.name" :value="v.name"
                  :disabled="!!(flow.inputs || {})[v.name]">{{ v.name }}</option>
        </select>
        <small v-else class="muted">该流程无 in 变量</small>
      </div>
      <div v-for="(src, name) in flow.inputs || {}" :key="'i' + name" class="sp-kv">
        <span class="sp-key num">{{ name }}</span>
        <select :value="srcKindOf(src)" :aria-label="`${name} 来源类型`"
                @change="setSrcKind(name, $event.target.value)">
          <option v-for="[k, t] in SRC_KINDS" :key="k" :value="k">{{ t }}</option>
        </select>
        <!-- 字面量来源 + 目标变量有取值域: 渲染下拉。这里是非法值的产生口 (方案存进 recipe 后
             调度器逐样品派发, 失败时批次已跑到一半), 堵在录入侧比后端拒收更省事故。
             ctx/batch 填的是上下文键名而非取值本身, 必须保持自由输入。 -->
        <select v-if="srcKindOf(src) === 'lit' && enumOf(varDefOf(name)).length"
                :value="String(src.lit ?? '')" :aria-label="`${name} 来源值`"
                @change="setSrcValue(name, $event.target.value)">
          <option :value="''">— 取脚本默认 —</option>
          <option v-if="src.lit != null && String(src.lit) !== ''
                        && !enumOf(varDefOf(name)).some((o) => o.value === String(src.lit))"
                  :value="String(src.lit)" disabled>{{ src.lit }} (已不在可选值内)</option>
          <option v-for="o in enumOf(varDefOf(name))" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <input v-else :value="src[srcKindOf(src)]" :aria-label="`${name} 来源值`"
               :placeholder="srcKindOf(src) === 'ctx' ? 'sample_id / tank / 上游输出键' : '值'"
               @change="setSrcValue(name, $event.target.value)" />
        <button class="mini" :title="`移除 ${name} 接线`" @click="dropInput(name)">×</button>
      </div>

      <div class="field">
        <label>输出接线 <small class="muted">(流程 out 变量 → 样品上下文键)</small></label>
        <select v-if="outVars.length" aria-label="添加输出接线"
                @change="addOutput($event.target.value); $event.target.value = ''">
          <option value="">＋ 输出…</option>
          <option v-for="v in outVars" :key="v.name" :value="v.name"
                  :disabled="!!(flow.outputs || {})[v.name]">{{ v.name }}</option>
        </select>
        <small v-else class="muted">该流程无 out 变量</small>
      </div>
      <div v-for="(ctxKey, name) in flow.outputs || {}" :key="'o' + name" class="sp-kv">
        <span class="sp-key num">{{ name }}</span>
        <input :value="ctxKey" :aria-label="`${name} 写入的上下文键`"
               @change="flow.outputs[name] = $event.target.value; emit('touch')" />
        <button class="mini" :title="`移除 ${name} 输出`" @click="dropOutput(name)">×</button>
      </div>

      <div class="field">
        <label for="sp-occ">占用占位 <small class="muted">(本段做完起占, 逗号分隔; 如 scrape-holder)</small></label>
        <input id="sp-occ" :value="listText(flow.occupy)" @change="setList('occupy', $event.target.value)" />
      </div>
      <div class="field">
        <label for="sp-rel">释放占位 <small class="muted">(须与某段的占用配平)</small></label>
        <input id="sp-rel" :value="listText(flow.release)" @change="setList('release', $event.target.value)" />
      </div>
      <div class="field">
        <label><input type="checkbox" :checked="!!flow.ingest_results"
                      @change="setIngest($event.target.checked)" />
          本段完成后摄取视觉结果 (含 Rf) 入实验库</label>
      </div>
    </template>

    <!-- 未选中: 方案级属性 -->
    <template v-else>
      <div class="sp-head"><span class="group-title">方案属性</span></div>
      <div class="field">
        <label for="sp-label">显示名</label>
        <input id="sp-label" :value="doc.label"
               @change="doc.label = $event.target.value; emit('touch')" />
      </div>
      <div class="field">
        <label>每样品消耗耗材 <small class="muted">(批次准入按此逐样品预留)</small></label>
        <select aria-label="添加耗材种类" @change="addConsumable($event.target.value); $event.target.value = ''">
          <option value="">＋ 耗材…</option>
          <option v-for="k in CONSUMABLE_KINDS" :key="k" :value="k"
                  :disabled="(doc.consumables || []).includes(k)">{{ k }}</option>
        </select>
      </div>
      <div v-for="k in doc.consumables || []" :key="k" class="sp-kv">
        <span class="sp-key num">{{ k }}</span>
        <button class="mini" :title="`移除 ${k}`" @click="dropConsumable(k)">×</button>
      </div>
      <p class="muted sp-hint">
        选中画布上的段可编辑它的流程/依赖/接线。段间串并行结构就是依赖关系:
        链式=串行, 分叉=并行; 样品间并发度在提交实验时用「样品间并发」旋钮设。
      </p>
    </template>
  </div>
</template>

<style scoped>
.sp { height: 100%; overflow: auto; padding: 8px 10px; display: flex; flex-direction: column; gap: 6px; }
.sp-head { display: flex; align-items: center; gap: 8px; }
.sp-head .mini { margin-left: auto; }
.field { display: flex; flex-direction: column; gap: 2px; }
.field > label { font-size: var(--fs-12, 12px); color: var(--muted, #888); }
.sp-cb label { display: flex; align-items: center; gap: 4px; font-size: var(--fs-12, 12px); }
.sp-kv { display: flex; align-items: center; gap: 4px; }
.sp-key { flex: 0 0 auto; min-width: 84px; font-size: var(--fs-12, 12px); }
.sp-kv input, .sp-kv select { min-width: 0; flex: 1 1 auto; }
.sp-hint { margin: 8px 0 0; }
</style>
