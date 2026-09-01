<script setup>
/**
 * 功能: 三维实时页 (/3d/live) 的组合根 —— 画布 + 左栏工位导航 + 顶部工具栏 + 右侧信息坞.
 *
 * 布局: grid `1fr | 坞宽`。右侧不再是四个抢同一个右上角的浮层, 而是一条真的 grid 轨道,
 * 宽度用仓内既有的 Splitter + stores/layout 持久化。这样做同时解决了三件事:
 *   ① 面板互相盖住(旧实现的互斥逻辑手写在模板内联表达式里, 且漏了组合);
 *   ② 内容被浏览器底边裁掉(坞自己是唯一的滚动容器);
 *   ③ 观察类信息与设备类信息混在一起(拆成「显示信息」与「工站信息」两页)。
 *
 * 面板互斥不再靠手写: scope 由 selectedStation **推导** (见 useLivePanels), 于是
 * "取消选中"的每条路径都自动收敛。
 *
 * 画布重算无需新增代码: SceneManager 用 ResizeObserver 观察 containerRef,
 * 改 grid 轨道 -> .twin__viewport 变宽 -> inset:0 的画布 div 边框盒变化 -> RO 触发。
 */
import { computed, reactive, ref, watch } from 'vue'

import Splitter from '../../components/Splitter.vue'
import { useAsyncAction } from '../../composables/useAsyncAction.js'
import { useLayoutStore } from '../../stores/layout.js'
import { fetchActions } from './api.js'
import { applyDraft, clearDraft, createDraft, describeEntry, putEntry, removeEntry, replayOrder }
  from './materialDraft.js'
import { materialHealthOf, stationHasMaterial, stationOfEntity, verifiedSensorCount } from './materialStations.js'
import { hasManualCamera, validateStationCamera } from './stationViewRules.js'
import { clearStationCamera, manifestKeyForUrl, saveStationCamera } from './stationViewWriter.js'
import { liveMaterialWriteApi } from './materialWriteApi.js'
import { availableStationTabs, GLOBAL_TABS, resolveStationTab, STATION_TABS, useLivePanels }
  from './useLivePanels.js'
import { useManualSession } from './useManualSession.js'
import { useTwinScene } from './useTwinScene.js'

import DisplayPanel from './panels/DisplayPanel.vue'
import DockTabs from './panels/DockTabs.vue'
import LiveHud from './panels/LiveHud.vue'
import LiveToolbar from './panels/LiveToolbar.vue'
import MachineInfoPanel from './panels/MachineInfoPanel.vue'
import ManualSessionBar from './panels/manual/ManualSessionBar.vue'
import MaterialInteraction from './panels/MaterialInteraction.vue'
import MaterialPanel from './panels/MaterialPanel.vue'
import StationActionsTab from './panels/StationActionsTab.vue'
import StationMaterialsTab from './panels/StationMaterialsTab.vue'
import StationStatusTab from './panels/StationStatusTab.vue'
import TimelineBar from './panels/TimelineBar.vue'
import { ReplayChannel } from '../replay/replayChannel.js'
import ViewerInfoPanel from './panels/ViewerInfoPanel.vue'
import { homeAll, machineResume, machineStop } from './manualApi.js'
import './panels/dock.css'

const props = defineProps({
  /** 整机 GLB 地址 */
  modelUrl: { type: String, default: '/api/3d/assets/models/machine.glb' },
  /** 绑定契约地址 */
  manifestUrl: { type: String, default: '/api/3d/assets/models/device-manifest.json' },
  /**
   * 是否接入上位机实时事件流.
   * 默认关闭 —— 本应用是独立的三维演示网页, 脱离上位机也应完整可用;
   * 状态对齐是可选增强, 不是运行前提.
   */
  live: { type: Boolean, default: false },
  /** 是否启用手动控制(实时页 /live 传入; 上位机手动模式操作) */
  manualEnabled: { type: Boolean, default: false },
})

/** 画布容器的模板引用 */
const containerRef = ref(null)
/** 录像回放传输层: 常驻实例, 由时间线条开关; 未激活时对实时链路完全透明。 */
const replayChannel = new ReplayChannel()
/** 显示设置弹层开关(它是浮层不是坞页, 与坞无关) */
const displayOpen = ref(false)

