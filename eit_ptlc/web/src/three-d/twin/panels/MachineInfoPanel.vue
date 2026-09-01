<script setup>
/**
 * 功能: 右侧信息坞的「工站信息」页 —— 只讲**设备**的事: 反馈完整度 + 只读实时诊断.
 *
 * 从旧 TwinHud 的指标区与 <details 只读实时诊断> 原样搬来, 与「显示信息」页分家
 * (那边是渲染器的事). 搬家时唯一的实质改动是: 整栏由坞自己滚, 各段仍保留自己的
 * 180px 上限 + 吸顶小标题, 于是不会出现"一段长表把另外三段挤出视口"。
 *
 * 整机级操作(单点会话 / 一键回原点 / 停机 / 恢复)也在这一页底部 —— 它们不属于任何单一
 * 工位, 而工位「操作」页只管本工位那几行.
 */
import { computed } from 'vue'

import { lidSummary, tankLidRows } from '../lidStatus.js'

const props = defineProps({
  /** manifest 内容 */
  manifest: { type: Object, default: null },
  /** manifest 装配完成度摘要 */
  summary: { type: Object, default: null },
  /** 高频机器人/轴/机构数据健康度 */
  realtime: { type: Object, default: () => ({}) },
  /** 上位机物料账本同步状态 */
  materials: { type: Object, default: () => ({}) },
})

/**
 * 功能: 把可能缺失的运动量格式化成定宽数字.
 * @param {number} value 数值
 * @param {string} suffix 单位后缀
 * @returns {string} 显示文本
 */
function formatMotionValue(value, suffix = '') {
  return Number.isFinite(value) ? `${value.toFixed(2)}${suffix}` : '—'
}

/**
 * 功能: 机构有效态的三值显示(ON/OFF/未知).
 * @param {object} item 机构行
 * @returns {string} 显示文本
 */
function mechanismValue(item) {
  if (typeof item.effective !== 'boolean') return '—'
  return item.effective ? 'ON' : 'OFF'
}

/** 末端工具的中文说明; 控制器报了 manifest 没声明的刀时如实写出来, 不装作正常。 */
const toolText = computed(() => {
  const tool = props.realtime?.tool
  if (!tool || !Number.isFinite(Number(tool.controllerTool))) return '—'
  if (tool.declared === false) return `控制器 ${tool.controllerTool} 号，模型无此工具`
  return tool.label || tool.id || '—'
})

/** 展缸盖开/关汇总; manifest 没声明盖气缸(旧产物)时整条不显示 */
const lidTotals = computed(() => {
  const tanks = (props.manifest?.tanks || []).filter((tank) => tank.lidMechanismId)
  if (!tanks.length) return null
  return lidSummary(tankLidRows(tanks, props.realtime?.mechanisms?.items || []))
})
</script>

