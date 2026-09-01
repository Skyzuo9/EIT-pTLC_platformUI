<script setup>
// 工位单点控制面板 (PC Manual Mode) —— 复刻 HMI 手动屏的"每模块单点操作"
//
// 为什么不走统一 Action API: HMI 手动位是**电平** (阀通电即保持), 点动是**按住持续**,
// 与"一发一终态"的原子动作模型不适配。补偿见 api/manual_routes.py 模块 docstring。
//
// 三层防卡死的第一层在 composables/useAxisJog.js: pointerup / pointercancel /
// lostpointercapture 立刻发 jog_stop, 再叠 visibilitychange / blur / pagehide 安全停。
//
// 展示分组 (develop 缸位×功能矩阵 / 其余按类型瓦片) 是纯前端启发式, 见 utils/manualGroups.js 头注;
// 矩阵解析失败整体回退瓦片路径, 不半渲染。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useAxisJog } from '../composables/useAxisJog'
import { useManualStore } from '../stores/manual'
import { useSystemStore } from '../store'
import { modeStateText } from '../utils/deviceLabels.js'
import { axisShortName, buildDevelopMatrix, buildGroups } from '../utils/manualGroups'

const props = defineProps({ station: { type: String, required: true } })

const manual = useManualStore()
const sys = useSystemStore()

const result = ref(null)
const isDebug = computed(() => sys.mode === 'DEBUG')
// 唯一权威是 PLC 回来的 PC_Manual_Active: 没它, 写下去的位不会被 FB 采纳
const canDrive = computed(() => isDebug.value && manual.active)

const disabledReason = computed(() => {
  if (!isDebug.value) return '仅 DEBUG 模式可用 (在顶部态势条切换)'
  if (!manual.enabled) return '请先进入单点控制模式'
  if (!manual.active) return manual.rejectText || 'PLC 尚未确认单点模式生效'
  return ''
})

const modeText = computed(() => modeStateText(manual.modeState))

const cylinders = computed(() => manual.stationPoints.cylinders || [])
const axes = computed(() => manual.stationPoints.axes || [])
const cylState = (id) => manual.state?.cylinders?.[id] || {}
const axisState = (id) => manual.state?.axes?.[id] || {}

// develop 命中矩阵则两张展缸卡, 否则按类型瓦片分组 (二选一渲染)
const developMatrix = computed(() => buildDevelopMatrix(cylinders.value))
const cylGroups = computed(() => buildGroups(cylinders.value))

function fmt(v, digits = 2) {
  return typeof v === 'number' ? v.toFixed(digits) : '—'
}

// 「运行中」按实际速度判, 不能用 bBusy: FB_SERVOAXIS 的 bBusy 含 MC_Power.Busy,
// 而汇川 SM3 在使能期间它恒为 TRUE (PLC 源码原话), 拿来显示会 11 根轴全程常亮。
// 排除 MC_Power 的 bMotionBusy 没接到 <轴>DATE 结构体, 上位机取不到。
function axisMoving(id) {
  const v = axisState(id).fActVel
  return typeof v === 'number' && Math.abs(v) > 0.01
}

async function call(fn, label) {
  try {
    const data = await fn()
    result.value = { ok: true, message: `${label} ✓`, data }
  } catch (e) {
    result.value = { ok: false, message: `${label} 失败: ${errText(e)}` }
  }
}

// ---- 会话 ----
// 进入单点不再要求先停机: PLC 会被切到电子手动档, 上位机只写手动位, L2 派发器写的
// 自动位一律被 FB 忽略, 不存在两个写者。手动档下「启动」也不被 FB_Mode 接受,
// 所以会话期间机器不可能被谁启动起来。
const MODE_RUNNING = 1
const machineRunning = computed(() => manual.modeState === MODE_RUNNING)

async function toggleSession() {
  if (manual.enabled) {
    if (!(await confirmAction({
      title: '退出单点模式',
      message: ['会把全部执行器的手动位清零, 并把档位交还给自动。', '各执行器随即恢复听流程的自动位。'],
      level: 'danger',
      confirmText: '退出单点',
    }))) return
    await manual.exit()
    return
  }
  await manual.enter()
  if (manual.error) {
    result.value = { ok: false, message: `进入失败: ${manual.error}` }
  }
}

