<script setup>
/**
 * 功能: 实时页左栏 —— 在线状态 + 工位列表(本页主导航) + 警告页脚.
 *
 * 由旧 TwinHud.vue(605 行, 什么都往里塞)瘦身而来: 视角/画质/开关去了 LiveToolbar,
 * 12 行指标与只读诊断去了右侧信息坞的两个页签. 剩下的只有"选哪个工位"这一件事.
 *
 * ⚠ 防截断契约(旧版下半截被浏览器裁掉的根因就在这里, 别删这三条):
 *     ① .live-hud 声明 max-height —— 旧的 .hud 连这个都没有, 内容一长就直接淌出视口底;
 *     ② 头/尾 flex:none, 不参与压缩;
 *     ③ **恰好一个**子元素是滚动体, 且它必须带 min-height:0 ——
 *        flex 子项默认 min-height:auto, 拒绝缩到内容以下, 所以只给父级 overflow 治不好。
 *   无论工位多少、警告多少、视口多矮, 这三条一起保证它不可能再被裁.
 */
import { HEALTH_TEXT, MATERIAL_HEALTH_TEXT } from '../../../utils/deviceLabels.js'

const props = defineProps({
  /** 工位清单(已按显示顺序过滤好) */
  stations: { type: Array, default: () => [] },
  /** 工位健康度(来自 PLC 遥测节点; 没有 nodeId 的工位不会有值) */
  health: { type: Object, default: () => ({}) },
  /**
   * 物料健康度(由光电与账本对不对得上推出) —— 只给没有遥测节点、但管着物料的工位用,
   * 眼下就是料架。有遥测节点的工位以设备健康为准, 不看这个。
   */
  materialHealth: { type: Object, default: () => ({}) },
  /** 各工位已核实光电的路数(tooltip 交代判据依据几路, 不许让人以为全被盯着) */
  sensorCounts: { type: Object, default: () => ({}) },
  /** 当前选中/悬停的工位 */
  selected: { type: String, default: null },
  hovered: { type: String, default: null },
  /** 能相机飞入的工位 id 集合(glbNode 真的解进了绑定层的那些) */
  focusable: { type: Object, default: () => new Set() },
  /** 事件流连接状态 */
  connection: { type: Object, default: () => ({ connected: false, lastError: '' }) },
  /** 一句话在线状态(实时/部分陈旧/重连中/离线) */
  liveLabel: { type: String, default: '' },
  /** manifest 装配警告(原先是画布左下角的独立浮层, 并进来省一个绝对定位元素) */
  warnings: { type: Array, default: () => [] },
})

const emit = defineEmits(['station'])

/**
 * 功能: 取一个工位小圆点的状态类名.
 *
 * 有 PLC 遥测节点的工位以设备健康为准; 没有节点的(料架)退到物料健康 ——
 * 后者的 'ok' 与前者共用绿色, 'mismatch' 用黄色(与 busy 同色但语义不同, 文案里说清)。
 * @param {object} station 工位定义
 * @returns {string} 状态键
 */
function dotState(station) {
  if (station.nodeId) return props.health[station.id] || 'unknown'
  return props.materialHealth[station.id] || 'unknown'
}

/**
 * 功能: 工位行的 tooltip —— 说清状态、判据来源与点击后会发生什么.
 * @param {object} station 工位定义
 * @param {boolean} canFocus 是否能相机飞入
 * @returns {string} tooltip 文本
 */
function stationTitle(station, canFocus) {
  const tail = canFocus ? '点击 = 特写 + 详情' : '模型里没有这个工位的几何, 相机不会移动'
  if (station.nodeId) {
    return `${station.label} · ${HEALTH_TEXT[props.health[station.id]] || '未知'} —— ${tail}`
  }
  // 无遥测节点的工位: 必须交代绿灯是凭几路光电得出的, 否则会被当成"整架都在监控中"
  const state = props.materialHealth[station.id] || 'unknown'
  const count = props.sensorCounts[station.id] || 0
  // 绿只代表"这几路已核实光电没有与账本打架", 不代表整架都在监控中 ——
  // 料架 14 个点位里有 12 个极性未核实(实测未供电), 文案必须把这层说破
  const basis = count
    ? `依据 ${count} 路已核实光电, 其余点位极性未核实、不参与判定`
    : '该工位没有已核实的光电, 无法判定帐实是否一致'
  return `${station.label} · ${MATERIAL_HEALTH_TEXT[state]} —— ${basis}。${tail}`
}
</script>

