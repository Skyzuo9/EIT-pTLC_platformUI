<script setup>
// 右栏「版本历史」: .project 全量快照列表 (rev / 时间 / 已部署徽标 / 说明) + 手动打快照 + 下载 + 还原。
// 快照由「保存到工程」自动触发 (内容哈希去重), 部署成功后自动打部署标记; 本面板做查看/管理。
import { computed, ref } from 'vue'
import { api } from '../../api'
import { confirmAction } from '../../composables/confirmService.js'
import { usePlcStore } from '../../stores/plc'

const plc = usePlcStore()
const snapMsg = ref('')
const restoringRev = ref('')

// 新→旧排列; 放 computed 免得模板每次渲染都复制+反转一遍数组
const versionsDesc = computed(() => [...plc.versions].reverse())

async function doSnapshot() {
  await plc.snapshot(snapMsg.value)
  snapMsg.value = ''
}
async function doRestore(rev) {
  // 还原覆盖活动工程 + 停 worker, 不可轻率: danger-ack 强制勾选
  const ok = await confirmAction({
    level: 'danger-ack',
    title: '还原工程版本',
    message: `还原版本 ${rev} 将覆盖当前活动工程 (未保存的编辑会丢失), 并停止 InoProShop。`,
    ackText: '我已确认要覆盖当前活动工程',
    confirmText: '还原',
  })
  if (!ok) {
    return
  }
  restoringRev.value = rev
  try {
    await plc.restore(rev)
  } finally {
    restoringRev.value = ''
  }
}
function sizeMB(bytes) {
  return (Number(bytes || 0) / 1024 / 1024).toFixed(2)
}
</script>

<template>
  <div class="version-panel">
    <h4 class="col-title">版本历史 <span class="muted">({{ plc.versions.length }})</span></h4>

    <div class="snap-row">
      <input v-model="snapMsg" class="snap-input" placeholder="快照说明 (可空)" aria-label="快照说明" />
      <button class="mini" :disabled="!plc.connected || plc.versionsBusy" @click="doSnapshot()">打快照</button>
    </div>
    <p v-if="plc.versionMsg" class="save-msg" role="status">{{ plc.versionMsg }}</p>

    <p v-if="!plc.connected" class="muted">未连接 —— 连接后显示版本历史</p>
    <p v-else-if="!plc.versions.length" class="muted">暂无快照 —— 「保存到工程」会自动留档一版</p>

    <ul v-else class="ver-list">
      <li v-for="v in versionsDesc" :key="v.rev" class="ver-row">
        <div class="ver-head">
          <span class="rev">#{{ v.rev }}</span>
          <span v-if="v.deployed_at" class="badge dep" :title="'部署于 ' + v.deployed_at">已部署</span>
          <span class="ts">{{ v.ts }}</span>
        </div>
        <div v-if="v.message" class="ver-msg">{{ v.message }}</div>
        <div class="ver-actions">
          <span class="size">{{ sizeMB(v.size) }} MB</span>
          <a class="mini" :href="api.plcVersionDownloadUrl(v.rev)" download>下载</a>
          <button class="mini danger" :disabled="plc.versionsBusy" @click="doRestore(v.rev)">
            {{ restoringRev === v.rev ? '还原中…' : '还原' }}
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.version-panel { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border); }
.col-title { margin: 0 0 8px; font-size: var(--fs-13); color: var(--text); font-weight: 700; }
.muted { color: var(--muted); font-size: var(--fs-11); }
.snap-row { display: flex; gap: 6px; margin-bottom: 6px; }
.snap-input { flex: 1; min-width: 0; padding: 4px 8px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text); border-radius: 4px; font-size: var(--fs-12); }
.save-msg { font-family: var(--font-mono); font-size: var(--fs-12); margin: 4px 0; }
/* .mini 基础样式与 .mini.danger 描边红均走全局 (style.css), 此处只留状态修饰 */
.mini:disabled { opacity: 0.5; cursor: not-allowed; }
.ver-list { list-style: none; padding: 0; margin: 8px 0 0; max-height: 40vh; overflow: auto; }
.ver-row { padding: 6px 0; border-bottom: 1px solid var(--border); }
.ver-head { display: flex; gap: 8px; align-items: center; font-size: var(--fs-12); }
.ver-head .rev { font-weight: 700; font-family: var(--font-mono); }
.ver-head .ts { color: var(--muted); margin-left: auto; font-family: var(--font-mono); }
.badge.dep { font-size: 10px; padding: 1px 6px; border-radius: 999px; background: var(--ok); color: var(--on-accent); font-weight: 700; }
.ver-msg { font-size: var(--fs-12); color: var(--text); margin: 3px 0; word-break: break-word; }
.ver-actions { display: flex; gap: 8px; align-items: center; margin-top: 4px; }
.ver-actions .size { font-size: var(--fs-11); color: var(--muted); margin-right: auto; font-family: var(--font-mono); }
</style>
