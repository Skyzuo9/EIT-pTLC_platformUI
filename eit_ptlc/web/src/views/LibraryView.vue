<script setup>
// 库中区分发: 动作 (原子指令详情/执行) vs 流程 (编排 IDE)
// 少数流程的入参不是"一组标量旋钮"而是一张表 (如多样品上样的样品清单), 通用节点树 IDE
// 填不了 —— 这类流程在 PANELS 里登记一个专用录入面板, 缺省渲染它, 仍可切回节点树编辑。
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ActionDetail from './ActionDetail.vue'
import EditorView from './EditorView.vue'
import SamplingMultiPanel from '../components/SamplingMultiPanel.vue'
import { confirmAction } from '../composables/confirmService.js'
import { useQuerySync } from '../composables/useQuerySync.js'
import { useEditorStore } from '../stores/editor'

const PANELS = {
  sampling_multi_execute: SamplingMultiPanel,
  sampling_multi_cycle: SamplingMultiPanel,
}

const route = useRoute()
const editor = useEditorStore()
const asEditor = ref(false)      // 切到节点树 (改流程本身而非填表)
useQuerySync('editor', asEditor, { parse: (v) => v === '1', serialize: (v) => (v ? '1' : '0'), defaultValue: false })
const panel = computed(() =>
  route.params.kind === 'operation' ? PANELS[route.params.name] || null : null)

// 换流程即回到该流程的缺省视图 (免得从 A 的节点树切过来, B 也被当成要编辑)
watch(() => route.params.name, () => { asEditor.value = false })

// 切回录入面板会卸载 EditorView (路由不变, 其路由守卫管不到), 脏时在此拦;
// 确认放弃后草稿仍留在 store, 直到下次进节点树时 EditorView 重载才真正丢弃
async function backToPanel() {
  if (editor.dirty && !(await confirmAction({
    title: '放弃未保存修改?',
    message: '切回录入面板将丢弃流程编辑。',
    confirmText: '放弃修改',
    cancelText: '继续编辑',
  }))) return
  asEditor.value = false
}
</script>

<template>
  <ActionDetail v-if="route.params.kind === 'action'" />
  <template v-else-if="route.params.kind === 'operation'">
    <div v-if="panel && !asEditor" class="lib-panel">
      <div class="lib-switch">
        <button class="mini" title="改流程本身 (节点树 / 变量 / 调试坞)"
                aria-label="切到节点树: 改流程本身 (节点树 / 变量 / 调试坞)"
                @click="asEditor = true">切到节点树</button>
      </div>
      <component :is="panel" />
    </div>
    <template v-else>
      <div v-if="panel" class="lib-switch">
        <button class="mini" title="回到该流程的专用录入面板"
                aria-label="切回录入面板: 回到该流程的专用录入面板"
                @click="backToPanel">切回录入面板</button>
      </div>
      <EditorView />
    </template>
  </template>
  <div v-else class="empty">从左侧「库」选择动作 (原子指令) 或流程 (可编排), 或新建流程 —— 新建入口在左栏「流程」分组标题旁的「+ 新建」</div>
</template>

<style scoped>
.lib-panel { display: flex; flex-direction: column; min-height: 0; }
.lib-switch { display: flex; justify-content: flex-end; padding: 4px 8px 0; }
</style>
