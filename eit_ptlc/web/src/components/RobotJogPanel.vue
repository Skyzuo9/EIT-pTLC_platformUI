<script setup>
// 机器人点动操作台 (维护页): 连续点动 / 步进增量 + 实时位姿数值轨 + 停止/急停
// 风格参考 eit_agv (EIT Hub) ArmJogPanel; 复用现有 robot 便捷端点, 无后端改动
import { ref, computed, watch } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useEstop } from '../composables/useEstop.js'
import { useRobotJog } from '../composables/useRobotJog.js'
import { useSystemStore } from '../store'
import { useLayoutStore } from '../stores/layout'
import { TOOL_NAMES, TOOL_OPTIONS } from '../utils/robotTools.js'
import Splitter from './Splitter.vue'

const props = defineProps({
  node: { type: Object, required: true },
})

const sys = useSystemStore()
const layout = useLayoutStore()

// 实时遥测 (已是展示单位: pose=[x,y,z(mm),rx,ry,rz(deg)], joint=[j1..j6(deg)])
const pose = computed(() => (props.node && props.node.data ? props.node.data.pose : null))
const joint = computed(() => (props.node && props.node.data ? props.node.data.joint : null))

// 全局速度比 SpeedFactor (1-100): 影响点动与所有运动. 当前值随遥测回显, 首次到达即同步到输入
const currentSpeedFactor = computed(() => {
  const v = props.node && props.node.data ? props.node.data.speed_factor : null
  return typeof v === 'number' ? v : null
})
const speedFactor = ref(20)
const speedFactorSynced = ref(false)
watch(
  currentSpeedFactor,
  (v) => {
    if (!speedFactorSynced.value && typeof v === 'number') {
      speedFactor.value = v
      speedFactorSynced.value = true
    }
  },
  { immediate: true },
)

const result = ref(null) // 动作回显 (ActionResult)

// 轴行模型: kind 决定 步进插补(joint->j, 其余->l) / 步长字段(translate->mm, 其余->deg) / 数值来源与单位后缀
// 连续令牌 = axis+'+' / axis+'-' (对齐 robot.jog_start 枚举); 步进轴 = axis (对齐 robot.step 枚举)
const TCP_ROWS = [
  { axis: 'Rx', kind: 'rotate', accent: 'rx-accent', idx: 3 },
  { axis: 'Ry', kind: 'rotate', accent: 'ry-accent', idx: 4 },
  { axis: 'Rz', kind: 'rotate', accent: 'rz-accent', idx: 5 },
  { axis: 'X', kind: 'translate', accent: 'x-accent', idx: 0 },
  { axis: 'Y', kind: 'translate', accent: 'y-accent', idx: 1 },
  { axis: 'Z', kind: 'translate', accent: 'z-accent', idx: 2 },
]
const JOINT_ROWS = Array.from({ length: 6 }, (_v, i) => ({
  axis: `J${i + 1}`,
  kind: 'joint',
  accent: 'joint-accent',
  idx: i,
}))

// ---- 末端工具 IO ----
// 语义 DO: 走后端语义白名单 robot.tool_action (带安全联锁/时序).
// 语义位 (commanded/actual_bits): bit0=DO1 快换(0锁/1松), bit1=DO3 真空, bit2=DO2 夹爪(0开/1合).
// 旋转走 DO6+DO2 配合, 后端不回读语义位, 故只触发不高亮.
const TOOL_GROUPS = [
  {
    label: '快换',
    btns: [
      { text: '锁紧', action: 'quick-change-lock', active: (b) => (b & 1) === 0 },
      { text: '松开', action: 'quick-change-release', active: (b) => (b & 1) === 1 },
    ],
  },
  {
    label: '真空',
    btns: [
      { text: '开', action: 'suction-on', active: (b) => (b & 2) !== 0 },
      { text: '关', action: 'suction-off', active: (b) => (b & 2) === 0 },
    ],
  },
  {
    label: '夹爪',
    btns: [
      { text: '张开', action: 'gripper-open', active: (b) => (b & 4) === 0 },
      { text: '闭合', action: 'gripper-close', active: (b) => (b & 4) !== 0 },
    ],
  },
  {
    label: '旋转',
    btns: [
      { text: '上升', action: 'rotary-up' },
      { text: '下降', action: 'rotary-down' },
    ],
  },
]
const DI_COUNT = 8 // 末端 DI 监视位数 (后端按低 16 位采集, 取常用低 8 位展示)
const DO_COUNT = 8 // DO 输出监视位数 (与 DI 对称, 取低 8 位实时回显)

// 裸 DO 直控: 后端白名单 {1,2,3,6}, 直接置位单口 (无语义联锁, 需 DEBUG).
// channel=口号; mask=do_bits 中的位 (1<<(channel-1)); note=该口的语义用途, 仅作提示
const RAW_DO_CHANNELS = [
  { channel: 1, note: '快换' },
  { channel: 2, note: '夹爪' },
  { channel: 3, note: '真空' },
  { channel: 6, note: '配合线' },
]

