<script setup>
/**
 * 功能: 右侧信息坞的页签条 —— 展开时横向文字页签, 收起时竖向图标条.
 *
 * 纯展示件: 页签清单与当前值由宿主给, 点击只 emit. 收起态仍渲染整条 ——
 * 收起是"坞变窄成图标轨", 不是"坞消失", 否则要另找地方安一个"把坞找回来"的按钮,
 * 而那种孤儿控件正是这次重构要消灭的东西.
 */
defineProps({
  /** 页签清单: [{key, label, icon?, title?}] */
  tabs: { type: Array, default: () => [] },
  /** 当前激活页签 key */
  active: { type: String, default: '' },
  /** 是否收起成图标轨 */
  collapsed: { type: Boolean, default: false },
  /** 坞标题(展开时显示在页签左侧, 如工位名) */
  title: { type: String, default: '' },
})

const emit = defineEmits(['select', 'toggle'])
</script>

<template>
  <header class="dt" :class="{ 'dt--rail': collapsed }">
    <button
      type="button"
      class="dt__collapse"
      :title="collapsed ? '展开信息栏' : '收起信息栏'"
      :aria-expanded="!collapsed"
      @click="emit('toggle')"
    >{{ collapsed ? '◀' : '▶' }}</button>

    <div class="dt__tabs">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        class="dt__tab"
        :class="{ 'dt__tab--on': tab.key === active }"
        :title="tab.title || tab.label"
        :aria-current="tab.key === active ? 'true' : undefined"
        @click="emit('select', tab.key)"
      >
        <span v-if="collapsed" class="dt__icon" aria-hidden="true">{{ tab.icon || tab.label[0] }}</span>
        <span v-else>{{ tab.label }}</span>
      </button>
    </div>

    <span v-if="!collapsed && title" class="dt__title" :title="title">{{ title }}</span>
  </header>
</template>

<style scoped>
.dt {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  user-select: none;
}

/* 收起态: 整条转竖向, 顶到坞顶 */
.dt--rail {
  flex-direction: column;
  gap: 4px;
  padding: 6px 4px;
  border-bottom: none;
}

.dt__tabs {
  display: flex;
  gap: 3px;
  min-width: 0;
}

.dt--rail .dt__tabs {
  flex-direction: column;
}

.dt__tab {
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
  cursor: pointer;
  background: none;
  border: 1px solid transparent;
  border-radius: 6px;
}

.dt--rail .dt__tab {
  padding: 6px 0;
  width: 26px;
  text-align: center;
}

.dt__tab:hover {
  color: var(--text-bright);
  background: var(--control-hover);
}

.dt__tab--on {
  color: var(--accent-bright);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.dt__icon {
  font-size: 13px;
  line-height: 1;
}

.dt__collapse {
  flex: none;
  padding: 4px 6px;
  font-size: 10px;
  color: var(--text-dim);
  cursor: pointer;
  background: none;
  border: 1px solid var(--border);
  border-radius: 5px;
}

.dt__collapse:hover {
  color: var(--text-bright);
  background: var(--control-hover);
}

/* 工位名: 占满剩余宽度并省略, 页签永远不被挤走 */
.dt__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
