// localStorage JSON 读写小工具 — 收编各处内联 try/catch (评审 F12; 键命名空间/配额清理将来只改这一处)。
// 仅收编存 JSON 的键: stores/theme.js / stores/layout.js 存裸串/裸整数, 并入 JSON 会破坏存量用户键,
// 有意不收编 (母 spec F12 收窄定案)。

// 读 key 并 JSON.parse; 键缺失/解析失败/存储被禁 → 返回 fallback。值形状守卫留给调用方。
export function loadJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw == null ? fallback : JSON.parse(raw)
  } catch {
    return fallback
  }
}

// JSON.stringify 后写入; 存储禁用/配额满 → 静默放弃
export function saveJson(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)) } catch { /* 存储禁用/满: 静默放弃 */ }
}
