/**
 * 功能: 实时页 (/3d/live) 右侧信息坞的状态机 —— 谁在坞里、开着哪一页、收没收起.
 *
 * 为什么不并进 useTwinScene: 那个 composable 被 SimView / MotionWorkbench / CalibPane /
 * WorkbenchView 四家共用, 塞实时页专属的展示态会让四家都背上它.
 *
 * 核心手法: **scope 是从 selectedStation 推导出来的, 不是存的**.
 *   旧实现在 TwinView 里放 showDisplay/showMaterials/showManual 三个布尔量, 互斥靠每个
 *   入口的模板内联表达式手写清零 —— 于是漏掉了组合 (手动+物料能同时开并重叠), 而点空白
 *   画布取消选中时那三个量还是陈的. 改成推导之后, "取消选中"的每一条路径 (点空白画布 →
 *   PickController.onSelect(null) / 点关闭 / 点全局页签) 都自动收敛到全局族, 没有一处
 *   需要手写互斥.
 *
 * 纯逻辑独立成导出函数供 node --test 直接单测 (照 stores/monitorPrefs.js 的仓内惯例).
 */
import { computed, reactive, watch } from 'vue'

import { loadJson, saveJson } from '../../utils/storage.js'

const PREFS_KEY = 'eit_twin_dock'

/** 全局族页签 (未选中工位时) */
export const GLOBAL_TABS = Object.freeze([
  { key: 'machine', label: '工站信息', icon: '⚙', title: '设备侧: 反馈完整度 + 只读实时诊断 + 整机操作' },
  { key: 'viewer', label: '显示信息', icon: '▦', title: '观察侧: 帧率/绘制调用/三角形/画质档' },
  { key: 'materials', label: '物料总览', icon: '⬒', title: '上位机物料账本全量 (只读)' },
])

/** 工位族页签 (选中工位时) */
export const STATION_TABS = Object.freeze([
  { key: 'status', label: '状态', title: '该工位的实时状态' },
  { key: 'actions', label: '操作', title: '该工位可执行的动作与手动控制' },
  { key: 'material', label: '物料', title: '该工位的物料账本 (可改)' },
])

const GLOBAL_TAB_KEYS = new Set(GLOBAL_TABS.map((tab) => tab.key))

/**
 * 功能: 校验并修补持久化的坞偏好.
 *
 * globalTab 只认闭集内的值; 任何越界值 (旧版本遗留的 'manual'、手改 localStorage、
 * JSON 里塞了对象) 一律回落到 machine —— 坞打不开比开错一页更难查.
 * @param {any} raw localStorage 里读出来的原始值
 * @returns {{collapsed: boolean, globalTab: string}} 可安全使用的偏好
 */
export function sanitizeDockPrefs(raw) {
  const src = raw && typeof raw === 'object' ? raw : {}
  const tab = GLOBAL_TAB_KEYS.has(src.globalTab) ? src.globalTab : 'machine'
  return { collapsed: src.collapsed === true, globalTab: tab }
}

/**
 * 功能: 算出某工位当前有哪些页签可用.
 *
 * 无遥测节点的工位 (料架/机架/视觉/工具站) 没有实时状态可显; 动作清单为空的没有操作页.
 * 物料页只在该工位确实管着物料实体时才出现 —— 判定交给调用方传进来, 本函数不认识 manifest.
 * @param {object|null} station manifest.stations 里的一项
 * @param {boolean} hasMaterial 该工位是否有物料实体
 * @returns {string[]} 可用页签 key, 保持 STATION_TABS 的次序
 */
export function availableStationTabs(station, hasMaterial) {
  if (!station) return []
  const keys = []
  if (station.nodeId) keys.push('status')
  if ((station.actions || []).length) keys.push('actions')
  if (hasMaterial) keys.push('material')
  // 一个页签都没有的工位仍要给出点什么, 否则坞是个空框 —— 状态页会显示"无遥测节点"
  return keys.length ? keys : ['status']
}

/**
 * 功能: 换工位时决定停在哪一页.
 *
 * 用户在上样工位停在「操作」页, 切到料架 (没有操作页) 时不能停在一个不存在的页签上,
 * 也不该每次都粗暴地回「状态」—— 能保留就保留, 保不住才回落到第一个可用页.
 * @param {string} preferred 用户上次停留的页签
 * @param {string[]} available 当前可用页签
 * @returns {string} 应当激活的页签 key
 */
export function resolveStationTab(preferred, available) {
  if (!available.length) return 'status'
  return available.includes(preferred) ? preferred : available[0]
}

/**
 * 功能: 建立坞状态机.
 * @param {object} options 参数对象
 * @param {import('vue').Ref<string|null>} options.selectedStation useTwinScene 的选中工位 ref
 * @param {Function} options.selectStation useTwinScene 的选中动作
 * @returns {object} 坞状态与动作
 */
export function useLivePanels({ selectedStation, selectStation }) {
  const saved = sanitizeDockPrefs(loadJson(PREFS_KEY, null))
  const dock = reactive({
    collapsed: saved.collapsed,
    globalTab: saved.globalTab,
    /** 工位族里用户最后停留的页签; 不持久化 (随选中而生, 随取消而灭) */
    stationTab: 'status',
  })

  /** 坞当前属于哪一族 —— 唯一真源是"有没有选中工位" */
  const scope = computed(() => (selectedStation.value ? 'station' : 'global'))

  watch(
    () => [dock.collapsed, dock.globalTab],
    () => saveJson(PREFS_KEY, { collapsed: dock.collapsed, globalTab: dock.globalTab }),
  )

  /**
   * 功能: 打开某个全局页 (物料总览 / 工站信息 / 显示信息).
   *
   * 这是全篇**唯一**一处显式互斥: 进全局族就得先退出工位族. 其余方向不需要写,
   * 因为 scope 是推导的.
   * @param {string} tab 页签 key
   * @returns {void}
   */
  function openGlobal(tab) {
    if (GLOBAL_TAB_KEYS.has(tab)) dock.globalTab = tab
    dock.collapsed = false
    if (selectedStation.value) selectStation(null)
  }

  /**
   * 功能: 切工位页签 (调用方保证 tab 在可用集内).
   * @param {string} tab 页签 key
   * @returns {void}
   */
  function openStationTab(tab) {
    dock.stationTab = tab
    dock.collapsed = false
  }

  /** 功能: 收起/展开坞. 收起时 body 会被 v-if 掉, 于是单点会话随之释放 (与关面板同义). */
  function toggleDock() {
    dock.collapsed = !dock.collapsed
  }

  return { dock, scope, openGlobal, openStationTab, toggleDock }
}
