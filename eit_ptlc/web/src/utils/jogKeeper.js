// 按住点动的续订器 (jog keep-alive)
// ------------------------------------------------------------------
// 后端给点动开了个 0.8s 的续订窗口, 前端按住期间要周期续订; 松手/失败/组件卸载都必须
// 把定时器停干净。
//
// 单独抽成模块并注入 setInterval/clearInterval, 是因为这里踩过一次坑: 原来直接
// `jogKeeper = setInterval(...)`, 一旦在旧定时器还活着时再赋值, 旧句柄就丢了 ——
// 那个定时器再没有任何代码路径能停它, SPA 又不整页刷新, 于是它跨页面一直发请求。
// 这里的不变量是: **任何时刻最多一个定时器, 且它的句柄一定在 handle 里**。
// start() 内部无条件先 stop(), 就是为了钉死这条。

export function createJogKeeper(timers = {}) {
  const setTimer = timers.setInterval || ((fn, ms) => setInterval(fn, ms))
  const clearTimer = timers.clearInterval || ((h) => clearInterval(h))

  let handle = null
  let current = ''

  function stop() {
    if (handle !== null) {
      clearTimer(handle)
      handle = null
    }
    current = ''
  }

  /**
   * 起一个续订循环。
   * @param {string} id     轴 id (仅供 isRunning/调试识别)
   * @param {Function} onTick 每拍调用, 返回 Promise; reject 即视为续订失败
   * @param {number} periodMs 续订间隔
   */
  function start(id, onTick, periodMs = 300) {
    stop()   // 不变量: 起新的之前旧的必须已经死透
    current = id
    handle = setTimer(() => {
      let ret
      try {
        ret = onTick(id)
      } catch (_e) {
        stop()
        return
      }
      // 续订失败多半是会话已被后端收走; 再发也只会刷 409, 直接收摊
      if (ret && typeof ret.catch === 'function') {
        ret.catch(() => stop())
      }
    }, periodMs)
  }

  const isRunning = () => handle !== null
  const runningId = () => current

  return { start, stop, isRunning, runningId }
}
