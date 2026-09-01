<script setup>
/**
 * 功能: 材质工作台 —— 对着实物照片把每种材质调到位.
 *
 * 布局(2026-07-31 按用户要求改版):
 *   左栏 = **零件层级树**: 与装配台同一棵树组件, 按成品模型(machine.glb)的真实层级展示
 *          (工位 → 运动件子层级 + 静态合并件). 点零件 → 取景 + 高亮 + 自动切到它的材质;
 *          三维里点零件, 树会自动展开定位 —— 你看照片发现某处不对, 点上去就知道该调哪种材质.
 *   右栏 = **材质类型 + 参数**: 上面是全部材质(中文名), 点一种高亮它的所有零件;
 *          下面是选中材质的参数编辑器, 拖滑块**实时**生效.
 *
 * 材质编辑粒度仍是"材质类"(MAT_*): 同一零件的全部实例天然共享材质, 树只是导航方式.
 *
 * 为什么调色放这儿而不是 Blender:
 *   1. 调色是连续迭代, 走 Blender 每次微调要重跑 60~80 秒, 摊销不掉;
 *   2. 浏览器里看到的**就是最终效果**(同一渲染器、同一套后处理), Blender 的 EEVEE 不是;
 *   3. 我们只用 glTF PBR 那几个参数, three 与 Blender 一一对应, 走网页不损失表达力.
 *
 * 分工: Blender 决定「谁用哪种材质」(分类, 靠规则), 网页决定「那种材质长什么样」(观感, 靠眼睛).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'

import { applyRobotHomePose } from '../anim/robotHomePose.js'
import ContextMenu from '../common/ContextMenu.vue'
import { createRightClickTracker } from '../common/rightClick.js'
import * as api from '../workbench/authoringApi.js'
import { PartIndex } from '../workbench/PartIndex.js'
import PartTree from '../workbench/PartTree.vue'
import RebuildPanel from '../workbench/RebuildPanel.vue'
import { SelectionModel } from '../workbench/selectionModel.js'
import { SceneManager } from '../twin/scene/SceneManager.js'
import ViewToolbar from '../twin/scene/ViewToolbar.vue'
import { ViewTools } from '../twin/scene/ViewTools.js'
import DisplayPanel from '../twin/panels/DisplayPanel.vue'
import { BboxHighlighter } from './bboxHighlight.js'
import { GroupModel } from './groupModel.js'
import GroupPanel from './GroupPanel.vue'
import { IsolateModel } from './isolateModel.js'
import {
  baseName,
  buildMemberIndex,
  familyName,
  groupByFamily,
  loadMemberData,
  rankCandidates,
  resolveMembers,
} from './memberIndex.js'
import StaticMembersCard from './StaticMembersCard.vue'
import { labelOf, stationLabelOf } from './labels.js'
import MaterialEditor from './MaterialEditor.vue'
import { MaterialsScene } from './MaterialsScene.js'
import { OverrideModel } from './overrideModel.js'
import QuickActions from './QuickActions.vue'
import UngroupedCard from './UngroupedCard.vue'
import {
  patchAppearanceOverrides,
  patchPartGroups,
  patchPartIsolate,
  patchPartOverrides,
  readAppearanceOverrides,
  readPartGroups,
  readPartIsolate,
  readPartOverrides,
} from './yamlPatch.js'

/** 材质台加载**清理后**的模型 —— 它才带最终的那二十来种材质 */
const MODEL_URL = '/api/3d/assets/models/machine.glb'

const containerRef = ref(null)
const manager = shallowRef(null)
const scene = shallowRef(null)
const tools = shallowRef(null)
const model = shallowRef(new OverrideModel())
/** 零件级覆盖模型(键=零件 glTF 原名); 与材质类覆盖同构, 分开存两段 YAML */
const partModel = shallowRef(new OverrideModel())
/** 材质组模型(工程师定义的合并规则; 键=组名) */
const groupModel = shallowRef(new GroupModel())
/** 孤立清单模型(「拆出为独立零件」的意图; 存零件 base 名, 重跑后生效) */
const isoModel = shallowRef(new IsolateModel())
/** 组面板当前展开编辑的组名 */
const activeGroup = ref('')
/** 组面板组件引用(右键菜单要打开它的新建输入框) */
const groupPanelRef = ref(null)

/** 观察工具的开关状态; helpersPresent 由模型自检(管线可能已停用示意体生成) */
const view = ref({ xray: false, wireframe: false, helpers: true, hidden: 0, helpersPresent: false })
/** 显示设置面板开关与运行时统计(负载条数据源) */
const showDisplay = ref(false)
const stats = ref({})
/** 三维里点到的零件(用于反查材质) */
const pickedPart = ref('')
/** 零件多选模型(Ctrl 加选; 复用装配台的 SelectionModel, 撤销栈白拿) */
const partSel = shallowRef(new SelectionModel())
/** 右键菜单状态与单击/拖拽判定器 */
const menu = ref(null)
const rightClick = createRightClickTracker()

const loading = ref(true)
const progress = ref(0)
const error = ref('')
const authoringAvailable = ref(false)
const saving = ref(false)
const message = ref('')
const selected = ref('')

/** 触发视图重算的版本号(覆盖模型是普通对象, 不走 Vue 响应式) */
const tick = ref(0)
/** 成品模型的零件索引(加载后固定), 供左侧层级树与三维反查用 */
const partIndex = shallowRef(null)
/** 层级树组件, 三维点选后调它的 reveal() 定位 */
const treeRef = ref(null)
/** 单选语义的零件键: 恰好选中 1 个时为它, 多选/无选为空(零件覆盖卡只在单选时出现) */
const selectedPartKey = computed(() => {
  tick.value
  const keys = partSel.value.selected
  return keys.size === 1 ? [...keys][0] : ''
})
/** 零件键 -> 材质名 的缓存(模型加载后不变), 供树的色点用 */
const partMaterialName = new Map()
/** material_semantics.yaml 原文; 保存时在其上打补丁以保住注释 */
let semanticsText = ''
let disposed = false

const materials = computed(() => {
  tick.value
  return scene.value?.list() || []
})

/** 材质列表搜索词(63 种材质翻找是真实痛点) */
const matSearch = ref('')

/** 过滤后的材质列表: 中文名与 MAT_* 名都参与匹配 */
const filteredMaterials = computed(() => {
  const term = matSearch.value.trim().toLowerCase()
  if (!term) return materials.value
  return materials.value.filter(
    (item) =>
      item.name.toLowerCase().includes(term) || labelOf(item.name).toLowerCase().includes(term),
  )
})

/** 材质名 -> 当前基色, 供物料行的小色块 */
const materialColor = computed(() => {
  const map = new Map()
  for (const item of materials.value) map.set(item.name, item.current.base_color || '#808080')
  return map
})

const overriddenCount = computed(() => {
  tick.value
  return model.value.entries.size
})

const currentPatch = computed(() => {
  tick.value
  return selected.value ? model.value.get(selected.value) : {}
})

const currentEntry = computed(() =>
  materials.value.find((item) => item.name === selected.value) || null,
)

const currentBaseline = computed(() =>
  selected.value && scene.value ? scene.value.baseline(selected.value) : {},
)

/** 层级树的选中集(多选; PartTree 的 isSelected 做成员测试, 渲染层零改动) */
const selectedKeySet = computed(() => {
  tick.value
  return partSel.value.selected
})

/**
 * 零件覆盖的目标解析: 选中树节点 → 三态之一.
 *
 * machine.glb 的静态几何已按 工位×材质 合并成 STATIC_MAT_* 块, 块内单件不可寻址,
 * 只有保护前缀子树(轴/机械臂/工具/耗材等)保留零件级粒度. 三态:
 *   part     —— 纯可寻址零件, 实时编辑零件覆盖;
 *   merged   —— 恰好一个 STATIC 块, 出成员清单卡(附 staticMesh 供取基线);
 *   assembly —— 子树混着合并块与其他(如 ST_ 工位根), 出中性提示.
 * 旧版把后两态混为一谈(子树含 STATIC 即 merged), 选中工位会弹出"0 件"的成员卡.
 */
const partTarget = computed(() => {
  tick.value
  const key = selectedPartKey.value
  if (!key) return null
  const info = partIndex.value?.get(key)
  if (!info) return null
  const meshes = []
  const staticMeshes = []
  info.object.traverse((child) => {
    if (!child.isMesh) return
    if (/^STATIC_/.test(child.name || '')) staticMeshes.push(child)
    else meshes.push(child)
  })
  if (meshes.length && !staticMeshes.length) {
    const savedName = partIndex.value.savedNameOf?.(key) ?? info.name
    // 覆盖按**实例族**生效: 同一零件的多个装配实例(侧门-1/侧门-2)拆出后各自
    // 有专属材质, 只改一个会出现"两扇门不一样"; meshes 取全族, 写盘逐实例写键
    const familyNames = soloFamilyNames(savedName)
    const familyMeshes =
      familyNames.length > 1 ? familyNames.flatMap((n) => meshesForSavedName(n)) : meshes
    return {
      kind: 'part',
      merged: false,
      info,
      meshes: familyMeshes.length ? familyMeshes : meshes,
      savedName,
      familyNames,
    }
  }
  if (staticMeshes.length === 1 && !meshes.length) {
    return { kind: 'merged', merged: true, info, staticMesh: staticMeshes[0] }
  }
  if (!meshes.length && !staticMeshes.length) return null
  return { kind: 'assembly', merged: false, info }
})

/** 零件覆盖编辑器的数据流(仅可编辑目标时有值) */
const partPatch = computed(() => {
  tick.value
  const target = partTarget.value
  return target?.kind === 'part' ? partModel.value.get(target.savedName) : {}
})
const partBaseline = computed(() => {
  tick.value
  const target = partTarget.value
  return target?.kind === 'part' ? scene.value?.partBaseline(target.meshes) || {} : {}
})
const partCurrent = computed(() => {
  tick.value
  const target = partTarget.value
  return target?.kind === 'part' ? scene.value?.partSnapshot(target.meshes) || {} : {}
})
const partClassName = computed(() => {
  tick.value
  const target = partTarget.value
  return target?.kind === 'part' ? scene.value?.partClassNameOf(target.meshes) || '' : ''
})