// 停机/恢复运行是独立能力 (脉冲 PLCStop/PLCStart, 与柜面按钮并联), 与单点模式无关 ——
// 单点已经不需要停机了, 但想让产线停下来时不必跑去柜子。
async function stopMachine() {
  if (!(await confirmAction({
    title: '停机',
    message: '会中断生产 (等效按柜面「停止」)。',
    level: 'danger',
    confirmText: '停机',
  }))) return
  await call(() => api.pcManualMachineStop(), '停机')
  await manual.refresh()
}

async function resumeRun() {
  if (!(await confirmAction({
    title: '恢复运行',
    message: '设备将重新接受流程派发 (等效按柜面「启动」)。',
    level: 'danger',
    confirmText: '恢复运行',
  }))) return
  await call(() => api.pcManualMachineResume(), '恢复运行')
  await manual.refresh()
}

async function homeAll() {
  if (!(await confirmAction({
    title: '一键回原点',
    message: '会驱动全部 11 根轴运动。',
    level: 'danger',
    confirmText: '回原点',
  }))) return
  await call(() => api.pcManualHomeAll(), '一键回原点')
}

// ---- 气缸: 电平二态 ----
// 高频调试直驱按定案走两段式武装 (弹模态会造成确认疲劳→文化性绕过): 首点按钮原地变
// 「再点确认」, 3 秒不二点自动撤防。行来自动态点表, 实例按 气缸×电平 建 (共用一个实例
// 会让武装跨按钮串台: A 钮首点武装, B 钮一点即发)。点表到达即在 watch 里预建 —— 渲染路径
// 只读不建, 免得在 render 上下文里注册生命周期钩子。
const cylActs = new Map()
function cylAct(cyl, on) {
  const key = `${cyl.id}:${on ? '1' : '0'}`
  let act = cylActs.get(key)
  if (!act) {
    act = useAsyncAction(
      async () => {
        await call(() => api.pcManualCylinder(cyl.id, on), `${cyl.label} ${on ? '开' : '关'}`)
        await manual.refresh()
      },
      { minInterval: 350, arm: { label: '再点确认', timeoutMs: 3000 } },
    )
    cylActs.set(key, act)
  }
  return act
}
watch(cylinders, (list) => {
  for (const c of list || []) {
    cylAct(c, true)
    cylAct(c, false)
  }
}, { immediate: true })
function setCylinder(cyl, on) {
  const act = cylAct(cyl, on)
  if (!act.armed) {
    // 新武装前撤防其它钮: 同屏只留一个「再点确认」, 防把别的钮误当二次确认点下去
    for (const other of cylActs.values()) {
      if (other !== act) other.disarm()
    }
  }
  act.run()
}
// 矩阵格的列语义 (进液/排液/吹气) 仅视觉, 读屏用整名; 武装态一并播出去
function cylBtnLabel(cyl, on) {
  const base = `${cyl.label} ${on ? '开' : '关'}`
  return cylAct(cyl, on).armed ? `${base} (再点确认)` : base
}

// ---- 轴点动: 按住起 / 松开停 + 按住期间续订 ----
// 代次令牌、pointer capture、窗口级安全停与卸载清理全在 useAxisJog 里 (与孔板标定页共用)
const { jogging, jogDown, stopJog } = useAxisJog({
  canDrive,
  onError: (message) => { result.value = { ok: false, message } },
})
// 高亮方向修正: jogging 只记轴不记方向, 两个方向钮的 active 条件曾相同 → 任一方向双高亮。
// 仅在外围记录按下方向 (useAxisJog 本体不动); 安全停路径直接清 jogging, 高亮以 jogging 为准,
// jogDir 残值无害 (下一次按下会覆盖)。
const jogDir = ref('') // 'neg' | 'pos' | ''
function jogPress(axis, dir, event) {
  jogDir.value = dir
  jogDown(axis, dir, event)
}
function jogRelease() {
  jogDir.value = ''
  stopJog()
}

