<script setup>
// 底部调试坞: STEP/运行/暂停(冻结)/运行后停止(边界)/继续/终止/急停/复位 + 状态徽标 + 日志 / 变量检查
import { computed, reactive, ref, useId } from 'vue'
import { useRouter } from 'vue-router'
import { useEditorStore } from '../../stores/editor'
import { useDebugStore } from '../../stores/debug'
import { useSystemStore } from '../../store'
import { fmtShortMs } from '../../utils/format'
import { isIdle, isRunActiveElsewhere } from '../../utils/runControl'
import { STRUCT_TYPES, validateValue, enumOf, sanitizeRestored, loadLastInputs, saveLastInputs, toDisplay, toRaw } from '../../utils/runInputs'
import { confirmAction } from '../../composables/confirmService.js'
import { useModalA11y } from '../../composables/useModalA11y.js'
import { api } from '../../api'

const editor = useEditorStore()
const debug = useDebugStore()
const sys = useSystemStore()
const router = useRouter()

const idle = computed(() => isIdle(debug.status))
// 正在跑的运行归属"别的流程" (当前只是浏览它): 运行控制指向别处, 本页禁用起跑/步进, 只提供跳回。
// 防止在浏览页点"运行"把另一个流程的 run 误续跑 (会触发意外机器人动作)。
const activeElsewhere = computed(() =>
  isRunActiveElsewhere({ status: debug.status, runOperation: debug.operation, editedFlow: editor.current.name }))
function jumpToRunning() {
  if (debug.operationAtomic) return          // 原子动作 (operation=动作 id, 如 robot.home) 无编辑页, 不跳死路由 (审阅 #6)
  if (debug.operation) router.push(`/library/operation/${debug.operation}`)
}
// 继续可用: 已挂起 (冻结/边界) 或停在单步/断点处
const canResume = computed(() => debug.hold !== 'none' || ['PAUSED', 'STOPPED'].includes(debug.status))
// 继续语义随挂起类型变化: 冻结→从冻结点续跑; 边界→放行下一动作
const resumeLabel = computed(() =>
  debug.hold === 'frozen' ? '继续(续跑)' : debug.hold === 'at_boundary' ? '继续(下一步)' : '继续')
const holdLabel = computed(() =>
  debug.hold === 'frozen' ? '已冻结' : debug.hold === 'at_boundary' ? '边界待停' : '')

// 起跑模式: false=从头开始 (b/0), true=从选中行开始 (快进至 editor.selectedAid)
const fromSel = ref(false)

// 调试入参: io=in 且无 ui 的变量 (裸入参); 带 ui 的 in var 归"运行前旋钮"面板 (见下), 二者不重叠
const inVars = computed(() => editor.variables.filter((v) => v.io === 'in' && !v.ui))
const inputForm = reactive({ open: false, modeRun: 'run', startAid: '', draft: {} })

// 入参卡弹窗可达性: 焦点圈禁/还焦 + Esc 关闭 (等效"取消"); 打开先落到第一个输入框
const inCard = ref(null)
const uid = useId()
useModalA11y(inCard, {
  open: computed(() => inputForm.open),
  onEsc: () => { inputForm.open = false },
  initialFocus: '.in-tab input, .in-tab select',   // 第一个真正的入参框 (跳过回填横幅/过滤开关)
})

// 终止 = 结束整次运行, 走危险确认; 急停不在此列 (急停路径零确认零延迟, 定案)
async function terminateRun() {
  if (!(await confirmAction({
    level: 'danger',
    title: '终止当前运行',
    message: '流程将立即结束, 已执行的物理动作不会回退。',
    confirmText: '终止',
  }))) return
  debug.terminate()
}

