<script setup>
// 液位单通道可视标定 (冻结帧): 左键拖 = 执行当前「左键工具」—— 框检测区(绿) / 框干参考区(橙)
// / 沿板竖直边画线摆正; 也可数字微调; 选流向; 采参考图; 保存标定。
// 画布占满左栏自适应放大; 控制面板经 Teleport 落到右栏 #wl-calib-panel 锚点 (WaterLevelChannel)。
// 旋转几何镜像上位机 waterlevel_detector.rotation_matrix / angle_to_make_line_vertical
// (改 Python 侧须同步此处), roi_frac 纯数学 → 后端同式复现, 像素级一致。
import { onBeforeUnmount, onMounted, reactive, ref, nextTick } from 'vue'
import { api, wlFrameUrl, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'

const props = defineProps({
  channel: { type: Number, required: true },
  online: { type: Boolean, default: false },
})

const canvas = ref(null)          // 展示画布 (旋转后)
const rawImg = ref(null)          // 冻结的原始帧 (Image 元素)
const angle = ref(0)              // 旋转总角 (度)
const flow = ref('left_to_right')
const roiFrac = reactive({ fx: 0.30, fy: 0.05, fw: 0.20, fh: 0.80 })
// 干参考区 (橙框, 漂移补偿参照): on=false 视为未配置, 保存时发 null 表示清除
const dry = reactive({ on: false, fx: 0.02, fy: 0.10, fw: 0.13, fh: 0.80 })
// 左键工具 (单一模态, 无右键旁路): 'roi'=框检测区(绿) | 'dry'=框干参考区(橙) | 'line'=画线摆正
const tool = ref('roi')
const msg = ref('')
const rotSize = reactive({ w: 1, h: 1 })   // 旋转后画布尺寸
const FLOWS = ['left_to_right', 'right_to_left', 'bottom_to_top']

// 交互态 (指针手势: pointerdown 捕获 → move 预览 → up 落定 / cancel 丢弃)
let lineP0 = null                 // 画线起点 (画布像素)
let lineCur = null
let boxDrag0 = null               // 拖框起点 (绿/橙共用, 落到谁由 tool 决定)
let boxDragCur = null
let activePointerId = null        // 在途手势的指针 id (多指第二指忽略; null=无手势)
let dragRect = null               // pointerdown 缓存的画布矩形 (move 逐帧 getBoundingClientRect 会强制布局)
let rafId = 0                     // move 重绘的 rAF 句柄 (一帧至多画一次)

// --- 几何: 镜像 Python rotation_matrix(scale=1) ---
function rotationMatrix(angleDeg, w, h) {
  const a = (angleDeg * Math.PI) / 180
  const cos = Math.cos(a), sin = Math.sin(a)
  const cosA = Math.abs(cos), sinA = Math.abs(sin)
  const newW = Math.trunc(h * sinA + w * cosA)
  const newH = Math.trunc(h * cosA + w * sinA)
  const cx = w / 2, cy = h / 2
  // cv2.getRotationMatrix2D(center, angle, 1): [[cos,sin,(1-cos)cx-sin*cy],[-sin,cos,sin*cx+(1-cos)cy]]
  let m02 = (1 - cos) * cx - sin * cy
  let m12 = sin * cx + (1 - cos) * cy
  m02 += newW / 2 - cx
  m12 += newH / 2 - cy
  return { m00: cos, m01: sin, m02, m10: -sin, m11: cos, m12, newW, newH }
}

// 镜像 Python angle_to_make_line_vertical
function angleToMakeLineVertical(dx, dy) {
  const theta = (Math.atan2(dy, dx) * 180) / Math.PI
  let delta = theta - 90   // 符号对齐 cv2.getRotationMatrix2D (与 Python angle_to_make_line_vertical 一致)
  while (delta <= -90) delta += 180
  while (delta > 90) delta -= 180
  return delta
}

function draw() {
  const cvs = canvas.value
  const img = rawImg.value
  if (!cvs || !img) return
  const R = rotationMatrix(angle.value, img.naturalWidth, img.naturalHeight)
  rotSize.w = R.newW; rotSize.h = R.newH
  cvs.width = R.newW; cvs.height = R.newH
  const ctx = cvs.getContext('2d')
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, R.newW, R.newH)
  // canvas.setTransform(a,b,c,d,e,f) = [[a,c,e],[b,d,f]] ← 对应 cv2 M
  ctx.setTransform(R.m00, R.m10, R.m01, R.m11, R.m02, R.m12)
  ctx.drawImage(img, 0, 0)
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  // 竖直参考线 (中线)
  ctx.strokeStyle = 'rgba(180,180,180,0.8)'; ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(R.newW / 2, 0); ctx.lineTo(R.newW / 2, R.newH); ctx.stroke()
  // ROI 框 (绿)
  ctx.strokeStyle = '#22c55e'; ctx.lineWidth = 2
  ctx.strokeRect(roiFrac.fx * R.newW, roiFrac.fy * R.newH, roiFrac.fw * R.newW, roiFrac.fh * R.newH)
  // 干参考区框 (橙, 对齐后端叠加色 BGR(0,128,255))
  if (dry.on) {
    ctx.strokeStyle = '#ff8000'; ctx.lineWidth = 2
    ctx.strokeRect(dry.fx * R.newW, dry.fy * R.newH, dry.fw * R.newW, dry.fh * R.newH)
  }
  // 交互中的画线 / 拖框 (拖框过程色随目标: 绿框琥珀 / 橙框橙)
  if (lineP0 && lineCur) {
    ctx.strokeStyle = '#d946ef'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(lineP0.x, lineP0.y); ctx.lineTo(lineCur.x, lineCur.y); ctx.stroke()
  }
  if (boxDrag0 && boxDragCur) {
    ctx.strokeStyle = tool.value === 'dry' ? '#ff8000' : '#f59e0b'; ctx.lineWidth = 1
    ctx.strokeRect(Math.min(boxDrag0.x, boxDragCur.x), Math.min(boxDrag0.y, boxDragCur.y),
      Math.abs(boxDragCur.x - boxDrag0.x), Math.abs(boxDragCur.y - boxDrag0.y))
  }
}

