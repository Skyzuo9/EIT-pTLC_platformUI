<script setup>
// 左 Dock: 按最左 rail 选中的栏渲染对应列表 (动作 / 流程 均按磁盘文件夹分组, 可折叠 / 设备 / 执行记录)
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '../api'
import { announce } from '../composables/announcer.js'
import { confirmAction, promptAction } from '../composables/confirmService.js'
import { pressable } from '../utils/a11y.js'
import { healthText as healthLabel } from '../utils/deviceLabels.js'
import { buildBuckets } from '../utils/opGroups.js'
import { useEditorStore } from '../stores/editor'
import { useNodesStore } from '../stores/nodes'
import { usePlannerStore } from '../stores/planner'
import { useSchedulerStore } from '../stores/scheduler'
import { usePointsStore } from '../stores/points'
import { usePlcStore } from '../stores/plc'
import { useRunsStore } from '../stores/runs'
import { fmtDur } from '../utils/planner'
import { runStatusLabel } from '../utils/runStatus'
import { loadJson, saveJson } from '../utils/storage'
import { sectionOf } from '../utils/section.js'
import SymbolExportPanel from './plc/SymbolExportPanel.vue'
import TimingSettingsModal from './planner/TimingSettingsModal.vue'
import ContextMenu from './ui/ContextMenu.vue'

const route = useRoute()
const router = useRouter()
const editor = useEditorStore()
const nodes = useNodesStore()
const points = usePointsStore()
const plc = usePlcStore()
// 会话属主独占徽标: 某自动方(agent/后端)正会话级独占共享 InoProShop; 空闲后可被别的进程接管
const plcOwnerLabel = computed(() => {
  const s = plc.sessionStatus
  if (!s?.owned || !s.owner) return ''
  const idle = typeof s.owner_idle_sec === 'number' ? ` · 空闲 ${Math.round(s.owner_idle_sec)}s` : ''
  return `${s.owner.label || 'client'}${idle}`
})
const runs = useRunsStore()
const planner = usePlannerStore()
const scheduler = useSchedulerStore()

// 实验栏子页 (Dock 高亮): board 缺省 | submit | batch | recipe
const schedulerSub = computed(() => route.params.sub || 'board')

// 轻量结果条 (取代 window.alert): 视觉落点在 dock 顶部, 读屏经 announce 播报
const dockErr = ref('')
function dockFail(prefix, e) {
  dockErr.value = `${prefix}: ${errText(e)}`   // 后端 400/422 的 detail (如删除引用清单) 原样透出
  announce(dockErr.value, { assertive: true })
}

// 当前栏由路由推导 (公共真源 utils/section.js)
const section = computed(() => sectionOf(route.path))

// 物料导航 (左 Dock): 四类物料来自后端拓扑 (config/material_topology.yaml 单一真源),
// 前端不再硬编码分类 —— 加一类物料只改那个 yaml。每类是一个子路由 /materials/<key>。
// 末尾再挂一条纯前端的「记账流水」(log): 它不属于任何一类物料, 是全量流水, 故不进拓扑。
const materialCats = ref([])
const MATERIAL_LOG_ENTRY = { key: 'log', label: '记账流水', hint: '最近 40 条; manual=人工盘点' }
const MATERIAL_AUDIT_ENTRY = { key: 'audit', label: '一键审查', hint: '账实体检: 传感器/派生/双账/人工核对 · 只报不改' }
const materialNav = computed(() => [...materialCats.value, MATERIAL_AUDIT_ENTRY, MATERIAL_LOG_ENTRY])
// 当前子页: 无 cat 参数时落在第一类 (与 MaterialView 的缺省一致)
const materialCat = computed(
  () => route.params.cat || materialCats.value[0]?.key || 'tray')
async function loadMaterialCats() {
  if (materialCats.value.length) return
  try { materialCats.value = await api.getMaterialTopology() }
  catch { materialCats.value = [] }
}
watch(() => section.value === 'materials', (on) => { if (on) loadMaterialCats() },
      { immediate: true })

// 实验栏惰性拉取 (照 planner 范式): 进栏才拉方案/批次列表与快照
watch(() => section.value === 'scheduler', (on) => {
  if (on) { scheduler.ensureRecipes(); scheduler.ensureBatches(); scheduler.ensureSnapshot() }
}, { immediate: true })
// 调度栏: 只需方案列表
watch(() => section.value === 'schedule', (on) => {
  if (on) scheduler.ensureRecipes()
}, { immediate: true })

// 新建调度方案: 以默认方案 (或第一个) 为模板整份复制改名 —— 空方案对工程师没有起点价值,
// 从一份能跑的 12 段方案改依赖是最短路径。后端 PUT 新名字即新建。
async function newSchedule() {
  const src = (scheduler.recipes.find((r) => r.default) || scheduler.recipes[0])?.name
  if (!src) { dockFail('新建方案失败', new Error('还没有可作模板的方案')); return }
  const next = await promptAction({
    title: '新建调度方案',
    message: `以「${src}」为模板复制一份, 随后在编排器里改段与依赖。`,
    initial: `${src}_copy`,
    validate: (v) => {
      const s = v.trim()
      if (!/^[A-Za-z0-9_-]+$/.test(s)) return '方案名仅限字母/数字/下划线/连字符'
      if (scheduler.recipes.some((r) => r.name === s)) return '该方案名已存在'
      return ''
    },
  })
  if (next === null) return
  const name = next.trim()
  try {
    const { doc } = await api.getRecipeDoc(src)
    await api.saveRecipeDoc(name, { ...doc, name, label: `${doc.label} (副本)` })
    await scheduler.loadRecipes()
    router.push(`/schedule/${name}`)
  } catch (e) {
    dockFail('新建方案失败', e)
  }
}
function openMaterial(key) { router.push(`/materials/${key}`) }

// 液位通道导航 (左 Dock): 网格总览 + CH1-8
const WL_CHANNELS = [1, 2, 3, 4, 5, 6, 7, 8]
function openWl(ch) { router.push(ch ? `/water_level/${ch}` : '/water_level') }

// PLC 程序 (POU): 列表不自动加载 (会拉起 InoProShop), 改由用户点「连接」显式触发 (plc.connect)
function openPou(path) { router.push('/plc/pou/' + path) }

// 手动动作面板隐藏: 点动起停 + VM 编排专用原语 (工具动作/锚点校验/驻留, 由点位 operation 调用, 不在面板直发)
const HIDDEN_ACTIONS = new Set([
  'robot.jog_start', 'robot.jog_stop',
  'robot.tool_action', 'robot.require_anchor', 'robot.home_ensure', 'robot.dwell',
])
const UNGROUPED = '未分组'

// 通用: 按 group 字段聚合为 [{title, items}], 组按名称升序 (数字前缀即顺序), 组内按 label
function groupBy(list, groupKey) {
  const map = new Map()
  for (const it of list) {
    const title = it[groupKey] || UNGROUPED
    if (!map.has(title)) map.set(title, [])
    map.get(title).push(it)
  }
  return [...map.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([title, items]) => ({ title, items: items.slice().sort((x, y) => (x.label || x.name).localeCompare(y.label || y.name)) }))
}

// 动作: 文件夹驱动分组 (组标题=config/actions 下子文件夹名)
const actionGroups = computed(() =>
  groupBy(editor.actionsCache.filter((a) => !HIDDEN_ACTIONS.has(a.name)), 'group'))