/**
 * 功能: 千分位格式化.
 * @param {number} value 数值
 * @returns {string} 结果
 */
function fmt(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}

/**
 * 功能: 层级树行的显示名 —— 工位与静态合并块(STATIC_<材质>)翻译成人话.
 * @param {object} item 零件索引信息
 * @returns {string} 显示名
 */
function nodeLabel(item) {
  const name = item.name.replace(/\.\d{3}$/, '')
  if (name.startsWith('ST_')) return stationLabelOf(name)
  if (name.startsWith('STATIC_MAT')) {
    return `静态合并件 · ${labelOf(name.slice('STATIC_'.length))}`
  }
  return item.chinese || name
}

/**
 * 功能: 层级树行的色点 —— 该节点子树第一个网格的材质基色(实时跟随调色).
 * @param {string} key 零件索引键
 * @returns {string|null} CSS 颜色
 */
function nodeDot(key) {
  let matName = partMaterialName.get(key)
  if (matName === undefined) {
    matName = ''
    const info = partIndex.value?.get(key)
    info?.object?.traverse((child) => {
      if (matName || !child.isMesh || !child.material) return
      const list = Array.isArray(child.material) ? child.material : [child.material]
      // 零件覆盖的克隆材质带 @part 后缀, 色点仍按材质类归色
      matName = (list[0]?.name || '').replace(/@part$/, '')
    })
    partMaterialName.set(key, matName)
  }
  return matName ? materialColor.value.get(matName) || null : null
}

/**
 * 功能: 选中一种材质并高亮它用到的全部零件.
 * @param {string} name 材质名
 * @returns {void}
 */
function pick(name) {
  selected.value = name
  pickedPart.value = ''
  partSel.value.clearSelection()
  const count = scene.value?.select(name) ?? 0
  message.value = `「${labelOf(name)}」用在 ${fmt(count)} 个零件上`
  tick.value += 1
}

/**
 * 功能: 收集一个零件键的子树网格.
 * @param {string} key 零件索引键
 * @returns {Array} 网格数组
 */
function meshesOfKey(key) {
  const info = partIndex.value?.get(key)
  const meshes = []
  info?.object?.traverse((child) => {
    if (child.isMesh) meshes.push(child)
  })
  return meshes
}

/**
 * 功能: 把当前选中集刷成描边高亮(多选=并集).
 * @returns {void}
 */
function highlightSelection() {
  const meshes = []
  for (const key of partSel.value.selected) meshes.push(...meshesOfKey(key))
  manager.value?.effects?.setSelected(meshes)
}

/**
 * 功能: 点层级树里的一个零件 —— 选中(Ctrl 加选)+高亮; 单选时取景并切到它的材质.
 *
 * 与 pick 的差别: 这里只高亮**选中的零件**而不是同材质的全部零件, 否则你点了
 * 一个接头, 满屏几十个接头一起亮, 反而看不清点的是哪个.
 *
 * @param {string} key 零件索引键
 * @param {MouseEvent} [event] 原始点击事件(读修饰键)
 * @returns {void}
 */
function focusNode(key, event) {
  const info = partIndex.value?.get(key)
  if (!info) return
  const meshes = meshesOfKey(key)
  if (!meshes.length) return

  const additive = Boolean(event && (event.ctrlKey || event.metaKey || event.shiftKey))
  if (additive) partSel.value.toggle(key)
  else partSel.value.select([key])
  tick.value += 1
  highlightSelection()

  if (additive) {
    message.value = `已选中 ${partSel.value.selected.size} 个零件(Ctrl 点击增删)`
    return
  }
  pickedPart.value = info.name.replace(/\.\d{3}$/, '')
  tools.value?.frameObjects(meshes)
  const list = Array.isArray(meshes[0].material) ? meshes[0].material : [meshes[0].material]
  const matName = (list[0]?.name || '').replace(/@part$/, '')
  if (matName.startsWith('GROUP_')) {
    activeGroup.value = matName.slice('GROUP_'.length)
    message.value = `「${nodeLabel(info)}」属于材质组「${activeGroup.value}」`
  } else if (matName && matName !== selected.value) {
    selected.value = matName
    tick.value += 1
    message.value = `「${nodeLabel(info)}」用的是「${labelOf(matName)}」`
  } else {
    message.value = `「${nodeLabel(info)}」用的是「${labelOf(matName)}」`
  }
}

/**
 * 功能: 把镜头飞到当前材质覆盖的零件.
 * @returns {void}
 */
function frame() {
  if (!selected.value) return
  const meshes = scene.value?.meshesOf(selected.value) || []
  if (!tools.value?.frameObjects(meshes)) message.value = '该材质没有可取景的几何'
}

/**
 * 功能: 改一个字段并立刻应用到三维.
 * @param {string} key 字段名
 * @param {string|number|null} value 值
 * @returns {void}
 */
function change(key, value) {
  if (!selected.value) return
  model.value.set(selected.value, key, value)
  scene.value?.apply(selected.value, model.value.get(selected.value))
  // 类是组与零件覆盖的"底": 先重放底为该类的组, 再重放零件克隆(件底可能是组)
  scene.value?.reapplyGroupsFor(selected.value)
  scene.value?.reapplyPartsFor(selected.value)
  tick.value += 1
}

/**
 * 功能: 改零件覆盖的一个字段并实时生效(仅可寻址零件).
 * @param {string} key 字段名
 * @param {string|number|null} value 值
 * @returns {void}
 */
function changePart(key, value) {
  const target = partTarget.value
  if (target?.kind !== 'part') return
  // 整族同参: 同一零件的每个装配实例各写一条键(拆出后它们是各自独立的材质)
  for (const name of target.familyNames) partModel.value.set(name, key, value)
  scene.value?.applyPart(target.meshes, partModel.value.get(target.savedName))
  tick.value += 1
}

/**
 * 功能: 清掉当前零件(整族)的全部覆盖.
 * @returns {void}
 */
function resetPart() {
  const target = partTarget.value
  if (target?.kind !== 'part') return
  for (const name of target.familyNames) partModel.value.reset(name)
  scene.value?.applyPart(target.meshes, {})
  message.value = `已还原「${nodeLabel(target.info)}」的零件覆盖`
  tick.value += 1
}

/**
 * 功能: 给当前零件(整族)应用材质预设(单步可撤销).
 * @param {{label: string, patch: object}} preset 预设
 * @returns {void}
 */
function applyPartPreset(preset) {
  const target = partTarget.value
  if (target?.kind !== 'part') return
  let n = 0
  for (const name of target.familyNames) n = partModel.value.setMany(name, preset.patch) || n
  if (!n) return
  scene.value?.applyPart(target.meshes, partModel.value.get(target.savedName))
  message.value = `已给「${nodeLabel(target.info)}」应用预设「${preset.label}」`
  tick.value += 1
}

/**
 * 功能: 零件覆盖的按住对比.
 * @param {boolean} active 是否按下
 * @returns {void}
 */
function comparePart(active) {
  const target = partTarget.value
  if (target?.kind !== 'part') return
  scene.value?.applyPart(
    target.meshes,
    active ? {} : partModel.value.get(target.savedName),
  )
}

/**
 * 功能: 把零件基色恢复成其材质类名里的 CAD 量化色.
 * @param {string} hex '#RRGGBB'
 * @returns {void}
 */
function applyPartCadColor(hex) {
  changePart('base_color', hex)
  message.value = `已恢复 CAD 原色 ${hex}`
}

// -- 材质组(工程师定义合并规则) ---------------------------------------------

/**
 * 功能: 零件键 → glTF 原名(写 YAML 用).
 * @param {string} key 零件索引键
 * @returns {string} 原名
 */
function savedNameOfKey(key) {
  return partIndex.value?.savedNameOf?.(key) ?? key
}

/**
 * 独立零件的实例族索引: 族名 -> Set<零件原名>(模型加载后固定, mount 时建一次).
 *
 * 合并块内成员的族靠 memberIndex.byFamily; 已独立(拆出/受保护)的零件不在那份
 * 数据里, 需要从场景索引另建一份 —— 两条路合起来才能保证"改这个零件"永远整族生效.
 */
const soloFamilyIndex = shallowRef(null)

/**
 * 功能: 建立独立零件的实例族索引.
 * @returns {Map<string, Set<string>>|null} 族名 -> 原名集合
 */
function buildSoloFamilyIndex() {
  const index = partIndex.value
  if (!index) return null
  const map = new Map()
  for (const key of index.allNames) {
    const info = index.get(key)
    if (!info || info.childNames?.length) continue
    if (/^STATIC_/.test(info.name || '')) continue
    const saved = savedNameOfKey(key)
    const family = familyName(saved)
    if (!map.has(family)) map.set(family, new Set())
    map.get(family).add(saved)
  }
  return map
}

/**
 * 功能: 求一个已独立零件所属实例族的全部原名.
 * @param {string} savedName 零件原名
 * @returns {string[]} 族内原名(至少含自身)
 */
function soloFamilyNames(savedName) {
  const set = soloFamilyIndex.value?.get(familyName(savedName))
  if (!set || !set.size) return [savedName]
  return set.has(savedName) ? [...set] : [savedName, ...set]
}

/**
 * 功能: 原名 → 可寻址网格(过滤合并块; 合并块内成员保存后重跑才生效).
 * @param {string} savedName 零件原名
 * @returns {Array} 网格数组
 */
function meshesForSavedName(savedName) {
  const keys = partIndex.value?.keysForSavedName?.(savedName) || []
  const meshes = []
  for (const key of keys) {
    const info = partIndex.value.get(key)
    info?.object?.traverse((child) => {
      if (child.isMesh && !/^STATIC_/.test(child.name || '')) meshes.push(child)
    })
  }
  return meshes
}

