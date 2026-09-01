<script setup>
/**
 * 功能: 动作执行表单. 参数控件按上位机动作目录里的 schema 自动生成.
 *
 * 安全设计(执行动作会真正驱动硬件, 三道关卡缺一不可):
 *   1. 模式门禁 —— RUN 模式下调试类动作会被上位机拒绝, 这里提前置灰并说明原因,
 *      而不是让用户点了以后才收到 RejectCode;
 *   2. 二次确认 —— 点击执行后先弹确认条, 显示动作全名与参数, 确认后才真正下发;
 *   3. 结果回显 —— 完整展示 status / reject_code / error_code / message,
 *      不把失败悄悄吞掉.
 *
 * 唯一的例外是**急停**: confirmService.js 定案「急停触发永不确认 —— 急停路径上不许出现
 * 任何对话框」, 而第 2 关是无条件插一步的, 故按 actionAudience.NO_CONFIRM 点名豁免。
 */
import { computed, ref, watch } from 'vue'

import { runAction } from '../api.js'
import { NO_CONFIRM } from '../actionAudience.js'
import { coerceParams, defaultValuesOf, missingRequiredOf, modeAllows } from './actionParams.js'
import ActionParamsForm from './ActionParamsForm.vue'

const props = defineProps({
  /** 动作定义(来自 GET /api/actions) */
  action: { type: Object, required: true },
  /** 当前控制模式: RUN / DEBUG */
  controlMode: { type: String, default: '' },
})

const emit = defineEmits(['executed', 'close'])

/** 参数取值 */
const values = ref({})
/** 当前处于"待确认"状态 */
const confirming = ref(false)
/** 正在下发 */
const running = ref(false)
/** 执行结果 */
const result = ref(null)
/** 前端校验或网络错误 */
const failure = ref('')

/** 动作声明的参数列表 */
const params = computed(() => props.action?.params || [])

/** 急停这类"越快越好"的动作不插二次确认 —— 见文件头注 */
const skipConfirm = computed(() => NO_CONFIRM.has(props.action?.name))

/**
 * 该动作是否被当前控制模式允许.
 * 动作定义里的 modes 声明了它可在哪些模式下执行; 缺省视为不限制.
 */
const modeAllowed = computed(() => modeAllows(props.action, props.controlMode))

const modeHint = computed(() => {
  if (modeAllowed.value) return ''
  const modes = (props.action?.modes || []).join(' / ')
  return `当前为 ${props.controlMode} 模式, 该动作仅允许在 ${modes} 模式下执行`
})

/** 必填参数是否都已填写 */
const missingRequired = computed(() => missingRequiredOf(params.value, values.value))

/**
 * 功能: 按参数 schema 初始化默认值.
 * @returns {void}
 */
function resetValues() {
  values.value = defaultValuesOf(params.value)
  confirming.value = false
  result.value = null
  failure.value = ''
}

watch(() => props.action?.name, resetValues, { immediate: true })

/**
 * 功能: 真正下发动作.
 * @returns {Promise<void>}
 */
async function execute() {
  confirming.value = false
  running.value = true
  failure.value = ''
  result.value = null
  try {
    result.value = await runAction(props.action.name, coerceParams(params.value, values.value))
    emit('executed', result.value)
  } catch (error) {
    failure.value = error?.message || String(error)
  } finally {
    running.value = false
  }
}

/** 结果是否算成功 */
const succeeded = computed(() => {
  const status = String(result.value?.status || '').toUpperCase()
  return status === 'DONE' || status === 'ACCEPTED' || status === 'SUBMITTED'
})
</script>

