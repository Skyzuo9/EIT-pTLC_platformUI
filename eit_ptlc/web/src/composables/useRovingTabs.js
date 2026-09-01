// 页签 roving tabindex (WAI-ARIA tabs 模式)
// ==========================================
// 语义: 页签组在 Tab 序里只占一站 (活动页签 tabindex=0, 其余 -1), ←/→ 在组内巡航
// (循环)、Home/End 到两端, 巡航即激活 (焦点跟随)。
//
// 两种接法:
//   1. 纯赋值页签 (ActionDetail/RightPanel): useRovingTabs(keys, tabRef) —— 巡航直写
//      active 并立即移焦。
//   2. 切换带副作用的页签 (未保存确认门/轮询启停): 传 { onChange } —— 巡航不写 active,
//      改调 onChange(nextKey) 由消费者走自己的切换函数 (可 async 可取消); 焦点只在
//      active **实际变化后**跟随 (pendingFocusKey 门: 点击/深链/程序切换引起的 active
//      变化不抢焦点; 确认被取消 → active 不变 → 焦点留在原页签)。
//
// 用法 (tabs 顺序与模板 v-for/静态序一致):
//   const roving = useRovingTabs(['form', 'doc'], tabRef, { onChange: switchTab })
//   <button role="tab" :tabindex="roving.tabindex('doc')" @keydown="roving.onKeydown" …>
// onKeydown 依赖按钮在同一 [role=tablist] 容器内。
import { unref, watch } from 'vue'

/**
 * @param {Array<string>|import('vue').Ref<Array<string>>} keys 页签 key 序 (与渲染序一致)
 * @param {import('vue').Ref<string>} active 当前激活页签 (可写 ref/computed)
 * @param {object} [opts]
 * @param {(nextKey: string) => void} [opts.onChange] 提供时巡航改走它 (消费者的切换函数)
 * @returns {{ tabindex: (key: string) => 0|-1, onKeydown: (e: KeyboardEvent) => void }}
 */
export function useRovingTabs(keys, active, { onChange } = {}) {
  let lastTablist = null // onChange 路径: onKeydown 时缓存, watch 移焦时查兄弟
  let pendingFocusKey = null // 仅键盘巡航发起的 active 变化才移焦

  function tabindex(key) {
    return unref(active) === key ? 0 : -1
  }

  function onKeydown(e) {
    const list = unref(keys)
    let idx = list.indexOf(unref(active))
    if (idx < 0) idx = 0
    let next = null
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (idx + 1) % list.length
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (idx - 1 + list.length) % list.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = list.length - 1
    if (next === null) return
    e.preventDefault()
    const nextKey = list[next]
    if (onChange) {
      lastTablist = e.currentTarget.closest('[role="tablist"]')
      pendingFocusKey = nextKey
      onChange(nextKey) // 可 async 可取消; 成败由下方 watch 按 active 实际值判定
      return
    }
    active.value = nextKey
    // 焦点跟随: 在同一 tablist 容器内按序取 role=tab 兄弟
    const tablist = e.currentTarget.closest('[role="tablist"]')
    const tabs = tablist ? tablist.querySelectorAll('[role="tab"]') : null
    if (tabs && tabs[next]) tabs[next].focus()
  }

  if (onChange) {
    // post-flush: tabindex 已按新 active 渲染完再移焦; 确认弹窗的还焦发生在 resolve 时
    // (早于 active 写入), 本处 focus 在其后执行故胜出
    watch(active, (v) => {
      const want = pendingFocusKey
      pendingFocusKey = null
      if (v !== want || !lastTablist) return
      const idx = unref(keys).indexOf(v)
      const tabs = lastTablist.querySelectorAll('[role="tab"]')
      if (tabs[idx]) tabs[idx].focus()
    }, { flush: 'post' })
  }

  return { tabindex, onKeydown }
}
