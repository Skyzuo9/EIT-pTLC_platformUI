<script setup>
// 右栏 (POU 模式): IDE 连接状态 (只读镜像) + 编译/保存按钮 + 编译错误/警告列表 + 下载到设备。
// 连接由左栏「连接」按钮显式触发 (plc.connect); 本面板不自动拉起 InoProShop。
// 编译: 先把当前文本写入内存工程再 build (store.compile); 满意后「保存到工程」落盘。
// 下载到设备: 全下载到真机 (编译 0 错误 + 已保存 + allow_deploy 才可点; 二次确认)。
// 后端先让 PLC 安全停轴/撤销使能，再下载并自动启动，等待 EtherCAT 与 5Z→4X 回零就绪。
import { ref, computed, onMounted } from 'vue'
import { confirmAction } from '../../composables/confirmService.js'
import { usePlcStore } from '../../stores/plc'

const plc = usePlcStore()

// 下发确认框本地态
const showDeployConfirm = ref(false)
const safeAck = ref(false)

// 最近一次编译是否 0 错误 (下发硬门控之一; 后端 deploy 还会再 build 兜底)
const compiledClean = computed(() => {
  const r = plc.compileResult
  return !!r && !r.error && r.error_count === 0
})
const manualControl = computed(() => !!plc.sessionStatus?.manual_control)
const sessionLabel = computed(() => {
  if (manualControl.value) return '用户接管'
  if (plc.sessionStatus?.worker_alive) return '共享在线'
  if (plc.sessionStatus?.keeper_alive) return '保活中'
  return '未保活'
})
const leaseLabel = computed(() => {
  const lease = plc.sessionStatus?.lease
  if (!plc.sessionStatus?.lease_active || !lease) return ''
  return `${lease.owner || 'client'} / ${lease.op || lease.last_op || 'operation'}`
})
// 会话属主独占: 某个自动方(agent/后端)正会话级独占共享实例; 空闲多久后即可被别的进程接管
const ownerLabel = computed(() => {
  const s = plc.sessionStatus
  if (!s?.owned || !s.owner) return ''
  const idle = typeof s.owner_idle_sec === 'number' ? ` · 空闲 ${Math.round(s.owner_idle_sec)}s` : ''
  return `${s.owner.label || 'client'}${idle}`
})
const downloaded = computed(() => !!(plc.deployResult &&
  (plc.deployResult.downloaded === true || plc.deployResult.deployed === true)))
const deploySucceeded = computed(() => downloaded.value && plc.deployResult?.ready === true)
const deployInProgress = computed(() => plc.deploying || plc.deployProgress?.active === true)
const maintenanceLocked = computed(() => plc.sessionStatus?.maintenance?.active === true)

const deployPhases = ['编译', '准备安全态', '下载', '重连', '5Z 回零', '4X 回零', '就绪']
// 阶段状态字形/读法: 状态不纯靠圆点配色 (色弱/读屏可辨); 字形即文本, 进 li 可见内容
const PHASE_GLYPH = { done: '✓ ', error: '✗ ', running: '· ' }
const PHASE_STATE_LABEL = { done: '完成', error: '失败', running: '进行中', pending: '待执行' }
const currentDeployPhaseLabel = computed(() => {
  const index = Number(plc.deployProgress?.phase_index)
  if (!Number.isInteger(index) || index < 0 || index >= deployPhases.length) return '等待阶段遥测'
  if (index === 2 && Number(plc.deployProgress?.deploy_state) === 25) {
    return '下载（State 25 已提交，不可由普通取消撤销）'
  }
  return deployPhases[index]
})
const phaseStates = computed(() => {
  const live = plc.deployProgress?.phase_states
  if ((deployInProgress.value || plc.deployResult) && Number(plc.deployProgress?.attempt) > 0 &&
      Array.isArray(live) && live.length === deployPhases.length) {
    return live
  }
  if (plc.deploying) return deployPhases.map(() => 'pending')
  const r = plc.deployResult
  if (!r) return deployPhases.map(() => 'pending')
  if (deploySucceeded.value) return deployPhases.map(() => 'done')

  const states = deployPhases.map(() => 'pending')
  if (downloaded.value) {
    states[0] = states[1] = states[2] = 'done'
    const startup = Number(r.startup_state)
    if (startup === 60) {
      for (let i = 3; i < states.length - 1; i += 1) states[i] = 'done'
      states[6] = 'error'
    } else if (startup === 50 || startup === 51) {
      states[3] = states[4] = 'done'
      states[5] = 'error'
    } else if (startup === 40 || startup === 41) {
      states[3] = 'done'
      states[4] = 'error'
    } else if (startup === 10 || startup === 20 || startup === 30 || r.started === false) {
      states[3] = 'error'
    } else {
      // State=90 只表示启动状态机已失败，不能凭空推断失败发生在哪根轴。
      states[6] = 'error'
    }
    return states
  }

  const stage = String(r.stage || plc.deployStage || '')
  const failed = stage.includes('compile') ? 0
    : (stage.includes('download') ? 2 : 1)
  for (let i = 0; i < failed; i += 1) states[i] = 'done'
  states[failed] = 'error'
  return states
})

