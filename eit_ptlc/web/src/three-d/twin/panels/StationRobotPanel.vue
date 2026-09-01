<script setup>
/**
 * 功能: 机械臂工位的操控面板 —— 三维实时页版, 对标二维设备页的 RobotJogPanel.
 *
 * 为什么另起一个而不是 import 二维那个: 它 1308 行、零子组件, 且整套 CSS 用的是二维主题
 * 变量(--panel/--surface-2/--fs-13), 与坞的 dock.css 变量体系(--control/--text-dim)不同。
 * 真正该共用的是**点动状态机**, 那部分已经抽成 composables/useRobotJog.js, 两页共用一份。
 *
 * 三维页相对二维页的唯一天然优势: 位姿取 20 Hz 的 robot_pose 插值(realtime.robot.joint/pose),
 * 而二维页读的是 1 Hz 的 telemetry —— 点动时数值跟不跟手全看这个。
 *
 * ⚠ 机械臂**不走** PLC 单点会话(/api/manual/*), 它有自己的 /api/robot/* 十条端点。
 *   所以本面板不看 manual.canWrite, 只看控制模式门(DEBUG)与连接状态。
 */
import { computed, ref, watch } from 'vue'

import { api } from '../../../api.js'
import { confirmAction } from '../../../composables/confirmService.js'
import { useEstop } from '../../../composables/useEstop.js'
import { useRobotJog } from '../../../composables/useRobotJog.js'

const props = defineProps({
  /** 机械臂节点的 1 Hz 遥测快照(tool_state / speed_factor / connected 等) */
  snapshot: { type: Object, default: null },
  /** TwinFeed.realtimeStatus() 载荷(robot.joint / robot.pose 是 20 Hz 的) */
  realtime: { type: Object, default: () => ({}) },
  /** 节点健康度(offline 时出断联横幅) */
  health: { type: String, default: '' },
  /** 当前控制模式(非 DEBUG 时写操作置灰; 后端 403 是第二道保险) */
  controlMode: { type: String, default: '' },
})

/**
 * 轴行模型.
 * kind 决定: 步进插补(joint→j, 其余→l) / 步长字段(translate→mm, 其余→deg) / 取数下标。
 * 连续令牌 = axis+'+' / axis+'-'(对齐 robot.jog_start 的 24 值枚举);
 * 步进轴 = axis(对齐 robot.step 的 12 值枚举)。顺序与二维页一致, 免得两处对不上。
 */
const TCP_ROWS = [
  { axis: 'Rx', kind: 'rotate', idx: 3, unit: '°', accent: 'rx-accent' },
  { axis: 'Ry', kind: 'rotate', idx: 4, unit: '°', accent: 'ry-accent' },
  { axis: 'Rz', kind: 'rotate', idx: 5, unit: '°', accent: 'rz-accent' },
  { axis: 'X', kind: 'translate', idx: 0, unit: 'mm', accent: 'x-accent' },
  { axis: 'Y', kind: 'translate', idx: 1, unit: 'mm', accent: 'y-accent' },
  { axis: 'Z', kind: 'translate', idx: 2, unit: 'mm', accent: 'z-accent' },
]
const JOINT_ROWS = Array.from({ length: 6 }, (_v, i) => ({
  axis: `J${i + 1}`, kind: 'joint', idx: i, unit: '°', accent: 'joint-accent',
}))

/**
 * 末端语义 IO —— 走后端白名单 robot.tool_action(带安全联锁与时序), 不是裸 DO.
 * 语义位(tool_state.actual_bits / commanded_bits): bit0=DO1 快换(0锁/1松),
 * bit1=DO3 真空, bit2=DO2 夹爪(0开/1合)。旋转走 DO6+DO2 配合, 后端不回读语义位,
 * 故只触发不高亮(active 缺省即为不高亮)。
 */
