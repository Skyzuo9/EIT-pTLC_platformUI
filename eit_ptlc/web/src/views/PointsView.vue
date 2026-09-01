<script setup>
// 点位详情 (中区): /points/:category/:id —— 上位机解释后的点位只读详情 + 原始 yaml 浏览/编辑
// (Phase 4 加 PLC 伺服实时读写)
import { computed, ref, useId, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useDirtyGuard } from '../composables/useDirtyGuard.js'
import { useQuerySync } from '../composables/useQuerySync.js'
import { useRovingTabs } from '../composables/useRovingTabs.js'
import { usePointsStore } from '../stores/points'
import { useSystemStore } from '../store'
import CalibratePanel from '../components/CalibratePanel.vue'
import PlateAlignPanel from '../components/PlateAlignPanel.vue'
import ToolAlignPanel from '../components/ToolAlignPanel.vue'
import ScrapeCalibPanel from '../components/ScrapeCalibPanel.vue'
import RackDiagram from '../components/RackDiagram.vue'
import TeachVerify from '../components/TeachVerify.vue'

const route = useRoute()
const router = useRouter()
const points = usePointsStore()
const sys = useSystemStore()

const tab = ref('detail') // 'detail' | 'raw'
useQuerySync('tab', tab, { defaultValue: 'detail' }) // 页签进 URL: 刷新不丢/可深链
// 键盘巡航走 onChange=switchTab: 保留未保存确认门 (取消 → tab 不变 → 焦点留原位)
const tabRoving = useRovingTabs(['detail', 'raw'], tab, { onChange: (k) => switchTab(k) })
const d = computed(() => points.detail)
// 孔板标定为独立入口 (/points/calibration), 与具体点位无关; 此处仅判断当前是否为该入口
const isCalib = computed(() => route.params.category === 'calibration')
// 板位对位为第二个标定独立入口 (/points/plate_align), 同样与具体点位无关
const isPlateAlign = computed(() => route.params.category === 'plate_align')
// 刮板对刀为第三个标定独立入口 (/points/tool_align), 同样与具体点位无关
const isToolAlign = computed(() => route.params.category === 'tool_align')
// 刮痕标定为第四个标定独立入口 (/points/scrape_calib): 与对刀同修 plate_origin, 但策略不同
// (对刀=刀尖目视静态对角, 需 PLC 解封; 刮痕标定=刮已知图案拍照测三链合量, 不依赖对位动作)
const isScrapeCalib = computed(() => route.params.category === 'scrape_calib')
// 网格库位 (货架): 仿射算出的计算点, 无单条源片段/示教入口 -> 改展示货架示意图
const isGridSlot = computed(
  () =>
    !!d.value &&
    d.value.category === 'robot' &&
    typeof d.value.derivation === 'string' &&
    d.value.derivation.startsWith('grid_affine'),
)

const title = computed(() => {
  const v = d.value
  if (!v) return ''
  // 机器人点: 中文名 (labels.yaml) + 控制器点名 P 号; 未登记中文名时回退英文 alias (与侧栏树同规则)
  if (v.category === 'robot') {
    if (!v.label) return v.alias || v.id
    return /^P\d+$/.test(v.robot_name || '') ? `${v.label} ${v.robot_name}` : v.label
  }
  if (v.category === 'plc_servo' || v.category === 'plc_servo_target' || v.category === 'plc_servo_composite') return v.label
  return v.id
})

// plc_servo: 路径 T 下仅余地轨「离散召回位」(其余连续伺服轴已迁 plc_servo_target flat 逐点示教)
const servoTeachNote = computed(() => {
  const v = d.value
  if (!v || v.category !== 'plc_servo') return ''
  if (v.sync)
    return '地轨为「离散召回位」模型, 坐标真源已收编到 PC (canonical)：自动派发器读 PLC 的 flat 数组 Rail_Pos_Target[位码] (slot 即下标)，HMI position[] 降为手动示教工作副本。下方可编辑该站点 PC 真源，并在工位级做 push / pull / diff 对账 (PC↔HMI 经 PLC flat 镜像 Rail_Pos_HMI，不直访 struct)。真机依赖 Rail_Sync POU + 5 个变量 (见 docs/PLC交付_地轨双源同步)。'
  return '该点为「离散召回位」(struct 槽位模型)，所在工位未配置 sync 双源同步契约，仅作只读配置展示。'
})

const rows = computed(() => {
  const v = d.value
  if (!v) return []
  if (v.category === 'robot') {
    return [
      ['point_id', v.id],
      ['robot_name', v.robot_name],
      ['中文名', v.label || '— (未登记于 robot/labels.yaml)'],
      ['别名', v.alias],
      ['工位', v.workstation],
      ['角色', v.role],
      ['状态', v.status],
      ['最近示教', v.calibrated_at || '—'],
      ['允许运动', (v.allowed_motion || []).join(' / ') || '—'],
      ['pose', (v.pose || []).join(', ')],
      ['joint', v.joint ? v.joint.join(', ') : '— (派生 / 直线点)'],
      ['acc / vel / cp', `${v.acc} / ${v.vel} / ${v.cp}`],
      ['user / tool', `${v.user} / ${v.tool}`],
      ['派生自', v.derived_from || '—'],
      ['派生式', v.derivation || '—'],
      ['备注', v.notes || '—'],
    ]
  }
  if (v.category === 'plc_servo') {
    return [
      ['key', v.id],
      ['标签', v.label],
      ['HMI struct 节点', v.node],
      ['工位', v.workstation],
      ['角色', v.role],
      ['槽位 slot (=数组下标)', v.slot],
      ['PC 真源 value', v.value == null ? '— (未收编)' : v.value],
      ['限位 min ~ max', `${v.limits.min} ~ ${v.limits.max}`],
      ['备份值', v.backup == null ? '—' : v.backup],
    ]
  }
  if (v.category === 'plc_servo_target') {
    const hmi = v.hmi_node
      ? v.hmi_node + (v.hmi_slot != null ? `.position[${v.hmi_slot}]` : '')
      : '—'
    return [
      ['key', v.id],
      ['标签', v.label],
      ['目标节点 (PC写)', v.node],
      ['实际位镜像 (只读)', v.actpos || '—'],
      ['HMI 绑定 (路径T: HMI改读上列目标)', hmi],
      ['工位', v.workstation],
      ['存储值 value', v.value],
      ['限位 min ~ max', `${v.limits.min} ~ ${v.limits.max}`],
      ['限位源', v.limit_source ? '是 (value 仅作软限位, 不可手动存值/下发; 真实下发走仿射 push_well)' : '否'],
      ['PLC 节点', v.pending ? '待建 (pending: 可离线存值, 读实际位/下发暂禁)' : '就绪'],
    ]
  }
  if (v.category === 'plc_servo_composite') {
    return [
      ['key', v.id],
      ['标签', v.label],
      ['工位', v.workstation],
      ['子坐标', (v.members || []).map((m) => m.label).join(' / ')],
    ]
  }
  return []
})

