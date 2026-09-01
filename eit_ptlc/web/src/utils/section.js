// 页面栏位 (section) 推导: route.path → 栏 key (单一真源)
// 原逻辑在 RailNav / ExplorerDock 各有一份 (逐字符相同); 底栏折叠偏好按 section 记忆后
// 消费方涨到 4 处 (RailNav / ExplorerDock / ConsoleShell / StatusBar), 收编到此。
// 判断顺序即优先级, 与原两份 copy 逐行一致; 兜底 'action' (含 '/' 重定向与未知路径)。
export function sectionOf(path) {
  if (path.startsWith('/points')) return 'points'
  if (path.startsWith('/nodes')) return 'nodes'
  if (path.startsWith('/3d')) return 'three_d'
  if (path.startsWith('/runs')) return 'runs'
  if (path.startsWith('/vision')) return 'vision'
  if (path.startsWith('/water_level')) return 'water_level'
  if (path.startsWith('/planner')) return 'planner'
  // 调度编排 (/schedule) 与实验 (/experiment) 是两栏; 前缀判断写死斜杠, 免与旧 /scheduler 混淆
  if (path === '/schedule' || path.startsWith('/schedule/')) return 'schedule'
  if (path.startsWith('/experiment')) return 'scheduler'
  if (path.startsWith('/materials')) return 'materials'
  if (path.startsWith('/plc')) return 'plc'
  if (path.startsWith('/library/operation')) return 'operation'
  return 'action'
}
