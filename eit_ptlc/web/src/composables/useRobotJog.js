/**
 * 功能: 机械臂点动的状态机 —— 连续(按住起/松手停) + 步进(单次增量) + 四路安全停.
 *
 * 由 components/RobotJogPanel.vue 原样抽出, **行为逐字不变**。抽出的理由是三维实时页的
 * 机械臂工位也要一套点动面板: 安全停这种东西不该存在两份实现, 改一处忘另一处的代价是
 * 机械臂在页面切走后继续走。
 *
 * 抽的是**逻辑不是 UI**: 轴行表、按钮布局、样式都留在各自的组件里, 这里只管
 * "按下去发什么、松开发什么、什么情况下必须停"。
 *
 * ⚠ 与 composables/useAxisJog.js 是**两套并行且已定案不合并**的东西(见 RobotJogPanel
 *   原注释): PLC 轴走 (axis, dir) + keepalive 续订; 机器人走 jogStart(token) 令牌模型,
 *   没有 keepalive, 且多一条步进分支。别去"统一"它们。
 *
 * 四路安全停缺一不可, 每一路都堵一种真实的走失:
 *   visibilitychange  切浏览器标签页 —— 指针事件不再来, 松手事件永远等不到
 *   blur              切到别的窗口 —— 同上
 *   pagehide          关标签页 / 前进后退缓存
 *   onBeforeUnmount   路由切走(三维页切页签就是这一条)
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import { announce } from './announcer.js'

/** 步进按下后视觉高亮的保持时长(毫秒) —— 步进无明确结束回包, 只能定时清 */
const STEP_HIGHLIGHT_MS = 200

/**
 * 功能: 建立机械臂点动会话.
 * @param {object} api 点动通道 {jogStart(token), jogStop(), step(axis, distance, motion)}
 * @param {object} [options] 选项
 * @param {(result: object) => void} [options.onResult] 每次下发后的回显(ActionResult 或错误壳)
 * @param {(err: Error) => string} [options.errText] 异常转文案
 * @returns {object} 状态与动作
 */
export function useRobotJog(api, { onResult = null, errText = (e) => String(e?.message || e) } = {}) {
  /** 'continuous' | 'step' */
  const mode = ref('continuous')
  /** 步进步长: 平移 mm / 旋转与关节 deg(对齐控制器的 step_distance_mm / step_angle_deg) */
  const stepMm = ref(1.0)
  const stepDeg = ref(1.0)
  /** 当前高亮的方向令牌(如 X+ / J1-); 空串表示没在动 */
  const activeDir = ref('')

  // 指针捕获态: 按住起、松开停, 捕获后指针移出按钮也仍算在按
  const activePointerId = ref(null)
  const activeElement = ref(null)

  const report = (value) => { onResult?.(value) }

  /**
   * 功能: 该令牌是不是当前正在动的方向(按钮高亮用).
   * @param {string} token 方向令牌
   * @returns {boolean} 是否高亮
   */
  function isActive(token) {
    return activeDir.value === token
  }

  function capturePointer(event) {
    const element = event.currentTarget
    if (element !== null) {
      try {
        element.setPointerCapture(event.pointerId)
      } catch (_e) {
        // 某些浏览器场景无法捕获, 忽略即可
      }
    }
    activePointerId.value = event.pointerId
    activeElement.value = element
  }

  function releasePointer() {
    const element = activeElement.value
    const pointerId = activePointerId.value
    if (element !== null && pointerId !== null) {
      try {
        if (element.hasPointerCapture(pointerId)) {
          element.releasePointerCapture(pointerId)
        }
      } catch (_e) {
        // 元素已失活时释放可能抛错, 忽略即可
      }
    }
    activePointerId.value = null
    activeElement.value = null
  }

  function isSamePointer(event) {
    return activePointerId.value === null || activePointerId.value === event.pointerId
  }

  /**
   * 功能: 按住起 —— 连续点动.
   * @param {string} token 方向令牌(如 'X+')
   * @param {PointerEvent} event 指针事件
   * @returns {Promise<void>} 完成
   */
  async function pressContinuous(token, event) {
    if (mode.value !== 'continuous') {
      return
    }
    event.preventDefault()
    capturePointer(event)
    const previous = activeDir.value
    activeDir.value = token
    try {
      // 换向: 已有方向先停再起, 保持后到者胜语义
      if (previous !== '' && previous !== token) {
        await api.jogStop()
      }
      report(await api.jogStart(token))
    } catch (e) {
      report({ status: 'ERROR', message: errText(e) })
    }
  }

  /**
   * 功能: 停连续点动(松手 / 安全停共用这一条).
   * @returns {Promise<void>} 完成
   */
  async function stopContinuous() {
    releasePointer()
    if (activeDir.value === '') {
      return
    }
    activeDir.value = ''
    try {
      await api.jogStop()
    } catch (_e) {
      // 松开停止失败不覆盖现有结果
    }
  }

  /**
   * 功能: 松开 / 移出 / 取消 —— 只认按下时那个指针.
   * @param {PointerEvent} event 指针事件
   * @returns {void}
   */
  function releaseContinuous(event) {
    if (mode.value !== 'continuous' || isSamePointer(event) === false) {
      return
    }
    stopContinuous()
  }

  /**
   * 功能: 步进一格(方向由 distance 的符号编码).
   * @param {object} row 轴行 {axis, kind}
   * @param {number} sign 方向(+1/-1)
   * @param {MouseEvent} [event] 点击事件(用 detail===0 认键盘激活)
   * @returns {Promise<void>} 完成
   */
  async function pressStep(row, sign, event) {
    if (mode.value !== 'step') {
      // 连续模式下按住/松开走 pointer 事件, click 静默失效会让键盘用户毫无反馈;
      // 只对键盘激活 (click.detail===0) 播报替代路径, 鼠标松开触发的 click 不刷屏
      if (!event || event.detail === 0) {
        announce('连续点动仅支持按住鼠标/触控; 键盘请切换到步进模式')
      }
      return
    }
    const token = row.axis + (sign > 0 ? '+' : '-')
    activeDir.value = token
    const distance = sign * (row.kind === 'translate' ? stepMm.value : stepDeg.value)
    const motion = row.kind === 'joint' ? 'j' : 'l'
    try {
      report(await api.step(row.axis, distance, motion))
    } catch (e) {
      report({ status: 'ERROR', message: errText(e) })
    } finally {
      // 步进无明确结束回包, 定时清视觉高亮
      window.setTimeout(() => {
        if (activeDir.value === token) {
          activeDir.value = ''
        }
      }, STEP_HIGHLIGHT_MS)
    }
  }

  /** 功能: 安全停 —— 仍在点动才发, 免得对着没在动的机器人空发 jogStop. */
  function safetyStop() {
    if (activeDir.value !== '') {
      stopContinuous()
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      safetyStop()
    }
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
    if (activeDir.value !== '') {
      try {
        api.jogStop()
      } catch (_e) {
        // 卸载兜底, 忽略
      }
    }
    releasePointer()
  })

  return {
    mode, stepMm, stepDeg, activeDir,
    isActive, pressContinuous, releaseContinuous, stopContinuous, pressStep, safetyStop,
  }
}
