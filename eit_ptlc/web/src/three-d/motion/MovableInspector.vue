<script setup>
/**
 * 功能: 选中可动件的调试卡 —— 按 kind 生成对应的滑杆/步进/开合控件.
 *
 * 纯展示组件: 一切驱动都 emit 给宿主(MotionView), 由宿主走 MachineStateDriver
 * (唯一状态写入层). 支持四类:
 *   axis      mm 滑杆 + ±0.1/1/10 步进(rangeMm 内, clamp 由 setAxisMm 兜底)
 *   joint     deg 滑杆(limitDeg 内)
 *   actuator/linkage  0..1 滑杆 + 「0 基准位 / 1 DO2 激活」按钮
 *   tool      锁紧(挂到法兰)/释放(回停靠位)演示
 * declared-only 条目显示"待装配"说明.
 */
import { computed, ref, watch } from 'vue'

const props = defineProps({
  /** classifySemantics 条目 */
  entry: { type: Object, required: true },
  /** 当前值(轴=mm, 关节=deg, 执行器/联动=0..1); null 表示未知 */
  current: { type: Number, default: null },
  /** 轴条目专属: 驱动层现行轴向量(glTF 系)与符号 —— 运动方向选择器的数据源 */
  axisDir: { type: Array, default: null },
  axisSign: { type: Number, default: 1 },
  /** 轴向相对已固化值有未写回的改动 */
  dirDirty: { type: Boolean, default: false },
  /** 授权中间件可用(写回按钮的前提) */
  canWrite: { type: Boolean, default: false },
})

const emit = defineEmits(['axis-mm', 'joint-deg', 'motion-value', 'tool-action', 'axis-dir', 'axis-dir-save'])

/**
 * 运动方向候选: 值 = mm 增大时滑车在世界系里移动的方向.
 * 前后以"面向机器正面"为参照(glTF +Z 朝向默认机位).
 */
const DIRECTIONS = [
  { key: '+x', label: '向右(+X)', axis: [1, 0, 0], sign: 1 },
  { key: '-x', label: '向左(−X)', axis: [1, 0, 0], sign: -1 },
  { key: '+y', label: '向上(+Y)', axis: [0, 1, 0], sign: 1 },
  { key: '-y', label: '向下(−Y)', axis: [0, 1, 0], sign: -1 },
  { key: '+z', label: '向前(+Z)', axis: [0, 0, 1], sign: 1 },
  { key: '-z', label: '向后(−Z)', axis: [0, 0, 1], sign: -1 },
]

/** 现行 (axis, sign) 对应的候选 key; 非轴对齐向量返回 '' (显示"自定义") */
const dirKey = computed(() => {
  const dir = props.axisDir
  if (!Array.isArray(dir) || dir.length !== 3) return ''
  return matchDirKey(dir, props.axisSign)
})

/**
 * 功能: (axis, sign) -> 候选 key. 轴向量分量含负数时折算进符号.
 * @param {number[]} dir 轴向量
 * @param {number} sign 符号
 * @returns {string} key 或 ''
 */
function matchDirKey(dir, sign) {
  const idx = dir.findIndex((v) => Math.abs(Number(v)) > 1e-6)
  if (idx < 0) return ''
  for (let k = 0; k < 3; k += 1) {
    if (k !== idx && Math.abs(Number(dir[k])) > 1e-6) return ''
  }
  const total = Math.sign(Number(dir[idx])) * (Number(sign) >= 0 ? 1 : -1)
  const key = `${total > 0 ? '+' : '-'}${'xyz'[idx]}`
  return DIRECTIONS.some((option) => option.key === key) ? key : ''
}

/**
 * 功能: 选择器变更 -> 上抛新方向(宿主立即预览).
 * @param {string} key 候选 key
 * @returns {void}
 */
function pickDir(key) {
  const option = DIRECTIONS.find((item) => item.key === key)
  if (!option) return
  emit('axis-dir', props.entry.params.axisId, { axis: [...option.axis], sign: option.sign })
}