const layout = useLayoutStore()

const {
  manager, manifest, feed, eventStream, loading, progress, error, warnings,
  stats, modelInfo, summary, connection, realtime, materials,
  hoveredStation, selectedStation, focusableStations, stationHealth,
  tankStates, tankVolumesMl, tankCapacityMl, pumpSyringes, selectedSnapshot,
  autoRotate, setQuality, applyPreset, selectStation, toggleAutoRotate, replayIntro,
} = useTwinScene({
  containerRef,
  modelUrl: props.modelUrl,
  manifestUrl: props.manifestUrl,
  live: props.live,
  // 薄层板层只在孪生视图开: 装配台/材质台要的是 CAD 原貌, 不该多出在制板与料仓堆叠
  plates: true,
  // 录像回放: 通道常驻但默认不激活(active=false), 切模式因此无需重挂场景 ——
  // 整机 GLB 14.8 MB 且资产端点带 no-store, 重挂一次就是几秒黑屏。
  replayChannel,
  // "现在"的定义随模式切换: 回放态取播放头, 否则墙钟。下游全部 staleness/插值判定
  // 都吃这一个函数(见 TwinFeed 构造函数注释)。
  feedClock: () => (replayChannel.active ? replayChannel.now() : Date.now()),
})

const { dock, scope, openGlobal, openStationTab, toggleDock } = useLivePanels({
  selectedStation, selectStation,
})
const manual = useManualSession()

// ── 工位与页签 ──────────────────────────────────────────────────────────
/**
 * 左栏工位列表. 过滤条件是"有遥测节点**或**管着物料" ——
 * 料架(RACK)没有遥测节点, 但 12 个库位 72 个孔位都归它, 用户要改物料就得能点到它。
 */
const stations = computed(() =>
  (manifest.value?.stations || []).filter(
    (station) => station.nodeId || stationHasMaterial(manifest.value, station.id),
  ))

const station = computed(() =>
  (manifest.value?.stations || []).find((item) => item.id === selectedStation.value) || null)

/**
 * 没有 PLC 遥测节点、但管着物料的工位(眼下只有料架)的圆点状态.
 *
 * 只算这些工位: 有遥测节点的一律以设备健康为准, 多算一遍纯属浪费。
 */
const materialStationHealth = computed(() => {
  const snapshot = materials.value?.snapshot || null
  const out = {}
  for (const item of stations.value) {
    if (item.nodeId) continue
    out[item.id] = materialHealthOf(manifest.value, snapshot, item.id)
  }
  return out
})

/** 上述工位各有几路已核实光电(tooltip 要如实交代判据来源) */
const materialSensorCounts = computed(() => {
  const snapshot = materials.value?.snapshot || null
  const out = {}
  for (const item of stations.value) {
    if (item.nodeId) continue
    out[item.id] = verifiedSensorCount(manifest.value, snapshot, item.id)
  }
  return out
})

const stationTabKeys = computed(() =>
  availableStationTabs(station.value, stationHasMaterial(manifest.value, selectedStation.value)))

const activeStationTab = computed(() => resolveStationTab(dock.stationTab, stationTabKeys.value))

const dockTabs = computed(() => (scope.value === 'station'
  ? STATION_TABS.filter((tab) => stationTabKeys.value.includes(tab.key))
  : GLOBAL_TABS))

const activeTab = computed(() =>
  (scope.value === 'station' ? activeStationTab.value : dock.globalTab))

const dockWidth = computed(() => (dock.collapsed ? '36px' : `${layout.sizes.twinDockW}px`))

/** 动作目录(全量, 挂载时拉一次; 工位页按 station.actions 过滤) */
const actionCatalog = ref([])
fetchActions()
  .then((list) => { actionCatalog.value = Array.isArray(list) ? list : list?.items || [] })
  .catch(() => { actionCatalog.value = [] })

/**
 * 功能: 页签点击 —— 工位族切页, 全局族切页.
 * @param {string} key 页签 key
 * @returns {void}
 */