// ---- 原始 yaml/json 浏览与编辑: 文件列表 = config/points/ 下真实文件 (目录即视图) ----
const RAW_KINDS = ref([]) // [{kind, label}], 由后端枚举 (stations.yaml / plc/*.yaml / robot 真源)
const rawKind = ref('')
const rawText = ref('')
const rawPath = ref('')
const rawMsg = ref('')
const rawBusy = ref(false)
const rawSnapshot = ref('') // 载入/保存成功时的全文快照 (dirty 判据)
const rawDirty = computed(() => rawText.value !== rawSnapshot.value)
let rawKindLoaded = '' // 当前 rawText 对应的文件 kind; 切换被取消时回退到它
let rawLoading = false // 防 watch 触发与显式调用同 tick 双载

useQuerySync('raw', rawKind) // 选中文件进 URL: 刷新不丢/可深链

// 未保存守卫: 原始文件整文编辑 (路由离开 + 刷新/关标签); confirmDiscard 供页内切换复用
const { confirmDiscard: confirmDiscardRaw } = useDirtyGuard(() => rawDirty.value, {
  message: '原始 yaml 有未保存修改, 离开将丢弃。',
})

async function loadRawFiles() {
  try {
    RAW_KINDS.value = await api.listPointsRawFiles()
    if (!rawKind.value && RAW_KINDS.value.length) rawKind.value = RAW_KINDS.value[0].kind
  } catch (e) {
    rawMsg.value = '文件列表加载失败: ' + errText(e)
  }
}

async function loadRaw() {
  if (!rawKind.value || rawLoading) return
  rawLoading = true
  rawMsg.value = ''
  const kind = rawKind.value
  try {
    const r = await api.getPointsRaw(kind)
    rawText.value = r.text
    rawPath.value = r.path
    rawSnapshot.value = r.text
    rawKindLoaded = kind
  } catch (e) {
    rawMsg.value = '读取失败: ' + errText(e)
  } finally {
    rawLoading = false
  }
}

// 文件切换统一走 watch (下拉 v-model 与 URL 前进/后退同一条路): 先拦脏, 取消则回退选择
watch(rawKind, async (k) => {
  if (!k || k === rawKindLoaded) return
  if (rawDirty.value && !(await confirmDiscardRaw('原始文件有未保存修改, 切换文件将丢弃。'))) {
    rawKind.value = rawKindLoaded
    return
  }
  loadRaw()
})

async function saveRaw() {
  rawBusy.value = true
  rawMsg.value = ''
  try {
    const r = await api.savePointsRaw(rawKind.value, rawText.value)
    rawMsg.value = '已保存 ✓' + (r.points ? ` (${r.points} 点已重载)` : '')
    rawSnapshot.value = rawText.value
    points.loadTree(true) // 刷新左侧点位树
  } catch (e) {
    rawMsg.value = '保存失败: ' + errText(e)
  } finally {
    rawBusy.value = false
  }
}

async function ensureRawLoaded() {
  if (!RAW_KINDS.value.length) await loadRawFiles()
  if (!rawText.value) loadRaw()
}

async function switchTab(t) {
  if (t === tab.value) return
  // 离开原始 yaml 页签: 脏则确认; 确认放弃即回退快照, 避免"已放弃"的改动暗存
  if (tab.value === 'raw' && rawDirty.value) {
    if (!(await confirmDiscardRaw())) return
    rawText.value = rawSnapshot.value
  }
  tab.value = t
  if (t === 'raw') ensureRawLoaded()
}

// 深链/刷新直达 raw 页签时补做首载 (不经过 switchTab)
onMounted(() => {
  if (tab.value === 'raw') ensureRawLoaded()
})

// 注: plc_servo (HMI struct 点) 为只读配置展示 —— B 方案下 HMI position[] 不经 OPC, 上位机对 PLC
// 位置的示教统一走下方 plc_servo_target 的 flat 流程, 故此处不再有伺服实时读写。

// ---- PC 侧 flat 目标点位 (点样/拍照): 读 actpos 镜像 / 存 value / 下发 *_Target ----
const tgtActpos = ref(null)
const tgtValue = ref('')
const tgtMsg = ref('')
const tgtBusy = ref(false)

// 读取实际位: 独立 busy (在途去重防连发), 错误仍落 tgtMsg
const readTgt = useAsyncAction(
  async () => {
    tgtMsg.value = ''
    tgtActpos.value = (await api.getTargetActpos(d.value.id)).actpos
  },
  { errorPrefix: '读取失败', onError: (msg) => { tgtMsg.value = msg } },
)
function fillFromActpos() {
  if (tgtActpos.value != null) tgtValue.value = String(tgtActpos.value)
}
async function saveTargetValue() {
  const v = Number(tgtValue.value)
  if (Number.isNaN(v)) {
    tgtMsg.value = '请输入数值'
    return
  }
  tgtBusy.value = true
  tgtMsg.value = ''
  try {
    const r = await api.setTargetValue(d.value.id, v)
    tgtMsg.value = `已存为点位值 ✓ (value = ${r.value}, 持久化于 points.yaml)`
    points.loadTree(true)
    points.loadDetail('plc_servo_target', d.value.id)
  } catch (e) {
    tgtMsg.value = '保存失败: ' + errText(e)
  } finally {
    tgtBusy.value = false
  }
}
async function pushTarget() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '下发伺服目标位',
    message: `确认把「${d.value.label}」存储值下发到 PLC 节点 ${d.value.node}? (B方案单写者; 仅写目标, 运动由后续 L2 触发)`,
    ackText: '我已确认现场无干涉, 允许写入伺服目标位',
    confirmText: '下发',
  })
  if (!ok) return
  tgtBusy.value = true
  tgtMsg.value = ''
  try {
    const r = await api.pushTarget(d.value.id)
    tgtMsg.value = `已下发 ✓ (${r.node} = ${r.written})`
  } catch (e) {
    tgtMsg.value = '下发失败: ' + errText(e)
  } finally {
    tgtBusy.value = false
  }
}

