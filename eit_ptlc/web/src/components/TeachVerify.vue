<script setup>
// 示教复核 (teach-verify): 竖向分步引导 —— ①采集当前位为示教点 → ②退到进近点 → ③二次进入复核
// → ④回位漂移检查 → ⑤提交。所有机器人运动仅 DEBUG、长按 deadman (松手即停)、限速 (走 teach/move)。
// 与 PointsView 的 run-block / teach-block 同套 idiom (ARM_MS 长按触发、指针捕获、fmtVec/fmtDelta)。
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'

const props = defineProps({
  pointId: { type: String, required: true }, // URL 中的 point_id
  robotName: { type: String, default: '' },
  isGrid: { type: Boolean, default: false }, // 网格库位 (锚点→重解整架 / 非锚位→写库位偏置)
  disabled: { type: Boolean, default: false }, // true = 非 DEBUG, 禁用一切运动/提交
})
const emit = defineEmits(['committed'])

const ARM_MS = 500

// --- 状态机 refs ---
const capture = ref(null) // { point_id, robot_name, is_grid, is_anchor, has_approach, current, captured, delta }
const plan = ref(null) // { target_pose:[6], has_approach, waypoints:[{role,label,pose:[6]}] }  (近→远)
const drift = ref(null) // { actual:[6], drift_mm, drift_deg, over }
const note = ref('')
const busy = ref(false) // 采集/规划/漂移/提交 的网络忙 (与长按序列 runDir 区分)
const captureMsg = ref('')
const driftMsg = ref('')
const commitMsg = ref('')

// --- 长按序列 deadman 态 ---
const armDir = ref('') // '' | 'out' | 'in' —— 正在长按计时的方向
const runDir = ref('') // '' | 'out' | 'in' —— 正在走位的方向
const seqStatus = ref('')
let armTimer = null
let seqPointerEl = null
let seqPointerId = null
let cancelFlag = false // 松手/取消标志; 序列循环在每步之间同步读取以中止

const hasWaypoints = computed(
  () => !!plan.value && Array.isArray(plan.value.waypoints) && plan.value.waypoints.length > 0,
)
const canCommit = computed(
  () => !!capture.value && !props.disabled && !busy.value && !runDir.value && !armDir.value,
)

function fmtVec(vec) {
  return (vec || []).map((v) => Number(v).toFixed(4)).join(', ')
}
function fmtDelta(vec) {
  return (vec || [])
    .map((v) => {
      const n = Number(v)
      return `${n >= 0 ? '+' : ''}${n.toFixed(4)}`
    })
    .join(', ')
}

// ---- Step ① 采集当前位置为示教点 (操作员已手动 jog 到位) ----
async function doCapture() {
  if (props.disabled || busy.value || runDir.value || armDir.value) return
  busy.value = true
  captureMsg.value = ''
  commitMsg.value = ''
  try {
    const cap = await api.captureRobotPoint(props.pointId)
    capture.value = cap
    plan.value = null
    drift.value = null
    seqStatus.value = ''
    captureMsg.value = '已把当前位置采集为示教点，请核对差值。'
    if (cap.has_approach) {
      // 用「新」采集位姿重算进近航点 (verify-with-new-geometry)
      try {
        plan.value = await api.teachPlan(props.pointId, cap.captured.pose)
      } catch (e) {
        captureMsg.value = '进近点规划失败: ' + errText(e)
      }
    }
  } catch (e) {
    capture.value = null
    captureMsg.value = '读取失败: ' + errText(e)
  } finally {
    busy.value = false
  }
}

// ---- Step ②③ 长按序列: out = 退出 (近→远, 数组序); in = 进入 (远→近, 反序) 再回示教点 ----
function buildSeq(dir) {
  const wps = plan.value?.waypoints || []
  const step = (w) => ({ pose: w.pose, label: w.label || w.role || '进近点' })
  if (dir === 'out') return wps.map(step)
  const seq = [...wps].reverse().map(step)
  seq.push({ pose: plan.value.target_pose, label: '示教点' })
  return seq
}

function pressSeq(dir, event) {
  if (props.disabled || runDir.value || armDir.value || !hasWaypoints.value) return
  event.preventDefault()
  const el = event.currentTarget
  try {
    if (el) el.setPointerCapture(event.pointerId)
  } catch (_e) {
    // 某些场景无法捕获, 忽略
  }
  seqPointerEl = el
  seqPointerId = event.pointerId
  cancelFlag = false
  armDir.value = dir
  seqStatus.value = `按住中… 保持 ${ARM_MS}ms 触发 (松开取消)`
  armTimer = window.setTimeout(() => fireSeq(dir), ARM_MS)
}

