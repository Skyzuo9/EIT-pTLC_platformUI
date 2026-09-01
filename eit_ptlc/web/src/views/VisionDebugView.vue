<script setup>
// 视觉调试台: 单模块拍照/识别验证，不接生产流程，不建历史层。
import { computed, onMounted, reactive, ref } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useDirtyGuard } from '../composables/useDirtyGuard.js'
import { usePoll } from '../composables/usePoll.js'
import { useQuerySync } from '../composables/useQuerySync.js'
import ImageLightbox from '../components/ImageLightbox.vue'
import OverlayLegend from '../components/OverlayLegend.vue'
import RecognitionParams from '../components/RecognitionParams.vue'

const DEFAULT_CAMERA_PARAMS = {
  exposure_time_us: 1000000,
  gain: 1.0,
  uv_on_time_ms: 1000,
}

const DEFAULT_RECOGNITION_PARAMS = {
  image_plate_orientation: 'rot180',
  auto_rectify_tilt: true,
  rectify_min_angle_deg: 0.5,
  min_row_score: 5.0,
  image_plate_rotation_deg: null,
}

const CAMERA_PARAM_KEYS = ['exposure_time_us', 'gain', 'uv_on_time_ms']
const RECOGNITION_PARAM_KEYS = [
  'image_plate_orientation',
  'auto_rectify_tilt',
  'rectify_min_angle_deg',
  'min_row_score',
  'image_plate_rotation_deg',
]

const state = reactive({
  revision: 0,
  updated_at: '',
  before: { source: 'none', url: '', quality_url: '', filename: '' },
  after: { source: 'none', url: '', quality_url: '', filename: '' },
  camera_params: { ...DEFAULT_CAMERA_PARAMS },
  recognition_params: { ...DEFAULT_RECOGNITION_PARAMS },
  capture_quality: { before: null, after: null },
  uv_timing: null,
  analysis: null,
  source_context: null,
  error: null,
})

const loading = reactive({
  state: false,
  mode: false,
  capture: { before: false, after: false },
  upload: { before: false, after: false },
  analyze: false,
  cncPreview: false,
  loadCase: false,
})

const controlMode = ref('')
const lightbox = ref([])        // ImageLightbox 吃一组图; 此处单图, 装一个元素
// 触发源是包住 img 的 btn-bare 按钮 (键盘可开灯箱); 从按钮取 img, 兼容鼠标/键盘两种激活
function openLightbox(evt) {
  const img = evt?.currentTarget?.querySelector?.('img') || (evt?.target?.tagName === 'IMG' ? evt.target : null)
  if (img?.src) lightbox.value = [{ src: img.src, alt: img.alt || '' }]
}
const localError = ref('')
const applyMsg = ref('')
const fileBefore = ref(null)
const fileAfter = ref(null)
const dirty = reactive({ camera: false, recognition: false })
const cases = ref([])
const casesTruncated = ref(false)
const selectedCase = ref('')
const selectedCncBand = ref('')

// 选中 case / 预览条带进 URL: 刷新不丢/可深链 (band 会被 normalizeState 按分析结果校正)
useQuerySync('case', selectedCase, { defaultValue: '' })
useQuerySync('band', selectedCncBand, { defaultValue: '' })

// 未保存守卫: 相机/识别参数改了还没经拍摄/分析确认就离开时拦一道
useDirtyGuard(() => dirty.camera || dirty.recognition, {
  message: '拍照/识别参数有未保存修改, 离开将丢弃。',
})
let stateFetchInFlight = false
let modeFetchInFlight = false

const busy = computed(() =>
  loading.capture.before || loading.capture.after ||
  loading.upload.before || loading.upload.after || loading.analyze || loading.loadCase
  || loading.cncPreview
)

const hasBefore = computed(() => !!state.before?.url)
const hasAfter = computed(() => !!state.after?.url)
const canAnalyze = computed(() => hasBefore.value && hasAfter.value && !busy.value)
const canCapture = computed(() => controlMode.value === 'DEBUG' && !busy.value)
const pageError = computed(() => localError.value || state.error || '')
const analysisUrls = computed(() => state.analysis?.urls || {})
const solventFront = computed(() => parseSolventFront(state.analysis?.summary))
const liquidObservation = computed(() => state.source_context?.liquid_observation || null)
const liquidMeasurement = computed(() => liquidObservation.value?.measurement || null)

