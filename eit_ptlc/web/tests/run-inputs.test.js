// runInputs.js 的有限取值域三件套: enumOf 规范化 / validateValue 成员判定 / sanitizeRestored 回填清洗。
// 杀的是"用户在自由输入框里打了个不存在的分支名, 一路跑到机器人换完刀才炸"那类事故的前端半边。
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { enumOf, enumToText, parseEnumText, sanitizeRestored, validateValue } from '../src/utils/runInputs.js'

test('enumOf: 标量简写与带标签形都规范成 {value,label}', () => {
  assert.deepEqual(enumOf({ enum: ['collector', 'bottle'] }),
    [{ value: 'collector', label: 'collector' }, { value: 'bottle', label: 'bottle' }])
  assert.deepEqual(enumOf({ enum: [{ value: 1, label: '1 上样' }, { value: 2, label: '2 拍照' }] }),
    [{ value: '1', label: '1 上样' }, { value: '2', label: '2 拍照' }])
})

test('enumOf: value 一律字符串化 (INT 域的 1 与 draft 的 "1" 必须相等)', () => {
  assert.deepEqual(enumOf({ enum: [1, 2, 3] }).map((o) => o.value), ['1', '2', '3'])
})

test('enumOf: 同一列表内标量与带标签项可混用; 缺 label 时回落到 value', () => {
  assert.deepEqual(enumOf({ enum: ['auto', { value: 'manual' }] }),
    [{ value: 'auto', label: 'auto' }, { value: 'manual', label: 'manual' }])
})

test('enumOf: 无取值域 / 空列表 / 空对象一律返回 []', () => {
  assert.deepEqual(enumOf({}), [])
  assert.deepEqual(enumOf({ enum: [] }), [])
  assert.deepEqual(enumOf(null), [])
  assert.deepEqual(enumOf(undefined), [])
})

test('enumOf: 兼容期仍认旧的 ui.enum, 但顶层 enum 优先', () => {
  assert.deepEqual(enumOf({ ui: { enum: ['feed', 'waste'] } }).map((o) => o.value), ['feed', 'waste'])
  assert.deepEqual(enumOf({ enum: ['a'], ui: { enum: ['b'] } }).map((o) => o.value), ['a'])
})

test('validateValue: 成员判定 — 域内放行, 域外报"不在可选值内"', () => {
  const opts = enumOf({ enum: ['collector', 'bottle'] })
  assert.equal(validateValue('STRING', 'collector', null, opts), '')
  assert.equal(validateValue('STRING', 'control', null, opts), '不在可选值内')
})

test('validateValue: 留空恒合法 (取脚本默认值), 即便声明了取值域', () => {
  const opts = enumOf({ enum: ['collector', 'bottle'] })
  assert.equal(validateValue('STRING', '', null, opts), '')
  assert.equal(validateValue('STRING', null, null, opts), '')
  assert.equal(validateValue('STRING', '   ', null, opts), '')
})

test('validateValue: 成员判定优先于类型判定 — INT 域外值报取值域而非"须为整数"', () => {
  const opts = enumOf({ enum: [1, 2, 3] })
  assert.equal(validateValue('INT', '2', null, opts), '')
  assert.equal(validateValue('INT', '7', null, opts), '不在可选值内')
})

test('validateValue: 无取值域时原有类型校验行为不变', () => {
  assert.equal(validateValue('INT', 'abc'), '须为整数')
  assert.equal(validateValue('STRING', '随便什么'), '')
  assert.equal(validateValue('INT', '5', { min: 10 }), '低于下限 10')
  assert.equal(validateValue('LIST', '{}'), '须为 JSON 数组')
})

test('sanitizeRestored: 丢掉不在取值域内的陈旧回填值并点名', () => {
  const vars = [{ name: 'rack_id', enum: ['collector', 'bottle'] }, { name: 'note' }]
  const { values, dropped } = sanitizeRestored(vars, { rack_id: 'control', note: '随便' })
  assert.deepEqual(values, { note: '随便' })
  assert.deepEqual(dropped, ['rack_id'])
})

test('sanitizeRestored: 域内值与无取值域的自由值都原样保留', () => {
  const vars = [{ name: 'rack_id', enum: ['collector', 'bottle'] }, { name: 'note' }]
  const { values, dropped } = sanitizeRestored(vars, { rack_id: 'bottle', note: 'x' })
  assert.deepEqual(values, { rack_id: 'bottle', note: 'x' })
  assert.deepEqual(dropped, [])
})

test('sanitizeRestored: 空串保留 (它表示"取默认", 不是陈旧值)', () => {
  const vars = [{ name: 'rack_id', enum: ['collector', 'bottle'] }]
  const { values, dropped } = sanitizeRestored(vars, { rack_id: '' })
  assert.deepEqual(values, { rack_id: '' })
  assert.deepEqual(dropped, [])
})

test('sanitizeRestored: INT 域的数字回填值按字符串比对, 不误伤', () => {
  const vars = [{ name: 'target', type: 'INT', enum: [1, 2, 3] }]
  assert.deepEqual(sanitizeRestored(vars, { target: 2 }).dropped, [])
  assert.deepEqual(sanitizeRestored(vars, { target: 9 }).dropped, ['target'])
})

test('parseEnumText: 每行一项, `值 | 标签` 拆开, 空行忽略', () => {
  assert.deepEqual(parseEnumText('collector\nbottle\n\n', 'STRING'), ['collector', 'bottle'])
  assert.deepEqual(parseEnumText('1 | 1 上样\n2 | 2 拍照', 'INT'),
    [{ value: 1, label: '1 上样' }, { value: 2, label: '2 拍照' }])
})

test('parseEnumText: INT/FLOAT 转成数字 (后端 schema 要求 INT 域是 YAML 整数)', () => {
  assert.deepEqual(parseEnumText('1\n2\n3', 'INT'), [1, 2, 3])
  assert.deepEqual(parseEnumText('0.5\n1.5', 'FLOAT'), [0.5, 1.5])
  assert.deepEqual(parseEnumText('1\n2', 'STRING'), ['1', '2'])
})

test('parseEnumText: 空文本返回 [] (调用方据此删掉 enum 字段)', () => {
  assert.deepEqual(parseEnumText('', 'STRING'), [])
  assert.deepEqual(parseEnumText('  \n \n', 'STRING'), [])
  assert.deepEqual(parseEnumText(null, 'STRING'), [])
})

test('parseEnumText: 标签与值相同时退回标量形 (不产生冗余 {value,label})', () => {
  assert.deepEqual(parseEnumText('feed | feed', 'STRING'), ['feed'])
})

test('enumToText/parseEnumText 往返一致', () => {
  for (const [raw, type] of [
    [['collector', 'bottle'], 'STRING'],
    [[{ value: 1, label: '1 上样' }, { value: 2, label: '2 拍照' }], 'INT'],
    [[1, 2, 3], 'INT'],
  ]) {
    assert.deepEqual(parseEnumText(enumToText(raw), type), raw)
  }
})

test('enumToText: 无取值域返回空串', () => {
  assert.equal(enumToText(undefined), '')
  assert.equal(enumToText([]), '')
})
