<script setup>
/**
 * 功能: 演示页 —— 自动关联实机现有的全部流程, 逐条给出可播的运动动画.
 *
 * 左栏与流程界面(/library/operation)**同源同规则**: 同一个 editor store 的 operations,
 * 同样按目录分组、同样滤掉 ui.hidden。所以"流程界面里有的, 这里都有"是结构保证, 不是
 * 靠人去同步两份清单 —— 新增一个流程, 打开本页就多一条。
 *
 * 每条流程的动画分两级:
 *   ✓ 精编译  后端 clip_compiler 编出的正式片段(实测示教点 + 离线 IK, 有 SHA 门禁)
 *   ≈ 近似    前端按脚本即时展开(flowSim), 秒级可见, 分支/循环/无轨迹处都在标签上写明
 *   — 无机械动作  展开后一步机构都不动 —— 如实说, 而不是让人对着静止画面猜
 *   ✗ 无法生成  连展开都做不到, 给出具体原因
 */
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api } from '../../api.js'
import { useEditorStore } from '../../stores/editor.js'
import { compileClip, parseClip, railCalibStatus } from '../anim/clipSchema.js'
import DisplayPanel from '../twin/panels/DisplayPanel.vue'
import * as twinApi from '../twin/api.js'
import ViewToolbar from '../twin/scene/ViewToolbar.vue'
import * as authoring from '../workbench/authoringApi.js'
import { installAnimHooks } from '../motion/devHooks.js'
import { useMotionScene } from '../motion/useMotionScene.js'
import { useMotionStack } from '../motion/useMotionStack.js'
import '../motion/workbench.css'
import { enumOf } from '../../utils/runInputs.js'
import { indexServoPoints } from './actionSim.js'
import { simulateFlow } from './flowSim.js'
import { inputsDiffer, matchVariantIndex } from './flowInputs.js'
import { loadMotionMap, resetMotionMap } from './motionMap.js'

const MODEL_URL = '/api/3d/assets/models/machine.official-cr5.glb'
const MANIFEST_URL = '/api/3d/assets/models/device-manifest.official-cr5.json'
const FLOW_INDEX_URL = '/api/3d/assets/clips/flow-index.json'
const POINTS_URL = '/api/3d/assets/generated/robot-points.json'

/** 目录名 → 中文组名; 与流程界面的目录一一对应 */
const GROUP_LABELS = {
  '00_system': '系统',
  '01_sampling': '上样',
  '02_develop': '展开',
  '03_photoscrape': '拍照刮板',
  '04_collect': '收集',
  '05_transfer': '转移',
  '06_robot': '机械臂',
  '07_feedlift': '上下料升降',
  '08_rail': '地轨',
  '09_full': '整机',
  '11_parallel': '并行流程',
}

const route = useRoute()
const router = useRouter()
const editor = useEditorStore()
const containerRef = ref(null)

const message = ref('')
const showDisplay = ref(false)
const view = ref({ xray: false, wireframe: false, hidden: 0 })
const transport = ref({ time: 0, duration: 0, playing: false, speed: 1, stepIndex: 0 })

const flowIndex = shallowRef(new Map())
const servoIndex = shallowRef(new Map())
const pointCatalog = shallowRef(null)
const motionMap = shallowRef(null)
const scriptCache = shallowRef(new Map())
const listError = ref('')
const filter = ref('')
const collapsed = ref(new Set())

const selectedName = ref('')
const inputs = ref({})
/** 精编译片段有多个变体时(如展开-上料 8 个缸)选中的下标 */
const variantIndex = ref(0)
/** 当前装载的片段 {source, label, steps, notes, unknown, deferred} */
const loaded = shallowRef(null)
const busy = ref(false)
/** 精编译进度 */
const compiling = ref(null)

/**
 * 功能: 面向用户的提示.
 * @param {string} text 文本
 * @returns {void}
 */
function notify(text) {
  message.value = text
}

const scene = useMotionScene({
  containerRef,
  modelUrl: MODEL_URL,
  manifestUrl: MANIFEST_URL,
  quality: 'high',
  onReady: (manifest) => {
    stack.attach(manifest)
    if (selectedName.value) load(selectedName.value)
  },
})
const { manager, manifest, loading, progress, error, stats, state } = scene

const stack = useMotionStack({
  manager,
  notify,
  onValueChange: () => {},
  onTransport: (next) => {
    transport.value = next
  },
})

/** 流程清单: 与 /library/operation 左栏同源同规则 */
const flows = computed(() => (editor.operations || []).filter((item) => !(item.ui && item.ui.hidden)))