// 可下发 = 已连接 + 无未保存改动 + allow_deploy + 编译过且 0 错误 + 非下发中 + 本会话未锁定
const canDeploy = computed(() =>
  plc.connected && !manualControl.value && !plc.dirty && plc.allowDeploy && compiledClean.value &&
  !deployInProgress.value && !plc.deployRetryLocked && !maintenanceLocked.value)

function openDeploy() {
  if (manualControl.value) return
  safeAck.value = false
  showDeployConfirm.value = true
  plc.loadOnlineStatus()  // 打开确认框时探测真机前置条件
}
async function confirmDeploy() {
  if (manualControl.value) return
  showDeployConfirm.value = false
  await plc.deploy()
}

async function reconcileMaintenance() {
  // normal 级: 纯只读对账, 不下载不发运动命令
  const confirmed = await confirmAction({
    title: '读取 PLC 对账',
    message: '仅当你已在 InoProShop 人工核对在线应用版本，并确认现场已恢复安全状态时继续。' +
      '系统随后只读检查 Startup=60、PLC_Ready=TRUE、Deploy=0；不会再次下载或发运动命令。',
    confirmText: '读取',
  })
  if (!confirmed) return
  await plc.reconcileMaintenance()
}

onMounted(() => {
  plc.loadSession().catch(() => {})
  plc.loadDeployProgress().catch(() => {})
})
</script>

