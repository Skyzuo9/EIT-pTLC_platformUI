/**
 * 功能: TwinFeed 夹爪持料包络状态机测试(三态闭合的持料位来源) + 节点入参 enter→done 配对.
 *
 * 判据(用户拍板): robot_*_pick 脚本里完成的 gripper-close → 持料; 任意 gripper-open
 * 完成 → 释放。机构 id 由 manifest realtime.mechanisms[].controllerTool(2=大爪/
 * 3=小爪)按当前挂载工具反查, 不再新增硬编码 id 契约。这里锁的行为: pick 内闭合
 * 置位、open 清除、面板手动闭合(无 *_pick 脚本)不置位、非 DONE/非 tool_action
 * 忽略、换刀后定位到正确机构、holding 随 sampleMechanismStates 下发。
 *
 * ⚠ 本文件的 fixture 必须发**生产事件形状**: 入参只随 `vm_node_enter` 出现,
 * `vm_node_done` 不带 args(见 operation/vm/thread.py 的 _emit_node_enter/_emit_node_done)。
 * 2026-08 之前这里的 fixture 给 done 自造了 args, 于是测试全绿而生产链恒不生效 ——
 * 那是一次典型的"测试形状与生产事件形状脱节"。改回去等于把该 BUG 放回来。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PENDING_ARGS_MAX, TwinFeed } from '../../src/three-d/twin/bindings/TwinFeed.js'

const MANIFEST = {
  stations: [],
  axes: [],
  tools: [],
  realtime: {
    mechanisms: [
      { id: 'rob_grip_plate96', station: 'robot', kind: 'gripper', rigged: true, controllerTool: 2 },
      { id: 'rob_grip_vial', station: 'robot', kind: 'gripper', rigged: true, controllerTool: 3 },
      { id: 'rob_flip_suction', station: 'robot', kind: 'rotary', rigged: true },
    ],
  },
}

function makeFeed({ tool = 2 } = {}) {
  const feed = new TwinFeed(MANIFEST)
  // telemetry 兜底路径设置挂载工具号(robot_pose 高频路径需要合法帧, 测试走低频入口)
  feed.handleEvent({ type: 'telemetry', node: 'robot', data: { tool_state: { mounted_tool: tool } } })
  // 机构先有状态条目, holding 才有宿主可附着
  feed.handleEvent({
    type: 'mechanism_state',
    ts: Date.now() / 1000,
    states: { rob_grip_plate96: { commanded: true }, rob_grip_vial: { commanded: true } },
  })
  return feed
}

/** 生产形状的一次节点执行: enter(带 args) + done(不带 args), 二者靠 run_id|script|aid 配对。 */
function emitNode(feed, {
  runId = 'run-1',
  script = 'robot_group_rack_pick',
  aid = 'b/0',
  op = 'call',
  action = 'robot.tool_action',
  status = 'DONE',
  args = { action: 'gripper-close' },
} = {}) {
  feed.handleEvent({ type: 'vm_node_enter', run_id: runId, script, aid, op, action, args })
  feed.handleEvent({ type: 'vm_node_done', run_id: runId, script, aid, op, action, status })
}

test('pick 脚本内 gripper-close 完成 → 当前工具对应机构持料', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed)
  const states = feed.sampleMechanismStates()
  assert.equal(states.rob_grip_plate96.holding, true, '大爪应持料')
  assert.notEqual(states.rob_grip_vial.holding, true, '小爪不得被波及')
})

test('生产事件形状回归: vm_node_done 不带 args 时, 入参必须来自配对的 vm_node_enter', () => {
  const feed = makeFeed({ tool: 2 })
  // 只发 done、既无 enter 也无 args: 拿不到入参就绝不能凭空置位
  feed.handleEvent({
    type: 'vm_node_done',
    run_id: 'run-x', script: 'robot_group_rack_pick', aid: 'b/0',
    op: 'call', action: 'robot.tool_action', status: 'DONE',
  })
  assert.notEqual(feed.sampleMechanismStates().rob_grip_plate96.holding, true, '无入参不得置位')

  // 补上配对的 enter 之后, 同一个 done 才生效
  emitNode(feed, { runId: 'run-x' })
  assert.equal(feed.sampleMechanismStates().rob_grip_plate96.holding, true)
})

test('gripper-open 完成 → 释放(不管在哪个脚本里)', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed)
  emitNode(feed, { script: 'robot_group_staging_put', aid: 'b/1', args: { action: 'gripper-open' } })
  const states = feed.sampleMechanismStates()
  assert.equal(states.rob_grip_plate96.holding, false, '放料后应释放')
})

test('面板手动单发 gripper-close(无 *_pick 脚本)→ 不置持料 = 空爪紧闭', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed, { script: '' })
  emitNode(feed, { script: 'robot_maintenance_check' })
  const states = feed.sampleMechanismStates()
  assert.notEqual(states.rob_grip_plate96.holding, true, '手动闭合应显示空爪紧闭')
})

