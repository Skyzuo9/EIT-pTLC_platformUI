<script setup>
/**
 * 功能: 运动模式子页 —— 定"哪些东西会动、怎么动、动多远".
 *
 * 原「运动语义」页签, 改名后职责收敛为三件事:
 *   1. 运动模组: manifest 投影成条目表(motionSemantics), 一键三色着色(MotionPaint),
 *      未绑定几何的条目可进指认模式点选滑车成员;
 *   2. 运动方式: 直线/旋转、运动方向(六个世界系候选)、执行器与联动组的运动学参数;
 *   3. 运动范围: 行程区间, 滑杆/±步进/视口内 1-DOF 约束拖拽三种方式核对.
 *
 * 一切驱动都经 MachineStateDriver 这一唯一写入层; 参数改动先在内存里预览(spec 与
 * 驱动层是同对象引用), 攒够了由 RigWriteBar 统一写回 rig_map.
 */
import { computed, inject, ref } from 'vue'

import { outputRangesForLift, solveLift } from '../linkageKinematics.js'
import MovableInspector from '../MovableInspector.vue'
import RigParamsCard from '../RigParamsCard.vue'
import RigWriteBar from '../RigWriteBar.vue'
import { patchRigMapAxisDirection, readRigMapLiquidEnabled } from '../rigPatch.js'
import { patchRigMap, readRigMap } from '../rigWriter.js'
import SemanticsPanel from '../SemanticsPanel.vue'
import * as api from '../../workbench/authoringApi.js'

const ctx = inject('motionWorkbench')
const { manager, stack, assignMode, valueTick, authoringAvailable, axisDirSaved, notify, bumpValue, state } = ctx

/** 语义着色开关 */
const paintOn = ref(false)
/** 当前选中的语义条目 */
const selectedEntry = ref(null)
/** 关节调试面板 */
const jointPanel = ref(false)
const jointDeg = ref([0, 0, 0, 0, 0, 0])
/** 未写回 rig_map 的运动参数改动 */
const rigDirty = ref({ actuators: {}, linkages: {} })
/** 液面开关: 当前值 + 待写值(null = 未改) */
const liquidEnabled = ref(false)
const liquidPending = ref(null)

const semantics = computed(() => stack.semantics.value)

/** 选中执行器/联动的 spec 现值(RigParamsCard 的数据源, 与驱动层同对象) */
const paramsLive = computed(() => {
  valueTick.value
  const entry = selectedEntry.value
  const machine = stack.rig.value
  if (!entry || !machine) return {}
  if (entry.kind === 'actuator') {
    const spec = machine.actuators.get(entry.params.actuatorId)?.spec
    return spec
      ? { sign: spec.sign, outputRange: spec.outputRange, transitionS: spec.transitionS, motion: spec.motion }
      : {}
  }
  if (entry.kind === 'linkage') {
    const link = machine.linkages.get(entry.params.linkageId)
    return link
      ? {
          outputRange: link.members[0]?.spec.outputRange,
          transitionS: link.spec.transitionS,
          motion: 'translate',
          // 首成员的真实 motion: 联动组的行程单位按它标(rotate 是度不是 mm)
          memberMotion: link.members[0]?.spec.motion,
          // 带耦合约束的机构(展缸盖)只暴露主参数, 见 linkageKinematics.js
          kinematics: link.spec.kinematics,
        }
      : {}
  }
  return {}
})

/** 选中条目是否有未写回的参数改动 */
const paramsDirty = computed(() => {
  const entry = selectedEntry.value
  if (!entry) return false
  if (entry.kind === 'actuator') return Boolean(rigDirty.value.actuators[entry.params.actuatorId])
  if (entry.kind === 'linkage') return Boolean(rigDirty.value.linkages[entry.params.linkageId])
  return false
})

