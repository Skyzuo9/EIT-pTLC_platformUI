<!--
  功能: 三维页底部唯一的一条时间线 —— 墙钟录像 + 工位利用率 + 动作甘特泳道.

  它由原来并列的两条合并而来: 上面那条是墙钟录像回放, 下面那条是按**步骤下标**跳转的
  索引条(拖动只高亮工位, 不重演任何状态)。两条都叫"回放", 用户要在两个入口之间猜。
  现在以录像为基础合成一条, 名字就叫时间线。

  "实时"不是一个模式, 而是**时间轴的最右端**: 默认贴着右缘跟随, 一旦拖走就自动进入
  回放, 旁边出现「回到实时」。这与监控录像机的心智一致, 也省掉一次模式切换。

  版式的要点是**左名条 + 右时间区**: 利用率条、刻度、动作泳道三者共用同一套 x 映射,
  于是播放头那一条竖线扫过几个色块, 就是那一刻有几件事在跑。原先动作是右侧一个独立
  列表, 与时间轴没有任何对应关系 —— 而后续是并行流程, 列表根本读不出"同时有几件事"。
-->
<template>
  <div class="tl" :class="{ 'tl--replay': replaying, 'tl--open': expanded }">
    <!-- ── 工具栏 ─────────────────────────────────────────────── -->
    <div class="tl__bar">
      <button class="tl__toggle" :title="expanded ? '收起时间线' : '展开时间线'"
              @click="expanded = !expanded">
        {{ expanded ? '▾' : '▴' }} 时间线
      </button>

      <button class="tl__btn" :title="playing ? '暂停 (空格)' : '播放 (空格)'"
              @click="togglePlay">{{ playing ? '⏸' : '▶' }}</button>
      <button class="tl__btn" title="后退 10 秒 (←)" @click="nudge(-10)">⏪</button>
      <button class="tl__btn" title="前进 10 秒 (→)" @click="nudge(10)">⏩</button>

      <select v-model.number="speed" class="tl__speed" title="播放倍速 (J / L)"
              @change="applySpeed">
        <option v-for="s in SPEEDS" :key="s" :value="s">{{ s }}×</option>
      </select>

      <span class="tl__clock" :title="`播放头 ${formatClock(playhead, true)}`">
        {{ formatClock(playhead, true) }}
      </span>

      <button class="tl__btn" :class="{ on: loop }" title="A-B 循环 (A 标起点 / B 标终点)"
              @click="clearLoop">{{ loopLabel }}</button>

      <input v-model="jumpText" class="tl__jump" type="datetime-local" step="1"
             title="跳到确切时刻" @keydown.enter.stop.prevent="jumpToInstant">
      <button class="tl__btn" title="跳转" @click="jumpToInstant">跳转</button>

      <button v-if="replaying" class="tl__btn tl__btn--live" title="回到实时 (End)"
              @click="backToLive">⟲ 回到实时</button>

      <span class="tl__spacer" />
      <span v-if="lastError" class="tl__err" :title="lastError">{{ lastError }}</span>
      <span class="tl__now" :title="currentTitle">{{ currentText }}</span>
      <span class="tl__rec" :class="recClass" :title="recTitle">{{ recText }}</span>
    </div>

    <!-- ── 左名条 + 右时间区 (各行共用同一套 x 映射) ──────────── -->
    <div v-if="expanded" class="tl__body">
      <div class="tl__names">
        <div class="tl__name tl__name--track"
             title="上半: 每桶有几个工位在动 / 共 9 个模块; 下半: 整段录像总览, 框住的是当前视窗">
          利用率
        </div>
        <div class="tl__name tl__name--axis" />
        <button class="tl__lanes-toggle" :title="lanesOpen ? '收起动作泳道' : '展开动作泳道'"
                @click="lanesOpen = !lanesOpen">
          {{ lanesOpen ? '▾' : '▸' }} 动作 {{ lanes.total }}
        </button>
        <template v-if="lanesOpen">
          <div v-for="lane in lanes.lanes" :key="lane.runId" class="tl__name tl__name--run"
               :class="{ 'tl__name--failed': lane.failed }"
               :style="{ height: laneHeight(lane) }" :title="`${lane.label} · ${lane.count} 步`"
               @click="toggleRun(lane.runId)">
            {{ lane.collapsed ? '▸' : '▾' }} {{ lane.label }}
          </div>
        </template>
      </div>

      <div ref="timeRef" class="tl__time" @wheel.prevent="onWheel"
           @pointerdown="onPointerDown">
        <div class="tl__track">
          <!-- 上半: 利用率 —— 柱高 = 在动的工位数 / 模块总数; 空闲留基线, 未补算走底纹 -->
          <div class="tl__track-util">
            <div class="tl__density">
              <i v-for="(bar, i) in heights" :key="i" class="tl__bar-i"
                 :class="{ 'tl__bar-i--unknown': bar.unknown, 'tl__bar-i--gap': bar.gap,
                           'tl__bar-i--idle': !bar.unknown && !bar.gap && !bar.count }"
                 :style="{ height: bar.height + '%' }" :title="barTitle(bar)" />
            </div>
            <!-- 尚未落盘的一段: coverage 取的是已落盘块的 MAX(t1), 拖进去 state_at 会 404 -->
            <i v-if="pendingZone" class="tl__pending" :style="pendingZone" title="尚未落盘" />
            <i v-if="loopBand" class="tl__loop" :style="loopBand" title="A-B 循环区间" />
            <i v-for="m in markers" :key="m.ts + m.kind" class="tl__mark"
               :style="{ left: pct(m.offset), background: m.color }"
               :title="`${formatClock(m.ts, true)}  ${m.label}`"
               @click.stop="seekTo(m.ts)" />
          </div>
          <!-- 下半: 总览 —— 始终是整段录像(x 映射是总览取数窗, 与上半的视窗坐标系**不同**)。
               视窗框随缩放当场变大变小, "缩了多少"由它回答。拖框身平移 / 拖两端改跨度。
               不透明底 + 更高 z-index: 播放头光标(视窗坐标)从它后面穿过, 不在错误的
               x 位置划破总览; 总览自带迷你播放头(全程坐标)。 -->
          <div ref="overviewRef" class="tl__overview" @pointerdown.stop="onOverviewDown">
            <div class="tl__density">
              <i v-for="(bar, i) in overviewHeights" :key="i" class="tl__bar-i"
                 :class="{ 'tl__bar-i--gap': bar.gap, 'tl__bar-i--idle': !bar.gap && !bar.count }"
                 :style="{ height: bar.height + '%' }" />
            </div>
            <i class="tl__vp" :style="viewportBox"
               :title="`当前视窗 ${formatSpan(spanS)} —— 拖动平移, 拖两端改跨度`">
              <i class="tl__vp-h tl__vp-h--l" /><i class="tl__vp-h tl__vp-h--r" />
            </i>
            <i v-show="overviewCursorOffset >= 0 && overviewCursorOffset <= 1"
               class="tl__ov-cursor" :style="{ left: pct(overviewCursorOffset) }" />
          </div>
        </div>

        <div class="tl__axis">
          <span v-for="(t, i) in ticks" :key="i" :style="{ left: pct(t.offset) }">
            {{ formatClock(t.t, spanS > 86400) }}
          </span>
        </div>

        <div class="tl__lanes-gap" />
        <template v-if="lanesOpen">
          <div v-for="lane in lanes.lanes" :key="lane.runId" class="tl__lane"
               :style="{ height: laneHeight(lane) }">
            <div v-for="(row, i) in lane.rows" :key="i" class="tl__lane-row">
              <i v-for="(seg, j) in row" :key="j" class="tl__seg"
                 :class="{ 'tl__seg--failed': seg.failed, 'tl__seg--open': seg.open }"
                 :style="{ left: pct(seg.left), width: pct(seg.width) }"
                 :title="segTitle(lane, seg)" @pointerdown.stop @click.stop="pickSegment(seg)" />
            </div>
          </div>
        </template>

        <!-- 播放头贯穿到底: 它扫过几个色块, 就是那一刻有几件事在跑。
             视窗外必须隐藏: left 可以是几十倍容器宽, 撑出 scrollWidth 就是
             底部那条无意义横向滚动条的主犯 -->
        <i v-show="cursorOffset >= 0 && cursorOffset <= 1"
           class="tl__cursor" :style="{ left: pct(cursorOffset) }" />
      </div>
    </div>

    <div v-if="expanded" class="tl__hint">
      滚轮缩放 · 拖动擦洗 · 总览条拖框改跨度 · 空格播放 · ←→ 跳转 · A/B 标循环
      <span v-if="lanes.clipped" class="tl__warn">{{ lanes.clipped }} 个动作超出泳道未画</span>
      <span class="tl__span">{{ formatSpan(spanS) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { api } from '../../../api.js'
import {
  formatClock, formatSpan, layoutMarkers, utilizationHeights,
} from '../../replay/replayBarModel.js'
import {
  abLoopNext, actionsAt, axisTicksIn, clampWindow, followWindow, formatInstantInput,
  keyIntent, normalizeLoop, packActionLanes, panBy, parseInstant, pxToTime, snapToLive,
  timeToRatio, zoomAt,
} from '../../replay/timelineViewModel.js'

const props = defineProps({
  /** ReplayChannel 实例 (由 TwinView 建好传入) */
  channel: { type: Object, default: null },
  /** 实时事件流 —— 只用来取"当前动作"这一条即时信息 */
  stream: { type: Object, default: null },
  /** 设备清单里的工位表, 只用来把工位 key 译成中文名 */
  stations: { type: Array, default: () => [] },
})
const emit = defineEmits(['focus-station'])

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16]
/** 拖动多少像素才算拖动而不是点击(照抄 GanttChart 的判据) */
const DRAG_THRESHOLD_PX = 3
/** 一条子泳道的行高(px), 与样式里的 .tl__lane-row 必须一致 */
const LANE_ROW_PX = 13
/**
 * 视窗缓动的**总时长**(ms), 而不是每帧衰减系数。
 *
 * 缩放本来是瞬间跳变的, 眼睛读不出"跳到哪儿去了"; 给一小段缓动之后, 缩放被感知成一个
 * 连续动作, 与总览条上那个当场变大变小的视窗框一起, 才回答得了"我缩了多少"。
 *
 * 按时长而不是按帧衰减是硬要求: 后者在慢机器上会退化成"每隔几秒挪一大步"的爬行, 比
 * 不做动画还糟。实测无头软件渲染下整机场景的 rAF **4 秒才来一帧**, 指数衰减写法当场
 * 卡在半路(见 [[three-d-pixel-diff-validation-traps]] 里那一类环境)。按时长写的话, 慢到
 * 第一帧就已经超时, 于是直接一步到位 —— 该动画的时候动画, 动不起来的时候至少是对的。
 */
const VIEW_EASE_MS = 160
/** 总览缩略条的桶数。它画的是整段录像(可能几十天), 200 个桶够看出忙闲分布了。 */
const OVERVIEW_BUCKETS = 200
/** 总览条两端把手的命中宽度(px) */
const VP_HANDLE_PX = 6
/**
 * 覆盖区间右缘长了这么多秒才值得重取总览。bounds 右缘现已钉在落盘边界(约 10s 一跳),
 * 取 10 = 每跳重取一次 —— 200 个桶一请求, 十秒一次可忽略; 视窗框与总览柱的
 * x 映射按取数窗(overviewRange)算, 所以取数节奏只影响柱子新鲜度, 不再造成错位。
 */
const OVERVIEW_REFRESH_S = 10
/**
 * 实时右缘允许超出落盘边界的上限(秒)。右缘取 clamp(墙钟, 落盘边界, 边界+此值):
 * 健康录制时空白 ≈ 一个块(10s)且随墙钟平滑推进; 录制停摆/浏览器时钟漂移时空白
 * 封顶在这里, 而不是像过去拿裸墙钟当右缘 —— 那会让"利用率条右边一大片空白"
 * 随时间无限增长(2026-08-15 用户截图里的病)。
 */
const PENDING_MAX_S = 30
/** 拖把手时视窗的最小跨度(秒), 与 clampWindow 的下限同源 */
const MIN_VIEW_SPAN_S = 2

const expanded = ref(false)
const lanesOpen = ref(true)
const playing = ref(false)
const playhead = ref(0)
const speed = ref(1)
const lastError = ref('')
const jumpText = ref('')
const liveAction = ref('')
const liveActionTitle = ref('')
const rec = ref(/** @type {object|null} */ (null))
const coverage = ref({ t0: null, t1: null })
const density = shallowRef({ active: [], covered: [], stations: [], markers: [], modules_total: 9 })
/** 总览条的数据: 整段录像的粗粒度利用率, 与视窗无关, 只在覆盖区间变了才重取 */
const overview = shallowRef({ active: [], covered: [], stations: [], modules_total: 9 })
const actions = shallowRef([])
const collapsed = ref(new Set())
const loop = ref(/** @type {{a:number,b:number}|null} */ (null))
const loopMark = ref(/** @type {number|null} */ (null))
const timeRef = ref(null)
const overviewRef = ref(null)
/** 时间区实测像素宽 —— 泳道的窄段合并按它算, 猜一个值会让密集段要么糊要么爆 DOM */
const timePx = ref(800)

/**
 * 视窗(看哪一段) —— 与 clock.t0/t1(录像覆盖)是两回事。
 *
 * 这两个是**渲染中**的值, 缩放时会从旧值缓动到目标; 目标存在 target 里。取数一律按
 * 目标发起, 不跟每一帧动画走 —— 否则一次缩放要打十几个请求。
 */
const viewT0 = ref(0)
const viewT1 = ref(0)
const target = { t0: 0, t1: 0 }
let animRaf = 0
let easeTimer = 0
/**
 * 总览条当前画的是哪一段。**必须响应式**: 视窗框/迷你播放头/总览手势的 x 映射
 * 全按它算 —— 按 bounds 算的话, 取数与渲染两个窗一漂移(最多一个刷新周期),
 * 框就指错时刻。
 */
const overviewRange = ref({ t0: 0, t1: 0 })
/** 视窗右缘是否贴着实时边 */
const followLive = ref(true)
/** 视窗是否跟着播放头翻页 */
const followPlayhead = ref(true)

let poll = 0
let densityTimer = 0
let unsubscribe = null
let resizeObserver = null
let drag = null
let overviewDrag = null

/**
 * 是否处于回放态。**必须是 ref 而不是 computed**: channel 是普通对象, 刻意不进 Vue
 * 响应式(高频状态一律绕开代理, 见 TwinFeed 头注释), 所以 computed 读 channel.active
 * 永远不会被触发重算 —— 表现是拖完之后界面还一直显示"实时"。由 syncFromChannel 桥接。
 */
const replaying = ref(false)
const spanS = computed(() => Math.max(viewT1.value - viewT0.value, 0))
const view = computed(() => ({ t0: viewT0.value, t1: viewT1.value }))

/**
 * 可用边界。实时右缘 = clamp(墙钟, 落盘边界, 边界 + PENDING_MAX_S):
 * coverage.t1 是已落盘块的 MAX(t1), 块 10 秒才落一次 —— 纯用它当右缘会让"实时"
 * 永远差最多一个块; 纯用墙钟(旧写法)则在录制停摆/时钟漂移时右侧空白无限增长。
 * 夹在两者之间: 健康时右缘随墙钟平滑推进且空白 ≈ 一个块(斜纹 pendingZone 如实
 * 交代), 异常时空白封顶 PENDING_MAX_S。
 */
const bounds = computed(() => {
  const t0 = coverage.value.t0
  if (!Number.isFinite(t0)) return { t0: 0, t1: 0 }
  if (replaying.value) return { t0, t1: Math.max(coverage.value.t1 ?? 0, t0 + 1) }
  const edge = coverage.value.t1
  const now = Date.now() / 1000
  const live = Number.isFinite(edge)
    ? Math.min(Math.max(now, edge), edge + PENDING_MAX_S)
    : now
  return { t0, t1: Math.max(live, t0 + 1) }
})
/** 可安全 seek 的右界: 尚未落盘的那一段拖进去会 404, 吸附到它之前 */
const seekableEdge = computed(() => (coverage.value.t1 ?? bounds.value.t1) - 0.05)

/** 工位 key -> 中文名。设备清单是唯一出处, 这里不另建一份会漂的表。 */
const stationLabels = computed(() => {
  const out = {}
  for (const station of props.stations || []) {
    if (station?.id) out[String(station.id).toUpperCase()] = station.label || station.id
  }
  return out
})

const heights = computed(() => utilizationHeights(
  density.value.active, density.value.modules_total,
  density.value.stations, density.value.covered))
const overviewHeights = computed(() => utilizationHeights(
  overview.value.active, overview.value.modules_total,
  overview.value.stations, overview.value.covered))
/**
 * 总览条的 x 坐标系 = 它**实际取数**的那一段。取数窗落后 bounds 最多一个刷新周期,
 * 拿 bounds 映射会让框/柱错位一截; 首帧取数没回来前退回 bounds 兜底。
 */
const overviewWindow = computed(() => (
  overviewRange.value.t1 > overviewRange.value.t0 ? overviewRange.value : bounds.value
))
/**
 * 视窗框在总览条上的位置。**缩放时它当场变大变小** —— 这就是"缩了多少"的答案:
 * 只看轨道本身是看不出来的, 刻度换了个数字而已。
 */
const viewportBox = computed(() => {
  const b = overviewWindow.value
  if (!(b.t1 > b.t0)) return { left: '0%', width: '100%' }
  const a = Math.min(Math.max(timeToRatio(viewT0.value, b), 0), 1)
  const z = Math.min(Math.max(timeToRatio(viewT1.value, b), 0), 1)
  // 缩到极限时框会窄成一条线, 留 0.6% 的最小宽度才抓得住
  const width = Math.max(z - a, 0.006)
  return { left: pct(Math.min(a, 1 - width)), width: pct(width) }
})
/** 总览里的迷你播放头(全程坐标) —— 主播放头是视窗坐标, 穿过总览半区时位置无意义 */
const overviewCursorOffset = computed(() => timeToRatio(playhead.value, overviewWindow.value))
const markers = computed(() => layoutMarkers(density.value.markers, viewT0.value, viewT1.value))
const ticks = computed(() => axisTicksIn(view.value, 6))
const cursorOffset = computed(() => timeToRatio(playhead.value, view.value))
const lanes = computed(() => packActionLanes(actions.value, {
  view: view.value, trackPx: timePx.value, collapsed: collapsed.value,
}))

/** 工具栏的"此刻在跑什么": 回放时按播放头切片, 实时时取事件流最新一条。 */
const currentText = computed(() => {
  if (!replaying.value) return liveAction.value || '暂无动作'
  const running = actionsAt(actions.value, playhead.value)
  if (!running.length) return '此刻无动作'
  return running.length === 1 ? running[0].action : `${running.length} 件在跑`
})
const currentTitle = computed(() => {
  if (!replaying.value) return liveActionTitle.value
  return actionsAt(actions.value, playhead.value)
    .map((a) => `${a.script || ''} · ${a.action}`).join('\n') || ''
})

const pendingZone = computed(() => {
  const from = coverage.value.t1
  if (!Number.isFinite(from) || from >= bounds.value.t1) return null
  const a = timeToRatio(from, view.value)
  const b = timeToRatio(bounds.value.t1, view.value)
  if (b <= 0 || a >= 1) return null
  return { left: pct(Math.max(a, 0)), width: pct(Math.min(b, 1) - Math.max(a, 0)) }
})
const loopBand = computed(() => {
  if (!loop.value) return null
  const a = timeToRatio(loop.value.a, view.value)
  const b = timeToRatio(loop.value.b, view.value)
  if (b <= 0 || a >= 1) return null
  return { left: pct(Math.max(a, 0)), width: pct(Math.min(b, 1) - Math.max(a, 0)) }
})
const loopLabel = computed(() => {
  if (loop.value) return 'A-B ✓'
  return loopMark.value != null ? 'A…' : 'A-B'
})

const recText = computed(() => {
  if (!rec.value) return '录制状态未知'
  if (!rec.value.running) return '未录制'
  return `录制中 · ${((rec.value.coverage?.bytes || 0) / 1e9).toFixed(2)} GB`
})
const recClass = computed(() => ({
  on: rec.value?.running,
  warn: (rec.value?.dropped || 0) > 0 || (rec.value?.bad_ts || 0) > 0,
}))
// 丢帧、坏时间戳与认不出工位的机构都必须如实上墙: 录像有洞比不知道有洞好
const recTitle = computed(() => {
  if (!rec.value) return ''
  const parts = [
    `已录 ${rec.value.recorded} · 丢弃 ${rec.value.dropped} · 坏时间戳 ${rec.value.bad_ts || 0}`,
    `增量事件索引 ${rec.value.lowfreq_written || 0} 条`,
    `存于 ${rec.value.root}`,
  ]
  if (rec.value.unmapped_ids?.length) {
    parts.push(`未归工位: ${rec.value.unmapped_ids.join(', ')}`)
  }
  return parts.join(' · ')
})

function pct(ratio) { return `${(ratio * 100).toFixed(4)}%` }

/**
 * 功能: 唯一的视窗改动入口 —— 钳边界、记目标、按需缓动、按目标安排取数.
 *
 * animate 只给"离散跳转"用(滑轮缩放 / 时刻跳转 / 点总览)。**拖动期间一律不缓动**:
 * 擦洗与平移都靠 px↔时间的当前映射, 视窗要是在手指底下漂, 拖出来的位置就是错的。
 *
 * @param {{t0: number, t1: number}} next 目标视窗
 * @param {{animate?: boolean}} [options]
 * @returns {void}
 */
function setView(next, { animate = false } = {}) {
  const clamped = clampWindow(next, bounds.value)
  const span = Math.max(clamped.t1 - clamped.t0, 1)
  // 只有挪得**够远**才重取。贴实时跟随是每秒挪一秒, 每次都取的话就是一秒一轮
  // /timeline + /actions + 240 根柱子重绘 —— 页面会被自己拖到点不动。挪过 2% 跨度
  // 才算真动过, 于是跟随实时时自然退化成十几秒一次。
  const moved = Math.abs(clamped.t0 - target.t0) + Math.abs(clamped.t1 - target.t1)
  target.t0 = clamped.t0
  target.t1 = clamped.t1
  if (animate) {
    startViewEase()
  } else {
    cancelAnimationFrame(animRaf)
    clearTimeout(easeTimer)
    animRaf = 0
    easeTimer = 0
    viewT0.value = clamped.t0
    viewT1.value = clamped.t1
  }
  if (moved > span * 0.02) scheduleWindowData()
}

/**
 * 功能: 在 VIEW_EASE_MS 内从当前视窗缓动到 target.
 *
 * 两处刻意的写法, 都是踩出来的:
 *   1. **不设"已在跑就返回"的门。** 那道门看似省事, 实则一旦某一帧被丢, animRaf 就
 *      永远停在一个不会再触发的 id 上, 缓动死在半路且再也起不来。这里改成每次都取消
 *      旧帧、从**当前值**朝**当前目标**重新起一段 —— 天然可重入, 也天然自愈。
 *   2. **进度按墙钟算, 不按帧累积。** 第一帧就已经超时(慢机器上 rAF 可能几秒才来一帧)
 *      时 p 直接是 1, 一步到位。动得起来就动, 动不起来至少是对的。
 */
function startViewEase() {
  cancelAnimationFrame(animRaf)
  clearTimeout(easeTimer)
  const from = { t0: viewT0.value, t1: viewT1.value }
  const startedMs = performance.now()
  const settle = () => {
    cancelAnimationFrame(animRaf)
    animRaf = 0
    easeTimer = 0
    viewT0.value = target.t0
    viewT1.value = target.t1
  }
  const step = (nowMs) => {
    const p = Math.min((nowMs - startedMs) / VIEW_EASE_MS, 1)
    const eased = 1 - (1 - p) ** 3          // easeOutCubic: 起手快, 收尾稳
    viewT0.value = from.t0 + (target.t0 - from.t0) * eased
    viewT1.value = from.t1 + (target.t1 - from.t1) * eased
    if (p >= 1) {
      clearTimeout(easeTimer)
      easeTimer = 0
      animRaf = 0
      return
    }
    animRaf = requestAnimationFrame(step)
  }
  animRaf = requestAnimationFrame(step)
  // 兜底闹钟, 而且是**必须**的一条: rAF 绑在合成器上, 实测无头软件渲染只有 0.67 fps,
  // 第一帧可能 1.5 秒后才来 —— 在那之前视窗**纹丝不动**, 于是一次滚轮的效果要等到下一
  // 次滚轮才显形, 看起来就是"缩放整整慢一拍"。setTimeout 不受帧率影响, 到点直接落位:
  // 动得起来就动画, 动不起来至少准时到位。
  easeTimer = window.setTimeout(settle, VIEW_EASE_MS + 40)
}

function laneHeight(lane) {
  return `${Math.max(lane.rows.length, 1) * LANE_ROW_PX}px`
}

function barTitle(bar) {
  // 这三句的区分是硬要求: 把"没录到"说成"没动", 等于用一段空洞证明设备当时是好的
  if (bar.gap) return '该时段没有录像'
  if (bar.unknown) return '有录像, 但还没补算过活动度 (跑 recording_reconcile --rebuild-derived)'
  if (!bar.count) return '有录像, 设备空闲'
  const names = bar.stations.map((k) => stationLabels.value[k.toUpperCase()] || k)
  return `${bar.count} 个模块在动 —— ${names.join(', ')}`
}

function segTitle(lane, seg) {
  const when = formatClock(seg.ts, true)
  // 未闭合的必须说清楚"我们只是没看到它结束", 否则一条长块会被读成"它跑了这么久"
  const how = seg.open
    ? `未闭合 —— 证据止于 ${formatClock(seg.endTs)}`
    : (seg.duration != null ? `${seg.duration}s` : seg.status)
  return `${when}  ${lane.label} · ${seg.action}  ${how}`
}

// ── 取数 ──────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    rec.value = await api.recordingStatus()
    coverage.value = rec.value.coverage || { t0: null, t1: null }
    if (!Number.isFinite(viewT1.value) || viewT1.value <= viewT0.value) resetView()
    // 时刻输入框预填当前播放头: 空着的话"跳转"按钮点了没反应, 用户得先猜格式再手打
    if (!jumpText.value && Number.isFinite(coverage.value.t1)) {
      jumpText.value = formatInstantInput(coverage.value.t1)
    }
    else if (followLive.value && !replaying.value) {
      setView(snapToLive(view.value, bounds.value.t1, bounds.value))
    }
    if (Math.abs(bounds.value.t0 - overviewRange.value.t0) > 1
        || Math.abs(bounds.value.t1 - overviewRange.value.t1) > OVERVIEW_REFRESH_S) {
      void refreshOverview()
    }
  } catch { rec.value = null }
}

