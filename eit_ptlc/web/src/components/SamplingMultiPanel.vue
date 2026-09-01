<script setup>
// 多样品上样控制台 (流程页 sampling_multi_execute / sampling_multi_cycle 的专用录入面板)。
// 一次装板, 板上点 N 条带: 逐行填「哪个孔的样品 → 点到板上哪块区域 → 用什么参数」。
//
// 为什么不用通用的「运行前旋钮」面板:
//   运行前旋钮覆盖是全局的 (按名注入到每一帧, 见 vm/thread.py 的 _make_frame), 逐样品的
//   孔位/几何/参数一旦做成旋钮, 一个被动过的旋钮就会把所有样品压成同一个值 —— 那正是本
//   流程要解决的问题。故逐行数据只经 samples (LIST 非旋钮入参) 下发, 本面板就是那张表的编辑器。
//
// 量程真源不在本文件:
//   逐行参数的 min/max/缺省/单位换算全部读 GET /api/scripts/{op}/debug/knobs (即流程 YAML 的
//   ui 块); 几何的限位与示教基准读 spot_pose 组合点位。本文件只定「哪些列、什么短标题、什么列序」。
//   改量程改流程 YAML 即可, 不必回来改前端。
//
// 校验只是"未跑先拒"的 UX 兜底 (免机器人空跑几步才在动作层被拒); 真安全闸仍在
// 动作层 executor._validate 与流程内的体积链守卫。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { usePoll } from '../composables/usePoll.js'
import { useDebugStore } from '../stores/debug'
import { useSystemStore } from '../store'
import { loadJson, saveJson } from '../utils/storage'
import { toDisplay, toRaw } from '../utils/runInputs'

const OP_EXECUTE = 'sampling_multi_execute'
const OP_CYCLE = 'sampling_multi_cycle'
const STORE_KEY = 'ptlc.sampling_multi.rows.v1'
const IDLE_STATES = ['idle', 'NEW', 'DONE', 'ERROR', 'KILLED', '']
const DEAD_VOLUME_ML = 1.125     // 针流路死体积; 与流程守卫/动作层同一常数 (体积链镜像)
const ASPIRATE_CEIL_ML = 15.0    // 单轮吸取上限; 与 sampling.aspirate 硬闸同值

// 必填几何列: key == spot_pose 的成员 key (逐带覆盖那三个成员), 限位与基准都由该点位给
const GEOM_COLS = [
  { key: 'x_start', title: 'X起点' },
  { key: 'x_end', title: 'X终点' },
  { key: 'y_height', title: 'Y高度' },
]
// 可选参数列: 留空即继承下方「流程缺省」。common=常用列 (缺省显示), 其余折在「全部参数」里。
const PARAM_COLS = [
  { key: 'sample_volume_ml', title: '样品体积', common: true },
  { key: 'rinse_rounds', title: '润洗轮数', common: true },
  { key: 'spot_speed_mm_s', title: '喷涂速度', common: true },
  { key: 'spot_disp_speed', title: '供液泵速', common: true },
  { key: 'dry_cycles', title: '吹气趟数', common: true },
  { key: 'plate_spec', title: '孔板规格' },
  { key: 'plate_no', title: '盘位号' },
  { key: 'dry_speed_mm_s', title: '吹气速度' },
  { key: 'over_aspirate_ml', title: '排空余量' },
  { key: 'air_gap_ml', title: '气隔断' },
  { key: 'rinse_volume_ml', title: '润洗液量' },
  { key: 'mix_volume_ml', title: '吹打体积' },
  { key: 'mix_count', title: '吹打次数' },
]

const debug = useDebugStore()
const sys = useSystemStore()

