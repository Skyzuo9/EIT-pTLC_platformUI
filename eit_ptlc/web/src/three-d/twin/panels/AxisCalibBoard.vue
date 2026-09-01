<script setup>
/**
 * 功能: 轴标定工作台(AxisCalibBoard) —— 标定页(/calib)的核心面板, AxisDebugPanel 演进版.
 *
 * 标定闭环: [接管] 把该轴从实时覆写里摘出来 → jog/步进把虚拟模型拖到与实机目视重合
 *          → [匹配] 按 zero_new = zero_old + (R − P_v) 反算零点并释放接管
 *          → [写回 rig_map] 直落 pipeline/rig_map.yaml(自动 .bak)并秒级重跑 manifest.
 *
 * 继承 AxisDebugPanel 的全部纪律:
 *   - 改的 spec 与 MachineStateDriver 是同一对象引用, 写后立即生效; 同 mm 值下
 *     setAxisMm 返回"未变化", 每次写入后必须自行 manager.invalidateShadows();
 *   - manager 是原生 SceneManager 实例, 本组件用本地 tick 驱动重算, 绝不 reactive 化;
 *   - 非 rigged 轴无法 jog(先在装配台指认 carriage 并重跑), 行置灰给指引;
 *   - 接管态锁定 sign 编辑: 匹配公式的 sign 消去以"接管期间未翻转 sign"为前提.
 * 剪贴板导出保留(生产构建无写盘能力时的降级通道).
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { patchRigMapAxisCalib } from '../../motion/rigPatch.js'
import * as api from '../../workbench/authoringApi.js'
import {
  buildYamlFragment,
  calibValuesOf,
  changedAxes,
  formatMm,
  matchDriftToleranceM,
  matchedZeroOffset,
  rangeCovering,
  snapshotAxes,
} from './axisCalib.js'

const props = defineProps({
  /** SceneManager 实例(父级 shallowRef 持有, 挂载时 bindings 必已建立) */
  manager: { type: Object, required: true },
  /** 绑定契约(其 axes[] 条目就是驱动层持有的 spec 对象) */
  manifest: { type: Object, default: null },
  /** TwinFeed.realtimeStatus 载荷(axes.items[] 是未 clamp 的原始采样值) */
  realtime: { type: Object, default: () => ({}) },
  /** 是否实时模式(live 下未接管且有数据的轴禁用 jog, 由 feed 接管) */
  live: { type: Boolean, default: false },
})

const emit = defineEmits([
  /** 写回 + 重跑 manifest 成功: 宿主该热重载契约并重挂本组件 */
  'rebuilt',
  /** 未写回轴数变化: 宿主拿它做离页拦截 */
  'dirty',
])

/** 驱动实例: SceneManager → TwinBindings → MachineStateDriver(原生对象链) */
const machine = props.manager?.bindings?.machine || null

/** spec 内存态变更计数 —— rows 重算的唯一扳机(spec 本身不是响应式对象) */
const tick = ref(0)
/** 挂载时的原值快照: diff 基准与单轴还原的来源 */
const snapshot = snapshotAxes(props.manifest?.axes)
/** 零点微调步进(mm) */
const stepMm = ref(1)
/** 导出按钮的"已复制"反馈 */
const copied = ref(false)
/** 已接管的轴 id 集合(挂起实时覆写, 允许手动拖对齐) */
const held = ref(new Set())
/** 写回状态 */
const writing = ref(false)
const writeMsg = ref('')
const authoringAvailable = ref(false)

const STEP_OPTIONS = [0.1, 1, 10]

/** 实时轴条目按 id 索引(HUD 同源: {id,label,position,velocity,stale,rigged}) */
const liveById = computed(() => {
  const map = new Map()
  for (const item of props.realtime?.axes?.items || []) map.set(item.id, item)
  return map
})

/** 相对快照有变更的轴清单(导出/写回与行高亮共用) */
const changed = computed(() => {
  void tick.value
  return changedAxes(props.manifest?.axes, snapshot)
})
const changedIds = computed(() => new Set(changed.value.map((item) => item.id)))

