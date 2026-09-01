<script setup>
/**
 * 功能: 沙盒运行面板 —— 流程/单动作两页签 + 调试动词 + 时间倍率 + HITL 门 + 日志.
 *
 * 流程入参从脚本文档的 in 变量生成 (默认值预填); 执行走 /api/sim/* (沙盒 VM),
 * 与真机调试台 (DebugDock) 物理隔离 —— 本面板绝不喂全局 debug store。
 *
 * 入参提交契约见 ../runFormRows.js (纯函数, 离线单测钉住 —— 教训 2026-08-09:
 * 未归一的 enum 对象经 parseInt 变 NaN, JSON 序列化成 null, 后端精确报"留空")。
 */
import { computed, reactive, ref } from 'vue'

import { api as hostApi } from '../../../api.js'
import {
  collectFlowInputs, collectParams, rowsFromParams, rowsFromVars,
} from '../runFormRows.js'
import { isFinal } from '../simRunState.js'

const props = defineProps({
  session: { type: Object, required: true },   // useSimSession 返回值
  runState: { type: Object, required: true },  // simRunState (reactive)
})

const tab = ref('flow')
const operations = ref([])
const actions = ref([])
const selectedOp = ref('')
const selectedAction = ref('')
const inputRows = ref([])                       // [{name, label, type, value}]
const actionRows = ref([])
const loading = ref(false)
const lastActionResult = ref(null)
const rates = [1, 4, 16]

const running = computed(() => !isFinal(props.runState) && props.runState.status !== 'IDLE')

async function loadCatalogs() {
  loading.value = true
  try {
    const [ops, acts] = await Promise.all([
      fetch('/api/scripts?kind=operation').then((r) => r.json()),
      hostApi.listActions(),
    ])
    operations.value = (ops || []).filter((item) => !item?.ui?.hidden)
    actions.value = acts || []
  } catch (error) {
    props.session.message.value = `目录加载失败: ${error.message}`
  } finally {
    loading.value = false
  }
}
void loadCatalogs()

async function pickOperation(name) {
  selectedOp.value = name
  inputRows.value = []
  if (!name) return
  try {
    const doc = await fetch(`/api/scripts/${encodeURIComponent(name)}`).then((r) => r.json())
    inputRows.value = rowsFromVars(doc?.vars)
  } catch (error) {
    props.session.message.value = `脚本读取失败: ${error.message}`
  }
}

async function pickAction(name) {
  selectedAction.value = name
  actionRows.value = []
  lastActionResult.value = null
  if (!name) return
  try {
    const detail = await hostApi.getAction(name)
    actionRows.value = rowsFromParams(detail?.params)
  } catch (error) {
    props.session.message.value = `动作读取失败: ${error.message}`
  }
}

async function startFlow(modeRun) {
  if (!selectedOp.value) return
  try {
    const started = await props.session.api.startRun(selectedOp.value, {
      inputs: collectFlowInputs(inputRows.value), modeRun,
    })
    props.runState.runId = started.run_id
    props.runState.operation = selectedOp.value
    props.runState.status = String(started.status || 'RUNNING').toUpperCase()
    props.runState.logs.splice(0)
  } catch (error) {
    props.session.message.value = `启动失败: ${error.message}`
  }
}

async function verb(name) {
  if (!props.runState.runId) return
  try {
    const state = await props.session.api.runVerb(props.runState.runId, name)
    if (state?.status) props.runState.status = String(state.status).toUpperCase()
  } catch (error) {
    props.session.message.value = `${name} 失败: ${error.message}`
  }
}

async function runSingleAction() {
  if (!selectedAction.value) return
  lastActionResult.value = null
  try {
    lastActionResult.value = await props.session.api.runAction(
      selectedAction.value, collectParams(actionRows.value))
  } catch (error) {
    props.session.message.value = `动作执行失败: ${error.message}`
  }
}

const humanValues = reactive({})

async function replyHuman(choice) {
  const human = props.runState.human
  if (!human) return
  try {
    await props.session.api.humanReply(props.runState.runId, human.reqId, {
      choice, values: { ...humanValues },
    })
    props.runState.human = null
    Object.keys(humanValues).forEach((key) => delete humanValues[key])
  } catch (error) {
    props.session.message.value = `人工回复失败: ${error.message}`
  }
}
</script>

