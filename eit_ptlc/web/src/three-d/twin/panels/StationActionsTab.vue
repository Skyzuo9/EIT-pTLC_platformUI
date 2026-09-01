<script>
/**
 * 工程师区解锁集(danger-ack 过一次即记住) —— **模块级**, 不在 setup 里.
 *
 * 宿主按工位 :key 重挂本组件(切工位状态才会归零), 而 <script setup> 每次实例化都重跑,
 * 放那里会让每次切工位都丢解锁、danger-ack 反复弹 —— 确认疲劳正是当初
 * "每工位每页面会话一次"要防的。模块级的生命周期 = 页面会话, 语义不变。
 * 只在 toggleEngineer 的命令式流程里读写, 不进模板, 无需响应式。
 */
const engineerUnlocked = new Set()
</script>

<script setup>
/**
 * 功能: 工位「操作」页 —— 常用运维动作直接给, 工程师动作折进抽屉.
 *
 * 一页两层:
 *   运维区    该工位的原子动作(白名单, 见 twin/actionAudience.js) + 「模块状态」区
 *             (气缸/泵/轴的实时态与手动开关; 手动控制会话按钮在该区标题行右侧)
 *   工程师区  其余全部, 折叠, 首次展开要过一次 danger-ack 确认
 *
 * 每个动作**原有的三道门一道不少**: 模式门(非 DEBUG 置灰, 后端 403 双保险) /
 * 二次确认(ActionQuickForm 内联) / 结果完整回显。本页只改"先看见哪些", 不改"能不能发".
 *
 * 手动控制会话是**整页一份**(useManualSession, 由 TwinView 持有并注入), 切工位不会
 * 掉一次 PLC 闩锁再重拿.
 */
import { computed, onBeforeUnmount, ref } from 'vue'

import { confirmAction } from '../../../composables/confirmService.js'
import { buildGroups, classifyMechanism } from '../../../utils/manualGroups.js'
import { ENGINEER_WARNING, splitStationActions, supersededHint } from '../actionAudience.js'
import { mechanismsOfStation, realtimeAxesOfStation } from '../manifest.js'
import { homeAxis, moveAxis, resetAxis, setCylinder, stopAxis } from '../manualApi.js'
import ActionQuickForm from './ActionQuickForm.vue'
import ManualAxisRow from './manual/ManualAxisRow.vue'
import ManualMechanismRow from './manual/ManualMechanismRow.vue'
import StationRobotPanel from './StationRobotPanel.vue'

const props = defineProps({
  /** manifest 内容 */
  manifest: { type: Object, required: true },
  /** 工位定义 */
  station: { type: Object, default: null },
  /** 动作目录(全量; 本页按 station.actions 过滤) */
  actionCatalog: { type: Array, default: () => [] },
  /** TwinFeed.realtimeStatus 载荷(轴/机构实时值; robot.joint/pose 是 20 Hz 的) */
  realtime: { type: Object, default: () => ({}) },
  /** 该工位遥测节点的 1 Hz 快照(机械臂面板要 tool_state / speed_factor) */
  snapshot: { type: Object, default: null },
  /** 该工位的健康度(机械臂断联横幅要它) */
  health: { type: String, default: '' },
  /** useManualSession 的返回值(整页一份) */
  manual: { type: Object, required: true },
  /** SceneManager(点轴时描边高亮, 操作与三维对上眼) */
  manager: { type: Object, default: null },
})

/** 展开中的动作 */
const openAction = ref(null)
/** 工程师区是否展开 */
const showEngineer = ref(false)
const message = ref('')

const stationId = computed(() => props.station?.id || '')

/** 该工位可执行的动作(按 manifest 声明的动作清单过滤目录) */
const stationActions = computed(() => {
  const names = new Set(props.station?.actions || [])
  if (!names.size) return []
  return props.actionCatalog.filter((action) => names.has(action.name))
})

const split = computed(() => splitStationActions(stationActions.value))

/**
 * 功能: 取一个单点件在三维里的节点.
 *
 * realtime.axes[] / realtime.mechanisms[] 里**没有任何节点路径**, 只有一个 rigged 布尔;
 * 真正的路径分散在 manifest 的 axes[] / actuators[] / linkages[] 三张表里, 靠同一个 id 关联。
 * 绑定层已经把它们解成 Object3D 了, 所以这里直接问绑定层而不是再解析一遍路径。
 * @param {'axis'|'mechanism'} kind 件的类别
 * @param {string} id 件 id
 * @returns {object[]} 节点数组(联动机构是多个; 没有几何时为空数组)
 */
