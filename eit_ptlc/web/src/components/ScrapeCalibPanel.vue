<script setup>
// 刮痕标定控制台 (点位页「刮痕标定」独立入口)。
// 一键式: 放空白牺牲板 + 放接粉桶 → 点开始 → 拍空白板建帧 / 刮标定图案 / 补拍 / 自动测量 /
// 自动写回 plate_origin / 二次刮取 / 复测确认收敛 → 出报告。
//
// 面板启动 photoscrape_scrape_calib 流程并接管其轮次门: 机器动作全在 VM(保住资源锁+气缸配对释放),
// 测量与配置回写留在面板侧(保住"防 run 上下文越权改标定"原则)。
//
// ★ 硬闸: 全自动写盘的前提是测量可信。任一可信度判据不通过 → 不写配置 → 回 finish 干净放板 →
//   报明未过判据。宁可这次白跑, 不可把一个坏值写进标定。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useDebugStore } from '../stores/debug'
import { useSystemStore } from '../store'
import ImageLightbox from './ImageLightbox.vue'

const OP_NAME = 'photoscrape_scrape_calib'
const IDLE_STATES = ['idle', 'NEW', 'DONE', 'ERROR', 'KILLED', '']
const CHECK_LABEL = {
  area_ratio: '面积比',
  centroid_agreement_cm: '质心/包围盒一致性',
  component_count: '连通块数',
  stray_ratio: '窗外杂痕占比',
}

const debug = useDebugStore()
const sys = useSystemStore()

const gcode = ref(null)
const localError = ref('')
const roundsWanted = ref(2)
const rounds = ref([])        // [{n, summary_path, dx_cm, dy_cm, trustworthy, checks, annotated_url, applied, message}]
const phase = ref('idle')     // idle | running | done | aborted
const verdict = ref('')       // 终态报告文字
const busy = reactive({ start: false, gate: false })
const sampleId = ref('')
// 放大器: 刮前/刮后**成对**装入, 共享缩放平移 —— 两帧逐像素配准(帧回放契约保证),
// 同倍率同位置并排才能肉眼判断刮痕到底偏了多少
const lightbox = ref([])
let pending = null            // 已刮待测的轮次 {n, summary_path}
let gateSeq = 0               // 已处理过的门序号, 防同一门重复处理
// 首门(空白板确认)是否已代答: 之后再来的 confirm 门是**取桶门**, 面板不得代答
const firstGateDone = ref(false)

const isDebugMode = computed(() => sys.mode === 'DEBUG')
const runActive = computed(() => !IDLE_STATES.includes(debug.status))
const owned = computed(() => debug.operation === OP_NAME && runActive.value)
const foreignRun = computed(() => runActive.value && debug.operation !== OP_NAME)
const canStart = computed(() => !busy.start && !runActive.value && isDebugMode.value)
// 取桶门正等人: 收尾翻料后 VM 停在第二个 confirm 门(见 photoscrape_scrape_calib.yaml), 由通用弹窗答
const bucketWaiting = computed(() =>
  owned.value && debug.hitl?.kind === 'confirm' && firstGateDone.value)
// 收敛阈值 = 一个刀宽 (cm); 复测残差在此以内即判标定生效
const tolCm = computed(() => Number(gcode.value?.tool?.cutter_diameter_mm || 2) / 10)

function fmt(v, d = 3) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(d) : String(v)
}
function failedOf(res) {
  const c = res?.checks || {}
  return Object.keys(c).filter((k) => !c[k].pass).map((k) => CHECK_LABEL[k] || k)
}

// 点任一张帧都装入**两张**: 刮前基准 + 刮后叠加, 并排联动放大
function openFrames(r) {
  lightbox.value = [
    { src: r.base_frame_url, alt: '刮前基准帧', caption: `第 ${r.n} 轮 · 刮前 (差分基准)` },
    {
      src: r.annotated_url,
      alt: r.ok ? '刮后测量叠加' : '刮后指令区叠加 (未检出)',
      caption: r.ok
        ? `第 ${r.n} 轮 · 刮后 + 测量叠加`
        : `第 ${r.n} 轮 · 刮后 + 指令区叠加 (未检出, 无实刮轮廓)`,
    },
  ].filter((it) => it.src)
}

