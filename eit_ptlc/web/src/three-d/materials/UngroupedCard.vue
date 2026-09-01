<script setup>
/**
 * 功能: 未入组零件清单 —— 回答"还有哪些零件没归任何材质组", 供批量整理.
 *
 * 两类零件分开列(语义与可用操作都不同):
 *   合并散件 —— 融在 STATIC 块里的零件(无组/无单件覆盖). 可批量入组/批量拆出,
 *              悬浮亮出该零件全部实例的包围盒线框(几何已融合, 无法描边高亮);
 *   独立散件 —— 可寻址的叶子零件(无组). 已经独立, 拆出无意义(该操作禁用),
 *              点击行即树内定位选中, 直接可调.
 *
 * 行按**实例族**列(`侧门-1`/`侧门-2` 合成一行 `侧门 ×2`), 操作整族生效 ——
 * 按实例列会让人只处理其中一个, 另一半仍留在块里.
 */
import { computed, ref, watch } from 'vue'

const props = defineProps({
  /** ungroupedView 产物: {merged: [...], solo: [...]} */
  data: { type: Object, default: () => ({ merged: [], solo: [] }) },
  /** 现有材质组名(批量入组下拉) */
  groupNames: { type: Array, default: () => [] },
  /** 宿主版本号(非响应式模型的重渲染依据) */
  tick: { type: Number, default: 0 },
})

const emit = defineEmits(['batch-isolate', 'batch-group', 'hover', 'focus'])

/** 展开/收起(默认收起 —— 千件清单不该常驻占屏) */
const open = ref(false)
/** 当前类别页: merged | solo */
const tab = ref('merged')
const filter = ref('')
/** 多选集合(零件名) */
const checked = ref(new Set())
/** 平铺上限: 清单是整理入口不是浏览器, 超出请用搜索收窄 */
const CAP = 300

const rows = computed(() => {
  void props.tick
  const source = tab.value === 'merged' ? props.data.merged : props.data.solo
  const term = filter.value.trim().toLowerCase()
  const list = term
    ? (source || []).filter((row) => row.name.toLowerCase().includes(term))
    : source || []
  return { list: list.slice(0, CAP), total: list.length }
})

watch([tab, () => props.data], () => {
  checked.value = new Set()
})

