<script setup>
// 刮板对刀控制台 (点位页「刮板对刀」独立标定入口)。
// 本面板不直接驱动机床: 它启动 photoscrape_tool_align 流程, 再用步骤式 UI 渲染该流程的人工门
// (首门 confirm / 内环 choose / 微调 input), 经 debug.replyHuman 应答。
// 如此保留流程自带的三层保护: station:photo_scrape 资源锁 + 自动压板/配对释放 + 失败先回零。
// Δ 与建议值一律取自后端 align_readout (单点产地 controller/align_check.py), 面板不自行换算。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { usePoll } from '../composables/usePoll.js'
import { useDebugStore } from '../stores/debug'
import { useSystemStore } from '../store'

const OP_NAME = 'photoscrape_tool_align'
const IDLE_STATES = ['idle', 'NEW', 'DONE', 'ERROR', 'KILLED', '']

const debug = useDebugStore()
const sys = useSystemStore()

const readout = ref(null)       // align_readout 结构化回显 (x/y/z/原点/Δ/inspect_z/建议值)
const readoutErr = ref('')
const gcode = ref(null)         // app.yaml gcode 段 (取 plate_surface_z_mm 供换刀前置核对)
const localError = ref('')
const saveMsg = ref('')
const busy = reactive({ start: false, gate: false, save: false })
const jog = reactive({ dx: '', dy: '' })
const precheck = reactive({ zUpdated: false, plateLoaded: false })
const wentOrigin = ref(false)   // 本轮是否已走过原点角; 未走过时缓降必被 PLC 拒 (424), 界面先拦一道

const isDebug = computed(() => sys.mode === 'DEBUG')
const runActive = computed(() => !IDLE_STATES.includes(debug.status))
const owned = computed(() => debug.operation === OP_NAME && runActive.value)
// 别处已有运行在跑: 对刀占 station:photo_scrape, 此时启动必被资源锁拒, 先在界面说清楚
const foreignRun = computed(() => runActive.value && debug.operation !== OP_NAME)
const gateKind = computed(() => (owned.value && debug.hitl ? debug.hitl.kind : ''))

// 面板阶段: idle 未开跑 | precheck 首门 | loop 内环选项 | jog 微调输入 | busy 机器在动(无门)
const phase = computed(() => {
  if (!owned.value) return 'idle'
  if (gateKind.value === 'confirm') return 'precheck'
  if (gateKind.value === 'choose') return 'loop'
  if (gateKind.value === 'input') return 'jog'
  return 'busy'
})

const canStart = computed(() => !busy.start && !runActive.value)
const canConfirm = computed(() => precheck.zUpdated && precheck.plateLoaded && !busy.gate)
// 已在安全高时不必再抬; 用于「升回安全高」的禁用与「微调」的提示文案
const atSafeZ = computed(() => Number(readout.value?.z_mm ?? 1) === 0)
const canSave = computed(() => isDebug.value && !busy.save && !!readout.value)

function fmt(v, d = 2) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(d) : String(v)
}

async function refreshReadout(opts = {}) {
  try {
    readout.value = await api.alignReadout()
    readoutErr.value = ''
  } catch (e) {
    if (!opts.silent) readoutErr.value = errText(e)
  }
}

async function refreshGcode() {
  try {
    gcode.value = (await api.getConfigSection('gcode'))?.values || null
  } catch (e) {
    gcode.value = null
  }
}

async function startAlign() {
  localError.value = ''
  saveMsg.value = ''
  busy.start = true
  try {
    // 复位本轮界面态: 步骤门控与首门勾选不得跨 run 残留
    wentOrigin.value = false
    precheck.zUpdated = false
    precheck.plateLoaded = false
    jog.dx = ''
    jog.dy = ''
    await debug.start(OP_NAME, {}, sys.mode, 'run')
  } catch (e) {
    localError.value = errText(e)
  } finally {
    busy.start = false
  }
}