function nodesOfPart(kind, id) {
  const machine = props.manager?.bindings?.machine
  if (!machine) return []
  if (kind === 'axis') {
    const node = machine.axes?.get(id)?.node
    return node ? [node] : []
  }
  const actuator = machine.actuators?.get(id)?.node
  if (actuator) return [actuator]
  const members = machine.linkages?.get(id)?.members || []
  return members.map((member) => member.node).filter(Boolean)
}

/** 当前聚焦的零件 id(行高亮; 低画质档没有描边链时这是唯一的反馈) */
const focusedPart = ref('')

/** 本工位的单点控制轴, ⨝ 实时采样 */
const axisRows = computed(() => {
  const live = new Map((props.realtime?.axes?.items || []).map((item) => [item.id, item]))
  return realtimeAxesOfStation(props.manifest, stationId.value).map((axis) => {
    const sample = live.get(axis.id)
    return {
      id: axis.id,
      label: axis.label || axis.id,
      rigged: Boolean(axis.rigged),
      focusable: nodesOfPart('axis', axis.id).length > 0,
      position: Number.isFinite(Number(sample?.position)) ? Number(sample.position) : null,
      stale: Boolean(sample?.stale),
      jogging: props.manual.sessionState.value?.jogging?.axisId === axis.id,
    }
  })
})

/** 本工位的执行器, ⨝ 机构账本 */
const mechanismRows = computed(() => {
  const live = new Map((props.realtime?.mechanisms?.items || []).map((item) => [item.id, item]))
  return mechanismsOfStation(props.manifest, stationId.value).map((mech) => {
    const sample = live.get(mech.id)
    return {
      id: mech.id,
      label: mech.label || mech.id,
      kind: mech.kind,
      focusable: nodesOfPart('mechanism', mech.id).length > 0,
      effective: sample?.effective ?? null,
      commanded: sample?.commanded ?? null,
      stale: Boolean(sample?.stale),
    }
  })
})

/**
 * 机械臂工位走专用面板.
 *
 * 通用的轴/气缸两段对 ROBOT 是空的与坏的: manifest.realtime.axes 里没有 robot 的轴,
 * 而它那 4 个执行器(夹爪/吸盘/翻转)在 manual_points.yaml 里根本不存在, 走
 * /api/manual/cylinder 必然 404。机械臂真正的写路径是 /api/robot/* 与 robot.tool_action。
 */
const isRobot = computed(() => stationId.value === 'ROBOT')

/**
 * 该工位有没有可写的手动控制通道(决定要不要渲染「模块状态」区与会话按钮).
 *
 * 机械臂不走 /api/manual/*, 给它显示"进入手动控制"是误导 —— 进了也不影响它。
 */
const hasManualChannel = computed(() =>
  !isRobot.value && (axisRows.value.length > 0 || mechanismRows.value.length > 0))

/**
 * 「模块状态」运维档执行器 = 气缸 + 泵.
 * 气缸有双端磁性开关的**真到位反馈**, 开合结果看得见;
 * 泵(大真空泵)按用户要求提供人工开关 —— 它只写手动线圈、不碰资源票, 无到位反馈,
 * 行内状态是下令回显, hint 里如实交代副作用。
 * 阀/电机只有下令没有反馈且无人工开关诉求, 仍归工程师带着仪表操作。
 * 直接复用 utils/manualGroups.js 的 classifyMechanism, 不新造判据。
 */
const opsCylinders = computed(() =>
  mechanismRows.value.filter((row) => classifyMechanism(row) === 'cylinder'))
const opsPumps = computed(() => mechanismRows.value
  .filter((row) => classifyMechanism(row) === 'pump')
  .map((row) => ({
    ...row,
    hint: '手动线圈开关, 不改流程的资源票; 手动接管期间在跑流程的排液/抽吸将失去真空源',
  })))

