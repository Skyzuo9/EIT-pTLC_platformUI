<script setup>
/**
 * 功能: 保存与重跑面板 —— 把授权结果落盘, 并触发管线把它变成真实的模型.
 *
 * 这里体现了整套工作流的核心取舍: 点了删除并不会立刻改模型, 而是先写成一份 yaml 名单,
 * 再由管线重新生成. 多花约 3 分钟(全链实测 2.5~3 分钟, 含 raw 换臂链),
 * 换来"图纸更新后决策不作废"和"随时可撤销".
 */
import { onMounted, ref } from 'vue'

import * as api from './authoringApi.js'

const props = defineProps({
  /** 授权中间件是否可用(生产构建里不可用) */
  available: { type: Boolean, default: false },
  /** 是否正在保存 */
  saving: { type: Boolean, default: false },
  /** 各标记计数 */
  counts: { type: Object, default: () => ({ delete: 0, keep: 0, decimate: 0 }) },
  /** 规模预估 */
  estimate: { type: Object, default: null },
  /** 保存按钮文案(装配台/材质台落盘目标不同, 文案由宿主定) */
  saveLabel: { type: String, default: '保存标记到 prune_list.yaml' },
  /**
   * 待生效摘要(材质台): {items: [{label, count}], budget: {used, projected, max}}
   * items 逐行显示"重跑后才生效"的改动; budget 显示绘制调用预算预估.
   */
  pending: { type: Object, default: null },
})

const emit = defineEmits(['save'])

const rebuilding = ref(false)
const steps = ref([])
const rebuildError = ref('')
const elapsed = ref(0)

/**
 * 功能: 轮询跟踪一次已在执行的重跑, 直到结束.
 *
 * 点击触发与挂载时恢复共用这一段: 进度的真身在 dev-server 进程里,
 * 组件只是它的显示器, 谁挂载谁接着显示.
 *
 * @returns {Promise<void>}
 */
async function track() {
  rebuilding.value = true
  try {
    const final = await api.waitRebuild((status) => {
      steps.value = status.steps
      elapsed.value = status.elapsed_s
    })
    rebuildError.value = final.error || ''
    if (!final.error) {
      // 模型文件已换, 但浏览器缓存里还是旧的 —— 硬刷新最省事也最不会出错
      setTimeout(() => window.location.reload(), 700)
    }
  } catch (error) {
    rebuildError.value = error.message
  } finally {
    rebuilding.value = false
  }
}

/**
 * 功能: 触发管线重跑并跟踪进度.
 *
 * 不跑 01/02 两步: STEP 解析要 11 分钟, 只有图纸本身变了才需要重跑,
 * 改删减规则只影响 03 之后的步骤.
 *
 * @param {string[]} [only] 只跑这几步; 空数组 = 全链. 宿主用它做"只刷工作台原始模型"
 *                          那种窄重跑(标红基线过期时只需要 raw-swap + raw).
 * @returns {Promise<void>}
 */
async function rebuild(only = []) {
  rebuilding.value = true
  rebuildError.value = ''
  steps.value = []
  try {
    await api.startRebuild(Array.isArray(only) ? only : [])
  } catch (error) {
    rebuildError.value = error.message
    rebuilding.value = false
    return
  }
  await track()
}

// 宿主(装配台的"基线过期"告警条)要能直接发起窄重跑, 而进度显示仍归本面板一处
defineExpose({ rebuild })

// 刷新/切页会销毁组件, 但重跑本体在 dev-server 里并没有停 ——
// 挂载时查一次服务端状态: 还在跑就把进度接回来继续轮询, 已失败就把结局补显出来.
onMounted(async () => {
  let status
  try {
    status = await api.rebuildStatus()
  } catch {
    return // 生产构建没有授权中间件, 保持静默
  }
  if (status.running) {
    steps.value = status.steps
    elapsed.value = status.elapsed_s
    await track()
  } else if (status.error) {
    rebuildError.value = status.error
    steps.value = status.steps
  }
})

/** 步骤状态对应的符号 */
const MARKS = { pending: '○', running: '◐', done: '●', failed: '✕' }
</script>

