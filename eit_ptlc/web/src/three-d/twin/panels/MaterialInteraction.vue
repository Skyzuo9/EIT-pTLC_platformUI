<script setup>
/**
 * 功能: 三维物料点选改账的接线组件 (实时页/仿真页共用).
 *
 * 手势: 右键**单击**物料实体弹快捷菜单 (rightClick 4px 判定, 右键**拖拽**仍平移相机);
 * 菜单一步操作直达写端点, "编辑数量…"打开右侧卡片。危险操作 (清空/置空/清在途/清件位)
 * 走 confirmService danger 确认, 与二维物料页逐条同级。
 * 左键**单击**单件/孔位 = 选中该孔 (emit 给宿主定位工位物料页; 同款 4px 拖拽判定,
 * 左键拖拽仍旋转相机); 工位物料页反向选孔经 selectedCell prop 流回本组件描边 ——
 * material 描边层保持**单写者**就是本组件, 三个持有者 (菜单/卡片/选中孔) 合一撤销。
 *
 * 纪律:
 *   - 渲染零回归: 无悬停、无帧钩子, 拾取只在右键那一击发生;
 *   - 不写 node.visible / 不改材质 (显隐是 TwinBindings/TrayBinding/ViewTools 多写者
 *     仲裁), 选中反馈只走 manager.outline 的 material 层描边 (low 档无描边链时菜单即反馈);
 *     描边通道有工位/零件/物料三个写者, 由 OutlineArbiter 按优先级仲裁, 本组件只声明
 *     自己那一层、也只撤自己那一层, 撤掉后自动露出宿主的工位或零件描边;
 *   - 不做乐观渲染: 写完等 material_state 推流整帧替换 (约 1 秒内);
 *   - 写通道可注入: 实时页缺省 /api/materials, 仿真页注入 /api/sim/materials
 *     (端点未就绪时 404 按"沙盒物料端点未就绪"播报, 不静默)。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { confirmAction } from '../../../composables/confirmService.js'
import { useAsyncAction } from '../../../composables/useAsyncAction.js'
import ContextMenu from '../../common/ContextMenu.vue'
import { createRightClickTracker } from '../../common/rightClick.js'
import { buildMaterialMenu, describeIdentity } from '../materialMenu.js'
import { liveMaterialWriteApi } from '../materialWriteApi.js'
import { MaterialPickController } from '../scene/MaterialPickController.js'
import { identityAtMenuTime } from '../scene/materialPick.js'
import MaterialCellPanel from './MaterialCellPanel.vue'

const props = defineProps({
  /** SceneManager (宿主保证非空且加载完成后才挂本组件) */
  manager: { type: Object, required: true },
  /** useTwinScene 的 materials ref 值 ({available, stale, snapshot}) */
  materials: { type: Object, default: null },
  /** 写通道 (materialWriteApi.createMaterialWriteApi 产物); 缺省 = 实时页 */
  writeApi: { type: Object, default: () => liveMaterialWriteApi },
  /**
   * 是否暂时锁住右键写入 (工位物料页有未保存草稿时置 true)。
   * 不锁就是两条写路径并发: 右键即时写会立刻被推流盖回来, 而草稿还挂在旧基准上。
   */
  locked: { type: Boolean, default: false },
  /** 宿主持有的选中孔 {kind, plate, hole}|null; 面板选孔与三维左键都汇到它 */
  selectedCell: { type: Object, default: null },
})
const emit = defineEmits(['panel-open', 'cell-selected'])

const menu = ref(/** @type {{x:number, y:number, items:object[]}|null} */ (null))
/** 编辑卡片的目标身份 (静态部分; 卡片内容从快照现查) */
const editing = ref(/** @type {object|null} */ (null))

const snapshot = computed(() => props.materials?.snapshot || null)
const writable = computed(() =>
  !!props.materials?.available && !props.materials?.stale && !props.locked)

let controller = null
let tracker = null
let canvas = null

