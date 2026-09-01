<script setup>
/**
 * 功能: 执行器/联动组的运动学参数编辑卡 —— 改完即预览, 攒够了统一写回 rig_map.
 *
 * v1 可编辑面收敛到数值参数(sign/outputRange/transitionS): spec 与驱动层是同对象
 * 引用, 改完重放当前值立即可见; 成员 node 改选、attach/mount 调参是 v2(会破坏
 * 标定可复现性, 见方案).
 */
import { computed } from 'vue'

import { primaryParam, solveLift } from './linkageKinematics.js'

const props = defineProps({
  /** classifySemantics 条目(kind = actuator | linkage) */
  entry: { type: Object, required: true },
  /** 当前生效的 spec 值(宿主从驱动层 spec 现值取) */
  live: { type: Object, default: () => ({}) },
  /** 是否有未写回的改动 */
  dirty: { type: Boolean, default: false },
})

const emit = defineEmits(['change'])

const isActuator = computed(() => props.entry.kind === 'actuator')

/**
 * 带耦合约束的机构(展缸盖): 成员行程被几何锁死, 只暴露一个主参数.
 * 分别调各成员会让盖与摆臂脱节(连接处错位), 所以这里整段替换掉行程编辑.
 */
const coupled = computed(() => primaryParam(props.live.kinematics))

/** 主参数当前值解出的从动量(只读展示, 让用户看清联动关系) */
const derived = computed(() => {
  const kin = props.live.kinematics
  if (!coupled.value || !kin) return null
  try {
    return solveLift(kin, Number(kin.liftMm))
  } catch {
    return null
  }
})

/** 输出行程的单位: 执行器看自己的 motion, 联动组看首成员(rotate 是度不是 mm) */
const outputUnit = computed(() => {
  const motion = isActuator.value ? props.live.motion : props.live.memberMotion
  return motion === 'rotate' || motion === 'rotary' ? '(°)' : '(mm)'
})

/**
 * 功能: 提交一个参数变更.
 * @param {string} key 参数名(sign/outputMin/outputMax/transitionS/liftMm)
 * @param {*} value 值
 * @returns {void}
 */
function change(key, value) {
  const num = Number(value)
  if (!Number.isFinite(num)) return
  if (key === 'outputMin' || key === 'outputMax') {
    const range = [...(props.live.outputRange || [0, 1])]
    range[key === 'outputMin' ? 0 : 1] = num
    emit('change', props.entry, 'outputRange', range)
    return
  }
  emit('change', props.entry, key, num)
}
</script>

<template>
  <div class="rp">
    <header class="rp__head">
      <span>运动参数</span>
      <span v-if="dirty" class="rp__dirty" title="有未写回 rig_map 的改动">未写回</span>
    </header>

    <div v-if="isActuator" class="rp__row">
      <label>方向 sign</label>
      <select :value="live.sign ?? 1" @change="change('sign', $event.target.value)">
        <option :value="1">+1</option>
        <option :value="-1">-1</option>
      </select>
    </div>

    <!-- 耦合机构: 只给主参数, 从动量只读展示(分别调会让机构脱节) -->
    <template v-if="coupled">
      <div class="rp__row">
        <label>{{ coupled.label }} ({{ coupled.unit }})</label>
        <input
          type="number"
          :step="coupled.step"
          :min="coupled.min"
          :max="coupled.max"
          :value="live.kinematics?.liftMm ?? 0"
          @change="change('liftMm', $event.target.value)"
        />
        <span class="rp__lim">≤ {{ coupled.max.toFixed(0) }}</span>
      </div>
      <p v-if="derived" class="rp__derived">
        联动解算：摆臂 {{ derived.thetaDeg.toFixed(1) }}° · 滑车
        {{ derived.travelMm.toFixed(1) }}mm（由抬升唯一确定，不可分别调）
      </p>
    </template>

    <div v-else class="rp__row">
      <label>输出行程 {{ outputUnit }}</label>
      <input
        type="number"
        step="0.5"
        :value="live.outputRange?.[0] ?? 0"
        @change="change('outputMin', $event.target.value)"
      />
      <span class="rp__tilde">~</span>
      <input
        type="number"
        step="0.5"
        :value="live.outputRange?.[1] ?? 1"
        @change="change('outputMax', $event.target.value)"
      />
    </div>

    <div class="rp__row">
      <label>过渡时长 (s)</label>
      <input
        type="number"
        step="0.05"
        min="0"
        :value="live.transitionS ?? 0.3"
        @change="change('transitionS', $event.target.value)"
      />
    </div>

    <p class="rp__hint">
      改完立即预览（拖上方 0↔1 滑杆看效果）；「写回 rig_map」在左栏底部，
      写回后重跑 manifest 即固化。成员节点改选属 v2。
    </p>
  </div>
</template>

<style scoped>
.rp {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  margin-top: 8px;
  border-top: 1px dashed var(--hair);
}

.rp__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-bright);
}

.rp__dirty {
  padding: 0 6px;
  font-size: 9px;
  font-weight: 400;
  color: var(--warn);
  background: var(--warn-soft);
  border-radius: 7px;
}

.rp__row {
  display: flex;
  gap: 6px;
  align-items: center;
  font-size: 11px;
  color: var(--text-mid);
}

.rp__row label {
  flex: none;
  width: 92px;
}

.rp__row input,
.rp__row select {
  width: 64px;
  padding: 2px 5px;
  font-size: 11px;
  color: var(--text);
  background: var(--well, var(--surface));
  border: 1px solid var(--hair);
  border-radius: 4px;
}

.rp__tilde { color: var(--text-dim); }

.rp__lim {
  font-size: 10px;
  color: var(--text-dim);
}

.rp__derived {
  margin: 0;
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-mid);
}

.rp__hint {
  margin: 0;
  font-size: 10px;
  line-height: 1.6;
  color: var(--text-dim);
}
</style>
