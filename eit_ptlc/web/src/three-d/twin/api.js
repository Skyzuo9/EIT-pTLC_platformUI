/**
 * 功能: 三维组件到上位机统一 REST 客户端的语义适配层.
 */

import { api } from '../../api.js'

/** 取动作目录. */
export function fetchActions() {
  return api.listActions()
}

/** 取当前控制模式并归一化 mode 字段. */
export async function fetchMode() {
  const payload = await api.getMode()
  return { ...payload, mode: payload?.control_mode || payload?.mode || '' }
}

/** 取 PLC 示教点位树. */
export function fetchPointsTree() {
  return api.getPointsTree()
}

/** 执行一个上位机动作. */
export function runAction(name, params, mode) {
  return api.runAction(name, params || {}, mode)
}

/** 取最近运行记录. */
export function fetchRuns(limit = 20) {
  return api.listRuns({ limit })
}

/** 取单次运行详情. */
export function fetchRun(runId) {
  return api.getRun(runId)
}

/** 取全部节点快照. */
export function fetchNodes() {
  return api.listNodes()
}