function resetView() {
  const b = bounds.value
  if (!(b.t1 > b.t0)) return
  // 默认看最近 10 分钟 —— 全览铺开 24 小时的话什么细节都看不见
  const span = Math.min(600, b.t1 - b.t0)
  setView({ t0: b.t1 - span, t1: b.t1 })
}

async function refreshWindowData() {
  // 按**目标**视窗取, 不按缓动中的当前值 —— 否则一次缩放要打十几个请求
  const { t0, t1 } = target
  if (!(t1 > t0)) return
  try {
    const [tl, act] = await Promise.all([
      api.recordingTimeline({ t0, t1, buckets: 240 }),
      api.recordingActions({ t0, t1, limit: 2000 }),
    ])
    density.value = tl
    actions.value = act.actions || []
  } catch (error) {
    lastError.value = `时间轴读取失败: ${error?.message || error}`
  }
}

/**
 * 功能: 取总览条的数据 —— 整段录像的粗粒度利用率.
 *
 * 它与视窗无关, 所以不进 scheduleWindowData 的防抖: 缩放平移一秒好几次, 而总览只在
 * 录像又长了半分钟时才需要重画。
 */
async function refreshOverview() {
  const b = bounds.value
  if (!(b.t1 > b.t0)) return
  try {
    const data = await api.recordingTimeline(
      { t0: b.t0, t1: b.t1, buckets: OVERVIEW_BUCKETS })
    overview.value = data
    // 取数**成功后**才记窗: 柱子与坐标窗必须原子换代, 失败时留旧窗配旧柱仍然自洽
    overviewRange.value = { t0: b.t0, t1: b.t1 }
  } catch { /* 总览取不到就留白, 不影响主轨道 */ }
}

