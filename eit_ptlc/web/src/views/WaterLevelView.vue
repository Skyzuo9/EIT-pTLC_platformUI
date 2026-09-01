<script setup>
// 液位检测外设控制台 (中区): /water_level/:channel? —— 香橙派 8 路液位调试/调参。
// 无 channel = 8 路网格总览; 有 channel = 单路调试。本视图统一轮询只读快照 (~1s) 下发给子组件,
// 避免多处重复轮询; 命令/视频走 api.wlCmd / wlFrameUrl 单帧轮询 (子组件直接调用)。
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { usePoll } from '../composables/usePoll.js'
import WaterLevelGrid from '../components/WaterLevelGrid.vue'
import WaterLevelChannel from '../components/WaterLevelChannel.vue'

const route = useRoute()
// online 三态: null=尚无一次成功快照 (连接中, 中性), true=在线, false=确证离线
const snap = ref({ online: null, channels: {}, params: {}, alarm_count: 0, enabled: false })
const err = ref('')

const channel = computed(() => (route.params.channel ? Number(route.params.channel) : null))

// 香橙派 SSH 远程管理 (启动/停止 run.sh)
const opi = ref({ enabled: false, running: false, target: '' })
const opiBusy = ref('')
const opiMsg = ref('')

let lastOpiSsh = 0          // 上次 SSH 探活时刻 (ms); 离线兜底 SSH 限频, 避免与启动命令抢 sshd
const OPI_SSH_MIN_GAP = 8000

async function pollOpi() {
  // 设备 MQTT 在线(LWT) 已证明脚本存活 → 直接信 MQTT, 不发 SSH (避免每轮新开 SSH 压垮 sshd)。
  // 仅离线时才慢频 SSH 兜底 (区分"进程死" vs "进程活但 MQTT 异常"), enabled 标志保留。
  if (snap.value.online) {
    opi.value = { ...opi.value, running: true }
    return
  }
  // 离线兜底 SSH 限频 (≥8s 一次): 每秒新开 SSH 会压垮香橙派 sshd 并与启动命令争连接
  if (opiBusy.value || Date.now() - lastOpiSsh < OPI_SSH_MIN_GAP) return
  lastOpiSsh = Date.now()
  try {
    opi.value = await api.wlOpiStatus()
  } catch (e) {
    /* 状态查询失败不打断主轮询, 保持上一次值 */
  }
}

async function opiStart() {
  if (opiBusy.value) return
  opiBusy.value = 'start'
  opiMsg.value = '正在 SSH 启动液位脚本…'
  try {
    await api.wlOpiStart(true) // wait=1: 启动后等 MQTT online 确认
    opiMsg.value = '已启动'
    await pollOpi()
  } catch (e) {
    opiMsg.value = '启动失败: ' + errText(e) + ' — 检查香橙派电源/网络与 SSH 免密配置后重试'
  } finally {
    opiBusy.value = ''
  }
}

async function opiStop() {
  if (opiBusy.value) return
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '停止远端液位脚本',
    message: '将通过 SSH 结束香橙派上的采集服务, 8 路液位读数中断。',
    ackText: '我确认当前无依赖液位的流程在跑',
    confirmText: '停止脚本',
  })
  if (!ok) return
  opiBusy.value = 'stop'
  opiMsg.value = '正在 SSH 停止液位脚本…'
  try {
    await api.wlOpiStop()
    opiMsg.value = '已停止'
    await pollOpi()
  } catch (e) {
    opiMsg.value = '停止失败: ' + errText(e) + ' — 脚本可能仍在运行, 检查 SSH 连通后重试'
  } finally {
    opiBusy.value = ''
  }
}

async function opiDeploy() {
  if (opiBusy.value) return
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '推送载荷到香橙派',
    message: '将通过 scp 覆盖香橙派 work_dir 下的载荷脚本文件, 无备份。',
    ackText: '我已确认本机载荷是要下发的版本, 允许覆盖远端',
    confirmText: '推送载荷',
  })
  if (!ok) return
  opiBusy.value = 'deploy'
  opiMsg.value = '正在 scp 推送载荷到香橙派…'
  try {
    const r = await api.wlOpiDeploy()
    opiMsg.value = '已推送: ' + (r.files || []).join(', ')
  } catch (e) {
    opiMsg.value = '推送失败: ' + errText(e) + ' — 检查 SSH/scp 连通与远端 work_dir 权限后重试'
  } finally {
    opiBusy.value = ''
  }
}

