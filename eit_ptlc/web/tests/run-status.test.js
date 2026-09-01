// runStatusLabel: 运行状态英文枚举 → 两字中文 (执行记录列表 + 执行详情共用)
import { strict as assert } from 'node:assert'
import test from 'node:test'
import { runStatusLabel } from '../src/utils/runStatus.js'

test('runStatusLabel: 已知枚举两字中文, 未知原样, 空值空串', () => {
  assert.equal(runStatusLabel('RUNNING'), '运行')
  assert.equal(runStatusLabel('DONE'), '完成')
  assert.equal(runStatusLabel('FAILED'), '失败')
  assert.equal(runStatusLabel('CANCELLED'), '取消')
  assert.equal(runStatusLabel('WEIRD'), 'WEIRD')   // 未知值原样直出 (class 兼容同理)
  assert.equal(runStatusLabel(''), '')             // 详情页 view.status 初始空串
  assert.equal(runStatusLabel(undefined), '')
})