<template>
  <section class="rb">
    <header class="rb__head">保存与重跑</header>

    <p v-if="!available" class="rb__warn">
      授权中间件不可用（生产构建或未用 <code>npm run dev</code> 启动），当前为只读浏览模式。
    </p>

    <template v-else>
      <button
        type="button"
        class="rb__btn rb__btn--save"
        :disabled="saving || rebuilding"
        @click="emit('save')"
      >
        {{ saving ? '保存中…' : saveLabel }}
      </button>

      <button
        type="button"
        class="rb__btn rb__btn--run"
        :disabled="rebuilding || saving"
        @click="rebuild()"
      >
        {{ rebuilding ? `重跑中… ${elapsed}s` : '重跑管线（约 2.5~3 分钟）' }}
      </button>

      <div v-if="pending?.items?.length || pending?.budget" class="rb__pending">
        <p v-if="pending.items?.length" class="rb__pendingline">
          待生效：{{ pending.items.map((i) => `${i.label} ${i.count}`).join(' · ') }}（重跑后生效）
        </p>
        <p
          v-if="pending.budget"
          class="rb__pendingline"
          :class="{ 'rb__pendingline--warn': pending.budget.projected >= pending.budget.max * 0.9 }"
        >
          绘制调用预估 ~{{ pending.budget.projected }} / {{ pending.budget.max }}
          <template v-if="pending.budget.projected > pending.budget.used">
            （当前 {{ pending.budget.used }}）
          </template>
        </p>
      </div>

      <ol v-if="steps.length" class="rb__steps">
        <li v-for="step in steps" :key="step.id" :class="`rb__step--${step.status}`">
          <span class="rb__mark">{{ MARKS[step.status] }}</span>
          <span class="rb__label">{{ step.label }}</span>
          <span v-if="step.elapsed_s" class="rb__time">{{ step.elapsed_s }}s</span>
        </li>
      </ol>

      <pre v-if="rebuildError" class="rb__error">{{ rebuildError }}{{
        steps.find((s) => s.status === 'failed')?.tail
          ? '\n\n' + steps.find((s) => s.status === 'failed').tail
          : ''
      }}</pre>

      <p class="rb__note">
        重跑不含 STEP 转换（那步要 11 分钟，只有图纸变了才需要）。<br />
        完成后页面会自动刷新加载新模型。
      </p>
    </template>
  </section>
</template>

<style scoped>
.rb {
  flex: none;
  border-radius: 10px;
  background: var(--surface-soft);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  padding: 9px 12px 10px;
  color: var(--text-bright);
  font-size: 12px;
}

.rb__head {
  font-weight: 600;
  color: var(--text-mid);
  margin-bottom: 8px;
}

.rb__warn {
  margin: 0;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--warn-soft);
  border: 1px solid var(--warn-soft);
  color: var(--warn);
  line-height: 1.6;
}

.rb__warn code {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--well);
  font-size: 11px;
}

.rb__btn {
  width: 100%;
  margin-bottom: 5px;
  padding: 6px;
  border-radius: 6px;
  border: 1px solid var(--border-strong);
  background: var(--control);
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
}

.rb__btn:hover:not(:disabled) {
  background: var(--control-hover);
}

.rb__btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.rb__btn--save:not(:disabled) {
  border-color: var(--accent-border);
  background: var(--accent-soft);
  color: var(--accent-bright);
}

.rb__btn--run:not(:disabled) {
  border-color: var(--ok-soft);
  background: var(--ok-soft);
  color: var(--ok-bright);
}

.rb__steps {
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 2px;
}

.rb__steps li {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--text-dim);
}

.rb__step--running {
  color: var(--warn);
}
.rb__step--done {
  color: var(--ok-bright);
}
.rb__step--failed {
  color: var(--err-bright);
}

.rb__mark {
  width: 12px;
  flex: none;
}

.rb__label {
  flex: 1;
}

.rb__time {
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

.rb__error {
  margin: 8px 0 0;
  padding: 7px 9px;
  border-radius: 6px;
  background: var(--err-soft);
  border: 1px solid var(--err-soft);
  color: var(--err-bright);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
}

.rb__note {
  margin: 8px 0 0;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.6;
}

.rb__pending {
  margin-top: 2px;
  padding: 5px 8px;
  border-radius: 6px;
  background: var(--well, rgba(0, 0, 0, 0.12));
}

.rb__pendingline {
  margin: 0;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.6;
}

.rb__pendingline--warn {
  color: var(--warn);
}
</style>