function pickNumber(value, fallback) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function normalizeFrame(frame) {
  return {
    source: frame?.source || 'none',
    url: frame?.url || '',
    quality_url: frame?.quality_url || '',
    filename: frame?.filename || '',
  }
}

function mergeKnown(target, incoming, defaults, keys) {
  for (const key of keys) {
    if (incoming && incoming[key] !== undefined && incoming[key] !== null) {
      target[key] = incoming[key]
    } else if (target[key] === undefined || target[key] === null) {
      target[key] = defaults[key]
    }
  }
}

function ensureDefaults(target, defaults, keys) {
  for (const key of keys) {
    if (target[key] === undefined || target[key] === null) target[key] = defaults[key]
  }
}

function pickParams(source, keys) {
  return keys.reduce((acc, key) => {
    acc[key] = source[key]
    return acc
  }, {})
}

function sameParams(current, submitted, keys) {
  return keys.every((key) => current[key] === submitted[key])
}

function markCameraDirty() {
  dirty.camera = true
}

function markRecognitionDirty() {
  dirty.recognition = true
}

function normalizeState(payload, options = {}) {
  const next = payload || {}
  state.revision = pickNumber(next.revision, state.revision)
  state.updated_at = next.updated_at || ''
  state.before = normalizeFrame(next.before)
  state.after = normalizeFrame(next.after)
  if (options.syncCamera ?? !dirty.camera) {
    mergeKnown(state.camera_params, next.camera_params, DEFAULT_CAMERA_PARAMS, CAMERA_PARAM_KEYS)
  } else {
    ensureDefaults(state.camera_params, DEFAULT_CAMERA_PARAMS, CAMERA_PARAM_KEYS)
  }
  if (options.syncRecognition ?? !dirty.recognition) {
    mergeKnown(
      state.recognition_params,
      next.recognition_params,
      DEFAULT_RECOGNITION_PARAMS,
      RECOGNITION_PARAM_KEYS
    )
  } else {
    ensureDefaults(state.recognition_params, DEFAULT_RECOGNITION_PARAMS, RECOGNITION_PARAM_KEYS)
  }
  state.capture_quality = {
    before: next.capture_quality?.before || null,
    after: next.capture_quality?.after || null,
  }
  state.uv_timing = next.uv_timing || null
  state.analysis = next.analysis || null
  state.source_context = next.source_context || null
  state.error = next.error || null
  const bandIds = (state.analysis?.bands || []).filter((band) => !band.is_origin).map((band) => band.band_id)
  if (!bandIds.includes(selectedCncBand.value)) selectedCncBand.value = bandIds[0] || ''
}

async function refreshMode(options = {}) {
  if (modeFetchInFlight) return
  modeFetchInFlight = true
  if (!options.silent) loading.mode = true
  try {
    const mode = await api.getMode()
    controlMode.value = String(mode?.control_mode || mode?.mode || '').toUpperCase()
  } catch (e) {
    controlMode.value = ''
  } finally {
    if (!options.silent) loading.mode = false
    modeFetchInFlight = false
  }
}

async function fetchState(options = {}) {
  if (stateFetchInFlight) return
  stateFetchInFlight = true
  if (!options.silent) loading.state = true
  if (!options.silent) localError.value = ''
  try {
    const next = await api.getVisionDebugState()
    normalizeState(next)
  } catch (e) {
    if (!options.silent) localError.value = errText(e)
  } finally {
    if (!options.silent) loading.state = false
    stateFetchInFlight = false
  }
}

async function refreshAll(options = {}) {
  await Promise.all([fetchState(options), refreshMode(options)])
}

async function capture(role) {
  if (!canCapture.value) return
  loading.capture[role] = true
  localError.value = ''
  const submitted = pickParams(state.camera_params, CAMERA_PARAM_KEYS)
  try {
    const next = await api.captureVisionDebug(role, submitted)
    if (sameParams(state.camera_params, submitted, CAMERA_PARAM_KEYS)) {
      dirty.camera = false
      normalizeState(next, { syncCamera: true })
    } else {
      normalizeState(next, { syncCamera: false })
    }
  } catch (e) {
    localError.value = errText(e)
    await fetchState({ silent: true })
  } finally {
    loading.capture[role] = false
  }
}

function triggerUpload(role) {
  const el = role === 'before' ? fileBefore.value : fileAfter.value
  if (el) el.click()
}

