// opGroups.js: 流程库组内子栏分桶的行为锁 (样例取自 config/operation/06_robot 真实 ui 值)
import { strict as assert } from 'node:assert'
import test from 'node:test'

import { buildBuckets } from '../src/utils/opGroups.js'

test('无 subgroup 的组: 单匿名桶, 条目顺序原样保持 (非机械臂组渲染不变)', () => {
  const items = [
    { name: 'sampling_prepare', label: '上样-准备' },
    { name: 'sampling_run', label: '上样-执行', ui: { role: 'station_phase' } },
  ]
  const buckets = buildBuckets(items)
  assert.equal(buckets.length, 1)
  assert.equal(buckets[0].sub, null)
  assert.deepEqual(buckets[0].items.map((i) => i.name), ['sampling_prepare', 'sampling_run'])
})

test('机械臂组: 子栏按最小 ui.order 排序, 桶内按 ui.order (进入在退出前)', () => {
  const items = [
    // 故意打乱入参顺序 (上游 groupBy 按 label 排, 与工艺顺序无关)
    { name: 'robot_tool_pick', label: '装刀', ui: { subgroup: '刀库', order: 81 } },
    { name: 'robot_collect_holder_pick_exit', label: '收集工位取收集器-退出', ui: { subgroup: '收集工位', order: 54 } },
    { name: 'robot_feed_lift_pick_exit', label: '升降仓吸板-退出', ui: { subgroup: '升降仓', order: 12 } },
    { name: 'robot_collect_holder_pick_enter', label: '收集工位取收集器-进入', ui: { subgroup: '收集工位', order: 53 } },
    { name: 'robot_feed_lift_pick_enter', label: '升降仓吸板-进入', ui: { subgroup: '升降仓', order: 11 } },
  ]
  const buckets = buildBuckets(items)
  assert.deepEqual(buckets.map((b) => b.sub), ['升降仓', '收集工位', '刀库'])
  assert.deepEqual(buckets[0].items.map((i) => i.name), ['robot_feed_lift_pick_enter', 'robot_feed_lift_pick_exit'])
  assert.deepEqual(buckets[1].items.map((i) => i.name), ['robot_collect_holder_pick_enter', 'robot_collect_holder_pick_exit'])
})

test('混合与兜底: 无 subgroup 条目进匿名首桶; 缺 order 沉底且按 label 决序; 空入参得空数组', () => {
  const items = [
    { name: 'robot_new_b', label: 'B新流程', ui: { subgroup: '收集工位' } },   // 手建未标 order
    { name: 'robot_home_check', label: '回原点并查询', ui: { subgroup: '自检/回零', order: 92 } },
    { name: 'robot_draft', label: '草稿流程' },                               // 无 ui
    { name: 'robot_new_a', label: 'A新流程', ui: { subgroup: '收集工位' } },
    { name: 'robot_collect_bottle_pick', label: '收集工位取瓶', ui: { subgroup: '收集工位', order: 51 } },
  ]
  const buckets = buildBuckets(items)
  assert.deepEqual(buckets.map((b) => b.sub), [null, '收集工位', '自检/回零'])
  assert.deepEqual(buckets[0].items.map((i) => i.name), ['robot_draft'])
  // 有 order 的在前, 两个未标 order 的按 label 决序
  assert.deepEqual(buckets[1].items.map((i) => i.name), ['robot_collect_bottle_pick', 'robot_new_a', 'robot_new_b'])
  assert.deepEqual(buildBuckets([]), [])
  assert.deepEqual(buildBuckets(undefined), [])
})