// ---- 轴其它动作 ----
const moveTarget = ref({})
const moveVel = ref({})
const moveMode = ref({})

async function doMove(axis) {
  const target = Number(moveTarget.value[axis.id])
  if (!Number.isFinite(target)) {
    result.value = { ok: false, message: `${axis.label}: 目标位置必须是数字` }
    return
  }
  const velRaw = Number(moveVel.value[axis.id])
  const vel = Number.isFinite(velRaw) && velRaw > 0 ? Math.min(velRaw, axis.vel_max) : axis.vel_max
  const mode = moveMode.value[axis.id] || 'abs'
  await call(() => api.pcManualAxisMove(axis.id, mode, target, vel),
    `${axis.label} ${mode === 'abs' ? '绝对' : '相对'}定位`)
}

// 「清错」= 复位伺服故障: 故障轴带电复位可能立即恢复力矩, 先确认机构无卡阻
async function resetAxis(a) {
  if (!(await confirmAction({
    title: `复位 ${a.label} 伺服故障`,
    message: '复位伺服故障, 请先确认机构无卡阻。',
    level: 'danger',
    confirmText: '清错',
  }))) return
  await call(() => api.pcManualAxisReset(a.id), `${a.label} 清错`)
}

// 轴动作防连点: 照 cylActs 模式按 轴×动作 预建 (渲染路径只读不建)。
// 「停止」故意不入 map —— 安全出口保持裸 call, 永不因 busy/canDrive 设阻 (与原版一致)。
const axisActs = new Map()
function axisAct(a, kind) {
  const key = `${a.id}:${kind}`
  let act = axisActs.get(key)
  if (!act) {
    const runners = {
      home: () => call(() => api.pcManualAxisHome(a.id), `${a.label} 回零`),
      move: () => doMove(a),
      reset: () => resetAxis(a),
    }
    act = useAsyncAction(runners[kind], { minInterval: 350 })
    axisActs.set(key, act)
  }
  return act
}
watch(axes, (list) => {
  for (const a of list || []) {
    axisAct(a, 'home')
    axisAct(a, 'move')
    axisAct(a, 'reset')
  }
}, { immediate: true })

onMounted(() => {
  manual.loadPoints()
  manual.watchStation(props.station)
})

watch(() => props.station, (s) => manual.watchStation(s))

onBeforeUnmount(() => {
  // 点动的安全停与定时器清理由 useAxisJog 自己的 onBeforeUnmount 负责 (它先于本钩子注册,
  // 故先于本钩子执行 —— 正好是"先停轴再停心跳"的次序)。
  manual.stopPoll()
  manual.stopBeat()
  // 不在这里直接 exit(), 而是把心跳停掉、让后端 3.5s TTL 收口:
  //   · TTL 自带宽限期, 手滑点开又切回来不会白丢会话;
  //   · 工位之间切换 (/nodes/plc.a -> plc.b) 是同一组件实例更新 props, 本钩子根本不触发,
  //     所以那条路径不受影响 —— 真正离开工位页才会走到这里。
  // 但**必须**停心跳: 漏掉它的话会话永不超时, PC_Manual_Active 恒真 ⇒ 整机一直卡在
  // 电子手动档 ⇒ FB_Mode 的 `bAuto AND xStart` 让「启动」永远不被接受, 产线起不来,
  // 而界面上已经什么都看不到了。
})
</script>