const rows = ref([])
const knobs = ref([])            // 流程级缺省 (含 ui.min/max/enum/scale)
const knobDraft = reactive({})   // 缺省的编辑草稿 (字符串形)
const pose = ref(null)           // spot_pose 组合点位 {members:[{key,label,value,limits}]}
const loadErr = ref('')
const localError = ref('')
const showAllCols = ref(false)
const withLoadUnload = ref(false)  // 勾上=跑 sampling_multi_cycle (含上下料), 否则只跑执行段
const busy = ref(false)
const liveWell = ref('')           // 运行中当前行 (轮询 VM 变量得到)
const liveX = ref(null)

const opName = computed(() => (withLoadUnload.value ? OP_CYCLE : OP_EXECUTE))
const runActive = computed(() => !IDLE_STATES.includes(debug.status))
const owned = computed(() => [OP_EXECUTE, OP_CYCLE].includes(debug.operation) && runActive.value)
const foreignRun = computed(() => runActive.value && !owned.value)
const knobOf = computed(() => Object.fromEntries(knobs.value.map((k) => [k.name, k])))
const poseOf = computed(() =>
  Object.fromEntries((pose.value?.members || []).map((m) => [m.key, m])))
const visibleParamCols = computed(() =>
  showAllCols.value ? PARAM_COLS : PARAM_COLS.filter((c) => c.common))

// ---- 列元数据: 短标题来自本文件, 量程/缺省/单位来自流程 YAML 与点位表 ----
function meta(key) {
  const k = knobOf.value[key]
  const ui = k?.ui || {}
  return {
    type: k?.type || 'FLOAT',
    min: ui.min, max: ui.max, enum: ui.enum, scale: ui.scale, unit: ui.unit,
    default: k?.default,
  }
}
function geomMeta(key) {
  const m = poseOf.value[key] || {}
  return { min: m.limits?.min ?? -500, max: m.limits?.max ?? 500, base: m.value }
}
function colHint(col) {
  const m = meta(col.key)
  if (m.default == null) return ''          // 旋钮还没拉到 (或该列已从流程里删了): 不回显 undefined
  if (m.enum) return `缺省 ${m.default}`
  const lo = m.scale ? toDisplay(m.min, m.scale) : m.min
  const hi = m.scale ? toDisplay(m.max, m.scale) : m.max
  const def = m.scale ? toDisplay(m.default, m.scale) : m.default
  return `${lo}~${hi}${m.unit ? ' ' + m.unit : ''} · 缺省 ${def}`
}

// ---- 行编辑 ----
// _id: 表格 v-for 的稳定 key。用下标当 key 时, 增删/上下移会让 Vue 复用错行的 input,
// 光标与未提交的输入会跳到别的样品上 (下发的值仍对, 但编辑体验会骗人)。不进下发载荷。
let seq = 0
function blankRow() {
  const r = { _id: ++seq, label: '', well: '' }
  for (const c of GEOM_COLS) r[c.key] = ''
  for (const c of PARAM_COLS) r[c.key] = ''
  return r
}
function addRow() {
  const r = blankRow()
  // 新行几何预填示教基准: 第一行直接用 spot_pose, 之后沿用上一行 (多带常是同 Y 挪 X)
  const prev = rows.value[rows.value.length - 1]
  for (const c of GEOM_COLS) {
    r[c.key] = prev ? prev[c.key] : String(geomMeta(c.key).base ?? '')
  }
  rows.value = [...rows.value, r]
}
function dupRow(i) {
  const copy = { ...rows.value[i], _id: ++seq }
  rows.value = [...rows.value.slice(0, i + 1), copy, ...rows.value.slice(i + 1)]
}
async function delRow(i) {
  if (!(await confirmAction({
    title: '删除样品行 ' + (i + 1),
    message: '该行录入将丢失。',
    confirmText: '删除',
  }))) return
  rows.value = rows.value.filter((_, j) => j !== i)
}
function moveRow(i, d) {
  const j = i + d
  if (j < 0 || j >= rows.value.length) return
  const next = [...rows.value]
  ;[next[i], next[j]] = [next[j], next[i]]
  rows.value = next
}
// 几何整列填示教基准 (点位表改了之后一键对齐)
function fillGeomFromPose() {
  rows.value = rows.value.map((r) => {
    const next = { ...r }
    for (const c of GEOM_COLS) next[c.key] = String(geomMeta(c.key).base ?? '')
    return next
  })
}

