/**
 * 功能: L1 权威板位置投影(调度器快照)的测试.
 *
 * 三条最容易写错、错了又看不出来的:
 *   1. revision **只能比大小不能判连续** —— 它在节流 return 之前自增, 必然跳号;
 *      回退意味着后端重启, 也要接受。
 *   2. 仓态(feedlift/waste)**不建独立板实例** —— 否则与料仓堆叠双记账, 画面上多出一块浮板。
 *   3. 停放位冲突要**两块都画且报出来**, 不许去重 —— 那是账本异常, 藏起来只会让人查不到。
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { PlateLedgerStore } from '../../src/three-d/twin/bindings/PlateLedgerStore.js'

/** 造一帧调度器快照。 */
function snapshot({ revision = 1, samples = [] } = {}) {
  return {
    now: 0,
    revision,
    batches: [{
      batch_id: 'B-1',
      status: 'RUNNING',
      samples: samples.map((s, i) => ({
        sample_id: s.id, seq: i + 1, status: s.status || 'ACTIVE',
        tank: s.tank ?? null, position: s.position, message: s.message || '',
        jobs: (s.runs || []).map((runId, k) => ({
          flow_id: `s${k}`, seq: k, run_id: runId, status: s.running ? 'RUNNING' : 'DONE',
        })),
      })),
    }],
  }
}

test('仓态不建板实例(否则与料仓堆叠双记账)', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'feedlift', status: 'PENDING' },
      { id: 'S-02', position: 'waste', status: 'DONE' },
      { id: 'S-03', position: 'spot_seat' },
    ],
  }))
  assert.deepEqual(store.plates().map((p) => p.sampleId), ['S-03'])
  assert.equal(store.all().length, 3, '仓态样品仍进诊断表, 只是不画独立板')
})

test('HOLD / ABORTED 的板照画并标注 —— 中止不会让板凭空消失', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'tank:3', status: 'HOLD' },
      { id: 'S-02', position: 'scrape_table', status: 'ABORTED' },
    ],
  }))
  const plates = store.plates()
  assert.equal(plates.length, 2)
  assert.ok(plates.every((p) => p.needsAttention), '两者都该被标成待人工处理')
  assert.equal(plates[0].tank, 3)
})

test('revision: 递增接受 / 相等幂等丢弃', () => {
  const store = new PlateLedgerStore()
  assert.equal(store.push(snapshot({ revision: 5, samples: [{ id: 'S-01', position: 'spot_seat' }] })), true)
  assert.equal(store.push(snapshot({ revision: 5, samples: [{ id: 'S-99', position: 'tank:1' }] })), false,
    '同 revision 不该重算')
  assert.deepEqual(store.plates().map((p) => p.sampleId), ['S-01'])
  assert.equal(store.push(snapshot({ revision: 6, samples: [{ id: 'S-02', position: 'tank:1' }] })), true)
  assert.deepEqual(store.plates().map((p) => p.sampleId), ['S-02'])
})

test('revision: 跳号必须照常接受(它在节流 return 之前自增, 连续性判据是错的)', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({ revision: 3, samples: [{ id: 'S-01', position: 'spot_seat' }] }))
  assert.equal(store.push(snapshot({ revision: 47, samples: [{ id: 'S-01', position: 'tank:2' }] })), true)
  assert.equal(store.get('S-01').position, 'tank:2')
})

test('revision: 回退视为后端重启, 接受并置重同步标志', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({ revision: 120, samples: [{ id: 'S-01', position: 'tank:2' }] }))
  assert.equal(store.consumeResync(), false)
  assert.equal(store.push(snapshot({ revision: 1, samples: [{ id: 'S-01', position: 'spot_seat' }] })), true)
  assert.equal(store.consumeResync(), true, '重启后调用方应把板 snap 回 L1 并清 L2 轨迹')
  assert.equal(store.consumeResync(), false, '标志读后即清')
})

test('停放位冲突: 两块都留, 且如实报出来', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'spot_seat' },
      { id: 'S-02', position: 'spot_seat' },
      { id: 'S-03', position: 'tank:1' },
    ],
  }))
  assert.equal(store.plates().length, 3, '冲突时不许去重')
  const conflicts = store.conflicts()
  assert.equal(conflicts.length, 1)
  assert.equal(conflicts[0].slot, 'spot_seat')
  assert.deepEqual(conflicts[0].sampleIds.sort(), ['S-01', 'S-02'])
  assert.equal(store.status().conflicts, 1)
})

