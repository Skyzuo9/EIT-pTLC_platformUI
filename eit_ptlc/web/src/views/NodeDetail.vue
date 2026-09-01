<script setup>
// 设备节点详情 (中区): 实时快照; 机器人额外渲染点动操作台 (RobotJogPanel); PLC 工位额外提供 L2 复位
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useNodesStore } from '../stores/nodes'
import { useSystemStore } from '../store'
import { api } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { fmtValue } from '../utils/format'
import { healthText } from '../utils/deviceLabels.js'
import RobotJogPanel from '../components/RobotJogPanel.vue'
import StationManualPanel from '../components/StationManualPanel.vue'
import DeviceParamsPanel from '../components/DeviceParamsPanel.vue'
import Splitter from '../components/Splitter.vue'
import { useLayoutStore } from '../stores/layout'

const route = useRoute()
const nodes = useNodesStore()
const sys = useSystemStore()
const layout = useLayoutStore()

const node = computed(() => (route.params.id ? nodes.byId[route.params.id] : null))

// 健康态文字 (圆点纯色不可达, 点旁补字; 未知值原样直出) —— 表已并入 utils/deviceLabels.js

// 工位 L2 复位 (仅 plc_station 节点): station 名 = 节点 id 去 plc. 前缀; 危险外向操作 → DEBUG 门控 + 二次确认
const isDebug = computed(() => sys.mode === 'DEBUG')
const stationOf = computed(() => (node.value ? node.value.id.replace(/^plc\./, '') : ''))
const resetMsg = ref('')
const resetAction = useAsyncAction(async () => {
  await api.plcStationReset(stationOf.value)
  resetMsg.value = '已复位 ✓'
}, { errorPrefix: '复位失败', onError: (msg) => { resetMsg.value = msg } })
async function doReset() {
  if (!isDebug.value || !stationOf.value) {
    return
  }
  if (!(await confirmAction({
    title: `复位工位 ${stationOf.value}`,
    message: `确认复位工位 ${stationOf.value} 的 L2 故障?`,
    level: 'danger',
    confirmText: '复位',
  }))) {
    return
  }
  resetMsg.value = ''
  await resetAction.run()
}

// 工位初始化: 真跑一遍该工位的 *.init 原子 (清气缸/阀、轴归位、泵初始化), 与上面的复位不是一回事。
// 不做 DEBUG 门控 —— 初始化是每天开机的正常操作而非调试手段, RUN 下也要能用。
// 动作被拒/报错回的是 200 + ok=false (与 /api/actions/{name}/run 同口径), 故不能只 catch 异常。
const initMsg = ref('')
const initAction = useAsyncAction(async () => {
  const r = await api.plcStationInit(stationOf.value)
  if (r.ok) {
    // 展缸逐缸跑, 条数 >1 时点明跑了几条, 免得看着像只做了一件事
    initMsg.value = r.results && r.results.length > 1
      ? `已初始化 ✓ (${r.results.length} 缸)`
      : '已初始化 ✓'
  } else {
    const bad = (r.results || []).filter((x) => x.status !== 'DONE')
    initMsg.value = `初始化未完成: ${bad.map((x) => x.message || x.status).join('; ')}`
  }
}, { errorPrefix: '初始化失败', onError: (msg) => { initMsg.value = msg } })
async function doInit() {
  if (!stationOf.value) {
    return
  }
  if (!(await confirmAction({
    title: `初始化工位 ${stationOf.value}`,
    message: `确认初始化工位 ${stationOf.value}? 该操作会实际动作机构 (清气缸/阀、轴归位)。`,
    level: 'danger',
    confirmText: '初始化',
  }))) {
    return
  }
  initMsg.value = ''
  await initAction.run()
}

// 展缸 Tank_State 枚举 → 可读态 (真源: config/plc_nodes.yaml 的 Tank_State comment)。
// 98 是 develop.drain (code 50) 的终态: 该态下再发 drain 会走"幂等直通"秒返回 DONE 而不排液,
// 须先 develop.release_tank 归 0。原始数组经 fmtValue 会渲染成 98.00 且无缸号, 故单列成表。
const TANK_STATE_LABELS = {
  0: 'Idle',
  10: 'Prepping',
  40: 'Developing(legacy)',
  50: 'Draining',
  55: 'BlowAir',
  56: 'Drying',
  90: 'Error',
  98: 'DrainedIdle(盖关待取板)',
  99: 'legacy遗留',
}

