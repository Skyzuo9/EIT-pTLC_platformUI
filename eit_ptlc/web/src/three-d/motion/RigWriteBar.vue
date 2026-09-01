<script setup>
/**
 * 功能: rig_map 写回条 —— 汇总未落盘的运动参数/液体开关改动, 一键写回并触发重跑.
 *
 * 写回链: rigWriter.patchRigMap(读盘 → rigPatch 打补丁(注释保全) → writeFile, 中间件
 * 自动 .bak) → startRebuild(参数只需 manifest 三步秒级; 液体要全链 ~40-60s, 因为
 * liquidNode 是 03 生成的示意几何). 生产构建(authoring 不可用)整条隐藏.
 *
 * 走 rigWriter 而不是自己读写: rig_map 有多个写入方(标定子页、指认模式、别的会话),
 * 那里统一做"写前重读 + 第三方改动检测", 冲突时拒写并让人重试, 而不是闷头覆盖.
 */
import { computed, onMounted, ref } from 'vue'

import * as api from '../workbench/authoringApi.js'
import { patchRigMapLiquid, patchRigMapMotionParams, patchRigMapTankLidLift } from './rigPatch.js'
import { patchRigMap } from './rigWriter.js'

const props = defineProps({
  /** 授权中间件是否可用 */
  available: { type: Boolean, default: false },
  /** 未写回的参数改动 {actuators: {id: patch}, linkages: {id: patch}} */
  dirty: { type: Object, default: () => ({ actuators: {}, linkages: {} }) },
  /** 液体开关的待写值(null = 未改) */
  liquidPending: { type: Boolean, default: null },
})

const emit = defineEmits(['written', 'rebuilt'])

const busy = ref(false)
const message = ref('')
/** 重跑进度(挂载时恢复在跑任务, 照抄 RebuildPanel.track 的纪律) */
const rebuild = ref(null)

const dirtyCount = computed(
  () =>
    Object.keys(props.dirty?.actuators || {}).length +
    Object.keys(props.dirty?.linkages || {}).length +
    (props.liquidPending === null ? 0 : 1),
)

/**
 * 功能: 跟踪一次重跑直到结束.
 * @param {string[]} only 步骤过滤
 * @returns {Promise<void>}
 */
async function track(only) {
  await api.startRebuild(only)
  const final = await api.waitRebuild((status) => {
    rebuild.value = status
  })
  rebuild.value = final
  if (final.error) {
    message.value = `重跑失败: ${final.error}`
  } else {
    message.value = '重跑完成, 刷新页面加载新 manifest'
    emit('rebuilt')
  }
}

/**
 * 功能: 写回全部待落盘改动.
 * @returns {Promise<void>}
 */
async function write() {
  busy.value = true
  message.value = ''
  const liquidChanged = props.liquidPending !== null
  try {
    const result = await patchRigMap((original) => {
      let text = original
      // 展缸盖(liftMm)不在 rig_map.linkages 段里, 走 tank_lids.lift_mm 这条单独通路
      const linkages = { ...(props.dirty?.linkages || {}) }
      let lidLift = null
      for (const [id, patch] of Object.entries(linkages)) {
        if (!Object.hasOwn(patch, 'liftMm')) continue
        lidLift = patch.liftMm
        const rest = { ...patch }
        delete rest.liftMm
        if (Object.keys(rest).length) linkages[id] = rest
        else delete linkages[id]
      }
      if (lidLift !== null) text = patchRigMapTankLidLift(text, lidLift)
      const params = { actuators: props.dirty?.actuators || {}, linkages }
      const hasParams =
        Object.keys(params.actuators).length || Object.keys(params.linkages).length
      if (hasParams) text = patchRigMapMotionParams(text, params)
      if (liquidChanged) text = patchRigMapLiquid(text, props.liquidPending)
      return text
    })
    if (result.conflict === true) {
      message.value = 'rig_map 在此期间被其它会话改过, 已重新读取 —— 请再点一次写回'
      return
    }
    emit('written')
    message.value = '已写回 rig_map.yaml(自动留 .bak), 正在重跑…'
    // 参数只进 manifest; 液体要全链(03 生成液面几何)
    await track(liquidChanged ? [] : ['manifest', 'manifest-cr5', 'deploy'])
  } catch (err) {
    message.value = `写回失败: ${err.message}`
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  // 页面刷新时若有在跑的重跑任务, 恢复进度显示
  if (!props.available) return
  try {
    const status = await api.rebuildStatus()
    if (status.running) {
      rebuild.value = status
      busy.value = true
      const final = await api.waitRebuild((next) => {
        rebuild.value = next
      })
      rebuild.value = final
      busy.value = false
    }
  } catch {
    // 中间件不可用时静默(available 已兜底)
  }
})

const runningStep = computed(() => {
  const steps = rebuild.value?.steps || []
  return steps.find((step) => step.status === 'running')?.label || ''
})
</script>

<template>
  <div v-if="available" class="rw">
    <div class="rw__row">
      <span class="rw__count">
        {{ dirtyCount ? `${dirtyCount} 项未写回` : 'rig_map 无待写改动' }}
      </span>
      <button class="rw__btn" :disabled="!dirtyCount || busy" @click="write">
        {{ busy ? '处理中…' : '写回 rig_map 并重跑' }}
      </button>
    </div>
    <p v-if="runningStep" class="rw__step">正在: {{ runningStep }}</p>
    <p v-if="message" class="rw__msg">{{ message }}</p>
  </div>
  <p v-else class="rw__msg">授权中间件不可用（仅开发模式），rig 改动只在本会话预览。</p>
</template>

<style scoped>
.rw {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.rw__row {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.rw__count {
  font-size: 11px;
  color: var(--text-mid);
}

.rw__btn {
  flex: none;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--accent-ink);
  cursor: pointer;
  background: var(--accent);
  border: none;
  border-radius: 5px;
}

.rw__btn:disabled {
  opacity: 0.4;
  cursor: default;
}

.rw__step,
.rw__msg {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}
</style>
