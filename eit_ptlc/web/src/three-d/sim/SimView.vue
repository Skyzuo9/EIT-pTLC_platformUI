<script setup>
/**
 * 功能: 仿真工作台 (/3d/sim) —— 整机行为级虚拟 PLC 的三维视图.
 *
 * 数据面: 后端仿真沙盒 (/api/sim/*, runtime/sim_stack.SimStack) —— 与真机执行链
 * 逐字同构的独立副本 (VmThread→ActionExecutor→PlcController→第二台 Mock OPC UA)。
 * 渲染面: 与实时页同一条链 (useTwinScene→TwinFeed→TwinBindings→MachineStateDriver),
 * 只是经 streamFactory 换成沙盒事件源 (/api/sim/ws/events) —— 由状态渲染, 不播片段。
 *
 * 三块面板: 会话条(创建/销毁/连接态) + 状态设定(轴/机器人/执行器) + 运行控制
 * (流程/单动作 + 调试动词 + HITL + 日志)。
 */
import { computed, reactive, ref, watch } from 'vue'

import MaterialInteraction from '../twin/panels/MaterialInteraction.vue'
import { createMaterialWriteApi } from '../twin/materialWriteApi.js'
import { useTwinScene } from '../twin/useTwinScene.js'
import SimDiagPanel from './panels/SimDiagPanel.vue'
import SimFactsPanel from './panels/SimFactsPanel.vue'
import SimRunPanel from './panels/SimRunPanel.vue'
import SimStatePanel from './panels/SimStatePanel.vue'
import { createSimEventStream } from './simEventStream.js'
import { createRunState, ingest, reconcileActiveRuns } from './simRunState.js'
import { useSimSession } from './useSimSession.js'

const containerRef = ref(null)
const session = useSimSession()
const runState = reactive(createRunState())

const scene = useTwinScene({
  containerRef,
  modelUrl: '/api/3d/assets/models/machine.official-cr5.glb',
  manifestUrl: '/api/3d/assets/models/device-manifest.official-cr5.json',
  live: true,
  plates: true,
  streamFactory: () => {
    const stream = createSimEventStream()
    // 运行面板的状态机与三维渲染吃同一条流 (次序无关, reducer 只挑自己的事件)
    stream.onEvent((event) => {
      ingest(runState, event)
    })
    return stream
  },
  // 沙盒的板位只读投影 (不是调度器快照: 沙盒不装调度器)。它带 coverage 声明,
  // 板层据此把"L1 覆盖不到的落点"与"那里没有板"分开 —— 缸里的板不会被回收掉。
  plateLedgerUrl: '/api/sim/plate_positions',
  // 板堆节距改由上面那个投影带出 (读的是同一份 feedlift_calib.json), 不再打真机端点
  feedliftCalibUrl: null,
  // 板面痕迹整条不装: 投影的 sample_id 是按位置合成的, 打过去必然 404;
  // 且 spotPose 来自真机点表 —— 在沙盒里画痕迹既无数据也无意义
  plateTraceBase: null,
})

const presets = ['iso', 'front', 'left', 'top']

// 沙盒物料写通道: 镜像契约挂 /api/sim 前缀 (端点由阶段③物料链里程碑提供;
// 未就绪时 404 按"记账失败"播报, 不静默 —— 前端先接好线, 后端落地即通)
const simWriteApi = createMaterialWriteApi({ base: '/api/sim/materials' })

/** 状态编辑的写入口: 补丁 → PUT /api/sim/state → 沙盒发事件 → 3D 跟随 (单向流) */
async function onPatch(patch) {
  try {
    await session.patchState(patch)
  } catch {
    /* 失败已在 session.message 里报出 */
  }
}

// 会话就位后拉一次状态快照; 运行终态后也刷一轮 (机构/物料可能被流程改过)
watch(session.active, (active) => {
  if (active) void session.refreshState()
})
// UniLab 可在页面打开前从外部启动沙盒 operation；WS 不重放旧事件，因此必须用会话
// 轮询里的活动 run 快照恢复运行面板，尤其不能把待人工确认的安全门画成 IDLE。
watch(session.runs, (runs) => {
  reconcileActiveRuns(runState, runs)
}, { deep: true, immediate: true })
watch(() => runState.status, (status) => {
  if (status === 'DONE' || status === 'ERROR' || status === 'KILLED') {
    void session.refreshState()
  }
})

const connectionText = computed(() => {
  if (!session.active.value) return '沙盒未创建'
  return scene.connection.value.connected ? '沙盒已连接' : '沙盒连接中…'
})
</script>

