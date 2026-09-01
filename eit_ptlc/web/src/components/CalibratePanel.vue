<script setup>
// 孔板标定 / 按孔下发面板 (点位页「孔板标定」tab)
// 流程: 选实例 -> 开始标定(进单点模式) -> 点动把针对到锚孔 -> 采点×3 -> 提交solve+持久化
//       -> 预览全孔 -> 结束标定 -> 单孔下发验证
// 实时 ActPos 轮询显示 (供对点参考)。单写者: 仅读 *_ActPos / 写 *_Target, 不碰 HMI 示教槽。
//
// 为什么不是「去使能手推」(2026-07 之前的做法, 已废弃):
//   PLC `伺服调用` 里 4X/3Y 的 xEnable 是
//     急停 AND NOT (Sampling_Servo_FreeMove AND (上样轴5Z轴DATE.fActPos < 3))
//   而 PLC_Servo_伺服 状态机 60 又有 PLC_Ready := bAllAxesEnabled AND ...,
//   bAllAxesEnabled 含 4X/3Y。于是写 FreeMove=TRUE → 两轴掉使能 → PLC_Ready=FALSE
//   → 同 POU 末尾的排空块 `IF NOT PLC_Ready THEN ... Sampling_Servo_FreeMove := FALSE`
//   把请求位抹掉 → 轴立刻回电。**这是个自毁循环, 轴根本不会停在去使能态。**
//   而且 5Z 的 xEnable 只有 `急停`, 从设计上就永不释放, 三根轴里最关键的那根推不动。
//   现在改走 PC 单点模式的电动点动: 三轴全覆盖、可 0.01mm 步进、有三层防卡死。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAxisJog } from '../composables/useAxisJog'
import { usePoll } from '../composables/usePoll.js'
import { useManualStore } from '../stores/manual'
import { useSystemStore } from '../store'
import { modeStateText } from '../utils/deviceLabels.js'

const STATION = 'sampling'
// 标定只关心这三根, 且按操作次序排: 先抬 5Z, 再走 X/Y。
// (工位点表里还有 6X/7Y 点样轴, 与孔板标定无关, 要动去设备页 /nodes/plc.sampling)
const CALIB_AXES = ['axis_5z', 'axis_4x', 'axis_3y']
const AXIS_ROLE = { axis_5z: '升降 Z', axis_4x: '标定 X', axis_3y: '标定 Y' }
const STEPS = [0.01, 0.1, 1, 10]

const manual = useManualStore()
const sys = useSystemStore()

const instances = ref([])
const selectedId = ref('')
const detail = ref(null) // {id,label,plate:{rows,cols,calib_wells,...},points,is_calibrated}
const staged = ref({}) // "r,c" -> {well:[r,c], x_mm, y_mm} (来源: 采点 ActPos 或 手输)
const stagedSrc = ref({}) // "r,c" -> '采' | '输' (该锚点值来源, 仅显示用)
const manualIn = ref({}) // "r,c" -> {x, y} 手输草稿 (字符串, 经「填入」校验后写 staged)
const actpos = ref(null) // {x_axis,x_mm,y_axis,y_mm}
const actposErr = ref('')
const targets = ref(null)
const pushRow = ref(1)
const pushCol = ref(1)
const pushResult = ref(null)
const msg = ref('')
const busy = ref(false)
const step = ref(0.1)

const calibWells = computed(() => (detail.value && detail.value.plate && detail.value.plate.calib_wells) || [])
const allStaged = computed(
  () => calibWells.value.length > 0 && calibWells.value.every((w) => staged.value[`${w[0]},${w[1]}`]),
)

// ---- 单点会话 (与设备页共用同一个 store 单例) ----
const isDebug = computed(() => sys.mode === 'DEBUG')
// 唯一权威是 PLC 回来的 PC_Manual_Active: 没它, 写下去的位不会被 FB 采纳
const canDrive = computed(() => isDebug.value && manual.active)
const disabledReason = computed(() => {
  if (!isDebug.value) return '仅 DEBUG 模式可用 (在顶部态势条切换)'
  if (!manual.enabled) return '请先点「开始标定」进入手动控制'
  if (!manual.active) return manual.rejectText || 'PLC 尚未确认单点模式生效'
  return ''
})

