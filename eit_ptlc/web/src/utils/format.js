// 展示格式化小工具 (节点遥测 / 时间)
// Intl 格式器在模块顶层预建一次 (每帧调用不重复构造); locale 锁定 zh-CN,
// 输出不再随浏览器区域设置漂移。
const FULL = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'medium', hour12: false })
const SHORT = new Intl.DateTimeFormat('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
})
// 遥测数值: 定 2 位小数、不分组 (坐标/数组里出现千分位逗号会与 join 分隔符混淆)
const NUM2 = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false })

export function fmtTime(ts) {
  return ts ? FULL.format(new Date(ts * 1000)) : '—'
}

// 短时间戳 (MM/DD HH:mm); 入参为 epoch **毫秒** (Date.now() 同型) —
// 与上面 fmtTime 的秒入参双不同, 刻意分名, 勿合并勿互换 (评审 F11)
export function fmtShortMs(ms) {
  return SHORT.format(new Date(ms))
}

/**
 * 功能:
 *     数值定精度格式化 (不分组); 展示层统一入口, 替代散落的 toFixed
 * 参数:
 *     v 数值; digits 小数位, 默认 2
 * 返回:
 *     字符串; 非有限数值返回 '—'
 */
export function fmtNum(v, digits = 2) {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  if (digits === 2) return NUM2.format(v)
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false,
  }).format(v)
}

export function fmtValue(value) {
  if (Array.isArray(value)) return value.map((v) => (typeof v === 'number' ? fmtNum(v) : v)).join(', ')
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