// 应答内环 choose 门 (go_origin / z_down / z_up / jog / finish)。
// 直驱机床的选项先过确认: 走原点角/升回 = danger; 缓降 = danger-ack (接触/撞板风险,
// 唯一防线是 plate_surface_z_mm 正确)。「微调」只是切到步进量输入门 (无运动) 、
// 「结束对位」是收尾退环 (升刀/放板, 破坏性低), 均直行不弹窗。
async function choose(value) {
  if (value === 'go_origin') {
    if (!(await confirmAction({
      title: '走原点角',
      message: '刀将先升到 Z=0, 再平移到程序认为的板角上方 (机床实际运动)。',
      level: 'danger',
      confirmText: '走原点角',
    }))) return
  } else if (value === 'z_up') {
    if (!(await confirmAction({
      title: '升回安全高',
      message: '刀将抬升回 Z=0 安全高 (机床实际运动)。',
      level: 'danger',
      confirmText: '升回',
    }))) return
  } else if (value === 'z_down') {
    if (!(await confirmAction({
      title: '缓降到检查高度',
      message: `刀尖将缓降到板面上方 ${fmt(gcode.value?.align_clearance_mm)} mm 处停住, 有接触/撞板风险; 板面高度参数错误会直接撞板。`,
      detail: `plate_surface_z_mm=${fmt(gcode.value?.plate_surface_z_mm)} · 检查高度 Z=${fmt(readout.value?.inspect_z_mm)}`,
      level: 'danger-ack',
      ackText: '已确认 plate_surface_z_mm 与当前刀相符, 刀下方无障碍',
      confirmText: '缓降',
    }))) return
  }
  localError.value = ''
  busy.gate = true
  try {
    await debug.replyHuman({ choice: value, values: {} })
    if (value === 'go_origin') wentOrigin.value = true
  } catch (e) {
    localError.value = errText(e)
  } finally {
    busy.gate = false
  }
}

// 应答首门 confirm (ok 继续 / cancel 取消; 取消时板未夹持, 流程干净退出)
async function answerPrecheck(choice) {
  localError.value = ''
  busy.gate = true
  try {
    await debug.replyHuman({ choice, values: {} })
  } catch (e) {
    localError.value = errText(e)
  } finally {
    busy.gate = false
  }
}

// 应答微调 input 门: 只回填非空字段, 留空由 VM 保持默认 0.0 (与通用门同规则)。
// 盲步进属高频调试运动 → 两段式武装 (首点变「再点一次确认」, 3 秒不二点撤防), 不弹模态
const jogStepAct = useAsyncAction(
  async () => {
    localError.value = ''
    busy.gate = true
    try {
      const values = {}
      if (jog.dx !== '' && jog.dx != null) values.dx_mm = jog.dx
      if (jog.dy !== '' && jog.dy != null) values.dy_mm = jog.dy
      await debug.replyHuman({ choice: 'ok', values })
      jog.dx = ''
      jog.dy = ''
    } catch (e) {
      localError.value = errText(e)
    } finally {
      busy.gate = false
    }
  },
  { minInterval: 350, arm: { label: '再点一次确认', timeoutMs: 3000 } },
)

// 把当前实读 X/Y 存为 plate_origin: 刀尖对准物理板角后, 实读即原点角真值 (flip 不进公式)。
// 写 app.yaml 标定值 → danger-ack (与 calibration.yaml/设备参数保存同级)
async function saveOrigin() {
  const r = readout.value
  if (!r) return
  const ok = await confirmAction({
    title: '存为标定值',
    message: [
      `将把 gcode.plate_origin 改为 x=${r.x_mm} y=${r.y_mm}, 写入 app.yaml。`,
      '仅在刀尖已对准物理板角时才可保存。',
    ],
    detail: `原值 x=${r.origin_x_mm} y=${r.origin_y_mm}`,
    level: 'danger-ack',
    ackText: '刀尖已对准物理板角, 允许写入',
    confirmText: '写入',
  })
  if (!ok) return
  localError.value = ''
  saveMsg.value = ''
  busy.save = true
  try {
    await api.saveConfigSection('gcode', { plate_origin_x: r.x_mm, plate_origin_y: r.y_mm })
    saveMsg.value = `已写入 plate_origin: x=${r.x_mm} y=${r.y_mm} (下次 cnc_path 即生效, 无需重启)`
    await Promise.all([refreshGcode(), refreshReadout()])
  } catch (e) {
    localError.value = errText(e)
  } finally {
    busy.save = false
  }
}

// 新门到达即清空上一轮微调草稿, 防把上次的步进量误提交给这次
watch(gateKind, (k) => {
  if (k === 'jog') return
  jog.dx = ''
  jog.dy = ''
})

