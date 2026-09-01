<script setup>
// 调度视图: /schedule/:name? — 三层 (动作 / 流程 / 调度) 的第三层。
// 无 name = 空态引导; 有 name = 图形化编排器。
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import ScheduleOrchestrator from '../components/schedule/ScheduleOrchestrator.vue'
import { useEditorStore } from '../stores/editor'
import { useSchedulerStore } from '../stores/scheduler'

const route = useRoute()
const editor = useEditorStore()
const scheduler = useSchedulerStore()

onMounted(() => {
  // 段调色板与右栏下拉要流程摘要 (ui.role==='segment'); 方案列表供左栏与空态
  if (!editor.operations.length) editor.loadRepo().catch(() => {})
  scheduler.ensureRecipes()
})
</script>

<template>
  <!-- :key 让换方案时编排器整体重建 (本地选中态/校验结果不残留) -->
  <ScheduleOrchestrator v-if="route.params.name" :key="route.params.name" :name="route.params.name" />
  <div v-else class="empty sv-empty">
    <p>从左侧选一个调度方案, 或新建一个。</p>
    <p class="muted">
      调度方案 = 把「流程」里的段组合成一条实验链, 并规定谁能和谁并行:
      链式依赖 = 串行, 分叉 = 并行。改它不需要改代码, 保存时后端做全链静态校验。
    </p>
  </div>
</template>

<style scoped>
.sv-empty { flex-direction: column; gap: 8px; padding: 0 24px; text-align: center; }
.sv-empty p { margin: 0; max-width: 520px; }
</style>
