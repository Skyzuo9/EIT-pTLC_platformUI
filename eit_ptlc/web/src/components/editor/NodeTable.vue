<script setup>
// 节点表: 表头 + 根 body 递归渲染; 表头 Action/Input 右缘可拖拽改列宽 (layout 持久化)
import { onBeforeUnmount } from 'vue'
import NodeRow, { keyOf } from './NodeRow.vue'
import { useEditorStore } from '../../stores/editor'
import { useLayoutStore } from '../../stores/layout'

const editor = useEditorStore()
const layout = useLayoutStore()

// 列宽拖拽 (同 Splitter 范式: 记起点 + 全局监听; 拖动写 layout, 抬起落盘)
// pointer 事件系: 鼠标/触屏/笔同一路径; setPointerCapture 后 move/up 稳定送达 (拖出窗口不丢)
let dragKey = ''
let startX = 0
let startW = 0
let rafId = 0         // rAF 节流句柄 (0=无挂起)
let pendingX = null   // 最新指针 X (null=已落进 layout)

// pointermove 60-120Hz, 逐事件 setSize 会逐事件触发整表重排; rAF 节流一帧至多写一次
function onMove(e) {
  pendingX = e.clientX
  if (!rafId) rafId = requestAnimationFrame(applyMove)
}
function applyMove() {
  rafId = 0
  if (pendingX === null || !dragKey) return
  layout.setSize(dragKey, startW + (pendingX - startX))
  pendingX = null
}
function onUp() {
  // 末位值补落 (挂起的 rAF 可能还没跑, persist 前尺寸须为最终值); 兼作 unmount 兜底
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  applyMove()
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  if (dragKey) layout.persist(dragKey)
  dragKey = ''
}
function startResize(key, e) {
  dragKey = key
  startX = e.clientX
  startW = layout.sizes[key]
  pendingX = null
  try { e.target.setPointerCapture(e.pointerId) } catch (_e) { /* 捕获失败退化为纯 window 监听 */ }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  e.preventDefault()
}
// 键盘调宽: 左右箭头 ±8px, 走同一 setSize 夹紧路径, 即调即落盘
const GRIP_STEP = 8
function onGripKey(key, e) {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
  e.preventDefault()
  layout.setSize(key, layout.sizes[key] + (e.key === 'ArrowLeft' ? -GRIP_STEP : GRIP_STEP))
  layout.persist(key)
}
onBeforeUnmount(onUp)
</script>

<template>
  <div class="node-table" :style="{ '--col-act': layout.sizes.nodeColActW + 'px', '--col-in': layout.sizes.nodeColInW + 'px' }">
    <div class="node-row head">
      <div class="c-idx">#</div>
      <div class="c-act">Action<span class="col-grip" role="separator" aria-orientation="vertical" tabindex="0"
            aria-label="调整 Action 列宽" @pointerdown="startResize('nodeColActW', $event)"
            @keydown="onGripKey('nodeColActW', $event)" /></div>
      <div class="c-in">Input<span class="col-grip" role="separator" aria-orientation="vertical" tabindex="0"
            aria-label="调整 Input 列宽" @pointerdown="startResize('nodeColInW', $event)"
            @keydown="onGripKey('nodeColInW', $event)" /></div>
      <div class="c-out">Output</div>
    </div>
    <p v-if="!editor.tree.length" class="empty">空脚本 — 用上方工具栏插入节点</p>
    <NodeRow v-for="(node, i) in editor.tree" :key="keyOf(node)" :node="node" :aid="'b/' + i" :depth="0" />
  </div>
</template>

<style scoped>
/* 拖柄触屏起手不被浏览器抢去滚动/缩放 (pointer 拖拽的前提) */
.col-grip { touch-action: none; }
</style>
