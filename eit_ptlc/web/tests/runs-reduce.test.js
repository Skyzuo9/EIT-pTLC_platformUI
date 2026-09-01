import test from 'node:test'
import assert from 'node:assert/strict'

import { reduceRun, countSteps } from '../src/stores/runs.js'

// 事件构造小工具 (字段对照后端 thread.py 的 vm_node_enter/done)。script 缺省为根脚本 'root'。
const opStart = () => ({ type: 'operation_start', run_id: 'r1', operation: 'root', label: 'root' })
const enter = (aid, op, action, script = 'root') =>
  ({ type: 'vm_node_enter', run_id: 'r1', op, aid, action, script })
const done = (aid, op, action, script = 'root', status = 'DONE') =>
  ({ type: 'vm_node_done', run_id: 'r1', op, aid, action, script, status, message: '完成', result: {} })
const opDone = (status = 'DONE') => ({ type: 'operation_done', run_id: 'r1', status })
const opFailed = (status = 'CANCELLED') => ({ type: 'operation_failed', run_id: 'r1', status })

// 按 (script, aid) 递归查步骤节点
function findStep(steps, script, aid) {
  for (const s of steps) {
    if (s.script === script && s.step_id === aid) return s
    if (s.children && s.children.length) {
      const hit = findStep(s.children, script, aid)
      if (hit) return hit
    }
  }
  return null
}

test('最后一个叶子漏发 done: operation_done 收口后该步为 DONE 而非卡 RUNNING', () => {
  // 复刻截图结构: 根有 place_axis/place_release/rail_move_safe(run_script)/robot_suction_pick;
  // rail_move_safe 内含 require_anchor 与 rail.move。b/3 在根(place_axis)与子帧(rail.move)复用, 验证跨帧不撞键。
  // 末步 robot_suction_pick 只发 enter 不发 done —— 模拟并行取消/终止/事件总线丢最旧导致的丢 done。
  const events = [
    opStart(),
    enter('b/3', 'call', 'sampling.place_axis'), done('b/3', 'call', 'sampling.place_axis'),
    enter('b/4', 'call', 'sampling.place_release'), done('b/4', 'call', 'sampling.place_release'),
    enter('b/6', 'run_script', 'rail_move_safe'),
    enter('b/1', 'call', 'robot.require_anchor', 'rail_move_safe'), done('b/1', 'call', 'robot.require_anchor', 'rail_move_safe'),
    enter('b/3', 'call', 'rail.move', 'rail_move_safe'), done('b/3', 'call', 'rail.move', 'rail_move_safe'),
    done('b/6', 'run_script', 'rail_move_safe'),
    enter('b/7', 'call', 'robot_suction_pick'),   // 丢 done
    opDone('DONE'),
  ]
  const run = reduceRun(events)

  const last = findStep(run.steps, 'root', 'b/7')
  assert.ok(last, 'b/7 robot_suction_pick 应在根步骤中')
  assert.equal(last.status, 'DONE')   // 收口生效: 曾 RUNNING -> DONE, 不再脉冲

  // 跨帧同号 b/3 未互相污染, 且总叶子全部完成
  assert.equal(findStep(run.steps, 'root', 'b/3').action, 'sampling.place_axis')
  assert.equal(findStep(run.steps, 'rail_move_safe', 'b/3').action, 'rail.move')
  const { total, done: d } = countSteps(run.steps)
  assert.equal(total, 5)   // 叶子: place_axis, place_release, require_anchor, rail.move, robot_suction_pick
  assert.equal(d, 5)       // 无残留未完成叶子
  assert.equal(run.status, 'DONE')
})

