// 报警 store: 机器人碰撞/活动故障的一等公民告警 (顶部红条横幅 + 提示音)
// =====================================================================
// 设计要点 (状态对账, 非事件去重):
//   机器人故障本质是一个"锁存状态", 由 1Hz 遥测的 robot 节点 health 权威表达
//   (derive_health: error_ids 非空 或 check_result!=0 -> error; 见 runtime/node_registry.py)。
//   两个触发源共同驱动同一个锁存态 faultOn:
//     (a) 运行中: operation_failed 事件, 其 message 含 碰撞/collision/RobotMode= 等机器人故障标记
//         —— 立即 (无需等遥测) 且带驱动层富文本 ("机器人碰撞(活动故障)...: RobotMode=11, errors=[...]")。
//     (b) 空闲时: telemetry 事件 robot 节点 health==='error' —— 无运行也能告警, 文案由 error_ids/robot_mode 派生。
//   声音只在 faultOn 由 false->true 的"起始"响一次 (三声急促蜂鸣), 避免每秒重复。
//   清除: 遥测 robot health 回非 error (故障已由现场/维护页清除) -> 自动清横幅并复位;
//         或操作员点"关闭"(acked) -> 当前故障未解除也先静默隐藏, 解除后自动复位, 下次新故障再响。
// 说明: 后端 operation_failed 事件当前不带 error_code (仅 message), 故运行源以 message 文本判定/取码;
//       遥测源以 error_ids/robot_mode 取码。两源统一进 _raise 对账, 不做脆弱的跨源签名解析。
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

// 遥测中机器人节点 id (见 build_node_registry: NodeSpec("robot", ...))
const ROBOT_NODE = 'robot'
// Dobot RobotMode: 9=报警(ERROR) 11=碰撞(COLLISION) (见 driver/dobot_tcp_driver.py RobotMode)
const ROBOT_MODE_COLLISION = 11

// ---- 提示音 (Web Audio, 懒建 AudioContext; 被浏览器自动播放策略拦截则静默降级, 横幅仍在) ----
let _audioCtx = null
let _activeOsc = []
function _ctx() {
  try {
    if (_audioCtx == null) {
      const AC = window.AudioContext || window.webkitAudioContext
      if (!AC) return null
      _audioCtx = new AC()
    }
    if (_audioCtx.state === 'suspended') _audioCtx.resume().catch(() => {})
    return _audioCtx
  } catch (e) {
    return null
  }
}
function _beepAt(ctx, startT, freq, dur) {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()
  osc.type = 'square'
  osc.frequency.value = freq
  // 微包络: 起落各留斜坡避免爆音
  gain.gain.setValueAtTime(0.0001, startT)
  gain.gain.exponentialRampToValueAtTime(0.3, startT + 0.02)
  gain.gain.setValueAtTime(0.3, startT + dur - 0.03)
  gain.gain.exponentialRampToValueAtTime(0.0001, startT + dur)
  osc.connect(gain).connect(ctx.destination)
  osc.start(startT)
  osc.stop(startT + dur + 0.02)
  _activeOsc.push(osc)
  osc.onended = () => { _activeOsc = _activeOsc.filter((o) => o !== osc) }
}
function _playAlarmSound() {
  const ctx = _ctx()
  if (!ctx) return
  try {
    const t0 = ctx.currentTime + 0.01
    const dur = 0.18
    const gap = 0.12
    for (let i = 0; i < 3; i++) _beepAt(ctx, t0 + i * (dur + gap), 880, dur) // 三声急促高频
  } catch (e) {
    /* 音频异常不影响视觉告警 */
  }
}
function _stopAlarmSound() {
  for (const osc of _activeOsc) { try { osc.stop() } catch (e) { /* 已停止 */ } }
  _activeOsc = []
}

