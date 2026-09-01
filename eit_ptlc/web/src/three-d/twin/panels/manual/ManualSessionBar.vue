<script setup>
/**
 * 功能: 手动控制会话条 —— 显示会话/模式状态并提供进入·退出按钮.
 *
 * 会话是**整页一份**(useManualSession), 本组件只是它的一个显示面, 渲染在
 * 「工站信息」页的整机操作段; 工位「操作」页的入口是「模块状态」标题行右侧的
 * 紧凑按钮(StationActionsTab), 两处指向同一个会话.
 */
defineProps({
  /** ManualSession 的对外状态 {state, reason, jogging} */
  state: { type: Object, default: () => ({ state: 'idle', reason: '' }) },
  /** 上位机控制模式 */
  mode: { type: String, default: '' },
  /** /api/mode 请求本身失败 */
  modeOffline: { type: Boolean, default: false },
  /** 是否 DEBUG 模式 */
  modeAllowed: { type: Boolean, default: false },
  /** 会话是否已生效 */
  active: { type: Boolean, default: false },
  /** 模式门未过时的原因 */
  gateReason: { type: String, default: '' },
})

const emit = defineEmits(['toggle'])

const STATE_TEXT = {
  idle: '未进入', entering: '进入中…', active: '手动控制中 · 心跳保持', lost: '会话失联',
}
</script>

<template>
  <div class="msb">
    <div class="msb__line" :class="{ 'msb__line--on': active }">
      <span class="msb__state">{{ STATE_TEXT[state.state] || state.state }}</span>
      <em class="msb__mode" :class="{ 'msb__mode--ok': modeAllowed }">
        {{ modeOffline ? '后端未连' : mode || '模式未知' }}
      </em>
      <button
        type="button"
        class="dock-btn"
        :disabled="!modeAllowed && !active"
        :title="modeAllowed ? '' : '仅调试模式可进入(后端 403 双保险)'"
        @click="emit('toggle')"
      >{{ active ? '退出手动控制' : '进入手动控制' }}</button>
    </div>
    <p v-if="gateReason" class="msb__gate">{{ gateReason }}</p>
    <p v-else-if="state.reason" class="msb__gate">{{ state.reason }}</p>
  </div>
</template>

<style scoped>
.msb {
  display: grid;
  gap: 4px;
}

.msb__line {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 5px 8px;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.msb__line--on {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}

.msb__state {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msb__mode {
  flex: none;
  padding: 1px 6px;
  font-size: 10px;
  font-style: normal;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.msb__mode--ok {
  color: var(--ok);
  border-color: color-mix(in srgb, var(--ok, #39d98a) 45%, transparent);
}

.msb__gate {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}
</style>
