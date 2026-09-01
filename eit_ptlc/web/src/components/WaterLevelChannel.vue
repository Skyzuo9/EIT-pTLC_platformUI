<script setup>
// 液位单路调试 (中区右半): 视频 (实时/标定/识别三态) + 读数 + 检测参数调参 + 设备命令。
// 实时 = 原始帧低频单帧轮询 /frame (与网格总览同机制, 无持久 MJPEG 长连接), 画面流畅但看不出识别;
// 识别 = 上位机渲染的叠加图 (ROI 框/湿区掩膜/前沿线) + 走势曲线 + 健康数值, 随检测周期 ~2s 更新。
// 命令走 api.wlCmd。进入即 stream_start(仅作查看软 pin 保相机在采, 与页签无关), 离开 stream_stop。
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { api, errText, wlFrameUrl } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useFramePoll } from '../composables/framePoll'
import { usePoll } from '../composables/usePoll.js'
import { useRovingTabs } from '../composables/useRovingTabs.js'
import { wlReasonLabel } from '../wlStatus'
import Splitter from './Splitter.vue'
import WaterLevelCalibrate from './WaterLevelCalibrate.vue'
import WaterLevelDetect from './WaterLevelDetect.vue'
import { useLayoutStore } from '../stores/layout'

const layout = useLayoutStore()

const props = defineProps({
  channel: { type: Number, required: true },
  chData: { type: Object, default: null },
  params: { type: Object, default: null },
  online: { type: Boolean, default: false },
})

// 检测参数定义 (镜像上位机 WaterLevelDetectParams; 检测已搬到上位机, 前沿线法)
const PARAM_DEFS = [
  { key: 'flow_direction', label: '流动方向', type: 'enum', options: ['left_to_right', 'right_to_left', 'bottom_to_top'] },
  { key: 'roi_crop_x', label: 'ROI 横裁剪', type: 'range', min: 0, max: 0.4, step: 0.01 },
  { key: 'roi_crop_y', label: 'ROI 纵裁剪', type: 'range', min: 0, max: 0.4, step: 0.01 },
  { key: 'blur_ksize', label: '模糊核', type: 'enum', options: [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21] },
  // 判湿线 = 本值 × 湿平台幅值 A (相对量, 非绝对灰度差): 0.5 = 半幅穿越。
  // 相对化使前沿位置不随 A (随板/展开剂/照明在 0.07~0.10 浮动) 漂移。
  { key: 'front_ratio_level', label: '前沿判定比例 (占湿平台幅值 A)', type: 'range', min: 0.1, max: 0.9, step: 0.05 },
  { key: 'trigger_percent_t2', label: 'T2触发阈值 (front%)', type: 'range', min: 1, max: 100, step: 0.5 },
  { key: 't1_offset', label: 'T1提前量 (T2−offset)', type: 'range', min: 0, max: 50, step: 0.5 },
]

const mode = ref('live') // live | calibrate | detect
const msg = ref('')
const form = reactive({})

// 单通道录制 (Phase 0 手动): 服务端录制, 与视图解耦 —— 离开本通道不停录, 重进按 record_status 复位。
// 帧源 = /frame/chN, 需通道在取流; 录制期间请保持本通道视图开启以维持取流 (Phase 0 限制)。
const recSampleId = ref('')
const recording = ref(false)
const recInfo = reactive({ frame_count: 0, elapsed_s: 0, path: '' })

// 视频源: 单路实时 = 低频单帧轮询 /frame (与网格总览同机制, 无持久 MJPEG 长连接)。
// useFramePoll 只在取帧成功时换 src: 瞬断/上游 503 不再把 <img> 打进破图态黑闪一拍,
// 画面保持最后一帧, 中断只进 console/宿主日志; 持续中断亮 stale 角标。
const CH_POLL_MS = 100          // 10fps: 比网格(2.5fps)顺, 对慢速液位/标定够用, 单路负载轻(可调)
const { state: frame, start: startPoll, stop: stopPoll } = useFramePoll(
  () => wlFrameUrl('ch' + props.channel), CH_POLL_MS, `CH${props.channel}`)

// 读数
const readout = computed(() => {
  const d = props.chData || {}
  return [
    ['前沿位置', d.front_percent != null ? Number(d.front_percent).toFixed(1) + ' %' : '—'],
    ['信号', d.valid ? '有效' : wlReasonLabel(d.reason)],
    ['已标定', d.calibrated ? '是' : '否'],
    ['参考图', d.has_ref ? '已采' : '未采'],
    ['可达', d.reachable ? '是' : '否'],
    ['流向', d.flow_direction || '—'],
  ]
})

