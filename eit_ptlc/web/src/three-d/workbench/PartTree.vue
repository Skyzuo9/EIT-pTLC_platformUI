<script setup>
/**
 * 功能: 零件层级树 —— 按三角形数排序的装配层级, 任意深度可展开, 供装配台与材质台共用.
 *
 * 排序按三角形数降序而不是按名字: 精简模型时你要找的永远是"最重的那几个",
 * 让它们自动浮到顶部, 比按字母序找快得多.
 *
 * 两种宿主的差异全部走可选 props:
 *   装配台  传 model(SelectionModel)  —— 选中态与标记色点都从它取
 *   材质台  传 selectedKeys + labelOf + dotColorOf —— 无标记概念, 色点显示材质基色
 *
 * 对外暴露 reveal(key): 三维点选后把层级树自动展开、滚动定位并闪烁提示该行 ——
 * 这是"我点的这个零件在结构里是哪一个"的唯一回答方式.
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import PartTreeNode from './PartTreeNode.vue'
import { MARK_STYLES } from './selectionModel.js'

const props = defineProps({
  /** 零件索引 */
  index: { type: Object, required: true },
  /** 选择模型(装配台); 材质台不传, 改用 selectedKeys */
  model: { type: Object, default: null },
  /** 版本号, 用于触发重算 */
  tick: { type: Number, default: 0 },
  /** 选中键集合(材质台); 与 model 二选一 */
  selectedKeys: { type: Object, default: null },
  /** 行显示名; 缺省为 中文名 || 节点名 */
  labelOf: { type: Function, default: null },
  /** 行色点颜色; 缺省为标记色(需要 model) */
  dotColorOf: { type: Function, default: null },
  /** 被手动隐藏(整棵子树)的零件键集合(Set); 命中的行显示闭眼图标 */
  hiddenKeys: { type: Object, default: null },
  /** 面板标题 */
  header: { type: String, default: '零件层级（按面数降序）' },
  /**
   * 合并块的虚拟成员行(材质台专用; 装配台不传即零变化, 见 PartTreeNode 说明)
   */
  membersOf: { type: Function, default: null },
  onMemberFocus: { type: Function, default: null },
  onMemberHover: { type: Function, default: null },
  memberBadgeOf: { type: Function, default: null },
  /** 归属筛选 chips: [{key, label}]; 不传不渲染 */
  filters: { type: Array, default: null },
  /** 行归属判定: filterOf(key) 返回 filters 里的 key(空串=不参与筛选) */
  filterOf: { type: Function, default: null },
})

const emit = defineEmits(['focus', 'unhide'])

/** 已展开的节点键 */
const expanded = ref(new Set())
/** 名称搜索关键字 */
const filter = ref('')
/** 激活的归属筛选 key(空=树模式) */
const activeFilter = ref('')
/** 滚动容器, reveal 定位用 */
const bodyRef = ref(null)
/** 正在闪烁提示的行键(响应式, 直接改 DOM class 会被 Vue 的补丁抹掉) */
const flashKey = ref('')
let flashTimer = null

const assemblies = computed(() => {
  props.tick // 依赖
  return props.index.assemblies
})

/**
 * 搜索/归属筛选命中列表: 关键字或归属 chip 任一激活时代替树渲染.
 * 惰性树没法做深层过滤(未展开的分支根本没渲染), 平铺是找到深层零件的唯一方式;
 * 点击命中行会清掉搜索并转为树内定位. 归属筛选沿用同一平铺渲染, 零新机制.
 */
const searchHits = computed(() => {
  props.tick
  const keyword = filter.value.trim().toLowerCase()
  const mode = activeFilter.value
  if (!keyword && !mode) return null
  const hits = []
  for (const key of props.index.allNames) {
    const item = props.index.get(key)
    if (!item) continue
    if (mode && (!props.filterOf || props.filterOf(item.key) !== mode)) continue
    if (
      keyword &&
      !(
        item.name.toLowerCase().includes(keyword) ||
        (item.chinese && item.chinese.toLowerCase().includes(keyword)) ||
        labelText(item).toLowerCase().includes(keyword)
      )
    ) {
      continue
    }
    hits.push(item)
  }
  hits.sort((a, b) => b.subtreeTriangles - a.subtreeTriangles)
  return hits.slice(0, 200)
})

/**
 * 功能: 行显示名.
 * @param {object} item 零件信息
 * @returns {string} 显示名
 */
function labelText(item) {
  return props.labelOf ? props.labelOf(item) : item.chinese || item.name
}

/**
 * 功能: 是否被选中.
 * @param {string} key 零件索引键
 * @returns {boolean}
 */
function isSelected(key) {
  props.tick
  if (props.selectedKeys) return props.selectedKeys.has(key)
  return props.model ? props.model.selected.has(key) : false
}

/**
 * 功能: 是否处于定位闪烁态.
 * @param {string} key 零件索引键
 * @returns {boolean}
 */
function isFlash(key) {
  return flashKey.value === key
}