// 缩放列 (供液泵速): 界面填 mL/min, 存回底层 DT V —— 与 DebugDock 同一换算, 下发单位不变
function onScaledCell(row, key, ev) {
  const m = meta(key)
  const raw = toRaw(ev.target.value, m.scale, m.min, m.max)
  row[key] = String(raw)
  ev.target.value = toDisplay(raw, m.scale)
}
function onScaledKnob(key, ev) {
  const m = meta(key)
  const raw = toRaw(ev.target.value, m.scale, m.min, m.max)
  knobDraft[key] = String(raw)
  ev.target.value = toDisplay(raw, m.scale)
}

// ---- 校验 (镜像动作层量程 + 流程内的体积链守卫) ----
function numErr(raw, { min, max, int }) {
  const n = Number(raw)
  if (!Number.isFinite(n)) return '需要数字'
  if (int && !Number.isInteger(n)) return '需要整数'
  if (min != null && n < min) return `< ${min}`
  if (max != null && n > max) return `> ${max}`
  return ''
}
// 行内该字段的生效值: 行内留空即取流程缺省 (与流程里的 contains/get 合并逻辑一一对应)
function effective(row, key) {
  const raw = row[key]
  if (raw != null && raw !== '') return Number(raw)
  const d = knobDraft[key]
  return Number(d != null && d !== '' ? d : meta(key).default)
}

const cellErrors = computed(() => rows.value.map((row) => {
  const e = {}
  if (!String(row.well).trim()) e.well = '必填'
  for (const c of GEOM_COLS) {
    const g = geomMeta(c.key)
    e[c.key] = String(row[c.key]).trim() === '' ? '必填' : numErr(row[c.key], g)
  }
  for (const c of PARAM_COLS) {
    const raw = row[c.key]
    if (raw == null || String(raw).trim() === '') continue      // 留空=继承缺省, 不校验
    const m = meta(c.key)
    if (m.enum) {
      e[c.key] = m.enum.some((o) => String(o) === String(raw)) ? '' : '不在选项内'
    } else {
      e[c.key] = numErr(raw, { min: m.min, max: m.max, int: m.type === 'INT' })
    }
  }
  return e
}))

// 体积链: 与 sampling_volume_model 的三条守卫同判据, 提前到面板上拦 (免跑到该行才炸)
const chainErrors = computed(() => rows.value.map((row) => {
  const E = effective(row, 'over_aspirate_ml')
  const G = effective(row, 'air_gap_ml')
  const V = effective(row, 'sample_volume_ml')
  const R = effective(row, 'rinse_volume_ml')
  if (![E, G, V, R].every(Number.isFinite)) return ''
  if (E <= DEAD_VOLUME_ML) return `排空余量 ${E} 必须大于针流路死体积 ${DEAD_VOLUME_ML}`
  const bandEnd = DEAD_VOLUME_ML + G / 2
  if (bandEnd < 0 || bandEnd > 5) return `点样活塞终点 ${bandEnd.toFixed(3)} 越界 [0,5]`
  if (V + E > ASPIRATE_CEIL_ML) return `首轮吸取 ${(V + E).toFixed(2)} 超过 ${ASPIRATE_CEIL_ML} mL`
  if (R + E > ASPIRATE_CEIL_ML) return `润洗轮吸取 ${(R + E).toFixed(2)} 超过 ${ASPIRATE_CEIL_ML} mL`
  return ''
}))

