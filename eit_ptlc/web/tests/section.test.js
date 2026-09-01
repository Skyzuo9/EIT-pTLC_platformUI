// section.js: route.path → 栏 key 的单一真源 (底栏折叠默认表以此为键, 推导漂移即默认值错页)
import test from 'node:test'
import assert from 'node:assert/strict'
import { sectionOf } from '../src/utils/section.js'

test('sectionOf: 各路由前缀 → 栏 key (含带参数的深链)', () => {
  assert.equal(sectionOf('/plc'), 'plc')
  assert.equal(sectionOf('/plc/pou/60_actions/x'), 'plc')
  assert.equal(sectionOf('/nodes/robot'), 'nodes')
  assert.equal(sectionOf('/3d/live'), 'three_d')
  assert.equal(sectionOf('/3d/motion/rail.move'), 'three_d')
  assert.equal(sectionOf('/library/action/pick'), 'action')
  assert.equal(sectionOf('/library/operation/op1'), 'operation')
  assert.equal(sectionOf('/points/anchor/p1'), 'points')
  assert.equal(sectionOf('/vision'), 'vision')
  assert.equal(sectionOf('/water_level/3'), 'water_level')
  assert.equal(sectionOf('/planner'), 'planner')
  assert.equal(sectionOf('/schedule'), 'schedule')               // 调度编排 (第三层) 独立成栏
  assert.equal(sectionOf('/schedule/parallel_v1'), 'schedule')
  assert.equal(sectionOf('/experiment/batch/b1'), 'scheduler')   // 实验栏路由前缀是 /experiment
  assert.equal(sectionOf('/experiment'), 'scheduler')
  assert.equal(sectionOf('/materials/tray'), 'materials')
  assert.equal(sectionOf('/runs/r-123'), 'runs')
})

test('sectionOf: 根路径与未知路径兜底 action (与原 RailNav/ExplorerDock 行为一致)', () => {
  assert.equal(sectionOf('/'), 'action')
  assert.equal(sectionOf('/no-such-page'), 'action')
})
