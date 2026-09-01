<script setup>
// 类型化取值输入: 字面量 / 变量 双模; 复杂表达式只读显示并可改写为字面量
import { computed, ref, watch } from 'vue'
import { confirmAction } from '../../composables/confirmService.js'

const props = defineProps({
  modelValue: { default: null },
  type: { default: 'any' },     // int|float|bool|string|enum|point_ref|any
  // 有限取值域 [{value, label}] (后端 dto._options 下发)。非空即渲染下拉, 与 type 正交。
  // value 保留原生类型, 故 int 参数选中后拿回的仍是 int。
  options: { default: () => [] },
  vars: { default: () => [] },
  minimum: { default: null },   // int/float 下限 (来自动作参数声明)
  maximum: { default: null },   // int/float 上限
  placeholder: { default: '' }, // 空值占位 (如泵档默认数字); 仅显示, 不写入
  unsettable: { default: false }, // true=可选无默认参数: 空输入保留为空 (上报取消覆写), 不兜底 0
  label: { type: String, default: '' }, // 可见参数名 (调用方传入), 作各控件的可访问名
})
const emit = defineEmits(['update:modelValue'])

const mode = computed(() => {
  const v = props.modelValue
  if (v && typeof v === 'object' && 'var' in v) return 'var'
  if (v && typeof v === 'object' && 'lit' in v) return 'lit'
  return 'expr'
})

// 数值非法态: 非法输入不上抛 (model 保留上次合法值), 只做本地红框; 合法/外部改值即清除。
// 取代原 `parseInt(v)||0` 兜底 —— 那会把无效输入静默写成 0 下发到机器。
const err = ref(false)
watch(() => props.modelValue, () => { err.value = false })

const litValue = computed({
  get: () => (props.modelValue && 'lit' in props.modelValue ? props.modelValue.lit : ''),
  set: (val) => {
    if (props.type === 'int' || props.type === 'float') {
      // unsettable 参数 (可选无默认): 空输入保留为 '' 上报 -> 父级据此取消覆写 (回退默认), 不落 0
      if (props.unsettable && (val === '' || val === null || val === undefined)) {
        err.value = false
        emit('update:modelValue', { lit: '' })
        return
      }
      const n = props.type === 'int' ? parseInt(val, 10) : parseFloat(val)
      if (!Number.isFinite(n)) { err.value = true; return }
      err.value = false
      emit('update:modelValue', { lit: n })
      return
    }
    emit('update:modelValue', { lit: val })
  },
})
const boolValue = computed({
  get: () => !!(props.modelValue && props.modelValue.lit),
  set: (val) => emit('update:modelValue', { lit: !!val }),
})
const varName = computed({
  get: () => (props.modelValue && 'var' in props.modelValue ? props.modelValue.var : ''),
  set: (val) => emit('update:modelValue', { var: val }),
})

function setMode(m) {
  if (m === 'lit') {
    const numeric = props.type === 'int' || props.type === 'float'
    // unsettable 数值切到字面量时种子留空 (显示占位符, 不写 0); 其余维持原默认
    const def = numeric ? (props.unsettable ? '' : 0) : props.type === 'bool' ? false : ''
    emit('update:modelValue', { lit: def })
  } else if (m === 'var') {
    emit('update:modelValue', { var: (props.vars[0] && props.vars[0].name) || '' })
  }
}

// 离开 expr 态会不可逆丢弃表达式, 先确认 (lit/var 互切无此风险, 直通)
async function requestMode(m) {
  if (mode.value === 'expr') {
    const v = props.modelValue
    const expr = typeof v === 'string' ? v : JSON.stringify(v)
    const text = m === 'lit' ? '改为字面量' : '改为变量'
    if (!(await confirmAction({ title: text, message: '将丢弃表达式 ' + expr, confirmText: text }))) return
  }
  setMode(m)
}
</script>

<template>
  <div class="vinput">
    <div class="vmode">
      <button type="button" :class="{ on: mode === 'lit' }" :aria-pressed="mode === 'lit'" @click="requestMode('lit')">字面量</button>
      <button type="button" :class="{ on: mode === 'var' }" :aria-pressed="mode === 'var'" @click="requestMode('var')">变量</button>
    </div>
    <template v-if="mode === 'lit'">
      <!-- 判据只看有没有取值域, 不看 type —— 与后端 executor 的成员校验同一条规则,
           这样 type: int 的参数 (如地轨目标位) 也能是下拉而不必假装成 enum 类型 -->
      <select v-if="options.length" v-model="litValue" :aria-label="label || undefined">
        <option v-if="type === 'point_ref'" :value="''">— 选择点位 —</option>
        <option v-for="o in options" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <input v-else-if="type === 'int' || type === 'float'" type="number" :min="minimum" :max="maximum" :placeholder="placeholder"
             :class="{ err }" :aria-invalid="err" :aria-label="label || undefined" v-model="litValue" />
      <label v-else-if="type === 'bool'" class="chk-wrap"><input type="checkbox" v-model="boolValue" :aria-label="label || undefined" /></label>
      <input v-else type="text" :placeholder="placeholder" :aria-label="label || undefined" v-model="litValue" />
    </template>
    <select v-else-if="mode === 'var'" v-model="varName" :aria-label="label || undefined">
      <option v-if="!vars.length" :value="''">— 无变量 —</option>
      <option v-for="v in vars" :key="v.name" :value="v.name">${{ v.name }} ({{ v.type }})</option>
    </select>
    <span v-else class="expr-ro">复杂表达式 <button type="button" @click="requestMode('lit')">改为字面量</button></span>
  </div>
</template>

<style scoped>
/* 非法数值本地红框 (与 .in-tab input.err 同款视觉) */
.vinput input.err { border-color: var(--bad); outline: 1px solid var(--bad); }
</style>
