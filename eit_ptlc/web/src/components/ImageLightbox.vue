<script setup>
// 全屏图片查看器: 滚轮以光标为中心缩放, 拖拽平移, 双击切换 适配/1:1, Esc/点背景关闭。
//
// 吃**一组**图: 横向均分成 N 个窗格, 所有窗格共享同一套 transform ——
// 缩放/平移天然联动, 用于并排比对同尺寸的前后帧(如刮痕标定的刮前/刮后归一化帧,
// 帧回放契约保证两图逐像素配准, 故同一 (x,y) 在两图上就是板面同一点)。
// N=1 时行为与单图查看器完全一致。
//
// 契约: items 非空即显示; 关闭只发 close 事件, 由父组件把 items 置空。
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useModalA11y } from '../composables/useModalA11y.js'

const props = defineProps({
  // [{ src, alt, caption }] —— caption 可省, 有则显示在窗格下方
  items: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])

const rootRef = ref(null)
const viewportRef = ref(null)
const paneRefs = ref([])                        // 每个窗格的 DOM, 用于取窗格宽度
const imgRefs = ref([])
const t = reactive({ scale: 1, x: 0, y: 0 })    // 共享 transform: translate(x,y) scale(scale), origin 0 0
const natural = reactive({ w: 0, h: 0 })        // 各图原始尺寸的**最大值**, 用于算适配倍率
let dragging = false
let moved = false                               // 拖拽过则释放时的 click 不当作"点背景关闭"
let dragStart = { x: 0, y: 0, tx: 0, ty: 0 }

const shown = computed(() => (props.items || []).filter((it) => it && it.src))
const pct = computed(() => `${Math.round(t.scale * 100)}%`)

// 窗格几何缓存: 打开时/图 load 时/window resize 时各测一次, 滚轮与键盘缩放热路径零布局读
// (原先每个 wheel 事件都 getBoundingClientRect + clientWidth, 高频缩放时反复强制布局)。
// lefts 逐窗格存 —— 多窗格并排 left 各不相同, 光标局部坐标必须用所在窗格的原点; top/宽高各窗格一致。
const paneRect = { lefts: [], top: 0, w: 0, h: 0 }

function measurePanes() {
  const pane = paneRefs.value[0]
  const vp = viewportRef.value
  if (pane) {
    paneRect.lefts = paneRefs.value.map((el) => (el ? el.getBoundingClientRect().left : 0))
    paneRect.top = pane.getBoundingClientRect().top
    paneRect.w = pane.clientWidth
    paneRect.h = pane.clientHeight
  } else if (vp) {
    // 窗格未挂载时退回 viewport 整幅均分 (与原 paneSize 兜底同口径)
    const r = vp.getBoundingClientRect()
    paneRect.lefts = [r.left]
    paneRect.top = r.top
    paneRect.w = vp.clientWidth / Math.max(1, shown.value.length)
    paneRect.h = vp.clientHeight
  } else {
    paneRect.lefts = []
    paneRect.top = 0
    paneRect.w = 0
    paneRect.h = 0
  }
}

function computeFit() {
  if (!paneRect.w || !natural.w || !natural.h) return 1
  const pad = 32
  return Math.min((paneRect.w - pad) / natural.w, (paneRect.h - pad) / natural.h, 1)
}

function reset(mode) {
  // mode: 'fit' | 'full'(1:1); 居中按**单个窗格**算, 各窗格因共享 transform 而同步
  if (!paneRect.w || !natural.w) return
  const s = mode === 'full' ? 1 : computeFit()
  t.scale = s
  t.x = (paneRect.w - natural.w * s) / 2
  t.y = (paneRect.h - natural.h * s) / 2
}

function onLoad() {
  measurePanes()   // 图就绪即刷新几何缓存 (随后 reset('fit') 依赖它)
  // 取所有已加载图的最大原始尺寸 —— 按最大者适配, 保证没有一张被裁出窗格
  let mw = 0
  let mh = 0
  for (const img of imgRefs.value) {
    if (!img) continue
    mw = Math.max(mw, img.naturalWidth || 0)
    mh = Math.max(mh, img.naturalHeight || 0)
  }
  if (!mw || !mh) return
  natural.w = mw
  natural.h = mh
  reset('fit')
}

function onWheel(e) {
  if (!natural.w) return
  // 锚点取**光标所在窗格**的局部坐标: 各窗格共享 transform, 用局部坐标才能让光标下的像素不动。
  // 窗格原点走几何缓存 (indexOf 定位所在窗格), 热路径不再读布局
  const i = paneRefs.value.indexOf(e.currentTarget)
  const cx = e.clientX - (paneRect.lefts[i] || 0)
  const cy = e.clientY - paneRect.top
  const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2
  const next = Math.min(8, Math.max(computeFit() * 0.5, t.scale * factor))
  // 保持光标下的图像点不动: 光标处图像坐标 = (cx - t.x) / t.scale
  t.x = cx - ((cx - t.x) / t.scale) * next
  t.y = cy - ((cy - t.y) / t.scale) * next
  t.scale = next
}

function onPointerDown(e) {
  dragging = true
  moved = false
  dragStart = { x: e.clientX, y: e.clientY, tx: t.x, ty: t.y }
  e.currentTarget.setPointerCapture(e.pointerId)
}
function onPointerMove(e) {
  if (!dragging) return
  const dx = e.clientX - dragStart.x
  const dy = e.clientY - dragStart.y
  if (Math.abs(dx) > 3 || Math.abs(dy) > 3) moved = true
  t.x = dragStart.tx + dx
  t.y = dragStart.ty + dy
}
function onPointerUp() { dragging = false }
function onViewportClick(e) {
  if (e.target === e.currentTarget && !moved) emit('close')
}
function onDblClick() { reset(t.scale >= 0.999 ? 'fit' : 'full') }

