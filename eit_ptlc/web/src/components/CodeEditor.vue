<script setup>
// 可复用代码编辑器 (CodeMirror 6): YAML / ST 语法高亮 + 行号 + 可编辑 + 深/浅主题热切。
// 浅色 = VS Code Light+; 深色 = VS Code Dark+ (见 cmTheme.js)。
// 语言按 lang 属性选择: 'yaml' (动作 YAML 编辑) 走 yaml()+标量识别; 'st' (PLC 结构化文本) 走 stLanguage。
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { EditorState, Compartment } from '@codemirror/state'
import { EditorView, keymap } from '@codemirror/view'
import { basicSetup } from 'codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { darkExt, lightExt, scalarHighlighter } from './cmTheme'
import { stLanguage } from './stLang'

const props = defineProps({
  modelValue: { type: String, default: '' },
  theme: { type: String, default: 'dark' }, // 'dark' | 'light'
  lang: { type: String, default: 'yaml' }, // 'yaml' | 'st'; 实例生命周期内固定
  minHeight: { type: String, default: '60vh' }, // 最小高度 (CSS 长度); 双区堆叠时由父级调小
  label: { type: String, default: '代码编辑器' }, // 可访问名: 挂到 CodeMirror contentDOM (role=textbox 载体)
})
const emit = defineEmits(['update:modelValue', 'save'])

const host = ref(null)
let view = null
const themeCompartment = new Compartment()

// 主题扩展: 深色 = VS Code Dark+, 浅色 = VS Code Light+ (见 cmTheme.js)
function themeExt(t) {
  return t === 'dark' ? darkExt : lightExt
}

onMounted(() => {
  const updateListener = EditorView.updateListener.of((v) => {
    if (v.docChanged) {
      const text = v.state.doc.toString()
      if (text !== props.modelValue) {
        emit('update:modelValue', text)
      }
    }
  })
  // 语言扩展: ST 用 stLanguage (无 scalarHighlighter, 它是 YAML 语法树专用); 其余走 yaml()
  const langExt = props.lang === 'st' ? [stLanguage] : [yaml(), scalarHighlighter]
  // Mod-s → save 事件 (preventDefault 拦浏览器"保存网页"; 置于 basicSetup 之后优先生效,
  // 是否真正落盘由宿主决定 —— 如 PouEditor 只在 dirty 时调 plc.save)
  const saveKey = keymap.of([{ key: 'Mod-s', preventDefault: true, run: () => { emit('save'); return true } }])
  const state = EditorState.create({
    doc: props.modelValue,
    extensions: [basicSetup, saveKey, ...langExt, themeCompartment.of(themeExt(props.theme)), updateListener],
  })
  view = new EditorView({ state, parent: host.value })
  view.contentDOM.setAttribute('aria-label', props.label)
})

onBeforeUnmount(() => {
  if (view) {
    view.destroy()
    view = null
  }
})

// 外部 modelValue 变化 -> 同步编辑器文档 (比对当前文本防回环)
watch(() => props.modelValue, (val) => {
  if (!view) {
    return
  }
  const cur = view.state.doc.toString()
  if (val !== cur) {
    view.dispatch({ changes: { from: 0, to: cur.length, insert: val } })
  }
})

// 主题热切 (Compartment.reconfigure, 不重建编辑器)
watch(() => props.theme, (t) => {
  if (view) {
    view.dispatch({ effects: themeCompartment.reconfigure(themeExt(t)) })
  }
})
</script>

<template>
  <div ref="host" class="cm-host" :style="{ '--cm-min-h': minHeight }"></div>
</template>

<style scoped>
.cm-host { width: 100%; min-height: var(--cm-min-h, 60vh); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.cm-host :deep(.cm-editor) { height: 100%; min-height: var(--cm-min-h, 60vh); }
.cm-host :deep(.cm-scroller) { font-family: var(--font-mono); font-size: var(--fs-12); }
</style>