/** 视窗变了就防抖重取 —— 缩放/平移是连续手势, 每帧取一次会打爆后端 */
function scheduleWindowData() {
  clearTimeout(densityTimer)
  densityTimer = window.setTimeout(refreshWindowData, 150)
}

function syncFromChannel() {
  const channel = props.channel
  if (!channel) return
  const snap = channel.snapshot()
  replaying.value = Boolean(channel.active)
  playing.value = snap.playing
  lastError.value = snap.lastError || ''
  if (replaying.value) {
    playhead.value = snap.playhead
    if (loop.value) {
      const next = abLoopNext(snap.playhead, loop.value)
      if (next.wrapped) void channel.seek(next.playhead)
    }
    if (followPlayhead.value) {
      const out = followWindow(view.value, snap.playhead, bounds.value)
      if (out.paged) setView(out.view, { animate: true })
    }
  } else {
    playhead.value = bounds.value.t1
  }
}

// ── 播放控制 ──────────────────────────────────────────────────────

/** 任何跳转前先确保已进入回放态 —— 这就是"拖走即进入回放"。 */
let opening = null
async function ensureReplay() {
  const channel = props.channel
  if (!channel) return false
  if (channel.active) return true
  // 拖动一帧一次, 不加这道闸门 open() 会被重入好几次
  if (opening) return opening
  followLive.value = false
  opening = channel.open().then((ok) => {
    if (!ok) lastError.value = channel.snapshot().lastError || '没有可回放的录像'
    replaying.value = Boolean(channel.active)
    opening = null
    return ok
  })
  return opening
}