// 弹窗可达性 (Esc/Tab 圈禁/还焦统一走 useModalA11y, 不再自装 Esc 监听防双绑)
useModalA11y(rootRef, {
  open: computed(() => shown.value.length > 0),
  onEsc: () => emit('close'),
})

// 键盘等价缩放: +/- 以窗格中心为锚缩放 (与滚轮同一套 transform 公式), 0 复位适配, F 同双击切 适配/1:1
function zoomAtCenter(factor) {
  if (!natural.w) return
  const cx = paneRect.w / 2
  const cy = paneRect.h / 2
  const next = Math.min(8, Math.max(computeFit() * 0.5, t.scale * factor))
  t.x = cx - ((cx - t.x) / t.scale) * next
  t.y = cy - ((cy - t.y) / t.scale) * next
  t.scale = next
}
function onZoomKey(e) {
  if (!shown.value.length) return
  if (e.ctrlKey || e.metaKey || e.altKey) return   // 不截浏览器级快捷键 (Ctrl+- 等)
  if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomAtCenter(1.2) }
  else if (e.key === '-' || e.key === '_') { e.preventDefault(); zoomAtCenter(1 / 1.2) }
  else if (e.key === '0') { e.preventDefault(); reset('fit') }
  else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); onDblClick() }
}

watch(() => props.items, () => {
  natural.w = 0
  natural.h = 0
  t.scale = 1
  t.x = 0
  t.y = 0
  imgRefs.value = []
  paneRefs.value = []
  nextTick(measurePanes)   // 打开/换图后窗格重建, DOM 更新完重测几何缓存 (图 load 还会再测一次兜底)
})
// 窗口尺寸变化会挪窗格原点/宽高: 重测一次缓存 (关着时无窗格, 跳过)
function onWinResize() {
  if (!shown.value.length) return
  measurePanes()
}
onMounted(() => {
  window.addEventListener('keydown', onZoomKey)
  window.addEventListener('resize', onWinResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onZoomKey)
  window.removeEventListener('resize', onWinResize)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="shown.length" ref="rootRef" class="lb-backdrop"
      role="dialog" aria-modal="true" tabindex="-1" aria-label="图片查看器"
    >
      <div ref="viewportRef" class="lb-viewport" @click="onViewportClick">
        <div
          v-for="(it, i) in shown" :key="it.src + i"
          :ref="(el) => { if (el) paneRefs[i] = el }" class="lb-pane"
          @wheel.prevent="onWheel" @pointerdown="onPointerDown" @pointermove="onPointerMove"
          @pointerup="onPointerUp" @pointercancel="onPointerUp"
          @click="onViewportClick" @dblclick="onDblClick"
        >
          <img
            :ref="(el) => { if (el) imgRefs[i] = el }" :src="it.src" :alt="it.alt || ''"
            class="lb-img" draggable="false"
            :style="{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})` }"
            @load="onLoad"
          />
          <span v-if="it.caption" class="lb-cap">{{ it.caption }}</span>
        </div>
      </div>
      <div class="lb-bar">
        <span class="lb-pct">{{ pct }}</span>
        <button class="lb-btn" title="快捷键 0" @click="reset('fit')">适配</button>
        <button class="lb-btn" title="快捷键 F 切换" @click="reset('full')">1:1</button>
        <a v-for="(it, i) in shown" :key="'raw' + i" class="lb-btn" :href="it.src"
           target="_blank" rel="noopener">{{ shown.length > 1 ? `原图${i + 1}` : '原图' }}</a>
        <button class="lb-btn" aria-keyshortcuts="Escape"
                title="Esc 关闭 · +/− 缩放 · 0 适配 · F 切换 1:1" @click="emit('close')">关闭</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lb-backdrop { position: fixed; inset: 0; z-index: 1100; background: rgba(0, 0, 0, 0.82); }
.lb-viewport { position: absolute; inset: 0; display: flex; }
.lb-pane { position: relative; flex: 1 1 0; min-width: 0; overflow: hidden; cursor: grab; touch-action: none;
  overscroll-behavior: contain; }
.lb-pane + .lb-pane { border-left: 1px solid rgba(255, 255, 255, 0.18); }
.lb-pane:active { cursor: grabbing; }
.lb-img { position: absolute; left: 0; top: 0; transform-origin: 0 0; max-width: none; user-select: none; }
.lb-cap { position: absolute; left: 50%; bottom: 12px; transform: translateX(-50%); pointer-events: none;
  background: rgba(20, 22, 26, 0.88); color: #ddd; font-size: var(--fs-12); padding: 4px 10px; border-radius: 6px;
  white-space: nowrap; }
.lb-bar { position: absolute; top: 12px; right: 16px; display: flex; gap: 8px; align-items: center;
  background: rgba(20, 22, 26, 0.88); border-radius: 8px; padding: 6px 10px; }
.lb-pct { color: #ddd; font-size: var(--fs-12); min-width: 44px; text-align: center; }
.lb-btn { font-size: var(--fs-12); padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.25);
  background: transparent; color: #eee; cursor: pointer; text-decoration: none; line-height: 1.4; }
.lb-btn:hover { background: rgba(255, 255, 255, 0.12); }
</style>
