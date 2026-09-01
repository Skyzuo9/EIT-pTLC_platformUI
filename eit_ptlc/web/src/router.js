// 控制台三正交视图的中区深链: 库 (编排 IDE) / 设备 / 执行
// 重视图懒加载 (CodeMirror 等大依赖随 PlcView 分包, 不占首屏); 常驻主路径保持静态引入
import { createRouter, createWebHistory } from 'vue-router'
import LibraryView from './views/LibraryView.vue'
import NodeDetail from './views/NodeDetail.vue'
import NotFoundView from './views/NotFoundView.vue'
import RunDetail from './views/RunDetail.vue'
import { THREE_D_CHILD_ROUTES } from './three-d/routes.js'

const routes = [
  { path: '/', redirect: '/library/action' },
  { path: '/library/:kind?/:name?', component: LibraryView, name: 'library' },
  { path: '/points/:category?/:id?', component: () => import('./views/PointsView.vue'), name: 'points' },
  { path: '/nodes/:id?', component: NodeDetail, name: 'nodes' },
  {
    path: '/3d',
    component: () => import('./three-d/App.vue'),
    children: THREE_D_CHILD_ROUTES,
  },
  { path: '/runs/:id?', component: RunDetail, name: 'runs' },
  // 排程: 流程平均耗时甘特 + 多样品模拟排布 (只展示不控制执行, 离线模拟保留)
  { path: '/planner', component: () => import('./views/PlannerView.vue'), name: 'planner' },
  // 调度: 三层 (动作/流程/调度) 的第三层 — 段组合与串并行结构的图形化编排
  { path: '/schedule/:name?', component: () => import('./views/ScheduleView.vue'), name: 'schedule' },
  // 旧地址兼容 (书签/历史链接不死): 方案编辑已独立成 /schedule 栏 (须在动态 :sub 之前)
  { path: '/experiment/recipe/:name', redirect: (to) => `/schedule/${to.params.name}` },
  // 实验: 批量提交/运行看板/批次详情; sub = board(缺省) | submit | batch
  { path: '/experiment/:sub?/:id?', component: () => import('./views/SchedulerView.vue'), name: 'experiment' },
  // 旧 /scheduler/* -> /experiment/* (recipe 子页转投 /schedule)
  { path: '/scheduler/:rest(.*)*', redirect: (to) => {
    const rest = [].concat(to.params.rest || []).filter(Boolean)
    if (rest[0] === 'recipe' && rest[1]) return `/schedule/${rest[1]}`
    return '/experiment' + (rest.length ? '/' + rest.join('/') : '')
  } },
  // 物料: 每类物料一个子页 (cat 取自后端拓扑 tray/feed/glass/solvent/seat) + log=记账流水;
  // 缺省进第一类。建议式账本的唯一权威录入口。
  { path: '/materials/:cat?', component: () => import('./views/MaterialView.vue'), name: 'materials' },
  // 视觉调试台: Before/After 拍照、上传、参数编辑、识别分析
  { path: '/vision', component: () => import('./views/VisionDebugView.vue'), name: 'vision' },
  // 液位检测外设控制台 (调试调参): 无 channel = 8 路网格总览; 有 channel = 单路调试
  { path: '/water_level/:channel?', component: () => import('./views/WaterLevelView.vue'), name: 'water_level' },
  // PLC 程序编辑: 空态 / POU 编辑 (path 含斜杠故用 (.*) 捕获整段)
  { path: '/plc', component: () => import('./views/PlcView.vue'), name: 'plc' },
  { path: '/plc/pou/:path(.*)', component: () => import('./views/PlcView.vue'), name: 'plc-pou' },
  // 404 兜底 (必须在最后)
  { path: '/:pathMatch(.*)*', component: NotFoundView, name: 'not-found' },
]

export default createRouter({ history: createWebHistory(), routes })
