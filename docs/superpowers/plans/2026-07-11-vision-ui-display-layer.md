# 视觉 UI 展示层 (弹窗根因修复 + Lightbox + 图例) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 HITL 弹窗被 `width:420px` 卡死的根因,给视觉栏与 HITL 弹窗全部图片加点击放大 Lightbox,并给质量叠加图/识别标注图加颜色图例。

**Architecture:** 纯前端三切片(spec 切片 1/2/4),互相独立:① 一处 CSS 特异性覆盖修根因;② 自研 `ImageLightbox.vue`(Teleport 全屏,transform 缩放平移),各视图持一个 `lightbox` ref、现有 `<img>` 加 `@click` 即接入;③ 图例数据集中在 `overlayLegends.js`,`OverlayLegend.vue` 渲染色块+文案。

**Tech Stack:** Vue 3 `<script setup>` + Vite 5,无 UI 组件库(全自研,延续现状)。前端无测试设施,客观验证 = `npm run build` 通过;行为验证见末任务目验清单。

**Spec:** `docs/superpowers/specs/2026-07-11-vision-ui-tuning-loop-design.md`(切片 1、2、4)

## Global Constraints

- 只改 `eit_ptlc/` 活跃树;`View/pTLC_Viewing/tlc_analyze.py` 本次**只读**(方案 A 不动算法内部)。
- 参数空值语义:前端 `''` = 不覆盖/用基线;`0` 与 `0.0` 是合法值必须透传(沿用 `p.x !== '' && p.x != null` 判式,防 None-sentinel 零值坑)。
- `image_plate_rotation_deg` 语义:`null` = 每帧自动估计;写回 config 时允许 null(`VisionCfg` 字段本为 Optional)。
- 不破坏 run-vs-edit 解耦不变量(浏览/调参不得终止运行中的 run)。
- 后端改动须有离线 pytest 覆盖,现有全量离线套件保持全绿;前端无测试设施,`npm run build` 必须通过。
- UI 文案中文,风格沿用现有自研组件(无 UI 组件库)。
- 新文件服务端点必须有目录穿越防护与后缀白名单(沿用 `vision_routes.py` / `vision_debug_routes.py` 现有模式)。

**本 plan 全部任务无后端改动**;`npm` 命令一律在 `eit_ptlc/web/` 下执行。

---

### Task 1: HITL 弹窗尺寸根因修复

**Files:**
- Modify: `eit_ptlc/web/src/style.css:336-342`(`/* HITL 弹窗 */` 段)
- Modify: `eit_ptlc/web/src/components/HitlModal.vue:265`(加宽条件)、`:363`(`.modal-wide`)

**Interfaces:**
- Consumes: 无(首任务)。
- Produces: 加宽后的 `.modal-wide`(宽 `min(96vw,1500px)` 内自适应内容)与全局 `.hitl-img { max-height:72vh }`。Task 3 的 Lightbox 接入在同文件 `HitlModal.vue` 之上叠加,互不冲突。

背景:`.modal` 固定 `width: 420px` 赢过任何更大的 `max-width`(used width = min(420, max-width)),历史修复(`5b55a83`、`194b8f7`)只改过 `max-width`/`max-height`,全是死代码。scoped 的 `.modal-wide[data-v-*]`(class+属性,特异性 0,2,0)高于全局 `.modal`(0,1,0),补 `width` 即真正生效。

- [ ] **Step 1: 改全局 `.modal` 与 `.hitl-img`**

`eit_ptlc/web/src/style.css` 中把:

```css
/* HITL 弹窗 */
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--panel); border-radius: 10px; padding: 20px 24px; width: 420px; max-width: 90vw; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
.modal h3 { margin: 0 0 10px; }
.hitl-prompt { font-size: 15px; margin: 0 0 12px; }
.hitl-img { max-width: 100%; border-radius: 6px; margin-bottom: 12px; }
```

改为(`.modal` 加 max-height/overflow 防高图纵向溢出;`.hitl-img` 限高):

