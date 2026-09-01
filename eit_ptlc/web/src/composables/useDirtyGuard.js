// 未保存改动守卫 (路由 update/leave + beforeunload 三口全拦)
// ============================================================
// 以 ActionDetail 原有的三段守卫为模板抽出; PLC POU/点位 YAML/流程脚本/视觉参数
// 这些编辑成本最高的内容此前全部裸奔 (切走即静默丢弃)。
//
// 行为:
//   - 路由离开: 脏时弹 confirmAction (normal 级), 确认"放弃修改"才放行。
//   - 同路由参数变化 (如 /library/flow/:name 切另一个流程): 传 paramKey 才拦,
//     只在该 param 实际变化时提示; query 变化 (useQuerySync 的 replace) 永不拦。
//   - beforeunload (刷新/关标签): 保持浏览器原生提示 —— 这是全案唯一不走自建
//     对话的确认: unload 时序里自建弹窗来不及渲染, 原生同步机制是唯一可靠路径。
import { onBeforeUnmount, onMounted, unref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { confirmAction } from './confirmService.js'

/**
 * @param {import('vue').Ref<boolean>|Function} isDirty 脏判据 (ref 或 () => boolean)
 * @param {object} [opts]
 * @param {string} [opts.message] 提示文案
 * @param {string} [opts.paramKey] 同路由下标识"当前文档"的 route param 名 (如 'name');
 *     不传则同路由 update 一律放行
 * @returns {{ confirmDiscard: (msg?: string) => Promise<boolean> }} 页内切换 (tab/面板) 复用
 */
export function useDirtyGuard(isDirty, { message = '当前有未保存修改, 离开将丢弃。', paramKey = null } = {}) {
  const dirty = () => (typeof isDirty === 'function' ? !!isDirty() : !!unref(isDirty))

  async function confirmDiscard(msg) {
    if (!dirty()) return true
    return confirmAction({
      title: '放弃未保存修改?',
      message: msg || message,
      confirmText: '放弃修改',
      cancelText: '继续编辑',
    })
  }

  onBeforeRouteUpdate(async (to, from) => {
    if (!paramKey) return true
    if (to.params[paramKey] === from.params[paramKey]) return true
    return confirmDiscard()
  })

  onBeforeRouteLeave(async () => confirmDiscard())

  function onBeforeUnload(e) {
    if (!dirty()) return
    e.preventDefault()
    e.returnValue = '' // Chromium 系需要赋值才弹原生提示
  }

  onMounted(() => window.addEventListener('beforeunload', onBeforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', onBeforeUnload))

  return { confirmDiscard }
}
