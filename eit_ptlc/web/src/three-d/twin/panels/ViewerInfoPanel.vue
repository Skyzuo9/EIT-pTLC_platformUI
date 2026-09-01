<script setup>
/**
 * 功能: 右侧信息坞的「显示信息」页 —— 只讲**渲染器**的事.
 *
 * 与「工站信息」页严格分家: 帧率/绘制调用/三角形说的是这台电脑画得多快, 轴反馈/机构反馈
 * 说的是那台设备在干什么. 旧 HUD 把两类挤在同一个 <dl> 里, 于是"48 fps"和"11/11 轴"
 * 并排出现, 读的人得自己分辨哪个是设备哪个是画面.
 *
 * 只读: 调光/阴影/效果那些**设置**仍在 DisplayPanel 弹层里, 这里不重复一套入口.
 */
import { computed } from 'vue'

const props = defineProps({
  /** 运行时指标 */
  stats: { type: Object, default: () => ({}) },
  /** 模型信息(加载耗时/整机尺寸) */
  modelInfo: { type: Object, default: null },
})

const QUALITY_LABEL = { high: '高', medium: '中', low: '低', lite: '精简' }

const fpsTone = computed(() => {
  const fps = props.stats?.fps || 0
  if (fps >= 45) return 'ok'
  if (fps >= 25) return 'warn'
  return 'bad'
})

/**
 * 功能: 千分位格式化.
 * @param {number} value 数值
 * @returns {string} 格式化结果
 */
function formatNumber(value) {
  return Number(value || 0).toLocaleString('zh-CN')
}
</script>

<template>
  <section class="vip">
    <h3 class="vip__h3">画面</h3>
    <dl class="vip__metrics">
      <div class="vip__metric">
        <dt>帧率</dt>
        <dd :class="fpsTone">{{ stats.fps || 0 }} fps</dd>
      </div>
      <div class="vip__metric">
        <dt>画质档</dt>
        <dd>{{ QUALITY_LABEL[stats.quality] || stats.quality || '—' }}</dd>
      </div>
      <div class="vip__metric">
        <dt>绘制调用</dt>
        <dd>{{ formatNumber(stats.drawCalls) }}</dd>
      </div>
      <div class="vip__metric">
        <dt>三角形</dt>
        <dd>{{ formatNumber(stats.triangles) }}</dd>
      </div>
    </dl>

    <h3 class="vip__h3">模型</h3>
    <dl class="vip__metrics">
      <div v-if="modelInfo" class="vip__metric">
        <dt>加载耗时</dt>
        <dd>{{ (modelInfo.loadMs / 1000).toFixed(1) }} s</dd>
      </div>
      <div v-if="modelInfo?.sizeM?.size" class="vip__metric">
        <dt>整机尺寸</dt>
        <dd>{{ modelInfo.sizeM.size.join(' × ') }} m</dd>
      </div>
    </dl>

    <p class="vip__hint">
      卡顿时画质会自动降档; 低档没有选中描边, 那时靠工位列表高亮与页签指示当前选中。
      光源/阴影/效果的调整在工具栏的「显示」里。
    </p>
  </section>
</template>

<style scoped>
.vip {
  display: grid;
  gap: 6px;
  padding: 10px 12px;
  font-size: 12px;
}

.vip__h3 {
  margin: 6px 0 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-dim);
}

.vip__h3:first-child {
  margin-top: 0;
}

.vip__metrics {
  display: grid;
  gap: 3px;
  margin: 0;
}

.vip__metric {
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.vip__metric dt {
  color: var(--text-dim);
}

.vip__metric dd {
  margin: 0;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.vip__metric dd.ok { color: var(--ok); }
.vip__metric dd.warn { color: var(--warn); }
.vip__metric dd.bad { color: var(--err); }

.vip__hint {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-dim);
}
</style>