```css
/* HITL 弹窗 (宽度根因: 固定 width 赢过更大的 max-width — 加宽只能在 .modal-wide 里覆盖 width 本身) */
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.35); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.modal { background: var(--panel); border-radius: 10px; padding: 20px 24px; width: 420px; max-width: 90vw; max-height: 92vh; overflow: auto; box-shadow: 0 10px 40px rgba(0,0,0,0.2); }
.modal h3 { margin: 0 0 10px; }
.hitl-prompt { font-size: 15px; margin: 0 0 12px; }
.hitl-img { max-width: 100%; max-height: 72vh; object-fit: contain; border-radius: 6px; margin-bottom: 12px; }
```

- [ ] **Step 2: 改 `HitlModal.vue` 的加宽类与加宽条件**

`eit_ptlc/web/src/components/HitlModal.vue:363` 把:

```css
.modal-wide { max-width: min(96vw, 1500px); }
```

改为(补 width 覆盖全局固定宽;`width:auto` 由图片内容撑开、上限封顶,竖图不留大片空白):

```css
.modal-wide { width: auto; max-width: min(96vw, 1500px); }
```

`HitlModal.vue:265` 把:

```html
<div class="modal" :class="{ 'modal-wide': debug.hitl.kind === 'sketch' || debug.hitl.kind === 'reanalyze' }">
```

改为(凡带图的门都加宽 — input/confirm 门带 `image` 时同样受 420px 之苦):

```html
<div class="modal" :class="{ 'modal-wide': debug.hitl.kind === 'sketch' || debug.hitl.kind === 'reanalyze' || !!debug.hitl.image }">
```

- [ ] **Step 3: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `vite v5... ✓ built in ...s`,无 error。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/style.css eit_ptlc/web/src/components/HitlModal.vue
git commit -m "fix(hitl): 弹窗420px根因修复 — .modal-wide 补 width 覆盖固定宽 (历史 max-width 修复全是死代码)"
```

---

### Task 2: ImageLightbox 组件 + 视觉栏接入

**Files:**
- Create: `eit_ptlc/web/src/components/ImageLightbox.vue`
- Modify: `eit_ptlc/web/src/views/VisionDebugView.vue`(script 顶部 import/状态、template 6 处 `<img>`、scoped CSS 一行)

**Interfaces:**
- Consumes: 无(独立于 Task 1)。
- Produces: `ImageLightbox.vue` — props `{ src: String, alt: String }`,`src` 非空即显示,事件 `close`(父组件把自己的 `lightbox.src` 置空)。Task 3 按同一契约在 `HitlModal.vue` 接入。

- [ ] **Step 1: 创建 `eit_ptlc/web/src/components/ImageLightbox.vue`**

完整内容:

```vue
<script setup>
// 全屏图片查看器: 滚轮以光标为中心缩放, 拖拽平移, 双击切换 适配/1:1, Esc/点背景关闭。
// 契约: src 非空即显示; 关闭只发 close 事件, 由父组件把 lightbox.src 置空。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  alt: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const imgRef = ref(null)
const viewportRef = ref(null)
const t = reactive({ scale: 1, x: 0, y: 0 })   // 图片 transform: translate(x,y) scale(scale), origin 0 0
const natural = reactive({ w: 0, h: 0 })
let dragging = false
let moved = false                               // 拖拽过则释放时的 click 不当作"点背景关闭"
let dragStart = { x: 0, y: 0, tx: 0, ty: 0 }

const pct = computed(() => `${Math.round(t.scale * 100)}%`)

function computeFit() {
  const vp = viewportRef.value
  if (!vp || !natural.w || !natural.h) return 1
  const pad = 48
  return Math.min((vp.clientWidth - pad) / natural.w, (vp.clientHeight - pad) / natural.h, 1)
}

