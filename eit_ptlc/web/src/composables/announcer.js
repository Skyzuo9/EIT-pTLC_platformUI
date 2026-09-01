// 全局读屏播报单例 (aria-live)
// ================================
// 为什么是全局单例而不是各处自放 live region: v-if 动态挂载的 live region 在多数
// 读屏/浏览器组合下首播不可靠 (region 必须先于内容存在), 逐处铺开必然有漏。
// 本模块只维护两条文本 ref, 由 App.vue 挂载的 <LiveRegions> 常驻渲染成
// role="status"(polite) 与 role="alert"(assertive) 两个 .sr-only 元素, 内容置换即播报。
//
// 使用约定 (与局部方案的边界):
//   1. 用户动作的结果 (保存/执行/下载/急停) → announce(); 首选经 useAsyncAction 自动接入。
//   2. 常驻且内容置换的校验/计数区 (如 DebugDock .foot-err) → 元素自身加 role="status",
//      不要再 announce, 避免双读。
//   3. assertive 只给安全相关 (急停结果/报警/失败), 其余一律 polite。
//
// 不变量:
//   - 100ms 合并窗口: 遥测风暴/批量校验触发的连发播报只读最后一条, 不刷屏。
//   - 同文本重播时尾附   制造 DOM 变化, 否则 AT 不会重读。
import { ref } from 'vue'

const MERGE_MS = 100

const politeText = ref('')
const assertiveText = ref('')

const channels = {
  polite: { target: politeText, timer: null, pending: '' },
  assertive: { target: assertiveText, timer: null, pending: '' },
}

function flush(name) {
  const ch = channels[name]
  ch.timer = null
  let out = ch.pending
  if (out && ch.target.value === out) out += ' '
  ch.target.value = out
}

/**
 * 功能:
 *     向读屏播报一条消息 (视觉上不可见; 视觉反馈仍由调用方的 .result/文案负责)
 * 参数:
 *     text 字符串, 播报内容; 空串等效清空播报区
 *     opts.assertive 布尔, true 走 role="alert" 立即打断 (仅安全相关), 默认 polite
 * 返回:
 *     None
 */
export function announce(text, { assertive = false } = {}) {
  const ch = channels[assertive ? 'assertive' : 'polite']
  ch.pending = String(text == null ? '' : text)
  if (ch.timer) return // 合并窗口内: 只更新 pending, 收口时取最新
  ch.timer = setTimeout(() => flush(assertive ? 'assertive' : 'polite'), MERGE_MS)
}

// LiveRegions.vue 消费; 其它模块不要直接写
export { politeText, assertiveText }
