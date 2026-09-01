/**
 * 功能: 夹爪三态与"是不是取料脚本"两个判据的闭集行为.
 *
 * 这两个判据此前散在四处各写一遍并且已经漂了 (TwinFeed 用 /_pick/, TrayBinding 用
 * /_pick$/, 于是 robot_scrape_holder_pick_enter 在两层得到相反的答案), 开度那边更糟:
 * 实时页有完整三态, 演示近似档只有 0/1 两态, 夹住托盘时演成空爪紧闭把物料捏穿。
 * 收成一份之后, 这里就是它唯一的看门狗。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  gripperHome, gripperTarget, isPickScript, leafScript,
} from '../../src/three-d/gripSemantics.js'

/** 与 device-manifest 的 linkages[] 同形 (取真机实测值, 保持量级真实) */
const VIAL = { id: 'rob_grip_vial', holdValue: 0.101, inputRange: [0, 1] }
const PLATE96 = { id: 'rob_grip_plate96', holdValue: 0.288, inputRange: [0, 1] }

test('isPickScript: 分段取料脚本 (*_pick_enter) 也算取料', () => {
  // 站侧取料被拆成 enter/exit 两段, 夹爪动作在 enter 那一半。
  // 锚定尾部的 /_pick$/ 会把它漏掉 —— 那正是 TrayBinding 与 TwinFeed 分歧的来源。
  assert.equal(isPickScript('robot_individual_pick'), true)
  assert.equal(isPickScript('robot_group_rack_pick'), true)
  assert.equal(isPickScript('robot_scrape_holder_pick_enter'), true)
  assert.equal(isPickScript('robot_collect_holder_pick_enter'), true)
})

test('isPickScript: 名字里带 _pick 但没有夹爪动作的那些不算', () => {
  // robot_*_pick_exit 是"持件退出"那一半, 全程不动夹爪; robot_*_put_* 是放料。
  // 只写 /_pick/ (不锚定) 会把 pick_exit 误判成取料。
  assert.equal(isPickScript('robot_scrape_holder_pick_exit'), false)
  assert.equal(isPickScript('robot_feed_lift_pick_exit'), false)
  assert.equal(isPickScript('robot_individual_put'), false)
  assert.equal(isPickScript('robot_collect_bottle_put'), false)
  assert.equal(isPickScript(''), false)
  assert.equal(isPickScript(undefined), false)
})

test('leafScript: 近似档给的是展开路径, 实时链给的是脚本名, 判据要对同一个东西', () => {
  assert.equal(leafScript('collect_load/transfer_bottle/robot_individual_pick'),
    'robot_individual_pick')
  assert.equal(leafScript('robot_individual_pick'), 'robot_individual_pick')
  assert.equal(leafScript(''), '')
})

test('gripperTarget: 三态各归其位', () => {
  assert.equal(gripperTarget('gripper-open', VIAL, true), 0, '张开永远回 GLB 基准位')
  assert.equal(gripperTarget('gripper-open', VIAL, false), 0)
  assert.equal(gripperTarget('gripper-close', VIAL, true), 0.101, '夹住载荷取 holdValue')
  assert.equal(gripperTarget('gripper-close', VIAL, false), 1, '空爪紧闭取值域上界')
  assert.equal(gripperTarget('gripper-close', PLATE96, true), 0.288)
})

test('gripperTarget: 空爪紧闭取 inputRange 上界而不是写死的 1', () => {
  // col_clamp 的 outputRange 就是递减的 —— 值域不天然是 [0,1], 写死 1 会在有人改值域
  // 那天安静地发一个越界值。
  const odd = { id: 'odd_grip', holdValue: 0.4, inputRange: [0, 2.5] }
  assert.equal(gripperTarget('gripper-close', odd, false), 2.5)
})

test('gripperTarget: 缺 holdValue 时退回空爪紧闭并只告警一次', () => {
  const broken = { id: 'no_hold_grip', inputRange: [0, 1] }
  const seen = []
  const original = console.warn
  console.warn = (msg) => seen.push(String(msg))
  try {
    assert.equal(gripperTarget('gripper-close', broken, true), 1)
    assert.equal(gripperTarget('gripper-close', broken, true), 1)
  } finally {
    console.warn = original
  }
  assert.equal(seen.length, 1, '同一个联动组只该喊一次, 不刷屏')
  assert.match(seen[0], /holdValue/)
})

test('gripperHome: 取对侧端点, 与目标开到多少无关', () => {
  // 从前写的是 `target > 0.5 ? 0 : 1`, 在 target=0.101 (小夹爪夹持) 时算出 home=1,
  // 正好反了 —— 通道会从紧闭缓动到夹持, 画面上爪子先合死再张开一点。
  assert.equal(gripperHome('gripper-close', VIAL), 0, '合爪的起点必然是张开')
  assert.equal(gripperHome('gripper-close', PLATE96), 0)
  assert.equal(gripperHome('gripper-open', VIAL), 1, '张开的起点必然是闭合')
  assert.equal(gripperHome('gripper-open', { id: 'odd', inputRange: [0, 2.5] }), 2.5)
})
