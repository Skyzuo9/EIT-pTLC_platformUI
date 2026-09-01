<script setup>
// 板仓行程标定向导: 竖向分步引导 —— ①清空仓采空仓样本 → ②装已知张数逐组采样 → ③实测验证。
// 每次「运行并采样」由后端一次调用完成"发光电搜索动作 → 读轴位 → 记样本 → 重新拟合落盘",
// 不需要用户先去维护面板单发动作。与 TeachVerify.vue 同套 idiom (分步块 + busy + 分步消息)。
//
// ⚠ 采样与实测都会驱动 1Z/2Z 升降轴运动, 故每次点击先弹确认。运动本身受 PLC 有界 jog 保护
// (只在 SearchLow~SearchHigh 窗口内单向搜索, 前置不满足报 301/302, 到上界报 304/305),
// 故用普通确认即可, 不需要 TeachVerify 那套长按 deadman。
import { ref, computed } from 'vue'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'

const props = defineProps({
  magazine: { type: String, required: true },      // feed | waste
  state: { type: Object, default: null },          // GET /api/feedlift/calib 的该仓节
  ledgerCount: { type: Number, default: 0 },       // 账本当前记的张数 (实测后会被校正)
})
const emit = defineEmits(['changed'])

const busy = ref(false)
const note = ref('')
const err = ref('')
const plates = ref(null)          // 本次采样时仓内张数
const measured = ref(null)        // 「立即实测」的 probe 结果
const runId = ref('')             // 上一次运行的 run_id; 采样与实测都走 VM 编排, 有运行记录可查

const label = computed(() => props.state?.label || props.magazine)
const capacity = computed(() => props.state?.capacity ?? 0)
const samples = computed(() => props.state?.samples || [])
const fit = computed(() => props.state?.fit || null)
const calibrated = computed(() => !!props.state?.calibrated)
const searchAction = computed(() => props.state?.search_action || '')
const clearAction = computed(() => props.state?.clear_action || '')
// 一次测量实际发的两个动作: 清零(退到光电熄灭) → 逼近(搜到光电点亮)。
// 只发逼近是不行的 —— 它在光电已亮时原地确认即返回 DONE, 轴不动, 读到的是上次的陈旧位置。
const motionDesc = computed(
  () => `${clearAction.value} → ${searchAction.value}`)

// 每组样本的拟合残差 (mm); fit.residuals 与 samples 同序, 定不出直线时为空
function residualOf(i) {
  const rs = fit.value?.residuals || []
  return i < rs.length ? rs[i] : null
}

// 残差是否有解释力: 少于 3 组时两点必然共线, 残差恒为 0, 那个 0 不代表准
const residualInformative = computed(
  () => !!fit.value?.ok && fit.value.residual_rms_mm !== null)

// 旧版两步标定留下的 z_empty (无采样记录), 说不清是怎么来的, 如实标注
const legacyCalib = computed(
  () => !samples.value.length && !!props.state && props.state.z_empty_mm !== 0)

async function run(fn) {
  if (busy.value) return
  busy.value = true
  err.value = ''
  try {
    await fn()
    emit('changed')
  } catch (e) {
    err.value = errText(e)
  } finally {
    busy.value = false
  }
}

async function takeSample() {
  const n = Number(plates.value)
  if (!Number.isFinite(n) || n < 0 || n > capacity.value) {
    err.value = `请先填写此刻仓内实际张数 (1~${capacity.value})。这个数必须准确 —— 节距精度直接由它决定`
    return
  }
  // 空仓组挡在这里而不是等 PLC 报 301/302: 仓底接近开关是有无板检测, 空仓时清零动作的
  // 物料互锁不成立。而这一组本来就不必采 —— 空仓基准位是拟合截距, 由非零张数外推得出。
  if (n === 0) {
    err.value = '空仓这一组采不了: 仓底接近开关检测不到板, PLC 的清零动作会因物料互锁超时 (301/302)。'
      + '也不需要采 —— 空仓基准位是拟合直线的截距, 由不同的非零张数 (如 10/20/30) 外推得出'
    return
  }
  if (!(await confirmAction({
    title: '运行并采样',
    message: [
      `即将执行 ${motionDesc.value}, 驱动${label.value}升降轴`,
      '先向下退到光电熄灭, 再向上搜到光电点亮。',
      `请确认: 仓内确为 ${Math.round(n)} 张, 且升降区无人无障碍。`,
    ],
    level: 'danger',
    confirmText: '运行并采样',
  }))) return
  note.value = ''
  measured.value = null
  runId.value = ''
  return run(async () => {
    const r = await api.calibFeedliftSample(props.magazine, Math.round(n))
    runId.value = r.run_id || ''
    note.value = r.reject_reason
      ? `已记第 ${r.samples.length} 组 (${r.sampled.plates} 张 → ${r.sampled.z_mm} mm), 但${r.reject_reason}`
      : `已记第 ${r.samples.length} 组: ${r.sampled.plates} 张 → ${r.sampled.z_mm} mm`
  })
}