// 1s 轮询: jog 对点需要接近实时的位置反馈 (只读 ActPos, 不破单写者纪律)。
// 首拍非静默 = 复刻原 onMounted 首刷 (挂载即暴露读数不可达); 后续静默, 轮询失败不刷错误横幅。
let readoutPolledOnce = false
const readoutPoll = usePoll(async () => {
  await refreshReadout({ silent: readoutPolledOnce })
  readoutPolledOnce = true
}, 1000)

onMounted(() => {
  readoutPoll.start()
  refreshGcode()
})
</script>

<template>
  <div class="ta">
    <header class="ta-head">
      <div>
        <h3>刮板对刀 · 对位检查</h3>
        <p>换刀后用刀尖核对刮取原点角, 修 gcode.plate_origin_x/y</p>
      </div>
      <div class="ta-head-actions">
        <span class="mode-pill" :class="{ debug: isDebug }">{{ sys.mode || '模式未知' }}</span>
        <span class="mode-pill" :class="{ debug: owned }">{{ owned ? '对刀运行中' : (foreignRun ? '别处在跑' : '未开跑') }}</span>
      </div>
    </header>

    <div v-if="localError" class="ta-err" role="status">{{ localError }}</div>
    <div v-if="readoutErr" class="ta-warn" role="status">读取轴位置失败: {{ readoutErr }}</div>

    <!-- 实时回显: Δ 与建议值由后端 align_readout 单点产出, 面板只展示 -->
    <section class="ta-card">
      <div class="card-head">
        <h4>实时位置</h4>
        <span class="muted">Z 正方向向下 · Z=0 为安全高</span>
      </div>
      <dl class="metric-grid">
        <dt>当前 X / Y / Z (mm)</dt>
        <dd class="mono">{{ fmt(readout?.x_mm) }} / {{ fmt(readout?.y_mm) }} / {{ fmt(readout?.z_mm) }}</dd>
        <dt>原点角 plate_origin</dt>
        <dd class="mono">{{ fmt(readout?.origin_x_mm) }} , {{ fmt(readout?.origin_y_mm) }}</dd>
        <dt>Δ (实读 − 原点角)</dt>
        <dd class="mono">{{ fmt(readout?.dx_vs_origin_mm) }} , {{ fmt(readout?.dy_vs_origin_mm) }}</dd>
        <dt>检查高度 Z</dt>
        <dd class="mono">{{ fmt(readout?.inspect_z_mm) }}</dd>
      </dl>
    </section>

    <!-- 换刀前置: plate_surface_z_mm 是防撞板唯一依据, 开跑前先摆在眼前 -->
    <section class="ta-card">
      <div class="card-head"><h4>换刀前置核对</h4></div>
      <p class="ta-warn">
        换刀后必须先按当前刀更新 <strong>plate_surface_z_mm</strong>;
        未更新就缓降检查高度会<strong>撞板</strong>。
      </p>
      <dl class="metric-grid">
        <dt>plate_surface_z_mm (板面)</dt>
        <dd class="mono">{{ fmt(gcode?.plate_surface_z_mm) }}</dd>
        <dt>align_clearance_mm (余量)</dt>
        <dd class="mono">{{ fmt(gcode?.align_clearance_mm) }}</dd>
      </dl>
      <p class="muted">检查高度 = 板面 − 余量 = {{ fmt(readout?.inspect_z_mm) }};改板面高度请到设备参数页 gcode 段。</p>
    </section>

    <!-- 步骤区: 按流程当前所在的门渲染, 未到的步骤不给点 -->
    <section class="ta-card">
      <div class="card-head">
        <h4>对刀步骤</h4>
        <span class="muted">
          <template v-if="phase === 'idle'">① 启动</template>
          <template v-else-if="phase === 'precheck'">② 前置确认</template>
          <template v-else-if="phase === 'loop'">③ 走位 / 缓降 / 微调</template>
          <template v-else-if="phase === 'jog'">④ 填步进量</template>
          <template v-else>机器动作中…</template>
        </span>
      </div>

      <!-- 阶段 idle: 启动流程 -->
      <template v-if="phase === 'idle'">
        <ol class="steps">
          <li>物理换刀, 并先到设备参数页把 <strong>plate_surface_z_mm</strong> 改成当前刀的板面高度。</li>
          <li>在刮刀夹具里人工放一块板 (任意板, 角位置由定位夹具保证一致)。</li>
          <li>点「启动对刀」: 流程会占用 photo_scrape 工位并自动落定位气缸 + 压板。</li>
        </ol>
        <div v-if="foreignRun" class="ta-warn">
          当前有别的流程在跑 (<strong>{{ debug.operation || '未知' }}</strong>);
          对刀占用 photo_scrape 工位, 请先结束该运行。
        </div>
        <div class="ta-actions">
          <button class="btn run" :disabled="!canStart" @click="startAlign">
            {{ busy.start ? '启动中…' : '启动对刀' }}
          </button>
        </div>
      </template>

      <!-- 阶段 precheck: 首门 = 防撞板唯一防线, 两条都勾才放行 -->
      <template v-else-if="phase === 'precheck'">
        <p class="ta-warn">这道确认是防撞板的唯一防线, 请逐条核实后再继续。</p>
        <label class="ck">
          <input v-model="precheck.zUpdated" type="checkbox" />
          已按当前刀更新 <strong>plate_surface_z_mm</strong> (当前 {{ fmt(gcode?.plate_surface_z_mm) }})
        </label>
        <label class="ck">
          <input v-model="precheck.plateLoaded" type="checkbox" />
          刮板夹具里已人工放入一块板
        </label>
        <div class="ta-actions">
          <button class="btn run" :disabled="!canConfirm" @click="answerPrecheck('ok')">确认继续</button>
          <button class="btn ghost" :disabled="busy.gate" @click="answerPrecheck('cancel')">取消对刀</button>
          <span class="muted">取消时板尚未夹持, 流程干净退出。</span>
        </div>
      </template>

      <!-- 阶段 loop: 内环六选项 (对刀场景无路径起点, 故不渲染「走路径起点」) -->
      <template v-else-if="phase === 'loop'">
        <ol class="steps">
          <li>先「走原点角」: 刀升到 Z=0 再平移到程序认为的板角上方。</li>
          <li>再「缓降检查高度」: 降到板面上方 {{ fmt(gcode?.align_clearance_mm) }}mm, 停住供目视。</li>
          <li>低头比对刀尖与<strong>物理板角</strong> (点样边那个角), 用「微调」迭代收敛。</li>
          <li>对准后到下方「存为标定值」保存, 再「结束对位」。</li>
        </ol>
        <div class="ta-actions">
          <button class="btn" :disabled="busy.gate" @click="choose('go_origin')">走原点角</button>
          <button
            class="btn"
            :disabled="busy.gate || !wentOrigin"
            :title="wentOrigin ? '降到检查高度' : '先走原点角: XY 不在板区窗内时 PLC 会拒绝下降'"
            @click="choose('z_down')"
          >缓降检查高度</button>
          <button class="btn" :disabled="busy.gate || atSafeZ" @click="choose('z_up')">升回安全高</button>
          <button class="btn" :disabled="busy.gate" @click="choose('jog')">微调 (Δx/Δy)</button>
          <button class="btn ghost" :disabled="busy.gate" @click="choose('finish')">结束对位</button>
        </div>
        <p v-if="!wentOrigin" class="hint">「缓降检查高度」暂不可用: 请先「走原点角」—— XY 不在板区窗内时 PLC 会拒绝下降。</p>
        <p v-if="atSafeZ" class="hint">「升回安全高」已禁用: 当前已在安全高 (Z=0)。</p>
        <p class="muted">
          机床互锁: 一切 XY 平移只在 Z=0 发生。点「微调」后系统会<strong>先把刀升回安全高再平移</strong>,
          所以每次步进后需再「缓降检查高度」复查。
        </p>
      </template>

      <!-- 阶段 jog: 步进量输入 -->
      <template v-else-if="phase === 'jog'">
        <p class="muted">
          填刀尖需要移动的量 (mm, 可填负数, 留空按 0)。提交后刀先升到 Z=0 再平移,
          属<strong>盲步进</strong>, 落位后请再「缓降检查高度」复查。
        </p>
        <div class="jog-row">
          <label>ΔX (mm)<input v-model="jog.dx" type="number" inputmode="decimal" step="0.1" placeholder="0" /></label>
          <label>ΔY (mm)<input v-model="jog.dy" type="number" inputmode="decimal" step="0.1" placeholder="0" /></label>
        </div>
        <div class="ta-actions">
          <button class="btn run" :class="{ armed: jogStepAct.armed }"
                  :disabled="busy.gate || jogStepAct.busy" :aria-busy="jogStepAct.busy"
                  @click="jogStepAct.run()">
            {{ jogStepAct.armed ? jogStepAct.armedLabel : '升 Z 并步进' }}
          </button>
        </div>
      </template>

      <!-- 阶段 busy: 门未到, 机器在动 -->
      <template v-else>
        <p class="muted">流程执行中, 等待机床动作完成…</p>
      </template>
    </section>


    <!-- 存盘: 刀尖对准物理板角后, 当前实读即原点角真值 -->
    <section class="ta-card">
      <div class="card-head">
        <h4>存为标定值</h4>
        <span class="muted">刀尖对准物理板角后再存</span>
      </div>
      <dl class="metric-grid">
        <dt>建议 plate_origin_x</dt><dd class="mono">{{ fmt(readout?.x_mm) }}</dd>
        <dt>建议 plate_origin_y</dt><dd class="mono">{{ fmt(readout?.y_mm) }}</dd>
      </dl>
      <div class="ta-actions">
        <button class="btn" :disabled="!canSave" :title="isDebug ? '写回 app.yaml gcode 段' : '标定写盘仅 DEBUG 模式可用'" @click="saveOrigin">
          {{ busy.save ? '写入中…' : '存为标定值 (DEBUG)' }}
        </button>
        <span v-if="!isDebug" class="muted">切到 DEBUG 模式后可保存</span>
        <span v-if="saveMsg" class="ok">{{ saveMsg }}</span>
      </div>
      <p class="muted">存完建议复跑一次对刀, 确认 Δ ≈ 0 即验收通过。</p>
    </section>
  </div>
