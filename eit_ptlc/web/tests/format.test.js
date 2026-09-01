// format.js: Intl 化后的输出形状快照 (锁 zh-CN 且不随宿主区域漂移)。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { fmtNum, fmtShortMs, fmtTime, fmtValue } from '../src/utils/format.js'

test('fmtNum: 定 2 位小数、不分组、非法值 —', () => {
  assert.equal(fmtNum(1.2345), '1.23')
  assert.equal(fmtNum(7), '7.00')
  assert.equal(fmtNum(1234.5), '1234.50') // 不带千分位
  assert.equal(fmtNum(-0.005, 3), '-0.005')
  assert.equal(fmtNum(NaN), '—')
  assert.equal(fmtNum('9'), '—')
})

test('fmtValue: 数组数值走 fmtNum, 空值 —, 对象 JSON', () => {
  assert.equal(fmtValue([1, 2.5, 'x']), '1.00, 2.50, x')
  assert.equal(fmtValue(null), '—')
  assert.equal(fmtValue({ a: 1 }), '{"a":1}')
  assert.equal(fmtValue('str'), 'str')
})

test('fmtTime: 秒入参, 空值 —, 输出含年月日时分秒', () => {
  assert.equal(fmtTime(0), '—')
  const out = fmtTime(1753776000) // 2026-07-29 前后 (随时区), 只断形状
  assert.match(out, /^\d{4}\/\d{1,2}\/\d{1,2} \d{2}:\d{2}:\d{2}$/)
})

test('fmtShortMs: 毫秒入参, MM/DD HH:mm 补零', () => {
  const out = fmtShortMs(Date.UTC(2026, 6, 9, 4, 5))
  assert.match(out, /^\d{2}\/\d{2} \d{2}:\d{2}$/)
})
