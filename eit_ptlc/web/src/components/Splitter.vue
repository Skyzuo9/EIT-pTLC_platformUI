<script setup>
// 复用拖拽分隔条: 落在两栏之间的现有间隙内, 拖动改写 layout store 中对应大栏尺寸
// 用法: <Splitter skey="shellDockW" dir="x" :sign="1" class="seam-xxx" />
//   skey 指向 layout.sizes 的键; dir=拖拽轴 (x 改宽 / y 改高);
//   sign=方向 (px 栏在左/上 → +1 向右/下拖增大; 在右/下 → -1)
//   class 由调用方给出, 负责把手柄定位到目标间隙 (grid cell + 负 margin)
import { onBeforeUnmount } from 'vue'
import { useLayoutStore } from '../stores/layout'

const props = defineProps({
  skey: { type: String, required: true },
  dir: { type: String, default: 'x' },   // 'x' 竖向分隔(改宽) | 'y' 横向分隔(改高)
  sign: { type: Number, default: 1 },    // +1 / -1, 见上
})

const layout = useLayoutStore()
let startPos = 0   // 按下时的指针坐标 (clientX/Y)
let startSize = 0  // 按下时的栏尺寸 (px)
let rafId = 0          // rAF 节流句柄 (0=无挂起)
let pendingPos = null  // 最新指针位置 (null=已落进 layout)

// 拖拽中: pointermove 60-120Hz, 逐事件 setSize 会逐事件触发整片 grid 重排;
// rAF 节流: 事件里只存最新坐标, 一帧至多写一次 layout (末位值在 onUp 里补落)
function onMove(e) {
  pendingPos = props.dir === 'x' ? e.clientX : e.clientY
  if (!rafId) rafId = requestAnimationFrame(applyMove)
}

// 按 sign 把指针位移折算为尺寸增量 (逻辑与原 mousemove 等价, pointer 化后触屏/笔可用)
function applyMove() {
  rafId = 0
  if (pendingPos === null) return
  layout.setSize(props.skey, startSize + props.sign * (pendingPos - startPos))
  pendingPos = null
}

// 结束拖拽: 先补落末位值 (挂起的 rAF 可能还没跑), 再摘监听 + 复原全局光标/选区, 落盘记忆
function onUp() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  applyMove()
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  layout.persist(props.skey)
}

// 开始拖拽: 记起点 + 捕获指针 + 挂全局监听 + 锁定光标/禁选 (防拖拽中选中文本)
function onDown(e) {
  startPos = props.dir === 'x' ? e.clientX : e.clientY
  startSize = layout.sizes[props.skey]
  pendingPos = null
  try {
    e.currentTarget.setPointerCapture(e.pointerId)   // 指针离元素/出窗仍持续收 move (触屏尤要)
  } catch (_err) { /* 老内核无 API 时退化为纯 window 监听 */ }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
  document.body.style.cursor = props.dir === 'x' ? 'col-resize' : 'row-resize'
  document.body.style.userSelect = 'none'
  e.preventDefault()
}

// 键盘等价: 方向键 ±16px 走与拖拽相同的 setSize 写入路径 (sign 语义一致), 每步落盘
function onKeydown(e) {
  const STEP = 16
  let delta = 0
  if (props.dir === 'x') {
    if (e.key === 'ArrowLeft') delta = -STEP
    else if (e.key === 'ArrowRight') delta = STEP
  } else {
    if (e.key === 'ArrowUp') delta = -STEP
    else if (e.key === 'ArrowDown') delta = STEP
  }
  if (!delta) return
  e.preventDefault()
  layout.setSize(props.skey, layout.sizes[props.skey] + props.sign * delta)
  layout.persist(props.skey)
}

// 组件卸载时兜底摘监听并复原全局光标/选区 (拖拽中切路由等, 防卡死光标); 挂起 rAF 一并丢弃
onBeforeUnmount(() => {
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
  pendingPos = null
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<template>
  <div
    class="splitter"
    :class="dir === 'x' ? 'split-x' : 'split-y'"
    role="separator"
    tabindex="0"
    aria-label="调整分栏尺寸"
    :aria-orientation="dir === 'x' ? 'vertical' : 'horizontal'"
    :aria-valuenow="layout.sizes[skey]"
    @pointerdown="onDown"
    @keydown="onKeydown"
  />
</template>

<style scoped>
/* 全幅透明命中区 (整条间隙可抓), 视觉只露一条居中细圆角淡灰条, 仅悬停/拖动时淡入 */
.splitter {
  z-index: 10;
  position: relative;
  background: transparent;
  touch-action: none;   /* 触屏拖拽不触发页面滚动/回弹 (pointer 事件系的前提) */
}
.splitter::before {
  content: "";
  position: absolute;
  border-radius: 999px;
  background: var(--dot-idle);    /* 淡灰 (与现有调色板一致) */
  opacity: 0;
  transition: opacity 0.12s ease, background 0.12s ease;
}
/* 竖向分隔: 居中细竖条, 上下略留白 */
.split-x::before {
  top: 6px;
  bottom: 6px;
  left: 50%;
  width: 4px;
  transform: translateX(-50%);
}
/* 横向分隔: 居中细横条, 左右略留白 */
.split-y::before {
  left: 6px;
  right: 6px;
  top: 50%;
  height: 4px;
  transform: translateY(-50%);
}
.splitter:hover::before {
  opacity: 1;
}
.splitter:active::before {
  opacity: 1;
  background: var(--muted-soft);  /* 拖动时略深 */
}
.split-x {
  cursor: col-resize;
}
.split-y {
  cursor: row-resize;
}
</style>
