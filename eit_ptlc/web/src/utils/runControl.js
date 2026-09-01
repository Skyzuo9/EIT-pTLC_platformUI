// 调试坞运行控制的纯判定 (无 Vue 依赖, 便于单测)。
// 把"正在浏览哪个流程"与"运行器归属哪个流程"解耦: 浏览别的流程不得影响在跑的运行,
// 但也不能让"运行"按钮在浏览页误把另一个流程的 run 续跑 (会触发意外的机器人动作)。

// 运行终结/未起: 此时"运行"= 起跑当前编辑的流程 (与调试坞原 idle 判定一致, NEW 视为运行中)
export const IDLE_STATUSES = new Set(['idle', 'DONE', 'ERROR', 'KILLED', ''])
export function isIdle(status) {
  return IDLE_STATUSES.has(status)
}

// 有一个活动运行, 但它归属的流程 ≠ 当前正在浏览/编辑的流程。
// 为真时: 调试坞对"当前流程"只读, 运行控制指向别处 → 禁用起跑/步进, 改为提示并可一键跳回归属流程。
export function isRunActiveElsewhere({ status, runOperation, editedFlow }) {
  return !isIdle(status) && !!runOperation && runOperation !== editedFlow
}
