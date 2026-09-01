<script setup>
// 物料账本页: 五类物料 —— 盘位 (货架6板x6孔二态 + 中转托盘位A/B) / 上料 (上样料架两处, 纯传感器) /
// 玻璃板 (上下料仓板数 + 光电行程实测) / 溶剂 (余量 mL) / 板位 (点样座/刮板拍照台 有板/无板人工账)。
// 各类及其位置与传感器的真源是后端 config/material_topology.yaml, 经 /api/materials/topology
// 随 grid 一并下发 —— 本页不硬编码分类, 加一类物料只改那个 yaml。
// 每类是一个子路由 /materials/<cat> (左 Dock 切换), 本页只渲染当前那一类; 另有 log=记账流水。
// 账本是建议式的 (只预填输入框, 不参与执行决策), 故此页是它唯一的权威录入口。
// 货架库位另有板级在架人工账 (grid.rack, 有板/无板): 货架 12 路光电无信号, 在架只能人工记;
// "无板"参与决策 —— 后端统计剔除其孔位, 自动换板/预填/批次准入跳过该库位。板在中转时
// 其在架态由后端随中转占用维护 (本页只读显示「在中转」)。
// 板位人工账 (grid.seats) 与货架在架账同源同形, 但用途刻意更窄: 只供展示与人工同步,
// 不进统计、不进任何决策; 页面并列调度器的 samples.position 做对照, 不一致只标黄提示。
// 孔位二态: FRESH=可供一件未用耗材; USED=不可再供料 (空孔, 或装着已用件)。
// USED 两种情形由 sample_id 区分: 空=空孔; 非空=装着该样品的成品, 待人取走。
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { api, errText } from '../api'
import { confirmAction } from '../composables/confirmService.js'
import { useAsyncAction } from '../composables/useAsyncAction.js'
import { useSystemStore } from '../store'
import { useMaterialsStore } from '../stores/materials'
import { useSchedulerStore } from '../stores/scheduler'
import { fmtTime } from '../utils/format.js'
import FeedliftCalibWizard from '../components/FeedliftCalibWizard.vue'
import MaterialAudit from '../components/MaterialAudit.vue'
import CellAmountDialog from '../components/CellAmountDialog.vue'

const KINDS = [
  { key: 'collector', label: '接粉收集器', area: 'staging-a', areaLabel: '中转托盘位A' },
  { key: 'bottle', label: '收集瓶', area: 'staging-b', areaLabel: '中转托盘位B' },
]
const PLATES = [1, 2, 3, 4, 5, 6]
const HOLES = [1, 2, 3, 4, 5, 6]

const route = useRoute()
const sys = useSystemStore()
const materials = useMaterialsStore()
// 账本与流水都住在 store 里: 它同时接 material_state 推流 (App.vue 扇出), 于是本页
// 随流程自己变 —— 不必再靠人点刷新才看得见"托盘刚被取走"。人工录入路径一概不变,
// 每次写完仍立刻 reload 一把拿即时反馈, 推流只是把中间过程也画出来。
const grid = computed(() => materials.grid)
const events = computed(() => materials.events)
// 实时中 = 事件流连着 且 至少收到过一帧推流; 不用"距上次推送多少秒"那种要计时器才刷新的判据
const liveSynced = computed(() => sys.streamConnected && materials.pushed)
const err = ref('')
// 光电对账提示 (成功一次即显示结果; PLC 断链/符号未发布时显示原因)
const reconcileNote = ref('')
// 最近一次对账读到的原始输入字节: 12 位全 0 时要能分清"传感器说空"与"传感器没信号"
const reconcileRaw = ref(null)
// 升降板仓行程标定现状 {feed:{...}, waste:{...}}; 与账本分开取, 标定文件出问题不该让账本页空白。
// 采样/拟合/实测的交互全在 FeedliftCalibWizard 里, 此处只负责取数并把每仓状态传下去。
const feedliftCalib = ref(null)
const calibErr = ref('')

function calibOf(magazine) { return feedliftCalib.value?.[magazine] || null }

// 触及预警线的板仓整行标红: 上料仓看低料下限, 下料仓看快满上限 (与后端 _is_warn 同判据)
function magazineWarn(m) {
  const c = calibOf(m.magazine)
  if (!c) return false
  return m.magazine === 'waste' ? m.count >= c.warn_threshold : m.count <= c.warn_threshold
}

// 四类物料树 (后端 config/material_topology.yaml 单一真源); 分区标题与上料位置据此渲染
const cats = computed(() => grid.value?.topology?.categories || [])
function catOf(key) { return cats.value.find((c) => c.key === key) || null }
function catLabel(key, fallback) { return catOf(key)?.label || fallback }
function catHint(key) { return catOf(key)?.hint || '' }
// 某类下声明了传感器的位置 (上料分区按它渲染)
function locsOf(key) { return catOf(key)?.locations || [] }

// 当前子页: 四类物料 (tray/feed/glass/solvent, key 来自后端拓扑) + log=记账流水;
// 无参数时落在第一类 (与左 Dock 的缺省一致)
const activeCat = computed(() => route.params.cat || cats.value[0]?.key || 'tray')

// 在位快照: location_id -> 行; 无快照时为空 (从未对账过)
const presenceById = computed(() => {
  const map = {}
  for (const p of grid.value?.presence || []) map[p.location_id] = p
  return map
})
function presenceAt(locationId) { return presenceById.value[locationId] || null }
// 货架 12 库位的在位行 id 形如 rack.<kind>.<plate>
function presenceOf(kind, plate) { return presenceAt(`rack.${kind}.${plate}`) }

// 在位显示文案与配色: ok===null (上料无软件账) 只显现值不判对错
function presenceText(row) {
  if (!row) return '—'
  return row.present ? '有料' : '空'
}
function presenceClass(row) {
  if (!row) return 'muted'
  if (row.ok === null || row.ok === undefined) return 'di-plain'
  return row.ok ? 'di-ok' : 'di-bad'
}
function presenceTitle(row) {
  if (!row) return '尚未对账过, 点上方「在位对账」'
  const pol = row.polarity === 'nc' ? '常闭 NC (原始位0=有料)' : '常开 NO (原始位1=有料)'
  const vf = row.verified ? '极性已实证' : '⚠ 极性未核实'
  const cmp = row.ok === null || row.ok === undefined
    ? (row.verified ? '无软件账可比, 只显现值' : '极性未核实, 只显读数不判定')
    : (row.ok ? '与账本一致' : row.note || '与账本不一致')
  return `${row.sensor || ''} · ${pol} · ${vf}\n原始位=${row.raw ? 1 : 0} → ${presenceText(row)}\n${cmp}`
}

// (kind, plate, hole) -> 格; 供模板 O(1) 取用
const cellMap = computed(() => {
  const map = {}
  for (const c of grid.value?.cells || []) map[`${c.kind}/${c.plate}/${c.hole}`] = c
  return map
})
function cell(kind, plate, hole) { return cellMap.value[`${kind}/${plate}/${hole}`] || null }

// 该板是否正在中转区 (整板已搬去中转, 单件取放才落在它上面)
function stagedPlate(kind) {
  const area = KINDS.find((k) => k.key === kind)?.area
  return grid.value?.staging?.[area]?.plate ?? null
}

