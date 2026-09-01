/**
 * 功能: 设备状态人话化的单元测试.
 *
 * 三类断言:
 *   ① 金样键集匹配 —— 与 pytest 侧对着同一份 plcStatusLabels.contract.json,
 *      两道绊线夹一份金样, Python 改了枚举两边都会红;
 *   ② **开放世界三分覆盖** —— ops ∪ engineer ∪ hidden 必须等于快照全部非空键,
 *      后端新加一个镜像字段永远不会人间蒸发;
 *   ③ 一句话概述与色调 —— 六种典型工况的成文.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  L2_SAFE_STATE,
  L2_STATE,
  ROBOT_LAST_ACTION,
  ROBOT_MODE,
  actionCodeText,
  errorCodeText,
  fieldSpec,
  formatRaw,
  headline,
  isHiddenKey,
  semanticsOf,
  statusRows,
  stepText,
} from '../../src/three-d/twin/stationStatus.js'

const GOLDEN = JSON.parse(readFileSync(
  fileURLToPath(new URL('./plcStatusLabels.contract.json', import.meta.url)), 'utf8'))

/** 从 {code:{en,zh,tone}} 表抽出 {code:en} 供与金样比对 */
const enMap = (table) =>
  Object.fromEntries(Object.entries(table).map(([code, meta]) => [code, meta.en]))

// ── ① 金样 ────────────────────────────────────────────────────────────────
test('金样: RobotMode 键集与英文名一致', () => {
  assert.deepEqual(enMap(ROBOT_MODE), GOLDEN.robotMode)
})

test('金样: L2 State 键集与英文名一致', () => {
  assert.deepEqual(enMap(L2_STATE), GOLDEN.l2State)
})

test('金样: L2 SafeState 键集与英文名一致', () => {
  assert.deepEqual(enMap(L2_SAFE_STATE), GOLDEN.l2SafeState)
})

test('金样: last_action 码集一致', () => {
  assert.deepEqual(Object.keys(ROBOT_LAST_ACTION).map(Number).sort((a, b) => a - b),
    GOLDEN.robotLastAction)
})

test('每个枚举项都有中文与色调 (缺一项就会在界面上印出 undefined)', () => {
  for (const table of [ROBOT_MODE, L2_STATE, L2_SAFE_STATE]) {
    for (const [code, meta] of Object.entries(table)) {
      assert.ok(meta.zh, `${code} 缺中文`)
      assert.ok(['ok', 'warn', 'bad', 'busy', 'muted'].includes(meta.tone), `${code} 色调非法`)
    }
  }
})

// ── ② 开放世界三分覆盖 ────────────────────────────────────────────────────
/** 后端 _robot_feedback_to_dict + robot_reader 的实际形状 */
const ROBOT_SNAP = {
  pose: [1, 2, 3, 4, 5, 6], joint: [0, 0, 0, 0, 0, 0],
  check_result: 0, last_action: 24, robot_mode: 5, error_ids: [],
  connected: true, tool_state: { mounted_tool: 1 }, speed_factor: 20,
}
/** L2 工位 + 展开工位的额外镜像 */
const DEVELOP_SNAP = {
  State: 10, ActiveCode: 30, AcceptedSeq: 7, CompletedSeq: 6, Step: 32,
  ErrorCode: 0, SafeState: 10, Retryable: false,
  Expand_Waste_Empty_G1: false, Expand_Waste_Empty_G2: true,
}
const RAIL_SNAP = {
  State: 0, ActiveCode: 0, AcceptedSeq: 3, CompletedSeq: 3, Step: 0,
  ErrorCode: 0, SafeState: 10, Retryable: false,
  current_positions: [2], Rail_ActPos: 1234.5,
}
const PUMP_SNAP = {
  State: 0, ActiveCode: 0, AcceptedSeq: 1, CompletedSeq: 1, Step: 0,
  ErrorCode: 0, SafeState: 0, Retryable: false, Pump_Vacuum_On: true,
}

const CASES = [
  ['robot', ROBOT_SNAP, 'ROBOT'],
  ['plc', DEVELOP_SNAP, 'DEVELOP'],
  ['plc', RAIL_SNAP, 'RAIL'],
  ['plc', PUMP_SNAP, 'PUMP'],
]

