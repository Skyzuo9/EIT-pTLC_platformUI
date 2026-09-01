<script setup>
// 调度画布: 段 = 卡片, 依赖 = 连线。布局自动推导 (utils/dagLayout: 层=行, 并行段同行横排),
// 不持久化坐标 —— 工程师改依赖, 图自己重排, 方案文件里不长坐标噪音。
//
// 交互 (本组件只发 emit, doc 一律由壳改 —— 单一写入口便于脏标记与撤销):
//   出口圆点按下拖到别的卡片 = 加依赖 (成环即拒, announce 播报);
//   点卡片 = 选中 (右栏编辑); 点连线 = 选中边 (Delete 删);
//   Delete = 删选中的边/段。
// 指针范式照 NodeTable: pointer 事件 + setPointerCapture + rAF 节流。
import { computed, onBeforeUnmount, ref } from 'vue'
import { announce } from '../../composables/announcer.js'
import { layoutDag, wouldCycle, NODE_H, NODE_W } from '../../utils/dagLayout.js'
import { shortSegLabel } from '../../utils/scheduler.js'

const props = defineProps({
  flows: { type: Array, required: true },
  // 段脚本元数据 (label/hitl 展示用): {scriptName: {label, hitl}}
  meta: { type: Object, default: () => ({}) },
  selected: { type: String, default: '' },      // 选中段 id
  selectedEdge: { type: Object, default: null }, // 选中边 {from, to}
  readonly: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'select-edge', 'add-edge', 'remove-edge', 'remove-node'])

const layout = computed(() => layoutDag(props.flows))
const wrap = ref(null)

// ---- 拖线加边 ----
const drag = ref(null)      // {fromId, x, y} 拖动中的临时线终点 (画布坐标)
let rafId = 0
let pending = null
let hoverId = ''            // 松手时命中的目标卡片 id

function canvasPoint(e) {
  const box = wrap.value?.getBoundingClientRect()
  if (!box) return { x: 0, y: 0 }
  return { x: e.clientX - box.left + wrap.value.scrollLeft, y: e.clientY - box.top + wrap.value.scrollTop }
}

function onMove(e) {
  pending = e
  if (!rafId) rafId = requestAnimationFrame(applyMove)
}
function applyMove() {
  rafId = 0
  if (!pending || !drag.value) return
  const p = canvasPoint(pending)
  drag.value = { ...drag.value, x: p.x, y: p.y }
  // 命中测试: 指针落在哪张卡片的矩形内 (布局已知, 不查 DOM)
  hoverId = ''
  for (const n of layout.value.nodes) {
    if (p.x >= n.x && p.x <= n.x + NODE_W && p.y >= n.y && p.y <= n.y + NODE_H) {
      hoverId = n.id
      break
    }
  }
  pending = null
}
function onUp() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  applyMove()
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  document.body.style.userSelect = ''
  const from = drag.value?.fromId
  drag.value = null
  const to = hoverId
  hoverId = ''
  if (!from || !to) return
  tryAddEdge(from, to)
}
function tryAddEdge(from, to) {
  if (from === to) return
  const target = props.flows.find((f) => f.id === to)
  if (!target) return
  if ((target.depends_on || []).includes(from)) {
    announce(`${to} 已依赖 ${from}`)
    return
  }
  if (wouldCycle(props.flows, from, to)) {
    announce(`不能让 ${to} 依赖 ${from}: 会形成循环依赖`, { assertive: true })
    return
  }
  emit('add-edge', { from, to })
}
function startEdge(id, e) {
  if (props.readonly) return
  const n = layout.value.nodes.find((x) => x.id === id)
  if (!n) return
  drag.value = { fromId: id, x: n.outPort.x, y: n.outPort.y }
  hoverId = ''
  pending = null
  try { e.target.setPointerCapture(e.pointerId) } catch (_e) { /* 退化为纯 window 监听 */ }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
  document.body.style.userSelect = 'none'
  e.preventDefault()
  e.stopPropagation()
}
onBeforeUnmount(onUp)

const dragPath = computed(() => {
  const d = drag.value
  if (!d) return ''
  const n = layout.value.nodes.find((x) => x.id === d.fromId)
  if (!n) return ''
  const dy = Math.max(24, Math.abs(d.y - n.outPort.y) / 2)
  return `M ${n.outPort.x} ${n.outPort.y} C ${n.outPort.x} ${n.outPort.y + dy} ${d.x} ${d.y - dy} ${d.x} ${d.y}`
})

// ---- 键盘: Delete 删选中的边或段 ----
function onKeydown(e) {
  if (props.readonly) return
  if (e.key !== 'Delete' && e.key !== 'Backspace') return
  if (props.selectedEdge) {
    e.preventDefault()
    emit('remove-edge', props.selectedEdge)
  } else if (props.selected) {
    e.preventDefault()
    emit('remove-node', props.selected)
  }
}

// 卡片展示: 段脚本的中文短名 + 依赖数/人工门徽标
function nodeLabel(flow) {
  const m = props.meta[flow.script] || {}
  return shortSegLabel(m.label) || flow.script
}
function nodeTitle(flow) {
  const m = props.meta[flow.script] || {}
  const loc = m.from || m.to ? `\n${m.from || '?'} → ${m.to || '?'}` : ''
  return `${flow.id} · ${flow.script}${loc}\n依赖: ${(flow.depends_on || []).join(', ') || '无'}`
}
function isEdgeSelected(e) {
  return props.selectedEdge && props.selectedEdge.from === e.from && props.selectedEdge.to === e.to
}
</script>

