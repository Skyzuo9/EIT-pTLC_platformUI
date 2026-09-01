<script setup>
/**
 * 功能: 层级树的递归行 —— 渲染一行零件, 展开时递归渲染全部子件.
 *
 * 早期版本把树模板手写死在三层, 结果第四层往下的零件(紧固件、拖链节的具体实例)
 * 在树里根本点不到, 三维点选也没法定位过去. 递归组件让任意深度可达, 且保持惰性:
 * 只有展开的节点才会去查子件.
 *
 * 交互回调用函数 props(isSelected/dotOf/labelOf/onFocus/onToggle)而不是 emit:
 * 递归组件里事件要一层层冒泡回壳组件, 深度一深全是转发噪音; 函数引用穿透任意深度.
 */
const props = defineProps({
  /** 零件信息(PartIndex 的 info 对象) */
  item: { type: Object, required: true },
  /** 零件索引 */
  index: { type: Object, required: true },
  /** 层级深度, 决定缩进 */
  depth: { type: Number, default: 0 },
  /** 已展开键集合(由壳组件 PartTree 持有并整体替换以触发更新) */
  expanded: { type: Object, required: true },
  /** 版本号, 变化时强制本行重渲染(选中/标记态都从函数 props 现取) */
  tick: { type: Number, default: 0 },
  /** 行是否选中 */
  isSelected: { type: Function, required: true },
  /** 行是否处于定位闪烁态 */
  isFlash: { type: Function, required: true },
  /** 行是否被手动隐藏(整棵子树); 命中的行显示闭眼图标 */
  isHidden: { type: Function, default: () => false },
  /** 行色点颜色; 返回 null 则不渲染色点 */
  dotOf: { type: Function, required: true },
  /** 行显示名 */
  labelOf: { type: Function, required: true },
  /** 行点击回调 */
  onFocus: { type: Function, required: true },
  /** 展开切换回调 */
  onToggle: { type: Function, required: true },
  /** 闭眼图标点击回调(恢复显示); 不传则图标纯展示 */
  onUnhide: { type: Function, default: null },
  /**
   * 合并块的虚拟成员行(材质台专用, 装配台不传即零变化):
   * membersOf(item) 返回成员数组则该行可展开出成员; 成员行点击/悬浮走
   * onMemberFocus / onMemberHover; memberBadgeOf 返回行首徽标文本(如"拆").
   */
  membersOf: { type: Function, default: null },
  onMemberFocus: { type: Function, default: null },
  onMemberHover: { type: Function, default: null },
  memberBadgeOf: { type: Function, default: null },
})

/**
 * 功能: 三角形数的紧凑显示.
 * @param {number} n 数量
 * @returns {string} 如 "12.3k"
 */
function compact(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/**
 * 功能: 取该行的虚拟成员清单(仅材质台的 STATIC 块有).
 * @returns {Array} 成员数组
 */
function memberRows() {
  return (props.membersOf && props.membersOf(props.item)) || []
}
</script>

<template>
  <button
    type="button"
    class="tree__row"
    :class="{
      'tree__row--top': depth === 0,
      'tree__row--sel': isSelected(item.key),
      'tree__row--flash': isFlash(item.key),
      'tree__row--hid': isHidden(item.key),
    }"
    :style="{ paddingLeft: `${6 + depth * 14}px` }"
    :data-key="item.key"
    @click="onFocus(item.key, $event)"
  >
    <span
      v-if="item.childNames.length || memberRows().length"
      class="tree__caret"
      :class="{ 'tree__caret--open': expanded.has(item.key) }"
      role="button"
      tabindex="0"
      :aria-label="expanded.has(item.key) ? '折叠' : '展开'"
      @click.stop="onToggle(item.key)"
      @keydown.enter.stop="onToggle(item.key)"
    >▸</span>
    <span v-else class="tree__caret">·</span>
    <span
      v-if="dotOf(item.key)"
      class="tree__dot"
      :style="{ background: dotOf(item.key) }"
    />
    <span class="tree__name">{{ labelOf(item) }}</span>
    <span
      v-if="isHidden(item.key)"
      class="tree__eye"
      role="button"
      tabindex="0"
      title="已隐藏, 点击恢复显示"
      @click.stop="onUnhide && onUnhide(item.key)"
      @keydown.enter.stop="onUnhide && onUnhide(item.key)"
    ><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 10c2.2 3 5 4.5 8 4.5s5.8-1.5 8-4.5" /><path d="M6.2 13.4 4.6 15.8" /><path d="M12 14.5v2.8" /><path d="M17.8 13.4l1.6 2.4" /></svg></span>
    <span class="tree__tri">{{ compact(item.subtreeTriangles) }}</span>
  </button>

  <template v-if="expanded.has(item.key) && item.childNames.length">
    <PartTreeNode
      v-for="child in index.childrenOf(item.key)"
      :key="child.key"
      :item="child"
      :index="index"
      :depth="depth + 1"
      :expanded="expanded"
      :tick="tick"
      :is-selected="isSelected"
      :is-flash="isFlash"
      :is-hidden="isHidden"
      :dot-of="dotOf"
      :label-of="labelOf"
      :on-focus="onFocus"
      :on-toggle="onToggle"
      :on-unhide="onUnhide"
      :members-of="membersOf"
      :on-member-focus="onMemberFocus"
      :on-member-hover="onMemberHover"
      :member-badge-of="memberBadgeOf"
    />
  </template>

  <!-- 合并块的虚拟成员行: 几何已融合, 行不是真实节点; 点击=成员级选中,
       悬浮=包围盒线框指认(宿主实现) -->
  <template v-if="expanded.has(item.key) && memberRows().length">
    <button
      v-for="m in memberRows()"
      :key="m.name"
      type="button"
      class="tree__row tree__row--member"
      :style="{ paddingLeft: `${6 + (depth + 1) * 14}px` }"
      :title="m.name"
      @click="onMemberFocus && onMemberFocus(item.key, m, $event)"
      @mouseenter="onMemberHover && onMemberHover(item.key, m)"
      @mouseleave="onMemberHover && onMemberHover(item.key, null)"
    >
      <span class="tree__caret">·</span>
      <span
        v-if="memberBadgeOf && memberBadgeOf(m)"
        class="tree__memberbadge"
      >{{ memberBadgeOf(m) }}</span>
      <span class="tree__name tree__name--member">{{ m.name }}</span>
      <span class="tree__tri">{{ m.tris ? compact(m.tris) : '—' }}</span>
    </button>
  </template>
</template>
