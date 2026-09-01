<script setup>
// 控制台外壳: 最左竖向栏切换 / 态势条 / 左 Dock / 中工作区 (router-view) / 底 Monitor
// 大栏尺寸 (dock 宽 / monitor 高) 由 layout store 驱动, 经 CSS 变量注入栅格, 分隔条可拖拽
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import RailNav from './RailNav.vue'
import StatusBar from './StatusBar.vue'
import ExplorerDock from './ExplorerDock.vue'
import MonitorDock from './MonitorDock.vue'
import Splitter from './Splitter.vue'
import { useLayoutStore } from '../stores/layout'
import { useMonitorPrefsStore } from '../stores/monitorPrefs'
import { sectionOf } from '../utils/section.js'

const layout = useLayoutStore()
const route = useRoute()
// 动作页/设备节点详情页中区做成"无外壳"容器, 让内部两面板间露出页面底色缝 (照监视器)。
// 设备页仅在选中节点时 flush (两栏), 未选节点的落地页仍走白底单栏。
const isActionRoute = computed(() => route.path.startsWith('/library/action'))
const isDeviceDetail = computed(() => route.path.startsWith('/nodes/') && !!route.params.id)
const isThreeDRoute = computed(() => route.path.startsWith('/3d'))

// 底栏按页折叠: 当前页 section → 偏好 store (显式覆盖优先, 缺失走默认表);
// 收起时挂 .console--monitor-collapsed 切两行栅格, monitor 与其 seam 一并 v-if 卸载
const monitorPrefs = useMonitorPrefsStore()
const monitorCollapsed = computed(() => monitorPrefs.isCollapsed(sectionOf(route.path)))
</script>

<template>
  <div class="console" :class="{ 'console--monitor-collapsed': monitorCollapsed, 'console--three-d': isThreeDRoute }" :style="{ '--rail-w': layout.sizes.shellRailW + 'px', '--dock-w': layout.sizes.shellDockW + 'px', '--monitor-h': layout.sizes.shellMonitorH + 'px' }">
    <div class="area-rail"><RailNav /></div>
    <div class="area-status"><StatusBar /></div>
    <div v-if="!isThreeDRoute" class="area-dock"><ExplorerDock /></div>
    <main class="area-center" :class="{ 'area-center--flush': isActionRoute || isDeviceDetail || isThreeDRoute }"><router-view /></main>
    <div v-if="!monitorCollapsed" class="area-monitor"><MonitorDock /></div>
    <!-- rail↔dock 竖向 (rail 在左 → sign=+1); dock↔center 竖向 (dock 在左 → sign=+1); center↔monitor 横向 (monitor 在下 → sign=-1, 随折叠 v-if 卸载) -->
    <Splitter skey="shellRailW" dir="x" :sign="1" class="seam-rail-v" />
    <Splitter v-if="!isThreeDRoute" skey="shellDockW" dir="x" :sign="1" class="seam-shell-v" />
    <Splitter v-if="!monitorCollapsed" skey="shellMonitorH" dir="y" :sign="-1" class="seam-shell-h" />
  </div>
</template>
