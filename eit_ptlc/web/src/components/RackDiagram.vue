<script setup>
// 货架库位仿射网格示意图 (只读): 4×3 网格, 锚点高亮 + 每格偏置; 数据来自 /api/points/grids。
// 顶行=Z高, 左列=+Y (与真机一致); 顶两行=收集器板, 底两行=收集瓶板 (group-rack 语义)。
import { ref, onMounted } from 'vue'
import { api, errText } from '../api'

const props = defineProps({ highlight: { type: String, default: '' } })
const grids = ref([])
const err = ref('')
const loading = ref(true)   // 拉取在途标志: 首帧不再空白 (加载态见模板)

onMounted(async () => {
  try {
    grids.value = await api.listPointGrids()
  } catch (e) {
    err.value = errText(e)
  } finally {
    loading.value = false
  }
})

// group-rack 语义标签: 顶半=收集器板, 底半=收集瓶板; 每板 slot 1..N 行优先
function slotLabel(g, s) {
  if (g.id !== 'group-rack') return ''
  const half = Math.ceil(g.rows / 2)
  const n = s.row <= half
    ? (s.row - 1) * g.cols + s.col
    : (s.row - half - 1) * g.cols + s.col
  return `${s.row <= half ? '收集器' : '瓶'} #${n}`
}
</script>

<template>
  <div class="rack-diagram">
    <p v-if="err" class="rack-err">货架图加载失败: {{ err }}</p>
    <p v-else-if="loading" class="hint">载入库位…</p>
    <div v-for="g in grids" :key="g.id" class="rack">
      <div class="rack-head">
        <strong>货架库位图 · {{ g.id }} ({{ g.rows }}行×{{ g.cols }}列)</strong>
        <span class="legend">◆ 标定锚点 · 左=+Y · 顶=Z高 · Δ=每格偏置(mm)</span>
      </div>
      <div class="axis-x" aria-hidden="true">← 左 (+Y) &nbsp; 列 &nbsp; 右 (−Y) →</div>
      <!-- 只读示意图: role=img 整体成一张"图"暴露给读屏 (格内文字对 AT 摊平为噪音, 摘要进 aria-label) -->
      <div class="rack-body" role="img" :aria-label="`货架库位布局示意 · ${g.id} (${g.rows}行×${g.cols}列, ◆=标定锚点)`">
        <div class="axis-y">↑Z 高<br /><span>顶</span><br /><br /><span>底</span><br />↓</div>
        <div class="grid" :style="{ gridTemplateColumns: `repeat(${g.cols}, minmax(76px, 1fr))` }">
          <div
            v-for="s in g.slots"
            :key="s.name"
            class="cell"
            :class="{ anchor: s.is_anchor, active: s.name === highlight }"
            :style="{ gridRow: s.row, gridColumn: s.col }"
            :title="s.pose ? `pose: ${s.pose.join(', ')}` : ''"
          >
            <span class="cell-name">{{ s.name }}<span v-if="s.is_anchor" class="badge">◆</span></span>
            <span class="cell-sub">{{ slotLabel(g, s) }}</span>
            <span v-if="s.offset_mm > 0" class="cell-off">Δ{{ s.offset_mm }}mm</span>
            <span v-else class="cell-off anchor-off">锚点·基准</span>
          </div>
        </div>
      </div>
      <p class="rack-cap">
        顶两行=收集器板, 底两行=收集瓶板 (对应 <code>collector_rack_slot</code> / <code>bottle_rack_slot</code> 1–6)。
        重标只需教 3 个锚点 (◆)，其余库位由仿射算出并叠加各自偏置以吸收机械误差。
      </p>
    </div>
  </div>
</template>

<style scoped>
.rack-diagram { margin: 4px 0 8px; }
.rack-err { color: var(--bad-strong, #c33); font-family: var(--font-mono); font-size: var(--fs-12); }
.rack-head { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: baseline; margin-bottom: 6px; }
.rack-head strong { color: var(--subtle); }
.legend { color: var(--muted); font-size: var(--fs-11); }
.axis-x { color: var(--muted); font-size: var(--fs-11); text-align: center; margin: 2px 0 4px 34px; letter-spacing: 1px; }
.rack-body { display: flex; align-items: stretch; gap: 6px; }
.axis-y { display: flex; flex-direction: column; justify-content: space-between; color: var(--muted); font-size: 10px; text-align: center; width: 28px; padding: 4px 0; }
.axis-y span { color: var(--subtle); font-weight: 600; }
.grid { display: grid; gap: 6px; flex: 1; }
.cell {
  display: flex; flex-direction: column; gap: 2px; align-items: center; justify-content: center;
  min-height: 58px; padding: 6px 4px; border: 1px solid var(--border); border-radius: 7px;
  background: var(--surface-2); text-align: center;
}
.cell.anchor { border-color: var(--accent); border-width: 2px; background: var(--hover, var(--surface-2)); }
.cell.active { outline: 2px solid var(--accent-strong); outline-offset: 1px; box-shadow: 0 0 0 3px var(--accent-soft, rgba(80,140,255,0.25)); }
.cell-name { font-family: var(--font-mono); font-weight: 700; color: var(--text); font-size: var(--fs-13); }
.badge { color: var(--accent); margin-left: 3px; }
.cell-sub { font-size: 10px; color: var(--subtle); }
.cell-off { font-size: 10px; color: var(--muted); font-family: var(--font-mono); }
.anchor-off { color: var(--accent); }
.rack-cap { margin-top: 8px; color: var(--muted); font-size: var(--fs-11); line-height: 1.5; }
.rack-cap code { font-family: var(--font-mono); color: var(--subtle); }
</style>