/** 本地滑杆值(条目/外部值变化时重置) */
const local = ref(0)

watch(
  () => [props.entry?.id, props.current],
  () => {
    local.value = Number.isFinite(props.current) ? props.current : defaultValue()
  },
  { immediate: true },
)

/**
 * 功能: 条目的缺省值(未知时落在行程起点/零位).
 * @returns {number} 值
 */
function defaultValue() {
  const { kind, params } = props.entry
  if (kind === 'axis') return Number(params.rangeMm?.[0] ?? 0)
  return 0
}

/**
 * 功能: 滑杆边界.
 * @returns {{min: number, max: number, step: number, unit: string}} 边界
 */
function bounds() {
  const { kind, params } = props.entry
  if (kind === 'axis') {
    const [min, max] = params.rangeMm || [0, 100]
    return { min, max, step: 0.5, unit: 'mm' }
  }
  if (kind === 'joint') {
    const [min, max] = params.limitDeg || [-180, 180]
    return { min: Math.max(min, -360), max: Math.min(max, 360), step: 1, unit: '°' }
  }
  return { min: 0, max: 1, step: 0.01, unit: '' }
}

/**
 * 功能: 写一个新值(滑杆/步进共用出口).
 * @param {number} value 新值
 * @returns {void}
 */
function commit(value) {
  const box = bounds()
  const next = Math.min(box.max, Math.max(box.min, Number(value)))
  local.value = next
  const { kind, params } = props.entry
  if (kind === 'axis') emit('axis-mm', params.axisId, next)
  else if (kind === 'joint') emit('joint-deg', params.jointIndex, next)
  else emit('motion-value', props.entry, next)
}

/**
 * 功能: 步进按钮.
 * @param {number} delta 步长
 * @returns {void}
 */
function nudge(delta) {
  commit(Number(local.value) + delta)
}
</script>

