/**
 * 功能: MaterialStateStore 草稿叠加层的**性能与零回归**看门狗.
 *
 * 这是本次改造里风险最高的一处: status() 每帧被 TwinBindings 调 3 次 + TrayBinding 1 次,
 * 而 _updateMaterials / _applyTransit 都用 `snapshot === this._last` 做身份短路。
 * 叠加层若每次调用都新建对象, 就会静默打掉那两处短路, 把托盘/单件的显隐变成逐帧全量重算 ——
 * 不报错、不红灯, 只是帧率悄悄掉下去。所以下面这几条是**强制项**, 不是可选项。
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import { MaterialStateStore } from '../../src/three-d/twin/bindings/MaterialStateStore.js'
import { applyDraft, createDraft, putEntry } from '../../src/three-d/twin/materialDraft.js'

function rawEvent(seq = 1) {
  const cells = []
  for (let hole = 1; hole <= 6; hole += 1) {
    cells.push({
      kind: 'collector', plate: 1, hole, state: 'FRESH', sample_id: '',
      updated_at: 0, powder_mm3: 0, liquid_ml: 0, eluted: 0,
    })
  }
  return {
    type: 'material_state', ts: 1000 + seq, seq, cells,
    staging: { 'staging-a': { plate: null, kind: 'collector' } },
    magazines: [{ magazine: 'feed', count: 10, capacity: 30 }],
    bottles: [], seats: [], presence: [], payload_seats: [], transit: {},
  }
}

/** 造一个已收到一帧的 store */
function primed() {
  const store = new MaterialStateStore()
  store.push(rawEvent(1), 1000)
  return store
}

test('零回归: 无草稿时 status() 恒返回同一个快照对象', () => {
  const store = primed()
  const a = store.status(1000).snapshot
  const b = store.status(1001).snapshot
  assert.equal(a, b, '身份变了就会打掉下游的逐帧短路')
  assert.equal(a, store.snapshot)
  assert.equal(store.status(1000).draft, false)
})

test('零回归: setDraftOverlay(null) 之后回到基准身份', () => {
  const store = primed()
  const base = store.status().snapshot
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
  assert.notEqual(store.status().snapshot, base, '装了草稿应换一个对象')
  store.setDraftOverlay(null)
  assert.equal(store.status().snapshot, base, '卸了草稿必须回到基准对象本身')
  assert.equal(store.status().draft, false)
})

test('记忆化: 草稿不变时 N 次 status() 只算一次', () => {
  const store = primed()
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  let calls = 0
  store.setDraftOverlay((event) => { calls += 1; return applyDraft(event, draft) }, draft.revision)

  const first = store.status().snapshot
  for (let i = 0; i < 20; i += 1) assert.equal(store.status().snapshot, first)
  assert.equal(calls, 1, `叠加被算了 ${calls} 次 —— 每帧 4 次调用会把它变成逐帧全量重算`)
})

test('记忆化: 草稿版本变了才重算', () => {
  const store = primed()
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  let calls = 0
  const apply = (event) => { calls += 1; return applyDraft(event, draft) }
  store.setDraftOverlay(apply, draft.revision)
  const first = store.status().snapshot
  assert.equal(calls, 1)

  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 30 })
  store.setDraftOverlay(apply, draft.revision)
  const second = store.status().snapshot
  assert.equal(calls, 2)
  assert.notEqual(second, first)
  assert.equal(second.magazines[0].count, 30)
})

test('记忆化: 来了新推流帧, 叠加基准跟着换', () => {
  const store = primed()
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
  const before = store.status().snapshot

  const next = rawEvent(2)
  next.cells[0].state = 'USED'
  store.push(next, 2000)

  const after = store.status().snapshot
  assert.notEqual(after, before, '新基准要重算')
  assert.equal(after.cells[0].state, 'USED', '推流的真相要透过来')
  assert.equal(after.magazines[0].count, 25, '草稿仍叠在新基准上')
})

test('空草稿的叠加函数不触发多余的归一化 (仍返回基准对象)', () => {
  const store = primed()
  const base = store.status().snapshot
  const draft = createDraft()
  store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
  assert.equal(store.status().snapshot, base,
    'applyDraft 对空草稿返回原事件, 这时不该白归一化一遍')
})

test('断线即卸草稿: 基准已不可信, 预览不该继续作画', () => {
  const store = primed()
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 25 })
  store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
  assert.equal(store.hasDraftOverlay, true)

  store.markDisconnected()
  assert.equal(store.hasDraftOverlay, false)
  assert.equal(store.status().snapshot, store.snapshot)
  assert.equal(store.status().disconnected, true)
})

test('还没收到任何帧时装草稿不炸', () => {
  const store = new MaterialStateStore()
  const draft = createDraft()
  putEntry(draft, 'setMagazine', { magazine: 'feed', count: 1 })
  store.setDraftOverlay((event) => applyDraft(event, draft), draft.revision)
  const status = store.status()
  assert.equal(status.available, false)
  assert.equal(status.snapshot, null)
})

test('lastEvent 被保留下来 (叠加作用在原始事件上, 不是归一化后的快照)', () => {
  const event = rawEvent(1)
  const store = new MaterialStateStore()
  store.push(event, 1000)
  assert.equal(store.lastEvent, event)
})

test('status().draft 如实报告当前画面是不是预览', () => {
  const store = primed()
  assert.equal(store.status().draft, false)
  store.setDraftOverlay((e) => e, 1)
  assert.equal(store.status().draft, true)
})