<template>
  <div v-if="cylinders.length || axes.length" class="manual">
    <!-- 顶栏三簇: 会话 | 状态回显 | 全局动作 (逐钮行为与原版相同, 仅视觉分簇) -->
    <div class="bar">
      <div class="bar-session">
        <button type="button" class="sess" :class="{ on: manual.enabled }"
                :disabled="!isDebug || manual.busy"
                :title="isDebug ? '' : '仅 DEBUG 模式可用'" @click="toggleSession">
          {{ manual.busy ? '处理中…' : (manual.enabled ? '退出单点模式' : '进入单点模式') }}
        </button>
        <span class="badge" :class="manual.active ? 'ok' : 'idle'">
          {{ manual.active ? '单点已生效' : '未生效' }}
        </span>
        <span v-if="disabledReason" class="why">{{ disabledReason }}</span>
      </div>
      <div class="bar-state">
        <span class="kv">档位
          <b>{{ manual.manualAuto ? '自动' : '手动' }}</b>
          <em v-if="manual.active" class="by-pc">上位机接管</em>
        </span>
        <span class="kv">设备 <b>{{ modeText }}</b></span>
        <span class="kv" :class="{ warn: manual.alarmWord }">气缸报警字 <b>{{ manual.alarmWord }}</b></span>
      </div>
      <!-- 停机/恢复运行与柜面按钮并联; 单点模式本身不需要它们, 纯粹是省一趟腿 -->
      <div class="bar-global">
        <button v-if="machineRunning && !manual.enabled" type="button" class="act stop"
                :disabled="!isDebug || manual.busy"
                :title="isDebug ? '脉冲 PLCStop, 等效柜面「停止」' : '仅 DEBUG 模式可用'"
                @click="stopMachine">停机</button>
        <button v-if="!machineRunning && !manual.enabled" type="button" class="resume"
                :disabled="!isDebug || manual.busy"
                :title="isDebug ? '脉冲 PLCStart, 等效柜面「启动」(需自动档)' : '仅 DEBUG 模式可用'"
                @click="resumeRun">恢复运行</button>
        <button type="button" class="home-all" :disabled="!canDrive"
                :title="disabledReason || '全部 11 根轴按 PLC 内既定次序回零'" @click="homeAll">
          一键回原点
        </button>
      </div>
    </div>

    <div v-if="result" class="result" :class="{ bad: !result.ok }" role="status">{{ result.message }}</div>

    <!-- develop 矩阵: 每张展缸卡一行一个缸位, 列 = 该缸位的气缸与三路阀 (相关性归位) -->
    <template v-if="developMatrix">
      <section v-for="tk in developMatrix.tanks" :key="tk.tank" class="subpanel">
        <div class="subpanel-caption">展缸{{ tk.tank }}</div>
        <p class="hint">每行一个缸位; 电池阀无到位传感器, 仅显示命令态。</p>
        <table class="matrix">
          <thead>
            <tr><th class="mx-idx">缸位</th><th>气缸</th><th>进液</th><th>排液</th><th>吹气</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in tk.rows" :key="row.idx" :class="{ alarm: cylState(row.cyl.id).alarm }">
              <th scope="row" class="mx-idx num">{{ row.idx }}</th>
              <td>
                <span class="mx-btns">
                  <button type="button" class="tg" :class="{ on: cylState(row.cyl.id).manual, armed: cylAct(row.cyl, true).armed }"
                          :disabled="!canDrive || cylAct(row.cyl, true).busy" :title="disabledReason"
                          :aria-label="cylBtnLabel(row.cyl, true)"
                          @click="setCylinder(row.cyl, true)">{{ cylAct(row.cyl, true).armed ? cylAct(row.cyl, true).armedLabel : '开' }}</button>
                  <button type="button" class="tg" :class="{ off: cylState(row.cyl.id).manual === false, armed: cylAct(row.cyl, false).armed }"
                          :disabled="!canDrive || cylAct(row.cyl, false).busy" :title="disabledReason"
                          :aria-label="cylBtnLabel(row.cyl, false)"
                          @click="setCylinder(row.cyl, false)">{{ cylAct(row.cyl, false).armed ? cylAct(row.cyl, false).armedLabel : '关' }}</button>
                </span>
                <span class="mx-fb">
                  <span v-if="row.cyl.has_fb_off" class="lamp" :class="{ lit: cylState(row.cyl.id).fb_off }"
                        :title="`原点/缩回到位: ${cylState(row.cyl.id).fb_off ? '到位' : '未到位'}`"
                        :aria-label="`原点${cylState(row.cyl.id).fb_off ? '到位' : '未到位'}`">原</span>
                  <span v-if="row.cyl.has_fb_on" class="lamp" :class="{ lit: cylState(row.cyl.id).fb_on }"
                        :title="`动点/伸出到位: ${cylState(row.cyl.id).fb_on ? '到位' : '未到位'}`"
                        :aria-label="`动点${cylState(row.cyl.id).fb_on ? '到位' : '未到位'}`">动</span>
                  <span v-if="cylState(row.cyl.id).alarm" class="alarm-tag" role="alert">报警</span>
                  <span v-if="cylState(row.cyl.id).auto" class="auto-mini" title="自动位 ON (流程派发的命令电平, 只读)">自</span>
                </span>
              </td>
              <td v-for="valve in [row.fill, row.drain, row.blow]" :key="valve.id">
                <span class="mx-btns">
                  <button type="button" class="tg" :class="{ on: cylState(valve.id).manual, armed: cylAct(valve, true).armed }"
                          :disabled="!canDrive || cylAct(valve, true).busy" :title="disabledReason"
                          :aria-label="cylBtnLabel(valve, true)"
                          @click="setCylinder(valve, true)">{{ cylAct(valve, true).armed ? cylAct(valve, true).armedLabel : '开' }}</button>
                  <button type="button" class="tg" :class="{ off: cylState(valve.id).manual === false, armed: cylAct(valve, false).armed }"
                          :disabled="!canDrive || cylAct(valve, false).busy" :title="disabledReason"
                          :aria-label="cylBtnLabel(valve, false)"
                          @click="setCylinder(valve, false)">{{ cylAct(valve, false).armed ? cylAct(valve, false).armedLabel : '关' }}</button>
                </span>
                <span v-if="cylState(valve.id).auto" class="auto-mini" title="自动位 ON (流程派发的命令电平, 只读)">自</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>

    <!-- 通用路径: 按类型分组的瓦片流 (气缸/电磁阀/泵/电机/其他) -->
    <template v-else>
      <section v-for="g in cylGroups" :key="g.key" class="subpanel">
        <div class="subpanel-caption">{{ g.title }} ({{ g.items.length }})</div>
        <div class="tile-grid">
          <div v-for="c in g.items" :key="c.id" class="dev-tile" :class="{ alarm: cylState(c.id).alarm }">
            <div class="tile-head">
              <span class="tile-name">{{ c.label }}</span>
              <span v-if="cylState(c.id).alarm" class="alarm-tag" role="alert">报警</span>
              <span class="auto-pill" :class="{ on: cylState(c.id).auto }"
                    title="自动位 (流程派发的命令电平, 只读)">
                自动位 {{ cylState(c.id).auto === undefined ? '—' : (cylState(c.id).auto ? 'ON' : 'off') }}
              </span>
            </div>
            <div class="tile-ctrl">
              <button type="button" class="tg" :class="{ on: cylState(c.id).manual, armed: cylAct(c, true).armed }"
                      :disabled="!canDrive || cylAct(c, true).busy" :title="disabledReason"
                      :aria-label="cylBtnLabel(c, true)"
                      @click="setCylinder(c, true)">{{ cylAct(c, true).armed ? cylAct(c, true).armedLabel : '开' }}</button>
              <button type="button" class="tg" :class="{ off: cylState(c.id).manual === false, armed: cylAct(c, false).armed }"
                      :disabled="!canDrive || cylAct(c, false).busy" :title="disabledReason"
                      :aria-label="cylBtnLabel(c, false)"
                      @click="setCylinder(c, false)">{{ cylAct(c, false).armed ? cylAct(c, false).armedLabel : '关' }}</button>
              <span v-if="c.has_fb_off" class="lamp" :class="{ lit: cylState(c.id).fb_off }"
                    :title="`原点/缩回到位: ${cylState(c.id).fb_off ? '到位' : '未到位'}`"
                    :aria-label="`原点${cylState(c.id).fb_off ? '到位' : '未到位'}`">原</span>
              <span v-if="c.has_fb_on" class="lamp" :class="{ lit: cylState(c.id).fb_on }"
                    :title="`动点/伸出到位: ${cylState(c.id).fb_on ? '到位' : '未到位'}`"
                    :aria-label="`动点${cylState(c.id).fb_on ? '到位' : '未到位'}`">动</span>
              <span v-if="!c.has_fb_on && !c.has_fb_off" class="none">无传感器</span>
            </div>
            <div v-if="c.note" class="tile-note">{{ c.note }}</div>
          </div>
        </div>
      </section>
    </template>

    <!-- 伺服轴: 每轴一张卡, 自适应多列 (点动行借机器人面板的全局 .jog-row 配方) -->
    <section v-if="axes.length" class="subpanel">
      <div class="subpanel-caption">伺服轴 ({{ axes.length }})</div>
      <p class="hint">长按点动仅支持鼠标/触控按住; 键盘请使用步进或目标位下发。</p>
      <div class="axis-grid">
        <div v-for="a in axes" :key="a.id" class="axis-card">
          <div class="axis-head">
            <span class="name">{{ a.label }}</span>
            <span v-if="axisMoving(a.id)" class="tag busy">运行中</span>
            <span v-if="axisState(a.id).bHomed" class="tag ok">已回零</span>
            <span v-if="axisState(a.id).bError" class="tag bad">
              错误 {{ axisState(a.id).iErrorCode }}
            </span>
          </div>
          <div class="jog-row">
            <button type="button" class="side-btn" :class="{ active: jogging === a.id && jogDir === 'neg' }"
                    :disabled="!canDrive" :title="disabledReason || `点动速度 ${a.jog_vel_fixed} (PLC 固定值, 不可调)`"
                    :aria-label="`${a.label} 负向点动 (按住)`"
                    @pointerdown="jogPress(a, 'neg', $event)" @pointerup="jogRelease"
                    @pointercancel="jogRelease" @lostpointercapture="jogRelease">−</button>
            <div class="value-rail">
              <span class="axis-pill">{{ axisShortName(a.id) }}</span>
              <span class="axis-value num">{{ fmt(axisState(a.id).fActPos) }}</span>
            </div>
            <button type="button" class="side-btn" :class="{ active: jogging === a.id && jogDir === 'pos' }"
                    :disabled="!canDrive" :title="disabledReason || `点动速度 ${a.jog_vel_fixed} (PLC 固定值, 不可调)`"
                    :aria-label="`${a.label} 正向点动 (按住)`"
                    @pointerdown="jogPress(a, 'pos', $event)" @pointerup="jogRelease"
                    @pointercancel="jogRelease" @lostpointercapture="jogRelease">+</button>
          </div>
          <div class="axis-ops">
            <button type="button" class="act" :disabled="!canDrive || axisAct(a, 'home').busy"
                    :aria-busy="axisAct(a, 'home').busy" :title="disabledReason"
                    @click="axisAct(a, 'home').run()">回零</button>
            <button type="button" class="act stop"
                    @click="call(() => api.pcManualAxisStop(a.id), `${a.label} 停止`)">停止</button>
            <button type="button" class="act" :disabled="axisAct(a, 'reset').busy"
                    :aria-busy="axisAct(a, 'reset').busy"
                    @click="axisAct(a, 'reset').run()">清错</button>
            <select v-model="moveMode[a.id]" class="mv-mode" :disabled="!canDrive"
                    :aria-label="`${a.label} 定位模式`">
              <option value="abs">绝对</option>
              <option value="rel">相对</option>
            </select>
            <input v-model="moveTarget[a.id]" class="mv" type="number" step="0.1" inputmode="decimal"
                   placeholder="目标" :aria-label="`${a.label} 目标位置`" :disabled="!canDrive">
            <input v-model="moveVel[a.id]" class="mv" type="number" step="1" inputmode="numeric"
                   :max="a.vel_max" min="0"
                   :placeholder="`速度≤${a.vel_max}`" :aria-label="`${a.label} 速度, 上限 ${a.vel_max}`"
                   :disabled="!canDrive">
            <button type="button" class="act" :disabled="!canDrive || axisAct(a, 'move').busy"
                    :aria-busy="axisAct(a, 'move').busy" :title="disabledReason"
                    @click="axisAct(a, 'move').run()">执行</button>
          </div>
          <div v-if="a.note" class="axis-note">{{ a.note }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* 外壳: 照机器人 .movement-shell 的浅层底 shell, 内嵌 .subpanel 白卡 (全局配方) */
.manual { margin: 10px 0 14px; padding: 12px; display: grid; gap: 12px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-lg); }

