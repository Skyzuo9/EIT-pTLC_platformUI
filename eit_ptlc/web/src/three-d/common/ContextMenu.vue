<script setup>
/**
 * 功能: 通用右键快捷菜单 —— 固定定位于光标, 视口溢出自动翻转, 点外/Esc/失焦即关.
 *
 * 纯展示组件: 菜单项由宿主视图组装(items), 点击执行 item.action 并统一 emit close,
 * 装配台与材质台共用. 关闭监听挂 window **capture** 阶段 —— 保证先于 canvas 的
 * 场景 handler 判定; 菜单由 contextmenu(发生在 pointerup 之后)打开, 打开那一次
 * 点击不会立刻自杀.
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  /** 打开位置(clientX/clientY) */
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  /**
   * 菜单项: {key?, label, action?, disabled?, danger?, divider?, hint?,
   *          children?, onHover?}
   * divider: true 的行只画分隔线, 其余字段忽略.
   * children: 子项数组(同构; 仅支持一层), 悬浮/点击该行时贴行展开子面板.
   * onHover: 悬浮该行时回调(材质台用来高亮成员包围盒); 均为可选, 不传零变化.
   */
  items: { type: Array, required: true },
})

const emit = defineEmits(['close', 'select'])

const menuRoot = ref(null)
/** 定位样式(挂载后按自身尺寸翻转/夹取) */
const style = ref({ left: `${props.x}px`, top: `${props.y}px` })
/** 展开中的子面板: {index, style} | null(同时只开一个) */
const sub = ref(null)

/**
 * 功能: 点击一个菜单项.
 * @param {object} item 菜单项
 * @returns {void}
 */
function pick(item) {
  if (item.disabled || item.divider) return
  emit('select', item)
  item.action?.()
  emit('close')
}

/**
 * 功能: 悬浮/点击一行 —— 触发 onHover 回调, 有子项则贴行展开子面板.
 *
 * 子面板不做悬浮离开即关: 从行移进子面板必经过行边界, 计时器方案又碎又抖;
 * 悬浮到其他行或整个菜单关闭时自然收起, 与桌面软件的一层子菜单行为一致.
 *
 * @param {object} item 菜单项
 * @param {number} index 行号
 * @param {Event} event 鼠标事件(取行位置)
 * @returns {void}
 */
function openSub(item, index, event) {
  item.onHover?.()
  if (!item.children?.length) {
    if (!item.divider) sub.value = null
    return
  }
  const row = event.currentTarget.getBoundingClientRect()
  const menuRect = menuRoot.value?.getBoundingClientRect()
  if (!menuRect) return
  // 默认贴菜单右缘展开; 视口右侧放不下就翻到左侧(180 为子面板预估宽)
  let left = menuRect.width - 4
  if (menuRect.right + 180 > window.innerWidth - 4) left = -176
  sub.value = { index, style: { left: `${left}px`, top: `${row.top - menuRect.top}px` } }
}

/**
 * 功能: 行点击分发 —— 有子项的行点击等于展开(照顾触控), 其余执行动作.
 * @param {object} item 菜单项
 * @param {number} index 行号
 * @param {Event} event 鼠标事件
 * @returns {void}
 */
function onItemClick(item, index, event) {
  if (item.children?.length) openSub(item, index, event)
  else pick(item)
}

function onWindowPointerDown(event) {
  if (menuRoot.value?.contains(event.target)) return
  emit('close')
}

function onKeydown(event) {
  if (event.key === 'Escape') emit('close')
}

function onClose() {
  emit('close')
}

onMounted(async () => {
  window.addEventListener('pointerdown', onWindowPointerDown, true)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('blur', onClose)
  window.addEventListener('resize', onClose)

  await nextTick()
  const rect = menuRoot.value?.getBoundingClientRect()
  if (!rect) return
  let left = props.x
  let top = props.y
  if (left + rect.width > window.innerWidth - 4) left = props.x - rect.width
  if (top + rect.height > window.innerHeight - 4) top = props.y - rect.height
  style.value = {
    left: `${Math.max(4, left)}px`,
    top: `${Math.max(4, top)}px`,
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onWindowPointerDown, true)
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('blur', onClose)
  window.removeEventListener('resize', onClose)
})
</script>

<template>
  <div
    ref="menuRoot"
    class="cm"
    :style="style"
    @contextmenu.prevent
  >
    <template v-for="(item, index) in items" :key="item.key || index">
      <div v-if="item.divider" class="cm__divider" />
      <button
        v-else
        type="button"
        class="cm__item"
        :class="{ 'cm__item--danger': item.danger, 'cm__item--open': sub?.index === index }"
        :disabled="item.disabled"
        @mouseenter="openSub(item, index, $event)"
        @click="onItemClick(item, index, $event)"
      >
        <span class="cm__label">{{ item.label }}</span>
        <span v-if="item.hint" class="cm__hint">{{ item.hint }}</span>
        <span v-if="item.children?.length" class="cm__caret">▸</span>
      </button>
    </template>

    <div
      v-if="sub && items[sub.index]?.children?.length"
      class="cm cm--sub"
      :style="sub.style"
      @contextmenu.prevent
    >
      <template v-for="(child, ci) in items[sub.index].children" :key="child.key || ci">
        <div v-if="child.divider" class="cm__divider" />
        <button
          v-else
          type="button"
          class="cm__item"
          :class="{ 'cm__item--danger': child.danger }"
          :disabled="child.disabled"
          @mouseenter="child.onHover?.()"
          @click="pick(child)"
        >
          <span class="cm__label">{{ child.label }}</span>
          <span v-if="child.hint" class="cm__hint">{{ child.hint }}</span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.cm {
  position: fixed;
  z-index: 30;
  display: flex;
  flex-direction: column;
  min-width: 168px;
  padding: 4px;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 8px;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgb(0 0 0 / 0.28);
  user-select: none;
}

.cm__item {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 5px 10px;
  font-size: 12px;
  color: var(--text-mid);
  text-align: left;
  cursor: pointer;
  background: none;
  border: none;
  border-radius: 5px;
}

.cm__item:hover:not(:disabled) {
  color: var(--text-bright);
  background: var(--control-hover);
}

.cm__item:disabled {
  cursor: default;
  opacity: 0.35;
}

.cm__item--danger {
  color: var(--err-bright, #d95757);
}

.cm__item--danger:hover:not(:disabled) {
  color: #fff;
  background: #d95757;
}

.cm__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cm__hint {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.cm__divider {
  height: 1px;
  margin: 3px 6px;
  background: var(--hair);
}

.cm__caret {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.cm__item--open {
  color: var(--text-bright);
  background: var(--control-hover);
}

/* 子面板: 绝对定位挂在菜单根(fixed)上, 贴行展开 */
.cm--sub {
  position: absolute;
  z-index: 31;
  min-width: 172px;
}
</style>