const modeText = computed(() => modeStateText(manual.modeState))

// 点表里挑出标定三轴, 按 CALIB_AXES 的次序(点表原始次序是 3Y/4X/5Z, 与操作次序相反)
const axes = computed(() => {
  const byId = new Map((manual.stationPoints.axes || []).map((a) => [a.id, a]))
  return CALIB_AXES.map((id) => byId.get(id)).filter(Boolean)
})
const axisState = (id) => manual.state?.axes?.[id] || {}

function fmt(v, digits = 3) {
  return typeof v === 'number' ? v.toFixed(digits) : '—'
}
// 「运行中」按实际速度判, 不能用 bBusy: FB_SERVOAXIS 的 bBusy 含 MC_Power.Busy,
// 而汇川 SM3 在使能期间它恒为 TRUE, 拿来显示会全程常亮。
function axisMoving(id) {
  const v = axisState(id).fActVel
  return typeof v === 'number' && Math.abs(v) > 0.01
}

const { jogging, jogDown, stopJog } = useAxisJog({
  canDrive,
  onError: (message) => { msg.value = message },
})
// 高亮方向修正 (与 StationManualPanel 同源问题): jogging 只记轴不记方向, 两方向钮的
// active 条件相同 → 任一方向双高亮。仅在外围记录按下方向, useAxisJog 本体不动;
// 安全停路径直接清 jogging, 高亮以 jogging 为准, jogDir 残值无害。
const jogDir = ref('') // 'neg' | 'pos' | ''
function jogPress(axis, dir, event) {
  jogDir.value = dir
  jogDown(axis, dir, event)
}
function jogRelease() {
  jogDir.value = ''
  stopJog()
}

async function toggleSession() {
  msg.value = ''
  if (manual.enabled) {
    await manual.exit()
    msg.value = manual.error ? `结束标定失败: ${manual.error}` : '已结束标定 (档位交还自动)'
    return
  }
  await manual.enter()
  msg.value = manual.error
    ? `开始标定失败: ${manual.error}`
    : '已进入手动控制, 可点动三轴对孔'
}

async function stepMove(axis, sign) {
  const dist = sign * Number(step.value)
  await run(
    () => api.pcManualAxisMove(axis.id, 'rel', dist, axis.jog_vel_fixed),
    `${axis.label} 步进 ${dist > 0 ? '+' : ''}${dist} mm`,
  )
}

async function run(fn, label) {
  try {
    await fn()
    msg.value = `${label} ✓`
  } catch (e) {
    msg.value = `${label} 失败: ${errText(e)}`
  }
}

// ---- 标定数据 ----
const errMsg = errText
function rowLetter(r) {
  let n = r
  let s = ''
  while (n > 0) {
    const rem = (n - 1) % 26
    s = String.fromCharCode(65 + rem) + s
    n = Math.floor((n - 1) / 26)
  }
  return s
}
function wellLabel(r, c) {
  return `${rowLetter(r)}${c}`
}