// ---- 组合点位 (点样位置): 逐成员读 actpos / 存子坐标 value, 整体下发各成员 *_Target ----
// memState 按成员 key 存 { actpos, value, msg }; d 加载时由 watch 预置 (避免 render 期惰性建对象)
const memState = ref({})
const compBusy = ref(false)
const compMsg = ref('')

// 成员读/存共用一条在途去重链 (同一 PLC 通道); 错误按最近操作的成员落到各自 msg 位
let memberInFlight = null
function memberMsgSink(msg) {
  const st = memberInFlight && memState.value[memberInFlight.key]
  if (st) st.msg = msg
}
const readMember = useAsyncAction(
  async (m) => {
    memberInFlight = m
    const st = memState.value[m.key]
    st.msg = ''
    st.actpos = (await api.getCompositeMemberActpos(d.value.id, m.key)).actpos
  },
  { errorPrefix: '读取失败', onError: memberMsgSink },
)
function fillMember(m) {
  const e = memState.value[m.key]
  if (e.actpos != null) e.value = String(e.actpos)
}
const saveMember = useAsyncAction(
  async (m) => {
    memberInFlight = m
    const st = memState.value[m.key]
    const v = Number(st.value)
    if (Number.isNaN(v)) {
      st.msg = '请输入数值'
      return
    }
    st.msg = ''
    const r = await api.setCompositeMemberValue(d.value.id, m.key, v)
    // 不重载详情: 值已持久化且输入框即真值, 重载会重置 memState 抹掉本提示
    st.msg = `已存为子坐标值 ✓ (${r.value})`
  },
  { errorPrefix: '保存失败', onError: memberMsgSink },
)
async function pushComposite() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '下发点样位置目标',
    message: `确认把「${d.value.label}」三个子坐标下发到 PLC? (B方案单写者; 仅写目标, 运动由后续 L2 触发)`,
    ackText: '我已确认现场无干涉, 允许写入伺服目标位',
    confirmText: '下发',
  })
  if (!ok) return
  compBusy.value = true
  compMsg.value = ''
  try {
    const r = await api.pushComposite(d.value.id)
    compMsg.value = '已下发 ✓ (' + r.written.map((w) => `${w.node} = ${w.written}`).join(', ') + ')'
  } catch (err) {
    compMsg.value = '下发失败: ' + errText(err)
  } finally {
    compBusy.value = false
  }
}

// ---- plc_servo 离散召回位 (地轨): PC 真源 value 编辑 + 工位级双源同步 (push/pull/diff) ----
const svValue = ref('')
const svMsg = ref('')
const svBusy = ref(false)
const syncRows = ref(null) // diff 结果 [{key,label,slot,pc_value,hmi_value,delta,over}]
const syncAnyOver = ref(false)
const syncMsg = ref('')
const syncBusy = ref(false)
const pullPreview = ref(null) // pull confirm=false 的 {key: 教出值}

async function saveServoValue() {
  const v = Number(svValue.value)
  if (Number.isNaN(v)) {
    svMsg.value = '请输入数值'
    return
  }
  svBusy.value = true
  svMsg.value = ''
  try {
    const r = await api.setServoValue(d.value.id, v)
    svMsg.value = `已存为 PC 真源 ✓ (value = ${r.value}, 持久化于 plc/<工位>.yaml)`
    points.loadTree(true)
    points.loadDetail('plc_servo', d.value.id)
  } catch (e) {
    svMsg.value = '保存失败: ' + errText(e)
  } finally {
    svBusy.value = false
  }
}

async function doDiff() {
  syncBusy.value = true
  syncMsg.value = ''
  pullPreview.value = null
  try {
    const r = await api.syncDiff(d.value.workstation)
    syncRows.value = r.points
    syncAnyOver.value = r.any_over
    syncMsg.value = `偏差检查完成 (阈值 ${r.threshold})：${r.any_over ? '存在超阈点 ⚠' : '全部在阈内 ✓'}`
  } catch (e) {
    syncMsg.value = '偏差检查失败: ' + errText(e)
  } finally {
    syncBusy.value = false
  }
}

async function doPush() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '下发工位真源',
    message: `确认把工位「${d.value.workstation}」全部站点 PC 真源 push 到 PLC? (写 Rail_Pos_Target 并同步 HMI 面板工作副本; 安全, 只覆盖副本)`,
    ackText: '我已确认现场无干涉, 允许写入伺服目标位',
    confirmText: '下发真源',
  })
  if (!ok) return
  syncBusy.value = true
  syncMsg.value = ''
  try {
    const r = await api.syncPush(d.value.workstation)
    syncMsg.value = `已下发真源 ✓ (${r.target_node} = [${r.written.join(', ')}])` +
      (r.mirror_synced ? `；HMI 面板已同步 (Ack=${r.ack})` : '；⚠ 邮箱握手未确认 (真机 Rail_Sync 未就绪? 真源仍已写入)')
  } catch (e) {
    syncMsg.value = '下发失败: ' + errText(e)
  } finally {
    syncBusy.value = false
  }
}

async function doPullPreview() {
  syncBusy.value = true
  syncMsg.value = ''
  try {
    const r = await api.syncPull(d.value.workstation, false)
    pullPreview.value = r.preview
    syncMsg.value = '已读取现场教值 (经 PLC flat 镜像)；核对下表，确认后再提交写真源。'
  } catch (e) {
    pullPreview.value = null
    syncMsg.value = '回收预览失败: ' + errText(e)
  } finally {
    syncBusy.value = false
  }
}