test('非 DONE / 非 tool_action / 非 call 一律忽略', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed, { aid: 'b/0', status: 'ERROR' })
  emitNode(feed, { aid: 'b/1', action: 'robot.move_l' })
  emitNode(feed, { aid: 'b/2', op: 'run_script' })
  emitNode(feed, { aid: 'b/3', args: { action: 'rotary-up' } })
  const states = feed.sampleMechanismStates()
  assert.notEqual(states.rob_grip_plate96.holding, true)
})

test('挂小夹爪时置位的是 rob_grip_vial', () => {
  const feed = makeFeed({ tool: 3 })
  emitNode(feed, { script: 'robot_individual_pick' })
  const states = feed.sampleMechanismStates()
  assert.equal(states.rob_grip_vial.holding, true)
  assert.notEqual(states.rob_grip_plate96.holding, true)
})

test('裸腕(tool=0)时包络事件不落到任何机构', () => {
  const feed = makeFeed({ tool: 0 })
  emitNode(feed)
  const states = feed.sampleMechanismStates()
  assert.notEqual(states.rob_grip_plate96.holding, true)
  assert.notEqual(states.rob_grip_vial.holding, true)
})

test('流程中途取消后保持持料, 直到下一次 gripper-open(爪没松, 料就还在)', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed)
  // 取消/报错的后续节点不影响已置位的持料
  emitNode(feed, { aid: 'b/1', action: 'robot.move_l', status: 'CANCELLED' })
  assert.equal(feed.sampleMechanismStates().rob_grip_plate96.holding, true)
  emitNode(feed, { aid: 'b/2', args: { action: 'gripper-open' } })
  assert.equal(feed.sampleMechanismStates().rob_grip_plate96.holding, false)
})

test('配对表: done 消费后即清空, 不残留', () => {
  const feed = makeFeed({ tool: 2 })
  emitNode(feed)
  assert.equal(feed._pendingNodeArgs.size, 0, 'enter/done 成对后配对表应为空')
})

test('配对表: 同 (run_id, script, aid) 重入按后进先出各消一条', () => {
  const feed = makeFeed({ tool: 2 })
  const node = { run_id: 'run-1', script: 'robot_group_rack_pick', aid: 'b/0', op: 'call', action: 'robot.tool_action' }
  // 递归/重入: 外层 close, 内层 open, 内层先结束
  feed.handleEvent({ type: 'vm_node_enter', ...node, args: { action: 'gripper-close' } })
  feed.handleEvent({ type: 'vm_node_enter', ...node, args: { action: 'gripper-open' } })
  feed.handleEvent({ type: 'vm_node_done', ...node, status: 'DONE' })   // 消掉内层 open
  assert.equal(feed.sampleMechanismStates().rob_grip_plate96.holding, false)
  feed.handleEvent({ type: 'vm_node_done', ...node, status: 'DONE' })   // 消掉外层 close
  assert.equal(feed.sampleMechanismStates().rob_grip_plate96.holding, true)
  assert.equal(feed._pendingNodeArgs.size, 0)
})

test('配对表: operation_done / operation_failed 清干净该 run 的残留, 不影响其它 run', () => {
  const feed = makeFeed({ tool: 2 })
  feed.handleEvent({
    type: 'vm_node_enter', run_id: 'run-a', script: 's', aid: 'b/0',
    op: 'call', action: 'robot.tool_action', args: { action: 'gripper-close' },
  })
  feed.handleEvent({
    type: 'vm_node_enter', run_id: 'run-b', script: 's', aid: 'b/0',
    op: 'call', action: 'robot.tool_action', args: { action: 'gripper-close' },
  })
  assert.equal(feed._pendingNodeArgs.size, 2)
  feed.handleEvent({ type: 'operation_failed', run_id: 'run-a' })
  assert.equal(feed._pendingNodeArgs.size, 1, '只清 run-a')
  feed.handleEvent({ type: 'operation_done', run_id: 'run-b' })
  assert.equal(feed._pendingNodeArgs.size, 0)
})

test('配对表: 断流清空在途记录(那些 enter 永远等不到 done)', () => {
  const feed = makeFeed({ tool: 2 })
  feed.setTransportState(true)
  feed.handleEvent({
    type: 'vm_node_enter', run_id: 'run-1', script: 's', aid: 'b/0',
    op: 'call', action: 'robot.tool_action', args: { action: 'gripper-close' },
  })
  assert.equal(feed._pendingNodeArgs.size, 1)
  feed.setTransportState(false)
  assert.equal(feed._pendingNodeArgs.size, 0)
})

test('配对表: 只收 call / run_script, 且驻留量有上限', () => {
  const feed = makeFeed({ tool: 2 })
  feed.handleEvent({ type: 'vm_node_enter', run_id: 'r', script: 's', aid: 'x', op: 'assign', args: { a: 1 } })
  assert.equal(feed._pendingNodeArgs.size, 0, 'assign 之类无入参语义的节点不入表')

  for (let i = 0; i < PENDING_ARGS_MAX + 50; i += 1) {
    feed.handleEvent({
      type: 'vm_node_enter', run_id: 'r', script: 's', aid: `b/${i}`,
      op: 'call', action: 'robot.move_to_point', args: { point_id_or_robot_name: `P${i}` },
    })
  }
  assert.equal(feed._pendingNodeArgs.size, PENDING_ARGS_MAX, '超出上限按插入序淘汰最旧的')
})