async function seekTo(t, { focus = null } = {}) {
  if (!await ensureReplay()) return
  await props.channel.seek(Math.min(t, seekableEdge.value))
  syncFromChannel()
  // 只有**点击**才允许飞镜头: 擦洗/键盘/循环一律不碰相机, 否则拖进度条时镜头乱飞
  if (focus) emit('focus-station', focus)
}

async function togglePlay() {
  if (!await ensureReplay()) return
  if (props.channel.clock.playing) props.channel.pause()
  else props.channel.play()
  syncFromChannel()
}

function applySpeed() { props.channel?.setSpeed(speed.value) }

async function nudge(seconds) {
  if (!await ensureReplay()) return
  await props.channel.seek(props.channel.clock.playhead + seconds)
  syncFromChannel()
}

function backToLive() {
  props.channel?.close()
  followLive.value = true
  followPlayhead.value = true
  resetView()
  scheduleWindowData()
  syncFromChannel()
}

async function jumpToInstant() {
  const out = parseInstant(jumpText.value, bounds.value)
  if (out.error) { lastError.value = out.error; return }
  await seekTo(out.t)
  // 跳过去之后把视窗也带过去, 否则播放头在视窗外看不见
  const span = spanS.value || 600
  followLive.value = false
  setView({ t0: out.t - span / 2, t1: out.t + span / 2 }, { animate: true })
}