/** 面板行: manifest spec 现值 ⨝ 实时采样 ⨝ 驱动层已应用值 ⨝ 接管态 */
const rows = computed(() => {
  void tick.value
  return (props.manifest?.axes || []).map((spec) => {
    const entry = machine?.axes?.get(spec.id)
    const live = liveById.value.get(spec.id)
    const vals = calibValuesOf(spec)
    const position = Number(live?.position)
    const hasLive = Number.isFinite(position)
    const isHeld = held.value.has(spec.id)
    return {
      id: spec.id,
      label: spec.label || spec.id,
      rigged: Boolean(spec.rigged && entry),
      vals,
      appliedMm: entry && Number.isFinite(entry.valueMm) ? entry.valueMm : null,
      liveMm: hasLive ? position : null,
      stale: Boolean(live?.stale),
      outOfRange: hasLive && (position < vals.rangeMm[0] || position > vals.rangeMm[1]),
      changed: changedIds.value.has(spec.id),
      held: isHeld,
      // live 且有数据且未接管 -> feed 每帧覆写, jog 无意义; 接管后放开
      jogDisabled: props.live && hasLive && !isHeld,
      // 匹配的前提: 接管中(P_v 是人拖出来的) + 有实时反馈(R 可用且非 stale)
      canMatch: isHeld && hasLive && !live?.stale,
    }
  })
})

/**
 * 可标定的轴 —— 面板的主体.
 *
 * 未装配的轴(rigged:false)整段控件都被 `v-if="row.rigged"` 关掉, 只剩两行只读值,
 * 却和可标定的轴一样占版面. 十一根轴混排在 320 px 栏里要滚很久才找得到能动的那根,
 * 所以拆开, 未装配的收进折叠区.
 */
const riggedRows = computed(() => rows.value.filter((row) => row.rigged))
const unriggedRows = computed(() => rows.value.filter((row) => !row.rigged))
/** 未装配轴折叠区是否展开 */
const showUnrigged = ref(false)

// 未写回轴数上报宿主: 标定改的是 manifest 内存态, 离页即散, 宿主要据此拦一下
watch(
  () => changed.value.length,
  (count) => emit('dirty', count),
  { immediate: true },
)

/**
 * 功能: 改一条轴的 spec 并让改动立即可见 —— 统一入口.
 *       重放优先级: 接管中用驱动层已应用值(保持人拖的位置) > 实时采样 > 当前零点.
 * @param {string} id 轴 id
 * @param {Function} mutate 就地修改 spec 的回调
 * @returns {void}
 */
function applySpec(id, mutate) {
  const entry = machine?.axes?.get(id)
  if (!entry) return
  mutate(entry.spec)
  const live = Number(liveById.value.get(id)?.position)
  const fallback = Number.isFinite(entry.valueMm)
    ? entry.valueMm
    : Number(entry.spec.zeroOffsetMm || 0)
  const replay = held.value.has(id) || !Number.isFinite(live) ? fallback : live
  machine.setAxisMm(id, replay)
  props.manager.invalidateShadows?.()
  tick.value += 1
}

/**
 * 功能: 接管/释放一条轴的实时覆写.
 * @param {string} id 轴 id
 * @returns {void}
 */
function toggleHold(id) {
  const bindings = props.manager?.bindings
  if (!bindings?.setAxisHold) return
  const next = new Set(held.value)
  if (next.has(id)) {
    next.delete(id)
    bindings.setAxisHold(id, false)
  } else {
    next.add(id)
    bindings.setAxisHold(id, true)
  }
  held.value = next
  tick.value += 1
}

/**
 * 功能: jog —— 滑杆直接写 mm 绝对值; 接管期允许越界试探(range 本身可能未标对).
 * @param {string} id 轴 id
 * @param {*} raw 滑杆原始值
 * @returns {void}
 */
function onJog(id, raw) {
  const mm = Number(raw)
  if (!Number.isFinite(mm) || !machine?.axes?.has(id)) return
  machine.setAxisMm(id, mm, { unclamped: held.value.has(id) })
  props.manager.invalidateShadows?.()
  tick.value += 1
}