const groups = computed(() => {
  const term = filter.value.trim().toLowerCase()
  const buckets = new Map()
  for (const flow of flows.value) {
    if (term
      && !String(flow.name || '').toLowerCase().includes(term)
      && !String(flow.label || '').toLowerCase().includes(term)) continue
    const key = flow.group || ''
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(flow)
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, items]) => ({
      key,
      label: GROUP_LABELS[key] || key || '未分组',
      items: items.sort((a, b) => {
        const orderA = Number(a.ui?.order ?? 9999)
        const orderB = Number(b.ui?.order ?? 9999)
        if (orderA !== orderB) return orderA - orderB
        return String(a.label || a.name).localeCompare(String(b.label || b.name), 'zh')
      }),
    }))
})

const selected = computed(() => flows.value.find((item) => item.name === selectedName.value) || null)

/**
 * 片段编译时的地轨标定指纹(flow-index 的索引级单值).
 *
 * 一次 --flows 运行里全部片段共用同一份 manifest, 所以判陈旧只需这一个值, 不必为了
 * 一个徽章去逐条拉一百个片段。
 */
const flowRailCalib = shallowRef(undefined)

/**
 * 精编译片段相对当前绑定契约是否已陈旧.
 *
 * 片段里的机械臂与载荷落点是编译期按当时的 axis_11y 标定烘死的; 标完零点不重编译,
 * 那些落点就与新标定对不上, 而画面照播、不报任何错 —— 这个徽章就是那件事的唯一提示.
 */
const clipStale = computed(() => railCalibStatus(flowRailCalib.value, manifest.value))

/**
 * 功能: 这条流程是否有精编译片段(只有它们才谈得上"烘焙陈旧").
 * @param {string} name 流程名
 * @returns {boolean} 是否精编译
 */
function isExact(name) {
  const entry = flowIndex.value.get(name)
  return entry?.status === 'ok' && Boolean(entry.clips?.length)
}

/**
 * 功能: 一条流程的状态徽章.
 * @param {string} name 流程名
 * @returns {{text: string, cls: string, title: string}} 徽章
 */
function badgeOf(name) {
  const entry = flowIndex.value.get(name)
  if (entry?.status === 'ok' && entry.clips?.length) {
    // 烘焙陈旧优先于"精编译": 精编译过但落点已对不上, 比没精编译更误导
    if (clipStale.value.state === 'stale') {
      return { text: '待重编译', cls: 'mw__tag--fail', title: clipStale.value.reason }
    }
    if (clipStale.value.state === 'unstamped') {
      return { text: '未标记', cls: 'mw__tag--approx', title: clipStale.value.reason }
    }
    return { text: '精编译', cls: 'mw__tag--exact', title: '后端编译的正式片段: 实测示教点 + 离线 IK' }
  }
  if (entry?.status === 'no-motion') {
    return { text: '无机械动作', cls: 'mw__tag--none', title: entry.reason || '' }
  }
  if (entry?.status === 'failed') {
    return { text: '近似', cls: 'mw__tag--approx', title: `精编译失败: ${entry.reason}` }
  }
  return { text: '近似', cls: 'mw__tag--approx', title: '尚未精编译, 由前端按脚本即时展开' }
}

/** 选中流程的精编译片段变体清单(可能 0/1/多条) */
const variants = computed(() => flowIndex.value.get(selectedName.value)?.clips || [])

/**
 * 选中流程上次精编译失败的原因(没失败过就是空串).
 *
 * 直接摆在按钮旁边: 从前这个按钮不管能不能成都长一个样, 点下去等一分钟再看到还是近似,
 * 没有任何线索说明为什么 —— flow-index 里明明逐条记着原因.
 */
const lastFailure = computed(() => {
  const entry = flowIndex.value.get(selectedName.value)
  return entry?.status === 'failed' ? String(entry.reason || '') : ''
})

/** 入参: 取 doc.vars 里 io=in 的项 */
const inputVars = computed(() => {
  const doc = scriptCache.value.get(selectedName.value)
  return (doc?.vars || []).filter((item) => item?.io === 'in')
})

/**
 * 功能: 折叠/展开一个分组.
 * @param {string} key 分组键
 * @returns {void}
 */
function toggleGroup(key) {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}

/**
 * 功能: 取一个流程文档(带缓存; 子流程内联也走它).
 * @param {string} name 流程名
 * @returns {Promise<object|null>} 文档
 */
async function fetchScript(name) {
  const cache = scriptCache.value
  if (cache.has(name)) return cache.get(name)
  try {
    const doc = await api.getScript(name)
    cache.set(name, doc)
    scriptCache.value = new Map(cache)
    return doc
  } catch {
    return null
  }
}

/**
 * 功能: 预取一个流程用到的全部子脚本(近似展开是同步的, 必须先备好).
 * @param {object} doc 流程文档
 * @param {number} depth 当前深度
 * @returns {Promise<void>}
 */