/** op -> 写端点动词 (闭集; materialMenu 只产这些 op 名) */
const OP_RUNNERS = {
  mark: (args) => props.writeApi.mark(args),
  cellAmount: (args) => props.writeApi.setCellAmount(args),
  staging: (args) => props.writeApi.setStaging(args.area, args.plate),
  rack: (args) => props.writeApi.setRack(args.kind, args.plate, args.present),
  magazine: (args) => props.writeApi.setMagazine(args.magazine, args.count),
  transit: (args) => props.writeApi.clearTransit(args.carrier, args.landAt),
  payloadSeat: (args) => props.writeApi.clearPayloadSeat(args.seat),
}

const opA = useAsyncAction(
  async (row) => {
    const runner = OP_RUNNERS[row.op]
    if (!runner) return
    await runner(row.args)
  },
  {
    announce: '已写入账本 (画面随推流回读刷新)',
    onError: (msg, error) => {
      // 仿真页端点未就绪的定向提示 (阶段③里程碑落地后自然消失)
      if (error?.status === 404 || error?.status === 405) {
        console.warn('[物料点选] 写端点不存在 (沙盒物料端点未就绪?):', msg)
      }
    },
    errorPrefix: '记账失败',
  },
)

/**
 * 功能: 危险操作的确认文案.
 * @param {object} row 菜单行
 * @param {object} info 身份信息
 * @returns {string[]} 消息行
 */
function confirmMessage(row, info) {
  const target = describeIdentity(info)
  if (row.op === 'transit') {
    const where = { rack: '记回货架', staging: '记入中转', '': '只清行 (去向不明)' }[row.args.landAt]
    return [`把爪上的载荷${where}。`,
            '请先确认现场实物确实如此 —— 换板决策会据此放行, 记错会撞机。']
  }
  if (row.op === 'payloadSeat') {
    return [`将清掉工位座上的记录 (${target})。`,
            '件被拿去了哪里账本不猜, 孔位状态请随后自行更正。']
  }
  if (row.op === 'staging') {
    return [`将把该中转位的账本记录置空 (${target}), 无撤销。`,
            '原板将按回到货架库位记账; 若实际已被拿走, 请再把该库位标为无板。']
  }
  if (row.op === 'mark') {
    return [`将 ${target} 的 6 个孔全部标记为已用, 无撤销。`]
  }
  return [`将执行「${row.label}」(${target}), 无撤销。`]
}

/**
 * 功能: 执行一个菜单行 (danger 先确认; edit 打开卡片).
 * @param {object} row 菜单行
 * @param {object} info 身份信息
 * @returns {Promise<void>} 完成
 */
async function dispatch(row, info) {
  if (row.op === 'edit') {
    editing.value = { ...info }
    emit('panel-open')
    return
  }
  if (row.danger) {
    const ok = await confirmAction({
      level: 'danger',
      title: row.label,
      message: confirmMessage(row, info),
      detail: describeIdentity(info),
      confirmText: row.label,
    })
    if (!ok) return
  }
  await opA.run(row)
}

/**
 * 功能: 给纯描述行接上 action 闭包 (ContextMenu 的契约).
 * @param {object} row 菜单行
 * @param {object} info 身份信息
 * @returns {object} 可交给 ContextMenu 的行
 */
function wireRow(row, info) {
  const wired = { ...row }
  if (row.children?.length) {
    wired.children = row.children.map((child) => wireRow(child, info))
  } else if (row.op) {
    wired.action = () => { void dispatch(row, info) }
  }
  return wired
}

/** 功能: 撤掉物料层描边 (菜单/卡片/选中孔三个持有者都放手才撤); 撤后仲裁器自动露出下层. */
function clearSelection() {
  if (menu.value !== null || editing.value !== null || props.selectedCell) return
  props.manager.outline?.clear('material')
}

/**
 * 功能: 按选中孔刷新描边 —— selectedCell 与快照(件可能在货架/中转间移位)双源触发.
 * 空孔/在途时无可描边目标, 面板高亮承担反馈(与右键"菜单即反馈"同款约定)。
 */
function applySelectionOutline() {
  if (!controller) return
  const cell = props.selectedCell
  if (!cell) {
    clearSelection()
    return
  }
  const res = controller.resolveCell(cell.kind, cell.plate, cell.hole, snapshot.value)
  if (res.meshes.length) {
    props.manager.outline?.set('material', res.meshes)
  } else if (menu.value === null && editing.value === null) {
    props.manager.outline?.clear('material')
  }
}
watch([() => props.selectedCell, snapshot], applySelectionOutline)

