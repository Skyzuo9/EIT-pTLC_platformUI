<script setup>
/**
 * 功能: 单根运动轴的手动操作行 —— 点动 / 绝对定位 / 回零 / 停 / 清错.
 *
 * 从旧 ManualControlPanel 原样抽出, 行为一字不改. 抽出的理由是它现在要在两个地方渲染:
 * 各工位「操作」页只拿本工位那几根.
 *
 * jog 刻意**没有二次确认** —— 按住即动 / 松手即停本身就是它的安全模型, 加确认反而
 * 会让人先点掉确认再按住, 把"松手即停"这条命脉从肌肉记忆里挤走.
 */
import { ref } from 'vue'

const props = defineProps({
  /** 轴行 {id, label, position, stale, jogging, rigged, focusable} */
  row: { type: Object, required: true },
  /** 是否允许下发(模式门 + 会话门都过了) */
  canWrite: { type: Boolean, default: false },
  /** 当前点动方向('pos'|'neg'|null), 用于高亮 */
  jogDirection: { type: String, default: null },
  /**
   * 只读行: 整段操作控件(jog/定位/回零/停/清错)都不渲染, 只留名字与读数.
   * 未进入单点模式时置真 —— 用户定案"全部隐藏只留读数"(2026-08-14):
   * 没进单点就没有本页发起的运动, 停/清错也一并收进门后; 紧急收敛走顶栏急停。
   */
  readonlyRow: { type: Boolean, default: false },
  /** 本行是否是当前聚焦的那个零件(行高亮; 低画质档没有描边链, 这条是兜底反馈) */
  focused: { type: Boolean, default: false },
})

const emit = defineEmits(['jog-press', 'jog-release', 'move', 'op', 'focus'])

/** 定位输入暂存(mm 文本) */
const target = ref('')

function doMove() {
  emit('move', props.row.id, target.value)
}
</script>

<template>
  <section class="mar" :class="{ 'mar--focused': focused }">
    <div class="mar__line">
      <!-- 只有名字这一块可点 = 聚焦。整行可点的旧写法会让"停/清错"也顺带把相机飞走 -->
      <button
        type="button"
        class="mar__name"
        :disabled="!row.focusable"
        :title="row.focusable
          ? `${row.label} —— 点击在三维里聚焦并描边`
          : `${row.label} —— 模型里没有这根轴的几何, 无法聚焦`"
        @click="emit('focus', row.id)"
      >
        <span class="mar__id">{{ row.id }}</span>
        <span class="mar__label">{{ row.label }}</span>
      </button>
      <b class="mar__pos" :class="{ 'mar__pos--stale': row.stale }">
        {{ row.position === null ? '—' : row.position.toFixed(1) }} mm
      </b>
    </div>
    <div v-if="!readonlyRow" class="mar__line mar__line--ops">
      <!-- 按住点动: pointerdown 起, 松开/移出/取消任一即停 -->
      <button
        type="button"
        class="mar__jog"
        :class="{ 'mar__jog--on': row.jogging && jogDirection === 'neg' }"
        :disabled="!canWrite"
        title="按住反向点动, 松手即停(0.8s 窗口兜底)"
        @pointerdown.prevent="emit('jog-press', row.id, 'neg')"
        @pointerup="emit('jog-release')"
        @pointerleave="emit('jog-release')"
        @pointercancel="emit('jog-release')"
      >−jog</button>
      <button
        type="button"
        class="mar__jog"
        :class="{ 'mar__jog--on': row.jogging && jogDirection === 'pos' }"
        :disabled="!canWrite"
        title="按住正向点动, 松手即停(0.8s 窗口兜底)"
        @pointerdown.prevent="emit('jog-press', row.id, 'pos')"
        @pointerup="emit('jog-release')"
        @pointerleave="emit('jog-release')"
        @pointercancel="emit('jog-release')"
      >+jog</button>
      <input
        v-model="target"
        class="mar__target"
        type="number"
        placeholder="mm"
        :disabled="!canWrite"
        @keydown.enter="doMove"
      >
      <button type="button" class="mar__mini" :disabled="!canWrite" title="绝对定位到输入值"
              @click="doMove">定位</button>
      <button type="button" class="mar__mini" :disabled="!canWrite" title="单轴回零"
              @click="emit('op', row.id, 'home')">回零</button>
      <button type="button" class="mar__mini mar__mini--stop" title="停止该轴(不限模式)"
              @click="emit('op', row.id, 'stop')">停</button>
      <button type="button" class="mar__mini" title="清错(不限模式)"
              @click="emit('op', row.id, 'reset')">清错</button>
    </div>
  </section>
</template>

<style scoped>
.mar {
  display: grid;
  gap: 3px;
  padding: 5px 0;
  border-bottom: 1px solid var(--border);
}

.mar__line {
  display: flex;
  gap: 6px;
  align-items: center;
}

.mar__line--ops {
  flex-wrap: wrap;
}

.mar--focused {
  background: var(--accent-soft);
}

.mar__name {
  display: flex;
  flex: 1;
  gap: 6px;
  align-items: center;
  min-width: 0;
  padding: 1px 3px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
}

.mar__name:hover:not(:disabled) {
  color: var(--text-bright);
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.mar__name:disabled {
  cursor: default;
  opacity: 0.75;
}

.mar__id {
  flex: none;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  color: var(--text-dim);
}

.mar__label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mar__pos {
  flex: none;
  font-size: 12px;
  color: var(--accent-bright);
  font-variant-numeric: tabular-nums;
}

.mar__pos--stale {
  color: var(--text-dim);
}

.mar__jog,
.mar__mini {
  padding: 3px 8px;
  font-size: 11px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 5px;
  touch-action: none;
}

.mar__jog:hover:not(:disabled),
.mar__mini:hover:not(:disabled) {
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.mar__jog:disabled,
.mar__mini:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.mar__jog--on {
  color: var(--accent-ink, #fff);
  background: var(--accent);
  border-color: var(--accent);
}

.mar__mini--stop {
  color: var(--err-bright);
}

.mar__target {
  width: 62px;
  padding: 3px 6px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 5px;
}
</style>