<template>
  <div ref="wrap" class="dagc" tabindex="0" @keydown="onKeydown"
       @pointerdown.self="emit('select', ''); emit('select-edge', null)">
    <div class="dagc-stage" :style="{ width: layout.width + 'px', height: layout.height + 'px' }">
      <!-- 连线层 (在卡片下方; 线本身可点选) -->
      <svg class="dagc-edges" :width="layout.width" :height="layout.height">
        <path v-for="e in layout.edges" :key="e.key" :d="e.d"
              class="dagc-edge" :class="{ sel: isEdgeSelected(e) }"
              @pointerdown.stop="emit('select-edge', { from: e.from, to: e.to }); emit('select', '')" />
        <path v-if="dragPath" :d="dragPath" class="dagc-edge dragging" />
      </svg>

      <!-- 段卡片 -->
      <div v-for="n in layout.nodes" :key="n.id" class="dagc-node"
           :class="{ sel: n.id === selected, batch: n.flow.scope === 'batch', hot: drag && drag.fromId !== n.id }"
           :style="{ left: n.x + 'px', top: n.y + 'px', width: NODE_W + 'px', height: NODE_H + 'px' }"
           :title="nodeTitle(n.flow)"
           @pointerdown="emit('select', n.id); emit('select-edge', null)">
        <div class="dagc-node-main">
          <span class="dagc-node-label">{{ nodeLabel(n.flow) }}</span>
          <small v-if="(meta[n.flow.script] || {}).hitl === 'confirm'" title="含人工确认门">👤</small>
        </div>
        <div class="dagc-node-sub">
          <span class="num">{{ n.flow.id }}</span>
          <small v-if="n.flow.scope === 'batch'" class="dagc-tag">批次级</small>
          <button v-if="!readonly" type="button" class="dagc-del" title="删除该段 (Delete)"
                  @pointerdown.stop @click.stop="emit('remove-node', n.id)">×</button>
        </div>
        <!-- 端口: 上入下出; 下端口按下即拖线 -->
        <span class="dagc-port in" aria-hidden="true" />
        <span v-if="!readonly" class="dagc-port out" title="从这里拖到另一段 = 让那一段依赖本段"
              @pointerdown="startEdge(n.id, $event)" />
      </div>

      <p v-if="!layout.nodes.length" class="empty dagc-empty">
        方案里还没有段。用上方「＋ 添加段」从流程库选段, 再从卡片下端口拖线连出依赖。
      </p>
    </div>
  </div>
</template>

<style scoped>
.dagc { position: relative; height: 100%; overflow: auto; outline: none;
        background: var(--panel-bg, transparent); }
.dagc:focus-visible { box-shadow: inset 0 0 0 2px var(--accent, #58a); }
.dagc-stage { position: relative; }
.dagc-edges { position: absolute; inset: 0; pointer-events: none; }
.dagc-edge { fill: none; stroke: var(--muted, #888); stroke-width: 1.5;
             pointer-events: stroke; cursor: pointer; }
.dagc-edge:hover { stroke: var(--accent, #58a); stroke-width: 2.5; }
.dagc-edge.sel { stroke: var(--accent, #58a); stroke-width: 3; }
.dagc-edge.dragging { stroke: var(--accent, #58a); stroke-dasharray: 5 4; pointer-events: none; }

.dagc-node { position: absolute; box-sizing: border-box; display: flex; flex-direction: column;
             justify-content: space-between; gap: 2px; padding: 6px 8px; cursor: pointer;
             border: 1px solid var(--border, #4443); border-radius: 6px;
             background: var(--card-bg, var(--bg, #fff)); }
.dagc-node:hover { border-color: var(--accent, #58a); }
.dagc-node.sel { border-color: var(--accent, #58a); box-shadow: 0 0 0 2px var(--accent, #58a); }
.dagc-node.batch { border-style: dashed; }
.dagc-node.hot { border-color: var(--ok, #2a2); }   /* 拖线中: 提示可落点 */
.dagc-node-main { display: flex; align-items: center; gap: 4px; min-width: 0; }
.dagc-node-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }
.dagc-node-sub { display: flex; align-items: center; gap: 6px; font-size: var(--fs-11, 11px);
                 color: var(--muted, #888); }
.dagc-tag { border: 1px solid var(--border, #4443); border-radius: 6px; padding: 0 4px; }
.dagc-del { margin-left: auto; border: 0; background: none; cursor: pointer;
            color: var(--muted, #888); font-size: var(--fs-12, 12px); line-height: 1; padding: 0 2px; }
.dagc-del:hover { color: var(--danger, #d33); }

.dagc-port { position: absolute; left: 50%; width: 9px; height: 9px; margin-left: -4.5px;
             border-radius: 50%; background: var(--muted, #888); }
.dagc-port.in { top: -5px; }
.dagc-port.out { bottom: -5px; cursor: crosshair; background: var(--accent, #58a); }
.dagc-port.out:hover { transform: scale(1.35); }
.dagc-empty { position: absolute; left: 24px; top: 24px; max-width: 420px; }
</style>
