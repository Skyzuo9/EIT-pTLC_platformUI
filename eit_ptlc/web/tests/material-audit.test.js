// 一键审查纯展示逻辑测试 (utils/audit.js): severity 映射闭集 + 修复动作白名单 + 计数徽标。
// 判定逻辑在后端 (runtime/material_audit.py, 有 pytest); 此处锁的是前端映射面 ——
// 尤其是 FIX_ACTIONS 闭集: 修复按钮只许映射到既有写端点, 不执行后端下发的任意 URL。
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  FIX_ACTIONS, countBadges, fixAllowed, severityClass, severityLabel,
} from '../src/utils/audit.js'

test('severityClass: 闭集映射 + 未知值兜底', () => {
  assert.equal(severityClass('mismatch'), 'sev-mismatch')
  assert.equal(severityClass('warn'), 'sev-warn')
  assert.equal(severityClass('unverifiable'), 'sev-unverifiable')
  assert.equal(severityClass('ok'), 'sev-ok')
  assert.equal(severityClass('skip'), 'sev-skip')
  assert.equal(severityClass('whatever'), 'sev-unknown')
  assert.equal(severityClass(undefined), 'sev-unknown')
})

test('severityLabel: 中文文案与未知值原样透出', () => {
  assert.equal(severityLabel('mismatch'), '不一致')
  assert.equal(severityLabel('skip'), '未核对')
  assert.equal(severityLabel('odd'), 'odd')
})

test('fixAllowed: 动作闭集白名单, 列表外/缺载荷一律拒', () => {
  // 与 MaterialAudit.vue 的 FIX_RUNNERS 键集一致 (改一边必须改另一边)
  assert.deepEqual(FIX_ACTIONS, [
    'magazine', 'bottle', 'staging', 'rack', 'seat', 'payload_seat',
    'reservation_release',
  ])
  assert.ok(fixAllowed({ action: 'magazine', payload: { magazine: 'feed', count: 0 } }))
  assert.ok(fixAllowed({ action: 'reservation_release',
                         payload: { sample_id: 's1', kind: 'bottle' } }))
  assert.equal(fixAllowed(null), false)
  assert.equal(fixAllowed({ action: 'magazine' }), false, '缺载荷不许渲染修复按钮')
  assert.equal(fixAllowed({ action: 'rm -rf', payload: {} }), false, '列表外动作一律拒')
  assert.equal(fixAllowed({ action: 'http://evil', payload: {} }), false)
})

test('countBadges: 展示序固定 + 零值过滤', () => {
  const badges = countBadges({ mismatch: 2, warn: 0, unverifiable: 3, ok: 10, skipped: 1 })
  assert.deepEqual(badges.map((b) => b.key), ['mismatch', 'unverifiable', 'ok', 'skipped'])
  assert.deepEqual(badges[0], { key: 'mismatch', label: '不一致', count: 2 })
  assert.deepEqual(countBadges(null), [], '无计数时返回空数组 (页面显示提示语)')
  assert.deepEqual(countBadges({ mismatch: 0, ok: 0 }), [])
})
