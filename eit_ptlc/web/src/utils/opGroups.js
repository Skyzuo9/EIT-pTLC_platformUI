// 流程库组内子栏分桶 (无 Vue 依赖, 进 node --test)
//
// 为什么用 ui.subgroup 而不是复用 ui.station: station 是调度语义 (英文 token, 标注工位任务归属),
// 子栏是纯展示关切 —— 直接存中文标题, 前端零映射表。当前仅 06_robot 机械臂流程使用
// (28 条按涉及工位分栏); 其余组条目无 subgroup 全落匿名首桶, 渲染与原平铺逐项一致。

// 未标 order 的条目沉底 (仍按 label 兜底排序, 永不丢项)
const NO_ORDER = 999

function orderOf(it) {
  const n = it && it.ui ? it.ui.order : undefined
  return Number.isFinite(n) ? n : NO_ORDER
}

/**
 * 功能:
 *     把一个组的流程条目按 ui.subgroup 分桶。无 subgroup 的条目进匿名首桶 (sub=null,
 *     保持入参顺序, 即上游 groupBy 的 label 序); 子栏桶按桶内最小 ui.order 升序 (再按标题),
 *     桶内条目按 ui.order 升序 (再按 label/name)。
 * 参数:
 *     items 数组, 流程摘要列表 ({name, label, ui?, ...}; 可为空/undefined)
 * 返回:
 *     数组, [{sub, items}]; sub 为 null (匿名桶, 仅在有此类条目时出现) 或子栏标题字符串
 */
export function buildBuckets(items) {
  const plain = []
  const subs = new Map()
  for (const it of items || []) {
    const sub = it && it.ui && typeof it.ui.subgroup === 'string' && it.ui.subgroup ? it.ui.subgroup : null
    if (!sub) plain.push(it)
    else {
      if (!subs.has(sub)) subs.set(sub, [])
      subs.get(sub).push(it)
    }
  }
  const byOrderThenLabel = (a, b) =>
    orderOf(a) - orderOf(b) || String(a.label || a.name || '').localeCompare(String(b.label || b.name || ''))
  const out = plain.length ? [{ sub: null, items: plain }] : []
  return out.concat([...subs.entries()]
    .map(([sub, list]) => ({ sub, items: list.slice().sort(byOrderThenLabel), min: Math.min(...list.map(orderOf)) }))
    .sort((a, b) => a.min - b.min || a.sub.localeCompare(b.sub))
    .map(({ sub, items: sorted }) => ({ sub, items: sorted })))
}