// 启动前校验: 规则镜像后端 coerce_value (见 utils/runInputs); 出错行红框+文案, 有错禁启动。
// 按名字典 computed: 一次按键只全量算一遍, 模板 :class/v-if/插值全读字典 (免每行 3-4 次重复解析, 评审 F10)。
// enum 旋钮只查成员资格 (select 常态合法, 但 B3 回填的陈旧值可能已不在枚举里)。
// 有限取值域的入参: 无 default 时留空 = 以零值起跑 = 必落 else 分支, 面板直接拦 (它没有
// "取默认"可退, 空选择就是错的); 有 default 的留空仍合法, 走脚本默认。
const inErrors = computed(() =>
  Object.fromEntries(inVars.value.map((v) => {
    const opts = enumOf(v)
    const raw = inputForm.draft[v.name]
    if (opts.length && v.default == null && (raw == null || raw === '')) return [v.name, '必选']
    return [v.name, validateValue(v.type, raw, null, opts)]
  })))
// 旋钮校验与裸入参走同一个 validateValue (取值域 + 类型 + 范围), 不再各写一套成员判定
const knobErrors = computed(() =>
  Object.fromEntries(knobs.value.map((k) => [k.name, validateValue(k.type, knobDraft[k.name], k.ui, enumOf(k))])))
const errorCount = computed(() => {
  let n = 0
  for (const e of Object.values(inErrors.value)) if (e) n++
  for (const e of Object.values(knobErrors.value)) if (e) n++
  return n
})
// 无默认值的裸入参留空: 后端以类型零值 (0/""/false) 静默运行 — 黄色提示, 不拦截。
// 有取值域的变量不走这条: 它留空取的是 default 而非零值, 且无 default 时已由 inErrors 硬拦。
const zeroHints = computed(() => Object.fromEntries(inVars.value.map((v) => {
  const raw = inputForm.draft[v.name]
  const hit = !enumOf(v).length && v.default == null && (raw == null || raw === '')
  return [v.name, hit ? '留空将以零值运行' : '']
})))

// 运行前旋钮: 递归收集当前 operation 树 (含深层子脚本) 内带 ui 的 in var; 改动即进覆盖 map
const knobs = ref([])
const knobDraft = reactive({})
// 下钻树: operation(script) → action → 参数 两级导航壳 (身份仍是旋钮名)。一个旋钮被多 action 引用
// 则各挂一份 (仅展示; collectOverrides 按名收一份)。无关联 action 的散旋钮归"其它"。ui.group 降为行内子标签。
const knobTree = computed(() => {
  const ops = []
  const opIndex = {}
  const actIndex = {}
  for (const k of knobs.value) {
    const opKey = k.script_label || k.script || '其它'
    let op = opIndex[opKey]
    if (!op) { op = { name: opKey, actions: [] }; opIndex[opKey] = op; ops.push(op) }
    const acts = (k.actions && k.actions.length) ? k.actions : [{ name: '', label: '其它' }]
    for (const a of acts) {
      const aKey = `${opKey}::${a.name || ''}`
      let act = actIndex[aKey]
      if (!act) { act = { key: aKey, name: a.label || a.name || '其它', items: [] }; actIndex[aKey] = act; op.actions.push(act) }
      act.items.push(k)
    }
  }
  return ops
})

// 折叠 (会话级, key=op名/act键) + "只看已改动"过滤: knobView 在 knobTree 上过滤并统计每组改动数
const folded = reactive({})
function toggleFold(key) { folded[key] = !folded[key] }
const onlyChanged = ref(false)
// 已改动旋钮名集合 (draft 非空且 ≠ 默认串): 徽标计数/行高亮/"只看已改动"过滤共用一份
const changedSet = computed(() => {
  const s = new Set()
  for (const k of knobs.value) {
    const raw = knobDraft[k.name]
    if (raw != null && raw !== '' && raw !== k._baseStr) s.add(k.name)
  }
  return s
})
const changedCount = computed(() => changedSet.value.size)
const knobView = computed(() => {
  const ops = []
  for (const op of knobTree.value) {
    let opChanged = 0
    const acts = []
    for (const act of op.actions) {
      opChanged += act.items.filter((k) => changedSet.value.has(k.name)).length
      const items = onlyChanged.value ? act.items.filter((k) => changedSet.value.has(k.name)) : act.items
      if (items.length) acts.push({ ...act, items })
    }
    if (acts.length) ops.push({ ...op, actions: acts, changed: opChanged })
  }
  return ops
})