async function prefetchSubScripts(doc, depth = 0) {
  if (!doc || depth > 8) return
  const names = []
  const visit = (nodes) => {
    for (const node of nodes || []) {
      if (!node || typeof node !== 'object') continue
      if (node.op === 'run_script' && node.script) names.push(node.script)
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) visit(value)
        else if (value && typeof value === 'object' && Array.isArray(value.body)) visit(value.body)
      }
    }
  }
  visit(doc.body)
  // 起手态声明指名的前置段脚本(见 clip_compiler.PHASE_ENTRY_STATE): 它**不在 body 里**
  // —— 展开-上料的 body 一条液面动作都没有, 缸里那 60mL 是上一段 develop_prepare 留下的。
  // 不在这里预取, flowSim.seedEntryState 就只能记一笔 deferred, 近似档照旧演成空缸。
  const entryState = motionMap.value?.phaseEntryState?.[String(doc.name || '')]
  if (entryState?.liquidAfter) names.push(entryState.liquidAfter)
  for (const name of [...new Set(names)]) {
    const sub = await fetchScript(name)
    if (state.disposed) return
    await prefetchSubScripts(sub, depth + 1)
  }
}

/**
 * 功能: 读取片段 YAML.
 * @param {string} clipName 片段名
 * @returns {Promise<string>} YAML 文本
 */
async function fetchClipText(clipName) {
  try {
    return await authoring.readClip(clipName)
  } catch {
    // 强刷: 片段是 --flows 的产物, 后端 FileResponse 不发 Cache-Control, 浏览器会按
    // 启发式吃磁盘缓存 —— 重编译完还播旧片段, 且看不出任何异样
    const response = await fetch(`/api/3d/assets/clips/${clipName}.yaml?t=${Date.now()}`)
    if (!response.ok) throw new Error(`加载片段失败: ${clipName}`)
    return await response.text()
  }
}

/**
 * 功能: 选中并装载一个流程的动画.
 * @param {string} name 流程名
 * @returns {Promise<void>}
 */
async function load(name) {
  if (!name || busy.value) return
  if (name !== selectedName.value) variantIndex.value = 0
  selectedName.value = name
  loaded.value = null
  busy.value = true
  stack.rig.value?.home()
  try {
    // 深链可能给的是**片段名**而不是流程名 —— /3d/motion/<片段名> 的旧地址会重定向到
    // 这里(片段评审曾挂在动作页), 分享链接与验收脚本都还在用。先按清单判, 不去
    // 撞一次 /api/scripts 的 404: 那个 404 会进控制台, 看着像故障其实是探测。
    if (!flows.value.some((item) => item.name === name)) {
      await loadClipByName(name)
      return
    }
    const doc = await fetchScript(name)
    if (state.disposed) return
    if (!doc) throw new Error('流程文档取不到')
    // 一律字符串化: 有取值域的入参渲染成 <select>, 其 option value 是字符串,
    // INT 默认值若留成数字会与之对不上, 下拉初始渲成空白
    inputs.value = Object.fromEntries(
      (doc.vars || []).filter((item) => item.io === 'in').map((item) => [item.name, String(item.default ?? '')]),
    )

    const entry = flowIndex.value.get(name)
    // 一级: 已精编译的直接播正式片段(多个变体时按当前下拉选择)
    const clip = (entry?.clips || [])[variantIndex.value] || (entry?.clips || [])[0]
    if (entry?.status === 'ok' && clip) {
      if (!pointCatalog.value) {
        const response = await fetch(`${POINTS_URL}?t=${Date.now()}`)
        if (response.ok) pointCatalog.value = await response.json()
      }
      if (state.disposed) return
      const compiled = compileClip(parseClip(await fetchClipText(clip.clipName)), {
        pointCatalog: pointCatalog.value,
      })
      if (state.disposed) return
      stack.player.value?.load(compiled)
      loaded.value = {
        source: 'exact', label: compiled.label, steps: compiled.steps,
        notes: compiled.flowNotes || [], unknown: [], deferred: [],
        // 片段编译期烘死的那组入参 —— 面板要拿它比对, 决定"按这组入参编这一条"出不出。
        // clipSchema 早就透传了 compiled.operation, 此前这里把它丢掉了。
        operation: compiled.operation || null,
        clipName: clip.clipName,
        adhoc: clip.adhoc === true,
      }
      notify(`已装载正式片段「${compiled.label}」(${compiled.duration.toFixed(1)}s · ${compiled.steps.length} 步)`)
      return
    }
    // 编译期已判定"无机械动作": 不再前端展开一遍, 编译期的结论更可信
    if (entry?.status === 'no-motion') {
      loaded.value = { source: 'no-motion', reason: entry.reason, steps: [], notes: [], unknown: [], deferred: [] }
      return
    }

    // 二级: 前端即时近似
    await prefetchSubScripts(doc)
    if (state.disposed) return
    const result = simulateFlow(doc, inputs.value, {
      motionMap: motionMap.value,
      manifest: manifest.value,
      servoIndex: servoIndex.value,
      pointCatalog: pointCatalog.value,
      resolveScript: (subName) => scriptCache.value.get(subName) || null,
    })
    if (result.kind === 'approx') {
      const compiled = compileClip(result.doc, {})
      stack.player.value?.load(compiled)
      loaded.value = {
        source: 'approx',
        label: compiled.label,
        steps: compiled.steps,
        notes: result.notes || [],
        unknown: result.unknown || [],
        deferred: result.deferred || [],
      }
      notify(`已按脚本展开近似动画(${compiled.duration.toFixed(1)}s · ${compiled.steps.length} 步)`)
    } else if (result.kind === 'no-motion') {
      loaded.value = {
        source: 'no-motion',
        reason: result.reason,
        steps: [],
        notes: result.notes || [],
        unknown: result.unknown || [],
        deferred: result.deferred || [],
      }
    } else {
      loaded.value = { source: 'failed', reason: result.reason, steps: [], notes: [], unknown: [], deferred: [] }
    }
  } catch (err) {
    if (!state.disposed) loaded.value = { source: 'failed', reason: err?.message || String(err), steps: [] }
  } finally {
    if (!state.disposed) busy.value = false
  }
}