function onSelectTab(key) {
  if (scope.value === 'station') openStationTab(key)
  else openGlobal(key)
}

// ── 特写 ────────────────────────────────────────────────────────────────
/** 工位根节点下的 mesh 缓存(描边要 mesh 数组, Selection 不递归 Group) */
const stationMeshCache = new Map()

/**
 * 功能: 取某工位的 mesh 数组(首次遍历后缓存).
 * @param {string} id 工位 id
 * @returns {object[]} mesh 数组
 */
function meshesOfStation(id) {
  if (!id) return []
  if (stationMeshCache.has(id)) return stationMeshCache.get(id)
  const root = manager.value?.bindings?.getStationRoot?.(id)
  const meshes = []
  root?.traverse?.((child) => { if (child.isMesh) meshes.push(child) })
  stationMeshCache.set(id, meshes)
  return meshes
}

/**
 * 功能: 把选中工位描边.
 *
 * ⚠ 低画质档没有描边链(QUALITY_TIERS.low.outline === false), 而卡顿时会自动降档 ——
 *   所以描边**不是**选中反馈的唯一凭据: 左栏行高亮 + 坞页签 + 柜内工位外罩透视 才是。
 *   这与 MaterialInteraction 头注记的降级同款, 如实写在这里而不是假装它有保证。
 * @returns {void}
 */
function applyStationOutline() {
  manager.value?.outline?.set('station', meshesOfStation(selectedStation.value))
}

/**
 * 功能: 点工位 = 选中 + 相机特写.
 *
 * 环绕的自停在 SceneManager.flyToStation 里(它与画布双击、零件聚焦共用那一条闸口),
 * 这里不再重复一遍 —— 于是"点了个没有几何、相机压根没动的工位"也不会莫名其妙把环绕停掉。
 * @param {string} id 工位 id
 * @returns {void}
 */
function focusStation(id) {
  dock.collapsed = false
  selectStation(id)
  if (focusableStations.value.has(id)) manager.value?.flyToStation(id)
  applyStationOutline()
}

// ── 模块视角设定 ────────────────────────────────────────────────────────
/** 可设视角的模块(能相机飞入的那些) */
const viewStations = computed(() =>
  stations.value
    .filter((item) => focusableStations.value.has(item.id))
    .map((item) => ({ id: item.id, label: item.label, manual: hasManualCamera(item) })))

const viewBusy = ref(false)
const viewMessage = ref('')

/**
 * 功能: 把当前镜头存成某工位的跳转视角.
 *
 * 保存前用与产物看门狗**同一份**判据校验(stationViewRules) —— 存一个落在机柜内部的机位
 * 会让 manifest.test.js 变红, 而那时人早已离开这个页面, 根本联想不到是自己刚存的视角。
 * @param {string} stationId 工位 id
 * @returns {Promise<void>} 完成
 */
async function onSaveStationView(stationId) {
  const rig = manager.value?.cameraRig
  const target = (manifest.value?.stations || []).find((item) => item.id === stationId)
  if (!rig || !target) return
  const camera = rig.getState()
  const verdict = validateStationCamera(camera, manifest.value?.machine?.bounds)
  if (!verdict.ok) {
    viewMessage.value = `未保存: ${verdict.reason}`
    return
  }
  viewBusy.value = true
  viewMessage.value = ''
  try {
    // 写盘键随本页加载的 manifest 走: /3d/live 用 official-cr5, 写错文件=保存的视角刷新即丢
    const result = await saveStationCamera(
      manifestKeyForUrl(props.manifestUrl), stationId, camera, target.camera)
    if (result.conflict) {
      viewMessage.value = 'manifest 在你编辑期间被别处改过(可能是三维管线或另一个页面), '
        + '本次未写入。请重试一次 —— 补丁会打在最新内容上。'
      return
    }
    // 本地 manifest 立刻跟上, 否则要刷新页面才看得到"已设定"与新的跳转行为
    target.camera = { ...camera, manual: true, ...(target.camera?.auto ? { auto: target.camera.auto } : {}) }
    viewMessage.value = `已保存 ${target.label} 的跳转视角(演示页该工位的镜头也已改变)`
  } catch (err) {
    viewMessage.value = `保存失败: ${err.message}`
  } finally {
    viewBusy.value = false
  }
}