/** 选中条目的当前值(轴=mm, 关节=deg, 执行器/联动=0..1) */
const inspectorCurrent = computed(() => {
  valueTick.value
  const entry = selectedEntry.value
  const machine = stack.rig.value
  if (!entry || !machine) return null
  if (entry.kind === 'axis') {
    const value = machine.axes.get(entry.params.axisId)?.valueMm
    return Number.isFinite(value) ? value : null
  }
  if (entry.kind === 'joint') return jointDeg.value[entry.params.jointIndex] ?? 0
  if (entry.kind === 'actuator') {
    const value = machine.actuators.get(entry.params.actuatorId)?.value
    return Number.isFinite(value) ? value : 0
  }
  if (entry.kind === 'linkage') {
    const value = machine.linkages.get(entry.params.linkageId)?.value
    return Number.isFinite(value) ? value : 0
  }
  return null
})

/** 选中轴条目的现行轴向(驱动层 spec 为真源, 方向预览的改动立即反映) */
const inspectorAxisDir = computed(() => {
  valueTick.value
  const entry = selectedEntry.value
  if (!entry || entry.kind !== 'axis') return null
  const spec = stack.rig.value?.axes.get(entry.params.axisId)?.spec
  return spec ? [...(spec.axis || [1, 0, 0])] : null
})

/** 选中轴条目的现行符号 */
const inspectorAxisSign = computed(() => {
  valueTick.value
  const entry = selectedEntry.value
  if (!entry || entry.kind !== 'axis') return 1
  return Number(stack.rig.value?.axes.get(entry.params.axisId)?.spec?.sign ?? 1)
})

/** 选中轴的运动方向相对已固化值是否有未写回的改动 */
const inspectorDirDirty = computed(() => {
  valueTick.value
  const entry = selectedEntry.value
  if (!entry || entry.kind !== 'axis') return false
  const axisId = entry.params.axisId
  const spec = stack.rig.value?.axes.get(axisId)?.spec
  const saved = axisDirSaved.value
  if (!spec || !saved.has(axisId)) return false
  const now = JSON.stringify({ axis: spec.axis || [1, 0, 0], sign: Number(spec.sign ?? 1) })
  return saved.get(axisId) !== now
})

/**
 * 功能: 选中一个语义条目 —— 描边强调 + 取景.
 * @param {object} entry 条目
 * @returns {void}
 */
function selectEntry(entry) {
  selectedEntry.value = entry
  const meshes = stack.paint.value?.entryMeshes(entry) || []
  manager.value?.effects?.setSelected(meshes)
  if (meshes.length) stack.tools.value?.frameObjects(meshes)
  bumpValue()
}

/**
 * 功能: 手动调试前先暂停播放(播放器每帧覆写会跟手打架).
 * @returns {void}
 */
function pauseForManual() {
  if (ctx.transport.value.playing) stack.player.value?.toggle()
}

/**
 * 功能: 轴 mm 写入(调试卡滑杆/步进).
 * @param {string} axisId 轴 id
 * @param {number} mm 毫米
 * @returns {void}
 */