<template>
  <div class="compile-panel">
    <h4 class="col-title">编译 / 工程</h4>

    <div class="worker-status">
      <span class="lbl">IDE 状态</span>
      <span v-if="plc.statusBusy" class="val">连接中…</span>
      <span v-else-if="plc.connected" class="val ok">{{ plc.workerStatus?.state || '已连接' }}</span>
      <span v-else class="val" :class="{ err: plc.statusError }">未连接</span>
    </div>
    <p v-if="plc.statusError" class="hint err">连接失败: {{ plc.statusError }} —— 请在左栏点击「连接」重新拉起</p>

    <div class="session-box" :class="{ manual: manualControl }">
      <div class="session-line">
        <span class="lbl">会话</span>
        <span class="val" :class="{ ok: !manualControl && (plc.sessionStatus?.worker_alive || plc.sessionStatus?.keeper_alive), warn: manualControl }">
          {{ sessionLabel }}
        </span>
      </div>
      <div class="session-meta">
        <span>keeper {{ plc.sessionStatus?.keeper_alive ? '在线' : '离线' }}</span>
        <span>worker {{ plc.sessionStatus?.worker_alive ? '在线' : '离线' }}</span>
      </div>
      <p v-if="leaseLabel" class="hint muted tight">占用: {{ leaseLabel }}</p>
      <p v-if="ownerLabel" class="hint muted tight">属主独占: {{ ownerLabel }}</p>
      <p v-if="plc.sessionMsg" class="hint tight" :class="{ warn: manualControl }">{{ plc.sessionMsg }}</p>
      <div class="session-actions">
        <button class="mini" :disabled="plc.sessionBusy" @click="plc.loadSession()">刷新</button>
        <button v-if="!manualControl" class="mini" :disabled="plc.sessionBusy" @click="plc.takeoverSession()">接管</button>
        <button v-else class="mini ok" :disabled="plc.sessionBusy" @click="plc.releaseSession()">释放</button>
      </div>
    </div>
    <p v-if="manualControl" class="hint warn">用户已接管; 窗口继续保活，自动读写暂停</p>

    <div class="actions">
      <button class="primary" :disabled="manualControl || !plc.currentPath || plc.compiling || plc.saving" @click="plc.compile()">
        {{ plc.compiling ? '编译中…' : '编译' }}
      </button>
      <button :disabled="manualControl || !plc.currentPath || plc.saving || plc.compiling || !plc.dirty" @click="plc.save()">
        {{ plc.saving ? '保存中…' : '保存到工程' }}
      </button>
    </div>
    <p v-if="plc.saveMsg" class="save-msg">{{ plc.saveMsg }}</p>

    <div v-if="plc.compileResult" class="compile-result">
      <template v-if="plc.compileResult.error">
        <p class="hint err">编译调用失败: {{ plc.compileResult.error }}</p>
      </template>
      <template v-else>
        <p class="summary" :class="plc.compileResult.error_count ? 'err' : 'ok'">
          {{ plc.compileResult.error_count ? `✖ ${plc.compileResult.error_count} 错误` : '✓ 0 错误' }}
          · {{ plc.compileResult.warning_count }} 警告
        </p>
        <ul class="msg-list">
          <li v-for="(m, i) in plc.compileResult.errors" :key="'e' + i" class="msg err">E: {{ m.text }}</li>
          <li v-for="(m, i) in plc.compileResult.warnings" :key="'w' + i" class="msg warn">W: {{ m.text }}</li>
        </ul>
      </template>
    </div>

    <p class="muted">编译前会把当前文本写入内存工程; 校验满意后点「保存到工程」落盘 .project。</p>

    <!-- ── 下载到设备 (安全停机握手 → 全下载 → 自动启动/回零) ── -->
    <div class="deploy-sec">
      <h4 class="col-title">下载到设备</h4>
      <button class="btn danger" :disabled="!canDeploy" @click="openDeploy()">
        {{ deployInProgress ? '下发中…' : '下载到设备' }}
      </button>
      <p v-if="plc.deployRetryLocked || maintenanceLocked" class="hint lock-warn" role="alert">下载结果未确认或 PLC 未就绪 —— 维护门保持锁定，请人工核对在线版本与设备状态并完成只读对账，禁止再次下载</p>
      <button v-if="maintenanceLocked" class="mini"
              :disabled="deployInProgress || plc.reconcileBusy"
              @click="reconcileMaintenance()">
        {{ plc.reconcileBusy ? '对账中…' : '已核对在线版本，执行只读安全对账' }}
      </button>
      <p v-else-if="manualControl" class="hint muted">用户已接管 —— 释放后才可下载</p>
      <p v-else-if="!plc.connected" class="hint muted">未连接 —— 请先在左栏点击「连接」</p>
      <p v-else-if="!plc.allowDeploy" class="hint muted">部署未启用 (codesys.allow_deploy=false) —— spike 真机验证通过后开启</p>
      <p v-else-if="plc.dirty" class="hint muted">有未保存改动 —— 请先「保存到工程」</p>
      <p v-else-if="!compiledClean" class="hint muted">需先「编译」且 0 错误才可下发</p>

      <ol class="deploy-phases" :class="{ executing: deployInProgress }" aria-label="PLC 下载阶段">
        <li v-for="(phase, i) in deployPhases" :key="phase" :class="phaseStates[i]"
            :aria-label="`${phase}: ${PHASE_STATE_LABEL[phaseStates[i]] || '待执行'}`">
          <span class="phase-dot" aria-hidden="true"></span>
          <span>{{ (PHASE_GLYPH[phaseStates[i]] || '') + phase }}</span>
        </li>
      </ol>
      <p v-if="deployInProgress" class="hint muted tight">当前阶段：{{ currentDeployPhaseLabel }}；阶段查询只读后端内存，不会干扰 PLC 下载。</p>

      <div v-if="showDeployConfirm" class="confirm-box">
        <p class="warn-text">⚠ 系统会先确认设备空闲、泵/排液/气动输出已处于允许掉电的安全态，再让 PLC 受控停轴并撤销伺服使能；全下载后将<b>自动启动，并依次执行 5Z、4X 回零</b>。请清空两轴运动范围并确保急停可用。</p>
        <!-- 在线探测行: 全局 .probe-line 二态 (ok/bad); 状态/原因附加信息拼进同一行文案 -->
        <p v-if="plc.onlineStatus" class="probe-line" :class="plc.onlineStatus.ready ? 'ok' : 'bad'">在线探测: {{ plc.onlineStatus.ready ? '可对接' : '不可对接' }}{{ plc.onlineStatus.state ? ` · 状态 ${plc.onlineStatus.state}` : '' }}{{ !plc.onlineStatus.ready && plc.onlineStatus.reason ? ` (${plc.onlineStatus.reason}; 请在 InoProShop GUI 设好活动通信路径)` : '' }}</p>
        <label class="ack"><input type="checkbox" v-model="safeAck" /> 我确认当前无工艺动作，全部泵/阀/气缸可安全掉电，且 4X/5Z 回零路径安全</label>
        <div class="confirm-actions">
          <button class="btn danger" :disabled="manualControl || !safeAck || deployInProgress" @click="confirmDeploy()">确认下载</button>
          <button class="btn ghost" @click="showDeployConfirm = false">取消</button>
        </div>
      </div>

      <p v-if="plc.deployMsg" class="save-msg" role="status"
         :class="{ ok: deploySucceeded, err: !deploySucceeded }">
        {{ plc.deployMsg }}
      </p>
      <ul v-if="plc.deployResult && !downloaded && plc.deployResult.errors" class="msg-list">
        <li v-for="(m, i) in plc.deployResult.errors" :key="'de' + i" class="msg err">E: {{ m.text }}</li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.col-title { margin: 0 0 8px; font-size: var(--fs-13); color: var(--text); font-weight: 700; }
