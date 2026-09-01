// 编辑器 store: 脚本仓库 + 当前脚本节点树 + 选择 + 树变更 + 保存
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api'
import { locate, newNode } from '../utils/script'

export const useEditorStore = defineStore('editor', () => {
  const operations = ref([])                         // 流程脚本摘要 (仓库只存 operation)
  const doc = ref(null)                              // 当前脚本完整文档
  const current = ref({ name: '', kind: '' })
  const selectedAid = ref('')
  const dirty = ref(false)
  const readonly = ref(false)                        // 历史版本只读
  const clipboard = ref(null)
  const actionsCache = ref([])                       // 原子动作目录 (插入调色板)

  const tree = computed(() => (doc.value && doc.value.body) || [])
  const variables = computed(() => (doc.value && doc.value.vars) || [])
  const selectedNode = computed(() => {
    if (!doc.value || !selectedAid.value) return null
    try { return locate(doc.value, selectedAid.value).node } catch (e) { return null }
  })

  async function loadRepo() {
    operations.value = await api.listScripts('operation')
  }

  async function ensureActions() {
    if (!actionsCache.value.length) actionsCache.value = await api.listActions()
    return actionsCache.value
  }

  async function refreshActions() {
    // 强制重拉动作目录 (raw 编辑保存后 label/分组/增删名可能变, 刷新左栏库)
    actionsCache.value = await api.listActions()
    return actionsCache.value
  }

  async function reloadActions() {
    // 令后端从磁盘重扫动作目录并热替换 registry (直接改了 YAML 后手动同步), 再重拉左栏库
    await api.reloadActions()
    return refreshActions()
  }

  async function loadScript(name) {
    doc.value = await api.getScript(name)
    current.value = { name: doc.value.name, kind: doc.value.kind }
    selectedAid.value = ''
    dirty.value = false
    readonly.value = false
  }

  async function loadVersion(name, rev) {
    doc.value = await api.getScriptVersion(name, rev)
    readonly.value = true
    selectedAid.value = ''
  }

  async function save() {
    if (!doc.value || readonly.value) return
    const clean = JSON.parse(JSON.stringify(doc.value))
    await api.saveScript(clean.name, clean)
    dirty.value = false
    await loadRepo()
  }

  function selectNode(aid) {
    selectedAid.value = aid
  }

  function _touch() {
    dirty.value = true
  }

  // 整条流程注释 (doc.note): 右栏「注释」tab 编辑, 随 save() 持久化
  // (validate_script 不校验额外字段, ScriptRepo 用 safe_dump(doc) 保留 note)
  function setNote(v) {
    if (doc.value && !readonly.value) {
      doc.value.note = v
      _touch()
    }
  }

  // ---- 树变更 (按 AID 定位父数组后增删移) ----

  function insertAfter(aid, node) {
    if (!doc.value) return
    if (!aid) { doc.value.body.push(node); _touch(); return }
    const { list, index } = locate(doc.value, aid)
    list.splice(index + 1, 0, node)
    _touch()
  }

  function insertChild(aid, node) {
    // 把节点插入到所选控制流节点的首个子块 (then/body/try-body/资源区间体/分支0)
    const { node: target } = locate(doc.value, aid)
    if (!target) return
    if (target.op === 'if') (target.then || (target.then = [])).push(node)
    else if (['for', 'while', 'repeat'].includes(target.op)) (target.body || (target.body = [])).push(node)
    else if (target.op === 'try') (target.body || (target.body = [])).push(node)
    else if (target.op === 'with_resources') (target.body || (target.body = [])).push(node)
    else if (target.op === 'parallel') {
      if (!target.branches.length) target.branches.push([])
      target.branches[0].push(node)
    } else return
    _touch()
  }

  function insertNode(op, asChild = false) {
    const node = newNode(op)
    if (asChild && selectedNode.value) insertChild(selectedAid.value, node)
    else insertAfter(selectedAid.value, node)
  }

  function removeNode(aid) {
    if (!aid) return
    const { list, index } = locate(doc.value, aid)
    list.splice(index, 1)
    selectedAid.value = ''
    _touch()
  }

  function moveNode(aid, dir) {
    const { list, index } = locate(doc.value, aid)
    const to = dir === 'up' ? index - 1 : index + 1
    if (to < 0 || to >= list.length) return
    const [item] = list.splice(index, 1)
    list.splice(to, 0, item)
    selectedAid.value = ''
    _touch()
  }

  function copyNode(aid) {
    const { node } = locate(doc.value, aid)
    if (node) clipboard.value = JSON.parse(JSON.stringify(node))
  }

  function cutNode(aid) {
    copyNode(aid)
    removeNode(aid)
  }

  function pasteAfter(aid) {
    if (!clipboard.value) return
    insertAfter(aid, JSON.parse(JSON.stringify(clipboard.value)))
  }

  // ---- 控制流子块结构编辑 (RightPanel 用) ----

  function addElif(node) {
    ;(node.elifs || (node.elifs = [])).push({ cond: { lit: true }, body: [] })
    _touch()
  }
  function addCatch(node) {
    ;(node.catch || (node.catch = [])).push({ error: '*', body: [] })
    _touch()
  }
  function addBranch(node) {
    ;(node.branches || (node.branches = [])).push([])
    _touch()
  }

  return {
    operations, doc, current, selectedAid, dirty, readonly, clipboard, actionsCache,
    tree, variables, selectedNode,
    loadRepo, ensureActions, refreshActions, reloadActions, loadScript, loadVersion, save, selectNode,
    insertNode, insertChild, removeNode, moveNode, copyNode, cutNode, pasteAfter,
    addElif, addCatch, addBranch, markDirty: _touch, setNote,
  }
})
