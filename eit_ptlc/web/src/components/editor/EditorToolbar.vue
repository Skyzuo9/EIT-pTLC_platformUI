<script setup>
// 编辑器工具栏: 插入 (调用/脚本/赋值/控制流) + 子节点开关 + 移动/剪贴板/删除 + 保存
import { computed, ref } from 'vue'
import { useEditorStore } from '../../stores/editor'
import { useDebugStore } from '../../stores/debug'
import { confirmAction } from '../../composables/confirmService.js'

const editor = useEditorStore()
const debug = useDebugStore()
const asChild = ref(false)

// 插入按钮: [op, 标准英文名, 中文悬停提示]. 基础 3 键 + 控制流 8 键
const BASIC = [
  ['call', 'Action', '调用一个原子动作 (设备/PLC/机器人指令), 可传参数并把结果赋给变量'],
  ['run_script', 'Script', '运行另一个子流程脚本, 支持输入/输出变量映射'],
  ['assign', 'Assign', '计算表达式并把结果写入一个变量'],
]
const CONTROL = [
  ['if', 'If', '条件分支: 条件成立走 then, 可加 elif / else'],
  ['for', 'For', '计数循环: 按数值区间或遍历集合重复执行循环体'],
  ['while', 'While', '前判断循环: 当条件为真时反复执行循环体'],
  ['repeat', 'Repeat', '后判断循环: 先执行一次循环体, 直到条件为真才停止'],
  ['try', 'Try', '异常捕获: try 体出错转入 catch, finally 总会执行'],
  ['parallel', 'Parallel', '并行执行多个分支 (join=all 全部完成 / any 任一完成)'],
  ['with_resources', 'Resources', '区间持有共享设备资源 (如大真空泵): 进入取得, 退出释放; 由资源门按引用计数开关设备, 并发流程不会互相掐断'],
  ['raise', 'Raise', '主动抛出一个异常 (错误名+消息), 可被 try 捕获'],
  ['comment', 'Comment', '注释节点, 仅用于说明, 运行时不执行任何动作'],
]

// 调试运行中锁定结构编辑 (避免 AID 与运行期失配)
const locked = computed(() =>
  editor.readonly || !['idle', 'DONE', 'ERROR', 'KILLED', ''].includes(debug.status))

// 当前流程身份: label + 组/文件名, hover 显完整路径 (path 取自列表摘要; doc 本体不携带 path,
// 因为 doc 会整体 PUT 回后端落盘). 列表未加载到时降级为裸文件名。
const ident = computed(() => {
  const name = editor.current.name
  if (!name) return null
  const sum = editor.operations.find((o) => o.name === name)
  return {
    label: (editor.doc && editor.doc.label) || (sum && sum.label) || name,
    file: `${sum && sum.group ? sum.group + '/' : ''}${name}.yaml`,
    path: (sum && sum.path) || '',
  }
})

function insert(op) { editor.insertNode(op, asChild.value) }

async function removeSelected() {
  if (!(await confirmAction({
    level: 'danger',
    title: '删除选中节点',
    message: '控制流节点将连同整棵子树一起删除, 无撤销。',
    confirmText: '删除',
  }))) return
  editor.removeNode(editor.selectedAid)
}
</script>

<template>
  <div class="editor-toolbar">
    <button class="tb" v-for="c in BASIC" :key="c[0]" :disabled="locked" :title="c[2]" @click="insert(c[0])">+{{ c[1] }}</button>
    <span class="tb-sep" />
    <button class="tb" v-for="c in CONTROL" :key="c[0]" :disabled="locked" :title="c[2]" @click="insert(c[0])">+{{ c[1] }}</button>
    <span class="tb-sep" />
    <label class="tb-chk" title="勾选后, 新节点插入到所选控制流节点(If/For/While/Repeat/Try/Parallel)的首个子块内成为其子节点; 不勾选则插入到所选节点后方(同级)"><input type="checkbox" v-model="asChild" /> 子节点</label>
    <span class="tb-sep" />
    <button class="tb" :disabled="locked || !editor.selectedAid" title="上移选中节点" aria-label="上移选中节点" @click="editor.moveNode(editor.selectedAid, 'up')">↑</button>
    <button class="tb" :disabled="locked || !editor.selectedAid" title="下移选中节点" aria-label="下移选中节点" @click="editor.moveNode(editor.selectedAid, 'down')">↓</button>
    <button class="tb" :disabled="locked || !editor.selectedAid" @click="editor.copyNode(editor.selectedAid)">复制</button>
    <button class="tb" :disabled="locked || !editor.selectedAid" @click="editor.cutNode(editor.selectedAid)">剪切</button>
    <button class="tb" :disabled="locked || !editor.clipboard" @click="editor.pasteAfter(editor.selectedAid)">粘贴</button>
    <button class="tb danger" :disabled="locked || !editor.selectedAid" @click="removeSelected">删除</button>
    <span class="tb-grow" />
    <span v-if="ident" class="doc-ident" :title="ident.path || ident.file">
      <span class="di-label">{{ ident.label }}</span><small>{{ ident.file }}</small>
    </span>
    <span v-if="editor.readonly" class="ro-tag">只读历史版本</span>
    <button class="tb save" :disabled="editor.readonly || !editor.dirty" @click="editor.save()">
      <span role="status">{{ editor.dirty ? '保存 *' : '已保存' }}</span>
    </button>
  </div>
</template>

<style scoped>
/* 全局 .doc-ident 只在 small 上做省略; 外层不裁剪时 label 会顶开工具栏。
   flex 子项 min-width 归零后两段各自参与省略 */
.doc-ident { overflow: hidden; }
.di-label, .doc-ident small { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
</style>
