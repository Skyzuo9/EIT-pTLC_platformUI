<script setup>
/**
 * 功能: 三维观察工具条 —— 视角预设、隐藏/隔离、透视、线框、辅助体开关、显示设置入口.
 *
 * 悬在画布中间上方, 与 CAD 软件的习惯一致. 纯展示组件, 具体行为由父级用 ViewTools /
 * SceneManager 实现, 这样装配台与材质台可以共用同一条工具栏.
 *
 * 旧的「光照」弹层(亮度/反射两滑块)已升级为独立的显示设置面板(DisplayPanel.vue,
 * 分光源强度/主光角度/阴影/效果/负载), 这里只留一个「显示」入口按钮 —— 按钮标
 * data-display-toggle 供面板的"点外关闭"识别, 免得点按钮关面板又立刻被重新打开.
 */
import { VIEW_PRESETS } from './ViewTools.js'

defineProps({
  /** 当前是否有选中对象; 没有时隐藏/隔离要禁用 */
  hasSelection: { type: Boolean, default: false },
  /** 透视是否开启 */
  xray: { type: Boolean, default: false },
  /** 线框是否开启 */
  wireframe: { type: Boolean, default: false },
  /** 辅助体是否显示 */
  helpers: { type: Boolean, default: true },
  /** 当前被隐藏的对象数, 用于提示"还原显示"是否有意义 */
  hiddenCount: { type: Number, default: 0 },
  /** 是否显示辅助体开关(装配台加载的原始模型里没有辅助体) */
  showHelpersToggle: { type: Boolean, default: true },
  /** 是否显示「显示」设置入口(装配台不调显示效果, 显示调整统一归材质侧) */
  showDisplayToggle: { type: Boolean, default: true },
  /** 显示设置面板是否打开(画按钮激活态) */
  displayOpen: { type: Boolean, default: false },
})

const emit = defineEmits([
  'view', 'reset', 'hide', 'isolate', 'showAll', 'xray', 'wireframe', 'helpers', 'display',
])

const presets = Object.entries(VIEW_PRESETS).map(([key, value]) => ({ key, label: value.label }))
</script>

<template>
  <div class="vt">
    <!-- 视角预设 -->
    <div class="vt__group">
      <button
        v-for="preset in presets"
        :key="preset.key"
        class="vt__btn"
        :title="`切到${preset.label}视图`"
        @click="emit('view', preset.key)"
      >
        {{ preset.label }}
      </button>
      <button class="vt__btn" title="回到看全整机的默认取景" @click="emit('reset')">全景</button>
    </div>

    <span class="vt__sep" />

    <!-- 显示控制 -->
    <div class="vt__group">
      <button
        class="vt__btn"
        :disabled="!hasSelection"
        title="隐藏当前选中的零件"
        @click="emit('hide')"
      >
        隐藏
      </button>
      <button
        class="vt__btn"
        :disabled="!hasSelection"
        title="只显示当前选中的零件, 其余全部隐藏"
        @click="emit('isolate')"
      >
        隔离
      </button>
      <button
        class="vt__btn"
        :disabled="!hiddenCount"
        :title="hiddenCount ? `还原 ${hiddenCount} 个被隐藏的对象` : '当前没有被隐藏的对象'"
        @click="emit('showAll')"
      >
        全显<span v-if="hiddenCount" class="vt__num">{{ hiddenCount }}</span>
      </button>
    </div>

    <span class="vt__sep" />

    <!-- 渲染模式 -->
    <div class="vt__group">
      <button
        :class="['vt__btn', { 'vt__btn--on': xray }]"
        title="把其余零件压成半透明, 看清内部结构"
        @click="emit('xray', !xray)"
      >
        透视
      </button>
      <button
        :class="['vt__btn', { 'vt__btn--on': wireframe }]"
        title="线框显示"
        @click="emit('wireframe', !wireframe)"
      >
        线框
      </button>
      <button
        v-if="showHelpersToggle"
        :class="['vt__btn', { 'vt__btn--on': !helpers }]"
        title="状态灯条与液面盒是管线生成的示意几何, 核对实物时可关掉"
        @click="emit('helpers', !helpers)"
      >
        {{ helpers ? '隐藏示意体' : '显示示意体' }}
      </button>
      <button
        v-if="showDisplayToggle"
        :class="['vt__btn', { 'vt__btn--on': displayOpen }]"
        data-display-toggle
        title="显示设置: 光源/阴影/效果/负载, 各页面共用且会记住"
        @click="emit('display')"
      >
        显示
      </button>
    </div>
  </div>
</template>

<style scoped>
.vt {
  position: absolute;
  top: 12px;
  left: 50%;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  background: var(--surface);
  border: 1px solid var(--hair);
  border-radius: 8px;
  backdrop-filter: blur(6px);
  transform: translateX(-50%);
}

.vt__group {
  display: flex;
  gap: 3px;
}

.vt__sep {
  width: 1px;
  height: 18px;
  background: var(--hair);
}

.vt__btn {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 4px 9px;
  font-size: 12px;
  color: var(--text-mid);
  white-space: nowrap;
  background: var(--control);
  border: 1px solid transparent;
  border-radius: 5px;
  cursor: pointer;
}

.vt__btn:hover:not(:disabled) {
  color: var(--text-bright);
  background: var(--control-hover);
}

.vt__btn:disabled {
  opacity: 0.32;
  cursor: default;
}

.vt__btn--on {
  color: var(--accent-ink);
  background: var(--accent);
  border-color: var(--accent);
}

.vt__num {
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  opacity: 0.75;
}
</style>