async function handleUpload(role, event) {
  const file = event.target.files?.[0]
  if (!file) return
  loading.upload[role] = true
  localError.value = ''
  try {
    const next = await api.uploadVisionDebug(role, file)
    normalizeState(next)
  } catch (e) {
    localError.value = errText(e)
    await fetchState({ silent: true })
  } finally {
    loading.upload[role] = false
    const el = role === 'before' ? fileBefore.value : fileAfter.value
    if (el) el.value = ''
  }
}

async function analyze() {
  if (!canAnalyze.value) return
  loading.analyze = true
  localError.value = ''
  const submitted = pickParams(state.recognition_params, RECOGNITION_PARAM_KEYS)
  try {
    const next = await api.analyzeVisionDebug(submitted)
    if (sameParams(state.recognition_params, submitted, RECOGNITION_PARAM_KEYS)) {
      dirty.recognition = false
      normalizeState(next, { syncRecognition: true })
    } else {
      normalizeState(next, { syncRecognition: false })
    }
  } catch (e) {
    localError.value = errText(e)
    await fetchState({ silent: true })
  } finally {
    loading.analyze = false
  }
}

async function generateCncPreview() {
  if (!selectedCncBand.value || loading.cncPreview) return
  loading.cncPreview = true
  localError.value = ''
  try {
    const next = await api.previewVisionDebugCnc(selectedCncBand.value)
    normalizeState(next, { syncRecognition: false, syncCamera: false })
  } catch (e) {
    localError.value = errText(e)
  } finally {
    loading.cncPreview = false
  }
}

// 把调试台当前(最近一次分析所用)识别参数写回 config.vision 单一真源。
// 生产 analyze 运行期实时读 config.vision (bootstrap._analyze_live), 故下次分析即生效, 无需重启。
// applyMsg 区自带 role="status", 故成功不再重复 announce (避免双读)。
const applyA = useAsyncAction(
  async () => {
    applyMsg.value = ''
    localError.value = ''
    await api.applyVisionToProduction()
    applyMsg.value = '已写入 config.vision (生产 analyze 下次即用)'
  },
  { errorPrefix: '应用到生产失败', onError: (msg) => { localError.value = msg } },
)

async function applyToProduction() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '应用到生产配置',
    message: '把最近一次分析所用的识别参数写入 config.vision 生产真源 (生产 analyze 实时读取, 下次即生效)。',
    ackText: '我已在调试 case 上验证过这组参数',
    confirmText: '写入生产',
  })
  if (!ok) return
  return applyA.run()
}

async function refreshCases() {
  try {
    const res = await api.listVisionDebugCases()
    cases.value = res?.cases || []
    casesTruncated.value = !!res?.truncated
  } catch (e) {
    localError.value = errText(e)
  }
}

async function loadCase() {
  if (!selectedCase.value || busy.value) return
  loading.loadCase = true
  localError.value = ''
  try {
    const next = await api.loadVisionDebugCase(selectedCase.value)
    normalizeState(next)
  } catch (e) {
    localError.value = errText(e)
  } finally {
    loading.loadCase = false
  }
}

