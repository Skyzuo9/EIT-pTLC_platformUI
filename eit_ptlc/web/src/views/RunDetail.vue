<script setup>
// 执行详情 (中区): 历史运行回放 —— 由有序事件序列复现步骤树, 支持一键重放。
// 重放走前向增量 (applyEvent 逐条灌进持久 reactive 投影, 与实时 ingest/reseed 同一状态机):
// 原版每拍 reduceRun(slice(0,k)) 整场 O(N²) 且整树换引用 (StepTree 全树重渲),
// 现版整场 O(N)、view.steps 引用恒稳 (StepTree 增量 patch)。
import { ref, reactive, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import StepTree from '../components/StepTree.vue'
import { api, errText } from '../api'
import { applyEvent } from '../stores/runs'
import { fmtTime } from '../utils/format'
import { runStatusLabel } from '../utils/runStatus'

const route = useRoute()
const run = ref(null) // 原始记录 (含 events)
// 展示投影: 全字段形状照 runs.js reduceRun 初态; ctx 与它成对 (栈底哨兵持 view.steps 引用)
const view = reactive({ run_id: '', operation: '', label: '', status: '', message: '', steps: [] })
let ctx = { stack: [{ children: view.steps }] }
const loadError = ref('')
const replaying = ref(false)
const replayPos = ref(0)   // 已重放到第 k 个事件 (进度 k/N; 中途停止后保留, 续播从这继续)
let timer = null

// 投影重置: splice 就地清空保 reactive 引用 (照 runs.js reseedOne), 帧栈随之重建
function resetView() {
  view.run_id = ''
  view.operation = ''
  view.label = ''
  view.status = ''
  view.message = ''
  view.steps.splice(0)
  ctx = { stack: [{ children: view.steps }] }
}

function stopReplay() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
  replaying.value = false
}

async function load(id) {
  stopReplay()
  run.value = null
  resetView()
  loadError.value = ''
  replayPos.value = 0
  if (!id) return
  try {
    run.value = await api.getRun(id)
  } catch (e) {
    loadError.value = errText(e)
    return
  }
  // 终态展示: 一次性增量灌入 (O(N), 不再构造临时树)
  for (const ev of run.value.events) applyEvent(view, ctx, ev)
}

// 重放: 按事件顺序逐拍复现。重放中再点 = 停止 (兼防重入); 停止后再点 = 从当前位置续播;
// 已播完或正展示终态时起步 = 重置投影从头播
function replay() {
  if (!run.value) return
  if (replaying.value) {
    stopReplay()
    return
  }
  const events = run.value.events
  if (replayPos.value === 0 || replayPos.value >= events.length) {
    resetView()
    replayPos.value = 0
  }
  replaying.value = true
  timer = setInterval(() => {
    const k = replayPos.value + 1
    replayPos.value = k
    applyEvent(view, ctx, events[k - 1])   // 前向增量: 每拍恰好一条事件
    if (k >= events.length) stopReplay()
  }, 400)
}

watch(() => route.params.id, (id) => load(id), { immediate: true })
onUnmounted(stopReplay)
</script>

<template>
  <div class="detail">
    <p v-if="loadError" class="empty">
      <span>加载失败: {{ loadError }}</span>
      <button class="btn ghost retry" @click="load(route.params.id)">重试</button>
    </p>
    <p v-else-if="!run" class="empty">从左侧「执行」选择一次运行</p>
    <div v-else>
      <div class="head">
        <h2>
          {{ run.label || run.operation }}
          <small class="mono run-id" :title="run.run_id">{{ run.run_id }}</small>
          <span class="runtag" :class="view.status">{{ runStatusLabel(view.status) }}</span>
        </h2>
        <span class="replay-progress" role="status">
          <!-- 中途停止后继续显示 k/N, 点明步骤树是部分态; 播完自然收口 -->
          <span v-if="replaying || (replayPos > 0 && replayPos < run.events.length)" class="num">{{ replayPos }}/{{ run.events.length }}</span>
        </span>
        <button class="run" @click="replay">{{ replaying ? '停止重放' : '重放' }}</button>
      </div>
      <StepTree :steps="view.steps" />
      <pre v-if="run.message" class="result" :class="run.status">{{ run.message }}</pre>
      <div class="info">
        <div class="field"><span class="fname">开始</span><div>{{ fmtTime(run.started_at) }}</div></div>
        <div class="field"><span class="fname">结束</span><div>{{ fmtTime(run.finished_at) }}</div></div>
        <div class="field"><span class="fname">事件数</span><div class="num">{{ run.events.length }}</div></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* h2 标题样式已上提全局 (.detail h2, style.css); 标题行 flex 化, 重放按钮靠右 */
.head { display: flex; align-items: center; gap: 10px; margin: 0 0 12px; }
.head h2 { flex: 1; min-width: 0; margin: 0; }
.head .run { flex-shrink: 0; }
.mono { font-family: var(--font-mono); }
.run-id { display: inline-block; max-width: 320px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
.replay-progress { font-size: var(--fs-12); color: var(--subtle); }
/* label 改 span 后补回全局 .field label 的等价样式 (label 语义留给真表单控件) */
.fname { font-size: var(--fs-13); color: var(--subtle); font-weight: 600; }
.retry { margin-left: 8px; }
</style>