function pickSegment(seg) {
  jumpText.value = formatInstantInput(seg.ts)
  void seekTo(seg.ts)
}

function toggleRun(runId) {
  const next = new Set(collapsed.value)
  if (next.has(runId)) next.delete(runId)
  else next.add(runId)
  collapsed.value = next
}

function clearLoop() {
  loop.value = null
  loopMark.value = null
}

// ── 缩放 / 拖动 ───────────────────────────────────────────────────

function onWheel(event) {
  // ctrl+滚轮是浏览器页面缩放, 让给它
  if (event.ctrlKey) return
  const el = timeRef.value
  if (!el || !(spanS.value > 0)) return
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1)
  // 按滑动量成比例, 而不是每格固定 1.25 倍。固定倍率下从 1.3 天缩到 10 分钟要滚 23 格,
  // 手感上就成了"滚了半天没什么变化"。钳住 ±400 是防高分辨率触控板一帧甩出天文数字。
  const delta = Math.max(-400, Math.min(400, event.deltaY))
  const factor = 1.25 ** (-delta / 100)
  followLive.value = false
  followPlayhead.value = false
  setView(zoomAt(view.value, ratio, factor, bounds.value), { animate: true })
}

/**
 * 功能: 总览条上的手势 —— 拖框身平移, 拖两端把手改跨度, 点空白居中过去.
 *
 * 拖把手是最直观的缩放: 手指拉多宽, 视窗就多宽。它与滑轮走的是同一个 clampWindow,
 * 没有第二套几何。
 */