// 同一板上两条带重叠 (同 Y 且 X 区间相交): 不是硬错, 但多半是填错了行, 出黄色提示
const overlapWarn = computed(() => rows.value.map((row, i) => {
  const y = Number(row.y_height), a = Number(row.x_start), b = Number(row.x_end)
  if (![y, a, b].every(Number.isFinite)) return ''
  const lo = Math.min(a, b), hi = Math.max(a, b)
  for (let j = 0; j < rows.value.length; j++) {
    if (j === i) continue
    const o = rows.value[j]
    if (Number(o.y_height) !== y) continue
    const olo = Math.min(Number(o.x_start), Number(o.x_end))
    const ohi = Math.max(Number(o.x_start), Number(o.x_end))
    if (lo < ohi && olo < hi) return `与第 ${j + 1} 行同高且区间重叠`
  }
  return ''
}))

const knobErrors = computed(() => {
  const out = {}
  for (const k of knobs.value) {
    const raw = knobDraft[k.name]
    if (raw == null || raw === '') { out[k.name] = ''; continue }
    const ui = k.ui || {}
    out[k.name] = ui.enum
      ? (ui.enum.some((o) => String(o) === String(raw)) ? '' : '不在选项内')
      : (k.type === 'STRING' ? '' : numErr(raw, { min: ui.min, max: ui.max, int: k.type === 'INT' }))
  }
  return out
})

// 行级提示汇总 (体积链硬错 + 重叠软警); 模板不能在同一元素上同时 v-for/v-if, 故先在此过滤
const rowMessages = computed(() => {
  const out = []
  rows.value.forEach((_row, i) => {
    if (chainErrors.value[i]) out.push({ key: `chain-${i}`, bad: true, text: `第 ${i + 1} 行体积链: ${chainErrors.value[i]}` })
    if (overlapWarn.value[i]) {
      out.push({ key: `ov-${i}`, bad: false,
                 text: `第 ${i + 1} 行: ${overlapWarn.value[i]} —— 两条带会叠在一起, 确认是有意为之` })
    }
  })
  return out
})

const errorCount = computed(() => {
  let n = 0
  for (const e of cellErrors.value) n += Object.values(e).filter(Boolean).length
  n += chainErrors.value.filter(Boolean).length
  n += Object.values(knobErrors.value).filter(Boolean).length
  return n
})
const canStart = computed(() =>
  !busy.value && !runActive.value && rows.value.length > 0 && errorCount.value === 0)

// ---- 下发载荷 ----
// samples: 必填四项恒写; 可选项**只在行内填了时才写这个键** —— 键不存在流程才会回落到缺省
// (流程用 contains 判定而非真假值, 故 rinse_rounds=0 这类合法零值不会被当成"没给")。
function buildSamples() {
  return rows.value.map((row) => {
    const s = { well: String(row.well).trim() }
    if (String(row.label).trim()) s.label = String(row.label).trim()   // 备注, 流程忽略, 只进运行记录
    for (const c of GEOM_COLS) s[c.key] = Number(row[c.key])
    for (const c of PARAM_COLS) {
      const raw = row[c.key]
      if (raw == null || String(raw).trim() === '') continue
      const m = meta(c.key)
      s[c.key] = m.enum ? String(raw) : (m.type === 'INT' ? parseInt(raw, 10) : Number(raw))
    }
    return s
  })
}
// 流程级缺省走 overrides 而不是 inputs: overrides 按名注入到深层子脚本, 故「含上下料」时
// (入口是 cycle, 缺省旋钮声明在 execute 里) 一样能生效; 逐行值走 samples, 两者不打架 ——
// 覆盖设的是"缺省", 行内给了仍是行内胜 (合并在流程 body 里做, 在建帧注入之后)。
// 只发"改动过"的 (与 DebugDock 同一约定): 没动就让流程自己的 default 生效, 运行记录里的
// "覆盖 N 项"才如实反映本次真正改了几个缺省。
function collectOverrides() {
  const out = {}
  for (const k of knobs.value) {
    const raw = knobDraft[k.name]
    if (raw == null || raw === '') continue
    if (k.default != null && String(raw) === String(k.default)) continue
    out[k.name] = raw
  }
  return out
}

