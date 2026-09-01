// monitorPrefs 纯逻辑: 默认表 / 覆盖优先 / 切换写显式值 / 持久化数据清洗
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MONITOR_DEFAULT_COLLAPSED, monitorCollapsedOf, sanitizeMonitorPrefs, toggledMonitorPrefs,
} from '../src/stores/monitorPrefs.js'

test('默认表: 三维与 5 个数据页收起, 其余 6 页展开', () => {
  for (const s of ['three_d', 'vision', 'water_level', 'planner', 'materials', 'runs']) {
    assert.equal(monitorCollapsedOf(s, {}), true, s)
  }
  for (const s of ['plc', 'nodes', 'action', 'operation', 'points', 'scheduler']) {
    assert.equal(monitorCollapsedOf(s, {}), false, s)
  }
  assert.equal(MONITOR_DEFAULT_COLLAPSED.length, 6)
})

test('显式覆盖优先于默认; 非布尔脏值不生效', () => {
  assert.equal(monitorCollapsedOf('vision', { vision: false }), false)
  assert.equal(monitorCollapsedOf('plc', { plc: true }), true)
  assert.equal(monitorCollapsedOf('vision', { vision: 'yes' }), true)   // 脏值 → 走默认
  assert.equal(monitorCollapsedOf('vision', null), true)
})

test('toggled: 写显式反值不删键 (双击后仍是用户接管态), 且不改入参', () => {
  const a = toggledMonitorPrefs({}, 'vision')     // 默认收起 → 展开
  assert.deepEqual(a, { vision: false })
  assert.deepEqual(toggledMonitorPrefs(a, 'vision'), { vision: true })
  assert.deepEqual(toggledMonitorPrefs({}, 'plc'), { plc: true })
  assert.deepEqual(a, { vision: false })          // 入参未被就地修改
})

test('sanitize: 只留布尔项; 非对象/数组/裸值 → 空表', () => {
  assert.deepEqual(sanitizeMonitorPrefs({ vision: false, plc: 1, x: 'y' }), { vision: false })
  assert.deepEqual(sanitizeMonitorPrefs(null), {})
  assert.deepEqual(sanitizeMonitorPrefs([true]), {})
  assert.deepEqual(sanitizeMonitorPrefs('junk'), {})
})
