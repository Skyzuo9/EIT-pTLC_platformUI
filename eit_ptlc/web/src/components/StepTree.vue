<script setup>
// 步骤树 (递归): 实时监视与历史回放共用. 入参 steps 为嵌套 [{step_id, script, op, action, status, message, result, children}]。
// run_script 步的子脚本步骤挂在 children 下缩进渲染; 运行中步行级高亮 (变黄) + 根实例自动滚动跟随最深活动叶子。
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  depth: { type: Number, default: 0 },
})

const root = ref(null)

// 最深运行中叶子的定位串 (script|aid): 变化即触发滚动; 无运行中叶子则空串。
// 尾向反走 + 命中即返: 运行中叶子几乎总在树尾部, 反走只触碰尾段节点;
// 逆文档序第一个 ≡ 文档序最后一个, 语义与正走全遍历版等价 (候选判据不变:
// children 非空只递归、叶才候选)。watch 依赖随之收窄到尾段 —— 凡能改变结果的
// 变更 (命中叶转终态/尾部追加/命中叶生子) 仍必然触发重算。
function runningKey(steps) {
  const walk = (arr) => {
    for (let i = arr.length - 1; i >= 0; i--) {
      const s = arr[i]
      if (s.children && s.children.length) {
        const hit = walk(s.children)
        if (hit) return hit
      } else if (s.status === 'RUNNING') {
        return `${s.script}|${s.step_id}`
      }
    }
    return ''
  }
  return walk(steps || [])
}

// 自动滚动仅根实例 (depth 0) 负责: 步骤推进即把最深运行中叶子滚入视野, 让高亮跟随执行 (含子脚本内部)。
if (props.depth === 0) {
  watch(() => runningKey(props.steps), (key) => {
    if (!key) return
    nextTick(() => {
      const box = root.value
      if (!box) return
      const marks = box.querySelectorAll('[data-running="1"]')
      const last = marks[marks.length - 1]   // DOM 序最后 = 最深活动叶子
      if (last) last.scrollIntoView({ block: 'nearest' })
    })
  })
}
</script>

<template>
  <p v-if="!steps.length && depth === 0" class="empty">无步骤</p>
  <ol v-else class="steps" ref="root">
    <li v-for="s in steps" :key="`${s.script}|${s.step_id}`" :class="s.status">
      <div class="step-row"
           :data-running="s.status === 'RUNNING' && !(s.children && s.children.length) ? '1' : null">
        <span class="dot" />
        <span class="step-main">
          <span class="step-title">{{ s.step_id }} — {{ s.action }}</span>
          <span v-if="s.message" class="step-message">{{ s.message }}</span>
        </span>
        <span class="st">{{ s.status || '待执行' }}</span>
      </div>
      <StepTree v-if="s.children && s.children.length" :steps="s.children" :depth="depth + 1" />
    </li>
  </ol>
</template>
