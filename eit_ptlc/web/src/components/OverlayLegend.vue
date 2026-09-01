<script setup>
// 叠加图图例: 色块 + 标签 (title 提示详情), 非 compact 时附一行关键说明。
import { computed } from 'vue'
import {
  ANNOTATED_LEGEND, ANNOTATED_NOTE, CNC_LEGEND, CNC_NOTE,
  QUALITY_LEGEND, QUALITY_NOTE, SKETCH_AXES_LEGEND, SKETCH_AXES_NOTE,
} from '../overlayLegends'

const props = defineProps({
  type: { type: String, required: true },       // 'quality' | 'annotated' | 'cnc'
  compact: { type: Boolean, default: false },
})
const items = computed(() => {
  if (props.type === 'quality') return QUALITY_LEGEND
  if (props.type === 'cnc') return CNC_LEGEND
  if (props.type === 'sketch_axes') return SKETCH_AXES_LEGEND
  return ANNOTATED_LEGEND
})
const note = computed(() => {
  if (props.type === 'quality') return QUALITY_NOTE
  if (props.type === 'cnc') return CNC_NOTE
  if (props.type === 'sketch_axes') return SKETCH_AXES_NOTE
  return ANNOTATED_NOTE
})
</script>

<template>
  <div class="legend" :class="{ compact }">
    <span
      v-for="it in items" :key="it.label" class="legend-item" :title="it.note || ''"
      :aria-label="it.note ? `${it.label}: ${it.note}` : undefined"
    >
      <i class="swatch" :class="it.shape" :style="{ '--c': it.color }" aria-hidden="true"></i>{{ it.label }}
    </span>
    <p v-if="!compact" class="legend-note">{{ note }}</p>
  </div>
</template>

<style scoped>
.legend { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin-top: 6px;
  font-size: var(--fs-12); color: var(--subtle); }
.legend.compact { gap: 4px 10px; font-size: var(--fs-11); margin-top: 2px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; cursor: default; }
.swatch { display: inline-block; width: 12px; height: 12px; flex: none; }
.swatch.box { border: 2px solid var(--c); border-radius: 2px; }
.swatch.line { height: 3px; background: var(--c); }
.swatch.cross { position: relative; }
.swatch.cross::before, .swatch.cross::after { content: ''; position: absolute; background: var(--c); }
.swatch.cross::before { left: 5px; top: 0; width: 2px; height: 12px; }
.swatch.cross::after { left: 0; top: 5px; width: 12px; height: 2px; }
.legend-note { flex-basis: 100%; margin: 2px 0 0; color: var(--muted); }
</style>
