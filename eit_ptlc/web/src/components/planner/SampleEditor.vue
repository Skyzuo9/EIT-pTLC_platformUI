<script setup>
// 样品条 (排程页甘特上方): 横排紧凑卡片, 样品序 = FIFO 序 (左→右), 甘特因此吃满全宽。
// 流程来源是左 Dock 的「流程耗时」库: 在那里点一行即追加到这里选中的样品。
// 卡级/链级操作收进右键与 ⋯ 菜单 (ContextMenu); 链节点是序号胶囊 chip, 点击=开菜单
// (chip 太小塞不下二级按钮且 button 不能嵌 button; 触屏同走这条路径)。
import { computed, ref } from 'vue'
import { confirmAction } from '../../composables/confirmService.js'
import { usePlannerStore } from '../../stores/planner'
import { pressable } from '../../utils/a11y.js'
import { FALLBACK_DURATION_S, fmtDur } from '../../utils/planner.js'
import ContextMenu from '../ui/ContextMenu.vue'

const planner = usePlannerStore()
const menuRef = ref(null)

function opLabel(name) {
  const entry = planner.opIndex[name]
  return entry ? entry.label : name
}

// 链条目的耗时徽标: 按当前口径显示; 无历史则标估计值
function opBadge(name) {
  const entry = planner.opIndex[name]
  if (entry && entry.count > 0) {
    return fmtDur(planner.plan.settings.durationMode === 'last' ? entry.last_s : entry.avg_s)
  }
  return '估60s'
}

// 卡头 Σ 徽标: 链上按当前口径求和, 无历史节点按估计值计 (与排程算法的 fallback 一致)
function chainSum(s) {
  let sum = 0
  let est = false
  for (const name of s.chain) {
    const entry = planner.opIndex[name]
    if (entry && entry.count > 0) {
      sum += planner.plan.settings.durationMode === 'last' ? entry.last_s : entry.avg_s
    } else {
      sum += FALLBACK_DURATION_S
      est = true
    }
  }
  return (est ? '≈' : 'Σ') + ' ' + fmtDur(sum)
}

// 链条目是流程名字符串 (可重复), WeakMap 型 keyOf 不适用 (只收对象);
// 用「名字#第几次出现」作稳定 key: 重排不同名节点时 DOM/焦点跟着节点走,
// 同名重复项间的错配无感 (内容完全等价)。
const chainKeys = computed(() => {
  const out = {}
  for (const s of planner.plan.samples) {
    const seen = {}
    out[s.id] = s.chain.map((name) => name + '#' + (seen[name] = (seen[name] || 0) + 1))
  }
  return out
})

// 删样品连整条流程链: danger 确认 (菜单先关再弹, 不与 ContextMenu 叠层)
async function delSample(s) {
  if (!(await confirmAction({
    level: 'danger',
    title: '删除样品 ' + s.label,
    message: '其流程链一并删除。',
    confirmText: '删除',
  }))) return
  planner.removeSample(s.id)
}

async function delOp(s, oi, opName) {
  if (!(await confirmAction({
    title: '移除流程节点',
    message: `将从「${s.label}」的流程链移除「${opLabel(opName)}」。`,
    confirmText: '移除',
  }))) return
  planner.removeOp(s.id, oi)
}

// 名称 input 引用 (菜单「重命名」聚焦用); :ref 函数在卸载时以 null 调用
const nameInputs = ref({})
function setNameInput(id, el) {
  if (el) nameInputs.value[id] = el
  else delete nameInputs.value[id]
}

function openSampleMenu(ev, s, si) {
  menuRef.value?.open(ev, [
    { key: 'left', label: '← 左移 (FIFO 提前)', disabled: si === 0,
      onSelect: () => planner.moveSample(s.id, -1) },
    { key: 'right', label: '→ 右移', disabled: si === planner.plan.samples.length - 1,
      onSelect: () => planner.moveSample(s.id, 1) },
    { key: 'rename', label: '重命名',
      onSelect: () => { const el = nameInputs.value[s.id]; if (el) { el.focus(); el.select() } } },
    { key: 'del', label: '删除样品', variant: 'danger', onSelect: () => delSample(s) },
  ], s.label)
}

function openChipMenu(ev, s, oi) {
  const name = s.chain[oi]
  menuRef.value?.open(ev, [
    { key: 'fwd', label: '← 前移', disabled: oi === 0,
      onSelect: () => planner.moveOp(s.id, oi, -1) },
    { key: 'back', label: '→ 后移', disabled: oi === s.chain.length - 1,
      onSelect: () => planner.moveOp(s.id, oi, 1) },
    { key: 'detail', label: '明细 (步骤时间线)', onSelect: () => planner.openTimeline(name) },
    { key: 'rm', label: '移除', variant: 'danger', onSelect: () => delOp(s, oi, name) },
  ], `${s.label} · ${oi + 1}. ${opLabel(name)}`)
}
</script>

