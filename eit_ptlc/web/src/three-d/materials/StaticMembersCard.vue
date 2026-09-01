<script setup>
/**
 * 功能: STATIC 合并块的成员管理卡 —— 回答"这个合并块里都有哪些零件", 并对块内
 *       零件做拆出(part_isolate)/入组(part_groups)/覆盖(part_overrides).
 *
 * **按零件(实例族)列, 不按实例列**: `侧门-1`/`侧门-2` 是同一零件的两个装配实例,
 * 用户说"这个门板"指的是零件; 早期按实例列会让人只拆出其中一个, 另一半仍留在
 * 块里(实际踩过). 行上明示 ×N, 操作一律整族生效.
 *
 * 成员清单来自管线 03 的 join.members(经 memberIndex 归一, 含三角形数与包围盒);
 * 悬浮行会 emit hover 让宿主把该族全部实例的包围盒线框一起画出来 —— 块内几何
 * 已融合, 线框是唯一的"指认"手段. 一切改动保存并重跑后生效.
 */
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  /** 合并块的显示名 */
  blockLabel: { type: String, default: '' },
  /** 按族聚合后的行 [{family, members, tris}]; null = 数据源没有(旧产物, 提示重跑) */
  families: { type: Array, default: null },
  /** 块内实例总数(徽标显示) */
  memberCount: { type: Number, default: 0 },
  /** 现有材质组名(入组下拉) */
  groupNames: { type: Array, default: () => [] },
  /** 已标拆出的 base 名集合(判定族的拆出状态) */
  isolatedNames: { type: Object, default: () => new Set() },
  /** 要定位高亮的族名(右键"在成员清单中定位"设置) */
  activeMember: { type: String, default: '' },
  /** 宿主版本号(孤立集合等非响应式数据的重渲染依据) */
  tick: { type: Number, default: 0 },
})

const emit = defineEmits([
  'override',
  'add-to-group',
  'isolate',
  'unisolate',
  'hover',
  'batch-isolate',
  'batch-group',
])

const filter = ref('')
/** 排序: tris(三角形数降序, 大件是调观感的主角) | name */
const sortKey = ref('tris')
/** 多选集合(族名), 供批量入组/批量拆出 */
const checked = ref(new Set())
const listRef = ref(null)

/** 剥 .00N(与宿主 memberIndex.baseName 同规则, 就地实现免引依赖) */
function baseOf(name) {
  return String(name || '').replace(/\.\d{3}$/, '')
}

/**
 * 功能: 族的拆出状态 —— all(整族已标) / part(只标了一部分) / none.
 * @param {object} row 族行
 * @returns {string} 状态
 */
function isoStateOf(row) {
  const marked = row.members.filter((m) => props.isolatedNames.has(baseOf(m.name))).length
  if (!marked) return 'none'
  return marked === row.members.length ? 'all' : 'part'
}

const filtered = computed(() => {
  void props.tick
  const term = filter.value.trim().toLowerCase()
  const list = (props.families || []).filter(
    (row) => !term || row.family.toLowerCase().includes(term),
  )
  return [...list].sort((a, b) =>
    sortKey.value === 'tris' ? b.tris - a.tris : a.family.localeCompare(b.family, 'zh-CN'),
  )
})

/** 块切换时清掉失效的勾选 */
watch(
  () => props.families,
  () => {
    checked.value = new Set()
  },
)

