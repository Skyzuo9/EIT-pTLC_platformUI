<script setup>
/**
 * 功能: 实时视图 —— 实时镜像上位机的一切状态, 并提供手动模式控制以人工核对虚实一致.
 *
 * 实时工作台固定使用宿主事件流和正式模型资源:
 *   - 始终 live(EventStream 常开), 不再有"脱机演示"分支;
 *   - 固定加载 official-cr5 资产(实时链早已全量走它, legacy machine.glb 只剩材质台在用);
 *   - 路由即组件边界, 不再需要 ShowView 时代的 twinKey 强制重建技巧.
 */
import TwinView from '../twin/TwinView.vue'
</script>

<template>
  <TwinView
    live
    manual-enabled
    model-url="/api/3d/assets/models/machine.official-cr5.glb"
    manifest-url="/api/3d/assets/models/device-manifest.official-cr5.json"
  />
</template>
