<script setup>
/**
 * 功能: 演示子页 —— 逐条确认原子动作设置得是否合理.
 *
 * 左栏按设备分组列出动作栏里的**全部**原子动作(GET /api/actions), 右栏放该动作的
 * 全部参数与模拟结论; 选中即算一次 planSimulation, 徽章直接告诉你这条能不能看.
 *
 * 两种验证方式互斥(沿用原「动作验证」面板的语义):
 *   模拟播放  显式接管(setAxisHold + 涉及机械臂时 setRobotHold), 用既有 compileClip +
 *            ClipPlayer 在虚拟机上播 —— 终点应与实机同名位置目视重合。ClipPlayer 向后
 *            seek 会 home() 清场, 所以必须全程接管。
 *   实机对照  不接管, 去动作栏执行(那里有三道安全关卡), 实机反馈经实时链驱动虚拟 ——
 *            "虚拟是否跟随"本身就是验收。本页不下发任何指令。
 */
import { computed, inject, ref, shallowRef, watch } from 'vue'

import { compileClip, parseClip, railCalibStatus } from '../../anim/clipSchema.js'
import { ClipPlayer } from '../../anim/ClipPlayer.js'
import * as twinApi from '../../twin/api.js'
import ActionParamsForm from '../../twin/panels/ActionParamsForm.vue'
import { coerceParams, defaultValuesOf, modeAllows } from '../../twin/panels/actionParams.js'
import * as authoring from '../../workbench/authoringApi.js'
import { indexServoPoints, planSimulation } from '../../demo/actionSim.js'
import { loadMotionMap } from '../../demo/motionMap.js'

/** 目录名 → 中文组名. 目录本身是编号前缀, 直接显示对用户没有信息量 */
const GROUP_LABELS = {
  '01_sampling': '上样',
  '02_develop': '展开',
  '03_collect': '收集',
  '04_photoscrape': '拍照刮板',
  '05_feedlift': '上下料升降',
  '06_rail': '地轨',
  '07_robot': '机械臂',
  '08_pump': '泵',
  '10_vision': '视觉',
  '11_staging_a': '中转位',
  '12_material': '物料',
}

/** 资源钩子: 后端 /run 直接 409, 编排层也禁止直调 —— 列出来但不可选 */
const RESOURCE_HOOKS = new Set(['pump.vacuum_on', 'pump.vacuum_off'])

/** 内置正式片段清单(生产构建拿不到 listClips 端点时) */
const BUNDLED_CLIPS = ['robot.tool_pickup', 'robot.tool_return']

const ctx = inject('motionWorkbench')
const { manager, manifest, stack, transport, state, notify } = ctx

const actions = ref([])
const clipNames = ref([...BUNDLED_CLIPS])
const servoIndex = shallowRef(new Map())
const motionMap = shallowRef(null)
/** 机器人点位目录: robot.move_to_point/home 靠它取实测关节角, 正式片段编译也要它 */
const pointCatalog = shallowRef(null)
const controlMode = ref('')
const loadError = ref('')
const filter = ref('')
const collapsed = ref(new Set())

const selected = shallowRef(null)
const values = ref({})
/**
 * 排液动作的起始液位(mL); null = 用 planSimulation 给的建议值.
 *
 * 为什么要这么一个框: develop.drain / rinse_suction 的入参里**一滴体积都没有**, 只有
 * settle_s / drain_duration_s 这类时长 —— 缸里原本有多少液, 这条动作本身不知道. 建议值
 * 由配对注液动作(manifest 的 demoFillFrom)的目录默认配方推出, 是个假设; 让它可改,
 * 就把这个假设摆到明面上, 而不是藏在一句 note 里.
 */
const startMl = ref(null)
/** 模拟播放会话(null = 未在模拟) */
const sim = shallowRef(null)

/**
 * 功能: 过滤后的动作, 按目录分组.
 * @returns {Array<{key: string, label: string, items: Array}>} 分组
 */
const groups = computed(() => {
  const term = filter.value.trim().toLowerCase()
  const buckets = new Map()
  for (const action of actions.value) {
    if (term
      && !String(action.name || '').toLowerCase().includes(term)
      && !String(action.label || '').toLowerCase().includes(term)) continue
    const key = action.group || ''
    if (!buckets.has(key)) buckets.set(key, [])
    buckets.get(key).push(action)
  }
  return [...buckets.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, items]) => ({
      key,
      label: GROUP_LABELS[key] || key || '未分组',
      items: items.sort((a, b) => String(a.label || a.name).localeCompare(String(b.label || b.name), 'zh')),
    }))
})

