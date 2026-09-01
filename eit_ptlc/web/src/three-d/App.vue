<script setup>
/**
 * 功能: 上位机内的三维工作区外壳. 顶部切换五个工作台, 主题统一跟随宿主.
 *
 * 导航做得很轻是有意的: 这是个演示型应用, 画面才是主角, 外壳不该抢视觉。
 */
import { computed } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import './styles.css'

const route = useRoute()

/** 工作台清单: 六个界面依次递进 —— 装配→材质→动作→演示→实时→仿真 */
const TABS = [
  { key: 'workbench', to: '/3d/workbench', label: '装配', hint: '白模删减预览 · 点选授权' },
  { key: 'materials', to: '/3d/materials', label: '材质', hint: '材质类 + 单零件 · 实时生效' },
  { key: 'motion', to: '/3d/motion', label: '动作', hint: '运动模式 · 标定 · 原子动作演示' },
  { key: 'demo', to: '/3d/demo', label: '演示', hint: '实机全部流程 · 自动生成动画' },
  { key: 'live', to: '/3d/live', label: '实时', hint: '实时镜像 · 手动控制核对' },
  { key: 'sim', to: '/3d/sim', label: '仿真', hint: '沙盒推演 · 设状态 · 真实执行链试跑' },
]

const current = computed(() => route.path)

/** 一路由一界面, 按路径前缀判激活即可 */
function isTabActive(tab) {
  return current.value.startsWith(tab.to)
}

const currentHint = computed(() => TABS.find(isTabActive)?.hint || '')

</script>

<template>
  <div class="three-d-app">
    <nav class="app__nav" aria-label="工作台切换">
      <span class="app__brand">3D</span>
      <RouterLink
        v-for="tab in TABS"
        :key="tab.key"
        :to="tab.to"
        class="app__tab"
        :class="{ 'app__tab--active': isTabActive(tab) }"
        :title="tab.hint"
      >
        {{ tab.label }}
      </RouterLink>
      <span class="app__hint">{{ currentHint }}</span>
    </nav>

    <main class="app__body">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.three-d-app {
  display: grid;
  grid-template-rows: 38px 1fr;
  width: 100%;
  height: 100%;
  background: var(--bg);
}

.app__nav {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  user-select: none;
}

.app__brand {
  margin-right: 14px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--text-bright);
}

.app__tab {
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-mid);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
}

.app__tab:hover {
  background: var(--control-hover);
  color: var(--text);
}

.app__tab--active {
  background: var(--accent-soft);
  color: var(--accent-bright);
}

.app__hint {
  margin-left: 12px;
  font-size: 11px;
  color: var(--text-dim);
}

.app__body {
  position: relative;
  overflow: hidden;
}
</style>