async function refreshGcode() {
  try {
    gcode.value = (await api.getConfigSection('gcode'))?.values || null
  } catch (e) {
    gcode.value = null
  }
}

async function start() {
  // 全自动运行 + 板报废, 启动即不可逆 → danger-ack; 前置清单 (空白板/接粉桶) 已在面板明示
  if (!(await confirmAction({
    title: '开始刮痕自动标定',
    message: '将驱动机床全自动刮擦数轮, 消耗一块板 (报废)。',
    level: 'danger-ack',
    ackText: '已放置可报废板, 允许全自动运行',
    confirmText: '开始标定',
  }))) return
  localError.value = ''
  verdict.value = ''
  rounds.value = []
  pending = null
  gateSeq = 0
  firstGateDone.value = false
  busy.start = true
  try {
    // sample_id 兼作视觉 case 目录名与各轮工作区前缀; 用时间戳保证每次标定互不覆盖
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
    sampleId.value = `CALIB-${stamp}`
    phase.value = 'running'
    await debug.start(OP_NAME, { sample_id: sampleId.value, save_dir: `var/scrape_calib/${sampleId.value}` },
                      sys.mode, 'run')
  } catch (e) {
    localError.value = errText(e)
    phase.value = 'idle'
  } finally {
    busy.start = false
  }
}

// 收尾: 让 VM 退环并干净放板 (硬闸与正常结束共用这条路)
async function replyFinish() {
  await debug.replyHuman({ choice: 'ok', values: { action: 'finish' } })
}

async function onFirstGate() {
  // 前置(空白牺牲板 + 接粉桶)已在启动前于面板上明示并由用户点「开始」确认, 此处直接放行
  await debug.replyHuman({ choice: 'ok', values: {} })
}

// 轮次门: ① 测上一轮(含硬闸) ② 够轮数就收尾 ③ 否则生成下一轮图案
async function onRoundGate() {
  // ① 上一轮已刮 → 测量
  if (pending) {
    const res = await api.scrapeOffset(pending.summary_path, 2)
    const failed = failedOf(res)
    const row = {
      n: pending.n, summary_path: pending.summary_path,
      dx_cm: res.dx_cm, dy_cm: res.dy_cm,
      dx_agree_cm: res.dx_agree_cm, dy_agree_cm: res.dy_agree_cm,
      minor_count: res.minor_count || 0, minor_area_px: res.minor_area_px || 0,
      trustworthy: !!res.trustworthy, ok: !!res.ok,
      checks: res.checks || {}, annotated_url: res.annotated_url || '',
      base_frame_url: pending.base_frame_url || '',   // 本轮刮前基准帧, 与叠加图并列展示
      message: res.message || '', applied: false,
    }
    rounds.value = [...rounds.value, row]
    pending = null

    // ★ 硬闸: 测不出或判据不通过 → 绝不写配置, 干净收尾
    if (!res.ok || !res.trustworthy) {
      verdict.value = !res.ok
        ? `第 ${row.n} 轮未检出刮痕, 标定中止 —— ${res.message} 请对比刮前/刮后两图核实板面情况。`
        : `第 ${row.n} 轮测量可信度不足 (未通过: ${failed.join(', ')}), 未写入任何标定值。请看叠加图核实板面情况后重跑。`
      phase.value = 'aborted'
      await replyFinish()
      return
    }

    if (rounds.value.length === 1) {
      // 首轮: 把测得误差折进 plate_origin (全自动写盘, 由上面的硬闸把关)
      await api.saveConfigSection('gcode', {
        plate_origin_x: res.suggested_plate_origin_x,
        plate_origin_y: res.suggested_plate_origin_y,
      })
      row.applied = true
      rounds.value = [...rounds.value]
      await refreshGcode()
    }
    // 复测轮只记残差, 不再写 —— 避免来回振荡
  }

  // ② 轮数已满 → 收尾出报告
  if (rounds.value.length >= Number(roundsWanted.value)) {
    const last = rounds.value[rounds.value.length - 1]
    const resid = Math.hypot(Number(last.dx_cm) || 0, Number(last.dy_cm) || 0)
    verdict.value = resid <= tolCm.value
      ? `标定完成: 复测残差 ${resid.toFixed(3)}cm ≤ 一个刀宽 ${tolCm.value.toFixed(2)}cm, 已收敛。`
      : `复测残差 ${resid.toFixed(3)}cm 仍超一个刀宽 ${tolCm.value.toFixed(2)}cm, 未收敛 —— `
        + '相机链分量可能较大, 建议用卡尺量刮痕交叉验证后再判。本次不再自动修正。'
    phase.value = 'done'
    await replyFinish()
    return
  }

  // ③ 生成下一轮图案 (工作区命名与差分基准帧由后端 scrape_calib 单点决定)
  const next = rounds.value.length + 1
  const pat = await api.calibPattern(sampleId.value, next)
  pending = { n: next, summary_path: pat.summary_path, base_frame_url: pat.base_frame_url || '' }
  await debug.replyHuman({
    choice: 'ok', values: { calib_summary_path: pat.summary_path, action: 'go' },
  })
}