/**
 * 功能: "匹配" —— 虚拟已与实机目视重合, 反算零点写入并做不动性校验, 成功后释放接管.
 *
 * 不动性校验: zero_new 的代数构造保证"以 R 重放后模型位置不变", 位移超出零点量化
 * 残差(matchDriftToleranceM)说明 clamp/公式/代码有 bug —— 当场报错而不是静默错标.
 * 容差不可再收紧, 理由见 axisCalib.matchDriftToleranceM 的注释.
 *
 * 失败时**整体回滚**(零点 + range)并**保留接管** —— 用户刚做完的目视对齐很贵,
 * 不能因为一次校验失败就被 feed 覆写掉、逼人从头 jog.
 *
 * @param {object} row 面板行
 * @returns {void}
 */
function onMatch(row) {
  writeMsg.value = '' // 面板级共用状态行: 先清陈旧文案, 否则会拿上一根轴的结果误导人
  const entry = machine?.axes?.get(row.id)
  if (!entry) return
  if (!row.canMatch) {
    writeMsg.value = `${row.id} 无法匹配: 需先「接管」该轴, 且实时反馈可用(非 stale)`
    return
  }
  const liveMm = row.liveMm
  // 撤销基准取"点击前"而非挂载快照 —— 后者会连带丢掉本次会话里更早的成功匹配/手调零点
  const appliedMm = entry.valueMm
  const zeroBefore = Number(entry.spec.zeroOffsetMm ?? 0)
  const zeroNew = matchedZeroOffset({ liveMm, appliedMm, zeroOffsetMm: zeroBefore })
  if (zeroNew === null) {
    writeMsg.value = `${row.id} 无法匹配: 实时反馈或已应用值非法`
    return
  }

  // R 越界会被 feed 的 clamp 打回边界 —— 匹配前自动扩界并提示
  const vals = calibValuesOf(entry.spec)
  const rangeBefore = [...vals.rangeMm]
  let rangeNote = ''
  if (liveMm < vals.rangeMm[0] || liveMm > vals.rangeMm[1]) {
    const nextRange = rangeCovering(vals.rangeMm, liveMm)
    entry.spec.rangeMm = nextRange
    rangeNote = ` · range 已扩为 [${formatMm(nextRange[0])}, ${formatMm(nextRange[1])}]`
  }

  const before = entry.node.position.clone()
  entry.spec.zeroOffsetMm = zeroNew
  machine.setAxisMm(row.id, liveMm)
  const driftM = entry.node.position.distanceTo(before)
  const tolM = matchDriftToleranceM(entry.spec)
  if (driftM > tolM) {
    // 理论恒等被打破 = 代码或 clamp 有 bug: 零点与 range 一并撤销, 并以人拖出的
    // P_v 越界重放, 让节点逐位回到 before(接管仍在, 对齐不丢)
    entry.spec.zeroOffsetMm = zeroBefore
    entry.spec.rangeMm = rangeBefore
    machine.setAxisMm(row.id, appliedMm, { unclamped: true })
    writeMsg.value = `匹配校验失败(${row.id} 位移 ${driftM.toExponential(2)} m `
      + `> 容差 ${tolM.toExponential(2)} m), 已撤销, 接管保留 —— 请报告`
    console.error('[calib] 匹配不动性校验失败', row.id, driftM, tolM)
  } else {
    writeMsg.value = `${row.id} 零点已匹配为 ${formatMm(zeroNew)} mm${rangeNote}`
    // 释放接管: feed 下一帧用新零点覆写, 目视应保持重合 —— 这本身就是即时验收
    if (held.value.has(row.id)) toggleHold(row.id)
  }
  props.manager.invalidateShadows?.()
  tick.value += 1
}

/**
 * 功能: 零点微调 —— 输入框直设或步进按钮增减.
 * @param {string} id 轴 id
 * @param {*} raw 新零点(mm)
 * @returns {void}
 */
function onZeroSet(id, raw) {
  const value = Number(raw)
  if (!Number.isFinite(value)) {
    tick.value += 1 // 非法输入: 让输入框弹回当前值
    return
  }
  applySpec(id, (spec) => {
    spec.zeroOffsetMm = Math.round(value * 1000) / 1000
  })
}

/**
 * 功能: 零点按步进增减.
 * @param {string} id 轴 id
 * @param {number} direction +1/-1
 * @returns {void}
 */
function onZeroStep(id, direction) {
  const entry = machine?.axes?.get(id)
  if (!entry) return
  onZeroSet(id, Number(entry.spec.zeroOffsetMm || 0) + direction * stepMm.value)
}