/**
 * 功能: 清除人工机位, 还原成管线自动取景.
 * @param {string} stationId 工位 id
 * @returns {Promise<void>} 完成
 */
async function onClearStationView(stationId) {
  const target = (manifest.value?.stations || []).find((item) => item.id === stationId)
  // 与保存同一把写盘键: 清除也必须落在本页在用的那份 manifest 上
  if (!target) return
  viewBusy.value = true
  viewMessage.value = ''
  try {
    const result = await clearStationCamera(
      manifestKeyForUrl(props.manifestUrl), stationId, target.camera)
    if (result.conflict) {
      viewMessage.value = 'manifest 在你编辑期间被别处改过, 本次未写入。请重试一次。'
      return
    }
    const auto = target.camera?.auto
    target.camera = auto ? { pos: auto.pos, target: auto.target } : { ...target.camera, manual: false }
    viewMessage.value = `已清除 ${target.label} 的人工视角, 恢复自动取景`
  } catch (err) {
    viewMessage.value = `清除失败: ${err.message}`
  } finally {
    viewBusy.value = false
  }
}

/** 功能: 回整机全景(顺带清选中, 否则柜内工位的外罩透视会留在开着的状态, 看着像渲染 bug). */
function resetView() {
  selectStation(null)
  applyPreset('iso')
}

/** 功能: 重播开场 —— 同样先清选中. */
function onReplayIntro() {
  selectStation(null)
  replayIntro()
}

watch(selectedStation, (id) => {
  // 只撤自己那一层: 取消选中工位不该顺手抹掉用户刚点开的物料卡片描边
  if (id) applyStationOutline()
  else manager.value?.outline?.clear('station')
})

// ── 选中孔位(三维左键 ⇄ 工位物料页双向同源) ─────────────────────────────
const selectedCell = ref(/** @type {{kind:string, plate:number, hole:number}|null} */ (null))

/**
 * 功能: 选中一个孔 —— 三维左键与物料页孔位格网都汇到这里.
 *
 * 孔级账本挂在货架工位的「物料」页 rack 分段(无论件此刻画在货架还是中转,
 * 中转分段只管托盘级), 所以选中即定位到该工位的物料页签; 描边由
 * MaterialInteraction 按 selectedCell prop 单写者驱动。
 * @param {{kind:string, plate:number, hole:number}|null} cell 选中孔; null = 清选
 * @returns {void}
 */
function onCellSelected(cell) {
  selectedCell.value = cell
  if (!cell) return
  const owner = stationOfEntity(manifest.value, 'rack')
  if (!owner) return
  dock.collapsed = false
  selectStation(owner)
  openStationTab('material')
}

// 切去别的工位就放掉选中孔 —— 描边不留在没人看的角落
watch(selectedStation, (id) => {
  if (selectedCell.value && id !== stationOfEntity(manifest.value, 'rack')) {
    selectedCell.value = null
  }
})

// ── 物料草稿 ────────────────────────────────────────────────────────────
const draft = reactive(createDraft())
const draftCount = computed(() => draft.entries.size)
const draftRows = computed(() =>
  [...draft.entries.values()].map((entry) => ({ key: entry.key, ...describeEntry(entry) })))
const draftMessage = ref('')

/** 把草稿装到绑定层(叠加作用在原始事件上, 走同一个 normalizeSnapshot) */
function syncOverlay() {
  const store = feed.value?.materialStore
  if (!store) return
  if (draft.entries.size === 0) store.setDraftOverlay(null)
  else store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
}

/**
 * 功能: 记一条待提交的改动.
 * @param {string} verb 写动词
 * @param {object} args 参数
 * @returns {void}
 */
function onEdit(verb, args) {
  draftMessage.value = ''
  putEntry(draft, verb, args)
  syncOverlay()
}

/**
 * 功能: 撤掉草稿里的一条.
 * @param {string} key 幂等键
 * @returns {void}
 */
function onDropEntry(key) {
  removeEntry(draft, key)
  syncOverlay()
}