/**
 * 功能: 是否被手动隐藏(整棵子树).
 * @param {string} key 零件索引键
 * @returns {boolean}
 */
function isHidden(key) {
  props.tick
  return props.hiddenKeys ? props.hiddenKeys.has(key) : false
}

/**
 * 功能: 闭眼图标点击转发 —— 请求恢复该零件的显示.
 * @param {string} key 零件索引键
 * @returns {void}
 */
function unhideRow(key) {
  emit('unhide', key)
}

/**
 * 功能: 行色点颜色.
 * @param {string} key 零件索引键
 * @returns {string|null} CSS 颜色
 */
function dotOf(key) {
  props.tick
  if (props.dotColorOf) return props.dotColorOf(key)
  if (!props.model) return null
  const mark = props.model.markOf(key)?.mark
  return mark ? MARK_STYLES[mark].color : null
}

/**
 * 功能: 切换展开态.
 * @param {string} key 零件索引键
 * @returns {void}
 */
function toggleExpand(key) {
  if (expanded.value.has(key)) expanded.value.delete(key)
  else expanded.value.add(key)
  expanded.value = new Set(expanded.value)
}

/**
 * 功能: 行点击转发(带原始事件, 宿主可读 Ctrl/Shift 做加选).
 * @param {string} key 零件索引键
 * @param {MouseEvent} [event] 原始点击事件
 * @returns {void}
 */
function focusRow(key, event) {
  emit('focus', key, event)
}

/**
 * 功能: 点击搜索命中行 —— 选中它并转为树内定位.
 * @param {string} key 零件索引键
 * @param {MouseEvent} [event] 原始点击事件
 * @returns {Promise<void>}
 */
async function pickSearchHit(key, event) {
  emit('focus', key, event)
  await reveal(key)
}

/**
 * 功能: 三角形数的紧凑显示(搜索行用; 树行由 PartTreeNode 自带).
 * @param {number} n 数量
 * @returns {string} 如 "12.3k"
 */
function compact(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/**
 * 功能: 在树里定位一个零件 —— 展开全部祖先、滚动到行、闪烁提示.
 *
 * 三维点选(WorkbenchView/MaterialsView 的 handlePick)靠它把"点的是哪个"
 * 映射回结构树. 不改选中态 —— 选中由调用方的选择模型负责, 这里只管"让它看得见".
 *
 * @param {string} key 零件索引键
 * @returns {Promise<boolean>} 是否定位成功
 */
async function reveal(key) {
  const info = props.index?.get(key)
  if (!info) return false
  if (filter.value) filter.value = '' // 搜索平铺模式呈现不了层级, 先退回树
  if (activeFilter.value) activeFilter.value = '' // 归属筛选同理
  let changed = false
  // 祖先链沿 parentName(父节点索引键)向上走; 顶层的 parentName 为 null 或
  // 指向被剥壳的包装层, index.get() 取不到时自然终止
  for (let p = props.index.get(info.parentName); p; p = props.index.get(p.parentName)) {
    if (!expanded.value.has(p.key)) {
      expanded.value.add(p.key)
      changed = true
    }
  }
  if (changed) expanded.value = new Set(expanded.value)
  await nextTick()
  // key 含 #N 后缀/中文/括号等, 必须 CSS.escape 才能进选择器
  const el = bodyRef.value?.querySelector(`[data-key="${CSS.escape(key)}"]`)
  if (!el) return false
  el.scrollIntoView({ block: 'center' })
  flashKey.value = key
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    flashKey.value = ''
  }, 1300)
  return true
}

onBeforeUnmount(() => clearTimeout(flashTimer))

defineExpose({ reveal })
</script>