async function clearSamples() {
  if (!(await confirmAction({
    title: '清空重标',
    message: `将清空${label.value}的全部采样并把标定归零, 需要重新走一遍标定。`,
    level: 'danger',
    confirmText: '清空重标',
  }))) return
  note.value = ''
  measured.value = null
  return run(async () => {
    await api.clearFeedliftSamples(props.magazine)
    note.value = '采样与标定已清空'
  })
}

async function measure() {
  if (!(await confirmAction({
    title: '立即实测板数',
    message: [
      `即将执行 ${motionDesc.value} + 板数实测, 驱动${label.value}升降轴运动。`,
      '请确认升降区无人无障碍。实测结果会直接校正账本。',
    ],
    level: 'danger',
    confirmText: '实测',
  }))) return
  note.value = ''
  runId.value = ''
  return run(async () => {
    const before = props.ledgerCount
    const r = await api.measureFeedlift(props.magazine)
    measured.value = r
    runId.value = r.run_id || ''
    note.value = r.count === before
      ? `实测 ${r.count} 张, 与账本一致`
      : `实测 ${r.count} 张; 账本已由 ${before} 校正为 ${r.count}`
  })
}
</script>

<template>
  <div class="fw">
    <div class="fw-head">
      <strong>{{ label }} 行程标定</strong>
      <span v-if="calibrated" class="fw-ok">
        已标定 · 节距 {{ state.pitch_mm }} mm · 空仓位 {{ state.z_empty_mm }} mm
        <template v-if="residualInformative">
          · 残差 ±{{ fit.residual_rms_plates }} 张
        </template>
      </span>
      <span v-else class="fw-bad">未标定 —— 实测校正不生效</span>
      <button class="mini" :disabled="busy || !samples.length" @click="clearSamples">清空重标</button>
    </div>

    <p class="fw-warn">
      ⚠ 下面每个按钮都会<b>驱动 {{ magazine === 'feed' ? '1Z' : '2Z' }} 升降轴运动</b>:
      先 <code>{{ clearAction }}</code> 向下退到光电熄灭, 再 <code>{{ searchAction }}</code>
      向上搜到光电点亮。点击前确认升降区无人无障碍。
    </p>
    <p class="fw-warn">
      必须这样两步的原因: 逼近动作在光电已点亮时会原地确认即返回完成、轴一步不动,
      单发它只会读到上次停轴的<b>陈旧位置</b> —— 加了板也测不出变化。
    </p>
    <p v-if="legacyCalib" class="fw-warn">
      当前空仓位 {{ state.z_empty_mm }} mm 来自旧版两步标定, <b>没有采样记录</b>,
      无从核对它是怎么来的 —— 重新采样会覆盖它。
    </p>

    <ol class="fw-steps">
      <li>
        <b>装入已知张数</b>, 每换一个张数采一组。<b>建议 3 组以上</b> (如 10 / 20 / 30):
        两点必然共线, 残差恒为 0 而没有信息; 3 组起残差才是光电触发重复性的实测值,
        也才能看出堆叠有没有非线性 (被压实 / 有间隙)。
      </li>
      <li>
        <b>不要采空仓那一组</b> —— 仓底接近开关是有无板检测, 空仓时清零动作的物料互锁
        不成立, 必然报 301/302。<b>也不需要</b>: 空仓基准位是拟合直线的<b>截距</b>,
        由上面这些非零张数外推即可得出。
      </li>
    </ol>

    <div class="fw-row">
      <label :for="`fw-plates-${magazine}`">此刻仓内张数</label>
      <input :id="`fw-plates-${magazine}`" class="num" type="number" inputmode="numeric"
             min="1" :max="capacity" :disabled="busy"
             placeholder="如 10 / 20 / 30" v-model="plates" />
      <button class="mini" :disabled="busy" @click="takeSample">运行并采样</button>
    </div>

    <table v-if="samples.length" class="mat-tab fw-tab">
      <thead>
        <tr><th>#</th><th>张数</th><th>实测位置 (mm)</th><th>拟合残差 (mm)</th></tr>
      </thead>
      <tbody>
        <tr v-for="(s, i) in samples" :key="i">
          <td class="muted">{{ i + 1 }}</td>
          <td>{{ s.plates }}</td>
          <td class="mono">{{ s.z_mm }}</td>
          <td class="mono muted">{{ residualOf(i) === null ? '—' : residualOf(i) }}</td>
        </tr>
      </tbody>
    </table>

    <p v-if="fit" class="fw-fit" :class="{ bad: !fit.ok }">
      <template v-if="fit.ok">
        拟合 ({{ fit.n }} 组): 节距 <b>{{ fit.pitch_mm }} mm</b> · 空仓位 {{ fit.z_empty_mm }} mm
        <template v-if="residualInformative">
          · 残差 RMS {{ fit.residual_rms_mm }} mm (<b>±{{ fit.residual_rms_plates }} 张</b>)
        </template>
        <br v-if="fit.reason" /><i v-if="fit.reason" class="fw-bad">{{ fit.reason }}</i>
      </template>
      <template v-else>{{ fit.reason }}</template>
    </p>

    <div class="fw-row">
      <span class="row-lab">验证 / 日常盘点</span>
      <button class="mini" :disabled="busy || !calibrated" @click="measure">立即实测现在有几张</button>
      <span v-if="!calibrated" class="muted">(需先完成标定)</span>
      <span v-if="measured" class="fw-measured">
        实测 <b>{{ measured.count }}</b> 张 (残差 {{ measured.residual }} 张)
      </span>
    </div>

    <p v-if="note" class="fw-note" role="status">{{ note }}</p>
    <p v-if="err" class="fw-bad" role="status">{{ err }}</p>
    <!-- 采样与实测都走 VM 编排 (feedlift_calib_sample / feedlift_measure_count), 每次都有
         运行记录: 点进去能逐步看到自检/清零/逼近/记样各走到哪、耗时多少、失败卡在哪一步 -->
    <p v-if="runId" class="fw-note">
      <RouterLink :to="`/runs/${runId}`">查看这次运行的逐步记录 ({{ runId }})</RouterLink>
    </p>
  </div>
