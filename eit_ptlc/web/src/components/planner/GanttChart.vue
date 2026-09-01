<script setup>
// 甘特图 (手写 CSS 绝对定位, 不引依赖): 时间轴 + 每样品一条泳道 + 可折叠资源占用泳道。
// 块可横向拖动 (只改开始时间, 抬起时 emit move 由 store 重算冲突); 点击块 emit select。
// 冲突块红边斜纹; 无历史的估计块虚线边; 块色按流程 group 哈希取 8 色环。
import { computed, onBeforeUnmount, ref } from 'vue'

import { fmtDur, niceTicks } from '../../utils/planner.js'
import { announce } from '../../composables/announcer.js'

const props = defineProps({
  placements: { type: Array, default: () => [] },
  samples: { type: Array, default: () => [] },
  conflictKeys: { type: Object, default: () => new Set() },   // Set<placement.key>
  pxPerSec: { type: Number, default: 2 },
  resourcesMeta: { type: Array, default: () => [] },          // [{id, label, mode}]
  opIndex: { type: Object, default: () => ({}) },             // 流程名 → 统计项
  durationMode: { type: String, default: 'avg' },             // 当前时间口径 avg|last
  makespanS: { type: Number, default: 0 },
  // ↓ 调度看板增量 (缺省关闭, /planner 行为逐像素不变)
  readonly: { type: Boolean, default: false },                // 禁拖动; 点击即 select
  nowS: { type: Number, default: null },                      // 当前时刻竖线 (秒; null 不画)
})
const emit = defineEmits(['select', 'move'])

const LABEL_W = 150          // 泳道名列宽 (px, 与 PlannerView 适配缩放的扣除量呼应)
const showRes = ref(true)    // 资源泳道折叠态

const spanS = computed(() => Math.max(props.makespanS, 0.001))
const ticks = computed(() => niceTicks(spanS.value, props.pxPerSec))
const contentW = computed(() => LABEL_W + spanS.value * props.pxPerSec + 120)

// 泳道内容: 样品 id → 该样品的块
const laneMap = computed(() => {
  const map = {}
  for (const p of props.placements) {
    if (!map[p.sampleId]) map[p.sampleId] = []
    map[p.sampleId].push(p)
  }
  return map
})

// 资源泳道: 只列被引用的 exclusive 资源, 顺序跟 resourcesMeta
const usedResources = computed(() => {
  const used = new Map()
  for (const p of props.placements) {
    for (const rid of p.resources || []) used.set(rid, (used.get(rid) || []).concat(p))
  }
  const metaOf = {}
  for (const m of props.resourcesMeta) metaOf[m.id] = m
  const rows = []
  for (const [rid, items] of used) {
    const meta = metaOf[rid]
    if (meta && meta.mode === 'shared') continue   // shared 不阻塞, 不画占用泳道
    rows.push({ id: rid, label: (meta && meta.label) || rid, items })
  }
  rows.sort((a, b) => a.id.localeCompare(b.id))
  return rows
})

// 8 色环: 按 group 字符串哈希取色 (同组同色)
const HUES = [210, 30, 130, 275, 0, 60, 175, 320]
function hueOf(opName) {
  const entry = props.opIndex[opName]
  const key = (entry && entry.group) || opName
  let h = 0
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0
  return HUES[h % HUES.length]
}

function labelOf(opName) {
  const entry = props.opIndex[opName]
  return (entry && entry.label) || opName
}

function resourceLabel(rid) {
  const meta = props.resourcesMeta.find((m) => m.id === rid)
  return (meta && meta.label) || rid
}

// ---- 拖动 (window 级监听, 拖中本地预览, 抬起 emit move) ----
const drag = ref(null)   // {key, startX, origStart, dx, moved}

// left 恒为基准位 (不含拖拽增量): 拖拽中的位移走 transform, 不逐帧改布局属性
function blockLeft(p) {
  return p.start_s * props.pxPerSec
}