/* 顶栏三簇: 会话在左, 状态回显与全局动作靠右 */
.bar { display: flex; align-items: center; gap: 8px 14px; flex-wrap: wrap; }
.bar-session, .bar-state, .bar-global { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.bar-state { margin-left: auto; }
/* 面板门户动作 = 实心主按钮 (eit 按钮语言: 实底, hover 只压深); 进入后转红描边 = 退出方向 */
.sess { padding: 5px 14px; border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent);
        cursor: pointer; border-radius: var(--radius-md); font-weight: 700; }
.sess:hover:not(:disabled) { background: var(--accent-strong); border-color: var(--accent-strong); }
.sess.on { border-color: var(--bad); background: var(--bad-soft); color: var(--bad); }
.sess.on:hover:not(:disabled) { background: var(--bad-soft); border-color: var(--bad-strong); color: var(--bad-strong); }
.sess:disabled, .home-all:disabled { opacity: 0.45; cursor: not-allowed; }
.home-all { padding: 5px 12px; border: 1px solid var(--warn); background: var(--warn-soft);
            color: var(--warn-strong); cursor: pointer; border-radius: var(--radius-md); font-weight: 600; }
.home-all:hover:not(:disabled) { border-color: var(--warn-strong); }
.resume { padding: 5px 12px; border: 1px solid var(--ok); background: var(--ok-soft);
          color: var(--ok-strong); cursor: pointer; border-radius: var(--radius-md); font-weight: 600; }