const toolState = computed(() => (props.node && props.node.data ? props.node.data.tool_state : null))
// 状态指示优先用硬件回读 actual_bits, 缺失时回退到下发的 commanded_bits
const toolBits = computed(() => {
  const s = toolState.value
  if (!s) {
    return null
  }
  if (typeof s.actual_bits === 'number') {
    return s.actual_bits
  }
  return typeof s.commanded_bits === 'number' ? s.commanded_bits : null
})
const diBits = computed(() => {
  const s = toolState.value
  return s && typeof s.di_bits === 'number' ? s.di_bits : null
})
// 原始 DO 输出位 (后端 do_bits, 低 16 位); 实时反映硬件输出, 与 DI 监视对称
const doBits = computed(() => {
  const s = toolState.value
  return s && typeof s.do_bits === 'number' ? s.do_bits : null
})
// di_available=false 表示后端未启用 DI 确认 (仍实时监视, 用于验线后再开启)
const diAvailable = computed(() => !!(toolState.value && toolState.value.di_available))

// ---- 当前挂载工具 (权威四态) ----
// 机器人无"挂了哪个工具"的 DI: 权威工具态由状态文件持久化, 启动读盘恢复 (四态: 无/吸盘/大夹爪/小夹爪).
// 此处可手动覆盖当前挂载 (set_mounted_tool 写权威文件); NONE(裸腕) 下驱动拒发所有语义工具动作.
// 四态映射与三维实时页共用 utils/robotTools.js 一份, 防两处漂移。
const mountedTool = computed(() => {
  const s = toolState.value
  return s && typeof s.mounted_tool === 'number' ? s.mounted_tool : 0
})
const mountedToolText = computed(() => TOOL_NAMES[String(mountedTool.value)] ?? '未知')
// 覆盖下拉默认值: 首次拿到权威当前值即同步一次, 之后保持操作员的选择
const declaredTool = ref(0)
const declaredToolSynced = ref(false)
watch(
  mountedTool,
  (v) => {
    if (!declaredToolSynced.value && typeof v === 'number') {
      declaredTool.value = v
      declaredToolSynced.value = true
    }
  },
  { immediate: true },
)
// 各单发动作共用的错误落点: 保持原 catch 的视觉行为 (写回 result 展示位)
function errToResult(msg) {
  result.value = { status: 'ERROR', message: msg }
}

const declareAct = useAsyncAction(
  async () => {
    result.value = await api.runAction('robot.set_mounted_tool', { tool_id: String(declaredTool.value) }, sys.mode)
  },
  { errorPrefix: '设置挂载工具失败', minInterval: 350, onError: errToResult },
)
async function declareTool() {
  const name = TOOL_NAMES[String(declaredTool.value)] ?? String(declaredTool.value)
  if (!(await confirmAction({
    title: '改写当前挂载工具',
    message: `将把权威工具态改写为「${name}」并持久化。声明与实机不符时, 语义工具动作的安全前提会失效。`,
    level: 'danger',
    confirmText: '改写',
  }))) return
  await declareAct.run()
}

function isToolActive(btn) {
  if (!btn.active) {
    return false
  }
  const bits = toolBits.value
  return bits !== null && btn.active(bits)
}
function diOn(index) {
  const bits = diBits.value
  return bits !== null && (bits & (1 << (index - 1))) !== 0
}
// 单个 DO 口的当前输出态 (channel 为口号 1..16)
function doOn(channel) {
  const bits = doBits.value
  return bits !== null && (bits & (1 << (channel - 1))) !== 0
}

// 末端工具语义动作: 复用 runAction(robot.tool_action), 沿用当前系统模式 (与动作详情页一致)。
// 分级 (按命令表命令名): 「松开/张开」类会解除保持 (快换松开=掉工具, 夹爪张开=掉持物) → danger-ack;
// 其余语义动作 → danger。真空关按名不属「松开/张开/释放」类, 定案走 danger, 但后果文案写明失吸风险。
const RELEASE_TOOL_ACTIONS = new Set(['quick-change-release', 'gripper-open'])
const TOOL_ACTION_LABEL = {}
for (const g of TOOL_GROUPS) {
  for (const b of g.btns) TOOL_ACTION_LABEL[b.action] = `${g.label}${b.text}`
}
const toolAct = useAsyncAction(
  async (actionId) => {
    result.value = await api.runAction('robot.tool_action', { action: actionId }, sys.mode)
  },
  { errorPrefix: '工具动作失败', minInterval: 350, onError: errToResult },
)
async function toolAction(actionId) {
  const label = TOOL_ACTION_LABEL[actionId] || actionId
  const ok = RELEASE_TOOL_ACTIONS.has(actionId)
    ? await confirmAction({
        title: `执行${label}`,
        message: `「${label}」会解除当前保持, 工具/持物可能从末端脱落。`,
        level: 'danger-ack',
        ackText: '确认下方无跌落风险',
        confirmText: '执行',
      })
    : await confirmAction({
        title: `执行${label}`,
        message: actionId === 'suction-off'
          ? '将关闭真空; 若正吸持物件, 物件会失去吸力。'
          : `将向末端工具发出「${label}」动作。`,
        level: 'danger',
        confirmText: '执行',
      })
  if (!ok) return
  await toolAct.run(actionId)
}