// 被拖块的 transform 位移 (px): 钳位与 onDragUp 落盘公式同源 (左缘不越 0),
// 预览位置与原 left 版逐像素一致 —— max(0, start_s*px + dx) 的等价改写。
function dragShift(p) {
  return Math.max(-p.start_s * props.pxPerSec, drag.value.dx)
}

function onBlockDown(p, ev) {
  if (ev.button !== 0) {
    return  // 只认左键/主指针, 右键菜单等不进入拖动
  }
  if (props.readonly) {
    // 只读 (调度看板实际时间线): 不进入拖动, 出提示; 点击选中经 pointerup 直发
    tip.value = { p, x: ev.clientX + 14, y: ev.clientY + 14 }
    return
  }
  ev.preventDefault()
  // 触屏 tap 无 hover: pointerdown 即出提示; 顺手转焦点 (preventDefault 抑制了原生聚焦),
  // 使提示按"悬停或聚焦期间可见"收口 (blur 收)
  tip.value = { p, x: ev.clientX + 14, y: ev.clientY + 14 }
  if (ev.currentTarget && ev.currentTarget.focus) ev.currentTarget.focus({ preventScroll: true })
  // 捕获指针: 在窗口外松开也能收到 pointerup, 避免拖动悬挂
  if (ev.target && ev.target.setPointerCapture) {
    try { ev.target.setPointerCapture(ev.pointerId) } catch { /* 捕获失败不影响拖动 */ }
  }
  drag.value = { key: p.key, startX: ev.clientX, origStart: p.start_s, dx: 0, moved: false }
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragUp)
  window.addEventListener('pointercancel', onDragCancel)
}

// pointermove 60-120Hz 逐事件写 drag ref 会逐事件触发渲染; rAF 节流: 事件里只存最新坐标,
// 一帧至多落一次 dx (末位值在 onDragUp 里先 cancel 再同步补落, 保证 emit 用的是最终位移)
let dragRafId = 0
let dragPendingX = null

function _applyDragMove() {
  dragRafId = 0
  if (!drag.value || dragPendingX === null) return
  drag.value.dx = dragPendingX - drag.value.startX
  if (Math.abs(drag.value.dx) > 3) drag.value.moved = true
  dragPendingX = null
}

function onDragMove(ev) {
  if (!drag.value) {
    return
  }
  dragPendingX = ev.clientX
  if (!dragRafId) dragRafId = requestAnimationFrame(_applyDragMove)
}

function _teardownDrag() {
  if (dragRafId) { cancelAnimationFrame(dragRafId); dragRafId = 0 }
  dragPendingX = null
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragUp)
  window.removeEventListener('pointercancel', onDragCancel)
}

// 手势被系统取消 (触屏中断/窗口切换): 丢弃本次拖动, 不应用位移
function onDragCancel() {
  drag.value = null
  _teardownDrag()
}

function onDragUp() {
  // 末位 flush: 挂起的 rAF 可能尚未执行, 先取消再同步落最后一次 pointermove 的位移
  if (dragRafId) { cancelAnimationFrame(dragRafId); dragRafId = 0 }
  _applyDragMove()
  const d = drag.value
  drag.value = null
  _teardownDrag()
  if (!d) {
    return
  }
  const p = props.placements.find((item) => item.key === d.key)
  if (!p) {
    return
  }
  if (d.moved) {
    emit('move', { key: d.key, startS: Math.max(0, d.origStart + d.dx / props.pxPerSec) })
  } else {
    emit('select', p)
  }
}

// ---- 悬浮提示 (悬停或聚焦期间可见; 触屏 tap 经 pointerdown+焦点走同一收口) ----
const tip = ref(null)   // {p, x, y}

// @pointermove 逐块 60-120Hz 每事件新建对象写 tip → 每事件一轮 patch; rAF 节流成一帧至多一写
let tipRafId = 0
let tipPending = null

function _applyTip() {
  tipRafId = 0
  if (tipPending) { tip.value = tipPending; tipPending = null }
}

