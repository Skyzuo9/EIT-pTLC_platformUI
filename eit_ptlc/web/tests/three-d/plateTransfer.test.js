/**
 * 功能: L2 板搬运迁移判据(末点映射)的测试.
 *
 * 最容易写错的一条: **末点只能被取放基准点更新**。取放脚本在 suction 之后还要沿
 * 进近点/过渡点原路退回, 若那些点也更新末点, 下一次 suction 就会读到被冲掉的值,
 * 板会被放到错误的工位 —— 而画面照样流畅, 没有任何指标会报警。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PlateTransferTracker } from '../../src/three-d/twin/bindings/PlateTransferTracker.js'

function makeTracker(tool = 1) {
  let mounted = tool
  const tracker = new PlateTransferTracker({ getMountedTool: () => mounted })
  return { tracker, setTool: (t) => { mounted = t } }
}

/** 一次完成的 move_to_point。 */
function movePoint(tracker, point, { runId = 'run-1' } = {}) {
  tracker.handleEvent(
    { type: 'vm_node_done', run_id: runId, op: 'call', action: 'robot.move_to_point', status: 'DONE' },
    { point_id_or_robot_name: point },
  )
}

/** 一次完成的 tool_action。 */
function toolAction(tracker, action, { runId = 'run-1', script = 'robot_suction_put' } = {}) {
  tracker.handleEvent(
    { type: 'vm_node_done', run_id: runId, script, op: 'call', action: 'robot.tool_action', status: 'DONE' },
    { action },
  )
}

test('料仓取板: P21 → suction-on 得到 feedlift 的 pick', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P5')          // 过渡点, 不更新末点
  movePoint(tracker, 'P21')
  toolAction(tracker, 'suction-on', { script: 'robot_feed_lift_pick_enter' })
  assert.deepEqual(
    tracker.consumeTransfers().map((t) => [t.kind, t.slot]),
    [['pick', 'feedlift']],
  )
})

test('八个缸各自对到自己的点位 P11..P18', () => {
  for (let n = 1; n <= 8; n += 1) {
    const { tracker } = makeTracker()
    movePoint(tracker, `P${10 + n}`)
    toolAction(tracker, 'suction-off', { script: 'robot_tank_put' })
    assert.deepEqual(tracker.consumeTransfers().map((t) => t.slot), [`tank:${n}`])
  }
})

test('末点只被取放基准点更新: 进近点与过渡点不得把它冲掉', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P4')                       // 过渡点
  movePoint(tracker, 'P86')                      // 视觉纠偏位
  movePoint(tracker, 'spotting.put.approach_far')
  movePoint(tracker, 'spotting.put.approach_near')
  movePoint(tracker, 'P19')                      // ← 真正的放板基准点
  toolAction(tracker, 'suction-off')
  assert.deepEqual(tracker.consumeTransfers().map((t) => t.slot), ['spot_seat'])
})

test('退刀路径不影响下一次判定(整段取-退-放走完仍然对)', () => {
  const { tracker } = makeTracker()
  // 从刮板台取板
  movePoint(tracker, 'P65')
  toolAction(tracker, 'suction-on', { script: 'robot_suction_pick' })
  // 原路退回
  movePoint(tracker, 'scrape.plate-pick.retreat_near')
  movePoint(tracker, 'P63')
  movePoint(tracker, 'P1')
  // 再去展缸放板
  movePoint(tracker, 'P75')
  movePoint(tracker, 'P84')
  movePoint(tracker, 'tank.3.approach_near')
  movePoint(tracker, 'P13')
  toolAction(tracker, 'suction-off', { script: 'robot_tank_put' })
  assert.deepEqual(
    tracker.consumeTransfers().map((t) => [t.kind, t.slot]),
    [['pick', 'scrape_table'], ['put', 'tank:3']],
  )
})

test('已弃用的 P64 不当刮板台, 计入告警', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P64')
  toolAction(tracker, 'suction-on')
  assert.deepEqual(tracker.consumeTransfers(), [], '拿不到合法末点就不产出迁移')
  assert.equal(tracker.status().deprecatedPointHits, 1)
  assert.equal(tracker.status().mismatches, 1)
})

