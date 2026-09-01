<script setup>
// 人工介入弹窗: VM 暂停请求人工 (确认/输入/看图/多选门/手绘门) 时弹出, 回复后恢复运行。
//   input   : 文本字段 (如选带 band_id)
//   confirm : 确认/取消
//   choose  : 多按钮门 (下发/手绘/跳过/中止) → 回 choice
//   sketch  : 手绘门 — 在板照片(单张 canvas, 原生分辨率, CSS 缩放)上画闭合区域, 视觉未框到板时
//             先点四角标板; 预览走 /preview_path(所见即所跑), 提交走 /sketch_commit 落 summary,
//             把 summary_path 等经 values 带回 VM (交未改动的 cnc_path 动作)。
import { computed, nextTick, ref, useId, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useDebugStore } from '../stores/debug'
import { api, errText } from '../api'
import { confirmAction, current as confirmCurrent } from '../composables/confirmService.js'
import { useModalA11y } from '../composables/useModalA11y.js'
import ImageLightbox from './ImageLightbox.vue'
import OverlayLegend from './OverlayLegend.vue'
import RecognitionParams from './RecognitionParams.vue'
import EstopButton from './ui/EstopButton.vue'

const debug = useDebugStore()
const route = useRoute()
const values = ref({})

// 对刀/刮痕标定页自带门渲染 (ToolAlignPanel 步骤式 / ScrapeCalibPanel 全自动应答),
// 通用弹窗在这两页让位, 否则同一道门两处可点 (标定页更严重: 弹窗抢答会打断自动序列)。
const suppressed = computed(() =>
  ['tool_align', 'scrape_calib'].includes(route.params.category))

// ---- 手绘门状态 (native 像素坐标, 与 plate_bbox_px 同系) ----
const canvasRef = ref(null)
let bgImage = null              // 已加载的板照片 Image
const polygon = ref([])         // [[x,y]...] native px
const corners = ref([])         // 四角 native px [左上,右上,右下,左下]
const pickMode = ref('region')  // 'corners' | 'region'
const plateBbox = ref(null)
const plateSize = ref(20)
const hasPlateRef = ref(true)
const manualRectify = ref(null)  // 矫正帧记录: 提交时随 commit 落 manual summary (契约C-2)
const rectifiedUrl = ref('')     // 矫正图 URL: 生效时作 commit 的 backdrop_ref
const plateAxes = ref(null)      // 板坐标系标注几何 (后端 plate_coords 同源; 只核标角)
let originalImage = null         // 矫正前底图 (重标四角回退用)
const preview = ref(null)
const busy = ref(false)
const errMsg = ref('')

// ---- 重识别门状态 (kind=reanalyze): 调参→/reanalyze 重跑→选带→用此结果 ----
const reParams = ref({ min_row_score: '', image_plate_orientation: '', auto_rectify_tilt: '', rectify_min_angle_deg: '', image_plate_rotation_deg: '' })
const reResult = ref(null)      // /reanalyze 返回: {annotated_url, bands, band_ids, summary_path}
const reBand = ref('')          // 选中的 band_id
const reBusy = ref(false)
const reErr = ref('')
const reNonce = ref(0)          // 叠加图缓存击穿 (同 case_dir 被覆写, URL 不变)
const reBaseline = ref(null)    // 门打开时读一次 config.vision, 供 override 占位显示基线实际值

// ---- Lightbox 放大 ----
const lightbox = ref([])        // ImageLightbox 吃一组图; 此处单图, 装一个元素
function openLightbox(src, alt) {
  if (src) lightbox.value = [{ src, alt: alt || '' }]
}

// ---- 弹窗可达性 (只接行为层, DOM 结构不动) ----
// open: 与模板显隐同一条件 (v-if debug.hitl && !suppressed + v-show !hitlMinimized);
//   灯箱/确认对话在上层时本层视作"关闭", 焦点圈禁让位给上层弹窗 (双 trap 会互抢 Tab/Esc)。
// onEsc = 「稍后处理」同款动作: 只收起不应答, 最低破坏性 (门保持挂起, 决策不被 Esc 误触)。
const modalRef = ref(null)
const titleId = useId()
const modalOpen = computed(() =>
  !!debug.hitl && !suppressed.value && !debug.hitlMinimized
  && !lightbox.value.length && !confirmCurrent.value)
