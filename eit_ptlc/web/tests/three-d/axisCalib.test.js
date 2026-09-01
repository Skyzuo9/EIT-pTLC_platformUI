/**
 * 功能: 轴标定面板纯逻辑的单元测试 —— 快照/变更检测/数值格式/回填片段.
 */
import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  CALIB_FIELDS,
  calibValuesOf,
  snapshotAxes,
  changedAxes,
  formatMm,
  buildYamlFragment,
  matchDriftToleranceM,
  matchedZeroOffset,
  rangeCovering,
  ZERO_QUANT_MM,
} from '../../src/three-d/twin/panels/axisCalib.js'

/** 造两条 manifest 轴条目(结构对齐 device-manifest.json 的 axes[]) */
function makeAxes() {
  return [
    {
      id: 'axis_11y',
      label: '地轨轴11Y',
      sign: -1,
      zeroOffsetMm: 500.0,
      rangeMm: [0, 3000],
      rigged: true,
    },
    {
      id: 'axis_4x',
      label: '上样轴4X',
      sign: 1,
      zeroOffsetMm: 0.0,
      rangeMm: [0, 300],
      rigged: false,
    },
  ]
}

test('字段表自洽: manifest 侧与 rig_map 侧字段一一对应', () => {
  assert.deepEqual(
    CALIB_FIELDS.map((f) => f.yaml),
    ['sign', 'zero_offset_mm', 'range_mm'],
  )
})

test('calibValuesOf: 缺省字段按前端驱动的默认值归一', () => {
  assert.deepEqual(calibValuesOf({}), { sign: 1, zeroOffsetMm: 0, rangeMm: [0, 0] })
  assert.deepEqual(calibValuesOf({ sign: -1, zeroOffsetMm: 500, rangeMm: [0, 3000] }), {
    sign: -1,
    zeroOffsetMm: 500,
    rangeMm: [0, 3000],
  })
})

test('快照独立于后续修改: 改 spec 不影响已拍快照', () => {
  const axes = makeAxes()
  const snapshot = snapshotAxes(axes)
  axes[0].zeroOffsetMm = 512.3
  axes[0].rangeMm[0] = -50
  assert.equal(snapshot.get('axis_11y').zeroOffsetMm, 500)
  assert.equal(snapshot.get('axis_11y').rangeMm[0], 0)
})

test('changedAxes: 无改动返回空; 浮点等值不算变更', () => {
  const axes = makeAxes()
  const snapshot = snapshotAxes(axes)
  assert.deepEqual(changedAxes(axes, snapshot), [])
  axes[0].zeroOffsetMm = 500.0 + 1e-12 // 容差内
  assert.deepEqual(changedAxes(axes, snapshot), [])
})

test('changedAxes: 捕获 sign/zeroOffset/range 三类变更并带原值', () => {
  const axes = makeAxes()
  const snapshot = snapshotAxes(axes)
  axes[0].zeroOffsetMm = 512.5
  axes[1].sign = -1
  axes[1].rangeMm = [-5, 110]
  const changed = changedAxes(axes, snapshot)
  assert.deepEqual(
    changed.map((c) => c.id),
    ['axis_11y', 'axis_4x'],
  )
  assert.equal(changed[0].before.zeroOffsetMm, 500)
  assert.equal(changed[0].after.zeroOffsetMm, 512.5)
  assert.deepEqual(changed[1].after.rangeMm, [-5, 110])
})

test('formatMm: 整数不带小数点, 小数最多 3 位去尾零, 非数值给占位', () => {
  assert.equal(formatMm(500), '500')
  assert.equal(formatMm(-5), '-5')
  assert.equal(formatMm(512.5), '512.5')
  assert.equal(formatMm(0.1234), '0.123')
  assert.equal(formatMm(2.5000001), '2.5')
  assert.equal(formatMm('abc'), '—')
})

test('buildYamlFragment: 空变更返回空串', () => {
  assert.equal(buildYamlFragment([], '2026-08-01T12:00:00+08:00'), '')
})

