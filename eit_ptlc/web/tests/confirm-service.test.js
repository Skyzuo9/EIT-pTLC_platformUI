// 确认服务: 钉住"单弹窗不排队"与 promise 收口两条不变量。
// 排队是安全禁区 —— 排到后面的确认会在语境失效后才弹出; 定案是新请求立即按取消收口。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { confirmAction, promptAction, current } from '../src/composables/confirmService.js'

test('confirmAction: settle(true) → resolve true 且 current 清空', async () => {
  const p = confirmAction({ title: '删除测试', message: '后果', level: 'danger', confirmText: '删除' })
  assert.ok(current.value, '发起后应有当前对话')
  assert.equal(current.value.level, 'danger')
  current.value.settle(true)
  assert.equal(await p, true)
  assert.equal(current.value, null, '收口后应清空')
})

test('已开对话时新请求立即 resolve(false), 不排队不顶替', async () => {
  const first = confirmAction({ title: '第一个' })
  const firstReq = current.value
  const second = await confirmAction({ title: '第二个' }) // 应立即收口
  assert.equal(second, false, '并发请求按取消收口')
  assert.equal(current.value, firstReq, '第一个对话保持在场')
  firstReq.settle(false)
  assert.equal(await first, false)
})

test('promptAction: settle 字符串 → 原样返回; settle 非字符串 → null', async () => {
  const p1 = promptAction({ title: '输入名称', initial: 'abc' })
  assert.equal(current.value.kind, 'prompt')
  assert.equal(current.value.initial, 'abc')
  current.value.settle('新流程')
  assert.equal(await p1, '新流程')

  const p2 = promptAction({ title: '再次输入' })
  current.value.settle(false)
  assert.equal(await p2, null)
})

test('message 归一化为数组', async () => {
  const p = confirmAction({ title: 't', message: '单行' })
  assert.deepEqual(current.value.message, ['单行'])
  current.value.settle(false)
  await p
  const p2 = confirmAction({ title: 't', message: ['a', 'b'] })
  assert.deepEqual(current.value.message, ['a', 'b'])
  current.value.settle(false)
  await p2
})