useModalA11y(modalRef, {
  open: modalOpen,
  onEsc: () => { debug.hitlMinimized = true },
  initialFocus: 'h3',   // 落标题非主操作: 安全决策门上 Enter 不应立即触发任何应答
})

// input 门字段: label/id 配对 + 数值字段判据 (字段无 type 元数据, 按 var 单位后缀识别, 如 dx_mm/dy_mm)
const fieldIdBase = useId()
function fieldId(v) { return `${fieldIdBase}-${v}` }
function fieldType(f) { return /(_mm|_deg|_um|_pct|_ms|_s)$/.test(f.var) ? 'number' : 'text' }

watch(() => debug.hitl, (h) => {
  values.value = {}
  polygon.value = []
  corners.value = []
  preview.value = null
  errMsg.value = ''
  busy.value = false
  bgImage = null
  pickMode.value = 'region'
  plateBbox.value = null
  plateSize.value = 20        // 与其它手绘状态一并复位, 防跨门/跨 run 陈旧尺度送错 plate_size_cm (审阅 #5)
  hasPlateRef.value = true
  manualRectify.value = null
  rectifiedUrl.value = ''
  plateAxes.value = null
  originalImage = null
  reParams.value = { min_row_score: '', image_plate_orientation: '', auto_rectify_tilt: '', rectify_min_angle_deg: '', image_plate_rotation_deg: '' }
  reResult.value = null
  reBand.value = ''
  reBusy.value = false
  reErr.value = ''
  reNonce.value = 0
  reBaseline.value = null
  lightbox.value = []
  if (!h) return
  if (h.fields) for (const f of h.fields) values.value[f.var] = ''
  if (h.kind === 'reanalyze') {
    api.getConfigSection('vision')
      .then((v) => { reBaseline.value = v })
      .catch(() => { reBaseline.value = null })
  }
  if (h.kind === 'sketch') initSketch(h)
})

async function initSketch(h) {
  // 取板参照: 有 plate_bbox_px → 轴对齐; 无 → 前端走四角标板
  plateSize.value = 20        // 各分支兜底: catch / 无 context 都不沿用上一门陈旧尺度 (审阅 #5)
  if (h.context) {
    try {
      const ctx = await api.getSketchContext(h.context)
      plateBbox.value = ctx.plate_bbox_px || null
      plateSize.value = ctx.plate_size_cm || 20
      hasPlateRef.value = !!ctx.has_plate_ref
      plateAxes.value = ctx.plate_axes || null
    } catch (e) {
      hasPlateRef.value = false
      plateAxes.value = null
    }
  } else {
    hasPlateRef.value = false
  }
  if (!hasPlateRef.value) pickMode.value = 'corners'
  if (h.image) {
    const img = new Image()
    img.onload = () => { bgImage = img; nextTick(redraw) }
    img.onerror = () => { errMsg.value = '底图加载失败; 可用「重拍」(运行控制复位) 换一张照片' }
    img.src = h.image
  }
}

function canvasPoint(evt) {
  const c = canvasRef.value
  const rect = c.getBoundingClientRect()
  return [
    (evt.clientX - rect.left) * (c.width / rect.width),
    (evt.clientY - rect.top) * (c.height / rect.height),
  ]
}

function onCanvasClick(evt) {
  if (!bgImage) return
  if (busy.value) return   // rectify 在途防重入: 二次触发会把 originalImage 覆写成矫正帧
  const p = canvasPoint(evt)
  if (pickMode.value === 'corners') {
    if (corners.value.length < 4) corners.value.push(p)
    if (corners.value.length === 4) {
      const err = cornerOrderError(corners.value)
      if (err) { errMsg.value = err; corners.value.pop(); redraw(); return }
      errMsg.value = ''
      rectifyFromCorners()          // 成功→矫正帧接管; 失败→老路(单应)兜底
    }
  } else {
    polygon.value.push(p)
    preview.value = null   // 改动即失效预览
  }
  redraw()
}

