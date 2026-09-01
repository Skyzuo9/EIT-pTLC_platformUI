<script setup>
/**
 * 功能: 沙盒"现场事实"面板 —— 开跑前把物理前提摆好 (仓里几张板 / 座上有没有板 /
 *       中转放着哪块 / 瓶里还有多少).
 *
 * 为什么独立成板而不并进状态设定: 那边的契约是单一写通道 (@patch -> PUT /api/sim/state),
 * 现场事实走 /api/sim/materials/*, 是另一条通道、另一种刷新源。焊在一起会让两件事
 * 互相牵制。
 *
 * 显示源取推流投影 (material_state, 500ms 一帧) 而不是会话状态快照: 面板与三维画面
 * 永远同一帧, 于是"面板数字变了"本身就证明写入走完了整条链 —— 天然不做乐观回写。
 *
 * 危险分级: 会把账面清零/清空的操作走 confirmService 的 danger 档 (禁 window.confirm)。
 */
import { computed } from 'vue'

import { confirmAction } from '../../../composables/confirmService.js'
import {
  PLATE_STAGE_OPTIONS, bottleRows, clampCount, magazineRows, payloadSeatRows, rackRows,
  seatRows, stagingRows, transitRows,
} from '../simFactRows.js'

const props = defineProps({
  /** material_state 推流快照 (MaterialStateStore 的 snapshot) */
  grid: { type: Object, default: null },
  /** 沙盒物料写通道 (createMaterialWriteApi({base: '/api/sim/materials'})) */
  api: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['error'])

const magazines = computed(() => magazineRows(props.grid))
const seats = computed(() => seatRows(props.grid))
const staging = computed(() => stagingRows(props.grid))
const racks = computed(() => rackRows(props.grid))
const bottles = computed(() => bottleRows(props.grid))
const payloadSeats = computed(() => payloadSeatRows(props.grid))
const transit = computed(() => transitRows(props.grid))

const ready = computed(() => Boolean(props.api) && !props.disabled)

/** 统一的写入口: 失败播报而不静默 —— 沙盒物料端点没起来时要看得见。 */
async function write(run) {
  if (!ready.value) return
  try {
    await run()
  } catch (err) {
    emit('error', String(err?.message || err))
  }
}

function setMagazine(row, raw) {
  const count = clampCount(raw, row.capacity)
  if (count === row.count) return                 // 同值跳过, 不留无意义流水
  if (count === 0) {
    write(async () => {
      const ok = await confirmAction({
        level: 'danger',
        title: `把${row.label}清零?`,
        message: '账面清零会让该仓的仓底接近开关落位, 依赖它的 FeedLift 动作将报前置门超时。',
        confirmText: '清零',
      })
      if (ok) await props.api.setMagazine(row.magazine, 0)
    })
    return
  }
  write(() => props.api.setMagazine(row.magazine, count))
}

function toggleSeat(row) {
  write(() => props.api.setSeat(row.seat, !row.present))
}

function setSeatStage(row, stage) {
  if (stage === row.stage) return
  write(() => props.api.setSeatStage(row.seat, stage))
}

function setStaging(row, raw) {
  const value = raw === '' || raw === null ? null : Number(raw)
  if (value === row.plate) return
  write(() => props.api.setStaging(row.area, value))
}

function toggleRack(row) {
  write(() => props.api.setRack(row.kind, row.plate, !row.present))
}

function setBottle(row, raw) {
  const ml = Math.max(0, Number(raw) || 0)
  if (ml === row.volumeMl) return
  write(() => props.api.setBottle(row.bottle, ml))
}

function clearPayloadSeat(row) {
  write(async () => {
    const ok = await confirmAction({
      level: 'danger',
      title: `清空${row.label}?`,
      message: '件位账清空后, 收集工位的瓶位传感器会落位, PLC 的缺瓶互锁将生效。',
      confirmText: '清空',
    })
    if (ok) await props.api.clearPayloadSeat(row.seat)
  })
}

function clearTransit(row) {
  write(async () => {
    const ok = await confirmAction({
      level: 'danger',
      title: `清掉${row.label}上的在途载荷?`,
      message: '只清在途标记, 不改格账 —— 用于搬运中途取消后留下的残留。',
      confirmText: '清在途',
    })
    if (ok) await props.api.clearTransit(row.carrier)
  })
}
</script>

<template>
  <section class="sim-panel">
    <header class="sim-panel__head">
      <h3>现场事实</h3>
      <span class="sim-panel__hint">开跑前的物理前提; 写入即回灌板堆模型与传感器</span>
    </header>

    <details open>
      <summary>玻璃板仓</summary>
      <div v-for="row in magazines" :key="row.magazine" class="sim-row">
        <span class="sim-row__label" :title="row.magazine">{{ row.label }}</span>
        <input
          class="sim-row__num"
          type="number"
          min="0"
          :max="row.capacity || undefined"
          :value="row.count"
          :disabled="!ready"
          @change="setMagazine(row, $event.target.value)"
        >
        <span class="sim-row__unit">/ {{ row.capacity }} 张</span>
      </div>
      <p v-if="!magazines.length" class="sim-empty">沙盒未就绪</p>
    </details>

    <details open>
      <summary>板位 (薄层板 · {{ seats.length }} 处)</summary>
      <div v-for="row in seats" :key="row.seat" class="sim-row">
        <button
          class="sim-toggle sim-row__wide"
          :class="{ 'sim-toggle--on': row.present }"
          :disabled="!ready"
          :title="row.seat"
          @click="toggleSeat(row)"
        >
          {{ row.label }}
        </button>
        <select
          :value="row.stage"
          :disabled="!ready || !row.present"
          :title="row.present ? '这块板走到哪一步了' : '座上无板, 阶段无从谈起'"
          @change="setSeatStage(row, $event.target.value)"
        >
          <option v-for="opt in PLATE_STAGE_OPTIONS" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </div>
      <p class="sim-panel__hint">
        这些位置真机上都没有在位传感器, 只有账 —— 流程会写它 (放板/取板/工艺三大步),
        人工也可以直接改。阶段驱动三维板的四态外观。
      </p>
    </details>

    <details>
      <summary>中转区</summary>
      <div v-for="row in staging" :key="row.area" class="sim-row">
        <span class="sim-row__label">{{ row.area }} · {{ row.kind }}</span>
        <input
          class="sim-row__num"
          type="number"
          min="1"
          placeholder="空"
          :value="row.plate ?? ''"
          :disabled="!ready"
          @change="setStaging(row, $event.target.value)"
        >
        <span class="sim-row__unit">号盘</span>
      </div>
    </details>

    <details>
      <summary>货架库位 ({{ racks.length }})</summary>
      <div class="sim-group__grid">
        <button
          v-for="row in racks"
          :key="`${row.kind}-${row.plate}`"
          class="sim-toggle"
          :class="{ 'sim-toggle--on': row.present, 'sim-toggle--unknown': row.unknown }"
          :disabled="!ready"
          :title="row.unknown ? '该位无已验证传感器, 在位与否未知' : `${row.kind} ${row.plate}`"
          @click="toggleRack(row)"
        >
          {{ row.kind }}{{ row.plate }}
        </button>
      </div>
    </details>

    <details>
      <summary>溶剂瓶</summary>
      <div v-for="row in bottles" :key="row.bottle" class="sim-row">
        <span class="sim-row__label" :title="row.bottle">{{ row.label }}</span>
        <input
          class="sim-row__num"
          type="number"
          min="0"
          :value="row.volumeMl"
          :disabled="!ready"
          @change="setBottle(row, $event.target.value)"
        >
        <span class="sim-row__unit">/ {{ row.capacityMl }} mL</span>
      </div>
    </details>

    <details v-if="payloadSeats.length || transit.length">
      <summary>件位与在途</summary>
      <div v-for="row in payloadSeats" :key="row.seat" class="sim-row">
        <span class="sim-row__label">{{ row.label }}</span>
        <span class="sim-row__unit">{{ row.kind }} {{ row.plate }}-{{ row.hole }}</span>
        <button class="sim-danger" :disabled="!ready" @click="clearPayloadSeat(row)">清空</button>
      </div>
      <div v-for="row in transit" :key="row.carrier" class="sim-row">
        <span class="sim-row__label">
          {{ row.label }}<span v-if="row.stale" class="sim-danger-text"> · 陈旧</span>
        </span>
        <span class="sim-row__unit">{{ row.kind }} {{ row.plate }}</span>
        <button class="sim-danger" :disabled="!ready" @click="clearTransit(row)">清在途</button>
      </div>
    </details>
  </section>
</template>