<template>
  <div class="live-hud">
    <header class="live-hud__head">
      <span class="live-hud__dot" :class="connection.connected ? 'is-live' : 'is-down'" />
      <span>PTLC 自动化设备</span>
      <span class="live-hud__live">{{ liveLabel }}</span>
    </header>

    <div class="live-hud__list">
      <button
        v-for="station in stations"
        :key="station.id"
        type="button"
        class="live-hud__station"
        :class="{
          'is-selected': selected === station.id,
          'is-hovered': hovered === station.id,
        }"
        :title="stationTitle(station, focusable.has(station.id))"
        @click="emit('station', station.id)"
      >
        <span class="live-hud__station-dot" :class="`is-${dotState(station)}`" />
        <span class="live-hud__station-name">{{ station.label }}</span>
      </button>
    </div>

    <footer class="live-hud__foot">
      <p v-for="(warning, index) in warnings" :key="index" class="live-hud__warn">{{ warning }}</p>
      <p v-if="!connection.connected && connection.lastError" class="live-hud__warn">
        {{ connection.lastError }}
      </p>
      <p class="live-hud__tip">点击工位 = 特写 + 详情</p>
    </footer>
  </div>
</template>

<style scoped>
.live-hud {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: var(--live-hud-w, 216px);
  /* ① 永远够不到视口底 */
  max-height: calc(100% - 32px);
  min-height: 0;
  padding: 12px 14px;
  font-size: 12px;
  color: var(--text-bright);
  user-select: none;
  background: var(--surface-soft);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgb(0 0 0 / 0.45);
  backdrop-filter: blur(14px);
}

/* ② 头尾不参与压缩 */
.live-hud__head,
.live-hud__foot {
  flex: none;
}

.live-hud__head {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.live-hud__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-dim);
}
.live-hud__dot.is-live {
  background: var(--ok);
  box-shadow: 0 0 10px var(--ok-soft);
}

.live-hud__live {
  margin-left: auto;
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
}

/* ③ 唯一的滚动体; min-height:0 是承重的 */
.live-hud__list {
  display: grid;
  flex: 1;
  gap: 2px;
  min-height: 0;
  padding: 8px 0;
  overflow-y: auto;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
  align-content: start;
  scrollbar-width: thin;
}

.live-hud__station {
  display: flex;
  gap: 7px;
  align-items: center;
  padding: 4px 6px;
  font-size: 12px;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  background: none;
  border: 1px solid transparent;
  border-radius: 5px;
}

.live-hud__station:hover,
.live-hud__station.is-hovered {
  background: var(--control-hover);
}

.live-hud__station.is-selected {
  color: var(--accent-bright);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.live-hud__station-dot {
  flex: none;
  width: 7px;
  height: 7px;
  background: var(--text-dim);
  border-radius: 50%;
}
.live-hud__station-dot.is-ok { background: var(--ok); box-shadow: 0 0 7px var(--ok-soft); }
.live-hud__station-dot.is-busy { background: var(--warn); box-shadow: 0 0 7px var(--warn-soft); }
.live-hud__station-dot.is-error { background: var(--err); box-shadow: 0 0 7px var(--err-soft); }
/* 帐实不一: 与 busy 同色不同义 —— 语义差别由 tooltip 文案承担, 别再造一个色阶 */
.live-hud__station-dot.is-mismatch { background: var(--warn); box-shadow: 0 0 7px var(--warn-soft); }

.live-hud__station-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.live-hud__foot {
  display: grid;
  gap: 4px;
  /* 警告条自己也有上限, 否则一堆警告能把工位列表压没 */
  max-height: 108px;
  overflow-y: auto;
  scrollbar-width: thin;
}

.live-hud__warn {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: var(--warn);
}

.live-hud__tip {
  margin: 0;
  font-size: 11px;
  color: var(--text-dim);
}
</style>