// 货架在架人工账 (kind, plate) -> 行; 在中转的板由后端不变量维护 (present=0 但不算缺板)
const rackMap = computed(() => {
  const map = {}
  for (const r of grid.value?.rack || []) map[`${r.kind}/${r.plate}`] = r
  return map
})
function rackOf(kind, plate) { return rackMap.value[`${kind}/${plate}`] || null }
// 缺板 = 人工记无板且非当前中转板 (整行淡化、统计剔除的判据, 与后端 absent_plates 同口径)
function isAbsent(kind, plate) {
  const r = rackOf(kind, plate)
  return !!r && !r.present && stagedPlate(kind) !== plate
}

// ── 板位 (点样座/刮板拍照台): 人工账 + 调度账并列对照 ─────────────────────────
// 这两处无在位传感器, 故没有"光电"列可看; 唯一的机器侧参照就是调度器的 samples.position。
// 两份账的定位刻意不同: 人工账管"现场此刻有没有板"(人拿走了就来这里同步),
// 调度账管"哪个样品被流程记在这儿"。不一致只标黄提示, 不自动改任何一边 (见 legend)。
const seatRows = computed(() => grid.value?.seats || [])
function seatPresent(seat) { return seatRows.value.find((s) => s.seat === seat)?.present === true }

// 调度器记在该座上的样品号 (可能多个 —— 那本身就是调度账自身的冲突, 一并列出让人看见)
const sched = useSchedulerStore()
const schedBySlot = computed(() => {
  const map = {}
  for (const batch of sched.snapshot?.batches || []) {
    for (const s of batch?.samples || []) {
      const pos = String(s?.position || '')
      if (!pos) continue
      ;(map[pos] ||= []).push(s.sample_id)
    }
  }
  return map
})
function schedAt(seat) { return schedBySlot.value[seat] || [] }
// 账实不符: 人工记有板但调度无样品 / 人工记无板但调度记着样品。只提示, 不处置。
function seatMismatch(seat) {
  return seatPresent(seat) !== (schedAt(seat).length > 0)
}
function seatMismatchText(seat) {
  if (!seatMismatch(seat)) return ''
  return seatPresent(seat)
    ? '人工记有板, 但调度器没有样品记在这里 (可能是人放的板, 或批次已结束)'
    : '调度器记着样品在这里, 但人工记无板 (可能是人手动取走后已同步, 或忘了同步)'
}

async function reload() {
  try {
    await materials.load()
    await materials.loadEvents(40)
    err.value = ''
  } catch (e) {
    err.value = errText(e)
  }
  // 标定单独取: 标定文件缺失/损坏只该让板仓那一节显示原因, 不该把整页账本清空
  try {
    feedliftCalib.value = await api.getFeedliftCalib()
    calibErr.value = ''
  } catch (e) {
    feedliftCalib.value = null
    calibErr.value = errText(e)
  }
}

// 动作组各自独立 busy (代替原整页单一锁): 哪组在途只禁哪组的按钮, 刷新不再殃及全页。
// 每个实例内部在途去重即连发保护; 失败文案统一落回 err (reload 成功会清 err, 语义同旧 act)。
const refreshA = useAsyncAction(reload)
const cellA = useAsyncAction(
  async (kind, plate, hole, state) => {
    await api.markMaterial({ kind, plate, hole, state })
    await reload()
  },
  { announce: '已记账', onError: (msg) => { err.value = msg } },
)
const plateA = useAsyncAction(
  async (kind, plate, state) => {
    await api.markMaterial({ kind, plate, state })
    await reload()
  },
  { announce: '已整板记账', onError: (msg) => { err.value = msg } },
)
const stagingA = useAsyncAction(
  async (area, plate) => {
    await api.setMaterialStaging(area, plate)
    await reload()
  },
  { announce: '已更新中转位', onError: (msg) => { err.value = msg } },
)
const countA = useAsyncAction(
  async (magazine, count) => {
    await api.setMaterialMagazine(magazine, count)
    await reload()
  },
  { announce: '已写入板数', onError: (msg) => { err.value = msg } },
)
const volumeA = useAsyncAction(
  async (bottle, ml) => {
    await api.setMaterialBottle(bottle, ml)
    await reload()
  },
  { announce: '已写入余量', onError: (msg) => { err.value = msg } },
)
const rackA = useAsyncAction(
  async (kind, plate, present) => {
    await api.setMaterialRack(kind, plate, present)
    await reload()
  },
  { announce: '已更新在架状态', onError: (msg) => { err.value = msg } },
)
// 在架/无板 点击翻转 (可逆, 不走危险确认; 与单孔翻转同准则)。缺行按有板算 (与显示同口径)
function toggleRack(kind, plate) {
  return rackA.run(kind, plate, !(rackOf(kind, plate)?.present ?? true))
}

// 板位有板/无板 点击翻转: 同样可逆, 不走危险确认。缺行按无板算 (与显示同口径)。
// 只写人工账 (POST /api/materials/seat), 不碰调度器的 samples.position。
const seatA = useAsyncAction(
  async (seat, present) => {
    await api.setMaterialSeat(seat, present)
    await reload()
  },
  { announce: '已更新板位状态', onError: (msg) => { err.value = msg } },
)
function toggleSeat(seat) {
  return seatA.run(seat, !seatPresent(seat))
}

// 整板装满 / 整板清空: 实验员补料后的常用录入; 清空覆盖 6 孔且无撤销, 走危险确认
async function markPlate(kind, plate, state) {
  if (state === 'USED') {
    const ok = await confirmAction({
      level: 'danger',
      title: '整板清空',
      message: '将 6 个孔全部标记为已用, 无撤销。',
      confirmText: '整板清空',
    })
    if (!ok) return
  }
  return plateA.run(kind, plate, state)
}
// 单孔点选翻转: FRESH <-> USED (成品孔点一下即视为已取走, 清掉样品号)
function toggleCell(kind, plate, hole) {
  const c = cell(kind, plate, hole)
  if (!c) return
  const next = c.state === 'FRESH' ? 'USED' : 'FRESH'
  return cellA.run(kind, plate, hole, next)
}
// 中转区占用纠正: 面板单跑 robot_* 叶子脚本不入账, 会导致此处与现场失同步; 置空无撤销走确认
async function setStaging(area, plate) {
  if (plate == null) {
    const ok = await confirmAction({
      level: 'danger',
      title: '中转位置空',
      message: '将把该中转位的账本记录置空, 无撤销。原板将按回到货架库位记账; 若实际已被拿走, 请再把该库位标为无板。',
      confirmText: '置空',
    })
    if (!ok) return
  }
  return stagingA.run(area, plate)
}

// 光电对账: 读 PLC 12 位料库检测与账本比对。只报不改 —— 光电只知板级, 知不了孔级余量。
const reconA = useAsyncAction(
  async () => {
    reconcileNote.value = ''
    const res = await api.reconcileMaterials()
    materials.grid = res.grid
    reconcileRaw.value = res.raw || null
    await materials.loadEvents(40)
    const judged = (res.rows || []).filter((r) => r.ok === true || r.ok === false).length
    reconcileNote.value = res.mismatches
      ? `在位对账: ${res.mismatches} 处与账本不一致 (见下方传感器列标红)`
      : `在位对账: ${judged} 个可判定位置与账本一致 (未实证/无软件账的位置只显示读数)`
    err.value = ''
  },
  {
    errorPrefix: '光电对账失败',
    onError: (msg) => {
      reconcileRaw.value = null
      err.value = msg
    },
  },
)

