// 确认/录入对话服务 (取代 window.confirm / window.alert / window.prompt)
// ========================================================================
// 为什么要换: 原生 confirm 会阻塞主线程 (WS 事件积压)、深色主题下弹系统浅色框、
// 且浏览器"阻止此页面显示更多对话框"复选框能一次性静默掉全部安全确认 ——
// 对承担机器人使能/PLC 写入/整板清空的确认闸门, 这是实质安全缺口。
//
// 用法与原生同构, 逐行等价替换 (调用方法补 async 即可):
//   if (!(await confirmAction({ title: '删除流程', message: '不可恢复。', level: 'danger',
//     confirmText: '删除' }))) return
//
// 分级 (定案, 勿自行发挥):
//   normal      放弃未保存/切换丢草稿          — 中性视觉
//   danger      删除/覆盖/终止/执行硬件动作     — 实底红确认键 + 后果文案
//   danger-ack  写标定盘/写 PLC/SSH 停服务/释放急停/快换松开 — 追加强制勾选, 可带 probe 在线探测
//   ** 急停触发永不确认 —— 急停路径上不许出现任何对话框; 需要 ack 的是反方向的"释放急停"。
//
// 不变量:
//   1. 同一时刻至多一个对话; 已开时新请求立即按"取消"收口并 assertive 播报,
//      绝不排队 (排队意味着确认可能在语境失效后才弹出, 安全场景不可接受)。
//   2. level != 'normal' 时初始焦点落在"取消"键 (Enter 不会误确认危险操作)。
//   3. Esc 恒等于取消; 遮罩点击不关闭。
//   4. promise 永不 reject; ConfirmHost 卸载时按取消收口。
import { shallowRef } from 'vue'
import { announce } from './announcer.js'

// 当前对话请求 (ConfirmHost 消费); null = 无对话
const current = shallowRef(null)

let seq = 0

function open(req) {
  if (current.value) {
    announce('已有待确认操作, 请先处理当前对话', { assertive: true })
    return null
  }
  req.id = ++seq
  current.value = req
  return req
}

/**
 * 功能:
 *     弹出确认对话 (模态)。
 * 参数:
 *     opts.title       字符串, 必填, 短句动词开头 (如 '删除流程 xxx')
 *     opts.message     字符串或字符串数组, 后果文案 (多行传数组)
 *     opts.detail      字符串, 可选, mono 小字补充 (目标路径/设备名/坐标)
 *     opts.level       'normal' | 'danger' | 'danger-ack', 默认 'normal'
 *     opts.ackText     字符串, level='danger-ack' 必填, 勾选框文案
 *     opts.confirmText 字符串, 确认键文案, 默认 '确认' (尽量传具体动词: '删除'/'执行')
 *     opts.cancelText  字符串, 取消键文案, 默认 '取消'
 *     opts.probe       可选 async () => ({ ok: boolean, text: string }), 打开即执行的
 *                      在线探测, 结果行显示在对话内; 探测失败只展示不拦截
 * 返回:
 *     Promise<boolean> — true 确认 / false 取消 (含被顶替、宿主卸载)
 */
export function confirmAction(opts) {
  return new Promise((resolve) => {
    const req = open({
      kind: 'confirm',
      title: opts.title || '确认操作',
      message: Array.isArray(opts.message) ? opts.message : opts.message ? [opts.message] : [],
      detail: opts.detail || '',
      level: opts.level || 'normal',
      ackText: opts.ackText || '',
      confirmText: opts.confirmText || '确认',
      cancelText: opts.cancelText || '取消',
      probe: opts.probe || null,
      settle(result) {
        if (current.value && current.value.id === this.id) current.value = null
        resolve(!!result)
      },
    })
    if (!req) resolve(false)
  })
}

/**
 * 功能:
 *     弹出单行文本录入对话 (取代 window.prompt)。
 * 参数:
 *     opts.title / opts.message / opts.placeholder / opts.initial 见名知义
 *     opts.validate 可选 (value) => string, 返回非空错误文案则拦下确认
 * 返回:
 *     Promise<string|null> — 输入值 / null 取消
 */
export function promptAction(opts) {
  return new Promise((resolve) => {
    const req = open({
      kind: 'prompt',
      title: opts.title || '请输入',
      message: Array.isArray(opts.message) ? opts.message : opts.message ? [opts.message] : [],
      detail: '',
      level: 'normal',
      ackText: '',
      confirmText: opts.confirmText || '确定',
      cancelText: opts.cancelText || '取消',
      probe: null,
      initial: opts.initial || '',
      placeholder: opts.placeholder || '',
      validate: opts.validate || null,
      settle(result) {
        if (current.value && current.value.id === this.id) current.value = null
        resolve(typeof result === 'string' ? result : null)
      },
    })
    if (!req) resolve(null)
  })
}

export { current }
