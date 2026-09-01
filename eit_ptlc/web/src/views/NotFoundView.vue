<script setup>
// 404 兜底: 深链失效/输错 URL 时不再白屏
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <div class="empty nf">
    <div>
      <h2>页面不存在</h2>
      <p class="mono">{{ route.fullPath }}</p>
      <p>该地址没有对应的页面, 可能是深链已失效。</p>
      <router-link class="btn" to="/library/action">回到「库」首页</router-link>
    </div>
  </div>
</template>

<style scoped>
.nf { height: 100%; }
.nf h2 { margin: 0 0 8px; color: var(--text-strong); }
.nf .mono { font-family: var(--font-mono); color: var(--muted); overflow-wrap: anywhere; }
.nf .btn { display: inline-block; margin-top: 10px; text-decoration: none; }
</style>