test('未识别的位置词不迁移、不猜, 单独记账供 HUD 报警', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'some_new_slot' },
      { id: 'S-02', position: 'tank:?' },
      { id: 'S-03', position: 'tank:5' },
    ],
  }))
  assert.deepEqual(store.plates().map((p) => p.sampleId), ['S-03'])
  const unknown = store.unknownPositions()
  assert.equal(unknown.length, 2)
  assert.deepEqual(unknown.map((u) => u.position).sort(), ['some_new_slot', 'tank:?'])
})

test('run_id → sample_id 索引: 子脚本沿用父 run_id, 所以深处的事件也归得对', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'spot_seat', runs: ['run-a', 'run-b'] },
      { id: 'S-02', position: 'tank:4', runs: ['run-c'] },
    ],
  }))
  assert.equal(store.sampleIdForRun('run-b'), 'S-01')
  assert.equal(store.sampleIdForRun('run-c'), 'S-02')
  assert.equal(store.sampleIdForRun('run-未知'), '', '归属不到时给空串, 由调用方落到 inferred 板')
})

test('断连冻结: 不清空、不回零', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({ samples: [{ id: 'S-01', position: 'tank:6' }] }))
  store.markDisconnected()
  assert.equal(store.plates().length, 1, '断连后必须保留末态')
  assert.equal(store.status().frozen, true)
})

test('陈旧判定按快照年龄, 首帧之前 received=false', () => {
  const store = new PlateLedgerStore({ staleMs: 1000 })
  assert.equal(store.status(0).received, false)
  store.push(snapshot({ samples: [{ id: 'S-01', position: 'tank:1' }] }), 10_000)
  assert.equal(store.status(10_500).stale, false)
  assert.equal(store.status(12_000).stale, true)
})

test('在跑的样品要含仓态 —— 板从上料仓被吸起时账本正是记着 feedlift', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({
    samples: [
      { id: 'S-01', position: 'feedlift', runs: ['run-1'], running: true },
      { id: 'S-02', position: 'tank:3', runs: ['run-2'] },
    ],
  }))
  // plates() 按设计滤掉仓态; runningSamples() 不能跟着滤, 否则最常见的那一步恢复不了
  assert.deepEqual(store.plates().map((e) => e.sampleId), ['S-02'])
  assert.deepEqual(store.runningSamples().map((e) => e.sampleId), ['S-01'])
})

test('没有 RUNNING 作业时 runningSamples 为空(调用方据此退回推断板)', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({ samples: [{ id: 'S-01', position: 'tank:1', runs: ['run-1'] }] }))
  assert.deepEqual(store.runningSamples(), [])
})

test('残缺输入不抛: 无 batches / 空样品 / 缺 sample_id', () => {
  const store = new PlateLedgerStore()
  assert.equal(store.push(null), false)
  assert.equal(store.push({}), false)
  assert.equal(store.push({ batches: [] }), true)
  assert.equal(store.plates().length, 0)
  store.push({ revision: 2, batches: [{ batch_id: 'B', samples: [{ position: 'tank:1' }] }] })
  assert.equal(store.plates().length, 0, '没有 sample_id 的行直接跳过')
})

// ── coverage / identity: "缺"与"空"的分界 ────────────────────────────────────
//
// 沙盒不装调度器, 缸里有哪块板它真不知道。若把"不知道"报成"那里没有板",
// PlateBinding._syncLedger 会把那里的板回收掉 —— 板消失且无任何线索, 比 404 更危险。
// 调度器快照没有这两个字段, 于是 live 逐字维持原行为 —— 下面第一条就是那道护栏。

test('无 coverage 字段(调度器快照)= 全覆盖: live 的回收规则逐字不变', () => {
  const store = new PlateLedgerStore()
  store.push(snapshot({ samples: [{ id: 'S-01', position: 'spot_seat' }] }))
  assert.equal(store.coveredSlots(), null, '没声明就是全覆盖')
  assert.equal(store.covers('tank:3'), true)
  assert.equal(store.covers('carried'), true)
  assert.equal(store.covers('随便什么没见过的落点'), true)
  assert.equal(store.syntheticIdentity(), false)
})

