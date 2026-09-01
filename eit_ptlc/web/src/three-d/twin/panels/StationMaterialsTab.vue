<script setup>
/**
 * 功能: 工位「物料」页 —— 该工位管着的物料, 改了先在三维里预览, 保存才写账本.
 *
 * 两条纪律:
 *   ① **帐是一等公民。** 光电只报告读数, 从不改账。帐实不一时横幅明说"账本是准的那一方",
 *      请人去现场核对后用下面的编辑改账 —— 而不是暗示"传感器说没有那就是没有"。
 *      未核实极性的点位(那 12 个货架位实测就没接上)只显读数, 不下判定。
 *   ② **预览不是实况。** 有草稿时整页顶部常驻横幅 + 画布顶边琥珀条(宿主画), 保存成功后
 *      草稿立刻丢弃, 画面回落到推流账本 —— 仓内"不做乐观渲染"那条因此字面完好。
 */
import { computed, nextTick, watch } from 'vue'

import { KIND_LABEL, materialSectionsFor, presenceLabel, stationOfLocation } from '../materialStations.js'

const props = defineProps({
  /** manifest 内容 */
  manifest: { type: Object, required: true },
  /** 工位定义 */
  station: { type: Object, default: null },
  /** 归一化后的物料快照(可能已叠加草稿) */
  snapshot: { type: Object, default: null },
  /** 账本是否可用/陈旧 */
  materials: { type: Object, default: () => ({}) },
  /** 草稿条目描述 [{key, text, visible3d}] */
  draftRows: { type: Array, default: () => [] },
  /** 保存在途 */
  saving: { type: Boolean, default: false },
  /** 保存/取消的结果提示 */
  message: { type: String, default: '' },
  /** 宿主持有的选中孔 {kind, plate, hole}|null (三维左键与本页格网同源) */
  selectedCell: { type: Object, default: null },
})

const emit = defineEmits(['edit', 'drop-entry', 'save', 'cancel', 'select-cell'])

const sections = computed(() =>
  materialSectionsFor(props.manifest, props.station?.id, props.snapshot))

/** 账本不可用/陈旧时整页只读 —— 与右键菜单同一判据 */
const canEdit = computed(() =>
  Boolean(props.materials?.available) && !props.materials?.stale)

/** 本工位相关的帐实不符行 (只列已核实且判定为不符的) */
const mismatches = computed(() =>
  (props.snapshot?.presence || []).filter(
    (row) => row.ok === false
      && stationOfLocation(props.manifest, row.location_id) === props.station?.id,
  ))

/**
 * 功能: 孔位状态的中文 (不在位 / 新的 / 装过粉的 / 淋洗过的 / 已用).
 *
 * 它不是一个枚举列, 而是 state + powder_mm3 + eluted 三者的组合 —— 这一点在
 * config/material_topology.yaml 与后端都是如此, 前端跟着组合而不是另造一个字段。
 * @param {object} cell 孔位行
 * @returns {string} 中文态
 */
function cellStateText(cell) {
  if (cell.state === 'ABSENT') return '不在位'
  if (cell.kind === 'collector') {
    if (cell.eluted) return '淋洗过的'
    if (cell.powder_mm3 > 0) return '装过粉的'
    return cell.state === 'FRESH' ? '新的' : '已用'
  }
  if (cell.liquid_ml > 0) return `有液 ${cell.liquid_ml.toFixed(1)} mL`
  return cell.state === 'FRESH' ? '新的' : '已用'
}

/** 孔位色调: 新的=正常, 有内容物=在用, 已用/不在位=淡 */
function cellTone(cell) {
  if (cell.state === 'ABSENT') return 'muted'
  if (cell.eluted) return 'warn'
  if ((cell.kind === 'collector' ? cell.powder_mm3 : cell.liquid_ml) > 0) return 'busy'
  return cell.state === 'FRESH' ? 'ok' : 'muted'
}

/**
 * 单孔状态下拉的选项 (按耗材种类给不同措辞: 粉桶的三态是用户定案,
 * 倒扣/不画分别对应三维表现, 写在选项里让人改之前就知道会看到什么)
 */