/**
 * 功能: 翻转方向符号(接管态锁定 —— 匹配公式以 sign 不变为前提).
 * @param {string} id 轴 id
 * @returns {void}
 */
function onFlipSign(id) {
  if (held.value.has(id)) return
  applySpec(id, (spec) => {
    spec.sign = -(Number(spec.sign) || 1)
  })
}

/**
 * 功能: 改 clamp 边界(lo>hi 视为非法, 弹回).
 * @param {string} id 轴 id
 * @param {number} index 0=下界 1=上界
 * @param {*} raw 新值
 * @returns {void}
 */
function onRangeSet(id, index, raw) {
  const entry = machine?.axes?.get(id)
  const value = Number(raw)
  if (!entry || !Number.isFinite(value)) {
    tick.value += 1
    return
  }
  const next = [...calibValuesOf(entry.spec).rangeMm]
  next[index] = value
  if (next[0] > next[1]) {
    tick.value += 1
    return
  }
  applySpec(id, (spec) => {
    spec.rangeMm = next
  })
}

/**
 * 功能: 单轴还原到挂载时的原值.
 * @param {string} id 轴 id
 * @returns {void}
 */
function onRevert(id) {
  const before = snapshot.get(id)
  if (!before) return
  applySpec(id, (spec) => {
    spec.sign = before.sign
    spec.zeroOffsetMm = before.zeroOffsetMm
    spec.rangeMm = [...before.rangeMm]
  })
}

/**
 * 功能: 导出变更轴的 rig_map 回填片段到剪贴板(生产构建的降级通道).
 * @returns {Promise<void>} 完成
 */
async function onExport() {
  const text = buildYamlFragment(changed.value, new Date().toISOString())
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const area = document.createElement('textarea')
    area.value = text
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
  }
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 1600)
}

/**
 * 功能: 把变更轴直接写回 pipeline/rig_map.yaml 并秒级重跑 manifest.
 *
 * 重跑完必须让宿主热重载契约(emit rebuilt), 不能只提示"刷新页面": 写盘与重跑都成功了,
 * 而页面还抱着进页时那份 manifest —— 画面按旧零点摆且毫无报错, 正是"标完不生效"的由来.
 * @returns {Promise<void>} 完成
 */
async function onWriteBack() {
  if (!changed.value.length) return
  writing.value = true
  writeMsg.value = ''
  try {
    const patch = changed.value.map((item) => ({
      id: item.id,
      sign: item.after.sign,
      zeroOffsetMm: item.after.zeroOffsetMm,
      rangeMm: [...item.after.rangeMm],
    }))
    const text = await api.readFile('rig_map')
    await api.writeFile('rig_map', patchRigMapAxisCalib(text, patch))
    writeMsg.value = '已写回 rig_map.yaml(自动 .bak), 重跑 manifest 中…'
    await api.startRebuild(['manifest', 'manifest-cr5', 'deploy'])
    const final = await api.waitRebuild()
    if (final.error) {
      writeMsg.value = `manifest 重跑失败: ${final.error}`
    } else {
      writeMsg.value = '已固化并生效: rig_map 与 manifest 均已更新'
      // 宿主据此重取契约并重挂驱动栈; 本组件随后按新契约整块重挂
      emit('rebuilt')
    }
  } catch (err) {
    writeMsg.value = `写回失败: ${err.message}`
  } finally {
    writing.value = false
  }
}

onMounted(async () => {
  // 注意不要给这个探测加人为超时: 软渲染(无 GPU)环境下首帧会把任务队列饿上十几秒,
  // fetch 慢而必达 —— 加超时反而把成功响应丢掉(踩过). 真机上毫秒级返回.
  authoringAvailable.value = await api.probeAuthoring()
  if (import.meta.env.DEV) {
    // Playwright/console 验证钩子(承接 __ptlcAxisDebug 的配方, 新增接管/匹配)
    window.__ptlcCalib = {
      jog: (id, mm) => onJog(id, mm),
      setZero: (id, value) => onZeroSet(id, value),
      flipSign: (id) => onFlipSign(id),
      setRange: (id, lo, hi) => {
        onRangeSet(id, 0, lo)
        onRangeSet(id, 1, hi)
      },
      hold: (id, on) => {
        if (held.value.has(id) !== Boolean(on)) toggleHold(id)
      },
      match: (id) => {
        const row = rows.value.find((item) => item.id === id)
        if (row) onMatch(row)
        return machine?.axes?.get(id)?.spec?.zeroOffsetMm
      },
      revert: (id) => onRevert(id),
      export: () => buildYamlFragment(changed.value, new Date().toISOString()),
      rows: () => rows.value,
    }
  }
})