// 门到达即由面板应答; gateSeq 防同一 req_id 被重复处理
watch(() => debug.hitl, async (h) => {
  if (!h || !owned.value || busy.gate) return
  if (h.req_id === gateSeq) return
  // 取桶门(首门之后的 confirm): 面板**不代答**, 留给通用 HITL 弹窗由人确认 ——
  // 代答等于翻料后瞬间翻回, 人来不及取桶 (2026-07-28 操作员反馈; 门语义见 operation YAML)
  if (h.kind === 'confirm' && firstGateDone.value) return
  gateSeq = h.req_id
  busy.gate = true
  try {
    if (h.kind === 'confirm') { firstGateDone.value = true; await onFirstGate() }
    else if (h.kind === 'input') await onRoundGate()
  } catch (e) {
    localError.value = errText(e)
    verdict.value = '标定中断: ' + errText(e)
    phase.value = 'aborted'
    try { await replyFinish() } catch (_) { /* 门已失效: VM 自身的 catch 会放板 */ }
  } finally {
    busy.gate = false
  }
}, { deep: false })

onMounted(refreshGcode)
onBeforeUnmount(() => { pending = null })
</script>

<template>
  <div class="sc">
    <header class="sc-head">
      <div>
        <h3>刮痕标定 · 自动</h3>
        <p>刮已知图案 → 拍照测实刮位置 → 自动折进 gcode.plate_origin → 二次刮取复测</p>
      </div>
      <div class="sc-head-actions">
        <span class="pill" :class="{ on: isDebugMode }">{{ sys.mode || '模式未知' }}</span>
        <span class="pill" :class="{ on: owned }">
          {{ owned ? '标定运行中' : (foreignRun ? '别处在跑' : '未开跑') }}
        </span>
      </div>
    </header>

    <div v-if="localError" class="sc-err" role="status">{{ localError }}</div>

    <section class="sc-card">
      <div class="card-head">
        <h4>开始前</h4>
        <span class="muted">当前 plate_origin ({{ fmt(gcode?.plate_origin_x, 2) }}, {{ fmt(gcode?.plate_origin_y, 2) }})</span>
      </div>
      <p class="sc-warn">
        标定会在板上刮出图案, <strong>板将报废</strong> —— 必须放<strong>空白牺牲板</strong>。
        刮取动作同跑收集路径, <strong>接粉桶必须放好</strong>, 否则粉末散落。
      </p>
      <ol class="steps">
        <li>刮板夹具里放一块<strong>空白牺牲板</strong>。</li>
        <li>放好<strong>接粉收集桶</strong>。</li>
        <li>点「开始自动标定」——之后全程无需干预。</li>
      </ol>
      <div v-if="foreignRun" class="sc-warn">
        当前有别的流程在跑 (<strong>{{ debug.operation || '未知' }}</strong>);
        标定占用 photo_scrape 工位, 请先结束该运行。
      </div>
      <div class="sc-actions">
        <label class="inline">刮取轮数
          <select v-model="roundsWanted" :disabled="runActive">
            <option :value="2">2 (刮 + 校准 + 复测)</option>
            <option :value="3">3 (多一轮复核)</option>
          </select>
        </label>
        <button class="btn run" :disabled="!canStart" @click="start">
          {{ busy.start ? '启动中…' : '开始自动标定' }}
        </button>
        <span v-if="!isDebugMode" class="muted">标定会写配置, 仅 DEBUG 模式可启动</span>
      </div>
      <p class="muted">一块板最多容纳 3 轮图案 (位置逐轮错开); 超出需换板重跑。</p>
    </section>

    <section v-if="phase !== 'idle'" class="sc-card">
      <div class="card-head">
        <h4>进度</h4>
        <span class="muted">
          <template v-if="phase === 'running'">执行中… 已完成 {{ rounds.length }}/{{ roundsWanted }} 轮</template>
          <template v-else-if="phase === 'done'">已完成</template>
          <template v-else>已中止</template>
        </span>
      </div>

      <p v-if="verdict" :class="phase === 'done' ? 'ok-box' : 'sc-warn'" role="status">{{ verdict }}</p>
      <p v-else-if="phase === 'running'" class="muted" role="status">
        正在拍照 / 刮取 / 测量, 请勿操作机台。样品 {{ sampleId }}
      </p>

      <div v-if="bucketWaiting" class="sc-warn">
        <strong>等待取桶</strong> — 翻料已完成, 接粉桶定位气缸已松开。
        请取下接粉桶, 然后在弹出的确认框点「确认」, 收集器才会翻回复位。
      </div>

      <div v-for="r in rounds" :key="r.n" class="round">
        <div class="round-head">
          <strong>第 {{ r.n }} 轮</strong>
          <span v-if="r.applied" class="tag applied">已写回 plate_origin</span>
          <span v-else-if="r.n > 1" class="tag">复测(不写)</span>
          <span class="tag" :class="r.trustworthy ? 'good' : 'bad'">
            {{ r.ok ? (r.trustworthy ? '可信' : '存疑') : '未检出' }}
          </span>
        </div>
        <dl v-if="r.ok" class="metric-grid">
          <dt>Δ 实刮 − 指令 (cm)</dt>
          <dd class="mono">{{ fmt(r.dx_cm) }} , {{ fmt(r.dy_cm) }}</dd>
          <dt title="同一轮内质心法与包围盒法的估计差; 越大说明该轴越不可信">估计器分歧 (cm)</dt>
          <dd class="mono">
            dx ±{{ fmt(r.dx_agree_cm) }} , dy ±{{ fmt(r.dy_agree_cm) }}
            <span class="muted"> — 分歧接近或大于 Δ 本身时, 该轴的修正量不可当真</span>
          </dd>
        </dl>
        <table v-if="r.ok" class="chk-table">
          <tbody>
            <tr v-for="(c, k) in r.checks" :key="k" :class="{ bad: !c.pass }">
              <td :title="c.hint">{{ CHECK_LABEL[k] || k }}</td>
              <td class="mono">
                {{ c.value }}
                <span v-if="k === 'component_count' && r.minor_count" class="muted">
                  (另剔除 {{ r.minor_count }} 块碎屑 / {{ r.minor_area_px }}px, 图上红圈)
                </span>
              </td>
              <td>{{ c.pass ? '通过' : '不通过' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">{{ r.message }}</p>
        <div class="frames">
          <figure v-if="r.base_frame_url" tabindex="0" role="button" @click="openFrames(r)"
                  @keydown.enter.prevent="openFrames(r)" @keydown.space.prevent="openFrames(r)">
            <img :src="r.base_frame_url" alt="本轮刮前基准帧 (差分底图)" />
            <figcaption>刮前 (本轮差分基准) — 点击并排放大</figcaption>
          </figure>
          <figure v-if="r.annotated_url" tabindex="0" role="button" @click="openFrames(r)"
                  @keydown.enter.prevent="openFrames(r)" @keydown.space.prevent="openFrames(r)">
            <!-- 未检出时图上没有白轮廓也没有箭头, 图注不能照抄成功档的说法 -->
            <img :src="r.annotated_url"
                 :alt="r.ok
                   ? '刮痕测量叠加图: 青=指令扫掠区, 白=实刮轮廓, 黄箭头=位移'
                   : '未检出刮痕: 青=指令扫掠区, 红圈=面积不足被剔除的碎屑'" />
            <figcaption>
              {{ r.ok ? '刮后 + 测量叠加' : '刮后 + 指令区叠加 (未检出, 无实刮轮廓)' }} — 点击并排放大
            </figcaption>
          </figure>
        </div>
      </div>

      <p class="muted">
        青 = 指令扫掠区, 白 = 实刮轮廓, <strong>红圈 = 面积不足被剔除的碎屑</strong>, 黄箭头 = 质心位移。
        测到的是<strong>相机链 + 机床链 + 刀具链的合量</strong>, 分不出哪一段;
        需要分离时用卡尺量刮痕交叉验证。
      </p>
      <p class="muted">
        图案是 <strong>L 形</strong>: 长横带定 y, 左端竖笔定 x。扁带沿带长方向几何欠定
        (挪 2.8mm 只掉 2.5% 重叠), 竖笔就是为了把 x 方向的位置信息补回来。
      </p>
    </section>

    <ImageLightbox :items="lightbox" @close="lightbox = []" />
  </div>
</template>

<style scoped>
.sc { padding: 4px 2px 24px; color: var(--text); max-width: 760px; }
.sc-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.sc-head h3 { margin: 0; font-size: var(--fs-17); line-height: 1.3; color: var(--text-strong); }
.sc-head p { margin: 3px 0 0; color: var(--muted); font-size: var(--fs-12); }
.sc-head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
/* .pill 基础样式走全局 (style.css), 此处只留状态修饰 */
.pill.on { background: var(--ok-soft); color: var(--ok-strong); }
.sc-err { color: var(--bad-strong); font-size: var(--fs-13); padding: 8px 10px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 12px; }
.sc-warn { color: var(--bad-strong); font-size: var(--fs-13); padding: 7px 9px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 10px; }
.ok-box { color: var(--ok-strong); font-size: var(--fs-13); padding: 7px 9px; border-radius: 6px; background: var(--ok-soft); margin-bottom: 10px; }

.sc-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.card-head h4 { margin: 0; font-size: 15px; color: var(--text-strong); }

.steps { margin: 0 0 10px; padding-left: 20px; color: var(--subtle); font-size: var(--fs-13); line-height: 1.7; }
.steps strong { color: var(--text-strong); }

.sc-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 10px; }
.inline { display: flex; align-items: center; gap: 6px; font-size: var(--fs-12); color: var(--subtle); }
.inline select { padding: 4px 7px; border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }
/* .btn 全套样式走全局 (style.css) */

.round { border-top: 1px solid var(--border-soft); padding-top: 10px; margin-top: 10px; }
.round-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: var(--fs-13); color: var(--text-strong); }
.tag { font-size: var(--fs-11); padding: 2px 7px; border-radius: 9px; background: var(--chip-bg); color: var(--subtle); font-weight: 650; }
.tag.applied { background: var(--ok-soft); color: var(--ok-strong); }
.tag.good { background: var(--ok-soft); color: var(--ok-strong); }
.tag.bad { background: var(--bad-soft); color: var(--bad-strong); }