<template>
  <section class="sim-panel">
    <header class="sim-panel__head">
      <h3>运行控制</h3>
      <div class="sim-panel__actions">
        <span class="sim-rate__label">倍率</span>
        <button
          v-for="rate in rates"
          :key="rate"
          class="sim-toggle"
          :class="{ 'sim-toggle--on': session.timeScale.value === rate }"
          @click="session.setRate(rate)"
        >{{ rate }}×</button>
      </div>
    </header>

    <nav class="sim-tabs">
      <button :class="{ active: tab === 'flow' }" @click="tab = 'flow'">流程</button>
      <button :class="{ active: tab === 'action' }" @click="tab = 'action'">单动作</button>
    </nav>

    <div v-if="tab === 'flow'">
      <div class="sim-row">
        <select :value="selectedOp" @change="pickOperation($event.target.value)">
          <option value="">选择流程…</option>
          <option v-for="op in operations" :key="op.name" :value="op.name">
            {{ op.label || op.name }}
          </option>
        </select>
      </div>
      <div v-for="row in inputRows" :key="row.name" class="sim-row">
        <span class="sim-row__label" :title="row.name">{{ row.label }}</span>
        <select v-if="row.enum" v-model="row.value">
          <option value="">— 取默认{{ row.default != null ? ` (${row.default})` : '' }} —</option>
          <option v-for="opt in row.enum" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
        </select>
        <select v-else-if="row.type.includes('BOOL')" v-model="row.value">
          <option value="">— 取默认{{ row.default != null ? ` (${row.default})` : '' }} —</option>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <input v-else v-model="row.value" class="sim-row__wide" :placeholder="row.type">
      </div>
      <div class="sim-verbs">
        <button :disabled="!selectedOp || running" @click="startFlow('run')">▶ 运行</button>
        <button :disabled="!selectedOp || running" @click="startFlow('step')">⏯ 单步启动</button>
        <button :disabled="!running" @click="verb('step')">步入</button>
        <button :disabled="!running" @click="verb('step_over')">步过</button>
        <button :disabled="!running" @click="verb('run')">继续</button>
        <button :disabled="!running" @click="verb('pause')">暂停</button>
        <button :disabled="!running" @click="verb('resume')">恢复</button>
        <button :disabled="!runState.runId || !running" class="sim-danger" @click="verb('terminate')">终止</button>
      </div>

      <div class="sim-status">
        <span class="sim-status__badge" :data-status="runState.status">{{ runState.status }}</span>
        <span v-if="runState.operation">{{ runState.operation }}</span>
        <span v-if="runState.error" class="sim-danger-text">{{ runState.error }}</span>
      </div>

      <div v-if="runState.human" class="sim-hitl">
        <div class="sim-hitl__title">⏸ {{ runState.human.title || '人工确认' }}</div>
        <p>{{ runState.human.message }}</p>
        <div v-if="runState.human.kind === 'input'" class="sim-row">
          <input v-model="humanValues.value" placeholder="输入值">
        </div>
        <div class="sim-verbs">
          <template v-if="runState.human.options?.length">
            <button v-for="opt in runState.human.options" :key="opt.value ?? opt"
                    @click="replyHuman(opt.value ?? opt)">
              {{ opt.label ?? opt }}
            </button>
          </template>
          <template v-else>
            <button @click="replyHuman('ok')">确认</button>
            <button class="sim-danger" @click="replyHuman('cancel')">取消</button>
          </template>
        </div>
      </div>

      <ul class="sim-log">
        <li v-for="(entry, i) in [...runState.logs].reverse()" :key="runState.logs.length - i">
          {{ entry.text }}
        </li>
      </ul>
    </div>

    <div v-else>
      <div class="sim-row">
        <select :value="selectedAction" @change="pickAction($event.target.value)">
          <option value="">选择动作…</option>
          <option v-for="item in actions" :key="item.name" :value="item.name">
            {{ item.label || item.name }}
          </option>
        </select>
      </div>
      <div v-for="row in actionRows" :key="row.name" class="sim-row">
        <span class="sim-row__label" :title="row.name">{{ row.label }}</span>
        <select v-if="row.enum && row.enum.length" v-model="row.value">
          <option v-for="opt in row.enum" :key="opt" :value="opt">{{ opt }}</option>
        </select>
        <input v-else v-model="row.value" class="sim-row__wide" :placeholder="row.type">
      </div>
      <div class="sim-verbs">
        <button :disabled="!selectedAction" @click="runSingleAction">▶ 执行动作</button>
      </div>
      <div v-if="lastActionResult" class="sim-status">
        <span class="sim-status__badge" :data-status="lastActionResult.status?.toUpperCase()">
          {{ lastActionResult.status }}
        </span>
        <span>{{ lastActionResult.message }}</span>
      </div>
    </div>
  </section>
</template>
