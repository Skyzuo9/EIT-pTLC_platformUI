<script setup>
// 板位对位控制台: .163 对位相机的点样视觉零点一键示教 (与 .169 拍照分析的 /vision 分开)。
// 流程: 坐正空白板 -> DEBUG -> 运行示教(机器人取板到 P86 拍照测板姿) -> 预览新旧零点+差值 -> 确认应用(写回+热更)。
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { usePoll } from '../composables/usePoll.js'

const controlMode = ref('')
const status = reactive({ reference: null, bridge: null })
const teachResult = ref(null)
const loading = reactive({ status: false, teach: false, apply: false })
const localError = ref('')
const applyMsg = ref('')

const busy = computed(() => loading.teach || loading.apply)
const isDebug = computed(() => controlMode.value === 'DEBUG')
const canTeach = computed(() => isDebug.value && !busy.value)
const measured = computed(() => teachResult.value?.measured || null)
const canApply = computed(
  () => isDebug.value && !busy.value && !!measured.value?.valid && !!teachResult.value?.sane
)

function fmt(v, d = 1) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(d) : String(v)
}

function fmtPair(pair, d = 0) {
  if (!Array.isArray(pair) || pair.length < 2) return '-'
  return `${fmt(pair[0], d)}, ${fmt(pair[1], d)}`
}

async function refreshMode() {
  try {
    const m = await api.getMode()
    controlMode.value = String(m?.control_mode || m?.mode || '').toUpperCase()
  } catch (e) {
    controlMode.value = ''
  }
}

async function refreshStatus(opts = {}) {
  if (!opts.silent) loading.status = true
  try {
    const s = await api.plateAlignStatus()
    status.reference = s?.reference || null
    status.bridge = s?.bridge || null
    if (!opts.silent) localError.value = ''
  } catch (e) {
    if (!opts.silent) localError.value = errText(e)
  } finally {
    if (!opts.silent) loading.status = false
  }
}

async function refreshAll(opts = {}) {
  await Promise.all([refreshMode(), refreshStatus(opts)])
}

async function runTeach() {
  if (!canTeach.value) return
  if (!(await confirmAction({
    title: '运行示教',
    message: [
      '将驱动机器人从点样巢取板举到 P86 拍照并放回。',
      '请确认: 空白板已正确坐进点样巢, 现场无人无障碍。',
    ],
    level: 'danger',
    confirmText: '运行示教',
  }))) return
  loading.teach = true
  localError.value = ''
  applyMsg.value = ''
  teachResult.value = null
  try {
    teachResult.value = await api.plateAlignTeach()
  } catch (e) {
    localError.value = errText(e)
  } finally {
    loading.teach = false
    refreshStatus({ silent: true })
  }
}

async function applyRef() {
  if (!canApply.value || !measured.value) return
  if (!(await confirmAction({
    title: '应用为新零点',
    message: '把测得位姿写为新的视觉零点并热更 Bridge, 覆盖当前零点。',
    level: 'danger',
    confirmText: '应用',
  }))) return
  loading.apply = true
  localError.value = ''
  try {
    const m = measured.value
    const res = await api.plateAlignApply(m.u, m.v, m.theta, true)
    const r = res?.reference || {}
    applyMsg.value = `已写入新零点 u0=${fmt(r.u0)} v0=${fmt(r.v0)} θ0=${fmt(r.theta0, 2)}`
      + (res?.reloaded ? ' (Bridge 已热更, 下次放板即用新零点)' : ' (Bridge 未热更, 请手动重启 Bridge)')
    teachResult.value = null
    await refreshStatus({ silent: true })
  } catch (e) {
    localError.value = errText(e)
  } finally {
    loading.apply = false
  }
}

// 3s 轮询; 首拍非静默 = 复刻原 onMounted 首刷 (挂载即暴露不可达), 后续静默不刷错误
let statusPolledOnce = false
const statusPoll = usePoll(async () => {
  if (busy.value) return // busy 门: 示教/应用进行中不抢状态请求
  await refreshAll({ silent: statusPolledOnce })
  statusPolledOnce = true
}, 3000)

onMounted(() => {
  statusPoll.start()
})
</script>