function onOverviewDown(event) {
  const el = overviewRef.value
  if (!el || event.button !== 0) return
  // 手势几何按总览实际画的那一窗算(与视窗框/柱子同一坐标系); 目标仍经 setView 钳进 bounds
  const b = overviewWindow.value
  if (!(b.t1 > b.t0)) return
  const rect = el.getBoundingClientRect()
  const x = event.clientX - rect.left
  const leftPx = timeToRatio(viewT0.value, b) * rect.width
  const rightPx = timeToRatio(viewT1.value, b) * rect.width

  let mode = 'outside'
  if (Math.abs(x - leftPx) <= VP_HANDLE_PX) mode = 'left'
  else if (Math.abs(x - rightPx) <= VP_HANDLE_PX) mode = 'right'
  else if (x > leftPx && x < rightPx) mode = 'body'

  followLive.value = false
  followPlayhead.value = false
  if (mode === 'outside') {
    // 点空白 = 把视窗整段挪过去(跨度不变), 缓动过去让人看清是从哪儿飞到哪儿
    const at = b.t0 + (x / rect.width) * (b.t1 - b.t0)
    const span = spanS.value || 600
    setView({ t0: at - span / 2, t1: at + span / 2 }, { animate: true })
    return
  }
  overviewDrag = { rect, mode, startX: event.clientX,
                   startT0: viewT0.value, startT1: viewT1.value }
  try { el.setPointerCapture(event.pointerId) } catch { /* 老浏览器没有也不影响 */ }
  window.addEventListener('pointermove', onOverviewMove)
  window.addEventListener('pointerup', onOverviewUp)
  window.addEventListener('pointercancel', onOverviewUp)
  document.body.style.userSelect = 'none'
}

function onOverviewMove(event) {
  if (!overviewDrag) return
  const b = overviewWindow.value
  const edge = bounds.value
  const perPx = (b.t1 - b.t0) / overviewDrag.rect.width
  const shift = (event.clientX - overviewDrag.startX) * perPx
  const { mode, startT0, startT1 } = overviewDrag
  // 拖动期间不缓动: 视窗要是在手指底下漂, 拉出来的跨度就不是你比划的那个。
  // 把手分支必须**先把新边缘钳进 bounds**: clampWindow 的"贴边保跨度"语义只适合
  // 平移 —— 拿它兜 resize 的话, 手指继续外拉时跨度照涨、另一端被反推着跑,
  // 表现就是"右端能拖出数据末尾老远"(2026-08-15 用户截图里的病)。
  if (mode === 'body') {
    setView(panBy({ t0: startT0, t1: startT1 }, shift, edge))
  } else if (mode === 'left') {
    const t0 = Math.max(edge.t0, Math.min(startT0 + shift, startT1 - MIN_VIEW_SPAN_S))
    setView({ t0, t1: startT1 })
  } else {
    const t1 = Math.min(edge.t1, Math.max(startT1 + shift, startT0 + MIN_VIEW_SPAN_S))
    setView({ t0: startT0, t1 })
  }
}

function onOverviewUp() {
  overviewDrag = null
  window.removeEventListener('pointermove', onOverviewMove)
  window.removeEventListener('pointerup', onOverviewUp)
  window.removeEventListener('pointercancel', onOverviewUp)
  document.body.style.userSelect = ''
}

function onPointerDown(event) {
  const el = timeRef.value
  if (!el || event.button !== 0) return
  const rect = el.getBoundingClientRect()
  drag = { rect, startX: event.clientX, moved: false, shift: event.shiftKey, startT0: viewT0.value }
  try { el.setPointerCapture(event.pointerId) } catch { /* 老浏览器没有也不影响 */ }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
  document.body.style.userSelect = 'none'
}

function onPointerMove(event) {
  if (!drag) return
  if (Math.abs(event.clientX - drag.startX) > DRAG_THRESHOLD_PX) drag.moved = true
  if (!drag.moved) return
  if (drag.shift) {
    // shift+拖 = 平移视窗(不动播放头)
    const perPx = spanS.value / drag.rect.width
    setView(panBy({ t0: drag.startT0, t1: drag.startT0 + spanS.value },
                  -(event.clientX - drag.startX) * perPx, bounds.value))
    return
  }
  const t = Math.min(pxToTime(event.clientX - drag.rect.left, view.value, drag.rect.width),
                     seekableEdge.value)
  playhead.value = t
  // 擦洗: 向前且数据在手是免费的 drain, 向后才走单航班的预览 seek
  if (props.channel?.active) props.channel.scrubTo(t)
  else void ensureReplay().then(() => props.channel?.scrubTo(t))
}

