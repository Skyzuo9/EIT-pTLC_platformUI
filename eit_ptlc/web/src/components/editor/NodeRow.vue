<script>
// 稳定行 key: 节点对象 -> 自增序号。WeakMap 不写进节点对象 (doc 会整体 PUT 存盘),
// 上移/下移/删除只 splice 引用, key 不漂移; NodeTable 根层 v-for 复用同一份 (具名导出)。
const _keys = new WeakMap()
let _seq = 0
export function keyOf(obj) {
  if (!_keys.has(obj)) _keys.set(obj, ++_seq)
  return _keys.get(obj)
}
</script>

<script setup>
// 递归节点行: 一行 (# / Action / Input / Output) + 控制流子块分隔与缩进子行
import { computed } from 'vue'
import { useEditorStore } from '../../stores/editor'
import { useDebugStore } from '../../stores/debug'
import { childAid, controlBlocks, isControl, nodeAction, nodeInput, nodeOutput } from '../../utils/script'
import { pressable } from '../../utils/a11y.js'

const props = defineProps({ node: Object, aid: String, depth: { default: 0 } })
const editor = useEditorStore()
const debug = useDebugStore()

function select() { editor.selectNode(props.aid) }

const blocks = computed(() => controlBlocks(props.node))
const isSel = computed(() => editor.selectedAid === props.aid)
// 活动调用链中的父 run_script 与当前叶子同时高亮；script+aid 成对，避免父子帧同号 AID 误亮。
// 单步/断点/HITL 尚未发出 node_enter 时，由 debug store 的停驻位置兜底。
const isCur = computed(() => debug.isNodeHighlighted(editor.current.name, props.aid))
const isBp = computed(() => debug.breakpoints.includes(props.aid))
const tail = computed(() => props.aid.split('/').slice(-1)[0])
function indent(d) { return { paddingLeft: 8 + d * 16 + 'px' } }
</script>

<template>
  <div class="node-row" :class="{ active: isSel, current: isCur, comment: node.op === 'comment' }"
       v-bind="pressable(select)" :aria-selected="isSel">
    <!-- 断点格是行内真按钮: keydown.stop 挡住冒泡, 否则行级 pressable 会 preventDefault 吞掉按钮的 Enter/Space 原生激活 -->
    <button type="button" class="c-idx btn-bare" title="点击切换断点" :aria-pressed="isBp"
            :aria-label="'切换断点 行' + tail" @click.stop="debug.toggleBreakpoint(aid)" @keydown.stop>
      <span v-if="isBp" class="bp" />{{ tail }}
    </button>
    <div class="c-act" :style="indent(depth)">{{ nodeAction(node, editor.actionsCache, editor.operations) }}</div>
    <div class="c-in">{{ nodeInput(node) }}</div>
    <div class="c-out">{{ nodeOutput(node) }}</div>
  </div>
  <template v-if="isControl(node)">
    <template v-for="b in blocks" :key="b.block">
      <div class="block-sep" :style="indent(depth + 1)">{{ b.label }}</div>
      <NodeRow v-for="(child, i) in b.nodes" :key="keyOf(child)"
               :node="child" :aid="childAid(aid, b.block, i)" :depth="depth + 2" />
    </template>
  </template>
</template>

<style scoped>
/* 断点格 div→button 后不再命中全局 .node-row > div 的内边距, 就地补齐 */
.node-row > .c-idx { padding: 5px 6px; }
</style>