function toggle(name) {
  const next = new Set(checked.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  checked.value = next
}

function toggleAll() {
  checked.value =
    checked.value.size === rows.value.list.length
      ? new Set()
      : new Set(rows.value.list.map((row) => row.name))
}

/** 批量动作传每族首个实例名, 宿主按实例族展开到全部实例 */
function checkedFirstNames() {
  return rows.value.list
    .filter((row) => checked.value.has(row.name))
    .map((row) => row.firstName || row.name)
}

function batchIsolate() {
  if (checked.value.size) emit('batch-isolate', checkedFirstNames())
  checked.value = new Set()
}

function batchGroup(group) {
  if (group && checked.value.size) emit('batch-group', checkedFirstNames(), group)
  checked.value = new Set()
}

function onRowEnter(row) {
  if (tab.value === 'merged') emit('hover', row.member)
}

function onRowClick(row) {
  if (tab.value === 'solo') emit('focus', row.key)
}

function compact(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
</script>

<template>
  <section class="ug" @mouseleave="emit('hover', null)">
    <header class="ug__head">
      <button type="button" class="ug__toggle" @click="open = !open">
        <span class="ug__caret" :class="{ 'ug__caret--open': open }">▸</span>
        未入组零件
      </button>
      <span class="ug__badge">合并 {{ data.merged.length }} · 独立 {{ data.solo.length }}</span>
    </header>

    <template v-if="open">
      <div class="ug__tabs">
        <button
          type="button"
          class="ug__tab"
          :class="{ 'ug__tab--on': tab === 'merged' }"
          @click="tab = 'merged'"
        >合并散件 {{ data.merged.length }}</button>
        <button
          type="button"
          class="ug__tab"
          :class="{ 'ug__tab--on': tab === 'solo' }"
          @click="tab = 'solo'"
        >独立散件 {{ data.solo.length }}</button>
      </div>

      <input v-model="filter" class="ug__search" type="search" placeholder="过滤…" />

      <div v-if="checked.size" class="ug__batch">
        <span>已选 {{ checked.size }} 件</span>
        <button
          v-if="tab === 'merged'"
          class="ug__mini"
          title="批量标记拆出(保存并重跑后各自独立; 每件约 +1 绘制调用)"
          @click="batchIsolate"
        >批量拆出</button>
        <select
          v-if="groupNames.length"
          class="ug__select"
          title="批量加入材质组"
          @change="batchGroup($event.target.value); $event.target.value = ''"
        >
          <option value="">批量入组…</option>
          <option v-for="g in groupNames" :key="g" :value="g">{{ g }}</option>
        </select>
      </div>
      <p v-if="checked.size > 20 && tab === 'merged'" class="ug__warn">
        批量拆出 {{ checked.size }} 件将增加约 {{ checked.size }} 个绘制调用（预算上限 500），
        建议改用「入组」把它们合并成一块。
      </p>

      <ul class="ug__list">
        <li class="ug__row ug__row--head">
          <input
            type="checkbox"
            :checked="checked.size && checked.size === rows.list.length"
            title="全选/清空"
            @change="toggleAll"
          />
          <span class="ug__name ug__name--dim">名称</span>
          <span class="ug__tri">△</span>
        </li>
        <li
          v-for="row in rows.list"
          :key="row.name"
          class="ug__row"
          :class="{ 'ug__row--click': tab === 'solo' }"
          :title="tab === 'solo' ? '点击在树中定位' : row.name"
          @mouseenter="onRowEnter(row)"
          @click="onRowClick(row)"
        >
          <input
            type="checkbox"
            :checked="checked.has(row.name)"
            @click.stop
            @change="toggle(row.name)"
          />
          <span class="ug__name">
            <span
              v-if="row.isolated"
              class="ug__tag"
              :class="{ 'ug__tag--part': row.partial }"
              :title="row.partial ? '只有部分实例标了拆出, 点批量拆出补齐' : '已标拆出, 重跑后独立'"
            >{{ row.partial ? '拆半' : '拆' }}</span>
            {{ row.name }}
            <span v-if="row.instances > 1" class="ug__count">×{{ row.instances }}</span>
          </span>
          <span class="ug__tri">{{ row.tris ? compact(row.tris) : '—' }}</span>
        </li>
      </ul>
      <p v-if="rows.total > rows.list.length" class="ug__hint">
        仅显示前 {{ rows.list.length }} / {{ rows.total }} 件，请用搜索收窄。
      </p>
      <p class="ug__hint">
        合并散件悬浮显示位置线框；独立散件点击即树内定位。入组/拆出保存并重跑后生效。
      </p>
    </template>
  </section>
</template>

<style scoped>
.ug {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.ug__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.ug__toggle {
  display: flex;
  gap: 4px;
  align-items: center;
  padding: 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  cursor: pointer;
  background: none;
  border: none;
}

.ug__caret {
  color: var(--text-dim);
  transition: transform 0.15s ease;
}

.ug__caret--open {
  transform: rotate(90deg);
}

.ug__badge {
  font-size: 11px;
  color: var(--text-dim);
}

.ug__tabs {
  display: flex;
  gap: 4px;
}

.ug__tab {
  padding: 2px 8px;
  font-size: 10px;
  color: var(--text-dim);
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 999px;
}

.ug__tab--on {
  color: var(--accent-bright, #9fe5ff);
  background: var(--accent-soft, rgba(54, 209, 255, 0.16));
  border-color: var(--accent-border, rgba(54, 209, 255, 0.45));
}

.ug__search {
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.ug__batch {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 3px 6px;
  font-size: 10px;
  color: var(--text-mid);
  background: var(--accent-soft, rgba(54, 209, 255, 0.12));
  border-radius: 5px;
}

.ug__warn {
  margin: 0;
  padding: 3px 6px;
  font-size: 10px;
  line-height: 1.5;
  color: var(--warn, #d9a441);
  background: var(--warn-soft, rgba(217, 164, 65, 0.12));
  border-radius: 5px;
}

.ug__list {
  max-height: 220px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.ug__row {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 2px 2px;
  font-size: 10px;
}

.ug__row--head {
  position: sticky;
  top: 0;
  background: var(--control);
}

.ug__row--click {
  cursor: pointer;
}

.ug__row--click:hover {
  background: var(--control-hover);
  border-radius: 4px;
}

.ug__name {
  flex: 1;
  overflow: hidden;
  color: var(--text-mid);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ug__name--dim {
  color: var(--text-dim);
}

.ug__tag {
  display: inline-block;
  padding: 0 3px;
  margin-right: 2px;
  font-size: 9px;
  color: var(--accent-bright, #9fe5ff);
  border: 1px solid var(--accent-border, rgba(54, 209, 255, 0.45));
  border-radius: 3px;
}

/* 只标了一部分实例: 警示色, 它就是"拆了一半"的现场 */
.ug__tag--part {
  color: var(--warn, #d9a441);
  border-color: var(--warn, #d9a441);
}

.ug__count {
  color: var(--text-dim);
}

.ug__tri {
  flex: none;
  min-width: 30px;
  color: var(--text-dim);
  text-align: right;
}

.ug__mini {
  flex: none;
  padding: 1px 6px;
  font-size: 10px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.ug__select {
  flex: none;
  max-width: 84px;
  font-size: 10px;
  color: var(--text-mid);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.ug__hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}
</style>