/** 工程师档执行器: 其余全部, 仍按类型分组(只看阀是高频诉求) */
const engineerMechanismGroups = computed(() => {
  const rest = mechanismRows.value.filter(
    (row) => !['cylinder', 'pump'].includes(classifyMechanism(row)))
  return buildGroups(rest, classifyMechanism)
})

const jogDirection = computed(() => props.manual.sessionState.value?.jogging?.direction || null)
const canWrite = computed(() => props.manual.canWrite.value)
/** 单点会话是否已建立 —— 未建立时轴/机构两段整体只读(控件不渲染, 只留读数) */
const sessionActive = computed(() => props.manual.active.value)

/**
 * 功能: 展开工程师区 —— 首次要过一次 danger-ack 确认.
 *
 * 每工位每页面会话一次, 而不是每个动作一次: 逐个动作确认会造出确认疲劳,
 * 点到第三个人就开始盲点"确定"了, 那时确认框已经不起任何作用.
 * @returns {Promise<void>} 完成
 */
async function toggleEngineer() {
  if (showEngineer.value) {
    showEngineer.value = false
    return
  }
  if (!engineerUnlocked.has(stationId.value)) {
    const ok = await confirmAction({
      level: 'danger-ack',
      title: `${props.station?.label || stationId.value} · 工程师操作`,
      message: [ENGINEER_WARNING],
      ackText: '我已在工程师指导下操作',
      confirmText: '展开',
    })
    if (!ok) return
    engineerUnlocked.add(stationId.value)
  }
  showEngineer.value = true
}

/**
 * 功能: 点名字 = 相机推近该零件 + 描边(让"我在操作哪一块"在三维里看得见).
 *
 * 描边走 manager.outline 的 part 层: 它压过工位描边、被物料描边压过, 撤掉时自动露出
 * 下面那层, 不会把别人的描边抹掉。行高亮是**兜底反馈** —— 低画质档没有描边链
 * (QUALITY_TIERS.low.outline === false), 而卡顿会自动降档, 描边不是有保证的通道。
 * @param {'axis'|'mechanism'} kind 件的类别
 * @param {string} id 件 id
 * @returns {void}
 */
function focusPart(kind, id) {
  const nodes = nodesOfPart(kind, id)
  if (!nodes.length) return
  const meshes = []
  for (const node of nodes) {
    node.traverse((child) => {
      if (child.isMesh) meshes.push(child)
    })
  }
  props.manager?.outline?.set('part', meshes)
  props.manager?.focusObjects?.(nodes)
  focusedPart.value = id
}

/**
 * 功能: 绝对定位.
 * @param {string} axisId 轴 id
 * @param {string} raw 目标位置文本(mm)
 * @returns {Promise<void>} 完成
 */
async function onMove(axisId, raw) {
  const target = Number(raw)
  if (!Number.isFinite(target)) {
    message.value = '目标位置必须是数字(mm)'
    return
  }
  try {
    await moveAxis(axisId, { mode: 'abs', target })
    message.value = `${axisId} → ${target} mm 已下发(速度按点表限幅)`
  } catch (err) {
    message.value = `定位失败: ${err.message}`
  }
}

/**
 * 功能: 单轴收敛类操作(回零 / 停 / 清错).
 * @param {string} axisId 轴 id
 * @param {'home'|'stop'|'reset'} op 操作
 * @returns {Promise<void>} 完成
 */
async function onAxisOp(axisId, op) {
  try {
    if (op === 'home') await homeAxis(axisId)
    else if (op === 'stop') await stopAxis(axisId)
    else await resetAxis(axisId)
    message.value = `${axisId} ${{ home: '回零', stop: '停止', reset: '清错' }[op]}已下发`
  } catch (err) {
    message.value = `操作失败: ${err.message}`
  }
}

/**
 * 功能: 执行器开合.
 * @param {object} row 机构行
 * @param {boolean} on 目标态
 * @returns {Promise<void>} 完成
 */
async function onSetMechanism(row, on) {
  if (!canWrite.value) return
  try {
    await setCylinder(row.id, on)
    message.value = `${row.label} → ${on ? '开' : '关'}（看三维里是否跟随）`
  } catch (err) {
    message.value = `操作失败: ${err.message}`
  }
}

onBeforeUnmount(() => {
  // 本页可能给某个零件描过边; 离开时只撤自己那一层, 工位描边照旧留着
  props.manager?.outline?.clear('part')
})
</script>

