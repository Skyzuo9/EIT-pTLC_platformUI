<script setup>
// 通用弹窗壳: Teleport + 遮罩 + role="dialog"/aria-modal + 焦点圈禁/还焦 + Esc。
// 样式复用全局 .modal-backdrop/.modal/.modal-head (style.css)。
// closeOnBackdrop 默认 false: 工控确认场景误触背板不应关闭; 灯箱类查看器自行开启。
// estop 默认 true: backdrop 盖死态势条急停期间, 弹窗头部保持一个急停出口
// (机器运动与当前模态语义无关; 固定右上位建立肌肉记忆)。
import { computed, ref, useId } from 'vue'
import { useModalA11y } from '../../composables/useModalA11y.js'
import EstopButton from './EstopButton.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  wide: { type: Boolean, default: false },
  closeOnEsc: { type: Boolean, default: true },
  closeOnBackdrop: { type: Boolean, default: false },
  initialFocus: { type: [String, Function], default: null },
  estop: { type: Boolean, default: true },
})
const emit = defineEmits(['close'])

const card = ref(null)
const titleId = useId()

useModalA11y(card, {
  open: computed(() => props.open),
  onEsc: props.closeOnEsc ? () => emit('close') : undefined,
  // 常驻壳 (如 ConfirmHost) 的 initialFocus 随每次请求变化: 必须在"打开时"求值,
  // 不能在 setup 里一次性读 prop (否则被首帧值冻结)。
  // 缺省守卫: 未显式指定且头部有急停键时聚焦卡片本身 (tabindex=-1) ——
  // 否则"第一个可聚焦元素"就是急停, Enter 会误触发。
  initialFocus: () => {
    const v = props.initialFocus
    if (!v) return props.estop ? card.value : null
    if (typeof v === 'function') return v()
    return card.value ? card.value.querySelector(v) : null
  },
})

function onBackdrop() {
  if (props.closeOnBackdrop) emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="onBackdrop">
      <div
        ref="card"
        class="modal"
        :class="{ 'modal-wide': wide }"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="title ? titleId : undefined"
        tabindex="-1"
      >
        <div v-if="title || estop" class="modal-head">
          <h3 v-if="title" :id="titleId">{{ title }}</h3>
          <span v-else />
          <EstopButton v-if="estop" sm />
        </div>
        <slot />
        <div v-if="$slots.actions" class="modal-actions">
          <slot name="actions" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