test('开放世界: ops ∪ engineer ∪ hidden 恰等于快照全部非空键', () => {
  for (const [kind, snap, stationId] of CASES) {
    const { ops, engineer, hidden } = statusRows(kind, snap, { stationId })
    const covered = new Set([...ops.map((r) => r.key), ...engineer.map((r) => r.key), ...hidden])
    const expected = Object.entries(snap)
      .filter(([, v]) => v !== null && v !== undefined).map(([k]) => k)
    assert.deepEqual([...covered].sort(), expected.sort(),
      `${stationId} 有字段既没显示也没声明隐藏 —— 后端加字段被静默吞掉了`)
    // 同一个键不许同时出现在两层
    const opsKeys = new Set(ops.map((r) => r.key))
    for (const row of engineer) assert.ok(!opsKeys.has(row.key), `${row.key} 同时出现在两层`)
  }
})

test('开放世界: 后端凭空新增一个字段, 也会出现在工程师层', () => {
  const snap = { ...DEVELOP_SNAP, Brand_New_Mirror: 42 }
  const { engineer } = statusRows('plc', snap, { stationId: 'DEVELOP' })
  const row = engineer.find((r) => r.key === 'Brand_New_Mirror')
  assert.ok(row, '未登记字段应自动落入工程师层')
  assert.equal(row.text, '42')
})

test('error_ids 有值时进操作员层 (旧实现把数组整个滤掉了, 报警时面板一片空白)', () => {
  const { ops } = statusRows('robot', { ...ROBOT_SNAP, error_ids: [16, 117] }, { stationId: 'ROBOT' })
  const row = ops.find((r) => r.key === 'error_ids')
  assert.ok(row, 'error_ids 应显示')
  assert.equal(row.tone, 'bad')
  assert.match(row.text, /16, 117/)
})

test('isHiddenKey: 位姿与轴位置有意不进字段表 (它们各有专门呈现)', () => {
  assert.ok(isHiddenKey('pose'))
  assert.ok(isHiddenKey('joint'))
  assert.ok(isHiddenKey('Rail_ActPos'))
  assert.ok(isHiddenKey('Sampling_5Z_ActPos'))
  assert.ok(!isHiddenKey('State'))
})

test('无意义的常态值降到工程师层而不是消失 (ErrorCode=0 / SafeState=就绪)', () => {
  const { ops, engineer } = statusRows('plc', DEVELOP_SNAP, { stationId: 'DEVELOP' })
  assert.ok(!ops.some((r) => r.key === 'ErrorCode'), '无故障时不该占版面')
  assert.ok(engineer.some((r) => r.key === 'ErrorCode'), '但仍要能查到')
  assert.ok(!ops.some((r) => r.key === 'SafeState'))
  assert.ok(!ops.some((r) => r.key === 'check_result'))
})

test('空快照不炸', () => {
  assert.deepEqual(statusRows('plc', null), { ops: [], engineer: [], hidden: [] })
})

// ── ③ 释义与一句话概述 ────────────────────────────────────────────────────
test('semanticsOf: 八个 L2 工位都能查到语义表', () => {
  for (const id of ['SAMPLING', 'DEVELOP', 'COLLECT', 'PHOTOSCRAPE', 'FEEDLIFT', 'PUMP', 'RAIL', 'STAGINGA']) {
    assert.ok(semanticsOf(id), `${id} 查不到 PLC 语义`)
  }
  assert.equal(semanticsOf('ROBOT'), null, '机械臂不是 L2 工位')
})

test('errorCodeText: 真的把 FeedLift 301 翻成中文', () => {
  const text = errorCodeText('FEEDLIFT', 11, 301)
  assert.match(text, /前置门/)
  assert.ok(!/^错误码/.test(text), '不该回落到裸码')
})

test('errorCodeText: 门禁码 190 走 gateErrors', () => {
  assert.match(errorCodeText('FEEDLIFT', 11, 190), /部署门|PLC_Ready/)
})

test('errorCodeText: 查不到时也给出码, 不返回空', () => {
  assert.equal(errorCodeText('FEEDLIFT', 11, 999999), '错误码 999999')
  assert.equal(errorCodeText('FEEDLIFT', 11, 0), '')
})

