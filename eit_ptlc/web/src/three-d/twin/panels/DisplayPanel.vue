<script setup>
/**
 * 功能: 显示设置面板 —— 分光源强度/主光角度/阴影/效果/场景 的实时调节,
 *       画质档位切换, 以及 GPU 负载条与"开某项加多少"的实测增量.
 *
 * 数据流约定:
 *   - 一切读写都走 manager.display 操作面(SceneManager 提供), 面板不直接摸
 *     environment/effects; manager 经 shallowRef 传入, 面板内部用本地 ref 镜像
 *     数值, 绝不 reactive(manager)(深响应会把整个 three 场景图拖进代理).
 *   - 字段清单/范围/分组来自 displaySettings.DISPLAY_FIELDS 元数据, 面板零硬编码;
 *   - 主题热切时订阅 onThemeChange 刷新镜像 —— 滑块自动跳到新主题槽的有效值;
 *   - 负载数据从 stats prop 进(SceneManager.onStats 每秒一发), 含 frameMs/gpuMs/
 *     measuring/loadDeltas.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { getTheme, onThemeChange } from '../../theme.js'
import { QUALITY_TIERS } from '../scene/SceneManager.js'

const props = defineProps({
  /** SceneManager 实例(父级 shallowRef 持有) */
  manager: { type: Object, required: true },
  /** onStats 载荷(fps/quality/frameMs/gpuMs/loadDeltas/...) */
  stats: { type: Object, default: () => ({}) },
  /** 面板右缘距容器右缘(避开各视图右侧常驻栏) */
  anchorRight: { type: Number, default: 12 },
  /** 面板上缘距容器上缘 */
  anchorTop: { type: Number, default: 52 },
  /**
   * 可设视角的模块 [{id, label, manual}] —— 只有实时页传, 别的台不传即整段不渲染.
   * manual 表示该工位的机位是人工设过的(而不是三维管线自动烘的)。
   */
  viewStations: { type: Array, default: () => [] },
  /** 当前选中的工位 id(左栏正看着谁, 下拉就预选谁; 不在列表里则选第一个) */
  viewSelected: { type: String, default: '' },
  /** 能不能存(写盘接口只在 DEBUG 下开放) */
  viewSavable: { type: Boolean, default: false },
  /** 存盘进行中(防连点) */
  viewBusy: { type: Boolean, default: false },
  /** 上一次保存/清除的结果提示 */
  viewMessage: { type: String, default: '' },
})

const emit = defineEmits(['close', 'save-view', 'clear-view'])

/** 分区定义(字段按 group 归入) */
const GROUPS = [
  { id: 'light', title: '光源' },
  { id: 'shadow', title: '阴影' },
  { id: 'fx', title: '效果' },
  { id: 'scene', title: '场景' },
  // 薄层板不是观感参数(它是工件规格与物理表现), 但操作面同一个, 所以同一个面板呈现;
  // 存储另走单槽的 plateSettings —— 换个深浅主题板不该变厚, 碰撞也不该被关掉
  { id: 'plate', title: '薄层板' },
]

const panelEl = ref(null)
// setup 期同步取初值(面板挂载时 manager 必已就绪), 首帧不闪 undefined
const values = ref(props.manager.display.effective())
const overrides = ref(props.manager.display.overrides())
const theme = ref(getTheme())
const copied = ref(false)

const groups = computed(() =>
  GROUPS.map((group) => ({
    ...group,
    fields: props.manager.display.fields.filter((field) => field.group === group.id),
  })),
)

const themeLabel = computed(() => (theme.value === 'light' ? '白天' : '夜晚'))
const currentQuality = computed(() => props.stats.quality || props.manager.quality)

/**
 * 模块视角设定的当前选择.
 * 预选规则: 左栏正选着的工位在列表里就选它(用户多半就是来调它的), 否则第一个;
 * 用户改过之后跟随左栏选择(面板重开时再按左栏预选一次 —— 组件是 v-if 挂卸的)。
 */
const viewPick = ref('')
watch(
  () => [props.viewSelected, props.viewStations],
  () => {
    const ids = props.viewStations.map((row) => row.id)
    if (viewPick.value && ids.includes(viewPick.value)) return
    viewPick.value = ids.includes(props.viewSelected) ? props.viewSelected : (ids[0] || '')
  },
  { immediate: true },
)
const pickedView = computed(() =>
  props.viewStations.find((row) => row.id === viewPick.value) || null)

