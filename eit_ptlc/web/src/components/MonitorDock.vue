<script setup>
// 底部监视器 (常驻): 左=当前运行步骤树 (实时); 右=选中设备状态 (实时)
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import StepTree from './StepTree.vue'
import Splitter from './Splitter.vue'
import { useRunsStore } from '../stores/runs'
import { useNodesStore } from '../stores/nodes'
import { useLayoutStore } from '../stores/layout'
import { useRovingTabs } from '../composables/useRovingTabs.js'

const runs = useRunsStore()
const nodes = useNodesStore()
const router = useRouter()
const layout = useLayoutStore()

const node = computed(() => nodes.selected)

// 运行页签 roving: selectedEffectiveId 是只读 computed → 可写包装走 runs.select;
// keys 随 activeRuns 动态 (unref 兼容); select 无副作用, 走 roving 直写路径
const activeRunTab = computed({
  get: () => runs.selectedEffectiveId,
  set: (id) => runs.select(id),
})
const runKeys = computed(() => runs.activeRuns.map((r) => r.run_id))
const runRoving = useRovingTabs(runKeys, activeRunTab)

// 点表头一键跳回运行中的流程编辑器 (调试坞/HITL 所在面)
function openRunning() {
  const op = runs.live.operation
  if (op) router.push(`/library/operation/${op}`)
}

function fmtValue(value) {
  if (Array.isArray(value)) return value.map((v) => (typeof v === 'number' ? v.toFixed(2) : v)).join(', ')
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

// 展缸 8 元阵列在窄面板里会摊成 "98.00, 0.00, …" (枚举被当浮点且无缸号), 于本坞无可读性;
// 它们在设备页 NodeDetail 的「展缸阵列」表里按缸号逐行展示, 故本坞跳过
const TANK_ARRAY_KEYS = ['Tank_State', 'Tank_Drain_Done']

// 设备状态的标量/数组字段 (跳过嵌套对象与展缸阵列, 保持紧凑)
const rows = computed(() => {
  if (!node.value || !node.value.data) return []
  return Object.entries(node.value.data)
    .filter(([k, v]) => (typeof v !== 'object' || Array.isArray(v)) && !TANK_ARRAY_KEYS.includes(k))
    .map(([k, v]) => ({ k, v: fmtValue(v) }))
})
</script>

<template>
  <div class="monitor" :style="{ '--mon-right-w': layout.sizes.monitorRightW + 'px' }">
    <section>
      <h4>当前运行</h4>
      <!-- 并行调度下同时多条运行: tab 条切换选中通道 (>1 条才显; 单运行观感不变) -->
      <div v-if="runs.activeRuns.length > 1" class="mon-run-tabs" role="tablist" aria-label="运行通道页签">
        <button v-for="r in runs.activeRuns" :key="r.run_id" type="button" class="mon-run-tab"
                role="tab" :id="'md-tab-' + r.run_id" aria-controls="md-panel-run"
                :tabindex="runRoving.tabindex(r.run_id)"
                :aria-selected="r.run_id === runs.selectedEffectiveId"
                :class="{ active: r.run_id === runs.selectedEffectiveId }"
                :title="r.run_id" @click="runs.select(r.run_id)" @keydown="runRoving.onKeydown">
          <span class="dot" :class="r.status" />
          <span class="mon-run-tab-label">{{ r.label || r.operation || r.run_id }}</span>
        </button>
      </div>
      <div v-if="runs.live.run_id" id="md-panel-run" role="tabpanel" :aria-labelledby="'md-tab-' + runs.selectedEffectiveId">
        <button type="button" class="btn-bare mon-head clickable" @click="openRunning" title="跳转到运行中的流程">
          <span class="mon-link">{{ runs.live.label || runs.live.operation }}</span>
          <span class="runtag" :class="runs.live.status">{{ runs.live.status }}</span>
        </button>
        <p v-if="runs.live.message" class="mon-msg" :class="runs.live.status" role="status">{{ runs.live.message }}</p>
        <StepTree :steps="runs.live.steps" />
      </div>
      <p v-else class="empty">无运行</p>
    </section>

    <section>
      <div class="mon-section-head">
        <h4>设备状态</h4>
        <select class="mon-node-select" aria-label="选择设备节点" :value="nodes.selectedId || ''" @change="nodes.select($event.target.value)">
          <option value="">— 选择设备 —</option>
          <option v-for="n in nodes.list" :key="n.id" :value="n.id">{{ n.label }}</option>
        </select>
      </div>
      <div v-if="node">
        <div class="mon-head"><span class="health-dot" :class="node.health" /> {{ node.health }}</div>
        <!-- v-memo 与 v-for 同元素: 遥测 1Hz 整表重算时值未变的行跳过 patch (k 即 :key 恒定, 行内动态输出仅 row.v) -->
        <table class="kv">
          <tbody>
            <tr v-for="row in rows" :key="row.k" v-memo="[row.v]">
              <td>{{ row.k }}</td>
              <td>{{ row.v }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">在上方选择设备查看状态</p>
    </section>
    <!-- 当前运行↔设备状态 竖向 (设备状态在右 → sign=-1) -->
    <Splitter skey="monitorRightW" dir="x" :sign="-1" class="seam-monitor-v" />
  </div>
</template>

<style scoped>
.mon-run-tabs { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px; }
.mon-run-tab {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 8px; font-size: var(--fs-12); cursor: pointer;
  border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface-2); color: var(--text-2);
}
.mon-run-tab.active { border-color: var(--accent); color: var(--text); background: var(--surface); }
.mon-run-tab-label { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mon-run-tab .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); flex: none; }
.mon-run-tab .dot.RUNNING { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
.mon-run-tab .dot.WAITING_HUMAN { background: var(--accent); }
.mon-run-tab .dot.DONE { background: var(--ok); }
.mon-run-tab .dot.ERROR, .mon-run-tab .dot.FAILED, .mon-run-tab .dot.KILLED { background: var(--bad); }
.mon-head.clickable { cursor: pointer; }
/* div→button 语义化后维持原 div 的整行占位/点击区 (按钮默认收缩到内容宽) */
button.mon-head.clickable { width: 100%; }
.mon-head.clickable:hover .mon-link { text-decoration: underline; }
.mon-msg {
  margin: 6px 0 8px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  line-height: 1.4;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.mon-msg.FAILED, .mon-msg.ERROR, .mon-msg.REJECTED, .mon-msg.TIMEOUT { border-color: var(--bad); color: var(--bad); }
.mon-section-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.mon-section-head h4 { margin: 0; }
.mon-node-select { margin-left: auto; max-width: 60%; font-size: var(--fs-12); padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; }
</style>
