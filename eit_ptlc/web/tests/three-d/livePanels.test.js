/**
 * 功能: 实时页右侧信息坞状态机的单元测试 —— 偏好修补/页签可用性/换工位页签保留.
 *
 * 只测三个导出的纯函数; useLivePanels 本体要 Vue 运行时, 由页面验收覆盖.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  GLOBAL_TABS,
  STATION_TABS,
  availableStationTabs,
  resolveStationTab,
  sanitizeDockPrefs,
} from '../../src/three-d/twin/useLivePanels.js'

test('sanitizeDockPrefs: 空/异常输入回落到安全默认', () => {
  for (const bad of [null, undefined, 0, 'x', [], { globalTab: 'nope' }]) {
    assert.deepEqual(sanitizeDockPrefs(bad), { collapsed: false, globalTab: 'machine' })
  }
})

test('sanitizeDockPrefs: 合法值原样保留', () => {
  assert.deepEqual(
    sanitizeDockPrefs({ collapsed: true, globalTab: 'viewer' }),
    { collapsed: true, globalTab: 'viewer' },
  )
})

test('sanitizeDockPrefs: collapsed 只认真正的 true (避免 "false" 字符串被当真)', () => {
  assert.equal(sanitizeDockPrefs({ collapsed: 'false' }).collapsed, false)
  assert.equal(sanitizeDockPrefs({ collapsed: 1 }).collapsed, false)
  assert.equal(sanitizeDockPrefs({ collapsed: true }).collapsed, true)
})

test('sanitizeDockPrefs: 旧版本遗留的 manual 页签被降级 (刷新页面不该自动重开手动会话)', () => {
  assert.equal(sanitizeDockPrefs({ globalTab: 'manual' }).globalTab, 'machine')
})

test('availableStationTabs: 有遥测+有动作+有物料 = 三页全开', () => {
  const station = { nodeId: 'plc.sampling', actions: ['sampling.init'] }
  assert.deepEqual(availableStationTabs(station, true), ['status', 'actions', 'material'])
})

test('availableStationTabs: 料架那类无遥测无动作的工位只留物料页', () => {
  const rack = { nodeId: null, actions: [] }
  assert.deepEqual(availableStationTabs(rack, true), ['material'])
})

test('availableStationTabs: 一页都没有时兜底给状态页 (坞不能是个空框)', () => {
  assert.deepEqual(availableStationTabs({ nodeId: null, actions: [] }, false), ['status'])
  assert.deepEqual(availableStationTabs(null, true), [])
})

test('availableStationTabs: 次序恒与 STATION_TABS 一致', () => {
  const order = STATION_TABS.map((t) => t.key)
  const got = availableStationTabs({ nodeId: 'n', actions: ['a'] }, true)
  assert.deepEqual(got, order.filter((k) => got.includes(k)))
})

test('resolveStationTab: 能保留就保留用户上次停留的页', () => {
  assert.equal(resolveStationTab('actions', ['status', 'actions', 'material']), 'actions')
})

test('resolveStationTab: 保不住则回落到第一个可用页, 而不是硬回状态页', () => {
  assert.equal(resolveStationTab('actions', ['material']), 'material')
  assert.equal(resolveStationTab('status', ['material']), 'material')
})

test('resolveStationTab: 空可用集兜底', () => {
  assert.equal(resolveStationTab('actions', []), 'status')
})

test('页签表: key 唯一且都有中文标签', () => {
  for (const tabs of [GLOBAL_TABS, STATION_TABS]) {
    const keys = tabs.map((t) => t.key)
    assert.equal(new Set(keys).size, keys.length)
    for (const tab of tabs) assert.ok(tab.label && tab.label.length)
  }
})