// 裸 DO 直控: runAction(robot.set_do); 后端 DEBUG 门控 + 白名单, 非调试模式会被拒。
// 高频调试操作不弹模态 (确认疲劳→文化性绕过), 改两段式武装: 首点按钮原地变「再点一次确认」,
// 3 秒不二点自动撤防。每个 口×电平 一个独立实例 —— 共用实例会让武装跨按钮串台
// (A 钮首点武装, B 钮一点即发), 两段式就失去意义。
function doKey(channel, enabled) {
  return `${channel}:${enabled ? '1' : '0'}`
}
const doActs = {}
for (const d of RAW_DO_CHANNELS) {
  for (const enabled of [true, false]) {
    doActs[doKey(d.channel, enabled)] = useAsyncAction(
      async () => {
        result.value = await api.runAction('robot.set_do', { channel: String(d.channel), enabled }, sys.mode)
      },
      {
        errorPrefix: `DO${d.channel} 置${enabled ? '1' : '0'}失败`,
        minInterval: 350,
        arm: { label: '再点一次确认', timeoutMs: 3000 },
        onError: errToResult,
      },
    )
  }
}
function doAct(channel, enabled) {
  return doActs[doKey(channel, enabled)]
}
function setDo(channel, enabled) {
  const act = doAct(channel, enabled)
  if (!act.armed) {
    // 新武装前撤防其它钮: 同屏只留一个「再点一次确认」, 防把别的钮误当二次确认点下去
    for (const key of Object.keys(doActs)) {
      if (key !== doKey(channel, enabled)) doActs[key].disarm()
    }
  }
  act.run()
}

// 单轴数值轨: 关节取 joint[idx], 其余取 pose[idx]; 旋转/关节加 ° 后缀
function axisValue(row) {
  const src = row.kind === 'joint' ? joint.value : pose.value
  if (!Array.isArray(src) || src.length <= row.idx || typeof src[row.idx] !== 'number') {
    return '--'
  }
  const num = src[row.idx].toFixed(2)
  return row.kind === 'translate' ? num : `${num}°`
}

// pose 卡片: 整组 TCP / 关节读数 (等宽展示)
const poseText = computed(() => {
  const items = pose.value
  if (!Array.isArray(items)) {
    return '--'
  }
  return items
    .map((v, i) => (typeof v === 'number' ? (i < 3 ? v.toFixed(2) : `${v.toFixed(2)}°`) : '--'))
    .join('   ')
})
const jointText = computed(() => {
  const items = joint.value
  if (!Array.isArray(items)) {
    return '--'
  }
  return items.map((v, i) => `J${i + 1}: ${typeof v === 'number' ? v.toFixed(2) : '--'}°`).join('   ')
})

const hintText = computed(() =>
  mode.value === 'continuous' ? '按住点动, 松开停止 (需调试模式)' : '点击单步增量 (需调试模式)',
)

// 断联态: 节点健康为 offline 时机器人通信已断, 仅「重连」可用, 其余动作均会被后端拒
const offline = computed(() => props.node && props.node.health === 'offline')

function errMsg(e) {
  return errText(e)
}

// ---- 点动 (连续: 按住起/松开停, 换向后到者胜; 步进: 单次增量) ----
// 状态机在 composables/useRobotJog.js —— 三维实时页的机械臂面板共用同一份, 安全停这种
// 东西不该有两份实现。这里只保留 UI 与回显接线。
const {
  mode, stepMm, stepDeg, activeDir,
  isActive, pressContinuous, releaseContinuous, stopContinuous, pressStep,
} = useRobotJog(api, {
  onResult: (value) => { result.value = value },
  errText: errMsg,
})

// ---- 全局速度比 (影响点动与所有运动; 需调试模式) ----
const speedAct = useAsyncAction(
  async () => {
    result.value = await api.robotSetSpeedFactor(speedFactor.value)
  },
  { errorPrefix: '应用全局速度失败', minInterval: 350, onError: errToResult },
)

// ---- 中止类 (不限模式; 停止/急停零门槛, 不加确认不加禁用) ----
async function stop() {
  result.value = await api.robotStop()
}
// 急停触发走 useEstop 单例 (与态势条/弹窗头同一状态): 按钮三态文案 + assertive 播报 +
// StatusBar 常驻红字统一承担回执 —— 原先此处把回包写 result 面板的本地回显随之迁移。
// 急停路径上不许出现任何对话框 (定案)。
const { busy: estopBusy, sent: estopSent, emergencyStop } = useEstop()