const TOOL_GROUPS = [
  { label: '快换', btns: [
    { text: '锁紧', action: 'quick-change-lock', active: (b) => (b & 1) === 0 },
    { text: '松开', action: 'quick-change-release', active: (b) => (b & 1) === 1 },
  ] },
  { label: '真空', btns: [
    { text: '开', action: 'suction-on', active: (b) => (b & 2) !== 0 },
    { text: '关', action: 'suction-off', active: (b) => (b & 2) === 0 },
  ] },
  { label: '夹爪', btns: [
    { text: '张开', action: 'gripper-open', active: (b) => (b & 4) === 0 },
    { text: '闭合', action: 'gripper-close', active: (b) => (b & 4) !== 0 },
  ] },
  { label: '旋转', btns: [
    { text: '上升', action: 'rotary-up' },
    { text: '下降', action: 'rotary-down' },
  ] },
]

/** 松开类动作要过 danger-ack: 手上可能正夹着一块板 */
const RELEASE_TOOL_ACTIONS = new Set(['quick-change-release', 'gripper-open', 'suction-off'])

const result = ref(null)
const message = ref('')
const speedInput = ref(null)

/**
 * 点动是否已启用(机械臂版的"进入单点模式").
 *
 * 机械臂不走 PLC 单点会话(/api/manual/*), 但"点动控件收进一道门后 + 进入时警示"
 * 这条纪律对它同样成立 —— 用本地 arm 态复刻: 未启用时 12 行只显读数,
 * 点「启用点动」过一次 danger-ack(谨慎操作 + 以实机为准)后放开。
 * 组件按工位 :key 重挂, 切走自动撤防。
 */
const jogArmed = ref(false)

const { emergencyStop } = useEstop()

const offline = computed(() => props.health === 'offline')
const modeAllowed = computed(() => props.controlMode === 'DEBUG')
/** 点动总闸: 非 DEBUG 置灰(后端 403 是第二道), 且必须先过「启用点动」的警示门 */
const canJog = computed(() => modeAllowed.value && !offline.value && jogArmed.value)
/** 工具语义键的闸: 不含 arm —— 它们不是点动, 各自带 danger/danger-ack 确认 */
const canTool = computed(() => modeAllowed.value && !offline.value)

const currentSpeed = computed(() => {
  const value = Number(props.snapshot?.speed_factor)
  return Number.isFinite(value) ? value : null
})

/**
 * 速度输入框预填: 一次性闩, 照抄二维 RobotJogPanel 的 speedFactorSynced 手法.
 * 首次拿到遥测值就灌进输入框, 之后遥测再变不覆盖 —— 用户正在敲的数不能被 1 Hz
 * 回显冲掉。「应用」成功后手动同步(见 applySpeed)。
 */
const speedSynced = ref(false)
watch(currentSpeed, (value) => {
  if (!speedSynced.value && value !== null) {
    speedInput.value = value
    speedSynced.value = true
  }
}, { immediate: true })

/**
 * 功能: 启用点动 —— 过一次警示弹窗(与 PLC 单点模式同款文案).
 * @returns {Promise<void>} 完成
 */
async function armJog() {
  if (jogArmed.value) {
    jogArmed.value = false
    return
  }
  const acked = await confirmAction({
    level: 'danger-ack',
    title: '启用机械臂点动',
    message: [
      '点动将直接驱动机械臂, 请谨慎操作。',
      '三维画面与实机存在误差, 请以现场实机为准, 边看设备边操作。',
    ],
    ackText: '我已知晓, 将对照实机操作',
    confirmText: '启用',
  })
  if (!acked) return
  jogArmed.value = true
}

/** 工具语义位: 实际位优先, 没有就退到下令位(与二维页同判) */
const toolBits = computed(() => {
  const state = props.snapshot?.tool_state || {}
  const actual = Number(state.actual_bits)
  if (Number.isFinite(actual)) return actual
  const commanded = Number(state.commanded_bits)
  return Number.isFinite(commanded) ? commanded : 0
})

const mountedToolText = computed(() => {
  const label = props.realtime?.tool?.label
  if (label) return label
  const id = props.snapshot?.tool_state?.mounted_tool
  return id === undefined || id === null ? '—' : `工具 ${id}`
})

const jog = useRobotJog(api, {
  onResult: (value) => { result.value = value },
  errText: (e) => String(e?.message || e),
})

/**
 * 功能: 取某一行的实时数值(20 Hz 插值; 没有高频帧时为 null).
 * @param {object} row 轴行
 * @returns {number|null} 数值
 */
