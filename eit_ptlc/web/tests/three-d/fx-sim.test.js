/**
 * 功能: 效果预览沙盒的模拟状态驱动器单测 —— 剧本确定性/覆写/自愈/定格.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  createSimFeed,
  RUN_SCRIPT,
  STEP_STARTS,
  SCRIPT_TOTAL,
  ERROR_AT,
} from '../../src/three-d-fx-preview/simFeed.js'

const STATIONS = ['RAIL', 'ROBOT', 'DEVELOP', 'SAMPLING', 'PHOTOSCRAPE', 'COLLECT',
  'FEEDLIFT', 'STAGINGA', 'PUMP', 'RACK', 'TOOLING']
const TELEMETRY = STATIONS.filter((id) => id !== 'RACK' && id !== 'TOOLING')

/** 造一个驱动器 */
function make(overrides = {}) {
  return createSimFeed({ stationIds: STATIONS, telemetryIds: TELEMETRY, ...overrides })
}

test('idle 剧本: 有遥测者 ok, 无遥测者 unknown, PUMP 凑 offline 样例', () => {
  const feed = make({ scenario: 'idle' })
  feed.tick(5)
  const all = feed.getAll()
  assert.equal(all.DEVELOP.health, 'ok')
  assert.equal(all.RACK.health, 'unknown')
  assert.equal(all.TOOLING.health, 'unknown')
  assert.equal(all.PUMP.health, 'offline')
})

test('running 剧本: 工作步该工位忙, 搬运步 RAIL/ROBOT 忙且发 transfer 事件', () => {
  const feed = make({ scenario: 'running' })
  const transfers = []
  feed.onTransfer((t) => transfers.push(t))

  feed.tick(1) // 步0: FEEDLIFT work (0..4s)
  assert.equal(feed.get('FEEDLIFT').health, 'busy')
  assert.equal(feed.get('FEEDLIFT').action, 'feedlift.feed_upper')
  assert.ok(feed.get('FEEDLIFT').progress > 0.2 && feed.get('FEEDLIFT').progress < 0.3)

  feed.tick(4) // t=5, 步1: FEEDLIFT->SAMPLING transfer (4..7s)
  assert.equal(feed.get('RAIL').health, 'busy')
  assert.equal(feed.get('ROBOT').health, 'busy')
  assert.equal(feed.get('FEEDLIFT').health, 'ok')
  assert.deepEqual(transfers, [{ from: 'FEEDLIFT', to: 'SAMPLING' }])

  // 跑满一整圈回到步0, 途中每个 transfer 各发一次
  let guard = 0
  while (feed.getTime() < SCRIPT_TOTAL + 1 && guard < 1000) {
    feed.tick(0.5)
    guard += 1
  }
  const transferCount = RUN_SCRIPT.filter((s) => s.kind === 'transfer').length
  assert.ok(transfers.length >= transferCount, `一圈应至少 ${transferCount} 次搬运, 实际 ${transfers.length}`)
})

test('确定性: 两个实例喂同样的 tick 序列, 状态逐字相同', () => {
  const a = make({ scenario: 'running' })
  const b = make({ scenario: 'running' })
  for (let i = 0; i < 100; i += 1) {
    a.tick(0.37)
    b.tick(0.37)
  }
  assert.deepEqual(JSON.parse(JSON.stringify(a.getAll())), JSON.parse(JSON.stringify(b.getAll())))
})

test('手动覆写: set 后剧本不再碰该工位, clearOverride 恢复', () => {
  const feed = make({ scenario: 'running' })
  feed.set('DEVELOP', { health: 'error' })
  assert.equal(feed.get('DEVELOP').health, 'error')
  assert.equal(feed.get('DEVELOP').manual, true)

  // 推进到 DEVELOP 的工作步(剧本本该置 busy), 覆写仍应压住
  const developStart = STEP_STARTS[RUN_SCRIPT.findIndex((s) => s.station === 'DEVELOP')]
  feed.tick(developStart + 1)
  assert.equal(feed.get('DEVELOP').health, 'error')

  feed.clearOverride('DEVELOP')
  assert.equal(feed.get('DEVELOP').health, 'busy')
  assert.equal(feed.get('DEVELOP').manual, false)
})

test('injectError: 到时自愈回剧本', () => {
  const feed = make({ scenario: 'idle', errorRecoverS: 10 })
  feed.injectError('SAMPLING')
  assert.equal(feed.get('SAMPLING').health, 'error')
  feed.tick(9)
  assert.equal(feed.get('SAMPLING').health, 'error')
  feed.tick(2)
  assert.equal(feed.get('SAMPLING').health, 'ok')
})

test('error 剧本: 定点时刻后 DEVELOP 故障冻结, 其余回待机', () => {
  const feed = make({ scenario: 'error' })
  feed.tick(ERROR_AT + 1)
  assert.equal(feed.get('DEVELOP').health, 'error')
  assert.equal(feed.get('RAIL').health, 'ok')
  assert.equal(feed.get('FEEDLIFT').health, 'ok')
  // 再怎么推进也不变(冻结语义)
  feed.tick(100)
  assert.equal(feed.get('DEVELOP').health, 'error')
})

test('showcase 摆拍: 一帧五态全齐且不随时间漂', () => {
  const feed = make({ scenario: 'showcase' })
  const healths = () => new Set(Object.values(feed.getAll()).map((s) => s.health))
  const first = JSON.stringify(feed.getAll())
  assert.deepEqual([...healths()].sort(), ['busy', 'error', 'offline', 'ok', 'unknown'])
  feed.tick(37)
  assert.equal(JSON.stringify(feed.getAll()), first)
})

test('jumpToStep + freeze: 定格在指定步, tick 不再推进', () => {
  const feed = make({ scenario: 'running' })
  feed.jumpToStep(2) // SAMPLING work
  assert.equal(feed.get('SAMPLING').health, 'busy')
  feed.freeze(true)
  const t0 = feed.getTime()
  feed.tick(10)
  assert.equal(feed.getTime(), t0)
  assert.equal(feed.get('SAMPLING').health, 'busy')
})

test('onChange: 首次订阅即回放全量, 之后只发变化', () => {
  const feed = make({ scenario: 'running' })
  const batches = []
  feed.onChange((changes) => batches.push(changes))
  assert.equal(batches.length, 1)
  assert.equal(batches[0].length, STATIONS.length)

  feed.tick(0.001) // 进度变化 <1%, 不应发
  assert.equal(batches.length, 1)
  feed.tick(4.5) // 跨步: FEEDLIFT ok + RAIL/ROBOT busy
  assert.equal(batches.length, 2)
  const changedIds = new Set(batches[1].map((c) => c.id))
  assert.ok(changedIds.has('FEEDLIFT') && changedIds.has('RAIL') && changedIds.has('ROBOT'))
})