// 释放急停是反方向的恢复动力, 需现场安全 ack (保留本地实现与 result 回显)
async function releaseEstop() {
  if (!(await confirmAction({
    title: '释放急停',
    message: '将解除机器人急停, 机器人恢复动力并可再次运动。',
    level: 'danger-ack',
    ackText: '现场已确认安全, 允许机器人恢复动力',
    confirmText: '释放急停',
  }))) return
  result.value = await api.robotEmergencyStop(false)
}

// ---- 使能 / 清警 (维护; 需 DEBUG + 后端配置允许; 二次确认避免误触) ----
const enableAct = useAsyncAction(
  async () => {
    result.value = await api.robotEnable()
  },
  { errorPrefix: '使能失败', minInterval: 350, onError: errToResult },
)
async function enableRobot() {
  if (!(await confirmAction({
    title: '使能机器人',
    message: '确认使能机器人? 请先确保臂周围安全。',
    level: 'danger',
    confirmText: '使能',
  }))) return
  await enableAct.run()
}
const disableAct = useAsyncAction(
  async () => {
    result.value = await api.robotDisable()
  },
  { errorPrefix: '失能失败', minInterval: 350, onError: errToResult },
)
async function disableRobot() {
  if (!(await confirmAction({
    title: '下使能机器人',
    message: '确认下使能机器人? 臂将伺服下电, 失去保持力。',
    level: 'danger',
    confirmText: '下使能',
  }))) return
  await disableAct.run()
}
const clearErrorAct = useAsyncAction(
  async () => {
    result.value = await api.robotClearError()
  },
  { errorPrefix: '清警失败', minInterval: 350, onError: errToResult },
)
async function clearError() {
  if (!(await confirmAction({
    title: '清除机器人报警',
    message: '确认清除机器人报警? 请确认报警原因已排除。',
    level: 'danger',
    confirmText: '清除报警',
  }))) return
  await clearErrorAct.run()
}

// ---- 断联重连 (维护; 不限模式; 仅重建通信, 安全由后端重连校验兜底) ----
const connectAct = useAsyncAction(
  async () => {
    result.value = await api.robotConnect()
  },
  { errorPrefix: '重连失败', minInterval: 350, onError: errToResult },
)

// 安全停(visibilitychange / blur / pagehide / 卸载)由 useRobotJog 统一挂载与拆除
</script>