// 「⟳ 刷新」: 令后端从磁盘重扫动作目录并热重载, 再重拉左栏库 (直接改了动作 YAML 后同步, 无需重启后端)
const actionsReloading = ref(false)
async function onReloadActions() {
  if (actionsReloading.value) return
  actionsReloading.value = true
  dockErr.value = ''
  try {
    await editor.reloadActions()
  } catch (e) {
    dockFail('动作重载失败', e)
  } finally {
    actionsReloading.value = false
  }
}
// 全工站一键初始化: 走 system_init_all 编排 (留痕可回放)。耗时可达数分钟 (展缸逐缸 + 泵初始化),
// 故按钮全程置忙; 失败时后端 422 的 detail 里已点名哪几站没成, 原样透出即可。
// 确认框必须如实说明"两路同时动" —— 操作员据此判断现在什么在动, 写成串行是安全问题。
// 两路怎么切的 (按注射泵 485 总线) 见 config/operation/00_system/system_init_all.yaml 文件头。
const initAllBusy = ref(false)
async function onInitAll() {
  if (initAllBusy.value) return
  if (!(await confirmAction({
    title: '初始化全部工站',
    level: 'danger',
    message: [
      '将分两路同时跑:',
      '① 拍照刮板工站 → 上下料位',
      '② 上样工站 → 展开工站(8缸) → 收集工站',
      '两路并行, 会实际动作机构; 要求机械臂已停在 P1 安全位。',
    ],
    confirmText: '开始初始化',
  }))) {
    return
  }
  initAllBusy.value = true
  dockErr.value = ''
  try {
    await api.plcStationsInitAll()
    dockErr.value = ''
    announce('全工站初始化完成 ✓')
  } catch (e) {
    dockFail('全工站初始化失败', e)
  } finally {
    initAllBusy.value = false
  }
}
// 动作显示名/删除 (与流程侧同款交互): label 只是 UI 展示名, 流程按 id 引用动作, 改名零影响
async function renameActionLabel(name, label) {
  const next = await promptAction({
    title: '修改显示中文名',
    initial: label || name,
    validate: (v) => (v.trim() ? '' : '名称不能为空'),
  })
  if (next === null) return                 // 取消
  const v = next.trim()
  if (!v || v === label) return             // 未变则跳过
  try {
    await api.saveActionLabel(name, v)
    await editor.refreshActions()           // 左栏与流程编辑器步骤行/下拉即时跟新
  } catch (e) {
    dockFail('改显示名失败', e)
  }
}
async function deleteAction(name, label) {
  if (!(await confirmAction({
    title: `删除动作 ${label || name}`,
    message: '动作定义文件将被删除; 被流程引用时后端会拒绝并列出引用清单。',
    detail: name,
    level: 'danger',
    confirmText: '删除',
  }))) return
  try {
    await api.deleteAction(name)
    await editor.refreshActions()
    // 菜单可删非选中项: 仅当详情页正开着被删动作才退回落地页
    if (isActive('action', name)) router.push('/library/action')
  } catch (e) {
    dockFail('删除失败', e)                  // 被流程引用时后端 400, 提示含引用清单, 照旧展示
  }
}
// ---- 排程「流程耗时」栏 (流程库: 点行加入中区选中样品) ----
const plannerGroups = computed(() => groupBy(planner.pickerOps, 'group'))

// 行上的耗时徽标: 按当前口径显示; 无历史 (或已清除到无记录) 显"无历史"
function plannerOpDur(op) {
  if (!op.count) {
    return '无历史'
  }
  const dur = planner.plan.settings.durationMode === 'last' ? op.last_s : op.avg_s
  return `${fmtDur(dur)} · n=${op.count}`
}

// 耗时来源说明: 子流程的记录可能全部来自父流程里的嵌套执行, 标明来源才好判断可信度
function plannerOpDurTitle(op) {
  if (!op.count) {
    return '该流程还没有可用的耗时记录'
  }
  if (!op.nested_count) {
    return `${op.count} 次单独运行的耗时`
  }
  if (op.nested_count === op.count) {
    return `${op.count} 次全部来自父流程内的嵌套执行 (该流程没有单独运行过)`
  }
  return `${op.count} 次中有 ${op.nested_count} 次来自父流程内的嵌套执行`
}

// 清除 = 把统计基线设到当前时刻 (不删运行记录, 可撤销), 故确认文案只说"作废"且用 normal 级
async function clearPlannerStats(op) {
  if (!(await confirmAction({
    title: `作废「${op.label}」的耗时记录`,
    message: `现有 ${op.count} 条记录不再计入统计; 只重置统计起点, 运行记录与回放保留, 可随时撤销。`,
    confirmText: '作废',
  }))) return
  planner.resetBaseline(op.name)
}
// ---- 行菜单 (右键与行尾 ⋯ 共用一个 ContextMenu 单例) + 耗时设置弹窗开关 ----
// 右键不改变选中/导航 (菜单头部显示对象名供确认); 「历史」是唯一需要选中前提的项, 见 openHistory
const menuRef = ref(null)
const timingSettingsOpen = ref(false)

function openActionMenu(ev, a) {
  menuRef.value?.open(ev, [
    { key: 'label', label: '改显示名', onSelect: () => renameActionLabel(a.name, a.label) },
    { key: 'del', label: '删除', variant: 'danger', onSelect: () => deleteAction(a.name, a.label) },
  ], a.label || a.name)
}
function openOperationMenu(ev, s) {
  menuRef.value?.open(ev, [
    { key: 'clone', label: '克隆', onSelect: () => cloneOperation(s.name) },
    { key: 'rename', label: '重命名', onSelect: () => renameOperation(s.name) },
    { key: 'label', label: '改显示名', onSelect: () => renameLabel(s.name, s.label) },
    { key: 'history', label: '历史', onSelect: () => openHistory(s.name) },
    { key: 'del', label: '删除', variant: 'danger', onSelect: () => deleteOperation(s.name) },
  ], s.label || s.name)
}
function openPlannerOpMenu(ev, op) {
  menuRef.value?.open(ev, [
    { key: 'detail', label: '明细 (步骤时间线)', onSelect: () => planner.openTimeline(op.name) },
    op.baseline_ts
      ? { key: 'undo', label: '↺ 撤销清除', variant: 'ok',
          title: '撤销该流程的清除, 恢复历史统计', onSelect: () => planner.clearBaseline(op.name) }
      : { key: 'clear', label: '清除记录', variant: 'danger',
          title: '清除该流程的耗时记录 (只重置统计起点, 可撤销)', onSelect: () => clearPlannerStats(op) },
  ], op.label)
}

// 流程: 默认只展示主流程/主周期; helper/debug/legacy 脚本仍保留在仓库中供 run_script 引用。
// 组内按 ui.subgroup 再分子栏 (机械臂组按涉及工位); 无 subgroup 的组单匿名桶, 渲染同原平铺
const operationGroups = computed(() => groupBy(
  editor.operations.filter((s) => !(s.ui && s.ui.hidden)),
  'group',
).map((g) => ({ ...g, buckets: buildBuckets(g.items) })))
const existingOpGroups = computed(() => operationGroups.value.map((g) => g.title).filter((t) => t !== UNGROUPED))

// ---- PLC 程序树 (左 Dock「plc」栏): POU 程序树, 「预序行 + 折叠」渲染 ----
// 显示层级以 InoProShop 程序树为准: 真实嵌套 (文件夹→PRG→A 动作), 兄弟按名称数字感知升序 (10/20/30...), 阶梯缩进。
// 行结构: {key, path, name, depth, has_children, openable, openPath}

