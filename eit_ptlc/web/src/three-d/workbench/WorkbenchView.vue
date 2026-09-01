<script setup>
/**
 * 功能: 装配工作台 —— 人机协作的授权界面.
 *
 * 工作流: 你在三维里点选零件 → 标记删/留/减面 → 保存(写回 prune_list.yaml)
 *         → 重跑管线(约 60 秒) → 模型热重载, 看结果 → 不满意接着改.
 *
 * 关键设计: 网页只写"意图"(一份可读的 yaml 名单), 不写"产物"(GLB).
 * 所以图纸更新后重新导出, 重跑一遍即可, 之前的删减工作不作废.
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { applyRobotHomePose } from '../anim/robotHomePose.js'
import ContextMenu from '../common/ContextMenu.vue'
import { createRightClickTracker } from '../common/rightClick.js'
import { SceneManager } from '../twin/scene/SceneManager.js'
import ViewToolbar from '../twin/scene/ViewToolbar.vue'
import { ViewTools } from '../twin/scene/ViewTools.js'
import * as api from './authoringApi.js'
import { OFFICIAL_CR5_NAMES } from './officialCr5Names.js'
import { PartIndex } from './PartIndex.js'
import PartInspector from './PartInspector.vue'
import PartTree from './PartTree.vue'
import {
  compilePruneRules,
  evalEffectiveDeletes,
  previewStatus,
  ruleFingerprint,
  sourceStamp,
} from './pruneEval.js'
import RebuildPanel from './RebuildPanel.vue'
import RuleSelector from './RuleSelector.vue'
import { markStateOf, MARK_STYLES, restoreMarks, SelectionModel } from './selectionModel.js'
import { WorkbenchScene } from './WorkbenchScene.js'
import { parseYaml, patchPruneList } from './yamlPatch.js'

/** 工作台加载未删减的原始模型(仅机械臂已换官方件) —— 只有它保留了全部节点和真实零件名 */
const RAW_MODEL_URL = '/api/3d/assets/models/raw.glb'

const containerRef = ref(null)
/** 层级树组件, 三维点选后调它的 reveal() 定位 */
const treeRef = ref(null)
/** 重跑面板, 基线过期告警条借它发起窄重跑(进度显示仍归面板一处) */
const rebuildRef = ref(null)
const manager = shallowRef(null)
const scene = shallowRef(null)
const tools = shallowRef(null)
const index = shallowRef(null)
const model = shallowRef(new SelectionModel())

/** 观察工具的开关状态 */
const view = ref({ xray: false, wireframe: false, hidden: 0 })
/** 被手动隐藏(整棵子树)的零件键, 供层级树画闭眼图标 */
const hiddenKeys = ref(new Set())
/** 白模模式(默认开): 机身白 + 删减件着色; 关 = 管线材质对照(raw 已赋材质) */
const whiteMode = ref(true)

/** 右键菜单状态({x, y, items} | null)与单击/拖拽判定器 */
const menu = ref(null)
const rightClick = createRightClickTracker()
/** 右键按下瞬间捕获的目标零件键 —— contextmenu 在 pointerup 之后触发, 那时 hovered 已被清空 */
let menuTargetKey = null

const loading = ref(true)
const progress = ref(0)
const error = ref('')
const authoringAvailable = ref(false)
const saving = ref(false)
const message = ref('')

/** 触发视图重算的版本号(选择模型是普通对象, 不走 Vue 响应式) */
const tick = ref(0)
/** 原始 prune_list.yaml 原文, 保存时在其上打补丁以保住注释 */
let pruneText = ''
/** prune_list.yaml 编译出的删减规则(正则+尺寸阈值), 仅在基线不可用时退化用 */
let pruneRules = null
/** 管线产出的标红基线(work/prune_preview.json), 与真实删减同一份裁决 */
const baseline = shallowRef(null)
/** 基线跟不跟得上当前 prune_list.yaml 的判定, 见 pruneEval.previewStatus */
const baselineState = ref({ state: 'missing', reason: '基线尚未读取' })
let disposed = false

/** 基线不可用时预览退化为近似, 顶栏挂告警 —— 缺戳不许判绿 */
const previewApproximate = computed(() => baselineState.value.state !== 'ok')

/** 视图模式: 全部零件(all) / 减配后(reduced) */
const viewMode = ref('all')

