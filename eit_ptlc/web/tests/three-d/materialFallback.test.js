import test from 'node:test'
import assert from 'node:assert/strict'

import { EventStream } from '../../src/three-d/twin/bindings/eventStream.js'
import { api } from '../../src/api.js'

test('三维挂载时通过宿主 API 补种物料快照且不创建独立连接', async () => {
  const previousGetMaterials = api.getMaterials
  let calls = 0
  api.getMaterials = async () => {
    calls += 1
    return { cells: [], staging: {}, magazines: [], presence: [] }
  }

  try {
    const stream = new EventStream({ autoconnect: false })
    const events = []
    stream.onEvent((event) => events.push(event))

    assert.equal(await stream.seedMaterials(), true)
    assert.equal(events[0].type, 'material_state')
    assert.equal(events[0].initial, true)
    assert.equal(events[0].source, 'host_snapshot')
    assert.equal(calls, 1)
    stream.dispose()
  } finally {
    api.getMaterials = previousGetMaterials
  }
})