// 由扁平 POU 列表 (plc.pous, 顺序即 walk_pous 的 InoProShop 树序) 重建嵌套树, 产出"省略 Application 根"的预序行
function pouPreorder() {
  const root = { children: new Map() }   // Map 保插入序 = InoProShop 树序
  for (const p of plc.pous) {
    const parts = String(p.path).split('/')
    let cur = root
    let prefix = ''
    for (const seg of parts) {
      prefix = prefix ? prefix + '/' + seg : seg
      if (!cur.children.has(seg)) {
        cur.children.set(seg, { name: seg, path: prefix, has_impl: false, has_decl: false, children: new Map() })
      }
      cur = cur.children.get(seg)
    }
    cur.has_impl = !!p.has_impl   // 叶/PRG 自身的可编辑标记 (中间文件夹保持 false)
    cur.has_decl = !!p.has_decl
  }
  // 省略 Application 根: 单一根且名为 Application 时从其子级起始, 否则退回全部根 (防御)
  let top = root
  if (root.children.size === 1) {
    const only = [...root.children.values()][0]
    if (only.name.toLowerCase() === 'application') {
      top = only
    }
  }
  const out = []
  function dfs(node, depth) {
    // 同级按名称数字感知升序 (10/20/30...); 无数字前缀者排在数字之后
    const kids = [...node.children.values()].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
    for (const c of kids) {
      out.push({ path: c.path, name: c.name, depth, has_impl: c.has_impl, has_decl: c.has_decl,
                 has_children: c.children.size > 0 })
      dfs(c, depth + 1)
    }
  }
  dfs(top, 0)
  return out
}

// 预序列表按折叠态裁剪 + 补 key/openable/openPath; kp 为折叠键前缀 (持久化用)
function applyCollapse(preorder, kp) {
  const rows = []
  let hideDepth = Infinity   // 落在折叠子树内 (depth > hideDepth) 的行跳过
  for (const n of preorder) {
    if (n.depth > hideDepth) {
      continue
    }
    hideDepth = Infinity      // 出了折叠子树
    const key = kp + ':' + n.path
    const openable = !!(n.has_impl || n.has_decl)
    const openPath = n.path
    rows.push({ key, path: n.path, name: n.name, depth: n.depth, has_children: n.has_children, openable, openPath })
    if (n.has_children && isCollapsed(key)) {
      hideDepth = n.depth
    }
  }
  return rows
}

// 两级 computed 分离依赖: 树构建 (Map+DFS+localeCompare) 只随 plc.pous 变;
// 折叠切换只重跑 applyCollapse 裁剪, 不再全量重建树
const pouTree = computed(pouPreorder)
const pouRows = computed(() => applyCollapse(pouTree.value, 'pou'))

// 行点击: 程序节点 (POU/GVL/动作) 进编辑器; 纯文件夹/硬件节点折叠展开
function onPlcRow(r) {
  if (r.openable) {
    openPou(r.openPath)
    return
  }
  if (r.has_children) {
    toggleCollapse(r.key)
  }
}

// ---- 分组折叠 (localStorage 持久化, 默认展开) ----
const COLLAPSE_KEY = 'eit_dock_collapsed'
const collapsed = ref(loadJson(COLLAPSE_KEY, {}))
function isCollapsed(key) { return !!collapsed.value[key] }
function toggleCollapse(key) {
  const next = { ...collapsed.value }
  if (next[key]) delete next[key]; else next[key] = true
  collapsed.value = next
  saveJson(COLLAPSE_KEY, next)
}

// ---- 流程 (operation 脚本) 仓库操作 ----
const versionsOpen = ref(false)
const versions = ref([])

function isActive(kind, name) { return route.params.kind === kind && route.params.name === name }
function openAction(name) { router.push(`/library/action/${name}`) }
function openOperation(name) { versionsOpen.value = false; router.push(`/library/operation/${name}`) }

// 流程名校验: 非空 + 与现有流程查重 (allow = 重命名时放行自身)
function opNameError(v, allow = '') {
  const t = v.trim()
  if (!t) return '名称不能为空'
  if (t !== allow && editor.operations.some((s) => s.name === t)) return `已存在同名流程: ${t}`
  return ''
}
async function newOperation() {
  const name = await promptAction({
    title: '新建流程脚本',
    message: '脚本名用英文/下划线',
    placeholder: 'my_operation',
    validate: opNameError,
  })
  if (name === null) return
  const hint = existingOpGroups.value.length ? `已有组: ${existingOpGroups.value.join(' / ')}` : ''
  const group = await promptAction({
    title: '选择组 (文件夹)',
    message: hint ? ['留空 = 库根', hint] : '留空 = 库根',
  })
  if (group === null) return               // 第二步取消 = 放弃新建 (原生版把取消当空组继续建, 易误建)
  try {
    await api.createScript(name.trim(), 'operation', null, group.trim())
    await editor.loadRepo()
    openOperation(name.trim())
  } catch (e) {
    dockFail('新建失败', e)
  }
}
async function cloneOperation(name) {
  const dst = await promptAction({
    title: '克隆流程',
    message: `将 ${name} 克隆为新流程`,
    initial: name + '_copy',
    validate: opNameError,
  })
  if (dst === null) return
  try {
    await api.cloneScript(name, dst.trim())
    await editor.loadRepo()
    openOperation(dst.trim())
  } catch (e) {
    dockFail('克隆失败', e)
  }
}
async function renameOperation(name) {
  const dst = await promptAction({
    title: '重命名流程',
    initial: name,
    validate: (v) => opNameError(v, name),
  })
  if (dst === null || dst.trim() === name) return
  try {
    await api.renameScript(name, dst.trim())
    await editor.loadRepo()
    openOperation(dst.trim())
  } catch (e) {
    dockFail('重命名失败', e)
  }
}
async function renameLabel(name, label) {
  const next = await promptAction({
    title: '修改显示中文名',
    initial: label || name,
    validate: (v) => (v.trim() ? '' : '名称不能为空'),
  })
  if (next === null) return                 // 取消
  const v = next.trim()
  if (!v || v === label) return             // 未变则跳过
  try {
    await api.setScriptLabel(name, v)
    await editor.loadRepo()                  // 刷新左栏列表显示名
    await editor.loadScript(name)            // 刷新打开文档, 防后续 save 回写旧 label
  } catch (e) {
    dockFail('改显示名失败', e)
  }
}
async function deleteOperation(name) {
  if (!(await confirmAction({
    title: `删除流程 ${name}`,
    message: '脚本及其在左栏/排程中的入口将移除, 界面上不可恢复。',
    level: 'danger',
    confirmText: '删除',
  }))) return
  try {
    await api.deleteScript(name)
    await editor.loadRepo()
    // 菜单可删非选中项: 仅当编辑器正开着被删流程才退回落地页
    if (isActive('operation', name)) router.push('/library/operation')
  } catch (e) {
    dockFail('删除失败', e)
  }
}
// 「历史」(菜单项): 版本列表仅渲染在选中行之下 —— 非选中行先导航选中再展开; 已选中行保持开关语义
async function openHistory(name) {
  if (!isActive('operation', name)) {
    openOperation(name)               // 导航即选中 (顺带清掉上一处的 versionsOpen)
  } else if (versionsOpen.value) {
    versionsOpen.value = false
    return
  }
  versionsOpen.value = true
  versions.value = await api.listScriptVersions(name)
}
function openVersion(rev) { editor.loadVersion(route.params.name, rev) }

