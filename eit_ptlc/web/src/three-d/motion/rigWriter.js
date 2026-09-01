/**
 * 功能: rig_map.yaml 的统一写回口 —— 一律"读盘 → 打补丁 → 写", 并做并发检测.
 *
 * 为什么必须集中: rig_map 有多个写入方。本工作台内部就有三个(运动模式改方向/参数、
 * 指认模式改 carriage_members、标定改零点三元组), 加上另一个会话/后端也可能在写
 * (three_d/docs/CLAUDE.md §36 记了一次实际撞车: 开工时读到的 actuators 段只有 5 条,
 * 中途再看已被另一方补进 3 条, 行号整体后移)。
 *
 * 对策不是加锁(做不到), 而是: 每次写前重读, 补丁打在**刚读到的**文本上, 且把这次
 * 读到的原文记下来; 下一次写之前如果发现盘上的内容既不等于我们上次写出去的、也不等
 * 于我们上次读到的, 就说明中途被人改过 —— 报出来让人决定, 而不是闷头覆盖。
 *
 * rigPatch.js 的六个 patch 函数保持纯函数, 本模块只管"读-改-写"的时序与冲突判定。
 */
import * as api from '../workbench/authoringApi.js'

/** 上一次经本模块读到/写出的 rig_map 原文; 用于识别第三方改动 */
let lastSeen = null

/**
 * 功能: 读一次 rig_map 并记录基线.
 * @returns {Promise<string>} YAML 原文
 */
export async function readRigMap() {
  const text = await api.readFile('rig_map')
  lastSeen = text
  return text
}

/**
 * 功能: 读-改-写一次 rig_map.
 *
 * @param {(text: string) => string} patch 纯补丁函数, 收原文返回新文
 * @param {object} [options] 选项
 * @param {boolean} [options.force=false] 检测到第三方改动时仍然写入
 * @returns {Promise<{ok: boolean, conflict?: boolean, path?: string}>} 结果
 * @throws {Error} 读写失败或补丁抛错
 */
export async function patchRigMap(patch, { force = false } = {}) {
  const current = await api.readFile('rig_map')
  if (force === false && lastSeen !== null && current !== lastSeen) {
    // 不覆盖: 把基线更新到盘上现状, 调用方重试一次即可打在最新文本上
    lastSeen = current
    return { ok: false, conflict: true }
  }
  const next = patch(current)
  const result = await api.writeFile('rig_map', next)
  lastSeen = next
  return { ok: true, path: result?.path || '' }
}

/**
 * 功能: 丢弃基线(换页/重跑后调, 避免拿过期基线误判冲突).
 * @returns {void}
 */
export function resetRigBaseline() {
  lastSeen = null
}