<template>
  <div class="sample-strip" data-test="sample-strip">
    <p v-if="!planner.plan.samples.length" class="strip-empty">
      点左侧「流程耗时」里的流程即可开始 (会自动建一个样品)
    </p>

    <!-- pressable: 卡片 div 内嵌次级控件 (button 不能嵌 button), 补按钮语义+键盘激活;
         内层控件 @keydown.stop —— 否则卡片层对 Enter/Space 的 preventDefault 会吞掉
         输入框的空格与内嵌按钮的键盘激活 -->
    <div v-for="(s, si) in planner.plan.samples" :key="s.id" class="s-card" data-test="sample-card"
         :class="{ selected: planner.selectedSampleId === s.id }"
         :aria-pressed="planner.selectedSampleId === s.id"
         title="点卡片选中: 左侧点流程会加到选中的样品"
         v-bind="pressable(() => planner.selectSample(s.id))"
         @contextmenu.prevent.stop="openSampleMenu($event, s, si)">
      <div class="card-head">
        <input :ref="(el) => setNameInput(s.id, el)" class="name" :value="s.label"
               title="样品名" aria-label="样品名"
               @click.stop @keydown.stop @change="planner.renameSample(s.id, $event.target.value)" />
        <small class="sum num" title="流程链总耗时 (按当前口径; ≈ 表示含估计值)">{{ chainSum(s) }}</small>
        <button type="button" class="row-more" aria-haspopup="menu" :aria-label="`样品操作: ${s.label}`"
                @click.stop="openSampleMenu($event, s, si)" @keydown.stop>⋯</button>
      </div>

      <ol class="chain" @keydown.stop>
        <li v-for="(opName, oi) in s.chain" :key="chainKeys[s.id][oi]">
          <button type="button" class="chip-op" aria-haspopup="menu"
                  :title="`${opLabel(opName)} —— 点击/右键: 前移·后移·明细·移除`"
                  @click.stop="openChipMenu($event, s, oi)"
                  @contextmenu.prevent.stop="openChipMenu($event, s, oi)">
            <span class="cl">{{ opLabel(opName) }}</span>
            <small class="badge">{{ opBadge(opName) }}</small>
          </button>
        </li>
        <li v-if="!s.chain.length" class="empty-chain">空链 —— 点左侧流程加入</li>
      </ol>
    </div>

    <button type="button" class="s-add" data-test="add-sample"
            @click="planner.addSample()">+ 添加样品</button>
  </div>

  <ContextMenu ref="menuRef" />
</template>

<style scoped>
/* 横排卡片条: 横向滚动 nowrap (样品序=FIFO 序, 一条线左→右可读); 高度封顶, 甘特吃剩余 */
.sample-strip { display: flex; gap: 8px; overflow-x: auto; flex: 0 0 auto; align-items: stretch; padding: 2px; }
.s-card { flex: 0 0 280px; max-height: 200px; display: flex; flex-direction: column; gap: 6px;
  border: 1px solid var(--border); border-radius: 8px; padding: 8px; cursor: pointer; }
/* 选中样品 = 左侧点流程的落点, 用左侧色条 + 强调边框标出 */
.s-card.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.card-head { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.card-head .name { flex: 1 1 auto; min-width: 0; font-weight: 600; }
.card-head .sum { flex: 0 0 auto; color: var(--subtle); font-size: var(--fs-12); }
/* 链 chips: 换行铺排, 超高卡内滚 (整条高度可预测, 不被长链撑爆) */
.chain { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px;
  overflow-y: auto; min-height: 0; align-content: flex-start; counter-reset: step; }
.chain li { display: flex; min-width: 0; }
.chip-op { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; padding: 2px 8px;
  border: 1px solid var(--border); background: var(--surface-2); border-radius: 999px;
  cursor: pointer; font-size: var(--fs-12); color: var(--text); counter-increment: step; }
.chip-op::before { content: counter(step) '.'; color: var(--subtle); font-size: var(--fs-11); }
.chip-op:hover { background: var(--hover); border-color: var(--accent); }
.chip-op .cl { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-op .badge { color: var(--subtle); font-size: var(--fs-11); }
.empty-chain { color: var(--subtle); font-size: var(--fs-12); padding: 2px 0; }
.s-add { flex: 0 0 110px; display: flex; align-items: center; justify-content: center;
  border: 1px dashed var(--border); border-radius: 8px; background: transparent; cursor: pointer;
  color: var(--subtle); font-size: var(--fs-13); }
.s-add:hover { border-color: var(--accent); color: var(--accent); background: var(--hover); }
.strip-empty { flex: 1; display: flex; align-items: center; margin: 0; padding: 8px;
  color: var(--muted); font-size: var(--fs-13); }
</style>
