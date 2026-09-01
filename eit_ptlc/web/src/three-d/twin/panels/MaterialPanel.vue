<script setup>
/** 上位机 MaterialStore.grid 的只读物料面板。 */
import { computed } from 'vue'

const props = defineProps({
  state: { type: Object, default: null },
})
const emit = defineEmits(['close'])

const snapshot = computed(() => props.state?.snapshot || null)
const stagingRows = computed(() => [
  { id: 'staging-a', label: '中转 A（刮板拍照）', kindLabel: '粉末收集器托盘' },
  { id: 'staging-b', label: '中转 B（收集平台）', kindLabel: '收集瓶托盘' },
].map((item) => ({ ...item, ...(snapshot.value?.staging?.[item.id] || {}) })))
const magazines = computed(() => Object.fromEntries(
  (snapshot.value?.magazines || []).map((item) => [item.magazine, item]),
))
// 在途载荷: 取放过程中挂在夹爪上的托盘/耗材件。正常跑完自己消失, 长时间挂着说明中途断了。
// 画面上它正跟着机械臂走(TrayBinding 换父), 这里给出它的身份与来处。
const CARRIER_LABELS = { gripper_plate96: '大夹爪', gripper_vial: '小夹爪' }
const KIND_LABELS = { collector: '粉末收集器', bottle: '收集瓶' }
const transitRows = computed(() => Object.values(snapshot.value?.transit || {}))
function transitLabel(row) {
  const what = row.payload === 'tray' ? `${row.plate} 号托盘` : `${row.plate} 号托盘 · ${row.hole} 号位`
  return `${KIND_LABELS[row.kind] || row.kind} ${what}`
}

function plateLabel(row) {
  if (row.plate !== null && row.plate !== undefined) return `${row.kindLabel} ${row.plate} 号`
  if (row.present === true) return '传感器有板 · 账本未登记板号'
  return '空位'
}

function presenceLabel(row) {
  if (row.present === null || row.present === undefined) return '无在位快照'
  if (row.ok === false) return '账实不一致'
  return row.present ? '在位' : '空'
}

function percent(item) {
  if (!item?.capacity) return 0
  return Math.max(0, Math.min(100, item.count / item.capacity * 100))
}
</script>

<template>
  <aside class="materials-panel">
    <header>
      <div>
        <h2>实机物料</h2>
        <p>来自 PTLC 上位机物料设置 · 只读</p>
      </div>
      <span class="sync" :class="state?.stale ? 'warn' : 'ok'">
        {{ state?.available ? (state.stale ? '离线冻结' : '实时同步') : '等待数据' }}
      </span>
      <button type="button" title="关闭" @click="emit('close')">×</button>
    </header>

    <div v-if="!snapshot" class="empty">
      连接“实时验收”后，将显示上位机当前托盘、耗材与板仓数量。
    </div>

    <template v-else>
      <section v-if="transitRows.length">
        <h3>在途（跟着机械臂走）</h3>
        <div v-for="row in transitRows" :key="row.carrier" class="staging-row">
          <div>
            <strong>{{ CARRIER_LABELS[row.carrier] || row.carrier }}</strong>
            <span>{{ transitLabel(row) }}</span>
          </div>
          <em class="warn">自{{ row.from_loc === 'rack' ? '货架' : '中转位' }}取起</em>
        </div>
      </section>

      <section>
        <h3>中转托盘</h3>
        <div v-for="row in stagingRows" :key="row.id" class="staging-row">
          <div>
            <strong>{{ row.label }}</strong>
            <span>{{ plateLabel(row) }}</span>
          </div>
          <em :class="row.ok === false ? 'bad' : row.present ? 'ok' : ''">
            {{ presenceLabel(row) }}
          </em>
        </div>
      </section>

      <section>
        <h3>货架托盘与耗材</h3>
        <div class="rack-grid">
          <div v-for="kind in ['collector', 'bottle']" :key="kind" class="rack-kind">
            <h4>{{ kind === 'collector' ? '粉末收集器' : '收集瓶' }}</h4>
            <div v-for="row in snapshot.rack[kind]" :key="row.plate" class="rack-row">
              <span>{{ row.plate }} 号托盘</span>
              <span>可用 {{ row.fresh }}/6</span>
              <!-- 成品与装料合并进同一格: 两者都是次要计数, 而 em 必须稳定落在最后一列。
                   分成两个 v-if 会让 em 与"成品"抢第 3 列(有成品时撞格)。
                   装料 = 桶里有粉 / 瓶里有液的格数; 逐格画条放不进 520px 悬浮面板,
                   要看每一格多少去上位机物料页。 -->
              <span class="rack-extra">
                <template v-if="row.filled">成品 {{ row.filled }}</template>
                <template v-if="row.filled && row.loaded"> · </template>
                <template v-if="row.loaded">装料 {{ row.loaded }}</template>
              </span>
              <em :class="row.ok === false ? 'bad' : row.present === false ? 'warn' : 'ok'">
                {{ row.present === false ? '不在位' : row.present === true ? '在位' : '账本' }}
              </em>
            </div>
          </div>
        </div>
      </section>

      <section>
        <h3>玻璃板仓</h3>
        <div v-for="id in ['feed', 'waste']" :key="id" class="magazine">
          <div>
            <strong>{{ id === 'feed' ? '上料仓（1Z）' : '下料仓（2Z）' }}</strong>
            <span>{{ magazines[id]?.count ?? 0 }} / {{ magazines[id]?.capacity ?? 0 }} 张</span>
          </div>
          <div class="bar"><i :style="{ width: `${percent(magazines[id])}%` }" /></div>
        </div>
      </section>

      <p v-if="snapshot.presenceMismatches" class="mismatch">
        有 {{ snapshot.presenceMismatches }} 处账本与在位反馈不一致，请以上位机物料页核对。
      </p>
    </template>
  </aside>