<template>
  <div class="sim-view">
    <div class="sim-view__viewport">
      <div ref="containerRef" class="sim-view__canvas" />
      <div v-if="scene.loading.value" class="sim-view__overlay">
        <p>模型加载中 {{ Math.round(scene.progress.value * 100) }}%</p>
      </div>
      <div v-else-if="scene.error.value" class="sim-view__overlay sim-view__overlay--error">
        <p>{{ scene.error.value }}</p>
      </div>
      <div class="sim-view__toolbar">
        <button v-for="name in presets" :key="name" @click="scene.applyPreset(name)">
          {{ name }}
        </button>
      </div>

      <!-- 物料点选改账 (沙盒侧): 与实时页同一组件, 只换写通道前缀 -->
      <MaterialInteraction
        v-if="session.active.value && !scene.error.value && !scene.loading.value && scene.manager.value"
        :manager="scene.manager.value"
        :materials="scene.materials.value"
        :write-api="simWriteApi"
      />
    </div>

    <aside class="sim-view__side">
      <section class="sim-panel sim-session">
        <header class="sim-panel__head">
          <h3>仿真沙盒</h3>
          <span class="sim-session__badge" :class="{ on: session.active.value }">
            {{ connectionText }}
          </span>
        </header>
        <div class="sim-verbs">
          <button v-if="!session.active.value" :disabled="session.busy.value"
                  @click="session.create()">创建沙盒</button>
          <button v-if="!session.active.value" :disabled="session.busy.value"
                  @click="session.create({ adopt: true })">创建并采纳实时</button>
          <button v-if="session.active.value" class="sim-danger" :disabled="session.busy.value"
                  @click="session.destroy()">销毁沙盒</button>
        </div>
        <p v-if="session.message.value" class="sim-session__msg">{{ session.message.value }}</p>
        <p class="sim-session__hint">
          动作经真实执行链跑在虚拟 PLC 上。FeedLift/Collect/StagingA/Pump/Develop 已按
          从 CODESYS 提取的编排说明书复刻内部工序 (光电搜索/互锁/错误码/相位计时);
          板仓张数与传感器由板堆模型推导, 而模型跟着「现场事实」里的账面走。
          Sampling/PhotoScrape 的轴序仍是近似 (按 vel_max 匀速到目标位)。
          薄层板位置只覆盖点样座与刮板台 —— 缸里有哪块板沙盒不装调度器故不知道,
          那段由动作包络维持。「创建并采纳实时」会把真机账本整表搬进沙盒。
        </p>
      </section>

      <template v-if="session.active.value">
        <!-- 现场事实在状态设定之上: 动线是"先摆好现场, 再调轴与关节, 最后跑" -->
        <SimFactsPanel
          :grid="scene.materials.value?.snapshot"
          :api="simWriteApi"
          :disabled="session.busy.value"
          @error="session.message.value = `现场事实写入失败: ${$event}`"
        />
        <SimStatePanel
          :manifest="scene.manifest.value"
          :sim-state="session.simState.value"
          :disabled="session.busy.value"
          @patch="onPatch"
          @adopt="session.adopt()"
          @reset="session.reset()"
        />
        <SimRunPanel :session="session" :run-state="runState" />
        <SimDiagPanel :active="session.active.value" />
      </template>
    </aside>
  </div>
</template>

<style scoped>
.sim-view {
  display: grid;
  grid-template-columns: 1fr 400px;
  height: 100%;
  min-height: 0;
}
.sim-view__viewport {
  position: relative;
  min-width: 0;
  min-height: 0;
}
.sim-view__canvas {
  position: absolute;
  inset: 0;
}
.sim-view__overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #9aa4b2;
  background: rgba(10, 14, 20, 0.55);
  pointer-events: none;
}
.sim-view__overlay--error {
  color: #ff7b72;
}
.sim-view__toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  display: flex;
  gap: 6px;
}
.sim-view__toolbar button {
  padding: 4px 10px;
  font-size: 12px;
  color: #cdd6e4;
  background: rgba(20, 26, 34, 0.8);
  border: 1px solid #2c3644;
  border-radius: 6px;
  cursor: pointer;
}
.sim-view__side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  overflow-y: auto;
  background: #10151c;
  border-left: 1px solid #222b36;
}
.sim-session__badge {
  padding: 2px 10px;
  font-size: 12px;
  color: #8a94a4;
  border: 1px solid #2c3644;
  border-radius: 999px;
}
.sim-session__badge.on {
  color: #7ee2a8;
  border-color: #2d5c41;
}
.sim-session__msg {
  margin: 6px 0 0;
  font-size: 12px;
  color: #e3b341;
  word-break: break-all;
}
.sim-session__hint {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: #667084;
}