// 展缸阵列字段: 单列成表, 不再进通用快照表
const TANK_ARRAY_KEYS = ['Tank_State', 'Tank_Drain_Done']

// 展缸 per-tank 行 (仅 Develop 工位有 Tank_State 时非空); 下标 0 对应 1 号缸
const tankRows = computed(() => {
  const states = node.value && node.value.data ? node.value.data.Tank_State : null
  if (!Array.isArray(states)) return []
  const dones = node.value.data.Tank_Drain_Done
  return states.map((state, i) => ({
    id: i + 1,
    state,
    label: TANK_STATE_LABELS[state] !== undefined ? TANK_STATE_LABELS[state] : '未知',
    drainDone: Array.isArray(dones) ? dones[i] : null,
  }))
})

// 快照标量/数组字段 (跳过嵌套对象与已单列成表的展缸阵列)。
// 注意 typeof null === 'object': 后端读失败置 null 的字段本就被第一道过滤丢弃 (既有行为,
// 标量附加镜像同理), 故此处无须再为 null 分支留路。
const rows = computed(() => {
  if (!node.value || !node.value.data) return []
  return Object.entries(node.value.data)
    .filter(([k, v]) => (typeof v !== 'object' || Array.isArray(v)) && !TANK_ARRAY_KEYS.includes(k))
    .map(([k, v]) => ({ k, v: fmtValue(v) }))
})

// 切换节点时同步选中态 (监视器跟随)
watch(() => route.params.id, (id) => { if (id) nodes.select(id) }, { immediate: true })
</script>

