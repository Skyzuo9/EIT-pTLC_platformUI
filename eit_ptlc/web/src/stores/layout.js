// 布局尺寸 store: 集中管理各可拖拽"大栏"的宽/高 (px)
// 协议:
//   - 每个大栏一个 key, 登记默认尺寸 def 与允许范围 [min, max]
//   - 初值优先读 localStorage (键前缀 eit_layout_), 命中且合法则用之, 否则用 def (长期记忆)
//   - setSize 写入并夹紧到 [min, max]; persist 落盘; resetAll 全部回默认并清盘
import { defineStore } from 'pinia'
import { reactive } from 'vue'

// 各大栏规格 (px). key 同时作为 localStorage 持久化键的后缀
const SPECS = {
  shellRailW: { def: 64, min: 56, max: 120 },      // 壳层: 最左竖向栏 (rail) 宽 (图标+标签竖排)
  shellDockW: { def: 240, min: 160, max: 560 },    // 壳层: 左侧列表 (dock) 宽
  shellMonitorH: { def: 230, min: 120, max: 600 }, // 壳层: 底部监视器 (monitor) 高
  monitorRightW: { def: 380, min: 240, max: 900 }, // 监视器: 设备状态栏宽
  editorRightW: { def: 320, min: 220, max: 720 },  // 编辑器: 右栏宽
  nodeColActW: { def: 320, min: 120, max: 900 },   // 编辑器: 节点表 Action 列宽 (px, 可拖拽)
  nodeColInW: { def: 220, min: 100, max: 900 },    // 编辑器: 节点表 Input 列宽 (px, 可拖拽)
  wlParamW: { def: 360, min: 280, max: 720 },      // 液位通道: 参数栏宽
  jogRightW: { def: 300, min: 220, max: 640 },     // 机器人面板: 关节栏宽
  deviceSideW: { def: 360, min: 280, max: 720 },   // 设备节点页: 右侧状态栏宽
  actionParamsW: { def: 360, min: 280, max: 760 }, // 动作页: 右栏 (注释/PLC) 宽
  plcRightW: { def: 360, min: 280, max: 760 },     // PLC 页: 右栏 (编译/部署) 宽
  pouDeclH: { def: 220, min: 100, max: 640 },      // POU 编辑器: 声明 (VAR) 区高 (与实现区之间可拖)
  schedulerRightW: { def: 360, min: 260, max: 720 }, // 实验看板: 段作业详情右栏宽
  scheduleRightW: { def: 340, min: 260, max: 720 },  // 调度编排器: 段属性/接线右栏宽
  twinDockW: { def: 360, min: 280, max: 720 },       // 三维实时页: 右侧信息坞宽
}
const PREFIX = 'eit_layout_'

/**
 * 功能:
 *     将数值四舍五入并夹紧到闭区间 [lo, hi]
 * 参数:
 *     value 浮点, 待夹紧的尺寸 (px)
 *     lo/hi 整数, 允许的下/上界
 * 返回:
 *     int, 夹紧后的整数像素值
 */
function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, Math.round(value)))
}

export const useLayoutStore = defineStore('layout', () => {
  // 各大栏当前尺寸 (响应式). 渲染前同步初始化, 保证首帧即生效
  const sizes = reactive({})
  for (const key in SPECS) {
    const saved = parseInt(localStorage.getItem(PREFIX + key), 10)
    sizes[key] = Number.isFinite(saved) ? clamp(saved, SPECS[key].min, SPECS[key].max) : SPECS[key].def
  }

  // 设置某大栏尺寸 (拖拽过程中高频调用), 夹紧到规格范围
  function setSize(key, px) {
    if (!SPECS[key]) {
      return
    }
    sizes[key] = clamp(px, SPECS[key].min, SPECS[key].max)
  }

  // 落盘某大栏当前尺寸 (拖拽结束时调用一次)
  function persist(key) {
    try {
      localStorage.setItem(PREFIX + key, String(sizes[key]))
    } catch (e) {
      /* localStorage 不可用时静默忽略, 不影响交互 */
    }
  }

  // 恢复默认布局: 全部回默认尺寸并清除持久化
  function resetAll() {
    for (const key in SPECS) {
      sizes[key] = SPECS[key].def
      try {
        localStorage.removeItem(PREFIX + key)
      } catch (e) {
        /* 同上, 静默忽略 */
      }
    }
  }

  return { sizes, setSize, persist, resetAll }
})