async function poll() {
  try {
    snap.value = await api.wlSnapshot()
    err.value = ''
  } catch (e) {
    err.value = errText(e)
  }
}

// 并发无害: pollOpi 同步早读 snap.online (取上一拍值), 与旧串行语义一致; 两函数各自吞错
const snapPoll = usePoll(() => Promise.all([poll(), pollOpi()]), 1000)

onMounted(() => {
  snapPoll.start()
})
</script>

<template>
  <div class="wl">
    <div class="wl-head">
      <h2>液位监测 <small>香橙派 · 8 路展缸</small></h2>
      <span role="status" class="wl-state" :class="{ on: snap.online === true, off: snap.online === false }">
        {{ snap.online === true ? '设备在线' : snap.online === false ? '设备离线' : '连接中…' }}
      </span>
      <span v-if="snap.alarm_count" role="status" class="wl-alarm">报警 {{ snap.alarm_count }}</span>
      <span v-if="!snap.enabled" class="muted">（未启用 / SIM：config.water_level.enabled=false）</span>
      <span v-if="err" role="status" class="wl-err">快照错误: {{ err }} — 检查设备电源/网络, 或尝试「启动液位脚本」</span>
    </div>

    <!-- 香橙派 SSH 远程管理: 启动/停止 run.sh (需本机已配 SSH 免密登录香橙派) -->
    <div v-if="opi.enabled" class="wl-opi">
      <span class="wl-opi-label">液位服务（<span class="mono">{{ opi.target }}</span>）</span>
      <span class="wl-opi-state" :class="{ on: opi.running }">{{ opi.running ? '脚本运行中' : '脚本未运行' }}</span>
      <button class="btn" :disabled="!!opiBusy" @click="opiStart">
        {{ opiBusy === 'start' ? '启动中…' : '启动液位脚本' }}
      </button>
      <button class="btn ghost" :disabled="!!opiBusy" @click="opiStop">
        {{ opiBusy === 'stop' ? '停止中…' : '停止液位脚本' }}
      </button>
      <button class="btn ghost" :disabled="!!opiBusy" @click="opiDeploy" title="scp 推送本机载荷脚本到香橙派 work_dir">
        {{ opiBusy === 'deploy' ? '推送中…' : '推送载荷' }}
      </button>
      <span v-if="opiMsg" role="status" class="muted">{{ opiMsg }}</span>
    </div>

    <WaterLevelChannel
      v-if="channel"
      :key="channel"
      :channel="channel"
      :ch-data="snap.channels?.[channel] || null"
      :params="snap.params?.[channel] || null"
      :online="snap.online"
    />
    <WaterLevelGrid v-else :snapshot="snap" />
  </div>
</template>

<style scoped>
.wl { padding: 4px 2px; }
.wl-head { display: flex; gap: 12px; align-items: baseline; margin-bottom: 12px; }
/* h3→h2 语义升级: 字号压回原 h3 观感 (UA h3 = 1.17em) */
.wl-head h2 { margin: 0; font-size: 1.17em; }
.wl-head small { color: var(--muted); font-weight: 500; }
.wl-state { font-size: var(--fs-12); padding: 2px 8px; border-radius: 999px; background: var(--chip-bg); color: var(--subtle); font-weight: 600; }
.wl-state.on { background: var(--ok-soft); color: var(--ok-strong); }
/* 确证离线 (拿到过快照且 online=false) 才标红; 尚未连上为中性"连接中" */
.wl-state.off { background: var(--bad-soft); color: var(--bad-strong); }
.wl-alarm { font-size: var(--fs-12); padding: 2px 8px; border-radius: 999px; background: var(--bad-soft); color: var(--bad-strong); }
.wl-err { color: var(--bad-strong); font-size: var(--fs-12); }
.muted { color: var(--muted); font-size: var(--fs-12); }
.wl-opi { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
.wl-opi-label { font-size: var(--fs-12); color: var(--subtle); font-weight: 600; }
.wl-opi-state { font-size: var(--fs-12); padding: 2px 8px; border-radius: 999px; background: var(--chip-bg); color: var(--subtle); font-weight: 600; }
.wl-opi-state.on { background: var(--ok-soft); color: var(--ok-strong); }
.mono { font-family: var(--font-mono); }
/* .btn 全套样式走全局 (style.css) */
</style>