/**
 * 功能: 数据 → 场景的组预览全量对账(建组/改成员/解散/撤销/恢复后调用).
 *
 * 两遍式: 先把全部"不再属于"的成员移出(含被单一隶属规则evict的), 再逐组重放 ——
 * 顺序保证被换组的网格先还原到类材质, 才能被新组正确接管.
 * @returns {void}
 */
function syncAllGroupPreviews() {
  const kit = scene.value
  const model = groupModel.value
  if (!kit) return
  const wanted = new Set(model.names())

  // 第一遍: 解散已删的组; 剔除各组的过时成员
  for (const name of kit.groupNames()) {
    if (!wanted.has(name)) {
      kit.dissolveGroup(name)
      continue
    }
    const want = new Set()
    for (const part of model.partsOf(name)) {
      for (const mesh of meshesForSavedName(part)) want.add(mesh)
    }
    const stale = kit.groupMeshes(name).filter((mesh) => !want.has(mesh))
    if (stale.length) kit.removeGroupMember(name, stale)
  }

  // 第二遍: 逐组重放(底 = parts 首个可解析成员的类, 与管线同规则)
  for (const name of model.names()) {
    let meshes = []
    let baseClass = kit.groupBaseClass(name)
    for (const part of model.partsOf(name)) {
      const partMeshes = meshesForSavedName(part)
      if (partMeshes.length && !baseClass) baseClass = kit.partClassNameOf(partMeshes)
      meshes = meshes.concat(partMeshes)
    }
    if (meshes.length && baseClass) {
      kit.applyGroup(name, meshes, model.getParams(name), baseClass)
    }
  }
  if (activeGroup.value && !wanted.has(activeGroup.value)) activeGroup.value = ''
  tick.value += 1
}

/** 组面板的投影数组 */
const groupsView = computed(() => {
  tick.value
  const model = groupModel.value
  const kit = scene.value
  return model.names().map((name) => {
    const parts = model.partsOf(name)
    const base = kit?.groupBaseClass(name) || ''
    return {
      name,
      parts,
      patch: model.getParams(name),
      current: kit?.groupSnapshot(name) || {},
      baseline: base ? kit.classSnapshot(base) : {},
      unaddressable: parts.filter((part) => !meshesForSavedName(part).length).length,
    }
  })
})

/**
 * 功能: 用当前选中零件新建材质组.
 * @param {string} name 组名
 * @returns {void}
 */
function createGroupFromSelection(name) {
  const parts = [...partSel.value.selected].map(savedNameOfKey)
  if (!groupModel.value.createGroup(name, parts)) {
    message.value = `建组失败: 组名为空/重名或没有选中零件`
    return
  }
  syncAllGroupPreviews()
  activeGroup.value = name
  message.value = `已建组「${name}」(${parts.length} 件); 组内共享一个材质, 重跑后合并为同一块`
}

/**
 * 功能: 把当前选中零件加入既有组.
 * @param {string} name 组名
 * @returns {void}
 */
function addSelectionToGroup(name) {
  const parts = [...partSel.value.selected].map(savedNameOfKey)
  // 入组与拆出互斥(与管线清洗期同一裁决): 用户最新意图赢, 自动取消拆出标记
  const freed = parts.filter((part) => isoModel.value.remove(part)).length
  const n = groupModel.value.addParts(name, parts)
  syncAllGroupPreviews()
  activeGroup.value = name
  message.value =
    (n ? `已把 ${n} 件加入组「${name}」` : '选中零件均已在该组') +
    (freed ? `; ${freed} 件已自动取消拆出标记(入组优先)` : '')
}

/**
 * 功能: 把成员移出组.
 * @param {string} name 组名
 * @param {string} part 成员原名
 * @returns {void}
 */
function removeMemberFromGroup(name, part) {
  groupModel.value.removePart(name, part)
  syncAllGroupPreviews()
  message.value = `已把「${part}」移出组「${name}」`
}

/**
 * 功能: 解散组.
 * @param {string} name 组名
 * @returns {void}
 */
function deleteGroup(name) {
  groupModel.value.removeGroup(name)
  syncAllGroupPreviews()
  message.value = `已解散组「${name}」, 成员回到各自材质类`
}

// -- STATIC 合并块成员反查(A5) --------------------------------------------

/** 成员元数据索引(buildMemberIndex 产物); null=两个数据源都拿不到(整体降级) */
const memberIdx = shallowRef(null)
/** 成员级覆盖编辑目标(合并块内成员, 无实时预览): {name, baseline} | null */
const memberEdit = ref(null)
/** 成员清单卡里要高亮定位的成员 base 名(右键"在成员清单中定位"设置) */
const memberFocus = ref('')
/** 成员包围盒线框高亮器(模型加载后建立; 不走响应式) */
let highlighter = null

/**
 * 功能: 解析某节点(STATIC 块)的成员清单 —— 沿 parent 链找 ST_ 工位根,
 *       交给 memberIndex.resolveMembers 做三级兜底键匹配.
 * @param {object} info PartIndex 的节点信息
 * @returns {Array|null} 归一成员数组; 数据源缺失返回 null
 */
function membersOfInfo(info) {
  const index = memberIdx.value
  if (!index || !info) return null
  // 键用 Blender 最终名(= origName, 保留 .001 点号)
  let station = info
  let guard = 0
  while (station && !/^ST_/.test(station.name) && guard < 20) {
    station = partIndex.value?.get(station.parentName) || null
    guard += 1
  }
  return resolveMembers(
    index,
    station ? station.origName || station.name : '',
    info.origName || info.name,
    station?.name || '',
    info.name,
  )
}

/** 当前选中合并块的成员清单(null=数据源没有) */
const staticMembers = computed(() => {
  tick.value
  const target = partTarget.value
  if (target?.kind !== 'merged') return null
  return membersOfInfo(target.info)
})

/** 成员清单按实例族聚合(卡片按"零件"而非"实例"呈现, 免得只拆走一半) */
const staticFamilies = computed(() => {
  tick.value
  return groupByFamily(staticMembers.value)
})

/**
 * 当前合并块所用材质类的波及面: 该类共用在几处几何、其中几处在本块之外.
 *
 * 合并块只能靠"改材质类"整块调观感, 而材质类通常还被别的零件共用 —— 不说清楚
 * 就会出现"我只想改把手, 结果门也变了"(用户实际踩过). 有块外用户时给警示.
 */
const blockClassScope = computed(() => {
  tick.value
  const target = partTarget.value
  if (target?.kind !== 'merged' || !target.staticMesh) return { total: 0, outside: 0 }
  const className = scene.value?.partClassNameOf([target.staticMesh]) || ''
  const meshes = className ? scene.value?.meshesOf(className) || [] : []
  return {
    total: meshes.length,
    outside: meshes.filter((mesh) => mesh !== target.staticMesh).length,
  }
})

// 离开合并块选中时收起成员编辑卡与定位高亮
watch(
  () => partTarget.value?.kind,
  (kind) => {
    if (kind !== 'merged') {
      memberEdit.value = null
      memberFocus.value = ''
    }
  },
)

/**
 * 功能: 给合并块内成员开单件覆盖编辑(无实时预览, 保存重跑后生效).
 * @param {string} name 成员原名(内部剥 .00N —— 写盘键必须是 base 名)
 * @returns {void}
 */
function editStaticMember(name) {
  const target = partTarget.value
  // 基线 = 该块材质类的当前值(成员重跑前与块同色, 这是最贴近的"原值")
  const className = target?.staticMesh ? scene.value?.partClassNameOf([target.staticMesh]) : ''
  memberEdit.value = {
    // 编辑目标是"零件", 补丁写给族内每个实例 —— 同一零件的多个装配实例
    // 观感必然一致, 只写一个会出现"两扇门不一样"
    family: familyName(name),
    instances: familyInstancesOf(name),
    name: baseName(name),
    baseline: className ? scene.value.classSnapshot(className) : {},
  }
}

/** 已标拆出的 base 名集合(成员卡/树行画徽标用; 变更全经 tick 驱动) */
const isolatedNameSet = computed(() => {
  tick.value
  return new Set(isoModel.value.names)
})

/**
 * 功能: 悬浮成员行 → 包围盒线框指认某成员在哪(传 null 收起).
 * @param {object|null} member 归一成员
 * @returns {void}
 */
function hoverMember(member) {
  if (!member) {
    highlighter?.hide()
    return
  }
  const list = Array.isArray(member) ? member : [member]
  const dashed = list.every((m) => isoModel.value.has(m.name))
  highlighter?.show(list, { dashed })
}

/** 归属筛选 chips(树顶): 键与 ownershipOf 的返回值对应 */
const OWNERSHIP_FILTERS = [
  { key: 'group', label: '材质组' },
  { key: 'static', label: '静态合并' },
  { key: 'solo', label: '独立散件' },
]

/**
 * 功能: 树行归属判定(只归类叶子行, 避免父子重复计入筛选).
 * @param {string} key 零件索引键
 * @returns {string} group | static | solo | ''(不参与筛选)
 */
function ownershipOf(key) {
  const info = partIndex.value?.get(key)
  if (!info || info.childNames?.length) return ''
  if (/^STATIC_/.test(info.name)) return 'static'
  return groupModel.value.groupOfPart(savedNameOfKey(key)) ? 'group' : 'solo'
}

/**
 * 功能: 树行的虚拟成员提供者 —— 只有 STATIC 合并块行返回成员清单.
 * @param {object} item PartIndex 节点信息
 * @returns {Array|null} 成员数组
 */
function treeMembersOf(item) {
  if (!/^STATIC_/.test(item?.name || '')) return null
  const families = groupByFamily(membersOfInfo(item))
  if (!families) return null
  // 树里也按零件列(同一零件的多个实例合成一行, 行名带 ×N), 与成员卡同口径
  return families.map((row) => ({
    name: row.members.length > 1 ? `${row.family} ×${row.members.length}` : row.family,
    tris: row.tris,
    family: row.family,
    members: row.members,
  }))
}

