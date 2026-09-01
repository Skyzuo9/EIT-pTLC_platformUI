<script setup>
// 机器人碰撞/活动故障 顶部红条横幅 (一等公民告警)
// 常驻挂在应用外壳最上层 (App.vue), 由 alarms store 的 visible 驱动显隐。
// 远比监视器里那枚红色 FAILED 标签醒目: 满宽红条 + 闪烁 + 提示音 (声音在 store onset 触发)。
import { computed } from 'vue'
import { useAlarmStore } from '../stores/alarms'

const alarms = useAlarmStore()
const a = computed(() => alarms.current)
const sourceLabel = computed(() => (a.value && a.value.source === 'idle' ? '空闲监测' : '运行中'))

const CLOCK = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
function fmtClock(ts) {
  return ts ? CLOCK.format(new Date(ts)) : ''
}
</script>

<template>
  <transition name="alarm-slide">
    <div v-if="alarms.visible" class="alarm-banner" role="alert" aria-live="assertive">
      <span class="alarm-beacon" aria-hidden="true"></span>
      <div class="alarm-body">
        <div class="alarm-line1">
          <span class="alarm-title">机器人碰撞 / 活动故障</span>
          <span class="alarm-code" v-if="a && a.code && a.code !== '—'">报警码 {{ a.code }}</span>
          <span class="alarm-src">{{ sourceLabel }}</span>
          <span class="alarm-time" v-if="a && a.ts">{{ fmtClock(a.ts) }}</span>
        </div>
        <div class="alarm-msg">{{ a && a.message }}</div>
      </div>
      <button class="alarm-dismiss" type="button" @click="alarms.dismiss()" title="关闭横幅 (故障解除后自动复位)">关闭</button>
    </div>
  </transition>
</template>

<style scoped>
.alarm-banner {
  /* 文档流首行 (App.vue #app flex column): 告警推压控制台下移, 永不盖住态势条急停。
     z-index 仍拉高: 模态 backdrop (fixed, z1000) 出现时告警条依然可见 (根堆叠上下文内胜出) */
  position: relative;
  z-index: 3000;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 18px;
  background: #b42318;          /* 强制深红, 不随主题淡化, 保证最高辨识度 (eit danger 加深档) */
  color: #ffffff;
  border-bottom: 3px solid #8f2418;
  box-shadow: 0 4px 18px rgba(127, 0, 0, 0.55);
}
/* 整条红度轻微起伏: 动 opacity (合成器) 而非 background (原每帧重绘满宽条);
   prefers-reduced-motion 时被全局降频块冻结, 静态红条本身已足够醒目 */
.alarm-banner::before {
  content: "";
  position: absolute;
  inset: 0;
  background: #d6422b;
  opacity: 0;
  animation: alarm-flash 1.1s ease-in-out infinite;
  pointer-events: none;
}
.alarm-banner > * { position: relative; z-index: 1; }
@keyframes alarm-flash {
  0%, 100% { opacity: 0; }
  50% { opacity: 1; }
}
.alarm-beacon {
  flex: 0 0 auto;
  position: relative;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
}
/* 扩散环: transform+opacity (原 box-shadow 扩散是大面积 paint) */
.alarm-beacon::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.85);
  transform-origin: center;
  animation: alarm-pulse 1s ease-out infinite;
}
@keyframes alarm-pulse {
  0% { transform: scale(1); opacity: 0.85; }
  70%, 100% { transform: scale(2.4); opacity: 0; }
}
.alarm-body { min-width: 0; flex: 1; }
.alarm-line1 { display: flex; align-items: baseline; flex-wrap: wrap; gap: 10px; }
.alarm-title { font-size: 15px; font-weight: 800; letter-spacing: 0.5px; }
.alarm-code {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.28);
  color: #fff;
}
.alarm-src { font-size: var(--fs-12); font-weight: 700; opacity: 0.92; }
.alarm-time { font-size: var(--fs-12); opacity: 0.8; margin-left: auto; }
.alarm-msg {
  margin-top: 3px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  opacity: 0.97;
}
.alarm-dismiss {
  flex: 0 0 auto;
  align-self: center;
  padding: 6px 16px;
  font-size: var(--fs-13);
  font-weight: 700;
  color: #b42318;
  background: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
}
.alarm-dismiss:hover { background: #ffe1de; }

/* 进入/离开: 从顶部滑入 */
.alarm-slide-enter-active, .alarm-slide-leave-active { transition: transform 0.18s ease, opacity 0.18s ease; }
.alarm-slide-enter-from, .alarm-slide-leave-to { transform: translateY(-100%); opacity: 0; }
</style>