function closeMenu() {
  menu.value = null
  clearSelection()
}
function closePanel() {
  editing.value = null
  clearSelection()
}

function onContextMenu(event) {
  // 右键语义已被本层接管: 无论命中与否都不弹浏览器菜单 (与材质台/装配台同款)
  event.preventDefault()
  if (!tracker.shouldOpen(event)) return
  const hit = controller.pickAt(event.clientX, event.clientY, canvas)
  if (!hit) {
    closeMenu()
    return
  }
  const info = identityAtMenuTime(hit.identity, snapshot.value)
  const rows = buildMaterialMenu(info, {
    available: writable.value,
    // 被草稿锁住与账本离线是两回事, 文案必须分开 —— 说错了会让人去追一个不存在的连接问题
    unavailableHint: props.locked
      ? '工位物料正在编辑草稿中, 请先保存或取消'
      : '账本离线/陈旧, 暂不可写',
  })
  menu.value = {
    x: event.clientX,
    y: event.clientY,
    items: rows.map((row) => wireRow(row, info)),
  }
  // 选中反馈只走描边 (不写 visible/材质 —— 显隐是多写者仲裁); low 档无描边链时菜单即反馈
  props.manager.outline?.set('material', hit.meshes)
}

/** 左键按下位置 (拖拽阈值判定; 逻辑同 PickController 的 4px 约定) */
let leftDown = null

function onPointerDown(event) {
  tracker.onPointerDown(event)
  if (event.button === 0) leftDown = { x: event.clientX, y: event.clientY }
}

/**
 * 功能: 左键单击选孔 —— 命中单件/孔位就把 (kind, plate, hole) 交给宿主.
 *
 * 与工位左键**不是**竞争关系: 同一击 PickController 照常把坞切到该工位,
 * material 描边层按仲裁优先级压过 station 层, 组合出"点桶 → 桶描边 + 物料页定位到孔"。
 * 拾取按需一击一次 raycast, 不破本组件"零每帧开销"的预设。
 */
function onClick(event) {
  if (!leftDown) return
  const moved = Math.hypot(event.clientX - leftDown.x, event.clientY - leftDown.y)
  leftDown = null
  if (moved > 4) return
  const hit = controller.pickAt(event.clientX, event.clientY, canvas)
  if (!hit || (hit.identity.type !== 'item' && hit.identity.type !== 'hole')) {
    // 点空白/托盘本体外: 清选中(菜单或卡片开着时描边由它们的持有权保住)
    emit('cell-selected', null)
    return
  }
  const info = identityAtMenuTime(hit.identity, snapshot.value)
  if (info.plate == null) {
    emit('cell-selected', null)
    return
  }
  emit('cell-selected', { kind: info.kind, plate: info.plate, hole: info.hole })
}

onMounted(() => {
  controller = new MaterialPickController({
    camera: props.manager.camera,
    bindings: props.manager.bindings,
    plateLayer: props.manager.plates,
  })
  tracker = createRightClickTracker()
  canvas = props.manager.canvas
  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('contextmenu', onContextMenu)
  canvas.addEventListener('click', onClick)
  if (import.meta.env.DEV) {
    // 开发期验收脚本直取拾取器 (照 manager.picker 惯例)
    props.manager.materialPicker = controller
  }
})

onBeforeUnmount(() => {
  canvas?.removeEventListener('pointerdown', onPointerDown)
  canvas?.removeEventListener('contextmenu', onContextMenu)
  canvas?.removeEventListener('click', onClick)
  tracker?.reset()
  controller?.dispose()
  controller = null
  menu.value = null
  editing.value = null
  props.manager.outline?.clear('material')
})
</script>

<template>
  <ContextMenu
    v-if="menu"
    :x="menu.x"
    :y="menu.y"
    :items="menu.items"
    @close="closeMenu"
  />
  <MaterialCellPanel
    v-if="editing"
    :identity="editing"
    :snapshot="snapshot"
    :writable="writable"
    :busy="opA.busy"
    @op="dispatch($event, identityAtMenuTime(editing, snapshot))"
    @close="closePanel"
  />
</template>
