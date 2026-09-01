<script setup>
// 单件内容物装量对话框: 一次编辑整板 6 孔的 粉 mm³/已淋洗 (collector) 或 液 mL (bottle)。
// 两个量都无测量硬件 (粉按视觉轮廓估, 液按动作参数算), 试机空跑的假数据由人在此覆盖式改回。
// 「保存」只对有改动的孔逐个提交 (与 setMagazine 的同值跳过同思路);
// 「全板清零」覆盖 6 孔且无撤销, 走危险确认。
import { computed, reactive } from 'vue'
import { api } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import ModalShell from './ui/ModalShell.vue'

const props = defineProps({
  kind: { type: String, required: true },        // collector | bottle
  kindLabel: { type: String, default: '' },
  plate: { type: Number, required: true },
  // 该板 6 孔的账本行 (可能缺行); 与拓扑声明的量纲/容量
  cells: { type: Array, default: () => [] },
  spec: { type: Object, default: null },         // {label, unit, capacity}
})
const emit = defineEmits(['close', 'saved'])

const HOLES = [1, 2, 3, 4, 5, 6]
const isPowder = computed(() => props.kind === 'collector')
const column = computed(() => (isPowder.value ? 'powder_mm3' : 'liquid_ml'))

function cellOf(hole) {
  return props.cells.find((c) => c.hole === hole) || null
}

// 草稿: 打开时从账本值初始化 (对话框 v-if 挂载, 每次打开都是新实例, setup 初始化即可)
const draft = reactive(Object.fromEntries(HOLES.map((h) => {
  const c = cellOf(h)
  return [h, {
    amount: Number(c?.[column.value] ?? 0),
    eluted: !!c?.eluted,
  }]
})))

function pct(amount) {
  const cap = Number(props.spec?.capacity || 0)
  if (!(cap > 0)) return null
  return Math.round(Math.min(100, Math.max(0, (Number(amount) || 0) / cap * 100)))
}

// 有改动的孔 -> 提交载荷 (缺省字段不动: 只改动过的字段才带上)
function changedPayloads() {
  const out = []
  for (const h of HOLES) {
    const c = cellOf(h)
    const cur = { amount: Number(c?.[column.value] ?? 0), eluted: !!c?.eluted }
    const next = draft[h]
    const fields = {}
    const amount = Number(next.amount)
    if (Number.isFinite(amount) && amount >= 0 && amount !== cur.amount) {
      fields[column.value] = amount
    }
    if (isPowder.value && next.eluted !== cur.eluted) fields.eluted = next.eluted
    if (Object.keys(fields).length) out.push({ hole: h, fields })
  }
  return out
}

const saveA = useAsyncAction(
  async () => {
    const payloads = changedPayloads()
    for (const p of payloads) {
      await api.setMaterialCellAmount(props.kind, props.plate, p.hole, p.fields)
    }
    emit('saved')
    emit('close')
  },
  { announce: '已写入装量', errorPrefix: '装量写入失败' },
)

// 全板清零: 覆盖式写 0 (collector 顺带清已淋洗), 无撤销 -> 危险确认
const clearA = useAsyncAction(
  async () => {
    for (const h of HOLES) {
      const fields = { [column.value]: 0 }
      if (isPowder.value) fields.eluted = false
      await api.setMaterialCellAmount(props.kind, props.plate, h, fields)
    }
    emit('saved')
    emit('close')
  },
  { announce: '已全板清零', errorPrefix: '清零失败' },
)
// useAsyncAction 的 error 已是组装好的中文文案字符串, 两个动作共用一个落点
const saveErr = computed(() => saveA.error || clearA.error || '')

async function clearAll() {
  const ok = await confirmAction({
    level: 'danger',
    title: '全板装量清零',
    message: `将把 ${props.kindLabel || props.kind} ${props.plate} 号板 6 孔的`
      + `${props.spec?.label || '装量'}全部改写为 0${isPowder.value ? ' 并清掉已淋洗标记' : ''}, 无撤销。`,
    confirmText: '全板清零',
  })
  if (!ok) return
  return clearA.run()
}
</script>

<template>
  <ModalShell open :title="`装量盘点 · ${kindLabel || kind} ${plate} 号板`" @close="emit('close')">
    <p class="legend">
      {{ spec?.label || '装量' }}无测量硬件, 账面是估算值; 在此覆盖式改回真实值。
      保存只提交有改动的孔。
    </p>
    <table class="amt-tab">
      <thead>
        <tr>
          <th>孔</th>
          <th>{{ spec?.label || '装量' }} ({{ spec?.unit || '' }})</th>
          <th v-if="spec?.capacity">占容量</th>
          <th v-if="isPowder">已淋洗</th>
          <th>孔状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="h in HOLES" :key="h">
          <td class="num">{{ h }}</td>
          <td>
            <input class="num" type="number" min="0" :step="isPowder ? 50 : 1"
                   inputmode="decimal" v-model.number="draft[h].amount"
                   :aria-label="`孔${h} ${spec?.label || '装量'}`" />
          </td>
          <td v-if="spec?.capacity" class="num muted">
            {{ pct(draft[h].amount) === null ? '—' : pct(draft[h].amount) + '%' }}
          </td>
          <td v-if="isPowder">
            <input type="checkbox" v-model="draft[h].eluted"
                   :aria-label="`孔${h} 已淋洗`" />
          </td>
          <td class="muted">
            {{ cellOf(h)?.state === 'FRESH' ? '未用'
               : (cellOf(h)?.sample_id ? `成品 ${cellOf(h).sample_id}` : '空/已用') }}
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="saveErr" role="status" class="amt-err">{{ saveErr }}</p>
    <div class="amt-foot">
      <button class="mini" :disabled="clearA.busy || saveA.busy" @click="clearAll">全板清零</button>
      <span class="spacer" />
      <button class="mini" :disabled="saveA.busy" @click="emit('close')">取消</button>
      <button class="mini primary" :disabled="saveA.busy || clearA.busy" @click="saveA.run()">
        {{ saveA.busy ? '写入中…' : '保存' }}
      </button>
    </div>
  </ModalShell>
</template>

<style scoped>
.legend { font-size: var(--fs-11); color: var(--muted); margin: 0 0 8px; }
.amt-tab { border-collapse: collapse; font-size: var(--fs-12); width: 100%; }
.amt-tab th, .amt-tab td { border: 1px solid var(--border); padding: 4px 8px; text-align: center; }
.amt-tab th { background: var(--surface-2); color: var(--subtle); font-weight: 600; }
.amt-tab input.num { width: 90px; font-size: var(--fs-12); padding: 2px 4px; }
.amt-err { color: var(--bad); font-size: var(--fs-12); margin: 6px 0 0; }
.amt-foot { display: flex; gap: 8px; margin-top: 10px; align-items: center; }
.amt-foot .spacer { flex: 1; }
.mini.primary { font-weight: 700; }
.muted { color: var(--muted); }
</style>