<template>
  <section class="tree">
    <header class="tree__head">
      <span>{{ header }}</span>
      <span class="tree__count">{{ searchHits ? searchHits.length : assemblies.length }}</span>
    </header>

    <input
      v-model="filter"
      class="tree__filter"
      type="search"
      placeholder="搜索名称或中文…"
      aria-label="搜索零件"
    />

    <div v-if="filters?.length" class="tree__chips" role="group" aria-label="按归属筛选">
      <button
        type="button"
        class="tree__chip"
        :class="{ 'tree__chip--on': !activeFilter }"
        @click="activeFilter = ''"
      >全部</button>
      <button
        v-for="f in filters"
        :key="f.key"
        type="button"
        class="tree__chip"
        :class="{ 'tree__chip--on': activeFilter === f.key }"
        @click="activeFilter = activeFilter === f.key ? '' : f.key"
      >{{ f.label }}</button>
    </div>

    <div ref="bodyRef" class="tree__body">
      <template v-if="searchHits">
        <button
          v-for="item in searchHits"
          :key="item.key"
          type="button"
          class="tree__row"
          :class="{ 'tree__row--sel': isSelected(item.key), 'tree__row--hid': isHidden(item.key) }"
          :data-key="item.key"
          @click="pickSearchHit(item.key, $event)"
        >
          <span v-if="dotOf(item.key)" class="tree__dot" :style="{ background: dotOf(item.key) }" />
          <span class="tree__name">{{ labelText(item) }}</span>
          <span
            v-if="isHidden(item.key)"
            class="tree__eye"
            role="button"
            tabindex="0"
            title="已隐藏, 点击恢复显示"
            @click.stop="unhideRow(item.key)"
            @keydown.enter.stop="unhideRow(item.key)"
          ><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 10c2.2 3 5 4.5 8 4.5s5.8-1.5 8-4.5" /><path d="M6.2 13.4 4.6 15.8" /><path d="M12 14.5v2.8" /><path d="M17.8 13.4l1.6 2.4" /></svg></span>
          <span class="tree__tri">{{ compact(item.subtreeTriangles) }}</span>
        </button>
        <p v-if="!searchHits.length" class="tree__empty">没有匹配的零件</p>
      </template>

      <template v-else>
        <PartTreeNode
          v-for="asm in assemblies"
          :key="asm.key"
          :item="asm"
          :index="index"
          :depth="0"
          :expanded="expanded"
          :tick="tick"
          :is-selected="isSelected"
          :is-flash="isFlash"
          :is-hidden="isHidden"
          :dot-of="dotOf"
          :label-of="labelText"
          :on-focus="focusRow"
          :on-toggle="toggleExpand"
          :on-unhide="unhideRow"
          :members-of="membersOf"
          :on-member-focus="onMemberFocus"
          :on-member-hover="onMemberHover"
          :member-badge-of="memberBadgeOf"
        />
      </template>
    </div>
  </section>
</template>

<!-- 递归行需要跨子组件生效, 因此用 .three-d-app 前缀收口而不使用 scoped. -->
<style>
.three-d-app .tree {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  overflow: hidden;
}

.three-d-app .tree__head {
  display: flex;
  justify-content: space-between;
  padding: 9px 12px 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-mid);
}

.three-d-app .tree__count {
  color: var(--text-dim);
  font-weight: 400;
}

.three-d-app .tree__filter {
  margin: 0 10px 8px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text-bright);
  font-size: 12px;
}

.three-d-app .tree__filter:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

.three-d-app .tree__body {
  flex: 1;
  overflow-y: auto;
  padding: 0 6px 8px;
}

.three-d-app .tree__row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 3px 6px;
  border: none;
  border-radius: 5px;
  background: none;
  color: var(--text-mid);
  font-size: 11px;
  text-align: left;
  cursor: pointer;
}

.three-d-app .tree__row--top {
  color: var(--text);
  font-size: 12px;
}

.three-d-app .tree__row:hover {
  background: var(--control-hover);
}

.three-d-app .tree__row--sel {
  background: var(--accent-soft);
  color: var(--accent-bright);
}

.three-d-app .tree__row--flash {
  animation: tree-flash 0.65s ease 2;
}

@keyframes tree-flash {
  50% {
    background: var(--accent-border);
  }
}

@media (prefers-reduced-motion: reduce) {
  .tree__row--flash {
    animation: none;
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
}

.three-d-app .tree__caret {
  width: 12px;
  flex: none;
  color: var(--text-dim);
  transition: transform 0.15s ease;
}

.three-d-app .tree__caret--open {
  transform: rotate(90deg);
}

.three-d-app .tree__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex: none;
}

.three-d-app .tree__name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 已隐藏行: 名字压暗 + 行尾闭眼图标(点击恢复显示) */
.three-d-app .tree__row--hid .tree__name {
  opacity: 0.45;
}

.three-d-app .tree__eye {
  flex: none;
  display: inline-flex;
  align-items: center;
  color: var(--text-dim);
}

.three-d-app .tree__eye svg {
  width: 12px;
  height: 12px;
}

.three-d-app .tree__eye:hover,
.three-d-app .tree__eye:focus-visible {
  color: var(--accent-bright);
}

.three-d-app .tree__tri {
  flex: none;
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

.three-d-app .tree__empty {
  margin: 8px 6px;
  color: var(--text-dim);
  font-size: 12px;
  text-align: center;
}

/* 归属筛选 chips(材质台传 filters 才渲染) */
.three-d-app .tree__chips {
  display: flex;
  gap: 4px;
  margin: 0 10px 8px;
  flex-wrap: wrap;
}

.three-d-app .tree__chip {
  padding: 2px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-dim);
  font-size: 10px;
  cursor: pointer;
}

.three-d-app .tree__chip--on {
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-bright);
}

/* 合并块的虚拟成员行: 比真实节点行更"轻", 名字用中间色 + 斜体徽标 */
.three-d-app .tree__row--member .tree__name {
  color: var(--text-dim);
}

.three-d-app .tree__row--member:hover .tree__name {
  color: var(--text-mid);
}

.three-d-app .tree__memberbadge {
  flex: none;
  padding: 0 3px;
  border: 1px solid var(--accent-border);
  border-radius: 3px;
  color: var(--accent-bright);
  font-size: 9px;
  line-height: 1.4;
}
</style>