<template>
  <!-- 未选节点: 设备页落地 = 设备参数 (相机/CNC/视觉) 编辑; 单栏, 壳层不 flush -->
  <div v-if="!node" class="detail">
    <h2 class="col-title">设备参数</h2>
    <DeviceParamsPanel />
  </div>

  <!-- 已选节点: 页级两栏 (壳层 flush 露底色缝) —— 左控制主体 | 右状态侧栏, 中缝可拖 (照 .action-page 配方) -->
  <div v-else class="node-page" :style="{ '--device-side-w': layout.sizes.deviceSideW + 'px' }">
    <section class="detail node-main">
      <h2><span class="health-dot" :class="node.health" aria-hidden="true" /> <span class="health-text">{{ healthText(node.health) }}</span> {{ node.label }} <small>{{ node.id }}</small></h2>

      <!-- 机器人操作台 -->
      <RobotJogPanel v-if="node.kind === 'robot'" :node="node" />

      <!-- PLC 工位: 单点控制 (复刻 HMI 手动屏; 该工位无执行器/轴时组件自身不渲染) -->
      <StationManualPanel v-if="node.kind === 'plc_station'" :station="stationOf" />
    </section>

    <aside class="detail node-side">
      <h4 class="col-title">状态</h4>

      <!-- PLC 工位: 初始化 (跑 *.init, 会动机构) + L2 复位 (仅清故障位, 不动机构; DEBUG 门控)
           —— 看完状态要做的事, 置侧栏顶部随手可达 -->
      <div v-if="node.kind === 'plc_station'" class="station-ctrl">
        <button class="init-btn" :disabled="initAction.busy || resetAction.busy" :aria-busy="initAction.busy"
                title="跑该工位的初始化动作: 清气缸/阀、轴归位、泵初始化 (会实际动作机构)"
                @click="doInit">
          {{ initAction.busy ? '初始化中…' : '初始化' }}
        </button>
        <span v-if="initMsg" class="reset-msg" role="status">{{ initMsg }}</span>
        <button class="reset-btn" :disabled="!isDebug || resetAction.busy || initAction.busy" :aria-busy="resetAction.busy"
                :title="isDebug ? '脉冲 L2_Reset 清工位故障' : '仅 DEBUG 模式可复位'" @click="doReset">
          {{ resetAction.busy ? '复位中…' : '复位 (清 L2 故障)' }}
        </button>
        <span v-if="resetMsg" class="reset-msg" role="status">{{ resetMsg }}</span>
      </div>

      <!-- 展缸阵列 (仅 Develop 工位): per-tank 生命周期 + 排液完成位 -->
      <template v-if="tankRows.length">
        <h4>展缸阵列</h4>
        <table class="kv tanks">
          <thead>
            <tr><th>缸号</th><th>状态</th><th>排液完成</th></tr>
          </thead>
          <tbody>
            <!-- label 是 state 的纯函数, id 即 :key 恒定 → memo [state, drainDone] 已覆盖行内全部动态输出 -->
            <tr v-for="tank in tankRows" :key="tank.id" v-memo="[tank.state, tank.drainDone]">
              <td>缸 {{ tank.id }}</td>
              <td>{{ tank.state }} {{ tank.label }}</td>
              <td>{{ fmtValue(tank.drainDone) }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <h4>实时快照</h4>
      <!-- v-memo 与 v-for 同元素: 遥测 1Hz 整表重算时值未变的行跳过 patch (k 即 :key 恒定, 行内动态输出仅 row.v) -->
      <table class="kv">
        <tbody>
          <tr v-for="row in rows" :key="row.k" v-memo="[row.v]">
            <td>{{ row.k }}</td>
            <td class="num">{{ row.v }}</td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="2" class="none-row">暂无快照字段</td>
          </tr>
        </tbody>
      </table>
    </aside>

    <!-- 主区↔状态栏 竖向 (状态栏在右 → sign=-1); 手柄落进两栏间 10px 缝 -->
    <Splitter skey="deviceSideW" dir="x" :sign="-1" class="seam-device-v" />
  </div>
</template>

<style scoped>
/* 页级两栏: 左控制主体 minmax(0,1fr) + 右状态侧栏 (Splitter 可拖, layout.deviceSideW)。
   照 .action-page 配方 (style.css): 全高 grid + 两栏各自滚动 —— monitor 可把中区压到 ~400px,
   独立滚动在任意高度成立, 不做 sticky。gap 与 seam 负 margin 逐字耦合 (10px)。 */
.node-page { display: grid; grid-template-columns: minmax(0, 1fr) var(--device-side-w, 360px);
  grid-template-rows: minmax(0, 1fr); gap: 10px; height: 100%; }
.node-main, .node-side { overflow: auto; background: var(--panel); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 12px; }
/* 侧栏显式占 r1c2, 与分隔条同格重叠, 避免分隔条把它挤到隐式第二行 (照 .dev-params-col) */
.node-side { grid-row: 1; grid-column: 2; }
.seam-device-v { grid-row: 1; grid-column: 2; justify-self: start; align-self: stretch; width: 10px; margin-left: -10px; }
/* 窄屏塌单列: 控制在上、状态在下, 滚动交还 .area-center (与 RobotJogPanel 同断点) */
@media (max-width: 1100px) {
  .node-page { grid-template-columns: 1fr; grid-template-rows: none; height: auto; }
  .node-main, .node-side { overflow: visible; }
  .node-side { grid-row: auto; grid-column: auto; }
  .seam-device-v { display: none; }
}

.station-ctrl { display: flex; align-items: center; gap: 10px; margin: 8px 0 4px; flex-wrap: wrap; }
.reset-btn { padding: 5px 14px; border: 1px solid var(--bad); background: var(--bad-soft); color: var(--bad); cursor: pointer; border-radius: var(--radius-md); font-weight: 700; }
.reset-btn:hover:not(:disabled) { border-color: var(--bad-strong); color: var(--bad-strong); }
.reset-btn:disabled { opacity: 0.5; cursor: not-allowed; }
/* 初始化不同于复位: 是常规开机操作而非故障处置, 故用中性强调色而不是复位的告警红 */
.init-btn { padding: 5px 14px; border: 1px solid var(--accent); background: transparent; color: var(--accent); cursor: pointer; border-radius: var(--radius-md); font-weight: 700; }
.init-btn:hover:not(:disabled) { background: var(--hover); }
.init-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.reset-msg { font-family: var(--font-mono); font-size: var(--fs-12); }
/* 展缸阵列: 全局 .kv 只给 td 样式且首列锁 42%, 三列表需自设列宽与表头 */
.tanks th { border-bottom: 1px solid var(--border); padding: 4px 6px; text-align: left; color: var(--subtle); font-weight: 600; }
.tanks td:first-child { width: 18%; }
.tanks td:nth-child(2) { font-family: var(--font-mono); }
.tanks th:last-child, .tanks td:last-child { width: 22%; }
/* h2 标题样式已上提全局 (.detail h2); h2.col-title 由更高特异度的全局 .detail > .col-title 接管 */
.health-text { font-size: var(--fs-12); font-weight: 600; color: var(--subtle); }
/* 空快照占位行: 盖掉 .kv td:first-child 的 42% 锁宽与强调样式 */
.kv td.none-row { color: var(--muted); font-weight: 500; width: auto; }
</style>
