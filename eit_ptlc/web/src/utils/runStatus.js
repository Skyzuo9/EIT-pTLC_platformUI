// 运行状态英文枚举 → 两字中文 (执行记录列表 + 执行详情共用)。
// class 仍用原枚举值 (.run-li .dot.DONE / .runtag.DONE 等样式选择器不变), 未知值原样直出。
// runs 表会出现 RUNNING/DONE/FAILED/CANCELLED (vm/thread._finish 写入) 与
// INTERRUPTED (run_store.reconcile_orphans 启动收敛把上个进程留下的孤儿 RUNNING 判为中断);
// 详情页 view.status 经 vm_state 收口还可能是 ERROR/KILLED, 一并覆盖。
const RUN_STATUS_LABELS = {
  RUNNING: '运行',
  DONE: '完成',
  FAILED: '失败',
  CANCELLED: '取消',
  INTERRUPTED: '中断',
  ERROR: '错误',
  KILLED: '终止',
  REJECTED: '拒绝',
  TIMEOUT: '超时',
}

export function runStatusLabel(status) {
  return RUN_STATUS_LABELS[status] || status || ''
}