test('没有末点时绝不猜落点', () => {
  const { tracker } = makeTracker()
  toolAction(tracker, 'suction-on')
  assert.deepEqual(tracker.consumeTransfers(), [])
  assert.equal(tracker.status().mismatches, 1)
})

test('非 1 号刀挂载时吸盘事件一律忽略', () => {
  const { tracker, setTool } = makeTracker(2)
  movePoint(tracker, 'P19')
  toolAction(tracker, 'suction-off')
  assert.deepEqual(tracker.consumeTransfers(), [])
  setTool(1)
  toolAction(tracker, 'suction-off')
  assert.equal(tracker.consumeTransfers().length, 1)
})

test('非 DONE / 非 call / 非吸盘动作一律忽略', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P19')
  tracker.handleEvent(
    { type: 'vm_node_done', run_id: 'run-1', op: 'call', action: 'robot.tool_action', status: 'ERROR' },
    { action: 'suction-off' },
  )
  tracker.handleEvent(
    { type: 'vm_node_done', run_id: 'run-1', op: 'run_script', action: 'robot.tool_action', status: 'DONE' },
    { action: 'suction-off' },
  )
  toolAction(tracker, 'rotary-up')
  toolAction(tracker, 'gripper-close')
  assert.deepEqual(tracker.consumeTransfers(), [])
})

test('脚本入参交叉校验: 一致时不告警, 不一致时以末点为准并计数', () => {
  const { tracker } = makeTracker()
  tracker.handleEvent(
    { type: 'vm_node_enter', run_id: 'run-1', op: 'run_script', action: 'robot_suction_put' },
    { station_id: 'scrape' },
  )
  movePoint(tracker, 'P65')
  toolAction(tracker, 'suction-off')
  let out = tracker.consumeTransfers()
  assert.equal(out[0].slot, 'scrape_table')
  assert.equal(out[0].disagrees, false)
  assert.equal(tracker.status().mismatches, 0)

  // 入参说去点样座, 末点却在刮板台 → 以末点为准, 但要计数
  tracker.handleEvent(
    { type: 'vm_node_enter', run_id: 'run-1', op: 'run_script', action: 'robot_suction_put' },
    { station_id: 'spotting' },
  )
  movePoint(tracker, 'P65')
  toolAction(tracker, 'suction-off')
  out = tracker.consumeTransfers()
  assert.equal(out[0].slot, 'scrape_table', '末点是权威')
  assert.equal(out[0].disagrees, true)
  assert.equal(tracker.status().mismatches, 1)
})

test('并行两个 run 的末点互不串台', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P19', { runId: 'run-a' })
  movePoint(tracker, 'P13', { runId: 'run-b' })
  toolAction(tracker, 'suction-off', { runId: 'run-a' })
  toolAction(tracker, 'suction-on', { runId: 'run-b' })
  assert.deepEqual(
    tracker.consumeTransfers().map((t) => [t.runId, t.kind, t.slot]),
    [['run-a', 'put', 'spot_seat'], ['run-b', 'pick', 'tank:3']],
  )
})

test('流程结束清掉该 run 的末点, 不影响别的 run', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P19', { runId: 'run-a' })
  movePoint(tracker, 'P13', { runId: 'run-b' })
  tracker.handleEvent({ type: 'operation_failed', run_id: 'run-a' })
  toolAction(tracker, 'suction-off', { runId: 'run-a' })
  assert.deepEqual(tracker.consumeTransfers(), [], 'run-a 的末点已清')
  toolAction(tracker, 'suction-on', { runId: 'run-b' })
  assert.equal(tracker.consumeTransfers().length, 1, 'run-b 不受影响')
})

test('consumeTransfers 读后即清', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P19')
  toolAction(tracker, 'suction-off')
  assert.equal(tracker.consumeTransfers().length, 1)
  assert.equal(tracker.consumeTransfers().length, 0)
})

test('reset 清干净在途状态(断流后重连用)', () => {
  const { tracker } = makeTracker()
  movePoint(tracker, 'P19')
  tracker.reset()
  toolAction(tracker, 'suction-off')
  assert.deepEqual(tracker.consumeTransfers(), [])
})