// 点序自检 (即时提示; 后端 /sketch_rectify 有同规则最终校验): 返回空串=通过
function cornerOrderError(cs) {
  if (cs.length !== 4) return '需恰好 4 个角点'
  const [tl, tr, br, bl] = cs
  if (!(tl[0] < tr[0] && bl[0] < br[0])) return '左右颠倒: 请按 左上→右上→右下→左下 顺序点'
  if (!(tl[1] < bl[1] && tr[1] < br[1])) return '上下颠倒: 请按 左上→右上→右下→左下 顺序点'
  let sign = 0
  for (let i = 0; i < 4; i++) {
    const a = cs[i], b = cs[(i + 1) % 4], c = cs[(i + 2) % 4]
    const z = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    if (z === 0) return '角点共线, 请重新点'
    if (!sign) sign = Math.sign(z)
    else if (Math.sign(z) !== sign) return '四点不构成凸四边形, 请检查点位/顺序'
  }
  return ''
}

// 4 角就绪 → 后端出矫正帧: 用户看到"程序认为的板"(角点错→图歪斜/切边一眼可见),
// 且后续画区域/预览/提交走与视觉成功分支相同的 plate_bbox_px 仿射主路径。
async function rectifyFromCorners() {
  busy.value = true
  try {
    const res = await api.rectifySketch({
      summary_path: debug.hitl.context, corners_px: corners.value, plate_size_cm: plateSize.value,
    })
    const img = new Image()
    img.onload = () => {
      originalImage = bgImage
      bgImage = img
      plateBbox.value = res.plate_bbox_px
      plateAxes.value = res.plate_axes || null
      manualRectify.value = res.manual_rectify
      rectifiedUrl.value = res.image_url
      hasPlateRef.value = true
      corners.value = []   // 原图像素坐标, 叠矫正帧上是乱线; 成功后 _ready/_plateRefPayload 不再依赖 corners (失败回落路径保留不动)
      polygon.value = []; preview.value = null
      pickMode.value = 'region'
      redraw()
    }
    img.onerror = () => { errMsg.value = '矫正图加载失败 — 回落原图 4 角标定(老路)'; pickMode.value = 'region' }
    img.src = res.image_url
  } catch (e) {
    errMsg.value = errText(e) + ' — 回落原图 4 角标定(老路)'
    pickMode.value = 'region'       // 老路: corners 已点满, 单应链照旧可预览/提交
  } finally {
    busy.value = false
  }
}

function undoPoint() {
  if (pickMode.value === 'corners' && corners.value.length) corners.value.pop()
  else if (polygon.value.length) polygon.value.pop()
  preview.value = null
  redraw()
}

function clearAll() {
  polygon.value = []
  preview.value = null
  if (!hasPlateRef.value) { corners.value = []; pickMode.value = 'corners' }
  redraw()
}

function repickCorners() {
  if (busy.value) return   // rectify/预览/提交在途禁重入: 半路重置会把 originalImage/plateBbox 撕成两个世代 (审阅 P0)
  busy.value = true        // 与 onCanvasClick 同一 busy 语义; 同步体也走 try/finally, 防中途抛错卡死按钮
  try {
    if (originalImage) { bgImage = originalImage; originalImage = null }
    manualRectify.value = null
    rectifiedUrl.value = ''
    hasPlateRef.value = false
    plateBbox.value = null
    plateAxes.value = null
    corners.value = []
    polygon.value = []
    pickMode.value = 'corners'
    preview.value = null
    redraw()
  } finally {
    busy.value = false
  }
}

function _lw() { return bgImage ? Math.max(2, Math.round(bgImage.naturalWidth / 500)) : 2 }

function _poly(ctx, pts, closed, color, width) {
  if (!pts.length) return
  ctx.beginPath()
  ctx.moveTo(pts[0][0], pts[0][1])
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1])
  if (closed) ctx.closePath()
  ctx.lineWidth = width
  ctx.strokeStyle = color
  ctx.stroke()
}

function _arrow(ctx, from, to, color, lw, label) {
  ctx.strokeStyle = color; ctx.lineWidth = lw
  ctx.beginPath(); ctx.moveTo(from[0], from[1]); ctx.lineTo(to[0], to[1]); ctx.stroke()
  const ang = Math.atan2(to[1] - from[1], to[0] - from[0])
  ctx.beginPath()
  ctx.moveTo(to[0], to[1])
  ctx.lineTo(to[0] - lw * 4 * Math.cos(ang - 0.5), to[1] - lw * 4 * Math.sin(ang - 0.5))
  ctx.moveTo(to[0], to[1])
  ctx.lineTo(to[0] - lw * 4 * Math.cos(ang + 0.5), to[1] - lw * 4 * Math.sin(ang + 0.5))
  ctx.stroke()
  ctx.fillStyle = color; ctx.font = `${lw * 5}px sans-serif`
  ctx.fillText(label, to[0] + lw * 2, to[1] - lw * 2)
}