<template>
  <div class="robot-jog">
    <div v-if="offline" class="offline-banner" role="alert">
      <span class="offline-text">机器人已断联, 操作不可用</span>
      <button type="button" class="act-btn act-connect" :disabled="connectAct.busy" :aria-busy="connectAct.busy"
        @click="connectAct.run()">{{ connectAct.busy ? '重连中…' : '重连' }}</button>
    </div>

    <div class="movement-shell">
      <div class="jog-toolbar">
        <div class="mode-switch">
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'continuous' }"
            @click="mode = 'continuous'"
          >连续</button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'step' }"
            @click="mode = 'step'"
          >步进</button>
        </div>
        <div class="jog-hint">{{ hintText }}</div>
        <label class="param speed-param">
          <span class="param-name">全局速度</span>
          <input class="param-input" type="number" inputmode="numeric" v-model.number="speedFactor" min="1" max="100" step="5" />
          <span class="param-unit">%</span>
          <button type="button" class="speed-apply" :disabled="speedAct.busy" :aria-busy="speedAct.busy"
            @click="speedAct.run()">{{ speedAct.busy ? '应用中…' : '应用' }}</button>
          <span v-if="currentSpeedFactor !== null" class="speed-current num">当前 {{ currentSpeedFactor }}%</span>
        </label>
        <template v-if="mode === 'step'">
          <label class="param">
            <span class="param-name">平移</span>
            <input class="param-input" type="number" v-model.number="stepMm" min="0.1" max="50" step="0.5" />
            <span class="param-unit">mm</span>
          </label>
          <label class="param">
            <span class="param-name">旋转</span>
            <input class="param-input" type="number" v-model.number="stepDeg" min="0.1" max="30" step="0.5" />
            <span class="param-unit">deg</span>
          </label>
        </template>
      </div>

      <p class="hint">长按点动仅支持鼠标/触控按住; 键盘请使用步进或目标位下发。</p>

      <div class="panel-layout" :style="{ '--jog-right-w': layout.sizes.jogRightW + 'px' }">
        <div class="tcp-zone">
          <section class="jog-panel tcp-panel">
            <div class="panel-caption">TCP 点动</div>
            <div class="tcp-grid">
              <div v-for="row in TCP_ROWS" :key="row.axis" class="jog-row">
                <button
                  class="side-btn"
                  :class="{ active: isActive(row.axis + '-') }"
                  :aria-label="`${row.axis} 轴负向点动`"
                  @click.prevent="pressStep(row, -1, $event)"
                  @pointerdown="pressContinuous(row.axis + '-', $event)"
                  @pointerup.prevent="releaseContinuous($event)"
                  @pointercancel.prevent="releaseContinuous($event)"
                  @lostpointercapture="releaseContinuous($event)"
                >−</button>
                <div class="value-rail">
                  <span class="axis-pill" :class="row.accent">{{ row.axis }}</span>
                  <span class="axis-value num">{{ axisValue(row) }}</span>
                </div>
                <button
                  class="side-btn"
                  :class="{ active: isActive(row.axis + '+') }"
                  :aria-label="`${row.axis} 轴正向点动`"
                  @click.prevent="pressStep(row, 1, $event)"
                  @pointerdown="pressContinuous(row.axis + '+', $event)"
                  @pointerup.prevent="releaseContinuous($event)"
                  @pointercancel.prevent="releaseContinuous($event)"
                  @lostpointercapture="releaseContinuous($event)"
                >+</button>
              </div>
            </div>
          </section>

          <div class="pose-card">
            <div class="pose-line">
              <span class="pose-title">TCP</span>
              <span class="pose-value">{{ poseText }}</span>
            </div>
            <div class="pose-line">
              <span class="pose-title">关节</span>
              <span class="pose-value">{{ jointText }}</span>
            </div>
          </div>
        </div>

        <section class="jog-panel joint-panel">
          <div class="panel-caption">关节点动</div>
          <div class="joint-list">
            <div v-for="row in JOINT_ROWS" :key="row.axis" class="jog-row">
              <button
                class="side-btn"
                :class="{ active: isActive(row.axis + '-') }"
                :aria-label="`${row.axis} 轴负向点动`"
                @click.prevent="pressStep(row, -1, $event)"
                @pointerdown="pressContinuous(row.axis + '-', $event)"
                @pointerup.prevent="releaseContinuous($event)"
                @pointercancel.prevent="releaseContinuous($event)"
                @lostpointercapture="releaseContinuous($event)"
              >−</button>
              <div class="value-rail">
                <span class="axis-pill" :class="row.accent">{{ row.axis }}</span>
                <span class="axis-value num">{{ axisValue(row) }}</span>
              </div>
              <button
                class="side-btn"
                :class="{ active: isActive(row.axis + '+') }"
                :aria-label="`${row.axis} 轴正向点动`"
                @click.prevent="pressStep(row, 1, $event)"
                @pointerdown="pressContinuous(row.axis + '+', $event)"
                @pointerup.prevent="releaseContinuous($event)"
                @pointercancel.prevent="releaseContinuous($event)"
                @lostpointercapture="releaseContinuous($event)"
              >+</button>
            </div>
          </div>
        </section>
        <!-- TCP↔关节 竖向 (关节在右 → sign=-1) -->
        <Splitter skey="jogRightW" dir="x" :sign="-1" class="seam-jog-v" />
      </div>
    </div>

    <!-- 动作条三簇: 连接 ‖ 伺服会话 (均先弹确认 → 描边) ‖ 安全动作右锚 (停止/急停点击即生效 → 实底) -->
    <div class="jog-actions">
      <div class="act-cluster">
        <button class="act-btn act-connect" :disabled="!offline || connectAct.busy" :aria-busy="connectAct.busy"
          @click="connectAct.run()">{{ connectAct.busy ? '重连中…' : '重连' }}</button>
      </div>
      <span class="act-divider" aria-hidden="true"></span>
      <div class="act-cluster">
        <button class="act-btn act-ghost" :disabled="enableAct.busy" :aria-busy="enableAct.busy"
          @click="enableRobot">{{ enableAct.busy ? '使能中…' : '使能' }}</button>
        <button class="act-btn act-ghost" :disabled="disableAct.busy" :aria-busy="disableAct.busy"
          @click="disableRobot">{{ disableAct.busy ? '失能中…' : '失能' }}</button>
        <button class="act-btn act-ghost" :disabled="clearErrorAct.busy" :aria-busy="clearErrorAct.busy"
          @click="clearError">{{ clearErrorAct.busy ? '清警中…' : '清警' }}</button>
      </div>
      <div class="act-cluster act-cluster-safety">
        <button class="act-btn act-stop" @click="stop">停止</button>
        <button class="act-btn act-estop" @click="emergencyStop">
          {{ estopBusy ? '急停 · 下发中…' : estopSent ? '急停 ✓ 已下发' : '急停' }}</button>
        <button class="act-btn act-ghost danger" @click="releaseEstop">释放急停</button>
      </div>
    </div>

    <!-- 工具区两栏: 末端 IO 独占左列, 挂载工具/纯 DO 直控 叠右列 (≤1100 塌单列) -->
    <div class="tool-zone">
    <section class="tool-io tool-io--mount">
      <div class="tool-io-caption">当前挂载工具</div>
      <div class="tool-reconcile">
        <span class="tool-label">
          当前挂载
          <strong class="mounted-now">{{ mountedToolText }}</strong>
        </span>
        <label class="param">
          <span class="param-name">设为</span>
          <select class="param-input declare-select" v-model.number="declaredTool" :disabled="offline">
            <option v-for="o in TOOL_OPTIONS" :key="o.id" :value="o.id">{{ o.text }}</option>
          </select>
        </label>
        <button type="button" class="speed-apply" :disabled="offline || declareAct.busy" :aria-busy="declareAct.busy"
          @click="declareTool">{{ declareAct.busy ? '设置中…' : '设置' }}</button>
      </div>
    </section>

    <section class="tool-io tool-io--endio">
      <div class="tool-io-caption">末端工具 IO</div>
      <div class="tool-do">
        <div v-for="g in TOOL_GROUPS" :key="g.label" class="tool-group">
          <span class="tool-label">{{ g.label }}</span>
          <div class="tool-btns">
            <button
              v-for="b in g.btns"
              :key="b.action"
              type="button"
              class="tool-btn"
              :class="{ on: isToolActive(b) }"
              :disabled="offline || toolAct.busy"
              :aria-label="`${g.label}${b.text}`"
              @click="toolAction(b.action)"
            >{{ b.text }}</button>
          </div>
        </div>
      </div>
      <div class="tool-di">
        <span class="tool-label">
          DI 输入
          <small class="di-flag" :class="{ off: !diAvailable }">{{ diAvailable ? '已启用确认' : '仅监视' }}</small>
        </span>
        <div class="di-badges">
          <span v-for="i in DI_COUNT" :key="i" class="di-badge" :class="{ on: diOn(i) }"
            :title="`DI${i}: ${diOn(i) ? '通' : '断'}`"
            :aria-label="`DI${i}: ${diOn(i) ? '通' : '断'}`">DI{{ i }}</span>
        </div>
      </div>
      <div class="tool-di">
        <span class="tool-label">DO 输出<small class="di-flag do-flag">实时</small></span>
        <div class="di-badges">
          <span v-for="i in DO_COUNT" :key="i" class="di-badge" :class="{ on: doOn(i) }"
            :title="`DO${i}: ${doOn(i) ? '通' : '断'}`"
            :aria-label="`DO${i}: ${doOn(i) ? '通' : '断'}`">DO{{ i }}</span>
        </div>
      </div>
    </section>

    <section class="tool-io tool-io--rawdo">
      <div class="tool-io-caption">
        纯 DO 直控
        <small class="raw-do-warn">裸口直控 · 无安全联锁 · 需调试模式</small>
      </div>
      <div class="tool-do">
        <div v-for="d in RAW_DO_CHANNELS" :key="d.channel" class="tool-group">
          <span class="tool-label" :aria-label="`DO${d.channel} ${d.note}: 当前${doOn(d.channel) ? 'on' : 'off'}`">
            <span class="do-dot" :class="{ on: doOn(d.channel) }" aria-hidden="true"></span>
            <small class="do-state" :class="{ on: doOn(d.channel) }" aria-hidden="true">{{ doOn(d.channel) ? 'on' : 'off' }}</small>
            DO{{ d.channel }}
            <small class="do-note">{{ d.note }}</small>
          </span>
          <div class="tool-btns">
            <button
              type="button"
              class="tool-btn"
              :class="{ on: doOn(d.channel), armed: doAct(d.channel, true).armed }"
              :disabled="offline || doAct(d.channel, true).busy"
              :aria-label="`DO${d.channel} 置1`"
              @click="setDo(d.channel, true)"
            >{{ doAct(d.channel, true).armed ? doAct(d.channel, true).armedLabel : '置1' }}</button>
            <button
              type="button"
              class="tool-btn"
              :class="{ on: !doOn(d.channel), armed: doAct(d.channel, false).armed }"
              :disabled="offline || doAct(d.channel, false).busy"
              :aria-label="`DO${d.channel} 置0`"
              @click="setDo(d.channel, false)"
            >{{ doAct(d.channel, false).armed ? doAct(d.channel, false).armedLabel : '置0' }}</button>
          </div>
        </div>
      </div>
    </section>
    </div>

    <pre v-if="result" class="result" :class="result.status" role="status">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>
