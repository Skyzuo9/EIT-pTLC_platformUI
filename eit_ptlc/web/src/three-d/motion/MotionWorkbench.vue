<script setup>
/**
 * 功能: 动作工作台外壳 —— 一个场景, 三个子页(运动模式 / 标定 / 演示).
 *
 * 原「动作」与「标定」两页合并而来。合并的实质收益不是少一个页签, 而是:
 *   1. 模型只加载一次。三个子页共用同一份 machine.official-cr5.glb 与 manifest,
 *      切子页只挂拆驱动栈(毫秒), 不再各建一个 SceneManager 重新解析 14 MB;
 *   2. rig_map 的三个写入方(方向/参数、carriage_members、零点三元组)同处一页,
 *      统一走 rigWriter 的"读盘→打补丁→写"并做并发检测。
 *
 * 驱动栈互斥: 运动模式与演示子页用离线栈(useMotionStack, 人手/播放器写);
 * 标定子页用实时链(useLiveBindings, feed 写)。同一条轴被两边同时写会互相覆盖,
 * 所以切页时先拆后挂, 且拆实时链前必 clearHolds。
 */
import { computed, onBeforeUnmount, provide, ref, shallowRef, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'

import { confirmAction } from '../../composables/confirmService.js'
import DisplayPanel from '../twin/panels/DisplayPanel.vue'
import ViewToolbar from '../twin/scene/ViewToolbar.vue'
import * as api from '../workbench/authoringApi.js'
import ActionDemoPane from './panes/ActionDemoPane.vue'
import CalibPane from './panes/CalibPane.vue'
import ModePane from './panes/ModePane.vue'
import { installAnimHooks } from './devHooks.js'
import { resetRigBaseline } from './rigWriter.js'
import { useAssignMode } from './useAssignMode.js'
import { useLiveBindings } from './useLiveBindings.js'
import { useMotionScene } from './useMotionScene.js'
import { useMotionStack } from './useMotionStack.js'
import './workbench.css'

const MODEL_URL = '/api/3d/assets/models/machine.official-cr5.glb'
const MANIFEST_URL = '/api/3d/assets/models/device-manifest.official-cr5.json'

/** 三个子页; key 即路由 :tab 段 */
const SUBTABS = [
  { key: 'mode', label: '运动模式', hint: '定运动模组 · 运动方式 · 行程范围' },
  { key: 'calib', label: '标定', hint: '连实机 · 零点匹配 · 虚实位置对齐' },
  { key: 'action', label: '演示', hint: '逐条原子动作 · 参数试算 · 模拟播放' },
]
const PANES = { mode: ModePane, calib: CalibPane, action: ActionDemoPane }

const route = useRoute()
const router = useRouter()
const containerRef = ref(null)

const message = ref('')
const showDisplay = ref(false)
const view = ref({ xray: false, wireframe: false, hidden: 0 })
/** 驱动层值变化的版本号(子页重算扳机) */
const valueTick = ref(0)
/** 拖拽中的 HUD 浮字 */
const dragInfo = ref(null)
/** 传输条状态(由 ClipPlayer.onChange 推送) */
const transport = ref({ time: 0, duration: 0, playing: false, speed: 1, stepIndex: 0 })
/** 授权中间件可用性(rig 写回的前提) */
const authoringAvailable = ref(false)
/** 各轴已固化的运动方向快照(JSON of {axis, sign}), 判 dirty 用 */
const axisDirSaved = shallowRef(new Map())
/**
 * 契约代次: 每热重载一次 +1, 标定板按它重挂.
 *
 * 不用 manifest.generatedAt 做这个 key —— 它是秒级 unix 时间戳, 同一秒内连着重跑
 * 两次拿到的是同一个数, 标定板就不会重挂, 于是继续抱着已 dispose 的驱动实例.
 */
const contractTick = ref(0)
/** 标定子页里"已改但未写回"的轴数(离页拦截用) */
const calibDirty = ref(0)

const activeTab = computed(() => {
  const asked = String(route.params.tab || '')
  return PANES[asked] ? asked : 'mode'
})
const activeHint = computed(() => SUBTABS.find((t) => t.key === activeTab.value)?.hint || '')

/**
 * 功能: 面向用户的提示(子页与 composable 共用一条通道).
 * @param {string} text 提示文本
 * @returns {void}
 */
function notify(text) {
  message.value = text
}

/**
 * 功能: 驱动层值变化后的重算扳机.
 *
 * 驱动层的 spec 对象故意不进 Vue 响应式(60 fps 下依赖追踪开销很大), 所以子页的
 * computed 靠读这个计数器来重算。不要"顺手改成 reactive"。
 * @returns {void}
 */
function bumpValue() {
  valueTick.value += 1
}

const scene = useMotionScene({
  containerRef,
  modelUrl: MODEL_URL,
  manifestUrl: MANIFEST_URL,
  quality: 'high',
  onReady: (manifest) => {
    activate(activeTab.value, manifest)
  },
})
const {
  manager, manifest, loading, progress, error, stats, state, swapModel, reloadManifest,
} = scene

const stack = useMotionStack({
  manager,
  notify,
  onValueChange: bumpValue,
  onDrag: (dragState) => {
    if (dragState && transport.value.playing) stack.player.value?.toggle()
    dragInfo.value = dragState
  },
  onTransport: (next) => {
    transport.value = next
  },
})

const live = useLiveBindings({ manager })

const assignMode = useAssignMode({
  manager,
  tools: stack.tools,
  state,
  modelUrl: MODEL_URL,
  swapModel,
  detachStack: stack.detach,
  attachStack: (doc) => {
    axisDirSaved.value = stack.attach(doc)
    bumpValue()
  },
  semanticsOf: () => stack.semantics.value,
  notify,
})

/**
 * 功能: 切换到某个子页 —— 拆掉不需要的驱动栈, 挂上需要的.
 * @param {string} tab 子页 key
 * @param {object} [doc] manifest(初次挂载时由 onReady 传入)
 * @returns {void}
 */
function activate(tab, doc = null) {
  const current = doc || manifest.value
  if (!manager.value || !current) return
  if (tab === 'calib') {
    stack.detach()
    live.attach(current)
  } else {
    live.detach()
    if (!stack.rig.value) {
      axisDirSaved.value = stack.attach(current)
      bumpValue()
    }
  }
}

/**
 * 功能: 热重载绑定契约 —— 重取 manifest, 按新契约重挂驱动栈.
 *
 * 标定写回后必须走这一趟, 否则页面还抱着进页时那份 manifest: 写盘与重跑都成功了,
 * 画面却仍按旧零点摆, 而且**毫无报错**。原先靠提示"刷新页面加载新契约"绕过去,
 * 但没人会为改一个零点去刷新, 于是"标完不生效"成了常态。
 *
 * 与指认模式的 exit() 同一套路(重跑 → 重取契约 → 重挂栈), 只是跳过 GLB 换装 ——
 * 标定只动 sign/zero_offset_mm/range_mm 三个数, 几何一个顶点都没变。
 *
 * ⚠ 必须显式先 detach: activate() 里的 `if (!stack.rig.value)` 守卫会让"已挂着的
 * 栈"整个跳过重挂, 新契约就进不去 —— 那正是本函数要修的病。
 * @returns {Promise<void>} 完成
 */
async function refreshContract() {
  if (!manager.value || state.disposed === true) return
  try {
    const doc = await reloadManifest()
    if (state.disposed === true) return
    manifest.value = doc
    stack.detach()
    live.detach()
    activate(activeTab.value, doc)
    contractTick.value += 1
    bumpValue()
    notify('绑定契约已热重载, 新标定即时生效')
  } catch (err) {
    notify(`重载契约失败: ${err?.message || err} —— 请手动刷新页面`)
  }
}

/**
 * 功能: 标定子页未写回改动的离页拦截.
 *
 * 标定改的是 manifest 内存态, 离页即散: 不拦一下, 刚做完的目视对齐会静默丢掉,
 * 而页面不会有任何异样。
 * @returns {Promise<boolean>} 是否放行
 */
async function confirmLeaveCalib() {
  if (calibDirty.value < 1) return true
  return await confirmAction({
    title: '放弃未写回的标定改动',
    message: [
      `${calibDirty.value} 根轴已改但未写回 rig_map。`,
      '这些值只存在于本页内存 —— 离开本页即丢失, 流程演示与刷新后都不会生效。',
    ],
    confirmText: '放弃改动',
    cancelText: '留在本页',
  })
}

// 子页间切换(同一组件, 只换 :tab 段)
onBeforeRouteUpdate(async (to) => {
  if (activeTab.value !== 'calib' || to.params.tab === 'calib') return true
  return await confirmLeaveCalib()
})

// 离开动作台(去别的工作台/后退)
onBeforeRouteLeave(async () => {
  if (activeTab.value !== 'calib') return true
  return await confirmLeaveCalib()
})

// 子页切换: 指认模式中途不允许换页(整栈已换成 raw 模型), 先退回去
watch(activeTab, async (tab, previous) => {
  if (tab === previous) return
  if (assignMode.assign.value) await assignMode.cancel()
  if (state.disposed) return
  activate(tab)
})

/**
 * 功能: 观察工具分发.
 * @param {string} action 动作
 * @param {*} [payload] 参数
 * @returns {void}
 */
function onTool(action, payload) {
  const kit = stack.tools.value
  if (!kit) return
  const selected = assignMode.assign.value ? assignMode.meshes() : []
  if (action === 'view') kit.setView(payload)
  else if (action === 'reset') kit.resetView()
  else if (action === 'showAll') notify(`已还原 ${kit.showAll()} 个对象`)
  else if (action === 'hide') {
    notify(`已隐藏 ${kit.hide(selected)} 个对象`)
    assignMode.pick(null, false)
  } else if (action === 'isolate') {
    notify(`已隔离, 隐藏了 ${kit.isolate(selected)} 个对象`)
  } else if (action === 'xray') view.value.xray = kit.setXray(payload, selected)
  else if (action === 'wireframe') view.value.wireframe = kit.setWireframe(payload)
  view.value.hidden = kit._hidden.size
}

api.probeAuthoring().then((ok) => {
  if (state.disposed === false) authoringAvailable.value = ok
})
resetRigBaseline()

// 验收钩子(仅开发构建): 动作台额外暴露语义列表与指认模式
const uninstallHooks = installAnimHooks({
  manager,
  stack,
  transport,
  currentName: () => '',
  extra: {
    semantics: () => stack.semantics.value.map(
      (entry) => ({ id: entry.id, category: entry.category, nodes: entry.glbNodes.length }),
    ),
    resolveFailed: () => stack.semantics.value.filter((e) => e.resolveFailed).map((e) => e.id),
    paintActive: () => Boolean(stack.paint.value?.active),
  },
})
if (import.meta.env.DEV) {
  window.__motionAssign = {
    state: () => assignMode.assign.value?.phase || 'motion',
    count: () => assignMode.count.value,
    start: (id) => assignMode.start(id),
    save: () => assignMode.save(),
    cancel: () => assignMode.cancel(),
    pick: (key, add) => assignMode.pick(key, add),
  }
}

onBeforeUnmount(() => {
  uninstallHooks()
  if (import.meta.env.DEV) delete window.__motionAssign
  // 双清理兜底: 指认中途离开也不留监听/材质/指针捕获(两个 teardown 都幂等)
  assignMode.teardown()
  stack.detach()
  live.detach()
})

/**
 * 功能: 记录标定子页未写回的轴数(离页拦截的判据).
 * @param {number} count 轴数
 * @returns {void}
 */
function setCalibDirty(count) {
  calibDirty.value = Number(count) || 0
}

// 子页通过 inject 拿到共享上下文, 免去一长串 props 透传
provide('motionWorkbench', {
  manager,
  manifest,
  state,
  stack,
  live,
  assignMode,
  transport,
  valueTick,
  authoringAvailable,
  axisDirSaved,
  contractTick,
  notify,
  bumpValue,
  refreshContract,
  setCalibDirty,
})

/**
 * 功能: 子页签跳转(保留 :target 段清空, 避免带着上一个子页的目标).
 * @param {string} key 子页 key
 * @returns {void}
 */
function goTab(key) {
  router.push(`/3d/motion/${key}`)
}
</script>

<template>
  <!-- docked: 子页签栏与左栏焊成一块. 条件与下面 nav 的 v-if 必须一致 ——
       签栏不在时左栏要回到原来的 top, 否则顶上会空出一条 -->
  <div :class="['mw', { 'mw--docked': !error && !assignMode.assign.value }]">
    <div ref="containerRef" class="mw__canvas" />

    <!-- 子页签: 指认模式中隐藏(整栈已换成 raw 模型, 此时切页没有意义) -->
    <nav v-if="!error && !assignMode.assign.value" class="mw__subtabs" aria-label="动作工作台子页">
      <button
        v-for="tab in SUBTABS"
        :key="tab.key"
        type="button"
        :class="['mw__subtab', { 'mw__subtab--on': activeTab === tab.key }]"
        :title="tab.hint"
        :aria-current="activeTab === tab.key ? 'page' : undefined"
        @click="goTab(tab.key)"
      >{{ tab.label }}</button>
    </nav>

    <ViewToolbar
      v-if="!error"
      :has-selection="assignMode.assign.value ? assignMode.count.value > 0 : false"
      :xray="view.xray"
      :wireframe="view.wireframe"
      :hidden-count="view.hidden"
      :show-helpers-toggle="false"
      :display-open="showDisplay"
      @view="onTool('view', $event)"
      @reset="onTool('reset')"
      @hide="onTool('hide')"
      @isolate="onTool('isolate')"
      @show-all="onTool('showAll')"
      @xray="onTool('xray', $event)"
      @wireframe="onTool('wireframe', $event)"
      @display="showDisplay = !showDisplay"
    />

    <!-- 指认滑车成员模式: 顶部操作条 -->
    <div v-if="assignMode.assign.value && !error" class="mw__banner">
      <span class="mw__bannerTitle">指认滑车成员 · {{ assignMode.assign.value.label }}</span>
      <template v-if="assignMode.assign.value.phase === 'active'">
        <span class="mw__bannerHint">
          点选随该轴移动的零件(Ctrl 加选, 选装配根=整组随动), 已选 {{ assignMode.count.value }} 个
        </span>
        <button
          type="button"
          class="mw__btn"
          :disabled="!assignMode.count.value"
          @click="assignMode.save()"
        >写回 rig_map 并重跑</button>
        <button type="button" class="mw__btn mw__btn--ghost" @click="assignMode.cancel()">取消</button>
      </template>
      <span v-else-if="assignMode.assign.value.phase === 'saving'" class="mw__bannerHint">写回中…</span>
      <span v-else-if="assignMode.assign.value.phase === 'rebuilding'" class="mw__bannerHint">
        全链重跑中(约1分钟)… {{ assignMode.runningStep.value }}
      </span>
      <span v-else class="mw__bannerHint">正在切换模型…</span>
    </div>

    <DisplayPanel
      v-if="showDisplay && manager"
      :manager="manager"
      :stats="stats"
      :anchor-right="342"
      @close="showDisplay = false"
    />

    <!-- 子页: 指认模式下整体隐藏(驱动栈已拆) -->
    <component
      :is="PANES[activeTab]"
      v-if="!error && !loading && !assignMode.assign.value"
    />

    <!-- 拖拽浮字 -->
    <div v-if="dragInfo" class="mw__dragHud" :class="{ 'mw__dragHud--blocked': dragInfo.blocked }">
      <template v-if="dragInfo.blocked">
        {{ dragInfo.axisId }} · 视角与该轴近平行，先旋转视角再拖（Esc 取消）
      </template>
      <template v-else>
        {{ dragInfo.axisId }} · {{ Number(dragInfo.mm).toFixed(1) }} mm（Esc 取消）
      </template>
    </div>

    <p v-if="message" class="mw__toast">{{ message }}</p>

    <div v-if="loading" class="mw__mask">加载模型… {{ Math.round(progress * 100) }}%</div>
    <div v-if="error" class="mw__mask mw__mask--err">初始化失败：{{ error }}</div>
    <span v-else class="mw__srOnly">{{ activeHint }}</span>
  </div>
</template>

<style scoped>
.mw__srOnly {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
</style>