/** 功能: 放弃全部草稿, 画面回落到推流账本. */
function onCancelDraft() {
  clearDraft(draft)
  syncOverlay()
  draftMessage.value = '已放弃未保存的改动，画面已恢复为账本实况。'
}

/** 写动词 -> materialWriteApi 调用(闭集; materialDraft 只产这些动词) */
const WRITE_RUNNERS = {
  mark: (a) => liveMaterialWriteApi.mark(a),
  setCellAmount: (a) => liveMaterialWriteApi.setCellAmount(a),
  setStaging: (a) => liveMaterialWriteApi.setStaging(a.area, a.plate),
  setRack: (a) => liveMaterialWriteApi.setRack(a.kind, a.plate, a.present),
  setMagazine: (a) => liveMaterialWriteApi.setMagazine(a.magazine, a.count),
  setBottle: (a) => liveMaterialWriteApi.setBottle(a.bottle, a.volumeMl),
  setSeat: (a) => liveMaterialWriteApi.setSeat(a.seat, a.present),
}

const saveDraft = useAsyncAction(
  async () => {
    const entries = replayOrder(draft)
    // **串行**执行: 每个端点都在同一把 SQLite 锁后返回完整 grid(), 并行毫无收益,
    // 却会毁掉部分失败的可报告性(失败时说不清是第几条炸的)
    for (let index = 0; index < entries.length; index += 1) {
      const entry = entries[index]
      try {
        await WRITE_RUNNERS[entry.verb]?.(entry.args)
      } catch (err) {
        draftMessage.value = `已提交 ${index}/${entries.length} 条；第 ${index + 1} 条「`
          + `${describeEntry(entry).text}」失败: ${err.message}。余下改动仍留在草稿里。`
        throw err
      }
      removeEntry(draft, entry.key)
    }
    // 成功即丢草稿 —— 画面回落到推流账本(约 1 秒内回读)。
    // 这样"不做乐观渲染"那条纪律字面完好: 叠加层只存在于**提交之前**。
    clearDraft(draft)
    draftMessage.value = '已保存 · 等待账本回读（约 1 秒）'
  },
  { announce: '物料账本已保存', errorPrefix: '保存失败' },
)

async function onSaveDraft() {
  draftMessage.value = ''
  await saveDraft.run()
  syncOverlay()
}

// 换工位就丢草稿: 草稿是挂在某个工位的编辑意图上的, 带着它跑到别的工位没有意义,
// 而"悄悄跟着走"会让人在 B 工位保存出 A 工位的改动
watch(selectedStation, () => {
  if (draft.entries.size) {
    clearDraft(draft)
    syncOverlay()
    draftMessage.value = ''
  }
})

// ── 整机操作(不属于任何单一工位) ────────────────────────────────────────
/** 两击确认的武装状态: 动作名 -> 到期时间戳 */
const armed = ref({})
const machineMessage = ref('')

/**
 * 功能: 整机级危险操作的两击确认 —— 第一击武装(3s), 第二击执行.
 * @param {'homeAll'|'stop'|'resume'} name 动作名
 * @returns {Promise<void>} 完成
 */
async function machineOp(name) {
  const now = Date.now()
  if (!armed.value[name] || armed.value[name] < now) {
    armed.value = { ...armed.value, [name]: now + 3000 }
    setTimeout(() => {
      if (armed.value[name] && armed.value[name] <= Date.now()) {
        armed.value = { ...armed.value, [name]: 0 }
      }
    }, 3200)
    return
  }
  armed.value = { ...armed.value, [name]: 0 }
  try {
    if (name === 'homeAll') await homeAll()
    else if (name === 'stop') await machineStop()
    else await machineResume()
    machineMessage.value = { homeAll: '一键回原点已下发', stop: '停机已下发', resume: '恢复运行已下发' }[name]
  } catch (err) {
    machineMessage.value = `操作失败: ${err.message}`
  }
}

const liveLabel = computed(() => {
  if (!connection.value.connected) return connection.value.reconnecting ? '重连中' : '离线'
  if (realtime.value?.robot?.resynced
    || realtime.value?.axes?.resynced?.length
    || realtime.value?.mechanisms?.resynced?.length) return '重新同步'
  if (realtime.value?.robot?.stale) return '机器人陈旧'
  if ((realtime.value?.axes?.stale || 0) > 0) return '部分陈旧'
  return '实时'
})
</script>