/**
 * 功能: 树内成员行点击 —— 选中所属合并块并在右栏成员卡里定位该零件.
 * @param {string} key 合并块的索引键
 * @param {object} row 族行
 * @returns {void}
 */
function focusTreeMember(key, row) {
  partSel.value.select([key])
  tick.value += 1
  highlightSelection()
  revealMemberInCard(row.family)
}

/**
 * 功能: 树内成员行悬浮 —— 亮出该零件全部实例的包围盒线框.
 * @param {string} key 合并块的索引键(未用, 保持回调签名)
 * @param {object|null} row 族行
 * @returns {void}
 */
function treeMemberHover(key, row) {
  hoverMember(row ? row.members : null)
}

/**
 * 功能: 树内成员行徽标 —— 拆出(含"只拆了一半")/入组状态一眼可见.
 * @param {object} row 族行
 * @returns {string} 徽标文本
 */
function treeMemberBadge(row) {
  const marked = row.members.filter((m) => isoModel.value.has(m.name)).length
  if (marked) return marked === row.members.length ? '拆' : '拆半'
  return groupModel.value.groupOfPart(baseName(row.members[0].name)) ? '组' : ''
}

/** 05 报告的绘制调用现状 {used, max}(mount 时读一次, 预算预估用) */
const reportStats = shallowRef(null)

/** 保存/重跑面板的待生效摘要: 哪些改动要重跑才能落地 + 绘制调用预算预估 */
const pendingSummary = computed(() => {
  tick.value
  const items = []
  // 拆出: 只统计仍在合并块里的名字 —— 已重跑固化的条目不再是"待生效"
  const idx = memberIdx.value
  let pendingIso = 0
  for (const base of isoModel.value.names) {
    if (!idx || idx.byBase.has(base)) pendingIso += 1
  }
  if (pendingIso) items.push({ label: '拆出', count: pendingIso })
  // 成员覆盖: 键当前无可寻址网格(还融在块里), 重跑后才生效
  let pendingOverride = 0
  for (const name of partModel.value.entries.keys()) {
    if (!meshesForSavedName(name).length) pendingOverride += 1
  }
  if (pendingOverride) items.push({ label: '成员覆盖', count: pendingOverride })
  // 组成员: 各组里还并不进预览的成员(groupsView 已统计 unaddressable)
  const pendingGroup = groupsView.value.reduce((sum, g) => sum + (g.unaddressable || 0), 0)
  if (pendingGroup) items.push({ label: '组成员并入', count: pendingGroup })

  let budget = null
  if (reportStats.value) {
    budget = {
      used: reportStats.value.used,
      // 上界口径: 每个拆出/成员覆盖约 +1 绘制调用(组成员是合并, 不加)
      projected: reportStats.value.used + pendingIso + pendingOverride,
      max: reportStats.value.max,
    }
  }
  return items.length || budget ? { items, budget } : null
})

/**
 * 未入组零件清单(按实例族聚合, 与成员卡同口径):
 *   合并散件 —— 仍在 STATIC 块里、不属任何组也无覆盖的零件;
 *   独立散件 —— 可寻址叶子零件, 不属任何组.
 */
const ungroupedView = computed(() => {
  tick.value
  const grouped = new Set()
  for (const members of groupModel.value.parts.values()) {
    for (const part of members) grouped.add(baseName(part))
  }
  const overridden = new Set([...partModel.value.entries.keys()].map(baseName))

  const merged = []
  if (memberIdx.value) {
    for (const [family, refs] of memberIdx.value.byFamily) {
      const bases = refs.map((ref) => baseName(ref.member.name))
      if (bases.some((base) => grouped.has(base) || overridden.has(base))) continue
      const marked = bases.filter((base) => isoModel.value.has(base)).length
      merged.push({
        name: family,
        tris: refs.reduce((sum, ref) => sum + (ref.member.tris || 0), 0),
        // hover 亮全族; 批量动作传首个实例名, 宿主按族展开
        member: refs.map((ref) => ref.member),
        firstName: refs[0].member.name,
        instances: refs.length,
        isolated: marked > 0,
        partial: marked > 0 && marked < refs.length,
      })
    }
  }
  const soloMap = new Map()
  if (partIndex.value) {
    for (const key of partIndex.value.allNames) {
      const info = partIndex.value.get(key)
      if (!info || info.childNames?.length) continue
      if (/^STATIC_/.test(info.name)) continue
      const saved = savedNameOfKey(key)
      if (grouped.has(baseName(saved))) continue
      const family = familyName(saved)
      const entry = soloMap.get(family)
      if (entry) {
        entry.tris += info.subtreeTriangles || 0
        entry.instances += 1
      } else {
        soloMap.set(family, {
          name: family,
          firstName: saved,
          key,
          tris: info.subtreeTriangles || 0,
          instances: 1,
        })
      }
    }
  }
  merged.sort((a, b) => b.tris - a.tris)
  const solo = [...soloMap.values()].sort((a, b) => b.tris - a.tris)
  return { merged, solo }
})

/**
 * 功能: 未分组清单里独立散件行点击 —— 树内定位并选中.
 * @param {string} key 零件索引键
 * @returns {void}
 */
function focusSoloPart(key) {
  partSel.value.select([key])
  tick.value += 1
  highlightSelection()
  treeRef.value?.reveal(key)
}

/**
 * 功能: 改合并块内成员的覆盖字段(无实时预览, 保存重跑后生效).
 *
 * 覆盖与拆出互斥(与管线清洗裁决一致): 单件覆盖本就会独立成块, 一旦成员写下
 * 第一个覆盖字段, 自动取消它的拆出标记 —— 否则要等重跑时才看到清洗告警.
 *
 * @param {string} key 字段名
 * @param {string|number|null} value 值
 * @returns {void}
 */
function changeMemberOverride(key, value) {
  if (!memberEdit.value) return
  const { family, instances } = memberEdit.value
  let freed = 0
  for (const base of instances) {
    partModel.value.set(base, key, value)
    if (Object.keys(partModel.value.get(base)).length && isoModel.value.remove(base)) freed += 1
  }
  if (freed) message.value = `「${family}」已有单件覆盖(本就独立), 拆出标记已自动取消`
  tick.value += 1
}

/**
 * 功能: 清掉合并块内成员(整族)的全部覆盖.
 * @returns {void}
 */
function resetMemberOverride() {
  if (!memberEdit.value) return
  for (const base of memberEdit.value.instances) partModel.value.reset(base)
  tick.value += 1
}

/**
 * 功能: 把合并块内成员加入材质组(保存重跑后并入组块).
 * @param {string} name 成员原名
 * @param {string} group 组名
 * @returns {void}
 */
function addStaticMemberToGroup(name, group) {
  // 按实例族整族入组, 与拆出对称 —— 同一零件的多个装配实例观感必然一致;
  // 组成员一律存 base 名(成员名可能带 Blender 重名后缀 .00N, 跨次运行会漂移)
  const instances = familyInstancesOf(name)
  const freed = instances.filter((base) => isoModel.value.remove(base)).length
  const n = groupModel.value.addParts(group, instances)
  syncAllGroupPreviews()
  message.value =
    (n
      ? `已把「${familyName(name)}」${n > 1 ? ` ×${n}` : ''}加入组「${group}」(合并块内成员, 重跑后生效)`
      : `「${familyName(name)}」已在组「${group}」`) +
    (freed ? '; 已自动取消其拆出标记(入组优先)' : '')
}

/**
 * 功能: 求一个成员所属**实例族**的全部实例名(仍在合并块里的那些).
 *
 * `侧门-1` 与 `侧门-2` 是同一零件的两个装配实例, 管线按各自的名字建独立材质,
 * 所以整族操作必须逐个实例写键 —— 只写一个的话另一个仍留在块里(踩过).
 *
 * @param {string} name 成员名
 * @returns {string[]} 族内实例的 base 名(至少含自身)
 */
function familyInstancesOf(name) {
  const refs = memberIdx.value?.byFamily?.get(familyName(name)) || []
  const names = new Set(refs.map((ref) => baseName(ref.member.name)))
  names.add(baseName(name))
  return [...names]
}

/**
 * 功能: 把零件标记为「拆出为独立零件」(part_isolate; 保存并重跑后脱离静态合并).
 *
 * **按实例族整族拆出**: 用户说"这个门板"指的是零件, 不是其中某一个装配实例;
 * 只拆一个实例会留下另一半还在块里. 每个实例各写一条键(各自 MAT_SOLO_<slug>,
 * 从而各自独立可选), 因此族有 N 个实例就约 +N 绘制调用, 消息里明说.
 *
 * 单一隶属裁决(与管线清洗期一致): 已有单件覆盖 → 本就会独立成块, 跳过;
 * 在材质组 → 自动移出该组.
 *
 * @param {string} name 零件名(可带 .00N / -N, 内部按族展开)
 * @returns {void}
 */
function isolateMember(name) {
  const family = familyName(name)
  const instances = familyInstancesOf(name)
  const notes = []
  let added = 0
  let covered = 0
  let leftGroup = false
  for (const base of instances) {
    if (Object.keys(partModel.value.get(base)).length) {
      covered += 1
      continue
    }
    const owner = groupModel.value.groupOfPart(base)
    if (owner) {
      groupModel.value.removePart(owner, base)
      leftGroup = true
      notes.push(`已自动移出组「${owner}」`)
    }
    if (isoModel.value.add(base)) added += 1
  }
  if (leftGroup) syncAllGroupPreviews()
  tick.value += 1
  if (!added) {
    message.value = covered
      ? `「${family}」已有单件覆盖, 本就会独立成块, 无需再拆出`
      : `「${family}」的 ${instances.length} 个实例已全部标记拆出`
    return
  }
  if (instances.length > 1) notes.unshift(`同一零件的 ${instances.length} 个实例一并拆出`)
  if (covered) notes.push(`${covered} 个实例已有单件覆盖, 跳过`)
  message.value =
    `已标记拆出「${family}」${added > 1 ? ` ×${added}` : ''}(保存并重跑后成为独立零件)` +
    (notes.length ? `; ${[...new Set(notes)].join('; ')}` : '')
}