</template>

<style scoped>
.fw { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-top: 10px; }
.fw-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: var(--fs-13); }
.fw-ok { color: var(--ok, #2a7); font-size: var(--fs-12); }
.fw-bad { color: var(--warn-strong); font-size: var(--fs-12); }
.fw-warn { font-size: var(--fs-12); color: var(--warn-strong); margin: 6px 0 0; }
.fw-steps { font-size: var(--fs-12); color: var(--muted); margin: 6px 0; padding-left: 20px; line-height: 1.6; }
.fw-row { display: flex; align-items: center; gap: 6px; margin-top: 8px; font-size: var(--fs-12); flex-wrap: wrap; }
.fw-row label, .fw-row .row-lab { color: var(--subtle); font-weight: 600; }
.fw-tab { margin-top: 8px; }
/* .mat-tab/.mono 原是 MaterialView 的 scoped 类, 对本组件不生效 (跨组件死类) ——
   把等价规则补进本组件 scoped, 表格边框/表头底色与数字等宽才真正落地 */
.mat-tab { border-collapse: collapse; font-size: var(--fs-12); }
.mat-tab th, .mat-tab td { border: 1px solid var(--border); padding: 3px 6px; text-align: center; }
.mat-tab th { background: var(--surface-2); color: var(--subtle); font-weight: 600; }
.mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.fw-fit { font-size: var(--fs-12); color: var(--text); margin: 8px 0 0; }
.fw-fit.bad { color: var(--warn-strong); }
.fw-note { font-size: var(--fs-12); color: var(--accent); margin: 6px 0 0; }
.fw-measured { color: var(--accent); }
</style>
