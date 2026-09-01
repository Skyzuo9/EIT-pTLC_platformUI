/**
 * 功能: 实时页的单点(手动)会话 —— **整页一份**, 由 TwinView 实例化, 各工位「操作」页共用.
 *
 * 为什么必须上提到页面级 (旧实现是 ManualControlPanel 自己持有):
 *   ① 切工位页签不能 exit()+enter() —— 那是每点一下就掉一次 PLC 单点闩锁再重拿;
 *   ② 5s 的 /api/mode 轮询跑一份而不是每个面板一份。**顺带修掉一个既有 bug**:
 *      旧 StationPanel 只在 onMounted 拉一次 mode, 操作员中途切 RUN↔DEBUG 后
 *      它的模式门就一直是陈的;
 *   ③ blur / visibilitychange → jogStop 的监听注册一次;
 *   ④ onBeforeUnmount → exit() 属于页面, 与后端 3.5s 看门狗对齐.
 *
 * 纪律: **永不隐式 enter()**。进入单点模式始终是用户点会话条的显式动作 ——
 * 页面一挂载就抢 PLC 闩锁是不能接受的。
 */
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'

import { confirmAction } from '../../composables/confirmService.js'
import { fetchMode } from './api.js'
import { ManualSession } from './manualApi.js'

const MODE_POLL_MS = 5000

/**
 * 功能: 建立页面级单点会话.
 * @returns {object} 会话状态与动作
 */
export function useManualSession() {
  const session = shallowRef(/** @type {ManualSession|null} */ (null))
  const sessionState = ref({ state: 'idle', reason: '', jogging: null })
  const mode = ref('')
  /** /api/mode 请求本身失败(后端未连), 与"在线但非 DEBUG"分开提示 */
  const modeOffline = ref(false)
  const message = ref('')

  let modeTimer = null

  const modeAllowed = computed(() => mode.value === 'DEBUG')
  const active = computed(() => sessionState.value.state === 'active')
  const canWrite = computed(() => modeAllowed.value && active.value)

  /** 模式门没过时的原因文案(两种成因分开说, 否则现场会去查错方向) */
  const gateReason = computed(() => {
    if (modeAllowed.value) return ''
    return modeOffline.value
      ? '无法连接上位机(/api/mode 请求失败): 操作区置灰。请确认后端已启动。'
      : '非 DEBUG 模式: 操作区置灰。请在上位机顶栏切到调试模式后重试。'
  })

  /**
   * 功能: 会话开关(进入/退出手动控制模式).
   *
   * 进入前有一道 danger-ack: 手动控制放开的是直驱现场机构的控件, 且三维画面与实机
   * 存在误差(位姿插值/建模偏差), 操作员必须被明确告知"以现场实机为准"。
   * 本函数是全仓唯一的 enter() 调用点(工位操作页的模块状态区与工站信息页的整机
   * 操作段共用), 弹窗插在这里即覆盖全部入口。
   * @returns {Promise<void>} 完成
   */
  async function toggle() {
    message.value = ''
    if (active.value) {
      await session.value?.exit()
      message.value = '已退出手动控制'
      return
    }
    const acked = await confirmAction({
      level: 'danger-ack',
      title: '进入手动控制',
      message: [
        '手动控制将直接驱动现场机构, 请谨慎操作。',
        '三维画面与实机存在误差, 请以现场实机为准, 边看设备边操作。',
      ],
      ackText: '我已知晓, 将对照实机操作',
      confirmText: '进入',
    })
    if (!acked) return
    const ok = await session.value?.enter()
    message.value = ok ? '已进入手动控制(心跳 1s)' : `进入失败: ${sessionState.value.reason}`
  }

  /**
   * 功能: 按住点动起.
   * @param {string} axisId 轴 id
   * @param {'pos'|'neg'} direction 方向
   * @returns {void}
   */
  function jogStart(axisId, direction) {
    if (!canWrite.value) return
    session.value?.jogStart(axisId, direction)
  }

  /** 功能: 松开点动(松手/移出/取消任一都调, 是 jog 安全模型的一半). */
  function jogStop() {
    session.value?.jogStop()
  }

  async function pollMode() {
    try {
      const payload = await fetchMode()
      mode.value = payload?.mode || ''
      modeOffline.value = false
    } catch {
      mode.value = ''
      modeOffline.value = true
    }
  }

  function onVisibility() {
    // 页签隐藏 → 停 jog(会话保留, 心跳继续; 隐藏超 3.5s 后端自会清扫)
    if (document.hidden) jogStop()
  }

  onMounted(async () => {
    session.value = new ManualSession({
      onChange: (state) => {
        sessionState.value = state
      },
    })
    await pollMode()
    modeTimer = setInterval(pollMode, MODE_POLL_MS)
    window.addEventListener('blur', jogStop)
    document.addEventListener('visibilitychange', onVisibility)
  })

  onBeforeUnmount(() => {
    clearInterval(modeTimer)
    window.removeEventListener('blur', jogStop)
    document.removeEventListener('visibilitychange', onVisibility)
    // 主动退是纪律 —— 不退的话后端 3.5s 看门狗会兜底, 但那是兜底不是设计
    session.value?.exit()
  })

  return {
    session, sessionState, mode, modeOffline, message,
    modeAllowed, active, canWrite, gateReason,
    toggle, jogStart, jogStop,
  }
}