<template>
  <div v-if="station" class="sat">
    <StationRobotPanel
      v-if="isRobot"
      :snapshot="snapshot"
      :realtime="realtime"
      :health="health"
      :control-mode="manual.mode.value"
    />

    <!-- ── 运维区 ──────────────────────────────────────────────── -->
    <section v-if="split.ops.length" class="dock-section">
      <h3 class="dock-h3">常用操作<span class="dock-h3__sub">日常运维与中断后恢复</span></h3>
      <div class="sat__actions">
        <button
          v-for="action in split.ops"
          :key="action.name"
          type="button"
          class="sat__action"
          :class="{ 'is-open': openAction?.name === action.name }"
          :title="action.hint || action.desc || action.name"
          @click="openAction = openAction?.name === action.name ? null : action"
        >
          <span class="sat__action-label">{{ action.label || action.name }}</span>
          <span class="sat__action-name">{{ action.name }}</span>
        </button>
      </div>
      <ActionQuickForm
        v-if="openAction"
        :action="openAction"
        :control-mode="manual.mode.value"
        class="sat__form"
        @close="openAction = null"
      />
    </section>

    <!-- ── 模块状态: 气缸/泵/轴的实时态与手动开关。未进入手动控制时全部只读
         (只留名字+读数, 用户定案"控件收进手动门后"); 点名字聚焦三维不受影响 ——
         那是观察, 不是控制。会话按钮就在标题行右侧, 整页共用一份会话 -->
    <section v-if="hasManualChannel" class="dock-section">
      <div class="sat__module-head">
        <h3 class="dock-h3">
          模块状态
          <span class="dock-h3__sub">{{ sessionActive ? '手动控制中 · 心跳保持' : '进入手动控制后可操作' }}</span>
        </h3>
        <button
          type="button"
          class="dock-btn sat__manual-btn"
          :class="{ 'dock-btn--primary': !manual.active.value }"
          :disabled="!manual.modeAllowed.value && !manual.active.value"
          :title="manual.modeAllowed.value || manual.active.value ? '' : '仅调试模式可进入(后端 403 双保险)'"
          @click="manual.toggle()"
        >{{ manual.active.value ? '退出手动'
          : (manual.sessionState.value?.state === 'entering' ? '进入中…' : '手动控制') }}</button>
      </div>
      <p v-if="manual.gateReason.value" class="sat__gate">{{ manual.gateReason.value }}</p>
      <p v-else-if="manual.sessionState.value?.reason" class="sat__gate">
        {{ manual.sessionState.value.reason }}
      </p>

      <template v-if="opsCylinders.length">
        <p class="sat__group">
          气缸（{{ opsCylinders.length }}）<span class="dock-h3__sub">有到位反馈</span>
        </p>
        <ManualMechanismRow
          v-for="row in opsCylinders"
          :key="row.id"
          :row="row"
          :can-write="canWrite"
          :readonly-row="!sessionActive"
          :focused="focusedPart === row.id"
          @set="onSetMechanism"
          @focus="focusPart('mechanism', $event)"
        />
      </template>

      <template v-if="opsPumps.length">
        <p class="sat__group">
          泵（{{ opsPumps.length }}）<span class="dock-h3__sub">手动线圈 · 无反馈, 显示下令回显</span>
        </p>
        <ManualMechanismRow
          v-for="row in opsPumps"
          :key="row.id"
          :row="row"
          :can-write="canWrite"
          :readonly-row="!sessionActive"
          :focused="focusedPart === row.id"
          @set="onSetMechanism"
          @focus="focusPart('mechanism', $event)"
        />
      </template>

      <template v-if="axisRows.length">
        <p class="sat__group">
          轴（{{ axisRows.length }}）<span class="dock-h3__sub">按住 jog 即动 · 松手即停</span>
        </p>
        <ManualAxisRow
          v-for="row in axisRows"
          :key="row.id"
          :row="row"
          :can-write="canWrite"
          :readonly-row="!sessionActive"
          :jog-direction="jogDirection"
          :focused="focusedPart === row.id"
          @jog-press="manual.jogStart"
          @jog-release="manual.jogStop"
          @move="onMove"
          @op="onAxisOp"
          @focus="focusPart('axis', $event)"
        />
      </template>
    </section>

    <!-- ── 工程师区 ────────────────────────────────────────────── -->
    <section
      v-if="split.engineer.length || engineerMechanismGroups.length"
      class="dock-section"
    >
      <button type="button" class="sat__engineer-toggle" @click="toggleEngineer">
        <span>{{ showEngineer ? '▾' : '▸' }} 工程师操作</span>
        <span class="dock-h3__sub">
          {{ split.engineer.length }} 个动作 ·
          {{ engineerMechanismGroups.reduce((n, g) => n + g.items.length, 0) }} 个执行器
        </span>
      </button>

      <template v-if="showEngineer">
        <p class="dock-banner dock-banner--warn">
          <span class="dock-banner__title">请在工程师指导下使用</span>
          <span>{{ ENGINEER_WARNING }}</span>
        </p>

        <div v-if="split.engineer.length" class="sat__actions">
          <button
            v-for="action in split.engineer"
            :key="action.name"
            type="button"
            class="sat__action"
            :class="{ 'is-open': openAction?.name === action.name }"
            :title="action.desc || action.name"
            @click="openAction = openAction?.name === action.name ? null : action"
          >
            <span class="sat__action-label">{{ action.label || action.name }}</span>
            <span class="sat__action-name">{{ action.name }}</span>
            <!-- 从常用区降下来的动作要说清谁顶替了它 —— 操作员在上面找不到熟悉的按钮时,
                 答案就在原地, 而不是让人以为这个功能被删了 -->
            <span v-if="supersededHint(action.name)" class="sat__superseded">
              已由 {{ supersededHint(action.name) }} 替代
            </span>
          </button>
        </div>

        <template v-for="group in engineerMechanismGroups" :key="group.key">
          <p class="sat__group">
            {{ group.title }}<span class="dock-h3__sub">{{ group.items.length }}</span>
            <!-- 机械臂那 4 个执行器只是显示态: manual_points.yaml 里没有它们,
                 点开/关必然 404。写路径在上面的「末端工具」语义键。 -->
            <span v-if="isRobot" class="dock-h3__sub">只读显示态 · 写路径见上面的末端工具</span>
          </p>
          <ManualMechanismRow
            v-for="row in group.items"
            :key="row.id"
            :row="row"
            :can-write="canWrite"
            :readonly-row="isRobot || !sessionActive"
            :show-kind="group.key === 'other'"
            :focused="focusedPart === row.id"
            @set="onSetMechanism"
            @focus="focusPart('mechanism', $event)"
          />
        </template>
      </template>
    </section>

    <p v-if="!split.ops.length && !split.engineer.length && !axisRows.length && !mechanismRows.length"
       class="dock-empty">该工位没有可执行的动作或可手动操作的机构。</p>

    <p v-if="message" class="sat__msg">{{ message }}</p>
  </div>