function evtPos(e) {
  // 手势中用 pointerdown 缓存的矩形换算 (拖动期间布局不变); 手势外兜底现取
  const r = dragRect || canvas.value.getBoundingClientRect()
  // 画布 CSS 尺寸可能被缩放 → 换算回画布像素
  const sx = canvas.value.width / r.width, sy = canvas.value.height / r.height
  return { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy }
}

// move 重绘经 rAF 节流: 指针事件频率可高于刷新率, 一帧至多重绘一次
function scheduleDraw() {
  if (rafId) return
  rafId = requestAnimationFrame(() => { rafId = 0; draw() })
}
function cancelScheduledDraw() {
  if (rafId) { cancelAnimationFrame(rafId); rafId = 0 }
}

// 手势收口 (落定/丢弃共用): 清指针与缓存, 撤 window 兜底监听
function settleGesture() {
  activePointerId = null
  dragRect = null
  cancelScheduledDraw()
  window.removeEventListener('pointerup', onUp)
}

function onDown(e) {
  if (e.button !== 0) return      // 只认主键/主指针, 具体动作由「左键工具」决定
  if (activePointerId !== null) return   // 已有在途手势 (多指第二指): 忽略
  activePointerId = e.pointerId
  dragRect = canvas.value.getBoundingClientRect()
  const p = evtPos(e)
  if (tool.value === 'line') {    // 画竖直边 → 摆正
    lineP0 = p; lineCur = p
  } else {                        // 拖框 → 落到绿框或橙框
    boxDrag0 = p; boxDragCur = p
  }
  // 捕获指针: 画布外松手 pointerup 也必达本元素 (修"画布外松手拖拽卡死")
  try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 捕获失败: 靠 window 兜底 */ }
  window.addEventListener('pointerup', onUp)   // 兜底: 捕获不生效的环境也能收口
}
function onMove(e) {
  if (activePointerId === null || e.pointerId !== activePointerId) return
  if (!lineP0 && !boxDrag0) return
  const p = evtPos(e)
  if (boxDrag0) boxDragCur = p; else lineCur = p
  scheduleDraw()
}
function onUp(e) {
  if (activePointerId === null || e.pointerId !== activePointerId) return
  settleGesture()
  if (lineP0 && lineCur) {
    const dx = lineCur.x - lineP0.x, dy = lineCur.y - lineP0.y
    if (Math.abs(dx) + Math.abs(dy) >= 5) {
      angle.value = Math.max(-45, Math.min(45, angle.value + angleToMakeLineVertical(dx, dy)))
    }
    lineP0 = lineCur = null
  }
  if (boxDrag0 && boxDragCur) {
    const x = Math.min(boxDrag0.x, boxDragCur.x), y = Math.min(boxDrag0.y, boxDragCur.y)
    const w = Math.abs(boxDragCur.x - boxDrag0.x), h = Math.abs(boxDragCur.y - boxDrag0.y)
    if (w >= 3 && h >= 3) {
      const t = tool.value === 'dry' ? dry : roiFrac
      t.fx = +(x / rotSize.w).toFixed(4); t.fy = +(y / rotSize.h).toFixed(4)
      t.fw = +(w / rotSize.w).toFixed(4); t.fh = +(h / rotSize.h).toFixed(4)
      if (tool.value === 'dry') dry.on = true
    }
    boxDrag0 = boxDragCur = null
  }
  draw()
}
// 手势被系统取消 (触屏中断/窗口切换) 或捕获意外丢失: 丢弃本次交互不落任何改动。
// lostpointercapture 在正常 pointerup 后也会触发, 届时 activePointerId 已清, 守卫使其无害。
function onCancel(e) {
  if (activePointerId === null || e.pointerId !== activePointerId) return
  settleGesture()
  lineP0 = lineCur = null
  boxDrag0 = boxDragCur = null
  draw()
}