// 行内提示: ui.group (子标签) · (ui.hint | 范围) · 示教基准 (几何旋钮的 live, 占位符外再显式点明当前基准值)
// ui.hint: 显式语义提示, 存在时替代 min~max 机械回显 (min/max 仅作钳位, 如溶剂权重的归一化说明)。
// 缩放旋钮 (ui.scale): 范围/基准按 scale 换成物理单位显示, 附单位标; 步进即 scale, 由输入框直显。
function knobHint(k) {
  const parts = []
  const scale = k.ui && k.ui.scale
  const hint = k.ui && k.ui.hint
  if (k.ui && k.ui.group) parts.push(k.ui.group)
  if (hint) parts.push(hint)
  else if (k.ui && k.ui.min != null) {
    parts.push(scale
      ? `${toDisplay(k.ui.min, scale)}~${toDisplay(k.ui.max, scale)} ${k.ui.unit || ''}`.trim()
      : `${k.ui.min}~${k.ui.max}`)
  }
  if (k.live != null) parts.push(`基准 ${scale ? toDisplay(k.live, scale) : k.live}`)
  else if (!hint && !(k.ui && k.ui.min != null) && k.paths && k.paths[0]) parts.push(k.paths[0])
  return parts.join(' · ')
}

// 缩放旋钮提交: 把界面物理值 (如 mL/min) 换回底层原值 (整数 V) 写入 draft,
// 使 collectOverrides / 校验 / 已改动判定仍全程走 V (显示皮肤不改下发单位)。
// 末尾强制把输入框回写为吸附后的显示值: Vue 受控 :value 在 model 未变 (吸附后 V 与原值相同)
// 时不会重渲 DOM, 手动同步才能保证"显示恒等于真实下发值"(如输 1.6 恒回显 1.5)。
function onScaledKnob(k, ev) {
  const raw = toRaw(ev.target.value, k.ui.scale, k.ui.min, k.ui.max)
  knobDraft[k.name] = raw
  ev.target.value = toDisplay(raw, k.ui.scale)
}

// 旋钮默认值的字符串形 (与 draft 同型, 用于"是否动过"判定与回填); loadKnobs 后一次性缓存到
// 每个 knob 对象 (k._baseStr), changedSet/collectOverrides/_fillDefaults 读缓存, 免每键重复 JSON.stringify。
function _baseStr(k) {
  if (k.default == null) return ''
  return STRUCT_TYPES.includes(k.type) ? JSON.stringify(k.default) : String(k.default)
}

async function loadKnobs() {
  try { knobs.value = (await api.getKnobs(editor.current.name)).knobs || [] }
  catch { knobs.value = [] }
  for (const k of knobs.value) k._baseStr = _baseStr(k)
  return knobs.value
}

// 上次输入记忆: 启动成功即存 (原始字符串 draft), 打开面板铺完默认后自动叠加回填
// (只回填仍存在的变量/旋钮名, 改名/删除自动失效); restoredTs>0 时显示横幅+恢复默认按钮。
const restoredTs = ref(0)
const restoredDropped = ref([])          // 回填时因已不在取值域内而被丢弃的入参名 (横幅点名)
function _fillDefaults() {
  inputForm.draft = Object.fromEntries(inVars.value.map((v) => [v.name, v.default == null ? '' : String(v.default)]))
  for (const k of Object.keys(knobDraft)) delete knobDraft[k]
  for (const k of knobs.value) knobDraft[k.name] = k._baseStr
}
function restoreDefaults() { _fillDefaults(); restoredTs.value = 0; restoredDropped.value = []; matHints.value = {} }

// 物料账本给的库位/孔号建议 (变量名 -> 说明); 仅用于在输入行显示来源, 值已写进 draft
const matHints = ref({})

