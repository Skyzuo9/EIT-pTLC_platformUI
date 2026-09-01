<script setup>
/**
 * 功能: 材质组面板 —— 工程师在这里定义"哪些零件合并成同一种材质".
 *
 * 纯展示组件: 组的增删改/参数编辑全部 emit 给宿主(MaterialsView), 由宿主驱动
 * GroupModel(数据) + MaterialsScene(预览). 复用 MaterialEditor 编辑组参数.
 */
import { computed, ref } from 'vue'

import MaterialEditor from './MaterialEditor.vue'

const props = defineProps({
  /** 组投影数组: {name, parts: string[], patch, current, baseline, unaddressable: number} */
  groups: { type: Array, default: () => [] },
  /** 当前选中的零件数(决定"新建组/加入组"是否可用) */
  selectionCount: { type: Number, default: 0 },
  /** 当前展开编辑的组名 */
  activeGroup: { type: String, default: '' },
  /** 重算扳机 */
  tick: { type: Number, default: 0 },
})

const emit = defineEmits([
  'create', 'add-selection', 'remove-member', 'remove-group', 'select',
  'change-param', 'reset-params',
])

/** 新建组的名字输入(受控展开) */
const draftOpen = ref(false)
const draftName = ref('')

const active = computed(() => props.groups.find((g) => g.name === props.activeGroup) || null)

/**
 * 功能: 提交新建组.
 * @returns {void}
 */
function submitCreate() {
  const name = draftName.value.trim()
  if (!name) return
  emit('create', name)
  draftName.value = ''
  draftOpen.value = false
}

/**
 * 功能: 供宿主打开新建输入框(右键菜单入口).
 * @returns {void}
 */
function openDraft() {
  draftOpen.value = true
}

defineExpose({ openDraft })
</script>

<template>
  <section class="gp">
    <header class="gp__head">
      <span>材质组(合并规则)</span>
      <span class="gp__badge">{{ groups.length }} 组</span>
    </header>
    <p class="gp__hint">
      组内零件共享一个材质、重跑后合并为同一块；单件覆盖压过组，组压过材质类。
    </p>

    <!-- 多选时的建组/入组操作 -->
    <div v-if="selectionCount > 1" class="gp__ops">
      <template v-if="draftOpen">
        <input
          v-model="draftName"
          class="gp__input"
          type="text"
          placeholder="新组名(如: 面板铝件)"
          @keydown.enter="submitCreate"
        />
        <button class="gp__btn" @click="submitCreate">建组({{ selectionCount }}件)</button>
        <button class="gp__btn gp__btn--ghost" @click="draftOpen = false">×</button>
      </template>
      <template v-else>
        <button class="gp__btn" @click="draftOpen = true">
          选中 {{ selectionCount }} 件 → 新建材质组
        </button>
        <select
          v-if="groups.length"
          class="gp__select"
          @change="$event.target.value && emit('add-selection', $event.target.value); $event.target.value = ''"
        >
          <option value="">加入既有组…</option>
          <option v-for="g in groups" :key="g.name" :value="g.name">{{ g.name }}</option>
        </select>
      </template>
    </div>

    <!-- 组列表 -->
    <ul v-if="groups.length" class="gp__list">
      <li
        v-for="g in groups"
        :key="g.name"
        :class="['gp__item', { 'gp__item--on': g.name === activeGroup }]"
        @click="emit('select', g.name === activeGroup ? '' : g.name)"
      >
        <span class="gp__name">{{ g.name }}</span>
        <span v-if="Object.keys(g.patch).length" class="gp__dot" title="已调参数">●</span>
        <span class="gp__count">{{ g.parts.length }} 件</span>
        <button
          class="gp__mini gp__mini--danger"
          title="解散该组(成员还原为各自材质类)"
          @click.stop="emit('remove-group', g.name)"
        >解散</button>
      </li>
    </ul>

    <!-- 选中组的成员与参数 -->
    <template v-if="active">
      <p v-if="active.unaddressable" class="gp__warn">
        {{ active.unaddressable }} 个成员在合并块内不可实时预览，保存并重跑后生效。
      </p>
      <ul class="gp__members">
        <li v-for="part in active.parts" :key="part" class="gp__member">
          <span class="gp__memberName" :title="part">{{ part }}</span>
          <button
            class="gp__mini"
            title="移出该组"
            @click="emit('remove-member', active.name, part)"
          >移出</button>
        </li>
      </ul>
      <MaterialEditor
        :name="active.name"
        :title="`组 · ${active.name}`"
        :current="active.current"
        :baseline="active.baseline"
        :patch="active.patch"
        @change="(key, value) => emit('change-param', active.name, key, value)"
        @reset="emit('reset-params', active.name)"
      />
    </template>
  </section>
</template>

<style scoped>
.gp {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.gp__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
}

.gp__badge {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
}

.gp__hint,
.gp__warn {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}

.gp__warn {
  color: var(--warn, #d9a441);
}

.gp__ops {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.gp__input {
  flex: 1;
  min-width: 120px;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.gp__btn {
  padding: 4px 10px;
  font-size: 11px;
  color: var(--accent-ink);
  cursor: pointer;
  background: var(--accent);
  border: none;
  border-radius: 5px;
}

.gp__btn--ghost {
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
}

.gp__select {
  padding: 3px 6px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.gp__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.gp__item {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 4px 6px;
  font-size: 11px;
  cursor: pointer;
  border-radius: 5px;
}

.gp__item:hover { background: var(--control-hover); }
.gp__item--on { background: var(--accent-soft); }

.gp__name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gp__dot {
  font-size: 8px;
  color: var(--accent);
}

.gp__count {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.gp__mini {
  flex: none;
  padding: 1px 7px;
  font-size: 10px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.gp__mini--danger:hover {
  color: #fff;
  background: #d95757;
  border-color: #d95757;
}

.gp__members {
  max-height: 150px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.gp__member {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 2px 4px;
  font-size: 10px;
}

.gp__memberName {
  flex: 1;
  overflow: hidden;
  color: var(--text-mid);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