function redraw() {
  const c = canvasRef.value
  if (!c || !bgImage) return
  c.width = bgImage.naturalWidth
  c.height = bgImage.naturalHeight
  const ctx = c.getContext('2d')
  ctx.drawImage(bgImage, 0, 0)
  const lw = _lw()
  // 预览路径 (青=刮取, 洋红闭合=区域轮廓)
  if (preview.value) {
    _poly(ctx, preview.value.scrape_px || [], false, 'rgba(0,216,236,0.9)', lw)
    _poly(ctx, preview.value.contour_px || [], true, 'rgba(255,132,54,0.9)', lw)
  }
  // 用户手绘多边形
  if (polygon.value.length) {
    _poly(ctx, polygon.value, polygon.value.length >= 3, 'rgba(255,64,180,0.95)', lw)
    ctx.fillStyle = 'rgba(255,64,180,0.95)'
    for (const [x, y] of polygon.value) { ctx.beginPath(); ctx.arc(x, y, lw * 1.8, 0, 7); ctx.fill() }
  }
  // 四角标板
  const CORNER_LABELS = ['左上', '右上', '右下', '左下']
  corners.value.forEach(([x, y], i) => {
    ctx.fillStyle = 'yellow'; ctx.beginPath(); ctx.arc(x, y, lw * 2.2, 0, 7); ctx.fill()
    ctx.fillStyle = 'black'; ctx.font = `${lw * 6}px sans-serif`
    ctx.fillText(`${i + 1} ${CORNER_LABELS[i]}`, x + lw * 3, y)
  })
  if (corners.value.length === 4) _poly(ctx, corners.value, true, 'rgba(255,255,0,0.6)', lw)
  // 板坐标系标注 (后端同源几何): 原点双圈 + ±轴箭头 + 四角 cm 标签; 只核标角, 不核对刀
  if (plateAxes.value && hasPlateRef.value) {
    const a = plateAxes.value
    const gold = 'rgba(255,215,0,0.95)'
    ctx.strokeStyle = gold; ctx.lineWidth = lw
    ctx.beginPath(); ctx.arc(a.origin_px[0], a.origin_px[1], lw * 3, 0, 7); ctx.stroke()
    ctx.beginPath(); ctx.arc(a.origin_px[0], a.origin_px[1], lw * 6, 0, 7); ctx.stroke()
    _arrow(ctx, a.origin_px, a.x_tip_px, gold, lw, '+x')
    _arrow(ctx, a.origin_px, a.y_tip_px, gold, lw, '+y')
    ctx.fillStyle = gold; ctx.font = `${lw * 5}px sans-serif`
    for (const cnr of a.corners) {
      // 标签贴角但不出画幅: 左半角向右偏, 右半角向左偏; 上半角向下偏, 下半角向上偏
      const midX = (a.corners[0].px[0] + a.corners[1].px[0]) / 2
      const midY = (a.corners[0].px[1] + a.corners[2].px[1]) / 2
      const dx = cnr.px[0] <= midX ? lw * 2 : -lw * 18
      const dy = cnr.px[1] >= midY ? -lw * 2 : lw * 6
      ctx.fillText(cnr.label, cnr.px[0] + dx, cnr.px[1] + dy)
    }
  }
}

function _plateRefPayload() {
  return hasPlateRef.value
    ? { plate_bbox_px: plateBbox.value }
    : { plate_corners_px: corners.value }
}

function _ready() {
  if (polygon.value.length < 3) return false
  if (!hasPlateRef.value && corners.value.length !== 4) return false
  return true
}

async function doPreview() {
  if (!_ready()) { errMsg.value = '先画至少 3 个点的闭合区域' + (hasPlateRef.value ? '' : ' (并点满四角)'); return }
  busy.value = true; errMsg.value = ''
  try {
    preview.value = await api.previewScrapePath({
      polygon_px: polygon.value, plate_size_cm: plateSize.value, ..._plateRefPayload(),
    })
    redraw()
  } catch (e) { errMsg.value = errText(e) } finally { busy.value = false }
}