onBeforeUnmount(() => {
  // 接管兜底: 离开标定页必须把覆写还给 feed, 否则 3D 与实机静默脱钩
  props.manager?.bindings?.clearHolds?.()
  if (import.meta.env.DEV && window.__ptlcCalib) delete window.__ptlcCalib
})
</script>

<template>
  <aside class="acp" @pointerdown.stop>
    <header class="acp__head">
      <span class="acp__title">轴标定</span>
      <span class="acp__badge">{{ live ? '实时' : '离线' }}</span>
      <span v-if="held.size" class="acp__badge acp__badge--held">接管 {{ held.size }} 轴</span>
      <span v-if="changed.length" class="acp__badge acp__badge--hot">改动 {{ changed.length }}</span>
      <label class="acp__step">
        步进
        <select v-model.number="stepMm" class="acp__step-select">
          <option v-for="option in STEP_OPTIONS" :key="option" :value="option">{{ option }}</option>
        </select>
        mm
      </label>
    </header>

    <div class="acp__body">
      <section
        v-for="row in riggedRows"
        :key="row.id"
        class="acp__axis"
        :class="{ 'acp__axis--held': row.held }"
      >
        <div class="acp__line">
          <span class="acp__id" :class="{ 'acp__id--set': row.changed }">{{ row.id }}</span>
          <span class="acp__label" :title="row.label">{{ row.label }}</span>
          <em v-if="row.outOfRange" class="acp__tag acp__tag--bad" title="实机反馈落在 range_mm 之外, 模型被钳在边界上">
            越界 clamp
          </em>
          <button
            class="acp__revert"
            :disabled="!row.changed"
            title="还原此轴到进入页面时的值"
            @click="onRevert(row.id)"
          >
            ↺
          </button>
        </div>

        <div class="acp__line acp__line--vals">
          <span class="acp__val">
            实时 <b :class="{ 'acp__stale': row.stale }">{{ formatMm(row.liveMm) }}</b> mm
            <i v-if="row.stale" class="acp__stale">stale</i>
          </span>
          <span class="acp__val">已应用 <b>{{ formatMm(row.appliedMm) }}</b> mm</span>
        </div>

        <template v-if="row.rigged">
          <!-- 标定闭环: 接管 → jog 对齐 → 匹配 -->
          <div v-if="live" class="acp__line acp__line--calib">
            <button
              class="acp__mini acp__mini--hold"
              :class="{ 'acp__mini--holding': row.held }"
              :title="row.held ? '释放: 实时数据重新接管该轴' : '接管: 挂起实时覆写, 手动把虚拟拖到与实机重合'"
              @click="toggleHold(row.id)"
            >
              {{ row.held ? '⏸ 已接管' : '接管' }}
            </button>
            <button
              class="acp__mini acp__mini--match"
              :disabled="!row.canMatch"
              :title="row.canMatch
                ? '虚拟已与实机目视重合时点它: zero_new = zero_old + (实时R − 已应用P)'
                : '匹配需要: 已接管 + 实时反馈可用(非 stale)'"
              @click="onMatch(row)"
            >
              匹配零点
            </button>
          </div>

          <div class="acp__line">
            <input
              type="range"
              class="acp__jog"
              :min="row.vals.rangeMm[0]"
              :max="row.vals.rangeMm[1]"
              step="1"
              :value="row.appliedMm ?? row.vals.zeroOffsetMm"
              :disabled="row.jogDisabled"
              :title="row.jogDisabled ? '实时数据接管中 —— 点「接管」后才可手动 jog' : '直接驱动该轴(mm); 接管中可越界试探'"
              @input="onJog(row.id, $event.target.value)"
            />
          </div>

          <!-- 零点与方向 / range 分两行: 挤在一行需要 ~420px, 320 栏里会折断 -->
          <div class="acp__line acp__line--ctrl">
            <span class="acp__key">零点</span>
            <button class="acp__mini" title="零点减一个步进" @click="onZeroStep(row.id, -1)">−</button>
            <input
              type="number"
              class="acp__num-input"
              :value="row.vals.zeroOffsetMm"
              @change="onZeroSet(row.id, $event.target.value)"
            />
            <button class="acp__mini" title="零点加一个步进" @click="onZeroStep(row.id, 1)">＋</button>
            <span class="acp__key acp__key--gap">方向</span>
            <button
              class="acp__mini acp__mini--sign"
              :disabled="row.held"
              :title="row.held ? '接管中锁定 sign(匹配公式以 sign 不变为前提)' : '翻转伺服正方向与模型轴向的符号'"
              @click="onFlipSign(row.id)"
            >
              {{ row.vals.sign > 0 ? '+1' : '−1' }}
            </button>
          </div>

          <div class="acp__line acp__line--ctrl">
            <span class="acp__key">range</span>
            <input
              type="number"
              class="acp__num-input"
              :value="row.vals.rangeMm[0]"
              @change="onRangeSet(row.id, 0, $event.target.value)"
            />
            <span class="acp__key">~</span>
            <input
              type="number"
              class="acp__num-input"
              :value="row.vals.rangeMm[1]"
              @change="onRangeSet(row.id, 1, $event.target.value)"
            />
            <span class="acp__key">mm</span>
          </div>
        </template>
      </section>

      <!-- 未装配的轴: 没有任何可操作控件, 默认收起, 免得把可标定的轴挤出视野 -->
      <section v-if="unriggedRows.length" class="acp__unrigged">
        <button
          type="button"
          class="acp__fold"
          :title="'rig_map 中 rigged:false — 到动作界面选该轴, 去装配台指认滑块成员并重跑'"
          @click="showUnrigged = !showUnrigged"
        >
          {{ showUnrigged ? '▾' : '▸' }} 未装配 {{ unriggedRows.length }} 根（不可标定）
        </button>
        <ul v-if="showUnrigged" class="acp__unriggedList">
          <li v-for="row in unriggedRows" :key="row.id">
            <span class="acp__id">{{ row.id }}</span>
            <span class="acp__label" :title="row.label">{{ row.label }}</span>
            <em class="acp__tag acp__tag--dim">data-only</em>
          </li>
        </ul>
      </section>
    </div>

    <footer class="acp__foot">
      <!-- 未写回警示: 之前只有一行灰色小字, 太容易被当成说明文字略过, 而代价是
           "标完就走"整批改动静默丢失 —— 页面看不出任何异样 -->
      <p v-if="changed.length" class="acp__warn">
        <b>{{ changed.length }} 根轴已改但未写回</b> —— 仅存在于本页内存,
        流程演示与刷新后都不会生效。
      </p>
      <p class="acp__hint">
        {{ writeMsg || (authoringAvailable
          ? '「写回」直落 rig_map.yaml 并秒级重跑 manifest, 完成后即时生效.'
          : '生产构建无写盘能力: 用「导出」拿 YAML 片段人工回填 rig_map.yaml.') }}
      </p>
      <div class="acp__footBtns">
        <button class="acp__btn" :disabled="!changed.length" @click="onExport">
          {{ copied ? '已复制 ✓' : '导出' }}
        </button>
        <button
          v-if="authoringAvailable"
          class="acp__btn acp__btn--primary"
          :disabled="!changed.length || writing"
          @click="onWriteBack"
        >
          {{ writing ? '写回中…' : '写回 rig_map' }}
        </button>
      </div>
    </footer>
  </aside>
