<script setup>
// 变量定义表: 名称/类型/作用域/IO/默认/注释/可选值 + 增删
import { useId } from 'vue'
import { useEditorStore } from '../../stores/editor'
import { confirmAction } from '../../composables/confirmService.js'
import { enumToText, parseEnumText } from '../../utils/runInputs.js'

const editor = useEditorStore()
const uid = useId()
const TYPES = ['INT', 'FLOAT', 'STRING', 'BOOL', 'POSE', 'LIST', 'DICT']
const SCOPES = ['local', 'global']
const IO = ['var', 'in', 'out', 'const']

// 稳定行 key: 变量对象 -> 自增序号。WeakMap 不写进数据对象 (doc 会整体 PUT 存盘),
// splice 删行后其余行引用不变, 输入焦点/局部态不错位
const _keys = new WeakMap()
let _seq = 0
function keyOf(obj) {
  if (!_keys.has(obj)) _keys.set(obj, ++_seq)
  return _keys.get(obj)
}

function add() {
  if (!editor.doc) return
  if (!editor.doc.vars) editor.doc.vars = []
  editor.doc.vars.push({ name: 'var' + editor.doc.vars.length, scope: 'local', type: 'INT', io: 'var', default: 0, comment: '' })
  editor.markDirty()
}
// 可选值 (有限取值域): 声明后运行前设置面板渲染成下拉而非自由输入框。
// 空文本 = 删掉 enum 字段 —— 后端 schema 不接受空 enum (那既不是"无限制"也不是"有限制")。
function setEnum(v, text) {
  const list = parseEnumText(text, v.type)
  if (list.length) v.enum = list
  else delete v.enum
  editor.markDirty()
}
async function remove(i) {
  const v = editor.doc.vars[i]
  if (!v) return
  if (!(await confirmAction({
    level: 'danger',
    title: '删除变量 ' + (v.name || '(未命名)'),
    message: '被节点引用的变量删除后脚本将失效。',
    confirmText: '删除',
  }))) return
  const idx = editor.doc.vars.indexOf(v)   // 对话期间列表可能变化, 按对象重定位
  if (idx < 0) return
  editor.doc.vars.splice(idx, 1)
  editor.markDirty()
}
</script>

<template>
  <div class="var-editor">
    <div v-for="(v, i) in editor.variables" :key="keyOf(v)" class="var-card">
      <div class="vc-head">
        <input class="vc-name" v-model="v.name" placeholder="变量名" aria-label="变量名" @input="editor.markDirty()" />
        <button class="mini danger" title="删除该变量" :aria-label="'删除变量 ' + (v.name || '')" @click="remove(i)">×</button>
      </div>
      <div class="vc-grid">
        <label :for="`${uid}-${keyOf(v)}-type`">类型</label>
        <select :id="`${uid}-${keyOf(v)}-type`" v-model="v.type" @change="editor.markDirty()"><option v-for="t in TYPES" :key="t">{{ t }}</option></select>
        <label :for="`${uid}-${keyOf(v)}-scope`">作用域</label>
        <select :id="`${uid}-${keyOf(v)}-scope`" v-model="v.scope" @change="editor.markDirty()"><option v-for="s in SCOPES" :key="s">{{ s }}</option></select>
        <label :for="`${uid}-${keyOf(v)}-io`">IO</label>
        <select :id="`${uid}-${keyOf(v)}-io`" v-model="v.io" @change="editor.markDirty()"><option v-for="o in IO" :key="o">{{ o }}</option></select>
        <label :for="`${uid}-${keyOf(v)}-default`">默认值</label>
        <input :id="`${uid}-${keyOf(v)}-default`" :type="v.type === 'INT' || v.type === 'FLOAT' ? 'number' : 'text'"
               :step="v.type === 'FLOAT' ? 'any' : undefined" v-model="v.default" @input="editor.markDirty()" />
        <label :for="`${uid}-${keyOf(v)}-comment`">注释</label>
        <input :id="`${uid}-${keyOf(v)}-comment`" type="text" v-model="v.comment" @input="editor.markDirty()" />
        <!-- 只对 in/const 开放: out/var 是运行期产物, 声明取值域无意义 (后端 schema 也会拒) -->
        <template v-if="v.io === 'in' || v.io === 'const'">
          <label :for="`${uid}-${keyOf(v)}-enum`">可选值</label>
          <textarea :id="`${uid}-${keyOf(v)}-enum`" class="vc-enum" rows="3"
                    :value="enumToText(v.enum)"
                    placeholder="每行一个; 留空=不限制&#10;collector&#10;1 | 1 上样"
                    @change="setEnum(v, $event.target.value)"></textarea>
        </template>
      </div>
    </div>
    <button class="mini" @click="add">+ 变量</button>
    <p class="hint">注: 默认值按类型在后端强转; LIST/DICT 默认建议留空 (取零值).</p>
    <p class="hint">可选值: 每行一项, 可写 <code>值 | 标签</code> 给中文说明。填了它, 运行前设置就渲染成下拉菜单而不是自由输入框; 默认值必须是其中之一。</p>
  </div>
</template>

<style scoped>
.var-card { border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; background: var(--surface-2); }
.vc-head { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.vc-name { flex: 1; min-width: 0; min-height: 30px; padding: 5px 8px; border: 1px solid var(--border); border-radius: 5px; font-weight: 600; }
.vc-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 10px; align-items: center; }
.vc-grid > label { font-size: var(--fs-12); color: var(--subtle); font-weight: 600; white-space: nowrap; }
.vc-grid > select, .vc-grid > input, .vc-grid > textarea { width: 100%; min-width: 0; min-height: 30px; padding: 5px 7px; border: 1px solid var(--border); border-radius: 5px; }
.vc-enum { font-family: var(--font-mono); resize: vertical; }
</style>