test('buildYamlFragment: 片段逐行 —— 头注释/原值注释/4 空格字段/偏移恒带小数', () => {
  const axes = makeAxes()
  const snapshot = snapshotAxes(axes)
  axes[1].zeroOffsetMm = 55
  axes[1].rangeMm = [-5, 110]
  const text = buildYamlFragment(changedAxes(axes, snapshot), '2026-08-01T12:00:00+08:00')
  const lines = text.split('\n')
  assert.equal(lines[0], '# ==== AxisDebugPanel 标定导出 2026-08-01T12:00:00+08:00 ====')
  assert.ok(lines[3].includes('唯一固化真源'))
  assert.equal(lines[4], '')
  assert.equal(lines[5], '# axis_4x (上样轴4X)  原: sign=1  zero_offset_mm=0.0  range_mm=[0, 300]')
  assert.equal(lines[6], '    sign: 1')
  assert.equal(lines[7], '    zero_offset_mm: 55.0')
  assert.equal(lines[8], '    range_mm: [-5, 110]')
  assert.equal(lines[9], '')
  assert.equal(lines.length, 10) // 末尾单个换行
})

// -- 匹配公式(AxisCalibBoard 的"匹配零点") ---------------------------------

test('matchedZeroOffset 通式: zero_new = zero_old + (R − P_v)', () => {
  assert.equal(
    matchedZeroOffset({ liveMm: 500, appliedMm: 480, zeroOffsetMm: 100 }),
    120,
  )
  // zero_old = 0 时退化为直觉式 R − P_v
  assert.equal(matchedZeroOffset({ liveMm: 500, appliedMm: 480, zeroOffsetMm: 0 }), 20)
  // 精度 round 到 1e-3
  assert.equal(
    matchedZeroOffset({ liveMm: 10.0004, appliedMm: 0, zeroOffsetMm: 0 }),
    10,
  )
  assert.equal(matchedZeroOffset({ liveMm: NaN, appliedMm: 0, zeroOffsetMm: 0 }), null)
})

test('matchedZeroOffset 性质: zero_old + (R − P_v) 无需量化时, 位移严格恒等', () => {
  // 位移标量 D(mm, zero) = (mm − zero) · sign · mmToUnit; sign/mmToUnit 在恒等两侧消去,
  // 但性质测试仍带着它们跑一遍, 锁死"公式与 setAxisMm 同构"这层关系.
  // 本组四例的 zero_old + (R − P_v) 都已是 ≤3 位小数, Math.round 是恒等变换 —— 严格判据.
  const cases = [
    { R: 500, Pv: 480, zeroOld: 100, sign: -1, mmToUnit: 0.001 },
    { R: -20, Pv: 35, zeroOld: 0, sign: 1, mmToUnit: 0.001 },
    { R: 3000, Pv: 0, zeroOld: 500, sign: -1, mmToUnit: 0.002 },
    { R: 0.123, Pv: -9.5, zeroOld: -3.25, sign: 1, mmToUnit: 0.001 },
  ]
  for (const { R, Pv, zeroOld, sign, mmToUnit } of cases) {
    const zeroNew = matchedZeroOffset({ liveMm: R, appliedMm: Pv, zeroOffsetMm: zeroOld })
    const before = (Pv - zeroOld) * sign * mmToUnit
    const after = (R - zeroNew) * sign * mmToUnit
    assert.ok(Math.abs(before - after) < 1e-12, `位移不恒等: ${JSON.stringify({ R, Pv, zeroOld })}`)
  }
})

