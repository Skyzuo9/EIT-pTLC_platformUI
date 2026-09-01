<script setup>
// 内联确认段 (CompilePanel 下载确认的声明式封装): 留在文档流里不遮内容,
// 适合"边看设备状态边决策"或多阶段武装流程; 一次性删除/覆盖用模态 confirmAction。
// 样式全部来自全局 .confirm-box/.warn-text/.ack/.confirm-actions (style.css)。
import { computed, ref, watch } from 'vue'

const props = defineProps({
  title: { type: String, default: '' },
  message: { type: [String, Array], default: () => [] },
  level: { type: String, default: 'danger' }, // 'warn' | 'danger'
  ackText: { type: String, default: '' },
  confirmText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  busy: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['confirm', 'cancel'])

const acked = ref(false)
watch(
  () => props.ackText,
  () => {
    acked.value = false
  },
)
const msgs = computed(() => (Array.isArray(props.message) ? props.message : props.message ? [props.message] : []))
// !! 强转: 无 ackText 时 ('' && ...) 让 || 链落到空串, 而 Vue 对布尔属性把 '' 当 true,
// :disabled="''" 会真禁用确认钮 —— 必须归一成布尔
const blocked = computed(() => !!(props.disabled || props.busy || (props.ackText && !acked.value)))
</script>

<template>
  <div class="confirm-box" :class="{ danger: level === 'danger' }">
    <p v-if="title" class="warn-text"><b>{{ title }}</b></p>
    <p v-for="(m, i) in msgs" :key="i" class="warn-text">{{ m }}</p>
    <slot />
    <label v-if="ackText" class="ack">
      <input v-model="acked" type="checkbox" :disabled="busy" />
      <span>{{ ackText }}</span>
    </label>
    <div class="confirm-actions">
      <button class="btn ghost" type="button" :disabled="busy" @click="emit('cancel')">{{ cancelText }}</button>
      <button
        class="btn"
        :class="{ danger: level === 'danger' }"
        type="button"
        :disabled="blocked"
        :aria-busy="busy || undefined"
        @click="emit('confirm')"
      >
        {{ busy ? `${confirmText}中…` : confirmText }}
      </button>
    </div>
  </div>
</template>