/** 已测得的逐项开销: key -> {deltaMs, pct, note} */
const deltas = computed(() => new Map((props.stats.loadDeltas || []).map((d) => [d.key, d])))

/** 负载条: 有真 GPU 耗时用它, 否则用 CPU 提交耗时 */
const loadMs = computed(() => props.stats.gpuMs ?? props.stats.frameMs ?? null)
const loadRatio = computed(() => (loadMs.value === null ? 0 : Math.min(loadMs.value / 16.7, 1)))
const loadTone = computed(() => {
  if (loadRatio.value >= 1) return 'bad'
  if (loadRatio.value >= 0.6) return 'warn'
  return 'ok'
})
const loadLabel = computed(() => {
  if (loadMs.value === null) return '采样中…'
  const kind = props.stats.gpuAvailable ? 'GPU' : '提交'
  return `${kind} ${loadMs.value.toFixed(1)} ms / 16.7 ms`
})

const shadowDelta = computed(() => deltas.value.get('shadowsEnabled'))
const canMeasureShadows = computed(
  () => Boolean(props.manager.display.tier().shadows) && !props.stats.measuring,
)

/**
 * 功能: 从 manager 重新镜像有效值/覆盖/主题(每次写入与主题热切后调用).
 * @returns {void}
 */
function refresh() {
  theme.value = getTheme()
  values.value = props.manager.display.effective()
  overrides.value = props.manager.display.overrides()
}

/**
 * 功能: 字段当前是否置灰 —— 画质档位不允许, 或它依赖的开关是关的.
 * @param {object} field 字段元数据
 * @returns {boolean} 是否禁用
 */
function isDisabled(field) {
  const tier = props.manager.display.tier()
  if (field.tierKey && !tier[field.tierKey]) return true
  if (field.dependsOn && !values.value[field.dependsOn]) return true
  if (field.backgrounds && !field.backgrounds.includes(values.value.backgroundScene)) return true
  return false
}

/**
 * 功能: 置灰原因提示.
 * @param {object} field 字段元数据
 * @returns {string} title 文案
 */
function disabledTitle(field) {
  const tier = props.manager.display.tier()
  if (field.tierKey && !tier[field.tierKey]) return '当前画质档已停用'
  if (field.dependsOn && !values.value[field.dependsOn]) return '先打开它依赖的开关'
  if (field.backgrounds && !field.backgrounds.includes(values.value.backgroundScene)) {
    return '当前背景使用洁净地坪'
  }
  return ''
}

/**
 * 功能: 数值显示(步长 ≥1 的取整显示, 其余两位小数; 带单位).
 * @param {object} field 字段元数据
 * @param {*} value 当前值
 * @returns {string} 文案
 */
function formatValue(field, value) {
  if (value === undefined || value === null) return '—'
  const decimals = field.step >= 1 ? 0 : 2
  return `${Number(value).toFixed(decimals)}${field.unit || ''}`
}

/**
 * 功能: 开关行右侧的增量文案(测量中/已测得).
 * @param {object} field 字段元数据
 * @returns {string} 文案
 */
function deltaText(field) {
  if (props.stats.measuring === field.key) return '测量中…'
  const item = deltas.value.get(field.key)
  if (!item || !Number.isFinite(item.deltaMs)) return ''
  return `+${item.deltaMs.toFixed(1)}ms`
}

/**
 * 功能: 写入一个字段.
 * @param {object} field 字段元数据
 * @param {*} raw 控件原始值
 * @returns {void}
 */
function onSet(field, raw) {
  const value = field.type === 'toggle'
    ? Boolean(raw)
    : field.type === 'range'
      ? Number(raw)
      : raw
  props.manager.display.set(field.key, value)
  refresh()
}

/**
 * 功能: 单项还原(清除覆盖回到基准).
 * @param {object} field 字段元数据
 * @returns {void}
 */
function onClear(field) {
  props.manager.display.clear(field.key)
  refresh()
}

/**
 * 功能: 恢复当前主题的全部默认.
 * @returns {void}
 */
function onReset() {
  props.manager.display.resetTheme()
  refresh()
}

/**
 * 功能: 导出当前参数 JSON 到剪贴板(调满意后交回固化成新默认).
 * @returns {Promise<void>} 完成
 */
async function onExport() {
  const text = props.manager.display.exportJson()
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // 剪贴板权限被拒时退化为选中复制
    const area = document.createElement('textarea')
    area.value = text
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 1600)
}