async function submitSketch() {
  if (!_ready()) { errMsg.value = '先画至少 3 个点的闭合区域' + (hasPlateRef.value ? '' : ' (并点满四角)'); return }
  busy.value = true; errMsg.value = ''
  try {
    const res = await api.commitSketch({
      polygon_px: polygon.value, plate_size_cm: plateSize.value,
      summary_path: debug.hitl.context,
      backdrop_ref: rectifiedUrl.value || debug.hitl.image,
      manual_rectify: manualRectify.value || undefined,
      ..._plateRefPayload(),
    })
    await debug.replyHuman({ choice: 'ok', values: {   // await: 回复失败要能被 catch 并复位 busy, 否则弹窗卡死 (审阅 #7)
      sketch_summary_path: res.summary_path,
      sketch_band_id: res.band_id,
      sketch_annotated_url: res.annotated_url || '',
    } })
  } catch (e) {
    errMsg.value = errText(e)
  } finally {
    busy.value = false                                 // 成功(弹窗已关, 无害)/失败(可重试)都复位
  }
}

// 只收非空覆盖项; 留空 = 用 config.vision 实时基线 (与后端 /reanalyze 语义一致)
function reOverrides() {
  const p = reParams.value
  const o = {}
  if (p.min_row_score !== '' && p.min_row_score != null) o.min_row_score = Number(p.min_row_score)
  if (p.rectify_min_angle_deg !== '' && p.rectify_min_angle_deg != null) o.rectify_min_angle_deg = Number(p.rectify_min_angle_deg)
  if (p.image_plate_rotation_deg !== '' && p.image_plate_rotation_deg != null) o.image_plate_rotation_deg = Number(p.image_plate_rotation_deg)
  if (p.image_plate_orientation) o.image_plate_orientation = p.image_plate_orientation
  if (p.auto_rectify_tilt !== '') o.auto_rectify_tilt = p.auto_rectify_tilt === 'true'
  return o
}
function reImg(url) {
  if (!url) return ''
  return `${url}${url.includes('?') ? '&' : '?'}n=${reNonce.value}`
}
async function doReanalyze() {
  reBusy.value = true; reErr.value = ''
  try {
    const res = await api.reanalyzePhotoscrape({ summary_path: debug.hitl.context, ...reOverrides() })
    reResult.value = res
    reNonce.value += 1
    const first = (res.bands || []).find((b) => !b.is_origin) || (res.bands || [])[0]
    reBand.value = first ? first.band_id : (res.band_ids || [])[0] || 'band_01'
  } catch (e) { reErr.value = errText(e) } finally { reBusy.value = false }
}
async function useReanalyze() {
  if (!reResult.value) { reErr.value = '先「重新识别」出结果再用'; return }
  if (!reBand.value) { reErr.value = '请选择要刮取的条带'; return }
  reBusy.value = true; reErr.value = ''
  try {
    await debug.replyHuman({ choice: 'ok', values: {   // await + try/finally: 与 submitSketch 同型失败语义 (审阅 #7)
      reanalyze_summary_path: reResult.value.summary_path,
      reanalyze_band_id: reBand.value,
      reanalyze_annotated_url: reResult.value.annotated_url || '',
    } })
  } catch (e) {
    reErr.value = errText(e)
  } finally {
    reBusy.value = false
  }
}
// 「取消」= 中止整个运行, 非普通关窗 —— 危险级二次确认后才回 choice=cancel
function confirmAbort() {
  return confirmAction({
    level: 'danger',
    title: '中止当前运行',
    message: '流程将结束, 已执行的物理动作不会回退。',
    confirmText: '中止运行',
  })
}
async function cancelReanalyze() {
  if (!(await confirmAbort())) return
  debug.replyHuman({ choice: 'cancel', values: {} })
}
// #13: 只回填非空字段 —— 留空的输入(如 band_id)不覆盖 VM 默认(band_01)。
// VM 写入任何在 values 里出现的字段; 空串会把默认覆盖成 '' → cnc_path 选不到带 → 落回门。
function submit(choice) {
  const vals = {}
  for (const [k, v] of Object.entries(values.value)) if (v !== '' && v != null) vals[k] = v
  debug.replyHuman({ choice, values: vals })
}
function choose(value) { debug.replyHuman({ choice: value, values: {} }) }
async function cancelSketch() {
  if (!(await confirmAbort())) return
  debug.replyHuman({ choice: 'cancel', values: {} })
}
</script>

