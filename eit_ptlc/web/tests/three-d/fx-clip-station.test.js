/**
 * 功能: 片段步骤 -> 工位推导纯函数单测.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildStationLookup, stationOfStep, STATION_ALIAS } from '../../src/three-d-fx-preview/clipStation.js'

/** 迷你 manifest(形态照 device-manifest.official-cr5.json) */
const MANIFEST = {
  stations: [
    { id: 'RAIL', glbNode: 'ST_RAIL' },
    { id: 'ROBOT', glbNode: 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT' },
    { id: 'DEVELOP', glbNode: 'ST_DEVELOP' },
    { id: 'SAMPLING', glbNode: 'ST_SAMPLING' },
    { id: 'COLLECT', glbNode: 'ST_COLLECT' },
    { id: 'PHOTOSCRAPE', glbNode: 'ST_PHOTOSCRAPE' },
    { id: 'PUMP', glbNode: 'ST_PUMP' },
  ],
  axes: [
    { id: 'axis_11y', station: 'RAIL' },
    { id: 'axis_5z', station: 'SAMPLING' },
    { id: 'axis_1z', station: 'FEEDLIFT' },
  ],
  actuators: [
    { id: 'col_lift', node: 'ST_COLLECT/ACTUATOR_COL_LIFT' },
    { id: 'ps_press', node: 'ST_PHOTOSCRAPE/ACTUATOR_PS_PRESS' },
  ],
  linkages: [
    { id: 'rob_grip_vial', members: [{ node: 'ST_RAIL/AXIS_AXIS_11Y/CARRIAGE/ST_ROBOT/GRIP_L' }] },
    { id: 'dev_t1_cyl1', members: [{ node: 'ST_DEVELOP/展缸架总装-2/CYL_1' }] },
  ],
  lights: [{ id: 'uv_scrape', glbNode: 'ST_PHOTOSCRAPE/STATIC_MAT_UV_LAMP' }],
  tanks: [{ id: 'tank1', glbNode: 'ST_DEVELOP/展缸架总装-2/TANK_1' }],
  pumpSyringe: { pumps: [{ id: 'DEV1', station: 'PUMP' }] },
}

/** 造一个单步文档 */
function docOf(doStep) {
  return { steps: [{ label: 'x', dur: 1, do: doStep }] }
}

const lookup = buildStationLookup(MANIFEST)

test('axis -> 轴表反查工位', () => {
  assert.equal(stationOfStep(docOf({ axis: { id: 'axis_5z', to_mm: 0 } }), 0, lookup), 'SAMPLING')
  assert.equal(stationOfStep(docOf({ axis: { id: 'axis_11y', to_mm: 500 } }), 0, lookup), 'RAIL')
  assert.equal(stationOfStep(docOf({ axis: { id: 'axis_1z', to_mm: 0 } }), 0, lookup), 'FEEDLIFT')
})

test('robot_point/tool/joints/attach/detach -> ROBOT', () => {
  assert.equal(stationOfStep(docOf({ robot_point: { id: 'p1' } }), 0, lookup), 'ROBOT')
  assert.equal(stationOfStep(docOf({ tool: { action: 'lock', id: 'TOOL_SUCTION' } }), 0, lookup), 'ROBOT')
  assert.equal(stationOfStep(docOf({ joints: { to_deg: [0, 0, 0, 0, 0, 0] } }), 0, lookup), 'ROBOT')
  assert.equal(stationOfStep(docOf({ attach: { id: 'INV_X', parent: 'TOOL_MOUNT' } }), 0, lookup), 'ROBOT')
})

test('actuator/linkage -> 节点路径最后一个 ST_* 段', () => {
  assert.equal(stationOfStep(docOf({ actuator: { id: 'col_lift', to: 1 } }), 0, lookup), 'COLLECT')
  assert.equal(stationOfStep(docOf({ actuator: { id: 'ps_press', to: 1 } }), 0, lookup), 'PHOTOSCRAPE')
  // 机械臂夹爪路径穿过 ST_RAIL, 必须取"最后一个"才归 ROBOT
  assert.equal(stationOfStep(docOf({ linkage: { id: 'rob_grip_vial', to: 1 } }), 0, lookup), 'ROBOT')
  assert.equal(stationOfStep(docOf({ linkage: { id: 'dev_t1_cyl1', to: 0 } }), 0, lookup), 'DEVELOP')
})

test('liquid -> 展缸归 DEVELOP, 泵归 PUMP; light 按节点路径', () => {
  assert.equal(stationOfStep(docOf({ liquid: { id: 'tank1', to_ml: 20 } }), 0, lookup), 'DEVELOP')
  assert.equal(stationOfStep(docOf({ liquid: { id: 'DEV1', to_ml: 5 } }), 0, lookup), 'PUMP')
  assert.equal(stationOfStep(docOf({ light: { id: 'uv_scrape', to: 1 } }), 0, lookup), 'PHOTOSCRAPE')
})

test('显示别名: 地轨归入机械臂组(第三轮定夺)', () => {
  const raw = stationOfStep(docOf({ axis: { id: 'axis_11y', to_mm: 500 } }), 0, lookup)
  assert.equal(raw, 'RAIL') // 模型层仍是 RAIL
  assert.equal(STATION_ALIAS[raw], 'ROBOT') // 消费端折算到机械臂组
})

test('camera/wait/state 不指向工位; 越界/空步安全', () => {
  assert.equal(stationOfStep(docOf({ wait: {} }), 0, lookup), null)
  assert.equal(stationOfStep(docOf({ camera: { preset: 'iso' } }), 0, lookup), null)
  assert.equal(stationOfStep(docOf({ state: { id: 'X', value: true } }), 0, lookup), null)
  assert.equal(stationOfStep({ steps: [] }, 5, lookup), null)
  assert.equal(stationOfStep(null, 0, lookup), null)
})
