<script setup>
/**
 * 功能: 工位「状态」页 —— 一句话概述 + 人话字段 + 运动轴 / 注射泵 / 展缸.
 *
 * 这一页是本次改造的第一诉求: 旧面板把遥测快照剩下的标量**原样**倒出来, 于是机械臂
 * 那张卡片写着 `check_result 0 / last_action 24 / robot_mode 5`。释义全部走
 * twin/stationStatus.js (纯函数, 有金样看门狗), 本组件只负责画.
 *
 * 两层呈现: 上面是操作员看得懂且用得上的; 底部折叠区原样保留全部原始字段 ——
 * 降级, 绝不丢弃, 排障的人仍然一个字段都不少.
 */
import { computed, ref, watch } from 'vue'

import { api } from '../../../api.js'
import { confirmAction } from '../../../composables/confirmService.js'
import { TOOL_NAMES, TOOL_OPTIONS } from '../../../utils/robotTools.js'
import { axesOfStation } from '../manifest.js'
import { headline, statusRows } from '../stationStatus.js'
import { lidSummary, tankLidRows } from '../lidStatus.js'

const props = defineProps({
  /** manifest 内容 */
  manifest: { type: Object, required: true },
  /** 工位定义 */
  station: { type: Object, default: null },
  /** 工位健康度 */
  health: { type: String, default: 'unknown' },
  /** 该工位的遥测 data 快照 */
  snapshot: { type: Object, default: null },
  /** 当前控制模式(改写末端工具声明的 runAction 要带上; 该动作 modes:[] 不限模式) */
  controlMode: { type: String, default: '' },
  /** 动作目录(把 ActiveCode 翻成中文动作名要用) */
  actionCatalog: { type: Array, default: () => [] },
  /** 8 个展缸的状态码 */
  tankStates: { type: Array, default: () => [] },
  /** 8 个展缸溶液槽里的液体体积(mL, 真实值) */
  tankVolumesMl: { type: Array, default: () => [] },
  /** 溶液槽满到槽口的容积(mL) */
  tankCapacityMl: { type: Number, default: 0 },
  /** 实时机构状态: 展缸盖开/关的唯一数据源 */
  mechanisms: { type: Array, default: () => [] },
  /** 注射泵柱塞快照 */
  pumpSyringes: { type: Array, default: () => [] },
})

/** 机器人节点与 L2 工位的字段表不同 */
const nodeKind = computed(() => (props.station?.nodeId === 'robot' ? 'robot' : 'plc'))
const isRobot = computed(() => nodeKind.value === 'robot')

// ── 末端工具声明(仅机械臂) ─────────────────────────────────────────────
// 机器人没有工具在位 DI, 挂载态是人工声明的权威四态(状态文件持久化);
// 显示与改写都在这一页 —— 声明决定语义工具动作(夹爪/吸盘)的放行白名单。
const mountedTool = computed(() => {
  const value = Number(props.snapshot?.tool_state?.mounted_tool)
  return Number.isFinite(value) ? value : null
})
const mountedToolText = computed(() =>
  (mountedTool.value === null ? '—' : TOOL_NAMES[String(mountedTool.value)] ?? `工具 ${mountedTool.value}`))

/** 下拉默认值: 首次拿到权威当前值同步一次, 之后保持操作员的选择(照抄二维页的闩法) */
const declaredTool = ref(0)
const declaredToolSynced = ref(false)
watch(mountedTool, (value) => {
  if (!declaredToolSynced.value && value !== null) {
    declaredTool.value = value
    declaredToolSynced.value = true
  }
}, { immediate: true })

const toolMessage = ref('')

/** 功能: 改写权威挂载声明(danger 确认; 与二维 RobotJogPanel.declareTool 同款). */
async function declareTool() {
  const name = TOOL_NAMES[String(declaredTool.value)] ?? String(declaredTool.value)
  const ok = await confirmAction({
    title: '改写当前挂载工具',
    message: `将把权威工具态改写为「${name}」并持久化。声明与实机不符时, 语义工具动作的安全前提会失效。`,
    level: 'danger',
    confirmText: '改写',
  })
  if (!ok) return
  toolMessage.value = ''
  try {
    await api.runAction('robot.set_mounted_tool',
      { tool_id: String(declaredTool.value) }, props.controlMode)
    toolMessage.value = `已声明挂载: ${name}`
  } catch (err) {
    toolMessage.value = `设置挂载工具失败: ${err.message}`
  }
}

const summary = computed(() =>
  headline(props.station, props.health, props.snapshot, { actionCatalog: props.actionCatalog }))

