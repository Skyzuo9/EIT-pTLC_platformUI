/**
 * 功能: 右键"单击 vs 拖拽"判定器的单测.
 *
 * 值得单测的理由: 判定错一格, 要么平移视角时菜单乱弹, 要么右键点不出菜单 ——
 * 两种都是高频操作路径上的体验硬伤.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { createRightClickTracker } from '../../src/three-d/common/rightClick.js'

test('阈值内右键单击 -> 弹菜单', () => {
  const tracker = createRightClickTracker(4)
  tracker.onPointerDown({ button: 2, clientX: 100, clientY: 100 })
  assert.equal(tracker.shouldOpen({ clientX: 102, clientY: 101 }), true)
})

test('拖拽超阈值 -> 不弹(平移)', () => {
  const tracker = createRightClickTracker(4)
  tracker.onPointerDown({ button: 2, clientX: 100, clientY: 100 })
  assert.equal(tracker.shouldOpen({ clientX: 140, clientY: 120 }), false)
})

test('非右键按下被忽略', () => {
  const tracker = createRightClickTracker()
  tracker.onPointerDown({ button: 0, clientX: 100, clientY: 100 })
  assert.equal(tracker.shouldOpen({ clientX: 100, clientY: 100 }), false)
})

test('无 down 记录的 contextmenu(键盘菜单键)不弹', () => {
  const tracker = createRightClickTracker()
  assert.equal(tracker.shouldOpen({ clientX: 0, clientY: 0 }), false)
})

test('裁决后状态复位: 同一 down 不会二次弹', () => {
  const tracker = createRightClickTracker(4)
  tracker.onPointerDown({ button: 2, clientX: 10, clientY: 10 })
  assert.equal(tracker.shouldOpen({ clientX: 10, clientY: 10 }), true)
  assert.equal(tracker.shouldOpen({ clientX: 10, clientY: 10 }), false)
})

test('reset 强制清除', () => {
  const tracker = createRightClickTracker(4)
  tracker.onPointerDown({ button: 2, clientX: 10, clientY: 10 })
  tracker.reset()
  assert.equal(tracker.shouldOpen({ clientX: 10, clientY: 10 }), false)
})