const total = computed(() => actions.value.length)

/** 选中动作的模拟规划 */
const plan = computed(() => {
  const action = selected.value
  if (!action) return null
  return planSimulation(action, coerceParams(action.params || [], values.value), {
    servoIndex: servoIndex.value,
    manifest: manifest.value,
    clipNames: clipNames.value,
    motionMap: motionMap.value,
    pointCatalog: pointCatalog.value,
    currentMmOf: (id) => stack.rig.value?.axes?.get(id)?.valueMm ?? null,
    // 排液动作的起始液位与推建议值要用的动作目录; 其余动作用不到这两项
    startMl: startMl.value,
    actionCatalog: actions.value,
  })
})

/** 该动作要不要露"起始液位"框 —— 由 planSimulation 判定, 面板不自己认动作名 */
const needsStartMl = computed(() => Boolean(plan.value?.needsStartMl))
/** 框里的显示值: 用户改过就用他的, 否则用规划给的建议值 */
const startMlShown = computed(() => (
  startMl.value !== null && startMl.value !== ''
    ? startMl.value
    : (plan.value?.startMlSuggested ?? '')
))

const planTag = computed(() => {
  const kind = plan.value?.kind
  if (kind === 'clip') return { text: '精编译片段', cls: 'mw__tag--exact' }
  if (kind === 'pseudo') return { text: '可模拟', cls: 'mw__tag--approx' }
  if (kind === 'no-motion') return { text: '无机械动作', cls: 'mw__tag--none' }
  return { text: '无法模拟', cls: 'mw__tag--fail' }
})

const modeBlocked = computed(
  () => selected.value !== null && modeAllows(selected.value, controlMode.value) === false,
)

/**
 * 功能: 选中一个动作.
 * @param {object} action 动作定义
 * @returns {void}
 */
function select(action) {
  if (RESOURCE_HOOKS.has(action.name)) return
  exitSim()
  selected.value = action
  values.value = defaultValuesOf(action.params || [])
  // 起始液位交回"跟建议值": 上一条动作的手改值套到别的缸/别条动作上没有任何依据
  startMl.value = null
}

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
 * 功能: 读取片段 YAML(dev 走授权中间件, 生产 fetch 静态文件).
 * @param {string} name 片段名
 * @returns {Promise<string>} YAML 文本
 */
async function fetchClipText(name) {
  try {
    return await authoring.readClip(name)
  } catch {
    // 强刷: 片段是 --flows 的产物, 后端不发 Cache-Control, 不加戳会吃到旧片段
    const response = await fetch(`/api/3d/assets/clips/${name}.yaml?t=${Date.now()}`)
    if (!response.ok) throw new Error(`加载片段失败: ${name}`)
    return await response.text()
  }
}

/**
 * 功能: 进入模拟播放 —— 装载片段并播.
 *
 * 这里不接管实时链: 演示子页用的是离线驱动栈(stack.rig), 本来就没有 feed 在写。
 * 标定子页才有实时链, 而两者互斥(见 MotionWorkbench.activate)。
 * @returns {Promise<void>}
 */
async function startSim() {
  const current = plan.value
  if (!current || current.kind === 'unsupported' || current.kind === 'no-motion' || sim.value) return
  try {
    let compiled
    if (current.kind === 'clip') {
      if (!pointCatalog.value) throw new Error('点位目录不可用')
      compiled = compileClip(parseClip(await fetchClipText(current.clipName)), {
        pointCatalog: pointCatalog.value,
      })
    } else {
      compiled = compileClip(current.doc, {})
    }
    if (state.disposed) return
    stack.player.value?.load(compiled)
    // 烘焙陈旧判定: 片段的机械臂/载荷落点是编译期按当时的轴标定烘死的, 标完零点不重
    // 编译就对不上, 而片段照播不报错. 这里逐条比对, 比索引级判定更准(不必额外取数).
    // 没有 source 段 = 手写片段(如 develop.lid_cycle), 本就不含编译期烘焙, 传 null
    // 判"无关"; 有 source 却没 railCalib 键才是"旧编译器产物, 未标记"
    const stale = railCalibStatus(
      compiled.source ? compiled.source.railCalib : null,
      manifest.value,
    )
    sim.value = {
      label: compiled.label || selected.value.name,
      steps: compiled.steps,
      stale: stale.state === 'stale' || stale.state === 'unstamped' ? stale : null,
    }
    if (!transport.value.playing) stack.player.value?.toggle()
    notify(`已装载「${compiled.label}」(${compiled.duration.toFixed(1)}s · ${compiled.steps.length} 步)`)
  } catch (err) {
    notify(`模拟启动失败: ${err.message}`)
    exitSim()
  }
}