async function doPullCommit() {
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '回收示教写真源',
    message: '把现场教值收回写为 PC 真源 (改写 plc/<工位>.yaml + 重算 Rail_Pos_Target)。',
    ackText: '我已确认现场教值正确, 覆盖 PC 真源',
    confirmText: '提交写真源',
  })
  if (!ok) return
  syncBusy.value = true
  syncMsg.value = ''
  try {
    const r = await api.syncPull(d.value.workstation, true)
    syncMsg.value = `已回收并写真源 ✓ (${Object.keys(r.values).length} 点已提交)`
    pullPreview.value = null
    syncRows.value = null
    points.loadTree(true)
    points.loadDetail('plc_servo', d.value.id)
  } catch (e) {
    syncMsg.value = '回收提交失败: ' + errText(e)
  } finally {
    syncBusy.value = false
  }
}

// ---- 单点原始片段 (机器人): 只看/改当前点对应的源条目 (避免整文件冗长) ----
const ptRaw = ref('')
const ptRawFiles = ref(null)
const ptRawDerived = ref(false)
const ptRawLoaded = ref(false)
const ptRawMsg = ref('')
const ptRawBusy = ref(false)
const ptRawSnapshot = ref('') // 载入/保存成功时的片段快照 (dirty 判据)
const ptRawDirty = computed(() => ptRawLoaded.value && ptRaw.value !== ptRawSnapshot.value)
// 头部文件路径展示串 (模板截断显示, title 给全文)
const ptRawFilesText = computed(() => {
  if (!ptRawFiles.value) return ''
  return ptRawDerived.value ? ptRawFiles.value.meta : ptRawFiles.value.points + ' + ' + ptRawFiles.value.meta
})

// 未保存守卫: 本点片段编辑, 切点位 (同路由 :id 变化) 与路由离开都拦
useDirtyGuard(() => ptRawDirty.value, {
  message: '本点原始片段有未保存修改, 切换将丢弃。',
  paramKey: 'id',
})

async function loadPointRaw() {
  ptRaw.value = ''
  ptRawFiles.value = null
  ptRawLoaded.value = false
  ptRawMsg.value = ''
  ptRawSnapshot.value = ''
  if (!d.value || d.value.category !== 'robot') return
  if (isGridSlot.value) return // 网格库位无单条源片段 (由 meta.grids 拥有), 跳过避免 404
  try {
    const r = await api.getPointRaw('robot', d.value.id)
    ptRaw.value = r.text
    ptRawFiles.value = r.files
    ptRawDerived.value = r.is_derived
    ptRawLoaded.value = true
    ptRawSnapshot.value = r.text
  } catch (e) {
    ptRawMsg.value = '读取失败: ' + errText(e)
  }
}

async function savePointRaw() {
  ptRawBusy.value = true
  ptRawMsg.value = ''
  try {
    const r = await api.savePointRaw('robot', d.value.id, ptRaw.value)
    ptRawMsg.value = '已保存 ✓' + (r.points ? ` (${r.points} 点已重载)` : '')
    ptRawSnapshot.value = ptRaw.value
    points.loadTree(true)
    // 编辑 alias 可能改变 point_id, 后端回传新 id -> 重定位; 否则原地刷新详情
    if (r.point_id && r.point_id !== d.value.id) {
      router.push(`/points/robot/${encodeURIComponent(r.point_id)}`)
    } else {
      points.loadDetail('robot', d.value.id)
    }
  } catch (e) {
    ptRawMsg.value = '保存失败: ' + errText(e)
  } finally {
    ptRawBusy.value = false
  }
}

// ---- 机器人示教复核: 由 TeachVerify 组件承担 (当前点示教 + 退到进近点 + 二次进入 + 回位漂移 + 提交) ----
// 可示教 = 基础示教点 或 网格库位 (isGridSlot); offset 派生接近点不可独立示教。
const isTeachable = computed(
  () => !!d.value && d.value.category === 'robot' && (!d.value.is_derived || isGridSlot.value),
)

async function onTeachCommitted(payload) {
  await points.loadTree(true)
  const newId = payload && payload.result && payload.result.point_id
  if (newId && newId !== d.value.id) {
    router.push(`/points/robot/${encodeURIComponent(newId)}`)
  } else {
    await points.loadDetail('robot', d.value.id)
  }
}

// ---- 长按运行到此点位 (机器人; deadman: 长按 500ms 触发, 松手停, 限速 v=10) ----
const ARM_MS = 500
const runMotion = ref('move_j')
const runArmed = ref(false)
const runMoving = ref(false)
const runStatus = ref('')
let armTimer = null
let runPointerEl = null
let runPointerId = null

const canRun = computed(
  () =>
    !!d.value &&
    d.value.category === 'robot' &&
    sys.mode === 'DEBUG' &&
    Array.isArray(d.value.allowed_motion) &&
    d.value.allowed_motion.length > 0,
)

function pressRun(event) {
  if (!canRun.value || runMoving.value) return
  event.preventDefault()
  const el = event.currentTarget
  try {
    if (el) el.setPointerCapture(event.pointerId)
  } catch (_e) {
    // 某些场景无法捕获, 忽略
  }
  runPointerEl = el
  runPointerId = event.pointerId
  runArmed.value = true
  runStatus.value = `按住中… 保持 ${ARM_MS}ms 触发 (松开取消)`
  armTimer = window.setTimeout(fireRun, ARM_MS)
}

async function fireRun() {
  armTimer = null
  if (!runArmed.value) return // 已在计时途中释放
  runArmed.value = false
  runMoving.value = true
  runStatus.value = '运行中… 松手停止'
  try {
    const r = await api.runAction(
      'robot.move_to_point',
      { point_id_or_robot_name: d.value.id, motion: runMotion.value, acc: 20, vel: 10, cp: 0 },
      'DEBUG',
    )
    if (r.status === 'DONE') runStatus.value = '已到达 ✓'
    else if (r.status === 'CANCELLED') runStatus.value = '已停止 (未到达)'
    else runStatus.value = `${r.status || '?'}: ${r.message || ''}`
  } catch (e) {
    runStatus.value = '错误: ' + errText(e)
  } finally {
    runMoving.value = false
  }
}

