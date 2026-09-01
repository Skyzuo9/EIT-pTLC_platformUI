<script setup>
// 一键审查页: 调 POST /api/materials/audit, 分四组渲染核对结果。
// 审查本身只报不改; 行内"以实为准"修复按钮 = 把后端给的 fix.payload 交给**既有写端点**
// (动作名闭集映射, 见 utils/audit.js, 不执行后端下发的任意 URL), 走危险确认,
// 成功后自动重审形成即时闭环。已包含「在位对账」(presence 组就是它)。
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useMaterialsStore } from '../stores/materials'
import { countBadges, fixAllowed, severityClass, severityLabel } from '../utils/audit.js'
import { fmtTime } from '../utils/format.js'

const router = useRouter()
const materials = useMaterialsStore()
const report = ref(null)

const auditA = useAsyncAction(
  async () => {
    const res = await api.auditMaterials()
    report.value = res
    // 审查响应自带账本快照, 顺手刷新 store (与 reconcile 按钮同款)
    if (res.grid) materials.grid = res.grid
  },
  { announce: '审查完成', errorPrefix: '审查失败' },
)

const counts = computed(() => countBadges(report.value?.counts))
const groups = computed(() => report.value?.groups || [])

// 修复动作闭集 -> 既有写端点 (键集与 utils/audit.FIX_ACTIONS 一致, 有测试互锁)
const FIX_RUNNERS = {
  magazine: (p) => api.setMaterialMagazine(p.magazine, p.count),
  bottle: (p) => api.setMaterialBottle(p.bottle, p.volume_ml),
  staging: (p) => api.setMaterialStaging(p.area, p.plate),
  rack: (p) => api.setMaterialRack(p.kind, p.plate, p.present),
  seat: (p) => api.setMaterialSeat(p.seat, p.present),
  payload_seat: (p) => api.setMaterialPayloadSeat(p.seat),
  reservation_release: (p) => api.releaseMaterialReservation(p.sample_id, p.kind),
}

const fixA = useAsyncAction(
  async (fix) => {
    await FIX_RUNNERS[fix.action](fix.payload)
    await auditA.run()      // 修完自动重审: 即时看到该行转绿
  },
  { announce: '已修复并重审', errorPrefix: '修复失败' },
)

async function runFix(row) {
  const fix = row.fix
  if (!fixAllowed(fix)) return
  const ok = await confirmAction({
    level: 'danger',
    title: fix.label || '以实为准修复',
    message: fix.confirm || `将执行修复动作 ${fix.action}, 无撤销。`,
    detail: row.label,
    confirmText: fix.label || '执行修复',
  })
  if (!ok) return
  return fixA.run(fix)
}

function gotoCat(row) {
  if (row.goto?.cat) router.push(`/materials/${row.goto.cat}`)
}
</script>

<template>
  <section class="audit">
    <div class="kind-head">
      <strong>一键审查</strong>
      <span class="muted">
        账实体检: 传感器在位 / 派生核对 / 软件双账 / 人工核对项 · 只报不改 ·
        已包含「在位对账」
      </span>
      <button class="mini primary" :disabled="auditA.busy" :aria-busy="auditA.busy"
              @click="auditA.run()">
        {{ auditA.busy ? '审查中…' : '运行审查' }}
      </button>
      <span v-if="report" class="muted">{{ fmtTime(report.checked_at) }}</span>
    </div>
    <p v-if="auditA.error" role="status" class="audit-err">{{ auditA.error }}</p>

    <div v-if="report" class="badges" role="status">
      <span v-for="b in counts" :key="b.key" class="badge" :class="`b-${b.key}`">
        {{ b.label }} {{ b.count }}
      </span>
      <span v-if="!counts.length" class="muted">无任何核对行</span>
    </div>

    <template v-for="g in groups" :key="g.key">
      <div class="grp-head">
        <strong>{{ g.label }}</strong>
        <span class="muted">{{ g.rows.length }} 项</span>
      </div>
      <!-- 组级取数失败: 整组横幅给原因, 绝不用 0 拼一张假快照 -->
      <p v-if="g.error" class="grp-err">该组未核对: {{ g.error }}</p>
      <table v-else-if="g.rows.length" class="mat-tab audit-tab">
        <thead>
          <tr><th>项目</th><th>判定</th><th>账 / 实</th><th>说明</th><th>处置</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in g.rows" :key="row.id"
              :class="{ 'row-bad': row.severity === 'mismatch' }">
            <td class="td-plate">{{ row.label }}</td>
            <td>
              <span class="sev" :class="severityClass(row.severity)">
                {{ severityLabel(row.severity) }}
              </span>
            </td>
            <td class="td-actual">
              <div v-if="row.actual">{{ row.actual }}</div>
              <div v-if="row.expected" class="muted">期望: {{ row.expected }}</div>
            </td>
            <td class="td-note">{{ row.note || '—' }}</td>
            <td class="td-ops">
              <button v-if="fixAllowed(row.fix)" class="mini fix"
                      :disabled="fixA.busy || auditA.busy"
                      :title="row.fix.confirm" @click="runFix(row)">
                {{ row.fix.label || '以实为准' }}
              </button>
              <button v-if="row.goto?.cat" class="mini ghost" @click="gotoCat(row)">
                去处置
              </button>
              <span v-if="!fixAllowed(row.fix) && !row.goto" class="muted">—</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="muted grp-empty">本组无核对行</p>
    </template>

    <p v-if="!report && !auditA.busy" class="muted audit-hint">
      点「运行审查」开始: 读 PLC 传感器与调度器快照, 与物料账本逐项比对。
      纯读操作, 不会驱动任何硬件 (板仓精确张数实测会动轴, 不在本审查内,
      审查结果会给出跳转入口)。
    </p>
  </section>
</template>

<style scoped>
.audit { margin: 8px 0 18px; }
.kind-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.audit-err { color: var(--bad); font-size: var(--fs-12); }
.audit-hint { font-size: var(--fs-12); }
.badges { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0 10px; }
.badge {
  font-size: var(--fs-12); padding: 2px 10px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--chip-bg, var(--surface-2));
}
.b-mismatch { color: var(--bad); border-color: var(--bad); font-weight: 700; }
.b-warn { color: var(--warn-strong); border-color: var(--warn-strong); }
.b-ok { color: var(--ok); }
.grp-head { display: flex; align-items: baseline; gap: 10px; margin: 12px 0 4px; }
.grp-err {
  font-size: var(--fs-12); color: var(--warn-strong);
  border-left: 3px solid var(--warn-strong); padding: 4px 10px;
  background: var(--surface-2, transparent);
}
.grp-empty { font-size: var(--fs-12); margin: 2px 0 0; }
.audit-tab { width: 100%; }
.audit-tab td { text-align: left; }
.td-actual { max-width: 340px; }
.td-note { max-width: 300px; color: var(--subtle); }
.sev { font-weight: 600; white-space: nowrap; }
.sev-mismatch { color: var(--bad); }
.sev-warn { color: var(--warn-strong); }
.sev-unverifiable { color: var(--subtle); }
.sev-ok { color: var(--ok); }
.sev-skip { color: var(--muted); }
.row-bad .td-plate { color: var(--bad); font-weight: 700; }
.mini.fix { border-color: var(--bad); color: var(--bad); font-weight: 600; }
.mini.ghost { opacity: 0.75; }
.mini.primary { font-weight: 700; }
</style>