</template>

<style scoped>
.robot-jog {
  display: grid;
  gap: 4px;
}

.movement-shell {
  display: grid;
  gap: 14px;
  padding: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}

/* 工具栏: 模式切换 + 提示 + 步长 */
.jog-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}

.mode-switch {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.mode-btn {
  min-width: 64px;
  height: 36px;
  padding: 0 18px;
  border: none;
  background: var(--panel);
  color: var(--subtle);
  font-size: var(--fs-14);
  font-weight: 700;
  cursor: pointer;
}
.mode-btn + .mode-btn {
  border-left: 1px solid var(--border);
}
.mode-btn.active {
  background: var(--accent-strong);
  color: var(--on-accent);
}

.jog-hint {
  color: var(--muted);
  font-size: var(--fs-13);
}

.param {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.param-name,
.param-unit {
  color: var(--subtle);
  font-size: var(--fs-13);
  font-weight: 600;
}
.param-input {
  width: 96px;
  height: 36px;
  padding: 0 10px;
  color: var(--text);
  font-size: var(--fs-13);
  font-weight: 600;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

/* 全局速度比: 输入 + 应用按钮 + 当前值 */
.speed-param .param-input {
  width: 72px;
}
.speed-apply {
  height: 36px;
  padding: 0 14px;
  color: var(--on-accent);
  font-size: var(--fs-13);
  font-weight: 700;
  background: var(--accent-strong);
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
}
.speed-current {
  color: var(--muted);
  font-size: var(--fs-12);
  font-weight: 600;
}

/* 两栏布局: 左 TCP, 右 关节 */
.panel-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) var(--jog-right-w, 300px);
  gap: 14px;
  align-items: stretch;
}
/* TCP↔关节 分隔条: 落进 14px 间隙 (关节在右栏) */
.seam-jog-v { grid-column: 2; justify-self: start; align-self: stretch; width: 14px; margin-left: -14px; }
.tcp-zone {
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-self: stretch;
}

.jog-panel {
  padding: 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.joint-panel {
  align-self: stretch;
}
.panel-caption {
  margin-bottom: 12px;
  color: var(--text);
  font-size: var(--fs-13);
  font-weight: 700;
}

/* TCP 双列 (旋转 | 平移, 各 3 行); 关节单列 */
.tcp-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: repeat(3, auto);
  grid-auto-flow: column;
  align-content: start;
  gap: 10px 14px;
}
.joint-list {
  display: grid;
  gap: 10px;
}
/* .jog-row / .side-btn / .value-rail / .axis-pill / .axis-value 已上提 style.css 全局
   (与 StationManualPanel 共用配方); 此处只留 robot 特有的轴色标与 ≤768 靶区放大 */
.joint-accent {
  color: var(--muted);
  background: var(--surface-2);
}
.rx-accent,
.x-accent {
  color: var(--bad-strong);
  background: var(--bad-soft);
}
.ry-accent,
.y-accent {
  color: var(--ok-strong);
  background: var(--ok-soft);
}
.rz-accent,
.z-accent {
  color: var(--accent);
  background: var(--hover);
}

/* pose 读数卡片 */
.pose-card {
  display: flex;
  flex-wrap: wrap;
  flex: 1; /* 吸收 .tcp-zone 被右栏 (6 行关节) 拉出的余高, pose 卡下不再留断裂空洞 */
  align-content: flex-start;
  align-items: flex-start;
  column-gap: 48px;
  row-gap: 8px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow-x: auto;
}
.pose-line {
  display: grid;
  gap: 4px;
  min-width: max-content;
}
.pose-title {
  color: var(--text);
  font-size: var(--fs-12);
  font-weight: 700;
}
.pose-value {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  white-space: nowrap;
}

/* 动作条: 三簇 (连接 ‖ 伺服会话 ‖ 安全右锚), 簇间竖分隔 */
.jog-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 12px 0 2px;
  flex-wrap: wrap;
}
.act-cluster {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
/* 安全簇右锚定: 停止/急停位置恒定 (肌肉记忆) */
.act-cluster-safety {
  margin-left: auto;
}
.act-divider {
  width: 1px;
  height: 24px;
  background: var(--border);
}
.act-btn {
  padding: 8px 18px;
  font-size: var(--fs-14);
  font-weight: 600;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
}
.act-connect {
  background: var(--accent-strong);
  color: var(--on-accent);
}
.act-btn:disabled {
  opacity: 0.62;
  cursor: not-allowed;
}

/* 断联横幅: offline 时置顶, 提供唯一可用的「重连」入口 */
.offline-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: var(--bad-soft);
  border: 1px solid var(--bad);
  border-radius: var(--radius-lg);
}
.offline-text {
  color: var(--bad-strong);
  font-size: var(--fs-14);
  font-weight: 700;
}
/* 停止 = 点击即生效的运动中止: 警示色实底 (原 accent 实底与「重连」撞色, 误读成主 CTA) */
.act-stop {
  background: var(--warn);
  color: var(--on-accent);
}
/* 行为已归一 useEstop (三态文案/播报/回执共享); 尺寸走 .act-btn 体系, 类名有意保留不并入全局 .estop */
.act-estop {
  background: var(--bad);
  color: var(--on-accent);
  font-weight: 700;
}
.act-ghost {
  background: var(--panel);
  color: var(--text);
  border: 1px solid var(--border);
}
/* 释放急停: 危险确认流程的入口 → 红描边 ghost (照全局 .btn.danger.ghost 语义) */
.act-ghost.danger {
  color: var(--bad);
  border-color: var(--bad);
}