/**
 * 功能: 点面板外关闭(入口按钮标了 data-display-toggle, 点它交给按钮自己切换).
 * @param {PointerEvent} event 事件
 * @returns {void}
 */
function onPointerDown(event) {
  const el = panelEl.value
  if (!el) return
  const target = event.target
  if (el.contains(target)) return
  if (target?.closest?.('[data-display-toggle]')) return
  emit('close')
}

let offTheme = null

onMounted(() => {
  refresh()
  offTheme = onThemeChange(refresh)
  document.addEventListener('pointerdown', onPointerDown, true)
  if (import.meta.env.DEV) {
    // Playwright 验证钩子: 免 UI 直设参数/读增量
    window.__ptlcDisplay = {
      set: (key, value) => {
        const result = props.manager.display.set(key, value)
        refresh()
        return result
      },
      get: () => props.manager.display.effective(),
      overrides: () => props.manager.display.overrides(),
      measureShadows: () => props.manager.display.measureShadows(),
      deltas: () => props.stats.loadDeltas || [],
      export: () => props.manager.display.exportJson(),
    }
  }
})

onBeforeUnmount(() => {
  offTheme?.()
  document.removeEventListener('pointerdown', onPointerDown, true)
  if (import.meta.env.DEV && window.__ptlcDisplay) delete window.__ptlcDisplay
})
</script>