// 账本预填: 该填哪个库位/孔号由后端按绑定表解析 (前端不做推断)。
// 叠在"上次输入"之后 —— 上次用过的孔按定义已被消耗, 账本反映的是当下余量, 故账本优先。
// 账本无余量/请求失败时不动 draft, 静默退回脚本 default (账本是建议式的, 无权威)。
async function applyMaterialSuggestion() {
  matHints.value = {}
  const names = inVars.value.map((v) => v.name)
  if (!names.length) return
  try {
    const res = await api.suggestMaterialInputs(editor.current.name, names)
    for (const [k, v] of Object.entries(res.inputs || {})) {
      if (!(k in inputForm.draft)) continue
      // 建议值落在取值域外 (如账本孔数与脚本 enum 不同步) 就静默不写 —— 账本是建议式的,
      // 无权威 (见 material_store 的定性), 宁可退回脚本默认也不写进一个必炸的值
      const opts = enumOf(inVars.value.find((x) => x.name === k))
      if (opts.length && !opts.some((o) => o.value === String(v))) continue
      inputForm.draft[k] = String(v)
    }
    matHints.value = res.source || {}
  } catch { matHints.value = {} }
}

function openInputs(modeRun, startAid) {
  inputForm.modeRun = modeRun
  inputForm.startAid = startAid
  _fillDefaults()
  restoredTs.value = 0
  restoredDropped.value = []
  matHints.value = {}
  const last = loadLastInputs(editor.current.name)
  if (last) {
    let hit = 0
    // 入参先过取值域清洗: 分支被改名/删掉后, localStorage 里那个旧值已是必炸的死值,
    // 直接丢弃退回默认并点名 (旋钮刻意不清洗, 见 sanitizeRestored 的注释)
    const clean = sanitizeRestored(inVars.value, last.inputs || {})
    restoredDropped.value = clean.dropped
    for (const [k, v] of Object.entries(clean.values)) if (k in inputForm.draft) { inputForm.draft[k] = v; hit++ }
    for (const [k, v] of Object.entries(last.knobs || {})) if (k in knobDraft) { knobDraft[k] = v; hit++ }
    if (hit || clean.dropped.length) restoredTs.value = last.ts
  }
  inputForm.open = true
  applyMaterialSuggestion()      // 异步叠加, 不阻塞面板弹出
}

// 仅收集用户填写的非空项; 结构类型走 JSON 解析, 标量交后端按类型强转
function collectInputs() {
  const out = {}
  for (const v of inVars.value) {
    const raw = inputForm.draft[v.name]
    if (raw == null || raw === '') continue
    if (STRUCT_TYPES.includes(v.type)) {
      try { out[v.name] = JSON.parse(raw) } catch { out[v.name] = raw }
    } else {
      out[v.name] = raw
    }
  }
  return out
}

// 仅收集"动过"的旋钮 (draft != 默认); 未动 = 用默认, 不进 map. 标量交后端强转, 结构走 JSON
function collectOverrides() {
  const out = {}
  for (const k of knobs.value) {
    const raw = knobDraft[k.name]
    if (raw == null || raw === '' || raw === k._baseStr) continue
    if (STRUCT_TYPES.includes(k.type)) {
      try { out[k.name] = JSON.parse(raw) } catch { out[k.name] = raw }
    } else {
      out[k.name] = raw
    }
  }
  return out
}

function launch() {
  if (activeElsewhere.value) return          // 面板打开后归属被别处夺走时兜底拦截 (按钮点击与 @keyup.enter 都走此处, 审阅 #1)
  if (errorCount.value) return               // 有校验错误禁止启动 (按钮已禁用, 此处拦 Enter 键)
  saveLastInputs(editor.current.name, { inputs: { ...inputForm.draft }, knobs: { ...knobDraft }, ts: Date.now() })
  inputForm.open = false
  debug.start(editor.current.name, collectInputs(), sys.mode, inputForm.modeRun, inputForm.startAid, collectOverrides())
}

// 有 in 变量或旋钮则先弹面板; 否则沿用原行为直接启动. 选中行模式带上所选 AID, 否则从头 ('')
async function begin(modeRun) {
  const startAid = fromSel.value ? editor.selectedAid : ''
  await loadKnobs()
  if (inVars.value.length || knobs.value.length) openInputs(modeRun, startAid)
  else debug.start(editor.current.name, {}, sys.mode, modeRun, startAid)
}