</template>

<style scoped>
.ta { padding: 4px 2px 24px; color: var(--text); max-width: 760px; }
.ta-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.ta-head h3 { margin: 0; font-size: var(--fs-17); line-height: 1.3; color: var(--text-strong); }
.ta-head p { margin: 3px 0 0; color: var(--muted); font-size: var(--fs-12); }
.ta-head-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }
/* .mode-pill 基础样式走全局 (style.css), 此处只留状态修饰 */
.mode-pill.debug { background: var(--ok-soft); color: var(--ok-strong); }
.ta-err { color: var(--bad-strong); font-size: var(--fs-13); padding: 8px 10px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 12px; }
.ta-warn { color: var(--bad-strong); font-size: var(--fs-13); padding: 7px 9px; border-radius: 6px; background: var(--bad-soft); margin-bottom: 10px; }

.ta-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.card-head h4 { margin: 0; font-size: 15px; color: var(--text-strong); }

.steps { margin: 0 0 10px; padding-left: 20px; color: var(--subtle); font-size: var(--fs-13); line-height: 1.7; }
.steps strong { color: var(--text-strong); }

.metric-grid { display: grid; grid-template-columns: minmax(160px, 0.8fr) minmax(0, 1fr); gap: 0; margin: 0; border: 1px solid var(--border-soft); border-radius: 6px; overflow: hidden; }
.metric-grid dt, .metric-grid dd { margin: 0; padding: 6px 9px; border-bottom: 1px solid var(--border-soft); font-size: var(--fs-12); min-width: 0; }
.metric-grid dt { color: var(--subtle); background: var(--surface-2); font-weight: 650; }
.metric-grid dd { color: var(--text); word-break: break-word; }
.metric-grid dt:nth-last-child(2), .metric-grid dd:last-child { border-bottom: 0; }
.mono { font-variant-numeric: tabular-nums; }

.ck { display: flex; align-items: center; gap: 7px; font-size: var(--fs-13); color: var(--text); margin-bottom: 7px; }
.jog-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 4px; }
.jog-row label { display: flex; flex-direction: column; gap: 4px; font-size: var(--fs-12); color: var(--subtle); }
.jog-row input { width: 130px; padding: 4px 7px; border-radius: 5px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); }

.ta-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
/* .btn 全套样式走全局 (style.css); 两段式武装态在本面板内加警示色 */
.btn.armed { background: var(--warn); border-color: var(--warn); color: var(--on-accent); }
.muted { color: var(--muted); font-size: var(--fs-12); }
.ok { color: var(--ok-strong); font-size: var(--fs-12); }
</style>