async function loadInstances() {
  try {
    instances.value = await api.listCalibInstances()
    if (!selectedId.value && instances.value.length) selectInstance(instances.value[0].id)
  } catch (e) {
    msg.value = '加载实例失败: ' + errMsg(e)
  }
}
async function selectInstance(id) {
  selectedId.value = id
  staged.value = {}
  stagedSrc.value = {}
  manualIn.value = {}
  targets.value = null
  pushResult.value = null
  msg.value = ''
  try {
    detail.value = await api.getCalibInstance(id)
    // 手输草稿预填: 已持久化的标定点回填到对应锚孔, 便于核对/微调 (空=未标定)
    const existing = {}
    for (const p of detail.value.points || []) existing[`${p.well[0]},${p.well[1]}`] = p
    const draft = {}
    for (const w of calibWells.value) {
      const e = existing[`${w[0]},${w[1]}`]
      draft[`${w[0]},${w[1]}`] = { x: e ? String(e.x_mm) : '', y: e ? String(e.y_mm) : '' }
    }
    manualIn.value = draft
  } catch (e) {
    msg.value = '加载详情失败: ' + errMsg(e)
  }
}
async function refreshActpos() {
  try {
    actpos.value = await api.readActpos()
    actposErr.value = ''
  } catch (e) {
    actposErr.value = errMsg(e)
  }
}
const actposPoll = usePoll(refreshActpos, 800)
async function capture(w) {
  msg.value = ''
  try {
    const p = await api.captureWell(selectedId.value, w[0], w[1])
    const key = `${w[0]},${w[1]}`
    staged.value = { ...staged.value, [key]: p }
    stagedSrc.value = { ...stagedSrc.value, [key]: '采' }
  } catch (e) {
    msg.value = '采点失败: ' + errMsg(e)
  }
}
// 手输「填入」: 把该孔手输的 4X/3Y 校验后写入 staged (与采点同结构, 复用 commit)
function fillManual(w) {
  const key = `${w[0]},${w[1]}`
  const d = manualIn.value[key] || {}
  const x = Number(d.x)
  const y = Number(d.y)
  if (d.x === '' || d.y === '' || d.x == null || d.y == null || !Number.isFinite(x) || !Number.isFinite(y)) {
    msg.value = `孔 ${wellLabel(w[0], w[1])} 手输需填两个有效数字 (4X / 3Y mm)`
    return
  }
  staged.value = { ...staged.value, [key]: { well: [w[0], w[1]], x_mm: x, y_mm: y } }
  stagedSrc.value = { ...stagedSrc.value, [key]: '输' }
  msg.value = ''
}
async function commit() {
  if (!allStaged.value) return
  const points = calibWells.value.map((w) => staged.value[`${w[0]},${w[1]}`])
  if (!(await confirmAction({
    title: '提交标定并写盘',
    message: '将按下列锚点解 2D 仿射并写入 calibration.yaml, 覆盖该实例当前持久标定。',
    detail: points.map((p) => `${wellLabel(p.well[0], p.well[1])}: X=${p.x_mm} · Y=${p.y_mm}`).join('   '),
    level: 'danger-ack',
    ackText: '我已复核标定值, 写入持久标定',
    confirmText: '提交标定',
  }))) return
  busy.value = true
  msg.value = ''
  try {
    await api.commitCalibration(selectedId.value, points)
    msg.value = '标定已提交并持久化 ✓'
    await selectInstance(selectedId.value)
    await loadInstances()
  } catch (e) {
    msg.value = '提交失败: ' + errMsg(e)
  } finally {
    busy.value = false
  }
}
async function preview() {
  msg.value = ''
  try {
    targets.value = await api.getCalibTargets(selectedId.value)
  } catch (e) {
    msg.value = '预览失败: ' + errMsg(e)
  }
}
async function doPush() {
  const r = Number(pushRow.value)
  const c = Number(pushCol.value)
  const label = wellLabel(r, c)
  // 已预览过全孔时把即将写入的目标值摆进确认框; 未预览则明示值由后端解算
  const known = Array.isArray(targets.value) ? targets.value.find((t) => t.label === label) : null
  if (!(await confirmAction({
    title: `下发孔 ${label} 目标位`,
    message: '将把该孔的绝对目标写入 PLC (*_Target), 由 PLC 既有序列消费, 伺服会实际运动。',
    detail: known
      ? `孔 ${label} (行${r} 列${c}) → 4X=${known.x_mm} · 3Y=${known.y_mm} mm`
      : `孔 ${label} (行${r} 列${c}); 目标值由后端按当前标定解算, 可先「预览全孔」核对`,
    level: 'danger-ack',
    ackText: '我已确认现场无干涉, 允许写入伺服目标位',
    confirmText: '下发',
  }))) return
  msg.value = ''
  pushResult.value = null
  try {
    pushResult.value = await api.pushWell(selectedId.value, r, c)
  } catch (e) {
    msg.value = '下发失败: ' + errMsg(e)
  }
}