// 切页签: 实时 → 开原始帧轮询; 标定/识别 → 停本轮询 (两者各自管自己的取帧, 见对应组件),
// 否则会与子组件的轮询叠加, 白占一条代理连接。
function setMode(m) {
  mode.value = m
  if (m === 'live') startPoll()
  else stopPoll()
}
// 键盘巡航走 onChange=setMode: 保留轮询启停副作用 (直写 mode 会让视频轮询卡在错误档)
const modeRoving = useRovingTabs(['live', 'calibrate', 'detect'], mode, { onChange: setMode })

// 参数: 从上位机检测服务读取填充表单 (get_detect_param 返回 {params}); 用户改动后不覆盖
const dirty = ref(false)
function fillParams(p) {
  if (!p || dirty.value) return
  for (const def of PARAM_DEFS) if (p[def.key] != null) form[def.key] = p[def.key]
}
async function fetchParams(resetDirty = false) {
  if (resetDirty) dirty.value = false
  const r = await api.wlCmd('get_detect_param', { channel: props.channel })
  fillParams(r?.params)
}

let sendTimer = null
function onParamChange(def) {
  dirty.value = true
  const raw = form[def.key]
  const value = def.type === 'range' ? Number(raw) : (typeof def.options[0] === 'number' ? Number(raw) : raw)
  form[def.key] = value
  if (sendTimer) window.clearTimeout(sendTimer)
  sendTimer = window.setTimeout(async () => {
    await cmd('set_detect_param', { channel: props.channel, params: { [def.key]: value } }, `参数 ${def.label} 已下发`)
  }, 250)
}

async function cmd(name, payload, okMsg) {
  msg.value = ''
  try {
    await api.wlCmd(name, payload)
    msg.value = okMsg || `${name} 已下发 ✓`
  } catch (e) {
    msg.value = `${name} 失败: ` + errText(e)
  }
}

// ---- 操作钮 (useAsyncAction): 每钮独立 busy 在途去重防连发, 失败写回现有消息位 msg 并读屏播报 ----
function cmdAction(name, okMsg) {
  return useAsyncAction(async () => {
    msg.value = ''
    await api.wlCmd(name, { channel: props.channel })
    msg.value = okMsg
  }, { errorPrefix: `${name} 失败`, onError: (m) => { msg.value = m } })
}
const readParams = useAsyncAction(() => fetchParams(false),
  { errorPrefix: '读取参数失败', onError: (m) => { msg.value = m } })
const loadSavedParams = useAsyncAction(() => fetchParams(true),
  { errorPrefix: '从配置加载失败', onError: (m) => { msg.value = m } })
const saveParams = cmdAction('save_detect_param', '已保存到配置')
const captureRef = cmdAction('capture_reference', '已采集参考干板图')
const reloadCfg = cmdAction('reload_config', '已重载配置')
const startStream = cmdAction('stream_start', '已开流')
const stopStream = cmdAction('stream_stop', '已停流')
const restartCam = cmdAction('restart_camera', '已请求重启摄像头')

// 重启摄像头/停流会掐断检测帧源: danger 级确认后再执行 (急停类零确认原则不适用于此二者)
async function askRestartCamera() {
  if (restartCam.busy) return
  if (!(await confirmAction({
    level: 'danger', title: '重启摄像头',
    message: '会中断正在运行的液位检测。', confirmText: '重启',
  }))) return
  restartCam.run()
}
async function askStopStream() {
  if (stopStream.busy) return
  if (!(await confirmAction({
    level: 'danger', title: '停止视频流',
    message: '会中断正在运行的液位检测。', confirmText: '停流',
  }))) return
  stopStream.run()
}