<template>
  <div
    class="twin"
    :class="{ 'twin--railed': dock.collapsed }"
    :style="{ '--twin-dock-w': dockWidth }"
  >
    <div class="twin__viewport">
      <div ref="containerRef" class="twin__canvas" />

      <!-- 草稿预览的画布级标记: 侧栏滚走了也看得见"这不是设备实况" -->
      <div v-if="draftCount" class="twin__draft-strip" aria-hidden="true" />
      <div v-if="draftCount" class="twin__draft-chip">物料预览中 · {{ draftCount }} 项未保存</div>

      <LiveToolbar
        v-if="!error"
        :quality="stats.quality"
        :auto-rotate="autoRotate"
        :display-open="displayOpen"
        @preset="applyPreset"
        @quality="setQuality"
        @reset-view="resetView"
        @display="displayOpen = !displayOpen"
        @autorotate="toggleAutoRotate"
        @replay-intro="onReplayIntro"
      />

      <LiveHud
        v-if="!error"
        :stations="stations"
        :health="stationHealth"
        :material-health="materialStationHealth"
        :sensor-counts="materialSensorCounts"
        :selected="selectedStation"
        :hovered="hoveredStation"
        :focusable="focusableStations"
        :connection="connection"
        :live-label="liveLabel"
        :warnings="loading ? [] : warnings"
        @station="focusStation"
      />

      <!-- 显示设置: 浮层, 挂在工具栏下方 -->
      <DisplayPanel
        v-if="displayOpen && manager"
        :manager="manager"
        :stats="stats"
        :anchor-right="16"
        :anchor-top="56"
        :view-stations="viewStations"
        :view-selected="selectedStation || ''"
        :view-savable="manual.modeAllowed.value"
        :view-busy="viewBusy"
        :view-message="viewMessage"
        @close="displayOpen = false"
        @save-view="onSaveStationView"
        @clear-view="onClearStationView"
      />

      <!-- 物料点选改账: 右键物料实体弹快捷菜单/编辑卡片(卡片仍浮在画布区, 它的所指是
           空间性的 —— 用户右键了某个具体物体, 把卡片搬到 600px 外会断掉指向关系) -->
      <MaterialInteraction
        v-if="live && !error && !loading && manager"
        :manager="manager"
        :materials="materials"
        :locked="draftCount > 0"
        :selected-cell="selectedCell"
        @panel-open="displayOpen = false"
        @cell-selected="onCellSelected"
      />

      <!-- 唯一的一条时间线: 墙钟录像 + 工位利用率 + 动作甘特泳道。原来并列的两条已
           合并 —— 两条都叫"回放"只会让人在两个入口之间猜。
           stations 只用来把利用率提示里的工位 key 译成中文名, 设备清单是唯一出处。 -->
      <TimelineBar
        v-if="!error && !loading && manifest"
        :channel="replayChannel"
        :stream="eventStream"
        :stations="manifest.stations || []"
        @focus-station="focusStation"
      />

      <div v-if="loading" class="twin__overlay">
        <div class="twin__spinner" />
        <p class="twin__hint">正在加载设备模型…</p>
        <div class="twin__bar">
          <div class="twin__bar-fill" :style="{ width: `${Math.round(progress * 100)}%` }" />
        </div>
        <p class="twin__percent">{{ Math.round(progress * 100) }}%</p>
      </div>

      <div v-if="error" class="twin__overlay twin__overlay--error">
        <p class="twin__error-title">三维视图加载失败</p>
        <p class="twin__error-detail">{{ error }}</p>
        <p class="twin__error-hint">
          请确认 models/ 下已有 machine.glb 与 device-manifest.json，且资产管线已执行完毕。
        </p>
      </div>
    </div>

    <Splitter v-if="!dock.collapsed" skey="twinDockW" dir="x" :sign="-1" class="twin__seam" />

    <aside class="twin__dock">
      <DockTabs
        :tabs="dockTabs"
        :active="activeTab"
        :collapsed="dock.collapsed"
        :title="scope === 'station' ? (station?.label || '') : ''"
        @select="onSelectTab"
        @toggle="toggleDock"
      />

      <!-- v-if 而非 v-show: 收起坞要真的卸载页签体, 于是单点会话随之释放(与关面板同义) -->
      <div v-if="!dock.collapsed" class="twin__dock-body">
        <template v-if="scope === 'station' && station">
          <StationStatusTab
            v-if="activeTab === 'status' && manifest"
            :manifest="manifest"
            :station="station"
            :health="stationHealth[station.id] || 'unknown'"
            :snapshot="selectedSnapshot"
            :control-mode="manual.mode.value"
            :action-catalog="actionCatalog"
            :tank-states="tankStates"
            :tank-volumes-ml="tankVolumesMl"
            :tank-capacity-ml="tankCapacityMl"
            :mechanisms="realtime?.mechanisms?.items || []"
            :pump-syringes="pumpSyringes"
          />
          <!-- :key 是承重的: 三个页签同层 v-if/v-else-if, 切工位时 Vue 会复用同一实例
               只 patch props —— 上一个工位点开的动作表单(openAction)、零件聚焦(focusedPart)
               与描边 part 层全都留着, part 层还会压住新工位的 station 描边。
               按工位重挂让 onBeforeUnmount 的清理必然执行, 状态自然归零。 -->
          <StationActionsTab
            v-else-if="activeTab === 'actions' && manifest"
            :key="station.id"
            :manifest="manifest"
            :station="station"
            :action-catalog="actionCatalog"
            :realtime="realtime"
            :snapshot="selectedSnapshot"
            :health="station ? stationHealth[station.id] || '' : ''"
            :manual="manual"
            :manager="manager"
          />
          <StationMaterialsTab
            v-else-if="activeTab === 'material' && manifest"
            :manifest="manifest"
            :station="station"
            :snapshot="materials?.snapshot || null"
            :materials="materials"
            :draft-rows="draftRows"
            :saving="saveDraft.busy"
            :message="draftMessage || saveDraft.error || ''"
            :selected-cell="selectedCell"
            @edit="onEdit"
            @drop-entry="onDropEntry"
            @save="onSaveDraft"
            @cancel="onCancelDraft"
            @select-cell="onCellSelected"
          />
        </template>

        <template v-else>
          <MachineInfoPanel
            v-if="activeTab === 'machine'"
            :manifest="manifest"
            :summary="summary"
            :realtime="realtime"
            :materials="materials"
          >
            <template #machine-ops>
              <details v-if="manualEnabled && live" class="dock-details twin__machine-ops">
                <summary>整机操作</summary>
                <ManualSessionBar
                  :state="manual.sessionState.value"
                  :mode="manual.mode.value"
                  :mode-offline="manual.modeOffline.value"
                  :mode-allowed="manual.modeAllowed.value"
                  :active="manual.active.value"
                  :gate-reason="manual.gateReason.value"
                  @toggle="manual.toggle()"
                />
                <p class="twin__machine-note">
                  以下三项作用于**整机**，不属于任何单一工位；两击确认。
                </p>
                <div class="twin__machine-btns">
                  <button
                    type="button" class="dock-btn dock-btn--danger"
                    :disabled="!manual.canWrite.value" @click="machineOp('homeAll')"
                  >{{ armed.homeAll > Date.now() ? '确认回原点？' : '一键回原点' }}</button>
                  <button
                    type="button" class="dock-btn dock-btn--danger"
                    :disabled="!manual.modeAllowed.value" @click="machineOp('stop')"
                  >{{ armed.stop > Date.now() ? '确认停机？' : '停机' }}</button>
                  <button
                    type="button" class="dock-btn dock-btn--danger"
                    :disabled="!manual.modeAllowed.value" @click="machineOp('resume')"
                  >{{ armed.resume > Date.now() ? '确认恢复？' : '恢复运行' }}</button>
                </div>
                <p v-if="machineMessage" class="twin__machine-msg">{{ machineMessage }}</p>
              </details>
            </template>
          </MachineInfoPanel>

          <ViewerInfoPanel
            v-else-if="activeTab === 'viewer'"
            :stats="stats"
            :model-info="modelInfo"
          />

          <MaterialPanel
            v-else-if="activeTab === 'materials'"
            :state="materials"
          />
        </template>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.twin {
  position: relative;
  display: grid;
  grid-template-columns: 1fr var(--twin-dock-w, 360px);
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--bg);
  /* 左栏宽度: LiveToolbar 的防撞与 TimelineBar 的左缘都读它, 只此一处定义 */
  --live-hud-w: 216px;
}

