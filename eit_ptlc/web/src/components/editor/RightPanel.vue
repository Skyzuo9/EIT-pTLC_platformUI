<script setup>
// 右栏: 参数 / 变量 / 动作文档 / 流程注释
import { computed, onMounted, ref } from 'vue'
import ParamEditor from './ParamEditor.vue'
import VariableEditor from './VariableEditor.vue'
import { useEditorStore } from '../../stores/editor'
import { useRovingTabs } from '../../composables/useRovingTabs.js'

const editor = useEditorStore()
const tab = ref('param')
// 页签键盘巡航 (roving tabindex): 组内 ←→ 切换, Tab 一站穿出
const roving = useRovingTabs(['param', 'var', 'doc', 'note'], tab)
const def = computed(() => editor.actionsCache.find((a) => a.name === editor.selectedNode?.action))
onMounted(() => editor.ensureActions())
</script>

<template>
  <div class="right-panel">
    <div class="dock-tabs" role="tablist" aria-label="编辑器右栏页签">
      <button type="button" role="tab" class="dock-tab" id="rp-tab-param" aria-controls="rp-panel-param" :tabindex="roving.tabindex('param')" :class="{ active: tab === 'param' }" :aria-selected="tab === 'param'" @click="tab = 'param'" @keydown="roving.onKeydown">参数</button>
      <button type="button" role="tab" class="dock-tab" id="rp-tab-var" aria-controls="rp-panel-var" :tabindex="roving.tabindex('var')" :class="{ active: tab === 'var' }" :aria-selected="tab === 'var'" @click="tab = 'var'" @keydown="roving.onKeydown">变量</button>
      <button type="button" role="tab" class="dock-tab" id="rp-tab-doc" aria-controls="rp-panel-doc" :tabindex="roving.tabindex('doc')" :class="{ active: tab === 'doc' }" :aria-selected="tab === 'doc'" @click="tab = 'doc'" @keydown="roving.onKeydown">动作文档</button>
      <button type="button" role="tab" class="dock-tab" id="rp-tab-note" aria-controls="rp-panel-note" :tabindex="roving.tabindex('note')" :class="{ active: tab === 'note' }" :aria-selected="tab === 'note'" @click="tab = 'note'" @keydown="roving.onKeydown">流程注释</button>
    </div>
    <div v-show="tab === 'param'" id="rp-panel-param" role="tabpanel" aria-labelledby="rp-tab-param"><ParamEditor /></div>
    <div v-show="tab === 'var'" id="rp-panel-var" role="tabpanel" aria-labelledby="rp-tab-var"><VariableEditor /></div>
    <div v-show="tab === 'doc'" class="doc-panel" id="rp-panel-doc" role="tabpanel" aria-labelledby="rp-tab-doc">
      <div v-if="def">
        <h4>{{ def.label }} <small>{{ def.name }}</small></h4>
        <p class="muted">类别 {{ def.kind }} · 模式 {{ def.modes.join('/') || '不限' }}</p>
        <h4>动作说明</h4>
        <p class="action-desc">{{ def.desc }}</p>
        <div v-if="def.plc_link" class="plc-link">
          <div class="plc-link-title">执行关联</div>
          <p>{{ def.plc_link }}</p>
        </div>
        <h4>参数定义</h4>
        <table class="kv">
          <tbody>
            <tr v-for="p in def.params" :key="p.name">
              <td>{{ p.label }}</td><td>{{ p.type }}{{ p.required ? ' *' : '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="empty">选择一个「动作」节点查看其动作文档</p>
    </div>
    <!-- 流程注释: 整条流程说明; 与所选原子动作的 desc 分开 -->
    <div v-show="tab === 'note'" class="note-panel" id="rp-panel-note" role="tabpanel" aria-labelledby="rp-tab-note">
      <textarea class="note-area" :value="editor.doc?.note || ''" :readonly="editor.readonly"
                aria-label="流程注释"
                placeholder="这条流程是什么 / 需要注意哪些 / 用在哪里 (保存后随流程持久化)"
                @input="editor.setNote($event.target.value)"></textarea>
    </div>
  </div>
</template>

<style scoped>
.action-desc { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; font-size: var(--fs-13); }
.plc-link { margin: 10px 0; padding: 8px 10px; border: 1px solid var(--border); border-left: 3px solid var(--accent);
  border-radius: 6px; background: var(--surface-2); }
.plc-link-title { font-size: var(--fs-12); font-weight: 700; color: var(--subtle); margin-bottom: 4px; }
.plc-link p { margin: 0; font-size: var(--fs-12); line-height: 1.5; overflow-wrap: anywhere; }
.note-panel { height: 100%; display: flex; }
.note-area { flex: 1; width: 100%; min-height: 220px; resize: vertical; padding: 8px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--field-bg); color: var(--text); font-family: var(--font-ui); font-size: var(--fs-13); line-height: 1.6; }
.note-area:read-only { opacity: 0.7; cursor: default; }
</style>
