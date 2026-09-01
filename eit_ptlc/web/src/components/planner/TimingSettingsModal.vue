<script setup>
// 耗时统计设置弹窗 (左 Dock「流程耗时」⚙): 统计窗口 / 时间口径 / 全局清除·撤销。
// 常挂载 + :open 驱动 (照 OpTimelineModal): 关闭沿的还焦分支才能把焦点还给 ⚙ 触发钮。
// 「清除全部记录」用 InlineConfirm 而非 confirmAction: 两个 ModalShell 叠加会互抢
// capture keydown (Tab 焦点圈禁互拽 / Esc 两层同关), 确认段必须留在本弹窗文档流内。
import { ref, watch } from 'vue'

import { usePlannerStore } from '../../stores/planner'
import InlineConfirm from '../ui/InlineConfirm.vue'
import ModalShell from '../ui/ModalShell.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])
const planner = usePlannerStore()

// 危险区内联确认段展开态; 关弹窗顺带收起, 防下次打开残留半按下的确认
const confirmClearAll = ref(false)
watch(() => props.open, (on) => {
  if (!on) confirmClearAll.value = false
})

function onWindowChange(ev) {
  planner.setWindow(Number(ev.target.value))
  // store 自钳 1..200 并重拉统计; 回写输入框防显示越界值
  ev.target.value = planner.plan.settings.window
}

function clearAll() {
  planner.resetBaseline(null)
  confirmClearAll.value = false
}
</script>

<template>
  <ModalShell :open="open" title="耗时统计设置" initial-focus="#tm-set-window" @close="emit('close')">
    <label class="set-row">
      <span class="lbl">统计窗口</span>
      <input id="tm-set-window" type="number" min="1" max="200"
             :value="planner.plan.settings.window"
             title="平均取每个流程最近 N 次成功运行" @change="onWindowChange" />
      <span>次</span>
    </label>
    <p class="set-note">按每流程最近 N 次运行聚合; 改动后自动重新拉取统计</p>

    <div class="set-row">
      <span class="lbl">时间口径</span>
      <span class="seg">
        <button class="mini" :class="{ on: planner.plan.settings.durationMode === 'avg' }"
                title="用窗口内平均耗时" @click="planner.setDurationMode('avg')">平均</button>
        <button class="mini" :class="{ on: planner.plan.settings.durationMode === 'last' }"
                title="用最新一次运行的实测耗时" @click="planner.setDurationMode('last')">最新</button>
      </span>
    </div>

    <div class="set-divider" role="separator" />
    <div class="sec-title">数据管理</div>

    <button v-if="planner.hasGlobalBaseline" class="mini ok" data-test="undo-all-baseline"
            title="撤销全局基线, 恢复用全部历史统计" @click="planner.clearBaseline(null)">
      ↺ 撤销全部清除
    </button>
    <template v-else>
      <button v-if="!confirmClearAll" class="btn danger ghost" data-test="clear-all-baseline"
              title="作废所有流程的现有耗时记录 (只重置统计起点, 不删运行记录, 可撤销)"
              @click="confirmClearAll = true">
        清除全部记录
      </button>
      <InlineConfirm v-else
                     title="作废所有流程的耗时记录"
                     message="只重置统计起点, 运行记录与回放保留, 可随时撤销。"
                     confirm-text="作废"
                     @confirm="clearAll" @cancel="confirmClearAll = false" />
    </template>

    <template #actions>
      <button class="btn ghost" @click="emit('close')">关闭</button>
    </template>
  </ModalShell>
</template>

<style scoped>
.set-row { display: flex; align-items: center; gap: 8px; margin: 10px 0; font-size: var(--fs-13); }
.set-row .lbl { color: var(--subtle); font-weight: 600; min-width: 74px; }
.set-row input[type="number"] { width: 72px; padding: 4px 8px; border: 1px solid var(--border); border-radius: var(--radius-md); }
.set-row .seg { display: inline-flex; gap: 4px; }
/* 口径分段控件选中态 (全局 .mini 无此态; 自 ExplorerDock 迁入) */
.set-row .mini.on { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.set-note { color: var(--muted); font-size: var(--fs-11); margin: 2px 0 0 82px; }
.set-divider { border-top: 1px solid var(--border-soft); margin: 14px 0 10px; }
.sec-title { font-size: var(--fs-12); color: var(--subtle); font-weight: 650; margin-bottom: 8px; }
.mini.ok { border-color: var(--ok); color: var(--ok); }
</style>
