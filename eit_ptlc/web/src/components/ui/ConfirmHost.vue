<script setup>
// 确认服务的唯一模态宿主 (挂 App.vue)。渲染 confirmService.current, 按 level 切视觉:
//   normal → 中性; danger/danger-ack → 实底红确认键 + .confirm-box.danger 后果框。
// 初始焦点: normal/prompt → 确认键/输入框; danger 级 → 取消键 (Enter 不误确认)。
import { computed, ref, watch } from 'vue'
import { current } from '../../composables/confirmService.js'
import ModalShell from './ModalShell.vue'

const acked = ref(false)
const promptValue = ref('')
const promptError = ref('')
const probeResult = ref(null) // { ok, text } | null

const req = computed(() => current.value)
const isDanger = computed(() => !!req.value && req.value.level !== 'normal')
const needAck = computed(() => !!req.value && req.value.level === 'danger-ack')

watch(req, (r) => {
  acked.value = false
  promptError.value = ''
  promptValue.value = r && r.kind === 'prompt' ? r.initial : ''
  probeResult.value = null
  if (r && r.probe) {
    const id = r.id
    r.probe()
      .then((res) => {
        if (current.value && current.value.id === id) probeResult.value = res || null
      })
      .catch((e) => {
        if (current.value && current.value.id === id)
          probeResult.value = { ok: false, text: `探测失败: ${e && e.message ? e.message : e}` }
      })
  }
})

function cancel() {
  if (req.value) req.value.settle(false)
}

function confirm() {
  const r = req.value
  if (!r) return
  if (r.kind === 'prompt') {
    const v = promptValue.value
    if (r.validate) {
      const err = r.validate(v)
      if (err) {
        promptError.value = err
        return
      }
    }
    r.settle(v)
  } else {
    if (needAck.value && !acked.value) return
    r.settle(true)
  }
}
</script>

<template>
  <ModalShell
    :open="!!req"
    :title="req ? req.title : ''"
    :initial-focus="isDanger ? '[data-confirm-cancel]' : req && req.kind === 'prompt' ? 'input' : '[data-confirm-ok]'"
    @close="cancel"
  >
    <template v-if="req">
      <div class="confirm-box" :class="{ danger: isDanger }" v-if="req.message.length || req.detail || probeResult">
        <p v-for="(m, i) in req.message" :key="i" class="warn-text">{{ m }}</p>
        <p v-if="req.detail" class="confirm-detail">{{ req.detail }}</p>
        <p v-if="probeResult" class="probe-line" :class="probeResult.ok ? 'ok' : 'bad'">
          {{ probeResult.ok ? '✓' : '✗' }} {{ probeResult.text }}
        </p>
      </div>

      <div v-if="req.kind === 'prompt'" class="field">
        <label>
          {{ req.title }}
          <input
            v-model="promptValue"
            type="text"
            :placeholder="req.placeholder"
            spellcheck="false"
            autocomplete="off"
            @keydown.enter.prevent="confirm"
          />
        </label>
        <p v-if="promptError" class="cell-err" role="status">{{ promptError }}</p>
      </div>

      <label v-if="needAck" class="ack">
        <input v-model="acked" type="checkbox" />
        <span>{{ req.ackText }}</span>
      </label>

      <div class="modal-actions confirm-actions">
        <button class="btn ghost" type="button" data-confirm-cancel @click="cancel">
          {{ req.cancelText }}
        </button>
        <button
          class="btn"
          :class="{ danger: isDanger }"
          type="button"
          data-confirm-ok
          :disabled="needAck && !acked"
          @click="confirm"
        >
          {{ req.confirmText }}
        </button>
      </div>
    </template>
  </ModalShell>
</template>