/**
 * 功能: 按片段名直接装载(旧地址 /3d/motion/<片段名> 重定向过来的路径).
 * @param {string} clipName 片段名
 * @returns {Promise<void>}
 */
async function loadClipByName(clipName) {
  if (!pointCatalog.value) {
    const response = await fetch(`${POINTS_URL}?t=${Date.now()}`)
    if (response.ok) pointCatalog.value = await response.json()
  }
  if (state.disposed) return
  const compiled = compileClip(parseClip(await fetchClipText(clipName)), {
    pointCatalog: pointCatalog.value,
  })
  if (state.disposed) return
  stack.player.value?.load(compiled)
  loaded.value = {
        source: 'exact', label: compiled.label, steps: compiled.steps,
        notes: compiled.flowNotes || [], unknown: [], deferred: [],
      }
  notify(`已装载片段「${compiled.label}」(${compiled.duration.toFixed(1)}s · ${compiled.steps.length} 步)`)
}

/**
 * 功能: 触发后端精编译(把当前流程从"近似"升级成"精编译").
 * @returns {Promise<void>}
 */
async function compileExact() {
  if (compiling.value) return
  try {
    compiling.value = { step: '排队中' }
    await authoring.startRebuild(['flows'])
    const final = await authoring.waitRebuild((status) => {
      const running = (status.steps || []).find((item) => item.status === 'running')
      compiling.value = { step: running?.label || '编译中' }
    })
    if (state.disposed) return
    if (final?.error) throw new Error(final.error)
    // 映射表也是 --flows 的产物, 而它有一层永不失效的进程内缓存 —— 不清就整个会话
    // 都拿着旧表, 且看不出任何异样
    resetMotionMap()
    await loadFlowIndex()
    if (state.disposed) return
    notify('流程动画已重新编译, 正在重新装载')
    await load(selectedName.value)
  } catch (err) {
    if (!state.disposed) notify(`精编译失败: ${err?.message || err}`)
  } finally {
    if (!state.disposed) compiling.value = null
  }
}

/**
 * 功能: 拉取 flow-index.json(后端精编译结果台账).
 * @returns {Promise<void>}
 */
