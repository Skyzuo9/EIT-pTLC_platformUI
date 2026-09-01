<script setup>
// 通用右键/⋯ 菜单 (命令式单例): <ContextMenu ref="menuRef" /> + menuRef.open(ev, items, title?)
// items: [{ key, label, variant?: 'danger'|'ok', disabled?, title?, onSelect }]
//
// 触发方约定 (必须遵守):
// - 行上 @contextmenu.prevent.stop / ⋯ 按钮 @click.stop —— document 关闭监听在挂载期注册
//   (照 DeviceParamsPanel 的教训: 开卡时才注册会被同一次冒泡立即关掉);
// - contextmenu 在 iOS Safari 不触发, 调用方必须同时提供可见 ⋯ 入口 (style.css .row-more)。
//
// z-index 900, 刻意低于模态 (.modal-backdrop 1000): 菜单项常打开 confirmAction/promptAction,
// pick 的顺序是 关菜单→还焦→onSelect, 菜单从不与模态共存; 异步到来的 HITL/confirm 也必须压过菜单
// (浮卡层 1200 在模态之上, 不能沿用)。
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const isOpen = ref(false)
const items = ref([])
const title = ref('')
const posStyle = ref({})
const rootEl = ref(null)
let restoreEl = null      // 关闭还焦目标 (⋯ 按钮自身 / 右键行内的可聚焦元素)
let openedAt = 0

const MENU_W = 200

function open(ev, list, head = '') {
  items.value = list
  title.value = head
  const t = ev.currentTarget
  restoreEl = ev.type === 'contextmenu'
    ? (t.closest?.('[tabindex], button') || t.querySelector?.('button') || t)
    : t
  let x, y
  if (ev.type === 'contextmenu') {
    x = ev.clientX
    y = ev.clientY
  } else {
    const r = t.getBoundingClientRect()   // ⋯ 场景: 右对齐锚在按钮下缘
    x = r.right - MENU_W
    y = r.bottom + 2
  }
  x = Math.max(8, Math.min(x, window.innerWidth - MENU_W - 8))
  // 半屏锚点法 (照 DeviceParamsPanel): 上半屏向下长 / 下半屏向上长, 免渲染后测高再翻
  posStyle.value = y < window.innerHeight / 2
    ? { left: `${x}px`, top: `${y}px`, bottom: 'auto' }
    : { left: `${x}px`, bottom: `${window.innerHeight - y}px`, top: 'auto' }
  isOpen.value = true
  openedAt = Date.now()
  nextTick(() => rootEl.value?.querySelector('button.cm-item:not(:disabled)')?.focus())
}

function close(restore = false) {
  if (!isOpen.value) return
  isOpen.value = false
  if (restore && restoreEl && document.contains(restoreEl)) restoreEl.focus()
  restoreEl = null
}

function pick(it) {
  if (it.disabled) return
  close(true)   // 先关+还焦: onSelect 里的 confirm 在打开沿记录 activeElement 作还焦目标
  it.onSelect?.()
}

function onDocClick() { close(false) }
function onDocContextmenu() {
  // 开卡 50ms 内忽略: 触发行的 contextmenu 冒泡到 document, 否则刚开即关
  if (Date.now() - openedAt > 50) close(false)
}
function onDocScroll() { close(false) }   // fixed 浮层不跟滚; scroll 不冒泡须 capture
function onKeydown(e) {
  if (!isOpen.value) return
  if (e.key === 'Tab') { close(false); return }
  const list = [...(rootEl.value?.querySelectorAll('button.cm-item:not(:disabled)') || [])]
  if (e.key === 'Escape') { e.stopPropagation(); close(true); return }
  if (!list.length) return
  const i = list.indexOf(document.activeElement)
  if (e.key === 'ArrowDown') { e.preventDefault(); list[(i + 1) % list.length].focus() }
  else if (e.key === 'ArrowUp') { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus() }
  else if (e.key === 'Home') { e.preventDefault(); list[0].focus() }
  else if (e.key === 'End') { e.preventDefault(); list[list.length - 1].focus() }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('contextmenu', onDocContextmenu)
  document.addEventListener('scroll', onDocScroll, { capture: true, passive: true })
  // window 捕获期先于 ModalShell 的 document 捕获监听, Esc 的 stopPropagation 才拦得住
  window.addEventListener('keydown', onKeydown, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('contextmenu', onDocContextmenu)
  document.removeEventListener('scroll', onDocScroll, { capture: true })
  window.removeEventListener('keydown', onKeydown, true)
})

defineExpose({ open, close })
</script>

<template>
  <Teleport to="body">
    <div v-if="isOpen" ref="rootEl" class="cm" role="menu" :style="posStyle" @click.stop>
      <div v-if="title" class="cm-head" :title="title">{{ title }}</div>
      <button v-for="it in items" :key="it.key" type="button" role="menuitem"
              class="cm-item" :class="it.variant" :disabled="it.disabled || undefined"
              :title="it.title || undefined" @click="pick(it)">{{ it.label }}</button>
    </div>
  </Teleport>
</template>

<style scoped>
.cm { position: fixed; z-index: 900; width: 200px; padding: 4px;
  background: var(--panel); border: 1px solid var(--border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md); max-height: 46vh; overflow-y: auto; }
.cm-head { padding: 5px 10px 4px; margin-bottom: 3px; font-size: var(--fs-11); color: var(--muted);
  border-bottom: 1px solid var(--border-soft);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cm-item { display: flex; width: 100%; align-items: center; gap: 8px; padding: 6px 10px;
  border: none; background: transparent; border-radius: var(--radius-md); cursor: pointer;
  font-size: var(--fs-13); color: var(--text); text-align: left; }
.cm-item:hover, .cm-item:focus-visible { background: var(--hover); }
.cm-item:disabled { opacity: 0.45; cursor: default; }
.cm-item:disabled:hover { background: transparent; }
/* 描边红/绿语汇与全局 .mini.danger / .mini.ok 同源: 红=删除入口, 绿=恢复性操作 */
.cm-item.danger { color: var(--bad); }
.cm-item.danger:hover, .cm-item.danger:focus-visible { background: var(--bad-soft); }
.cm-item.ok { color: var(--ok); }
.cm-item.ok:hover, .cm-item.ok:focus-visible { background: var(--ok-soft); }
</style>
