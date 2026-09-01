// 一键审查的纯展示逻辑 (node --test 可测): severity 样式/文案映射 + 修复动作闭集。
// 行结构与 severity 词表由后端 runtime/material_audit.py 定义, 此处只做展示映射 ——
// 判定逻辑一概不在前端重算。

// severity -> 展示文案 (与后端闭集一一对应; 未知值按"未知"渲染不报错)
export const SEVERITY_LABEL = {
  mismatch: '不一致',
  warn: '提示',
  unverifiable: '无法核验',
  ok: '一致',
  skip: '未核对',
}

// severity -> 样式类 (MaterialAudit.vue scoped 样式按此配色)
export function severityClass(severity) {
  const known = { mismatch: 'sev-mismatch', warn: 'sev-warn',
                  unverifiable: 'sev-unverifiable', ok: 'sev-ok', skip: 'sev-skip' }
  return known[severity] || 'sev-unknown'
}

export function severityLabel(severity) {
  return SEVERITY_LABEL[severity] || String(severity || '未知')
}

// 修复动作闭集: 前端只把后端给的 fix.action 映射到**既有写端点**的调用,
// 不执行后端下发的任意 URL。列表外的 action 只渲染跳转不渲染修复按钮。
export const FIX_ACTIONS = [
  'magazine', 'bottle', 'staging', 'rack', 'seat', 'payload_seat',
  'reservation_release',
]

// fix 是否可渲染成一键修复按钮 (动作在闭集内且带载荷)
export function fixAllowed(fix) {
  if (!fix || typeof fix !== 'object') return false
  if (!FIX_ACTIONS.includes(fix.action)) return false
  return !!fix.payload && typeof fix.payload === 'object'
}

// 计数徽标的展示序与非零过滤: 全 0 时返回空数组 (页面显示"未运行/全空")
export function countBadges(counts) {
  const order = [
    ['mismatch', '不一致'], ['warn', '提示'], ['unverifiable', '无法核验'],
    ['ok', '一致'], ['skipped', '未核对'],
  ]
  const out = []
  for (const [key, label] of order) {
    const n = Number(counts?.[key] || 0)
    if (n > 0) out.push({ key, label, count: n })
  }
  return out
}
