<script setup>
/**
 * 功能: 沙盒诊断面板 —— 门为什么不满足 / 段号走到哪 / 传感器位由什么推导.
 *
 * 为什么独立成板: 它**没有运行时也有内容** (门此刻满不满足 = 发动作前的预判),
 * 正是"设完还没跑"那一拍最需要的东西; 塞进运行控制面板会被动词区淹掉。
 *
 * 面板内零写按钮: 想改就去"现场事实"改 —— 事实在一处设, 后果在一处看。
 * 折叠时停轮询 (诊断是低频只读, 没必要常驻拉取)。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { simApi } from '../simApi.js'
import {
  feedliftRows, gateRows, pumpLedgerBlock, sensorGroups, stationRows, syntheticBlock,
  tankRows,
} from '../simDiagRows.js'

const props = defineProps({
  active: { type: Boolean, default: false },
})

const POLL_MS = 3000

const open = ref(false)
const report = ref(null)
const error = ref('')
let timer = 0

const stations = computed(() => stationRows(report.value))
const attention = computed(() => stations.value.filter((row) => row.attention))
const sensors = computed(() => sensorGroups(report.value))
const magazines = computed(() => feedliftRows(report.value))
// 合成值台账: 沙盒给不出真值的那几处 (无对位相机/无液位相机) 用了几次
const synthetic = computed(() => syntheticBlock(report.value))
// 泵积分 vs 账本扣减: 两个数并排, 差异只呈现不回写 (账本口径与真机一致)
const pumpLedger = computed(() => pumpLedgerBlock(report.value))
const tanks = computed(() => tankRows(report.value))

/** 出错工位的门明细 (默认只展开这些 —— 全展开会把有用的一条淹掉)。 */
const gates = computed(() =>
  attention.value.map((row) => ({ station: row.station, rows: gateRows(report.value, row.station) })))

async function pull() {
  try {
    report.value = await simApi.diagnostics()
    error.value = ''
  } catch (err) {
    error.value = String(err?.message || err)
  }
}

function stop() {
  if (timer) window.clearInterval(timer)
  timer = 0
}

function start() {
  stop()
  pull()
  timer = window.setInterval(pull, POLL_MS)
}

watch(() => open.value && props.active, (on) => (on ? start() : stop()), { immediate: true })
onBeforeUnmount(stop)
</script>