onMounted(() => {
  loadInstances()
  actposPoll.start() // immediate 补拍替代原 onMounted 首拍
  manual.loadPoints()
  manual.watchStation(STATION)
})
onBeforeUnmount(() => {
  // 点动的安全停与定时器清理由 useAxisJog 自己的 onBeforeUnmount 负责 (先注册先执行,
  // 正好是"先停轴再停心跳"的次序); actpos 轮询由 usePoll 自清。
  manual.stopPoll()
  manual.stopBeat()
  // 不在这里直接 exit(): 让后端 3.5s TTL 收口, 手滑切走再回来不白丢会话。
  // 但**必须**停心跳 —— 漏掉它会话永不超时, PC_Manual_Active 恒真, 整机卡在电子手动档,
  // FB_Mode 的 `bAuto AND xStart` 让产线再也起不来, 而界面上已经什么都看不到了。
})
</script>

<template>
  <div class="calib">
    <!-- 实例选择 + 实时位置 -->
    <div class="calib-head">
      <select :value="selectedId" aria-label="标定实例" @change="selectInstance($event.target.value)">
        <option v-for="i in instances" :key="i.id" :value="i.id">
          {{ i.label }} ({{ i.plate_type }}) {{ i.is_calibrated ? '✓已标定' : '· 未标定' }}
        </option>
      </select>
      <span v-if="actpos" class="actpos num">
        实时 {{ actpos.x_axis }}={{ actpos.x_mm }} · {{ actpos.y_axis }}={{ actpos.y_mm }} mm
      </span>
      <span v-else-if="actposErr" class="actpos err">ActPos 不可读: {{ actposErr }}</span>
    </div>

    <!-- 手动控制: 开始标定 → PC 单点模式 → 点动三轴对孔 → 采点 -->
    <div class="mc">
      <div class="mc-bar">
        <button type="button" class="sess" :class="{ on: manual.enabled }"
                :disabled="!isDebug || manual.busy"
                :title="isDebug ? '' : '仅 DEBUG 模式可用'" @click="toggleSession">
          {{ manual.busy ? '处理中…' : (manual.enabled ? '结束标定' : '开始标定') }}
        </button>
        <span class="badge" :class="manual.active ? 'ok' : 'idle'">
          {{ manual.active ? '手动控制已生效' : '未生效' }}
        </span>
        <span v-if="disabledReason" class="why">{{ disabledReason }}</span>
        <span class="spacer" />
        <span class="kv">档位 <b>{{ manual.manualAuto ? '自动' : '手动' }}</b></span>
        <span class="kv" :class="{ warn: manual.modeState === 2 || manual.modeState === 3 }">
          设备 <b>{{ modeText }}</b>
        </span>
      </div>

      <div v-if="axes.length" class="mc-axes">
        <div class="mc-step">
          步进
          <div class="chip-group" role="radiogroup" aria-label="步进步长">
            <button v-for="s in STEPS" :key="s" type="button" class="chip"
                    role="radio" :aria-checked="step === s"
                    :class="{ on: step === s }" @click="step = s">{{ s }} mm</button>
          </div>
          <span class="hint">点动速度是 PLC 硬编码常量, 不可调; 步进走相对定位, 速度同点动。</span>
        </div>
        <p class="hint">长按点动仅支持鼠标/触控按住; 键盘请使用步进或目标位下发。</p>
        <div v-for="a in axes" :key="a.id" class="axis">
          <div class="axis-head">
            <span class="role">{{ AXIS_ROLE[a.id] }}</span>
            <span class="name">{{ a.label }}</span>
            <span class="pos">{{ fmt(axisState(a.id).fActPos) }}</span>
            <span v-if="axisMoving(a.id)" class="tag busy">运行中</span>
            <span v-if="axisState(a.id).bEnabled === false" class="tag bad">未使能</span>
            <span v-else-if="axisState(a.id).bHomed" class="tag ok">已回零</span>
            <span v-if="axisState(a.id).bError" class="tag bad">
              错误 {{ axisState(a.id).iErrorCode }}
            </span>
          </div>
          <div class="axis-ctrl">
            <button type="button" class="jog" :class="{ active: jogging === a.id && jogDir === 'neg' }"
                    :disabled="!canDrive"
                    :title="disabledReason || `点动速度 ${a.jog_vel_fixed} mm/s (PLC 固定值)`"
                    :aria-label="`${AXIS_ROLE[a.id] || a.label} 负向点动 (按住)`"
                    @pointerdown="jogPress(a, 'neg', $event)" @pointerup="jogRelease"
                    @pointercancel="jogRelease" @lostpointercapture="jogRelease">− 点动</button>
            <button type="button" class="jog" :class="{ active: jogging === a.id && jogDir === 'pos' }"
                    :disabled="!canDrive"
                    :title="disabledReason || `点动速度 ${a.jog_vel_fixed} mm/s (PLC 固定值)`"
                    :aria-label="`${AXIS_ROLE[a.id] || a.label} 正向点动 (按住)`"
                    @pointerdown="jogPress(a, 'pos', $event)" @pointerup="jogRelease"
                    @pointercancel="jogRelease" @lostpointercapture="jogRelease">点动 +</button>
            <button type="button" class="act" :disabled="!canDrive" :title="disabledReason"
                    @click="stepMove(a, -1)">− {{ step }}</button>
            <button type="button" class="act" :disabled="!canDrive" :title="disabledReason"
                    @click="stepMove(a, 1)">+ {{ step }}</button>
            <button type="button" class="act stop"
                    @click="run(() => api.pcManualAxisStop(a.id), `${a.label} 停止`)">停止</button>
            <button type="button" class="act"
                    @click="run(() => api.pcManualAxisReset(a.id), `${a.label} 清错`)">清错</button>
          </div>
          <div v-if="a.note" class="axis-note">{{ a.note }}</div>
        </div>
        <p class="mc-warn" role="alert">
          ⚠ 点动在 PLC 侧没有互锁 (只有绝对/相对定位有 5Z&lt;3 的门)。降 5Z 前请自行确认针下方无阻挡。
          4X/5Z 的回零需要先做 10 mm 正向退让, 单轴回零通道不做 —— 要回零请去设备页用「一键回原点」。
        </p>
      </div>
      <p v-else class="muted">点表加载中… (若一直为空, 检查 config/manual_points.yaml 的 sampling 工位)</p>
    </div>

    <div v-if="detail && detail.plate" class="calib-body">
      <p class="plate-info">
        {{ detail.label }} · {{ detail.plate.name }} · {{ detail.plate.rows }}×{{ detail.plate.cols }}
        · {{ detail.is_calibrated ? '已标定' : '未标定' }}
      </p>

      <!-- 采点 / 手输: 逐个推荐标定孔 (两法可混用, 都写入同一暂存) -->
      <h4>1. 采点 / 手输 (每锚孔: 点动到位「采点」读实时 ActPos, 或手输已知 4X/3Y 后「填入」)</h4>
      <table class="calib-pts">
        <thead>
          <tr>
            <th scope="col">锚孔</th>
            <th scope="col">采点</th>
            <th scope="col">手输</th>
            <th scope="col">暂存值</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="w in calibWells" :key="`${w[0]},${w[1]}`">
            <th scope="row">
              {{ wellLabel(w[0], w[1]) }}
              <small>(行{{ w[0] }} 列{{ w[1] }})</small>
            </th>
            <td>
              <button @click="capture(w)" title="读实时 ActPos 存为该孔">采点</button>
            </td>
            <td class="manual-in">
              <label>4X <input v-model="manualIn[`${w[0]},${w[1]}`].x" type="number" inputmode="decimal" step="0.001" placeholder="mm" /></label>
              <label>3Y <input v-model="manualIn[`${w[0]},${w[1]}`].y" type="number" inputmode="decimal" step="0.001" placeholder="mm" /></label>
              <button @click="fillManual(w)" title="把手输 4X/3Y 存为该孔">填入</button>
            </td>
            <td class="pt-val num">
              <template v-if="staged[`${w[0]},${w[1]}`]">
                ✓ X={{ staged[`${w[0]},${w[1]}`].x_mm }} · Y={{ staged[`${w[0]},${w[1]}`].y_mm }}
                <small class="src">[{{ stagedSrc[`${w[0]},${w[1]}`] || '?' }}]</small>
              </template>
              <template v-else>未采/未填</template>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 提交 -->
      <h4>2. 提交标定 (solve 仿射 + 写 calibration.yaml)</h4>
      <button :disabled="!allStaged || busy" :aria-busy="busy" @click="commit">
        {{ busy ? '提交中…' : '提交标定 (DEBUG)' }}
      </button>
      <span v-if="!allStaged" class="muted"> 需先采满 {{ calibWells.length }} 个标定孔</span>

      <!-- 预览全孔 -->
      <h4>3. 预览全孔目标 (可选)</h4>
      <button :disabled="!detail.is_calibrated" @click="preview">预览全孔 (X,Y)</button>
      <div v-if="targets" class="targets">
        共 {{ targets.length }} 孔。首 {{ targets[0].label }}=({{ targets[0].x_mm }}, {{ targets[0].y_mm }})
        · 末 {{ targets[targets.length - 1].label }}=({{ targets[targets.length - 1].x_mm }}, {{ targets[targets.length - 1].y_mm }})
      </div>

      <!-- 单孔下发验证 -->
      <h4>4. 单孔下发验证 (写 *_Target, DEBUG)</h4>
      <div class="push-row">
        <label>行 <input v-model="pushRow" type="number" min="1" :max="detail.plate.rows" /></label>
        <label>列 <input v-model="pushCol" type="number" min="1" :max="detail.plate.cols" /></label>
        <button :disabled="!detail.is_calibrated || manual.enabled"
                :title="manual.enabled ? '下发由 PLC 序列消费运动, 请先「结束标定」退出手动控制' : ''"
                @click="doPush">下发到孔 (DEBUG)</button>
        <span v-if="manual.enabled" class="muted">手动控制中不可下发</span>
        <span v-if="pushResult" class="push-res">
          已写 4X={{ pushResult.x_mm }} · 3Y={{ pushResult.y_mm }} mm
        </span>
      </div>

      <p v-if="msg" class="calib-msg" role="status">{{ msg }}</p>
      <p class="muted">
        采点只读伺服实际位置 (*_ActPos)；手输直接录入已知 4X/3Y 值 (免 PLC、离线可做)，两法可混用，
        都经「提交」按 3 点解 2D 仿射并存盘 calibration.yaml；下发把算出的绝对目标写入 PLC (*_Target)，
        由 PLC 既有序列消费运动。全程不写 HMI 示教槽 (单写者)。提交/下发限 DEBUG。
      </p>
    </div>
    <p v-else-if="!instances.length" class="muted">无标定实例 (见 config/calibration.yaml)。</p>
  </div>