/**
 * 功能: 取消拆出标记(同样按实例族整族撤销, 与拆出对称).
 * @param {string} name 零件名(可带 .00N / -N)
 * @returns {void}
 */
function unisolateMember(name) {
  const removed = familyInstancesOf(name).filter((base) => isoModel.value.remove(base)).length
  if (!removed) return
  tick.value += 1
  message.value = `已取消「${familyName(name)}」${removed > 1 ? ` ×${removed}` : ''}的拆出标记`
}

/**
 * 功能: 批量标记拆出(成员卡/未分组清单的多选操作; 规则与单件 isolateMember 一致).
 * @param {string[]} names 成员名数组
 * @returns {void}
 */
function batchIsolateMembers(names) {
  // 每个选中项按实例族展开(选中项本身就是族行时展开即全部实例)
  const targets = [...new Set((names || []).flatMap((raw) => familyInstancesOf(raw)))]
  let done = 0
  let skipped = 0
  for (const base of targets) {
    if (Object.keys(partModel.value.get(base)).length) {
      skipped += 1
      continue
    }
    const owner = groupModel.value.groupOfPart(base)
    if (owner) groupModel.value.removePart(owner, base)
    if (isoModel.value.add(base)) done += 1
  }
  syncAllGroupPreviews()
  message.value =
    `已批量标记拆出 ${done} 个实例(保存并重跑后各自独立)` +
    (skipped ? `; ${skipped} 个已有单件覆盖跳过` : '') +
    (done > 20 ? '; 注意: 每个实例约 +1 绘制调用(预算上限 500)' : '')
}

/**
 * 功能: 批量加入材质组(按实例族展开; 自动取消拆出标记, 入组优先).
 * @param {string[]} names 成员名数组
 * @param {string} group 组名
 * @returns {void}
 */
function batchAddMembersToGroup(names, group) {
  const targets = [...new Set((names || []).flatMap((raw) => familyInstancesOf(raw)))]
  const freed = targets.filter((base) => isoModel.value.remove(base)).length
  const n = groupModel.value.addParts(group, targets)
  syncAllGroupPreviews()
  message.value =
    (n ? `已把 ${n} 个实例加入组「${group}」(重跑后并入组块)` : '所选零件均已在该组') +
    (freed ? `; ${freed} 个已自动取消拆出标记(入组优先)` : '')
}

/**
 * 功能: 组面板选中一个组(高亮成员).
 * @param {string} name 组名(空=收起)
 * @returns {void}
 */
function selectGroup(name) {
  activeGroup.value = name
  if (!name) return
  const meshes = scene.value?.groupMeshes(name) || []
  if (meshes.length) {
    manager.value?.effects?.setSelected(meshes)
    tools.value?.frameObjects(meshes)
  }
}

/**
 * 功能: 改组参数并实时生效.
 * @param {string} name 组名
 * @param {string} key 字段
 * @param {*} value 值
 * @returns {void}
 */
function changeGroupParam(name, key, value) {
  groupModel.value.setParam(name, key, value)
  const kit = scene.value
  if (kit) {
    kit.applyGroup(name, [], groupModel.value.getParams(name), kit.groupBaseClass(name))
  }
  tick.value += 1
}

/**
 * 功能: 清掉组参数(成员保留, 观感回到组底).
 * @param {string} name 组名
 * @returns {void}
 */
function resetGroupParams(name) {
  groupModel.value.resetParams(name)
  const kit = scene.value
  if (kit) kit.applyGroup(name, [], {}, kit.groupBaseClass(name))
  message.value = `已还原组「${name}」的参数`
  tick.value += 1
}

/**
 * 功能: 还原某材质的全部人工调整.
 * @param {string} name 材质名
 * @returns {void}
 */
function reset(name) {
  model.value.reset(name)
  scene.value?.apply(name, {})
  message.value = `已还原「${labelOf(name)}」`
  tick.value += 1
}

/**
 * 功能: 撤销上一步.
 * @returns {void}
 */
function undo() {
  if (model.value.undo()) {
    scene.value?.applyAll(model.value)
    message.value = '已撤销'
  } else {
    message.value = '没有可撤销的操作'
  }
  tick.value += 1
}

/**
 * 功能: 应用一个材质预设 —— 批量写字段(单步可撤销)并实时生效.
 * @param {{label: string, patch: object}} preset 预设
 * @returns {void}
 */
function applyPreset(preset) {
  if (!selected.value) return
  const n = model.value.setMany(selected.value, preset.patch)
  if (!n) return
  scene.value?.apply(selected.value, model.value.get(selected.value))
  message.value = `已应用预设「${preset.label}」(${n} 项, 可撤销)`
  tick.value += 1
}

/**
 * 功能: 按住对比 —— 按下临时显示未覆盖的原值, 松开恢复当前覆盖.
 * @param {boolean} active 是否按下
 * @returns {void}
 */
function compareBaseline(active) {
  if (!selected.value) return
  scene.value?.apply(selected.value, active ? {} : model.value.get(selected.value))
}

/**
 * 功能: 把基色恢复成材质名里的 CAD 量化色.
 * @param {string} hex '#RRGGBB'
 * @returns {void}
 */
function applyCadColor(hex) {
  if (!selected.value) return
  change('base_color', hex)
  message.value = `已恢复 CAD 原色 ${hex}`
}

/**
 * 功能: 三维里点到零件时选中(Ctrl 加选)+反查材质+树定位; 点空白取消全部选中.
 * @param {{part: string, material: string, mesh: object}|null} hit 拾取结果
 * @param {boolean} [additive] Ctrl/Shift 加选
 * @returns {void}
 */
function handlePick(hit, additive = false) {
  if (!hit) {
    if (additive) return // Ctrl 点空白不清选(加选途中误点空白很常见)
    // 点空白 = 取消全部选中(材质/零件/树/三维高亮), 与装配台一致
    pickedPart.value = ''
    partSel.value.clearSelection()
    selected.value = ''
    scene.value?.select(null)
    message.value = ''
    tick.value += 1
    return
  }
  pickedPart.value = hit.part.replace(/\.\d{3}$/, '')
  // 按命中的网格反查零件键, 让层级树自动展开定位到它
  const key = hit.mesh ? partIndex.value?.ownerOfMesh(hit.mesh) : null
  if (key) {
    if (additive) partSel.value.toggle(key)
    else partSel.value.select([key])
    tick.value += 1
    highlightSelection()
    treeRef.value?.reveal(key)
  }
  if (additive) {
    message.value = `已选中 ${partSel.value.selected.size} 个零件(Ctrl 点击增删)`
    return
  }
  if (hit.material.startsWith('GROUP_')) {
    activeGroup.value = hit.material.slice('GROUP_'.length)
    message.value = `「${pickedPart.value}」属于材质组「${activeGroup.value}」`
    return
  }
  if (hit.material && hit.material !== selected.value) {
    selected.value = hit.material
    tick.value += 1
  }
  message.value = `「${pickedPart.value}」用的是「${labelOf(hit.material)}」`
}

/**
 * 功能: 当前该被"重点关照"的网格 —— 隔离与透视都以它为中心.
 *
 * 优先级: 树/三维的当前选中集(右键落点也会进选中集) → 最近点过的零件名 →
 * 当前材质类. 旧版只看 pickedPart, 而右键路径不设它, 导致右键菜单的
 * 「隐藏/隔离」作用在上一次左键的对象甚至整个材质类上(错位).
 * @returns {Array} 网格数组
 */
function focusMeshes() {
  const keys = [...partSel.value.selected]
  if (keys.length) {
    const meshes = keys.flatMap((key) => meshesOfKey(key))
    if (meshes.length) return meshes
  }
  if (pickedPart.value) {
    const meshes = scene.value?.meshesOfPart(pickedPart.value) || []
    if (meshes.length) return meshes
  }
  return selected.value ? scene.value?.meshesOf(selected.value) || [] : []
}

/**
 * 功能: 工具栏动作分发.
 * @param {string} action 动作名
 * @param {*} [payload] 附带参数
 * @returns {void}
 */
function onTool(action, payload) {
  const kit = tools.value
  if (!kit) return

  if (action === 'view') kit.setView(payload)
  else if (action === 'reset') kit.resetView()
  else if (action === 'hide') message.value = `已隐藏 ${kit.hide(focusMeshes())} 个对象`
  else if (action === 'isolate') message.value = `已隔离, 隐藏了 ${kit.isolate(focusMeshes())} 个对象`
  else if (action === 'showAll') message.value = `已还原 ${kit.showAll()} 个对象`
  else if (action === 'xray') {
    view.value.xray = kit.setXray(payload, focusMeshes())
  } else if (action === 'wireframe') {
    view.value.wireframe = kit.setWireframe(payload)
  } else if (action === 'helpers') {
    kit.setHelpersVisible(payload)
    view.value.helpers = payload
  }
  view.value.hidden = kit._hidden.size
}

// -- 右键快捷菜单 ----------------------------------------------------------

/**
 * 功能: 三角形数的紧凑显示(与树行同款).
 * @param {number} n 数量
 * @returns {string} 如 "12.3k"
 */