async function fireSeq(dir) {
  armTimer = null
  if (armDir.value !== dir) return // 计时途中已释放
  armDir.value = ''
  runDir.value = dir
  const seq = buildSeq(dir)
  const label = dir === 'out' ? '退出中' : '进入中'
  try {
    for (let i = 0; i < seq.length; i++) {
      if (cancelFlag) {
        seqStatus.value = '已停止 (未到位)'
        return
      }
      const s = seq[i]
      seqStatus.value = `${label}… ${s.label} (${i + 1}/${seq.length})`
      const r = await api.teachMove(props.pointId, s.pose, 'move_l')
      if (cancelFlag || (r && r.status === 'CANCELLED')) {
        seqStatus.value = '已停止 (未到位)'
        return
      }
      if (r && r.status && r.status !== 'DONE') {
        seqStatus.value = `${r.status}: ${r.message || ''}`
        return
      }
    }
    if (dir === 'out') {
      seqStatus.value = '已退到最远进近点 ✓ 可长按「二次进入复核」'
    } else {
      seqStatus.value = '已二次进入到位 ✓ 自动做回位漂移检查…'
      await runDrift()
    }
  } catch (e) {
    seqStatus.value = '错误: ' + errText(e)
  } finally {
    runDir.value = ''
  }
}

async function releaseSeq(event) {
  if (seqPointerId !== null && event && event.pointerId !== seqPointerId) return
  if (seqPointerEl && seqPointerId !== null) {
    try {
      if (seqPointerEl.hasPointerCapture(seqPointerId))
        seqPointerEl.releasePointerCapture(seqPointerId)
    } catch (_e) {
      // 元素已失活, 忽略
    }
  }
  seqPointerEl = null
  seqPointerId = null
  if (armTimer !== null) {
    window.clearTimeout(armTimer)
    armTimer = null
    if (armDir.value) seqStatus.value = '已取消 (长按不足)'
  }
  armDir.value = ''
  if (runDir.value) {
    // 走位中松手 -> 置取消标志 + 物理停止; in-flight teachMove 随后以 CANCELLED 收尾
    cancelFlag = true
    seqStatus.value = '停止中…'
    try {
      await api.robotStop()
    } catch (_e) {
      // 松手停失败不覆盖现有状态
    }
  }
}

// ---- Step ④ 回位漂移检查 (二次进入到位后自动 / 或手动复核) ----
async function runDrift() {
  if (!capture.value || props.disabled) return
  busy.value = true
  driftMsg.value = ''
  try {
    drift.value = await api.teachDrift(props.pointId, capture.value.captured.pose)
    driftMsg.value = drift.value.over ? '' : '回位漂移在阈内 ✓'
  } catch (e) {
    drift.value = null
    driftMsg.value = '漂移检查失败: ' + errText(e)
  } finally {
    busy.value = false
  }
}

// ---- Step ⑤ 提交 (覆盖真源) ----
function resetWorkflow() {
  capture.value = null
  plan.value = null
  drift.value = null
  note.value = ''
  seqStatus.value = ''
  captureMsg.value = ''
  driftMsg.value = ''
}

async function doCommit() {
  if (!canCommit.value) return
  const cap = capture.value
  const jd = cap.delta.joint ? fmtDelta(cap.delta.joint) : '— (直线点)'
  if (!(await confirmAction({
    level: 'danger-ack',
    title: '提交示教修正',
    message: `确认保存「${props.pointId}」为示教点?`,
    detail: `pose Δ: ${fmtDelta(cap.delta.pose)}  ·  joint Δ: ${jd}`,
    ackText: '我已确认修正量合理',
    confirmText: '提交',
  })))
    return
  busy.value = true
  commitMsg.value = ''
  try {
    const r = await api.commitRobotPoint(props.pointId, {
      pose: cap.captured.pose,
      joint: cap.captured.joint,
      note: note.value,
      confirm: true,
    })
    resetWorkflow()
    commitMsg.value = `已保存 ✓${r && r.points ? ` (${r.points} 点已重载)` : ''}`
    emit('committed', { pointId: props.pointId, result: r })
  } catch (e) {
    commitMsg.value = '保存失败: ' + errText(e)
  } finally {
    busy.value = false
  }
}

// ---- 安全: 切点/卸载/失焦时若仍在走位 -> 取消 + 物理停 ----
function safetyStop() {
  if (armTimer !== null) {
    window.clearTimeout(armTimer)
    armTimer = null
  }
  armDir.value = ''
  if (runDir.value) {
    cancelFlag = true
    try {
      api.robotStop()
    } catch (_e) {
      // 兜底, 忽略
    }
  }
}

watch(
  () => props.pointId,
  () => {
    safetyStop()
    resetWorkflow()
    commitMsg.value = ''
  },
)

onMounted(() => {
  window.addEventListener('blur', safetyStop)
  window.addEventListener('pagehide', safetyStop)
})
onBeforeUnmount(() => {
  window.removeEventListener('blur', safetyStop)
  window.removeEventListener('pagehide', safetyStop)
  safetyStop()
})
</script>