function freezeFrame() {
  msg.value = '取帧中…'
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => { rawImg.value = img; msg.value = ''; nextTick(draw) }
  img.onerror = () => { msg.value = '取帧失败 (通道未激活/离线)' }
  // 加时间戳绕缓存, 拉一张最新原始帧
  img.src = wlFrameUrl('ch' + props.channel) + '?t=' + Date.now()
}

async function save() {
  // danger-ack: 保存即作废参考图 (检测基线), 强制勾选防"顺手点掉"
  if (!(await confirmAction({
    level: 'danger-ack',
    title: '保存液位标定',
    message: '保存后现有参考图将失效, 需重新采集。',
    ackText: '我知道需要重新采集参考图',
    confirmText: '保存标定',
  }))) return
  msg.value = ''
  try {
    await api.wlCmd('set_calibration', {
      channel: props.channel,
      rotation_angle_deg: +angle.value.toFixed(3),
      roi_frac: [roiFrac.fx, roiFrac.fy, roiFrac.fw, roiFrac.fh],
      flow_direction: flow.value,
      // seed 在先 (loadCalib), UI 态即全量真值: 数组=设置, null=清除
      dry_ref_frac: dry.on ? [dry.fx, dry.fy, dry.fw, dry.fh] : null,
      save: true,
    })
    msg.value = '标定已保存 ✓ (参考图已失效, 请重新采集)'
  } catch (e) { msg.value = '保存失败: ' + errText(e) }
}

async function captureRef() {
  msg.value = ''
  try {
    await api.wlCmd('capture_reference', { channel: props.channel })
    msg.value = '已采集参考干板图 ✓'
  } catch (e) { msg.value = '采参考失败: ' + errText(e) }
}