/* 面板通用样式 (SimStatePanel / SimRunPanel 复用, 故不 scoped 到子组件) */
.sim-view :deep(.sim-panel) {
  padding: 10px 12px;
  color: #cdd6e4;
  background: #151b24;
  border: 1px solid #232d3a;
  border-radius: 10px;
}
.sim-view :deep(.sim-panel__head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.sim-view :deep(.sim-panel__head h3) {
  margin: 0;
  font-size: 14px;
}
.sim-view :deep(.sim-panel__actions) {
  display: flex;
  gap: 6px;
  align-items: center;
}
.sim-view :deep(.sim-panel details) {
  margin-top: 6px;
}
.sim-view :deep(.sim-panel summary) {
  font-size: 12px;
  color: #9aa4b2;
  cursor: pointer;
  user-select: none;
}
.sim-view :deep(.sim-row) {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: 12px;
}
.sim-view :deep(.sim-row input[type='range']) {
  flex: 1;
  min-width: 0;
}
.sim-view :deep(.sim-row select),
.sim-view :deep(.sim-row input:not([type='range'])) {
  padding: 3px 6px;
  color: #cdd6e4;
  background: #0e1319;
  border: 1px solid #2c3644;
  border-radius: 6px;
}
.sim-view :deep(.sim-row__label) {
  flex: 0 0 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sim-view :deep(.sim-row__num) {
  width: 72px;
}
.sim-view :deep(.sim-row__wide) {
  flex: 1;
  min-width: 0;
}
.sim-view :deep(.sim-row__unit) {
  color: #667084;
}
.sim-view :deep(.sim-group__title) {
  margin-top: 8px;
  font-size: 11px;
  color: #667084;
}
.sim-view :deep(.sim-group__grid) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
/* TCP 位姿只读格: 三列两行, 与关节滑杆视觉上分开 (那边可写, 这边不可写) */
.sim-view :deep(.sim-pose) {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 2px 8px;
  margin-top: 4px;
  font-size: 11px;
  color: #a9b3c4;
}
.sim-view :deep(.sim-pose__cell b) {
  margin-right: 4px;
  font-weight: 600;
  color: #667084;
}
.sim-view :deep(.sim-pose__cell i) {
  margin-left: 2px;
  font-style: normal;
  color: #667084;
}
.sim-view :deep(button) {
  padding: 4px 10px;
  font-size: 12px;
  color: #cdd6e4;
  cursor: pointer;
  background: #1b2330;
  border: 1px solid #2c3644;
  border-radius: 6px;
}
.sim-view :deep(button:disabled) {
  opacity: 0.45;
  cursor: not-allowed;
}
.sim-view :deep(.sim-toggle--on) {
  color: #7ee2a8;
  background: #17301f;
  border-color: #2d5c41;
}
/* 未命令过的末端: 状态未知, 与"关着"必须看得出区别 —— 把推定画成确认是本仓的老坑 */
.sim-view :deep(.sim-toggle--unknown) {
  color: #8b93a1;
  border-style: dashed;
}
.sim-view :deep(.sim-toggle__hint) {
  margin-left: 4px;
  font-size: 10px;
  color: #8b93a1;
}
.sim-view :deep(.sim-danger) {
  color: #ff7b72;
  border-color: #5c2d2d;
}
.sim-view :deep(.sim-danger-text) {
  color: #ff7b72;
}
.sim-view :deep(.sim-tabs) {
  display: flex;
  gap: 6px;
  margin: 6px 0;
}
.sim-view :deep(.sim-tabs .active) {
  color: #7ab8ff;
  border-color: #2d4a6b;
}
.sim-view :deep(.sim-verbs) {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}
.sim-view :deep(.sim-status) {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 6px 0;
  font-size: 12px;
}
.sim-view :deep(.sim-status__badge) {
  padding: 1px 8px;
  font-size: 11px;
  border: 1px solid #2c3644;
  border-radius: 999px;
}
.sim-view :deep(.sim-status__badge[data-status='RUNNING']) {
  color: #7ab8ff;
  border-color: #2d4a6b;
}
.sim-view :deep(.sim-status__badge[data-status='DONE']) {
  color: #7ee2a8;
  border-color: #2d5c41;
}
.sim-view :deep(.sim-status__badge[data-status='ERROR']),
.sim-view :deep(.sim-status__badge[data-status='KILLED']) {
  color: #ff7b72;
  border-color: #5c2d2d;
}
.sim-view :deep(.sim-status__badge[data-status='WAITING_HUMAN']),
.sim-view :deep(.sim-status__badge[data-status='PAUSED']) {
  color: #e3b341;
  border-color: #6b5c2d;
}
.sim-view :deep(.sim-hitl) {
  padding: 8px 10px;
  margin: 8px 0;
  font-size: 12px;
  background: #201c10;
  border: 1px solid #6b5c2d;
  border-radius: 8px;
}
.sim-view :deep(.sim-hitl__title) {
  font-weight: 600;
  color: #e3b341;
}
.sim-view :deep(.sim-log) {
  max-height: 180px;
  padding: 0 0 0 4px;
  margin: 6px 0 0;
  overflow-y: auto;
  font-size: 11px;
  line-height: 1.7;
  color: #8a94a4;
  list-style: none;
}
.sim-view :deep(.sim-empty) {
  font-size: 12px;
  color: #667084;
}
.sim-view :deep(.sim-rate__label) {
  font-size: 11px;
  color: #667084;
}
</style>