async function start() {
  if (!canStart.value) return
  // danger 级: 点了就是真机器人完整跑 N 个样品
  if (!(await confirmAction({
    level: 'danger',
    title: '启动多样品运行',
    message: `将驱动机器人完整执行 ${rows.value.length} 个样品的上样流程。`,
    confirmText: '启动',
  }))) return
  localError.value = ''
  busy.value = true
  try {
    await debug.start(opName.value, { samples: buildSamples() }, sys.mode, 'run', '',
                      collectOverrides())
  } catch (e) {
    localError.value = errText(e)
  } finally {
    busy.value = false
  }
}

// 终止走 danger 确认; 急停保持零确认 (急停路径上不许出现任何对话框, 见 confirmService 分级)
async function askTerminate() {
  if (!(await confirmAction({
    level: 'danger',
    title: '终止当前运行',
    message: '软停机器人, 不报警, 结束本次多样品运行。',
    confirmText: '终止',
  }))) return
  debug.terminate()
}

// ---- 运行进度: 轮询 VM 变量, 用 it_well/it_x_start 标出正在点的那一行 ----
// (VM 不发"第几行"事件; 逐行暂存变量就是最直接的真源。取不到时保留上一次, 不闪。)
async function pollLive() {
  if (!owned.value || !debug.runId) return
  try {
    const res = await api.debugVars(debug.runId)
    const v = res?.vars || {}
    if (v.it_well?.value) liveWell.value = String(v.it_well.value)
    if (v.it_x_start?.value != null) liveX.value = Number(v.it_x_start.value)
  } catch { /* 运行刚结束/切帧: 保留上一次, 下个周期再试 */ }
}
const livePoll = usePoll(pollLive, 1500) // owned/runId 门在 fn 内: 无运行时拍子空转不发请求
function isLiveRow(row) {
  return owned.value && liveWell.value !== ''
    && String(row.well).trim() === liveWell.value
    && (liveX.value == null || Number(row.x_start) === liveX.value)
}

async function reload() {
  loadErr.value = ''
  try {
    // 量程/缺省的唯一真源是流程 YAML 的 ui 块; 点位表给几何限位与示教基准
    const [k, p] = await Promise.all([
      api.getKnobs(OP_EXECUTE),
      api.getPoint('plc_servo_composite', 'spot_pose'),
    ])
    knobs.value = k.knobs || []
    pose.value = p
    for (const kn of knobs.value) {
      if (!(kn.name in knobDraft)) knobDraft[kn.name] = kn.default == null ? '' : String(kn.default)
    }
  } catch (e) {
    loadErr.value = errText(e)
  }
}

onMounted(async () => {
  const saved = loadJson(STORE_KEY, null)
  // 存量记录 (以及手改过的 localStorage) 可能没有 _id: 一律补发, 且 seq 从最大值续,
  // 免得新加的行与回填的行撞 key。
  if (Array.isArray(saved?.rows)) {
    seq = saved.rows.reduce((m, r) => Math.max(m, Number(r?._id) || 0), 0)
    rows.value = saved.rows.map((r) => ({ ...blankRow(), ...r, _id: Number(r?._id) || ++seq }))
  }
  await reload()
  if (saved?.knobs) Object.assign(knobDraft, saved.knobs)   // 缺省要等 knobs 到位再回填
  if (!rows.value.length) addRow()
  livePoll.start()
})

