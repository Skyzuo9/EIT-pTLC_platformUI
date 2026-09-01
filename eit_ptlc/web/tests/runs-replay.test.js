// RunDetail 前向增量重放的等价性: 逐条 applyEvent(与实时 ingest/reseed 同一状态机)
// 在**每个前缀 k** 上都必须与全量 reduceRun(events.slice(0,k)) 深等 —— 这是把重放从
// O(N²) 改 O(N) 的正确性锚。另锁 applyEvent 开子帧"经 parent.children 读回入栈"的
// 反应性修复 (reactive 下嵌套帧内变更必须走代理可被追踪) 防回归。
import test from 'node:test'
import assert from 'node:assert/strict'
import { computed, reactive } from 'vue'

import { applyEvent, reduceRun } from '../src/stores/runs.js'

// 事件构造小工具 (复制自 runs-reduce.test.js —— 四个 runs-*.test.js 的 helper 签名互不相同,
// 不抽公共文件以免动并行开发中的测试; 字段对照后端 thread.py)。script 缺省为根脚本 'root'。
const opStart = () => ({ type: 'operation_start', run_id: 'r1', operation: 'root', label: 'root' })
const enter = (aid, op, action, script = 'root') =>
  ({ type: 'vm_node_enter', run_id: 'r1', op, aid, action, script })
const done = (aid, op, action, script = 'root', status = 'DONE') =>
  ({ type: 'vm_node_done', run_id: 'r1', op, aid, action, script, status, message: '完成', result: {} })
const opDone = (status = 'DONE') => ({ type: 'operation_done', run_id: 'r1', status })
const opFailed = (status = 'CANCELLED') => ({ type: 'operation_failed', run_id: 'r1', status })
const vmState = (status, script = 'root') => ({ type: 'vm_state', run_id: 'r1', status, script })

function freshProj() {
  const run = { run_id: '', operation: '', label: '', status: '', message: '', steps: [] }
  const ctx = { stack: [{ children: run.steps }] }
  return { run, ctx }
}

// 代表性事件序列: 嵌套 run_script(含跨帧同号 aid)、混入非 run 类事件、漏 done + 终态收口、
// 中途 vm_state、二次 operation_start 重开
const SEQ = [
  opStart(),
  enter('b/0', 'call', 'place_axis'),
  done('b/0', 'call', 'place_axis'),
  enter('b/1', 'run_script', 'rail_move_safe'),
  enter('b/0', 'call', 'require_anchor', 'rail_move_safe'),
  { type: 'vm_vars', run_id: 'r1', vars: { x: 1 } },          // 非 run 类: 两条路径都应忽略
  done('b/0', 'call', 'require_anchor', 'rail_move_safe'),
  enter('b/1', 'run_script', 'nested_inner', 'rail_move_safe'),
  enter('b/0', 'call', 'rail.move', 'nested_inner'),
  done('b/0', 'call', 'rail.move', 'nested_inner'),
  done('b/1', 'run_script', 'nested_inner', 'rail_move_safe'),
  done('b/1', 'run_script', 'rail_move_safe'),
  vmState('RUNNING'),
  enter('b/2', 'call', 'robot_suction_pick'),
  opDone('DONE'),                                              // b/2 漏 done → 收口为 DONE
]

const SEQ_REOPEN = [
  ...SEQ,
  opStart(),                                                   // 同 run 重开: splice 清树重来
  enter('b/0', 'call', 'again'),
  opFailed('CANCELLED'),
]

test('逐条 applyEvent 在每个前缀 k 上与全量 reduceRun 深等 (纯对象)', () => {
  for (const events of [SEQ, SEQ_REOPEN]) {
    const { run, ctx } = freshProj()
    for (let k = 1; k <= events.length; k++) {
      applyEvent(run, ctx, events[k - 1])
      assert.deepEqual(run, reduceRun(events.slice(0, k)), `前缀 k=${k} 不等价`)
    }
  }
})

test('reactive 投影下嵌套帧内变更可被追踪 (锁"经 children 读回入栈"修复)', () => {
  const run = reactive({ run_id: '', operation: '', label: '', status: '', message: '', steps: [] })
  const ctx = { stack: [{ children: run.steps }] }
  // 依赖整树的 computed: 若嵌套帧内的变更绕过代理, 它不会失效
  let evals = 0
  const doneCount = computed(() => {
    evals += 1
    const walk = (arr) => arr.reduce((n, s) => n + (s.status === 'DONE' ? 1 : 0) + walk(s.children || []), 0)
    return walk(run.steps)
  })
  applyEvent(run, ctx, opStart())
  applyEvent(run, ctx, enter('b/1', 'run_script', 'rail_move_safe'))
  applyEvent(run, ctx, enter('b/0', 'call', 'require_anchor', 'rail_move_safe'))
  assert.equal(doneCount.value, 0)
  // 嵌套帧内的 done: 修复前经 raw 栈顶写入不触发代理 → doneCount 不失效仍读 0
  applyEvent(run, ctx, done('b/0', 'call', 'require_anchor', 'rail_move_safe'))
  assert.equal(doneCount.value, 1, '嵌套帧内 done 变更未被 reactive 追踪 (ctx.stack 持了 raw 对象?)')
  assert.ok(evals >= 2, 'computed 未因嵌套变更重算')
})
