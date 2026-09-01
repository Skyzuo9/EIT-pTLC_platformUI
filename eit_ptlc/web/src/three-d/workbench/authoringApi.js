/**
 * 功能: 三维 authoring 组件到上位机统一 API 客户端的适配层.
 */

import { api } from '../../api.js'

/** 探测 authoring 服务和当前写权限. */
export async function probeAuthoring() {
  try {
    const status = await api.threeDAuthoringStatus()
    return status?.available === true && status?.authoring_allowed === true
  } catch {
    return false
  }
}

/** 读取一个受管文件. */
export async function readFile(key) {
  const payload = await api.threeDRead({ key })
  return payload.content
}

/** 读取一个动画片段. */
export async function readClip(clip) {
  const payload = await api.threeDRead({ clip })
  return payload.content
}

/** 写入一个受管文件并由后端保留 .bak. */
export function writeFile(key, content) {
  return api.threeDWrite({ key, content })
}

/** 写入一个动画片段. */
export function writeClip(clip, content) {
  return api.threeDWrite({ clip, content })
}

/**
 * 启动固定管线重建.
 * @param {string[]} only 只跑这几个**管线步骤**(步骤 id, 不是流程名)
 * @param {object} [flow] 定向编一条流程 {operation, inputs} —— 只对 only:['flows'] 有效,
 *   约 20 秒而不是全量的 10 分钟。演示页"按这组入参编译这一条"走它
 */
export function startRebuild(only = [], flow = null) {
  return api.threeDStartRebuild(only, flow)
}

/** 查询管线重建状态. */
export function rebuildStatus() {
  return api.threeDRebuildStatus()
}

/** 轮询直到当前重建结束. */
export async function waitRebuild(onTick, intervalMs = 1200) {
  await new Promise((resolve) => setTimeout(resolve, 400))
  for (;;) {
    const status = await rebuildStatus()
    onTick?.(status)
    if (!status.running) return status
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

/** 列出已有动画片段. */
export async function listClips() {
  const payload = await api.threeDListClips()
  return payload.clips || []
}