</template>

<style scoped>
.sat {
  display: flex;
  flex-direction: column;
}

.sat__actions {
  display: grid;
  gap: 3px;
}

.sat__action {
  display: flex;
  flex-direction: column;
  gap: 1px;
  align-items: flex-start;
  padding: 5px 8px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  background: var(--control);
  border: 1px solid transparent;
  border-radius: 5px;
}

.sat__action:hover {
  background: var(--control-hover);
}

.sat__action.is-open {
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.sat__action-label {
  font-size: 12px;
  color: var(--text-bright);
}

.sat__action-name {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 10px;
  color: var(--text-dim);
}

.sat__superseded {
  margin-top: 2px;
  font-size: 10px;
  line-height: 1.45;
  color: var(--text-dim);
  text-align: left;
  white-space: normal;
}

.sat__form {
  margin-top: 6px;
}

/* 模块状态标题行: h3 与「手动控制」按钮同行, 按钮靠右 */
.sat__module-head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}

.sat__module-head .dock-h3 {
  flex: 1;
  min-width: 0;
  margin: 0;
}

.sat__manual-btn {
  flex: none;
}

.sat__gate {
  margin: 2px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}

.sat__engineer-toggle {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 5px 8px;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.sat__engineer-toggle:hover {
  background: var(--control-hover);
}

.sat__group {
  margin: 8px 0 2px;
  font-size: 11px;
  color: var(--text-dim);
}

.sat__msg {
  margin: 0;
  padding: 6px 12px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}
</style>
