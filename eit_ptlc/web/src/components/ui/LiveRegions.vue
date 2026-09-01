<script setup>
// 常驻读屏播报区: 挂在 App.vue 根部, 与 announcer.js 单例配对。
// 必须常驻空元素 + 内容置换 (而非 v-if 动态挂载), 否则多数 AT 不播报首条。
import { politeText, assertiveText } from '../../composables/announcer.js'
</script>

<template>
  <div class="sr-only" role="status" aria-live="polite">{{ politeText }}</div>
  <div class="sr-only" role="alert">{{ assertiveText }}</div>
</template>