// 表格与缺省随手存: 参数测试要反复调, 刷新/切页不该丢。
// 防抖 300ms: deep watch 每击键都触发, 同步序列化整表写 localStorage 拖输入手感;
// 新击键覆盖旧定时器, 卸载/关页冲刷 pending, 最后一击不丢。
let saveTimer = null
function doSave() {
  saveJson(STORE_KEY, { rows: rows.value, knobs: { ...knobDraft } })
}
function flushSave() {
  if (saveTimer == null) return
  clearTimeout(saveTimer)
  saveTimer = null
  doSave()
}
watch([rows, knobDraft], () => {
  if (saveTimer != null) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => { saveTimer = null; doSave() }, 300)
}, { deep: true })
window.addEventListener('beforeunload', flushSave)
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', flushSave)
  flushSave()
})
watch(runActive, (on) => { if (!on) { liveWell.value = ''; liveX.value = null } })
</script>

<template>
  <div class="sm-panel">
    <div class="sm-head">
      <h3>多样品上样 · 一次装板点多条带</h3>
      <p class="legend">
        每行 = 一个样品: 从哪个孔吸样 → 点到板上哪块区域 (X起点/X终点/Y高度) → 用什么参数。
        <b>参数列留空即继承下方「流程缺省」</b>; 几何三项必填 (缺了会被当成 0.0 真的把点样头开到零位, 故不设回落)。
        条带按<b>表格自上而下</b>的顺序点。
      </p>
      <p v-if="loadErr" class="cell-err">流程参数/点位读取失败: {{ loadErr }} —— 量程与缺省暂不可用, 请先修好再启动。</p>
      <p v-if="foreignRun" class="cell-warn">
        另一个流程正在运行 ({{ debug.operation }}), 本面板暂不能启动。
      </p>
    </div>

    <div class="sm-bar">
      <button class="tb" @click="addRow">+ 添加样品</button>
      <button class="tb" :disabled="!pose" @click="fillGeomFromPose"
              title="把所有行的几何三项填成 spot_pose 当前示教基准">几何填示教基准</button>
      <label class="tb-chk"><input type="checkbox" v-model="showAllCols" /> 全部参数列</label>
      <label class="tb-chk" :title="withLoadUnload
        ? '跑 sampling_multi_cycle: 准备 → 上料 → 多条带 → 下料'
        : '只跑 sampling_multi_execute: 板已在工位上时用'">
        <input type="checkbox" v-model="withLoadUnload" /> 含上下料
      </label>
      <span class="grow" />
      <span class="badge" :class="debug.status">{{ debug.status || 'idle' }}</span>
      <span v-if="errorCount" class="cell-err" role="status">{{ errorCount }} 项有误</span>
      <button class="tb save" :disabled="!canStart" @click="start">
        启动 · {{ rows.length }} 个样品 ({{ opName }})
      </button>
      <button class="tb danger" :disabled="!owned" @click="askTerminate"
              title="软停机器人, 不报警, 结束本次运行">终止</button>
      <button class="tb danger" :disabled="!owned" @click="debug.estop()"
              title="急停: 失能臂并报警, 需清警重新使能">急停</button>
    </div>
    <p v-if="localError" class="cell-err">{{ localError }}</p>

    <div class="sm-scroll">
      <table class="sm-tab">
        <thead>
          <tr>
            <th scope="col" class="c-idx">#</th>
            <th scope="col" class="c-note">备注</th>
            <th scope="col" class="c-well">孔位 <small class="muted">必填</small></th>
            <th scope="col" v-for="c in GEOM_COLS" :key="c.key">
              {{ c.title }} <small class="muted">必填 · {{ geomMeta(c.key).min }}~{{ geomMeta(c.key).max }}</small>
            </th>
            <th scope="col" v-for="c in visibleParamCols" :key="c.key">
              {{ c.title }} <small class="muted">{{ colHint(c) }}</small>
            </th>
            <th scope="col" class="c-ops">操作</th>
          </tr>
        </thead>
        <tbody>
          <!-- 单元格可访问名 = 表头文字 + 第N行; 错误格 aria-invalid + title 给出原因 (cellErrors 本身就是原因文案) -->
          <tr v-for="(row, i) in rows" :key="row._id" :class="{ live: isLiveRow(row) }"
              :aria-current="isLiveRow(row) ? 'true' : null">
            <td class="c-idx"><span v-if="isLiveRow(row)" class="live-mark" aria-hidden="true">▶</span>{{ i + 1 }}</td>
            <td><input v-model="row.label" placeholder="样品名" :aria-label="`备注 第${i + 1}行`" /></td>
            <td>
              <input v-model="row.well" placeholder="A1" :class="{ err: cellErrors[i].well }"
                     :aria-label="`孔位 第${i + 1}行`" :aria-invalid="!!cellErrors[i].well"
                     :title="cellErrors[i].well || null" />
            </td>
            <td v-for="c in GEOM_COLS" :key="c.key">
              <input type="number" step="any" v-model="row[c.key]"
                     :min="geomMeta(c.key).min" :max="geomMeta(c.key).max"
                     :placeholder="String(geomMeta(c.key).base ?? '')"
                     :class="{ err: cellErrors[i][c.key] }"
                     :aria-label="`${c.title} 第${i + 1}行`" :aria-invalid="!!cellErrors[i][c.key]"
                     :title="cellErrors[i][c.key] || null" />
            </td>
            <td v-for="c in visibleParamCols" :key="c.key">
              <select v-if="meta(c.key).enum" v-model="row[c.key]" :class="{ err: cellErrors[i][c.key] }"
                      :aria-label="`${c.title} 第${i + 1}行`" :aria-invalid="!!cellErrors[i][c.key]"
                      :title="cellErrors[i][c.key] || null">
                <option value="">缺省</option>
                <option v-for="o in meta(c.key).enum" :key="o" :value="o">{{ o }}</option>
              </select>
              <!-- 缩放列 (供液泵速): 界面 mL/min, 存回底层 DT V; 与 DebugDock 同一换算 -->
              <input v-else-if="meta(c.key).scale" type="number"
                     :min="toDisplay(meta(c.key).min, meta(c.key).scale)"
                     :max="toDisplay(meta(c.key).max, meta(c.key).scale)" :step="meta(c.key).scale"
                     :placeholder="String(toDisplay(meta(c.key).default, meta(c.key).scale))"
                     :value="row[c.key] === '' ? '' : toDisplay(row[c.key], meta(c.key).scale)"
                     :class="{ err: cellErrors[i][c.key] }"
                     :aria-label="`${c.title} 第${i + 1}行`" :aria-invalid="!!cellErrors[i][c.key]"
                     :title="cellErrors[i][c.key] || null"
                     @change="onScaledCell(row, c.key, $event)" />
              <input v-else type="number" :step="meta(c.key).type === 'INT' ? 1 : 'any'"
                     v-model="row[c.key]" :min="meta(c.key).min" :max="meta(c.key).max"
                     :placeholder="String(meta(c.key).default ?? '')"
                     :class="{ err: cellErrors[i][c.key] }"
                     :aria-label="`${c.title} 第${i + 1}行`" :aria-invalid="!!cellErrors[i][c.key]"
                     :title="cellErrors[i][c.key] || null" />
            </td>
            <td class="c-ops">
              <button class="mini" :disabled="i === 0" @click="moveRow(i, -1)" title="上移"
                      :aria-label="`上移 第${i + 1}行`">↑</button>
              <button class="mini" :disabled="i === rows.length - 1" @click="moveRow(i, 1)" title="下移"
                      :aria-label="`下移 第${i + 1}行`">↓</button>
              <button class="mini" @click="dupRow(i)" title="复制本行"
                      :aria-label="`复制 第${i + 1}行`">⧉</button>
              <button class="mini" @click="delRow(i)" title="删除本行"
                      :aria-label="`删除 第${i + 1}行`">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ul class="sm-msgs">
      <li v-for="m in rowMessages" :key="m.key" :class="m.bad ? 'cell-err' : 'cell-warn'">{{ m.text }}</li>
    </ul>
    <p v-if="!rows.length" class="empty">还没有样品, 点「+ 添加样品」开始。</p>

    <div class="sm-knobs">
      <div class="sm-knob-h">流程缺省 <small class="muted">行内留空的参数用这里的值; 量程来自流程 YAML</small></div>
      <table class="sm-tab knob-tab">
        <tbody>
          <tr v-for="k in knobs" :key="k.name">
            <td class="k-name">{{ (k.ui && k.ui.label) || k.name }}</td>
            <td>
              <select v-if="k.ui && k.ui.enum" v-model="knobDraft[k.name]" :class="{ err: knobErrors[k.name] }"
                      :aria-label="`流程缺省 ${(k.ui && k.ui.label) || k.name}`"
                      :aria-invalid="!!knobErrors[k.name]">
                <option v-for="o in k.ui.enum" :key="o" :value="o">{{ o }}</option>
              </select>
              <input v-else-if="k.ui && k.ui.scale" type="number"
                     :min="toDisplay(k.ui.min, k.ui.scale)" :max="toDisplay(k.ui.max, k.ui.scale)"
                     :step="k.ui.scale" :class="{ err: knobErrors[k.name] }"
                     :aria-label="`流程缺省 ${(k.ui && k.ui.label) || k.name}`"
                     :aria-invalid="!!knobErrors[k.name]"
                     :value="toDisplay(knobDraft[k.name], k.ui.scale)"
                     @change="onScaledKnob(k.name, $event)" />
              <input v-else type="number" :step="k.type === 'INT' ? 1 : 'any'"
                     :min="k.ui && k.ui.min" :max="k.ui && k.ui.max"
                     :aria-label="`流程缺省 ${(k.ui && k.ui.label) || k.name}`"
                     :aria-invalid="!!knobErrors[k.name]"
                     v-model="knobDraft[k.name]" :class="{ err: knobErrors[k.name] }" />
            </td>
            <td class="k-cmt">
              <small v-if="knobErrors[k.name]" class="cell-err">{{ knobErrors[k.name] }}</small>
              <small v-else class="muted">{{ (k.ui && k.ui.group) || '' }}</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.sm-panel { padding: 10px 12px; display: flex; flex-direction: column; gap: 8px; overflow: auto; }