const STATE_OPTIONS = {
  collector: [
    { value: 'FRESH', label: '新的 (直立)' },
    { value: 'USED', label: '已用 (倒扣在位)' },
    { value: 'ABSENT', label: '不在位 (不显示)' },
  ],
  bottle: [
    { value: 'FRESH', label: '新的' },
    { value: 'USED', label: '已用' },
    { value: 'ABSENT', label: '不在位' },
  ],
}

/** 功能: 孔位格子的 DOM id (三维选中后 scrollIntoView 的锚点). */
function cellDomId(cell) {
  return `smt-cell-${cell.kind}-${cell.plate}-${cell.hole}`
}

/** 功能: 该孔是否是当前选中孔. */
function isSelected(cell) {
  const sel = props.selectedCell
  return Boolean(sel && sel.kind === cell.kind
    && Number(sel.plate) === Number(cell.plate) && Number(sel.hole) === Number(cell.hole))
}

/** 功能: 选中孔若属于该板, 返回其账本行(单孔编辑区渲染判据). */
function selectedOf(plate) {
  const sel = props.selectedCell
  if (!sel) return null
  return (plate.cells || []).find((cell) => isSelected(cell)) || null
}

/** 功能: 单孔状态下拉改动 → mark 草稿. */
function onStateChange(cell, event) {
  emit('edit', 'mark',
    { kind: cell.kind, plate: cell.plate, hole: cell.hole, state: event.target.value })
}

/** 功能: 板级账本下拉(有板/无板) → setRack 草稿. */
function onPresenceChange(section, plate, event) {
  emit('edit', 'setRack',
    { kind: section.kind, plate: plate.plate, present: event.target.value === 'yes' })
}

/** 功能: 整板操作下拉 → 整板 mark 草稿; 触发后复位回占位项. */
function onPlateOp(kind, plate, event) {
  const state = event.target.value
  event.target.value = ''
  if (!state) return
  emit('edit', 'mark', { kind, plate, state })
}

// 三维左键选中后把对应格子滚进视野(格网可能在长列表深处)
watch(() => props.selectedCell, (cell) => {
  if (!cell) return
  void nextTick(() => {
    document.getElementById(`smt-cell-${cell.kind}-${cell.plate}-${cell.hole}`)
      ?.scrollIntoView({ block: 'nearest' })
  })
})
</script>