function onRoiInput() { draw() }   // 数值改动 → 重绘框 (数值↔框双向)
function onDryInput() { dry.on = true; draw() }   // 手输干区数值即视为启用
function clearDry() { dry.on = false; draw() }
function onAngleInput() {
  // v-model.number 空输入时为 '' → 跳过; 钳位与画线路径一致 ±45
  if (typeof angle.value !== 'number' || !Number.isFinite(angle.value)) return
  angle.value = Math.max(-45, Math.min(45, angle.value))
  draw()
}

async function loadCalib() {
  // 预加载该通道已存标定作初值, 避免保存时用默认值覆盖 (与整定台 seed 一致)
  try {
    const r = await api.wlCmd('get_calibration', { channel: props.channel })
    const c = r?.calib || {}
    if (c.rotation_angle_deg != null) angle.value = c.rotation_angle_deg
    if (Array.isArray(c.roi_frac) && c.roi_frac.length === 4) {
      roiFrac.fx = c.roi_frac[0]; roiFrac.fy = c.roi_frac[1]
      roiFrac.fw = c.roi_frac[2]; roiFrac.fh = c.roi_frac[3]
    }
    if (c.flow_direction) flow.value = c.flow_direction
    if (Array.isArray(c.dry_ref_frac) && c.dry_ref_frac.length === 4) {
      dry.fx = c.dry_ref_frac[0]; dry.fy = c.dry_ref_frac[1]
      dry.fw = c.dry_ref_frac[2]; dry.fh = c.dry_ref_frac[3]
      dry.on = true
    } else {
      dry.on = false
    }
  } catch (e) { /* 离线/未就绪: 用默认初值 */ }
}

onMounted(async () => { if (props.online) { await loadCalib(); freezeFrame() } })
onBeforeUnmount(() => {
  cancelScheduledDraw()
  window.removeEventListener('pointerup', onUp)   // 手势中途卸载: 撤兜底监听
})
</script>

<template>
  <div class="calib">
    <!-- pointer 事件 (兼容触屏): down 时 setPointerCapture, 画布外松手 up 仍必达; cancel/lostcapture 清态 -->
    <div class="calib-canvas-wrap"
         @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp"
         @pointercancel="onCancel" @lostpointercapture="onCancel" @contextmenu.prevent>
      <canvas ref="canvas" class="calib-canvas" role="img" aria-label="液位 ROI 标定画布"></canvas>
      <div v-if="!rawImg" class="calib-empty">{{ online ? '点「重新取帧」拉一张冻结帧' : '设备离线' }}</div>
    </div>
    <Teleport to="#wl-calib-panel">
      <div class="calib-ctrl">
        <div class="panel-head">标定控制</div>
        <div class="row">
          <button @click="freezeFrame" :disabled="!online">重新取帧</button>
          <button class="primary" @click="save" :disabled="!online">保存标定</button>
          <button @click="captureRef" :disabled="!online">采集参考图</button>
        </div>
        <div class="row"><label>旋转角</label>
          <input class="ang" type="number" step="0.05" min="-45" max="45"
                 v-model.number="angle" @input="onAngleInput" /><span class="unit">°</span>
          <button class="mini" @click="angle = 0; draw()">归零</button>
        </div>
        <div class="row"><label>流向</label>
          <select v-model="flow">
            <option v-for="f in FLOWS" :key="f" :value="f">{{ f }}</option>
          </select>
        </div>
        <div class="row"><label>左键工具</label>
          <button class="mini tgt roi-tgt" :class="{ on: tool === 'roi' }"
                  @click="tool = 'roi'">框检测区(绿)</button>
          <button class="mini tgt dry-tgt" :class="{ on: tool === 'dry' }"
                  @click="tool = 'dry'">框干参考区(橙)</button>
          <button class="mini tgt line-tgt" :class="{ on: tool === 'line' }"
                  @click="tool = 'line'">画摆正线</button>
        </div>
        <div class="row roi">
          <label>fx<input type="number" step="0.001" v-model.number="roiFrac.fx" @input="onRoiInput" /></label>
          <label>fy<input type="number" step="0.001" v-model.number="roiFrac.fy" @input="onRoiInput" /></label>
          <label>fw<input type="number" step="0.001" v-model.number="roiFrac.fw" @input="onRoiInput" /></label>
          <label>fh<input type="number" step="0.001" v-model.number="roiFrac.fh" @input="onRoiInput" /></label>
        </div>
        <div class="row roi">
          <label>dfx<input type="number" step="0.001" v-model.number="dry.fx" @input="onDryInput" /></label>
          <label>dfy<input type="number" step="0.001" v-model.number="dry.fy" @input="onDryInput" /></label>
          <label>dfw<input type="number" step="0.001" v-model.number="dry.fw" @input="onDryInput" /></label>
          <label>dfh<input type="number" step="0.001" v-model.number="dry.fh" @input="onDryInput" /></label>
          <button class="mini" @click="clearDry">清除干区</button>
          <span class="dry-state" :class="{ on: dry.on }">{{ dry.on ? '已设' : '未设' }}</span>
        </div>
        <p class="hint">左键拖 = 执行当前「左键工具」; 选「画摆正线」时沿板竖直边拖一条线, 松手即按该线摆正。</p>
        <p class="hint">保存标定会使参考图失效, 保存后请重新采集参考图。</p>
        <p v-if="msg" class="msg">{{ msg }}</p>
        <p class="muted">roi_frac 为分辨率无关比例, 跨通道可直接抄同值 (为将来统一液位阈值触发打一致性地基)。</p>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.calib { display: block; }