const counts = computed(() => {
  tick.value // 依赖版本号
  return model.value.counts()
})

/**
 * 有效删除集: 管线基线 + 用户未保存的显式标记(减配视图与统计条共用).
 * 基线过期/缺失时传 null, evalEffectiveDeletes 退化为按规则近似, 由告警条如实标注.
 */
const effectiveDeletes = computed(() => {
  tick.value
  if (!index.value) return null
  const usable = baselineState.value.state === 'ok' ? baseline.value : null
  return evalEffectiveDeletes(index.value, model.value, pruneRules, usable)
})

const estimate = computed(() => {
  tick.value
  return index.value ? index.value.estimate(model.value, effectiveDeletes.value) : null
})

const selectedNames = computed(() => {
  tick.value
  return [...model.value.selected]
})

const selectedPart = computed(() =>
  selectedNames.value.length === 1 ? index.value?.get(selectedNames.value[0]) : null,
)

/**
 * 功能: 层级树色点颜色 —— 与三维着色同一判定(markStateOf)与同一色表(MARK_STYLES).
 *
 * 覆盖 PartTree 的默认色点逻辑(那个只认显式标记): 正则/尺寸规则命中的零件
 * 同样带红点, 树与三维必然同色.
 * @param {string} key 零件索引键
 * @returns {string|null} CSS 颜色
 */
function dotColorOf(key) {
  const state = markStateOf(model.value, effectiveDeletes.value, key)
  return state ? MARK_STYLES[state].color : null
}

/**
 * 功能: 千分位格式化.
 * @param {number} value 数值
 * @returns {string} 结果
 */
