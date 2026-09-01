<script setup>
/**
 * 功能: 物料点选的编辑卡片 (右侧固定槽, 与 StationPanel 同位互斥).
 *
 * 只承担需要输入框的操作 (数量盘点/板仓张数); 一步动作走右键菜单。
 * 内容是**活的**: 身份是值对象, 每次渲染都从当前快照现查 (写后不乐观渲染,
 * material_state 推流整帧替换时本卡片自动重算 —— 单向闭环)。
 * 数字行内提交照二维物料页形制: 回车/失焦提交, 入口先与账面值比较同值跳过
 * (拦回车后紧跟的 change 双发)。
 */
import { computed } from 'vue'

import { identityAtMenuTime } from '../scene/materialPick.js'
import { describeIdentity, kindLabel } from '../materialMenu.js'

const props = defineProps({
  /** 建索引时的静态身份 (type/loc/kind/plate/area/hole/magazine) */
  identity: { type: Object, required: true },
  /** MaterialStateStore 快照 (推流整帧替换后 computed 自动重算) */
  snapshot: { type: Object, default: null },
  /** 账本可写 (在线且非陈旧) */
  writable: { type: Boolean, default: false },
  /** 在途写请求 (禁用输入) */
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['op', 'close'])

/** 菜单时刻同款补全: cell/在途/座位/板仓行全部现查 */
const info = computed(() => identityAtMenuTime(props.identity, props.snapshot))
const title = computed(() => describeIdentity(info.value))
/** 该件的量纲列 (粉桶看 powder_mm3, 样品瓶看 liquid_ml) */
const isPowder = computed(() => info.value.kind === 'collector')
const amount = computed(() => {
  const cell = info.value.cell
  if (!cell) return 0
  return Number(isPowder.value ? cell.powder_mm3 : cell.liquid_ml) || 0
})
const lockedNote = computed(() => {
  if (info.value.transitCarrier) return '件在爪上, 禁改格账 (请先清在途)'
  if (info.value.seatedAt) return '件停在工位座上, 数量随刮取/收集动作记账'
  if (!props.writable) return '账本离线/陈旧, 暂不可写'
  return ''
})

/**
 * 功能: 数量行内提交 (同值跳过).
 * @param {string|number} raw 输入值
 * @returns {void}
 */
function submitAmount(raw) {
  const value = Number(raw)
  if (!Number.isFinite(value) || value < 0) return
  if (value === amount.value) return
  const field = isPowder.value ? 'powder_mm3' : 'liquid_ml'
  emit('op', {
    op: 'cellAmount', danger: false,
    args: { kind: info.value.kind, plate: info.value.plate, hole: info.value.hole,
            [field]: value },
  })
}

/** 功能: 已淋洗翻转 (可逆, 不确认). */
function toggleEluted(checked) {
  emit('op', {
    op: 'cellAmount', danger: false,
    args: { kind: info.value.kind, plate: info.value.plate, hole: info.value.hole,
            eluted: !!checked },
  })
}

/** 功能: 板仓张数行内提交 (同值跳过). */
function submitMagazine(raw) {
  const count = Number(raw)
  if (!Number.isFinite(count) || count < 0) return
  const next = Math.round(count)
  if (next === Number(info.value.magazineRow?.count ?? 0)) return
  emit('op', { op: 'magazine', danger: false,
               args: { magazine: info.value.magazine, count: next } })
}
</script>

<template>
  <aside class="cellp" role="dialog" aria-label="物料编辑">
    <header class="cellp__head">
      <strong>{{ title }}</strong>
      <button class="cellp__close" aria-label="关闭" @click="emit('close')">×</button>
    </header>

    <p v-if="lockedNote" class="cellp__note">{{ lockedNote }}</p>

    <!-- 板仓: 盘点张数 -->
    <div v-if="info.type === 'magazine'" class="cellp__row">
      <label>
        账面张数
        <input class="cellp__num" type="number" min="0" inputmode="numeric"
               :value="info.magazineRow?.count ?? 0" :disabled="busy || !writable"
               title="回车或失焦写入板数"
               @keyup.enter="submitMagazine($event.target.value)"
               @change="submitMagazine($event.target.value)" />
      </label>
      <span class="cellp__muted">容量 {{ info.magazineRow?.capacity ?? '—' }}</span>
    </div>

    <!-- 单件/孔: 数量与已淋洗 -->
    <template v-else-if="info.hole != null && info.plate != null">
      <div class="cellp__row">
        <label>
          {{ isPowder ? '硅胶粉 (mm³)' : '淋洗液 (mL)' }}
          <input class="cellp__num" type="number" min="0" :step="isPowder ? 50 : 1"
                 inputmode="decimal" :value="amount"
                 :disabled="busy || !writable || !!info.transitCarrier"
                 title="回车或失焦写入 (估算值由人覆盖式改回)"
                 @keyup.enter="submitAmount($event.target.value)"
                 @change="submitAmount($event.target.value)" />
        </label>
      </div>
      <div v-if="isPowder" class="cellp__row">
        <label class="cellp__check">
          <input type="checkbox" :checked="!!info.cell?.eluted"
                 :disabled="busy || !writable || !!info.transitCarrier"
                 @change="toggleEluted($event.target.checked)" />
          已淋洗 (三维粉柱据此换色)
        </label>
      </div>
      <p class="cellp__muted">
        孔状态: {{ info.cell?.state === 'FRESH' ? '未用'
                   : (info.cell?.sample_id ? `成品 ${info.cell.sample_id}` : '空/已用') }}
        · 状态翻转走右键菜单
      </p>
    </template>

    <p v-else class="cellp__muted">该目标没有可输入的数量项, 操作走右键菜单。</p>

    <p class="cellp__muted cellp__foot">
      写入经上位机既有盘点端点; 画面变化来自推流回读 (约 1 秒内), 不做乐观渲染。
    </p>
  </aside>
</template>

<style scoped>
/* 右侧固定槽位: 与 StationPanel 同位 (宿主用 v-if 互斥) */
.cellp {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 12;
  width: 300px;
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--panel);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 12px;
  box-shadow: 0 8px 28px rgb(0 0 0 / 35%);
}
.cellp__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.cellp__close {
  border: none;
  background: none;
  color: var(--text-dim);
  font-size: 16px;
  cursor: pointer;
  line-height: 1;
}
.cellp__close:hover { color: var(--text); }
.cellp__row { margin: 8px 0; display: flex; align-items: center; gap: 8px; }
.cellp__row label { display: flex; align-items: center; gap: 6px; }
.cellp__num {
  width: 96px;
  padding: 2px 6px;
  font-size: 12px;
  background: var(--bg);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
}
.cellp__check { cursor: pointer; }
.cellp__note { margin: 4px 0; color: var(--warn); }
.cellp__muted { margin: 6px 0 0; color: var(--text-dim); }
.cellp__foot { font-size: 11px; }
</style>
