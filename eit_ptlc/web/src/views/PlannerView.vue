<script setup>
// 排程页 (中区): 上 = 工具条 + 样品条 (横排卡片, SampleEditor), 下 = 甘特图占满全宽。
// 只做模拟计算与展示 (平均耗时来自 /api/planner/stats), 不控制设备执行。
// 窗口/口径等统计设置在左 Dock「流程耗时」的 ⚙ 弹窗里 (TimingSettingsModal)。
import { computed, onMounted, ref } from 'vue'

import GanttChart from '../components/planner/GanttChart.vue'
import OpTimelineModal from '../components/planner/OpTimelineModal.vue'
import SampleEditor from '../components/planner/SampleEditor.vue'
import { confirmAction } from '../composables/confirmService.js'
import { useQuerySync } from '../composables/useQuerySync.js'
import { usePlannerStore } from '../stores/planner'
import { fmtDur } from '../utils/planner.js'

const planner = usePlannerStore()

const ganttWrap = ref(null)        // 甘特滚动容器 (适配缩放量宽用)

// 缩放倍率进 URL (?zoom=): 对 store 值包一层可写 computed 交给 useQuerySync 双向同步;
// 非法值由 setPxPerSec 自钳制丢弃。defaultValue=2 即 store 缺省 (planner.js), 等于它时不占 URL。
const pxPerSecSync = computed({
  get: () => planner.plan.settings.pxPerSec,
  set: (v) => planner.setPxPerSec(v),
})
useQuerySync('zoom', pxPerSecSync, { parse: Number, serialize: String, defaultValue: 2 })

function zoom(factor) {
  planner.setPxPerSec(planner.plan.settings.pxPerSec * factor)
}

// 自动排程会整体覆盖手动拖出的排布, 走危险确认
async function autoSchedule() {
  const ok = await confirmAction({
    level: 'danger',
    title: '重新自动排程',
    message: '将覆盖当前手动拖动的排布, 不可恢复。',
    confirmText: '重新排程',
  })
  if (!ok) return
  planner.autoSchedule()
}

// 适配: 让总时长占满当前甘特可视宽 (扣掉泳道名列)
function fitToView() {
  const el = ganttWrap.value
  if (el) planner.fitToWidth(Math.max(el.clientWidth - 160, 100))
}

onMounted(() => { planner.ensureStats() })
</script>

<template>
  <div class="planner-page">
    <div class="toolbar">
      <h2 class="ttl">排程模拟</h2>
      <span class="mode-hint" data-test="duration-mode">
        时间口径 {{ planner.plan.settings.durationMode === 'last' ? '最新一次' : '窗口平均' }}
        <small>(左栏 ⚙ 设置)</small>
      </span>
      <span class="zoom">
        <button class="mini" title="缩小" aria-label="缩小时间轴" @click="zoom(1 / 1.5)">−</button>
        <button class="mini" title="总时长占满可视宽" @click="fitToView">适配</button>
        <button class="mini" title="放大" aria-label="放大时间轴" @click="zoom(1.5)">+</button>
      </span>
      <button class="mini primary" title="FIFO 贪心重排 (会覆盖手动拖动的结果)"
              @click="autoSchedule">自动排程</button>
      <span class="makespan">总时长 <b class="num">{{ fmtDur(planner.makespanS) }}</b></span>
      <span v-if="planner.conflicts.length" role="status" class="conflict-badge" data-test="conflict-count">
        冲突 {{ planner.conflicts.length }}
      </span>
      <span v-if="planner.loading" class="hint">统计加载中…</span>
      <span v-else-if="planner.error" role="status" class="hint err">{{ planner.error }}</span>
      <span v-else class="hint">仅模拟, 不控制执行</span>
    </div>

    <!-- 样品横条 (原 260px 左侧栏): 甘特因此吃满全宽 -->
    <SampleEditor />

    <div ref="ganttWrap" class="gantt-wrap">
      <GanttChart
        :placements="planner.placements"
        :samples="planner.plan.samples"
        :conflict-keys="planner.conflictKeys"
        :px-per-sec="planner.plan.settings.pxPerSec"
        :resources-meta="planner.resourcesMeta"
        :op-index="planner.opIndex"
        :duration-mode="planner.plan.settings.durationMode"
        :makespan-s="planner.makespanS"
        @select="(p) => planner.openTimeline(p.opName)"
        @move="({ key, startS }) => planner.moveBlock(key, startS)"
      />
    </div>

    <!-- 弹窗由 store 驱动: 左 Dock 的「明细」菜单项与甘特块点击共用同一入口。
         常挂载 + :open 驱动 (非 v-if): ModalShell 关闭沿才能把焦点还给触发按钮 -->
    <OpTimelineModal :open="!!planner.timelineOp" :name="planner.timelineOp || ''"
                     :window="planner.plan.settings.window" @close="planner.closeTimeline()" />
  </div>
</template>

<style scoped>
.planner-page { display: flex; flex-direction: column; gap: 8px; height: 100%; min-height: 0; }
.toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; flex: 0 0 auto; }
/* span→h2 语义升级: 复位 h2 的 UA 外边距/字号, 视觉保持原 span 观感 */
.toolbar .ttl { font-weight: 600; font-size: 1em; margin: 0; }
.toolbar .mode-hint { color: var(--subtle); font-size: var(--fs-12); }
.toolbar .zoom { display: inline-flex; gap: 4px; }
.toolbar .makespan { font-size: var(--fs-13); }
.conflict-badge { color: var(--on-accent); background: var(--bad); border-radius: 999px; padding: 1px 8px; font-size: var(--fs-12); }
.hint { color: var(--subtle); font-size: var(--fs-12); }
.hint.err { color: var(--bad); }
.gantt-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; }
</style>