// 玻璃板仓板数 / 溶剂瓶余量 人工录入 (硬件都测不出量, 只能盘点)。
// 入口先与当前账本值比较, 同值直接跳过 —— 回车提交后紧跟的 change 双发在此拦下。
function setMagazine(magazine, value) {
  const count = Number(value)
  if (!Number.isFinite(count) || count < 0) return
  const next = Math.round(count)
  const cur = (grid.value?.magazines || []).find((m) => m.magazine === magazine)
  if (cur && next === cur.count) return
  return countA.run(magazine, next)
}
function setBottle(bottle, value) {
  const ml = Number(value)
  if (!Number.isFinite(ml) || ml < 0) return
  const cur = (grid.value?.bottles || []).find((b) => b.bottle === bottle)
  if (cur && ml === cur.volume_ml) return
  return volumeA.run(bottle, ml)
}
function bumpMagazine(magazine, delta) {
  const cur = (grid.value?.magazines || []).find((m) => m.magazine === magazine)
  if (!cur) return
  return setMagazine(magazine, Math.max(0, cur.count + delta))
}
// 溶剂「装满」直接把余量改写为瓶容量, 覆盖账面值, 走危险确认
async function fillBottle(b) {
  const ok = await confirmAction({
    level: 'danger',
    title: '溶剂装满',
    message: `将把「${b.label}」余量改写为瓶容量 ${b.capacity_ml.toFixed(0)} mL, 覆盖当前账面值。`,
    confirmText: '装满',
  })
  if (!ok) return
  return volumeA.run(b.bottle, b.capacity_ml)
}

function cellClass(c, kind, plate) {
  if (!c) return ''
  if (c.state === 'FRESH') return 'c-fresh'
  return c.sample_id ? 'c-filled' : 'c-empty'
}
function cellTitle(c) {
  if (!c) return ''
  if (c.state === 'FRESH') return '有未用耗材, 可取'
  return c.sample_id ? `成品待取 · 样品 ${c.sample_id}` : '空孔'
}

// ── 单件内容物装量 (粉桶里的硅胶粉 mm³ / 样品瓶里的淋洗液 mL) ────────────────
// 量纲与名义容量的真源是后端 material_topology.yaml 的 tray.contents, 前端不硬编码 ——
// **没声明的 kind 整条装量条不渲染**, 而不是画成 0%: 与 presenceText 返回 '—' 同一条纪律,
// "不知道"不许画成一个数。
// 两个量都无任何测量硬件 (粉按视觉轮廓面积×切深×松散系数估, 液按动作参数算), 估错由人
// 覆盖 (POST /api/materials/cell_amount) —— 与溶剂瓶余量同一处境。
const contentSpecs = computed(() => Object.fromEntries(
  cats.value.flatMap((c) => c.contents || []).map((c) => [c.kind, c]),
))
/** 该 kind 每格装的是哪一列 (粉桶看 powder_mm3, 样品瓶看 liquid_ml) */
const CONTENT_COLUMN = { collector: 'powder_mm3', bottle: 'liquid_ml' }

function contentAmount(kind, c) {
  const column = CONTENT_COLUMN[kind]
  const value = column && c ? Number(c[column]) : NaN
  return Number.isFinite(value) ? value : 0
}
/** 装量百分比; 未声明容量 / 无格 一律 null -> 整条不渲染 */
function contentPct(kind, c) {
  const spec = contentSpecs.value[kind]
  if (!spec || !(spec.capacity > 0) || !c) return null
  return Math.round(Math.min(100, Math.max(0, contentAmount(kind, c) / spec.capacity * 100)))
}
/** 装量的可读文本, 并进按钮既有的 aria-label 与 title —— 条本身 aria-hidden */
function contentText(kind, c) {
  const pct = contentPct(kind, c)
  if (pct === null) return ''
  const spec = contentSpecs.value[kind]
  const amount = contentAmount(kind, c)
  const digits = spec.unit === 'mL' ? 2 : 0
  let text = `${spec.label} ${amount.toFixed(digits)} ${spec.unit} (占 ${pct}%)`
  if (kind === 'collector' && c.eluted) text += ' · 已淋洗'
  return text
}
/** 每类"装着东西"的格数, 与 可用/已用/成品待取 并列 */
function loadedCount(kind) {
  return (grid.value?.cells || [])
    .filter((c) => c.kind === kind && contentAmount(kind, c) > 0).length
}

// ── 在途载荷 ────────────────────────────────────────────────────────────────
const CARRIER_LABELS = { gripper_plate96: '大夹爪', gripper_vial: '小夹爪' }
const LOC_LABELS = { rack: '货架', staging: '中转位' }
const transitRows = computed(() => Object.values(materials.transit))
// 工位夹具上的**单件耗材** (payload_seats): 只列带孔号的行 —— 整板不落工位座, 无孔号也
// 定位不到格。⚠ 与上面的 seatRows 不是一回事: 那个是薄层板的停放位 (点样座/刮板拍照台)。
const payloadSeatRows = computed(() => (grid.value?.payload_seats || []).filter((r) => r.hole))
function carrierLabel(carrier) { return CARRIER_LABELS[carrier] || carrier }
function locLabel(loc) { return LOC_LABELS[loc] || loc }
function kindLabel(kind) { return KINDS.find((k) => k.key === kind)?.label || kind }
function sinceText(sinceAt) {
  const secs = Math.max(0, Math.round(Date.now() / 1000 - Number(sinceAt || 0)))
  return secs < 60 ? `已 ${secs} 秒` : `已 ${Math.round(secs / 60)} 分钟`
}

// 人工清账: 只有流程中途取消/断电才用得上。三个去向都要人明确选, 不替他猜 ——
// 猜错的后果是下一次 plan_staging 拿着错账去撞机。故走危险确认。
const transitA = useAsyncAction(
  async (carrier, landAt) => {
    await api.clearMaterialTransit(carrier, landAt)
    await reload()
  },
  { announce: '已清在途', onError: (msg) => { err.value = msg } },
)
async function clearTransit(row, landAt) {
  const where = landAt === '' ? '不记落位 (去向随后自行更正)' : `记作落在${locLabel(landAt)}`
  const ok = await confirmAction({
    title: '清掉在途载荷',
    message: [
      `把${carrierLabel(row.carrier)}上的 ${kindLabel(row.kind)} ${row.plate} 号板${where}。`,
      '请先确认现场实物确实如此 —— 换板决策 (plan_staging) 会据此放行, 记错会撞机。',
    ],
    detail: `${row.carrier} · ${row.kind} 板${row.plate}${row.hole ? ` 孔${row.hole}` : ''}`,
    level: 'danger',
    confirmText: '确认清账',
  })
  if (!ok) return
  return transitA.run(row.carrier, landAt)
}

