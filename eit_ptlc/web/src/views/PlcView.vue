<script setup>
// PLC 程序编辑 (中区): /plc 空态 | /plc/pou/:path POU 编辑 (主体=声明+实现双区, 右=编译/工程面板)。
// 运行时控制各归其位: 执行→「动作」页, 工位状态+复位→「设备」页 (不在此重复)。
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useDirtyGuard } from '../composables/useDirtyGuard.js'
import { usePlcStore } from '../stores/plc'
import { useLayoutStore } from '../stores/layout'
import PouEditor from '../components/plc/PouEditor.vue'
import CompilePanel from '../components/plc/CompilePanel.vue'
import PlcVersionPanel from '../components/plc/PlcVersionPanel.vue'
import Splitter from '../components/Splitter.vue'

const route = useRoute()
const plc = usePlcStore()
const layout = useLayoutStore()

// POU 未保存守卫 (dirty 真源在 store, 仅「保存到工程」清除): 换 :path、离开 /plc、刷新三口全拦。
// 载入的 try/catch 与加载/错误态同样在 store.loadPou (loadingPou/pouError), 由 PouEditor 展示, 此处不重复。
useDirtyGuard(() => plc.dirty, { message: '当前 POU 有未保存修改, 离开将丢弃。', paramKey: 'path' })

// 切换选中 POU: 载入其声明/实现 (route.params.path 为含斜杠的整段路径)
watch(() => route.params.path, (p) => {
  if (p) {
    plc.loadPou(p)
  }
}, { immediate: true })
</script>

<template>
  <div class="plc-page" :style="{ '--plc-right-w': layout.sizes.plcRightW + 'px' }">
    <div class="plc-main">
      <PouEditor />
    </div>
    <aside class="plc-right">
      <CompilePanel />
      <PlcVersionPanel />
    </aside>
    <!-- 主体↔右栏 竖向 (右栏在右 → sign=-1), 照 action-page 的 seam 写法 -->
    <Splitter skey="plcRightW" dir="x" :sign="-1" class="seam-plc-v" />
  </div>
</template>

<style scoped>
.plc-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--plc-right-w, 360px);
  grid-template-rows: minmax(0, 1fr);
  gap: 10px;
  height: 100%;
  position: relative;
}
.plc-main { grid-row: 1; grid-column: 1; min-width: 0; min-height: 0; overflow: auto; }
.plc-right { grid-row: 1; grid-column: 2; min-width: 0; overflow: auto; border-left: 1px solid var(--border); padding-left: 10px; }
/* 分隔条与右栏同格重叠, 落进两列 10px 缝 (照 .seam-action-v) */
.seam-plc-v { grid-row: 1; grid-column: 2; justify-self: start; align-self: stretch; width: 10px; margin-left: -10px; }
</style>
