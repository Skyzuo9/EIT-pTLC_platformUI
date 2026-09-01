<script setup>
/**
 * 功能: 按动作目录的参数 schema 自动生成控件的受控表单.
 *
 * 只管渲染与取值, 不下发、不确认、不判模式 —— 那些是调用方的事:
 *   ActionQuickForm  三道安全关卡(模式门禁/二次确认/结果回显)后真下发硬件;
 *   ActionDemoPane   只拿参数去算模拟播放, 一行都不发给设备.
 *
 * 数值"显示缩放"皮肤(scale/unit)与动作详情页共用 utils/runInputs 的 toDisplay/toRaw:
 * 显示值 = 原值 × scale, 回写时 round 到最近档并 clamp 到原值域. 存/发/校验的一律
 * 是原值(如泵速的整数 V), 界面上看到的才是物理单位(mL/min).
 */
import { toDisplay, toRaw } from '../../../utils/runInputs.js'
import { maxOf, minOf } from './actionParams.js'

const props = defineProps({
  /** 参数定义数组(ActionDefDTO.params) */
  params: { type: Array, default: () => [] },
  /** 当前取值 {参数名: 值}; 受控 */
  modelValue: { type: Object, default: () => ({}) },
  /** 是否只读 */
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

/**
 * 功能: 写一个参数值(不就地改 props, 整体替换).
 * @param {string} name 参数名
 * @param {*} value 值
 * @returns {void}
 */
function set(name, value) {
  emit('update:modelValue', { ...props.modelValue, [name]: value })
}

/**
 * 功能: 带 scale 皮肤的数值回写 —— 输入的是显示值, 存的是原值.
 * @param {object} param 参数定义
 * @param {Event} event 输入事件
 * @returns {void}
 */
function onScaled(param, event) {
  const raw = toRaw(event.target.value, param.scale, minOf(param), maxOf(param))
  set(param.name, raw)
  // 回显归一后的显示值, 让"输入 3.3 → 落到最近档 3.25"当场可见
  event.target.value = toDisplay(raw, param.scale)
}

/**
 * 功能: 范围提示文案(带 scale 时按显示单位标).
 * @param {object} param 参数定义
 * @returns {string} 提示; 无上下限返回空串
 */
function rangeHint(param) {
  const low = minOf(param)
  const high = maxOf(param)
  if (low === null && high === null) return ''
  const show = (value) => (value === null ? '—' : (param.scale ? toDisplay(value, param.scale) : value))
  return `范围 ${show(low)} ~ ${show(high)}${param.scale && param.unit ? ` ${param.unit}` : ''}`
}

/**
 * 功能: 占位文案 —— 无 YAML 默认值的泵参数显示它"未覆写时的实际执行值".
 * @param {object} param 参数定义
 * @returns {string} 占位串
 */
function placeholderOf(param) {
  if (param.default_hint === null || param.default_hint === undefined) return ''
  return `${param.scale ? toDisplay(param.default_hint, param.scale) : param.default_hint} · 泵档默认`
}
</script>

<template>
  <div v-if="params.length" class="apf">
    <label v-for="param in params" :key="param.name" class="apf__row">
      <span class="apf__name">
        {{ param.label || param.name }}
        <em v-if="param.required" class="apf__required">*</em>
        <em v-if="param.scale && param.unit" class="apf__unit">{{ param.unit }}</em>
      </span>

      <select
        v-if="param.options && param.options.length"
        class="apf__input"
        :disabled="disabled"
        :value="modelValue[param.name]"
        @change="set(param.name, $event.target.value)"
      >
        <option value="">（未选择）</option>
        <option v-for="option in param.options" :key="option.value" :value="option.value">{{ option.label }}</option>
      </select>

      <input
        v-else-if="param.type === 'bool'"
        type="checkbox"
        class="apf__checkbox"
        :disabled="disabled"
        :checked="Boolean(modelValue[param.name])"
        @change="set(param.name, $event.target.checked)"
      />

      <!-- 带 scale 的数值: 输入显示值, 存原值 -->
      <input
        v-else-if="param.scale && (param.type === 'int' || param.type === 'float')"
        type="number"
        class="apf__input"
        :disabled="disabled"
        :min="toDisplay(minOf(param), param.scale)"
        :max="toDisplay(maxOf(param), param.scale)"
        :step="param.scale"
        :placeholder="placeholderOf(param)"
        :value="toDisplay(modelValue[param.name], param.scale)"
        @change="onScaled(param, $event)"
      />

      <input
        v-else-if="param.type === 'int' || param.type === 'float'"
        type="number"
        class="apf__input"
        :disabled="disabled"
        :min="minOf(param)"
        :max="maxOf(param)"
        :step="param.type === 'int' ? 1 : 'any'"
        :placeholder="placeholderOf(param)"
        :value="modelValue[param.name]"
        @input="set(param.name, $event.target.value)"
      />

      <input
        v-else
        type="text"
        class="apf__input"
        :disabled="disabled"
        :value="modelValue[param.name]"
        @input="set(param.name, $event.target.value)"
      />

      <span v-if="rangeHint(param)" class="apf__range">{{ rangeHint(param) }}</span>
    </label>
  </div>
  <p v-else class="apf__empty">该动作无参数</p>
</template>

<style scoped>
.apf {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apf__row {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12px;
}

.apf__name {
  display: flex;
  gap: 5px;
  align-items: baseline;
  color: var(--text-mid);
}

.apf__required {
  font-style: normal;
  color: var(--err-bright);
}

.apf__unit {
  font-size: 10px;
  font-style: normal;
  color: var(--text-dim);
}

.apf__input {
  width: 100%;
  padding: 4px 7px;
  font: inherit;
  font-size: 12px;
  color: var(--text);
  background: var(--well);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.apf__input:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.apf__checkbox {
  align-self: flex-start;
  accent-color: var(--accent);
}

.apf__range {
  font-size: 10px;
  color: var(--text-dim);
}

.apf__empty {
  margin: 0;
  font-size: 11px;
  color: var(--text-dim);
}
</style>