<template>
  <div v-if="station" class="smt">
    <!-- 草稿横幅: 有草稿时常驻置顶 -->
    <div v-if="draftRows.length" class="dock-section">
      <p class="dock-banner dock-banner--warn">
        <span class="dock-banner__title">预览中 · 尚未写入账本（{{ draftRows.length }} 项改动）</span>
        <span>三维当前显示的是你的草稿，不是设备实况。点「保存」才写进账本。</span>
      </p>
      <ul class="smt__draft">
        <li v-for="row in draftRows" :key="row.key">
          <span class="smt__draft-text">{{ row.text }}</span>
          <span v-if="!row.visible3d" class="smt__draft-note" title="这条只改账面数字, 三维里看不出变化">
            仅账面
          </span>
          <button type="button" class="smt__draft-x" title="撤掉这一条"
                  @click="emit('drop-entry', row.key)">×</button>
        </li>
      </ul>
      <div class="smt__draft-ops">
        <button type="button" class="dock-btn dock-btn--primary"
                :disabled="saving" @click="emit('save')">
          {{ saving ? '保存中…' : '保存生效' }}
        </button>
        <button type="button" class="dock-btn" :disabled="saving" @click="emit('cancel')">
          取消并恢复
        </button>
      </div>
    </div>

    <!-- 帐实不一: 账本是准的那一方 -->
    <div v-if="mismatches.length" class="dock-section">
      <p class="dock-banner dock-banner--bad">
        <span class="dock-banner__title">帐实不一致（{{ mismatches.length }} 处）</span>
        <span v-for="row in mismatches" :key="row.location_id">
          {{ row.label }}：账本记「{{ row.expected ? '有' : '无' }}」，光电读到「{{ row.present ? '有' : '无' }}」。
        </span>
        <span>
          <b>账本是准的那一方</b> —— 传感器只报告读数，从不改账。请到现场核对后用下面的编辑改账；
          若确认账本对而传感器错，忽略本提示并报修该点位。
        </span>
      </p>
    </div>

    <p v-if="!canEdit" class="dock-section dock-banner dock-banner--info">
      物料账本{{ materials?.available ? '已冻结（实时流断开，显示的是最后一帧）' : '未连接' }}，暂不可改。
    </p>

    <!-- 分段 -->
    <section v-for="section in sections" :key="section.key" class="dock-section">
      <h3 class="dock-h3">{{ section.title }}</h3>

      <!-- 货架库位: 点选式编辑器 —— 孔位格网只负责选中(与三维左键同源),
           状态改动走单孔编辑区的下拉; 板级与整板操作也收进下拉 -->
      <template v-if="section.type === 'rack'">
        <div v-for="plate in section.plates" :key="plate.plate" class="smt__plate">
          <div class="smt__plate-head">
            <span class="smt__plate-name">{{ KIND_LABEL[section.kind] }}托盘 {{ plate.plate }}</span>
            <span class="smt__presence" :class="presenceLabel(plate.presence).tone">
              {{ presenceLabel(plate.presence).text }}
            </span>
            <label class="smt__ledger">
              账本
              <select
                class="smt__select" :disabled="!canEdit"
                :value="plate.expected === false ? 'no' : 'yes'"
                @change="onPresenceChange(section, plate, $event)"
              >
                <option value="yes">有板</option>
                <option value="no">无板</option>
              </select>
            </label>
          </div>
          <div class="smt__holes">
            <button
              v-for="cell in plate.cells"
              :id="cellDomId(cell)"
              :key="cell.hole"
              type="button"
              class="smt__hole"
              :class="[`is-${cellTone(cell)}`, { 'is-selected': isSelected(cell) }]"
              :title="`第 ${cell.hole} 孔 · ${cellStateText(cell)}${cell.sample_id ? ` · 样品 ${cell.sample_id}` : ''} —— 点击选中, 三维里同步描边`"
              @click="emit('select-cell', { kind: cell.kind, plate: cell.plate, hole: cell.hole })"
            >
              <span class="smt__hole-no">{{ cell.hole }}</span>
              <span class="smt__hole-state">{{ cellStateText(cell) }}</span>
            </button>
          </div>
          <!-- 单孔编辑区: 选中该板的孔(点格网或点三维)才出现 -->
          <div v-if="selectedOf(plate)" class="smt__cell-editor">
            <div class="smt__line">
              <span class="smt__line-name">第 {{ selectedOf(plate).hole }} 孔</span>
              <select
                class="smt__select" :disabled="!canEdit"
                :value="selectedOf(plate).state"
                @change="onStateChange(selectedOf(plate), $event)"
              >
                <option v-for="opt in STATE_OPTIONS[section.kind]" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <p class="smt__cell-info">
              <template v-if="section.kind === 'collector'">
                粉 {{ (selectedOf(plate).powder_mm3 || 0).toFixed(1) }} mm³<template
                  v-if="selectedOf(plate).eluted"> · 已淋洗</template>
              </template>
              <template v-else>液 {{ (selectedOf(plate).liquid_ml || 0).toFixed(1) }} mL</template>
              <template v-if="selectedOf(plate).sample_id">
                · 样品 {{ selectedOf(plate).sample_id }}（实验关联件）
              </template>
            </p>
            <p class="smt__note">粉/液量与淋洗标记的修改走三维右键该件 →「编辑数量…」。</p>
          </div>
          <div class="smt__plate-ops">
            <select
              class="smt__select" :disabled="!canEdit" value=""
              @change="onPlateOp(section.kind, plate.plate, $event)"
            >
              <option value="" disabled selected>整板操作…</option>
              <option value="FRESH">全部标为新的</option>
              <option value="USED">全部标为已用</option>
              <option value="ABSENT">全部清空 (件已拿走)</option>
            </select>
          </div>
        </div>
      </template>

      <!-- 只读光电 -->
      <template v-else-if="section.type === 'sensor'">
        <div v-for="row in section.rows" :key="row.id" class="dock-field">
          <dt>{{ row.presence.label || row.id }}</dt>
          <dd :class="presenceLabel(row.presence).tone">{{ presenceLabel(row.presence).text }}</dd>
        </div>
        <p class="smt__note">上样料架按设计不设软件账，此处只报读数。</p>
      </template>

      <!-- 中转区托盘 -->
      <template v-else-if="section.type === 'staging'">
        <div v-for="row in section.rows" :key="row.area" class="smt__line">
          <span class="smt__line-name">{{ row.label }}</span>
          <span class="smt__presence" :class="presenceLabel(row.presence).tone">
            {{ presenceLabel(row.presence).text }}
          </span>
          <span class="smt__line-value">{{ row.plate === null ? '空' : `${row.plate} 号板` }}</span>
          <button type="button" class="dock-btn" :disabled="!canEdit || row.plate === null"
                  title="把该中转位的账本记录置空"
                  @click="emit('edit', 'setStaging', { area: row.area, plate: null })">置空</button>
        </div>
      </template>

      <!-- 玻璃板仓 -->
      <template v-else-if="section.type === 'magazine'">
        <div v-for="row in section.rows" :key="row.magazine" class="dock-row">
          <div class="dock-row__head">
            <span>{{ row.label }}</span>
            <span class="dock-row__value">{{ row.count }} / {{ row.capacity }} 张</span>
          </div>
          <div class="dock-bar">
            <div class="dock-bar__fill"
                 :style="{ width: `${row.capacity ? (row.count / row.capacity) * 100 : 0}%` }" />
          </div>
          <div class="smt__stepper">
            <button type="button" class="dock-btn" :disabled="!canEdit || row.count <= 0"
                    @click="emit('edit', 'setMagazine', { magazine: row.magazine, count: row.count - 1 })">−1</button>
            <button type="button" class="dock-btn" :disabled="!canEdit || row.count >= row.capacity"
                    @click="emit('edit', 'setMagazine', { magazine: row.magazine, count: row.count + 1 })">+1</button>
            <button type="button" class="dock-btn" :disabled="!canEdit"
                    @click="emit('edit', 'setMagazine', { magazine: row.magazine, count: 0 })">清零</button>
            <button type="button" class="dock-btn" :disabled="!canEdit"
                    @click="emit('edit', 'setMagazine', { magazine: row.magazine, count: row.capacity })">装满</button>
          </div>
        </div>
      </template>

      <!-- 溶剂瓶 -->
      <template v-else-if="section.type === 'bottle'">
        <div v-for="row in section.rows" :key="row.bottle" class="dock-row">
          <div class="dock-row__head">
            <span>{{ row.label || row.bottle }}</span>
            <span class="dock-row__value">{{ Number(row.volume_ml).toFixed(0) }} / {{ Number(row.capacity_ml).toFixed(0) }} mL</span>
          </div>
          <div class="dock-bar">
            <div class="dock-bar__fill"
                 :style="{ width: `${row.capacity_ml ? (row.volume_ml / row.capacity_ml) * 100 : 0}%` }" />
          </div>
          <div class="smt__stepper">
            <button type="button" class="dock-btn" :disabled="!canEdit"
                    @click="emit('edit', 'setBottle', { bottle: row.bottle, volumeMl: row.capacity_ml })">加满</button>
            <button type="button" class="dock-btn" :disabled="!canEdit"
                    @click="emit('edit', 'setBottle', { bottle: row.bottle, volumeMl: 0 })">清空</button>
          </div>
        </div>
      </template>

      <!-- 工位夹具上的件(只读; 清空走右键菜单的 danger 路径) -->
      <template v-else-if="section.type === 'payloadSeat'">
        <div v-for="row in section.rows" :key="row.seat" class="smt__line">
          <span class="smt__line-name">{{ row.label || row.seat }}</span>
          <span class="smt__line-value">
            {{ row.plate === null ? '—' : `${KIND_LABEL[row.kind] || row.kind} ${row.plate}-${row.hole}` }}
          </span>
          <span v-if="row.stale" class="dock-tag">上个进程留下</span>
        </div>
        <p class="smt__note">件位记录只读；要清掉请在三维里右键该件（那条路径带危险确认）。</p>
      </template>

      <!-- 薄层板停放位 -->
      <template v-else-if="section.type === 'seat'">
        <div v-for="row in section.rows" :key="row.seat" class="smt__line">
          <span class="smt__line-name">{{ row.label || row.seat }}</span>
          <span class="smt__line-value">{{ row.present ? '有板' : '无板' }}</span>
          <button type="button" class="dock-btn" :disabled="!canEdit"
                  @click="emit('edit', 'setSeat', { seat: row.seat, present: !row.present })">
            改为{{ row.present ? '无板' : '有板' }}
          </button>
        </div>
      </template>
    </section>

    <p v-if="!sections.length" class="dock-empty">
      {{ snapshot ? '该工位没有管着任何物料。' : '物料账本未连接。' }}
    </p>
    <p v-if="message" class="smt__msg">{{ message }}</p>
  </div>
