<script setup>
// POU 双区编辑器: 声明 (VAR) + 实现 (ST), 各用一个 CodeEditor (v-model 经 store setter 置脏)。
// 深/浅主题跟随全局主题 store (与全站统一, 见 StatusBar 切换开关)。
// 声明/实现之间可拖分栏 (声明区高度 = layout.pouDeclH, 作为编辑器最小高度: 内容更长仍可增长,
// 与全页滚动语义一致); 编辑器内 Ctrl/Cmd+S 直存 (与右栏「保存到工程」同一 plc.save)。
import { usePlcStore } from '../../stores/plc'
import { useThemeStore } from '../../stores/theme'
import { useLayoutStore } from '../../stores/layout'
import CodeEditor from '../CodeEditor.vue'
import Splitter from '../Splitter.vue'

const plc = usePlcStore()
const themeStore = useThemeStore()
const layout = useLayoutStore()

// Mod-s: 只在有未保存改动且不在途时落盘 (save 内部再守 currentPath)
function saveByKey() {
  if (plc.dirty && !plc.saving) plc.save()
}
</script>

<template>
  <div class="pou-editor">
    <div class="pou-head">
      <span class="pou-path">{{ plc.currentPath || '未选择 POU' }}</span>
      <span v-if="plc.dirty" class="dirty">● 未保存</span>
      <span class="key-hint">Ctrl+S 保存</span>
    </div>

    <p v-if="plc.loadingPou" class="empty loading">加载中…</p>
    <p v-else-if="plc.pouError" class="empty err">读取失败: {{ plc.pouError }}</p>
    <template v-else-if="plc.currentPath">
      <div v-if="plc.hasDecl" class="pou-section decl">
        <div class="sec-title">声明 (VAR)</div>
        <CodeEditor :modelValue="plc.decl" @update:modelValue="plc.setDecl" @save="saveByKey" :theme="themeStore.theme" lang="st" :min-height="layout.sizes.pouDeclH + 'px'" :label="'声明 (VAR)'" />
      </div>
      <Splitter v-if="plc.hasDecl && plc.hasImpl" skey="pouDeclH" dir="y" :sign="1" class="pou-split" />
      <div v-if="plc.hasImpl" class="pou-section impl">
        <div class="sec-title">实现 (ST)</div>
        <CodeEditor :modelValue="plc.impl" @update:modelValue="plc.setImpl" @save="saveByKey" :theme="themeStore.theme" lang="st" min-height="46vh" :label="'实现 (ST)'" />
      </div>
    </template>
    <p v-else class="empty">从左侧「PLC 程序」选择一个 POU 开始编辑</p>
  </div>
</template>

<style scoped>
.pou-editor { display: flex; flex-direction: column; gap: 8px; }
.pou-head { display: flex; gap: 10px; align-items: center; }
.pou-path { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--subtle); }
.dirty { color: var(--warn); font-size: var(--fs-12); font-weight: 700; }
.key-hint { margin-left: auto; font-size: var(--fs-11); color: var(--muted); }
.pou-section { display: flex; flex-direction: column; gap: 4px; }
.sec-title { font-size: var(--fs-12); font-weight: 700; color: var(--text); }
/* 分隔条走普通流 (非壳层 grid seam): 给出可命中的高度带 */
.pou-split { position: relative; flex: 0 0 auto; height: 8px; margin: -2px 0; }
/* .empty 交还全局 (flex 居中 + min-height 120px): 加载/空态占位一致, 消 CLS; err 只叠色 */
.empty.err { color: var(--bad); font-family: var(--font-mono); }
</style>