test('operation_failed: 残留 RUNNING 步收敛为流程失败终态', () => {
  const events = [
    opStart(),
    enter('b/0', 'call', 'robot.home'),   // 只 enter, 随后流程被终止
    opFailed('CANCELLED'),
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/0').status, 'CANCELLED')
  assert.equal(run.status, 'CANCELLED')
})

test('run_script 容器漏发 done 也随终态收口', () => {
  // 子脚本入帧后其内叶子完成, 但容器自身的 run_script done 丢失 (终止在弹栈前)。
  const events = [
    opStart(),
    enter('b/2', 'run_script', 'sub'),
    enter('b/0', 'call', 'A', 'sub'), done('b/0', 'call', 'A', 'sub'),
    // 缺 done('b/2','run_script','sub')
    opDone('DONE'),
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/2').status, 'DONE')   // 容器收口
  assert.equal(findStep(run.steps, 'sub', 'b/0').status, 'DONE')
})

test('顺利路径: 已终态步骤不被收口覆盖 (REJECTED 保留, 不被冲成 DONE)', () => {
  const events = [
    opStart(),
    enter('b/0', 'call', 'A'), done('b/0', 'call', 'A'),
    enter('b/1', 'call', 'B'), done('b/1', 'call', 'B', 'root', 'REJECTED'),
    opDone('DONE'),
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/0').status, 'DONE')
  assert.equal(findStep(run.steps, 'root', 'b/1').status, 'REJECTED')   // finalize 只动 RUNNING, 不覆盖真实终态
})

const vmState = (status, script = 'root') => ({ type: 'vm_state', run_id: 'r1', status, script })

test('实时丢包: 丢 b/7(run_script) 的 done 与 operation_done, 末条终态 vm_state 仍收口', () => {
  // 复刻真实运行 630d2e1f1965 的丢包: b/7 是 run_script, 其子步 (b/0/then/*) enter/done 都到,
  // 但 b/7 自身的 done 与 operation_done 被总线丢最旧挤掉, 只剩末条 vm_state{DONE} (最新故幸存)。
  // 这正是第一版 (只在 operation_done 收口) 覆盖不到、导致 b/7 永远闪的场景。
  const events = [
    opStart(),
    enter('b/3', 'call', 'sampling.place_axis'), done('b/3', 'call', 'sampling.place_axis'),
    enter('b/7', 'run_script', 'robot_suction_pick'),
    enter('b/0/then/0', 'call', 'robot.require_anchor', 'robot_suction_pick'), done('b/0/then/0', 'call', 'robot.require_anchor', 'robot_suction_pick'),
    enter('b/0/then/1', 'call', 'robot.move_to_point', 'robot_suction_pick'), done('b/0/then/1', 'call', 'robot.move_to_point', 'robot_suction_pick'),
    // 丢: done('b/7','run_script',...) 与 operation_done 都被挤掉
    vmState('DONE'),   // 只剩末条终态 vm_state
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/7').status, 'DONE')                       // run_script 容器收口
  assert.equal(findStep(run.steps, 'robot_suction_pick', 'b/0/then/1').status, 'DONE')  // 子步保持 DONE
  assert.equal(run.status, 'DONE')
  const { total, done: d } = countSteps(run.steps)
  assert.equal(d, total)   // 无残留未完成叶子
})

test('终态 vm_state KILLED 收敛为 KILLED', () => {
  const events = [
    opStart(),
    enter('b/0', 'call', 'robot.move_to_point'),   // 丢 done, 随后被急停
    vmState('KILLED'),
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/0').status, 'KILLED')
  assert.equal(run.status, 'KILLED')
})

test('非终态 vm_state 不提前收口 (运行中步保持 RUNNING)', () => {
  const events = [
    opStart(),
    enter('b/0', 'call', 'A'),
    vmState('RUNNING'),   // 运行途中的状态帧, 不得把在飞步收成终态
    vmState('PAUSED'),
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/0').status, 'RUNNING')
  assert.notEqual(run.status, 'DONE')
})

test('operation_done 与终态 vm_state 双到达时幂等 (不重复冲写已定终态)', () => {
  const events = [
    opStart(),
    enter('b/0', 'call', 'A'), done('b/0', 'call', 'A', 'root', 'REJECTED'),
    enter('b/1', 'call', 'B'),   // 丢 b/1 done
    opDone('DONE'),              // operation_done 先收口: b/1 -> DONE
    vmState('DONE'),             // 随后终态 vm_state 再到: 不得把已 REJECTED 的 b/0 冲成 DONE
  ]
  const run = reduceRun(events)
  assert.equal(findStep(run.steps, 'root', 'b/0').status, 'REJECTED')
  assert.equal(findStep(run.steps, 'root', 'b/1').status, 'DONE')
  assert.equal(run.status, 'DONE')
})
