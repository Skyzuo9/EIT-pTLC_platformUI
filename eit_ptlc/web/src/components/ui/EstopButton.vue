<script setup>
// 急停按钮 (共享 useEstop 单例状态): 态势条与各弹窗头部渲染同一状态。
// .estop 是全局样式 (style.css), Teleport 到 body 的弹窗内也生效; sm 变体缩尺寸。
// 失败详情在 StatusBar 红字 + assertive 播报; 此处 title 兜底提示物理急停。
import { useEstop } from '../../composables/useEstop.js'

defineProps({
  sm: { type: Boolean, default: false },
})

const { busy, sent, emergencyStop } = useEstop()
</script>

<template>
  <button
    class="estop"
    :class="{ engaged: sent, sm }"
    type="button"
    title="急停 (下发失败时请使用物理急停)"
    @click="emergencyStop"
  >
    {{ busy ? '急停 · 下发中…' : sent ? '急停 ✓ 已下发' : '急停' }}
  </button>
</template>

<style scoped>
.estop.sm { padding: 4px 10px; font-size: var(--fs-12); }
</style>
