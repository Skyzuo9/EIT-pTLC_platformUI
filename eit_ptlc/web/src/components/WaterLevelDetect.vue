<script setup>
// 液位单路「识别」页签: 检测叠加图 + 走势曲线 + 检测健康数值。
// 回答的问题是"算法到底把哪些像素当成湿了、前沿判在哪、这数字能不能信"——
// 「实时」页签给的是原始帧 (10fps, 好看但看不出识别), 这里给的是渲染帧 (随检测周期 ~2s,
// 慢但与读数严格同出一帧, 见后端 render_debug_frame 的口径约定)。
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { api, wlDebugFrameUrl } from '../api'
import { useFramePoll } from '../composables/framePoll'
import { usePoll } from '../composables/usePoll.js'
import { wlReasonLabel, wlFrozenLabel } from '../wlStatus'

const props = defineProps({
  channel: { type: Number, required: true },
  chData: { type: Object, default: null },
  params: { type: Object, default: null },
  online: { type: Boolean, default: false },
})

// 叠加图轮询 2s: 与后端检测周期 2s 对齐 (原 1s 是 2× 过采样 —— 再快也拿不到新内容, 只是白跑渲染)
const DEBUG_POLL_MS = 2000
const HISTORY_POLL_MS = 2000

// 就地叠加开关: 关掉板面不着色, 与开启态对照即可看出算法判的边界与真实干湿边界差多少 ——
// 这是"识别效果怎么样"最直接的判法, 故默认开 (默认关等于又退回"看不见识别结果")。
const showOverlay = ref(true)

const { state: frame, start: startPoll, stop: stopPoll } = useFramePoll(
  () => wlDebugFrameUrl('ch' + props.channel, showOverlay.value),
  DEBUG_POLL_MS, `CH${props.channel}-识别`)

// 切换后立刻重取一帧 (start() 内部会先跑一次 attempt), 否则要等下一轮才变, 对照就断了
function toggleOverlay() {
  stopPoll()
  startPoll()
}

// 图例: 颜色须与后端 waterlevel_detector 的 _VIS_* 常量一一对应, 改一侧须同步另一侧。
// dim=true 的项在叠加关闭时置灰 —— 避免"图例说有、画面上没有"的自相矛盾。
const LEGEND = computed(() => [
  { color: '#ffff00', text: 'ROI 全框', dim: false },
  { color: '#00ff00', text: '有效检测区 (裁剪后)', dim: false },
  { color: '#ff8000', text: '干参考区', dim: false },
  { color: '#ff0000', text: '判为浸润的像素 (半透明红)', dim: !showOverlay.value },
  { color: '#00a0ff', text: '前沿线', dim: !showOverlay.value },
])

// 检测健康数值: 这些字段后端 snapshot 一直有, 但此前页面从不显示
const health = computed(() => {
  const d = props.chData || {}
  const fmt = (v, n = 3) => (v == null ? '—' : Number(v).toFixed(n))
  return [
    ['掩膜浸润比 (诊断)', fmt(d.wet_ratio, 4)],
    ['差分强度 diff_mean', fmt(d.diff_mean, 4)],
    // 判湿线 = 前沿判定比例 × A, 故 A 是本口径的核心可观测量: 真机常态 0.07~0.10,
    // 它漂而前沿位置不漂, 才说明相对幅值化生效了
    ['湿平台幅值 A', fmt(d.amplitude, 4)],
    ['照度增益 gain', fmt(d.gain, 4)],
    ['信号', d.valid ? '有效' : wlReasonLabel(d.reason)],
    ['观测时刻', d.observed_at ? String(d.observed_at).slice(11, 19) + ' UTC' : '—'],
  ]
})

// 无参考图 → detect_level 走 Otsu 回退, valid 仍为 true 但数值不可采信 (与 wait_level 的
// config:no_reference 判据同源)。不显著警告的话, 本页面自己就会变成误判来源。
const noRef = computed(() => props.chData && props.chData.has_ref === false)

// ---- 走势曲线 (手写 SVG, 项目无图表库且惯例为零依赖手绘) ----
const points = ref([])