const rows = computed(() => statusRows(nodeKind.value, props.snapshot, {
  stationId: props.station?.id,
  actionCatalog: props.actionCatalog,
}))

/** 该工位下的运动轴, 附带当前位置 */
const axes = computed(() => {
  if (!props.station) return []
  return axesOfStation(props.manifest, props.station.id).map((axis) => {
    const key = axis.telemetry?.key
    const value = key && props.snapshot ? props.snapshot[key] : undefined
    return {
      ...axis,
      value: typeof value === 'number' ? value : null,
      // 未下装的 PLC 符号会返回 null; 明确区分"没这个量"和"读到 0"
      available: typeof value === 'number',
    }
  })
})

/** 展缸区块只在展开工位显示: 工艺状态码 + 盖开/关(两路独立数据源) */
const tanks = computed(() => {
  if (props.station?.id !== 'DEVELOP') return []
  const styles = props.manifest.tankStateStyles || {}
  return tankLidRows(props.manifest.tanks || [], props.mechanisms).map((tank) => {
    const state = props.tankStates[tank.index] ?? 0
    const style = styles[String(state)] || styles.default || {}
    // 液位条显示的是**真实 mL**, 不带三维那边的观感放大系数 —— 整机远景下溶液槽只有
    // 210×40mm, 三维里的液面高度是放大过的, 面板必须给出没有被放大的数字。
    const volumeMl = props.tankVolumesMl[tank.index] ?? 0
    const fill = props.tankCapacityMl > 0
      ? Math.max(0, Math.min(1, volumeMl / props.tankCapacityMl))
      : 0
    return {
      ...tank,
      state,
      stateLabel: style.label || '—',
      color: style.color || '#5a6472',
      volumeMl,
      fillPercent: `${(fill * 100).toFixed(1)}%`,
    }
  })
})

/** manifest 没有 tankLiquid(液面停用)时整列隐藏, 不留空槽位 */
const hasLiquid = computed(() => props.tankCapacityMl > 0)

/** 本工位的注射泵. 展开 2 台(缸 1-4 / 5-8)、上样 1 台、收集 1 台(CAD 未建模, 仍显读数) */
const pumps = computed(() =>
  (props.pumpSyringes || []).filter((pump) => pump.station === props.station?.id))

/** 行程分母(mm), 三台同型号故取第一台即可; 缺省回退官方额定 60 */
const pumpStrokeMm = computed(() => props.manifest?.pumpSyringe?.strokeMm ?? 60)

const lidTotals = computed(() => lidSummary(tanks.value))

/** 相位读数一行: 吸/排 · 第N相 · V速度; 正停在 M 延时里时显"稳液" */
function pumpPhaseText(phase) {
  if (phase.holding) return `稳液 · ${phase.index}/${phase.count}`
  const op = phase.op === 'aspirate' ? '吸液' : phase.op === 'dispense' ? '打液' : '归零'
  const speed = phase.speed ? ` · V${phase.speed}` : ''
  return `${op} · ${phase.index}/${phase.count}${speed}`
}

/**
 * 功能: 轴行程条的填充百分比.
 * @param {object} axis 轴行
 * @returns {string} CSS 宽度
 */
function axisFill(axis) {
  if (!axis.available) return '0%'
  const [lo, hi] = axis.rangeMm || [0, 1]
  const pct = ((axis.value - lo) / ((hi - lo) || 1)) * 100
  return `${Math.min(100, Math.max(0, pct))}%`
}
</script>