test('stepText: 给的是位置而不是裸段号 (phase 英文原文另存)', () => {
  const out = stepText('FEEDLIFT', 11, 12)
  assert.equal(out.text, '第 2/4 段')
  assert.equal(out.phase, 'confirm_stable')
})

test('stepText: 段号不在表里时退回裸段号而不是骗人', () => {
  assert.equal(stepText('FEEDLIFT', 11, 77).text, '第 77 段')
})

test('actionCodeText: 优先用动作目录的中文 label', () => {
  const catalog = [{ name: 'feedlift.feed_raise', station: 'feedlift', action_code: 11, label: '上料仓抬升' }]
  assert.equal(actionCodeText('FEEDLIFT', 11, catalog), '上料仓抬升')
})

test('actionCodeText: 无目录时回落到 spec 的 POU 名, 再回落到裸码', () => {
  assert.equal(actionCodeText('FEEDLIFT', 11, []), 'A11_feed_raise')
  assert.equal(actionCodeText('FEEDLIFT', 999, []), '动作码 999')
  assert.equal(actionCodeText('FEEDLIFT', 0, []), '')
})

test('headline: 执行中给出动作名与进度', () => {
  const station = { id: 'FEEDLIFT', label: '上下料位', nodeId: 'plc.feedlift' }
  const out = headline(station, 'busy',
    { State: 10, ActiveCode: 11, Step: 12, ErrorCode: 0, SafeState: 10 }, {})
  assert.match(out.text, /上下料位 · 执行中 · 正在执行 A11_feed_raise（第 2\/4 段）/)
  assert.equal(out.tone, 'busy')
})

test('headline: 故障时给中文原因而不是 ErrorCode 数字', () => {
  const station = { id: 'FEEDLIFT', label: '上下料位', nodeId: 'plc.feedlift' }
  const out = headline(station, 'error', { State: 40, ActiveCode: 11, ErrorCode: 301, SafeState: 10 })
  assert.match(out.text, /前置门/)
  assert.ok(!/301/.test(out.text), '不该把裸码甩给操作员')
  assert.equal(out.tone, 'bad')
})

test('headline: SafeState=90 压过 State (需人工到现场)', () => {
  const station = { id: 'DEVELOP', label: '展开工位', nodeId: 'plc.develop' }
  const out = headline(station, 'busy', { State: 10, ActiveCode: 30, SafeState: 90, ErrorCode: 0 })
  assert.match(out.text, /需人工恢复/)
  assert.equal(out.tone, 'bad')
})

test('headline: 机械臂给模式与速度; 碰撞时给碰撞', () => {
  const station = { id: 'ROBOT', label: '机械臂', nodeId: 'robot' }
  const ok = headline(station, 'ok', ROBOT_SNAP)
  assert.match(ok.text, /机械臂 · 正常 · 已使能 · 待命 · 速度 20%/)
  const bad = headline(station, 'error',
    { ...ROBOT_SNAP, robot_mode: 11, error_ids: [16] })
  assert.match(bad.text, /碰撞/)
  assert.equal(bad.tone, 'bad')
})

test('headline: 机械臂断连时明说断连', () => {
  const station = { id: 'ROBOT', label: '机械臂', nodeId: 'robot' }
  const out = headline(station, 'offline', { ...ROBOT_SNAP, connected: false })
  assert.match(out.text, /离线 · 控制器未连接/)
})

test('headline: 地轨追加站位', () => {
  const station = { id: 'RAIL', label: '地轨', nodeId: 'plc.rail' }
  assert.match(headline(station, 'ok', RAIL_SNAP).text, /在 拍照 站位/)
})

test('headline: 无遥测节点与无数据两种情况分得开', () => {
  assert.match(headline({ id: 'RACK', label: '料架', nodeId: null }, 'unknown', null).text,
    /纯结构件/)
  assert.match(headline({ id: 'PUMP', label: '泵站', nodeId: 'plc.pump' }, 'offline', null).text,
    /无遥测数据/)
})

test('fieldSpec / formatRaw 的兜底', () => {
  assert.equal(fieldSpec('plc', '没这个字段'), null)
  assert.equal(formatRaw(true), '是')
  assert.equal(formatRaw([1, 2]), '[1, 2]')
  assert.equal(formatRaw([]), '[]')
  assert.equal(formatRaw(1.234), '1.23')
  assert.equal(formatRaw(null), '—')
})