</template>

<style scoped>
/* 已去浮层: 本面板现在渲染在右侧信息坞的「物料总览」页里, 由坞统一负责定位与滚动。
   原先的 absolute/宽高/阴影/圆角/blur 全部撤掉 —— 四个面板各自贴右上角互相盖住,
   正是这次重构要消灭的东西。内容样式一字未动。 */
.materials-panel {
  padding: 12px;
  color: var(--text);
  font-size: 12px;
}
header { display: flex; align-items: flex-start; gap: 10px; }
h2, h3, h4, p { margin: 0; }
h2 { color: var(--text-bright); font-size: 14px; }
header p { margin-top: 3px; color: var(--text-dim); font-size: 11px; }
header button { margin-left: auto; border: 0; background: none; color: var(--text-dim); font-size: 20px; cursor: pointer; }
.sync { padding: 2px 7px; border-radius: 10px; background: var(--control); font-style: normal; white-space: nowrap; }
.ok { color: var(--ok); }
.warn { color: var(--warn); }
.bad { color: var(--err); }
section { margin-top: 14px; padding-top: 11px; border-top: 1px solid var(--border); }
h3 { margin-bottom: 7px; color: var(--text-bright); font-size: 12px; }
h4 { margin-bottom: 5px; color: var(--text-mid); font-size: 11px; }
.empty { margin-top: 14px; padding: 14px; border-radius: 8px; background: var(--control); color: var(--text-dim); line-height: 1.6; }
.staging-row, .rack-row { display: flex; align-items: center; gap: 8px; padding: 5px 7px; border-radius: 6px; background: var(--control); }
.staging-row + .staging-row, .rack-row + .rack-row { margin-top: 3px; }
.staging-row > div { display: grid; gap: 2px; }
.staging-row span { color: var(--text-dim); }
.staging-row em, .rack-row em { margin-left: auto; font-style: normal; }
.rack-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.rack-kind { min-width: 0; }
/* 四列固定: 托盘名 / 可用 / 成品·装料 / 在位. 第 3 格恒渲染(可为空)才能让 em 稳定落在
   第 4 列 —— 早先 em 硬钉 grid-column:3 而"成品"是 v-if, 有成品时两者撞格。 */
.rack-row { display: grid; grid-template-columns: 1fr auto auto auto; gap: 6px; font-variant-numeric: tabular-nums; }
.rack-row > span:nth-child(2) { color: var(--text-dim); }
.rack-row > span:nth-child(3) { color: var(--accent-bright); }
.rack-row em { grid-column: 4; }
.magazine + .magazine { margin-top: 8px; }
.magazine > div:first-child { display: flex; justify-content: space-between; }
.bar { height: 5px; margin-top: 5px; overflow: hidden; border-radius: 3px; background: var(--control); }
.bar i { display: block; height: 100%; background: var(--accent-gradient); transition: width .2s ease; }
.mismatch { margin-top: 12px; padding: 8px; border-radius: 6px; background: var(--err-soft); color: var(--err); }
@media (max-width: 720px) { .rack-grid { grid-template-columns: 1fr; } }
</style>
