<script setup>
// 态势条 (常驻顶部): 标题 / 控制模式 / 连接 / 当前运行 / 设备健康汇总 / 急停
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useSystemStore, CONTROL_MODES, MODE_LABELS } from '../store'
import { useNodesStore } from '../stores/nodes'
import { useRunsStore, countSteps } from '../stores/runs'
import { useLayoutStore } from '../stores/layout'
import { useThemeStore } from '../stores/theme'
import { useDebugStore } from '../stores/debug'
import { useMonitorPrefsStore } from '../stores/monitorPrefs'
import { errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { announce } from '../composables/announcer.js'
import { useEstop } from '../composables/useEstop.js'
import { railStationText } from '../utils/deviceLabels.js'
import { sectionOf } from '../utils/section.js'

const sys = useSystemStore()
const nodes = useNodesStore()
const runs = useRunsStore()
const route = useRoute()
const router = useRouter()
const layout = useLayoutStore()
const themeStore = useThemeStore()
const debug = useDebugStore()

// 底栏 (当前运行/设备状态) 折叠开关: 按当前页 section 记忆, 写入 monitorPrefs 覆盖表
const monitorPrefs = useMonitorPrefsStore()
const section = computed(() => sectionOf(route.path))
const monitorCollapsed = computed(() => monitorPrefs.isCollapsed(section.value))

// 恢复默认布局 = 尺寸 + 底栏折叠偏好一并回默认: 整栏消失是最显眼的「布局」,
// 用户找不回底栏时会来点这颗, 不联动会留下"恢复了默认底栏还是没了"的死角
function resetLayout() {
  layout.resetAll()
  monitorPrefs.resetAll()
}
// 等待人工徽标: 常规 = hitl 已就位 (弹着或已稍后处理); 兜底 = 状态卡 WAITING_HUMAN 却无 hitl
// (事件丢失的残余失效模式) → 点击先 seedActive 手动找回再展开
const hitlWaiting = computed(() => !!debug.hitl || debug.status === 'WAITING_HUMAN')
async function openHitl() {
  if (!debug.hitl) await debug.seedActive()
  debug.hitlMinimized = false
}

// 一键跳转: 单运行仍进流程编辑器; 并行多运行时进实验看板 (单编辑器盛不下多条)
function openRunning() {
  if (runningCount.value > 1) {
    router.push('/experiment')
    return
  }
  const op = runs.live.operation
  if (op) router.push(`/library/operation/${op}`)
}

// 运行中的通道数 (并行调度下可 >1)
const runningCount = computed(() =>
  runs.activeRuns.filter((r) => r.status === 'RUNNING' || r.status === 'WAITING_HUMAN').length)

// 运行进度: 单运行保持原文案; 多运行显示条数 + 全体叶子步聚合 (只算运行中的通道)
const runProgress = computed(() => {
  const running = runs.activeRuns.filter((r) => r.status === 'RUNNING' || r.status === 'WAITING_HUMAN')
  if (!running.length) return null
  if (running.length === 1) {
    const r = running[0]
    const { total, done } = countSteps(r.steps)
    return { label: r.label || r.operation, done, total }
  }
  let total = 0
  let done = 0
  for (const r of running) {
    const c = countSteps(r.steps)
    total += c.total
    done += c.done
  }
  return { label: `${running.length} 个运行中`, done, total }
})

// 机械臂末端工具 (现接: 来自 robot 节点遥测 tool_state.mounted_tool)
const MOUNT_TOOL_NAMES = { 0: '无', 1: '吸盘', 2: '大夹爪', 3: '小夹爪' }
const robotTool = computed(() => {
  const mt = nodes.byId['robot']?.data?.tool_state?.mounted_tool
  return typeof mt === 'number' ? (MOUNT_TOOL_NAMES[mt] ?? '未知') : '—'
})
// 机械臂所在站点 (待 PLC 当前位置回读 current_position; 现无该字段则显示 —)
// current_positions: 后端据地轨实际位算出的命中站位码列表(重位可多个); 站名表见 utils/deviceLabels.js
const robotStation = computed(() =>
  railStationText(nodes.byId['plc.rail']?.data?.current_positions),
)

// 切模式: RUN→DEBUG 解锁全站直驱控制 (轴点动/DO 直控/PLC 写入), 必须过 danger 确认;
// 用户取消时把 select 回拨到当前值 (change 已经改了 DOM)
async function onModeChange(e) {
  const next = e.target.value
  if (next === sys.mode) return
  if (next === 'DEBUG') {
    const ok = await confirmAction({
      title: '切换到调试模式',
      message: '调试模式解锁全站直驱控制 (轴点动 / DO 直控 / PLC 写入), 误操作会产生真实机械动作。',
      level: 'danger',
      confirmText: '切换到调试',
    })
    if (!ok) {
      e.target.value = sys.mode
      return
    }
  }
  try {
    await sys.setMode(next)
    announce(`已切换到${MODE_LABELS[next] || next}模式`)
  } catch (err) {
    e.target.value = sys.mode
    announce(`切换模式失败: ${errText(err)}`, { assertive: true })
  }
}

// 急停迁移到 useEstop 模块级单例 (状态与各弹窗头部的 EstopButton 共享同步显示);
// 定案不变: 永不确认、永不禁用、每次点击直发。失败红字仍显示在本条 (estopError)。
const { busy: estopBusy, sent: estopSent, error: estopError, emergencyStop } = useEstop()
</script>

<template>
  <div class="statusbar">
    <h1>pTLC 上位机</h1>

    <div class="sb-item">
      <span class="lbl" aria-hidden="true">模式</span>
      <select :value="sys.mode" aria-label="控制模式" @change="onModeChange">
        <option v-for="m in CONTROL_MODES" :key="m" :value="m">{{ MODE_LABELS[m] }}</option>
      </select>
    </div>

    <span class="health-dot" :class="sys.streamConnected ? 'ok' : 'offline'" aria-hidden="true" />
    <span class="lbl" role="status">{{ sys.streamConnected ? '实时在线' : '实时断开' }}</span>

    <button type="button" class="btn-bare sb-item run-ind" v-if="runProgress" @click="openRunning" title="跳转到运行中的流程">
      <span>▶ {{ runProgress.label }}</span>
      <span class="muted num">({{ runProgress.done }}/{{ runProgress.total }})</span>
    </button>

    <button type="button" class="btn-bare sb-item hitl-ind" v-if="hitlWaiting" @click="openHitl" title="有流程在等待人工处理, 点击打开">
      <span class="badge WAITING_HUMAN">等待人工</span>
    </button>

    <!-- 设备健康汇总: 点 + 双字标签双编码 (照左侧连接态的 点+文本 写法), 不再纯色传状态 -->
    <div class="sb-summary" title="设备健康汇总: 正常 / 忙碌 / 错误 / 离线">
      <span class="chip" :aria-label="`正常 ${nodes.summary.ok} 台`"><span class="health-dot ok" aria-hidden="true" /><span class="chip-lbl" aria-hidden="true">正常</span><span class="num">{{ nodes.summary.ok }}</span></span>
      <span class="chip" :aria-label="`忙碌 ${nodes.summary.busy} 台`"><span class="health-dot busy" aria-hidden="true" /><span class="chip-lbl" aria-hidden="true">忙碌</span><span class="num">{{ nodes.summary.busy }}</span></span>
      <span class="chip" :aria-label="`错误 ${nodes.summary.error} 台`"><span class="health-dot error" aria-hidden="true" /><span class="chip-lbl" aria-hidden="true">错误</span><span class="num">{{ nodes.summary.error }}</span></span>
      <span class="chip" :aria-label="`离线 ${nodes.summary.offline} 台`"><span class="health-dot offline" aria-hidden="true" /><span class="chip-lbl" aria-hidden="true">离线</span><span class="num">{{ nodes.summary.offline }}</span></span>
    </div>

    <div class="sb-item">
      <span class="lbl">站点</span>
      <strong class="sb-val" title="机械臂所在站点 (待 PLC 当前位置回读)">{{ robotStation }}</strong>
    </div>
    <div class="sb-item">
      <span class="lbl">末端</span>
      <strong class="sb-val" title="机械臂末端挂载工具">{{ robotTool }}</strong>
    </div>

    <button class="btn-theme" type="button" @click="themeStore.toggle()"
      :aria-label="themeStore.theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
      :title="themeStore.theme === 'dark' ? '切换浅色主题' : '切换深色主题'"><span aria-hidden="true">{{ themeStore.theme === 'dark' ? '☀' : '☾' }}</span></button>
    <!-- 底栏开关: 固定 aria-label + aria-pressed 传状态 (动态 label 会与 pressed 双编码矛盾) -->
    <button class="btn-monitor" type="button" @click="monitorPrefs.toggle(section)"
      aria-label="底部监视栏" :aria-pressed="!monitorCollapsed"
      :title="monitorCollapsed ? '展开底部监视栏 (按页面记忆)' : '收起底部监视栏 (按页面记忆)'">
      <!-- 「带底栏的窗口」图标: 照 RailNav 的 Feather 风描边画法 -->
      <svg class="mon-ic" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13A1.5 1.5 0 0 1 5.5 4Z" />
        <path d="M4 14.5h16" />
      </svg>
    </button>
    <button class="btn-reset-layout" type="button" @click="resetLayout" title="把所有可拖拽栏恢复到默认尺寸, 并恢复各页底栏显示默认">恢复默认布局</button>
    <span v-if="estopError" class="estop-err" role="status">{{ estopError }} — 请使用物理急停</span>
    <button class="estop" type="button" :class="{ engaged: estopSent }" @click="emergencyStop">
      {{ estopBusy ? '急停 · 下发中…' : estopSent ? '急停 ✓ 已下发' : '急停' }}
    </button>
  </div>
</template>

<style scoped>
.run-ind { cursor: pointer; }
.run-ind:hover { text-decoration: underline; }
.hitl-ind { cursor: pointer; }
.chip-lbl { font-size: var(--fs-11); color: var(--muted); font-weight: 600; }
.estop-err { font-size: var(--fs-12); color: var(--bad); font-weight: 600; max-width: 260px; }
.hitl-ind .badge { animation: hitl-pulse 1.2s ease-in-out infinite; }
@keyframes hitl-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
.sb-val { font-size: var(--fs-13); font-weight: 600; color: var(--accent); white-space: nowrap; }
.btn-reset-layout { padding: 7px 14px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  border-radius: 6px; cursor: pointer; font-size: var(--fs-13); white-space: nowrap; }
.btn-reset-layout:hover { background: var(--hover); border-color: var(--accent); color: var(--accent); }
.btn-theme { padding: 7px 12px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  border-radius: 6px; cursor: pointer; font-size: var(--fs-14); line-height: 1; white-space: nowrap; }
.btn-theme:hover { background: var(--hover); border-color: var(--accent); color: var(--accent); }
/* 底栏开关: 盒式 icon 按钮照 .btn-theme; pressed(=显示中) 时图标走 accent 双编码状态 */
.btn-monitor { padding: 7px 12px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text);
  border-radius: 6px; cursor: pointer; line-height: 1; white-space: nowrap; }
.btn-monitor:hover { background: var(--hover); border-color: var(--accent); color: var(--accent); }
.btn-monitor[aria-pressed="true"] { color: var(--accent); }
.mon-ic { width: 16px; height: 16px; display: block; fill: none; stroke: currentColor;
  stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
</style>
