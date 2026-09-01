<script setup>
// 识别参数控件组 (视觉调试台 & HITL 重识别门共用, 5 参数一处维护)。
// mode='value'    : 绑定有类型的当前值 (调试台 state.recognition_params); rotation 空输入 → null (每帧自动估)。
// mode='override' : 全部控件以 '' 表示"用基线"; baseline 提供占位显示的基线实际值。
// 0 是合法覆盖值 — 判空只用 '', 不用 falsy (None-sentinel 零值坑)。
const props = defineProps({
  modelValue: { type: Object, required: true },
  mode: { type: String, default: 'value' },        // 'value' | 'override'
  baseline: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'change'])

function set(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
  emit('change', key)
}
function numOrNull(raw) {
  if (raw === '' || raw === null) return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}
function ph(key, fallback = '') {
  if (props.mode !== 'override') return fallback
  const v = props.baseline?.[key]
  if (v === undefined) return '基线'
  if (v === null) return '基线 自动'
  return `基线 ${v}`
}
</script>

<template>
  <div class="rp">
    <label class="rp-field">
      <span>板朝向</span>
      <select
        :value="modelValue.image_plate_orientation"
        @change="set('image_plate_orientation', $event.target.value)"
      >
        <option v-if="mode === 'override'" value="">{{ ph('image_plate_orientation') }}</option>
        <option value="rot0">rot0</option>
        <option value="rot90cw">rot90cw</option>
        <option value="rot180">rot180</option>
        <option value="rot270cw">rot270cw</option>
      </select>
    </label>
    <label v-if="mode === 'value'" class="rp-check">
      <input
        type="checkbox"
        :checked="!!modelValue.auto_rectify_tilt"
        @change="set('auto_rectify_tilt', $event.target.checked)"
      />
      <span>自动倾斜矫正</span>
    </label>
    <label v-else class="rp-field">
      <span>倾斜矫正</span>
      <select
        :value="modelValue.auto_rectify_tilt"
        @change="set('auto_rectify_tilt', $event.target.value)"
      >
        <option value="">{{ ph('auto_rectify_tilt') }}</option>
        <option value="true">开</option>
        <option value="false">关</option>
      </select>
    </label>
    <label class="rp-field">
      <span>最小矫正角 deg</span>
      <input
        type="number" min="0" step="0.1"
        :value="modelValue.rectify_min_angle_deg"
        :placeholder="ph('rectify_min_angle_deg')"
        @input="set('rectify_min_angle_deg', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
    <label class="rp-field">
      <span>min_row_score</span>
      <input
        type="number" min="0" step="0.1"
        :value="modelValue.min_row_score"
        :placeholder="ph('min_row_score')"
        @input="set('min_row_score', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
    <label class="rp-field">
      <span>相机滚转角 deg</span>
      <input
        type="number" step="0.01"
        :value="modelValue.image_plate_rotation_deg"
        :placeholder="ph('image_plate_rotation_deg', '空 = 每帧自动估')"
        @input="set('image_plate_rotation_deg', mode === 'override' ? $event.target.value : numOrNull($event.target.value))"
      />
    </label>
  </div>
</template>

<style scoped>
.rp { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin: 6px 0; }
.rp-field { display: grid; grid-template-columns: 110px minmax(0, 1fr); align-items: center; gap: 6px;
  font-size: var(--fs-12); color: var(--subtle); font-weight: 650; }
.rp-field input, .rp-field select { min-width: 0; min-height: 26px; padding: 3px 6px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--field-bg); color: var(--text); font-size: var(--fs-13); }
.rp-check { display: flex; align-items: center; gap: 8px; font-size: var(--fs-12); color: var(--subtle); font-weight: 650; }
</style>