<template>
  <div class="mi">
    <header class="mi__head">
      <span class="mi__title">{{ entry.label }}</span>
      <span class="mi__kind">{{ entry.kind }}</span>
    </header>

    <p v-if="entry.category === 'declared-only'" class="mi__hint">
      数据侧已声明但几何未绑定（待装配）。
      <template v-if="entry.kind === 'axis'">
        在下方「指认滑块成员」里选出随该轴移动的零件并写回 rig_map，重跑后即可驱动。
      </template>
    </p>

    <template v-else-if="entry.kind === 'axis' || entry.kind === 'joint'">
      <div class="mi__row">
        <input
          type="range"
          :min="bounds().min"
          :max="bounds().max"
          :step="bounds().step"
          :value="local"
          @input="commit($event.target.value)"
        />
        <span class="mi__val">{{ Number(local).toFixed(1) }}{{ bounds().unit }}</span>
      </div>
      <div v-if="entry.kind === 'axis'" class="mi__nudges">
        <button v-for="d in [-10, -1, -0.1]" :key="d" class="mi__btn" @click="nudge(d)">{{ d }}</button>
        <button v-for="d in [0.1, 1, 10]" :key="d" class="mi__btn" @click="nudge(d)">+{{ d }}</button>
      </div>
      <div v-if="entry.kind === 'axis'" class="mi__dir">
        <span class="mi__dirLabel">运动方向</span>
        <select class="mi__select" :value="dirKey" @change="pickDir($event.target.value)">
          <option v-if="!dirKey" value="" disabled>自定义向量</option>
          <option v-for="option in DIRECTIONS" :key="option.key" :value="option.key">
            {{ option.label }}
          </option>
        </select>
        <button
          v-if="dirDirty"
          class="mi__btn mi__btn--save"
          :disabled="!canWrite"
          :title="canWrite ? '写回 rig_map 并快速部署(仅 manifest, 秒级)' : '需要开发中间件(vite dev)'"
          @click="emit('axis-dir-save', entry.params.axisId)"
        >
          写回
        </button>
      </div>
      <p v-if="entry.kind === 'axis'" class="mi__meta">
        行程 {{ entry.params.rangeMm?.[0] }} ~ {{ entry.params.rangeMm?.[1] }} mm ·
        零点 {{ entry.params.zeroOffsetMm }} mm · 视口内可直接拖拽滑块组 ·
        运动方向 = 数值增大时滑车的移动朝向(选择后立即预览, 拖一下核对, 对了再写回)
      </p>
      <p v-else class="mi__meta">
        限位 {{ entry.params.limitDeg?.[0]?.toFixed?.(0) }}° ~ {{ entry.params.limitDeg?.[1]?.toFixed?.(0) }}°
      </p>
    </template>

    <template v-else-if="entry.kind === 'actuator' || entry.kind === 'linkage'">
      <div class="mi__row">
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          :value="local"
          @input="commit($event.target.value)"
        />
        <span class="mi__val">{{ Number(local).toFixed(2) }}</span>
      </div>
      <div class="mi__nudges">
        <button class="mi__btn" @click="commit(0)">0 · 基准位</button>
        <button class="mi__btn" @click="commit(1)">1 · DO2 激活</button>
      </div>
      <p class="mi__meta">
        <template v-if="entry.kind === 'actuator'">
          {{ entry.params.motion }} · 输出 {{ entry.params.outputRange?.join(' ~ ') }}
          {{ entry.params.motion === 'rotate' ? '°' : 'mm' }} · 过渡 {{ entry.params.transitionS }}s
        </template>
        <!-- 耦合机构(展缸盖): 成员行程被几何锁死, 报主参数而不是首成员的数 -->
        <template v-else-if="entry.params.kinematics">
          {{ entry.params.members?.length }} 成员 · 盖抬升
          {{ entry.params.kinematics.liftMm }}mm（摆臂 {{ entry.params.kinematics.thetaDeg }}° ·
          滑车 {{ entry.params.kinematics.travelMm }}mm 联动）· 过渡 {{ entry.params.transitionS }}s
        </template>
        <template v-else>
          {{ entry.params.members?.length }} 成员 · 首成员输出
          {{ entry.params.members?.[0]?.outputRange?.join(' ~ ') }}{{ entry.params.members?.[0]?.motion === 'rotate' ? '°' : 'mm' }} ·
          过渡 {{ entry.params.transitionS }}s
        </template>
      </p>
    </template>

    <template v-else-if="entry.kind === 'tool'">
      <div class="mi__nudges">
        <button class="mi__btn" @click="emit('tool-action', entry.params.toolId, 'lock')">
          锁紧（挂到法兰）
        </button>
        <button class="mi__btn" @click="emit('tool-action', entry.params.toolId, 'release')">
          释放（回停靠位）
        </button>
      </div>
      <p class="mi__meta">
        控制器刀号 {{ entry.params.controllerTool }} · 停靠 {{ entry.params.dockNode }} ·
        机械臂-夹爪联动 = 快换锁紧后场景图换父（attach），非同步动画
      </p>
    </template>

    <p v-else class="mi__hint">该条目当前只作展示。</p>
  </div>
</template>

<style scoped>
.mi {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.mi__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.mi__title {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-bright);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mi__kind {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.mi__row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mi__row input {
  flex: 1;
  accent-color: var(--accent);
}

.mi__val {
  flex: none;
  min-width: 56px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  text-align: right;
}

.mi__nudges {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.mi__btn {
  padding: 2px 8px;
  font-size: 11px;
  color: var(--text-mid);
  cursor: pointer;
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.mi__btn:hover {
  color: var(--text-bright);
  background: var(--control-hover);
}

.mi__meta,
.mi__hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-dim);
}

.mi__dir {
  display: flex;
  gap: 6px;
  align-items: center;
}

.mi__dirLabel {
  flex: none;
  font-size: 10px;
  color: var(--text-dim);
}

.mi__select {
  flex: 1;
  min-width: 0;
  padding: 2px 4px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 5px;
}

.mi__btn--save {
  color: var(--accent);
}

.mi__btn--save:disabled {
  color: var(--text-dim);
  cursor: not-allowed;
}
</style>