<template>
  <div v-if="station" class="sst">
    <!-- 一句话概述: 扫一眼就知道这个工位此刻在干嘛 -->
    <p class="sst__headline" :class="`is-${summary.tone}`">{{ summary.text }}</p>

    <section v-if="rows.ops.length" class="dock-section">
      <h3 class="dock-h3">实时状态</h3>
      <dl class="dock-fields">
        <div v-for="row in rows.ops" :key="row.key" class="dock-field">
          <dt>{{ row.label }}</dt>
          <dd :class="row.tone">{{ row.text }}</dd>
        </div>
      </dl>
    </section>
    <p v-else-if="station.nodeId && !snapshot" class="dock-empty">
      暂无遥测数据（后端未连接或该节点离线）
    </p>

    <!-- 末端工具声明(仅机械臂): 权威态显示 + 人工改写入口 -->
    <section v-if="isRobot" class="dock-section">
      <h3 class="dock-h3">
        末端工具<span class="dock-h3__sub">人工声明的权威态, 决定语义动作放行</span>
      </h3>
      <div class="dock-field sst__tool-now">
        <dt>当前挂载</dt>
        <dd>{{ mountedToolText }}</dd>
      </div>
      <div class="sst__tool-edit">
        <select v-model.number="declaredTool" class="sst__tool-select" :disabled="!snapshot">
          <option v-for="opt in TOOL_OPTIONS" :key="opt.id" :value="opt.id">{{ opt.text }}</option>
        </select>
        <button
          type="button" class="dock-btn"
          :disabled="!snapshot || declaredTool === mountedTool"
          :title="declaredTool === mountedTool ? '与当前声明一致, 无需改写' : ''"
          @click="declareTool"
        >改写声明</button>
      </div>
      <p class="sst__tool-note">
        机器人没有工具在位传感, 挂载态靠人工声明并持久化; 声明与实机不符会让夹爪/吸盘动作的安全前提失效。
      </p>
      <p v-if="toolMessage" class="sst__tool-msg">{{ toolMessage }}</p>
    </section>

    <section v-if="axes.length" class="dock-section">
      <h3 class="dock-h3">运动轴</h3>
      <div v-for="axis in axes" :key="axis.id" class="dock-row">
        <div class="dock-row__head">
          <span>{{ axis.label }}</span>
          <span class="dock-row__value">{{ axis.available ? `${axis.value.toFixed(1)} mm` : '—' }}</span>
        </div>
        <div class="dock-bar">
          <div class="dock-bar__fill" :style="{ width: axisFill(axis) }" />
        </div>
        <div class="dock-row__foot">
          <span>{{ axis.rangeMm[0] }} ~ {{ axis.rangeMm[1] }} mm</span>
          <span v-if="!axis.rigged" class="dock-tag">模型未装配</span>
        </div>
      </div>
    </section>

    <section v-if="pumps.length" class="dock-section">
      <h3 class="dock-h3">
        注射泵（{{ pumps.length }}）
        <!-- 恒显: 这一列的数字全是按动作参数估的, 不是量出来的 -->
        <span class="dock-h3__sub">柱塞位置为估计值</span>
      </h3>
      <div v-for="pump in pumps" :key="pump.id" class="dock-row">
        <div class="dock-row__head">
          <span :title="`DT 地址 ${pump.dtAddr} · ${pump.valve} 阀头`">{{ pump.label }}</span>
          <span class="dock-row__value">{{ pump.known ? `${pump.volumeMl.toFixed(2)} mL` : '—' }}</span>
        </div>
        <div v-if="pump.valvePorts" class="dock-row__foot">
          <span :title="`${pump.valve} 分配阀共 ${pump.valvePorts} 通`">
            阀位 {{ pump.valvePort ? `第 ${pump.valvePort} 口` : '—' }}
          </span>
        </div>
        <!-- 在途相位读数: 时长按 PLC 的 V(步/秒) 与 M(ms) 换算, 与实机 1:1 -->
        <div v-if="pump.phase" class="dock-row__foot">
          <span :title="`相位 ${pump.phase.index}/${pump.phase.count} · 目标 ${pump.phase.targetMl.toFixed(2)} mL`">
            {{ pumpPhaseText(pump.phase) }}
          </span>
          <span v-if="pump.phase.remainS !== null" class="dock-row__value">
            剩 {{ pump.phase.remainS < 1 ? '<1' : pump.phase.remainS.toFixed(0) }} s
          </span>
        </div>
        <div class="dock-bar">
          <div class="dock-bar__fill" :style="{ width: pump.known ? `${(pump.level * 100).toFixed(1)}%` : '0%' }" />
        </div>
        <div class="dock-row__foot">
          <span>
            {{ pump.known ? `柱塞 ${pump.plungerMm.toFixed(1)} mm` : '位置未知' }} / {{ pumpStrokeMm }} mm
          </span>
          <span
            class="dock-tag"
            :title="pump.stale
              ? '实时流已断, 冻结在末态'
              : pump.known
                ? '按动作参数包络估算 —— 泵没有任何位置反馈通道'
                : '冷启动或断线重连后位置不可信, 待下一次初始化(Z 归零)或动作'"
          >{{ pump.stale ? '已冻结' : pump.known ? '估算值' : '未知' }}</span>
          <span v-if="!pump.rigged" class="dock-tag">模型未装配</span>
        </div>
      </div>
    </section>

    <section v-if="tanks.length" class="dock-section">
      <h3 class="dock-h3">
        展缸（{{ tanks.length }}）
        <span class="dock-h3__sub">盖 {{ lidTotals.text }}</span>
      </h3>
      <div class="sst__tanks" :class="{ 'sst__tanks--liquid': hasLiquid }">
        <div v-for="tank in tanks" :key="tank.id" class="sst__tank">
          <span class="sst__swatch" :style="{ background: tank.color }" />
          <span class="sst__tank-name">{{ tank.label }}</span>
          <!-- 盖开/关: 来自气缸双端磁性开关, 与三维里盖的升降同一路信号 -->
          <span
            v-if="tank.lid"
            class="sst__lid"
            :class="`sst__lid--${tank.lid.tone}`"
            :title="tank.lid.estimated
              ? `${tank.lidMechanismId}: 已下令但磁性开关未确认到位`
              : `${tank.lidMechanismId}: 磁性开关确认`"
          >{{ tank.lid.label }}</span>
          <span v-else class="sst__lid sst__lid--stale" title="manifest 未声明该缸的盖气缸">盖 —</span>
          <span class="sst__tank-state">{{ tank.stateLabel }}</span>
          <template v-if="hasLiquid">
            <span
              class="sst__tank-bar"
              role="img"
              :aria-label="`液量 ${tank.volumeMl.toFixed(1)} 毫升，占溶液槽 ${tank.fillPercent}`"
              :title="`${tank.volumeMl.toFixed(1)} / ${tankCapacityMl.toFixed(1)} mL`"
            >
              <span class="sst__tank-bar-fill"
                    :style="{ width: tank.fillPercent, background: tank.color }" />
            </span>
            <span class="sst__tank-ml">{{ tank.volumeMl.toFixed(1) }} mL</span>
          </template>
        </div>
      </div>
    </section>

    <!-- 原始字段(工程师)区已按用户要求删除(2026-08-14): 三维实时页面向操作员,
         裸镜像字段的完整视图在二维设备页仍有。statusRows 的 engineer 桶照算不显 ——
         开放世界测试守的是"每个后端键都被登记归档", 不是"都要显示"。 -->
  </div>