function axisValue(row) {
  const source = row.kind === 'joint' ? props.realtime?.robot?.joint : props.realtime?.robot?.pose
  const value = Array.isArray(source) ? Number(source[row.idx]) : NaN
  return Number.isFinite(value) ? value : null
}

/**
 * 功能: 包一次下发, 统一回显与错误.
 * @param {Function} run 实际调用
 * @param {string} label 中文动作名(失败提示用)
 * @returns {Promise<void>} 完成
 */
async function submit(run, label) {
  message.value = ''
  try {
    result.value = await run()
  } catch (err) {
    result.value = null
    message.value = `${label}失败: ${err.message}`
  }
}

/** 功能: 应用全局速度倍率. */
async function applySpeed() {
  const ratio = Number(speedInput.value)
  if (!Number.isFinite(ratio) || ratio <= 0 || ratio > 100) {
    message.value = '速度倍率必须是 1~100 之间的数'
    return
  }
  await submit(() => api.robotSetSpeedFactor(ratio), '应用速度')
}

/**
 * 功能: 末端语义动作(松开类要过 danger-ack —— 手上可能夹着板).
 * @param {object} btn 按钮定义
 * @returns {Promise<void>} 完成
 */
async function toolAction(btn) {
  const level = RELEASE_TOOL_ACTIONS.has(btn.action) ? 'danger-ack' : 'danger'
  const ok = await confirmAction({
    level,
    title: `末端工具 · ${btn.text}`,
    message: [`将对末端执行「${btn.text}」(${btn.action})。`],
    ackText: level === 'danger-ack' ? '我已确认末端下方无跌落风险' : undefined,
    confirmText: '执行',
  })
  if (!ok) return
  await submit(() => api.runAction('robot.tool_action', { action: btn.action }, props.controlMode),
    btn.text)
}

/**
 * 上次重连是否被 CurrentCommandId 接管守卫拦下.
 *
 * 只认这一个文案片段: 守卫是驱动层唯一会说"CurrentCommandId 已变化"的出口
 * (dobot_tcp_driver._reconcile_after_connect), 其它重连失败(地址不可达/仍在运行)
 * 不该给强制接管入口 —— 那些不是"确认无他人"能解决的事。
 */
const takeoverBlocked = computed(() => {
  if (result.value?.action !== 'robot.connect') return false
  return String(result.value?.message || '').includes('CurrentCommandId 已变化')
})

/** 功能: 强制接管重连 —— 守卫文案里"需人工确认"的真实入口, danger-ack 后带 confirm 重连. */
async function forceTakeover() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '强制接管重连',
    message: [
      '守卫检测到机器人的运动队列在断联期间被推进过, 可能有其他控制者。',
      '强制接管会清除比对基准并直接取得控制权。',
    ],
    ackText: '我已确认机械臂已物理停止, 且无 DobotStudio/示教器/其他进程在控制',
    confirmText: '强制接管',
  })
  if (!ok) return
  await submit(() => api.robotConnect(true), '强制接管重连')
}

/** 功能: 急停 —— 直发, 永不确认永不禁用(confirmService 头注定案). */
function onEstop() {
  emergencyStop()
}

/** 功能: 释放急停 —— 与按下相反, 这条必须过 danger-ack. */
async function releaseEstop() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '释放急停',
    message: ['释放后机械臂将重新可以运动。请先确认现场无人、无异物。'],
    ackText: '我已确认现场安全',
    confirmText: '释放',
  })
  if (!ok) return
  await submit(() => api.robotEmergencyStop(false), '释放急停')
}
</script>