function compactTris(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/**
 * 功能: 右键命中合并块时, 由命中点×成员包围盒算出候选成员(CAD Select Other 式).
 * @param {{mesh: THREE.Mesh, point: THREE.Vector3}} hit pickAt 命中(含世界坐标命中点)
 * @returns {{list: Array, total: number}|null} 候选清单; 成员数据缺失返回 null
 */
function memberCandidates(hit) {
  if (!memberIdx.value || !hit?.point) return null
  const key = partIndex.value?.ownerOfMesh(hit.mesh)
  const info = key ? partIndex.value?.get(key) : null
  const members = info ? membersOfInfo(info) : null
  if (!members?.length) return null
  // 命中点转到 glTF y-up 模型空间(与成员 bbox 同口径), 不做任何单位换算
  const space = manager.value?.machineRoot?.children?.[0]
  if (!space) return null
  const local = space.worldToLocal(hit.point.clone())
  return rankCandidates(members, [local.x, local.y, local.z])
}

/**
 * 功能: 滚动定位到右栏的成员清单卡, 可选高亮某一行.
 * @param {string} name 成员名或族名(空=只定位卡片); 一律归一到族名 —— 清单按族列行
 * @returns {void}
 */
function revealMemberInCard(name) {
  memberFocus.value = name ? familyName(name) : ''
  nextTick(() => {
    document
      .getElementById('mt-members-card')
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

/**
 * 功能: 组装单个候选成员的子菜单(拆出/移组/设材质/清单定位).
 * @param {object} member 归一成员
 * @returns {Array} 子菜单项
 */
function buildMemberActions(member) {
  const instances = familyInstancesOf(member.name)
  const fanout = instances.length > 1 ? `${instances.length} 个实例` : ''
  const isolated = instances.every((base) => isoModel.value.has(base))
  const actions = [
    isolated
      ? {
          key: 'un-isolate',
          label: '取消拆出标记',
          hint: fanout,
          action: () => unisolateMember(member.name),
        }
      : {
          key: 'isolate',
          label: '拆出为独立零件',
          // 整族拆出: 同一零件的多个装配实例一起走, 免得只拆一半
          hint: fanout ? `${fanout} · 重跑生效` : '重跑生效',
          action: () => isolateMember(member.name),
        },
  ]
  for (const group of groupModel.value.names().slice(0, 5)) {
    actions.push({
      key: `grp-${group}`,
      label: `移入组「${group}」`,
      hint: fanout,
      action: () => addStaticMemberToGroup(member.name, group),
    })
  }
  actions.push(
    {
      key: 'edit',
      label: '单独设材质',
      hint: fanout ? `${fanout} · 重跑生效` : '重跑生效',
      action: () => editStaticMember(member.name),
    },
    {
      key: 'locate',
      label: '在成员清单中定位',
      action: () => revealMemberInCard(member.name),
    },
  )
  return actions
}

/**
 * 功能: 组装材质台的右键菜单项.
 * @param {string} key 被右击的零件键
 * @param {boolean} merged 是否合并块
 * @param {{list: Array, total: number}|null} [candidates] 合并块的命中成员候选
 * @returns {Array} 菜单项
 */
function buildMtMenu(key, merged, candidates = null) {
  const keys = [...partSel.value.selected]
  const items = []

  if (keys.length > 1) {
    items.push({
      key: 'group-new',
      label: `选中 ${keys.length} 件 → 新建材质组…`,
      action: () => groupPanelRef.value?.openDraft?.(),
    })
    for (const name of groupModel.value.names().slice(0, 6)) {
      items.push({
        key: `group-add-${name}`,
        label: `加入组「${name}」`,
        action: () => addSelectionToGroup(name),
      })
    }
    items.push({ divider: true })
  } else if (!merged) {
    items.push({
      key: 'override',
      label: '单独设材质(零件覆盖)',
      hint: '实时生效',
      action: () => {
        // 零件覆盖卡随单选自动出现, 这里给一个空补丁占位并提示
        message.value = '零件覆盖卡已在右栏, 直接拖字段即可(压过组与材质类)'
      },
    })
    const savedName = savedNameOfKey(key)
    const owner = groupModel.value.groupOfPart(savedName)
    if (owner) {
      items.push({
        key: 'group-leave',
        label: `移出组「${owner}」`,
        action: () => removeMemberFromGroup(owner, savedName),
      })
    } else {
      for (const name of groupModel.value.names().slice(0, 6)) {
        items.push({
          key: `group-add-${name}`,
          label: `加入组「${name}」`,
          action: () => addSelectionToGroup(name),
        })
      }
    }
    items.push({
      key: 'reset-part',
      label: '恢复零件覆盖',
      disabled: !Object.keys(partModel.value.get(savedName)).length,
      action: () => {
        partModel.value.reset(savedName)
        scene.value?.applyPart(meshesOfKey(key), {})
        tick.value += 1
        message.value = `已恢复「${savedName}」的零件覆盖`
      },
    })
    items.push({ divider: true })
  } else {
    // 合并块: 命中点候选成员置顶(小件优先), 每个候选一层子菜单做资产操作;
    // 悬浮候选画 bbox 线框, 悬浮其他行即收起
    if (candidates?.list?.length) {
      items.push({
        key: 'cand-head',
        label: `命中成员候选(共 ${candidates.total} 件)`,
        disabled: true,
      })
      for (const member of candidates.list) {
        const base = baseName(member.name)
        const family = memberIdx.value?.byFamily?.get(familyName(member.name)) || []
        const siblings = family.map((ref) => ref.member)
        items.push({
          key: `cand-${member.name}`,
          label: (isoModel.value.has(base) ? '⛏ ' : '') + base,
          hint: member.tris ? `${compactTris(member.tris)}△` : '',
          // 悬浮候选行亮出整族(命中的这件在其中), 让"这零件有几个实例"当场可见
          onHover: () =>
            highlighter?.show(siblings.length ? siblings : member, {
              dashed: isoModel.value.has(base),
            }),
          children: buildMemberActions(member),
        })
      }
      items.push({
        key: 'members',
        label: `查看全部 ${candidates.total} 名成员`,
        onHover: () => highlighter?.hide(),
        action: () => revealMemberInCard(''),
      })
    } else {
      items.push({
        key: 'members',
        label: '查看合并成员',
        action: () => revealMemberInCard(''),
      })
    }
    items.push({ divider: true })
  }

  items.push(
    { key: 'hide', label: '隐藏', hint: '视图', onHover: () => highlighter?.hide(), action: () => onTool('hide') },
    { key: 'isolate', label: '隔离显示', hint: '视图', onHover: () => highlighter?.hide(), action: () => onTool('isolate') },
    {
      key: 'focus',
      label: '飞过去看',
      onHover: () => highlighter?.hide(),
      action: () => {
        const meshes = meshesOfKey(key)
        if (meshes.length) tools.value?.frameObjects(meshes)
      },
    },
    {
      key: 'reveal',
      label: '在树中定位',
      onHover: () => highlighter?.hide(),
      action: () => treeRef.value?.reveal(key),
    },
  )
  return items
}

/**
 * 功能: canvas 的 pointerdown —— 喂右键判定器.
 * @param {PointerEvent} event 指针事件
 * @returns {void}
 */
function onCanvasPointerDown(event) {
  rightClick.onPointerDown(event)
}

/**
 * 功能: canvas 的 contextmenu —— 右键单击零件弹菜单(pickAt 只读拾取), 拖拽平移不弹.
 * @param {MouseEvent} event contextmenu 事件
 * @returns {void}
 */
function onCanvasContextMenu(event) {
  event.preventDefault()
  if (!rightClick.shouldOpen(event)) return
  const hit = scene.value?.pickAt(event.clientX, event.clientY)
  const key = hit?.mesh ? partIndex.value?.ownerOfMesh(hit.mesh) : null
  if (!key) return
  // 右键也算一次"点到": 与左键同步 pickedPart, 免得 focusMeshes 兜底拿到旧目标
  pickedPart.value = (hit.mesh.name || '').replace(/\.\d{3}$/, '')
  if (!partSel.value.selected.has(key)) {
    partSel.value.select([key])
    tick.value += 1
    highlightSelection()
    treeRef.value?.reveal(key)
  }
  const merged = /^STATIC_/.test(hit.mesh.name || '')
  menu.value = {
    x: event.clientX,
    y: event.clientY,
    items: buildMtMenu(key, merged, merged ? memberCandidates(hit) : null),
  }
}

/**
 * 功能: 关闭右键菜单并收起成员高亮线框.
 * @returns {void}
 */
function onMenuClose() {
  menu.value = null
  highlighter?.hide()
}

/**
 * 功能: 保存到 material_semantics.yaml.
 * @returns {Promise<void>}
 */
async function save() {
  saving.value = true
  message.value = ''
  try {
    // 保存前重读原文再打补丁: 并行会话可能已改过本文件的其他段落, 段级补丁只
    // 重建自己的四段, 以最新原文为底才不会把别人的段落写回旧版
    try {
      semanticsText = await api.readFile('material_semantics')
    } catch {
      // 读失败(中间件抖动)时退回内存底稿, 行为与旧版一致
    }
    // 四段串联打补丁后一次写盘: 无部分写入窗口, 中间件自动留 .bak
    const next = patchPartIsolate(
      patchPartGroups(
        patchPartOverrides(patchAppearanceOverrides(semanticsText, model.value), partModel.value),
        groupModel.value,
      ),
      isoModel.value,
    )
    await api.writeFile('material_semantics', next)
    semanticsText = next
    const partCount = partModel.value.entries.size
    const groupCount = groupModel.value.parts.size
    const isoCount = isoModel.value.names.size
    message.value =
      `已保存 ${overriddenCount.value} 条材质覆盖` +
      (partCount ? ` + ${partCount} 条零件覆盖` : '') +
      (isoCount ? ` + ${isoCount} 条拆出标记(重跑后独立)` : '') +
      (groupCount ? ` + ${groupCount} 个材质组(重跑后按组合并)` : '') +
      ' 到 material_semantics.yaml'
  } catch (err) {
    message.value = `保存失败: ${err.message}`
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  authoringAvailable.value = await api.probeAuthoring()
  if (disposed === true) return

  try {
    const instance = new SceneManager(containerRef.value, {
      quality: 'high',
      onStats: (next) => {
        stats.value = next
      },
    })
    manager.value = instance

    // 创作页无 manifest 构建戳可用 —— 每次强刷, 保证重跑管线后立即见到新模型
    await instance.loadMachineModel(`${MODEL_URL}?t=${Date.now()}`, (f) => {
      progress.value = f
    })
    if (disposed === true) return

    scene.value = new MaterialsScene({ manager: instance, onPick: handlePick })
    tools.value = new ViewTools(instance)
    // 右键快捷菜单: 单击弹菜单, 按住拖拽仍是平移
    instance.canvas.addEventListener('pointerdown', onCanvasPointerDown)
    instance.canvas.addEventListener('contextmenu', onCanvasContextMenu)
    // 左侧层级树直接索引成品模型的场景图(工位 → 运动件子层级 + 静态合并件);
    // machine.glb 的真零件名本就是中文, 不需要 names.csv 映射
    partIndex.value = new PartIndex(instance.machineRoot)
    soloFamilyIndex.value = buildSoloFamilyIndex()
    if (import.meta.env.DEV) {
      console.info('[materials] 层级树顶层:', partIndex.value.assemblies.map((a) => a.name))
    }
    view.value.helpersPresent = tools.value.countHelpers() > 0

    // 合并成员元数据: dev 优先读 clean_report(与本次 GLB 同次运行), 生产回退部署
    // 产物 merge-members.json; 树的成员行/右键候选/成员卡/未分组清单共用这一份
    loadMemberData(authoringAvailable.value ? api : null).then((blocks) => {
      if (disposed === true) return
      memberIdx.value = buildMemberIndex(blocks)
      tick.value += 1
    })
    // 05 报告的绘制调用现状: 保存栏的预算预估行(读不到就不显示该行)
    if (authoringAvailable.value) {
      api
        .readFile('report')
        .then((text) => {
          if (disposed === true) return
          const data = JSON.parse(text)
          reportStats.value = {
            used: data?.metrics?.primitives || 0,
            max: data?.budget?.max_draw_calls || 500,
          }
          tick.value += 1
        })
        .catch(() => {})
    }
    // 成员包围盒高亮挂 glTF y-up 模型空间(machineRoot 首子节点): 管线 bbox 坐标
    // 在该空间内直接可用, 不做任何单位换算
    highlighter = new BboxHighlighter(instance.machineRoot?.children?.[0] || instance.machineRoot)

    // 机械臂摆到折叠工作姿态(与装配台/演示一致); PartIndex 已按零位建完, 不受影响
    await applyRobotHomePose(instance)
    if (disposed === true) return

    // 恢复上次调好的覆盖 —— 这样不重跑管线也能看到当前 YAML 的真实状态
    if (authoringAvailable.value) {
      try {
        semanticsText = await api.readFile('material_semantics')
        if (disposed === true) return
        const restored = model.value.load(readAppearanceOverrides(semanticsText))
        if (restored) {
          scene.value.applyAll(model.value)
        }
        // 零件覆盖: 能寻址(未合并)的零件立即重放; 已被重跑固化成 MAT_PART_* 的
        // 零件此时按类覆盖路径生效, 重复叠加也幂等
        const restoredParts = partModel.value.load(readPartOverrides(semanticsText))
        if (restoredParts) {
          for (const [savedName, patch] of partModel.value.entries) {
            const keys = partIndex.value?.keysForSavedName?.(savedName) || []
            for (const key of keys) {
              const info = partIndex.value.get(key)
              const meshes = []
              info?.object?.traverse((child) => {
                if (child.isMesh && !/^STATIC_/.test(child.name || '')) meshes.push(child)
              })
              if (meshes.length) scene.value.applyPart(meshes, patch)
            }
          }
        }
        // 材质组: 装入并重放预览(合并块内成员不可寻址, 计入组卡的"待重跑"提示)
        const restoredGroups = groupModel.value.load(readPartGroups(semanticsText))
        if (restoredGroups) syncAllGroupPreviews()
        // 孤立清单: 装入即可 —— 观感不变, 没有可重放的预览; 已重跑固化的条目
        // 在树里表现为独立节点, 未固化的计入"待生效"提示
        const restoredIso = isoModel.value.load(readPartIsolate(semanticsText))
        // 与单件覆盖重叠的条目就地清掉: 覆盖本就会让零件独立成块, 两者并存会让
        // build_materials 每次重跑都告警一次(并行会话写出过这种组合)
        for (const name of [...isoModel.value.names]) {
          if (Object.keys(partModel.value.get(name)).length) isoModel.value.remove(name)
        }
        if (restored || restoredParts || restoredGroups || restoredIso) {
          message.value = `已恢复上次的 ${restored} 条材质调整` +
            (restoredParts ? ` + ${restoredParts} 条零件覆盖` : '') +
            (restoredIso ? ` + ${restoredIso} 条拆出标记` : '') +
            (restoredGroups ? ` + ${restoredGroups} 个材质组` : '')
        }
      } catch (err) {
        message.value = `读取 material_semantics.yaml 失败: ${err.message}`
      }
    }

    tick.value += 1

    // dev-only 目检钩子: 让 Playwright 能把镜头对准指定节点/机位截放大图.
    // 这是"每类部件对照照片过一遍"审查流程的抓手, 生产构建不挂.
    if (import.meta.env.DEV) {
      window.__ptlc = {
        focus(nodeName, padding = 1.4) {
          // 目检用大边距: 贴着包围盒会钻进机器内部, 白墙上看不出任何东西
          let target = null
          manager.value?.machineRoot?.traverse((child) => {
            if (!target && child.name === nodeName) target = child
          })
          if (!target) return false
          manager.value?.effects?.setSelected([])
          return tools.value?.frameObjects([target], padding) || false
        },
        view(key) {
          return tools.value?.setView(key) ?? false
        },
        isolate(nodeName) {
          let target = null
          manager.value?.machineRoot?.traverse((child) => {
            if (!target && child.name === nodeName) target = child
          })
          if (!target) return 0
          return tools.value?.isolate([target]) ?? 0
        },
        // 验证钩子: 按网格名选中零件/合并块(Playwright 驱动成员卡与右栏面板)
        selectNode(nodeName) {
          let mesh = null
          manager.value?.machineRoot?.traverse((child) => {
            if (!mesh && child.isMesh && child.name === nodeName) mesh = child
          })
          const key = mesh ? partIndex.value?.ownerOfMesh(mesh) : null
          if (!key) return false
          partSel.value.select([key])
          tick.value += 1
          highlightSelection()
          treeRef.value?.reveal(key)
          return true
        },
        showAll() {
          return tools.value?.showAll() ?? 0
        },
        // 审查用: 名字(或祖先名)含 sub 的网格 -> 材质分布/明细
        materialsOf(sub) {
          const tally = {}
          manager.value?.machineRoot?.traverse((child) => {
            if (!child.isMesh) return
            let hit = false
            for (let node = child; node; node = node.parent) {
              if ((node.name || '').includes(sub)) {
                hit = true
                break
              }
            }
            if (!hit) return
            const list = Array.isArray(child.material) ? child.material : [child.material]
            const key = list[0]?.name || '(无)'
            tally[key] = (tally[key] || 0) + 1
          })
          return tally
        },
        meshList(sub, limit = 40) {
          const rows = []
          manager.value?.machineRoot?.traverse((child) => {
            if (!child.isMesh || rows.length >= limit) return
            let hit = false
            for (let node = child; node; node = node.parent) {
              if ((node.name || '').includes(sub)) {
                hit = true
                break
              }
            }
            if (!hit) return
            const list = Array.isArray(child.material) ? child.material : [child.material]
            rows.push([child.name, list[0]?.name || ''])
          })
          return rows
        },
        reset() {
          tools.value?.resetView()
          return true
        },
      }
    }
  } catch (err) {
    if (disposed === true) return
    error.value = err?.message || String(err)
    console.error('[materials] 初始化失败', err)
  } finally {
    if (disposed === false) loading.value = false
  }
})

onBeforeUnmount(() => {
  disposed = true
  if (import.meta.env.DEV && window.__ptlc) delete window.__ptlc
  const canvas = manager.value?.canvas
  canvas?.removeEventListener('pointerdown', onCanvasPointerDown)
  canvas?.removeEventListener('contextmenu', onCanvasContextMenu)
  highlighter?.dispose()
  highlighter = null
  tools.value?.dispose()
  scene.value?.dispose()
  manager.value?.dispose()
  manager.value = null
})
</script>

<template>
  <div class="mt">
    <div ref="containerRef" class="mt__canvas" />

    <ViewToolbar
      v-if="!error"
      :has-selection="Boolean(selected || pickedPart)"
      :xray="view.xray"
      :wireframe="view.wireframe"
      :helpers="view.helpers"
      :hidden-count="view.hidden"
      :show-helpers-toggle="view.helpersPresent"
      :display-open="showDisplay"
      @view="onTool('view', $event)"
      @reset="onTool('reset')"
      @hide="onTool('hide')"
      @isolate="onTool('isolate')"
      @show-all="onTool('showAll')"
      @xray="onTool('xray', $event)"
      @wireframe="onTool('wireframe', $event)"
      @helpers="onTool('helpers', $event)"
      @display="showDisplay = !showDisplay"
    />

    <!-- 显示设置面板: 右缘避开 330px 材质栏(+12 边距+10 间隙) -->
    <DisplayPanel
      v-if="showDisplay && manager"
      :manager="manager"
      :stats="stats"
      :anchor-right="352"
      @close="showDisplay = false"
    />

    <!-- 左: 零件层级树(与装配台同一棵树); 点零件 → 取景 + 高亮 + 切到它的材质 -->
    <aside v-if="!error" class="mt__left">
      <PartTree
        v-if="partIndex"
        ref="treeRef"
        :index="partIndex"
        :tick="tick"
        header="零件层级"
        :selected-keys="selectedKeySet"
        :label-of="nodeLabel"
        :dot-color-of="nodeDot"
        :members-of="treeMembersOf"
        :on-member-focus="focusTreeMember"
        :on-member-hover="treeMemberHover"
        :member-badge-of="treeMemberBadge"
        :filters="OWNERSHIP_FILTERS"
        :filter-of="ownershipOf"
        @focus="focusNode"
      />
    </aside>

    <!-- 右: 材质类型(中文名) + 选中材质的参数 -->
    <aside v-if="!error" class="mt__right">
      <section class="mt__panel mt__mats">
        <header class="mt__subhead">
          <span>材质类型</span>
          <span class="mt__badge">{{ materials.length }} 种 · 已调 {{ overriddenCount }}</span>
        </header>
        <input
          v-model="matSearch"
          class="mt__search"
          type="search"
          placeholder="搜索材质（中文名或 MAT_*）"
        />
        <ul class="mt__list">
          <li
            v-for="item in filteredMaterials"
            :key="item.name"
            :class="['mt__item', { 'mt__item--on': item.name === selected }]"
            :title="item.name"
            @click="pick(item.name)"
          >
            <span
              class="mt__swatch"
              :style="{ background: item.current.base_color || '#808080' }"
            />
            <span class="mt__itemName">{{ labelOf(item.name) }}</span>
            <span v-if="model.entries.has(item.name)" class="mt__dot" title="已人工调整">●</span>
            <span class="mt__count">{{ fmt(item.meshes) }}</span>
          </li>
        </ul>
      </section>

      <section v-if="currentEntry" class="mt__panel">
        <div class="mt__meta">
          <span>{{ fmt(currentEntry.meshes) }} 个零件</span>
          <span>{{ fmt(currentEntry.triangles) }} 三角形</span>
          <button class="mt__btn mt__btn--ghost" @click="frame">飞过去看</button>
        </div>
        <QuickActions
          :name="selected"
          :has-patch="Object.keys(currentPatch).length > 0"
          @preset="applyPreset"
          @compare="compareBaseline"
          @cad-color="applyCadColor"
        />
        <MaterialEditor
          :name="selected"
          :title="labelOf(selected)"
          :current="currentEntry.current"
          :baseline="currentBaseline"
          :patch="currentPatch"
          @change="change"
          @reset="reset"
        />
      </section>

      <!-- 零件覆盖: 未合并零件实时预览; 合并块说明"重跑生效"的机制 -->
      <section v-if="partTarget?.kind === 'part'" class="mt__panel">
        <p class="mt__hint mt__hint--part">
          零件覆盖 · 实时生效，保存并重跑后固化为独立材质（MAT_PART_*）
        </p>
        <QuickActions
          :name="partClassName"
          :has-patch="Object.keys(partPatch).length > 0"
          @preset="applyPartPreset"
          @compare="comparePart"
          @cad-color="applyPartCadColor"
        />
        <MaterialEditor
          :name="partTarget.savedName"
          :title="nodeLabel(partTarget.info)"
          :current="partCurrent"
          :baseline="partBaseline"
          :patch="partPatch"
          @change="changePart"
          @reset="resetPart"
        />
      </section>
      <section v-else-if="partTarget?.kind === 'assembly'" class="mt__panel">
        <p class="mt__hint">
          「{{ nodeLabel(partTarget.info) }}」是装配层级节点。在树里展开它，选中具体零件
          或"静态合并件"再做调整；也可以右键三维里的几何直达。
        </p>
      </section>
      <template v-else-if="partTarget?.kind === 'merged'">
        <section class="mt__panel">
          <p class="mt__hint">
            「{{ nodeLabel(partTarget.info) }}」是静态合并几何（按工位×材质合并），块内单件不可实时调。
            块内单件可拆出为独立零件、移入材质组或单独设材质，保存并重跑后生效。
          </p>
          <p class="mt__hint" :class="{ 'mt__hint--warn': blockClassScope.outside > 0 }">
            <template v-if="blockClassScope.outside > 0">
              注意：改上面的材质类会同时改到本块之外的 {{ blockClassScope.outside }} 处几何
              （该材质共用在 {{ blockClassScope.total }} 处）。只想改这一块，先把成员拆出或建成材质组。
            </template>
            <template v-else>
              该材质类目前只用在这一块上，直接调它即可，不会波及别处。
            </template>
          </p>
        </section>
        <StaticMembersCard
          id="mt-members-card"
          :block-label="nodeLabel(partTarget.info)"
          :families="staticFamilies"
          :member-count="staticMembers?.length || 0"
          :group-names="groupModel.names()"
          :isolated-names="isolatedNameSet"
          :active-member="memberFocus"
          :tick="tick"
          @override="editStaticMember"
          @add-to-group="addStaticMemberToGroup"
          @isolate="isolateMember"
          @unisolate="unisolateMember"
          @hover="hoverMember"
          @batch-isolate="batchIsolateMembers"
          @batch-group="batchAddMembersToGroup"
        />
        <section v-if="memberEdit" class="mt__panel">
          <p class="mt__hint mt__hint--part">
            成员覆盖 · {{ memberEdit.family
            }}<template v-if="memberEdit.instances.length > 1"> ×{{ memberEdit.instances.length }} 个实例</template>
            · 无实时预览，保存并重跑后独立成块
          </p>
          <MaterialEditor
            :name="memberEdit.name"
            :title="memberEdit.family"
            :current="{ ...memberEdit.baseline, ...partModel.get(memberEdit.name) }"
            :baseline="memberEdit.baseline"
            :patch="(tick, partModel.get(memberEdit.name))"
            @change="changeMemberOverride"
            @reset="resetMemberOverride"
          />
        </section>
      </template>

      <!-- 材质组: 工程师定义"哪些零件合并成同一种材质" -->
      <GroupPanel
        ref="groupPanelRef"
        :groups="groupsView"
        :selection-count="selectedKeySet.size"
        :active-group="activeGroup"
        :tick="tick"
        @create="createGroupFromSelection"
        @add-selection="addSelectionToGroup"
        @remove-member="removeMemberFromGroup"
        @remove-group="deleteGroup"
        @select="selectGroup"
        @change-param="changeGroupParam"
        @reset-params="resetGroupParams"
      />

      <!-- 未入组零件: 批量整理入口(合并散件可批量入组/拆出, 独立散件点击定位) -->
      <UngroupedCard
        :data="ungroupedView"
        :group-names="groupModel.names()"
        :tick="tick"
        @batch-isolate="batchIsolateMembers"
        @batch-group="batchAddMembersToGroup"
        @hover="hoverMember"
        @focus="focusSoloPart"
      />

      <section class="mt__panel mt__actions">
        <button class="mt__btn" :disabled="!authoringAvailable || saving" @click="save">
          {{ saving ? '保存中…' : '保存到 YAML' }}
        </button>
        <button class="mt__btn mt__btn--ghost" @click="undo">撤销</button>
        <p v-if="!authoringAvailable" class="mt__hint">
          授权中间件不可用（仅开发模式生效），当前为只读预览。
        </p>
        <p class="mt__hint">
          调整实时生效，无需重跑管线；重跑只是把它烘进 machine.glb。
        </p>
      </section>

      <RebuildPanel
        v-if="authoringAvailable"
        :available="authoringAvailable"
        :saving="saving"
        save-label="保存材质设置到 material_semantics.yaml"
        :pending="pendingSummary"
        @save="save"
      />
    </aside>

    <ContextMenu v-if="menu" v-bind="menu" @close="onMenuClose" />

    <p v-if="message" class="mt__toast">{{ message }}</p>

    <div v-if="loading" class="mt__mask">
      加载模型… {{ Math.round(progress * 100) }}%
    </div>
    <div v-if="error" class="mt__mask mt__mask--err">
      初始化失败：{{ error }}
    </div>
  </div>
</template>

<style scoped>
.mt {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg);
}

.mt__canvas {
  position: absolute;
  inset: 0;
}

.mt__left,
.mt__right {
  position: absolute;
  /* 顶格: 与居中的视图工具栏(ViewToolbar, top:12px)上缘齐平, 四周留白统一 12px */
  top: 12px;
  bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 290px;
  color: var(--text);
}

/* 左列是层级树自带的卡片样式, 容器保持透明 */
.mt__left {
  left: 12px;
  overflow: hidden;
}

.mt__right {
  right: 12px;
  width: 330px;
  padding: 10px;
  overflow: hidden auto;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 10px;
  backdrop-filter: blur(6px);
}

.mt__badge {
  font-size: 11px;
  color: var(--text-dim);
}

.mt__list {
  flex: 1;
  margin: 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
}

.mt__search {
  margin-bottom: 6px;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 6px;
  outline: none;
}

.mt__search:focus {
  border-color: var(--accent);
}

.mt__mats {
  display: flex;
  flex-direction: column;
  min-height: 120px;
  max-height: 40%;
}

.mt__item {
  display: grid;
  grid-template-columns: 14px 1fr auto auto;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  font-size: 11px;
  border-radius: 5px;
  cursor: pointer;
}

.mt__item:hover { background: var(--control); }
.mt__item--on { background: var(--accent-soft); }

.mt__swatch {
  width: 14px;
  height: 14px;
  border: 1px solid var(--hair);
  border-radius: 3px;
}

.mt__itemName {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mt__dot { font-size: 8px; color: var(--accent); }
.mt__count { color: var(--text-dim); font-variant-numeric: tabular-nums; }

.mt__panel {
  flex: none;
  padding: 10px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.mt__subhead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
}

.mt__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--text-dim);
}

.mt__actions { display: flex; flex-wrap: wrap; gap: 8px; }

.mt__btn {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--accent-ink);
  cursor: pointer;
  background: var(--accent);
  border: none;
  border-radius: 5px;
}

.mt__btn:disabled { opacity: 0.4; cursor: default; }

.mt__btn--ghost {
  margin-left: auto;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
}

.mt__hint {
  flex-basis: 100%;
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-dim);
}

.mt__hint--part {
  margin-bottom: 6px;
  color: var(--accent-bright);
}

/* 改材质类会波及块外零件时的警示 */
.mt__hint--warn {
  color: var(--warn);
}

.mt__toast {
  position: absolute;
  bottom: 16px;
  left: 50%;
  margin: 0;
  padding: 7px 14px;
  font-size: 12px;
  color: var(--text-bright);
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 18px;
  transform: translateX(-50%);
}

.mt__mask {
  position: absolute;
  inset: 0;
  display: grid;
  font-size: 13px;
  color: var(--text-mid);
  background: var(--surface);
  place-items: center;
}

.mt__mask--err { color: var(--err-bright); }
</style>