</template>

<style scoped>
.calib { font-size: var(--fs-13); }
.calib-head { display: flex; gap: 12px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.calib-head select { padding: 4px 8px; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 4px; }
.actpos { font-family: var(--font-mono); color: var(--accent); }
.actpos.err { color: var(--bad); }

/* 手动控制 */
.mc { margin-bottom: 14px; border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; background: var(--surface-2); }
.mc-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.spacer { flex: 1; }
.sess { padding: 5px 14px; border: 1px solid var(--accent); background: var(--chip-bg); color: var(--accent);
        cursor: pointer; border-radius: 4px; font-weight: 700; }
.sess.on { border-color: var(--bad); background: var(--bad-soft); color: var(--bad); }
.sess:disabled { opacity: 0.45; cursor: not-allowed; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: var(--fs-12); font-weight: 700; }
.badge.ok { background: var(--ok-soft); color: var(--ok-strong); }
.badge.idle { background: var(--muted-soft); color: var(--muted); }
.why { font-size: var(--fs-12); color: var(--warn-strong); }
.kv { font-size: var(--fs-12); color: var(--subtle); }
.kv b { color: var(--text-strong); font-family: var(--font-mono); }
.kv.warn b { color: var(--bad); }

.mc-axes { margin-top: 8px; }
.mc-step { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: var(--fs-12); color: var(--subtle); margin-bottom: 6px; }
.chip-group { display: inline-flex; align-items: center; gap: 6px; }
.chip { padding: 2px 8px; border: 1px solid var(--border); background: var(--panel); color: var(--text);
        border-radius: 10px; cursor: pointer; font-size: var(--fs-12); }
.chip.on { border-color: var(--accent); color: var(--accent); font-weight: 700; }
.mc-step .hint { color: var(--muted); }

.axis { padding: 5px 0; border-top: 1px solid var(--border-soft); }
.axis-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.axis-head .role { font-size: var(--fs-11); padding: 1px 6px; border-radius: 8px; background: var(--chip-bg); color: var(--accent); font-weight: 700; }
.axis-head .name { font-weight: 600; }
.axis-head .pos { font-family: var(--font-mono); color: var(--accent); min-width: 84px; text-align: right; }
.tag { font-size: var(--fs-11); padding: 1px 6px; border-radius: 8px; }
.tag.busy { background: var(--warn-soft); color: var(--warn-strong); }
.tag.ok { background: var(--ok-soft); color: var(--ok-strong); }
.tag.bad { background: var(--bad-soft); color: var(--bad); }
.axis-ctrl { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
.jog { padding: 4px 14px; border: 1px solid var(--accent); background: var(--chip-bg); color: var(--accent);
       border-radius: 4px; cursor: pointer; font-weight: 700; touch-action: none; user-select: none; }
.jog.active { background: var(--accent); color: var(--on-accent); }
.act { padding: 4px 10px; border: 1px solid var(--border); background: var(--panel); color: var(--text);
       border-radius: 4px; cursor: pointer; }
.act.stop { border-color: var(--bad); color: var(--bad); }
.jog:disabled, .act:disabled { opacity: 0.45; cursor: not-allowed; }
.axis-note { font-size: var(--fs-11); color: var(--muted); margin-top: 3px; }
.mc-warn { font-size: var(--fs-12); color: var(--warn-strong); margin: 8px 0 0; }

.plate-info { color: var(--muted); margin: 0 0 10px; }
.calib h4 { margin: 16px 0 6px; font-size: var(--fs-13); color: var(--text); font-weight: 700; }
.calib-pts { border-collapse: collapse; }
.calib-pts th { text-align: right; padding: 3px 12px 3px 0; color: var(--subtle); font-weight: 600; }
.calib-pts thead th { text-align: left; padding: 3px 8px; font-size: var(--fs-12); border-bottom: 1px solid var(--border); }
.calib-pts td { padding: 3px 8px; }
.manual-in { white-space: nowrap; }
.manual-in label { color: var(--subtle); font-size: var(--fs-12); margin-right: 6px; font-weight: 600; }
.manual-in input { width: 84px; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 3px 6px; margin-left: 2px; }
.pt-val { font-family: var(--font-mono); color: var(--ok); }
.pt-val .src { color: var(--muted); }
.calib-body button { padding: 4px 12px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; border-radius: 4px; }
.calib-body button:hover:not(:disabled) { background: var(--hover); }
.calib-body button:disabled { opacity: 0.62; cursor: not-allowed; }
.push-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.push-row input { width: 56px; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 4px; padding: 3px 6px; }
.push-res, .targets { font-family: var(--font-mono); color: var(--accent); margin-top: 6px; }
.calib-msg { font-family: var(--font-mono); font-size: var(--fs-12); margin: 8px 0; color: var(--text); }
.muted { color: var(--muted); margin-top: 12px; font-size: var(--fs-12); }
</style>