<template>
  <div class="srp">
    <p v-if="offline" class="dock-banner dock-banner--bad">
      <span class="dock-banner__title">机械臂已断联</span>
      <span>控制柜通信会话失效, 所有运动指令都发不出去。</span>
      <button type="button" class="srp__btn" @click="submit(() => api.robotConnect(), '重连')">
        重连
      </button>
      <!-- 重连被 CurrentCommandId 接管守卫拦下时才出现: 这是守卫文案里
           "需人工确认"的真实入口, 不是常规按钮 -->
      <template v-if="takeoverBlocked">
        <span>重连被"其他控制者"守卫拦下。确认机械臂已物理停止、没有 DobotStudio/示教器/其他进程在控制后, 可强制接管。</span>
        <button type="button" class="srp__btn srp__btn--estop" @click="forceTakeover">
          强制接管重连
        </button>
      </template>
    </p>

    <!-- ── 安全行: 常驻, 不折叠 ─────────────────────────────────────── -->
    <section class="dock-section">
      <h3 class="dock-h3">安全<span class="dock-h3__sub">上排不限控制模式</span></h3>
      <div class="srp__row">
        <button type="button" class="srp__btn"
                @click="submit(() => api.robotStop(), '停止')">停止</button>
        <button type="button" class="srp__btn srp__btn--estop" @click="onEstop">急停</button>
        <button type="button" class="srp__btn" @click="releaseEstop">释放急停</button>
      </div>
      <!-- 第二排: 报警/使能收敛(仅调试模式; 端点自带三重门: DEBUG + 配置开关 + 端点即显式 confirm)。
           奇异点等报警的现场恢复路径就是 清错 → 使能, 不再需要重启任何东西 -->
      <div class="srp__row">
        <button type="button" class="srp__btn" :disabled="!modeAllowed"
                :title="modeAllowed ? '清除控制器报警(报警原因未排除会立刻复发)' : '仅调试模式可用'"
                @click="submit(() => api.robotClearError(), '清错')">清错</button>
        <button type="button" class="srp__btn" :disabled="!modeAllowed"
                :title="modeAllowed ? '机械臂上使能' : '仅调试模式可用'"
                @click="submit(() => api.robotEnable(), '使能')">使能</button>
        <button type="button" class="srp__btn" :disabled="!modeAllowed"
                :title="modeAllowed ? '机械臂下使能(抱闸)' : '仅调试模式可用'"
                @click="submit(() => api.robotDisable(), '下使能')">下使能</button>
        <span class="srp__hint">仅调试模式</span>
      </div>
    </section>

    <!-- ── 速度 ──────────────────────────────────────────────────────── -->
    <section class="dock-section">
      <h3 class="dock-h3">
        全局速度<span class="dock-h3__sub">影响点动与所有运动</span>
      </h3>
      <div class="srp__row">
        <input v-model="speedInput" class="srp__num" type="number" min="1" max="100"
               placeholder="%" :disabled="!modeAllowed">
        <button type="button" class="srp__btn" :disabled="!modeAllowed" @click="applySpeed">
          应用
        </button>
        <span class="srp__hint">当前 {{ currentSpeed === null ? '—' : `${currentSpeed}%` }}</span>
      </div>
    </section>

    <!-- ── 点动 ──────────────────────────────────────────────────────── -->
    <section class="dock-section">
      <h3 class="dock-h3">
        点动<span class="dock-h3__sub">
          {{ !jogArmed ? '启用后可操作' : jog.mode.value === 'continuous' ? '按住即动 · 松手即停' : '单击走一格' }}
        </span>
        <button type="button" class="srp__btn srp__arm" :class="{ 'is-on': jogArmed }"
                @click="armJog">{{ jogArmed ? '停用点动' : '启用点动' }}</button>
      </h3>

      <template v-if="jogArmed">
        <div class="srp__row">
          <button type="button" class="srp__tab" :class="{ 'is-on': jog.mode.value === 'continuous' }"
                  @click="jog.mode.value = 'continuous'">连续</button>
          <button type="button" class="srp__tab" :class="{ 'is-on': jog.mode.value === 'step' }"
                  @click="jog.mode.value = 'step'">步进</button>
          <template v-if="jog.mode.value === 'step'">
            <input v-model.number="jog.stepMm.value" class="srp__num" type="number" step="0.1"
                   title="平移步长(mm)">
            <span class="srp__hint">mm</span>
            <input v-model.number="jog.stepDeg.value" class="srp__num" type="number" step="0.1"
                   title="旋转/关节步长(deg)">
            <span class="srp__hint">°</span>
          </template>
        </div>

        <p v-if="!modeAllowed" class="srp__gate">
          非 DEBUG 模式: 点动与工具动作已置灰。请在顶栏切到调试模式后重试。
        </p>
      </template>

      <!-- 行形制照抄二维 RobotJogPanel: [−] [轴标药丸+实时值] [+], 全局配方
           .jog-row/.side-btn/.value-rail/.axis-pill/.axis-value (style.css 为共用上提)。
           未启用点动时 side-btn 整个不渲染, 只剩读数轨 —— 读数永远可见 -->
      <p class="srp__group">笛卡尔 (TCP)</p>
      <div class="srp__tcp-grid">
        <div v-for="row in TCP_ROWS" :key="row.axis" class="jog-row"
             :class="{ 'srp__jog-readonly': !jogArmed }">
          <button
            v-if="jogArmed"
            type="button" class="side-btn" :class="{ active: jog.isActive(`${row.axis}-`) }"
            :disabled="!canJog" :aria-label="`${row.axis} 轴负向点动`"
            @click.prevent="jog.pressStep(row, -1, $event)"
            @pointerdown="jog.pressContinuous(`${row.axis}-`, $event)"
            @pointerup.prevent="jog.releaseContinuous($event)"
            @pointercancel.prevent="jog.releaseContinuous($event)"
            @lostpointercapture="jog.releaseContinuous($event)"
          >−</button>
          <div class="value-rail">
            <span class="axis-pill" :class="row.accent">{{ row.axis }}</span>
            <span class="axis-value num" :class="{ 'srp__stale': realtime?.robot?.stale }">
              {{ axisValue(row) === null ? '—' : axisValue(row).toFixed(2) }}{{ row.unit }}
            </span>
          </div>
          <button
            v-if="jogArmed"
            type="button" class="side-btn" :class="{ active: jog.isActive(`${row.axis}+`) }"
            :disabled="!canJog" :aria-label="`${row.axis} 轴正向点动`"
            @click.prevent="jog.pressStep(row, 1, $event)"
            @pointerdown="jog.pressContinuous(`${row.axis}+`, $event)"
            @pointerup.prevent="jog.releaseContinuous($event)"
            @pointercancel.prevent="jog.releaseContinuous($event)"
            @lostpointercapture="jog.releaseContinuous($event)"
          >+</button>
        </div>
      </div>

      <p class="srp__group">关节</p>
      <div class="srp__joint-list">
        <div v-for="row in JOINT_ROWS" :key="row.axis" class="jog-row"
             :class="{ 'srp__jog-readonly': !jogArmed }">
          <button
            v-if="jogArmed"
            type="button" class="side-btn" :class="{ active: jog.isActive(`${row.axis}-`) }"
            :disabled="!canJog" :aria-label="`${row.axis} 轴负向点动`"
            @click.prevent="jog.pressStep(row, -1, $event)"
            @pointerdown="jog.pressContinuous(`${row.axis}-`, $event)"
            @pointerup.prevent="jog.releaseContinuous($event)"
            @pointercancel.prevent="jog.releaseContinuous($event)"
            @lostpointercapture="jog.releaseContinuous($event)"
          >−</button>
          <div class="value-rail">
            <span class="axis-pill" :class="row.accent">{{ row.axis }}</span>
            <span class="axis-value num" :class="{ 'srp__stale': realtime?.robot?.stale }">
              {{ axisValue(row) === null ? '—' : axisValue(row).toFixed(2) }}{{ row.unit }}
            </span>
          </div>
          <button
            v-if="jogArmed"
            type="button" class="side-btn" :class="{ active: jog.isActive(`${row.axis}+`) }"
            :disabled="!canJog" :aria-label="`${row.axis} 轴正向点动`"
            @click.prevent="jog.pressStep(row, 1, $event)"
            @pointerdown="jog.pressContinuous(`${row.axis}+`, $event)"
            @pointerup.prevent="jog.releaseContinuous($event)"
            @pointercancel.prevent="jog.releaseContinuous($event)"
            @lostpointercapture="jog.releaseContinuous($event)"
          >+</button>
        </div>
      </div>
    </section>

    <!-- ── 末端工具 ──────────────────────────────────────────────────── -->
    <section class="dock-section">
      <h3 class="dock-h3">
        末端工具<span class="dock-h3__sub">当前挂载 {{ mountedToolText }}</span>
      </h3>
      <div class="srp__tool-grid">
        <div v-for="group in TOOL_GROUPS" :key="group.label" class="srp__tool">
          <span class="srp__tool-label">{{ group.label }}</span>
          <button
            v-for="btn in group.btns" :key="btn.action"
            type="button" class="srp__btn"
            :class="{ 'is-on': btn.active ? btn.active(toolBits) : false }"
            :disabled="!canTool"
            :title="btn.action"
            @click="toolAction(btn)"
          >{{ btn.text }}</button>
        </div>
      </div>
    </section>

    <p v-if="message" class="srp__msg">{{ message }}</p>
    <pre v-if="result" class="srp__result" role="status">{{ JSON.stringify(result) }}</pre>
  </div>