test('matchedZeroOffset 性质: 真实 float32 反馈下, 残差不得超过 matchDriftToleranceM', () => {
  // 真机的 R 是 PLC 的 REAL(float32), 小数位远不止 3 位, 零点量化必留残差 ——
  // 面板的不动性校验只能按这个容差判, 不能按 1e-9(2026-08-05 事故: 阈值严 1000 倍,
  // 报"匹配校验失败 位移 4.95e-7 m, 已撤销", 标定闭环整条不可用).
  const cases = [
    { R: 297.4563843, Pv: 297, zeroOld: 0, sign: 1, mmToUnit: 0.001 },
    { R: -4.9954271, Pv: -14, zeroOld: -14, sign: -1, mmToUnit: 0.001 },
    { R: 1234.56749, Pv: 1200, zeroOld: 500, sign: -1, mmToUnit: 0.002 },
  ]
  for (const { R, Pv, zeroOld, sign, mmToUnit } of cases) {
    const zeroNew = matchedZeroOffset({ liveMm: R, appliedMm: Pv, zeroOffsetMm: zeroOld })
    const before = (Pv - zeroOld) * sign * mmToUnit
    const after = (R - zeroNew) * sign * mmToUnit
    const drift = Math.abs(before - after)
    const tol = matchDriftToleranceM({ mmToUnit })
    assert.ok(drift <= tol, `残差 ${drift} 超容差 ${tol}: ${JSON.stringify({ R, Pv, zeroOld })}`)
    // 同时锁住"这些用例确实带量化残差" —— 否则它们退化成上一组, 抓不到阈值回归
    assert.ok(drift > 1e-9, `用例无量化残差, 抓不到回归: ${JSON.stringify({ R, Pv, zeroOld })}`)
  }
})

test('matchDriftToleranceM: 按 mmToUnit 派生, 且必须容得下半个量化步长', () => {
  assert.equal(matchDriftToleranceM({ mmToUnit: 0.001 }), 1e-6)
  assert.equal(matchDriftToleranceM({ mmToUnit: 0.002 }), 2e-6)
  // mmToUnit 缺省/为 0/非法时回落 0.001(与 setAxisMm 的 `spec.mmToUnit || 0.001` 同源)
  assert.equal(matchDriftToleranceM({}), 1e-6)
  assert.equal(matchDriftToleranceM({ mmToUnit: 0 }), 1e-6)
  assert.equal(matchDriftToleranceM(null), 1e-6)
  // 回归锁: 谁再把容差收紧到量化残差以下, 这里先红
  for (const mmToUnit of [0.001, 0.002]) {
    assert.ok(
      matchDriftToleranceM({ mmToUnit }) > 0.5 * ZERO_QUANT_MM * mmToUnit,
      `容差 ${matchDriftToleranceM({ mmToUnit })} 盖不住量化残差(mmToUnit=${mmToUnit})`,
    )
  }
  // 但仍要远严于真 bug 的量级(clamp 咬住/sign 错/认错节点是 1e-3 m 起)
  assert.ok(matchDriftToleranceM({ mmToUnit: 0.001 }) < 1e-4)
})

test('rangeCovering: 已覆盖原样返回, 越界扩到覆盖(带余量)', () => {
  assert.deepEqual(rangeCovering([0, 3000], 500), [0, 3000])
  assert.deepEqual(rangeCovering([0, 3000], -20), [-20, 3000])
  assert.deepEqual(rangeCovering([0, 100], 130, 5), [0, 135])
  assert.deepEqual(rangeCovering([0, 100], NaN), [0, 100])
})

test('rangeCovering: 向外取整 —— 越界值必被新界真正覆盖(round 会漏)', () => {
  // round 的话新下界回到 −14.000, 仍盖不住 −14.0004, clamp 照咬 0.4 µm
  assert.ok(rangeCovering([-14, 36], -14.0004)[0] <= -14.0004)
  assert.ok(rangeCovering([0, 100], 100.0004)[1] >= 100.0004)
  assert.deepEqual(rangeCovering([-14, 36], -14.0004), [-14.001, 36])
  assert.deepEqual(rangeCovering([0, 100], 100.0004), [0, 100.001])
  // 已是 1e-3 整数倍的边界不因取整被无谓外扩
  assert.deepEqual(rangeCovering([-50, 550], -50), [-50, 550])
  assert.deepEqual(rangeCovering([0, 3000], 0.1 * 3), [0, 3000])
})