/* 工具区两栏: 末端 IO (最高的一块) 独占左列, 挂载工具/纯 DO 直控叠右列 —— 消掉三满宽卡的右半空 */
.tool-zone {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  margin-top: 4px;
}
.tool-io--endio { grid-column: 1; grid-row: 1 / 3; }
.tool-io--mount { grid-column: 2; grid-row: 1; }
.tool-io--rawdo { grid-column: 2; grid-row: 2; }

/* 末端工具 IO: 语义 DO 配对按钮 (兼作状态指示) + DI 监视徽标 */
.tool-io {
  display: grid;
  gap: 12px;
  padding: 12px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}
.tool-io-caption {
  color: var(--text);
  font-size: var(--fs-13);
  font-weight: 700;
}
.tool-do {
  display: flex;
  flex-wrap: wrap;
  gap: 16px 22px;
}
.tool-group {
  display: flex;
  align-items: center;
  gap: 10px;
}
.tool-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--subtle);
  font-size: var(--fs-13);
  font-weight: 700;
}
.tool-btns {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.tool-btn {
  min-width: 52px;
  height: 36px;
  padding: 0 16px;
  border: none;
  background: var(--panel);
  color: var(--subtle);
  font-size: var(--fs-14);
  font-weight: 700;
  cursor: pointer;
}
.tool-btn + .tool-btn {
  border-left: 1px solid var(--border);
}
.tool-btn.on {
  background: var(--accent-strong);
  color: var(--on-accent);
}
/* 两段式武装态: 首点后按钮原地变「再点一次确认」, 用警示色盖过 .on (声明序后者胜) */
.tool-btn.armed {
  background: var(--warn);
  color: var(--on-accent);
}
.tool-btn:disabled {
  opacity: 0.62;
  cursor: not-allowed;
}

/* 当前挂载工具: 回显 + 覆盖下拉 */
.tool-reconcile {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
}
.mounted-now {
  padding: 2px 10px;
  font-size: var(--fs-13);
  font-weight: 700;
  color: var(--accent-strong);
  background: var(--hover);
  border-radius: 999px;
}
.declare-select {
  width: 120px;
  cursor: pointer;
}

/* DI 监视: 实时反映硬件输入位, di_available=false 时仅监视不参与确认 */
.tool-di {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.di-flag {
  padding: 1px 8px;
  font-size: var(--fs-11);
  font-weight: 700;
  color: var(--ok-strong);
  background: var(--ok-soft);
  border-radius: 999px;
}
.di-flag.off {
  color: var(--warn-strong);
  background: var(--warn-soft);
}
.do-flag {
  color: var(--accent-strong);
  background: var(--hover);
}

/* 纯 DO 直控: 警示 + 口语义提示 + 实时态圆点 */
.raw-do-warn {
  margin-left: 10px;
  padding: 1px 8px;
  font-size: var(--fs-11);
  font-weight: 700;
  color: var(--bad-strong);
  background: var(--bad-soft);
  border-radius: 999px;
}
.do-note {
  font-size: var(--fs-11);
  font-weight: 600;
  color: var(--muted);
}
/* 圆点旁的文字层: 状态不再只靠纯色 (色弱/灰度屏可辨) */
.do-state {
  min-width: 18px;
  font-size: 10px;
  font-weight: 700;
  color: var(--muted);
  text-transform: uppercase;
}
.do-state.on {
  color: var(--ok-strong);
}
.do-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--border);
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.08);
}
.do-dot.on {
  background: var(--ok);
  box-shadow: 0 0 0 2px rgba(43, 182, 115, 0.25);
}
.di-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.di-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  height: 30px;
  padding: 0 10px;
  font-size: var(--fs-12);
  font-weight: 700;
  color: var(--muted);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}
