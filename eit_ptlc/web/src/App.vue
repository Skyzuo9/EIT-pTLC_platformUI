<script setup>
// 应用根: 装配控制台外壳, 首屏拉取状态, 启动单事件流并把事件分发到各 store
import { onMounted } from 'vue'
import ConsoleShell from './components/ConsoleShell.vue'
import AlarmBanner from './components/AlarmBanner.vue'
import HitlModal from './components/HitlModal.vue'
import ConfirmHost from './components/ui/ConfirmHost.vue'
import LiveRegions from './components/ui/LiveRegions.vue'
import { useSystemStore } from './store'
import { useNodesStore } from './stores/nodes'
import { useRunsStore } from './stores/runs'
import { useDebugStore } from './stores/debug'
import { useAlarmStore } from './stores/alarms'
import { useSchedulerStore } from './stores/scheduler'
import { useMaterialsStore } from './stores/materials'
import { startEventStream, onEvent, onEventStreamStatus } from './composables/eventStream'

const sys = useSystemStore()
const nodes = useNodesStore()
const runs = useRunsStore()
const debug = useDebugStore()
const alarms = useAlarmStore()
const scheduler = useSchedulerStore()
const materials = useMaterialsStore()

onMounted(async () => {
  await sys.refresh()
  // 首屏种子 (节点清单含 label/kind; 历史运行); 任一失败不阻断其它
  await Promise.all([nodes.seed().catch(() => {}), runs.seedRecent().catch(() => {})])
  // 单事件流分发: telemetry -> 节点/报警; operation_*/vm_* -> 运行 + 调试器; operation_failed(机器人故障) -> 报警
  onEvent((event) => {
    nodes.ingest(event)
    runs.ingest(event)
    debug.ingest(event)
    alarms.ingest(event)
    scheduler.ingest(event)   // scheduler_update/experiment_update -> 去抖刷新快照
    materials.ingest(event)   // material_state -> 物料账本整帧替换 (含在途载荷)
  })
  debug.seedActive()   // 首屏 rehydrate: 刷新丢门找回 (seedActive 内部吞错, 不阻断)
  // 挂载补种 (多通道): 并行调度下可能同时多条 RUNNING, 逐条串行补种 (防 N 路 getRun 突发);
  // 吞错继续 —— 单条补种失败不阻断其余通道恢复
  const runningRuns = runs.recent.filter((r) => r.status === 'RUNNING').slice(0, 8)
  for (const r of runningRuns) {
    try { await runs.reseedLive(r.run_id) } catch (e) { /* 单通道失败不阻断 */ }
  }
  let wasConnected = false
  onEventStreamStatus((connected) => {
    sys.setStreamConnected(connected)
    if (connected && !wasConnected) {
      debug.seedActive()        // 断线→重连沿: 补拉断线期间可能丢的门
      runs.reseedLive()         // 断线窗口可能吞掉终态: 从权威记录整树重放收口
      runs.seedRecent().catch(() => {})   // 历史列表同理可能停留在 RUNNING
      // 物料账本同理: 断线期间的整帧都被丢了, 而推流是"变更即发 + 5s 心跳", 后端若在
      // 断线窗口内重启, 下一帧要等到有变更或心跳才来。这一拉把在途/座位/余量立刻收口。
      materials.load().catch(() => {})
    }
    wasConnected = connected
  })
  startEventStream()
})
</script>

<template>
  <!-- AlarmBanner 在文档流首行 (非 fixed): 告警出现时推压整个控制台下移,
       态势条上的急停永不被盖 (#app 为 flex column, 见 style.css) -->
  <AlarmBanner />
  <ConsoleShell />
  <HitlModal />
  <ConfirmHost />
  <LiveRegions />
</template>