<template>
  <Teleport to="body">
    <div v-if="debug.hitl && !suppressed" v-show="!debug.hitlMinimized" class="modal-backdrop">
      <div
        ref="modalRef" class="modal"
        :class="{ 'modal-wide': debug.hitl.kind === 'sketch' || debug.hitl.kind === 'reanalyze' || !!debug.hitl.image }"
        role="dialog" aria-modal="true" tabindex="-1" :aria-labelledby="titleId"
      >
        <!-- 标题行内嵌急停 (共享 useEstop 单例): 本弹窗阻塞机器等人工决策, backdrop 期间
             态势条急停被盖, 这里保持出口; initialFocus 仍是 h3, Enter 不会误触发 -->
        <div class="modal-head">
          <h3 :id="titleId" tabindex="-1">人工介入</h3>
          <EstopButton sm />
        </div>
        <p class="hitl-prompt">{{ debug.hitl.prompt }}</p>

        <!-- 手绘门: 单 canvas 画区域 -->
        <template v-if="debug.hitl.kind === 'sketch'">
          <p v-if="!hasPlateRef" class="hitl-hint">
            视觉未框到板 — 请按 <b>左上→右上→右下→左下</b> 点四角标板 ({{ corners.length }}/4);
            点满后自动生成<b>矫正图</b>供确认(板应充满画幅、边缘横平竖直), 再画要刮取的闭合区域。
          </p>
          <p v-else-if="manualRectify" class="hitl-hint">
            已按 4 角矫正 — 当前即"程序认为的板"。若板歪斜/切边说明角点有误, 点「重标四角」重来;
            确认无误后画要刮取的<b>闭合区域</b>。金色双圈 = 程序认定的 cm 原点角, 应贴点样边。
          </p>
          <p v-else class="hitl-hint">在板照片上点击若干点圈出要刮取的<b>闭合区域</b>, 预览满意后提交。</p>
          <div class="sketch-wrap">
            <canvas ref="canvasRef" class="sketch-canvas" role="img" aria-label="板位四角标注画布" @click="onCanvasClick"></canvas>
          </div>
          <OverlayLegend v-if="hasPlateRef && plateAxes" type="sketch_axes" />
          <p v-if="preview" class="hitl-hint">
            预览: {{ preview.pass_count }} pass · {{ preview.point_count }} 点 · 进给 {{ preview.feed }}
          </p>
          <p v-if="errMsg" class="hitl-err">{{ errMsg }}</p>
          <div class="modal-actions">
            <button class="run" :disabled="busy" @click="submitSketch">提交路径</button>
            <button class="run ghost" :disabled="busy" @click="doPreview">预览</button>
            <button class="run ghost" :disabled="busy" @click="undoPoint">撤销点</button>
            <button class="run ghost" :disabled="busy" @click="clearAll">清除</button>
            <button v-if="!hasPlateRef || manualRectify" class="run ghost" :disabled="busy" @click="repickCorners">重标四角</button>
            <!-- 「稍后处理」有意不随 busy 禁用: 只收起不改门状态, 是在途长请求时唯一的离场出口 (Esc 同款) -->
            <button class="run ghost" @click="debug.hitlMinimized = true">稍后处理</button>
            <button class="run ghost" :disabled="busy" @click="cancelSketch">取消</button>
          </div>
        </template>

        <!-- 重识别门: 调参 → 在本 run before/after 重跑 → 选带 → 用此结果 (与手绘门同形: 回带 summary_path) -->
        <template v-else-if="debug.hitl.kind === 'reanalyze'">
          <p class="hitl-hint">调整识别参数后「重新识别」—— 在本 run 的 before/after 上重跑分析; 满意后选条带「用此结果」下发。<b>留空 = 用当前生产配置基线</b>。</p>
          <RecognitionParams v-model="reParams" mode="override" :baseline="reBaseline" />
          <button v-if="reResult && reResult.annotated_url" type="button" class="btn-bare img-btn" title="放大查看"
                  @click="openLightbox(reImg(reResult.annotated_url), '重识别标注图: 板面条带识别结果')">
            <img :src="reImg(reResult.annotated_url)" alt="重识别标注图: 板面条带识别结果" class="hitl-img" />
          </button>
          <button v-else-if="debug.hitl.image" type="button" class="btn-bare img-btn" title="放大查看"
                  @click="openLightbox(debug.hitl.image, '视觉标注图: 板面条带识别结果')">
            <img :src="debug.hitl.image" alt="视觉标注图: 板面条带识别结果" class="hitl-img" />
          </button>
          <OverlayLegend v-if="reResult?.annotated_url || debug.hitl.image" type="annotated" compact />
          <div v-if="reResult" class="re-bands">
            <label><span>选条带</span>
              <select v-model="reBand">
                <option v-for="b in reResult.bands || []" :key="b.band_id" :value="b.band_id">
                  {{ b.band_id }}{{ b.is_origin ? ' (origin)' : '' }}{{ b.normalized_develop_height != null ? ` · Rf ${Number(b.normalized_develop_height).toFixed(3)}` : '' }}
                </option>
              </select>
            </label>
            <span>{{ (reResult.bands || []).length }} 条带</span>
          </div>
          <p v-if="reErr" class="hitl-err">{{ reErr }}</p>
          <div class="modal-actions">
            <button class="run" :disabled="reBusy || !reResult" @click="useReanalyze">用此结果</button>
            <button class="run ghost" :disabled="reBusy" @click="doReanalyze">{{ reBusy ? '识别中…' : '重新识别' }}</button>
            <button class="run ghost" @click="debug.hitlMinimized = true">稍后处理</button>
            <button class="run ghost" :disabled="reBusy" @click="cancelReanalyze">取消</button>
          </div>
        </template>

        <!-- 其余门: 图 + 字段/按钮 -->
        <template v-else>
          <button v-if="debug.hitl.image" type="button" class="btn-bare img-btn" title="放大查看"
                  @click="openLightbox(debug.hitl.image, '门附图: 当前工位现场照片')">
            <img :src="debug.hitl.image" alt="门附图: 当前工位现场照片" class="hitl-img" />
          </button>
          <OverlayLegend
            v-if="debug.hitl.image"
            :type="debug.hitl.kind === 'choose' ? 'cnc' : 'annotated'"
            compact
          />
          <div v-if="debug.hitl.kind === 'input'">
            <div v-for="f in debug.hitl.fields" :key="f.var" class="field">
              <label :for="fieldId(f.var)">{{ f.label || f.var }}</label>
              <input :id="fieldId(f.var)" v-model="values[f.var]" :type="fieldType(f)"
                     :step="fieldType(f) === 'number' ? 'any' : undefined" placeholder="留空 = 用默认值" />
            </div>
          </div>
          <div class="modal-actions">
            <template v-if="debug.hitl.kind === 'choose'">
              <button v-for="o in debug.hitl.options" :key="o.value" class="run" @click="choose(o.value)">
                {{ o.label || o.value }}
              </button>
            </template>
            <template v-else>
              <button class="run" @click="submit('ok')">{{ debug.hitl.kind === 'confirm' ? '确认' : '提交' }}</button>
              <button v-if="debug.hitl.kind === 'confirm'" class="run ghost" @click="submit('cancel')">取消</button>
            </template>
            <button class="run ghost" @click="debug.hitlMinimized = true">稍后处理</button>
          </div>
        </template>
      </div>
    </div>
    <ImageLightbox :items="lightbox" @close="lightbox = []" />
  </Teleport>
</template>

<style scoped>
.modal-wide { width: auto; max-width: min(96vw, 1500px); }
.hitl-hint { font-size: var(--fs-12); opacity: 0.8; margin: 4px 0; }
.hitl-err { color: var(--bad); font-size: var(--fs-12); margin: 4px 0; }
/* min-height 占位防 CLS: 全局 .hitl-img (style.css) 只有 max 约束, 门附图加载期弹窗会塌陷跳变 */
.hitl-img { cursor: zoom-in; min-height: 200px; }
/* 图片外包的灯箱按钮 (键盘可达): 占位与原裸 img 一致, 全局 .hitl-img 尺寸规则原样生效 */
button.img-btn { display: block; width: 100%; }
/* 手绘画布尽量占满可视高度: 大屏上不再被 900px/60vh 挤成小图, 提高描点精度 */
.sketch-wrap { max-height: 80vh; overflow: auto; border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; }
.sketch-canvas { display: block; max-width: 100%; height: auto; cursor: crosshair; }
.modal-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.re-bands { display: flex; align-items: center; gap: 12px; margin: 6px 0; font-size: var(--fs-12); }
.re-bands label { display: flex; align-items: center; gap: 6px; }
</style>