async function onPointerUp(event) {
  const info = drag
  drag = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
  document.body.style.userSelect = ''
  if (!info) return
  if (info.shift) { scheduleWindowData(); return }
  if (!info.moved) {
    // 没动 = 点击, 直接跳
    const t = pxToTime(event.clientX - info.rect.left, view.value, info.rect.width)
    await seekTo(t)
    return
  }
  await props.channel?.endScrub()
  syncFromChannel()
}

// ── 键盘 ──────────────────────────────────────────────────────────

async function onKeyDown(event) {
  const target = event.target
  const inEditable = Boolean(target?.closest?.('input, textarea, select, [contenteditable]'))
  const intent = keyIntent({
    key: event.key, shiftKey: event.shiftKey, ctrlKey: event.ctrlKey,
    altKey: event.altKey, metaKey: event.metaKey, inEditable,
  })
  if (!intent) return
  event.preventDefault()
  if (intent.kind === 'toggle') await togglePlay()
  else if (intent.kind === 'nudge') await nudge(intent.seconds)
  else if (intent.kind === 'speed') {
    const i = SPEEDS.indexOf(speed.value)
    speed.value = SPEEDS[Math.min(Math.max(i + intent.direction, 0), SPEEDS.length - 1)]
    applySpeed()
  } else if (intent.kind === 'jump') {
    if (intent.to === 'live') backToLive()
    else await seekTo(bounds.value.t0)
  } else if (intent.kind === 'step') {
    await nudge(intent.direction * 0.2)
  } else if (intent.kind === 'loopMark') {
    if (intent.which === 'a') loopMark.value = playhead.value
    else if (loopMark.value != null) loop.value = normalizeLoop(loopMark.value, playhead.value)
  }
}

// ── 生命周期 ──────────────────────────────────────────────────────

/** 时间区是展开后才存在的, 所以量宽度要等它挂上。 */
function watchTimeWidth() {
  const el = timeRef.value
  resizeObserver?.disconnect()
  resizeObserver = null
  if (!el) return
  timePx.value = el.clientWidth || 800
  if (typeof ResizeObserver === 'undefined') return
  resizeObserver = new ResizeObserver(() => { timePx.value = el.clientWidth || 800 })
  resizeObserver.observe(el)
}

watch(expanded, (open) => {
  if (!open) { resizeObserver?.disconnect(); resizeObserver = null; return }
  requestAnimationFrame(watchTimeWidth)
})

onMounted(() => {
  // 当前动作走实时流(即时), 列表本体走 1 Hz 拉取(全量) —— 两者要的东西不同。
  // 回放中必须停用实时源: 否则一条叫"时间线"的条会一边放昨天一边滚今天的步骤。
  unsubscribe = props.stream?.onEvent?.((event) => {
    if (replaying.value) return
    const type = String(event?.type || '')
    if (type === 'vm_node_enter' || type === 'step_start') {
      liveAction.value = String(event.action || event.op || '')
      liveActionTitle.value = `${event.script || ''} · ${formatClock(event.ts)}`
    }
  })
  poll = window.setInterval(() => {
    syncFromChannel()
    void refreshStatus()
  }, 1000)
  void refreshStatus().then(() => { resetView(); void refreshWindowData() })
  window.addEventListener('keydown', onKeyDown)
})

onBeforeUnmount(() => {
  clearInterval(poll)
  clearTimeout(densityTimer)
  cancelAnimationFrame(animRaf)
  clearTimeout(easeTimer)
  onOverviewUp()
  unsubscribe?.()
  resizeObserver?.disconnect()
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
  document.body.style.userSelect = ''
  // close() 会自增 resetToken, 让实时接管时清掉回放留下的时间单调锁存
  props.channel?.close()
})
</script>