// ---- 单通道录制 ----
async function pollRecStatus() {
  try {
    const r = await api.wlCmd('record_status', {})
    const mine = (r?.recordings || []).find(x => x.channel === props.channel)
    if (mine) {
      recording.value = true
      recInfo.frame_count = mine.frame_count
      recInfo.elapsed_s = Math.round(mine.elapsed_s || 0)
      recInfo.path = mine.path
    } else {
      recording.value = false
    }
  } catch (e) { /* 离线/未就绪: 忽略 */ }
}
// 仅录制中在表 (enabled 门): recording 翻转自动启停; 服务端外停也由拍内 recording=false 收敛停表
const recPoll = usePoll(pollRecStatus, 1000, { enabled: computed(() => recording.value) })
async function startRecord() {
  msg.value = ''
  try {
    const r = await api.wlCmd('record_start', { channel: props.channel, sample_id: recSampleId.value || undefined })
    recording.value = true
    recInfo.frame_count = 0
    recInfo.elapsed_s = 0
    recInfo.path = r?.path || ''
    msg.value = '录制已开始 ● ' + (r?.path || '')
  } catch (e) {
    msg.value = '录制启动失败: ' + errText(e)
  }
}
async function stopRecord() {
  msg.value = ''
  try {
    const r = await api.wlCmd('record_stop', { channel: props.channel })
    recording.value = false
    const s = r?.summary || {}
    msg.value = s.stopped ? `录制已停止: ${s.frame_count} 帧 / ${s.duration_s}s → ${s.path}` : '未在录制'
  } catch (e) {
    msg.value = '录制停止失败: ' + errText(e)
  }
}

onMounted(async () => {
  if (props.online) {
    // stream_start 在此仅作"查看软 pin"(ensure_active): 保 max_active 下本通道相机在采, 供 /frame
    // 轮询取帧; 不再连持久 /stream 流。
    cmd('stream_start', { channel: props.channel }, '已请求视频流')
  }
  // 轮询不因离线不启: 失败自带退避, 设备上线后画面自动跟上 (离线期间保持最后一帧/占位)
  if (mode.value === 'live') startPoll()
  fetchParams().catch(() => { /* 离线/未就绪: 挂载静默尝试, 不报错 */ })
  recPoll.start()                // 意图常开; 是否实际在表由 enabled(recording) 门决定
  await recPoll.tick()           // 复位单拍: 本通道若已在录 (导航前开的), 重新贴上并自动续表
})
onBeforeUnmount(() => {
  if (sendTimer) window.clearTimeout(sendTimer)
  stopPoll()
  // 录制中则不停流(不解 pin)—— 服务端录制与视图解耦, release_pin 会掐断相机帧源
  if (!recording.value) api.wlCmd('stream_stop', { channel: props.channel }).catch(() => {})
})
</script>

