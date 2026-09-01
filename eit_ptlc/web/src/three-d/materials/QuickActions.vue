<script setup>
/**
 * 功能: 材质编辑器上方的快捷操作条 —— 预设 chips + 按住对比 + 恢复 CAD 原色.
 *
 * 纯展示组件: 预设应用/对比切换/CAD 色回填的实际数据流都在宿主(MaterialsView)里,
 * 材质类编辑与零件覆盖编辑可共用同一条快捷栏.
 */
import { computed } from 'vue'

import { cadColorOf, MATERIAL_PRESETS } from './materialPresets.js'

const props = defineProps({
  /** 材质名(MAT_*); 用于判断能否解码 CAD 原色 */
  name: { type: String, default: '' },
  /** 当前是否有人工覆盖(决定"对比"是否可用) */
  hasPatch: { type: Boolean, default: false },
})

const emit = defineEmits(['preset', 'compare', 'cad-color'])

const presets = MATERIAL_PRESETS
const cadHex = computed(() => cadColorOf(props.name))

/**
 * 功能: 按住对比 —— pointerdown 看原值, 抬起/移出恢复覆盖后的样子.
 * @param {boolean} active 是否按下
 * @returns {void}
 */
function compare(active) {
  if (props.hasPatch) emit('compare', active)
}
</script>

<template>
  <div class="qa">
    <div class="qa__presets">
      <button
        v-for="preset in presets"
        :key="preset.id"
        class="qa__chip"
        type="button"
        :title="`应用「${preset.label}」预设(可撤销)`"
        @click="emit('preset', preset)"
      >
        <span
          class="qa__chipDot"
          :style="{ background: preset.patch.base_color || '#808080' }"
        />{{ preset.label }}
      </button>
    </div>
    <div class="qa__ops">
      <button
        class="qa__btn"
        type="button"
        :disabled="!hasPatch"
        title="按住查看未调整前的原值, 松开恢复"
        @pointerdown="compare(true)"
        @pointerup="compare(false)"
        @pointerleave="compare(false)"
        @pointercancel="compare(false)"
      >
        按住对比
      </button>
      <button
        v-if="cadHex"
        class="qa__btn"
        type="button"
        :title="`把基色恢复成 CAD 量化色 ${cadHex}`"
        @click="emit('cad-color', cadHex)"
      >
        <span class="qa__chipDot" :style="{ background: cadHex }" />CAD 原色
      </button>
    </div>
  </div>
</template>

<style scoped>
.qa {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
}

.qa__presets {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.qa__chip,
.qa__btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 10px;
}

.qa__chip:hover,
.qa__btn:hover:not(:disabled) {
  color: var(--text-bright);
  background: var(--control-hover);
}

.qa__btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.qa__chipDot {
  width: 9px;
  height: 9px;
  border: 1px solid var(--hair);
  border-radius: 50%;
}

.qa__ops {
  display: flex;
  gap: 4px;
}
</style>