/* 收起态 = 36px 图标轨, 不是隐藏 —— 隐藏就得另找地方安一个"把坞找回来"的孤儿按钮 */
.twin--railed {
  grid-template-columns: 1fr 36px;
}

.twin__viewport {
  position: relative;
  min-width: 0;
  min-height: 0;
  /* 必须自己裁绝对定位的浮层(HUD/时间线/加载遮罩), 旧实现靠 .twin 一个 overflow 兜住一切,
     拆成 grid 两列之后就兜不住了。
     注: 曾以为画布本身也会溢出到右侧坞, 实为 Effects.resize 漏传 updateStyle 把画布 CSS 盒
     钉成固定像素所致(已修), 画布现在恒为容器的 100%, 不可能溢出。 */
  overflow: hidden;
}

.twin__canvas {
  position: absolute;
  inset: 0;
}

.twin__seam {
  position: absolute;
  top: 0;
  bottom: 0;
  right: calc(var(--twin-dock-w, 360px) - 5px);
  width: 10px;
}

.twin__dock {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  /* 坞内字号基线: 不设的话所有裸文本继承 body 的 14px, 与坞里满屏的 11-12px 组件
     格格不入(kv 行、轴名、蓝色数值都曾因此偏大)。与 MachineInfoPanel 的 .mip 同一手法 */
  font-size: 12px;
  background: var(--surface-soft);
  border-left: 1px solid var(--border);
}