<template>
  <section class="mip">
    <h3 class="mip__h3">反馈完整度</h3>
    <dl class="mip__metrics">
      <div v-if="summary" class="mip__metric">
        <dt>已装配轴</dt>
        <dd>{{ summary.axesRigged }} / {{ summary.axes }}</dd>
      </div>
      <div class="mip__metric">
        <dt>机器人反馈</dt>
        <dd :class="realtime?.robot?.stale ? 'warn' : 'ok'">
          {{ realtime?.robot?.available ? (realtime.robot.stale ? '已冻结' : '实时') : '—' }}
        </dd>
      </div>
      <div class="mip__metric">
        <dt>轴反馈</dt>
        <dd>{{ realtime?.axes?.known || 0 }} / {{ realtime?.axes?.total || 0 }}</dd>
      </div>
      <div class="mip__metric">
        <dt>机构反馈</dt>
        <dd>{{ realtime?.mechanisms?.known || 0 }} / {{ realtime?.mechanisms?.total || 0 }}</dd>
      </div>
      <!-- 展缸盖: 不点开工位也能一眼看到几个缸敞着(缸口敞开时不能放板) -->
      <div v-if="lidTotals" class="mip__metric">
        <dt>展缸盖</dt>
        <dd :class="lidTotals.open ? 'warn' : 'ok'">{{ lidTotals.text }}</dd>
      </div>
      <!-- 注射泵: 永远给 warn 而不是 ok —— 柱塞位置没有任何传感器确认, 标 ok 就是骗人 -->
      <div v-if="realtime?.pumps?.total" class="mip__metric">
        <dt>注射泵</dt>
        <dd :class="realtime.pumps.stale ? 'bad' : 'warn'">
          {{ realtime.pumps.known }} / {{ realtime.pumps.total }} · 估算值
        </dd>
      </div>
      <div class="mip__metric">
        <dt>物料账本</dt>
        <dd :class="materials?.stale ? 'warn' : 'ok'">
          {{ materials?.available ? (materials.stale ? '已冻结' : '已同步') : '—' }}
        </dd>
      </div>
    </dl>

    <details class="mip__diag">
      <summary>只读实时诊断</summary>

      <section>
        <h4>末端工具</h4>
        <div class="mip__row mip__row--tool">
          <span>Tool {{ realtime?.tool?.controllerTool ?? '—' }}</span>
          <span :title="toolText">{{ toolText }}</span>
          <em :class="realtime?.tool?.declared === false ? 'bad' : realtime?.tool?.stale ? 'warn' : 'ok'">
            {{ realtime?.tool?.declared === false ? '模型未声明' : realtime?.tool?.stale ? '已冻结' : '正常' }}
          </em>
        </div>
      </section>

      <section>
        <h4>PLC 轴（{{ realtime?.axes?.known || 0 }}/{{ realtime?.axes?.total || 0 }}）</h4>
        <div v-for="item in realtime?.axes?.items || []" :key="item.id" class="mip__row">
          <span :title="item.label">{{ item.id }}</span>
          <span>{{ formatMotionValue(item.position, ' mm') }}</span>
          <span>{{ formatMotionValue(item.velocity, ' mm/s') }}</span>
          <em :class="item.stale ? 'bad' : item.rigged ? 'ok' : 'warn'">
            {{ item.stale ? '已冻结' : item.rigged ? '已装配' : '仅数据' }}
          </em>
        </div>
      </section>

      <section>
        <h4>机构（{{ realtime?.mechanisms?.known || 0 }}/{{ realtime?.mechanisms?.total || 0 }}）</h4>
        <div
          v-for="item in realtime?.mechanisms?.items || []"
          :key="item.id"
          class="mip__row mip__row--mech"
        >
          <span :title="item.label">{{ item.id }}</span>
          <span>{{ mechanismValue(item) }}</span>
          <span>{{ item.estimated ? '推定' : '已确认' }}</span>
          <em :class="item.stale ? 'bad' : item.estimated ? 'warn' : 'ok'">
            {{ item.stale ? '已冻结' : item.rigged ? '已装配' : '仅数据' }}
          </em>
        </div>
      </section>

      <section v-if="realtime?.pumps?.total">
        <h4>注射泵（{{ realtime.pumps.known }}/{{ realtime.pumps.total }}）</h4>
        <div v-for="item in realtime.pumps.items" :key="item.id" class="mip__row mip__row--mech">
          <span :title="`${item.label} · DT ${item.dtAddr} · ${item.valve} 阀头`">{{ item.id }}</span>
          <span>{{ item.known ? `${item.volumeMl.toFixed(2)} mL` : '—' }}</span>
          <!-- 恒为估算: 柱塞位置全程无反馈, 只能按动作参数包络估算 -->
          <span>估算</span>
          <!-- 这一列**永远不给"正常"**: 本页"正常"的含义是"有确认过的反馈", 泵拿不到 -->
          <em :class="item.stale || !item.known ? 'bad' : 'warn'">
            {{ item.stale ? '已冻结' : !item.known ? '未知' : item.rigged ? '已装配' : '仅数据' }}
          </em>
        </div>
      </section>
    </details>

    <!-- 整机操作(单点会话/回原点/停机/恢复)由宿主经插槽注入 —— 它要 ManualSession,
         而会话是页面级的一份, 不该由这个纯展示面板去持有 -->
    <slot name="machine-ops" />
  </section>
</template>

<style scoped>
.mip {
  display: grid;
  gap: 8px;
  padding: 10px 12px;
  font-size: 12px;
}

.mip__h3 {
  margin: 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
}

.mip__metrics {
  display: grid;
  gap: 3px;
  margin: 0;
}

.mip__metric {
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.mip__metric dt { color: var(--text-dim); }
.mip__metric dd {
  margin: 0;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.mip__metric dd.ok { color: var(--ok); }
.mip__metric dd.warn { color: var(--warn); }
.mip__metric dd.bad { color: var(--err); }

.mip__diag {
  padding-top: 6px;
  color: var(--text-dim);
  border-top: 1px solid var(--border);
}

.mip__diag summary {
  color: var(--text);
  cursor: pointer;
}

/* 各段自持上限 + 吸顶小标题: 一段长表不会把另外三段挤出视口(整栏还有坞的滚动兜底) */
.mip__diag section {
  max-height: 180px;
  margin-top: 8px;
  overflow: auto;
  scrollbar-width: thin;
}

.mip__diag h4 {
  position: sticky;
  top: 0;
  margin: 0 0 4px;
  padding: 2px 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
  background: var(--surface-soft);
}

.mip__row {
  display: grid;
  grid-template-columns: minmax(64px, 1fr) auto auto auto;
  gap: 6px;
  align-items: center;
  padding: 2px 0;
  font-variant-numeric: tabular-nums;
}

/* 末端工具只有三格(工具号 / 名称 / 状态), 名称占满中间避免右侧留空 */
.mip__row--tool {
  grid-template-columns: auto minmax(64px, 1fr) auto;
}

.mip__row--tool > span:nth-child(2),
.mip__row > span:first-child {
  overflow: hidden;
  color: var(--text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mip__row em { font-style: normal; }
.mip__row em.ok { color: var(--ok); }
.mip__row em.warn { color: var(--warn); }
.mip__row em.bad { color: var(--err); }
</style>