/* 画布自适应放大: 宽度吃满左栏, 高度按帧长宽比自算 (canvas 为替换元素, height:auto 保比例)。
   不用 object-fit 信箱缩放 — evtPos 以 canvas.width/rect.width 线性映射, 信箱会错位鼠标坐标 */
/* touch-action: none — 框选/画线手势自管, 不让浏览器把触摸吃成滚动/缩放 */
.calib-canvas-wrap { position: relative; background: #0b0f14; border-radius: 6px; min-height: 160px; touch-action: none; }
.calib-canvas { display: block; width: 100%; height: auto; cursor: crosshair; border-radius: 6px; touch-action: none; }
.calib-empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #cbd5e1; font-size: var(--fs-13); }
.calib-ctrl { display: flex; flex-direction: column; gap: 8px; }
.panel-head { font-weight: 600; border-top: 1px solid var(--border); padding-top: 10px; margin-top: 12px; }
.calib-ctrl .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.calib-ctrl label { font-size: var(--fs-12); color: var(--subtle); font-weight: 600; }
.calib-ctrl .roi label { display: inline-flex; flex-direction: column; }
.calib-ctrl .roi input { width: 64px; }
.calib-ctrl .ang { width: 76px; }
.unit { color: var(--subtle); }
.calib-ctrl button { padding: 4px 12px; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; border-radius: var(--radius-sm); }
.calib-ctrl button.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.calib-ctrl button.mini { padding: 2px 8px; font-size: var(--fs-12); }
.calib-ctrl button:disabled { opacity: .5; cursor: not-allowed; }
/* 左键工具 toggle: 选中态描该工具在画布上的颜色, 按钮色即所画之物的颜色 */
.tgt.on.roi-tgt { border-color: #22c55e; color: #22c55e; font-weight: 600; }
.tgt.on.dry-tgt { border-color: #ff8000; color: #ff8000; font-weight: 600; }
.tgt.on.line-tgt { border-color: #d946ef; color: #d946ef; font-weight: 600; }
.dry-state { font-size: var(--fs-12); color: var(--muted); }
.dry-state.on { color: #ff8000; font-weight: 600; }
.hint { font-size: var(--fs-12); color: var(--muted); }
.msg { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); }
.muted { color: var(--muted); font-size: var(--fs-12); }
</style>