<template>
  <div class="tv">
    <p v-if="disabled" class="tv-disabled">当前非 DEBUG，示教/运动已禁用</p>

    <!-- ① 示教当前位置 -->
    <section class="tv-step">
      <div class="tv-head"><span class="tv-num">①</span><strong>示教当前位置</strong></div>
      <p class="tv-hint">先手动 jog 机器人到目标位姿，再点下方按钮把「当前位置」采集为示教点。</p>
      <div class="tv-row">
        <button class="tv-btn" :disabled="disabled || busy || !!runDir || !!armDir" @click="doCapture">
          {{ busy && !runDir ? '处理中…' : '读取当前位置' }}
        </button>
      </div>
      <div v-if="capture" class="tv-compare">
        <div class="tv-col">
          <strong>pose</strong>
          <dl>
            <dt>当前</dt><dd>{{ fmtVec(capture.current.pose) }}</dd>
            <dt>采集</dt><dd>{{ fmtVec(capture.captured.pose) }}</dd>
            <dt>差值</dt><dd>{{ fmtDelta(capture.delta.pose) }}</dd>
          </dl>
        </div>
        <div class="tv-col">
          <strong>joint</strong>
          <dl>
            <dt>当前</dt><dd>{{ capture.current.joint ? fmtVec(capture.current.joint) : '— (直线点)' }}</dd>
            <dt>采集</dt><dd>{{ capture.captured.joint ? fmtVec(capture.captured.joint) : '—' }}</dd>
            <dt>差值</dt><dd>{{ capture.delta.joint ? fmtDelta(capture.delta.joint) : '—' }}</dd>
          </dl>
        </div>
      </div>
      <p v-if="captureMsg" class="tv-msg">{{ captureMsg }}</p>
    </section>

    <!-- ②③④ 仅当有进近点 -->
    <template v-if="capture && capture.has_approach">
      <!-- ② 退到进近点 (向外, 近→远) -->
      <section class="tv-step">
        <div class="tv-head"><span class="tv-num">②</span><strong>退到进近点</strong></div>
        <p class="tv-hint">长按向外退出：依次经过进近点 近 → 远 (松手即停，限速直线走位)。</p>
        <p class="hint">长按运动仅支持鼠标/触控按住 (deadman, 松手即停)；键盘无替代路径，请使用指点设备操作。</p>
        <button
          class="tv-hold"
          :class="{ arming: armDir === 'out', moving: runDir === 'out' }"
          :disabled="disabled || !hasWaypoints || runDir === 'in' || armDir === 'in'"
          @pointerdown="pressSeq('out', $event)"
          @pointerup.prevent="releaseSeq"
          @pointercancel.prevent="releaseSeq"
          @lostpointercapture="releaseSeq"
        >
          {{ runDir === 'out' ? '退出中… 松手停止' : armDir === 'out' ? '继续按住…' : '按住退到进近点' }}
        </button>
      </section>

      <!-- ③ 二次进入复核 (向内, 远→近 → 示教点) -->
      <section class="tv-step">
        <div class="tv-head"><span class="tv-num">③</span><strong>二次进入复核</strong></div>
        <p class="tv-hint">长按向内进入：进近点 远 → 近 → 示教点 (松手即停)；完整到位后自动做回位漂移检查。</p>
        <div class="tv-row">
          <button
            class="tv-hold"
            :class="{ arming: armDir === 'in', moving: runDir === 'in' }"
            :disabled="disabled || !hasWaypoints || runDir === 'out' || armDir === 'out'"
            @pointerdown="pressSeq('in', $event)"
            @pointerup.prevent="releaseSeq"
            @pointercancel.prevent="releaseSeq"
            @lostpointercapture="releaseSeq"
          >
            {{ runDir === 'in' ? '进入中… 松手停止' : armDir === 'in' ? '继续按住…' : '按住二次进入复核' }}
          </button>
          <span v-if="seqStatus" class="tv-status" role="status">{{ seqStatus }}</span>
        </div>
        <p class="tv-hint">长按 {{ ARM_MS }}ms 触发，松手即停 (软停)。</p>
      </section>

      <!-- ④ 回位漂移检查 -->
      <section class="tv-step">
        <div class="tv-head"><span class="tv-num">④</span><strong>回位漂移检查</strong></div>
        <div class="tv-row">
          <button class="tv-btn" :disabled="disabled || busy || !!runDir || !!armDir" @click="runDrift">
            复核漂移
          </button>
          <span v-if="drift" class="tv-drift">
            drift_mm <b>{{ Number(drift.drift_mm).toFixed(4) }}</b> · drift_deg
            <b>{{ Number(drift.drift_deg).toFixed(4) }}</b>
          </span>
        </div>
        <p v-if="drift && drift.over" class="tv-warn" role="alert">回位漂移超阈，重复性存疑，请复核示教/机械</p>
        <p v-else-if="driftMsg" class="tv-msg" role="status">{{ driftMsg }}</p>
      </section>
    </template>

    <!-- 无进近点: 跳过 ②③④ -->
    <p v-else-if="capture" class="tv-hint tv-noapproach">此点无进近点，示教后可用上方长按运行验证。</p>

    <!-- ⑤ 提交 -->
    <section class="tv-step tv-last">
      <div class="tv-head"><span class="tv-num">⑤</span><strong>提交</strong></div>
      <div class="tv-row">
        <button class="tv-btn tv-primary" :disabled="!canCommit" @click="doCommit">确认无误 → 保存</button>
        <input v-model="note" class="tv-note" type="text" placeholder="备注 (可选)"
               aria-label="复核备注" :disabled="disabled" />
      </div>
      <p class="tv-hint">
        {{
          isGrid
            ? '网格库位：锚点→重解整架；非锚位→更新该库位偏置 (写回 meta.grids)'
            : '示教点：覆盖 robot_points.json 的 pose/joint'
        }}
      </p>
      <p v-if="commitMsg" class="tv-msg" role="status">{{ commitMsg }}</p>
    </section>
  </div>