</template>

<style scoped>
.srp {
  display: flex;
  flex-direction: column;
}

.srp__row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  align-items: center;
}

.srp__group {
  margin: 8px 0 3px;
  font-size: 11px;
  color: var(--text-dim);
}

/* ── 点动行: 全局配方 .jog-row/.side-btn/.value-rail/.axis-pill/.axis-value ──
   (style.css 当年就是为共用上提的; 这里只做坞内的尺寸收缩与轴色标) */

/* TCP/关节都是固定两列(用户定案): auto-fill 在实际坞宽下会落成一列, 不再自适应。
   TCP 的行序 Rx/Ry/Rz 在前配合 column 流向 = 左列旋转、右列平移(与二维页同布局) */
.srp__tcp-grid,
.srp__joint-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-auto-flow: column;
  grid-template-rows: repeat(3, auto);
  gap: 5px 8px;
  align-content: start;
}

/* 全局 .jog-row 是 40px|1fr|40px 三列; 坞里侧钮缩到 30px, 未启用(无按钮)时单列铺满。
   这些行都在本组件自己的模板里, scoped 选择器直接命中, 不需要 :deep */
.jog-row {
  grid-template-columns: 30px minmax(0, 1fr) 30px;
  gap: 5px;
}

.jog-row.srp__jog-readonly {
  grid-template-columns: minmax(0, 1fr);
}