<template>
  <aside
    ref="panelEl"
    class="dp"
    :style="{ right: `${anchorRight}px`, top: `${anchorTop}px` }"
  >
    <header class="dp__head">
      <span class="dp__title">显示设置</span>
      <span class="dp__badge">{{ themeLabel }}</span>
      <button class="dp__close" title="关闭" @click="emit('close')">✕</button>
    </header>

    <div class="dp__body">
      <section v-for="group in groups" :key="group.id" class="dp__group">
        <h3 class="dp__group-title">{{ group.title }}</h3>
        <p v-if="group.id === 'light'" class="dp__hint dp__hint--lead">
          昼夜共用同一套观感参数, 仅环境不同
        </p>

        <div
          v-for="field in group.fields"
          :key="field.key"
          class="dp__row"
          :class="{ 'dp__row--off': isDisabled(field) }"
          :title="disabledTitle(field)"
        >
          <span class="dp__label" :class="{ 'dp__label--set': field.key in overrides }">
            {{ field.label }}
          </span>

          <template v-if="field.type === 'range'">
            <input
              type="range"
              class="dp__range"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              :value="values[field.key]"
              :disabled="isDisabled(field)"
              @input="onSet(field, $event.target.value)"
            />
            <span class="dp__num">{{ formatValue(field, values[field.key]) }}</span>
          </template>

          <template v-else-if="field.type === 'select'">
            <select
              class="dp__select"
              :value="values[field.key]"
              :disabled="isDisabled(field)"
              @change="onSet(field, $event.target.value)"
            >
              <option v-for="option in field.options" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
          </template>

          <template v-else>
            <button
              class="dp__toggle"
              :class="{ 'dp__toggle--on': values[field.key] }"
              :disabled="isDisabled(field)"
              @click="onSet(field, !values[field.key])"
            >
              {{ values[field.key] ? '开' : '关' }}
            </button>
            <span class="dp__num dp__num--delta">{{ deltaText(field) }}</span>
          </template>

          <button
            class="dp__revert"
            :disabled="!(field.key in overrides)"
            title="还原此项到默认"
            @click="onClear(field)"
          >
            ↺
          </button>
        </div>
      </section>

      <section class="dp__group">
        <h3 class="dp__group-title">画质档位</h3>
        <div class="dp__seg">
          <button
            v-for="(tier, key) in QUALITY_TIERS"
            :key="key"
            class="dp__seg-btn"
            :class="{ 'dp__seg-btn--on': currentQuality === key }"
            @click="manager.display.setQuality(key)"
          >
            {{ tier.label }}
          </button>
        </div>
        <p class="dp__hint">帧率持续不足时会自动降档; 低档停用阴影与效果区各项</p>
      </section>

      <!-- 模块视角设定: 只在实时页出现(别的台没有工位跳转这回事)。
           形制是"选工位 → 对它操作"的紧凑子卡片, 不是逐工位一行 ——
           10 个工位 × 每行一个保存钮会把面板无限抻长 -->
      <section v-if="viewStations.length" class="dp__group">
        <h3 class="dp__group-title">模块视角设定</h3>
        <div class="dp__view-card">
          <select v-model="viewPick" class="dp__select dp__view-select">
            <option v-for="row in viewStations" :key="row.id" :value="row.id">
              {{ row.label }}{{ row.manual ? ' · 已设定' : '' }}
            </option>
          </select>
          <div v-if="pickedView" class="dp__view">
            <span class="dp__view-tag" :class="{ 'is-manual': pickedView.manual }">
              {{ pickedView.manual ? '已设定人工视角' : '自动取景' }}
            </span>
            <button type="button" class="dp__view-btn" :disabled="!viewSavable || viewBusy"
                    title="把当前镜头存成该模块的跳转视角"
                    @click="emit('save-view', pickedView.id)">保存当前视角</button>
            <button v-if="pickedView.manual" type="button" class="dp__view-btn"
                    :disabled="!viewSavable || viewBusy"
                    title="还原成管线自动取景"
                    @click="emit('clear-view', pickedView.id)">清除</button>
          </div>
          <p class="dp__hint">
            调好镜头后保存。存的是 manifest 的 stations[].camera ——
            <b>演示页飞向该工位的镜头也会跟着变</b>。
          </p>
          <p v-if="!viewSavable" class="dp__hint dp__hint--warn">
            保存视角需要调试模式(写盘接口只在 DEBUG 下开放), 现在只能查看。
          </p>
          <p v-if="viewMessage" class="dp__hint dp__hint--warn">{{ viewMessage }}</p>
        </div>
      </section>

      <section class="dp__group">
        <h3 class="dp__group-title">GPU 负载</h3>
        <div class="dp__load">
          <div class="dp__bar">
            <div
              class="dp__bar-fill"
              :class="`dp__bar-fill--${loadTone}`"
              :style="{ width: `${Math.round(loadRatio * 100)}%` }"
            />
          </div>
          <span class="dp__num dp__load-num">{{ loadLabel }}</span>
        </div>
        <p v-if="!stats.gpuAvailable" class="dp__hint">
          本机浏览器不支持 GPU 计时扩展, 显示的是渲染的 CPU 提交耗时
        </p>

        <div v-for="item in stats.loadDeltas || []" :key="item.key" class="dp__delta">
          <span class="dp__delta-label">{{ item.label }}</span>
          <span class="dp__num">+{{ item.deltaMs.toFixed(1) }} ms · {{ Math.round(item.pct * 100) }}%</span>
          <span v-if="item.note" class="dp__delta-note">{{ item.note }}</span>
        </div>

        <div class="dp__delta">
          <span class="dp__delta-label">实时阴影开销</span>
          <button
            v-if="stats.measuring !== 'shadowsEnabled'"
            class="dp__toggle"
            :disabled="!canMeasureShadows"
            :title="canMeasureShadows ? '约 2 秒, 期间画面会短暂翻转阴影' : '当前画质档无阴影或正在测量'"
            @click="manager.display.measureShadows()"
          >
            测量
          </button>
          <span v-else class="dp__num dp__num--delta">测量中…</span>
          <span class="dp__delta-note">仅动画/交互帧产生开销</span>
        </div>
      </section>
    </div>

    <footer class="dp__foot">
      <!-- 覆盖已收成单槽(昼夜共用), 所以不再带主题名 -->
      <button class="dp__btn" @click="onReset">恢复默认</button>
      <button class="dp__btn dp__btn--primary" @click="onExport">
        {{ copied ? '已复制 ✓' : '导出参数' }}
      </button>
    </footer>
  </aside>
</template>

<style scoped>
.dp {
  position: absolute;
  z-index: 12; /* 压过 wb__meter(11)/右侧栏(10), 仍在加载 overlay 之下 */
  display: flex;
  flex-direction: column;
  width: 300px;
  max-height: min(70vh, calc(100% - 70px));
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 8px;
  backdrop-filter: blur(6px);
  box-shadow: 0 8px 28px rgb(0 0 0 / 0.25);
}

.dp__head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--hair);
}

.dp__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
}

.dp__badge {
  padding: 1px 6px;
  font-size: 10px;
  color: var(--text-dim);
  border: 1px solid var(--hair);
  border-radius: 999px;
}

.dp__close {
  margin-left: auto;
  padding: 2px 6px;
  font-size: 11px;
  color: var(--text-dim);
  background: none;
  border: none;
  cursor: pointer;
}