</template>

<style scoped>
.sst {
  display: flex;
  flex-direction: column;
}

.sst__headline {
  margin: 0;
  /* 它的"显大"来自字重与内距, 不是字号 —— 500/7px 让它压得住阵又不喧宾夺主 */
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.55;
  border-left: 3px solid var(--border);
}

.sst__headline.is-ok { color: var(--ok); border-left-color: var(--ok); }
.sst__headline.is-busy { color: var(--accent-bright); border-left-color: var(--accent); }
.sst__headline.is-warn { color: var(--warn); border-left-color: var(--warn); }
.sst__headline.is-bad { color: var(--err-bright); border-left-color: var(--err); }
.sst__headline.is-muted { color: var(--text-dim); }

/* 末端工具声明区(仅机械臂) */
.sst__tool-edit {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 4px;
}

.sst__tool-select {
  flex: 1;
  min-width: 0;
  padding: 3px 6px;
  font-size: 11px;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 5px;
}

.sst__tool-note {
  margin: 4px 0 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-dim);
}

.sst__tool-msg {
  margin: 4px 0 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
}

.sst__tanks {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 10px;
}

/* 带液位条时收成单列: 半宽格子塞不下 色块+缸号+盖+状态+液位条+mL */
.sst__tanks--liquid {
  grid-template-columns: 1fr;
}

.sst__tank {
  display: flex;
  gap: 6px;
  align-items: center;
}

.sst__swatch {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 2px;
}

.sst__tank-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sst__tank-state {
  color: var(--text-dim);
}

/* 盖开/关徽标: 开=琥珀(留意缸口敞着), 关=绿, 断流/未知=灰 */
.sst__lid {
  flex: none;
  min-width: 34px;
  padding: 0 5px;
  font-size: 10px;
  line-height: 15px;
  text-align: center;
  border: 1px solid transparent;
  border-radius: 7px;
}

.sst__lid--closed {
  color: var(--ok, #39d98a);
  background: color-mix(in srgb, var(--ok, #39d98a) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok, #39d98a) 45%, transparent);
}

.sst__lid--open {
  color: var(--warn, #f4b740);
  background: color-mix(in srgb, var(--warn, #f4b740) 12%, transparent);
  border-color: color-mix(in srgb, var(--warn, #f4b740) 45%, transparent);
}

.sst__lid--stale {
  color: var(--text-dim);
  border-color: var(--hair);
}

.sst__tank-bar {
  flex: none;
  width: 56px;
  height: 6px;
  margin-left: auto;
  overflow: hidden;
  background: var(--surface-sunken, rgb(255 255 255 / 8%));
  border-radius: 3px;
}

.sst__tank-bar-fill {
  display: block;
  height: 100%;
  border-radius: 3px;
  transition: width 220ms ease-out;
}

.sst__tank-ml {
  flex: none;
  min-width: 52px;
  color: var(--text-dim);
  text-align: right;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  .sst__tank-bar-fill { transition: none; }
}
</style>
