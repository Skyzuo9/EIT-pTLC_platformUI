<script setup>
// 单流程步骤时间线弹窗: 上半 = 最近一次干净运行的步骤条 (按 depth 缩进, 偏移归一化),
// 下半 = 窗口内按 (script, aid) 的跨运行步骤统计表。数据来自 /api/planner/.../timeline。
// 壳层走 ModalShell (dialog 语义/焦点圈禁/Esc); 常挂载由 open prop 驱动 (照 ConfirmHost 范式)
// —— 原先父级 v-if + :open="true" 会让关闭沿的还焦分支永不触发, 焦点回不到触发按钮。
import { computed, ref, watch } from 'vue'

import { api, errText } from '../../api.js'
import { fmtDur } from '../../utils/planner.js'
import { fmtTime } from '../../utils/format.js'
import ModalShell from '../ui/ModalShell.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  name: { type: String, default: '' }, // 关闭态为空串 (required 会在关闭态刷 warn)
  window: { type: Number, default: 50 },
})
const emit = defineEmits(['close'])

const data = ref(null)
const loading = ref(true)
const error = ref('')

const title = computed(() =>
  `步骤时间线 —— ${data.value ? data.value.label : props.name} (${props.name})`)

// 每次打开(或打开中换流程)重置并取数; 关闭态不取
watch(() => [props.open, props.name], async ([open]) => {
  if (!open || !props.name) return
  data.value = null
  error.value = ''
  loading.value = true
  try {
    data.value = await api.plannerTimeline(props.name, props.window)
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}, { immediate: true })

// 步骤条几何: 偏移/时长按运行总时长归一化为百分比
function barStyle(step) {
  const total = (data.value && data.value.last_run && data.value.last_run.duration_s) || 0
  if (!(total > 0)) return { left: 0, width: '2px' }
  const left = Math.min(100, Math.max(0, (step.start_offset_s / total) * 100))
  const width = Math.max(0.4, (step.duration_s / total) * 100)
  return { left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }
}
</script>

<template>
  <ModalShell :open="open" wide :title="title" @close="emit('close')">
    <div class="planner-timeline" data-test="op-timeline">
      <p v-if="loading" class="empty loading">加载中…</p>
      <p v-else-if="error" class="empty err">{{ error }}</p>
      <template v-else-if="data">
        <p v-if="data.baseline_ts" class="meta base">
          已清除记录: 只统计 {{ fmtTime(data.baseline_ts) }} 之后的运行 (原记录未删, 可在左栏撤销)
        </p>
        <p class="meta">
          窗口 {{ data.window }} 次: 有效 {{ data.count }} 次, 剔除干预 {{ data.excluded }} 次
          <template v-if="data.last_run">
            · 最近一次 {{ fmtTime(data.last_run.started_at) }},
            总时长 {{ fmtDur(data.last_run.duration_s) }}
            <span v-if="data.last_run.unpaired" class="warn">
              (有 {{ data.last_run.unpaired }} 个步骤缺结束事件, 已忽略)
            </span>
          </template>
        </p>

        <p v-if="!data.last_run" class="empty">该流程暂无干净的成功运行记录</p>
        <template v-else>
          <div class="bars">
            <div v-for="(step, i) in data.last_run.steps" :key="i"
                 class="bar-row" :class="{ container: step.op === 'run_script' }">
              <div class="bar-name" :style="{ paddingLeft: step.depth * 14 + 'px' }"
                   :title="`${step.script} · ${step.aid}`">
                {{ step.action || step.aid }}
              </div>
              <div class="bar-track">
                <div class="bar" :class="{ failed: step.status !== 'DONE' }" :style="barStyle(step)"
                     :title="`${fmtDur(step.start_offset_s)} 起, 历时 ${fmtDur(step.duration_s)}`"></div>
              </div>
              <div class="bar-dur">{{ fmtDur(step.duration_s) }}</div>
            </div>
          </div>

          <h4>跨运行步骤统计 (窗口内平均)</h4>
          <div class="stat-wrap">
            <table class="stat-table">
              <thead>
                <tr>
                  <th scope="col">脚本</th><th scope="col">步骤</th><th scope="col">动作/子流程</th>
                  <th scope="col">次数</th><th scope="col">平均</th><th scope="col">最小</th><th scope="col">最大</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in data.step_stats" :key="row.script + row.aid">
                  <td>{{ row.script }}</td>
                  <td>{{ row.aid }}</td>
                  <td>{{ row.action }}</td>
                  <td class="num">{{ row.count }}</td>
                  <td class="num">{{ fmtDur(row.avg_s) }}</td>
                  <td class="num">{{ fmtDur(row.min_s) }}</td>
                  <td class="num">{{ fmtDur(row.max_s) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>

    <template #actions>
      <button class="mini" @click="emit('close')">关闭</button>
    </template>
  </ModalShell>
</template>

<style scoped>
/* 宽度由 ModalShell 的 .modal-wide 统一 (860px); 原 720px 定宽随手写骨架一并去掉 */
.meta { color: var(--subtle); font-size: var(--fs-12); margin: 0 0 10px; }
.meta .warn { color: var(--warn-strong); }
.meta.base { color: var(--warn-strong); margin-bottom: 4px; }
.empty { color: var(--subtle); }
.empty.err { color: var(--bad); }

.bars { display: flex; flex-direction: column; gap: 2px; max-height: 40vh; overflow: auto; overscroll-behavior: contain; border: 1px solid var(--border); border-radius: 6px; padding: 6px; }
.bar-row { display: grid; grid-template-columns: 220px minmax(0, 1fr) 70px; align-items: center; gap: 8px; font-size: var(--fs-12); }
.bar-row.container .bar-name { font-weight: 600; }
.bar-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { position: relative; height: 12px; background: var(--surface-2); border-radius: 3px; }
.bar { position: absolute; top: 1px; height: 10px; border-radius: 3px; background: var(--accent); opacity: 0.8; min-width: 2px; }
.bar.failed { background: var(--bad); }
.bar-dur { text-align: right; color: var(--subtle); }

h4 { margin: 12px 0 6px; font-size: var(--fs-13); }
.stat-wrap { max-height: 30vh; overflow: auto; overscroll-behavior: contain; border: 1px solid var(--border); border-radius: 6px; }
.stat-table { width: 100%; border-collapse: collapse; font-size: var(--fs-12); }
.stat-table th, .stat-table td { text-align: left; padding: 3px 8px; border-bottom: 1px solid var(--border); white-space: nowrap; }
.stat-table th { position: sticky; top: 0; background: var(--panel); }
</style>
