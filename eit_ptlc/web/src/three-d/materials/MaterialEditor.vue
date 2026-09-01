<script setup>
/**
 * 功能: 单个材质的观感编辑器 —— 颜色拾取 + 各项滑块, 改一下立刻生效.
 *
 * 每个字段旁边都显示"原值", 并可单独清除回到原值 —— 调色是试错过程,
 * 能随时看出"我把它从哪儿改到了哪儿"、能一键退回, 比只有一个总的重置按钮好用得多.
 */
import { computed } from 'vue'

import { FIELDS, normalizeHex } from './overrideModel.js'

const props = defineProps({
  /** 材质名(MAT_*, 与 YAML 对账用) */
  name: { type: String, required: true },
  /** 中文显示名; 传了就以它为主标题, MAT_* 缩成小字 */
  title: { type: String, default: '' },
  /** 当前生效值(初始值叠加覆盖后的结果) */
  current: { type: Object, default: () => ({}) },
  /** 未被覆盖前的初始值 */
  baseline: { type: Object, default: () => ({}) },
  /** 已有的人工覆盖 */
  patch: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['change', 'reset'])

/** 只显示该材质真实拥有的字段 —— 不透明材质没必要露出透射滑块 */
const visibleFields = computed(() =>
  FIELDS.filter((field) => field.key in props.baseline || field.key in props.patch),
)

/**
 * 功能: 取某字段当前该显示的值.
 * @param {object} field 字段定义
 * @returns {string|number} 值
 */
function valueOf(field) {
  const value = props.patch[field.key] ?? props.baseline[field.key]
  if (field.type === 'color') return normalizeHex(value) || '#808080'
  return Number(value ?? 0)
}

/**
 * 功能: 判断某字段是否被人工改过.
 * @param {object} field 字段定义
 * @returns {boolean} 是否已覆盖
 */
function isOverridden(field) {
  return field.key in props.patch
}

/**
 * 功能: 把原值格式化成可读文本.
 * @param {object} field 字段定义
 * @returns {string} 文本
 */
function baselineText(field) {
  const value = props.baseline[field.key]
  if (value === undefined) return '—'
  return field.type === 'color' ? String(value) : Number(value).toFixed(2)
}
</script>

<template>
  <div class="me">
    <div class="me__head">
      <span class="me__name">
        <template v-if="title && title !== name">{{ title }}
          <em class="me__code">{{ name }}</em>
        </template>
        <template v-else>{{ name }}</template>
      </span>
      <button
        class="me__reset"
        :disabled="!Object.keys(patch).length"
        title="清掉这个材质的全部人工调整"
        @click="emit('reset', name)"
      >
        全部还原
      </button>
    </div>

    <div v-for="field in visibleFields" :key="field.key" class="me__row">
      <div class="me__label">
        <span :class="{ 'me__label--on': isOverridden(field) }">{{ field.label }}</span>
        <button
          v-if="isOverridden(field)"
          class="me__clear"
          :title="`还原为 ${baselineText(field)}`"
          @click="emit('change', field.key, null)"
        >
          ↺
        </button>
      </div>

      <template v-if="field.type === 'color'">
        <input
          type="color"
          class="me__color"
          :value="valueOf(field)"
          @input="emit('change', field.key, $event.target.value)"
        />
        <input
          type="text"
          class="me__hex"
          :value="valueOf(field)"
          spellcheck="false"
          @change="emit('change', field.key, $event.target.value)"
        />
      </template>

      <template v-else>
        <input
          type="range"
          class="me__range"
          :min="field.min"
          :max="field.max"
          :step="field.step"
          :value="valueOf(field)"
          @input="emit('change', field.key, $event.target.value)"
        />
        <span class="me__num">{{ Number(valueOf(field)).toFixed(2) }}</span>
      </template>

      <span class="me__base" :title="`原值 ${baselineText(field)}`">{{ baselineText(field) }}</span>
    </div>
  </div>
</template>

<style scoped>
.me {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.me__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--hair);
}

.me__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  word-break: break-all;
}

.me__code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  font-style: normal;
  font-weight: 400;
  color: var(--text-dim);
}

.me__reset {
  flex: none;
  padding: 3px 8px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
  cursor: pointer;
}

.me__reset:disabled {
  opacity: 0.35;
  cursor: default;
}

.me__row {
  display: grid;
  grid-template-columns: 84px 1fr 46px 58px;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}

.me__label {
  display: flex;
  align-items: center;
  gap: 3px;
  color: var(--text-mid);
}

.me__label--on {
  color: var(--accent);
  font-weight: 600;
}

.me__clear {
  padding: 0 3px;
  font-size: 11px;
  line-height: 1;
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
}

.me__color {
  width: 100%;
  height: 22px;
  padding: 0;
  background: none;
  border: 1px solid var(--hair);
  border-radius: 4px;
  cursor: pointer;
}

.me__hex,
.me__num {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text);
  text-align: right;
}

.me__hex {
  width: 100%;
  padding: 2px 4px;
  background: var(--well);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.me__range {
  width: 100%;
  accent-color: var(--accent);
}

.me__base {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  color: var(--text-dim);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
