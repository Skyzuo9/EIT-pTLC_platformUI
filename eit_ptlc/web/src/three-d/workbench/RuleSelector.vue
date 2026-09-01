<script setup>
/**
 * 功能: 规则批选 —— 一次性选中一大批同类零件.
 *
 * 精简模型的绝大部分工作量在这里完成: 螺栓垫圈、拖链节、供应商自动命名件都是成百上千个,
 * 一个个点要点到天亮; 用一条规则圈住它们才是正确的做法.
 * 逐个点选留给"这个零件我拿不准"的少数情况.
 */
import { ref } from 'vue'

const props = defineProps({
  /** 零件索引; 加载完成前为 null */
  index: { type: Object, default: null },
})

const emit = defineEmits(['apply'])

/** 常用预设 —— 覆盖了精简模型时 90% 的批选需求 */
const PRESETS = [
  { label: '供应商无名件', hint: 'OCCT 自动命名, 原图纸里就没名字', rule: { vendorAutoOnly: true } },
  { label: '紧固件', hint: '螺栓/螺钉/螺母/垫圈/销', rule: { pattern: 'luo_shuan|luo_ding|luo_mu|dian_quan|tan_dian|xiao_zi|screw|bolt|washer' } },
  { label: '拖链与线槽', hint: '数量极多, 视觉贡献低', rule: { pattern: 'tuo_lian|xian_cao|cable_chain' } },
  { label: '小于 6mm', hint: '整机视角下不足一像素', rule: { maxLongestMm: 6 } },
  { label: '小于 15mm', hint: '更激进的尺寸阈值', rule: { maxLongestMm: 15 } },
  { label: '重型零件', hint: '面数 > 2 万, 减面收益最高', rule: { minTriangles: 20000 } },
]

const pattern = ref('')
const maxSize = ref('')
const minTri = ref('')

/**
 * 功能: 应用一条预设规则.
 * @param {object} rule 规则
 * @returns {void}
 */
function applyPreset(rule) {
  emit('apply', rule)
}

/**
 * 功能: 应用自定义规则.
 * @returns {void}
 */
function applyCustom() {
  const rule = {}
  if (pattern.value.trim()) rule.pattern = pattern.value.trim()
  if (maxSize.value !== '') rule.maxLongestMm = Number(maxSize.value)
  if (minTri.value !== '') rule.minTriangles = Number(minTri.value)
  if (!Object.keys(rule).length) return
  emit('apply', rule)
}

/**
 * 功能: 预览某条规则会命中多少个, 用于下手前心里有数.
 * @param {object} rule 规则
 * @returns {number} 命中数
 */
function preview(rule) {
  return props.index ? props.index.query(rule).length : 0
}
</script>

<template>
  <section class="rules">
    <header class="rules__head">规则批选</header>

    <div class="rules__presets">
      <button
        v-for="preset in PRESETS"
        :key="preset.label"
        type="button"
        class="rules__preset"
        :title="preset.hint"
        :disabled="!index"
        @click="applyPreset(preset.rule)"
      >
        <span>{{ preset.label }}</span>
        <span class="rules__hits">{{ index ? preview(preset.rule) : '—' }}</span>
      </button>
    </div>

    <details class="rules__custom">
      <summary>自定义规则</summary>
      <label class="rules__field">
        <span>名称正则</span>
        <input v-model="pattern" type="text" placeholder="如 qi_gang|cylinder" />
      </label>
      <label class="rules__field">
        <span>最长边 &lt;</span>
        <input v-model="maxSize" type="number" placeholder="mm" />
      </label>
      <label class="rules__field">
        <span>面数 &gt;</span>
        <input v-model="minTri" type="number" placeholder="三角形" />
      </label>
      <button type="button" class="rules__go" :disabled="!index" @click="applyCustom">
        选中匹配项
      </button>
    </details>
  </section>
</template>

<style scoped>
.rules {
  flex: none;
  border-radius: 10px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  padding: 9px 10px 10px;
}

.rules__head {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-mid);
  margin-bottom: 7px;
}

.rules__presets {
  display: grid;
  gap: 3px;
}

.rules__preset {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: var(--control);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}

.rules__preset:hover:not(:disabled) {
  background: var(--control-hover);
}

.rules__preset:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rules__hits {
  flex: none;
  color: var(--warn);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

.rules__custom {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-mid);
}

.rules__custom summary {
  cursor: pointer;
  padding: 3px 0;
}

.rules__field {
  display: grid;
  grid-template-columns: 72px 1fr;
  align-items: center;
  gap: 6px;
  margin-top: 5px;
}

.rules__field input {
  padding: 3px 7px;
  border-radius: 5px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text-bright);
  font-size: 12px;
  width: 100%;
}

.rules__field input:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.rules__go {
  margin-top: 8px;
  width: 100%;
  padding: 4px;
  border-radius: 5px;
  border: 1px solid var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-bright);
  font-size: 12px;
  cursor: pointer;
}

.rules__go:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