.metric-grid { display: grid; grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1fr); gap: 0; margin: 0 0 8px; border: 1px solid var(--border-soft); border-radius: 6px; overflow: hidden; }
.metric-grid dt, .metric-grid dd { margin: 0; padding: 6px 9px; font-size: var(--fs-12); min-width: 0; }
.metric-grid dt { color: var(--subtle); background: var(--surface-2); font-weight: 650; }
.metric-grid dd { color: var(--text); }
.mono { font-variant-numeric: tabular-nums; }

.chk-table { width: 100%; border-collapse: collapse; font-size: var(--fs-12); }
.chk-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--border-soft); }
.chk-table tr.bad td { color: var(--bad-strong); }
.frames { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
.frames figure { margin: 0; flex: 1 1 260px; min-width: 0; cursor: zoom-in; }
.frames figure:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 6px; }
/* 相机帧 4/3 定比 (同 WaterLevelGrid): 图未到时先占稳高度, 防加载重排 */
/* 4:3 锁定自 config/app.yaml camera.cap_width/height=640×480; 后端提 1280×720 时同步改 */
.frames img { display: block; width: 100%; aspect-ratio: 4 / 3; object-fit: contain;
              background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; }
.frames figure:hover img { border-color: var(--accent); }
.frames figcaption { margin-top: 4px; font-size: var(--fs-11); color: var(--muted); }
.muted { color: var(--muted); font-size: var(--fs-12); }
</style>
