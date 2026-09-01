// 伺服轴「按住点动」—— 三层防卡死的第一层
// ================================================
// OPC UA 写进去的是**电平**不是脉冲: 前端若在轴点动时崩溃/切走, PLC 侧不会自己松开。
// 三层分别是 前端(本模块) / 后端 jog 续订窗口 0.8s / PLC 的 3s 心跳看门狗,
// 详见 docs/单点控制_PC_Manual_Mode.md §3。
//
// 抽成 composable 是因为工位单点面板与孔板标定面板都要按住点动, 而这段逻辑里有三条
// 用事故换来的不变量, 复制一份就等于把踩坑机会也复制一份:
//
//  1. **代次令牌 jogSeq** —— jogDown 里那个 await 是个竞态窗口: 快速点一下时
//     pointerup → stopJog() 会在 await 期间整个跑完, 若不作废这次 jogDown, 它恢复执行后
//     还会装上续订器, 而那时 jogging 已空, 再没有任何路径会去停它 (踩过: 定时器跨页面
//     永生, 一直刷 409)。
//  2. **pointer capture** —— 指针滑出按钮也要能收到 up; 释放要包 try/catch (元素已失活
//     时 releasePointerCapture 会抛)。
//  3. **keeper 的单定时器不变量** —— 见 utils/jogKeeper.js 顶部注释。
//
// 窗口级安全停 (visibilitychange / blur / pagehide) 与卸载清理都在本模块内注册,
// 调用方不需要 (也不应该) 再抄一遍。
// 相对导入写全 .js: 本模块被 tests/axis-jog.test.js 用裸 node --test 直接加载,
// 而 node 的 ESM 不做扩展名补全 (Vite 会)。
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errText } from '../api.js'
import { createJogKeeper } from '../utils/jogKeeper.js'

const KEEP_PERIOD_MS = 300 // 后端续订窗口 0.8s, 300ms 续一次留足两拍余量

/**
 * @param {object}   opts
 * @param {import('vue').Ref<boolean>} opts.canDrive 可下发判据 (通常是 DEBUG && PC_Manual_Active)
 * @param {Function} [opts.onError] (message: string) => void, 点动起步失败时回调
 */
export function useAxisJog({ canDrive, onError } = {}) {
  const jogging = ref('') // 当前点动中的 axisId ('' = 无)
  const keeper = createJogKeeper() // 内部保证任何时刻最多一个定时器
  const pointerId = ref(null)
  const pointerEl = ref(null)
  let jogSeq = 0

  function releasePointer() {
    const el = pointerEl.value
    const id = pointerId.value
    if (el !== null && id !== null) {
      try {
        if (el.hasPointerCapture(id)) el.releasePointerCapture(id)
      } catch (_e) {
        // 元素已失活时释放可能抛错, 忽略
      }
    }
    pointerId.value = null
    pointerEl.value = null
  }

  async function jogDown(axis, direction, event) {
    if (canDrive && !canDrive.value) return
    event.preventDefault()
    const el = event.currentTarget
    try {
      el.setPointerCapture(event.pointerId)
      pointerId.value = event.pointerId
      pointerEl.value = el
    } catch (_e) {
      // 某些浏览器场景无法捕获, 忽略
    }
    const seq = ++jogSeq
    jogging.value = axis.id
    try {
      await api.pcManualJogStart(axis.id, direction)
    } catch (e) {
      if (seq === jogSeq) jogging.value = ''
      if (onError) onError(`${axis.label} 点动失败: ${errText(e)}`)
      return
    }
    if (seq !== jogSeq) {
      // await 期间已经松手了: 不装续订器, 补一次停止把轴收干净
      api.pcManualJogStop(axis.id).catch(() => {})
      return
    }
    keeper.start(axis.id, (id) => api.pcManualJogKeep(id), KEEP_PERIOD_MS)
  }

  async function stopJog() {
    jogSeq += 1 // 作废在途的 jogDown, 免得它回来又装上续订器
    keeper.stop()
    releasePointer()
    const id = jogging.value
    if (!id) return
    jogging.value = ''
    try {
      await api.pcManualJogStop(id)
    } catch (_e) {
      // 松开失败不覆盖既有结果; 后端与 PLC 两层看门狗兜底
    }
  }

  function safetyStop() {
    if (jogging.value) stopJog()
  }

  function onVisibilityChange() {
    if (document.hidden) safetyStop()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener('blur', safetyStop)
    window.addEventListener('pagehide', safetyStop)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    window.removeEventListener('blur', safetyStop)
    window.removeEventListener('pagehide', safetyStop)
    safetyStop()
    keeper.stop() // 无条件停: 不能指望 jogging 非空 (它可能已被置空而定时器还活着)
  })

  return { jogging, jogDown, stopJog, safetyStop }
}
