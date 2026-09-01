/**
 * 功能: 料架(及一切无遥测节点但管物料的工位)圆点判据的单测.
 *
 * 承重的是**第一条**: `verified: false` 的点位不许参与染色。
 * 货架那 12 路光电 2026-07-26 现场实测未供电、恒回 False, 后端已定案对它们一律 ok=null。
 * 若判据把它们算进来, 料架会凭一堆恒假信号显示"帐实不一"(或更糟, 显示一切正常),
 * 而真实依据其实只有上样料架那两路。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  materialHealthOf,
  stationOfLocation,
  verifiedSensorCount,
} from '../../src/three-d/twin/materialStations.js'

const MANIFEST = JSON.parse(readFileSync(
  fileURLToPath(new URL('../../../three_d/models/device-manifest.json', import.meta.url)), 'utf8'))

/** 造一条 presence 行 */
const row = (location_id, { present = true, ok = true, verified = true } = {}) =>
  ({ location_id, present, ok, verified })

test('前提: 货架与上样料架的点位都归到 RACK 工位', () => {
  assert.equal(stationOfLocation(MANIFEST, 'rack.collector.1'), 'RACK')
  assert.equal(stationOfLocation(MANIFEST, 'rack.bottle.6'), 'RACK')
  assert.equal(stationOfLocation(MANIFEST, 'feed-1'), 'RACK')
  assert.equal(stationOfLocation(MANIFEST, 'feed-2'), 'RACK')
})

test('verified:false 的点位一律不参与判定(本文件存在的理由)', () => {
  // 12 路货架光电全是未核实且 ok 为 null —— 这正是现场实况
  const snapshot = {
    presence: [
      ...['collector', 'bottle'].flatMap((kind) => [1, 2, 3, 4, 5, 6].map(
        (n) => row(`rack.${kind}.${n}`, { present: false, ok: null, verified: false }),
      )),
    ],
  }
  assert.equal(verifiedSensorCount(MANIFEST, snapshot, 'RACK'), 0)
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'unknown',
    '12 路未核实光电不该推出任何结论 —— 既不是绿也不是黄')
})

test('两路已核实光电都与账本一致 → 绿', () => {
  const snapshot = { presence: [row('feed-1'), row('feed-2')] }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'ok')
  assert.equal(verifiedSensorCount(MANIFEST, snapshot, 'RACK'), 2)
})

test('任一已核实光电与账本不符 → 黄(帐实不一)', () => {
  const snapshot = { presence: [row('feed-1'), row('feed-2', { present: false, ok: false })] }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'mismatch')
})

test('未核实的坏点不会把已核实的绿灯拽成黄', () => {
  const snapshot = {
    presence: [
      row('feed-1'), row('feed-2'),
      row('rack.collector.1', { present: false, ok: false, verified: false }),
    ],
  }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'ok',
    '未核实点位的 ok=false 也不该染色 —— 后端对它们本来就只回 null')
})

test('已核实但读不到(present 为 null) → 灰, 不冒充一致', () => {
  const snapshot = { presence: [row('feed-1', { present: null, ok: null })] }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'unknown')
})

test('实机形状: feed-1/feed-2 的 ok 恒为 null(无软件账)也要能变绿', () => {
  // 这是 2026-08-13 从真机 /api/materials 抓下来的真实形状 —— topology 把 feed 类别标了
  // "纯传感器读数, 无软件账", 后端因此算不出 ok。若判据要求 ok===true, 料架永远绿不了。
  const snapshot = {
    presence: [
      row('feed-1', { present: true, ok: null }),
      row('feed-2', { present: false, ok: null }),
      ...[1, 2, 3, 4, 5, 6].map((n) => row(`rack.collector.${n}`, { present: true, ok: null, verified: false })),
    ],
  }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'ok')
  assert.equal(verifiedSensorCount(MANIFEST, snapshot, 'RACK'), 2)
})

test('present=false 是有效读数(那里就是没东西), 不算读不到', () => {
  const snapshot = { presence: [row('feed-2', { present: false, ok: null })] }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'ok')
})

test('一路读不到、另一路明确不符 → 仍报不符(坏消息优先)', () => {
  const snapshot = {
    presence: [row('feed-1', { present: null, ok: null }), row('feed-2', { ok: false })],
  }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'mismatch')
})

test('一路读得到、另一路明确不符 → 仍报不符(不被"读得到"盖过去)', () => {
  const snapshot = { presence: [row('feed-1'), row('feed-2', { present: true, ok: false })] }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'mismatch')
})

test('没有快照 / 没有 presence / 没给工位 → 灰, 不炸', () => {
  assert.equal(materialHealthOf(MANIFEST, null, 'RACK'), 'unknown')
  assert.equal(materialHealthOf(MANIFEST, {}, 'RACK'), 'unknown')
  assert.equal(materialHealthOf(MANIFEST, { presence: [] }, 'RACK'), 'unknown')
  assert.equal(materialHealthOf(MANIFEST, { presence: [row('feed-1')] }, null), 'unknown')
  assert.equal(verifiedSensorCount(MANIFEST, null, 'RACK'), 0)
})

test('别的工位的点位不会算进本工位', () => {
  const snapshot = {
    presence: [row('feed-1'), row('staging-a', { ok: false })],
  }
  assert.equal(materialHealthOf(MANIFEST, snapshot, 'RACK'), 'ok',
    '中转位的不一致不该把料架染黄')
  assert.equal(verifiedSensorCount(MANIFEST, snapshot, 'RACK'), 1)
})