<template>
  <div class="ch" :style="{ '--wl-param-w': layout.sizes.wlParamW + 'px' }">
    <!-- 左: 视频 + 读数 -->
    <div class="ch-left">
      <div class="vid-tabs" role="tablist" aria-label="液位通道视图页签">
        <button type="button" role="tab" :id="`wlc-tab-live-${channel}`" :aria-controls="`wlc-panel-${channel}`"
          :tabindex="modeRoving.tabindex('live')" :aria-selected="mode === 'live'"
          :class="{ active: mode === 'live' }" @click="setMode('live')" @keydown="modeRoving.onKeydown">实时</button>
        <button type="button" role="tab" :id="`wlc-tab-calibrate-${channel}`" :aria-controls="`wlc-panel-${channel}`"
          :tabindex="modeRoving.tabindex('calibrate')" :aria-selected="mode === 'calibrate'"
          :class="{ active: mode === 'calibrate' }" @click="setMode('calibrate')" @keydown="modeRoving.onKeydown">标定</button>
        <button type="button" role="tab" :id="`wlc-tab-detect-${channel}`" :aria-controls="`wlc-panel-${channel}`"
          :tabindex="modeRoving.tabindex('detect')" :aria-selected="mode === 'detect'"
          :class="{ active: mode === 'detect' }" @click="setMode('detect')" @keydown="modeRoving.onKeydown">识别</button>
      </div>
      <!-- 单面板承载三态内容: tabpanel 共用一个 id, aria-labelledby 绑当前活动 tab -->
      <div :id="`wlc-panel-${channel}`" role="tabpanel" :aria-labelledby="`wlc-tab-${mode}-${channel}`">
      <!-- 识别页自带图像井/曲线/数值, 不套外层 .vid 与读数表 (那两者是实时/标定共用的) -->
      <WaterLevelDetect v-if="mode === 'detect'" :channel="channel" :ch-data="chData"
                        :params="form" :online="online" />
      <template v-else>
        <!-- 实时才用固定 4:3 视频井; 标定自管尺寸 (画布占满左栏, 控件 Teleport 到右栏锚点) -->
        <div v-if="mode === 'live'" class="vid">
          <img v-if="frame.src" :src="frame.src" :alt="'CH' + channel" />
          <div v-else class="noimg">{{ online ? '等待视频…' : '设备离线 — 无视频' }}</div>
          <span v-if="frame.src && frame.stale" class="vid-stale">信号中断 · 保持最后画面</span>
        </div>
        <WaterLevelCalibrate v-else :channel="channel" :online="online" />
        <table class="readout">
          <tbody><tr v-for="[k, v] in readout" :key="k"><th>{{ k }}</th><td>{{ v }}</td></tr></tbody>
        </table>
      </template>
      </div><!-- /tabpanel -->
    </div>

    <!-- 右: 标定锚点 + 调参 + ROI + 命令 -->
    <div class="ch-right">
      <!-- 标定控件锚点: WaterLevelCalibrate 的控制面板 Teleport 至此 (常驻空 div 避免目标时序问题)。
           置于右栏顶部: 标定页签下焦点序变为「左栏画布→右栏标定控件→检测参数」,
           修原"画布→检测参数→标定控件"的 Tab 序三段跳 (视觉位置随之上移, 有意为之) -->
      <div id="wl-calib-panel" v-show="mode === 'calibrate'"></div>

      <div class="sect-head" :class="{ 'flush-top': mode !== 'calibrate' }">检测参数
        <button class="mini" :disabled="readParams.busy" :aria-busy="readParams.busy"
                @click="readParams.run()">{{ readParams.busy ? '读取中…' : '读取' }}</button>
        <button class="mini" :disabled="saveParams.busy" :aria-busy="saveParams.busy"
                @click="saveParams.run()">{{ saveParams.busy ? '保存中…' : '保存到配置' }}</button>
        <button class="mini" :disabled="loadSavedParams.busy" :aria-busy="loadSavedParams.busy"
                @click="loadSavedParams.run()">{{ loadSavedParams.busy ? '加载中…' : '从配置加载' }}</button>
      </div>
      <!-- label for/id 显式关联 (布局是 grid 三列, 包裹会破格): range 与 select 共用同一名 -->
      <div v-for="def in PARAM_DEFS" :key="def.key" class="prow">
        <label :for="`wlp-${channel}-${def.key}`">{{ def.label }}</label>
        <template v-if="def.type === 'range'">
          <input :id="`wlp-${channel}-${def.key}`" type="range" :min="def.min" :max="def.max" :step="def.step"
                 v-model="form[def.key]"
                 :aria-valuetext="String(form[def.key] != null ? form[def.key] : '—')"
                 @input="onParamChange(def)" />
          <span class="pv">{{ form[def.key] != null ? form[def.key] : '—' }}</span>
        </template>
        <select v-else :id="`wlp-${channel}-${def.key}`" v-model="form[def.key]" @change="onParamChange(def)">
          <option v-for="o in def.options" :key="o" :value="o">{{ o }}</option>
        </select>
      </div>

      <div class="sect-head">设备命令</div>
      <div class="btn-row">
        <button :disabled="captureRef.busy" :aria-busy="captureRef.busy"
                @click="captureRef.run()">{{ captureRef.busy ? '采集中…' : '采集参考图' }}</button>
        <button :disabled="restartCam.busy" :aria-busy="restartCam.busy"
                @click="askRestartCamera">{{ restartCam.busy ? '重启中…' : '重启摄像头' }}</button>
        <button :disabled="reloadCfg.busy" :aria-busy="reloadCfg.busy"
                @click="reloadCfg.run()">{{ reloadCfg.busy ? '重载中…' : '重载配置' }}</button>
      </div>
      <div class="btn-row">
        <button :disabled="startStream.busy" :aria-busy="startStream.busy"
                @click="startStream.run()">{{ startStream.busy ? '开流中…' : '开流' }}</button>
        <button :disabled="stopStream.busy" :aria-busy="stopStream.busy"
                @click="askStopStream">{{ stopStream.busy ? '停流中…' : '停流' }}</button>
      </div>

      <div class="sect-head">单通道录制 (原始, 可回放)</div>
      <div class="rec-row">
        <input v-model="recSampleId" placeholder="sample_id (可选)" aria-label="录制样本 ID"
               spellcheck="false" :disabled="recording" />
        <button v-if="!recording" class="rec-btn" :disabled="!online" @click="startRecord">● 录制</button>
        <button v-else class="rec-btn recording" @click="stopRecord">■ 停止</button>
        <span v-if="recording" class="rec-live">● {{ recInfo.frame_count }} 帧 / {{ recInfo.elapsed_s }}s</span>
      </div>

      <p v-if="msg" class="msg">{{ msg }}</p>
      <p class="muted">检测在上位机 (拉帧 + 前沿线法)。ROI/参数即时写入上位机标定真源并持久化；「采集参考图」拍干板作干湿差分基线。</p>
    </div>
    <!-- 视频↔参数 竖向 (参数在右 → sign=-1) -->
    <Splitter skey="wlParamW" dir="x" :sign="-1" class="seam-wl-v" />
  </div>