async function loadHistory() {
  try {
    const r = await api.wlHistory(props.channel)
    points.value = r?.points || []
  } catch (e) { /* 离线/未就绪: 保持上次曲线, 不清空 */ }
}
const histPoll = usePoll(loadHistory, HISTORY_POLL_MS)

// viewBox 宽度跟随图区容器的**真实 CSS 像素宽** (下方 ResizeObserver 维护), 使用户坐标系
// 与像素恒 1:1。这是文字不被拉伸的前提: 早先 VB_W 写死 640 而元素宽 1741, 配
// preserveAspectRatio="none" 就是横向 2.72×、纵向 1× 的非等比缩放, <text> 字形被抻扁
// (线条没露馅只因 vector-effect: non-scaling-stroke 保护了描边宽度 —— 它管不到字形)。
const chartBox = ref(null)
const vbW = ref(640)      // 初值仅用于首帧, 挂载后立刻被实测宽覆盖
const VB_H = 180
const PAD_L = 30
const PAD_R = 8
const PAD_T = 8
const PAD_B = 18
const PLOT_W = computed(() => Math.max(1, vbW.value - PAD_L - PAD_R))
const PLOT_H = VB_H - PAD_T - PAD_B
let chartRO = null

// x 按真实时间排布 (非索引): 通道停采/服务重启造成的时间空洞要如实拉开, 不能被压平
const timeSpan = computed(() => {
  const pts = points.value
  if (pts.length < 2) return null
  const t0 = Date.parse(pts[0].t)
  const t1 = Date.parse(pts[pts.length - 1].t)
  if (!Number.isFinite(t0) || !Number.isFinite(t1) || t1 <= t0) return null
  return { t0, span: t1 - t0 }
})

function xOf(pt, i) {
  const ts = timeSpan.value
  if (ts === null) {
    const n = Math.max(1, points.value.length - 1)
    return PAD_L + (i / n) * PLOT_W.value
  }
  return PAD_L + ((Date.parse(pt.t) - ts.t0) / ts.span) * PLOT_W.value
}
function yOf(v) {
  return PAD_T + (1 - Math.min(Math.max(v, 0), 100) / 100) * PLOT_H
}

// 无效点断开成多段 (不跨断口连线 —— 中断/等待前沿本身就是要看的信息, 抹平即失真)
function segmentsOf(key) {
  const segs = []
  let cur = []
  points.value.forEach((pt, i) => {
    const v = pt[key]
    if (pt.valid && v != null) {
      cur.push(`${xOf(pt, i).toFixed(1)},${yOf(v).toFixed(1)}`)
    } else if (cur.length) {
      segs.push(cur)
      cur = []
    }
  })
  if (cur.length) segs.push(cur)
  return segs.filter((s) => s.length > 1).map((s) => s.join(' '))
}
const frontSegs = computed(() => segmentsOf('front_percent'))

// T2/T1 阈值线与曲线同量纲: 页面上只剩 front_percent 这一个读数 (见 waterlevel_trigger)
const t2 = computed(() => {
  const v = props.params?.trigger_percent_t2
  return v == null ? null : Number(v)
})
const t1 = computed(() => {
  const off = props.params?.t1_offset
  return t2.value == null || off == null ? null : t2.value - Number(off)
})

const gridLines = [0, 25, 50, 75, 100]
const hasCurve = computed(() => frontSegs.value.length > 0)

onMounted(() => {
  startPoll()
  histPoll.start()
  // 图区宽度随窗口/左右栏分隔条变化, 必须持续跟随而非只量一次, 否则拉伸会随下次改宽卷土重来
  if (chartBox.value) {
    chartRO = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) vbW.value = w
    })
    chartRO.observe(chartBox.value)
  }
})
onBeforeUnmount(() => {
  stopPoll()
  if (chartRO !== null) chartRO.disconnect()
})
</script>

