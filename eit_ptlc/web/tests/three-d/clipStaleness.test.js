/**
 * 功能: 片段陈旧检测(railCalibStatus)的单元测试.
 *
 * 守的是一条只会静默出错的通路: 片段里机械臂与载荷的落点是**编译期**按当时的
 * axis_11y 标定烘死的, 标完零点不重编译片段就对不上, 而画面照播、不报任何错.
 * 这里锁住三件事: 戳一致不报警 / 戳不一致要报警 / **缺戳一律不许判绿**.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { railCalibStatus } from '../../src/three-d/anim/clipSchema.js'

/** 当前契约: 地轨零点 500 / 反向 / 行程 [-54.9, 845.1] */
function manifestOf(overrides = {}) {
  return {
    axes: [
      { id: 'axis_1z', zeroOffsetMm: -22, sign: 1, rangeMm: [-50, 550] },
      {
        id: 'axis_11y',
        zeroOffsetMm: 500,
        sign: -1,
        rangeMm: [-54.9, 845.1],
        ...overrides,
      },
    ],
  }
}

/** 与上面契约完全一致的戳 */
function stampOf(overrides = {}) {
  return {
    axis: 'axis_11y',
    zeroOffsetMm: 500,
    sign: -1,
    rangeMm: [-54.9, 845.1],
    ...overrides,
  }
}

test('戳与契约一致时判 ok, 不报警', () => {
  const result = railCalibStatus(stampOf(), manifestOf())
  assert.equal(result.state, 'ok')
  assert.equal(result.reason, '')
})

test('缺戳(旧编译器产物)判 unstamped —— 绝不默认判绿', () => {
  // source 里根本没有 railCalib 这个键 -> undefined
  const result = railCalibStatus(undefined, manifestOf())
  assert.equal(result.state, 'unstamped')
  assert.match(result.reason, /未记录/)
})

test('显式 null(编译期无场景, 没烘任何落位)判 none, 与陈旧区分开', () => {
  const result = railCalibStatus(null, manifestOf())
  assert.equal(result.state, 'none')
  assert.equal(result.reason, '')
})

test('零点变了判 stale, 且理由里带新旧值', () => {
  const result = railCalibStatus(stampOf({ zeroOffsetMm: 480 }), manifestOf())
  assert.equal(result.state, 'stale')
  assert.match(result.reason, /零点 480 → 500/)
})

test('方向翻转判 stale', () => {
  const result = railCalibStatus(stampOf({ sign: 1 }), manifestOf())
  assert.equal(result.state, 'stale')
  assert.match(result.reason, /方向/)
})

test('range 变了也判 stale —— 它在烘焙公式里参与 clamp, 能改落点', () => {
  const result = railCalibStatus(stampOf({ rangeMm: [0, 900] }), manifestOf())
  assert.equal(result.state, 'stale')
  assert.match(result.reason, /行程/)
})

test('零点差在量化步长以下不算变 —— 别把浮点噪声报成陈旧', () => {
  // 写回时零点按 1e-3 mm 量化, 比它更细的差是噪声
  const result = railCalibStatus(stampOf({ zeroOffsetMm: 500 + 1e-9 }), manifestOf())
  assert.equal(result.state, 'ok')
})

test('契约里没有该轴时判 unstamped 而非 ok', () => {
  const result = railCalibStatus(stampOf(), { axes: [{ id: 'axis_1z' }] })
  assert.equal(result.state, 'unstamped')
  assert.match(result.reason, /axis_11y/)
})

test('手写片段(整个 source 段都没有)按 none 处理, 不挂常年「未标记」', () => {
  // 调用约定: doc.source ? doc.source.railCalib : null
  const handWritten = { schema: 'ptlc.clip/v1', source: undefined }
  const stamp = handWritten.source ? handWritten.source.railCalib : null
  assert.equal(railCalibStatus(stamp, manifestOf()).state, 'none')

  // 而"有 source 却没 railCalib 键"仍是未标记 —— 两者必须区分开
  const oldCompiled = { source: { referencePointHash: 'abc' } }
  const oldStamp = oldCompiled.source ? oldCompiled.source.railCalib : null
  assert.equal(railCalibStatus(oldStamp, manifestOf()).state, 'unstamped')
})

test('戳里没写 axis 时默认按 axis_11y 比', () => {
  const stamp = stampOf()
  delete stamp.axis
  assert.equal(railCalibStatus(stamp, manifestOf()).state, 'ok')
  assert.equal(railCalibStatus({ ...stamp, sign: 1 }, manifestOf()).state, 'stale')
})