.dp__close:hover {
  color: var(--text-bright);
}

.dp__body {
  flex: 1;
  padding: 8px 12px;
  overflow: hidden auto;
}

.dp__group + .dp__group {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--hair);
}

.dp__group-title {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-mid);
  letter-spacing: 0.06em;
}

/* 四列: 标签 | 控件 | 当前值 | 单项还原 (照 MaterialEditor 的行范式收窄) */
.dp__row {
  display: grid;
  grid-template-columns: 64px 1fr 56px 20px;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  font-size: 11px;
}

.dp__row--off {
  opacity: 0.4;
}

.dp__label {
  color: var(--text-mid);
}

.dp__label--set {
  color: var(--accent);
  font-weight: 600;
}

.dp__range {
  flex: 1;
  width: 100%;
  accent-color: var(--accent);
}

.dp__select {
  grid-column: 2 / 4;
  width: 100%;
  min-width: 0;
  height: 23px;
  padding: 1px 24px 1px 7px;
  font: inherit;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
  outline: none;
  cursor: pointer;
}

.dp__select:hover,
.dp__select:focus-visible {
  border-color: var(--accent);
}

.dp__select:disabled {
  cursor: default;
}

.dp__num {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  color: var(--text-mid);
  text-align: right;
  white-space: nowrap;
}

.dp__num--delta {
  color: var(--text-dim);
}

.dp__toggle {
  justify-self: start;
  min-width: 40px;
  padding: 2px 10px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
  cursor: pointer;
}

.dp__toggle--on {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

.dp__toggle:disabled {
  cursor: default;
}

.dp__revert {
  padding: 0 2px;
  font-size: 12px;
  color: var(--text-dim);
  background: none;
  border: none;
  cursor: pointer;
}

.dp__revert:disabled {
  opacity: 0.25;
  cursor: default;
}

.dp__seg {
  display: flex;
  gap: 4px;
}

.dp__seg-btn {
  flex: 1;
  padding: 3px 0;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
  cursor: pointer;
}

.dp__seg-btn--on {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

.dp__hint {
  margin: 6px 0 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}

/* 组标题下方的说明: 贴着标题走, 与下方第一行控件留出间距 */
.dp__hint--lead {
  margin: -2px 0 6px;
}

.dp__hint--warn {
  color: var(--warn);
}

/* ── 模块视角设定 ────────────────────────────────────────────────── */
.dp__view-card {
  display: grid;
  gap: 5px;
  padding: 7px 8px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 6px;
}

/* .dp__select 原生绑着 .dp__row 的四列网格(grid-column:2/4), 子卡片里要铺满整行 */
.dp__view-select {
  grid-column: auto;
  width: 100%;
}

.dp__view {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 3px 0;
}

.dp__view-tag {
  /* 状态标占满剩余宽, 把操作按钮推到右侧 */
  flex: 1;
  min-width: 0;
  font-size: 10px;
  color: var(--text-dim);
}

.dp__view-tag.is-manual {
  color: var(--accent-bright);
}

.dp__view-btn {
  flex: none;
  padding: 2px 7px;
  font-size: 10px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.dp__view-btn:hover:not(:disabled) {
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.dp__view-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.dp__load {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 负载条: 抄 TwinView 的加载条形制, 按档位变色 */
.dp__bar {
  flex: 1;
  height: 4px;
  overflow: hidden;
  background: var(--border);
  border-radius: 2px;
}

.dp__bar-fill {
  height: 100%;
  transition: width 0.3s ease;
}

.dp__bar-fill--ok {
  background: var(--accent-gradient);
}

.dp__bar-fill--warn {
  background: #d9a441;
}

.dp__bar-fill--bad {
  background: #d95757;
}

.dp__load-num {
  min-width: 96px;
}

.dp__delta {
  display: grid;
  grid-template-columns: 84px 1fr;
  align-items: center;
  gap: 4px 6px;
  margin-top: 4px;
  font-size: 11px;
}

.dp__delta-label {
  color: var(--text-mid);
}

.dp__delta-note {
  grid-column: 2;
  font-size: 10px;
  color: var(--text-dim);
}

.dp__foot {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 8px 12px 10px;
  border-top: 1px solid var(--hair);
}

.dp__btn {
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 5px;
  cursor: pointer;
}

.dp__btn--primary {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}
</style>