.sm-head h3 { margin: 0 0 4px; }
.sm-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.sm-bar .grow { flex: 1; }
.sm-scroll { overflow-x: auto; }
.sm-tab { border-collapse: collapse; font-size: var(--fs-12); }
.sm-tab th, .sm-tab td { border: 1px solid rgba(128, 128, 128, 0.28); padding: 2px 4px; white-space: nowrap; }
.sm-tab th { text-align: left; font-weight: 600; }
.sm-tab th small { display: block; font-weight: 400; }
.sm-tab input, .sm-tab select { width: 88px; box-sizing: border-box; }
.sm-tab .c-idx { width: 24px; text-align: center; }
.sm-tab .c-note input { width: 96px; }
.sm-tab .c-well input { width: 56px; }
.sm-tab tr.live { outline: 2px solid var(--accent, #3b82f6); outline-offset: -2px; }
/* 执行行的 ▶ 字形: 不纯靠轮廓色标状态 (色弱/高对比模式可辨); 读屏走 tr[aria-current] */
.live-mark { color: var(--accent, #3b82f6); margin-right: 2px; }
.c-ops { white-space: nowrap; }
.sm-msgs { list-style: none; margin: 0; padding: 0; }
.sm-msgs li { padding: 1px 0; }
.sm-knobs { margin-top: 6px; }
.sm-knob-h { font-weight: 600; opacity: 0.85; padding: 2px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.25); }
.knob-tab { margin-top: 4px; }
.knob-tab .k-name { min-width: 180px; }
.knob-tab .k-cmt { min-width: 120px; }
</style>