// ── 件位 (holder) 人工盘点: 清账 + 放件 ─────────────────────────────────────
// 座位账通常由流程事件维护; 人工入口只在盘点发现账实不符时用。
// 清账不猜去向 (与清在途的 land_at='' 同纪律), 放件是清账的反向。
const payloadSeatA = useAsyncAction(
  async (seat, identity = null) => {
    await api.setMaterialPayloadSeat(seat, identity)
    await reload()
  },
  { announce: '已更新件位', onError: (msg) => { err.value = msg } },
)
async function clearPayloadSeat(row) {
  const ok = await confirmAction({
    level: 'danger',
    title: '清件位账',
    message: [
      `将清掉「${row.label || row.seat}」上的 ${kindLabel(row.kind)} ${row.plate} 号板 · ${row.hole} 号孔记录。`,
      '件被拿去了哪里账本不猜 —— 孔位状态请随后在盘位页自行更正。',
    ],
    confirmText: '清账',
  })
  if (!ok) return
  return payloadSeatA.run(row.seat)
}

// 件位子页: 三个座 (拓扑驱动), 账面行按座号反查; 放件表单一次只展开一行
const holderSeats = computed(() => catOf('holder')?.payload_seats || [])
function seatedOf(seatId) {
  return (grid.value?.payload_seats || []).find((r) => r.seat === seatId) || null
}
const placing = ref(null)   // {seat, kind, plate, hole} 或 null
function startPlacing(seatSpec) {
  placing.value = { seat: seatSpec.id, kind: seatSpec.accepts, plate: 1, hole: 1 }
}
async function submitPlacing(seatSpec) {
  const p = placing.value
  if (!p) return
  const ok = await confirmAction({
    level: 'danger',
    title: '人工放件',
    message: [
      `将把 ${kindLabel(p.kind)} ${p.plate} 号板 · ${p.hole} 号孔的件记到「${seatSpec.label}」上。`,
      '只记座位账, 不改托盘孔账 —— 请确认现场那只件确实停在该夹具上。',
    ],
    confirmText: '放件',
  })
  if (!ok) return
  await payloadSeatA.run(p.seat, { kind: p.kind, plate: p.plate, hole: p.hole })
  placing.value = null
}

// ── 装量对话框 (粉 mm³ / 液 mL / 已淋洗): 整板 6 孔一次编辑 ──────────────────
const cellAmountFor = ref(null)   // {kind, plate} 或 null
function plateCells(kind, plate) {
  return (grid.value?.cells || []).filter((c) => c.kind === kind && c.plate === plate)
}

onMounted(() => {
  reload()
  // 板位一节要并列显示调度器记的样品; 只拉一帧 (不开轮询 —— 这里是对照参考, 不是看板)。
  // 快照拉不到不影响本页: schedAt() 退化成空数组, 那一列显 "—"。
  sched.ensureSnapshot()
})
</script>