function onBlockEnterMove(p, ev) {
  tipPending = { p, x: ev.clientX + 14, y: ev.clientY + 14 }
  if (!tipRafId) tipRafId = requestAnimationFrame(_applyTip)
}

// 收提示统一走这里: 连挂起的 rAF 一并丢弃, 防"离开/失焦后下一帧又把提示写回来"
function closeTip() {
  if (tipRafId) { cancelAnimationFrame(tipRafId); tipRafId = 0 }
  tipPending = null
  tip.value = null
}

// 键盘改期: ←/→ ±1s、Shift+←/→ ±10s, 走与拖拽同一 emit('move') 落盘路径
// (store moveBlock 自带上界钳位, 此处只钳下界 0); readonly 下方向键 no-op
function onBlockKeydown(p, e) {
  if (props.readonly) return
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  const step = (e.shiftKey ? 10 : 1) * (e.key === 'ArrowRight' ? 1 : -1)
  const next = Math.max(0, p.start_s + step)
  if (next === p.start_s) return
  emit('move', { key: p.key, startS: next })
  announce(`${labelOf(p.opName)} 开始时刻 ${fmtDur(next)}`)
}

// 卸载兜底: 拖拽三重摘监听+拖拽 rAF (走 _teardownDrag) 与提示 rAF 一并清
onBeforeUnmount(() => {
  _teardownDrag()
  if (tipRafId) { cancelAnimationFrame(tipRafId); tipRafId = 0 }
  tipPending = null
})

// 键盘聚焦: 锚到块自身下缘 (无指针坐标可用); 指针路径已出的同块提示不重定位
function onBlockFocus(p, ev) {
  if (tip.value && tip.value.p === p) return
  const r = ev.target.getBoundingClientRect()
  tip.value = { p, x: r.left + 14, y: r.bottom + 8 }
}

// 离开即收; 但块仍持焦点时交给 blur 收口 (触屏 tap 松手会连发 pointerleave, 提示要留到失焦)
function onBlockLeave(ev) {
  if (ev.target === document.activeElement) return
  closeTip()
}

// 提示行: 标出当前口径用的是哪个值, 另一口径的值一并列出便于对比
function tipStats(p) {
  if (p.variant === 'actual') {
    return [p.status ? `状态 ${p.status}` : '', p.running ? '进行中 (末端随刷新推进)' : '']
      .filter(Boolean)
  }
  const entry = props.opIndex[p.opName]
  if (p.estimated || !entry || !(entry.count > 0)) {
    return ['无历史耗时, 按 60s 估计', entry && entry.baseline_ts ? '(该流程记录已被清除, 可撤销)' : '']
      .filter(Boolean)
  }
  const usingLast = props.durationMode === 'last'
  return [
    usingLast
      ? `本块用最新一次 ${fmtDur(entry.last_s)}`
      : `本块用窗口平均 ${fmtDur(entry.avg_s)}`,
    usingLast
      ? `窗口平均 ${fmtDur(entry.avg_s)} (最小 ${fmtDur(entry.min_s)} / 最大 ${fmtDur(entry.max_s)} / n=${entry.count})`
      : `最新一次 ${fmtDur(entry.last_s)} (最小 ${fmtDur(entry.min_s)} / 最大 ${fmtDur(entry.max_s)} / n=${entry.count})`,
  ]
}

// 时间网格背景: 每个刻度一条竖线
const trackBg = computed(() => {
  const step = ticks.value.stepS * props.pxPerSec
  return {
    backgroundImage: `repeating-linear-gradient(to right, var(--border) 0 1px, transparent 1px ${step}px)`,
    width: (spanS.value * props.pxPerSec + 120) + 'px',
  }
})
</script>

