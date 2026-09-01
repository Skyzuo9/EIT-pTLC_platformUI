// 弹窗可达性行为层: 焦点圈禁 + 打开移焦/关闭还焦 + Esc
// ========================================================
// 只管"行为"; role="dialog"/aria-modal 等标记是模板层的事 (ModalShell 已带,
// 自有 markup 的弹窗如 HitlModal 自己在根元素上补)。
//
// 不变量:
//   1. 打开沿记录 document.activeElement, 关闭沿还焦包 try/catch (原元素可能已被 v-if 卸载)。
//   2. Tab 圈禁在 document keydown 捕获阶段做 (Teleport 后 DOM 不在 #app 里, 冒泡链不可靠)。
//   3. 焦点逃逸 (activeElement 落到弹窗外) 时下一次 Tab 强制拉回第一个可聚焦元素。
//   4. onEsc 不传 = 不响应 Esc (HitlModal 这类必须显式决策的门用)。
import { nextTick, onBeforeUnmount, watch } from 'vue'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * @param {import('vue').Ref<HTMLElement|null>} rootRef 弹窗卡片根元素
 * @param {object} opts
 * @param {import('vue').Ref<boolean>|import('vue').ComputedRef<boolean>} opts.open 打开状态
 * @param {Function} [opts.onEsc] Esc 回调; 不传则 Esc 不做任何事
 * @param {string|Function} [opts.initialFocus] 打开后聚焦目标 (css 选择器或 () => HTMLElement);
 *     缺省取弹窗内第一个可聚焦元素, 再兜底聚焦根元素 (根元素需 tabindex="-1")
 */
export function useModalA11y(rootRef, { open, onEsc, initialFocus } = {}) {
  let restoreEl = null

  function focusables() {
    const root = rootRef.value
    if (!root) return []
    return Array.from(root.querySelectorAll(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    )
  }

  function focusInitial() {
    const root = rootRef.value
    if (!root) return
    let el = null
    if (typeof initialFocus === 'string') el = root.querySelector(initialFocus)
    else if (typeof initialFocus === 'function') el = initialFocus()
    if (!el) el = focusables()[0] || root
    try {
      el.focus()
    } catch (_e) {
      /* 元素不可聚焦时忽略 */
    }
  }

  function onKeydown(e) {
    if (!open.value || !rootRef.value) return
    if (e.key === 'Escape') {
      if (onEsc) {
        e.stopPropagation()
        onEsc()
      }
      return
    }
    if (e.key !== 'Tab') return
    const list = focusables()
    if (!list.length) {
      e.preventDefault()
      focusInitial()
      return
    }
    const active = document.activeElement
    const inRoot = rootRef.value.contains(active)
    const first = list[0]
    const last = list[list.length - 1]
    if (!inRoot) {
      e.preventDefault()
      first.focus()
    } else if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }

  watch(
    open,
    (isOpen, wasOpen) => {
      if (isOpen && !wasOpen) {
        restoreEl = document.activeElement
        nextTick(focusInitial)
      } else if (!isOpen && wasOpen) {
        const el = restoreEl
        restoreEl = null
        if (el && typeof el.focus === 'function') {
          try {
            el.focus()
          } catch (_e) {
            /* 原元素已卸载, 焦点留给浏览器缺省 */
          }
        }
      }
    },
    { immediate: true },
  )

  document.addEventListener('keydown', onKeydown, true)
  onBeforeUnmount(() => {
    document.removeEventListener('keydown', onKeydown, true)
  })
}
