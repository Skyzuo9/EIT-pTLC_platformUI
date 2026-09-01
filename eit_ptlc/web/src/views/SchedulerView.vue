<script setup>
// 实验视图分发器: /experiment/:sub?/:id? -> board(缺省 运行看板) | submit(新建实验) | batch(批次详情)
// 方案编辑不在这里 —— 它是独立的"调度"栏 (/schedule, views/ScheduleView.vue)
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import SchedulerBoard from '../components/scheduler/SchedulerBoard.vue'
import ExperimentSubmitForm from '../components/scheduler/ExperimentSubmitForm.vue'
import BatchDetail from '../components/scheduler/BatchDetail.vue'
import { useSchedulerStore } from '../stores/scheduler'

const route = useRoute()
const scheduler = useSchedulerStore()

const sub = computed(() => route.params.sub || 'board')

onMounted(() => {
  scheduler.ensureRecipes()
  scheduler.ensureSnapshot()
  scheduler.startPolling()   // 视图挂载期 3s 快照轮询 (引用计数; 离开即停)
})
onBeforeUnmount(() => scheduler.stopPolling())
</script>

<template>
  <div class="scheduler-view">
    <BatchDetail v-if="sub === 'batch' && route.params.id" :batch-id="route.params.id" />
    <ExperimentSubmitForm v-else-if="sub === 'submit'" />
    <SchedulerBoard v-else />
  </div>
</template>

<style scoped>
.scheduler-view { height: 100%; overflow: hidden; }
</style>