async function releaseRun(event) {
  if (runPointerId !== null && event && event.pointerId !== runPointerId) return
  if (runPointerEl && runPointerId !== null) {
    try {
      if (runPointerEl.hasPointerCapture(runPointerId)) runPointerEl.releasePointerCapture(runPointerId)
    } catch (_e) {
      // 元素已失活, 忽略
    }
  }
  runPointerEl = null
  runPointerId = null
  if (armTimer !== null) {
    window.clearTimeout(armTimer)
    armTimer = null
    if (runArmed.value) runStatus.value = '已取消 (长按不足)'
  }
  runArmed.value = false
  if (runMoving.value) {
    // 运动中松手 -> 物理停止; in-flight 动作随后以 CANCELLED 收尾
    runStatus.value = '停止中…'
    try {
      await api.robotStop()
    } catch (_e) {
      // 松手停失败不覆盖现有状态
    }
  }
}

function resetRun() {
  if (armTimer !== null) {
    window.clearTimeout(armTimer)
    armTimer = null
  }
  runArmed.value = false
  runStatus.value = ''
}

// 详情加载完成后 (d 变化): 载入该点原始片段 + 设默认运动方式 (move_j, 无则首个允许动作)
watch(d, (v) => {
  loadPointRaw()
  if (v && v.category === 'robot' && Array.isArray(v.allowed_motion) && v.allowed_motion.length) {
    runMotion.value = v.allowed_motion.includes('move_j') ? 'move_j' : v.allowed_motion[0]
  }
  if (v && v.category === 'plc_servo_target') tgtValue.value = String(v.value)
  if (v && v.category === 'plc_servo') svValue.value = v.value == null ? '' : String(v.value)
  // 组合点位: 按成员预置示教态 (value 初值=存储值), 供模板直接索引 memState[key]
  if (v && v.category === 'plc_servo_composite') {
    const st = {}
    for (const m of v.members || []) st[m.key] = { actpos: null, value: String(m.value), msg: '' }
    memState.value = st
  }
})

const isDebug = computed(() => sys.mode === 'DEBUG')

// label↔input 显式关联 (布局是 flex 兄弟, 不便包裹, 走 useId + for/id)
const svInputId = useId()
const tgtInputId = useId()
const memInputBase = useId()

// 切走点位时若仍在运动, 安全停
function safetyStopRun() {
  if (runMoving.value) {
    try {
      api.robotStop()
    } catch (_e) {
      // 兜底, 忽略
    }
  }
}
onMounted(() => {
  window.addEventListener('blur', safetyStopRun)
  window.addEventListener('pagehide', safetyStopRun)
})
onBeforeUnmount(() => {
  window.removeEventListener('blur', safetyStopRun)
  window.removeEventListener('pagehide', safetyStopRun)
  safetyStopRun()
})

watch(
  () => [route.params.category, route.params.id],
  ([c, id]) => {
    safetyStopRun()
    points.loadDetail(c, id)
    tgtActpos.value = null
    tgtMsg.value = ''
    compMsg.value = ''
    svMsg.value = ''
    syncRows.value = null
    syncMsg.value = ''
    pullPreview.value = null
    resetRun()
  },
  { immediate: true },
)
</script>

