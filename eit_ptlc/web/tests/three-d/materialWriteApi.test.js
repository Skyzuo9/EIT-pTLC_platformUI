// 物料写通道测试 (twin/materialWriteApi.js): 注入 request 替身断言 动词 -> URL/body,
// base 换 /api/sim/materials 后全动词前缀正确 (照 simApi 的测法)。
// 这层是协议 §5.1 的执行面: 三维只许写既有人工盘点端点, URL 集合就是契约。
import test from 'node:test'
import assert from 'node:assert/strict'
import { createMaterialWriteApi } from '../../src/three-d/twin/materialWriteApi.js'

function capture() {
  const calls = []
  const api = createMaterialWriteApi({
    request: async (path, body) => { calls.push({ path, body }); return { ok: true } },
  })
  return { api, calls }
}

test('动词 -> URL/body 映射 (实时页缺省前缀)', async () => {
  const { api, calls } = capture()
  await api.mark({ kind: 'collector', plate: 3, hole: 5, state: 'USED' })
  await api.mark({ kind: 'collector', plate: 3, state: 'FRESH' })   // 整板: 无 hole
  await api.setCellAmount({ kind: 'bottle', plate: 1, hole: 2, liquid_ml: 12.5 })
  await api.setStaging('staging-a', null)
  await api.setRack('collector', 4, false)
  await api.setMagazine('feed', 30)
  await api.setBottle('eluent', 100)
  await api.setSeat('spot_seat', true)
  await api.clearTransit('gripper_vial', '')
  await api.clearPayloadSeat('scrape-holder')

  assert.deepEqual(calls.map((c) => c.path), [
    '/api/materials/mark', '/api/materials/mark', '/api/materials/cell_amount',
    '/api/materials/staging', '/api/materials/rack', '/api/materials/magazine',
    '/api/materials/bottle', '/api/materials/seat', '/api/materials/transit',
    '/api/materials/payload_seat',
  ])
  assert.deepEqual(calls[0].body, { kind: 'collector', plate: 3, hole: 5, state: 'USED' })
  assert.equal('hole' in calls[1].body, false, '整板 mark 不带 hole 键')
  assert.deepEqual(calls[2].body, { kind: 'bottle', plate: 1, hole: 2, liquid_ml: 12.5 })
  assert.deepEqual(calls[3].body, { area: 'staging-a', plate: null })
  assert.deepEqual(calls[8].body, { carrier: 'gripper_vial', land_at: '' },
                   'land_at 空串语义 = 只清行')
  assert.deepEqual(calls[9].body, { seat: 'scrape-holder' },
                   '清件位只带 seat (不带 identity, 后端按清账分支走)')
})

test('base 注入: 仿真页全动词换 /api/sim/materials 前缀', async () => {
  const calls = []
  const api = createMaterialWriteApi({
    base: '/api/sim/materials',
    request: async (path, body) => { calls.push({ path, body }); return {} },
  })
  await api.setMagazine('feed', 30)
  await api.mark({ kind: 'collector', plate: 1, hole: 1, state: 'FRESH' })
  await api.clearTransit('gripper_plate96', 'rack')
  assert.ok(calls.every((c) => c.path.startsWith('/api/sim/materials/')),
            `沙盒前缀漏换: ${calls.map((c) => c.path)}`)
})
