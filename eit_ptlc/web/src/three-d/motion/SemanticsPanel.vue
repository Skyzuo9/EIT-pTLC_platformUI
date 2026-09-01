<script setup>
/**
 * 功能: 运动语义列表 —— 按 kind 分组展示"哪些会动/哪些是耗材/哪些待装配",
 *       色点与三维着色同源(SEMANTIC_COLORS), 行点击选中并高亮对应几何.
 */
import { computed } from 'vue'

import { CATEGORY_LABELS, KIND_GROUPS, SEMANTIC_COLORS } from './motionSemantics.js'

const props = defineProps({
  /** classifySemantics 产物 */
  entries: { type: Array, default: () => [] },
  /** 当前选中的条目 id */
  activeId: { type: String, default: '' },
})

const emit = defineEmits(['select'])

/** 按 kind 分组(空组不显示); "数据侧机构"默认收进 <details> 折叠 */
const groups = computed(() =>
  KIND_GROUPS.map((group) => ({
    ...group,
    items: props.entries.filter((entry) => entry.kind === group.kind),
  })).filter((group) => group.items.length),
)

/**
 * 功能: 条目色点颜色.
 * @param {object} entry 条目
 * @returns {string} CSS 颜色
 */
function dotOf(entry) {
  return SEMANTIC_COLORS[entry.category] || SEMANTIC_COLORS.static
}
</script>

<template>
  <div class="sp">
    <div class="sp__legend">
      <span
        v-for="cat in ['movable', 'consumable', 'static', 'declared-only']"
        :key="cat"
        class="sp__legendItem"
      >
        <span class="sp__dot" :style="{ background: SEMANTIC_COLORS[cat] }" />
        {{ CATEGORY_LABELS[cat] }}
      </span>
    </div>

    <template v-for="group in groups" :key="group.kind">
      <details :open="group.kind !== 'mechanism'" class="sp__group">
        <summary class="sp__groupHead">
          {{ group.label }}<span class="sp__count">{{ group.items.length }}</span>
        </summary>
        <ul class="sp__list">
          <li
            v-for="entry in group.items"
            :key="entry.id"
            :class="['sp__row', { 'sp__row--on': entry.id === activeId }]"
            :title="entry.resolveFailed
              ? 'manifest 声明 rigged 但模型中未解析到节点 —— 检查节点名/重跑管线'
              : entry.category === 'declared-only' ? '数据侧已声明, 几何未绑定 —— 待装配' : entry.label"
            @click="emit('select', entry)"
          >
            <span class="sp__dot" :style="{ background: dotOf(entry) }" />
            <span class="sp__label">{{ entry.label }}</span>
            <span
              v-if="entry.category === 'declared-only'"
              :class="['sp__badge', { 'sp__badge--err': entry.resolveFailed }]"
            >{{ entry.resolveFailed ? '解析失败' : '待装配' }}</span>
          </li>
        </ul>
      </details>
    </template>
  </div>
</template>

<style scoped>
.sp {
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow-y: auto;
}

.sp__legend {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 0 6px;
  font-size: 10px;
  color: var(--text-dim);
  border-bottom: 1px solid var(--hair);
}

.sp__legendItem {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.sp__group {
  margin: 0;
}

.sp__groupHead {
  padding: 4px 2px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  cursor: pointer;
  user-select: none;
}

.sp__count {
  margin-left: 6px;
  font-size: 10px;
  font-weight: 400;
  color: var(--text-dim);
}

.sp__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.sp__row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  font-size: 11px;
  border-radius: 4px;
  cursor: pointer;
}

.sp__row:hover { background: var(--control); }
.sp__row--on { background: var(--accent-soft); }

.sp__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border: 1px solid var(--hair);
  border-radius: 50%;
}

.sp__label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sp__badge {
  flex: none;
  margin-left: auto;
  padding: 0 5px;
  font-size: 9px;
  color: var(--text-dim);
  background: var(--control);
  border-radius: 7px;
}

.sp__badge--err {
  color: #fff;
  background: #d95757;
}
</style>