.worker-status { display: flex; gap: 8px; align-items: center; font-size: var(--fs-12); }
.worker-status .lbl { color: var(--muted); }
.worker-status .val { font-weight: 700; }
.worker-status .val.ok { color: var(--ok); }
.worker-status .val.err { color: var(--bad); }
.session-box { margin-top: 8px; padding: 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); }
.session-box.manual { border-color: var(--warn); }
.session-line { display: flex; align-items: center; gap: 8px; font-size: var(--fs-12); }
.session-line .lbl { color: var(--muted); }
.session-line .val { font-weight: 700; }
.session-line .val.ok { color: var(--ok); }
.session-line .val.warn { color: var(--warn); }
.session-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 5px; color: var(--muted); font-size: var(--fs-11); }
.session-actions { display: flex; gap: 6px; margin-top: 8px; }
.session-actions .mini.ok { border-color: var(--ok); color: var(--ok); }
.actions { display: flex; gap: 8px; margin: 12px 0 4px; }
.actions button { padding: 6px 14px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); cursor: pointer; border-radius: var(--radius-md); font-weight: 600; }
.actions button.primary { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.actions button:disabled { opacity: 0.5; cursor: not-allowed; }
.save-msg { font-family: var(--font-mono); font-size: var(--fs-12); margin: 4px 0; }
.summary { font-weight: 700; margin: 8px 0 4px; }
.summary.ok { color: var(--ok); }
.summary.err { color: var(--bad); }
.msg-list { list-style: none; padding: 0; margin: 0; max-height: 40vh; overflow: auto; }
.msg { font-family: var(--font-mono); font-size: var(--fs-12); padding: 2px 0; white-space: pre-wrap; word-break: break-word; }
.msg.err { color: var(--bad); }
.msg.warn { color: var(--warn); }
.hint { font-size: var(--fs-12); }
.hint.err { color: var(--bad); }
.hint.warn { color: var(--warn); }
.hint.tight { margin: 5px 0 0; }
.hint.muted { margin-top: 4px; }
/* .mini 基础样式走全局 (style.css) */
.muted { color: var(--muted); font-size: var(--fs-11); margin-top: 12px; }

/* ── 下载到设备 ── */
/* 下载/确认按钮与确认段吃全局体系 (.btn danger / .btn ghost / .confirm-box / .warn-text / .ack /
   .confirm-actions / .probe-line, 均定义于 style.css), 本组件不再自造 */
.deploy-sec { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
.deploy-sec .col-title { margin-bottom: 8px; }
.lock-warn { color: var(--bad); font-weight: 700; line-height: 1.45; }
.deploy-phases { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 3px; list-style: none; padding: 0; margin: 10px 0 4px; }
.deploy-phases li { min-width: 0; display: flex; flex-direction: column; align-items: center; gap: 4px; color: var(--muted); font-size: 10px; text-align: center; }
.phase-dot { width: 9px; height: 9px; border: 1px solid var(--border); border-radius: 50%; background: var(--surface-2); }
.deploy-phases li.done { color: var(--ok); }
.deploy-phases li.done .phase-dot { border-color: var(--ok); background: var(--ok); }
.deploy-phases li.error { color: var(--bad); font-weight: 700; }
.deploy-phases li.error .phase-dot { border-color: var(--bad); background: var(--bad); }
.deploy-phases li.running { color: var(--accent); }
.deploy-phases li.running .phase-dot { border-color: var(--accent); animation: deploy-pulse 1s ease-in-out infinite alternate; }
@keyframes deploy-pulse { from { background: transparent; } to { background: var(--accent); } }
.save-msg.ok { color: var(--ok); }
.save-msg.err { color: var(--bad); }
</style>
