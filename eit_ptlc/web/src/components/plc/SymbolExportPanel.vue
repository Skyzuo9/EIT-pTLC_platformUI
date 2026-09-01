<script setup>
// 「符号导出 (OPC)」内容体: 列出当前打开 POU/GVL 声明里的变量, 勾选即给其加/删 symbol 导出 pragma,
// 使变量暴露到 OPC UA (上位机据此读取)。改动落盘后需「编译」+「下载到设备」才在真机生效。
// 取代"回 InoProShop 勾符号配置"——后端用 pragma 机制 (复用 POU 写), 与现有符号配置并存。
// 无自带标题/边框: 由左 Dock 的可折叠段头提供, 本组件只渲染内容, 适配 Dock 窄栏。
import { ref, computed } from 'vue'
import { usePlcStore } from '../../stores/plc'

const plc = usePlcStore()
const filter = ref('')

// 按搜索词过滤 (变量名不区分大小写); 空词显示全部
const shown = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) {
    return plc.symbols
  }
  return plc.symbols.filter((s) => s.name.toLowerCase().includes(q))
})
const exportedCount = computed(() => plc.symbols.filter((s) => s.exported).length)

// 在途守卫: 同名符号的 pragma 写(落盘+重读)未返回前忽略再次切换, 防连点连发;
// Set 原地 mutate 不触发响应性, 每次换新 Set 让 :disabled 跟上
const pending = ref(new Set())

async function onToggle(sym) {
  if (pending.value.has(sym.name)) return
  const started = new Set(pending.value)
  started.add(sym.name)
  pending.value = started
  try {
    // 取反当前导出态; 后端增删 pragma 并落盘, store 随后重读声明刷新
    await plc.toggleSymbol(sym.name, !sym.exported)
  } finally {
    const done = new Set(pending.value)
    done.delete(sym.name)
    pending.value = done
  }
}
</script>

<template>
  <div class="sym-dock">
    <p v-if="!plc.connected" class="sym-hint muted">未连接 —— 先在「PLC 程序」点「连接」</p>
    <p v-else-if="!plc.currentPath || !plc.hasDecl" class="sym-hint muted">打开一个 GVL/POU 查看其变量</p>
    <template v-else>
      <p class="sym-hint">
        勾选 = 暴露到 OPC,需「编译」+「下载到设备」生效。
        <span class="muted">({{ exportedCount }}/{{ plc.symbols.length }})</span>
      </p>
      <input v-model="filter" type="search" class="sym-search" placeholder="搜索变量名…"
             aria-label="搜索变量名" />
      <p v-if="plc.symbolsMsg" class="sym-msg">{{ plc.symbolsMsg }}</p>

      <p v-if="plc.symbolsBusy && !plc.symbols.length" class="sym-hint muted">读取中…</p>
      <p v-else-if="!plc.symbols.length" class="sym-hint muted">该对象声明里无变量</p>
      <p v-else-if="!shown.length" class="sym-hint muted">无匹配「{{ filter }}」的变量</p>

      <ul v-else class="sym-list">
        <li v-for="s in shown" :key="s.name" class="sym-row" :class="{ on: s.exported }">
          <label class="sym-label" :title="s.type">
            <input type="checkbox" :checked="s.exported"
                   :disabled="plc.symbolsBusy || plc.dirty || pending.has(s.name)"
                   @change="onToggle(s)" />
            <span class="sym-name">{{ s.name }}</span>
            <span class="sym-type muted">{{ s.type }}</span>
          </label>
        </li>
      </ul>
      <p v-if="plc.dirty" class="sym-hint warn">编辑器有未保存改动 —— 先「保存到工程」再勾选。</p>
    </template>
  </div>
</template>

<style scoped>
.sym-dock { padding: 2px 0 6px; }
.muted { color: var(--muted); }
.sym-hint { font-size: var(--fs-11); color: var(--muted); margin: 2px 0 6px; line-height: 1.4; padding: 0 2px; }
.sym-hint.warn { color: var(--bad); }
.sym-search { width: 100%; box-sizing: border-box; padding: 4px 8px; border: 1px solid var(--border);
  background: var(--surface-2); color: var(--text); border-radius: 4px; font-size: var(--fs-12); }
.sym-msg { font-family: var(--font-mono); font-size: var(--fs-11); margin: 5px 2px 0; color: var(--accent); line-height: 1.4; }
.sym-list { list-style: none; padding: 0; margin: 6px 0 0; max-height: 38vh; overflow: auto; }
.sym-row { padding: 2px 4px; border-radius: 4px; }
.sym-row.on { background: color-mix(in srgb, var(--ok) 12%, transparent); }
.sym-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: var(--fs-12); }
.sym-label input { cursor: pointer; flex: none; }
.sym-name { font-family: var(--font-mono); color: var(--text); overflow-wrap: anywhere; }
.sym-type { margin-left: auto; font-family: var(--font-mono); font-size: var(--fs-11); white-space: nowrap;
  max-width: 42%; overflow: hidden; text-overflow: ellipsis; }
</style>