</template>

<style scoped>
/* 左栏里的流式块(320 px). 曾是右上角 420 px 浮窗, 与另两个子页的栏位不同侧、
 * 不同宽, 且 z-index:12 会盖住居中的 ViewToolbar. 滚动交给左栏, 这里不再自持. */
.acp {
  display: flex;
  flex: none;
  flex-direction: column;
  width: 100%;
  min-width: 0;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.acp__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 6px;
  border-bottom: 1px solid var(--hair);
}

.acp__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
}

.acp__badge {
  padding: 1px 6px;
  font-size: 10px;
  color: var(--text-dim);
  border: 1px solid var(--hair);
  border-radius: 999px;
}

.acp__badge--hot {
  color: var(--accent);
  border-color: var(--accent);
}

.acp__badge--held {
  color: #d95757;
  border-color: #d95757;
}

.acp__step {
  display: flex;
  gap: 4px;
  align-items: center;
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
}

.acp__step-select {
  font-size: 10px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

/* 滚动交给左栏(.mw__left 自带 overflow: hidden auto): 面板内再套一层滚动会出现
   双滚动条, 且轴多时外层永远滚不动 */
.acp__body {
  padding: 4px 10px;
}

.acp__axis {
  padding: 6px 0;
}

.acp__axis + .acp__axis {
  border-top: 1px solid var(--hair);
}

.acp__axis--held {
  background: linear-gradient(90deg, rgb(217 87 87 / 0.07), transparent);
}

.acp__line {
  display: flex;
  gap: 6px;
  align-items: center;
  min-height: 20px;
  font-size: 11px;
}

.acp__line--calib {
  gap: 8px;
}

.acp__id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  color: var(--text-bright);
}