/**
 * 功能: 退出模拟 —— 停播并把机构清回零位.
 * @returns {void}
 */
function exitSim() {
  if (!sim.value) return
  if (transport.value.playing) stack.player.value?.toggle()
  stack.rig.value?.home()
  manager.value?.invalidateShadows()
  sim.value = null
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

// 参数改了就作废当前模拟(片段是按旧参数编的, 继续播是骗人)
watch(values, () => {
  if (sim.value) exitSim()
}, { deep: true })

// 注意不要给这些加载加人为超时: 软渲染环境下首帧把任务队列饿上十几秒,
// fetch 慢而必达, 加超时反而丢掉成功响应(AxisCalibBoard 同款教训)
twinApi.fetchActions()
  .then((list) => {
    if (state.disposed === false) actions.value = list || []
  })
  .catch((err) => {
    if (state.disposed === false) loadError.value = `动作目录不可用: ${err.message}`
  })
twinApi.fetchPointsTree()
  .then((tree) => {
    if (state.disposed === false) servoIndex.value = indexServoPoints(tree)
  })
  .catch(() => {
    // 点表不可用: 相关动作会给出对应 reason, 不致命
  })
twinApi.fetchMode()
  .then((payload) => {
    if (state.disposed === false) controlMode.value = payload?.mode || ''
  })
  .catch(() => {
    // 模式读不到就不做前端置灰, 后端仍会拒
  })
authoring.listClips()
  .then((names) => {
    if (state.disposed === false && names?.length) {
      clipNames.value = [...new Set([...names, ...BUNDLED_CLIPS])]
    }
  })
  .catch(() => {
    // 生产构建: 用内置清单
  })
loadMotionMap()
  .then((map) => {
    if (state.disposed === false) motionMap.value = map
  })
  .catch(() => {
    // 映射表拿不到: planSimulation 退化为只认地轨与正式片段
  })
fetch(`/api/3d/assets/generated/robot-points.json?t=${Date.now()}`)
  .then((response) => (response.ok ? response.json() : null))
  .then((doc) => {
    if (state.disposed === false && doc) pointCatalog.value = doc
  })
  .catch(() => {
    // 点位目录拿不到: 机械臂到点动作会如实说"没有实测关节角"
  })
</script>

<template>
  <div>
    <aside class="mw__left">
      <header class="mw__head">
        <h2>原子动作</h2>
        <span class="mw__badge">{{ total }} 条</span>
      </header>
      <input v-model="filter" class="mw__search" type="search" placeholder="搜索动作…" />
      <p v-if="loadError" class="mw__notice mw__notice--err">{{ loadError }}</p>

      <div v-for="group in groups" :key="group.key" class="mw__group">
        <button type="button" class="mw__groupTitle" @click="toggleGroup(group.key)">
          <span>{{ collapsed.has(group.key) ? '▸' : '▾' }} {{ group.label }}</span>
          <span class="mw__groupCount">{{ group.items.length }}</span>
        </button>
        <ul v-if="!collapsed.has(group.key)" class="mw__list">
          <li
            v-for="action in group.items"
            :key="action.name"
            :class="['mw__item', {
              'mw__item--on': selected?.name === action.name,
              'mw__item--off': RESOURCE_HOOKS.has(action.name),
            }]"
            :title="RESOURCE_HOOKS.has(action.name)
              ? `${action.name} · 资源钩子, 由资源表自动调度, 不可直调`
              : action.name"
            @click="select(action)"
          >
            <span class="mw__itemLabel">{{ action.label || action.name }}</span>
            <em v-if="RESOURCE_HOOKS.has(action.name)" class="mw__tag">钩子</em>
          </li>
        </ul>
      </div>
    </aside>

    <aside class="mw__right">
      <template v-if="selected">
        <section class="mw__panel">
          <header class="mw__head">
            <h2>{{ selected.label || selected.name }}</h2>
            <em class="mw__tag" :class="planTag.cls">{{ planTag.text }}</em>
          </header>
          <code class="ad__name">{{ selected.name }}</code>
          <p v-if="selected.plc_link" class="mw__tip">{{ selected.plc_link }}</p>
        </section>

        <section class="mw__panel">
          <header class="mw__head"><h2>参数</h2></header>
          <ActionParamsForm v-model="values" :params="selected.params || []" />
          <!--
            排液动作的起始液位: 不是这条动作的入参(它根本不带体积), 而是**演示假设**,
            所以单独放在参数表外面, 免得被读成"下发给 PLC 的一个值".
          -->
          <div v-if="needsStartMl" class="ad__assume">
            <label class="ad__assumeRow">
              <span>起始液位 (mL)</span>
              <input
                type="number"
                min="0"
                step="1"
                class="ad__assumeInput"
                :value="startMlShown"
                @input="startMl = $event.target.value === '' ? null : Number($event.target.value)"
              >
            </label>
            <p class="mw__tip">
              演示假设，不下发。排液动作本身不带体积——缸内原有多少液，这条动作不知道；
              预填值按配对注液动作的目录默认配方推得。
            </p>
          </div>
        </section>

        <section class="mw__panel">
          <p v-if="modeBlocked" class="mw__notice mw__notice--warn">
            当前为 {{ controlMode }} 模式，该动作仅允许在 {{ (selected.modes || []).join(' / ') }} 模式下执行；
            模拟播放不受此限，但实机对照会被上位机拒绝。
          </p>
          <p v-if="plan && plan.kind === 'no-motion'" class="mw__notice mw__notice--info">
            该动作无机械动作（{{ plan.reason }}）。
          </p>
          <p v-else-if="plan && plan.kind === 'unsupported'" class="mw__notice mw__notice--warn">
            {{ plan.reason }}
          </p>
          <!-- 动画只演了一半时必须说出来, 否则会被当成"三维已经演全了" -->
          <p v-if="plan && plan.note" class="mw__notice mw__notice--info">{{ plan.note }}</p>
          <div class="ad__row">
            <button
              type="button"
              class="mw__btn"
              :disabled="!plan || plan.kind === 'unsupported' || plan.kind === 'no-motion'"
              @click="startSim"
            >▶ 模拟播放</button>
            <button
              v-if="sim"
              type="button"
              class="mw__btn mw__btn--ghost"
              @click="exitSim"
            >退出模拟</button>
          </div>
          <p class="mw__tip">
            本页只算不发：模拟播放全在虚拟机上进行，不会向设备下发任何指令。
            要做实机对照请到动作栏执行，那里有模式门禁与二次确认。
          </p>
        </section>

        <section v-if="sim" class="mw__panel">
          <header class="mw__head">
            <h2>{{ sim.label }}</h2>
            <span class="mw__badge">{{ sim.steps.length }} 步</span>
          </header>
          <!-- 片段陈旧: 轴的毫米行程跟着新标定走, 机械臂与载荷的落点不会 -->
          <p
            v-if="sim.stale"
            class="mw__notice"
            :class="sim.stale.state === 'stale' ? 'mw__notice--err' : 'mw__notice--warn'"
          >
            <strong>{{ sim.stale.state === 'stale' ? '片段已陈旧' : '片段未标记' }}</strong>：
            {{ sim.stale.reason }}。到演示栏重新编译流程动画可修。
          </p>
          <ol class="mw__steps">
            <li
              v-for="step in sim.steps"
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
        在左栏选一个原子动作：右侧会列出它的全部参数，并算出这条动作能不能在三维里播出来。
      </p>
    </aside>

    <!-- 传输条: 只在有模拟片段时出现 -->
    <div v-if="sim" class="mw__transport">
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
      <span class="mw__now">{{ sim.steps[transport.stepIndex]?.label || '' }}</span>
    </div>
  </div>
</template>

<style scoped>
.ad__name {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text-dim);
  word-break: break-all;
}

.ad__row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

/* 演示假设区: 与真入参用一条分隔线隔开, 视觉上就不像"要下发的参数" */
.ad__assume {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--mw-line, rgb(255 255 255 / 18%));
}

.ad__assumeRow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.ad__assumeInput {
  width: 96px;
}
</style>
