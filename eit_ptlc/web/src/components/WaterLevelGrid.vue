<script setup>
// 液位 8 路网格总览: 每路一格单帧缩略 (400ms 轮询 /frame 原图) + 液位/标定/状态读数; 点击进单路调试。
// 注: 用低频单帧轮询而非持久 MJPEG 流 —— 8 路持久流会撑满浏览器单主机连接上限致画面定格。
//     /frame 只需通道已 CAPTURE (set_active_channels 激活), 不需 stream_start 生命周期。
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { wlFrameUrl } from '../api'
import { useFramePoll } from '../composables/framePoll'
import { wlReasonLabel } from '../wlStatus'

const props = defineProps({
  snapshot: { type: Object, required: true },
})
const router = useRouter()
const CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]

// 网格用低频单帧轮询(/frame, 瞬时连接)而非 8 路持久 MJPEG 流: 后者会撑满浏览器单主机连接上限(~6)
// 致画面连上即定格不再刷新, 8 路持久流也压垮香橙派。连续实时流留给单路视图。
// useFramePoll 只在取帧成功时换 src: 瞬断/上游 503 不再让该格黑闪一拍, 画面保持最后一帧,
// 中断只进 console/宿主日志; 持续中断亮"中断"角标 (失败自带退避, 离线时不高频打代理)。
// 轮询周期: 640×480 监控档下香橙派/网络负担轻, 从早期 1s 提到 400ms(≈2.5fps)让总览更跟手; 要更快改小即可。
const GRID_POLL_MS = 400
const pollers = Object.fromEntries(CHANNELS.map((ch) => [
  ch, useFramePoll(() => wlFrameUrl('ch' + ch), GRID_POLL_MS, `CH${ch}(网格)`),
]))
onMounted(() => {
  CHANNELS.forEach((ch) => pollers[ch].start())
})

const cells = computed(() =>
  CHANNELS.map((ch) => {
    const d = props.snapshot.channels?.[ch] || null
    return {
      ch,
      data: d,
      src: pollers[ch].state.src,
      stale: pollers[ch].state.stale,
      // front_percent = 溶剂前沿到达 ROI 百分比 (上位机拉帧检测; valid=false 时为空)
      percent: d && d.front_percent != null ? Number(d.front_percent).toFixed(1) : null,
      calibrated: !!(d && d.calibrated),
      status: d
        ? (d.valid
            ? (d.has_ref ? '检测中' : '检测中 (无参考)')
            : d.reachable ? wlReasonLabel(d.reason) : '不可达')
        : null,
    }
  }),
)

function open(ch) { router.push(`/water_level/${ch}`) }
</script>

<template>
  <div class="grid">
    <!-- 整卡即按钮 (btn-bare 复位 UA 样式): 键盘/读屏白得原 div@click 没有的激活语义 -->
    <button v-for="c in cells" :key="c.ch" type="button" class="btn-bare cell"
            :aria-label="`CH${c.ch} 液位单元, 打开单路调试`" @click="open(c.ch)">
      <div class="cell-head">
        <strong>CH{{ c.ch }}</strong>
        <span class="badge" :class="{ ok: c.calibrated }">{{ c.calibrated ? '已标定' : '未标定' }}</span>
        <span class="h">{{ c.percent != null ? c.percent + ' %' : '—.— %' }}</span>
      </div>
      <div class="cell-img">
        <img v-if="c.src" :src="c.src" :alt="'CH' + c.ch" />
        <div v-else class="noimg">{{ snapshot.online ? '无画面' : '设备离线' }}</div>
        <span v-if="c.src && c.stale" class="stale">中断</span>
      </div>
      <div class="cell-foot"><small>{{ c.status || '无数据' }}</small></div>
    </button>
  </div>
</template>

<style scoped>
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
/* display/width 盖掉 .btn-bare 的 inline-flex (否则三段子块被排成一行), 余样式与原 div 版一致 */
.cell { display: block; width: 100%; text-align: left; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; cursor: pointer; background: var(--panel); }
.cell:hover { border-color: var(--accent); }
.cell-head { display: flex; gap: 8px; align-items: center; padding: 6px 8px; }
.cell-head .h { margin-left: auto; font-family: var(--font-mono); color: var(--accent); }
.badge { font-size: var(--fs-11); padding: 1px 6px; border-radius: 8px; background: var(--chip-bg); color: var(--subtle); font-weight: 600; }
.badge.ok { background: var(--ok-soft); color: var(--ok-strong); }
/* 图像占位区: 近黑底 + 浅灰占位字, 深浅主题下均为暗底, 故保留字面量 (主题无关) */
/* 4:3 锁定自 config/app.yaml camera.cap_width/height=640×480; 后端提 1280×720 时同步改 */
.cell-img { aspect-ratio: 4 / 3; background: #0b0f14; color: #cbd5e1; display: flex; align-items: center; justify-content: center; position: relative; }
.cell-img img { width: 100%; height: 100%; object-fit: contain; }
/* 取帧持续中断角标: 保持最后一帧 + 叠提示, 不黑屏 */
.cell-img .stale { position: absolute; top: 4px; left: 4px; font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 7px; background: rgba(220, 38, 38, .85); color: #fff; }
.noimg { color: #cbd5e1; font-size: var(--fs-13); }
.cell-foot { padding: 4px 8px; color: var(--muted); font-weight: 500; }
</style>
