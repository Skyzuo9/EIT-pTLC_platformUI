<script setup>
/**
 * 功能: 标定子页 —— 确定虚拟模型与实机信号的位置关系.
 *
 * 标的只有轴的三元组: sign(方向) / zero_offset_mm(零点) / range_mm(行程).
 * 闭环见 AxisCalibBoard 头注释: 接管 → jog 对齐 → 匹配零点 → 写回 rig_map 并秒级重跑.
 *
 * 本子页是三个子页里唯一接实时链的: 标定的判据就是"虚拟与实机目视重合", 没有实机
 * 反馈就无从标起。切走时 useLiveBindings.detach() 会先 clearHolds 再拆绑定 ——
 * 接管中的轴带着 hold 离场的话, 下次接回来 feed 仍写不进去, 表现是"三维不跟实机动"
 * 却毫无报错。
 *
 * 栏位与另两个子页一致(左栏 320px): 三个子页共用一块面板几何, 标定单独浮在右上角
 * 会与 ViewToolbar 抢 z 序, 且切子页时栏位左右横跳.
 */
import { computed, inject } from 'vue'

import AxisCalibBoard from '../../twin/panels/AxisCalibBoard.vue'

const ctx = inject('motionWorkbench')
const { manager, manifest, live, contractTick, refreshContract, setCalibDirty } = ctx

const connection = computed(() => live.connection.value)
const warnings = computed(() => live.warnings.value)

/**
 * 功能: 写回并重跑成功后, 换掉整块标定板.
 *
 * 必须整块重建而不是就地更新: AxisCalibBoard 在 setup 里一次性抓了驱动实例
 * (props.manager.bindings.machine)与进页快照(snapshotAxes), 热重载契约会把那个
 * 驱动实例 dispose 掉, 快照也不再是"当前盘上的值". 用 contractTick 做 key 让它
 * 随新契约重挂, 顺带把"改动 N"归零 —— 刚写回完, 零改动正是实情.
 * @returns {Promise<void>} 完成
 */
async function onRebuilt() {
  setCalibDirty(0)
  await refreshContract()
}
</script>

<template>
  <aside class="mw__left mw__left--tall">
    <!-- 连接状态: 标定依赖实机反馈, 断连时匹配不可用, 状态必须常显 -->
    <div class="cp__conn" :class="{ 'cp__conn--on': connection.connected }">
      <span class="cp__connDot" />
      {{ connection.connected
        ? '已连接上位机'
        : `未连接上位机${connection.lastError ? ` · ${connection.lastError}` : ''}` }}
    </div>

    <AxisCalibBoard
      v-if="manager && live.attached.value"
      :key="contractTick"
      :manager="manager"
      :manifest="manifest"
      :realtime="live.realtime.value"
      live
      @rebuilt="onRebuilt"
      @dirty="setCalibDirty"
    />

    <div v-if="warnings.length" class="cp__warnings">
      <p v-for="(warning, index) in warnings" :key="index">{{ warning }}</p>
    </div>
  </aside>
</template>

<style scoped>
/* 连接状态条: 左栏里的常规流式块(不再是浮层) */
.cp__conn {
  display: flex;
  flex: none;
  gap: 6px;
  align-items: center;
  padding: 5px 10px;
  font-size: 11px;
  color: var(--text-mid);
  background: var(--control);
  border: 1px solid var(--hair);
  border-radius: 14px;
}

.cp__connDot {
  flex: none;
  width: 8px;
  height: 8px;
  background: #d95757;
  border-radius: 50%;
}

.cp__conn--on .cp__connDot {
  background: var(--ok-bright, #39d98a);
}

.cp__warnings {
  flex: none;
  padding: 8px 10px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--warn);
  background: var(--warn-soft);
  border: 1px solid var(--warn-soft);
  border-radius: 8px;
}

.cp__warnings p {
  margin: 0;
}
</style>