</template>

<style scoped>
.ch { display: grid; grid-template-columns: minmax(360px, 1fr) var(--wl-param-w, 360px); gap: 16px; }
/* 视频↔参数 分隔条: 落进 16px 间隙 (子组件根节点受父级 scoped 影响, 故此类可命中 Splitter) */
.seam-wl-v { grid-column: 2; justify-self: start; align-self: stretch; width: 16px; margin-left: -16px; }
/* 页签: 下划线式, 与全局 .dock-tab (style.css) 同款规则 */
.vid-tabs { display: flex; gap: 2px; margin-bottom: 6px; border-bottom: 1px solid var(--border-soft); }
.vid-tabs button { padding: 4px 10px 5px; border: none; background: transparent; color: var(--subtle); cursor: pointer;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0; font-weight: 600;
  transition: background-color var(--transition-fast), color var(--transition-fast), box-shadow var(--transition-fast); }
.vid-tabs button:hover { color: var(--text); background: var(--hover); }
.vid-tabs button.active { color: var(--accent); box-shadow: inset 0 -2px 0 var(--accent); }
/* 4:3 锁定自 config/app.yaml camera.cap_width/height=640×480; 后端提 1280×720 时同步改 */
.vid { background: #0b0f14; aspect-ratio: 4 / 3; display: flex; align-items: center; justify-content: center; border-radius: 6px; position: relative; }
.vid img { width: 100%; height: 100%; object-fit: contain; }
.noimg { color: #cbd5e1; }
/* 取帧持续中断角标: 画面保持最后一帧, 只叠提示不黑屏 (暗底视频区, 主题无关字面量) */
.vid-stale { position: absolute; top: 6px; left: 6px; font-size: var(--fs-11); font-weight: 600; padding: 2px 8px; border-radius: 8px; background: rgba(220, 38, 38, .85); color: #fff; }
.readout { border-collapse: collapse; margin-top: 10px; }
.readout th { text-align: right; padding: 2px 12px 2px 0; color: var(--subtle); font-weight: 600; white-space: nowrap; }
.readout td { padding: 2px 0; font-family: var(--font-mono); }
.sect-head { font-weight: 600; margin: 12px 0 6px; border-top: 1px solid var(--border); padding-top: 10px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
/* 锚点 div 常驻右栏首位 → :first-child 不再命中「检测参数」头; 改由 flush-top 类
   (仅锚点隐藏时挂上) 免顶边框, 标定页签下则保留边框分隔标定控件与参数区 */
.sect-head.flush-top { border-top: none; padding-top: 0; }
.prow { display: grid; grid-template-columns: 96px 1fr 56px; gap: 8px; align-items: center; margin-bottom: 4px; }
.prow label { color: var(--subtle); font-size: var(--fs-12); font-weight: 600; }
.prow input[type=range] { width: 100%; }
.prow select { grid-column: 2 / 4; }
.pv { font-family: var(--font-mono); font-size: var(--fs-12); text-align: right; }
.btn-row { display: flex; gap: 6px; flex-wrap: wrap; margin: 8px 0; }
.btn-row button, .sect-head .mini { padding: 4px 10px; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; border-radius: var(--radius-sm); }
.mini { font-size: var(--fs-12); }
.rec-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
.rec-row input { flex: 1; min-width: 120px; padding: 3px 6px; }
.rec-btn { padding: 4px 12px; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; border-radius: var(--radius-sm); font-weight: 600; }
.rec-btn:disabled { opacity: .5; cursor: not-allowed; }
.rec-btn.recording { background: var(--bad); color: var(--on-accent); border-color: var(--bad); }
.rec-live { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--bad); font-weight: 600; }
.msg { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); }
.muted { color: var(--muted); font-size: var(--fs-12); margin-top: 8px; }
</style>