// ---- 触发判定 / 文案派生 ----
// 运行中 operation_failed 是否为机器人故障 (只认机器人相关, 不误伤普通动作失败/PLC 拒绝)
function _isRobotFault(ev) {
  const m = (ev && ev.message) || ''
  if (/碰撞|collision/i.test(m)) return true
  if (/RobotMode\s*=\s*(9|11)\b/.test(m)) return true            // 9=报警 11=碰撞 活动故障
  if (/机器人.*(故障|报警)/.test(m)) return true
  if (/机器人/.test(m) && /errors\s*=\s*\[/.test(m)) return true // 机器人报警 id 直陈
  return false
}
// 从运行源富文本抽取报警码 (优先首个 error id, 退化到 RobotMode)
function _codeFromMessage(m) {
  const e = (m || '').match(/errors\s*=\s*\[([^\]]*)\]/)
  if (e && e[1].trim()) return e[1].split(',')[0].trim()
  const rm = (m || '').match(/RobotMode\s*=\s*(\d+)/)
  return rm ? `RobotMode=${rm[1]}` : ''
}
// 空闲源: 由 robot 遥测快照派生报警码与文案 (data 见 _robot_feedback_to_dict)
function _codeFromTelemetry(data) {
  const ids = (data && data.error_ids) || []
  if (ids.length) return String(ids[0])
  const mode = data && data.robot_mode
  return mode != null ? `RobotMode=${mode}` : ''
}
/**
 * 功能: 由 robot 遥测快照派生一句故障文案.
 *
 * 导出是给三维实时页的工位状态栏用的 —— 侧栏与本报警横幅必须说同一句话,
 * 否则同一个故障在两处措辞不同, 操作员会以为是两回事.
 * @param {object} data robot 节点遥测 data (见后端 _robot_feedback_to_dict)
 * @returns {string} 中文故障描述
 */
export function robotFaultText(data) {
  const ids = (data && data.error_ids) || []
  const mode = data && data.robot_mode
  const isColl = mode === ROBOT_MODE_COLLISION || (data && data.collision_state)
  const parts = [`机器人${isColl ? '碰撞' : '报警'}(活动故障)`]
  if (mode != null) parts.push(`RobotMode=${mode}`)
  if (ids.length) parts.push(`errors=[${ids.join(', ')}]`)
  return parts.join(', ')
}
const _messageFromTelemetry = robotFaultText

export const useAlarmStore = defineStore('alarms', () => {
  const faultOn = ref(false)          // 机器人故障锁存态 (两源共同驱动; 遥测回 ok 才落回)
  const acked = ref(false)            // 操作员已"关闭"当前故障 (静默隐藏, 解除后复位)
  const current = ref(null)           // {source:'running'|'idle', message, code, ts} | null

  // 横幅可见 = 有故障 且 未被关闭
  const visible = computed(() => faultOn.value && !acked.value && current.value != null)

  // 统一起警对账: onset (false->true) 才发声; running 富文本可覆盖 idle 派生文案, 反之不降级
  function _raise(source, message, code) {
    const onset = !faultOn.value
    faultOn.value = true
    if (onset || (source === 'running' && (current.value == null || current.value.source !== 'running'))) {
      current.value = { source, message, code: code || '—', ts: Date.now() }
    }
    if (onset) _playAlarmSound()
  }

  // 故障解除 (遥测 robot health 回非 error): 清横幅并复位, 使下次新故障重新起警发声
  function _resolve() {
    if (!faultOn.value) return
    faultOn.value = false
    acked.value = false
    current.value = null
    _stopAlarmSound()
  }

  // 操作员关闭横幅: 当前故障未解除也先静默隐藏 (不清 faultOn, 待遥测回 ok 再复位)
  function dismiss() {
    acked.value = true
    _stopAlarmSound()
  }

  // WS 事件消费 (在 App.vue onEvent 注册, 与 nodes/runs/debug 并列)
  function ingest(event) {
    const t = event && event.type
    if (t === 'telemetry') {
      if (event.node !== ROBOT_NODE) return
      if (event.health === 'error') {
        _raise('idle', _messageFromTelemetry(event.data), _codeFromTelemetry(event.data))
      } else {
        _resolve() // ok/busy/offline: 机器人不在活动故障 -> 解除
      }
    } else if (t === 'operation_failed') {
      if (_isRobotFault(event)) {
        const code = _codeFromMessage(event.message) || (event.error_code ? String(event.error_code) : '')
        _raise('running', event.message || '机器人故障', code)
      }
    }
  }

  return { faultOn, acked, current, visible, dismiss, ingest }
})