<template>
  <div class="pa">
    <header class="pa-head">
      <div>
        <h3>板位对位 · 视觉零点示教</h3>
        <p>.163 对位相机 · 点样放板零点一键重标</p>
      </div>
      <div class="pa-head-actions">
        <span class="mode-pill" :class="{ debug: isDebug }">{{ controlMode || '模式未知' }}</span>
        <button class="btn ghost" :disabled="loading.status || busy" @click="refreshAll()">
          {{ loading.status ? '刷新中…' : '刷新状态' }}
        </button>
      </div>
    </header>

    <div v-if="localError" class="pa-err" role="status">{{ localError }}</div>

    <section class="pa-card">
      <div class="card-head"><h4>当前零点参考</h4></div>
      <dl class="metric-grid">
        <dt>u0 (板中心 X 像素)</dt><dd>{{ fmt(status.reference?.u0) }}</dd>
        <dt>v0 (板中心 Y 像素)</dt><dd>{{ fmt(status.reference?.v0) }}</dd>
        <dt>θ0 (板倾角 deg)</dt><dd>{{ fmt(status.reference?.theta0, 2) }}</dd>
        <dt>名义板位 expect_center</dt><dd>{{ fmtPair(status.reference?.expect_center) }}</dd>
        <dt>Bridge</dt>
        <dd v-if="status.bridge">
          <span :class="status.bridge.last_error ? 'bad' : 'ok'">
            {{ status.bridge.last_error ? '有错误' : '在线' }}
          </span>
          <span class="muted" v-if="status.bridge.uptime_s != null"> · uptime {{ fmt(status.bridge.uptime_s, 0) }}s</span>
          <span class="bad" v-if="status.bridge.last_error"> · {{ status.bridge.last_error }}</span>
        </dd>
        <dd v-else class="muted">不可达</dd>
      </dl>
    </section>

    <section class="pa-card">
      <div class="card-head">
        <h4>一键示教</h4>
        <span class="muted">取板 → P86 拍照 → 放回 (机器人运动, 约需 30–60s)</span>
      </div>
      <ol class="steps">
        <li>把一块<strong>空白板正确坐进点样巢</strong> (由夹具定位到正确位置)。</li>
        <li>控制模式切到 <strong>DEBUG</strong> (补光 DO7 由后端示教期自动开关)。</li>
        <li>点"运行示教": 机器人取板举到 P86 拍照, 测出板真实位姿并与当前零点比对。</li>
        <li>核对差值合理后, 点"应用为新零点"写回并热更。</li>
      </ol>
      <div class="pa-actions">
        <button class="btn run" :disabled="!canTeach" :title="isDebug ? '驱动机器人取板到 P86 拍照测姿' : '示教仅 DEBUG 模式可用'" @click="runTeach">
          {{ loading.teach ? '示教运行中 (机器人取板到 P86)…' : '运行示教' }}
        </button>
        <span v-if="!isDebug" class="muted">切到 DEBUG 模式后可运行</span>
      </div>
    </section>

    <section v-if="teachResult" class="pa-card">
      <div class="card-head">
        <h4>示教结果</h4>
        <span :class="teachResult.sane && measured?.valid ? 'ok' : 'bad'">
          {{ measured?.valid ? (teachResult.sane ? '可采纳' : '疑似误检') : '未识别到板' }}
        </span>
      </div>
      <div v-if="!measured?.valid" class="pa-warn">{{ teachResult.message }}</div>
      <dl class="metric-grid">
        <dt>测得 u / v</dt><dd>{{ fmt(measured?.u) }} / {{ fmt(measured?.v) }}</dd>
        <dt>测得 θ (deg)</dt><dd>{{ fmt(measured?.theta, 2) }}</dd>
        <dt>当前零点 u0 / v0 / θ0</dt>
        <dd>{{ fmt(teachResult.current_reference?.u0) }} / {{ fmt(teachResult.current_reference?.v0) }} / {{ fmt(teachResult.current_reference?.theta0, 2) }}</dd>
        <dt>Δ 中心 (像素)</dt><dd>{{ fmt(teachResult.delta_px) }}</dd>
        <dt>Δθ (deg)</dt><dd>{{ fmt(teachResult.delta_theta_deg, 2) }}</dd>
        <dt>合理性</dt><dd :class="teachResult.sane ? 'ok' : 'bad'">{{ teachResult.message }}</dd>
      </dl>
      <div class="pa-actions">
        <button class="btn" :disabled="!canApply" :title="canApply ? '写回 reference 并热更 Bridge' : '需 DEBUG + 采值有效且合理'" @click="applyRef">
          {{ loading.apply ? '应用中…' : '应用为新零点' }}
        </button>
        <span v-if="applyMsg" class="ok">{{ applyMsg }}</span>
      </div>
    </section>

    <div v-else-if="applyMsg" class="pa-card"><span class="ok">{{ applyMsg }}</span></div>
  </div>
</template>

<style scoped>
.pa { padding: 4px 2px 24px; color: var(--text); max-width: 760px; }
.pa-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.pa-head h3 { margin: 0; font-size: var(--fs-17); line-height: 1.3; color: var(--text-strong); }
.pa-head p { margin: 3px 0 0; color: var(--muted); font-size: var(--fs-12); }
.pa-head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
/* .mode-pill 基础样式走全局 (style.css), 此处只留状态修饰 */
.mode-pill.debug { background: var(--ok-soft); color: var(--ok-strong); }
.pa-err { color: var(--bad-strong); font-size: var(--fs-13); padding: 8px 10px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 12px; }
.pa-warn { color: var(--bad-strong); font-size: var(--fs-13); padding: 7px 9px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 10px; }

.pa-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.card-head h4 { margin: 0; font-size: 15px; color: var(--text-strong); }

.steps { margin: 0 0 10px; padding-left: 20px; color: var(--subtle); font-size: var(--fs-13); line-height: 1.7; }
.steps strong { color: var(--text-strong); }

.metric-grid { display: grid; grid-template-columns: minmax(140px, 0.8fr) minmax(0, 1fr); gap: 0; margin: 0; border: 1px solid var(--border-soft); border-radius: 6px; overflow: hidden; }
.metric-grid dt, .metric-grid dd { margin: 0; padding: 6px 9px; border-bottom: 1px solid var(--border-soft); font-size: var(--fs-12); min-width: 0; }
.metric-grid dt { color: var(--subtle); background: var(--surface-2); font-weight: 650; }
.metric-grid dd { color: var(--text); word-break: break-word; }
.metric-grid dt:nth-last-child(2), .metric-grid dd:last-child { border-bottom: 0; }

.pa-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
/* .btn 全套样式走全局 (style.css) */
.muted { color: var(--muted); font-size: var(--fs-12); }
.ok { color: var(--ok-strong); font-size: var(--fs-12); font-weight: 650; }
.bad { color: var(--bad-strong); font-size: var(--fs-12); font-weight: 650; }
</style>
