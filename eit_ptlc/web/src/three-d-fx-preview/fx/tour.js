/**
 * 功能: 巡检模式 —— 相机自动逐工位运镜, 每站用**该工位的定制视角**(第四轮:
 * focus 内部走 applyStationView, 与点击聚焦同机位) + 聚焦联动 + 停留数秒循环.
 * 适合展会/参观时的无人值守展示.
 *
 * 路线(第四轮): cfg.tour.route 空串 = 按世界 X 左→右全工位(含无遥测的视觉定位等,
 * 幽灵透视照样有展示价值); 非空 = 逗号分隔工位 id 串. manifest 声明序≠空间序,
 * 旧"声明序"路线会让相机左右横跳, 已废.
 *
 * 用户一动相机(camera-controls 的 controlstart)立即让位停巡检 —— 展示模式
 * 永远不和人抢相机(程序化 setLookAt 不触发 controlstart, 不会自锁).
 */

/**
 * 功能: 创建巡检器.
 * @param {object} ctx 沙盒上下文
 * @param {object} deps { focusApi }
 * @returns {object} 特效实例(另暴露 start/stop/toggle/tourStep/isRunning)
 */
export function createTour(ctx, deps) {
  const cfg = ctx.config.tour
  const { focusApi } = deps
  const byX = ctx.stationListByX.map((s) => s.id)
  const route = cfg.route
    ? String(cfg.route).split(',').map((s) => s.trim()).filter((id) => ctx.stations.has(id))
    : byX
  if (!route.length) route.push(...byX)

  let running = false
  let index = 0
  let timer = 0

  function step(i, instant = false) {
    index = ((i % route.length) + route.length) % route.length
    const id = route[index]
    // instant 与实播同一机位(focus 内部 applyStationView) —— 截图定格与运行一致
    focusApi.focus(id, instant ? { instant: true } : {})
    timer = cfg.flyS + cfg.dwellS
  }

  function stop() {
    if (!running) return
    running = false
    focusApi.blur()
    ctx.events.emit('tour', false)
  }

  const onUserControl = () => stop()
  ctx.controls.addEventListener('controlstart', onUserControl)

  return {
    name: 'tour',
    isRunning: () => running,

    start() {
      if (running) return
      running = true
      ctx.events.emit('tour', true)
      step(0)
    },
    stop,
    toggle() {
      if (running) stop()
      else this.start()
    },

    /**
     * 功能: 直接跳到第 i 站(无过渡, 截图定格用; 不启动自动推进).
     * @param {number} i 站序号(按有遥测工位的 manifest 声明序)
     * @returns {string} 该站工位 id
     */
    tourStep(i) {
      running = false
      step(i, true)
      return route[index]
    },

    update(dt) {
      if (!running) return
      timer -= dt
      if (timer <= 0) step(index + 1)
    },

    setStationState() {},
    setEnabled(on) {
      if (!on) stop()
    },
    setParams() {},

    dispose() {
      stop()
      ctx.controls.removeEventListener('controlstart', onUserControl)
    },
  }
}