.di-badge.on {
  color: var(--on-accent);
  background: linear-gradient(135deg, var(--ok) 0%, var(--ok) 100%);
  border-color: var(--ok);
}

/* 交互态: 与全局按钮体系同款轻过渡 + hover 反馈 (.side-btn 的过渡/hover 已随上提走全局) */
.mode-btn, .act-btn, .tool-btn, .speed-apply {
  transition: background-color var(--transition-fast), color var(--transition-fast),
    border-color var(--transition-fast), box-shadow var(--transition-fast), filter var(--transition-fast);
}
.mode-btn:hover:not(.active):not(:disabled), .tool-btn:hover:not(.on):not(:disabled) { background: var(--hover); color: var(--text); }
.speed-apply:hover:not(:disabled) { background: var(--accent); }
.act-btn:hover:not(:disabled) { filter: brightness(1.06); }
.act-ghost:hover:not(:disabled) { filter: none; background: var(--hover); }
.act-ghost.danger:hover:not(:disabled) { background: var(--bad-soft); }

@media (max-width: 1100px) {
  .panel-layout {
    grid-template-columns: 1fr;
  }
  /* 单列堆叠时 TCP/关节不再并排, 隐藏竖向分隔条 */
  .seam-jog-v {
    display: none;
  }
  .tool-zone {
    grid-template-columns: 1fr;
  }
  .tool-io--endio, .tool-io--mount, .tool-io--rawdo {
    grid-column: auto;
    grid-row: auto;
  }
}

@media (max-width: 767.98px) {
  .tcp-grid {
    grid-template-columns: 1fr;
    grid-auto-flow: row;
  }
  .jog-toolbar {
    gap: 10px;
  }
  .side-btn {
    width: 44px;
    height: 44px;
  }
  .pose-value {
    white-space: normal;
    overflow-wrap: anywhere;
  }
}
</style>