function openNode(id) { nodes.select(id); router.push(`/nodes/${id}`) }
function openRun(runId) { router.push(`/runs/${runId}`) }

// ---- 执行记录日期筛选 (组件本地态) ----
// 不动 store.recent: runs.js 的对账轮询与 operation 事件都会用 listRuns({limit:50})
// 整体替换 recent, 筛选结果放 store 会被覆盖, 故本地另拉一份。
const runFilterDate = ref('')        // 'YYYY-MM-DD'; 空 = 不筛选
const filteredRuns = ref([])
const runFilterLoading = ref(false)
const runFilterErr = ref('')
const shownRuns = computed(() => (runFilterDate.value ? filteredRuns.value : runs.recent))

// 本地时区当日半开区间 [00:00, 次日00:00) 的 epoch 秒。必须分量构造:
// new Date('YYYY-MM-DD') 按 ISO 规则解析为 UTC 零点, 会整体偏移一个时区;
// 分量构造 d+1 自动进位, 跨月/跨年安全。
function dayRange(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number)
  return {
    since: new Date(y, m - 1, d).getTime() / 1000,
    until: new Date(y, m - 1, d + 1).getTime() / 1000,
  }
}

let runFilterEpoch = 0               // 竞态门: 快速换日期时旧响应作废 (照 runs.js reseedEpoch)
async function loadFilteredRuns() {
  if (!runFilterDate.value) return
  const epoch = ++runFilterEpoch
  runFilterLoading.value = true
  runFilterErr.value = ''
  try {
    const { since, until } = dayRange(runFilterDate.value)
    // limit=1000 对齐 RunStore max_runs 上限: 单日不可能超过全库
    const rows = await api.listRuns({ limit: 1000, since, until })
    if (epoch !== runFilterEpoch) return
    filteredRuns.value = rows
  } catch (e) {
    if (epoch !== runFilterEpoch) return
    runFilterErr.value = errText(e)
    filteredRuns.value = []
  } finally {
    if (epoch === runFilterEpoch) runFilterLoading.value = false
  }
}
watch(runFilterDate, () => { filteredRuns.value = []; loadFilteredRuns() })
// recent 被轮询/终态事件整体替换 = 后端有新动静 → 筛选激活时重拉保持准实时 (引用替换, 浅 watch 即触发)
watch(() => runs.recent, () => { if (runFilterDate.value) loadFilteredRuns() })

// ---- 点位栏 (机器人 / PLC伺服; 两级折叠: 类别 -> 工位) ----
// 顶层 2 个设备类: 伺服 struct 槽位点 (plc_servo) 与 PC 侧 flat 目标点 (plc_servo_target)
// 同归 plc_servo 枝 (后端 tree() 合并)。两者命名空间独立、key 可同名 (如 spot_7y), 故列表项的
// key/id 必须带各点自身 category 去重; 路由/高亮也按点自身 category (p.category) 而非树枝。
// (CNC 为 app.yaml gcode 参数, 已归设备参数页, 不在点位树。)
const POINT_CATS = ['robot', 'plc_servo']
// 机器人点显示名: 中文名 (labels.yaml) + 控制器点名 P 号 —— P 号是流程 YAML 与示教器共用的寻址名,
// 带上便于现场对照; 派生点的 robot_name 是 FLOW_*/DERIVED__* 内部名, 无对照价值故只显中文。
// 无中文名 (labels.yaml 未登记) 时回退英文 alias。PLC 伺服点位沿用其自身 label (本就是中文)。
function pointLabel(p) {
  if (p.category === 'robot') {
    if (!p.label) return p.alias || p.id
    return /^P\d+$/.test(p.robot_name || '') ? `${p.label} ${p.robot_name}` : p.label
  }
  if (p.category === 'plc_servo' || p.category === 'plc_servo_target' || p.category === 'plc_servo_composite') return p.label
  return p.id
}
// hover 提示: 机器人点显中文名背后的英文 alias (与机器人程序源码/示教器对照)
function pointTitle(p) {
  return p.category === 'robot' ? (p.alias || p.robot_name || p.id) : p.id
}
function isActivePoint(p) { return route.params.category === p.category && (route.params.id === p.id || route.params.id === p.robot_name) }
function openPoint(cat, id) { router.push(`/points/${cat}/${encodeURIComponent(id)}`) }
// 孔板标定 / 板位对位 / 刮板对刀: 独立标定入口 (与点位无关)
function openCalib() { router.push('/points/calibration') }
function openPlateAlign() { router.push('/points/plate_align') }
function openToolAlign() { router.push('/points/tool_align') }
function openScrapeCalib() { router.push('/points/scrape_calib') }
function expandGroup(key) {
  if (collapsed.value[key]) {
    const next = { ...collapsed.value }
    delete next[key]
    collapsed.value = next
    saveJson(COLLAPSE_KEY, next)
  }
}
// 跳转到点位: 展开所属类别 + 工位并滚动高亮 (供 action/operation 页 → 点位 跳转)
function focusRoutePoint() {
  if (section.value !== 'points') return
  const cat = route.params.category
  const fid = route.params.id
  if (!cat || !fid || !points.tree) return
  // 目标点位 (category=plc_servo_target) 现并入 plc_servo 枝展示, 故按"点自身 category"跨枝定位
  let branch = null
  let found = null
  let ws = null
  for (const bk of POINT_CATS) {
    const node = points.tree[bk]
    if (!node) continue
    for (const g of node.groups) {
      for (const p of g.points) {
        if (p.category === cat && (p.id === fid || p.robot_name === fid)) { branch = bk; found = p; ws = g.key; break }
      }
      if (found) break
    }
    if (found) break
  }
  if (!found) return
  expandGroup('ptsec:store')                      // 大节收起时点位不可见, 跨页跳转须先展开
  expandGroup('ptcat:' + branch)
  expandGroup('ptws:' + branch + ':' + ws)
  nextTick(() => {
    const el = document.getElementById('pt-' + found.category + '-' + found.id)
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' })
  })
}
watch(() => [route.params.category, route.params.id, points.tree], focusRoutePoint, { immediate: true })

// 排程栏按需拉统计: 不在应用启动时预拉 (其它页面用不到这份数据); 切栏顺带清上一栏的结果条
watch(section, (cur) => {
  dockErr.value = ''
  if (cur === 'planner') {
    planner.ensureStats()
  }
}, { immediate: true })

// 设备健康点的中文可读文本 (纯色点对读屏/色弱不可辨; 取值与 style.css .health-dot.* 一致)
// 标签表在 utils/deviceLabels.js —— 全站一份, 这里只加"健康状态: "前缀
function healthText(h) { return `健康状态: ${healthLabel(h)}` }

onMounted(async () => {
  await editor.ensureActions().catch(() => {})   // 原子指令目录 (动作栏 + 编辑器调色板共用)
  await editor.loadRepo().catch(() => {})         // 流程脚本
  points.loadTree().catch(() => {})               // 点位目录 (机器人/PLC伺服)
  plc.loadSession().catch(() => {})               // 只读会话状态; 不拉起 InoProShop
  if (!runs.recent.length) runs.seedRecent().catch(() => {})
})
</script>

