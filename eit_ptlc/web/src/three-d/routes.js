/** 六个三维工作台的纯路由定义, 供宿主路由与离线契约测试共用. */

/** 动作工作台的三个子页; 路由 :tab 段只认这三个值 */
export const MOTION_TABS = ['mode', 'calib', 'action']

export const THREE_D_CHILD_ROUTES = [
  { path: '', redirect: '/3d/live' },
  { path: 'workbench', component: () => import('./workbench/WorkbenchView.vue'), name: 'three-d-workbench' },
  { path: 'materials', component: () => import('./materials/MaterialsView.vue'), name: 'three-d-materials' },
  // 动作工作台: 运动模式 / 标定 / 演示 三个子页共用一个场景
  { path: 'motion', redirect: '/3d/motion/mode' },
  {
    path: 'motion/:tab(mode|calib|action)/:target?',
    component: () => import('./motion/MotionWorkbench.vue'),
    name: 'three-d-motion',
  },
  // 演示: 与动作平级, 自动关联流程界面里的全部流程
  { path: 'demo/:flow?', component: () => import('./demo/DemoView.vue'), name: 'three-d-demo' },
  { path: 'live', component: () => import('./live/LiveView.vue'), name: 'three-d-live' },
  // 仿真: 独立沙盒 (虚拟 PLC + 真实执行链), 由状态渲染, 与实时页同一条渲染链
  { path: 'sim', component: () => import('./sim/SimView.vue'), name: 'three-d-sim' },
  // 旧地址兼容(书签/验收脚本/分享链接不死):
  //   /3d/calib            标定曾是独立页, 现为动作工作台的子页
  //   /3d/motion/<片段名>  片段评审曾挂在动作页, 现归演示页; 片段名含点号,
  //                        不匹配上面的 :tab 正则, 会落到这条兜底上
  { path: 'calib', redirect: '/3d/motion/calib' },
  { path: 'motion/:legacy(.*)', redirect: (to) => `/3d/demo/${to.params.legacy}` },
]
