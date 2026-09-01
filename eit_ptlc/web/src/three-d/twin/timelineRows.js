/**
 * 功能: 把运行步骤树摊平成时间线条带的行序列.
 *
 * 三维页底部的时间线是一条窄横栏, 放不下 RunDetail 那样的嵌套树, 因此这里把
 * stores/runs.js 的 reduceRun/applyEvent 产出的树按前序遍历摊平, 用 depth 表达层级.
 *
 * 步骤树本身不在这里重建 —— 那是 stores/runs.js 的职责(它已处理 vm_node_enter/done
 * 的脚本帧嵌套、终态收口与丢事件兜底, 且有单测). 本模块只做"树 -> 行"的展示变换,
 * 保持纯函数以便单测.
 */

import { stationForAction } from './manifest.js'

/** 步骤失败态集合(与 stores/runs.js 的 _FINAL 同源, 但这里只关心"红行"判定) */
const FAILED_STATUS = new Set(['FAILED', 'ERROR', 'KILLED', 'CANCELLED'])

/**
 * 功能: 判断一个步骤状态是否算失败(决定是否标红).
 * @param {string} status 步骤状态
 * @returns {boolean} 是否失败
 */
export function isFailedStatus(status) {
  return FAILED_STATUS.has(status)
}

/**
 * 功能: 把步骤树前序摊平成行, 并补上工位反查与失败判定.
 *
 * run_script 容器行一并保留: 它是"进了哪个子流程"的分组语义, 在条带上同样有信息量;
 * 其 depth 比子步小 1, 模板据此缩进.
 * @param {object[]} steps 步骤树(reduceRun 产出的 run.steps)
 * @param {object|null} manifest device-manifest 内容(用于按动作名反查工位); 缺失则工位列留空
 * @returns {object[]} 行数组, 每行含 depth / stationId / stationLabel / failed
 */
export function flattenSteps(steps, manifest = null, depth = 0, out = []) {
  for (const step of steps || []) {
    const station = manifest && step.action ? stationForAction(manifest, step.action) : null
    out.push({
      stepId: step.step_id || '',
      script: step.script || '',
      op: step.op || '',
      action: step.action || '',
      status: step.status || '',
      message: step.message || '',
      ts: step.ts || null,
      doneTs: step.doneTs || null,
      depth,
      isGroup: !!(step.children && step.children.length),
      stationId: station?.id || null,
      stationLabel: station?.label || '',
      failed: isFailedStatus(step.status),
    })
    if (step.children && step.children.length) {
      flattenSteps(step.children, manifest, depth + 1, out)
    }
  }
  return out
}

/**
 * 功能: epoch 秒格式化为 时:分:秒.
 * @param {number|null} ts epoch 秒(事件里的 ts 字段)
 * @returns {string} 显示文本; 无时间戳时给占位
 */
export function formatEpoch(ts) {
  if (!ts) return '--:--:--'
  const date = new Date(ts * 1000)
  return Number.isNaN(date.getTime()) ? '--:--:--' : date.toTimeString().slice(0, 8)
}

/**
 * 功能: 运行记录列表项的显示摘要(历史列表用).
 * @param {object} run 运行记录行(/api/runs 的元素)
 * @returns {{id: string, name: string, status: string, time: string}} 显示字段
 */
export function runSummary(run) {
  return {
    id: run?.run_id || run?.id || '',
    name: run?.label || run?.operation || run?.name || run?.run_id || run?.id || '',
    status: run?.status || '',
    time: formatEpoch(run?.started_at),
  }
}