<template>
  <div class="det">
    <!-- role=alert: "数值不可采信"是正确性关键警告, 出现即打断播报 -->
    <p v-if="noRef" class="warn-bar" role="alert">
      未采集参考图 · 当前走 Otsu 回退, 数值不可采信 — 请先在右侧「采集参考图」拍干板
    </p>

    <label class="ov-toggle">
      <input type="checkbox" v-model="showOverlay" @change="toggleOverlay" />
      显示识别叠加
      <span class="ov-hint">关掉可看未着色的真实板面, 与开启态对照即知判得准不准</span>
    </label>

    <div class="vid">
      <img v-if="frame.src" :src="frame.src" :alt="'CH' + channel + ' 识别叠加图'" />
      <div v-else class="noimg">{{ online ? '等待检测帧…' : '设备离线 — 无识别画面' }}</div>
      <span v-if="frame.src && frame.stale" class="vid-stale">信号中断 · 保持最后画面</span>
    </div>

    <div class="legend">
      <span v-for="l in LEGEND" :key="l.text" class="lg" :class="{ dim: l.dim }">
        <i :style="{ background: l.color }"></i>{{ l.text }}
      </span>
    </div>

    <!-- 走势与检测健康并排: 表格自然宽仅 ~228px 而图占满整栏, 上下堆叠白白多占约 176px 高 -->
    <div class="trend-row">
      <div class="trend-col">
        <div class="sect-head">走势 (近 30 分钟)</div>
        <!-- ref 给 ResizeObserver 量真实像素宽 (见 vbW): 图区宽 == viewBox 宽 才不拉伸字 -->
        <div class="chart" ref="chartBox">
          <!-- preserveAspectRatio="none" 在 vbW==渲染宽 时是恒等变换, 故保留: resize 与观察者
               回调差一帧时它只瞬时轻微拉伸, 而默认的 meet 会把整张图缩成信箱式跳一下 -->
          <svg :viewBox="`0 0 ${vbW} ${VB_H}`" preserveAspectRatio="none" class="svg"
               role="img" aria-label="液位走势图 (含阈值线)">
            <!-- 网格 + y 轴刻度 -->
            <g>
              <template v-for="g in gridLines" :key="g">
                <line :x1="PAD_L" :y1="yOf(g)" :x2="vbW - PAD_R" :y2="yOf(g)" class="grid" />
                <text :x="PAD_L - 4" :y="yOf(g) + 3" class="tick">{{ g }}</text>
              </template>
            </g>
            <!-- T2/T1 阈值线 (与下面的 front% 曲线同量纲) -->
            <template v-if="t2 !== null">
              <line :x1="PAD_L" :y1="yOf(t2)" :x2="vbW - PAD_R" :y2="yOf(t2)" class="thr t2" />
              <text :x="vbW - PAD_R - 2" :y="yOf(t2) - 3" class="thr-lbl t2-lbl">T2 {{ t2 }}</text>
            </template>
            <template v-if="t1 !== null">
              <line :x1="PAD_L" :y1="yOf(t1)" :x2="vbW - PAD_R" :y2="yOf(t1)" class="thr t1" />
              <text :x="vbW - PAD_R - 2" :y="yOf(t1) - 3" class="thr-lbl t1-lbl">T1 {{ t1 }}</text>
            </template>
            <!-- 数据线: front% (唯一读数真源) -->
            <polyline v-for="(s, i) in frontSegs" :key="'f' + i" :points="s" class="ln front" />
          </svg>
          <p v-if="!hasCurve" class="empty-curve">暂无有效走势点 (等待检测产出)</p>
        </div>
        <div class="legend">
          <span class="lg"><i class="ln-swatch front-sw"></i>前沿线 front% (T1/T2 比的就是它)</span>
        </div>
      </div>

      <div class="health-col">
        <div class="sect-head">检测健康</div>
        <table class="readout">
          <tbody>
            <tr v-for="[k, v] in health" :key="k">
              <th>{{ k }}</th>
              <td>
                {{ v }}
                <span v-if="k.startsWith('照度增益') && chData && chData.gain_frozen" class="frozen">已冻结{{ chData.gain_frozen_reason ? ' · ' + wlFrozenLabel(chData.gain_frozen_reason) : '' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <p class="muted">
      叠加图与读数同出一帧 (随检测周期 ~2s 更新)。要看流畅原始画面请切「实时」页签。
      增益「已冻结」= 干区将被/已被前沿打湿, 守卫改用最后一次可信增益, 属正常保护。
      若干区照度一拍突变 (光照真变了), 守卫不冻结而是跟上新增益, 并把该拍记为
      「照度突变(已弃帧)」—— 曲线上表现为一个断口。
    </p>
  </div>
</template>

<style scoped>
.det { display: flex; flex-direction: column; }
/* 图像井: 与「实时」页签同规格 (暗底在深浅主题下均为暗, 故保留字面量, 主题无关) */
/* 4:3 锁定自 config/app.yaml camera.cap_width/height=640×480; 后端提 1280×720 时同步改 */
.vid { background: #0b0f14; aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center; border-radius: 6px; position: relative; }
.vid img { width: 100%; height: 100%; object-fit: contain; }
.noimg { color: #cbd5e1; }
.vid-stale { position: absolute; top: 6px; left: 6px; font-size: var(--fs-11); font-weight: 600; padding: 2px 8px; border-radius: 8px; background: rgba(220, 38, 38, .85); color: #fff; }
.warn-bar { margin: 0 0 8px; padding: 5px 10px; border-radius: 4px; font-size: var(--fs-12); font-weight: 600; background: var(--bad-soft); color: var(--bad-strong); border: 1px solid var(--bad); }
.ov-toggle { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: var(--fs-12); font-weight: 600; color: var(--text); cursor: pointer; flex-wrap: wrap; }
.ov-toggle input { cursor: pointer; }
.ov-hint { font-weight: 400; color: var(--muted); }
.legend { display: flex; gap: 12px; flex-wrap: wrap; margin: 6px 0 0; font-size: var(--fs-12); color: var(--subtle); }
.lg { display: inline-flex; align-items: center; gap: 4px; }
.lg i { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
/* 叠加关闭时置灰对应图例项: 图例说有而画面没有会让人以为是检测挂了 */
.lg.dim { opacity: .35; text-decoration: line-through; }
.ln-swatch { width: 16px; height: 0; border-top-width: 2px; border-radius: 0; }
.front-sw { border-top-style: solid; border-top-color: #00a0ff; }
.sect-head { font-weight: 600; margin: 12px 0 6px; border-top: 1px solid var(--border); padding-top: 10px; }
/* 走势 | 检测健康 并排; 左栏窄到放不下时 wrap 回上下堆叠 */
.trend-row { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
/* min-width: 0 必须有 —— flex 子项默认 min-width: auto, 不给 0 则内部 svg (width: 100%)
   会把这一列撑住不肯收缩, 左栏一窄整行就横向溢出 */
.trend-col { flex: 1 1 320px; min-width: 0; }
/* 表格自然宽实测 228px; 不参与拉伸, 横向余量全让给图 */
.health-col { flex: 0 0 auto; }
.chart { position: relative; }
.svg { width: 100%; height: 180px; display: block; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; }
.grid { stroke: var(--border-soft); stroke-width: 1; vector-effect: non-scaling-stroke; }
.tick { fill: var(--muted); font-size: var(--fs-11); text-anchor: end; font-family: var(--font-mono); }
.thr { stroke-width: 1; stroke-dasharray: 5 4; vector-effect: non-scaling-stroke; }
.t2 { stroke: var(--bad); }
.t1 { stroke: var(--warn); }
.thr-lbl { font-size: var(--fs-11); text-anchor: end; font-family: var(--font-mono); }
.t2-lbl { fill: var(--bad-strong); }
.t1-lbl { fill: var(--warn-strong); }
.ln { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.front { stroke: #00a0ff; }
.empty-curve { position: absolute; top: 50%; left: 0; right: 0; transform: translateY(-50%); text-align: center; color: var(--muted); font-size: var(--fs-12); margin: 0; }
.readout { border-collapse: collapse; }
.readout th { text-align: right; padding: 2px 12px 2px 0; color: var(--subtle); font-weight: 600; white-space: nowrap; }
.readout td { padding: 2px 0; font-family: var(--font-mono); }
.frozen { margin-left: 6px; font-family: var(--font-ui); font-size: var(--fs-11); font-weight: 600; padding: 1px 6px; border-radius: 8px; background: var(--warn-soft); color: var(--warn-strong); }
.muted { color: var(--muted); font-size: var(--fs-12); margin-top: 8px; }
</style>