test('有 coverage 时按集合判定, 覆盖外一律 false', () => {
  const store = new PlateLedgerStore()
  const frame = snapshot({ samples: [{ id: 'sim:seat:spot_seat', position: 'spot_seat' }] })
  frame.identity = 'synthetic'
  frame.coverage = { slots: ['spot_seat', 'scrape_table', 'feedlift', 'waste'] }
  store.push(frame)
  assert.equal(store.covers('spot_seat'), true)
  assert.equal(store.covers('waste'), true)
  assert.equal(store.covers('tank:3'), false, '缸不在覆盖面内')
  assert.equal(store.covers('carried'), false, '在途也不在')
  assert.equal(store.syntheticIdentity(), true)
})

test('合成身份的快照不产 run 索引与在跑样品(它压根没有 jobs)', () => {
  const store = new PlateLedgerStore()
  const frame = snapshot({ samples: [{ id: 'sim:seat:spot_seat', position: 'spot_seat' }] })
  frame.identity = 'synthetic'
  frame.coverage = { slots: ['spot_seat'] }
  store.push(frame)
  assert.equal(store.sampleIdForRun('run-1'), '')
  assert.deepEqual(store.runningSamples(), [])
  assert.deepEqual(store.plates().map((e) => e.sampleId), ['sim:seat:spot_seat'])
})

test('coverage 随帧更新: 后一帧撤掉声明即回到全覆盖', () => {
  const store = new PlateLedgerStore()
  const first = snapshot({ revision: 1, samples: [{ id: 'S-01', position: 'spot_seat' }] })
  first.coverage = { slots: ['spot_seat'] }
  first.identity = 'synthetic'
  store.push(first)
  assert.equal(store.covers('tank:1'), false)

  store.push(snapshot({ revision: 2, samples: [{ id: 'S-01', position: 'spot_seat' }] }))
  assert.equal(store.covers('tank:1'), true, '换回调度器快照就该恢复全覆盖')
  assert.equal(store.syntheticIdentity(), false)
})

test('工艺阶段: 载荷显式给的优先, live 没有该字段则仍从 jobs 推导', () => {
  const store = new PlateLedgerStore()
  // 仿真沙盒: 投影直读账本 seat_occupancy.stage, jobs 恒空
  store.push({
    revision: 1,
    identity: 'synthetic',
    coverage: { slots: ['spot_seat', 'tank:3'], uncovered: ['carried'] },
    batches: [{
      batch_id: '', samples: [
        { sample_id: 'sim:seat:tank_3', position: 'tank:3', stage: 'developed', jobs: [] },
        { sample_id: 'sim:seat:spot_seat', position: 'spot_seat', stage: 'spotted', jobs: [] },
      ],
    }],
  })
  assert.equal(store.get('sim:seat:tank_3').stage, 'developed')
  assert.equal(store.get('sim:seat:spot_seat').stage, 'spotted')

  // 写错的阶段值一律忽略, 退回推导 —— 不把脏值画上板面
  store.push({
    revision: 2,
    batches: [{ batch_id: '', samples: [
      { sample_id: 'x', position: 'spot_seat', stage: '乱写的', jobs: [] },
    ] }],
  })
  assert.equal(store.get('x').stage, 'blank')
})

test('★live 护栏: 调度器快照没有 stage 字段时, 阶段仍逐字由 jobs 推导', () => {
  const store = new PlateLedgerStore()
  store.push({
    revision: 1,
    batches: [{
      batch_id: 'B1', samples: [{
        sample_id: 'S1', position: 'spot_seat',
        jobs: [
          { script: 'sampling_execute', status: 'DONE' },
          { script: 'develop_execute', status: 'DONE' },
          { script: 'photoscrape_process', status: 'PENDING' },
        ],
      }],
    }],
  })
  // DONE 的最高里程碑 = developed; PENDING 的不算 —— 与改动前完全一致
  assert.equal(store.get('S1').stage, 'developed')
})