<style scoped>
.tl {
  position: absolute;
  /* 左右等距 = 居中。
     原先左边让开 HUD 一整个宽度(216+32)、右边只留 16, 于是整条明显偏右。改成两边
     都让 216 也不对: 舞台净宽才 1046px, 让掉 496 只剩 550, 工具栏直接折成三行。
     所以两边都取 16 —— HUD 是**顶部锚定**的短面板(13 个工位约占 41% 高), 够不到
     底部这条; 万一内容长到够得着, 本条 z-index 11 压过它的 10, 而 HUD 自己可滚动。*/
  left: 16px;
  right: 16px;
  bottom: 16px;
  z-index: 11;
  border-radius: 10px;
  background: var(--surface-soft);
  backdrop-filter: blur(14px);
  border: 1px solid var(--border);
  color: var(--text-bright);
  font-size: 12px;
  overflow: hidden;
  --tl-gutter: 96px;
}
.tl--replay { border-color: #22d3ee66; }

/* nowrap 是硬要求: 折行会把工具栏顶成三行高, 播放头时刻被劈成三段读不出来。
   宽度不够时让最右边的状态文字截断, 而不是让整条变形。 */
.tl__bar { display: flex; align-items: center; gap: 8px; padding: 6px 12px;
           flex-wrap: nowrap; white-space: nowrap; overflow: hidden; }
.tl__spacer { flex: 1; }

.tl__toggle, .tl__btn {
  flex: none;
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  color: var(--text-bright); cursor: pointer; font-size: 12px; padding: 3px 9px;
}
.tl__btn:hover, .tl__toggle:hover { background: rgba(255, 255, 255, 0.08); }
.tl__btn.on { border-color: #22d3ee; color: #22d3ee; }
.tl__btn--live { border-color: #4ade80; color: #4ade80; }

.tl__speed, .tl__jump {
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  color: var(--text-bright); font-size: 12px; padding: 3px 4px;
}
.tl__jump { width: 178px; }
.tl__clock { font-variant-numeric: tabular-nums; font-weight: 600; flex: none; }
.tl__now { color: var(--text-dim, #94a3b8); max-width: 22%; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; }
.tl__err { color: #ff8f8f; max-width: 26%; overflow: hidden;
           text-overflow: ellipsis; white-space: nowrap; }
.tl__rec { color: var(--text-dim, #94a3b8); }
.tl__rec.on { color: #4ade80; }
.tl__rec.warn { color: #ffb020; }

/* 左名条 + 右时间区: 两列各自纵向堆行, 行高一一对应。
   overflow-x 必须显式 hidden: 只写 overflow-y 时 x 的计算值变 auto, 任何绝对定位
   子元素(刻度文字/越窗播放头)一伸出去就召出一条原生横向滚动条, 一横滚柱子整体
   左移、右侧露出无意义空白 */
.tl__body { display: flex; gap: 0; padding: 0 12px; max-height: 220px;
            overflow-x: hidden; overflow-y: auto; }
.tl__names { width: var(--tl-gutter); flex: none; }
.tl__time { position: relative; flex: 1; min-width: 0; cursor: ew-resize;
            touch-action: none; }

.tl__name { display: flex; align-items: center; font-size: 10px;
            color: var(--text-dim, #94a3b8); overflow: hidden;
            text-overflow: ellipsis; white-space: nowrap; }
/* 与 .tl__track 总高(利用率 44 + 总览 16)逐像素对齐 —— 两列靠行高硬对应 */
.tl__name--track { height: 60px; }
.tl__name--axis { height: 16px; }
.tl__name--run { cursor: pointer; padding-right: 6px; }
.tl__name--run:hover { color: var(--text-bright); }
.tl__name--failed { color: #ff8f8f; }
.tl__lanes-toggle {
  height: 22px; width: 100%; text-align: left; background: transparent; border: 0;
  color: var(--text-bright); cursor: pointer; font-size: 10px; padding: 0;
}
.tl__lanes-toggle:hover { color: #22d3ee; }

/* 复合轨道: 上半利用率(44px) + 下半总览(16px), 用户定案"总览放利用率的下半部" */
.tl__track {
  position: relative; display: flex; flex-direction: column; height: 60px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.25); overflow: hidden;
}
.tl__track-util { position: relative; flex: 1; min-height: 0; overflow: hidden; }

/* 总览半区: 不透明底 + z-index 2 —— 主播放头(视窗坐标, z-index 1)从后面穿过,
   不在错误的 x 位置划破总览; 自带 overflow:hidden 承住视窗框的 9999px 遮罩阴影 */
.tl__overview {
  position: relative; z-index: 2; flex: none; height: 16px;
  background: rgb(16 20 27); overflow: hidden; cursor: pointer;
  border-top: 1px solid rgb(255 255 255 / 10%);
}
/* 视窗框: 框外压暗, 框内透亮 —— 一眼看出"整段录像里我在看哪一小截" */
.tl__vp {
  position: absolute; top: 0; height: 100%; box-sizing: border-box;
  border: 1px solid #22d3ee; background: rgba(34, 211, 238, 0.16);
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42); cursor: grab;
}
.tl__vp:active { cursor: grabbing; }
.tl__vp-h { position: absolute; top: 0; width: 6px; height: 100%; cursor: ew-resize; }
.tl__vp-h--l { left: -3px; }
.tl__vp-h--r { right: -3px; }
/* 总览的迷你播放头(全程坐标): 主播放头进不来, 位置感由它补上 */
.tl__ov-cursor { position: absolute; top: 0; bottom: 0; width: 1px; background: #fff;
                 opacity: 0.8; pointer-events: none; }
.tl__density { display: flex; align-items: flex-end; height: 100%; gap: 1px; }
.tl__bar-i { flex: 1; background: #22d3ee66; min-width: 1px; }
/* 空闲: 只留一条基线 —— 与"根本没录"区分开 */
.tl__bar-i--idle { height: 1px !important; background: #ffffff1a; }
/* 没有录像: 什么都不画 —— 与"录了但空闲"的基线区分开 */
.tl__bar-i--gap { height: 0 !important; }
/* 未补算: 斜纹底纹, 绝不能画成"空闲" */
.tl__bar-i--unknown { height: 100% !important;
  background: repeating-linear-gradient(45deg, #ffffff0d 0 3px, transparent 3px 6px); }
.tl__pending { position: absolute; top: 0; height: 100%;
               background: repeating-linear-gradient(45deg, #ffffff10 0 6px, transparent 6px 12px); }
.tl__loop { position: absolute; top: 0; height: 100%; background: #8b5cf633;
            border-left: 1px solid #8b5cf6; border-right: 1px solid #8b5cf6; }
.tl__mark { position: absolute; top: 0; width: 2px; height: 100%;
            transform: translateX(-1px); cursor: pointer; }
.tl__mark:hover { width: 4px; }
/* 播放头贯穿轨道 + 刻度 + 全部泳道 (z-index 1: 被总览半区压住, 不划破全程坐标系) */
.tl__cursor { position: absolute; top: 0; bottom: 0; z-index: 1; width: 2px; background: #fff;
              box-shadow: 0 0 6px #fff; transform: translateX(-1px); pointer-events: none; }

/* overflow hidden: 右缘刻度文字经 translateX(-50%) 会伸出容器半个字宽,
   不裁会常驻一条横向滚动条 */
.tl__axis { position: relative; height: 16px; overflow: hidden;
            color: var(--text-dim, #94a3b8); font-size: 10px; }
.tl__axis span { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.tl__lanes-gap { height: 22px; }

.tl__lane { position: relative; }
.tl__lane-row { position: relative; height: 13px; overflow: hidden; }
.tl__seg {
  position: absolute; top: 2px; height: 9px; min-width: 2px; border-radius: 2px;
  background: #22d3ee; cursor: pointer;
}
.tl__seg:hover { background: #67e8f9; }
.tl__seg--failed { background: #ff5a5f; }
/* 未闭合: 斜纹 + 右端渐隐。实心块会被读成"它实打实跑了这么久", 而我们只是没看到它结束 */
.tl__seg--open {
  background: repeating-linear-gradient(45deg, #22d3ee 0 3px, #22d3ee44 3px 6px);
  opacity: 0.85;
}

.tl__hint { color: var(--text-dim, #94a3b8); font-size: 10px; display: flex; gap: 8px;
            padding: 2px 12px 6px; }
.tl__warn { color: #ffb020; }
.tl__span { margin-left: auto; }
</style>