/** 右键"在清单中定位"时滚动到目标行 */
watch(
  () => props.activeMember,
  async (name) => {
    if (!name) return
    await nextTick()
    listRef.value
      ?.querySelector(`[data-family="${CSS.escape(name)}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  },
)

function toggle(family) {
  const next = new Set(checked.value)
  if (next.has(family)) next.delete(family)
  else next.add(family)
  checked.value = next
}

function toggleAll() {
  checked.value =
    checked.value.size === filtered.value.length
      ? new Set()
      : new Set(filtered.value.map((row) => row.family))
}

/** 批量动作传族内首个实例名, 宿主按族展开 */
function firstNames() {
  return filtered.value
    .filter((row) => checked.value.has(row.family))
    .map((row) => row.members[0].name)
}

function batchIsolate() {
  if (checked.value.size) emit('batch-isolate', firstNames())
  checked.value = new Set()
}

function batchGroup(group) {
  if (group && checked.value.size) emit('batch-group', firstNames(), group)
  checked.value = new Set()
}

function compact(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}
</script>

<template>
  <section class="smc" @mouseleave="emit('hover', null)">
    <header class="smc__head">
      <span>合并块成员 · {{ blockLabel }}</span>
      <span v-if="families" class="smc__badge">
        {{ families.length }} 种零件 / {{ memberCount }} 件
      </span>
    </header>

    <p v-if="!families" class="smc__hint">
      当前没有成员清单数据（旧版产物）。重跑一次管线后即可在这里反查该块的全部成员。
    </p>

    <template v-else>
      <div class="smc__bar">
        <input
          v-model="filter"
          class="smc__search"
          type="search"
          placeholder="过滤零件…"
        />
        <button
          class="smc__mini"
          :title="sortKey === 'tris' ? '当前按三角形数降序, 点击改按名称' : '当前按名称, 点击改按三角形数'"
          @click="sortKey = sortKey === 'tris' ? 'name' : 'tris'"
        >{{ sortKey === 'tris' ? '△↓' : '名↓' }}</button>
      </div>

      <div v-if="checked.size" class="smc__batch">
        <span>已选 {{ checked.size }} 种</span>
        <button class="smc__mini" title="批量标记拆出(整族全部实例, 保存并重跑后各自独立)" @click="batchIsolate">
          批量拆出
        </button>
        <select
          v-if="groupNames.length"
          class="smc__select"
          title="批量加入材质组(整族全部实例)"
          @change="batchGroup($event.target.value); $event.target.value = ''"
        >
          <option value="">批量入组…</option>
          <option v-for="g in groupNames" :key="g" :value="g">{{ g }}</option>
        </select>
      </div>

      <ul ref="listRef" class="smc__list">
        <li class="smc__row smc__row--head">
          <input
            type="checkbox"
            :checked="checked.size && checked.size === filtered.length"
            title="全选/清空"
            @change="toggleAll"
          />
          <span class="smc__name smc__name--dim">零件（同名实例已合并计数）</span>
          <span class="smc__tri">△</span>
        </li>
        <li
          v-for="row in filtered"
          :key="row.family"
          class="smc__row"
          :class="{ 'smc__row--active': row.family === activeMember }"
          :data-family="row.family"
          @mouseenter="emit('hover', row.members)"
        >
          <input type="checkbox" :checked="checked.has(row.family)" @change="toggle(row.family)" />
          <span class="smc__name" :title="row.members.map((m) => m.name).join('\n')">
            <span
              v-if="isoStateOf(row) !== 'none'"
              class="smc__tag"
              :class="{ 'smc__tag--part': isoStateOf(row) === 'part' }"
              :title="isoStateOf(row) === 'all' ? '已标拆出, 重跑后独立' : '只有部分实例标了拆出, 点「拆出」补齐'"
            >{{ isoStateOf(row) === 'all' ? '拆' : '拆半' }}</span>
            {{ row.family }}
            <span v-if="row.members.length > 1" class="smc__count">×{{ row.members.length }}</span>
          </span>
          <span class="smc__tri">{{ row.tris ? compact(row.tris) : '—' }}</span>
          <button
            v-if="isoStateOf(row) !== 'all'"
            class="smc__mini"
            :title="`拆出为独立零件(${row.members.length} 个实例一并拆出, 约 +${row.members.length} 绘制调用)`"
            @click="emit('isolate', row.members[0].name)"
          >拆出</button>
          <button
            v-else
            class="smc__mini"
            title="取消拆出标记(整族)"
            @click="emit('unisolate', row.members[0].name)"
          >撤销</button>
          <button
            class="smc__mini"
            title="给该零件写单件覆盖(整族同参数, 保存并重跑后独立成块并转为可实时预览)"
            @click="emit('override', row.members[0].name)"
          >设材质</button>
          <select
            v-if="groupNames.length"
            class="smc__select"
            title="把该零件加入材质组(整族, 保存并重跑后并入组块)"
            @change="$event.target.value && emit('add-to-group', row.members[0].name, $event.target.value); $event.target.value = ''"
          >
            <option value="">入组…</option>
            <option v-for="g in groupNames" :key="g" :value="g">{{ g }}</option>
          </select>
        </li>
      </ul>
      <p class="smc__hint">
        悬浮零件会亮出它全部实例的位置线框；拆出/入组/设材质均整族生效，保存并重跑后落地。
      </p>
    </template>
  </section>
</template>

<style scoped>
.smc {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.smc__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
}

.smc__badge {
  flex: none;
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
}

.smc__bar {
  display: flex;
  gap: 6px;
  align-items: center;
}

.smc__search {
  flex: 1;
  min-width: 0;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.smc__batch {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 3px 6px;
  font-size: 10px;
  color: var(--text-mid);
  background: var(--accent-soft, rgba(54, 209, 255, 0.12));
  border-radius: 5px;
}

.smc__list {
  max-height: 240px;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.smc__row {
  display: flex;
  gap: 5px;
  align-items: center;
  padding: 2px 2px;
  font-size: 10px;
}

.smc__row--head {
  position: sticky;
  top: 0;
  background: var(--control);
}

.smc__row--active {
  background: var(--accent-soft, rgba(54, 209, 255, 0.16));
  border-radius: 4px;
}

.smc__name {
  flex: 1;
  overflow: hidden;
  color: var(--text-mid);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.smc__name--dim {
  color: var(--text-dim);
}

.smc__tag {
  display: inline-block;
  padding: 0 3px;
  margin-right: 2px;
  font-size: 9px;
  color: var(--accent-bright, #9fe5ff);
  border: 1px solid var(--accent-border, rgba(54, 209, 255, 0.45));
  border-radius: 3px;
}

/* 只标了一部分实例: 用警示色, 它就是"拆了一半"的现场 */
.smc__tag--part {
  color: var(--warn, #d9a441);
  border-color: var(--warn, #d9a441);
}

.smc__count {
  color: var(--text-dim);
}

.smc__tri {
  flex: none;
  min-width: 30px;
  color: var(--text-dim);
  text-align: right;
}

.smc__mini {
  flex: none;
  padding: 1px 6px;
  font-size: 10px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.smc__select {
  flex: none;
  max-width: 64px;
  font-size: 10px;
  color: var(--text-mid);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.smc__hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}
</style>