.acp__id--set {
  color: var(--accent);
  font-weight: 600;
}

.acp__label {
  overflow: hidden;
  color: var(--text-mid);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.acp__tag {
  padding: 0 5px;
  font-size: 9px;
  font-style: normal;
  border: 1px solid var(--hair);
  border-radius: 999px;
}

.acp__tag--dim {
  color: var(--text-dim);
}

.acp__tag--bad {
  color: #d95757;
  border-color: #d95757;
}

.acp__revert {
  margin-left: auto;
  padding: 0 2px;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
  background: none;
  border: none;
}

.acp__revert:disabled {
  cursor: default;
  opacity: 0.25;
}

.acp__line--vals {
  gap: 14px;
  color: var(--text-dim);
}

.acp__val b {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  font-weight: 500;
  color: var(--text-mid);
}

.acp__stale {
  font-style: normal;
  color: #d9a441;
}

.acp__jog {
  flex: 1;
  width: 100%;
  accent-color: var(--accent);
}

.acp__jog:disabled {
  opacity: 0.5;
}

.acp__line--ctrl {
  flex-wrap: wrap;
}

.acp__key {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

/* 「方向」与前面的零点组拉开一档, 免得两组控件糊成一片 */
.acp__key--gap {
  margin-left: 8px;
}

.acp__mini {
  min-width: 20px;
  padding: 1px 4px;
  font-size: 11px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.acp__mini:disabled {
  cursor: default;
  opacity: 0.4;
}

.acp__mini--sign {
  min-width: 30px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.acp__mini--hold {
  min-width: 56px;
}

.acp__mini--holding {
  color: #fff;
  background: #d95757;
  border-color: #d95757;
}

.acp__mini--match {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

/* 数字框跟着栏宽伸缩(不再写死 64/52 px): 320 栏里写死宽度会把整行挤到折断 */
.acp__num-input {
  flex: 1;
  min-width: 0;
  padding: 1px 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  color: var(--text-mid);
  background: var(--well, var(--control));
  border: 1px solid var(--hair);
  border-radius: 4px;
}

/* 未装配轴折叠区 */
.acp__unrigged {
  padding-top: 6px;
  border-top: 1px solid var(--hair);
}

.acp__fold {
  width: 100%;
  padding: 3px 0;
  font: inherit;
  font-size: 11px;
  color: var(--text-dim);
  text-align: left;
  cursor: pointer;
  background: none;
  border: none;
}

.acp__unriggedList {
  margin: 2px 0 0;
  padding: 0;
  list-style: none;
}

.acp__unriggedList li {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 2px 0;
  font-size: 11px;
  opacity: 0.55;
}

.acp__foot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px 10px;
  border-top: 1px solid var(--hair);
}

.acp__warn {
  margin: 0;
  padding: 6px 8px;
  font-size: 10px;
  line-height: 1.6;
  color: var(--warn);
  background: var(--warn-soft);
  border-radius: 6px;
}

.acp__hint {
  margin: 0;
  font-size: 9px;
  line-height: 1.5;
  color: var(--text-dim);
}

.acp__footBtns {
  display: flex;
  gap: 8px;
}

.acp__btn {
  flex: 1;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.acp__btn--primary {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

.acp__btn:disabled {
  cursor: default;
  opacity: 0.5;
}
</style>