</template>

<style scoped>
.tv {
  margin-top: 6px;
}
.tv-disabled {
  background: var(--warn-soft);
  border: 1px solid var(--warn);
  color: var(--warn-strong);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: var(--fs-12);
  margin-bottom: 10px;
}
.tv-step {
  padding: 10px 0;
  border-top: 1px dashed var(--border);
}
.tv-step:first-of-type {
  border-top: none;
  padding-top: 0;
}
.tv-last {
  border-top: 1px solid var(--border);
}
.tv-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  color: var(--subtle);
}
.tv-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--accent);
  color: var(--on-accent);
  font-size: var(--fs-12);
  font-weight: 700;
}
.tv-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin: 6px 0;
}
.tv-hint {
  color: var(--muted);
  font-size: var(--fs-12);
  margin: 4px 0;
}
.tv-noapproach {
  padding: 8px 10px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  background: var(--surface-2);
}
/* 次级按钮 (采集/漂移): 显式令牌化, 深色下不回退 UA 浅灰 */
.tv-btn {
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface-2);
  color: var(--text);
  font-weight: 600;
  cursor: pointer;
}
.tv-btn:hover:not(:disabled) {
  background: var(--hover);
  border-color: var(--accent);
  color: var(--accent);
}
.tv-btn:disabled {
  color: var(--muted);
  cursor: not-allowed;
}
.tv-primary {
  background: var(--accent-strong);
  color: var(--on-accent);
  border: none;
}
.tv-primary:hover:not(:disabled) {
  background: var(--accent-strong);
  color: var(--on-accent);
}
.tv-primary:disabled {
  opacity: 0.62;
  color: var(--on-accent);
}
/* 长按 deadman 按钮 (mirror run-block): arming=warn, moving=bad */
.tv-hold {
  padding: 10px 22px;
  font-size: var(--fs-14);
  font-weight: 700;
  color: var(--on-accent);
  background: var(--accent-strong);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  user-select: none;
  touch-action: none;
}
.tv-hold.arming {
  background: var(--warn);
}
.tv-hold.moving {
  background: var(--bad);
}
.tv-hold:disabled {
  opacity: 0.62;
  cursor: not-allowed;
}
.tv-status {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  color: var(--accent);
}
.tv-drift {
  font-size: var(--fs-12);
  color: var(--subtle);
}
.tv-drift b {
  font-family: var(--font-mono);
  color: var(--accent);
}
.tv-warn {
  background: var(--warn-soft);
  border: 1px solid var(--warn);
  color: var(--warn-strong);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: var(--fs-12);
  margin: 6px 0;
}
.tv-msg {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  margin: 6px 0;
  color: var(--subtle);
}
.tv-note {
  min-width: 200px;
  min-height: 28px;
  padding: 3px 8px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--field-bg);
  color: var(--text);
}
.tv-compare {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 12px;
  margin: 8px 0;
}
.tv-col strong {
  color: var(--subtle);
  font-size: var(--fs-12);
  text-transform: uppercase;
}
.tv-col dl {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 2px 8px;
  margin: 4px 0 0;
  font-size: var(--fs-12);
}
.tv-col dt {
  color: var(--subtle);
  font-weight: 600;
}
.tv-col dd {
  margin: 0;
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}
@media (max-width: 900px) {
  .tv-compare {
    grid-template-columns: 1fr;
  }
  .tv-note {
    min-width: 0;
    width: 100%;
  }
}
</style>