.resume:disabled { opacity: 0.45; cursor: not-allowed; }
.badge { padding: 2px 8px; border-radius: 999px; font-size: var(--fs-12); font-weight: 700; }
.badge.ok { background: var(--ok-soft); color: var(--ok-strong); }
.badge.idle { background: var(--chip-bg); color: var(--muted); }
.why { font-size: var(--fs-12); color: var(--warn-strong); }
/* width:auto 挡掉全局表格 .kv 的 width:100% (flex 里 inline 被块化后会一行一个) */
.kv { width: auto; font-size: var(--fs-12); color: var(--subtle); }
.kv b { color: var(--text-strong); font-family: var(--font-mono); }
.by-pc { margin-left: 4px; font-style: normal; padding: 1px 5px; border-radius: 999px;
         background: var(--accent); color: var(--on-accent); font-size: var(--fs-11); }
.kv.warn b { color: var(--bad); }
/* 回执行: 间距交给外壳 grid gap (全局 .result 的盒样式保留) */
.result { margin: 0; font-family: var(--font-mono); font-size: var(--fs-12); color: var(--ok-strong); }
.result.bad { color: var(--bad); }
/* 卡内提示行: 紧贴 caption */
.subpanel .hint { margin: -6px 0 10px; }

/* develop 缸位×功能矩阵 */
.matrix { width: 100%; border-collapse: collapse; font-size: var(--fs-13); }
.matrix thead th { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--border);
  color: var(--subtle); font-weight: 600; font-size: var(--fs-12); }