<template>
  <div class="gantt">
    <p v-if="!placements.length" class="gantt-empty">
      左侧添加样品与流程链后, 点「自动排程」生成时间线; 块可横向拖动微调, 冲突会红色高亮
    </p>
    <div v-else class="gantt-scroll">
      <div class="gantt-content" :style="{ width: contentW + 'px' }">
        <!-- 时间轴头行 -->
        <div class="row head-row">
          <div class="cell-label head-label"></div>
          <div class="track head-track" :style="{ width: trackBg.width }">
            <span v-for="t in ticks.ticks" :key="t.t" class="tick num"
                  :style="{ left: t.t * pxPerSec + 'px' }">{{ t.label }}</span>
          </div>
        </div>

        <!-- 样品泳道 -->
        <div v-for="s in samples" :key="s.id" class="row lane">
          <div class="cell-label" :title="s.label">{{ s.label }}</div>
          <div class="track" :style="trackBg">
            <!-- 拖拽中的位移用 transform (合成层, 不逐帧触发布局); 结束时 drag 置空即归零, 落盘走 emit move -->
            <div v-for="p in laneMap[s.id] || []" :key="p.key"
                 class="gantt-block"
                 :class="[p.variant, { conflict: conflictKeys.has(p.key), estimated: p.estimated, dragging: drag && drag.key === p.key, readonly, 'running-blk': p.running }]"
                 :style="{
                   left: blockLeft(p) + 'px',
                   width: Math.max(2, p.duration_s * pxPerSec) + 'px',
                   transform: drag && drag.key === p.key ? `translateX(${dragShift(p)}px)` : undefined,
                   '--blk-h': hueOf(p.opName),
                 }"
                 :data-key="p.key"
                 tabindex="0"
                 :aria-label="`${labelOf(p.opName)}, ${fmtDur(p.start_s)} 至 ${fmtDur(p.end_s)}, 时长 ${fmtDur(p.duration_s)}${readonly ? '' : ', 方向键调整开始时间'}`"
                 @pointerdown="onBlockDown(p, $event)"
                 @click="readonly && emit('select', p)"
                 @keydown="onBlockKeydown(p, $event)"
                 @pointermove="onBlockEnterMove(p, $event)"
                 @pointerleave="onBlockLeave($event)"
                 @focus="onBlockFocus(p, $event)"
                 @blur="closeTip()">
              <span class="blk-label">{{ p.label || labelOf(p.opName) }}</span>
            </div>
          </div>
        </div>

        <!-- 当前时刻线 (调度看板实际时间线用; nowS 为 null 不画) -->
        <div v-if="nowS != null" class="gantt-nowline"
             :style="{ left: (150 + nowS * pxPerSec) + 'px' }" aria-hidden="true"></div>

        <!-- 资源占用泳道 (仅被引用的 exclusive 资源); 折叠开关是真按钮 + aria-expanded -->
        <button type="button" class="btn-bare row res-toggle" :aria-expanded="showRes"
                @click="showRes = !showRes">
          <span class="cell-label"><span class="caret" aria-hidden="true">{{ showRes ? '▾' : '▸' }}</span>资源占用</span>
          <span class="track" :style="{ width: trackBg.width }"></span>
        </button>
        <template v-if="showRes">
          <div v-for="r in usedResources" :key="r.id" class="row res-lane">
            <div class="cell-label res-label" :title="r.id">{{ r.label }}</div>
            <div class="track" :style="trackBg">
              <div v-for="p in r.items" :key="r.id + p.key"
                   class="res-interval" :class="{ conflict: conflictKeys.has(p.key) }"
                   :style="{ left: blockLeft(p) + 'px', width: Math.max(2, p.duration_s * pxPerSec) + 'px' }"
                   :title="labelOf(p.opName)"></div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 悬浮提示 (fixed 跟随指针; 焦点/触屏 tap 锚块下缘) -->
    <div v-if="tip" class="gantt-tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
      <div class="tip-title">{{ labelOf(tip.p.opName) }} <small>({{ tip.p.opName }})</small></div>
      <div class="num">开始 {{ fmtDur(tip.p.start_s) }} → 结束 {{ fmtDur(tip.p.end_s) }}</div>
      <div class="num">本块时长 {{ fmtDur(tip.p.duration_s) }}</div>
      <div v-for="(line, i) in tipStats(tip.p)" :key="i" class="num">{{ line }}</div>
      <div v-if="tip.p.resources.length">资源: {{ tip.p.resources.map(resourceLabel).join(', ') }}</div>
      <div v-if="conflictKeys.has(tip.p.key)" class="tip-conflict">与其它块存在资源/顺序冲突</div>
    </div>
  </div>
