// 调度方案 DAG 的自动布局与图论纯函数 (无 DOM/网络; node --test 可测)
//
// 布局是**推导出来的, 不持久化**: 层号 = 最长路径深度, 同层横向并排。
// 这样"并行的段天然横向并列、串行的段纵向串下来"—— 画布本身就在讲串并行结构,
// 且方案文件里不会长出坐标噪音 (工程师改 depends_on, 图自己重排)。

// 节点几何 (与 DagCanvas.vue 的 CSS 尺寸对齐)
export const NODE_W = 168
export const NODE_H = 52
export const GAP_X = 28
export const GAP_Y = 64
export const PAD = 24

// 每段的直接上游 -> Map(id -> string[]); 未知 id 的依赖静默忽略 (校验器负责报错)
function depsOf(flows) {
  const ids = new Set(flows.map((f) => f.id))
  const map = new Map()
  for (const f of flows) map.set(f.id, (f.depends_on || []).filter((d) => ids.has(d)))
  return map
}

// 传递上游闭包 Map(id -> Set(全部祖先))。有环时环内节点闭包可能不完整,
// 故成环判定用 hasCycle/wouldCycle, 不要靠这个函数。
export function ancestorSets(flows) {
  const deps = depsOf(flows)
  const out = new Map()
  const state = new Map()   // id -> 0 访问中 | 1 完成
  function visit(id) {
    if (state.get(id) === 1) return out.get(id)
    if (state.get(id) === 0) return new Set()    // 环: 就地断开, 不无限递归
    state.set(id, 0)
    const acc = new Set()
    for (const d of deps.get(id) || []) {
      acc.add(d)
      for (const a of visit(d)) acc.add(a)
    }
    state.set(id, 1)
    out.set(id, acc)
    return acc
  }
  for (const f of flows) visit(f.id)
  return out
}

// 是否已成环 (DFS 三色)
export function hasCycle(flows) {
  const deps = depsOf(flows)
  const color = new Map()
  let found = false
  function dfs(id) {
    if (found) return
    const c = color.get(id)
    if (c === 1) { found = true; return }
    if (c === 2) return
    color.set(id, 1)
    for (const d of deps.get(id) || []) dfs(d)
    color.set(id, 2)
  }
  for (const f of flows) dfs(f.id)
  return found
}

// 加一条边 from -> to (即 to.depends_on += from) 会不会成环?
// 成环 <=> from 已经是 to 的下游 (from 可经依赖链到达 to), 或 from === to。
export function wouldCycle(flows, fromId, toId) {
  if (fromId === toId) return true
  const anc = ancestorSets(flows)
  return (anc.get(fromId) || new Set()).has(toId)
}

// 最长路径分层: layer(n) = 0 (无上游) 或 max(layer(上游)) + 1
export function layerOf(flows) {
  const deps = depsOf(flows)
  const layer = new Map()
  const state = new Map()
  function calc(id) {
    if (state.get(id) === 1) return layer.get(id)
    if (state.get(id) === 0) return 0            // 环: 断开取 0 (校验器会拒, 此处只求能画)
    state.set(id, 0)
    let lv = 0
    for (const d of deps.get(id) || []) lv = Math.max(lv, calc(d) + 1)
    state.set(id, 1)
    layer.set(id, lv)
    return lv
  }
  for (const f of flows) calc(f.id)
  return layer
}

/**
 * 布局: flows -> {nodes, edges, width, height, layers}
 *   nodes: [{id, flow, layer, col, x, y, inPort:{x,y}, outPort:{x,y}}]  (x/y = 卡片左上角)
 *   edges: [{key, from, to, d}]   d = SVG path (三次贝塞尔, 出口向下 -> 入口向上)
 *   layers: [[id...]]  按层分组 (层内保 flows 声明序 —— 与 YAML 顺序一致, 稳定不跳)
 */
export function layoutDag(flows) {
  const list = flows || []
  const layer = layerOf(list)
  const depth = list.length ? Math.max(...list.map((f) => layer.get(f.id) || 0)) + 1 : 0
  const layers = Array.from({ length: depth }, () => [])
  for (const f of list) layers[layer.get(f.id) || 0].push(f.id)

  const widest = layers.reduce((m, l) => Math.max(m, l.length), 0)
  const rowW = widest * NODE_W + Math.max(0, widest - 1) * GAP_X
  const nodes = []
  const byId = new Map()
  layers.forEach((ids, lv) => {
    const n = ids.length
    const thisW = n * NODE_W + Math.max(0, n - 1) * GAP_X
    const left = PAD + (rowW - thisW) / 2          // 层内居中, 视觉上是一棵对称的树
    ids.forEach((id, col) => {
      const x = left + col * (NODE_W + GAP_X)
      const y = PAD + lv * (NODE_H + GAP_Y)
      const node = {
        id, flow: list.find((f) => f.id === id), layer: lv, col, x, y,
        inPort: { x: x + NODE_W / 2, y },
        outPort: { x: x + NODE_W / 2, y: y + NODE_H },
      }
      nodes.push(node)
      byId.set(id, node)
    })
  })

  const edges = []
  for (const f of list) {
    for (const d of f.depends_on || []) {
      const a = byId.get(d)
      const b = byId.get(f.id)
      if (!a || !b) continue
      edges.push({ key: `${d}->${f.id}`, from: d, to: f.id, d: edgePath(a.outPort, b.inPort) })
    }
  }
  return {
    nodes, edges, layers,
    width: rowW + PAD * 2,
    height: depth ? PAD * 2 + depth * NODE_H + Math.max(0, depth - 1) * GAP_Y : PAD * 2,
  }
}

// 出口 -> 入口的三次贝塞尔 (竖直出/入, 控制点按纵距取半; 反向边也不会画成直线穿过卡片)
export function edgePath(from, to) {
  const dy = Math.max(24, Math.abs(to.y - from.y) / 2)
  return `M ${from.x} ${from.y} C ${from.x} ${from.y + dy} ${to.x} ${to.y - dy} ${to.x} ${to.y}`
}

// 新段 id: 在已用 id 里找 <prefix><n> 的最小空闲 n (s1..s11 已占则给 s12)
export function nextSegId(flows, prefix = 's') {
  const used = new Set((flows || []).map((f) => f.id))
  for (let i = 1; i < 1000; i++) {
    const id = `${prefix}${i}`
    if (!used.has(id)) return id
  }
  return `${prefix}_new`
}
