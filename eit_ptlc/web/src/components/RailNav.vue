<script setup>
// 最左竖向栏切换 (activity-bar): PLC / 设备 / 动作 / 流程 / 点位 / 视觉 / 液位 / 排程 / 实验 / 物料 / 执行记录; active 由路由推导
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { sectionOf } from '../utils/section.js'

const route = useRoute()

const section = computed(() => sectionOf(route.path))

// d: 图标 path 数据 (Feather 风描边, 24 viewBox), 纯视觉装饰, 不参与任何逻辑
const TABS = [
  { key: 'plc', base: '/plc', label: 'PLC',
    d: ['M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3Z', 'M9.5 9.5h5v5h-5Z', 'M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2'] },
  { key: 'nodes', base: '/nodes', label: '设备',
    d: ['M4.5 4h15A1.5 1.5 0 0 1 21 5.5v3A1.5 1.5 0 0 1 19.5 10h-15A1.5 1.5 0 0 1 3 8.5v-3A1.5 1.5 0 0 1 4.5 4Z', 'M4.5 14h15a1.5 1.5 0 0 1 1.5 1.5v3a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18.5v-3A1.5 1.5 0 0 1 4.5 14Z', 'M6.5 7h.01M6.5 17h.01'] },
  { key: 'three_d', base: '/3d/live', label: '3D',
    d: ['M12 2.8 20 7.2v9.6L12 21.2 4 16.8V7.2L12 2.8Z', 'M4.3 7.4 12 11.7l7.7-4.3', 'M12 11.7v9.2'] },
  { key: 'action', base: '/library/action', label: '动作',
    d: ['M13 2 3 14h9l-1 8 10-12h-9l1-8Z'] },
  { key: 'operation', base: '/library/operation', label: '流程',
    d: ['M4 4h6v6H4Z', 'M14 14h6v6h-6Z', 'M10 7h4a3 3 0 0 1 3 3v4'] },
  // 调度: 段组合 DAG (一进两分再汇一) —— 图形即"串行/并行"本身
  { key: 'schedule', base: '/schedule', label: '调度',
    d: ['M9.5 2.5h5v4h-5Z', 'M3 10h5v4H3Z', 'M16 10h5v4h-5Z', 'M9.5 17.5h5v4h-5Z',
        'M12 6.5v1.2a1.3 1.3 0 0 1-1.3 1.3H5.5', 'M12 6.5v1.2a1.3 1.3 0 0 0 1.3 1.3h5.2',
        'M5.5 14v1.2a1.3 1.3 0 0 0 1.3 1.3H12', 'M18.5 14v1.2a1.3 1.3 0 0 1-1.3 1.3H12'] },
  { key: 'points', base: '/points', label: '点位',
    d: ['M12 5.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z', 'M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22', 'M12 12h.01'] },
  { key: 'vision', base: '/vision', label: '视觉',
    d: ['M9.5 4h5l2 3H20a1.5 1.5 0 0 1 1.5 1.5V18a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 18V8.5A1.5 1.5 0 0 1 4 7h3.5l2-3Z', 'M12 9.5a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z'] },
  { key: 'water_level', base: '/water_level', label: '液位',
    d: ['M12 3.5c3.6 4.1 5.5 6.9 5.5 9.5a5.5 5.5 0 0 1-11 0c0-2.6 1.9-5.4 5.5-9.5Z', 'M9 14.5h6'] },
  { key: 'planner', base: '/planner', label: '排程',
    d: ['M5 5.5h14A1.5 1.5 0 0 1 20.5 7v12a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V7A1.5 1.5 0 0 1 5 5.5Z', 'M8 3v4M16 3v4M3.5 10.5h17', 'M7 14h6M11 17h6'] },
  { key: 'scheduler', base: '/experiment', label: '实验',
    d: ['M4 6h7M4 12h7M4 18h7', 'M15 5.5 21 9l-6 3.5v-7Z', 'M15 14.5h6M15 18h6'] },
  { key: 'materials', base: '/materials', label: '物料',
    d: ['M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5Z', 'M3.7 7.2 12 11.7l8.3-4.5', 'M12 11.7v9.6'] },
  { key: 'runs', base: '/runs', label: '执行记录',
    d: ['M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8', 'M3 3v5h5', 'M12 7v5l4 2'] },
]
</script>

<template>
  <nav class="rail" aria-label="主导航">
    <!-- 真链接 (router-link): 中键/Ctrl+点击可开新标签, 右键可复制地址; 视觉沿用 .rail-tab -->
    <router-link
      v-for="t in TABS"
      :key="t.key"
      class="rail-tab"
      :class="{ active: section === t.key }"
      :aria-current="section === t.key ? 'page' : undefined"
      :to="t.base"
    >
      <svg class="rail-ic" viewBox="0 0 24 24" aria-hidden="true">
        <path v-for="(p, i) in t.d" :key="i" :d="p" />
      </svg>
      <span>{{ t.label }}</span>
    </router-link>
  </nav>
</template>

<style scoped>
/* router-link 化后 .rail-tab 落在 <a> 上: 去链接缺省装饰, 其余样式仍吃全局 .rail-tab */
a.rail-tab { text-decoration: none; }
</style>