.side-btn {
  width: 30px;
  height: 30px;
  font-size: 16px;
}

.value-rail {
  min-height: 28px;
  padding: 0 8px 0 3px;
  font-size: 11px;
}

.axis-pill {
  min-width: 26px;
  height: 22px;
  padding: 0 6px;
  font-size: 10px;
}

/* 轴色标: 照抄二维 RobotJogPanel scoped 的 4 条(那边跨不出组件)。
   用的都是 :root 基色(--bad-soft/--ok-soft/--hover/--surface-2), 不被 three-d 令牌桥覆盖 */
.joint-accent { color: var(--muted); background: var(--surface-2); }
.rx-accent, .x-accent { color: var(--bad-strong); background: var(--bad-soft); }
.ry-accent, .y-accent { color: var(--ok-strong); background: var(--ok-soft); }
.rz-accent, .z-accent { color: var(--accent); background: var(--hover); }

.srp__stale {
  color: var(--text-dim);
}

.srp__arm {
  margin-left: auto;
}

.srp__arm.is-on {
  color: var(--accent-bright);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

/* 末端工具 2×2 双列(用户定案): 快换/真空 一行, 夹爪/旋转 一行 */
.srp__tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 10px;
}

.srp__tool {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 2px 0;
}

.srp__tool-label {
  flex: none;
  width: 34px;
  font-size: 11px;
  color: var(--text-dim);
}

.srp__btn,
.srp__tab {
  padding: 3px 9px;
  font-size: 11px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.srp__btn:hover:not(:disabled),
.srp__tab:hover:not(:disabled) {
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.srp__btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.srp__btn.is-on,
.srp__tab.is-on {
  color: var(--accent-bright);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.srp__btn--estop {
  color: var(--err-bright);
  border-color: var(--err);
}

.srp__num {
  width: 58px;
  padding: 3px 6px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.srp__hint {
  font-size: 11px;
  color: var(--text-dim);
}

.srp__gate {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}

.srp__msg {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}

.srp__result {
  max-height: 96px;
  margin: 6px 0 0;
  padding: 5px 7px;
  overflow: auto;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--control);
  border-radius: 5px;
}
</style>
