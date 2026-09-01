// manualGroups.js: 单点点表展示分组的行为锁 (样例取自 config/manual_points.yaml 真实 id/label)
import { strict as assert } from 'node:assert'
import test from 'node:test'

import {
  axisShortName,
  buildDevelopMatrix,
  buildGroups,
  classifyCylinder,
  classifyMechanism,
} from '../src/utils/manualGroups.js'

// develop 32 条: dev_t{1|2}_{cyl|fill|drain|blow}{1-4} (与 yaml 逐字同构)
function developCylinders() {
  const out = []
  const KINDS = [
    ['cyl', (t, i) => `展缸${t}气缸${i}`],
    ['fill', (t, i) => `展缸${t}进液电池阀${i}`],
    ['drain', (t, i) => `展缸${t}排液电池阀${i}`],
    ['blow', (t, i) => `展缸${t}吹气电池阀${i}`],
  ]
  for (const t of [1, 2]) {
    for (const [kind, label] of KINDS) {
      for (const i of [1, 2, 3, 4]) {
        out.push({ id: `dev_t${t}_${kind}${i}`, label: label(t, i) })
      }
    }
  }
  return out
}

test('classifyCylinder: 各工位真实 label 全部命中预期类', () => {
  // 判序: 阀 > 泵 > 电机 > 气缸 > other
  assert.equal(classifyCylinder({ label: '收集下压气缸' }), 'cylinder')
  assert.equal(classifyCylinder({ label: '溶液收集瓶定位气缸' }), 'cylinder')
  assert.equal(classifyCylinder({ label: '展缸1进液电池阀1' }), 'valve')
  assert.equal(classifyCylinder({ label: '收集排液3通阀' }), 'valve')
  assert.equal(classifyCylinder({ label: '刮板拍照真空阀' }), 'valve')
  assert.equal(classifyCylinder({ label: '上样吹气二通阀' }), 'valve')
  assert.equal(classifyCylinder({ label: '大真空泵' }), 'pump')
  assert.equal(classifyCylinder({ label: '刮板拍照无刷电机' }), 'motor')
  assert.equal(classifyCylinder({ label: '粉末收集器定位气缸' }), 'cylinder')
  assert.equal(classifyCylinder({ label: '神秘新设备' }), 'other')
  assert.equal(classifyCylinder(null), 'other')
})

test('buildGroups: 按序成组、空组剔除、未知落 other 永不丢失', () => {
  // photoscrape 形态: 4 气缸 + 1 阀 + 1 电机
  const ps = buildGroups([
    { id: 'ps_shade', label: '刮板拍照遮光气缸' },
    { id: 'ps_rotate', label: '刮板拍照旋转气缸' },
    { id: 'ps_press', label: '刮板拍照下压气缸' },
    { id: 'ps_vacuum', label: '刮板拍照真空阀' },
    { id: 'ps_motor', label: '刮板拍照无刷电机' },
    { id: 'ps_locator', label: '刮板拍照定位气缸' },
  ])
  assert.deepEqual(ps.map((g) => g.key), ['cylinder', 'valve', 'motor'])
  assert.deepEqual(ps.map((g) => g.items.length), [4, 1, 1])
  assert.equal(ps[0].title, '气缸')

  // pump 形态: 单泵 → 只出一组; 条目总数守恒
  const pump = buildGroups([{ id: 'pump_vacuum', label: '大真空泵' }])
  assert.deepEqual(pump.map((g) => g.key), ['pump'])

  const withUnknown = buildGroups([
    { id: 'x1', label: '神秘新设备' },
    { id: 'col_press', label: '收集下压气缸' },
  ])
  assert.deepEqual(withUnknown.map((g) => g.key), ['cylinder', 'other'])
  assert.equal(withUnknown.reduce((n, g) => n + g.items.length, 0), 2)

  assert.deepEqual(buildGroups([]), [])
  assert.deepEqual(buildGroups(undefined), [])
})

// 三维手动面板走 manifest 条目 (多带一个 kind 字段), 分类器 label 优先、kind 兜底
test('classifyMechanism: label 判不出才回落 kind (机械臂末端 4 件)', () => {
  // 这 4 条 label 不含 阀/泵/电机/气缸 任一关键字 → 落 other → 回落到 manifest 的 kind
  assert.equal(classifyMechanism({ id: 'rob_flip_suction', label: '吸盘翻转', kind: 'rotary' }), 'rotary')
  assert.equal(classifyMechanism({ id: 'rob_grip_plate96', label: '96孔板夹爪', kind: 'gripper' }), 'gripper')
  assert.equal(classifyMechanism({ id: 'rob_grip_vial', label: '样品瓶电爪', kind: 'gripper' }), 'gripper')
  assert.equal(classifyMechanism({ id: 'rob_suction', label: '吸盘真空', kind: 'vacuum' }), 'vacuum')
})