</template>

<style scoped>
.smt {
  display: flex;
  flex-direction: column;
}

.smt__draft {
  display: grid;
  gap: 3px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.smt__draft li {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
}

.smt__draft-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smt__draft-note {
  flex: none;
  padding: 0 5px;
  font-size: 10px;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 7px;
}

.smt__draft-x {
  flex: none;
  padding: 0 4px;
  font-size: 13px;
  line-height: 1;
  color: var(--text-dim);
  cursor: pointer;
  background: none;
  border: none;
}

.smt__draft-x:hover {
  color: var(--err-bright);
}

.smt__draft-ops {
  display: flex;
  gap: 6px;
}

.smt__plate {
  display: grid;
  gap: 4px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
}

.smt__plate-head,
.smt__line {
  display: flex;
  gap: 6px;
  align-items: center;
}

.smt__plate-name,
.smt__line-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smt__line-value {
  flex: none;
  color: var(--accent-bright);
  font-variant-numeric: tabular-nums;
}

.smt__presence {
  flex: none;
  font-size: 10px;
}

.smt__presence.ok { color: var(--ok); }
.smt__presence.warn { color: var(--warn); }
.smt__presence.bad { color: var(--err-bright); }
.smt__presence.muted { color: var(--text-dim); }

.smt__ledger {
  display: flex;
  flex: none;
  gap: 4px;
  align-items: center;
  font-size: 10px;
  color: var(--text-dim);
}

.smt__select {
  padding: 2px 4px;
  font-size: 11px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.smt__select:hover:not(:disabled) {
  border-color: var(--accent-border);
}

.smt__select:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.smt__cell-editor {
  display: grid;
  gap: 3px;
  padding: 5px 7px;
  background: var(--control);
  border: 1px solid var(--accent-border);
  border-radius: 6px;
}

.smt__cell-info {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--accent-bright);
}

/* 6 个孔一排, 与实物 2×3 排布无关 —— 面板窄, 一排更好扫 */
.smt__holes {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 3px;
}

.smt__hole {
  display: grid;
  gap: 1px;
  padding: 3px 1px;
  font-size: 9px;
  line-height: 1.25;
  color: var(--text-dim);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 4px;
}

.smt__hole:hover:not(:disabled) {
  border-color: var(--accent-border);
}

.smt__hole:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.smt__hole.is-ok { color: var(--ok); border-color: color-mix(in srgb, var(--ok, #39d98a) 40%, transparent); }
.smt__hole.is-busy { color: var(--accent-bright); border-color: var(--accent-border); }
.smt__hole.is-warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn, #f4b740) 40%, transparent); }
.smt__hole.is-muted { opacity: 0.6; }

/* 选中孔(与三维描边同源): 边框加亮 + 底色, 压过状态色 */
.smt__hole.is-selected {
  background: var(--accent-soft);
  border-color: var(--accent-bright);
  box-shadow: 0 0 0 1px var(--accent-bright);
  opacity: 1;
}

.smt__hole-no {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.smt__hole-state {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smt__plate-ops,
.smt__stepper {
  display: flex;
  gap: 4px;
}

.smt__note {
  margin: 4px 0 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}

.smt__msg {
  margin: 0;
  padding: 6px 12px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}
</style>