<template>
  <!-- 孔板标定: 独立入口, 与选中点位无关 (自带实例下拉, 读 config/calibration.yaml) -->
  <div v-if="isCalib" class="detail calib-pane">
    <CalibratePanel />
  </div>

  <!-- 板位对位: 独立标定入口, 与选中点位无关 (视觉零点一键示教, .163 对位相机) -->
  <div v-else-if="isPlateAlign" class="detail calib-pane">
    <PlateAlignPanel />
  </div>

  <!-- 刮板对刀: 独立标定入口, 与选中点位无关 (刀尖核对刮取原点角, 修 gcode.plate_origin_x/y) -->
  <div v-else-if="isToolAlign" class="detail calib-pane">
    <ToolAlignPanel />
  </div>

  <!-- 刮痕标定: 独立标定入口 (刮已知图案 → 拍照测实刮位置 → 自动折进 gcode.plate_origin) -->
  <div v-else-if="isScrapeCalib" class="detail calib-pane">
    <ScrapeCalibPanel />
  </div>

  <div v-else class="detail">
    <div class="pt-tabs" role="tablist" aria-label="点位视图页签">
      <button type="button" role="tab" id="pt-tab-detail" aria-controls="pt-panel-detail"
        :tabindex="tabRoving.tabindex('detail')" :aria-selected="tab === 'detail'"
        :class="{ active: tab === 'detail' }" @click="switchTab('detail')" @keydown="tabRoving.onKeydown">点位详情</button>
      <button type="button" role="tab" id="pt-tab-raw" aria-controls="pt-panel-raw"
        :tabindex="tabRoving.tabindex('raw')" :aria-selected="tab === 'raw'"
        :class="{ active: tab === 'raw' }" @click="switchTab('raw')" @keydown="tabRoving.onKeydown">原始 yaml</button>
    </div>

    <!-- 点位详情 -->
    <div v-if="tab === 'detail'" id="pt-panel-detail" role="tabpanel" aria-labelledby="pt-tab-detail">
      <p v-if="!d" class="empty">从左侧「点位」选择一个点位查看详情 (机器人 / PLC伺服)</p>
      <div v-else>
        <h2>{{ title }} <small>{{ d.category }} · {{ d.id }}</small></h2>
        <table v-if="rows.length" class="pt-detail">
          <tbody>
            <tr v-for="[k, val] in rows" :key="k"><th>{{ k }}</th><td>{{ val }}</td></tr>
          </tbody>
        </table>
        <p v-else class="empty">该分类暂无点位</p>
        <div v-if="d.category === 'plc_servo'" class="servo-ops">
          <!-- 收编工位 (地轨): PC 真源 value 编辑 + 工位级双源同步 push/pull/diff -->
          <template v-if="d.sync">
            <div class="servo-row">
              <label :for="svInputId">PC 真源 value (限位 {{ d.limits.min }} ~ {{ d.limits.max }})</label>
              <input :id="svInputId" v-model="svValue" type="number" :min="d.limits.min" :max="d.limits.max" step="0.1" :disabled="!isDebug" />
              <button :disabled="svBusy || !isDebug" @click="saveServoValue">{{ svBusy ? '处理中…' : '存为真源 (DEBUG)' }}</button>
            </div>
            <p v-if="svMsg" class="servo-msg">{{ svMsg }}</p>

            <div class="sync-block">
              <h4>工位双源同步 · {{ d.workstation }}</h4>
              <div class="servo-row">
                <button :disabled="syncBusy" @click="doDiff">偏差检查 (diff)</button>
                <button :disabled="syncBusy || !isDebug" class="push-btn" @click="doPush">下发真源 (push)</button>
                <button :disabled="syncBusy || !isDebug" @click="doPullPreview">回收示教 (pull 预览)</button>
              </div>
              <table v-if="syncRows" class="sync-table">
                <thead><tr><th>站点</th><th>slot</th><th>PC 真源</th><th>HMI 教值</th><th>偏差</th></tr></thead>
                <tbody>
                  <tr v-for="r in syncRows" :key="r.key" :class="{ over: r.over }">
                    <td>{{ r.label }}</td><td>{{ r.slot }}</td>
                    <td class="num">{{ r.pc_value }}</td><td class="num">{{ r.hmi_value == null ? '—' : r.hmi_value }}</td>
                    <td class="num">{{ r.delta == null ? '—' : r.delta.toFixed(3) }}{{ r.over ? ' ⚠' : '' }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="pullPreview" class="pull-preview">
                <p class="muted">将提交的教出值 (经 PLC flat 镜像读取，已过限位校验)：</p>
                <ul><li v-for="(val, key) in pullPreview" :key="key">{{ key }} = {{ val }}</li></ul>
                <button :disabled="syncBusy || !isDebug" class="btn danger" @click="doPullCommit">确认提交写真源 (危险)</button>
              </div>
              <p v-if="syncMsg" class="servo-msg">{{ syncMsg }}</p>
            </div>
          </template>
          <p class="muted">{{ servoTeachNote }}</p>
        </div>

        <!-- PC 侧 flat 目标点位 (点样/拍照): 读实际位 → 存 value → 下发 *_Target -->
        <div v-else-if="d.category === 'plc_servo_target'" class="servo-ops">
          <!-- 限位源点位 (上样仿射轴): value 仅供软限位钳制, 手动存值/下发无意义且会误推 → 只读; 示教走孔板标定 -->
          <template v-if="d.limit_source">
            <div class="servo-row">
              <button :disabled="readTgt.busy" @click="readTgt.run()">{{ readTgt.busy ? '读取中…' : '读取实际位' }}</button>
              <span v-if="tgtActpos != null" class="servo-live">{{ d.actpos }} = {{ tgtActpos }}</span>
              <button class="link-btn" @click="router.push('/points/calibration')">→ 去孔板标定示教</button>
            </div>
            <p v-if="tgtMsg" class="servo-msg">{{ tgtMsg }}</p>
            <p class="muted">该点位为<strong>仿射轴 / 限位源</strong>: limits 仅供 CalibrationService 写前钳制 (防边角孔越程撞机)，value 为占位。示教走<strong>孔板标定</strong> (jog 到 3 孔读 *_ActPos → solve 仿射 → 持久化)；真实目标由仿射按孔实时计算下发 (push_well)，故此处不提供「存值 / 下发」。</p>
          </template>
          <template v-else>
            <p v-if="d.pending" class="pending-banner">⏳ PLC flat 节点待建 (pending)：可离线<strong>存值</strong>预示教；「读取实际位 / 下发」待 PLC 建 {{ d.node }} / {{ d.actpos }} 后开放 (排期: 5Z/地轨批次)。</p>
            <div class="servo-row">
              <button :disabled="d.pending || readTgt.busy" :title="d.pending ? 'PLC 节点待建, 暂不可读' : ''" @click="readTgt.run()">{{ readTgt.busy ? '读取中…' : '读取实际位 (jog 采点)' }}</button>
              <span v-if="tgtActpos != null" class="servo-live">{{ d.actpos }} = {{ tgtActpos }}</span>
              <button v-if="tgtActpos != null" @click="fillFromActpos">填入 ↓</button>
            </div>
            <div class="servo-row">
              <label :for="tgtInputId">点位值 value (限位 {{ d.limits.min }} ~ {{ d.limits.max }})</label>
              <input :id="tgtInputId" v-model="tgtValue" type="number" :min="d.limits.min" :max="d.limits.max" step="0.1" />
              <button :disabled="tgtBusy" @click="saveTargetValue">{{ tgtBusy ? '处理中…' : '存为点位值 (DEBUG)' }}</button>
            </div>
            <div class="servo-row">
              <button :disabled="tgtBusy || d.pending" class="push-btn" @click="pushTarget">下发到 PLC ({{ d.node }})</button>
            </div>
            <p v-if="tgtMsg" class="servo-msg">{{ tgtMsg }}</p>
            <p class="muted">路径 T 单一真源: value 是 PC 侧真值 (持久化于 plc/&lt;工位&gt;.yaml, 因 flat 节点不 retain)。「存为点位值」改配置真源；「下发」把真值写到 PLC <strong>*_Target</strong> (仅写目标，不运动)；HMI 面板改读同一 *_Target 故无代差。运行流程会在点样/拍照 L2 触发前自动下发。编辑/下发仅 DEBUG。</p>
          </template>
        </div>

        <!-- 组合点位 (点样位置): 逐成员 jog 采点 → 存子坐标值 → 整体下发各成员 *_Target -->
        <div v-else-if="d.category === 'plc_servo_composite'" class="servo-ops">
          <div v-for="m in (d.members || [])" :key="m.key" class="comp-member">
            <strong class="comp-mlabel">{{ m.label }} <small>{{ m.node }} · 限位 {{ m.limits.min }} ~ {{ m.limits.max }}</small></strong>
            <div class="servo-row">
              <button :disabled="readMember.busy" @click="readMember.run(m)">{{ readMember.busy ? '读取中…' : '读取实际位 (jog 采点)' }}</button>
              <span v-if="memState[m.key] && memState[m.key].actpos != null" class="servo-live">{{ m.actpos }} = {{ memState[m.key].actpos }}</span>
              <button v-if="memState[m.key] && memState[m.key].actpos != null" @click="fillMember(m)">填入 ↓</button>
            </div>
            <div v-if="memState[m.key]" class="servo-row">
              <label :for="`${memInputBase}-${m.key}`">子坐标值 (限位 {{ m.limits.min }} ~ {{ m.limits.max }})</label>
              <input :id="`${memInputBase}-${m.key}`" v-model="memState[m.key].value" type="number" :min="m.limits.min" :max="m.limits.max" step="0.1" />
              <button :disabled="saveMember.busy" @click="saveMember.run(m)">{{ saveMember.busy ? '保存中…' : '存为点位值 (DEBUG)' }}</button>
            </div>
            <p v-if="memState[m.key] && memState[m.key].msg" class="servo-msg">{{ memState[m.key].msg }}</p>
          </div>
          <div class="servo-row">
            <button :disabled="compBusy" class="push-btn" @click="pushComposite">下发到 PLC (点样位置)</button>
          </div>
          <p v-if="compMsg" class="servo-msg">{{ compMsg }}</p>
          <p class="muted">路径 T 单一真源: 各子坐标 value 是 PC 侧真值 (持久化于 plc/&lt;工位&gt;.yaml, 因 flat 节点不 retain)。逐成员 jog 采点存值；「下发」把三个子坐标整体写到各自 PLC <strong>*_Target</strong> (仅写目标，不运动)。运行流程会在点样 L2 触发前自动下发。编辑/下发仅 DEBUG。</p>
        </div>

        <!-- 机器人点位: 长按运行 + 本点原始片段编辑 -->
        <div v-if="d.category === 'robot'" class="robot-ops">
          <div class="run-block">
            <div class="run-row">
              <label v-if="(d.allowed_motion || []).length > 1" class="run-motion">运动方式
                <select v-model="runMotion">
                  <option v-for="m in d.allowed_motion" :key="m" :value="m">{{ m }}</option>
                </select>
              </label>
              <button
                class="run-hold"
                :class="{ arming: runArmed, moving: runMoving }"
                :disabled="!canRun || runMoving"
                @pointerdown="pressRun"
                @pointerup.prevent="releaseRun"
                @pointercancel.prevent="releaseRun"
                @lostpointercapture="releaseRun"
              >{{ runMoving ? '运行中… 松手停止' : runArmed ? '继续按住…' : '按住运行到此点位' }}</button>
              <span v-if="runStatus" role="status" class="run-status">{{ runStatus }}</span>
            </div>
            <p class="hint">长按运行仅支持鼠标/触控按住; 键盘请使用目标位下发。</p>
            <p class="muted">长按 {{ ARM_MS }}ms 触发, 松手即停 (软停, 受控减速), 限速 v=10 (a=20, cp=0)；仅 DEBUG 模式。<span v-if="sys.mode !== 'DEBUG'">当前非 DEBUG, 已禁用。</span></p>
          </div>

          <!-- 网格库位 (货架): 仿射网格示意图 + 示教复核 (锚点→重解整架 / 非锚位→改偏置, 写回 meta.grids) -->
          <template v-if="isGridSlot">
            <RackDiagram :highlight="d.robot_name" />
            <div class="teach-block">
              <h4 class="teach-title">货架库位示教复核</h4>
              <TeachVerify
                :point-id="d.id"
                :robot-name="d.robot_name"
                :is-grid="true"
                :disabled="sys.mode !== 'DEBUG'"
                @committed="onTeachCommitted"
              />
            </div>
          </template>

          <!-- 非网格点: 基础示教点走示教复核; offset 派生接近点仅可编辑 supplement 条目 -->
          <template v-else>
            <div v-if="isTeachable" class="teach-block">
              <h4 class="teach-title">示教复核</h4>
              <TeachVerify
                :point-id="d.id"
                :robot-name="d.robot_name"
                :is-grid="false"
                :disabled="sys.mode !== 'DEBUG'"
                @committed="onTeachCommitted"
              />
            </div>
            <div v-else class="muted">该点为 offset 派生接近点 (base + offset)；不能独立示教，请示教其 base 点。下方可编辑其 supplement 条目 (base_point/offset/role)。</div>

            <div class="ptraw-block">
              <div class="ptraw-head">
                <h4>本点原始片段</h4>
                <button :disabled="!ptRawLoaded || ptRawBusy" @click="savePointRaw">{{ ptRawBusy ? '保存中…' : '保存' }}</button>
                <span v-if="ptRawFiles" class="raw-path" :title="ptRawFilesText">{{ ptRawFilesText }}</span>
              </div>
              <textarea v-model="ptRaw" class="raw-text ptraw-text" spellcheck="false" aria-label="本点原始片段内容"></textarea>
              <p v-if="ptRawMsg" class="raw-msg">{{ ptRawMsg }}</p>
              <p class="muted">{{ ptRawDerived ? '派生点: 编辑 supplement 条目 (base_point/offset/role 等)。' : '基础点: point = robot_points.json 条目, meta = overrides 覆盖项 (清空 meta 即移除覆盖)。' }} 保存走全量校验, 不通过不写盘；仅 DEBUG。</p>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- 原始 yaml/json 浏览与编辑 -->
    <div v-else class="raw-pane" id="pt-panel-raw" role="tabpanel" aria-labelledby="pt-tab-raw">
      <div class="raw-head">
        <!-- 文件切换的载入/脏拦截统一由 script 里 watch(rawKind) 处理 (URL 前进/后退同路) -->
        <select v-model="rawKind" aria-label="原始文件选择">
          <option v-for="k in RAW_KINDS" :key="k.kind" :value="k.kind">{{ k.label }}</option>
        </select>
        <button :disabled="rawBusy" @click="saveRaw">{{ rawBusy ? '保存中…' : '保存' }}</button>
        <span class="raw-path" :title="rawPath">{{ rawPath }}</span>
      </div>
      <textarea v-model="rawText" class="raw-text" spellcheck="false" aria-label="原始文件内容"></textarea>
      <p v-if="rawMsg" class="raw-msg">{{ rawMsg }}</p>
      <p class="muted">保存前后端会全量校验 (机器人点位过 PointRegistry 安全校验)；不通过返回错误且不写盘。robot_* 仅 DEBUG 模式可保存。</p>
    </div>
  </div>
</template>

<style scoped>
/* 页签: 下划线式, 与全局 .dock-tab (style.css) 同款规则 */
.pt-tabs { display: flex; gap: 2px; margin-bottom: 10px; border-bottom: 1px solid var(--border-soft); }
.pt-tabs button { padding: 6px 10px 7px; border: none; background: transparent; color: var(--subtle); cursor: pointer;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0; font-weight: 600; font-size: var(--fs-13);
  transition: background-color var(--transition-fast), color var(--transition-fast), box-shadow var(--transition-fast); }
.pt-tabs button:hover { color: var(--text); background: var(--hover); }
.pt-tabs button.active { color: var(--accent); box-shadow: inset 0 -2px 0 var(--accent); }
.pt-detail { border-collapse: collapse; margin-top: 10px; }
.pt-detail th { text-align: right; padding: 3px 12px 3px 0; color: var(--subtle); white-space: nowrap; vertical-align: top; font-weight: 600; }
.pt-detail td { padding: 3px 0; font-family: var(--font-mono); }
/* h2 标题样式已上提全局 (.detail h2, style.css) */
/* strong→h4 分节标题: 复位全局 .detail h4 的外边距/字号, 保持原 strong 行内观感 */
.sync-block h4, .ptraw-head h4 { margin: 0; font-size: 1em; }
h4.teach-title { margin: 0 0 4px; font-size: 1em; }
.raw-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
/* 长路径截断显示 (title 悬停给全文), 防止把 flex 行撑破 */
.raw-path { color: var(--muted); font-size: var(--fs-11); font-family: var(--font-mono);
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.raw-text { width: 100%; min-height: 60vh; font-family: var(--font-mono); font-size: var(--fs-12); white-space: pre; resize: vertical; }
.raw-msg { margin-top: 6px; font-family: var(--font-mono); font-size: var(--fs-12); }
.muted { color: var(--muted); margin-top: 12px; font-size: var(--fs-12); }
.servo-ops { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; }
.servo-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.servo-live { font-family: var(--font-mono); color: var(--accent); }
/* servo/PLC 操作区无专有 class 的次级按钮: 显式令牌化, 不再回退 UA 默认浅灰按钮
   (深色下 UA 浅灰底 #f0f0f0 + 继承的浅色字 → 灰字看不清); push/link 有专有样式、
   .btn 系 (含全局 btn danger) 走全局按钮体系, 故排除。
   disabled 用 muted 文字而非压暗 opacity, 保证深色下仍可读 */
.servo-row button:not(.push-btn):not(.btn):not(.link-btn),
.ptraw-head button,
.teach-head button:not(.push-btn) {
  padding: 6px 14px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-2); color: var(--text); font-weight: 600; cursor: pointer;
}
.servo-row button:not(.push-btn):not(.btn):not(.link-btn):hover:not(:disabled),
.ptraw-head button:hover:not(:disabled),
.teach-head button:not(.push-btn):hover:not(:disabled) {
  background: var(--hover); border-color: var(--accent); color: var(--accent);
}
.servo-row button:not(.push-btn):not(.btn):not(.link-btn):disabled,
.ptraw-head button:disabled,
.teach-head button:disabled {
  color: var(--muted); cursor: not-allowed;
}
.push-btn { background: var(--accent-strong); color: var(--on-accent); border: none; padding: 6px 16px; border-radius: 6px; cursor: pointer; font-weight: 600; }
.push-btn:disabled { opacity: 0.62; cursor: not-allowed; }
.servo-msg { font-family: var(--font-mono); font-size: var(--fs-12); margin: 6px 0; }
.link-btn { background: none; border: none; color: var(--accent); cursor: pointer; padding: 4px 6px; text-decoration: underline; }
.pending-banner { background: var(--warn-soft); border: 1px solid var(--warn); color: var(--warn-strong); padding: 6px 10px; border-radius: 6px; font-size: var(--fs-12); margin-bottom: 8px; }
/* 组合点位成员: 各子坐标一组示教控件, 虚线分隔 */
.comp-member { margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed var(--border); }
.comp-mlabel { display: block; margin-bottom: 6px; color: var(--subtle); }
.comp-mlabel small { color: var(--muted); font-weight: 400; font-family: var(--font-mono); }
.sync-block { margin-top: 12px; border-top: 1px dashed var(--border); padding-top: 10px; }
.sync-table { border-collapse: collapse; margin: 8px 0; font-size: var(--fs-12); }
.sync-table th, .sync-table td { border: 1px solid var(--border); padding: 3px 10px; text-align: right; font-family: var(--font-mono); }
.sync-table th { color: var(--subtle); font-weight: 600; }
.sync-table tr.over td { background: var(--bad-soft); color: var(--bad-strong); }
.pull-preview { background: var(--warn-soft); border: 1px solid var(--warn); border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
.pull-preview ul { margin: 4px 0; padding-left: 18px; font-family: var(--font-mono); font-size: var(--fs-12); }
/* 提交写真源按钮吃全局 .btn.danger (style.css), 不再自造实底红 */

/* 机器人: 长按运行 + 本点原始片段 */
.robot-ops { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; }
.run-block { margin-bottom: 14px; }
.run-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.run-motion { display: inline-flex; gap: 6px; align-items: center; color: var(--subtle); font-size: var(--fs-13); font-weight: 600; }
.run-hold {
  padding: 10px 22px; font-size: var(--fs-14); font-weight: 700; color: var(--on-accent);
  background: var(--accent-strong); border: none; border-radius: 8px; cursor: pointer;
  user-select: none; touch-action: none;
}
.run-hold.arming { background: var(--warn); }
.run-hold.moving { background: var(--bad); }
.run-hold:disabled { opacity: 0.62; cursor: not-allowed; }
.run-status { font-family: var(--font-mono); font-size: var(--fs-12); color: var(--accent); }
.teach-block { margin: 12px 0 14px; border-top: 1px dashed var(--border); padding-top: 10px; }
.teach-title { display: block; color: var(--subtle); font-weight: 600; margin-bottom: 4px; }
.ptraw-block { margin-top: 8px; }
.ptraw-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.ptraw-text { min-height: 32vh; }
</style>