.matrix td, .matrix tbody th { padding: 5px 6px; border-bottom: 1px solid var(--border-soft);
  vertical-align: middle; }
.matrix tbody tr:last-child td, .matrix tbody tr:last-child th { border-bottom: none; }
.matrix tbody th { text-align: left; width: 40px; color: var(--subtle); font-weight: 600; }
.matrix tr.alarm { background: var(--bad-soft); }
.mx-btns { display: inline-flex; gap: 4px; }
.mx-fb { display: inline-flex; gap: 4px; align-items: center; margin-left: 8px; }
.auto-mini { margin-left: 6px; padding: 0 5px; border-radius: 999px; background: var(--accent);
  color: var(--on-accent); font-size: var(--fs-11); font-weight: 700; }

/* 通用瓦片流 */
.tile-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 8px; }
.dev-tile { display: grid; gap: 6px; align-content: start; padding: 8px 10px;
  background: var(--surface-2); border: 1px solid var(--border-soft); border-radius: var(--radius-md); }
.dev-tile.alarm { border-color: var(--bad); background: var(--bad-soft); }
.tile-head { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tile-name { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.auto-pill { margin-left: auto; padding: 1px 8px; border-radius: 999px; font-size: var(--fs-11);
  font-weight: 650; background: var(--chip-bg); color: var(--subtle); white-space: nowrap; }
.auto-pill.on { background: var(--accent); color: var(--on-accent); }
.tile-ctrl { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tile-note { font-size: var(--fs-12); color: var(--subtle); }

/* 开/关电平钮与到位灯 (矩阵/瓦片共用) */
.tg { padding: 4px 14px; border: 1px solid var(--border); background: var(--panel);
      color: var(--text); cursor: pointer; border-radius: var(--radius-md); font-weight: 600; }
/* :where 压零特异度: 悬停提示只作用于中性态 (可点方向), .on/.off/.armed 状态色按特异度照常压过 */
.tg:where(:hover:not(:disabled)) { border-color: var(--accent); color: var(--accent); }
.tg.on { border-color: var(--ok); background: var(--ok-soft); color: var(--ok-strong); font-weight: 700; }
.tg.off { border-color: var(--muted); color: var(--muted); }
/* 两段式武装态: 首点后原地变「再点确认」; 声明在 .on/.off 之后, 武装期以警示色为准 */
.tg.armed { border-color: var(--warn); background: var(--warn-soft); color: var(--warn-strong); font-weight: 700; }
.tg:disabled { opacity: 0.45; cursor: not-allowed; }
/* 报警文字徽标: 行/瓦片背景色之外的显式文字层 (不只靠颜色) */
.alarm-tag { padding: 1px 6px; border-radius: 999px; background: var(--bad);
             color: var(--on-accent); font-size: var(--fs-11); font-weight: 700; }
.lamp { display: inline-block; min-width: 22px; text-align: center; border-radius: var(--radius-md);
        background: var(--chip-bg); color: var(--muted); font-size: var(--fs-12); }
.lamp.lit { background: var(--ok-soft); color: var(--ok-strong); font-weight: 700; }
.none { color: var(--subtle); font-size: var(--fs-12); }

/* 伺服轴卡片网格 */
.axis-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 8px; }
.axis-card { display: grid; gap: 8px; align-content: start; padding: 10px;
  background: var(--surface-2); border: 1px solid var(--border-soft); border-radius: var(--radius-md); }
/* 卡底已是 surface-2, 数值药丸换面板底保持对比 (全局 .value-rail 默认 surface-2) */
.axis-card .value-rail { background: var(--panel); }
.axis-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.axis-head .name { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.tag { padding: 1px 6px; border-radius: 999px; font-size: var(--fs-11); }
.tag.busy { background: var(--warn-soft); color: var(--warn-strong); }
.tag.ok { background: var(--ok-soft); color: var(--ok-strong); }
.tag.bad { background: var(--bad-soft); color: var(--bad); }
.axis-ops { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.act { padding: 4px 12px; border: 1px solid var(--border); background: var(--panel); color: var(--text);
       cursor: pointer; border-radius: var(--radius-md); }
/* 同 .tg: 中性态悬停提示; .stop 是安全出口, 恒定红描边不做 hover 戏法 */
.act:where(:hover:not(:disabled)) { border-color: var(--accent); color: var(--accent); }
.act.stop { border-color: var(--bad); color: var(--bad); }
.act:disabled, .mv:disabled, .mv-mode:disabled { opacity: 0.45; cursor: not-allowed; }
.mv { width: 88px; padding: 3px 6px; border: 1px solid var(--border); background: var(--field-bg);
      color: var(--text); border-radius: var(--radius-md); font-family: var(--font-mono); }
.mv-mode { padding: 3px; border: 1px solid var(--border); background: var(--field-bg); color: var(--text);
      border-radius: var(--radius-md); }
.axis-note { font-size: var(--fs-12); color: var(--subtle); }
</style>