function reset(mode) {
  // mode: 'fit' | 'full'(1:1)
  const vp = viewportRef.value
  if (!vp || !natural.w) return
  const s = mode === 'full' ? 1 : computeFit()
  t.scale = s
  t.x = (vp.clientWidth - natural.w * s) / 2
  t.y = (vp.clientHeight - natural.h * s) / 2
}

function onLoad() {
  natural.w = imgRef.value?.naturalWidth || 0
  natural.h = imgRef.value?.naturalHeight || 0
  reset('fit')
}

function onWheel(e) {
  if (!natural.w) return
  const vp = viewportRef.value.getBoundingClientRect()
  const cx = e.clientX - vp.left
  const cy = e.clientY - vp.top
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
function onKey(e) {
  if (e.key === 'Escape' && props.src) emit('close')
}

watch(() => props.src, (v) => {
  if (v) { natural.w = 0; natural.h = 0; t.scale = 1; t.x = 0; t.y = 0 }
})
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="src" class="lb-backdrop">
      <div
        ref="viewportRef" class="lb-viewport"
        @wheel.prevent="onWheel" @pointerdown="onPointerDown" @pointermove="onPointerMove"
        @pointerup="onPointerUp" @pointercancel="onPointerUp"
        @click="onViewportClick" @dblclick="onDblClick"
      >
        <img
          ref="imgRef" :src="src" :alt="alt" class="lb-img" draggable="false"
          :style="{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})` }"
          @load="onLoad"
        />
      </div>
      <div class="lb-bar">
        <span class="lb-pct">{{ pct }}</span>
        <button class="lb-btn" @click="reset('fit')">适配</button>
        <button class="lb-btn" @click="reset('full')">1:1</button>
        <a class="lb-btn" :href="src" target="_blank" rel="noopener">原图</a>
        <button class="lb-btn" @click="emit('close')">关闭 Esc</button>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.lb-backdrop { position: fixed; inset: 0; z-index: 1100; background: rgba(0, 0, 0, 0.82); }
.lb-viewport { position: absolute; inset: 0; overflow: hidden; cursor: grab; touch-action: none; }
.lb-viewport:active { cursor: grabbing; }
.lb-img { position: absolute; left: 0; top: 0; transform-origin: 0 0; max-width: none; user-select: none; }
.lb-bar { position: absolute; top: 12px; right: 16px; display: flex; gap: 8px; align-items: center;
  background: rgba(20, 22, 26, 0.88); border-radius: 8px; padding: 6px 10px; }
.lb-pct { color: #ddd; font-size: 12px; min-width: 44px; text-align: center; }
.lb-btn { font-size: 12px; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.25);
  background: transparent; color: #eee; cursor: pointer; text-decoration: none; line-height: 1.4; }
.lb-btn:hover { background: rgba(255, 255, 255, 0.12); }
</style>
```

- [ ] **Step 2: 视觉栏接入**

`eit_ptlc/web/src/views/VisionDebugView.vue` script 顶部 import 区(`:4` 后)加:

```js
import ImageLightbox from '../components/ImageLightbox.vue'
```

script 中状态区(`const controlMode = ref('')` 附近)加:

```js
const lightbox = ref({ src: '', alt: '' })
function openLightbox(evt) {
  if (evt?.target?.src) lightbox.value = { src: evt.target.src, alt: evt.target.alt || '' }
}
```

template 中 6 处 `<img>` 全部加 `@click="openLightbox"`(取 `$event.target.src`,不重算 URL):

```html
<!-- :510 原图 -->
<img v-if="state[role].url" :src="imageUrl(state[role].url)" :alt="role" @click="openLightbox" />
<!-- :515 质量叠加 -->
<img :src="roleQualityUrl(role)" :alt="`${role} quality overlay`" @click="openLightbox" />
<!-- :558 annotated -->
<img :src="imageUrl(analysisUrls.annotated)" alt="annotated" @click="openLightbox" />
<!-- :562 score -->
<img :src="imageUrl(analysisUrls.score)" alt="score" @click="openLightbox" />
```

template 末尾(`</div>` 根元素闭合前)加:

```html
<ImageLightbox :src="lightbox.src" :alt="lightbox.alt" @close="lightbox = { src: '', alt: '' }" />
```

scoped CSS(`:634` 的图片规则后)加一行:

```css
.image-box img, .overlay-box img, .result-image img { cursor: zoom-in; }
```

- [ ] **Step 3: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error(未用变量/组件会报 warning,须为零)。

- [ ] **Step 4: Commit**

```bash
git add eit_ptlc/web/src/components/ImageLightbox.vue eit_ptlc/web/src/views/VisionDebugView.vue
git commit -m "feat(vision-ui): ImageLightbox 点击放大 (滚轮缩放/拖拽/1:1), 视觉栏 6 图全接入"
```

---

### Task 3: HITL 弹窗接入 Lightbox

**Files:**
- Modify: `eit_ptlc/web/src/components/HitlModal.vue`(import、状态、`:316-317` 与 `:338` 三处 `<img>`、template 末尾、scoped CSS)

**Interfaces:**
- Consumes: Task 2 的 `ImageLightbox.vue`(props `{src, alt}`,事件 `close`)。
- Produces: 无下游依赖。

- [ ] **Step 1: 接入**

`HitlModal.vue` script imports(`:11` 后)加:

```js
import ImageLightbox from './ImageLightbox.vue'
```

script 状态区(`const reNonce = ref(0)` 后)加:

```js
const lightbox = ref({ src: '', alt: '' })
function openLightbox(evt) {
  if (evt?.target?.src) lightbox.value = { src: evt.target.src, alt: evt.target.alt || '' }
}
```

门切换/关闭时复位 Lightbox(防门已关而放大图残留):`watch(() => debug.hitl, ...)` 复位区(`reNonce.value = 0` 后)加一行:

```js
  lightbox.value = { src: '', alt: '' }
```

三处 `<img>` 加 `@click`(手绘 canvas 不接 — 交互画布):

```html
<!-- :316 重识别结果图 -->
<img v-if="reResult && reResult.annotated_url" :src="reImg(reResult.annotated_url)" alt="重识别标注图" class="hitl-img" @click="openLightbox" />
<!-- :317 门初始图 (reanalyze 门) -->
<img v-else-if="debug.hitl.image" :src="debug.hitl.image" alt="视觉标注图" class="hitl-img" @click="openLightbox" />
<!-- :338 其余门的图 -->
<img v-if="debug.hitl.image" :src="debug.hitl.image" alt="门附图" class="hitl-img" @click="openLightbox" />
```

template 中 `</Teleport>` 前(`:359`,与 modal 同级)加:

```html
    <ImageLightbox :src="lightbox.src" :alt="lightbox.alt" @close="lightbox = { src: '', alt: '' }" />
```

scoped CSS 加:

```css
.hitl-img { cursor: zoom-in; }
```

(注: Lightbox 的 `z-index: 1100` 高于 `.modal-backdrop` 的 1000,弹窗之上正常展开;Esc 只关 Lightbox 不动门 — 门本身无 Esc 逻辑。)

- [ ] **Step 2: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error。

- [ ] **Step 3: Commit**

```bash
git add eit_ptlc/web/src/components/HitlModal.vue
git commit -m "feat(hitl): 门内标注图接入 ImageLightbox 放大 (canvas 手绘门不接)"
```

---

### Task 4: 叠加图图例

**Files:**
- Create: `eit_ptlc/web/src/overlayLegends.js`
- Create: `eit_ptlc/web/src/components/OverlayLegend.vue`
- Modify: `eit_ptlc/web/src/views/VisionDebugView.vue`(import + 2 处挂载)
- Modify: `eit_ptlc/web/src/components/HitlModal.vue`(import + 1 处挂载)

**Interfaces:**
- Consumes: 无(独立切片;与 Task 2/3 改同两个文件,注意在其改动之上叠加)。
- Produces: `OverlayLegend.vue` — props `{ type: 'quality' | 'annotated', compact?: boolean }`;`overlayLegends.js` — 具名导出 `QUALITY_LEGEND` / `QUALITY_NOTE` / `ANNOTATED_LEGEND` / `ANNOTATED_NOTE`。

- [ ] **Step 1: 创建 `eit_ptlc/web/src/overlayLegends.js`**

```js
// 叠加图图例数据 — 色值为**实际渲染色** (Python 端 BGR → CSS RGB 换算)。
// 源: eit_ptlc/controller/vision_quality.py:776-782 (质量叠加, BGR 常量)
//     View/pTLC_Viewing/tlc_analyze.py:33-45 与 controller/vision_controller.py:709-714 (识别标注, BGR)
// 改动 Python 端颜色时须同步此处 (两端无运行时联动, 靠本注释互指)。

export const QUALITY_LEGEND = [
  { color: 'rgb(0,220,0)', shape: 'box', label: '板外接框', note: '质量指标统计 ROI — 整块板, 非 band' },
  { color: 'rgb(220,220,0)', shape: 'box', label: '板旋转四角', note: '旋转角/透视偏斜证据 — 仍是板级' },
  { color: 'rgb(220,0,0)', shape: 'cross', label: '板中心十字', note: '判机械对中' },
  { color: 'rgb(0,220,220)', shape: 'line', label: '四边留白线', note: '板边到画面边的 margin' },
  { color: 'rgb(240,240,240)', shape: 'cross', label: '画面中心/曝光统计', note: '白色十字与文字、直方图' },
]
export const QUALITY_NOTE = '此图只评估拍照质量 (板几何/曝光), 不含 band; 识别结果见识别标注图 (annotated)。'

export const ANNOTATED_LEGEND = [
  { color: 'rgb(255,132,54)', shape: 'box', label: 'band 轮廓', note: '每条检出条带 (代码常量名 CONTOUR_MAGENTA, 实际渲染为橙)' },
  { color: 'rgb(0,216,236)', shape: 'line', label: '刮取路径', note: '该 band 的 CNC 刮取轨迹' },
  { color: 'rgb(245,245,245)', shape: 'cross', label: 'band 质心/路径端点', note: '' },
  { color: 'rgb(228,232,232)', shape: 'box', label: '板边界框', note: '' },
]
export const ANNOTATED_NOTE = '标签 = band_id (O=origin) · Rf; 最终刮取哪条 band 由 HITL 选择或 VM 默认 (band_01) 决定, 不体现在颜色上。'
```

- [ ] **Step 2: 创建 `eit_ptlc/web/src/components/OverlayLegend.vue`**

```vue
<script setup>
// 叠加图图例: 色块 + 标签 (title 提示详情), 非 compact 时附一行关键说明。
import { computed } from 'vue'
import { ANNOTATED_LEGEND, ANNOTATED_NOTE, QUALITY_LEGEND, QUALITY_NOTE } from '../overlayLegends'

const props = defineProps({
  type: { type: String, required: true },       // 'quality' | 'annotated'
  compact: { type: Boolean, default: false },
})
const items = computed(() => (props.type === 'quality' ? QUALITY_LEGEND : ANNOTATED_LEGEND))
const note = computed(() => (props.type === 'quality' ? QUALITY_NOTE : ANNOTATED_NOTE))
</script>

<template>
  <div class="legend" :class="{ compact }">
    <span v-for="it in items" :key="it.label" class="legend-item" :title="it.note || ''">
      <i class="swatch" :class="it.shape" :style="{ '--c': it.color }"></i>{{ it.label }}
    </span>
    <p v-if="!compact" class="legend-note">{{ note }}</p>
  </div>
</template>

<style scoped>
.legend { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin-top: 6px;
  font-size: 12px; color: var(--subtle); }
.legend.compact { gap: 4px 10px; font-size: 11px; margin-top: 2px; }
.legend-item { display: inline-flex; align-items: center; gap: 5px; cursor: default; }
.swatch { display: inline-block; width: 12px; height: 12px; flex: none; }
.swatch.box { border: 2px solid var(--c); border-radius: 2px; }
.swatch.line { height: 3px; background: var(--c); }
.swatch.cross { position: relative; }
.swatch.cross::before, .swatch.cross::after { content: ''; position: absolute; background: var(--c); }
.swatch.cross::before { left: 5px; top: 0; width: 2px; height: 12px; }
.swatch.cross::after { left: 0; top: 5px; width: 12px; height: 2px; }
.legend-note { flex-basis: 100%; margin: 2px 0 0; color: var(--muted); }
</style>
```

- [ ] **Step 3: 两视图挂载**

`VisionDebugView.vue` import 区加:

```js
import OverlayLegend from '../components/OverlayLegend.vue'
```

template 两处:质量叠加图后(`overlay-box` 内 `<img>` 之后):

```html
<div v-if="roleQualityUrl(role)" class="overlay-box">
  <div class="subhead">质量叠加</div>
  <img :src="roleQualityUrl(role)" :alt="`${role} quality overlay`" @click="openLightbox" />
  <OverlayLegend type="quality" />
</div>
```

annotated 结果图后:

```html
<div v-if="analysisUrls.annotated" class="result-image">
  <div class="subhead">annotated</div>
  <img :src="imageUrl(analysisUrls.annotated)" alt="annotated" @click="openLightbox" />
  <OverlayLegend type="annotated" />
</div>
```

`HitlModal.vue` import 区加:

```js
import OverlayLegend from './OverlayLegend.vue'
```

reanalyze 门标注图(`:316-317` 两个 `<img>`)之后、`re-bands` 之前加:

```html
<OverlayLegend v-if="reResult?.annotated_url || debug.hitl.image" type="annotated" compact />
```

- [ ] **Step 4: 构建验证**

Run: `cd eit_ptlc/web && npm run build`
Expected: `✓ built`,无 error。

- [ ] **Step 5: Commit**

```bash
git add eit_ptlc/web/src/overlayLegends.js eit_ptlc/web/src/components/OverlayLegend.vue eit_ptlc/web/src/views/VisionDebugView.vue eit_ptlc/web/src/components/HitlModal.vue
git commit -m "feat(vision-ui): 叠加图图例 (绿=板ROI/黄=板四角均非band; 标注图band轮廓实为橙) + 质量图不含band说明"
```

---

### Task 5: 收尾验证与目验清单

**Files:**
- 无新改动(验证任务)。

**Interfaces:**
- Consumes: Task 1-4 全部产物。
- Produces: 目验记录(留言即可,不入库)。

- [ ] **Step 1: 全量构建 + 后端离线套件回归(确认前端改动未碰后端)**

Run: `cd eit_ptlc/web && npm run build && cd ../.. && python -m pytest eit_ptlc/tests -q`
Expected: build `✓`;pytest 全绿(数量与改动前一致 — 本 plan 不增减后端测试)。

- [ ] **Step 2: 浏览器目验(需后端: `python -m eit_ptlc` 或 sim 启动后开 web)**

逐项检查并记录:
1. 视觉栏 6 图点击 → Lightbox 打开,滚轮缩放至 1:1 可读 bandid/Rf 标签,拖拽平移,双击切换,Esc 关闭。
2. 质量叠加图与 annotated 图下方图例显示,色块与图上线条目视一致。
3. 触发一次 photoscrape 流程到 reanalyze 门(或 sim):弹窗宽度 ≥ 1200px(1080p 屏),图不再是 420px 小图;门内图可点开 Lightbox;图例 compact 版在图下。
4. 无图的 input/confirm 门仍是 420px 窄弹窗(不受影响)。
5. 手绘门:画布随弹窗加宽,描点精度提升;canvas 点击仍是画点(未被 Lightbox 劫持)。

- [ ] **Step 3: 完成声明**

真机 HITL 实弹验证(第 3 项若无 sim 条件)单列入下次上机 checklist,在完成留言中注明。