<template>
  <div class="dock">
    <!-- 轻量结果条: CRUD/初始化的失败落点 (取代 window.alert), announce 负责读屏 -->
    <p v-if="dockErr" class="hint" role="status">{{ dockErr }}</p>

    <!-- 动作 (原子指令, 文件夹分组, 可折叠, 只读可执行) -->
    <div v-if="section === 'action'">
      <div class="repo-head">
        <span class="group-title">动作 (原子指令)</span>
        <button class="mini act-refresh" :disabled="actionsReloading" @click="onReloadActions"
                title="从磁盘重新加载动作 YAML(直接改了配置文件后点此同步, 无需重启后端)">
          {{ actionsReloading ? '刷新中…' : '⟳ 刷新' }}
        </button>
      </div>
      <div v-for="g in actionGroups" :key="g.title">
        <button type="button" class="btn-bare group-title clickable"
                :aria-expanded="!isCollapsed('act:' + g.title)" @click="toggleCollapse('act:' + g.title)">
          <span class="chev" aria-hidden="true">{{ isCollapsed('act:' + g.title) ? '▸' : '▾' }}</span>{{ g.title }}
        </button>
        <ul v-show="!isCollapsed('act:' + g.title)">
          <!-- 行操作 (改显示名/删除) 收进右键与行尾 ⋯ 菜单; ⋯ 常显是触屏唯一入口 (iOS 无 contextmenu) -->
          <li v-for="a in g.items" :key="a.name" class="has-more"
              :class="{ active: isActive('action', a.name) }"
              @contextmenu.prevent.stop="openActionMenu($event, a)">
            <button type="button" class="btn-bare" :aria-current="isActive('action', a.name) ? 'true' : undefined"
                    @click="openAction(a.name)">{{ a.label }}</button>
            <button type="button" class="row-more" aria-haspopup="menu" :aria-label="`更多操作: ${a.label}`"
                    @click.stop="openActionMenu($event, a)" @keydown.stop>⋯</button>
          </li>
        </ul>
      </div>
      <p v-if="!actionGroups.length" class="empty">暂无动作</p>
    </div>

    <!-- 流程 (可编排 operation 脚本, 文件夹分组, 可折叠) -->
    <div v-else-if="section === 'operation'">
      <div class="repo-head">
        <span class="group-title">流程 (operation)</span>
        <button class="mini" @click="newOperation">+ 新建</button>
      </div>
      <p v-if="!operationGroups.length" class="empty">暂无流程</p>
      <div v-for="g in operationGroups" :key="g.title">
        <button type="button" class="btn-bare group-title clickable"
                :aria-expanded="!isCollapsed('op:' + g.title)" @click="toggleCollapse('op:' + g.title)">
          <span class="chev" aria-hidden="true">{{ isCollapsed('op:' + g.title) ? '▸' : '▾' }}</span>{{ g.title }}
        </button>
        <div v-show="!isCollapsed('op:' + g.title)">
          <template v-for="b in g.buckets" :key="b.sub || ''">
            <!-- 子栏头 (仅 ui.subgroup 桶, 目前只有机械臂组按工位分): 复用点位树的 sub 样式与折叠机制 -->
            <button v-if="b.sub" type="button" class="btn-bare group-title clickable sub"
                    :aria-expanded="!isCollapsed('op:' + g.title + ':' + b.sub)" @click="toggleCollapse('op:' + g.title + ':' + b.sub)">
              <span class="chev" aria-hidden="true">{{ isCollapsed('op:' + g.title + ':' + b.sub) ? '▸' : '▾' }}</span>{{ b.sub }} <small class="cnt">{{ b.items.length }}</small>
            </button>
            <ul v-show="!b.sub || !isCollapsed('op:' + g.title + ':' + b.sub)" :class="{ 'sub-items': !!b.sub }">
              <template v-for="s in b.items" :key="s.name">
                <!-- 行操作 (克隆/重命名/改显示名/历史/删除) 收进右键与行尾 ⋯ 菜单 -->
                <li class="has-more" :class="{ active: isActive('operation', s.name) }"
                    @contextmenu.prevent.stop="openOperationMenu($event, s)">
                  <button type="button" class="btn-bare" :title="s.note || undefined"
                          :aria-current="isActive('operation', s.name) ? 'true' : undefined"
                          @click="openOperation(s.name)">{{ s.label }}</button>
                  <button type="button" class="row-more" aria-haspopup="menu" :aria-label="`更多操作: ${s.label}`"
                          @click.stop="openOperationMenu($event, s)" @keydown.stop>⋯</button>
                </li>
                <li v-if="isActive('operation', s.name) && versionsOpen" class="versions">
                  <p v-if="!versions.length" class="empty">无版本</p>
                  <button v-for="v in versions" :key="v.rev" type="button" class="btn-bare ver"
                          @click.stop="openVersion(v.rev)">
                    #{{ v.rev }} <small>{{ v.ts }}</small>
                  </button>
                </li>
              </template>
            </ul>
          </template>
        </div>
      </div>
    </div>

    <!-- 点位: 两个可整体折叠的平级大节 —— 标定 (独立入口) / 存储 (点位树) -->
    <div v-else-if="section === 'points'">
      <!-- 点位标定: 与具体点位无关的标定/示教入口 -->
      <button type="button" class="btn-bare group-title clickable"
              :aria-expanded="!isCollapsed('ptsec:calib')" @click="toggleCollapse('ptsec:calib')">
        <span class="chev" aria-hidden="true">{{ isCollapsed('ptsec:calib') ? '▸' : '▾' }}</span>点位标定
      </button>
      <ul v-show="!isCollapsed('ptsec:calib')">
        <li :class="{ active: route.params.category === 'calibration' }">
          <button type="button" class="btn-bare" :aria-current="route.params.category === 'calibration' ? 'true' : undefined" @click="openCalib">孔板标定</button>
        </li>
        <li :class="{ active: route.params.category === 'plate_align' }">
          <button type="button" class="btn-bare" :aria-current="route.params.category === 'plate_align' ? 'true' : undefined" @click="openPlateAlign">板位对位</button>
        </li>
        <li :class="{ active: route.params.category === 'tool_align' }">
          <button type="button" class="btn-bare" :aria-current="route.params.category === 'tool_align' ? 'true' : undefined" @click="openToolAlign">刮板对刀</button>
        </li>
        <li :class="{ active: route.params.category === 'scrape_calib' }">
          <button type="button" class="btn-bare" :aria-current="route.params.category === 'scrape_calib' ? 'true' : undefined" @click="openScrapeCalib">刮痕标定</button>
        </li>
      </ul>

      <!-- 点位存储: 点位目录 (机器人 / PLC伺服; 内部仍是两级折叠: 类别 -> 工位) -->
      <button type="button" class="btn-bare group-title clickable"
              :aria-expanded="!isCollapsed('ptsec:store')" @click="toggleCollapse('ptsec:store')">
        <span class="chev" aria-hidden="true">{{ isCollapsed('ptsec:store') ? '▸' : '▾' }}</span>点位存储
      </button>
      <div v-show="!isCollapsed('ptsec:store')">
        <p v-if="points.loading" class="empty loading">加载中…</p>
        <p v-else-if="points.error" class="empty">点位加载失败: {{ points.error }}</p>
        <p v-else-if="!points.tree" class="empty">暂无点位</p>
        <template v-for="cat in POINT_CATS" :key="cat">
          <div v-if="points.tree && points.tree[cat]">
            <button type="button" class="btn-bare group-title clickable cat"
                    :aria-expanded="!isCollapsed('ptcat:' + cat)" @click="toggleCollapse('ptcat:' + cat)">
              <span class="chev" aria-hidden="true">{{ isCollapsed('ptcat:' + cat) ? '▸' : '▾' }}</span>{{ points.tree[cat].label }}
            </button>
            <div v-show="!isCollapsed('ptcat:' + cat)">
              <div v-for="g in points.tree[cat].groups" :key="g.key">
                <button type="button" class="btn-bare group-title clickable sub"
                        :aria-expanded="!isCollapsed('ptws:' + cat + ':' + g.key)" @click="toggleCollapse('ptws:' + cat + ':' + g.key)">
                  <span class="chev" aria-hidden="true">{{ isCollapsed('ptws:' + cat + ':' + g.key) ? '▸' : '▾' }}</span>{{ g.label }} <small class="cnt">{{ g.points.length }}</small>
                </button>
                <ul v-show="!isCollapsed('ptws:' + cat + ':' + g.key)">
                  <li v-for="p in g.points" :key="p.category + ':' + p.id" :id="'pt-' + p.category + '-' + p.id"
                      class="pt-leaf" :class="{ active: isActivePoint(p) }">
                    <button type="button" class="btn-bare" :aria-current="isActivePoint(p) ? 'true' : undefined"
                            :title="pointTitle(p)"
                            @click="openPoint(p.category, p.id)">{{ pointLabel(p) }}</button>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 视觉调试: 拍照与识别 -->
    <div v-else-if="section === 'vision'">
      <div class="group-title">视觉调试</div>
      <ul>
        <li :class="{ active: route.path === '/vision' }">
          <button type="button" class="btn-bare" :aria-current="route.path === '/vision' ? 'true' : undefined"
                  @click="router.push('/vision')">拍照与识别</button>
        </li>
      </ul>
    </div>

    <!-- 液位检测外设 (香橙派): 网格总览 + 8 路通道 -->
    <div v-else-if="section === 'water_level'">
      <div class="group-title">液位监测</div>
      <ul>
        <li :class="{ active: !route.params.channel }">
          <button type="button" class="btn-bare" :aria-current="!route.params.channel ? 'true' : undefined"
                  @click="openWl(null)">网格总览 (8 路)</button>
        </li>
        <li v-for="ch in WL_CHANNELS" :key="ch"
            :class="{ active: String(route.params.channel) === String(ch) }">
          <button type="button" class="btn-bare"
                  :aria-current="String(route.params.channel) === String(ch) ? 'true' : undefined"
                  @click="openWl(ch)">CH{{ ch }}</button>
        </li>
      </ul>
    </div>

    <!-- PLC 栏: 「符号导出」「PLC 程序」两个可整体折叠的平级段 (符号导出在上, PLC 程序在下) -->
    <div v-else-if="section === 'plc'">
      <!-- 符号导出 (OPC): 跟随当前打开的 GVL/POU; 勾选变量 → 加 symbol pragma 暴露到 OPC -->
      <button type="button" class="btn-bare group-title clickable"
              :aria-expanded="!isCollapsed('plcsec:symbols')" @click="toggleCollapse('plcsec:symbols')">
        <span class="chev" aria-hidden="true">{{ isCollapsed('plcsec:symbols') ? '▸' : '▾' }}</span>符号导出 (OPC)
      </button>
      <div v-show="!isCollapsed('plcsec:symbols')">
        <SymbolExportPanel />
      </div>

      <!-- PLC 程序 (CODESYS): 显式「连接」拉起 InoProShop 后显示 POU 树, 点程序节点进双区编辑。
           头部内嵌真按钮 (button 不可嵌 button) → 折叠开关走 pressable; 内嵌钮 @keydown.stop 挡行级 Enter/Space (NodeRow 同款) -->
      <div class="group-title clickable plcsec-head"
           v-bind="pressable(() => toggleCollapse('plcsec:program'))"
           :aria-expanded="!isCollapsed('plcsec:program')">
        <span class="chev" aria-hidden="true">{{ isCollapsed('plcsec:program') ? '▸' : '▾' }}</span>PLC 程序
        <button class="mini" :disabled="plc.statusBusy || plc.sessionStatus?.manual_control"
                @click.stop="plc.connect()" @keydown.stop>
          {{ plc.statusBusy ? '连接中…' : (plc.connected ? '重新连接' : '连接') }}
        </button>
      </div>
      <div v-show="!isCollapsed('plcsec:program')">
        <div class="session-strip" :class="{ manual: plc.sessionStatus?.manual_control }">
          <span class="session-dot"
                :class="{ ok: plc.sessionStatus?.worker_alive || plc.sessionStatus?.keeper_alive, warn: plc.sessionStatus?.manual_control }" />
          <span class="session-text">
            {{ plc.sessionStatus?.manual_control ? '用户接管' : (plc.sessionStatus?.worker_alive ? '共享在线' : (plc.sessionStatus?.keeper_alive ? '保活中' : '未保活')) }}
          </span>
          <button class="mini" :disabled="plc.sessionBusy" @click.stop="plc.loadSession()">刷新</button>
          <button v-if="!plc.sessionStatus?.manual_control" class="mini" :disabled="plc.sessionBusy" @click.stop="plc.takeoverSession()">接管</button>
          <button v-else class="mini ok" :disabled="plc.sessionBusy" @click.stop="plc.releaseSession()">释放</button>
        </div>
        <p v-if="plcOwnerLabel" class="empty session-msg">属主独占: {{ plcOwnerLabel }}</p>
        <p v-if="plc.sessionMsg" class="empty session-msg">{{ plc.sessionMsg }}</p>
        <p v-if="plc.statusBusy" class="empty">连接中… (首次启动 InoProShop, 会弹出窗口)</p>
        <p v-else-if="plc.sessionStatus?.manual_control" class="empty">用户已接管 PLC 会话; 释放后上位机再读取/编译</p>
        <p v-else-if="plc.statusError" class="empty err">连接失败: {{ plc.statusError }} —— 点击「连接」重新拉起</p>
        <p v-else-if="!plc.connected" class="empty">未连接 —— 点击「连接」启动 InoProShop</p>
        <template v-else>
          <!-- 加载/空态 -->
          <p v-if="plc.loadingPous" class="empty loading">加载中…</p>
          <p v-else-if="plc.pousError" class="empty err">加载失败: {{ plc.pousError }}</p>
          <p v-else-if="!plc.pous.length" class="empty">暂无 POU</p>
          <!-- 程序树渲染: 阶梯缩进, 子级恒比父级右一级; chevron 折叠, 程序节点点名进编辑器。
               行内嵌 chevron 真按钮 → 行级交互走 pressable (键盘可达); chev 钮 @keydown.stop 挡行级 Enter/Space -->
          <div>
            <div v-for="r in pouRows" :key="r.key" class="tree-row"
                 :class="{ active: r.openable && route.params.path === r.openPath }"
                 :style="{ paddingLeft: (r.depth * 14 + 8) + 'px' }" :title="r.path"
                 v-bind="pressable(() => onPlcRow(r))"
                 :aria-current="r.openable && route.params.path === r.openPath ? 'true' : undefined">
              <button v-if="r.has_children" type="button" class="btn-bare chev"
                      :aria-expanded="!isCollapsed(r.key)"
                      :aria-label="(isCollapsed(r.key) ? '展开 ' : '折叠 ') + r.name"
                      @click.stop="toggleCollapse(r.key)" @keydown.stop>{{ isCollapsed(r.key) ? '▸' : '▾' }}</button>
              <span class="chev" v-else aria-hidden="true"></span>{{ r.name }}
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 设备 -->
    <div v-else-if="section === 'nodes'">
      <!-- 设备参数 (相机/CNC/视觉): 未选节点的设备页落地 -->
      <ul>
        <li :class="{ active: !route.params.id }">
          <button type="button" class="btn-bare" :aria-current="!route.params.id ? 'true' : undefined"
                  @click="router.push('/nodes')">设备参数</button>
        </li>
      </ul>
      <!-- 全工站一键初始化: 逐站跑 *.init。单工站初始化在各工位节点详情页里 (层级刻意错开) -->
      <div class="repo-head">
        <span class="group-title">设备节点</span>
        <button class="mini act-refresh" :disabled="initAllBusy" @click="onInitAll"
                title="依次初始化拍照刮板/上样/展开(逐缸)/收集各工站与上下料位; 机械臂须停在 P1 安全位">
          {{ initAllBusy ? '初始化中…' : '⟳ 全工站初始化' }}
        </button>
      </div>
      <p v-if="!nodes.list.length" class="empty">暂无设备节点</p>
      <ul>
        <li v-for="n in nodes.list" :key="n.id" class="node-li" :class="{ active: route.params.id === n.id }">
          <button type="button" class="btn-bare" :aria-current="route.params.id === n.id ? 'true' : undefined"
                  @click="openNode(n.id)">
            <span class="health-dot" :class="n.health" role="img"
                  :title="healthText(n.health)" :aria-label="healthText(n.health)" />
            <span>{{ n.label }}</span>
          </button>
        </li>
      </ul>
    </div>

    <!-- 物料: 四类物料 + 记账流水, 每项一个子页 (/materials/<key>) -->
    <div v-else-if="section === 'materials'">
      <div class="group-title">物料种类</div>
      <ul>
        <li v-for="m in materialNav" :key="m.key"
            :class="{ active: materialCat === m.key }">
          <button type="button" class="btn-bare mat-btn" :title="m.hint"
                  :aria-current="materialCat === m.key ? 'true' : undefined" @click="openMaterial(m.key)">
            {{ m.label }}
            <small class="mat-hint">{{ m.hint }}</small>
          </button>
        </li>
        <li v-if="!materialCats.length" class="muted">拓扑加载中…</li>
      </ul>
    </div>

    <!-- 排程: 流程库 (流程 + 各自耗时); 点行加入中区选中的样品, 样品编辑在中区 -->
    <div v-else-if="section === 'planner'">
      <!-- 头部只留标题 + 小号 ⟳/⚙ (循「动作」栏 act-refresh 规格); 窗口/口径/清除全部 收进 ⚙ 设置弹窗 -->
      <div class="repo-head">
        <span class="group-title">流程耗时</span>
        <span class="tm-head-btns">
          <button class="mini act-refresh" :disabled="planner.loading"
                  :title="planner.loading ? '刷新中…' : '重新拉取统计'" aria-label="重新拉取统计"
                  @click="planner.loadStats()">⟳</button>
          <button class="mini act-refresh" title="耗时统计设置 (窗口 / 口径 / 清除全部记录)"
                  aria-label="耗时统计设置" aria-haspopup="dialog"
                  @click="timingSettingsOpen = true">⚙</button>
        </span>
      </div>

      <p v-if="planner.error" class="empty err">{{ planner.error }}</p>
      <p v-else-if="!plannerGroups.length" class="empty">
        {{ planner.loading ? '统计加载中…' : '暂无可排的流程' }}
      </p>
      <div v-for="g in plannerGroups" :key="g.title">
        <button type="button" class="btn-bare group-title clickable"
                :aria-expanded="!isCollapsed('tm:' + g.title)" @click="toggleCollapse('tm:' + g.title)">
          <span class="chev" aria-hidden="true">{{ isCollapsed('tm:' + g.title) ? '▸' : '▾' }}</span>{{ g.title }}
        </button>
        <ul v-show="!isCollapsed('tm:' + g.title)">
          <!-- 行级"加入样品"走 pressable; 明细/清除·撤销 收进右键与行尾 ⋯ 菜单 (⋯ @keydown.stop 挡行级 Enter/Space);
               基线徽标留在行上: 它是"该流程已被清除"的唯一常显信号, 不能藏进菜单 -->
          <li v-for="op in g.items" :key="op.name" class="tm-li" data-test="planner-op-row"
              :title="`点击加入样品「${planner.selectedSample ? planner.selectedSample.label : '(将自动新建)'}」`"
              v-bind="pressable(() => planner.addOpToSelected(op.name))"
              @contextmenu.prevent.stop="openPlannerOpMenu($event, op)">
            <span class="tm-name">{{ op.label }}</span>
            <small class="tm-dur" :class="{ none: !op.count }"
                   :title="plannerOpDurTitle(op)">{{ plannerOpDur(op) }}</small>
            <small v-if="op.baseline_ts" class="tm-base" title="已设统计基线: 只统计该时刻之后的运行">基线</small>
            <button type="button" class="row-more" aria-haspopup="menu" :aria-label="`更多操作: ${op.label}`"
                    @click.stop="openPlannerOpMenu($event, op)" @keydown.stop>⋯</button>
          </li>
        </ul>
      </div>
    </div>

    <!-- 调度 (第三层): 方案列表 + 新建 —— 方案定义段怎么组合、谁能和谁并行 -->
    <div v-else-if="section === 'schedule'">
      <div class="repo-head">
        <span class="group-title">调度方案</span>
        <button class="mini" @click="newSchedule">+ 新建</button>
      </div>
      <p v-if="scheduler.error" class="empty err">{{ scheduler.error }}</p>
      <p v-else-if="!scheduler.recipes.length" class="empty">暂无方案</p>
      <ul>
        <li v-for="r in scheduler.recipes" :key="r.name"
            :class="{ active: route.params.name === r.name }"
            :title="`${r.name} · ${r.segments.length} 段${r.default ? ' · 默认方案' : ''}`"
            v-bind="pressable(() => router.push(`/schedule/${r.name}`))">
          <span class="sch-batch-name">{{ r.label || r.name }}</span>
          <small v-if="r.default" class="muted" title="实验提交默认选它">默认</small>
          <small class="sch-batch-prog num">{{ r.segments.length }} 段</small>
        </li>
      </ul>
    </div>

    <!-- 实验 (串/并行批量): 固定导航 + 批次列表 -->
    <div v-else-if="section === 'scheduler'">
      <div class="group-title">实验</div>
      <ul>
        <li :class="{ active: schedulerSub === 'board' }" v-bind="pressable(() => router.push('/experiment'))">
          <span>运行看板</span>
        </li>
        <li :class="{ active: schedulerSub === 'submit' }" v-bind="pressable(() => router.push('/experiment/submit'))">
          <span>＋ 新建实验</span>
        </li>
      </ul>
      <div class="group-title">批次</div>
      <p v-if="scheduler.error" class="empty err">{{ scheduler.error }}</p>
      <p v-else-if="!scheduler.batches.length" class="empty">暂无批次</p>
      <ul>
        <li v-for="b in scheduler.batches" :key="b.batch_id" class="sch-batch-li"
            :class="{ active: route.params.sub === 'batch' && route.params.id === b.batch_id }"
            :title="`${b.name || b.batch_id} · ${b.status}`"
            v-bind="pressable(() => router.push(`/experiment/batch/${b.batch_id}`))">
          <span class="dot" :class="b.status" />
          <span class="sch-batch-name">{{ b.name || b.batch_id }}</span>
          <small class="sch-batch-prog num">{{ b.sample_done }}/{{ b.sample_total }}</small>
        </li>
      </ul>
    </div>

    <!-- 执行记录 -->
    <div v-else>
      <div class="run-head">
        <div class="group-title">执行记录</div>
        <input v-model="runFilterDate" type="date" class="run-date"
               aria-label="按日期筛选执行记录" title="只看某一天的运行" />
        <button v-if="runFilterDate" type="button" class="mini" @click="runFilterDate = ''">清除</button>
      </div>
      <p v-if="runFilterErr" class="empty err">{{ runFilterErr }}</p>
      <p v-else-if="!shownRuns.length" class="empty">
        {{ runFilterDate ? (runFilterLoading ? '筛选中…' : '该日无运行记录') : '暂无运行记录' }}
      </p>
      <ul>
        <li v-for="r in shownRuns" :key="r.run_id" class="run-li" :class="{ active: route.params.id === r.run_id }">
          <button type="button" class="btn-bare" :aria-current="route.params.id === r.run_id ? 'true' : undefined"
                  @click="openRun(r.run_id)">
            <span class="run-chip" :class="r.status">{{ runStatusLabel(r.status) }}</span>
            <span class="run-li-main">
              <span>{{ r.label || r.operation }}</span>
            </span>
          </button>
        </li>
      </ul>
    </div>

    <!-- 行菜单单例 (三类行共用) + 耗时设置弹窗 (均 Teleport 到 body, DOM 挂此处不影响层叠) -->
    <ContextMenu ref="menuRef" />
    <TimingSettingsModal :open="timingSettingsOpen" @close="timingSettingsOpen = false" />
  </div>