// activeElsewhere 时一律拦截: 运行控制属于别的流程, 本页只读 (按钮亦禁用, 此处兜底防误触)
function run() { if (activeElsewhere.value) return; idle.value ? begin('run') : debug.cont() }
function step() { if (activeElsewhere.value) return; idle.value ? begin('step') : debug.stepOver() }   // 空闲→以单步起跑; 运行中→步过 (子流程一次跑完)
function stepInto() { if (activeElsewhere.value) return; if (!idle.value) debug.step() }               // 运行中→步入子流程逐叶停驻
</script>

<template>
  <div class="debug-dock">
    <div class="dbg-bar">
      <span class="tid">TID: {{ debug.runId || 'DEBUG' }}</span>
      <span class="badge" :class="debug.status" role="status">{{ debug.status || 'idle' }}</span>
      <span v-if="holdLabel" class="badge hold">{{ holdLabel }}</span>
      <!-- 运行归属别的流程: 本页只读, 点此跳回在跑的流程去控制它 -->
      <button v-if="activeElsewhere" class="run-elsewhere" :class="{ 'no-jump': debug.operationAtomic }"
              @click="jumpToRunning"
              title="运行控制属于正在执行的流程, 点击跳转过去">运行中: {{ debug.operation }}{{ debug.operationAtomic ? ' (原子动作)' : ' · 跳转 ▸' }}</button>
      <select class="tb-sel" v-model="fromSel" :disabled="!idle || activeElsewhere"
              title="起跑位置: 从头开始 / 从选中行 (跳过其前设备/人工动作)">
        <option :value="false">从头开始</option>
        <option :value="true">从选中行开始</option>
      </select>
      <button class="tb" :disabled="activeElsewhere || !editor.current.name || (idle && fromSel && !editor.selectedAid)" @click="step" title="步过: 子流程(run_script)一次执行完, 停在父流程下一步" aria-label="步过: 子流程(run_script)一次执行完">步过</button>
      <button class="tb" :disabled="activeElsewhere || idle || !editor.current.name" @click="stepInto" title="步入: 进入子流程逐叶单步" aria-label="步入: 进入子流程逐叶单步">步入</button>
      <button class="tb" :disabled="activeElsewhere || !editor.current.name || (idle && fromSel && !editor.selectedAid)" @click="run">运行</button>
      <button class="tb" :disabled="activeElsewhere || idle || debug.hold === 'frozen'" @click="debug.pause()" title="立即冻结在飞运动" aria-label="暂停: 立即冻结在飞运动">暂停</button>
      <button class="tb" :disabled="activeElsewhere || idle || debug.hold === 'at_boundary'" @click="debug.stopAfter()" title="跑完当前动作停在边界" aria-label="运行后停止: 跑完当前动作停在边界">运行后停止</button>
      <button class="tb" :disabled="activeElsewhere || !canResume" @click="debug.resume()">{{ resumeLabel }}</button>
      <button class="tb danger" :disabled="activeElsewhere || idle" @click="terminateRun" title="软停机器人, 不报警, 结束本次运行" aria-label="终止运行: 软停机器人">终止运行</button>
      <button class="tb danger" :disabled="activeElsewhere || idle" @click="debug.estop()" title="急停: 失能臂并报警, 需清警重新使能" aria-label="急停: 失能臂并报警">急停</button>
      <button class="tb" :disabled="activeElsewhere || !debug.runId" @click="debug.reset()">复位</button>
    </div>

    <div v-if="inputForm.open" class="in-overlay" @click.self="inputForm.open = false">
      <div class="in-card" ref="inCard" role="dialog" aria-modal="true" tabindex="-1" :aria-labelledby="`${uid}-title`">
        <div class="in-title" :id="`${uid}-title`">运行前设置 · {{ inputForm.modeRun === 'step' ? 'STEP' : '运行' }}</div>
        <div v-if="restoredTs" class="restored">
          <span>已回填上次输入 ({{ fmtShortMs(restoredTs) }})</span>
          <span v-if="restoredDropped.length" class="cell-warn">{{ restoredDropped.join('/') }} 的旧值已不在可选值内, 已退回默认</span>
          <button class="mini" @click="restoreDefaults">恢复默认</button>
        </div>

        <template v-if="inVars.length">
          <table class="in-tab">
            <tr v-for="v in inVars" :key="v.name">
              <td class="in-name" :id="`${uid}-in-${v.name}`">{{ v.name }}<small class="muted">{{ v.type }}</small></td>
              <td>
                <!-- 有限取值域: 渲染下拉, 杜绝自由输入打出不存在的分支名 (那会一路跑到脚本
                     末尾 else 才抛 SELECTOR, 那时机器人已 home 完换完刀)。
                     Enter 不绑 launch: 原生 select 上 Enter 用于展开列表, 会被浏览器吃掉。 -->
                <select v-if="enumOf(v).length" v-model="inputForm.draft[v.name]"
                        :class="{ err: inErrors[v.name] }"
                        :aria-labelledby="`${uid}-in-${v.name}`"
                        :aria-invalid="!!inErrors[v.name]"
                        :aria-describedby="inErrors[v.name] ? `${uid}-err-${v.name}` : undefined">
                  <option :value="''">{{ v.default == null ? '— 未选择 —' : `— 取默认 (${v.default}) —` }}</option>
                  <option v-for="o in enumOf(v)" :key="o.value" :value="o.value">{{ o.label }}</option>
                </select>
                <input v-else v-model="inputForm.draft[v.name]" :class="{ err: inErrors[v.name] }"
                       :type="v.type === 'INT' || v.type === 'FLOAT' ? 'number' : 'text'"
                       :step="v.type === 'FLOAT' ? 'any' : undefined"
                       :aria-labelledby="`${uid}-in-${v.name}`"
                       :aria-invalid="!!inErrors[v.name]"
                       :aria-describedby="inErrors[v.name] ? `${uid}-err-${v.name}` : undefined"
                       :placeholder="v.default == null ? '' : String(v.default)"
                       @keyup.enter="launch" />
              </td>
              <td class="in-cmt">
                <small v-if="inErrors[v.name]" class="cell-err" :id="`${uid}-err-${v.name}`">{{ inErrors[v.name] }}</small>
                <small v-else-if="zeroHints[v.name]" class="cell-warn">{{ zeroHints[v.name] }}</small>
                <small v-else-if="matHints[v.name]" class="cell-mat">账本建议 · {{ matHints[v.name] }}</small>
                <small v-else class="muted">{{ v.comment }}</small>
              </td>
            </tr>
          </table>
          <p class="hint">留空取脚本默认值; LIST/DICT/POSE 按 JSON 填写.</p>
        </template>

        <div v-if="knobs.length" class="knob-sec">
          <div class="in-title knob-head">运行前旋钮
            <label class="tb-chk"><input type="checkbox" v-model="onlyChanged" /> 只看已改动 ({{ changedCount }})</label>
            <small class="muted">改动即覆盖 · 未动取默认/示教基准</small>
          </div>
          <p v-if="onlyChanged && !changedCount" class="hint">无改动项</p>
          <div v-for="op in knobView" :key="op.name" class="knob-op">
            <button type="button" class="btn-bare knob-op-h fold" :aria-expanded="!folded[op.name]" @click="toggleFold(op.name)">
              <span class="caret">{{ folded[op.name] ? '▸' : '▾' }}</span>{{ op.name }}
              <small v-if="op.changed" class="chg-badge">{{ op.changed }} 改动</small>
            </button>
            <template v-if="!folded[op.name]">
              <div v-for="act in op.actions" :key="act.key" class="knob-grp">
                <button type="button" class="btn-bare knob-grp-h fold" :aria-expanded="!folded[act.key]" @click="toggleFold(act.key)">
                  <span class="caret">{{ folded[act.key] ? '▸' : '▾' }}</span>{{ act.name }}
                </button>
                <table v-if="!folded[act.key]" class="in-tab">
                  <tr v-for="k in act.items" :key="`${act.key}::${k.name}`" class="knob-row" :class="{ changed: changedSet.has(k.name) }">
                    <td class="in-name">{{ (k.ui && k.ui.label) || k.name }}<small class="muted">{{ k.type }}</small></td>
                    <td>
                      <!-- 可访问名走 aria-label 而非 in-name 单元格 id: 同一旋钮可挂在多个 action 组下, id 会重复 -->
                      <select v-if="enumOf(k).length" v-model="knobDraft[k.name]" :class="{ err: knobErrors[k.name] }"
                              :aria-label="(k.ui && k.ui.label) || k.name" :aria-invalid="!!knobErrors[k.name]">
                        <!-- 陈旧值兜底: 旋钮刻意保留越界的旧值 (标红+禁启动, 与入参的"丢弃退默认"分叉),
                             故需要这一项撑住 v-model —— 否则 select 渲成空白而坏值仍在 draft 里, 看不见问题 -->
                        <option v-if="knobDraft[k.name] && !enumOf(k).some((o) => o.value === String(knobDraft[k.name]))"
                                :value="knobDraft[k.name]" disabled>{{ knobDraft[k.name] }} (已不在可选值内)</option>
                        <option v-for="o in enumOf(k)" :key="o.value" :value="o.value">{{ o.label }}</option>
                      </select>
                      <!-- 缩放旋钮 (ui.scale): 与普通输入同构的裸 input (填满窄单元格, 不塞行内单位标,
                           以免挤塌输入框); 单位由旋钮标签与 knobHint 承载。仅换算属性不同。 -->
                      <input v-else-if="(k.type === 'INT' || k.type === 'FLOAT') && k.ui && k.ui.scale" type="number"
                             :min="toDisplay(k.ui.min, k.ui.scale)" :max="toDisplay(k.ui.max, k.ui.scale)" :step="k.ui.scale"
                             :placeholder="k.live != null ? toDisplay(k.live, k.ui.scale) : ''" :class="{ err: knobErrors[k.name] }"
                             :aria-label="(k.ui && k.ui.label) || k.name" :aria-invalid="!!knobErrors[k.name]"
                             :value="toDisplay(knobDraft[k.name], k.ui.scale)"
                             @change="onScaledKnob(k, $event)" @keyup.enter="launch" />
                      <input v-else-if="k.type === 'INT' || k.type === 'FLOAT'" type="number"
                             :min="k.ui && k.ui.min" :max="k.ui && k.ui.max" :step="k.type === 'INT' ? 1 : 'any'"
                             :placeholder="k.live != null ? String(k.live) : ''" :class="{ err: knobErrors[k.name] }"
                             :aria-label="(k.ui && k.ui.label) || k.name" :aria-invalid="!!knobErrors[k.name]"
                             v-model="knobDraft[k.name]" @keyup.enter="launch" />
                      <input v-else v-model="knobDraft[k.name]" :class="{ err: knobErrors[k.name] }"
                             :aria-label="(k.ui && k.ui.label) || k.name" :aria-invalid="!!knobErrors[k.name]" @keyup.enter="launch" />
                    </td>
                    <td class="in-cmt">
                      <small v-if="knobErrors[k.name]" class="cell-err">{{ knobErrors[k.name] }}</small>
                      <small v-else class="muted">{{ knobHint(k) }}</small>
                    </td>
                  </tr>
                </table>
              </div>
            </template>
          </div>
        </div>

        <div class="in-foot">
          <span v-if="errorCount" class="cell-err foot-err" role="status">{{ errorCount }} 项有误</span>
          <button class="tb" @click="inputForm.open = false">取消</button>
          <button class="tb save" :disabled="activeElsewhere || errorCount > 0" @click="launch">启动</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* operation 级导航壳: 比 action 级 (.knob-grp-h, 全局样式) 更醒目一档, 内层动作组缩进对齐 */
.knob-op { margin-top: 8px; }
.knob-op-h { font-weight: 600; opacity: 0.85; padding: 2px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.25); }
.knob-op .knob-grp { margin-left: 10px; }
/* 折叠开关 div→button 后保持整行块级排版 (btn-bare 默认 inline-flex 会缩成内容宽) */
button.knob-op-h, button.knob-grp-h { display: block; width: 100%; text-align: left; }
.tid { font-family: var(--font-mono); }
</style>
