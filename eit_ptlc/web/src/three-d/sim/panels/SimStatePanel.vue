<script setup>
/**
 * 功能: 沙盒状态编辑器 —— 轴/机器人/执行器三组, 单向流.
 *
 * 交互纪律: 滑杆拖动只改本地预览值, 松手(@change)才发补丁; 面板显示值永远来自
 * 沙盒状态快照(事件回流/轮询), 不做乐观回写 —— "3D 跟没跟" 本身就是沙盒链路的
 * 目视验收 (与 ManualControlPanel 的虚实核对哲学同构)。
 */
import { computed, reactive } from 'vue'

import {
  PUMP_STROKE_ML, axisRows, buildAxisPatch, buildEffectorPatch, buildJointPatch,
  buildMechanismPatch, buildPumpPatch, buildToolPatch, effectorRows, jointRows,
  mechanismGroups, poseRows, pumpRows,
} from '../simStateRows.js'

const props = defineProps({
  manifest: { type: Object, default: null },
  simState: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['patch', 'adopt', 'reset'])

/** 拖动中的本地预览值 (id -> mm/deg); 松手发补丁后清除 */
const preview = reactive({ axes: {}, joints: {} })

const axes = computed(() => axisRows(props.manifest, props.simState?.axes))
const joints = computed(() => jointRows(props.manifest, props.simState?.robot?.joint))
// 气缸组读的是单点快照 (PLC 气缸自动位), 与末端执行器分开: 后者是机器人 DO,
// 两类物理量混进一张表会让写口的语义含糊 (一个落 auto_ro, 一个发 tool_action)
const mechGroups = computed(() =>
  mechanismGroups(props.manifest, props.simState?.manual?.mechanisms))
const effectors = computed(() =>
  effectorRows(props.manifest, props.simState?.robot, props.simState?.mechanisms))
const tool = computed(() => props.simState?.robot?.tool ?? 0)
const tools = computed(() => props.manifest?.tools || [])
// TCP 位姿只读 (见 simStateRows.poseRows: 开写口会造出 pose 与 joint 不自洽的姿态)
const pose = computed(() => poseRows(props.simState?.robot?.pose))
// 注射泵相位: "吸了一半停电重开"是真实初态; busy 时禁写 (会与积分器打架, 后端也拒)
const pumps = computed(() => pumpRows(props.simState?.pumps))

function axisValue(row) {
  return preview.axes[row.id] ?? (row.mm ?? row.min)
}

function commitAxis(row, raw) {
  delete preview.axes[row.id]
  emit('patch', buildAxisPatch(row, raw))
}

function commitJoint(index, raw) {
  delete preview.joints[index]
  const degrees = joints.value.map((row, i) =>
    i === index ? Number(raw) : (preview.joints[i] ?? row.deg))
  emit('patch', buildJointPatch(joints.value, degrees))
}

function commitTool(raw) {
  emit('patch', buildToolPatch(raw))
}

function toggleMech(item) {
  emit('patch', buildMechanismPatch(item.id, !item.on))
}

/** 末端执行器: 未命令过 (on=null) 时按"开"发一次 —— 从未知走向确认。 */
function toggleEffector(row) {
  emit('patch', buildEffectorPatch(row.id, row.on === null ? true : !row.on))
}

function commitPump(row, field, raw) {
  emit('patch', buildPumpPatch(row.id, field, raw))
}
</script>

<template>
  <section class="sim-panel">
    <header class="sim-panel__head">
      <h3>状态设定</h3>
      <div class="sim-panel__actions">
        <button :disabled="disabled" @click="emit('adopt')">采纳实时状态</button>
        <button :disabled="disabled" @click="emit('reset')">复位 home</button>
      </div>
    </header>

    <details open>
      <summary>直线轴 ({{ axes.length }})</summary>
      <div v-for="row in axes" :key="row.id" class="sim-row">
        <span class="sim-row__label" :title="row.id">{{ row.label }}</span>
        <input
          type="range"
          :min="row.min"
          :max="row.max"
          step="0.1"
          :value="axisValue(row)"
          :disabled="disabled"
          @input="preview.axes[row.id] = Number($event.target.value)"
          @change="commitAxis(row, $event.target.value)"
        >
        <input
          class="sim-row__num"
          type="number"
          :value="Number(axisValue(row)).toFixed(1)"
          :disabled="disabled"
          @change="commitAxis(row, $event.target.value)"
        >
        <span class="sim-row__unit">mm</span>
      </div>
    </details>

    <details>
      <summary>机器人</summary>
      <div v-for="row in joints" :key="row.index" class="sim-row">
        <span class="sim-row__label">{{ row.label }}</span>
        <input
          type="range"
          :min="row.min"
          :max="row.max"
          step="0.5"
          :value="preview.joints[row.index] ?? row.deg"
          :disabled="disabled"
          @input="preview.joints[row.index] = Number($event.target.value)"
          @change="commitJoint(row.index, $event.target.value)"
        >
        <input
          class="sim-row__num"
          type="number"
          :value="Number(preview.joints[row.index] ?? row.deg).toFixed(1)"
          :disabled="disabled"
          @change="commitJoint(row.index, $event.target.value)"
        >
        <span class="sim-row__unit">°</span>
      </div>
      <div v-if="pose.length" class="sim-group">
        <div class="sim-group__title">TCP 位姿 (只读 · 由关节角决定)</div>
        <div class="sim-pose">
          <span v-for="item in pose" :key="item.key" class="sim-pose__cell">
            <b>{{ item.label }}</b>
            {{ item.value === null ? '—' : item.value.toFixed(item.unit === 'mm' ? 1 : 2) }}
            <i>{{ item.unit }}</i>
          </span>
        </div>
      </div>
      <div class="sim-row">
        <span class="sim-row__label">腕上工具</span>
        <select :value="tool" :disabled="disabled" @change="commitTool($event.target.value)">
          <option :value="0">0 · 裸腕</option>
          <option v-for="item in tools" :key="item.slot ?? item.id" :value="item.slot ?? item.id">
            {{ item.slot ?? item.id }} · {{ item.label || item.id }}
          </option>
        </select>
      </div>
      <div class="sim-group">
        <div class="sim-group__title">末端执行器</div>
        <div class="sim-group__grid">
          <button
            v-for="row in effectors"
            :key="row.id"
            class="sim-toggle"
            :class="{ 'sim-toggle--on': row.on === true, 'sim-toggle--unknown': !row.known }"
            :disabled="disabled"
            :title="row.known
              ? `${row.id} · ${row.source === 'feedback' ? '到位反馈' : '命令态(推定)'}`
              : `${row.id} · 未命令过, 状态未知`"
            @click="toggleEffector(row)"
          >
            {{ row.label }}<span v-if="row.source === 'commanded'" class="sim-toggle__hint">推定</span>
            <span v-else-if="!row.known" class="sim-toggle__hint">未命令</span>
          </button>
        </div>
        <p v-if="!effectors.length" class="sim-empty">裸腕 —— 未挂刀时不发布末端机构</p>
      </div>
    </details>

    <details v-if="pumps.length">
      <summary>注射泵 ({{ pumps.length }})</summary>
      <div v-for="row in pumps" :key="row.id" class="sim-row">
        <span class="sim-row__label" :title="row.busy ? '指令串执行中, 此刻不接受直写' : row.id">
          {{ row.id }}<span v-if="row.busy" class="sim-row__unit"> 忙</span>
        </span>
        <input
          class="sim-row__num"
          type="number"
          min="0"
          :max="PUMP_STROKE_ML"
          step="0.1"
          :value="Number(row.plungerMl).toFixed(2)"
          :disabled="disabled || row.busy"
          @change="commitPump(row, 'plunger_ml', $event.target.value)"
        >
        <span class="sim-row__unit">mL</span>
        <input
          class="sim-row__num"
          type="number"
          min="1"
          placeholder="阀"
          :value="row.valvePort ?? ''"
          :disabled="disabled || row.busy"
          @change="commitPump(row, 'valve_port', $event.target.value)"
        >
        <span class="sim-row__unit">口</span>
      </div>
    </details>

    <details>
      <summary>执行器 (气缸/联动)</summary>
      <div v-for="group in mechGroups" :key="group.station" class="sim-group">
        <div class="sim-group__title">{{ group.station }}</div>
        <div class="sim-group__grid">
          <button
            v-for="item in group.items"
            :key="item.id"
            class="sim-toggle"
            :class="{ 'sim-toggle--on': item.on }"
            :disabled="disabled"
            :title="item.id"
            @click="toggleMech(item)"
          >
            {{ item.label }}
          </button>
        </div>
      </div>
      <p v-if="!mechGroups.length" class="sim-empty">沙盒未就绪或无执行器快照</p>
    </details>
  </section>
</template>
