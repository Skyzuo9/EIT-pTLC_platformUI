// 设备节点 store: 节点清单 + 实时遥测 + 健康汇总
import { defineStore } from 'pinia'
import { reactive, ref, computed } from 'vue'
// 相对导入写全 .js: 本模块被 tests/nodes-merge.test.js 用裸 node --test 直载 (node ESM 不补扩展名)
import { api } from '../api.js'

// ---- 遥测字段级合并 (纯函数, 供单测直载) ----
// 为什么: 每帧整体替换 byId[node] 会让所有下游 computed (StatusBar 工具/站点、健康汇总、
// 列表、快照表) 每秒无效重算一遍, 即使帧间数值一个没变。就地合并 + 值不同才写, 让
// reactive 依赖只在真实变化处失效。消费者审计: 全部消费点是"读字段"语义, 无人依赖
// 对象身份变化, 纯性能改动。

// 数组浅比较 (长度 + 逐元素 Object.is): 相同则保留旧数组身份, 否则身份 churn 只是下移一层
export function sameArray(a, b) {
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) if (!Object.is(a[i], b[i])) return false
  return true
}

/**
 * 功能:
 *     把 src 的字段就地合并进 target (reactive 代理), 值不同才写、src 里消失的 key 删除
 * 参数:
 *     target/src 均须为非 null 普通对象 (调用方守卫); depth 嵌套对象的递归层数
 *     (遥测 data 消费最深链是 data.tool_state.<标量>, 一层足够)
 * 返回:
 *     None (就地变更)
 */
export function mergeInto(target, src, depth) {
  for (const k in target) {
    if (!(k in src)) delete target[k] // reactive 代理上 delete 触发 deleteProperty trap
  }
  for (const k of Object.keys(src)) {
    const nv = src[k]
    const ov = target[k]
    if (Array.isArray(nv)) {
      if (!Array.isArray(ov) || !sameArray(ov, nv)) target[k] = nv
    } else if (nv && typeof nv === 'object') {
      if (depth > 0 && ov && typeof ov === 'object' && !Array.isArray(ov)) mergeInto(ov, nv, depth - 1)
      else if (ov !== nv) target[k] = nv
    } else if (!Object.is(ov, nv)) {
      target[k] = nv
    }
  }
}

export const useNodesStore = defineStore('nodes', () => {
  const byId = reactive({}) // id -> 节点快照 {id,label,kind,health,data,ts}
  const order = ref([]) // 装配顺序的 id 列表
  const selectedId = ref(null)

  const list = computed(() => order.value.map((id) => byId[id]).filter(Boolean))
  const selected = computed(() => (selectedId.value ? byId[selectedId.value] : null))
  const summary = computed(() => {
    const acc = { ok: 0, busy: 0, error: 0, offline: 0 }
    for (const id of order.value) {
      const node = byId[id]
      if (node && acc[node.health] !== undefined) acc[node.health] += 1
    }
    return acc
  })

  // 首屏拉取节点清单 (含 label/kind), 之后由 telemetry 事件持续刷新
  async function seed() {
    const nodes = await api.listNodes()
    order.value = nodes.map((n) => n.id)
    for (const node of nodes) byId[node.id] = node
  }

  // 消费 telemetry 事件; 保留首屏 label/kind, 刷新 health/data/ts。
  // 首帧整建; 后续帧就地字段级合并 (见顶部 mergeInto) —— byId[id] 身份稳定,
  // 帧间无变化时下游 computed 不再无效重算。
  function ingest(event) {
    if (event.type !== 'telemetry') return
    const prev = byId[event.node]
    if (!prev) {
      byId[event.node] = {
        id: event.node,
        label: event.node,
        kind: '',
        health: event.health,
        data: event.data,
        ts: event.ts,
      }
    } else {
      if (prev.health !== event.health) prev.health = event.health
      prev.ts = event.ts // 无人读 ts (grep 零命中), 直写零代价; 留作调试字段
      // 空值防御: 后端读失败字段是置 null 而非删 key; 任一侧非普通对象则退回整赋值
      if (prev.data && typeof prev.data === 'object' && !Array.isArray(prev.data)
        && event.data && typeof event.data === 'object' && !Array.isArray(event.data)) {
        mergeInto(prev.data, event.data, 1)
      } else if (prev.data !== event.data) {
        prev.data = event.data
      }
    }
    if (!order.value.includes(event.node)) order.value = [...order.value, event.node]
  }

  function select(id) {
    selectedId.value = id
  }

  return { byId, order, selectedId, list, selected, summary, seed, ingest, select }
})
