<script setup>
/**
 * 功能: 单个执行器(气缸/阀/泵/夹爪…)的手动开关行.
 *
 * 从旧 ManualControlPanel 原样抽出. 状态标识是明文三态(不用圆点, 圆点辨识度太低):
 *   「开」= 到位反馈为真; 「关」= 为假; 虚线降透明 = 陈旧(实时流断了, 显示的是末态).
 * 三态不能压成两态 —— "读不到"画成"关着"会把人引到错误的地方查.
 */
import { computed } from 'vue'
const props = defineProps({
  /** 机构行 {id, label, kind, effective, commanded, stale, focusable} */
  row: { type: Object, required: true },
  /** 是否允许下发 */
  canWrite: { type: Boolean, default: false },
  /** 是否显示 manifest 原始 kind(仅"其他执行器"这类混合组需要) */
  showKind: { type: Boolean, default: false },
  /**
   * 只读行: 不画开/关按钮.
   * 机械臂那 4 个执行器(夹爪/吸盘/翻转)在 manifest 里只是**显示态** —— manual_points.yaml
   * 里没有它们, 走 /api/manual/cylinder 必然 404。真正的写路径是 robot.tool_action。
   */
  readonlyRow: { type: Boolean, default: false },
  /** 本行是否是当前聚焦的那个零件 */
  focused: { type: Boolean, default: false },
})

const emit = defineEmits(['set', 'focus'])

/** 明文状态: 开 / 关 / —(从未读到值) */
const stateText = computed(() => {
  if (props.row.effective === 1 || props.row.effective === true) return '开'
  if (props.row.effective === 0 || props.row.effective === false) return '关'
  return '—'
})

/** 名字的悬停说明: 聚焦能力 + 行级附注(如泵行的副作用提示, row.hint 可选) */
const nameTitle = computed(() => {
  const base = props.row.focusable
    ? `${props.row.id} —— 点击在三维里聚焦并描边`
    : `${props.row.id} —— 模型里没有这个执行器的独立几何, 无法聚焦`
  return props.row.hint ? `${base}\n${props.row.hint}` : base
})
</script>

<template>
  <div class="mmr" :class="{ 'mmr--focused': focused }">
    <span
      class="mmr__state"
      :class="{
        'mmr__state--on': row.effective === 1 || row.effective === true,
        'mmr__state--stale': row.stale,
      }"
      :title="`下令=${row.commanded} 反馈=${row.effective}${row.stale ? ' (已冻结)' : ''}`"
    >{{ stateText }}</span>
    <!-- 名字可点 = 在三维里聚焦; 55 个执行器里只有 20 个有独立几何, 其余置灰并说明原因 -->
    <button
      type="button"
      class="mmr__name"
      :disabled="!row.focusable"
      :title="nameTitle"
      @click="emit('focus', row.id)"
    >{{ row.label }}</button>
    <span v-if="showKind" class="mmr__kind">{{ row.kind }}</span>
    <template v-if="!readonlyRow">
      <button type="button" class="mmr__mini" :disabled="!canWrite"
              @click="emit('set', row, true)">开</button>
      <button type="button" class="mmr__mini" :disabled="!canWrite"
              @click="emit('set', row, false)">关</button>
    </template>
  </div>
</template>

<style scoped>
.mmr {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 3px 0;
}

.mmr__state {
  flex: none;
  width: 22px;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
  text-align: center;
  border: 1px solid var(--border);
  border-radius: 4px;
}

.mmr__state--on {
  color: var(--ok);
  border-color: color-mix(in srgb, var(--ok, #39d98a) 55%, transparent);
  box-shadow: 0 0 6px var(--ok-soft);
}

.mmr__state--stale {
  border-style: dashed;
  opacity: 0.6;
  box-shadow: none;
}

.mmr--focused {
  background: var(--accent-soft);
}

.mmr__name {
  flex: 1;
  min-width: 0;
  padding: 1px 3px;
  overflow: hidden;
  font-size: 12px;
  color: var(--text);
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
}

.mmr__name:hover:not(:disabled) {
  color: var(--text-bright);
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.mmr__name:disabled {
  cursor: default;
  opacity: 0.75;
}

.mmr__kind {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.mmr__mini {
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.mmr__mini:hover:not(:disabled) {
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.mmr__mini:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}
</style>