/* 坞是整页唯一的右侧滚动容器 —— 旧实现里四个浮层各自处理高度, 于是各自都会被裁 */
.twin__dock-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.twin__machine-ops {
  display: grid;
  gap: 6px;
  margin-top: 8px;
}

.twin__machine-note {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-dim);
}

.twin__machine-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.twin__machine-msg {
  margin: 0;
  font-size: 11px;
  color: var(--warn);
}

/* 草稿预览: 画布顶边琥珀条 + 角标. 放顶部是因为左下角是时间线, 左上角是 HUD */
.twin__draft-strip {
  position: absolute;
  top: 0;
  right: 0;
  left: 0;
  z-index: 14;
  height: 3px;
  background: var(--warn);
  pointer-events: none;
}

.twin__draft-chip {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 14;
  padding: 3px 10px;
  font-size: 11px;
  color: var(--warn);
  background: var(--warn-soft);
  border: 1px solid color-mix(in srgb, var(--warn, #f4b740) 45%, transparent);
  border-radius: 999px;
  pointer-events: none;
}

.twin__overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 12px;
  align-items: center;
  justify-content: center;
  /* 加载遮罩用渐变而非纯色, 让背后的舞台微微透出来 */
  background: var(--curtain);
  color: var(--text);
  font-size: 13px;
}

.twin__spinner {
  width: 34px;
  height: 34px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: twin-spin 0.9s linear infinite;
}

@keyframes twin-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .twin__spinner { animation-duration: 3s; }
}

.twin__hint {
  margin: 0;
  letter-spacing: 0.05em;
}

.twin__bar {
  width: 220px;
  height: 3px;
  overflow: hidden;
  background: var(--border);
  border-radius: 2px;
}

.twin__bar-fill {
  height: 100%;
  background: var(--accent-gradient);
  transition: width 0.2s ease;
}

.twin__percent {
  margin: 0;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.twin__overlay--error {
  color: var(--err-bright);
}

.twin__error-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.twin__error-detail {
  max-width: 560px;
  margin: 0;
  color: var(--text-bright);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  text-align: center;
  word-break: break-all;
}

.twin__error-hint {
  margin: 0;
  color: var(--text-dim);
}
</style>
