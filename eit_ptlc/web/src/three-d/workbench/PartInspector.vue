<script setup>
/**
 * 功能: 选中零件的详情卡 + 标记操作按钮.
 *
 * 这是"授权"发生的地方: 看清楚这是什么零件、多大、多少面, 然后决定删/留/减面.
 */
import { computed } from 'vue'

import { REGION_SPLIT_SUFFIX } from './pruneEval.js'
import { MARKS, MARK_STYLES } from './selectionModel.js'

const props = defineProps({
  /** 单选时的零件信息; 多选或未选时为 null */
  part: { type: Object, default: null },
  /** 当前选中的数量 */
  count: { type: Number, default: 0 },
  /** 选择模型 */
  model: { type: Object, required: true },
  /** 版本号 */
  tick: { type: Number, default: 0 },
})

const emit = defineEmits(['mark', 'undo'])

const currentMark = computed(() => {
  props.tick
  return props.part ? props.model.markOf(props.part.key)?.mark : null
})

/**
 * 管线在 raw 阶段按 region_delete 的区域框分离出来的"注定被删"几何(见
 * blender_clean.region_split). 它不是图纸里的零件, 名字也不是真实节点名 ——
 * 标记它只会往 explicit_delete 里塞一条永远命不中的死条目, 所以这里禁掉操作,
 * 改规则请去编辑 prune_list.yaml 的 region_delete 框.
 */
const isRegionSplit = computed(() =>
  Boolean(props.part && String(props.part.name || '').includes(REGION_SPLIT_SUFFIX)),
)

/** 标记按钮定义 */
const BUTTONS = [
  { mark: MARKS.DELETE, label: '删除', hint: '写进 explicit_delete，重跑后从模型消失' },
  { mark: MARKS.KEEP, label: '保留', hint: '写进 explicit_keep，优先级高于所有正则删减规则' },
  { mark: MARKS.DECIMATE, label: '减面', hint: '保留外形但降低面数，默认保留 30%' },
  { mark: null, label: '待定', hint: '清除标记，交回给正则规则决定' },
]

/**
 * 功能: 毫米尺寸的紧凑显示.
 * @param {number[]} size 三个方向尺寸
 * @returns {string} 显示文本
 */
function fmtSize(size) {
  if (!size) return '—'
  return size.map((v) => (v >= 100 ? v.toFixed(0) : v.toFixed(1))).join(' × ') + ' mm'
}
</script>

<template>
  <section class="ins">
    <header class="ins__head">
      <span>选中零件</span>
      <span v-if="count > 1" class="ins__multi">{{ count }} 个</span>
    </header>

    <div v-if="part" class="ins__body">
      <div class="ins__name">{{ part.chinese || part.name }}</div>
      <div v-if="part.chinese" class="ins__slug">{{ part.name }}</div>

      <dl class="ins__fields">
        <div><dt>三角形</dt><dd>{{ part.subtreeTriangles.toLocaleString('zh-CN') }}</dd></div>
        <div><dt>网格数</dt><dd>{{ part.subtreeMeshes }}</dd></div>
        <div v-if="part.childNames.length">
          <dt>子零件</dt><dd>{{ part.childNames.length }}（删除会连带）</dd>
        </div>
        <div><dt>尺寸</dt><dd>{{ fmtSize(part.sizeMm) }}</dd></div>
        <div><dt>层级</dt><dd>第 {{ part.depth + 1 }} 层</dd></div>
        <div v-if="part.isVendorAuto">
          <dt>来源</dt><dd class="ins__vendor">供应商无名件</dd>
        </div>
      </dl>

      <div v-if="isRegionSplit" class="ins__region">
        这段几何由 <code>prune_list.yaml</code> 的 <code>region_delete</code> 区域框切除，<br />
        不是图纸里的零件，标不了。要改请编辑那条规则的 <code>boxes_mm</code>。
      </div>

      <div v-else-if="currentMark" class="ins__current">
        当前标记：
        <span :style="{ color: MARK_STYLES[currentMark].color }">
          {{ MARK_STYLES[currentMark].label }}
        </span>
      </div>
    </div>

    <p v-else-if="count > 1" class="ins__hint">
      已选中 {{ count }} 个零件，下面的标记会一次性应用到全部。
    </p>
    <p v-else class="ins__hint">在三维里点击零件，或用下方规则批选。<br />Ctrl/Shift + 点击可加选。</p>

    <div class="ins__actions">
      <button
        v-for="btn in BUTTONS"
        :key="btn.label"
        type="button"
        class="ins__btn"
        :class="{ 'ins__btn--active': currentMark === btn.mark }"
        :style="btn.mark ? { '--accent': MARK_STYLES[btn.mark].color } : {}"
        :disabled="!count || isRegionSplit"
        :title="btn.hint"
        @click="emit('mark', btn.mark)"
      >
        {{ btn.label }}
      </button>
    </div>

    <button type="button" class="ins__undo" @click="emit('undo')">撤销上一步</button>
  </section>
</template>

<style scoped>
.ins {
  flex: none;
  border-radius: 10px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  padding: 9px 12px 10px;
  color: var(--text-bright);
  font-size: 12px;
}

.ins__head {
  display: flex;
  justify-content: space-between;
  font-weight: 600;
  color: var(--text-mid);
  margin-bottom: 8px;
}

.ins__multi {
  color: var(--accent);
}

.ins__name {
  font-size: 13px;
  color: var(--text-bright);
  word-break: break-all;
}

.ins__slug {
  margin-top: 2px;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  color: var(--text-dim);
  word-break: break-all;
}

.ins__fields {
  margin: 8px 0 0;
  display: grid;
  gap: 3px;
}

.ins__fields > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.ins__fields dt {
  color: var(--text-dim);
}

.ins__fields dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
  text-align: right;
  word-break: break-all;
}

.ins__vendor {
  color: var(--warn);
}

.ins__current {
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
}

.ins__region {
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px solid var(--border);
  color: var(--text-dim);
  line-height: 1.6;
}

.ins__region code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  color: var(--text);
}

.ins__hint {
  margin: 0;
  color: var(--text-dim);
  line-height: 1.7;
}

.ins__actions {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.ins__btn {
  padding: 5px 0;
  border-radius: 5px;
  border: 1px solid var(--border-strong);
  background: var(--control);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}

.ins__btn:hover:not(:disabled) {
  border-color: var(--accent-border);
  color: var(--accent, var(--text));
}

.ins__btn--active {
  background: color-mix(in srgb, var(--accent, var(--accent)) 18%, transparent);
  border-color: var(--accent, var(--accent));
  color: var(--accent, var(--accent-bright));
}

.ins__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ins__undo {
  margin-top: 5px;
  width: 100%;
  padding: 4px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: none;
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
}

.ins__undo:hover {
  background: var(--control-hover);
  color: var(--text);
}
</style>