<template>
  <div class="form">
    <header class="form__head">
      <div>
        <div class="form__name">{{ action.name }}</div>
        <div v-if="action.label" class="form__label">{{ action.label }}</div>
      </div>
      <button type="button" class="form__close" aria-label="关闭" @click="emit('close')">×</button>
    </header>

    <!-- 有 hint(操作员向一句话)时它当正文, 工程师级长 desc 折进「详细说明」;
         没有 hint 的动作(工程师区)保持长 desc 平铺 —— 那正是排障要看的 -->
    <template v-if="action.hint">
      <p class="form__desc">{{ action.hint }}</p>
      <details v-if="action.desc" class="dock-details">
        <summary>详细说明</summary>
        <p class="form__desc">{{ action.desc }}</p>
      </details>
    </template>
    <p v-else-if="action.desc" class="form__desc">{{ action.desc }}</p>

    <div v-if="!modeAllowed" class="form__gate">{{ modeHint }}</div>

    <ActionParamsForm v-model="values" :params="params" />

    <div v-if="missingRequired.length" class="form__warn">
      必填项未填: {{ missingRequired.join('、') }}
    </div>

    <div class="form__actions">
      <template v-if="!confirming">
        <button
          type="button"
          class="form__btn"
          :class="skipConfirm ? 'form__btn--danger' : 'form__btn--primary'"
          :disabled="!modeAllowed || running || missingRequired.length > 0"
          @click="skipConfirm ? execute() : (confirming = true)"
        >
          {{ skipConfirm ? '立即执行' : '执行…' }}
        </button>
      </template>
      <template v-else>
        <span class="form__confirm-text">确认执行 {{ action.name }}？该动作会驱动真实设备</span>
        <button type="button" class="form__btn form__btn--danger" :disabled="running" @click="execute">
          确认执行
        </button>
        <button type="button" class="form__btn" @click="confirming = false">取消</button>
      </template>
      <span v-if="running" class="form__running">下发中…</span>
    </div>

    <div v-if="failure" class="form__result form__result--bad">请求失败: {{ failure }}</div>

    <div
      v-else-if="result"
      class="form__result"
      :class="succeeded ? 'form__result--ok' : 'form__result--bad'"
    >
      <div><strong>状态</strong> {{ result.status }}</div>
      <div v-if="result.reject_code"><strong>拒绝码</strong> {{ result.reject_code }}</div>
      <div v-if="result.error_code"><strong>错误码</strong> {{ result.error_code }}</div>
      <div v-if="result.message"><strong>说明</strong> {{ result.message }}</div>
      <div v-if="result.step !== undefined && result.step !== null">
        <strong>步骤</strong> {{ result.step }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.form {
  padding: 12px 14px;
  border-radius: 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.form__name {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 13px;
  color: var(--accent-bright);
}

.form__label {
  font-size: 12px;
  color: var(--text-bright);
  margin-top: 2px;
}

.form__close {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}

.form__close:hover {
  color: var(--text-bright);
}

.form__desc {
  margin: 0;
  font-size: 12px;
  color: var(--text-mid);
  line-height: 1.5;
}

.form__gate {
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--warn-soft);
  border: 1px solid var(--warn-soft);
  color: var(--warn);
  font-size: 12px;
}

/* 参数控件的样式随 ActionParamsForm 一起走(.apf__*), 这里不再重复 */

.form__warn {
  font-size: 12px;
  color: var(--warn);
}

.form__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.form__confirm-text {
  font-size: 12px;
  color: var(--err-bright);
  flex: 1 1 100%;
}

.form__btn {
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-strong);
  background: var(--control);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}

.form__btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.form__btn--primary:not(:disabled) {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent-bright);
}

.form__btn--danger:not(:disabled) {
  background: var(--err-soft);
  border-color: var(--err-soft);
  color: var(--err-bright);
}

.form__running {
  font-size: 12px;
  color: var(--warn);
}

.form__result {
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 12px;
  display: grid;
  gap: 3px;
  line-height: 1.5;
}

.form__result--ok {
  background: var(--ok-soft);
  border: 1px solid var(--ok-soft);
  color: var(--ok-bright);
}

.form__result--bad {
  background: var(--err-soft);
  border: 1px solid var(--err-soft);
  color: var(--err-bright);
}

.form__result strong {
  color: inherit;
  opacity: 0.75;
  margin-right: 6px;
  font-weight: 500;
}
</style>