function imageUrl(url) {
  if (!url) return ''
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}rev=${encodeURIComponent(state.revision || 0)}`
}

function roleQualityUrl(role) {
  const frame = state[role]
  return imageUrl(frame?.quality_url || analysisUrls.value?.[`${role}_quality`] || '')
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : String(value)
}

function fmtBool(value) {
  if (value === true) return '是'
  if (value === false) return '否'
  return '-'
}

function fmtPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  const n = Number(value)
  if (!Number.isFinite(n)) return String(value)
  return `${(n * 100).toFixed(2)}%`
}

function fmtPair(value, unit = '') {
  if (!Array.isArray(value) || value.length < 2) return '-'
  return `${fmt(value[0])}, ${fmt(value[1])}${unit ? ` ${unit}` : ''}`
}

function fmtMargins(value) {
  if (!value) return '-'
  if (Array.isArray(value)) return value.map((v) => fmt(v, 0)).join(' / ')
  if (typeof value === 'object') {
    return ['left', 'right', 'top', 'bottom']
      .filter((k) => value[k] !== undefined)
      .map((k) => `${k}:${fmt(value[k], 0)}`)
      .join(' / ') || JSON.stringify(value)
  }
  return String(value)
}

function bandRf(band) {
  return band?.normalized_develop_height ?? band?.Rf ?? band?.rf
}

function bandCentroid(band) {
  const c = band?.centroid_cm || band?.centroid
  if (Array.isArray(c)) return fmtPair(c, 'cm')
  if (c && typeof c === 'object') return `${fmt(c.x_cm ?? c.x)}, ${fmt(c.y_cm ?? c.y)} cm`
  return '-'
}

function parseSolventFront(summary) {
  const src = summary?.solvent_front || summary?.solventFront || summary?.front || null
  const source =
    src?.source ||
    src?.method ||
    summary?.solvent_front_source ||
    summary?.solvent_front_method ||
    ''
  const y =
    src?.y_px ??
    src?.position_px ??
    src?.y ??
    summary?.solvent_front_y_px ??
    summary?.solvent_front_px ??
    null
  const label = source || (y !== null ? 'detected' : '-')
  return {
    source: label,
    position: y,
    fallback: !!src?.is_fallback || !!summary?.solvent_front_is_fallback || String(label).toLowerCase().includes('fallback'),
  }
}

function qualityRows(metrics) {
  return [
    ['板中心偏移', fmtPair(metrics?.plate_center_offset_mm, 'mm')],
    ['旋转角', `${fmt(metrics?.plate_rotation_deg)} deg`],
    ['透视偏斜', `${fmt(metrics?.perspective_skew_deg)} deg`],
    ['四边留白', fmtMargins(metrics?.margin_px)],
    ['平均亮度', fmt(metrics?.mean_brightness)],
    ['过曝比例', fmtPercent(metrics?.overexposed_ratio)],
    ['欠曝比例', fmtPercent(metrics?.underexposed_ratio)],
    ['清晰度', fmt(metrics?.sharpness)],
    ['图像尺寸', metrics?.image_width && metrics?.image_height ? `${metrics.image_width} x ${metrics.image_height}` : '-'],
  ]
}

// 图位动态比例: capture_quality (analyze 后) 或 capture/upload 返回体 (后端新增字段) 里的
// 图像尺寸 → aspect-ratio, 图片到位不再顶开下方内容; 无尺寸时回落容器 min-height 兜底。
// 拍照相机整幅传感器无固定比例契约 (app.yaml width/height=0), 故不能写死, 只能按数据设。
function imgBoxStyle(role) {
  const q = state.capture_quality[role]
  const w = q?.image_width || state[role]?.image_width
  const h = q?.image_height || state[role]?.image_height
  return w && h ? { aspectRatio: `${w} / ${h}` } : undefined
}

// 对象值以缩进 JSON 折叠展示 (details/pre), 标量原样; 第三元标记是否对象
function reportRows(report) {
  if (!report || typeof report !== 'object') return []
  return Object.entries(report).map(([key, value]) => {
    const isObj = !!value && typeof value === 'object'
    return [key, isObj ? JSON.stringify(value, null, 2) : String(value), isObj]
  })
}

// 2s 轮询; 首拍非静默 = 复刻原 onMounted 首刷 (挂载即暴露不可达)。
// loading 门: 手动「刷新状态」(非静默拉取) 进行中跳拍, 避免抢 loading.state 指示
let statePolledOnce = false
const statePoll = usePoll(async () => {
  if (loading.state) return
  await refreshAll({ silent: statePolledOnce })
  statePolledOnce = true
}, 2000)

onMounted(() => {
  statePoll.start()
  refreshCases()
})
</script>

<template>
  <div class="vd">
    <header class="vd-head">
      <div>
        <h2>视觉调试台</h2>
        <p>单模块拍照与双帧识别验证</p>
      </div>
      <div class="vd-head-actions">
        <span class="mode-pill" :class="{ debug: controlMode === 'DEBUG' }">
          {{ controlMode || '模式未知' }}
        </span>
        <button class="btn ghost" :disabled="loading.state || loading.mode" @click="refreshAll()">
          {{ loading.state ? '刷新中…' : '刷新状态' }}
        </button>
      </div>
    </header>

    <input ref="fileBefore" type="file" accept="image/*" hidden @change="handleUpload('before', $event)" />
    <input ref="fileAfter" type="file" accept="image/*" hidden @change="handleUpload('after', $event)" />

    <div v-if="pageError" role="alert" class="vd-err">{{ pageError }}</div>

    <section class="vd-params">
      <fieldset class="vd-param-group">
        <legend>拍照参数</legend>
        <label class="vd-field">
          <span>曝光 us</span>
          <input
            v-model.number="state.camera_params.exposure_time_us"
            type="number"
            inputmode="numeric"
            min="1"
            step="1000"
            @input="markCameraDirty"
          />
        </label>
        <label class="vd-field">
          <span>增益</span>
          <input
            v-model.number="state.camera_params.gain"
            type="number"
            inputmode="decimal"
            min="0"
            step="0.1"
            @input="markCameraDirty"
          />
        </label>
        <label class="vd-field">
          <span>UV总时长 ms</span>
          <input
            v-model.number="state.camera_params.uv_on_time_ms"
            type="number"
            inputmode="numeric"
            min="1"
            step="10"
            @input="markCameraDirty"
          />
        </label>
        <div class="uv-note">
          <span>请求 {{ fmt(state.uv_timing?.requested_uv_on_ms, 0) }} ms</span>
          <span>实际 {{ fmt(state.uv_timing?.actual_uv_on_ms, 0) }} ms</span>
          <span>关灯 {{ fmtBool(state.uv_timing?.line1_close_ok) }}</span>
          <span :class="{ danger: state.uv_timing?.over_limit }">超限 {{ fmtBool(state.uv_timing?.over_limit) }}</span>
          <span v-if="state.uv_timing?.simulated">Mock</span>
        </div>
      </fieldset>

      <fieldset class="vd-param-group">
        <legend>识别参数</legend>
        <RecognitionParams
          v-model="state.recognition_params"
          mode="value"
          @change="markRecognitionDirty"
        />
      </fieldset>
    </section>

    <section class="vd-cases">
      <label class="vd-field case-field">
        <span>生产 case</span>
        <select v-model="selectedCase">
          <option value="">选择要复盘的生产分析…</option>
          <option v-for="c in cases" :key="c.summary_dir" :value="c.summary_dir">
            {{ c.id }} · {{ (c.mtime_iso || '').slice(0, 19).replace('T', ' ') }}
          </option>
        </select>
      </label>
      <button class="btn" :disabled="busy || loading.loadCase || !selectedCase" @click="loadCase">
        {{ loading.loadCase ? '载入中…' : '载入' }}
      </button>
      <button class="btn ghost" @click="refreshCases">刷新列表</button>
      <span v-if="casesTruncated" class="muted">仅显示最近 50 个 case</span>
    </section>

    <section class="vd-images">
      <article v-for="role in ['before', 'after']" :key="role" class="vd-pane">
        <div class="pane-top">
          <div>
            <h4>{{ role === 'before' ? 'Before' : 'After' }}</h4>
            <p>{{ state[role].filename || state[role].source || '未加载' }}</p>
          </div>
          <div class="pane-actions">
            <button
              class="btn"
              :disabled="!canCapture"
              :title="controlMode === 'DEBUG' ? '执行一次原子拍照' : '拍照仅 DEBUG 模式可用'"
              @click="capture(role)"
            >
              {{ loading.capture[role] ? '拍摄中…' : '拍摄' }}
            </button>
            <button class="btn ghost" :disabled="busy" @click="triggerUpload(role)">
              {{ loading.upload[role] ? '加载中…' : '加载图片' }}
            </button>
          </div>
        </div>
        <div class="image-box" :style="imgBoxStyle(role)">
          <button v-if="state[role].url" type="button" class="btn-bare" title="放大查看" @click="openLightbox">
            <img :src="imageUrl(state[role].url)" :alt="`拍摄原图 (${role})`" />
          </button>
          <span v-else>尚未拍摄或加载图片</span>
        </div>
        <div v-if="roleQualityUrl(role)" class="overlay-box">
          <div class="subhead">质量叠加</div>
          <button type="button" class="btn-bare" title="放大查看" @click="openLightbox">
            <img :src="roleQualityUrl(role)" :alt="`质量叠加图 (${role})`" />
          </button>
          <OverlayLegend type="quality" />
        </div>
        <dl class="metric-grid">
          <template v-for="[label, value] in qualityRows(state.capture_quality[role])" :key="label">
            <dt>{{ label }}</dt>
            <dd>{{ value }}</dd>
          </template>
        </dl>
      </article>
    </section>

    <section class="vd-run">
      <button class="btn run" :disabled="!canAnalyze" @click="analyze">
        {{ loading.analyze ? '分析中…' : '分析当前双图' }}
      </button>
      <button
        class="btn"
        :disabled="!state.analysis || applyA.busy"
        @click="applyToProduction"
      >
        {{ applyA.busy ? '应用中…' : '应用到生产' }}
      </button>
      <span v-if="!hasBefore || !hasAfter" class="muted">Before 和 After 都存在后才可分析</span>
      <span v-else-if="state.analysis?.ok === false" role="status" class="bad">分析未通过</span>
      <span v-else-if="state.analysis?.ok === true" role="status" class="ok">分析完成</span>
      <span v-if="dirty.recognition" class="muted">参数已改, 建议先重新分析再应用</span>
      <span v-if="applyMsg" role="status" class="ok">{{ applyMsg }}</span>
    </section>

    <section v-if="state.analysis" class="vd-results">
      <div class="result-head">
        <h4>识别结果</h4>
        <span>revision {{ state.revision }}</span>
      </div>
      <div class="front-line" :class="{ warn: solventFront.fallback }">
        溶剂前沿来源：{{ solventFront.source }}
        <span v-if="solventFront.position !== null">，位置 {{ fmt(solventFront.position, 1) }} px</span>
      </div>

      <div v-if="state.source_context" class="front-observation">
        <div class="front-observation-head">
          <strong>展开前沿观测</strong>
          <span>Rf 来源：图像识别（液位结果暂不参与计算）</span>
        </div>
        <template v-if="liquidObservation">
          <dl class="metric-grid front-observation-grid">
            <dt>样品 / run</dt><dd>{{ state.source_context.sample_id || '-' }} / {{ liquidObservation.run_id || '-' }}</dd>
            <dt>展缸 / 通道</dt><dd>{{ liquidObservation.tank_id ?? '-' }} / {{ liquidObservation.channel ?? '-' }}</dd>
            <dt>冻结时间</dt><dd>{{ liquidObservation.captured_at || '-' }}</dd>
            <dt>检测时间 / 年龄</dt><dd>{{ liquidMeasurement?.observed_at || '-' }} / {{ fmt(liquidMeasurement?.age_s, 2) }} s</dd>
            <dt>ROI 湿润面积</dt><dd>{{ fmt(liquidMeasurement?.percent, 2) }}%</dd>
            <dt>前沿位置</dt><dd>{{ fmt(liquidMeasurement?.front_percent, 2) }}%</dd>
            <dt>有效 / 可达 / 已标定</dt>
            <dd>{{ fmtBool(liquidMeasurement?.valid) }} / {{ fmtBool(liquidMeasurement?.reachable) }} / {{ fmtBool(liquidMeasurement?.calibrated) }}</dd>
            <dt>状态</dt><dd>{{ liquidMeasurement?.reason || 'ok' }}</dd>
          </dl>
          <p class="front-observation-note">front_percent 尚未标定到板面 cm，仅与图像前沿并列观察；不计算跨单位差值。</p>
        </template>
        <p v-else class="front-observation-note">该生产 case 没有同 run 的排液前液位观测旁挂。</p>
      </div>

      <div class="cnc-preview-controls">
        <label class="vd-field">
          <span>预览条带</span>
          <select v-model="selectedCncBand">
            <option v-for="band in (state.analysis.bands || []).filter((item) => !item.is_origin)" :key="band.band_id" :value="band.band_id">
              {{ band.band_id }} · Rf {{ fmt(bandRf(band), 3) }}
            </option>
          </select>
        </label>
        <button class="btn" :disabled="!selectedCncBand || loading.cncPreview" @click="generateCncPreview">
          {{ loading.cncPreview ? '生成中…' : '生成真实 CNC 预览' }}
        </button>
        <span v-if="state.analysis.cnc_preview" class="muted">
          {{ state.analysis.cnc_preview.strategy }} · {{ state.analysis.cnc_preview.point_count }} 点 · {{ state.analysis.cnc_preview.pass_count }} pass
        </span>
      </div>

      <div class="result-images">
        <div v-if="analysisUrls.annotated" class="result-image">
          <div class="subhead">annotated</div>
          <button type="button" class="btn-bare" title="放大查看" @click="openLightbox">
            <img :src="imageUrl(analysisUrls.annotated)" alt="识别标注图 (annotated)" loading="lazy" />
          </button>
          <OverlayLegend type="annotated" />
        </div>
        <div v-if="analysisUrls.score" class="result-image">
          <div class="subhead">score</div>
          <button type="button" class="btn-bare" title="放大查看" @click="openLightbox">
            <img :src="imageUrl(analysisUrls.score)" alt="行评分图 (score)" loading="lazy" />
          </button>
        </div>
        <div v-if="analysisUrls.cnc_preview" class="result-image">
          <div class="subhead">CNC execution preview</div>
          <button type="button" class="btn-bare" title="放大查看" @click="openLightbox">
            <img :src="imageUrl(analysisUrls.cnc_preview)" alt="CNC 执行预览图" loading="lazy" />
          </button>
          <OverlayLegend type="cnc" />
        </div>
      </div>

      <table class="vd-table">
        <thead>
          <tr>
            <th>Band</th>
            <th>类型</th>
            <th>Rf</th>
            <th>质心</th>
            <th>宽度</th>
            <th>跨度</th>
            <th>面积</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="band in state.analysis.bands || []" :key="band.band_id">
            <td>{{ band.band_id }}</td>
            <td>{{ band.is_origin ? 'origin' : 'band' }}</td>
            <td class="num">{{ fmt(bandRf(band), 3) }}</td>
            <td class="num">{{ bandCentroid(band) }}</td>
            <td class="num">{{ fmt(band.vertical_width_cm) }}</td>
            <td class="num">{{ fmt(band.horizontal_span_cm) }}</td>
            <td class="num">{{ fmt(band.area_cm2) }}</td>
          </tr>
          <tr v-if="!(state.analysis.bands || []).length">
            <td colspan="7" class="empty">未返回有效 band</td>
          </tr>
        </tbody>
      </table>

      <details v-if="reportRows(state.analysis.quality_report).length" class="report">
        <summary>质量对比报告</summary>
        <dl class="metric-grid">
          <template v-for="[label, value, isObj] in reportRows(state.analysis.quality_report)" :key="label">
            <dt>{{ label }}</dt>
            <dd>
              <details v-if="isObj" class="dd-json">
                <summary>展开</summary>
                <pre>{{ value }}</pre>
              </details>
              <template v-else>{{ value }}</template>
            </dd>
          </template>
        </dl>
      </details>
    </section>
    <ImageLightbox :items="lightbox" @close="lightbox = []" />
  </div>
</template>

<style scoped>
.vd { padding: 4px 2px 24px; color: var(--text); }
.vd-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
/* h3→h2 语义升级: 声明沿用, 视觉不变 */
.vd-head h2 { margin: 0; font-size: var(--fs-17); line-height: 1.3; color: var(--text-strong); }
.vd-head p { margin: 3px 0 0; color: var(--muted); font-size: var(--fs-12); }
.vd-head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
/* .mode-pill 基础样式走全局 (style.css), 此处只留状态修饰 */
.mode-pill.debug { background: var(--ok-soft); color: var(--ok-strong); }
.vd-err { color: var(--bad-strong); font-size: var(--fs-13); padding: 8px 10px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 12px; }

.vd-params { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; margin-bottom: 12px; }
.vd-param-group { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin: 0; min-width: 0; }
.vd-param-group legend { font-size: var(--fs-13); font-weight: 700; color: var(--subtle); padding: 0 6px; }
.vd-field { display: grid; grid-template-columns: 118px minmax(0, 1fr); align-items: center; gap: 8px; margin-bottom: 8px; font-size: var(--fs-12); color: var(--subtle); font-weight: 650; }
.vd-field input, .vd-field select { min-width: 0; min-height: 28px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--field-bg); color: var(--text); font-size: var(--fs-13); }
.vd-check { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: var(--fs-12); color: var(--subtle); font-weight: 650; }
.uv-note { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.uv-note span { font-size: var(--fs-12); padding: 2px 7px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border-soft); color: var(--subtle); }
.uv-note .danger { color: var(--bad-strong); background: var(--bad-soft); border-color: transparent; }

.vd-images { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; margin-bottom: 12px; }
.vd-pane { border: 1px solid var(--border); border-radius: 8px; padding: 10px; min-width: 0; }
.pane-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.pane-top h4 { margin: 0; font-size: var(--fs-14); color: var(--text-strong); }
.pane-top p { margin: 2px 0 0; font-size: var(--fs-12); color: var(--muted); word-break: break-all; }
.pane-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.image-box, .overlay-box { border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); display: flex; align-items: center; justify-content: center; overflow: hidden; min-height: 220px; color: var(--muted); font-size: var(--fs-13); }
.image-box img, .overlay-box img, .result-image img { max-width: 100%; max-height: 360px; object-fit: contain; display: block; cursor: zoom-in; }
.overlay-box { display: block; min-height: auto; padding: 8px; margin-top: 8px; }
.overlay-box img { margin: 0 auto; max-height: 260px; }
.subhead { font-size: var(--fs-12); color: var(--subtle); font-weight: 700; margin-bottom: 6px; }

.metric-grid { display: grid; grid-template-columns: minmax(90px, 0.7fr) minmax(0, 1fr); gap: 0; margin: 8px 0 0; border: 1px solid var(--border-soft); border-radius: 6px; overflow: hidden; }
.metric-grid dt, .metric-grid dd { margin: 0; padding: 5px 8px; border-bottom: 1px solid var(--border-soft); font-size: var(--fs-12); min-width: 0; }
.metric-grid dt { color: var(--subtle); background: var(--surface-2); font-weight: 650; }
.metric-grid dd { color: var(--text); word-break: break-word; }
.metric-grid dt:nth-last-child(2), .metric-grid dd:last-child { border-bottom: 0; }

.vd-run { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.vd-results { border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.result-head { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 8px; }
.result-head h4 { margin: 0; font-size: 15px; color: var(--text-strong); }
.result-head span { color: var(--muted); font-size: var(--fs-12); }
.front-line { font-size: var(--fs-13); padding: 7px 9px; border-radius: 6px; background: var(--surface-2); border: 1px solid var(--border-soft); margin-bottom: 10px; }
.front-line.warn { color: var(--bad-strong); background: var(--bad-soft); border-color: transparent; }
.result-images { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin-bottom: 12px; }
/* min-height 占位: 三张分析产出图 lazy 落位时不再顶开下方内容 (上轮 CLS 修复的漏网点) */
.result-image { border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: var(--surface-2); min-width: 0; min-height: 200px; }
.result-image img { margin: 0 auto; }
.front-observation { margin-bottom: 10px; padding: 9px; border: 1px solid var(--border-soft); border-radius: 6px; background: var(--surface-2); }
.front-observation-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.front-observation-head strong { font-size: var(--fs-13); color: var(--text-strong); }
.front-observation-head span { font-size: var(--fs-12); color: var(--subtle); }
.front-observation-grid { grid-template-columns: minmax(120px, .55fr) minmax(0, 1fr); }
.front-observation-note { margin: 7px 0 0; font-size: var(--fs-12); color: var(--muted); }
.cnc-preview-controls { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 0 0 10px; padding: 8px 9px; border: 1px solid var(--border-soft); border-radius: 6px; }
.cnc-preview-controls .vd-field { margin: 0; min-width: 270px; }
.vd-table { width: 100%; border-collapse: collapse; font-size: var(--fs-12); line-height: 1.45; }
.vd-table th, .vd-table td { border-bottom: 1px solid var(--border); padding: 6px 8px; text-align: left; vertical-align: top; }
.vd-table th { color: var(--subtle); font-weight: 700; background: var(--surface-2); }
.vd-table td { color: var(--text); }
.report { margin-top: 12px; }
.report summary { cursor: pointer; color: var(--subtle); font-size: var(--fs-13); font-weight: 700; }
/* 报告里对象值的折叠 JSON (缩进两格, 软换行避免撑破 dd) */
.dd-json summary { cursor: pointer; color: var(--subtle); }
.dd-json pre { margin: 4px 0 0; font-family: var(--font-mono); font-size: var(--fs-11); white-space: pre-wrap; word-break: break-word; }
/* 灯箱触发按钮 (键盘可开): 占满原图容器宽, 维持 img margin:auto 居中 */
.overlay-box .btn-bare, .result-image .btn-bare { display: block; width: 100%; }

/* .btn 全套样式走全局 (style.css) */
.muted { color: var(--muted); font-size: var(--fs-12); }
.ok { color: var(--ok-strong); font-size: var(--fs-12); font-weight: 650; }
.bad { color: var(--bad-strong); font-size: var(--fs-12); font-weight: 650; }
.empty { color: var(--muted); text-align: center; }

.vd-cases { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.vd-cases .case-field { margin-bottom: 0; flex: 1 1 320px; }

@media (max-width: 980px) {
  .vd-params, .vd-images, .result-images { grid-template-columns: 1fr; }
  .vd-head { flex-direction: column; align-items: stretch; }
  .vd-head-actions { justify-content: flex-start; }
}
</style>