test('classifyMechanism: label 优先于 manifest 的错误 kind (ps_motor 回归锁)', () => {
  // gen_twin_manifest.py 把 "电机" 与 "阀" 并进同一分支, 故 manifest 标它 valve;
  // 直接信 kind 会让无刷电机掉进电磁阀组 —— 本用例锁住 label 判序优先
  assert.equal(classifyMechanism({ id: 'ps_motor', label: '刮板拍照无刷电机', kind: 'valve' }), 'motor')
  // PLC 侧其余条目: label 命中即用, kind 一致与否都不影响
  assert.equal(classifyMechanism({ id: 'dev_t1_cyl1', label: '展缸1气缸1', kind: 'cylinder' }), 'cylinder')
  assert.equal(classifyMechanism({ id: 'dev_t1_blow1', label: '展缸1吹气电池阀1', kind: 'valve' }), 'valve')
  assert.equal(classifyMechanism({ id: 'pump_vacuum', label: '大真空泵', kind: 'pump' }), 'pump')
})

test('classifyMechanism: label 与 kind 都不认 → other (新设备永不丢失)', () => {
  assert.equal(classifyMechanism({ id: 'x1', label: '神秘新设备', kind: 'teleporter' }), 'other')
  assert.equal(classifyMechanism({ id: 'x2', label: '神秘新设备' }), 'other')
  assert.equal(classifyMechanism(null), 'other')
})

test('buildGroups(rows, classifyMechanism): 按新 GROUP_ORDER 出组, 条目总数守恒', () => {
  const rows = [
    { id: 'dev_t1_cyl1', label: '展缸1气缸1', kind: 'cylinder' },
    { id: 'dev_t1_blow1', label: '展缸1吹气电池阀1', kind: 'valve' },
    { id: 'pump_vacuum', label: '大真空泵', kind: 'pump' },
    { id: 'ps_motor', label: '刮板拍照无刷电机', kind: 'valve' },
    { id: 'rob_grip_plate96', label: '96孔板夹爪', kind: 'gripper' },
    { id: 'rob_grip_vial', label: '样品瓶电爪', kind: 'gripper' },
    { id: 'rob_flip_suction', label: '吸盘翻转', kind: 'rotary' },
    { id: 'rob_suction', label: '吸盘真空', kind: 'vacuum' },
  ]
  const groups = buildGroups(rows, classifyMechanism)
  assert.deepEqual(groups.map((g) => g.key), [
    'cylinder', 'valve', 'pump', 'motor', 'gripper', 'rotary', 'vacuum',
  ])
  assert.deepEqual(groups.map((g) => g.items.length), [1, 1, 1, 1, 2, 1, 1])
  assert.deepEqual(groups.map((g) => g.title), [
    '气缸', '电磁阀', '泵', '电机', '夹爪', '旋转', '真空',
  ])
  assert.equal(groups.reduce((n, g) => n + g.items.length, 0), rows.length)
})

test('buildGroups: 不传分类器时行为不变 (2D 面板调用点向后兼容)', () => {
  const rows = [{ id: 'col_press', label: '收集下压气缸' }, { id: 'x1', label: '神秘新设备' }]
  assert.deepEqual(buildGroups(rows), buildGroups(rows, classifyCylinder))
})

test('buildDevelopMatrix: 32 条全格命中 → 2 展缸 × 4 缸位 × 4 功能', () => {
  const m = buildDevelopMatrix(developCylinders())
  assert.ok(m)
  assert.deepEqual(m.tanks.map((t) => t.tank), [1, 2])
  for (const t of m.tanks) {
    assert.equal(t.rows.length, 4)
    t.rows.forEach((row, i) => {
      assert.equal(row.idx, i + 1)
      assert.ok(row.cyl && row.fill && row.drain && row.blow)
    })
  }
  // 抽查落位: 展缸2 缸位3 的排液阀
  assert.equal(m.tanks[1].rows[2].drain.id, 'dev_t2_drain3')
})

test('buildDevelopMatrix: 契约破坏整体回退 null (不半渲染)', () => {
  const full = developCylinders()
  // 混入外来 id
  assert.equal(buildDevelopMatrix([...full, { id: 'col_press', label: '收集下压气缸' }]), null)
  // 缺一格
  assert.equal(buildDevelopMatrix(full.filter((c) => c.id !== 'dev_t1_blow2')), null)
  // 重复条目
  assert.equal(buildDevelopMatrix([...full, { id: 'dev_t1_cyl1', label: '展缸1气缸1' }]), null)
  // 空清单
  assert.equal(buildDevelopMatrix([]), null)
  assert.equal(buildDevelopMatrix(undefined), null)
})

test('axisShortName: axis_8y → 8Y, 全 11 轴命中, 不匹配原样回退', () => {
  for (const [id, short] of [
    ['axis_1z', '1Z'], ['axis_2z', '2Z'], ['axis_3y', '3Y'], ['axis_4x', '4X'],
    ['axis_5z', '5Z'], ['axis_6x', '6X'], ['axis_7y', '7Y'], ['axis_8y', '8Y'],
    ['axis_9x', '9X'], ['axis_10z', '10Z'], ['axis_11y', '11Y'],
  ]) {
    assert.equal(axisShortName(id), short)
  }
  assert.equal(axisShortName('spindle'), 'spindle')
  assert.equal(axisShortName(''), '')
  assert.equal(axisShortName(undefined), '')
})