</template>

<style scoped>
.gantt { height: 100%; position: relative; }
.gantt-empty { color: var(--subtle); padding: 16px; }
.gantt-scroll { height: 100%; overflow: auto; }
.gantt-content { min-width: 100%; position: relative; }   /* relative: 当前时刻线定位锚 */

.row { display: flex; align-items: stretch; }
.cell-label {
  flex: 0 0 150px; width: 150px; position: sticky; left: 0; z-index: 2;
  background: var(--panel); border-right: 1px solid var(--border);
  padding: 0 8px; display: flex; align-items: center; font-size: var(--fs-12);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.track { position: relative; flex: 0 0 auto; }

.head-row { position: sticky; top: 0; z-index: 3; background: var(--panel); border-bottom: 1px solid var(--border); }
.head-label { z-index: 4; height: 26px; }
.head-track { height: 26px; }
.tick { position: absolute; top: 4px; transform: translateX(-50%); font-size: var(--fs-11); color: var(--subtle); }
.tick:first-child { transform: none; }

.lane { border-bottom: 1px solid var(--border); }
.lane .track { height: 38px; }

.gantt-block {
  position: absolute; top: 5px; height: 28px; box-sizing: border-box;
  border-radius: 5px; cursor: grab; user-select: none; touch-action: none;
  background: hsla(var(--blk-h), 65%, 55%, 0.35);
  border: 1px solid hsl(var(--blk-h), 60%, 45%);
  overflow: hidden; display: flex; align-items: center; padding: 0 4px;
}
.gantt-block.dragging { cursor: grabbing; z-index: 5; opacity: 0.9; }
.gantt-block.estimated { border-style: dashed; }
.gantt-block.readonly { cursor: pointer; }
/* 实际执行块 (调度看板): 运行中的开区间块微弱脉冲; 当前时刻线贯穿全部泳道 */
.gantt-block.running-blk { animation: pulse 1.6s ease-in-out infinite; }
.gantt-nowline { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--accent); opacity: 0.7; z-index: 4; pointer-events: none; }
.gantt-block.conflict {
  border-color: var(--bad); border-width: 2px;
  background-image: repeating-linear-gradient(45deg,
    rgba(220, 38, 38, 0.25) 0 6px, transparent 6px 12px);
}
.blk-label { font-size: var(--fs-11); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; pointer-events: none; }

/* div→button 化: btn-bare 是收缩盒, 补回整行宽; .row 的 flex 布局照常命中 */
.res-toggle { cursor: pointer; user-select: none; border-bottom: 1px solid var(--border); width: 100%; }
.res-toggle .cell-label { color: var(--subtle); height: 24px; }
.res-toggle .caret { margin-right: 4px; }
.res-lane { border-bottom: 1px dashed var(--border); }
.res-lane .track { height: 20px; }
.res-label { color: var(--subtle); }
.res-interval {
  position: absolute; top: 5px; height: 10px; border-radius: 3px;
  background: var(--muted); opacity: 0.55;
}
.res-interval.conflict { background: var(--bad); opacity: 0.8; }

.gantt-tip {
  position: fixed; z-index: 1200; max-width: 340px; pointer-events: none;
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md); padding: 8px 10px; font-size: var(--fs-12);
  display: flex; flex-direction: column; gap: 2px;
}
.tip-title { font-weight: 600; }
.tip-conflict { color: var(--bad); }
</style>
