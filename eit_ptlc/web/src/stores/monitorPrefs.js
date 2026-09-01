// 底部监视栏 (MonitorDock) 折叠偏好 store: 按页面 (section) 记忆整栏收起/展开
// 协议:
//   - 默认表: 数据浏览类 5 页 (vision/water_level/planner/materials/runs) 默认收起, 其余默认展开
//   - 用户在某页手动切换后写显式覆盖 (localStorage JSON map, 键 eit_monitor_collapsed),
//     覆盖优先于默认; 未覆盖的页跟随默认表
//   - resetAll 清空全部覆盖 (StatusBar「恢复默认布局」与 layout.resetAll 同批调用)
// 纯逻辑独立成导出函数, 供 node --test 直接单测 (照 stores/runs.js 的 reduceRun 范式)
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { loadJson, saveJson } from '../utils/storage.js'

const KEY = 'eit_monitor_collapsed'

// 默认收起的页: 以数据浏览/回看为主, 底栏实时信息在这些页价值低, 让中区吃满
export const MONITOR_DEFAULT_COLLAPSED = ['three_d', 'vision', 'water_level', 'planner', 'materials', 'runs']

// 清洗持久化数据: 只留布尔项 (loadJson 的形状守卫按约定归调用方; 防手改/旧版残留脏形状)
export function sanitizeMonitorPrefs(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const out = {}
  for (const [k, v] of Object.entries(raw)) {
    if (typeof v === 'boolean') out[k] = v
  }
  return out
}

// 有效折叠态: 显式覆盖优先, 缺失走默认表
export function monitorCollapsedOf(section, overrides) {
  const v = overrides ? overrides[section] : undefined
  if (typeof v === 'boolean') return v
  return MONITOR_DEFAULT_COLLAPSED.includes(section)
}

// 切换后的覆盖表 (纯函数, 不改入参): 写显式反值且不删键 —— 语义是「该页已被用户接管」;
// 不照 eit_dock_collapsed 的删键法: 这里默认按页不同, true/false 都是有效覆盖值
export function toggledMonitorPrefs(overrides, section) {
  return { ...overrides, [section]: !monitorCollapsedOf(section, overrides) }
}

export const useMonitorPrefsStore = defineStore('monitorPrefs', () => {
  // 覆盖表 (响应式): 每次整对象替换, 消费方 computed 的依赖追踪简单可靠
  const overrides = ref(sanitizeMonitorPrefs(loadJson(KEY, {})))

  // 某页当前是否收起 (组件在 computed 里调用即建立依赖)
  function isCollapsed(section) { return monitorCollapsedOf(section, overrides.value) }

  // 切换某页折叠态并立即落盘
  function toggle(section) {
    overrides.value = toggledMonitorPrefs(overrides.value, section)
    saveJson(KEY, overrides.value)
  }

  // 清空全部页面覆盖回默认表 (配合「恢复默认布局」)
  function resetAll() {
    overrides.value = {}
    try { localStorage.removeItem(KEY) } catch (e) { /* 存储禁用: 静默忽略 */ }
  }

  return { overrides, isCollapsed, toggle, resetAll }
})
