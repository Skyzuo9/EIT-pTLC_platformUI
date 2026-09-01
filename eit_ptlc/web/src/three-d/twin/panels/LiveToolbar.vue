<script setup>
/**
 * 功能: 实时页的观察工具栏 —— 悬在画布中间上方的半透明图标条.
 *
 * 为什么不复用 twin/scene/ViewToolbar.vue: 那条被装配台/材质台/动作台/工作台四家引用,
 * 且是文字按钮铺开的形制; 实时页要的是"图标 + 弹出菜单"的收窄形制, 改共享件会连坐四页.
 * 视觉语言(玻璃药丸 / .vt__btn--on 高亮 / top:12 居中)照抄它, 保持四页一致的观感.
 *
 * 视角与画质走 ContextMenu 弹层: 外部点击/Esc/视口翻转它已解决. 从 @click 打开是安全的 ——
 * 它的 window 捕获监听在 onMounted 才注册, 那时开启这一次的 pointerdown 早已冒泡完毕.
 */
import { computed, ref } from 'vue'

import ContextMenu from '../../common/ContextMenu.vue'
import { VIEW_PRESETS } from '../scene/CameraRig.js'

const props = defineProps({
  /** 当前画质档 */
  quality: { type: String, default: '' },
  /** 自动环绕是否开启 */
  autoRotate: { type: Boolean, default: false },
  /** 显示设置面板是否打开(画按钮激活态) */
  displayOpen: { type: Boolean, default: false },
})

const emit = defineEmits(['preset', 'quality', 'reset-view', 'display', 'autorotate', 'replay-intro'])

/**
 * 视角预设的中文名. key 直接枚举 CameraRig.VIEW_PRESETS ——
 * 旧 HUD 里那份 PRESETS 常量是手抄的 5 条, 漏了 back(后视), 这里不再手抄.
 */
const PRESET_LABEL = {
  iso: '轴测', front: '前视', back: '后视', left: '左视', right: '右视', top: '俯视',
}

const QUALITY_LABEL = { high: '高', medium: '中', low: '低' }

/** 弹层状态: {x, y, items} | null (同时只开一个) */
const menu = ref(null)

/**
 * 功能: 在按钮下方打开一个弹层.
 * @param {Event} event 点击事件(取按钮位置)
 * @param {object[]} items 菜单项
 * @returns {void}
 */
function openMenu(event, items) {
  const rect = event.currentTarget.getBoundingClientRect()
  menu.value = { x: rect.left, y: rect.bottom + 4, items }
}

const presetItems = computed(() =>
  Object.keys(VIEW_PRESETS).map((key) => ({
    key,
    label: PRESET_LABEL[key] || key,
    action: () => emit('preset', key),
  })),
)

const qualityItems = computed(() =>
  Object.keys(QUALITY_LABEL).map((key) => ({
    key,
    label: QUALITY_LABEL[key],
    hint: props.quality === key ? '当前' : '',
    action: () => emit('quality', key),
  })),
)
</script>

<template>
  <div class="lt">
    <div class="lt__group">
      <button
        type="button" class="lt__btn" title="切换标准视角"
        @click="openMenu($event, presetItems)"
      >
        <span class="lt__icon" aria-hidden="true">◳</span>视角<span class="lt__caret">▾</span>
      </button>
      <button type="button" class="lt__btn" title="回到看全整机的默认取景(并取消选中工位)"
              @click="emit('reset-view')">
        <span class="lt__icon" aria-hidden="true">⛶</span>全景
      </button>
    </div>

    <span class="lt__sep" />

    <div class="lt__group">
      <button
        type="button" class="lt__btn" title="渲染画质档位(卡顿时会自动降档)"
        @click="openMenu($event, qualityItems)"
      >
        <span class="lt__icon" aria-hidden="true">◈</span>{{ QUALITY_LABEL[quality] || '画质'
        }}<span class="lt__caret">▾</span>
      </button>
      <!-- data-display-toggle 必须留着: DisplayPanel 的捕获阶段"点外关闭"靠它认自己的按钮,
           少了它点这个按钮会开完立刻被关掉 -->
      <button
        type="button" class="lt__btn" :class="{ 'lt__btn--on': displayOpen }"
        data-display-toggle title="显示设置: 光源/阴影/效果/负载"
        @click="emit('display')"
      >
        <span class="lt__icon" aria-hidden="true">☀</span>显示
      </button>
    </div>

    <span class="lt__sep" />

    <div class="lt__group">
      <button
        type="button" class="lt__btn" :class="{ 'lt__btn--on': autoRotate }"
        title="镜头缓慢环绕整机; 手动操作相机或选中工位即自动停止"
        @click="emit('autorotate')"
      >
        <span class="lt__icon" aria-hidden="true">↻</span>环绕
      </button>
      <button type="button" class="lt__btn" title="重播开场动画(点击画面或 Esc 可跳过)"
              @click="emit('replay-intro')">
        <span class="lt__icon" aria-hidden="true">▶</span>开场
      </button>
    </div>

    <!-- Teleport 是必须的, 不是讲究: ContextMenu 是 position:fixed, 而本组件根 .lt 同时带
         transform 与 backdrop-filter —— 两者任一都会让 .lt 成为后代 fixed 元素的**包含块**,
         于是 openMenu 算出的视口坐标被再叠加一次 .lt 自身的位置, 菜单会甩到画面右侧;
         ContextMenu 内部拿 props.x 与 window.innerWidth 比的翻转判据也一并失效。
         挂到 body 下就没有任何祖先能抢包含块了。 -->
    <Teleport to="body">
      <ContextMenu
        v-if="menu"
        :x="menu.x"
        :y="menu.y"
        :items="menu.items"
        @close="menu = null"
      />
    </Teleport>
  </div>
</template>

<style scoped>
.lt {
  position: absolute;
  top: 12px;
  left: 50%;
  z-index: 9;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 5px 8px;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 8px;
  backdrop-filter: blur(10px);
  transform: translateX(-50%);
  /* 窄视口时不许压到左侧 HUD 上; 放不下就整条换行 */
  max-width: calc(100% - 2 * (var(--live-hud-w, 216px) + 24px));
  user-select: none;
}

.lt__group {
  display: flex;
  gap: 3px;
}

.lt__sep {
  width: 1px;
  height: 18px;
  background: var(--border);
}

.lt__btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 9px;
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  cursor: pointer;
  background: var(--control);
  border: 1px solid transparent;
  border-radius: 5px;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.lt__btn:hover {
  color: var(--text-bright);
  background: var(--control-hover);
  border-color: var(--accent-border);
}

.lt__btn--on {
  color: var(--accent-bright);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.lt__icon {
  font-size: 12px;
  line-height: 1;
  opacity: 0.85;
}

.lt__caret {
  font-size: 9px;
  color: var(--text-dim);
}
</style>