</template>

<style scoped>
.group-title.clickable { cursor: pointer; user-select: none; }
/* div→button 语义化后的占位补齐: 折叠头撑满整行 (点击区与原 div 一致), 保持左对齐 */
button.group-title.clickable { display: flex; width: 100%; text-align: left; }
/* 物料项按钮: 名 + 块级灰提示上下堆叠 (flex 会把提示挤到右侧), 覆写 .dock li > .btn-bare 的 flex */
.dock li > .btn-bare.mat-btn { display: block; }
/* 版本行 (div→button 后 flex 化吃掉词间空格): 用 gap 还原 "#rev 时间戳" 的间距 */
.versions .ver { gap: 6px; }
/* 排程「流程耗时」栏: 每行 = 名 / 耗时徽标 / 基线徽标 / 行尾 ⋯ (设置区已收进 ⚙ 弹窗) */
.tm-head-btns { margin-left: auto; display: inline-flex; gap: 4px; }
.tm-li { display: flex; align-items: center; gap: 6px; }
.tm-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tm-dur { flex: 0 0 auto; color: var(--subtle); font-variant-numeric: tabular-nums; }
.tm-dur.none { opacity: 0.6; }
.tm-base { flex: 0 0 auto; color: var(--warn, #c80); border: 1px solid currentColor; border-radius: 8px; padding: 0 4px; font-size: 10px; }
/* PLC 程序段标题: 折叠开关 (chevron+标题) 在左, 连接按钮靠右 (@click.stop 不触发折叠) */
.plcsec-head { display: flex; align-items: center; gap: 6px; }
.plcsec-head .mini { margin-left: auto; }
/* 「动作」栏刷新按钮: 靠右 + 缩小贴近「动作」标题文字 (仅本按钮, 不动共享 .mini) */
.repo-head .act-refresh { margin-left: auto; align-self: center; padding: 1px 6px; font-size: var(--fs-11); color: var(--subtle); }
.session-strip { display: flex; align-items: center; gap: 6px; padding: 6px 8px; margin: 4px 0 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); }
.session-strip.manual { border-color: var(--warn); }
.session-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); flex: 0 0 auto; }
.session-dot.ok { background: var(--ok); }
.session-dot.warn { background: var(--warn); }
.session-text { min-width: 0; flex: 1; font-size: var(--fs-12); font-weight: 700; color: var(--text); }
.session-strip .mini { flex: 0 0 auto; }
.session-strip .mini.ok { border-color: var(--ok); color: var(--ok); }
.session-msg { margin-top: 0; }
/* 点位树三级阶梯缩进 (类别 0 -> 工位 +1 -> 点位 +2): 工位标题与点位项逐级右移, 层级清晰 */
.group-title.sub { padding-left: 16px; font-weight: 600; color: var(--subtle); }
/* 点位栏两个平级大节 (标定 / 存储): 加粗 + 下分隔线, 与树内分组标题区分 */
/* 点位栏的点位类别 (机器人/PLC伺服): 比所属大节右一档, 仍浅于工位的 16px, 叶子缩进不受影响 */
.group-title.cat { padding-left: 8px; }
.dock li.pt-leaf { padding-left: 34px; }
/* 流程组内子栏 (ui.subgroup, 机械臂按工位): 子栏头复用 .sub 的 16px, 桶内条目比默认 10px 再右移一档 */
.dock ul.sub-items li { padding-left: 26px; }
.chev { display: inline-block; width: 1em; color: var(--muted); }
/* 分组计数徽标: 必须与标题视觉分离 —— 紧贴时 "工具更换区" + "10" 会被读成 "工具更换区10" (伪区号) */
.cnt { color: var(--muted); font-size: var(--fs-11); font-weight: 600; margin-left: 6px; padding: 0 6px; border-radius: 999px; background: var(--hover); }
/* 侧栏树分组标题不转大写: 分组名已是中文, 且工位 key 回退时须显真名 (area-12 而非 AREA-12) */
.dock .group-title.cat, .dock .group-title.sub { text-transform: none; }
.empty.err { color: var(--bad); }
/* PLC/设备 树行: 缩进经内联 padding-left 按 depth 计算 (子级恒比父级右一级) */
.tree-row { padding: 6px 10px; border-radius: 6px; cursor: pointer; color: var(--text); font-size: var(--fs-13); line-height: 1.35; overflow-wrap: anywhere; user-select: none; }
.tree-row:hover { background: var(--hover); }
.tree-row.active { background: var(--accent); color: var(--on-accent); font-weight: 600; }
/* 物料种类导航: 名 + 一行灰提示 */
.mat-hint { display: block; font-size: 10px; color: var(--muted); line-height: 1.3; margin-top: 1px; }
li.active .mat-hint { color: var(--on-accent); opacity: 0.85; }
/* 调度栏批次行: 状态点 + 名 + 完成进度 */
.sch-batch-li { display: flex; align-items: center; gap: 6px; }
.sch-batch-li .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dot-idle); flex: none; }
.sch-batch-li .dot.RUNNING { background: var(--warn); animation: pulse 1.2s ease-in-out infinite; }
.sch-batch-li .dot.QUEUED { background: var(--accent); }
.sch-batch-li .dot.PAUSED { background: var(--warn); }
.sch-batch-li .dot.COMPLETED { background: var(--ok); }
.sch-batch-li .dot.ABORTED { background: var(--bad); }
.sch-batch-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sch-batch-prog { color: var(--muted); font-size: var(--fs-11); }
/* 执行记录标题行: 标题居左 + 日期筛选靠右同行 (原生 date 控件, 日历图标随全局 color-scheme) + 条件清除钮;
   group-title 的外边距上提到容器, dock 拖窄时输入框可收缩 */
.run-head { display: flex; align-items: center; gap: 6px; margin: 10px 0 5px; }
.run-head .group-title { margin: 0; flex: 0 0 auto; }
.run-head .run-date { flex: 0 1 150px; min-width: 90px; margin-left: auto; padding: 2px 6px; border: 1px solid var(--border); border-radius: var(--radius-sm); }
</style>