function onAxisMm(axisId, mm) {
  pauseForManual()
  stack.rig.value?.setAxisMm(axisId, mm)
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 关节滑杆 —— 自动暂停后直接驱动关节(编排/校准轴向用, 不写进片段).
 * @param {number} index 关节下标
 * @param {string|number} value 角度
 * @returns {void}
 */
function onJointSlider(index, value) {
  pauseForManual()
  jointDeg.value[index] = Number(value)
  stack.rig.value?.setJointsDeg(jointDeg.value)
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 关节全部回零.
 * @returns {void}
 */
function jointsHome() {
  jointDeg.value = [0, 0, 0, 0, 0, 0]
  stack.rig.value?.setJointsDeg(jointDeg.value)
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 运动方向预览 —— 直接改驱动层 spec/direction, 模型立即按新方向重新站位,
 * 滑杆/步进/视口拖拽全部即刻按新方向生效(拖拽每次按下现读 entry.direction).
 * @param {string} axisId 轴 id
 * @param {{axis: number[], sign: number}} next 新方向
 * @returns {void}
 */
function onAxisDir(axisId, next) {
  const entry = stack.rig.value?.axes.get(axisId)
  if (!entry || !Array.isArray(next?.axis)) return
  pauseForManual()
  entry.spec.axis = [...next.axis]
  entry.spec.sign = Number(next.sign) >= 0 ? 1 : -1
  entry.direction.set(next.axis[0], next.axis[1], next.axis[2]).normalize()
  const mm = Number.isFinite(entry.valueMm) ? entry.valueMm : Number(entry.spec.zeroOffsetMm || 0)
  stack.rig.value.setAxisMm(axisId, mm)
  manager.value?.invalidateShadows()
  bumpValue()
  notify('方向已预览: 拖拽/滑杆核对, 对了点「写回」固化')
}

/**
 * 功能: 把当前预览的运动方向写回 rig_map 并快速部署(仅 manifest 两步+deploy, 秒级).
 * @param {string} axisId 轴 id
 * @returns {Promise<void>}
 */
async function onAxisDirSave(axisId) {
  if (!authoringAvailable.value) return
  const entry = stack.rig.value?.axes.get(axisId)
  if (!entry) return
  const axis = entry.spec.axis || [1, 0, 0]
  const sign = Number(entry.spec.sign ?? 1)
  try {
    notify('写回 rig_map…')
    const result = await patchRigMap((text) => patchRigMapAxisDirection(text, axisId, axis, sign))
    if (state.disposed) return
    if (result.conflict === true) {
      notify('rig_map 在此期间被其它会话改过, 已重新读取 —— 请再点一次写回')
      return
    }
    notify('已写回, 正在快速部署 manifest…')
    await api.startRebuild(['manifest', 'manifest-cr5', 'deploy'])
    const status = await api.waitRebuild()
    if (state.disposed) return
    if (status?.error) throw new Error(status.error)
    axisDirSaved.value.set(axisId, JSON.stringify({ axis, sign: Number(sign) >= 0 ? 1 : -1 }))
    bumpValue()
    notify(`轴 ${axisId} 的运动方向已固化并部署`)
  } catch (err) {
    if (state.disposed) return
    notify(`方向写回失败: ${err?.message || err}`)
  }
}

/**
 * 功能: 执行器/联动 0..1 写入.
 * @param {object} entry 条目
 * @param {number} value 值
 * @returns {void}
 */
function onMotionValue(entry, value) {
  pauseForManual()
  if (entry.kind === 'actuator') stack.rig.value?.setActuator(entry.params.actuatorId, value)
  else if (entry.kind === 'linkage') stack.rig.value?.setLinkage(entry.params.linkageId, value)
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 工具锁紧/释放演示(机械臂-夹爪联动 = attach 换父).
 * @param {string} toolId 工具 id
 * @param {'lock'|'release'} action 动作
 * @returns {void}
 */
function onToolAction(toolId, action) {
  pauseForManual()
  const machine = stack.rig.value
  if (!machine) return
  const done = action === 'lock' ? machine.lockTool(toolId) : machine.releaseTool(toolId)
  notify(done
    ? `已${action === 'lock' ? '锁紧到法兰' : '释放回停靠位'}: ${toolId}`
    : `操作失败: ${toolId}(检查 manifest tools 声明)`)
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 运动参数编辑 —— 改 spec 现值(与驱动层同对象)立即预览, 记入待写回.
 * @param {object} entry 语义条目
 * @param {string} key 参数名(sign/outputRange/transitionS/liftMm)
 * @param {*} value 值
 * @returns {void}
 */
function onParamChange(entry, key, value) {
  const machine = stack.rig.value
  if (!machine) return
  if (entry.kind === 'actuator') {
    const id = entry.params.actuatorId
    const bound = machine.actuators.get(id)
    if (!bound) return
    bound.spec[key] = value
    machine.refreshMotionAxis('actuator', id)
    // 重放当前值让行程/方向改动立即可见
    if (Number.isFinite(bound.value)) machine.setActuator(id, bound.value)
    rigDirty.value.actuators[id] = { ...rigDirty.value.actuators[id], [key]: value }
  } else if (entry.kind === 'linkage') {
    const id = entry.params.linkageId
    const bound = machine.linkages.get(id)
    if (!bound) return
    if (key === 'transitionS') bound.spec.transitionS = value
    else if (key === 'liftMm') {
      // 耦合机构(展缸盖): 主参数解出各成员行程. 一刀切套同一个数会让盖与摆臂
      // 脱节(现象: 连接处错位) —— 这条路径正是为此存在的.
      const kin = bound.spec.kinematics
      let ranges
      try {
        ranges = outputRangesForLift(kin, value)
      } catch (err) {
        notify(`抬升越界: ${err.message}`)
        return
      }
      bound.members.forEach((member, index) => { member.spec.outputRange = ranges[index] })
      const solved = solveLift(kin, value)
      Object.assign(kin, {
        liftMm: Number(solved.liftMm.toFixed(2)),
        travelMm: Number(solved.travelMm.toFixed(2)),
        thetaDeg: Number(solved.thetaDeg.toFixed(2)),
      })
    } else if (key === 'outputRange') {
      if (bound.spec.kinematics) return // 耦合机构不接受逐成员改行程
      for (const member of bound.members) member.spec.outputRange = [...value]
    }
    machine.refreshMotionAxis('linkage', id)
    if (Number.isFinite(bound.value)) machine.setLinkage(id, bound.value)
    rigDirty.value.linkages[id] = { ...rigDirty.value.linkages[id], [key]: value }
  } else {
    return
  }
  rigDirty.value = { ...rigDirty.value }
  manager.value?.invalidateShadows()
  bumpValue()
}

/**
 * 功能: 写回完成后清空待写状态.
 * @returns {void}
 */
function onRigWritten() {
  rigDirty.value = { actuators: {}, linkages: {} }
  if (liquidPending.value !== null) {
    liquidEnabled.value = liquidPending.value
    liquidPending.value = null
  }
}

/**
 * 功能: 液体开关(写回后随全链重跑生效).
 * @param {boolean} on 是否启用
 * @returns {void}
 */
function toggleLiquid(on) {
  liquidPending.value = on === liquidEnabled.value ? null : on
}

/**
 * 功能: 语义着色开关 —— 换装是纯材质指针替换, drawCalls 不升.
 * @returns {void}
 */
function togglePaint() {
  paintOn.value = !paintOn.value
  const paint = stack.paint.value
  if (!paint) return
  if (paintOn.value) {
    const counts = paint.apply(semantics.value)
    notify(`语义着色: 可动 ${counts.movable} · 耗材 ${counts.consumable} · 静止 ${counts.static} 个网格`)
  } else {
    paint.restore()
  }
  manager.value?.invalidateShadows()
}

// 液面当前值: 生产构建读不到受管文件, 失败即静默(液体卡本来就只在授权可用时才渲染)
readRigMap()
  .then((text) => {
    if (state.disposed === false) liquidEnabled.value = readRigMapLiquidEnabled(text)
  })
  .catch(() => {
    // rig_map 读不到不致命, 液体卡显示未知态
  })
</script>

<template>
  <div>
    <aside class="mw__left mw__left--tall">
      <button
        type="button"
        :class="['mw__btn', 'mw__btn--wide', paintOn ? '' : 'mw__btn--ghost']"
        title="三色近白模: 可动=蓝 · 耗材=琥珀 · 静止=浅灰; 与列表色点同源"
        @click="togglePaint"
      >{{ paintOn ? '✓ 语义着色中' : '开启语义着色' }}</button>

      <SemanticsPanel
        :entries="semantics"
        :active-id="selectedEntry?.id || ''"
        @select="selectEntry"
      />

      <!-- 液体设定: 开关写回 rig_map, 全链重跑后 03 生成液面几何 -->
      <div v-if="authoringAvailable" class="mp__liquid">
        <label class="mp__liquidLabel">
          <input
            type="checkbox"
            :checked="liquidPending ?? liquidEnabled"
            @change="toggleLiquid($event.target.checked)"
          />
          展缸液面动画
        </label>
        <span class="mp__liquidHint">
          {{ liquidPending !== null ? '待写回(需全链重跑约1分钟)' : liquidEnabled ? '已启用' : '已停用' }}
        </span>
      </div>

      <RigWriteBar
        :available="authoringAvailable"
        :dirty="rigDirty"
        :liquid-pending="liquidPending"
        @written="onRigWritten"
      />
    </aside>

    <aside class="mw__right mw__right--tall">
      <section v-if="selectedEntry" class="mw__panel">
        <MovableInspector
          :entry="selectedEntry"
          :current="inspectorCurrent"
          :axis-dir="inspectorAxisDir"
          :axis-sign="inspectorAxisSign"
          :dir-dirty="inspectorDirDirty"
          :can-write="authoringAvailable"
          @axis-mm="onAxisMm"
          @joint-deg="onJointSlider"
          @motion-value="onMotionValue"
          @tool-action="onToolAction"
          @axis-dir="onAxisDir"
          @axis-dir-save="onAxisDirSave"
        />
        <!-- 轴条目: 页内指认/修改滑车成员(临时切换原始模型, 全零件粒度) -->
        <button
          v-if="selectedEntry.kind === 'axis' && authoringAvailable"
          type="button"
          class="mw__btn mw__btn--ghost mw__btn--wide mp__assign"
          title="临时切换到原始模型点选成员, 写回 rig_map 后自动重跑并切回"
          @click="assignMode.start(selectedEntry.params.axisId)"
        >
          {{ selectedEntry.category === 'declared-only' ? '指认滑车成员(切换原始模型)' : '修改滑车成员(切换原始模型)' }}
        </button>
        <!-- 执行器/联动: 运动参数编辑(改完即预览, 写回见左栏底部) -->
        <RigParamsCard
          v-if="selectedEntry.kind === 'actuator' || selectedEntry.kind === 'linkage'"
          :entry="selectedEntry"
          :live="paramsLive"
          :dirty="paramsDirty"
          @change="onParamChange"
        />
      </section>
      <p v-else class="mw__notice mw__notice--info">
        在左栏选一个条目：轴与关节可拖滑杆或直接在视口里拖动核对行程；
        执行器与联动组可改运动学参数，改完即预览。
      </p>

      <section class="mw__panel">
        <button type="button" class="mp__fold" @click="jointPanel = !jointPanel">
          {{ jointPanel ? '▾' : '▸' }} 关节调试（编排姿态用）
        </button>
        <div v-if="jointPanel" class="mp__joints">
          <div v-for="(value, i) in jointDeg" :key="i" class="mp__jointRow">
            <span class="mp__jointName">J{{ i + 1 }}</span>
            <input
              type="range"
              min="-180"
              max="180"
              step="1"
              :value="value"
              @input="onJointSlider(i, $event.target.value)"
            />
            <span class="mp__jointVal">{{ Number(value).toFixed(0) }}°</span>
          </div>
          <button type="button" class="mw__btn mw__btn--ghost mw__btn--wide" @click="jointsHome">全部回零</button>
          <p class="mw__tip">拖滑杆会自动暂停播放；这里的角度只用于试姿态，不写进片段。</p>
        </div>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.mp__liquid {
  display: flex;
  flex: none;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  padding: 6px 8px;
  font-size: 11px;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 8px;
}

.mp__liquidLabel {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  color: var(--text-mid);
  cursor: pointer;
}

.mp__liquidHint {
  font-size: 10px;
  color: var(--text-dim);
}

.mp__assign { margin-top: 8px; }

.mp__fold {
  width: 100%;
  padding: 2px 0;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  text-align: left;
  cursor: pointer;
  background: none;
  border: none;
}

.mp__joints {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}

.mp__jointRow {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 11px;
}

.mp__jointName {
  flex: none;
  width: 20px;
  color: var(--text-mid);
}

.mp__jointRow input {
  flex: 1;
  accent-color: var(--accent);
}

.mp__jointVal {
  flex: none;
  width: 38px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  text-align: right;
}
</style>