<template>
  <section class="sim-panel">
    <details @toggle="open = $event.target.open">
      <summary>
        诊断
        <span v-if="attention.length" class="sim-danger-text">· {{ attention.length }} 个工位待查</span>
        <span v-if="synthetic.total" class="sim-diag-raw">· 合成值 {{ synthetic.total }} 次</span>
      </summary>

      <p v-if="error" class="sim-danger-text">{{ error }}</p>

      <div v-if="synthetic.items.length" class="sim-group">
        <div class="sim-group__title">合成值 (本次会话 {{ synthetic.total }} 次)</div>
        <div v-for="item in synthetic.items" :key="item.host" class="sim-diag-gate">
          <span class="sim-diag-unknown">⚠ {{ item.host }} × {{ item.count }}</span>
          <span class="sim-diag-because">← {{ item.reason }}</span>
        </div>
      </div>

      <div class="sim-group">
        <div class="sim-group__title">工位段号</div>
        <div v-for="row in stations" :key="row.station" class="sim-row">
          <span class="sim-row__label" :title="row.actionName">{{ row.station }}</span>
          <span class="sim-row__unit" :class="{ 'sim-danger-text': row.attention }">
            {{ row.stateText }}
            <template v-if="row.stepText"> · {{ row.stepText }}</template>
            <template v-else-if="row.step"> · 段 {{ row.step }}</template>
            <template v-if="row.errorCode"> · err {{ row.errorCode }}</template>
          </span>
        </div>
      </div>

      <div v-for="group in gates" :key="group.station" class="sim-group">
        <div class="sim-group__title">{{ group.station }} 前置门</div>
        <div v-for="item in group.rows" :key="item.key" class="sim-diag-gate">
          <span :class="{ 'sim-danger-text': item.value === false, 'sim-diag-unknown': item.unknown }">
            {{ item.mark }} {{ item.spec }}
          </span>
          <span class="sim-diag-because">← {{ item.because }}</span>
        </div>
      </div>

      <div v-for="row in stations.filter((s) => s.errorText)" :key="`t-${row.station}`"
           class="sim-group">
        <div class="sim-group__title">{{ row.station }} 错误码释义</div>
        <p class="sim-diag-because">{{ row.errorText }}</p>
      </div>

      <div v-if="tanks.length" class="sim-group">
        <div class="sim-group__title">展缸液量 (后端积分)</div>
        <div v-for="row in tanks" :key="row.tank" class="sim-row">
          <span class="sim-row__label">{{ row.tank }} 号缸</span>
          <span class="sim-row__unit">
            {{ row.volumeMl.toFixed(1) }} mL · 液面 {{ (row.level * 100).toFixed(0) }}%
            · 已泡 {{ row.soakS.toFixed(0) }}s
          </span>
        </div>
      </div>

      <div class="sim-group">
        <div class="sim-group__title">
          泵积分 vs 账本扣减
          <span v-if="pumpLedger.diverged" class="sim-danger-text">· 账实不符</span>
        </div>
        <div class="sim-row">
          <span class="sim-row__label">泵吸入 / 排出</span>
          <span class="sim-row__unit">
            {{ pumpLedger.aspiratedMl.toFixed(2) }} / {{ pumpLedger.dispensedMl.toFixed(2) }} mL
          </span>
        </div>
        <div class="sim-row">
          <span class="sim-row__label">账本扣减</span>
          <span class="sim-row__unit" :class="{ 'sim-danger-text': pumpLedger.diverged }">
            {{ pumpLedger.ledgerMl.toFixed(2) }} mL
          </span>
        </div>
        <div v-for="row in pumpLedger.items" :key="row.id" class="sim-row">
          <span class="sim-row__label">{{ row.id }}<span v-if="row.busy"> ·忙</span></span>
          <span class="sim-row__unit">
            柱塞 {{ row.plungerMl.toFixed(2) }} · 吸 {{ row.aspiratedMl.toFixed(2) }}
            · 排 {{ row.dispensedMl.toFixed(2) }} mL
          </span>
        </div>
        <p class="sim-diag-because">{{ pumpLedger.note }}</p>
      </div>

      <div class="sim-group">
        <div class="sim-group__title">板堆模型</div>
        <div v-for="row in magazines" :key="row.magazine" class="sim-row">
          <span class="sim-row__label">{{ row.magazine }}</span>
          <span class="sim-row__unit">
            {{ row.count }}/{{ row.capacity }} 张 · 轴 {{ row.z_mm }}mm ·
            触发位 {{ row.z_trigger_mm }}mm ·
            {{ row.homed ? '已回零' : '未回零' }}
          </span>
        </div>
      </div>

      <div v-for="group in sensors" :key="group.byte" class="sim-group">
        <div class="sim-group__title">
          {{ group.byte }} <span class="sim-diag-raw">{{ group.bits }}</span>
        </div>
        <div v-for="item in group.rows" :key="item.name" class="sim-diag-gate">
          <span :class="{ 'sim-danger-text': item.on === false }">
            {{ item.label }} {{ item.on === null ? '未知' : (item.on ? 'TRUE' : 'FALSE') }}
            <span class="sim-diag-raw">({{ item.address }})</span>
          </span>
          <span class="sim-diag-because">← {{ item.source }}</span>
        </div>
        <p v-if="!group.rows.length" class="sim-diag-because">
          该字节无具名位 (料库 12 路恒 0: 真机未供电, 沙盒复刻现实)
        </p>
      </div>
    </details>
  </section>
</template>

<style scoped>
.sim-diag-gate {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 3px 0;
  font-size: 12px;
  color: #cdd6e4;
  border-bottom: 1px solid #1b2330;
}
.sim-diag-because {
  font-size: 11px;
  color: #8b93a1;
}
.sim-diag-unknown {
  color: #8b93a1;
}
.sim-diag-raw {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: #6f7885;
}
</style>
