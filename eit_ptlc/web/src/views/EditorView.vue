<script setup>
// 编排 IDE 中区: 工具栏 / (节点表 + 右栏) / 调试坞 (HITL 弹窗已全局化, 挂 App.vue)
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import EditorToolbar from '../components/editor/EditorToolbar.vue'
import NodeTable from '../components/editor/NodeTable.vue'
import RightPanel from '../components/editor/RightPanel.vue'
import DebugDock from '../components/editor/DebugDock.vue'
import Splitter from '../components/Splitter.vue'
import { errText } from '../api'
import { useDirtyGuard } from '../composables/useDirtyGuard.js'
import { useEditorStore } from '../stores/editor'
import { useLayoutStore } from '../stores/layout'

const route = useRoute()
const editor = useEditorStore()
const layout = useLayoutStore()

const loading = ref(false)
const loadError = ref('')

// 未保存守卫 (dirty 真源在 store): 换 :name 流程 / 离开 / 刷新三口全拦
useDirtyGuard(() => editor.dirty, { message: '当前流程有未保存修改, 离开将丢弃。', paramKey: 'name' })

async function load(name) {
  // 切换被编辑/浏览的流程 = 只读导航: 只加载脚本, 绝不软停后端 run、也不清"当前运行"监视器。
  // 运行是全局的, 与"在看哪个流程"解耦; 若浏览到的流程不是在跑的那个, 由调试坞按归属禁用起跑,
  // 避免"运行"误续别处的 run (见 DebugDock / utils/runControl.js)。
  if (!name) return
  loading.value = true
  loadError.value = ''
  try {
    await editor.loadScript(name)
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}
watch(() => route.params.name, load)
onMounted(() => {
  // 流程摘要 (run_script 节点据此显示脚本中文名); 正常已由左 Dock 加载, 此处兜底
  // (兜底失败只影响子脚本中文名显示, 静默即可, 不能拖垮主体加载)
  if (!editor.operations.length) editor.loadRepo().catch(() => {})
  load(route.params.name)
})
</script>

<template>
  <div v-if="!route.params.name" class="empty">从左侧「库 &gt; 流程」选择或新建一个流程脚本</div>
  <div v-else-if="loading" class="empty loading">载入流程…</div>
  <div v-else-if="loadError" class="empty">
    <span>加载失败: {{ loadError }}</span>
    <button class="btn ghost" @click="load(route.params.name)">重试</button>
  </div>
  <div v-else class="editor">
    <EditorToolbar />
    <div class="editor-mid" :style="{ '--editor-right-w': layout.sizes.editorRightW + 'px' }">
      <NodeTable />
      <RightPanel />
      <!-- 节点表↔右栏 竖向 (右栏在右 → sign=-1) -->
      <Splitter skey="editorRightW" dir="x" :sign="-1" class="seam-editor-v" />
    </div>
    <!-- 调试坞 = 薄按钮条 (自适应高度); 运行结果统一看底部「当前运行」 -->
    <DebugDock />
  </div>
</template>

<style scoped>
/* 全局 .empty 是居中 flex 无 gap, 错误态"文案+重试"两个子元素需要间距 */
.empty { gap: 8px; }
</style>