<template>
  <div class="mat-view">
    <div class="mat-head">
      <h2>物料账本</h2>
      <span class="muted mat-note">
        建议式账本: 只用于预填运行前输入框, 不否决任何动作。最终以现场确认为准。
      </span>
      <span class="mat-live" :class="{ off: !liveSynced }"
            :title="liveSynced ? '正在接收上位机推流, 本页随流程自动更新'
                               : '事件流未连通, 显示的是最后一次拉取的结果'">
        {{ liveSynced ? '实时同步' : '离线冻结' }}
      </span>
      <button class="mini" :disabled="refreshA.busy" @click="refreshA.run()">{{ refreshA.busy ? '刷新中…' : '刷新' }}</button>
      <button class="mini" :disabled="reconA.busy"
              title="读 PLC 输入映像, 逐位置按各自极性折算有/无并与账本比对 (只报不改)"
              @click="reconA.run()">{{ reconA.busy ? '对账中…' : '在位对账' }}</button>
    </div>
    <p v-if="err" role="status" class="mat-err">{{ err }}</p>

    <!-- 在途载荷: 取放过程中载荷挂在夹爪上, 既不在货架也不在中转位。
         流程正常跑完它会自己消失; 中途取消/断电才会滞留 —— 那正是这一条要暴露的情况,
         旧账本在这段窗口里静默失同步且不留痕。 -->
    <div v-for="row in transitRows" :key="row.carrier" class="mat-transit">
      <b>{{ carrierLabel(row.carrier) }}</b> 上有在途{{ row.payload === 'tray' ? '整板' : '单件' }}:
      {{ kindLabel(row.kind) }} {{ row.plate }} 号板<template v-if="row.hole"> · {{ row.hole }} 号孔</template>
      <!-- 带上装量: 流程跑到一半时"粉去哪了"在 6x6 阵列里是看不到的 (件已离开托盘孔) -->
      <template v-if="row.hole && contentText(row.kind, cell(row.kind, row.plate, row.hole))">
        · {{ contentText(row.kind, cell(row.kind, row.plate, row.hole)) }}
      </template>
      <span class="muted">(自 {{ locLabel(row.from_loc) }} 取起{{ row.since_at ? ` · ${sinceText(row.since_at)}` : '' }})</span>
      <button class="mini" :disabled="transitA.busy" @click="clearTransit(row, 'rack')">记回货架</button>
      <button class="mini" :disabled="transitA.busy" @click="clearTransit(row, 'staging')">记入中转</button>
      <button class="mini" :disabled="transitA.busy" @click="clearTransit(row, '')">只清在途</button>
    </div>

    <!-- 工位夹具上的单件: 有座位行 ⇒ 该件不在托盘孔里, 上面 6x6 阵列把那个孔画成空。
         粉正是在这段窗口里累积的 (刮板夹具上边刮边吸), 不列出来就会出现"账上加了粉,
         页面上哪都看不到"。与在途条同一形态, 同样只在非空时出现。 -->
    <div v-for="row in payloadSeatRows" :key="row.seat" class="mat-transit mat-seat">
      <b>{{ row.label || row.seat }}</b> 上停着:
      {{ kindLabel(row.kind) }} {{ row.plate }} 号板 · {{ row.hole }} 号孔
      <template v-if="contentText(row.kind, cell(row.kind, row.plate, row.hole))">
        · {{ contentText(row.kind, cell(row.kind, row.plate, row.hole)) }}
      </template>
      <span class="muted">
        {{ row.since_at ? `(自 ${sinceText(row.since_at)})` : '' }}
        <b v-if="row.stale" class="absent-tally">· 上一进程遗留, 请盘点</b>
      </span>
      <button class="mini" :disabled="payloadSeatA.busy" @click="clearPayloadSeat(row)">清账</button>
    </div>
    <p v-if="reconcileNote" role="status" class="mat-recon"
       :class="{ bad: grid && grid.presence_mismatches }">{{ reconcileNote }}</p>
    <!-- 原始输入字节: 某组位全 0 时用它分清"传感器说空"与"传感器没信号"。
         IX12 高 3 位是机器人工具检测, 有值即证明该字节所在 IO 模块是活的 (交叉验证锚点)。 -->
    <p v-if="reconcileRaw" class="mat-raw">
      读到
      <span v-for="(v, name) in reconcileRaw" :key="name" class="raw-one">
        {{ name }}=<code>{{ v.bits }}</code>({{ v.value }})
      </span>
      <span v-if="reconcileRaw.IX12?.tool_detect_bits" class="muted">
        | IX12 高 3 位是机器人工具检测 (读到
        {{ reconcileRaw.IX12.tool_detect_bits.map((b) => (b ? 1 : 0)).join('') }},
        有值即说明该字节的 IO 模块是活的)
      </span>
    </p>

    <h3 v-if="activeCat === 'tray'">{{ catLabel('tray', '盘位') }}</h3>
    <section v-for="k in (activeCat === 'tray' ? KINDS : [])" :key="k.key" class="mat-kind">
      <div class="kind-head">
        <strong>{{ k.label }}</strong>
        <span v-if="grid" class="tally">
          可用 {{ grid.summary[k.key].fresh }} · 已用 {{ grid.summary[k.key].used }}
          <template v-if="grid.summary[k.key].filled">
            · 成品待取 {{ grid.summary[k.key].filled }}
          </template>
          <template v-if="loadedCount(k.key)">
            · 装料 {{ loadedCount(k.key) }}
          </template>
          <template v-if="grid.summary[k.key].absent_plates">
            · <b class="absent-tally">缺板 {{ grid.summary[k.key].absent_plates }}</b>
          </template>
        </span>
        <span class="staging">
          {{ k.areaLabel }}:
          <template v-if="stagedPlate(k.key) != null">
            <b>{{ stagedPlate(k.key) }} 号板</b>
            <button class="mini" :disabled="stagingA.busy" @click="setStaging(k.area, null)">置空</button>
          </template>
          <template v-else><i class="muted">空</i></template>
        </span>
      </div>

      <table class="mat-tab">
        <thead>
          <tr>
            <th class="th-plate">货架库位</th>
            <th class="th-rack"
                title="人工记的板级在架状态 —— 标为无板后该库位的孔不计入可用统计, 自动换板与预填也会跳过它; 板在中转时由系统维护">在架</th>
            <th class="th-di" title="PLC 料库检测光电: 原始读数仅供参考 (货架 12 路信号未接通且极性未实证, 不参与判定)">光电</th>
            <th v-for="h in HOLES" :key="h">孔{{ h }}</th>
            <th class="th-ops">盘点</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in PLATES" :key="p"
              :class="{ 'row-staged': stagedPlate(k.key) === p, 'row-absent': isAbsent(k.key, p) }">
            <td class="td-plate">
              {{ p }} 号板
              <small v-if="stagedPlate(k.key) === p" class="in-staging">在{{ k.areaLabel }}</small>
              <button v-else class="mini ghost" :disabled="stagingA.busy"
                      @click="setStaging(k.area, p)">标为在{{ k.areaLabel }}</button>
            </td>
            <td class="td-rack">
              <small v-if="stagedPlate(k.key) === p" class="muted">在中转</small>
              <button v-else class="mini" :class="{ 'rk-off': rackOf(k.key, p)?.present === false }"
                      :disabled="rackA.busy"
                      :title="rackOf(k.key, p)?.present !== false
                        ? '账本记有板; 点击标为无板 (该库位的孔不再计入可用与自动决策)'
                        : '账本记无板; 点击标为有板'"
                      @click="toggleRack(k.key, p)">
                {{ rackOf(k.key, p)?.present !== false ? '有板' : '无板' }}
              </button>
            </td>
            <td class="td-di">
              <span :class="presenceClass(presenceOf(k.key, p))" role="img"
                    :title="presenceTitle(presenceOf(k.key, p))"
                    :aria-label="presenceTitle(presenceOf(k.key, p))">
                {{ presenceOf(k.key, p) ? (presenceOf(k.key, p).present ? '有板' : '空') : '—' }}
                <b v-if="presenceOf(k.key, p)?.ok === false">!</b>
              </span>
            </td>
            <td v-for="h in HOLES" :key="h" class="td-cell">
              <button class="hole" :class="cellClass(cell(k.key, p, h), k.key, p)"
                      :disabled="cellA.busy"
                      :title="[cellTitle(cell(k.key, p, h)), contentText(k.key, cell(k.key, p, h))]
                        .filter(Boolean).join(' · ')"
                      :aria-label="`${k.label} ${p} 号板 孔${h}: ${cellTitle(cell(k.key, p, h)) || '未知'}`
                        + (contentText(k.key, cell(k.key, p, h)) ? `, ${contentText(k.key, cell(k.key, p, h))}` : '')"
                      :aria-pressed="cell(k.key, p, h)?.state === 'FRESH'"
                      @click="toggleCell(k.key, p, h)">
                <span class="hole-mark" aria-hidden="true">{{ cell(k.key, p, h)?.state === 'FRESH' ? '●' : '○' }}</span>
                <small v-if="cell(k.key, p, h)?.sample_id" class="hole-sample">
                  {{ cell(k.key, p, h).sample_id }}
                </small>
                <!-- 装量条: 纯装饰, aria-hidden。数值已并进按钮的可访问名(见 contentText)。
                     刻意不用 role="progressbar": 36 个格子各挂一个 widget role 会把屏幕阅读器
                     淹掉, 而且把 widget role 套进 <button> 内部本身就是错的。
                     溶剂那条是单条主数据配数字读数, 才适合 progressbar。 -->
                <span v-if="contentPct(k.key, cell(k.key, p, h)) !== null"
                      class="hole-bar bar" aria-hidden="true">
                  <i :style="{ width: contentPct(k.key, cell(k.key, p, h)) + '%' }"
                     :class="{ wet: k.key === 'collector' && cell(k.key, p, h)?.eluted }" />
                </span>
              </button>
            </td>
            <td class="td-ops">
              <button class="mini" :disabled="plateA.busy" @click="markPlate(k.key, p, 'FRESH')">装满</button>
              <button class="mini" :disabled="plateA.busy" @click="markPlate(k.key, p, 'USED')">清空</button>
              <!-- 装量编辑入口: 只在拓扑声明了该 kind 的内容物时渲染 (与装量条同门槛) -->
              <button v-if="contentSpecs[k.key]" class="mini"
                      :title="`编辑整板 6 孔的${contentSpecs[k.key].label} (${contentSpecs[k.key].unit})`"
                      @click="cellAmountFor = { kind: k.key, plate: p }">装量…</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="legend">
        ● 可用 &nbsp; ○ 空孔 &nbsp; <span class="lg-filled">○</span> 成品待取 (带样品号) &nbsp;·&nbsp;
        点孔即翻转状态; 整行"装满/清空"批量录入 &nbsp;·&nbsp;
        「在架」为人工账, 标无板后整行淡化 (孔账保留, 不计入可用)
      </p>
    </section>

    <!-- 中转两处: 软件记板号 + 传感器校验有/无 (这两个传感器实测可用)。
         属于 tray 类 (渲染的就是 locsOf('tray')), 故跟着盘位子页走。 -->
    <section v-if="activeCat === 'tray'" class="mat-kind">
      <div class="kind-head">
        <strong>中转位</strong>
        <span class="muted">软件记板号, 传感器只校验有/无 —— 两者不符即标红</span>
      </div>
      <table class="mat-tab">
        <thead><tr><th>位置</th><th>账本记</th><th>传感器</th><th>传感器点</th><th>盘点</th></tr></thead>
        <tbody>
          <tr v-for="loc in locsOf('tray').filter((l) => l.area)" :key="loc.id"
              :class="{ 'row-bad': presenceAt(loc.id)?.ok === false }">
            <td class="td-plate">{{ loc.label }}</td>
            <td>
              <b v-if="grid?.staging?.[loc.area]?.plate != null">
                {{ grid.staging[loc.area].plate }} 号板
              </b>
              <i v-else class="muted">空</i>
            </td>
            <td class="td-di">
              <span :class="presenceClass(presenceAt(loc.id))" role="img"
                    :title="presenceTitle(presenceAt(loc.id))"
                    :aria-label="presenceTitle(presenceAt(loc.id))">
                {{ presenceText(presenceAt(loc.id)) }}
                <b v-if="presenceAt(loc.id)?.ok === false">!</b>
              </span>
              <small v-if="presenceAt(loc.id) && !presenceAt(loc.id).verified"
                     class="unverified">极性未核实</small>
            </td>
            <td class="mono muted">{{ loc.sensor }} · {{ loc.byte }}.{{ loc.bit }}</td>
            <td class="td-ops">
              <button class="mini" :disabled="stagingA.busy"
                      @click="setStaging(loc.area, null)">置空</button>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 上料: 两处托盘位, 纯传感器读数 (刻意不建软件账, 故只读、不判定账实不符) -->
    <h3 v-if="activeCat === 'feed'">{{ catLabel('feed', '上料') }}</h3>
    <section v-if="activeCat === 'feed'" class="mat-kind">
      <p class="legend">{{ catHint('feed') }}</p>
      <table class="mat-tab">
        <thead><tr><th>位置</th><th>传感器</th><th>原始位</th><th>传感器点</th><th>极性</th></tr></thead>
        <tbody>
          <tr v-for="loc in locsOf('feed')" :key="loc.id">
            <td class="td-plate">{{ loc.label }}</td>
            <td class="td-di">
              <span :class="presenceClass(presenceAt(loc.id))" role="img"
                    :title="presenceTitle(presenceAt(loc.id))"
                    :aria-label="presenceTitle(presenceAt(loc.id))">
                {{ presenceText(presenceAt(loc.id)) }}
              </span>
            </td>
            <td class="mono">{{ presenceAt(loc.id) ? (presenceAt(loc.id).raw ? 1 : 0) : '—' }}</td>
            <td class="mono muted">{{ loc.sensor }} · {{ loc.byte }}.{{ loc.bit }}</td>
            <td>
              <span class="muted">{{ loc.polarity === 'nc' ? '常闭 NC' : '常开 NO' }}</span>
              <small v-if="!loc.verified" class="unverified">未核实</small>
            </td>
          </tr>
          <tr v-if="!locsOf('feed').length"><td colspan="5" class="muted">拓扑加载中…</td></tr>
        </tbody>
      </table>
    </section>

    <h3 v-if="activeCat === 'glass'">{{ catLabel('glass', '玻璃板') }}</h3>
    <section v-if="activeCat === 'glass'" class="mat-kind">
      <p class="legend">
        板数主线仍是软件计 (上料一次 −1, 下料一次 +1), 但两个 cycle 内会用
        <b>光电触发位 + 升降轴行程</b>实测校正: 板越多平台停得越低,
        <code>张数 = (空仓基准位 − 触发位) ÷ 堆叠节距</code>。上料 cycle 还会在取板前后各测一次,
        行程差 ≠ 一个节距即判为双张/空吸并当次停机。
      </p>
      <table class="mat-tab">
        <thead><tr><th>板仓</th><th>板数</th><th>容量</th><th>预警线</th><th>盘点</th></tr></thead>
        <tbody>
          <tr v-for="m in grid?.magazines || []" :key="m.magazine"
              :class="{ 'mag-warn': magazineWarn(m) }">
            <td class="td-plate">{{ m.label }}</td>
            <td class="num"><b>{{ m.count }}</b> 张</td>
            <td class="muted num">{{ m.capacity }}</td>
            <td class="muted num">
              <template v-if="calibOf(m.magazine)">
                {{ m.magazine === 'waste' ? '≥' : '≤' }}{{ calibOf(m.magazine).warn_threshold }} 张
                <b v-if="magazineWarn(m)">{{ m.magazine === 'waste' ? '已快满' : '已低料' }}</b>
              </template>
              <template v-else>—</template>
            </td>
            <td class="td-ops">
              <button class="mini" :disabled="countA.busy" :aria-label="`${m.label}板数减一`"
                      @click="bumpMagazine(m.magazine, -1)">−1</button>
              <button class="mini" :disabled="countA.busy" :aria-label="`${m.label}板数加一`"
                      @click="bumpMagazine(m.magazine, 1)">+1</button>
              <input class="num" type="number" min="0" inputmode="numeric" :value="m.count"
                     :disabled="countA.busy" title="回车或失焦写入板数"
                     :aria-label="`${m.label}板数盘点`"
                     @keyup.enter="setMagazine(m.magazine, $event.target.value)"
                     @change="setMagazine(m.magazine, $event.target.value)" />
            </td>
          </tr>
          <tr v-if="!(grid?.magazines || []).length"><td colspan="5" class="muted">暂无数据</td></tr>
        </tbody>
      </table>
      <p v-if="calibErr" class="legend mag-uncalib">标定读取失败: {{ calibErr }}</p>
      <FeedliftCalibWizard v-for="m in grid?.magazines || []" :key="`wiz-${m.magazine}`"
                           :magazine="m.magazine" :state="calibOf(m.magazine)"
                           :ledger-count="m.count" @changed="reload" />
    </section>

    <h3 v-if="activeCat === 'solvent'">{{ catLabel('solvent', '溶剂') }}</h3>
    <section v-if="activeCat === 'solvent'" class="mat-kind">
      <p class="legend">
        硬件<b>无任何体积测量</b> (PLC 只有二值的废液管走空检测, 展缸液位是相机相对幅值) ——
        余量由注液/洗脱动作按 <code>体积 × 次数 × 配比</code> 扣减。换瓶后请在此录入新余量。
        <br />⚠ 一处已知少记, 会让余量偏高, 请定期校正: 从维护面板单发动作不入账
        (该路由绕过 VM, 事件不带参数), 手动试发上液/润洗会真实耗液而账本无感。
      </p>
      <table class="mat-tab">
        <thead><tr><th>溶剂</th><th>余量</th><th>瓶容量</th><th>余量比</th><th>盘点 (mL)</th></tr></thead>
        <tbody>
          <tr v-for="b in grid?.bottles || []" :key="b.bottle"
              :class="{ 'row-low': b.percent < 10 }">
            <td class="td-plate">{{ b.label }}</td>
            <td class="num"><b>{{ b.volume_ml.toFixed(1) }}</b> mL</td>
            <td class="muted num">{{ b.capacity_ml.toFixed(0) }}</td>
            <td class="num">
              <span class="bar" role="progressbar" :aria-valuenow="b.percent"
                    aria-valuemin="0" aria-valuemax="100"
                    :aria-label="`${b.label}余量 ${b.percent}%`">
                <i :style="{ width: b.percent + '%' }" :class="{ low: b.percent < 10 }" />
              </span>
              <small class="muted">{{ b.percent }}%</small>
            </td>
            <td class="td-ops">
              <input class="num" type="number" min="0" step="10" inputmode="decimal" :value="b.volume_ml"
                     :disabled="volumeA.busy" title="回车或失焦写入余量 mL"
                     :aria-label="`${b.label}余量盘点 (mL)`"
                     @keyup.enter="setBottle(b.bottle, $event.target.value)"
                     @change="setBottle(b.bottle, $event.target.value)" />
              <button class="mini" :disabled="volumeA.busy"
                      @click="fillBottle(b)">装满</button>
            </td>
          </tr>
          <tr v-if="!(grid?.bottles || []).length"><td colspan="5" class="muted">暂无数据</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 板位: 点样座/刮板拍照台 有板/无板人工账 (无传感器, 故无"光电"列)。
         并列调度器 samples.position 做对照 —— 不一致只标黄提示, 两边都不自动改。 -->
    <h3 v-if="activeCat === 'seat'">{{ catLabel('seat', '板位') }}</h3>
    <section v-if="activeCat === 'seat'" class="mat-kind">
      <p class="legend">
        这两处<b>没有任何在位传感器</b> (PLC 输入映像里没有点样座/刮板台的板检测), 所以有板/无板
        只能人工记 —— 手动把板拿走或放上后, 点一下这里同步现场。落库跨重启保留。
        <br />⚠ 此状态<b>只用于展示与人工同步, 流程不读它</b>: 不参与自动换板/预填/批次准入,
        也不写调度器的位置账。右侧「调度器记」是流程侧的权威位置账, 仅供对照;
        两者不一致时整格标黄<b>仅作提示, 不自动处置</b>。
      </p>
      <table class="mat-tab">
        <thead>
          <tr>
            <th>位置</th>
            <th class="th-rack" title="人工记的现场状态; 点击翻转 (可逆, 无需确认)">有板/无板</th>
            <th title="调度器 samples.position 记在该位置的样品号 (流程侧权威位置账, 只读)">调度器记</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in seatRows" :key="s.seat">
            <td class="td-plate">{{ s.label }}</td>
            <td class="td-rack">
              <button class="mini" :class="{ 'rk-off': !s.present }" :disabled="seatA.busy"
                      :title="s.present ? '人工记有板; 点击标为无板' : '人工记无板; 点击标为有板'"
                      :aria-pressed="s.present" @click="toggleSeat(s.seat)">
                {{ s.present ? '有板' : '无板' }}
              </button>
            </td>
            <td :class="{ 'seat-warn': seatMismatch(s.seat) }" :title="seatMismatchText(s.seat)">
              <span v-if="schedAt(s.seat).length" class="mono">{{ schedAt(s.seat).join(', ') }}</span>
              <i v-else class="muted">—</i>
              <small v-if="seatMismatch(s.seat)" class="unverified">账实不符 (仅提示)</small>
            </td>
            <td class="muted">{{ fmtTime(s.updated_at) }}</td>
          </tr>
          <tr v-if="!seatRows.length"><td colspan="4" class="muted">拓扑加载中…</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 件位: 单件耗材在工位夹具上 (刮板夹具/收集工位)。座位账由流程事件自动维护;
         人工入口 (清账/放件) 只在盘点发现账实不符时用。与「板位」不是一回事:
         那边是薄层板的停放位人工账, 这边是耗材件的座位账 (有行 ⇒ 该件不在托盘孔里)。 -->
    <h3 v-if="activeCat === 'holder'">{{ catLabel('holder', '件位') }}</h3>
    <section v-if="activeCat === 'holder'" class="mat-kind">
      <p class="legend">{{ catHint('holder') }}
        <br />⚠ 座位账与托盘孔账分开更正: 清账/放件都<b>不改孔位状态</b>, 孔账请到盘位页盘点。
      </p>
      <table class="mat-tab">
        <thead>
          <tr>
            <th>座位</th><th>账面</th>
            <th title="收集瓶位有传感器 (IX8.1); 另两座无传感器只能人工盘点">传感器</th>
            <th class="th-ops">盘点</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="seatSpec in holderSeats" :key="seatSpec.id">
            <td class="td-plate">{{ seatSpec.label }}</td>
            <td>
              <template v-if="seatedOf(seatSpec.id)">
                <b>{{ kindLabel(seatedOf(seatSpec.id).kind) }}
                   {{ seatedOf(seatSpec.id).plate }} 号板 · {{ seatedOf(seatSpec.id).hole }} 号孔</b>
                <template v-if="contentText(seatedOf(seatSpec.id).kind,
                                            cell(seatedOf(seatSpec.id).kind,
                                                 seatedOf(seatSpec.id).plate,
                                                 seatedOf(seatSpec.id).hole))">
                  · {{ contentText(seatedOf(seatSpec.id).kind,
                                   cell(seatedOf(seatSpec.id).kind,
                                        seatedOf(seatSpec.id).plate,
                                        seatedOf(seatSpec.id).hole)) }}
                </template>
                <small v-if="seatedOf(seatSpec.id).stale" class="muted">
                  (上一进程记的; 座位账跨重启仍可信)
                </small>
              </template>
              <i v-else class="muted">空</i>
            </td>
            <td class="td-di">
              <template v-if="presenceAt(seatSpec.id)">
                <span :class="presenceClass(presenceAt(seatSpec.id))" role="img"
                      :title="presenceTitle(presenceAt(seatSpec.id))"
                      :aria-label="presenceTitle(presenceAt(seatSpec.id))">
                  {{ presenceText(presenceAt(seatSpec.id)) }}
                </span>
                <small v-if="!presenceAt(seatSpec.id).verified" class="unverified">极性未核实</small>
              </template>
              <span v-else class="muted" title="该座无在位传感器, 或尚未对账过">—</span>
            </td>
            <td class="td-ops">
              <template v-if="seatedOf(seatSpec.id)">
                <button class="mini" :disabled="payloadSeatA.busy"
                        @click="clearPayloadSeat(seatedOf(seatSpec.id))">清账</button>
              </template>
              <template v-else-if="placing?.seat === seatSpec.id">
                <label class="place-lab">板
                  <select v-model.number="placing.plate">
                    <option v-for="p in PLATES" :key="p" :value="p">{{ p }}</option>
                  </select>
                </label>
                <label class="place-lab">孔
                  <select v-model.number="placing.hole">
                    <option v-for="h in HOLES" :key="h" :value="h">{{ h }}</option>
                  </select>
                </label>
                <button class="mini" :disabled="payloadSeatA.busy"
                        @click="submitPlacing(seatSpec)">确认放件</button>
                <button class="mini ghost" @click="placing = null">取消</button>
              </template>
              <button v-else class="mini"
                      :title="`盘点发现座上有件而账本没有时用; 只收 ${kindLabel(seatSpec.accepts)}`"
                      @click="startPlacing(seatSpec)">人工放件</button>
            </td>
          </tr>
          <tr v-if="!holderSeats.length"><td colspan="4" class="muted">拓扑加载中…</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 一键审查: 独立组件 (四组核对表 + 计数徽标 + 行内修复) -->
    <MaterialAudit v-if="activeCat === 'audit'" />

    <section v-if="activeCat === 'log'" class="mat-log">
      <div class="kind-head"><strong>记账流水</strong>
        <span class="muted">最近 40 条 · 全量 (不分物料类别) · manual=人工盘点</span>
      </div>
      <table class="mat-tab log-tab">
        <thead>
          <tr><th>动作</th><th>耗材</th><th>板/孔</th><th>状态迁移</th><th>脚本</th><th>备注</th></tr>
        </thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td>{{ e.effect }}</td>
            <td>{{ e.kind }}</td>
            <td>{{ e.plate == null ? '—' : e.plate }}<template v-if="e.hole != null"> / {{ e.hole }}</template></td>
            <td>{{ e.from_state || '—' }}<template v-if="e.to_state"> → {{ e.to_state }}</template></td>
            <td class="mono">{{ e.script || '—' }}</td>
            <td class="td-detail" :title="e.detail">{{ e.detail }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="6" class="muted">暂无记录</td></tr>
        </tbody>
      </table>
    </section>

    <!-- 装量对话框: v-if 挂载, 每次打开都是新实例 (草稿从当前账本值初始化) -->
    <CellAmountDialog v-if="cellAmountFor"
                      :kind="cellAmountFor.kind" :plate="cellAmountFor.plate"
                      :kind-label="kindLabel(cellAmountFor.kind)"
                      :cells="plateCells(cellAmountFor.kind, cellAmountFor.plate)"
                      :spec="contentSpecs[cellAmountFor.kind] || null"
                      @saved="reload" @close="cellAmountFor = null" />
  </div>
</template>

<style scoped>
.mat-view { padding: 12px 16px; overflow: auto; }
.mat-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.mat-head h2 { margin: 0 0 6px; font-size: 16px; }
.mat-note { font-size: var(--fs-11); }
.mat-err { color: var(--bad); font-family: var(--font-mono); font-size: var(--fs-12); }
.mat-recon { font-size: var(--fs-12); color: var(--ok-strong, var(--ok)); margin: 2px 0 6px; }
.mat-recon.bad { color: var(--warn-strong); }
.mat-raw { font-size: var(--fs-11); color: var(--subtle); margin: -2px 0 6px; }
.mat-raw code { font-family: var(--font-mono); color: var(--text); }
/* 实时徽标: 与三维侧 MaterialPanel 同一套措辞 (同一份账本, 两页别各说各话) */
.mat-live { font-size: var(--fs-11); color: var(--ok); white-space: nowrap; }
.mat-live.off { color: var(--subtle); }
/* 在途条: 正常跑完会自己消失, 长时间挂着就是中途断了 —— 用告警色让人注意到 */
.mat-transit {
  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
  margin: 4px 0 8px; padding: 6px 10px;
  font-size: var(--fs-12);
  border-left: 3px solid var(--warn-strong);
  background: var(--surface-2, transparent);
}
/* 光电在位列: 与账本期望不符即标红 */
.th-di, .td-di { white-space: nowrap; }
.di-ok { color: var(--ok); }
.di-bad { color: var(--bad); font-weight: 700; }
.di-bad b { margin-left: 2px; }
/* 无软件账可比的位置 (上料两处): 只显现值, 不用对错配色 */
.di-plain { color: var(--text); }
.unverified { display: block; font-size: 9px; color: var(--warn-strong); line-height: 1.2; }
/* 板位: 人工账与调度账不一致时整格标黄 (只提示, 不处置) */
.seat-warn { color: var(--warn-strong); background: var(--warn-soft); }
.row-bad .td-plate { color: var(--bad); font-weight: 700; }
.raw-one { margin-right: 8px; }
/* 货架在架人工账: 无板行淡化 (库位名与在架按钮保持全亮可点; 孔不禁用, 板不在架时孔账仍可盘) */
.th-rack, .td-rack { white-space: nowrap; }
.row-absent .td-cell, .row-absent .td-di, .row-absent .td-ops { opacity: 0.45; }
.rk-off { color: var(--warn-strong); border-color: var(--warn-strong); }
.absent-tally { color: var(--warn-strong); }
/* 板数 / 余量 录入框 (限定 input, 避免吃掉表格数值列的全局 .num tabular-nums) */
input.num { width: 76px; font-size: var(--fs-12); padding: 2px 4px; margin-left: 4px; }
/* 溶剂余量条 */
.bar {
  display: inline-block; width: 70px; height: 8px; vertical-align: middle;
  border: 1px solid var(--border); border-radius: 4px; overflow: hidden; background: var(--surface-2);
}
.bar i { display: block; height: 100%; background: var(--ok); }
.bar i.low { background: var(--bad); }
.row-low .td-plate { color: var(--bad); font-weight: 700; }
.mat-kind, .mat-log { margin: 14px 0 18px; }
.kind-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 6px; }
.tally, .staging { font-size: var(--fs-12); color: var(--subtle); }
.staging { display: flex; align-items: baseline; gap: 6px; }
.mat-tab { border-collapse: collapse; font-size: var(--fs-12); }
.mat-tab th, .mat-tab td { border: 1px solid var(--border); padding: 3px 6px; text-align: center; }
.mat-tab th { background: var(--surface-2); color: var(--subtle); font-weight: 600; }
.th-plate, .td-plate { text-align: left; white-space: nowrap; }
.td-plate { display: table-cell; }
.row-staged .td-plate { font-weight: 700; }
.in-staging { color: var(--accent); margin-left: 4px; }
.td-cell { padding: 2px; }
.hole {
  width: 100%; min-width: 54px; min-height: 34px; cursor: pointer;
  border: 1px solid var(--border); border-radius: 5px; background: var(--surface-2);
  display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px;
}
.hole:disabled { cursor: default; opacity: 0.6; }
.hole-mark { font-size: var(--fs-14); line-height: 1; }
.hole-sample { font-size: 9px; font-family: var(--font-mono); color: var(--accent); }
/* 装量条: 复用 .bar 的边框/圆角/背景, 但必须排在 .bar 之后才盖得掉它的 70x8px */
.hole-bar { width: calc(100% - 8px); height: 3px; border-radius: 2px; }
/* 已淋洗的粉呈湿色 —— 与三维粉柱换色同一个信号, 两处看到的是同一件事 */
.hole-bar i.wet { background: var(--muted); }
.c-fresh { border-color: var(--ok); color: var(--ok); background: var(--ok-soft, var(--surface-2)); }
.c-empty { color: var(--muted); }
.c-filled { border-color: var(--accent); color: var(--accent); }
.lg-filled { color: var(--accent); }
.td-ops { white-space: nowrap; }
.legend { font-size: var(--fs-11); color: var(--muted); margin: 5px 0 0; }
.log-tab { width: 100%; }
.log-tab td { text-align: left; }
.mono { font-family: var(--font-mono); }
/* 备注列: 截断显示, 悬停 title 给全文 */
.td-detail { color: var(--warn-strong); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mini.ghost { opacity: 0.7; }
/* 件位放件行内表单: 两个 select 紧凑排布 */
.place-lab { font-size: var(--fs-12); color: var(--subtle); margin-right: 4px; white-space: nowrap; }
.place-lab select { font-size: var(--fs-12); padding: 1px 2px; margin-left: 2px; }
/* 板仓触及预警线 (上料低料 / 下料快满) 整行标警色; 未标定单标, 因为它使实测校正不生效 */
.mag-warn td { color: var(--warn-strong); border-color: var(--warn-strong); }
.mag-uncalib { color: var(--warn-strong); }
</style>
