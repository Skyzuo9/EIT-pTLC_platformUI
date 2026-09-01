/**
 * 功能: 展缸盖耦合运动学的回归 —— 主参数(盖抬升)必须唯一确定摆角与滑车行程.
 *
 * 这条约束是"连接处错位"那个 bug 的根治面: 摆角 θ、抬升 h、滑车行程 s 被
 * |铰点−枢轴| = R 一条几何锁死, 只有一个自由度. 动作页早前把一个数一刀切套给
 * 全部成员, 盖与摆臂立刻脱节. 本测试锁三件事: 解算与实测几何自洽、越界必须拒绝、
 * 摊给成员的 outputRange 按角色分派且保持"值1=基准态"的反相语义.
 *
 * 公式与 pipeline/gen_twin_manifest.solve_lid_kinematics 同源, 那边改了这里要同步.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { outputRangesForLift, primaryParam, solveLift } from '../../src/three-d/motion/linkageKinematics.js'

/** 架1 TANK_1 的实测几何(逐顶点, 与 03 报告一致) */
const KIN = {
  model: 'crank-slider-lift',
  d0Mm: 60.9,
  v0Mm: 109.2,
  radiusMm: 125.03,
  singularMarginMm: 3,
  maxLiftMm: 81.8,
  minLiftMm: 5,
  roles: ['rocker', 'rocker', 'lid', 'carriage'],
  liftMm: 80,
}

test('抬升→摆角/行程的解算与实测几何自洽', () => {
  // h=0 时摆臂停在建模态: 行程与摆角都为 0
  const zero = solveLift(KIN, 5)
  assert.ok(zero.travelMm > 0 && zero.thetaDeg > 0, '有抬升就必有行程与摆角')

  // 35.4mm 抬升 ↔ 40mm 行程 ↔ 24.66°(上一版实测值, 反解必须复现)
  const mid = solveLift(KIN, 35.36)
  assert.ok(Math.abs(mid.travelMm - 40) < 0.1, `行程应≈40mm: ${mid.travelMm}`)
  assert.ok(Math.abs(mid.thetaDeg - 24.66) < 0.1, `摆角应≈24.66°: ${mid.thetaDeg}`)

  // 用户要的 80mm: 摆臂 47.5°, 滑车 60.7mm
  const full = solveLift(KIN, 80)
  assert.ok(Math.abs(full.travelMm - 60.67) < 0.1, `行程应≈60.7mm: ${full.travelMm}`)
  assert.ok(Math.abs(full.thetaDeg - 47.35) < 0.1, `摆角应≈47.35°: ${full.thetaDeg}`)

  // 单调: 抬得越高, 行程与摆角都越大
  assert.ok(full.travelMm > mid.travelMm && full.thetaDeg > mid.thetaDeg)
})

test('越界抬升必须拒绝(摆臂逼近转平的奇异位)', () => {
  assert.throws(() => solveLift(KIN, KIN.maxLiftMm + 1), /越界/)
  assert.throws(() => solveLift(KIN, 0), /越界/)
  assert.throws(() => solveLift(KIN, Number.NaN), /数字/)
})

test('按角色摊给成员: 摆杆得角度、盖得抬升、滑车得行程, 一律 [行程, 0] 反相', () => {
  const ranges = outputRangesForLift(KIN, 80)
  assert.equal(ranges.length, 4)
  const [rockerF, rockerR, lid, carriage] = ranges
  assert.deepEqual(rockerF, rockerR, '前后摆杆必须同角(平行四边形)')
  assert.ok(Math.abs(rockerF[0] - 47.35) < 0.02, `摆杆输出应是角度 47.35°: ${rockerF[0]}`)
  assert.ok(Math.abs(lid[0] - 80) < 0.02, `盖输出应是抬升 80mm: ${lid[0]}`)
  assert.ok(Math.abs(carriage[0] - 60.67) < 0.02, `滑车输出应是行程 60.7mm: ${carriage[0]}`)
  for (const range of ranges) {
    assert.equal(range[1], 0, '值 1=关盖=GLB 基准态 ⇒ 区间必须降序到 0')
  }
})

test('primaryParam: 只有耦合机构才提供主参数(普通夹爪返回 null)', () => {
  const meta = primaryParam(KIN)
  assert.equal(meta.key, 'liftMm')
  assert.equal(meta.unit, 'mm')
  assert.equal(meta.max, 81.8)
  assert.equal(primaryParam({ model: 'plain' }), null)
  assert.equal(primaryParam(undefined), null)
})