async function loadFlowIndex() {
  try {
    const response = await fetch(`${FLOW_INDEX_URL}?t=${Date.now()}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const doc = await response.json()
    const map = new Map()
    for (const item of doc.flows || []) map.set(item.name, item)
    flowIndex.value = map
    // 三态照原样存(键缺失=undefined / null / 对象), 别用 `|| null` 抹平 —— 见 railCalibStatus
    flowRailCalib.value = doc.railCalib
  } catch {
    // 还没跑过 --flows: 全部按近似处理, 不是错误
    flowIndex.value = new Map()
    flowRailCalib.value = undefined
  }
}

/**
 * 功能: 跳到某一步开头.
 * @param {object} step 步骤
 * @returns {void}
 */
function seekStep(step) {
  stack.player.value?.seek(step.at)
}

/**
 * 功能: 时间格式化.
 * @param {number} value 秒
 * @returns {string} 文本
 */
function fmtTime(value) {
  return `${Number(value || 0).toFixed(1)}s`
}

/**
 * 功能: 观察工具分发.
 * @param {string} action 动作
 * @param {*} [payload] 参数
 * @returns {void}
 */
function onTool(action, payload) {
  const kit = stack.tools.value
  if (!kit) return
  if (action === 'view') kit.setView(payload)
  else if (action === 'reset') kit.resetView()
  else if (action === 'showAll') notify(`已还原 ${kit.showAll()} 个对象`)
  else if (action === 'xray') view.value.xray = kit.setXray(payload, [])
  else if (action === 'wireframe') view.value.wireframe = kit.setWireframe(payload)
  view.value.hidden = kit._hidden.size
}

/**
 * 功能: 选中流程时同步地址栏(可分享 / 可刷新).
 * @param {string} name 流程名
 * @returns {void}
 */
function pick(name) {
  router.replace(`/3d/demo/${name}`)
}

watch(() => route.params.flow, (next) => {
  const name = String(next || '')
  if (name && name !== selectedName.value) load(name)
}, { immediate: false })

// 入参改了怎么办, 按当前播的是哪一级分头处理:
//   近似档 —— 直接重新展开(flowSim 本来就吃面板入参);
//   精编译 —— 先看这组参数是不是**已经编过**(扇出变体或上次临时编的): 是就秒切下拉;
//             不是就什么都不做, 由 exactDirty 让"按这组入参编这一条"按钮浮出来。
// ⚠ load() 自己会在开头重置 inputs.value, 那一下也会触发本 watcher —— 它在重置前先把
//   loaded.value 置 null, 所以下面两条都会早退, 不会自激。
watch(inputs, () => {
  const current = loaded.value
  if (!current) return
  if (current.source === 'approx') { load(selectedName.value); return }
  if (current.source !== 'exact' || busy.value) return
  const hit = matchVariantIndex(flowIndex.value.get(selectedName.value), inputs.value, inputVars.value)
  if (hit >= 0 && hit !== variantIndex.value) {
    variantIndex.value = hit
    load(selectedName.value)
  }
}, { deep: true })

/**
 * 面板入参与当前片段烘死的那组是否不同 —— "按这组入参编这一条"按钮的出现判据。
 *
 * busy 期间恒 false: 装载过程中 inputs 正被 load() 重置, 不挡住会让按钮闪一下。
 * 12 条硬编码路线覆盖的流程(clips[0] 没有 stepCount)不给控件: 它们不在
 * flow_discovery 的 specs 里, --only 匹配不上会 SystemExit。
 */
const exactDirty = computed(() => {
  const current = loaded.value
  if (!current || current.source !== 'exact' || busy.value || compiling.value) return false
  const entry = flowIndex.value.get(selectedName.value)
  const clip = (entry?.clips || [])[variantIndex.value] || (entry?.clips || [])[0]
  if (!clip || !('stepCount' in clip)) return false      // 硬编码路线, 入参不参与编译
  if (matchVariantIndex(entry, inputs.value, inputVars.value) >= 0) return false
  return inputsDiffer(current.operation?.inputs, inputs.value, inputVars.value)
})

/**
 * 功能: 按面板当前这组入参, 只重编当前这一条流程(约 20 秒, 全量是 10 分钟).
 *
 * 与 compileExact 的差别只在 argv: 那条跑 --plates --flows 全量, 这条跑
 * --flows --only flow.<op>* --inputs <json>。产出是货架上多出来的一条**临时片段**
 * (带入参后缀的名字), 正式片段分毫不动; 下次全量重编时临时的自然消失。
 * @returns {Promise<void>}
 */
async function compileExactOne() {
  if (compiling.value || !selectedName.value) return
  const wanted = Object.fromEntries(
    inputVars.value.map((item) => {
      const raw = inputs.value[item.name]
      return [item.name, (raw === undefined || String(raw).trim() === '') ? item.default : raw]
    }).filter(([, value]) => value !== undefined && value !== null),
  )
  try {
    compiling.value = { step: '排队中' }
    await authoring.startRebuild(['flows'], { operation: selectedName.value, inputs: wanted })
    const final = await authoring.waitRebuild((status) => {
      const running = (status.steps || []).find((item) => item.status === 'running')
      compiling.value = { step: running?.label || '编译中' }
    })
    if (state.disposed) return
    if (final?.error) throw new Error(final.error)
    resetMotionMap()
    await loadFlowIndex()
    if (state.disposed) return
    // 编完立刻切到刚编出来的那一条; 切不过去说明产物与请求对不上, 明确报出来而不是
    // 静默停在旧片段上(那正是"改了参数却看不出变化"的原样复发)
    const hit = matchVariantIndex(flowIndex.value.get(selectedName.value), inputs.value, inputVars.value)
    if (hit < 0) throw new Error('编出来的片段与这组入参对不上, 请看后端日志')
    variantIndex.value = hit
    notify('已按当前入参编好这一条, 正在装载')
    await load(selectedName.value)
  } catch (err) {
    if (!state.disposed) notify(`单条编译失败: ${err?.message || err}`)
  } finally {
    if (!state.disposed) compiling.value = null
  }
}

// 验收钩子(仅开发构建); three_d/tools/visual_validation 的脚本靠它读内部真值
const uninstallHooks = installAnimHooks({
  manager,
  stack,
  transport,
  currentName: () => loaded.value?.label || selectedName.value,
})

onBeforeUnmount(() => {
  uninstallHooks()
  stack.detach()
})

// -- 初始化: 清单、台账、映射表、点表 --------------------------------------
editor.loadRepo()
  .then(() => {
    if (state.disposed) return
    const asked = String(route.params.flow || '')
    if (asked) load(asked)
  })
  .catch((err) => {
    if (!state.disposed) listError.value = `流程清单不可用: ${err.message}`
  })
loadFlowIndex()
loadMotionMap().then((map) => {
  if (!state.disposed) motionMap.value = map
})
twinApi.fetchPointsTree()
  .then((tree) => {
    if (!state.disposed) servoIndex.value = indexServoPoints(tree)
  })
  .catch(() => {
    // 点表不可用: 地轨段会退回映射表里的参考毫米
  })
fetch(`${POINTS_URL}?t=${Date.now()}`)
  .then((response) => (response.ok ? response.json() : null))
  .then((doc) => {
    if (!state.disposed && doc) pointCatalog.value = doc
  })
  .catch(() => {
    // 点位目录不可用: 机械臂段会标"点位无实测关节角"
  })
</script>

<template>
  <div class="mw">
    <div ref="containerRef" class="mw__canvas" />

    <ViewToolbar
      v-if="!error"
      :has-selection="false"
      :xray="view.xray"
      :wireframe="view.wireframe"
      :hidden-count="view.hidden"
      :show-helpers-toggle="false"
      :display-open="showDisplay"
      @view="onTool('view', $event)"
      @reset="onTool('reset')"
      @show-all="onTool('showAll')"
      @xray="onTool('xray', $event)"
      @wireframe="onTool('wireframe', $event)"
      @display="showDisplay = !showDisplay"
    />

    <DisplayPanel
      v-if="showDisplay && manager"
      :manager="manager"
      :stats="stats"
      :anchor-right="342"
      @close="showDisplay = false"
    />

    <aside v-if="!error" class="mw__left">
      <header class="mw__head">
        <h2>流程</h2>
        <span class="mw__badge">{{ flows.length }} 条</span>
      </header>
      <input v-model="filter" class="mw__search" type="search" placeholder="搜索流程…" />
      <p v-if="listError" class="mw__notice mw__notice--err">{{ listError }}</p>

      <div v-for="group in groups" :key="group.key" class="mw__group">
        <button type="button" class="mw__groupTitle" @click="toggleGroup(group.key)">
          <span>{{ collapsed.has(group.key) ? '▸' : '▾' }} {{ group.label }}</span>
          <span class="mw__groupCount">{{ group.items.length }}</span>
        </button>
        <ul v-if="!collapsed.has(group.key)" class="mw__list">
          <li
            v-for="flow in group.items"
            :key="flow.name"
            :class="['mw__item', { 'mw__item--on': selectedName === flow.name }]"
            :title="flow.note || flow.name"
            @click="pick(flow.name)"
          >
            <span class="mw__itemLabel">{{ flow.label || flow.name }}</span>
            <em class="mw__tag" :class="badgeOf(flow.name).cls" :title="badgeOf(flow.name).title">
              {{ badgeOf(flow.name).text }}
            </em>
          </li>
        </ul>
      </div>
      <p class="mw__tip">
        清单与流程界面同源：那里新增一个流程，这里刷新即多一条。
      </p>
    </aside>

    <aside v-if="!error" class="mw__right">
      <template v-if="selected || loaded">
        <section class="mw__panel">
          <header class="mw__head">
            <h2>{{ selected?.label || loaded?.label || selectedName }}</h2>
            <em v-if="selected" class="mw__tag" :class="badgeOf(selected.name).cls">
              {{ badgeOf(selected.name).text }}
            </em>
            <em v-else class="mw__tag mw__tag--exact">片段直达</em>
          </header>
          <code class="dm__name">{{ selectedName }}</code>
          <p v-if="selected?.note" class="mw__tip">{{ selected.note }}</p>
          <p v-else-if="!selected" class="mw__tip">
            按片段名直达（旧地址 /3d/motion/&lt;片段名&gt; 会重定向到这里）。
          </p>
        </section>

        <!-- 精编译片段的变体(如展开-上料 8 个缸): 一条流程一行, 缸号在这里选 -->
        <section v-if="variants.length > 1" class="mw__panel">
          <header class="mw__head">
            <h2>变体</h2>
            <span class="mw__badge">{{ variants.length }} 个</span>
          </header>
          <label class="dm__row">
            <span class="dm__key">{{ variants[0].variant?.[0]?.label || '变体' }}</span>
            <select
              class="dm__input"
              :value="variantIndex"
              @change="variantIndex = Number($event.target.value); load(selectedName)"
            >
              <option v-for="(item, index) in variants" :key="item.clipName" :value="index">
                {{ item.variant?.map((v) => `${v.label}${v.valueLabel}`).join(' · ') || item.clipName }}
              </option>
            </select>
          </label>
        </section>

        <section v-if="selected && inputVars.length" class="mw__panel">
          <header class="mw__head"><h2>入参</h2></header>
          <label v-for="item in inputVars" :key="item.name" class="dm__row">
            <span class="dm__key">{{ item.ui?.label || item.name }}</span>
            <select
              v-if="enumOf(item).length"
              class="dm__input"
              :value="String(inputs[item.name] ?? '')"
              @change="inputs = { ...inputs, [item.name]: $event.target.value }"
            >
              <option :value="''">{{ item.default == null ? '— 未选择 —' : `— 取默认 (${item.default}) —` }}</option>
              <option v-for="o in enumOf(item)" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <input
              v-else
              class="dm__input"
              :value="inputs[item.name]"
              :placeholder="String(item.default ?? '')"
              @change="inputs = { ...inputs, [item.name]: $event.target.value }"
            />
          </label>
          <p v-if="loaded?.source === 'exact' && loaded?.adhoc" class="mw__tip">
            这是按你填的入参**临时**编出来的片段；下次全量重编会消失。
            要长期保留，请把这个取值写进 pipeline/flow_params.yaml。
          </p>
          <p v-else-if="exactDirty" class="mw__tip">
            这组入参还没编过。点下面的按钮只重编这一条（约 20 秒），正式片段不受影响。
          </p>
        </section>

        <section v-if="selected || loaded?.source !== 'exact'" class="mw__panel">
          <p v-if="busy" class="mw__notice mw__notice--info">正在生成动画…</p>

          <p v-else-if="loaded?.source === 'no-motion'" class="mw__notice mw__notice--info">
            该流程无机械动作。<br />{{ loaded.reason }}
          </p>

          <p v-else-if="loaded?.source === 'failed'" class="mw__notice mw__notice--err">
            无法生成动画：{{ loaded.reason }}
          </p>

          <template v-else-if="loaded?.source === 'approx'">
            <p class="mw__notice mw__notice--warn">
              这是<strong>近似</strong>动画：前端按流程脚本即时展开，秒级可见。
              位置来自实测示教点，接近位/退离位由官方运动学离线反解；
              但分支只走一支、循环只演一轮、直线段按关节插值。
              <strong>用来看“这条流程大致怎么走”，不是用来验位置。</strong>
            </p>
            <ul v-if="loaded.notes.length" class="dm__notes">
              <li v-for="(note, i) in loaded.notes" :key="i">{{ note }}</li>
            </ul>
            <!-- 两类未表现必须分开说: "没进表"是待补的活, "参数运行期才定"不是 -->
            <p v-if="loaded.unknown.length" class="mw__tip">
              {{ loaded.unknown.length }} 个动作不在映射表中，只占了时间格：
              {{ loaded.unknown.slice(0, 4).join('、') }}
            </p>
            <p v-if="loaded.deferred?.length" class="mw__tip">
              {{ loaded.deferred.length }} 个动作已在映射表中，但缸号/槽位等参数要运行期才定，
              只占了时间格：{{ loaded.deferred.slice(0, 4).join('、') }}
            </p>

            <!-- 精编译按钮必须说实话: 上次为什么没成, 就在按钮旁边写着 -->
            <p class="mw__tip">
              <strong>精编译</strong>是另一级：后端逐条编译，实测示教点 + 官方运动学
              反解出整条直线轨迹，终点 FK 误差 ≤1mm，带板取放与锚点校验都在。用来验“位置对不对”。
            </p>
            <p v-if="lastFailure" class="mw__notice mw__notice--warn">
              这条流程上次精编译没成：{{ lastFailure }}
            </p>
            <button
              type="button"
              class="mw__btn mw__btn--wide"
              :disabled="Boolean(compiling)"
              @click="compileExact"
            >
              {{ compiling
                ? `编译中… ${compiling.step}`
                : `${lastFailure ? '重试' : '生成'}精确动画（后端逐条编译全部流程，约 10 分钟）` }}
            </button>
          </template>

          <template v-else-if="loaded?.source === 'exact'">
            <!-- 烘焙陈旧: 片段照播, 但机械臂与载荷落点仍是旧标定算的 -->
            <p
              v-if="clipStale.state === 'stale' || clipStale.state === 'unstamped'"
              class="mw__notice"
              :class="clipStale.state === 'stale' ? 'mw__notice--err' : 'mw__notice--warn'"
            >
              <strong>{{ clipStale.state === 'stale' ? '片段已陈旧' : '片段未标记' }}</strong>：
              {{ clipStale.reason }}。
              轴的毫米行程跟着新标定走，<strong>机械臂与载荷的落点不会</strong> —— 它们是编译时烘死的。
            </p>
            <p v-else class="mw__notice mw__notice--info">
              <strong>精编译</strong>片段：关节角来自实测示教点，接近位由官方运动学反解，
              move_l 段是整条离线 IK 轨迹（终点 FK 误差 ≤1mm）。<strong>几何是精确的。</strong>
            </p>
            <!-- 但"路线"仍是拍平过的: 分支取了一支、循环只编了一轮。
                 不写出来, "精编译"三个字会被读成"这就是实况"。 -->
            <ul v-if="loaded.notes?.length" class="dm__notes">
              <li v-for="(note, i) in loaded.notes" :key="i">{{ note }}</li>
            </ul>
            <!-- 两个按钮**各自独立出现**, 判据不同也不互相遮蔽:
                 上面这条治"标定变了片段没跟上"(全量), 下面这条治"想换一组入参看看"(单条)。
                 此前它们共用一个 v-if, 而 railCalib 是新的时候整段都不渲染 —— 于是提示
                 叫人"重新编译", 屏幕上却根本没有那个控件。 -->
            <button
              v-if="clipStale.state === 'stale' || clipStale.state === 'unstamped'"
              type="button"
              class="mw__btn mw__btn--wide"
              :disabled="Boolean(compiling)"
              @click="compileExact"
            >
              {{ compiling ? `编译中… ${compiling.step}` : '按当前标定重新编译（全部流程，约 10 分钟）' }}
            </button>
            <button
              v-if="exactDirty"
              type="button"
              class="mw__btn mw__btn--wide"
              :disabled="Boolean(compiling)"
              @click="compileExactOne"
            >
              {{ compiling ? `编译中… ${compiling.step}` : '按这组入参编译这一条（约 20 秒）' }}
            </button>
          </template>
        </section>

        <section v-if="loaded?.steps?.length" class="mw__panel">
          <header class="mw__head">
            <h2>步骤</h2>
            <span class="mw__badge">{{ loaded.steps.length }} 步</span>
          </header>
          <ol class="mw__steps">
            <li
              v-for="step in loaded.steps"
              :key="step.index"
              :class="['mw__step', { 'mw__step--on': step.index === transport.stepIndex }]"
              :title="`${step.at.toFixed(1)}s ~ ${step.end.toFixed(1)}s`"
              @click="seekStep(step)"
            >
              <span class="mw__stepTime">{{ step.at.toFixed(1) }}s</span>
              <span class="mw__stepLabel">{{ step.label }}</span>
            </li>
          </ol>
        </section>
      </template>
      <p v-else class="mw__notice mw__notice--info">
        在左栏选一条流程：这里会给出它的入参、动画来源与逐步时间轴。
      </p>
    </aside>

    <div v-if="loaded?.steps?.length" class="mw__transport">
      <button type="button" class="mw__btn" @click="stack.player.value?.toggle()">
        {{ transport.playing ? '⏸ 暂停' : '▶ 播放' }}
      </button>
      <select
        class="mw__speed"
        :value="transport.speed"
        @change="stack.player.value?.setSpeed($event.target.value)"
      >
        <option :value="0.5">0.5×</option>
        <option :value="1">1×</option>
        <option :value="1.5">1.5×</option>
        <option :value="2">2×</option>
      </select>
      <input
        type="range"
        class="mw__timeline"
        min="0"
        :max="transport.duration"
        step="0.05"
        :value="transport.time"
        @input="stack.player.value?.seek(Number($event.target.value))"
      />
      <span class="mw__clock">{{ fmtTime(transport.time) }} / {{ fmtTime(transport.duration) }}</span>
      <span class="mw__now">{{ loaded.steps[transport.stepIndex]?.label || '' }}</span>
    </div>

    <p v-if="message" class="mw__toast">{{ message }}</p>

    <div v-if="loading" class="mw__mask">加载模型… {{ Math.round(progress * 100) }}%</div>
    <div v-if="error" class="mw__mask mw__mask--err">初始化失败：{{ error }}</div>
  </div>
</template>

<style scoped>
.dm__name {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text-dim);
  word-break: break-all;
}

.dm__row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
  font-size: 12px;
}

.dm__key {
  flex: 0 0 96px;
  overflow: hidden;
  color: var(--text-mid);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dm__input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 4px 7px;
  font: inherit;
  font-size: 12px;
  color: var(--text);
  background: var(--well);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.dm__notes {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-mid);
}
</style>