function fmt(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

/**
 * 功能: 处理三维里的拾取.
 * @param {string|null} name 零件名
 * @param {boolean} additive 是否加选
 * @returns {void}
 */
function handlePick(name, additive) {
  if (!name) {
    if (!additive) model.value.clearSelection()
  } else if (additive) {
    model.value.toggle(name)
  } else {
    model.value.select([name])
  }
  tick.value += 1
  // 在层级树里展开定位到点中的零件(加选时定位最后点的那个)
  if (name) treeRef.value?.reveal(name)
}

/**
 * 功能: 给当前选中集打标记.
 * @param {string|null} mark 标记种类; null 表示清除
 * @returns {void}
 */
function mark(markType) {
  const n = model.value.markSelected(markType)
  if (n) {
    // 标完就取消选中: 选中态的高亮盖在标记色之上, 不清掉就看不见删减效果
    model.value.clearSelection()
    const label = markType
      ? { delete: '删除', keep: '保留', decimate: '减面' }[markType]
      : '待定'
    message.value = `已标记 ${n} 个零件为「${label}」`
  } else {
    message.value = '请先选中零件'
  }
  tick.value += 1
}

/**
 * 功能: 按规则批量选择.
 * @param {object} rule 规则
 * @returns {void}
 */
function applyRule(rule) {
  const hits = index.value?.query(rule) || []
  model.value.select(hits)
  message.value = `规则命中 ${hits.length} 个零件`
  tick.value += 1
}

/**
 * 功能: 撤销上一次标记操作.
 * @returns {void}
 */
function undo() {
  message.value = model.value.undo() ? '已撤销' : '没有可撤销的操作'
  tick.value += 1
}

/**
 * 功能: 收集一组零件键对应的子树网格.
 * @param {string[]} keys 零件索引键数组
 * @returns {Array} 网格数组(已去重)
 */
function meshesOf(keys) {
  const idx = index.value
  if (!idx) return []
  const found = new Set()
  for (const key of keys) {
    const part = idx.get(key)
    part?.object?.traverse((child) => {
      if (child.isMesh) found.add(child)
    })
  }
  return [...found]
}

/**
 * 功能: 取当前选中零件对应的网格 —— 隐藏/隔离/透视都以它们为重点.
 *
 * 按选中实例的整棵子树收集(与选中高亮同口径). 不能按名字匹配: 从树上选中
 * 装配(Group)时, 子孙网格的名字与装配名毫无关系, 名字匹配是 0 命中 ——
 * 现象就是"隐藏一个装配, 实际隐藏 0 个对象".
 * @returns {Array} 网格数组
 */
function selectedMeshes() {
  return meshesOf(selectedNames.value)
}

/**
 * 功能: 工具栏动作分发.
 * @param {string} action 动作名
 * @param {*} [payload] 附带参数
 * @returns {void}
 */
function onTool(action, payload) {
  const kit = tools.value
  if (!kit) return

  if (action === 'view') kit.setView(payload)
  else if (action === 'reset') kit.resetView()
  else if (action === 'hide') {
    message.value = `已隐藏 ${kit.hide(selectedMeshes())} 个对象`
    // 隐藏即"移开视线": 保留选中只会让工具栏与右侧面板指向看不见的零件
    model.value.clearSelection()
  }
  else if (action === 'isolate') message.value = `已隔离, 隐藏了 ${kit.isolate(selectedMeshes())} 个对象`
  else if (action === 'showAll') {
    message.value = `已还原 ${kit.showAll()} 个对象`
    // 全显按 ViewTools 自己的台账恢复可见性, 可能点亮减配视图藏起的网格 —— 重刷压回
    scene.value?.refresh()
  }
  else if (action === 'xray') view.value.xray = kit.setXray(payload, selectedMeshes())
  else if (action === 'wireframe') view.value.wireframe = kit.setWireframe(payload)
  refreshHiddenState()
}

/**
 * 功能: 手动隐藏状态变化后, 重算工具栏计数与层级树的闭眼集合.
 *
 * 只统计 ViewTools 的手动隐藏台账 —— 「减配后」视图藏起的删减件由树上的
 * 标记色点表达, 不画闭眼(否则整机标删几百个紧固件后满树都是眼睛).
 * @returns {void}
 */
function refreshHiddenState() {
  const kit = tools.value
  const idx = index.value
  view.value.hidden = kit ? kit._hidden.size : 0
  hiddenKeys.value = kit && idx && kit._hidden.size ? idx.hiddenKeys(kit._hidden) : new Set()
  tick.value += 1
}

/**
 * 功能: 恢复单个零件的显示(层级树闭眼图标点击).
 * @param {string} key 零件索引键
 * @returns {void}
 */
function handleUnhide(key) {
  const kit = tools.value
  if (!kit) return
  const n = kit.show(meshesOf([key]))
  const part = index.value?.get(key)
  const label = part?.chinese || part?.name || key
  message.value = n ? `已恢复显示「${label}」` : `「${label}」不在手动隐藏名单里`
  refreshHiddenState()
}

/**
 * 功能: 读管线产出的标红基线, 并判它跟不跟得上当前的 prune_list.yaml.
 *
 * 读不到不致命(全新工作区、或还没按新管线重跑过 raw): 预览退化为按规则近似, 顶栏
 * 挂告警如实标注 —— 与片段陈旧检测同一约定, 缺戳不许判绿.
 * @returns {Promise<void>}
 */
async function loadBaseline() {
  try {
    baseline.value = JSON.parse(await api.readFile('prune_preview'))
  } catch {
    baseline.value = null
  }
  baselineState.value = previewStatus(baseline.value, sourceStamp(pruneText))
}

/**
 * 功能: 只重跑工作台原始模型那两步, 把标红基线刷新到当前规则.
 * @returns {void}
 */
function rebuildBaseline() {
  rebuildRef.value?.rebuild(['raw-swap', 'raw'])
}

/**
 * 功能: 保存标记到 prune_list.yaml.
 * @returns {Promise<void>}
 */
async function save() {
  saving.value = true
  message.value = ''
  try {
    // 写盘用 glTF 原名(three 名与 Blender 侧对不上, 硬约束 27)
    const next = patchPruneList(pruneText, model.value, (name) =>
      index.value?.savedNameOf?.(name) ?? name,
    )
    const before = ruleFingerprint(parseYaml(pruneText))
    await api.writeFile('prune_list', next)
    const parsed = parseYaml(next)
    pruneText = next
    pruneRules = compilePruneRules(parsed)
    // 保存只动 explicit_* 三段名单时基线依然作数(它的规则档裁决不依赖那几段, 显式那档
    // 由 model.marks 实时算), 把戳跟着推到新文本上, 免得每存一次预览就退化成近似一次.
    // 规则档真被改了才让戳失配, 顶栏照常挂"预览为近似".
    if (baseline.value && baselineState.value.state === 'ok' && before === ruleFingerprint(parsed)) {
      baseline.value = { ...baseline.value, source_stamp: sourceStamp(next) }
    }
    baselineState.value = previewStatus(baseline.value, sourceStamp(next))
    message.value = `已保存到 prune_list.yaml（删除 ${counts.value.delete} · 保留 ${counts.value.keep} · 减面 ${counts.value.decimate}）`
  } catch (err) {
    message.value = `保存失败: ${err.message}`
  } finally {
    saving.value = false
  }
}

/**
 * 功能: 选中零件并把镜头对过去.
 * @param {string} name 零件名
 * @returns {void}
 */
function focusPart(name) {
  model.value.select([name])
  scene.value?.focus(name)
  tick.value += 1
}

// 切换「全部零件 / 减配后」. 切换前先还原手动隐藏/隔离: ViewTools 与场景的
// 两套可见性台账各记各的, 在干净状态下切换才不会互相污染.
watch(viewMode, (mode) => {
  const kit = tools.value
  if (kit && kit._hidden.size) {
    kit.showAll()
    refreshHiddenState()
    message.value = '已还原手动隐藏的对象'
  }
  scene.value?.setViewMode(mode)
})

// 切换「白模 / 原色」—— 场景侧自带台账时序处理(先还原着色再翻基线)
watch(whiteMode, (on) => {
  scene.value?.setWhiteMode(on)
})

// -- 右键快捷菜单 ----------------------------------------------------------

/**
 * 功能: 组装装配台的右键菜单项(全部复用现有动作).
 * @param {string} key 被右击的零件键
 * @returns {Array} 菜单项
 */
function buildWbMenu(key) {
  const hasSelection = selectedNames.value.length > 0
  return [
    { key: 'mark-delete', label: '标记删除', danger: true, action: () => mark('delete') },
    { key: 'mark-keep', label: '标记保留', action: () => mark('keep') },
    { key: 'mark-decimate', label: '标记减面', action: () => mark('decimate') },
    { key: 'mark-clear', label: '清除标记', action: () => mark(null) },
    { divider: true },
    { key: 'hide', label: '隐藏', disabled: !hasSelection, action: () => onTool('hide') },
    { key: 'isolate', label: '隔离', disabled: !hasSelection, action: () => onTool('isolate') },
    // 聚焦走 scene.focus 而不是 focusPart: 后者会把多选压成单选
    { key: 'focus', label: '飞过去看', action: () => scene.value?.focus(key) },
    { key: 'reveal', label: '在树中定位', action: () => treeRef.value?.reveal(key) },
  ]
}

/**
 * 功能: canvas 的 pointerdown —— 喂判定器, 右键时捕获当下悬停的零件.
 * @param {PointerEvent} event 指针事件
 * @returns {void}
 */
function onCanvasPointerDown(event) {
  rightClick.onPointerDown(event)
  if (event.button === 2) menuTargetKey = scene.value?.hovered || null
}

/**
 * 功能: canvas 的 contextmenu 处理 —— 右键单击零件弹菜单, 拖拽平移不弹.
 * @param {MouseEvent} event contextmenu 事件
 * @returns {void}
 */
function onCanvasContextMenu(event) {
  event.preventDefault()
  const key = menuTargetKey
  menuTargetKey = null
  if (!rightClick.shouldOpen(event) || !key) return
  // 右击未选中的零件 = 先选中它(已选中者保持多选, 菜单作用于整个选中集)
  if (!model.value.selected.has(key)) {
    model.value.select([key])
    tick.value += 1
    treeRef.value?.reveal(key)
  }
  menu.value = { x: event.clientX, y: event.clientY, items: buildWbMenu(key) }
}

onMounted(async () => {
  authoringAvailable.value = await api.probeAuthoring()
  if (disposed === true) return

  try {
    const instance = new SceneManager(containerRef.value, {
      // 原始模型有两千多个绘制调用, bloom/SSAO 等全屏特效是纯负担; 但选中/悬停
      // 需要与材质台一致的描边 —— lite 档 = 仅 outline 的最小后期链
      quality: 'lite',
      autoDegrade: false,
    })
    manager.value = instance

    // 创作页无 manifest 构建戳可用 —— 每次强刷, 保证重跑管线后立即见到新模型
    const result = await instance.loadMachineModel(`${RAW_MODEL_URL}?t=${Date.now()}`, (f) => {
      progress.value = f
    })
    if (disposed === true) return

    // 中文原名让层级树可读 —— 拼音 slug 认起来太费劲
    let chinese = new Map()
    if (authoringAvailable.value) {
      try {
        chinese = PartIndex.parseNamesCsv(await api.readFile('names_csv'))
        if (disposed === true) return
      } catch {
        // 没有 names.csv 不致命, 只是树里少了中文列
      }
    }
    for (const [en, zh] of OFFICIAL_CR5_NAMES) {
      if (!chinese.has(en)) chinese.set(en, zh)
    }

    index.value = new PartIndex(result.root, chinese)

    // 机械臂摆到折叠工作姿态(与材质台/演示一致). 必须在 PartIndex 之后:
    // 索引里的 sizeMm 是世界包围盒口径, 要与管线的零位测量一致
    await applyRobotHomePose(instance)
    if (disposed === true) return

    // 恢复上次的标记, 让工作可以分多次做完; 同时把正则/尺寸规则编译好供退化路径用
    if (authoringAvailable.value) {
      try {
        pruneText = await api.readFile('prune_list')
        if (disposed === true) return
        const parsed = parseYaml(pruneText)
        pruneRules = compilePruneRules(parsed)
        const restored = restoreMarks(parsed, model.value, index.value)
        if (restored) message.value = `已恢复上次的 ${restored} 条标记`
      } catch (err) {
        message.value = `读取 prune_list.yaml 失败: ${err.message}`
      }
      await loadBaseline()
      if (disposed === true) return
    }

    scene.value = new WorkbenchScene({
      manager: instance,
      index: index.value,
      model: model.value,
      onPick: handlePick,
      getEffectiveDeletes: () => effectiveDeletes.value,
      whiteMode: whiteMode.value,
    })
    tools.value = new ViewTools(instance)
    tick.value += 1

    // 右键快捷菜单: 单击(<4px)弹菜单, 按住拖拽仍是 camera-controls 的平移
    instance.canvas.addEventListener('pointerdown', onCanvasPointerDown)
    instance.canvas.addEventListener('contextmenu', onCanvasContextMenu)

    // 验收脚本钩子(verify_workbench.py 用), 生产构建不暴露
    if (import.meta.env.DEV) {
      window.__wb = {
        quality: () => instance.quality,
        hasEffects: () => Boolean(instance.effects),
        whiteMode: () => whiteMode.value,
        setWhiteMode: (on) => {
          whiteMode.value = Boolean(on)
        },
        markState: (key) => markStateOf(model.value, effectiveDeletes.value, key),
        meshColorOf: (key) => {
          const part = index.value?.get(key)
          let hex = null
          part?.object?.traverse((child) => {
            if (hex === null && child.isMesh && child.material && !Array.isArray(child.material)) {
              hex = child.material.color.getHex()
            }
          })
          return hex
        },
        // 拖拽描边挂起的验收断言: 按下应两项归零, 松手 sel 恢复
        outlineSizes: () => ({
          hover: instance.effects?.hoverOutline?.selection?.size ?? 0,
          sel: instance.effects?.selectOutline?.selection?.size ?? 0,
        }),
        fps: () => instance.fps,
      }
    }
  } catch (err) {
    if (disposed === true) return
    error.value = err?.message || String(err)
    console.error('[workbench] 初始化失败', err)
  } finally {
    if (disposed === false) loading.value = false
  }
})

onBeforeUnmount(() => {
  disposed = true
  const canvas = manager.value?.canvas
  canvas?.removeEventListener('pointerdown', onCanvasPointerDown)
  canvas?.removeEventListener('contextmenu', onCanvasContextMenu)
  tools.value?.dispose()
  scene.value?.dispose()
  manager.value?.dispose()
  manager.value = null
})
</script>

<template>
  <div class="wb">
    <div ref="containerRef" class="wb__canvas" />

    <!-- 装配台不调显示效果(显示调整统一归材质侧), 工具条不出「显示」入口 -->
    <ViewToolbar
      v-if="!error"
      :has-selection="selectedNames.length > 0"
      :xray="view.xray"
      :wireframe="view.wireframe"
      :hidden-count="view.hidden"
      :show-helpers-toggle="false"
      :show-display-toggle="false"
      @view="onTool('view', $event)"
      @reset="onTool('reset')"
      @hide="onTool('hide')"
      @isolate="onTool('isolate')"
      @show-all="onTool('showAll')"
      @xray="onTool('xray', $event)"
      @wireframe="onTool('wireframe', $event)"
    />

    <!-- 左：零件层级树(独占整列) -->
    <aside v-if="!error" class="wb__left">
      <PartTree
        v-if="index"
        ref="treeRef"
        :index="index"
        :model="model"
        :tick="tick"
        :hidden-keys="hiddenKeys"
        :dot-color-of="dotColorOf"
        @focus="focusPart"
        @unhide="handleUnhide"
      />
    </aside>

    <!-- 右：选中详情 + 规则批选 + 重跑 -->
    <aside v-if="!error" class="wb__right">
      <PartInspector
        :part="selectedPart"
        :count="selectedNames.length"
        :model="model"
        :tick="tick"
        @mark="mark"
        @undo="undo"
      />
      <RuleSelector :index="index" @apply="applyRule" />
      <RebuildPanel
        ref="rebuildRef"
        :available="authoringAvailable"
        :saving="saving"
        :counts="counts"
        :estimate="estimate"
        @save="save"
      />
    </aside>

    <!-- 基线不可用时红色就只是近似, 必须说出来: 静默的近似正是这套预览过去骗人的方式 -->
    <div v-if="authoringAvailable && !error && previewApproximate" class="wb__stale">
      <span class="wb__stale-tag">预览为近似</span>
      <span class="wb__stale-text">{{ baselineState.reason }}</span>
      <button type="button" class="wb__stale-btn" @click="rebuildBaseline">
        刷新工作台原始模型（约 2 分钟）
      </button>
    </div>

    <!-- 顶部：视图切换 + 白模切换 + 规模计数器 -->
    <div v-if="estimate && !error" class="wb__meter">
      <span class="wb__seg" role="group" aria-label="视图模式">
        <button
          type="button"
          class="wb__seg-btn"
          :class="{ 'wb__seg-btn--on': viewMode === 'all' }"
          @click="viewMode = 'all'"
        >全部零件</button>
        <button
          type="button"
          class="wb__seg-btn"
          :class="{ 'wb__seg-btn--on': viewMode === 'reduced' }"
          title="隐藏将被删减的零件（口径 = 显式标记 + 正则规则 + 尺寸阈值；减面数字按显式标记近似）"
          @click="viewMode = 'reduced'"
        >减配后</button>
      </span>
      <span class="wb__seg" role="group" aria-label="展示模式">
        <button
          type="button"
          class="wb__seg-btn"
          :class="{ 'wb__seg-btn--on': whiteMode }"
          title="机身白模，删除/保留/减面按树色点同色着色；减面与局部切割的实际效果以重跑管线为准"
          @click="whiteMode = true"
        >白模</button>
        <button
          type="button"
          class="wb__seg-btn"
          :class="{ 'wb__seg-btn--on': !whiteMode }"
          title="CAD 原色对照，不做删减着色（标记状态看树色点与计数）"
          @click="whiteMode = false"
        >原色</button>
      </span>
      <span>网格 <b>{{ fmt(estimate.meshes) }}</b> → <b class="wb__after">{{ fmt(estimate.afterMeshes) }}</b></span>
      <span>三角形 <b>{{ fmt(estimate.triangles) }}</b> → <b class="wb__after">{{ fmt(estimate.afterTriangles) }}</b></span>
      <span v-if="counts.delete" class="wb__badge wb__badge--del">删 {{ counts.delete }}</span>
      <span v-if="counts.keep" class="wb__badge wb__badge--keep">留 {{ counts.keep }}</span>
      <span v-if="counts.decimate" class="wb__badge wb__badge--dec">减面 {{ counts.decimate }}</span>
    </div>

    <ContextMenu v-if="menu" v-bind="menu" @close="menu = null" />

    <p v-if="message && !error" class="wb__message">{{ message }}</p>

    <div v-if="loading" class="wb__overlay">
      <div class="wb__spinner" />
      <p>正在加载原始模型（2271 个节点，约 52 MB）…</p>
      <div class="wb__bar"><div :style="{ width: `${Math.round(progress * 100)}%` }" /></div>
    </div>

    <div v-if="error" class="wb__overlay wb__overlay--error">
      <p class="wb__err-title">工作台加载失败</p>
      <p class="wb__err-detail">{{ error }}</p>
      <p class="wb__err-hint">
        需要把原始模型放到 three_d/models/raw.glb。<br />
        运行：<code>copy work\TLC_she_bei_zong_zhuang_named.raw.glb app\public\models\raw.glb</code>
      </p>
    </div>
  </div>
</template>

<style scoped>
.wb {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
}

.wb__canvas {
  position: absolute;
  inset: 0;
}

.wb__left,
.wb__right {
  position: absolute;
  /* 与视图工具栏上缘对齐, 四周统一留白 12px. */
  top: 12px;
  bottom: 12px;
  z-index: 10;
  width: 300px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: hidden;
}

.wb__left {
  left: 12px;
}
.wb__right {
  right: 12px;
  /* 详情/批选/重建三卡叠放, 矮窗口下会超高, 整列滚动兜底 */
  overflow-y: auto;
  scrollbar-width: thin;
}

.wb__meter {
  position: absolute;
  /* 视图工具栏(ViewToolbar)占住了 top:12px 的中间上方, 统计条降到它下面, 恰与左右面板顶对齐 */
  top: 58px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 11;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 7px 16px;
  border-radius: 8px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  color: var(--text-mid);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.wb__meter b {
  color: var(--text);
  font-weight: 500;
}

/* 基线过期告警: 压在统计条正下方, 与它同宽同风格但用警示色 —— 要一眼看见, 又不遮画面 */
.wb__stale {
  position: absolute;
  top: 96px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 11;
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: min(760px, calc(100% - 640px));
  padding: 7px 14px;
  border-radius: 8px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid #f4b740;
  color: var(--text-mid);
  font-size: 12px;
}

.wb__stale-tag {
  flex: none;
  padding: 1px 7px;
  border-radius: 5px;
  background: #f4b740;
  color: #1b1b1b;
  font-size: 11px;
  font-weight: 600;
}

.wb__stale-text {
  min-width: 0;
}

.wb__stale-btn {
  flex: none;
  padding: 3px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 11px;
  cursor: pointer;
}

.wb__stale-btn:hover {
  border-color: #f4b740;
}

.wb__seg {
  display: inline-flex;
  padding: 2px;
  border-radius: 7px;
  background: var(--surface);
  border: 1px solid var(--border);
}

.wb__seg-btn {
  padding: 2px 9px;
  border: none;
  border-radius: 5px;
  background: none;
  color: var(--text-mid);
  font-size: 11px;
  cursor: pointer;
}

.wb__seg-btn--on {
  background: var(--accent-soft);
  color: var(--accent-bright);
}

.wb__after {
  color: var(--ok) !important;
}

.wb__badge {
  padding: 1px 7px;
  border-radius: 9px;
  font-size: 11px;
}
.wb__badge--del {
  background: var(--err-soft);
  color: var(--err-bright);
}
.wb__badge--keep {
  background: var(--ok-soft);
  color: var(--ok-bright);
}
.wb__badge--dec {
  background: var(--warn-soft);
  color: var(--warn);
}


.wb__message {
  position: absolute;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 11;
  margin: 0;
  padding: 6px 14px;
  border-radius: 7px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 12px;
}

.wb__overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: var(--curtain);
  color: var(--text);
  font-size: 13px;
}

.wb__spinner {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  animation: wb-spin 0.9s linear infinite;
}

@keyframes wb-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .wb__spinner {
    animation-duration: 3s;
  }
}

.wb__bar {
  width: 220px;
  height: 3px;
  border-radius: 2px;
  background: var(--border);
  overflow: hidden;
}
.wb__bar > div {
  height: 100%;
  background: var(--accent-gradient);
  transition: width 0.2s ease;
}

.wb__overlay--error {
  color: var(--err-bright);
}
.wb__err-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}
.wb__err-detail {
  margin: 0;
  max-width: 620px;
  text-align: center;
  color: var(--text-bright);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}
.wb__err-hint {
  margin: 0;
  text-align: center;
  color: var(--text-dim);
  line-height: 1.7;
}
.wb__err-hint code {
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--border);
  font-size: 11px;
}
</style>
